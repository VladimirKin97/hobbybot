import asyncio
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

from config import BOT_TOKEN
from database import (init_db_pool, get_user_from_db, save_user_to_db, find_events_near, 
                      save_event_to_db, get_organizer_avg_rating, list_user_events, 
                      find_events_by_kw, get_events_for_swipe)
from keyboards import (main_menu, back_kb, skip_back_kb, search_menu_kb, location_choice_kb, 
                       month_kb, event_publish_kb, myevents_filter_kb, event_join_kb, 
                       swipe_city_kb, swipe_action_kb, event_city_kb)
from utils import _now_utc, parse_user_datetime, parse_time_hhmm

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states: dict[int, dict] = {}

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
async def render_events_list(message: types.Message, events: list, uid: int, error_text: str):
    if not events:
        await message.answer(f"😕 {error_text} нічого не знайдено.", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        return
    await message.answer(f"🎉 Знайдено {len(events)} подій:")
    for ev in events:
        dt_str = ev['date'].strftime('%d.%m.%Y %H:%M') if ev['date'] else "—"
        card = (f"🎯 <b>{ev['title']}</b>\n👤 Орг: {ev.get('organizer_name', 'Невідомий')}\n"
                f"📅 {dt_str}\n📍 {ev['location']}\n\n📝 {ev['description'][:200]}\n👥 Шукають ще: {ev['needed_count']}")
        kb = event_join_kb(ev['id']) if str(ev['user_id']) != str(uid) else None
        if ev['photo']: await message.answer_photo(ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
        else: await message.answer(card, parse_mode="HTML", reply_markup=kb)

async def show_swipe_card(chat_id: int, uid: int, message_to_delete: int = None):
    st = user_states.get(uid, {})
    events = st.get('swipe_list', [])
    idx = st.get('swipe_index', 0)
    if message_to_delete:
        try: await bot.delete_message(chat_id, message_to_delete)
        except: pass

    if idx >= len(events):
        await bot.send_message(chat_id, "🏁 Ти переглянув усі актуальні івенти!\nЗазирни сюди пізніше 😉")
        st['step'] = 'menu'
        return

    ev = events[idx]
    dt_str = ev['date'].strftime('%d.%m.%Y %H:%M') if ev['date'] else "—"
    card = (f"🔥 <b>{ev['title']}</b>\n👤 Орг: {ev.get('organizer_name', 'Невідомий')}\n"
            f"📅 {dt_str} | 📍 {ev['location']}\n\n📝 {ev['description'][:200]}\n👥 Вільних місць: {ev['needed_count']}")
    
    if ev.get('photo'): await bot.send_photo(chat_id, ev['photo'], caption=card, parse_mode="HTML", reply_markup=swipe_action_kb(ev['id']))
    else: await bot.send_message(chat_id, card, parse_mode="HTML", reply_markup=swipe_action_kb(ev['id']))

def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%Y-%m-%d %H:%M') if isinstance(dt, datetime) else "—"
    loc_line = st.get('event_location', "—")
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    return (f"<b>Перевір дані перед публікацією</b>\n📝 {st.get('event_title','—')}\n"
            f"📅 {dt_str}\n📍 {loc_line}\n👥 Заповнено: {filled}/{st.get('capacity','—')} • шукаємо ще: {st.get('needed_count','—')}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    user = await get_user_from_db(uid)
    if user:
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}! Обери дію:", reply_markup=main_menu(is_guest=False))
    else:
        st['step'] = 'guest_menu'
        await message.answer("🐧 Привіт! Це Findsy. Можеш оглянути івенти або зареєструватися!", reply_markup=main_menu(is_guest=True))

# --- СПЕЦИФІЧНІ КНОПКИ (Мають бути ВИЩЕ за handle_text) ---
@dp.message(F.text == "📦 Мої івенти")
async def my_events_cmd(message: types.Message):
    uid = message.from_user.id
    events = await list_user_events(uid, 'active')
    if not events:
        await message.answer("У тебе поки немає активних подій 🤷‍♂️", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        return
    text = "<b>📦 Твої активні події:</b>\n\n"
    for i, ev in enumerate(events, 1):
        dt_str = ev['date'].strftime('%d.%m %H:%M') if ev['date'] else "—"
        text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\n"
    await message.answer(text, parse_mode="HTML", reply_markup=myevents_filter_kb())

@dp.message(F.text.in_(["🃏 Шукати івенти (Стрічка)", "🃏 Шукати івенти"]))
async def swipe_start(message: types.Message):
    user_states.setdefault(message.from_user.id, {})['step'] = 'swipe_choose_city'
    await message.answer("📍 Обери місто для пошуку:", reply_markup=swipe_city_kb())

@dp.message(F.text.in_(["🎛 Фільтр івентів (Гость)", "🎛 Фільтр івентів"]))
async def filter_menu_start(message: types.Message):
    user_states.setdefault(message.from_user.id, {})['step'] = 'search_menu'
    await message.answer("Як шукаємо події?", reply_markup=search_menu_kb())

@dp.message(F.text == "🔎 За ключовим словом")
async def search_kw_start(message: types.Message):
    user_states.setdefault(message.from_user.id, {})['step'] = 'search_kw_wait'
    await message.answer("Введи слово для пошуку:", reply_markup=back_kb())

@dp.message(F.text == "🔮 За моїми інтересами")
async def search_by_interests(message: types.Message):
    uid = message.from_user.id
    user = await get_user_from_db(uid)
    if not user or not user.get('interests'):
        await message.answer("У тебе не заповнені інтереси в профілі 😕", reply_markup=main_menu(is_guest=not bool(user)))
        return
    interests = user['interests'].split(',')[0].strip()
    await message.answer(f"🔍 Шукаю події за інтересом: <b>{interests}</b>...", parse_mode="HTML")
    events = await find_events_by_kw(interests, limit=5)
    await render_events_list(message, events, uid, f"за інтересом «{interests}»")

# --- ЗАГАЛЬНИЙ ОБРОБНИК (FSM) ---
@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    step = st.get('step', 'guest_menu')

    if text in ["⬅️ Назад", "🏠 Меню"]:
        user = await get_user_from_db(uid)
        st['step'] = 'menu' if user else 'guest_menu'
        await message.answer("🏠 Головне меню", reply_markup=main_menu(is_guest=not bool(user)))
        return

    if step == 'swipe_choose_city':
        events = await get_events_for_swipe(text)
        if not events:
            await message.answer(f"😕 У місті {text} поки немає подій.", reply_markup=swipe_city_kb())
            return
        st['swipe_list'] = [dict(ev) for ev in events]
        st['swipe_index'] = 0
        st['step'] = 'swiping'
        await message.answer(f"🚀 Поїхали!", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        await show_swipe_card(message.chat.id, uid)
        return

    if step == 'search_kw_wait':
        events = await find_events_by_kw(text, limit=5)
        await render_events_list(message, events, uid, f"За запитом «{text}»")
        st['step'] = 'menu'
        return

    if text in ["👤 Створити профіль / Реєстрація", "👤 Зареєструватися"]:
        st['step'] = 'name'
        await message.answer("📝 Вкажи імʼя або нікнейм:", reply_markup=back_kb())
        return

    if text == "👤 Мій профіль":
        user = await get_user_from_db(uid)
        if user:
            avg = await get_organizer_avg_rating(uid)
            avg_line = f"\n⭐ Рейтинг: {avg:.1f}/10" if avg else ""
            caption = f"👤 Профіль:\n📛 {user['name']}\n🏙 {user['city']}\n🎯 {user['interests']}{avg_line}"
            kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text='✏️ Змінити профіль')], [types.KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
            if user.get('photo'): await message.answer_photo(user['photo'], caption=caption, reply_markup=kb)
            else: await message.answer(caption, reply_markup=kb)
        return

    if text == "✏️ Змінити профіль":
        st.update({'step': 'edit_name'})
        await message.answer("✍️ Нове ім'я (або Пропустити):", reply_markup=skip_back_kb())
        return

    if step in ['name', 'edit_name']:
        if text != "⏭ Пропустити": st['name'] = text
        st['step'] = 'city' if step == 'name' else 'edit_city'
        await message.answer("🏙 Введи місто:", reply_markup=skip_back_kb() if step == 'edit_name' else back_kb())
        return

    if step in ['city', 'edit_city']:
        if text != "⏭ Пропустити": st['city'] = text
        st['step'] = 'photo' if step == 'city' else 'edit_photo'
        await message.answer("🖼 Надішли фото профілю (або пропусти):", reply_markup=skip_back_kb() if step == 'edit_city' else back_kb())
        return

    if step == 'edit_photo' and text == "⏭ Пропустити":
        st['step'] = 'edit_interests'
        await message.answer("🎯 Онови інтереси:", reply_markup=skip_back_kb())
        return

    if step in ['interests', 'edit_interests']:
        if text != "⏭ Пропустити": st['interests'] = text
        try:
            await save_user_to_db(uid, "", st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            st['step'] = 'menu'
            await message.answer("✅ Збережено!", reply_markup=main_menu(is_guest=False))
        except Exception:
            await message.answer("❌ Помилка.", reply_markup=main_menu(is_guest=True))
        return

    if text == "➕ Створити подію":
        user = await get_user_from_db(uid)
        if not user:
            st['step'] = 'name'
            await message.answer("⚠️ Спочатку створи профіль.\nВкажи ім'я:", reply_markup=back_kb())
            return
        st.clear(); st['step'] = 'create_event_title'; st['creator_name'] = user['name']
        await message.answer("📝 Назва події:", reply_markup=back_kb())
        return

    if step == 'create_event_title':
        st['event_title'] = text
        st['step'] = 'create_event_description'
        await message.answer("📄 Опис події:", reply_markup=back_kb())
        return

    if step == 'create_event_description':
        st['event_description'] = text
        st['step'] = 'create_event_date'
        now = datetime.now()
        await message.answer("📅 Дата та час:", reply_markup=month_kb(now.year, now.month))
        return

    if step == 'create_event_date':
        dt = parse_user_datetime(text)
        if dt:
            st['event_date'] = dt
            st['step'] = 'create_event_city'  # НОВИЙ КРОК: МІСТО
            await message.answer("🏙 Обери місто проведення:", reply_markup=event_city_kb())
        return

    if step == 'create_event_time':
        t = parse_time_hhmm(text)
        if t:
            d: date = st.get('picked_date')
            st['event_date'] = datetime(d.year, d.month, d.day, t[0], t[1])
            st['step'] = 'create_event_city'  # НОВИЙ КРОК: МІСТО
            await message.answer("🏙 Обери місто проведення:", reply_markup=event_city_kb())
        return

    if step == 'create_event_city':
        st['event_city'] = text
        st['step'] = 'create_event_location'
        await message.answer("📍 Тепер вкажи точну адресу (або гео):", reply_markup=location_choice_kb())
        return

    if step == 'create_event_location':
        if text == "📝 Ввести адресу текстом":
            st['step'] = 'create_event_location_name'
            await message.answer("Вкажи адресу:", reply_markup=back_kb())
            return
        if text == "⏭ Пропустити локацію":
            st['event_location'] = st.get('event_city', '') # Зберігаємо хоча б місто
            st['step'] = 'create_event_capacity'
            await message.answer("👥 Місткість (скільки всього людей):", reply_markup=back_kb())
            return
        return

    if step == 'create_event_location_name':
        city = st.get('event_city', '')
        st['event_location'] = f"{city}, {text}" # Склеюємо Місто + Адресу
        st['step'] = 'create_event_capacity'
        await message.answer("👥 Місткість:", reply_markup=back_kb())
        return

    if step == 'create_event_capacity':
        if text.isdigit() and int(text) > 0:
            st['capacity'] = int(text)
            st['step'] = 'create_event_needed'
            await message.answer("👤 Скільки ще шукаєш?", reply_markup=back_kb())
        return

    if step == 'create_event_needed':
        if text.isdigit() and 0 < int(text) <= st.get('capacity', 999):
            st['needed_count'] = int(text)
            st['step'] = 'create_event_photo'
            await message.answer("📸 Фото події", reply_markup=skip_back_kb())
        return

    if step == 'create_event_photo' and text == "⏭ Пропустити":
        st['event_photo'] = None
        st['step'] = 'create_event_review'
        caption = compose_event_review_text(st)
        await message.answer(caption, parse_mode="HTML", reply_markup=event_publish_kb())
        return

    if step == 'create_event_review':
        if text == '✅ Опублікувати':
            try:
                await save_event_to_db(uid, st.get('creator_name',''), "", st['event_title'], st['event_description'],
                                       st['event_date'], st.get('event_location',''), st['capacity'], st['needed_count'],
                                       'active', st.get('event_lat'), st.get('event_lon'), st.get('event_photo'))
                await message.answer("🚀 Подія опублікована!", reply_markup=main_menu(is_guest=False))
            except Exception:
                await message.answer("❌ Помилка публікації", reply_markup=main_menu(is_guest=False))
            st['step'] = 'menu'
        elif text == '❌ Скасувати':
            st['step'] = 'menu'
            await message.answer("❌ Скасовано.", reply_markup=main_menu(is_guest=False))

# --- ІНЛАЙН КНОПКИ ТА МЕДІА ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    st = user_states.setdefault(message.from_user.id, {})
    step = st.get('step')
    if step in ('photo', 'edit_photo'):
        st['photo'] = message.photo[-1].file_id
        st['step'] = 'interests' if step == 'photo' else 'edit_interests'
        await message.answer("🎯 Інтереси:", reply_markup=skip_back_kb() if step == 'edit_photo' else back_kb())
    elif step == 'create_event_photo':
        st['event_photo'] = message.photo[-1].file_id
        st['step'] = 'create_event_review'
        await message.answer_photo(st['event_photo'], caption=compose_event_review_text(st), parse_mode="HTML", reply_markup=event_publish_kb())

@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    cur = st.get('step')
    if cur == 'create_event_location':
        st['event_lat'], st['event_lon'] = message.location.latitude, message.location.longitude
        city = st.get('event_city', '')
        st['event_location'] = f"{city} (За геолокацією)"
        st['step'] = 'create_event_capacity'
        await message.answer("👥 Місткість:", reply_markup=back_kb())
    elif cur == 'search_geo_wait_location':
        events = await find_events_near(message.location.latitude, message.location.longitude, 10.0, 5)
        await render_events_list(message, events, uid, "Поруч")

@dp.callback_query(F.data.startswith("cal:"))
async def cal_handler(call: types.CallbackQuery):
    data = call.data.split(":")
    if data[1] == "nav":
        y, m = map(int, data[2].split("-"))
        try: await call.message.edit_reply_markup(reply_markup=month_kb(y, m))
        except: pass
    elif data[1] == "date":
        st = user_states.setdefault(call.from_user.id, {})
        st['picked_date'] = datetime.strptime(data[2], "%Y-%m-%d").date()
        st['step'] = 'create_event_time'
        await call.message.answer("⏰ Введіть час HH:MM:", reply_markup=back_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("myevents:filter:"))
async def filter_my_events(call: types.CallbackQuery):
    filter_kind = call.data.split(":")[2]
    events = await list_user_events(call.from_user.id, filter_kind)
    status_names = {"active": "🟢 Активні", "finished": "✅ Проведені", "deleted": "🗑 Скасовані"}
    if not events:
        await call.message.edit_text(f"У категорії «{status_names.get(filter_kind)}» подій немає.", reply_markup=myevents_filter_kb())
        return
    text = f"<b>{status_names.get(filter_kind)} події:</b>\n\n"
    for i, ev in enumerate(events[:10], 1):
        dt_str = ev['date'].strftime('%d.%m') if ev['date'] else "—"
        text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\n"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=myevents_filter_kb())

@dp.callback_query(F.data == "swipe:next")
async def swipe_next_callback(call: types.CallbackQuery):
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['swipe_index'] = st.get('swipe_index', 0) + 1
    await show_swipe_card(call.message.chat.id, uid, message_to_delete=call.message.message_id)
    await call.answer()

# --- ЗАПУСК ---
async def main():
    logging.info("🚀 Запускаємо Findsy Bot...")
    await init_db_pool()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
