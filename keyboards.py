from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.web_app_info import WebAppInfo
import calendar as calmod
from datetime import datetime

# --- ПОСИЛАННЯ НА ТВІЙ ДОДАТОК ---
WEB_APP_URL = "https://worker-production-784c.up.railway.app/?v=5"

BTN_PROFILE, BTN_CREATE = "👤 Мій профіль", "➕ Створити подію"
BTN_MY_CHATS, BTN_MY_EVENTS = "👥 Мої контакти", "📦 Мої івенти"
BTN_BACK, BTN_SKIP, BTN_MENU = "⬅️ Назад", "⏭ Пропустити", "🏠 Меню"

def main_menu(is_guest: bool = False) -> ReplyKeyboardMarkup:
    # Створюємо магічну кнопку для TMA
    web_app_btn = KeyboardButton(
        text="🚀 Відкрити карту", 
        web_app=WebAppInfo(url=WEB_APP_URL)
    )

    if is_guest:
        kb = [
            [web_app_btn], # <--- Наша кнопка зверху!
            [KeyboardButton(text="🃏 Всі івенти в місті")], 
            [KeyboardButton(text="🎛 Фільтр івентів")], 
            [KeyboardButton(text="👤 Створити профіль / Реєстрація")]
        ]
    else:
        kb = [
            [web_app_btn], # <--- Наша кнопка зверху!
            [KeyboardButton(text="🃏 Всі івенти в місті"), KeyboardButton(text="➕ Створити подію")],
            [KeyboardButton(text="🎛 Фільтр івентів"), KeyboardButton(text="👤 Мій профіль")],
            [KeyboardButton(text=BTN_MY_CHATS), KeyboardButton(text=BTN_MY_EVENTS)]
        ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def back_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def search_menu_kb(is_guest: bool = False) -> ReplyKeyboardMarkup: 
    kb = [[KeyboardButton(text="🔎 За ключовим словом")], [KeyboardButton(text="📍 Поруч зі мною")]]
    if not is_guest:
        kb.append([KeyboardButton(text="🔮 За моїми інтересами")])
    kb.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def skip_back_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def reg_city_kb(is_edit: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="Київ"), KeyboardButton(text="Дніпро"), KeyboardButton(text="Львів")], 
        [KeyboardButton(text="Одеса"), KeyboardButton(text="Харків")]
    ]
    if is_edit:
        kb.append([KeyboardButton(text=BTN_SKIP)])
    kb.append([KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def event_city_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Київ"), KeyboardButton(text="Дніпро"), KeyboardButton(text="Львів")], [KeyboardButton(text="Одеса"), KeyboardButton(text="Харків")], [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def location_choice_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Надіслати поточну геолокацію", request_location=True)], [KeyboardButton(text="📝 Ввести адресу текстом"), KeyboardButton(text="⏭ Пропустити локацію")], [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def event_publish_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='✅ Опублікувати'), KeyboardButton(text='✏️ Редагувати')], [KeyboardButton(text='❌ Скасувати')]], resize_keyboard=True)

def swipe_city_kb() -> ReplyKeyboardMarkup: 
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Київ"), KeyboardButton(text="Дніпро"), KeyboardButton(text="Львів")], [KeyboardButton(text="Одеса"), KeyboardButton(text="Харків")], [KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def myevents_role_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👑 Я Організатор", callback_data="myevents:role:org")], [InlineKeyboardButton(text="🙋‍♂️ Я Учасник", callback_data="myevents:role:part")], [InlineKeyboardButton(text="📜 Історія івентів", callback_data="myevents:role:history")]])

def myevents_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 Активні", callback_data="myevents:filter:active"), InlineKeyboardButton(text="✅ Проведені", callback_data="myevents:filter:finished"), InlineKeyboardButton(text="🗑 Скасовані", callback_data="myevents:filter:deleted")]])

def event_join_kb(event_id: int) -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")],
        [InlineKeyboardButton(text="🚨 Поскаржитись", callback_data=f"report:{event_id}")]
    ])

def swipe_action_kb(event_id: int) -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")], 
        [InlineKeyboardButton(text="👎 Не цікаво (Далі)", callback_data="swipe:next")],
        [InlineKeyboardButton(text="🚨 Поскаржитись", callback_data=f"report:{event_id}")]
    ])

def request_decision_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Прийняти", callback_data=f"req_yes:{req_id}"), InlineKeyboardButton(text="❌ Відхилити", callback_data=f"req_no:{req_id}")]])

def month_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb = []
    month_name = datetime(year, month, 1).strftime("%B %Y")
    kb.append([InlineKeyboardButton(text=month_name, callback_data="cal:noop")])
    kb.append([InlineKeyboardButton(text=t, callback_data="cal:noop") for t in ["Mo","Tu","We","Th","Fr","Sa","Su"]])
    for week in calmod.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0: row.append(InlineKeyboardButton(text=" ", callback_data="cal:noop"))
            else: row.append(InlineKeyboardButton(text=str(d), callback_data=f"cal:date:{year:04d}-{month:02d}-{d:02d}"))
        kb.append(row)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1)  if month == 12 else (year, month + 1)
    kb.append([InlineKeyboardButton(text="«", callback_data=f"cal:nav:{prev_y:04d}-{prev_m:02d}"), InlineKeyboardButton(text="»", callback_data=f"cal:nav:{next_y:04d}-{next_m:02d}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def main_webapp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Відкрити Findsy", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
