import asyncio
import logging
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command

from config import BOT_TOKEN
from database import *
from keyboards import *
from utils import _now_utc, parse_user_datetime, parse_time_hhmm

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states: dict[int, dict] = {}
sent_reminders = set()

# === ТВІЙ TELEGRAM ID ДЛЯ ПАНЕЛІ АДМІНА ===
# Введи в боті /admin, щоб дізнатися свій ID, і встав його сюди:
ADMIN_ID = 0 

# --- ФОНОВІ ПРОЦЕСИ ---
async def reminders_loop():
    while True:
        try:
            async with db_pool.acquire() as conn:
                upcoming = await conn.fetch("SELECT * FROM events WHERE status='active' AND date >= now() AND date <= now() + interval '25 hours'")
            for ev in upcoming:
                ev_id = ev['id']
                hours_left = (ev['date'].replace(tzinfo=None) - datetime.now()).total_seconds() / 3600
                if 23.5 <= hours_left <= 24.5 and f"{ev_id}_24h" not in sent_reminders:
                    await send_reminder(ev, "24 години"); sent_reminders.add(f"{ev_id}_24h")
                elif 0.5 <= hours_left <= 1.5 and f"{ev_id}_1h" not in sent_reminders:
                    await send_reminder(ev, "1 годину"); sent_reminders.add(f"{ev_id}_1h")
        except Exception as e: logging.error(f"Помилка в ремайндер-лупі: {e}")
        await asyncio.sleep(60 * 10)

async def finish_events_loop():
    while True:
        try:
            past_events = await get_past_active_events()
            for ev in past_events:
                await mark_event_finished(ev['id'])
                participants = await get_approved_participants(ev['id'])
                for p in participants:
                    kb = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text=str(i), callback_data=f"rate:{ev['id']}:{ev['user_id']}:{i}") for i in range(1, 6)],
                        [types.InlineKeyboardButton(text=str(i), callback_data=f"rate:{ev['id']}:{ev['user_id']}:{i}") for i in range(6, 11)]
                    ])
                    text = f"🏁 Подія <b>{ev['title']}</b> завершилась!\n\nОціни, як все пройшло та наскільки крутим був організатор (від 1 до 10):"
                    try: await bot.send_message(p['telegram_id'], text, parse_mode="HTML", reply_markup=kb)
                    except: pass
        except Exception as e: logging.error(f"Помилка в циклі завершення подій: {e}")
        await asyncio.sleep(60 * 30)

async def send_reminder(ev: dict, time_str: str):
    title = str(ev['title']).upper()
    text = f"⏰ <b>НАГАДУВАННЯ!</b>\nПодія <b>🎟 {title}</b> почнеться вже через {time_str}!"
    try: await bot.send_message(ev['user_id'], text, parse_mode="HTML")
    except: pass
    participants = await get_approved_participants(ev['id'])
    for p in participants:
        try: await bot.send_message(p['telegram_id'], text, parse_mode="HTML")
        except: pass

def format_event_card(ev: dict, show_org_link: bool = False) -> str:
    dt_str = ev['date'].strftime('%d.%m.%Y о %H:%M') if ev['date'] else "—"
    org_rating = f"⭐ {ev.get('org_rating'):.1f}/10" if ev.get('org_rating') else "⭐ Новачок"
    title = str(ev.get('title', 'Івент')).upper()
    org_name = ev.get('organizer_name', 'Невідомий')
    if show_org_link and ev.get('user_id'): org_display = f"<a href='tg://user?id={ev['user_id']}'>{org_name}</a> ({org_rating})"
    else: org_display = f"{org_name} ({org_rating})"
        
    return (f"🎟 <b>{title}</b>\n\n👤 <b>Організатор:</b> {org_display}\n📅 <b>Коли:</b> {dt_str}\n"
            f"📍 <b>Де:</b> {ev.get('location', '—')}\n\n💬 <b>Про подію:</b>\n<i>{str(ev.get('description', '—'))[:300]}</i>\n\n"
            f"👥 <b>Всього людей на події:</b> {ev.get('capacity', '—')}\n🔥 <b>Залишилося вільних місць:</b> {ev.get('needed_count', 0)}")

