import asyncio
import os
import sqlite3
import logging
import os
import uuid
import base64
import httpx
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from openai import AsyncOpenAI
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import uvicorn
import gspread
from google.oauth2.service_account import Credentials


def load_env(path="/root/.env_mama"):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
    except Exception as exc:
        logging.warning("Не удалось загрузить %s: %s", path, exc)
    return env

_ENV = load_env()

APP_VERSION = "10.4.2-max-upload-fix"
# ========== КОНФИГ ==========
MAX_TOKEN = "f9LHodD0cOIWTyPeJTIKgqKDGe8OGcGqK1BXLiPyMJqGIi1-CZR29YAPZgDbbUpDfwQXKDJovDVJ3HN_88XV"
MAX_API = "https://platform-api.max.ru"
OPENAI_KEY = _ENV.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
if not OPENAI_KEY:
    logging.warning("OPENAI_API_KEY не задан: AI-функции будут недоступны")
OWNER_ID = int(_ENV.get("MAX_OWNER_ID") or os.getenv("MAX_OWNER_ID") or "214128371")
CHANNEL_ID = -75619101439475
SUPPORT_URL = "https://t.me/demo23rus"
MAX_BOT_PUBLIC_URL = "https://max.ru/id232007136009_2_bot"
MAX_CHANNEL_PUBLIC_URL = os.getenv("MAX_CHANNEL_PUBLIC_URL", "")
MAX_BOT_DEEPLINK = MAX_BOT_PUBLIC_URL
MAX_BOT_CHANNEL_LINK = MAX_BOT_PUBLIC_URL
CHANNEL_VISUALS_ENABLED = (_ENV.get("CHANNEL_VISUALS_ENABLED") or os.getenv("CHANNEL_VISUALS_ENABLED") or "1") == "1"
OPENAI_IMAGE_MODEL = _ENV.get("OPENAI_IMAGE_MODEL") or os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1"
CHANNEL_IMAGE_SIZE = _ENV.get("CHANNEL_IMAGE_SIZE") or os.getenv("CHANNEL_IMAGE_SIZE") or "1024x1024"

PLAN_CATALOG = {
    "free": {"name": "Бесплатный", "amount": "0.00", "days": 0},
    "start": {"name": "Старт", "amount": "190.00", "days": 30},
    "pro": {"name": "Про", "amount": "390.00", "days": 30},
    "pro_year": {"name": "Про на год", "amount": "2990.00", "days": 365},
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

PLAN_LIMITS = {
    "free": {"questions": 5, "psycho_messages": 15},
    "start": {"questions": 30, "psycho_messages": 50},
    "pro": {"questions": None, "psycho_messages": None},
    "pro_year": {"questions": None, "psycho_messages": None},
}
AI_FAILURE_MESSAGE = "Сейчас помощник временно не смог подготовить ответ. Попробуй ещё раз немного позже. Если вопрос срочный и касается здоровья, обратись к врачу или звони 112."


# Лимиты

# ЮКасса
YOOKASSA_SHOP_ID = "1363324"
YOOKASSA_SECRET = "live_-RKE9nsi8wZiM-5f00z78E84OYSi3M0Dj9w_-pE0Mvw"

# ========== GOOGLE SHEETS ==========
GOOGLE_CREDS_PATH = "/root/google_credentials.json"
SPREADSHEET_ID_MAMA = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
SHEET_NAME = "МамаБот MAX"
SALES_SHEET = "Продажи МамаБот"
MAX_USER_HEADERS = [
    "Последнее посещение", "user_id", "Имя", "Username",
    "AI-запросы", "Тариф", "Дата окончания", "Отзыв"
]
SALES_HEADERS = [
    "Дата", "Платформа", "user_id", "Имя", "Username", "Продукт",
    "Тип", "Сумма", "Payment ID", "Дата окончания", "Статус"
]

def _max_sheets_book():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID_MAMA)

def _max_worksheet(book, title, headers):
    try:
        ws = book.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=title, rows=2000, cols=max(12, len(headers)))
        ws.append_row(headers)
    if ws.row_values(1) != headers:
        ws.update('A1', [headers])
    return ws

def sheets_upsert_max_user(user_id, first_name="", username="", source="", review=None, last_action=""):
    """Компактная карточка: одна строка на пользователя."""
    try:
        book = _max_sheets_book()
        ws = _max_worksheet(book, SHEET_NAME, MAX_USER_HEADERS)
        uid = str(user_id)
        ids = ws.col_values(2)
        row_num = next((i + 1 for i, value in enumerate(ids) if value == uid), None)
        conn = db_connect()
        row = conn.execute("SELECT first_name,username FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        saved_name, saved_username = row if row else ("", "")
        limits = get_limits(user_id)
        plan, sub_end = get_subscription(user_id)
        plan_name = PLAN_CATALOG.get(plan, {}).get("name", "Бесплатный") if plan else "Бесплатный"
        end_text = sub_end.strftime("%d.%m.%Y") if sub_end else ""
        values = [
            datetime.now().strftime("%d.%m.%Y %H:%M"), uid,
            first_name or saved_name or "", username or saved_username or "",
            limits["requests"], plan_name, end_text,
            review if review is not None else "",
        ]
        if row_num:
            old = ws.row_values(row_num)
            while len(old) < len(MAX_USER_HEADERS):
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
        logging.error(f"Ошибка upsert MAX Sheets: {e}")

def sheets_log_visit(user_id, first_name, username, plan=None):
    sheets_upsert_max_user(user_id, first_name, username, last_action="Вход")

def sheets_log_review(user_id, first_name, username, review_text):
    sheets_upsert_max_user(user_id, first_name, username, review=review_text, last_action="Отзыв/обратная связь")

def sheets_log_sale_max(user_id, product_code, amount, payment_id, ends_at="", status="Успешно"):
    try:
        book = _max_sheets_book()
        ws = _max_worksheet(book, SALES_SHEET, SALES_HEADERS)
        conn = db_connect()
        row = conn.execute("SELECT first_name,username FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        name, username = row if row else ("", "")
        info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS.get(product_code, {})
        product_type = "Подписка" if product_code in PLAN_CATALOG else "Разовая покупка"
        end_text = ""
        if ends_at:
            try: end_text = datetime.fromisoformat(str(ends_at)).strftime("%d.%m.%Y")
            except Exception: end_text = str(ends_at)
        ws.append_row([
            datetime.now().strftime("%d.%m.%Y %H:%M"), "MAX", str(user_id), name or "", username or "",
            info.get("name", product_code), product_type, str(amount), payment_id, end_text, status
        ])
        sheets_upsert_max_user(user_id, name or "", username or "", last_action=f"Оплата {product_code}")
    except Exception as e:
        logging.error(f"Ошибка журнала продаж MAX: {e}")

def save_growth(user_id, height, weight):
    conn = db_connect()
    conn.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?,?,?,?)",
                 (user_id, height, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_growth(user_id):
    conn = db_connect()
    rows = conn.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (user_id,)).fetchall()
    conn.close()
    return rows

def save_symptom_entry(user_id, symptom):
    conn = db_connect()
    conn.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?,?,?)",
                 (user_id, symptom, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_symptoms_list(user_id):
    conn = db_connect()
    rows = conn.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,)).fetchall()
    conn.close()
    return rows

# ========== ЛОГИ ==========
logging.basicConfig(level=logging.INFO)

# ========== КЛИЕНТЫ AI ==========
openai_client = AsyncOpenAI(api_key=OPENAI_KEY)

# ========== MAX API ==========
MAX_TEXT_LIMIT = 3900

def clean_text(text):
    text = str(text or "")
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = text.replace("`", "").replace("###", "").replace("##", "").replace("#", "")
    return text.strip()

def split_message(text, limit=MAX_TEXT_LIMIT):
    text = (text or "").strip()
    if not text:
        return [" "]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks

async def send_message(chat_id, text, buttons=None):
    if not chat_id:
        logging.error("send_message: отсутствует chat_id")
        return None
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    chunks = split_message(clean_text(text))
    result = None
    async with httpx.AsyncClient(timeout=30) as client:
        for index, chunk in enumerate(chunks):
            payload = {"text": chunk}
            if buttons and index == len(chunks) - 1:
                payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
            try:
                r = await client.post(f"{MAX_API}/messages?chat_id={chat_id}", json=payload, headers=headers)
                logging.info("send_message chat_id=%s status=%s", chat_id, r.status_code)
                if not r.is_success:
                    logging.error("MAX API error status=%s body=%s", r.status_code, r.text[:500])
                    continue
                try:
                    result = r.json()
                except ValueError:
                    result = {"raw": r.text}
            except Exception as exc:
                logging.exception("Ошибка отправки сообщения в MAX: %s", exc)
    return result

async def download_file(file_url, max_size=15 * 1024 * 1024):
    try:
        headers = {"Authorization": MAX_TOKEN}
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            r = await client.get(file_url, headers=headers)
            if not r.is_success:
                logging.error("Ошибка скачивания файла: %s %s", r.status_code, r.text[:300])
                return None, None
            content = r.content
            if len(content) < 100 or len(content) > max_size:
                logging.error("Недопустимый размер файла: %s", len(content))
                return None, None
            return content, r.headers.get("content-type", "").split(";")[0]
    except Exception as exc:
        logging.exception("Ошибка download_file: %s", exc)
        return None, None

async def get_photo(photo_url):
    content, _ = await download_file(photo_url)
    return content

def detect_image_mime(data, declared=None):
    if declared and declared.startswith("image/"):
        return declared
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"

async def refresh_max_bot_identity():
    """Использует подтверждённую публичную ссылку MAX-бота."""
    if not MAX_BOT_PUBLIC_URL:
        logging.error("Публичная ссылка MAX-бота не задана")
        return False
    logging.info("MAX ссылка для канала: %s", MAX_BOT_PUBLIC_URL)
    return True


