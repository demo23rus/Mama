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
from fastapi.responses import JSONResponse, HTMLResponse
import uvicorn
import gspread
from google.oauth2.service_account import Credentials
from yookassa import Configuration, Payment
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

# ========== КОНФИГ ==========
MAX_TOKEN        = "f9LHodD0cOIWTyPeJTIKgqKDGe8OGcGqK1BXLiPyMJqGIi1-CZR29YAPZgDbbUpDfwQXKDJovDVJ3HN_88XV"
MAX_API          = "https://platform-api.max.ru"
OPENAI_KEY       = "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"
WEBHOOK_URL      = "https://maminpomoshnik.ru/webhook"
SUPPORT_URL      = "https://t.me/demo23rus"
CHANNEL_ID       = -75619101439475
FREE_REQUESTS    = 10
DB               = "/root/mama_max.db"

YOOKASSA_SHOP_ID = "1363324"
YOOKASSA_SECRET  = "live_-RKE9nsi8wZiM-5f00z78E84OYSi3M0Dj9w_-pE0Mvw"
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key  = YOOKASSA_SECRET

GOOGLE_CREDS_PATH = "/root/google_credentials.json"
SPREADSHEET_ID    = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"

openai_client = AsyncOpenAI(api_key=OPENAI_KEY)

WELCOME_TEXT = """Привет, {name}! 🤍

Я Мамин Помощник — твой личный ИИ-помощник для мам.

Советы на основе рекомендаций ВОЗ и ведущих педиатров мира — именно для твоей ситуации.

Сначала укажи кто ты 👇"""

# ========== GOOGLE SHEETS ==========
def sheets_log_visit(user_id, first_name, username, plan=""):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        try:
            ws = spreadsheet.worksheet("МамаБот MAX")
        except:
            ws = spreadsheet.add_worksheet(title="МамаБот MAX", rows=1000, cols=6)
            ws.append_row(["Дата", "ID", "Имя", "Username", "Тариф", "Отзыв"])
        ws.append_row([datetime.now().strftime("%d.%m.%Y %H:%M"), str(user_id),
                       first_name or "", username or "", plan or "бесплатный", ""])
    except Exception as e:
        logging.error(f"Sheets error: {e}")

def sheets_log_review(user_id, first_name, text):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        try:
            ws = spreadsheet.worksheet("Отзывы МамаБот MAX")
        except:
            ws = spreadsheet.add_worksheet(title="Отзывы МамаБот MAX", rows=1000, cols=4)
            ws.append_row(["Дата", "ID", "Имя", "Отзыв"])
        ws.append_row([datetime.now().strftime("%d.%m.%Y %H:%M"), str(user_id), first_name or "", text])
    except Exception as e:
        logging.error(f"Sheets review error: {e}")

# ========== MAX API ==========
async def send_message(chat_id, text, buttons=None):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"text": text[:4000]}
    if buttons:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{MAX_API}/messages?chat_id={chat_id}", json=payload, headers=headers)
        logging.info(f"send_message chat_id={chat_id}: {r.status_code}")
        return r

async def send_to_channel(text):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"text": text[:4000]}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{MAX_API}/messages?chat_id={CHANNEL_ID}", json=payload, headers=headers)
        logging.info(f"Channel post: {r.status_code}")

# ========== КНОПКИ ==========
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
        [{"type": "callback", "text": "🔄 Новый разговор", "payload": "psycho_new"}],
        [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
    ]

