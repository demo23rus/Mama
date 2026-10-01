import asyncio
import logging
import sqlite3
import os
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, TelegramObject, BufferedInputFile, ReplyKeyboardRemove, WebAppInfo
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uuid
import base64
import hashlib
import random
import re
import httpx
import gspread
from google.oauth2.service_account import Credentials
from yookassa import Configuration, Payment
from urllib.parse import quote

APP_VERSION = "10.5.0-human-channel"
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
BOT_TOKEN = _env.get("BOT_TOKEN", "").strip()
SUPPORT_USERNAME = "@demo23rus"
OWNER_ID = int(_env.get("TG_OWNER_ID", "0") or 0)
CHANNEL_REPORT_CHAT_ID = _env.get("CHANNEL_REPORT_CHAT_ID", str(OWNER_ID) if OWNER_ID else SUPPORT_USERNAME)
BOT_NAME = "Мамин помощник"
OPENAI_KEY = _env.get("OPENAI_API_KEY", "").strip()
if not OPENAI_KEY:
    logging.warning("OPENAI_API_KEY не задан в /root/.env_mama: AI-функции будут недоступны")

# ─── ЮКАССА ──────────────────────────────────────────────────
YOOKASSA_SHOP_ID = "1363324"
YOOKASSA_SECRET  = "live_-RKE9nsi8wZiM-5f00z78E84OYSi3M0Dj9w_-pE0Mvw"
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key  = YOOKASSA_SECRET

# ─── GOOGLE SHEETS ─────────────────────────────────────────
SPREADSHEET_ID   = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
CREDENTIALS_FILE = "/root/google_credentials.json"

# ─── ИНИЦИАЛИЗАЦИЯ ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
client = AsyncOpenAI(api_key=OPENAI_KEY)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
logging.basicConfig(level=logging.INFO)

HEARTBEAT_FILE = "/tmp/mama_telegram.heartbeat"

async def heartbeat_loop():
    """Обновляет heartbeat-файл для независимого watchdog."""
    while True:
        try:
            with open(HEARTBEAT_FILE, "a", encoding="utf-8"):
                os.utime(HEARTBEAT_FILE, None)
        except Exception as exc:
            logging.error("Не удалось обновить Telegram heartbeat: %s", exc)
        await asyncio.sleep(30)

DB_PATH = "/root/mama.db"
MAX_DB_PATH = "/root/mama_max.db"
CHANNEL_VISUALS_ENABLED = _env.get("CHANNEL_VISUALS_ENABLED", "1") == "1"
OPENAI_IMAGE_MODEL = _env.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
CHANNEL_IMAGE_SIZE = _env.get("CHANNEL_IMAGE_SIZE", "1024x1024")

PLAN_CATALOG = {
    "free": {"name": "Бесплатный", "amount": "0.00", "days": 0, "type": "subscription"},
    "start": {"name": "Старт", "amount": "190.00", "days": 30, "type": "subscription"},
    "pro": {"name": "Про", "amount": "390.00", "days": 30, "type": "subscription"},
    "pro_year": {"name": "Про на год", "amount": "2990.00", "days": 365, "type": "subscription"},
}
ONE_TIME_PRODUCTS = {
    "doctor_report": {"name": "Сводка к педиатру", "amount": "149.00", "credit": "doctor_report"},
    "sleep_report": {"name": "Разбор сна за 7 дней", "amount": "199.00", "credit": "sleep_report"},
    "feeding_report": {"name": "Разбор кормлений", "amount": "149.00", "credit": "feeding_report"},
    "weekly_report": {"name": "Недельный семейный отчёт", "amount": "199.00", "credit": "weekly_report"},
    "photo_analysis": {"name": "Один анализ фото", "amount": "99.00", "credit": "photo_analysis"},
}
PAID_PLANS = {"start", "pro", "pro_year"}
PRO_PLANS = {"pro", "pro_year"}

# ─── ЛИЧНЫЙ РАЗБОР СИТУАЦИИ (отдельная платная услуга, без кредитов и подписки) ──
PERSONAL_REVIEW_PRICE_RUB = 690
PERSONAL_REVIEW_PRODUCT_CODE = "personal_mom_review"

PLAN_LIMITS = {
    "free": {"questions": 5, "psycho_messages": 15},
    "start": {"questions": 30, "psycho_messages": 50},
    "pro": {"questions": None, "psycho_messages": None},
    "pro_year": {"questions": None, "psycho_messages": None},
}
AI_FAILURE_MESSAGE = "Сейчас помощник временно не смог подготовить ответ. Попробуй ещё раз немного позже. Если вопрос срочный и касается здоровья, обратись к врачу или звони 112."



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

class EmergencyStates(StatesGroup):
    waiting_description = State()

class OwnerReviewStates(StatesGroup):
    waiting_voice = State()

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────────
def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

def _add_column_if_missing(conn, table, column, definition):
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        logging.info(f"DB migration: added {table}.{column}")