# ========== КНОПКИ ==========
def start_buttons():
    buttons = [
        [{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"}],
        [{"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}],
    ]
    if MAX_CHANNEL_PUBLIC_URL:
        buttons.append([{"type": "link", "text": "📢 Наш канал", "url": MAX_CHANNEL_PUBLIC_URL}])
    buttons.append([
        {"type": "callback", "text": "💎 Премиум", "payload": "pay_premium"},
        {"type": "callback", "text": "🆘 Поддержка", "payload": "support_menu"},
    ])
    return buttons


def pregnant_menu_buttons():
    return [
        [{"type":"callback","text":"✨ Сегодня","payload":"today_brief"}],
        [{"type":"callback","text":"🤰 Беременность","payload":"cat_pregnancy"}, {"type":"callback","text":"❤️ Здоровье","payload":"cat_preg_health"}],
        [{"type":"callback","text":"🧠 Для мамы","payload":"cat_mom_preg"}, {"type":"callback","text":"📓 Мои данные","payload":"profile"}],
        [{"type":"callback","text":"❓ Задать вопрос","payload":"ask"}],
        [{"type":"callback","text":"💎 Премиум","payload":"pay_premium"}, {"type":"callback","text":"🆘 Поддержка","payload":"support_menu"}],
        [{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}],
        [{"type":"callback","text":"🔄 Изменить данные","payload":"change_data"}],
    ]


def main_menu_buttons():
    return [
        [{"type":"callback","text":"✨ Сегодня","payload":"today_brief"}],
        [{"type":"callback","text":"👶 Ребёнок","payload":"cat_child"}, {"type":"callback","text":"❤️ Здоровье","payload":"cat_health"}],
        [{"type":"callback","text":"📊 Трекеры","payload":"cat_trackers"}, {"type":"callback","text":"🧠 Для мамы","payload":"cat_mom"}],
        [{"type":"callback","text":"👨‍👩‍👧 Семья","payload":"cat_family"}, {"type":"callback","text":"📓 Мои данные","payload":"profile"}],
        [{"type":"callback","text":"❓ Задать вопрос","payload":"ask"}],
        [{"type":"callback","text":"💎 Премиум","payload":"pay_premium"}, {"type":"callback","text":"🆘 Поддержка","payload":"support_menu"}],
        [{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}],
        [{"type":"callback","text":"🔄 Изменить данные","payload":"change_data"}],
    ]


def child_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"📊 Развитие по возрасту","payload":"development"}],
        [{"type":"callback","text":"🎮 Игры и занятия","payload":"games"}, {"type":"callback","text":"📚 Что читать","payload":"books"}],
        [{"type":"callback","text":"🍼 Питание и прикорм","payload":"food"}, {"type":"callback","text":"🥣 Рецепты","payload":"recipes"}],
        [{"type":"callback","text":"🌙 Режим дня","payload":"routine"}, {"type":"callback","text":"😴 Проблемы со сном","payload":"sleep"}],
        [{"type":"callback","text":"😢 Истерики и капризы","payload":"tantrums"}],
        [{"type":"callback","text":"📋 Первые дни с малышом","payload":"firstdays"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"🌙 Разбор сна · Про / 199 ₽","payload":"buy_sleep_report"}],
        [{"type":"callback","text":"📈 Отчёт за неделю · Про / 199 ₽","payload":"buy_weekly_report"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def health_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🚨 Ребёнку плохо","payload":"emergency"}],
        [{"type":"callback","text":"🌡 Здоровье","payload":"health"}, {"type":"callback","text":"💊 Лекарства","payload":"meds"}],
        [{"type":"callback","text":"🦷 Зубки","payload":"teeth"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"🩺 Сводка врачу · Про / 149 ₽","payload":"doctor_prep"}],
        [{"type":"callback","text":"📸 Анализ фото · Про / 99 ₽","payload":"photo_menu"}],
        [{"type":"callback","text":"💉 Прививки · Старт","payload":"vaccines"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def tracker_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"📓 Дневник малыша","payload":"diary"}],
        [{"type":"callback","text":"🌱 ДОСТУПНО СО СТАРТ","payload":"noop"}],
        [{"type":"callback","text":"📏 Рост и вес · Старт","payload":"growth"}, {"type":"callback","text":"🌡 Симптомы · Старт","payload":"symptoms"}],
        [{"type":"callback","text":"🤱 Кормления · Старт","payload":"feeding"}, {"type":"callback","text":"🌙 Сон · Старт","payload":"sleep_log"}],
        [{"type":"callback","text":"💎 ГЛУБОКИЙ АНАЛИЗ","payload":"noop"}],
        [{"type":"callback","text":"🤱 Разбор кормлений · Про / 149 ₽","payload":"buy_feeding_report"}],
        [{"type":"callback","text":"🌙 Разбор сна · Про / 199 ₽","payload":"buy_sleep_report"}],
        [{"type":"callback","text":"📈 Отчёт за 7 дней · Про / 199 ₽","payload":"weekly_report"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def mom_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Эмоции мамы","payload":"emotions"}],
        [{"type":"callback","text":"🤱 Грудное вскармливание","payload":"breastfeeding"}],
        [{"type":"callback","text":"🏥 Восстановление мамы","payload":"recovery"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"🧠 Мамин психолог · 15 бесплатно","payload":"psycho"}],
        [{"type":"callback","text":"💰 Пособия и выплаты · Старт","payload":"benefits"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def family_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"👨‍👩‍👧 Отношения в семье","payload":"family"}],
        [{"type":"callback","text":"📓 Дневник малыша","payload":"diary"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"📈 Недельный отчёт · Про / 199 ₽","payload":"weekly_report"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def pregnancy_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"📊 Мой срок","payload":"preg_week"}],
        [{"type":"callback","text":"👶 Развитие малыша","payload":"preg_baby"}],
        [{"type":"callback","text":"✅ Чек-лист","payload":"preg_checklist"}],
        [{"type":"callback","text":"🛍 Список покупок","payload":"preg_shop"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def preg_health_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"❓ Задать вопрос","payload":"ask"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"📸 Анализы и УЗИ · Про / 99 ₽","payload":"photo_menu"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def preg_mom_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Эмоциональная поддержка","payload":"emotions"}],
        [{"type":"callback","text":"💎 РАСШИРЕННЫЕ ВОЗМОЖНОСТИ","payload":"noop"}],
        [{"type":"callback","text":"🧠 Мамин психолог · 15 бесплатно","payload":"psycho"}],
        [{"type":"callback","text":"💰 Пособия и выплаты · Старт","payload":"benefits"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def back_button():
    return [[{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]]

def upgrade_buttons(plan="any"):
    return [
        [{"type":"callback","text":"🌱 Старт — 190 ₽","payload":"pay_plan_start"}],
        [{"type":"callback","text":"💎 Про — 390 ₽","payload":"pay_plan_pro"}],
        [{"type":"callback","text":"⭐ Про на год — 2 990 ₽","payload":"pay_plan_pro_year"}],
        [{"type":"callback","text":"🩺 Сводка врачу — 149 ₽","payload":"buy_doctor_report"}],
        [{"type":"callback","text":"🌙 Разбор сна — 199 ₽","payload":"buy_sleep_report"}],
        [{"type":"callback","text":"🤱 Разбор кормлений — 149 ₽","payload":"buy_feeding_report"}],
        [{"type":"callback","text":"📈 Недельный отчёт — 199 ₽","payload":"buy_weekly_report"}],
        [{"type":"callback","text":"📸 Анализ фото — 99 ₽","payload":"buy_photo_analysis"}],
        [{"type":"callback","text":"🔙 В меню","payload":"back_menu"}],
    ]

def psycho_buttons():
    return [
        [{"type": "callback", "text": "🔄 Новый разговор", "payload": "psycho_new"},
         {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
    ]

# ========== БАЗА ДАННЫХ ==========
DB = "/root/mama_max.db"

def db_connect():
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def ensure_column(conn, table, column, definition):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    conn = db_connect()
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
        step TEXT DEFAULT 'idle', birth_date TEXT DEFAULT '', registered_at TEXT DEFAULT ''
    )""")
    # Миграции старой базы выполняются без удаления пользовательских данных.
    ensure_column(conn, "users", "username", "TEXT DEFAULT ''")
    ensure_column(conn, "users", "first_name", "TEXT DEFAULT ''")
    ensure_column(conn, "users", "step", "TEXT DEFAULT 'idle'")
    ensure_column(conn, "users", "birth_date", "TEXT DEFAULT ''")
    ensure_column(conn, "users", "registered_at", "TEXT DEFAULT ''")
    ensure_column(conn, "users", "pending_start", "TEXT DEFAULT ''")
    old_user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "name" in old_user_cols:
        conn.execute("UPDATE users SET first_name=COALESCE(NULLIF(first_name,''), name, '')")

    c.execute("""CREATE TABLE IF NOT EXISTS limits (
        user_id INTEGER PRIMARY KEY, requests INTEGER DEFAULT 0, psycho_messages INTEGER DEFAULT 0
    )""")
    ensure_column(conn, "limits", "requests", "INTEGER DEFAULT 0")
    ensure_column(conn, "limits", "psycho_messages", "INTEGER DEFAULT 0")
    c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY, plan TEXT DEFAULT '', sub_end TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS diary (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, entry TEXT,
        response TEXT DEFAULT '', created_at TEXT
    )""")
    ensure_column(conn, "diary", "response", "TEXT DEFAULT ''")
    c.execute("""CREATE TABLE IF NOT EXISTS vaccinations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, vaccine TEXT,
        scheduled_date TEXT, done INTEGER DEFAULT 0, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS growth (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, height REAL, weight REAL, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS symptoms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, symptom TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS psycho_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT, created_at TEXT
    )""")
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_user_date ON sales_events(user_id, created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_counters (user_id INTEGER NOT NULL, counter TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,counter))""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage_periods (
        user_id INTEGER PRIMARY KEY, plan TEXT NOT NULL DEFAULT 'free',
        period_started_at TEXT NOT NULL, period_ends_at TEXT DEFAULT '',
        questions_used INTEGER NOT NULL DEFAULT 0, psycho_used INTEGER NOT NULL DEFAULT 0,
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
    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT DEFAULT '',
        first_name TEXT DEFAULT '', review TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channel_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slot TEXT, theme TEXT, format_name TEXT,
        title TEXT, text TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channel_poll_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, poll_key TEXT, user_id INTEGER, option_key TEXT,
        created_at TEXT, UNIQUE(poll_key, user_id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_diary_user_created ON diary(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_growth_user_created ON growth(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symptoms_user_created ON symptoms(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vaccinations_user ON vaccinations(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_created ON channel_posts(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_channel_votes_poll ON channel_poll_votes(poll_key, option_key)")
    # Перенос старого счётчика вопросов, если таблица существовала.
    old_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "requests_count" in old_tables:
        for old_user_id, old_count in conn.execute("SELECT user_id, count FROM requests_count").fetchall():
            conn.execute("INSERT OR IGNORE INTO limits(user_id, requests) VALUES (?,?)", (old_user_id, old_count or 0))
            conn.execute("UPDATE limits SET requests=MAX(requests, ?) WHERE user_id=?", (old_count or 0, old_user_id))
    conn.commit()
    conn.close()

def get_user(user_id, username="", first_name=""):
    conn = db_connect()
    now = datetime.now().isoformat()
    conn.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, registered_at) VALUES (?,?,?,?)",
                 (user_id, username or "", first_name or "", now))
    if username or first_name:
        conn.execute("UPDATE users SET username=COALESCE(NULLIF(?,''), username), first_name=COALESCE(NULLIF(?,''), first_name) WHERE user_id=?",
                     (username or "", first_name or "", user_id))
    conn.execute("INSERT OR IGNORE INTO limits (user_id) VALUES (?)", (user_id,))
    row = conn.execute("SELECT step, birth_date FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.commit(); conn.close()
    return {"step": (row[0] or "idle") if row else "idle", "birth_date": (row[1] or "") if row else ""}

def set_step(user_id, step):
    with db_connect() as conn:
        conn.execute("UPDATE users SET step=? WHERE user_id=?", (step, user_id))

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
    row = conn.execute("SELECT plan,period_started_at,period_ends_at,questions_used,psycho_used FROM usage_periods WHERE user_id=?", (user_id,)).fetchone()
    expired = False
    if row and row[2]:
        try: expired = datetime.fromisoformat(row[2]) <= now
        except ValueError: expired = True
    if not row or row[0] != plan or (plan == "start" and expired):
        legacy_q = legacy_p = 0
        if not row and plan == "free":
            old = conn.execute("SELECT requests,psycho_messages FROM limits WHERE user_id=?", (user_id,)).fetchone()
            if old: legacy_q, legacy_p = int(old[0] or 0), int(old[1] or 0)
        period_end = (now + timedelta(days=30)).isoformat() if plan == "start" else ""
        conn.execute("INSERT OR REPLACE INTO usage_periods(user_id,plan,period_started_at,period_ends_at,questions_used,psycho_used,updated_at) VALUES (?,?,?,?,?,?,?)", (user_id,plan,now.isoformat(),period_end,legacy_q,legacy_p,now.isoformat()))
        row=(plan,now.isoformat(),period_end,legacy_q,legacy_p)
        if own: conn.commit()
    if own: conn.close()
    return row


def reset_usage_period(user_id, plan, conn=None):
    own = conn is None
    conn = conn or db_connect()
    now=datetime.now(); period_end=(now+timedelta(days=30)).isoformat() if plan=="start" else ""
    conn.execute("INSERT OR REPLACE INTO usage_periods(user_id,plan,period_started_at,period_ends_at,questions_used,psycho_used,updated_at) VALUES (?,?,?,?,0,0,?)", (user_id,plan,now.isoformat(),period_end,now.isoformat()))
    if own: conn.commit(); conn.close()


def get_limits(user_id):
    """Возвращает актуальные счётчики текущего тарифного периода."""
    row = _usage_period_row(user_id)
    return {
        "requests": int(row[3] or 0),
        "psycho": int(row[4] or 0),
    }

def get_request_count(user_id): return get_limits(user_id)["requests"]
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


def log_analytics_event(event_name,user_id=0,source="",details=""):
    try:
        with db_connect() as conn: conn.execute("INSERT INTO analytics_events(created_at,platform,user_id,event_name,source,details) VALUES (?,?,?,?,?,?)", (datetime.now().isoformat(),"max",int(user_id or 0),event_name,source or "",str(details or "")[:1000]))
    except Exception as exc: logging.error("Analytics MAX error: %s", exc)

def _referral_month_start():
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def get_referral_bonus_questions(user_id):
    with db_connect() as conn:
        row = conn.execute("SELECT bonus_questions FROM referral_bonus_questions WHERE user_id=?", (user_id,)).fetchone()
    return int(row[0] or 0) if row else 0


def register_referral(invited_user_id, referrer_user_id):
    try:
        invited_user_id = int(invited_user_id); referrer_user_id = int(referrer_user_id)
    except (TypeError, ValueError):
        return None
    if invited_user_id <= 0 or referrer_user_id <= 0 or invited_user_id == referrer_user_id:
        return None
    now = datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM referrals WHERE invited_user_id=?", (invited_user_id,)).fetchone():
            conn.rollback(); return None
        conn.execute("INSERT INTO referrals(invited_user_id,referrer_user_id,platform,started_at) VALUES (?,?,?,?)", (invited_user_id,referrer_user_id,"max",now))
        count = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_user_id=? AND start_reward_granted=1 AND started_at>=?", (referrer_user_id,_referral_month_start())).fetchone()[0]
        granted = count < 5
        if granted:
            conn.execute(
                "INSERT INTO referral_bonus_questions(user_id,bonus_questions,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET bonus_questions=bonus_questions+1,updated_at=excluded.updated_at",
                (referrer_user_id,1,now),
            )
            conn.execute("UPDATE referrals SET start_reward_granted=1 WHERE invited_user_id=?", (invited_user_id,))
        conn.commit()
    log_analytics_event("referral_started", invited_user_id, f"ref_{referrer_user_id}", "bonus=1" if granted else "monthly_cap")
    return referrer_user_id if granted else None


def reward_referrer_for_first_payment(invited_user_id, conn):
    row = conn.execute("SELECT referrer_user_id,payment_reward_granted FROM referrals WHERE invited_user_id=?", (invited_user_id,)).fetchone()
    if not row or int(row[1] or 0): return None
    referrer_id = int(row[0]); now = datetime.now(); start = now
    sub = conn.execute("SELECT plan,sub_end FROM subscriptions WHERE user_id=?", (referrer_id,)).fetchone()
    reward_plan = sub[0] if sub and sub[0] in ("pro", "pro_year") else "pro"
    if sub and sub[1]:
        try:
            old_end = datetime.fromisoformat(sub[1])
            if old_end > now: start = old_end
        except (TypeError, ValueError): pass
    end = start + timedelta(days=7)
    conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)", (referrer_id,reward_plan,end.isoformat()))
    conn.execute("UPDATE referrals SET payment_reward_granted=1,first_payment_at=? WHERE invited_user_id=?", (now.isoformat(),invited_user_id))
    return referrer_id


def referral_stats(user_id):
    with db_connect() as conn:
        row = conn.execute("SELECT COUNT(*),COALESCE(SUM(start_reward_granted),0),COALESCE(SUM(payment_reward_granted),0) FROM referrals WHERE referrer_user_id=?", (user_id,)).fetchone()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def referral_link_max(user_id):
    return f"{MAX_BOT_PUBLIC_URL}?start=ref_{int(user_id)}"


def save_pending_payment(payment_id,user_id,plan,amount=None):
    plan=_normalize_plan(plan); info=PLAN_CATALOG[plan]; now=datetime.now().isoformat(); amount=amount or info["amount"]
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)",(payment_id,user_id,plan,now))
        conn.execute("INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(payment_id,user_id,"max","subscription",plan,amount,"RUB","pending",now,now))

def get_pending_payments():
    conn=db_connect(); rows=conn.execute("SELECT payment_id,user_id,plan FROM pending_payments").fetchall(); conn.close(); return rows

def mark_payment_canceled(payment_id):
    now=datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("UPDATE payments SET status='canceled',raw_status='canceled',updated_at=? WHERE payment_id=?",(now,payment_id)); conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))

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
        conn.execute("INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)",(payment_id,now_iso,"max",user_id,plan,info["amount"],"RUB",end.isoformat()))
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))
        reward_referrer_for_first_payment(user_id, conn)
        conn.commit(); return True,end
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def delete_pending_payment(payment_id):
    with db_connect() as conn: conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))

def save_review(user_id, username, first_name, review_text):
    with db_connect() as conn: conn.execute("INSERT INTO reviews (user_id, username, first_name, review, created_at) VALUES (?,?,?,?,?)", (user_id, username or "", first_name or "", review_text, datetime.now().isoformat()))


def add_psycho_message(user_id, role, content):
    """Сохраняет сообщение поддерживающего диалога."""
    clean_role = role if role in {"user", "assistant", "system"} else "user"
    clean_content = (content or "").strip()
    if not clean_content:
        return
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
            (user_id, clean_role, clean_content, datetime.now().isoformat()),
        )

def get_psycho_history(user_id, limit=15):
    """Возвращает последние сообщения в хронологическом порядке."""
    safe_limit = max(1, min(int(limit or 15), 50))
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, safe_limit),
        ).fetchall()
    return list(reversed(rows))

def clear_psycho_history(user_id):
    """Очищает историю поддерживающего диалога пользователя."""
    with db_connect() as conn:
        conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))

def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)

PREMIUM_EXACT_CALLBACKS = {
    "psycho", "psycho_new", "photo_menu", "photo_skin", "photo_food", "photo_package",
    "photo_stool", "photo_analysis", "photo_uzi", "photo_med_preg", "growth", "growth_add",
    "growth_analyze", "symptoms", "symptom_add", "symptom_analyze", "feeding", "feed_left",
    "feed_right", "feed_bottle", "feed_stats", "sleep_log", "sleep_start", "sleep_end",
    "sleep_analyze", "vaccines", "vaccines_create", "vaccines_done", "vaccines_info",
    "benefits", "ben_birth", "ben_15", "ben_3", "ben_matcap", "ben_decree", "ben_multi", "ben_personal",
    "doctor_prep", "weekly_report"
}

def callback_requires_premium(payload):
    return payload in PREMIUM_EXACT_CALLBACKS or payload.startswith("vac_done_") or payload.startswith("vac_")




def get_user_plan(user_id):
    plan, end = get_subscription(user_id)
    return plan if end else "free"


def plan_rank(plan):
    return {"free":0,"start":1,"pro":2,"pro_year":2}.get(plan,0)


def has_plan_access(user_id, minimum="start"):
    return plan_rank(get_user_plan(user_id)) >= plan_rank(minimum)


def get_credit(user_id, product_code):
    conn=db_connect(); row=conn.execute("SELECT credits FROM user_credits WHERE user_id=? AND product_code=?",(user_id,product_code)).fetchone(); conn.close(); return int(row[0]) if row else 0


def add_credit(user_id, product_code, amount=1, conn=None):
    own=conn is None; conn=conn or db_connect(); now=datetime.now().isoformat()
    conn.execute("INSERT INTO user_credits(user_id,product_code,credits,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id,product_code) DO UPDATE SET credits=credits+excluded.credits,updated_at=excluded.updated_at",(user_id,product_code,amount,now))
    if own: conn.commit(); conn.close()


def consume_credit(user_id, product_code):
    conn=db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row=conn.execute("SELECT credits FROM user_credits WHERE user_id=? AND product_code=?",(user_id,product_code)).fetchone()
        if not row or int(row[0])<=0: conn.rollback(); return False
        conn.execute("UPDATE user_credits SET credits=credits-1,updated_at=? WHERE user_id=? AND product_code=?",(datetime.now().isoformat(),user_id,product_code)); conn.commit(); return True
    except Exception:
        conn.rollback(); raise
    finally: conn.close()


def can_use_product(user_id, product_code):
    return get_user_plan(user_id) in PRO_PLANS or get_credit(user_id,product_code)>0


def question_limit_for(user_id):
    base = PLAN_LIMITS[get_user_plan(user_id)]["questions"]
    return None if base is None else int(base) + get_referral_bonus_questions(user_id)
def psycho_limit_for(user_id): return PLAN_LIMITS[get_user_plan(user_id)]["psycho_messages"]


FUNNEL_QUESTION_PROMPTS = {
    "funnel_sleep": "🌙 Опиши, что происходит со сном ребёнка: возраст, время подъёма, дневные сны, укладывание и что тревожит больше всего.",
    "funnel_feeding": "🥣 Опиши вопрос о питании или кормлении: возраст ребёнка, тип питания и что именно вызывает сомнения.",
    "funnel_development": "👶 Напиши возраст ребёнка и навык или поведение, которое хочешь проверить по возрасту.",
    "funnel_tantrum": "🧠 Опиши последнюю истерику: возраст, что произошло перед ней и как ребёнок успокоился.",
    "funnel_doctor": "🩺 Опиши симптомы и наблюдения. Я помогу собрать важное и подготовить вопросы врачу. Диагноз бот не ставит.",
    "funnel_mom": "🤍 Расскажи, что сейчас даётся тяжелее всего. Я помогу спокойно разобрать ситуацию по шагам.",
    "funnel_family": "👨‍👩‍👧 Опиши семейную ситуацию и чего ты хочешь добиться в следующем разговоре.",
    "funnel_pregnancy": "🤰 Напиши срок беременности и вопрос, который сейчас волнует больше всего.",
}


def _question_next_action_max(question_text, pregnant=False):
    text = (question_text or "").lower()
    rules = [
        (("сон", "засып", "просып", "режим"), "🌙 Ещё вопрос о сне", "funnel_sleep"),
        (("корм", "питан", "прикорм", "смесь", "гв"), "🥣 Уточнить питание", "funnel_feeding"),
        (("истер", "каприз", "плач", "поведен"), "🧠 Понять поведение", "funnel_tantrum"),
        (("развит", "речь", "навык", "возраст"), "👶 Проверить развитие", "funnel_development"),
        (("врач", "температур", "сып", "симптом", "болит", "лекар"), "🩺 Подготовить вопросы врачу", "funnel_doctor"),
        (("муж", "пап", "отношен", "семь"), "👨‍👩‍👧 Разобрать семью", "funnel_family"),
        (("устал", "тревог", "выгор", "тяжело", "одиноко"), "🤍 Разобрать мою ситуацию", "funnel_mom"),
    ]
    for words, label, callback in rules:
        if any(w in text for w in words): return label, callback
    return ("🤰 Ещё вопрос о беременности", "funnel_pregnancy") if pregnant else ("❓ Задать ещё вопрос", "ask")



def build_question_funnel_max(user_id, question_text=""):
    plan=get_user_plan(user_id); limit=question_limit_for(user_id); used=get_request_count(user_id)
    remaining=None if limit is None else max(0,limit-used)
    user=get_user(user_id); pregnant=user.get("birth_date","").startswith("pdr:")
    next_label,next_payload=_question_next_action_max(question_text,pregnant)
    if plan=="free":
        if remaining==4:
            text="🤍 Ответ готов. Бесплатных персональных разборов осталось: 4 из 5."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}]]
        elif remaining==3:
            text="🤍 Осталось 3 бесплатных разбора. Можно продолжить со сном, питанием, развитием, здоровьем или семейной ситуацией."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}]]
        elif remaining==2:
            text="🤍 Осталось 2 бесплатных разбора. В «Старт» доступно 30 вопросов на 30 дней и основные трекеры."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}],[{"type":"callback","text":"🌱 Старт — 190 ₽","payload":"pay_plan_start"}]]
        elif remaining==1:
            text="🤍 Остался 1 бесплатный разбор. Используй его для вопроса, который тревожит сильнее всего."; buttons=[[{"type":"callback","text":"❓ Задать последний вопрос","payload":next_payload}],[{"type":"callback","text":"💎 Посмотреть возможности","payload":"pay_premium"}]]
        else:
            text="🤍 Бесплатные разборы закончились. Продолжить можно с тарифа «Старт» за 190 ₽ или получить бонус за приглашение подруги."; buttons=[[{"type":"callback","text":"🌱 Продолжить — 190 ₽","payload":"pay_plan_start"}],[{"type":"callback","text":"💎 Выбрать тариф","payload":"pay_premium"}],[{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}]]
    elif plan=="start":
        text=f"✨ Использовано {used} из 30 вопросов тарифа «Старт»."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}]]
        if remaining is not None and remaining<=6:
            text+=" В «Про» вопросы без лимита и доступны расширенные отчёты."; buttons.append([{"type":"callback","text":"💎 Перейти на Про — 390 ₽","payload":"pay_plan_pro"}])
    else:
        text="✨ Готово. Можно продолжить с ещё одним вопросом."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}]]
    if MAX_CHANNEL_PUBLIC_URL: buttons.append([{"type":"link","text":"📣 Вернуться в канал","url":MAX_CHANNEL_PUBLIC_URL}])
    return text,buttons

def get_usage_counter(user_id,counter):
    if counter == "psycho_messages": return int(_usage_period_row(user_id)[4])
    conn=db_connect(); row=conn.execute("SELECT value FROM usage_counters WHERE user_id=? AND counter=?",(user_id,counter)).fetchone(); conn.close(); return int(row[0]) if row else 0

def increment_usage_counter(user_id,counter):
    if counter == "psycho_messages":
        _usage_period_row(user_id)
        with db_connect() as conn: conn.execute("UPDATE usage_periods SET psycho_used=psycho_used+1,updated_at=? WHERE user_id=?", (datetime.now().isoformat(),user_id))
        return
    with db_connect() as conn:
        conn.execute("INSERT INTO usage_counters(user_id,counter,value,updated_at) VALUES (?,?,1,?) ON CONFLICT(user_id,counter) DO UPDATE SET value=value+1,updated_at=excluded.updated_at",(user_id,counter,datetime.now().isoformat()))


def can_show_marketing_offer(user_id, offer_type, global_hours=24, repeat_hours=72):
    if get_user_plan(user_id) in PRO_PLANS:
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
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO marketing_offers(user_id,offer_type,last_shown_at,show_count) VALUES (?,?,?,1) "
            "ON CONFLICT(user_id,offer_type) DO UPDATE SET last_shown_at=excluded.last_shown_at,show_count=show_count+1",
            (user_id, offer_type, datetime.now().isoformat()),
        )


async def maybe_send_marketing_offer(chat_id, user_id, offer_type, text, buttons):
    if not can_show_marketing_offer(user_id, offer_type):
        return False
    result = await send_message(chat_id, text, buttons)
    if result is not None:
        record_marketing_offer(user_id, offer_type)
        return True
    return False


def callback_feature(payload):
    if payload=="doctor_prep": return ("product","doctor_report")
    if payload=="weekly_report": return ("product","weekly_report")
    if payload=="sleep_analyze": return ("product","sleep_report")
    if payload=="feed_stats": return ("product","feeding_report")
    if payload in {"photo_menu","photo_skin","photo_food","photo_package","photo_stool","photo_analysis","photo_uzi","photo_med_preg"}: return ("product","photo_analysis")
    if payload in {"growth","growth_add","growth_analyze","symptoms","symptom_add","symptom_analyze","feeding","feed_left","feed_right","feed_bottle","sleep_log","sleep_start","sleep_end","vaccines","vaccines_create","vaccines_done","vaccines_info","benefits","ben_birth","ben_15","ben_3","ben_matcap","ben_decree","ben_multi","ben_personal"} or payload.startswith("vac_"):
        return ("plan","start")
    return None

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
    growth = conn.execute(
        "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 3",
        (user_id,)
    ).fetchall()
    vaccines = conn.execute(
        "SELECT vaccine, scheduled_date, done FROM vaccinations WHERE user_id=? ORDER BY scheduled_date LIMIT 20",
        (user_id,)
    ).fetchall()
    conn.close()
    return {"symptoms": symptoms, "diary": diary, "growth": growth, "vaccines": vaccines}


def build_activity_summary(data):
    diary = data["diary"]
    feeds = [(e, dt) for e, dt in diary if e.startswith("КОРМ:")]
    sleep = [(e, dt) for e, dt in diary if e.startswith("СОН:")]
    notes = [(e, dt) for e, dt in diary if not e.startswith(("КОРМ:", "СОН:", "СИМПТОМ:"))]
    return {
        "feed_count": len(feeds),
        "sleep_events": len(sleep),
        "notes_count": len(notes),
        "symptom_count": len(data["symptoms"]),
        "feeds": feeds,
        "sleep": sleep,
        "notes": notes,
    }


def format_recent_data(data, days=7):
    activity = build_activity_summary(data)
    parts = [
        f"Период: последние {days} дней.",
        f"Кормления: {activity['feed_count']} записей.",
        f"Сон: {activity['sleep_events']} событий (засыпание/пробуждение).",
        f"Симптомы: {activity['symptom_count']} записей.",
        f"Дневник: {activity['notes_count']} обычных записей.",
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
    if activity["feeds"]:
        parts.append("Последние кормления:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {entry.replace('КОРМ:', '')}"
            for entry, dt in activity["feeds"][-10:]
        ))
    if activity["sleep"]:
        parts.append("Последние события сна:\n" + "\n".join(
            f"- {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {entry.replace('СОН:', '')}"
            for entry, dt in activity["sleep"][-12:]
        ))
    return "\n\n".join(parts)