def status_buttons():
    return [[
        {"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
        {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}
    ]]

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
        step TEXT DEFAULT 'idle', mode TEXT DEFAULT '', date_value TEXT DEFAULT '',
        registered_at TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY, plan TEXT DEFAULT '', sub_end TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER, plan TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests_count (
        user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS psycho_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        role TEXT, content TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS growth (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        height REAL, weight REAL, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS symptoms (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        symptom TEXT, created_at TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id, username="", first_name=""):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, registered_at) VALUES (?,?,?,?)",
              (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    c.execute("SELECT step, mode, date_value FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"step": row[0], "mode": row[1], "date_value": row[2]}

def set_step(user_id, step):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET step=? WHERE user_id=?", (step, user_id))
    conn.commit()
    conn.close()

def save_mode(user_id, mode, date_value):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET mode=?, date_value=? WHERE user_id=?", (mode, date_value, user_id))
    conn.commit()
    conn.close()

def get_subscription(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT plan, sub_end FROM subscriptions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or not row[1]:
        return None, None
    sub_end = datetime.fromisoformat(row[1])
    return (row[0], sub_end) if sub_end > datetime.now() else (None, None)

def set_subscription(user_id, plan, days):
    conn = sqlite3.connect(DB)
    end = (datetime.now() + timedelta(days=days)).isoformat()
    conn.execute("INSERT OR REPLACE INTO subscriptions (user_id, plan, sub_end) VALUES (?,?,?)",
                 (user_id, plan, end))
    conn.commit()
    conn.close()

def is_premium(user_id):
    plan, _ = get_subscription(user_id)
    return plan == "mama_premium"

def get_request_count(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT count FROM requests_count WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_requests(user_id):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT OR REPLACE INTO requests_count (user_id, count) VALUES (?, COALESCE((SELECT count FROM requests_count WHERE user_id=?),0)+1)",
                 (user_id, user_id))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT payment_id, user_id, plan FROM pending_payments").fetchall()
    conn.close()
    return rows

def save_pending_payment(payment_id, user_id, plan):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO pending_payments (payment_id, user_id, plan, created_at) VALUES (?,?,?,?)",
                 (payment_id, user_id, plan, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def delete_pending_payment(payment_id):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
    conn.commit()
    conn.close()

def get_psycho_history(user_id, limit=15):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                        (user_id, limit)).fetchall()
    conn.close()
    return list(reversed(rows))

def add_psycho_message(user_id, role, content):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                 (user_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def clear_psycho_history(user_id):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def save_growth(user_id, height, weight):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO growth (user_id, height, weight, created_at) VALUES (?,?,?,?)",
                 (user_id, height, weight, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_growth(user_id):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
                        (user_id,)).fetchall()
    conn.close()
    return rows

def save_symptom(user_id, symptom):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?,?,?)",
                 (user_id, symptom, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_symptoms(user_id):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                        (user_id,)).fetchall()
    conn.close()
    return rows

# ========== GPT ==========
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

async def generate_text(system, prompt, max_tokens=1200):
    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            max_tokens=max_tokens
        )
        text = resp.choices[0].message.content
        return text.replace("**", "").replace("__", "").replace("`", "").strip()
    except Exception as e:
        return f"Ошибка: {e}"

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
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
        from datetime import date, timedelta
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

# ========== ЮКАССА ==========
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
        }
    }, str(uuid.uuid4()))
    return payment

async def check_payments_loop():
    while True:
        await asyncio.sleep(15)
        try:
            for payment_id, user_id, plan in get_pending_payments():
                try:
                    payment = Payment.find_one(payment_id)
                    if payment.status == "succeeded":
                        set_subscription(user_id, "mama_premium", 30)
                        delete_pending_payment(payment_id)
                        await send_message(user_id,
                            "✅ Оплата прошла!\n\n💎 Премиум активирован на 30 дней.\nВсе функции разблокированы 🤍",
                            main_menu_buttons()
                        )
                    elif payment.status == "canceled":
                        delete_pending_payment(payment_id)
                except Exception as e:
                    logging.error(f"Payment check {payment_id}: {e}")
        except Exception as e:
            logging.error(f"Payments loop: {e}")

# ========== АВТОПОСТИНГ ==========
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
    8:  ("🌅 Доброе утро, мама", "Короткий заряд на день — мотивация, поддержка. 100-150 слов."),
    10: ("🔬 Научный факт дня", "Интересный научный факт о детях. Ссылка на ВОЗ или AAP. 150-200 слов."),
    13: ("💡 Совет педиатра", "Практический совет по ВОЗ/AAP. 200-250 слов."),
    16: ("🧠 Детская психология", "Объяснение поведения ребёнка по Петрановской/Сигелу. 200-250 слов."),
    20: ("❤️ Для мамы", "О восстановлении, выгорании. Тепло. 150-200 слов."),
}

