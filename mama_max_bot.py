import asyncio
import os
import sqlite3
import logging
import os
import json
import uuid
import base64
import hashlib
import hmac
import httpx
import calendar
import random
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from PIL import Image, ImageOps

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
from urllib.parse import urlparse, parse_qs, parse_qsl, quote
from openai import AsyncOpenAI
from fastapi import FastAPI, Request, HTTPException
from starlette.datastructures import UploadFile
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

APP_VERSION = "10.5.5-max-channel-private-response-fix"
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
MINIAPP_URL = "https://maminpomoshnik.ru/app/"
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

# Таблица PostGenius Users общая для нескольких независимых проектов (Aura,
# МамаБот, MarketPro, AI Местный и др.) через один service account. Гвард не
# даёт коду МамаБот MAX удалить/переименовать/массово очистить свой или чужой
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
        title = getattr(self._wrapped, "title", SPREADSHEET_ID_MAMA)
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


def _max_sheets_book():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_PATH, scopes=scopes)
    return _NoDeleteSpreadsheetGuard(gspread.authorize(creds).open_by_key(SPREADSHEET_ID_MAMA))

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

HEARTBEAT_FILE = "/tmp/mama_max.heartbeat"

async def heartbeat_loop():
    """Обновляет heartbeat-файл для независимого watchdog."""
    while True:
        try:
            with open(HEARTBEAT_FILE, "a", encoding="utf-8"):
                os.utime(HEARTBEAT_FILE, None)
        except Exception as exc:
            logging.error("Не удалось обновить MAX heartbeat: %s", exc)
        await asyncio.sleep(30)

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
def start_buttons(user_id=None):
    buttons = [
        [{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"}],
        [{"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}],
    ]
    if MINIAPP_URL:
        buttons.append([{"type": "link", "text": "📱 Открыть приложение", "url": MINIAPP_URL}])
    if MAX_CHANNEL_PUBLIC_URL:
        buttons.append([{"type": "link", "text": "📢 Наш канал", "url": MAX_CHANNEL_PUBLIC_URL}])
    buttons.append([
        {"type": "callback", "text": "❤️ Поддержать проект", "payload": "donate_menu"},
        {"type": "callback", "text": "🆘 Поддержка", "payload": "support_menu"},
    ])
    return _with_owner_button_max(buttons, user_id)


def _with_owner_button_max(rows, user_id=None):
    if OWNER_ID and int(user_id or 0) == OWNER_ID:
        rows.append([{"type": "callback", "text": "👑 Кабинет владельца", "payload": "owner_cab:home"}])
    return rows


def pregnant_menu_buttons(user_id=None):
    return _with_owner_button_max([
        [{"type":"callback","text":"✨ Сегодня","payload":"today_brief"}],
        [{"type":"callback","text":"🤰 Беременность","payload":"cat_pregnancy"}, {"type":"callback","text":"❤️ Здоровье","payload":"cat_preg_health"}],
        [{"type":"callback","text":"🧠 Для мамы","payload":"cat_mom_preg"}, {"type":"callback","text":"📓 Мои данные","payload":"profile"}],
        [{"type":"callback","text":"❓ Задать вопрос","payload":"ask"}],
        [{"type": "link", "text": "📱 Открыть приложение", "url": MINIAPP_URL}],
        [{"type":"callback","text":"❤️ Поддержать проект","payload":"donate_menu"}, {"type":"callback","text":"🆘 Поддержка","payload":"support_menu"}],
        [{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}],
        [{"type":"callback","text":"🔄 Изменить данные","payload":"change_data"}],
    ], user_id)


def main_menu_buttons(user_id=None):
    return _with_owner_button_max([
        [{"type":"callback","text":"✨ Сегодня","payload":"today_brief"}],
        [{"type":"callback","text":"👶 Ребёнок","payload":"cat_child"}, {"type":"callback","text":"❤️ Здоровье","payload":"cat_health"}],
        [{"type":"callback","text":"📊 Трекеры","payload":"cat_trackers"}, {"type":"callback","text":"🧠 Для мамы","payload":"cat_mom"}],
        [{"type":"callback","text":"👨‍👩‍👧 Семья","payload":"cat_family"}, {"type":"callback","text":"📓 Мои данные","payload":"profile"}],
        [{"type":"callback","text":"❓ Задать вопрос","payload":"ask"}],
        [{"type": "link", "text": "📱 Открыть приложение", "url": MINIAPP_URL}],
        [{"type":"callback","text":"❤️ Поддержать проект","payload":"donate_menu"}, {"type":"callback","text":"🆘 Поддержка","payload":"support_menu"}],
        [{"type":"callback","text":"🎁 Пригласить подругу","payload":"invite_friend"}],
        [{"type":"callback","text":"🔄 Изменить данные","payload":"change_data"}],
    ], user_id)


def child_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"📊 Развитие по возрасту","payload":"development"}],
        [{"type":"callback","text":"🎮 Игры и занятия","payload":"games"}, {"type":"callback","text":"📚 Что читать","payload":"books"}],
        [{"type":"callback","text":"🍼 Питание и прикорм","payload":"food"}, {"type":"callback","text":"🥣 Рецепты","payload":"recipes"}],
        [{"type":"callback","text":"🌙 Режим дня","payload":"routine"}, {"type":"callback","text":"😴 Проблемы со сном","payload":"sleep"}],
        [{"type":"callback","text":"😢 Истерики и капризы","payload":"tantrums"}],
        [{"type":"callback","text":"📋 Первые дни с малышом","payload":"firstdays"}],
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"🌙 Разбор сна","payload":"sleep_analyze"}],
        [{"type":"callback","text":"📈 Отчёт за неделю","payload":"weekly_report"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def health_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🚨 Ребёнку плохо","payload":"emergency"}],
        [{"type":"callback","text":"🌡 Здоровье","payload":"health"}, {"type":"callback","text":"💊 Лекарства","payload":"meds"}],
        [{"type":"callback","text":"🦷 Зубки","payload":"teeth"}],
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"🩺 Сводка врачу","payload":"doctor_prep"}],
        [{"type":"callback","text":"📸 Анализ фото","payload":"photo_menu"}],
        [{"type":"callback","text":"💉 Прививки","payload":"vaccines"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def tracker_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"📓 Дневник малыша","payload":"diary"}],
        [{"type":"callback","text":"📊 ТРЕКЕРЫ","payload":"noop"}],
        [{"type":"callback","text":"📏 Рост и вес","payload":"growth"}, {"type":"callback","text":"🌡 Симптомы","payload":"symptoms"}],
        [{"type":"callback","text":"🤱 Кормления","payload":"feeding"}, {"type":"callback","text":"🌙 Сон","payload":"sleep_log"}],
        [{"type":"callback","text":"✨ ГЛУБОКИЙ АНАЛИЗ","payload":"noop"}],
        [{"type":"callback","text":"🤱 Разбор кормлений","payload":"feed_stats"}],
        [{"type":"callback","text":"🌙 Разбор сна","payload":"sleep_analyze"}],
        [{"type":"callback","text":"📈 Отчёт за 7 дней","payload":"weekly_report"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def mom_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Эмоции мамы","payload":"emotions"}],
        [{"type":"callback","text":"🤱 Грудное вскармливание","payload":"breastfeeding"}],
        [{"type":"callback","text":"🏥 Восстановление мамы","payload":"recovery"}],
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Мамин психолог","payload":"psycho"}],
        [{"type":"callback","text":"💰 Пособия и выплаты","payload":"benefits"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def family_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"👨‍👩‍👧 Отношения в семье","payload":"family"}],
        [{"type":"callback","text":"📓 Дневник малыша","payload":"diary"}],
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"📈 Недельный отчёт","payload":"weekly_report"}],
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
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"📸 Анализы и УЗИ","payload":"photo_menu"}],
        [{"type":"callback","text":"🔙 Главное меню","payload":"back_menu"}],
    ]


