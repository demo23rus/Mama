import asyncio
import sqlite3
import logging
import uuid
import httpx
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from openai import AsyncOpenAI
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import gspread
from google.oauth2.service_account import Credentials

# ========== КОНФИГ ==========
MAX_TOKEN = "f9LHodD0cOIWTyPeJTIKgqKDGe8OGcGqK1BXLiPyMJqGIi1-CZR29YAPZgDbbUpDfwQXKDJovDVJ3HN_88XV"
MAX_API = "https://platform-api.max.ru"
OPENAI_KEY = "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"
OWNER_ID = 549639607
CHANNEL_ID = -75619101439475
SUPPORT_URL = "https://t.me/demo23rus"

# Лимиты
FREE_REQUESTS = 15
FREE_PSYCHO = 30
START_PSYCHO = 100
START_PHOTO = 5

# ЮКасса
YOOKASSA_SHOP_ID = "1363324"
YOOKASSA_SECRET = "live_-RKE9nsi8wZiM-5f00z78E84OYSi3M0Dj9w_-pE0Mvw"

# ========== GOOGLE SHEETS ==========
GOOGLE_CREDS_PATH = "/root/google_credentials.json"
SPREADSHEET_ID_MAMA = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
SHEET_NAME = "МамаБот MAX"

def get_gsheet():
    try:
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID_MAMA)
        try:
            return spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
            ws.append_row(["Дата", "user_id", "Имя", "Username", "Тариф", "Отзыв"])
            return ws
    except Exception as e:
        logging.error(f"Ошибка Google Sheets: {e}")
        return None

def sheets_log_visit(user_id, first_name, username, plan):
    try:
        ws = get_gsheet()
        if ws:
            ws.append_row([
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                str(user_id),
                first_name or "",
                username or "",
                plan or "бесплатный",
                ""
            ])
    except Exception as e:
        logging.error(f"Ошибка записи посещения в Sheets: {e}")

def sheets_log_review(user_id, first_name, username, review_text):
    try:
        ws = get_gsheet()
        if not ws:
            return
        col_user = ws.col_values(2)
        uid_str = str(user_id)
        last_row = None
        for i, val in enumerate(col_user):
            if val == uid_str:
                last_row = i + 1
        if last_row:
            ws.update_cell(last_row, 6, review_text)
        else:
            ws.append_row([
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                uid_str,
                first_name or "",
                username or "",
                "",
                review_text
            ])
    except Exception as e:
        logging.error(f"Ошибка записи отзыва в Sheets: {e}")

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

