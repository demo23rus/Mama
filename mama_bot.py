import asyncio
import logging
import sqlite3
import os
from datetime import datetime, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uuid
import gspread
from google.oauth2.service_account import Credentials
from yookassa import Configuration, Payment

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
SUPPORT_USERNAME = "@demo23rus"
BOT_NAME = "Мамин помощник"
OPENAI_KEY = "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"

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

class PhotoStates(StatesGroup):
    waiting_photo = State()

class GrowthStates(StatesGroup):
    waiting_height = State()
    waiting_weight = State()

class SymptomStates(StatesGroup):
    waiting_symptom = State()

class FeedingStates(StatesGroup):
    waiting_side = State()
    waiting_duration = State()

class BenefitsStates(StatesGroup):
    waiting_params = State()

class PsychoStates(StatesGroup):
    in_session = State()

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS growth (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            height REAL,
            weight REAL,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS symptoms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symptom TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS feeding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            side TEXT,
            duration INTEGER,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sleep_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS psycho_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vaccinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            vaccine TEXT,
            scheduled_date TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT DEFAULT '',
            sub_end TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER,
            plan TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests_count (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
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

def save_growth(user_id, height, weight):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?, ?, ?, ?)",
              (user_id, height, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_growth(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_symptom(user_id, symptom):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?, ?, ?)",
              (user_id, symptom, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_symptoms(user_id, days=7):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_feeding(user_id, side, duration):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO feeding (user_id, side, duration, created_at) VALUES (?, ?, ?, ?)",
              (user_id, side, duration, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_feedings(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT side, duration, created_at FROM feeding WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_sleep(user_id, action):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO sleep_log (user_id, action, created_at) VALUES (?, ?, ?)",
              (user_id, action, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_sleep_log(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT action, created_at FROM sleep_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_subscription(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT plan, sub_end FROM subscriptions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "", None
    return row[0], row[1]

def set_subscription(user_id, plan, days):
    from datetime import timedelta
    end = (datetime.now() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect("/root/mama.db")
    conn.execute("INSERT OR REPLACE INTO subscriptions (user_id, plan, sub_end) VALUES (?,?,?)",
                 (user_id, plan, end))
    conn.commit()
    conn.close()

def is_premium(user_id):
    plan, sub_end = get_subscription(user_id)
    if plan == "mama_premium" and sub_end:
        if datetime.fromisoformat(sub_end) > datetime.now():
            return True
    return False

def get_request_count(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT count FROM requests_count WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_request_count(user_id):
    conn = sqlite3.connect("/root/mama.db")
    conn.execute("INSERT OR REPLACE INTO requests_count (user_id, count) VALUES (?, COALESCE((SELECT count FROM requests_count WHERE user_id=?), 0) + 1)",
                 (user_id, user_id))
    conn.commit()
    conn.close()

def save_pending_payment(payment_id, user_id, plan):
    conn = sqlite3.connect("/root/mama.db")
    conn.execute("INSERT INTO pending_payments (payment_id, user_id, plan, created_at) VALUES (?,?,?,?)",
                 (payment_id, user_id, plan, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT payment_id, user_id, plan FROM pending_payments")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_pending_payment(payment_id):
    conn = sqlite3.connect("/root/mama.db")
    conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
    conn.commit()
    conn.close()

def save_vaccination(user_id, vaccine, scheduled_date):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO vaccinations (user_id, vaccine, scheduled_date, created_at) VALUES (?, ?, ?, ?)",
              (user_id, vaccine, scheduled_date, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_vaccinations(user_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT id, vaccine, scheduled_date, done FROM vaccinations WHERE user_id=? ORDER BY scheduled_date", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_psycho_message(user_id, role, content):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
              (user_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_psycho_history(user_id, limit=15):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def clear_psycho_history(user_id):
    conn = sqlite3.connect("/root/mama.db")
    conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def mark_vaccination_done(vac_id):
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    c.execute("UPDATE vaccinations SET done=1 WHERE id=?", (vac_id,))
    conn.commit()
    conn.close()

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

async def send_long_message(chat_id, text, reply_markup=None):
    """Разбиваем длинные сообщения на части по 4000 символов"""
    max_len = 4000
    if len(text) <= max_len:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return
    parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            await bot.send_message(chat_id, part, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id, part)

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
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/yamama_ai")],
        [InlineKeyboardButton(text="💎 Премиум", callback_data="pay_premium"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")]
    ])

def kb_pregnant_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мой срок", callback_data="preg_week")],
        [InlineKeyboardButton(text="👶 Развитие малыша", callback_data="preg_baby")],
        [InlineKeyboardButton(text="✅ Чек-лист", callback_data="preg_checklist")],
        [InlineKeyboardButton(text="🛍 Список покупок", callback_data="preg_shop")],
        [InlineKeyboardButton(text="📸 Анализ фото 🔒", callback_data="show_premium")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="💎 Премиум", callback_data="pay_premium"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")],
        [InlineKeyboardButton(text="🔄 Изменить данные", callback_data="change_data")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])

def kb_mama_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Первые дни с малышом", callback_data="mama_firstdays")],
        [InlineKeyboardButton(text="💉 Прививки 🔒", callback_data="check_premium_vaccines"),
         InlineKeyboardButton(text="📏 Рост и вес 🔒", callback_data="check_premium_growth")],
        [InlineKeyboardButton(text="🌡 Трекер симптомов 🔒", callback_data="check_premium_symptoms"),
         InlineKeyboardButton(text="🤱 Трекер кормлений 🔒", callback_data="check_premium_feeding")],
        [InlineKeyboardButton(text="🌙 Дневник сна 🔒", callback_data="check_premium_sleep"),
         InlineKeyboardButton(text="💰 Пособия и выплаты 🔒", callback_data="check_premium_benefits")],
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
        [InlineKeyboardButton(text="📸 Анализ фото", callback_data="photo_menu")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="💎 Премиум", callback_data="pay_premium"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")],
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
                    f"🤰 Ты на {weeks} неделе беременности ({days} дн.)\n\n"
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
                    f"👶 Малышу {age_label(months)}\n\n"
                    f"Чем могу помочь?",
                    
                    reply_markup=kb_mama_menu()
                )
            else:
                await show_start(message, name, state)
    else:
        await show_start(message, name, state)

async def show_start(message: Message, name: str, state: FSMContext):
    import threading
    threading.Thread(target=sheets_add_user, args=(
        message.from_user.id, message.from_user.username, name
    )).start()
    await state.set_state(RegStates.choosing_mode)
    await message.answer(
        f"👋 Привет, {name}!\n\n"
        f"Я Мамин помощник 🤱 — твой личный ИИ-помощник.\n\n"
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
        "📅 Формат: ДД.ММ.ГГГГ\nНапример: 15.09.2025",
        
    )

@dp.callback_query(F.data == "mode_mama")
async def choose_mama(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.entering_birthdate)
    await call.message.edit_text(
        "👶 Отлично! Введи дату рождения малыша.\n\n"
        "📅 Формат: ДД.ММ.ГГГГ\nНапример: 10.03.2024",
        
    )

# ─── ВВОД ПДР ────────────────────────────────────────────────
@dp.message(RegStates.entering_pdr, F.text)
async def enter_pdr(message: Message, state: FSMContext):
    text = message.text.strip()
    weeks, days = calc_pregnancy_weeks(text)
    if not weeks:
        await message.answer("❌ Неверный формат. Введи дату так: 15.09.2025", )
        return
    if weeks < 0 or weeks > 42:
        await message.answer("❌ Дата выглядит неверно. Проверь и введи снова.")
        return

    name = message.from_user.first_name or ""
    save_user(message.from_user.id, "pregnant", text, name)
    await state.clear()
    await message.answer(
        f"✅ Сохранила!\n\n"
        f"🤰 Ты на {weeks} неделе беременности ({days} дн.)\n\n"
        f"Я буду давать советы и отвечать на вопросы именно для этого срока 💕",
        
        reply_markup=kb_pregnant_menu()
    )

# ─── ВВОД ДАТЫ РОЖДЕНИЯ ──────────────────────────────────────
@dp.message(RegStates.entering_birthdate, F.text)
async def enter_birthdate(message: Message, state: FSMContext):
    text = message.text.strip()
    months, days = calc_child_age(text)
    if months is None:
        await message.answer("❌ Неверный формат. Введи дату так: 10.03.2024", )
        return
    if months < 0 or months > 216:
        await message.answer("❌ Дата выглядит неверно. Проверь и введи снова.")
        return

    name = message.from_user.first_name or ""
    save_user(message.from_user.id, "mama", text, name)
    await state.clear()
    await message.answer(
        f"✅ Сохранила!\n\n"
        f"👶 Малышу {age_label(months)}\n\n"
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
                f"🤰 Ты на {weeks} неделе беременности\n\nЧем могу помочь?",
                
                reply_markup=kb_pregnant_menu()
            )
        else:
            months, _ = calc_child_age(date_value)
            await call.message.edit_text(
                f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?",
                
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
            f"🤰 Ты на {weeks} неделе беременности\n\nЧем могу помочь?",
            
            reply_markup=kb_pregnant_menu()
        )

@dp.callback_query(F.data == "menu_mama")
async def menu_mama(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user:
        _, date_value, _ = user
        months, _ = calc_child_age(date_value)
        await call.message.edit_text(
            f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?",
            
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
    await send_long_message(call.message.chat.id, answer, reply_markup=kb_back_to_menu("mama"))

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
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.edit_text("⏳ Подбираю игры...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Предложи 3-4 научно обоснованные развивающие игры для ребёнка {age_label(months)} ({months} месяцев). "
        f"Опирайся на теорию Выготского и исследования нейропластичности. "
        f"Для каждой: название, как играть пошагово, что развивает. "
        f"Только простые игры без дорогих игрушек."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё игры", callback_data="mama_games_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

@dp.callback_query(F.data == "mama_games_more")
async def mama_games_more(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.answer("⏳ Подбираю ещё игры...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Предложи ещё 3-4 ДРУГИЕ развивающие игры для ребёнка {age_label(months)} ({months} месяцев). "
        f"Не повторяй предыдущие игры. Другие виды активности — сенсорные, моторные, речевые или социальные. "
        f"Для каждой: название, как играть, что развивает."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё игры", callback_data="mama_games_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

@dp.callback_query(F.data == "mama_books")
async def mama_books(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.edit_text("⏳ Подбираю книги...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Порекомендуй 3 книги для чтения ребёнку {age_label(months)} ({months} месяцев). "
        f"Для каждой: название, автор, почему подходит для этого возраста. "
        f"И 1 книгу ДЛЯ МАМЫ от ведущего специалиста по этому возрасту."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё книги", callback_data="mama_books_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

@dp.callback_query(F.data == "mama_books_more")
async def mama_books_more(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.answer("⏳ Подбираю ещё книги...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Порекомендуй ещё 3 ДРУГИЕ книги для ребёнка {age_label(months)} ({months} месяцев). "
        f"Не повторяй предыдущие. Для каждой: название, автор, почему подходит."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё книги", callback_data="mama_books_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

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
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.edit_text("⏳ Подбираю рецепты...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Дай 2 рецепта для ребёнка {age_label(months)} ({months} месяцев) по нормам ВОЗ и ESPGHAN. "
        f"Для каждого: ингредиенты, способ приготовления, почему полезен в этом возрасте. "
        f"Только разрешённые продукты для данного возраста."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё рецепты", callback_data="mama_recipes_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

@dp.callback_query(F.data == "mama_recipes_more")
async def mama_recipes_more(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала введи данные!", show_alert=True)
        return
    _, date_value, _ = user
    months, _ = calc_child_age(date_value)
    await call.message.answer("⏳ Подбираю ещё рецепты...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Дай ещё 2 ДРУГИХ рецепта для ребёнка {age_label(months)} ({months} месяцев). "
        f"Не повторяй предыдущие. Только разрешённые продукты для этого возраста."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё рецепты", callback_data="mama_recipes_more")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

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
        text = "📓 Дневник малыша\n\n"
        for entry, created_at in entries[:10]:
            dt = datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
            text += f"📅 {dt}\n{entry}\n\n"
    else:
        text = "📓 Дневник малыша\n\nЗаписей пока нет. Начни фиксировать важные моменты! 💕"
    await call.message.edit_text(text,  reply_markup=kb)

@dp.callback_query(F.data == "diary_add")
async def diary_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(DiaryStates.waiting_entry)
    await call.message.edit_text(
        "📓 Напиши запись в дневник.\n\n"
        "Например: первый зуб, первый шаг, первое слово, рост и вес, смешной момент 💕"
    )

@dp.message(DiaryStates.waiting_entry, F.text)
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
        "❓ Задай любой вопрос\n\n"
        "О беременности, ребёнке, здоровье, воспитании, психологии — "
        "я отвечу с учётом твоей ситуации 💕\n\n"
        "Напиши свой вопрос:",
        
    )

@dp.message(QuestionStates.waiting_question, F.text)
async def handle_question(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    await state.clear()
    # Проверка лимита запросов
    if not is_premium(message.from_user.id):
        count = get_request_count(message.from_user.id)
        if count >= 10:
            await message.answer(
                "❓ Ты использовала 10 бесплатных вопросов\n\n"
                "Для продолжения оформи Премиум — 299 руб/месяц\n"
                "Безлимитные вопросы + все функции бота!",
                reply_markup=kb_premium()
            )
            return
        increment_request_count(message.from_user.id)

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


# ─── АНАЛИЗ ФОТО ─────────────────────────────────────────────
def kb_photo_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Сыпь и кожа малыша", callback_data="photo_skin")],
        [InlineKeyboardButton(text="💩 Стул малыша", callback_data="photo_stool")],
        [InlineKeyboardButton(text="🍽 Еда — подходит ли малышу", callback_data="photo_food")],
        [InlineKeyboardButton(text="💊 Упаковка смеси/лекарства", callback_data="photo_package")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])

@dp.callback_query(F.data == "photo_menu")
async def photo_menu(call: CallbackQuery):
    if not is_premium(call.from_user.id):
        await call.message.answer("🔒 Анализ фото доступен в Премиум 💎", reply_markup=kb_premium())
        return
    await call.message.answer(
        "📸 Анализ фото\n\n"
        "Отправь фото и я помогу разобраться.\n"
        "Выбери что хочешь проанализировать 👇",
        reply_markup=kb_photo_menu()
    )

@dp.callback_query(F.data == "photo_skin")
async def photo_skin(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="skin")
    await call.message.answer(
        "📸 Отправь фото кожи или сыпи малыша\n\n"
        "Я опишу что вижу и подскажу на что это похоже.\n"
        "⚠️ Это не замена осмотру педиатра — только ориентир."
    )

@dp.callback_query(F.data == "photo_stool")
async def photo_stool(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="stool")
    await call.message.answer(
        "📸 Отправь фото стула малыша\n\n"
        "Я оценю цвет и консистенцию — это важный показатель здоровья.\n"
        "⚠️ При любых сомнениях — к педиатру."
    )

@dp.callback_query(F.data == "photo_food")
async def photo_food_photo(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="food", user=user)
    age_info = ""
    if user and user[0] == "mama":
        months, _ = calc_child_age(user[1])
        age_info = f" (малышу {age_label(months)})"
    await call.message.answer(
        f"📸 Отправь фото еды или блюда{age_info}\n\n"
        "Я скажу подходит ли это по возрасту малыша."
    )

@dp.callback_query(F.data == "photo_package")
async def photo_package(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="package")
    await call.message.answer(
        "📸 Отправь фото упаковки смеси или лекарства\n\n"
        "Я расшифрую состав и скажу на что обратить внимание."
    )

@dp.message(PhotoStates.waiting_photo, F.photo)
async def handle_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_type = data.get("photo_type", "skin")
    user = get_user(message.from_user.id)
    await state.clear()

    # Получаем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    import aiohttp
    await message.answer("⏳ Анализирую фото...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                photo_bytes = await resp.read()

        import base64
        photo_b64 = base64.b64encode(photo_bytes).decode()

        # Сначала фильтр — проверяем что на фото нужное
        if photo_type == "skin":
            filter_prompt = "Посмотри на это изображение. На нём кожа человека или ребёнка с возможными высыпаниями, покраснениями или другими кожными проявлениями? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты опытный педиатр. Опиши что видишь на коже ребёнка: "
                "1) Характер высыпаний — цвет, форма, размер, локализация; "
                "2) На какие известные состояния это визуально похоже — потница, атопический дерматит, аллергия, инфекция и т.д.; "
                "3) Что можно сделать дома прямо сейчас; "
                "4) Красные флаги — когда срочно к врачу. "
                "В конце обязательно напомни что это описание а не диагноз."
            )
            wrong_msg = "📸 Я жду фото кожи или сыпи малыша 🤍 Отправь фотографию кожного покрова ребёнка."

        elif photo_type == "stool":
            filter_prompt = "На этом изображении подгузник или стул ребёнка? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты педиатр. Оцени стул ребёнка по фото: "
                "1) Цвет — что он означает для здоровья малыша; "
                "2) Консистенция — норма или нет; "
                "3) Что это может говорить о пищеварении; "
                "4) Когда нужен врач. "
                "Напомни что точный диагноз ставит только педиатр."
            )
            wrong_msg = "📸 Я жду фото стула малыша 🤍 Отправь соответствующее фото."

        elif photo_type == "food":
            age_context = ""
            if user and user[0] == "mama":
                months, _ = calc_child_age(user[1])
                age_context = f" Малышу {age_label(months)} ({months} месяцев)."
            filter_prompt = "На этом изображении еда или блюдо? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                f"Ты диетолог-педиатр.{age_context} "
                "Посмотри на это блюдо или продукт и скажи: "
                "1) Что это за еда; "
                "2) Подходит ли это ребёнку по возрасту — да/нет и почему; "
                "3) Что в составе может быть проблематично; "
                "4) Как правильно приготовить если нужна адаптация под возраст."
            )
            wrong_msg = "📸 Я жду фото еды или блюда 🤍 Отправь фотографию продукта или блюда."

        else:  # package
            filter_prompt = "На этом изображении упаковка товара, лекарства или смеси? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты педиатр-фармаколог. Изучи упаковку и скажи: "
                "1) Что это за продукт; "
                "2) Основные компоненты состава — что важно; "
                "3) Для какого возраста подходит; "
                "4) На что обратить особое внимание маме; "
                "5) Есть ли спорные ингредиенты."
            )
            wrong_msg = "📸 Я жду фото упаковки смеси или лекарства 🤍 Отправь фотографию упаковки."

        # Проверка фильтром
        filter_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                    {"type": "text", "text": filter_prompt}
                ]
            }],
            max_tokens=10
        )
        filter_answer = filter_response.choices[0].message.content.strip().upper()

        if "НЕТ" in filter_answer or "NO" in filter_answer:
            await message.answer(wrong_msg, reply_markup=kb_photo_menu())
            return

        # Основной анализ
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                    {"type": "text", "text": analysis_prompt}
                ]
            }],
            max_tokens=1000
        )
        answer = clean_text(response.choices[0].message.content)
        await message.answer(answer, reply_markup=kb_photo_menu())

    except Exception as e:
        logging.error(f"Ошибка анализа фото: {e}")
        await message.answer("Не удалось проанализировать фото. Попробуй ещё раз.", reply_markup=kb_photo_menu())

@dp.message(PhotoStates.waiting_photo)
async def photo_wrong_input(message: Message, state: FSMContext):
    await message.answer("📸 Жду именно фото — отправь изображение 🤍")

# ─── ГОЛОСОВЫЕ СООБЩЕНИЯ ─────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    # Сбрасываем любое текущее состояние — голос имеет приоритет
    await state.clear()
    if not is_premium(message.from_user.id):
        await message.answer("🔒 Голосовые сообщения доступны в Премиум 💎", reply_markup=kb_premium())
        return
    user = get_user(message.from_user.id)
    await message.answer("🎤 Слушаю тебя...")

    try:
        import io
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        file_path = f"/tmp/mama_voice_{message.from_user.id}.ogg"
        await bot.download_file(file.file_path, file_path)

        # Транскрибируем через Whisper
        with open(file_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ru"
            )
        text = transcript.text.strip()
        logging.info(f"Голос распознан: {text}")

        if not text:
            await message.answer("Не удалось распознать речь. Говори чуть громче и попробуй ещё раз 🎤")
            return

        # Отвечаем через GPT с контекстом мамы
        if user:
            mode, date_value, name = user
            if mode == "pregnant":
                weeks, _ = calc_pregnancy_weeks(date_value)
                context = f"Беременная женщина на {weeks} неделе."
            else:
                months, _ = calc_child_age(date_value)
                context = f"Мама, ребёнку {age_label(months)} ({months} месяцев)."
        else:
            context = "Мама с вопросом о ребёнке или беременности."

        answer = await ask_gpt(
            f"Ты эксперт в педиатрии и детской психологии. {context} "
            f"Опирайся на рекомендации ВОЗ, AAP и ведущих специалистов. "
            f"Отвечай тепло и конкретно. При медицинских симптомах направляй к врачу.",
            text
        )

        kb = kb_mama_menu() if user and user[0] == "mama" else kb_pregnant_menu() if user else kb_start()
        await message.answer(f"🎤 Ты спросила: {text}\n\n{answer}", reply_markup=kb)

    except Exception as e:
        logging.error(f"Ошибка голоса: {e}")
        await message.answer("Не удалось распознать голос. Попробуй ещё раз или напиши текстом 🤍")



# ─── ПРЕМИУМ ПРОВЕРКИ ────────────────────────────────────────
async def premium_gate(call: CallbackQuery, target_cb: str):
    if is_premium(call.from_user.id):
        # Разблокировано — вызываем нужный обработчик
        await call.data.__class__
        call.data = target_cb
        await dp.process_update(call._bot if hasattr(call, "_bot") else call)
    else:
        await call.message.answer(
            "🔒 Эта функция доступна в Премиум\n\n"
            "💎 Премиум — 299 руб/месяц\n"
            "Открывает все трекеры, анализ фото, голос и безлимитные вопросы.",
            reply_markup=kb_premium()
        )

@dp.callback_query(F.data == "check_premium_vaccines")
async def check_prem_vaccines(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await tracker_vaccines(call)
    else:
        await call.message.answer("🔒 Прививочный календарь доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_growth")
async def check_prem_growth(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await tracker_growth(call)
    else:
        await call.message.answer("🔒 Трекер роста и веса доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_symptoms")
async def check_prem_symptoms(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await tracker_symptoms(call)
    else:
        await call.message.answer("🔒 Трекер симптомов доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_feeding")
async def check_prem_feeding(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await tracker_feeding(call)
    else:
        await call.message.answer("🔒 Трекер кормлений доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_sleep")
async def check_prem_sleep(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await tracker_sleep(call)
    else:
        await call.message.answer("🔒 Дневник сна доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_benefits")
async def check_prem_benefits(call: CallbackQuery):
    if is_premium(call.from_user.id):
        await benefits_menu(call)
    else:
        await call.message.answer("🔒 Пособия и выплаты доступны в Премиум 💎", reply_markup=kb_premium())

# ─── GOOGLE SHEETS ───────────────────────────────────────────
def sheets_add_user(user_id, username, first_name, mode=""):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        try:
            sheet = spreadsheet.worksheet("МамаБот")
        except:
            sheet = spreadsheet.add_worksheet(title="МамаБот", rows=1000, cols=10)
            sheet.append_row(["ID", "Username", "Имя", "Режим", "Подписка", "Дата регистрации"])
        data = sheet.get_all_values()
        ids = [row[0] for row in data[1:]]
        if str(user_id) not in ids:
            sheet.append_row([str(user_id), username or "", first_name or "", mode, "Бесплатно", datetime.now().strftime("%d.%m.%Y %H:%M")])
    except Exception as e:
        logging.error(f"Sheets add_user error: {e}")

def sheets_add_review(user_id, username, text, sheet_name="Отзывы МамаБот"):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        try:
            sheet = spreadsheet.worksheet(sheet_name)
        except:
            sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=5)
            sheet.append_row(["ID", "Username", "Текст", "Дата"])
        sheet.append_row([str(user_id), username or "", text, datetime.now().strftime("%d.%m.%Y %H:%M")])
    except Exception as e:
        logging.error(f"Sheets add_review error: {e}")

def sheets_update_subscription(user_id, plan):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet("МамаБот")
        data = sheet.get_all_values()
        for i, row in enumerate(data):
            if row[0] == str(user_id):
                sheet.update_cell(i + 1, 5, "💎 Премиум")
                break
    except Exception as e:
        logging.error(f"Sheets update_sub error: {e}")

# ─── ЮКАССА ПЛАТЕЖИ ──────────────────────────────────────────
def kb_premium():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Оформить Премиум — 299 руб/мес", callback_data="pay_premium")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])

async def create_payment_mama(user_id):
    payment = Payment.create({
        "amount": {"value": "299.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://t.me/MaminPomoshnikAI_bot"},
        "capture": True,
        "description": f"Мамин помощник Премиум 30 дней — {user_id}",
        "receipt": {
            "customer": {"email": "client@maminpomoshnik.ru"},
            "items": [{
                "description": "Мамин помощник Премиум 30 дней",
                "quantity": "1.00",
                "amount": {"value": "299.00", "currency": "RUB"},
                "vat_code": 1,
                "payment_subject": "service",
                "payment_mode": "full_payment"
            }]
        },
        "metadata": {"user_id": user_id, "plan": "mama_premium"}
    }, str(uuid.uuid4()))
    return payment

async def check_payments_loop():
    while True:
        await asyncio.sleep(15)
        try:
            pending = get_pending_payments()
            for payment_id, user_id, plan in pending:
                try:
                    payment = Payment.find_one(payment_id)
                    if payment.status == "succeeded":
                        set_subscription(user_id, plan, 30)
                        delete_pending_payment(payment_id)
                        import asyncio as aio
                        aio.create_task(aio.to_thread(sheets_update_subscription, user_id, plan))
                        await bot.send_message(
                            user_id,
                            "✅ Оплата прошла успешно!\n\n"
                            "💎 Премиум активирован на 30 дней.\n\n"
                            "Все функции разблокированы — пользуйся на здоровье! 🤍",
                            reply_markup=kb_mama_menu() if get_user(user_id) and get_user(user_id)[0] == "mama" else kb_pregnant_menu()
                        )
                    elif payment.status == "canceled":
                        delete_pending_payment(payment_id)
                except Exception as e:
                    logging.error(f"Ошибка проверки платежа {payment_id}: {e}")
        except Exception as e:
            logging.error(f"Ошибка check_payments_loop: {e}")

@dp.callback_query(F.data == "pay_premium")
async def pay_premium(call: CallbackQuery):
    user_id = call.from_user.id
    try:
        payment = await create_payment_mama(user_id)
        save_pending_payment(payment.id, user_id, "mama_premium")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 299 руб", url=payment.confirmation.confirmation_url)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
        ])
        await call.message.answer(
            "💎 Премиум подписка — 299 руб/месяц\n\n"
            "Что открывается:\n"
            "🎤 Голосовые сообщения\n"
            "📸 Анализ фото\n"
            "📏 Все трекеры\n"
            "💉 Прививочный календарь\n"
            "💰 Подбор пособий\n"
            "❓ Безлимитные вопросы GPT\n\n"
            "После оплаты всё активируется автоматически!",
            reply_markup=kb
        )
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await call.message.answer("Ошибка при создании платежа. Напиши в поддержку " + SUPPORT_USERNAME)

@dp.callback_query(F.data == "show_premium")
async def show_premium(call: CallbackQuery):
    await call.message.answer(
        "🔒 Эта функция доступна в Премиум\n\n"
        "💎 Премиум — 299 руб/месяц\n"
        "Открывает все функции бота без ограничений.",
        reply_markup=kb_premium()
    )

# ─── ПОДДЕРЖКА И ОТЗЫВЫ ──────────────────────────────────────
class SupportStates(StatesGroup):
    waiting_support = State()
    waiting_review = State()
    waiting_suggestion = State()

@dp.callback_query(F.data == "support_menu")
async def support_menu(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆘 Написать в поддержку", callback_data="support_write")],
        [InlineKeyboardButton(text="⭐ Оставить отзыв", callback_data="review_write")],
        [InlineKeyboardButton(text="💡 Предложить идею", callback_data="suggestion_write")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")]
    ])
    await call.message.answer(
        "🤍 Поддержка и обратная связь\n\n"
        "Мы рады каждому отзыву и предложению!",
        reply_markup=kb
    )

@dp.callback_query(F.data == "support_write")
async def support_write(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_support)
    await call.message.answer(
        "🆘 Напиши своё сообщение — я перешлю его команде поддержки.\n\n"
        "Опиши проблему подробно 👇"
    )

@dp.message(SupportStates.waiting_support, F.text)
async def support_send(message: Message, state: FSMContext):
    await state.clear()
    username = message.from_user.username or "нет"
    name = message.from_user.first_name or ""
    try:
        await bot.send_message(
            SUPPORT_USERNAME,
            f"🆘 Обращение в поддержку\n"
            f"Бот: {BOT_NAME}\n"
            f"От: {name} (@{username}, ID: {message.from_user.id})\n\n"
            f"{message.text}"
        )
    except Exception as e:
        logging.error(f"Support send error: {e}")
    await message.answer(
        "✅ Сообщение отправлено! Мы ответим в ближайшее время.\n\n"
        f"Или напиши напрямую: {SUPPORT_USERNAME}",
        reply_markup=kb_mama_menu() if get_user(message.from_user.id) and get_user(message.from_user.id)[0] == "mama" else kb_start()
    )

@dp.callback_query(F.data == "review_write")
async def review_write(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_review)
    await call.message.answer("⭐ Напиши свой отзыв о боте 💕")

@dp.message(SupportStates.waiting_review, F.text)
async def review_send(message: Message, state: FSMContext):
    await state.clear()
    import threading
    threading.Thread(target=sheets_add_review, args=(
        message.from_user.id, message.from_user.username, message.text, "Отзывы МамаБот"
    )).start()
    await message.answer("⭐ Спасибо за отзыв! Это очень важно для нас 💕", reply_markup=kb_mama_menu() if get_user(message.from_user.id) and get_user(message.from_user.id)[0] == "mama" else kb_start())

@dp.callback_query(F.data == "suggestion_write")
async def suggestion_write(call: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_suggestion)
    await call.message.answer("💡 Напиши свою идею — что добавить или улучшить в боте?")

@dp.message(SupportStates.waiting_suggestion, F.text)
async def suggestion_send(message: Message, state: FSMContext):
    await state.clear()
    import threading
    threading.Thread(target=sheets_add_review, args=(
        message.from_user.id, message.from_user.username, message.text, "Предложения МамаБот"
    )).start()
    await message.answer("💡 Спасибо за идею! Мы обязательно рассмотрим её 🤍", reply_markup=kb_mama_menu() if get_user(message.from_user.id) and get_user(message.from_user.id)[0] == "mama" else kb_start())

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


# ─── ТРЕКЕР РОСТА И ВЕСА ─────────────────────────────────────
@dp.callback_query(F.data == "tracker_growth")
async def tracker_growth(call: CallbackQuery):
    user = get_user(call.from_user.id)
    entries = get_growth(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить замер", callback_data="growth_add")],
        [InlineKeyboardButton(text="📊 Анализ динамики", callback_data="growth_analyze")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if entries:
        text = "📏 Рост и вес малыша\n\n"
        for h, w, dt in entries[:5]:
            d = datetime.fromisoformat(dt).strftime("%d.%m.%Y")
            text += f"📅 {d} — рост {h} см, вес {w} кг\n"
    else:
        text = "📏 Рост и вес малыша\n\nЗамеров пока нет. Начни отслеживать!"
    await call.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "growth_add")
async def growth_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(GrowthStates.waiting_height)
    await call.message.answer("📏 Введи рост малыша в сантиметрах\nНапример: 67.5")

@dp.message(GrowthStates.waiting_height, F.text)
async def growth_height(message: Message, state: FSMContext):
    try:
        h = float(message.text.replace(",", "."))
        await state.update_data(height=h)
        await state.set_state(GrowthStates.waiting_weight)
        await message.answer("⚖️ Теперь введи вес в килограммах\nНапример: 7.2")
    except:
        await message.answer("❌ Введи число, например: 67.5")

@dp.message(GrowthStates.waiting_weight, F.text)
async def growth_weight(message: Message, state: FSMContext):
    try:
        w = float(message.text.replace(",", "."))
        data = await state.get_data()
        h = data["height"]
        save_growth(message.from_user.id, h, w)
        await state.clear()
        user = get_user(message.from_user.id)
        months = 0
        if user and user[0] == "mama":
            months, _ = calc_child_age(user[1])
        answer = await ask_gpt(
            EXPERT_BASE,
            f"Ребёнку {age_label(months)} ({months} месяцев). Рост {h} см, вес {w} кг. "
            f"Оцени эти показатели по нормам ВОЗ — в каком перцентиле находится ребёнок. "
            f"Скажи норма это или нет, и что делать если отклонение."
        )
        await message.answer(f"✅ Замер сохранён!\n\n{answer}", reply_markup=kb_mama_menu())
    except:
        await message.answer("❌ Введи число, например: 7.2")

@dp.callback_query(F.data == "growth_analyze")
async def growth_analyze(call: CallbackQuery):
    entries = get_growth(call.from_user.id)
    user = get_user(call.from_user.id)
    if not entries:
        await call.message.answer("Нет данных для анализа. Добавь хотя бы один замер!", reply_markup=kb_mama_menu())
        return
    await call.message.answer("⏳ Анализирую динамику...")
    months = 0
    if user and user[0] == "mama":
        months, _ = calc_child_age(user[1])
    data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m.%Y')}: рост {h} см, вес {w} кг"
                          for h, w, dt in entries])
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот динамика роста и веса:\n{data_str}\n\n"
        f"Проанализируй динамику по нормам ВОЗ — прибавки в норме или нет, тренд хороший или нет, "
        f"на что обратить внимание педиатру."
    )
    await call.message.answer(answer, reply_markup=kb_mama_menu())

# ─── ТРЕКЕР СИМПТОМОВ ────────────────────────────────────────
@dp.callback_query(F.data == "tracker_symptoms")
async def tracker_symptoms(call: CallbackQuery):
    entries = get_symptoms(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Записать симптом", callback_data="symptom_add")],
        [InlineKeyboardButton(text="🔍 Анализ за 7 дней", callback_data="symptom_analyze")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if entries:
        text = "🌡 Трекер симптомов\n\n"
        for s, dt in entries[:7]:
            d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
            text += f"📅 {d} — {s}\n"
    else:
        text = "🌡 Трекер симптомов\n\nЗаписей нет. Фиксируй симптомы и бот поможет отследить динамику."
    await call.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "symptom_add")
async def symptom_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(SymptomStates.waiting_symptom)
    await call.message.answer(
        "🌡 Опиши симптом малыша\n\n"
        "Например: температура 38.2, кашель, сыпь на щеках, не ест, плачет, зелёный стул\n\n"
        "Пиши как есть — бот сохранит с датой и временем."
    )

@dp.message(SymptomStates.waiting_symptom, F.text)
async def save_symptom_entry(message: Message, state: FSMContext):
    save_symptom(message.from_user.id, message.text)
    await state.clear()
    await message.answer("✅ Симптом записан!", reply_markup=kb_mama_menu())

@dp.callback_query(F.data == "symptom_analyze")
async def symptom_analyze(call: CallbackQuery):
    entries = get_symptoms(call.from_user.id)
    user = get_user(call.from_user.id)
    if not entries:
        await call.message.answer("Нет симптомов для анализа.", reply_markup=kb_mama_menu())
        return
    await call.message.answer("⏳ Анализирую симптомы...")
    months = 0
    if user and user[0] == "mama":
        months, _ = calc_child_age(user[1])
    data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {s}"
                          for s, dt in entries])
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот симптомы за последние дни:\n{data_str}\n\n"
        f"Проанализируй картину: что это может быть, какова динамика — лучше или хуже, "
        f"стоит ли идти к врачу прямо сейчас или можно наблюдать дома. "
        f"Красные флаги — если есть тревожные симптомы скажи прямо."
    )
    await call.message.answer(answer, reply_markup=kb_mama_menu())

# ─── ТРЕКЕР КОРМЛЕНИЙ ────────────────────────────────────────
@dp.callback_query(F.data == "tracker_feeding")
async def tracker_feeding(call: CallbackQuery):
    entries = get_feedings(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤱 Левая грудь", callback_data="feed_left"),
         InlineKeyboardButton(text="🤱 Правая грудь", callback_data="feed_right")],
        [InlineKeyboardButton(text="🍼 Смесь/бутылочка", callback_data="feed_bottle")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="feed_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if entries:
        text = "🤱 Трекер кормлений\n\n"
        for side, dur, dt in entries[:5]:
            d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
            text += f"📅 {d} — {side}, {dur} мин\n"
        # Время с последнего кормления
        last_dt = datetime.fromisoformat(entries[0][2])
        diff = datetime.now() - last_dt
        mins = int(diff.total_seconds() / 60)
        if mins < 60:
            text += f"\n⏱ Последнее кормление {mins} мин назад"
        else:
            text += f"\n⏱ Последнее кормление {mins // 60} ч {mins % 60} мин назад"
    else:
        text = "🤱 Трекер кормлений\n\nЗаписей нет. Нажми кнопку после каждого кормления!"
    await call.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.in_({"feed_left", "feed_right", "feed_bottle"}))
async def feed_start(call: CallbackQuery, state: FSMContext):
    sides = {"feed_left": "Левая грудь", "feed_right": "Правая грудь", "feed_bottle": "Смесь/бутылочка"}
    side = sides[call.data]
    await state.set_state(FeedingStates.waiting_duration)
    await state.update_data(side=side)
    await call.message.answer(f"⏱ Сколько минут кормила? ({side})\nВведи число:")

@dp.message(FeedingStates.waiting_duration, F.text)
async def feed_duration(message: Message, state: FSMContext):
    try:
        dur = int(message.text.strip())
        data = await state.get_data()
        save_feeding(message.from_user.id, data["side"], dur)
        await state.clear()
        await message.answer(f"✅ Кормление записано! {data['side']}, {dur} мин 🤱", reply_markup=kb_mama_menu())
    except:
        await message.answer("❌ Введи число минут, например: 15")

@dp.callback_query(F.data == "feed_stats")
async def feed_stats(call: CallbackQuery):
    entries = get_feedings(call.from_user.id)
    user = get_user(call.from_user.id)
    if not entries:
        await call.message.answer("Нет данных для анализа.", reply_markup=kb_mama_menu())
        return
    await call.message.answer("⏳ Считаю статистику...")
    months = 0
    if user and user[0] == "mama":
        months, _ = calc_child_age(user[1])
    data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {side}, {dur} мин"
                          for side, dur, dt in entries])
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот журнал кормлений:\n{data_str}\n\n"
        f"Проанализируй: достаточно ли кормлений по нормам ВОЗ для этого возраста, "
        f"правильные ли интервалы, достаточная ли продолжительность. "
        f"Дай практические рекомендации."
    )
    await call.message.answer(answer, reply_markup=kb_mama_menu())

# ─── ДНЕВНИК СНА ─────────────────────────────────────────────
@dp.callback_query(F.data == "tracker_sleep")
async def tracker_sleep(call: CallbackQuery):
    entries = get_sleep_log(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😴 Уснул", callback_data="sleep_start"),
         InlineKeyboardButton(text="🌅 Проснулся", callback_data="sleep_end")],
        [InlineKeyboardButton(text="📊 Анализ сна", callback_data="sleep_analyze")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if entries:
        text = "🌙 Дневник сна\n\n"
        for action, dt in entries[:6]:
            d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
            emoji = "😴" if action == "уснул" else "🌅"
            text += f"{emoji} {d} — {action}\n"
    else:
        text = "🌙 Дневник сна\n\nЗаписей нет. Нажимай кнопки когда малыш засыпает и просыпается!"
    await call.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "sleep_start")
async def sleep_start(call: CallbackQuery):
    save_sleep(call.from_user.id, "уснул")
    await call.message.answer("😴 Записала — малыш уснул!", reply_markup=kb_mama_menu())

@dp.callback_query(F.data == "sleep_end")
async def sleep_end(call: CallbackQuery):
    save_sleep(call.from_user.id, "проснулся")
    await call.message.answer("🌅 Записала — малыш проснулся!", reply_markup=kb_mama_menu())

@dp.callback_query(F.data == "sleep_analyze")
async def sleep_analyze(call: CallbackQuery):
    entries = get_sleep_log(call.from_user.id)
    user = get_user(call.from_user.id)
    if len(entries) < 4:
        await call.message.answer("Нужно больше записей для анализа. Фиксируй сон несколько дней!", reply_markup=kb_mama_menu())
        return
    await call.message.answer("⏳ Анализирую сон...")
    months = 0
    if user and user[0] == "mama":
        months, _ = calc_child_age(user[1])
    data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {action}"
                          for action, dt in entries])
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот дневник сна:\n{data_str}\n\n"
        f"Проанализируй паттерн сна по нормам AAP и NSF для этого возраста: "
        f"сколько часов спит суммарно, правильные ли интервалы бодрствования, "
        f"есть ли проблемы и как их решить. Конкретные рекомендации."
    )
    await call.message.answer(answer, reply_markup=kb_mama_menu())

# ─── ПРИВИВОЧНЫЙ КАЛЕНДАРЬ ───────────────────────────────────
@dp.callback_query(F.data == "tracker_vaccines")
async def tracker_vaccines(call: CallbackQuery):
    user = get_user(call.from_user.id)
    vaccinations = get_vaccinations(call.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Создать календарь", callback_data="vaccines_create")],
        [InlineKeyboardButton(text="✅ Отметить сделанную", callback_data="vaccines_done")],
        [InlineKeyboardButton(text="❓ Что такое эта прививка", callback_data="vaccines_info")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    if vaccinations:
        text = "💉 Прививочный календарь\n\n"
        for vid, vaccine, sdate, done in vaccinations[:10]:
            status = "✅" if done else "⏳"
            text += f"{status} {sdate} — {vaccine}\n"
    else:
        text = "💉 Прививочный календарь\n\nКалендарь не создан. Нажми 'Создать календарь'!"
    await call.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "vaccines_create")
async def vaccines_create(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user or user[0] != "mama":
        await call.message.answer("Сначала введи дату рождения малыша!", reply_markup=kb_mama_menu())
        return
    months, _ = calc_child_age(user[1])
    birth = datetime.strptime(user[1], "%d.%m.%Y")
    await call.message.answer("⏳ Создаю персональный календарь прививок...")

    # Стандартный календарь РФ
    schedule = [
        (0, "БЦЖ (туберкулёз)"),
        (0, "Гепатит B — 1-я доза"),
        (1, "Гепатит B — 2-я доза"),
        (2, "АКДС — 1-я доза"),
        (2, "Полиомиелит — 1-я доза"),
        (2, "Пневмококк — 1-я доза"),
        (3, "АКДС — 2-я доза"),
        (3, "Полиомиелит — 2-я доза"),
        (4, "АКДС — 3-я доза"),
        (4, "Полиомиелит — 3-я доза"),
        (4, "Пневмококк — 2-я доза"),
        (6, "Гепатит B — 3-я доза"),
        (12, "Корь, краснуха, паротит (КПК)"),
        (12, "Ветряная оспа"),
        (15, "Пневмококк — ревакцинация"),
        (18, "АКДС — ревакцинация"),
        (18, "Полиомиелит — ревакцинация"),
    ]

    added = 0
    for month_age, vaccine in schedule:
        vac_date = (birth + __import__('datetime').timedelta(days=month_age*30)).strftime("%d.%m.%Y")
        save_vaccination(call.from_user.id, vaccine, vac_date)
        added += 1

    await call.message.answer(
        f"✅ Календарь создан! Добавлено {added} прививок.\n\n"
        f"Бот будет напоминать за 3 дня до каждой прививки.",
        reply_markup=kb_mama_menu()
    )

@dp.callback_query(F.data == "vaccines_info")
async def vaccines_info(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💉 БЦЖ", callback_data="vac_bcg"),
         InlineKeyboardButton(text="💉 Гепатит B", callback_data="vac_hepb")],
        [InlineKeyboardButton(text="💉 АКДС", callback_data="vac_akds"),
         InlineKeyboardButton(text="💉 Полиомиелит", callback_data="vac_polio")],
        [InlineKeyboardButton(text="💉 Пневмококк", callback_data="vac_pneumo"),
         InlineKeyboardButton(text="💉 КПК", callback_data="vac_kpk")],
        [InlineKeyboardButton(text="💉 Ветрянка", callback_data="vac_varicella")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="tracker_vaccines")]
    ])
    await call.message.answer("Выбери прививку чтобы узнать подробнее 👇", reply_markup=kb)

async def vaccine_detail(call, vaccine_name, description):
    await call.message.answer("⏳ Подбираю информацию...")
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Дай подробное научное объяснение прививки {vaccine_name} для родителей. "
        f"1) От чего защищает и насколько опасна болезнь без прививки; "
        f"2) Как работает вакцина — механизм иммунитета; "
        f"3) Когда делают и сколько доз нужно; "
        f"4) Как подготовить ребёнка — за день до и в день прививки; "
        f"5) Нормальные реакции — что ожидать в первые дни; "
        f"6) Красные флаги — когда срочно к врачу; "
        f"7) Развенчай главные мифы о этой прививке с научными аргументами."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К прививкам", callback_data="vaccines_info")]
    ])
    await send_long_message(call.message.chat.id, answer, reply_markup=kb)

@dp.callback_query(F.data == "vac_bcg")
async def vac_bcg(call: CallbackQuery):
    await vaccine_detail(call, "БЦЖ (туберкулёз)", "")

@dp.callback_query(F.data == "vac_hepb")
async def vac_hepb(call: CallbackQuery):
    await vaccine_detail(call, "Гепатит B", "")

@dp.callback_query(F.data == "vac_akds")
async def vac_akds(call: CallbackQuery):
    await vaccine_detail(call, "АКДС (коклюш, дифтерия, столбняк)", "")

@dp.callback_query(F.data == "vac_polio")
async def vac_polio(call: CallbackQuery):
    await vaccine_detail(call, "Полиомиелит", "")

@dp.callback_query(F.data == "vac_pneumo")
async def vac_pneumo(call: CallbackQuery):
    await vaccine_detail(call, "Пневмококковая инфекция", "")

@dp.callback_query(F.data == "vac_kpk")
async def vac_kpk(call: CallbackQuery):
    await vaccine_detail(call, "КПК (корь, паротит, краснуха)", "")

@dp.callback_query(F.data == "vac_varicella")
async def vac_varicella(call: CallbackQuery):
    await vaccine_detail(call, "Ветряная оспа", "")

# ─── ПОСОБИЯ И ВЫПЛАТЫ ───────────────────────────────────────
@dp.callback_query(F.data == "benefits_menu")
async def benefits_menu(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👶 Единовременное при рождении", callback_data="ben_birth")],
        [InlineKeyboardButton(text="🤱 Пособие по уходу до 1.5 лет", callback_data="ben_15")],
        [InlineKeyboardButton(text="📅 Выплаты до 3 лет", callback_data="ben_3")],
        [InlineKeyboardButton(text="🏠 Материнский капитал", callback_data="ben_matcap")],
        [InlineKeyboardButton(text="💊 По беременности и родам", callback_data="ben_decree")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Многодетная семья", callback_data="ben_multi")],
        [InlineKeyboardButton(text="❓ Что положено именно мне", callback_data="ben_personal")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])
    await call.message.answer(
        "💰 Пособия и выплаты\n\n"
        "Узнай на что ты имеешь право 👇",
        reply_markup=kb
    )

async def benefits_gpt(call, prompt):
    await call.message.answer("⏳ Подбираю актуальную информацию...")
    answer = await ask_gpt(
        "Ты эксперт по социальным выплатам и пособиям в России. "
        "Давай актуальную информацию на 2024-2025 год. "
        "Указывай конкретные суммы, сроки подачи, необходимые документы и куда обращаться. "
        "Отвечай структурированно и понятно.",
        prompt
    )
    await call.message.answer(answer, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К пособиям", callback_data="benefits_menu")]
    ]))

@dp.callback_query(F.data == "ben_birth")
async def ben_birth(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о единовременном пособии при рождении ребёнка в России в 2024-2025 году. "
                       "Размер, кто имеет право, документы, куда подавать, сроки.")

@dp.callback_query(F.data == "ben_15")
async def ben_15(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о ежемесячном пособии по уходу за ребёнком до 1.5 лет в России 2024-2025. "
                       "Размер для работающих и неработающих мам, как рассчитывается, документы, сроки.")

@dp.callback_query(F.data == "ben_3")
async def ben_3(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о выплатах и пособиях на ребёнка от 1.5 до 3 лет в России 2024-2025. "
                       "Путинские выплаты, региональные пособия, условия получения.")

@dp.callback_query(F.data == "ben_matcap")
async def ben_matcap(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о материнском капитале в России 2024-2025. "
                       "Размер на первого и второго ребёнка, на что можно потратить, как оформить через Госуслуги, "
                       "сроки получения сертификата.")

@dp.callback_query(F.data == "ben_decree")
async def ben_decree(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о пособии по беременности и родам (декретные) в России 2024-2025. "
                       "Как рассчитывается для работающих, ИП, безработных. "
                       "Сроки декрета, документы, куда обращаться.")

@dp.callback_query(F.data == "ben_multi")
async def ben_multi(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о льготах и выплатах многодетным семьям в России 2024-2025. "
                       "Федеральные и региональные льготы, налоговые вычеты, земельные участки, "
                       "транспортный налог, ЖКХ, досрочная пенсия мамы.")

@dp.callback_query(F.data == "ben_personal")
async def ben_personal(call: CallbackQuery, state: FSMContext):
    await state.set_state(BenefitsStates.waiting_params)
    await call.message.answer(
        "❓ Расскажи о своей ситуации и я скажу что тебе положено\n\n"
        "Напиши: работаешь или нет, какой по счёту ребёнок, "
        "замужем или нет, регион проживания\n\n"
        "Например: работаю официально, второй ребёнок, замужем, Москва"
    )

@dp.message(BenefitsStates.waiting_params, F.text)
async def ben_personal_answer(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Подбираю что положено именно тебе...")
    answer = await ask_gpt(
        "Ты эксперт по социальным выплатам в России 2024-2025. "
        "Давай конкретные персональные рекомендации на основе ситуации мамы.",
        f"Мама описала свою ситуацию: {message.text}\n\n"
        f"Перечисли все федеральные и региональные пособия и выплаты на которые она имеет право. "
        f"Для каждого: название, размер, как оформить, куда обратиться. "
        f"Отсортируй по сумме — сначала самые крупные."
    )
    await message.answer(answer, reply_markup=kb_mama_menu())


# ─── МАМИН ПСИХОЛОГ ──────────────────────────────────────────
PSYCHO_SYSTEM = """Ты Мамин психолог — тёплый, внимательный, профессиональный психолог специально для мам.

Твои принципы:
- Ты помнишь всё что мама рассказывала тебе раньше — используй это в ответах
- Отвечаешь как живой человек, не как робот — с теплом, эмпатией, без шаблонов
- Опираешься на доказательные методы: КПТ (когнитивно-поведенческая терапия), ACT (терапия принятия), нарративную терапию, теорию привязанности Петрановской
- Никогда не осуждаешь маму — любое её чувство нормально
- Не даёшь советов пока не поймёшь ситуацию — сначала слушаешь и задаёшь вопросы
- Замечаешь паттерны в том что мама рассказывает и мягко указываешь на них
- Помогаешь маме понять себя, а не просто решаешь проблему
- При серьёзных симптомах (суицидальные мысли, тяжёлая депрессия) мягко направляешь к специалисту

Ты знаешь что материнство — это огромный труд. Мама важна не меньше ребёнка."""

@dp.callback_query(F.data == "check_premium_psycho")
async def check_prem_psycho(call: CallbackQuery, state: FSMContext):
    if not is_premium(call.from_user.id):
        await call.message.answer(
            "🧠 Мамин психолог доступен в Премиум 💎\n\n"
            "Персональный психолог который помнит тебя и твою историю.",
            reply_markup=kb_premium()
        )
        return
    await psycho_start(call, state)

@dp.callback_query(F.data == "psycho_start")
async def psycho_start(call: CallbackQuery, state: FSMContext):
    if not is_premium(call.from_user.id):
        await call.message.answer("🔒 Мамин психолог доступен в Премиум 💎", reply_markup=kb_premium())
        return
    await state.set_state(PsychoStates.in_session)
    history = get_psycho_history(call.from_user.id)
    user = get_user(call.from_user.id)
    name = user[2] if user and user[2] else "мама"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Начать новый диалог", callback_data="psycho_clear")],
        [InlineKeyboardButton(text="🏠 Выйти из сеанса", callback_data="psycho_exit")]
    ])
    if history:
        await call.message.answer(
            f"🧠 С возвращением, {name}!\n\n"
            f"Я помню наш последний разговор. Как ты сейчас? 💕",
            reply_markup=kb
        )
    else:
        await call.message.answer(
            f"🧠 Привет, {name}! Я твой личный психолог 💕\n\n"
            f"Здесь можно говорить обо всём — усталость, тревога, отношения, "
            f"чувство вины, злость, растерянность. Всё что накопилось.\n\n"
            f"Я слушаю. Расскажи как ты сейчас?",
            reply_markup=kb
        )

@dp.callback_query(F.data == "psycho_clear")
async def psycho_clear(call: CallbackQuery, state: FSMContext):
    clear_psycho_history(call.from_user.id)
    await state.set_state(PsychoStates.in_session)
    await call.message.answer(
        "🧠 Начинаем с чистого листа 💕\n\nКак ты сейчас?"
    )

@dp.callback_query(F.data == "psycho_exit")
async def psycho_exit(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer(
        "🧠 До встречи! Ты молодец что заботишься о себе 💕",
        reply_markup=kb_mama_menu()
    )

@dp.message(PsychoStates.in_session, F.text)
async def psycho_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = get_user(user_id)

    # Сохраняем сообщение мамы
    save_psycho_message(user_id, "user", message.text)

    # Получаем историю
    history = get_psycho_history(user_id, limit=15)

    # Строим контекст пользователя
    context = ""
    if user:
        mode, date_value, name = user
        if mode == "pregnant":
            weeks, _ = calc_pregnancy_weeks(date_value)
            context = f"Это беременная женщина на {weeks} неделе."
        else:
            months, _ = calc_child_age(date_value)
            context = f"Это мама, ребёнку {age_label(months)} ({months} месяцев)."

    await message.answer("🧠 Думаю...")

    # Строим сообщения для GPT с историей
    messages = [{"role": "system", "content": PSYCHO_SYSTEM + (f"\n\nКонтекст: {context}" if context else "")}]
    for role, content_msg in history[:-1]:  # все кроме последнего (только что сохранённого)
        messages.append({"role": role, "content": content_msg})
    messages.append({"role": "user", "content": message.text})

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=800
        )
        answer = clean_text(response.choices[0].message.content)

        # Сохраняем ответ психолога
        save_psycho_message(user_id, "assistant", answer)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Новый диалог", callback_data="psycho_clear"),
             InlineKeyboardButton(text="🏠 Выйти", callback_data="psycho_exit")]
        ])
        await message.answer(answer, reply_markup=kb)

    except Exception as e:
        logging.error(f"Psycho GPT error: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз 💕")

