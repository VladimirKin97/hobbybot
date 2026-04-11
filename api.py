import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Імпортуємо твої функції та змінні прямо з main.py та database.py
from main import bot, dp, ActivityMiddleware, reminders_loop, finish_events_loop
from database import init_db_pool, db_pool

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

# 1. Головна сторінка (Віддає main_screen.html)
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("main_screen.html", {"request": request})

# === НОВИЙ МАРШРУТ ДЛЯ ПРОФІЛЮ ===
@app.get("/api/profile/{user_id}")
async def get_user_profile(user_id: int):
    """
    Віддає дані користувача для профілю ТМА на основі реальної БД.
    """
    if not db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
        
    async with db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                SELECT full_name AS name, city, bio 
                FROM users 
                WHERE telegram_id = $1
            """, user_id)
            
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
                
            return dict(row)
            
        except Exception as e:
            print(f"Помилка БД: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# 2. ДИНАМІЧНИЙ МАРШРУТ (Магія, яка полагодить твій плюсик і всі інші лінки)
# Цей код буде ловити будь-які запити типу /createevent.html, /Strichka.html і віддавати їх
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
