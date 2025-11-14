# ================================================
#  FIND SY — Telegram Bot (FULL REBUILD 14.11)
#  PART 1 / 10 — Import, Logger, Bot, DB Init
# ================================================

import asyncio
import logging
import math
from datetime import datetime, timedelta

import asyncpg
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# -----------------------------------------
#  LOGGING
# -----------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# -----------------------------------------
#  BOT TOKEN
# -----------------------------------------
# ВСТАВ СВОЙ ТОКЕН!!
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# -----------------------------------------
#  DATABASE
# -----------------------------------------

# ВСТАВ СВОЙ DATABASE_URL!!!
DATABASE_URL = os.getenv("DATABASE_URL")

# -----------------------------------------
#  INIT DB
# -----------------------------------------

async def init_db():
    """
    Ініціалізація всіх таблиць для Findsy.
    Включає:
    - users
    - events
    - event_participants
    - ratings
    - event_subscriptions (НОВА ТАБЛИЦЯ)
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # таблиця користувачів
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            phone TEXT,
            name TEXT,
            city TEXT,
            photo TEXT,
            interests TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)

        # таблиця подій
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            creator_name TEXT,
            creator_phone TEXT,
            title TEXT,
            description TEXT,
            date TIMESTAMPTZ,
            location TEXT,
            capacity INT,
            needed_count INT,
            status TEXT NOT NULL DEFAULT 'active', -- active / collected / finished / deleted
            location_lat DOUBLE PRECISION,
            location_lon DOUBLE PRECISION,
            photo TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)

        # учасники подій
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_participants (
            id SERIAL PRIMARY KEY,
            event_id INT NOT NULL REFERENCES events(id),
            participant_id BIGINT NOT NULL,
            organizer_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',  -- pending / accepted / rejected
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(event_id, participant_id)
        );
        """)

        # рейтинги (юзер оцінює організатора)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            event_id INT NOT NULL,
            organizer_id BIGINT NOT NULL,
            seeker_id BIGINT NOT NULL,
            score INT CHECK (score BETWEEN 1 AND 10),
            status TEXT NOT NULL DEFAULT 'pending',  -- pending/done/skipped
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(event_id, seeker_id)
        );
        """)

        # ПІДПИСКИ на нові події
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            mode TEXT NOT NULL,              -- keyword | interests | radius
            keyword TEXT,
            radius_km DOUBLE PRECISION,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)

    finally:
        await conn.close()

# ================================================
#  PART 2 / 10 — CONSTANTS, BUTTONS, KEYBOARDS
# ================================================

# -----------------------------------------
#  BUTTON TEXT CONSTANTS
# -----------------------------------------

BTN_PROFILE = "👤 Мій профіль"
BTN_CREATE = "➕ Створити подію"
BTN_SEARCH = "🔍 Знайти компанію"
BTN_MY_EVENTS = "📁 Мої події"
BTN_BACK = "⬅️ Назад"
BTN_MENU = "🏠 Головне меню"

# Пошук
BTN_SEARCH_KW = "🔎 За ключовим словом"
BTN_SEARCH_NEAR = "📍 Поруч"
BTN_SEARCH_MINE = "🎯 За моїми інтересами"


# ================================================
#  PART 2 / 10 — CONSTANTS, BUTTONS, KEYBOARDS
# ================================================

# -----------------------------------------
#  BUTTON TEXT CONSTANTS
# -----------------------------------------

BTN_PROFILE = "👤 Мій профіль"
BTN_CREATE = "➕ Створити подію"
BTN_SEARCH = "🔍 Знайти компанію"
BTN_MY_EVENTS = "📁 Мої події"
BTN_BACK = "⬅️ Назад"
BTN_MENU = "🏠 Головне меню"

# Пошук
BTN_SEARCH_KW = "🔎 За ключовим словом"
BTN_SEARCH_NEAR = "📍 Поруч"
BTN_SEARCH_MINE = "🎯 За моїми інтересами"

# Мої івенти — фільтри
BTN_MY_EVENTS_ACTIVE = "🟢 Активні"
BTN_MY_EVENTS_FINISHED = "🔵 Проведені"
BTN_MY_EVENTS_DELETED = "🔴 Видалені"

# Підписки
BTN_SUB_YES  = "✅ Хочу сповіщення"
BTN_SUB_NO   = "❌ Не потрібно"

BTN_SUB_MODE_KEYWORD   = "1️⃣ За ключовим словом"
BTN_SUB_MODE_INTERESTS = "2️⃣ За інтересами профілю"
BTN_SUB_MODE_RADIUS    = "3️⃣ За радіусом"

# Локація
BTN_SEND_CURRENT_LOCATION = "📍 Надіслати поточну геолокацію"
BTN_CHOOSE_ON_MAP = "🗺 Обрати точку на мапі"

# Подія
BTN_PUBLISH = "✅ Опублікувати"
BTN_SKIP_PHOTO = "⏭ Пропустити фото"
BTN_EDIT_EVENT = "✏️ Редагувати"
BTN_CANCEL_EVENT = "🗑 Скасувати подію"

# Чат
BTN_OPEN_CHAT = "💬 Відкрити чат"
BTN_CLOSE_CHAT = "❌ Закрити чат"
BTN_RETURN_MENU = "🏠 В головне меню"

# -----------------------------------------
#  GENERAL KEYBOARDS
# -----------------------------------------

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_MY_EVENTS)],
            [KeyboardButton(text=BTN_PROFILE)]
        ],
        resize_keyboard=True
    )

def back_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BACK)]],
        resize_keyboard=True
    )

# -----------------------------------------
#  ПОШУК — МЕНЮ
# -----------------------------------------

def search_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH_KW)],
            [KeyboardButton(text=BTN_SEARCH_NEAR)],
            [KeyboardButton(text=BTN_SEARCH_MINE)],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

# -----------------------------------------
#  ПІДПИСКИ
# -----------------------------------------

def subscribe_offer_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SUB_YES)],
            [KeyboardButton(text=BTN_SUB_NO)],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

def subscribe_mode_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SUB_MODE_KEYWORD)],
            [KeyboardButton(text=BTN_SUB_MODE_INTERESTS)],
            [KeyboardButton(text=BTN_SUB_MODE_RADIUS)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True
    )

def radius_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="3")],
            [KeyboardButton(text="5")],
            [KeyboardButton(text="10")],
            [KeyboardButton(text="20")],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

# -----------------------------------------
#  ЛОКАЦІЯ
# -----------------------------------------

def location_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEND_CURRENT_LOCATION, request_location=True)],
            [KeyboardButton(text=BTN_CHOOSE_ON_MAP)],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

# -----------------------------------------
#  МОЇ ІВЕНТИ — ФІЛЬТРИ
# -----------------------------------------

def my_events_filter_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_MY_EVENTS_ACTIVE)],
            [KeyboardButton(text=BTN_MY_EVENTS_FINISHED)],
            [KeyboardButton(text=BTN_MY_EVENTS_DELETED)],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

# -----------------------------------------
#  ІНЛАЙН ДЛЯ ВІДПИСАННЯ ВІД ПІДПИСОК
# -----------------------------------------

def unsub_inline_kb(sub_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🚫 Не отримувати більше такі події",
                callback_data=f"unsub:{sub_id}"
            )
        ]]
    )

# ================================================
#  PART 3 / 10 — DATABASE HELPERS, RATING, SUBSCRIPTIONS
# ================================================


# -----------------------------------------
#  BASIC DB HELPERS
# -----------------------------------------

async def get_user_from_db(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    finally:
        await conn.close()


async def save_user_to_db(user_id: int, phone: str, name: str, city: str, photo: str, interests: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            INSERT INTO users (user_id, phone, name, city, photo, interests)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (user_id) DO UPDATE
                SET phone = EXCLUDED.phone,
                    name = EXCLUDED.name,
                    city = EXCLUDED.city,
                    photo = EXCLUDED.photo,
                    interests = EXCLUDED.interests
        """, user_id, phone, name, city, photo, interests)
    finally:
        await conn.close()


