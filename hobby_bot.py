import os
import logging
import asyncio
import re
import calendar as calmod
from datetime import datetime, timedelta, timezone, date

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- Init ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Environment variables BOT_TOKEN and DATABASE_URL must be set")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_states: dict[int, dict] = {}

# --- Keyboards ---
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Мій профіль")],
        [KeyboardButton(text="➕ Створити подію")],
        [KeyboardButton(text="🔍 Знайти подію")]
    ],
    resize_keyboard=True
)
def get_back_button() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)

def location_choice_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            [KeyboardButton(text="📝 Ввести адресу текстом"), KeyboardButton(text="⏭ Пропустити локацію")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )

def radius_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="3"), KeyboardButton(text="5")],
            [KeyboardButton(text="10"), KeyboardButton(text="20")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )

def search_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔎 За ключовим словом")],
            [KeyboardButton(text="📍 Поруч зі мною")],
            [KeyboardButton(text="🔮 За моїми інтересами")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )

def event_publish_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='✅ Опублікувати'), KeyboardButton(text='✏️ Редагувати')],
            [KeyboardButton(text='❌ Скасувати')],
            [KeyboardButton(text='⬅️ Назад')]
        ], resize_keyboard=True
    )

def event_join_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")]])

def approve_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve:{req_id}"),
        InlineKeyboardButton(text="❌ Відхилити",   callback_data=f"reject:{req_id}")
    ]])