async def post_rubric(hour):
    weekday = datetime.now().weekday()
    rubric_name, rubric_instruction = RUBRICS[hour]
    daily_theme = DAILY_THEMES[weekday]
    post = await generate_text(
        "Ты автор экспертного канала 'Я МАМА' в MAX. "
        "Пишешь на основе ВОЗ, AAP, Петрановской, Карпа. "
        "Тепло и научно. Без воды. Добавляй эмодзи. В конце — практический совет.",
        f"Рубрика: {rubric_name}\nТема: {daily_theme}\nИнструкция: {rubric_instruction}\n"
        f"Начни с эмодзи рубрики и её названия."
    )
    await send_to_channel(post)
    logging.info(f"Канал: пост опубликован — {rubric_name}")

# ========== ОБРАБОТКА СООБЩЕНИЙ ==========
async def process_command(chat_id, user_id, text, username="", first_name=""):
    get_user(user_id, username, first_name)
    name = first_name or "мама"
    user = get_user(user_id)
    step = user.get("step", "idle")
    mode = user.get("mode", "")
    date_value = user.get("date_value", "")

    if text in ("/start", "start"):
        set_step(user_id, "idle")
        plan, _ = get_subscription(user_id)
        asyncio.create_task(asyncio.to_thread(sheets_log_visit, user_id, first_name, username, plan))
        await send_message(chat_id, WELCOME_TEXT.format(name=name), status_buttons())
        return

    # Психолог
    if step == "psycho":
        if not is_premium(user_id):
            set_step(user_id, "idle")
            await send_message(chat_id, "🔒 Мамин психолог доступен в Премиум 💎", premium_button())
            return
        add_psycho_message(user_id, "user", text)
        history = get_psycho_history(user_id)
        context = ""
        if mode == "pregnant" and date_value:
            context = f"Беременная на {calc_pregnancy_weeks(date_value)} неделе."
        elif mode == "mama" and date_value:
            context = f"Мама, ребёнку {age_label(calc_child_age(date_value))}."
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
            await send_message(chat_id, "Что-то пошло не так. Попробуй ещё раз 💕")
        return

    # Вопрос
    if step == "ask":
        set_step(user_id, "idle")
        if not is_premium(user_id) and get_request_count(user_id) >= FREE_REQUESTS:
            await send_message(chat_id, f"❓ Ты использовала {FREE_REQUESTS} бесплатных вопросов\n\nОформи Премиум — 299 руб/мес", premium_button())
            return
        increment_requests(user_id)
        context = ""
        if mode == "pregnant" and date_value:
            context = f"Беременная на {calc_pregnancy_weeks(date_value)} неделе."
        elif mode == "mama" and date_value:
            context = f"Мама, ребёнку {age_label(calc_child_age(date_value))}."
        await send_message(chat_id, "⏳ Думаю...")
        answer = await generate_text(f"{EXPERT_BASE} {context}", text)
        await send_message(chat_id, answer, back_button())
        return

    # Ввод даты рождения
    if step == "enter_birthdate":
        months = calc_child_age(text)
        if months is None or months < 0 or months > 216:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
            return
        save_mode(user_id, "mama", text)
        set_step(user_id, "idle")
        await send_message(chat_id, f"✅ Малышу {age_label(months)}\n\nЧем могу помочь? 💕", main_menu_buttons())
        return

    # Ввод ПДР
    if step == "enter_pdr":
        weeks = calc_pregnancy_weeks(text)
        if weeks is None or weeks < 0 or weeks > 42:
            await send_message(chat_id, "❌ Неверный формат. Введи: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
            return
        save_mode(user_id, "pregnant", text)
        set_step(user_id, "idle")
        await send_message(chat_id, f"✅ Ты на {weeks} неделе беременности\n\nЧем могу помочь? 💕", main_menu_buttons())
        return

    # Ввод роста
    if step == "enter_height":
        try:
            h = float(text.replace(",", "."))
            set_step(user_id, f"enter_weight_{h}")
            await send_message(chat_id, "⚖️ Введи вес в килограммах\nНапример: 7.2")
        except:
            await send_message(chat_id, "❌ Введи число, например: 67.5")
        return

    if step.startswith("enter_weight_"):
        try:
            w = float(text.replace(",", "."))
            h = float(step.replace("enter_weight_", ""))
            save_growth(user_id, h, w)
            months = calc_child_age(date_value) if mode == "mama" and date_value else None
            set_step(user_id, "idle")
            await send_message(chat_id, "⏳ Анализирую...")
            answer = await generate_text(EXPERT_BASE, f"Ребёнку {age_label(months)}. Рост {h} см, вес {w} кг. Оцени по нормам ВОЗ.")
            await send_message(chat_id, f"📏 Рост и вес\n\n{answer}", back_button())
        except:
            await send_message(chat_id, "❌ Введи число, например: 7.2")
        return

    # Ввод симптома
    if step == "enter_symptom":
        save_symptom(user_id, text)
        set_step(user_id, "idle")
        await send_message(chat_id, "✅ Симптом записан!", back_button())
        return

    # Ввод отзыва
    if step == "review":
        set_step(user_id, "idle")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, text))
        await send_message(chat_id, "⭐ Спасибо за отзыв! 💕", main_menu_buttons())
        return

    # Если статус не указан
    if not mode:
        await send_message(chat_id, WELCOME_TEXT.format(name=name), status_buttons())
        return

    await send_message(chat_id, "Выбери действие из меню 👇", main_menu_buttons())

