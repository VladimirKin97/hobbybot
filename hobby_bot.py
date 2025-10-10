import os
import logging
import asyncio
from datetime import datetime

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command

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

# Логируем, к какой базе мы подключаемся
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
        [types.KeyboardButton(text="🔍 Знайти подію за інтересами")]
    ],
    resize_keyboard=True
)
def get_back_button() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True
    )

# --- Database helpers ---
async def get_user_from_db(user_id: int) -> asyncpg.Record | None:
    """Повертає користувача за telegram_id"""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # через ::text універсально працює і для BIGINT, і для TEXT колонок
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
    """Сохраняет пользователя или обновляет его по telegram_id"""
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
    status: str
):
    """Створює подію (insert). Статус передаємо явно ('active' або 'draft')."""
    logging.info("→ save_event_to_db: user_id=%s title=%r status=%r",
                 user_id, title, status)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO events (
                user_id, creator_name, creator_phone, title,
                description, date, location, capacity, needed_count, status
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING id, created_at
            """,
            user_id, creator_name, creator_phone or '',
            title, description, date, location,
            capacity, needed_count, status
        )
        logging.info("← saved event id=%s created_at=%s", row["id"], row["created_at"])
        return row
    finally:
        await conn.close()

async def publish_event(user_id: int, title: str):
    """Обновляет статус события на 'active' (если заранее создали черновик)."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE events SET status='active' WHERE user_id::text = $1 AND title = $2",
            str(user_id), title
        )
    finally:
        await conn.close()

async def cancel_event(user_id: int, title: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE events SET status='cancelled' WHERE user_id::text = $1 AND title = $2",
            str(user_id), title
        )
    finally:
        await conn.close()

