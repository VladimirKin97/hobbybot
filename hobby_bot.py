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
            "👋 Привіт! Давайте створимо ваш профіль. Натисніть на кнопку авторизації.",
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

@dp.message(F.text == "➕ Створити подію")
async def start_event_creation(message: types.Message):
    user_id = str(message.from_user.id)
    user_states[user_id]["step"] = "create_event_title"
    await message.answer(
        "📝 Введіть назву події:\n\n"
        "🔍 Рекомендація: Введіть коректну назву, яка відображає суть події.",
        reply_markup=back_button
    )

@dp.message(F.text & ~F.text.in_(["⬅️ Назад"]))
async def handle_event_creation(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "create_event_title":
        user_states[user_id]["event_title"] = message.text
        user_states[user_id]["step"] = "create_event_description"
        await message.answer(
            "📝 Додайте короткий опис події (до 200 символів):",
            reply_markup=back_button
        )

    elif step == "create_event_description":
        user_states[user_id]["event_description"] = message.text[:200]
        user_states[user_id]["step"] = "create_event_datetime"
        await message.answer(
            "📅 Вкажіть дату та час проведення (наприклад: 2025-05-08 19:00):",
            reply_markup=back_button
        )

    elif step == "create_event_datetime":
        user_states[user_id]["event_datetime"] = message.text
        user_states[user_id]["step"] = "create_event_location"
        await message.answer(
            "📍 Вкажіть місце проведення або поділіться геолокацією:",
            reply_markup=back_button
        )

    elif step == "create_event_location":
        user_states[user_id]["event_location"] = message.text
        user_states[user_id]["step"] = "create_event_confirmation"
        await message.answer(
            "✅ Перевірте інформацію:\n"
            f"📛 Назва: {user_states[user_id]['event_title']}\n"
            f"📝 Опис: {user_states[user_id]['event_description']}\n"
            f"📅 Дата і час: {user_states[user_id]['event_datetime']}\n"
            f"📍 Місце: {user_states[user_id]['event_location']}\n\n"
            "✅ Підтвердити / ❌ Скасувати",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[
                    [types.KeyboardButton(text="✅ Підтвердити")],
                    [types.KeyboardButton(text="❌ Скасувати")]
                ],
                resize_keyboard=True
            )
        )

@dp.message(F.text == "✅ Підтвердити")
async def confirm_event(message: types.Message):
    user_id = str(message.from_user.id)
    await message.answer("🎉 Подію успішно створено!", reply_markup=main_menu)

@dp.message(F.text == "❌ Скасувати")
async def cancel_event(message: types.Message):
    user_id = str(message.from_user.id)
    await message.answer("❗️ Створення події скасовано.", reply_markup=main_menu)

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

   
