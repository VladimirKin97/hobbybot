import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
import os
import json

# --- ФУНКЦІЇ ДЛЯ РОБОТИ З ПРОФІЛЯМИ --- #

USERS_FILE = "users.json"

def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users(users_data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)

# Завантажуємо дані юзерів при запуску
users = load_users()

# Логування
logging.basicConfig(level=logging.INFO)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація бота і диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словник для тимчасового зберігання стану користувачів
user_states = {}

# --- КНОПКИ ГОЛОВНОГО МЕНЮ --- #
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="🔍 Знайти подію")],
        [types.KeyboardButton(text="👤 Мій профіль")],
    ],
    resize_keyboard=True
)

# --- КНОПКИ ДЛЯ ПОШУКУ ПОДІЙ --- #
find_event_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="🎯 Переглянути за інтересами")],
        [types.KeyboardButton(text="📍 Події поруч (5 км)")],
        [types.KeyboardButton(text="🏙 Всі події в місті")],
        [types.KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

# --- КНОПКА НАЗАД --- #
back_button = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
    resize_keyboard=True
)

# --- ОБРОБКА /start --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)  # user_id як стрічка для JSON

    if user_id not in users:
        # Якщо користувача нема у базі ➔ реєстрація
        user_states[user_id] = {"step": "authorization"}
        await message.answer(
            "👋 Привіт, ти потрапив у Findsy! Тут з легкістю знайдеш заняття на вечір або однодумців до своєї компанії! \n\nШукай, створюй, запрошуй, взаємодій та спілкуйся! 💛",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="📞 Авторизуватись")]],
                resize_keyboard=True
            )
        )
    else:
        # Якщо профіль вже є ➔ привітати і відкрити меню
        user_profile = users[user_id]
        user_states[user_id] = {"step": "menu"}
        await message.answer(
            f"👋 Привіт знову, {user_profile.get('name', 'друг')}! Обирай, що будемо робити далі:",
            reply_markup=main_menu
        )

@dp.message(F.text == "📞 Авторизуватись")
@dp.message(F.text == "📞 Авторизуватись")
async def authorize_step(message: types.Message):
    user_id = str(message.from_user.id)

    if user_id not in user_states:
        user_states[user_id] = {}

    user_states[user_id]["step"] = "phone"

    await message.answer(
        "📲 Будь ласка, поділіться номером телефону:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="📱 Поділитися номером телефону", request_contact=True)],
                [types.KeyboardButton(text="⬅️ Назад")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

@dp.message(F.contact)
@dp.message(F.contact)
async def get_phone(message: types.Message):
    user_id = str(message.from_user.id)

    if user_id not in user_states:
        user_states[user_id] = {}

    user_states[user_id]["phone"] = message.contact.phone_number
    user_states[user_id]["step"] = "name"

    await message.answer(
        "✍️ Введіть ваше ім'я:",
        reply_markup=back_button
    )


@dp.message(F.text & ~F.text.in_("⬅️ Назад"))
async def handle_steps(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "name":
        user_states[user_id]["name"] = message.text
        user_states[user_id]["step"] = "city"
        await message.answer(
            "🏙 Дякую! Тепер введіть ваше місто:",
            reply_markup=back_button
        )

    elif step == "city":
        user_states[user_id]["city"] = message.text
        user_states[user_id]["step"] = "photo"
        await message.answer(
            "🖼 Дякую! Тепер надішліть свою світлину (фото профілю):",
            reply_markup=back_button
        )

    elif step == "interests":
        user_states[user_id]["interests"] = message.text.split(",")

        # Зберігаємо профіль у файл users.json
        users[user_id] = {
            "phone": user_states[user_id]["phone"],
            "name": user_states[user_id]["name"],
            "city": user_states[user_id]["city"],
            "photo": user_states[user_id]["photo"],
            "interests": user_states[user_id]["interests"],
        }
        save_users(users)

        user_states[user_id]["step"] = "menu"
        await message.answer(
            "✅ Ваш профіль успішно створено! Оберіть, що бажаєте зробити далі:",
            reply_markup=main_menu
        )

    if step == "menu":
        if message.text == "➕ Створити подію":
            await message.answer("📝 Введіть назву події:", reply_markup=back_button)
            user_states[user_id]["step"] = "create_event_title"
        elif message.text == "🔍 Знайти подію":
            await message.answer("🔎 Виберіть спосіб пошуку:", reply_markup=find_event_menu)
            user_states[user_id]["step"] = "find_event_menu"
        elif message.text == "👤 Мій профіль":
            profile = users.get(user_id, {})
            await message.answer(
                f"👤 Ваш профіль:\nІм'я: {profile.get('name')}\nМісто: {profile.get('city')}\nІнтереси: {', '.join(profile.get('interests', []))}",
                reply_markup=main_menu
            )

    elif step == "create_event_title":
        user_states[user_id]["event_title"] = message.text
        user_states[user_id]["step"] = "create_event_description"
        await message.answer("🖊 Додайте короткий опис події:", reply_markup=back_button)

    elif step == "create_event_description":
        user_states[user_id]["event_description"] = message.text
        user_states[user_id]["step"] = "create_event_datetime"
        await message.answer("📅 Вкажіть дату і час проведення:", reply_markup=back_button)

    elif step == "create_event_datetime":
        user_states[user_id]["event_datetime"] = message.text
        user_states[user_id]["step"] = "create_event_location"
        await message.answer("📍 Вкажіть місто та місце проведення або поділіться геолокацією:", reply_markup=back_button)

    elif step == "create_event_location":
        user_states[user_id]["event_location"] = message.text
        user_states[user_id]["step"] = "create_event_capacity"
        await message.answer("👥 Вкажіть загальну кількість людей:", reply_markup=back_button)

    elif step == "create_event_capacity":
        user_states[user_id]["event_capacity"] = message.text
        user_states[user_id]["step"] = "create_event_needed"
        await message.answer("➕ Вкажіть кількість людей, яких шукаєте:", reply_markup=back_button)

    elif step == "create_event_needed":
        user_states[user_id]["event_needed"] = message.text
        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Подію створено! Оберіть, що бажаєте зробити далі:", reply_markup=main_menu)

    elif step == "find_event_menu":
        await message.answer("🔧 Пошук ще в розробці. Повертаємо у меню.", reply_markup=main_menu)
        user_states[user_id]["step"] = "menu"


@dp.message(F.photo)
async def get_photo(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "photo":
        user_states[user_id]["photo"] = message.photo[-1].file_id
        user_states[user_id]["step"] = "interests"
        await message.answer(
            "🎯 Дякую! Тепер вкажіть ваші інтереси через кому (наприклад: футбол, настолки, прогулянки):",
            reply_markup=back_button
        )


@dp.message(F.text == "⬅️ Назад")
async def go_back(message: types.Message):
    user_id = message.from_user.id
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
        await message.answer("🖼 Будь ласка, надішліть свою світлину:", reply_markup=back_button)
    else:
        await message.answer("⬅️ Повертаємось у головне меню.", reply_markup=main_menu)
        user_states[user_id]["step"] = "menu"

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