def preg_mom_category_buttons():
    return [
        [{"type":"callback","text":"🆓 БЕСПЛАТНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Эмоциональная поддержка","payload":"emotions"}],
        [{"type":"callback","text":"✨ ДОПОЛНИТЕЛЬНО","payload":"noop"}],
        [{"type":"callback","text":"🧠 Мамин психолог","payload":"psycho"}],
        [{"type":"callback","text":"💰 Пособия и выплаты","payload":"benefits"}],
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

DONATE_AMOUNTS = [
    (99, "99 ₽ — Сказать спасибо"),
    (199, "199 ₽ — Поддержать развитие"),
    (499, "499 ₽ — Большое спасибо"),
    (990, "990 ₽ — Помочь проекту расти"),
]
DONATE_MIN_AMOUNT = 10
DONATE_MAX_AMOUNT = 100000

def kb_donate_menu():
    buttons = [[{"type": "callback", "text": label, "payload": f"donate_amt_{amount}"}] for amount, label in DONATE_AMOUNTS]
    buttons.append([{"type": "callback", "text": "Другая сумма", "payload": "donate_amt_custom"}])
    buttons.append([{"type": "callback", "text": "Назад", "payload": "back_menu"}])
    return buttons

def psycho_buttons():
    return [
        [{"type": "callback", "text": "🔄 Новый разговор", "payload": "psycho_new"},
         {"type": "callback", "text": "🔙 В меню", "payload": "back_menu"}]
    ]

# ========== БАЗА ДАННЫХ ==========
DB = "/root/mama_max.db"
TG_DB_PATH = "/root/mama.db"

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
    c.execute("""CREATE TABLE IF NOT EXISTS support_payments (
        payment_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, platform TEXT NOT NULL,
        amount TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'RUB', status TEXT NOT NULL DEFAULT 'pending',
        variant TEXT NOT NULL DEFAULT '', source TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_user_date ON sales_events(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_support_payments_user ON support_payments(user_id, created_at)")
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
    c.execute("""CREATE TABLE IF NOT EXISTS command_locks (
        lock_key TEXT PRIMARY KEY, created_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_command_locks_created ON command_locks(created_at)")
    # MAX API адресует приватный чат по chat_id, который отличается от user_id и
    # ранее нигде не сохранялся — из-за этого проактивная рассылка была невозможна.
    c.execute("""CREATE TABLE IF NOT EXISTS max_user_chats (
        user_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
        first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_update_type TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_max_user_chats_chat ON max_user_chats(chat_id)")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback_campaign_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_key TEXT NOT NULL, platform TEXT NOT NULL,
        user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(campaign_key, platform, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS broadcast_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, broadcast_key TEXT NOT NULL, platform TEXT NOT NULL,
        user_id INTEGER NOT NULL, status TEXT NOT NULL, error_code TEXT DEFAULT '', ts TEXT NOT NULL,
        UNIQUE(broadcast_key, platform, user_id)
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


def referral_link_tg(user_id):
    # Тот же формат deep link, что и referral_link_tg в mama_bot.py (отдельный процесс,
    # без общего импорта) — @MaminPomoshnikAI_bot, ref_<referrer_user_id> в start-параметре.
    return f"https://t.me/MaminPomoshnikAI_bot?start=ref_{int(user_id)}"


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
    # Проект бесплатный: весь функционал доступен всем без тарифа.
    return True


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
        "payload": "ask",
    },
    "channel_doctor": {
        "title": "Ребёнок заболел — подготовить вопросы врачу",
        "free": "Сейчас помогу собрать симптомы, что записать перед приёмом и какие вопросы задать врачу.",
        "button": "Подготовить вопросы врачу",
        "payload": "funnel_doctor",
    },
    "channel_sleep": {
        "title": "Плохо спит — разобрать режим",
        "free": "Ответьте на несколько вопросов — получите первичный разбор режима и 2–3 идеи, что попробовать сегодня.",
        "button": "Разобрать сон ребёнка",
        "payload": "funnel_sleep",
    },
    "channel_tantrum": {
        "title": "Истерики и поведение — получить план действий",
        "free": "Сначала бесплатно разберём ситуацию: что делать родителю, чего лучше не делать и что сказать ребёнку.",
        "button": "Понять, что делать при истерике",
        "payload": "funnel_tantrum",
    },
    "channel_garden": {
        "title": "Не хочет в садик — понять, что делать",
        "free": "Соберём короткий чек-лист адаптации, вопросы воспитателю и способ облегчить утро.",
        "button": "Разобрать адаптацию к садику",
        "payload": "funnel_garden",
    },
    "channel_school": {
        "title": "Школа, уроки, оценки — получить подсказки",
        "free": "Получите короткий план по одной ситуации, вопросы ребёнку после школы и идею, как снизить конфликт.",
        "button": "Получить подсказки по школе",
        "payload": "funnel_school",
    },
    "channel_feeding": {
        "title": "Что приготовить ребёнку",
        "free": "Подберём 1–3 идеи завтрака, перекуса или ужина и простой рецепт из доступных продуктов.",
        "button": "Получить подсказку по питанию",
        "payload": "funnel_feeding",
    },
    "channel_psycho": {
        "title": "Мама устала — поговорить с помощником",
        "free": "Можно начать с бесплатных сообщений психологическому помощнику и собрать короткий план разгрузки на день.",
        "button": "Поговорить с психологическим помощником",
        "payload": "psycho",
    },
    "channel_grandma": {
        "title": "Бабушки и воспитание — договориться без ссоры",
        "free": "Соберём готовые фразы для разговора и способ обозначить границы без конфликта.",
        "button": "Подготовить разговор",
        "payload": "funnel_grandma",
    },
    "channel_gadgets": {
        "title": "Гаджеты и экранное время",
        "free": "Соберём короткий план семейных правил, чтобы телефон не превращался в постоянную войну.",
        "button": "Составить правила экранного времени",
        "payload": "funnel_gadgets",
    },
    "channel_child": {
        "title": "Понять развитие ребёнка по возрасту",
        "free": "Опишите возраст и навык — получите спокойную подсказку, что обычно важно проверить.",
        "button": "Проверить развитие",
        "payload": "funnel_development",
    },
    "channel_family": {
        "title": "Семейная ситуация — подготовить разговор",
        "free": "Разберём, что важно сказать, где поставить границу и как не усиливать конфликт.",
        "button": "Подготовить разговор",
        "payload": "funnel_family",
    },
    "channel_pregnancy": {
        "title": "Беременность — получить подсказку по сроку",
        "free": "Напишите срок и вопрос — получите понятный бесплатный ответ с учётом беременности.",
        "button": "Задать вопрос по беременности",
        "payload": "funnel_pregnancy",
    },
}


def channel_landing_max(payload):
    item = CHANNEL_LANDING.get(payload, CHANNEL_LANDING["channel_today"])
    text = (
        f"{item['title']}\n\n"
        f"{item['free']}\n\n"
        "Это не заменяет врача или специалиста, но поможет не забыть важное.\n\n"
        "Ответ бесплатный — как и все остальные функции «Маминого помощника»."
    )
    buttons = [
        [{"type": "callback", "text": item["button"], "payload": item["payload"]}],
        [{"type": "callback", "text": "Все функции Маминого помощника", "payload": "back_menu"}],
    ]
    return text, buttons


def _question_next_action_max(question_text, pregnant=False):
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
    return ("🤰 Ещё вопрос о беременности", "funnel_pregnancy") if pregnant else ("❓ Задать ещё вопрос", "ask")



def build_question_funnel_max(user_id, question_text=""):
    # Проект бесплатный: без счётчика оставшихся вопросов и без цен.
    user=get_user(user_id); pregnant=user.get("birth_date","").startswith("pdr:")
    next_label,next_payload=_question_next_action_max(question_text,pregnant)
    text="✨ Готово. Можно продолжить с ещё одним вопросом."; buttons=[[{"type":"callback","text":next_label,"payload":next_payload}]]
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
    # Проект бесплатный: ни один callback больше не требует тарифа или покупки.
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
            openai_client.chat.completions.create(
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
    """AI-генерация изображений отключена. Канал работает в текстовом режиме."""
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


async def send_donate_confirm(chat_id, amount, variant):
    amount_label = f"{amount:.0f}" if amount == int(amount) else f"{amount:.2f}"
    await send_message(
        chat_id,
        "Вы поддерживаете развитие бесплатного проекта «Мамин помощник». "
        "Оплата добровольная и не открывает дополнительных функций — они уже доступны всем.",
        [[{"type": "callback", "text": f"Оплатить {amount_label} ₽", "payload": f"donate_confirm:{variant}:{amount:.2f}"}],
         [{"type": "callback", "text": "Назад", "payload": "donate_menu"}]],
    )


async def create_support_payment(user_id, amount):
    amount_str = f"{amount:.2f}"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json={
                "amount": {"value": amount_str, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://maminpomoshnik.ru/payment/success"},
                "capture": True,
                "description": "Добровольная поддержка развития цифрового сервиса",
                "receipt": {"customer": {"email": "6038484@mail.ru"}, "items": [{
                    "description": "Добровольная поддержка развития цифрового сервиса", "quantity": "1.00",
                    "amount": {"value": amount_str, "currency": "RUB"}, "vat_code": 1,
                    "payment_subject": "service", "payment_mode": "full_payment"
                }]},
                "metadata": {"user_id": user_id, "product_code": "support_project", "product_type": "support"}
            },
            headers={"Idempotence-Key": str(uuid.uuid4()), "Content-Type": "application/json"},
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET),
        )
        if not r.is_success:
            raise RuntimeError(f"ЮКасса: {r.status_code} {r.text[:300]}")
        return r.json()


def save_support_payment(payment_id, user_id, amount, variant, platform="max"):
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
            (payment_id, now_iso, "max", user_id, "support_project", amount, "RUB", ""),
        )
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
        conn.commit(); return True, amount
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


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
                        if product_code == "support_project":
                            processed, amount = process_support_payment(payment_id, user_id)
                            if not processed: continue
                            log_analytics_event("support_payment_success", user_id, "support_project", amount)
                            await send_message(
                                user_id,
                                "Спасибо за поддержку ❤️ Благодаря вам «Мамин помощник» сможет развиваться и оставаться бесплатным для родителей.",
                                [[{"type": "callback", "text": "Вернуться в главное меню", "payload": "back_menu"}]],
                            )
                            try:
                                await send_message(OWNER_ID, f"💛 Поддержка проекта (MAX)\n\nUser ID: {user_id}\nСумма: {amount} ₽\nPayment ID: {payment_id}")
                            except Exception as exc:
                                logging.error(f"Ошибка уведомления владельца о поддержке MAX: {exc}")
                            continue
                        if product_code == PERSONAL_REVIEW_PRODUCT_CODE:
                            processed, review_id = process_personal_review_payment_max(payment_id, user_id)
                            if not processed: continue
                            log_analytics_event("personal_review_payment_success", user_id, PERSONAL_REVIEW_PRODUCT_CODE, payment_id)
                            try:
                                await send_message(user_id, "Заявка принята ✅\n\nЛичный разбор готовит автор проекта. Ответ придёт сюда, в этот чат.")
                            except Exception as exc:
                                logging.error(f"Ошибка уведомления клиента о заявке на разбор (MAX): {exc}")
                            try:
                                await send_message(
                                    OWNER_ID,
                                    f"🧩 Новая заявка на личный разбор (MAX) №{review_id} — {PERSONAL_REVIEW_PRICE_RUB} ₽\nUser ID: {user_id}\nPayment ID: {payment_id}",
                                    [
                                        [{"type": "callback", "text": "Открыть заявку", "payload": f"pr_open:{review_id}"}],
                                        [{"type": "callback", "text": "Взять в работу", "payload": f"pr_take:{review_id}"}],
                                    ],
                                )
                            except Exception as exc:
                                logging.error(f"Ошибка уведомления владельца о заявке на разбор (MAX): {exc}")
                            continue
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
                        if product_code == "support_project":
                            log_analytics_event("support_payment_failed", user_id, "support_project")
                            try:
                                await send_message(user_id, "Оплата не завершена. Все функции «Маминого помощника» по-прежнему доступны бесплатно.")
                            except Exception as exc:
                                logging.error(f"Ошибка уведомления об отмене поддержки MAX: {exc}")
                        elif product_code == PERSONAL_REVIEW_PRODUCT_CODE:
                            mark_personal_review_canceled_max(payment_id)
                            log_analytics_event("personal_review_payment_failed", user_id, PERSONAL_REVIEW_PRODUCT_CODE, payment_id)
                            try:
                                await send_message(user_id, "Оплата не завершена. Заявка на личный разбор не оформлена — попробуйте ещё раз из мини-приложения.")
                            except Exception as exc:
                                logging.error(f"Ошибка уведомления об отмене заявки на разбор (MAX): {exc}")
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

Я Мамин Помощник — бесплатный личный AI-помощник для беременности, ребёнка и поддержки мамы.

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

def claim_persistent_command_lock(lock_key, ttl_seconds=86400):
    """Атомарно блокирует повтор служебной команды, включая ретраи после перезапуска."""
    now = datetime.now(MOSCOW_TZ)
    cutoff = (now - timedelta(seconds=ttl_seconds)).isoformat()
    with db_connect() as conn:
        conn.execute("DELETE FROM command_locks WHERE created_at < ?", (cutoff,))
        row = conn.execute("SELECT created_at FROM command_locks WHERE lock_key=?", (lock_key,)).fetchone()
        if row:
            return False
        conn.execute(
            "INSERT INTO command_locks(lock_key, created_at) VALUES (?, ?)",
            (lock_key, now.isoformat()),
        )
        return True


def release_persistent_command_lock(lock_key):
    """Снимает временную блокировку, если публикация не состоялась."""
    with db_connect() as conn:
        conn.execute("DELETE FROM command_locks WHERE lock_key=?", (lock_key,))


def owner_home_text_max():
    return "👑 Кабинет владельца «Мамин помощник»\n\nВыберите раздел:"


def owner_cabinet_buttons_max():
    return [
        [{"type": "callback", "text": "📊 Сегодня", "payload": "owner_cab:today"},
         {"type": "callback", "text": "💰 Продажи", "payload": "owner_cab:sales"}],
        [{"type": "callback", "text": "👥 Пользователи", "payload": "owner_cab:users"},
         {"type": "callback", "text": "📈 Воронка", "payload": "owner_cab:funnel"}],
        [{"type": "callback", "text": "🎯 Источники рекламы", "payload": "owner_cab:sources"},
         {"type": "callback", "text": "📣 Реклама", "payload": "owner_cab:ads"}],
        [{"type": "callback", "text": "⚠️ Ошибки", "payload": "owner_cab:errors"},
         {"type": "callback", "text": "💬 Обратная связь", "payload": "owner_cab:feedback"}],
        [{"type": "callback", "text": "📤 Рассылка", "payload": "owner_cab:broadcast"}],
        [{"type": "callback", "text": "📄 Экспорт / Google-таблица", "payload": "owner_cab:export"}],
        [{"type": "callback", "text": "🧪 Проверка бота", "payload": "owner_cab:check"}],
        [{"type": "callback", "text": "🏠 В обычное меню", "payload": "back_menu"}],
    ]


def owner_back_buttons_max():
    return [[{"type": "callback", "text": "◀️ Назад", "payload": "owner_cab:home"},
             {"type": "callback", "text": "🏠 В обычное меню", "payload": "back_menu"}]]


def _owner_conn_max(path):
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _owner_table_exists_max(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _owner_scalar_max(path, sql, params=(), default=0):
    try:
        with _owner_conn_max(path) as conn:
            return conn.execute(sql, params).fetchone()[0] or default
    except Exception:
        return default


def _owner_sales_max(path, since):
    try:
        with _owner_conn_max(path) as conn:
            if _owner_table_exists_max(conn, "sales_events"):
                rows = conn.execute("SELECT product_code, amount FROM sales_events WHERE created_at>=?", (since,)).fetchall()
            else:
                rows = conn.execute("SELECT product_code, amount FROM payments WHERE status IN ('processed','succeeded') AND updated_at>=?", (since,)).fetchall()
        products = {}
        total = 0.0
        for row in rows:
            total += float(row["amount"] or 0)
            code = row["product_code"] or "unknown"
            products[code] = products.get(code, 0) + 1
        return len(rows), total, products
    except Exception:
        return 0, 0.0, {}


def _owner_event_count_max(path, since, names=None, source_prefix=None):
    try:
        with _owner_conn_max(path) as conn:
            if not _owner_table_exists_max(conn, "analytics_events"):
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


def _owner_top_sources_max(path, since, limit=3):
    try:
        with _owner_conn_max(path) as conn:
            if not _owner_table_exists_max(conn, "analytics_events"):
                return []
            return conn.execute(
                "SELECT COALESCE(NULLIF(source,''),'organic') source, COUNT(*) cnt "
                "FROM analytics_events WHERE created_at>=? AND (source LIKE 'channel_%' OR source LIKE 'ref_%') "
                "GROUP BY source ORDER BY cnt DESC LIMIT ?",
                (since, limit),
            ).fetchall()
    except Exception:
        return []


def _owner_user_counts_max(path, platform):
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
    today = datetime.now().date().isoformat()
    week = (datetime.now() - timedelta(days=7)).isoformat()
    month = (datetime.now() - timedelta(days=30)).isoformat()
    return {
        "total": _owner_scalar_max(path, "SELECT COUNT(*) FROM users"),
        "today": _owner_scalar_max(path, today_sql, (today,)),
        "week": _owner_scalar_max(path, today_sql, (week,)),
        "month": _owner_scalar_max(path, today_sql, (month,)),
        "complete": _owner_scalar_max(path, complete_sql),
        "pregnant": _owner_scalar_max(path, pregnant_sql),
        "mama": _owner_scalar_max(path, mama_sql),
    }


def _owner_product_lines_max(products):
    names = {**{k: v["name"] for k, v in PLAN_CATALOG.items()}, **{k: v["name"] for k, v in ONE_TIME_PRODUCTS.items()}}
    if not products:
        return "нет"
    return ", ".join(f"{names.get(k, k)}: {v}" for k, v in sorted(products.items(), key=lambda item: (-item[1], item[0]))[:8])


def owner_report_max(section):
    now = datetime.now()
    today = now.date().isoformat()
    week = (now - timedelta(days=7)).isoformat()
    month = (now - timedelta(days=30)).isoformat()
    dbs = [("TG", TG_DB_PATH), ("MAX", DB)]
    if section == "today":
        tg = _owner_user_counts_max(TG_DB_PATH, "tg")
        mx = _owner_user_counts_max(DB, "max")
        sales = [_owner_sales_max(path, today) for _, path in dbs]
        pay_count = sum(item[0] for item in sales)
        pay_sum = sum(item[1] for item in sales)
        top_rows = []
        for label, path in dbs:
            top_rows.extend((label, r["source"], r["cnt"]) for r in _owner_top_sources_max(path, today))
        top = "\n".join(f"• {src} ({label}): {cnt}" for label, src, cnt in top_rows[:3]) or "нет данных"
        scenarios = ["doctor", "sleep", "feeding", "psycho", "tantrum", "garden", "school", "gadgets", "grandma"]
        scen = "\n".join(
            f"{key}: {sum(_owner_event_count_max(path, today, names=('free_result_started','funnel_question_opened'), source_prefix=f'channel_{key}') for _, path in dbs)}"
            for key in scenarios
        )
        return (
            "📊 Сегодня\n\n"
            f"Новые TG: {tg['today']}\nНовые MAX: {mx['today']}\nВсего новых: {tg['today'] + mx['today']}\n"
            f"Активных по событиям: {sum(_owner_event_count_max(path, today) for _, path in dbs)}\n"
            f"Рекламные payload: {sum(_owner_event_count_max(path, today, source_prefix='channel_') for _, path in dbs)}\n"
            f"Оплат: {pay_count}\nСумма: {pay_sum:.0f} ₽\n"
            f"Ошибки: {sum(_owner_event_count_max(path, today, names=('error_logged',)) for _, path in dbs)}\n\n"
            f"Топ источников:\n{top}\n\nБесплатные сценарии:\n{scen}"
        )
    if section == "sales":
        lines = ["💰 Продажи"]
        for label, since in (("Сегодня", today), ("7 дней", week), ("30 дней", month)):
            sales = [_owner_sales_max(path, since) for _, path in dbs]
            count = sum(item[0] for item in sales)
            amount = sum(item[1] for item in sales)
            products = {}
            for _, _, prod in sales:
                for k, v in prod.items():
                    products[k] = products.get(k, 0) + v
            lines.append(f"\n{label}: {count} оплат, {amount:.0f} ₽, средний чек {(amount / count if count else 0):.0f} ₽\nПродукты: {_owner_product_lines_max(products)}")
        tg30 = _owner_sales_max(TG_DB_PATH, month)
        mx30 = _owner_sales_max(DB, month)
        lines.append(f"\nПлатформы 30 дней: TG {tg30[0]} / {tg30[1]:.0f} ₽, MAX {mx30[0]} / {mx30[1]:.0f} ₽")
        return "\n".join(lines)
    if section == "users":
        tg = _owner_user_counts_max(TG_DB_PATH, "tg")
        mx = _owner_user_counts_max(DB, "max")
        paid = sum(_owner_scalar_max(path, "SELECT COUNT(*) FROM subscriptions WHERE plan IN ('start','pro','pro_year') AND COALESCE(sub_end,'')<>''") for _, path in dbs)
        one_time = sum(_owner_scalar_max(path, "SELECT COUNT(DISTINCT user_id) FROM purchases") for _, path in dbs)
        return (
            "👥 Пользователи\n\n"
            f"Всего: {tg['total'] + mx['total']} (TG {tg['total']}, MAX {mx['total']})\n"
            f"Новые: сегодня {tg['today'] + mx['today']}, 7 дней {tg['week'] + mx['week']}, 30 дней {tg['month'] + mx['month']}\n"
            f"Активные: сегодня {sum(_owner_event_count_max(path, today) for _, path in dbs)}, 7 дней {sum(_owner_event_count_max(path, week) for _, path in dbs)}\n"
            f"Беременные: {tg['pregnant'] + mx['pregnant']}\nМамы: {tg['mama'] + mx['mama']}\n"
            f"Профиль заполнен: {tg['complete'] + mx['complete']}\nБез завершённого профиля: {tg['total'] + mx['total'] - tg['complete'] - mx['complete']}\n"
            f"Платные тарифы: {paid}\nРазовые покупки: {one_time}"
        )
    if section == "funnel":
        steps = [("Перешёл по ссылке", ("channel_click", "ad_payload_opened")), ("Start / bot_started", ("user_start",)), ("Профиль заполнен", ("profile_completed",)), ("Бесплатный сценарий", ("free_result_started", "funnel_question_opened")), ("Бесплатный результат", ("free_result_completed",)), ("Платный оффер", ("paid_offer_shown",)), ("Нажал оплату", ("payment_clicked",)), ("Оплатил", ("payment_success", "payment_succeeded"))]
        return "\n".join(["📈 Воронка за 30 дней"] + [f"{title}: {sum(_owner_event_count_max(path, month, names=names) for _, path in dbs)}" for title, names in steps])
    if section == "sources":
        sources = {}
        for _, path in dbs:
            for row in _owner_top_sources_max(path, month, 20):
                sources[row["source"]] = sources.get(row["source"], 0) + row["cnt"]
        lines = ["🎯 Источники рекламы за 30 дней"]
        if not sources:
            lines.append("Данных по источникам пока нет.")
        for src, cnt in sorted(sources.items(), key=lambda item: (-item[1], item[0]))[:15]:
            paid = sum(_owner_event_count_max(path, month, names=("payment_success", "payment_succeeded"), source_prefix=src) for _, path in dbs)
            lines.append(f"• {src}: входов {cnt}, оплат {paid}, конверсия {(paid / cnt * 100 if cnt else 0):.1f}%")
        return "\n".join(lines)
    if section == "ads":
        topics = [("врач", "channel_doctor"), ("сон", "channel_sleep"), ("питание", "channel_feeding"), ("психолог", "channel_psycho"), ("истерики", "channel_tantrum"), ("садик", "channel_garden"), ("школа", "channel_school"), ("гаджеты", "channel_gadgets"), ("бабушки", "channel_grandma")]
        lines = ["📣 Реклама", "Telegram:"]
        for title, payload in topics:
            lines.append(f"• {title}: https://t.me/MaminPomoshnikAI_bot?start={payload}")
            lines.append(f"  ya/vk/land: {payload}_ya1 | {payload}_vk1 | {payload}_land1")
        if MAX_BOT_PUBLIC_URL:
            lines.append("\nMAX:")
            lines.extend(f"• {title}: {MAX_BOT_PUBLIC_URL}?start={payload}" for title, payload in topics)
        return "\n".join(lines)
    if section == "errors":
        return f"⚠️ Ошибки\n\nСегодня: {sum(_owner_event_count_max(path, today, names=('error_logged',)) for _, path in dbs)}\nЗа 7 дней: {sum(_owner_event_count_max(path, week, names=('error_logged',)) for _, path in dbs)}\n\nSystemd journal из бота не читается."
    if section == "feedback":
        lines = ["💬 Обратная связь"]
        try:
            with _owner_conn_max(DB) as conn:
                rows = conn.execute("SELECT created_at, review FROM reviews ORDER BY id DESC LIMIT 10").fetchall()
                lines.extend(f"• {r['created_at'][:16]}: {str(r['review'])[:160]}" for r in rows)
        except Exception:
            pass
        if len(lines) == 1:
            lines.append("Свежих отзывов не найдено.")
        return "\n".join(lines)
    if section == "broadcast":
        return f"📤 Рассылка\n\nРассылка пока в безопасном режиме.\nПотенциальные получатели: TG {_owner_user_counts_max(TG_DB_PATH, 'tg')['total']}, MAX {_owner_user_counts_max(DB, 'max')['total']}.\n\nМассовая отправка из этого кабинета не выполняется."
    if section == "export":
        return "📄 Экспорт / Google-таблица\n\nИнтеграция Google Sheets уже есть для пользователей/продаж/отзывов.\nОтдельный экспорт кабинета подключается отдельной задачей.\nЛисты: Mama TG, Mama MAX, Продажи, Реклама, Ошибки, Воронка."
    if section == "check":
        return f"🧪 Проверка бота\n\nMAX version: {APP_VERSION}\nMAX health: /health настроен\nProduction TG: /root/mama_bot.py\nProduction MAX: /root/mama_max_bot.py\n\nПерезапуск сервисов из кабинета не выполняется."
    return owner_home_text_max()


async def process_command(chat_id, user_id, text, username="", first_name=""):
    command_text = text.strip()
    if command_text.startswith("/") and get_user(user_id, username, first_name).get("step") == "fb2026_suggest":
        set_step(user_id, "idle")
    if command_text.startswith("/") and get_user(user_id, username, first_name).get("step") == "cf2026_feedback":
        set_step(user_id, "idle")

    # Служебная команда доступна всем и помогает узнать реальный MAX user_id.
    if command_text.lower() in ("/my_id", "/myid"):
        await send_message(chat_id, f"Ваш MAX user_id: {user_id}")
        return
    if command_text.lower() in ("/owner", "/admin", "owner", "admin"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        await send_message(chat_id, owner_home_text_max(), owner_cabinet_buttons_max())
        return
    normalized_command = command_text.lower()
    if normalized_command in ("/test_channel_visual", "test_channel_visual"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Команда доступна только владельцу.")
            return
        await send_message(chat_id, "ℹ️ Генерация картинок отключена. Канал публикует текстовые посты.")
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
        await send_message(chat_id,
            "⚠️ Это удалит ваш профиль и сохранённые данные в боте. Платёжный журнал не удаляется.\n\nУдалить данные?",
            [[{"type": "callback", "text": "Удалить данные", "payload": "reset_me_confirm"}],
             [{"type": "callback", "text": "Отмена", "payload": "reset_me_cancel"}]])
        return

    if text.strip().lower() == "/reset_me_now_legacy_disabled":
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
            await send_message(chat_id, f"🤰 Ты {m_label}\n\nЧем могу помочь? 💕", pregnant_menu_buttons(user_id))
        elif birth_date:
            await send_message(chat_id, f"Привет, {name}! 🤍\n\nЧем могу помочь?", main_menu_buttons(user_id))
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons(user_id))
        return

    if step == "donate_custom_amount":
        set_step(user_id, "idle")
        raw = (text or "").replace(",", ".").strip()
        try:
            amount = float(raw)
        except ValueError:
            amount = None
        if amount is None or not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
            await send_message(chat_id, f"Пожалуйста, введи сумму от {DONATE_MIN_AMOUNT} до {DONATE_MAX_AMOUNT} рублей, например: 250", kb_donate_menu())
            return
        await send_donate_confirm(chat_id, round(amount, 2), "custom")
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
        log_analytics_event("profile_completed", user_id, pending_start)
        lbl = age_label(m)
        if pending_start:
            await send_message(chat_id, f"✅ Малышу {lbl}")
            landing_text, landing_buttons = channel_landing_max(pending_start)
            await send_message(chat_id, landing_text, landing_buttons)
        else:
            await send_message(chat_id, f"✅ Малышу {lbl}\n\nЧем могу помочь? 💕", main_menu_buttons(user_id))
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
        log_analytics_event("profile_completed", user_id, pending_start)
        if pending_start:
            await send_message(chat_id, f"✅ Ты на {w} неделе беременности")
            landing_text, landing_buttons = channel_landing_max(pending_start)
            await send_message(chat_id, landing_text, landing_buttons)
        else:
            await send_message(chat_id, f"✅ Ты на {w} неделе беременности\n\nЧем могу помочь? 💕", pregnant_menu_buttons(user_id))
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

    if step == "fb2026_suggest" and text.strip().startswith("/"):
        set_step(user_id, "idle")
        await send_message(
            chat_id,
            "Команда не записана как предложение.",
            main_menu_buttons(user_id) if birth_date else start_buttons(user_id),
        )
        return

    if step == "fb2026_suggest":
        set_step(user_id, "idle")
        try:
            await send_message(OWNER_ID,
                "💡 Новое предложение\n\nПлатформа: MAX\n"
                f"Имя: {first_name or '—'}\nUsername: {username or '—'}\nUser ID: {user_id}\nПредложение:\n{text}")
        except Exception as exc:
            logging.error("fb2026 suggestion owner notify error: %s", exc)
        save_review(user_id, username, first_name, f"ПРЕДЛОЖЕНИЕ (feedback_features_2026_09): {text}")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, f"ПРЕДЛОЖЕНИЕ: {text}"))
        await send_message(chat_id, "Спасибо ❤️ Предложение отправлено. Я обязательно его прочитаю.", main_menu_buttons())
        return

    if step == "cf2026_feedback" and text.strip().startswith("/"):
        set_step(user_id, "idle")
        await send_message(
            chat_id,
            "Команда не записана как отзыв.",
            main_menu_buttons(user_id) if birth_date else start_buttons(user_id),
        )
        return

    if step == "cf2026_feedback":
        set_step(user_id, "idle")
        try:
            await send_message(OWNER_ID,
                "🥣 Отзыв о «Прикорм 6+»\n\nПлатформа: MAX\n"
                f"Имя: {first_name or '—'}\nUsername: {username or '—'}\nUser ID: {user_id}\n\nОтзыв:\n{text}")
        except Exception as exc:
            logging.error("cf2026 feedback owner notify error: %s", exc)
        save_review(user_id, username, first_name, f"ОТЗЫВ О ПРИКОРМ 6+ ({CF_CAMPAIGN_KEY}): {text}")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, f"ОТЗЫВ (Прикорм 6+): {text}"))
        await send_message(chat_id, "Спасибо ❤️ Ваше мнение отправлено. Оно поможет сделать «Прикорм 6+» полезнее.", main_menu_buttons())
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
            start_buttons(user_id))
        return

    menu = pregnant_menu_buttons(user_id) if birth_date.startswith("pdr:") else main_menu_buttons(user_id)
    await send_message(chat_id, "Выбери действие из меню 👇", menu)


def save_channel_poll_vote(user_id, payload):
    """Сохраняет или обновляет голос пользователя из callback/deeplink MAX."""
    if not payload.startswith("channel_poll_"):
        return False
    parts = payload.split("_", 3)
    if len(parts) != 4:
        return False
    _, _, poll_key, option_key = parts
    if not poll_key or not option_key:
        return False
    with db_connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channel_poll_votes (poll_key, user_id, option_key, created_at) VALUES (?,?,?,?)",
            (poll_key, user_id, option_key, datetime.now().isoformat()),
        )
    return True


async def process_callback(chat_id, user_id, payload, first_name=""):
    get_user(user_id, "", first_name)
    if payload.startswith("owner_cab:"):
        if user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        section = payload.split(":", 1)[1]
        if section == "home":
            await send_message(chat_id, owner_home_text_max(), owner_cabinet_buttons_max())
        else:
            await send_message(chat_id, owner_report_max(section), owner_back_buttons_max())
        return

    if payload.startswith("pr_open:"):
        if not OWNER_ID or user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        try:
            review_id = int(payload.split(":", 1)[1])
        except (IndexError, ValueError):
            await send_message(chat_id, "Некорректная заявка")
            return
        row = get_personal_review_max(review_id)
        if not row:
            await send_message(chat_id, "Заявка не найдена")
            return
        reply_label = "Email" if row["preferred_reply"] == "email" else "MAX"
        lines = [
            f"Заявка №{review_id} — {_pr_status_label_max(row['status'])}",
            f"User ID: {row['user_id']}",
            f"Способ ответа: {reply_label}",
        ]
        if row["preferred_reply"] == "email" and row["email"]:
            lines.append(f"Email клиента: {row['email']}")
        lines.append("")
        lines.append("Текст ситуации:")
        lines.append(row["situation_text"])
        buttons = None
        if row["status"] == "paid":
            buttons = [[{"type": "callback", "text": "Взять в работу", "payload": f"pr_take:{review_id}"}]]
        await send_message(chat_id, "\n".join(lines), buttons)
        return

    if payload.startswith("pr_take:"):
        if not OWNER_ID or user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        try:
            review_id = int(payload.split(":", 1)[1])
        except (IndexError, ValueError):
            await send_message(chat_id, "Некорректная заявка")
            return
        ok = take_personal_review_max(review_id)
        if not ok:
            row = get_personal_review_max(review_id)
            current = _pr_status_label_max(row["status"]) if row else "не найдена"
            await send_message(chat_id, f"Уже {current}")
            return
        set_step(user_id, f"pr_voice_{review_id}")
        await send_message(chat_id, f"Заявка №{review_id} взята в работу. Отправь одно голосовое сообщение с ответом — оно будет привязано к этой заявке.")
        return

    if payload.startswith("pr_rerecord:"):
        if not OWNER_ID or user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        try:
            review_id = int(payload.split(":", 1)[1])
        except (IndexError, ValueError):
            await send_message(chat_id, "Некорректная заявка")
            return
        row = get_personal_review_max(review_id)
        if not row or row["status"] != "in_review":
            await send_message(chat_id, "Заявка недоступна для перезаписи")
            return
        set_step(user_id, f"pr_voice_{review_id}")
        await send_message(chat_id, f"Хорошо, пришли новое голосовое для заявки №{review_id}.")
        return

    if payload.startswith("pr_send:"):
        if not OWNER_ID or user_id != OWNER_ID:
            await send_message(chat_id, "Недоступно")
            return
        try:
            review_id = int(payload.split(":", 1)[1])
        except (IndexError, ValueError):
            await send_message(chat_id, "Некорректная заявка")
            return
        row = get_personal_review_max(review_id)
        if not row or row["status"] != "in_review" or not row["answer_path"]:
            await send_message(chat_id, "Заявка не готова к отправке")
            return
        client_user_id = row["user_id"]
        preferred_reply = row["preferred_reply"]
        voice_path = row["answer_path"]
        if not os.path.exists(voice_path):
            await send_message(chat_id, f"Голосовой файл заявки №{review_id} не найден на сервере — запиши заново.")
            return
        if preferred_reply == "email":
            delivered = mark_personal_review_answered_max(review_id)
            if not delivered:
                await send_message(chat_id, "Ответ уже был отправлен")
                return
            await send_message(
                chat_id,
                f"Заявка №{review_id}: клиент выбрал ответ по email.\n"
                f"Email клиента: {row['email'] or '—'}\n\n"
                "Голосовое сохранено — отправь его на почту клиента вручную. Ниже пересылаю запись для удобства.",
            )
            try:
                owner_chat_id = get_saved_max_chat_id(user_id) or chat_id
                await send_personal_review_voice_max(owner_chat_id, voice_path)
            except Exception as exc:
                logging.error(f"Не удалось переслать голосовое владельцу MAX для заявки {review_id}: {exc}")
        else:
            try:
                client_chat_id = get_saved_max_chat_id(client_user_id) or client_user_id
                sent = await send_personal_review_voice_max(client_chat_id, voice_path)
                if not sent:
                    raise RuntimeError("MAX не подтвердил доставку файла")
                await send_message(client_chat_id, "Ваш разбор готов 🎧")
            except Exception as exc:
                logging.error(f"Не удалось отправить голосовое клиенту MAX по заявке {review_id}: {exc}")
                await send_message(chat_id, f"Не удалось отправить сообщение клиенту (заявка №{review_id}): {exc}")
                return
            delivered = mark_personal_review_answered_max(review_id)
            if not delivered:
                await send_message(chat_id, "Ответ уже был отправлен")
                return
            await send_message(chat_id, f"Готово — ответ отправлен клиенту (заявка №{review_id}).")
        log_analytics_event("personal_review_answered", client_user_id, PERSONAL_REVIEW_PRODUCT_CODE, str(review_id))
        return

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
            pregnant_menu_buttons(user_id) if birth_date.startswith("pdr:") else main_menu_buttons(user_id) if birth_date else start_buttons(user_id))
        return

    if payload.startswith("channel_poll_"):
        if save_channel_poll_vote(user_id, payload):
            await send_message(chat_id, "Спасибо за ответ 🤍 Ваш голос учтён.")
        return

    if payload == "noop":
        return

    if payload == "donate_menu":
        log_analytics_event("support_open", user_id)
        await send_message(
            chat_id,
            "Поддержать проект\n\n"
            "«Мамин помощник» остаётся бесплатным для всех родителей. Если проект оказался полезен, "
            "вы можете поддержать его развитие любой удобной суммой. Это добровольная благодарность — "
            "все функции доступны и без оплаты.",
            kb_donate_menu(),
        )
        return

    if payload.startswith("donate_amt_"):
        variant = payload.replace("donate_amt_", "", 1)
        if variant == "custom":
            log_analytics_event("support_custom", user_id)
            set_step(user_id, "donate_custom_amount")
            await send_message(chat_id, f"Введи сумму в рублях (от {DONATE_MIN_AMOUNT} до {DONATE_MAX_AMOUNT}):")
            return
        try:
            amount = float(variant)
        except ValueError:
            return
        if not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
            return
        log_analytics_event(f"support_amount_{variant}", user_id)
        await send_donate_confirm(chat_id, amount, variant)
        return

    if payload.startswith("donate_confirm:"):
        try:
            _, variant, amount_str = payload.split(":", 2)
            amount = float(amount_str)
        except (ValueError, IndexError):
            await send_message(chat_id, "Не удалось определить сумму. Попробуй ещё раз.", kb_donate_menu())
            return
        if not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
            await send_message(chat_id, "Некорректная сумма.", kb_donate_menu())
            return
        try:
            payment = await create_support_payment(user_id, amount)
            payment_id = payment.get("id", "")
            pay_url = payment.get("confirmation", {}).get("confirmation_url", "")
            if not payment_id or not pay_url:
                raise RuntimeError("ЮКасса не вернула ссылку или id")
            save_support_payment(payment_id, user_id, amount, variant, "max")
            log_analytics_event("support_payment_created", user_id, variant, amount_str)
            await send_message(
                chat_id,
                "Спасибо! Нажми кнопку ниже, чтобы завершить оплату.",
                [[{"type": "link", "text": f"💳 Оплатить {amount:.0f} ₽", "url": pay_url}],
                 [{"type": "callback", "text": "Назад", "payload": "donate_menu"}]],
            )
        except Exception as exc:
            logging.error(f"Ошибка создания платежа поддержки MAX: {exc}")
            await send_message(chat_id, "Не удалось создать платёж. Попробуй позже.", kb_donate_menu())
        return

    if payload == "reset_me_cancel":
        await send_message(chat_id, "Отменено. Данные не удалены.")
        return

    if payload == "reset_me_confirm":
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

    if payload == "back_menu":
        set_step(user_id, "idle")
        if birth_date and birth_date.startswith("pdr:"):
            weeks_cur = calc_pregnancy_weeks(birth_date.replace("pdr:", ""))
            await send_message(chat_id, f"🤰 Ты на {weeks_cur} неделе беременности\n\nЧем могу помочь? 💕", pregnant_menu_buttons(user_id))
        elif birth_date:
            await send_message(chat_id, f"Чем могу помочь? 💕", main_menu_buttons(user_id))
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons(user_id))
        return

    if payload == "main_menu":
        set_step(user_id, "idle")
        if birth_date.startswith("pdr:"):
            await send_message(chat_id, f"🤰 Ты {m_label}\n\nЧем могу помочь? 💕", pregnant_menu_buttons(user_id))
        elif birth_date:
            await send_message(chat_id, f"Чем могу помочь? 💕", main_menu_buttons(user_id))
        else:
            await send_message(chat_id, WELCOME_TEXT.format(name=name),
                start_buttons(user_id))
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
            "Все функции «Маминого помощника» и так доступны бесплатно — приглашение просто помогает больше мам узнать о проекте.\n\n"
            f"Приглашено: {invited}\n"
            f"Бонусов начислено: {start_rewards}"
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

    if payload == "fb2026:suggest":
        set_step(user_id, "fb2026_suggest")
        await send_message(chat_id,
            "💬 Напишите одним сообщением, какую функцию или возможность вы хотели бы добавить "
            "в «Мамин Помощник».\n\nМожно написать совсем коротко — я обязательно прочитаю ❤️")
        return

    if payload == "cf2026:feedback":
        set_step(user_id, "cf2026_feedback")
        await send_message(chat_id,
            "💬 Напишите одним сообщением, как вам новый раздел «Прикорм 6+».\n\n"
            "Что понравилось? Чего не хватает? Что стоит сделать удобнее?\n\n"
            "Я обязательно прочитаю ❤️")
        return

    if payload == "fb2026:like":
        with db_connect() as conn:
            row = conn.execute("SELECT username, first_name FROM users WHERE user_id=?", (user_id,)).fetchone()
            cur = conn.execute(
                "INSERT OR IGNORE INTO feedback_campaign_likes(campaign_key, platform, user_id, created_at) VALUES (?, 'max', ?, ?)",
                (FEEDBACK_CAMPAIGN_KEY, user_id, datetime.now().isoformat()),
            )
            already = cur.rowcount == 0
        if already:
            await send_message(chat_id, "Спасибо ❤️ Ваш ответ уже получен.")
            return
        fb_username = (row[0] if row else "") or ""
        fb_first_name = (row[1] if row else "") or first_name or ""
        try:
            await send_message(OWNER_ID,
                "❤️ Положительная обратная связь\n\nПлатформа: MAX\n"
                f"Имя: {fb_first_name or '—'}\nUsername: {fb_username or '—'}\nUser ID: {user_id}\nОтвет: Всё нравится")
        except Exception as exc:
            logging.error("fb2026 like owner notify error: %s", exc)
        save_review(user_id, fb_username, fb_first_name, "ПОЛОЖИТЕЛЬНАЯ ОБРАТНАЯ СВЯЗЬ (feedback_features_2026_09): Всё нравится")
        asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, fb_first_name, fb_username, "Всё нравится (кампания feedback_features_2026_09)"))
        await send_message(chat_id, "Спасибо ❤️ Очень приятно это знать. Такие сообщения действительно помогают продолжать развивать приложение.")
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

    if payload in {"pay_premium", "premium_info"} or payload.startswith("pay_plan_") or payload.startswith("buy_"):
        # Старые тарифные ссылки/кнопки больше не продают функционал — он бесплатный.
        await send_message(chat_id,
            "Все текущие функции «Маминого помощника» теперь доступны бесплатно.",
            [[{"type": "callback", "text": "❤️ Поддержать проект", "payload": "donate_menu"}],
             [{"type": "callback", "text": "🏠 Вернуться в главное меню", "payload": "back_menu"}]])
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
    use_photo_credit = False  # Проект бесплатный: старые кредиты за анализ фото больше не расходуются
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

# 3 поста в день, 8 рубрик практического родительского контента (без ежедневных
# выдуманных семейных историй). Категории: REC рецепт, WHATIF воспитание/поведение,
# HEALTH здоровье-сон-врач, AGE сад/школа/развитие по возрасту, MOM мама тоже человек,
# DAD папин взгляд (короткое наблюдение, не сюжет), FAM бабушки-дедушки-семья,
# SAVE сохрани-пригодится (также резерв вместо личной истории без фактов владельца).
# Темы и форматы вращаются по дням и сохраняются в БД, чтобы канал не повторялся.

CHANNEL_CONTENT_LIBRARY_PATH = "/root/mama_channel_content.json"

# Редакционная архитектура: свободная AI-генерация поста с нуля больше не используется.
# Основа каждой публикации — заранее написанный и вручную проверенный материал из
# библиотеки CHANNEL_CONTENT_LIBRARY_PATH (минимум 120 готовых постов, общая с ботом в
# Telegram). AI-адаптация (лёгкая правка вступления/порядка абзацев/CTA-фразы)
# необязательна и по умолчанию выключена — надёжный дефолт после FINAL_FAIL свободной
# генерации в предыдущей задаче (JOB_20260711_175411). Включать только после отдельной
# проверки владельцем.
CHANNEL_AI_ADAPTATION_ENABLED = False

CHANNEL_LIBRARY_MAX_CHARS = {
    "REC": 1800, "WHATIF": 1200, "HEALTH": 1200, "AGE": 1200,
    "MOM": 1100, "DAD": 650, "FAM": 1100, "SAVE": 1100,
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
    "Ты ведёшь канал «Мамин помощник» в MAX — полезно о детях, семье и родительской жизни простыми человеческими "
    "словами. Твой голос — это голос отца троих дочерей, но ты не обязан быть героем каждого поста и не должен "
    "ежедневно сочинять события своей семьи: тебе запрещено выдумывать конкретные биографические события автора, "
    "жены и дочерей. Настоящие личные истории — отдельная серия и не твоя задача. "
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
    import re
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
    import re
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
    "Ты редактор канала «Мамин помощник» в MAX. Тебе дают готовый, уже проверенный пост. "
    "Разрешено ТОЛЬКО: слегка изменить вступление, поменять местами два-три абзаца (если "
    "смысл не меняется), адаптировать обращение к читателю, немного сократить или "
    "расширить текст, изменить финальный вопрос. Категорически запрещено: придумывать "
    "новые факты, менять любые цифры и количества, менять рецепт, менять шаги "
    "приготовления, менять медицинский смысл, добавлять личные истории или прямую речь, "
    "добавлять статистику и исследования, менять итоговый смысл текста. Верни только "
    "финальный текст поста без пояснений и без заголовка."
)


def _channel_number_tokens(text):
    import re
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
    raw = await generate_text(CHANNEL_ADAPTATION_SYSTEM_PROMPT, prompt, model="gpt-4o-mini")
    if not ai_answer_success(raw):
        return None
    candidate = clean_text(raw or "").strip()
    if not candidate:
        return None
    if _channel_number_tokens(candidate) != _channel_number_tokens(original):
        logging.warning("Канал MAX: адаптация %s изменила цифры, используется оригинал", item.get("id"))
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
    max_chars = CHANNEL_LIBRARY_MAX_CHARS.get(category, 1800)
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
# рубрики cta_allowed — CTA не показывается вовсе (см. post_max_slot).
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


def max_bot_deeplink(payload="channel_today"):
    return f"{MAX_BOT_PUBLIC_URL}?start={payload}"


def channel_open_button(text="✨ Открыть помощника на сегодня", payload="channel_today"):

    if not MAX_BOT_CHANNEL_LINK:
        logging.error("Кнопка перехода в бот не добавлена: не задан MAX_BOT_CHANNEL_LINK")
        return None
    return [[{"type": "link", "text": text, "url": max_bot_deeplink(payload)}]]


async def send_to_channel(text, buttons=None, bot_button_text="✨ Открыть помощника на сегодня", image_payload=None, start_payload="channel_today", force_bot_button=True):
    """Отправляет пост в канал. Кнопка-ссылка на бота добавляется только если force_bot_button=True (не на каждый пост)."""
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
    if force_bot_button and MAX_BOT_PUBLIC_URL and not has_bot_link_button:
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


def _channel_publish_lock_key(slot):
    """Одна публикация на слот и дату; блокирует дубли всего поста, а не генерацию картинки отдельно."""
    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    return f"max_channel_publish:{today}:{slot}"


async def publish_channel_post(slot, theme, format_name, title, body, cta_mode="none", category="", cta_allowed=None):
    if not body:
        logging.warning("Канал: публикация %s пропущена — не удалось получить уникальный текст", slot)
        return

    publish_lock = _channel_publish_lock_key(slot)
    if not claim_persistent_command_lock(publish_lock, ttl_seconds=3 * 86400):
        logging.warning("Канал: повторная публикация полностью заблокирована slot=%s", slot)
        return

    final_text = f"{title}\n\n{body}".strip() if title else body.strip()
    want_button = False
    button_text = "✨ Открыть помощника на сегодня"
    start_payload = "channel_today"
    if cta_mode == "bot":
        bridge_text, thematic_button, start_payload = channel_cta_for_post(category, cta_allowed or ())
        final_text += f"\n\n{bridge_text}"
        button_text = thematic_button
        want_button = True
    elif cta_mode == "question":
        final_text += "\n\nА у вас было что-то похожее? Расскажите, интересно 🤍"

    try:
        ok = await send_to_channel(
            final_text,
            None,
            button_text,
            image_payload=None,
            start_payload=start_payload,
            force_bot_button=want_button,
        )
        if ok:
            save_channel_post(slot, theme, format_name, title, final_text)
            logging.info(
                "Канал: опубликовано %s | %s | %s | CTA=%s | start=%s | image=disabled",
                slot, format_name, title, cta_mode, start_payload,
            )
            return

        release_persistent_command_lock(publish_lock)
        logging.error("Канал: публикация %s не состоялась, блокировка снята для безопасной повторной попытки", slot)
    except Exception as exc:
        release_persistent_command_lock(publish_lock)
        logging.exception("Канал: ошибка публикации %s, блокировка снята: %s", slot, exc)


MAX_CHANNEL_SLOTS = ("max_first", "max_second", "max_third")

# Тот же принцип, что и в Telegram: недельный шаблон из 7 паттернов (утро/день/вечер) на 21 пост
# по 8 рубрикам — ~4 рецепта, ~4 воспитание и поведение, ~3 здоровье/сон/врач, ~3 сад/школа/по
# возрасту, ~2 мама тоже человек, ~2 папин взгляд, ~2 бабушки и семья, ~1 сохрани-пригодится
# (резерв вместо личной истории без свежих фактов владельца). Порядок дней внутри недели тасуется
# по seed на ISO-неделю; рубрики утра и вечера соседних дней никогда не совпадают ни при каком
# порядке перестановки.
MAX_CHANNEL_DAY_PATTERNS = [
    ("REC", "WHATIF", "MOM"),
    ("REC", "HEALTH", "DAD"),
    ("REC", "AGE", "FAM"),
    ("REC", "WHATIF", "MOM"),
    ("HEALTH", "AGE", "DAD"),
    ("AGE", "FAM", "WHATIF"),
    ("HEALTH", "SAVE", "WHATIF"),
]


def _daily_max_format_plan(day_key):
    dt = datetime.fromisoformat(day_key)
    iso_year, iso_week, iso_weekday = dt.isocalendar()
    patterns = list(MAX_CHANNEL_DAY_PATTERNS)
    random.Random(f"max-channel-week:{iso_year}-W{iso_week}").shuffle(patterns)
    pattern = patterns[iso_weekday - 1]
    return dict(zip(MAX_CHANNEL_SLOTS, pattern))


def _daily_max_choice(day_key, slot, category):
    rnd = random.Random(f"max-human-channel:{day_key}:{slot}")
    return select_channel_library_post(category, rnd)


def _daily_max_channel_plan(day_key, categories_by_slot):
    """CTA-ссылка — детерминированно 3-4 раза в неделю, только в уместных рубриках."""
    dt = datetime.fromisoformat(day_key)
    iso_year, iso_week, _ = dt.isocalendar()
    slots = list(MAX_CHANNEL_SLOTS)
    week_start = dt - timedelta(days=dt.weekday())
    eligible_by_day = {}
    for offset in range(7):
        week_day = (week_start + timedelta(days=offset)).date().isoformat()
        weekly_categories = _daily_max_format_plan(week_day)
        candidates = [
            weekly_slot for weekly_slot in slots
            if weekly_categories.get(weekly_slot) in ("HEALTH", "WHATIF", "AGE", "MOM", "FAM", "SAVE")
        ]
        if candidates:
            eligible_by_day[week_day] = candidates
    weekly_rnd = random.Random(f"max-human-cta-week:{iso_year}-W{iso_week}")
    weekly_days = list(eligible_by_day)
    weekly_rnd.shuffle(weekly_days)
    weekly_limit = min(len(weekly_days), 3 + int(weekly_rnd.random() < 0.5))
    weekly_cta = {
        weekly_day: weekly_rnd.choice(eligible_by_day[weekly_day])
        for weekly_day in weekly_days[:weekly_limit]
    }
    cta_slot = weekly_cta.get(day_key)
    rnd = random.Random(f"max-human-question:{day_key}")
    question_eligible = [s for s in slots if s != cta_slot and categories_by_slot.get(s) != "REC"]
    question_slot = rnd.choice(question_eligible) if question_eligible and rnd.random() < 0.4 else None
    return cta_slot, question_slot


async def post_max_slot(slot):
    if channel_slot_published_today(slot):
        return
    day_key = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    categories_by_slot = _daily_max_format_plan(day_key)
    category = categories_by_slot[slot]
    item = _daily_max_choice(day_key, slot, category)
    if not item:
        logging.error("Канал MAX: библиотека пуста для рубрики %s, публикация пропущена", category)
        return
    cta_slot, question_slot = _daily_max_channel_plan(day_key, categories_by_slot)
    if slot == cta_slot:
        cta_mode = "bot"
    elif slot == question_slot:
        cta_mode = "question"
    else:
        cta_mode = "none"
    if cta_mode == "bot" and not channel_has_allowed_cta(category, item.get("cta_allowed", [])):
        tried_topics = {item["topic"]}
        for attempt in range(6):
            cta_item = select_channel_library_post(
                category,
                random.Random(f"max-cta-library:{day_key}:{slot}:{attempt}"),
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

async def post_max_first():
    await post_max_slot("max_first")


async def post_max_second():
    await post_max_slot("max_second")


async def post_max_third():
    await post_max_slot("max_third")


_max_channel_scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


def schedule_daily_max_posts():
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    rnd = random.Random(f"max-human-times:{today.isoformat()}")
    windows = ((8 * 60 + 30, 11 * 60 + 30), (13 * 60 + 30, 16 * 60 + 30), (18 * 60, 21 * 60 + 30))
    minutes = []
    for lo, hi in windows:
        candidates = [minute for minute in range(lo, hi + 1) if minute % 60 % 5 != 0]
        minutes.append(rnd.choice(candidates))
    tz = ZoneInfo("Europe/Moscow")
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    job_ids = ("mama_max_channel_first", "mama_max_channel_second", "mama_max_channel_third")
    targets = (post_max_first, post_max_second, post_max_third)
    for job_id in job_ids:
        try:
            _max_channel_scheduler.remove_job(job_id)
        except Exception:
            pass
    for job_id, target, minute in zip(job_ids, targets, minutes):
        _max_channel_scheduler.add_job(target, "date", run_date=midnight + timedelta(minutes=minute), id=job_id, replace_existing=True, misfire_grace_time=30)
    logging.info(
        "Канал MAX: посты на сегодня запланированы на %02d:%02d, %02d:%02d и %02d:%02d",
        minutes[0] // 60, minutes[0] % 60, minutes[1] // 60, minutes[1] % 60, minutes[2] // 60, minutes[2] % 60,
    )


async def channel_weekly_editorial_report():
    conn = db_connect()
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT slot, format_name, COUNT(*) FROM channel_posts WHERE created_at>=? GROUP BY slot, format_name ORDER BY slot, format_name",
        (week_ago,),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM channel_posts WHERE created_at>=?", (week_ago,)).fetchone()[0]
    last_post = conn.execute("SELECT created_at, slot, title FROM channel_posts ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()

    by_slot, by_format = {}, {}
    for slot, format_name, count in rows:
        by_slot[slot] = by_slot.get(slot, 0) + count
        by_format[format_name] = by_format.get(format_name, 0) + count
    slot_labels = {"max_first": "Первых постов дня", "max_second": "Вторых постов дня", "max_third": "Третьих постов дня"}
    lines = ["📊 Отчёт MAX-канала за неделю", "", f"Опубликовано материалов: {total}"]
    for slot in ("max_first", "max_second", "max_third"):
        lines.append(f"{slot_labels[slot]}: {by_slot.get(slot, 0)}")
    if by_format:
        lines.extend(["", "Форматы:"])
        for format_name, count in sorted(by_format.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"• {format_name} — {count}")
    if last_post:
        created_at, slot, title = last_post
        try: created_label = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
        except Exception: created_label = created_at
        lines.extend(["", f"Последняя публикация: {created_label}", f"• {title} ({slot})"])
    report_text = "\n".join(lines)
    logging.info("Канал: недельный редакционный отчёт: %s", report_text)
    await send_message(OWNER_ID, report_text)


async def channel_posting_loop():
    schedule_daily_max_posts()
    _max_channel_scheduler.add_job(schedule_daily_max_posts, "cron", hour=0, minute=12, id="mama_max_channel_daily_planner", replace_existing=True, coalesce=True, max_instances=1)
    _max_channel_scheduler.add_job(channel_weekly_editorial_report, "cron", day_of_week="sun", hour=21, minute=0, id="mama_channel_weekly_report", replace_existing=True, coalesce=True, misfire_grace_time=60, max_instances=1)
    _max_channel_scheduler.start()
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
    asyncio.create_task(heartbeat_loop())
    logging.info("Мамин Помощник MAX запущен!")


# Строгая защита MAX webhook от повторной доставки долгих событий.
# MAX может менять timestamp при повторной доставке, поэтому timestamp не участвует
# в резервном ключе. Дополнительно блокируется повтор одной команды пользователя.
_WEBHOOK_SEEN = {}
_COMMAND_SEEN = {}
_WEBHOOK_DEDUP_TTL = 30 * 60
_COMMAND_DEDUP_TTL = 10 * 60


def _cleanup_seen(cache, now_ts, ttl):
    expired = [key for key, ts in cache.items() if now_ts - ts > ttl]
    for key in expired:
        cache.pop(key, None)


def _extract_message_id(data):
    message = data.get("message") or {}
    body = message.get("body") or {}
    callback = data.get("callback") or {}
    candidates = [
        message.get("message_id"),
        message.get("id"),
        body.get("mid"),
        body.get("message_id"),
        data.get("update_id"),
        callback.get("callback_id"),
        callback.get("id"),
    ]
    for value in candidates:
        if value not in (None, ""):
            return str(value)
    return ""


def _webhook_event_key(data):
    update_type = data.get("update_type", "")
    message = data.get("message") or {}
    body = message.get("body") or {}
    callback = data.get("callback") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}

    stable_id = _extract_message_id(data)
    if stable_id:
        return f"{update_type}:{stable_id}"

    # Важно: timestamp намеренно исключён — MAX меняет его при ретраях.
    attachments = body.get("attachments") or []
    attachment_fingerprint = ""
    if attachments:
        attachment_fingerprint = repr(attachments)[:2000]
    raw = "|".join([
        str(update_type),
        str(sender.get("user_id") or callback.get("user", {}).get("user_id") or ""),
        str(recipient.get("chat_id") or callback.get("chat_id") or ""),
        str((body.get("text") or "").strip()),
        str(callback.get("payload") or ""),
        attachment_fingerprint,
    ])
    return f"fallback:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _accept_webhook_once(data):
    now_ts = datetime.now().timestamp()
    _cleanup_seen(_WEBHOOK_SEEN, now_ts, _WEBHOOK_DEDUP_TTL)
    key = _webhook_event_key(data)
    if key in _WEBHOOK_SEEN:
        logging.warning("MAX webhook duplicate ignored: %s", key)
        return False
    _WEBHOOK_SEEN[key] = now_ts
    return True


def _accept_command_once(user_id, chat_id, text):
    now_ts = datetime.now().timestamp()
    _cleanup_seen(_COMMAND_SEEN, now_ts, _COMMAND_DEDUP_TTL)
    normalized = " ".join((text or "").strip().lower().split())
    key_raw = f"{user_id}|{chat_id}|{normalized}"
    key = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()
    if key in _COMMAND_SEEN:
        logging.warning("MAX repeated command ignored: user=%s text=%s", user_id, normalized[:80])
        return False
    _COMMAND_SEEN[key] = now_ts
    return True


def _run_webhook_task(coro, label):
    task = asyncio.create_task(coro)
    def _done(fut):
        try:
            fut.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logging.exception("MAX background task failed [%s]: %s", label, exc)
    task.add_done_callback(_done)
    return task


def save_max_chat_id(user_id, chat_id, update_type):
    """Сохраняет соответствие user_id -> chat_id, полученное из реального входящего апдейта.
    chat_id для приватного чата в MAX API отличается от user_id и без этого сохранения
    проактивная отправка (POST /messages?chat_id=) для уже известных пользователей невозможна.
    Ошибка записи не должна ронять обработку вебхука."""
    if not user_id or not chat_id or chat_id == CHANNEL_ID:
        return
    try:
        now = datetime.now().isoformat()
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO max_user_chats(user_id, chat_id, first_seen_at, updated_at, last_update_type) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, "
                "updated_at=excluded.updated_at, last_update_type=excluded.last_update_type",
                (user_id, chat_id, now, now, update_type),
            )
    except Exception:
        logging.error("save_max_chat_id: ошибка записи chat_id (update_type=%s)", update_type)


def get_saved_max_chat_id(user_id):
    """Возвращает приватный chat_id MAX для проактивной отправки, если он уже известен."""
    if not user_id:
        return None
    try:
        with db_connect() as conn:
            row = conn.execute("SELECT chat_id FROM max_user_chats WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else None
    except Exception:
        logging.error("get_saved_max_chat_id: ошибка чтения chat_id для user_id=%s", user_id)
        return None


# Одноразовая безадресная доставка объявления о бесплатной модели тем MAX-пользователям,
# чей исторический chat_id не восстановлен, — срабатывает при их следующем обращении.
# Строго привязано к одному broadcast_key, легко отключается флагом ниже.
MAX_PENDING_BROADCAST_ENABLED = True
MAX_PENDING_BROADCAST_KEY = "mama_free_announcement_20260727"
MAX_PENDING_BROADCAST_TEXT = (
    "Дорогие родители! ❤️\n\n"
    "Рады поделиться хорошей новостью: все текущие функции «Маминого помощника» "
    "теперь доступны бесплатно.\n\n"
    "Вы можете без подписки и обязательной оплаты пользоваться всеми разделами "
    "помощника: задавать вопросы, вести трекеры, получать разборы сна и кормлений, "
    "составлять сводки, пользоваться чек-листами и другими полезными возможностями.\n\n"
    "Мы хотим, чтобы «Мамин помощник» действительно помогал родителям каждый день "
    "— спокойно, понятно и без лишних ограничений.\n\n"
    "Открывайте помощника и пользуйтесь всеми функциями бесплатно 🌿"
)
MAX_PENDING_BROADCAST_BUTTONS = [
    [{"type": "callback", "text": "Открыть Мамин помощник", "payload": "main_menu"}],
    [{"type": "callback", "text": "❤️ Поддержать проект", "payload": "donate_menu"}],
]


def _claim_max_broadcast(user_id, broadcast_key=MAX_PENDING_BROADCAST_KEY):
    """Атомарно claim'ит право на отправку: no-op, если уже 'sent' или уже claimed
    другим параллельным событием. Без await между проверкой и записью — гонки внутри
    процесса исключены. broadcast_key параметризован, чтобы функцию можно было
    переиспользовать для других одноразовых кампаний без дублирования логики."""
    now = datetime.now().isoformat()
    with db_connect() as conn:
        cur = conn.execute(
            "INSERT INTO broadcast_log(broadcast_key, platform, user_id, status, error_code, ts) "
            "VALUES (?, 'max', ?, 'claimed', '', ?) "
            "ON CONFLICT(broadcast_key, platform, user_id) DO UPDATE SET status='claimed', ts=excluded.ts "
            "WHERE broadcast_log.status NOT IN ('sent', 'claimed', 'forbidden')",
            (broadcast_key, user_id, now),
        )
        return cur.rowcount == 1


def _mark_max_broadcast(user_id, status, error_code="", broadcast_key=MAX_PENDING_BROADCAST_KEY):
    now = datetime.now().isoformat()
    try:
        with db_connect() as conn:
            conn.execute(
                "UPDATE broadcast_log SET status=?, error_code=?, ts=? "
                "WHERE broadcast_key=? AND platform='max' AND user_id=?",
                (status, str(error_code)[:200], now, broadcast_key, user_id),
            )
    except Exception:
        logging.error("_mark_max_broadcast: ошибка обновления статуса broadcast_log")


def _feedback_broadcast_status_max(user_id, broadcast_key):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM broadcast_log WHERE broadcast_key=? AND platform='max' AND user_id=?",
            (broadcast_key, user_id),
        ).fetchone()
    return row[0] if row else None


def _claim_existing_max_broadcast(user_id, broadcast_key):
    """Claims only a pre-created campaign marker. This prevents a current-user
    one-off campaign from leaking to users who register after the campaign run."""
    now = datetime.now().isoformat()
    with db_connect() as conn:
        cur = conn.execute(
            "UPDATE broadcast_log SET status='claimed', error_code='', ts=? "
            "WHERE broadcast_key=? AND platform='max' AND user_id=? "
            "AND status NOT IN ('sent', 'claimed', 'forbidden')",
            (now, broadcast_key, user_id),
        )
        return cur.rowcount == 1


def _ensure_feedback_campaign_snapshot_max(audience):
    """Creates the campaign audience snapshot only on the first manual run."""
    now = datetime.now().isoformat()
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM broadcast_log WHERE broadcast_key=? AND platform='max' LIMIT 1",
            (FEEDBACK_CAMPAIGN_KEY,),
        ).fetchone()
        if exists:
            return
        conn.executemany(
            "INSERT OR IGNORE INTO broadcast_log(broadcast_key, platform, user_id, status, error_code, ts) "
            "VALUES (?, 'max', ?, 'pending', '', ?)",
            [(FEEDBACK_CAMPAIGN_KEY, user_id, now) for user_id in audience],
        )


async def _send_max_once(chat_id, text, buttons):
    headers = {"Authorization": MAX_TOKEN, "Content-Type": "application/json"}
    payload = {"text": text, "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(f"{MAX_API}/messages?chat_id={chat_id}", json=payload, headers=headers)
        if r.is_success:
            return "sent", ""
        if r.status_code == 403:
            return "forbidden", str(r.status_code)
        if r.status_code == 404:
            return "chat_not_found", str(r.status_code)
        if r.status_code == 429:
            return "rate_limited", str(r.status_code)
        return "temp_error", str(r.status_code)
    except Exception:
        return "temp_error", "exception"


async def maybe_deliver_pending_max_broadcast(user_id, chat_id):
    """Не более одного раза доставляет отложенное объявление broadcast_key пользователю,
    как только у него появился валидный chat_id (текущее сообщение/callback/старт).
    Не блокирует и не задерживает основной ответ (запускается отдельной задачей)."""
    if not MAX_PENDING_BROADCAST_ENABLED or not user_id or not chat_id or chat_id == CHANNEL_ID:
        return
    try:
        if not _claim_max_broadcast(user_id):
            return
        result, error_code = await _send_max_once(chat_id, MAX_PENDING_BROADCAST_TEXT, MAX_PENDING_BROADCAST_BUTTONS)
        if result == "rate_limited" or (result == "temp_error" and error_code != "exception"):
            await asyncio.sleep(3)
            result, error_code = await _send_max_once(chat_id, MAX_PENDING_BROADCAST_TEXT, MAX_PENDING_BROADCAST_BUTTONS)
        _mark_max_broadcast(user_id, result, error_code)
    except Exception:
        logging.error("maybe_deliver_pending_max_broadcast: непредвиденная ошибка")
        try:
            _mark_max_broadcast(user_id, "temp_error", "exception")
        except Exception:
            pass


# ─── ОДНОРАЗОВАЯ РАССЫЛКА ОБРАТНОЙ СВЯЗИ (campaign: feedback_features_2026_09) ──
# MAX адресует приватный чат только по уже известному chat_id (см. max_user_chats выше).
# Для пользователей без сохранённого chat_id доставка невозможна активным batch-циклом —
# используем тот же проверенный паттерн "доставить при следующем обращении", что и для
# MAX_PENDING_BROADCAST выше. Это не периодическая рассылка: сообщение уходит максимум
# один раз на пользователя благодаря dedup через broadcast_log.
FEEDBACK_CAMPAIGN_ENABLED = True
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
FEEDBACK_CAMPAIGN_BUTTONS = [
    [{"type": "callback", "text": "💬 Предложить функцию", "payload": "fb2026:suggest"}],
    [{"type": "callback", "text": "❤️ Всё нравится", "payload": "fb2026:like"}],
]


async def maybe_deliver_pending_feedback_campaign(user_id, chat_id):
    """Доставляет одноразовую кампанию обратной связи, как только у пользователя
    появился валидный chat_id. Не более одного раза на пользователя (dedup в broadcast_log)."""
    if not FEEDBACK_CAMPAIGN_ENABLED or not user_id or not chat_id or chat_id == CHANNEL_ID or user_id == OWNER_ID:
        return
    try:
        if not _claim_existing_max_broadcast(user_id, FEEDBACK_CAMPAIGN_KEY):
            return
        result, error_code = await _send_max_once(chat_id, FEEDBACK_CAMPAIGN_TEXT, FEEDBACK_CAMPAIGN_BUTTONS)
        if result == "rate_limited" or (result == "temp_error" and error_code != "exception"):
            await asyncio.sleep(3)
            result, error_code = await _send_max_once(chat_id, FEEDBACK_CAMPAIGN_TEXT, FEEDBACK_CAMPAIGN_BUTTONS)
        _mark_max_broadcast(user_id, result, error_code, FEEDBACK_CAMPAIGN_KEY)
    except Exception:
        logging.error("maybe_deliver_pending_feedback_campaign: непредвиденная ошибка")
        try:
            _mark_max_broadcast(user_id, "temp_error", "exception", FEEDBACK_CAMPAIGN_KEY)
        except Exception:
            pass


async def send_feedback_campaign_max():
    """Ручная одноразовая рассылка обратной связи. Не запускается из scheduler/main —
    вызывается один раз внешним job-скриптом. Активно отправляет только пользователям
    с уже известным chat_id; остальным сообщение будет доставлено при следующем
    обращении через maybe_deliver_pending_feedback_campaign (тот же принцип, что и
    для исторической рассылки MAX_PENDING_BROADCAST)."""
    with db_connect() as conn:
        total_rows = conn.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL AND user_id > 0").fetchall()
        known_rows = conn.execute(
            "SELECT u.user_id, m.chat_id FROM users u JOIN max_user_chats m ON m.user_id = u.user_id "
            "WHERE u.user_id IS NOT NULL AND u.user_id > 0"
        ).fetchall()
    audience = [r[0] for r in total_rows if r[0] != OWNER_ID]
    _ensure_feedback_campaign_snapshot_max(audience)
    reachable = [(uid, cid) for uid, cid in known_rows if uid != OWNER_ID and cid != CHANNEL_ID]
    sent, failed = 0, 0
    for user_id, chat_id in reachable:
        if not _claim_existing_max_broadcast(user_id, FEEDBACK_CAMPAIGN_KEY):
            status = _feedback_broadcast_status_max(user_id, FEEDBACK_CAMPAIGN_KEY)
            if status == "sent":
                sent += 1
            else:
                failed += 1
            continue
        result, error_code = await _send_max_once(chat_id, FEEDBACK_CAMPAIGN_TEXT, FEEDBACK_CAMPAIGN_BUTTONS)
        if result == "rate_limited" or (result == "temp_error" and error_code != "exception"):
            await asyncio.sleep(3)
            result, error_code = await _send_max_once(chat_id, FEEDBACK_CAMPAIGN_TEXT, FEEDBACK_CAMPAIGN_BUTTONS)
        _mark_max_broadcast(user_id, result, error_code, FEEDBACK_CAMPAIGN_KEY)
        if result == "sent":
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.3)
    queued_opportunistic = max(0, len(audience) - len(reachable))
    return {
        "audience": len(audience),
        "reachable_now": len(reachable),
        "sent": sent,
        "failed": failed,
        "queued_opportunistic": queued_opportunistic,
    }


# ─── ОДНОРАЗОВАЯ РАССЫЛКА «ПРИКОРМ 6+» (campaign: complementary_foods_2026_09) ──
# Тот же проверенный паттерн, что и FEEDBACK_CAMPAIGN выше: пользователям с уже
# известным chat_id отправляем сразу, остальным — при следующем обращении
# (maybe_deliver_pending_cf_campaign). Не периодическая рассылка, dedup через broadcast_log.
CF_CAMPAIGN_ENABLED = True
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
CF_CAMPAIGN_BUTTONS = [
    [{"type": "link", "text": "🥣 Открыть «Прикорм 6+»", "url": MINIAPP_URL + "?screen=complementary-feeding"}],
    [{"type": "callback", "text": "💬 Оставить мнение", "payload": "cf2026:feedback"}],
]


def _ensure_cf_campaign_snapshot_max(audience):
    """Creates the campaign audience snapshot only on the first manual run."""
    now = datetime.now().isoformat()
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM broadcast_log WHERE broadcast_key=? AND platform='max' LIMIT 1",
            (CF_CAMPAIGN_KEY,),
        ).fetchone()
        if exists:
            return
        conn.executemany(
            "INSERT OR IGNORE INTO broadcast_log(broadcast_key, platform, user_id, status, error_code, ts) "
            "VALUES (?, 'max', ?, 'pending', '', ?)",
            [(CF_CAMPAIGN_KEY, user_id, now) for user_id in audience],
        )


async def maybe_deliver_pending_cf_campaign(user_id, chat_id):
    """Доставляет одноразовую кампанию «Прикорм 6+», как только у пользователя
    появился валидный chat_id. Не более одного раза на пользователя (dedup в broadcast_log)."""
    if not CF_CAMPAIGN_ENABLED or not user_id or not chat_id or chat_id == CHANNEL_ID or user_id == OWNER_ID:
        return
    try:
        if not _claim_existing_max_broadcast(user_id, CF_CAMPAIGN_KEY):
            return
        result, error_code = await _send_max_once(chat_id, CF_CAMPAIGN_TEXT, CF_CAMPAIGN_BUTTONS)
        if result == "rate_limited" or (result == "temp_error" and error_code != "exception"):
            await asyncio.sleep(3)
            result, error_code = await _send_max_once(chat_id, CF_CAMPAIGN_TEXT, CF_CAMPAIGN_BUTTONS)
        _mark_max_broadcast(user_id, result, error_code, CF_CAMPAIGN_KEY)
    except Exception:
        logging.error("maybe_deliver_pending_cf_campaign: непредвиденная ошибка")
        try:
            _mark_max_broadcast(user_id, "temp_error", "exception", CF_CAMPAIGN_KEY)
        except Exception:
            pass


async def send_cf_campaign_max():
    """Ручная одноразовая рассылка «Прикорм 6+». Не запускается из scheduler/main —
    вызывается один раз внешним job-скриптом. Активно отправляет только пользователям
    с уже известным chat_id; остальным сообщение будет доставлено при следующем
    обращении через maybe_deliver_pending_cf_campaign."""
    with db_connect() as conn:
        total_rows = conn.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL AND user_id > 0").fetchall()
        known_rows = conn.execute(
            "SELECT u.user_id, m.chat_id FROM users u JOIN max_user_chats m ON m.user_id = u.user_id "
            "WHERE u.user_id IS NOT NULL AND u.user_id > 0"
        ).fetchall()
    audience = [r[0] for r in total_rows if r[0] != OWNER_ID]
    _ensure_cf_campaign_snapshot_max(audience)
    reachable = [(uid, cid) for uid, cid in known_rows if uid != OWNER_ID and cid != CHANNEL_ID]
    sent, failed = 0, 0
    for user_id, chat_id in reachable:
        if not _claim_existing_max_broadcast(user_id, CF_CAMPAIGN_KEY):
            status = _feedback_broadcast_status_max(user_id, CF_CAMPAIGN_KEY)
            if status == "sent":
                sent += 1
            else:
                failed += 1
            continue
        result, error_code = await _send_max_once(chat_id, CF_CAMPAIGN_TEXT, CF_CAMPAIGN_BUTTONS)
        if result == "rate_limited" or (result == "temp_error" and error_code != "exception"):
            await asyncio.sleep(3)
            result, error_code = await _send_max_once(chat_id, CF_CAMPAIGN_TEXT, CF_CAMPAIGN_BUTTONS)
        _mark_max_broadcast(user_id, result, error_code, CF_CAMPAIGN_KEY)
        if result == "sent":
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.3)
    queued_opportunistic = max(0, len(audience) - len(reachable))
    return {
        "audience": len(audience),
        "reachable_now": len(reachable),
        "sent": sent,
        "failed": failed,
        "queued_opportunistic": queued_opportunistic,
    }


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logging.info(f"MAX webhook: {data}")

        if not _accept_webhook_once(data):
            return JSONResponse({"ok": True})

        update_type = data.get("update_type", "")
        message = data.get("message", {})
        callback = data.get("callback", {})

        if update_type == "bot_started":
            user = data.get("user", {})
            start_payload = data.get("payload") or ""
            real_chat_id = data.get("chat_id")
            chat_id = real_chat_id or user.get("user_id")
            user_id = user.get("user_id") or chat_id
            if not user_id:
                return JSONResponse({"ok": True})
            # real_chat_id — фактическое поле апдейта; chat_id выше может быть подменён
            # на user_id как fallback для немедленного ответа, такое значение сохранять нельзя.
            if real_chat_id and real_chat_id != CHANNEL_ID:
                save_max_chat_id(user_id, real_chat_id, "bot_started")
                _run_webhook_task(maybe_deliver_pending_max_broadcast(user_id, real_chat_id), f"pending_broadcast:{user_id}")
                _run_webhook_task(maybe_deliver_pending_feedback_campaign(user_id, real_chat_id), f"pending_feedback_campaign:{user_id}")
                _run_webhook_task(maybe_deliver_pending_cf_campaign(user_id, real_chat_id), f"pending_cf_campaign:{user_id}")
            # Если запуск пришёл из канала, отвечаем только пользователю в личный чат.
            response_chat_id = user_id if chat_id == CHANNEL_ID else chat_id
            first_name = user.get("name", "мама")
            username = user.get("username", "")
            log_analytics_event("user_start", user_id, start_payload)
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
            if start_payload.startswith("channel_poll_"):
                if save_channel_poll_vote(user_id, start_payload):
                    await send_message(response_chat_id, "Спасибо за ответ 🤍 Ваш голос учтён.")
                return JSONResponse({"ok": True})
            if start_payload.startswith("channel_"):
                log_analytics_event("ad_payload_opened", user_id, start_payload)
            existing_user = get_user(user_id, username, first_name)
            existing_birth_date = existing_user.get("birth_date", "")
            is_pregnant_profile = existing_birth_date.startswith("pdr:")
            is_channel_payload = start_payload.startswith("channel_")
            intro = "🤍 Ты пришла из канала «Я МАМА». Здесь рекомендации становятся персональными.\n\n" if start_payload.startswith("channel") else ""
            if existing_birth_date.startswith("pdr:"):
                weeks = calc_pregnancy_weeks(existing_birth_date[4:])
                if is_channel_payload:
                    landing_text, landing_buttons = channel_landing_max(start_payload)
                    await send_message(response_chat_id, landing_text, landing_buttons)
                else:
                    await send_message(response_chat_id, intro + f"🤰 Ты на {weeks} неделе беременности. Чем могу помочь?", pregnant_menu_buttons(user_id))
            elif existing_birth_date:
                months = calc_child_age(existing_birth_date)
                if is_channel_payload:
                    landing_text, landing_buttons = channel_landing_max(start_payload)
                    await send_message(response_chat_id, landing_text, landing_buttons)
                else:
                    await send_message(response_chat_id, intro + f"👶 Малышу {age_label(months)}. Чем могу помочь?", main_menu_buttons(user_id))
            else:
                if start_payload.startswith("channel_"):
                    with db_connect() as conn:
                        conn.execute("UPDATE users SET pending_start=? WHERE user_id=?", (start_payload, user_id))
                await send_message(response_chat_id, intro + WELCOME_TEXT.format(name=first_name),
                    [[{"type": "callback", "text": "🤰 Я беременна", "payload": "set_pregnant"},
                      {"type": "callback", "text": "👩 Я уже мама", "payload": "set_mama"}]] + ([[{"type": "callback", "text": "👑 Кабинет владельца", "payload": "owner_cab:home"}]] if user_id == OWNER_ID else []))

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

            if chat_id:
                save_max_chat_id(user_id, chat_id, "message_created")
                _run_webhook_task(maybe_deliver_pending_max_broadcast(user_id, chat_id), f"pending_broadcast:{user_id}")
                _run_webhook_task(maybe_deliver_pending_feedback_campaign(user_id, chat_id), f"pending_feedback_campaign:{user_id}")
                _run_webhook_task(maybe_deliver_pending_cf_campaign(user_id, chat_id), f"pending_cf_campaign:{user_id}")

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
                            _run_webhook_task(
                                process_photo(chat_id, user_id, photo_url),
                                f"photo:{user_id}",
                            )
                            return JSONResponse({"ok": True})
                    elif att.get("type") in ("audio", "voice"):
                        audio_url = att.get("payload", {}).get("url")
                        if audio_url:
                            owner_step = get_user(user_id).get("step", "") if (OWNER_ID and user_id == OWNER_ID) else ""
                            if owner_step.startswith("pr_voice_"):
                                _run_webhook_task(
                                    pr_receive_voice_max(chat_id, user_id, owner_step, audio_url),
                                    f"pr_voice:{user_id}",
                                )
                                return JSONResponse({"ok": True})
                            _run_webhook_task(
                                process_voice(chat_id, user_id, audio_url, first_name),
                                f"voice:{user_id}",
                            )
                            return JSONResponse({"ok": True})

            if text:
                if not _accept_command_once(user_id, chat_id, text):
                    return JSONResponse({"ok": True})
                _run_webhook_task(
                    process_command(chat_id, user_id, text, username, first_name),
                    f"command:{user_id}:{text[:40]}",
                )

        elif update_type == "message_callback":
            user = callback.get("user", {})
            recipient = message.get("recipient", {})
            raw_chat_id = (
                recipient.get("chat_id") or
                callback.get("chat_id") or
                message.get("sender", {}).get("chat_id")
            )
            chat_id = raw_chat_id
            user_id = user.get("user_id") or message.get("sender", {}).get("user_id")
            first_name = user.get("name") or message.get("sender", {}).get("name", "мама")
            payload_cb = callback.get("payload", "")
            if chat_id == CHANNEL_ID and user_id:
                chat_id = user_id
            # raw_chat_id — значение до подмены на user_id для канальных callback'ов,
            # сохранять на будущее можно только его.
            if user_id and raw_chat_id and raw_chat_id != CHANNEL_ID:
                save_max_chat_id(user_id, raw_chat_id, "message_callback")
                _run_webhook_task(maybe_deliver_pending_max_broadcast(user_id, raw_chat_id), f"pending_broadcast:{user_id}")
                _run_webhook_task(maybe_deliver_pending_feedback_campaign(user_id, raw_chat_id), f"pending_feedback_campaign:{user_id}")
                _run_webhook_task(maybe_deliver_pending_cf_campaign(user_id, raw_chat_id), f"pending_cf_campaign:{user_id}")
            logging.info(f"CALLBACK: chat_id={chat_id} user_id={user_id} payload={payload_cb}")
            if chat_id and user_id and payload_cb:
                _run_webhook_task(
                    process_callback(chat_id, user_id, payload_cb, first_name),
                    f"callback:{user_id}:{payload_cb[:40]}",
                )
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


# ========== MINI APP API (Home v1, Telegram + MAX auth) ==========
# Один и тот же production Mini App обслуживает и Telegram, и MAX через единый platform-aware
# контракт: initData проверяется HMAC-SHA256 (см. _miniapp_verify_init_data для Telegram и
# _miniapp_verify_max_init_data для MAX — тот же алгоритм, свой секрет на платформу), затем
# запрос маршрутизируется в свою БД (_miniapp_db): telegram -> mama.db, max -> mama_max.db.
# Namespace-ы user_id платформ НЕ смешиваются — это разные БД, разные таблицы users.
MINIAPP_TG_BOT_TOKEN = _ENV.get("BOT_TOKEN", "").strip()
MINIAPP_INIT_DATA_MAX_AGE = 86400  # сутки, рекомендация Telegram/MAX для initData
MINIAPP_HISTORY_LIMIT = 20
# Обратная связь Mini App (support_menu/support_write/review_write/suggestion_write из mama_bot.py):
# TG_OWNER_ID — тот же владелец, которому mama_bot.py пересылает обращения через aiogram Bot;
# здесь используется HTTP Bot API напрямую, т.к. mama_max_bot.py — отдельный процесс без
# доступа к тому объекту Bot. SUPPORT_USERNAME — тот же резервный контакт, что в mama_bot.py.
MINIAPP_TG_OWNER_ID = int(_ENV.get("TG_OWNER_ID", "0") or 0)
MINIAPP_TG_SUPPORT_USERNAME = "@demo23rus"
# Тот же Google Sheet (SPREADSHEET_ID_MAMA == SPREADSHEET_ID из mama_bot.py), тот же лист и
# заголовки, что TG_USER_SHEET/TG_USER_HEADERS в mama_bot.py — не отдельная таблица.
MINIAPP_TG_USER_SHEET = "МамаБот Telegram"
MINIAPP_TG_USER_HEADERS = [
    "Последнее посещение", "user_id", "Имя", "Username",
    "AI-запросы", "Тариф", "Дата окончания", "Отзыв"
]
_miniapp_max_schema_ready = False


def _miniapp_db(user=None):
    platform = user.get("platform", "telegram") if isinstance(user, dict) else (user or "telegram")
    if platform == "max":
        conn = sqlite3.connect(DB, timeout=5)
        conn.row_factory = sqlite3.Row
        global _miniapp_max_schema_ready
        if not _miniapp_max_schema_ready:
            # Чат-бот MAX хранит сон/кормления в diary с префиксами (СОН:/КОРМ:); Mini App
            # использует те же нативные таблицы, что и Telegram-бот в mama.db — добавляем их
            # аддитивно (CREATE TABLE IF NOT EXISTS), не трогая существующие данные чат-бота.
            conn.execute("""CREATE TABLE IF NOT EXISTS sleep_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                created_at TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sleep_log_user_date ON sleep_log(user_id, created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS feeding (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                side TEXT,
                duration INTEGER,
                created_at TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feeding_user_date ON feeding(user_id, created_at)")
            conn.commit()
            _miniapp_max_schema_ready = True
        return conn
    conn = sqlite3.connect(TG_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _miniapp_verify_init_data(init_data):
    """Проверяет Telegram WebApp initData по документированной схеме HMAC-SHA256."""
    if not init_data or not MINIAPP_TG_BOT_TOKEN:
        return None
    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", MINIAPP_TG_BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date <= 0 or (datetime.now().timestamp() - auth_date) > MINIAPP_INIT_DATA_MAX_AGE:
        return None
    try:
        user = json.loads(data.get("user", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None
    if not user.get("id"):
        return None
    return user


def _miniapp_verify_max_init_data(init_data):
    """Проверяет MAX WebAppData: тот же HMAC-SHA256 алгоритм, что и Telegram, свой secret_key
    из MAX_TOKEN. hash должен встречаться ровно один раз в launch params."""
    if not init_data or not MAX_TOKEN:
        return None
    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None
    if sum(1 for k, _ in pairs if k == "hash") != 1:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    launch_params = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", MAX_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date <= 0 or (datetime.now().timestamp() - auth_date) > MINIAPP_INIT_DATA_MAX_AGE:
        return None
    try:
        user = json.loads(data.get("user", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None
    if not user.get("id"):
        return None
    return user


def _miniapp_resolve_user(request: Request, body_init_data=None):
    """Единая точка входа platform-aware авторизации. Platform-заголовок клиента — это только
    подсказка, какой секрет и какую init-data проверять; доверие полностью определяется
    результатом HMAC-проверки, а не тем, что заявил клиент."""
    platform = (request.headers.get("X-Miniapp-Platform") or "telegram").strip().lower()
    if platform not in ("telegram", "max"):
        platform = "telegram"
    if platform == "max":
        init_data = request.headers.get("X-Init-Data") or body_init_data or ""
        user = _miniapp_verify_max_init_data(init_data)
    else:
        init_data = (
            request.headers.get("X-Init-Data")
            or request.headers.get("X-Telegram-Init-Data")
            or body_init_data
            or ""
        )
        user = _miniapp_verify_init_data(init_data)
    if not user:
        return None
    user = dict(user)
    user["platform"] = platform
    return user


def _miniapp_require_user(request: Request):
    user = _miniapp_resolve_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def _miniapp_profile_row(conn, platform, user_id):
    """Единый вид профиля (mode/date_value/name/created_at) поверх разных схем users:
    mama.db (Telegram) хранит mode+date_value напрямую; mama_max.db (MAX) хранит birth_date,
    где 'pdr:ДД.ММ.ГГГГ' значит беременность. Не путать с чат-ботом MAX — читаем ту же таблицу
    users, что и mama_max_bot.py, но ничего в ней не меняем."""
    if platform == "max":
        row = conn.execute(
            "SELECT user_id, first_name, birth_date, registered_at FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        birth_date = row["birth_date"] or ""
        if birth_date.startswith("pdr:"):
            mode, date_value = "pregnant", birth_date[4:]
        elif birth_date:
            mode, date_value = "mama", birth_date
        else:
            mode, date_value = "", ""
        return {
            "user_id": row["user_id"],
            "mode": mode,
            "date_value": date_value,
            "name": row["first_name"] or "",
            "created_at": row["registered_at"] or "",
        }
    row = conn.execute(
        "SELECT user_id, mode, date_value, name, created_at FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "mode": row["mode"] or "",
        "date_value": row["date_value"] or "",
        "name": row["name"] or "",
        "created_at": row["created_at"] or "",
    }


def _miniapp_pregnancy_weeks(pdr_str):
    try:
        pdr = datetime.strptime(pdr_str, "%d.%m.%Y").date()
        conception = pdr - timedelta(days=280)
        days = (datetime.now().date() - conception).days
        return days // 7
    except Exception:
        return None


def _miniapp_child_months(birth_str):
    try:
        birth = datetime.strptime(birth_str, "%d.%m.%Y").date()
        today = datetime.now().date()
        return (today.year - birth.year) * 12 + (today.month - birth.month)
    except Exception:
        return None


@app.get("/api/miniapp/health")
async def miniapp_health():
    return {"status": "ok"}


@app.post("/api/miniapp/auth")
async def miniapp_auth(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = _miniapp_resolve_user(request, (body or {}).get("initData"))
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return {
        "ok": True,
        "user_id": user.get("id"),
        "first_name": user.get("first_name", ""),
        "platform": user.get("platform", "telegram"),
    }


@app.get("/api/miniapp/home")
async def miniapp_home(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    name = ""
    registered = False
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            if row:
                registered = True
                name = row["name"] or ""
    except Exception:
        logging.exception("miniapp_home db error")
    return {
        "ok": True,
        "registered": registered,
        "name": name or user.get("first_name", ""),
        "status_message": "Все функции бесплатно",
    }


@app.get("/api/miniapp/profile")
async def miniapp_profile(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    row = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
    except Exception:
        logging.exception("miniapp_profile db error")
    if not row:
        return {"ok": True, "registered": False, "user_id": user_id, "first_name": user.get("first_name", "")}
    mode = row["mode"] or ""
    date_value = row["date_value"] or ""
    weeks = _miniapp_pregnancy_weeks(date_value) if mode == "pregnant" else None
    months = _miniapp_child_months(date_value) if mode and mode != "pregnant" else None
    return {
        "ok": True,
        "registered": True,
        "user_id": row["user_id"],
        "name": row["name"] or user.get("first_name", ""),
        "mode": mode,
        "date_value": date_value,
        "pregnancy_weeks": weeks,
        "child_months": months,
        "created_at": row["created_at"] or "",
    }


# ========== MINI APP: СЕГОДНЯ ==========
# Персональная сводка для широкой плашки на Home и отдельного экрана "Сегодня". Использует
# только уже существующие таблицы/хелперы (_miniapp_profile_row, _miniapp_pregnancy_weeks_days,
# _miniapp_child_months, age_label, sleep_log/feeding/symptoms/diary/growth/vaccinations) и уже
# существующий OpenAI client через _miniapp_ask_gpt — новых таблиц нет, AI вызывается только по
# отдельному эндпоинту /today/advice (по кнопке), не при каждом открытии Home/Сегодня.
MINIAPP_TODAY_WINDOW_HOURS = 24


def _miniapp_today_snapshot(conn, platform, user_id):
    """Единый срез "Сегодня" по режиму профиля. None, если профиль/режим ещё не заполнен."""
    row = _miniapp_profile_row(conn, platform, user_id)
    if not row or not row["mode"]:
        return None
    mode = row["mode"]
    date_value = row["date_value"] or ""
    snapshot = {"mode": mode, "date_value": date_value}

    if mode == "pregnant":
        weeks, days = _miniapp_pregnancy_weeks_days(date_value)
        trimester = None
        if weeks is not None:
            trimester = (
                "1-й триместр — закладка всех органов" if weeks <= 13
                else "2-й триместр — активный рост" if weeks <= 26
                else "3-й триместр — подготовка к рождению"
            )
        snapshot["pregnancy_weeks"] = weeks
        snapshot["pregnancy_days"] = days
        snapshot["trimester"] = trimester
        return snapshot

    months = _miniapp_child_months(date_value)
    snapshot["child_months"] = months
    snapshot["child_age_label"] = age_label(months)

    since = (datetime.now() - timedelta(hours=MINIAPP_TODAY_WINDOW_HOURS)).isoformat()
    snapshot["sleep_count_24h"] = int(conn.execute(
        "SELECT COUNT(*) FROM sleep_log WHERE user_id=? AND created_at>=?", (user_id, since)
    ).fetchone()[0] or 0)
    snapshot["feeding_count_24h"] = int(conn.execute(
        "SELECT COUNT(*) FROM feeding WHERE user_id=? AND created_at>=?", (user_id, since)
    ).fetchone()[0] or 0)
    snapshot["symptoms_count_24h"] = int(conn.execute(
        "SELECT COUNT(*) FROM symptoms WHERE user_id=? AND created_at>=?", (user_id, since)
    ).fetchone()[0] or 0)

    growth_row = conn.execute(
        "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if growth_row:
        snapshot["last_growth"] = {
            "height": growth_row["height"],
            "weight": growth_row["weight"],
            "created_at": growth_row["created_at"] or "",
        }

    diary_row = conn.execute(
        "SELECT entry, created_at FROM diary WHERE user_id=? AND entry NOT LIKE 'КОРМ:%' "
        "AND entry NOT LIKE 'СОН:%' AND entry NOT LIKE 'СИМПТОМ:%' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if diary_row:
        snapshot["last_diary"] = {"entry": diary_row["entry"] or "", "created_at": diary_row["created_at"] or ""}

    nearest_vaccine = None
    nearest_date = None
    today_date = datetime.now().date()
    for vrow in conn.execute(
        "SELECT vaccine, scheduled_date FROM vaccinations WHERE user_id=? AND done=0", (user_id,)
    ):
        try:
            vdate = datetime.strptime(vrow["scheduled_date"] or "", "%d.%m.%Y").date()
        except Exception:
            continue
        if vdate < today_date:
            continue
        if nearest_date is None or vdate < nearest_date:
            nearest_date = vdate
            nearest_vaccine = {"vaccine": vrow["vaccine"] or "", "scheduled_date": vrow["scheduled_date"] or ""}
    snapshot["nearest_vaccine"] = nearest_vaccine

    if months is not None and months >= 6:
        try:
            _miniapp_cf_ensure_schema(conn, platform)
            cf_rows = list(conn.execute(
                "SELECT food_key, status, updated_at FROM complementary_food_log "
                "WHERE platform=? AND user_id=? AND status!='not_tried' ORDER BY updated_at DESC",
                (platform, user_id),
            ))
            if cf_rows:
                last_food = MINIAPP_CF_FOOD_BY_KEY.get(cf_rows[0]["food_key"])
                snapshot["complementary_food"] = {
                    "tried_count": len(cf_rows),
                    "liked_count": sum(1 for r in cf_rows if r["status"] == "liked"),
                    "last_food": last_food["title"] if last_food else cf_rows[0]["food_key"],
                    "last_food_status": cf_rows[0]["status"],
                }
        except Exception:
            logging.exception("miniapp_today_snapshot complementary_food error")
    return snapshot


@app.get("/api/miniapp/today")
async def miniapp_today(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        with _miniapp_db(user) as conn:
            snapshot = _miniapp_today_snapshot(conn, user.get("platform", "telegram"), user_id)
    except Exception:
        logging.exception("miniapp_today db error")
        raise HTTPException(status_code=500, detail="db_error")
    if snapshot is None:
        return {"ok": True, "registered": False}
    snapshot["ok"] = True
    snapshot["registered"] = True
    snapshot["date"] = datetime.now().strftime("%d.%m.%Y")
    return snapshot


@app.get("/api/miniapp/today/advice")
async def miniapp_today_advice(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        with _miniapp_db(user) as conn:
            snapshot = _miniapp_today_snapshot(conn, user.get("platform", "telegram"), user_id)
    except Exception:
        logging.exception("miniapp_today_advice db error")
        raise HTTPException(status_code=500, detail="db_error")
    if snapshot is None:
        raise HTTPException(status_code=400, detail="profile_required")

    if snapshot["mode"] == "pregnant":
        weeks = snapshot.get("pregnancy_weeks")
        days = snapshot.get("pregnancy_days")
        context_lines = [
            f"Срок беременности: {weeks} недель и {days} дней."
            if weeks is not None else "Срок беременности неизвестен."
        ]
        system_prompt = EXPERT_PREG
    else:
        context_lines = [f"Возраст ребёнка: {snapshot.get('child_age_label')}."]
        context_lines.append(
            f"За последние 24 часа: сон — {snapshot.get('sleep_count_24h', 0)} записей, "
            f"кормление — {snapshot.get('feeding_count_24h', 0)} записей, "
            f"самочувствие — {snapshot.get('symptoms_count_24h', 0)} записей."
        )
        last_growth = snapshot.get("last_growth")
        if last_growth:
            context_lines.append(f"Последний рост/вес: {last_growth.get('height')} см, {last_growth.get('weight')} кг.")
        last_diary = snapshot.get("last_diary")
        if last_diary:
            context_lines.append(f"Последняя запись дневника: {last_diary.get('entry')}")
        system_prompt = EXPERT_BASE

    nearest_vaccine = snapshot.get("nearest_vaccine")
    if nearest_vaccine:
        context_lines.append(f"Ближайшая прививка: {nearest_vaccine.get('vaccine')} — {nearest_vaccine.get('scheduled_date')}.")

    context_str = "\n".join(context_lines)
    log_analytics_event_tg(user_id, "request_started", "today_advice", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        system_prompt,
        f"Вот реальные данные пользователя на сегодня:\n{context_str}\n\n"
        f"Дай короткий персональный совет на сегодня — 3-5 по-настоящему полезных пунктов, "
        f"основанных только на этих данных. Не придумывай событий и цифр, которых нет выше. "
        f"Не ставь диагнозов. Если в данных есть тревожные признаки — прямо скажи об этом и "
        f"порекомендуй обратиться к врачу."
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "today_advice", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "today_advice", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


@app.get("/api/miniapp/referral")
async def miniapp_referral(request: Request):
    # Перенос invite_friend из mama_bot.py (Telegram callback) и process_callback (MAX payload
    # "invite_friend") в Mini App — та же таблица referrals/referral_bonus_questions на платформу
    # (mama.db для Telegram, mama_max.db для MAX, через уже platform-routed _miniapp_db(user)),
    # без новой системы начисления. Проект сейчас бесплатный, поэтому мы не придумываем новую
    # награду: bonus_questions_granted/available отражают реально работающую механику
    # increment_request_count (бонусный вопрос сверх лимита тарифа), как есть.
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    link = referral_link_tg(user_id) if platform == "telegram" else referral_link_max(user_id)
    share_url = None
    if platform == "telegram":
        # Тот же share intent, что и кнопка "📤 Поделиться" в mama_bot.py invite_friend (call.data
        # "invite_friend"): t.me/share/url — открывается через Platform.openLink на клиенте.
        share_text = "Я пользуюсь «Маминым Помощником» — здесь можно получить поддержку по беременности, ребёнку, сну, питанию и развитию 🤍"
        share_url = "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote(share_text, safe="")
    invited_count = 0
    bonus_questions_granted = 0
    bonus_questions_available = 0
    try:
        with _miniapp_db(user) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(start_reward_granted),0) FROM referrals WHERE referrer_user_id=?",
                (user_id,),
            ).fetchone()
            invited_count = int(row[0] or 0)
            bonus_questions_granted = int(row[1] or 0)
            bonus_row = conn.execute(
                "SELECT bonus_questions FROM referral_bonus_questions WHERE user_id=?",
                (user_id,),
            ).fetchone()
            bonus_questions_available = int(bonus_row[0] or 0) if bonus_row else 0
    except Exception:
        logging.exception("miniapp_referral db error")
    return {
        "ok": True,
        "platform": platform,
        "link": link,
        "share_url": share_url,
        "invited_count": invited_count,
        "bonus_questions_granted": bonus_questions_granted,
        "bonus_questions_available": bonus_questions_available,
        "note": "Все функции «Маминого помощника» и так доступны бесплатно — приглашение просто помогает больше мам узнать о проекте.",
    }


@app.get("/api/miniapp/history/recent")
async def miniapp_history_recent(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    items = []
    try:
        with _miniapp_db(user) as conn:
            for r in conn.execute(
                "SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                items.append({"type": "symptoms", "label": "Самочувствие", "detail": r["symptom"] or "", "created_at": r["created_at"] or ""})
            for r in conn.execute(
                "SELECT action, created_at FROM sleep_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                items.append({"type": "sleep", "label": "Сон", "detail": r["action"] or "", "created_at": r["created_at"] or ""})
            for r in conn.execute(
                "SELECT side, duration, created_at FROM feeding WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                detail = (r["side"] or "").strip()
                if r["duration"]:
                    detail = f"{detail} · {r['duration']} мин".strip(" ·")
                items.append({"type": "feeding", "label": "Питание", "detail": detail, "created_at": r["created_at"] or ""})
            for r in conn.execute(
                "SELECT entry, created_at FROM diary WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                items.append({"type": "diary", "label": "Дневник", "detail": r["entry"] or "", "created_at": r["created_at"] or ""})
            for r in conn.execute(
                "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                detail = f"{r['height']} см, {r['weight']} кг" if r["height"] is not None and r["weight"] is not None else ""
                items.append({"type": "growth", "label": "Рост и вес", "detail": detail, "created_at": r["created_at"] or ""})
            for r in conn.execute(
                "SELECT vaccine, scheduled_date, done, created_at FROM vaccinations WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_HISTORY_LIMIT),
            ):
                status = "✅ сделано" if r["done"] else "⏳ запланировано"
                detail = f"{r['vaccine'] or ''} · {status} {r['scheduled_date'] or ''}".strip()
                items.append({"type": "vaccines", "label": "Прививки", "detail": detail, "created_at": r["created_at"] or ""})
    except Exception:
        logging.exception("miniapp_history_recent db error")
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return {"ok": True, "items": items[:MINIAPP_HISTORY_LIMIT]}


# ========== MINI APP: ОБРАТНАЯ СВЯЗЬ ==========
# Перенос support_menu/support_write/review_write/suggestion_write из mama_bot.py (Telegram) и
# их аналогов в process_message/process_callback из этого файла (MAX) — тот же канал доставки
# на платформу, без нового независимого хранилища:
#   MAX:      support -> send_message(OWNER_ID,...) + save_review(...) + sheets_upsert_max_user(...)
#             review -> save_review(...) + sheets_log_review(...), suggestion -> sheets_log_review(...)
#             с префиксом "ПРЕДЛОЖЕНИЕ:" — как в process_message.
#   Telegram: support -> Telegram Bot API sendMessage владельцу (TG_OWNER_ID) — тот же получатель,
#             что и mama_bot.py, но через HTTP, т.к. mama_max_bot.py не держит aiogram Bot;
#             review/suggestion -> тот же Google Sheet/лист/заголовки, что sheets_upsert_user
#             в mama_bot.py (MINIAPP_TG_USER_SHEET/MINIAPP_TG_USER_HEADERS == TG_USER_SHEET/
#             TG_USER_HEADERS, тот же SPREADSHEET_ID_MAMA == SPREADSHEET_ID).
# user_id всегда берётся из проверенного initData (_miniapp_require_user), не с клиента.
# Текст обращения нигде не пишется в analytics_events — только event_name/source.
MINIAPP_FEEDBACK_MAX_LEN = 3000


async def _miniapp_feedback_read_text(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > MINIAPP_FEEDBACK_MAX_LEN:
        raise HTTPException(status_code=400, detail="text_too_long")
    return text


async def _miniapp_tg_owner_send(text):
    """Отправляет сообщение владельцу Telegram через HTTP Bot API — тот же TG_OWNER_ID и тот же
    BOT_TOKEN, что использует mama_bot.py (aiogram bot.send_message), но напрямую по HTTP,
    так как aiogram Bot этого бота живёт в процессе mambot.service, а не здесь."""
    if not MINIAPP_TG_BOT_TOKEN or not MINIAPP_TG_OWNER_ID:
        logging.warning("miniapp feedback: BOT_TOKEN/TG_OWNER_ID не заданы, обращение владельцу Telegram не отправлено")
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{MINIAPP_TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": MINIAPP_TG_OWNER_ID, "text": text[:3900]},
            )
            if not r.is_success:
                logging.error("miniapp feedback tg owner send: status=%s body=%s", r.status_code, r.text[:300])
    except Exception:
        logging.exception("miniapp feedback tg owner send error")


def _miniapp_sheets_tg_feedback(user_id, username, first_name, review=None):
    """Пишет в тот же лист 'МамаБот Telegram' той же таблицы SPREADSHEET_ID_MAMA, что и
    sheets_upsert_user в mama_bot.py — не отдельный механизм хранения отзывов/обращений."""
    try:
        book = _max_sheets_book()
        ws = _max_worksheet(book, MINIAPP_TG_USER_SHEET, MINIAPP_TG_USER_HEADERS)
        uid = str(user_id)
        ids = ws.col_values(2)
        row_num = next((i + 1 for i, value in enumerate(ids) if value == uid), None)
        values = [
            datetime.now().strftime("%d.%m.%Y %H:%M"), uid,
            first_name or "", username or "",
            "", "", "",
            review if review is not None else "",
        ]
        if row_num:
            old = ws.row_values(row_num)
            while len(old) < len(MINIAPP_TG_USER_HEADERS):
                old.append("")
            if not first_name:
                values[2] = old[2]
            if not username:
                values[3] = old[3]
            values[4], values[5], values[6] = old[4], old[5], old[6]
            if review is None:
                values[7] = old[7]
            ws.update(f"A{row_num}:H{row_num}", [values])
        else:
            ws.append_row(values)
    except Exception as e:
        logging.error(f"Miniapp TG sheets feedback error: {e}")


@app.post("/api/miniapp/feedback/support")
async def miniapp_feedback_support(request: Request):
    user = _miniapp_require_user(request)
    text = await _miniapp_feedback_read_text(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    first_name = user.get("first_name", "") or ""
    username = user.get("username", "") or ""
    try:
        if platform == "max":
            plan, sub_end = get_subscription(user_id)
            plan_name = PLAN_CATALOG.get(plan, {}).get("name", "Бесплатный") if plan else "Бесплатный"
            end_text = sub_end.strftime("%d.%m.%Y") if sub_end else "—"
            owner_text = (
                f"🆘 Поддержка Мамин Помощник MAX (Mini App)\n\nПлатформа: MAX\n"
                f"Пользователь: {first_name or 'без имени'}\nID: {user_id}\nUsername: {username or 'нет'}\n"
                f"Тариф: {plan_name}\nОкончание: {end_text}\n\nСообщение:\n{text}"
            )
            try:
                await send_message(OWNER_ID, owner_text)
            except Exception:
                logging.exception("miniapp feedback support MAX owner send error")
            save_review(user_id, username, first_name, f"ПОДДЕРЖКА: {text}")
            asyncio.create_task(asyncio.to_thread(
                sheets_upsert_max_user, user_id, first_name, username, "", None, "Обращение в поддержку"
            ))
        else:
            owner_text = (
                f"🆘 Поддержка Мамин Помощник Telegram (Mini App)\n\nПлатформа: Telegram\n"
                f"Имя: {first_name or 'без имени'}\nUsername: @{username or 'нет'}\nID: {user_id}\n\nСообщение:\n{text}"
            )
            await _miniapp_tg_owner_send(owner_text)
            asyncio.create_task(asyncio.to_thread(_miniapp_sheets_tg_feedback, user_id, username, first_name, None))
    except Exception:
        logging.exception("miniapp_feedback_support error")
    log_analytics_event_tg(user_id, "feedback_submitted", "support", "miniapp", platform)
    return {"ok": True, "message": f"Сообщение отправлено! Мы ответим в ближайшее время.\n\nРезервный контакт: {MINIAPP_TG_SUPPORT_USERNAME}"}


@app.post("/api/miniapp/feedback/review")
async def miniapp_feedback_review(request: Request):
    user = _miniapp_require_user(request)
    text = await _miniapp_feedback_read_text(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    first_name = user.get("first_name", "") or ""
    username = user.get("username", "") or ""
    try:
        if platform == "max":
            save_review(user_id, username, first_name, text)
            asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, text))
        else:
            asyncio.create_task(asyncio.to_thread(_miniapp_sheets_tg_feedback, user_id, username, first_name, text))
    except Exception:
        logging.exception("miniapp_feedback_review error")
    log_analytics_event_tg(user_id, "feedback_submitted", "review", "miniapp", platform)
    return {"ok": True, "message": "Спасибо за отзыв! Это очень важно для нас 💕"}


@app.post("/api/miniapp/feedback/suggestion")
async def miniapp_feedback_suggestion(request: Request):
    user = _miniapp_require_user(request)
    text = await _miniapp_feedback_read_text(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    first_name = user.get("first_name", "") or ""
    username = user.get("username", "") or ""
    try:
        if platform == "max":
            suggestion_text = f"ПРЕДЛОЖЕНИЕ: {text}"
            asyncio.create_task(asyncio.to_thread(sheets_log_review, user_id, first_name, username, suggestion_text))
        else:
            asyncio.create_task(asyncio.to_thread(_miniapp_sheets_tg_feedback, user_id, username, first_name, text))
    except Exception:
        logging.exception("miniapp_feedback_suggestion error")
    log_analytics_event_tg(user_id, "feedback_submitted", "suggestion", "miniapp", platform)
    return {"ok": True, "message": "Спасибо за идею! Мы обязательно рассмотрим её 🤍"}


# ========== MINI APP: БЕРЕМЕННОСТЬ ==========
# Тот же системный prompt (EXPERT_PREG) и те же user prompts, тот же OpenAI client (gpt-4o,
# max_tokens=2000 через _miniapp_ask_gpt), что и в preg_week/preg_baby/preg_checklist/preg_shop
# из mama_bot.py (Telegram) — тексты и расчёт срока (280 дней от ПДР) скопированы дословно.
# Доступно только профилю mode="pregnant" (см. _miniapp_require_pregnant_profile); для остальных
# профилей — 400 pregnancy_profile_required, не 500. user_id с клиента не доверяется.
EXPERT_PREG = (
    "Ты эксперт в акушерстве, перинатальной психологии и фетальной медицине. "
    "Опирайся на рекомендации ВОЗ, протоколы ACOG (Американский колледж акушеров и гинекологов), "
    "исследования в области эмбриологии и нейронауки развития плода. "
    "Отвечай тепло, поддерживающе, без страшилок — но точно и научно. "
    "При любых тревожных симптомах направляй к врачу."
)


def _miniapp_pregnancy_weeks_days(pdr_str):
    """Тот же расчёт, что и calc_pregnancy_weeks() в mama_bot.py (280 дней от ПДР до "зачатия"),
    но с остатком дней — нужен для текста, идентичного Telegram-сценарию preg_week."""
    try:
        pdr = datetime.strptime(pdr_str, "%d.%m.%Y").date()
        conception = pdr - timedelta(days=280)
        days = (datetime.now().date() - conception).days
        return days // 7, days % 7
    except Exception:
        return None, None


def _miniapp_require_pregnant_profile(user):
    """Отдаёт date_value беременной или бросает 400 pregnancy_profile_required — раздел
    доступен только профилю mode='pregnant', без 500 для остальных профилей."""
    user_id = user.get("id")
    row = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
    except Exception:
        logging.exception("miniapp_pregnancy: profile lookup error")
        raise HTTPException(status_code=500, detail="db_error")
    if not row or row["mode"] != "pregnant":
        raise HTTPException(status_code=400, detail="pregnancy_profile_required")
    return row["date_value"] or ""


@app.get("/api/miniapp/pregnancy/week")
async def miniapp_pregnancy_week(request: Request):
    user = _miniapp_require_user(request)
    date_value = _miniapp_require_pregnant_profile(user)
    weeks, days = _miniapp_pregnancy_weeks_days(date_value)
    if weeks is None:
        raise HTTPException(status_code=400, detail="invalid_date_value")
    trimester = (
        "1-й триместр — закладка всех органов" if weeks <= 13
        else "2-й триместр — активный рост" if weeks <= 26
        else "3-й триместр — подготовка к рождению"
    )
    text = f"Твой срок\n\n🤰 {weeks} недель и {days} дней\n\nЭто {trimester}"
    return {"ok": True, "weeks": weeks, "days": days, "trimester": trimester, "text": text}


@app.get("/api/miniapp/pregnancy/baby")
async def miniapp_pregnancy_baby(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    date_value = _miniapp_require_pregnant_profile(user)
    weeks, _days = _miniapp_pregnancy_weeks_days(date_value)
    log_analytics_event_tg(user_id, "request_started", "pregnancy_baby", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
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
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "pregnancy_baby", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "pregnancy_baby", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "weeks": weeks, "answer": answer}


@app.get("/api/miniapp/pregnancy/checklist")
async def miniapp_pregnancy_checklist(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    date_value = _miniapp_require_pregnant_profile(user)
    weeks, _days = _miniapp_pregnancy_weeks_days(date_value)
    log_analytics_event_tg(user_id, "request_started", "pregnancy_checklist", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        EXPERT_PREG,
        f"Составь исчерпывающий чек-лист для {weeks} недели беременности по протоколам ВОЗ и ACOG. "
        f"1) Обязательные анализы и скрининги именно для этого срока — что, зачем, что показывает; "
        f"2) Визиты к специалистам — акушер, узист, другие; "
        f"3) Питание — что критически важно сейчас (фолиевая, железо, йод, омега-3 по нормам); "
        f"4) Физическая активность — что разрешено и полезно на этом сроке; "
        f"5) Что нужно сделать практически (документы, курсы, подготовка); "
        f"6) Тревожные симптомы на этом сроке — когда срочно к врачу."
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "pregnancy_checklist", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "pregnancy_checklist", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "weeks": weeks, "answer": answer}


@app.get("/api/miniapp/pregnancy/shop")
async def miniapp_pregnancy_shop(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    date_value = _miniapp_require_pregnant_profile(user)
    weeks, _days = _miniapp_pregnancy_weeks_days(date_value)
    log_analytics_event_tg(user_id, "request_started", "pregnancy_shop", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
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
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "pregnancy_shop", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "pregnancy_shop", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "weeks": weeks, "answer": answer}


# ========== MINI APP: ВОПРОС СПЕЦИАЛИСТУ ==========
# Тот же системный prompt, тот же OpenAI client (gpt-4o, max_tokens=2000) и те же правила
# ответа, что и в handle_question() из mama_bot.py (Telegram). Читает mama.db только для
# контекста (режим/возраст), текст вопроса в отдельную таблицу не сохраняется и не логируется.
MINIAPP_ASK_QUESTION_MAX_LEN = 2000


async def _miniapp_ask_gpt(system_prompt, user_prompt):
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2000,
        )
        return clean_text(response.choices[0].message.content)
    except Exception as exc:
        logging.exception("Ошибка AI MiniApp ask-question")
        await notify_owner_max(f"⚠️ Ошибка AI MiniApp ask-question\n\n{type(exc).__name__}: {exc}", key=f"ai_miniapp_{type(exc).__name__}")
        return AI_FAILURE_MESSAGE


@app.post("/api/miniapp/ask-question")
async def miniapp_ask_question(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    question = str((body or {}).get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question_required")
    if len(question) > MINIAPP_ASK_QUESTION_MAX_LEN:
        raise HTTPException(status_code=400, detail="question_too_long")

    context = "Мама задаёт вопрос о ребёнке или беременности."
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
        if row:
            mode = row["mode"] or ""
            date_value = row["date_value"] or ""
            if mode == "pregnant":
                weeks = _miniapp_pregnancy_weeks(date_value)
                if weeks is not None:
                    context = f"Женщина на {weeks} неделе беременности задаёт вопрос."
            elif mode:
                months = _miniapp_child_months(date_value)
                if months is not None:
                    context = f"Мама, ребёнку {age_label(months)} ({months} месяцев), задаёт вопрос."
    except Exception:
        logging.exception("miniapp_ask_question: profile lookup error")

    log_analytics_event_tg(user_id, "request_started", "personal_question", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        "Ты эксперт в педиатрии, перинатальной психологии и детском развитии. "
        f"{context} "
        "Опирайся на рекомендации ВОЗ, AAP, ACOG и труды ведущих специалистов. "
        "Отвечай развёрнуто, точно и с теплом. При медицинских симптомах — направляй к педиатру.",
        question,
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "personal_question", "miniapp", user.get("platform", "telegram"))
        return {"ok": True, "answer": answer}
    log_analytics_event_tg(user_id, "request_failed", "personal_question", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ЛИЧНЫЙ РАЗБОР СИТУАЦИИ ==========
# Platform-aware, как и остальные Mini App endpoints: пишет/читает через _miniapp_db(user) —
# Telegram -> mama.db, MAX -> mama_max.db, платформа берётся из verified initData, не с клиента.
# Оплату Telegram-заявок подтверждает check_payments_loop в mama_bot.py (mama.db); оплату
# MAX-заявок — check_payments_loop в этом же файле (mama_max.db), см. process_personal_review_payment_max.
# Здесь никогда не пишем situation_text в логи/аналитику.
PERSONAL_REVIEW_MIN_LEN = 10
PERSONAL_REVIEW_MAX_LEN = 4000
PERSONAL_REVIEW_STATUS_LABELS = {
    "draft": {"title": "Заявка не завершена", "detail": "Заполните форму и оплатите разбор."},
    "payment_pending": {"title": "Ждём подтверждение оплаты", "detail": "Обычно это занимает несколько секунд."},
    "paid": {"title": "Заявка принята", "detail": "Личный разбор готовит автор проекта."},
    "in_review": {"title": "Заявка принята", "detail": "Личный разбор готовит автор проекта."},
    "answered": {"title": "Ваш разбор готов", "detail": "Голосовое сообщение отправлено вам в бот «Мамин помощник»."},
    "cancelled": {"title": "Оплата не прошла", "detail": "Попробуйте отправить заявку ещё раз."},
}


def _personal_reviews_ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS personal_reviews (
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_user ON personal_reviews(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_status ON personal_reviews(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_personal_reviews_payment ON personal_reviews(payment_id)")


def _valid_email(value):
    value = (value or "").strip()
    if not value or " " in value or value.count("@") != 1 or len(value) > 254:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


async def _create_personal_review_payment(user_id, review_id):
    amount_str = f"{PERSONAL_REVIEW_PRICE_RUB:.2f}"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json={
                "amount": {"value": amount_str, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": "https://maminpomoshnik.ru/payment/success"},
                "capture": True,
                "description": "Личный разбор ситуации",
                "receipt": {"customer": {"email": "6038484@mail.ru"}, "items": [{
                    "description": "Личный разбор ситуации", "quantity": "1.00",
                    "amount": {"value": amount_str, "currency": "RUB"}, "vat_code": 1,
                    "payment_subject": "service", "payment_mode": "full_payment"
                }]},
                "metadata": {"user_id": user_id, "product_code": PERSONAL_REVIEW_PRODUCT_CODE, "product_type": "personal_review", "review_id": review_id}
            },
            headers={"Idempotence-Key": str(uuid.uuid4()), "Content-Type": "application/json"},
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET),
        )
        if not r.is_success:
            raise RuntimeError(f"ЮКасса: {r.status_code} {r.text[:300]}")
        return r.json()


def process_personal_review_payment_max(payment_id, user_id):
    """MAX-аналог process_personal_review_payment из mama_bot.py, но пишет в mama_max.db
    (DB) через db_connect(), которую здесь же читает check_payments_loop. Идемпотентно
    фиксирует оплату личного разбора; не выдаёт кредиты, не активирует подписку."""
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    try:
        _personal_reviews_ensure_schema(conn)
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
            (payment_id, now_iso, "max", user_id, PERSONAL_REVIEW_PRODUCT_CODE, f"{PERSONAL_REVIEW_PRICE_RUB:.2f}", "RUB", ""),
        )
        conn.execute("DELETE FROM pending_payments WHERE payment_id=?", (payment_id,))
        conn.commit(); return True, review_id
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def mark_personal_review_canceled_max(payment_id):
    now_iso = datetime.now().isoformat()
    conn = db_connect()
    try:
        _personal_reviews_ensure_schema(conn)
        conn.execute(
            "UPDATE personal_reviews SET status='cancelled',payment_status='cancelled',updated_at=? "
            "WHERE payment_id=? AND status IN ('draft','payment_pending')",
            (now_iso, payment_id),
        )
        conn.commit()
    finally:
        conn.close()


# ─── ЛИЧНЫЙ РАЗБОР СИТУАЦИИ: owner-flow (MAX) ──────────────────
# Эквивалент pr_open/pr_take/pr_receive_voice/pr_rerecord/pr_send из mama_bot.py,
# читает и пишет только personal_reviews в mama_max.db (см. db_connect() выше).
# MAX API в этом проекте подтверждён только для входящих voice/audio-вложений
# (см. process_voice) и для исходящих image/file-вложений (upload_channel_image_to_max,
# aura_owner_book_delivery.py). Исходящий voice/audio ни в mama_max_bot.py, ни в
# aura_max_bot.py не используется нигде — поэтому голос владельца скачивается и
# сохраняется как локальный файл (безопасная временная ссылка в уже существующей
# колонке answer_path), а доставляется получателю как file-вложение по проверенному
# паттерну /uploads?type=file + retry на attachment.not.ready.
PERSONAL_REVIEW_VOICE_DIR = "/root/mama_max_personal_review_voices"

_PR_STATUS_LABELS_OWNER = {
    "draft": "черновик", "payment_pending": "ожидает оплаты", "paid": "оплачена",
    "in_review": "в работе", "answered": "отвечена", "cancelled": "отменена",
}


def _pr_status_label_max(status):
    return _PR_STATUS_LABELS_OWNER.get(status, status)


def get_personal_review_max(review_id):
    with db_connect() as conn:
        _personal_reviews_ensure_schema(conn)
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM personal_reviews WHERE id=?", (review_id,)).fetchone()


def take_personal_review_max(review_id):
    """paid -> in_review, идемпотентно (повторное нажатие ничего не меняет)."""
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        _personal_reviews_ensure_schema(conn)
        cur = conn.execute(
            "UPDATE personal_reviews SET status='in_review',updated_at=? WHERE id=? AND status='paid'",
            (now_iso, review_id),
        )
        return cur.rowcount == 1


def attach_personal_review_voice_max(review_id, voice_path):
    """Привязывает локальный путь к голосовому владельца. answer_file_id (постоянный
    MAX-идентификатор) не подтверждён для исходящих voice/audio, поэтому используется
    answer_path — то же поле, что уже есть в схеме personal_reviews."""
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        _personal_reviews_ensure_schema(conn)
        cur = conn.execute(
            "UPDATE personal_reviews SET answer_path=?,updated_at=? WHERE id=? AND status='in_review'",
            (voice_path, now_iso, review_id),
        )
        return cur.rowcount == 1


def mark_personal_review_answered_max(review_id):
    """in_review -> answered, идемпотентно. True только на первом успешном переходе —
    повторный вызов после answered ничего не меняет и не должен приводить к повторной отправке."""
    now_iso = datetime.now().isoformat()
    with db_connect() as conn:
        _personal_reviews_ensure_schema(conn)
        cur = conn.execute(
            "UPDATE personal_reviews SET status='answered',answered_at=?,updated_at=? "
            "WHERE id=? AND status='in_review' AND answer_path IS NOT NULL",
            (now_iso, now_iso, review_id),
        )
        return cur.rowcount == 1


def _extract_max_file_token(data):
    """Рекурсивный поиск token в ответе MAX /uploads?type=file — тот же проверенный
    паттерн, что и в aura_owner_book_delivery.py (send_owner_pdf_via_max)."""
    if isinstance(data, str):
        return data if len(data) > 10 else None
    if isinstance(data, dict):
        if "token" in data:
            return data["token"]
        for v in data.values():
            result = _extract_max_file_token(v)
            if result:
                return result
    if isinstance(data, list):
        for item in data:
            result = _extract_max_file_token(item)
            if result:
                return result
    return None


async def send_personal_review_voice_max(chat_id, voice_path):
    """Доставляет голосовой ответ владельца получателю через MAX Bot API как
    file-вложение (см. пояснение в шапке секции выше). Возвращает True только
    при подтверждённой отправке."""
    if not voice_path or not os.path.exists(voice_path):
        logging.error("send_personal_review_voice_max: файл не найден %s", voice_path)
        return False
    headers = {"Authorization": MAX_TOKEN}
    filename = os.path.basename(voice_path)
    content_type = "audio/mpeg" if voice_path.endswith(".mp3") else "audio/ogg"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            init_resp = await client.post(f"{MAX_API}/uploads?type=file", headers=headers)
            if not init_resp.is_success:
                logging.error("MAX personal review voice upload init error %s %s", init_resp.status_code, init_resp.text[:300])
                return False
            upload_url = init_resp.json().get("url")
            if not upload_url:
                logging.error("MAX personal review voice upload init: в ответе нет url")
                return False
            with open(voice_path, "rb") as f:
                upload_resp = await client.post(upload_url, files={"data": (filename, f, content_type)})
            if not upload_resp.is_success:
                logging.error("MAX personal review voice upload error %s %s", upload_resp.status_code, upload_resp.text[:300])
                return False
            try:
                token = _extract_max_file_token(upload_resp.json())
            except ValueError:
                token = None
            if not token:
                logging.error("MAX personal review voice upload: token не найден")
                return False
            payload = {"text": " ", "attachments": [{"type": "file", "payload": {"token": token}}]}
            sent = None
            for attempt in range(5):
                sent = await client.post(
                    f"{MAX_API}/messages?chat_id={chat_id}", json=payload,
                    headers={**headers, "Content-Type": "application/json"},
                )
                if sent.status_code < 400:
                    return True
                if sent.status_code == 400 and "attachment.not.ready" in (sent.text or ""):
                    await asyncio.sleep(1.5)
                    continue
                break
            logging.error("MAX personal review voice send error %s %s", sent.status_code if sent else "?", (sent.text[:300] if sent else ""))
            return False
    except Exception:
        logging.exception("send_personal_review_voice_max exception")
        return False


async def pr_receive_voice_max(chat_id, user_id, step, audio_url):
    """MAX-аналог pr_receive_voice из mama_bot.py: принимает голос/аудио владельца
    для заявки, скачивает и сохраняет как безопасную временную ссылку (локальный
    файл), затем показывает подтверждение отправки."""
    try:
        review_id = int(step.replace("pr_voice_", "", 1))
    except ValueError:
        set_step(user_id, "idle")
        await send_message(chat_id, "Нет активной заявки для голосового ответа.")
        return
    row = get_personal_review_max(review_id)
    if not row or row["status"] != "in_review":
        set_step(user_id, "idle")
        await send_message(chat_id, f"Заявка №{review_id} недоступна для голосового ответа.")
        return
    audio_bytes, audio_mime = await download_file(audio_url, max_size=25 * 1024 * 1024)
    if not audio_bytes:
        await send_message(chat_id, "Не удалось получить голосовое. Попробуй отправить ещё раз.")
        return
    try:
        os.makedirs(PERSONAL_REVIEW_VOICE_DIR, exist_ok=True)
        ext = "mp3" if audio_mime == "audio/mpeg" else "ogg"
        for stale_ext in ("ogg", "mp3"):
            if stale_ext == ext:
                continue
            stale_path = os.path.join(PERSONAL_REVIEW_VOICE_DIR, f"{review_id}.{stale_ext}")
            if os.path.exists(stale_path):
                os.remove(stale_path)
        voice_path = os.path.join(PERSONAL_REVIEW_VOICE_DIR, f"{review_id}.{ext}")
        with open(voice_path, "wb") as f:
            f.write(audio_bytes)
    except Exception:
        logging.exception("pr_receive_voice_max: не удалось сохранить файл заявки %s", review_id)
        await send_message(chat_id, "Не удалось сохранить голосовое. Попробуй ещё раз.")
        return
    ok = attach_personal_review_voice_max(review_id, voice_path)
    set_step(user_id, "idle")
    if not ok:
        await send_message(chat_id, f"Не удалось привязать голосовое к заявке №{review_id} — проверь её статус через «Открыть заявку».")
        return
    await send_message(
        chat_id,
        "Отправить ответ клиенту?",
        [
            [{"type": "callback", "text": "✅ Отправить ответ клиенту", "payload": f"pr_send:{review_id}"}],
            [{"type": "callback", "text": "🔁 Записать заново", "payload": f"pr_rerecord:{review_id}"}],
        ],
    )


@app.post("/api/miniapp/personal-review/submit")
async def miniapp_personal_review_submit(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    try:
        body = await request.json()
    except Exception:
        body = {}
    situation_text = str((body or {}).get("situation_text") or "").strip()
    preferred_reply = str((body or {}).get("preferred_reply") or "telegram").strip().lower()
    email = str((body or {}).get("email") or "").strip()
    consent = bool((body or {}).get("consent"))
    disclaimer_ack = bool((body or {}).get("disclaimer_ack"))

    if len(situation_text) < PERSONAL_REVIEW_MIN_LEN:
        raise HTTPException(status_code=400, detail="situation_text_too_short")
    if len(situation_text) > PERSONAL_REVIEW_MAX_LEN:
        raise HTTPException(status_code=400, detail="situation_text_too_long")
    if preferred_reply not in ("telegram", "email"):
        raise HTTPException(status_code=400, detail="invalid_preferred_reply")
    if preferred_reply == "email" and not _valid_email(email):
        raise HTTPException(status_code=400, detail="invalid_email")
    if not consent:
        raise HTTPException(status_code=400, detail="consent_required")
    if not disclaimer_ack:
        raise HTTPException(status_code=400, detail="disclaimer_required")

    now = datetime.now().isoformat()
    review_id = None
    try:
        with _miniapp_db(user) as conn:
            _personal_reviews_ensure_schema(conn)
            cur = conn.execute(
                "INSERT INTO personal_reviews(platform,user_id,situation_text,preferred_reply,email,consent_at,payment_status,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (platform, user_id, situation_text, preferred_reply, email if preferred_reply == "email" else None, now, "unpaid", "draft", now, now),
            )
            review_id = cur.lastrowid
            conn.commit()
    except Exception:
        logging.exception("miniapp_personal_review_submit: db insert error")
        raise HTTPException(status_code=500, detail="internal_error")

    try:
        payment = await _create_personal_review_payment(user_id, review_id)
    except Exception:
        logging.exception("miniapp_personal_review_submit: yookassa error")
        try:
            with _miniapp_db(user) as conn:
                conn.execute("DELETE FROM personal_reviews WHERE id=? AND status='draft'", (review_id,))
                conn.commit()
        except Exception:
            logging.exception("miniapp_personal_review_submit: cleanup after payment error failed")
        raise HTTPException(status_code=502, detail="payment_create_failed")

    payment_id = payment.get("id")
    confirmation = payment.get("confirmation") or {}
    confirmation_url = confirmation.get("confirmation_url")
    amount_str = f"{PERSONAL_REVIEW_PRICE_RUB:.2f}"
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "UPDATE personal_reviews SET payment_id=?,status='payment_pending',payment_status='pending',updated_at=? WHERE id=?",
                (payment_id, datetime.now().isoformat(), review_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)",
                (payment_id, user_id, PERSONAL_REVIEW_PRODUCT_CODE, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (payment_id, user_id, platform, "personal_review", PERSONAL_REVIEW_PRODUCT_CODE, amount_str, "RUB", "pending", now, now),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_personal_review_submit: db update error after payment create")
        raise HTTPException(status_code=500, detail="internal_error")

    log_analytics_event_tg(user_id, "personal_review_payment_created", PERSONAL_REVIEW_PRODUCT_CODE, payment_id, platform)
    return {"ok": True, "review_id": review_id, "payment_id": payment_id, "confirmation_url": confirmation_url, "amount": PERSONAL_REVIEW_PRICE_RUB}


@app.get("/api/miniapp/personal-review/status")
async def miniapp_personal_review_status(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    review_id = request.query_params.get("id")
    if not review_id or not review_id.isdigit():
        raise HTTPException(status_code=400, detail="invalid_id")
    row = None
    try:
        with _miniapp_db(user) as conn:
            _personal_reviews_ensure_schema(conn)
            row = conn.execute(
                "SELECT id,user_id,status,preferred_reply,answered_at,created_at FROM personal_reviews WHERE id=?",
                (int(review_id),),
            ).fetchone()
    except Exception:
        logging.exception("miniapp_personal_review_status db error")
        raise HTTPException(status_code=500, detail="internal_error")
    if not row or int(row["user_id"]) != int(user_id):
        raise HTTPException(status_code=404, detail="not_found")
    label = PERSONAL_REVIEW_STATUS_LABELS.get(row["status"], {"title": row["status"], "detail": ""})
    return {
        "ok": True,
        "review_id": row["id"],
        "status": row["status"],
        "title": label["title"],
        "detail": label["detail"],
        "answered": row["status"] == "answered",
        "answered_at": row["answered_at"] or "",
    }


# ========== MINI APP: ПОДДЕРЖАТЬ ПРОЕКТ (ДОНАТ) ==========
# Переиспользует существующий добровольный support-flow: create_support_payment() — тот же
# вызов ЮKassa (креды/провайдер не меняются), что уже использует нативный MAX-бот
# (donate_confirm) и mama_bot.py (Telegram). Новый webhook не создаётся. Запись уходит в
# pending_payments/payments/support_payments БД своей платформы (_miniapp_db, telegram ->
# mama.db, max -> mama_max.db) — подтверждение оплаты и уведомление делает уже работающий
# check_payments_loop: свой для Telegram (mama_bot.py) и свой для MAX (в этом файле).
# Донат не выдаёт кредиты, не активирует подписку и не меняет тариф.
DONATE_MINIAPP_VARIANTS = {str(int(a)) for a, _ in DONATE_AMOUNTS} | {"custom"}


@app.post("/api/miniapp/support/create")
async def miniapp_support_create(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    try:
        body = await request.json()
    except Exception:
        body = {}
    variant = str((body or {}).get("variant") or "").strip()
    if variant not in DONATE_MINIAPP_VARIANTS:
        raise HTTPException(status_code=400, detail="invalid_variant")
    try:
        amount = round(float((body or {}).get("amount")), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_amount")
    if not (DONATE_MIN_AMOUNT <= amount <= DONATE_MAX_AMOUNT):
        raise HTTPException(status_code=400, detail="invalid_amount")
    if variant != "custom" and amount != float(variant):
        raise HTTPException(status_code=400, detail="invalid_amount")

    try:
        payment = await create_support_payment(user_id, amount)
    except Exception:
        logging.exception("miniapp_support_create: yookassa error")
        raise HTTPException(status_code=502, detail="payment_create_failed")

    payment_id = payment.get("id")
    confirmation_url = (payment.get("confirmation") or {}).get("confirmation_url")
    if not payment_id or not confirmation_url:
        raise HTTPException(status_code=502, detail="payment_create_failed")

    amount_str = f"{amount:.2f}"
    now = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute("INSERT OR IGNORE INTO pending_payments(payment_id,user_id,plan,created_at) VALUES (?,?,?,?)", (payment_id, user_id, "support_project", now))
            conn.execute(
                "INSERT OR IGNORE INTO payments(payment_id,user_id,platform,product_type,product_code,amount,currency,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (payment_id, user_id, platform, "support", "support_project", amount_str, "RUB", "pending", now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO support_payments(payment_id,user_id,platform,amount,currency,status,variant,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (payment_id, user_id, platform, amount_str, "RUB", "pending", variant, "miniapp", now, now),
            )
    except Exception:
        logging.exception("miniapp_support_create: db error")
        raise HTTPException(status_code=500, detail="internal_error")

    log_analytics_event_tg(user_id, "support_payment_created", variant, amount_str, platform)
    return {"ok": True, "payment_id": payment_id, "confirmation_url": confirmation_url, "amount": amount}


# ========== MINI APP: ИСТЕРИКИ И ЭМОЦИИ ==========
# Те же системные prompts, тот же OpenAI client (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt),
# что и в mama_tantrums() / mama_emotions() из mama_bot.py (Telegram) — тексты скопированы дословно.
# Возраст ребёнка для "Истерики ребёнка" читается из mama.db (users.date_value), как в Telegram
# (mama_gpt_handler требует заполненный профиль); "Эмоции мамы" от возраста не зависит, как в Telegram.
MINIAPP_TANTRUMS_SYSTEM = (
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

MINIAPP_EMOTIONS_SYSTEM = (
    MINIAPP_TANTRUMS_SYSTEM + " Ты также специалист по послеродовой психологии и материнскому выгоранию. "
    "Говори с мамой как заботливый друг-эксперт — тепло, без осуждения, с глубоким пониманием. "
    "Мама важна не меньше ребёнка. Это научный факт."
)

MINIAPP_EMOTIONS_PROMPT = (
    "Дай развёрнутую научную информацию об эмоциональном состоянии мамы после родов. "
    "1) Послеродовая депрессия vs беби-блюз — в чём разница, критерии DSM-5, распространённость по данным ВОЗ; "
    "2) Материнское выгорание — симптомы, исследования Моники Роскам; "
    "3) Тревожность молодых мам — нейрофизиология и доказанные методы снижения; "
    "4) Самозабота с научной точки зрения — что реально восстанавливает ресурс мамы; "
    "5) Когда нужна профессиональная помощь — конкретные признаки. "
    "Говори тепло, поддерживающе, без осуждения."
)


@app.post("/api/miniapp/tantrums")
async def miniapp_tantrums(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    months = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
        if row and row["mode"] and row["mode"] != "pregnant":
            months = _miniapp_child_months(row["date_value"] or "")
    except Exception:
        logging.exception("miniapp_tantrums: profile lookup error")
    if months is None:
        raise HTTPException(status_code=400, detail="profile_required")

    log_analytics_event_tg(user_id, "request_started", "tantrums", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        MINIAPP_TANTRUMS_SYSTEM,
        f"Объясни поведение ребёнка {age_label(months)} ({months} месяцев) с нейронаучной точки зрения "
        f"на основе трудов Людмилы Петрановской, Дэниэла Сигела и Тины Пейн Брайсон. "
        f"1) Почему ребёнок ведёт себя именно так — незрелость префронтальной коры; "
        f"2) Теория привязанности Петрановской — как это применить прямо сейчас; "
        f"3) Метод 'Connect and Redirect' Сигела — пошаговый алгоритм; "
        f"4) Что делать в момент истерики — конкретные фразы и действия; "
        f"5) Как НЕ навредить психике ребёнка — чего избегать категорически.",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "tantrums", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "tantrums", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


@app.post("/api/miniapp/emotions")
async def miniapp_emotions(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    log_analytics_event_tg(user_id, "request_started", "emotions", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_EMOTIONS_SYSTEM, MINIAPP_EMOTIONS_PROMPT)
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "emotions", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "emotions", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: МАМИН ПСИХОЛОГ ==========
# Тот же сценарий psycho_start/psycho_message/psycho_clear, что и в mama_bot.py (Telegram) и
# в step=="psycho" из этого файла (MAX-бот): тот же PSYCHO_SYSTEM, тот же OpenAI client
# (gpt-4o, max_tokens=800), та же таблица psycho_history (без новой таблицы), история читается
# и пишется через _miniapp_db(user) — своя БД на платформу (mama.db/mama_max.db), как и во всех
# остальных miniapp-эндпоинтах. Лимит psycho_messages (премиум/апсейл) здесь намеренно не
# применяется — как и в остальных AI-эндпоинтах Mini App (ask-question/emotions/tantrums/
# kindergarten), чтобы не трогать логику payments/subscriptions.
# Точный Telegram PSYCHO_SYSTEM (mama_bot.py, PsychoStates.in_session / psycho_message) — дословно,
# без сокращений и перефразирования, включая инструкцию по кризисным состояниям и мягкое
# направление к специалисту. Используется ТОЛЬКО эндпоинтом Mini App /api/miniapp/psycho/message
# (обе платформы, Telegram и MAX, проходят через этот же FastAPI-процесс). Отдельно от глобального
# PSYCHO_SYSTEM выше (используется MAX chat-flow step=="psycho", не трогаем).
MINIAPP_PSYCHO_SYSTEM_TG = """Ты Мамин психолог — тёплый, внимательный, профессиональный психолог специально для мам.

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

MINIAPP_PSYCHO_MAX_LEN = 2000
MINIAPP_PSYCHO_AI_HISTORY_LIMIT = 15  # столько сообщений уходит в контекст GPT — как в Telegram/MAX
MINIAPP_PSYCHO_DISPLAY_LIMIT = 60  # сколько сообщений отдаём на экран истории чата


def _miniapp_psycho_context(row):
    if not row:
        return ""
    mode = row["mode"] or ""
    date_value = row["date_value"] or ""
    if mode == "pregnant":
        weeks = _miniapp_pregnancy_weeks(date_value)
        if weeks is not None:
            return f"Это беременная женщина на {weeks} неделе."
    elif mode:
        months = _miniapp_child_months(date_value)
        if months is not None:
            return f"Это мама, ребёнку {age_label(months)} ({months} месяцев)."
    return ""


@app.get("/api/miniapp/psycho/history")
async def miniapp_psycho_history(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    items = []
    try:
        with _miniapp_db(user) as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM psycho_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, MINIAPP_PSYCHO_DISPLAY_LIMIT),
            ).fetchall()
        items = [
            {"role": r["role"] or "assistant", "content": r["content"] or "", "created_at": r["created_at"] or ""}
            for r in reversed(rows)
        ]
    except Exception:
        logging.exception("miniapp_psycho_history db error")
        raise HTTPException(status_code=500, detail="db_error")
    return {"ok": True, "items": items}


@app.post("/api/miniapp/psycho/message")
async def miniapp_psycho_message(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str((body or {}).get("message") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message_required")
    if len(text) > MINIAPP_PSYCHO_MAX_LEN:
        raise HTTPException(status_code=400, detail="message_too_long")

    context = ""
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            context = _miniapp_psycho_context(row)
            conn.execute(
                "INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                (user_id, "user", text, created_at),
            )
            conn.commit()
            history_rows = conn.execute(
                "SELECT role, content FROM psycho_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, MINIAPP_PSYCHO_AI_HISTORY_LIMIT),
            ).fetchall()
    except HTTPException:
        raise
    except Exception:
        logging.exception("miniapp_psycho_message db error")
        raise HTTPException(status_code=500, detail="db_error")

    history = list(reversed(history_rows))
    messages = [{"role": "system", "content": MINIAPP_PSYCHO_SYSTEM_TG + (f" {context}" if context else "")}]
    for r in history[:-1]:
        messages.append({"role": r["role"], "content": r["content"]})
    messages.append({"role": "user", "content": text})

    log_analytics_event_tg(user_id, "request_started", "psycho", "miniapp", user.get("platform", "telegram"))
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=800)
        answer = clean_text(response.choices[0].message.content)
    except Exception as exc:
        logging.exception("miniapp_psycho_message AI error")
        await notify_owner_max(
            f"⚠️ Ошибка AI MiniApp psycho\n\n{type(exc).__name__}: {exc}",
            key=f"ai_miniapp_psycho_{type(exc).__name__}",
        )
        answer = AI_FAILURE_MESSAGE

    if ai_answer_success(answer):
        try:
            with _miniapp_db(user) as conn:
                conn.execute(
                    "INSERT INTO psycho_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                    (user_id, "assistant", answer, datetime.now().isoformat()),
                )
                conn.commit()
        except Exception:
            logging.exception("miniapp_psycho_message: save assistant error")
        log_analytics_event_tg(user_id, "request_completed", "psycho", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "psycho", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


@app.post("/api/miniapp/psycho/clear")
async def miniapp_psycho_clear(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        with _miniapp_db(user) as conn:
            conn.execute("DELETE FROM psycho_history WHERE user_id=?", (user_id,))
            conn.commit()
    except Exception:
        logging.exception("miniapp_psycho_clear db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "psycho_clear", "miniapp", user.get("platform", "telegram"))
    return {"ok": True}


# ========== MINI APP: УДАЛИТЬ МОИ ДАННЫЕ ==========
# Перенос reset_me/reset_me_confirm из mama_bot.py (Telegram) в Mini App: список таблиц
# скопирован дословно из reset_me_confirm_tg, включая допущение "таблицы может не быть на
# этой платформе — пропускаем" (sqlite3.OperationalError), как в оригинале. Платёжный журнал
# (payments/processed_payments/subscription_history/purchases/sales_events/support_payments)
# в список не входит и не трогается — как и в Telegram-сценарии. user_id берётся только из
# проверенного initData (_miniapp_require_user), с клиента не принимается.
MINIAPP_RESET_ME_TABLES = [
    "diary", "growth", "symptoms", "feeding", "sleep_log", "psycho_history",
    "vaccinations", "subscriptions", "requests_count", "user_credits",
    "marketing_offers", "pending_payments", "users"
]


@app.post("/api/miniapp/reset-me")
async def miniapp_reset_me(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="confirm_required")
    try:
        with _miniapp_db(user) as conn:
            for table in MINIAPP_RESET_ME_TABLES:
                try:
                    conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "no such table" not in msg and "no such column" not in msg:
                        raise
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        logging.exception("miniapp_reset_me db error")
        raise HTTPException(status_code=500, detail="db_error")
    return {"ok": True, "reset": True}


# ========== MINI APP: САДИК ==========
# Тот же системный prompt (EXPERT_BASE) и тот же user prompt, тот же OpenAI client
# (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt), что и в fd_sadik() из mama_bot.py
# (Telegram) — текст скопирован дословно. fd_sadik не использует профиль/возраст
# ребёнка, поэтому запрос к users не выполняется, как и в Telegram-сценарии.
MINIAPP_KINDERGARTEN_SYSTEM = MINIAPP_TANTRUMS_SYSTEM

MINIAPP_KINDERGARTEN_PROMPT = (
    "Дай подробную инструкцию по записи ребёнка в детский сад в России. "
    "1) Когда вставать в очередь — оптимальный возраст ребёнка; "
    "2) Как встать в очередь через Госуслуги — пошагово; "
    "3) Какие документы нужны; "
    "4) Как работает система льготных очередей — кто имеет право; "
    "5) Что делать если отказали или долго ждать; "
    "6) С какого возраста берут в садик по закону. "
    "Конкретно и пошагово."
)


@app.post("/api/miniapp/kindergarten")
async def miniapp_kindergarten(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    log_analytics_event_tg(user_id, "request_started", "kindergarten", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_KINDERGARTEN_SYSTEM, MINIAPP_KINDERGARTEN_PROMPT)
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "kindergarten", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "kindergarten", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПЕРВЫЕ ДНИ С МАЛЫШОМ ==========
# Тот же системный prompt (EXPERT_BASE/MINIAPP_TANTRUMS_SYSTEM) и те же user prompts, тот же
# OpenAI client (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt), что и в fd_pediatr/fd_doctors/
# fd_svid/fd_massage/fd_swim из mama_bot.py (Telegram) — тексты скопированы дословно. Единый
# endpoint с query-параметром topic, авторизация через _miniapp_require_user (user_id с клиента
# не доверяется). Ни один из этих 5 Telegram-хендлеров не использует профиль/возраст ребёнка,
# поэтому запрос к users не выполняется — как и в /api/miniapp/kindergarten. fd_sadik сюда
# намеренно НЕ включён — это уже отдельный рабочий /api/miniapp/kindergarten, дублировать его
# промпт здесь нельзя.
MINIAPP_FIRSTDAYS_SYSTEM = MINIAPP_TANTRUMS_SYSTEM

MINIAPP_FIRSTDAYS_PROMPTS = {
    "pediatrician": (
        "Расскажи подробно о первом осмотре педиатра после выписки из роддома. "
        "1) Когда педиатр должен прийти по закону — сроки по российскому законодательству; "
        "2) Как вызвать педиатра на дом — пошаговая инструкция (телефон, Госуслуги, сайт поликлиники); "
        "3) Что педиатр проверяет при первом осмотре новорождённого — полный список; "
        "4) Какие вопросы задать педиатру при первом визите; "
        "5) Что приготовить к приходу врача. "
        "Отвечай конкретно и практично."
    ),
    "doctors": (
        "Составь подробный календарь обходов врачей для ребёнка по месяцам — от рождения до 1 года. "
        "По каждому визиту укажи: возраст, каких врачей пройти, какие анализы сдать, "
        "какие прививки по национальному календарю РФ. "
        "Также укажи какие специалисты нужны в 1 год. "
        "Сделай в виде чёткого структурированного списка по месяцам."
    ),
    "documents": (
        "Дай пошаговую инструкцию по оформлению документов на новорождённого в России. "
        "1) Свидетельство о рождении — где получить (ЗАГС/МФЦ/Госуслуги), какие документы нужны, сроки; "
        "2) Регистрация ребёнка по месту жительства — как и где; "
        "3) Полис ОМС на ребёнка — как оформить, сроки; "
        "4) СНИЛС — как получить; "
        "5) Пособия и выплаты — какие положены, куда обращаться, сроки подачи; "
        "6) Материнский капитал — как получить. "
        "Всё пошагово, конкретно, с указанием сроков."
    ),
    "massage": (
        "Дай научно обоснованное руководство по массажу и гимнастике для младенцев. "
        "1) С какого возраста можно начинать массаж — по рекомендациям педиатров; "
        "2) Виды массажа для разных возрастов (0-3 мес, 3-6 мес, 6-12 мес); "
        "3) Пошаговая техника общего укрепляющего массажа — как делать маме дома; "
        "4) Массаж при коликах и газах — техника и движения; "
        "5) Гимнастика по возрастам — конкретные упражнения; "
        "6) Противопоказания к массажу; "
        "7) Когда нужен профессиональный массажист а не домашний. "
        "Описывай движения чётко чтобы мама могла повторить."
    ),
    "swimming": (
        "Дай научно обоснованное руководство по плаванию с младенцем. "
        "1) С какого возраста можно купать и плавать — научные данные; "
        "2) Рефлекс плавания у новорождённых — что это и как использовать; "
        "3) Раннее плавание — польза для физического и нервного развития по исследованиям; "
        "4) Как организовать плавание дома в ванной — пошаговая инструкция; "
        "5) Температура воды, продолжительность, позиции поддержки; "
        "6) Бассейн с грудничком — с какого возраста, что выбрать; "
        "7) Противопоказания к плаванию. "
        "Конкретно и безопасно."
    ),
}


@app.get("/api/miniapp/content/firstdays")
async def miniapp_content_firstdays(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    topic = (request.query_params.get("topic") or "").strip().lower()
    if topic not in MINIAPP_FIRSTDAYS_PROMPTS:
        raise HTTPException(status_code=400, detail="invalid_topic")

    log_analytics_event_tg(user_id, "request_started", "firstdays_" + topic, "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_FIRSTDAYS_SYSTEM, MINIAPP_FIRSTDAYS_PROMPTS[topic])
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "firstdays_" + topic, "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "firstdays_" + topic, "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ГРУДНОЕ ВСКАРМЛИВАНИЕ ==========
# Тот же системный prompt (EXPERT_BASE/MINIAPP_TANTRUMS_SYSTEM) и те же user prompts, тот же
# OpenAI client (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt), что и в bf_start/bf_pump/
# bf_lactostaz/bf_food/bf_nofood/bf_formula из mama_bot.py (Telegram) — тексты скопированы
# дословно. Единый endpoint с query-параметром topic, авторизация через _miniapp_require_user
# (user_id с клиента не доверяется).
MINIAPP_BREASTFEEDING_PROMPTS = {
    "start": (
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
    ),
    "pump": (
        "Дай научно обоснованное руководство по увеличению лактации и расцеживанию. "
        "1) Почему молока может быть мало — физиологические причины; "
        "2) Как стимулировать выработку молока — доказанные методы (частые прикладывания, сцеживание, контакт кожа-к-коже); "
        "3) Техника ручного сцеживания — пошагово, движения, как правильно; "
        "4) Молокоотсос — как выбрать, как пользоваться правильно; "
        "5) Питание и питьевой режим мамы для лактации — что реально помогает по науке; "
        "6) Лактогонные средства — что доказано, что миф; "
        "7) Когда обратиться к консультанту по ГВ. "
    ),
    "lactostaz": (
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
    ),
    "food": (
        "Дай научно обоснованные рекомендации по питанию кормящей мамы. "
        "1) Принципы питания при ГВ по позиции ВОЗ — что реально важно; "
        "2) Что обязательно включить в рацион — белки, жиры, углеводы, витамины, минералы; "
        "3) Продукты которые улучшают качество молока — с научным обоснованием; "
        "4) Витамины для кормящей мамы — какие нужны, дозировки по нормам; "
        "5) Водный режим — сколько пить и что; "
        "6) Развенчание мифов о диете при ГВ — что на самом деле не нужно исключать. "
        "Конкретно и без излишних ограничений."
    ),
    "nofood": (
        "Дай научно обоснованный список того что нельзя или нужно ограничить при грудном вскармливании. "
        "1) Алкоголь — как влияет на молоко, безопасный интервал по данным AAP; "
        "2) Кофеин — допустимые дозы, в каких продуктах содержится; "
        "3) Аллергены — нужно ли исключать заранее или только при реакции ребёнка; "
        "4) Лекарства при ГВ — общий принцип, где проверять совместимость (LactMed); "
        "5) Продукты которые влияют на вкус молока; "
        "6) Что категорически запрещено. "
        "Развенчай популярные мифы — многие мамы излишне ограничивают себя без причины."
    ),
    "formula": (
        "Дай поддерживающее и научно обоснованное руководство по переходу на смесь. "
        "1) Когда переход на смесь оправдан — медицинские показания; "
        "2) Как правильно завершить ГВ — постепенно, без вреда для здоровья мамы; "
        "3) Как выбрать смесь по возрасту — на что смотреть в составе; "
        "4) Как правильно разводить смесь — температура, пропорции, стерильность; "
        "5) Смешанное вскармливание — как совмещать ГВ и смесь; "
        "6) Психологический аспект — мама не должна чувствовать вину. "
        "Отвечай без осуждения, поддерживающе."
    ),
}


@app.get("/api/miniapp/content/breastfeeding")
async def miniapp_content_breastfeeding(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    topic = (request.query_params.get("topic") or "").strip().lower()
    if topic not in MINIAPP_BREASTFEEDING_PROMPTS:
        raise HTTPException(status_code=400, detail="invalid_topic")

    log_analytics_event_tg(user_id, "request_started", "breastfeeding_" + topic, "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_TANTRUMS_SYSTEM, MINIAPP_BREASTFEEDING_PROMPTS[topic])
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "breastfeeding_" + topic, "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "breastfeeding_" + topic, "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ВОССТАНОВЛЕНИЕ МАМЫ ==========
# Тот же системный prompt (EXPERT_BASE/MINIAPP_TANTRUMS_SYSTEM) и те же user prompts, тот же
# OpenAI client (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt), что и в rec_natural/rec_caesar/
# rec_sport/rec_intimate/rec_hair/rec_diastaz из mama_bot.py (Telegram) — тексты скопированы
# дословно. Единый endpoint с query-параметром topic, авторизация через _miniapp_require_user
# (user_id с клиента не доверяется).
MINIAPP_RECOVERY_PROMPTS = {
    "natural": (
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
    ),
    "caesar": (
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
    ),
    "sport": (
        "Дай научно обоснованный план возвращения к физической активности после родов. "
        "1) После естественных родов — когда начинать, с чего начать; "
        "2) После КС — другие сроки и ограничения; "
        "3) Упражнения Кегеля — почему критически важны, как делать правильно; "
        "4) Первые упражнения в роддоме — что безопасно сразу; "
        "5) Диастаз — как проверить самостоятельно, какие упражнения запрещены при диастазе; "
        "6) Постепенный план: 6 недель, 3 месяца, 6 месяцев после родов; "
        "7) Бег, силовые тренировки — когда можно. "
        "С научным обоснованием и без вреда для здоровья."
    ),
    "intimate": (
        "Дай деликатное и научно обоснованное руководство по интимной жизни после родов. "
        "1) Когда физически можно возобновить — рекомендации ACOG после естественных родов и КС; "
        "2) Почему может быть дискомфорт и боль — физиологические причины (сухость, швы, гормоны); "
        "3) Как справиться с сухостью при ГВ — безопасные средства; "
        "4) Психологический аспект — снижение либидо после родов это норма, почему; "
        "5) Как разговаривать с партнёром об этом; "
        "6) Контрацепция после родов — какие методы при ГВ безопасны. "
        "Деликатно, без осуждения, с уважением к маме."
    ),
    "hair": (
        "Объясни послеродовое выпадение волос научно и дай практические рекомендации. "
        "1) Почему выпадают волосы после родов — физиология, роль эстрогена и телогеновой фазы; "
        "2) Когда начинается и заканчивается — нормальные сроки; "
        "3) Это норма или патология — как отличить; "
        "4) Что реально помогает — витамины, питание, уход за волосами с доказательной базой; "
        "5) Что не поможет — развенчание мифов о масках и народных средствах; "
        "6) Когда обратиться к трихологу или эндокринологу. "
        "Поддерживающий тон — многие мамы очень переживают из-за этого."
    ),
    "diastaz": (
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
    ),
}


@app.get("/api/miniapp/content/recovery")
async def miniapp_content_recovery(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    topic = (request.query_params.get("topic") or "").strip().lower()
    if topic not in MINIAPP_RECOVERY_PROMPTS:
        raise HTTPException(status_code=400, detail="invalid_topic")

    log_analytics_event_tg(user_id, "request_started", "recovery_" + topic, "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_TANTRUMS_SYSTEM, MINIAPP_RECOVERY_PROMPTS[topic])
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "recovery_" + topic, "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "recovery_" + topic, "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПОСОБИЯ И ВЫПЛАТЫ ==========
# Тот же системный prompt и те же user prompts, тот же OpenAI client (gpt-4o, max_tokens=2000
# через _miniapp_ask_gpt), что и в benefits_gpt()/ben_birth/ben_15/ben_3/ben_matcap/ben_decree/
# ben_multi из mama_bot.py (Telegram) — тексты скопированы дословно. Единый endpoint с
# query-параметром topic, авторизация через _miniapp_require_user (user_id с клиента не доверяется).
MINIAPP_BENEFITS_SYSTEM = (
    "Ты эксперт по социальным выплатам и пособиям в России. "
    "Давай актуальную информацию на текущую дату; если точная сумма может измениться, предупреди и предложи проверить на Госуслугах или СФР. "
    "Указывай конкретные суммы, сроки подачи, необходимые документы и куда обращаться. "
    "Отвечай структурированно и понятно."
)

MINIAPP_BENEFITS_PROMPTS = {
    "birth": (
        "Расскажи о единовременном пособии при рождении ребёнка в России на текущую дату. "
        "Размер, кто имеет право, документы, куда подавать, сроки."
    ),
    "15": (
        "Расскажи о ежемесячном пособии по уходу за ребёнком до 1.5 лет в России на текущую дату. "
        "Размер для работающих и неработающих мам, как рассчитывается, документы, сроки."
    ),
    "3": (
        "Расскажи о выплатах и пособиях на ребёнка от 1.5 до 3 лет в России на текущую дату. "
        "Путинские выплаты, региональные пособия, условия получения."
    ),
    "matcap": (
        "Расскажи о материнском капитале в России на текущую дату. "
        "Размер на первого и второго ребёнка, на что можно потратить, как оформить через Госуслуги, "
        "сроки получения сертификата."
    ),
    "decree": (
        "Расскажи о пособии по беременности и родам (декретные) в России на текущую дату. "
        "Как рассчитывается для работающих, ИП, безработных. "
        "Сроки декрета, документы, куда обращаться."
    ),
    "multi": (
        "Расскажи о льготах и выплатах многодетным семьям в России на текущую дату. "
        "Федеральные и региональные льготы, налоговые вычеты, земельные участки, "
        "транспортный налог, ЖКХ, досрочная пенсия мамы."
    ),
}


@app.get("/api/miniapp/content/benefits")
async def miniapp_content_benefits(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    topic = (request.query_params.get("topic") or "").strip().lower()
    if topic not in MINIAPP_BENEFITS_PROMPTS:
        raise HTTPException(status_code=400, detail="invalid_topic")

    log_analytics_event_tg(user_id, "request_started", "benefits_" + topic, "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_BENEFITS_SYSTEM, MINIAPP_BENEFITS_PROMPTS[topic])
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "benefits_" + topic, "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "benefits_" + topic, "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПОСОБИЯ — ПЕРСОНАЛЬНЫЙ РАЗБОР ==========
# Тот же системный prompt и user prompt, что и в ben_personal_answer() из mama_bot.py
# (Telegram) — текст скопирован дословно. Текст ситуации нигде не сохраняется (ни в БД, ни в
# аналитике) — так же, как остальные AI-сценарии мини-приложения не пишут вопрос пользователя.
MINIAPP_BENEFITS_PERSONAL_MAX_LEN = 2000


@app.post("/api/miniapp/benefits/personal")
async def miniapp_benefits_personal(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    situation = str((body or {}).get("situation") or "").strip()
    if not situation:
        raise HTTPException(status_code=400, detail="situation_required")
    if len(situation) > MINIAPP_BENEFITS_PERSONAL_MAX_LEN:
        raise HTTPException(status_code=400, detail="situation_too_long")

    log_analytics_event_tg(user_id, "request_started", "benefits_personal", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        "Ты эксперт по социальным выплатам в России на текущую дату. "
        "Давай конкретные персональные рекомендации на основе ситуации мамы.",
        f"Мама описала свою ситуацию: {situation}\n\n"
        f"Перечисли все федеральные и региональные пособия и выплаты на которые она имеет право. "
        f"Для каждого: название, размер, как оформить, куда обратиться. "
        f"Отсортируй по сумме — сначала самые крупные."
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "benefits_personal", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "benefits_personal", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: РЕБЁНОК ==========
# Единый каталог "Ребёнок" — тот же системный prompt (EXPERT_BASE, дословно продублирован как
# MINIAPP_TANTRUMS_SYSTEM выше) и те же user prompts по возрасту ребёнка, тот же OpenAI client
# (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt), что и в mama_dev/mama_games/mama_games_more/
# mama_books/mama_books_more/mama_health/mama_meds/mama_teeth/mama_food/mama_recipes/
# mama_recipes_more/mama_routine/mama_sleep/mama_family из mama_bot.py (Telegram) — тексты
# скопированы дословно. Единый endpoint с query-параметром topic, авторизация через
# _miniapp_require_user (user_id с клиента не доверяется), профиль ребёнка проверяется как в
# mama_gpt_handler()/mama_games() и т.п. — при отсутствии профиля 400 profile_required, не 500.
# "sleep" здесь — контентный AI-раздел "Сон ребёнка" (аналог Telegram mama_sleep): отдельный от
# tracker'а /api/miniapp/sleep/log и /api/miniapp/sleep/analyze (дневник сна) — не путать и не
# смешивать, это разные функции с разным назначением.
MINIAPP_CHILD_PROMPTS = {
    "development": lambda m: (
        f"Дай подробный научно обоснованный анализ развития ребёнка в {age_label(m)} ({m} месяцев). "
        f"Охвати все сферы по стандартам AAP и ВОЗ: "
        f"1) Физическое развитие — моторика крупная и мелкая, нормы роста и веса; "
        f"2) Речевое развитие — что должен говорить/понимать по нормам; "
        f"3) Когнитивное развитие — мышление, память, причинно-следственные связи; "
        f"4) Социально-эмоциональное развитие — привязанность, эмоции, взаимодействие; "
        f"5) Сенсорное развитие — зрение, слух, тактильное восприятие. "
        f"Укажи чёткие нормы и что должно насторожить маму."
    ),
    "games": lambda m: (
        f"Предложи 3-4 научно обоснованные развивающие игры для ребёнка {age_label(m)} ({m} месяцев). "
        f"Опирайся на теорию Выготского и исследования нейропластичности. "
        f"Для каждой: название, как играть пошагово, что развивает. "
        f"Только простые игры без дорогих игрушек."
    ),
    "games_more": lambda m: (
        f"Предложи ещё 3-4 ДРУГИЕ развивающие игры для ребёнка {age_label(m)} ({m} месяцев). "
        f"Не повторяй предыдущие игры. Другие виды активности — сенсорные, моторные, речевые или социальные. "
        f"Для каждой: название, как играть, что развивает."
    ),
    "books": lambda m: (
        f"Порекомендуй 3 книги для чтения ребёнку {age_label(m)} ({m} месяцев). "
        f"Для каждой: название, автор, почему подходит для этого возраста. "
        f"И 1 книгу ДЛЯ МАМЫ от ведущего специалиста по этому возрасту."
    ),
    "books_more": lambda m: (
        f"Порекомендуй ещё 3 ДРУГИЕ книги для ребёнка {age_label(m)} ({m} месяцев). "
        f"Не повторяй предыдущие. Для каждой: название, автор, почему подходит."
    ),
    "health": lambda m: (
        f"Дай исчерпывающую информацию о здоровье ребёнка {age_label(m)} ({m} месяцев) "
        f"по стандартам ВОЗ и AAP. "
        f"1) Типичные проблемы этого возраста и доказанные методы помощи; "
        f"2) Алгоритм действий при температуре (по протоколам AAP); "
        f"3) Признаки ОРВИ vs бактериальной инфекции — когда антибиотики НЕ нужны; "
        f"4) Красные флаги — симптомы при которых немедленно к врачу; "
        f"5) Плановые осмотры и прививки по календарю ВОЗ для этого возраста."
    ),
    "meds": lambda m: (
        f"Дай научно обоснованную информацию о лекарственной безопасности "
        f"для ребёнка {age_label(m)} ({m} месяцев) по стандартам AAP. "
        f"1) Жаропонижающие — парацетамол vs ибупрофен, при какой температуре давать по протоколу AAP; "
        f"2) Что категорически нельзя в этом возрасте и почему; "
        f"3) Доказательная база по популярным средствам (колики, зубы, простуда); "
        f"4) Когда самолечение опасно. "
        f"Конкретные дозировки — только у педиатра. Объясни маме почему это важно."
    ),
    "teeth": lambda m: (
        f"Дай полную научную информацию о зубах ребёнка {age_label(m)} ({m} месяцев). "
        f"1) Хронология прорезывания по нормам ВОЗ — что ожидать сейчас; "
        f"2) Нейрофизиология боли при прорезывании и доказанные методы облегчения; "
        f"3) Что НЕ работает и опасно (гели с лидокаином — позиция AAP); "
        f"4) Уход за молочными зубами — когда начинать чистить, фторид по рекомендации AAP; "
        f"5) Первый визит к стоматологу — когда и зачем по стандартам."
    ),
    "food": lambda m: (
        f"Дай научно обоснованные рекомендации по питанию ребёнка {age_label(m)} ({m} месяцев) "
        f"строго по протоколам ВОЗ и ESPGHAN (Европейское общество детской гастроэнтерологии). "
        f"1) Что вводить сейчас — конкретный список продуктов с обоснованием; "
        f"2) Что категорически нельзя и почему (физиология ЖКТ ребёнка); "
        f"3) Размер порций по возрасту; "
        f"4) Грудное вскармливание vs смесь — позиция ВОЗ; "
        f"5) Аллергены — когда и как вводить по новым исследованиям (метод LEAP); "
        f"6) Признаки пищевой аллергии и непереносимости."
    ),
    "recipes": lambda m: (
        f"Дай 2 рецепта для ребёнка {age_label(m)} ({m} месяцев) по нормам ВОЗ и ESPGHAN. "
        f"Для каждого: ингредиенты, способ приготовления, почему полезен в этом возрасте. "
        f"Только разрешённые продукты для данного возраста."
    ),
    "recipes_more": lambda m: (
        f"Дай ещё 2 ДРУГИХ рецепта для ребёнка {age_label(m)} ({m} месяцев). "
        f"Не повторяй предыдущие. Только разрешённые продукты для этого возраста."
    ),
    "routine": lambda m: (
        f"Составь научно обоснованный режим дня для ребёнка {age_label(m)} ({m} месяцев) "
        f"на основе хронобиологии и исследований сна AAP и ВОЗ. "
        f"1) Нормы сна для этого возраста — дневной и ночной по данным NSF; "
        f"2) Примерное расписание по часам с объяснением физиологии; "
        f"3) Окна бодрствования — сколько времени ребёнок может не спать без переутомления; "
        f"4) Признаки переутомления и недосыпа; "
        f"5) Как выстроить режим с учётом циркадных ритмов ребёнка."
    ),
    "sleep": lambda m: (
        f"Дай исчерпывающий научный анализ сна ребёнка {age_label(m)} ({m} месяцев) "
        f"на основе исследований AAP, NSF и сомнологии. "
        f"1) Нейрофизиология сна в этом возрасте — почему ребёнок так спит; "
        f"2) Доказанные методы улучшения сна (без метода CIO если возраст до 6 мес); "
        f"3) Безопасная среда сна по стандартам AAP (профилактика СВДС); "
        f"4) Ночные пробуждения — норма или нет для этого возраста; "
        f"5) Методы засыпания с доказательной базой — что реально работает."
    ),
    "family": lambda m: (
        f"Дай научно обоснованные рекомендации по семейным отношениям "
        f"когда ребёнку {age_label(m)} ({m} месяцев). "
        f"Опирайся на исследования Джона Готтмана (стабильность пар), "
        f"Петрановской (роль отца в привязанности) и психологию семейных систем. "
        f"1) Роль отца в развитии ребёнка этого возраста — что говорит наука; "
        f"2) Как сохранить партнёрские отношения с доказательными стратегиями Готтмана; "
        f"3) Ревность старших детей — нейрофизиология и как помочь; "
        f"4) Бабушки и дедушки — границы и сотрудничество без конфликтов."
    ),
}


@app.get("/api/miniapp/content/child")
async def miniapp_content_child(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    topic = (request.query_params.get("topic") or "").strip().lower()
    if topic not in MINIAPP_CHILD_PROMPTS:
        raise HTTPException(status_code=400, detail="invalid_topic")

    months = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
        if row and row["mode"] and row["mode"] != "pregnant":
            months = _miniapp_child_months(row["date_value"] or "")
    except Exception:
        logging.exception("miniapp_content_child: profile lookup error")
    if months is None:
        raise HTTPException(status_code=400, detail="profile_required")

    log_analytics_event_tg(user_id, "request_started", "child_" + topic, "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(MINIAPP_TANTRUMS_SYSTEM, MINIAPP_CHILD_PROMPTS[topic](months))
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "child_" + topic, "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "child_" + topic, "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: СОН ==========
# Пишет/читает ту же таблицу sleep_log в mama.db, что и tracker_sleep/sleep_start/sleep_end
# из mama_bot.py (Telegram) — те же значения action ("уснул"/"проснулся"). sleep/analyze
# использует тот же EXPERT_BASE и тот же user prompt, что и sleep_analyze() из mama_bot.py,
# через тот же OpenAI client (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt).
MINIAPP_SLEEP_ACTIONS = {"start": "уснул", "end": "проснулся"}


@app.post("/api/miniapp/sleep/log")
async def miniapp_sleep_log(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = str((body or {}).get("action") or "").strip()
    if action not in MINIAPP_SLEEP_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid_action")
    sleep_action = MINIAPP_SLEEP_ACTIONS[action]
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "INSERT INTO sleep_log (user_id, action, created_at) VALUES (?, ?, ?)",
                (user_id, sleep_action, created_at),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_sleep_log db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "sleep_log", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "action": sleep_action, "created_at": created_at}


@app.get("/api/miniapp/sleep/analyze")
async def miniapp_sleep_analyze(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    entries = []
    months = 0
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            if row and row["mode"] and row["mode"] != "pregnant":
                m = _miniapp_child_months(row["date_value"] or "")
                if m is not None:
                    months = m
            for r in conn.execute(
                "SELECT action, created_at FROM sleep_log WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                (user_id,),
            ):
                entries.append((r["action"], r["created_at"]))
    except Exception:
        logging.exception("miniapp_sleep_analyze: db error")

    if len(entries) < 4:
        raise HTTPException(status_code=400, detail="not_enough_entries")

    data_str = "\n".join(
        f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {action}"
        for action, dt in entries
    )
    log_analytics_event_tg(user_id, "request_started", "sleep_analyze", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот дневник сна:\n{data_str}\n\n"
        f"Проанализируй паттерн сна по нормам AAP и NSF для этого возраста: "
        f"сколько часов спит суммарно, правильные ли интервалы бодрствования, "
        f"есть ли проблемы и как их решить. Конкретные рекомендации.",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "sleep_analyze", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "sleep_analyze", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПИТАНИЕ ==========
# Пишет/читает ту же таблицу feeding в mama.db, что и tracker_feeding/feed_left/feed_right/
# feed_bottle/feed_duration из mama_bot.py (Telegram) — те же значения side ("Левая грудь"/
# "Правая грудь"/"Смесь/бутылочка"). feeding/analyze использует тот же EXPERT_BASE и тот же
# user prompt, что и feed_stats() из mama_bot.py, через тот же OpenAI client (gpt-4o,
# max_tokens=2000 через _miniapp_ask_gpt).
MINIAPP_FEEDING_SIDES = {"left": "Левая грудь", "right": "Правая грудь", "bottle": "Смесь/бутылочка"}
MINIAPP_FEEDING_MAX_DURATION = 600


@app.post("/api/miniapp/feeding/log")
async def miniapp_feeding_log(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    side_key = str((body or {}).get("side") or "").strip()
    if side_key not in MINIAPP_FEEDING_SIDES:
        raise HTTPException(status_code=400, detail="invalid_side")
    side = MINIAPP_FEEDING_SIDES[side_key]
    try:
        duration = int((body or {}).get("duration"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_duration")
    if duration <= 0 or duration > MINIAPP_FEEDING_MAX_DURATION:
        raise HTTPException(status_code=400, detail="invalid_duration")
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "INSERT INTO feeding (user_id, side, duration, created_at) VALUES (?, ?, ?, ?)",
                (user_id, side, duration, created_at),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_feeding_log db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "feeding_log", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "side": side, "duration": duration, "created_at": created_at}


@app.get("/api/miniapp/feeding/analyze")
async def miniapp_feeding_analyze(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    entries = []
    months = 0
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            if row and row["mode"] and row["mode"] != "pregnant":
                m = _miniapp_child_months(row["date_value"] or "")
                if m is not None:
                    months = m
            for r in conn.execute(
                "SELECT side, duration, created_at FROM feeding WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                (user_id,),
            ):
                entries.append((r["side"], r["duration"], r["created_at"]))
    except Exception:
        logging.exception("miniapp_feeding_analyze: db error")

    if not entries:
        raise HTTPException(status_code=400, detail="not_enough_entries")

    data_str = "\n".join(
        f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {side}, {dur} мин"
        for side, dur, dt in entries
    )
    log_analytics_event_tg(user_id, "request_started", "feeding_analyze", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот журнал кормлений:\n{data_str}\n\n"
        f"Проанализируй: достаточно ли кормлений по нормам ВОЗ для этого возраста, "
        f"правильные ли интервалы, достаточная ли продолжительность. "
        f"Дай практические рекомендации.",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "feeding_analyze", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "feeding_analyze", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПРИКОРМ 6+ ==========
# Справочный навигатор по прикорму (WHO complementary feeding 6-23 months). Каталог продуктов и
# категорий статический (ниже) — в БД пишутся только личные отметки мамы, в отдельной новой
# таблице complementary_food_log (аддитивно, тем же platform-routed _miniapp_db(user), что и
# остальной Mini App). Никаких AI-вызовов и индивидуальных лечебных назначений — только
# справочная информация и safety-тексты.
MINIAPP_CF_AGE_TIERS = ["6-7", "8-9", "10-12", "12+"]

MINIAPP_CF_CATEGORIES = [
    {"key": "vegetables", "title": "Овощи", "example": "брокколи + картофель + рыба"},
    {"key": "fruits", "title": "Фрукты и ягоды", "example": "овсяная каша + груша"},
    {"key": "grains", "title": "Каши и крупы", "example": "гречка + индейка + кабачок"},
    {"key": "protein_iron", "title": "Источники железа и белка", "example": "чечевица + овощи"},
    {"key": "dairy", "title": "Кисломолочные продукты", "example": "натуральный йогурт + мягкий фрукт"},
    {"key": "fats", "title": "Полезные жиры", "example": "авокадо + овощное пюре"},
]

MINIAPP_CF_FOODS = [
    {"key": "kabachok", "title": "Кабачок", "category": "vegetables", "min_tier": "6-7"},
    {"key": "brokkoli", "title": "Брокколи", "category": "vegetables", "min_tier": "6-7"},
    {"key": "cvetnaya_kapusta", "title": "Цветная капуста", "category": "vegetables", "min_tier": "6-7"},
    {"key": "morkov", "title": "Морковь", "category": "vegetables", "min_tier": "6-7"},
    {"key": "tykva", "title": "Тыква", "category": "vegetables", "min_tier": "6-7"},
    {"key": "kartofel", "title": "Картофель", "category": "vegetables", "min_tier": "6-7"},
    {"key": "goroshek", "title": "Зелёный горошек", "category": "vegetables", "min_tier": "8-9"},
    {"key": "yabloko", "title": "Яблоко", "category": "fruits", "min_tier": "6-7"},
    {"key": "grusha", "title": "Груша", "category": "fruits", "min_tier": "6-7"},
    {"key": "banan", "title": "Банан", "category": "fruits", "min_tier": "6-7"},
    {"key": "persik", "title": "Персик", "category": "fruits", "min_tier": "6-7"},
    {"key": "sliva", "title": "Слива", "category": "fruits", "min_tier": "6-7"},
    {"key": "yagody", "title": "Ягоды (безопасно размятые, по возрасту)", "category": "fruits", "min_tier": "8-9"},
    {"key": "grechka", "title": "Гречневая каша", "category": "grains", "min_tier": "6-7"},
    {"key": "ovsyanka", "title": "Овсяная каша", "category": "grains", "min_tier": "6-7"},
    {"key": "kukuruznaya", "title": "Кукурузная каша", "category": "grains", "min_tier": "6-7"},
    {"key": "pshenka", "title": "Пшённая каша", "category": "grains", "min_tier": "8-9"},
    {"key": "obogaschennaya_kasha", "title": "Другая обогащённая цельнозерновая каша (например, пшеничная)", "category": "grains", "min_tier": "10-12", "allergen": "wheat"},
    {"key": "govyadina", "title": "Говядина", "category": "protein_iron", "min_tier": "6-7"},
    {"key": "indeyka", "title": "Индейка", "category": "protein_iron", "min_tier": "6-7"},
    {"key": "kuritsa", "title": "Курица", "category": "protein_iron", "min_tier": "6-7"},
    {"key": "ryba", "title": "Рыба (нежирная)", "category": "protein_iron", "min_tier": "8-9", "allergen": "fish"},
    {"key": "yaytso", "title": "Яйцо", "category": "protein_iron", "min_tier": "6-7", "allergen": "egg"},
    {"key": "chechevitsa", "title": "Чечевица", "category": "protein_iron", "min_tier": "8-9"},
    {"key": "fasol", "title": "Фасоль/бобовые (мягкая консистенция)", "category": "protein_iron", "min_tier": "8-9"},
    {"key": "yogurt", "title": "Натуральный йогурт без добавленного сахара", "category": "dairy", "min_tier": "8-9", "allergen": "dairy"},
    {"key": "syr", "title": "Мягкий творог/сыр в безопасной форме", "category": "dairy", "min_tier": "8-9", "allergen": "dairy"},
    {"key": "maslo", "title": "Растительное масло (немного, в блюда)", "category": "fats", "min_tier": "6-7"},
    {"key": "avokado", "title": "Авокадо", "category": "fats", "min_tier": "6-7"},
    {"key": "orehovaya_pasta", "title": "Ореховая паста (тонким слоем, не цельные орехи)", "category": "fats", "min_tier": "8-9", "allergen": "nuts"},
]
MINIAPP_CF_FOOD_BY_KEY = {f["key"]: f for f in MINIAPP_CF_FOODS}

MINIAPP_CF_ALLERGEN_NOTE = (
    "Потенциально аллергенные продукты вводят в рацион наряду с другими продуктами, учитывая "
    "готовность ребёнка и индивидуальные особенности. Если у ребёнка тяжёлая экзема, уже "
    "известная пищевая аллергия или была выраженная реакция на еду — обсудите введение этого "
    "продукта с педиатром или аллергологом."
)

MINIAPP_CF_REACTION_SAFETY_NOTE = (
    "При выраженной или быстро нарастающей реакции, затруднении дыхания, отёке или ухудшении "
    "состояния малыша — это повод для срочной медицинской помощи, а не для ожидания."
)

MINIAPP_CF_DISCLAIMER = "Информация носит справочный характер и не заменяет рекомендации педиатра."

MINIAPP_CF_STATUSES = {"not_tried", "tried", "liked", "disliked", "reaction"}
MINIAPP_CF_REACTION_TEXT_MAX_LEN = 300

_miniapp_cf_schema_ready_tg = False
_miniapp_cf_schema_ready_max = False


def _miniapp_cf_ensure_schema(conn, platform):
    """Создаёт complementary_food_log аддитивно (CREATE TABLE IF NOT EXISTS), не трогая ничего
    остального в mama.db/mama_max.db. Флаг на процесс — чтобы не выполнять DDL на каждый запрос."""
    global _miniapp_cf_schema_ready_tg, _miniapp_cf_schema_ready_max
    if platform == "max":
        if _miniapp_cf_schema_ready_max:
            return
    else:
        if _miniapp_cf_schema_ready_tg:
            return
    conn.execute("""CREATE TABLE IF NOT EXISTS complementary_food_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT,
        user_id INTEGER,
        food_key TEXT,
        status TEXT,
        first_tried_at TEXT,
        reaction_text TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(platform, user_id, food_key)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cf_log_user ON complementary_food_log(platform, user_id)")
    conn.commit()
    if platform == "max":
        _miniapp_cf_schema_ready_max = True
    else:
        _miniapp_cf_schema_ready_tg = True


def _miniapp_cf_age_tier(months):
    """Возраст — только подсказка для вкладки по умолчанию; пользователь может открыть любую."""
    if months is None:
        return "6-7"
    if months < 8:
        return "6-7"
    if months < 10:
        return "8-9"
    if months <= 12:
        return "10-12"
    return "12+"


def _miniapp_cf_catalog_payload(default_tier):
    categories = []
    for cat in MINIAPP_CF_CATEGORIES:
        foods = [
            {"key": f["key"], "title": f["title"], "min_tier": f["min_tier"], "allergen": f.get("allergen")}
            for f in MINIAPP_CF_FOODS
            if f["category"] == cat["key"]
        ]
        categories.append({"key": cat["key"], "title": cat["title"], "example": cat["example"], "foods": foods})
    return {
        "ok": True,
        "age_tiers": MINIAPP_CF_AGE_TIERS,
        "default_age_tier": default_tier,
        "categories": categories,
        "allergen_note": MINIAPP_CF_ALLERGEN_NOTE,
        "disclaimer": MINIAPP_CF_DISCLAIMER,
        "total_foods": len(MINIAPP_CF_FOODS),
    }


@app.get("/api/miniapp/complementary-foods")
async def miniapp_complementary_foods(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    default_tier = "6-7"
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, platform, user_id)
            if row and row["mode"] and row["mode"] != "pregnant":
                months = _miniapp_child_months(row["date_value"] or "")
                default_tier = _miniapp_cf_age_tier(months)
    except Exception:
        logging.exception("miniapp_complementary_foods db error")
    return _miniapp_cf_catalog_payload(default_tier)


@app.get("/api/miniapp/complementary-foods/my")
async def miniapp_complementary_foods_my(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    items = []
    try:
        with _miniapp_db(user) as conn:
            _miniapp_cf_ensure_schema(conn, platform)
            for r in conn.execute(
                "SELECT food_key, status, first_tried_at, reaction_text, updated_at FROM complementary_food_log "
                "WHERE platform=? AND user_id=? ORDER BY updated_at DESC",
                (platform, user_id),
            ):
                food = MINIAPP_CF_FOOD_BY_KEY.get(r["food_key"])
                if not food:
                    continue
                items.append({
                    "food_key": r["food_key"],
                    "title": food["title"],
                    "category": food["category"],
                    "status": r["status"] or "not_tried",
                    "first_tried_at": r["first_tried_at"] or "",
                    "reaction_text": r["reaction_text"] or "",
                    "updated_at": r["updated_at"] or "",
                })
    except Exception:
        logging.exception("miniapp_complementary_foods_my db error")
        raise HTTPException(status_code=500, detail="db_error")
    tried_count = sum(1 for it in items if it["status"] != "not_tried")
    liked_count = sum(1 for it in items if it["status"] == "liked")
    return {
        "ok": True,
        "items": items,
        "tried_count": tried_count,
        "liked_count": liked_count,
        "total_foods": len(MINIAPP_CF_FOODS),
    }


@app.post("/api/miniapp/complementary-foods/mark")
async def miniapp_complementary_foods_mark(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    platform = user.get("platform", "telegram")
    try:
        body = await request.json()
    except Exception:
        body = {}
    food_key = str((body or {}).get("food_key") or "").strip()
    status = str((body or {}).get("status") or "").strip()
    if food_key not in MINIAPP_CF_FOOD_BY_KEY:
        raise HTTPException(status_code=400, detail="invalid_food_key")
    if status not in MINIAPP_CF_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_status")
    reaction_text = str((body or {}).get("reaction_text") or "").strip()[:MINIAPP_CF_REACTION_TEXT_MAX_LEN]
    if status != "reaction":
        reaction_text = ""
    now = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            _miniapp_cf_ensure_schema(conn, platform)
            existing = conn.execute(
                "SELECT first_tried_at FROM complementary_food_log WHERE platform=? AND user_id=? AND food_key=?",
                (platform, user_id, food_key),
            ).fetchone()
            first_tried_at = (existing["first_tried_at"] if existing else None) or ""
            if status != "not_tried" and not first_tried_at:
                first_tried_at = now
            conn.execute(
                "INSERT INTO complementary_food_log "
                "(platform, user_id, food_key, status, first_tried_at, reaction_text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(platform, user_id, food_key) DO UPDATE SET "
                "status=excluded.status, first_tried_at=excluded.first_tried_at, "
                "reaction_text=excluded.reaction_text, updated_at=excluded.updated_at",
                (platform, user_id, food_key, status, first_tried_at or None, reaction_text or None, now, now),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_complementary_foods_mark db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "complementary_mark", "miniapp", platform)
    resp = {
        "ok": True,
        "food_key": food_key,
        "status": status,
        "first_tried_at": first_tried_at,
        "reaction_text": reaction_text,
        "updated_at": now,
    }
    if status == "reaction":
        resp["safety_note"] = MINIAPP_CF_REACTION_SAFETY_NOTE
    return resp


# ========== MINI APP: САМОЧУВСТВИЕ ==========
# Пишет/читает ту же таблицу symptoms в mama.db, что и tracker_symptoms/symptom_add/
# save_symptom_entry из mama_bot.py (Telegram) — та же структура записи (user_id, symptom,
# created_at). symptoms/analyze использует тот же EXPERT_BASE и тот же user prompt, что и
# symptom_analyze() из mama_bot.py, через тот же OpenAI client (gpt-4o, max_tokens=2000
# через _miniapp_ask_gpt).
MINIAPP_SYMPTOM_MAX_LEN = 500


@app.post("/api/miniapp/symptoms/log")
async def miniapp_symptoms_log(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    symptom = str((body or {}).get("symptom") or "").strip()
    if not symptom:
        raise HTTPException(status_code=400, detail="symptom_required")
    if len(symptom) > MINIAPP_SYMPTOM_MAX_LEN:
        raise HTTPException(status_code=400, detail="symptom_too_long")
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "INSERT INTO symptoms (user_id, symptom, created_at) VALUES (?, ?, ?)",
                (user_id, symptom, created_at),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_symptoms_log db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "symptoms_log", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "symptom": symptom, "created_at": created_at}


@app.get("/api/miniapp/symptoms/analyze")
async def miniapp_symptoms_analyze(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    entries = []
    months = 0
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            if row and row["mode"] and row["mode"] != "pregnant":
                m = _miniapp_child_months(row["date_value"] or "")
                if m is not None:
                    months = m
            for r in conn.execute(
                "SELECT symptom, created_at FROM symptoms WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
                (user_id,),
            ):
                entries.append((r["symptom"], r["created_at"]))
    except Exception:
        logging.exception("miniapp_symptoms_analyze: db error")

    if not entries:
        raise HTTPException(status_code=400, detail="not_enough_entries")

    data_str = "\n".join(
        f"{datetime.fromisoformat(dt).strftime('%d.%m %H:%M')}: {s}"
        for s, dt in entries
    )
    log_analytics_event_tg(user_id, "request_started", "symptoms_analyze", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот симптомы за последние дни:\n{data_str}\n\n"
        f"Проанализируй картину: что это может быть, какова динамика — лучше или хуже, "
        f"стоит ли идти к врачу прямо сейчас или можно наблюдать дома. "
        f"Красные флаги — если есть тревожные симптомы скажи прямо.",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "symptoms_analyze", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "symptoms_analyze", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ДНЕВНИК МАЛЫША ==========
# Пишет/читает ту же таблицу diary в mama.db, что и mama_diary/diary_add/save_diary_entry
# из mama_bot.py (Telegram) — та же структура записи (user_id, entry, created_at).
MINIAPP_DIARY_MAX_LEN = 2000
MINIAPP_DIARY_LIST_LIMIT = 20


@app.get("/api/miniapp/diary/list")
async def miniapp_diary_list(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    items = []
    try:
        with _miniapp_db(user) as conn:
            for r in conn.execute(
                "SELECT entry, created_at FROM diary WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, MINIAPP_DIARY_LIST_LIMIT),
            ):
                items.append({"text": r["entry"] or "", "created_at": r["created_at"] or ""})
    except Exception:
        logging.exception("miniapp_diary_list db error")
        raise HTTPException(status_code=500, detail="db_error")
    return {"ok": True, "items": items}


@app.post("/api/miniapp/diary/add")
async def miniapp_diary_add(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > MINIAPP_DIARY_MAX_LEN:
        raise HTTPException(status_code=400, detail="text_too_long")
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "INSERT INTO diary (user_id, entry, created_at) VALUES (?, ?, ?)",
                (user_id, text, created_at),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_diary_add db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "diary_add", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "text": text, "created_at": created_at}


# ========== MINI APP: РОСТ И ВЕС ==========
# Пишет/читает ту же таблицу growth в mama.db, что и tracker_growth/growth_add/growth_height/
# growth_weight из mama_bot.py (Telegram) — та же структура записи (user_id, height, weight,
# created_at). growth/analyze использует тот же EXPERT_BASE и тот же user prompt, что и
# growth_analyze() из mama_bot.py, через тот же OpenAI client (gpt-4o, max_tokens=2000 через
# _miniapp_ask_gpt).
MINIAPP_GROWTH_MIN_HEIGHT = 30.0
MINIAPP_GROWTH_MAX_HEIGHT = 200.0
MINIAPP_GROWTH_MIN_WEIGHT = 0.5
MINIAPP_GROWTH_MAX_WEIGHT = 100.0


@app.post("/api/miniapp/growth/log")
async def miniapp_growth_log(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        height = float((body or {}).get("height"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_height")
    if not (MINIAPP_GROWTH_MIN_HEIGHT <= height <= MINIAPP_GROWTH_MAX_HEIGHT):
        raise HTTPException(status_code=400, detail="invalid_height")
    try:
        weight = float((body or {}).get("weight"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_weight")
    if not (MINIAPP_GROWTH_MIN_WEIGHT <= weight <= MINIAPP_GROWTH_MAX_WEIGHT):
        raise HTTPException(status_code=400, detail="invalid_weight")
    created_at = datetime.now().isoformat()
    try:
        with _miniapp_db(user) as conn:
            conn.execute(
                "INSERT INTO growth (user_id, height, weight, created_at) VALUES (?, ?, ?, ?)",
                (user_id, height, weight, created_at),
            )
            conn.commit()
    except Exception:
        logging.exception("miniapp_growth_log db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "growth_log", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "height": height, "weight": weight, "created_at": created_at}


@app.get("/api/miniapp/growth/list")
async def miniapp_growth_list(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    items = []
    try:
        with _miniapp_db(user) as conn:
            for r in conn.execute(
                "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                (user_id,),
            ):
                items.append({"height": r["height"], "weight": r["weight"], "created_at": r["created_at"]})
    except Exception:
        logging.exception("miniapp_growth_list db error")
    return {"ok": True, "items": items}


@app.get("/api/miniapp/growth/analyze")
async def miniapp_growth_analyze(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    entries = []
    months = 0
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
            if row and row["mode"] and row["mode"] != "pregnant":
                m = _miniapp_child_months(row["date_value"] or "")
                if m is not None:
                    months = m
            for r in conn.execute(
                "SELECT height, weight, created_at FROM growth WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                (user_id,),
            ):
                entries.append((r["height"], r["weight"], r["created_at"]))
    except Exception:
        logging.exception("miniapp_growth_analyze: db error")

    if not entries:
        raise HTTPException(status_code=400, detail="not_enough_entries")

    data_str = "\n".join(
        f"{datetime.fromisoformat(dt).strftime('%d.%m.%Y')}: рост {h} см, вес {w} кг"
        for h, w, dt in entries
    )
    log_analytics_event_tg(user_id, "request_started", "growth_analyze", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        EXPERT_BASE,
        f"Ребёнку {age_label(months)} ({months} месяцев). Вот динамика роста и веса:\n{data_str}\n\n"
        f"Проанализируй динамику по нормам ВОЗ — прибавки в норме или нет, тренд хороший или нет, "
        f"на что обратить внимание педиатру.",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "growth_analyze", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "growth_analyze", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ПРИВИВОЧНЫЙ КАЛЕНДАРЬ ==========
# Тот же стандартный календарь РФ (список и месяцы) и та же логика, что в
# tracker_vaccines/vaccines_create/vaccines_done/vac_done_{id}/vaccines_info из mama_bot.py
# (Telegram) — тексты и prompt скопированы дословно. Читает/пишет исключительно mama.db,
# существующую таблицу vaccinations, без миграций. Планировщик напоминаний (check_vaccine_reminders)
# не затрагивается.
MINIAPP_VACCINE_SCHEDULE = [
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
MINIAPP_VACCINE_NAME_MAX_LEN = 200


def _miniapp_add_months(dt, count):
    month = dt.month - 1 + count
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


@app.get("/api/miniapp/vaccines/list")
async def miniapp_vaccines_list(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    items = []
    try:
        with _miniapp_db(user) as conn:
            for r in conn.execute(
                "SELECT id, vaccine, scheduled_date, done FROM vaccinations WHERE user_id=? ORDER BY scheduled_date",
                (user_id,),
            ):
                items.append({
                    "id": r["id"],
                    "vaccine": r["vaccine"] or "",
                    "scheduled_date": r["scheduled_date"] or "",
                    "done": bool(r["done"]),
                    "status": "done" if r["done"] else "planned",
                })
    except Exception:
        logging.exception("miniapp_vaccines_list db error")
    return {"ok": True, "items": items}


@app.post("/api/miniapp/vaccines/create-schedule")
async def miniapp_vaccines_create_schedule(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    row = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
    except Exception:
        logging.exception("miniapp_vaccines_create_schedule: profile lookup error")
    if not row or row["mode"] != "mama" or not (row["date_value"] or "").strip():
        raise HTTPException(status_code=400, detail="profile_required")
    try:
        birth = datetime.strptime(row["date_value"], "%d.%m.%Y")
    except ValueError:
        raise HTTPException(status_code=400, detail="profile_required")

    added = 0
    try:
        with _miniapp_db(user) as conn:
            conn.execute("DELETE FROM vaccinations WHERE user_id=?", (user_id,))
            created_at = datetime.now().isoformat()
            for month_age, vaccine in MINIAPP_VACCINE_SCHEDULE:
                vac_date = _miniapp_add_months(birth, month_age).strftime("%d.%m.%Y")
                conn.execute(
                    "INSERT INTO vaccinations (user_id, vaccine, scheduled_date, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, vaccine, vac_date, created_at),
                )
                added += 1
            conn.commit()
    except Exception:
        logging.exception("miniapp_vaccines_create_schedule db error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "vaccines_create_schedule", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "added": added}


@app.post("/api/miniapp/vaccines/{vac_id}/done")
async def miniapp_vaccines_done(vac_id: int, request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    row = None
    try:
        with _miniapp_db(user) as conn:
            row = conn.execute("SELECT id, user_id FROM vaccinations WHERE id=?", (vac_id,)).fetchone()
    except Exception:
        logging.exception("miniapp_vaccines_done: lookup error")
        raise HTTPException(status_code=500, detail="internal_error")
    if not row or int(row["user_id"]) != int(user_id):
        raise HTTPException(status_code=404, detail="not_found")
    try:
        with _miniapp_db(user) as conn:
            conn.execute("UPDATE vaccinations SET done=1 WHERE id=? AND user_id=?", (vac_id, user_id))
            conn.commit()
    except Exception:
        logging.exception("miniapp_vaccines_done: update error")
        raise HTTPException(status_code=500, detail="db_error")
    log_analytics_event_tg(user_id, "request_completed", "vaccines_done", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "id": vac_id, "done": True}


@app.get("/api/miniapp/vaccines/info")
async def miniapp_vaccines_info(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    vaccine_name = (request.query_params.get("name") or "").strip()
    if not vaccine_name:
        raise HTTPException(status_code=400, detail="name_required")
    if len(vaccine_name) > MINIAPP_VACCINE_NAME_MAX_LEN:
        raise HTTPException(status_code=400, detail="name_too_long")

    log_analytics_event_tg(user_id, "request_started", "vaccines_info", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
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
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "vaccines_info", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "vaccines_info", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


# ========== MINI APP: ЭКСТРЕННАЯ ПОМОЩЬ ==========
# Перенос существующего Telegram-сценария emergency/EMERGENCY_GUIDES/em_other/
# emergency_other_answer из mama_bot.py 1:1: те же темы и тот же текст статичных guides
# (без AI, отдаются напрямую), тот же system/user prompt и тот же OpenAI client
# (gpt-4o, max_tokens=2000 через _miniapp_ask_gpt) для "Другой ситуации". situation
# не сохраняется и не логируется — та же приватность, что и в /ask-question.
MINIAPP_EMERGENCY_SITUATION_MAX_LEN = 2000

MINIAPP_EMERGENCY_INTRO = (
    "Выбери главное проявление. Раздел помогает оценить срочность, но не заменяет врача. "
    "Если ребёнок не дышит, синеет, не реагирует или у него судороги — звони 112 сразу."
)

MINIAPP_EMERGENCY_GUIDES = {
    "em_fever": ("🌡 Температура", "Звони 112 при судорогах, нарушении дыхания, синюшности, потере сознания или не бледнеющей сыпи. Для ребёнка младше 3 месяцев температура 38°C и выше требует срочной медицинской оценки. Не укутывай и не растирай спиртом или уксусом. Предлагай питьё или грудь чаще. Лекарство давай только подходящее по возрасту и весу по рекомендации врача."),
    "em_breath": ("😮‍💨 Проблемы с дыханием", "Звони 112 немедленно, если синеют губы, есть паузы дыхания, выраженное втяжение межрёберий, спутанность или потеря сознания. Держи ребёнка вертикально, освободи тесную одежду, не давай еду и не пытайся осматривать горло предметами."),
    "em_vomit": ("🤮 Рвота или понос", "Звони 112 при крови, зелёной рвоте, судорогах, резкой боли или нарушении сознания. Срочно к врачу при отсутствии мочи, сухих губах, отсутствии слёз и запавших глазах. Отпаивай часто маленькими порциями; не давай противорвотные и противодиарейные средства без врача."),
    "em_lethargic": ("😴 Сильная вялость", "Если ребёнка трудно разбудить, он не удерживает взгляд, необычно обмяк или вялость сопровождается нарушением дыхания — звони 112. Проверь дыхание, цвет кожи и температуру. Не заставляй есть и не оставляй одного."),
    "em_rash": ("🔴 Внезапная сыпь", "Надави прозрачным стаканом на сыпь. Если пятна не бледнеют, особенно вместе с температурой или вялостью, — звони 112. Также срочно вызывай помощь при отёке губ или языка, осиплости и затруднении дыхания."),
    "em_crying": ("😭 Безутешный плач", "Звони 112 при нарушении дыхания, посинении, судорогах, травме, резкой вялости или необычном пронзительном крике с рвотой. Проверь температуру, подгузник, голод, одежду и пальцы на пережимающий волос. Никогда не встряхивай ребёнка."),
}

MINIAPP_EMERGENCY_GUIDE_FOOTER = "Если сомневаешься — лучше позвонить 112 или в неотложную помощь."

MINIAPP_EMERGENCY_OTHER_SYSTEM = (
    "Ты медицинский навигатор. Сначала укажи, есть ли повод звонить 112. "
    "Затем безопасные действия до врача и уточняющие вопросы. "
    "Не ставь диагноз, не назначай препараты и дозировки."
)


@app.get("/api/miniapp/emergency/guides")
async def miniapp_emergency_guides(request: Request):
    _miniapp_require_user(request)
    return {
        "ok": True,
        "intro": MINIAPP_EMERGENCY_INTRO,
        "footer": MINIAPP_EMERGENCY_GUIDE_FOOTER,
        "guides": [
            {"key": key, "title": title, "text": text}
            for key, (title, text) in MINIAPP_EMERGENCY_GUIDES.items()
        ],
    }


@app.post("/api/miniapp/emergency/ask")
async def miniapp_emergency_ask(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")
    try:
        body = await request.json()
    except Exception:
        body = {}
    situation = str((body or {}).get("situation") or "").strip()
    if not situation:
        raise HTTPException(status_code=400, detail="situation_required")
    if len(situation) > MINIAPP_EMERGENCY_SITUATION_MAX_LEN:
        raise HTTPException(status_code=400, detail="situation_too_long")

    months = None
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user_id)
        if row:
            mode = row["mode"] or ""
            if mode and mode != "pregnant":
                months = _miniapp_child_months(row["date_value"] or "")
    except Exception:
        logging.exception("miniapp_emergency_ask: profile lookup error")

    log_analytics_event_tg(user_id, "request_started", "emergency_other", "miniapp", user.get("platform", "telegram"))
    answer = await _miniapp_ask_gpt(
        MINIAPP_EMERGENCY_OTHER_SYSTEM,
        f"Ребёнку {age_label(months) if months is not None else 'неизвестного возраста'}. Ситуация: {situation}",
    )
    if ai_answer_success(answer):
        log_analytics_event_tg(user_id, "request_completed", "emergency_other", "miniapp", user.get("platform", "telegram"))
    else:
        log_analytics_event_tg(user_id, "request_failed", "emergency_other", "miniapp_ai_answer_invalid", user.get("platform", "telegram"))
    return {"ok": True, "answer": answer}


def log_analytics_event_tg(user_id, event_name, source="", details="", platform="telegram"):
    """Аналитика заявок из Mini App — пишет в свою БД на платформу (mama.db/mama_max.db),
    не логирует situation_text."""
    try:
        with _miniapp_db(platform) as conn:
            conn.execute(
                "INSERT INTO analytics_events(created_at,platform,user_id,event_name,source,details) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(), platform, int(user_id or 0), event_name, source or "", str(details or "")[:1000]),
            )
            conn.commit()
    except Exception:
        logging.error("log_analytics_event_tg error")


# ========== MINI APP: ФОТОАНАЛИЗ ==========
# Перенос существующего Telegram-сценария photo_menu/photo_analysis/photo_uzi/photo_med_preg/
# photo_skin/photo_stool/photo_food/photo_package/handle_photo из mama_bot.py 1:1: та же
# двухступенчатая проверка (сначала filter_prompt — соответствует ли фото выбранному типу, затем
# analysis_prompt — экспертный разбор), те же формулировки wrong_msg и тот же OpenAI client
# (gpt-4o, max_tokens=10 для фильтра и 1000 для анализа, как в handle_photo). Загруженное фото
# никогда не пишется на диск и не логируется (в т.ч. в analytics details) — только временный
# bytes-объект в памяти запроса, который освобождается сразу после ответа.
MINIAPP_PHOTO_MAX_BYTES = 8 * 1024 * 1024  # 8 МБ — с запасом покрывает обычное фото с телефона

MINIAPP_PHOTO_TYPES = {
    "analysis": {
        "filter_prompt": "На этом изображении медицинский документ, бланк анализов или результаты лабораторного исследования? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты опытный акушер-гинеколог и лабораторный диагност. Расшифруй результаты анализов для беременной женщины: "
            "1) Какие показатели в норме; "
            "2) Какие отклонения от нормы для беременных; "
            "3) На что обратить внимание; "
            "4) С какими результатами нужно срочно к врачу. "
            "Напомни что интерпретацию результатов должен делать врач."
        ),
        "wrong_msg": "📸 Я жду фото результатов анализов 🤍",
    },
    "uzi": {
        "filter_prompt": "На этом изображении медицинский документ или заключение УЗИ? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты опытный акушер-гинеколог. Объясни заключение УЗИ беременной понятным языком: "
            "1) Что означают основные показатели (размеры плода, ИАЖ, плацента, кровоток); "
            "2) Что в норме для данного срока; "
            "3) Если есть отклонения — что они означают простыми словами; "
            "4) Нужно ли беспокоиться и когда срочно к врачу. "
            "Используй простые слова, избегай медицинского жаргона."
        ),
        "wrong_msg": "📸 Я жду фото заключения УЗИ 🤍",
    },
    "med_preg": {
        "filter_prompt": "На этом изображении упаковка лекарства или медицинского препарата? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты акушер-гинеколог и клинический фармаколог. Оцени лекарство для беременной: "
            "1) Что это за препарат и для чего; "
            "2) Можно ли при беременности — по категориям FDA/ACOG; "
            "3) В каком триместре разрешён/запрещён; "
            "4) Возможные риски для плода; "
            "5) Обязательно: решение о приёме принимает только врач. "
            "Будь конкретной и честной."
        ),
        "wrong_msg": "📸 Я жду фото упаковки лекарства 🤍",
    },
    "skin": {
        "filter_prompt": "Посмотри на это изображение. На нём кожа человека или ребёнка с возможными высыпаниями, покраснениями или другими кожными проявлениями? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты опытный педиатр. Опиши что видишь на коже ребёнка: "
            "1) Характер высыпаний — цвет, форма, размер, локализация; "
            "2) На какие известные состояния это визуально похоже — потница, атопический дерматит, аллергия, инфекция и т.д.; "
            "3) Что можно сделать дома прямо сейчас; "
            "4) Красные флаги — когда срочно к врачу. "
            "В конце обязательно напомни что это описание а не диагноз."
        ),
        "wrong_msg": "📸 Я жду фото кожи или сыпи малыша 🤍 Отправь фотографию кожного покрова ребёнка.",
    },
    "stool": {
        "filter_prompt": "На этом изображении подгузник или стул ребёнка? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты педиатр. Оцени стул ребёнка по фото: "
            "1) Цвет — что он означает для здоровья малыша; "
            "2) Консистенция — норма или нет; "
            "3) Что это может говорить о пищеварении; "
            "4) Когда нужен врач. "
            "Напомни что точный диагноз ставит только педиатр."
        ),
        "wrong_msg": "📸 Я жду фото стула малыша 🤍 Отправь соответствующее фото.",
    },
    "food": {
        "filter_prompt": "На этом изображении еда или блюдо? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты диетолог-педиатр.{age_context} "
            "Посмотри на это блюдо или продукт и скажи: "
            "1) Что это за еда; "
            "2) Подходит ли это ребёнку по возрасту — да/нет и почему; "
            "3) Что в составе может быть проблематично; "
            "4) Как правильно приготовить если нужна адаптация под возраст."
        ),
        "wrong_msg": "📸 Я жду фото еды или блюда 🤍 Отправь фотографию продукта или блюда.",
    },
    "package": {
        "filter_prompt": "На этом изображении упаковка товара, лекарства или смеси? Ответь только: ДА или НЕТ.",
        "analysis_prompt": (
            "Ты педиатр-фармаколог. Изучи упаковку и скажи: "
            "1) Что это за продукт; "
            "2) Основные компоненты состава — что важно; "
            "3) Для какого возраста подходит; "
            "4) На что обратить особое внимание маме; "
            "5) Есть ли спорные ингредиенты."
        ),
        "wrong_msg": "📸 Я жду фото упаковки смеси или лекарства 🤍 Отправь фотографию упаковки.",
    },
}

MINIAPP_PHOTO_GENERIC_ERROR = "Не удалось проанализировать фото. Попробуй ещё раз."


def _miniapp_photo_age_context(user):
    """Тот же возрастной контекст для type=food, что в photo_food_photo/handle_photo из
    mama_bot.py: добавляется только для профиля 'mama', для беременных и пустого профиля — пусто."""
    try:
        with _miniapp_db(user) as conn:
            row = _miniapp_profile_row(conn, user.get("platform", "telegram"), user.get("id"))
        if row and (row["mode"] or "") not in ("", "pregnant"):
            months = _miniapp_child_months(row["date_value"] or "")
            if months is not None:
                return f" Малышу {age_label(months)} ({months} месяцев)."
    except Exception:
        logging.exception("miniapp_photo_analyze: profile lookup error")
    return ""


@app.post("/api/miniapp/photo/analyze")
async def miniapp_photo_analyze(request: Request):
    user = _miniapp_require_user(request)
    user_id = user.get("id")

    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_form")

    photo_type = str(form.get("type") or "").strip()
    spec = MINIAPP_PHOTO_TYPES.get(photo_type)
    if not spec:
        raise HTTPException(status_code=400, detail="invalid_type")

    image = form.get("image")
    if not isinstance(image, UploadFile):
        raise HTTPException(status_code=400, detail="image_required")

    content_type = (image.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="invalid_mime")

    raw = await image.read()
    await image.close()
    if not raw:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(raw) > MINIAPP_PHOTO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="file_too_large")

    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        picture = Image.open(io.BytesIO(raw))
        picture = ImageOps.exif_transpose(picture)
        if picture.mode != "RGB":
            picture = picture.convert("RGB")
        jpeg_buf = io.BytesIO()
        picture.save(jpeg_buf, format="JPEG", quality=88)
        photo_bytes = jpeg_buf.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_image")
    finally:
        raw = None

    photo_b64 = base64.b64encode(photo_bytes).decode()
    photo_bytes = None

    analysis_prompt = spec["analysis_prompt"]
    if photo_type == "food":
        analysis_prompt = analysis_prompt.format(age_context=_miniapp_photo_age_context(user))

    log_analytics_event_tg(user_id, "request_started", f"photo_{photo_type}", "miniapp", user.get("platform", "telegram"))

    try:
        filter_response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                    {"type": "text", "text": spec["filter_prompt"]},
                ],
            }],
            max_tokens=10,
        )
        filter_answer = (filter_response.choices[0].message.content or "").strip().upper()

        if "НЕТ" in filter_answer or "NO" in filter_answer:
            log_analytics_event_tg(user_id, "request_completed", f"photo_{photo_type}", "miniapp_no_match", user.get("platform", "telegram"))
            return {"ok": True, "match": False, "message": spec["wrong_msg"]}

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_b64}"}},
                    {"type": "text", "text": analysis_prompt},
                ],
            }],
            max_tokens=1000,
        )
        answer = clean_text(response.choices[0].message.content)
    except Exception as exc:
        logging.error(f"miniapp_photo_analyze: ошибка анализа фото (type={photo_type})")
        await notify_owner_max(f"⚠️ Ошибка AI MiniApp photo/analyze\n\n{type(exc).__name__}: {exc}", key=f"ai_miniapp_photo_{type(exc).__name__}")
        log_analytics_event_tg(user_id, "request_failed", f"photo_{photo_type}", "miniapp_ai_error", user.get("platform", "telegram"))
        return {"ok": False, "match": True, "message": MINIAPP_PHOTO_GENERIC_ERROR}
    finally:
        photo_b64 = None

    log_analytics_event_tg(user_id, "request_completed", f"photo_{photo_type}", "miniapp", user.get("platform", "telegram"))
    return {"ok": True, "match": True, "answer": answer}


async def main():
    if not OWNER_ID:
        logging.warning("MAX_OWNER_ID не задан: уведомления владельцу недоступны")
    config = uvicorn.Config(app, host="0.0.0.0", port=8082, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
