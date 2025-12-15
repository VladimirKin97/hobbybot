# findsy_bot.py
# --- Findsy bot (aiogram 3.x) ---
import os
import logging
import asyncio
import re
import calendar as calmod
from datetime import datetime, timedelta, timezone, date
from math import radians, sin, cos, acos

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ========= Init =========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Телеграм ID для адмін-сповіщень

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Environment variables BOT_TOKEN and DATABASE_URL must be set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========= In-memory FSM + timers =========
user_states: dict[int, dict] = {}

REMINDER_CREATE_MIN = 15     # 15 хв після останньої активності в флоу створення
RESET_TO_MENU_MIN   = 60     # 60 хв бездіяльності -> назад у головне меню

# ========= Helpers =========
async def notify_admin(text: str):
    if not ADMIN_CHAT_ID:
        return
    try:
        chat_id = int(ADMIN_CHAT_ID)
    except Exception:
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:
        logging.warning("notify_admin failed: %s", e)

async def safe_alert(call: types.CallbackQuery, text: str, show_alert: bool = True):
    try:
        await call.answer(text[:180], show_alert=show_alert)
    except Exception as e:
        logging.warning("call.answer failed: %s", e)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

# ========= Buttons / Keyboards =========
BTN_PROFILE      = "👤 Мій профіль"
BTN_CREATE       = "➕ Створити подію"
BTN_SEARCH       = "🔍 Знайти подію"
BTN_MY_CHATS     = "📨 Мої чати"
BTN_MY_EVENTS    = "📦 Мої івенти"
BTN_BACK         = "⬅️ Назад"
BTN_SKIP         = "⏭ Пропустити"
BTN_SEARCH_KW    = "🔎 За ключовим словом"
BTN_MENU         = "🏠 Меню"  
BTN_SEARCH_NEAR  = "📍 Поруч зі мною"
BTN_SEARCH_MINE  = "🔮 За моїми інтересами"

FILTER_ACTIVE   = "active"
FILTER_FINISHED = "finished"
FILTER_DELETED  = "deleted"

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PROFILE)],
            [KeyboardButton(text=BTN_CREATE)],
            [KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_MY_CHATS), KeyboardButton(text=BTN_MY_EVENTS)]
        ],
        resize_keyboard=True
    )

def back_kb() -> ReplyKeyboardMarkup:
    # Назад + Меню
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]],
        resize_keyboard=True
    )
def search_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH_KW)],
            [KeyboardButton(text=BTN_SEARCH_NEAR)],
            [KeyboardButton(text=BTN_SEARCH_MINE)],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )


def skip_back_kb() -> ReplyKeyboardMarkup:
    # Пропустити + (Назад, Меню)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SKIP)],
            [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]
        ],
        resize_keyboard=True
    )

def location_choice_kb() -> ReplyKeyboardMarkup:
    # важливе перейменування: "поточна геолокація"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати поточну геолокацію", request_location=True)],
            [KeyboardButton(text="📝 Ввести адресу текстом"), KeyboardButton(text="⏭ Пропустити локацію")],
            [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]
        ],
        resize_keyboard=True
    )

def event_publish_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='✅ Опублікувати'), KeyboardButton(text='✏️ Редагувати')],
            [KeyboardButton(text='❌ Скасувати')],
            [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]
        ],
        resize_keyboard=True
    )


def myevents_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Активні", callback_data=f"myevents:filter:{FILTER_ACTIVE}"),
            InlineKeyboardButton(text="✅ Проведені", callback_data=f"myevents:filter:{FILTER_FINISHED}"),
            InlineKeyboardButton(text="🗑 Скасовані/Видалені", callback_data=f"myevents:filter:{FILTER_DELETED}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")]
    ])

def event_edit_menu_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Назва", callback_data=f"event:edit:title:{event_id}"),
             InlineKeyboardButton(text="📄 Опис", callback_data=f"event:edit:descr:{event_id}")],
            [InlineKeyboardButton(text="📅 Дата й час", callback_data=f"event:edit:datetime:{event_id}")],
            [InlineKeyboardButton(text="📍 Адреса", callback_data=f"event:edit:addr:{event_id}")],
            [InlineKeyboardButton(text="👥 Місткість", callback_data=f"event:edit:capacity:{event_id}"),
             InlineKeyboardButton(text="👤 Вільні місця", callback_data=f"event:edit:needed:{event_id}")],
            [InlineKeyboardButton(text="📸 Фото", callback_data=f"event:edit:photo:{event_id}")],
            [InlineKeyboardButton(text="⬅️ Назад до подій", callback_data=f"myevents:filter:{FILTER_ACTIVE}")]
        ]
    )

def request_actions_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Відкрити чат", callback_data=f"reqchat:{req_id}")],
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve:{req_id}"),
         InlineKeyboardButton(text="❌ Відхилити",   callback_data=f"reject:{req_id}")],
    ])

def event_join_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")]]
    )

