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

# Динамічний маршрут для HTML-сторінок
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