# --- Calendar (inline) ---
def month_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    # Header: month name
    month_name = datetime(year, month, 1).strftime("%B %Y")
    kb.append([InlineKeyboardButton(text=month_name, callback_data="cal:noop")])
    # Weekdays
    kb.append([InlineKeyboardButton(t, callback_data="cal:noop") for t in ["Mo","Tu","We","Th","Fr","Sa","Su"]])
    # Days
    for week in calmod.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal:noop"))
            else:
                row.append(InlineKeyboardButton(str(d), callback_data=f"cal:date:{year:04d}-{month:02d}-{d:02d}"))
        kb.append(row)
    # Nav
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1)  if month == 12 else (year, month + 1)
    kb.append([
        InlineKeyboardButton("«", callback_data=f"cal:nav:{prev_y:04d}-{prev_m:02d}"),
        InlineKeyboardButton("»", callback_data=f"cal:nav:{next_y:04d}-{next_m:02d}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("cal:nav:"))
async def cal_nav(call: types.CallbackQuery):
    ym = call.data.split(":")[2]
    y, m = map(int, ym.split("-"))
    try:
        await call.message.edit_reply_markup(reply_markup=month_kb(y, m))
    except Exception:
        pass
    await call.answer()

@dp.callback_query(F.data.startswith("cal:date:"))
async def cal_pick_date(call: types.CallbackQuery):
    dstr = call.data.split(":")[2]  # YYYY-MM-DD
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['picked_date'] = datetime.strptime(dstr, "%Y-%m-%d").date()
    st['step'] = 'create_event_time'
    await call.message.answer(f"⏰ Обрано {dstr}. Введіть час у форматі HH:MM (наприклад, 19:30).", reply_markup=get_back_button())
    await call.answer()

# --- Human date parser ---
MONTHS = {
    # uk (genitive)
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
    # ru (genitive)
    "января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
    "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12,
    # en
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}
def parse_user_datetime(text: str) -> datetime | None:
    s = text.strip().lower()
    # 1) dd.mm.yyyy hh:mm
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        dd, mm, yyyy, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
    # 2) yyyy-mm-dd hh:mm
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        yyyy, mm, dd, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
    # 3) dd <month> yyyy hh:mm
    m = re.match(r"^(\d{1,2})\s+([a-zа-яіїєё]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})$", s, re.IGNORECASE)
    if m:
        dd = int(m.group(1)); mon = m.group(2); yyyy = int(m.group(3)); HH=int(m.group(4)); MM=int(m.group(5))
        mm = MONTHS.get(mon, None)
        if mm:
            return datetime(yyyy, mm, dd, HH, MM)
    return None

def parse_time_hhmm(s: str) -> tuple[int,int] | None:
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", s.strip())
    if not m: return None
    HH, MM = map(int, m.groups())
    if 0 <= HH <= 23 and 0 <= MM <= 59:
        return HH, MM
    return None

# --- DB helpers ---
async def get_user_from_db(user_id: int) -> asyncpg.Record | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id::text = $1", str(user_id))
    finally:
        await conn.close()

async def save_user_to_db(user_id: int, phone: str, name: str, city: str, photo: str, interests: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            INSERT INTO users (telegram_id, phone, name, city, photo, interests)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (telegram_id) DO UPDATE SET
              phone=EXCLUDED.phone, name=EXCLUDED.name, city=EXCLUDED.city,
              photo=EXCLUDED.photo, interests=EXCLUDED.interests
        """, user_id, phone, name, city, photo, interests)
    finally:
        await conn.close()

async def save_event_to_db(
    user_id: int, creator_name: str, creator_phone: str,
    title: str, description: str, date: datetime, location: str,
    capacity: int, needed_count: int, status: str,
    location_lat: float | None = None, location_lon: float | None = None,
    photo: str | None = None
):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("""
            INSERT INTO events (
                user_id, creator_name, creator_phone, title,
                description, date, location, capacity, needed_count, status,
                location_lat, location_lon, photo
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            RETURNING id, created_at
        """, user_id, creator_name or '', creator_phone or '', title, description, date, location,
           capacity, needed_count, status, location_lat, location_lon, photo)
        return row
    finally:
        await conn.close()

async def find_events_by_kw(keyword: str, limit: int = 10):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT e.*,
                   u.name AS organizer_name, u.interests AS organizer_interests,
                   (SELECT COUNT(*) FROM events ev2 WHERE ev2.user_id = e.user_id) AS org_count
            FROM events e
            LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active' AND (e.title ILIKE $1 OR e.description ILIKE $1)
            ORDER BY e.date ASC NULLS LAST, e.id DESC
            LIMIT $2
        """, f"%{keyword}%", limit)
        return rows
    finally:
        await conn.close()

async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 10):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            WITH params AS (SELECT $1::float AS lat, $2::float AS lon, $3::float AS r)
            SELECT e.*,
                   u.name AS organizer_name, u.interests AS organizer_interests,
                   (SELECT COUNT(*) FROM events ev2 WHERE ev2.user_id = e.user_id) AS org_count,
                   (6371 * acos(
                       cos(radians(p.lat)) * cos(radians(e.location_lat)) *
                       cos(radians(e.location_lon) - radians(p.lon)) +
                       sin(radians(p.lat)) * sin(radians(e.location_lat))
                   )) AS dist_km
            FROM events e
            JOIN params p ON true
            LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active'
              AND e.location_lat IS NOT NULL AND e.location_lon IS NOT NULL
              AND (6371 * acos(
                       cos(radians(p.lat)) * cos(radians(e.location_lat)) *
                       cos(radians(e.location_lon) - radians(p.lon)) +
                       sin(radians(p.lat)) * sin(radians(e.location_lat))
                  )) <= p.r
            ORDER BY dist_km ASC
            LIMIT $4
        """, lat, lon, radius_km, limit)
        return rows
    finally:
        await conn.close()

async def find_events_by_user_interests(user_id: int, limit: int = 20):
    # читаємо інтереси користувача -> розбиваємо на ключові слова
    user = await get_user_from_db(user_id)
    if not user or not user.get('interests'):
        return []
    tokens = [t.strip() for t in user['interests'].split(",") if t.strip()]
    if not tokens:
        return []
    patterns = [f"%{t}%" for t in tokens]
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT e.*,
                   u.name AS organizer_name, u.interests AS organizer_interests,
                   (SELECT COUNT(*) FROM events ev2 WHERE ev2.user_id = e.user_id) AS org_count
            FROM events e
            LEFT JOIN users u ON u.telegram_id::text = e.user_id::text
            WHERE e.status='active'
              AND (e.title ILIKE ANY($1::text[]) OR e.description ILIKE ANY($1::text[]))
            ORDER BY e.date ASC NULLS LAST, e.id DESC
            LIMIT $2
        """, patterns, limit)
        return rows
    finally:
        await conn.close()

async def get_active_conversation_for_user(uid: int) -> asyncpg.Record | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("""
            SELECT * FROM conversations
            WHERE status='active' AND expires_at > now()
              AND (organizer_id=$1 OR seeker_id=$1)
            ORDER BY created_at DESC LIMIT 1
        """, uid)
    finally:
        await conn.close()

async def close_conversation(conv_id: int, reason: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("UPDATE conversations SET status=$2 WHERE id=$1", conv_id, 'expired' if reason=='expired' else 'closed')
    finally:
        await conn.close()

# --- Debug / Start ---
@dp.message(Command("dbinfo"))
async def cmd_dbinfo(message: types.Message):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("""
            SELECT current_database() AS db, current_user AS usr, current_schema() AS sch,
                   current_setting('search_path') AS search_path,
                   current_setting('server_version') AS ver,
                   current_setting('TimeZone', true) AS tz;
        """); await conn.close()
        await message.answer(
            f"🗄 DB={row['db']}\n👤 user={row['usr']}\n📚 schema={row['sch']}\n"
            f"🔎 search_path={row['search_path']}\n🐘 pg={row['ver']}\n🌍 tz={row['tz']}"
        )
    except Exception as e:
        await message.answer(f"❌ DB error: {e}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    try:
        user = await get_user_from_db(uid)
    except Exception:
        st['step'] = 'menu'
        await message.answer("⚠️ Не вдалося з'єднатися з БД, робота обмежена.", reply_markup=main_menu)
        return
    if user:
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}! Оберіть дію:", reply_markup=main_menu)
    else:
        st.clear(); st.update({'step': 'name', 'phone': None})
        await message.answer("👋 Вітаю! Введіть ваше ім'я:\n<i>Ім’я буде видно в заявках.</i>", reply_markup=get_back_button(), parse_mode="HTML")

# --- Photo handlers ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    step = st.get('step')

    if step == 'photo':
        st['photo'] = message.photo[-1].file_id
        st['step'] = 'interests'
        await message.answer("🎯 Інтереси (через кому):", reply_markup=get_back_button()); return

    if step == 'create_event_photo':
        st['event_photo'] = message.photo[-1].file_id
        await message.answer("📸 Фото збережено. Натисніть «✅ Опублікувати» або відредагуйте.", reply_markup=event_publish_kb()); return

@dp.message(F.text == "⬅️ Назад")
async def back_to_menu(message: types.Message):
    user_states[message.from_user.id] = {'step': 'menu'}
    await message.answer("⬅️ Повертаємось у меню", reply_markup=main_menu)

# --- Main FSM ---
@dp.message(F.text)
async def handle_steps(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    step = st.get('step')

    # Меню
    if text == "👤 Мій профіль" and step in (None, 'menu'):
        user = await get_user_from_db(uid)
        if user and user.get('photo'):
            await message.answer_photo(user['photo'], caption=f"👤 Профіль:\n📛 {user['name']}\n🏙 {user['city']}\n🎯 {user['interests']}",
                                       reply_markup=types.ReplyKeyboardMarkup(
                                           keyboard=[[KeyboardButton(text='✏️ Змінити профіль'), KeyboardButton(text='⬅️ Назад')]],
                                           resize_keyboard=True
                                       ))
        else:
            await message.answer("Профіль не знайдено або без фото.", reply_markup=main_menu)
        return

    if text == "✏️ Змінити профіль" and step == 'menu':
        user = await get_user_from_db(uid)
        st.clear(); st.update({'step': 'name', 'phone': user.get('phone','') if user else ''})
        await message.answer("✍️ Нове ім'я:", reply_markup=get_back_button()); return

    if text == "➕ Створити подію":
        if step == 'name': return
        user = await get_user_from_db(uid)
        if not user:
            await message.answer("⚠️ Спочатку зареєструйтесь через /start"); return
        st.clear()
        st.update({'step': 'create_event_title', 'creator_name': user.get('name',''), 'creator_phone': user.get('phone','')})
        await message.answer("📝 Назва події:\n<i>Шукають за назвою — пишіть чітко й без помилок.</i>", reply_markup=get_back_button(), parse_mode="HTML"); return

    if text == "🔍 Знайти подію" and step in (None, 'menu'):
        st['step'] = 'search_menu'
        await message.answer("Оберіть режим пошуку:", reply_markup=search_menu_kb()); return

    # Реєстрація
    if step == 'name':
        st['name'] = text; st['step'] = 'city'
        await message.answer("🏙 Місто:", reply_markup=get_back_button()); return
    if step == 'city':
        st['city'] = text; st['step'] = 'photo'
        await message.answer("🖼 Надішліть фото профілю:", reply_markup=get_back_button()); return
    if step == 'interests':
        st['interests'] = [i.strip() for i in text.split(',') if i.strip()]
        try:
            await save_user_to_db(uid, st.get('phone',''), st.get('name',''), st.get('city',''), st.get('photo',''), ', '.join(st['interests']))
            await message.answer('✅ Профіль збережено!', reply_markup=main_menu)
        except Exception as e:
            logging.error('save profile: %s', e); await message.answer('❌ Не вдалося зберегти профіль.', reply_markup=main_menu)
        st['step'] = 'menu'; return

    # Створення події
    if step == 'create_event_title':
        st['event_title'] = text; st['step'] = 'create_event_description'
        await message.answer("📝 Опис:\n<i>Кількома реченнями, щоб хотілося приєднатися.</i>", reply_markup=get_back_button(), parse_mode="HTML"); return

    if step == 'create_event_description':
        st['event_description'] = text; st['step'] = 'create_event_date'
        now = datetime.now()
        await message.answer(
            "📅 Дата та час.\n"
            "— Можна написати так: <code>10 жовтня 2025 19:30</code> або <code>10.10.2025 19:30</code>.\n"
            "— Або оберіть день у календарі нижче, після цього я запитаю час.",
            reply_markup=get_back_button(), parse_mode="HTML"
        )
        # Показуємо календар
        await message.answer("🗓 Оберіть день:", reply_markup=None)
        await message.answer(".", reply_markup=month_kb(now.year, now.month))  # окремим повідомленням тільки інлайн-кб
        return

    if step == 'create_event_date':
        # (залишено для сумісності, але по факту ми вже одразу показуємо календар)
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer("Не впізнав дату. Приклад: 10 жовтня 2025 19:30 або скористайтесь календарем.", reply_markup=get_back_button())
            return
        st['event_date'] = dt; st['step'] = 'create_event_location'
        await message.answer("📍 Локація (опційно): Надішліть геоточкy, введіть адресу або пропустіть.", reply_markup=location_choice_kb()); return

    if step == 'create_event_time':
        t = parse_time_hhmm(text)
        if not t:
            await message.answer("Формат часу HH:MM, напр. 19:30", reply_markup=get_back_button()); return
        d: date = st.get('picked_date')  # set by calendar
        dt = datetime(d.year, d.month, d.day, t[0], t[1])
        st['event_date'] = dt; st['step'] = 'create_event_location'
        await message.answer("📍 Локація (опційно): Надішліть геоточкy, введіть адресу або пропустіть.", reply_markup=location_choice_kb()); return

    if step == 'create_event_location':
        if text == "📝 Ввести адресу текстом":
            st['step'] = 'create_event_location_name'
            await message.answer("🏷 Введіть адресу/назву місця:", reply_markup=get_back_button()); return
        if text == "⏭ Пропустити локацію":
            st['event_location'] = ''; st['event_lat'] = None; st['event_lon'] = None
            st['step'] = 'create_event_capacity'
            await message.answer("👥 Скільки всього місць? (позитивне число)", reply_markup=get_back_button()); return
        await message.answer("Надішліть геолокацію кнопкою або оберіть опцію нижче.", reply_markup=location_choice_kb()); return

    if step == 'create_event_location_name':
        st['event_location'] = text; st['step'] = 'create_event_capacity'
        await message.answer("👥 Скільки всього місць? (позитивне число)", reply_markup=get_back_button()); return

    if step == 'create_event_capacity':
        try:
            cap = int(text); assert cap > 0
        except Exception:
            await message.answer("❗ Введіть позитивне число.", reply_markup=get_back_button()); return
        st['capacity'] = cap; st['step'] = 'create_event_needed'
        await message.answer("👤 Скільки учасників шукаєте? (1..місткість)", reply_markup=get_back_button()); return

    if step == 'create_event_needed':
        try:
            need = int(text); cap = st['capacity']; assert 0 < need <= cap
        except Exception:
            await message.answer(f"❗ Від 1 до {st['capacity']}", reply_markup=get_back_button()); return
        st['needed_count'] = need; st['step'] = 'create_event_photo'
        await message.answer("📸 Фото події (опційно): надішліть фото або натисніть «✅ Опублікувати».", reply_markup=event_publish_kb()); return

    if text == '✅ Опублікувати' and step == 'create_event_photo':
        try:
            await save_event_to_db(
                user_id=uid,
                creator_name=st.get('creator_name',''),
                creator_phone=st.get('creator_phone',''),
                title=st['event_title'],
                description=st['event_description'],
                date=st['event_date'],
                location=st.get('event_location',''),
                capacity=st['capacity'],
                needed_count=st['needed_count'],
                status='active',
                location_lat=st.get('event_lat'),
                location_lon=st.get('event_lon'),
                photo=st.get('event_photo')
            )
            await message.answer("🚀 Подію опубліковано!", reply_markup=main_menu)
        except Exception as e:
            logging.exception("publish"); await message.answer(f"❌ Помилка публікації: {e}", reply_markup=main_menu)
        user_states[uid] = {'step': 'menu'}; return

    if text == '✏️ Редагувати' and step == 'create_event_photo':
        st['step'] = 'create_event_title'
        await message.answer("📝 Нова назва:", reply_markup=get_back_button()); return

    if text == '❌ Скасувати' and step == 'create_event_photo':
        user_states[uid] = {'step': 'menu'}; await message.answer("❌ Створення події скасовано.", reply_markup=main_menu); return

    # Пошук
    if step == 'search_menu' and text == "🔎 За ключовим словом":
        st['step'] = 'search_keyword_wait'
        await message.answer("Введіть ключове слово:", reply_markup=get_back_button()); return

    if step == 'search_menu' and text == "📍 Поруч зі мною":
        st['step'] = 'search_geo_wait_location'
        await message.answer("Надішліть геолокацію або оберіть точку на карті.", reply_markup=location_choice_kb()); return

    if step == 'search_menu' and text == "🔮 За моїми інтересами":
        rows = await find_events_by_user_interests(uid, limit=20)
        if not rows:
            await message.answer("Поки немає подій за вашими інтересами.", reply_markup=main_menu)
            user_states[uid] = {'step': 'menu'}; return
        await send_event_cards(message.chat.id, rows)
        user_states[uid] = {'step': 'menu'}; return

    if step == 'search_keyword_wait':
        rows = await find_events_by_kw(text, limit=10)
        if not rows:
            await message.answer("Нічого не знайдено.", reply_markup=main_menu)
            user_states[uid] = {'step': 'menu'}; return
        await send_event_cards(message.chat.id, rows)
        user_states[uid] = {'step': 'menu'}; return

    if step == 'search_geo_wait_radius':
        try: radius = float(text)
        except ValueError: radius = 5.0
        lat, lon = st.get('search_lat'), st.get('search_lon')
        if lat is None or lon is None:
            await message.answer("Не бачу геолокації. Спробуйте ще раз.", reply_markup=location_choice_kb())
            st['step'] = 'search_geo_wait_location'; return
        rows = await find_events_near(lat, lon, radius, limit=10)
        if not rows:
            await message.answer("Поруч подій не знайдено 😕", reply_markup=main_menu)
            user_states[uid] = {'step': 'menu'}; return
        await send_event_cards(message.chat.id, rows)
        user_states[uid] = {'step': 'menu'}; return

    if step == 'search_menu' and text == '⬅️ Назад':
        user_states[uid] = {'step': 'menu'}
        await message.answer("Меню:", reply_markup=main_menu); return

    # Ретрансляція в активній розмові
    conv = await get_active_conversation_for_user(uid)
    if conv:
        now = datetime.now(timezone.utc)
        if conv['expires_at'] <= now:
            await close_conversation(conv['id'], reason='expired')
            await message.answer("⌛ Чат завершено (час вичерпано).", reply_markup=main_menu)
            return
        partner_id = conv['seeker_id'] if uid == conv['organizer_id'] else conv['organizer_id']
        try:
            await bot.send_message(partner_id, f"💬 {message.from_user.full_name}:\n{text}")
        except Exception as e:
            logging.warning("relay failed: %s", e)
        return

    logging.info("Unhandled step=%s text=%s", step, text)

# Geo
@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    cur = st.get('step')

    if cur == 'create_event_location':
        st['event_lat'] = message.location.latitude
        st['event_lon'] = message.location.longitude
        st['step'] = 'create_event_location_name'
        await message.answer("🏷 Введіть адресу/назву місця (опційно):", reply_markup=get_back_button()); return

    if cur == 'search_geo_wait_location':
        st['search_lat'] = message.location.latitude
        st['search_lon'] = message.location.longitude
        st['step'] = 'search_geo_wait_radius'
        await message.answer("📏 Радіус у км? (дефолт 5). Надішліть число або виберіть кнопку.", reply_markup=radius_kb()); return

# JOIN — анти-спам; нотифікація з профілем шукача
@dp.callback_query(F.data.startswith("join:"))
async def cb_join(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    seeker_id = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        existing = await conn.fetchrow("SELECT id, status FROM requests WHERE event_id=$1 AND seeker_id=$2", event_id, seeker_id)
        if existing:
            st = existing['status']
            msg = "Заявку вже відправлено, очікуйте відповіді ✅" if st=='pending' else ("Заявку вже підтверджено. Можете писати в чат тут!" if st=='approved' else "На жаль, вашу заявку відхилено.")
            await call.answer(msg, show_alert=True); await conn.close(); return

        req = await conn.fetchrow("INSERT INTO requests (event_id, seeker_id) VALUES ($1,$2) RETURNING id", event_id, seeker_id)
        ev  = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        seeker = await conn.fetchrow("SELECT name, city, interests, photo FROM users WHERE telegram_id::text=$1", str(seeker_id))
        await conn.close()

        await call.answer("Запит на приєднання надіслано ✅", show_alert=False)

        if ev:
            caption = (f"🔔 Запит на участь у події “{ev['title']}” (#{ev['id']}).\n\n"
                       f"👤 Пошукач: {seeker['name'] if seeker else call.from_user.full_name}\n"
                       f"🎯 Інтереси: {(seeker['interests'] or '—') if seeker else '—'}\n"
                       f"🏙 Місто: {(seeker['city'] or '—') if seeker else '—'}\n\n"
                       f"Підтвердити участь?")
            if seeker and seeker.get('photo'):
                try:
                    await bot.send_photo(ev["user_id"], seeker['photo'], caption=caption, reply_markup=approve_kb(req["id"]))
                except Exception:
                    await bot.send_message(ev["user_id"], caption, reply_markup=approve_kb(req["id"]))
            else:
                await bot.send_message(ev["user_id"], caption, reply_markup=approve_kb(req["id"]))
    except Exception as e:
        logging.error("join error: %s", e)
        await call.answer(f"Помилка: {e}", show_alert=True)

# APPROVE / REJECT
@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        async with conn.transaction():
            req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1 FOR UPDATE", req_id)
            if not req: await call.answer("Заявку не знайдено.", show_alert=True); return
            ev  = await conn.fetchrow("SELECT * FROM events WHERE id=$1 FOR UPDATE", req['event_id'])
            if not ev: await call.answer("Подію не знайдено.", show_alert=True); return
            if call.from_user.id != ev['user_id']:
                await call.answer("Лише організатор може підтвердити.", show_alert=True); return
            if req['status'] == 'approved':
                await call.answer("Вже підтверджено.", show_alert=True); return
            if req['status'] == 'rejected':
                await call.answer("Вже відхилено.", show_alert=True); return
            if ev['needed_count'] is not None and ev['needed_count'] <= 0:
                await call.answer("Немає вільних місць.", show_alert=True); return

            await conn.execute("UPDATE requests SET status='approved' WHERE id=$1", req_id)
            await conn.execute("UPDATE events SET needed_count = GREATEST(COALESCE(needed_count,0)-1,0) WHERE id=$1", ev['id'])

            expires = datetime.now(timezone.utc) + timedelta(minutes=30)
            conv = await conn.fetchrow("""
                INSERT INTO conversations (event_id, organizer_id, seeker_id, expires_at)
                VALUES ($1,$2,$3,$4)
                RETURNING id, expires_at
            """, ev['id'], ev['user_id'], req['seeker_id'], expires)
        await conn.close()

        await call.answer("✅ Підтверджено", show_alert=False)
        until = conv['expires_at'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        try:
            await bot.send_message(req['seeker_id'],
                f"✅ Вас прийнято до події “{ev['title']}”.\n"
                f"💬 Чат з організатором активний до {until}. Напишіть повідомлення тут — я перешлю.\n"
                f"Команда /stopchat — завершити.")
            await bot.send_message(ev['user_id'],
                f"✅ Учасника підтверджено (id {req['seeker_id']}). Чат активний до {until}.")
        except Exception as e:
            logging.warning("notify approve failed: %s", e)

    except Exception as e:
        logging.error("approve error: %s", e)
        await call.answer(f"Помилка: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        req = await conn.fetchrow("UPDATE requests SET status='rejected' WHERE id=$1 RETURNING seeker_id, event_id", req_id)
        ev  = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", req['event_id']) if req else None
        await conn.close()
        if not req: await call.answer("Заявку не знайдено.", show_alert=True); return
        if ev and call.from_user.id != ev['user_id']:
            await call.answer("Лише організатор може відхилити.", show_alert=True); return
        await call.answer("❌ Відхилено", show_alert=False)
        if ev:
            try: await bot.send_message(req['seeker_id'], f"❌ На жаль, запит на подію “{ev['title']}” відхилено.")
            except Exception: pass
    except Exception as e:
        logging.error("reject error: %s", e)
        await call.answer(f"Помилка: {e}", show_alert=True)

# /stopchat
@dp.message(Command("stopchat"))
async def stop_chat(message: types.Message):
    uid = message.from_user.id
    conv = await get_active_conversation_for_user(uid)
    if not conv:
        await message.answer("Активного чату не знайдено.", reply_markup=main_menu); return
    await close_conversation(conv['id'], reason='closed')
    other = conv['seeker_id'] if uid == conv['organizer_id'] else conv['organizer_id']
    await message.answer("✅ Чат завершено.", reply_markup=main_menu)
    try: await bot.send_message(other, "ℹ️ Співрозмовник завершив чат.")
    except Exception: pass

# Cards (event photo only; без фото організатора)
async def send_event_cards(chat_id: int, rows: list[asyncpg.Record]):
    for r in rows:
        dt = r["date"].strftime('%Y-%m-%d %H:%M') if r["date"] else "—"
        loc_line = (r["location"] or "").strip() or (f"{r['location_lat']:.5f}, {r['location_lon']:.5f}" if r["location_lat"] is not None else "—")
        organizer_name = r.get("organizer_name") or "—"
        org_interests = r.get("organizer_interests") or "—"
        org_count = r.get("org_count") or 0
        parts = [
            f"<b>{r['title']}</b> (#{r['id']})",
            f"📅 {dt}",
            f"📍 {loc_line}",
            f"👤 Шукаємо: {r['needed_count']}/{r['capacity']}",
            f"👑 Організатор: {organizer_name} · подій: {org_count}",
            f"🎯 Інтереси орг.: {org_interests}"
        ]
        desc = (r['description'] or '').strip()
        if desc:
            parts.append("")
            parts.append(desc[:300] + ('…' if len(desc) > 300 else ''))
        caption = "\n".join(parts)
        kb = event_join_kb(r["id"])
        if r.get('photo'):
            try:
                await bot.send_photo(chat_id, r['photo'], caption=caption, parse_mode="HTML", reply_markup=kb)
                continue
            except Exception:
                pass
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)

# Entrypoint
async def main():
    logging.info('Starting polling')
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())









   