def _run_db_migrations(conn):
    """Безопасно обновляет старую mama.db без удаления пользовательских данных."""
    migrations = {
        "users": {
            "mode": "TEXT DEFAULT ''",
            "date_value": "TEXT DEFAULT ''",
            "name": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "diary": {
            "user_id": "INTEGER",
            "entry": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "growth": {
            "user_id": "INTEGER",
            "height": "REAL",
            "weight": "REAL",
            "created_at": "TEXT DEFAULT ''",
        },
        "symptoms": {
            "user_id": "INTEGER",
            "symptom": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "feeding": {
            "user_id": "INTEGER",
            "side": "TEXT DEFAULT ''",
            "duration": "INTEGER DEFAULT 0",
            "created_at": "TEXT DEFAULT ''",
        },
        "sleep_log": {
            "user_id": "INTEGER",
            "action": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "psycho_history": {
            "user_id": "INTEGER",
            "role": "TEXT DEFAULT ''",
            "content": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "vaccinations": {
            "user_id": "INTEGER",
            "vaccine": "TEXT DEFAULT ''",
            "scheduled_date": "TEXT DEFAULT ''",
            "done": "INTEGER DEFAULT 0",
            "created_at": "TEXT DEFAULT ''",
        },
        "subscriptions": {
            "plan": "TEXT DEFAULT ''",
            "sub_end": "TEXT DEFAULT ''",
        },
        "pending_payments": {
            "user_id": "INTEGER",
            "plan": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
        "requests_count": {
            "count": "INTEGER DEFAULT 0",
        },
        "channel_posts": {
            "slot": "TEXT DEFAULT ''",
            "theme": "TEXT DEFAULT ''",
            "format_name": "TEXT DEFAULT ''",
            "title": "TEXT DEFAULT ''",
            "text": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        },
    }
    for table, columns in migrations.items():
        for column, definition in columns.items():
            _add_column_if_missing(conn, table, column, definition)

    # Совместимость с возможной старой схемой MAX/ранней TG-версии.
    user_cols = _table_columns(conn, "users")
    if "first_name" in user_cols and "name" in user_cols:
        conn.execute(
            "UPDATE users SET name=COALESCE(NULLIF(name, ''), first_name, '')"
        )
    if "birth_date" in user_cols and "date_value" in user_cols:
        conn.execute(
            "UPDATE users SET date_value=COALESCE(NULLIF(date_value, ''), REPLACE(birth_date, 'pdr:', ''), '')"
        )
    if "birth_date" in user_cols and "mode" in user_cols:
        conn.execute(
            "UPDATE users SET mode=CASE "
            "WHEN COALESCE(mode, '')<>'' THEN mode "
            "WHEN birth_date LIKE 'pdr:%' THEN 'pregnant' "
            "WHEN COALESCE(birth_date, '')<>'' THEN 'mama' ELSE mode END"
        )

    # Индексы ускоряют отчёты, трекеры и напоминания на существующей базе.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_diary_user_date ON diary(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_growth_user_date ON growth(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symptoms_user_date ON symptoms(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feeding_user_date ON feeding(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sleep_user_date ON sleep_log(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_psycho_user_date ON psycho_history(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vaccinations_user_date ON vaccinations(user_id, scheduled_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_date ON channel_posts(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_slot ON channel_posts(slot, created_at)")

def init_db():
    conn = db_connect()
    conn.execute("PRAGMA journal_mode=WAL")
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
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, platform TEXT NOT NULL,
        product_type TEXT NOT NULL, product_code TEXT NOT NULL, amount TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'RUB', status TEXT NOT NULL DEFAULT 'created',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, raw_status TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS processed_payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, product_code TEXT NOT NULL, processed_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS subscription_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT UNIQUE, user_id INTEGER NOT NULL,
        plan TEXT NOT NULL, started_at TEXT NOT NULL, ends_at TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT UNIQUE, user_id INTEGER NOT NULL,
        product_code TEXT NOT NULL, amount TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_credits (
        user_id INTEGER NOT NULL, product_code TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL, PRIMARY KEY(user_id, product_code)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sales_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT UNIQUE, created_at TEXT NOT NULL,
        platform TEXT NOT NULL, user_id INTEGER NOT NULL, product_code TEXT NOT NULL,
        amount TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'RUB', ends_at TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS support_payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, platform TEXT NOT NULL,
        amount TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'RUB', status TEXT NOT NULL DEFAULT 'pending',
        variant TEXT NOT NULL DEFAULT '', source TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS personal_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL DEFAULT 'telegram',
        user_id INTEGER NOT NULL,
        situation_text TEXT NOT NULL,
        preferred_reply TEXT NOT NULL DEFAULT 'telegram',
        email TEXT DEFAULT NULL,
        consent_at TEXT NOT NULL,
        payment_id TEXT DEFAULT '',
        payment_status TEXT NOT NULL DEFAULT 'unpaid',
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        answer_file_id TEXT DEFAULT NULL,
        answer_path TEXT DEFAULT NULL,
        answered_at TEXT DEFAULT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_user ON personal_reviews(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_status ON personal_reviews(status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_payment ON personal_reviews(payment_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_user_date ON sales_events(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_support_payments_user ON support_payments(user_id, created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_counters (user_id INTEGER NOT NULL, counter TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,counter))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_periods (
        user_id INTEGER PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'free',
        period_started_at TEXT NOT NULL, period_ends_at TEXT DEFAULT '',
        questions_used INTEGER NOT NULL DEFAULT 0,
        psycho_used INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS analytics_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
        platform TEXT NOT NULL, user_id INTEGER DEFAULT 0,
        event_name TEXT NOT NULL, source TEXT DEFAULT '', details TEXT DEFAULT ''
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_analytics_event_date ON analytics_events(event_name, created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (
        invited_user_id INTEGER PRIMARY KEY,
        referrer_user_id INTEGER NOT NULL,
        platform TEXT NOT NULL,
        started_at TEXT NOT NULL,
        first_payment_at TEXT DEFAULT '',
        start_reward_granted INTEGER NOT NULL DEFAULT 0,
        payment_reward_granted INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referral_bonus_questions (
        user_id INTEGER PRIMARY KEY,
        bonus_questions INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id, started_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS marketing_offers (
        user_id INTEGER NOT NULL, offer_type TEXT NOT NULL, last_shown_at TEXT NOT NULL,
        show_count INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id, offer_type)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_marketing_offers_user_date ON marketing_offers(user_id, last_shown_at)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests_count (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot TEXT DEFAULT '',
            theme TEXT DEFAULT '',
            format_name TEXT DEFAULT '',
            title TEXT DEFAULT '',
            text TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)
    c.execute("""CREATE TABLE IF NOT EXISTS broadcast_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, broadcast_key TEXT NOT NULL, platform TEXT NOT NULL,
        user_id INTEGER NOT NULL, status TEXT NOT NULL, error_code TEXT DEFAULT '', ts TEXT NOT NULL,
        UNIQUE(broadcast_key, platform, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback_campaign_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_key TEXT NOT NULL, platform TEXT NOT NULL,
        user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(campaign_key, platform, user_id)
    )""")
    _run_db_migrations(conn)
    conn.commit()
    conn.close()

def save_user(user_id, mode, date_value, name=""):
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO users (user_id, mode, date_value, name, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, mode, date_value, name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT mode, date_value, name FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_diary(user_id, entry):
    conn = db_connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO diary (user_id, entry, created_at)
        VALUES (?, ?, ?)
    """, (user_id, entry, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_diary(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT entry, created_at FROM diary WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_growth(user_id, height, weight):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?, ?, ?, ?)",
              (user_id, height, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_growth(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_symptom(user_id, symptom):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?, ?, ?)",
              (user_id, symptom, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_symptoms(user_id, days=7):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_feeding(user_id, side, duration):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO feeding (user_id, side, duration, created_at) VALUES (?, ?, ?, ?)",
              (user_id, side, duration, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_feedings(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT side, duration, created_at FROM feeding WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_sleep(user_id, action):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO sleep_log (user_id, action, created_at) VALUES (?, ?, ?)",
              (user_id, action, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_sleep_log(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT action, created_at FROM sleep_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def _normalize_plan(plan):
    return "pro" if plan == "mama_premium" else plan if plan in PLAN_CATALOG else "free"

def get_subscription(user_id):
    conn=db_connect(); row=conn.execute("SELECT plan, sub_end FROM subscriptions WHERE user_id=?",(user_id,)).fetchone()
    if not row or not row[1]: conn.close(); return "free", None
    plan=_normalize_plan(row[0])
    try: end=datetime.fromisoformat(row[1])
    except (TypeError,ValueError):
        conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?, 'free','')",(user_id,)); conn.commit(); conn.close(); return "free",None
    if end<=datetime.now():
        conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?, 'free','')",(user_id,)); conn.commit(); conn.close(); return "free",None
    if plan!=row[0]: conn.execute("UPDATE subscriptions SET plan=? WHERE user_id=?",(plan,user_id)); conn.commit()
    conn.close(); return plan,end

def set_subscription(user_id,plan,days):
    plan=_normalize_plan(plan)
    if plan not in PAID_PLANS: raise ValueError(f"Недопустимый тариф: {plan}")
    now=datetime.now(); _,current_end=get_subscription(user_id); start=current_end if current_end and current_end>now else now; end=start+timedelta(days=days)
    with db_connect() as conn: conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)",(user_id,plan,end.isoformat()))
    return end

def is_premium(user_id):
    plan,end=get_subscription(user_id); return plan in PAID_PLANS and end is not None

def _usage_period_row(user_id, conn=None):
    own = conn is None
    conn = conn or db_connect()
    plan = get_user_plan(user_id)
    now = datetime.now()
    row = conn.execute(
        "SELECT plan,period_started_at,period_ends_at,questions_used,psycho_used FROM usage_periods WHERE user_id=?",
        (user_id,),
    ).fetchone()
    expired = False
    if row and row[2]:
        try:
            expired = datetime.fromisoformat(row[2]) <= now
        except ValueError:
            expired = True
    if not row or row[0] != plan or (plan == "start" and expired):
        legacy_q = 0
        legacy_p = 0
        if not row and plan == "free":
            old_q = conn.execute("SELECT count FROM requests_count WHERE user_id=?", (user_id,)).fetchone()
            legacy_q = int(old_q[0]) if old_q else 0
            old_p = conn.execute("SELECT value FROM usage_counters WHERE user_id=? AND counter='psycho_messages'", (user_id,)).fetchone()
            legacy_p = int(old_p[0]) if old_p else 0
        period_end = (now + timedelta(days=30)).isoformat() if plan == "start" else ""
        conn.execute(
            "INSERT OR REPLACE INTO usage_periods(user_id,plan,period_started_at,period_ends_at,questions_used,psycho_used,updated_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, plan, now.isoformat(), period_end, legacy_q, legacy_p, now.isoformat()),
        )
        row = (plan, now.isoformat(), period_end, legacy_q, legacy_p)
        if own:
            conn.commit()
    if own:
        conn.close()
    return row


def reset_usage_period(user_id, plan, conn=None):
    own = conn is None
    conn = conn or db_connect()
    now = datetime.now()
    period_end = (now + timedelta(days=30)).isoformat() if plan == "start" else ""
    conn.execute(
        "INSERT OR REPLACE INTO usage_periods(user_id,plan,period_started_at,period_ends_at,questions_used,psycho_used,updated_at) VALUES (?,?,?,?,0,0,?)",
        (user_id, plan, now.isoformat(), period_end, now.isoformat()),
    )
    if own:
        conn.commit(); conn.close()


def get_request_count(user_id):
    return int(_usage_period_row(user_id)[3])


def increment_request_count(user_id):
    row = _usage_period_row(user_id)
    used = int(row[3] or 0)
    base = PLAN_LIMITS[get_user_plan(user_id)]["questions"]
    now = datetime.now().isoformat()
    with db_connect() as conn:
        if base is not None and used >= int(base):
            bonus = conn.execute("SELECT bonus_questions FROM referral_bonus_questions WHERE user_id=?", (user_id,)).fetchone()
            if bonus and int(bonus[0] or 0) > 0:
                conn.execute("UPDATE referral_bonus_questions SET bonus_questions=bonus_questions-1,updated_at=? WHERE user_id=?", (now,user_id))
                return
        conn.execute("UPDATE usage_periods SET questions_used=questions_used+1,updated_at=? WHERE user_id=?", (now,user_id))


def log_analytics_event(event_name, user_id=0, source="", details=""):
    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO analytics_events(created_at,platform,user_id,event_name,source,details) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(), "telegram", int(user_id or 0), event_name, source or "", str(details or "")[:1000]),
            )
    except Exception as exc:
        logging.error(f"Analytics TG error: {exc}")

def _referral_month_start():
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def get_referral_bonus_questions(user_id):
    with db_connect() as conn:
        row = conn.execute("SELECT bonus_questions FROM referral_bonus_questions WHERE user_id=?", (user_id,)).fetchone()
    return int(row[0] or 0) if row else 0


def register_referral(invited_user_id, referrer_user_id):
    """Фиксирует первое приглашение и начисляет до 5 бонусных вопросов в месяц."""
    try:
        invited_user_id = int(invited_user_id)
        referrer_user_id = int(referrer_user_id)
    except (TypeError, ValueError):
        return None
    if invited_user_id <= 0 or referrer_user_id <= 0 or invited_user_id == referrer_user_id:
        return None
    now = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute("SELECT 1 FROM referrals WHERE invited_user_id=?", (invited_user_id,)).fetchone()
        if exists:
            conn.rollback(); return None
        conn.execute(
            "INSERT INTO referrals(invited_user_id,referrer_user_id,platform,started_at) VALUES (?,?,?,?)",
            (invited_user_id, referrer_user_id, "telegram", now),
        )
        rewarded_this_month = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_user_id=? AND start_reward_granted=1 AND started_at>=?",
            (referrer_user_id, _referral_month_start()),
        ).fetchone()[0]
        granted = rewarded_this_month < 5
        if granted:
            conn.execute(
                "INSERT INTO referral_bonus_questions(user_id,bonus_questions,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET bonus_questions=bonus_questions+1,updated_at=excluded.updated_at",
                (referrer_user_id, 1, now),
            )
            conn.execute("UPDATE referrals SET start_reward_granted=1 WHERE invited_user_id=?", (invited_user_id,))
        conn.commit()
    log_analytics_event("referral_started", invited_user_id, f"ref_{referrer_user_id}", "bonus=1" if granted else "monthly_cap")
    return referrer_user_id if granted else None


def reward_referrer_for_first_payment(invited_user_id, conn):
    """Один раз начисляет пригласившему 7 дней Про после первой оплаты приглашённого."""
    row = conn.execute(
        "SELECT referrer_user_id,payment_reward_granted FROM referrals WHERE invited_user_id=?",
        (invited_user_id,),
    ).fetchone()
    if not row or int(row[1] or 0):
        return None
    referrer_id = int(row[0])
    now = datetime.now()
    sub = conn.execute("SELECT plan,sub_end FROM subscriptions WHERE user_id=?", (referrer_id,)).fetchone()
    reward_plan = sub[0] if sub and sub[0] in ("pro", "pro_year") else "pro"
    start = now
    if sub and sub[1]:
        try:
            old_end = datetime.fromisoformat(sub[1])
            if old_end > now:
                start = old_end
        except (TypeError, ValueError):
            pass
    end = start + timedelta(days=7)
    conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)", (referrer_id, reward_plan, end.isoformat()))
    conn.execute(
        "UPDATE referrals SET payment_reward_granted=1,first_payment_at=? WHERE invited_user_id=?",
        (now.isoformat(), invited_user_id),
    )
    return referrer_id


def referral_stats(user_id):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*),COALESCE(SUM(start_reward_granted),0),COALESCE(SUM(payment_reward_granted),0) "
            "FROM referrals WHERE referrer_user_id=?",
            (user_id,),
        ).fetchone()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def referral_link_tg(user_id):
    return f"https://t.me/MaminPomoshnikAI_bot?start=ref_{int(user_id)}"


def save_pending_payment(payment_id,user_id,plan,amount=None):
    plan=_normalize_plan(plan); info=PLAN_CATALOG[plan]; now=datetime.now().isoformat(); amount=amount or info["amount"]
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)",(payment_id,user_id,plan,now))
        conn.execute("INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(payment_id,user_id,"telegram","subscription",plan,amount,"RUB","pending",now,now))

def get_pending_payments():
    conn=db_connect(); rows=conn.execute("SELECT payment_id,user_id,plan FROM pending_payments").fetchall(); conn.close(); return rows

def mark_payment_canceled(payment_id):
    now=datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("UPDATE payments SET status='canceled',raw_status='canceled',updated_at=? WHERE payment_id=?",(now,payment_id)); conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))
        conn.execute("UPDATE support_payments SET status='canceled',updated_at=? WHERE payment_id=?",(now,payment_id))

def process_subscription_payment(payment_id,user_id,plan):
    plan=_normalize_plan(plan); info=PLAN_CATALOG[plan]; now=datetime.now(); conn=db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM processed_payments WHERE payment_id=?",(payment_id,)).fetchone(): conn.rollback(); return False,None
        row=conn.execute("SELECT sub_end FROM subscriptions WHERE user_id=?",(user_id,)).fetchone(); start=now
        if row and row[0]:
            try:
                old=datetime.fromisoformat(row[0]); start=old if old>now else now
            except ValueError: pass
        end=start+timedelta(days=info["days"]); now_iso=now.isoformat()
        conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)",(user_id,plan,end.isoformat()))
        conn.execute("INSERT INTO processed_payments(payment_id,user_id,product_code,processed_at) VALUES (?,?,?,?)",(payment_id,user_id,plan,now_iso))
        conn.execute("INSERT INTO subscription_history(payment_id,user_id,plan,started_at,ends_at,created_at) VALUES (?,?,?,?,?,?)",(payment_id,user_id,plan,start.isoformat(),end.isoformat(),now_iso))
        reset_usage_period(user_id, plan, conn=conn)
        conn.execute("UPDATE payments SET status='processed',raw_status='succeeded',updated_at=? WHERE payment_id=?",(now_iso,payment_id))
        conn.execute("INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)",(payment_id,now_iso,"telegram",user_id,plan,info["amount"],"RUB",end.isoformat()))
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))
        reward_referrer_for_first_payment(user_id, conn)
        conn.commit(); return True,end
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def delete_pending_payment(payment_id):
    with db_connect() as conn: conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))



def get_user_plan(user_id):
    plan, end = get_subscription(user_id)
    return plan if end else "free"


def plan_rank(plan):
    return {"free": 0, "start": 1, "pro": 2, "pro_year": 2}.get(plan, 0)


def has_plan_access(user_id, minimum="start"):
    # Проект бесплатный: весь функционал доступен всем без тарифа.
    return True


def get_credit(user_id, product_code):
    conn = db_connect()
    row = conn.execute(
        "SELECT credits FROM user_credits WHERE user_id=? AND product_code=?",
        (user_id, product_code),
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def add_credit(user_id, product_code, amount=1, conn=None):
    own_conn = conn is None
    conn = conn or db_connect()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO user_credits(user_id,product_code,credits,updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id,product_code) DO UPDATE SET credits=credits+excluded.credits, updated_at=excluded.updated_at",
        (user_id, product_code, amount, now),
    )
    if own_conn:
        conn.commit(); conn.close()


def consume_credit(user_id, product_code):
    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT credits FROM user_credits WHERE user_id=? AND product_code=?",
            (user_id, product_code),
        ).fetchone()
        if not row or int(row[0]) <= 0:
            conn.rollback(); return False
        conn.execute(
            "UPDATE user_credits SET credits=credits-1,updated_at=? WHERE user_id=? AND product_code=?",
            (datetime.now().isoformat(), user_id, product_code),
        )
        conn.commit(); return True
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def can_use_product(user_id, product_code):
    # Проект бесплатный: разовые разборы и отчёты доступны без покупки.
    return True


def question_limit_for(user_id):
    # Проект бесплатный: лимит AI-вопросов снят для всех тарифов.
    return None


def psycho_limit_for(user_id):
    # Проект бесплатный: лимит поддерживающего диалога снят для всех тарифов.
    return None


FUNNEL_QUESTION_PROMPTS = {
    "funnel_sleep": "🌙 Опиши, что происходит со сном ребёнка: возраст, время подъёма, дневные сны, укладывание и что тревожит больше всего.",
    "funnel_feeding": "🥣 Опиши вопрос о питании или кормлении: возраст ребёнка, тип питания и что именно вызывает сомнения.",
    "funnel_development": "👶 Напиши возраст ребёнка и навык или поведение, которое хочешь проверить по возрасту.",
    "funnel_tantrum": "🧠 Опиши последнюю истерику: возраст, что произошло перед ней и как ребёнок успокоился.",
    "funnel_garden": "🎒 Опиши, что происходит с садиком: возраст ребёнка, как давно ходит, когда тяжелее всего и что уже пробовали.",
    "funnel_school": "📚 Опиши ситуацию со школой, уроками или оценками: возраст ребёнка, что вызывает конфликт и как он обычно заканчивается.",
    "funnel_gadgets": "📱 Опиши ситуацию с гаджетами: возраст ребёнка, сколько экранного времени сейчас и из-за чего чаще всего спорите.",
    "funnel_grandma": "👵 Опиши ситуацию с бабушками или родственниками: о чём спор, где нужна граница и какого разговора ты хочешь.",
    "funnel_doctor": "🩺 Опиши симптомы и наблюдения. Я помогу собрать важное и подготовить вопросы врачу. Диагноз бот не ставит.",
    "funnel_mom": "🤍 Расскажи, что сейчас даётся тяжелее всего. Я помогу спокойно разобрать ситуацию по шагам.",
    "funnel_family": "👨‍👩‍👧 Опиши семейную ситуацию и чего ты хочешь добиться в следующем разговоре.",
    "funnel_pregnancy": "🤰 Напиши срок беременности и вопрос, который сейчас волнует больше всего.",
}


CHANNEL_LANDING = {
    "channel_today": {
        "title": "Получить персональный ответ",
        "free": "Ответьте на один вопрос — получите короткий план по вашей ситуации.",
        "button": "Задать вопрос",
        "callback": "ask_question",
    },
    "channel_doctor": {
        "title": "Ребёнок заболел — подготовить вопросы врачу",
        "free": "Сейчас помогу собрать симптомы, что записать перед приёмом и какие вопросы задать врачу.",
        "button": "Подготовить вопросы врачу",
        "callback": "funnel_doctor",
    },
    "channel_sleep": {
        "title": "Плохо спит — разобрать режим",
        "free": "Ответьте на несколько вопросов — получите первичный разбор режима и 2–3 идеи, что попробовать сегодня.",
        "button": "Разобрать сон ребёнка",
        "callback": "funnel_sleep",
    },
    "channel_tantrum": {
        "title": "Истерики и поведение — получить план действий",
        "free": "Сначала бесплатно разберём ситуацию: что делать родителю, чего лучше не делать и что сказать ребёнку.",
        "button": "Понять, что делать при истерике",
        "callback": "funnel_tantrum",
    },
    "channel_garden": {
        "title": "Не хочет в садик — понять, что делать",
        "free": "Соберём короткий чек-лист адаптации, вопросы воспитателю и способ облегчить утро.",
        "button": "Разобрать адаптацию к садику",
        "callback": "funnel_garden",
    },
    "channel_school": {
        "title": "Школа, уроки, оценки — получить подсказки",
        "free": "Получите короткий план по одной ситуации, вопросы ребёнку после школы и идею, как снизить конфликт.",
        "button": "Получить подсказки по школе",
        "callback": "funnel_school",
    },
    "channel_feeding": {
        "title": "Что приготовить ребёнку",
        "free": "Подберём 1–3 идеи завтрака, перекуса или ужина и простой рецепт из доступных продуктов.",
        "button": "Получить подсказку по питанию",
        "callback": "funnel_feeding",
    },
    "channel_psycho": {
        "title": "Мама устала — поговорить с помощником",
        "free": "Можно начать с бесплатных сообщений психологическому помощнику и собрать короткий план разгрузки на день.",
        "button": "Поговорить с психологическим помощником",
        "callback": "psycho_start",
    },
    "channel_grandma": {
        "title": "Бабушки и воспитание — договориться без ссоры",
        "free": "Соберём готовые фразы для разговора и способ обозначить границы без конфликта.",
        "button": "Подготовить разговор",
        "callback": "funnel_grandma",
    },
    "channel_gadgets": {
        "title": "Гаджеты и экранное время",
        "free": "Соберём короткий план семейных правил, чтобы телефон не превращался в постоянную войну.",
        "button": "Составить правила экранного времени",
        "callback": "funnel_gadgets",
    },
    "channel_child": {
        "title": "Понять развитие ребёнка по возрасту",
        "free": "Опишите возраст и навык — получите спокойную подсказку, что обычно важно проверить.",
        "button": "Проверить развитие",
        "callback": "funnel_development",
    },
    "channel_family": {
        "title": "Семейная ситуация — подготовить разговор",
        "free": "Разберём, что важно сказать, где поставить границу и как не усиливать конфликт.",
        "button": "Подготовить разговор",
        "callback": "funnel_family",
    },
    "channel_pregnancy": {
        "title": "Беременность — получить подсказку по сроку",
        "free": "Напишите срок и вопрос — получите понятный бесплатный ответ с учётом беременности.",
        "button": "Задать вопрос по беременности",
        "callback": "funnel_pregnancy",
    },
}


def channel_landing_tg(payload):
    item = CHANNEL_LANDING.get(payload, CHANNEL_LANDING["channel_today"])
    text = (
        f"{item['title']}\n\n"
        f"{item['free']}\n\n"
        "Это не заменяет врача или специалиста, но поможет не забыть важное.\n\n"
        "Ответ бесплатный — как и все остальные функции «Маминого помощника»."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=item["button"], callback_data=item["callback"])],
        [InlineKeyboardButton(text="Все функции Маминого помощника", callback_data="main_menu")],
    ])
    return text, markup


def _question_next_action(question_text, mode="mama"):
    text = (question_text or "").lower()
    rules = [
        (("сон", "засып", "просып", "режим"), "🌙 Ещё вопрос о сне", "funnel_sleep"),
        (("корм", "питан", "прикорм", "смесь", "гв"), "🥣 Уточнить питание", "funnel_feeding"),
        (("истер", "каприз", "плач", "поведен"), "🧠 Понять поведение", "funnel_tantrum"),
        (("сад", "адаптац", "воспитател"), "🎒 Разобрать садик", "funnel_garden"),
        (("школ", "урок", "оцен"), "📚 Разобрать школу", "funnel_school"),
        (("гаджет", "телефон", "экран", "мультик"), "📱 Настроить правила", "funnel_gadgets"),
        (("бабуш", "дедуш", "родствен", "границ"), "👵 Подготовить разговор", "funnel_grandma"),
        (("развит", "речь", "навык", "возраст"), "👶 Проверить развитие", "funnel_development"),
        (("врач", "температур", "сып", "симптом", "болит", "лекар"), "🩺 Подготовить вопросы врачу", "funnel_doctor"),
        (("муж", "пап", "отношен", "семь"), "👨‍👩‍👧 Разобрать семью", "funnel_family"),
        (("устал", "тревог", "выгор", "тяжело", "одиноко"), "🤍 Разобрать мою ситуацию", "funnel_mom"),
    ]
    for words, label, callback in rules:
        if any(w in text for w in words): return label, callback
    return ("🤰 Ещё вопрос о беременности", "funnel_pregnancy") if mode == "pregnant" else ("❓ Задать ещё вопрос", "ask_question")


def build_question_funnel_tg(user_id, question_text=""):
    # Проект бесплатный: без счётчика оставшихся вопросов и без цен.
    user = get_user(user_id); mode = user[0] if user else "mama"
    next_label, next_callback = _question_next_action(question_text, mode)
    text = "✨ Готово. Можно продолжить с ещё одним вопросом."
    rows = [[InlineKeyboardButton(text=next_label, callback_data=next_callback)]]
    lower_question = (question_text or "").lower()
    soft_offer = ""
    if any(word in lower_question for word in ("врач", "температур", "сып", "симптом", "болит", "лекар")):
        soft_offer = "Если нужно, бот может собрать полную сводку для врача по вашим ответам — это бесплатно."
    elif any(word in lower_question for word in ("сон", "засып", "просып", "режим")):
        soft_offer = "Если проблема повторяется, можно сделать подробный разбор сна с учётом возраста и режима."
    elif any(word in lower_question for word in ("корм", "питан", "прикорм", "смесь", "гв", "рецепт", "ужин", "завтрак")):
        soft_offer = "Если нужна более точная картина, можно продолжить разбор питания или кормлений."
    elif any(word in lower_question for word in ("истер", "каприз", "поведен", "сад", "школ", "урок", "оцен", "гаджет", "телефон", "экран", "бабуш", "границ")):
        soft_offer = "Если ситуация повторяется часто, её можно разобрать подробнее с персональным планом."
    if soft_offer:
        text += "\n\n" + soft_offer
    rows.append([InlineKeyboardButton(text="📣 Вернуться в канал", url="https://t.me/yamama_ai")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def get_usage_counter(user_id, counter):
    if counter == "psycho_messages":
        return int(_usage_period_row(user_id)[4])
    conn = db_connect()
    row = conn.execute("SELECT value FROM usage_counters WHERE user_id=? AND counter=?", (user_id, counter)).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def increment_usage_counter(user_id, counter):
    if counter == "psycho_messages":
        _usage_period_row(user_id)
        with db_connect() as conn:
            conn.execute("UPDATE usage_periods SET psycho_used=psycho_used+1,updated_at=? WHERE user_id=?", (datetime.now().isoformat(), user_id))
        return
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO usage_counters(user_id,counter,value,updated_at) VALUES (?,?,1,?) "
            "ON CONFLICT(user_id,counter) DO UPDATE SET value=value+1,updated_at=excluded.updated_at",
            (user_id, counter, datetime.now().isoformat()),
        )


def can_show_marketing_offer(user_id, offer_type, global_hours=24, repeat_hours=72):
    # Проект бесплатный: больше не предлагаем купить тариф.
    return False
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT offer_type,last_shown_at FROM marketing_offers WHERE user_id=? ORDER BY last_shown_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    now = datetime.now()
    for old_type, shown_at in rows:
        try:
            shown = datetime.fromisoformat(shown_at)
        except (TypeError, ValueError):
            continue
        hours = (now - shown).total_seconds() / 3600
        if hours < global_hours:
            return False
        if old_type == offer_type and hours < repeat_hours:
            return False
    return True


def record_marketing_offer(user_id, offer_type):
    now = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO marketing_offers(user_id,offer_type,last_shown_at,show_count) VALUES (?,?,?,1) "
            "ON CONFLICT(user_id,offer_type) DO UPDATE SET last_shown_at=excluded.last_shown_at,show_count=show_count+1",
            (user_id, offer_type, now),
        )


def offer_markup(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def maybe_send_marketing_offer(chat_id, user_id, offer_type, text, rows):
    if not can_show_marketing_offer(user_id, offer_type):
        return False
    try:
        await bot.send_message(chat_id, text, reply_markup=offer_markup(rows), disable_web_page_preview=True)
        record_marketing_offer(user_id, offer_type)
        return True
    except Exception as exc:
        logging.error(f"Не удалось показать мягкий оффер {offer_type}: {exc}")
        return False


def callback_feature(payload):
    # Проект бесплатный: ни один callback больше не требует тарифа или покупки.
    return None

def save_vaccination(user_id, vaccine, scheduled_date):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO vaccinations (user_id, vaccine, scheduled_date, created_at) VALUES (?, ?, ?, ?)",
              (user_id, vaccine, scheduled_date, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_vaccinations(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT id, vaccine, scheduled_date, done FROM vaccinations WHERE user_id=? ORDER BY scheduled_date", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_psycho_message(user_id, role, content):
    conn = db_connect()
    c = conn.cursor()
    c.execute("INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
              (user_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_psycho_history(user_id, limit=15):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def clear_psycho_history(user_id):
    conn = db_connect()
    conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def mark_vaccination_done(vac_id, user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("UPDATE vaccinations SET done=1 WHERE id=? AND user_id=?", (vac_id, user_id))
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
    text = clean_text(str(text))
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

_LAST_OWNER_ERRORS = {}

async def notify_owner_tg(text, key="general", cooldown_minutes=30):
    target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
    if not target:
        return
    now = datetime.now()
    last = _LAST_OWNER_ERRORS.get(key)
    if last and (now - last).total_seconds() < cooldown_minutes * 60:
        return
    _LAST_OWNER_ERRORS[key] = now
    try:
        await bot.send_message(target, clean_text(text)[:3900])
    except Exception as exc:
        logging.error(f"Owner notify TG error: {exc}")

async def show_typing(chat_id):
    """Показывает системный индикатор набора вместо отдельного сообщения-заглушки."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass


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
        logging.exception("Ошибка AI Telegram")
        await notify_owner_tg(f"⚠️ Ошибка AI Telegram\n\n{type(e).__name__}: {e}", key=f"ai_{type(e).__name__}")
        return AI_FAILURE_MESSAGE


def ai_answer_success(answer):
    return bool(answer and answer != AI_FAILURE_MESSAGE)



def channel_visual_subject(theme="", title="", body="", format_name=""):
    text = " ".join([theme or "", title or "", body or "", format_name or ""]).lower()
    mapping = [
        (("сон", "недосып", "засып", "пробуж"), "реальная домашняя сцена сна малыша или тихого укладывания"),
        (("корм", "гв", "груд", "прикорм", "питан", "смесь"), "реальная сцена кормления малыша или семейного приёма пищи"),
        (("врач", "симптом", "здоров", "температур", "сып", "лекар", "боле", "педиатр"), "реальная заботливая сцена наблюдения за самочувствием ребёнка дома, без медицинской драмы"),
        (("развит", "возраст", "игр", "заняти", "навык", "речь"), "мама или папа естественно играют и занимаются с ребёнком по возрасту"),
        (("истер", "каприз", "эмоц", "устал", "тревог", "вина", "психолог", "выгор"), "узнаваемая жизненная сцена усталой мамы и бережной поддержки рядом"),
        (("отношен", "муж", "пап", "семь", "партн", "близост", "бабуш"), "естественная семейная сцена с мамой, папой и ребёнком без постановочного позирования"),
        (("беремен", "род", "восстанов", "срок"), "реальная спокойная сцена беременности или восстановления мамы после родов"),
    ]
    for keywords, subject in mapping:
        if any(word in text for word in keywords):
            return subject
    return "естественная современная семейная сцена с мамой и ребёнком"


VISUAL_SHOT_OPTIONS = [
    "крупный эмоциональный план с акцентом на лица и жесты",
    "средний семейный план с живым взаимодействием в кадре",
    "общий план комнаты с заметной домашней средой и действием",
    "репортажный кадр немного сбоку, как будто момент пойман случайно",
    "полуверхний ракурс с ощущением спокойной бытовой жизни",
    "естественный кадр на уровне глаз ребёнка или мамы",
]

VISUAL_ROOM_OPTIONS = [
    "светлая спальня или детская с мягкими домашними деталями",
    "уютная кухня или столовая зона без постановочного декора",
    "гостиная с пледом, креслом, диваном и реальной семейной атмосферой",
    "спокойный уголок у окна с естественным светом и воздухом",
    "домашний интерьер с кроваткой, игрушками и аккуратным lived-in feel",
    "небольшая современная квартира с мягким минималистичным интерьером",
]

VISUAL_MOOD_OPTIONS = [
    "спокойная забота и эмоциональная близость",
    "тёплая поддержка и ощущение неидеальной, но живой семьи",
    "мягкое умиротворение без искусственной улыбчивости",
    "нежный бытовой реализм с узнаваемой жизненной правдой",
    "бережная усталость и тепло дома",
    "ощущение доверия, безопасности и домашней поддержки",
]

VISUAL_DETAIL_OPTIONS = [
    "в кадре заметны натуральные бытовые детали: чашка, плед, игрушки, книга или детские вещи",
    "в кадре ощущается жилая среда: немного вещей, текстиль, кроватка, подушка или мягкий беспорядок",
    "детали окружения должны поддерживать сюжет, но не перегружать сцену",
    "добавь одну-две реалистичные семейные детали, которые делают сцену живой и узнаваемой",
    "интерьер должен выглядеть современно и спокойно, без рекламной вылизанности",
]

VISUAL_ACTION_OPTIONS = {
    "sleep": [
        "мама мягко укладывает малыша, поправляет одеяло или сидит рядом с кроваткой",
        "родитель держит сонного малыша на руках в тихом домашнем моменте",
        "мама сидит рядом во время спокойного засыпания или ночного пробуждения",
    ],
    "feeding": [
        "мама кормит малыша грудью или из бутылочки в естественной домашней позе",
        "родители организуют спокойный семейный приём пищи или прикорм малыша",
        "мама заботливо кормит ребёнка, а малыш взаимодействует естественно и живо",
    ],
    "health": [
        "мама внимательно наблюдает за состоянием ребёнка дома без драматизации",
        "родитель успокаивает малыша и проверяет его самочувствие в спокойной обстановке",
        "семейная сцена домашней заботы: объятие, наблюдение, термометр или плед без акцента на болезни",
    ],
    "development": [
        "мама или папа играют с ребёнком по возрасту, вовлечённо и естественно",
        "семья вместе занимается простой домашней активностью или развивающей игрой",
        "родитель показывает ребёнку книгу, игрушку или сенсорную игру в тёплом домашнем моменте",
    ],
    "emotions": [
        "уставшая мама получает мягкую поддержку от близкого человека или отдыхает рядом с ребёнком",
        "мама и ребёнок переживают тихий эмоциональный момент поддержки и близости",
        "семейная сцена, где читается усталость, но есть тепло, участие и забота",
    ],
    "family": [
        "мама, папа и ребёнок взаимодействуют естественно, как живая семья, без позирования",
        "семейная сцена разговора, объятия или совместного простого действия дома",
        "домашний момент участия отца: он рядом, помогает, держит ребёнка или поддерживает маму",
    ],
    "pregnancy": [
        "беременная женщина спокойно находится дома, касается живота или отдыхает в мягком свете",
        "пара проживает тёплый момент беременности в уютном домашнем интерьере",
        "реальная сцена заботы о беременной женщине без глянцевой постановки",
    ],
    "default": [
        "естественный семейный момент с мамой и ребёнком в домашнем интерьере",
        "тёплая бытовая сцена заботы и близости между взрослым и ребёнком",
        "редакционный lifestyle-кадр живой семьи в спокойной домашней среде",
    ],
}


def _channel_visual_category(theme="", title="", body="", format_name=""):
    text = " ".join([theme or "", title or "", body or "", format_name or ""]).lower()
    checks = [
        (("сон", "засып", "пробуж", "уклады"), "sleep"),
        (("корм", "гв", "прикорм", "смесь", "питан"), "feeding"),
        (("врач", "симптом", "здоров", "температ", "сып", "педиатр", "лекар"), "health"),
        (("развит", "игр", "заняти", "навык", "речь", "книг"), "development"),
        (("эмоц", "истер", "каприз", "устал", "тревог", "вина", "выгор", "психолог"), "emotions"),
        (("отношен", "семь", "муж", "пап", "партн", "близост"), "family"),
        (("беремен", "род", "восстанов", "срок"), "pregnancy"),
    ]
    for words, cat in checks:
        if any(word in text for word in words):
            return cat
    return "default"



def build_channel_visual_variation(slot, theme, title, body, format_name, attempt=1):
    seed = f"{slot}|{theme}|{title}|{' '.join((body or '').split())[:800]}|{format_name}|{attempt}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    indexes = [int(digest[i:i+4], 16) for i in range(0, 24, 4)]
    category = _channel_visual_category(theme, title, body, format_name)
    shot = VISUAL_SHOT_OPTIONS[indexes[0] % len(VISUAL_SHOT_OPTIONS)]
    room = VISUAL_ROOM_OPTIONS[indexes[1] % len(VISUAL_ROOM_OPTIONS)]
    mood = VISUAL_MOOD_OPTIONS[indexes[2] % len(VISUAL_MOOD_OPTIONS)]
    detail = VISUAL_DETAIL_OPTIONS[indexes[3] % len(VISUAL_DETAIL_OPTIONS)]
    action_pool = VISUAL_ACTION_OPTIONS.get(category, VISUAL_ACTION_OPTIONS["default"])
    action = action_pool[indexes[4] % len(action_pool)]
    if category == "pregnancy":
        cast = [
            "в кадре беременная женщина или беременная пара",
            "в кадре одна беременная женщина без лишних персонажей",
            "в кадре беременная женщина и поддерживающий партнёр",
        ][indexes[5] % 3]
    elif category == "family":
        cast = [
            "в кадре мама, папа и ребёнок",
            "в кадре отец помогает маме и взаимодействует с ребёнком",
            "в кадре семья из трёх человек в естественном домашнем моменте",
        ][indexes[5] % 3]
    else:
        cast = [
            "в кадре мама и ребёнок",
            "в кадре мама с малышом, а при необходимости рядом папа",
            "в кадре один взрослый и ребёнок в живом семейном моменте",
        ][indexes[5] % 3]
    lighting = "мягкий утренний естественный свет" if slot == "morning" else "тёплый вечерний домашний свет"
    return {
        "category": category,
        "shot": shot,
        "room": room,
        "mood": mood,
        "detail": detail,
        "action": action,
        "cast": cast,
        "lighting": lighting,
        "signature": f"{category}|{shot}|{room}|{action}|{cast}",
    }


async def build_channel_visual_brief(slot, theme, title, body, format_name, attempt=1):
    """Отдельно превращает смысл поста в конкретную жизненную сцену и задаёт вариативность кадра."""
    subject = channel_visual_subject(theme, title, body, format_name)
    variation = build_channel_visual_variation(slot, theme, title, body, format_name, attempt)
    retry_hint = (
        "Это повторная попытка: сцена должна быть заметно другой по композиции и действию, чем первая, "
        "но всё ещё реалистичной и без графического дизайна."
        if attempt > 1 else ""
    )
    prompt = (
        "Ты арт-директор премиального семейного медиа. По тексту поста составь один конкретный визуальный бриф "
        "для реалистичной lifestyle-фотографии. Опиши только то, что должно быть видно в кадре: кто, где, что делает, "
        "эмоция, свет, ракурс и детали среды. Никаких надписей, плакатов, карточек, рамок, логотипов, инфографики, "
        "символов, абстрактных фонов и декоративного дизайна. Не предлагай текст на изображении. "
        "Кадр должен выглядеть как дорогая редакционная фотография реальной семьи, снятая в естественный момент. "
        "Избегай повторяющейся сцены: опирайся на указанный профиль вариативности.\n\n"
        f"Базовый сюжет: {subject}.\n"
        f"Тема: {theme}.\nЗаголовок: {title}.\nФормат: {format_name}.\n"
        f"Содержание поста: {' '.join((body or '').split())[:1200]}\n"
        f"Профиль вариативности: {variation['cast']}; {variation['action']}; {variation['room']}; "
        f"{variation['shot']}; настроение — {variation['mood']}; свет — {variation['lighting']}; {variation['detail']}.\n"
        f"{retry_hint}\n"
        "Верни только краткий визуальный бриф на русском, 90–160 слов."
    )
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты создаёшь только реалистичные фотосцены без текста и графического дизайна."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=400,
            ),
            timeout=35,
        )
        brief = clean_text(response.choices[0].message.content)
        if brief:
            return brief, variation
    except Exception as exc:
        logging.warning("Канал: не удалось подготовить визуальный бриф: %s", exc)
    fallback = (
        f"{subject}; {variation['cast']}; {variation['action']}; {variation['room']}; "
        f"{variation['shot']}; {variation['lighting']}; настроение: {variation['mood']}."
    )
    return fallback, variation


def build_channel_image_prompt(slot, theme, title, body, format_name, visual_brief, variation, attempt=1):
    retry = (
        "Previous result was rejected because it looked repetitive, poster-like, templated, illustrated, or contained text. "
        "Make this retry clearly different in shot composition and action while keeping the same post meaning. "
        if attempt > 1 else ""
    )
    diversity = (
        f"Required variation profile: {variation['cast']}; {variation['action']}; {variation['room']}; "
        f"{variation['shot']}; mood: {variation['mood']}; lighting: {variation['lighting']}; {variation['detail']}. "
        "Do not default to the same generic mother-and-baby portrait unless it truly fits this profile. "
        "Make the scene feel distinct from other family-channel images by varying framing, room, action, and who is present. "
    )
    return (
        "Create a premium vertical 4:5 editorial lifestyle photograph for a family media channel. "
        "It must look like a genuine photograph captured in a real moment, not a designed social-media card. "
        f"Scene brief: {visual_brief}. "
        f"{diversity}"
        f"{retry}"
        "Use photorealistic people, natural anatomy, believable skin texture, authentic facial expressions, "
        "realistic hands, subtle depth of field, natural household details, soft cinematic but credible lighting, "
        "and a refined contemporary editorial composition. Avoid glossy advertising poses and avoid repeating the same default setup. "
        "ABSOLUTELY NO TEXT, letters, words, numbers, logos, watermarks, captions, signs, posters, typography, "
        "frames, borders, icons, stickers, charts, UI elements, collages, split layouts, abstract backgrounds, "
        "graphic design, illustration, 3D render, greeting card, quote card, book cover, or infographic. "
        "One single full-bleed photographic scene only."
    )


async def validate_channel_image(image_bytes, theme, title, body):
    """Отбраковывает текстовые карточки, иллюстрации и нерелевантные изображения."""
    if not image_bytes:
        return False, "empty"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    criteria = (
        "Проверь изображение для семейного канала. Ответь строго PASS или RETRY, затем короткая причина. "
        "PASS только если это реалистичная цельная lifestyle-фотография с людьми или правдоподобной жизненной сценой, "
        "она соответствует смыслу поста и не содержит текста, букв, цифр, логотипов, водяных знаков, постерной верстки, "
        "рамок, карточек, инфографики, коллажа, иллюстрации или 3D-рендера. "
        f"Тема: {theme}. Заголовок: {title}. Суть: {' '.join((body or '').split())[:500]}"
    )
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": criteria},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": "low"}},
                    ],
                }],
                max_tokens=80,
            ),
            timeout=45,
        )
        verdict = clean_text(response.choices[0].message.content)
        return verdict.upper().startswith("PASS"), verdict[:300]
    except Exception as exc:
        logging.warning("Канал: автопроверка изображения недоступна: %s", exc)
        return False, f"validation_error:{type(exc).__name__}"


async def _generate_channel_image_once(prompt):
    resp = await asyncio.wait_for(
        client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size=CHANNEL_IMAGE_SIZE,
        ),
        timeout=90,
    )
    image_data = resp.data[0]
    b64_json = getattr(image_data, "b64_json", None)
    image_url = getattr(image_data, "url", None)
    if not b64_json and isinstance(image_data, dict):
        b64_json = image_data.get("b64_json")
        image_url = image_data.get("url")
    if b64_json:
        return base64.b64decode(b64_json)
    if image_url:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http_client:
            response = await http_client.get(image_url)
            if response.is_success:
                return response.content
    return None


async def create_channel_visual(dt, rubric, title, post_text=""):
    """AI-генерация изображений отключена. Канал работает в текстовом режиме."""
    return None


def fit_telegram_caption(title, body, bridge_text, limit=1024):
    title = (title or "").strip()
    body = (body or "").strip()
    bridge_text = (bridge_text or "").strip()
    fixed = f"{title}\n\n{{body}}\n\n{bridge_text}".strip()
    available = limit - len(fixed.format(body=""))
    if available <= 0:
        return f"{title}\n\n{bridge_text}"[:limit].rstrip()
    if len(body) > available:
        trimmed = body[:available].rstrip()
        sentence_end = max(trimmed.rfind(". "), trimmed.rfind("! "), trimmed.rfind("? "))
        if sentence_end >= int(available * 0.55):
            trimmed = trimmed[:sentence_end + 1]
        else:
            trimmed = trimmed.rstrip(" ,;:-") + "…"
        body = trimmed
    return f"{title}\n\n{body}\n\n{bridge_text}".strip()[:limit]


async def send_channel_image_tg(slot, caption, image_bytes, reply_markup):
    if not image_bytes:
        return False
    try:
        photo = BufferedInputFile(image_bytes, filename=f"channel_{slot}_{uuid.uuid4().hex[:8]}.png")
        await bot.send_photo(
            CHANNEL_ID,
            photo=photo,
            caption=caption,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logging.error(f"Канал TG: ошибка отправки изображения: {e}")
        return False

# ─── ПЕРСОНАЛЬНАЯ АНАЛИТИКА И ДОСТУП ────────────────────────
PREMIUM_CALLBACKS = {
    "tracker_growth", "growth_add", "growth_analyze",
    "tracker_symptoms", "symptom_add", "symptom_analyze",
    "tracker_feeding", "feed_left", "feed_right", "feed_bottle", "feed_stats",
    "tracker_sleep", "sleep_start", "sleep_end", "sleep_analyze",
    "tracker_vaccines", "vaccines_create", "vaccines_done", "vaccines_info",
    "vac_bcg", "vac_hepb", "vac_akds", "vac_polio", "vac_pneumo", "vac_kpk", "vac_varicella",
    "benefits_menu", "ben_birth", "ben_15", "ben_3", "ben_matcap", "ben_decree", "ben_multi", "ben_personal",
    "photo_menu", "photo_analysis", "photo_uzi", "photo_med_preg", "photo_skin", "photo_stool", "photo_food", "photo_package",
    "psycho_start", "psycho_clear", "doctor_prep", "weekly_report"
}

class PremiumCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, CallbackQuery):
            rule = callback_feature(event.data or "")
            if rule:
                kind, value = rule
                allowed = has_plan_access(event.from_user.id, value) if kind == "plan" else can_use_product(event.from_user.id, value)
                if not allowed:
                    await event.answer("Нужен тариф или разовая покупка", show_alert=True)
                    await event.message.answer(
                        "🔒 Эта функция не входит в ваш текущий доступ.\n\nВыберите подписку или купите один конкретный результат.",
                        reply_markup=kb_premium(),
                    )
                    return
        return await handler(event, data)


def get_recent_family_data(user_id, days=7):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = db_connect()
    symptoms = conn.execute(
        "SELECT symptom, created_at FROM symptoms WHERE user_id=? AND created_at>=? ORDER BY created_at",
        (user_id, since)
    ).fetchall()
    diary = conn.execute(
        "SELECT entry, created_at FROM diary WHERE user_id=? AND created_at>=? ORDER BY created_at",
        (user_id, since)
    ).fetchall()
    feedings = conn.execute(
        "SELECT side, duration, created_at FROM feeding WHERE user_id=? AND created_at>=? ORDER BY created_at",
        (user_id, since)
    ).fetchall()
    sleep = conn.execute(
        "SELECT action, created_at FROM sleep_log WHERE user_id=? AND created_at>=? ORDER BY created_at",
        (user_id, since)
    ).fetchall()
    growth = conn.execute(
        "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 3",
        (user_id,)
    ).fetchall()
    conn.close()
    return {"symptoms": symptoms, "diary": diary, "feedings": feedings, "sleep": sleep, "growth": growth}


def format_recent_data(data, days=7):
    parts = [
        f"Период: последние {days} дней.",
        f"Кормления: {len(data['feedings'])} записей.",
        f"Сон: {len(data['sleep'])} событий.",
        f"Симптомы: {len(data['symptoms'])} записей.",
        f"Дневник: {len(data['diary'])} записей.",
    ]
    if data["symptoms"]:
        parts.append("Симптомы:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {text}"
            for text, dt in data["symptoms"][-10:]
        ))
    if data["growth"]:
        parts.append("Последние замеры:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m.%Y')}: {h} см, {w} кг"
            for h, w, dt in reversed(data["growth"])
        ))
    if data["feedings"]:
        parts.append("Последние кормления:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {side}, {dur} мин"
            for side, dur, dt in data["feedings"][-10:]
        ))
    if data["sleep"]:
        parts.append("Последние события сна:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {action}"
            for action, dt in data["sleep"][-12:]
        ))
    return "\n\n".join(parts)


def kb_emergency():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌡 Температура", callback_data="em_fever"),
         InlineKeyboardButton(text="😮‍💨 Дыхание", callback_data="em_breath")],
        [InlineKeyboardButton(text="🤮 Рвота/понос", callback_data="em_vomit"),
         InlineKeyboardButton(text="😴 Сильная вялость", callback_data="em_lethargic")],
        [InlineKeyboardButton(text="🔴 Внезапная сыпь", callback_data="em_rash"),
         InlineKeyboardButton(text="😭 Безутешный плач", callback_data="em_crying")],
        [InlineKeyboardButton(text="✍️ Другое — описать", callback_data="em_other")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mama")]
    ])

