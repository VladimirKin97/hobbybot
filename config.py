import os
import logging

# Налаштування логування (щоб бачити помилки в Railway)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Змінні оточення з Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Не знайдені змінні BOT_TOKEN або DATABASE_URL у Railway!")
