import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command

# Імпортуємо наші нові модулі
from config import BOT_TOKEN, ADMIN_CHAT_ID
from database import init_db_pool, get_user_from_db, save_user_to_db, find_events_near
from keyboards import main_menu, back_kb, skip_back_kb, search_menu_kb, location_choice_kb
from utils import _now_utc

# Ініціалізація бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словник для збереження станів користувачів (твоя FSM)
user_states: dict[int, dict] = {}

# ==========================================
# 1. ТОЧКА ВХОДУ (Гостьовий режим)
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()

    try:
        user = await get_user_from_db(uid)
    except Exception as e:
        logging.error(f"Помилка БД: {e}")
        await message.answer("⚠️ Не вдалося з'єднатися з базою даних.")
        return

    if user:
        # Користувач вже зареєстрований
        st['step'] = 'menu'
        await message.answer(
            f"👋 Вітаю, {user['name']}! Обери, що хочеш зробити:",
            reply_markup=main_menu(is_registered=True)
        )
    else:
        # НОВИЙ ГОСТЬОВИЙ РЕЖИМ
        st['step'] = 'guest_menu'
        await message.answer(
            "🐧 Привіт! Це Findsy — бот для пошуку компанії на івенти, настолки та спорт.\n\n"
            "Ти можеш одразу подивитися, що відбувається поруч, а зареєструватися пізніше! 😊",
            reply_markup=main_menu(is_guest=True)
        )

# ==========================================
# 2. ОБРОБКА КНОПОК МЕНЮ
# ==========================================
@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    step = st.get('step', 'guest_menu')

    # --- Кнопки для ГОСТЯ ---
    if text in ["🔍 Знайти подію (Гостьовий доступ)", "🔍 Знайти подію", "🔍 Дивитися події (Гость)"]:
        st['step'] = 'search_menu'
        await message.answer(
            "Як шукаємо події?\n"
            "• 🔎 За ключовим словом\n"
            "• 📍 Поруч зі мною",
            reply_markup=search_menu_kb()
        )
        return

    if text in ["👤 Створити профіль / Реєстрація", "👤 Зареєструватися"]:
        st['step'] = 'name'
        await message.answer(
            "📝 <b>Реєстрація у Findsy</b>\n\n"
            "Вкажи імʼя або нікнейм, за яким тебе будуть бачити інші.",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    # --- ТРИГЕР: Створення події (потребує реєстрації) ---
    if text == "➕ Створити подію":
        user = await get_user_from_db(uid)
        if not user:
            st['step'] = 'name'
            await message.answer(
                "⚠️ Щоб створювати події, потрібно створити профіль.\n\n"
                "📝 Вкажи своє ім'я або нікнейм:",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return
        
        st['step'] = 'create_event_title'
        await message.answer("<b>📝 Назва події</b>\nКоротко опиши суть:", parse_mode="HTML", reply_markup=back_kb())
        return

    # --- ЛОГІКА РЕЄСТРАЦІЇ ---
    if step == 'name':
        st['name'] = text
        st['step'] = 'city'
        await message.answer("🏙 <b>Місто</b>\nНапиши місто, де плануєш ходити на події:", parse_mode="HTML")
        return

    if step == 'city':
        st['city'] = text
        st['step'] = 'interests'
        await message.answer("🎯 <b>Інтереси</b>\nНапиши свої інтереси через кому (наприклад: кіно, мафія, спорт):", parse_mode="HTML")
        return

    if step == 'interests':
        interests = text
        # Зберігаємо юзера в БД!
        try:
            await save_user_to_db(uid, phone="", name=st['name'], city=st['city'], photo="", interests=interests)
            st['step'] = 'menu'
            await message.answer("✅ Профіль успішно створено!", reply_markup=main_menu(is_registered=True))
        except Exception as e:
            logging.error(f"Помилка реєстрації: {e}")
            await message.answer("❌ Сталася помилка при збереженні.", reply_markup=main_menu(is_guest=True))
        return

    # --- ЛОГІКА ПОШУКУ ПОБЛИЗУ ---
    if step == 'search_menu' and text == "📍 Поруч зі мною":
        st['step'] = 'search_geo_wait_location'
        await message.answer("Надішліть геолокацію, щоб я знайшов івенти поруч:", reply_markup=location_choice_kb())
        return

    # Обробка кнопки "Назад"
    if text == "⬅️ Назад" or text == "🏠 Меню":
        user = await get_user_from_db(uid)
        st['step'] = 'menu' if user else 'guest_menu'
        await message.answer("🏠 Головне меню", reply_markup=main_menu(is_registered=bool(user)))
        return


@dp.message(F.location)
async def handle_location(message: types.Message):
    """Обробка відправленої геолокації"""
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    
    if st.get('step') == 'search_geo_wait_location':
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Використовуємо нову функцію з пулом БД (радіус 10 км за замовчуванням)
        events = await find_events_near(lat, lon, radius_km=10.0, limit=5)
        
        if events:
            await message.answer(f"🎉 Знайдено {len(events)} подій поруч з вами!")
            # Тут в майбутньому ми додамо красиве виведення карток івентів
            for ev in events:
                await message.answer(f"📍 {ev['title']} ({ev['dist_km']:.1f} км від вас)")
        else:
            await message.answer("😕 Поруч поки немає активних подій.")
            
        user = await get_user_from_db(uid)
        await message.answer("Меню:", reply_markup=main_menu(is_registered=bool(user)))


# ==========================================
# 3. ЗАПУСК БОТА (Start Polling)
# ==========================================
async def main():
    logging.info("🚀 Запускаємо Findsy Bot...")
    
    # 1. Створюємо пул з'єднань з БД (DBeaver)
    await init_db_pool()
    
    # 2. Видаляємо старі вебхуки та запускаємо отримання повідомлень
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