# ========== ОБРАБОТКА КНОПОК ==========
async def process_callback(chat_id, user_id, payload, first_name=""):
    get_user(user_id)
    user = get_user(user_id)
    mode = user.get("mode", "")
    date_value = user.get("date_value", "")
    months = calc_child_age(date_value) if mode == "mama" and date_value else None
    weeks = calc_pregnancy_weeks(date_value) if mode == "pregnant" and date_value else None

    if payload == "back_menu":
        set_step(user_id, "idle")
        if mode == "mama" and months is not None:
            await send_message(chat_id, f"👶 Малышу {age_label(months)}\n\nЧем могу помочь?", main_menu_buttons())
        elif mode == "pregnant" and weeks:
            await send_message(chat_id, f"🤰 Ты на {weeks} неделе\n\nЧем могу помочь?", main_menu_buttons())
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=first_name or "мама"), status_buttons())
        return

    if payload == "set_mama":
        set_step(user_id, "enter_birthdate")
        await send_message(chat_id, "👶 Введи дату рождения малыша\n\nФормат: ДД.ММ.ГГГГ\nНапример: 10.03.2024")
        return

    if payload == "set_pregnant":
        set_step(user_id, "enter_pdr")
        await send_message(chat_id, "🤰 Введи предполагаемую дату родов (ПДР)\n\nФормат: ДД.ММ.ГГГГ\nНапример: 15.09.2025")
        return

    # Информационные разделы (бесплатные)
    info_map = {
        "firstdays": "Расскажи о первых днях после рождения: первый педиатр, документы (свидетельство, ОМС, СНИЛС), массаж, плавание.",
        "breastfeeding": "Расскажи о грудном вскармливании: налаживание по ВОЗ, правильный захват, лактостаз.",
        "recovery": "Восстановление после родов: естественные и КС, швы, упражнения Кегеля, диастаз.",
        "emotions": "Послеродовая депрессия, беби-блюз, выгорание. Как распознать. Тепло и без осуждения.",
    }
    age_info_map = {
        "development": f"Развитие ребёнка {age_label(months)} по AAP и ВОЗ: физическое, речевое, когнитивное, социальное.",
        "health": f"Типичные проблемы здоровья у ребёнка {age_label(months)} по AAP. Когда к врачу.",
        "food": f"Питание ребёнка {age_label(months)} по ВОЗ и ESPGHAN: что вводить, что нельзя.",
        "routine": f"Режим дня для ребёнка {age_label(months)} по хронобиологии и AAP.",
        "sleep": f"Сон ребёнка {age_label(months)}: нормы, методы улучшения, безопасная среда.",
        "tantrums": f"Поведение ребёнка {age_label(months)} по Петрановской и Сигелу. Как реагировать.",
    }

    if payload in info_map:
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, info_map[payload])
        await send_message(chat_id, answer, back_button())
        return

    if payload in age_info_map:
        if not mode:
            await send_message(chat_id, "Сначала укажи кто ты 👇", status_buttons())
            return
        await send_message(chat_id, "⏳ Подбираю информацию...")
        answer = await generate_text(EXPERT_BASE, age_info_map[payload])
        await send_message(chat_id, answer, back_button())
        return

    if payload == "ask":
        if not is_premium(user_id) and get_request_count(user_id) >= FREE_REQUESTS:
            await send_message(chat_id, f"❓ Ты использовала {FREE_REQUESTS} бесплатных вопросов\n\nОформи Премиум — 299 руб/мес", premium_button())
            return
        set_step(user_id, "ask")
        await send_message(chat_id, "❓ Напиши свой вопрос о малыше, беременности или воспитании 💕")
        return

    # Премиум проверка
    premium_names = {"psycho": "Мамин психолог", "photo_menu": "Анализ фото",
                     "growth": "Трекер роста и веса", "symptoms": "Трекер симптомов",
                     "vaccines": "Прививочный календарь", "benefits": "Пособия и выплаты"}
    if payload in premium_names and not is_premium(user_id):
        await send_message(chat_id, f"🔒 {premium_names[payload]} доступна в Премиум 💎\n\n299 руб/месяц", premium_button())
        return

    if payload == "psycho":
        history = get_psycho_history(user_id)
        set_step(user_id, "psycho")
        if history:
            await send_message(chat_id, "🧠 С возвращением! Я помню наш разговор.\n\nКак ты сейчас? 💕", psycho_buttons())
        else:
            await send_message(chat_id,
                "🧠 Привет! Я твой личный психолог 💕\n\n"
                "Говори обо всём — усталость, тревога, отношения, чувство вины.\n\nКак ты сейчас?",
                psycho_buttons()
            )
        return

    if payload == "psycho_new":
        clear_psycho_history(user_id)
        set_step(user_id, "psycho")
        await send_message(chat_id, "🧠 Начинаем с чистого листа 💕\n\nКак ты сейчас?", psycho_buttons())
        return

    if payload == "photo_menu":
        buttons = [
            [{"type": "callback", "text": "🔴 Сыпь и кожа", "payload": "photo_skin"},
             {"type": "callback", "text": "🍽 Еда малыша", "payload": "photo_food"}],
            [{"type": "callback", "text": "💊 Упаковка смеси", "payload": "photo_package"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "📸 Выбери тип фото и отправь изображение 👇", buttons)
        return

    for pt in ["photo_skin", "photo_food", "photo_package"]:
        if payload == pt:
            set_step(user_id, f"photo_{pt}")
            prompts = {
                "photo_skin": "📸 Отправь фото кожи или сыпи малыша\n\n⚠️ Это ориентир, не диагноз.",
                "photo_food": "📸 Отправь фото еды или блюда",
                "photo_package": "📸 Отправь фото упаковки смеси или лекарства"
            }
            await send_message(chat_id, prompts[pt])
            return

    if payload == "growth":
        entries = get_growth(user_id)
        text = "📏 Рост и вес малыша\n\n"
        if entries:
            for h, w, dt in entries[:3]:
                d = datetime.fromisoformat(dt).strftime("%d.%m.%Y")
                text += f"📅 {d} — {h} см, {w} кг\n"
            text += "\n"
        text += "Введи рост малыша в сантиметрах\nНапример: 67.5"
        set_step(user_id, "enter_height")
        await send_message(chat_id, text)
        return

    if payload == "symptoms":
        entries = get_symptoms(user_id)
        buttons = [
            [{"type": "callback", "text": "➕ Записать симптом", "payload": "symptom_add"},
             {"type": "callback", "text": "🔍 Анализ", "payload": "symptom_analyze"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        text = "🌡 Трекер симптомов\n\n"
        text += "\n".join([f"📅 {datetime.fromisoformat(dt).strftime('%d.%m %H:%M')} — {s}" for s, dt in entries[:5]]) if entries else "Записей нет."
        await send_message(chat_id, text, buttons)
        return

    if payload == "symptom_add":
        set_step(user_id, "enter_symptom")
        await send_message(chat_id, "🌡 Опиши симптом\n\nНапример: температура 38.2, кашель, сыпь")
        return

    if payload == "symptom_analyze":
        entries = get_symptoms(user_id)
        if not entries:
            await send_message(chat_id, "Нет симптомов для анализа.", back_button())
            return
        await send_message(chat_id, "⏳ Анализирую...")
        data_str = "\n".join([f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {s}" for s, dt in entries])
        answer = await generate_text(EXPERT_BASE, f"Ребёнку {age_label(months)}. Симптомы:\n{data_str}\n\nПроанализируй: что это, динамика, стоит ли к врачу.")
        await send_message(chat_id, answer, back_button())
        return

    if payload == "vaccines":
        await send_message(chat_id, "⏳ Подбираю...")
        answer = await generate_text(EXPERT_BASE, "Расскажи о национальном календаре прививок РФ для детей до 2 лет: БЦЖ, Гепатит B, АКДС, Полиомиелит, Пневмококк, КПК, Ветрянка. Когда, зачем, как подготовить.")
        await send_message(chat_id, f"💉 Прививочный календарь\n\n{answer}", back_button())
        return

    if payload == "benefits":
        buttons = [
            [{"type": "callback", "text": "👶 При рождении", "payload": "ben_birth"},
             {"type": "callback", "text": "🤱 До 1.5 лет", "payload": "ben_15"}],
            [{"type": "callback", "text": "📅 До 3 лет", "payload": "ben_3"},
             {"type": "callback", "text": "🏠 Маткапитал", "payload": "ben_matcap"}],
            [{"type": "callback", "text": "❓ Что положено мне", "payload": "ben_personal"}],
            [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
        ]
        await send_message(chat_id, "💰 Пособия и выплаты\n\nВыбери раздел 👇", buttons)
        return

    ben_map = {
        "ben_birth": "Единовременное пособие при рождении в России 2024-2025. Размер, документы, куда обращаться.",
        "ben_15": "Пособие по уходу до 1.5 лет в России 2024-2025. Для работающих и неработающих.",
        "ben_3": "Выплаты на ребёнка от 1.5 до 3 лет в России 2024-2025. Путинские выплаты.",
        "ben_matcap": "Материнский капитал в России 2024-2025. Размер, на что потратить, как оформить.",
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

    if payload in ["premium_info", "pay_premium"]:
        try:
            payment = await create_payment(user_id)
            save_pending_payment(payment.id, user_id, "mama_premium")
            buttons = [
                [{"type": "link", "text": "💳 Оплатить 299 руб", "url": payment.confirmation.confirmation_url}],
                [{"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
            ]
            await send_message(chat_id,
                "💎 Премиум подписка — 299 руб/месяц\n\n"
                "Что открывается:\n"
                "🧠 Мамин психолог с историей диалогов\n"
                "📸 Анализ фото\n"
                "📏 Трекер роста и веса\n"
                "🌡 Трекер симптомов\n"
                "💉 Прививки\n"
                "💰 Пособия\n"
                "❓ Безлимитные вопросы\n\n"
                "После оплаты активируется автоматически!",
                buttons
            )
        except Exception as e:
            logging.error(f"Payment error: {e}")
            await send_message(chat_id, f"Ошибка платежа. Напиши в поддержку: {SUPPORT_URL}", back_button())
        return

    if payload == "review":
        set_step(user_id, "review")
        await send_message(chat_id, "⭐ Напиши свой отзыв о боте 💕")
        return

    await send_message(chat_id, "Выбери действие из меню 👇", main_menu_buttons())

# ========== АНАЛИЗ ФОТО ==========
async def process_photo(chat_id, user_id, photo_url):
    if not is_premium(user_id):
        await send_message(chat_id, "🔒 Анализ фото доступен в Премиум 💎", premium_button())
        return

    user = get_user(user_id)
    step = user.get("step", "")
    photo_type = "skin"
    if "food" in step: photo_type = "food"
    elif "package" in step: photo_type = "package"
    set_step(user_id, "idle")

    await send_message(chat_id, "⏳ Анализирую фото...")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(photo_url)
            photo_b64 = base64.b64encode(resp.content).decode()

        prompts = {
            "skin": ("На фото кожа человека?", "Ты педиатр. Опиши кожу: высыпания, цвет, форма. На что похоже, что делать, когда к врачу. Это описание, не диагноз."),
            "food": ("На фото еда?", "Ты диетолог-педиатр. Что это за еда, подходит ли детям, с какого возраста."),
            "package": ("На фото упаковка товара?", "Ты педиатр. Изучи упаковку: что это, состав, возраст, на что обратить внимание."),
        }
        filter_q, analysis_q = prompts.get(photo_type, prompts["skin"])

        filter_resp = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                {"type": "text", "text": filter_q + " Ответь только: ДА или НЕТ."}
            ]}], max_tokens=10
        )
        if "НЕТ" in filter_resp.choices[0].message.content.upper():
            await send_message(chat_id, "📸 Отправь нужное фото 🤍", back_button())
            return

        resp2 = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                {"type": "text", "text": analysis_q}
            ]}], max_tokens=800
        )
        answer = resp2.choices[0].message.content.replace("**", "").strip()
        await send_message(chat_id, answer, back_button())
    except Exception as e:
        logging.error(f"Photo error: {e}")
        await send_message(chat_id, "Не удалось проанализировать фото.", back_button())

# ========== FASTAPI WEBHOOK ==========
app = FastAPI()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

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
    scheduler.add_job(lambda: asyncio.create_task(post_rubric(8)),  "cron", hour=8,  minute=0)
    scheduler.add_job(lambda: asyncio.create_task(post_rubric(10)), "cron", hour=10, minute=0)
    scheduler.add_job(lambda: asyncio.create_task(post_rubric(13)), "cron", hour=13, minute=0)
    scheduler.add_job(lambda: asyncio.create_task(post_rubric(16)), "cron", hour=16, minute=0)
    scheduler.add_job(lambda: asyncio.create_task(post_rubric(20)), "cron", hour=20, minute=0)
    scheduler.start()
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
            first_name = user.get("name", "мама")
            username = user.get("username", "")
            get_user(user_id, username, first_name)
            set_step(user_id, "idle")
            plan, _ = get_subscription(user_id)
            asyncio.create_task(asyncio.to_thread(sheets_log_visit, user_id, first_name, username, plan))
            await send_message(chat_id, WELCOME_TEXT.format(name=first_name), status_buttons())

        elif update_type == "message_created":
            sender = message.get("sender", {})
            chat_id = message.get("recipient", {}).get("chat_id")
            user_id = sender.get("user_id")
            first_name = sender.get("name", "мама")
            username = sender.get("username", "")
            body = message.get("body", {})
            text = body.get("text", "")
            attachments = body.get("attachments", [])

            # Игнорируем если сообщение из канала
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
                        if photo_url:
                            await process_photo(chat_id, user_id, photo_url)
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
            user_id = user.get("user_id")
            first_name = user.get("name", "мама")
            payload_cb = callback.get("payload", "")
            logging.info(f"CALLBACK: chat_id={chat_id} user_id={user_id} payload={payload_cb}")
            if chat_id and payload_cb:
                await process_callback(chat_id, user_id, payload_cb, first_name)
            else:
                logging.error(f"Нет chat_id в callback: {data}")

    except Exception as e:
        logging.error(f"Webhook error: {e}")

    return JSONResponse({"ok": True})

@app.get("/payment/success")
async def payment_success():
    return HTMLResponse("""
    <html><body style="font-family:Arial;text-align:center;padding:50px;background:#fff0f5">
    <div style="font-size:64px">💎</div>
    <h1 style="color:#e91e8c">Оплата прошла!</h1>
    <p>Премиум подписка активирована.<br>Вернись в Мамин Помощник и пользуйся всеми функциями!</p>
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