def my_events_kb(rows: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    # якщо rows == [], покажемо "порожньо", але все одно залишимо кнопки навігації
    ikb = []
    if rows:
        for r in rows:
            dt = (r['date'].strftime('%d.%m %H:%M') if r['date'] else '—')
            role = "(Орг)" if r['role'] == 'owner' else "(Учасник)"
            line = f"{role} {r['title']} • {dt} • {r['status']}"

            # верхній рядок з назвою і статусом івенту
            ikb.append([
                InlineKeyboardButton(
                    text=line,
                    callback_data=f"event:info:{r['id']}"
                )
            ])

            if r['role'] == 'owner':
                # КНОПКИ ДЛЯ ОРГАНІЗАТОРА
                row_btns = [
                    InlineKeyboardButton(text="👥 Учасники", callback_data=f"event:members:{r['id']}"),
                    InlineKeyboardButton(text="🔔 Заявки",    callback_data=f"event:reqs:{r['id']}"),
                    InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"event:edit:{r['id']}"),
                ]
                if r['status'] in ('active', 'collected'):
                    row_btns.append(InlineKeyboardButton(text="🗑 Видалити", callback_data=f"event:delete:{r['id']}"))
                    row_btns.append(InlineKeyboardButton(text="🚫 Скасувати", callback_data=f"event:cancel:{r['id']}"))
                elif r['status'] in ('cancelled', 'deleted', 'finished'):
                    row_btns.append(InlineKeyboardButton(text="♻️ Відкрити", callback_data=f"event:open:{r['id']}"))
                ikb.append(row_btns)

            else:
                # 🆕 УЧАСНИК:
                # 1) подивитися учасників
                # 2) відкрити картку організатора (там будуть "через Findsy" + "Дірект")
                # 3) вийти з івенту
                ikb.append([
                    InlineKeyboardButton(
                        text="👥 Учасники",
                        callback_data=f"event:members:{r['id']}"
                    ),
                    InlineKeyboardButton(
                        text="📞 Організатор",
                        callback_data=f"event:orginfo:{r['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🚪 Вийти з івенту",
                        callback_data=f"event:leave:{r['id']}"
                    ),
                ])
    else:
        ikb.append([InlineKeyboardButton(text="Подій не знайдено", callback_data="noop")])

    ikb.append([InlineKeyboardButton(text="⬅️ Фільтри", callback_data="myevents:filters")])
    ikb.append([InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=ikb)


def chats_list_kb(rows: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    ikb = []
    if rows:
        for r in rows:
            title = (r["title"] or "Подія")
            other = r["other_name"] or f"id {r['other_id']}"
            ikb.append([InlineKeyboardButton(text=f"💬 {title} · {other}", callback_data=f"chat:open:{r['id']}")])
            ikb.append([InlineKeyboardButton(text=f"📜 Історія", callback_data=f"chat:history:{r['id']}")])
            ikb.append([InlineKeyboardButton(text=f"❌ Закрити чат", callback_data=f"chat:close:{r['id']}")])
    else:
        ikb.append([InlineKeyboardButton(text="Немає активних чатів", callback_data="noop")])
    ikb.append([InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=ikb)

# ========= Calendar (inline) =========
def month_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    month_name = datetime(year, month, 1).strftime("%B %Y")
    kb.append([InlineKeyboardButton(text=month_name, callback_data="cal:noop")])
    kb.append([InlineKeyboardButton(t, callback_data="cal:noop") for t in ["Mo","Tu","We","Th","Fr","Sa","Su"]])
    for week in calmod.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal:noop"))
            else:
                row.append(InlineKeyboardButton(str(d), callback_data=f"cal:date:{year:04d}-{month:02d}-{d:02d}"))
        kb.append(row)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1)  if month == 12 else (year, month + 1)
    kb.append([
        InlineKeyboardButton("«", callback_data=f"cal:nav:{prev_y:04d}-{prev_m:02d}"),
        InlineKeyboardButton("»", callback_data=f"cal:nav:{next_y:04d}-{next_m:02d}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("cal:nav:"))
async def cal_nav(call: types.CallbackQuery):
    y, m = map(int, call.data.split(":")[2].split("-"))
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
    await call.message.answer("⏰ Виберіть або введіть час у форматі HH:MM (наприклад, 19:30).", reply_markup=back_kb())
    await call.answer()

# ========= Human date parser =========
MONTHS = {
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
    "января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
    "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12,
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":2,"august":8,"september":9,"october":10,"november":11,"december":12,
}
def parse_user_datetime(text: str) -> datetime | None:
    s = text.strip().lower()
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        dd, mm, yyyy, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", s)
    if m:
        yyyy, mm, dd, HH, MM = map(int, m.groups())
        return datetime(yyyy, mm, dd, HH, MM)
    m = re.match(r"^(\d{1,2})\s+([a-zа-яіїєё]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})$", s, re.IGNORECASE)
    if m:
        dd = int(m.group(1)); mon = m.group(2); yyyy = int(m.group(3)); HH = int(m.group(4)); MM = int(m.group(5))
        mm = MONTHS.get(mon)
        if mm:
            return datetime(yyyy, mm, dd, HH, MM)
    return None

def parse_time_hhmm(s: str) -> tuple[int,int] | None:
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", s.strip())
    if not m: return None
    HH, MM = map(int, m.groups())
    if 0 <= HH <= 23 and 0 <= MM <= 59: return HH, MM
    return None

def tg_link_from_username(username: str | None) -> str:
    """
    Повертає клікабельне посилання на t.me/<username> або текст, що нікнейм відсутній.
    Використовується разом з parse_mode="HTML".
    """
    if username:
        u = username.lstrip("@")
        return f'<a href="https://t.me/{u}">@{u}</a>'
    return "нікнейм відсутній"


# ========= DB helpers =========
async def init_db():
    # ---- Таблица рейтингов ----
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            event_id INT NOT NULL,
            organizer_id BIGINT NOT NULL,
            seeker_id BIGINT NOT NULL,
            score INT CHECK (score BETWEEN 1 AND 10) NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(event_id, seeker_id)
        );
        """)
    finally:
        await conn.close()

    # ---- Таблица подписок на уведомления ----
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS event_notifications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            type TEXT NOT NULL,          -- 'radius' | 'interests' | 'keyword'
            keyword TEXT,                -- если type='keyword'
            lat DOUBLE PRECISION,        -- если type='radius'
            lon DOUBLE PRECISION,
            radius_km DOUBLE PRECISION,
            interests TEXT,              -- кеш интересов на момент подписки
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
    finally:
        await conn.close()

                
   

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
            RETURNING *
        """, user_id, creator_name or '', creator_phone or '', title, description, date, location,
           capacity, needed_count, status, location_lat, location_lon, photo)
        return row
    finally:
        await conn.close()


async def update_event_status(event_id: int, owner_id: int, new_status: str) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        res = await conn.execute("""
            UPDATE events SET status=$3
            WHERE id=$1 AND user_id::text=$2
        """, event_id, str(owner_id), new_status)
        return res.startswith("UPDATE")
    finally:
        await conn.close()

async def update_event_field(event_id: int, owner_id: int, field: str, value):
    whitelist = {
        "title": "text", "description": "text", "date": "timestamp",
        "location": "text", "capacity": "int", "needed_count": "int", "photo": "text"
    }
    if field not in whitelist:
        raise ValueError("field not allowed")
    sql = f"UPDATE events SET {field}=$3 WHERE id=$1 AND user_id::text=$2"
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        res = await conn.execute(sql, event_id, str(owner_id), value)
        return res.startswith("UPDATE")
    finally:
        await conn.close()

async def list_user_events(user_id: int, filter_kind: str | None = None):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            WITH mine AS (
                SELECT e.id, e.title, e.date, e.needed_count, e.capacity, e.status, e.created_at,
                       'owner'::text AS role, 1 AS role_order
                FROM events e
                WHERE e.user_id::text = $1
            ),
            joined AS (
                SELECT e.id, e.title, e.date, e.needed_count, e.capacity, e.status, e.created_at,
                       'member'::text AS role, 2 AS role_order
                FROM events e
                JOIN requests r ON r.event_id=e.id AND r.status='approved'
                WHERE r.seeker_id::text=$1
            ),
            allrows AS (
                SELECT * FROM mine
                UNION ALL
                SELECT * FROM joined
            )
            SELECT DISTINCT ON (id) id, title, date, needed_count, capacity, status, created_at, role
            FROM allrows
            ORDER BY id, role_order
        """, str(user_id))
    finally:
        await conn.close()

    def is_active(st):   return st in ('active','collected')
    def is_finished(st): return st in ('finished',)
    def is_deleted(st):  return st in ('deleted','cancelled')

    if filter_kind == FILTER_ACTIVE:
        rows = [r for r in rows if is_active(r['status'])]
    elif filter_kind == FILTER_FINISHED:
        rows = [r for r in rows if is_finished(r['status'])]
    elif filter_kind == FILTER_DELETED:
        rows = [r for r in rows if is_deleted(r['status'])]

    return sorted(rows, key=lambda r: (r['date'] or datetime.max, r['created_at'] or datetime.max))

async def list_pending_requests(event_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT r.id AS req_id, r.seeker_id, u.name, u.city, u.interests, u.photo
            FROM requests r
            LEFT JOIN users u ON u.telegram_id::text = r.seeker_id::text
            WHERE r.event_id=$1 AND r.status='pending'
            ORDER BY r.created_at ASC
        """, event_id)
    finally:
        await conn.close()

async def list_approved_members(event_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT r.seeker_id, u.name, u.city, u.interests, u.photo
            FROM requests r
            LEFT JOIN users u ON u.telegram_id::text = r.seeker_id::text
            WHERE r.event_id=$1 AND r.status='approved'
            ORDER BY r.created_at ASC
        """, event_id)
    finally:
        await conn.close()

async def list_active_conversations_for_user(uid: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch("""
            SELECT c.id, c.event_id, e.title,
                   CASE WHEN c.organizer_id=$1 THEN c.seeker_id ELSE c.organizer_id END AS other_id,
                   u.name AS other_name, c.expires_at
            FROM conversations c
            JOIN events e ON e.id=c.event_id
            LEFT JOIN users u ON (u.telegram_id::text = (CASE WHEN c.organizer_id=$1 THEN c.seeker_id ELSE c.organizer_id END)::text)
            WHERE c.status='active' AND c.expires_at > now()
              AND (c.organizer_id=$1 OR c.seeker_id=$1)
            ORDER BY c.expires_at DESC
        """, uid)
    finally:
        await conn.close()

async def get_conversation(conv_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow("SELECT * FROM conversations WHERE id=$1", conv_id)
    finally:
        await conn.close()

async def get_or_create_conversation(event_id: int, organizer_id: int, seeker_id: int, minutes: int = 30):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("""
            SELECT * FROM conversations
            WHERE event_id=$1 AND organizer_id=$2 AND seeker_id=$3 AND status='active' AND expires_at > now()
            ORDER BY id DESC LIMIT 1
        """, event_id, organizer_id, seeker_id)
        if row:
            return row
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        row = await conn.fetchrow("""
            INSERT INTO conversations (event_id, organizer_id, seeker_id, expires_at)
            VALUES ($1,$2,$3,$4)
            RETURNING *
        """, event_id, organizer_id, seeker_id, expires)
        return row
    finally:
        await conn.close()

async def close_conversation(conv_id: int, reason: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("UPDATE conversations SET status=$2 WHERE id=$1",
                           conv_id, 'expired' if reason=='expired' else 'closed')
    finally:
        await conn.close()

async def save_message(conv_id: int, sender_id: int, text: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("INSERT INTO messages (conv_id, sender_id, text) VALUES ($1,$2,$3)",
                           conv_id, sender_id, text)
    finally:
        await conn.close()

async def load_last_messages(conv_id: int, limit: int = 20):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetch(
            "SELECT sender_id, text, created_at FROM messages WHERE conv_id=$1 ORDER BY created_at DESC LIMIT $2",
            conv_id, limit
        )
    finally:
        await conn.close()
# ========= Notifications Logic =========

async def add_event_notification(user_id: int, type_: str,
                                 keyword: str | None = None,
                                 lat: float | None = None,
                                 lon: float | None = None,
                                 radius_km: float | None = None,
                                 interests: str | None = None):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            INSERT INTO event_notifications(user_id, type, keyword, lat, lon, radius_km, interests)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
        """, user_id, type_, keyword, lat, lon, radius_km, interests)
    finally:
        await conn.close()


async def deactivate_subscription(sub_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("UPDATE event_notifications SET active=FALSE WHERE id=$1", sub_id)
    finally:
        await conn.close()


async def reactivate_subscription(sub_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("UPDATE event_notifications SET active=TRUE WHERE id=$1", sub_id)
    finally:
        await conn.close()


def notification_choice_kb(sub_id: int, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙌 Долучитися", callback_data=f"join:{event_id}")],
        [
            InlineKeyboardButton(text="🔔 Продовжити", callback_data=f"notif_continue:{sub_id}"),
            InlineKeyboardButton(text="❌ Відписатися", callback_data=f"notif_stop:{sub_id}")
        ]
    ])


async def send_event_notification_card(user_id: int, event: asyncpg.Record, sub_id: int):
    dt = event["date"].strftime('%Y-%m-%d %H:%M') if event["date"] else "—"
    loc_line = (event["location"] or "").strip() or (
        f"{event['location_lat']:.5f}, {event['location_lon']:.5f}"
        if event['location_lat'] else "—"
    )
    filled = max((event['capacity'] or 0) - (event['needed_count'] or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{event['capacity']} • шукаємо ще: {event['needed_count']}"
    avg = await get_organizer_avg_rating(event['user_id'])
    rating_line = f"\n⭐ Рейтинг орг.: {avg:.1f}/10" if avg else ""

    caption = (
        f"<b>{event['title']}</b>\n"
        f"📅 {dt}\n"
        f"📍 {loc_line}\n"
        f"{places_line}\n"
        f"👑 Організатор: <b>{event['creator_name'] or '—'}</b>{rating_line}\n\n"
        f"{(event['description'] or '').strip()[:600]}"
    )

    kb = notification_choice_kb(sub_id, event["id"])

    try:
        if event.get("photo"):
            await bot.send_photo(user_id, event["photo"], caption=caption, parse_mode="HTML", reply_markup=kb)
            return
    except Exception:
        pass

    await bot.send_message(user_id, caption, parse_mode="HTML", reply_markup=kb)


async def check_event_notifications(event: asyncpg.Record):
    # Для дебагу в логах
    logging.info(f"[notif] New event {event.get('id')} title={event.get('title')}")

    # тягнемо всі активні підписки
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        subs = await conn.fetch("SELECT * FROM event_notifications WHERE active = TRUE")
    finally:
        await conn.close()

    logging.info(f"[notif] Active subscriptions count = {len(subs)}")

    if not subs:
        return

    title = (event.get("title") or "").lower()
    descr = (event.get("description") or "").lower()
    lat = event.get("location_lat")
    lon = event.get("location_lon")

    for sub in subs:
        ok = False
        reason = ""

        # --- keyword ---
        if sub["type"] == "keyword":
            kw = (sub["keyword"] or "").lower()
            if kw and (kw in title or kw in descr):
                ok = True
                reason = f"keyword match: {kw}"

        # --- interests ---
        elif sub["type"] == "interests":
            if sub["interests"]:
                interests = [i.strip().lower() for i in sub["interests"].split(",") if i.strip()]
                if any(i in title or i in descr for i in interests):
                    ok = True
                    reason = f"interests match: {interests}"

        # --- radius ---
        elif sub["type"] == "radius" and lat is not None and lon is not None \
                and sub["lat"] is not None and sub["lon"] is not None:
            R = 6371
            d = R * acos(
                cos(radians(sub["lat"])) *
                cos(radians(lat)) *
                cos(radians(lon) - radians(sub["lon"])) +
                sin(radians(sub["lat"])) * sin(radians(lat))
            )
            if d <= (sub["radius_km"] or 5):
                ok = True
                reason = f"radius match: dist={d:.2f}km <= {sub['radius_km']}km"

        logging.info(f"[notif] check sub #{sub['id']} type={sub['type']} -> ok={ok} ({reason})")

        if ok:
            # деактивуємо підписку, щоб не спамити
            await deactivate_subscription(sub["id"])

            try:
                await bot.send_message(
                    sub["user_id"],
                    "🎉 З’явився новий івент, який може вам підійти!"
                )
            except Exception as e:
                logging.warning(f"[notif] send_message failed for user {sub['user_id']}: {e}")

            # Надсилаємо повну карточку івенту
            try:
                await send_event_cards(sub["user_id"], [event])
            except Exception as e:
                logging.warning(f"[notif] send_event_cards failed: {e}")



# ========= Rating =========
async def get_organizer_avg_rating(organizer_id: int) -> float | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("""
            SELECT AVG(score)::float AS avg
            FROM ratings
            WHERE organizer_id=$1 AND status='done' AND score IS NOT NULL
        """, organizer_id)
        return row["avg"]
    finally:
        await conn.close()

def rating_kb(event_id: int) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"rate:{event_id}:{i}") for i in range(1,6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"rate:{event_id}:{i}") for i in range(6,11)]
    row3 = [InlineKeyboardButton(text="🙈 У мене не вийшло долучитися", callback_data=f"rate_skip:{event_id}")]
    return InlineKeyboardMarkup(inline_keyboard=[row1,row2,row3])

@dp.callback_query(F.data.startswith("rate:"))
async def cb_rate(call: types.CallbackQuery):
    _, ev_id_str, score_str = call.data.split(":")
    event_id, score = int(ev_id_str), int(score_str)
    uid = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        ev = await conn.fetchrow("SELECT user_id, title FROM events WHERE id=$1", event_id)
        if not ev:
            await safe_alert(call, "Подію не знайдено."); await conn.close(); return
        await conn.execute("""
            INSERT INTO ratings(event_id, organizer_id, seeker_id, score, status)
            VALUES ($1,$2,$3,$4,'done')
            ON CONFLICT (event_id, seeker_id) DO UPDATE SET score=EXCLUDED.score, status='done'
        """, event_id, ev['user_id'], uid, score)
        await conn.close()
        await safe_alert(call, "Дякуємо за оцінку!", show_alert=False)
        # після оцінки — у головне меню
        await bot.send_message(uid, "Повертаю у головне меню.", reply_markup=main_menu())
    except Exception:
        logging.exception("rate error")
        await safe_alert(call, "Помилка збереження оцінки")

@dp.callback_query(F.data.startswith("rate_skip:"))
async def cb_rate_skip(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    uid = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        ev = await conn.fetchrow("SELECT user_id FROM events WHERE id=$1", event_id)
        if ev:
            await conn.execute("""
                INSERT INTO ratings(event_id, organizer_id, seeker_id, score, status)
                VALUES ($1,$2,$3,NULL,'skipped')
                ON CONFLICT (event_id, seeker_id) DO UPDATE SET score=NULL, status='skipped'
            """, event_id, ev['user_id'], uid)
        await conn.close()
        await safe_alert(call, "Зрозуміло, дякуємо!", show_alert=False)
        await bot.send_message(uid, "Повертаю у головне меню.", reply_markup=main_menu())
    except Exception:
        logging.exception("rateskip error")
        await safe_alert(call, "Сталася помилка")

# ========= Debug =========
@dp.message(Command("dbinfo"))
async def cmd_dbinfo(message: types.Message):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("""
            SELECT current_database() AS db, current_user AS usr, current_schema AS sch,
                   current_setting('server_version') AS ver,
                   current_setting('TimeZone', true) AS tz;
        """)
        await conn.close()
        await message.answer(
            f"🗄 DB={row['db']}\n👤 user={row['usr']}\n📚 schema={row['sch']}\n"
            f"🐘 pg={row['ver']}\n🌍 tz={row['tz']}"
        )
    except Exception as e:
        await message.answer(f"DB error: {e}")

# ========= Start =========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    try:
        user = await get_user_from_db(uid)
    except Exception:
        st['step'] = 'menu'
        await message.answer("⚠️ Не вдалося з'єднатися з БД.", reply_markup=main_menu()); return
    if user:
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}! Оберіть дію:", reply_markup=main_menu())
    else:
        # новий користувач — показуємо інвайт + старт реєстрації
        st['step'] = 'name'
        await message.answer(
            "👋 Привіт! Я Findsy — бот, який допомагає знайти компанію для будь-яких активностей: "
            "настолки, футбол, пробіжки, концерти, бари та багато іншого.\n\n"
            "Щоб створювати свої події або шукати існуючі, потрібно заповнити короткий профіль: "
            "імʼя, місто, інтереси та фото. Це 1–2 хвилини, зате іншим буде простіше зрозуміти, "
            "з ким вони йдуть на івент, а я зможу підбирати більш релевантні події 🧩\n\n"
            "Почнемо з профілю 🙂",
            reply_markup=back_kb()
        )

        await message.answer(
            "📝 <b>Назва профілю</b>\n\n"
            "💡 Вкажи імʼя або нік, яким ти хочеш відображатися у Findsy.\n"
            "Наприклад: «Вова з Позняків», «Іра · настолки & кіно».",
            parse_mode="HTML",
            reply_markup=back_kb()
        )

# ========= Admin: ручні пінги =========
@dp.message(Command("sendto"))
async def cmd_sendto(message: types.Message):
    # Тільки для адміна
    if not ADMIN_CHAT_ID or str(message.from_user.id) != str(ADMIN_CHAT_ID):
        await message.answer("Ця команда доступна лише адміну.")
        return

    # Очікуємо формат:
    # /sendto 123456789 текст повідомлення
    # або
    # /sendto 123456789,987654321 текст повідомлення
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Формат:\n"
            "/sendto <id або id1,id2,id3> <текст повідомлення>\n\n"
            "Приклад:\n"
            "/sendto 123456789 Привіт! Є новий івент по настолках 😉"
        )
        return

    raw_ids = parts[1]
    body = parts[2].strip()
    if not body:
        await message.answer("Текст повідомлення порожній 😅")
        return

    # Парсимо кілька ID через кому або крапку з комою
    ids: list[int] = []
    for chunk in raw_ids.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError:
            await message.answer(f"Не зміг розпізнати ID: {chunk}")
            return

    if not ids:
        await message.answer("Не знайшов жодного валідного ID.")
        return

    ok, fail = 0, 0
    for uid in ids:
        try:
            await bot.send_message(uid, body)
            ok += 1
        except Exception as e:
            logging.warning("sendto fail %s: %s", uid, e)
            fail += 1

    await message.answer(
        f"✅ Відправлено {ok} користувачам.\n"
        f"⚠️ З помилкою: {fail}" if fail else f"✅ Відправлено {ok} користувачам без помилок."
    )



# ========= Timers (reminders) =========
def schedule_create_reminder(uid: int):
    st = user_states.setdefault(uid, {})
    # відмічаємо останню активність у флоу
    st['create_last_touch'] = _now_utc()
    # скасовуємо попереднє нагадування якщо було
    task = st.get('create_reminder_task')
    if task and not task.done():
        task.cancel()
    st['create_reminder_task'] = asyncio.create_task(_create_reminder_task(uid))

async def _create_reminder_task(uid: int):
    try:
        await asyncio.sleep(REMINDER_CREATE_MIN * 60)
        st = user_states.get(uid) or {}
        # нагадувати 1 раз якщо з моменту останньої дії минуло 15 хв, і користувач ще у флоу створення
        if (st.get('step','').startswith('create_event')
            and st.get('create_last_touch')
            and (_now_utc() - st['create_last_touch']).total_seconds() >= REMINDER_CREATE_MIN * 60):
            human_step = {
                'create_event_title': "назву події",
                'create_event_description': "опис події",
                'create_event_date': "дату й час",
                'create_event_time': "час",
                'create_event_location': "локацію",
                'create_event_location_name': "адресу/місце",
                'create_event_capacity': "місткість (скільки всього людей)",
                'create_event_needed': "скільки ще учасників шукаєте",
                'create_event_photo': "фото (опційно)",
                'create_event_review': "підтвердження публікації",
            }
            need = human_step.get(st.get('step'), "наступний крок")
            await bot.send_message(uid,
                f"⏰ Ти не завершив створення івенту — потрібно ввести {need}. "
                f"Повертаюсь на потрібний крок. Продовжимо?",
                reply_markup=back_kb()
            )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.warning("create reminder task err: %s", e)

def schedule_reset_to_menu(uid: int):
    st = user_states.setdefault(uid, {})
    task = st.get('reset_task')
    if task and not task.done():
        task.cancel()
    st['reset_task'] = asyncio.create_task(_reset_to_menu_task(uid))

async def _reset_to_menu_task(uid: int):
    try:
        await asyncio.sleep(RESET_TO_MENU_MIN * 60)
        st = user_states.setdefault(uid, {})
        st['step'] = 'menu'
        await bot.send_message(uid, "🔄 Повертаю в головне меню для нового старту.", reply_markup=main_menu())
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.warning("reset task err: %s", e)

# ========= Compose event review =========
def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%Y-%m-%d %H:%M') if isinstance(dt, datetime) else "—"
    if st.get('event_location'):
        loc_line = st['event_location']
    elif st.get('event_lat') is not None and st.get('event_lon') is not None:
        loc_line = f"{st.get('event_lat'):.5f}, {st.get('event_lon'):.5f}"
    else:
        loc_line = "—"
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{st.get('capacity','—')} • шукаємо ще: {st.get('needed_count','—')}"
    parts = [
        "<b>Перевір дані перед публікацією</b>",
        f"📝 {st.get('event_title','—')}",
        f"📄 {(st.get('event_description','') or '—')[:500]}",
        f"📅 {dt_str}",
        f"📍 {loc_line}",
        places_line
    ]
    return "\n".join(parts)

async def send_event_review(chat_id: int, st: dict):
    caption = compose_event_review_text(st)
    kb = event_publish_kb()
    photo = st.get('event_photo')
    try:
        if photo:
            await bot.send_photo(chat_id, photo, caption=caption, parse_mode="HTML", reply_markup=kb); return
    except Exception:
        pass
    await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)

# ========= Back (reply) =========
@dp.message(F.text == BTN_BACK)
async def back_to_menu(message: types.Message):
    st = user_states.setdefault(message.from_user.id, {})
    st['step'] = 'menu'
    st['last_activity'] = _now_utc()
    await message.answer("⬅️ Повертаємось у меню", reply_markup=main_menu())

@dp.message(F.text == BTN_MENU)
async def go_main_menu(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['step'] = 'menu'
    st['active_conv_id'] = None   # на всяк випадок виходимо з активного чату
    st['last_activity'] = _now_utc()
    await message.answer("🏠 Повертаю в головне меню.", reply_markup=main_menu())


# ========= Inline back =========
@dp.callback_query(F.data == "back:menu")
async def cb_back_menu(call: types.CallbackQuery):
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['step'] = 'menu'
    st['last_activity'] = _now_utc()
    await safe_alert(call, "Головне меню", show_alert=False)
    try:
        await call.message.delete()
    except Exception:
        pass
    await bot.send_message(uid, "Меню:", reply_markup=main_menu())

# ========= Photo handlers =========
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    step = st.get('step')

    if step in ('photo', 'edit_photo'):
        st['photo'] = message.photo[-1].file_id
        if step == 'photo':
            st['step'] = 'interests'
            await message.answer("🎯 Інтереси (через кому):", reply_markup=back_kb())
        else:
            st['step'] = 'edit_interests'
            await message.answer("🎯 Онови інтереси або натисніть «⏭ Пропустити».", reply_markup=skip_back_kb())
        return

    if step == 'create_event_photo':
        st['event_photo'] = message.photo[-1].file_id
        st['step'] = 'create_event_review'
        await send_event_review(message.chat.id, st)
        return

    if step == 'edit_event_photo':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для оновлення фото.", reply_markup=main_menu()); return
        file_id = message.photo[-1].file_id
        ok = await update_event_field(ev_id, message.from_user.id, "photo", file_id)
        await message.answer("📸 Фото оновлено." if ok else "❌ Не вдалося оновити фото.", reply_markup=main_menu())
        if ok:
            await notify_members_event_changed(ev_id, "Оновлено фото події.")
        st['step'] = 'menu'
        return

# ========= Geo handlers =========
@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    cur = st.get('step')

    if cur == 'create_event_location':
        st['event_lat'] = message.location.latitude
        st['event_lon'] = message.location.longitude
        st['step'] = 'create_event_location_name'
        await message.answer("📍 Вкажи адресу/місце (опціонально):", reply_markup=back_kb()); return

    if cur == 'search_geo_wait_location':
        st['search_lat'] = message.location.latitude
        st['search_lon'] = message.location.longitude
        st['step'] = 'search_geo_wait_radius'
        await message.answer("📏 Радіус у км? (дефолт 5).", reply_markup=radius_kb()); return

# ========= Notifiers for members on change =========
async def notify_members_event_changed(event_id: int, what: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        ev = await conn.fetchrow("SELECT title FROM events WHERE id=$1", event_id)
        rows = await conn.fetch("SELECT seeker_id FROM requests WHERE event_id=$1 AND status='approved'", event_id)
    finally:
        await conn.close()
    if not ev: return
    text = f"ℹ️ Подія “{ev['title']}” оновлена: {what}"
    for r in rows:
        try: await bot.send_message(r['seeker_id'], text)
        except Exception: pass

# ========= Send event cards (with organizer rating) =========
async def send_event_cards(chat_id: int, rows: list[asyncpg.Record]):
    for r in rows:
        dt = r["date"].strftime('%Y-%m-%d %H:%M') if r["date"] else "—"
        loc_line = (r["location"] or "").strip() or (
            f"{r['location_lat']:.5f}, {r['location_lon']:.5f}" if r["location_lat"] is not None else "—"
        )
        organizer_name = r.get("organizer_name") or "—"
        org_interests = r.get("organizer_interests") or "—"
        org_count = r.get("org_count") or 0
        avg = await get_organizer_avg_rating(r['user_id']) if 'user_id' in r else None
        rating_line = f"\n⭐ Рейтинг орг.: {avg:.1f}/10" if avg else ""

        filled = max((r['capacity'] or 0) - (r['needed_count'] or 0), 0)
        places_line = f"👥 Заповнено: {filled}/{r['capacity']} • шукаємо ще: {r['needed_count']}"

        parts = [
            f"<b>{r['title']}</b>",
            f"📅 {dt}",
            f"📍 {loc_line}",
            places_line,
            f"👑 Організатор: <b>{organizer_name}</b> · подій: {org_count}",
            f"🎯 Інтереси орг.: {org_interests}{rating_line}"
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

# ========= Collect complete -> notify all =========
async def notify_collected(event_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        ev  = await conn.fetchrow("SELECT * FROM events WHERE id=$1", event_id)
        rows = await conn.fetch("SELECT seeker_id FROM requests WHERE event_id=$1 AND status='approved'", event_id)
    finally:
        await conn.close()
    if not ev: return
    dt = ev['date'].strftime('%Y-%m-%d %H:%M') if ev['date'] else '—'
    addr = (ev['location'] or '—')
    text = (f"🎉 Подія “{ev['title']}” у повному складі!\n"
            f"📅 Час: {dt}\n"
            f"📍 Адреса: {addr}\n"
            f"До зустрічі!")
    ids = [r['seeker_id'] for r in rows] + [ev['user_id']]
    for uid in ids:
        try:
            await bot.send_message(uid, text)
        except Exception:
            pass

# ========= Message router (main FSM) =========
@dp.message(F.text)
async def handle_steps(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    schedule_reset_to_menu(uid)

    # ===== Головне меню =====
    if text == BTN_PROFILE and st.get('step') in (None, 'menu'):
        user = await get_user_from_db(uid)
        if user and user.get('photo'):
            avg = await get_organizer_avg_rating(uid)
            avg_line = f"\n⭐ Рейтинг організатора: {avg:.1f}/10" if avg else ""
            await message.answer_photo(
                user['photo'],
                caption=(
                    "👤 Профіль:\n"
                    f"📛 {user['name']}\n"
                    f"🏙 {user['city']}\n"
                    f"🎯 {user['interests']}{avg_line}"
                ),
                reply_markup=types.ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text='✏️ Змінити профіль')],[KeyboardButton(text=BTN_BACK)]],
                    resize_keyboard=True
                )
            )
        else:
            await message.answer("Профіль не знайдено або без фото.", reply_markup=main_menu())
        return

    if text == "✏️ Змінити профіль" and st.get('step') == 'menu':
        user = await get_user_from_db(uid) or {}
        st.update({
            'step': 'edit_name',
            'name': user.get('name',''),
            'city': user.get('city',''),
            'photo': user.get('photo',''),
            'interests': user.get('interests',''),
            'phone': user.get('phone','')
        })
        await message.answer("✍️ Нове ім'я або натисни «⏭ Пропустити».", reply_markup=skip_back_kb()); return

    if text == BTN_CREATE:
        if st.get('step') == 'name':
            return
        user = await get_user_from_db(uid)
        if not user:
            await message.answer("⚠️ Спочатку зареєструйся через /start")
            return
    
        st.clear()
        st['step'] = 'create_event_title'
        st['creator_name'] = user.get('name', '')
        st['creator_phone'] = user.get('phone', '')
    
        await message.answer(
            "<b>📝 Назва події</b>\n\n"
            "<i>💡 Коротко опиши суть. Напр.: «Гра в мафію», «Ранкова пробіжка», «Похід на концерт».\n"
            "Це допоможе пошукачам знаходити події за ключовими словами.</i>",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        schedule_create_reminder(uid)
        return

    if text == BTN_SEARCH and st.get('step') in (None, 'menu'):
        st['step'] = 'search_menu'
        await message.answer(
            "Як працює пошук:\n"
            "• 🔎 <b>За ключовим словом</b> — шукає у назві й описі.\n"
            "• 📍 <b>Поруч зі мною</b> — показує івенти в радіусі від обраної точки/гео.\n"
            "• 🔮 <b>За моїми інтересами</b> — підбирає івенти за інтересами у вашому профілі.",
            parse_mode="HTML",
            reply_markup=search_menu_kb()
        ); return

    if text == BTN_MY_CHATS and st.get('step') in (None, 'menu'):
        rows = await list_active_conversations_for_user(uid)
        await message.answer("Ваші активні чати:", reply_markup=types.ReplyKeyboardRemove())
        await bot.send_message(uid, "Список:", reply_markup=chats_list_kb(rows))
        return

    if text == BTN_MY_EVENTS and st.get('step') in (None, 'menu'):
        # СПОЧАТКУ ФІЛЬТРИ — а не одразу список
        st['step'] = 'my_events_filters'
        await message.answer("Оберіть категорію:", reply_markup=types.ReplyKeyboardRemove())
        await bot.send_message(uid, "Фільтри:", reply_markup=myevents_filter_kb())
        return

       # ===== Реєстрація =====
    if st.get('step') == 'name':
        st['name'] = text
        st['step'] = 'city'
        await message.answer(
            "🏙 <b>Місто</b>\n\n"
            "Напиши місто, де ти зазвичай буваєш та плануєш ходити на події. "
            "Так я зможу підбирати івенти поблизу.",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        return

    if st.get('step') == 'city':
        st['city'] = text
        st['step'] = 'photo'
        await message.answer(
            "🖼 <b>Фото профілю</b>\n\n"
            "Додай фото, за яким тебе легко впізнати. Це підвищує довіру до тебе як до учасника/організатора.\n\n"
            "Можеш надіслати селфі, фото з події або будь-яке зручне зображення 🙂",
            parse_mode="HTML",
            reply_markup=back_kb()
        )
        return

    # тут НИЧЕГО про фото не пишем — фото ловится в @dp.message(F.photo)

    if st.get('step') == 'interests':
        st['interests'] = ', '.join([i.strip() for i in text.split(',') if i.strip()])

        try:
            # 1) зберігаємо юзера в БД
            await save_user_to_db(
                uid,
                st.get('phone', ''),
                st.get('name', ''),
                st.get('city', ''),
                st.get('photo', ''),
                st['interests']
            )

            await message.answer('✅ Профіль збережено!', reply_markup=main_menu())

            # 2) адмін-сповіщення з Telegram-нікнеймом
            try:
                u = message.from_user
                fn = u.full_name or ""
                uname = f"@{u.username}" if getattr(u, "username", None) else "—"
            except Exception:
                fn = ""
                uname = "—"

            try:
                await notify_admin(
                    "🆕 Новий користувач зареєстрований\n"
                    f"• ID: {uid}\n"
                    f"• Telegram: {uname}\n"
                    f"• Ім'я: {st.get('name') or fn or '—'}\n"
                    f"• Місто: {st.get('city') or '—'}\n"
                    f"• Інтереси: {st.get('interests') or '—'}"
                )
            except Exception as e:
                logging.warning("notify_admin failed: %s", e)

        except Exception as e:
            logging.error('save profile: %s', e)
            await message.answer('❌ Не вдалося зберегти профіль.', reply_markup=main_menu())

        st['step'] = 'menu'
        return


    # ===== Редагування профілю =====
    if st.get('step') == 'edit_name':
        if text != BTN_SKIP: st['name'] = text
        st['step'] = 'edit_city'
        await message.answer("🏙 Нове місто або «⏭ Пропустити».", reply_markup=skip_back_kb()); return
    if st.get('step') == 'edit_city':
        if text != BTN_SKIP: st['city'] = text
        st['step'] = 'edit_photo'
        await message.answer("🖼 Надішли нове фото або «⏭ Пропустити».", reply_markup=skip_back_kb()); return
    if st.get('step') == 'edit_interests':
        if text != BTN_SKIP:
            st['interests'] = ', '.join([i.strip() for i in text.split(',') if i.strip()])
        try:
            await save_user_to_db(uid, st.get('phone',''), st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            await message.answer('✅ Профіль оновлено!', reply_markup=main_menu())
        except Exception as e:
            logging.error('update profile: %s', e); await message.answer('❌ Помилка оновлення профілю.', reply_markup=main_menu())
        st['step'] = 'menu'; return
     # ===== Підписка: перший етап =====
    if st.get('step') == 'subscription_offer':
        if text == "🔔 Так, повідомляти":
            st['step'] = 'subscription_type'
            await message.answer(
                "За яким критерієм повідомляти?",
                reply_markup=subscription_type_kb()
            )
            return
        else:
            st['step'] = 'menu'
            await message.answer("Ок! Повертаю у меню.", reply_markup=main_menu())
            return


    # ===== Підписка: вибір типу =====
    if st.get('step') == 'subscription_type':

        # За інтересами профілю
        if text == "⭐ За інтересами профілю":
            user = await get_user_from_db(uid)
            await add_event_notification(
                user_id=uid,
                type_='interests',
                interests=user.get('interests')
            )
            st['step'] = 'menu'
            await message.answer(
                "🔔 Готово! Повідомимо, коли з’являться події за вашими інтересами.",
                reply_markup=main_menu()
            )
            return

        # За ключовими словами
        if text == "🔑 За ключовими словами":
            st['step'] = 'subscription_word_wait'
            await message.answer("Введіть ключове слово:", reply_markup=back_kb())
            return

        # За радіусом
        if text == "📍 За радіусом":
            st['step'] = 'subscription_radius_wait'
            await message.answer("Введіть радіус у км:", reply_markup=radius_kb())
            return


    # ===== Підписка: ключове слово =====
    if st.get('step') == 'subscription_word_wait':
        kw = text.lower().strip()
        await add_event_notification(
            user_id=uid,
            type_='keyword',
            keyword=kw
        )
        st['step'] = 'menu'
        await message.answer(
            f"🔔 Готово! Повідомимо, коли з’явиться подія з ключовим словом «{kw}».",
            reply_markup=main_menu()
        )
        return


    # ===== Підписка: радіус =====
    if st.get('step') == 'subscription_radius_wait':
        try:
            radius = float(text)
        except:
            radius = 5.0

        lat, lon = st.get('search_lat'), st.get('search_lon')

        await add_event_notification(
            user_id=uid,
            type_='radius',
            lat=lat,
            lon=lon,
            radius_km=radius
        )

        st['step'] = 'menu'
        await message.answer(
            f"🔔 Готово! Повідомимо, коли з’являться події в радіусі {radius} км.",
            reply_markup=main_menu()
        )
        return




    # ===== Створення події =====
    # ===== Створення події =====
        # ===== Створення події =====

    if st.get('step') == 'create_event_title':
        st['event_title'] = text
        st['step'] = 'create_event_description'

        await message.answer(
            "<b>📄 Опис події</b>\n\n"
            "<i>💡 Опиши детально подію, щоб її було простіше знайти за ключовими словами.\n"
            "Наприклад: Збираємось грати у мафію з друзями у гейм-кафе «Piter Pen», шукаємо компанію. "
            "Дружня атмосфера, смачна їжа, пиво, коктейлі. Рівень гри — середній (не професійний).</i>",
            parse_mode="HTML",
            reply_markup=back_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    if st.get('step') == 'create_event_description':
        st['event_description'] = text
        st['step'] = 'create_event_date'

        now = datetime.now()
        await message.answer(
            "<b>📅 Дата та час</b>\n\n"
            "<i>✅ Напиши дату та час проведення івенту у форматі 10.10.2025 19:30. "
            "Вказуй саме час початку івенту. Якщо зручно — можеш просто обрати день у календарі нижче.</i>",
            parse_mode="HTML",
            reply_markup=back_kb()
        )

        await message.answer(
            "🗓 Обери день:",
            reply_markup=month_kb(now.year, now.month)
        )

        st['create_last_touch'] = _now_utc()
        return

    # Користувач ввів дату й час одним рядком (15.11.2025 20:00)
    if st.get('step') == 'create_event_date':
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer(
                "Не впізнав дату. Приклад: 10.10.2025 19:30",
                reply_markup=back_kb()
            )
            return

        st['event_date'] = dt
        st['step'] = 'create_event_location'

        await message.answer(
            "📍 Локація (гео або текстом)\n\n"
            "• Кнопка «поточна геолокація» — надішле ваші поточні координати.\n"
            "• Можна <b>ввести адресу текстом</b> або <b>натиснути «прикріпити» → «геолокація»</b> "
            "і вибрати точку на мапі — це допоможе пошукачам шукати івенти поблизу.",
            parse_mode="HTML",
            reply_markup=location_choice_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    # Користувач спочатку вибрав день у календарі, тепер вводить тільки час
    if st.get('step') == 'create_event_time':
        t = parse_time_hhmm(text)
        if not t:
            await message.answer(
                "Формат часу HH:MM, напр. 19:30",
                reply_markup=back_kb()
            )
            return

        d: date = st.get('picked_date')
        st['event_date'] = datetime(d.year, d.month, d.day, t[0], t[1])
        st['step'] = 'create_event_location'

        await message.answer(
            "📍 Локація (гео або текстом)\n\n"
            "• Кнопка «поточна геолокація» — надішле ваші поточні координати.\n"
            "• Можна <b>ввести адресу текстом</b> або <b>натиснути «прикріпити» → «геолокація»</b> "
            "і вибрати точку на мапі — це допоможе пошукачам шукати івенти поблизу.",
            parse_mode="HTML",
            reply_markup=location_choice_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    if st.get('step') == 'create_event_location':
        if text == "📝 Ввести адресу текстом":
            st['step'] = 'create_event_location_name'
            await message.answer(
                "Вкажи адресу/місце:",
                reply_markup=back_kb()
            )
            st['create_last_touch'] = _now_utc()
            return

        if text == "⏭ Пропустити локацію":
            st['event_location'] = ''
            st['event_lat'] = None
            st['event_lon'] = None
            st['step'] = 'create_event_capacity'

            await message.answer(
                "👥 Місткість\n\n"
                "<i>💡 Вкажи, скільки людей загалом може бути на події (включно з тобою). "
                "Наприклад, якщо ти збираєш гру у футбол 5 на 5, то вкажи число 10.</i>",
                parse_mode="HTML",
                reply_markup=back_kb()
            )

            st['create_last_touch'] = _now_utc()
            return

        # якщо ні текст, ні пропуск – чекаємо геолокацію
        await message.answer(
            "Надішли геолокацію або обери опцію нижче.",
            reply_markup=location_choice_kb()
        )
        return

    if st.get('step') == 'create_event_location_name':
        st['event_location'] = text
        st['step'] = 'create_event_capacity'

        await message.answer(
            "👥 Місткість\n\n"
            "<i>💡 Скільки людей загалом може бути на події (включно з тобою)?</i>",
            parse_mode="HTML",
            reply_markup=back_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    if st.get('step') == 'create_event_capacity':
        try:
            cap = int(text)
            assert cap > 0
        except Exception:
            await message.answer(
                "❗ Введи позитивне число.",
                reply_markup=back_kb()
            )
            return

        st['capacity'] = cap
        st['step'] = 'create_event_needed'

        await message.answer(
            "👤 Скільки ще учасників шукаєш?\n\n"
            "<i>💡 Вкажи кількість людей, яких хочеш знайти за допомогою Findsy. "
            "Наприклад, якщо для гри у футбол у тебе вже є своя команда з 5 людей, "
            "а ти шукаєш команду супротивника, то вкажи число 5.</i>",
            parse_mode="HTML",
            reply_markup=back_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    if st.get('step') == 'create_event_needed':
        try:
            need = int(text)
            cap = st['capacity']
            assert 0 < need <= cap
        except Exception:
            await message.answer(
                f"❗ Від 1 до {st.get('capacity')}",
                reply_markup=back_kb()
            )
            return

        st['needed_count'] = need
        st['step'] = 'create_event_photo'

        await message.answer(
            "📸 Фото події (опційно)\n\n"
            "<i>💡 Додай фото — це допоможе пошукачам швидше зорієнтуватися та зацікавитися.</i>",
            parse_mode="HTML",
            reply_markup=skip_back_kb()
        )

        st['create_last_touch'] = _now_utc()
        return

    if text == BTN_SKIP and st.get('step') == 'create_event_photo':
        st['event_photo'] = None
        st['step'] = 'create_event_review'

        await send_event_review(message.chat.id, st)
        st['create_last_touch'] = _now_utc()
        return

    if text == '✅ Опублікувати' and st.get('step') == 'create_event_review':
        try:
            row = await save_event_to_db(
                user_id=uid,
                creator_name=st.get('creator_name', ''),
                creator_phone=st.get('creator_phone', ''),
                title=st['event_title'],
                description=st['event_description'],
                date=st['event_date'],
                location=st.get('event_location', ''),
                capacity=st['capacity'],
                needed_count=st['needed_count'],
                status='active',
                location_lat=st.get('event_lat'),
                location_lon=st.get('event_lon'),
                photo=st.get('event_photo')
            )

            # 🔔 Перевіряємо підписки на нові івенти
            if row:
                try:
                    await check_event_notifications(row)
                except Exception as e:
                    logging.warning(f"check_event_notifications error: {e}")

            await message.answer(
                "🚀 Подія опублікована і доступна пошукачам! "
                "Коли хтось захоче долучитися, ти отримаєш повідомлення про запит.",
                reply_markup=main_menu()
            )

            # адмін-сповіщення
            try:
                dt_str = st['event_date'].strftime('%Y-%m-%d %H:%M')
            except Exception:
                dt_str = '—'

            try:
                if st.get('event_location'):
                    loc_line = st.get('event_location')
                elif st.get('event_lat') is not None and st.get('event_lon') is not None:
                    lat = float(st.get('event_lat'))
                    lon = float(st.get('event_lon'))
                    loc_line = f"{lat:.5f}, {lon:.5f}"
                else:
                    loc_line = "—"
            except Exception:
                loc_line = "—"

            organizer_name = (
                st.get('creator_name')
                or (message.from_user.full_name if message.from_user else '')
                or str(uid)
            )

            try:
                await notify_admin(
                    "🆕 Створено новий івент\n"
                    f"• ID: {row['id'] if row else '—'}\n"
                    f"• Організатор: {organizer_name}\n"
                    f"• Title: {st.get('event_title')}\n"
                    f"• Коли: {dt_str}\n"
                    f"• Де: {loc_line}\n"
                    f"• Місць: {st.get('capacity')} | Шукаємо ще: {st.get('needed_count')}"
                )
            except Exception as e:
                logging.warning("notify_admin (event) failed: %s", e)

        except Exception:
            logging.exception("publish")
            await message.answer(
                "❌ Помилка публікації",
                reply_markup=main_menu()
            )

        st['step'] = 'menu'
        return

    if text == '✏️ Редагувати' and st.get('step') == 'create_event_review':
        st['step'] = 'create_event_title'
        await message.answer(
            "📝 Нова назва:",
            reply_markup=back_kb()
        )
        return

    if text == '❌ Скасувати' and st.get('step') == 'create_event_review':
        st['step'] = 'menu'
        await message.answer(
            "❌ Створення події скасовано.",
            reply_markup=main_menu()
        )
        return

    # ===== Пошук =====


    # ===== Пошук =====

    # --- Пошук за ключовим словом ---
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_KW:
        st['step'] = 'search_keyword_wait'
        await message.answer("Введіть ключове слово:", reply_markup=back_kb())
        return
    
    if st.get('step') == 'search_keyword_wait':
        st['search_keyword'] = text.lower().strip()
        rows = await find_events_by_kw(text, limit=10)
    
        if not rows:
            st['step'] = 'subscription_offer'
            st['subscription_origin'] = 'keyword'
            await message.answer(
                "Нічого не знайдено 😕\n\n"
                "Бажаєте отримати сповіщення, коли з’явиться подія з таким словом?",
                reply_markup=subscription_offer_kb()
            )
            return
    
        await send_event_cards(message.chat.id, rows)
        st['step'] = 'menu'
        return
    
    
    # --- Пошук за інтересами ---
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_MINE:
        rows = await find_events_by_user_interests(uid, limit=20)
    
        if not rows:
            st['step'] = 'subscription_offer'
            st['subscription_origin'] = 'interests'
            await message.answer(
                "Поки немає подій за вашими інтересами.\n\n"
                "Хочете отримувати сповіщення, коли з’являться відповідні події?",
                reply_markup=subscription_offer_kb()
            )
            return
    
        await send_event_cards(message.chat.id, rows)
        st['step'] = 'menu'
        return
    
    
    # --- Пошук за геолокацією ---
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_NEAR:
        st['step'] = 'search_geo_wait_location'
        await message.answer(
            "Надішліть геолокацію або оберіть точку на мапі.",
            reply_markup=location_choice_kb()
        )
        return
    
    if st.get('step') == 'search_geo_wait_location':
        # геолокація отримана у handler Location
        # переходимо до радіусу
        st['step'] = 'search_geo_wait_radius'
        await message.answer("📏 Вкажіть радіус у км:", reply_markup=radius_kb())
        return
    
    if st.get('step') == 'search_geo_wait_radius':
        try:
            radius = float(text)
        except:
            radius = 5.0
    
        lat = st.get('search_lat')
        lon = st.get('search_lon')
    
        rows = await find_events_near(lat, lon, radius, limit=10)
    
        if not rows:
            st['step'] = 'subscription_offer'
            st['subscription_origin'] = 'radius'
            st['subscription_radius'] = radius
            await message.answer(
                f"Поруч подій не знайдено в радіусі {radius} км 😕\n\n"
                "Хочете отримувати сповіщення, коли з’являться події у цьому радіусі?",
                reply_markup=subscription_offer_kb()
            )
            return
    
        await send_event_cards(message.chat.id, rows)
        st['step'] = 'menu'
        return


    # ===== Редагування івента (inline -> текст) =====
    if st.get('step') == 'edit_event_title':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "title", text)
        await message.answer("📝 Назву оновлено." if ok else "❌ Не вдалося оновити назву.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено назву події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_descr':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "description", text)
        await message.answer("📄 Опис оновлено." if ok else "❌ Не вдалося оновити опис.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено опис події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_datetime':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer("Не впізнав дату. Приклад: 10.10.2025 19:30", reply_markup=back_kb()); return
        ok = await update_event_field(ev_id, uid, "date", dt)
        await message.answer("📅 Дату/час оновлено." if ok else "❌ Не вдалося оновити дату.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено дату/час події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_addr':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "location", text)
        await message.answer("📍 Адресу оновлено." if ok else "❌ Не вдалося оновити адресу.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено адресу події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_capacity':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        try:
            cap = int(text); assert cap > 0
        except Exception:
            await message.answer("Введіть додатне число.", reply_markup=back_kb()); return
        ok = await update_event_field(ev_id, uid, "capacity", cap)
        await message.answer("👥 Місткість оновлено." if ok else "❌ Не вдалося оновити місткість.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено місткість події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_needed':
        ev_id = st.get('edit_event_id')
        if not ev_id:
            await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        try:
            need = int(text); assert need >= 0
        except Exception:
            await message.answer("Введіть число ≥ 0.", reply_markup=back_kb()); return
        ok = await update_event_field(ev_id, uid, "needed_count", need)
        await message.answer("👤 К-ть вільних місць оновлено." if ok else "❌ Не вдалося оновити к-ть місць.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено кількість вільних місць.")
        st['step']='menu'; return

    # ===== Роутинг повідомлень у активний чат =====
    active_conv_id = st.get('active_conv_id')
    if active_conv_id:
        conv = await get_conversation(active_conv_id)
        now = _now_utc()
        if not conv or conv['status'] != 'active' or conv['expires_at'] <= now:
            await message.answer("Чат недоступний або завершений. Відкрийте інший у «📨 Мої чати».", reply_markup=main_menu())
            st['active_conv_id'] = None
            return
        partner_id = conv['seeker_id'] if uid == conv['organizer_id'] else conv['organizer_id']
        try:
            await save_message(active_conv_id, uid, text)
            await bot.send_message(partner_id, f"💬 {message.from_user.full_name}:\n{text}")
        except Exception as e:
            logging.warning("relay failed: %s", e)
        return

    # Якщо немає активного конверса — підкажемо про «Мої чати»
    rows = await list_active_conversations_for_user(uid)
    if rows:
        await message.answer("У вас є активні чати. Виберіть у меню «📨 Мої чати».", reply_markup=main_menu()); return

# ========= JOIN / заявки =========
@dp.callback_query(F.data.startswith("join:"))
async def cb_join(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    seeker_id = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # перевіряємо, чи не було заявки раніше
        existing = await conn.fetchrow(
            "SELECT id, status FROM requests WHERE event_id=$1 AND seeker_id=$2",
            event_id, seeker_id
        )
        if existing:
            st = existing['status']
            msg = (
                "Заявку вже відправлено, очікуйте відповіді ✅" if st == 'pending'
                else ("Заявку вже підтверджено. Перейдіть у «📨 Мої чати»" if st == 'approved'
                      else "На жаль, вашу заявку відхилено.")
            )
            await safe_alert(call, msg, show_alert=False)
            await conn.close()
            return

        # створюємо нову заявку
        req = await conn.fetchrow(
            "INSERT INTO requests (event_id, seeker_id) VALUES ($1,$2) RETURNING id",
            event_id, seeker_id
        )
        ev = await conn.fetchrow(
            "SELECT id, title, user_id FROM events WHERE id=$1",
            event_id
        )
        seeker = await conn.fetchrow(
            "SELECT name, city, interests, photo FROM users WHERE telegram_id::text=$1",
            str(seeker_id)
        )
        await conn.close()

        await safe_alert(call, "Запит на приєднання надіслано ✅", show_alert=False)

        # Додаткове повідомлення пошукачу
        try:
            await bot.send_message(
                seeker_id,
                "✅ Заявка на участь відправлена.\n\n"
                "Організатор отримав вашу заявку. "
                "Як тільки він підтвердить участь, ви зможете зв’язатися з ним "
                "через Findsy або напряму у Telegram."
            )
        except Exception:
            pass

        if ev:
            caption = (f"🔔 Запит на участь у події “{ev['title']}”.\n\n")
               
        if ev:
            # username пошукача
            try:
                ch = await bot.get_chat(seeker_id)
                seeker_uname_link = tg_link_from_username(getattr(ch, "username", None))
            except Exception:
                seeker_uname_link = "нікнейм відсутній"

            # рейтинг організатора
            avg = await get_organizer_avg_rating(ev['user_id'])
            rating_line = f"⭐ Твій рейтинг як організатора: {avg:.1f}/10\n" if avg else ""

            caption = (
                f"🔔 Запит на участь у події “{ev['title']}”.\n\n"
                f"👤 Пошукач: <b>{seeker['name'] if seeker else call.from_user.full_name}</b>\n"
                f"🏙 Місто: {(seeker['city'] or '—') if seeker else '—'}\n"
                f"🎯 Інтереси: {(seeker['interests'] or '—') if seeker else '—'}\n"
                f"📲 Telegram пошукача: {seeker_uname_link}\n"
                f"{rating_line}"
                f"Що робимо?"
            )

            kb = request_actions_kb(req["id"])

            if seeker and seeker.get('photo'):
                try:
                    await bot.send_photo(
                        ev["user_id"],
                        seeker['photo'],
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                    return
                except Exception:
                    pass

            await bot.send_message(
                ev["user_id"],
                caption,
                parse_mode="HTML",
                reply_markup=kb
            )
    except Exception:
        logging.exception("join error")
        await safe_alert(call, "Помилка, спробуйте ще раз")


# ========= OPEN CHAT FROM REQUEST =========
async def reminder_decision(req_id: int, organizer_id: int, event_id: int, delay_min: int = 30):
    try:
        await asyncio.sleep(delay_min * 60)
        conn = await asyncpg.connect(DATABASE_URL)
        req = await conn.fetchrow("SELECT status FROM requests WHERE id=$1", req_id)
        await conn.close()
        if req and req['status'] == 'pending':
            kb = request_actions_kb(req_id)
            try:
                await bot.send_message(organizer_id, "⏰ Нагадування: потрібно прийняти рішення щодо заявки.", reply_markup=kb)
            except Exception:
                pass
    except Exception as e:
        logging.warning("reminder failed: %s", e)

@dp.callback_query(F.data.startswith("reqchat:"))
async def cb_req_open_chat(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1", req_id)
        if not req: await safe_alert(call, "Заявку не знайдено."); await conn.close(); return
        ev  = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", req['event_id'])
        await conn.close()
        if not ev or ev['user_id'] != call.from_user.id:
            await safe_alert(call, "Лише організатор може відкрити чат."); return

        conv = await get_or_create_conversation(ev['id'], ev['user_id'], req['seeker_id'], minutes=30)
        await safe_alert(call, "💬 Чат відкрито. Див. «📨 Мої чати».", show_alert=False)

        asyncio.create_task(reminder_decision(req_id, ev['user_id'], ev['id'], delay_min=30))

        until = conv['expires_at'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        try:
            await bot.send_message(req['seeker_id'],
                f"💬 Організатор відкрив чат щодо події “{ev['title']}”. "
                f"Чат активний до {until}. Перейдіть у меню «📨 Мої чати».")
        except Exception:
            pass
    except Exception:
        logging.exception("reqchat error")
        await safe_alert(call, "Сталася помилка")

# ========= APPROVE / REJECT =========
@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        async with conn.transaction():
            req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1 FOR UPDATE", req_id)
            if not req:
                await safe_alert(call, "Заявку не знайдено.")
                return

            ev = await conn.fetchrow("SELECT * FROM events WHERE id=$1 FOR UPDATE", req['event_id'])
            if not ev:
                await safe_alert(call, "Подію не знайдено.")
                return

            if call.from_user.id != ev['user_id']:
                await safe_alert(call, "Лише організатор може підтвердити.")
                return

            if req['status'] == 'approved':
                await safe_alert(call, "Вже підтверджено.")
                return

            if req['status'] == 'rejected':
                await safe_alert(call, "Вже відхилено.")
                return

            if ev['needed_count'] is not None and ev['needed_count'] <= 0:
                await safe_alert(call, "Немає вільних місць.")
                return

            conv = await conn.fetchrow("""
                SELECT * FROM conversations
                 WHERE event_id=$1 AND organizer_id=$2 AND seeker_id=$3
                   AND status='active' AND expires_at > now()
                 ORDER BY id DESC LIMIT 1
            """, ev['id'], ev['user_id'], req['seeker_id'])

            if not conv:
                expires = _now_utc() + timedelta(minutes=30)
                conv = await conn.fetchrow("""
                    INSERT INTO conversations (event_id, organizer_id, seeker_id, expires_at)
                    VALUES ($1,$2,$3,$4) RETURNING *
                """, ev['id'], ev['user_id'], req['seeker_id'], expires)

            await conn.execute("UPDATE requests SET status='approved' WHERE id=$1", req_id)

            row = await conn.fetchrow("""
                UPDATE events
                   SET needed_count = CASE WHEN needed_count > 0 THEN needed_count - 1 ELSE 0 END,
                       status        = CASE WHEN needed_count <= 1 THEN 'collected' ELSE status END
                 WHERE id = $1
                 RETURNING needed_count, status, title, user_id, location, date, id
            """, ev['id'])

        await conn.close()

        new_needed = row['needed_count']
        ev_title   = row['title']
        ev_id      = row['id']
        organizer_id = row['user_id']

        # username організатора для Direct
        try:
            ch = await bot.get_chat(organizer_id)
            uname = f"@{ch.username}" if getattr(ch, "username", None) else None
        except Exception:
            uname = None

        # Кнопки для пошукача: через Findsy + Direct
        btns = [
            InlineKeyboardButton(text="💬 Через Findsy", callback_data=f"chat:open:{conv['id']}")
        ]
        if uname:
            btns.append(
                InlineKeyboardButton(text="➡️ Написати у Direct", url=f"https://t.me/{uname[1:]}")
            )
        kb_seeker = InlineKeyboardMarkup(inline_keyboard=[btns])

        await safe_alert(call, "✅ Підтверджено", show_alert=False)

        await bot.send_message(
            req['seeker_id'],
            f"✅ Вас прийнято до події “{ev_title}”.\n\n"
            f"Обирайте, як зручно зв’язатися з організатором:",
            reply_markup=kb_seeker
        )

        await bot.send_message(
            call.from_user.id,
            f"✅ Учасника підтверджено. Залишилось місць: {new_needed}."
        )

        if new_needed == 0:
            await notify_collected(ev_id)

    except Exception:
        logging.exception("approve error")
        await safe_alert(call, "Сталася помилка під час підтвердження")



@dp.callback_query(F.data.startswith("reject:"))
async def cb_reject(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        req = await conn.fetchrow("UPDATE requests SET status='rejected' WHERE id=$1 RETURNING seeker_id, event_id", req_id)
        ev  = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", req['event_id']) if req else None
        await conn.close()
        if not req: await safe_alert(call, "Заявку не знайдено."); return
        if ev and call.from_user.id != ev['user_id']:
            await safe_alert(call, "Лише організатор може відхилити."); return
        await safe_alert(call, "❌ Відхилено", show_alert=False)
        if ev:
            try: await bot.send_message(req['seeker_id'], f"❌ На жаль, запит на подію “{ev['title']}” відхилено.")
            except Exception: pass
    except Exception:
        logging.exception("reject error")
        await safe_alert(call, "Сталася помилка відхилення")

# ========= Chats: open / history / close =========
@dp.callback_query(F.data.startswith("chat:open:"))
async def cb_chat_open(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id
    conv = await get_conversation(conv_id)
    if not conv or conv['status'] != 'active' or not (conv['organizer_id']==uid or conv['seeker_id']==uid):
        await safe_alert(call, "Чат недоступний."); return
    if conv['expires_at'] <= _now_utc():
        await safe_alert(call, "Чат прострочено."); return
    user_states.setdefault(uid, {})['active_conv_id'] = conv_id
    await call.answer()
    msgs = await load_last_messages(conv_id, 20)
    if msgs:
        transcript = []
        for m in reversed(msgs):
            who = "Ви" if m['sender_id']==uid else "Співрозмовник"
            ts  = m['created_at'].strftime('%H:%M')
            transcript.append(f"[{ts}] {who}: {m['text']}")
        await bot.send_message(uid, "📜 Останні повідомлення:\n" + "\n".join(transcript))
    await bot.send_message(uid, "💬 Чат відкрито. Пишіть повідомлення — я перешлю співрозмовнику.", reply_markup=main_menu())

@dp.callback_query(F.data.startswith("chat:history:"))
async def cb_chat_history(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id
    conv = await get_conversation(conv_id)
    if not conv or not (conv['organizer_id']==uid or conv['seeker_id']==uid):
        await safe_alert(call, "Чат недоступний."); return
    await call.answer()
    msgs = await load_last_messages(conv_id, 20)
    if not msgs:
        await bot.send_message(uid, "Поки що історія порожня."); return
    transcript = []
    for m in reversed(msgs):
        who = "Ви" if m['sender_id']==uid else "Співрозмовник"
        ts  = m['created_at'].strftime('%d.%m %H:%M')
        transcript.append(f"[{ts}] {who}: {m['text']}")
    await bot.send_message(uid, "📜 Останні повідомлення:\n" + "\n".join(transcript))

@dp.callback_query(F.data.startswith("chat:close:"))
async def cb_chat_close(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    conv = await get_conversation(conv_id)
    if not conv:
        await safe_alert(call, "Чат не знайдено."); return
    await close_conversation(conv_id, reason='closed')
    await safe_alert(call, "✅ Чат закрито", show_alert=False)
    other = conv['seeker_id'] if call.from_user.id == conv['organizer_id'] else conv['organizer_id']
    try: await bot.send_message(other, "ℹ️ Співрозмовник завершив чат.")
    except Exception: pass

@dp.message(Command("stopchat"))
async def stop_chat(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    conv_id = st.get('active_conv_id')
    if not conv_id:
        await message.answer("Немає вибраного чату. Відкрийте його у «📨 Мої чати».", reply_markup=main_menu()); return
    conv = await get_conversation(conv_id)
    if not conv or conv['status'] != 'active':
        await message.answer("Чат вже закритий.", reply_markup=main_menu()); return
    await close_conversation(conv_id, reason='closed')
    other = conv['seeker_id'] if uid == conv['organizer_id'] else conv['organizer_id']
    await message.answer("✅ Чат завершено.", reply_markup=main_menu())
    try: await bot.send_message(other, "ℹ️ Співрозмовник завершив чат.")
    except Exception: pass

# ========= Events: info / reqs / members / edit =========
@dp.callback_query(F.data.startswith("event:info:"))
async def cb_event_info(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[2])
    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("SELECT * FROM events WHERE id=$1", ev_id)
    await conn.close()
    if not ev:
        await safe_alert(call, "Подію не знайдено."); return
    dt = ev['date'].strftime('%Y-%m-%d %H:%M') if ev['date'] else '—'
    filled = max((ev['capacity'] or 0) - (ev['needed_count'] or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{ev['capacity']} • шукаємо ще: {ev['needed_count']}"
    avg = await get_organizer_avg_rating(ev['user_id'])
    rating_line = f"\n⭐ Рейтинг організатора: {avg:.1f}/10" if avg else ""
    text = (f"<b>{ev['title']}</b>\n"
            f"📅 {dt}\n📍 {(ev['location'] or '—')}\n{places_line}\n"
            f"Статус: {ev['status']}{rating_line}\n\n{(ev['description'] or '').strip()[:600]}")
    await call.answer()
    if ev.get('photo'):
        try:
            await bot.send_photo(call.from_user.id, ev['photo'], caption=text, parse_mode="HTML"); return
        except Exception:
            pass
    await bot.send_message(call.from_user.id, text, parse_mode="HTML")

@dp.callback_query(F.data == "myevents:filters")
async def cb_myevents_filters(call: types.CallbackQuery):
    await call.answer()
    await bot.send_message(call.from_user.id, "Фільтри:", reply_markup=myevents_filter_kb())

@dp.callback_query(F.data.startswith("myevents:filter:"))
async def cb_myevents_filter(call: types.CallbackQuery):
    kind = call.data.split(":")[2]
    rows = await list_user_events(call.from_user.id, filter_kind=kind)
    await call.answer()
    await bot.send_message(call.from_user.id, f"Ваші події ({kind}):", reply_markup=my_events_kb(rows))

@dp.callback_query(F.data.startswith("event:reqs:"))
async def cb_event_requests(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[2])
    rows = await list_pending_requests(event_id)
    if not rows:
        await safe_alert(call, "Немає очікуючих заявок")
        return

    await call.answer()
    for r in rows:
        # username пошукача
        try:
            ch = await bot.get_chat(r['seeker_id'])
            seeker_uname_link = tg_link_from_username(getattr(ch, "username", None))
        except Exception:
            seeker_uname_link = "нікнейм відсутній"

        cap = (
            f"👤 <b>{r['name'] or ('id ' + str(r['seeker_id']))}</b>\n"
            f"🏙 {r['city'] or '—'}\n"
            f"🎯 {r['interests'] or '—'}\n"
            f"📲 Telegram: {seeker_uname_link}\n\n"
            f"Що робимо?"
        )
        kb = request_actions_kb(r['req_id'])
        if r.get('photo'):
            try:
                await bot.send_photo(
                    call.from_user.id,
                    r['photo'],
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=kb
                )
                continue
            except Exception:
                pass
        await bot.send_message(
            call.from_user.id,
            cap,
            parse_mode="HTML",
            reply_markup=kb
        )


@dp.callback_query(F.data.startswith("event:members:"))
async def cb_event_members(call: types.CallbackQuery):
    """Показати підтверджених учасників (і @username, і прямий чат Telegram)."""
    event_id = int(call.data.split(":")[2])
    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
    if not ev:
        await conn.close(); await safe_alert(call, "Подію не знайдено."); return

    approved = await conn.fetchrow("""
        SELECT 1 FROM requests WHERE event_id=$1 AND seeker_id=$2 AND status='approved' LIMIT 1
    """, event_id, call.from_user.id)
    rows = await conn.fetch("""
        SELECT r.seeker_id, u.name, u.city, u.interests, u.photo
        FROM requests r
        LEFT JOIN users u ON u.telegram_id::text=r.seeker_id::text
        WHERE r.event_id=$1 AND r.status='approved'
        ORDER BY r.created_at ASC
    """, event_id)
    await conn.close()

    if ev['user_id'] != call.from_user.id and not approved:
        await safe_alert(call, "Перегляд учасників недоступний."); return

    await call.answer()
    await bot.send_message(call.from_user.id, f"👥 Підтверджені учасники “{ev['title']}”:")
    for r in rows:
        # отримаємо username напряму з Telegram
        try:
            ch = await bot.get_chat(r['seeker_id'])
            uname = f"@{ch.username}" if getattr(ch, "username", None) else "—"
        except Exception:
            uname = "—"

        cap = (f"👤 <b>{r['name'] or ('id ' + str(r['seeker_id']))}</b>\n"
               f"🏙 {r['city'] or '—'}\n"
               f"🎯 {r['interests'] or '—'}\n"
               f"tg: {uname}\n\n"
               f"Можна: написати напряму у Telegram або відкрити короткий чат у Findsy.")
        # Кнопки: Direct (t.me/username якщо є) + локальний чат
        buttons = []
        if uname != "—":
            buttons.append(InlineKeyboardButton(text="➡️ Direct Message", url=f"https://t.me/{uname[1:]}"))
        if ev['user_id'] == call.from_user.id:
            buttons.append(InlineKeyboardButton(text="💬 Відкрити чат", callback_data=f"event:memberchat:{event_id}:{r['seeker_id']}"))
        kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None

        if r.get('photo'):
            try:
                await bot.send_photo(call.from_user.id, r['photo'], caption=cap, parse_mode="HTML", reply_markup=kb)
                continue
            except Exception:
                pass
        await bot.send_message(call.from_user.id, cap, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("event:orginfo:"))
async def cb_event_orginfo(call: types.CallbackQuery):
    """Показати картку організатора + кнопки для зв'язку."""
    event_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        if not ev:
            await conn.close()
            await safe_alert(call, "Подію не знайдено.")
            return

        # перевіряємо, що юзер — підтверджений учасник або сам організатор
        approved = await conn.fetchrow("""
            SELECT 1
            FROM requests
            WHERE event_id=$1 AND seeker_id=$2 AND status='approved'
            LIMIT 1
        """, event_id, uid)

        org = await conn.fetchrow(
            "SELECT name, city, interests FROM users WHERE telegram_id::text=$1",
            str(ev['user_id'])
        )
    finally:
        await conn.close()

    if not approved and uid != ev['user_id']:
        await safe_alert(call, "Контакти організатора доступні лише учасникам події.")
        return

    # Telegram username організатора
    try:
        ch = await bot.get_chat(ev['user_id'])
        uname = f"@{ch.username}" if getattr(ch, "username", None) else "—"
    except Exception:
        uname = "—"

    await call.answer()

    txt = (
        f"👑 <b>Організатор події “{ev['title']}”</b>\n\n"
        f"Ім'я: {org['name'] if org and org['name'] else '—'}\n"
        f"Місто: {org['city'] if org and org['city'] else '—'}\n"
        f"Інтереси: {org['interests'] if org and org['interests'] else '—'}\n"
        f"Telegram: {uname}"
    )

    buttons = [
        InlineKeyboardButton(text="💬 Через Findsy", callback_data=f"event:contactorg:{event_id}")
    ]
    if uname != "—":
        buttons.append(
            InlineKeyboardButton(text="➡️ Написати у Direct", url=f"https://t.me/{uname[1:]}")
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[buttons])
    await bot.send_message(uid, txt, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("event:contactorg:"))
async def cb_event_contactorg(call: types.CallbackQuery):
    """Учасник відкриває короткий чат з організатором через Findsy."""
    event_id = int(call.data.split(":")[2])
    uid = call.from_user.id

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        if not ev:
            await conn.close()
            await safe_alert(call, "Подію не знайдено.")
            return

        approved = await conn.fetchrow("""
            SELECT 1
            FROM requests
            WHERE event_id=$1 AND seeker_id=$2 AND status='approved'
            LIMIT 1
        """, event_id, uid)
    finally:
        await conn.close()

    if not approved and uid != ev['user_id']:
        await safe_alert(call, "Чат з організатором доступний лише учасникам події.")
        return

    # Створюємо / знаходимо розмову
    conv = await get_or_create_conversation(event_id, ev['user_id'], uid, minutes=30)

    await safe_alert(call, "💬 Чат відкрито. Дивіться у «📨 Мої чати».", show_alert=False)

    until = conv['expires_at'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # Повідомляємо учасника
    try:
        await bot.send_message(
            uid,
            f"💬 Чат з організатором події “{ev['title']}” відкрито.\n"
            f"Чат активний до {until}. Знайдеш його у меню «📨 Мої чати»."
        )
    except Exception:
        pass

    # Повідомляємо організатора
    try:
        await bot.send_message(
            ev['user_id'],
            f"💬 Учасник відкрив чат щодо події “{ev['title']}”. "
            f"Перейдіть у «📨 Мої чати», щоб відповісти."
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("event:memberchat:"))
async def cb_event_memberchat(call: types.CallbackQuery):
    event_id, seeker_id = map(int, call.data.split(":")[2:4])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        await conn.close()
        if not ev:
            await safe_alert(call, "Подію не знайдено."); return
        if ev['user_id'] != call.from_user.id:
            await safe_alert(call, "Лише організатор може відкривати чат."); return

        conv = await get_or_create_conversation(event_id, ev['user_id'], seeker_id, minutes=30)
        await safe_alert(call, "💬 Чат відкрито. Див. «📨 Мої чати».", show_alert=False)

        until = conv['expires_at'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        try:
            await bot.send_message(seeker_id,
                f"💬 Організатор відкрив чат щодо події “{ev['title']}”. "
                f"Чат активний до {until}. Перейдіть у меню «📨 Мої чати».")
        except Exception:
            pass
    except Exception:
        logging.exception("memberchat error")
        await safe_alert(call, "Сталася помилка при відкритті чату")

# ===== Edit (inline entrypoints) =====
@dp.callback_query(F.data.startswith("event:edit:"))
async def cb_event_edit(call: types.CallbackQuery):
    parts = call.data.split(":")
    if len(parts) == 3:
        ev_id = int(parts[2])
        await call.answer()
        await bot.send_message(call.from_user.id, "Що редагуємо?", reply_markup=event_edit_menu_kb(ev_id))
        return
    field = parts[2]; ev_id = int(parts[3])
    uid = call.from_user.id
    user_states.setdefault(uid, {})['edit_event_id'] = ev_id
    if field == "title":
        user_states[uid]['step'] = 'edit_event_title'
        await call.answer(); await bot.send_message(uid, "📝 Введіть нову назву:", reply_markup=back_kb()); return
    if field == "descr":
        user_states[uid]['step'] = 'edit_event_descr'
        await call.answer(); await bot.send_message(uid, "📄 Введіть новий опис:", reply_markup=back_kb()); return
    if field == "datetime":
        user_states[uid]['step'] = 'edit_event_datetime'
        await call.answer(); await bot.send_message(uid, "📅 Введіть дату й час (10.10.2025 19:30):", reply_markup=back_kb()); return
    if field == "addr":
        user_states[uid]['step'] = 'edit_event_addr'
        await call.answer(); await bot.send_message(uid, "📍 Введіть адресу:", reply_markup=back_kb()); return
    if field == "capacity":
        user_states[uid]['step'] = 'edit_event_capacity'
        await call.answer(); await bot.send_message(uid, "👥 Введіть нову місткість (число > 0):", reply_markup=back_kb()); return
    if field == "needed":
        user_states[uid]['step'] = 'edit_event_needed'
        await call.answer(); await bot.send_message(uid, "👤 Введіть нову к-ть вільних місць (≥ 0):", reply_markup=back_kb()); return
    if field == "photo":
        user_states[uid]['step'] = 'edit_event_photo'
        await call.answer(); await bot.send_message(uid, "📸 Надішліть нове фото:", reply_markup=back_kb()); return

async def _refresh_my_events_inline(call: types.CallbackQuery, owner_id: int):
    rows = await list_user_events(owner_id, FILTER_ACTIVE)
    try:
        await call.message.edit_reply_markup(reply_markup=my_events_kb(rows))
    except Exception as e:
        logging.warning("edit_reply_markup failed: %s", e)

@dp.callback_query(F.data.startswith("event:delete:"))
async def cb_event_delete(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[2])
    ok = await update_event_status(event_id, call.from_user.id, 'deleted')
    await safe_alert(call, "🗑 Івент приховано" if ok else "Не вдалося змінити статус", show_alert=not ok)
    if ok: await _refresh_my_events_inline(call, call.from_user.id)

@dp.callback_query(F.data.startswith("event:cancel:"))
async def cb_event_cancel(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[2])
    ok = await update_event_status(event_id, call.from_user.id, 'cancelled')
    await safe_alert(call, "🚫 Івент скасовано" if ok else "Не вдалося змінити статус", show_alert=not ok)
    if ok: await _refresh_my_events_inline(call, call.from_user.id)

@dp.callback_query(F.data.startswith("event:open:"))
async def cb_event_open(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[2])
    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("SELECT needed_count FROM events WHERE id=$1 AND user_id::text=$2", event_id, str(call.from_user.id))
    await conn.close()
    if not ev:
        await safe_alert(call, "Подію не знайдено."); return
    if ev['needed_count'] <= 0:
        await safe_alert(call, "Неможливо відкрити: немає вільних місць."); return
    ok = await update_event_status(event_id, call.from_user.id, 'active')
    await safe_alert(call, "♻️ Івент знову активний" if ok else "Не вдалося змінити статус", show_alert=not ok)
    if ok: await _refresh_my_events_inline(call, call.from_user.id)

# ===== Підписка: кнопки після відправлення першої події =====

@dp.callback_query(F.data.startswith("notif_continue:"))
async def cb_notif_continue(call: types.CallbackQuery):
    notif_id = int(call.data.split(":")[1])
    try:
        await activate_notification(notif_id)
        await call.answer("Підписку активовано", show_alert=False)
        await bot.send_message(
            call.from_user.id,
            "👍 Добре! Я продовжу надсилати нові події за цією підпискою.",
            reply_markup=main_menu()
        )
    except Exception:
        logging.exception("notif_continue error")
        await call.answer("Помилка, спробуйте ще раз", show_alert=True)


@dp.callback_query(F.data.startswith("notif_stop:"))
async def cb_notif_stop(call: types.CallbackQuery):
    notif_id = int(call.data.split(":")[1])
    try:
        await deactivate_notification(notif_id)
        await call.answer("Відписано", show_alert=False)
        await bot.send_message(
            call.from_user.id,
            "🔕 Гаразд! Більше не надсилатиму події за цією підпискою.",
            reply_markup=main_menu()
        )
    except Exception:
        logging.exception("notif_stop error")
        await call.answer("Помилка, спробуйте ще раз", show_alert=True)


# ===== Учасник виходить з івенту =====
@dp.callback_query(F.data.startswith("event:leave:"))
async def cb_event_leave(call: types.CallbackQuery):
    """Учасник може вийти з івенту (повідомляємо організатора; якщо івент був 'collected' — запропонуємо знову відкрити)."""
    event_id = int(call.data.split(":")[2])
    seeker_id = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        ev = await conn.fetchrow("SELECT id, user_id, title, status FROM events WHERE id=$1", event_id)
        if not ev:
            await conn.close(); await safe_alert(call, "Подію не знайдено."); return
        req = await conn.fetchrow("""
            UPDATE requests SET status='rejected'
            WHERE event_id=$1 AND seeker_id=$2 AND status='approved'
            RETURNING id
        """, event_id, seeker_id)
        if not req:
            await conn.close(); await safe_alert(call, "Ви не значитесь серед підтверджених учасників."); return

        # повернемо одне місце у ліміт
        await conn.execute("""
            UPDATE events
               SET needed_count = CASE WHEN needed_count IS NULL THEN 1 ELSE needed_count + 1 END,
                   status = CASE WHEN status='collected' THEN 'active' ELSE status END
             WHERE id=$1
        """, event_id)
        await conn.close()

        await safe_alert(call, "✅ Ви вийшли з івенту", show_alert=False)

        # Сповістити організатора
        kb = None
        if ev['status'] == 'collected':
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="♻️ Знову опублікувати", callback_data=f"event:open:{event_id}")
            ]])
        try:
            await bot.send_message(ev['user_id'],
                f"ℹ️ Учасник вийшов із події “{ev['title']}”. Місце звільнилося.",
                reply_markup=kb)
        except Exception:
            pass
    except Exception:
        logging.exception("leave error")
        await safe_alert(call, "Сталася помилка. Спробуйте ще раз.")

# ========= Search queries =========
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
              AND e.date IS NOT NULL AND e.date >= now()
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
              AND e.date IS NOT NULL AND e.date >= now()
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
    user = await get_user_from_db(user_id)
    if not user or not user.get('interests'): return []
    tokens = [t.strip() for t in user['interests'].split(",") if t.strip()]
    if not tokens: return []
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
              AND e.date IS NOT NULL AND e.date >= now()
            ORDER BY e.date ASC NULLS LAST, e.id DESC
            LIMIT $2
        """, patterns, limit)
        return rows
    finally:
        await conn.close()

# ========= Background: auto-finish + rating prompt =========
async def fini_and_rate_loop():
    """Кожні 2 хв: переносимо минулі active/collected у finished та шлемо оцінку учасникам."""
    while True:
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            rows = await conn.fetch("""
                UPDATE events
                   SET status='finished'
                 WHERE date IS NOT NULL AND date < now()
                   AND status IN ('active','collected')
                 RETURNING id, user_id, title, date
            """)
            await conn.close()
            for ev in rows:
                conn2 = await asyncpg.connect(DATABASE_URL)
                members = await conn2.fetch("SELECT seeker_id FROM requests WHERE event_id=$1 AND status='approved'", ev['id'])
                await conn2.close()
                if not members: continue
                for m in members:
                    try:
                        await bot.send_message(m['seeker_id'],
                            f"⭐ Оцініть організатора події “{ev['title']}”:",
                            reply_markup=rating_kb(ev['id']))
                    except Exception:
                        pass
        except Exception as e:
            logging.warning("fini_and_rate_loop error: %s", e)
        await asyncio.sleep(120)

# ========= Entrypoint =========
async def main():
    logging.info("Starting polling")
    await init_db()
    asyncio.create_task(fini_and_rate_loop())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())




















































































































