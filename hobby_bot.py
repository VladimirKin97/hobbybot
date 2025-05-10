import logging
import asyncio
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

# --- ІНІЦІАЛІЗАЦІЯ --- #
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФАЙЛ ЗБЕРЕЖЕННЯ --- #
USER_DATA_FILE = "users.json"

if os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
else:
    users = {}

def save_users(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

user_states = {}

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

find_event_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="🔍 Події за інтересами")],
        [types.KeyboardButton(text="📍 Події біля мене")],
        [types.KeyboardButton(text="🏙 Події у місті")],
        [types.KeyboardButton(text="⬅️ Назад")],
    ], resize_keyboard=True
)

# --- START --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in users:
        await message.answer(
            f"👋 Вітаю, {users[user_id].get('name')}! Обери дію нижче:",
            reply_markup=main_menu
        )
        user_states[user_id] = {"step": "menu"}
    else:
        await message.answer(
            "👋 Привіт, ти потрапив у Findsy! Тут з легкістю знайдеш заняття на вечір або однодумців до своєї компанії!\n\nШукай, створюй, запрошуй, взаємодій та спілкуйся! 💛",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="📞 Авторизуватись")]],
                resize_keyboard=True
            )
        )
        user_states[user_id] = {"step": "authorization"}

@dp.message(F.text == "📞 Авторизуватись")
async def authorize_step(message: types.Message):
    user_id = str(message.from_user.id)
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
    user_states[user_id]["phone"] = message.contact.phone_number
    user_states[user_id]["step"] = "name"
    await message.answer("✍️ Введіть ваше ім'я:", reply_markup=back_button)

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
        users[user_id] = {
            "phone": user_states[user_id].get("phone"),
            "name": user_states[user_id].get("name"),
            "city": user_states[user_id].get("city"),
            "photo": user_states[user_id].get("photo"),
            "interests": user_states[user_id].get("interests")
        }
        save_users(users)
        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Ваш профіль створено! Оберіть дію нижче:", reply_markup=main_menu)

    elif step == "menu":
        if message.text == "👤 Мій профіль":
            profile = users.get(user_id, {})
            if profile.get("photo"):
                await message.answer_photo(
                    photo=profile["photo"],
                    caption=f"👤 Ваш профіль:\n\n📛 Ім'я: {profile.get('name')}\n🏙 Місто: {profile.get('city')}\n🎯 Інтереси: {', '.join(profile.get('interests', []))}",
                    reply_markup=types.ReplyKeyboardMarkup(
                        keyboard=[[types.KeyboardButton(text="✏️ Змінити профіль")],[types.KeyboardButton(text="⬅️ Назад")]],
                        resize_keyboard=True
                    )
                )
            else:
                await message.answer("❗️Фото профілю не знайдено.", reply_markup=main_menu)

        elif message.text == "✏️ Змінити профіль":
            phone = users[user_id].get("phone")
            user_states[user_id] = {"step": "name", "phone": phone}
            await message.answer("✍️ Введіть нове ім'я:", reply_markup=back_button)

        elif message.text == "➕ Створити подію":
            user_states[user_id]["step"] = "create_event_title"
            await message.answer("📝 Введіть назву події:", reply_markup=back_button)

        elif message.text == "🔍 Знайти подію":
            user_states[user_id]["step"] = "find_event_menu"
            await message.answer("🔎 Оберіть як шукати події:", reply_markup=find_event_menu)

    elif step == "photo":
        await message.answer("🖼 Надішліть свою світлину (фото):", reply_markup=back_button)

    elif step == "create_event_title":
        event_title = message.text.strip()
        if len(event_title) < 3:
            await message.answer("❗ Назва надто коротка. Спробуйте ще раз.")
            return

        user_states[user_id]["event_title"] = event_title
        user_states[user_id]["step"] = "create_event_description"
        await message.answer(
            "📝 Введіть опис події:\n\n"
            "✏️ *Рекомендація:* Опис має бути коротким і чітким, щоб зацікавити учасників.",
        reply_markup=back_button
        )


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


   


# --- ОБРОБКА СТВОРЕННЯ ПОДІЇ --- #
@dp.message(F.text == "➕ Створити подію")
async def start_event_creation(message: types.Message):
    user_id = str(message.from_user.id)
    user_states[user_id] = {"step": "create_event_title"}
    await message.answer(
        "📝 Введіть назву події:

"
        "🔍 *Рекомендація:* Введіть коректну та чітку назву події. "
        "Користувачі шукатимуть її саме за ключовими словами.",
        reply_markup=back_button
    )

@dp.message(F.text & ~F.text.in_(["⬅️ Назад"]))
async def create_event_steps(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "create_event_title":
        event_title = message.text.strip()
        if len(event_title) < 3:
            await message.answer("❗ Назва надто коротка. Спробуйте ще раз.")
            return

        user_states[user_id]["event_title"] = event_title
        user_states[user_id]["step"] = "create_event_description"
        await message.answer(
            "📝 Введіть опис події:"
            
            "✏️ *Рекомендація:* Опис має бути коротким і чітким, щоб зацікавити учасників.",
            reply_markup=back_button
        )

    elif step == "create_event_description":
        event_description = message.text.strip()
        user_states[user_id]["event_description"] = event_description
        user_states[user_id]["step"] = "create_event_date"
        await message.answer(
            "📅 Введіть дату та час події (наприклад: 25.05.2025 18:00):",
            reply_markup=back_button
        )

    elif step == "create_event_date":
        event_date = message.text.strip()
        user_states[user_id]["event_date"] = event_date
        user_states[user_id]["step"] = "create_event_location"
        await message.answer(
            "📍 Вкажіть місце проведення події (адресу або назву локації):",
            reply_markup=back_button
        )

    elif step == "create_event_location":
        event_location = message.text.strip()
        user_states[user_id]["event_location"] = event_location
        user_states[user_id]["step"] = "create_event_limit"
        await message.answer(
            "👥 Вкажіть ліміт учасників (число):",
            reply_markup=back_button
        )

    elif step == "create_event_limit":
        try:
            event_limit = int(message.text.strip())
            user_states[user_id]["event_limit"] = event_limit

            # Збереження події
            event = {
                "title": user_states[user_id].get("event_title"),
                "description": user_states[user_id].get("event_description"),
                "date": user_states[user_id].get("event_date"),
                "location": user_states[user_id].get("event_location"),
                "limit": user_states[user_id].get("event_limit"),
                "organizer": users[user_id].get("name")
            }
            save_users(event)
            user_states[user_id]["step"] = "menu"

            await message.answer(
                f"✅ Подію створено!"
                f"📛 Назва: {event['title']}"
                f"✏️ Опис: {event['description']}"
                f"📅 Дата: {event['date']}"
                f"📍 Локація: {event['location']}"
                f"👥 Ліміт учасників: {event['limit']}"
                f"👤 Організатор: {event['organizer']}",
                reply_markup=main_menu
            )
        except ValueError:
            await message.answer("❗ Ліміт учасників має бути числом. Спробуйте ще раз.")





   
