import asyncio
import logging
import sqlite3
import os
from datetime import datetime, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── ЗАГРУЗКА КЛЮЧЕЙ ─────────────────────────────────────────
def load_env(path="/root/.env_mama"):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception as e:
        logging.warning(f"Не удалось загрузить {path}: {e}")
    return env

_env = load_env()

# ─── НАСТРОЙКИ ───────────────────────────────────────────────
BOT_TOKEN  = "8769245157:AAH2EbEFpGj8MzuHUMiBKeLB7eJztyxfC1s"
OPENAI_KEY = "sk-mfvVI3QN2uQvXPlhMkAeUUzmbjK5aQzj"
CHANNEL_ID = _env.get("CHANNEL_ID") or "@YaMamaChannel"

logging.basicConfig(level=logging.INFO)

# ─── ИНИЦИАЛИЗАЦИЯ ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
client = AsyncOpenAI(api_key=OPENAI_KEY)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
logging.basicConfig(level=logging.INFO)

# ─── FSM СОСТОЯНИЯ ───────────────────────────────────────────
class RegStates(StatesGroup):
    choosing_mode = State()
    entering_pdr = State()
    entering_birthdate = State()

class QuestionStates(StatesGroup):
    waiting_question = State()

class DiaryStates(StatesGroup):
    waiting_entry = State()

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            mode TEXT,
            date_value TEXT,
            name TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            entry TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id, mode, date_value, name=""):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO users (user_id, mode, date_value, name, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, mode, date_value, name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT mode, date_value, name FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_diary(user_id, entry):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO diary (user_id, entry, created_at)
        VALUES (?, ?, ?)
    """, (user_id, entry, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_diary(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT entry, created_at FROM diary WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────
def calc_pregnancy_weeks(pdr_str):
    try:
        pdr = datetime.strptime(pdr_str, "%d.%m.%Y").date()
        conception = pdr - __import__('datetime').timedelta(days=280)
        today = date.today()
        days = (today - conception).days
        weeks = days // 7
        day_extra = days % 7
        return weeks, day_extra
    except:
        return None, None

def calc_child_age(birth_str):
    try:
        birth = datetime.strptime(birth_str, "%d.%m.%Y").date()
        today = date.today()
        months = (today.year - birth.year) * 12 + (today.month - birth.month)
        days = (today - birth).days
        return months, days
    except:
        return None, None

def age_label(months):
    if months < 1:
        return "новорождённый"
    elif months < 12:
        return f"{months} мес."
    else:
        years = months // 12
        m = months % 12
        if m == 0:
            return f"{years} г."
        return f"{years} г. {m} мес."

async def ask_gpt(system_prompt, user_prompt):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка GPT: {e}"

# ─── КЛАВИАТУРЫ ──────────────────────────────────────────────
def kb_start():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤰 Я беременна", callback_data="mode_pregnant")],
        [InlineKeyboardButton(text="👩 Я уже мама", callback_data="mode_mama")],
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/YaMamaChannel")]
    ])

def kb_pregnant_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мой срок", callback_data="preg_week")],
        [InlineKeyboardButton(text="👶 Развитие малыша", callback_data="preg_baby")],
        [InlineKeyboardButton(text="✅ Чек-лист", callback_data="preg_checklist")],
        [InlineKeyboardButton(text="🛍 Список покупок", callback_data="preg_shop")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="🔄 Изменить данные", callback_data="change_data")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])

def kb_mama_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Развитие по возрасту", callback_data="mama_dev"),
         InlineKeyboardButton(text="🎮 Игры и занятия", callback_data="mama_games")],
        [InlineKeyboardButton(text="📚 Что читать", callback_data="mama_books"),
         InlineKeyboardButton(text="🌡 Здоровье", callback_data="mama_health")],
        [InlineKeyboardButton(text="💊 Лекарства", callback_data="mama_meds"),
         InlineKeyboardButton(text="🦷 Зубки", callback_data="mama_teeth")],
        [InlineKeyboardButton(text="🍼 Питание и прикорм", callback_data="mama_food"),
         InlineKeyboardButton(text="🥣 Рецепты", callback_data="mama_recipes")],
        [InlineKeyboardButton(text="🌙 Режим дня", callback_data="mama_routine"),
         InlineKeyboardButton(text="😴 Проблемы со сном", callback_data="mama_sleep")],
        [InlineKeyboardButton(text="😢 Истерики и капризы", callback_data="mama_tantrums"),
         InlineKeyboardButton(text="👨‍👩‍👧 Отношения в семье", callback_data="mama_family")],
        [InlineKeyboardButton(text="🧠 Эмоции мамы", callback_data="mama_emotions"),
         InlineKeyboardButton(text="📓 Дневник малыша", callback_data="mama_diary")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="🔄 Изменить данные", callback_data="change_data")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])

def kb_back_to_menu(mode):
    cb = "menu_pregnant" if mode == "pregnant" else "menu_mama"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data=cb)],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])

# ─── СТАРТ ───────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    name = message.from_user.first_name or "мамочка"

    if user:
        mode, date_value, saved_name = user
        if mode == "pregnant":
            weeks, days = calc_pregnancy_weeks(date_value)
            if weeks:
                await message.answer(
                    f"👋 С возвращением, {saved_name or name}!\n\n"
                    f"🤰 Ты на *{weeks} неделе* беременности ({days} дн.)\n\n"
                    f"Чем могу помочь?",
                    parse_mode="Markdown",
                    reply_markup=kb_pregnant_menu()
                )
            else:
                await show_start(message, name, state)
        else:
            months, days = calc_child_age(date_value)
            if months is not None:
                await message.answer(
                    f"👋 С возвращением, {saved_name or name}!\n\n"
                    f"👶 Малышу *{age_label(months)}*\n\n"
                    f"Чем могу помочь?",
                    parse_mode="Markdown",
                    reply_markup=kb_mama_menu()
                )
            else:
                await show_start(message, name, state)
    else:
        await show_start(message, name, state)

async def show_start(message: Message, name: str, state: FSMContext):
    await state.set_state(RegStates.choosing_mode)
    await message.answer(
        f"👋 Привет, *{name}*!\n\n"
        f"Я *Мамин помощник* 🤱 — твой личный ИИ-помощник.\n\n"
        f"Я буду давать советы, отвечать на вопросы и помогать — "
        f"всё строго под твою ситуацию.\n\n"
        f"Расскажи мне о себе 👇",
        parse_mode="Markdown",
        reply_markup=kb_start()
    )

# ─── ВЫБОР РЕЖИМА ────────────────────────────────────────────
@dp.callback_query(F.data == "mode_pregnant")
async def choose_pregnant(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.entering_pdr)
    await call.message.edit_text(
        "🤰 Отлично! Введи предполагаемую дату родов (ПДР).\n\n"
        "Её можно узнать у врача или в обменной карте.\n\n"
        "📅 Формат: *ДД.ММ.ГГГГ*\nНапример: *15.09.2025*",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "mode_mama")
async def choose_mama(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.entering_birthdate)
    await call.message.edit_text(
        "👶 Отлично! Введи дату рождения малыша.\n\n"
        "📅 Формат: *ДД.ММ.ГГГГ*\nНапример: *10.03.2024*",
        parse_mode="Markdown"
    )

# ─── ВВОД ПДР ────────────────────────────────────────────────
@dp.message(RegStates.entering_pdr)
async def enter_pdr(message: Message, state: FSMContext):
    text = message.text.strip()
    weeks, days = calc_pregnancy_weeks(text)
    if not weeks:
        await message.answer("❌ Неверный формат. Введи дату так: *15.09.2025*", parse_mode="Markdown")
        return
    if weeks < 0 or weeks > 42:
        await message.answer("❌ Дата выглядит неверно. Проверь и введи снова.")
        return

    name = message.from_user.first_name or ""
    save_user(message.from_user.id, "pregnant", text, name)
    await state.clear()
    await message.answer(
        f"✅ Сохранила!\n\n"
        f"🤰 Ты на *{weeks} неделе* беременности ({days} дн.)\n\n"
        f"Я буду давать советы и отвечать на вопросы именно для этого срока 💕",
        parse_mode="Markdown",
        reply_markup=kb_pregnant_menu()
    )

# ─── ВВОД ДАТЫ РОЖДЕНИЯ ──────────────────────────────────────
@dp.message(RegStates.entering_birthdate)
async def enter_birthdate(message: Message, state: FSMContext):
    text = message.text.strip()
    months, days = calc_child_age(text)
    if months is None:
        await message.answer("❌ Неверный формат. Введи дату так: *10.03.2024*", parse_mode="Markdown")
        return
    if months < 0 or months > 216:
        await message.answer("❌ Дата выглядит неверно. Проверь и введи снова.")
        return

    name = message.from_user.first_name or ""
    save_user(message.from_user.id, "mama", text, name)
    await state.clear()
    await message.answer(
        f"✅ Сохранила!\n\n"
        f"👶 Малышу *{age_label(months)}*\n\n"
        f"Буду давать советы именно для этого возраста 💕",
        parse_mode="Markdown",
        reply_markup=kb_mama_menu()
    )

# ─── ГЛАВНОЕ МЕНЮ ────────────────────────────────────────────
@dp.callback_query(F.data == "main_menu")
async def main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(call.from_user.id)
    if user:
        mode, date_value, name = user
        if mode == "pregnant":
            weeks, days = calc_pregnancy_weeks(date_value)
            await call.message.edit_text(
                f"🤰 Ты на *{weeks} неделе* беременности\n\nЧем могу помочь?",
                parse_mode="Markdown",
                reply_markup=kb_pregnant_menu()
            )
        else:
            months, _ = calc_child_age(date_value)
            await call.message.edit_text(
                f"👶 Малышу *{age_label(months)}*\n\nЧем могу помочь?",
                parse_mode="Markdown",
                reply_markup=kb_mama_menu()
            )
    else:
        await call.message.edit_text(
            "👋 Привет! Расскажи мне о себе 👇",
            reply_markup=kb_start()
        )

@dp.callback_query(F.data == "menu_pregnant")
async def menu_pregnant(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user:
        _, date_value, _ = user
        weeks, days = calc_pregnancy_weeks(date_value)
        await call.message.edit_text(
            f"🤰 Ты на *{weeks} неделе* беременности\n\nЧем могу помочь?",
            parse_mode="Markdown",
            reply_markup=kb_pregnant_menu()
        )

@dp.callback_query(F.data == "menu_mama")
async def menu_mama(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user:
        _, date_value, _ = user
        months, _ = calc_child_age(date_value)
        await call.message.edit_text(
            f"👶 Малышу *{age_label(months)}*\n\nЧем могу помочь?",
            parse_mode="Markdown",
            reply_markup=kb_mama_menu()
        )

@dp.callback_query(F.data == "change_data")
async def change_data(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.choosing_mode)
    await call.message.edit_text(
        "Выбери свой статус 👇",
        reply_markup=kb_start()
    )

# ─── БЕРЕМЕННОСТЬ — РАЗДЕЛЫ ──────────────────────────────────
@dp.callback_query(F.data == "preg_week")
async def preg_week(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    weeks, days = calc_pregnancy_weeks(date_value)
    await call.message.edit_text(
        f"📅 *Твой срок*\n\n"
        f"🤰 *{weeks} недель* и *{days} дней*\n\n"
        f"Это {'1-й триместр 🌱' if weeks <= 13 else '2-й триместр 🌸' if weeks <= 26 else '3-й триместр 🌺'}",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("pregnant")
    )

@dp.callback_query(F.data == "preg_baby")
async def preg_baby(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    weeks, _ = calc_pregnancy_weeks(date_value)
    await call.message.edit_text("⏳ Узнаю как развивается малыш...")
    answer = await ask_gpt(
        "Ты мягкий и заботливый помощник для беременных женщин. Отвечай тепло, ободряюще, без страшилок.",
        f"Расскажи подробно как развивается малыш на {weeks} неделе беременности. "
        f"Размер, органы, движения, что чувствует мама. Максимально интересно и тепло."
    )
    await call.message.edit_text(
        f"👶 *Малыш на {weeks} неделе*\n\n{answer}",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("pregnant")
    )

@dp.callback_query(F.data == "preg_checklist")
async def preg_checklist(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    weeks, _ = calc_pregnancy_weeks(date_value)
    await call.message.edit_text("⏳ Составляю чек-лист для твоего срока...")
    answer = await ask_gpt(
        "Ты помощник для беременных. Давай конкретные практичные советы.",
        f"Составь чек-лист что важно сделать на {weeks} неделе беременности. "
        f"Анализы, визиты к врачу, подготовка, покупки. Коротко и по делу, список."
    )
    await call.message.edit_text(
        f"✅ *Чек-лист на {weeks} неделю*\n\n{answer}",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("pregnant")
    )

@dp.callback_query(F.data == "preg_shop")
async def preg_shop(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    weeks, _ = calc_pregnancy_weeks(date_value)
    await call.message.edit_text("⏳ Составляю список покупок...")
    answer = await ask_gpt(
        "Ты помощник для беременных. Давай практичные списки.",
        f"Составь список что нужно купить/приготовить к родам на {weeks} неделе беременности. "
        f"Что для мамы, что для малыша, что в роддом. Структурированный список."
    )
    await call.message.edit_text(
        f"🛍 *Список покупок*\n\n{answer}",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("pregnant")
    )

# ─── МАМА — РАЗДЕЛЫ ──────────────────────────────────────────
async def mama_gpt_handler(call: CallbackQuery, system: str, prompt_fn):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(system, prompt_fn(months))
    await call.message.edit_text(
        answer,
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("mama")
    )

@dp.callback_query(F.data == "mama_dev")
async def mama_dev(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский педиатр и психолог. Отвечай тепло и понятно для мамы.",
        lambda m: f"Расскажи подробно что должен уметь ребёнок в {age_label(m)} ({m} месяцев). "
                  f"Физическое развитие, речь, социальные навыки, когнитивное развитие. "
                  f"Что нормально, на что обратить внимание."
    )

@dp.callback_query(F.data == "mama_games")
async def mama_games(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский педагог. Предлагай развивающие игры и занятия.",
        lambda m: f"Предложи 7-10 игр и занятий для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Простые, без дорогих игрушек. Для каждой укажи что развивает."
    )

@dp.callback_query(F.data == "mama_books")
async def mama_books(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский педагог и библиотекарь. Рекомендуй книги для детей.",
        lambda m: f"Порекомендуй 5-7 книг для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Для каждой — название, автор, почему подходит в этом возрасте."
    )

@dp.callback_query(F.data == "mama_health")
async def mama_health(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты педиатр. Отвечай понятно, без паники, направляй к врачу при серьёзных симптомах.",
        lambda m: f"Расскажи о типичных проблемах со здоровьем у детей {age_label(m)} ({m} месяцев). "
                  f"Колики, температура, простуда — как реагировать маме. "
                  f"Когда точно нужен врач."
    )

@dp.callback_query(F.data == "mama_meds")
async def mama_meds(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты педиатр. Давай общую информацию, всегда рекомендуй консультацию врача.",
        lambda m: f"Расскажи какие лекарства обычно разрешены детям {age_label(m)} ({m} месяцев). "
                  f"При температуре, коликах, прорезывании зубов, простуде. "
                  f"Только общая информация, конкретные дозы — у врача."
    )

@dp.callback_query(F.data == "mama_teeth")
async def mama_teeth(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты педиатр. Рассказывай о зубках понятно и ободряюще.",
        lambda m: f"Расскажи о зубках для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Когда ждать следующих зубов, симптомы прорезывания, как помочь малышу, "
                  f"уход за первыми зубками."
    )

@dp.callback_query(F.data == "mama_food")
async def mama_food(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты диетолог-педиатр. Давай конкретные рекомендации по питанию детей.",
        lambda m: f"Расскажи о питании и прикорме для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Что уже можно вводить, что нельзя, размер порций, режим кормления. "
                  f"Грудное/искусственное вскармливание."
    )

@dp.callback_query(F.data == "mama_recipes")
async def mama_recipes(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский повар. Давай простые полезные рецепты для детей.",
        lambda m: f"Дай 3-5 простых рецептов для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Учитывай что можно в этом возрасте. Для каждого — ингредиенты и способ приготовления."
    )

@dp.callback_query(F.data == "mama_routine")
async def mama_routine(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты педиатр-сомнолог. Помогай мамам выстраивать режим.",
        lambda m: f"Составь примерный режим дня для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Сон, кормление, бодрствование, прогулки. Разбей по часам."
    )

@dp.callback_query(F.data == "mama_sleep")
async def mama_sleep(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский сомнолог. Помогай мамам решать проблемы со сном без стресса.",
        lambda m: f"Расскажи о типичных проблемах со сном у детей {age_label(m)} ({m} месяцев). "
                  f"Почему не спит, как наладить сон, ритуалы укладывания. "
                  f"Нормы сна для этого возраста."
    )

@dp.callback_query(F.data == "mama_tantrums")
async def mama_tantrums(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты детский психолог. Помогай мамам понять и принять поведение ребёнка.",
        lambda m: f"Расскажи об истериках и капризах у детей {age_label(m)} ({m} месяцев). "
                  f"Почему возникают, как реагировать маме, что делать в моменте, "
                  f"как предотвратить. Без осуждения мамы и ребёнка."
    )

@dp.callback_query(F.data == "mama_family")
async def mama_family(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        "Ты семейный психолог. Помогай мамам выстраивать гармоничные отношения в семье.",
        lambda m: f"Расскажи об отношениях в семье когда ребёнку {age_label(m)} ({m} месяцев). "
                  f"Роль папы, как сохранить отношения с партнёром, ревность старших детей, "
                  f"бабушки и дедушки. Практические советы."
    )

@dp.callback_query(F.data == "mama_emotions")
async def mama_emotions(call: CallbackQuery):
    user = get_user(call.from_user.id)
    await call.message.edit_text("⏳ Готовлю поддержку для тебя...")
    answer = await ask_gpt(
        "Ты психолог и друг для мам. Отвечай с теплотой, пониманием и без осуждения. "
        "Мама важна не меньше ребёнка.",
        "Расскажи о выгорании, тревоге и усталости мамы. "
        "Как распознать, что чувствовать это нормально, "
        "как заботиться о себе с маленьким ребёнком, "
        "когда обратиться за помощью. Тепло и поддерживающе."
    )
    await call.message.edit_text(
        f"🧠 *Эмоции мамы*\n\n{answer}",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu("mama")
    )

# ─── ДНЕВНИК ─────────────────────────────────────────────────
@dp.callback_query(F.data == "mama_diary")
async def mama_diary(call: CallbackQuery, state: FSMContext):
    entries = get_diary(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Добавить запись", callback_data="diary_add")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if entries:
        text = "📓 *Дневник малыша*\n\n"
        for entry, created_at in entries[:10]:
            dt = datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
            text += f"📅 *{dt}*\n{entry}\n\n"
    else:
        text = "📓 *Дневник малыша*\n\nЗаписей пока нет. Начни фиксировать важные моменты! 💕"
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "diary_add")
async def diary_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(DiaryStates.waiting_entry)
    await call.message.edit_text(
        "📓 Напиши запись в дневник.\n\n"
        "Например: первый зуб, первый шаг, первое слово, рост и вес, смешной момент 💕"
    )

@dp.message(DiaryStates.waiting_entry)
async def save_diary_entry(message: Message, state: FSMContext):
    save_diary(message.from_user.id, message.text)
    await state.clear()
    user = get_user(message.from_user.id)
    await message.answer(
        "✅ Запись сохранена в дневник! 💕",
        reply_markup=kb_mama_menu() if user and user[0] == "mama" else kb_pregnant_menu()
    )

# ─── ВОПРОС ПОМОЩНИКУ ────────────────────────────────────────
@dp.callback_query(F.data == "ask_question")
async def ask_question(call: CallbackQuery, state: FSMContext):
    await state.set_state(QuestionStates.waiting_question)
    await call.message.edit_text(
        "❓ *Задай любой вопрос*\n\n"
        "О беременности, ребёнке, здоровье, воспитании, психологии — "
        "я отвечу с учётом твоей ситуации 💕\n\n"
        "Напиши свой вопрос:",
        parse_mode="Markdown"
    )

@dp.message(QuestionStates.waiting_question)
async def handle_question(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()

    if user:
        mode, date_value, name = user
        if mode == "pregnant":
            weeks, _ = calc_pregnancy_weeks(date_value)
            context = f"Это беременная женщина на {weeks} неделе беременности."
        else:
            months, _ = calc_child_age(date_value)
            context = f"Это мама, ребёнку {age_label(months)} ({months} месяцев)."
    else:
        context = "Это мама с вопросом о ребёнке или беременности."

    await message.answer("⏳ Думаю над ответом...")
    answer = await ask_gpt(
        f"Ты заботливый помощник для мам. {context} "
        f"Отвечай тепло, понятно, по делу. При медицинских вопросах рекомендуй врача.",
        message.text
    )
    kb = kb_mama_menu() if user and user[0] == "mama" else kb_pregnant_menu() if user else kb_start()
    await message.answer(answer, reply_markup=kb)

# ─── АВТОПОСТИНГ В КАНАЛ ─────────────────────────────────────
async def post_to_channel():
    topics = [
        "совет по воспитанию ребёнка от 0 до 3 лет",
        "детская психология — понять и принять поведение ребёнка",
        "уход за новорождённым — практический совет",
        "питание и прикорм — что важно знать маме",
        "сон ребёнка — как наладить режим",
        "эмоциональное выгорание мамы — как справляться",
        "развивающие игры для малышей",
        "беременность — полезный совет для будущей мамы",
    ]
    import random
    topic = random.choice(topics)
    post = await ask_gpt(
        "Ты автор уютного Telegram-канала для мам 'Я МАМА'. "
        "Пишешь тепло, с любовью, практично. Добавляй эмодзи. "
        "Пост должен быть 150-250 слов, с конкретной пользой.",
        f"Напиши пост для канала на тему: {topic}"
    )
    try:
        await bot.send_message(CHANNEL_ID, post)
    except Exception as e:
        logging.error(f"Ошибка постинга: {e}")

# ─── ЗАПУСК ──────────────────────────────────────────────────
async def main():
    init_db()
    scheduler.add_job(post_to_channel, "cron", hour=9, minute=0)
    scheduler.add_job(post_to_channel, "cron", hour=13, minute=0)
    scheduler.add_job(post_to_channel, "cron", hour=19, minute=0)
    scheduler.start()
    logging.info("Мамин помощник запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
