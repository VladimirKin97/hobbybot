import os
import logging
import asyncio
from datetime import datetime

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- Initialization ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
if not BOT_TOKEN or not DATABASE_URL:
    logging.error(
        f"Missing env vars: BOT_TOKEN={'set' if BOT_TOKEN else 'unset'}, DATABASE_URL={'set' if DATABASE_URL else 'unset'}"
    )
    raise RuntimeError("Environment variables BOT_TOKEN and DATABASE_URL must be set")

logging.info("Using DATABASE_URL = %s", DATABASE_URL)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# In-memory user state
user_states: dict[int, dict] = {}

# --- Keyboards ---
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="👤 Мій профіль")],
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="🔍 Знайти подію")]
    ],
    resize_keyboard=True
)

def get_back_button() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True
    )

def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати геолокацію", request_location=True)],
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
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )

def event_join_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")]
        ]
    )

# --- Database helpers ---
async def get_user_from_db(user_id: int) -> asyncpg.Record | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id::text = $1",
            str(user_id)
        )
    finally:
        await conn.close()

async def save_user_to_db(
    user_id: int,
    phone: str,
    name: str,
    city: str,
    photo: str,
    interests: str
):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, phone, name, city, photo, interests)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (telegram_id) DO UPDATE SET
              phone     = EXCLUDED.phone,
              name      = EXCLUDED.name,
              city      = EXCLUDED.city,
              photo     = EXCLUDED.photo,
              interests = EXCLUDED.interests
            """,
            user_id, phone, name, city, photo, interests
        )
    finally:
        await conn.close()

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
    location_lat: float | None = None,
    location_lon: float | None = None
):
    """Створює подію з координатами. Повертає id і created_at."""
    logging.info("→ save_event_to_db: user_id=%s title=%r status=%r", user_id, title, status)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO events (
                user_id, creator_name, creator_phone, title,
                description, date, location, capacity, needed_count, status,
                location_lat, location_lon
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING id, created_at
            """,
            user_id, creator_name or '', creator_phone or '',
            title, description, date, location,
            capacity, needed_count, status,
            location_lat, location_lon
        )
        logging.info("← saved event id=%s created_at=%s", row["id"], row["created_at"])
        return row
    finally:
        await conn.close()

async def find_events_near(lat: float, lon: float, radius_km: float, limit: int = 10):
    """Пошук активних подій за радіусом (Haversine)."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            WITH params AS (SELECT $1::float AS lat, $2::float AS lon, $3::float AS r)
            SELECT e.*,
                   (6371 * acos(
                       cos(radians(p.lat)) * cos(radians(e.location_lat)) *
                       cos(radians(e.location_lon) - radians(p.lon)) +
                       sin(radians(p.lat)) * sin(radians(e.location_lat))
                   )) AS dist_km
            FROM events e, params p
            WHERE e.status='active'
              AND e.location_lat IS NOT NULL
              AND e.location_lon IS NOT NULL
              AND (6371 * acos(
                       cos(radians(p.lat)) * cos(radians(e.location_lat)) *
                       cos(radians(e.location_lon) - radians(p.lon)) +
                       sin(radians(p.lat)) * sin(radians(e.location_lat))
                  )) <= p.r
            ORDER BY dist_km ASC
            LIMIT $4
            """,
            lat, lon, radius_km, limit
        )
        return rows
    finally:
        await conn.close()

# --- Debug commands ---
@dp.message(Command("dbinfo"))
async def cmd_dbinfo(message: types.Message):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow("""
            SELECT current_database() AS db,
                   current_user AS usr,
                   current_schema() AS sch,
                   current_setting('search_path') AS search_path,
                   current_setting('server_version') AS ver,
                   current_setting('TimeZone', true) AS tz;
        """)
        await conn.close()
        await message.answer(
            f"🗄 DB={row['db']}\n👤 user={row['usr']}\n📚 schema={row['sch']}\n"
            f"🔎 search_path={row['search_path']}\n🐘 pg={row['ver']}\n🌍 tz={row['tz']}"
        )
    except Exception as e:
        await message.answer(f"❌ DB error: {e}")