# ─── КЛАВИАТУРЫ ──────────────────────────────────────────────
MINIAPP_URL = "https://maminpomoshnik.ru/app/"


def _with_owner_button(rows, user_id=None):
    if OWNER_ID and int(user_id or 0) == OWNER_ID:
        rows.append([InlineKeyboardButton(text="👑 Кабинет владельца", callback_data="owner_cab:home")])
    return rows


def kb_start(user_id=None):
    return InlineKeyboardMarkup(inline_keyboard=_with_owner_button([
        [InlineKeyboardButton(text="🤰 Я беременна", callback_data="mode_pregnant")],
        [InlineKeyboardButton(text="👩 Я уже мама", callback_data="mode_mama")],
        [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/yamama_ai")],
        [InlineKeyboardButton(text="❤️ Поддержать проект", callback_data="donate_menu"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")]
    ], user_id))

def kb_pregnant_menu(user_id=None):
    return InlineKeyboardMarkup(inline_keyboard=_with_owner_button([
        [InlineKeyboardButton(text="✨ Сегодня", callback_data="today_brief")],
        [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton(text="🤰 Беременность", callback_data="cat_pregnancy"),
         InlineKeyboardButton(text="❤️ Здоровье", callback_data="cat_preg_health")],
        [InlineKeyboardButton(text="🧠 Для мамы", callback_data="cat_mom_preg"),
         InlineKeyboardButton(text="📓 Мои данные", callback_data="profile")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="❤️ Поддержать проект", callback_data="donate_menu"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")],
        [InlineKeyboardButton(text="🎁 Пригласить подругу", callback_data="invite_friend")],
        [InlineKeyboardButton(text="🔄 Изменить данные", callback_data="change_data")]
    ], user_id))


def kb_mama_menu(user_id=None):
    return InlineKeyboardMarkup(inline_keyboard=_with_owner_button([
        [InlineKeyboardButton(text="✨ Сегодня", callback_data="today_brief")],
        [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=MINIAPP_URL))],
        [InlineKeyboardButton(text="👶 Ребёнок", callback_data="cat_child"),
         InlineKeyboardButton(text="❤️ Здоровье", callback_data="cat_health")],
        [InlineKeyboardButton(text="📊 Трекеры", callback_data="cat_trackers"),
         InlineKeyboardButton(text="🧠 Для мамы", callback_data="cat_mom")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Семья", callback_data="cat_family"),
         InlineKeyboardButton(text="📓 Мои данные", callback_data="profile")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="❤️ Поддержать проект", callback_data="donate_menu"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_menu")],
        [InlineKeyboardButton(text="🎁 Пригласить подругу", callback_data="invite_friend")],
        [InlineKeyboardButton(text="🔄 Изменить данные", callback_data="change_data")]
    ], user_id))


def kb_cat_child():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="📊 Развитие по возрасту", callback_data="mama_dev")],
        [InlineKeyboardButton(text="🎮 Игры и занятия", callback_data="mama_games"),
         InlineKeyboardButton(text="📚 Что читать", callback_data="mama_books")],
        [InlineKeyboardButton(text="🍼 Питание и прикорм", callback_data="mama_food"),
         InlineKeyboardButton(text="🥣 Рецепты", callback_data="mama_recipes")],
        [InlineKeyboardButton(text="🌙 Режим дня", callback_data="mama_routine"),
         InlineKeyboardButton(text="😴 Проблемы со сном", callback_data="mama_sleep")],
        [InlineKeyboardButton(text="😢 Истерики и капризы", callback_data="mama_tantrums")],
        [InlineKeyboardButton(text="📋 Первые дни с малышом", callback_data="mama_firstdays")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="🌙 Разбор сна", callback_data="sleep_analyze")],
        [InlineKeyboardButton(text="📈 Отчёт за неделю", callback_data="weekly_report")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_mama")]
    ])


def kb_cat_health():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="🚨 Ребёнку плохо", callback_data="emergency")],
        [InlineKeyboardButton(text="🌡 Здоровье", callback_data="mama_health"),
         InlineKeyboardButton(text="💊 Лекарства", callback_data="mama_meds")],
        [InlineKeyboardButton(text="🦷 Зубки", callback_data="mama_teeth")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="🩺 Сводка врачу", callback_data="doctor_prep")],
        [InlineKeyboardButton(text="📸 Анализ фото", callback_data="photo_menu")],
        [InlineKeyboardButton(text="💉 Прививки", callback_data="check_premium_vaccines")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_mama")]
    ])


def kb_cat_trackers():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="📓 Дневник малыша", callback_data="mama_diary")],
        [InlineKeyboardButton(text="📊 ТРЕКЕРЫ", callback_data="noop")],
        [InlineKeyboardButton(text="📏 Рост и вес", callback_data="check_premium_growth"),
         InlineKeyboardButton(text="🌡 Симптомы", callback_data="check_premium_symptoms")],
        [InlineKeyboardButton(text="🤱 Кормления", callback_data="check_premium_feeding"),
         InlineKeyboardButton(text="🌙 Сон", callback_data="check_premium_sleep")],
        [InlineKeyboardButton(text="✨ ГЛУБОКИЙ АНАЛИЗ", callback_data="noop")],
        [InlineKeyboardButton(text="🤱 Разбор кормлений", callback_data="feed_stats")],
        [InlineKeyboardButton(text="🌙 Разбор сна", callback_data="sleep_analyze")],
        [InlineKeyboardButton(text="📈 Отчёт за 7 дней", callback_data="weekly_report")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_mama")]
    ])


def kb_cat_mom():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="🧠 Эмоции мамы", callback_data="mama_emotions")],
        [InlineKeyboardButton(text="🤱 Грудное вскармливание", callback_data="mama_breastfeeding")],
        [InlineKeyboardButton(text="🏥 Восстановление мамы", callback_data="mama_recovery")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="🧠 Мамин психолог", callback_data="psycho_start")],
        [InlineKeyboardButton(text="💰 Пособия и выплаты", callback_data="check_premium_benefits")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_mama")]
    ])


def kb_cat_family():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="👨‍👩‍👧 Отношения в семье", callback_data="mama_family")],
        [InlineKeyboardButton(text="📓 Дневник малыша", callback_data="mama_diary")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="📈 Недельный отчёт", callback_data="weekly_report")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_mama")]
    ])


def kb_cat_pregnancy():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="📊 Мой срок", callback_data="preg_week")],
        [InlineKeyboardButton(text="👶 Развитие малыша", callback_data="preg_baby")],
        [InlineKeyboardButton(text="✅ Чек-лист", callback_data="preg_checklist")],
        [InlineKeyboardButton(text="🛍 Список покупок", callback_data="preg_shop")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_pregnant")]
    ])


def kb_cat_preg_health():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="📸 Анализы и УЗИ", callback_data="photo_menu")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_pregnant")]
    ])


def kb_cat_mom_preg():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆓 БЕСПЛАТНО", callback_data="noop")],
        [InlineKeyboardButton(text="🧠 Эмоциональная поддержка", callback_data="mama_emotions")],
        [InlineKeyboardButton(text="✨ ДОПОЛНИТЕЛЬНО", callback_data="noop")],
        [InlineKeyboardButton(text="🧠 Мамин психолог", callback_data="psycho_start")],
        [InlineKeyboardButton(text="💰 Пособия и выплаты", callback_data="check_premium_benefits")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_pregnant")]
    ])


def profile_text(user_id):
    user = get_user(user_id)
    if not user:
        return "📓 Профиль пока не заполнен."
    mode, date_value, name = user
    plan, sub_end = get_subscription(user_id)
    labels = {"free": "Бесплатный", "start": "Старт", "pro": "Про", "pro_year": "Про на год", "": "Бесплатный"}
    plan_name = labels.get(plan or "", plan or "Бесплатный")
    end_text = ""
    if sub_end:
        try:
            end_text = f"\nДоступ до: {datetime.fromisoformat(sub_end).strftime('%d.%m.%Y')}"
        except Exception:
            pass
    if mode == "pregnant":
        weeks, days = calc_pregnancy_weeks(date_value)
        stage = f"Беременность: {weeks} недель {days} дней" if weeks is not None else "Беременность"
    else:
        months, _ = calc_child_age(date_value)
        stage = f"Ребёнку: {age_label(months)}" if months is not None else "Профиль малыша"
    return f"📓 Мой профиль\n\nИмя: {name or 'не указано'}\n{stage}\nТариф: {plan_name}{end_text}\nИспользовано AI-вопросов: {get_request_count(user_id)}"

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


OWNER_SECTIONS = {
    "today": "📊 Сегодня",
    "sales": "💰 Продажи",
    "users": "👥 Пользователи",
    "funnel": "📈 Воронка",
    "sources": "🎯 Источники рекламы",
    "ads": "📣 Реклама",
    "errors": "⚠️ Ошибки",
    "feedback": "💬 Обратная связь",
    "broadcast": "📤 Рассылка",
    "export": "📄 Экспорт / Google-таблица",
    "check": "🧪 Проверка бота",
}


def owner_cabinet_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Сегодня", callback_data="owner_cab:today"),
         InlineKeyboardButton(text="💰 Продажи", callback_data="owner_cab:sales")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="owner_cab:users"),
         InlineKeyboardButton(text="📈 Воронка", callback_data="owner_cab:funnel")],
        [InlineKeyboardButton(text="🎯 Источники рекламы", callback_data="owner_cab:sources"),
         InlineKeyboardButton(text="📣 Реклама", callback_data="owner_cab:ads")],
        [InlineKeyboardButton(text="⚠️ Ошибки", callback_data="owner_cab:errors"),
         InlineKeyboardButton(text="💬 Обратная связь", callback_data="owner_cab:feedback")],
        [InlineKeyboardButton(text="📤 Рассылка", callback_data="owner_cab:broadcast")],
        [InlineKeyboardButton(text="📄 Экспорт / Google-таблица", callback_data="owner_cab:export")],
        [InlineKeyboardButton(text="🧪 Проверка бота", callback_data="owner_cab:check")],
        [InlineKeyboardButton(text="🏠 В обычное меню", callback_data="main_menu")],
    ])


def owner_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="owner_cab:home"),
         InlineKeyboardButton(text="🏠 В обычное меню", callback_data="main_menu")]
    ])


def owner_home_text():
    return "👑 Кабинет владельца «Мамин помощник»\n\nВыберите раздел:"


def _owner_conn(path):
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _owner_table_exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _owner_scalar(path, sql, params=(), default=0):
    try:
        with _owner_conn(path) as conn:
            return conn.execute(sql, params).fetchone()[0] or default
    except Exception:
        return default