# -----------------------------------------
#  EVENT HELPERS
# -----------------------------------------

async def save_event_to_db(
    user_id: int,
    creator_name: str,
    creator_phone: str,
    title: str,
    description: str,
    date: datetime,
    location: str,
    capacity: int,
    needed_count: int,
    status: str,
    location_lat: float,
    location_lon: float,
    photo: str
):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("""
            INSERT INTO events (
                user_id, creator_name, creator_phone,
                title, description, date, location,
                capacity, needed_count, status,
                location_lat, location_lon, photo
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            RETURNING *
        """, user_id, creator_name, creator_phone, title, description,
             date, location, capacity, needed_count, status,
             location_lat, location_lon, photo)
        return row
    finally:
        await conn.close()


async def update_event_status(event_id: int, new_status: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            UPDATE events SET status = $2 WHERE id = $1
        """, event_id, new_status)
    finally:
        await conn.close()


async def get_event(event_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
    finally:
        await conn.close()


async def get_events_by_user(user_id: int, status: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT * FROM events
            WHERE user_id = $1 AND status = $2
            ORDER BY date ASC
        """, user_id, status)
    finally:
        await conn.close()


# -----------------------------------------
#  SEARCH HELPERS
# -----------------------------------------

async def find_events_by_kw(keyword: str, limit: int = 20):
    if not keyword:
        return []
    kw = "%" + keyword.lower().strip() + "%"

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT * FROM events
            WHERE status = 'active'
              AND (LOWER(title) LIKE $1 OR LOWER(description) LIKE $1)
              AND date >= now()
            ORDER BY date ASC
            LIMIT $2
        """, kw, limit)
    finally:
        await conn.close()


async def find_events_by_user_interests(user_id: int, limit: int = 20):
    user = await get_user_from_db(user_id)
    if not user or not user.get("interests"):
        return []

    tokens = [t.strip().lower() for t in user["interests"].split(",") if t.strip()]
    if not tokens:
        return []

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = []
        for t in tokens:
            part = await conn.fetch("""
                SELECT * FROM events
                WHERE status = 'active'
                  AND date >= now()
                  AND (
                        LOWER(title) LIKE $1
                        OR LOWER(description) LIKE $1
                      )
                ORDER BY date ASC
                LIMIT $2
            """, "%" + t + "%", limit)
            rows.extend(part)

        # унікальні
        uniq = {r["id"]: r for r in rows}
        return list(uniq.values())
    finally:
        await conn.close()


async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 20):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT * FROM events
            WHERE status = 'active'
              AND date >= now()
              AND location_lat IS NOT NULL
              AND location_lon IS NOT NULL
        """)
    finally:
        await conn.close()

    result = []
    for ev in rows:
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        lat2 = math.radians(ev["location_lat"])
        lon2 = math.radians(ev["location_lon"])

        dphi = lat2 - lat1
        dlambda = lon2 - lon1
        a = (math.sin(dphi / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlambda / 2) ** 2)
        dist = 2 * 6371 * math.asin(min(1, math.sqrt(a)))

        if dist <= radius_km:
            result.append(ev)

    result.sort(key=lambda x: x["date"])
    return result[:limit]


# -----------------------------------------
#  PARTICIPANTS
# -----------------------------------------

