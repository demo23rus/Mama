import asyncio
import sqlite3
import logging
import uuid
import httpx
import base64
import threading
from datetime import datetime, timedelta
from openai import AsyncOpenAI
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from yookassa import Configuration, Payment
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)

# ─── НАСТРОЙКИ ───────────────────────────────────────────────
MAX_TOKEN        = "f9LHodD0cOIWTyPeJTIKgqKDGe8OGcGqK1BXLiPyMJqGIi1-CZR29YAPZgDbbUpDfwQXKDJovDVJ3HN_88XV"
OPENAI_KEY       = "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"
WEBHOOK_URL      = "https://maminpomoshnik.ru/webhook"
SUPPORT_URL      = "https://t.me/demo23rus"
BOT_NAME         = "Мамин Помощник MAX"

YOOKASSA_SHOP_ID = "1363324"
YOOKASSA_SECRET  = "live_-RKE9nsi8wZiM-5f00z78E84OYSi3M0Dj9w_-pE0Mvw"
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key  = YOOKASSA_SECRET

SPREADSHEET_ID   = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
CREDENTIALS_FILE = "/root/google_credentials.json"

MAX_API          = "https://botapi.max.ru"
DB_PATH          = "/root/mama_max.db"
FREE_REQUESTS    = 10

client = AsyncOpenAI(api_key=OPENAI_KEY)
app = FastAPI()

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, name TEXT,
        mode TEXT DEFAULT '',
        date_value TEXT DEFAULT '',
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        plan TEXT DEFAULT '',
        sub_end TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        payment_id TEXT PRIMARY KEY,
        user_id INTEGER, plan TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests_count (
        user_id INTEGER PRIMARY KEY,
        count INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS steps (
        user_id INTEGER PRIMARY KEY,
        step TEXT DEFAULT 'idle',
        data TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS psycho_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, role TEXT, content TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS growth (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, height REAL, weight REAL, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS symptoms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, symptom TEXT, created_at TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id, username="", name=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, mode, date_value FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.execute("INSERT INTO users (user_id, username, name, created_at) VALUES (?,?,?,?)",
                     (user_id, username, name, datetime.now().isoformat()))
        conn.commit()
    conn.close()
    return row

def set_step(user_id, step, data=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO steps (user_id, step, data) VALUES (?,?,?)",
                 (user_id, step, data))
    conn.commit()
    conn.close()

def get_step(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT step, data FROM steps WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else ("idle", "")

def save_user_mode(user_id, mode, date_value):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET mode=?, date_value=? WHERE user_id=?",
                 (mode, date_value, user_id))
    conn.commit()
    conn.close()

def get_subscription(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT plan, sub_end FROM subscriptions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row if row else ("", None)

def set_subscription(user_id, plan, days):
    end = (datetime.now() + timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT count FROM requests_count WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_requests(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO requests_count (user_id, count) VALUES (?, COALESCE((SELECT count FROM requests_count WHERE user_id=?), 0) + 1)",
                 (user_id, user_id))
    conn.commit()
    conn.close()

def save_pending_payment(payment_id, user_id, plan):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO pending_payments (payment_id, user_id, plan, created_at) VALUES (?,?,?,?)",
                 (payment_id, user_id, plan, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT payment_id, user_id, plan FROM pending_payments")
    rows = c.fetchall()
    conn.close()
    return rows

def delete_pending_payment(payment_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
    conn.commit()
    conn.close()

def save_psycho(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                 (user_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_psycho_history(user_id, limit=15):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def clear_psycho(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def save_growth(user_id, height, weight):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?,?,?,?)",
                 (user_id, height, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_growth(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
              (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_symptom(user_id, symptom):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?,?,?)",
                 (user_id, symptom, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_symptoms(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
              (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ─── GOOGLE SHEETS ───────────────────────────────────────────
def sheets_log_visit(user_id, name, username, plan=""):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client_gs = gspread.authorize(creds)
        spreadsheet = client_gs.open_by_key(SPREADSHEET_ID)
        try:
            sheet = spreadsheet.worksheet("МамаБот MAX")
        except:
            sheet = spreadsheet.add_worksheet(title="МамаБот MAX", rows=1000, cols=8)
            sheet.append_row(["ID", "Username", "Имя", "Подписка", "Дата"])
        data = sheet.get_all_values()
        ids = [row[0] for row in data[1:]]
        if str(user_id) not in ids:
            sheet.append_row([str(user_id), username or "", name or "",
                              plan or "Бесплатно", datetime.now().strftime("%d.%m.%Y %H:%M")])
    except Exception as e:
        logging.error(f"Sheets error: {e}")

def sheets_add_review(user_id, username, text):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client_gs = gspread.authorize(creds)
        spreadsheet = client_gs.open_by_key(SPREADSHEET_ID)
        try:
            sheet = spreadsheet.worksheet("Отзывы МамаБот MAX")
        except:
            sheet = spreadsheet.add_worksheet(title="Отзывы МамаБот MAX", rows=1000, cols=4)
            sheet.append_row(["ID", "Username", "Текст", "Дата"])
        sheet.append_row([str(user_id), username or "", text,
                         datetime.now().strftime("%d.%m.%Y %H:%M")])
    except Exception as e:
        logging.error(f"Sheets review error: {e}")

# ─── MAX API ─────────────────────────────────────────────────
async def send_message(chat_id, text, buttons=None):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"recipient": {"chat_id": chat_id}, "type": "bot_action",
               "action": "send_message",
               "body": {"type": "text", "text": text[:4000]}}
    if buttons:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    async with httpx.AsyncClient() as c:
        try:
            r = await c.post(f"{MAX_API}/messages", headers=headers, json=payload, timeout=15)
            logging.info(f"send_message {chat_id}: {r.status_code}")
        except Exception as e:
            logging.error(f"send_message error: {e}")

async def answer_callback(callback_id):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as c:
        try:
            await c.post(f"{MAX_API}/answers/{callback_id}", headers=headers,
                        json={"type": "callback"}, timeout=10)
        except Exception as e:
            logging.error(f"answer_callback error: {e}")

async def register_webhook():
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"url": WEBHOOK_URL, "update_types": [
        "bot_started", "message_created", "bot_action"
    ]}
    async with httpx.AsyncClient() as c:
        try:
            r = await c.post(f"{MAX_API}/subscriptions", headers=headers, json=payload, timeout=15)
            logging.info(f"Webhook registered: {r.status_code} {r.text}")
        except Exception as e:
            logging.error(f"Webhook error: {e}")

# ─── КНОПКИ ──────────────────────────────────────────────────
def main_menu_buttons():
    return [
        [{"type": "callback", "text": "📋 Первые дни", "payload": "firstdays"},
         {"type": "callback", "text": "🤱 Грудное ВС", "payload": "breastfeeding"}],
        [{"type": "callback", "text": "🏥 Восстановление", "payload": "recovery"},
         {"type": "callback", "text": "📊 Развитие", "payload": "development"}],
        [{"type": "callback", "text": "🌡 Здоровье", "payload": "health"},
         {"type": "callback", "text": "🍼 Питание", "payload": "food"}],
        [{"type": "callback", "text": "🌙 Режим дня", "payload": "routine"},
         {"type": "callback", "text": "😴 Сон", "payload": "sleep"}],
        [{"type": "callback", "text": "😢 Истерики", "payload": "tantrums"},
         {"type": "callback", "text": "🧠 Эмоции мамы", "payload": "emotions"}],
        [{"type": "callback", "text": "❓ Задать вопрос", "payload": "ask"}],
        [{"type": "callback", "text": "━━━ 💎 ПРЕМИУМ ━━━", "payload": "premium_info"}],
        [{"type": "callback", "text": "🧠 Мамин психолог 🔒", "payload": "psycho"},
         {"type": "callback", "text": "📸 Анализ фото 🔒", "payload": "photo_menu"}],
        [{"type": "callback", "text": "📏 Рост и вес 🔒", "payload": "growth"},
         {"type": "callback", "text": "🌡 Трекер симптомов 🔒", "payload": "symptoms"}],
        [{"type": "callback", "text": "💉 Прививки 🔒", "payload": "vaccines"},
         {"type": "callback", "text": "💰 Пособия 🔒", "payload": "benefits"}],
        [{"type": "callback", "text": "💎 Оформить Премиум", "payload": "pay_premium"}],
        [{"type": "callback", "text": "⭐ Отзыв", "payload": "review"},
         {"type": "link", "text": "🆘 Поддержка", "url": SUPPORT_URL}],
    ]

def back_button():
    return [[{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]]

def premium_button():
    return [
        [{"type": "callback", "text": "💎 Оформить Премиум — 299 руб/мес", "payload": "pay_premium"}],
        [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
    ]

def psycho_buttons():
    return [
        [{"type": "callback", "text": "🗑 Новый диалог", "payload": "psycho_clear"},
         {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
    ]

# ─── GPT ─────────────────────────────────────────────────────
EXPERT_BASE = (
    "Ты эксперт в детской педиатрии, психологии развития и нейронауке. "
    "Опирайся на рекомендации ВОЗ, AAP, труды Петрановской, Карпа, Серза, Пиаже, Выготского. "
    "Отвечай развёрнуто, структурированно, тепло и понятно для мамы. "
    "При симптомах здоровья рекомендуй консультацию педиатра."
)

PSYCHO_SYSTEM = (
    "Ты Мамин психолог — тёплый, внимательный, профессиональный психолог для мам. "
    "Помнишь всё что мама рассказывала. Отвечаешь как живой человек — с теплом, без шаблонов. "
    "Опираешься на КПТ, ACT, нарративную терапию, теорию привязанности Петрановской. "
    "Никогда не осуждаешь. Сначала слушаешь, потом помогаешь."
)

async def ask_gpt(system, prompt, max_tokens=1500):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )
        text = response.choices[0].message.content
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = text.replace("###", "").replace("##", "").replace("# ", "")
        return text.strip()
    except Exception as e:
        return f"Ошибка GPT: {e}"

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────
def calc_child_age(birth_str):
    try:
        from datetime import date
        birth = datetime.strptime(birth_str, "%d.%m.%Y").date()
        today = date.today()
        months = (today.year - birth.year) * 12 + (today.month - birth.month)
        return months
    except:
        return None

def calc_pregnancy_weeks(pdr_str):
    try:
        from datetime import date, timedelta
        pdr = datetime.strptime(pdr_str, "%d.%m.%Y").date()
        conception = pdr - timedelta(days=280)
        today = date.today()
        days = (today - conception).days
        return days // 7
    except:
        return None

def age_label(months):
    if months is None:
        return "неизвестного возраста"
    if months < 1:
        return "новорождённый"
    elif months < 12:
        return f"{months} мес."
    else:
        years = months // 12
        m = months % 12
        return f"{years} г. {m} мес." if m else f"{years} г."

# ─── ЮКАССА ──────────────────────────────────────────────────
async def create_payment(user_id):
    payment = Payment.create({
        "amount": {"value": "299.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://maminpomoshnik.ru/payment/success"},
        "capture": True,
        "description": f"Мамин Помощник Премиум 30 дней — {user_id}",
        "receipt": {
            "customer": {"email": "client@maminpomoshnik.ru"},
            "items": [{"description": "Мамин Помощник Премиум 30 дней",
                       "quantity": "1.00",
                       "amount": {"value": "299.00", "currency": "RUB"},
                       "vat_code": 1, "payment_subject": "service",
                       "payment_mode": "full_payment"}]
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
                        threading.Thread(target=sheets_log_visit,
                                        args=(user_id, "", "", "💎 Премиум")).start()
                        await send_message(user_id,
                            "✅ Оплата прошла!\n\n"
                            "💎 Премиум активирован на 30 дней.\n\n"
                            "Все функции разблокированы — пользуйся на здоровье! 🤍",
                            main_menu_buttons()
                        )
                    elif payment.status == "canceled":
                        delete_pending_payment(payment_id)
                except Exception as e:
                    logging.error(f"Payment check error {payment_id}: {e}")
        except Exception as e:
            logging.error(f"Payments loop error: {e}")

# ─── ОБРАБОТКА СООБЩЕНИЙ ─────────────────────────────────────
async def handle_message(user_id, text, username="", name=""):
    step, step_data = get_step(user_id)

    # Психолог — диалог
    if step == "psycho_session":
        if not is_premium(user_id):
            set_step(user_id, "idle")
            await send_message(user_id, "🔒 Мамин психолог доступен в Премиум 💎", premium_button())
            return
        save_psycho(user_id, "user", text)
        history = get_psycho_history(user_id)
        user_row = get_user(user_id)
        context = ""
        if user_row and user_row[1] and user_row[2]:
            mode, date_value = user_row[1], user_row[2]
            if mode == "pregnant":
                weeks = calc_pregnancy_weeks(date_value)
                context = f"Беременная на {weeks} неделе."
            elif mode == "mama":
                months = calc_child_age(date_value)
                context = f"Мама, ребёнку {age_label(months)}."
        messages = [{"role": "system", "content": PSYCHO_SYSTEM + (f" {context}" if context else "")}]
        for role, content in history[:-1]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": text})
        await send_message(user_id, "🧠 Думаю...")
        try:
            response = await client.chat.completions.create(
                model="gpt-4o", messages=messages, max_tokens=800)
            answer = response.choices[0].message.content.replace("**", "").strip()
            save_psycho(user_id, "assistant", answer)
            await send_message(user_id, answer, psycho_buttons())
        except Exception as e:
            await send_message(user_id, "Что-то пошло не так. Попробуй ещё раз 💕")
        return

    # Вопрос к GPT
    if step == "ask_question":
        set_step(user_id, "idle")
        if not is_premium(user_id):
            count = get_request_count(user_id)
            if count >= FREE_REQUESTS:
                await send_message(user_id,
                    f"❓ Ты использовала {FREE_REQUESTS} бесплатных вопросов\n\n"
                    "Для продолжения оформи Премиум — 299 руб/месяц",
                    premium_button()
                )
                return
            increment_requests(user_id)
        user_row = get_user(user_id)
        context = ""
        if user_row and user_row[1] and user_row[2]:
            mode, date_value = user_row[1], user_row[2]
            if mode == "pregnant":
                weeks = calc_pregnancy_weeks(date_value)
                context = f"Беременная на {weeks} неделе."
            elif mode == "mama":
                months = calc_child_age(date_value)
                context = f"Мама, ребёнку {age_label(months)}."
        await send_message(user_id, "⏳ Думаю над ответом...")
        answer = await ask_gpt(
            f"{EXPERT_BASE} {context}",
            text
        )
        await send_message(user_id, answer, back_button())
        return

    # Ввод даты рождения малыша
    if step == "enter_birthdate":
        months = calc_child_age(text)
        if months is None or months < 0 or months > 216:
            await send_message(user_id, "❌ Неверный формат. Введи дату: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
            return
        save_user_mode(user_id, "mama", text)
        set_step(user_id, "idle")
        await send_message(user_id,
            f"✅ Сохранила!\n\nМалышу {age_label(months)}\n\nЧем могу помочь? 💕",
            main_menu_buttons()
        )
        return

    # Ввод ПДР
    if step == "enter_pdr":
        weeks = calc_pregnancy_weeks(text)
        if weeks is None or weeks < 0 or weeks > 42:
            await send_message(user_id, "❌ Неверный формат. Введи дату: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
            return
        save_user_mode(user_id, "pregnant", text)
        set_step(user_id, "idle")
        await send_message(user_id,
            f"✅ Сохранила!\n\nТы на {weeks} неделе беременности\n\nЧем могу помочь? 💕",
            main_menu_buttons()
        )
        return

    # Ввод роста
    if step == "enter_height":
        try:
            h = float(text.replace(",", "."))
            set_step(user_id, "enter_weight", str(h))
            await send_message(user_id, "⚖️ Теперь введи вес в килограммах\nНапример: 7.2")
        except:
            await send_message(user_id, "❌ Введи число, например: 67.5")
        return

    if step == "enter_weight":
        try:
            w = float(text.replace(",", "."))
            h = float(step_data)
            save_growth(user_id, h, w)
            user_row = get_user(user_id)
            months = None
            if user_row and user_row[2]:
                months = calc_child_age(user_row[2])
            set_step(user_id, "idle")
            await send_message(user_id, "⏳ Анализирую...")
            answer = await ask_gpt(
                EXPERT_BASE,
                f"Ребёнку {age_label(months)}. Рост {h} см, вес {w} кг. "
                f"Оцени по нормам ВОЗ — в каком перцентиле, норма или нет."
            )
            await send_message(user_id, f"📏 Рост и вес\n\n{answer}", back_button())
        except:
            await send_message(user_id, "❌ Введи число, например: 7.2")
        return

    # Ввод симптома
    if step == "enter_symptom":
        save_symptom(user_id, text)
        set_step(user_id, "idle")
        await send_message(user_id, "✅ Симптом записан!", back_button())
        return

    # Ввод отзыва
    if step == "enter_review":
        threading.Thread(target=sheets_add_review, args=(user_id, username, text)).start()
        set_step(user_id, "idle")
        await send_message(user_id, "⭐ Спасибо за отзыв! 💕", main_menu_buttons())
        return

    # По умолчанию
    await send_message(user_id, "Выбери действие из меню 👇", main_menu_buttons())

# ─── ОБРАБОТКА КНОПОК ────────────────────────────────────────
async def handle_callback(user_id, payload, username="", name=""):
    user_row = get_user(user_id)
    mode = user_row[1] if user_row else ""
    date_value = user_row[2] if user_row else ""

    months = calc_child_age(date_value) if mode == "mama" and date_value else None
    weeks = calc_pregnancy_weeks(date_value) if mode == "pregnant" and date_value else None

    # Меню
    if payload == "back_menu":
        set_step(user_id, "idle")
        if mode == "mama" and months is not None:
            await send_message(user_id, f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?", main_menu_buttons())
        elif mode == "pregnant" and weeks:
            await send_message(user_id, f"🤰 Ты на {weeks} неделе беременности\n\nЧем могу помочь?", main_menu_buttons())
        else:
            await send_message(user_id, "Чем могу помочь? 💕", main_menu_buttons())
        return

    # Настройка профиля
    if payload == "set_mama":
        set_step(user_id, "enter_birthdate")
        await send_message(user_id, "👶 Введи дату рождения малыша\n\nФормат: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
        return

    if payload == "set_pregnant":
        set_step(user_id, "enter_pdr")
        await send_message(user_id, "🤰 Введи предполагаемую дату родов (ПДР)\n\nФормат: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
        return

    # Информационные разделы
    info_sections = {
        "firstdays": ("📋 Первые дни с малышом", "Расскажи о первых днях после рождения малыша: первый осмотр педиатра, оформление документов (свидетельство о рождении, ОМС, СНИЛС), массаж с 1 месяца, плавание. Подробно и практично."),
        "breastfeeding": ("🤱 Грудное вскармливание", "Расскажи о грудном вскармливании: как наладить с первых дней по ВОЗ, правильный захват, позиции, как понять что молока хватает, лактостаз и как с ним справляться."),
        "recovery": ("🏥 Восстановление мамы", "Расскажи о восстановлении после родов: естественные роды и КС — разница, швы, послеродовые выделения, упражнения Кегеля, диастаз, когда можно заниматься спортом."),
        "development": ("📊 Развитие малыша", f"Расскажи о развитии ребёнка {age_label(months)} ({months} месяцев) по стандартам AAP и ВОЗ: физическое, речевое, когнитивное, социальное развитие. Нормы и на что обратить внимание." if months else "Сначала укажи возраст малыша в профиле."),
        "health": ("🌡 Здоровье", f"Расскажи о типичных проблемах со здоровьем у ребёнка {age_label(months)} по стандартам AAP: температура, ОРВИ, колики. Когда срочно к врачу." if months else "Сначала укажи возраст малыша."),
        "food": ("🍼 Питание и прикорм", f"Расскажи о питании ребёнка {age_label(months)} по протоколам ВОЗ и ESPGHAN: что вводить, что нельзя, размер порций." if months else "Сначала укажи возраст малыша."),
        "routine": ("🌙 Режим дня", f"Составь научно обоснованный режим дня для ребёнка {age_label(months)} по хронобиологии и рекомендациям AAP." if months else "Сначала укажи возраст малыша."),
        "sleep": ("😴 Проблемы со сном", f"Расскажи о сне ребёнка {age_label(months)} — нормы, методы улучшения, безопасная среда сна по AAP." if months else "Сначала укажи возраст малыша."),
        "tantrums": ("😢 Истерики и капризы", f"Объясни поведение ребёнка {age_label(months)} с нейронаучной точки зрения по Петрановской и Сигелу. Как реагировать маме." if months else "Сначала укажи возраст малыша."),
        "emotions": ("🧠 Эмоции мамы", "Расскажи о послеродовой депрессии, беби-блюзе, материнском выгорании по DSM-5 и ВОЗ. Как распознать и что делать. Тепло и без осуждения."),
    }

    if payload in info_sections:
        title, prompt = info_sections[payload]
        await send_message(user_id, "⏳ Подбираю информацию...")
        answer = await ask_gpt(EXPERT_BASE, prompt)
        await send_message(user_id, f"{title}\n\n{answer}", back_button())
        return

    # Задать вопрос
    if payload == "ask":
        if not is_premium(user_id) and get_request_count(user_id) >= FREE_REQUESTS:
            await send_message(user_id,
                f"❓ Ты использовала {FREE_REQUESTS} бесплатных вопросов\n\n"
                "Оформи Премиум для безлимитных вопросов — 299 руб/мес",
                premium_button()
            )
            return
        set_step(user_id, "ask_question")
        await send_message(user_id, "❓ Напиши свой вопрос о малыше, беременности или воспитании 💕")
        return

    # Премиум разделы
    premium_sections = ["psycho", "photo_menu", "growth", "symptoms", "vaccines", "benefits"]
    if payload in premium_sections and not is_premium(user_id):
        names = {
            "psycho": "Мамин психолог",
            "photo_menu": "Анализ фото",
            "growth": "Трекер роста и веса",
            "symptoms": "Трекер симптомов",
            "vaccines": "Прививочный календарь",
            "benefits": "Пособия и выплаты"
        }
        await send_message(user_id,
            f"🔒 {names.get(payload, 'Эта функция')} доступна в Премиум 💎\n\n"
            "299 руб/месяц — все функции без ограничений",
            premium_button()
        )
        return

    # Психолог
    if payload == "psycho":
        history = get_psycho_history(user_id)
        set_step(user_id, "psycho_session")
        if history:
            await send_message(user_id,
                "🧠 С возвращением! Я помню наш разговор.\n\nКак ты сейчас? 💕",
                psycho_buttons()
            )
        else:
            await send_message(user_id,
                "🧠 Привет! Я твой личный психолог 💕\n\n"
                "Здесь можно говорить обо всём — усталость, тревога, отношения, "
                "чувство вины. Я слушаю.\n\nКак ты сейчас?",
                psycho_buttons()
            )
        return

    if payload == "psycho_clear":
        clear_psycho(user_id)
        set_step(user_id, "psycho_session")
        await send_message(user_id, "🧠 Начинаем с чистого листа 💕\n\nКак ты сейчас?", psycho_buttons())
        return

    # Фото меню
    if payload == "photo_menu":
        buttons = [
            [{"type": "callback", "text": "🔴 Сыпь и кожа", "payload": "photo_skin"},
             {"type": "callback", "text": "🍽 Еда малыша", "payload": "photo_food"}],
            [{"type": "callback", "text": "💊 Упаковка смеси", "payload": "photo_package"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(user_id,
            "📸 Анализ фото\n\nВыбери тип фото и отправь изображение 👇",
            buttons
        )
        return

    if payload in ["photo_skin", "photo_food", "photo_package"]:
        prompts = {
            "photo_skin": "Жду фото кожи или сыпи малыша 📸",
            "photo_food": "Жду фото еды или блюда 📸",
            "photo_package": "Жду фото упаковки смеси или лекарства 📸"
        }
        set_step(user_id, f"waiting_photo_{payload}")
        await send_message(user_id, prompts[payload] + "\n\n⚠️ Это ориентир, не диагноз.")
        return

    # Рост и вес
    if payload == "growth":
        entries = get_growth(user_id)
        set_step(user_id, "enter_height")
        text = "📏 Рост и вес малыша\n\n"
        if entries:
            for h, w, dt in entries[:3]:
                d = datetime.fromisoformat(dt).strftime("%d.%m.%Y")
                text += f"📅 {d} — {h} см, {w} кг\n"
            text += "\n"
        text += "Введи рост малыша в сантиметрах\nНапример: 67.5"
        await send_message(user_id, text)
        return

    # Трекер симптомов
    if payload == "symptoms":
        entries = get_symptoms(user_id)
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
            text += "Записей нет. Фиксируй симптомы чтобы отслеживать динамику."
        await send_message(user_id, text, buttons)
        return

    if payload == "symptom_add":
        set_step(user_id, "enter_symptom")
        await send_message(user_id, "🌡 Опиши симптом малыша\n\nНапример: температура 38.2, кашель, сыпь на щеках")
        return

    if payload == "symptom_analyze":
        entries = get_symptoms(user_id)
        if not entries:
            await send_message(user_id, "Нет симптомов для анализа.", back_button())
            return
        await send_message(user_id, "⏳ Анализирую симптомы...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {s}" for s, dt in entries])
        answer = await ask_gpt(
            EXPERT_BASE,
            f"Ребёнку {age_label(months)}. Симптомы за последние дни:\n{data_str}\n\n"
            f"Проанализируй: что это может быть, динамика лучше или хуже, стоит ли к врачу."
        )
        await send_message(user_id, answer, back_button())
        return

    # Прививки
    if payload == "vaccines":
        await send_message(user_id, "⏳ Подбираю информацию о прививках...")
        answer = await ask_gpt(
            EXPERT_BASE,
            "Расскажи о национальном календаре прививок в России для детей до 2 лет. "
            "БЦЖ, Гепатит B, АКДС, Полиомиелит, Пневмококк, КПК, Ветрянка — "
            "когда делают, зачем, как подготовить ребёнка, нормальные реакции."
        )
        await send_message(user_id, f"💉 Прививочный календарь\n\n{answer}", back_button())
        return

    # Пособия
    if payload == "benefits":
        buttons = [
            [{"type": "callback", "text": "👶 При рождении", "payload": "ben_birth"},
             {"type": "callback", "text": "🤱 До 1.5 лет", "payload": "ben_15"}],
            [{"type": "callback", "text": "📅 До 3 лет", "payload": "ben_3"},
             {"type": "callback", "text": "🏠 Маткапитал", "payload": "ben_matcap"}],
            [{"type": "callback", "text": "❓ Что положено мне", "payload": "ben_personal"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(user_id, "💰 Пособия и выплаты\n\nВыбери раздел 👇", buttons)
        return

    ben_prompts = {
        "ben_birth": "Расскажи о единовременном пособии при рождении ребёнка в России 2024-2025. Размер, документы, куда обращаться.",
        "ben_15": "Расскажи о пособии по уходу до 1.5 лет в России 2024-2025. Размер для работающих и неработающих, как рассчитать.",
        "ben_3": "Расскажи о выплатах на ребёнка от 1.5 до 3 лет в России 2024-2025. Путинские выплаты, условия.",
        "ben_matcap": "Расскажи о материнском капитале в России 2024-2025. Размер, на что потратить, как оформить.",
    }
    if payload in ben_prompts:
        await send_message(user_id, "⏳ Подбираю информацию...")
        answer = await ask_gpt(
            "Ты эксперт по социальным выплатам в России 2024-2025. Давай конкретную информацию.",
            ben_prompts[payload]
        )
        await send_message(user_id, answer, back_button())
        return

    if payload == "ben_personal":
        set_step(user_id, "ask_question")
        await send_message(user_id,
            "❓ Расскажи о своей ситуации:\n\n"
            "Работаешь или нет, какой по счёту ребёнок, замужем или нет, регион.\n\n"
            "Например: работаю официально, второй ребёнок, замужем, Москва"
        )
        return

    # Премиум инфо
    if payload in ["premium_info", "pay_premium"]:
        try:
            payment = await create_payment(user_id)
            save_pending_payment(payment.id, user_id, "mama_premium")
            buttons = [
                [{"type": "link", "text": "💳 Оплатить 299 руб", "url": payment.confirmation.confirmation_url}],
                [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
            ]
            await send_message(user_id,
                "💎 Премиум подписка — 299 руб/месяц\n\n"
                "Что открывается:\n"
                "🧠 Мамин психолог с историей диалогов\n"
                "📸 Анализ фото (сыпь, еда, упаковка)\n"
                "📏 Трекер роста и веса\n"
                "🌡 Трекер симптомов\n"
                "💉 Прививочный календарь\n"
                "💰 Подбор пособий\n"
                "❓ Безлимитные вопросы GPT\n\n"
                "После оплаты всё активируется автоматически!",
                buttons
            )
        except Exception as e:
            logging.error(f"Payment error: {e}")
            await send_message(user_id, f"Ошибка платежа. Напиши в поддержку: {SUPPORT_URL}", back_button())
        return

    # Отзыв
    if payload == "review":
        set_step(user_id, "enter_review")
        await send_message(user_id, "⭐ Напиши свой отзыв о боте 💕")
        return

    # По умолчанию
    await send_message(user_id, "Выбери действие из меню 👇", main_menu_buttons())

# ─── WEBHOOK ─────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(check_payments_loop())
    await register_webhook()
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
            name = user.get("name", "мама")
            username = user.get("username", "")
            get_user(chat_id, username, name)
            set_step(chat_id, "idle")
            threading.Thread(target=sheets_log_visit, args=(chat_id, name, username)).start()
            await send_message(chat_id,
                f"Привет, {name}! 🤍\n\n"
                f"Я Мамин Помощник — твой личный ИИ-помощник.\n\n"
                f"Даю советы основанные на рекомендациях ВОЗ и ведущих педиатров мира — "
                f"именно для твоей ситуации.\n\n"
                f"Сначала укажи кто ты 👇",
                [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                  {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]]
            )

        elif update_type == "message_created":
            msg = data.get("message", {})
            sender = msg.get("sender", {})
            chat_id = sender.get("user_id") or msg.get("recipient", {}).get("chat_id")
            username = sender.get("username", "")
            name = sender.get("name", "")
            body = msg.get("body", {})

            # Фото
            if body.get("type") == "image" or (body.get("attachments") and
               any(a.get("type") == "image" for a in body.get("attachments", []))):
                step, _ = get_step(chat_id)
                if step.startswith("waiting_photo_"):
                    photo_type = step.replace("waiting_photo_photo_", "")
                    await handle_photo(chat_id, data, photo_type)
                else:
                    await send_message(chat_id,
                        "📸 Выбери сначала тип анализа в меню Анализ фото",
                        back_button()
                    )
                return JSONResponse({"ok": True})

            text = body.get("text", "").strip()
            if text:
                get_user(chat_id, username, name)
                await handle_message(chat_id, text, username, name)

        elif update_type == "bot_action":
            cb = data.get("callback", {})
            payload = cb.get("payload", "")
            user = cb.get("user", {})
            chat_id = user.get("user_id")
            username = user.get("username", "")
            name = user.get("name", "")
            callback_id = cb.get("callback_id", "")
            get_user(chat_id, username, name)
            await answer_callback(callback_id)
            await handle_callback(chat_id, payload, username, name)

    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return JSONResponse({"ok": True})

async def handle_photo(chat_id, data, photo_type):
    set_step(chat_id, "idle")
    await send_message(chat_id, "⏳ Анализирую фото...")
    try:
        # Получаем URL фото из MAX
        msg = data.get("message", {})
        body = msg.get("body", {})
        attachments = body.get("attachments", [])
        photo_url = None
        for att in attachments:
            if att.get("type") == "image":
                photo_url = att.get("payload", {}).get("url") or att.get("url")
                break
        if not photo_url:
            await send_message(chat_id, "Не удалось получить фото. Попробуй ещё раз.", back_button())
            return

        async with httpx.AsyncClient() as c:
            resp = await c.get(photo_url, timeout=15)
            photo_b64 = base64.b64encode(resp.content).decode()

        prompts = {
            "photo_skin": (
                "Ты педиатр. Опиши что видишь на коже ребёнка: характер высыпаний, цвет, форма. "
                "На что похоже, что можно сделать дома, когда к врачу. Это описание, не диагноз.",
                "На фото кожа человека или ребёнка?"
            ),
            "photo_food": (
                "Ты диетолог-педиатр. Посмотри на блюдо: что это, подходит ли детям, с какого возраста.",
                "На фото еда или блюдо?"
            ),
            "photo_package": (
                "Ты педиатр-фармаколог. Изучи упаковку: что это, состав, для какого возраста, на что обратить внимание.",
                "На фото упаковка товара или лекарства?"
            ),
        }

        if photo_type not in prompts:
            photo_type = "photo_skin"

        analysis_prompt, filter_prompt = prompts[photo_type]

        # Фильтр
        filter_resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                {"type": "text", "text": filter_prompt + " Ответь только: ДА или НЕТ."}
            ]}],
            max_tokens=10
        )
        if "НЕТ" in filter_resp.choices[0].message.content.upper():
            wrong = {
                "photo_skin": "📸 Жду фото кожи малыша 🤍",
                "photo_food": "📸 Жду фото еды 🤍",
                "photo_package": "📸 Жду фото упаковки 🤍"
            }
            await send_message(chat_id, wrong.get(photo_type, "Отправь нужное фото"), back_button())
            return

        # Анализ
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                {"type": "text", "text": analysis_prompt}
            ]}],
            max_tokens=800
        )
        answer = resp.choices[0].message.content.replace("**", "").strip()
        await send_message(chat_id, answer, back_button())

    except Exception as e:
        logging.error(f"Photo analysis error: {e}")
        await send_message(chat_id, "Не удалось проанализировать фото. Попробуй ещё раз.", back_button())

@app.get("/payment/success")
async def payment_success():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
    <html><body style="font-family:Arial;text-align:center;padding:50px;background:#fff0f5">
    <h1>💎 Оплата прошла!</h1>
    <p>Премиум подписка активирована.<br>Вернись в Мамин Помощник и пользуйся всеми функциями!</p>
    </body></html>
    """)

# ─── ЗАПУСК ──────────────────────────────────────────────────
async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8082, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    import uvicorn
    asyncio.run(main())
