import logging
import asyncio
from aiogram import Bot, Dispatcher, types
import os

# Логування
logging.basicConfig(level=logging.INFO)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація бота і диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message()
async def handle_message(message: types.Message):
    if message.text == "/start":
        await message.answer("Привіт! 👋 Я допоможу тобі знайти компанію для розваг і зустрічей!")
    else:
        await message.answer("Напиши /start, щоб почати 🚀")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
