```python
import os
import logging
import asyncio
from datetime import datetime

import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

# --- Initialization ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# In-memory user state storage
user_states: dict[int, dict] = {}

# --- Keyboards ---
def get_back_button() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True
    )

main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="👤 Мій профіль")],
        [types.KeyboardButton(text="➕ Створити подію")],
        [types.KeyboardButton(text="🔍 Знайти подію за інтересами")]
    ],
    resize_keyboard=True
)

# --- Database helpers ---
async def get_user_from_db(user_id: int) -> asyncpg.Record | None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1",
            str(user_id)
        )
    finally:
        await conn.close()

async def save_user_to_db(
    user_id: int, phone: str, name: str, city: str, photo: str, interests: str
):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO users (telegram_id, phone, name, city, photo, interests) VALUES ($1,$2,$3,$4,$5,$6)",
            str(user_id), phone, name, city, photo, interests
        )
    finally:
        await conn.close()

async def save_event_to_db(
    user_id: int,
    creator_name: str,
    creator_phone: str,
    title: str,
    description: str,
    date: datetime,
    location: str,
    capacity: int,
    needed_count: int,
    status: str
):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO events (
                user_id, creator_name, creator_phone, title,
                description, date, location, capacity, needed_count, status
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            user_id, creator_name, creator_phone, title,
            description, date, location, capacity, needed_count, status
        )
    finally:
        await conn.close()

async def publish_event(user_id: int, title: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE events SET status='published' WHERE user_id=$1 AND title=$2",
            user_id, title
        )
    finally:
        await conn.close()

async def cancel_event(user_id: int, title: str):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE events SET status='cancelled' WHERE user_id=$1 AND title=$2",
            user_id, title
        )
    finally:
        await conn.close()

# --- Handlers ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_states.setdefault(user_id, {})
    user = await get_user_from_db(user_id)
    if not user:
        user_states[user_id] = {"step": "name", "phone": None}
        await message.answer(
            "👋 Вітаю! Давай створимо профіль. Введіть ваше ім'я:",
            reply_markup=get_back_button()
        )
    else:
        user_states[user_id]["step"] = "menu"
        await message.answer(
            "👋 Ласкаво просимо назад! Оберіть дію:",
            reply_markup=main_menu
        )
    return

@dp.message(F.text & ~F.text.in_(['⬅️ Назад']))
async def handle_steps(message: types.Message):
    user_id = message.from_user.id
    text    = message.text.strip()
    state   = user_states.setdefault(user_id, {})
    step    = state.get('step')
    print(f"=== handle_steps: step={step!r}, text={text!r}")

    # Global Create Event trigger
    if text == '➕ Створити подію':
        user = await get_user_from_db(user_id)
        if not user:
            await message.answer('⚠️ Спочатку зареєструйтесь через /start')
            return
        state.clear()
        state.update({
            'step': 'create_event_title',
            'creator_name': user['name'],
            'creator_phone': user['phone']
        })
        await message.answer('📝 Введіть назву події:', reply_markup=get_back_button())
        return

    # 1) Registration
    if step == 'name':
        state['name'] = text
        state['step'] = 'city'
        await message.answer('🏙 Введіть ваше місто:', reply_markup=get_back_button())
        return
    elif step == 'city':
        state['city'] = text
        state['step'] = 'photo'
        await message.answer('🖼 Надішліть свою світлину:', reply_markup=get_back_button())
        return
    elif step == 'photo':
        if message.photo:
            state['photo'] = message.photo[-1].file_id
        state['step'] = 'interests'
        await message.answer('🎯 Введіть ваші інтереси (через кому):', reply_markup=get_back_button())
        return
    elif step == 'interests':
        state['interests'] = [i.strip() for i in text.split(',')]
        await save_user_to_db(
            user_id=user_id,
            phone=state.get('phone'),
            name=state.get('name'),
            city=state.get('city'),
            photo=state.get('photo',''),
            interests=', '.join(state['interests'])
        )
        state['step'] = 'menu'
        await message.answer('✅ Профіль створено!', reply_markup=main_menu)
        return

    # 2) Main menu
    if step == 'menu':
        if text == '👤 Мій профіль':
            user = await get_user_from_db(user_id)
            if user and user.get('photo'):
                await message.answer_photo(
                    photo=user['photo'],
                    caption=(
                        f"👤 Ваш профіль:\n📛 Ім'я: {user['name']}\n"
                        f"🏙 Місто: {user['city']}\n🎯 Інтереси: {user['interests']}"
                    ),
                    reply_markup=types.ReplyKeyboardMarkup(
                        [[types.KeyboardButton('✏️ Змінити профіль')], [types.KeyboardButton('⬅️ Назад')]],
                        resize_keyboard=True
                    )
                )
            else:
                await message.answer('❗ Профіль не знайдено.', reply_markup=main_menu)
            return
        elif text == '✏️ Змінити профіль':
            usr = await get_user_from_db(user_id)
            state.clear()
            state['step'] = 'name'
            state['phone'] = usr['phone'] if usr else None
            await message.answer("✍️ Введіть нове ім'я:", reply_markup=get_back_button())
            return

    # 3) Create event flow
    if step == 'create_event_title':
        state['event_title'] = text
        state['step'] = 'create_event_description'
        await message.answer('📝 Введіть опис події:', reply_markup=get_back_button())
        return
    elif step == 'create_event_description':
        state['event_description'] = text
        state['step'] = 'create_event_date'
        await message.answer(
            '📅 Введіть дату та час YYYY-MM-DD HH:MM', reply_markup=get_back_button()
        )
        return
    elif step == 'create_event_date':
        try:
            dt = datetime.strptime(text, '%Y-%m-%d %H:%M')
        except ValueError:
            await message.answer('❗ Невірний формат дати!', reply_markup=get_back_button())
            return
        state['event_date'] = dt
        state['step'] = 'create_event_location'
        await message.answer('📍 Вкажіть місце:', reply_markup=get_back_button())
        return
    elif step == 'create_event_location':
        state['event_location'] = text
        state['step'] = 'create_event_capacity'
        await message.answer('👥 Скільки всього місць?', reply_markup=get_back_button())
        return
    elif step == 'create_event_capacity':
        try:
            cap = int(text)
            if cap <= 0:
                raise ValueError
        except ValueError:
            await message.answer('❗ Введіть додатнє число.', reply_markup=get_back_button())
            return
        state['capacity'] = cap
        state['step'] = 'create_event_needed'
        await message.answer('👤 Скільки учасників шукаєте?', reply_markup=get_back_button())
        return
    elif step == 'create_event_needed':
        try:
            need = int(text)
            cap = state['capacity']
            if need <= 0 or need > cap:
                raise ValueError
        except ValueError:
            await message.answer(f"❗ Від 1 до {state['capacity']}", reply_markup=get_back_button())
            return
        state['needed_count'] = need
        try:
            await save_event_to_db(
                user_id=user_id,
                creator_name=state['creator_name'],
                creator_phone=state['creator_phone'],
                title=state['event_title'],
                description=state['event_description'],
                date=state['event_date'],
                location=state['event_location'],
                capacity=state['capacity'],
                needed_count=state['needed_count'],
                status='draft'
            )
        except Exception as e:
            logging.error('Save event failed: %s', e)
            await message.answer('❌ Не вдалося зберегти.', reply_markup=main_menu)
            state['step'] = 'menu'
            return
        state['step'] = 'publish_confirm'
        await message.answer(
            '🔍 Перевірте та підтвердіть публікацію',
            reply_markup=types.ReplyKeyboardMarkup(
                [[types.KeyboardButton('✅ Опублікувати')], [types.KeyboardButton('❌ Скасувати')], [types.KeyboardButton('⬅️ Назад')]],
                resize_keyboard=True
            )
        )
        return

    # 4) Publish/Cancel
    if step == 'publish_confirm':
        if text == '✅ Опублікувати':
            await publish_event(user_id, state['event_title'])
            state['step'] = 'menu'
            await message.answer('🚀 Опубліковано!', reply_markup=main_menu)
        elif text == '❌ Скасувати':
            await cancel_event(user_id, state['event_title'])
            state['step'] = 'menu'
            await message.answer('❌ Скасовано.', reply_markup=main_menu)
        return

    # 5) Search events
    if step == 'find_event_menu' and text == '🔍 Знайти подію за інтересами':
        user = await get_user_from_db(user_id)
        # implement search logic
        return

    # Fallback
    logging.info('Unhandled step %s text %s', step, text)

# --- Entrypoint ---
async def main():
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
```



   
