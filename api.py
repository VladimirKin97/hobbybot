import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from fastapi.staticfiles import StaticFiles
import httpx
import os

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
    creator_name: str
    title: str
    description: str
    date: datetime
    location: str
    location_lat: float
    location_lon: float
    capacity: int
    photo: Optional[str] = ""

class JoinRequest(BaseModel):
    event_id: int
    user_id: int

class UpdateRequestStatus(BaseModel):
    event_id: int
    seeker_id: int
    status: str

# === ЖИТТЄВИЙ ЦИКЛ ДОДАТКУ ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запускаємо FastAPI та підключаємо базу PostgreSQL...")
    await database.init_db_pool()
    
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
                    user_id, creator_name, title, description, 
                    date, location, location_lat, location_lon, 
                    capacity, needed_count, status, photo, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active', $11, NOW()
                ) RETURNING id
            """, 
            event.user_id, event.creator_name, event.title, event.description,
            event.date, event.location, event.location_lat, event.location_lon,
            event.capacity, event.capacity, event.photo)
            
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
                SELECT id, title, description, date, location, location_lat, location_lon, capacity, needed_count, photo, creator_name 
                FROM events 
                WHERE status = 'active'
            """)
            events_list = []
            for row in rows:
                event_dict = dict(row)
                if event_dict['date']:
                    event_dict['date'] = event_dict['date'].isoformat()
                events_list.append(event_dict)
            return events_list
        except Exception as e:
            print(f"Помилка завантаження івентів: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}")
async def get_single_event(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
            if not row:
                raise HTTPException(status_code=404, detail="Івент не знайдено")
            
            event_dict = dict(row)
            if event_dict.get('date'):
                event_dict['date'] = event_dict['date'].isoformat()
            if event_dict.get('created_at'):
                event_dict['created_at'] = event_dict['created_at'].isoformat()
                
            return event_dict
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/events/join")
async def join_event(req: JoinRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            # 1. Перевірка на дублікати
            existing = await conn.fetchrow("SELECT id FROM requests WHERE event_id = $1 AND seeker_id = $2", req.event_id, req.user_id)
            if existing:
                return {"success": False, "error": "Ти вже подав заявку на цей івент!"}

            # 2. Записуємо заявку в БД
            await conn.execute("INSERT INTO requests (event_id, seeker_id, status, created_at) VALUES ($1, $2, 'pending', NOW())", req.event_id, req.user_id)
            
            # 3. Відправка ПУШ-сповіщення
            try:
                event_info = await conn.fetchrow("SELECT title, user_id FROM events WHERE id = $1", req.event_id)
                seeker_info = await conn.fetchrow("SELECT name FROM users WHERE id = $1", req.user_id)
                
                if event_info and seeker_info:
                    bot_token = os.getenv("BOT_TOKEN")
                    if bot_token:
                        msg = f"🔔 *Нова заявка!*\n\n*{seeker_info['name'] or 'Хтось'}* хоче долучитися до івенту «_{event_info['title'] or 'Без назви'}_».\n\nВідкрий Findsy ➡️ Мої івенти, щоб переглянути."
                        
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": event_info['user_id'], "text": msg, "parse_mode": "Markdown"}
                            )
                    else:
                        print("УВАГА: Токен не знайдено!")
            except Exception as e:
                print(f"Помилка пуша: {e}")

            return {"success": True}
        except Exception as e:
            print(f"Помилка створення заявки: {e}")
            return {"success": False, "error": str(e)}

@app.get("/api/events/{event_id}/participants")
async def get_event_participants(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT u.id, u.name, u.photo 
                FROM requests r
                JOIN users u ON r.seeker_id = u.id
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
                WHERE e.user_id = $1 AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            part_events = await conn.fetch("""
                SELECT e.*, r.status as req_status
                FROM events e 
                JOIN requests r ON e.id = r.event_id 
                WHERE r.seeker_id = $1 AND e.user_id != $1 AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            history_events = await conn.fetch("""
                SELECT DISTINCT e.*
                FROM events e 
                LEFT JOIN requests r ON e.id = r.event_id 
                WHERE (e.user_id = $1 OR (r.seeker_id = $1 AND r.status = 'approved')) 
                  AND e.date < CURRENT_DATE 
                ORDER BY e.date DESC
            """, user_id)

            def format_rows(rows):
                res = []
                for r in rows:
                    d = dict(r)
                    if d.get('date'): d['date'] = d['date'].isoformat()
                    if d.get('created_at'): d['created_at'] = d['created_at'].isoformat()
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

@app.get("/api/events/{event_id}/requests")
async def get_event_requests(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT r.seeker_id, r.status, u.name, u.photo
                FROM requests r
                JOIN users u ON r.seeker_id = u.id
                WHERE r.event_id = $1 AND r.status = 'pending'
            """, event_id)
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Помилка отримання заявок: {e}")
            return []

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
            return {"success": True}
        except Exception as e:
            print(f"Помилка оновлення статусу: {e}")
            return {"success": False, "error": str(e)}

@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
