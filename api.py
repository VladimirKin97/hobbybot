import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from fastapi.staticfiles import StaticFiles
import httpx
import os

# Імпорти для Телеграм кнопок
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.web_app_info import WebAppInfo

import database
from main import bot, dp, ActivityMiddleware, reminders_loop, finish_events_loop

# === СТРУКТУРИ ДАНИХ (MODELS) ===
class ProfileUpdate(BaseModel):
    telegram_id: int
    name: str
    bio: str
    interests: str
    photo: str

class EventCreate(BaseModel):
    user_id: int
    creator_name: Optional[str] = None
    title: str
    description: str
    additional_info: Optional[str] = None
    date: datetime
    location: str
    location_lat: float
    location_lon: float
    capacity: int
    needed_count: int  
    photo: Optional[str] = None
    is_address_public: bool = False

class JoinRequest(BaseModel):
    event_id: int
    user_id: int
    message: Optional[str] = None
    user_photo: Optional[str] = None
    user_name: Optional[str] = None
    username: Optional[str] = None

class ContactUserRequest(BaseModel):
    user_id: int
    target_id: int

class UpdateRequestStatus(BaseModel):
    event_id: int
    seeker_id: int
    status: str

class LeaveRequest(BaseModel):
    user_id: int

class KickRequest(BaseModel):
    user_id: int
    seeker_id: int
    
class SyncRequest(BaseModel):
    user_id: int
    username: Optional[str] = None
    name: Optional[str] = None
    photo: Optional[str] = None

class EventEdit(BaseModel):
    user_id: int
    title: str
    description: str
    capacity: int
    needed_count: int

