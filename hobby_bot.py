import logging
import asyncio
import os
import asyncpg
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from datetime import datetime
from aiogram import types

# --- ІНІЦІАЛІЗАЦІЯ БОТА --- #
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states = {}

# --- ПІДКЛЮЧЕННЯ ДО БАЗИ --- #
DATABASE_URL = os.getenv("DB_URL")

print("DATABASE_URL =", DATABASE_URL)
async def connect_db():
    return await asyncpg.connect(DATABASE_URL)

async def save_user_to_db(user_id, phone, name, city, photo, interests, role="пошук"):
    conn = await connect_db()
    await conn.execute("""
        INSERT INTO users (telegram_id, phone, name, city, photo, interests)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (telegram_id) DO UPDATE SET phone = $2, name = $3, city = $4, photo = $5, interests = $6 
    """, user_id, phone, name, city, photo, interests)
    await conn.close()

async def get_user_from_db(user_id):
    conn = await connect_db()
    user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", user_id)
    await conn.close()
    return user

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
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO events (
                user_id,
                creator_name,
                creator_phone,
                title,
                description,
                date,
                location,
                capacity,
                needed_count,
                status
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            user_id,
            creator_name,
            creator_phone,
            title,
            description,
            date,
            location,
            capacity,
            needed_count,
            status
        )
    finally:
        await conn.close()


async def search_events_by_interests(user_interests):
    conn = await connect_db()
    conditions = []
    params = []

    for i, kw in enumerate(user_interests):
        kw = kw.strip().lower()
        conditions.append(f"(LOWER(title) LIKE ${2 * i + 1} OR LOWER(description) LIKE ${2 * i + 2})")
        params.extend([f"%{kw}%", f"%{kw}%"])

    query = f"SELECT * FROM events WHERE {' OR '.join(conditions)}"
    results = await conn.fetch(query, *params)
    await conn.close()
    return results


# --- КНОПКИ --- #
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="🔍 Знайти подію")],
        [types.KeyboardButton(text="👤 Мій профіль")],
    ], resize_keyboard=True
)

back_button = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
    resize_keyboard=True
)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    user_states.setdefault(user_id, {})
    user = await get_user_from_db(user_id)
    if user:
        await message.answer(
            f"👋 Вітаю, {user['name']}! Обери дію нижче:",
            reply_markup=main_menu
        )
        user_states[user_id]["step"] = "menu"
    else:
        await message.answer(
            "👋 Привіт, ти потрапив у Findsy! Тут з легкістю знайдеш заняття на вечір або однодумців до своєї компанії!\n\nШукай, створюй, запрошуй, взаємодій та спілкуйся! 💛",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="📞 Авторизуватись")]],
                resize_keyboard=True
            )
        )
        user_states[user_id]["step"] = "authorization"

@dp.message(F.text == "📞 Авторизуватись")
async def authorize_step(message: types.Message):
    user_id = str(message.from_user.id)
    user_states.setdefault(user_id, {})
    user_states[user_id]["step"] = "phone"
    await message.answer(
        "📲 Поділіться номером телефону:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="📱 Поділитися номером", request_contact=True)], [types.KeyboardButton(text="⬅️ Назад")]],
            resize_keyboard=True
        )
    )

@dp.message(F.contact)
async def get_phone(message: types.Message):
    user_id = str(message.from_user.id)
    user_states.setdefault(user_id, {})
    raw = message.contact.phone_number
    cleaned = ''.join(filter(str.isdigit, raw))
    if cleaned.startswith('0'):
        cleaned = '38' + cleaned  # якщо хтось ввів "096..."
    elif cleaned.startswith('+'):
        cleaned = cleaned.lstrip('+')  # прибрати "+" якщо є
    user_states[user_id]["phone"] = cleaned

    user_states[user_id]["step"] = "name"
    await message.answer("✍️ Введіть ваше ім'я:", reply_markup=back_button)

