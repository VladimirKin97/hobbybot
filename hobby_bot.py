import logging
import asyncio
import os
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

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

async def save_event_to_db(user_id, name, phone, title, description, date, location):
    conn = await connect_db()
    await conn.execute("""
        INSERT INTO events (creator_id, creator_name, creator_phone, title, description, date, location, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'draft')
    """, user_id, name, phone, title, description, date, location)
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
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "name":
        user_states[user_id]["name"] = message.text
        user_states[user_id]["step"] = "city"
        await message.answer("🏙 Введіть ваше місто:", reply_markup=back_button)

    elif step == "city":
        user_states[user_id]["city"] = message.text
        user_states[user_id]["step"] = "photo"
        await message.answer("🖼 Надішліть свою світлину:", reply_markup=back_button)

    elif step == "interests":
        user_states[user_id]["interests"] = message.text.split(",")

        print("DEBUG збереження юзера:", user_states[user_id])  
        
        await save_user_to_db(
            user_id=user_id,
            phone=user_states[user_id].get("phone"),
            name=user_states[user_id].get("name"),
            city=user_states[user_id].get("city"),
            photo=user_states[user_id].get("photo"),
            interests=", ".join(user_states[user_id].get("interests", [])),
        )

        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Ваш профіль створено! Оберіть дію нижче:", reply_markup=main_menu)

    elif step == "menu":
        if message.text == "👤 Мій профіль":
            user = await get_user_from_db(user_id)
            if user and user["photo"]:
                await message.answer_photo(
                    photo=user["photo"],
                    caption=f"👤 Ваш профіль:\n\n📛 Ім'я: {user['name']}\n🏙 Місто: {user['city']}\n🎯 Інтереси: {user['interests']}",
                    reply_markup=types.ReplyKeyboardMarkup(
                        keyboard=[[types.KeyboardButton(text="✏️ Змінити профіль")], [types.KeyboardButton(text="⬅️ Назад")]],
                        resize_keyboard=True
                    )
                )
            else:
                await message.answer("❗️Фото профілю не знайдено.", reply_markup=main_menu)

        elif message.text == "✏️ Змінити профіль":
            user = await get_user_from_db(user_id)
            user_states[user_id] = {"step": "name", "phone": user["phone"]}
            await message.answer("✍️ Введіть нове ім'я:", reply_markup=back_button)

        elif message.text == "➕ Створити подію":
            user = await get_user_from_db(user_id)
            if not user:
                await message.answer("⚠️ Спочатку зареєструйтесь через /start")
                return

            user_states[user_id] = {
                "step": "create_event_title",
                "creator_name": user["name"],
                "creator_phone": user["phone"]
            }
            print("📥 SET STEP = create_event_title")
            await message.answer("📝 Введіть назву події:", reply_markup=back_button)

        



# --- ДОДАТКОВА ФУНКЦІЯ ДЛЯ ВІДМІНИ --- #
async def cancel_event(user_id, title):
    conn = await connect_db()
    await conn.execute("""
        UPDATE events
        SET status = 'cancelled'
        WHERE creator_id = $1 AND title = $2
    """, user_id, title)
    await conn.close()

# --- ЛОГІКА СТВОРЕННЯ ПОДІЇ --- #

@dp.message(F.text & ~F.text.in_(["⬅️ Назад", "✅ Опублікувати", "❌ Скасувати", "👤 Мій профіль", "✏️ Змінити профіль", "➕ Створити подію", "🔍 Події за інтересами"]))
async def create_event_steps(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")
    print("🧪 STEP =", step)
    print("🧪 MESSAGE =", message.text)

    if step == "create_event_title":
        user_states[user_id]["event_title"] = message.text
        user_states[user_id]["step"] = "create_event_description"
        await message.answer("📝 Введіть опис події:", reply_markup=back_button)

    elif step == "create_event_description":
        user_states[user_id]["event_description"] = message.text
        user_states[user_id]["step"] = "create_event_date"
        await message.answer("📅 Введіть дату та час (наприклад 2025-05-28 18:00):", reply_markup=back_button)

    elif step == "create_event_date":
        user_states[user_id]["event_date"] = message.text
        user_states[user_id]["step"] = "create_event_location"
        await message.answer("📍 Вкажіть місце події:", reply_markup=back_button)

    elif step == "create_event_location":
        user_states[user_id]["event_location"] = message.text

        await save_event_to_db(
            user_id=user_id,
            name=user_states[user_id]["creator_name"],
            phone=user_states[user_id]["creator_phone"],
            title=user_states[user_id]["event_title"],
            description=user_states[user_id]["event_description"],
            date=user_states[user_id]["event_date"],
            location=user_states[user_id]["event_location"]
        )

        user_states[user_id]["step"] = "publish_confirm"
        await message.answer("🔍 Перевірте інформацію про подію:\n\n"
                             f"📛 Назва: {user_states[user_id]['event_title']}\n"
                             f"📅 Дата: {user_states[user_id]['event_date']}\n"
                             f"📍 Локація: {user_states[user_id]['event_location']}\n"
                             f"✏️ Опис: {user_states[user_id]['event_description']}\n\n"
                             f"✅ Підтвердити публікацію чи скасувати?",
                             reply_markup=types.ReplyKeyboardMarkup(
                                 keyboard=[
                                     [types.KeyboardButton(text="✅ Опублікувати")],
                                     [types.KeyboardButton(text="❌ Скасувати")],
                                     [types.KeyboardButton(text="⬅️ Назад")]
                                 ], resize_keyboard=True))

    elif step == "publish_confirm":
        if message.text == "✅ Опублікувати":
            await publish_event(user_id, user_states[user_id]['event_title'])
            user_states[user_id]["step"] = "menu"
            await message.answer("🚀 Подію опубліковано зі статусом 'active'!", reply_markup=main_menu)

        elif message.text == "❌ Скасувати":
            await cancel_event(user_id, user_states[user_id]['event_title'])
            user_states[user_id]["step"] = "menu"
            await message.answer("❌ Подію скасовано.", reply_markup=main_menu)



        elif step == "find_event_menu":
            if message.text == "🔍 Події за інтересами":
                user = await get_user_from_db(user_id)
                if user and user['interests']:
                    interests_list = [i.strip().lower() for i in user['interests'].split(',')]
                    events = await search_events_by_interests(interests_list)
                    if events:
                        response = "🔍 Знайдені події за вашими інтересами:\n\n"
                        for e in events:
                            response += (
                                f"📛 Назва: {e['title']}\n"
                                f"✏️ Опис: {e['description']}\n"
                                f"📅 Дата: {e['date']}\n"
                                f"📍 Локація: {e['location']}\n\n"
                            )
                        await message.answer(response)
                    else:
                        await message.answer("Нажаль, подій за вашими інтересами не знайдено.")
                else:
                    await message.answer("Ваш профіль не містить інтересів. Додайте їх для пошуку подій.")

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

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())





   