async def add_participant(event_id: int, participant_id: int, organizer_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.execute("""
            INSERT INTO event_participants (event_id, participant_id, organizer_id)
            VALUES ($1,$2,$3)
            ON CONFLICT DO NOTHING
        """, event_id, participant_id, organizer_id)
    finally:
        await conn.close()


async def update_participant_status(event_id: int, participant_id: int, new_status: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            UPDATE event_participants
               SET status = $3
             WHERE event_id = $1 AND participant_id = $2
        """, event_id, participant_id, new_status)
    finally:
        await conn.close()


async def get_event_participants(event_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT * FROM event_participants
            WHERE event_id = $1
        """, event_id)
    finally:
        await conn.close()


# -----------------------------------------
#  RATINGS
# -----------------------------------------

async def create_rating_request(event_id: int, organizer_id: int, seeker_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            INSERT INTO ratings (event_id, organizer_id, seeker_id, status)
            VALUES ($1,$2,$3,'pending')
            ON CONFLICT DO NOTHING
        """, event_id, organizer_id, seeker_id)
    finally:
        await conn.close()


async def submit_rating(event_id: int, seeker_id: int, score: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            UPDATE ratings
               SET score = $3,
                   status = 'done'
             WHERE event_id = $1 AND seeker_id = $2
        """, event_id, seeker_id, score)
    finally:
        await conn.close()


async def get_organizer_rating(organizer_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT score FROM ratings
            WHERE organizer_id = $1 AND status = 'done'
        """, organizer_id)
    finally:
        await conn.close()

    scores = [r["score"] for r in rows if r["score"] is not None]
    if not scores:
        return 10  # стартовий рейтинг
    return round(sum(scores) / len(scores), 2)


# -----------------------------------------
#  SUBSCRIPTIONS
# -----------------------------------------

async def create_subscription_keyword(user_id: int, keyword: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("""
            INSERT INTO event_subscriptions (user_id, mode, keyword)
            VALUES ($1,'keyword',$2)
            RETURNING *
        """, user_id, keyword.strip().lower())
    finally:
        await conn.close()


async def create_subscription_interests(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("""
            INSERT INTO event_subscriptions (user_id, mode)
            VALUES ($1,'interests')
            RETURNING *
        """, user_id)
    finally:
        await conn.close()


async def create_subscription_radius(user_id: int, lat: float, lon: float, radius_km: float):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("""
            INSERT INTO event_subscriptions (user_id, mode, lat, lon, radius_km)
            VALUES ($1,'radius',$2,$3,$4)
            RETURNING *
        """, user_id, lat, lon, radius_km)
    finally:
        await conn.close()


async def deactivate_subscription(sub_id: int, user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        res = await conn.execute("""
            UPDATE event_subscriptions
               SET active = false
             WHERE id = $1 AND user_id = $2
        """, sub_id, user_id)
        return res.startswith("UPDATE")
    finally:
        await conn.close()

# ================================================
#  PART 4 / 10 — START, PROFILE, EDIT PROFILE
# ================================================


# -----------------------------------------
#  SAFE SEND (бот не падає, якщо юзер закрив чат)
# -----------------------------------------

async def safe_send(chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.warning(f"safe_send failed: {e}")


async def safe_photo(chat_id: int, photo: str, caption: str = None, **kwargs):
    try:
        return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except Exception as e:
        logging.warning(f"safe_photo failed: {e}")


async def safe_alert(call: types.CallbackQuery, text: str, show_alert=False):
    try:
        return await call.answer(text, show_alert=show_alert)
    except Exception as e:
        logging.warning(f"safe_alert failed: {e}")


# -----------------------------------------
#  START — ПРИВІТАННЯ
# -----------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id

    user = await get_user_from_db(uid)
    if not user:
        # Нова реєстрація
        dp.storage.data[uid] = {"step": "name"}
        await message.answer(
            "👋 Привіт! Давай познайомимось.\n\n"
            "Як тебе звати?",
            reply_markup=back_kb()
        )
        return

    # вже є профіль
    dp.storage.data[uid] = {"step": "menu"}
    await message.answer("Вітаю знову у Findsy 🤝", reply_markup=main_menu())


# -----------------------------------------
#  ГОЛОВНЕ МЕНЮ
# -----------------------------------------

@dp.message(F.text == BTN_MENU)
async def menu_return(message: types.Message):
    uid = message.from_user.id
    dp.storage.data[uid] = {"step": "menu"}
    await message.answer("Головне меню 👇", reply_markup=main_menu())


# -----------------------------------------
#  МІЙ ПРОФІЛЬ
# -----------------------------------------

@dp.message(F.text == BTN_PROFILE)
async def open_profile(message: types.Message):
    uid = message.from_user.id
    dp.storage.data[uid] = {"step": "profile"}

    user = await get_user_from_db(uid)
    if not user:
        await message.answer("У вас ще немає профілю 🤔", reply_markup=main_menu())
        return

    rating = await get_organizer_rating(uid)

    text = (
        f"👤 <b>Ваш профіль</b>\n\n"
        f"📛 Ім'я: {user.get('name') or '—'}\n"
        f"🏙 Місто: {user.get('city') or '—'}\n"
        f"🎯 Інтереси: {user.get('interests') or '—'}\n"
        f"⭐ Рейтинг організатора: {rating}/10\n\n"
        "Хочеш щось змінити?"
    )

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Змінити ім'я")],
            [KeyboardButton(text="🏙 Змінити місто")],
            [KeyboardButton(text="📸 Змінити фото")],
            [KeyboardButton(text="🎯 Змінити інтереси")],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

    if user.get("photo"):
        await safe_photo(message.chat.id, user["photo"], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


# -----------------------------------------
#  РЕДАГУВАННЯ ПРОФІЛЮ
# -----------------------------------------

@dp.message(F.text == "✏️ Змінити ім'я")
async def edit_name(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    st["step"] = "edit_name"
    await message.answer("Введіть нове ім'я:", reply_markup=back_kb())


@dp.message(F.text == "🏙 Змінити місто")
async def edit_city(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    st["step"] = "edit_city"
    await message.answer("Введіть нове місто:", reply_markup=back_kb())


@dp.message(F.text == "📸 Змінити фото")
async def edit_photo(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    st["step"] = "edit_photo"
    await message.answer("Надішліть нове фото профілю:", reply_markup=back_kb())


@dp.message(F.text == "🎯 Змінити інтереси")
async def edit_interests(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    st["step"] = "edit_interests"
    await message.answer(
        "Введіть ваші інтереси через кому 🧩\n\n"
        "Напр.: футбол, настільний теніс, подорожі",
        reply_markup=back_kb()
    )


# -----------------------------------------
#  ОБРОБКА ТЕКСТУ ПРИ РЕДАГУВАННІ
# -----------------------------------------

@dp.message()
async def handle_profile_edit(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    step = st.get("step")

    # Назад у меню
    if message.text == BTN_BACK:
        st["step"] = "menu"
        await message.answer("Повертаюсь у головне меню.", reply_markup=main_menu())
        return

    # НЕ реєстрація і НЕ створення івента → профіль
    if step == "edit_name":
        await save_user_to_db(uid, None, message.text, None, None, None)
        st["step"] = "profile"
        await message.answer("Імʼя оновлено ✔", reply_markup=main_menu())
        return

    if step == "edit_city":
        await save_user_to_db(uid, None, None, message.text, None, None)
        st["step"] = "profile"
        await message.answer("Місто оновлено ✔", reply_markup=main_menu())
        return

    if step == "edit_photo":
        await message.answer("Надішліть фото (як файл або з галереї).")
        return

    if step == "edit_interests":
        interests = ", ".join([i.strip() for i in message.text.split(",") if i.strip()])
        user = await get_user_from_db(uid)
        await save_user_to_db(
            uid,
            phone=user["phone"],
            name=user["name"],
            city=user["city"],
            photo=user["photo"],
            interests=interests
        )
        st["step"] = "profile"
        await message.answer("Інтереси оновлено ✔", reply_markup=main_menu())
        return

    # Якщо нічого з цього — передам у PART 5 (створення події)

# ================================================
#  PART 5 / 10 — CREATE EVENT FLOW
# ================================================


# -------------------------------------------------
#  КНОПКИ ДЛЯ ЛОКАЦІЇ
# -------------------------------------------------

def location_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати поточну геолокацію", request_location=True)],
            [KeyboardButton(text="📝 Ввести адресу текстом")],
            [KeyboardButton(text="📌 Обрати точку на мапі (через меню “Прикріпити”)")],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )


# -------------------------------------------------
#  СТАРТ СТВОРЕННЯ ІВЕНТА
# -------------------------------------------------

@dp.message(F.text == BTN_CREATE)
async def start_create_event(message: types.Message):
    uid = message.from_user.id

    user = await get_user_from_db(uid)
    if not user:
        await message.answer("Спочатку завершіть реєстрацію через /start 😊")
        return

    st = dp.storage.data.setdefault(uid, {})
    st.clear()

    st["step"] = "event_title"

    await message.answer(
        "📝 <b>Назва події</b>\n\n"
        "💡 Коротко опишіть суть.\n"
        "Наприклад: «Гра в покер», «Ранкова пробіжка».\n\n"
        "Ця назва допоможе людям знаходити подію за ключовими словами 🔎",
        parse_mode="HTML",
        reply_markup=back_kb()
    )


# -------------------------------------------------
#  НАЗВА → ОПИС
# -------------------------------------------------

@dp.message()
async def create_event_router(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    step = st.get("step")

    # -------- Назад --------
    if message.text == BTN_BACK:
        st["step"] = "menu"
        await message.answer("🔙 Повертаюсь у меню", reply_markup=main_menu())
        return

    # -----------------------------------------
    #  TITLE
    # -----------------------------------------
    if step == "event_title":
        st["event_title"] = message.text
        st["step"] = "event_description"

        await message.answer(
            "📄 <b>Опис події</b>\n\n"
            "Розкажіть детально, що саме буде.\n"
            "Це допоможе зацікавити людей та уникнути непорозумінь.\n\n"
            "Напр.: правила гри, формат зустрічі, що потрібно взяти.",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        return

    # -----------------------------------------
    #  DESCRIPTION → DATE
    # -----------------------------------------
    if step == "event_description":
        st["event_description"] = message.text
        st["step"] = "event_date"

        now = datetime.now()
        await message.answer(
            "📅 <b>Дата та час</b>\n\n"
            "Ви можете:\n"
            "• Ввести вручну у форматі <b>10.10.2025 19:30</b>\n"
            "• АБО обрати день у календарі нижче ⤵️",
            reply_markup=back_kb(),
            parse_mode="HTML"
        )
        await message.answer("🗓 Оберіть день:", reply_markup=month_kb(now.year, now.month))
        return

    # -----------------------------------------
    #  DATE (ручне введення)
    # -----------------------------------------
    if step == "event_date":
        dt = parse_user_datetime(message.text)
        if not dt:
            await message.answer("⛔ Не вдалося розпізнати дату. Приклад: 10.10.2025 19:30")
            return

        st["event_date"] = dt
        st["step"] = "event_location"

        await message.answer(
            "📍 <b>Локація</b>\n\n"
            "Виберіть спосіб:\n"
            "• Надіслати поточну геопозицію\n"
            "• Ввести адресу текстом\n"
            "• Обрати на мапі (через меню «Прикріпити» в Telegram)\n\n"
            "Чим точніше вказана локація — тим легше людям приєднатися.",
            parse_mode="HTML",
            reply_markup=location_choice_kb()
        )
        return

    # -----------------------------------------
    #  LOCATION (text)
    # -----------------------------------------
    if step == "event_location_name":
        st["event_location"] = message.text
        st["step"] = "event_capacity"

        await message.answer(
            "👥 <b>Місткість</b>\n\n"
            "Скільки всього людей може бути на цій події (разом з вами)?\n\n"
            "Наприклад: 6, 10, 20.",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        return

    # -----------------------------------------
    #  CAPACITY
    # -----------------------------------------
    if step == "event_capacity":
        try:
            cap = int(message.text)
            assert cap > 0
        except:
            await message.answer("❗ Введіть додатне число (напр. 6)")
            return

        st["capacity"] = cap
        st["step"] = "event_needed"

        await message.answer(
            "👤 <b>Кількість учасників, яких шукаєте</b>\n\n"
            "Скільки людей ви хочете знайти через Findsy?\n"
            "Не може перевищувати загальну місткість.",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        return

    # -----------------------------------------
    #  NEEDED COUNT
    # -----------------------------------------
    if step == "event_needed":
        try:
            need = int(message.text)
            assert 0 < need <= st["capacity"]
        except:
            await message.answer(f"❗ Введіть число від 1 до {st['capacity']}")
            return

        st["needed_count"] = need
        st["step"] = "event_photo"

        await message.answer(
            "📸 <b>Фото</b>\n\n"
            "Додайте фото події — це допоможе привернути увагу 🔥\n\n"
            "Або натисніть «Пропустити».",
            parse_mode="HTML",
            reply_markup=skip_back_kb()
        )
        return

    # -----------------------------------------
    #  PHOTO SKIP
    # -----------------------------------------
    if step == "event_photo" and message.text == BTN_SKIP:
        st["event_photo"] = None
        st["step"] = "event_review"
        await send_event_review(message.chat.id, st)
        return

    # -----------------------------------------
    #  PUBLISH (handled in Part 6)
    # -----------------------------------------

# ================================================
#  PART 6 — REVIEW, PUBLISH, REMINDERS, ADMIN
# ================================================


# -------------------------------------------------
#  🧾 ЗБІРКА REVIEW-ПОВІДОМЛЕННЯ
# -------------------------------------------------

def compose_event_review_text(st: dict) -> str:
    dt = st.get("event_date")
    dt_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "—"

    location = st.get("event_location") or (
        f"{st.get('event_lat'):.5f}, {st.get('event_lon'):.5f}"
        if st.get("event_lat") is not None else "—"
    )

    filled = max((st.get("capacity", 0) - st.get("needed_count", 0)), 0)

    return (
        "<b>Перевірте дані перед публікацією</b>\n\n"
        f"📝 <b>{st.get('event_title')}</b>\n\n"
        f"📄 {st.get('event_description')}\n\n"
        f"📅 <b>{dt_str}</b>\n"
        f"📍 {location}\n\n"
        f"👥 Заповнено: {filled}/{st.get('capacity')} • "
        f"Шукаємо ще: {st.get('needed_count')}"
    )


async def send_event_review(chat_id: int, st: dict):
    caption = compose_event_review_text(st)
    photo = st.get("event_photo")

    if photo:
        try:
            await bot.send_photo(
                chat_id,
                photo,
                caption=caption,
                parse_mode="HTML",
                reply_markup=event_publish_kb()
            )
            return
        except:
            pass

    await bot.send_message(
        chat_id,
        caption,
        parse_mode="HTML",
        reply_markup=event_publish_kb()
    )


# -------------------------------------------------
#  🟩 ПУБЛІКАЦІЯ ІВЕНТА
# -------------------------------------------------

@dp.message(F.text == "✅ Опублікувати")
async def publish_event(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})

    if st.get("step") != "event_review":
        return

    try:
        row = await save_event_to_db(
            user_id=uid,
            creator_name=st.get("creator_name", ""),
            creator_phone=st.get("creator_phone", ""),
            title=st["event_title"],
            description=st["event_description"],
            date=st["event_date"],
            location=st.get("event_location", ""),
            capacity=st["capacity"],
            needed_count=st["needed_count"],
            status="active",
            location_lat=st.get("event_lat"),
            location_lon=st.get("event_lon"),
            photo=st.get("event_photo")
        )

        # ========== Сповіщення юзеру ==========
        await message.answer("🚀 Подію опубліковано!", reply_markup=main_menu())

        # ========== Сповіщення адміну ==========
        try:
            dt_str = st["event_date"].strftime("%Y-%m-%d %H:%M")
        except:
            dt_str = "—"

        loc = st.get("event_location") or (
            f"{st.get('event_lat'):.5f}, {st.get('event_lon'):.5f}"
            if st.get("event_lat") else "—"
        )

        await notify_admin(
            "🆕 <b>Створено новий івент</b>\n"
            f"• ID: {row['id']}\n"
            f"• Організатор: {st.get('creator_name')}\n"
            f"• Назва: {st['event_title']}\n"
            f"• Дата: {dt_str}\n"
            f"• Локація: {loc}\n"
            f"• Місткість: {st['capacity']} | Шукаємо ще: {st['needed_count']}"
        )

    except Exception as e:
        logging.exception("publish error")
        await message.answer("❌ Сталася помилка публікації", reply_markup=main_menu())

    # Повертаємо у меню
    st["step"] = "menu"


# -------------------------------------------------
#  ⛔ СКАСУВАТИ СТВОРЕННЯ
# -------------------------------------------------

@dp.message(F.text == "❌ Скасувати")
async def cancel_event_creation(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})
    if st.get("step") != "event_review":
        return

    st["step"] = "menu"
    await message.answer("❌ Створення події скасовано.", reply_markup=main_menu())


# -------------------------------------------------
#  ✏ РЕДАГУВАТИ ПЕРЕД ПУБЛІКАЦІЄЮ
# -------------------------------------------------

@dp.message(F.text == "✏️ Редагувати")
async def edit_before_publish(message: types.Message):
    uid = message.from_user.id
    st = dp.storage.data.setdefault(uid, {})

    if st.get("step") != "event_review":
        return

    st["step"] = "event_title"
    await message.answer("📝 Введіть нову назву:", reply_markup=back_kb())


# -------------------------------------------------
#  🔔 Нагадування про незавершений івент
#  — фіксимо, щоб НЕ спамило
# -------------------------------------------------

async def remind_unfinished_event(uid: int):
    """Нагадує ОДИН раз після 15 хв бездіяльності."""
    await asyncio.sleep(15 * 60)

    st = dp.storage.data.get(uid)
    if not st:
        return

    # Якщо все ще створює подію
    if st.get("step", "").startswith("event_") and st.get("last_activity"):
        delta = datetime.now() - st["last_activity"]
        if delta.seconds > 15 * 60:
            step = st["step"]

            step_dict = {
                "event_title": "введіть назву події",
                "event_description": "введіть опис",
                "event_date": "вкажіть дату й час",
                "event_location": "виберіть спосіб локації",
                "event_capacity": "вкажіть місткість",
                "event_needed": "вкажіть кількість учасників яких шукаєте",
                "event_photo": "додайте фото або пропустіть"
            }

            need = step_dict.get(step, "продовжіть створення")

            await bot.send_message(
                uid,
                f"⏰ Ти не завершив створення івенту.\n"
                f"Щоб продовжити — {need}.",
                reply_markup=back_kb()
            )


def schedule_event_reminder(uid: int):
    """Запускається тільки ОДИН раз при старті створення."""
    st = dp.storage.data.setdefault(uid, {})
    if st.get("reminder_running"):
        return
    st["reminder_running"] = True
    asyncio.create_task(remind_unfinished_event(uid))


# (Reminder запускається в Part 5, коли ти натискаєш “Створити подію”)

# ============================================================
#   PART 7 — JOIN → REQUESTS → APPROVE/REJECT → CHAT FIX
# ============================================================


# ------------------------------------------------------------
#  🔗 JOIN — Пошукач хоче долучитись
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("join:"))
async def cb_join(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    seeker_id = call.from_user.id

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Перевіряємо, чи вже подавав заявку
        existing = await conn.fetchrow("""
            SELECT id, status FROM requests
            WHERE event_id=$1 AND seeker_id=$2
        """, event_id, seeker_id)

        if existing:
            status = existing["status"]
            if status == "pending":
                await safe_alert(call, "Заявку вже надіслано. Очікуйте рішення організатора.")
            elif status == "approved":
                await safe_alert(call, "Ви вже підтверджені. Перейдіть у «📨 Мої чати».")
            else:
                await safe_alert(call, "На жаль, вашу заявку відхилено.")
            await conn.close()
            return

        # Створюємо нову заявку
        req = await conn.fetchrow("""
            INSERT INTO requests (event_id, seeker_id)
            VALUES ($1,$2) RETURNING id
        """, event_id, seeker_id)

        # Дані події
        ev = await conn.fetchrow("""
            SELECT id, title, user_id
            FROM events WHERE id=$1
        """, event_id)

        # Дані пошукача
        seeker = await conn.fetchrow("""
            SELECT name, city, interests, photo
            FROM users WHERE telegram_id::text=$1
        """, str(seeker_id))

        await conn.close()
        await safe_alert(call, "Запит на участь надіслано! ✅", show_alert=False)

        # Сповіщення організатору
        if ev:
            caption = (
                f"🔔 Запит на участь у події “{ev['title']}”.\n\n"
                f"👤 Пошукач: {seeker['name'] if seeker else call.from_user.full_name}\n"
                f"📱 <code>@{call.from_user.username or '—'}</code>\n"
                f"🏙 Місто: {seeker['city'] or '—'}\n"
                f"🎯 Інтереси: {seeker['interests'] or '—'}\n\n"
                f"Що робимо?"
            )

            kb = request_actions_kb(req["id"])

            # Відправляємо з фото або без
            if seeker and seeker.get("photo"):
                try:
                    await bot.send_photo(ev["user_id"], seeker["photo"], caption=caption, reply_markup=kb)
                except:
                    await bot.send_message(ev["user_id"], caption, reply_markup=kb)
            else:
                await bot.send_message(ev["user_id"], caption, reply_markup=kb)

    except Exception:
        logging.exception("join error")
        await safe_alert(call, "Сталася помилка. Спробуйте ще раз.")


# ------------------------------------------------------------
#  💬 ВІДКРИТИ ЧАТ ЗІ ЗАЯВКИ (ORGANIZER)
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("reqchat:"))
async def cb_req_open_chat(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    uid = call.from_user.id

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        req = await conn.fetchrow("""
            SELECT * FROM requests WHERE id=$1
        """, req_id)
        if not req:
            await safe_alert(call, "Заявку не знайдено.")
            await conn.close()
            return

        ev = await conn.fetchrow("""
            SELECT id, title, user_id
            FROM events WHERE id=$1
        """, req["event_id"])

        await conn.close()

        if not ev or ev["user_id"] != uid:
            await safe_alert(call, "Лише організатор може відкрити чат.")
            return

        # Створюємо або повертаємо існуючий чат
        conv = await get_or_create_conversation(ev["id"], ev["user_id"], req["seeker_id"])

        await safe_alert(call, "💬 Чат відкрито. Перейдіть у «📨 Мої чати»", show_alert=False)

        # Сповіщення пошукачу
        until = conv["expires_at"].strftime("%Y-%m-%d %H:%M")
        await bot.send_message(
            req["seeker_id"],
            f"💬 Організатор відкрив чат щодо події “{ev['title']}”.\n"
            f"Чат активний до {until}. Перейдіть у меню «📨 Мої чати»."
        )

    except Exception:
        logging.exception("reqchat error")
        await safe_alert(call, "Сталася помилка при відкритті чату.")


# ------------------------------------------------------------
#  ✔ FIX: чат завжди відкривається навіть у “collected”
# ------------------------------------------------------------

async def safe_open_chat_for(conv_id: int, uid: int):
    """Гарантовано відкриває чат, не падає."""
    conv = await get_conversation(conv_id)

    if not conv:
        return False

    # Чат може бути тільки active
    if conv["expires_at"] <= datetime.now(timezone.utc):
        return False

    # Зберігаємо активний чат в state
    dp.storage.data.setdefault(uid, {})["active_conv_id"] = conv_id
    return True


# ------------------------------------------------------------
#  👍 APPROVE — підтвердити пошукача
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    org_id = call.from_user.id

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        async with conn.transaction():
            req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1 FOR UPDATE", req_id)
            if not req:
                await safe_alert(call, "Заявку не знайдено.")
                return

            ev = await conn.fetchrow("SELECT * FROM events WHERE id=$1 FOR UPDATE", req["event_id"])
            if not ev:
                await safe_alert(call, "Подію не знайдено.")
                return

            if ev["user_id"] != org_id:
                await safe_alert(call, "Лише організатор може підтвердити.")
                return

            # Якщо вже підтверджено
            if req["status"] == "approved":
                await safe_alert(call, "Вже підтверджено.")
                return

            # Якщо вже немає місць
            if ev["needed_count"] <= 0:
                await safe_alert(call, "Немає вільних місць.")
                return

            # Переводимо заявку у approved
            await conn.execute("""
                UPDATE requests
                SET status='approved'
                WHERE id=$1
            """, req_id)

            # Зменшуємо needed_count
            updated = await conn.fetchrow("""
                UPDATE events
                SET needed_count=needed_count-1,
                    status = CASE WHEN needed_count-1 <= 0 THEN 'collected' ELSE status END
                WHERE id=$1
                RETURNING needed_count, status, title
            """, ev["id"])

        await conn.close()

        await safe_alert(call, "Підтверджено!", show_alert=False)

        # Сповіщення учаснику
        await bot.send_message(
            req["seeker_id"],
            f"✅ Вас прийнято до події “{updated['title']}”. Перейдіть у «📨 Мої чати»."
        )

        # Якщо зібраний
        if updated["needed_count"] <= 0:
            await notify_collected(ev["id"])

    except Exception:
        logging.exception("approve error")
        await safe_alert(call, "Сталася помилка при підтвердженні.")


# ------------------------------------------------------------
#  ❌ REJECT — відхилити учасника
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        req = await conn.fetchrow("""
            UPDATE requests
            SET status='rejected'
            WHERE id=$1
            RETURNING seeker_id, event_id
        """, req_id)

        if not req:
            await conn.close()
            await safe_alert(call, "Заявку не знайдено.")
            return

        ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", req["event_id"])
        await conn.close()

        if ev["user_id"] != call.from_user.id:
            await safe_alert(call, "Лише організатор може відхилити.")
            return

        await safe_alert(call, "❌ Відхилено.", show_alert=False)

        try:
            await bot.send_message(
                req["seeker_id"],
                f"❌ На жаль, вашу заявку на подію “{ev['title']}” відхилено."
            )
        except:
            pass

    except Exception:
        logging.exception("reject error")
        await safe_alert(call, "Сталася помилка.")


# ------------------------------------------------------------
#  👥 СПИСОК УЧАСНИКІВ З USERNAME
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("event:members:"))
async def cb_event_members(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[2])

    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("""
        SELECT id, title, user_id
        FROM events WHERE id=$1
    """, ev_id)

    if not ev:
        await conn.close()
        await safe_alert(call, "Подію не знайдено.")
        return

    # Чи має право бачити список
    approved = await conn.fetchrow("""
        SELECT 1 FROM requests
        WHERE event_id=$1 AND seeker_id=$2 AND status='approved'
    """, ev_id, call.from_user.id)

    members = await conn.fetch("""
        SELECT r.seeker_id,
               u.name,
               u.city,
               u.interests,
               u.photo
        FROM requests r
        LEFT JOIN users u ON u.telegram_id::text = r.seeker_id::text
        WHERE r.event_id=$1 AND r.status='approved'
    """, ev_id)

    await conn.close()

    if ev["user_id"] != call.from_user.id and not approved:
        await safe_alert(call, "Перегляд учасників недоступний.")
        return

    await call.answer()
    await bot.send_message(call.from_user.id, f"👥 Підтверджені учасники “{ev['title']}”:")
    
    for m in members:
        uname = await get_username(m["seeker_id"])
        uname_display = f"@{uname}" if uname else "—"

        caption = (
            f"👤 <b>{m['name']}</b>\n"
            f"📱 {uname_display}\n"
            f"🏙 {m['city']}\n"
            f"🎯 {m['interests']}"
        )

        if m["photo"]:
            try:
                await bot.send_photo(call.from_user.id, m["photo"], caption=caption, parse_mode="HTML")
                continue
            except:
                pass

        await bot.send_message(call.from_user.id, caption, parse_mode="HTML")
# ============================================================
#   PART 8 — МОЇ ІВЕНТИ: ФІЛЬТРИ, СПИСОК, INFO, LEAVE, EDIT
# ============================================================


# ------------------------------------------------------------
#  🧭 КНОПКИ ГОЛОВНОГО МЕНЮ «Мої івенти»
# ------------------------------------------------------------

@dp.message(F.text == BTN_MY_EVENTS)
async def open_my_events(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st["step"] = "my_events_filters"

    await message.answer("Оберіть категорію:", reply_markup=types.ReplyKeyboardRemove())
    await bot.send_message(uid, "Фільтри:", reply_markup=myevents_filter_kb())


# ------------------------------------------------------------
#  🧭 Inline: показ фільтрів
# ------------------------------------------------------------

@dp.callback_query(F.data == "myevents:filters")
async def cb_myevents_filters(call: types.CallbackQuery):
    await call.answer()
    await bot.send_message(call.from_user.id, "Фільтри:", reply_markup=myevents_filter_kb())


# ------------------------------------------------------------
#  📋 Inline: вибрано фільтр → показуємо список
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("myevents:filter:"))
async def cb_myevents_filter(call: types.CallbackQuery):
    kind = call.data.split(":")[2]
    uid = call.from_user.id

    rows = await list_user_events(uid, filter_kind=kind)
    await call.answer()

    if not rows:
        await bot.send_message(
            uid,
            f"Подій не знайдено ({kind}).",
            reply_markup=myevents_filter_kb()
        )
        return

    await bot.send_message(uid, f"Ваші події ({kind}):", reply_markup=my_events_kb(rows))


# ------------------------------------------------------------
#  ℹ️ Інформація про подію
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("event:info:"))
async def cb_event_info(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[2])
    conn = await asyncpg.connect(DATABASE_URL)

    ev = await conn.fetchrow("SELECT * FROM events WHERE id=$1", ev_id)
    await conn.close()

    if not ev:
        await safe_alert(call, "Подію не знайдено.")
        return

    dt = ev["date"].strftime("%Y-%m-%d %H:%M") if ev["date"] else "—"
    filled = max((ev["capacity"] or 0) - (ev["needed_count"] or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{ev['capacity']}   •   шукаємо ще: {ev['needed_count']}"

    rating = await get_organizer_avg_rating(ev["user_id"])
    rating_line = f"\n⭐ Рейтинг організатора: {rating:.1f}/10" if rating else ""

    text = (
        f"<b>{ev['title']}</b>\n"
        f"📅 {dt}\n"
        f"📍 {ev['location'] or '—'}\n"
        f"{places_line}\n"
        f"Статус: {ev['status']}{rating_line}\n\n"
        f"{(ev['description'] or '').strip()[:600]}"
    )

    await call.answer()

    if ev.get("photo"):
        try:
            await bot.send_photo(call.from_user.id, ev["photo"], caption=text, parse_mode="HTML")
            return
        except:
            pass

    await bot.send_message(call.from_user.id, text, parse_mode="HTML")


# ------------------------------------------------------------
#  🚪 ВИЙТИ З ІВЕНТУ (пошукач)
# ------------------------------------------------------------

async def remove_user_from_event(event_id: int, seeker_id: int):
    """Пошукач виходить з події."""
    conn = await asyncpg.connect(DATABASE_URL)

    # Чи був approved?
    row = await conn.fetchrow("""
        UPDATE requests
        SET status='left'
        WHERE event_id=$1 AND seeker_id=$2 AND status='approved'
        RETURNING event_id
    """, event_id, seeker_id)

    if not row:
        await conn.close()
        return False

    # Повернути 1 місце
    await conn.execute("""
        UPDATE events
        SET needed_count = needed_count + 1
        WHERE id=$1
    """, event_id)

    await conn.close()
    return True


@dp.callback_query(F.data.startswith("event:leave:"))
async def cb_event_leave(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    ok = await remove_user_from_event(ev_id, uid)

    if not ok:
        await safe_alert(call, "Не вийшло вийти з події.")
        return

    # Сповіщаємо організатора
    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("SELECT title, user_id, status FROM events WHERE id=$1", ev_id)
    await conn.close()

    await safe_alert(call, "Ви вийшли з події.", show_alert=False)

    text = (
        f"ℹ️ Користувач @{call.from_user.username or '—'} вийшов з події “{ev['title']}”."
    )
    await bot.send_message(ev["user_id"], text)

    # Якщо подія була collected → пропонуємо відкрити знову
    if ev["status"] == "collected":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="♻️ Зробити активною", callback_data=f"event:open:{ev_id}")],
            [InlineKeyboardButton(text="❌ Залишити як є", callback_data="noop")]
        ])
        await bot.send_message(ev["user_id"], "Хочете знову відкрити подію?", reply_markup=kb)


# ------------------------------------------------------------
#  🗑 DELETE / CANCEL / OPEN
# ------------------------------------------------------------

async def refresh_my_events_inline(call, owner_id):
    """Оновлює inline список після змін."""
    rows = await list_user_events(owner_id, FILTER_ACTIVE)

    try:
        await call.message.edit_reply_markup(reply_markup=my_events_kb(rows))
    except:
        pass


@dp.callback_query(F.data.startswith("event:delete:"))
async def cb_event_delete(call):
    ev_id = int(call.data.split(":")[2])
    ok = await update_event_status(ev_id, call.from_user.id, "deleted")

    await safe_alert(call, "Подію приховано." if ok else "Не вдалося видалити.")
    if ok:
        await refresh_my_events_inline(call, call.from_user.id)


@dp.callback_query(F.data.startswith("event:cancel:"))
async def cb_event_cancel(call):
    ev_id = int(call.data.split(":")[2])
    ok = await update_event_status(ev_id, call.from_user.id, "cancelled")

    await safe_alert(call, "Подію скасовано." if ok else "Не вдалося скасувати.")
    if ok:
        await refresh_my_events_inline(call, call.from_user.id)


@dp.callback_query(F.data.startswith("event:open:"))
async def cb_event_open(call):
    ev_id = int(call.data.split(":")[2])

    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("""
        SELECT needed_count
        FROM events WHERE id=$1 AND user_id::text=$2
    """, ev_id, str(call.from_user.id))
    await conn.close()

    if not ev:
        await safe_alert(call, "Подію не знайдено.")
        return

    if ev["needed_count"] <= 0:
        await safe_alert(call, "Немає вільних місць — не можна відкрити.")
        return

    ok = await update_event_status(ev_id, call.from_user.id, "active")
    await safe_alert(call, "Подію знову активовано!" if ok else "Не вдалося.")
    
    if ok:
        await refresh_my_events_inline(call, call.from_user.id)
# ============================================================
#   PART 9 — ЧАТИ: OPEN / RELAY / HISTORY / CLOSE / STOPCHAT
# ============================================================

# ------------------------------------------------------------
#  🆔 Хелпер: отримати Telegram username
# ------------------------------------------------------------

async def get_username(user_id: int) -> str | None:
    try:
        u = await bot.get_chat(user_id)
        return u.username
    except:
        return None


# ------------------------------------------------------------
#  💬 ВІДКРИТИ ЧАТ (з My Chats)
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("chat:open:"))
async def cb_chat_open(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    conv = await get_conversation(conv_id)

    if not conv:
        await safe_alert(call, "Чат не знайдено.")
        return

    if conv["status"] != "active":
        await safe_alert(call, "Чат завершено.")
        return

    # Час вийшов?
    if conv["expires_at"] <= datetime.now(timezone.utc):
        await safe_alert(call, "Чат вже прострочено.")
        return

    # Перевірка участі
    if not (conv["organizer_id"] == uid or conv["seeker_id"] == uid):
        await safe_alert(call, "Це не ваш чат.")
        return

    # Активуємо чат у state
    st = user_states.setdefault(uid, {})
    st["active_conv_id"] = conv_id

    await call.answer()

    # Показуємо історію
    msgs = await load_last_messages(conv_id, 20)
    if msgs:
        transcript = []
        for m in reversed(msgs):
            who = "Ви" if m["sender_id"] == uid else "Співрозмовник"
            ts = m["created_at"].strftime("%H:%M")
            transcript.append(f"[{ts}] {who}: {m['text']}")
        await bot.send_message(uid, "📜 Останні повідомлення:\n" + "\n".join(transcript))

    await bot.send_message(
        uid,
        "💬 Чат відкрито.\nПишіть — я перешлю співрозмовнику.",
        reply_markup=main_menu()
    )


# ------------------------------------------------------------
#  📜 ІСТОРІЯ ЧАТУ
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("chat:history:"))
async def cb_chat_history(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    conv = await get_conversation(conv_id)

    if not conv:
        await safe_alert(call, "Чат не знайдено.")
        return

    if not (conv["organizer_id"] == uid or conv["seeker_id"] == uid):
        await safe_alert(call, "Це не ваш чат.")
        return

    await call.answer()

    msgs = await load_last_messages(conv_id, 40)
    if not msgs:
        await bot.send_message(uid, "Історія порожня.")
        return

    transcript = []
    for m in reversed(msgs):
        who = "Ви" if m["sender_id"] == uid else "Співрозмовник"
        ts = m["created_at"].strftime("%Y-%m-%d %H:%M")
        transcript.append(f"[{ts}] {who}: {m['text']}")

    await bot.send_message(uid, "📜 Повна історія:\n" + "\n".join(transcript))


# ------------------------------------------------------------
#  ❌ ЗАКРИТИ ЧАТ
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("chat:close:"))
async def cb_chat_close(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    conv = await get_conversation(conv_id)
    if not conv:
        await safe_alert(call, "Чат не знайдено.")
        return

    await close_conversation(conv_id, reason="closed")

    await safe_alert(call, "Чат закрито.", show_alert=False)

    # Сповіщаємо іншого учасника
    other_id = conv["seeker_id"] if uid == conv["organizer_id"] else conv["organizer_id"]
    try:
        await bot.send_message(other_id, "ℹ️ Співрозмовник завершив чат.")
    except:
        pass

    # Чистимо state
    st = user_states.setdefault(uid, {})
    st["active_conv_id"] = None

    await bot.send_message(uid, "Повернення до меню:", reply_markup=main_menu())


# ------------------------------------------------------------
#  🛑 /stopchat — ручне завершення
# ------------------------------------------------------------

@dp.message(Command("stopchat"))
async def stop_chat(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    conv_id = st.get("active_conv_id")

    if not conv_id:
        await message.answer("У вас немає активного чату.", reply_markup=main_menu())
        return

    conv = await get_conversation(conv_id)
    if not conv or conv["status"] != "active":
        st["active_conv_id"] = None
        await message.answer("Чат вже завершено.", reply_markup=main_menu())
        return

    await close_conversation(conv_id, reason="closed")

    other = conv["seeker_id"] if uid == conv["organizer_id"] else conv["organizer_id"]

    await message.answer("Чат завершено.", reply_markup=main_menu())

    try:
        await bot.send_message(other, "ℹ️ Співрозмовник завершив чат.")
    except:
        pass

    st["active_conv_id"] = None


# ------------------------------------------------------------
#  ✉️ RELAY — Пересилка повідомлень у чаті
# ------------------------------------------------------------

@dp.message(F.text)
async def relay_chat(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()

    st = user_states.setdefault(uid, {})
    conv_id = st.get("active_conv_id")

    # Якщо немає активного чату → це не relay
    if not conv_id:
        return  # інші PART-и оброблять

    conv = await get_conversation(conv_id)

    if not conv or conv["status"] != "active":
        st["active_conv_id"] = None
        await message.answer("Чат недоступний.", reply_markup=main_menu())
        return

    if conv["expires_at"] <= datetime.now(timezone.utc):
        st["active_conv_id"] = None
        await message.answer("Чат прострочено.", reply_markup=main_menu())
        return

    # Визначаємо співрозмовника
    partner = conv["seeker_id"] if uid == conv["organizer_id"] else conv["organizer_id"]

    # Зберігаємо
    try:
        await save_message(conv_id, uid, text)
    except Exception as e:
        logging.warning(f"save_message failed: {e}")

    # Пересилаємо
    try:
        await bot.send_message(
            partner,
            f"💬 <b>{message.from_user.full_name}</b>:\n{text}",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"relay failed: {e}")

    return
# ============================================================
#   PART 10 — Rating, Reminders, Auto-Finish, Main()
# ============================================================

# ------------------------------------------------------------
#  ⭐ ЗБЕРЕГТИ РЕЙТИНГ
# ------------------------------------------------------------

async def save_rating(event_id: int, rater_id: int, rating: int):
    conn = await asyncpg.connect(DATABASE_URL)

    # Перевірити, чи вже є оцінка
    exists = await conn.fetchrow("""
        SELECT id FROM ratings
        WHERE event_id=$1 AND rater_id=$2
    """, event_id, rater_id)

    if exists:
        await conn.close()
        return False

    await conn.execute("""
        INSERT INTO ratings (event_id, rater_id, rating)
        VALUES ($1,$2,$3)
    """, event_id, rater_id, rating)

    await conn.close()
    return True


# ------------------------------------------------------------
#  ⭐ СЕРЕДНІЙ РЕЙТИНГ ОРГАНІЗАТОРА
# ------------------------------------------------------------

async def get_organizer_avg_rating(organizer_id: int) -> float | None:
    conn = await asyncpg.connect(DATABASE_URL)

    rows = await conn.fetch("""
        SELECT rating FROM ratings r
        JOIN events e ON e.id = r.event_id
        WHERE e.user_id = $1
    """, organizer_id)

    await conn.close()

    if not rows:
        return None

    return sum(r["rating"] for r in rows) / len(rows)


# ------------------------------------------------------------
#  🎯 Надіслати форму оцінки
# ------------------------------------------------------------

async def send_rating_form(event_id: int, user_id: int, title: str, organizer_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1️⃣", callback_data=f"rate:{event_id}:1"),
            InlineKeyboardButton(text="2️⃣", callback_data=f"rate:{event_id}:2"),
            InlineKeyboardButton(text="3️⃣", callback_data=f"rate:{event_id}:3"),
            InlineKeyboardButton(text="4️⃣", callback_data=f"rate:{event_id}:4"),
            InlineKeyboardButton(text="5️⃣", callback_data=f"rate:{event_id}:5"),
        ],
        [
            InlineKeyboardButton(text="6️⃣", callback_data=f"rate:{event_id}:6"),
            InlineKeyboardButton(text="7️⃣", callback_data=f"rate:{event_id}:7"),
            InlineKeyboardButton(text="8️⃣", callback_data=f"rate:{event_id}:8"),
            InlineKeyboardButton(text="9️⃣", callback_data=f"rate:{event_id}:9"),
            InlineKeyboardButton(text="🔟", callback_data=f"rate:{event_id}:10"),
        ],
        [
            InlineKeyboardButton(text="Не зміг долучитись", callback_data=f"rate:{event_id}:0")
        ]
    ])

    await bot.send_message(
        user_id,
        f"⭐ Оцініть організатора події «{title}».",
        reply_markup=kb
    )


# ------------------------------------------------------------
#  ⭐ Callback — обробка оцінки
# ------------------------------------------------------------

@dp.callback_query(F.data.startswith("rate:"))
async def cb_rate(call: types.CallbackQuery):
    _, event_id, score = call.data.split(":")
    event_id = int(event_id)
    rating = int(score)
    uid = call.from_user.id

    ok = await save_rating(event_id, uid, rating)

    await call.answer()

    if not ok:
        await bot.send_message(uid, "Ви вже оцінили цю подію.", reply_markup=main_menu())
        return

    await bot.send_message(uid, "Дякуємо за оцінку! ⭐", reply_markup=main_menu())


# ------------------------------------------------------------
#  ⏰ Нагадування за 12 год / 1 год
# ------------------------------------------------------------

async def send_upcoming_reminders():
    conn = await asyncpg.connect(DATABASE_URL)
    now = datetime.now(timezone.utc)

    # Події, які стартують через 12 годин
    soon12 = await conn.fetch("""
        SELECT * FROM events
        WHERE status='active'
        AND date BETWEEN $1 AND $2
    """, now + timedelta(hours=11, minutes=55), now + timedelta(hours=12, minutes=5))

    # Події, які стартують через 1 годину
    soon1 = await conn.fetch("""
        SELECT * FROM events
        WHERE status='active'
        AND date BETWEEN $1 AND $2
    """, now + timedelta(minutes=55), now + timedelta(minutes=65))

    await conn.close()

    # Надсилаємо пошукачам
    async def notify(event, before):
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch("""
            SELECT seeker_id FROM requests
            WHERE event_id=$1 AND status='approved'
        """, event["id"])
        await conn.close()

        for u in users:
            await safe_send(
                u["seeker_id"],
                f"⏰ Нагадування!\nЧерез {before} відбудеться подія: “{event['title']}”."
            )

    for ev in soon12:
        await notify(ev, "12 годин")

    for ev in soon1:
        await notify(ev, "1 годину")


# ------------------------------------------------------------
#  📌 Автоматичне завершення подій
# ------------------------------------------------------------

async def finish_past_events():
    now = datetime.now(timezone.utc)

    conn = await asyncpg.connect(DATABASE_URL)

    # Знайти події, які вже пройшли, але ще не закриті
    rows = await conn.fetch("""
        SELECT * FROM events
        WHERE status='active'
        AND date < $1
    """, now)

    await conn.close()

    for ev in rows:
        # Переводимо у finished
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            UPDATE events
            SET status='finished'
            WHERE id=$1
        """, ev["id"])
        await conn.close()

        # Надсилаємо форму оцінки всім approved
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch("""
            SELECT seeker_id FROM requests
            WHERE event_id=$1 AND status='approved'
        """, ev["id"])
        await conn.close()

        for u in users:
            await send_rating_form(ev["id"], u["seeker_id"], ev["title"], ev["user_id"])

        # Організатор також оцінює
        await send_rating_form(ev["id"], ev["user_id"], ev["title"], ev["user_id"])


# ------------------------------------------------------------
#  🔄 Головний цикл (постійні задачі)
# ------------------------------------------------------------

async def background_scheduler():
    while True:
        await send_upcoming_reminders()
        await finish_past_events()
        await asyncio.sleep(60)   # перевіряємо кожну хвилину


# ------------------------------------------------------------
#  🚀 main()
# ------------------------------------------------------------

async def main():
    asyncio.create_task(background_scheduler())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())











































