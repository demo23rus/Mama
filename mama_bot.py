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
            max_tokens=2000
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
        [InlineKeyboardButton(text="📋 Первые дни с малышом", callback_data="mama_firstdays")],
        [InlineKeyboardButton(text="🤱 Грудное вскармливание", callback_data="mama_breastfeeding")],
        [InlineKeyboardButton(text="🏥 Восстановление мамы", callback_data="mama_recovery")],
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

def kb_firstdays():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍⚕️ Первый осмотр педиатра", callback_data="fd_pediatr")],
        [InlineKeyboardButton(text="📄 Свидетельство о рождении", callback_data="fd_svid")],
        [InlineKeyboardButton(text="🤸 Массаж и гимнастика", callback_data="fd_massage")],
        [InlineKeyboardButton(text="🏊 Плавание с малышом", callback_data="fd_swim")],
        [InlineKeyboardButton(text="🩺 Обходы врачей по месяцам", callback_data="fd_doctors")],
        [InlineKeyboardButton(text="🏫 Запись в садик", callback_data="fd_sadik")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])

def kb_breastfeeding():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍼 Как наладить ГВ с первых дней", callback_data="bf_start")],
        [InlineKeyboardButton(text="🥛 Молока мало — как расцедить", callback_data="bf_pump")],
        [InlineKeyboardButton(text="🔴 Уплотнения и лактостаз", callback_data="bf_lactostaz")],
        [InlineKeyboardButton(text="🥗 Питание мамы при ГВ", callback_data="bf_food")],
        [InlineKeyboardButton(text="❌ Что нельзя при ГВ", callback_data="bf_nofood")],
        [InlineKeyboardButton(text="🔄 Переход на смесь", callback_data="bf_formula")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])