def _owner_sales(path, since):
    try:
        with _owner_conn(path) as conn:
            if _owner_table_exists(conn, "sales_events"):
                rows = conn.execute("SELECT product_code, amount FROM sales_events WHERE created_at>=?", (since,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT product_code, amount FROM payments WHERE status IN ('processed','succeeded') AND updated_at>=?",
                    (since,),
                ).fetchall()
        count = len(rows)
        amount = sum(float(r["amount"] or 0) for r in rows)
        products = {}
        for r in rows:
            code = r["product_code"] or "unknown"
            products[code] = products.get(code, 0) + 1
        return count, amount, products
    except Exception:
        return 0, 0.0, {}


def _owner_event_count(path, since, names=None, source_prefix=None):
    try:
        with _owner_conn(path) as conn:
            if not _owner_table_exists(conn, "analytics_events"):
                return 0
            sql = "SELECT COUNT(*) FROM analytics_events WHERE created_at>=?"
            params = [since]
            if names:
                sql += " AND event_name IN (%s)" % ",".join("?" for _ in names)
                params.extend(names)
            if source_prefix:
                sql += " AND source LIKE ?"
                params.append(source_prefix + "%")
            return conn.execute(sql, params).fetchone()[0] or 0
    except Exception:
        return 0


def _owner_top_sources(path, since, limit=3):
    try:
        with _owner_conn(path) as conn:
            if not _owner_table_exists(conn, "analytics_events"):
                return []
            return conn.execute(
                "SELECT COALESCE(NULLIF(source,''),'organic') source, COUNT(*) cnt "
                "FROM analytics_events WHERE created_at>=? AND (source LIKE 'channel_%' OR source LIKE 'ref_%') "
                "GROUP BY source ORDER BY cnt DESC LIMIT ?",
                (since, limit),
            ).fetchall()
    except Exception:
        return []


def _owner_user_counts(path, platform):
    if platform == "tg":
        today_sql = "SELECT COUNT(*) FROM users WHERE created_at>=?"
        complete_sql = "SELECT COUNT(*) FROM users WHERE COALESCE(mode,'')<>'' AND COALESCE(date_value,'')<>''"
        pregnant_sql = "SELECT COUNT(*) FROM users WHERE mode='pregnant'"
        mama_sql = "SELECT COUNT(*) FROM users WHERE mode='mama'"
    else:
        today_sql = "SELECT COUNT(*) FROM users WHERE registered_at>=?"
        complete_sql = "SELECT COUNT(*) FROM users WHERE COALESCE(birth_date,'')<>''"
        pregnant_sql = "SELECT COUNT(*) FROM users WHERE birth_date LIKE 'pdr:%'"
        mama_sql = "SELECT COUNT(*) FROM users WHERE COALESCE(birth_date,'')<>'' AND birth_date NOT LIKE 'pdr:%'"
    today = date.today().isoformat()
    week = (datetime.now() - timedelta(days=7)).isoformat()
    month = (datetime.now() - timedelta(days=30)).isoformat()
    return {
        "total": _owner_scalar(path, "SELECT COUNT(*) FROM users"),
        "today": _owner_scalar(path, today_sql, (today,)),
        "week": _owner_scalar(path, today_sql, (week,)),
        "month": _owner_scalar(path, today_sql, (month,)),
        "complete": _owner_scalar(path, complete_sql),
        "pregnant": _owner_scalar(path, pregnant_sql),
        "mama": _owner_scalar(path, mama_sql),
    }


def _owner_product_lines(products):
    names = {**{k: v["name"] for k, v in PLAN_CATALOG.items()}, **{k: v["name"] for k, v in ONE_TIME_PRODUCTS.items()}}
    if not products:
        return "нет"
    return ", ".join(f"{names.get(k, k)}: {v}" for k, v in sorted(products.items(), key=lambda item: (-item[1], item[0]))[:8])


def _owner_report(section):
    now = datetime.now()
    today = date.today().isoformat()
    week = (now - timedelta(days=7)).isoformat()
    month = (now - timedelta(days=30)).isoformat()
    dbs = [("TG", DB_PATH), ("MAX", MAX_DB_PATH)]
    if section == "today":
        tg = _owner_user_counts(DB_PATH, "tg")
        mx = _owner_user_counts(MAX_DB_PATH, "max")
        active = sum(_owner_event_count(path, today) for _, path in dbs)
        ad = sum(_owner_event_count(path, today, source_prefix="channel_") for _, path in dbs)
        sales = [_owner_sales(path, today) for _, path in dbs]
        pay_count = sum(item[0] for item in sales)
        pay_sum = sum(item[1] for item in sales)
        errors = sum(_owner_event_count(path, today, names=("error_logged",)) for _, path in dbs)
        source_rows = []
        for label, path in dbs:
            source_rows.extend((label, r["source"], r["cnt"]) for r in _owner_top_sources(path, today))
        top = "\n".join(f"• {src} ({label}): {cnt}" for label, src, cnt in source_rows[:3]) or "нет данных"
        scenarios = ["doctor", "sleep", "feeding", "psycho", "tantrum", "garden", "school", "gadgets", "grandma"]
        scen_lines = []
        for key in scenarios:
            cnt = sum(_owner_event_count(path, today, names=("free_result_started", "funnel_question_opened"), source_prefix=f"channel_{key}") for _, path in dbs)
            scen_lines.append(f"{key}: {cnt}")
        return (
            "📊 Сегодня\n\n"
            f"Новые TG: {tg['today']}\nНовые MAX: {mx['today']}\nВсего новых: {tg['today'] + mx['today']}\n"
            f"Активных по событиям: {active}\nРекламные payload: {ad}\n"
            f"Оплат: {pay_count}\nСумма: {pay_sum:.0f} ₽\nОшибки: {errors}\n\n"
            f"Топ источников:\n{top}\n\nБесплатные сценарии:\n" + "\n".join(scen_lines)
        )
    if section == "sales":
        lines = ["💰 Продажи"]
        for label, since in (("Сегодня", today), ("7 дней", week), ("30 дней", month)):
            sales = [_owner_sales(path, since) for _, path in dbs]
            count = sum(item[0] for item in sales)
            amount = sum(item[1] for item in sales)
            products = {}
            for _, _, prod in sales:
                for k, v in prod.items():
                    products[k] = products.get(k, 0) + v
            avg = amount / count if count else 0
            lines.append(f"\n{label}: {count} оплат, {amount:.0f} ₽, средний чек {avg:.0f} ₽\nПродукты: {_owner_product_lines(products)}")
        tg30 = _owner_sales(DB_PATH, month)
        mx30 = _owner_sales(MAX_DB_PATH, month)
        lines.append(f"\nПлатформы 30 дней: TG {tg30[0]} / {tg30[1]:.0f} ₽, MAX {mx30[0]} / {mx30[1]:.0f} ₽")
        return "\n".join(lines)
    if section == "users":
        tg = _owner_user_counts(DB_PATH, "tg")
        mx = _owner_user_counts(MAX_DB_PATH, "max")
        active_today = sum(_owner_event_count(path, today) for _, path in dbs)
        active_week = sum(_owner_event_count(path, week) for _, path in dbs)
        paid = sum(_owner_scalar(path, "SELECT COUNT(*) FROM subscriptions WHERE plan IN ('start','pro','pro_year') AND COALESCE(sub_end,'')<>''") for _, path in dbs)
        one_time = sum(_owner_scalar(path, "SELECT COUNT(DISTINCT user_id) FROM purchases") for _, path in dbs)
        return (
            "👥 Пользователи\n\n"
            f"Всего: {tg['total'] + mx['total']} (TG {tg['total']}, MAX {mx['total']})\n"
            f"Новые: сегодня {tg['today'] + mx['today']}, 7 дней {tg['week'] + mx['week']}, 30 дней {tg['month'] + mx['month']}\n"
            f"Активные: сегодня {active_today}, 7 дней {active_week}\n"
            f"Беременные: {tg['pregnant'] + mx['pregnant']}\nМамы: {tg['mama'] + mx['mama']}\n"
            f"Профиль заполнен: {tg['complete'] + mx['complete']}\nБез завершённого профиля: {tg['total'] + mx['total'] - tg['complete'] - mx['complete']}\n"
            f"Платные тарифы: {paid}\nРазовые покупки: {one_time}"
        )
    if section == "funnel":
        steps = [
            ("Перешёл по ссылке", ("channel_click", "ad_payload_opened")),
            ("Start / bot_started", ("user_start",)),
            ("Профиль заполнен", ("profile_completed",)),
            ("Бесплатный сценарий", ("free_result_started", "funnel_question_opened")),
            ("Бесплатный результат", ("free_result_completed",)),
            ("Платный оффер", ("paid_offer_shown",)),
            ("Нажал оплату", ("payment_clicked",)),
            ("Оплатил", ("payment_success", "payment_succeeded")),
        ]
        lines = ["📈 Воронка за 30 дней"]
        for title, names in steps:
            lines.append(f"{title}: {sum(_owner_event_count(path, month, names=names) for _, path in dbs)}")
        return "\n".join(lines)
    if section == "sources":
        lines = ["🎯 Источники рекламы за 30 дней"]
        sources = {}
        for _, path in dbs:
            for row in _owner_top_sources(path, month, 20):
                sources[row["source"]] = sources.get(row["source"], 0) + row["cnt"]
        if not sources:
            lines.append("Данных по источникам пока нет.")
        for src, cnt in sorted(sources.items(), key=lambda item: (-item[1], item[0]))[:15]:
            paid = sum(_owner_event_count(path, month, names=("payment_success", "payment_succeeded"), source_prefix=src) for _, path in dbs)
            conv = (paid / cnt * 100) if cnt else 0
            lines.append(f"• {src}: входов {cnt}, оплат {paid}, конверсия {conv:.1f}%")
        return "\n".join(lines)
    if section == "ads":
        bot_link = "https://t.me/MaminPomoshnikAI_bot?start="
        topics = [("врач", "channel_doctor"), ("сон", "channel_sleep"), ("питание", "channel_feeding"), ("психолог", "channel_psycho"), ("истерики", "channel_tantrum"), ("садик", "channel_garden"), ("школа", "channel_school"), ("гаджеты", "channel_gadgets"), ("бабушки", "channel_grandma")]
        lines = ["📣 Реклама", "Telegram ссылки:"]
        for title, payload in topics:
            lines.append(f"• {title}: {bot_link}{payload}")
            lines.append(f"  ya/vk/land: {payload}_ya1 | {payload}_vk1 | {payload}_land1")
        lines.append("\nMAX: публичная ссылка формируется в MAX-боте, если задан MAX_BOT_PUBLIC_URL.")
        return "\n".join(lines)
    if section == "errors":
        today_count = sum(_owner_event_count(path, today, names=("error_logged",)) for _, path in dbs)
        week_count = sum(_owner_event_count(path, week, names=("error_logged",)) for _, path in dbs)
        return f"⚠️ Ошибки\n\nСегодня: {today_count}\nЗа 7 дней: {week_count}\n\nСистемный journal из бота не читается, чтобы не подвешивать процесс."
    if section == "feedback":
        lines = ["💬 Обратная связь"]
        try:
            with _owner_conn(MAX_DB_PATH) as conn:
                if _owner_table_exists(conn, "reviews"):
                    rows = conn.execute("SELECT created_at, review FROM reviews ORDER BY id DESC LIMIT 10").fetchall()
                    lines.extend(f"• {r['created_at'][:16]}: {str(r['review'])[:160]}" for r in rows)
        except Exception:
            pass
        if len(lines) == 1:
            lines.append("Отдельная таблица отзывов есть в MAX; свежих записей не найдено.")
        return "\n".join(lines)
    if section == "broadcast":
        tg = _owner_user_counts(DB_PATH, "tg")["total"]
        mx = _owner_user_counts(MAX_DB_PATH, "max")["total"]
        return f"📤 Рассылка\n\nРассылка пока в безопасном режиме.\nПотенциальные получатели: TG {tg}, MAX {mx}.\n\nМассовая отправка из этого кабинета не выполняется."
    if section == "export":
        return "📄 Экспорт / Google-таблица\n\nИнтеграция Google Sheets в проекте уже есть для пользователей/продаж/отзывов.\n\nОтдельный экспорт кабинета подключается отдельной задачей.\nЛисты: Mama TG, Mama MAX, Продажи, Реклама, Ошибки, Воронка."
    if section == "check":
        def hb(path):
            try:
                dt = datetime.fromtimestamp(os.path.getmtime(path))
                age = int((datetime.now() - dt).total_seconds())
                return f"{dt.strftime('%d.%m %H:%M:%S')} ({age} сек. назад)"
            except Exception:
                return "нет данных"
        return (
            "🧪 Проверка бота\n\n"
            f"TG version: {APP_VERSION}\nMAX DB доступна: {'да' if os.path.exists(MAX_DB_PATH) else 'нет'}\n"
            f"TG heartbeat: {hb(HEARTBEAT_FILE)}\n"
            f"Production TG: /root/mama_bot.py\nProduction MAX: /root/mama_max_bot.py\n\n"
            "Перезапуск сервисов из кабинета не выполняется."
        )
    return owner_home_text()


@dp.message(Command("owner", "admin"))
async def owner_command_tg(message: Message):
    if not OWNER_ID or message.from_user.id != OWNER_ID:
        await message.answer("Недоступно")
        return
    await message.answer(owner_home_text(), reply_markup=owner_cabinet_keyboard())


@dp.callback_query(F.data.startswith("owner_cab:"))
async def owner_cabinet_tg(call: CallbackQuery):
    if not OWNER_ID or call.from_user.id != OWNER_ID:
        await call.answer("Недоступно", show_alert=True)
        return
    section = (call.data or "owner_cab:home").split(":", 1)[1]
    if section == "home":
        await call.message.edit_text(owner_home_text(), reply_markup=owner_cabinet_keyboard())
    else:
        await call.message.edit_text(_owner_report(section), reply_markup=owner_back_keyboard())
    await call.answer()


# ─── СТАРТ ───────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # Удаляем старую постоянную клавиатуру, которая могла остаться от другого бота.
    cleanup_message = await message.answer(
        "\u2063",
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        await cleanup_message.delete()
    except Exception:
        pass
    parts = (message.text or "").split(maxsplit=1)
    start_payload = parts[1].strip() if len(parts) > 1 else ""
    user = get_user(message.from_user.id)
    name = message.from_user.first_name or "мамочка"
    log_analytics_event("user_start", message.from_user.id, start_payload)
    rewarded_referrer = None
    if user is None and start_payload.startswith("ref_"):
        try:
            rewarded_referrer = register_referral(message.from_user.id, int(start_payload[4:]))
        except (TypeError, ValueError):
            rewarded_referrer = None
        if rewarded_referrer:
            try:
                await bot.send_message(rewarded_referrer, "🎁 По твоей ссылке пришёл новый пользователь. Начислен 1 дополнительный AI-вопрос.")
            except Exception as exc:
                logging.warning(f"Не удалось уведомить пригласившего {rewarded_referrer}: {exc}")
    if start_payload.startswith("channel_"):
        await state.update_data(channel_start_payload=start_payload)
        log_analytics_event("channel_click", message.from_user.id, start_payload)
        log_analytics_event("ad_payload_opened", message.from_user.id, start_payload)

    if user:
        mode, date_value, saved_name = user
        if mode == "pregnant":
            weeks, days = calc_pregnancy_weeks(date_value)
            if weeks and start_payload.startswith("channel_"):
                await open_channel_destination_tg(message, start_payload)
            elif weeks:
                await message.answer(
                    f"👋 С возвращением, {saved_name or name}!\n\n"
                    f"🤰 Ты на {weeks} неделе беременности ({days} дн.)\n\n"
                    f"Чем могу помочь?",
                    
                    reply_markup=kb_pregnant_menu(message.from_user.id)
                )
            else:
                await show_start(message, name, state)
        else:
            months, days = calc_child_age(date_value)
            if months is not None and start_payload.startswith("channel_"):
                await open_channel_destination_tg(message, start_payload)
            elif months is not None:
                await message.answer(
                    f"👋 С возвращением, {saved_name or name}!\n\n"
                    f"👶 Малышу {age_label(months)}\n\n"
                    f"Чем могу помочь?",
                    
                    reply_markup=kb_mama_menu(message.from_user.id)
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
        f"Я Мамин Помощник — бесплатный личный AI-помощник для беременности, ребёнка и поддержки мамы.\n\n"
        f"Подскажу по возрасту, помогу вести трекеры, подготовиться к врачу "
        f"и разобраться в сложной ситуации.\n\n"
        f"Расскажи, кто ты 👇",
        
        reply_markup=kb_start(message.from_user.id)
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
    pending_data = await state.get_data()
    pending_payload = pending_data.get("channel_start_payload", "")
    save_user(message.from_user.id, "pregnant", text, name)
    log_analytics_event("profile_completed", message.from_user.id, pending_payload)
    await state.clear()
    if pending_payload:
        await message.answer(
            f"✅ Сохранила!\n\n"
            f"🤰 Ты на {weeks} неделе беременности ({days} дн.)"
        )
        await open_channel_destination_tg(message, pending_payload)
    else:
        await message.answer(
            f"✅ Сохранила!\n\n"
            f"🤰 Ты на {weeks} неделе беременности ({days} дн.)\n\n"
            f"Я буду давать советы и отвечать на вопросы именно для этого срока 💕",
            
            reply_markup=kb_pregnant_menu(message.from_user.id)
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
    pending_data = await state.get_data()
    pending_payload = pending_data.get("channel_start_payload", "")
    save_user(message.from_user.id, "mama", text, name)
    log_analytics_event("profile_completed", message.from_user.id, pending_payload)
    await state.clear()
    if pending_payload:
        await message.answer(
            f"✅ Сохранила!\n\n"
            f"👶 Малышу {age_label(months)}"
        )
        await open_channel_destination_tg(message, pending_payload)
    else:
        await message.answer(
            f"✅ Сохранила!\n\n"
            f"👶 Малышу {age_label(months)}\n\n"
            f"Буду давать советы именно для этого возраста 💕",
            
            reply_markup=kb_mama_menu(message.from_user.id)
        )

# ─── ГЛАВНОЕ МЕНЮ ────────────────────────────────────────────
@dp.callback_query(F.data == "main_menu")
async def main_menu(call: CallbackQuery, state: FSMContext):
    """Отправляет новое меню, не удаляя полезный ответ пользователя."""
    await call.answer()
    await state.clear()
    user = get_user(call.from_user.id)
    if user:
        mode, date_value, name = user
        if mode == "pregnant":
            weeks, days = calc_pregnancy_weeks(date_value)
            await call.message.answer(
                f"🤰 Ты на {weeks} неделе беременности\n\nЧем могу помочь?",
                reply_markup=kb_pregnant_menu(call.from_user.id)
            )
        else:
            months, _ = calc_child_age(date_value)
            await call.message.answer(
                f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?",
                reply_markup=kb_mama_menu(call.from_user.id)
            )
    else:
        await call.message.answer(
            "👋 Привет! Расскажи мне о себе 👇",
            reply_markup=kb_start(call.from_user.id)
        )

@dp.callback_query(F.data == "menu_pregnant")
async def menu_pregnant(call: CallbackQuery):
    """Возвращает в меню беременной отдельным сообщением, сохраняя результат выше."""
    await call.answer()
    user = get_user(call.from_user.id)
    if user:
        _, date_value, _ = user
        weeks, days = calc_pregnancy_weeks(date_value)
        await call.message.answer(
            f"🤰 Ты на {weeks} неделе беременности\n\nЧем могу помочь?",
            reply_markup=kb_pregnant_menu(call.from_user.id)
        )

@dp.callback_query(F.data == "menu_mama")
async def menu_mama(call: CallbackQuery):
    """Возвращает в меню мамы отдельным сообщением, сохраняя результат выше."""
    await call.answer()
    user = get_user(call.from_user.id)
    if user:
        _, date_value, _ = user
        months, _ = calc_child_age(date_value)
        await call.message.answer(
            f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?",
            reply_markup=kb_mama_menu(call.from_user.id)
        )

@dp.callback_query(F.data == "change_data")
async def change_data(call: CallbackQuery, state: FSMContext):
    await state.set_state(RegStates.choosing_mode)
    await call.message.edit_text(
        "Выбери свой статус 👇",
        reply_markup=kb_start(call.from_user.id)
    )

@dp.callback_query(F.data == "noop")
async def noop_callback(call: CallbackQuery):
    await call.answer("Это заголовок раздела")

@dp.callback_query(F.data == "cat_child")
async def cat_child(call: CallbackQuery):
    await call.message.edit_text("👶 Ребёнок\n\nРазвитие, питание, сон и занятия по возрасту.", reply_markup=kb_cat_child())

@dp.callback_query(F.data == "cat_health")
async def cat_health(call: CallbackQuery):
    await call.message.edit_text("❤️ Здоровье\n\nБезопасная навигация, подготовка к врачу и медицинские наблюдения.", reply_markup=kb_cat_health())

@dp.callback_query(F.data == "cat_trackers")
async def cat_trackers(call: CallbackQuery):
    await call.message.edit_text("📊 Трекеры\n\nСохраняйте данные — со временем они превращаются в полезную динамику.", reply_markup=kb_cat_trackers())

@dp.callback_query(F.data == "cat_mom")
async def cat_mom(call: CallbackQuery):
    await call.message.edit_text("🧠 Для мамы\n\nПоддержка, восстановление и забота о вашем состоянии.", reply_markup=kb_cat_mom())

@dp.callback_query(F.data == "cat_family")
async def cat_family(call: CallbackQuery):
    await call.message.edit_text("👨‍👩‍👧 Семья\n\nОтношения, общая история и недельные итоги.", reply_markup=kb_cat_family())

@dp.callback_query(F.data == "cat_pregnancy")
async def cat_pregnancy(call: CallbackQuery):
    await call.message.edit_text("🤰 Беременность\n\nСрок, развитие малыша и подготовка к родам.", reply_markup=kb_cat_pregnancy())

@dp.callback_query(F.data == "cat_preg_health")
async def cat_preg_health(call: CallbackQuery):
    await call.message.edit_text("❤️ Здоровье при беременности\n\nАнализы, УЗИ и персональные вопросы.", reply_markup=kb_cat_preg_health())

@dp.callback_query(F.data == "cat_mom_preg")
async def cat_mom_preg(call: CallbackQuery):
    await call.message.edit_text("🧠 Для мамы\n\nЭмоциональная и практическая поддержка во время беременности.", reply_markup=kb_cat_mom_preg())

@dp.callback_query(F.data == "invite_friend")
async def invite_friend(call: CallbackQuery):
    user_id = call.from_user.id
    invited, start_rewards, payment_rewards = referral_stats(user_id)
    available_bonus = get_referral_bonus_questions(user_id)
    link = referral_link_tg(user_id)
    share_url = "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote(
        "Я пользуюсь «Маминым Помощником» — здесь можно получить поддержку по беременности, ребёнку, сну, питанию и развитию 🤍",
        safe="",
    )
    text = (
        "🎁 Пригласить подругу\n\n"
        "Поделись личной ссылкой:\n"
        f"{link}\n\n"
        "Все функции «Маминого помощника» и так доступны бесплатно — приглашение просто помогает больше мам узнать о проекте.\n\n"
        f"Приглашено: {invited}\n"
        f"Бонусов начислено: {start_rewards}"
    )
    await call.answer()
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=share_url)],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")],
    ]))


@dp.callback_query(F.data == "profile")
async def profile_view(call: CallbackQuery):
    user = get_user(call.from_user.id)
    mode = user[0] if user else "mama"
    await call.message.edit_text(profile_text(call.from_user.id), reply_markup=kb_back_to_menu(mode))

# ─── ПЕРСОНАЛЬНЫЕ И КОММЕРЧЕСКИЕ ФУНКЦИИ ─────────────────
@dp.callback_query(F.data == "today_brief")
async def today_brief(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Сначала укажи данные", show_alert=True)
        return
    mode, date_value, _ = user
    await show_typing(call.message.chat.id)
    if mode == "pregnant":
        weeks, days = calc_pregnancy_weeks(date_value)
        prompt = (
            f"Беременная на {weeks} неделе и {days} дне. Составь короткий персональный план на сегодня: "
            "что происходит с малышом, один пункт заботы о маме, одно полезное действие и один красный флаг. "
            "Не ставь диагноз и не запугивай. Максимум 350 слов."
        )
        title = "✨ Сегодня для тебя"
        markup = kb_back_to_menu("pregnant")
    else:
        months, _ = calc_child_age(date_value)
        data = get_recent_family_data(call.from_user.id, 2)
        prompt = (
            f"Ребёнку {age_label(months)}. За 2 дня: кормлений {len(data['feedings'])}, "
            f"событий сна {len(data['sleep'])}, симптомов {len(data['symptoms'])}. "
            "Составь короткий план на сегодня: возрастной фокус, одна игра, совет по режиму и забота о маме. "
            "При недостатке данных не делай медицинских выводов. Максимум 350 слов."
        )
        title = "✨ Сегодня для вас"
        markup = kb_back_to_menu("mama")
    answer = await ask_gpt(EXPERT_BASE if mode == "mama" else EXPERT_PREG, prompt)
    await send_long_message(call.message.chat.id, f"{title}\n\n{answer}", reply_markup=markup)


@dp.callback_query(F.data == "emergency")
async def emergency_menu(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user or user[0] != "mama":
        await call.message.answer("Тревожная кнопка предназначена для ребёнка после рождения. При угрозе жизни звони 112.")
        return
    await call.message.answer(
        "🚨 Ребёнку плохо\n\nВыбери главное проявление. Раздел помогает оценить срочность, но не заменяет врача. "
        "Если ребёнок не дышит, синеет, не реагирует или у него судороги — звони 112 сразу.",
        reply_markup=kb_emergency()
    )

EMERGENCY_GUIDES = {
    "em_fever": ("🌡 Температура", "Звони 112 при судорогах, нарушении дыхания, синюшности, потере сознания или не бледнеющей сыпи. Для ребёнка младше 3 месяцев температура 38°C и выше требует срочной медицинской оценки. Не укутывай и не растирай спиртом или уксусом. Предлагай питьё или грудь чаще. Лекарство давай только подходящее по возрасту и весу по рекомендации врача."),
    "em_breath": ("😮‍💨 Проблемы с дыханием", "Звони 112 немедленно, если синеют губы, есть паузы дыхания, выраженное втяжение межрёберий, спутанность или потеря сознания. Держи ребёнка вертикально, освободи тесную одежду, не давай еду и не пытайся осматривать горло предметами."),
    "em_vomit": ("🤮 Рвота или понос", "Звони 112 при крови, зелёной рвоте, судорогах, резкой боли или нарушении сознания. Срочно к врачу при отсутствии мочи, сухих губах, отсутствии слёз и запавших глазах. Отпаивай часто маленькими порциями; не давай противорвотные и противодиарейные средства без врача."),
    "em_lethargic": ("😴 Сильная вялость", "Если ребёнка трудно разбудить, он не удерживает взгляд, необычно обмяк или вялость сопровождается нарушением дыхания — звони 112. Проверь дыхание, цвет кожи и температуру. Не заставляй есть и не оставляй одного."),
    "em_rash": ("🔴 Внезапная сыпь", "Надави прозрачным стаканом на сыпь. Если пятна не бледнеют, особенно вместе с температурой или вялостью, — звони 112. Также срочно вызывай помощь при отёке губ или языка, осиплости и затруднении дыхания."),
    "em_crying": ("😭 Безутешный плач", "Звони 112 при нарушении дыхания, посинении, судорогах, травме, резкой вялости или необычном пронзительном крике с рвотой. Проверь температуру, подгузник, голод, одежду и пальцы на пережимающий волос. Никогда не встряхивай ребёнка."),
}

@dp.callback_query(F.data.in_(set(EMERGENCY_GUIDES)))
async def emergency_guide(call: CallbackQuery):
    title, guide = EMERGENCY_GUIDES[call.data]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К симптомам", callback_data="emergency")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu_mama")]
    ])
    await call.message.answer(f"🚨 {title}\n\n{guide}\n\nЕсли сомневаешься — лучше позвонить 112 или в неотложную помощь.", reply_markup=kb)

@dp.callback_query(F.data == "em_other")
async def emergency_other_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(EmergencyStates.waiting_description)
    await call.message.answer(
        "✍️ Опиши ситуацию одним сообщением:\n\n• возраст;\n• что произошло;\n• температура;\n• как дышит и реагирует;\n• когда началось.\n\n"
        "При потере сознания, судорогах или нарушении дыхания не жди ответа — звони 112."
    )

@dp.message(EmergencyStates.waiting_description, F.text)
async def emergency_other_answer(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    months = calc_child_age(user[1])[0] if user and user[0] == "mama" else None
    answer = await ask_gpt(
        "Ты медицинский навигатор. Сначала укажи, есть ли повод звонить 112. Затем безопасные действия до врача и уточняющие вопросы. Не ставь диагноз, не назначай препараты и дозировки.",
        f"Ребёнку {age_label(months) if months is not None else 'неизвестного возраста'}. Ситуация: {message.text}"
    )
    await message.answer("🚨 Оценка срочности\n\n" + answer, reply_markup=kb_emergency())

@dp.callback_query(F.data == "doctor_prep")
async def doctor_prep(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user or user[0] != "mama":
        await call.message.answer("Сводка для педиатра доступна после рождения малыша.")
        return
    months, _ = calc_child_age(user[1])
    data = get_recent_family_data(call.from_user.id, 14)
    raw = format_recent_data(data, 14)
    await show_typing(call.message.chat.id)
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)}. Составь сводку для педиатра: причина обращения, хронология, что отслеживали, 5 вопросов врачу и какие данные взять. Не ставь диагноз и не придумывай факты.\n\n{raw}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Отчёт за 7 дней", callback_data="weekly_report")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, "🩺 Сводка к педиатру\n\n" + answer, reply_markup=kb)

@dp.callback_query(F.data == "weekly_report")
async def weekly_report(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user or user[0] != "mama":
        await call.message.answer("Недельный отчёт доступен для профиля малыша.")
        return
    months, _ = calc_child_age(user[1])
    data = get_recent_family_data(call.from_user.id, 7)
    if not any((data["symptoms"], data["diary"], data["feedings"], data["sleep"], data["growth"])):
        await call.message.answer("Пока недостаточно записей. Несколько дней отмечай сон, кормления, симптомы или события — и бот соберёт динамику.", reply_markup=kb_mama_menu())
        return
    await show_typing(call.message.chat.id)
    raw = format_recent_data(data, 7)
    answer = await ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)}. Подготовь недельный отчёт: краткие цифры, что стабильно, что изменилось, что отслеживать и 3 действия на следующую неделю. Не ставь диагноз.\n\n{raw}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🩺 Подготовить к врачу", callback_data="doctor_prep")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu_mama")]
    ])
    await send_long_message(call.message.chat.id, "📈 Ваши 7 дней\n\n" + answer, reply_markup=kb)

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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
@dp.callback_query(F.data.in_(set(FUNNEL_QUESTION_PROMPTS)))
async def funnel_question_entry(call: CallbackQuery, state: FSMContext):
    await state.set_state(QuestionStates.waiting_question)
    await state.update_data(funnel_source=call.data)
    log_analytics_event("funnel_question_opened", call.from_user.id, call.data)
    await call.message.edit_text(FUNNEL_QUESTION_PROMPTS[call.data])

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
    limit = question_limit_for(message.from_user.id)

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

    log_analytics_event("request_started", message.from_user.id, "personal_question", message.text[:300])
    await show_typing(message.chat.id)
    answer = await ask_gpt(
        f"Ты эксперт в педиатрии, перинатальной психологии и детском развитии. "
        f"{context} "
        f"Опирайся на рекомендации ВОЗ, AAP, ACOG и труды ведущих специалистов. "
        f"Отвечай развёрнуто, точно и с теплом. При медицинских симптомах — направляй к педиатру.",
        message.text
    )
    await message.answer(answer)
    if ai_answer_success(answer):
        if limit is not None:
            increment_request_count(message.from_user.id)
        log_analytics_event("request_completed", message.from_user.id, "personal_question", f"used={get_request_count(message.from_user.id)}")
        funnel_text, funnel_markup = build_question_funnel_tg(message.from_user.id, message.text)
        await message.answer(funnel_text, reply_markup=funnel_markup)
    else:
        log_analytics_event("request_failed", message.from_user.id, "personal_question", "ai_answer_invalid")
        kb = kb_mama_menu() if user and user[0] == "mama" else kb_pregnant_menu() if user else kb_start()
        await message.answer("Лимит не списан. Попробуй ещё раз немного позже.", reply_markup=kb)

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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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
    await show_typing(call.message.chat.id)
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

