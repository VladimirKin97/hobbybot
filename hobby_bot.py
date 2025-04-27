import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
import os

# Логування
logging.basicConfig(level=logging.INFO)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація бота і диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- КНОПКИ ГОЛОВНОГО МЕНЮ --- #
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="🔍 Знайти компанію")],
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="👤 Мій профіль")],
    ],
    resize_keyboard=True
)

# --- КНОПКА ДЛЯ ПОДІЛИТИСЯ КОНТАКТОМ --- #
request_contact_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [
            types.KeyboardButton(
                text="📱 Поділитися номером телефону",
                request_contact=True
            )
        ]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# --- ОБРОБКА /start --- #
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привіт! Я допоможу тобі знайти компанію для розваг і зустрічей! 💚",
        reply_markup=main_menu
    )

# --- ОБРОБКА ВИБОРУ МЕНЮ --- #
@dp.message(F.text == "🔍 Знайти компанію")
async def find_company(message: types.Message):
    await message.answer(
        "📚 Список доступних подій:\n- Покер о 19:00\n- Прогулянка з собаками о 10:00\n- Мафія о 20:00"
    )

@dp.message(F.text == "➕ Створити подію")
async def create_event(message: types.Message):
    await message.answer(
        "📅 Щоб створити подію, напишіть її назву у відповідь (поки що тестовий режим!)"
    )

@dp.message(F.text == "👤 Мій профіль")
async def my_profile(message: types.Message):
    await message.answer(
        "📱 Будь ласка, поділіться своїм номером телефону для авторизації:",
        reply_markup=request_contact_kb
    )

# --- ОБРОБКА ОТРИМАННЯ КОНТАКТУ --- #
@dp.message()
async def handle_contact(message: types.Message):
    if message.contact:
        phone_number = message.contact.phone_number
        await message.answer(
            f"📢 Дякуємо! Ваш номер збережено: {phone_number}",
            reply_markup=main_menu
        )
    else:
        await message.answer(
            "🔎 Я не зрозумів ваше повідомлення. Будь ласка, скористайтесь меню."
        )

# --- ЗАПУСК --- #
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