# --- Debug commands (зручно діагностувати прямо в Telegram) ---
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
            status="active"
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
            "👋 Вітаю! Давай створимо профіль. Введіть ваше ім'я:",
            reply_markup=get_back_button()
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
        "🎯 Введіть ваші інтереси (через кому):",
        reply_markup=get_back_button()
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

    # === ТРИГЕРИ ГОЛОВНОГО МЕНЮ ===
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
        await message.answer("📝 Введіть назву події:", reply_markup=get_back_button())
        return

    if text == "🔍 Знайти подію за інтересами" and step in (None, 'menu'):
        state['step'] = 'search_keyword_wait'
        await message.answer("🔎 Введіть ключове слово для пошуку:", reply_markup=get_back_button())
        return

    # === РЕЄСТРАЦІЯ ===
    if step == 'name':
        state['name'] = text
        state['step'] = 'city'
        await message.answer("🏙 Введіть ваше місто:", reply_markup=get_back_button())
        return

    if step == 'city':
        state['city'] = text
        state['step'] = 'photo'
        await message.answer("🖼 Надішліть свою світлину:", reply_markup=get_back_button())
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
        logging.debug('Profile button pressed')
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
        logging.debug('Edit profile triggered')
        user = await get_user_from_db(user_id)
        state.clear()
        state.update({'step': 'name', 'phone': user.get('phone','') if user else ''})
        await message.answer("✍️ Введіть нове ім'я:", reply_markup=get_back_button())
        return

    # === СТВОРЕННЯ ПОДІЇ ===
    if step == 'create_event_title':
        state['event_title'] = text
        state['step'] = 'create_event_description'
        await message.answer('📝 Введіть опис події:', reply_markup=get_back_button())
        return

    if step == 'create_event_description':
        state['event_description'] = text
        state['step'] = 'create_event_date'
        await message.answer('📅 Введіть дату та час YYYY-MM-DD HH:MM', reply_markup=get_back_button())
        return

    if step == 'create_event_date':
        try:
            dt = datetime.strptime(text, '%Y-%m-%d %H:%M')
        except ValueError:
            await message.answer('❗ Невірний формат дати!', reply_markup=get_back_button())
            return
        state['event_date'] = dt
        state['step'] = 'create_event_location'
        await message.answer('📍 Вкажіть місце події:', reply_markup=get_back_button())
        return

    if step == 'create_event_location':
        state['event_location'] = text
        state['step'] = 'create_event_capacity'
        await message.answer('👥 Скільки всього місць?', reply_markup=get_back_button())
        return

    if step == 'create_event_capacity':
        try:
            cap = int(text)
            if cap <= 0:
                raise ValueError
        except ValueError:
            await message.answer('❗ Введіть позитивне число.', reply_markup=get_back_button())
            return
        state['capacity'] = cap
        state['step'] = 'create_event_needed'
        await message.answer('👤 Скільки учасників шукаєте?', reply_markup=get_back_button())
        return

    if step == 'create_event_needed':
        logging.debug('Entering create_event_needed with state %s', state)
        try:
            need = int(text)
            cap = state['capacity']
            if need <= 0 or need > cap:
                raise ValueError
        except ValueError:
            await message.answer(f"❗ Від 1 до {state['capacity']}", reply_markup=get_back_button())
            return
        state['needed_count'] = need
        # preview event
        await message.answer(
            "🔍 Перевірте вашу подію:\n\n"
            f"📛 {state['event_title']}\n"
            f"✏️ {state['event_description']}\n"
            f"📅 {state['event_date'].strftime('%Y-%m-%d %H:%M')}\n"
            f"📍 {state['event_location']}\n"
            f"👥 Місткість: {state['capacity']}\n"
            f"👤 Шукаємо: {state['needed_count']}\n\n"
            "✅ Опублікувати | ✏️ Редагувати | ❌ Скасувати",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[
                    [types.KeyboardButton(text='✅ Опублікувати'), types.KeyboardButton(text='✏️ Редагувати')],
                    [types.KeyboardButton(text='❌ Скасувати')],
                    [types.KeyboardButton(text='⬅️ Назад')]
                ], resize_keyboard=True
            )
        )
        state['step'] = 'publish_confirm'
        return

    if step == 'publish_confirm':
        logging.debug("PUBLISH_CONFIRM: state=%s, text=%r", state, text)

        if text == '✅ Опублікувати':
            try:
                # ПРЯМА вставка події зі статусом 'active'
                await save_event_to_db(
                    user_id=user_id,
                    creator_name=state.get('creator_name', ''),
                    creator_phone=state.get('creator_phone', '') or '',
                    title=state['event_title'],
                    description=state['event_description'],
                    date=state['event_date'],
                    location=state['event_location'],
                    capacity=state['capacity'],
                    needed_count=state['needed_count'],
                    status='active'
                )
                logging.info("Event published (inserted): %s by user %s", state['event_title'], user_id)
                await message.answer(
                    "🚀 Ваша подія опублікована та доступна пошукачам!",
                    reply_markup=main_menu
                )
            except Exception as e:
                logging.error("Publish failed: %s", e)
                await message.answer(
                    f"❌ Помилка при публікації події: {e}",
                    reply_markup=main_menu
                )
            state['step'] = 'menu'
            return

        elif text == '✏️ Редагувати':
            state['step'] = 'create_event_title'
            await message.answer(
                "📝 Введіть нову назву події:",
                reply_markup=get_back_button()
            )
            return

        elif text == '❌ Скасувати':
            # Якщо був чернетковий запис — можна оновити його статусом cancelled.
            try:
                await cancel_event(user_id, state.get('event_title', ''))
            except Exception as e:
                logging.error("Cancel failed: %s", e)
            await message.answer(
                "❌ Ви скасували створення події.",
                reply_markup=main_menu
            )
            state['step'] = 'menu'
            return

    # === ПОШУК ПОДІЙ (простий варіант за ключовим словом) ===
    if step == 'search_keyword_wait':
        kw = text
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            rows = await conn.fetch(
                """
                SELECT id, title, description, date, location, capacity, needed_count, status
                FROM events
                WHERE status = 'active'
                  AND (title ILIKE $1 OR description ILIKE $1)
                ORDER BY date ASC NULLS LAST, id DESC
                LIMIT 5
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

        out = ["🔎 Знайдені події:"]
        for r in rows:
            dt = r["date"].strftime('%Y-%m-%d %H:%M') if r["date"] else "—"
            out.append(
                f"\n• <b>{r['title']}</b> (#{r['id']})\n"
                f"  📅 {dt} | 📍 {r['location']}\n"
                f"  👥 {r['needed_count']}/{r['capacity']} шукаємо\n"
                f"  🟢 {r['status']}\n"
                f"  ✏️ {r['description'][:120]}{'…' if r['description'] and len(r['description'])>120 else ''}"
            )
        await message.answer("\n".join(out), parse_mode="HTML", reply_markup=main_menu)
        state['step'] = 'menu'
        return

    # === ЗАГЛУШКА ===
    logging.info('Unhandled step=%s text=%s', step, text)

# Entrypoint
async def main():
    logging.info('Starting polling')
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())







   