@dp.message(F.photo)
async def get_photo(message: types.Message):
    user_id = str(message.from_user.id)
    if user_states.get(user_id, {}).get("step") == "photo":
        file_id = message.photo[-1].file_id
        print("📸 Фото збережено:", file_id)  # 👈
        user_states[user_id]["photo"] = file_id
        user_states[user_id]["step"] = "interests"
        await message.answer("🎯 Вкажіть ваші інтереси через кому:", reply_markup=back_button)


@dp.message(F.text & ~F.text.in_(["⬅️ Назад"]))
async def handle_steps(message: types.Message):
    user_id = message.from_user.id       # сразу int
    text    = message.text.strip()
    step    = user_states.get(user_id, {}).get("step")
    # убедимся, что словарь есть
    user_states.setdefault(user_id, {})

    print(f"=== handle_steps called: step={step!r}, text={text!r}")

    # ════════════════════════════════════════════════════════════
    # ЛОВУШКА: всегда на «➕ Створити подію»
    # ════════════════════════════════════════════════════════════
    if text == "➕ Створити подію":
        user = await get_user_from_db(user_id)
        if not user:
            await message.answer("⚠️ Спочатку зареєструйтесь через /start")
            return

        # Сбрасываем предыдущее состояние и начинаем новый flow
        user_states[user_id].clear()
        user_states[user_id].update({
            "step":           "create_event_title",
            "creator_name":   user["name"],
            "creator_phone":  user["phone"]
        })
        await message.answer("📝 Введіть назву події:", reply_markup=back_button)
        return

    # ════════════════════════════════════════════════════════════
    # 1) РЕГИСТРАЦИЯ / ПРОФИЛЬ
    # ════════════════════════════════════════════════════════════
    if step == "name":
        user_states[user_id]["name"] = text
        user_states[user_id]["step"] = "city"
        await message.answer("🏙 Введіть ваше місто:", reply_markup=back_button)
        return

    elif step == "city":
        user_states[user_id]["city"] = text
        user_states[user_id]["step"] = "photo"
        await message.answer("🖼 Надішліть свою світлину:", reply_markup=back_button)
        return

    elif step == "photo":
        # здесь должен быть хендлер на фото, но если текстом:
        user_states[user_id]["photo"] = message.photo[-1].file_id  # или как вы храните
        user_states[user_id]["step"] = "interests"
        await message.answer("🎯 Введіть ваші інтереси (через кому):", reply_markup=back_button)
        return

    elif step == "interests":
        user_states[user_id]["interests"] = [i.strip() for i in text.split(",")]
        await save_user_to_db(
            user_id   = user_id,
            phone     = user_states[user_id].get("phone"),
            name      = user_states[user_id].get("name"),
            city      = user_states[user_id].get("city"),
            photo     = user_states[user_id].get("photo"),
            interests = ", ".join(user_states[user_id]["interests"])
        )
        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Ваш профіль створено! Оберіть дію нижче:", reply_markup=main_menu)
        return

    # ════════════════════════════════════════════════════════════
    # 2) ГЛАВНОЕ МЕНЮ
    # ════════════════════════════════════════════════════════════
    if step == "menu":
        if text == "👤 Мій профіль":
            user = await get_user_from_db(user_id)
            if user and user.get("photo"):
                await message.answer_photo(
                    photo=user["photo"],
                    caption=(
                        "👤 Ваш профіль:\n\n"
                        f"📛 Ім'я: {user['name']}\n"
                        f"🏙 Місто: {user['city']}\n"
                        f"🎯 Інтереси: {user['interests']}"
                    ),
                    reply_markup=types.ReplyKeyboardMarkup(
                        [[types.KeyboardButton("✏️ Змінити профіль")],
                         [types.KeyboardButton("⬅️ Назад")]],
                        resize_keyboard=True
                    )
                )
            else:
                await message.answer("❗ Фото профілю не знайдено.", reply_markup=main_menu)
            return

        elif text == "✏️ Змінити профіль":
            user = await get_user_from_db(user_id)
            user_states[user_id] = {"step": "name", "phone": user["phone"]}
            await message.answer("✍️ Введіть нове ім'я:", reply_markup=back_button)
            return

        # кнопка «➕ Створити подію» обрабатывается в глобальной ловушке выше

    # ════════════════════════════════════════════════════════════
    # 3) БЛОК СОЗДАНИЯ СОБЫТИЯ
    # ════════════════════════════════════════════════════════════
    if step == "create_event_title":
        user_states[user_id]["event_title"] = text
        user_states[user_id]["step"]       = "create_event_description"
        await message.answer("📝 Введіть опис події:", reply_markup=back_button)
        return

    elif step == "create_event_description":
        user_states[user_id]["event_description"] = text
        user_states[user_id]["step"]             = "create_event_date"
        await message.answer(
            "📅 Введіть дату та час у форматі `YYYY-MM-DD HH:MM`:\n"
            "Наприклад: `2025-05-28 18:00`",
            parse_mode="Markdown",
            reply_markup=back_button
        )
        return

    elif step == "create_event_date":
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            await message.answer(
                "❗ Неправильний формат дати! Введіть `YYYY-MM-DD HH:MM`.",
                parse_mode="Markdown",
                reply_markup=back_button
            )
            return

        user_states[user_id]["event_date"] = dt
        user_states[user_id]["step"]       = "create_event_location"
        await message.answer("📍 Вкажіть місце події:", reply_markup=back_button)
        return

    elif step == "create_event_location":
        user_states[user_id]["event_location"] = text
        user_states[user_id]["step"]           = "create_event_capacity"
        await message.answer("👥 Скільки людей всього буде на вашому івенті?", reply_markup=back_button)
        return

    elif step == "create_event_capacity":
        try:
            cap = int(text)
            if cap <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❗ Будь ласка, введіть позитивне число, наприклад `10`.", reply_markup=back_button)
            return

        user_states[user_id]["capacity"] = cap
        user_states[user_id]["step"]     = "create_event_needed"
        await message.answer("👤 Скільки людей ви шукаєте для приєднання?", reply_markup=back_button)
        return

    elif step == "create_event_needed":
        try:
            need = int(text)
            cap  = user_states[user_id]["capacity"]
            if need <= 0 or need > cap:
                raise ValueError
        except ValueError:
            await message.answer(
                f"❗ Введіть число від 1 до {user_states[user_id]['capacity']}.",
                reply_markup=back_button
            )
            return

        user_states[user_id]["needed_count"] = need

        # сохраняем draft в БД
        try:
            await save_event_to_db(
                user_id       = user_id,
                creator_name  = user_states[user_id]["creator_name"],
                creator_phone = user_states[user_id]["creator_phone"],
                title         = user_states[user_id]["event_title"],
                description   = user_states[user_id]["event_description"],
                date          = user_states[user_id]["event_date"],
                location      = user_states[user_id]["event_location"],
                capacity      = user_states[user_id]["capacity"],
                needed_count  = user_states[user_id]["needed_count"],
                status        = "draft"
            )
        except Exception as e:
            print("ERROR save_event:", e)
            await message.answer("❌ Не вдалося зберегти подію. Спробуйте пізніше.", reply_markup=main_menu)
            user_states[user_id]["step"] = "menu"
            return

        user_states[user_id]["step"] = "publish_confirm"
        await message.answer(
            "🔍 Перевірте вашу подію:\n\n"
            f"📛 {user_states[user_id]['event_title']}\n"
            f"✏️ {user_states[user_id]['event_description']}\n"
            f"📅 {user_states[user_id]['event_date'].strftime('%Y-%m-%d %H:%M')}\n"
            f"📍 {user_states[user_id]['event_location']}\n"
            f"👥 Місткість: {user_states[user_id]['capacity']}\n"
            f"👤 Шукаємо: {user_states[user_id]['needed_count']}\n\n"
            "✅ Опублікувати чи ❌ Скасувати?",
            reply_markup=types.ReplyKeyboardMarkup(
                [
                    [types.KeyboardButton("✅ Опублікувати")],
                    [types.KeyboardButton("❌ Скасувати")],
                    [types.KeyboardButton("⬅️ Назад")]
                ], resize_keyboard=True
            )
        )
        return

    # ════════════════════════════════════════════════════════════
    # 4) ПУБЛИКАЦИЯ / ОТМЕНА
    # ════════════════════════════════════════════════════════════
    elif step == "publish_confirm" and text == "✅ Опублікувати":
        await publish_event(user_id, user_states[user_id]["event_title"])
        user_states[user_id]["step"] = "menu"
        await message.answer("🚀 Подію опубліковано!", reply_markup=main_menu)
        return

    elif step == "publish_confirm" and text == "❌ Скасувати":
        await cancel_event(user_id, user_states[user_id]["event_title"])
        user_states[user_id]["step"] = "menu"
        await message.answer("❌ Подію скасовано.", reply_markup=main_menu)
        return

    # ════════════════════════════════════════════════════════════
    # ВСЕ ОСТАЛЬНОЕ (поиск, etc.) — сюда можно добавить другие ветки
    # ════════════════════════════════════════════════════════════
    print(f"Unhandled in handle_steps: step={step}, text={text}")




    # === ПОШУК ПОДІЙ ЗА ІНТЕРЕСАМИ ===
    if step == "find_event_menu":
        if message.text == "🔍 Події за інтересами":
            user = await get_user_from_db(user_id)
            if user and user.get('interests'):
                interests_list = [i.strip().lower() for i in user['interests'].split(',')]
                events = await search_events_by_interests(interests_list)
                if events:
                    response = "🔍 Знайдені події за вашими інтересами:\n\n"
                    for e in events:
                        response += (
                            f"📛 {e['title']}\n"
                            f"✏️ {e['description']}\n"
                            f"📅 {e['date']}\n"
                            f"📍 {e['location']}\n\n"
                        )
                    await message.answer(response)
                else:
                    await message.answer("Нажаль, подій за вашими інтересами не знайдено.")
            else:
                await message.answer("Ваш профіль не містить інтересів. Додайте їх для пошуку подій.")
        return

    # === ІНШЕ ===
    # додаткові стани або тексти можна обробити тут


    