def kb_recovery():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 После естественных родов", callback_data="rec_natural")],
        [InlineKeyboardButton(text="🏥 После кесарева сечения", callback_data="rec_caesar")],
        [InlineKeyboardButton(text="💪 Физическая активность", callback_data="rec_sport")],
        [InlineKeyboardButton(text="❤️ Интимная жизнь после родов", callback_data="rec_intimate")],
        [InlineKeyboardButton(text="💇 Выпадение волос", callback_data="rec_hair")],
        [InlineKeyboardButton(text="🏋️ Диастаз — восстановление пресса", callback_data="rec_diastaz")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
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

# ─── ПЕРВЫЕ ДНИ С МАЛЫШОМ ───────────────────────────────────
@dp.callback_query(F.data == "mama_firstdays")
async def mama_firstdays(call: CallbackQuery):
    await call.message.edit_text(
        "📋 Первые дни с малышом\n\n"
        "Всё что нужно знать и сделать после рождения малыша 👇",
        reply_markup=kb_firstdays()
    )

@dp.callback_query(F.data == "fd_pediatr")
async def fd_pediatr(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Расскажи подробно о первом осмотре педиатра после выписки из роддома. "
        "1) Когда педиатр должен прийти по закону — сроки по российскому законодательству; "
        "2) Как вызвать педиатра на дом — пошаговая инструкция (телефон, Госуслуги, сайт поликлиники); "
        "3) Что педиатр проверяет при первом осмотре новорождённого — полный список; "
        "4) Какие вопросы задать педиатру при первом визите; "
        "5) Что приготовить к приходу врача. "
        "Отвечай конкретно и практично."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

@dp.callback_query(F.data == "fd_doctors")
async def fd_doctors(call: CallbackQuery):
    await call.message.edit_text("⏳ Составляю расписание врачей...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Составь подробный календарь обходов врачей для ребёнка по месяцам — от рождения до 1 года. "
        "По каждому визиту укажи: возраст, каких врачей пройти, какие анализы сдать, "
        "какие прививки по национальному календарю РФ. "
        "Также укажи какие специалисты нужны в 1 год. "
        "Сделай в виде чёткого структурированного списка по месяцам."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

@dp.callback_query(F.data == "fd_svid")
async def fd_svid(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию о документах...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай пошаговую инструкцию по оформлению документов на новорождённого в России. "
        "1) Свидетельство о рождении — где получить (ЗАГС/МФЦ/Госуслуги), какие документы нужны, сроки; "
        "2) Регистрация ребёнка по месту жительства — как и где; "
        "3) Полис ОМС на ребёнка — как оформить, сроки; "
        "4) СНИЛС — как получить; "
        "5) Пособия и выплаты — какие положены, куда обращаться, сроки подачи; "
        "6) Материнский капитал — как получить. "
        "Всё пошагово, конкретно, с указанием сроков."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

@dp.callback_query(F.data == "fd_sadik")
async def fd_sadik(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию о садике...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай подробную инструкцию по записи ребёнка в детский сад в России. "
        "1) Когда вставать в очередь — оптимальный возраст ребёнка; "
        "2) Как встать в очередь через Госуслуги — пошагово; "
        "3) Какие документы нужны; "
        "4) Как работает система льготных очередей — кто имеет право; "
        "5) Что делать если отказали или долго ждать; "
        "6) С какого возраста берут в садик по закону. "
        "Конкретно и пошагово."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

@dp.callback_query(F.data == "fd_massage")
async def fd_massage(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию о массаже...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованное руководство по массажу и гимнастике для младенцев. "
        "1) С какого возраста можно начинать массаж — по рекомендациям педиатров; "
        "2) Виды массажа для разных возрастов (0-3 мес, 3-6 мес, 6-12 мес); "
        "3) Пошаговая техника общего укрепляющего массажа — как делать маме дома; "
        "4) Массаж при коликах и газах — техника и движения; "
        "5) Гимнастика по возрастам — конкретные упражнения; "
        "6) Противопоказания к массажу; "
        "7) Когда нужен профессиональный массажист а не домашний. "
        "Описывай движения чётко чтобы мама могла повторить."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

@dp.callback_query(F.data == "fd_swim")
async def fd_swim(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию о плавании...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованное руководство по плаванию с младенцем. "
        "1) С какого возраста можно купать и плавать — научные данные; "
        "2) Рефлекс плавания у новорождённых — что это и как использовать; "
        "3) Раннее плавание — польза для физического и нервного развития по исследованиям; "
        "4) Как организовать плавание дома в ванной — пошаговая инструкция; "
        "5) Температура воды, продолжительность, позиции поддержки; "
        "6) Бассейн с грудничком — с какого возраста, что выбрать; "
        "7) Противопоказания к плаванию. "
        "Конкретно и безопасно."
    )
    await call.message.answer(answer, reply_markup=kb_firstdays())

# ─── ГРУДНОЕ ВСКАРМЛИВАНИЕ ───────────────────────────────────
@dp.callback_query(F.data == "mama_breastfeeding")
async def mama_breastfeeding(call: CallbackQuery):
    await call.message.edit_text(
        "🤱 Грудное вскармливание\n\n"
        "Научная поддержка на каждом этапе 💕",
        reply_markup=kb_breastfeeding()
    )

@dp.callback_query(F.data == "bf_start")
async def bf_start(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай исчерпывающее руководство по налаживанию грудного вскармливания с первых дней "
        "по рекомендациям ВОЗ и ЮНИСЕФ. "
        "1) Первое прикладывание — когда и как, важность в первый час после родов; "
        "2) Правильный захват груди — детальное описание, признаки правильного и неправильного захвата; "
        "3) Позиции для кормления — колыбель, из-под руки, лёжа — как каждая выполняется; "
        "4) Как понять что молока хватает ребёнку — конкретные признаки; "
        "5) Частота кормлений по возрасту — по требованию vs по расписанию, позиция ВОЗ; "
        "6) Молозиво — что это, почему оно важнее любой смеси; "
        "7) Как приходит молоко — сроки, что нормально. "
        "Поддерживающий и конкретный тон."
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

@dp.callback_query(F.data == "bf_pump")
async def bf_pump(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованное руководство по увеличению лактации и расцеживанию. "
        "1) Почему молока может быть мало — физиологические причины; "
        "2) Как стимулировать выработку молока — доказанные методы (частые прикладывания, сцеживание, контакт кожа-к-коже); "
        "3) Техника ручного сцеживания — пошагово, движения, как правильно; "
        "4) Молокоотсос — как выбрать, как пользоваться правильно; "
        "5) Питание и питьевой режим мамы для лактации — что реально помогает по науке; "
        "6) Лактогонные средства — что доказано, что миф; "
        "7) Когда обратиться к консультанту по ГВ. "
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

@dp.callback_query(F.data == "bf_lactostaz")
async def bf_lactostaz(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай исчерпывающее руководство по лактостазу и уплотнениям в груди. "
        "1) Что такое лактостаз — причины, симптомы, как отличить от мастита; "
        "2) Лактостаз vs мастит vs абсцесс — чёткие различия и алгоритм действий для каждого; "
        "3) Первая помощь при лактостазе — конкретные действия в первые часы; "
        "4) Техника массажа при уплотнениях — движения, направление, интенсивность; "
        "5) Правильное расцеживание при лактостазе — пошагово; "
        "6) Тепло или холод — что и когда применять по доказательной медицине; "
        "7) Газоотводная трубка и другие народные методы — что говорит наука; "
        "8) Красные флаги — когда срочно к врачу; "
        "9) Профилактика лактостаза. "
        "Это срочная тема — отвечай чётко и конкретно."
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

@dp.callback_query(F.data == "bf_food")
async def bf_food(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованные рекомендации по питанию кормящей мамы. "
        "1) Принципы питания при ГВ по позиции ВОЗ — что реально важно; "
        "2) Что обязательно включить в рацион — белки, жиры, углеводы, витамины, минералы; "
        "3) Продукты которые улучшают качество молока — с научным обоснованием; "
        "4) Витамины для кормящей мамы — какие нужны, дозировки по нормам; "
        "5) Водный режим — сколько пить и что; "
        "6) Развенчание мифов о диете при ГВ — что на самом деле не нужно исключать. "
        "Конкретно и без излишних ограничений."
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

@dp.callback_query(F.data == "bf_nofood")
async def bf_nofood(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованный список того что нельзя или нужно ограничить при грудном вскармливании. "
        "1) Алкоголь — как влияет на молоко, безопасный интервал по данным AAP; "
        "2) Кофеин — допустимые дозы, в каких продуктах содержится; "
        "3) Аллергены — нужно ли исключать заранее или только при реакции ребёнка; "
        "4) Лекарства при ГВ — общий принцип, где проверять совместимость (LactMed); "
        "5) Продукты которые влияют на вкус молока; "
        "6) Что категорически запрещено. "
        "Развенчай популярные мифы — многие мамы излишне ограничивают себя без причины."
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

@dp.callback_query(F.data == "bf_formula")
async def bf_formula(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай поддерживающее и научно обоснованное руководство по переходу на смесь. "
        "1) Когда переход на смесь оправдан — медицинские показания; "
        "2) Как правильно завершить ГВ — постепенно, без вреда для здоровья мамы; "
        "3) Как выбрать смесь по возрасту — на что смотреть в составе; "
        "4) Как правильно разводить смесь — температура, пропорции, стерильность; "
        "5) Смешанное вскармливание — как совмещать ГВ и смесь; "
        "6) Психологический аспект — мама не должна чувствовать вину. "
        "Отвечай без осуждения, поддерживающе."
    )
    await call.message.answer(answer, reply_markup=kb_breastfeeding())

# ─── ВОССТАНОВЛЕНИЕ МАМЫ ─────────────────────────────────────
@dp.callback_query(F.data == "mama_recovery")
async def mama_recovery(call: CallbackQuery):
    await call.message.edit_text(
        "🏥 Восстановление мамы после родов\n\n"
        "Твоё здоровье так же важно как здоровье малыша 💕",
        reply_markup=kb_recovery()
    )

@dp.callback_query(F.data == "rec_natural")
async def rec_natural(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай подробное руководство по восстановлению после естественных родов. "
        "1) Первые 24 часа — что нормально, что должно насторожить; "
        "2) Послеродовые выделения (лохии) — норма по срокам и объёму, красные флаги; "
        "3) Швы и разрывы — уход, когда заживут, когда снимают; "
        "4) Восстановление матки — сроки, признаки нормального процесса; "
        "5) Боль и дискомфорт — что облегчит, какие препараты безопасны при ГВ; "
        "6) Поход в туалет после родов — как облегчить; "
        "7) Геморрой после родов — как лечить безопасно; "
        "8) Когда можно вставать, ходить, поднимать тяжести. "
        "Конкретно и практично."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())

@dp.callback_query(F.data == "rec_caesar")
async def rec_caesar(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай исчерпывающее руководство по восстановлению после кесарева сечения. "
        "1) Первые дни в больнице — что происходит, когда встают, обезболивание; "
        "2) Шов после КС — виды швов, уход в домашних условиях, чем обрабатывать; "
        "3) Когда снимают швы или рассасываются сами — по видам; "
        "4) Ограничения после КС — что нельзя и сколько времени: поднятие тяжестей, секс, спорт; "
        "5) Боль после КС — как справляться, какие препараты при ГВ; "
        "6) Восстановление тканей — сроки заживления по слоям; "
        "7) Рубец — уход, когда начинать массаж рубца, силиконовые пластыри; "
        "8) Следующая беременность после КС — через сколько можно, риски; "
        "9) Красные флаги — симптомы при которых срочно к врачу. "
        "Максимально конкретно — мамы после КС часто не знают что нормально."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())

@dp.callback_query(F.data == "rec_sport")
async def rec_sport(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай научно обоснованный план возвращения к физической активности после родов. "
        "1) После естественных родов — когда начинать, с чего начать; "
        "2) После КС — другие сроки и ограничения; "
        "3) Упражнения Кегеля — почему критически важны, как делать правильно; "
        "4) Первые упражнения в роддоме — что безопасно сразу; "
        "5) Диастаз — как проверить самостоятельно, какие упражнения запрещены при диастазе; "
        "6) Постепенный план: 6 недель, 3 месяца, 6 месяцев после родов; "
        "7) Бег, силовые тренировки — когда можно. "
        "С научным обоснованием и без вреда для здоровья."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())

@dp.callback_query(F.data == "rec_intimate")
async def rec_intimate(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай деликатное и научно обоснованное руководство по интимной жизни после родов. "
        "1) Когда физически можно возобновить — рекомендации ACOG после естественных родов и КС; "
        "2) Почему может быть дискомфорт и боль — физиологические причины (сухость, швы, гормоны); "
        "3) Как справиться с сухостью при ГВ — безопасные средства; "
        "4) Психологический аспект — снижение либидо после родов это норма, почему; "
        "5) Как разговаривать с партнёром об этом; "
        "6) Контрацепция после родов — какие методы при ГВ безопасны. "
        "Деликатно, без осуждения, с уважением к маме."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())

@dp.callback_query(F.data == "rec_hair")
async def rec_hair(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Объясни послеродовое выпадение волос научно и дай практические рекомендации. "
        "1) Почему выпадают волосы после родов — физиология, роль эстрогена и телогеновой фазы; "
        "2) Когда начинается и заканчивается — нормальные сроки; "
        "3) Это норма или патология — как отличить; "
        "4) Что реально помогает — витамины, питание, уход за волосами с доказательной базой; "
        "5) Что не поможет — развенчание мифов о масках и народных средствах; "
        "6) Когда обратиться к трихологу или эндокринологу. "
        "Поддерживающий тон — многие мамы очень переживают из-за этого."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())

@dp.callback_query(F.data == "rec_diastaz")
async def rec_diastaz(call: CallbackQuery):
    await call.message.edit_text("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        "Дай подробное научное руководство по диастазу после родов. "
        "1) Что такое диастаз — анатомия, почему возникает при беременности; "
        "2) Как самостоятельно проверить есть ли диастаз — пошаговый тест; "
        "3) Степени диастаза — лёгкий, средний, тяжёлый; "
        "4) Упражнения которые ЗАПРЕЩЕНЫ при диастазе — скручивания, планка, пресс; "
        "5) Упражнения которые ПОМОГАЮТ — дыхательные, гипопрессивные, Кегеля; "
        "6) Бандаж после родов — помогает ли, как носить правильно; "
        "7) Когда нужна операция — показания; "
        "8) Сроки восстановления при разных степенях. "
        "Конкретно с описанием упражнений которые мама может делать дома."
    )
    await call.message.answer(answer, reply_markup=kb_recovery())


# ─── АВТОПОСТИНГ В КАНАЛ ─────────────────────────────────────

CHANNEL_ID = "@yamama_ai"

DAILY_THEMES = {
    0: "беременность и подготовка к родам",
    1: "новорождённый 0-3 месяца",
    2: "малыш 3-12 месяцев",
    3: "ребёнок 1-3 года",
    4: "дошкольник 3-7 лет",
    5: "здоровье и педиатрия",
    6: "мама о себе — восстановление и психология",
}

RUBRICS = {
    8:  ("🌅 Доброе утро, мама",
         "Короткий заряд на день — мотивация, поддержка, маленький совет психолога. Тёплый тон. 100-150 слов."),
    10: ("🔬 Научный факт дня",
         "Интересный научный факт который удивляет и хочется переслать подруге. Ссылка на ВОЗ или AAP. 150-200 слов."),
    13: ("💡 Совет педиатра",
         "Практический научно обоснованный совет — конкретный и применимый сегодня. По рекомендациям ВОЗ, AAP. 200-250 слов."),
    16: ("🧠 Детская психология",
         "Объяснение поведения ребёнка с нейронаучной точки зрения. Опирайся на Петрановскую, Сигела. 200-250 слов."),
    20: ("❤️ Для мамы",
         "О восстановлении, выгорании, отношениях, самой себе. Тепло и поддерживающе. 150-200 слов."),
}

async def post_rubric(hour: int):
    from datetime import datetime
    weekday = datetime.now().weekday()
    daily_theme = DAILY_THEMES[weekday]
    rubric_name, rubric_instruction = RUBRICS[hour]
    post = await ask_gpt(
        "Ты автор экспертного Telegram-канала 'Я МАМА' для современных мам. "
        "Пишешь на основе научных исследований, рекомендаций ВОЗ, AAP, ACOG и ведущих специалистов — "
        "Петрановской, Карпа, Серза, Готтмана, Сигела. "
        "Стиль: тепло и по-человечески, но с научной точностью. "
        "Без воды, с конкретной пользой. Добавляй эмодзи уместно. "
        "ВАЖНО: каждый пост должен быть на уникальную подтему, не повторяй предыдущие посты. "
        "В конце — один практический совет который мама может применить сегодня.",
        f"Рубрика: {rubric_name}\n"
        f"Тема дня: {daily_theme}\n"
        f"Инструкция: {rubric_instruction}\n"
        f"Начни пост с эмодзи рубрики и её названия."
    )
    try:
        await bot.send_message(CHANNEL_ID, post)
        logging.info(f"Пост опубликован: {rubric_name} | {daily_theme}")
    except Exception as e:
        logging.error(f"Ошибка постинга: {e}")

async def post_morning():   await post_rubric(8)
async def post_10():        await post_rubric(10)
async def post_afternoon(): await post_rubric(13)
async def post_evening():   await post_rubric(16)
async def post_night():     await post_rubric(20)

async def post_today_all():
    import asyncio as aio
    logging.info("Публикуем первый день постов...")
    for hour in [8, 10, 13, 16, 20]:
        await post_rubric(hour)
        await aio.sleep(15)
    logging.info("Все посты первого дня опубликованы!")

# ─── ЗАПУСК ──────────────────────────────────────────────────
async def main():
    init_db()
    scheduler.add_job(post_morning,   "cron", hour=8,  minute=0)
    scheduler.add_job(post_10,        "cron", hour=10, minute=0)
    scheduler.add_job(post_afternoon, "cron", hour=13, minute=0)
    scheduler.add_job(post_evening,   "cron", hour=16, minute=0)
    scheduler.add_job(post_night,     "cron", hour=20, minute=0)
    scheduler.start()
    logging.info("Мамин помощник запущен!")
    asyncio.create_task(post_today_all())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