def get_request_count(user_id):
    conn = db_connect()
    c = conn.cursor()
    c.execute("SELECT count FROM requests_count WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_request_count(user_id):
    conn = db_connect()
    conn.execute("INSERT OR REPLACE INTO requests_count (user_id, count) VALUES (?, COALESCE((SELECT count FROM requests_count WHERE user_id=?),0)+1)",
                 (user_id, user_id))
    conn.commit()
    conn.close()

# ========== ЛОГИ ==========
logging.basicConfig(level=logging.INFO)

# ========== КЛИЕНТЫ AI ==========
openai_client = AsyncOpenAI(api_key=OPENAI_KEY)

# ========== MAX API ==========
MAX_TEXT_LIMIT = 3900

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
    chunks = split_message(str(text))
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

# ========== КНОПКИ ==========
def pregnant_menu_buttons():
    return [
        [{"type": "callback", "text": "✨ Сегодня для меня", "payload": "today_brief"}],
        [{"type": "callback", "text": "📊 Мой срок", "payload": "preg_week"}],
        [{"type": "callback", "text": "👶 Развитие малыша", "payload": "preg_baby"}],
        [{"type": "callback", "text": "✅ Чек-лист", "payload": "preg_checklist"}],
        [{"type": "callback", "text": "🛍 Список покупок", "payload": "preg_shop"}],
        [{"type": "callback", "text": "📸 Анализ фото 🔒", "payload": "photo_menu"}],
        [{"type": "callback", "text": "❓ Задать вопрос", "payload": "ask"}],
        [{"type": "callback", "text": "💎 Премиум", "payload": "pay_premium"},
         {"type": "link", "text": "🆘 Поддержка", "url": SUPPORT_URL}],
        [{"type": "callback", "text": "🔄 Изменить данные", "payload": "change_data"},
         {"type": "callback", "text": "🏠 Главная", "payload": "main_menu"}],
    ]

def main_menu_buttons():
    return [
        [{"type": "callback", "text": "✨ Сегодня для нас", "payload": "today_brief"}],
        [{"type": "callback", "text": "🚨 Ребёнку плохо", "payload": "emergency"},
         {"type": "callback", "text": "🩺 К врачу", "payload": "doctor_prep"}],
        [{"type": "callback", "text": "📋 Первые дни с малышом", "payload": "firstdays"}],
        [{"type": "callback", "text": "🤱 Грудное вскармливание", "payload": "breastfeeding"}],
        [{"type": "callback", "text": "🏥 Восстановление мамы", "payload": "recovery"}],
        [{"type": "callback", "text": "📊 Развитие по возрасту", "payload": "development"},
         {"type": "callback", "text": "🎮 Игры и занятия", "payload": "games"}],
        [{"type": "callback", "text": "📚 Что читать", "payload": "books"},
         {"type": "callback", "text": "🌡 Здоровье", "payload": "health"}],
        [{"type": "callback", "text": "💊 Лекарства", "payload": "meds"},
         {"type": "callback", "text": "🦷 Зубки", "payload": "teeth"}],
        [{"type": "callback", "text": "🍼 Питание и прикорм", "payload": "food"},
         {"type": "callback", "text": "🥣 Рецепты", "payload": "recipes"}],
        [{"type": "callback", "text": "🌙 Режим дня", "payload": "routine"},
         {"type": "callback", "text": "😴 Проблемы со сном", "payload": "sleep"}],
        [{"type": "callback", "text": "😢 Истерики и капризы", "payload": "tantrums"},
         {"type": "callback", "text": "👨‍👩‍👧 Отношения в семье", "payload": "family"}],
        [{"type": "callback", "text": "🧠 Эмоции мамы", "payload": "emotions"},
         {"type": "callback", "text": "📓 Дневник малыша", "payload": "diary"}],
        [{"type": "callback", "text": "❓ Задать вопрос", "payload": "ask"}],
        [{"type": "callback", "text": "━━━ 💎 ПРЕМИУМ ━━━", "payload": "premium_info"}],
        [{"type": "callback", "text": "🧠 Мамин психолог 🔒", "payload": "psycho"},
         {"type": "callback", "text": "📸 Анализ фото 🔒", "payload": "photo_menu"}],
        [{"type": "callback", "text": "📏 Рост и вес 🔒", "payload": "growth"},
         {"type": "callback", "text": "🌡 Трекер симптомов 🔒", "payload": "symptoms"}],
        [{"type": "callback", "text": "🤱 Трекер кормлений 🔒", "payload": "feeding"},
         {"type": "callback", "text": "🌙 Дневник сна 🔒", "payload": "sleep_log"}],
        [{"type": "callback", "text": "💉 Прививки 🔒", "payload": "vaccines"},
         {"type": "callback", "text": "💰 Пособия 🔒", "payload": "benefits"}],
        [{"type": "callback", "text": "📈 Отчёт за 7 дней 🔒", "payload": "weekly_report"}],
        [{"type": "callback", "text": "💎 Оформить Премиум", "payload": "pay_premium"}],
        [{"type": "callback", "text": "⭐ Отзыв", "payload": "review"},
         {"type": "callback", "text": "🆘 Поддержка", "payload": "support_menu"}],
        [{"type": "callback", "text": "🔄 Изменить данные", "payload": "change_data"},
         {"type": "callback", "text": "🏠 Главная", "payload": "main_menu"}],
    ]
def back_button():
    return [[{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]]

def upgrade_buttons(plan="any"):
    return [
        [{"type": "callback", "text": "💎 Оформить Премиум — 299 руб/мес", "payload": "pay_premium"}],
        [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
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
    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT DEFAULT '',
        first_name TEXT DEFAULT '', review TEXT, created_at TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_diary_user_created ON diary(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_growth_user_created ON growth(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symptoms_user_created ON symptoms(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vaccinations_user ON vaccinations(user_id)")
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

def get_subscription(user_id):
    conn = db_connect(); row = conn.execute("SELECT plan, sub_end FROM subscriptions WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    if not row or not row[1]: return None, None
    try:
        sub_end = datetime.fromisoformat(row[1])
    except ValueError:
        return None, None
    return (row[0], sub_end) if sub_end > datetime.now() else (None, None)

def set_subscription(user_id, plan, days):
    current_plan, current_end = get_subscription(user_id)
    start = current_end if current_end and current_end > datetime.now() else datetime.now()
    end = (start + timedelta(days=days)).isoformat()
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO subscriptions (user_id, plan, sub_end) VALUES (?,?,?)", (user_id, plan, end))

def is_premium(user_id):
    return get_subscription(user_id)[0] == "mama_premium"

def get_limits(user_id):
    conn = db_connect()
    conn.execute("INSERT OR IGNORE INTO limits (user_id) VALUES (?)", (user_id,))
    row = conn.execute("SELECT requests, psycho_messages FROM limits WHERE user_id=?", (user_id,)).fetchone()
    conn.commit(); conn.close()
    return {"requests": row[0] if row else 0, "psycho": row[1] if row else 0}

def increment_limit(user_id, field):
    if field not in {"requests", "psycho_messages"}:
        raise ValueError("Недопустимое поле лимита")
    with db_connect() as conn:
        conn.execute("INSERT OR IGNORE INTO limits(user_id) VALUES (?)", (user_id,))
        conn.execute(f"UPDATE limits SET {field}={field}+1 WHERE user_id=?", (user_id,))

def get_request_count(user_id): return get_limits(user_id)["requests"]
def increment_request_count(user_id): increment_limit(user_id, "requests")

def get_psycho_history(user_id, limit=20):
    conn=db_connect(); rows=conn.execute("SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall(); conn.close(); return list(reversed(rows))
def add_psycho_message(user_id, role, content):
    with db_connect() as conn: conn.execute("INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)", (user_id, role, content, datetime.now().isoformat()))
def clear_psycho_history(user_id):
    with db_connect() as conn: conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
def get_diary_history(user_id, limit=5):
    conn=db_connect(); rows=conn.execute("SELECT entry, response, created_at FROM diary WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall(); conn.close(); return list(reversed(rows))
def add_diary_entry(user_id, entry, response=""):
    with db_connect() as conn: conn.execute("INSERT INTO diary (user_id, entry, response, created_at) VALUES (?,?,?,?)", (user_id, entry, response, datetime.now().isoformat()))
def save_growth(user_id, height, weight):
    with db_connect() as conn: conn.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?,?,?,?)", (user_id, height, weight, datetime.now().isoformat()))
def get_growth(user_id):
    conn=db_connect(); rows=conn.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall(); conn.close(); return rows
def save_symptom_entry(user_id, symptom):
    with db_connect() as conn: conn.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?,?,?)", (user_id, symptom, datetime.now().isoformat()))
def get_symptoms_list(user_id):
    conn=db_connect(); rows=conn.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (user_id,)).fetchall(); conn.close(); return rows
def save_pending_payment(payment_id, user_id, plan):
    with db_connect() as conn: conn.execute("INSERT OR REPLACE INTO pending_payments (payment_id, user_id, plan, created_at) VALUES (?,?,?,?)", (payment_id, user_id, plan, datetime.now().isoformat()))
def get_pending_payments():
    conn=db_connect(); rows=conn.execute("SELECT payment_id, user_id, plan FROM pending_payments").fetchall(); conn.close(); return rows
def delete_pending_payment(payment_id):
    with db_connect() as conn: conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
def save_review(user_id, username, first_name, review_text):
    with db_connect() as conn: conn.execute("INSERT INTO reviews (user_id, username, first_name, review, created_at) VALUES (?,?,?,?,?)", (user_id, username or "", first_name or "", review_text, datetime.now().isoformat()))

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
async def generate_text(system, prompt, model="gpt-4o-mini"):
    response = await openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        max_tokens=1500
    )
    return response.choices[0].message.content

async def generate_with_history(system, history, new_message):
    messages = [{"role": "system", "content": system}]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": new_message})
    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, max_tokens=1500
    )
    return response.choices[0].message.content

# ========== ОПЛАТА ==========
async def create_payment(user_id, plan):
    amount = "299.00"
    plan_name = "Премиум"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json={
                "amount": {"value": amount, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://maminpomoshnik.ru/payment/success"},
                "capture": True,
                "description": f"Мамин Помощник MAX — {plan_name} — {user_id}",
                "receipt": {"customer": {"email": "6038484@mail.ru"}, "items": [{
                    "description": f"Мамин Помощник MAX — {plan_name}, 30 дней",
                    "quantity": "1.00",
                    "amount": {"value": amount, "currency": "RUB"},
                    "vat_code": 1, "payment_subject": "service", "payment_mode": "full_payment"
                }]},
                "metadata": {"user_id": user_id, "plan": plan}
            },
            headers={"Idempotence-Key": str(uuid.uuid4()), "Content-Type": "application/json"},
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET)
        )
        if not r.is_success:
            logging.error("ЮКасса create payment: %s %s", r.status_code, r.text[:1000])
            raise RuntimeError("ЮКасса не создала платёж")
        return r.json()

# ========== ФОНОВАЯ ПРОВЕРКА ОПЛАТЫ ==========
async def check_payments_loop():
    while True:
        await asyncio.sleep(15)
        try:
            for payment_id, user_id, plan in get_pending_payments():
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.get(
                            f"https://api.yookassa.ru/v3/payments/{payment_id}",
                            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET)
                        )
                        payment = r.json()
                    if payment.get("status") == "succeeded":
                        set_subscription(user_id, plan, 30)
                        delete_pending_payment(payment_id)
                        plan_name = "💎 Премиум"
                        await send_message(user_id,
                            f"✅ Оплата прошла!\n\nТариф {plan_name} активирован на 30 дней.\n\nПользуйся на здоровье! 🔮",
                            main_menu_buttons()
                        )
                    elif payment.get("status") == "canceled":
                        delete_pending_payment(payment_id)
                        await send_message(user_id, "❌ Платёж отменён. Попробуй снова.", main_menu_buttons())
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

WELCOME_TEXT = """Привет, {name}! 🤍

Я Мамин Помощник — твой личный ИИ-ассистент для мам.

Что я умею:
🤰 Поддержка при беременности — развитие малыша, чек-листы, подготовка к родам
👶 Советы по возрасту — развитие, питание, сон, здоровье
🤱 Грудное вскармливание и восстановление после родов
🧠 Детская психология — истерики, поведение, эмоции
💊 Здоровье — симптомы, лекарства, прививки
📏 Трекеры — рост, вес, симптомы, кормления, сон
🧠 Мамин психолог — личный психолог который тебя помнит
💰 Пособия и выплаты

Все советы основаны на рекомендациях ВОЗ, AAP и ведущих педиатров мира.

Сначала укажи кто ты 👇"""

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
                [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                  {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])
        return

    # Психолог
    if step == "psycho":
        plan, _ = get_subscription(user_id)
        if plan != "mama_premium":
            set_step(user_id, "idle")
            await send_message(chat_id, "🔒 Мамин психолог доступен в Премиум 💎", upgrade_buttons())
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
        except Exception as e:
            logging.exception("Ошибка психолога: %s", e)
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
        if plan != "mama_premium" and get_request_count(user_id) >= FREE_REQUESTS:
            await send_message(chat_id, f"Использовано {FREE_REQUESTS} бесплатных вопросов. Оформи Премиум — 299 руб/мес", upgrade_buttons())
            return
        if plan != "mama_premium":
            increment_request_count(user_id)
        context = f"Ребёнку {m_label}." if months is not None else f"Беременная {m_label}." if weeks_preg else ""
        await send_message(chat_id, "⏳ Думаю...")
        answer = await generate_text(f"{EXPERT_BASE} {context}", text)
        await send_message(chat_id, answer, back_button())
        return

    # Ввод даты рождения малыша
    if step == "enter_birthdate":
        m = calc_child_age(text)
        if m is None or m < 0 or m > 216:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
            return
        conn = db_connect()
        conn.execute("UPDATE users SET birth_date=?, step='idle' WHERE user_id=?", (text, user_id))
        conn.commit()
        conn.close()
        lbl = age_label(m)
        await send_message(chat_id, f"✅ Малышу {lbl}\n\nЧем могу помочь? 💕", main_menu_buttons())
        return

    # Ввод ПДР
    if step == "enter_pdr":
        w = calc_pregnancy_weeks(text)
        if w is None or w < 0 or w > 42:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
            return
        conn = db_connect()
        conn.execute("UPDATE users SET birth_date=?, step='idle' WHERE user_id=?", (f"pdr:{text}", user_id))
        conn.commit()
        conn.close()
        await send_message(chat_id, f"✅ Ты на {w} неделе беременности\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
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
        set_step(user_id, "idle")
        try:
            await send_message(OWNER_ID, f"🆘 Поддержка Мамин Помощник MAX\n\nПользователь: {first_name or 'без имени'}\nID: {user_id}\nUsername: {username or 'нет'}\n\n{text}")
        except Exception as exc:
            logging.error("Не удалось переслать обращение владельцу: %s", exc)
        save_review(user_id, username, first_name, f"ПОДДЕРЖКА: {text}")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, f"ПОДДЕРЖКА: {text}"))
        await send_message(chat_id, f"✅ Обращение принято. Мы ответим при первой возможности.\n\nТакже можно написать напрямую: {SUPPORT_URL}", main_menu_buttons())
        return

    # Если режим не выбран
    if not birth_date:
        await send_message(chat_id, WELCOME_TEXT.format(name=name),
            [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
              {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])
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

    if callback_requires_premium(payload) and plan != "mama_premium":
        await send_message(chat_id, "🔒 Этот раздел доступен в Премиум 💎", upgrade_buttons())
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
                [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                  {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])
        return

    if payload == "main_menu":
        set_step(user_id, "idle")
        if birth_date.startswith("pdr:"):
            await send_message(chat_id, f"🤰 Ты {m_label}\n\nЧем могу помочь? 💕", pregnant_menu_buttons())
        elif birth_date:
            await send_message(chat_id, f"Чем могу помочь? 💕", main_menu_buttons())
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                  {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])
        return

    if payload == "change_data":
        # Reset birth_date so user can choose again
        conn = db_connect()
        conn.execute("UPDATE users SET birth_date='', step='idle' WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await send_message(chat_id, "Выбери свой статус 👇",
            [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
              {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]])
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
        if plan != "mama_premium" and get_request_count(user_id) >= FREE_REQUESTS:
            await send_message(chat_id, f"Использовано {FREE_REQUESTS} бесплатных вопросов. Оформи Премиум — 299 руб/мес", upgrade_buttons())
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Мамин психолог доступен в Премиум 💎\n\nПерсональный психолог который тебя помнит.", upgrade_buttons())
            return
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Анализ фото доступен в Премиум 💎", upgrade_buttons())
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Трекер роста и веса доступен в Премиум 💎", upgrade_buttons())
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Трекер симптомов доступен в Премиум 💎", upgrade_buttons())
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Трекер кормлений доступен в Премиум 💎", upgrade_buttons())
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
        return

    for feed_type in ["feed_left", "feed_right", "feed_bottle"]:
        if payload == feed_type:
            names = {"feed_left": "Левая грудь", "feed_right": "Правая грудь", "feed_bottle": "Смесь/бутылочка"}
            set_step(user_id, f"feed_duration_{feed_type}")
            await send_message(chat_id, f"⏱ Сколько минут кормила? ({names[feed_type]})\nВведи число:")
            return

    if payload == "sleep_log":
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Дневник сна доступен в Премиум 💎", upgrade_buttons())
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
        return

    if payload == "sleep_start":
        conn = db_connect()
        conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                     (user_id, "СОН:уснул", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await send_message(chat_id, "😴 Записала — малыш уснул!", back_button())
        return

    if payload == "sleep_end":
        conn = db_connect()
        conn.execute("INSERT INTO diary (user_id, entry, created_at) VALUES (?,?,?)",
                     (user_id, "СОН:проснулся", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        await send_message(chat_id, "🌅 Записала — малыш проснулся!", back_button())
        return

    if payload == "vaccines":
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Прививочный календарь доступен в Премиум 💎", upgrade_buttons())
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
        if plan != "mama_premium":
            await send_message(chat_id, "🔒 Пособия и выплаты доступны в Премиум 💎", upgrade_buttons())
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

    if payload == "pay_premium" or payload == "premium_info":
        try:
            payment = await create_payment(user_id, "mama_premium")
            pay_url = payment.get("confirmation", {}).get("confirmation_url", "")
            payment_id = payment.get("id", "")
            if not pay_url or not payment_id:
                logging.error("ЮКасса вернула ответ без ссылки или id: %s", payment)
                await send_message(chat_id, f"Не удалось создать платёж. Напиши в поддержку: {SUPPORT_URL}", back_button())
                return
            if pay_url and payment_id:
                save_pending_payment(payment_id, user_id, "mama_premium")
                await send_message(chat_id,
                    "💎 Премиум подписка — 299 руб/месяц\n\n"
                    "Что открывается:\n"
                    "🧠 Мамин психолог с историей\n"
                    "📸 Анализ фото\n"
                    "📏 Трекер роста и веса\n"
                    "🌡 Трекер симптомов\n"
                    "🤱 Трекер кормлений\n"
                    "🌙 Дневник сна\n"
                    "💉 Прививки\n"
                    "💰 Пособия\n"
                    "🩺 Сводка для педиатра\n"
                    "📈 Персональный отчёт за 7 дней\n"
                    "❓ Безлимитные вопросы\n\n"
                    "После оплаты активируется автоматически!",
                    [[{"type": "link", "text": "💳 Оплатить 299 руб", "url": pay_url}],
                     [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]]
                )
        except Exception as e:
            logging.error(f"Payment error: {e}")
            await send_message(chat_id, f"Ошибка платежа. Напиши в поддержку: {SUPPORT_URL}", back_button())
        return

    await send_message(chat_id, "Выбери действие из меню 👇", main_menu_buttons())


async def process_photo(chat_id, user_id, photo_url):
    if not is_premium(user_id):
        await send_message(chat_id, "🔒 Анализ фото доступен в Премиум 💎", upgrade_buttons())
        return

    user = get_user(user_id)
    step = user.get("step", "")
    type_map = {
        "photo_skin": "skin", "photo_food": "food", "photo_package": "package",
        "photo_stool": "stool", "photo_analysis": "analysis", "photo_uzi": "uzi",
        "photo_med_preg": "med_preg"
    }
    photo_type = type_map.get(step)
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
    except Exception as exc:
        logging.exception("Photo error: %s", exc)
        await send_message(chat_id, "Не удалось проанализировать фото. Попробуй более чёткое изображение.", back_button())


# ========== АВТОПОСТИНГ В КАНАЛ ==========
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
    8:  ("🌅 Доброе утро, мама", "Заряд на день — мотивация, поддержка. 100-150 слов."),
    10: ("🔬 Научный факт дня", "Интересный факт о детях по ВОЗ или AAP. 150-200 слов."),
    13: ("💡 Совет педиатра", "Практический совет по ВОЗ/AAP. 200-250 слов."),
    16: ("🧠 Детская психология", "Объяснение поведения ребёнка по Петрановской/Сигелу. 200-250 слов."),
    20: ("❤️ Для мамы", "О восстановлении, выгорании. Тепло. 150-200 слов."),
}

async def send_to_channel(text):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"text": text[:4000]}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{MAX_API}/messages?chat_id={CHANNEL_ID}", json=payload, headers=headers)
        logging.info(f"Channel post: {r.status_code}")

async def channel_posting_loop():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler as _APScheduler
    scheduler = _APScheduler(timezone="Europe/Moscow")
    for hour, (rubric_name, rubric_instruction) in RUBRICS.items():
        async def post_job(h=hour, rn=rubric_name, ri=rubric_instruction):
            weekday = datetime.now(ZoneInfo("Europe/Moscow")).weekday()
            daily_theme = DAILY_THEMES[weekday]
            post = await generate_text(
                "Ты автор экспертного канала 'Я МАМА' в MAX. Пишешь на основе ВОЗ, AAP, Петрановской. Тепло и научно. В конце — практический совет.",
                f"Рубрика: {rn}\nТема: {daily_theme}\nИнструкция: {ri}\nНачни с эмодзи рубрики и её названия."
            )
            await send_to_channel(post)
        scheduler.add_job(post_job, "cron", hour=hour, minute=0, id=f"mama_channel_{hour}", replace_existing=True, coalesce=True, misfire_grace_time=1800, max_instances=1)
    scheduler.start()
    while True:
        await asyncio.sleep(3600)


# ========== FASTAPI WEBHOOK ==========
WEBHOOK_URL = "https://maminpomoshnik.ru/webhook"

app = FastAPI()

@app.on_event("startup")
async def startup():
    init_db()
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{MAX_API}/subscriptions",
                json={"url": WEBHOOK_URL}, headers=headers)
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
            chat_id = user.get("user_id")
            user_id = chat_id
            # Игнорируем если это канал
            if not user_id or user_id == CHANNEL_ID:
                return JSONResponse({"ok": True})
            first_name = user.get("name", "мама")
            username = user.get("username", "")
            get_user(user_id, username, first_name)
            set_step(user_id, "idle")
            plan, _ = get_subscription(user_id)
            asyncio.create_task(asyncio.to_thread(sheets_log_visit, user_id, first_name, username, plan))
            await send_message(chat_id, WELCOME_TEXT.format(name=first_name),
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
    config = uvicorn.Config(app, host="0.0.0.0", port=8082, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