# === ЖИТТЄВИЙ ЦИКЛ ДОДАТКУ ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запускаємо FastAPI...")
    await database.init_db_pool()
    
    # Авто-миграция
    async with database.db_pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")
        except:
            pass
    
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    
    asyncio.create_task(reminders_loop())
    asyncio.create_task(finish_events_loop())
    
    print("🤖 Піднімаємо Телеграм-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    bot_task = asyncio.create_task(dp.start_polling(bot))
    
    yield 
    
    print("🛑 Вимикаємо сервер, зупиняємо бота...")
    bot_task.cancel()

# === ІНІЦІАЛІЗАЦІЯ ДОДАТКУ ===
app = FastAPI(title="Findsy TMA API", lifespan=lifespan)

app.mount("/img", StaticFiles(directory="img"), name="img")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

# === МАРШРУТИ ===

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main_screen.html", {"request": request})

@app.get("/api/profile/{user_id}")
async def get_user_profile(user_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                SELECT name, city, interests, bio, photo 
                FROM users 
                WHERE telegram_id = $1
            """, user_id)
            
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
                
            user_data = dict(row)
            user_data['organized_count'] = 0
            user_data['participated_count'] = 0
            return user_data
        except Exception as e:
            print(f"Помилка БД: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/profile/update")
async def update_profile(data: ProfileUpdate):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            await conn.execute("""
                UPDATE users 
                SET name = $1, bio = $2, interests = $3, photo = $4
                WHERE telegram_id = $5
            """, data.name, data.bio, data.interests, data.photo, data.telegram_id)
            return {"success": True}
        except Exception as e:
            print(f"Помилка оновлення профілю: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/create")
async def create_event(event: EventCreate):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            event_id = await conn.fetchval("""
                INSERT INTO events (
                    user_id, creator_name, title, description, additional_info, 
                    date, location, location_lat, location_lon, 
                    capacity, needed_count, status, photo, is_address_public, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'active', $12, $13, NOW()
                ) RETURNING id
            """, 
            event.user_id, 
            event.creator_name, 
            event.title, 
            event.description, 
            event.additional_info, 
            event.date, 
            event.location, 
            event.location_lat, 
            event.location_lon,
            event.capacity, 
            event.needed_count,     
            event.photo,
            event.is_address_public)
            
            return {"success": True, "event_id": event_id}
        except Exception as e:
            print(f"Помилка створення івенту: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events")
async def get_events():
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT id, title, description, date, location, location_lat, location_lon, capacity, needed_count, photo, creator_name, is_address_public 
                FROM events 
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            events_list = []
            for row in rows:
                event_dict = dict(row)
                if event_dict['date']:
                    event_dict['date'] = event_dict['date'].isoformat()
                
                # МАСКУЄМО АДРЕСУ ДЛЯ РАНДОМНИХ ЮЗЕРІВ В СТРІЧЦІ
                if not event_dict.get('is_address_public'):
                    city = event_dict['location'].split(',')[0]
                    event_dict['location'] = f"{city} (Точна адреса після підтвердження)"
                    
                events_list.append(event_dict)
            return events_list
        except Exception as e:
            print(f"Помилка завантаження івентів: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# === ОТРИМАТИ ОДИН ІВЕНТ ЗА ID ===
@app.get("/api/events/{event_id}")
async def get_single_event(event_id: int, user_id: int = 0):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
    SELECT e.*, u.username as creator_username 
    FROM events e 
    LEFT JOIN users u ON e.user_id = u.telegram_id 
    WHERE e.id = $1
""", event_id)
            if not row:
                raise HTTPException(status_code=404, detail="Івент не знайдено")
            
            event_dict = dict(row)
            if event_dict.get('date'):
                event_dict['date'] = event_dict['date'].isoformat()
            if event_dict.get('created_at'):
                event_dict['created_at'] = event_dict['created_at'].isoformat()
                
            # Перевіряємо чи юзер подав заявку
            if user_id > 0:
                req = await conn.fetchrow("SELECT status FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, user_id)
                if req:
                    event_dict['my_request_status'] = req['status'] # 'pending' або 'approved'
            
            # МАСКУЄМО АДРЕСУ ДЛЯ НЕПІДТВЕРДЖЕНИХ ЮЗЕРІВ
            is_owner = (user_id == event_dict['user_id'])
            is_approved = (event_dict.get('my_request_status') == 'approved')
            
            if not event_dict.get('is_address_public') and not is_owner and not is_approved:
                city = event_dict['location'].split(',')[0]
                event_dict['location'] = f"{city} (Точна адреса після підтвердження)"
                    
            return event_dict
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# === ФОНОВІ ФУНКЦІЇ ПУШІВ ===
async def send_new_request_push(event_id: int, seeker_id: int, user_message: str = None):
    await asyncio.sleep(1) 
    if not database.db_pool: return
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", event_id)
            seeker = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", seeker_id)
            if event and seeker:
                msg = f"🔔 *Нова заявка!*\n\n*{seeker['name'] or 'Хтось'}* хоче долучитися до «_{event['title']}_».\n"
                if user_message: 
                    msg += f"\n💬 *Повідомлення:* \"{user_message}\"\n"
                domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
                web_app_url = f"https://{domain}/my_events.html" if domain else "https://ТВІЙ_ДОМЕН.up.railway.app/my_events.html"
                markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎯 Переглянути заявку", web_app=WebAppInfo(url=web_app_url))]])
                await bot.send_message(chat_id=event['user_id'], text=msg, parse_mode="Markdown", reply_markup=markup)
    except Exception as e: print(f"Помилка пуша: {e}")

async def send_decision_push(event_id: int, seeker_id: int, status: str):
    await asyncio.sleep(1)
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title, location, additional_info, user_id FROM events WHERE id = $1", event_id)
            if event:
                if status == 'approved':
                    msg = f"🎉 *Заявку прийнято!*\n\nОрганізатор додав тебе до івенту «_{event['title']}_».\n\n📍 *Точна адреса:*\n{event['location']}"
                    if event.get('additional_info'):
                        msg += f"\n\n🔐 *Секретна інфа:*\n_{event['additional_info']}_"
                    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Написати організатору", url=f"tg://user?id={event['user_id']}")]])
                    await bot.send_message(chat_id=seeker_id, text=msg, parse_mode="Markdown", reply_markup=markup)
                elif status == 'rejected':
                    msg = f"😔 *Заявку відхилено*\n\nНа жаль, організатор івенту «_{event['title']}_» не зміг прийняти твою заявку. Не засмучуйся, поруч є ще багато цікавого!"
                    await bot.send_message(chat_id=seeker_id, text=msg, parse_mode="Markdown")
    except Exception as e: print(f"Помилка пуша рішення: {e}")

async def send_participant_left_push(event_id: int, seeker_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", event_id)
            seeker = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", seeker_id)
            if event and seeker:
                msg = f"⚠️ *Зміни в івенті*\n\nУчасник *{seeker['name']}* покинув твій івент «_{event['title']}_». Місце знову стало вільним."
                await bot.send_message(chat_id=event['user_id'], text=msg, parse_mode="Markdown")
    except Exception as e: print(f"Помилка пуша виходу: {e}")

async def send_event_deleted_push(event_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title FROM events WHERE id = $1", event_id)
            seekers = await conn.fetch("SELECT seeker_id FROM requests WHERE event_id = $1 AND status = 'approved'", event_id)
            if event:
                for row in seekers:
                    msg = f"❌ *Івент скасовано*\n\nОрганізатор видалив івент «_{event['title']}_». Плани змінюються, але попереду ще багато двіжу!"
                    try: await bot.send_message(chat_id=row['seeker_id'], text=msg, parse_mode="Markdown")
                    except: pass
    except Exception as e: print(f"Помилка пуша видалення: {e}")

async def send_event_updated_push(event_id: int):
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title FROM events WHERE id = $1", event_id)
            seekers = await conn.fetch("SELECT seeker_id FROM requests WHERE event_id = $1 AND status = 'approved'", event_id)
            if event:
                for row in seekers:
                    msg = f"⚠️ *Оновлення івенту*\n\nОрганізатор змінив деталі події «_{event['title']}_». Зайди у свої івенти, щоб перевірити, що нового!"
                    try: await bot.send_message(chat_id=row['seeker_id'], text=msg, parse_mode="Markdown")
                    except: pass
    except Exception as e: print(f"Помилка пуша оновлення: {e}")

async def send_kicked_push(event_title: str, seeker_id: int):
    try:
        msg = f"😔 *Зміни в планах*\n\nОрганізатор івенту «_{event_title}_» скасував твою участь. Але не засмучуйся, поруч ще багато крутих івентів!"
        await bot.send_message(chat_id=seeker_id, text=msg, parse_mode="Markdown")
    except Exception as e: print(f"Помилка пуша про вилучення: {e}")

# === ДІЇ З ЗАЯВКАМИ ТА ІВЕНТАМИ ===
@app.post("/api/events/join")
async def join_event(req: JoinRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            existing = await conn.fetchrow("SELECT id FROM requests WHERE event_id = $1 AND seeker_id = $2", req.event_id, req.user_id)
            if existing:
                return {"success": False, "error": "Ти вже подав заявку на цей івент!"}

            # АВТО-ОНОВЛЕННЯ ПРОФІЛЮ
            if req.user_photo or req.user_name or req.username:
                await conn.execute("""
                    UPDATE users 
                    SET photo = COALESCE($1, photo), name = COALESCE($2, name), username = COALESCE($4, username)
                    WHERE telegram_id = $3
                """, req.user_photo, req.user_name, req.user_id, req.username)

            await conn.execute("""
                INSERT INTO requests (event_id, seeker_id, status, message, created_at) 
                VALUES ($1, $2, 'pending', $3, NOW())
            """, req.event_id, req.user_id, req.message)
            
            asyncio.create_task(send_new_request_push(req.event_id, req.user_id, req.message))
            return {"success": True}
        except Exception as e:
            print(f"Помилка створення заявки: {e}")
            return {"success": False, "error": str(e)}

@app.post("/api/events/{event_id}/leave")
async def leave_event(event_id: int, req: LeaveRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            req_row = await conn.fetchrow("SELECT status FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, req.user_id)
            if req_row:
                await conn.execute("DELETE FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, req.user_id)
                if req_row['status'] == 'approved':
                    await conn.execute("UPDATE events SET needed_count = needed_count + 1 WHERE id = $1", event_id)
                    asyncio.create_task(send_participant_left_push(event_id, req.user_id))
            return {"success": True}
        except Exception as e:
            print(f"Помилка виходу з івенту: {e}")
            return {"success": False, "error": str(e)}

@app.delete("/api/events/{event_id}")
async def delete_event(event_id: int, user_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            event = await conn.fetchrow("SELECT user_id FROM events WHERE id = $1", event_id)
            if not event or event['user_id'] != user_id:
                return {"success": False, "error": "Немає прав"}
            asyncio.create_task(send_event_deleted_push(event_id))
            await conn.execute("UPDATE events SET status = 'deleted' WHERE id = $1", event_id)
            return {"success": True}
        except Exception as e:
            print(f"Помилка видалення івенту: {e}")
            return {"success": False, "error": str(e)}

@app.post("/api/events/requests/status")
async def update_request_status(req: UpdateRequestStatus):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            await conn.execute("""
                UPDATE requests 
                SET status = $1 
                WHERE event_id = $2 AND seeker_id = $3
            """, req.status, req.event_id, req.seeker_id)
            
            if req.status == 'approved':
                await conn.execute("UPDATE events SET needed_count = needed_count - 1 WHERE id = $1", req.event_id)
                
            asyncio.create_task(send_decision_push(req.event_id, req.seeker_id, req.status))
            return {"success": True}
        except Exception as e:
            print(f"Помилка оновлення статусу: {e}")
            return {"success": False, "error": str(e)}

@app.post("/api/events/{event_id}/kick")
async def kick_participant(event_id: int, req: KickRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            event = await conn.fetchrow("SELECT user_id, title FROM events WHERE id = $1", event_id)
            if not event or event['user_id'] != req.user_id:
                return {"success": False, "error": "Немає прав"}
            
            req_row = await conn.fetchrow("SELECT status FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, req.seeker_id)
            if req_row and req_row['status'] == 'approved':
                await conn.execute("DELETE FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, req.seeker_id)
                await conn.execute("UPDATE events SET needed_count = needed_count + 1 WHERE id = $1", event_id)
                asyncio.create_task(send_kicked_push(event['title'], req.seeker_id))
                return {"success": True}
            return {"success": False, "error": "Користувач не знайдений або не підтверджений"}
        except Exception as e:
            print(f"Помилка вилучення учасника: {e}")
            return {"success": False, "error": str(e)}

@app.get("/api/events/{event_id}/requests")
async def get_event_requests(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT r.seeker_id, r.status, r.message, u.name, u.photo, u.username 
                FROM requests r
                JOIN users u ON r.seeker_id = u.telegram_id
                WHERE r.event_id = $1 AND r.status = 'pending'
            """, event_id)
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Помилка отримання заявок: {e}")
            return []

@app.get("/api/events/{event_id}/participants")
async def get_event_participants(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT u.telegram_id as id, u.name, u.photo, u.username 
                FROM requests r
                JOIN users u ON r.seeker_id = u.telegram_id
                WHERE r.event_id = $1 AND r.status = 'approved'
            """, event_id)
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Помилка отримання учасників: {e}")
            return []

@app.get("/api/users/{user_id}/my_events")
async def get_my_events(user_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            org_events = await conn.fetch("""
                SELECT e.*, 
                       (SELECT COUNT(*) FROM requests r WHERE r.event_id = e.id AND r.status = 'pending') as pending_count
                FROM events e 
                WHERE e.user_id = $1 AND e.status = 'active' AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            part_events = await conn.fetch("""
                SELECT e.*, r.status as req_status
                FROM events e 
                JOIN requests r ON e.id = r.event_id 
                WHERE r.seeker_id = $1 AND e.user_id != $1 AND e.status = 'active' AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            history_events = await conn.fetch("""
                SELECT DISTINCT e.*
                FROM events e 
                LEFT JOIN requests r ON e.id = r.event_id 
                WHERE (e.user_id = $1 OR (r.seeker_id = $1 AND r.status = 'approved')) 
                  AND (e.date < CURRENT_DATE OR e.status = 'deleted')
                ORDER BY e.date DESC
            """, user_id)

            def format_rows(rows):
                res = []
                for r in rows:
                    d = dict(r)
                    for k, v in d.items():
                        if hasattr(v, 'isoformat'):
                            d[k] = v.isoformat()
                    res.append(d)
                return res

            return {
                "organizer": format_rows(org_events),
                "participant": format_rows(part_events),
                "history": format_rows(history_events)
            }
        except Exception as e:
            print(f"Помилка my_events: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# === ЕНДПОІНТ: ОТРИМАННЯ КОНТАКТІВ (НОВІ ЗАЯВКИ + УЧАСНИКИ) ===
@app.get("/api/users/{user_id}/contacts")
async def get_user_contacts(user_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            org_contacts = await conn.fetch("""
                SELECT u.telegram_id as id, u.name, u.photo, u.username, e.title as event_title, r.status
                FROM requests r
                JOIN events e ON r.event_id = e.id
                JOIN users u ON r.seeker_id = u.telegram_id
                WHERE e.user_id = $1 AND r.status IN ('approved', 'pending') AND e.status = 'active'
            """, user_id)
            
            part_contacts = await conn.fetch("""
                SELECT u.telegram_id as id, u.name, u.photo, u.username, e.title as event_title, r.status
                FROM requests r
                JOIN events e ON r.event_id = e.id
                JOIN users u ON e.user_id = u.telegram_id
                WHERE r.seeker_id = $1 AND r.status IN ('approved', 'pending') AND e.status = 'active'
            """, user_id)
            
            contacts = [dict(row) for row in org_contacts] + [dict(row) for row in part_contacts]
            return contacts
        except Exception as e:
            print(f"Помилка отримання контактів: {e}")
            return []

# === ПРОКСИ ДЛЯ ОТКРЫТИЯ ЧАТА ИЗ TMA ===
@app.post("/api/users/contact_user")
async def request_contact_via_bot(req: ContactUserRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не подключена")
    async with database.db_pool.acquire() as conn:
        try:
            # Ищем имя того, кому хотим написать
            target = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", req.target_id)
            target_name = target['name'] if target else "Користувача"
            
            # Отправляем сообщение-прокси в бота
            msg = f"✉️ *Перехід у чат!*\n\nТи хотів написати користувачу *{target_name}*.\nТисни кнопку нижче, щоб відкрити його профіль 👇"
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💬 Написати {target_name}", url=f"tg://user?id={req.target_id}")]
            ])
            
            await bot.send_message(chat_id=req.user_id, text=msg, parse_mode="Markdown", reply_markup=markup)
            return {"success": True}
        except Exception as e:
            print(f"Ошибка прокси-чата: {e}")
            return {"success": False, "error": str(e)}


# === ПРОКСИ ДЛЯ ОТКРЫТИЯ ЧАТА ===
@app.post("/api/users/contact_user")
async def request_contact_via_bot(req: ContactUserRequest):
    if not database.db_pool: raise HTTPException(status_code=500)
    async with database.db_pool.acquire() as conn:
        try:
            target = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", req.target_id)
            target_name = target['name'] if target else "Користувач"
            msg = f"✉️ *Перехід у чат!*\n\nТи хотів написати користувачу *{target_name}*.\nТисни кнопку нижче, щоб відкрити його профіль 👇"
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"💬 Написати {target_name}", url=f"tg://user?id={req.target_id}")]])
            await bot.send_message(chat_id=req.user_id, text=msg, parse_mode="Markdown", reply_markup=markup)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

# === АВТО-СИНХРОНИЗАЦИЯ ДАННЫХ ЮЗЕРА ===
@app.post("/api/sync_user")
async def sync_user_data(req: SyncRequest):
    if not database.db_pool: return {"success": False}
    async with database.db_pool.acquire() as conn:
        try:
            # Оновлюємо юзернейм, ім'я та фото при кожному вході в апку
            await conn.execute("""
                UPDATE users 
                SET username = $1,
                    name = COALESCE($2, name),
                    photo = COALESCE($3, photo)
                WHERE telegram_id = $4
            """, req.username, req.name, req.photo, req.user_id)
            return {"success": True}
        except Exception as e:
            print(f"Помилка синхронізації: {e}")
            return {"success": False}

# === РЕДАГУВАННЯ ІВЕНТУ ===
@app.post("/api/events/{event_id}/edit")
async def edit_event(event_id: int, req: EventEdit):
    if not database.db_pool: raise HTTPException(status_code=500)
    async with database.db_pool.acquire() as conn:
        try:
            owner = await conn.fetchval("SELECT user_id FROM events WHERE id = $1", event_id)
            if owner != req.user_id:
                return {"success": False, "error": "Немає прав"}
            
            await conn.execute("""
                UPDATE events 
                SET title = $1, description = $2, capacity = $3, needed_count = $4
                WHERE id = $5
            """, req.title, req.description, req.capacity, req.needed_count, event_id)
            
            # ДОДАЄМО ВИКЛИК ПУША ПРО ОНОВЛЕННЯ ОСЬ ТУТ:
            asyncio.create_task(send_event_updated_push(event_id))
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