def emergency_buttons():
    return [
        [{"type": "callback", "text": "🌡 Температура", "payload": "em_fever"},
         {"type": "callback", "text": "😮‍💨 Дыхание", "payload": "em_breath"}],
        [{"type": "callback", "text": "🤮 Рвота/понос", "payload": "em_vomit"},
         {"type": "callback", "text": "😴 Сильная вялость", "payload": "em_lethargic"}],
        [{"type": "callback", "text": "🔴 Внезапная сыпь", "payload": "em_rash"},
         {"type": "callback", "text": "😭 Безутешный плач", "payload": "em_crying"}],
        [{"type": "callback", "text": "✍️ Другое — описать", "payload": "em_other"}],
        [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}],
    ]

# ========== ПРОМПТЫ ==========
PSYCHO_SYSTEM = """Ты мудрый психолог и коуч с 20-летним опытом. Помогаешь людям разобраться в себе.
Говоришь тепло, человечно, как близкий друг. Пишешь только на русском.
Никогда не начинай с Конечно, Отлично, Вот, Готово. Обращайся на ты.
Задаёшь уточняющие вопросы. Даёшь конкретные техники и советы. Помнишь всё что человек рассказывал."""

DIARY_SYSTEM = """Ты тихий хранитель дневника. Человек записывает мысли.
Никаких советов. Никакого анализа. Просто скажи одним-двумя предложениями что услышал.
Потом задай один простой тёплый вопрос. Максимум 3 предложения. Пишешь только на русском."""

# ========== AI ФУНКЦИИ ==========
_MAX_OWNER_ERROR_CACHE = {}

async def notify_owner_max(text, key="general", cooldown_minutes=30):
    now = datetime.now()
    last = _MAX_OWNER_ERROR_CACHE.get(key)
    if last and (now - last).total_seconds() < cooldown_minutes * 60:
        return
    _MAX_OWNER_ERROR_CACHE[key] = now
    try:
        await send_message(OWNER_ID, str(text)[:3800])
    except Exception as exc:
        logging.error("MAX owner notify error: %s", exc)

async def generate_text(system, prompt, model="gpt-4o-mini"):
    try:
        response = await openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens=1500
        )
        return clean_text(response.choices[0].message.content)
    except Exception as exc:
        logging.exception("Ошибка AI MAX")
        await notify_owner_max(f"⚠️ Ошибка AI MAX\n\n{type(exc).__name__}: {exc}", key=f"ai_{type(exc).__name__}")
        return AI_FAILURE_MESSAGE

def ai_answer_success(answer):
    return bool(answer and answer != AI_FAILURE_MESSAGE)


async def generate_with_history(system, history, new_message):
    messages = [{"role": "system", "content": system}]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": new_message})
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, max_tokens=1500
    )
    return clean_text(response.choices[0].message.content)




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


async def build_channel_visual_brief(slot, theme, title, body, format_name, attempt=1):
    """Отдельно превращает смысл поста в конкретную жизненную сцену, а не в дизайн-карточку."""
    subject = channel_visual_subject(theme, title, body, format_name)
    time_hint = (
        "мягкий утренний естественный свет" if slot == "morning"
        else "тёплый вечерний домашний свет"
    )
    retry_hint = (
        "Это повторная попытка: сцена должна выглядеть ещё более фотографично и жизненно, "
        "без пустого фона, графических элементов и любой типографики."
        if attempt > 1 else ""
    )
    prompt = (
        "Ты арт-директор премиального семейного медиа. По тексту поста составь один конкретный визуальный бриф "
        "для реалистичной lifestyle-фотографии. Опиши только то, что должно быть видно в кадре: кто, где, что делает, "
        "эмоция, свет, ракурс и детали среды. Никаких надписей, плакатов, карточек, рамок, логотипов, инфографики, "
        "символов, абстрактных фонов и декоративного дизайна. Не предлагай текст на изображении. "
        "Кадр должен выглядеть как дорогая редакционная фотография реальной семьи, снятая в естественный момент.\n\n"
        f"Время кадра: {time_hint}.\n"
        f"Базовый сюжет: {subject}.\n"
        f"Тема: {theme}.\nЗаголовок: {title}.\nФормат: {format_name}.\n"
        f"Содержание поста: {' '.join((body or '').split())[:1200]}\n"
        f"{retry_hint}\n"
        "Верни только краткий визуальный бриф на русском, 80–140 слов."
    )
    try:
        response = await asyncio.wait_for(
            openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты создаёшь только реалистичные фотосцены без текста и графического дизайна."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=350,
            ),
            timeout=35,
        )
        brief = clean_text(response.choices[0].message.content)
        if brief:
            return brief
    except Exception as exc:
        logging.warning("Канал: не удалось подготовить визуальный бриф: %s", exc)
    return f"{subject}; {time_hint}; естественный бытовой момент, искренние эмоции, правдоподобная домашняя среда"


def build_channel_image_prompt(slot, theme, title, body, format_name, visual_brief, attempt=1):
    retry = (
        "Previous result was rejected because it looked like a poster, template, illustration, or contained text. "
        "Make this retry unmistakably a candid real-life photograph with people and a believable environment. "
        if attempt > 1 else ""
    )
    return (
        "Create a premium vertical 4:5 editorial lifestyle photograph for a family media channel. "
        "It must look like a genuine photograph captured in a real moment, not a designed social-media card. "
        f"Scene brief: {visual_brief}. "
        f"{retry}"
        "Use photorealistic people, natural anatomy, believable skin texture, authentic facial expressions, "
        "realistic hands, subtle depth of field, natural household details, soft cinematic but credible lighting, "
        "and a refined contemporary editorial composition. Avoid glossy advertising poses. "
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
            openai_client.chat.completions.create(
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
        openai_client.images.generate(
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
    """Aura-эталон: создаёт настоящую AI-фотографию только для утреннего и вечернего поста."""
    if isinstance(dt, str):
        slot = dt if dt in {"morning", "evening"} else ""
    else:
        try:
            hour = dt.hour
            slot = "morning" if hour < 12 else "evening" if hour >= 17 else ""
        except Exception:
            slot = ""
    if not CHANNEL_VISUALS_ENABLED or slot not in {"morning", "evening"}:
        return None

    format_name = "premium_editorial_photo"
    for attempt in (1, 2):
        try:
            visual_brief = await build_channel_visual_brief(slot, rubric, title, post_text, format_name, attempt)
            prompt = build_channel_image_prompt(slot, rubric, title, post_text, format_name, visual_brief, attempt)
            image_bytes = await _generate_channel_image_once(prompt)
            accepted, reason = await validate_channel_image(image_bytes, rubric, title, post_text)
            logging.info("Канал: проверка изображения slot=%s attempt=%s accepted=%s reason=%s", slot, attempt, accepted, reason)
            if accepted:
                return image_bytes
        except asyncio.TimeoutError:
            logging.error("Канал: генерация изображения превысила 90 секунд, попытка %s", attempt)
        except Exception as exc:
            logging.error("Канал: ошибка Aura-генерации изображения, попытка %s: %s", attempt, exc)
    logging.warning("Канал: обе попытки изображения отклонены; пост будет опубликован без картинки")
    return None


async def upload_channel_image_to_max(image_bytes, filename="channel.png"):
    if not image_bytes:
        return None
    headers = {"Authorization": MAX_TOKEN}
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            init_resp = await client.post(f"{MAX_API}/uploads?type=image", headers=headers)
            if not init_resp.is_success:
                logging.error("MAX upload init error %s %s", init_resp.status_code, init_resp.text[:300])
                return None
            upload_url = init_resp.json().get("url")
            if not upload_url:
                logging.error("MAX upload init: в ответе нет url")
                return None
            upload_resp = await client.post(upload_url, files={"data": (filename, image_bytes, "image/png")})
            if not upload_resp.is_success:
                logging.error("MAX image upload error %s %s", upload_resp.status_code, upload_resp.text[:300])
                return None
            try:
                payload = upload_resp.json()
            except ValueError:
                logging.error("MAX image upload: ответ не JSON: %s", upload_resp.text[:500])
                return None

            # Рабочий формат MAX: токен изображения находится внутри объекта photos.
            token = payload.get("token") if isinstance(payload, dict) else None
            if not token and isinstance(payload, dict):
                photos = payload.get("photos")
                if isinstance(photos, dict):
                    for photo_data in photos.values():
                        if isinstance(photo_data, dict) and photo_data.get("token"):
                            token = photo_data["token"]
                            break
                elif isinstance(photos, list):
                    for photo_data in photos:
                        if isinstance(photo_data, dict) and photo_data.get("token"):
                            token = photo_data["token"]
                            break

            # Дополнительная совместимость с альтернативными ответами MAX.
            if not token and isinstance(payload, dict):
                for key in ("photo", "image", "attachment"):
                    item = payload.get(key)
                    if isinstance(item, dict) and item.get("token"):
                        token = item["token"]
                        break

            if not token:
                logging.error(
                    "MAX image upload: token не найден; keys=%s response=%s",
                    list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                    str(payload)[:800],
                )
                return None
            return {"token": token}
    except Exception as exc:
        logging.exception("MAX image upload exception: %s", exc)
        return None

async def send_private_image_max(chat_id, image_payload, text=""):
    """Отправляет изображение в личный чат MAX, не публикуя его в канале."""
    if not image_payload:
        return False
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {
        "text": clean_text(text or " "),
        "attachments": [{"type": "image", "payload": image_payload}],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{MAX_API}/messages?chat_id={chat_id}", json=payload, headers=headers)
        if response.is_success:
            return True
        logging.error("MAX private image error %s %s", response.status_code, response.text[:300])
    except Exception as exc:
        logging.exception("MAX private image exception: %s", exc)
    return False


# ========== ОПЛАТА ==========
async def create_payment(user_id, product_code):
    info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
    product_type = "subscription" if product_code in PLAN_CATALOG else "one_time"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json={
                "amount":{"value":info["amount"],"currency":"RUB"},
                "confirmation":{"type":"redirect","return_url":"https://maminpomoshnik.ru/payment/success"},
                "capture":True,
                "description":f"Мамин Помощник MAX — {info['name']} — {user_id}",
                "receipt":{"customer":{"email":"6038484@mail.ru"},"items":[{"description":f"Мамин Помощник MAX — {info['name']}","quantity":"1.00","amount":{"value":info["amount"],"currency":"RUB"},"vat_code":1,"payment_subject":"service","payment_mode":"full_payment"}]},
                "metadata":{"user_id":user_id,"product_code":product_code,"product_type":product_type}
            },
            headers={"Idempotence-Key":str(uuid.uuid4()),"Content-Type":"application/json"},
            auth=(YOOKASSA_SHOP_ID,YOOKASSA_SECRET),
        )
        if not r.is_success:
            raise RuntimeError(f"ЮКасса: {r.status_code} {r.text[:300]}")
        return r.json()


def save_commercial_payment(payment_id,user_id,product_code):
    info=PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
    product_type="subscription" if product_code in PLAN_CATALOG else "one_time"
    now=datetime.now().isoformat()
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)",(payment_id,user_id,product_code,now))
        conn.execute("INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(payment_id,user_id,"max",product_type,product_code,info["amount"],"RUB","pending",now,now))


def process_commercial_payment(payment_id,user_id,product_code):
    now=datetime.now(); now_iso=now.isoformat(); conn=db_connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM processed_payments WHERE payment_id=?",(payment_id,)).fetchone():
            conn.rollback(); return False,None,None
        if product_code in PLAN_CATALOG:
            info=PLAN_CATALOG[product_code]
            row=conn.execute("SELECT sub_end FROM subscriptions WHERE user_id=?",(user_id,)).fetchone(); start=now
            if row and row[0]:
                try:
                    old=datetime.fromisoformat(row[0]); start=old if old>now else now
                except ValueError: pass
            end=start+timedelta(days=info["days"])
            conn.execute("INSERT OR REPLACE INTO subscriptions(user_id,plan,sub_end) VALUES (?,?,?)",(user_id,product_code,end.isoformat()))
            conn.execute("INSERT INTO subscription_history(payment_id,user_id,plan,started_at,ends_at,created_at) VALUES (?,?,?,?,?,?)",(payment_id,user_id,product_code,start.isoformat(),end.isoformat(),now_iso))
            reset_usage_period(user_id, product_code, conn=conn)
            ends_at=end.isoformat(); result_end=end; product_type="subscription"
        else:
            info=ONE_TIME_PRODUCTS[product_code]
            add_credit(user_id,info["credit"],1,conn=conn)
            conn.execute("INSERT INTO purchases(payment_id,user_id,product_code,amount,created_at) VALUES (?,?,?,?,?)",(payment_id,user_id,product_code,info["amount"],now_iso))
            ends_at=""; result_end=None; product_type="one_time"
        conn.execute("INSERT INTO processed_payments(payment_id,user_id,product_code,processed_at) VALUES (?,?,?,?)",(payment_id,user_id,product_code,now_iso))
        conn.execute("UPDATE payments SET status='processed',raw_status='succeeded',updated_at=? WHERE payment_id=?",(now_iso,payment_id))
        conn.execute("INSERT INTO sales_events(payment_id,created_at,platform,user_id,product_code,amount,currency,ends_at) VALUES (?,?,?,?,?,?,?,?)",(payment_id,now_iso,"max",user_id,product_code,info["amount"],"RUB",ends_at))
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?",(payment_id,))
        reward_referrer_for_first_payment(user_id, conn)
        conn.commit(); return True,result_end,product_type
    except Exception:
        conn.rollback(); raise
    finally: conn.close()


async def check_payments_loop():
    while True:
        await asyncio.sleep(15)
        try:
            for payment_id,user_id,product_code in get_pending_payments():
                try:
                    async with httpx.AsyncClient() as client:
                        r=await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}",auth=(YOOKASSA_SHOP_ID,YOOKASSA_SECRET))
                        payment=r.json()
                    if payment.get("status")=="succeeded":
                        processed,end,product_type=process_commercial_payment(payment_id,user_id,product_code)
                        if not processed: continue
                        info=PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
                        if product_type=="subscription":
                            text=f"✅ Оплата прошла!\n\nТариф {info['name']} активирован до {end.strftime('%d.%m.%Y')}."
                            sale_end=end.isoformat()
                        else:
                            text=f"✅ Оплата прошла!\n\nПокупка «{info['name']}» начислена. Кредит спишется только после успешного результата."
                            sale_end=""
                        asyncio.create_task(asyncio.to_thread(sheets_log_sale_max,user_id,product_code,info['amount'],payment_id,sale_end,"Успешно"))
                        await send_message(user_id,text,main_menu_buttons())
                        await send_message(OWNER_ID,f"💳 Новая продажа MAX\n\nUser ID: {user_id}\nПродукт: {info['name']}\nСумма: {info['amount']} ₽\nPayment ID: {payment_id}")
                    elif payment.get("status")=="canceled":
                        mark_payment_canceled(payment_id)
                except Exception as e:
                    logging.error(f"Ошибка проверки платежа {payment_id}: {e}")
        except Exception as e:
            logging.error(f"Ошибка check_payments_loop: {e}")

# ========== УТРЕННИЕ РАССЫЛКИ ==========
# ========== МАМИН ПОМОЩНИК — ЛОГИКА ==========

EXPERT_BASE = (
    "Ты эксперт в детской педиатрии, психологии развития и нейронауке. "
    "Опирайся на рекомендации ВОЗ, AAP, труды Петрановской, Карпа, Серза, Выготского. "
    "Отвечай развёрнуто, тепло и понятно для мамы. "
    "При симптомах здоровья рекомендуй консультацию педиатра."
)

PSYCHO_SYSTEM = (
    "Ты Мамин психолог — тёплый, внимательный профессиональный психолог для мам. "
    "Помнишь всё что мама рассказывала. Отвечаешь как живой человек — с теплом, без шаблонов. "
    "Опираешься на КПТ, ACT, теорию привязанности Петрановской. Никогда не осуждаешь."
)

WELCOME_TEXT = """👋 Привет, {name}!

Я Мамин Помощник — личный AI-помощник для беременности, ребёнка и поддержки мамы.

Подскажу по возрасту, помогу вести трекеры, подготовиться к врачу и разобраться в сложной ситуации.

Расскажи, кто ты 👇"""


def calc_child_age(birth_str):
    try:
        from datetime import date
        birth = datetime.strptime(birth_str, "%d.%m.%Y").date()
        today = date.today()
        return (today.year - birth.year) * 12 + (today.month - birth.month)
    except:
        return None

def calc_pregnancy_weeks(pdr_str):
    try:
        from datetime import date
        pdr = datetime.strptime(pdr_str, "%d.%m.%Y").date()
        conception = pdr - timedelta(days=280)
        return (date.today() - conception).days // 7
    except:
        return None

def age_label(months):
    if months is None: return "неизвестного возраста"
    if months < 1: return "новорождённый"
    if months < 12: return f"{months} мес."
    years = months // 12
    m = months % 12
    return f"{years} г. {m} мес." if m else f"{years} г."

async def process_command(chat_id, user_id, text, username="", first_name=""):
    # Служебная команда доступна всем и помогает узнать реальный MAX user_id.
    if text.strip().lower() in ("/my_id", "/myid"):
        await send_message(chat_id, f"Ваш MAX user_id: {user_id}")
        return
    if text.strip().lower() in ("/test_channel_visual", "test_channel_visual"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Команда доступна только владельцу.")
            return
        await send_message(chat_id, "🖼 Генерирую тестовую AI-картинку. Канал не затрагивается.")
        image_path = await create_channel_visual(
            "evening",
            "Забота и поддержка мамы",
            "Тихий вечер, когда мама наконец не одна",
            "Мама сидит рядом со спящим малышом, папа приносит ей тёплый чай. Спокойный домашний интерьер, мягкий естественный свет, живая семейная сцена.",
        )
        image_payload = await upload_channel_image_to_max(image_path, filename="test_mama_visual.png") if image_path else None
        ok = await send_private_image_max(chat_id, image_payload, "✅ Безопасный тест AI-визуала. В канал не опубликовано.")
        if not ok:
            await send_message(chat_id, "❌ Тестовая картинка не создана или не отправлена. Канал не затронут.")
        return
    if text.strip().lower() in ("/publish_channel_intro", "publish_channel_intro"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Команда доступна только владельцу.")
            return
        intro_text = (
            "🤍 Я МАМА — пространство без чувства вины и гонки за идеальностью.\n\n"
            "Здесь каждый день выходят три коротких и полезных материала: поддержка утром, "
            "практический разбор днём и спокойный вечерний разговор.\n\n"
            "В «Мамином помощнике» можно получить персональный план, вести сон и кормления, "
            "собрать сводку к врачу и задать вопрос по возрасту ребёнка или сроку беременности.\n\n"
            "Материалы не заменяют врача. Резервный контакт поддержки указан в описании канала."
        )
        ok = await send_to_channel(intro_text, None, "✨ Открыть Маминого помощника", start_payload="channel_today")
        await send_message(chat_id, "✅ Приветственный пост опубликован. Закрепи его в канале вручную." if ok else "❌ Не удалось опубликовать приветственный пост.")
        return
    if text.strip().lower() == "/reset_me":
        tables = [
            "diary", "growth", "symptoms", "psycho_history", "vaccinations",
            "subscriptions", "limits", "user_credits", "marketing_offers",
            "pending_payments", "reviews", "users"
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
        await send_message(chat_id, "✅ Ваш профиль и тестовые данные сброшены. Отправьте /start для новой регистрации.")
        return
    get_user(user_id, username, first_name)
    name = first_name or "мама"
    user = get_user(user_id)
    step = user.get("step", "")
    birth_date = user.get("birth_date", "")

    # Определяем возраст/срок для контекста
    months = None
    weeks_preg = None
    m_label = "неизвестного возраста"
    if birth_date and not birth_date.startswith("pdr:"):
        months = calc_child_age(birth_date)
        m_label = age_label(months)
    elif birth_date.startswith("pdr:"):
        weeks_preg = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
        m_label = f"на {weeks_preg} неделе беременности" if weeks_preg else "беременная"

    # Скрытая команда владельца: публикует НОВЫЙ тестовый пост в канал.
    if text.strip().lower() in ("/test_channel_link", "test_channel_link"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Команда доступна только владельцу.")
            return
        test_buttons = [
            [{"type": "link", "text": "Открыть бота напрямую", "url": MAX_BOT_DEEPLINK}],
            [{"type": "link", "text": "Открыть через сайт", "url": MAX_BOT_CHANNEL_LINK}],
        ]
        test_text = (
            "🧪 Тест перехода в Мамин Помощник\n\n"
            "Это новый тестовый пост, опубликованный после обновления кода.\n"
            "Нажмите первую кнопку. Если она не откроется — попробуйте вторую.\n\n"
            f"Прямая ссылка: {MAX_BOT_DEEPLINK}\n"
            f"Резервная ссылка: {MAX_BOT_CHANNEL_LINK}"
        )
        ok = await send_to_channel(test_text, test_buttons)
        if ok:
            await send_message(chat_id, "✅ Новый тестовый пост опубликован в канале. Проверяй только его, старые посты не меняются.")
        else:
            await send_message(chat_id, "❌ Не удалось опубликовать тестовый пост. Проверь логи MAX API.")
        return

    if text in ("/start", "start"):
        set_step(user_id, "idle")
        plan, _ = get_subscription(user_id)
        asyncio.create_task(asyncio.to_thread(sheets_log_visit, user_id, first_name, username, plan))
        if birth_date.startswith("pdr:"):
            await send_message(chat_id, f"🤰 Ты {m_label}\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
        elif birth_date:
            await send_message(chat_id, f"Привет, {name}! 🤍\n\nЧем могу помочь?", main_menu_buttons())
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons())
        return

    # Психолог
    if step == "psycho":
        psycho_limit = psycho_limit_for(user_id)
        if psycho_limit is not None and get_usage_counter(user_id, "psycho_messages") >= psycho_limit:
            set_step(user_id, "idle")
            await send_message(chat_id, f"Лимит поддерживающего диалога ({psycho_limit} сообщений) исчерпан. Выберите Старт или Про.", upgrade_buttons())
            return
        add_psycho_message(user_id, "user", text)
        history = get_psycho_history(user_id)
        context = f"Ребёнку {m_label}." if months is not None else f"Беременная {m_label}." if weeks_preg else ""
        messages = [{"role": "system", "content": PSYCHO_SYSTEM + (f" {context}" if context else "")}]
        for role, content in history[:-1]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})
        await send_message(chat_id, "🧠 Думаю...")
        try:
            resp = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=800)
            answer = resp.choices[0].message.content.replace("**", "").strip()
            add_psycho_message(user_id, "assistant", answer)
            await send_message(chat_id, answer, psycho_buttons())
            increment_usage_counter(user_id, "psycho_messages")
            used = get_usage_counter(user_id, "psycho_messages")
            plan_now = get_user_plan(user_id)
            threshold = 10 if plan_now == "free" else 40 if plan_now == "start" else None
            if threshold is not None and used >= threshold:
                await maybe_send_marketing_offer(
                    chat_id, user_id, "psycho_upgrade",
                    "🤍 Я сохраняю контекст разговора. В Про можно продолжать без лимита и не объяснять ситуацию заново.",
                    [[{"type": "callback", "text": "💎 Про — 390 ₽ / 30 дней", "payload": "pay_plan_pro"}]],
                )
        except Exception as e:
            logging.exception("Ошибка психолога: %s", e)
            await send_message(
                chat_id,
                "Не удалось подготовить ответ. Попробуйте ещё раз — сообщение в лимит не засчитано.",
                psycho_buttons(),
            )
            await send_message(chat_id, "Что-то пошло не так 💕")
        return

    # Свободное описание экстренной ситуации
    if step == "emergency_other":
        set_step(user_id, "idle")
        await send_message(chat_id, "⏳ Проверяю тревожные признаки...")
        emergency_system = (
            "Ты помощник по медицинской навигации для родителей. Не ставь диагноз и не назначай лечение. "
            "Сначала перечисли признаки, при которых нужно немедленно звонить 112. Затем дай безопасные действия "
            "до осмотра врача и уточняющие вопросы. Не указывай дозировки лекарств без веса, возраста и назначения врача."
        )
        prompt = f"{context} Родитель описывает ситуацию: {text}"
        try:
            answer = await generate_text(emergency_system, prompt, model="gpt-4o")
            await send_message(chat_id, "🚨 Оценка срочности\n\n" + answer,
                [[{"type": "callback", "text": "🔙 К тревожной кнопке", "payload": "emergency"}],
                 [{"type": "callback", "text": "🏠 В меню", "payload": "back_menu"}]])
        except Exception as exc:
            logging.exception("Emergency AI error: %s", exc)
            await send_message(chat_id,
                "Если ребёнок плохо дышит, синеет, не реагирует, у него судороги или не бледнеющая сыпь — звони 112 немедленно.",
                back_button())
        return

    # Вопрос к GPT
    if step == "ask":
        set_step(user_id, "idle")
        plan, _ = get_subscription(user_id)
        limit = question_limit_for(user_id)
        if limit is not None and get_request_count(user_id) >= limit:
            log_analytics_event("paywall_seen", user_id, "questions_limit", f"used={get_request_count(user_id)};limit={limit}")
            await send_message(chat_id, "🤍 Бесплатные персональные разборы закончились. Продолжить можно с тарифа «Старт» или получить бонус за приглашение подруги.", [[{"type":"callback","text":"🌱 Продолжить — 190 ₽","payload":"pay_plan_start"}],[{"type":"callback","text":"💎 Выбрать тариф","payload":"pay_premium"}],[{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}]])
            return
        context = f"Ребёнку {m_label}." if months is not None else f"Беременная {m_label}." if weeks_preg else ""
        log_analytics_event("request_started", user_id, "personal_question", text[:300])
        await send_message(chat_id, "⏳ Думаю...")
        answer = await generate_text(f"{EXPERT_BASE} {context}", text)
        await send_message(chat_id, answer)
        if ai_answer_success(answer):
            if limit is not None:
                increment_request_count(user_id)
            log_analytics_event("request_completed", user_id, "personal_question", f"used={get_request_count(user_id)}")
            funnel_text, funnel_buttons = build_question_funnel_max(user_id, text)
            await send_message(chat_id, funnel_text, funnel_buttons)
        else:
            log_analytics_event("request_failed", user_id, "personal_question", "ai_answer_invalid")
            await send_message(chat_id, "Лимит не списан. Попробуй ещё раз немного позже.", back_button())
        return

    # Ввод даты рождения малыша
    if step == "enter_birthdate":
        m = calc_child_age(text)
        if m is None or m < 0 or m > 216:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
            return
        conn = db_connect()
        pending_row = conn.execute("SELECT pending_start FROM users WHERE user_id=?", (user_id,)).fetchone()
        pending_start = (pending_row[0] or "") if pending_row else ""
        conn.execute("UPDATE users SET birth_date=?, step='idle', pending_start='' WHERE user_id=?", (text, user_id))
        conn.commit()
        conn.close()
        lbl = age_label(m)
        await send_message(chat_id, f"✅ Малышу {lbl}\n\nЧем могу помочь? 💕", main_menu_buttons())
        if pending_start:
            route = {
                "channel_today": ("❓ Получить персональный ответ", "ask"),
                "channel_sleep": ("🌙 Сон и режим", "sleep_log"),
                "channel_feeding": ("🤱 Кормления и питание", "feeding"),
                "channel_doctor": ("🩺 Подготовка к врачу", "doctor_prep"),
                "channel_psycho": ("🤍 Разобрать мою ситуацию", "funnel_mom"),
                "channel_pregnancy": ("🏥 Восстановление мамы", "recovery"),
                "channel_child": ("👶 Развитие ребёнка", "development"),
                "channel_family": ("👨‍👩‍👧 Семья", "family"),
            }.get(pending_start)
            if route:
                await send_message(chat_id, route[0], [[{"type": "callback", "text": route[0], "payload": route[1]}]])
        return

    # Ввод ПДР
    if step == "enter_pdr":
        w = calc_pregnancy_weeks(text)
        if w is None or w < 0 or w > 42:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
            return
        conn = db_connect()
        pending_row = conn.execute("SELECT pending_start FROM users WHERE user_id=?", (user_id,)).fetchone()
        pending_start = (pending_row[0] or "") if pending_row else ""
        conn.execute("UPDATE users SET birth_date=?, step='idle', pending_start='' WHERE user_id=?", (f"pdr:{text}", user_id))
        conn.commit()
        conn.close()
        await send_message(chat_id, f"✅ Ты на {w} неделе беременности\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
        if pending_start:
            route = {
                "channel_today": ("❓ Получить персональный ответ", "ask"),
                "channel_sleep": ("🌙 Разобрать сон ребёнка", "funnel_sleep"),
                "channel_feeding": ("🥣 Разобрать питание ребёнка", "funnel_feeding"),
                "channel_doctor": ("🩺 Подготовить вопросы врачу", "funnel_doctor"),
                "channel_psycho": ("🤍 Разобрать мою ситуацию", "funnel_mom"),
                "channel_pregnancy": ("🤰 Задать вопрос по беременности", "funnel_pregnancy"),
                "channel_child": ("👶 Проверить развитие", "funnel_development"),
                "channel_family": ("👨‍👩‍👧 Подготовить разговор", "funnel_family"),
            }.get(pending_start)
            if route:
                await send_message(chat_id, route[0], [[{"type": "callback", "text": route[0], "payload": route[1]}]])
        return

    # Ввод роста
    if step == "enter_height":
        try:
            h = float(text.replace(",", "."))
            conn = db_connect()
            conn.execute("UPDATE users SET step=? WHERE user_id=?", (f"enter_weight_{h}", user_id))
            conn.commit()
            conn.close()
            await send_message(chat_id, "⚖️ Введи вес в килограммах\nНапример: 7.2")
        except:
            await send_message(chat_id, "❌ Введи число, например: 67.5")
        return

    if step.startswith("enter_weight_"):
        try:
            w = float(text.replace(",", "."))
            h = float(step.replace("enter_weight_", ""))
            save_growth(user_id, h, w)
            set_step(user_id, "idle")
            await send_message(chat_id, "⏳ Анализирую...")
            answer = await generate_text(EXPERT_BASE,
                f"Ребёнку {m_label}. Рост {h} см, вес {w} кг. Оцени по нормам ВОЗ — перцентиль, норма или нет.")
            await send_message(chat_id, f"📏 Рост и вес\n\n{answer}", back_button())
        except:
            await send_message(chat_id, "❌ Введи число, например: 7.2")
        return

    if step == "enter_symptom":
        save_symptom_entry(user_id, text)
        set_step(user_id, "idle")
        await send_message(chat_id, "✅ Симптом записан!", back_button())
        if len(get_symptoms_list(user_id)) >= 2:
            await maybe_send_marketing_offer(
                chat_id, user_id, "doctor_report_ready",
                "🩺 Уже накопилось несколько наблюдений. Их можно собрать в аккуратную сводку для педиатра.",
                [[{"type": "callback", "text": "🩺 Сводка к врачу — 149 ₽", "payload": "buy_doctor_report"}],
                 [{"type": "callback", "text": "💎 Все отчёты в Про", "payload": "pay_plan_pro"}]],
            )
        return

    if step == "diary_add":
        conn = db_connect()
        conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                     (user_id, text, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        set_step(user_id, "idle")
        await send_message(chat_id, "✅ Запись сохранена в дневник! 💕", main_menu_buttons())
        return

    if step.startswith("feed_duration_"):
        try:
            dur = int(text.strip())
            feed_type = step.replace("feed_duration_", "")
            names = {"feed_left": "Левая грудь", "feed_right": "Правая грудь", "feed_bottle": "Смесь/бутылочка"}
            side = names.get(feed_type, feed_type)
            conn = db_connect()
            conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                         (user_id, f"КОРМ:{side} {dur} мин", datetime.now().isoformat()))
            conn.commit()
            conn.close()
            set_step(user_id, "idle")
            await send_message(chat_id, f"✅ Кормление записано! {side}, {dur} мин 🤱", main_menu_buttons())
            activity = build_activity_summary(get_recent_family_data(user_id, days=7))
            if activity["feed_count"] >= 4:
                await maybe_send_marketing_offer(
                    chat_id, user_id, "feeding_report_ready",
                    "🍼 Уже есть данные для первичного разбора кормлений: интервалы, частота и продолжительность.",
                    [[{"type": "callback", "text": "📊 Разбор кормлений — 149 ₽", "payload": "buy_feeding_report"}],
                     [{"type": "callback", "text": "💎 Все разборы в Про", "payload": "pay_plan_pro"}]],
                )
        except:
            await send_message(chat_id, "❌ Введи число минут, например: 15")
        return

    if step == "review":
        set_step(user_id, "idle")
        save_review(user_id, username, first_name, text)
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, text))
        await send_message(chat_id, "⭐ Спасибо за отзыв! 💕", main_menu_buttons())
        return

    if step == "suggestion":
        set_step(user_id, "idle")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, f"ПРЕДЛОЖЕНИЕ: {text}"))
        await send_message(chat_id, "💡 Спасибо за идею! Мы обязательно рассмотрим её 🤍", main_menu_buttons())
        return

    if step == "support_write":
        current_step = step
        set_step(user_id, "idle")
        plan, sub_end = get_subscription(user_id)
        plan_name = PLAN_CATALOG.get(plan, {}).get("name", "Бесплатный") if plan else "Бесплатный"
        end_text = sub_end.strftime("%d.%m.%Y") if sub_end else "—"
        try:
            await send_message(OWNER_ID,
                f"🆘 Поддержка Мамин Помощник MAX\n\nПлатформа: MAX\n"
                f"Пользователь: {first_name or 'без имени'}\nID: {user_id}\nUsername: {username or 'нет'}\n"
                f"Тариф: {plan_name}\nОкончание: {end_text}\nТекущий шаг: {current_step}\n\nСообщение:\n{text}")
        except Exception as exc:
            logging.error("Не удалось переслать обращение владельцу: %s", exc)
        save_review(user_id, username, first_name, f"ПОДДЕРЖКА: {text}")
        asyncio.create_task(asyncio.to_thread(sheets_upsert_max_user, user_id, first_name, username, "", None, "Обращение в поддержку"))
        await send_message(chat_id, f"✅ Обращение принято. Мы ответим при первой возможности.\n\nРезервный контакт: {SUPPORT_URL}", main_menu_buttons())
        return

    # Если режим не выбран
    if not birth_date:
        await send_message(chat_id, WELCOME_TEXT.format(name=name),
            start_buttons())
        return

    menu = pregnant_menu_buttons() if birth_date.startswith("pdr:") else main_menu_buttons()
    await send_message(chat_id, "Выбери действие из меню 👇", menu)


