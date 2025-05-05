import logging
import asyncio
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

# --- Логування --- #
logging.basicConfig(level=logging.INFO)

# --- Бот токен --- #
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Ініціалізація --- #
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Словники --- #
user_states = {}

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_users(data):
    with open("users.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_users()

# --- Меню --- #
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="🔍 Знайти подію")],
        [types.KeyboardButton(text="👤 Мій профіль")],
    ],
    resize_keyboard=True
)

back_button = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
    resize_keyboard=True
)

find_event_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="🎯 За інтересами")],
        [types.KeyboardButton(text="📍 Події поблизу")],
        [types.KeyboardButton(text="🏙 У місті")],
        [types.KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True
)

# --- Команди --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in users:
        user_states[user_id] = {"step": "menu"}
        await message.answer("👋 Радий вас знову бачити! Оберіть, що бажаєте зробити далі:", reply_markup=main_menu)
    else:
        user_states[user_id] = {"step": "authorization"}
        await message.answer(
            "👋 Привіт, ти потрапив у Findsy! Тут з легкістю знайдеш заняття на вечір або однодумців до своєї компанії! \n\nШукай, створюй, запрошуй, взаємодій та спілкуйся! 💛",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="📞 Авторизуватись")]],
                resize_keyboard=True
            )
        )

@dp.message(F.text == "📞 Авторизуватись")
async def authorize_step(message: types.Message):
    user_id = str(message.from_user.id)
    user_states[user_id]["step"] = "phone"
    await message.answer(
        "📲 Будь ласка, поділіться номером телефону:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="📱 Поділитися номером телефону", request_contact=True)], [types.KeyboardButton(text="⬅️ Назад")]],
            resize_keyboard=True,
            one_time_keyboard=True
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
        await message.answer("🏙 Дякую! Тепер введіть ваше місто:", reply_markup=back_button)

    elif step == "city":
        user_states[user_id]["city"] = message.text
        user_states[user_id]["step"] = "photo"
        await message.answer("🖼 Дякую! Тепер надішліть свою світлину (фото профілю):", reply_markup=back_button)

    elif step == "interests":
        user_states[user_id]["interests"] = message.text.split(",")
        users[user_id] = {
            "phone": user_states[user_id]["phone"],
            "name": user_states[user_id]["name"],
            "city": user_states[user_id]["city"],
            "photo": user_states[user_id]["photo"],
            "interests": user_states[user_id]["interests"]
        }
        save_users(users)
        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Ваш профіль успішно створено! Оберіть, що бажаєте зробити далі:", reply_markup=main_menu)

@dp.message(F.photo)
async def get_photo(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")
    if step == "photo":
        user_states[user_id]["photo"] = message.photo[-1].file_id
        user_states[user_id]["step"] = "interests"
        await message.answer("🎯 Дякую! Тепер вкажіть ваші інтереси через кому:", reply_markup=back_button)

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
        await message.answer("🖼 Будь ласка, надішліть свою світлину:", reply_markup=back_button)
    else:
        await message.answer("⬅️ Повертаємось у головне меню.", reply_markup=main_menu)
        user_states[user_id]["step"] = "menu"

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

