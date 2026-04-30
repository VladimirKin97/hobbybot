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
import pytz

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
    username: Optional[str] = ""
    name: str
    photo: Optional[str] = ""
    city: Optional[str] = ""
    interests: Optional[str] = ""
    bio: Optional[str] = ""

class EventEdit(BaseModel):
    user_id: int
    title: str
    description: str
    capacity: int
    needed_count: int
    date: datetime

class RatingSubmit(BaseModel):
    event_id: int
    from_user_id: int
    to_user_id: int
    role_evaluated: str
    score: int


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

# Повертаємо пошук шаблонів у папку templates
templates = Jinja2Templates(directory="templates")

# === МАРШРУТИ ===

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main_screen.html", {"request": request})

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int):
    if not database.db_pool: return {"success": False}
    async with database.db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", user_id)
        if user:
            org_count = await conn.fetchval("SELECT COUNT(*) FROM events WHERE user_id = $1", user_id)
            part_count = await conn.fetchval("SELECT COUNT(*) FROM requests WHERE seeker_id = $1 AND status = 'approved'", user_id)
            
            return {
                "success": True, 
                "photo": user.get('photo'), 
                "name": user.get('name'), 
                "city": user.get('city'),           # <-- ДОДАЛИ МІСТО
                "bio": user.get('bio'), 
                "interests": user.get('interests'),
                "events_organized": org_count or 0,
                "events_joined": part_count or 0,
                "rating_org": float(user.get('rating_org', 5.0)),
                "votes_org": user.get('votes_org', 0),
                "rating_part": float(user.get('rating_part', 5.0)),
                "votes_part": user.get('votes_part', 0)
            }
        return {"success": False}

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
async def get_events(user_id: int = 0):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            if user_id > 0:
                rows = await conn.fetch("""
                    SELECT id, title, description, date, location, location_lat, location_lon, capacity, needed_count, photo, creator_name, is_address_public 
                    FROM events 
                    WHERE status = 'active' AND needed_count > 0 AND date >= NOW() AND user_id != $1
                    ORDER BY created_at DESC
                """, user_id)
            else:
                rows = await conn.fetch("""
                    SELECT id, title, description, date, location, location_lat, location_lon, capacity, needed_count, photo, creator_name, is_address_public 
                    FROM events 
                    WHERE status = 'active' AND needed_count > 0 AND date >= NOW()
                    ORDER BY created_at DESC
                """)
            
            events_list = []
            for row in rows:
                event_dict = dict(row)
                if event_dict['date']:
                    event_dict['date'] = event_dict['date'].isoformat()
                
                if not event_dict.get('is_address_public'):
                    city = event_dict['location'].split(',')[0]
                    event_dict['location'] = f"{city} (Точна адреса після підтвердження)"
                    
                events_list.append(event_dict)
            return events_list
        except Exception as e:
            print(f"Помилка завантаження івентів: {e}")
            raise HTTPException(status_code=500, detail=str(e))

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
                
            if user_id > 0:
                req = await conn.fetchrow("SELECT status FROM requests WHERE event_id = $1 AND seeker_id = $2", event_id, user_id)
                if req:
                    event_dict['my_request_status'] = req['status']
            
            is_owner = (user_id == event_dict['user_id'])
            is_approved = (event_dict.get('my_request_status') == 'approved')
            
            if not event_dict.get('is_address_public') and not is_owner and not is_approved:
                city = event_dict['location'].split(',')[0]
                event_dict['location'] = f"{city} (Точна адреса після підтвердження)"
                    
            return event_dict
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# === ФОНОВІ ФУНКЦІЇ ПУШІВ ===
async def send_new_request_push(event_id: int, seeker_id: int):
    await asyncio.sleep(1) 
    if not database.db_pool: return
    try:
        from main import bot
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from aiogram.types.web_app_info import WebAppInfo

        domain = "https://worker-production-784c.up.railway.app"

        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", event_id)
            seeker = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", seeker_id)
            
            if event and seeker:
                safe_name = str(seeker['name'] or 'Хтось').replace('<', '&lt;').replace('>', '&gt;')
                safe_title = str(event['title']).replace('<', '&lt;').replace('>', '&gt;')
                
                msg = (f"🔔 <b>Нова заявка!</b>\n\n"
                       f"<b>{safe_name}</b> хоче долучитися до «{safe_title}».\n\n"
                       f"Відкрий додаток (розділ «Івенти»), щоб переглянути деталі та прийняти рішення.")
                
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Відкрити Findsy", web_app=WebAppInfo(url=f"{domain}/"))]
                ])
                
                await bot.send_message(chat_id=event['user_id'], text=msg, parse_mode="HTML", reply_markup=markup)
    except Exception as e: 
        print(f"Помилка пуша: {e}")

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

