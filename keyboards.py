from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import calendar as calmod
from datetime import datetime

# --- Тексты кнопок ---
BTN_PROFILE      = "👤 Мій профіль"
BTN_CREATE       = "➕ Створити подію"
BTN_SEARCH       = "🔍 Знайти подію"
BTN_MY_CHATS     = "📨 Мої чати"
BTN_MY_EVENTS    = "📦 Мої івенти"
BTN_BACK         = "⬅️ Назад"
BTN_SKIP         = "⏭ Пропустити"
BTN_MENU         = "🏠 Меню"  
BTN_SEARCH_KW    = "🔎 За ключовим словом"
BTN_SEARCH_NEAR  = "📍 Поруч зі мною"
BTN_SEARCH_MINE  = "🔮 За моїми інтересами"

FILTER_ACTIVE   = "active"
FILTER_FINISHED = "finished"
FILTER_DELETED  = "deleted"

# --- Reply Клавиатуры (Нижнее меню) ---
def main_menu(is_guest: bool = False) -> ReplyKeyboardMarkup:
    if is_guest:
        keyboard = [
            [KeyboardButton(text="🃏 Шукати івенти (Стрічка)")],
            [KeyboardButton(text="🎛 Фільтр івентів (Гость)")],
            [KeyboardButton(text="👤 Створити профіль / Реєстрація")]
        ]
    else:
        keyboard = [
            [KeyboardButton(text="🃏 Шукати івенти"), KeyboardButton(text="➕ Створити подію")],
            [KeyboardButton(text="🎛 Фільтр івентів"), KeyboardButton(text="👤 Мій профіль")],
            [KeyboardButton(text="📨 Мої чати"), KeyboardButton(text="📦 Мої івенти")]
        ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], resize_keyboard=True)

def search_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH_KW)],
            [KeyboardButton(text=BTN_SEARCH_NEAR)],
            [KeyboardButton(text=BTN_SEARCH_MINE)],
            [KeyboardButton(text=BTN_BACK)]
        ], resize_keyboard=True
    )

def skip_back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]], 
        resize_keyboard=True
    )

def location_choice_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Надіслати поточну геолокацію", request_location=True)],
            [KeyboardButton(text="📝 Ввести адресу текстом"), KeyboardButton(text="⏭ Пропустити локацію")],
            [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]
        ], resize_keyboard=True
    )

def event_publish_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='✅ Опублікувати'), KeyboardButton(text='✏️ Редагувати')],
            [KeyboardButton(text='❌ Скасувати')],
            [KeyboardButton(text=BTN_BACK), KeyboardButton(text=BTN_MENU)]
        ], resize_keyboard=True
    )

# --- Inline Клавиатуры (Под сообщениями) ---
def myevents_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Активні", callback_data=f"myevents:filter:{FILTER_ACTIVE}"),
            InlineKeyboardButton(text="✅ Проведені", callback_data=f"myevents:filter:{FILTER_FINISHED}"),
            InlineKeyboardButton(text="🗑 Скасовані", callback_data=f"myevents:filter:{FILTER_DELETED}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад до меню", callback_data="back:menu")]
    ])

def event_join_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")]])

def request_actions_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Відкрити чат", callback_data=f"reqchat:{req_id}")],
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve:{req_id}"),
         InlineKeyboardButton(text="❌ Відхилити",   callback_data=f"reject:{req_id}")],
    ])

def rating_kb(event_id: int) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(i), callback_data=f"rate:{event_id}:{i}") for i in range(1,6)]
    row2 = [InlineKeyboardButton(text=str(i), callback_data=f"rate:{event_id}:{i}") for i in range(6,11)]
    row3 = [InlineKeyboardButton(text="🙈 У мене не вийшло долучитися", callback_data=f"rate_skip:{event_id}")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2, row3])

def notification_choice_kb(sub_id: int, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙌 Долучитися", callback_data=f"join:{event_id}")],
        [InlineKeyboardButton(text="🔔 Продовжити", callback_data=f"notif_continue:{sub_id}"),
         InlineKeyboardButton(text="❌ Відписатися", callback_data=f"notif_stop:{sub_id}")]
    ])

def month_kb(year: int, month: int) -> InlineKeyboardMarkup:
    kb = []
    month_name = datetime(year, month, 1).strftime("%B %Y")
    kb.append([InlineKeyboardButton(text=month_name, callback_data="cal:noop")])
    kb.append([InlineKeyboardButton(t, callback_data="cal:noop") for t in ["Mo","Tu","We","Th","Fr","Sa","Su"]])
    for week in calmod.monthcalendar(year, month):
        row = []
        for d in week:
            if d == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal:noop"))
            else:
                row.append(InlineKeyboardButton(str(d), callback_data=f"cal:date:{year:04d}-{month:02d}-{d:02d}"))
        kb.append(row)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1)  if month == 12 else (year, month + 1)
    kb.append([
        InlineKeyboardButton("«", callback_data=f"cal:nav:{prev_y:04d}-{prev_m:02d}"),
        InlineKeyboardButton("»", callback_data=f"cal:nav:{next_y:04d}-{next_m:02d}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def swipe_city_kb() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="Київ"), KeyboardButton(text="Дніпро"), KeyboardButton(text="Львів")],
        [KeyboardButton(text="Одеса"), KeyboardButton(text="Харків")],
        [KeyboardButton(text="⬅️ Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def swipe_action_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Долучитися", callback_data=f"join:{event_id}")],
        [InlineKeyboardButton(text="👎 Не цікаво (Далі)", callback_data="swipe:next")]
    ])
