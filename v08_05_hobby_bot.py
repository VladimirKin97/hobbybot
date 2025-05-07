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
    for user_id in users:
        user_states[user_id] = {"step": "menu"}
else:
    users = {}

user_states = {}

def save_users(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

# --- Створення події --- #
@dp.message(F.text == "➕ Створити подію")
async def start_event_creation(message: types.Message):
    user_id = str(message.from_user.id)
    user_states[user_id] = {"step": "create_event_title"}
    await message.answer(
        "📝 Введіть назву події:", reply_markup=back_button
    )

@dp.message(F.text & ~F.text.in_(["⬅️ Назад"]))
async def create_event_steps(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step == "create_event_title":
        user_states[user_id]["event_title"] = message.text
        user_states[user_id]["step"] = "create_event_description"
        await message.answer(
            "🖊 Додайте короткий опис події (до 200 символів):",
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
            "📍 Вкажіть місце проведення (місто, адреса):",
            reply_markup=back_button
        )

    elif step == "create_event_location":
        user_states[user_id]["event_location"] = message.text
        user_states[user_id]["step"] = "create_event_capacity"
        await message.answer(
            "👥 Вкажіть загальну кількість учасників:",
            reply_markup=back_button
        )

    elif step == "create_event_capacity":
        user_states[user_id]["event_capacity"] = message.text
        user_states[user_id]["step"] = "create_event_needed"
        await message.answer(
            "➕ Вкажіть кількість людей, яких ще шукаєте:",
            reply_markup=back_button
        )

    elif step == "create_event_needed":
        user_states[user_id]["event_needed"] = message.text
        user_states[user_id]["step"] = "confirm_event"
        await message.answer(
            f"✅ Подію створено!\n\nНазва: {user_states[user_id]['event_title']}\nОпис: {user_states[user_id]['event_description']}\nДата і час: {user_states[user_id]['event_datetime']}\nМісце: {user_states[user_id]['event_location']}\nУчасники: {user_states[user_id]['event_capacity']} (потрібно: {user_states[user_id]['event_needed']})",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="✅ Підтвердити"), types.KeyboardButton(text="❌ Скасувати")]],
                resize_keyboard=True
            )
        )

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