def kb_photo_pregnant_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Результаты анализов", callback_data="photo_analysis")],
        [InlineKeyboardButton(text="🩺 Заключение УЗИ", callback_data="photo_uzi")],
        [InlineKeyboardButton(text="💊 Лекарство при беременности", callback_data="photo_med_preg")],
        [InlineKeyboardButton(text="🔴 Сыпь и кожа", callback_data="photo_skin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])

@dp.callback_query(F.data == "photo_menu")
async def photo_menu(call: CallbackQuery):
    if not can_use_product(call.from_user.id, "photo_analysis"):
        await call.message.answer("🔒 Анализ фото доступен в Про или разово за 99 ₽", reply_markup=kb_premium())
        return
    user = get_user(call.from_user.id)
    if user and user[0] == "pregnant":
        await call.message.answer(
            "📸 Анализ фото для беременных\n\n"
            "Выбери тип фото 👇",
            reply_markup=kb_photo_pregnant_menu()
        )
    else:
        await call.message.answer(
            "📸 Анализ фото\n\n"
            "Отправь фото и я помогу разобраться.\n"
            "Выбери что хочешь проанализировать 👇",
            reply_markup=kb_photo_menu()
        )

@dp.callback_query(F.data == "photo_analysis")
async def photo_analysis(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="analysis")
    await call.message.answer(
        "📸 Отправь фото результатов анализов\n\n"
        "Я расшифрую показатели понятным языком.\n"
        "⚠️ Интерпретацию подтверждает только врач."
    )

@dp.callback_query(F.data == "photo_uzi")
async def photo_uzi(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="uzi")
    await call.message.answer(
        "📸 Отправь фото заключения УЗИ\n\n"
        "Я объясню показатели понятным языком.\n"
        "⚠️ Интерпретацию подтверждает только врач."
    )

@dp.callback_query(F.data == "photo_med_preg")
async def photo_med_preg(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoStates.waiting_photo)
    await state.update_data(photo_type="med_preg")
    await call.message.answer(
        "📸 Отправь фото упаковки лекарства\n\n"
        "Я скажу можно ли его принимать при беременности.\n"
        "⚠️ Решение принимает только врач."
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
    use_photo_credit = False  # Проект бесплатный: старые кредиты за анализ фото больше не расходуются
    await state.clear()

    # Получаем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    import aiohttp
    await show_typing(message.chat.id)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                photo_bytes = await resp.read()

        import base64
        photo_b64 = base64.b64encode(photo_bytes).decode()

        # Сначала фильтр — проверяем что на фото нужное
        if photo_type == "analysis":
            filter_prompt = "На этом изображении медицинский документ, бланк анализов или результаты лабораторного исследования? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты опытный акушер-гинеколог и лабораторный диагност. Расшифруй результаты анализов для беременной женщины: "
                "1) Какие показатели в норме; "
                "2) Какие отклонения от нормы для беременных; "
                "3) На что обратить внимание; "
                "4) С какими результатами нужно срочно к врачу. "
                "Напомни что интерпретацию результатов должен делать врач."
            )
            wrong_msg = "📸 Я жду фото результатов анализов 🤍"

        elif photo_type == "uzi":
            filter_prompt = "На этом изображении медицинский документ или заключение УЗИ? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты опытный акушер-гинеколог. Объясни заключение УЗИ беременной понятным языком: "
                "1) Что означают основные показатели (размеры плода, ИАЖ, плацента, кровоток); "
                "2) Что в норме для данного срока; "
                "3) Если есть отклонения — что они означают простыми словами; "
                "4) Нужно ли беспокоиться и когда срочно к врачу. "
                "Используй простые слова, избегай медицинского жаргона."
            )
            wrong_msg = "📸 Я жду фото заключения УЗИ 🤍"

        elif photo_type == "med_preg":
            filter_prompt = "На этом изображении упаковка лекарства или медицинского препарата? Ответь только: ДА или НЕТ."
            analysis_prompt = (
                "Ты акушер-гинеколог и клинический фармаколог. Оцени лекарство для беременной: "
                "1) Что это за препарат и для чего; "
                "2) Можно ли при беременности — по категориям FDA/ACOG; "
                "3) В каком триместре разрешён/запрещён; "
                "4) Возможные риски для плода; "
                "5) Обязательно: решение о приёме принимает только врач. "
                "Будь конкретной и честной."
            )
            wrong_msg = "📸 Я жду фото упаковки лекарства 🤍"

        elif photo_type == "skin":
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
            user = get_user(message.from_user.id)
            kb = kb_photo_pregnant_menu() if user and user[0] == "pregnant" else kb_photo_menu()
            await message.answer(wrong_msg, reply_markup=kb)
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
        user = get_user(message.from_user.id)
        kb = kb_photo_pregnant_menu() if user and user[0] == "pregnant" else kb_photo_menu()
        await message.answer(answer, reply_markup=kb)
        if use_photo_credit:
            consume_credit(message.from_user.id, "photo_analysis")

    except Exception as e:
        logging.error(f"Ошибка анализа фото: {e}")
        user = get_user(message.from_user.id)
        kb = kb_photo_pregnant_menu() if user and user[0] == "pregnant" else kb_photo_menu()
        await message.answer("Не удалось проанализировать фото. Попробуй ещё раз.", reply_markup=kb)

@dp.message(PhotoStates.waiting_photo, ~F.voice)
async def photo_wrong_input(message: Message, state: FSMContext):
    await message.answer("📸 Жду именно фото — отправь изображение 🤍")

# ─── ГОЛОСОВЫЕ СООБЩЕНИЯ ─────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    # Сбрасываем любое текущее состояние — голос имеет приоритет
    await state.clear()
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
@dp.callback_query(F.data == "check_premium_vaccines")
async def check_prem_vaccines(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await tracker_vaccines(call)
    else:
        await call.message.answer("🔒 Прививочный календарь доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_growth")
async def check_prem_growth(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await tracker_growth(call)
    else:
        await call.message.answer("🔒 Трекер роста и веса доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_symptoms")
async def check_prem_symptoms(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await tracker_symptoms(call)
    else:
        await call.message.answer("🔒 Трекер симптомов доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_feeding")
async def check_prem_feeding(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await tracker_feeding(call)
    else:
        await call.message.answer("🔒 Трекер кормлений доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_sleep")
async def check_prem_sleep(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await tracker_sleep(call)
    else:
        await call.message.answer("🔒 Дневник сна доступен в Премиум 💎", reply_markup=kb_premium())

@dp.callback_query(F.data == "check_premium_benefits")
async def check_prem_benefits(call: CallbackQuery):
    if has_plan_access(call.from_user.id, "start"):
        await benefits_menu(call)
    else:
        await call.message.answer("🔒 Пособия и выплаты доступны в Премиум 💎", reply_markup=kb_premium())

# ─── GOOGLE SHEETS ───────────────────────────────────────────
TG_USER_SHEET = "МамаБот Telegram"
SALES_SHEET = "Продажи МамаБот"
TG_USER_HEADERS = [
    "Последнее посещение", "user_id", "Имя", "Username",
    "AI-запросы", "Тариф", "Дата окончания", "Отзыв"
]
SALES_HEADERS = [
    "Дата", "Платформа", "user_id", "Имя", "Username", "Продукт",
    "Тип", "Сумма", "Payment ID", "Дата окончания", "Статус"
]

# Таблица PostGenius Users общая для нескольких независимых проектов (Aura,
# МамаБот, MarketPro, AI Местный и др.) через один service account. Гвард не
# даёт коду МамаБот удалить/переименовать/массово очистить свой или чужой
# лист — инициализация может только создать отсутствующий собственный лист.
_BLOCKED_SPREADSHEET_METHODS = ("del_worksheet", "delete_worksheet", "duplicate_sheet", "batch_update")
_BLOCKED_WORKSHEET_METHODS = ("clear", "batch_clear", "update_title", "delete_rows", "delete_columns", "delete_dimension")


class _NoDeleteWorksheetGuard:
    """Прокси над gspread.Worksheet, блокирующий удаление/переименование/очистку."""

    def __init__(self, worksheet, spreadsheet_title):
        object.__setattr__(self, "_wrapped", worksheet)
        object.__setattr__(self, "_spreadsheet_title", spreadsheet_title)

    def __getattr__(self, name):
        if name in _BLOCKED_WORKSHEET_METHODS:
            def _blocked(*args, **kwargs):
                logging.error(
                    "destructive_action_blocked: попытка вызвать %s() на листе %s (таблица %s) "
                    "заблокирована — деструктивные операции над листами общей таблицы требуют "
                    "отдельного owner-решения",
                    name, self._wrapped.title, self._spreadsheet_title,
                )
                raise PermissionError(
                    f"{name} is blocked: destructive worksheet operations require explicit owner sign-off"
                )
            return _blocked
        target = getattr(self._wrapped, name)
        return target


class _NoDeleteSpreadsheetGuard:
    """Прокси над gspread.Spreadsheet, блокирующий деструктивные операции и
    оборачивающий возвращаемые листы в _NoDeleteWorksheetGuard."""

    def __init__(self, spreadsheet):
        object.__setattr__(self, "_wrapped", spreadsheet)

    def __getattr__(self, name):
        title = getattr(self._wrapped, "title", SPREADSHEET_ID)
        if name in _BLOCKED_SPREADSHEET_METHODS:
            def _blocked(*args, **kwargs):
                logging.error(
                    "destructive_action_blocked: попытка вызвать %s() на таблице %s "
                    "заблокирована — удаление/переименование листов требует отдельного "
                    "owner-решения",
                    name, title,
                )
                raise PermissionError(
                    f"{name} is blocked: destructive worksheet operations require explicit owner sign-off"
                )
            return _blocked
        target = getattr(self._wrapped, name)
        if name in ("worksheet", "add_worksheet", "get_worksheet"):
            def _wrapped_call(*args, **kwargs):
                return _NoDeleteWorksheetGuard(target(*args, **kwargs), title)
            return _wrapped_call
        if name == "sheet1":
            return _NoDeleteWorksheetGuard(target, title)
        return target


def _sheets_book():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return _NoDeleteSpreadsheetGuard(gspread.authorize(creds).open_by_key(SPREADSHEET_ID))

def _worksheet(book, title, headers):
    try:
        ws = book.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=title, rows=2000, cols=max(12, len(headers)))
        ws.append_row(headers)
    current = ws.row_values(1)
    if current != headers:
        ws.update('A1', [headers])
    return ws

def sheets_upsert_user(user_id, username="", first_name="", mode="", source="", last_action="", review=None):
    """Компактная карточка: одна строка на пользователя."""
    try:
        book = _sheets_book()
        ws = _worksheet(book, TG_USER_SHEET, TG_USER_HEADERS)
        uid = str(user_id)
        ids = ws.col_values(2)
        row_num = next((i + 1 for i, value in enumerate(ids) if value == uid), None)
        user = get_user(user_id)
        plan, sub_end = get_subscription(user_id)
        plan_name = PLAN_CATALOG.get(plan, {}).get("name", "Бесплатный") if plan else "Бесплатный"
        end_text = ""
        if sub_end:
            try:
                end_text = datetime.fromisoformat(str(sub_end)).strftime("%d.%m.%Y")
            except Exception:
                end_text = str(sub_end)
        values = [
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            uid,
            first_name or (user[2] if user else ""),
            username or "",
            get_request_count(user_id),
            plan_name,
            end_text,
            review if review is not None else "",
        ]
        if row_num:
            old = ws.row_values(row_num)
            while len(old) < len(TG_USER_HEADERS):
                old.append("")
            if not first_name:
                values[2] = old[2]
            if not username:
                values[3] = old[3]
            if review is None:
                values[7] = old[7]
            ws.update(f"A{row_num}:H{row_num}", [values])
        else:
            ws.append_row(values)
    except Exception as e:
        logging.error(f"Sheets upsert user TG: {e}")

def sheets_add_user(user_id, username, first_name, mode=""):
    sheets_upsert_user(user_id, username, first_name, mode=mode, last_action="Регистрация/вход")

def sheets_add_review(user_id, username, text, sheet_name="Отзывы МамаБот"):
    try:
        user = get_user(user_id)
        sheets_upsert_user(user_id, username or "", user[2] if user else "", review=text, last_action="Отзыв")
    except Exception as e:
        logging.error(f"Sheets review TG: {e}")

def sheets_update_subscription(user_id, plan):
    user = get_user(user_id)
    sheets_upsert_user(user_id, "", user[2] if user else "", last_action=f"Оплата {plan}")

def sheets_log_sale(user_id, product_code, amount, payment_id, ends_at="", status="Успешно"):
    try:
        book = _sheets_book()
        ws = _worksheet(book, SALES_SHEET, SALES_HEADERS)
        user = get_user(user_id)
        name = user[2] if user else ""
        info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS.get(product_code, {})
        product_type = "Подписка" if product_code in PLAN_CATALOG else "Разовая покупка"
        end_text = ""
        if ends_at:
            try: end_text = datetime.fromisoformat(str(ends_at)).strftime("%d.%m.%Y")
            except Exception: end_text = str(ends_at)
        ws.append_row([
            datetime.now().strftime("%d.%m.%Y %H:%M"), "Telegram", str(user_id), name, "",
            info.get("name", product_code), product_type, str(amount), payment_id, end_text, status
        ])
    except Exception as e:
        logging.error(f"Sheets sale TG: {e}")

# ─── ЮКАССА ПЛАТЕЖИ ──────────────────────────────────────────
def kb_premium():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Старт — 190 ₽ / 30 дней", callback_data="pay_plan_start")],
        [InlineKeyboardButton(text="💎 Про — 390 ₽ / 30 дней", callback_data="pay_plan_pro")],
        [InlineKeyboardButton(text="⭐ Про на год — 2 990 ₽", callback_data="pay_plan_pro_year")],
        [InlineKeyboardButton(text="🩺 Сводка врачу — 149 ₽", callback_data="buy_doctor_report")],
        [InlineKeyboardButton(text="🌙 Разбор сна — 199 ₽", callback_data="buy_sleep_report")],
        [InlineKeyboardButton(text="🤱 Разбор кормлений — 149 ₽", callback_data="buy_feeding_report")],
        [InlineKeyboardButton(text="📈 Недельный отчёт — 199 ₽", callback_data="buy_weekly_report")],
        [InlineKeyboardButton(text="📸 Анализ фото — 99 ₽", callback_data="buy_photo_analysis")],
        [InlineKeyboardButton(text="🏠 Главная", callback_data="main_menu")],
    ])


async def create_payment_mama(user_id, product_code):
    if product_code in PLAN_CATALOG:
        info = PLAN_CATALOG[product_code]; product_type = "subscription"; days = info["days"]
    else:
        info = ONE_TIME_PRODUCTS[product_code]; product_type = "one_time"; days = 0
    return Payment.create({
        "amount": {"value": info["amount"], "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://t.me/MaminPomoshnikAI_bot"},
        "capture": True,
        "description": f"Мамин помощник — {info['name']} — {user_id}",
        "receipt": {"customer": {"email": "client@maminpomoshnik.ru"}, "items": [{
            "description": f"Мамин помощник — {info['name']}", "quantity": "1.00",
            "amount": {"value": info["amount"], "currency": "RUB"}, "vat_code": 1,
            "payment_subject": "service", "payment_mode": "full_payment"
        }]},
        "metadata": {"user_id": user_id, "product_code": product_code, "product_type": product_type, "days": days}
    }, str(uuid.uuid4()))


def save_commercial_payment(payment_id, user_id, product_code):
    info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
    product_type = "subscription" if product_code in PLAN_CATALOG else "one_time"
    now = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)", (payment_id,user_id,product_code,now))
        conn.execute("INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (payment_id,user_id,"telegram",product_type,product_code,info["amount"],"RUB","pending",now,now))


def process_commercial_payment(payment_id, user_id, product_code):
    now = datetime.now(); now_iso = now.isoformat(); conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM processed_payments WHERE payment_id=?", (payment_id,)).fetchone():
            conn.rollback(); return False, None, None
        if product_code in PLAN_CATALOG:
            info = PLAN_CATALOG[product_code]
            row = conn.execute("SELECT sub_end FROM subscriptions WHERE user_id=?", (user_id,)).fetchone(); start = now
            if row and row[0]:
                try:
                    old = datetime.fromisoformat(row[0]); start = old if old > now else now
                except ValueError: pass
            end = start + timedelta(days=info["days"])
            conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)", (user_id,product_code,end.isoformat()))
            conn.execute("INSERT INTO subscription_history(payment_id,user_id,plan,started_at,ends_at,created_at) VALUES (?,?,?,?,?,?)", (payment_id,user_id,product_code,start.isoformat(),end.isoformat(),now_iso))
            reset_usage_period(user_id, product_code, conn=conn)
            ends_at = end.isoformat(); result_end = end; product_type = "subscription"
        else:
            info = ONE_TIME_PRODUCTS[product_code]
            add_credit(user_id, info["credit"], 1, conn=conn)
            conn.execute("INSERT INTO purchases(payment_id,user_id,product_code,amount,created_at) VALUES (?,?,?,?,?)", (payment_id,user_id,product_code,info["amount"],now_iso))
            ends_at = ""; result_end = None; product_type = "one_time"
        conn.execute("INSERT INTO processed_payments(payment_id,user_id,product_code,processed_at) VALUES (?,?,?,?)", (payment_id,user_id,product_code,now_iso))
        conn.execute("UPDATE payments SET status='processed',raw_status='succeeded',updated_at=? WHERE payment_id=?", (now_iso,payment_id))
        conn.execute("INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)", (payment_id,now_iso,"telegram",user_id,product_code,info["amount"],"RUB",ends_at))
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
        reward_referrer_for_first_payment(user_id, conn)
        conn.commit(); return True, result_end, product_type
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def create_support_payment(user_id, amount):
    amount_str = f"{amount:.2f}"
    return Payment.create({
        "amount": {"value": amount_str, "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://t.me/MaminPomoshnikAI_bot"},
        "capture": True,
        "description": "Добровольная поддержка развития цифрового сервиса",
        "receipt": {"customer": {"email": "client@maminpomoshnik.ru"}, "items": [{
            "description": "Добровольная поддержка развития цифрового сервиса", "quantity": "1.00",
            "amount": {"value": amount_str, "currency": "RUB"}, "vat_code": 1,
            "payment_subject": "service", "payment_mode": "full_payment"
        }]},
        "metadata": {"user_id": user_id, "product_code": "support_project", "product_type": "support"}
    }, str(uuid.uuid4()))


def save_support_payment(payment_id, user_id, amount, variant, platform="telegram"):
    amount_str = f"{amount:.2f}"
    now = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)", (payment_id, user_id, "support_project", now))
        conn.execute(
            "INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (payment_id, user_id, platform, "support", "support_project", amount_str, "RUB", "pending", now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO support_payments(payment_id,user_id,platform,amount,currency,status,variant,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (payment_id, user_id, platform, amount_str, "RUB", "pending", variant, "main_menu", now, now),
        )


def process_support_payment(payment_id, user_id):
    """Идемпотентно фиксирует добровольный платёж поддержки. Не выдаёт кредиты, не активирует подписку."""
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM processed_payments WHERE payment_id=?", (payment_id,)).fetchone():
            conn.rollback(); return False, None
        row = conn.execute("SELECT amount FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
        amount = row[0] if row else "0.00"
        conn.execute("INSERT INTO processed_payments(payment_id,user_id,product_code,processed_at) VALUES (?,?,?,?)", (payment_id, user_id, "support_project", now_iso))
        conn.execute("UPDATE payments SET status='processed',raw_status='succeeded',updated_at=? WHERE payment_id=?", (now_iso, payment_id))
        conn.execute("UPDATE support_payments SET status='processed',updated_at=? WHERE payment_id=?", (now_iso, payment_id))
        conn.execute(
            "INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)",
            (payment_id, now_iso, "telegram", user_id, "support_project", amount, "RUB", ""),
        )
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
        conn.commit(); return True, amount
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


# ─── ЛИЧНЫЙ РАЗБОР СИТУАЦИИ ───────────────────────────────────
def get_personal_review(review_id):
    with db_connect() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM personal_reviews WHERE id=?", (review_id,)).fetchone()


def get_personal_review_by_payment(payment_id):
    with db_connect() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM personal_reviews WHERE payment_id=?", (payment_id,)).fetchone()


def process_personal_review_payment(payment_id, user_id):
    """Идемпотентно фиксирует оплату личного разбора. Не выдаёт кредиты, не активирует подписку."""
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM processed_payments WHERE payment_id=?", (payment_id,)).fetchone():
            conn.rollback(); return False, None
        review_row = conn.execute("SELECT id FROM personal_reviews WHERE payment_id=?", (payment_id,)).fetchone()
        if not review_row:
            conn.rollback(); return False, None
        review_id = review_row[0]
        conn.execute(
            "UPDATE personal_reviews SET status='paid',payment_status='paid',updated_at=? "
            "WHERE payment_id=? AND status IN ('draft','payment_pending')",
            (now_iso, payment_id),
        )
        conn.execute("INSERT INTO processed_payments(payment_id,user_id,product_code,processed_at) VALUES (?,?,?,?)", (payment_id, user_id, PERSONAL_REVIEW_PRODUCT_CODE, now_iso))
        conn.execute("UPDATE payments SET status='processed',raw_status='succeeded',updated_at=? WHERE payment_id=?", (now_iso, payment_id))
        conn.execute(
            "INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)",
            (payment_id, now_iso, "telegram", user_id, PERSONAL_REVIEW_PRODUCT_CODE, f"{PERSONAL_REVIEW_PRICE_RUB:.2f}", "RUB", ""),
        )
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
        conn.commit(); return True, review_id
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def mark_personal_review_canceled(payment_id):
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute(
            "UPDATE personal_reviews SET status='cancelled',payment_status='cancelled',updated_at=? "
            "WHERE payment_id=? AND status IN ('draft','payment_pending')",
            (now_iso, payment_id),
        )


def take_personal_review(review_id, owner_id):
    """paid -> in_review, идемпотентно (повторный клик ничего не меняет)."""
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        cur = conn.execute(
            "UPDATE personal_reviews SET status='in_review',updated_at=? WHERE id=? AND status='paid'",
            (now_iso, review_id),
        )
        return cur.rowcount == 1


def attach_personal_review_voice(review_id, file_id):
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        cur = conn.execute(
            "UPDATE personal_reviews SET answer_file_id=?,updated_at=? WHERE id=? AND status='in_review'",
            (file_id, now_iso, review_id),
        )
        return cur.rowcount == 1


def mark_personal_review_answered(review_id):
    """in_review -> answered, идемпотентно. Возвращает True только на первом успешном переходе."""
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        cur = conn.execute(
            "UPDATE personal_reviews SET status='answered',answered_at=?,updated_at=? "
            "WHERE id=? AND status='in_review' AND answer_file_id IS NOT NULL",
            (now_iso, now_iso, review_id),
        )
        return cur.rowcount == 1


async def check_payments_loop():
    while True:
        await asyncio.sleep(15)
        try:
            for payment_id,user_id,product_code in get_pending_payments():
                try:
                    payment = Payment.find_one(payment_id)
                    if payment.status == "succeeded":
                        if product_code == "support_project":
                            processed, amount = process_support_payment(payment_id, user_id)
                            if not processed: continue
                            log_analytics_event("support_payment_success", user_id, "support_project", amount)
                            await bot.send_message(
                                user_id,
                                "Спасибо за поддержку ❤️ Благодаря вам «Мамин помощник» сможет развиваться и оставаться бесплатным для родителей.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Вернуться в главное меню", callback_data="main_menu")]]),
                            )
                            owner_target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
                            try: await bot.send_message(owner_target, f"💛 Поддержка проекта (Telegram)\n\nUser ID: {user_id}\nСумма: {amount} ₽\nPayment ID: {payment_id}")
                            except Exception as exc: logging.error(f"Ошибка уведомления владельца о поддержке TG: {exc}")
                            continue
                        if product_code == PERSONAL_REVIEW_PRODUCT_CODE:
                            processed, review_id = process_personal_review_payment(payment_id, user_id)
                            if not processed: continue
                            log_analytics_event("personal_review_payment_success", user_id, PERSONAL_REVIEW_PRODUCT_CODE, payment_id)
                            try:
                                await bot.send_message(user_id, "Заявка принята ✅\n\nЛичный разбор готовит автор проекта. Ответ придёт голосовым сообщением прямо сюда, в этот чат.")
                            except Exception as exc: logging.error(f"Ошибка уведомления клиента о заявке на разбор: {exc}")
                            owner_target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
                            try:
                                kb = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="Открыть заявку", callback_data=f"pr_open:{review_id}")],
                                    [InlineKeyboardButton(text="Взять в работу", callback_data=f"pr_take:{review_id}")],
                                ])
                                await bot.send_message(owner_target, f"🧩 Новая заявка на личный разбор №{review_id} — {PERSONAL_REVIEW_PRICE_RUB} ₽", reply_markup=kb)
                            except Exception as exc: logging.error(f"Ошибка уведомления владельца о заявке на разбор: {exc}")
                            continue
                        processed,end,product_type = process_commercial_payment(payment_id,user_id,product_code)
                        if not processed: continue
                        info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
                        if product_type == "subscription":
                            asyncio.create_task(asyncio.to_thread(sheets_update_subscription,user_id,product_code))
                            text = f"✅ Оплата прошла!\n\nТариф {info['name']} активирован до {end.strftime('%d.%m.%Y')}."
                            sale_end = end.isoformat()
                        else:
                            text = f"✅ Оплата прошла!\n\nПокупка «{info['name']}» начислена. Кредит спишется только после успешного результата."
                            sale_end = ""
                        asyncio.create_task(asyncio.to_thread(sheets_log_sale,user_id,product_code,info['amount'],payment_id,sale_end,"Успешно"))
                        log_analytics_event("payment_succeeded", user_id, product_code, payment_id)
                        await bot.send_message(user_id, text, reply_markup=kb_mama_menu() if get_user(user_id) and get_user(user_id)[0]=="mama" else kb_pregnant_menu())
                        owner_target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
                        try: await bot.send_message(owner_target, f"💳 Новая продажа Telegram\n\nUser ID: {user_id}\nПродукт: {info['name']}\nСумма: {info['amount']} ₽\nPayment ID: {payment_id}")
                        except Exception as exc: logging.error(f"Ошибка уведомления владельца TG: {exc}")
                    elif payment.status == "canceled":
                        if product_code == PERSONAL_REVIEW_PRODUCT_CODE:
                            mark_personal_review_canceled(payment_id)
                            mark_payment_canceled(payment_id)
                            log_analytics_event("personal_review_payment_failed", user_id, PERSONAL_REVIEW_PRODUCT_CODE, payment_id)
                            try:
                                await bot.send_message(user_id, "Оплата не завершена. Заявка на личный разбор не оформлена — попробуй ещё раз из мини-приложения.")
                            except Exception as exc: logging.error(f"Ошибка уведомления об отмене заявки на разбор: {exc}")
                            continue
                        mark_payment_canceled(payment_id)
                        if product_code == "support_project":
                            log_analytics_event("support_payment_failed", user_id, "support_project")
                            try:
                                await bot.send_message(user_id, "Оплата не завершена. Все функции «Маминого помощника» по-прежнему доступны бесплатно.")
                            except Exception as exc: logging.error(f"Ошибка уведомления об отмене поддержки TG: {exc}")
                except Exception as exc: logging.error(f"Ошибка проверки платежа {payment_id}: {exc}")
        except Exception as exc: logging.error(f"Ошибка check_payments_loop: {exc}")


