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
OPENAI_KEY = "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"
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

def clean_text(text):
    """Убираем markdown символы чтобы Telegram не ругался"""
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = text.replace("`", "").replace("###", "").replace("##", "").replace("#", "")
    return text.strip()

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
        return clean_text(response.choices[0].message.content)
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
        
    )

@dp.callback_query(F.data == "mode_mama")
async def choose_mama(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.entering_birthdate)
    await call.message.edit_text(
        "👶 Отлично! Введи дату рождения малыша.\n\n"
        "📅 Формат: *ДД.ММ.ГГГГ*\nНапример: *10.03.2024*",
        
    )

# ─── ВВОД ПДР ────────────────────────────────────────────────
@dp.message(RegStates.entering_pdr)
async def enter_pdr(message: Message, state: FSMContext):
    text = message.text.strip()
    weeks, days = calc_pregnancy_weeks(text)
    if not weeks:
        await message.answer("❌ Неверный формат. Введи дату так: *15.09.2025*", )
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
        
        reply_markup=kb_pregnant_menu()
    )

# ─── ВВОД ДАТЫ РОЖДЕНИЯ ──────────────────────────────────────
@dp.message(RegStates.entering_birthdate)
async def enter_birthdate(message: Message, state: FSMContext):
    text = message.text.strip()
    months, days = calc_child_age(text)
    if months is None:
        await message.answer("❌ Неверный формат. Введи дату так: *10.03.2024*", )
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
                
                reply_markup=kb_pregnant_menu()
            )
        else:
            months, _ = calc_child_age(date_value)
            await call.message.edit_text(
                f"👶 Малышу *{age_label(months)}*\n\nЧем могу помочь?",
                
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
EXPERT_PREG = (
    "Ты эксперт в акушерстве, перинатальной психологии и фетальной медицине. "
    "Опирайся на рекомендации ВОЗ, протоколы ACOG (Американский колледж акушеров и гинекологов), "
    "исследования в области эмбриологии и нейронауки развития плода. "
    "Отвечай тепло, поддерживающе, без страшилок — но точно и научно. "
    "При любых тревожных симптомах направляй к врачу."
)

@dp.callback_query(F.data == "preg_week")
async def preg_week(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    weeks, days = calc_pregnancy_weeks(date_value)
    await call.message.edit_text(
        f"Твой срок\n\n"
        f"🤰 {weeks} недель и {days} дней\n\n"
        f"Это {'1-й триместр — закладка всех органов' if weeks <= 13 else '2-й триместр — активный рост' if weeks <= 26 else '3-й триместр — подготовка к рождению'}",
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
        EXPERT_PREG,
        f"Дай подробное научное описание развития плода на {weeks} неделе беременности. "
        f"1) Размер и вес плода — конкретные цифры по нормам УЗИ; "
        f"2) Какие органы и системы формируются/развиваются прямо сейчас; "
        f"3) Сенсорное развитие — что малыш уже слышит, чувствует, воспринимает; "
        f"4) Нейрогенез — как развивается мозг на этой неделе; "
        f"5) Движения плода — что норма для этого срока; "
        f"6) Что мама может сделать для оптимального развития малыша прямо сейчас. "
        f"Пиши увлекательно и с любовью — мама должна почувствовать связь с малышом."
    )
    await call.message.edit_text(
        f"👶 Малыш на {weeks} неделе\n\n{answer}",
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
        EXPERT_PREG,
        f"Составь исчерпывающий чек-лист для {weeks} недели беременности по протоколам ВОЗ и ACOG. "
        f"1) Обязательные анализы и скрининги именно для этого срока — что, зачем, что показывает; "
        f"2) Визиты к специалистам — акушер, узист, другие; "
        f"3) Питание — что критически важно сейчас (фолиевая, железо, йод, омега-3 по нормам); "
        f"4) Физическая активность — что разрешено и полезно на этом сроке; "
        f"5) Что нужно сделать практически (документы, курсы, подготовка); "
        f"6) Тревожные симптомы на этом сроке — когда срочно к врачу."
    )
    await call.message.edit_text(
        f"Чек-лист на {weeks} неделю\n\n{answer}",
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
        EXPERT_PREG,
        f"Составь практичный список покупок для мамы на {weeks} неделе беременности. "
        f"Раздели на категории: "
        f"1) Для мамы сейчас — одежда, уход, здоровье; "
        f"2) В роддом — сумка мамы и малыша по актуальным рекомендациям; "
        f"3) Для новорождённого — базовый список без лишнего; "
        f"4) Для дома — что подготовить заранее; "
        f"5) Что точно НЕ нужно покупать — развенчай популярные мифы о необходимых товарах. "
        f"Будь практичной и честной — без рекламы ненужных вещей."
    )
    await call.message.edit_text(
        f"Список покупок\n\n{answer}",
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
        reply_markup=kb_back_to_menu("mama")
    )

EXPERT_BASE = (
    "Ты эксперт в детской педиатрии, психологии развития и нейронауке. "
    "Опирайся строго на научно доказанные данные: рекомендации ВОЗ, руководства AAP "
    "(Американской академии педиатрии), исследования CDC, труды ведущих специалистов — "
    "Людмилы Петрановской (теория привязанности), Харви Карпа (успокоение новорождённых), "
    "Уильяма Серза (attachment parenting), Жана Пиаже (когнитивное развитие), "
    "Льва Выготского (зона ближайшего развития). "
    "Отвечай развёрнуто, структурированно, с конкретными практическими рекомендациями. "
    "Пиши тепло и понятно для мамы — без медицинского жаргона, но с научной точностью. "
    "При любых симптомах здоровья обязательно рекомендуй консультацию педиатра."
)

@dp.callback_query(F.data == "mama_dev")
async def mama_dev(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай подробный научно обоснованный анализ развития ребёнка в {age_label(m)} ({m} месяцев). "
                  f"Охвати все сферы по стандартам AAP и ВОЗ: "
                  f"1) Физическое развитие — моторика крупная и мелкая, нормы роста и веса; "
                  f"2) Речевое развитие — что должен говорить/понимать по нормам; "
                  f"3) Когнитивное развитие — мышление, память, причинно-следственные связи; "
                  f"4) Социально-эмоциональное развитие — привязанность, эмоции, взаимодействие; "
                  f"5) Сенсорное развитие — зрение, слух, тактильное восприятие. "
                  f"Укажи чёткие нормы и что должно насторожить маму."
    )

@dp.callback_query(F.data == "mama_games")
async def mama_games(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Предложи 8-10 научно обоснованных развивающих игр и занятий для ребёнка {age_label(m)} ({m} месяцев). "
                  f"Опирайся на теорию зоны ближайшего развития Выготского и исследования нейропластичности. "
                  f"Для каждой игры укажи: название, как играть (пошагово), "
                  f"какие зоны мозга и навыки развивает, почему это важно именно сейчас. "
                  f"Только простые игры без специальных игрушек — руки, голос, бытовые предметы."
    )

@dp.callback_query(F.data == "mama_books")
async def mama_books(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Порекомендуй 6-8 книг для чтения ребёнку {age_label(m)} ({m} месяцев) "
                  f"с научным обоснованием выбора. "
                  f"Объясни почему именно эти книги подходят для данного этапа развития мозга — "
                  f"ритм, повторения, цвета, объём текста, когнитивная нагрузка. "
                  f"Также порекомендуй 3-4 книги ДЛЯ МАМ от ведущих специалистов по этому возрасту."
    )

@dp.callback_query(F.data == "mama_health")
async def mama_health(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай исчерпывающую информацию о здоровье ребёнка {age_label(m)} ({m} месяцев) "
                  f"по стандартам ВОЗ и AAP. "
                  f"1) Типичные проблемы этого возраста и доказанные методы помощи; "
                  f"2) Алгоритм действий при температуре (по протоколам AAP); "
                  f"3) Признаки ОРВИ vs бактериальной инфекции — когда антибиотики НЕ нужны; "
                  f"4) Красные флаги — симптомы при которых немедленно к врачу; "
                  f"5) Плановые осмотры и прививки по календарю ВОЗ для этого возраста."
    )

@dp.callback_query(F.data == "mama_meds")
async def mama_meds(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай научно обоснованную информацию о лекарственной безопасности "
                  f"для ребёнка {age_label(m)} ({m} месяцев) по стандартам AAP. "
                  f"1) Жаропонижающие — парацетамол vs ибупрофен, при какой температуре давать по протоколу AAP; "
                  f"2) Что категорически нельзя в этом возрасте и почему; "
                  f"3) Доказательная база по популярным средствам (колики, зубы, простуда); "
                  f"4) Когда самолечение опасно. "
                  f"Конкретные дозировки — только у педиатра. Объясни маме почему это важно."
    )

@dp.callback_query(F.data == "mama_teeth")
async def mama_teeth(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай полную научную информацию о зубах ребёнка {age_label(m)} ({m} месяцев). "
                  f"1) Хронология прорезывания по нормам ВОЗ — что ожидать сейчас; "
                  f"2) Нейрофизиология боли при прорезывании и доказанные методы облегчения; "
                  f"3) Что НЕ работает и опасно (гели с лидокаином — позиция AAP); "
                  f"4) Уход за молочными зубами — когда начинать чистить, фторид по рекомендации AAP; "
                  f"5) Первый визит к стоматологу — когда и зачем по стандартам."
    )

@dp.callback_query(F.data == "mama_food")
async def mama_food(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай научно обоснованные рекомендации по питанию ребёнка {age_label(m)} ({m} месяцев) "
                  f"строго по протоколам ВОЗ и ESPGHAN (Европейское общество детской гастроэнтерологии). "
                  f"1) Что вводить сейчас — конкретный список продуктов с обоснованием; "
                  f"2) Что категорически нельзя и почему (физиология ЖКТ ребёнка); "
                  f"3) Размер порций по возрасту; "
                  f"4) Грудное вскармливание vs смесь — позиция ВОЗ; "
                  f"5) Аллергены — когда и как вводить по новым исследованиям (метод LEAP); "
                  f"6) Признаки пищевой аллергии и непереносимости."
    )

@dp.callback_query(F.data == "mama_recipes")
async def mama_recipes(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Составь 4-5 nutritionally balanced рецептов для ребёнка {age_label(m)} ({m} месяцев) "
                  f"по стандартам ВОЗ и ESPGHAN. "
                  f"Для каждого рецепта укажи: ингредиенты, способ приготовления, "
                  f"пищевую ценность (белки/жиры/углеводы), какие витамины и минералы содержит, "
                  f"почему полезен именно в этом возрасте. "
                  f"Учитывай только то что разрешено в данном возрасте по протоколам."
    )

@dp.callback_query(F.data == "mama_routine")
async def mama_routine(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Составь научно обоснованный режим дня для ребёнка {age_label(m)} ({m} месяцев) "
                  f"на основе хронобиологии и исследований сна AAP и ВОЗ. "
                  f"1) Нормы сна для этого возраста — дневной и ночной по данным NSF; "
                  f"2) Примерное расписание по часам с объяснением физиологии; "
                  f"3) Окна бодрствования — сколько времени ребёнок может не спать без переутомления; "
                  f"4) Признаки переутомления и недосыпа; "
                  f"5) Как выстроить режим с учётом циркадных ритмов ребёнка."
    )

@dp.callback_query(F.data == "mama_sleep")
async def mama_sleep(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай исчерпывающий научный анализ сна ребёнка {age_label(m)} ({m} месяцев) "
                  f"на основе исследований AAP, NSF и сомнологии. "
                  f"1) Нейрофизиология сна в этом возрасте — почему ребёнок так спит; "
                  f"2) Доказанные методы улучшения сна (без метода CIO если возраст до 6 мес); "
                  f"3) Безопасная среда сна по стандартам AAP (профилактика СВДС); "
                  f"4) Ночные пробуждения — норма или нет для этого возраста; "
                  f"5) Методы засыпания с доказательной базой — что реально работает."
    )

@dp.callback_query(F.data == "mama_tantrums")
async def mama_tantrums(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Объясни поведение ребёнка {age_label(m)} ({m} месяцев) с нейронаучной точки зрения "
                  f"на основе трудов Людмилы Петрановской, Дэниэла Сигела и Тины Пейн Брайсон. "
                  f"1) Почему ребёнок ведёт себя именно так — незрелость префронтальной коры; "
                  f"2) Теория привязанности Петрановской — как это применить прямо сейчас; "
                  f"3) Метод 'Connect and Redirect' Сигела — пошаговый алгоритм; "
                  f"4) Что делать в момент истерики — конкретные фразы и действия; "
                  f"5) Как НЕ навредить психике ребёнка — чего избегать категорически."
    )

@dp.callback_query(F.data == "mama_family")
async def mama_family(call: CallbackQuery):
    await mama_gpt_handler(
        call,
        EXPERT_BASE,
        lambda m: f"Дай научно обоснованные рекомендации по семейным отношениям "
                  f"когда ребёнку {age_label(m)} ({m} месяцев). "
                  f"Опирайся на исследования Джона Готтмана (стабильность пар), "
                  f"Петрановской (роль отца в привязанности) и психологию семейных систем. "
                  f"1) Роль отца в развитии ребёнка этого возраста — что говорит наука; "
                  f"2) Как сохранить партнёрские отношения с доказательными стратегиями Готтмана; "
                  f"3) Ревность старших детей — нейрофизиология и как помочь; "
                  f"4) Бабушки и дедушки — границы и сотрудничество без конфликтов."
    )

@dp.callback_query(F.data == "mama_emotions")
async def mama_emotions(call: CallbackQuery):
    user = get_user(call.from_user.id)
    await call.message.edit_text("⏳ Готовлю поддержку для тебя...")
    answer = await ask_gpt(
        EXPERT_BASE + " Ты также специалист по послеродовой психологии и материнскому выгоранию. "
        "Говори с мамой как заботливый друг-эксперт — тепло, без осуждения, с глубоким пониманием. "
        "Мама важна не меньше ребёнка. Это научный факт.",
        "Дай развёрнутую научную информацию об эмоциональном состоянии мамы после родов. "
        "1) Послеродовая депрессия vs беби-блюз — в чём разница, критерии DSM-5, распространённость по данным ВОЗ; "
        "2) Материнское выгорание — симптомы, исследования Моники Роскам; "
        "3) Тревожность молодых мам — нейрофизиология и доказанные методы снижения; "
        "4) Самозабота с научной точки зрения — что реально восстанавливает ресурс мамы; "
        "5) Когда нужна профессиональная помощь — конкретные признаки. "
        "Говори тепло, поддерживающе, без осуждения."
    )
    await call.message.edit_text(
        f"🧠 Эмоции мамы\n\n{answer}",
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
    await call.message.edit_text(text,  reply_markup=kb)

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
        
    )

@dp.message(QuestionStates.waiting_question)
async def handle_question(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()

    if user:
        mode, date_value, name = user
        if mode == "pregnant":
            weeks, _ = calc_pregnancy_weeks(date_value)
            context = f"Женщина на {weeks} неделе беременности задаёт вопрос."
        else:
            months, _ = calc_child_age(date_value)
            context = f"Мама, ребёнку {age_label(months)} ({months} месяцев), задаёт вопрос."
    else:
        context = "Мама задаёт вопрос о ребёнке или беременности."

    await message.answer("⏳ Думаю над ответом...")
    answer = await ask_gpt(
        f"Ты эксперт в педиатрии, перинатальной психологии и детском развитии. "
        f"{context} "
        f"Опирайся на рекомендации ВОЗ, AAP, ACOG и труды ведущих специалистов. "
        f"Отвечай развёрнуто, точно и с теплом. При медицинских симптомах — направляй к педиатру.",
        message.text
    )
    kb = kb_mama_menu() if user and user[0] == "mama" else kb_pregnant_menu() if user else kb_start()
    await message.answer(answer, reply_markup=kb)

# ─── АВТОПОСТИНГ В КАНАЛ ─────────────────────────────────────
async def post_to_channel():
    topics = [
        "научно обоснованный совет по развитию ребёнка от 0 до 3 лет",
        "детская психология — объяснение поведения ребёнка с нейронаучной точки зрения",
        "рекомендации ВОЗ по уходу за новорождённым — что важно знать каждой маме",
        "питание и прикорм по стандартам ESPGHAN — практический совет",
        "сон ребёнка — научные факты о детском сне от AAP",
        "послеродовое восстановление мамы — что говорит наука",
        "развивающие игры с научным обоснованием для малышей",
        "беременность — важный совет основанный на исследованиях ACOG",
        "теория привязанности Петрановской — как применить в жизни",
        "мифы о воспитании детей которые опровергает наука",
    ]
    import random
    topic = random.choice(topics)
    post = await ask_gpt(
        "Ты автор экспертного Telegram-канала 'Я МАМА' для современных мам. "
        "Пишешь на основе научных исследований, рекомендаций ВОЗ, AAP и ведущих специалистов — "
        "Петрановской, Карпа, Серза, Готтмана. "
        "Стиль: тепло и по-человечески, но с научной точностью. "
        "Без воды, с конкретной пользой. Добавляй эмодзи уместно. "
        "Пост 200-300 слов. В конце — один практический совет который мама может применить сегодня.",
        f"Напиши экспертный пост для канала на тему: {topic}"
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