async def send_event_full_push(event_id: int):
    """Пуш коли івент повністю зібрав компанію (needed_count == 0)"""
    await asyncio.sleep(1)
    try:
        async with database.db_pool.acquire() as conn:
            event = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", event_id)
            if not event: return
            
            # 1. Пуш Організатору
            org_msg = f"🥳 *Бінго!*\n\nТвій івент «_{event['title']}_» повністю зібрано! Всі місця зайняті. Перейди в чати з учасниками, щоб обговорити останні деталі."
            try: await bot.send_message(chat_id=event['user_id'], text=org_msg, parse_mode="Markdown")
            except Exception as e: print(f"Не вийшло пушнути оргу: {e}")
            
            # 2. Пуш Учасникам
            participants = await conn.fetch("SELECT seeker_id FROM requests WHERE event_id = $1 AND status = 'approved'", event_id)
            part_msg = f"🔥 *Компанія зібрана!*\n\nІвент «_{event['title']}_» повністю укомплектований! Готуйся до крутого двіжу. Не забудь перевірити чат з організатором."
            for p in participants:
                try: await bot.send_message(chat_id=p['seeker_id'], text=part_msg, parse_mode="Markdown")
                except: pass
    except Exception as e:
        print(f"Помилка пуша про повний збір: {e}")

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
    print(f"[API] 🚀 СТАРТ: Отримано запит на участь: event_id={req.event_id}, user_id={req.user_id}, msg={req.message}")
    
    if not database.db_pool: 
        print("[API] ❌ Помилка: БД не підключена!")
        return {"success": False, "error": "БД не підключена"}

    try:
        async with database.db_pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM requests WHERE event_id = $1 AND seeker_id = $2", 
                req.event_id, req.user_id
            )
            if existing:
                print(f"[API] ⚠️ Заявка від {req.user_id} на івент {req.event_id} ВЖЕ ІСНУЄ!")
                return {"success": False, "error": "Ти вже подав заявку на цей івент!"}
            
            print("[API] 🔄 Синхронізація користувача...")
            user_exists = await conn.fetchval("SELECT telegram_id FROM users WHERE telegram_id = $1", req.user_id)
            if user_exists:
                await conn.execute("""
                    UPDATE users 
                    SET username = COALESCE($1, username),
                        name = COALESCE(name, $2),
                        photo = COALESCE(photo, $3)
                    WHERE telegram_id = $4
                """, req.username, req.user_name, req.user_photo, req.user_id)
            else:
                await conn.execute("""
                    INSERT INTO users (telegram_id, name, photo, username)
                    VALUES ($1, $2, $3, $4)
                """, req.user_id, req.user_name, req.user_photo, req.username)
            
            print(f"[API] 📝 Збереження заявки в базу... Message: {req.message}")
            await conn.execute("""
                INSERT INTO requests (event_id, seeker_id, status, message) 
                VALUES ($1, $2, 'pending', $3)
            """, req.event_id, req.user_id, req.message)
            print("[API] ✅ Заявка успішно збережена в БД!")
            
            print("[API] 🔔 Підготовка пуша організатору...")
            ev = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", req.event_id)
            if ev:
                safe_name = str(req.user_name or 'Хтось').replace('<', '').replace('>', '')
                safe_title = str(ev['title']).replace('<', '').replace('>', '')
                msg = f"🔔 <b>Нова заявка!</b>\n\n<b>{safe_name}</b> хоче долучитися до «{safe_title}».\n\nВідкрий додаток, щоб переглянути."
                
                domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "worker-production-784c.up.railway.app")
                clean_domain = domain.replace("https://", "").replace("http://", "").strip("/")
                
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📱 Відкрити Findsy", web_app=WebAppInfo(url=f"https://{clean_domain}/"))]
                ])
                
                try:
                    from main import bot 
                    await bot.send_message(chat_id=ev['user_id'], text=msg, parse_mode="HTML", reply_markup=markup)
                    print("[API] 🚀 Пуш успішно відправлено організатору!")
                except Exception as push_err:
                    print(f"[API] ❌ Помилка відправки пуша: {push_err}")
            else:
                print(f"[API] ❌ Івент {req.event_id} не знайдено для відправки пуша!")
            
            return {"success": True}

    except Exception as e:
        print(f"[API] 🛑 КРИТИЧНА ПОМИЛКА: {e}")
        import traceback
        traceback.print_exc() 
        return {"success": False, "error": f"Помилка сервера: {str(e)}"}
        
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
                # Зменшуємо needed_count і одразу повертаємо нове значення
                new_needed = await conn.fetchval("""
                    UPDATE events SET needed_count = GREATEST(needed_count - 1, 0) 
                    WHERE id = $1 RETURNING needed_count
                """, req.event_id)
                
                # Якщо місць більше немає (івент зібрано) - пушимо всім!
                if new_needed == 0:
                    asyncio.create_task(send_event_full_push(req.event_id))
                
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