# ─── ЛИЧНЫЙ РАЗБОР СИТУАЦИИ: owner-flow ───────────────────────
def _pr_status_label(status):
    return {
        "draft": "черновик", "payment_pending": "ожидает оплаты", "paid": "оплачена",
        "in_review": "в работе", "answered": "отвечена", "cancelled": "отменена",
    }.get(status, status)


@dp.callback_query(F.data.startswith("pr_open:"))
async def pr_open(call: CallbackQuery):
    if not OWNER_ID or call.from_user.id != OWNER_ID:
        await call.answer("Недоступно", show_alert=True)
        return
    try:
        review_id = int(call.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await call.answer("Некорректная заявка", show_alert=True)
        return
    row = get_personal_review(review_id)
    if not row:
        await call.answer("Заявка не найдена", show_alert=True)
        return
    reply_label = "Email" if row["preferred_reply"] == "email" else "Telegram"
    lines = [
        f"Заявка №{review_id} — {_pr_status_label(row['status'])}",
        f"User ID: {row['user_id']}",
        f"Способ ответа: {reply_label}",
    ]
    if row["preferred_reply"] == "email" and row["email"]:
        lines.append(f"Email клиента: {row['email']}")
    lines.append("")
    lines.append("Текст ситуации:")
    lines.append(row["situation_text"])
    kb_rows = []
    if row["status"] == "paid":
        kb_rows.append([InlineKeyboardButton(text="Взять в работу", callback_data=f"pr_take:{review_id}")])
    await call.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None)
    await call.answer()


@dp.callback_query(F.data.startswith("pr_take:"))
async def pr_take(call: CallbackQuery, state: FSMContext):
    if not OWNER_ID or call.from_user.id != OWNER_ID:
        await call.answer("Недоступно", show_alert=True)
        return
    try:
        review_id = int(call.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await call.answer("Некорректная заявка", show_alert=True)
        return
    ok = take_personal_review(review_id, call.from_user.id)
    if not ok:
        row = get_personal_review(review_id)
        current = _pr_status_label(row["status"]) if row else "не найдена"
        await call.answer(f"Уже {current}", show_alert=True)
        return
    await state.set_state(OwnerReviewStates.waiting_voice)
    await state.update_data(review_id=review_id)
    await call.message.answer(f"Заявка №{review_id} взята в работу. Отправь одно голосовое сообщение с ответом — оно будет привязано к этой заявке.")
    await call.answer()


@dp.message(OwnerReviewStates.waiting_voice, F.voice, F.from_user.id == OWNER_ID)
async def pr_receive_voice(message: Message, state: FSMContext):
    data = await state.get_data()
    review_id = data.get("review_id")
    if not review_id:
        await message.answer("Нет активной заявки для голосового ответа.")
        await state.clear()
        return
    ok = attach_personal_review_voice(review_id, message.voice.file_id)
    await state.clear()
    if not ok:
        await message.answer(f"Не удалось привязать голосовое к заявке №{review_id} — проверь её статус через «Открыть заявку».")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить ответ клиенту", callback_data=f"pr_send:{review_id}")],
        [InlineKeyboardButton(text="🔁 Записать заново", callback_data=f"pr_rerecord:{review_id}")],
    ])
    await message.answer("Отправить ответ клиенту?", reply_markup=kb)


@dp.callback_query(F.data.startswith("pr_rerecord:"))
async def pr_rerecord(call: CallbackQuery, state: FSMContext):
    if not OWNER_ID or call.from_user.id != OWNER_ID:
        await call.answer("Недоступно", show_alert=True)
        return
    try:
        review_id = int(call.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await call.answer("Некорректная заявка", show_alert=True)
        return
    row = get_personal_review(review_id)
    if not row or row["status"] != "in_review":
        await call.answer("Заявка недоступна для перезаписи", show_alert=True)
        return
    await state.set_state(OwnerReviewStates.waiting_voice)
    await state.update_data(review_id=review_id)
    await call.message.answer(f"Хорошо, пришли новое голосовое для заявки №{review_id}.")
    await call.answer()


@dp.callback_query(F.data.startswith("pr_send:"))
async def pr_send(call: CallbackQuery):
    if not OWNER_ID or call.from_user.id != OWNER_ID:
        await call.answer("Недоступно", show_alert=True)
        return
    try:
        review_id = int(call.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await call.answer("Некорректная заявка", show_alert=True)
        return
    row = get_personal_review(review_id)
    if not row or row["status"] != "in_review" or not row["answer_file_id"]:
        await call.answer("Заявка не готова к отправке", show_alert=True)
        return
    client_user_id = row["user_id"]
    preferred_reply = row["preferred_reply"]
    answer_file_id = row["answer_file_id"]
    if preferred_reply == "email":
        delivered = mark_personal_review_answered(review_id)
        if not delivered:
            await call.answer("Ответ уже был отправлен", show_alert=True)
            return
        await call.message.answer(
            f"Заявка №{review_id}: клиент выбрал ответ по email.\n"
            f"Email клиента: {row['email'] or '—'}\n\n"
            "Голосовое сохранено — отправь его на почту клиента вручную. Ниже пересылаю запись для удобства."
        )
        try:
            await bot.send_voice(call.from_user.id, answer_file_id)
        except Exception as exc:
            logging.error(f"Не удалось переслать голосовое владельцу для заявки {review_id}: {exc}")
    else:
        try:
            await bot.send_message(client_user_id, "Ваш разбор готов 🎧")
            await bot.send_voice(client_user_id, answer_file_id)
        except Exception as exc:
            logging.error(f"Не удалось отправить голосовое клиенту по заявке {review_id}: {exc}")
            await call.message.answer(f"Не удалось отправить сообщение клиенту (заявка №{review_id}): {exc}")
            await call.answer("Не удалось отправить ответ клиенту", show_alert=True)
            return
        delivered = mark_personal_review_answered(review_id)
        if not delivered:
            await call.answer("Ответ уже был отправлен", show_alert=True)
            return
        await call.message.answer(f"Готово — ответ отправлен клиенту (заявка №{review_id}).")
    log_analytics_event("personal_review_answered", client_user_id, PERSONAL_REVIEW_PRODUCT_CODE, review_id)
    await call.answer()


async def start_product_payment(call, product_code):
    try:
        info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
        payment = await create_payment_mama(call.from_user.id, product_code)
        save_commercial_payment(payment.id, call.from_user.id, product_code)
        log_analytics_event("payment_created", call.from_user.id, product_code, payment.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {int(float(info['amount']))} ₽", url=payment.confirmation.confirmation_url)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="show_premium")],
        ])
        await call.message.answer(f"{info['name']}\n\nСтоимость: {int(float(info['amount']))} ₽.\nПосле оплаты доступ активируется автоматически.", reply_markup=kb)
    except Exception as exc:
        logging.error(f"Ошибка создания платежа TG: {exc}")
        await call.message.answer("Не удалось создать платёж. Попробуй позже или напиши в поддержку.", reply_markup=kb_premium())


def kb_already_free():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Поддержать проект", callback_data="donate_menu")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu")],
    ])


@dp.callback_query(F.data == "pay_premium")
@dp.callback_query(F.data == "show_premium")
async def show_premium(call: CallbackQuery):
    # Старые тарифные ссылки/кнопки больше не продают функционал — он бесплатный.
    await call.message.answer(
        "Все текущие функции «Маминого помощника» теперь доступны бесплатно.",
        reply_markup=kb_already_free(),
    )


@dp.callback_query(F.data.startswith("pay_plan_"))
async def pay_plan_selected(call: CallbackQuery):
    await show_premium(call)


@dp.callback_query(F.data.startswith("buy_"))
async def buy_product_selected(call: CallbackQuery):
    await show_premium(call)

# ─── ПОДДЕРЖАТЬ ПРОЕКТ (добровольно) ─────────────────────────
DONATE_AMOUNTS = [
    (99, "99 ₽ — Сказать спасибо"),
    (199, "199 ₽ — Поддержать развитие"),
    (499, "499 ₽ — Большое спасибо"),
    (990, "990 ₽ — Помочь проекту расти"),
]
DONATE_MIN_AMOUNT = 10
DONATE_MAX_AMOUNT = 100000

class DonateStates(StatesGroup):
    waiting_custom_amount = State()

def kb_donate_menu():
    rows = [[InlineKeyboardButton(text=label, callback_data=f"donate_amt_{amount}")] for amount, label in DONATE_AMOUNTS]
    rows.append([InlineKeyboardButton(text="Другая сумма", callback_data="donate_amt_custom")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "donate_menu")
async def donate_menu(call: CallbackQuery):
    log_analytics_event("support_open", call.from_user.id)
    await call.message.answer(
        "Поддержать проект\n\n"
        "«Мамин помощник» остаётся бесплатным для всех родителей. Если проект оказался полезен, "
        "вы можете поддержать его развитие любой удобной суммой. Это добровольная благодарность — "
        "все функции доступны и без оплаты.",
        reply_markup=kb_donate_menu(),
    )

async def show_donate_confirm(message, amount, variant):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {amount:.0f} ₽" if amount == int(amount) else f"Оплатить {amount:.2f} ₽", callback_data=f"donate_confirm:{variant}:{amount:.2f}")],
        [InlineKeyboardButton(text="Назад", callback_data="donate_menu")],
    ])
    await message.answer(
        "Вы поддерживаете развитие бесплатного проекта «Мамин помощник». "
        "Оплата добровольная и не открывает дополнительных функций — они уже доступны всем.",
        reply_markup=kb,
    )

@dp.callback_query(F.data.startswith("donate_amt_"))
async def donate_amount_selected(call: CallbackQuery, state: FSMContext):
    variant = call.data.replace("donate_amt_", "", 1)
    if variant == "custom":
        log_analytics_event("support_custom", call.from_user.id)
        await state.set_state(DonateStates.waiting_custom_amount)
        await call.message.answer(f"Введи сумму в рублях (от {DONATE_MIN_AMOUNT} до {DONATE_MAX_AMOUNT}):")
        return
    try:
        amount = float(variant)
    except ValueError:
        return
    if not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
        return
    log_analytics_event(f"support_amount_{variant}", call.from_user.id)
    await show_donate_confirm(call.message, amount, variant)

@dp.message(DonateStates.waiting_custom_amount, F.text)
async def donate_custom_amount_input(message: Message, state: FSMContext):
    await state.clear()
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        amount = None
    if amount is None or not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
        await message.answer(
            f"Пожалуйста, введи сумму от {DONATE_MIN_AMOUNT} до {DONATE_MAX_AMOUNT} рублей, например: 250",
            reply_markup=kb_donate_menu(),
        )
        return
    await show_donate_confirm(message, round(amount, 2), "custom")

@dp.callback_query(F.data.startswith("donate_confirm:"))
async def donate_confirm(call: CallbackQuery):
    try:
        _, variant, amount_str = call.data.split(":", 2)
        amount = float(amount_str)
    except (ValueError, IndexError):
        await call.message.answer("Не удалось определить сумму. Попробуй ещё раз.", reply_markup=kb_donate_menu())
        return
    if not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
        await call.message.answer("Некорректная сумма.", reply_markup=kb_donate_menu())
        return
    try:
        payment = create_support_payment(call.from_user.id, amount)
        save_support_payment(payment.id, call.from_user.id, amount, variant, "telegram")
        log_analytics_event("support_payment_created", call.from_user.id, variant, amount_str)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {amount:.0f} ₽", url=payment.confirmation.confirmation_url)],
            [InlineKeyboardButton(text="Назад", callback_data="donate_menu")],
        ])
        await call.message.answer("Спасибо! Нажми кнопку ниже, чтобы завершить оплату.", reply_markup=kb)
    except Exception as exc:
        logging.error(f"Ошибка создания платежа поддержки TG: {exc}")
        await call.message.answer("Не удалось создать платёж. Попробуй позже.", reply_markup=kb_donate_menu())

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
    current_state = await state.get_state()
    await state.clear()
    username = message.from_user.username or "нет"
    name = message.from_user.first_name or ""
    plan, sub_end = get_subscription(message.from_user.id)
    plan_name = PLAN_CATALOG.get(plan, {}).get("name", "Бесплатный") if plan else "Бесплатный"
    end_text = ""
    if sub_end:
        try: end_text = datetime.fromisoformat(str(sub_end)).strftime("%d.%m.%Y")
        except Exception: end_text = str(sub_end)
    target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
    support_text = (
        f"🆘 Поддержка Мамин Помощник Telegram\n\n"
        f"Платформа: Telegram\nИмя: {name or 'без имени'}\nUsername: @{username}\n"
        f"ID: {message.from_user.id}\nТариф: {plan_name}\nОкончание: {end_text or '—'}\n"
        f"Текущий шаг: {current_state or 'не определён'}\n\nСообщение:\n{message.text}"
    )
    try:
        await bot.send_message(target, support_text[:3900])
    except Exception as e:
        logging.error(f"Support send error: {e}")
    import threading
    threading.Thread(target=sheets_upsert_user, args=(message.from_user.id, message.from_user.username or "", name), kwargs={"last_action":"Обращение в поддержку"}).start()
    await message.answer(
        "✅ Сообщение отправлено! Мы ответим в ближайшее время.\n\n"
        f"Резервный контакт: {SUPPORT_USERNAME}",
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

# ─── ОДНОРАЗОВАЯ РАССЫЛКА ОБРАТНОЙ СВЯЗИ (campaign: feedback_features_2026_09) ──
FEEDBACK_CAMPAIGN_KEY = "feedback_features_2026_09"
FEEDBACK_CAMPAIGN_TEXT = (
    "❤️ Дорогие мамы!\n\n"
    "Мне очень приятно видеть, что вас становится всё больше и что «Мамин Помощник» "
    "действительно используется каждый день.\n\n"
    "Я продолжаю развивать приложение и хочу делать его не просто больше, а действительно "
    "полезнее именно для вас.\n\n"
    "Поэтому хочу спросить:\n\n"
    "Какой функции вам сейчас не хватает? Что вы хотели бы видеть в приложении дальше?\n\n"
    "Это может быть что угодно — новый трекер, полезный раздел, напоминания, новая возможность "
    "для ребёнка или для мамы.\n\n"
    "Я читаю ваши предложения и буду учитывать их при следующих обновлениях ❤️\n\n"
    "Нажмите кнопку ниже и напишите свою идею."
)

def feedback_campaign_kb_tg():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Предложить функцию", callback_data="fb2026:suggest")],
        [InlineKeyboardButton(text="❤️ Всё нравится", callback_data="fb2026:like")],
    ])

class FeedbackCampaignStates(StatesGroup):
    waiting_suggestion = State()

def _claim_feedback_broadcast_tg(user_id):
    now = datetime.now().isoformat()
    conn = db_connect()
    try:
        cur = conn.execute(
            "INSERT INTO broadcast_log(broadcast_key, platform, user_id, status, error_code, ts) "
            "VALUES (?, 'telegram', ?, 'claimed', '', ?) "
            "ON CONFLICT(broadcast_key, platform, user_id) DO UPDATE SET status='claimed', ts=excluded.ts "
            "WHERE broadcast_log.status NOT IN ('sent', 'claimed', 'forbidden', 'blocked')",
            (FEEDBACK_CAMPAIGN_KEY, user_id, now),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()

def _mark_feedback_broadcast_tg(user_id, status, error_code=""):
    now = datetime.now().isoformat()
    conn = db_connect()
    try:
        conn.execute(
            "UPDATE broadcast_log SET status=?, error_code=?, ts=? WHERE broadcast_key=? AND platform='telegram' AND user_id=?",
            (status, str(error_code)[:200], now, FEEDBACK_CAMPAIGN_KEY, user_id),
        )
        conn.commit()
    finally:
        conn.close()

def _feedback_broadcast_status_tg(user_id):
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT status FROM broadcast_log WHERE broadcast_key=? AND platform='telegram' AND user_id=?",
            (FEEDBACK_CAMPAIGN_KEY, user_id),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

async def send_feedback_campaign_tg():
    """Ручная одноразовая рассылка обратной связи. Не запускается из scheduler/main —
    вызывается один раз внешним job-скриптом. Безопасна для повторного запуска: уже
    отправленным по этому broadcast_key пользователям сообщение повторно не уходит."""
    conn = db_connect()
    try:
        rows = conn.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL AND user_id > 0").fetchall()
    finally:
        conn.close()
    audience = [r[0] for r in rows if r[0] != OWNER_ID]
    sent, failed = 0, 0
    for user_id in audience:
        if not _claim_feedback_broadcast_tg(user_id):
            status = _feedback_broadcast_status_tg(user_id)
            if status == "sent":
                sent += 1
            else:
                failed += 1
            continue
        try:
            await bot.send_message(user_id, FEEDBACK_CAMPAIGN_TEXT, reply_markup=feedback_campaign_kb_tg())
            _mark_feedback_broadcast_tg(user_id, "sent")
            sent += 1
        except TelegramForbiddenError:
            _mark_feedback_broadcast_tg(user_id, "forbidden")
            failed += 1
        except TelegramBadRequest as e:
            _mark_feedback_broadcast_tg(user_id, "chat_not_found", str(e))
            failed += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(user_id, FEEDBACK_CAMPAIGN_TEXT, reply_markup=feedback_campaign_kb_tg())
                _mark_feedback_broadcast_tg(user_id, "sent")
                sent += 1
            except Exception as e2:
                _mark_feedback_broadcast_tg(user_id, "temp_error", str(e2))
                failed += 1
        except Exception as e:
            _mark_feedback_broadcast_tg(user_id, "temp_error", str(e))
            failed += 1
        await asyncio.sleep(0.15)
    return {"audience": len(audience), "sent": sent, "failed": failed}

@dp.callback_query(F.data == "fb2026:suggest")
async def fb2026_suggest(call: CallbackQuery, state: FSMContext):
    await state.set_state(FeedbackCampaignStates.waiting_suggestion)
    await call.message.answer(
        "💬 Напишите одним сообщением, какую функцию или возможность вы хотели бы добавить "
        "в «Мамин Помощник».\n\nМожно написать совсем коротко — я обязательно прочитаю ❤️"
    )
    await call.answer()

@dp.message(FeedbackCampaignStates.waiting_suggestion, F.text, ~F.text.startswith("/"))
async def fb2026_suggestion_send(message: Message, state: FSMContext):
    await state.clear()
    username = message.from_user.username or ""
    name = message.from_user.first_name or ""
    target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
    username_line = f"@{username}" if username else "—"
    owner_text = (
        "💡 Новое предложение\n\n"
        "Платформа: Telegram\n"
        f"Имя: {name or '—'}\n"
        f"Username: {username_line}\n"
        f"User ID: {message.from_user.id}\n"
        f"Предложение:\n{message.text}"
    )
    try:
        await bot.send_message(target, owner_text[:3900])
    except Exception as e:
        logging.error(f"fb2026 suggestion owner notify error: {e}")
    import threading
    threading.Thread(target=sheets_add_review, args=(
        message.from_user.id, message.from_user.username, message.text, "Предложения МамаБот"
    )).start()
    await message.answer(
        "Спасибо ❤️ Предложение отправлено. Я обязательно его прочитаю.",
        reply_markup=kb_mama_menu() if get_user(message.from_user.id) and get_user(message.from_user.id)[0] == "mama" else kb_start()
    )

@dp.callback_query(F.data == "fb2026:like")
async def fb2026_like(call: CallbackQuery):
    user_id = call.from_user.id
    now = datetime.now().isoformat()
    conn = db_connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO feedback_campaign_likes(campaign_key, platform, user_id, created_at) VALUES (?, 'telegram', ?, ?)",
            (FEEDBACK_CAMPAIGN_KEY, user_id, now),
        )
        conn.commit()
        already = cur.rowcount == 0
    finally:
        conn.close()
    await call.answer()
    if already:
        await call.message.answer("Спасибо ❤️ Ваш ответ уже получен.")
        return
    username = call.from_user.username or ""
    name = call.from_user.first_name or ""
    target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
    username_line = f"@{username}" if username else "—"
    owner_text = (
        "❤️ Положительная обратная связь\n\n"
        "Платформа: Telegram\n"
        f"Имя: {name or '—'}\n"
        f"Username: {username_line}\n"
        f"User ID: {user_id}\n"
        "Ответ: Всё нравится"
    )
    try:
        await bot.send_message(target, owner_text[:3900])
    except Exception as e:
        logging.error(f"fb2026 like owner notify error: {e}")
    import threading
    threading.Thread(target=sheets_add_review, args=(
        user_id, username, "Всё нравится (кампания feedback_features_2026_09)", "Отзывы МамаБот"
    )).start()
    await call.message.answer(
        "Спасибо ❤️ Очень приятно это знать. Такие сообщения действительно помогают продолжать развивать приложение."
    )

# ─── ОДНОРАЗОВАЯ РАССЫЛКА «ПРИКОРМ 6+» (campaign: complementary_foods_2026_09) ──
CF_CAMPAIGN_KEY = "complementary_foods_2026_09"
CF_CAMPAIGN_TEXT = (
    "🥣 Новая функция — «Прикорм 6+» ❤️\n\n"
    "Дорогие мамы, в «Мамин Помощник» появился новый раздел для начала прикорма.\n\n"
    "Теперь можно:\n"
    "• посмотреть, что можно давать ребёнку по возрасту;\n"
    "• отмечать уже попробованные продукты;\n"
    "• сохранять, что понравилось или не понравилось;\n"
    "• отмечать возможную реакцию;\n"
    "• смотреть рекомендации по введению продуктов и важные правила безопасности.\n\n"
    "Раздел находится:\nПитание → Прикорм 6+\n\n"
    "Буду очень рада вашей обратной связи ❤️\n"
    "Попробуйте новую функцию и напишите, насколько она вам полезна и чего в ней ещё не хватает."
)