async def process_callback(chat_id, user_id, payload, first_name=""):
    get_user(user_id, "", first_name)
    name = first_name or "мама"
    user = get_user(user_id)
    birth_date = user.get("birth_date", "")
    plan, sub_end = get_subscription(user_id)

    # Возраст/срок для контекста
    months = None
    weeks_preg = None
    m_label = "неизвестного возраста"
    if birth_date and not birth_date.startswith("pdr:"):
        months = calc_child_age(birth_date)
        m_label = age_label(months)
    elif birth_date.startswith("pdr:"):
        weeks_preg = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
        m_label = f"на {weeks_preg} неделе беременности" if weeks_preg else "беременная"

    context = f"Ребёнку {m_label}." if months is not None else f"Беременная {m_label}." if weeks_preg else ""

    rule = callback_feature(payload)
    if rule:
        kind, value = rule
        allowed = has_plan_access(user_id, value) if kind == "plan" else can_use_product(user_id, value)
        if not allowed:
            await send_message(chat_id, "🔒 Эта функция не входит в текущий доступ. Выберите подписку или разовую покупку.", upgrade_buttons())
            return

    if payload in FUNNEL_QUESTION_PROMPTS:
        set_step(user_id, "ask")
        log_analytics_event("funnel_question_opened", user_id, payload)
        await send_message(chat_id, FUNNEL_QUESTION_PROMPTS[payload])
        return

    if payload == "channel_open_bot":
        await send_message(user_id,
            "🤍 Ты пришла из канала «Я МАМА». Здесь можно получить персональный план, вести трекеры и задать вопрос с учётом возраста ребёнка.",
            pregnant_menu_buttons() if birth_date.startswith("pdr:") else main_menu_buttons() if birth_date else start_buttons())
        return

    if payload.startswith("channel_poll_"):
        parts = payload.split("_", 3)
        if len(parts) == 4:
            _, _, poll_key, option_key = parts
            conn = db_connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO channel_poll_votes (poll_key, user_id, option_key, created_at) VALUES (?,?,?,?)",
                    (poll_key, user_id, option_key, datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
            await send_message(user_id, "Спасибо за ответ 🤍 Он поможет делать канал полезнее именно для мам.")
        return

    if payload == "noop":
        return

    if payload == "back_menu":
        set_step(user_id, "idle")
        if birth_date and birth_date.startswith("pdr:"):
            weeks_cur = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
            await send_message(chat_id, f"🤰 Ты на {weeks_cur} неделе беременности\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
        elif birth_date:
            await send_message(chat_id, f"Чем могу помочь? 💕", main_menu_buttons())
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons())
        return

    if payload == "main_menu":
        set_step(user_id, "idle")
        if birth_date.startswith("pdr:"):
            await send_message(chat_id, f"🤰 Ты {m_label}\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
        elif birth_date:
            await send_message(chat_id, f"Чем могу помочь? 💕", main_menu_buttons())
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons())
        return

    if payload == "cat_child":
        await send_message(
            chat_id,
            "👶 Ребёнок\n\nРазвитие, питание, сон и занятия по возрасту.",
            child_category_buttons(),
        )
        return

    if payload == "cat_health":
        await send_message(
            chat_id,
            "❤️ Здоровье\n\nБезопасная навигация, подготовка к врачу и медицинские наблюдения.",
            health_category_buttons(),
        )
        return

    if payload == "cat_trackers":
        await send_message(
            chat_id,
            "📊 Трекеры\n\nСохраняйте данные — со временем они превращаются в полезную динамику.",
            tracker_category_buttons(),
        )
        return

    if payload == "cat_mom":
        await send_message(
            chat_id,
            "🧠 Для мамы\n\nПоддержка, восстановление и забота о вашем состоянии.",
            mom_category_buttons(),
        )
        return

    if payload == "cat_family":
        await send_message(
            chat_id,
            "👨‍👩‍👧 Семья\n\nОтношения, общая история и недельные итоги.",
            family_category_buttons(),
        )
        return

    if payload == "cat_pregnancy":
        await send_message(
            chat_id,
            "🤰 Беременность\n\nСрок, развитие малыша и подготовка к родам.",
            pregnancy_category_buttons(),
        )
        return

    if payload == "cat_preg_health":
        await send_message(
            chat_id,
            "❤️ Здоровье при беременности\n\nАнализы, УЗИ и персональные вопросы.",
            preg_health_category_buttons(),
        )
        return

    if payload == "cat_mom_preg":
        await send_message(
            chat_id,
            "🧠 Для мамы\n\nЭмоциональная и практическая поддержка во время беременности.",
            preg_mom_category_buttons(),
        )
        return

    if payload == "invite_friend":
        invited, start_rewards, payment_rewards = referral_stats(user_id)
        available_bonus = get_referral_bonus_questions(user_id)
        link = referral_link_max(user_id)
        text = (
            "🎁 Пригласить подругу\n\n"
            "Отправь ей личную ссылку:\n"
            f"{link}\n\n"
            "За первый запуск — 1 дополнительный AI-вопрос. За первую оплату — 7 дней тарифа Про.\n\n"
            "Не более 5 бонусов за запуск в месяц. Самоприглашения и повторные регистрации не учитываются.\n\n"
            f"Приглашено: {invited}\n"
            f"Бонусов начислено: {start_rewards}\n"
        f"Доступно AI-вопросов: {available_bonus}\n"
            f"Наград Про: {payment_rewards}"
        )
        await send_message(chat_id, text, [
            [{"type":"link","text":"📤 Открыть ссылку","url":link}],
            [{"type":"callback","text":"🔙 В меню","payload":"back_menu"}],
        ])
        return

    if payload == "profile":
        current_plan = get_user_plan(user_id)
        plan_name = PLAN_CATALOG.get(current_plan, {}).get("name", "Бесплатный")
        _, active_end = get_subscription(user_id)
        limits = get_limits(user_id)
        if birth_date.startswith("pdr:"):
            profile_line = f"Статус: беременность, {m_label}"
        elif birth_date:
            profile_line = f"Ребёнку: {m_label}"
        else:
            profile_line = "Профиль ещё не заполнен"
        end_line = active_end.strftime("%d.%m.%Y") if active_end else "—"
        await send_message(
            chat_id,
            "📓 Мои данные\n\n"
            f"Имя: {name}\n"
            f"{profile_line}\n"
            f"Тариф: {plan_name}\n"
            f"Действует до: {end_line}\n"
            f"AI-вопросов использовано: {limits['requests']}\n"
            f"Сообщений психологу: {limits['psycho']}",
            back_button(),
        )
        return

    if payload == "change_data":
        # Reset birth_date so user can choose again
        conn = db_connect()
        conn.execute("UPDATE users SET birth_date='', step='idle' WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await send_message(chat_id, "Выбери свой статус 👇",
            start_buttons())
        return

    if payload == "set_mama":
        set_step(user_id, "enter_birthdate")
        await send_message(chat_id, "👶 Введи дату рождения малыша\n\nФормат: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
        return

    if payload == "set_pregnant":
        set_step(user_id, "enter_pdr")
        await send_message(chat_id, "🤰 Введи предполагаемую дату родов (ПДР)\n\nФормат: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
        return

    # ─── ПЕРСОНАЛЬНЫЕ И КОММЕРЧЕСКИЕ ФУНКЦИИ ───────────────
    if payload == "today_brief":
        if not birth_date:
            await send_message(chat_id, "Сначала укажи статус и дату.", back_button())
            return
        await send_message(chat_id, "✨ Собираю персональный план на сегодня...")
        if birth_date.startswith("pdr:"):
            prompt = (
                f"Беременная {m_label}. Составь короткий персональный план на сегодня: "
                "1) что происходит с малышом; 2) один пункт заботы о маме; "
                "3) одно полезное действие или подготовка; 4) один красный флаг, при котором связаться с врачом. "
                "Не ставь диагноз, не запугивай, максимум 350 слов."
            )
            title = "✨ Сегодня для тебя"
        else:
            data = get_recent_family_data(user_id, days=2)
            activity = build_activity_summary(data)
            prompt = (
                f"Ребёнку {m_label}. За последние 2 дня в трекерах: кормлений {activity['feed_count']}, "
                f"событий сна {activity['sleep_events']}, симптомов {activity['symptom_count']}. "
                "Составь короткий план на сегодня: возрастной фокус развития, одна игра, один совет по режиму, "
                "один пункт заботы о маме. Если данных мало, не делай выводов о здоровье. Максимум 350 слов."
            )
            title = "✨ Сегодня для вас"
        answer = await generate_text(EXPERT_BASE, prompt)
        await send_message(chat_id, f"{title}\n\n{answer}", back_button())
        return

    if payload == "emergency":
        if birth_date.startswith("pdr:"):
            await send_message(chat_id,
                "Эта тревожная кнопка предназначена для ребёнка после рождения. При тревожных симптомах во время беременности свяжись со своим врачом или звони 112.",
                back_button())
            return
        await send_message(chat_id,
            "🚨 Ребёнку плохо\n\nВыбери главное проявление. Этот раздел помогает оценить срочность, но не заменяет врача. "
            "Если ребёнок не дышит, синеет, не реагирует или у него судороги — звони 112 сразу.",
            emergency_buttons())
        return

    emergency_guides = {
        "em_fever": (
            "🌡 Температура",
            "Звони 112 при судорогах, нарушении дыхания, синюшности, потере сознания или не бледнеющей сыпи. "
            "Для ребёнка младше 3 месяцев температура 38°C и выше требует срочной медицинской оценки. "
            "Не укутывай, не растирай спиртом или уксусом. Предлагай питьё или грудь чаще. "
            "Жаропонижающее давай только подходящее по возрасту и весу по инструкции врача; не чередуй препараты без назначения."
        ),
        "em_breath": (
            "😮‍💨 Проблемы с дыханием",
            "Звони 112 немедленно, если синеют губы, ребёнок не может плакать/говорить из-за одышки, есть паузы дыхания, "
            "выраженное втяжение межрёберий, спутанность или потеря сознания. Посади или держи ребёнка вертикально, "
            "освободи тесную одежду, не давай еду и не пытайся осматривать горло предметами."
        ),
        "em_vomit": (
            "🤮 Рвота или понос",
            "Звони 112 при крови в рвоте или стуле, сильной сонливости, судорогах, резкой боли, зелёной рвоте или нарушении сознания. "
            "Срочно к врачу при отсутствии мочи, сухих губах, отсутствии слёз и запавших глазах. Отпаивай часто маленькими порциями; "
            "не давай противорвотные и противодиарейные средства без врача."
        ),
        "em_lethargic": (
            "😴 Сильная вялость",
            "Если ребёнка трудно разбудить, он не узнаёт близких, не удерживает взгляд, необычно обмяк или вялость сопровождается нарушением дыхания — звони 112. "
            "Проверь дыхание, цвет кожи и температуру. Не заставляй есть и не оставляй одного."
        ),
        "em_rash": (
            "🔴 Внезапная сыпь",
            "Надави прозрачным стаканом на элемент сыпи. Если пятна не бледнеют, особенно вместе с температурой или вялостью, — звони 112. "
            "Также срочно вызывай помощь при отёке губ/языка, осиплости и затруднении дыхания. Не наноси новые кремы до оценки врача и сделай фото при хорошем свете."
        ),
        "em_crying": (
            "😭 Безутешный плач",
            "Звони 112 при нарушении дыхания, посинении, судорогах, травме, резкой вялости или пронзительном необычном крике с рвотой. "
            "Проверь температуру, подгузник, голод, одежду, пальцы рук и ног на пережимающий волос. Никогда не встряхивай ребёнка. "
            "Если чувствуешь, что теряешь контроль, положи малыша в безопасную кроватку и позови взрослого на помощь."
        ),
    }
    if payload in emergency_guides:
        title, guide = emergency_guides[payload]
        await send_message(chat_id, f"🚨 {title}\n\n{guide}\n\nЕсли сомневаешься в срочности — лучше позвонить 112 или в неотложную помощь.",
            [[{"type": "callback", "text": "🔙 К симптомам", "payload": "emergency"}],
             [{"type": "callback", "text": "🏠 В меню", "payload": "back_menu"}]])
        return

    if payload == "em_other":
        set_step(user_id, "emergency_other")
        await send_message(chat_id,
            "✍️ Опиши ситуацию одним сообщением:\n\n• возраст ребёнка;\n• что произошло;\n• температура;\n• как дышит и реагирует;\n• когда началось.\n\nПри потере сознания, судорогах или нарушении дыхания не жди ответа — звони 112.")
        return

    if payload == "doctor_prep":
        if not birth_date or birth_date.startswith("pdr:"):
            await send_message(chat_id, "Сводка для педиатра доступна после рождения малыша и заполнения даты рождения.", back_button())
            return
        data = get_recent_family_data(user_id, days=14)
        raw_summary = format_recent_data(data, days=14)
        await send_message(chat_id, "🩺 Готовлю сводку для врача...")
        prompt = (
            f"Ребёнку {m_label}. Ниже данные трекеров. Составь аккуратную сводку для педиатра: "
            "1) причина обращения/наблюдаемые изменения; 2) хронология; 3) что уже отслеживали; "
            "4) 5 вопросов врачу; 5) какие данные желательно взять на приём. "
            "Не ставь диагноз и не придумывай отсутствующие факты.\n\n" + raw_summary
        )
        answer = await generate_text(EXPERT_BASE, prompt)
        await send_message(chat_id, "🩺 Сводка к педиатру\n\n" + answer,
            [[{"type": "callback", "text": "📈 Отчёт за 7 дней", "payload": "weekly_report"}],
             [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        if ai_answer_success(answer) and get_user_plan(user_id) not in PRO_PLANS: consume_credit(user_id, "doctor_report")
        return

    if payload == "weekly_report":
        if not birth_date or birth_date.startswith("pdr:"):
            await send_message(chat_id, "Недельный отчёт сейчас доступен для профиля малыша.", back_button())
            return
        data = get_recent_family_data(user_id, days=7)
        activity = build_activity_summary(data)
        if not any((activity["feed_count"], activity["sleep_events"], activity["symptom_count"], activity["notes_count"], data["growth"])):
            await send_message(chat_id,
                "Пока недостаточно записей для отчёта. В течение нескольких дней отмечай сон, кормления, симптомы или важные события — и бот соберёт персональную динамику.",
                back_button())
            return
        await send_message(chat_id, "📈 Анализирую последние 7 дней...")
        raw_summary = format_recent_data(data, days=7)
        prompt = (
            f"Ребёнку {m_label}. Подготовь недельный отчёт для мамы по данным ниже. "
            "Структура: краткие цифры, что было стабильным, что изменилось, что продолжать отслеживать, "
            "3 практических действия на следующую неделю. Не ставь диагноз и не делай выводов при недостатке данных.\n\n" + raw_summary
        )
        answer = await generate_text(EXPERT_BASE, prompt)
        await send_message(chat_id, "📈 Ваши 7 дней\n\n" + answer,
            [[{"type": "callback", "text": "🩺 Подготовить к врачу", "payload": "doctor_prep"}],
             [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        if ai_answer_success(answer) and get_user_plan(user_id) not in PRO_PLANS: consume_credit(user_id, "weekly_report")
        return

    # ─── БЕРЕМЕННЫЙ РАЗДЕЛ ───────────────────────────────────
    if payload == "preg_week":
        if not birth_date or not birth_date.startswith("pdr:"):
            await send_message(chat_id, "Сначала укажи дату родов!", back_button())
            return
        weeks = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE,
            f"Беременная на {weeks} неделе. Расскажи подробно что происходит с малышом и мамой "
            f"на {weeks} неделе беременности: размер и развитие плода, ощущения мамы, "
            f"что важно сделать и проверить на этом сроке по рекомендациям ACOG и ВОЗ.")
        await send_message(chat_id, f"📊 {weeks} неделя беременности\n\n{answer}", back_button())
        return

    if payload == "preg_baby":
        if not birth_date or not birth_date.startswith("pdr:"):
            await send_message(chat_id, "Сначала укажи дату родов!", back_button())
            return
        weeks = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE,
            f"Беременная на {weeks} неделе. Расскажи подробно о развитии малыша: "
            f"размер, вес, какие органы и системы формируются, что он умеет делать, "
            f"когда начинает двигаться и слышать. Интересные факты о развитии плода на этом сроке.")
        await send_message(chat_id, f"👶 Малыш на {weeks} неделе\n\n{answer}", back_button())
        return

    if payload == "preg_checklist":
        await send_message(chat_id, "⏳ Подбираю информацию...")
        weeks = calc_pregnancy_weeks(birth_date.replace("pdr:", "")) if birth_date and birth_date.startswith("pdr:") else 0
        answer = await generate_text(EXPERT_BASE,
            f"Составь чек-лист для беременной{'на сроке ' + str(weeks) + ' недель' if weeks else ''}: "
            f"что нужно сделать, купить, оформить, какие анализы сдать, "
            f"как подготовиться к родам. Структурированно по категориям.")
        await send_message(chat_id, f"✅ Чек-лист беременной\n\n{answer}", back_button())
        return

    if payload == "preg_shop":
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE,
            "Составь список покупок для беременной и новорождённого: "
            "что нужно для роддома (список в роддом), для малыша первые месяцы, "
            "для кормящей мамы. Что важно, что необязательно, на чём сэкономить.")
        await send_message(chat_id, f"🛍 Список покупок\n\n{answer}", back_button())
        return

    if payload == "psycho_new":
        clear_psycho_history(user_id)
        set_step(user_id, "psycho")
        await send_message(chat_id, "🧠 Новый разговор.\n\nКак ты сейчас? 💕", psycho_buttons())
        return

    if payload == "support_menu":
        buttons = [
            [{"type": "callback", "text": "🆘 Написать в поддержку", "payload": "support_write"}],
            [{"type": "callback", "text": "⭐ Оставить отзыв", "payload": "review_write"}],
            [{"type": "callback", "text": "💡 Предложить идею", "payload": "suggestion_write"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "🤍 Поддержка и обратная связь\n\nМы рады каждому отзыву и предложению!", buttons)
        return

    if payload == "support_write":
        set_step(user_id, "support_write")
        await send_message(chat_id, "🆘 Напиши своё сообщение — я перешлю его в поддержку.\n\nОпиши проблему подробно 👇")
        return

    if payload == "review_write":
        set_step(user_id, "review")
        await send_message(chat_id, "⭐ Напиши свой отзыв о боте 💕")
        return

    if payload == "suggestion_write":
        set_step(user_id, "suggestion")
        await send_message(chat_id, "💡 Напиши свою идею — что добавить или улучшить в боте?")
        return

    if payload == "review":
        set_step(user_id, "review")
        await send_message(chat_id, "⭐ Напиши свой отзыв о боте 💕", back_button())
        return

    # ─── БЕСПЛАТНЫЕ РАЗДЕЛЫ ──────────────────────────────────
    async def gpt_reply(prompt, title=""):
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, prompt)
        prefix = f"{title}\n\n" if title else ""
        await send_message(chat_id, prefix + answer, back_button())

    free_map = {
        "development": f"Развитие ребёнка {m_label} по AAP и ВОЗ: физическое, речевое, когнитивное, социальное. Нормы и тревожные признаки.",
        "health": f"Типичные проблемы здоровья у ребёнка {m_label} по AAP: температура, ОРВИ, колики. Когда к врачу.",
        "food": f"Питание ребёнка {m_label} по ВОЗ и ESPGHAN: что вводить, что нельзя, размер порций.",
        "routine": f"Режим дня для ребёнка {m_label} по хронобиологии и AAP: нормы сна, расписание, окна бодрствования.",
        "sleep": f"Сон ребёнка {m_label}: нормы, методы улучшения, безопасная среда по AAP.",
        "tantrums": f"Поведение ребёнка {m_label} по Петрановской и Сигелу: нейрофизиология, как реагировать маме.",
        "family": f"Отношения в семье когда ребёнку {m_label}: роль папы, отношения с партнёром по Готтману, ревность старших, бабушки.",
        "emotions": "Послеродовая депрессия, беби-блюз, материнское выгорание по DSM-5 и ВОЗ. Как распознать, что делать. Тепло и без осуждения.",
        "meds": f"Лекарства для ребёнка {m_label} по стандартам AAP: жаропонижающие, колики, зубы, простуда. Конкретные дозы — только у врача.",
        "teeth": f"Зубы ребёнка {m_label}: хронология по ВОЗ, симптомы прорезывания, как помочь, уход. Что НЕ работает по позиции AAP.",
    }

    if payload in free_map:
        await gpt_reply(free_map[payload])
        return

    if payload == "games":
        await send_message(chat_id, "⏳ Подбираю игры...")
        answer = await generate_text(EXPERT_BASE,
            f"Предложи 3-4 развивающие игры для ребёнка {m_label} по Выготскому. Для каждой: название, как играть, что развивает.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё игры", "payload": "games_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "games_more":
        await send_message(chat_id, "⏳ Подбираю ещё...")
        answer = await generate_text(EXPERT_BASE, f"Ещё 3-4 ДРУГИЕ игры для ребёнка {m_label}. Не повторяй предыдущие.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё игры", "payload": "games_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "books":
        await send_message(chat_id, "⏳ Подбираю книги...")
        answer = await generate_text(EXPERT_BASE, f"Порекомендуй 3 книги для ребёнка {m_label} с обоснованием. И 1 книгу для мамы от специалиста.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё книги", "payload": "books_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "books_more":
        await send_message(chat_id, "⏳ Подбираю ещё...")
        answer = await generate_text(EXPERT_BASE, f"Ещё 3 ДРУГИЕ книги для ребёнка {m_label}. Не повторяй предыдущие.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё книги", "payload": "books_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "recipes":
        await send_message(chat_id, "⏳ Подбираю рецепты...")
        answer = await generate_text(EXPERT_BASE, f"Дай 2 рецепта для ребёнка {m_label} по нормам ВОЗ. Ингредиенты и способ приготовления.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё рецепты", "payload": "recipes_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "recipes_more":
        await send_message(chat_id, "⏳ Подбираю ещё...")
        answer = await generate_text(EXPERT_BASE, f"Ещё 2 ДРУГИХ рецепта для ребёнка {m_label}. Не повторяй предыдущие.")
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "➕ Ещё рецепты", "payload": "recipes_more"},
              {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]])
        return

    if payload == "diary":
        conn = db_connect()
        entries = conn.execute(
            "SELECT entry, created_at FROM diary WHERE user_id=? AND entry NOT LIKE 'КОРМ:%' AND entry NOT LIKE 'СОН:%' AND entry NOT LIKE 'СИМПТОМ:%' ORDER BY created_at DESC LIMIT 10",
            (user_id,)).fetchall()
        conn.close()
        buttons = [
            [{"type": "callback", "text": "✏️ Добавить запись", "payload": "diary_add"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        if entries:
            text = "📓 Дневник малыша\n\n"
            for entry, dt in entries[:5]:
                d = datetime.fromisoformat(dt).strftime("%d.%m.%Y")
                text += f"📅 {d}\n{entry}\n\n"
        else:
            text = "📓 Дневник малыша\n\nЗаписей пока нет. Начни фиксировать важные моменты! 💕"
        await send_message(chat_id, text, buttons)
        return

    if payload == "diary_add":
        set_step(user_id, "diary_add")
        await send_message(chat_id, "📓 Напиши запись в дневник\n\nНапример: первый зуб, первый шаг, смешной момент 💕")
        return

    if payload == "ask":
        limit = question_limit_for(user_id)
        if limit is not None and get_request_count(user_id) >= limit:
            await send_message(chat_id, f"Использован лимит вопросов: {limit}. Выберите Старт или Про.", upgrade_buttons())
            return
        set_step(user_id, "ask")
        await send_message(chat_id, "❓ Напиши свой вопрос о малыше, беременности или воспитании 💕")
        return

    # ─── ПЕРВЫЕ ДНИ ──────────────────────────────────────────
    if payload == "firstdays":
        buttons = [
            [{"type": "callback", "text": "👨‍⚕️ Первый осмотр педиатра", "payload": "fd_pediatr"}],
            [{"type": "callback", "text": "📄 Свидетельство о рождении", "payload": "fd_svid"}],
            [{"type": "callback", "text": "🤸 Массаж и гимнастика", "payload": "fd_massage"}],
            [{"type": "callback", "text": "🏊 Плавание с малышом", "payload": "fd_swim"}],
            [{"type": "callback", "text": "🩺 Обходы врачей по месяцам", "payload": "fd_doctors"}],
            [{"type": "callback", "text": "🏫 Запись в садик", "payload": "fd_sadik"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "📋 Первые дни с малышом\n\nЧто нужно знать и сделать после рождения 👇", buttons)
        return

    fd_map = {
        "fd_pediatr": "Расскажи о первом осмотре педиатра после выписки: когда придёт по закону, как вызвать, что проверяет, какие вопросы задать.",
        "fd_svid": "Как оформить документы на новорождённого в России: свидетельство (ЗАГС/МФЦ/Госуслуги), ОМС, СНИЛС, пособия, маткапитал. Пошагово.",
        "fd_massage": "Массаж и гимнастика для младенцев: с какого возраста, виды, техника для мамы дома, массаж при коликах, противопоказания.",
        "fd_swim": "Плавание с младенцем: рефлекс плавания, польза, как организовать дома, температура воды, когда можно в бассейн.",
        "fd_doctors": "Календарь обходов врачей от рождения до 1 года: по месяцам, какие врачи, анализы, прививки по национальному календарю РФ.",
        "fd_sadik": "Как записать ребёнка в детский сад в России: когда вставать в очередь, Госуслуги, документы, льготные очереди.",
    }
    if payload in fd_map:
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, fd_map[payload])
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "🔙 К первым дням", "payload": "firstdays"},
              {"type": "callback", "text": "🏠 В меню", "payload": "back_menu"}]])
        return

    # ─── ГРУДНОЕ ВСКАРМЛИВАНИЕ ───────────────────────────────
    if payload == "breastfeeding":
        buttons = [
            [{"type": "callback", "text": "🍼 Как наладить ГВ", "payload": "bf_start"}],
            [{"type": "callback", "text": "🥛 Молока мало — расцедить", "payload": "bf_pump"}],
            [{"type": "callback", "text": "🔴 Уплотнения и лактостаз", "payload": "bf_lactostaz"}],
            [{"type": "callback", "text": "🥗 Питание мамы при ГВ", "payload": "bf_food"}],
            [{"type": "callback", "text": "❌ Что нельзя при ГВ", "payload": "bf_nofood"}],
            [{"type": "callback", "text": "🔄 Переход на смесь", "payload": "bf_formula"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "🤱 Грудное вскармливание\n\nНаучная поддержка на каждом этапе 💕", buttons)
        return

    bf_map = {
        "bf_start": "Руководство по налаживанию ГВ по ВОЗ и ЮНИСЕФ: первое прикладывание, правильный захват, позиции, признаки что молока хватает, молозиво.",
        "bf_pump": "Как увеличить лактацию: причины нехватки, ручное сцеживание пошагово, молокоотсос, питание мамы, лактогонные по науке.",
        "bf_lactostaz": "Лактостаз и уплотнения: чем отличается от мастита, первая помощь, техника массажа, расцеживание, тепло или холод по доказательной медицине, красные флаги.",
        "bf_food": "Питание кормящей мамы по ВОЗ: что включить обязательно, витамины, водный режим, развенчание мифов о диете.",
        "bf_nofood": "Что нельзя при ГВ: алкоголь, кофеин, аллергены, лекарства (LactMed). Развенчай мифы об излишних ограничениях.",
        "bf_formula": "Переход на смесь: показания, как завершить ГВ, выбор смеси, смешанное вскармливание. Без осуждения.",
    }
    if payload in bf_map:
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, bf_map[payload])
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "🔙 К ГВ", "payload": "breastfeeding"},
              {"type": "callback", "text": "🏠 В меню", "payload": "back_menu"}]])
        return

    # ─── ВОССТАНОВЛЕНИЕ ──────────────────────────────────────
    if payload == "recovery":
        buttons = [
            [{"type": "callback", "text": "🌸 После естественных родов", "payload": "rec_natural"}],
            [{"type": "callback", "text": "🏥 После кесарева сечения", "payload": "rec_caesar"}],
            [{"type": "callback", "text": "💪 Физическая активность", "payload": "rec_sport"}],
            [{"type": "callback", "text": "❤️ Интимная жизнь", "payload": "rec_intimate"}],
            [{"type": "callback", "text": "💇 Выпадение волос", "payload": "rec_hair"}],
            [{"type": "callback", "text": "🏋️ Диастаз", "payload": "rec_diastaz"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "🏥 Восстановление мамы после родов\n\nТвоё здоровье так же важно 💕", buttons)
        return

    rec_map = {
        "rec_natural": "Восстановление после естественных родов: первые 24 часа, лохии — нормы и красные флаги, швы, восстановление матки, боль, геморрой.",
        "rec_caesar": "Восстановление после кесарева: уход за швом, когда снимают, ограничения, рубец, следующая беременность.",
        "rec_sport": "Возвращение к физической активности: сроки после ест. и КС, упражнения Кегеля, диастаз — как проверить, запрещённые упражнения, план по месяцам.",
        "rec_intimate": "Интимная жизнь после родов: когда можно по ACOG, почему боль, сухость при ГВ, психологический аспект, контрацепция. Деликатно.",
        "rec_hair": "Послеродовое выпадение волос: почему (телогеновая фаза), нормальные сроки, что реально помогает, что миф, когда к трихологу.",
        "rec_diastaz": "Диастаз: что это, как проверить самостоятельно, степени, запрещённые упражнения, что помогает, бандаж, когда операция.",
    }
    if payload in rec_map:
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, rec_map[payload])
        await send_message(chat_id, answer,
            [[{"type": "callback", "text": "🔙 К восстановлению", "payload": "recovery"},
              {"type": "callback", "text": "🏠 В меню", "payload": "back_menu"}]])
        return

    # ─── ПРЕМИУМ РАЗДЕЛЫ ─────────────────────────────────────
    if payload == "psycho":
        history = get_psycho_history(user_id)
        set_step(user_id, "psycho")
        if history:
            await send_message(chat_id, "🧠 С возвращением! Я помню наш разговор.\n\nКак ты сейчас? 💕", psycho_buttons())
        else:
            await send_message(chat_id,
                "🧠 Привет! Я твой личный психолог 💕\n\nГовори обо всём — усталость, тревога, отношения, чувство вины.\n\nКак ты сейчас?",
                psycho_buttons())
        return

    if payload == "photo_menu":
        if not can_use_product(user_id, "photo_analysis"):
            await send_message(chat_id, "🔒 Анализ фото доступен в Про или разово за 99 ₽", upgrade_buttons())
            return
        # Разное меню для беременных и мам
        if birth_date and birth_date.startswith("pdr:"):
            buttons = [
                [{"type": "callback", "text": "📋 Результаты анализов", "payload": "photo_analysis"}],
                [{"type": "callback", "text": "🩺 Заключение УЗИ", "payload": "photo_uzi"}],
                [{"type": "callback", "text": "💊 Лекарство при беременности", "payload": "photo_med_preg"}],
                [{"type": "callback", "text": "🔴 Сыпь и кожа", "payload": "photo_skin"}],
                [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
            ]
            await send_message(chat_id, "📸 Выбери тип фото 👇", buttons)
        else:
            buttons = [
                [{"type": "callback", "text": "🔴 Сыпь и кожа", "payload": "photo_skin"},
                 {"type": "callback", "text": "🍽 Еда малыша", "payload": "photo_food"}],
                [{"type": "callback", "text": "💩 Стул малыша", "payload": "photo_stool"},
                 {"type": "callback", "text": "💊 Упаковка смеси", "payload": "photo_package"}],
                [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
            ]
            await send_message(chat_id, "📸 Выбери тип фото и отправь изображение 👇", buttons)
        return

    for pt in ["photo_skin", "photo_food", "photo_package", "photo_stool", "photo_analysis", "photo_uzi", "photo_med_preg"]:
        if payload == pt:
            set_step(user_id, pt)
            prompts = {
                "photo_skin": "📸 Отправь фото кожи или сыпи малыша\n\n⚠️ Это ориентир, не диагноз.",
                "photo_food": "📸 Отправь фото еды или блюда",
                "photo_stool": "📸 Отправь фото стула малыша\n\n⚠️ Это ориентир, не диагноз.",
                "photo_package": "📸 Отправь фото упаковки смеси или лекарства",
                "photo_analysis": "📸 Отправь фото результатов анализов\n\nЯ расшифрую показатели.",
                "photo_uzi": "📸 Отправь фото заключения УЗИ\n\nЯ объясню показатели понятным языком.",
                "photo_med_preg": "📸 Отправь фото упаковки лекарства\n\nЯ скажу можно ли его при беременности."
            }
            await send_message(chat_id, prompts[pt])
            return

    if payload == "growth":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Трекер роста и веса доступен с тарифа Старт", upgrade_buttons())
            return
        entries = get_growth(user_id)
        text = "📏 Рост и вес малыша\n\n"
        if entries:
            for h, w, dt in entries[:3]:
                d = datetime.fromisoformat(dt).strftime("%d.%m.%Y")
                text += f"📅 {d} — {h} см, {w} кг\n"
            text += "\n"
        buttons = [
            [{"type": "callback", "text": "➕ Добавить замер", "payload": "growth_add"}],
            [{"type": "callback", "text": "📊 Анализ динамики", "payload": "growth_analyze"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, text, buttons)
        return

    if payload == "growth_add":
        set_step(user_id, "enter_height")
        await send_message(chat_id, "📏 Введи рост малыша в сантиметрах\nНапример: 67.5")
        return

    if payload == "growth_analyze":
        entries = get_growth(user_id)
        if not entries:
            await send_message(chat_id, "Нет данных для анализа. Добавь хотя бы один замер!", back_button())
            return
        await send_message(chat_id, "⏳ Анализирую динамику...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m.%Y')}: рост {h} см, вес {w} кг" for h, w, dt in entries])
        answer = await generate_text(EXPERT_BASE,
            f"Ребёнку {m_label}. Динамика роста и веса:\n{data_str}\n\n"
            f"Проанализируй по нормам ВОЗ: прибавки в норме или нет, тренд хороший или нет, на что обратить внимание педиатру.")
        await send_message(chat_id, answer, back_button())
        return

    if payload == "symptoms":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Трекер симптомов доступен с тарифа Старт", upgrade_buttons())
            return
        entries = get_symptoms_list(user_id)
        buttons = [
            [{"type": "callback", "text": "➕ Записать симптом", "payload": "symptom_add"},
             {"type": "callback", "text": "🔍 Анализ", "payload": "symptom_analyze"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        text = "🌡 Трекер симптомов\n\n"
        if entries:
            for s, dt in entries[:5]:
                d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
                text += f"📅 {d} — {s}\n"
        else:
            text += "Записей нет."
        await send_message(chat_id, text, buttons)
        return

    if payload == "symptom_add":
        set_step(user_id, "enter_symptom")
        await send_message(chat_id, "🌡 Опиши симптом\n\nНапример: температура 38.2, кашель, сыпь")
        return

    if payload == "symptom_analyze":
        entries = get_symptoms_list(user_id)
        if not entries:
            await send_message(chat_id, "Нет симптомов для анализа.", back_button())
            return
        await send_message(chat_id, "⏳ Анализирую...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {s}" for s, dt in entries])
        answer = await generate_text(EXPERT_BASE,
            f"Ребёнку {m_label}. Симптомы:\n{data_str}\n\nПроанализируй: что это, динамика, стоит ли к врачу.")
        await send_message(chat_id, answer, back_button())
        return

    if payload == "feeding":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Трекер кормлений доступен с тарифа Старт", upgrade_buttons())
            return
        conn = db_connect()
        entries = conn.execute(
            "SELECT entry, created_at FROM diary WHERE user_id=? AND entry LIKE 'КОРМ:%' ORDER BY created_at DESC LIMIT 5",
            (user_id,)).fetchall()
        conn.close()
        buttons = [
            [{"type": "callback", "text": "🤱 Левая грудь", "payload": "feed_left"},
             {"type": "callback", "text": "🤱 Правая грудь", "payload": "feed_right"}],
            [{"type": "callback", "text": "🍼 Смесь/бутылочка", "payload": "feed_bottle"}],
            [{"type": "callback", "text": "📊 Статистика", "payload": "feed_stats"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        text = "🤱 Трекер кормлений\n\n"
        if entries:
            for entry, dt in entries:
                d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
                text += f"📅 {d} — {entry.replace('КОРМ:', '')}\n"
        else:
            text += "Записей нет. Нажми кнопку после каждого кормления!"
        await send_message(chat_id, text, buttons)
        return

    if payload == "feed_stats":
        conn = db_connect()
        entries = conn.execute(
            "SELECT entry, created_at FROM diary WHERE user_id=? AND entry LIKE 'КОРМ:%' ORDER BY created_at DESC LIMIT 20",
            (user_id,)).fetchall()
        conn.close()
        if not entries:
            await send_message(chat_id, "Нет данных для анализа.", back_button())
            return
        await send_message(chat_id, "⏳ Анализирую кормления...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {entry.replace('КОРМ:','')}" for entry, dt in entries])
        answer = await generate_text(EXPERT_BASE,
            f"Ребёнку {m_label}. Журнал кормлений:\n{data_str}\n\n"
            f"Проанализируй: достаточно ли кормлений по нормам ВОЗ, правильные ли интервалы, достаточная ли продолжительность. Дай практические рекомендации.")
        await send_message(chat_id, answer, back_button())
        if ai_answer_success(answer) and get_user_plan(user_id) not in PRO_PLANS:
            consume_credit(user_id, "feeding_report")
        return

    for feed_type in ["feed_left", "feed_right", "feed_bottle"]:
        if payload == feed_type:
            names = {"feed_left": "Левая грудь", "feed_right": "Правая грудь", "feed_bottle": "Смесь/бутылочка"}
            set_step(user_id, f"feed_duration_{feed_type}")
            await send_message(chat_id, f"⏱ Сколько минут кормила? ({names[feed_type]})\nВведи число:")
            return

    if payload == "sleep_log":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Дневник сна доступен с тарифа Старт", upgrade_buttons())
            return
        conn = db_connect()
        entries = conn.execute(
            "SELECT entry, created_at FROM diary WHERE user_id=? AND entry LIKE 'СОН:%' ORDER BY created_at DESC LIMIT 6",
            (user_id,)).fetchall()
        conn.close()
        buttons = [
            [{"type": "callback", "text": "😴 Уснул", "payload": "sleep_start"},
             {"type": "callback", "text": "🌅 Проснулся", "payload": "sleep_end"}],
            [{"type": "callback", "text": "📊 Анализ сна", "payload": "sleep_analyze"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        text = "🌙 Дневник сна\n\n"
        if entries:
            for entry, dt in entries:
                d = datetime.fromisoformat(dt).strftime("%d.%m %H:%M")
                action = entry.replace("СОН:", "")
                emoji = "😴" if "уснул" in action else "🌅"
                text += f"{emoji} {d} — {action}\n"
        else:
            text += "Записей нет. Нажимай когда малыш засыпает и просыпается!"
        await send_message(chat_id, text, buttons)
        return

    if payload == "sleep_analyze":
        conn = db_connect()
        entries = conn.execute(
            "SELECT entry, created_at FROM diary WHERE user_id=? AND entry LIKE 'СОН:%' ORDER BY created_at DESC LIMIT 20",
            (user_id,)).fetchall()
        conn.close()
        if len(entries) < 4:
            await send_message(chat_id, "Нужно больше записей для анализа. Фиксируй сон несколько дней!", back_button())
            return
        await send_message(chat_id, "⏳ Анализирую сон...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {entry.replace('СОН:','')}" for entry, dt in entries])
        answer = await generate_text(EXPERT_BASE,
            f"Ребёнку {m_label}. Дневник сна:\n{data_str}\n\n"
            f"Проанализируй паттерн сна по нормам AAP для этого возраста: "
            f"сколько часов спит суммарно, правильные ли интервалы бодрствования, "
            f"есть ли проблемы и как их решить. Конкретные рекомендации.")
        await send_message(chat_id, answer, back_button())
        if ai_answer_success(answer) and get_user_plan(user_id) not in PRO_PLANS: consume_credit(user_id, "sleep_report")
        return

    if payload == "sleep_start":
        conn = db_connect()
        conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                     (user_id, "СОН:уснул", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await send_message(chat_id, "😴 Записала — малыш уснул!", back_button())
        activity = build_activity_summary(get_recent_family_data(user_id, days=7))
        if activity["sleep_events"] >= 4:
            await maybe_send_marketing_offer(
                chat_id, user_id, "sleep_report_ready",
                "🌙 Картина сна уже начинает формироваться. Разбор покажет интервалы и возможные закономерности.",
                [[{"type": "callback", "text": "🌙 Разбор сна — 199 ₽", "payload": "buy_sleep_report"}],
                 [{"type": "callback", "text": "💎 Все отчёты в Про", "payload": "pay_plan_pro"}]],
            )
        return

    if payload == "sleep_end":
        conn = db_connect()
        conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                     (user_id, "СОН:проснулся", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await send_message(chat_id, "🌅 Записала — малыш проснулся!", back_button())
        activity = build_activity_summary(get_recent_family_data(user_id, days=7))
        if activity["sleep_events"] >= 4:
            await maybe_send_marketing_offer(
                chat_id, user_id, "sleep_report_ready",
                "🌙 Картина сна уже начинает формироваться. Разбор покажет интервалы и возможные закономерности.",
                [[{"type": "callback", "text": "🌙 Разбор сна — 199 ₽", "payload": "buy_sleep_report"}],
                 [{"type": "callback", "text": "💎 Все отчёты в Про", "payload": "pay_plan_pro"}]],
            )
        return

    if payload == "vaccines":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Прививочный календарь доступен с тарифа Старт", upgrade_buttons())
            return
        # Получаем прививки из БД
        conn = db_connect()
        vaccinations = conn.execute(
            "SELECT id, vaccine, scheduled_date, done FROM vaccinations WHERE user_id=? ORDER BY scheduled_date",
            (user_id,)).fetchall()
        conn.close()
        buttons = [
            [{"type": "callback", "text": "📅 Создать календарь", "payload": "vaccines_create"}],
            [{"type": "callback", "text": "✅ Отметить сделанную", "payload": "vaccines_done"}],
            [{"type": "callback", "text": "❓ Что такое эта прививка", "payload": "vaccines_info"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        if vaccinations:
            text = "💉 Прививочный календарь\n\n"
            for vid, vaccine, sdate, done in vaccinations[:10]:
                status = "✅" if done else "⏳"
                text += f"{status} {sdate} — {vaccine}\n"
        else:
            text = "💉 Прививочный календарь\n\nКалендарь не создан. Нажми 'Создать календарь'!"
        await send_message(chat_id, text, buttons)
        return

    if payload == "vaccines_create":
        if not birth_date or birth_date.startswith("pdr:"):
            await send_message(chat_id, "Сначала укажи дату рождения малыша!", back_button())
            return
        birth = datetime.strptime(birth_date, "%d.%m.%Y")
        schedule = [
            (0, "БЦЖ (туберкулёз)"), (0, "Гепатит B — 1-я доза"),
            (1, "Гепатит B — 2-я доза"), (2, "АКДС — 1-я доза"),
            (2, "Полиомиелит — 1-я доза"), (2, "Пневмококк — 1-я доза"),
            (3, "АКДС — 2-я доза"), (3, "Полиомиелит — 2-я доза"),
            (4, "АКДС — 3-я доза"), (4, "Полиомиелит — 3-я доза"),
            (4, "Пневмококк — 2-я доза"), (6, "Гепатит B — 3-я доза"),
            (12, "Корь, краснуха, паротит (КПК)"), (12, "Ветряная оспа"),
            (15, "Пневмококк — ревакцинация"), (18, "АКДС — ревакцинация"),
            (18, "Полиомиелит — ревакцинация"),
        ]
        conn = db_connect()
        existing = conn.execute("SELECT COUNT(*) FROM vaccinations WHERE user_id=?", (user_id,)).fetchone()[0]
        if existing:
            conn.close()
            await send_message(chat_id, "Календарь уже создан. Чтобы избежать дублей, повторное создание отменено.", back_button())
            return
        for month_age, vaccine in schedule:
            vac_date = add_months(birth, month_age).strftime("%d.%m.%Y")
            conn.execute("INSERT INTO vaccinations (user_id, vaccine, scheduled_date, created_at) VALUES (?,?,?,?)",
                        (user_id, vaccine, vac_date, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await send_message(chat_id, f"✅ Календарь создан! Добавлено {len(schedule)} прививок.\n\nКалендарь сохранён. Напоминания можно будет включить после подключения модуля уведомлений.", back_button())
        return

    if payload == "vaccines_done":
        conn = db_connect()
        vaccinations = conn.execute(
            "SELECT id, vaccine, scheduled_date FROM vaccinations WHERE user_id=? AND done=0 ORDER BY scheduled_date",
            (user_id,)).fetchall()
        conn.close()
        if not vaccinations:
            await send_message(chat_id, "Нет незавершённых прививок.", back_button())
            return
        buttons = [[{"type": "callback", "text": f"✅ {vaccine} ({sdate})", "payload": f"vac_done_{vid}"}]
                   for vid, vaccine, sdate in vaccinations[:8]]
        buttons.append([{"type": "callback", "text": "🔙 Назад", "payload": "vaccines"}])
        await send_message(chat_id, "Выбери прививку которую сделали:", buttons)
        return

    if payload.startswith("vac_done_"):
        vac_id = int(payload.replace("vac_done_", ""))
        conn = db_connect()
        conn.execute("UPDATE vaccinations SET done=1 WHERE id=? AND user_id=?", (vac_id, user_id))
        conn.commit()
        conn.close()
        await send_message(chat_id, "✅ Прививка отмечена как сделанная!", back_button())
        return

    if payload == "vaccines_info":
        buttons = [
            [{"type": "callback", "text": "💉 БЦЖ", "payload": "vac_bcg"},
             {"type": "callback", "text": "💉 Гепатит B", "payload": "vac_hepb"}],
            [{"type": "callback", "text": "💉 АКДС", "payload": "vac_akds"},
             {"type": "callback", "text": "💉 Полиомиелит", "payload": "vac_polio"}],
            [{"type": "callback", "text": "💉 Пневмококк", "payload": "vac_pneumo"},
             {"type": "callback", "text": "💉 КПК", "payload": "vac_kpk"}],
            [{"type": "callback", "text": "💉 Ветрянка", "payload": "vac_varicella"}],
            [{"type": "callback", "text": "🔙 Назад", "payload": "vaccines"}]
        ]
        await send_message(chat_id, "Выбери прививку чтобы узнать подробнее 👇", buttons)
        return

    vac_info = {
        "vac_bcg": "БЦЖ (туберкулёз)",
        "vac_hepb": "Гепатит B",
        "vac_akds": "АКДС (коклюш, дифтерия, столбняк)",
        "vac_polio": "Полиомиелит",
        "vac_pneumo": "Пневмококковая инфекция",
        "vac_kpk": "КПК (корь, паротит, краснуха)",
        "vac_varicella": "Ветряная оспа",
    }
    if payload in vac_info:
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE,
            f"Дай подробное объяснение прививки {vac_info[payload]} для родителей: "
            f"от чего защищает, когда делают, как подготовить, нормальные реакции, "
            f"красные флаги, развенчай мифы с научными аргументами.")
        await send_message(chat_id, answer, [[{"type": "callback", "text": "🔙 К прививкам", "payload": "vaccines_info"}]])
        return

    if payload == "benefits":
        if not has_plan_access(user_id, "start"):
            await send_message(chat_id, "🔒 Пособия и выплаты доступны с тарифа Старт", upgrade_buttons())
            return
        buttons = [
            [{"type": "callback", "text": "👶 Единовременное при рождении", "payload": "ben_birth"}],
            [{"type": "callback", "text": "🤱 Пособие по уходу до 1.5 лет", "payload": "ben_15"}],
            [{"type": "callback", "text": "📅 Выплаты до 3 лет", "payload": "ben_3"}],
            [{"type": "callback", "text": "🏠 Материнский капитал", "payload": "ben_matcap"}],
            [{"type": "callback", "text": "💊 По беременности и родам", "payload": "ben_decree"}],
            [{"type": "callback", "text": "👨‍👩‍👧 Многодетная семья", "payload": "ben_multi"}],
            [{"type": "callback", "text": "❓ Что положено именно мне", "payload": "ben_personal"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "💰 Пособия и выплаты\n\nВыбери раздел 👇", buttons)
        return

    ben_map = {
        "ben_birth": "Единовременное пособие при рождении в России 2024-2025. Размер, документы, куда обращаться.",
        "ben_15": "Пособие по уходу до 1.5 лет в России 2024-2025. Для работающих и неработающих, как рассчитать.",
        "ben_3": "Выплаты на ребёнка от 1.5 до 3 лет в России 2024-2025. Путинские выплаты, условия.",
        "ben_matcap": "Материнский капитал в России 2024-2025. Размер, на что потратить, как оформить.",
        "ben_decree": "Пособие по беременности и родам (декретные) в России 2024-2025. Как рассчитывается для работающих, ИП, безработных. Сроки декрета, документы.",
        "ben_multi": "Льготы и выплаты многодетным семьям в России 2024-2025. Федеральные и региональные льготы, налоговые вычеты, земельные участки, ЖКХ, досрочная пенсия мамы.",
    }
    if payload in ben_map:
        await send_message(chat_id, "⏳ Подбираю...")
        answer = await generate_text("Ты эксперт по социальным выплатам в России 2024-2025.", ben_map[payload])
        await send_message(chat_id, answer, back_button())
        return

    if payload == "ben_personal":
        set_step(user_id, "ask")
        await send_message(chat_id, "❓ Расскажи о своей ситуации:\n\nРаботаешь или нет, какой по счёту ребёнок, замужем или нет, регион.")
        return

    if payload in {"pay_premium", "premium_info"}:
        await send_message(chat_id,
            "💎 Премиум-возможности\n\n"
            "🌱 Старт\n"
            "Трекеры роста, симптомов, кормлений и сна, прививки, пособия, 30 AI-вопросов и 50 сообщений поддержки.\n\n"
            "💎 Про\n"
            "Всё из Старт + Мамин психолог, анализ фото, сводка врачу, разбор сна и кормлений, недельный отчёт.\n\n"
            "🛒 Отдельные решения без подписки:\n"
            "Фото — 99 ₽ · Сводка врачу — 149 ₽ · Кормления — 149 ₽ · Сон — 199 ₽ · Отчёт — 199 ₽.",
            upgrade_buttons())
        return

    if payload.startswith("pay_plan_") or payload.startswith("buy_"):
        product_code = payload.replace("pay_plan_", "", 1) if payload.startswith("pay_plan_") else payload.replace("buy_", "", 1)
        try:
            info = PLAN_CATALOG.get(product_code) or ONE_TIME_PRODUCTS[product_code]
            payment = await create_payment(user_id, product_code)
            payment_id = payment.get("id", "")
            pay_url = payment.get("confirmation", {}).get("confirmation_url", "")
            if not payment_id or not pay_url:
                raise RuntimeError("ЮКасса не вернула ссылку или id")
            save_commercial_payment(payment_id,user_id,product_code)
            amount_int=int(float(info["amount"]))
            await send_message(chat_id,
                f"{info['name']}\n\nСтоимость: {amount_int} ₽. После оплаты доступ активируется автоматически.",
                [[{"type":"link","text":f"💳 Оплатить {amount_int} ₽","url":pay_url}],
                 [{"type":"callback","text":"🔙 К тарифам","payload":"premium_info"}]])
        except Exception as exc:
            logging.error("Ошибка создания платежа MAX: %s", exc)
            await send_message(chat_id,"Не удалось создать платёж. Попробуйте позже.",upgrade_buttons())
        return

    await send_message(chat_id, "Выбери действие из меню 👇", main_menu_buttons())


async def process_photo(chat_id, user_id, photo_url):
    if not can_use_product(user_id, "photo_analysis"):
        await send_message(chat_id, "🔒 Анализ фото доступен в Про или разово за 99 ₽", upgrade_buttons())
        return

    user = get_user(user_id)
    step = user.get("step", "")
    type_map = {
        "photo_skin": "skin", "photo_food": "food", "photo_package": "package",
        "photo_stool": "stool", "photo_analysis": "analysis", "photo_uzi": "uzi",
        "photo_med_preg": "med_preg"
    }
    photo_type = type_map.get(step)
    use_photo_credit = get_user_plan(user_id) not in PRO_PLANS
    if not photo_type:
        await send_message(chat_id, "Сначала выбери тип анализа фото в меню.", back_button())
        return

    birth_date = user.get("birth_date", "")
    if birth_date and birth_date.startswith("pdr:"):
        weeks = calc_pregnancy_weeks(birth_date[4:])
        person_context = f"Беременность: {weeks} недель." if weeks is not None else "Беременность."
    else:
        months = calc_child_age(birth_date) if birth_date else None
        person_context = f"Возраст ребёнка: {age_label(months)}."

    set_step(user_id, "idle")
    await send_message(chat_id, "⏳ Анализирую фото...")
    try:
        photo_bytes, declared_mime = await download_file(photo_url)
        if not photo_bytes:
            await send_message(chat_id, "Не удалось получить фото. Попробуй отправить его ещё раз.", back_button())
            return
        import base64
        photo_b64 = base64.b64encode(photo_bytes).decode()
        mime = detect_image_mime(photo_bytes, declared_mime)

        prompts = {
            "skin": (
                "На изображении видна кожа человека с возможным кожным проявлением? Ответь только ДА или НЕТ.",
                "Ты педиатр. Опиши только видимые признаки на коже: локализацию, цвет, форму и распространённость. Назови несколько возможных причин без постановки диагноза. Дай безопасные действия дома и красные флаги для срочного обращения к врачу. Не назначай рецептурные препараты и обязательно укажи, что фото не заменяет осмотр."
            ),
            "stool": (
                "На изображении виден подгузник или стул ребёнка? Ответь только ДА или НЕТ.",
                "Ты педиатр. Опиши видимые цвет и консистенцию стула ребёнка, возможные нормальные варианты и настораживающие признаки. Укажи, когда нужен педиатр срочно. Не ставь диагноз по фотографии."
            ),
            "analysis": (
                "На изображении медицинский документ или результаты лабораторных анализов? Ответь только ДА или НЕТ.",
                f"Ты врач, объясняющий анализы беременной понятным языком. {person_context} Перепиши только уверенно читаемые показатели, сравнивай их прежде всего с референсами на самом бланке и учитывай беременность. Не додумывай нечитаемые значения. Выдели отклонения и вопросы для лечащего врача. Не ставь диагноз."
            ),
            "uzi": (
                "На изображении медицинское заключение УЗИ или его бланк? Ответь только ДА или НЕТ.",
                f"Ты акушер-гинеколог, объясняющий заключение УЗИ простыми словами. {person_context} Разбирай только читаемые данные, не угадывай срок или значения. Объясни показатели, отметь, что требует обсуждения с врачом, и перечисли красные флаги. Не ставь диагноз."
            ),
            "med_preg": (
                "На изображении упаковка лекарства или медицинского препарата? Ответь только ДА или НЕТ.",
                f"Ты клинический фармаколог. {person_context} Определи препарат и действующее вещество только если надпись читаема. Объясни назначение и известные ограничения при беременности. Не используй устаревшие буквенные категории FDA как единственную оценку, не назначай дозу и не разрешай приём без врача. Если препарат не распознан уверенно, прямо скажи это."
            ),
            "food": (
                "На изображении еда, продукт или блюдо? Ответь только ДА или НЕТ.",
                f"Ты диетолог-педиатр. {person_context} Опиши, что видно, оцени соответствие возрасту, форму подачи и риски удушья, соли, сахара, мёда и аллергенов. Не утверждай состав, если упаковка или ингредиенты не видны. Дай безопасный вариант адаптации блюда."
            ),
            "package": (
                "На изображении упаковка смеси, детского продукта или лекарства? Ответь только ДА или НЕТ.",
                f"Ты педиатр и фармаколог. {person_context} Считай только видимую информацию с упаковки: название, назначение, возраст, состав и предупреждения. Не додумывай нечитаемый текст. Для лекарств не назначай дозировку, для смеси не советуй замену без оценки ребёнка врачом."
            ),
        }
        filter_q, analysis_q = prompts[photo_type]
        image_url = f"data:{mime};base64,{photo_b64}"
        filter_resp = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": filter_q}
            ]}], max_tokens=10
        )
        verdict = (filter_resp.choices[0].message.content or "").strip().upper()
        if "ДА" not in verdict:
            await send_message(chat_id, "📸 На фото не удалось уверенно распознать выбранный тип. Выбери раздел и отправь более чёткое изображение.", back_button())
            return
        resp = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": analysis_q}
            ]}], max_tokens=900
        )
        answer = (resp.choices[0].message.content or "").replace("**", "").strip()
        await send_message(chat_id, answer or "Не удалось уверенно разобрать изображение.", back_button())
        if use_photo_credit:
            consume_credit(user_id, "photo_analysis")
    except Exception as exc:
        logging.exception("Photo error: %s", exc)
        await send_message(chat_id, "Не удалось проанализировать фото. Попробуй более чёткое изображение.", back_button())


# ========== АВТОПОСТИНГ В КАНАЛ ==========
# Редакционная система MAX-канала: 3 публикации в день,
# память тем, защита от повторов, опросы и мягкие переходы в личный чат бота.

WEEKLY_EDITORIAL = {
    0: "организация недели, режим семьи и снижение бытового хаоса",
    1: "развитие ребёнка без сравнений и лишней тревоги",
    2: "здоровье понятным языком и безопасные алгоритмы действий",
    3: "сон, режим и восстановление всей семьи",
    4: "эмоции мамы, чувство вины, усталость и отношения",
    5: "семейная жизнь, папа, бабушки, прогулки и простые игры",
    6: "итоги недели, наблюдения, полезные привычки и подготовка к новой неделе",
}

MORNING_FORMATS = [
    "короткое тёплое напоминание без наставлений",
    "одна маленькая задача на день",
    "поддерживающая мысль для уставшей мамы",
    "мини-практика на две минуты",
    "разрешение не быть идеальной",
]

DAY_FORMATS = [
    "сохраняемый чек-лист",
    "миф или правда с объяснением",
    "одна ситуация для трёх возрастов",
    "разбор частой ошибки без осуждения",
    "пошаговый алгоритм действий",
    "короткий разбор вопроса мамы",
    "что нормально, а что стоит обсудить со специалистом",
    "три практических шага на сегодня",
]

EVENING_FORMATS = [
    "короткая история с узнаваемой ситуацией",
    "вопрос для самопроверки",
    "мини-кейс до и после использования трекера",
    "подборка из трёх полезных наблюдений",
    "мягкая демонстрация одной функции бота",
]

CHANNEL_SYSTEM_PROMPT = (
    "Ты редактор полезного канала «Я МАМА» в MAX для беременных и родителей детей до 7 лет. "
    "Пиши живо, тепло и естественно, без ощущения нейросетевой статьи. "
    "Не изображай врача и не придумывай истории реальных подписчиц. "
    "Не вставляй несуществующие исследования, ссылки, точные проценты или спорные медицинские дозировки. "
    "Медицинские темы подавай осторожно: объясняй общие ориентиры, красные флаги и необходимость очной помощи. "
    "Не используй канцелярит, длинное вступление, хэштеги и фразы «важно помнить», «давайте разберёмся». "
    "Каждый пост должен иметь одну ясную мысль и практическую пользу. "
    "Не повторяй темы и формулировки из истории публикаций."
)


def save_channel_post(slot, theme, format_name, title, text):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO channel_posts (slot, theme, format_name, title, text, created_at) VALUES (?,?,?,?,?,?)",
            (slot, theme, format_name, title, text, datetime.now().isoformat()),
        )


def channel_slot_published_today(slot):
    start = datetime.now(ZoneInfo("Europe/Moscow")).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM channel_posts WHERE slot=? AND created_at>=? ORDER BY id DESC LIMIT 1",
            (slot, start),
        ).fetchone()
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


def is_channel_post_too_similar(title, text, threshold=0.66):
    from difflib import SequenceMatcher
    candidate = normalize_for_similarity(f"{title} {text}")[:1200]
    if not candidate:
        return True
    for old_title, _, _, old_text in get_recent_channel_posts(50):
        previous = normalize_for_similarity(f"{old_title} {old_text}")[:1200]
        if previous and SequenceMatcher(None, candidate, previous).ratio() >= threshold:
            return True
    return False


def fallback_channel_post(slot, theme, format_name):
    """Резервный пост, чтобы канал не останавливался при недоступности AI."""
    theme_low = (theme or "").lower()
    if "сон" in theme_low:
        subject = "сон ребёнка"
        action = "Сегодня отметьте время засыпания и пробуждения — даже две записи уже полезнее, чем попытка вспомнить всё вечером."
    elif any(x in theme_low for x in ("питан", "корм", "гв", "прикорм")):
        subject = "питание и кормления"
        action = "Сегодня запишите хотя бы одно кормление: время, продолжительность и то, как чувствовал себя малыш."
    elif any(x in theme_low for x in ("здоров", "симптом", "врач")):
        subject = "здоровье ребёнка"
        action = "Если что-то настораживает, запишите время появления симптома, температуру и изменения в поведении — это поможет врачу увидеть картину точнее."
    elif any(x in theme_low for x in ("эмоц", "устал", "тревог", "мам")):
        subject = "состояние мамы"
        action = "Выберите сегодня одно действие, которое действительно уменьшит нагрузку: попросить о помощи, перенести необязательное дело или отдохнуть 15 минут без чувства вины."
    elif any(x in theme_low for x in ("развит", "игр", "речь")):
        subject = "развитие ребёнка"
        action = "Проведите десять спокойных минут без телефона: поговорите, назовите предметы вокруг или повторите любимую игру малыша."
    else:
        subject = "спокойный день с ребёнком"
        action = "Не пытайтесь сделать всё идеально. Выберите одно важное дело для ребёнка и одно маленькое действие для себя."

    if slot in ("08:00", "morning"):
        return "Один спокойный шаг на сегодня", f"Сегодняшняя тема — {subject}.\n\n{action}\n\nМаленькие повторяющиеся действия дают больше пользы, чем редкие идеальные дни."
    if slot in ("13:00", "afternoon"):
        return "Практичный ориентир для мамы", f"Когда дел много, полезно опираться не на память, а на простую систему.\n\nТема дня: {subject}.\n\n1. Зафиксируйте один важный факт.\n2. Отметьте, что изменилось по сравнению со вчера.\n3. Запишите один вопрос, который стоит обсудить со специалистом или близкими.\n4. Не делайте выводов по одному эпизоду — смотрите на динамику.\n\n{action}"
    return "День не обязан быть идеальным", f"Сегодня мы говорили про {subject}.\n\nВечером достаточно ответить себе на два вопроса: что сегодня получилось и что можно упростить завтра.\n\nЗабота о семье начинается не с идеальности, а с устойчивости."


def parse_generated_channel_post(raw):
    raw = (raw or "").replace("**", "").strip()
    title = "Полезное для мамы"
    body = raw
    if raw.startswith("ЗАГОЛОВОК:"):
        first, _, rest = raw.partition("\n")
        title = first.replace("ЗАГОЛОВОК:", "", 1).strip() or title
        body = rest.strip()
    elif "\n" in raw:
        first, rest = raw.split("\n", 1)
        if len(first) <= 90:
            title = first.strip(" —:•") or title
            body = rest.strip()
    return title[:100], body


async def generate_channel_post(slot, theme, format_name, instruction, max_chars, with_bot_bridge=False):
    history = channel_history_for_prompt()
    bridge = (
        "В конце добавь один естественный переход к конкретной функции личного бота — не продавай подписку напрямую. "
        "Подходящие функции: персональный план «Сегодня», дневник сна, трекер кормлений, сводка к врачу, "
        "недельный отчёт, тревожная кнопка «Ребёнку плохо», психолог. "
        if with_bot_bridge else
        "Не упоминай бот и не продавай ничего."
    )
    prompt = (
        f"Время публикации: {slot}.\n"
        f"Тема дня: {theme}.\n"
        f"Формат: {format_name}.\n"
        f"Задача: {instruction}.\n"
        f"Ограничение: до {max_chars} знаков. Короткие абзацы, удобно читать одной рукой.\n"
        f"{bridge}\n"
        "Верни текст в формате:\nЗАГОЛОВОК: короткий цепляющий заголовок\nтекст поста\n\n"
        "Недавние публикации, которые нельзя повторять:\n"
        f"{history}"
    )
    last_error = None
    for _ in range(3):
        try:
            raw = await generate_text(CHANNEL_SYSTEM_PROMPT, prompt, model="gpt-4o-mini")
        except Exception as exc:
            last_error = str(exc)
            break
        title, body = parse_generated_channel_post(raw)
        body = body[:max_chars].rstrip()
        if body and not is_channel_post_too_similar(title, body):
            return title, body
        prompt += "\nПредыдущий вариант оказался слишком похож на старые публикации. Выбери совершенно другой угол и примеры."

    title, body = fallback_channel_post(slot, theme, format_name)
    logging.error("Канал MAX: AI-текст недоступен, опубликован резервный пост. Причина: %s", last_error or "нет уникального ответа")
    try:
        await send_message(OWNER_ID, f"⚠️ Канал MAX: AI-генерация недоступна. Для слота {slot} будет опубликован резервный пост.")
    except Exception as exc:
        logging.error("Канал MAX: не удалось уведомить владельца об ошибке AI: %s", exc)
    return title, body[:max_chars].rstrip()


def channel_funnel_for_post(theme="", title="", body="", format_name=""):
    """Подбирает тематический мостик и CTA для каждого поста MAX-канала."""
    text = " ".join([theme or "", title or "", body or "", format_name or ""]).lower()
    rules = [
        (("сон", "недосып", "засып", "пробуж"),
         "🌙 Общие нормы не учитывают возраст и ваш режим. Получите бесплатный персональный разбор сна.",
         "🌙 Разобрать сон ребёнка"),
        (("корм", "гв", "груд", "прикорм", "питан", "смесь"),
         "🥣 Получите рекомендацию по кормлению с учётом возраста и вашей ситуации.",
         "🥣 Разобрать питание ребёнка"),
        (("врач", "симптом", "здоров", "температур", "сып", "лекар", "боле", "педиатр"),
         "🩺 Опишите наблюдения — помощник бесплатно соберёт важное и подготовит вопросы врачу.",
         "🩺 Подготовить вопросы врачу"),
        (("развит", "возраст", "игр", "заняти", "навык", "речь"),
         "👶 Проверьте навык или поведение с учётом точного возраста ребёнка.",
         "👶 Проверить развитие"),
        (("истер", "каприз", "эмоц", "устал", "тревог", "вина", "психолог", "выгор"),
         "🤍 Опишите, что происходит. Первый персональный разбор поможет спокойно увидеть следующий шаг.",
         "🤍 Разобрать мою ситуацию"),
        (("отношен", "муж", "пап", "семь", "бабуш", "партн", "близост"),
         "👨‍👩‍👧 Опишите ситуацию и получите спокойный план следующего разговора.",
         "👨‍👩‍👧 Подготовить разговор"),
        (("беремен", "род", "восстанов", "срок"),
         "🤰 Получите персональную подсказку для вашего срока или этапа восстановления.",
         "🤰 Открыть помощника"),
    ]
    for keywords, bridge, button in rules:
        if any(word in text for word in keywords):
            return bridge, button
    return (
        "✨ В «Мамином помощнике» можно получить подсказку именно для вашей ситуации и возраста ребёнка.",
        "✨ Открыть помощника на сегодня",
    )


def channel_start_payload(theme="", title="", body="", format_name=""):
    text = " ".join([theme or "", title or "", body or "", format_name or ""]).lower()
    rules = [
        (("сон", "недосып", "засып", "пробуж"), "channel_sleep"),
        (("корм", "гв", "груд", "прикорм", "питан", "смесь"), "channel_feeding"),
        (("врач", "симптом", "здоров", "температур", "сып", "лекар", "боле", "педиатр"), "channel_doctor"),
        (("истер", "каприз", "эмоц", "устал", "тревог", "вина", "психолог", "выгор"), "channel_psycho"),
        (("беремен", "род", "восстанов", "срок"), "channel_pregnancy"),
        (("развит", "возраст", "игр", "заняти", "навык", "речь"), "channel_child"),
        (("отношен", "муж", "пап", "семь", "бабуш", "партн", "близост"), "channel_family"),
    ]
    for keywords, payload in rules:
        if any(word in text for word in keywords):
            return payload
    return "channel_today"


def max_bot_deeplink(payload="channel_today"):
    return f"{MAX_BOT_PUBLIC_URL}?start={payload}"


def channel_open_button(text="✨ Открыть помощника на сегодня", payload="channel_today"):

    if not MAX_BOT_CHANNEL_LINK:
        logging.error("Кнопка перехода в бот не добавлена: не задан MAX_BOT_CHANNEL_LINK")
        return None
    return [[{"type": "link", "text": text, "url": max_bot_deeplink(payload)}]]


async def send_to_channel(text, buttons=None, bot_button_text="✨ Открыть помощника на сегодня", image_payload=None, start_payload="channel_today"):
    """Отправляет пост с обязательной кликабельной кнопкой и резервной ссылкой, при наличии — с изображением."""
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    raw_text = (text or "").strip()
    final_text = raw_text[:MAX_TEXT_LIMIT].rstrip()

    final_buttons = [list(row) for row in (buttons or [])]
    has_bot_link_button = any(
        button.get("type") == "link" and button.get("url") == max_bot_deeplink(start_payload)
        for row in final_buttons
        for button in row
        if isinstance(button, dict)
    )
    if MAX_BOT_PUBLIC_URL and not has_bot_link_button:
        final_buttons.append([
            {"type": "link", "text": bot_button_text, "url": max_bot_deeplink(start_payload)}
        ])

    attachments = []
    if image_payload:
        attachments.append({"type": "image", "payload": image_payload})
    if final_buttons:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": final_buttons}})

    payload = {"text": final_text, "format": "markdown"}
    if attachments:
        payload["attachments"] = attachments

    delays = [0, 2, 4]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt, delay in enumerate(delays, start=1):
                if delay:
                    await asyncio.sleep(delay)
                r = await client.post(f"{MAX_API}/messages?chat_id={CHANNEL_ID}", json=payload, headers=headers)
                if r.is_success:
                    logging.info("Канал MAX: публикация отправлена status=%s CTA=%s image=%s", r.status_code, bot_button_text, 'yes' if image_payload else 'no')
                    return True
                body = r.text[:500]
                if "attachment.not.ready" in body and attempt < len(delays):
                    next_delay = delays[attempt] if attempt < len(delays) else 0
                    logging.warning("Канал MAX: вложение ещё не готово, повтор через %s сек.", next_delay)
                    continue
                logging.error("Канал MAX: ошибка %s %s", r.status_code, body)
                return False
    except Exception as exc:
        logging.exception("Канал MAX: ошибка отправки: %s", exc)
        return False


async def publish_channel_post(slot, theme, format_name, title, body, with_button=True, button_text=None):
    if not title or not body:
        logging.warning("Канал: публикация %s пропущена — не удалось получить уникальный текст", slot)
        return

    bridge_text, thematic_button = channel_funnel_for_post(theme, title, body, format_name)
    final_button_text = button_text or thematic_button
    start_payload = channel_start_payload(theme, title, body, format_name)
    final_text = f"{title}\n\n{body}\n\n{bridge_text}".strip()

    image_payload = None
    if slot in {"morning", "evening"}:
        image_path = await create_channel_visual(slot, theme, title, body)
        image_bytes = image_path
        image_payload = await upload_channel_image_to_max(image_bytes, filename=f"channel_{slot}.png") if image_bytes else None
    ok = await send_to_channel(final_text, None, final_button_text, image_payload=image_payload, start_payload=start_payload)
    if ok:
        save_channel_post(slot, theme, format_name, title, final_text)
        logging.info("Канал: опубликовано %s | %s | %s | CTA=%s | start=%s | image=%s", slot, format_name, title, final_button_text, start_payload, 'yes' if image_payload else 'no')


async def post_morning():
    today = datetime.now(ZoneInfo("Europe/Moscow"))
    theme = WEEKLY_EDITORIAL[today.weekday()]
    format_name = MORNING_FORMATS[today.date().toordinal() % len(MORNING_FORMATS)]
    title, body = await generate_channel_post(
        "08:00", theme, format_name,
        "Создай короткий утренний пост на 350–650 знаков. Он должен поддержать маму и дать одно маленькое выполнимое действие на сегодня.",
        700, with_bot_bridge=False,
    )
    await publish_channel_post("morning", theme, format_name, title, body)


async def post_afternoon():
    today = datetime.now(ZoneInfo("Europe/Moscow"))
    theme = WEEKLY_EDITORIAL[today.weekday()]
    format_name = DAY_FORMATS[(today.date().toordinal() + today.weekday()) % len(DAY_FORMATS)]
    title, body = await generate_channel_post(
        "13:00", theme, format_name,
        "Создай главный полезный материал дня на 1000–1800 знаков. Дай конкретный алгоритм, чек-лист или разбор ситуации. Материал должен хотеться сохранить или переслать. Не перегружай теорией.",
        1900, with_bot_bridge=False,
    )
    await publish_channel_post("afternoon", theme, format_name, title, body)


async def post_evening_poll():
    if channel_slot_published_today("evening_poll"):
        logging.info("Канал: вечерний опрос уже публиковался сегодня, повтор пропущен")
        return
    today = datetime.now(ZoneInfo("Europe/Moscow"))
    polls = {
        2: ("health", "Что сейчас тревожит вас сильнее всего?", [
            ("sleep", "Сон ребёнка"), ("food", "Питание или прикорм"),
            ("health", "Здоровье"), ("fatigue", "Моя усталость"),
        ]),
        6: ("week", "Что было самым сложным на этой неделе?", [
            ("sleep", "Недосып"), ("tantrums", "Капризы ребёнка"),
            ("time", "Нехватка времени"), ("anxiety", "Тревога и чувство вины"),
        ]),
    }
    poll_data = polls.get(today.weekday())
    if not poll_data:
        logging.warning("Канал: для weekday=%s вечерний опрос не настроен", today.weekday())
        return
    poll_key_base, question, options = poll_data
    poll_key = f"{poll_key_base}{today.strftime('%y%m%d')}"
    buttons = [[{"type": "callback", "text": label, "payload": f"channel_poll_{poll_key}_{key}"}] for key, label in options]
    poll_bridge, poll_button = channel_funnel_for_post(
        WEEKLY_EDITORIAL[today.weekday()], question, " ".join(label for _, label in options), "опрос"
    )
    image_payload = None
    start_payload = channel_start_payload(WEEKLY_EDITORIAL[today.weekday()], question, " ".join(label for _, label in options), "опрос")
    ok = await send_to_channel(
        f"📊 {question}\n\nВыберите один вариант — ответ сохранится анонимно для других участников.\n\n{poll_bridge}",
        buttons,
        poll_button,
        image_payload=image_payload,
        start_payload=start_payload,
    )
    if ok:
        save_channel_post("evening_poll", WEEKLY_EDITORIAL[today.weekday()], "опрос", question, " | ".join(label for _, label in options))
        logging.info("Канал: опубликован опрос | %s | image=%s", question, "yes" if image_payload else "no")


async def post_evening():
    today = datetime.now(ZoneInfo("Europe/Moscow"))
    if today.weekday() in (2, 6):
        await post_evening_poll()
        return
    theme = WEEKLY_EDITORIAL[today.weekday()]
    format_name = EVENING_FORMATS[(today.date().toordinal() * 3) % len(EVENING_FORMATS)]
    title, body = await generate_channel_post(
        "20:00", theme, format_name,
        "Создай вечерний пост на 550–1000 знаков. Он должен вызывать узнавание, реакцию или желание ответить себе на вопрос. Не повторяй дневной материал и не пиши длинную лекцию.",
        1100, with_bot_bridge=False,
    )
    await publish_channel_post("evening", theme, format_name, title, body)


async def channel_weekly_editorial_report():
    conn = db_connect()
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT slot, format_name, COUNT(*) FROM channel_posts WHERE created_at>=? GROUP BY slot, format_name ORDER BY slot, format_name",
        (week_ago,),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM channel_posts WHERE created_at>=?", (week_ago,)).fetchone()[0]
    last_post = conn.execute("SELECT created_at, slot, title FROM channel_posts ORDER BY created_at DESC LIMIT 1").fetchone()
    vote_rows = conn.execute(
        "SELECT poll_key, option_key, COUNT(*) FROM channel_poll_votes WHERE created_at>=? GROUP BY poll_key, option_key ORDER BY poll_key, COUNT(*) DESC",
        (week_ago,),
    ).fetchall()
    conn.close()

    by_slot, by_format = {}, {}
    for slot, format_name, count in rows:
        by_slot[slot] = by_slot.get(slot, 0) + count
        by_format[format_name] = by_format.get(format_name, 0) + count
    slot_labels = {"morning": "Утренних постов", "afternoon": "Полезных разборов", "evening": "Вечерних постов", "evening_poll": "Опросов"}
    lines = ["📊 Отчёт MAX-канала за неделю", "", f"Опубликовано материалов: {total}"]
    for slot in ("morning", "afternoon", "evening", "evening_poll"):
        lines.append(f"{slot_labels[slot]}: {by_slot.get(slot, 0)}")
    if by_format:
        lines.extend(["", "Форматы:"])
        for format_name, count in sorted(by_format.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"• {format_name} — {count}")
    if vote_rows:
        lines.extend(["", "Ответы в опросах:"])
        for poll_key, option_key, count in vote_rows:
            lines.append(f"• {poll_key}: {option_key} — {count}")
    if last_post:
        created_at, slot, title = last_post
        try: created_label = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        except Exception: created_label = created_at
        lines.extend(["", f"Последняя публикация: {created_label}", f"• {title} ({slot})"])
    report_text = "\n".join(lines)
    logging.info("Канал: недельный редакционный отчёт: %s", report_text)
    await send_message(OWNER_ID, report_text)


async def channel_posting_loop():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler as _APScheduler
    scheduler = _APScheduler(timezone="Europe/Moscow")
    scheduler.add_job(post_morning, "cron", hour=8, minute=0, id="mama_channel_morning", replace_existing=True, coalesce=True, misfire_grace_time=1800, max_instances=1)
    scheduler.add_job(post_afternoon, "cron", hour=13, minute=0, id="mama_channel_afternoon", replace_existing=True, coalesce=True, misfire_grace_time=1800, max_instances=1)
    scheduler.add_job(post_evening, "cron", hour=20, minute=0, id="mama_channel_evening", replace_existing=True, coalesce=True, misfire_grace_time=1800, max_instances=1)
    scheduler.add_job(channel_weekly_editorial_report, "cron", day_of_week="sun", hour=21, minute=0, id="mama_channel_weekly_report", replace_existing=True, coalesce=True, misfire_grace_time=3600, max_instances=1)
    scheduler.start()
    while True:
        await asyncio.sleep(3600)


# ========== FASTAPI WEBHOOK ==========
WEBHOOK_URL = "https://maminpomoshnik.ru/webhook"

app = FastAPI()

@app.on_event("startup")
async def startup():
    init_db()
    identity_ok = await refresh_max_bot_identity()
    if identity_ok and MAX_BOT_DEEPLINK:
        logging.info("Публичная ссылка MAX-бота для канала: %s", MAX_BOT_DEEPLINK)
        try:
            await send_message(OWNER_ID, f"✅ Ссылка канала на бота настроена:\n{MAX_BOT_DEEPLINK}\n\nОна будет публиковаться и текстом, и кнопкой.")
        except Exception as exc:
            logging.warning("Не удалось отправить владельцу диагностическую ссылку: %s", exc)
    else:
        logging.error("Публичная ссылка MAX-бота не определена в MAX_BOT_PUBLIC_URL.")
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{MAX_API}/subscriptions",
                json={"url": WEBHOOK_URL, "update_types": ["message_created", "message_callback", "bot_started", "bot_stopped"]}, headers=headers)
            logging.info(f"Webhook регистрация: {r.json()}")
    except Exception as e:
        logging.error(f"Ошибка регистрации webhook: {e}")
    asyncio.create_task(check_payments_loop())
    asyncio.create_task(channel_posting_loop())
    logging.info("Мамин Помощник MAX запущен!")

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logging.info(f"MAX webhook: {data}")

        update_type = data.get("update_type", "")
        message = data.get("message", {})
        callback = data.get("callback", {})

        if update_type == "bot_started":
            user = data.get("user", {})
            start_payload = data.get("payload") or ""
            chat_id = data.get("chat_id") or user.get("user_id")
            user_id = user.get("user_id") or chat_id
            # Игнорируем если это канал
            if not user_id or user_id == CHANNEL_ID:
                return JSONResponse({"ok": True})
            first_name = user.get("name", "мама")
            username = user.get("username", "")
            with db_connect() as conn:
                was_known = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is not None
            get_user(user_id, username, first_name)
            if not was_known and start_payload.startswith("ref_"):
                try:
                    rewarded_referrer = register_referral(user_id, int(start_payload[4:]))
                    if rewarded_referrer:
                        await send_message(rewarded_referrer, "🎁 По твоей ссылке пришёл новый пользователь. Начислен 1 дополнительный AI-вопрос.")
                except (TypeError, ValueError):
                    pass
            set_step(user_id, "idle")
            plan, _ = get_subscription(user_id)
            asyncio.create_task(asyncio.to_thread(sheets_log_visit, user_id, first_name, username, plan))
            existing_user = get_user(user_id, username, first_name)
            existing_birth_date = existing_user.get("birth_date", "")
            is_pregnant_profile = existing_birth_date.startswith("pdr:")
            channel_payloads = {
                "channel": ("🤍 Ты пришла из канала «Я МАМА». ", None),
                "channel_today": ("❓ Получить персональный ответ", "ask"),
                "channel_sleep": ("🌙 Разобрать сон ребёнка", "funnel_sleep"),
                "channel_feeding": ("🥣 Разобрать питание ребёнка", "funnel_feeding"),
                "channel_doctor": ("🩺 Подготовить вопросы врачу", "funnel_doctor"),
                "channel_psycho": ("🤍 Разобрать мою ситуацию", "funnel_mom"),
                "channel_pregnancy": ("🤰 Задать вопрос по беременности", "funnel_pregnancy"),
                "channel_child": ("👶 Проверить развитие", "funnel_development"),
                "channel_family": ("👨‍👩‍👧 Подготовить разговор", "funnel_family"),
            }
            channel_title, channel_callback = channel_payloads.get(start_payload, ("", None))
            intro = "🤍 Ты пришла из канала «Я МАМА». Здесь рекомендации становятся персональными.\n\n" if start_payload.startswith("channel") else ""
            if existing_birth_date.startswith("pdr:"):
                weeks = calc_pregnancy_weeks(existing_birth_date[4:])
                await send_message(chat_id, intro + f"🤰 Ты на {weeks} неделе беременности. Чем могу помочь?", pregnant_menu_buttons())
                if channel_callback:
                    await send_message(chat_id, channel_title, [[{"type": "callback", "text": channel_title, "payload": channel_callback}]])
            elif existing_birth_date:
                months = calc_child_age(existing_birth_date)
                await send_message(chat_id, intro + f"👶 Малышу {age_label(months)}. Чем могу помочь?", main_menu_buttons())
                if channel_callback:
                    await send_message(chat_id, channel_title, [[{"type": "callback", "text": channel_title, "payload": channel_callback}]])
            else:
                if start_payload.startswith("channel_"):
                    with db_connect() as conn:
                        conn.execute("UPDATE users SET pending_start=? WHERE user_id=?", (start_payload, user_id))
                await send_message(chat_id, intro + WELCOME_TEXT.format(name=first_name),
                    [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                      {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])

        elif update_type == "message_created":
            sender = message.get("sender", {})
            chat_id = message.get("recipient", {}).get("chat_id")
            user_id = sender.get("user_id")
            first_name = sender.get("name", "мама")
            username = sender.get("username", "")
            body = message.get("body", {})
            text = body.get("text", "")
            attachments = body.get("attachments", [])

            # Игнорируем сообщения в канале
            if not user_id or chat_id == CHANNEL_ID:
                return JSONResponse({"ok": True})

            if attachments:
                for att in attachments:
                    if att.get("type") == "image":
                        payload_data = att.get("payload", {})
                        photo_url = (
                            payload_data.get("url") or
                            payload_data.get("photo_url") or
                            (payload_data.get("photos", [{}])[0].get("url") if payload_data.get("photos") else None)
                        )
                        logging.info(f"Фото payload: {payload_data}")
                        if photo_url:
                            await process_photo(chat_id, user_id, photo_url)
                            return JSONResponse({"ok": True})
                    elif att.get("type") in ("audio", "voice"):
                        audio_url = att.get("payload", {}).get("url")
                        if audio_url:
                            await process_voice(chat_id, user_id, audio_url, first_name)
                            return JSONResponse({"ok": True})

            if text:
                await process_command(chat_id, user_id, text, username, first_name)

        elif update_type == "message_callback":
            user = callback.get("user", {})
            recipient = message.get("recipient", {})
            chat_id = (
                recipient.get("chat_id") or
                callback.get("chat_id") or
                message.get("sender", {}).get("chat_id")
            )
            user_id = user.get("user_id") or message.get("sender", {}).get("user_id")
            first_name = user.get("name") or message.get("sender", {}).get("name", "мама")
            payload_cb = callback.get("payload", "")
            logging.info(f"CALLBACK: chat_id={chat_id} user_id={user_id} payload={payload_cb}")
            if chat_id and payload_cb:
                await process_callback(chat_id, user_id, payload_cb, first_name)
            else:
                logging.error(f"Нет chat_id в callback: {data}")

    except Exception as e:
        logging.error(f"Webhook error: {e}")

    return JSONResponse({"ok": True})


async def process_voice(chat_id, user_id, audio_url, first_name=""):
    await send_message(chat_id, "🎤 Слушаю тебя...")
    try:
        import io
        audio_bytes, audio_mime = await download_file(audio_url, max_size=25 * 1024 * 1024)
        if not audio_bytes:
            await send_message(chat_id, "Не удалось получить голосовое. Попробуй написать текстом.")
            return
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.mp3" if audio_mime == "audio/mpeg" else "voice.ogg"
        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1", file=audio_file, language="ru"
        )
        text = transcript.text.strip()
        if not text:
            await send_message(chat_id, "Не удалось распознать. Говори чуть громче 🎤")
            return
        logging.info(f"Голос распознан: {text}")
        await process_command(chat_id, user_id, text, "", first_name)
    except Exception as e:
        logging.error(f"Voice error: {e}")
        await send_message(chat_id, "Ошибка распознавания. Попробуй написать текстом 💕")



@app.get("/open-max-bot")
async def open_max_bot():
    """Промежуточная страница для перехода из канала MAX в личный чат бота."""
    target = MAX_BOT_DEEPLINK or MAX_BOT_PUBLIC_URL
    return HTMLResponse(f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <meta http-equiv="refresh" content="0;url={target}">
      <title>Открываем Мамин Помощник</title>
      <style>
        body {{font-family:Arial,sans-serif;background:#fff5f8;color:#222;text-align:center;padding:48px 20px}}
        .card {{max-width:520px;margin:auto;background:#fff;border-radius:24px;padding:32px;box-shadow:0 12px 40px rgba(0,0,0,.08)}}
        a {{display:inline-block;margin-top:20px;padding:15px 24px;border-radius:14px;background:#7b61ff;color:#fff;text-decoration:none;font-weight:700}}
      </style>
      <script>setTimeout(function(){{window.location.href={target!r};}},300);</script>
    </head>
    <body>
      <div class="card">
        <div style="font-size:52px">🤱</div>
        <h1>Открываем Мамин Помощник</h1>
        <p>Если приложение MAX не открылось автоматически, нажмите кнопку ниже.</p>
        <a href="{target}">Открыть бота в MAX</a>
      </div>
    </body>
    </html>
    """)

@app.get("/payment/success")
async def payment_success():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
    <html><body style="font-family:Arial;text-align:center;padding:50px;background:#fff0f5">
    <div style="font-size:64px">💎</div>
    <h1 style="color:#e91e8c">Оплата прошла!</h1>
    <p>Оплата принята. Подписка активируется автоматически в течение нескольких секунд.<br>Вернись в Мамин Помощник!</p>
    </body></html>""")

@app.get("/health")
async def health():
    return {"status": "ok"}


async def main():
    if not OWNER_ID:
        logging.warning("MAX_OWNER_ID не задан: уведомления владельцу недоступны")
    config = uvicorn.Config(app, host="0.0.0.0", port=8082, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
