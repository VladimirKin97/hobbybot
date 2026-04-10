import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Імпортуємо твої функції та змінні прямо з main.py та database.py
from main import bot, dp, ActivityMiddleware, reminders_loop, finish_events_loop
from database import init_db_pool, save_event_to_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запускаємо FastAPI та підключаємо базу PostgreSQL...")
    # 1. Підключаємо базу (один раз для бота і для API)
    await init_db_pool()
    
    # 2. Обов'язково додаємо твій middleware для активності
    dp.message.middleware(ActivityMiddleware())
    dp.callback_query.middleware(ActivityMiddleware())
    
    # 3. Запускаємо твої фонові лупи з main.py
    asyncio.create_task(reminders_loop())
    asyncio.create_task(finish_events_loop())
    
    print("🤖 Піднімаємо Телеграм-бота (у фоновому режимі)...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 4. Запускаємо бота як паралельну задачу, щоб він не блокував FastAPI
    bot_task = asyncio.create_task(dp.start_polling(bot))
    
    yield # <--- З цього моменту FastAPI готовий приймати запити від TMA
    
    print("🛑 Вимикаємо сервер, зупиняємо бота...")
    bot_task.cancel()

# Створюємо сам додаток API
app = FastAPI(title="Findsy TMA API", lifespan=lifespan)

# Дозволяємо твоєму HTML (TMA) спілкуватися з цим бекендом
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Вказуємо FastAPI, де лежать наші HTML-файли (папка templates)
templates = Jinja2Templates(directory="templates")

# Головна "ручка", яка віддає HTML-сторінку (Твою Карту)
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main_screen.html", {"request": request})

# ВІДДАЄ ФОРМУ СТВОРЕННЯ ІВЕНТУ
@app.get("/create_event", response_class=HTMLResponse)
async def create_event_page(request: Request):
    return templates.TemplateResponse("createevent.html", {"request": request})

# === НОВИЙ БЛОК: ОБРОБКА ФОРМИ СТВОРЕННЯ ІВЕНТУ З КАРТОЮ ===
@app.post("/create_event")
async def handle_create_event_form(
    request: Request,
    title: str = Form(...),
    capacity: int = Form(10), # Якщо не передадуть, буде 10 за замовчуванням
    needed_count: int = Form(5),
    # Наші координати з прихованих полів мапи
    location_lat: float = Form(None), 
    location_lon: float = Form(None)
):
    # ТУТ МАЄ БУТИ ID ЮЗЕРА (поки ставимо 0, пізніше підв'яжемо до Telegram WebApp даних)
    user_id = 0 
    
    # Викликаємо функцію з твого database.py
    await save_event_to_db(
        user_id, 
        "Організатор", # creator_name
        "Київ", # city
        title, 
        "Опис з апки", # description
        "2026-12-31 12:00", # event_date (заглушка дати)
        "Точка на мапі", # event_location
        capacity, 
        needed_count, 
        'active', # status
        location_lat, # Ось наша широта з карти!
        location_lon, # Ось наша довгота з карти!
        None # photo
    )
    
    # Після успішного збереження перекидаємо юзера назад на головну карту
    return RedirectResponse(url="/", status_code=303)

# Перевірочна "ручка" (просто щоб знати, що бекенд відповідає)
@app.get("/api/ping")
async def ping():
    return {"ping": "pong"}