def cf_campaign_kb_tg():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥣 Открыть «Прикорм 6+»", web_app=WebAppInfo(url=MINIAPP_URL + "?screen=complementary-feeding"))],
        [InlineKeyboardButton(text="💬 Оставить мнение", callback_data="cf2026:feedback")],
    ])

class CFCampaignStates(StatesGroup):
    waiting_feedback = State()

def _claim_cf_broadcast_tg(user_id):
    now = datetime.now().isoformat()
    conn = db_connect()
    try:
        cur = conn.execute(
            "INSERT INTO broadcast_log(broadcast_key, platform, user_id, status, error_code, ts) "
            "VALUES (?, 'telegram', ?, 'claimed', '', ?) "
            "ON CONFLICT(broadcast_key, platform, user_id) DO UPDATE SET status='claimed', ts=excluded.ts "
            "WHERE broadcast_log.status NOT IN ('sent', 'claimed', 'forbidden', 'blocked')",
            (CF_CAMPAIGN_KEY, user_id, now),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()

def _mark_cf_broadcast_tg(user_id, status, error_code=""):
    now = datetime.now().isoformat()
    conn = db_connect()
    try:
        conn.execute(
            "UPDATE broadcast_log SET status=?, error_code=?, ts=? WHERE broadcast_key=? AND platform='telegram' AND user_id=?",
            (status, str(error_code)[:200], now, CF_CAMPAIGN_KEY, user_id),
        )
        conn.commit()
    finally:
        conn.close()

def _cf_broadcast_status_tg(user_id):
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT status FROM broadcast_log WHERE broadcast_key=? AND platform='telegram' AND user_id=?",
            (CF_CAMPAIGN_KEY, user_id),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

async def send_cf_campaign_tg():
    """Ручная одноразовая рассылка «Прикорм 6+». Не запускается из scheduler/main —
    вызывается один раз внешним job-скриптом. Безопасна для повторного запуска: уже
    отправленным по этому broadcast_key пользователям сообщение повторно не уходит."""
    conn = db_connect()
    try:
        rows = conn.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL AND user_id > 0").fetchall()
    finally:
        conn.close()
    audience = [r[0] for r in rows if r[0] != OWNER_ID]
    sent, failed = 0, 0
    for user_id in audience:
        if not _claim_cf_broadcast_tg(user_id):
            status = _cf_broadcast_status_tg(user_id)
            if status == "sent":
                sent += 1
            else:
                failed += 1
            continue
        try:
            await bot.send_message(user_id, CF_CAMPAIGN_TEXT, reply_markup=cf_campaign_kb_tg())
            _mark_cf_broadcast_tg(user_id, "sent")
            sent += 1
        except TelegramForbiddenError:
            _mark_cf_broadcast_tg(user_id, "forbidden")
            failed += 1
        except TelegramBadRequest as e:
            _mark_cf_broadcast_tg(user_id, "chat_not_found", str(e))
            failed += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(user_id, CF_CAMPAIGN_TEXT, reply_markup=cf_campaign_kb_tg())
                _mark_cf_broadcast_tg(user_id, "sent")
                sent += 1
            except Exception as e2:
                _mark_cf_broadcast_tg(user_id, "temp_error", str(e2))
                failed += 1
        except Exception as e:
            _mark_cf_broadcast_tg(user_id, "temp_error", str(e))
            failed += 1
        await asyncio.sleep(0.15)
    return {"audience": len(audience), "sent": sent, "failed": failed}

@dp.callback_query(F.data == "cf2026:feedback")
async def cf2026_feedback(call: CallbackQuery, state: FSMContext):
    await state.set_state(CFCampaignStates.waiting_feedback)
    await call.message.answer(
        "💬 Напишите одним сообщением, как вам новый раздел «Прикорм 6+».\n\n"
        "Что понравилось? Чего не хватает? Что стоит сделать удобнее?\n\n"
        "Я обязательно прочитаю ❤️"
    )
    await call.answer()

@dp.message(CFCampaignStates.waiting_feedback, F.text)
async def cf2026_feedback_send(message: Message, state: FSMContext):
    await state.clear()
    username = message.from_user.username or ""
    name = message.from_user.first_name or ""
    target = OWNER_ID or CHANNEL_REPORT_CHAT_ID
    username_line = f"@{username}" if username else "—"
    owner_text = (
        "🥣 Отзыв о «Прикорм 6+»\n\n"
        "Платформа: Telegram\n"
        f"Имя: {name or '—'}\n"
        f"Username: {username_line}\n"
        f"User ID: {message.from_user.id}\n\n"
        f"Отзыв:\n{message.text}"
    )
    try:
        await bot.send_message(target, owner_text[:3900])
    except Exception as e:
        logging.error(f"cf2026 feedback owner notify error: {e}")
    import threading
    threading.Thread(target=sheets_add_review, args=(
        message.from_user.id, message.from_user.username, f"ОТЗЫВ (Прикорм 6+): {message.text}", "Отзывы МамаБот"
    )).start()
    await message.answer(
        "Спасибо ❤️ Ваше мнение отправлено. Оно поможет сделать «Прикорм 6+» полезнее.",
        reply_markup=kb_mama_menu() if get_user(message.from_user.id) and get_user(message.from_user.id)[0] == "mama" else kb_start()
    )

@dp.message(Command("myid"))
async def myid_tg(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")


@dp.message(Command("reset_me"))
async def reset_me_tg(message: Message, state: FSMContext):
    """Полностью сбрасывает личные тестовые данные пользователя, но сохраняет журнал продаж."""
    await state.clear()
    await message.answer(
        "⚠️ Это удалит ваш профиль и сохранённые данные в боте. Платёжный журнал не удаляется.\n\n"
        "Удалить данные?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить данные", callback_data="reset_me_confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="reset_me_cancel")],
        ])
    )


@dp.callback_query(F.data == "reset_me_cancel")
async def reset_me_cancel_tg(call: CallbackQuery):
    await call.message.edit_text("Отменено. Данные не удалены.")


@dp.callback_query(F.data == "reset_me_confirm")
async def reset_me_confirm_tg(call: CallbackQuery, state: FSMContext):
    """Полностью сбрасывает личные тестовые данные пользователя, но сохраняет журнал продаж."""
    user_id = call.from_user.id
    await state.clear()
    tables = [
        "diary", "growth", "symptoms", "feeding", "sleep_log", "psycho_history",
        "vaccinations", "subscriptions", "requests_count", "user_credits",
        "marketing_offers", "pending_payments", "users"
    ]
    conn = db_connect()
    try:
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()
    await call.message.edit_text("✅ Ваш профиль и тестовые данные сброшены. Нажмите /start для новой регистрации.")


@dp.message(Command("test_channel_visual"))
async def test_channel_visual_tg(message: Message):
    """AI-генерация изображений временно отключена."""
    if not OWNER_ID or message.from_user.id != OWNER_ID:
        await message.answer("Команда доступна только владельцу. Сначала задайте TG_OWNER_ID.")
        return
    await message.answer("ℹ️ Генерация картинок отключена. Канал публикует текстовые посты.")


@dp.message(Command("publish_channel_intro"))
async def publish_channel_intro_tg(message: Message):
    if not OWNER_ID or message.from_user.id != OWNER_ID:
        await message.answer("Команда доступна только владельцу. Сначала задайте TG_OWNER_ID.")
        return
    text = (
        "🤍 Я МАМА — пространство без чувства вины и гонки за идеальностью.\n\n"
        "Здесь каждый день выходят три коротких и полезных материала: поддержка утром, "
        "практический разбор днём и спокойный вечерний разговор.\n\n"
        "А в «Мамином помощнике» можно получить персональный план, вести сон и кормления, "
        "собрать сводку к врачу и задать вопрос с учётом возраста ребёнка или срока беременности.\n\n"
        "Медицинские материалы носят информационный характер и не заменяют врача. "
        "Резервный контакт поддержки указан в описании канала."
    )
    await bot.send_message(
        CHANNEL_ID, text,
        reply_markup=channel_post_markup("✨ Открыть Маминого помощника", "channel_today"),
        disable_web_page_preview=True,
    )
    await message.answer("✅ Приветственный пост опубликован. Закрепи его в канале вручную.")


# ─── АВТОПОСТИНГ В КАНАЛ ─────────────────────────────────────

CHANNEL_ID = "@yamama_ai"
BOT_BASE_URL = "https://t.me/MaminPomoshnikAI_bot"
BOT_PUBLIC_URL = f"{BOT_BASE_URL}?start=channel"

# 3 поста в день, 8 рубрик практического родительского контента (без ежедневных
# выдуманных семейных историй). Категории: REC рецепт, WHATIF воспитание/поведение,
# HEALTH здоровье-сон-врач, AGE сад/школа/развитие по возрасту, MOM мама тоже человек,
# DAD папин взгляд (короткое наблюдение, не сюжет), FAM бабушки-дедушки-семья,
# SAVE сохрани-пригодится (также резерв вместо личной истории без фактов владельца).
# Темы и форматы вращаются по дням и сохраняются в БД, чтобы канал не повторялся.

CHANNEL_CONTENT_LIBRARY_PATH = "/root/mama_channel_content.json"

# Редакционная архитектура: свободная AI-генерация поста с нуля больше не используется.
# Основа каждой публикации — заранее написанный и вручную проверенный материал из
# библиотеки CHANNEL_CONTENT_LIBRARY_PATH (минимум 120 готовых постов). AI-адаптация
# (лёгкая правка вступления/порядка абзацев/CTA-фразы) необязательна и по умолчанию
# выключена — надёжный дефолт после FINAL_FAIL свободной генерации в предыдущей задаче
# (JOB_20260711_175411). Включать только после отдельной проверки владельцем.
CHANNEL_AI_ADAPTATION_ENABLED = False

CHANNEL_LIBRARY_MAX_CHARS = {
    "REC": 2000, "WHATIF": 1300, "HEALTH": 1300, "AGE": 1300,
    "MOM": 1200, "DAD": 700, "FAM": 1200, "SAVE": 1200,
}

# Рубрика -> все format_name, которые ей присваиваются (для анти-повтора по истории
# публикаций: get_recent_channel_posts хранит только slot/theme/format_name/text).
CHANNEL_FORMAT_NAMES_BY_CATEGORY = {
    "REC": ("рецепт",),
    "WHATIF": ("что делать, если", "поговорим честно"),
    "HEALTH": ("здоровье и сон",),
    "AGE": ("по возрасту",),
    "MOM": ("мама тоже человек",),
    "DAD": ("папин взгляд",),
    "FAM": ("семья и бабушки",),
    "SAVE": ("сохрани, пригодится",),
}

_channel_content_library_cache = None


def load_channel_content_library():
    """Загружает и кеширует библиотеку готовых постов из CHANNEL_CONTENT_LIBRARY_PATH."""
    global _channel_content_library_cache
    if _channel_content_library_cache is None:
        with open(CHANNEL_CONTENT_LIBRARY_PATH, "r", encoding="utf-8") as f:
            _channel_content_library_cache = json.load(f)
    return _channel_content_library_cache


def channel_library_by_category(category):
    return [item for item in load_channel_content_library() if item.get("category") == category]


def _recent_channel_topics(limit=45):
    return {theme_ for _, theme_, _, _ in get_recent_channel_posts(limit) if theme_}


def _recent_channel_topics_for_category(category, limit):
    format_names = CHANNEL_FORMAT_NAMES_BY_CATEGORY.get(category, ())
    rows = get_recent_channel_posts(limit)
    return [theme_ for _, theme_, f, _ in rows if f in format_names and theme_]


def select_channel_library_post(category, rnd, exclude_topics=()):
    """Выбирает готовый пост из библиотеки: не повторяет тему/id до полного цикла
    рубрики и не повторяет тему за последние 45 публикаций (раздел 9 задачи)."""
    pool = channel_library_by_category(category)
    if not pool:
        return None
    cycle_len = max(len(pool) - 1, 0)
    recent_in_category = _recent_channel_topics_for_category(category, limit=cycle_len + 45 + 5)
    banned_topics = set(recent_in_category[:cycle_len]) | _recent_channel_topics(45) | set(exclude_topics)
    candidates = [item for item in pool if item["topic"] not in banned_topics]
    if not candidates:
        candidates = [item for item in pool if item["topic"] not in exclude_topics] or list(pool)
    return rnd.choice(candidates)

CHANNEL_SYSTEM_PROMPT = (
    "Ты ведёшь канал «Мамин помощник» — полезно о детях, семье и родительской жизни простыми человеческими словами. "
    "Твой голос — это голос отца троих дочерей, но ты не обязан быть героем каждого поста и не должен ежедневно "
    "сочинять события своей семьи: тебе запрещено выдумывать конкретные биографические события автора, жены и "
    "дочерей. Настоящие личные истории — отдельная серия и не твоя задача. "
    "Пиши простым разговорным русским языком, обращайся к читателям напрямую, абзацы разной длины, лёгкий юмор "
    "и самоирония уместны, конкретика и практическая польза обязательны, переходы между мыслями естественные. "
    "Каждый пост должен звучать так, будто его написал живой человек, а не нейросеть и не редакция. "
    "Запрещено: сочинять ежедневные истории семьи автора; придумывать прямую речь детей; указывать возраст детей "
    "в скобках вроде «старшая (11 лет)»; служебные заголовки-названия формата («История дня», «Семейная история», "
    "«Полезный пост», «Ситуация из жизни»); название рубрики в тексте поста; сценические ремарки в скобках; "
    "искусственные диалоги; обязательный счастливый финал; мораль в конце; высокопарные метафоры; журнальный или "
    "канцелярский язык; странные литературные обороты; образ идеального и мудрого отца; одинаковая композиция "
    "каждый день; фальшивые исследования и статистика; советы, приписанные врачам или психологам без источника; "
    "диагнозы; назначение лечения; гарантированный результат. "
    "Особенно запрещены фразы: «И тут я понял…», «В такие моменты понимаешь…», «Ссоры временны, а дружба навсегда», "
    "«Как важно создавать пространство…», «Жизнь внесла свои коррективы», «Серые тучи сгущались», «Мораль этой "
    "истории», «Каждая мама должна», «Важно помнить», «Давайте разберёмся», «По мнению экспертов» без конкретного "
    "проверенного источника, «каждый ребёнок уникален», «главное — сохранять спокойствие», «это нормально», "
    "«в современном мире», «ни для кого не секрет», «внешняя сторона семьи», «бешеный диссонанс», «полная "
    "безысходность», «хорошая мама должна», «хорошая мама обязана», «это важная тема для родителей», «это может "
    "быть стрессовым моментом», «непростой процесс». "
    "Не давай советы без конкретики вроде «просто будьте рядом», «уделите ребёнку внимание», «создайте атмосферу "
    "поддержки», «следите за состоянием» — если даёшь такой совет, сразу поясни, что именно делать: что сказать, "
    "что сделать руками, сколько минут, что именно наблюдать. Вместо «поддержите ребёнка» пиши «сядьте рядом», "
    "«скажите, что будет происходить», «предложите выбрать игрушку» — конкретное действие вместо общего лозунга. "
    "Не начинай пост с общих фраз вроде «Сегодня я хочу поговорить о важной теме», «В современном мире родители "
    "часто сталкиваются», «Давайте разберёмся», «Важно помнить», «Гаджеты — важная тема для родителей», "
    "«Воспитание детей — непростой процесс». Начинай сразу с конкретной ситуации, вопроса или факта, как будто "
    "читатель уже в середине разговора, например: «Если ребёнок боится уколов, фраза 'не бойся' часто не "
    "помогает», «Ребёнок снова говорит, что не хочет в садик», «Этот ужин можно приготовить за 25 минут». "
    "Ты — мужчина, отец троих дочерей, ведущий канала, а не герой каждого текста: фразы вроде «с тремя детьми "
    "быстро понимаешь одну вещь…», «мне как папе это тоже знакомо» уместны изредка и только по смыслу, не в "
    "каждом посте; формальные вставки авторства без содержания («я сам это чувствую», «на мой взгляд» без "
    "продолжения мысли) запрещены. "
    "Никогда не выдумывай сцены и цитаты, поданные как реальные сегодняшние или вчерашние события — что "
    "сказала бабушка, жена, ребёнок или сосед, что случилось только что дома у автора. Готовая фраза для "
    "разговора с ребёнком — это совет читателю, что сказать («скажите: 'я рядом'»), а не цитата в кавычках "
    "с припиской «сказала», «заявила», «эта фраза сегодня звучала» — так писать запрещено. "
    "Каждый пост обязан дать читателю конкретный результат: чек-лист, последовательность действий, рецепт, "
    "готовую фразу для разговора с ребёнком, вопросы врачу, понятное правило или наблюдение. Если после текста "
    "нельзя ответить, что именно читатель узнал, сохранил или сможет попробовать — текст не годится. "
    "Не заканчивай пост фразами «всё обязательно получится», «главное — любовь», «семья — это самое важное», "
    "«каждый момент бесценен», «детство проходит быстро» — заверши конкретным выводом, вопросом, предложением "
    "сохранить пост или уместным по теме CTA. "
    "Про здоровье пиши только информационно и организационно: наблюдения, дневник симптомов, вопросы врачу, режим "
    "сна, напоминание обратиться за медицинской помощью — без диагнозов, без дозировок, без замены врача. Точные "
    "возрастные нормы, нормы сна, экранного времени и другие цифры без проверенного источника не выдумывай — "
    "используй осторожные формулировки вроде «ориентируйтесь на рекомендации своего педиатра» или «нормы "
    "индивидуальны и зависят от ситуации». "
    "Не придумывай реальные даты, города, новости, исследования или статистику. Не обрывай текст на середине слова "
    "или фразы. Каждый пост должен отличаться от недавних по теме, началу и структуре — не используй одинаковое "
    "начало и одну и ту же композицию постоянно. Один естественный вопрос читателям или просьба поделиться опытом "
    "уместны не в каждом посте, а изредка и по смыслу."
)