@app.get("/api/users/{user_id}/status")
async def get_user_status(user_id: int):
    if not database.db_pool: return {"is_registered": False}
    async with database.db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT city, interests FROM users WHERE telegram_id = $1", user_id)
        if user:
            # Ты зарегистрирован ТОЛЬКО если в базе реально сохранились город и интересы!
            has_city = bool(user.get("city"))
            has_interests = bool(user.get("interests"))
            return {"is_registered": has_city and has_interests}
        return {"is_registered": False}

@app.get("/api/users/{user_id}/contacts")
async def get_user_contacts(user_id: int):
    if not database.db_pool: raise HTTPException(status_code=500)
    async with database.db_pool.acquire() as conn:
        try:
            org_contacts = await conn.fetch("""
                SELECT u.telegram_id as id, u.name, u.photo, u.username, e.title as event_title, r.status
                FROM requests r
                JOIN events e ON r.event_id = e.id
                JOIN users u ON r.seeker_id = u.telegram_id
                WHERE e.user_id = $1 AND r.status IN ('approved', 'pending')
            """, user_id)
            
            part_contacts = await conn.fetch("""
                SELECT u.telegram_id as id, u.name, u.photo, u.username, e.title as event_title, r.status
                FROM requests r
                JOIN events e ON r.event_id = e.id
                JOIN users u ON e.user_id = u.telegram_id
                WHERE r.seeker_id = $1 AND r.status IN ('approved', 'pending')
            """, user_id)
            
            return [dict(row) for row in org_contacts] + [dict(row) for row in part_contacts]
        except: return []

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

@app.post("/api/sync_user")
async def sync_user_data(req: SyncRequest):
    if not database.db_pool: 
        return {"success": False, "error": "No DB pool"}
    
    async with database.db_pool.acquire() as conn:
        try:
            # АВТО-МИГРАЦИЯ: база сама создаст колонки, если их нет
            try:
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS city TEXT;")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS interests TEXT;")
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT;")
            except Exception:
                pass

            user_exists = await conn.fetchval("SELECT telegram_id FROM users WHERE telegram_id = $1", req.user_id)
            
            if user_exists:
                # Если юзер есть — ОБНОВЛЯЕМ ВСЕ ДАННЫЕ
                await conn.execute("""
                    UPDATE users 
                    SET username = $1,
                        name = $2,
                        photo = $3,
                        city = $4,
                        interests = $5,
                        bio = $6,
                        last_active = now()
                    WHERE telegram_id = $7
                """, req.username, req.name, req.photo, req.city, req.interests, req.bio, req.user_id)
            else:
                # Если новый — ВСТАВЛЯЕМ ВСЕ ДАННЫЕ
                await conn.execute("""
                    INSERT INTO users (telegram_id, username, name, photo, city, interests, bio, last_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                """, req.user_id, req.username, req.name, req.photo, req.city, req.interests, req.bio)
            
            return {"success": True}
        except Exception as e:
            logging.error(f"БЕШЕНАЯ ОШИБКА В SYNC_USER: {e}")
            return {"success": False, "error": str(e)}

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
                SET title = $1, description = $2, capacity = $3, needed_count = $4, date = $5
                WHERE id = $6
            """, req.title, req.description, req.capacity, req.needed_count, req.date, event_id)
            
            asyncio.create_task(send_event_updated_push(event_id))
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

@app.post("/api/rating/submit")
async def submit_rating(req: RatingSubmit):
    if not database.db_pool: return {"success": False}
    await database.add_review_and_update_rating(
        req.event_id, req.from_user_id, req.to_user_id, req.role_evaluated, req.score
    )
    return {"success": True}

@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
