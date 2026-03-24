import asyncio
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command

# Імпортуємо наші модулі
from config import BOT_TOKEN, ADMIN_CHAT_ID
from database import (init_db_pool, get_user_from_db, save_user_to_db, 
                      find_events_near, save_event_to_db, get_organizer_avg_rating, 
                      update_event_field, list_user_events, find_events_by_kw)
from keyboards import (main_menu, back_kb, skip_back_kb, search_menu_kb, 
                       location_choice_kb, month_kb, event_publish_kb, 
                       myevents_filter_kb, event_join_kb)
from utils import _now_utc, parse_user_datetime, parse_time_hhmm

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states: dict[int, dict] = {}

# ==========================================
# 1. ТОЧКА ВХОДУ
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
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}! Обери, що хочеш зробити:", reply_markup=main_menu(is_guest=False))
    else:
        st['step'] = 'guest_menu'
        await message.answer(
            "🐧 Привіт! Це Findsy — бот для пошуку компанії на івенти, настолки та спорт.\n\n"
            "Ти можеш одразу подивитися, що відбувається поруч, а зареєструватися пізніше! 😊",
            reply_markup=main_menu(is_guest=True)
        )

# ==========================================
# 2. СПЕЦИФІЧНІ КНОПКИ (МОЇ ІВЕНТИ ТА ПОШУК)
# Повинні бути ВИЩЕ за загальний обробник тексту!
# ==========================================
@dp.message(F.text == "📦 Мої івенти")
async def my_events_cmd(message: types.Message):
    uid = message.from_user.id
    events = await list_user_events(uid, 'active')
    if not events:
        await message.answer("У тебе поки немає активних подій 🤷‍♂️\nСтвори нову!", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        return
    text = "<b>📦 Твої активні події:</b>\n\n"
    for i, ev in enumerate(events, 1):
        dt_str = ev['date'].strftime('%d.%m %H:%M') if ev['date'] else "—"
        text += f"{i}. <b>{ev['title']}</b>\n📅 {dt_str} | 👥 Заявок: {ev['capacity'] - ev['needed_count']}/{ev['capacity']}\n\n"
    await message.answer(text, parse_mode="HTML", reply_markup=myevents_filter_kb())

@dp.message(F.text == "🔎 За ключовим словом")
async def search_kw_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['step'] = 'search_kw_wait'
    await message.answer("Введи слово для пошуку (наприклад: <i>мафія, теніс, кіно</i>):", parse_mode="HTML", reply_markup=back_kb())

@dp.message(F.text == "🔮 За моїми інтересами")
async def search_by_interests(message: types.Message):
    uid = message.from_user.id
    user = await get_user_from_db(uid)
    if not user or not user.get('interests'):
        await message.answer("У тебе не заповнені інтереси в профілі 😕\nЗайди в «Мій профіль» і онови їх!", reply_markup=main_menu(is_guest=not bool(user)))
        return
    # Беремо перший інтерес з анкети юзера для пошуку
    interests = user['interests'].split(',')[0].strip()
    await message.answer(f"🔍 Шукаю події за твоїм головним інтересом: <b>{interests}</b>...", parse_mode="HTML")
    # Шукаємо
    events = await find_events_by_kw(interests, limit=5)
    await render_events_list(message, events, uid, f"за інтересом «{interests}»")

async def render_events_list(message: types.Message, events: list, uid: int, error_text: str):
    """Допоміжна функція для виведення карток івентів"""
    if not events:
        await message.answer(f"😕 {error_text} нічого не знайдено.", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        return
    await message.answer(f"🎉 Знайдено {len(events)} подій:")
    for ev in events:
        dt_str = ev['date'].strftime('%d.%m.%Y %H:%M') if ev['date'] else "—"
        org_name = ev.get('organizer_name', 'Невідомий')
        card = (
            f"🎯 <b>{ev['title']}</b>\n"
            f"👤 Організатор: {org_name}\n"
            f"📅 {dt_str}\n"
            f"📍 {ev['location']}\n\n"
            f"📝 {ev['description'][:200]}\n\n"
            f"👥 Шукають ще: {ev['needed_count']} людей"
        )
        # Кнопка "Долучитися" тільки якщо івент не твій
        kb = event_join_kb(ev['id']) if str(ev['user_id']) != str(uid) else None
        if ev['photo']:
            await message.answer_photo(ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(card, parse_mode="HTML", reply_markup=kb)

# ==========================================
# 3. ЗАГАЛЬНИЙ ОБРОБНИК ТЕКСТУ
# ==========================================
@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    step = st.get('step', 'guest_menu')

    # Обробка кнопки "Назад"
    if text in ["⬅️ Назад", "🏠 Меню"]:
        user = await get_user_from_db(uid)
        st['step'] = 'menu' if user else 'guest_menu'
        await message.answer("🏠 Головне меню", reply_markup=main_menu(is_guest=not bool(user)))
        return

    # --- МЕНЮ ПОШУКУ ---
    if text in ["🎛 Фільтр івентів (Гость)", "🎛 Фільтр івентів"]:
        st['step'] = 'search_menu'
        await message.answer(
            "Як шукаємо події?\n"
            "• 🔎 За ключовим словом\n"
            "• 📍 Поруч зі мною\n"
            "• 🔮 За моїми інтересами", 
            reply_markup=search_menu_kb()
        )
        return

    # --- ОЧІКУВАННЯ КЛЮЧОВОГО СЛОВА ---
    if step == 'search_kw_wait':
        events = await find_events_by_kw(text, limit=5)
        await render_events_list(message, events, uid, f"За запитом «{text}»")
        st['step'] = 'menu'
        return

    # --- ІНША ЛОГІКА (Реєстрація, Профіль, Створення івенту) ---
    # (Цей блок працював і раніше)
    if text in ["👤 Створити профіль / Реєстрація", "👤 Зареєструватися"]:
        st['step'] = 'name'
        await message.answer("📝 <b>Реєстрація у Findsy</b>\n\nВкажи імʼя або нікнейм.", parse_mode="HTML", reply_markup=back_kb())
        return

    if text == "👤 Мій профіль":
        user = await get_user_from_db(uid)
        if user:
            avg = await get_organizer_avg_rating(uid)
            avg_line = f"\n⭐ Рейтинг організатора: {avg:.1f}/10" if avg else ""
            caption = f"👤 Профіль:\n📛 {user['name']}\n🏙 {user['city']}\n🎯 {user['interests']}{avg_line}"
            kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text='✏️ Змінити профіль')],[types.KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
            if user.get('photo'):
                await message.answer_photo(user['photo'], caption=caption, reply_markup=kb)
            else:
                await message.answer(caption, reply_markup=kb)
        return

    if text == "✏️ Змінити профіль":
        user = await get_user_from_db(uid) or {}
        st.update({'step': 'edit_name', 'name': user.get('name',''), 'city': user.get('city','')})
        await message.answer("✍️ Нове ім'я або натисни «⏭ Пропустити».", reply_markup=skip_back_kb())
        return

    if step in ['name', 'edit_name']:
        if text != "⏭ Пропустити": st['name'] = text
        st['step'] = 'city' if step == 'name' else 'edit_city'
        await message.answer("🏙 Введи місто (або пропусти):", reply_markup=skip_back_kb() if step == 'edit_name' else back_kb())
        return

    if step in ['city', 'edit_city']:
        if text != "⏭ Пропустити": st['city'] = text
        st['step'] = 'photo' if step == 'city' else 'edit_photo'
        await message.answer("🖼 Надішли фото профілю (або пропусти):", reply_markup=skip_back_kb() if step == 'edit_city' else back_kb())
        return

    if step == 'edit_photo' and text == "⏭ Пропустити":
        st['step'] = 'edit_interests'
        await message.answer("🎯 Онови інтереси (або пропусти):", reply_markup=skip_back_kb())
        return

    if step in ['interests', 'edit_interests']:
        if text != "⏭ Пропустити": st['interests'] = text
        try:
            await save_user_to_db(uid, "", st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            st['step'] = 'menu'
            await message.answer("✅ Профіль збережено!", reply_markup=main_menu(is_guest=False))
        except Exception as e:
            logging.error(f"Помилка збереження: {e}")
            await message.answer("❌ Сталася помилка.", reply_markup=main_menu(is_guest=True))
        return

    if text == "➕ Створити подію":
        user = await get_user_from_db(uid)
        if not user:
            st['step'] = 'name'
            await message.answer("⚠️ Спочатку треба створити профіль.\nВкажи своє ім'я:", reply_markup=back_kb())
            return
        st.clear(); st['step'] = 'create_event_title'; st['creator_name'] = user['name']
        await message.answer("<b>📝 Назва події</b>\nКоротко опиши суть:", parse_mode="HTML", reply_markup=back_kb())
        return

    if step == 'create_event_title':
        st['event_title'] = text
        st['step'] = 'create_event_description'
        await message.answer("<b>📄 Опис події</b>\nОпиши детально:", parse_mode="HTML", reply_markup=back_kb())
        return

    if step == 'create_event_description':
        st['event_description'] = text
        st['step'] = 'create_event_date'
        now = datetime.now()
        await message.answer("<b>📅 Дата та час</b>\nВведи текстом (10.10.2025 19:30) або обери в календарі:", parse_mode="HTML", reply_markup=back_kb())
        await message.answer("🗓 Обери день:", reply_markup=month_kb(now.year, now.month))
        return

    if step == 'create_event_date':
        dt = parse_user_datetime(text)
        if not dt:
            await message.answer("Не впізнав дату. Приклад: 10.10.2025 19:30", reply_markup=back_kb())
            return
        st['event_date'] = dt
        st['step'] = 'create_event_location'
        await message.answer("📍 Локація (гео або текстом)", reply_markup=location_choice_kb())
        return

    if step == 'create_event_time':
        t = parse_time_hhmm(text)
        if not t:
            await message.answer("Формат часу HH:MM, напр. 19:30", reply_markup=back_kb())
            return
        d: date = st.get('picked_date')
        st['event_date'] = datetime(d.year, d.month, d.day, t[0], t[1])
        st['step'] = 'create_event_location'
        await message.answer("📍 Локація (гео або текстом)", reply_markup=location_choice_kb())
        return

    if step == 'create_event_location':
        if text == "📝 Ввести адресу текстом":
            st['step'] = 'create_event_location_name'
            await message.answer("Вкажи адресу:", reply_markup=back_kb())
            return
        if text == "⏭ Пропустити локацію":
            st['event_location'] = ''
            st['step'] = 'create_event_capacity'
            await message.answer("👥 Місткість (скільки всього людей):", reply_markup=back_kb())
            return
        await message.answer("Надішліть гео або виберіть кнопку.", reply_markup=location_choice_kb())
        return

    if step == 'create_event_location_name':
        st['event_location'] = text
        st['step'] = 'create_event_capacity'
        await message.answer("👥 Місткість (скільки всього людей):", reply_markup=back_kb())
        return

    if step == 'create_event_capacity':
        if not text.isdigit() or int(text) <= 0:
            await message.answer("❗ Введи позитивне число.")
            return
        st['capacity'] = int(text)
        st['step'] = 'create_event_needed'
        await message.answer("👤 Скільки ще учасників шукаєш?", reply_markup=back_kb())
        return

    if step == 'create_event_needed':
        if not text.isdigit() or int(text) <= 0 or int(text) > st.get('capacity', 999):
            await message.answer(f"❗ Від 1 до {st.get('capacity')}")
            return
        st['needed_count'] = int(text)
        st['step'] = 'create_event_photo'
        await message.answer("📸 Фото події (опційно)", reply_markup=skip_back_kb())
        return

    if step == 'create_event_photo' and text == "⏭ Пропустити":
        st['event_photo'] = None
        st['step'] = 'create_event_review'
        await send_event_review(message.chat.id, st)
        return

    if step == 'create_event_review':
        if text == '✅ Опублікувати':
            try:
                await save_event_to_db(
                    uid, st.get('creator_name',''), "", st['event_title'], st['event_description'],
                    st['event_date'], st.get('event_location',''), st['capacity'], st['needed_count'],
                    'active', st.get('event_lat'), st.get('event_lon'), st.get('event_photo')
                )
                await message.answer("🚀 Подія опублікована!", reply_markup=main_menu(is_guest=False))
            except Exception as e:
                logging.error(f"Publish error: {e}")
                await message.answer("❌ Помилка публікації", reply_markup=main_menu(is_guest=False))
            st['step'] = 'menu'
        elif text == '✏️ Редагувати':
            st['step'] = 'create_event_title'
            await message.answer("📝 Нова назва:", reply_markup=back_kb())
        elif text == '❌ Скасувати':
            st['step'] = 'menu'
            await message.answer("❌ Створення скасовано.", reply_markup=main_menu(is_guest=False))
        return

# ==========================================
# 4. ФОТО, ГЕО ТА КАЛЕНДАР (ІНЛАЙН КНОПКИ)
# ==========================================
def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%Y-%m-%d %H:%M') if isinstance(dt, datetime) else "—"
    loc_line = st.get('event_location', "—")
    if not loc_line and st.get('event_lat'):
        loc_line = f"{st.get('event_lat'):.5f}, {st.get('event_lon'):.5f}"
        
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    places_line = f"👥 Заповнено: {filled}/{st.get('capacity','—')} • шукаємо ще: {st.get('needed_count','—')}"
    parts = [
        "<b>Перевір дані перед публікацією</b>",
        f"📝 {st.get('event_title','—')}",
        f"📄 {(st.get('event_description','') or '—')[:500]}",
        f"📅 {dt_str}",
        f"📍 {loc_line}",
        places_line
    ]
    return "\n".join(parts)

async def send_event_review(chat_id: int, st: dict):
    caption = compose_event_review_text(st)
    kb = event_publish_kb()
    photo = st.get('event_photo')
    if photo:
        try:
            await bot.send_photo(chat_id, photo, caption=caption, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    step = st.get('step')
    if step in ('photo', 'edit_photo'):
        st['photo'] = message.photo[-1].file_id
        st['step'] = 'interests' if step == 'photo' else 'edit_interests'
        await message.answer("🎯 Інтереси (через кому):", reply_markup=skip_back_kb() if step == 'edit_photo' else back_kb())
    elif step == 'create_event_photo':
        st['event_photo'] = message.photo[-1].file_id
        st['step'] = 'create_event_review'
        await send_event_review(message.chat.id, st)

@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    cur = st.get('step')
    if cur == 'create_event_location':
        st['event_lat'], st['event_lon'] = message.location.latitude, message.location.longitude
        st['step'] = 'create_event_location_name'
        await message.answer("📍 Вкажи адресу/місце (опціонально):", reply_markup=back_kb())
    elif cur == 'search_geo_wait_location':
        events = await find_events_near(message.location.latitude, message.location.longitude, 10.0, 5)
        await render_events_list(message, events, uid, "Поруч")

@dp.callback_query(F.data.startswith("cal:nav:"))
async def cal_nav(call: types.CallbackQuery):
    y, m = map(int, call.data.split(":")[2].split("-"))
    try: await call.message.edit_reply_markup(reply_markup=month_kb(y, m))
    except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("cal:date:"))
async def cal_pick_date(call: types.CallbackQuery):
    dstr = call.data.split(":")[2]
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['picked_date'] = datetime.strptime(dstr, "%Y-%m-%d").date()
    st['step'] = 'create_event_time'
    await call.message.answer("⏰ Введіть час у форматі HH:MM (наприклад, 19:30).", reply_markup=back_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("myevents:filter:"))
async def filter_my_events(call: types.CallbackQuery):
    uid = call.from_user.id
    filter_kind = call.data.split(":")[2]
    events = await list_user_events(uid, filter_kind)
    status_names = {"active": "🟢 Активні", "finished": "✅ Проведені", "deleted": "🗑 Скасовані"}
    
    if not events:
        await call.message.edit_text(f"У категорії «{status_names.get(filter_kind)}» подій немає.", reply_markup=myevents_filter_kb())
        return
        
    text = f"<b>{status_names.get(filter_kind)} події:</b>\n\n"
    for i, ev in enumerate(events[:10], 1):
        dt_str = ev['date'].strftime('%d.%m') if ev['date'] else "—"
        text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\n"
        
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=myevents_filter_kb())

# ==========================================
# 5. СТРІЧКА ПОДІЙ (ТІНДЕР-СВАЙПИ)
# ==========================================
@dp.message(F.text.in_(["🃏 Шукати івенти (Стрічка)", "🃏 Шукати івенти"]))
async def swipe_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['step'] = 'swipe_choose_city'
    await message.answer("📍 Обери місто, де хочеш подивитися івенти:", reply_markup=swipe_city_kb())

@dp.message(lambda msg: user_states.get(msg.from_user.id, {}).get('step') == 'swipe_choose_city')
async def swipe_fetch_city(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    city = message.text.strip()
    
    if city == "⬅️ Назад":
        user = await get_user_from_db(uid)
        st['step'] = 'menu'
        await message.answer("🏠 Головне меню", reply_markup=main_menu(is_guest=not bool(user)))
        return

    # Завантажуємо івенти з БД і зберігаємо їх в "оперативну пам'ять" юзера
    events = await get_events_for_swipe(city)
    
    if not events:
        await message.answer(f"😕 У місті {city} поки немає активних подій. Спробуй інше!", reply_markup=swipe_city_kb())
        return

    # Зберігаємо список івентів та індекс поточного
    st['swipe_list'] = [dict(ev) for ev in events] 
    st['swipe_index'] = 0
    st['step'] = 'swiping'
    
    # Змінюємо клавіатуру на звичайну, щоб не заважала
    user = await get_user_from_db(uid)
    await message.answer(f"🚀 Знайдено {len(events)} подій у {city}. Поїхали!", reply_markup=main_menu(is_guest=not bool(user)))
    
    # Показуємо першу картку
    await show_swipe_card(message.chat.id, uid)

async def show_swipe_card(chat_id: int, uid: int, message_to_delete: int = None):
    st = user_states.get(uid, {})
    events = st.get('swipe_list', [])
    idx = st.get('swipe_index', 0)

    # Видаляємо попередню картку, якщо вона була (для ефекту свайпу)
    if message_to_delete:
        try:
            await bot.delete_message(chat_id, message_to_delete)
        except Exception:
            pass

    if idx >= len(events):
        await bot.send_message(chat_id, "🏁 Ти переглянув усі актуальні івенти в цьому місті!\nЗазирни сюди пізніше 😉")
        st['step'] = 'menu'
        return

    ev = events[idx]
    dt_str = ev['date'].strftime('%d.%m.%Y %H:%M') if ev['date'] else "—"
    org_name = ev.get('organizer_name', 'Невідомий')
    
    card = (
        f"🔥 <b>{ev['title']}</b>\n"
        f"👤 Орг: {org_name}\n"
        f"📅 {dt_str} | 📍 {ev['location']}\n\n"
        f"📝 {ev['description'][:200]}...\n\n"
        f"👥 Вільних місць: {ev['needed_count']}"
    )
    
    kb = swipe_action_kb(ev['id'])
    
    if ev.get('photo'):
        await bot.send_photo(chat_id, ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
    else:
        await bot.send_message(chat_id, card, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "swipe:next")
async def swipe_next_callback(call: types.CallbackQuery):
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    
    # Збільшуємо лічильник і показуємо наступну картку
    st['swipe_index'] = st.get('swipe_index', 0) + 1
    await show_swipe_card(call.message.chat.id, uid, message_to_delete=call.message.message_id)
    await call.answer()

# ==========================================
# ЗАПУСК БОТА
# ==========================================
async def main():
    logging.info("🚀 Запускаємо Findsy Bot...")
    await init_db_pool()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

