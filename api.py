import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Правильний імпорт: імпортуємо весь модуль, щоб не губити змінну db_pool
import database 
from main import bot, dp, ActivityMiddleware, reminders_loop, finish_events_loop

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
    # Тепер ми беремо пул напряму з модуля
    if not database.db_pool:
        raise HTTPException(status_code=500, detail="База даних не підключена")
        
    async with database.db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                SELECT name AS name, city, bio 
                FROM users 
                WHERE telegram_id = $1
            """, user_id)
            
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
                
            return dict(row)
            
        except Exception as e:
            print(f"Помилка БД: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# Динамічний маршрут для HTML-сторінок
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def serve_html_pages(request: Request, page_name: str):
    return templates.TemplateResponse(f"{page_name}.html", {"request": request})