async def render_events_list(message: types.Message, events: list, uid: int, error_text: str):
    if not events: return await message.answer(f"😕 {error_text} нічого не знайдено.", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
    await message.answer(f"🎉 Знайдено {len(events)} подій:")
    for ev in events:
        card = format_event_card(ev)
        kb = event_join_kb(ev['id']) if str(ev['user_id']) != str(uid) else None
        if ev.get('photo'): await message.answer_photo(ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
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
        st['step'] = 'menu'; return
    ev = events[idx]
    card = format_event_card(ev)
    kb = swipe_action_kb(ev['id']) if str(ev['user_id']) != str(uid) else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Це твій івент -> Далі", callback_data="swipe:next")]])
    if ev.get('photo'): await bot.send_photo(chat_id, ev['photo'], caption=card, parse_mode="HTML", reply_markup=kb)
    else: await bot.send_message(chat_id, card, parse_mode="HTML", reply_markup=kb)

def compose_event_review_text(st: dict) -> str:
    dt = st.get('event_date')
    dt_str = dt.strftime('%d.%m.%Y о %H:%M') if isinstance(dt, datetime) else "—"
    filled = max((st.get('capacity',0) or 0) - (st.get('needed_count',0) or 0), 0)
    title = str(st.get('event_title','—')).upper()
    return (f"<b>Перевір дані перед публікацією:</b>\n\n🎟 <b>{title}</b>\n📅 <b>Коли:</b> {dt_str}\n"
            f"📍 <b>Де:</b> {st.get('event_location', '—')}\n👥 <b>Заповнено:</b> {filled}/{st.get('capacity','—')} • <b>Шукаємо ще:</b> {st.get('needed_count','—')}")

# --- АДМІН ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    uid = message.from_user.id
    if uid != ADMIN_ID:
        await message.answer(f"🔒 Немає доступу.\nТвій Telegram ID: <code>{uid}</code>\n<i>(Додай його в ADMIN_ID у коді, щоб отримати доступ)</i>", parse_mode="HTML")
        return
    
    stats = await get_admin_stats()
    text = (f"📊 <b>Панель Адміністратора Findsy:</b>\n\n"
            f"👥 Всього користувачів: <b>{stats['users']}</b>\n"
            f"🎟 Активних подій: <b>{stats['events']}</b>\n"
            f"📝 Заявок: <b>{stats['requests']}</b>\n"
            f"🚨 Скарг: <b>{stats['reports']}</b>")
    await message.answer(text, parse_mode="HTML")

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    st = user_states.setdefault(uid, {})
    st['last_activity'] = _now_utc()
    user = await get_user_from_db(uid)
    if user: st['step'] = 'menu'; await message.answer(f"👋 Вітаю, {user['name']}!", reply_markup=main_menu(is_guest=False))
    else: st['step'] = 'guest_menu'; await message.answer("🐧 Привіт! Це Findsy.", reply_markup=main_menu(is_guest=True))

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

    # --- ЛОГІКА СКАРГ (REPORT) ---
    if step == 'wait_report_reason':
        ev_id = st.get('report_event_id')
        await save_report_db(uid, ev_id, text)
        await message.answer("✅ Скаргу прийнято! Модератори перевірять цю подію.", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        st['step'] = 'menu'
        return

    if step == 'wait_welcome_msg':
        event_id = st.get('join_event_id')
        msg_to_org = text if text != "⏭ Пропустити" else "Хочу долучитися!"
        req_id = await create_join_request(event_id, uid, msg_to_org)
        if req_id == -1: await message.answer("⚠️ Ти вже подавав заявку на цей івент!", reply_markup=main_menu(is_guest=False))
        else:
            await message.answer("✅ Заявку відправлено організатору! Очікуй підтвердження.", reply_markup=main_menu(is_guest=False))
            ev = await get_event_by_id(event_id)
            user = await get_user_from_db(uid)
            org_text = (f"🔔 <b>Нова заявка на «{ev['title']}»</b>!\n\n👤 Від: <a href='tg://user?id={uid}'>{user['name']}</a>\n💬 Повідомлення: <i>{msg_to_org}</i>\n\nРішення за тобою:")
            try: await bot.send_message(ev['user_id'], org_text, parse_mode="HTML", reply_markup=request_decision_kb(req_id))
            except: pass
        st['step'] = 'menu'; return

    if "Мої івенти" in text: await message.answer("📦 Обери розділ:", reply_markup=myevents_role_kb()); return
    if "Всі івенти в місті" in text: st['step'] = 'swipe_choose_city'; await message.answer("📍 Обери місто для пошуку:", reply_markup=swipe_city_kb()); return
    if "Фільтр івентів" in text: st['step'] = 'search_menu'; await message.answer("Як шукаємо події?", reply_markup=search_menu_kb()); return
    if "За ключовим словом" in text: st['step'] = 'search_kw_wait'; await message.answer("Введи слово для пошуку:", reply_markup=back_kb()); return
    if "Поруч зі мною" in text: st['step'] = 'search_geo_radius'; kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="1 км"), types.KeyboardButton(text="5 км"), types.KeyboardButton(text="10 км")], [types.KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True); await message.answer("📍 Обери радіус пошуку:", reply_markup=kb); return

    if step == 'search_geo_radius' and text in ["1 км", "5 км", "10 км"]: st['search_radius'] = float(text.replace(" км", "")); st['step'] = 'search_geo_wait_location'; await message.answer("📍 Тепер надішли свою поточну геолокацію:", reply_markup=location_choice_kb()); return

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
    if "Мої контакти" in text: await message.answer("👥 Тут скоро будуть зберігатися посилання на всіх учасників та організаторів, з якими ти взаємодіяв!", reply_markup=main_menu(is_guest=False)); return

    if "Створити подію" in text:
        user = await get_user_from_db(uid)
        if not user: await message.answer("⚠️ Спочатку створи профіль.\nВкажи ім'я:", reply_markup=back_kb()); return
        st.clear(); st['step'] = 'create_event_title'; st['creator_name'] = user['name']
        await message.answer("📝 <b>Назва події:</b>\n\n<i>Приклад: Гра в теніс на вихідних.</i>", parse_mode="HTML", reply_markup=back_kb()); return

    if step == 'swipe_choose_city':
        events = await get_events_for_swipe(text)
        if not events: await message.answer(f"😕 У місті {text} поки немає майбутніх подій.", reply_markup=swipe_city_kb()); return
        st['swipe_list'] = [dict(ev) for ev in events]; st['swipe_index'] = 0; st['step'] = 'swiping'
        await message.answer(f"🚀 Поїхали!", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        await show_swipe_card(message.chat.id, uid); return

    if step == 'search_kw_wait': events = await find_events_by_kw(text, limit=5); await render_events_list(message, events, uid, f"За запитом «{text}»"); st['step'] = 'menu'; return

    if step in ['name', 'edit_name']:
        if text != "⏭ Пропустити": st['name'] = text
        st['step'] = 'city' if step == 'name' else 'edit_city'; await message.answer("🏙 Введи місто:", reply_markup=skip_back_kb() if step == 'edit_name' else back_kb()); return
    if step in ['city', 'edit_city']:
        if text != "⏭ Пропустити": st['city'] = text
        st['step'] = 'photo' if step == 'city' else 'edit_photo'; await message.answer("🖼 Надішли фото профілю (або пропусти):", reply_markup=skip_back_kb() if step == 'edit_city' else back_kb()); return
    if step == 'edit_photo' and text == "⏭ Пропустити": st['step'] = 'edit_interests'; await message.answer("🎯 Онови інтереси:", reply_markup=skip_back_kb()); return
    if step in ['interests', 'edit_interests']:
        if text != "⏭ Пропустити": st['interests'] = text
        try:
            await save_user_to_db(uid, "", st.get('name',''), st.get('city',''), st.get('photo',''), st.get('interests',''))
            st['step'] = 'menu'; await message.answer("✅ Збережено!", reply_markup=main_menu(is_guest=False))
        except Exception: await message.answer("❌ Помилка.", reply_markup=main_menu(is_guest=True))
        return

    if step == 'create_event_title': st['event_title'] = text; st['step'] = 'create_event_description'; await message.answer("📄 <b>Опис події:</b>\n\n<i>Деталі збільшують довіру та шанси знайти компанію!</i>", parse_mode="HTML", reply_markup=back_kb()); return
    if step == 'create_event_description': st['event_description'] = text; st['step'] = 'create_event_date'; await message.answer("📅 <b>Дата та час:</b>\n\n<i>Обери день у календарі нижче.</i>", parse_mode="HTML", reply_markup=month_kb(datetime.now().year, datetime.now().month)); return

    if step == 'create_event_date':
        dt = parse_user_datetime(text)
        if dt:
            if dt < datetime.now(): await message.answer("⚠️ Не можна створювати подію в минулому!", reply_markup=back_kb()); return
            st['event_date'] = dt; st['step'] = 'create_event_city'; await message.answer("🏙 <b>Обери місто проведення:</b>", parse_mode="HTML", reply_markup=event_city_kb())
        else: await message.answer("Не впізнав дату.", reply_markup=back_kb())
        return

    if step == 'create_event_time':
        t = parse_time_hhmm(text)
        if t:
            d: date = st.get('picked_date'); dt = datetime(d.year, d.month, d.day, t[0], t[1])
            if dt < datetime.now(): await message.answer("⚠️ Цей час вже минув! Введи майбутній час:", reply_markup=back_kb()); return
            st['event_date'] = dt; st['step'] = 'create_event_city'; await message.answer("🏙 <b>Обери місто проведення:</b>", parse_mode="HTML", reply_markup=event_city_kb())
        else: await message.answer("Формат часу HH:MM", reply_markup=back_kb())
        return

    if step == 'create_event_city': st['event_city'] = text; st['step'] = 'create_event_location'; await message.answer("📍 <b>Точна адреса (або гео):</b>\n\n<i>Точна локація допомагає зрозуміти, наскільки зручно добиратися.</i>", parse_mode="HTML", reply_markup=location_choice_kb()); return
    if step == 'create_event_location':
        if text == "📝 Ввести адресу текстом": st['step'] = 'create_event_location_name'; await message.answer("Вкажи адресу:", reply_markup=back_kb()); return
        if text == "⏭ Пропустити локацію": st['event_location'] = st.get('event_city', ''); st['step'] = 'create_event_capacity'; await message.answer("👥 <b>Місткість:</b>\n\n<i>Вкажи загальну кількість учасників.</i>", parse_mode="HTML", reply_markup=back_kb()); return
        return

    if step == 'create_event_location_name': st['event_location'] = f"{st.get('event_city', '')}, {text}"; st['step'] = 'create_event_capacity'; await message.answer("👥 <b>Місткість:</b>", parse_mode="HTML", reply_markup=back_kb()); return
    if step == 'create_event_capacity':
        if text.isdigit() and int(text) > 0: st['capacity'] = int(text); st['step'] = 'create_event_needed'; await message.answer("👤 <b>Скільки ще шукаєш?</b>", parse_mode="HTML", reply_markup=back_kb()); return
    if step == 'create_event_needed':
        if text.isdigit() and 0 < int(text) <= st.get('capacity', 999): st['needed_count'] = int(text); st['step'] = 'create_event_photo'; await message.answer("📸 <b>Фото події</b>\n\n<i>Яскраве фото привертає на 50% більше уваги!</i>", parse_mode="HTML", reply_markup=skip_back_kb()); return
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
        st['event_location'] = f"{st.get('event_city', '')} (За геолокацією)"; st['step'] = 'create_event_capacity'; await message.answer("👥 <b>Місткість:</b>", parse_mode="HTML", reply_markup=back_kb())
    elif cur == 'search_geo_wait_location':
        radius = st.get('search_radius', 10.0)
        await message.answer(f"🔍 Шукаю події в радіусі {radius} км...", reply_markup=main_menu(is_guest=not bool(await get_user_from_db(uid))))
        events = await find_events_near(message.location.latitude, message.location.longitude, radius, limit=10)
        await render_events_list(message, events, uid, f"В радіусі {radius} км")
        st['step'] = 'menu'

# --- ІНЛАЙН КНОПКИ ---
@dp.callback_query(F.data.startswith("report:"))
async def report_event_callback(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    uid = call.from_user.id
    st = user_states.setdefault(uid, {})
    st['report_event_id'] = event_id
    st['step'] = 'wait_report_reason'
    await call.message.answer("🚨 Напиши, що не так з цією подією або організатором (реклама, скам, неадекватність тощо):", reply_markup=back_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("join:"))
async def join_event_callback(call: types.CallbackQuery):
    event_id = int(call.data.split(":")[1])
    if not await get_user_from_db(call.from_user.id): await call.message.answer("⚠️ Тобі потрібно створити профіль!", reply_markup=main_menu(is_guest=True)); await call.answer(); return
    st = user_states.setdefault(call.from_user.id, {})
    st['join_event_id'] = event_id; st['step'] = 'wait_welcome_msg'
    await call.message.answer("💬 Напиши коротке повідомлення організатору.\n\nАбо просто натисни «⏭ Пропустити».", reply_markup=skip_back_kb()); await call.answer()

@dp.callback_query(F.data.startswith("req_yes:"))
async def approve_request_callback(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1]); req = await get_request_info(req_id)
    if not req or req['status'] != 'pending': return await call.answer("Заявка вже оброблена.", show_alert=True)
    await update_request_status_db(req_id, 'approved'); await decrement_needed_count(req['event_id'])
    await call.message.edit_text(call.message.html_text + f"\n\n✅ <b>Схвалено!</b>\nНапиши учаснику: <a href='tg://user?id={req['seeker_id']}'>{req['seeker_name']}</a>", parse_mode="HTML")
    user = await get_user_from_db(call.from_user.id)
    try: await bot.send_message(req['seeker_id'], f"🎉 Твою заявку на <b>{req['event_title']}</b> схвалено!\n\nЗв'яжися з організатором: <a href='tg://user?id={req['organizer_id']}'>{user['name']}</a>", parse_mode="HTML")
    except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("req_no:"))
async def reject_request_callback(call: types.CallbackQuery):
    req_id = int(call.data.split(":")[1]); req = await get_request_info(req_id)
    if not req or req['status'] != 'pending': return await call.answer("Заявка вже оброблена.", show_alert=True)
    await update_request_status_db(req_id, 'rejected')
    await call.message.edit_text(call.message.html_text + "\n\n❌ <b>Відхилено.</b>", parse_mode="HTML")
    try: await bot.send_message(req['seeker_id'], f"😕 На жаль, заявку на <b>{req['event_title']}</b> відхилено.", parse_mode="HTML")
    except: pass
    await call.answer()

@dp.callback_query(F.data.startswith("rate:"))
async def handle_rating(call: types.CallbackQuery):
    _, ev_id, org_id, score = call.data.split(":")
    await save_rating(int(ev_id), int(org_id), call.from_user.id, int(score))
    await call.message.edit_text("Дякуємо за твою оцінку! ⭐ Рейтинг організатора оновлено.")
    await call.answer()

@dp.callback_query(F.data.startswith("myevents:role:"))
async def myevents_role_callback(call: types.CallbackQuery):
    role = call.data.split(":")[2]
    uid = call.from_user.id
    kb = []
    if role == "org":
        events = await list_user_events(uid, 'active')
        if not events: return await call.message.edit_text("Ти ще не створив активних подій 🤷‍♂️")
        for ev in events[:10]: kb.append([types.InlineKeyboardButton(text=f"👑 {ev['title']} ({ev['date'].strftime('%d.%m')})", callback_data=f"view_ev:{ev['id']}")])
        await call.message.edit_text("<b>👑 Ти Організатор:</b>\nОбери подію, щоб переглянути деталі:", parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
    elif role == "part":
        events = await get_user_participations(uid)
        if not events: return await call.message.edit_text("Ти ще не подавав заявки (або їх відхилили) 🤷‍♂️")
        status_emoji = {"pending": "⏳", "approved": "✅"}
        for ev in events[:10]:
            st_emoji = status_emoji.get(ev['req_status'], "❓")
            kb.append([types.InlineKeyboardButton(text=f"{st_emoji} {ev['title']} ({ev['date'].strftime('%d.%m')})", callback_data=f"view_ev:{ev['id']}")])
        await call.message.edit_text("<b>🙋‍♂️ Ти Учасник:</b>\nОбери подію для перегляду:", parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("view_ev:"))
async def view_event_callback(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[1])
    ev = await get_event_by_id(ev_id)
    if not ev or ev['status'] == 'deleted': return await call.answer("Подія більше не існує", show_alert=True)
    
    uid = call.from_user.id
    participants = await get_approved_participants(ev_id)
    is_org = str(ev['user_id']) == str(uid)
    is_approved = any(str(p['telegram_id']) == str(uid) for p in participants)
    
    card = format_event_card(ev, show_org_link=(is_approved or is_org))
    
    if is_org or is_approved:
        card += "\n\n👥 <b>Схвалені учасники:</b>\n"
        if participants:
            for p in participants: card += f"• <a href='tg://user?id={p['telegram_id']}'>{p['name']}</a>\n"
        else: card += "Поки нікого немає."
            
    kb_buttons = []
    if is_approved and not is_org: kb_buttons.append([types.InlineKeyboardButton(text="💬 Написати організатору", url=f"tg://user?id={ev['user_id']}")])

    if is_org:
        kb_buttons.append([types.InlineKeyboardButton(text="❌ Скасувати подію", callback_data=f"cancel_ev:{ev_id}")])
        back_role = "org"
    else:
        kb_buttons.append([types.InlineKeyboardButton(text="🚪 Скасувати заявку / Вийти", callback_data=f"leave_ev:{ev_id}")])
        back_role = "part"
        
    kb_buttons.append([types.InlineKeyboardButton(text="⬅️ Назад до списку", callback_data=f"myevents:role:{back_role}")])
    await call.message.edit_text(card, parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@dp.callback_query(F.data.startswith("cancel_ev:"))
async def cancel_event_handler(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[1])
    ev = await get_event_by_id(ev_id)
    if str(ev['user_id']) != str(call.from_user.id): return await call.answer("Немає доступу!", show_alert=True)
    await cancel_event_db(ev_id)
    parts = await get_approved_participants(ev_id)
    for p in parts:
        try: await bot.send_message(p['telegram_id'], f"⚠️ Організатор на жаль скасував подію <b>{ev['title']}</b>.", parse_mode="HTML")
        except: pass
    await call.message.edit_text("❌ Подію успішно скасовано.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="myevents:role:org")]]))

@dp.callback_query(F.data.startswith("leave_ev:"))
async def leave_event_handler(call: types.CallbackQuery):
    ev_id = int(call.data.split(":")[1])
    req = await get_request_by_event_and_user(ev_id, call.from_user.id)
    if not req: return await call.answer("Заявку не знайдено.", show_alert=True)
    await cancel_request_db(req['id'], ev_id, req['status'] == 'approved')
    ev = await get_event_by_id(ev_id)
    user = await get_user_from_db(call.from_user.id)
    try: await bot.send_message(ev['user_id'], f"ℹ️ Учасник <a href='tg://user?id={call.from_user.id}'>{user['name']}</a> скасував свою участь у події <b>{ev['title']}</b>. Місце знову вільне!", parse_mode="HTML")
    except: pass
    await call.message.edit_text("🚪 Ти успішно скасував свою участь у цій події.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="myevents:role:part")]]))

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
    asyncio.create_task(reminders_loop())
    asyncio.create_task(finish_events_loop())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(main())
