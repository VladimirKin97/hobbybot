import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime  # <--- Додаємо цей імпорт
from fastapi.staticfiles import StaticFiles

# Правильний імпорт: імпортуємо весь модуль, щоб не губити змінну db_pool
import database 
from main import bot, dp, ActivityMiddleware, reminders_loop, finish_events_loop

class ProfileUpdate(BaseModel):
    telegram_id: int
    name: str
    bio: str
    interests: str
    photo: str  # <--- Додали поле для фото

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запускаємо FastAPI та підключаємо базу PostgreSQL...")
    # 1. Підключаємо базу 
    await database.init_db_pool()
    
    # 2. Додаємо middleware
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    
    # 3. Запускаємо фонові лупи
    asyncio.create_task(reminders_loop())
    asyncio.create_task(finish_events_loop())
    
    print("🤖 Піднімаємо Телеграм-бота...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 4. Запускаємо бота
    bot_task = asyncio.create_task(dp.start_polling(bot))
    
    yield 
    
    print("🛑 Вимикаємо сервер, зупиняємо бота...")
    bot_task.cancel()

app = FastAPI(title="Findsy TMA API", lifespan=lifespan)
# === ДОДАЙ ОЦЕЙ РЯДОК ===
# Робимо папку img публічною, щоб браузер міг брати звідти картинки
app.mount("/img", StaticFiles(directory="img"), name="img")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main_screen.html", {"request": request})

# === МАРШРУТ ДЛЯ ПРОФІЛЮ ===
@app.get("/api/profile/{user_id}")
async def get_user_profile(user_id: int):
    """
    Віддає дані користувача для профілю ТМА.
    """
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
        
    async with database.db_pool.acquire() as conn:
        try:
            # Беремо ВСЕ: ім'я, місто, інтереси, біо та фото (photo, а не photo_url)
            row = await conn.fetchrow("""
                SELECT name, city, interests, bio, photo 
                FROM users 
                WHERE telegram_id = $1
            """, user_id)
            
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
                
            # Перетворюємо рядок з БД на словник
            user_data = dict(row)
            
            # ДОДАЄМО ЗАГЛУШКИ ДЛЯ СТАТИСТИКИ
            user_data['organized_count'] = 0
            user_data['participated_count'] = 0
            
            return user_data
            
        except Exception as e:
            print(f"Помилка БД: {e}")
            raise HTTPException(status_code=500, detail=str(e))


# === МАРШРУТ ДЛЯ ОНОВЛЕННЯ ПРОФІЛЮ ===
@app.post("/api/profile/update")
async def update_profile(data: ProfileUpdate):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
        
    async with database.db_pool.acquire() as conn:
        try:
            # Тепер оновлюємо і колонку photo ($4)
            await conn.execute("""
                UPDATE users 
                SET name = $1, bio = $2, interests = $3, photo = $4
                WHERE telegram_id = $5
            """, data.name, data.bio, data.interests, data.photo, data.telegram_id)
            
            return {"success": True}
        except Exception as e:
            print(f"Помилка оновлення профілю: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# === СТРУКТУРА ДАНИХ ДЛЯ ІВЕНТУ ===
# === СТРУКТУРА ДАНИХ ДЛЯ ІВЕНТУ ===
class EventCreate(BaseModel):
    user_id: int
    creator_name: str
    title: str
    description: str
    date: datetime  # <--- Змінили str на datetime
    location: str
    location_lat: float
    location_lon: float
    capacity: int
    photo: Optional[str] = ""

# === МАРШРУТ ДЛЯ СТВОРЕННЯ ІВЕНТУ ===
@app.post("/api/events/create")
async def create_event(event: EventCreate):
    """
    Приймає дані з форми createevent.html і створює новий запис у базі.
    """
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


# === МАРШРУТ ДЛЯ ОТРИМАННЯ ВСІХ ІВЕНТІВ (ДЛЯ МАПИ І СТРІЧКИ) ===
@app.get("/api/events")
async def get_events():
    """
    Повертає список всіх активних івентів з бази даних.
    """
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
        
    async with database.db_pool.acquire() as conn:
        try:
            # Забираємо тільки активні івенти (щоб не показувати старі або скасовані)
            rows = await conn.fetch("""
                SELECT id, title, description, date, location, location_lat, location_lon, capacity, needed_count, photo, creator_name 
                FROM events 
                WHERE status = 'active'
            """)
            
            # Перетворюємо записи з БД на список
            events_list = []
            for row in rows:
                event_dict = dict(row)
                # Дату треба перетворити на рядок, щоб JSON не сварився
                if event_dict['date']:
                    event_dict['date'] = event_dict['date'].isoformat()
                events_list.append(event_dict)
                
            return events_list
            
        except Exception as e:
            print(f"Помилка завантаження івентів: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# === СТРУКТУРА ДЛЯ ЗАЯВКИ ===
class JoinRequest(BaseModel):
    event_id: int
    user_id: int

# === ОТРИМАТИ ОДИН ІВЕНТ ЗА ID ===
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
            if event_dict['date']:
                event_dict['date'] = event_dict['date'].isoformat()
            if event_dict['created_at']:
                event_dict['created_at'] = event_dict['created_at'].isoformat()
                
            return event_dict
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
# === СТРУКТУРА ДЛЯ ЗАЯВКИ ===
class JoinRequest(BaseModel):
    event_id: int
    user_id: int # Фронтенд відправляє це поле

# === ОТРИМАТИ ОДИН ІВЕНТ ЗА ID ===
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

# === ВІДПРАВИТИ ЗАЯВКУ НА УЧАСТЬ ===
@app.post("/api/events/join")
async def join_event(req: JoinRequest):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            # Перевіряємо, чи юзер вже не подавав заявку на цей івент
            existing_request = await conn.fetchrow("""
                SELECT id FROM requests WHERE event_id = $1 AND seeker_id = $2
            """, req.event_id, req.user_id)
            
            if existing_request:
                return {"success": False, "error": "Ти вже подав заявку на цей івент"}

            # Записуємо заявку в БД. Зверни увагу: req.user_id йде в колонку seeker_id
            await conn.execute("""
                INSERT INTO requests (event_id, seeker_id, status, created_at) 
                VALUES ($1, $2, 'pending', NOW())
            """, req.event_id, req.user_id)
            
            return {"success": True}
        except Exception as e:
            print(f"Помилка створення заявки: {e}")
            return {"success": False, "error": str(e)}

# === ОТРИМАТИ УЧАСНИКІВ ІВЕНТУ ===
@app.get("/api/events/{event_id}/participants")
async def get_event_participants(event_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            # Шукаємо тих, у кого status = 'approved'
            # JOIN з таблицею users, щоб дістати їхні фотки (якщо таблиця users має колонку photo)
            # Якщо в users немає photo, заміни u.photo на щось інше, або просто u.id
            rows = await conn.fetch("""
                SELECT u.id, u.name, u.photo 
                FROM requests r
                JOIN users u ON r.seeker_id = u.id
                WHERE r.event_id = $1 AND r.status = 'approved'
            """, event_id)
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Помилка отримання учасників: {e}")
            return [] # Якщо помилка - повертаємо порожній список

# === ОТРИМАТИ МОЇ ІВЕНТИ (ОРГАНІЗАТОР, УЧАСНИК, ІСТОРІЯ) ===
@app.get("/api/users/{user_id}/my_events")
async def get_my_events(user_id: int):
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="БД не підключена")
    async with database.db_pool.acquire() as conn:
        try:
            # 1. Організатор (Активні: дата >= сьогодні)
            # Підзапит COUNT рахує кількість заявок в очікуванні
            org_events = await conn.fetch("""
                SELECT e.*, 
                       (SELECT COUNT(*) FROM requests r WHERE r.event_id = e.id AND r.status = 'pending') as pending_count
                FROM events e 
                WHERE e.user_id = $1 AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            # 2. Учасник (Активні)
            part_events = await conn.fetch("""
                SELECT e.*, r.status as req_status
                FROM events e 
                JOIN requests r ON e.id = r.event_id 
                WHERE r.seeker_id = $1 AND e.date >= CURRENT_DATE 
                ORDER BY e.date ASC
            """, user_id)
            
            # 3. Історія (Минулі івенти, де дата < сьогодні)
            history_events = await conn.fetch("""
                SELECT DISTINCT e.*
                FROM events e 
                LEFT JOIN requests r ON e.id = r.event_id 
                WHERE (e.user_id = $1 OR (r.seeker_id = $1 AND r.status = 'approved')) 
                  AND e.date < CURRENT_DATE 
                ORDER BY e.date DESC
            """, user_id)

            # Хелпер для форматування
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

# Динамічний маршрут для HTML-сторінок
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
