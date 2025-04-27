import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Text
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
@dp.message(Text("\ud83d\udd0d \u0417\u043d\u0430\u0439\u0442\u0438 \u043a\u043e\u043c\u043f\u0430\u043d\u0456\u044e"))
async def find_company(message: types.Message):
    await message.answer(
        "📚 Список доступних подій:\n- Покер о 19:00\n- Прогулянка з собаками о 10:00\n- Мафія о 20:00"
    )

@dp.message(Text("\u2795 \u0421\u0442\u0432\u043e\u0440\u0438\u0442\u0438 \u043f\u043e\u0434\u0456\u044e"))
async def create_event(message: types.Message):
    await message.answer(
        "📅 Щоб створити подію, напишіть її назву у відповідь (поки що тестовий режим!)"
    )

@dp.message(Text("\ud83d\udc64 \u041c\u0456\u0439 \u043f\u0440\u043e\u0444\u0456\u043b\u044c"))
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