def save_channel_post(slot, theme, format_name, title, text):
    conn = db_connect()
    conn.execute(
        "INSERT INTO channel_posts (slot, theme, format_name, title, text, created_at) VALUES (?,?,?,?,?,?)",
        (slot, theme, format_name, title, text, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def channel_slot_published_today(slot):
    conn = db_connect()
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = conn.execute(
        "SELECT 1 FROM channel_posts WHERE slot=? AND created_at>=? ORDER BY id DESC LIMIT 1",
        (slot, start),
    ).fetchone()
    conn.close()
    return bool(row)


def get_recent_channel_posts(limit=40):
    conn = db_connect()
    rows = conn.execute(
        "SELECT title, theme, format_name, text FROM channel_posts ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def channel_history_for_prompt(limit=30):
    rows = get_recent_channel_posts(limit)
    if not rows:
        return "История пока пустая."
    lines = []
    for title, theme, format_name, text in rows:
        compact = " ".join((text or "").split())[:180]
        lines.append(f"- {title} | {theme} | {format_name} | {compact}")
    return "\n".join(lines)


def normalize_for_similarity(text):
    import re
    return " ".join(re.sub(r"[^а-яёa-z0-9 ]", " ", (text or "").lower()).split())


def is_channel_post_too_similar(title, text, threshold=0.66, edge_threshold=0.8):
    """Сравнивает не только общий текст, но и начало/конец — против повтора сюжета, героя и развязки."""
    from difflib import SequenceMatcher
    candidate = normalize_for_similarity(f"{title} {text}")[:1200]
    if not candidate:
        return True
    candidate_body = normalize_for_similarity(text)
    candidate_start = candidate_body[:220]
    candidate_end = candidate_body[-220:]
    for old_title, _, _, old_text in get_recent_channel_posts(35):
        previous = normalize_for_similarity(f"{old_title} {old_text}")[:1200]
        if previous and SequenceMatcher(None, candidate, previous).ratio() >= threshold:
            return True
        old_body = normalize_for_similarity(old_text)
        old_start = old_body[:220]
        old_end = old_body[-220:]
        if old_start and candidate_start and SequenceMatcher(None, candidate_start, old_start).ratio() >= edge_threshold:
            return True
        if old_end and candidate_end and SequenceMatcher(None, candidate_end, old_end).ratio() >= edge_threshold:
            return True
    return False


def looks_like_full_recipe(text):
    """Грубая проверка: рецепт должен содержать количества и шаги, а не просто идею блюда."""
    value = (text or "").lower()
    has_quantity = bool(re.search(r"\d+\s*(г\b|мл|ст\.?\s*л|ч\.?\s*л|шт\b|стакан|минут|мин\b|градус|°)", value))
    has_steps = value.count("\n") >= 3 or len(re.findall(r"\d+[.)]", value)) >= 3
    return bool(has_quantity and has_steps and len(text or "") >= 400)


CHANNEL_FORBIDDEN_PHRASES = (
    "каждый ребёнок уникален", "важно помнить", "давайте разберёмся", "главное — сохранять спокойствие",
    "главное - сохранять спокойствие", "это нормально", "в современном мире", "ни для кого не секрет",
    "внешняя сторона семьи", "бешеный диссонанс", "полная безысходность", "жизнь внесла свои коррективы",
    "в такие моменты понимаешь", "и тут я понял", "мораль этой истории", "каждая мама должна",
    "хорошая мама должна", "хорошая мама обязана", "создайте атмосферу поддержки", "просто будьте рядом",
    "уделите ребёнку внимание", "следите за состоянием", "это важная тема для родителей",
    "это может быть стрессовым моментом", "непростой процесс", "серые тучи сгущались",
    "ссоры временны, а дружба навсегда", "всё обязательно получится", "главное — любовь",
    "главное - любовь", "семья — это самое важное", "семья - это самое важное", "каждый момент бесценен",
    "детство проходит быстро",
)

CHANNEL_BAD_OPENING_PHRASES = (
    "сегодня я хочу поговорить", "в современном мире родители", "каждый ребёнок уникален",
    "ни для кого не секрет", "давайте разберёмся", "важно помнить", "главное — сохранять спокойствие",
    "главное - сохранять спокойствие", "это может быть стрессовым моментом",
    "гаджеты — важная тема для родителей", "гаджеты - важная тема для родителей",
    "воспитание детей — непростой процесс", "воспитание детей - непростой процесс",
)


def channel_post_quality_issues(text, category):
    """Автоматическая проверка перед публикацией: запрещённые шаблоны, обрыв текста, отсутствие конкретики."""
    value = (text or "").strip()
    if not value:
        return ["пустой текст"]
    low = value.lower()
    issues = []
    for phrase in CHANNEL_FORBIDDEN_PHRASES:
        if phrase in low:
            issues.append(f"запрещённая шаблонная фраза: «{phrase}»")
    opening = low[:180]
    for phrase in CHANNEL_BAD_OPENING_PHRASES:
        if phrase in opening:
            issues.append(f"шаблонное вступление: «{phrase}»")
    if value[-1] not in ".!?…»\")":
        issues.append("текст обрывается без завершающего знака препинания")
    dialogue_pattern = re.search(
        r"(?:«[^»]{3,90}»|\"[^\"]{3,90}\")\s*[—\-,]?\s*(?:сказал\w*|спросил\w*|заявил\w*|воскликнул\w*|"
        r"ответил\w*|прошептал\w*|произнес\w*|произнёс\w*|эта фраза\s+(?:сегодня|вчера|на днях)?\s*"
        r"(?:звучал\w*|прозвучал\w*))",
        value, re.I,
    )
    if dialogue_pattern:
        issues.append("похоже на выдуманный диалог или цитату, поданную как реальное событие")
    if category != "DAD" and len(value) > 250:
        has_digits = bool(re.search(r"\d", value))
        has_list = bool(re.search(r"(?:^|\n)\s*(?:[-•]|\d+[.)])\s+\S", value))
        has_quote = "«" in value or "'" in value
        if not (has_digits or has_list or has_quote):
            issues.append("нет конкретики: ни цифр, ни списка, ни готовой фразы для разговора")
    return issues


def is_ai_error_text(text):
    value = (text or "").lower()
    return value.startswith("ошибка gpt:") or "invalid_api_key" in value or "incorrect api key" in value or "error code: 401" in value


def trim_channel_post_body(text, max_chars):
    """Обрезает пост только по завершённому предложению или абзацу, не посередине слова."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    candidate = text[:max_chars].rstrip()
    min_cut = int(max_chars * 0.68)

    sentence_positions = [
        candidate.rfind(". "),
        candidate.rfind("! "),
        candidate.rfind("? "),
        candidate.rfind("… "),
        candidate.rfind(".\n"),
        candidate.rfind("!\n"),
        candidate.rfind("?\n"),
    ]
    cut = max(sentence_positions)

    if cut >= min_cut:
        return candidate[:cut + 1].strip()

    paragraph_cut = candidate.rfind("\n\n")
    if paragraph_cut >= min_cut:
        return candidate[:paragraph_cut].strip()

    word_cut = candidate.rfind(" ")
    if word_cut >= min_cut:
        return candidate[:word_cut].rstrip(" ,;:-") + "…"

    return candidate.rstrip(" ,;:-") + "…"


CHANNEL_ADAPTATION_SYSTEM_PROMPT = (
    "Ты редактор канала «Мамин помощник». Тебе дают готовый, уже проверенный пост. "
    "Разрешено ТОЛЬКО: слегка изменить вступление, поменять местами два-три абзаца (если "
    "смысл не меняется), адаптировать обращение к читателю, немного сократить или "
    "расширить текст, изменить финальный вопрос. Категорически запрещено: придумывать "
    "новые факты, менять любые цифры и количества, менять рецепт, менять шаги "
    "приготовления, менять медицинский смысл, добавлять личные истории или прямую речь, "
    "добавлять статистику и исследования, менять итоговый смысл текста. Верни только "
    "финальный текст поста без пояснений и без заголовка."
)


def _channel_number_tokens(text):
    return sorted(re.findall(r"\d+[.,]?\d*", text or ""))


async def try_channel_ai_adaptation(category, item):
    """Необязательная лёгкая AI-адаптация готового поста (раздел 7 задачи). Отключена по
    умолчанию через CHANNEL_AI_ADAPTATION_ENABLED и не вызывается для рецептов и
    медицинских материалов (см. channel_post_from_library). Адаптация принимается только
    если цифры и объём текста не изменились и текст проходит тот же quality gate, что и
    обычная библиотека — иначе используется исходный проверенный текст без изменений."""
    original = item["body"]
    prompt = (
        f"Готовый пост рубрики «{item.get('format_name', '')}», тема: {item.get('topic', '')}.\n"
        "Исходный текст:\n" + original + "\n\n"
        "Сделай разрешённую лёгкую редакционную правку и верни только новый текст поста целиком."
    )
    try:
        raw = await ask_gpt(CHANNEL_ADAPTATION_SYSTEM_PROMPT, prompt)
    except Exception as exc:
        logging.warning("Канал TG: адаптация недоступна для %s: %s", item.get("id"), exc)
        return None
    if is_ai_error_text(raw):
        return None
    candidate = clean_text(raw or "").strip()
    if not candidate:
        return None
    if _channel_number_tokens(candidate) != _channel_number_tokens(original):
        logging.warning("Канал TG: адаптация %s изменила цифры, используется оригинал", item.get("id"))
        return None
    if not (0.5 * len(original) <= len(candidate) <= 1.8 * len(original)):
        return None
    if channel_post_quality_issues(candidate, category):
        return None
    return candidate


async def channel_post_from_library(slot, category, item):
    """Готовит библиотечный пост к публикации: опциональная лёгкая AI-адаптация (см. флаг
    CHANNEL_AI_ADAPTATION_ENABLED выше), затем защитная проверка тем же quality gate, что
    и раньше. Если вариант не проходит проверку или похож на недавние публикации — берёт
    другой готовый пост из той же рубрики вместо технического сообщения (раздел 8 задачи).
    Возвращает (title, body, item) — item может быть заменён на резервный."""
    candidate_item = item
    max_chars = CHANNEL_LIBRARY_MAX_CHARS.get(category, 2000)
    title = candidate_item.get("title") or ""
    body = candidate_item["body"]
    can_adapt = CHANNEL_AI_ADAPTATION_ENABLED and category != "REC" and not candidate_item.get("medical")
    if can_adapt:
        adapted = await try_channel_ai_adaptation(category, candidate_item)
        if adapted:
            body = adapted
    body = trim_channel_post_body(body, max_chars)
    tried_topics = {candidate_item["topic"]}
    attempts = 0
    while (channel_post_quality_issues(body, category) or is_channel_post_too_similar(title, body)) and attempts < 3:
        rnd = random.Random(f"library-fallback:{slot}:{candidate_item['id']}:{attempts}")
        next_item = select_channel_library_post(category, rnd, exclude_topics=tried_topics)
        if not next_item:
            break
        candidate_item = next_item
        tried_topics.add(candidate_item["topic"])
        title = candidate_item.get("title") or ""
        body = trim_channel_post_body(candidate_item["body"], max_chars)
        attempts += 1
    return title, body, candidate_item

CHANNEL_CTA_CATALOG = {
    "sleep": ("🌙 Общие нормы не учитывают возраст и ваш режим. Получите бесплатный персональный разбор сна.",
              "🌙 Разобрать сон ребёнка", "channel_sleep"),
    "feeding": ("🥣 Получите рекомендацию по кормлению с учётом возраста и вашей ситуации.",
                "🥣 Разобрать питание ребёнка", "channel_feeding"),
    "doctor": ("🩺 Опишите наблюдения — помощник бесплатно соберёт важное и подготовит вопросы врачу.",
               "🩺 Подготовить вопросы врачу", "channel_doctor"),
    "development": ("👶 Проверьте навык или поведение с учётом точного возраста ребёнка.",
                     "👶 Проверить развитие", "channel_child"),
    "psycho": ("🤍 Опишите, что происходит. Первый персональный разбор поможет спокойно увидеть следующий шаг.",
               "🤍 Разобрать мою ситуацию", "channel_psycho"),
    "family": ("👨‍👩‍👧 Опишите ситуацию и получите спокойный план следующего разговора.",
               "👨‍👩‍👧 Подготовить разговор", "channel_family"),
    "pregnancy": ("🤰 Получите персональную подсказку для вашего срока или этапа восстановления.",
                  "🤰 Открыть помощника", "channel_pregnancy"),
    "generic": ("✨ В «Мамином помощнике» можно получить подсказку именно для вашей ситуации и возраста ребёнка.",
                "✨ Открыть помощника на сегодня", "channel_today"),
}

# Допустимые для CTA рубрики автопостинга и, для каждой рубрики, безопасный дефолт.
# CTA выбирается ТОЛЬКО по metadata библиотечного поста (cta_allowed), без сканирования
# текста по ключевым словам (раздел 10 задачи: "запрещено выбирать CTA по случайному
# совпадению слова внутри текста"). Если у поста нет ни одного допустимого для его
# рубрики cta_allowed — CTA не показывается вовсе (см. post_human_slot).
CHANNEL_CTA_ALLOWED_BY_CATEGORY = {
    "HEALTH": (("doctor", "sleep", "feeding"), "doctor"),
    "WHATIF": (("sleep", "family", "psycho"), "psycho"),
    "AGE": (("development",), "development"),
    "MOM": (("psycho",), "psycho"),
    "FAM": (("family",), "family"),
    "SAVE": (("sleep", "feeding", "doctor", "development", "family"), "generic"),
}


def channel_cta_for_post(category, cta_allowed=()):
    """Возвращает (текст-мостик, текст кнопки, payload) строго по метаданным поста:
    первый ключ из разрешённых для рубрики, который также есть в cta_allowed поста."""
    allowed_keys, default_key = CHANNEL_CTA_ALLOWED_BY_CATEGORY.get(category, ((), "generic"))
    cta_allowed = cta_allowed or ()
    for key in allowed_keys:
        if key in cta_allowed:
            return CHANNEL_CTA_CATALOG[key]
    return CHANNEL_CTA_CATALOG[default_key]


def channel_has_allowed_cta(category, cta_allowed=()):
    allowed_keys, _ = CHANNEL_CTA_ALLOWED_BY_CATEGORY.get(category, ((), "generic"))
    cta_allowed = cta_allowed or ()
    return any(key in cta_allowed for key in allowed_keys)


def channel_deeplink(payload="channel"):
    return f"{BOT_BASE_URL}?start={payload}"


def channel_post_markup(button_text="✨ Открыть помощника на сегодня", payload="channel_today"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, url=channel_deeplink(payload))]
    ])


async def open_channel_destination_tg(message: Message, payload: str):
    user = get_user(message.from_user.id)
    if not user:
        return False
    text, markup = channel_landing_tg(payload)
    await message.answer(text, reply_markup=markup)
    return True


async def publish_channel_post(slot, theme, format_name, title, body, cta_mode="none", category="", cta_allowed=None):
    if not body or channel_slot_published_today(slot):
        return
    final_text = f"{title}\n\n{body}".strip() if title else body.strip()
    reply_markup = None
    if cta_mode == "bot":
        bridge_text, thematic_button, start_payload = channel_cta_for_post(category, cta_allowed or ())
        final_text += f"\n\n{bridge_text}"
        reply_markup = channel_post_markup(thematic_button, start_payload)
    elif cta_mode == "comments":
        final_text += "\n\nА у вас было что-то похожее? Расскажите в комментариях 🤍"
    try:
        await bot.send_message(CHANNEL_ID, final_text, reply_markup=reply_markup, disable_web_page_preview=True)
        save_channel_post(slot, theme, format_name, title, final_text)
        logging.info(f"Канал: опубликовано {slot} | {format_name} | {title} | CTA={cta_mode}")
    except Exception as e:
        logging.error(f"Канал: ошибка публикации {slot}: {e}")


CHANNEL_SLOTS = ("human_first", "human_second", "human_third")

# Недельный шаблон из 7 паттернов (утро/день/вечер), покрывающий 21 пост по 8 рубрикам:
# ~4 рецепта, ~4 воспитание и поведение, ~3 здоровье/сон/врач, ~3 сад/школа/по возрасту,
# ~2 мама тоже человек, ~2 папин взгляд, ~2 бабушки и семья, ~1 сохрани-пригодится
# (последний слот также резерв вместо личной истории, если у владельца нет свежих фактов).
# Ни один день не состоит из двух одинаковых рубрик подряд, а рубрики вечера одного дня и
# утра следующего никогда не совпадают ни при каком порядке перестановки по неделям.
# Порядок дней внутри недели тасуется по seed на ISO-неделю.
CHANNEL_DAY_PATTERNS = [
    ("REC", "WHATIF", "MOM"),
    ("REC", "HEALTH", "DAD"),
    ("REC", "AGE", "FAM"),
    ("REC", "WHATIF", "MOM"),
    ("HEALTH", "AGE", "DAD"),
    ("AGE", "FAM", "WHATIF"),
    ("HEALTH", "SAVE", "WHATIF"),
]


def _daily_channel_format_plan(day_key):
    dt = datetime.fromisoformat(day_key)
    iso_year, iso_week, iso_weekday = dt.isocalendar()
    patterns = list(CHANNEL_DAY_PATTERNS)
    random.Random(f"tg-channel-week:{iso_year}-W{iso_week}").shuffle(patterns)
    pattern = patterns[iso_weekday - 1]
    return dict(zip(CHANNEL_SLOTS, pattern))


def _channel_pick_for_slot(day_key, slot, category):
    rnd = random.Random(f"tg-human-channel:{day_key}:{slot}")
    return select_channel_library_post(category, rnd)


def _daily_channel_plan(day_key, categories_by_slot):
    """CTA-ссылка — детерминированно 3-4 раза в неделю, только в уместных рубриках."""
    dt = datetime.fromisoformat(day_key)
    iso_year, iso_week, _ = dt.isocalendar()
    slots = list(CHANNEL_SLOTS)
    week_start = dt - timedelta(days=dt.weekday())
    eligible_by_day = {}
    for offset in range(7):
        week_day = (week_start + timedelta(days=offset)).date().isoformat()
        weekly_categories = _daily_channel_format_plan(week_day)
        candidates = [
            weekly_slot for weekly_slot in slots
            if weekly_categories.get(weekly_slot) in ("HEALTH", "WHATIF", "AGE", "MOM", "FAM", "SAVE")
        ]
        if candidates:
            eligible_by_day[week_day] = candidates
    weekly_rnd = random.Random(f"tg-human-cta-week:{iso_year}-W{iso_week}")
    weekly_days = list(eligible_by_day)
    weekly_rnd.shuffle(weekly_days)
    weekly_limit = min(len(weekly_days), 3 + int(weekly_rnd.random() < 0.5))
    weekly_cta = {
        weekly_day: weekly_rnd.choice(eligible_by_day[weekly_day])
        for weekly_day in weekly_days[:weekly_limit]
    }
    cta_slot = weekly_cta.get(day_key)
    rnd = random.Random(f"tg-human-question:{day_key}")
    question_eligible = [s for s in slots if s != cta_slot and categories_by_slot.get(s) != "REC"]
    question_slot = rnd.choice(question_eligible) if question_eligible and rnd.random() < 0.4 else None
    return cta_slot, question_slot


async def post_human_slot(slot):
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if channel_slot_published_today(slot):
        return
    day_key = now.date().isoformat()
    categories_by_slot = _daily_channel_format_plan(day_key)
    category = categories_by_slot[slot]
    item = _channel_pick_for_slot(day_key, slot, category)
    if not item:
        logging.error("Канал TG: библиотека пуста для рубрики %s, публикация пропущена", category)
        return
    cta_slot, question_slot = _daily_channel_plan(day_key, categories_by_slot)
    if slot == cta_slot:
        cta_mode = "bot"
    elif slot == question_slot:
        cta_mode = "comments"
    else:
        cta_mode = "none"
    if cta_mode == "bot" and not channel_has_allowed_cta(category, item.get("cta_allowed", [])):
        tried_topics = {item["topic"]}
        for attempt in range(6):
            cta_item = select_channel_library_post(
                category,
                random.Random(f"tg-cta-library:{day_key}:{slot}:{attempt}"),
                exclude_topics=tried_topics,
            )
            if not cta_item:
                break
            tried_topics.add(cta_item["topic"])
            if channel_has_allowed_cta(category, cta_item.get("cta_allowed", [])):
                item = cta_item
                break
    title, body, used_item = await channel_post_from_library(slot, category, item)
    if cta_mode == "bot" and not channel_has_allowed_cta(category, used_item.get("cta_allowed", [])):
        cta_mode = "none"
    await publish_channel_post(slot, used_item["topic"], used_item["format_name"], title, body, cta_mode, category, used_item.get("cta_allowed", []))

async def post_human_first():
    await post_human_slot("human_first")


async def post_human_second():
    await post_human_slot("human_second")


async def post_human_third():
    await post_human_slot("human_third")


def schedule_daily_human_posts():
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    rnd = random.Random(f"tg-human-times:{today.isoformat()}")
    windows = ((8 * 60 + 30, 11 * 60 + 30), (13 * 60 + 30, 16 * 60 + 30), (18 * 60, 21 * 60 + 30))
    minutes = []
    for lo, hi in windows:
        candidates = [minute for minute in range(lo, hi + 1) if minute % 60 % 5 != 0]
        minutes.append(rnd.choice(candidates))
    job_ids = ("channel_human_first", "channel_human_second", "channel_human_third")
    targets = (post_human_first, post_human_second, post_human_third)
    for job_id in job_ids:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    for job_id, target, minute in zip(job_ids, targets, minutes):
        scheduler.add_job(target, "date", run_date=datetime.combine(today, datetime.min.time()) + timedelta(minutes=minute), id=job_id, replace_existing=True, misfire_grace_time=30)
    logging.info(
        "Канал TG: посты на сегодня запланированы на %02d:%02d, %02d:%02d и %02d:%02d",
        minutes[0] // 60, minutes[0] % 60, minutes[1] // 60, minutes[1] % 60, minutes[2] // 60, minutes[2] % 60,
    )


async def channel_weekly_editorial_report():
    """Отправляет владельцу сводку автоканала за последние 7 дней и сохраняет её в лог."""
    conn = db_connect()
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT slot, format_name, COUNT(*) FROM channel_posts WHERE created_at>=? GROUP BY slot, format_name ORDER BY slot, format_name",
        (week_ago,),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM channel_posts WHERE created_at>=?",
        (week_ago,),
    ).fetchone()[0]
    bridges = conn.execute(
        "SELECT COUNT(*) FROM channel_posts "
        "WHERE created_at>=? AND slot IN ('human_first','human_second','human_third') "
        "AND (text LIKE '%помощник%' OR text LIKE '%бот%' OR text LIKE '%разбор%')",
        (week_ago,),
    ).fetchone()[0]
    last_post = conn.execute(
        "SELECT created_at, slot, title FROM channel_posts ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    by_slot = {}
    by_format = {}
    for slot, format_name, count in rows:
        by_slot[slot] = by_slot.get(slot, 0) + count
        by_format[format_name] = by_format.get(format_name, 0) + count

    slot_labels = {
        "human_first": "Первых постов дня",
        "human_second": "Вторых постов дня",
        "human_third": "Третьих постов дня",
    }
    lines = [
        "📊 Отчёт канала за неделю",
        "",
        f"Опубликовано материалов: {total}",
    ]
    for slot in ("human_first", "human_second", "human_third"):
        lines.append(f"{slot_labels[slot]}: {by_slot.get(slot, 0)}")

    if by_format:
        lines.extend(["", "Форматы:"])
        for format_name, count in sorted(by_format.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"• {format_name} — {count}")

    lines.extend(["", f"Материалов с потенциальным переходом в бот: {bridges}"])
    if last_post:
        created_at, slot, title = last_post
        try:
            created_label = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        except Exception:
            created_label = created_at
        lines.extend(["", f"Последняя публикация: {created_label}", f"• {title} ({slot})"])

    report_text = "\n".join(lines)
    logging.info(f"Канал: недельный редакционный отчёт: {report_text}")
    try:
        await bot.send_message(CHANNEL_REPORT_CHAT_ID, report_text)
    except Exception as e:
        logging.error(f"Канал: не удалось отправить недельный отчёт получателю {CHANNEL_REPORT_CHAT_ID}: {e}")


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
    if len(get_symptoms(message.from_user.id)) >= 2:
        await maybe_send_marketing_offer(
            message.chat.id,
            message.from_user.id,
            "doctor_report_ready",
            "🩺 Уже накопилось несколько наблюдений. Их можно собрать в аккуратную сводку для педиатра, чтобы на приёме ничего не забыть.",
            [
                [InlineKeyboardButton(text="🩺 Сводка к врачу — 149 ₽", callback_data="buy_doctor_report")],
                [InlineKeyboardButton(text="💎 Все отчёты в Про", callback_data="pay_plan_pro")],
            ],
        )

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
        if len(get_feedings(message.from_user.id)) >= 4:
            await maybe_send_marketing_offer(
                message.chat.id,
                message.from_user.id,
                "feeding_report_ready",
                "🍼 Уже есть данные для первичного разбора кормлений: интервалы, частота и продолжительность.",
                [
                    [InlineKeyboardButton(text="📊 Разбор кормлений — 149 ₽", callback_data="buy_feeding_report")],
                    [InlineKeyboardButton(text="💎 Все разборы в Про", callback_data="pay_plan_pro")],
                ],
            )
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
    if len(get_sleep_log(call.from_user.id)) >= 4:
        await maybe_send_marketing_offer(
            call.message.chat.id,
            call.from_user.id,
            "sleep_report_ready",
            "🌙 Картина сна уже начинает формироваться. Разбор покажет интервалы, возможные закономерности и что стоит отслеживать дальше.",
            [
                [InlineKeyboardButton(text="🌙 Разбор сна — 199 ₽", callback_data="buy_sleep_report")],
                [InlineKeyboardButton(text="💎 Все отчёты в Про", callback_data="pay_plan_pro")],
            ],
        )

@dp.callback_query(F.data == "sleep_end")
async def sleep_end(call: CallbackQuery):
    save_sleep(call.from_user.id, "проснулся")
    await call.message.answer("🌅 Записала — малыш проснулся!", reply_markup=kb_mama_menu())
    if len(get_sleep_log(call.from_user.id)) >= 4:
        await maybe_send_marketing_offer(
            call.message.chat.id,
            call.from_user.id,
            "sleep_report_ready",
            "🌙 Картина сна уже начинает формироваться. Разбор покажет интервалы, возможные закономерности и что стоит отслеживать дальше.",
            [
                [InlineKeyboardButton(text="🌙 Разбор сна — 199 ₽", callback_data="buy_sleep_report")],
                [InlineKeyboardButton(text="💎 Все отчёты в Про", callback_data="pay_plan_pro")],
            ],
        )

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

    conn = db_connect()
    conn.execute("DELETE FROM vaccinations WHERE user_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()

    from calendar import monthrange
    def add_months(dt, count):
        month = dt.month - 1 + count
        year = dt.year + month // 12
        month = month % 12 + 1
        day = min(dt.day, monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)

    added = 0
    for month_age, vaccine in schedule:
        vac_date = add_months(birth, month_age).strftime("%d.%m.%Y")
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
    await show_typing(call.message.chat.id)
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
        "Давай актуальную информацию на текущую дату; если точная сумма может измениться, предупреди и предложи проверить на Госуслугах или СФР. "
        "Указывай конкретные суммы, сроки подачи, необходимые документы и куда обращаться. "
        "Отвечай структурированно и понятно.",
        prompt
    )
    await call.message.answer(answer, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К пособиям", callback_data="benefits_menu")]
    ]))

@dp.callback_query(F.data == "ben_birth")
async def ben_birth(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о единовременном пособии при рождении ребёнка в России на текущую дату. "
                       "Размер, кто имеет право, документы, куда подавать, сроки.")

@dp.callback_query(F.data == "ben_15")
async def ben_15(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о ежемесячном пособии по уходу за ребёнком до 1.5 лет в России на текущую дату. "
                       "Размер для работающих и неработающих мам, как рассчитывается, документы, сроки.")

@dp.callback_query(F.data == "ben_3")
async def ben_3(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о выплатах и пособиях на ребёнка от 1.5 до 3 лет в России на текущую дату. "
                       "Путинские выплаты, региональные пособия, условия получения.")

@dp.callback_query(F.data == "ben_matcap")
async def ben_matcap(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о материнском капитале в России на текущую дату. "
                       "Размер на первого и второго ребёнка, на что можно потратить, как оформить через Госуслуги, "
                       "сроки получения сертификата.")

@dp.callback_query(F.data == "ben_decree")
async def ben_decree(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о пособии по беременности и родам (декретные) в России на текущую дату. "
                       "Как рассчитывается для работающих, ИП, безработных. "
                       "Сроки декрета, документы, куда обращаться.")

@dp.callback_query(F.data == "ben_multi")
async def ben_multi(call: CallbackQuery):
    await benefits_gpt(call, "Расскажи о льготах и выплатах многодетным семьям в России на текущую дату. "
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
        "Ты эксперт по социальным выплатам в России на текущую дату. "
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
    await psycho_start(call, state)

@dp.callback_query(F.data == "psycho_start")
async def psycho_start(call: CallbackQuery, state: FSMContext):
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
    psycho_limit = psycho_limit_for(message.from_user.id)
    if psycho_limit is not None and get_usage_counter(message.from_user.id, "psycho_messages") >= psycho_limit:
        await message.answer(f"Лимит поддерживающего диалога ({psycho_limit} сообщений) исчерпан. Выбери Старт или Про.", reply_markup=kb_premium())
        return
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
        increment_usage_counter(user_id, "psycho_messages")
        used = get_usage_counter(user_id, "psycho_messages")
        plan = get_user_plan(user_id)
        threshold = 10 if plan == "free" else 40 if plan == "start" else None
        if threshold is not None and used >= threshold:
            await maybe_send_marketing_offer(
                message.chat.id,
                user_id,
                "psycho_upgrade",
                "🤍 Я сохраняю контекст нашего разговора. В Про можно продолжать без лимита и не объяснять ситуацию заново.",
                [[InlineKeyboardButton(text="💎 Про — 390 ₽ / 30 дней", callback_data="pay_plan_pro")]],
            )

    except Exception as e:
        logging.error(f"Psycho GPT error: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз 💕")

@dp.message(PsychoStates.in_session, F.voice)
async def psycho_voice(message: Message, state: FSMContext):
    """Голос тоже работает в сеансе психолога"""
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
    mark_vaccination_done(vac_id, call.from_user.id)
    await call.message.answer("✅ Прививка отмечена как сделанная!", reply_markup=kb_mama_menu())

async def check_vaccine_reminders():
    conn = db_connect()
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
    if not OWNER_ID:
        logging.warning("TG_OWNER_ID не задан: коммерческие уведомления будут отправляться в CHANNEL_REPORT_CHAT_ID")
    dp.callback_query.outer_middleware(PremiumCallbackMiddleware())
    # Напоминания о прививках — каждый день в 9:00
    scheduler.add_job(check_vaccine_reminders, "cron", hour=9, minute=0, id="vaccine_reminders", replace_existing=True, coalesce=True, max_instances=1)
    schedule_daily_human_posts()
    scheduler.add_job(schedule_daily_human_posts, "cron", hour=0, minute=7, id="channel_human_daily_planner", replace_existing=True, coalesce=True, max_instances=1)
    scheduler.add_job(channel_weekly_editorial_report, "cron", day_of_week="sun", hour=21, minute=0, id="channel_weekly_report", replace_existing=True, coalesce=True, max_instances=1)
    scheduler.start()
    logging.info("Мамин помощник запущен!")
    asyncio.create_task(check_payments_loop())
    asyncio.create_task(heartbeat_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
