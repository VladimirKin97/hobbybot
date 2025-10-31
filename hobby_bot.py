import os
import logging
import asyncio
import re
import calendar as calmod
from datetime import datetime, timedelta, timezone, date

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
if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Environment variables BOT_TOKEN and DATABASE_URL must be set")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Telegram ID для адмін-сповіщень


# Просте FSM-хранилище + таймери
user_states: dict[int, dict] = {}
# ========= Admin notify helper =========
async def notify_admin(text: str):
    """Відправляє повідомлення адміну, якщо вказано ADMIN_CHAT_ID."""
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
REMINDER_CREATE_MIN = 15     # через 15 хв нагадати про незавершене створення
RESET_TO_MENU_MIN   = 60     # через 60 хв відправити в головне меню

# ========= Labels / Keyboards =========
BTN_PROFILE      = "👤 Мій профіль"
BTN_CREATE       = "➕ Створити подію"
BTN_SEARCH       = "🔍 Знайти подію"
BTN_MY_CHATS     = "📨 Мої чати"
BTN_MY_EVENTS    = "📦 Мої івенти"
BTN_BACK         = "⬅️ Назад"
BTN_SKIP         = "⏭ Пропустити"
BTN_SEARCH_KW    = "🔎 За ключовим словом"
BTN_SEARCH_NEAR  = "📍 Поруч зі мною"
BTN_SEARCH_MINE  = "🔮 За моїми інтересами"

# Фільтри для «Мої івенти»
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
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_BACK)]], resize_keyboard=True)

def skip_back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_BACK)]],
        resize_keyboard=True
    )

def location_choice_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
            [KeyboardButton(text="📝 Ввести адресу текстом"), KeyboardButton(text="⏭ Пропустити локацію")],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

def radius_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="3"), KeyboardButton(text="5")],
            [KeyboardButton(text="10"), KeyboardButton(text="20")],
            [KeyboardButton(text=BTN_BACK)]
        ],
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

def event_publish_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='✅ Опублікувати'), KeyboardButton(text='✏️ Редагувати')],
            [KeyboardButton(text='❌ Скасувати')],
            [KeyboardButton(text=BTN_BACK)]
        ],
        resize_keyboard=True
    )

def request_actions_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Відкрити чат", callback_data=f"reqchat:{req_id}")],
                         [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve:{req_id}"),
                          InlineKeyboardButton(text="❌ Відхилити",   callback_data=f"reject:{req_id}")]]
    )

def event_join_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")]]
    )

def myevents_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Активні", callback_data=f"myevents:filter:{FILTER_ACTIVE}"),
        InlineKeyboardButton(text="✅ Проведені", callback_data=f"myevents:filter:{FILTER_FINISHED}"),
        InlineKeyboardButton(text="🗑 Видалені/Скасовані", callback_data=f"myevents:filter:{FILTER_DELETED}")
    ],[
        InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")
    ]])

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