@dp.message(PsychoStates.in_session, F.voice)
async def psycho_voice(message: Message, state: FSMContext):
    """Голос тоже работает в сеансе психолога"""
    if not is_premium(message.from_user.id):
        await message.answer("🔒 Голосовые сообщения доступны в Премиум 💎", reply_markup=kb_premium())
        return
    try:
        file = await bot.get_file(message.voice.file_id)
        file_path = f"/tmp/mama_psycho_{message.from_user.id}.ogg"
        await bot.download_file(file.file_path, file_path)
        with open(file_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1", file=f, language="ru"
            )
        text = transcript.text.strip()
        if not text:
            await message.answer("Не удалось распознать. Говори чуть громче 🎤")
            return
        message.text = text
        await psycho_message(message, state)
    except Exception as e:
        logging.error(f"Psycho voice error: {e}")
        await message.answer("Ошибка распознавания голоса 💕")



@dp.callback_query(F.data == "vaccines_done")
async def vaccines_done(call: CallbackQuery):
    vaccinations = get_vaccinations(call.from_user.id)
    if not vaccinations:
        await call.message.answer("Нет прививок в календаре.", reply_markup=kb_mama_menu())
        return
    kb_rows = []
    for vid, vaccine, sdate, done in vaccinations:
        if not done:
            kb_rows.append([InlineKeyboardButton(
                text=f"✅ {vaccine} ({sdate})",
                callback_data=f"vac_done_{vid}"
            )])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tracker_vaccines")])
    await call.message.answer(
        "Выбери прививку которую уже сделали:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )

@dp.callback_query(F.data.startswith("vac_done_"))
async def vac_mark_done(call: CallbackQuery):
    vac_id = int(call.data.replace("vac_done_", ""))
    mark_vaccination_done(vac_id)
    await call.message.answer("✅ Прививка отмечена как сделанная!", reply_markup=kb_mama_menu())

async def check_vaccine_reminders():
    conn = sqlite3.connect("/root/mama.db")
    c = conn.cursor()
    today = date.today()
    reminder_date = (today + __import__('datetime').timedelta(days=3)).strftime("%d.%m.%Y")
    c.execute("SELECT user_id, vaccine, scheduled_date FROM vaccinations WHERE scheduled_date=? AND done=0", (reminder_date,))
    rows = c.fetchall()
    conn.close()
    for user_id, vaccine, sdate in rows:
        try:
            await bot.send_message(user_id,
                f"💉 Напоминание о прививке!\n\n"
                f"Через 3 дня ({sdate}) запланирована:\n"
                f"🔹 {vaccine}\n\n"
                f"Не забудь записаться к педиатру заранее!"
            )
        except Exception as e:
            logging.error(f"Ошибка напоминания о прививке: {e}")

# ─── ЗАПУСК ──────────────────────────────────────────────────
async def main():
    init_db()
    # Напоминания о прививках — каждый день в 9:00
    scheduler.add_job(check_vaccine_reminders, "cron", hour=9, minute=0)
    scheduler.add_job(post_morning,   "cron", hour=8,  minute=0)
    scheduler.add_job(post_10,        "cron", hour=10, minute=0)
    scheduler.add_job(post_afternoon, "cron", hour=13, minute=0)
    scheduler.add_job(post_evening,   "cron", hour=16, minute=0)
    scheduler.add_job(post_night,     "cron", hour=20, minute=0)
    scheduler.start()
    logging.info("Мамин помощник запущен!")
    asyncio.create_task(check_payments_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