@dp.message(Command("test_event"))
async def cmd_test_event(message: types.Message):
    try:
        r = await save_event_to_db(
            user_id=message.from_user.id,
            creator_name=message.from_user.full_name or "",
            creator_phone="",
            title="BOT TEST",
            description="insert from /test_event",
            date=datetime.utcnow(),
            location="N/A",
            capacity=1,
            needed_count=1,
            status="active",
            location_lat=50.45,
            location_lon=30.523
        )
        await message.answer(f"✅ events.id={r['id']} created_at={r['created_at']}")
    except Exception as e:
        await message.answer(f"❌ insert error: {e}")

# --- Handlers ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    state = user_states.setdefault(user_id, {})
    try:
        user = await get_user_from_db(user_id)
    except Exception as e:
        logging.error("DB connection error: %s", e)
        state['step'] = 'menu'
        await message.answer(
            "⚠️ Не вдалося з'єднатися з БД, робота обмежена.",
            reply_markup=main_menu
        )
        return
    if user:
        state['step'] = 'menu'
        await message.answer(
            f"👋 Ласкаво просимо назад, {user['name']}! Оберіть дію:",
            reply_markup=main_menu
        )
    else:
        state.clear()
        state.update({'step': 'name', 'phone': None})
        await message.answer(
            "👋 Вітаю! Давай створимо профіль. Введіть ваше ім'я:\n"
            "<i>Ім’я буде видно в заявках на участь.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
    return

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    state = user_states.setdefault(user_id, {})
    if state.get('step') != 'photo':
        return
    state['photo'] = message.photo[-1].file_id
    state['step'] = 'interests'
    await message.answer(
        "🎯 Введіть ваші інтереси (через кому):\n"
        "<i>На основі інтересів ми підбиратимемо події для вас.</i>",
        reply_markup=get_back_button(),
        parse_mode="HTML"
    )

@dp.message(F.text == "⬅️ Назад")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = {'step': 'menu'}
    await message.answer("⬅️ Повертаємось у меню", reply_markup=main_menu)

@dp.message(F.text)
async def handle_steps(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.setdefault(user_id, {})
    step = state.get('step')
    logging.debug("handle_steps: step=%s, text=%s", step, text)

    # === МЕНЮ ===
    if text == "➕ Створити подію":
        if step == 'name':
            return
        user = await get_user_from_db(user_id)
        if not user:
            await message.answer("⚠️ Спочатку зареєструйтесь через /start")
            return
        state.clear()
        state.update({
            'step': 'create_event_title',
            'creator_name': user.get('name') if user else '',
            'creator_phone': user.get('phone') if user else ''
        })
        await message.answer(
            "📝 Введіть назву події:\n"
            "<i>Пошукачі будуть шукати вашу подію за ключовими словами, "
            "тому переконайтеся, що назва без помилок і точно відображає суть.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if text == "🔍 Знайти подію" and step in (None, 'menu'):
        state['step'] = 'search_menu'
        await message.answer("Оберіть режим пошуку:", reply_markup=search_menu_kb())
        return

    # === РЕЄСТРАЦІЯ ===
    if step == 'name':
        state['name'] = text
        state['step'] = 'city'
        await message.answer(
            "🏙 Введіть ваше місто:\n"
            "<i>Місто допоможе знаходити релевантні події.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'city':
        state['city'] = text
        state['step'] = 'photo'
        await message.answer(
            "🖼 Надішліть свою світлину:\n"
            "<i>Фото зробить ваш профіль більш привабливим для організаторів.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'interests':
        state['interests'] = [i.strip() for i in text.split(',')]
        try:
            await save_user_to_db(
                user_id=user_id,
                phone=state.get('phone',''),
                name=state.get('name',''),
                city=state.get('city',''),
                photo=state.get('photo',''),
                interests=', '.join(state['interests'])
            )
            await message.answer('✅ Профіль збережено!', reply_markup=main_menu)
        except Exception as e:
            logging.error('Error saving profile: %s', e)
            await message.answer('❌ Не вдалося зберегти профіль.', reply_markup=main_menu)
        state['step'] = 'menu'
        return

    # === ПРОФІЛЬ ===
    if step == 'menu' and text == '👤 Мій профіль':
        user = await get_user_from_db(user_id)
        if user and user.get('photo'):
            await message.answer_photo(
                photo=user['photo'],
                caption=(
                    f"👤 Ваш профіль:\n📛 Ім'я: {user['name']}\n"
                    f"🏙 Місто: {user['city']}\n🎯 Інтереси: {user['interests']}"
                ),
                reply_markup=types.ReplyKeyboardMarkup(
                    keyboard=[
                        [types.KeyboardButton(text='✏️ Змінити профіль'), types.KeyboardButton(text='⬅️ Назад')]
                    ],
                    resize_keyboard=True
                )
            )
        else:
            await message.answer('❗ Профіль не знайдено.', reply_markup=main_menu)
        return

    if step == 'menu' and text == '✏️ Змінити профіль':
        user = await get_user_from_db(user_id)
        state.clear()
        state.update({'step': 'name', 'phone': user.get('phone','') if user else ''})
        await message.answer(
            "✍️ Введіть нове ім'я:\n<i>Це ім’я бачитимуть організатори.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    # === СТВОРЕННЯ ПОДІЇ ===
    if step == 'create_event_title':
        state['event_title'] = text
        state['step'] = 'create_event_description'
        await message.answer(
            '📝 Введіть опис події:\n'
            '<i>Опишіть у кількох реченнях, що буде відбуватися, щоб пошукачі охоче приєднувалися.</i>',
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'create_event_description':
        state['event_description'] = text
        state['step'] = 'create_event_date'
        await message.answer(
            '📅 Введіть дату та час у форматі YYYY-MM-DD HH:MM\n'
            '<i>Наприклад: 2025-10-12 19:30. Використовуйте місцевий час.</i>',
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'create_event_date':
        try:
            dt = datetime.strptime(text, '%Y-%m-%d %H:%M')
        except ValueError:
            await message.answer('❗ Невірний формат дати!\n<i>Приклад: 2025-10-12 19:30</i>',
                                 reply_markup=get_back_button(), parse_mode="HTML")
            return
        state['event_date'] = dt
        state['step'] = 'create_event_location'
        await message.answer(
            '📍 Надішліть точку локації кнопкою нижче або виберіть місце на мапі у вкладенні.\n'
            '<i>Ви можете надіслати свою поточну геолокацію або обрати точку на карті вручну.</i>',
            reply_markup=location_request_kb(),
            parse_mode="HTML"
        )
        return

    # Якщо на кроці локації користувач надсилає текст — просимо саме гео
    if step == 'create_event_location':
        await message.answer(
            'Будь ласка, надішліть геолокацію кнопкою нижче ⤵️\n'
            '<i>У вкладенні Telegram можна обрати будь-яку точку на мапі.</i>',
            reply_markup=location_request_kb(),
            parse_mode="HTML"
        )
        return

    if step == 'create_event_location_name':
        state['event_location'] = text  # людиночитна адреса/місце
        state['step'] = 'create_event_capacity'
        await message.answer(
            '👥 Скільки всього місць?\n'
            '<i>Вкажіть максимальну місткість події.</i>',
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'create_event_capacity':
        try:
            cap = int(text)
            if cap <= 0:
                raise ValueError
        except ValueError:
            await message.answer('❗ Введіть позитивне число.',
                                 reply_markup=get_back_button())
            return
        state['capacity'] = cap
        state['step'] = 'create_event_needed'
        await message.answer(
            '👤 Скільки учасників шукаєте?\n'
            '<i>Скільки людей вам бракує до повної місткості.</i>',
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'create_event_needed':
        logging.debug('Entering create_event_needed with state %s', state)
        try:
            need = int(text)
            cap = state['capacity']
            if need <= 0 or need > cap:
                raise ValueError
        except ValueError:
            await message.answer(f"❗ Від 1 до {state['capacity']}",
                                 reply_markup=get_back_button())
            return
        state['needed_count'] = need
        # preview event
        await message.answer(
            "🔍 Перевірте вашу подію:\n\n"
            f"📛 {state['event_title']}\n"
            f"✏️ {state['event_description']}\n"
            f"📅 {state['event_date'].strftime('%Y-%m-%d %H:%M')}\n"
            f"📍 {state.get('event_location','—')} "
            f"({state.get('event_lat','?')}, {state.get('event_lon','?')})\n"
            f"👥 Місткість: {state['capacity']}\n"
            f"👤 Шукаємо: {state['needed_count']}\n\n"
            "<i>Якщо все правильно — публікуйте. Можна повернутись і відредагувати.</i>",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[
                    [types.KeyboardButton(text='✅ Опублікувати'), types.KeyboardButton(text='✏️ Редагувати')],
                    [types.KeyboardButton(text='❌ Скасувати')],
                    [types.KeyboardButton(text='⬅️ Назад')]
                ], resize_keyboard=True
            ),
            parse_mode="HTML"
        )
        state['step'] = 'publish_confirm'
        return

    if step == 'publish_confirm':
        logging.debug("PUBLISH_CONFIRM: state=%s, text=%r", state, text)

        if text == '✅ Опублікувати':
            try:
                await save_event_to_db(
                    user_id=user_id,
                    creator_name=state.get('creator_name', ''),
                    creator_phone=state.get('creator_phone', '') or '',
                    title=state['event_title'],
                    description=state['event_description'],
                    date=state['event_date'],
                    location=state.get('event_location', ''),
                    capacity=state['capacity'],
                    needed_count=state['needed_count'],
                    status='active',
                    location_lat=state.get('event_lat'),
                    location_lon=state.get('event_lon')
                )
                logging.info("Event published (inserted): %s by user %s", state['event_title'], user_id)
                await message.answer("🚀 Ваша подія опублікована та доступна пошукачам!", reply_markup=main_menu)
            except Exception as e:
                logging.error("Publish failed: %s", e)
                await message.answer(f"❌ Помилка при публікації події: {e}", reply_markup=main_menu)
            state['step'] = 'menu'
            return

        elif text == '✏️ Редагувати':
            state['step'] = 'create_event_title'
            await message.answer(
                "📝 Введіть нову назву події:\n"
                "<i>Назва має чітко відображати суть івента.</i>",
                reply_markup=get_back_button(),
                parse_mode="HTML"
            )
            return

        elif text == '❌ Скасувати':
            await message.answer("❌ Ви скасували створення події.", reply_markup=main_menu)
            state['step'] = 'menu'
            return

    # === ПОШУК ===
    if step == 'search_menu' and text == "🔎 За ключовим словом":
        state['step'] = 'search_keyword_wait'
        await message.answer(
            "Введіть ключове слово:\n"
            "<i>Шукаємо в назві та описі активних подій.</i>",
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if step == 'search_menu' and text == "📍 Поруч зі мною":
        state['step'] = 'search_geo_wait_location'
        await message.answer(
            "Надішліть вашу геолокацію:\n"
            "<i>Можна надіслати поточну або вибрати точку на мапі у вкладенні.</i>",
            reply_markup=location_request_kb(),
            parse_mode="HTML"
        )
        return

    if step == 'search_keyword_wait':
        kw = text
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            rows = await conn.fetch(
                """
                SELECT id, title, description, date, location, capacity, needed_count, status,
                       location_lat, location_lon
                FROM events
                WHERE status = 'active'
                  AND (title ILIKE $1 OR description ILIKE $1)
                ORDER BY date ASC NULLS LAST, id DESC
                LIMIT 10
                """,
                f"%{kw}%"
            )
            await conn.close()
        except Exception as e:
            logging.error("Search error: %s", e)
            await message.answer("❌ Помилка пошуку.", reply_markup=main_menu)
            state['step'] = 'menu'
            return

        if not rows:
            await message.answer("😕 Нічого не знайдено. Спробуйте інше слово.", reply_markup=main_menu)
            state['step'] = 'menu'
            return

        for r in rows:
            dt = r["date"].strftime('%Y-%m-%d %H:%M') if r["date"] else "—"
            loc_line = r["location"] or (
                f"{r['location_lat']:.5f}, {r['location_lon']:.5f}"
                if r["location_lat"] is not None else "—"
            )
            text_card = (
                f"<b>{r['title']}</b> (#{r['id']})\n"
                f"📅 {dt}\n📍 {loc_line}\n"
                f"👤 Шукаємо: {r['needed_count']}/{r['capacity']}\n\n"
                f"{(r['description'] or '')[:300]}{'…' if r['description'] and len(r['description'])>300 else ''}"
            )
            await message.answer(text_card, parse_mode="HTML", reply_markup=event_join_kb(r["id"]))
        state['step'] = 'menu'
        await message.answer("Готово ✅", reply_markup=main_menu)
        return

    if step == 'search_geo_wait_radius':
        try:
            radius = float(text)
        except ValueError:
            radius = 5.0  # дефолт

        lat = state.get('search_lat')
        lon = state.get('search_lon')
        if lat is None or lon is None:
            await message.answer("Не бачу геолокації. Спробуйте ще раз.", reply_markup=location_request_kb())
            state['step'] = 'search_geo_wait_location'
            return

        rows = await find_events_near(lat, lon, radius, limit=10)
        if not rows:
            await message.answer("Поруч подій не знайдено 😕", reply_markup=main_menu)
            state['step'] = 'menu'
            return

        for r in rows:
            dt = r["date"].strftime('%Y-%m-%d %H:%M') if r["date"] else "—"
            loc_line = r["location"] or f"{r['location_lat']:.5f}, {r['location_lon']:.5f}"
            dist = f"{r['dist_km']:.1f} км"
            text_card = (
                f"<b>{r['title']}</b> (#{r['id']}) — {dist}\n"
                f"📅 {dt}\n📍 {loc_line}\n"
                f"👤 Шукаємо: {r['needed_count']}/{r['capacity']}\n\n"
                f"{(r['description'] or '')[:300]}{'…' if r['description'] and len(r['description'])>300 else ''}"
            )
            await message.answer(text_card, parse_mode="HTML", reply_markup=event_join_kb(r["id"]))
        state['step'] = 'menu'
        await message.answer("Готово ✅", reply_markup=main_menu)
        return

    if step == 'search_menu' and text == '⬅️ Назад':
        state['step'] = 'menu'
        await message.answer("Меню:", reply_markup=main_menu)
        return

    # === ЗАГЛУШКА ===
    logging.info('Unhandled step=%s text=%s', step, text)

# --- Геолокації (створення та пошук) ---
@dp.message(F.location)
async def handle_location(message: types.Message):
    user_id = message.from_user.id
    state = user_states.setdefault(user_id, {})
    cur = state.get('step')

    if cur == 'create_event_location':
        state['event_lat'] = message.location.latitude
        state['event_lon'] = message.location.longitude
        state['step'] = 'create_event_location_name'
        await message.answer(
            '🏷 Напишіть назву місця/адресу текстом:\n'
            '<i>Це допоможе пошукачам зорієнтуватися.</i>',
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return

    if cur == 'search_geo_wait_location':
        state['search_lat'] = message.location.latitude
        state['search_lon'] = message.location.longitude
        state['step'] = 'search_geo_wait_radius'
        await message.answer(
            '📏 Радіус у км? (за замовчуванням 5)\n'
            '<i>Надішліть число або виберіть кнопку.</i>',
            reply_markup=radius_kb(),
            parse_mode="HTML"
        )
        return

# --- Callback: join request ---
@dp.callback_query(F.data.startswith("join:"))
async def cb_join(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    seeker_id = call.from_user.id
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        req = await conn.fetchrow("""
            INSERT INTO requests (event_id, seeker_id)
            VALUES ($1,$2)
            ON CONFLICT (event_id, seeker_id)
            DO UPDATE SET status='pending'
            RETURNING id
        """, event_id, seeker_id)

        ev = await conn.fetchrow("SELECT id, title, user_id FROM events WHERE id=$1", event_id)
        await conn.close()

        await call.answer("Запит на приєднання надіслано ✅", show_alert=False)

        if ev:
            try:
                uname = f"@{call.from_user.username}" if call.from_user.username else call.from_user.full_name
                await bot.send_message(
                    ev["user_id"],
                    f"🔔 Запит на участь у події “{ev['title']}” (#{ev['id']}).\n"
                    f"Від: {uname} (id {seeker_id})."
                )
            except Exception as e:
                logging.warning("Organizer notification failed: %s", e)

    except Exception as e:
        logging.error("join request error: %s", e)
        await call.answer(f"Помилка: {e}", show_alert=True)

# Entrypoint
async def main():
    logging.info('Starting polling')
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())







   