@dp.message(F.photo)
async def get_photo(message: types.Message):
    user_id = str(message.from_user.id)
    if user_states.get(user_id, {}).get("step") == "photo":
        user_states[user_id]["photo"] = message.photo[-1].file_id
        user_states[user_id]["step"] = "interests"
        await message.answer("🎯 Вкажіть ваші інтереси через кому:", reply_markup=back_button)

@dp.message(F.text == "⬅️ Назад")
async def go_back(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")
    if step == "name":
        await authorize_step(message)
    elif step == "city":
        user_states[user_id]["step"] = "name"
        await message.answer("✍️ Введіть ваше ім'я:", reply_markup=back_button)
    elif step == "photo":
        user_states[user_id]["step"] = "city"
        await message.answer("🏙 Введіть ваше місто:", reply_markup=back_button)
    elif step == "interests":
        user_states[user_id]["step"] = "photo"
        await message.answer("🖼 Надішліть свою світлину:", reply_markup=back_button)
    else:
        await message.answer("⬅️ Повертаємось у головне меню.", reply_markup=main_menu)
        user_states[user_id]["step"] = "menu"

@dp.message()
async def debug_all_messages(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")
    print("💣 DEBUG_CATCH_ALL:")
    print("USER:", user_id)
    print("STEP:", step)
    print("TEXT:", message.text)

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())





   