def my_events_kb(rows: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    ikb = []
    for r in rows:
        dt = (r['date'].strftime('%d.%m %H:%M') if r['date'] else '—')
        role = "(Орг)" if r['role'] == 'owner' else "(Учасник)"
        line  = f"{role} {r['title']} • {dt} • {r['status']}"
        ikb.append([InlineKeyboardButton(text=line, callback_data=f"event:info:{r['id']}")])
        # кнопки керування / перегляд
        if r['role'] == 'owner':
            btns = [
                InlineKeyboardButton(text="👥 Учасники", callback_data=f"event:members:{r['id']}"),
                InlineKeyboardButton(text="🔔 Заявки", callback_data=f"event:reqs:{r['id']}"),
                InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"event:edit:{r['id']}"),
            ]
            if r['status'] in ('active','collected'):
                btns.append(InlineKeyboardButton(text="🗑 Видалити", callback_data=f"event:delete:{r['id']}"))
                btns.append(InlineKeyboardButton(text="🚫 Скасувати", callback_data=f"event:cancel:{r['id']}"))
            elif r['status'] in ('cancelled','deleted','finished'):
                btns.append(InlineKeyboardButton(text="♻️ Відкрити", callback_data=f"event:open:{r['id']}"))
            ikb.append(btns)
        else:
            # Учасник теж може подивитись учасників
            ikb.append([InlineKeyboardButton(text="👥 Учасники", callback_data=f"event:members:{r['id']}")])
    ikb.append([InlineKeyboardButton(text="⬅️ Фільтри", callback_data="myevents:filters")])
    ikb.append([InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")])
    if not rows:
        ikb = [
            [InlineKeyboardButton(text="Подій не знайдено", callback_data="noop")],
            [InlineKeyboardButton(text="⬅️ Фільтри", callback_data="myevents:filters")],
            [InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=ikb)

def chats_list_kb(rows: list[asyncpg.Record]) -> InlineKeyboardMarkup:
    ikb = []
    for r in rows:
        title = (r["title"] or "Подія")
        other = r["other_name"] or f"id {r['other_id']}"
        ikb.append([InlineKeyboardButton(text=f"💬 {title} · {other}", callback_data=f"chat:open:{r['id']}")])
        ikb.append([InlineKeyboardButton(text=f"📜 Історія", callback_data=f"chat:history:{r['id']}")])
        ikb.append([InlineKeyboardButton(text=f"❌ Закрити чат", callback_data=f"chat:close:{r['id']}")])
    ikb.append([InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")])
    if not rows:
        ikb = [
            [InlineKeyboardButton(text="Немає активних чатів", callback_data="noop")],
            [InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=ikb)

async def safe_alert(call: types.CallbackQuery, text: str, show_alert: bool = True):
    try:
        await call.answer(text[:180], show_alert=show_alert)
    except Exception as e:
        logging.warning("call.answer failed: %s", e)

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
    await call.message.answer("⏰ Введіть час у форматі HH:MM (наприклад, 19:30).", reply_markup=back_kb())
    await call.answer()

# ========= Human date parser =========
MONTHS = {
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
    "января":1,"февраля":2,"марта":3,"апреля":4,"мая":5,"июня":6,
    "июля":7,"августа":8,"сентября":9,"октября":10,"ноября":11,"декабря":12,
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
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

# ========= DB helpers =========
async def init_db():
    """Легка ініціалізація додаткових таблиць."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            event_id INT NOT NULL,
            organizer_id BIGINT NOT NULL,
            seeker_id BIGINT NOT NULL,
            score INT CHECK (score BETWEEN 1 AND 10) NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- pending|done|skipped
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(event_id, seeker_id)
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
            RETURNING id, created_at
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
    """Безпечно оновлює одне поле з білого списку."""
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
    """Повертає події користувача з фільтром: active/finished/deleted."""
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

async def get_user_ratings(user_id: int) -> tuple[float, float]:
    """
    Повертає (organizer_rating, seeker_rating).
    Якщо оцінок ще немає або таблиці ratings немає — повертає 10.0 за замовчуванням.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Спробуємо зчитати середні оцінки з таблиці ratings (якщо є)
        avg_org = None
        avg_seek = None
        try:
            row_org = await conn.fetchrow(
                "SELECT AVG(score)::float AS avg FROM ratings WHERE organizer_id::text=$1 AND role='organizer'",
                str(user_id)
            )
            if row_org:
                avg_org = row_org["avg"]
        except Exception:
            avg_org = None  # таблиці може не бути — тихо ідемо далі

        try:
            row_seek = await conn.fetchrow(
                "SELECT AVG(score)::float AS avg FROM ratings WHERE seeker_id::text=$1 AND role='seeker'",
                str(user_id)
            )
            if row_seek:
                avg_seek = row_seek["avg"]
        except Exception:
            avg_seek = None

        # Якщо оцінок ще немає — за замовчуванням 10.0, але перевіримо активність
        has_org = False
        has_part = False
        try:
            row_ev = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM events WHERE user_id::text=$1", str(user_id))
            has_org = bool(row_ev and row_ev["cnt"] > 0)
        except Exception:
            pass
        try:
            row_part = await conn.fetchrow("""
                SELECT COUNT(*) AS cnt
                FROM requests r
                JOIN events e ON e.id = r.event_id
                WHERE r.seeker_id::text=$1 AND r.status='approved'
            """, str(user_id))
            has_part = bool(row_part and row_part["cnt"] > 0)
        except Exception:
            pass

        organizer_rating = avg_org if avg_org is not None else (10.0 if not has_org else 10.0)
        seeker_rating    = avg_seek if avg_seek is not None else (10.0 if not has_part else 10.0)

        return round(float(organizer_rating), 1), round(float(seeker_rating), 1)
    finally:
        await conn.close()


    # фільтри
    def is_active(st):   return st in ('active','collected')
    def is_finished(st): return st in ('finished',)
    def is_deleted(st):  return st in ('deleted','cancelled')
    if filter_kind == FILTER_ACTIVE:
        rows = [r for r in rows if is_active(r['status'])]
    elif filter_kind == FILTER_FINISHED:
        rows = [r for r in rows if is_finished(r['status'])]
    elif filter_kind == FILTER_DELETED:
        rows = [r for r in rows if is_deleted(r['status'])]

    # відсортовано: найближчі вгорі
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
            SELECT r.seeker_id,
                   u.name, u.city, u.interests, u.photo
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

# ========= Пошук (не показувати минулі дати) =========
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

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

# ========= Рейтинг організатора =========
async def get_organizer_avg_rating(organizer_id: int) -> float | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("SELECT AVG(score)::float AS avg FROM ratings WHERE organizer_id=$1 AND status='done' AND score IS NOT NULL", organizer_id)
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
        # organizer_id з events
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
    except Exception:
        logging.exception("rateskip error")
        await safe_alert(call, "Сталася помилка")

# ========= Debug / Start =========
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

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = datetime.now(timezone.utc)
    try:
        user = await get_user_from_db(uid)
    except Exception:
        st['step'] = 'menu'
        await message.answer("⚠️ Не вдалося з'єднатися з БД.", reply_markup=main_menu()); return
    if user:
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}! Оберіть дію:", reply_markup=main_menu())
    else:
        st['step'] = 'name'
        await message.answer("👋 Введіть ваше ім'я:", reply_markup=back_kb())

# ========= Photo handlers =========
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = datetime.now(timezone.utc)
    step = st.get('step')

    if step in ('photo', 'edit_photo'):
        st['photo'] = message.photo[-1].file_id
        if step == 'photo':
            st['step'] = 'interests'
            await message.answer("🎯 Інтереси (через кому):", reply_markup=back_kb())
        else:
            st['step'] = 'edit_interests'
            await message.answer("🎯 Оновіть інтереси або натисніть «⏭ Пропустити».", reply_markup=skip_back_kb())
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
        # повідомити учасників
        if ok:
            await notify_members_event_changed(ev_id, "Оновлено фото події.")
        st['step'] = 'menu'
        return

# ========= Back (reply keyboard) =========
@dp.message(F.text == BTN_BACK)
async def back_to_menu(message: types.Message):
    st = user_states.setdefault(message.from_user.id, {})
    st['step'] = 'menu'
    st['last_activity'] = datetime.now(timezone.utc)
    await message.answer("⬅️ Повертаємось у меню", reply_markup=main_menu())

# ========= Inline back-to-menu =========
@dp.callback_query(F.data == "back:menu")
async def cb_back_menu(call: types.CallbackQuery):
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['step'] = 'menu'
    st['last_activity'] = datetime.now(timezone.utc)
    await safe_alert(call, "Головне меню", show_alert=False)
    try:
        await call.message.delete()
    except Exception:
        pass
    await bot.send_message(uid, "Меню:", reply_markup=main_menu())

# ========= HELPERS: event review =========
def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%Y-%m-%d %H:%M') if isinstance(dt, datetime) else "—"
    loc_line = st.get('event_location') or (
        f"{st.get('event_lat'):.5f}, {st.get('event_lon'):.5f}"
        if (st.get('event_lat') is not None and st.get('event_lon') is not None) else "—"
    )
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{st.get('capacity','—')} • шукаємо ще: {st.get('needed_count','—')}"
    parts = [
        f"<b>Перевірте дані перед публікацією</b>",
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

# ========= Таймери/нагадування =========
def schedule_create_reminder(uid: int):
    st = user_states.setdefault(uid, {})
    st['create_started_at'] = datetime.now(timezone.utc)
    st['create_reminder_task'] = asyncio.create_task(_create_reminder_task(uid))

async def _create_reminder_task(uid: int):
    try:
        await asyncio.sleep(REMINDER_CREATE_MIN * 60)
        st = user_states.get(uid) or {}
        if st.get('step','').startswith('create_event') and st.get('create_started_at'):
            await bot.send_message(uid, "⏰ Ти не завершив створення івенту. Повертаємось і доробляємо?")
    except Exception as e:
        logging.warning("create reminder task err: %s", e)

def schedule_reset_to_menu(uid: int):
    st = user_states.setdefault(uid, {})
    # скасувати попередній ресет, якщо був
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

# ========= Головний FSM =========
@dp.message(F.text)
async def handle_steps(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    st['last_activity'] = datetime.now(timezone.utc)
    schedule_reset_to_menu(uid)

    # ===== Меню =====
if text == BTN_PROFILE and step in (None, 'menu'):
        user = await get_user_from_db(uid)
        if user:
            # отримаємо рейтинги
            org_rt, seek_rt = await get_user_ratings(uid)
            caption = (
                "👤 Профіль:\n"
                f"📛 {user.get('name') or '—'}\n"
                f"🏙 {user.get('city') or '—'}\n"
                f"🎯 {user.get('interests') or '—'}\n"
                f"⭐ Рейтинг організатора: {org_rt}/10\n"
                f"⭐ Рейтинг пошукача: {seek_rt}/10"
            )
            kb = types.ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text='✏️ Змінити профіль')],
                    [KeyboardButton(text=BTN_BACK)]
                ],
                resize_keyboard=True
            )
            if user.get('photo'):
                await message.answer_photo(user['photo'], caption=caption, reply_markup=kb)
            else:
                await message.answer(caption, reply_markup=kb)
        else:
            await message.answer("Профіль не знайдено. Натисніть /start для реєстрації.", reply_markup=main_menu())
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
        await message.answer("✍️ Нове ім'я або натисніть «⏭ Пропустити».", reply_markup=skip_back_kb()); return

    if text == BTN_CREATE:
        if st.get('step') == 'name': return
        user = await get_user_from_db(uid)
        if not user: await message.answer("⚠️ Спочатку зареєструйтесь через /start"); return
        st.clear(); st['step']='create_event_title'
        st['creator_name']=user.get('name',''); st['creator_phone']=user.get('phone','')
        await message.answer(
            "Як назвеш подію? ✍️\n<i>Наприклад: «Гра в покер» або «Ранкова пробіжка».</i>",
            reply_markup=back_kb(), parse_mode="HTML"
        )
        schedule_create_reminder(uid)
        schedule_reset_to_menu(uid)
        return

    if text == BTN_SEARCH and st.get('step') in (None, 'menu'):
        st['step'] = 'search_menu'
        await message.answer("Оберіть режим пошуку:", reply_markup=search_menu_kb()); return

    if text == BTN_MY_CHATS and st.get('step') in (None, 'menu'):
        rows = await list_active_conversations_for_user(uid)
        await message.answer("Ваші активні чати:", reply_markup=types.ReplyKeyboardRemove())
        await bot.send_message(uid, "Список:", reply_markup=chats_list_kb(rows))
        return

    if text == BTN_MY_EVENTS and st.get('step') in (None, 'menu'):
        st['step'] = 'my_events_filters'
        await message.answer("Оберіть категорію:", reply_markup=types.ReplyKeyboardRemove())
        await bot.send_message(uid, "Фільтри:", reply_markup=myevents_filter_kb())
        return

    # ===== Реєстрація =====
        # ===== Реєстрація =====
    if st.get('step') == 'name':
        st['name'] = text
        st['step'] = 'city'
        await message.answer("🏙 Місто:", reply_markup=back_kb())
        return

    if st.get('step') == 'city':
        st['city'] = text
        st['step'] = 'photo'
        await message.answer("🖼 Надішліть фото профілю:", reply_markup=back_kb())
        return

    if st.get('step') == 'interests':
        st['interests'] = ', '.join([i.strip() for i in text.split(',') if i.strip()])
        try:
            await save_user_to_db(
                uid,
                st.get('phone', ''),
                st.get('name', ''),
                st.get('city', ''),
                st.get('photo', ''),
                st['interests']
            )
            await message.answer('✅ Профіль збережено!', reply_markup=main_menu())

            # адмін-сповіщення про нового користувача (тільки у флоу первинної реєстрації)
            try:
                fn = message.from_user.full_name or ""
            except Exception:
                fn = ""

            try:
                await notify_admin(
                    "🆕 Новий користувач зареєстрований\n"
                    f"• ID: {uid}\n"
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
        await message.answer("🖼 Надішліть нове фото або «⏭ Пропустити».", reply_markup=skip_back_kb()); return
    if st.get('step') == 'edit_interests':
        if text != BTN_SKIP:
            st['interests'] = ', '.join([i.strip() for i in text.split(',') if i.strip()])
        try:
            await save_user_to_db(uid, st.get('phone',''), st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            await message.answer('✅ Профіль оновлено!', reply_markup=main_menu())
        except Exception as e:
            logging.error('update profile: %s', e); await message.answer('❌ Помилка оновлення профілю.', reply_markup=main_menu())
        st['step'] = 'menu'; return

    # ===== Створення події =====
    if st.get('step') == 'create_event_title':
        st['event_title'] = text; st['step'] = 'create_event_description'
        await message.answer("Опиши подію коротко 👇", reply_markup=back_kb()); return
    if st.get('step') == 'create_event_description':
        st['event_description'] = text; st['step'] = 'create_event_date'
        now = datetime.now()
        await message.answer("📅 Напишіть дату й час (10.10.2025 19:30) або оберіть в календарі:", reply_markup=back_kb())
        await message.answer("🗓 Оберіть день:", reply_markup=month_kb(now.year, now.month)); return
    if st.get('step') == 'create_event_date':
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer("Не впізнав дату. Приклад: 10.10.2025 19:30", reply_markup=back_kb()); return
        st['event_date'] = dt; st['step'] = 'create_event_location'
        await message.answer("📍 Локація (гео або текстом):", reply_markup=location_choice_kb()); return
    if st.get('step') == 'create_event_time':
        t = parse_time_hhmm(text)
        if not t: await message.answer("Формат часу HH:MM, напр. 19:30", reply_markup=back_kb()); return
        d: date = st.get('picked_date'); st['event_date'] = datetime(d.year, d.month, d.day, t[0], t[1])
        st['step'] = 'create_event_location'
        await message.answer("📍 Локація (гео або текстом):", reply_markup=location_choice_kb()); return
    if st.get('step') == 'create_event_location':
        if text == "📝 Ввести адресу текстом":
            st['step'] = 'create_event_location_name'
            await message.answer("Вкажи адресу/місце:", reply_markup=back_kb()); return
        if text == "⏭ Пропустити локацію":
            st['event_location'] = ''; st['event_lat'] = None; st['event_lon'] = None
            st['step'] = 'create_event_capacity'
            await message.answer("👥 Місткість (загалом, включно з тобою):", reply_markup=back_kb()); return
        await message.answer("Надішліть геолокацію або оберіть опцію нижче.", reply_markup=location_choice_kb()); return
    if st.get('step') == 'create_event_location_name':
        st['event_location'] = text; st['step'] = 'create_event_capacity'
        await message.answer("👥 Місткість (загалом):", reply_markup=back_kb()); return
    if st.get('step') == 'create_event_capacity':
        try:
            cap = int(text); assert cap > 0
        except Exception:
            await message.answer("❗ Введіть позитивне число.", reply_markup=back_kb()); return
        st['capacity'] = cap; st['step'] = 'create_event_needed'
        await message.answer("👤 Скільки ще шукаєш? (вільні місця):", reply_markup=back_kb()); return
    if st.get('step') == 'create_event_needed':
        try:
            need = int(text); cap = st['capacity']; assert 0 < need <= cap
        except Exception:
            await message.answer(f"❗ Від 1 до {st['capacity']}", reply_markup=back_kb()); return
        st['needed_count'] = need; st['step'] = 'create_event_photo'
        await message.answer("📸 Додайте фото події або «⏭ Пропустити».", reply_markup=skip_back_kb()); return

    if text == BTN_SKIP and st.get('step') == 'create_event_photo':
        st['event_photo'] = None
        st['step'] = 'create_event_review'
        await send_event_review(message.chat.id, st); return

    if text == '✅ Опублікувати' and step == 'create_event_review':
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

            await message.answer("🚀 Подію опубліковано!", reply_markup=main_menu())

            # ===== Адмін-сповіщення про новий івент =====
            # Без вкладених f-рядків і бекслешів усередині виразів.
            try:
                dt_str = st['event_date'].strftime('%Y-%m-%d %H:%M')
            except Exception:
                dt_str = '—'

            # Підготуємо локацію одним рядком
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

            try:
                organizer_name = st.get('creator_name') or (message.from_user.full_name if message.from_user else '') or str(uid)
            except Exception:
                organizer_name = str(uid)

            try:
                await notify_admin(
                    (
                        "🆕 Створено новий івент\n"
                        f"• ID: {row['id'] if row else '—'}\n"
                        f"• Організатор: {organizer_name}\n"
                        f"• Title: {st.get('event_title')}\n"
                        f"• Коли: {dt_str}\n"
                        f"• Де: {loc_line}\n"
                        f"• Місць: {st.get('capacity')} | Шукаємо ще: {st.get('needed_count')}"
                    )
                )
            except Exception as e:
                logging.warning("notify_admin (event) failed: %s", e)

        except Exception:
            logging.exception("publish")
            await message.answer("❌ Помилка публікації", reply_markup=main_menu())

        st['step'] = 'menu'
        return


    if text == '✏️ Редагувати' and st.get('step') == 'create_event_review':
        st['step'] = 'create_event_title'
        await message.answer("📝 Нова назва:", reply_markup=back_kb()); return

    if text == '❌ Скасувати' and st.get('step') == 'create_event_review':
        st['step'] = 'menu'; await message.answer("❌ Створення події скасовано.", reply_markup=main_menu()); return

    # ===== Пошук =====
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_KW:
        st['step'] = 'search_keyword_wait'
        await message.answer("Введіть ключове слово:", reply_markup=back_kb()); return
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_NEAR:
        st['step'] = 'search_geo_wait_location'
        await message.answer("Надішліть геолокацію або оберіть точку на карті.", reply_markup=location_choice_kb()); return
    if st.get('step') == 'search_menu' and text == BTN_SEARCH_MINE:
        rows = await find_events_by_user_interests(uid, limit=20)
        if not rows:
            await message.answer("Поки немає подій за вашими інтересами.", reply_markup=main_menu())
            st['step'] = 'menu'; return
        await send_event_cards(message.chat.id, rows); st['step'] = 'menu'; return
    if st.get('step') == 'search_keyword_wait':
        rows = await find_events_by_kw(text, limit=10)
        if not rows:
            await message.answer("Нічого не знайдено.", reply_markup=main_menu())
            st['step'] = 'menu'; return
        await send_event_cards(message.chat.id, rows); st['step'] = 'menu'; return
    if st.get('step') == 'search_geo_wait_radius':
        try: radius = float(text)
        except ValueError: radius = 5.0
        lat, lon = st.get('search_lat'), st.get('search_lon')
        if lat is None or lon is None:
            await message.answer("Не бачу геолокації. Спробуйте ще раз.", reply_markup=location_choice_kb())
            st['step'] = 'search_geo_wait_location'; return
        rows = await find_events_near(lat, lon, radius, limit=10)
        if not rows:
            await message.answer("Поруч подій не знайдено 😕", reply_markup=main_menu())
            st['step'] = 'menu'; return
        await send_event_cards(message.chat.id, rows); st['step'] = 'menu'; return

    # ===== Редагування івента (inline -> текстові кроки) =====
    if st.get('step') == 'edit_event_title':
        ev_id = st.get('edit_event_id')
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "title", text)
        await message.answer("📝 Назву оновлено." if ok else "❌ Не вдалося оновити назву.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено назву події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_descr':
        ev_id = st.get('edit_event_id')
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "description", text)
        await message.answer("📄 Опис оновлено." if ok else "❌ Не вдалося оновити опис.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено опис події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_datetime':
        ev_id = st.get('edit_event_id')
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer("Не впізнав дату. Приклад: 10.10.2025 19:30", reply_markup=back_kb()); return
        ok = await update_event_field(ev_id, uid, "date", dt)
        await message.answer("📅 Дату/час оновлено." if ok else "❌ Не вдалося оновити дату.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено дату/час події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_addr':
        ev_id = st.get('edit_event_id')
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        ok = await update_event_field(ev_id, uid, "location", text)
        await message.answer("📍 Адресу оновлено." if ok else "❌ Не вдалося оновити адресу.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено адресу події.")
        st['step']='menu'; return

    if st.get('step') == 'edit_event_capacity':
        ev_id = st.get('edit_event_id')
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
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
        if not ev_id: await message.answer("Не знайдено івент для редагування.", reply_markup=main_menu()); st['step']='menu'; return
        try:
            need = int(text); assert need >= 0
        except Exception:
            await message.answer("Введіть число ≥ 0.", reply_markup=back_kb()); return
        ok = await update_event_field(ev_id, uid, "needed_count", need)
        await message.answer("👤 К-ть вільних місць оновлено." if ok else "❌ Не вдалося оновити к-ть місць.", reply_markup=main_menu())
        if ok: await notify_members_event_changed(ev_id, "Оновлено кількість вільних місць.")
        st['step']='menu'; return

    # ===== Роутинг повідомлень у активний чат + логування =====
    active_conv_id = st.get('active_conv_id')
    if active_conv_id:
        conv = await get_conversation(active_conv_id)
        now = datetime.now(timezone.utc)
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

    rows = await list_active_conversations_for_user(uid)
    if rows:
        await message.answer("У вас є активні чати. Виберіть у меню «📨 Мої чати».", reply_markup=main_menu()); return

# ========= Geo (створення/пошук) =========
@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = datetime.now(timezone.utc)
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

# ========= JOIN / заявки =========
@dp.callback_query(F.data.startswith("join:"))
async def cb_join(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    seeker_id = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        existing = await conn.fetchrow("SELECT id, status FROM requests WHERE event_id=$1 AND seeker_id=$2", event_id, seeker_id)
        if existing:
            st = existing['status']
            msg = "Заявку вже відправлено, очікуйте відповіді ✅" if st=='pending' \
                else ("Заявку вже підтверджено. Перейдіть у «📨 Мої чати»" if st=='approved' else "На жаль, вашу заявку відхилено.")
            await safe_alert(call, msg, show_alert=False); await conn.close(); return

        req = await conn.fetchrow("INSERT INTO requests (event_id, seeker_id) VALUES ($1,$2) RETURNING id", event_id, seeker_id)
        ev  = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        seeker = await conn.fetchrow("SELECT name, city, interests, photo FROM users WHERE telegram_id::text=$1", str(seeker_id))
        await conn.close()

        await safe_alert(call, "Запит на приєднання надіслано ✅", show_alert=False)

        if ev:
            caption = (f"🔔 Запит на участь у події “{ev['title']}”.\n\n"
                       f"👤 Пошукач: {seeker['name'] if seeker else call.from_user.full_name}\n"
                       f"🎯 Інтереси: {(seeker['interests'] or '—') if seeker else '—'}\n"
                       f"🏙 Місто: {(seeker['city'] or '—') if seeker else '—'}\n\n"
                       f"Що робимо?")
            kb = request_actions_kb(req["id"])
            if seeker and seeker.get('photo'):
                try:
                    await bot.send_photo(ev["user_id"], seeker['photo'], caption=caption, reply_markup=kb)
                except Exception:
                    await bot.send_message(ev["user_id"], caption, reply_markup=kb)
            else:
                await bot.send_message(ev["user_id"], caption, reply_markup=kb)
    except Exception:
        logging.exception("join error")
        await safe_alert(call, "Помилка, спробуйте ще раз")

# ========= OPEN CHAT FROM REQUEST + reminder =========
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

@dp.callback_query(F.data.startswith("approve:"))
async def cb_approve(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        async with conn.transaction():
            req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1 FOR UPDATE", req_id)
            if not req: await safe_alert(call, "Заявку не знайдено."); return
            ev  = await conn.fetchrow("SELECT * FROM events WHERE id=$1 FOR UPDATE", req['event_id'])
            if not ev: await safe_alert(call, "Подію не знайдено."); return
            if call.from_user.id != ev['user_id']:
                await safe_alert(call, "Лише організатор може підтвердити."); return
            if req['status'] == 'approved':
                await safe_alert(call, "Вже підтверджено."); return
            if req['status'] == 'rejected':
                await safe_alert(call, "Вже відхилено."); return
            if ev['needed_count'] is not None and ev['needed_count'] <= 0:
                await safe_alert(call, "Немає вільних місць."); return

            conv = await conn.fetchrow("""
                SELECT * FROM conversations
                 WHERE event_id=$1 AND organizer_id=$2 AND seeker_id=$3
                   AND status='active' AND expires_at > now()
                 ORDER BY id DESC LIMIT 1
            """, ev['id'], ev['user_id'], req['seeker_id'])
            if not conv:
                expires = datetime.now(timezone.utc) + timedelta(minutes=30)
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
                 RETURNING needed_count, status, title, user_id, location, date
            """, ev['id'])
            new_needed = row['needed_count']
            ev_title   = row['title']

        await conn.close()

        await safe_alert(call, "✅ Підтверджено", show_alert=False)
        until = conv['expires_at'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        await bot.send_message(req['seeker_id'],
            f"✅ Вас прийнято до події “{ev_title}”.\n"
            f"💬 Чат активний до {until}. Виберіть його у меню «📨 Мої чати».")
        await bot.send_message(call.from_user.id,
            f"✅ Учасника підтверджено. Залишилось місць: {new_needed}.")

        if new_needed == 0:
            await notify_collected(ev['id'])

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

# ========= Чати: вибір / історія / закриття =========
@dp.callback_query(F.data.startswith("chat:open:"))
async def cb_chat_open(call: types.CallbackQuery):
    conv_id = int(call.data.split(":")[2])
    uid = call.from_user.id
    conv = await get_conversation(conv_id)
    if not conv or conv['status'] != 'active' or not (conv['organizer_id']==uid or conv['seeker_id']==uid):
        await safe_alert(call, "Чат недоступний."); return
    if conv['expires_at'] <= datetime.now(timezone.utc):
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
    # без нумерації чату
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

# ========= Події: інфо / заявки / учасники / редагування =========
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
        await safe_alert(call, "Немає очікуючих заявок"); return
    await call.answer()
    for r in rows:
        cap = (f"👤 {r['name'] or ('id ' + str(r['seeker_id']))}\n"
               f"🏙 {r['city'] or '—'}\n"
               f"🎯 {r['interests'] or '—'}\n"
               f"Що робимо?")
        kb = request_actions_kb(r['req_id'])
        if r.get('photo'):
            try:
                await bot.send_photo(call.from_user.id, r['photo'], caption=cap, reply_markup=kb); continue
            except Exception:
                pass
        await bot.send_message(call.from_user.id, cap, reply_markup=kb)

@dp.callback_query(F.data.startswith("event:members:"))
async def cb_event_members(call: types.CallbackQuery):
    """Показати підтверджених учасників: організатор або затверджений учасник."""
    event_id = int(call.data.split(":")[2])
    conn = await asyncpg.connect(DATABASE_URL)
    ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
    if not ev:
        await conn.close(); await safe_alert(call, "Подію не знайдено."); return
    # чи є користувач затвердженим учасником
    approved = await conn.fetchrow("SELECT 1 FROM requests WHERE event_id=$1 AND seeker_id=$2 AND status='approved' LIMIT 1",
                                   event_id, call.from_user.id)
    await conn.close()

    if ev['user_id'] != call.from_user.id and not approved:
        await safe_alert(call, "Перегляд учасників недоступний."); return

    rows = await list_approved_members(event_id)
    if not rows:
        await safe_alert(call, "Поки що підтверджених учасників немає."); return

    await call.answer()
    await bot.send_message(call.from_user.id, f"👥 Підтверджені учасники “{ev['title']}”:")
    for r in rows:
        cap = (f"👤 {r['name'] or ('id ' + str(r['seeker_id']))}\n"
               f"🏙 {r['city'] or '—'}\n"
               f"🎯 {r['interests'] or '—'}")
        # Організатор може відкрити чат
        kb = None
        if ev['user_id'] == call.from_user.id:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💬 Відкрити чат", callback_data=f"event:memberchat:{event_id}:{r['seeker_id']}")
            ]])
        if r.get('photo'):
            try:
                await bot.send_photo(call.from_user.id, r['photo'], caption=cap, reply_markup=kb)
                continue
            except Exception:
                pass
        await bot.send_message(call.from_user.id, cap, reply_markup=kb)

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

# ===== Редагування (inline entrypoints) =====
@dp.callback_query(F.data.startswith("event:edit:"))
async def cb_event_edit(call: types.CallbackQuery):
    parts = call.data.split(":")
    # event:edit:{id}  або event:edit:{field}:{id}
    if len(parts) == 3:
        ev_id = int(parts[2])
        await call.answer()
        await bot.send_message(call.from_user.id, "Що редагуємо?", reply_markup=event_edit_menu_kb(ev_id))
        return
    # field-варіанти:
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

# ========= Нотиф учасникам про зміни =========
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

# ========= Відправка карток подій (з рейтингом орг) =========
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
            f"👑 Організатор: {organizer_name} · подій: {org_count}",
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

# ========= Фонові задачі: автоперевід у “проведені” + розсилка оцінок =========
async def fini_and_rate_loop():
    """Кожні 2 хв: переносимо минулі active/collected у finished та шлемо оцінку учасникам."""
    while True:
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            # вибірка подій, що пройшли
            rows = await conn.fetch("""
                UPDATE events
                   SET status='finished'
                 WHERE date IS NOT NULL AND date < now()
                   AND status IN ('active','collected')
                 RETURNING id, user_id, title, date
            """)
            await conn.close()
            for ev in rows:
                # надіслати оцінку всім approved
                conn2 = await asyncpg.connect(DATABASE_URL)
                members = await conn2.fetch("SELECT seeker_id FROM requests WHERE event_id=$1 AND status='approved'", ev['id'])
                await conn2.close()
                if not members: continue
                for m in members:
                    try:
                        await bot.send_message(m['seeker_id'],
                            f"⭐ Оцініть подію “{ev['title']}” та організатора:",
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
    # запуск фону
    asyncio.create_task(fini_and_rate_loop())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())


















