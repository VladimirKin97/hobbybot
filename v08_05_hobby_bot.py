import logging
import asyncio
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

# --- INITIALIZATION ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- DATA FILE ---
USER_DATA_FILE = "users.json"
if os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
else:
    users = {}

# Utility functions

def save_users(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_users():
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

users = load_users()
user_states = {}

# --- KEYBOARDS ---
main_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.add(types.KeyboardButton("➕ Створити подію"))
main_menu.add(types.KeyboardButton("🔍 Знайти подію"))
main_menu.add(types.KeyboardButton("👤 Мій профіль"))

back_button = types.ReplyKeyboardMarkup(resize_keyboard=True)
back_button.add(types.KeyboardButton("⬅️ Назад"))

find_event_menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
find_event_menu.add(types.KeyboardButton("🔍 Події за інтересами"))
find_event_menu.add(types.KeyboardButton("📍 Події біля мене"))
find_event_menu.add(types.KeyboardButton("🏙 Події у місті"))
find_event_menu.add(types.KeyboardButton("⬅️ Назад"))

# --- HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in users:
        user_states[user_id] = {"step": "menu"}
        await message.answer(
            f"👋 Вітаю, {users[user_id]['name']}! Обери дію нижче:",
            reply_markup=main_menu
        )
    else:
        user_states[user_id] = {"step": "authorization"}
        await message.answer(
            "👋 Привіт, ти потрапив у Findsy! Тут з легкістю знайдеш заняття на вечір або однодумців до своєї компанії! 💛",
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
        "📲 Поділіться номером телефону:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
                [types.KeyboardButton(text="⬅️ Назад")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(F.contact)
async def get_phone(message: types.Message):
    user_id = str(message.from_user.id)
    user_states[user_id]["phone"] = message.contact.phone_number
    user_states[user_id]["step"] = "name"
    await message.answer("✍️ Введіть ваше ім'я:", reply_markup=back_button)

@dp.message(F.photo)
async def get_photo(message: types.Message):
    user_id = str(message.from_user.id)
    if user_states.get(user_id, {}).get("step") == "photo":
        user_states[user_id]["photo"] = message.photo[-1].file_id
        user_states[user_id]["step"] = "interests"
        await message.answer("🎯 Вкажіть ваші інтереси через кому:", reply_markup=back_button)

@dp.message(F.text & ~F.text.in_(['⬅️ Назад']))
async def handle_steps(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    # Registration flow
    if step == "name":
        user_states[user_id]["name"] = message.text
        user_states[user_id]["step"] = "city"
        await message.answer("🏙 Введіть ваше місто:", reply_markup=back_button)

    elif step == "city":
        user_states[user_id]["city"] = message.text
        user_states[user_id]["step"] = "photo"
        await message.answer("🖼 Надішліть свою світлину:", reply_markup=back_button)

    elif step == "interests":
        user_states[user_id]["interests"] = [i.strip() for i in message.text.split(",")]
        users[user_id] = {
            "phone": user_states[user_id]["phone"],
            "name": user_states[user_id]["name"],
            "city": user_states[user_id]["city"],
            "photo": user_states[user_id]["photo"],
            "interests": user_states[user_id]["interests"]
        }
        save_users(users)
        user_states[user_id]["step"] = "menu"
        await message.answer("✅ Ваш профіль створено! Оберіть дію нижче:", reply_markup=main_menu)

    # Main menu actions
    elif step == "menu":
        text = message.text
        if text == "👤 Мій профіль":
            profile = users.get(user_id, {})
            if profile.get("photo"):
                await message.answer_photo(
                    photo=profile["photo"],
                    caption=(
                        f"👤 Ваш профіль:\n\n"
                        f"📛 Ім'я: {profile.get('name')}\n"
                        f"🏙 Місто: {profile.get('city')}\n"
                        f"🎯 Інтереси: {', '.join(profile.get('interests', []))}"
                    ),
                    reply_markup=types.ReplyKeyboardMarkup(
                        keyboard=[
                            [types.KeyboardButton(text="✏️ Змінити профіль")],
                            [types.KeyboardButton(text="⬅️ Назад")]
                        ],
                        resize_keyboard=True
                    )
                )
            else:
                await message.answer("❗️Фото профілю не знайдено.", reply_markup=main_menu)

        elif text == "✏️ Змінити профіль":
            phone = users[user_id]["phone"]
            user_states[user_id] = {"step": "name", "phone": phone}
            await message.answer("✍️ Введіть нове ім'я:", reply_markup=back_button)

        elif text == "🔍 Знайти подію":
            user_states[user_id]["step"] = "find_event_menu"
            await message.answer("🔎 Оберіть як шукати події:", reply_markup=find_event_menu)

        elif text == "➕ Створити подію":
            user_states[user_id]["step"] = "create_event_title"
            await message.answer(
                "📝 Введіть назву події:\n\n"
                "🔍 *Рекомендація:* Введіть коректну та чітку назву події.",
                reply_markup=back_button
            )
        else:
            await message.answer("Будь ласка, оберіть дію з меню.", reply_markup=main_menu)

    # Find event options
    elif step == "find_event_menu":
        if message.text in ["🔍 Події за інтересами", "📍 Події біля мене", "🏙 Події у місті"]:
            # TODO: implement search logic
            await message.answer("🔎 Шукаю події...", reply_markup=main_menu)
            user_states[user_id]["step"] = "menu"
        else:
            await message.answer("Оберіть опцію пошуку:", reply_markup=find_event_menu)

@dp.message(F.text & ~F.text.in_(['⬅️ Назад']))
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
            "📍 Вкажіть місце проведення (місто, адреса) або поділіться геолокацією:",
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
        user_states[user_id]["step"] = "menu"
        # TODO: save event data
        await message.answer("✅ Подію створено! Дякуємо за додавання інформації.", reply_markup=main_menu)

@dp.message(F.text == "⬅️ Назад")
async def go_back(message: types.Message):
    user_id = str(message.from_user.id)
    step = user_states.get(user_id, {}).get("step")

    if step in ["name", "city", "photo", "interests"]:
        # Go back in registration
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
        user_states[user_id]["step"] = "menu"
        await message.answer("⬅️ Повертаємось у головне меню.", reply_markup=main_menu)

# --- RUN ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

