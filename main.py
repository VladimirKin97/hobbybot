import asyncio
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

from config import BOT_TOKEN
from database import *
from keyboards import *
from utils import _now_utc, parse_user_datetime, parse_time_hhmm

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states: dict[int, dict] = {}

# --- НОВИЙ КРАСИВИЙ ДИЗАЙН КАРТОК ---
def format_event_card(ev: dict) -> str:
    dt_str = ev['date'].strftime('%d.%m.%Y о %H:%M') if ev['date'] else "—"
    org_rating = f"⭐ {ev.get('org_rating'):.1f}/10" if ev.get('org_rating') else "⭐ Новачок"
    title = str(ev['title']).upper()
    
    return (
        f"🎟 <b>{title}</b>\n\n"
        f"👤 <b>Організатор:</b> {ev.get('organizer_name', 'Невідомий')} ({org_rating})\n"
        f"📅 <b>Коли:</b> {dt_str}\n"
        f"📍 <b>Де:</b> {ev['location']}\n\n"
        f"💬 <b>Про подію:</b>\n<i>{str(ev['description'])[:300]}</i>\n\n"
        f"🔥 <b>Шукаємо ще:</b> {ev['needed_count']} людей"
    )

async def render_events_list(message: types.Message, events: list, uid: int, error_text: str):
    if not events:
        await message.answer(f"😕 {error_text} нічого не знайдено.", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        return
    await message.answer(f"🎉 Знайдено {len(events)} подій:")
    for ev in events:
        card = format_event_card(ev)
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
        await bot.send_message(chat_id, "🏁 Ти переглянув усі актуальні івенти!\nЗазирни сюди пізніше 😉", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        st['step'] = 'menu'
        return

    ev = events[idx]
    card = format_event_card(ev)
    
    kb = swipe_action_kb(ev['id']) if str(ev['user_id']) != str(uid) else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Це твій івент -> Далі", callback_data="swipe:next")]])
    if ev.get('photo'): await bot.send_photo(chat_id, ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
    else: await bot.send_message(chat_id, card, parse_mode="HTML", reply_markup=kb)

def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%d.%m.%Y о %H:%M') if isinstance(dt, datetime) else "—"
    loc_line = st.get('event_location', "—")
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    title = str(st.get('event_title','—')).upper()
    return (
        f"<b>Перевір дані перед публікацією:</b>\n\n"
        f"🎟 <b>{title}</b>\n"
        f"📅 <b>Коли:</b> {dt_str}\n"
        f"📍 <b>Де:</b> {loc_line}\n"
        f"👥 <b>Заповнено:</b> {filled}/{st.get('capacity','—')} • <b>Шукаємо ще:</b> {st.get('needed_count','—')}"
    )

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    user = await get_user_from_db(uid)
    if user:
        st['step'] = 'menu'
        await message.answer(f"👋 Вітаю, {user['name']}!", reply_markup=main_menu(is_guest=False))
    else:
        st['step'] = 'guest_menu'
        await message.answer("🐧 Привіт! Це Findsy.", reply_markup=main_menu(is_guest=True))

@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text = message.text.strip()
    st = user_states.setdefault(uid, {})
    step = st.get('step', 'guest_menu')

    if "Назад" in text or "Меню" in text:
        user = await get_user_from_db(uid)
        st['step'] = 'menu' if user else 'guest_menu'
        await message.answer("🏠 Головне меню", reply_markup=main_menu(is_guest=not bool(user)))
        return

    # --- ЛОГІКА ЗАЯВКИ (Welcome-меседж) ---
    if step == 'wait_welcome_msg':
        event_id = st.get('join_event_id')
        msg_to_org = text if text != "⏭ Пропустити" else "Хочу долучитися!"
        
        req_id = await create_join_request(event_id, uid, msg_to_org)
        if req_id == -1:
            await message.answer("⚠️ Ти вже подавав заявку на цей івент!", reply_markup=main_menu(is_guest=False))
        else:
            await message.answer("✅ Заявку відправлено організатору! Очікуй підтвердження.", reply_markup=main_menu(is_guest=False))
            ev = await get_event_by_id(event_id)
            org_tg_id = ev['user_id']
            user = await get_user_from_db(uid)
            org_text = (f"🔔 <b>Нова заявка на «{ev['title']}»</b>!\n\n"
                        f"👤 Від: <a href='tg://user?id={uid}'>{user['name']}</a>\n"
                        f"💬 Повідомлення: <i>{msg_to_org}</i>\n\nРішення за тобою:")
            try:
                await bot.send_message(org_tg_id, org_text, parse_mode="HTML", reply_markup=request_decision_kb(req_id))
            except Exception as e:
                logging.error(f"Не зміг відправити пуш оргу: {e}")
        st['step'] = 'menu'
        return

    if "Мої івенти" in text: await message.answer("📦 Обери розділ:", reply_markup=myevents_role_kb()); return
    if "Шукати івенти" in text: st['step'] = 'swipe_choose_city'; await message.answer("📍 Обери місто для пошуку:", reply_markup=swipe_city_kb()); return
    if "Фільтр івентів" in text: st['step'] = 'search_menu'; await message.answer("Як шукаємо події?", reply_markup=search_menu_kb()); return
    if "За ключовим словом" in text: st['step'] = 'search_kw_wait'; await message.answer("Введи слово для пошуку:", reply_markup=back_kb()); return

    if "Поруч зі мною" in text:
        st['step'] = 'search_geo_radius'
        kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="1 км"), types.KeyboardButton(text="5 км"), types.KeyboardButton(text="10 км")], [types.KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
        await message.answer("📍 Обери радіус пошуку:", reply_markup=kb)
        return

    if step == 'search_geo_radius' and text in ["1 км", "5 км", "10 км"]:
        st['search_radius'] = float(text.replace(" км", ""))
        st['step'] = 'search_geo_wait_location'
        await message.answer("📍 Тепер надішли свою поточну геолокацію:", reply_markup=location_choice_kb())
        return

    if "За моїми інтересами" in text:
        user = await get_user_from_db(uid)
        if not user or not user.get('interests'): await message.answer("У тебе не заповнені інтереси 😕", reply_markup=main_menu(is_guest=not bool(user))); return
        interests = user['interests'].split(',')[0].strip()
        await message.answer(f"🔍 Шукаю події за інтересом: <b>{interests}</b>...", parse_mode="HTML")
        events = await find_events_by_kw(interests, limit=5)
        await render_events_list(message, events, uid, f"за інтересом «{interests}»")
        return

    if "Створити профіль" in text or "Зареєструватися" in text: st['step'] = 'name'; await message.answer("📝 Вкажи імʼя або нікнейм:", reply_markup=back_kb()); return

    if "Мій профіль" in text:
        user = await get_user_from_db(uid)
        if user:
            avg = await get_organizer_avg_rating(uid)
            avg_line = f"\n⭐ Рейтинг: {avg:.1f}/10" if avg else "\n⭐ Рейтинг: Новачок"
            caption = f"👤 Профіль:\n📛 {user['name']}\n🏙 {user['city']}\n🎯 {user['interests']}{avg_line}"
            kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text='✏️ Змінити профіль')], [types.KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)
            if user.get('photo'): await message.answer_photo(user['photo'], caption=caption, reply_markup=kb)
            else: await message.answer(caption, reply_markup=kb)
        return

    if "Змінити профіль" in text: st.update({'step': 'edit_name'}); await message.answer("✍️ Нове ім'я (або Пропустити):", reply_markup=skip_back_kb()); return

    if "Створити подію" in text:
        user = await get_user_from_db(uid)
        if not user: await message.answer("⚠️ Спочатку створи профіль.\nВкажи ім'я:", reply_markup=back_kb()); return
        st.clear(); st['step'] = 'create_event_title'; st['creator_name'] = user['name']
        await message.answer("📝 Назва події:", reply_markup=back_kb()); return

    if step == 'swipe_choose_city':
        events = await get_events_for_swipe(text)
        if not events: await message.answer(f"😕 У місті {text} поки немає майбутніх подій.", reply_markup=swipe_city_kb()); return
        st['swipe_list'] = [dict(ev) for ev in events]
        st['swipe_index'] = 0
        st['step'] = 'swiping'
        await message.answer(f"🚀 Поїхали!", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        await show_swipe_card(message.chat.id, uid)
        return

    if step == 'search_kw_wait':
        events = await find_events_by_kw(text, limit=5)
        await render_events_list(message, events, uid, f"За запитом «{text}»")
        st['step'] = 'menu'; return

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

    if step == 'edit_photo' and text == "⏭ Пропустити": st['step'] = 'edit_interests'; await message.answer("🎯 Онови інтереси:", reply_markup=skip_back_kb()); return

    if step in ['interests', 'edit_interests']:
        if text != "⏭ Пропустити": st['interests'] = text
        try:
            await save_user_to_db(uid, "", st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            st['step'] = 'menu'; await message.answer("✅ Збережено!", reply_markup=main_menu(is_guest=False))
        except Exception: await message.answer("❌ Помилка.", reply_markup=main_menu(is_guest=True))
        return

    if step == 'create_event_title': st['event_title'] = text; st['step'] = 'create_event_description'; await message.answer("📄 Опис події:", reply_markup=back_kb()); return
    if step == 'create_event_description': st['event_description'] = text; st['step'] = 'create_event_date'; now = datetime.now(); await message.answer("📅 Дата та час:", reply_markup=month_kb(now.year, now.month)); return

    if step == 'create_event_date':
        dt = parse_user_datetime(text)
        if dt:
            if dt < datetime.now(): await message.answer("⚠️ Не можна створювати подію в минулому! Вкажи майбутню дату та час:", reply_markup=back_kb()); return
            st['event_date'] = dt; st['step'] = 'create_event_city'; await message.answer("🏙 Обери місто проведення:", reply_markup=event_city_kb())
        else: await message.answer("Не впізнав дату.", reply_markup=back_kb())
        return

    if step == 'create_event_time':
        t = parse_time_hhmm(text)
        if t:
            d: date = st.get('picked_date')
            dt = datetime(d.year, d.month, d.day, t[0], t[1])
            if dt < datetime.now(): await message.answer("⚠️ Цей час вже минув! Введи майбутній час:", reply_markup=back_kb()); return
            st['event_date'] = dt; st['step'] = 'create_event_city'; await message.answer("🏙 Обери місто проведення:", reply_markup=event_city_kb())
        else: await message.answer("Формат часу HH:MM", reply_markup=back_kb())
        return

    if step == 'create_event_city': st['event_city'] = text; st['step'] = 'create_event_location'; await message.answer("📍 Тепер вкажи точну адресу (або гео):", reply_markup=location_choice_kb()); return

    if step == 'create_event_location':
        if text == "📝 Ввести адресу текстом": st['step'] = 'create_event_location_name'; await message.answer("Вкажи адресу:", reply_markup=back_kb()); return
        if text == "⏭ Пропустити локацію": st['event_location'] = st.get('event_city', ''); st['step'] = 'create_event_capacity'; await message.answer("👥 Місткість (скільки всього людей):", reply_markup=back_kb()); return
        return

    if step == 'create_event_location_name': st['event_location'] = f"{st.get('event_city', '')}, {text}"; st['step'] = 'create_event_capacity'; await message.answer("👥 Місткість:", reply_markup=back_kb()); return
    if step == 'create_event_capacity':
        if text.isdigit() and int(text) > 0: st['capacity'] = int(text); st['step'] = 'create_event_needed'; await message.answer("👤 Скільки ще шукаєш?", reply_markup=back_kb()); return
    if step == 'create_event_needed':
        if text.isdigit() and 0 < int(text) <= st.get('capacity', 999): st['needed_count'] = int(text); st['step'] = 'create_event_photo'; await message.answer("📸 Фото події", reply_markup=skip_back_kb()); return
    if step == 'create_event_photo' and text == "⏭ Пропустити": st['event_photo'] = None; st['step'] = 'create_event_review'; await message.answer(compose_event_review_text(st), parse_mode="HTML", reply_markup=event_publish_kb()); return

    if step == 'create_event_review':
        if text == '✅ Опублікувати':
            try:
                await save_event_to_db(uid, st.get('creator_name',''), "", st['event_title'], st['event_description'], st['event_date'], st.get('event_location',''), st['capacity'], st['needed_count'], 'active', st.get('event_lat'), st.get('event_lon'), st.get('event_photo'))
                await message.answer("🚀 Подія опублікована!", reply_markup=main_menu(is_guest=False))
            except Exception: await message.answer("❌ Помилка публікації", reply_markup=main_menu(is_guest=False))
            st['step'] = 'menu'
        elif text == '❌ Скасувати': st['step'] = 'menu'; await message.answer("❌ Скасовано.", reply_markup=main_menu(is_guest=False))

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    st = user_states.setdefault(message.from_user.id, {})
    step = st.get('step')
    if step in ('photo', 'edit_photo'): st['photo'] = message.photo[-1].file_id; st['step'] = 'interests' if step == 'photo' else 'edit_interests'; await message.answer("🎯 Інтереси:", reply_markup=skip_back_kb() if step == 'edit_photo' else back_kb())
    elif step == 'create_event_photo': st['event_photo'] = message.photo[-1].file_id; st['step'] = 'create_event_review'; await message.answer_photo(st['event_photo'], caption=compose_event_review_text(st), parse_mode="HTML", reply_markup=event_publish_kb())

@dp.message(F.location)
async def handle_location(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    cur = st.get('step')
    if cur == 'create_event_location':
        st['event_lat'], st['event_lon'] = message.location.latitude, message.location.longitude
        st['event_location'] = f"{st.get('event_city', '')} (За геолокацією)"
        st['step'] = 'create_event_capacity'; await message.answer("👥 Місткість:", reply_markup=back_kb())
    elif cur == 'search_geo_wait_location':
        radius = st.get('search_radius', 10.0)
        await message.answer(f"🔍 Шукаю події в радіусі {radius} км...", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        events = await find_events_near(message.location.latitude, message.location.longitude, radius, limit=10)
        await render_events_list(message, events, uid, f"В радіусі {radius} км")
        st['step'] = 'menu'

@dp.callback_query(F.data.startswith("join:"))
async def join_event_callback(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    uid = call.from_user.id
    user = await get_user_from_db(uid)
    if not user:
        await call.message.answer("⚠️ Тобі потрібно створити профіль, щоб подавати заявки!", reply_markup=main_menu(is_guest=True))
        await call.answer()
        return
    st = user_states.setdefault(uid, {})
    st['join_event_id'] = event_id
    st['step'] = 'wait_welcome_msg'
    await call.message.answer("💬 Напиши коротке повідомлення організатору (наприклад, який у тебе рівень досвіду).\n\nАбо просто натисни «⏭ Пропустити».", reply_markup=skip_back_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("req_yes:"))
async def approve_request_callback(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    req = await get_request_info(req_id)
    if not req or req['status'] != 'pending': await call.answer("Заявка вже оброблена або не існує.", show_alert=True); return
    
    await update_request_status_db(req_id, 'approved')
    await decrement_needed_count(req['event_id'])
    await call.message.edit_text(call.message.html_text + f"\n\n✅ <b>Схвалено!</b>\nНапиши учаснику: <a href='tg://user?id={req['seeker_id']}'>{req['seeker_name']}</a>", parse_mode="HTML")
    
    user = await get_user_from_db(call.from_user.id)
    seeker_text = f"🎉 Твою заявку на <b>{req['event_title']}</b> схвалено!\n\nЗв'яжися з організатором: <a href='tg://user?id={req['organizer_id']}'>{user['name']}</a>"
    try: await bot.send_message(req['seeker_id'], seeker_text, parse_mode="HTML")
    except Exception: pass
    await call.answer()

@dp.callback_query(F.data.startswith("req_no:"))
async def reject_request_callback(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1])
    req = await get_request_info(req_id)
    if not req or req['status'] != 'pending': await call.answer("Заявка вже оброблена.", show_alert=True); return
    
    await update_request_status_db(req_id, 'rejected')
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>Відхилено.</b>", parse_mode="HTML")
    
    seeker_text = f"😕 На жаль, твою заявку на <b>{req['event_title']}</b> відхилено. Спробуй знайти інший івент!"
    try: await bot.send_message(req['seeker_id'], seeker_text, parse_mode="HTML")
    except Exception: pass
    await call.answer()

@dp.callback_query(F.data.startswith("myevents:role:"))
async def myevents_role_callback(call: types.CallbackQuery):
    role = call.data.split(":")[2]
    uid = call.from_user.id
    
    if role == "org":
        events = await list_user_events(uid, 'active')
        if not events: await call.message.edit_text("Ти ще не створив жодної активної події 🤷‍♂️"); return
        text = "<b>👑 Ти Організатор:</b>\n\n"
        for i, ev in enumerate(events, 1):
            dt_str = ev['date'].strftime('%d.%m %H:%M')
            filled = ev['capacity'] - ev['needed_count']
            text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\n👥 Заявок: {filled}/{ev['capacity']}\n\n"
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=myevents_filter_kb())
        
    elif role == "part":
        events = await get_user_participations(uid)
        if not events: await call.message.edit_text("Ти ще не подавав заявки на івенти 🤷‍♂️"); return
        text = "<b>🙋‍♂️ Ти Учасник:</b>\n\n"
        status_emoji = {"pending": "⏳ Розглядається", "approved": "✅ Схвалено", "rejected": "❌ Відхилено"}
        for i, ev in enumerate(events, 1):
            dt_str = ev['date'].strftime('%d.%m %H:%M')
            st_emoji = status_emoji.get(ev['req_status'], ev['req_status'])
            text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\nСтатус: {st_emoji}\n\n"
        await call.message.edit_text(text, parse_mode="HTML")

@dp.callback_query(F.data.startswith("myevents:filter:"))
async def filter_my_events(call: types.CallbackQuery):
    filter_kind = call.data.split(":")[2]
    events = await list_user_events(call.from_user.id, filter_kind)
    status_names = {"active": "🟢 Активні", "finished": "✅ Проведені", "deleted": "🗑 Скасовані"}
    if not events: await call.message.edit_text(f"У категорії «{status_names.get(filter_kind)}» подій немає.", reply_markup=myevents_filter_kb()); return
    text = f"<b>{status_names.get(filter_kind)} події:</b>\n\n"
    for i, ev in enumerate(events[:10], 1):
        dt_str = ev['date'].strftime('%d.%m') if ev['date'] else "—"
        text += f"{i}. <b>{ev['title']}</b> (📅 {dt_str})\n"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=myevents_filter_kb())

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

@dp.callback_query(F.data == "swipe:next")
async def swipe_next_callback(call: types.CallbackQuery):
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['swipe_index'] = st.get('swipe_index', 0) + 1
    await show_swipe_card(call.message.chat.id, uid, message_to_delete=call.message.message_id)
    await call.answer()

async def main():
    logging.info("🚀 Запускаємо Findsy Bot...")
    await init_db_pool()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
