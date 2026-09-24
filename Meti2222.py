# -*- coding: utf-8 -*-

import os
import re
import time
import sqlite3
import json
import hashlib
import subprocess
from datetime import datetime, timedelta

import requests
import asyncio
import copy

from splusthon import SoroushClient, events
from splusthon.sessions import StringSession


# =========================================================
#                  Infinity War Bot
# =========================================================

DB_NAME = "infinity_war.db"
CHANNEL = "Warzone096"
SESSION_FILE = "session.txt"

try:
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        saved_session = f.read().strip()
except FileNotFoundError:
    saved_session = ""

client = SoroushClient(StringSession(saved_session))

# کلاینت دوم، با همون session، ولی کانکشن کاملاً مجزا از کلاینت اصلی.
# خطای RPCError 422: FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER وقتی
# پیش میاد که درخواست فایل (دانلود/آپلود) روی همون کانکشنی بره که برای
# پیام‌های عادی/realtime استفاده میشه. اینجا هر عملیات فایل (دانلود
# مدیای بیانیه و آپلودش توی کانال) رو فقط از طریق این کلاینت دوم انجام
# می‌دیم تا کانکشن اصلی client دست‌نخورده بمونه.
media_client = SoroushClient(StringSession(saved_session))
_media_client_ready = False
_media_client_lock = asyncio.Lock()


async def _ensure_media_client():
    global _media_client_ready
    async with _media_client_lock:
        if not _media_client_ready:
            await media_client.start()
            _media_client_ready = True
    return media_client


ADMIN_CODE = "ADMIN2626"
STARTING_MONEY = 20000

# 🧪 تست موقت: وقتی True باشه، فقط کد کشور واگنر اجازه‌ی ورود داره
# (کد ادمین جداست و تحت تأثیر این فلگ نیست). برای برگردوندن به حالت
# عادی و باز شدن همه‌ی کشورها، این رو False کن.
TEST_MODE_ONLY_WAGNER = False

TOMAN_CONTACT = "@Meettiiiii"


# =========================================================
#                     کشورها
# =========================================================

COUNTRIES = {
    "WQCRGY26": ("واگنر", "🏴‍☠️"),
    "USA7K4P2": ("آمریکا", "🇺🇸"),
    "RUS9M3X8": ("روسیه", "🇷🇺"),
    "CHN5Q8L1": ("چین", "🇨🇳"),
    "GBR4T9N6": ("بریتانیا", "🇬🇧"),
    "FRA8C2V5": ("فرانسه", "🇫🇷"),
    "GER6H3K9": ("آلمان", "🇩🇪"),
    "IRN7P5D2": ("ایران", "🇮🇷"),
    "ISR3X8M4": ("اسرائیل", "🇮🇱"),
    "PRK9L6Q2": ("کره شمالی", "🇰🇵"),
    "IND5V7R3": ("هند", "🇮🇳"),
    "ITA8N4C6": ("ایتالیا", "🇮🇹"),
    "PAK2M9H5": ("پاکستان", "🇵🇰"),
    "TUR6Q3X8": ("ترکیه", "🇹🇷"),
    "CAN4X7M9": ("کانادا", "🇨🇦"),
    "SAU8K5P3": ("عربستان سعودی", "🇸🇦"),
    "BRA7D2L6": ("برزیل", "🇧🇷"),
    "UKR5M8C4": ("اوکراین", "🇺🇦"),
    "IRQ3P9V7": ("عراق", "🇮🇶"),
    "NLD6X2K8": ("هلند", "🇳🇱"),
    "JPN9R4H5": ("ژاپن", "🇯🇵"),
}

# نام انگلیسی کشورها — فقط برای بخش مذاکره (کد مذاکرات و لیست کشورها) استفاده میشه
ENGLISH_NAMES = {
    "USA7K4P2": "United States",
    "RUS9M3X8": "Russia",
    "CHN5Q8L1": "China",
    "GBR4T9N6": "United Kingdom",
    "FRA8C2V5": "France",
    "GER6H3K9": "Germany",
    "IRN7P5D2": "Iran",
    "ISR3X8M4": "Israel",
    "PRK9L6Q2": "North Korea",
    "IND5V7R3": "India",
    "ITA8N4C6": "Italy",
    "PAK2M9H5": "Pakistan",
    "TUR6Q3X8": "Turkey",
    "CAN4X7M9": "Canada",
    "SAU8K5P3": "Saudi Arabia",
    "BRA7D2L6": "Brazil",
    "UKR5M8C4": "Ukraine",
    "IRQ3P9V7": "Iraq",
    "NLD6X2K8": "Netherlands",
    "JPN9R4H5": "Japan",
}

# ترتیب نمایش کشورها توی لیست مذاکره (واگنر توش نیست)
NEGOTIATION_COUNTRY_ORDER = [
    "USA7K4P2", "RUS9M3X8", "CHN5Q8L1", "CAN4X7M9", "GBR4T9N6", "FRA8C2V5",
    "GER6H3K9", "IRN7P5D2", "ISR3X8M4", "PRK9L6Q2", "IND5V7R3", "ITA8N4C6",
    "PAK2M9H5", "TUR6Q3X8", "SAU8K5P3", "BRA7D2L6", "UKR5M8C4", "IRQ3P9V7",
    "NLD6X2K8", "JPN9R4H5",
]


# =========================================================
#                 اتصال اکانتی SoroushClient
# =========================================================

def send_message(chat_id, text):
    """سازگارکننده ارسال پیام برای توابع قدیمی پروژه."""
    try:
        return asyncio.create_task(client.send_message(chat_id, text))
    except Exception as e:
        print("SEND ERROR:", repr(e))
        return None


# =========================================================
#                     DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():

    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            country_id INTEGER DEFAULT NULL,
            state TEXT DEFAULT 'login',
            temp_data TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            flag TEXT,
            tier INTEGER DEFAULT 1,
            leader TEXT DEFAULT '',
            president TEXT DEFAULT '',
            foreign_minister TEXT DEFAULT '',
            commander TEXT DEFAULT '',
            negotiation_team TEXT DEFAULT '',
            money INTEGER DEFAULT 20000,
            approval INTEGER DEFAULT 100,
            security INTEGER DEFAULT 0,
            nuclear INTEGER DEFAULT 0,
            daily_profit INTEGER DEFAULT 0,
            last_profit_date TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT DEFAULT '',
            amount INTEGER DEFAULT 0,
            UNIQUE(country_id, code)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            requested INTEGER DEFAULT 0,
            repayment INTEGER DEFAULT 0,
            days INTEGER DEFAULT 0,
            paid_days INTEGER DEFAULT 0,
            missed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            paid INTEGER DEFAULT 0,
            penalty INTEGER DEFAULT 0,
            due_date TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            price INTEGER DEFAULT 0,
            capacity INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            bought INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            role_text TEXT DEFAULT '',
            amount INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO bot_settings(key,value)
        VALUES ('shop_enabled','1')
    """)

    # جلوگیری از پردازش دوباره یک آپدیت
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_updates (
            update_key TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT ''
        )
    """)

    # جلوگیری از پردازش دوباره یک پیام، حتی اگر API همان پیام را
    # با update_id متفاوت برگرداند.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            message_key TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS toman_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            amount INTEGER DEFAULT 0,
            UNIQUE(country_id, code)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS negotiations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT DEFAULT 'bilateral',
            requester_country_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            code TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS negotiation_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            negotiation_id INTEGER NOT NULL,
            country_id INTEGER NOT NULL,
            role TEXT DEFAULT 'target',
            response TEXT DEFAULT 'pending',
            responded_at TEXT DEFAULT ''
        )
    """)

    # مهاجرت دیتابیس‌های قدیمی
    add_column_if_missing(conn, "users", "temp_data", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "countries", "daily_profit", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "base_daily_profit", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "last_profit_date", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "countries", "nuclear_license", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "approval_bonus", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "loans", "paid", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "loans", "penalty", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "loans", "due_date", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "loans", "paid_amount", "INTEGER DEFAULT 0")

    # کشورها
    for code, data in COUNTRIES.items():

        name, flag = data

        conn.execute("""
            INSERT OR IGNORE INTO countries
            (code, name, flag, money, approval)
            VALUES (?, ?, ?, ?, ?)
        """, (
            code,
            name,
            flag,
            STARTING_MONEY,
            100
        ))

    # تنظیمات پیش‌فرض
    defaults = {
        "bot_enabled": "1",
        "loan_enabled": "1",
        "invention_enabled": "1",
        "role_enabled": "1",
        "negotiation_enabled": "1",
        "game_day": "0",
        "special_starts_applied": "0",
    }

    for key, value in defaults.items():

        conn.execute("""
            INSERT OR IGNORE INTO bot_settings
            (key, value)
            VALUES (?, ?)
        """, (key, value))

    # شروع ویژه چهار کشور فقط یک بار اعمال می‌شود.
    special_done = conn.execute("SELECT value FROM bot_settings WHERE key='special_starts_applied'").fetchone()
    if not special_done or special_done["value"] != "1":
        for code in ("RUS9M3X8", "CHN5Q8L1", "USA7K4P2", "CAN4X7M9"):
            conn.execute("UPDATE countries SET money=30000, daily_profit=5000, base_daily_profit=5000 WHERE code=?", (code,))
        conn.execute("UPDATE bot_settings SET value='1' WHERE key='special_starts_applied'")

    conn.commit()
    conn.close()


# =========================================================
#                    تنظیمات
# =========================================================

def get_setting(key, default="0"):

    conn = db()

    row = conn.execute("""
        SELECT value
        FROM bot_settings
        WHERE key=?
    """, (key,)).fetchone()

    conn.close()

    if not row:
        return default

    return row["value"]


def set_setting(key, value):

    conn = db()

    conn.execute("""
        INSERT INTO bot_settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def is_enabled(key):
    return get_setting(key, "0") == "1"


def claim_update(update):
    """
    هر آپدیت فقط یک بار پردازش شود.
    بعضی نسخه‌های API ممکن است update_id نداشته باشند؛
    در آن حالت از هش محتوای کامل آپدیت استفاده می‌کنیم.
    """

    update_id = update.get("update_id")

    if update_id is not None:
        update_key = "id:" + str(update_id)
    else:
        raw = json.dumps(
            update,
            sort_keys=True,
            ensure_ascii=False,
            default=str
        )
        update_key = "hash:" + hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    conn = db()

    try:
        conn.execute("""
            INSERT INTO processed_updates(update_key, processed_at)
            VALUES (?, ?)
        """, (
            update_key,
            datetime.now().isoformat()
        ))
        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        conn.close()


# =========================================================
#                     ابزارها
# =========================================================


def claim_message(update, chat_id, text):
    """
    لایه دوم جلوگیری از دوباره‌پردازش شدن پیام.
    اگر message_id موجود باشد همان شناسه مبناست؛ در غیر این صورت
    یک کلید کوتاه‌مدت از chat + text ساخته می‌شود.
    """
    message = update.get("message")
    if not isinstance(message, dict):
        message = update.get("result")
    if not isinstance(message, dict):
        message = {}

    # فقط به message_id اعتماد نمی‌کنیم؛ بعضی وقت‌ها API یک پیام
    # یکسان را با شناسه‌های متفاوت برمی‌گرداند. بنابراین یک قفل
    # کوتاه‌مدت بر اساس کاربر + متن هم داریم.
    bucket = int(time.time() / 2)
    raw = f"{chat_id}|{text}|{bucket}"
    message_key = "semantic:" + hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()

    conn = db()
    try:
        conn.execute("""
            INSERT INTO processed_messages(message_key, processed_at)
            VALUES (?, ?)
        """, (message_key, datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def money(value):
    return f"{int(value):,} IC"


def toman(value):
    return f"{int(value):,} تومان"


def normalize_text(text):
    if text is None:
        return ""

    return str(text).strip()


def country_by_code(code):

    code = normalize_text(code).upper()

    # 🧪 حالت تست موقت: فقط کد واگنر اجازه‌ی ورود داره (کد ادمین جدا
    # و از همین مسیر رد نمیشه). برای برگردوندن به حالت عادی، فقط این
    # بلوک رو حذف/کامنت کن یا TEST_MODE_ONLY_WAGNER رو False کن.
    if TEST_MODE_ONLY_WAGNER and code != "WQCRGY26":
        return None

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM countries
        WHERE code=?
    """, (code,)).fetchone()

    conn.close()

    return row


def get_country_by_id(country_id):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM countries
        WHERE id=?
    """, (country_id,)).fetchone()

    conn.close()

    return row


def get_user(user_id):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM users
        WHERE user_id=?
    """, (str(user_id),)).fetchone()

    conn.close()

    return row


def ensure_user(user_id):

    conn = db()

    conn.execute("""
        INSERT OR IGNORE INTO users(user_id)
        VALUES (?)
    """, (str(user_id),))

    conn.commit()
    conn.close()


def set_user_state(user_id, state, temp_data=""):

    conn = db()

    conn.execute("""
        UPDATE users
        SET state=?, temp_data=?
        WHERE user_id=?
    """, (
        state,
        temp_data,
        str(user_id)
    ))

    conn.commit()
    conn.close()


def clear_temp(user_id):

    conn = db()

    conn.execute("""
        UPDATE users
        SET temp_data=''
        WHERE user_id=?
    """, (str(user_id),))

    conn.commit()
    conn.close()


def set_user_country(user_id, country_id):

    conn = db()

    conn.execute("""
        UPDATE users
        SET country_id=?, state='main', temp_data=''
        WHERE user_id=?
    """, (
        country_id,
        str(user_id)
    ))

    conn.commit()
    conn.close()


def logout_user(user_id):

    conn = db()

    conn.execute("""
        UPDATE users
        SET country_id=NULL,
            state='login',
            temp_data=''
        WHERE user_id=?
    """, (str(user_id),))

    conn.commit()
    conn.close()


def change_money(country_id, amount):

    conn = db()

    conn.execute("""
        UPDATE countries
        SET money=money+?
        WHERE id=?
    """, (amount, country_id))

    conn.commit()
    conn.close()


def change_daily_profit(country_id, amount):

    conn = db()
    conn.execute("""
        UPDATE countries
        SET base_daily_profit=base_daily_profit+?
        WHERE id=?
    """, (amount, country_id))
    conn.commit()
    conn.close()

    sync_daily_profit(country_id)


def change_approval(country_id, amount):

    conn = db()

    conn.execute("""
        UPDATE countries
        SET approval=MAX(0, MIN(100, approval+?))
        WHERE id=?
    """, (amount, country_id))

    conn.commit()
    conn.close()


# =========================================================
#                      مذاکره
# =========================================================

def has_international_airport(country_id):
    return get_equipment(country_id, "airport_international") > 0


def negotiation_display_name(country_row):
    """نام انگلیسی برای کد مذاکرات؛ اگه توی لیست نبود (مثلاً واگنر) اسم فارسی برمی‌گرده."""
    return ENGLISH_NAMES.get(country_row["code"], country_row["name"])


def build_negotiation_code(kind, names):
    """names: لیست اسم‌های انگلیسی به ترتیب (درخواست‌کننده اول)."""
    if len(names) < 2:
        return ""
    if kind == "bilateral":
        return f"Infinity war {names[0]}🤜🤛{names[1]}"
    seps = ["🤛🤜", "🤜🤛"]
    result = names[0]
    for idx, name in enumerate(names[1:]):
        result += f"{seps[idx % 2]} {name}"
    return result


def create_negotiation(kind, requester_id, target_ids):
    conn = db()
    now = datetime.utcnow().isoformat()
    cur = conn.execute("""
        INSERT INTO negotiations (kind, requester_country_id, status, created_at)
        VALUES (?, ?, 'pending', ?)
    """, (kind, requester_id, now))
    neg_id = cur.lastrowid
    conn.execute("""
        INSERT INTO negotiation_participants (negotiation_id, country_id, role, response, responded_at)
        VALUES (?, ?, 'requester', 'accepted', ?)
    """, (neg_id, requester_id, now))
    for tid in target_ids:
        conn.execute("""
            INSERT INTO negotiation_participants (negotiation_id, country_id, role, response, responded_at)
            VALUES (?, ?, 'target', 'pending', '')
        """, (neg_id, tid))
    conn.commit()
    conn.close()
    return neg_id


def get_negotiation(neg_id):
    conn = db()
    row = conn.execute("SELECT * FROM negotiations WHERE id=?", (neg_id,)).fetchone()
    conn.close()
    return row


def negotiation_participants(neg_id, only_active=False):
    conn = db()
    q = "SELECT * FROM negotiation_participants WHERE negotiation_id=?"
    if only_active:
        q += " AND response!='rejected'"
    q += " ORDER BY id"
    rows = conn.execute(q, (neg_id,)).fetchall()
    conn.close()
    return rows


def negotiation_respond(neg_id, country_id, accept):
    """کشور مقصد به یه مذاکره جواب میده. خروجی: ('accepted', code) / ('rejected', None) / ('pending', None)"""
    now = datetime.utcnow().isoformat()

    conn = db()
    conn.execute("""
        UPDATE negotiation_participants
        SET response=?, responded_at=?
        WHERE negotiation_id=? AND country_id=?
    """, ("accepted" if accept else "rejected", now, neg_id, country_id))
    conn.commit()
    conn.close()

    targets = [p for p in negotiation_participants(neg_id) if p["role"] == "target"]
    active_targets = [p for p in targets if p["response"] != "rejected"]

    all_accepted = len(active_targets) > 0 and all(p["response"] == "accepted" for p in active_targets)
    all_rejected = len(active_targets) == 0

    if not all_accepted and not all_rejected:
        return "pending", None

    neg = get_negotiation(neg_id)

    if all_rejected:
        conn = db()
        conn.execute("UPDATE negotiations SET status='rejected' WHERE id=?", (neg_id,))
        conn.commit()
        conn.close()
        return "rejected", None

    # all_accepted
    active_all = [p for p in negotiation_participants(neg_id) if p["response"] != "rejected"]
    names = [
        negotiation_display_name(get_country_by_id(p["country_id"]))
        for p in active_all
    ]
    code = build_negotiation_code(neg["kind"], names)

    conn = db()
    conn.execute("UPDATE negotiations SET status='accepted', code=? WHERE id=?", (code, neg_id))
    conn.commit()
    conn.close()

    # پاداش ۵٪ رضایت مردمی به همه‌ی طرفین (اگه از قبل ۱۰۰٪ نباشن)
    for p in active_all:
        c = get_country_by_id(p["country_id"])
        if c and int(c["approval"]) < 100:
            change_approval(p["country_id"], 5)

    return "accepted", code


# =========================================================
#                     فروشگاه
# =========================================================

# unit = مقدار واقعی که با یک خرید اضافه می‌شود
# max = حداکثر مقدار واقعی
SHOP_ITEMS = [

    # ---------------- پهپاد ----------------

    {
        "code": "drone_mq9",
        "name": "MQ-9 Reaper",
        "category": "پهپادها",
        "price": 7000,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_tb2",
        "name": "Bayraktar TB2",
        "category": "پهپادها",
        "price": 5000,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_shahed136",
        "name": "Shahed-136",
        "category": "پهپادها",
        "price": 3500,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_predator",
        "name": "MQ-1 Predator",
        "category": "پهپادها",
        "price": 3000,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_wing",
        "name": "Wing Loong II",
        "category": "پهپادها",
        "price": 2500,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_heron",
        "name": "Heron TP",
        "category": "پهپادها",
        "price": 2000,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_switchblade",
        "name": "Switchblade 600",
        "category": "پهپادها",
        "price": 1500,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_mavic",
        "name": "DJI Mavic",
        "category": "پهپادها",
        "price": 1000,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },
    {
        "code": "drone_shahed131",
        "name": "Shahed-131",
        "category": "پهپادها",
        "price": 500,
        "unit": 10,
        "max": 3000,
        "requires": "air",
    },

    # ---------------- بمب‌افکن ----------------

    {
        "code": "bomber_b2",
        "name": "B-2",
        "category": "بمب‌افکن‌ها",
        "price": 10000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },
    {
        "code": "bomber_b21",
        "name": "B-21",
        "category": "بمب‌افکن‌ها",
        "price": 8000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },
    {
        "code": "bomber_b1",
        "name": "B-1 Lancer",
        "category": "بمب‌افکن‌ها",
        "price": 7000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },
    {
        "code": "bomber_b52",
        "name": "B-52",
        "category": "بمب‌افکن‌ها",
        "price": 6000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },
    {
        "code": "bomber_h20",
        "name": "H-20",
        "category": "بمب‌افکن‌ها",
        "price": 5000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },
    {
        "code": "bomber_normal",
        "name": "بمب‌افکن نرمال",
        "category": "بمب‌افکن‌ها",
        "price": 3000,
        "unit": 1,
        "max": 100,
        "requires": "air",
    },

    # ---------------- هلیکوپتر ----------------

    {
        "code": "heli_apache",
        "name": "Apache",
        "category": "هلیکوپترها",
        "price": 7000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "heli_blackhawk",
        "name": "Black Hawk",
        "category": "هلیکوپترها",
        "price": 6000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "heli_cobra",
        "name": "Cobra",
        "category": "هلیکوپترها",
        "price": 5000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "heli_mi24",
        "name": "Mi-24",
        "category": "هلیکوپترها",
        "price": 4500,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "heli_kiowa",
        "name": "OH-58 Kiowa",
        "category": "هلیکوپترها",
        "price": 3000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "heli_bell206",
        "name": "Bell 206",
        "category": "هلیکوپترها",
        "price": 2000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },

    # ---------------- نفربر ----------------

    {
        "code": "apc_btr80",
        "name": "BTR-80",
        "category": "نفربرها",
        "price": 10000,
        "unit": 10,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "apc_bmp3",
        "name": "BMP-3",
        "category": "نفربرها",
        "price": 9000,
        "unit": 10,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "apc_bradley",
        "name": "M2 Bradley",
        "category": "نفربرها",
        "price": 8000,
        "unit": 10,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "apc_stryker",
        "name": "Stryker",
        "category": "نفربرها",
        "price": 7000,
        "unit": 10,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "apc_bmd2",
        "name": "BMD-2",
        "category": "نفربرها",
        "price": 6000,
        "unit": 10,
        "max": 500,
        "requires": "military",
    },

    # ---------------- مین ----------------

    {
        "code": "mine_border",
        "name": "مین مرزی",
        "category": "مین‌ها",
        "price": 500,
        "unit": 100000,
        "max": 5000000,
        "requires": "all",
    },
    {
        "code": "mine_naval",
        "name": "مین دریایی",
        "category": "مین‌ها",
        "price": 500,
        "unit": 100000,
        "max": 5000000,
        "requires": "all",
    },
    {
        "code": "mine_antitank",
        "name": "مین ضدتانک",
        "category": "مین‌ها",
        "price": 700,
        "unit": 100000,
        "max": 5000000,
        "requires": "all",
    },
    {
        "code": "mine_hidden",
        "name": "مین مخفی حساس",
        "category": "مین‌ها",
        "price": 1000,
        "unit": 100000,
        "max": 5000000,
        "requires": "all",
    },

    # ---------------- تانک ----------------

    {
        "code": "tank_normal",
        "name": "تانک نرمال",
        "category": "تانک‌ها",
        "price": 500,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_armored",
        "name": "تانک زرهی",
        "category": "تانک‌ها",
        "price": 1000,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_challenger",
        "name": "Challenger 2",
        "category": "تانک‌ها",
        "price": 2000,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_merkava",
        "name": "Merkava",
        "category": "تانک‌ها",
        "price": 3500,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_super",
        "name": "تانک سوپر مرزی",
        "category": "تانک‌ها",
        "price": 4000,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_heydar",
        "name": "تانک حیدر",
        "category": "تانک‌ها",
        "price": 6000,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_leopard",
        "name": "Leopard",
        "category": "تانک‌ها",
        "price": 8000,
        "unit": 15,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_missile",
        "name": "تانک موشکی",
        "category": "تانک‌ها",
        "price": 10000,
        "unit": 5,
        "max": 500,
        "requires": "military",
    },
    {
        "code": "tank_modern",
        "name": "تانک مدرن کامل",
        "category": "تانک‌ها",
        "price": 12000,
        "unit": 5,
        "max": 500,
        "requires": "military",
    },

    # ---------------- جنگنده ----------------

    {
        "code": "fighter_f22",
        "name": "F-22",
        "category": "جنگنده‌ها",
        "price": 5000,
        "unit": 1,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_f35",
        "name": "F-35",
        "category": "جنگنده‌ها",
        "price": 4500,
        "unit": 1,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_su57",
        "name": "Su-57",
        "category": "جنگنده‌ها",
        "price": 4000,
        "unit": 1,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_f117",
        "name": "F-117",
        "category": "جنگنده‌ها",
        "price": 3500,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_rafale",
        "name": "Rafale",
        "category": "جنگنده‌ها",
        "price": 3000,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_eurofighter",
        "name": "Eurofighter Typhoon",
        "category": "جنگنده‌ها",
        "price": 2500,
        "unit": 10,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_f15",
        "name": "F-15EX",
        "category": "جنگنده‌ها",
        "price": 2000,
        "unit": 15,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_su35",
        "name": "Su-35",
        "category": "جنگنده‌ها",
        "price": 1500,
        "unit": 15,
        "max": 500,
        "requires": "air",
    },
    {
        "code": "fighter_f16",
        "name": "F-16",
        "category": "جنگنده‌ها",
        "price": 1000,
        "unit": 15,
        "max": 500,
        "requires": "air",
    },

    # ---------------- سرباز ----------------

    {
        "code": "soldier_ground",
        "name": "ارتش زمینی",
        "category": "نیروهای انسانی",
        "price": 1000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_navy",
        "name": "ارتش دریایی",
        "category": "نیروهای انسانی",
        "price": 2000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_air",
        "name": "ارتش هوایی",
        "category": "نیروهای انسانی",
        "price": 3000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_border",
        "name": "مرزبانی و امنیت",
        "category": "نیروهای انسانی",
        "price": 4000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_special",
        "name": "نیروهای ویژه",
        "category": "نیروهای انسانی",
        "price": 5000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_sniper",
        "name": "تک‌تیرانداز",
        "category": "نیروهای انسانی",
        "price": 6000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_rpg",
        "name": "اپراتور RPG",
        "category": "نیروهای انسانی",
        "price": 7000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_airborne",
        "name": "کماندوی هوابرد",
        "category": "نیروهای انسانی",
        "price": 8000,
        "unit": 10000,
        "max": 5000000,
        "requires": "military",
    },
    {
        "code": "soldier_delta",
        "name": "Delta Force",
        "category": "نیروهای انسانی",
        "price": 10000,
        "unit": 10000,
        "max": 10000,
        "requires": "military",
    },

    # ---------------- پناهگاه ----------------

    {
        "code": "shelter_nuclear",
        "name": "پناهگاه هسته‌ای",
        "category": "پناهگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 500,
        "requires": "all",
    },
    {
        "code": "shelter_command",
        "name": "پناهگاه فرماندهی",
        "category": "پناهگاه‌ها",
        "price": 2500,
        "unit": 1,
        "max": 500,
        "requires": "all",
    },
    {
        "code": "shelter_underground",
        "name": "پناهگاه زیرزمینی",
        "category": "پناهگاه‌ها",
        "price": 1000,
        "unit": 1,
        "max": 500,
        "requires": "all",
    },
    {
        "code": "shelter_normal",
        "name": "پناهگاه نرمال",
        "category": "پناهگاه‌ها",
        "price": 500,
        "unit": 1,
        "max": 500,
        "requires": "all",
    },

    # ---------------- هکر ----------------

    {
        "code": "hacker_pro",
        "name": "هکر حرفه‌ای",
        "category": "سایبری",
        "price": 10000,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },
    {
        "code": "hacker_normal",
        "name": "هکر نرمال",
        "category": "سایبری",
        "price": 500,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },
    {
        "code": "anti_pro",
        "name": "ضدهکر حرفه‌ای",
        "category": "سایبری",
        "price": 10000,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },
    {
        "code": "anti_normal",
        "name": "ضدهکر نرمال",
        "category": "سایبری",
        "price": 500,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },
    {
        "code": "hacker_system",
        "name": "سیستم کامپیوتری هکر ویژه",
        "category": "سایبری",
        "price": 10000,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },
    {
        "code": "anti_system",
        "name": "سیستم کامپیوتری ضدهک ویژه",
        "category": "سایبری",
        "price": 10000,
        "unit": 10,
        "max": 200,
        "requires": "cyber",
    },

    # ---------------- فرودگاه ----------------

    {
        "code": "airport_international",
        "name": "فرودگاه بین‌المللی",
        "category": "فرودگاه‌ها",
        "price": 1000,
        "unit": 1,
        "max": 50,
        "requires": "all",
    },
    {
        "code": "airport_domestic",
        "name": "فرودگاه داخلی",
        "category": "فرودگاه‌ها",
        "price": 500,
        "unit": 1,
        "max": 100,
        "requires": "all",
    },
    {
        "code": "airport_emergency",
        "name": "فرودگاه اضطراری",
        "category": "فرودگاه‌ها",
        "price": 500,
        "unit": 1,
        "max": 100,
        "requires": "all",
    },

    # ---------------- درآمدزا ----------------

    {
        "code": "income_petro",
        "name": "صنایع پتروشیمی بزرگ",
        "category": "درآمدزا",
        "price": 50000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 33000,
        "approval": 12,
    },
    {
        "code": "income_smuggling",
        "name": "ساختمان قاچاق",
        "category": "درآمدزا",
        "price": 10000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 7000,
        "approval": 2,
    },
    {
        "code": "income_gas",
        "name": "خط تولید گاز",
        "category": "درآمدزا",
        "price": 30000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 17000,
        "approval": 4,
    },
    {
        "code": "income_clothing",
        "name": "کارخانه پوشاک",
        "category": "درآمدزا",
        "price": 15000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 8000,
        "approval": 8,
    },
    {
        "code": "income_trading",
        "name": "تالار معاملات",
        "category": "درآمدزا",
        "price": 20000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 9500,
        "approval": 10,
    },
    {
        "code": "income_small_tanker",
        "name": "تانکر کوچک",
        "category": "درآمدزا",
        "price": 15000,
        "unit": 1,
        "max": 5,
        "requires": None,
        "daily_profit": 1500,
    },
    {
        "code": "income_large_tanker",
        "name": "تانکر بزرگ",
        "category": "درآمدزا",
        "price": 25000,
        "unit": 1,
        "max": 5,
        "requires": None,
        "daily_profit": 3500,
    },

    # ---------------- دریایی ----------------

    {
        "code": "navy_carrier_lincoln",
        "name": "ناو هواپیمابر ابراهام لینکلن",
        "category": "دریایی",
        "price": 100000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_carrier_ford",
        "name": "ناو هواپیمابر جرالد فورد",
        "category": "دریایی",
        "price": 90000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_carrier_charles",
        "name": "ناو هواپیمابر چارلز",
        "category": "دریایی",
        "price": 80000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_carrier_bush",
        "name": "ناو هواپیمابر یواس‌اس جورج اچ دبلیو بوش",
        "category": "دریایی",
        "price": 70000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_erlik_bruch",
        "name": "ناو ارلیک بروخ",
        "category": "دریایی",
        "price": 40000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_admiral",
        "name": "ناو ادمیرال",
        "category": "دریایی",
        "price": 30000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_sub_ohio",
        "name": "زیر دریایی اوهایو",
        "category": "دریایی",
        "price": 25000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_sub_delta",
        "name": "زیر دریایی دلتا",
        "category": "دریایی",
        "price": 20000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_boat_seraj",
        "name": "قایق تندرو سراج",
        "category": "دریایی",
        "price": 7000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_boat_lightning",
        "name": "قایق تندرو آذرخش",
        "category": "دریایی",
        "price": 5000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_destroyer",
        "name": "ناوشکن",
        "category": "دریایی",
        "price": 5000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },
    {
        "code": "navy_destroyer_missile",
        "name": "ناوشکن موشکی",
        "category": "دریایی",
        "price": 10000,
        "unit": 1,
        "max": 500,
        "requires": "naval",
    },

    # ---------------- امکانات عمومی ----------------

    {
        "code": "public_park",
        "name": "پارک",
        "category": "امکانات عمومی",
        "price": 2000,
        "unit": 1,
        "max": 100,
        "requires": "all",
        "approval": 2,
    },
    {
        "code": "public_amusement",
        "name": "شهربازی",
        "category": "امکانات عمومی",
        "price": 4000,
        "unit": 1,
        "max": 50,
        "requires": "all",
        "approval": 4,
    },
    {
        "code": "public_stadium",
        "name": "استادیوم",
        "category": "امکانات عمومی",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": "all",
        "approval": 7,
    },
    {
        "code": "public_cinema",
        "name": "سینما",
        "category": "امکانات عمومی",
        "price": 2500,
        "unit": 1,
        "max": 100,
        "requires": "all",
        "approval": 3,
    },
    {
        "code": "public_library",
        "name": "کتابخانه",
        "category": "امکانات عمومی",
        "price": 1000,
        "unit": 1,
        "max": 100,
        "requires": "all",
        "approval": 1,
    },
    {
        "code": "public_zoo",
        "name": "باغ‌وحش",
        "category": "امکانات عمومی",
        "price": 3000,
        "unit": 1,
        "max": 50,
        "requires": "all",
        "approval": 3,
    },

    # ---------------- پایگاه‌ها ----------------

    {
        "code": "base_military",
        "name": "پایگاه نظامی ویژه",
        "category": "پایگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_naval",
        "name": "پایگاه دریایی ویژه",
        "category": "پایگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_air",
        "name": "پایگاه هوایی ویژه",
        "category": "پایگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_missile",
        "name": "پایگاه موشکی ویژه",
        "category": "پایگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_cyber",
        "name": "پایگاه سایبری ویژه",
        "category": "پایگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_command",
        "name": "پایگاه فرماندهی نظامی",
        "category": "پایگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },
    {
        "code": "base_bio",
        "name": "آزمایشگاه زیستی",
        "category": "پایگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 20,
        "requires": None,
    },

    # ---------------- اتمی ----------------

    {
        "code": "atomic_bomb",
        "name": "بمب اتم",
        "category": "اتمی",
        "price": 30000,
        "unit": 1,
        "max": 5,
        "requires": "nuclear_license",
        "destruction": 2,
    },]


# =========================================================
#                دسته‌بندی فروشگاه
# =========================================================

CATEGORIES = []


for item in SHOP_ITEMS:
    if item["category"] not in CATEGORIES:
        CATEGORIES.append(item["category"])


def get_item(code):

    for item in SHOP_ITEMS:
        if item["code"] == code:
            return item

    return None


def items_in_category(category):

    return [
        item for item in SHOP_ITEMS
        if item["category"] == category
    ]


# =========================================================
#               تجهیزات یک کشور
# =========================================================

def get_equipment(country_id, code):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM equipment
        WHERE country_id=? AND code=?
    """, (
        country_id,
        code
    )).fetchone()

    conn.close()

    if not row:
        return 0

    return int(row["amount"])


def set_equipment(country_id, item, amount):

    conn = db()

    conn.execute("""
        INSERT INTO equipment
        (country_id, code, name, category, amount)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(country_id, code)
        DO UPDATE SET
            name=excluded.name,
            category=excluded.category,
            amount=excluded.amount
    """, (
        country_id,
        item["code"],
        item["name"],
        item["category"],
        amount
    ))

    conn.commit()
    conn.close()


def change_equipment(country_id, item, delta):

    current = get_equipment(
        country_id,
        item["code"]
    )

    new_amount = current + delta

    if new_amount < 0:
        return False, current

    if new_amount > item["max"]:
        return False, current

    set_equipment(
        country_id,
        item,
        new_amount
    )

    return True, new_amount


# =========================================================
#                  پیش‌نیازها
# =========================================================

def has_base(country_id, code):

    return get_equipment(
        country_id,
        code
    ) > 0


def requirement_text(req):

    names = {
        "military": "پایگاه نظامی ویژه",
        "air": "پایگاه هوایی ویژه",
        "naval": "پایگاه دریایی ویژه",
        "missile": "پایگاه موشکی ویژه",
        "cyber": "پایگاه سایبری ویژه",
        "bio": "آزمایشگاه زیستی",
        "all": "تمام پایگاه‌های لازم",
        "nuclear_license": "مجوز اتم",
    }

    return names.get(req, "")


def check_requirement(country_id, req):

    if not req:
        return True

    if req == "military":
        return has_base(country_id, "base_military")

    if req == "air":
        return has_base(country_id, "base_air")

    if req == "naval":
        return has_base(country_id, "base_naval")

    if req == "missile":
        return has_base(country_id, "base_missile")

    if req == "cyber":
        return has_base(country_id, "base_cyber")

    if req == "bio":
        return has_base(country_id, "base_bio")

    if req == "nuclear_license":
        country = get_country_by_id(country_id)
        return bool(country and int(country["nuclear_license"]) == 1)

    if req == "all":

        required = [
            "base_military",
            "base_naval",
            "base_air",
            "base_missile",
            "base_cyber",
            "base_command",
            "base_bio",
        ]

        return all(
            has_base(country_id, code)
            for code in required
        )

    return True


# =========================================================
#                  سود روزانه
# =========================================================

def calculate_country_profit(country_id):

    country = get_country_by_id(country_id)
    total = int(country["base_daily_profit"]) if country else 0

    for item in SHOP_ITEMS:

        profit = int(item.get("daily_profit", 0))

        if profit <= 0:
            continue

        amount = get_equipment(
            country_id,
            item["code"]
        )

        total += amount * profit

    total += get_toman_amount(country_id, "royal_treasury") * TOMAN_ITEMS["royal_treasury"]["profit"]

    return total


def sync_daily_profit(country_id):

    country = get_country_by_id(country_id)

    if not country:
        return

    calculated = calculate_country_profit(
        country_id
    )

    conn = db()

    conn.execute("""
        UPDATE countries
        SET daily_profit=?
        WHERE id=?
    """, (
        calculated,
        country_id
    ))

    conn.commit()
    conn.close()


def apply_daily_profits():

    today = datetime.now().date().isoformat()

    conn = db()

    countries = conn.execute("""
        SELECT *
        FROM countries
    """).fetchall()

    for country in countries:

        last = country["last_profit_date"]

        calculated = calculate_country_profit(
            country["id"]
        )

        if not last:
            conn.execute("""
                UPDATE countries
                SET daily_profit=?,
                    last_profit_date=?
                WHERE id=?
            """, (
                calculated,
                today,
                country["id"]
            ))

            continue

        if last < today:

            conn.execute("""
                UPDATE countries
                SET money=money+?,
                    daily_profit=?,
                    last_profit_date=?
                WHERE id=?
            """, (
                calculated,
                calculated,
                today,
                country["id"]
            ))

    conn.commit()
    conn.close()


# =========================================================
#                     خرید فروشگاه
# =========================================================

def buy_item_qty(country_id, item, qty):
    """مثل buy_item ولی برای خرید چند برابری یک‌جا: qty بار پشت‌سرهم
    همون بسته (item['unit'] عدد، به قیمت item['price']) خریده میشه."""

    country = get_country_by_id(country_id)

    if not country:
        return False, "کشور پیدا نشد."

    total_price = item["price"] * qty
    total_amount = item["unit"] * qty

    current = get_equipment(country_id, item["code"])

    if current + total_amount > item["max"]:
        return False, (
            f"❌ از حد مجاز بیشتر می‌شود.\n"
            f"📦 موجودی فعلی: {current:,}\n"
            f"🔢 حداکثر: {item['max']:,}"
        )

    if not check_requirement(country_id, item.get("requires")):
        return False, (
            "❌ پیش‌نیاز این تجهیز را ندارید.\n\n"
            f"🏗️ نیازمند: {requirement_text(item['requires'])}"
        )

    if country["money"] < total_price:
        return False, (
            "❌ بودجه کافی نیست.\n"
            f"💰 بودجه فعلی: {money(country['money'])}\n"
            f"💵 قیمت کل: {money(total_price)}"
        )

    conn = db()
    conn.execute(
        "UPDATE countries SET money=money-? WHERE id=?",
        (total_price, country_id)
    )
    conn.commit()
    conn.close()

    ok, new_amount = change_equipment(country_id, item, total_amount)

    if not ok:
        change_money(country_id, total_price)
        return False, "❌ خرید انجام نشد."

    approval = int(item.get("approval", 0)) * qty
    if approval:
        change_approval(country_id, approval)

    sync_daily_profit(country_id)

    return True, (
        f"✅ خرید با موفقیت انجام شد.\n\n"
        f"🛠️ تجهیز: {display_equipment_name(item['name'], item['category'])}\n"
        f"📦 مقدار اضافه‌شده: {total_amount:,}\n"
        f"💰 هزینه کل: {money(total_price)}\n"
        f"📦 موجودی جدید: {new_amount:,}"
    )


def buy_item(country_id, item):

    country = get_country_by_id(country_id)

    if not country:
        return False, "کشور پیدا نشد."

    current = get_equipment(
        country_id,
        item["code"]
    )

    if current + item["unit"] > item["max"]:
        return False, (
            f"❌ از حد مجاز بیشتر می‌شود.\n"
            f"حداکثر: {item['max']:,}"
        )

    if not check_requirement(
        country_id,
        item.get("requires")
    ):
        return False, (
            "❌ پیش‌نیاز این تجهیز را ندارید.\n\n"
            f"🏗️ نیازمند: "
            f"{requirement_text(item['requires'])}"
        )

    if country["money"] < item["price"]:
        return False, (
            "❌ بودجه کافی نیست.\n"
            f"💰 بودجه فعلی: {money(country['money'])}\n"
            f"💵 قیمت: {money(item['price'])}"
        )

    conn = db()

    conn.execute("""
        UPDATE countries
        SET money=money-?
        WHERE id=?
    """, (
        item["price"],
        country_id
    ))

    conn.commit()
    conn.close()

    ok, new_amount = change_equipment(
        country_id,
        item,
        item["unit"]
    )

    if not ok:
        change_money(
            country_id,
            item["price"]
        )

        return False, "❌ خرید انجام نشد."

    approval = int(item.get("approval", 0))

    if approval:
        change_approval(
            country_id,
            approval
        )

    sync_daily_profit(country_id)

    return True, (
        f"✅ خرید با موفقیت انجام شد.\n\n"
        f"🛠️ تجهیز: {display_equipment_name(item['name'], item['category'])}\n"
        f"📦 مقدار اضافه‌شده: {item['unit']:,}\n"
        f"💰 هزینه: {money(item['price'])}\n"
        f"📦 موجودی جدید: {new_amount:,}"
    )


# =========================================================
#                  منوی اصلی
# =========================================================

def main_menu():

    return (
        "🌍 𝐈𝐍𝐅𝐈𝐍𝐈𝐓𝐘 𝐖𝐀𝐑\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ 🏳️ کشور من\n"
        "2️⃣ 🎒 تجهیزات من\n"
        "3️⃣ 🛒 فروشگاه\n"
        "4️⃣ 💳 پنل وام\n"
        "5️⃣ 🧪 اختراع\n"
        "6️⃣ 🎭 رول\n"
        "7️⃣ 💰 تجهیزات تومانی\n"
        "8️⃣ 📝 ارسال بیانیه\n"
        "9️⃣ 🤝 مذاکره\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "0️⃣ 🚪 خروج"
    )


def show_country(country):

    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 کد کشور: {country['code']}\n"
        f"💰 بودجه: {money(country['money'])}\n"
        f"📈 سود روزانه: {money(country['daily_profit'])}\n"
        f"❤️ رضایت مردمی: {country['approval']}%" + (f" (+{country['approval_bonus']})" if int(country['approval_bonus']) else "") + "\n"
        f"🛡️ امنیت: {country['security']}\n"
        f"☢️ هسته‌ای: {country['nuclear']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "0️⃣ بازگشت"
    )


# =========================================================
#                  تجهیزات من
# =========================================================

def display_equipment_name(name, category):
    """نام نمایشی تجهیزات؛ نام‌های فارسی دست‌نخورده می‌مانند."""
    name = str(name).strip()

    # اگر نام فارسی است، همان نام اصلی نمایش داده شود.
    if re.search(r"[آ-ی]", name):
        return name

    if category == "پهپادها":
        return f"پهپاد {name}"

    if category == "بمب‌افکن‌ها":
        return f"بمب افکن {name}"

    if category == "نفربرها":
        return f"نفربر {name}"

    return name


def equipment_text(country_id):

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM equipment
        WHERE country_id=?
          AND amount>0
        ORDER BY category, name
    """, (country_id,)).fetchall()

    conn.close()

    if not rows:
        return "🎒 تجهیزات شما خالی است."

    text = "🎒 تجهیزات کشور\n━━━━━━━━━━━━━━━━━━━━━━\n"

    current_category = None

    for row in rows:

        if row["category"] != current_category:

            current_category = row["category"]

            text += (
                f"\n📂 {current_category}\n"
            )

        text += (
            f"▫️ {display_equipment_name(row['name'], row['category'])}: "
            f"{row['amount']:,}\n"
        )

    return text


# =========================================================
#                    فروشگاه
# =========================================================

def number_sticker(number):
    """برچسب شماره‌ی لیست رو می‌سازه. برای 1 تا 20 از کاراکترهای
    یونیکد «دایره‌ای» (①②③...) استفاده می‌کنه که هرکدوم یک کاراکتر
    تکی هستن، پس هیچ‌وقت داخل متن راست‌به‌چپ فارسی برعکس نمایش داده
    نمیشن (برخلاف ترکیب چند تا ایموجی رقم که تو بعضی اپ‌ها مثل
    سروش، حتی با ایزوله‌ی جهت هم گاهی برعکس رندر میشه)."""
    circled = [
        "0", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
        "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
    ]
    if 0 <= number < len(circled):
        return circled[number]
    return "\u2066(" + str(number) + ")\u2069"

CATEGORY_EMOJI = {
    "پهپادها": "🛸",
    "بمب‌افکن‌ها": "💣",
    "هلیکوپترها": "🚁",
    "نفربرها": "🚚",
    "مین‌ها": "💥",
    "تانک‌ها": "🛡️",
    "جنگنده‌ها": "🛩️",
    "نیروهای انسانی": "🪖",
    "پناهگاه‌ها": "🏠",
    "درآمدزا": "💰",
    "دریایی": "🚢",
    "امکانات عمومی": "🏗️",
    "سایبری": "💻",
    "فرودگاه‌ها": "✈️",
    "پایگاه‌ها": "🏭",
    "اتمی": "☢️",
}


def category_emoji(category):
    return CATEGORY_EMOJI.get(category, "▪️")


def shop_menu():

    if not is_enabled("shop_enabled"):
        return "🔴 فروشگاه بسته است.\n\nدر حال حاضر امکان خرید تجهیزات وجود ندارد."

    text = (
        "🛒 فروشگاه\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, category in enumerate(CATEGORIES, 1):

        text += f"{number_sticker(i)} {category_emoji(category)} {category}\n"

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "شماره دسته را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )

    return text


def shop_category_menu(category):

    items = items_in_category(category)

    text = (
        f"🛒 {category}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, item in enumerate(items, 1):

        profit = int(item.get("daily_profit", 0))
        approval = int(item.get("approval", 0))

        text += (
            f"{number_sticker(i)} {display_equipment_name(item['name'], item['category'])}\n"
            f"   💰 قیمت: {money(item['price'])}\n"
            f"   📦 خرید: {item['unit']:,} عدد\n"
        )

        if profit:
            text += (
                f"   📈 سود روزانه: "
                f"{money(profit)} به ازای هر واحد\n"
            )

        if approval:
            text += (
                f"   ❤️ رضایت: +{approval}%\n"
            )

        if item.get("destruction"):
            text += (
                f"   💥 تخریب: {item['destruction']}% از خاک حریف\n"
            )

        if item.get("requires"):
            text += (
                f"   🏗️ نیازمند: "
                f"{requirement_text(item['requires'])}\n"
            )

        text += (
            f"   🔢 حداکثر: {item['max']:,}\n\n"
        )

    text += "0️⃣ بازگشت"

    return text


def shop_item_details(item, country_id):

    current = get_equipment(
        country_id,
        item["code"]
    )

    profit = int(item.get("daily_profit", 0))
    approval = int(item.get("approval", 0))

    text = (
        f"🛠️ {display_equipment_name(item['name'], item['category'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت: {money(item['price'])}\n"
        f"📦 مقدار خرید: {item['unit']:,}\n"
        f"📦 موجودی شما: {current:,}\n"
        f"🔢 حداکثر: {item['max']:,}\n"
    )

    if profit:
        text += (
            f"📈 سود روزانه: "
            f"{money(profit)} به ازای هر واحد\n"
        )

    if approval:
        text += (
            f"❤️ رضایت: +{approval}%\n"
        )

    if item.get("destruction"):
        text += (
            f"💥 تخریب: {item['destruction']}% از خاک حریف\n"
        )

    if item.get("requires"):
        text += (
            f"🏗️ پیش‌نیاز: "
            f"{requirement_text(item['requires'])}\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ خرید\n"
        "0️⃣ بازگشت"
    )

    return text


def shop_qty_prompt(item, country_id):

    current = get_equipment(country_id, item["code"])
    room_left = item["max"] - current
    max_qty = room_left // item["unit"] if item["unit"] else 0

    return (
        f"🛠️ {display_equipment_name(item['name'], item['category'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت هر بسته: {money(item['price'])}\n"
        f"📦 هر بسته: {item['unit']:,} عدد\n"
        f"📦 موجودی شما: {current:,}\n"
        f"🔢 حداکثر تعداد بسته‌ی قابل خرید: {max_qty:,}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔢 چند بسته می‌خواید بخرید؟ عدد را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )


def shop_confirm_prompt(item, qty):

    total_price = item["price"] * qty
    total_amount = item["unit"] * qty

    return (
        f"🛠️ {display_equipment_name(item['name'], item['category'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 تعداد بسته: {qty:,}\n"
        f"📦 مقدار کل: {total_amount:,}\n"
        f"💰 قیمت کل: {money(total_price)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ خرید\n"
        "2️⃣ لغو"
    )


# =========================================================
#                تجهیزات تومانی
# =========================================================

TOMAN_ITEMS = {
    "royal_treasury": {
        "name": "🏛️ خزانه سلطنتی",
        "price": 50000,
        "limit": 3,
        "profit": 20000,
        "description": "📈 سود: ۲۰,۰۰۰ IC",
    },
    "international_stadium": {
        "name": "🏟️ استادیوم بین المللی",
        "price": 30000,
        "limit": 1,
        "profit": 0,
        "description": "❤️ کاربرد: افزایش ۵۰٪ رضایت مردمی",
    },
    "all_bases": {
        "name": "🪖 تمام پایگاه ها",
        "price": 50000,
        "limit": 1,
        "profit": 0,
        "description": "🛡️ کاربرد: گرفتن رایگان تمام پایگاه های لازم",
    },
}


def toman_menu():
    return (
        "💰 تجهیزات تومانی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ خزانه سلطنتی = ۵۰,۰۰۰ تومان ، سود = ۲۰,۰۰۰ IC\n"
        "   حداکثر: ۳\n"
        "2️⃣ استادیوم بین المللی = ۳۰,۰۰۰ تومان ، کاربرد = افزایش ۵۰٪ رضایت مردمی\n"
        "   حداکثر: ۱\n"
        "3️⃣ تمام پایگاه ها = ۵۰,۰۰۰ تومان ، کاربرد = گرفتن رایگان تمام پایگاه های لازم\n"
        "   حداکثر: ۱\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "شماره تجهیز را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )


def toman_details(key):
    item = TOMAN_ITEMS[key]
    return (
        f"{display_equipment_name(item['name'], item.get('category', ''))}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت: {toman(item['price'])}\n"
        f"🔢 حداکثر: {item['limit']}\n"
        f"{item['description']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📩 برای خرید به این آیدی پیام دهید: {TOMAN_CONTACT}\n"
        "⚠️ خرید آنلاین داخل بات وجود ندارد؛ پس از پرداخت، ادمین تجهیز را به کشور اضافه می‌کند.\n\n"
        "0️⃣ بازگشت"
    )


# =========================================================
#                     وام
# =========================================================

def loan_menu():

    if not is_enabled("loan_enabled"):

        return (
            "🏦 پنل وام\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 سیستم وام در حال حاضر خاموش است.\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "0️⃣ بازگشت"
        )

    return (
        "🏦 پنل وام\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ درخواست وام\n"
        "2️⃣ وام من\n"
        "3️⃣ پرداخت وام\n"
        "0️⃣ بازگشت"
    )


def create_loan(country_id, requested, days):

    repayment = requested + int(requested * 0.5)

    due = datetime.now() + timedelta(days=days)

    conn = db()

    conn.execute("""
        INSERT INTO loans
        (country_id, requested, repayment, days,
         status, created_at, due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        country_id,
        requested,
        repayment,
        days,
        "pending",
        datetime.now().isoformat(),
        due.isoformat()
    ))

    conn.commit()
    conn.close()


def active_loan(country_id):

    conn = db()

    row = conn.execute("""
        SELECT *
        FROM loans
        WHERE country_id=?
          AND status='approved'
          AND paid=0
        ORDER BY id DESC
        LIMIT 1
    """, (country_id,)).fetchone()

    conn.close()

    return row


def user_loans_text(country_id):

    loan = active_loan(country_id)

    if not loan:
        return (
            "🏦 وام من\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌ وام فعالی ندارید."
        )

    return (
        "🏦 وام من\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 مبلغ وام: {money(loan['requested'])}\n"
        f"💳 بازپرداخت کل: {money(loan['repayment'])}\n"
        f"💸 پرداخت‌شده: {money(loan['paid_amount'])}\n"
        f"📌 باقی‌مانده: {money(max(0, loan['repayment'] - loan['paid_amount']))}\n"
        f"⏳ مدت: {loan['days']} روز\n"
        f"📅 سررسید: {loan['due_date'][:10]}\n"
    )


# =========================================================
#                 بررسی وام‌های سررسید
# =========================================================

def update_loan_penalties():

    conn = db()

    loans = conn.execute("""
        SELECT *
        FROM loans
        WHERE status='approved'
          AND paid=0
    """).fetchall()

    today = datetime.now()

    for loan in loans:

        try:
            due = datetime.fromisoformat(
                loan["due_date"]
            )
        except Exception:
            continue

        if today <= due:
            continue

        country = conn.execute("""
            SELECT *
            FROM countries
            WHERE id=?
        """, (loan["country_id"],)).fetchone()

        if not country:
            continue

        repayment = int(loan["repayment"])

        if country["money"] >= repayment:

            conn.execute("""
                UPDATE countries
                SET money=money-?
                WHERE id=?
            """, (
                repayment,
                country["id"]
            ))

            conn.execute("""
                UPDATE loans
                SET paid=1,
                    status='paid'
                WHERE id=?
            """, (loan["id"],))

        else:

            # جریمه بازی:
            # بودجه موجود همان روز کسر می‌شود
            # و رضایت عمومی 50 واحد درصد کم می‌شود.
            available = int(country["money"])

            conn.execute("""
                UPDATE countries
                SET money=0,
                    approval=MAX(0, approval-50)
                WHERE id=?
            """, (country["id"],))

            conn.execute("""
                UPDATE loans
                SET missed=missed+1,
                    penalty=penalty+?,
                    due_date=?
                WHERE id=?
            """, (
                available,
                (today + timedelta(days=1)).isoformat(),
                loan["id"]
            ))

    conn.commit()
    conn.close()


# =========================================================
#                   اختراعات
# =========================================================

def invention_menu():

    if not is_enabled("invention_enabled"):

        return (
            "🧪 اختراعات\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 سیستم اختراعات خاموش است.\n"
            "0️⃣ بازگشت"
        )

    return (
        "🧪 اختراعات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ اختراع جدید\n"
        "2️⃣ وضعیت اختراع\n"
        "3️⃣ اختراع من\n"
        "0️⃣ بازگشت"
    )


def my_inventions(country_id):

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM inventions
        WHERE country_id=?
          AND status='approved'
    """, (country_id,)).fetchall()

    conn.close()

    if not rows:
        return "🧪 اختراع فعالی ندارید."

    text = "🧪 اختراع من\n━━━━━━━━━━━━━━━━━━━━━━\n"

    for i, row in enumerate(rows, 1):

        text += (
            f"{number_sticker(i)} {row['title']}\n"
            f"📦 هر 1 دانه\n"
            f"💰 قیمت: {money(row['price'])}\n"
            f"🔢 ظرفیت: {row['capacity']:,}\n\n"
        )

    return text


# =========================================================
#                       رول
# =========================================================

def role_menu():

    return (
        "🎭 رول\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ رول جدید\n"
        "2️⃣ وضعیت رول\n"
        "3️⃣ رول‌های فعال\n"
        "0️⃣ بازگشت"
    )


def active_roles(country_id):

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM roles
        WHERE country_id=?
          AND status='approved'
        ORDER BY id DESC
    """, (country_id,)).fetchall()

    conn.close()

    if not rows:
        return "🎭 رول فعالی ندارید."

    text = "🎭 رول‌های فعال\n━━━━━━━━━━━━━━━━━━━━━━\n"

    for row in rows:

        text += (
            f"▫️ {row['role_text']}\n"
            f"💰 مبلغ: {money(row['amount'])}\n\n"
        )

    return text


def admin_active_roles():
    conn = db()
    rows = conn.execute("""
        SELECT r.*, c.name, c.flag
        FROM roles r
        JOIN countries c ON c.id=r.country_id
        WHERE r.status='approved'
        ORDER BY r.id DESC
    """).fetchall()
    conn.close()
    if not rows:
        return "🎭 رول فعال وجود ندارد.\n\n0️⃣ بازگشت"
    text = "🎭 رول‌های فعال\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows, 1):
        text += f"{number_sticker(i)} {row['flag']} {row['name']}\n💰 بودجه گرفته شده: {money(row['amount'])}\n\n"
    text += "0️⃣ بازگشت"
    return text


def admin_role_menu():
    status = "🟢 روشن" if is_enabled("role_enabled") else "🔴 خاموش"
    return (
        "🎭 مدیریت رول‌ها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت: {status}\n\n"
        "1️⃣ رول‌های فعال\n"
        "2️⃣ درخواست‌های رول\n"
        "3️⃣ روشن / خاموش کردن رول‌ها\n"
        "0️⃣ بازگشت"
    )


# =========================================================
#                      مذاکره (منو)
# =========================================================

def negotiation_menu():
    return (
        "🤝 مذاکره\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ مذاکره با یک کشور\n"
        "2️⃣ مذاکره بین چند کشور\n"
        "3️⃣ وضعیت مذاکرات\n"
        "4️⃣ بایگانی\n"
        "0️⃣ بازگشت"
    )


def negotiation_country_list(prompt):
    text = f"{prompt}\n\n"
    for idx, code in enumerate(NEGOTIATION_COUNTRY_ORDER, start=1):
        name, flag = COUNTRIES[code]
        en = ENGLISH_NAMES[code]
        text += f"{idx}. {flag} {name} — {en}\n\n"
    text += "0️⃣ بازگشت"
    return text


def negotiation_status_text(country_id):
    conn = db()
    neg_ids = [
        r["negotiation_id"]
        for r in conn.execute(
            "SELECT DISTINCT negotiation_id FROM negotiation_participants WHERE country_id=?",
            (country_id,)
        ).fetchall()
    ]
    conn.close()

    if not neg_ids:
        return "🤝 وضعیت مذاکرات\n━━━━━━━━━━━━━━━━━━━━━━\nهیچ مذاکره‌ای ثبت نشده.\n\n0️⃣ بازگشت"

    text = "🤝 وضعیت مذاکرات\n━━━━━━━━━━━━━━━━━━━━━━\n"

    for neg_id in sorted(neg_ids, reverse=True):
        neg = get_negotiation(neg_id)
        requester = get_country_by_id(neg["requester_country_id"])
        targets = [p for p in negotiation_participants(neg_id) if p["role"] == "target"]
        target_names = "، ".join(get_country_by_id(t["country_id"])["name"] for t in targets)

        if neg["status"] == "accepted":
            status_line = "✅ قبول شده"
        elif neg["status"] == "rejected":
            status_line = "❌ رد شده"
        else:
            pending_names = "، ".join(
                get_country_by_id(t["country_id"])["name"]
                for t in targets if t["response"] == "pending"
            )
            status_line = f"⏳ منتظر پاسخ {pending_names}" if pending_names else "⏳ منتظر پاسخ"

        text += (
            "📌 درخواست مذاکره\n"
            f"درخواست‌کننده: {requester['flag']} {requester['name']}\n"
            f"به کشور: {target_names}\n"
            f"وضعیت: {status_line}\n"
        )

        if neg["code"]:
            text += f"کد مذاکرات: {neg['code']}\n"

        text += "━━━━━━━━━━━━━━━━━━━━━━\n"

    text += "0️⃣ بازگشت"
    return text


def negotiation_archive_rows(country_id):
    conn = db()
    rows = conn.execute("""
        SELECT np.negotiation_id AS neg_id, n.requester_country_id
        FROM negotiation_participants np
        JOIN negotiations n ON n.id = np.negotiation_id
        WHERE np.country_id=? AND np.role='target' AND np.response='pending' AND n.status='pending'
        ORDER BY np.negotiation_id
    """, (country_id,)).fetchall()
    conn.close()
    return rows


def negotiation_archive_text(country_id):
    rows = negotiation_archive_rows(country_id)

    if not rows:
        return "🗂 بایگانی\n━━━━━━━━━━━━━━━━━━━━━━\nدرخواستی در انتظار پاسخ نیست.\n\n0️⃣ بازگشت"

    text = "🗂 بایگانی\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, r in enumerate(rows, start=1):
        req = get_country_by_id(r["requester_country_id"])
        text += f"{idx}. درخواست مذاکره از {req['flag']} {req['name']}\n"
    text += "\nشماره‌ی درخواست را ارسال کنید.\n0️⃣ بازگشت"
    return text


def negotiation_archive_respond_menu(neg_id, requester):
    return (
        f"شما یک درخواست مذاکره از کشور {requester['flag']} {requester['name']} دارید.\n\n"
        "1️⃣ تایید\n"
        "2️⃣ لغو\n"
        "0️⃣ بازگشت"
    )


# =========================================================
#              مدیریت مذاکره (ادمین)
# =========================================================

def admin_negotiation_menu():
    status = "🟢 باز" if is_enabled("negotiation_enabled") else "🔴 بسته"
    return (
        "🤝 مدیریت مذاکره\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت: {status}\n\n"
        "1️⃣ بستن مذاکرات\n"
        "2️⃣ باز کردن مذاکرات\n"
        "3️⃣ مذاکرات قبول‌شده\n"
        "0️⃣ بازگشت"
    )


def admin_negotiation_accepted_list():
    conn = db()
    rows = conn.execute("""
        SELECT * FROM negotiations WHERE status='accepted' ORDER BY id DESC
    """).fetchall()
    conn.close()

    if not rows:
        return "🤝 مذاکرات قبول‌شده\n━━━━━━━━━━━━━━━━━━━━━━\nهنوز مذاکره‌ای قبول نشده.\n\n0️⃣ بازگشت"

    text = "🤝 مذاکرات قبول‌شده\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for neg in rows:
        text += f"🔗 {neg['code']}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "0️⃣ بازگشت"
    return text


# =========================================================
#          مدیریت کد کشورها (ادمین)
# =========================================================

def admin_country_code_menu():
    return (
        "🔑 مدیریت کد کشورها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ عوض کردن کد کشور\n"
        "2️⃣ کد کشورها\n"
        "0️⃣ بازگشت"
    )


def country_codes_list():
    conn = db()
    rows = conn.execute("SELECT * FROM countries ORDER BY name").fetchall()
    conn.close()
    text = "🔑 کد کشورها\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for c in rows:
        text += f"{c['flag']} {c['name']}: {c['code']}\n"
    text += "\n0️⃣ بازگشت"
    return text


def validate_country_code_format(raw):
    """برمی‌گردونه (True, کد نرمال‌شده) یا (False, پیام خطای دقیق)."""
    code = raw.strip()

    if len(code) != 8:
        return False, f"❌ کد باید دقیقاً ۸ کاراکتر باشد (کد شما {len(code)} کاراکتر است)."

    if not code.isascii():
        return False, "❌ فقط حروف بزرگ انگلیسی و عدد مجاز است."

    if not re.fullmatch(r"[A-Za-z0-9]{8}", code):
        return False, "❌ فقط حروف انگلیسی و عدد مجاز است (بدون فاصله یا نماد)."

    if code != code.upper():
        return False, "❌ حروف باید همگی بزرگ (Uppercase) باشند."

    return True, code


# =========================================================
#          مدیریت رضایت مردمی (ادمین)
# =========================================================

def admin_approval_menu():
    return (
        "❤️ مدیریت رضایت مردمی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "کد کشور مورد نظر را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )


def admin_approval_actions(country):
    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️ رضایت مردمی فعلی: {country['approval']}%\n\n"
        "1️⃣ اضافه کردن رضایت مردمی\n"
        "2️⃣ کم کردن رضایت مردمی\n"
        "0️⃣ بازگشت"
    )


# =========================================================
#                    پنل ادمین
# =========================================================

def admin_daily_deposit_confirm_menu():
    day = int(get_setting("game_day", "0"))
    return (
        "💸 واریز سود روزانه\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 روز بازی فعلی: {day}\n"
        "با تایید، یک روز بازی جلو می‌رود و سود همه کشورها واریز می‌شود.\n"
        "وام‌های سررسیدشده هم بررسی می‌شوند.\n\n"
        "1️⃣ تایید واریز\n0️⃣ بازگشت"
    )

def nuclear_license_menu():
    return ("☢️ مجوز اتم\n━━━━━━━━━━━━━━━━━━━━━━\n1️⃣ دادن مجوز اتم\n2️⃣ گرفتن مجوز اتم\n0️⃣ بازگشت")

def nuclear_license_country_menu(action):
    title = "دادن" if action == "grant" else "گرفتن"
    return f"☢️ {title} مجوز اتم\n━━━━━━━━━━━━━━━━━━━━━━\nکد کشور را ارسال کنید.\n0️⃣ بازگشت"

def advance_game_day():
    conn = db(); countries = conn.execute("SELECT id FROM countries").fetchall(); total = 0
    for country in countries:
        calculated = calculate_country_profit(country["id"])
        conn.execute("UPDATE countries SET money=money+?, daily_profit=? WHERE id=?", (calculated, calculated, country["id"]))
        total += calculated
    day = int(get_setting("game_day", "0")) + 1
    conn.execute("INSERT INTO bot_settings(key,value) VALUES ('game_day',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(day),))
    conn.commit(); conn.close()
    update_loan_penalties()
    return day, len(countries), total

def announcement_menu(country):
    return (
        "✉️ ارسال بیانیه\n\n"
        f"✅ کشور شما: 🌍 {country['name']}\n\n"
        "⚔️یک عکس یا فیلم همراه با متن بیانیه\n"
        "در یک پیام ارسال کنید.\n\n"
        "بدون مدیا یا بدون متن قبول نمی‌شود.\n"
        "حداقل باید 2 خط متن داشته باشد.\n\n"
        "0. بازگشت"
    )

NEWS_TAGS = {
    "آمریکا": "🇺🇸 United States | CNN",
    "روسیه": "🇷🇺 Russia | RT News",
    "چین": "🇨🇳 China | CCTV News",
    "بریتانیا": "🇬🇧 United Kingdom | BBC News",
    "فرانسه": "🇫🇷 France | France 24",
    "آلمان": "🇩🇪 Germany | DW News",
    "ایران": "🇮🇷 Iran | IRNA News",
    "اسرائیل": "🇮🇱 Israel | The Times of Israel",
    "کره شمالی": "🇰🇵 North Korea | KCNA",
    "هند": "🇮🇳 India | ANI News",
    "ایتالیا": "🇮🇹 Italy | ANSA",
    "پاکستان": "🇵🇰 Pakistan | PTV News",
    "ترکیه": "🇹🇷 Turkey | TRT World",
    "کانادا": "🇨🇦 Canada | CBC News",
    "عربستان سعودی": "🇸🇦 Saudi Arabia | SPA News",
    "برزیل": "🇧🇷 Brazil | Agência Brasil",
    "اوکراین": "🇺🇦 Ukraine | Ukrinform",
    "عراق": "🇮🇶 Iraq | INA News",
    "هلند": "🇳🇱 Netherlands | NOS News",
    "ژاپن": "🇯🇵 Japan | NHK News",
    "واگنر": "⚔️ ⊰ 𝐖𝐀𝐆𝐍𝐄𝐑 — 𝐏𝐑𝐈𝐕𝐀𝐓𝐄 𝐌𝐈𝐋𝐈𝐓𝐀𝐑𝐘 𝐂𝐎𝐌𝐏𝐀𝐍𝐘",
}

def announcement_tag(country_name):
    return NEWS_TAGS.get(country_name, f"{country_name}")

def save_announcement(country_id, user_id, text):
    conn=db()
    conn.execute("INSERT INTO announcements(country_id,user_id,text,created_at) VALUES(?,?,?,?)",(country_id,str(user_id),text,datetime.now().isoformat()))
    conn.commit(); conn.close()

def announcements_page(page=0):
    page=max(0,int(page)); offset=page*10
    conn=db()
    rows=conn.execute("""SELECT a.*,c.name FROM announcements a JOIN countries c ON c.id=a.country_id ORDER BY a.id DESC LIMIT 10 OFFSET ?""",(offset,)).fetchall()
    total=conn.execute("SELECT COUNT(*) AS n FROM announcements").fetchone()["n"]
    conn.close()
    if not rows:
        return "📝 بیانیه های ارسالی\n━━━━━━━━━━━━━━━━━━━━━━\nهیچ بیانیه‌ای ثبت نشده است.\n\n0️⃣ بازگشت"
    out=f"📝 بیانیه های ارسالی — صفحه {page+1}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i,row in enumerate(rows,offset+1):
        out += f"\n{i}. کشور : {row['name']}\nمتن بیانیه:\n{row['text']}\n"
    out += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if offset+10 < total: out += "1️⃣ صفحه بعد\n"
    if page>0: out += "2️⃣ صفحه قبل\n"
    out += "0️⃣ بازگشت"
    return out

def admin_announcement_menu():
    return "📝 مدیریت بیانیه ها\n━━━━━━━━━━━━━━━━━━━━━━\n1️⃣ بیانیه های ارسالی\n0️⃣ بازگشت"

def admin_shop_menu():
    status="🟢 روشن" if is_enabled("shop_enabled") else "🔴 خاموش"
    return f"🛒 مدیریت شاپ\n━━━━━━━━━━━━━━━━━━━━━━\nوضعیت شاپ: {status}\n\n1️⃣ خاموش کردن شاپ\n2️⃣ روشن کردن شاپ\n0️⃣ بازگشت"

def admin_menu():

    status = (
        "🟢 روشن"
        if is_enabled("bot_enabled")
        else
        "🔴 خاموش"
    )

    return (
        "👑 𝙄𝙉𝙁𝙄𝙉𝙄𝙏𝙔 𝙒𝘼𝙍 — پنل مدیریت\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 وضعیت بات: {status}\n\n"
        "1️⃣ روشن / خاموش کردن بات\n"
        "2️⃣ 💰 مدیریت بودجه\n"
        "3️⃣ 📈 مدیریت سود روزانه\n"
        "4️⃣ 🎒 مدیریت تجهیزات\n"
        "5️⃣ 🏦 مدیریت وام\n"
        "6️⃣ 🧪 مدیریت اختراعات\n"
        "7️⃣ 🎭 مدیریت رول‌ها\n"
        "8️⃣ 🌍 مدیریت کشورها\n"
        "9️⃣ 📊 آمار کلی\n"
        f"{number_sticker(10)} 💸 واریز سود روزانه\n"
        f"{number_sticker(11)} ☢️ مجوز اتم\n"
        f"{number_sticker(12)} 💰 مدیریت تجهیزات تومانی\n"
        f"{number_sticker(13)} 📝 مدیریت بیانیه ها\n"
        f"{number_sticker(14)} 🛒 مدیریت شاپ\n"
        f"{number_sticker(15)} 🔑 مدیریت کد کشورها\n"
        f"{number_sticker(16)} 🤝 مدیریت مذاکره\n"
        f"{number_sticker(17)} ❤️ مدیریت رضایت مردمی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "0️⃣ 🚪 خروج"
    )


def admin_budget_menu():

    return (
        "💰 مدیریت بودجه\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "کد کشور مورد نظر را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )


def admin_budget_actions(country):

    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 بودجه فعلی: {money(country['money'])}\n\n"
        "1️⃣ اضافه کردن بودجه\n"
        "2️⃣ کم کردن بودجه\n"
        "0️⃣ بازگشت"
    )


def admin_profit_actions(country):

    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 سود روزانه فعلی: {money(country['daily_profit'])}\n\n"
        "1️⃣ اضافه کردن سود روزانه\n"
        "2️⃣ کم کردن سود روزانه\n"
        "0️⃣ بازگشت"
    )




def get_toman_amount(country_id, code):
    conn=db(); row=conn.execute("SELECT amount FROM toman_equipment WHERE country_id=? AND code=?",(country_id,code)).fetchone(); conn.close()
    return int(row["amount"]) if row else 0


def set_toman_amount(country_id, code, amount):
    conn=db(); conn.execute("INSERT INTO toman_equipment(country_id,code,amount) VALUES(?,?,?) ON CONFLICT(country_id,code) DO UPDATE SET amount=excluded.amount",(country_id,code,amount)); conn.commit(); conn.close()


def admin_toman_list(country_id):
    c=get_country_by_id(country_id)
    text=f"💰 تجهیزات تومانی کشور\n━━━━━━━━━━━━━━━━━━━━━━\n{c['flag']} {c['name']}\n\n"
    for key,item in TOMAN_ITEMS.items():
        text += f"{item['name']}: {get_toman_amount(country_id,key)}/{item['limit']}\n"
    bonus = 50 if get_toman_amount(country_id,'international_stadium') else 0
    text += f"\n❤️ رضایت مردمی: {c['approval']}%" + (f" (+{bonus})" if bonus else "") + "\n\n1️⃣ اضافه کردن\n2️⃣ کم کردن\n0️⃣ بازگشت"
    return text


def admin_toman_items(country_id, operation):
    text="💰 انتخاب تجهیزات تومانی\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i,(key,item) in enumerate(TOMAN_ITEMS.items(),1):
        text += f"{number_sticker(i)} {item['name']} — {get_toman_amount(country_id,key)}/{item['limit']}\n"
    return text+"\n0️⃣ بازگشت"

# =========================================================
#                مدیریت تجهیزات ادمین
# =========================================================

def admin_equipment_list(country_id):

    text = (
        "🎒 تجهیزات کشور\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM equipment
        WHERE country_id=?
          AND amount>0
        ORDER BY category, name
    """, (country_id,)).fetchall()

    conn.close()

    if not rows:
        text += "❌ تجهیزی ندارد.\n\n"

    current_category = None

    for row in rows:

        if current_category != row["category"]:

            current_category = row["category"]

            text += (
                f"\n📂 {current_category}\n"
            )

        text += (
            f"▫️ {display_equipment_name(row['name'], row['category'])}: "
            f"{row['amount']:,}\n"
        )

    text += (
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ اضافه کردن تجهیزات\n"
        "2️⃣ کم کردن تجهیزات\n"
        "0️⃣ بازگشت"
    )

    return text


def admin_category_list():
    text = (
        "🛒 فروشگاه\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, category in enumerate(CATEGORIES, 1):
        text += f"{number_sticker(i)} {category_emoji(category)} {category}\n"
    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "شماره دسته را ارسال کنید.\n"
        "0️⃣ بازگشت"
    )
    return text


def admin_category_items(category, country_id):
    items = items_in_category(category)
    text = f"🛒 {category}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, item in enumerate(items, 1):
        text += f"{number_sticker(i)} {display_equipment_name(item['name'], item['category'])} | موجودی: {get_equipment(country_id, item['code']):,}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\nشماره تجهیز را ارسال کنید.\n0️⃣ بازگشت"
    return text


# =========================================================
#                     مدیریت کشورها
# =========================================================

def country_list():

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM countries
        ORDER BY name
    """).fetchall()

    conn.close()

    text = (
        "🌍 لیست کشورها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for country in rows:

        text += (
            f"{country['flag']} {country['name']}\n"
            f"🔑 {country['code']}\n"
            f"💰 {money(country['money'])}\n"
            f"📈 {money(country['daily_profit'])}\n"
            f"❤️ {country['approval']}%\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    text += "0️⃣ بازگشت"

    return text


# =========================================================
#                    قدرت تجهیزات
# =========================================================

def equipment_power(country_id):

    """
    امتیاز داخلی برای رتبه‌بندی بازی.
    این عدد پول واقعی نیست و فقط برای آمار کلی است.
    """

    score = 0

    conn = db()

    rows = conn.execute("""
        SELECT code, amount
        FROM equipment
        WHERE country_id=?
    """, (country_id,)).fetchall()

    conn.close()

    price_map = {
        item["code"]: item["price"]
        for item in SHOP_ITEMS
    }

    for row in rows:

        price = price_map.get(
            row["code"],
            0
        )

        amount = int(row["amount"])

        # ارزش تقریبی موجودی، با محدودسازی برای جلوگیری
        # از اعداد بسیار بزرگ
        score += min(
            amount * price,
            10_000_000_000
        )

    return score


def economic_power(country):

    return int(country["money"]) + (
        int(country["daily_profit"]) * 10
    )


def global_stats():

    conn = db()

    countries = conn.execute("""
        SELECT *
        FROM countries
    """).fetchall()

    conn.close()

    economic = sorted(
        countries,
        key=economic_power,
        reverse=True
    )

    military = sorted(
        countries,
        key=lambda c: equipment_power(c["id"]),
        reverse=True
    )

    text = (
        "📊 آمار کلی — Infinity War\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 ابرقدرت‌های اقتصادی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, country in enumerate(economic):

        medal = (
            medals[i]
            if i < 3
            else f"{i+1}️⃣"
        )

        text += (
            f"{medal} {country['flag']} "
            f"{country['name']}\n"
            f"   💰 بودجه: {money(country['money'])}\n"
            f"   📈 سود روزانه: "
            f"{money(country['daily_profit'])}\n\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚔️ ابرقدرت‌های تجهیزات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, country in enumerate(military):

        medal = (
            medals[i]
            if i < 3
            else f"{i+1}️⃣"
        )

        score = equipment_power(
            country["id"]
        )

        text += (
            f"{medal} {country['flag']} "
            f"{country['name']}\n"
            f"   ⚔️ امتیاز تجهیزات: "
            f"{score:,}\n\n"
        )

    return text


# =========================================================
#             مدیریت اختراعات ادمین
# =========================================================

def admin_invention_menu():

    status = (
        "🟢 روشن"
        if is_enabled("invention_enabled")
        else
        "🔴 خاموش"
    )

    return (
        "🧪 مدیریت اختراعات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت: {status}\n\n"
        "1️⃣ روشن کردن اختراع\n"
        "2️⃣ خاموش کردن اختراع\n"
        "3️⃣ درخواست‌های اختراع\n"
        "4️⃣ حذف اختراع\n"
        "0️⃣ بازگشت"
    )


def pending_inventions():

    conn = db()

    rows = conn.execute("""
        SELECT i.*, c.name, c.flag
        FROM inventions i
        JOIN countries c
        ON c.id=i.country_id
        WHERE i.status='pending'
        ORDER BY i.id
    """).fetchall()

    conn.close()

    if not rows:
        return "🧪 درخواست اختراع در انتظاری وجود ندارد."

    text = (
        "🧪 درخواست‌های اختراع\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, row in enumerate(rows, 1):

        text += (
            f"{number_sticker(i)} {row['flag']} {row['name']}\n"
            f"📝 {row['title']}\n"
            f"📦 ظرفیت: {row['capacity']:,}\n"
            f"💰 قیمت: {money(row['price'])}\n\n"
        )

    text += "شماره درخواست را ارسال کنید."

    return text


# =========================================================
#                  مدیریت رول ادمین
# =========================================================

def pending_roles():

    conn = db()

    rows = conn.execute("""
        SELECT r.*, c.name, c.flag
        FROM roles r
        JOIN countries c
        ON c.id=r.country_id
        WHERE r.status='pending'
        ORDER BY r.id
    """).fetchall()

    conn.close()

    if not rows:
        return "🎭 رول در انتظار بررسی وجود ندارد."

    text = (
        "🎭 رول‌های در انتظار بررسی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, row in enumerate(rows, 1):

        text += (
            f"{number_sticker(i)} {row['flag']} {row['name']}\n"
            f"📝 {row['role_text']}\n\n"
        )

    text += "شماره رول را ارسال کنید."

    return text


# =========================================================
#                     مدیریت وام ادمین
# =========================================================

def admin_loan_menu():

    status = (
        "🟢 روشن"
        if is_enabled("loan_enabled")
        else
        "🔴 خاموش"
    )

    return (
        "🏦 مدیریت وام\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت وام: {status}\n\n"
        "1️⃣ روشن کردن وام\n"
        "2️⃣ خاموش کردن وام\n"
        "3️⃣ درخواست‌های وام\n"
        "4️⃣ وام‌های فعال\n"
        "0️⃣ بازگشت"
    )


def active_loans_text():

    conn = db()

    rows = conn.execute("""
        SELECT l.*, c.name, c.flag
        FROM loans l
        JOIN countries c
        ON c.id=l.country_id
        WHERE l.status='approved'
          AND l.paid=0
        ORDER BY l.id
    """).fetchall()

    conn.close()

    if not rows:
        return "🏦 هیچ وام فعالی وجود ندارد."

    today = datetime.now()

    text = (
        "🏦 وام‌های فعال\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, row in enumerate(rows, 1):

        try:
            created = datetime.fromisoformat(row["created_at"])
            passed_days = max(0, (today - created).days)
        except Exception:
            passed_days = "-"

        try:
            due = datetime.fromisoformat(row["due_date"])
            remaining_days = (due - today).days
        except Exception:
            remaining_days = "-"

        remaining_label = (
            f"{remaining_days} روز"
            if isinstance(remaining_days, int) and remaining_days >= 0
            else "سررسید گذشته ⚠️"
        )

        text += (
            f"{number_sticker(i)} {row['flag']} {row['name']}\n"
            f"💰 مبلغ وام: {money(row['requested'])}\n"
            f"💳 بازپرداخت کل: {money(row['repayment'])}\n"
            f"📅 مدت کل: {row['days']} روز\n"
            f"⏳ گذشته: {passed_days} روز | باقی‌مانده: {remaining_label}\n"
        )

        if int(row["missed"] or 0) > 0:
            text += f"⚠️ تعداد جریمه‌های قبلی: {row['missed']}\n"

        text += "\n"

    return text


def pending_loans():

    conn = db()

    rows = conn.execute("""
        SELECT l.*, c.name, c.flag
        FROM loans l
        JOIN countries c
        ON c.id=l.country_id
        WHERE l.status='pending'
        ORDER BY l.id
    """).fetchall()

    conn.close()

    if not rows:
        return "🏦 درخواست وام در انتظاری وجود ندارد."

    text = (
        "🏦 درخواست‌های وام\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, row in enumerate(rows, 1):

        text += (
            f"{number_sticker(i)} {row['flag']} {row['name']}\n"
            f"💰 وام: {money(row['requested'])}\n"
            f"💳 بازپرداخت: {money(row['repayment'])}\n"
            f"⏳ مدت: {row['days']} روز\n\n"
        )

    return text


# =========================================================
#                فرمت مدیریت بودجه
# =========================================================

def parse_admin_money(text):

    text = normalize_text(text)

    # فقط عدد
    if not re.fullmatch(r"\d+", text):
        return None

    value = int(text)

    if value <= 0:
        return None

    return value


# =========================================================
#                     هندلر پیام
# =========================================================

def extract_message(update):

    # ساختار ممکن است بسته به نسخه API متفاوت باشد.
    # چند مسیر رایج بررسی می‌شود.

    message = update.get("message")

    if not message:
        message = update.get("result")

    if not isinstance(message, dict):
        return None

    chat_id = (
        message.get("chat_id")
        or message.get("chat", {}).get("id")
        or message.get("from_id")
        or message.get("user_id")
    )

    text = (
        message.get("text")
        or message.get("message")
        or ""
    )

    if chat_id is None:
        return None

    return str(chat_id), str(text).strip()


# =========================================================
#                     پردازش کاربر
# =========================================================

def handle_user(chat_id, text):

    ensure_user(chat_id)

    user = get_user(chat_id)

    if not user:
        return

    state = user["state"] or "login"

    # اگر کاربر کشور دارد، نباید به‌خاطر state قدیمی دوباره
    # وارد مرحله دریافت کد کشور شود.
    if user["country_id"] is not None and state == "login":
        state = "main"
        set_user_state(chat_id, "main")

    # ---------------------------------------------
    # خروج
    # ---------------------------------------------

    if text in ("0", "🚪 خروج") and state == "main":

        logout_user(chat_id)

        send_message(
            chat_id,
            "🚪 از کشور خارج شدید.\n"
            "برای ورود دوباره /start را بزنید."
        )

        return

    # ---------------------------------------------
    # /start
    # ---------------------------------------------

    if text == "/start":

        if user["country_id"] is not None:

            set_user_state(
                chat_id,
                "main"
            )

            country = get_country_by_id(
                user["country_id"]
            )

            if country:
                send_message(
                    chat_id,
                    f"🏠 به منوی اصلی برگشتید.\n\n{main_menu()}"
                )
                return

        set_user_state(
            chat_id,
            "login"
        )

        send_message(
            chat_id,
            "🌍 𝐈𝐍𝐅𝐈𝐍𝐈𝐓𝐘 𝐖𝐀𝐑\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔑 کد کشور خود را ارسال کنید:"
        )

        return

    # ---------------------------------------------
    # ورود
    # ---------------------------------------------

    if state == "login":

        country = country_by_code(text)

        if not country:

            send_message(
                chat_id,
                "❌ کد کشور نامعتبر است.\n"
                "🔐 کد کشور خود را ارسال کنید:"
            )

            return

        set_user_country(
            chat_id,
            country["id"]
        )

        send_message(
            chat_id,
            f"✅ ورود موفق!\n\n"
            f"{country['flag']} "
            f"{country['name']}\n\n"
            f"{main_menu()}"
        )

        return

    # ---------------------------------------------
    # کشور کاربر
    # ---------------------------------------------

    country = get_country_by_id(
        user["country_id"]
    )

    if not country:

        set_user_state(
            chat_id,
            "login"
        )

        send_message(
            chat_id,
            "❌ کشور شما پیدا نشد.\n"
            "کد کشور را دوباره ارسال کنید."
        )

        return

    # =====================================================
    # MAIN
    # =====================================================

    if state == "main":

        if text in ("1", "🏳️ کشور من"):

            set_user_state(
                chat_id,
                "country"
            )

            send_message(
                chat_id,
                show_country(country)
            )

            return

        if text in ("2", "🎒 تجهیزات من"):

            set_user_state(
                chat_id,
                "equipment"
            )

            send_message(
                chat_id,
                equipment_text(country["id"])
                + "\n\n0️⃣ بازگشت"
            )

            return

        if text in ("3", "🛒 فروشگاه"):

            if not is_enabled("shop_enabled"):
                send_message(chat_id, "🔴 فروشگاه بسته است.\n\nدر حال حاضر امکان خرید تجهیزات وجود ندارد.")
                return

            set_user_state(
                chat_id,
                "shop"
            )

            send_message(
                chat_id,
                shop_menu()
            )

            return

        if text in ("4", "🏦 وام", "💳 پنل وام"):

            if not is_enabled("loan_enabled"):

                send_message(
                    chat_id,
                    "🔴 سیستم وام خاموش است."
                )

                return

            set_user_state(
                chat_id,
                "loan"
            )

            send_message(
                chat_id,
                loan_menu()
            )

            return

        if text in ("5", "🧪 اختراع"):

            set_user_state(
                chat_id,
                "invention"
            )

            send_message(
                chat_id,
                invention_menu()
            )

            return

        if text in ("6", "🎭 رول"):

            if not is_enabled("role_enabled"):
                send_message(chat_id, "🔴 سیستم رول‌ها فعلاً خاموش است.")
                return

            set_user_state(
                chat_id,
                "role"
            )

            send_message(
                chat_id,
                role_menu()
            )

            return

        if text in ("7", "💰 تجهیزات تومانی"):

            set_user_state(
                chat_id,
                "toman"
            )

            send_message(
                chat_id,
                toman_menu()
            )

            return

        if text in ("8", "📝 ارسال بیانیه"):
            set_user_state(chat_id, "announcement")
            send_message(chat_id, announcement_menu(country))
            return

        if text in ("9", "🤝 مذاکره"):

            if not is_enabled("negotiation_enabled"):
                send_message(chat_id, "🔴 سیستم مذاکره فعلاً بسته است.")
                return

            set_user_state(chat_id, "negotiation")
            send_message(chat_id, negotiation_menu())
            return

        send_message(
            chat_id,
            main_menu()
        )

        return

    # =====================================================
    # NEGOTIATION (مذاکره)
    # =====================================================

    if state == "negotiation":

        if text == "0":
            set_user_state(chat_id, "main")
            send_message(chat_id, main_menu())
            return

        if text == "1":
            if not has_international_airport(country["id"]):
                send_message(
                    chat_id,
                    "❌ کشور شما پیش‌نیاز مذاکره را ندارد.\n"
                    "پیش‌نیاز: فرودگاه بین‌المللی\n\n" + negotiation_menu()
                )
                return
            set_user_state(chat_id, "negotiation_single_pick")
            send_message(chat_id, negotiation_country_list("🤝 مذاکره با یک کشور\nکشور مورد نظر را انتخاب کنید:"))
            return

        if text == "2":
            if not has_international_airport(country["id"]):
                send_message(
                    chat_id,
                    "❌ کشور شما پیش‌نیاز مذاکره را ندارد.\n"
                    "پیش‌نیاز: فرودگاه بین‌المللی\n\n" + negotiation_menu()
                )
                return
            set_user_state(chat_id, "negotiation_multi_pick")
            send_message(
                chat_id,
                negotiation_country_list(
                    "🤝 مذاکره بین چند کشور\n"
                    "حداقل ۳ کشور را انتخاب کنید — شماره‌ها را هرکدام در یک خط ارسال کنید\n"
                    "مثال:\n1\n6\n15"
                )
            )
            return

        if text == "3":
            set_user_state(chat_id, "negotiation_status")
            send_message(chat_id, negotiation_status_text(country["id"]))
            return

        if text == "4":
            set_user_state(chat_id, "negotiation_archive")
            send_message(chat_id, negotiation_archive_text(country["id"]))
            return

        send_message(chat_id, negotiation_menu())
        return

    if state == "negotiation_single_pick":

        if text == "0":
            set_user_state(chat_id, "negotiation")
            send_message(chat_id, negotiation_menu())
            return

        if not text.isdigit() or not (1 <= int(text) <= len(NEGOTIATION_COUNTRY_ORDER)):
            send_message(chat_id, "❌ شماره نامعتبر است. دوباره وارد کنید:")
            return

        target_code = NEGOTIATION_COUNTRY_ORDER[int(text) - 1]
        target = country_by_code(target_code)

        if target["id"] == country["id"]:
            send_message(chat_id, "❌ نمی‌توانید با کشور خودتان مذاکره کنید. کشور دیگری انتخاب کنید:")
            return

        if not has_international_airport(target["id"]):
            send_message(chat_id, f"❌ کشور {target['name']} فعلاً فرودگاه بین‌المللی ندارد. کشور دیگری انتخاب کنید:")
            return

        create_negotiation("bilateral", country["id"], [target["id"]])

        set_user_state(chat_id, "negotiation")
        send_message(
            chat_id,
            f"✅ درخواست مذاکره برای {target['flag']} {target['name']} ارسال شد.\n\n" + negotiation_menu()
        )
        return

    if state == "negotiation_multi_pick":

        if text == "0":
            set_user_state(chat_id, "negotiation")
            send_message(chat_id, negotiation_menu())
            return

        raw_numbers = [t.strip() for t in text.replace(",", "\n").splitlines() if t.strip()]

        if not all(n.isdigit() for n in raw_numbers):
            send_message(chat_id, "❌ فقط شماره‌ی کشورها را هرکدام در یک خط ارسال کنید. دوباره امتحان کنید:")
            return

        numbers = [int(n) for n in raw_numbers]

        if len(set(numbers)) < 3:
            send_message(chat_id, "❌ باید حداقل ۳ کشور متفاوت انتخاب کنید. دوباره ارسال کنید:")
            return

        if any(not (1 <= n <= len(NEGOTIATION_COUNTRY_ORDER)) for n in numbers):
            send_message(chat_id, "❌ یکی از شماره‌ها نامعتبر است. دوباره ارسال کنید:")
            return

        target_ids = []
        for n in dict.fromkeys(numbers):  # حذف تکراری با حفظ ترتیب
            target = country_by_code(NEGOTIATION_COUNTRY_ORDER[n - 1])
            if target["id"] == country["id"]:
                send_message(chat_id, "❌ نمی‌توانید کشور خودتان را انتخاب کنید. دوباره ارسال کنید:")
                return
            if not has_international_airport(target["id"]):
                send_message(chat_id, f"❌ کشور {target['name']} فعلاً فرودگاه بین‌المللی ندارد. دوباره ارسال کنید:")
                return
            target_ids.append(target["id"])

        create_negotiation("multilateral", country["id"], target_ids)

        set_user_state(chat_id, "negotiation")
        send_message(chat_id, "✅ درخواست مذاکره برای همه‌ی کشورهای انتخاب‌شده ارسال شد.\n\n" + negotiation_menu())
        return

    if state == "negotiation_status":
        if text == "0":
            set_user_state(chat_id, "negotiation")
            send_message(chat_id, negotiation_menu())
            return
        send_message(chat_id, negotiation_status_text(country["id"]))
        return

    if state == "negotiation_archive":

        if text == "0":
            set_user_state(chat_id, "negotiation")
            send_message(chat_id, negotiation_menu())
            return

        rows = negotiation_archive_rows(country["id"])

        if not text.isdigit() or not (1 <= int(text) <= len(rows)):
            send_message(chat_id, negotiation_archive_text(country["id"]))
            return

        row = rows[int(text) - 1]
        requester = get_country_by_id(row["requester_country_id"])

        set_user_state(chat_id, f"negotiation_archive_respond|{row['neg_id']}")
        send_message(chat_id, negotiation_archive_respond_menu(row["neg_id"], requester))
        return

    if state.startswith("negotiation_archive_respond|"):

        neg_id = int(state.split("|", 1)[1])

        if text == "0":
            set_user_state(chat_id, "negotiation_archive")
            send_message(chat_id, negotiation_archive_text(country["id"]))
            return

        if text not in ("1", "2"):
            neg = get_negotiation(neg_id)
            requester = get_country_by_id(neg["requester_country_id"])
            send_message(chat_id, negotiation_archive_respond_menu(neg_id, requester))
            return

        result, code = negotiation_respond(neg_id, country["id"], text == "1")

        set_user_state(chat_id, "negotiation")

        if result == "accepted":
            send_message(chat_id, f"✅ مذاکره قبول شد.\n🔗 کد مذاکرات: {code}\n\n" + negotiation_menu())
        elif result == "rejected":
            send_message(chat_id, "❌ مذاکره لغو شد.\n\n" + negotiation_menu())
        else:
            send_message(chat_id, "✅ پاسخ شما ثبت شد. منتظر بقیه‌ی طرفین هستیم.\n\n" + negotiation_menu())
        return

    # =====================================================
    # COUNTRY
    # =====================================================

    if state == "country":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        send_message(
            chat_id,
            show_country(country)
        )

        return

    # =====================================================
    # EQUIPMENT
    # =====================================================

    if state == "equipment":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        send_message(
            chat_id,
            equipment_text(country["id"])
            + "\n\n0️⃣ بازگشت"
        )

        return

    # =====================================================
    # SHOP
    # =====================================================

    if state.startswith("shop") and not is_enabled("shop_enabled"):
        set_user_state(chat_id, "main")
        send_message(chat_id, "🔴 فروشگاه بسته است.\n\nدر حال حاضر امکان خرید تجهیزات وجود ندارد.")
        return

    if state == "shop":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        if not text.isdigit():

            send_message(
                chat_id,
                shop_menu()
            )

            return

        number = int(text)

        if 1 <= number <= len(CATEGORIES):

            category = CATEGORIES[number - 1]

            set_user_state(
                chat_id,
                "shop_category|" + category
            )

            send_message(
                chat_id,
                shop_category_menu(category)
            )

            return

        send_message(
            chat_id,
            shop_menu()
        )

        return

    # =====================================================
    # SHOP CATEGORY
    # =====================================================

    if state.startswith("shop_category|"):

        category = state.split("|", 1)[1]

        items = items_in_category(
            category
        )

        if text == "0":

            set_user_state(
                chat_id,
                "shop"
            )

            send_message(
                chat_id,
                shop_menu()
            )

            return

        if not text.isdigit():

            send_message(
                chat_id,
                shop_category_menu(category)
            )

            return

        number = int(text)

        if not (1 <= number <= len(items)):

            send_message(
                chat_id,
                shop_category_menu(category)
            )

            return

        item = items[number - 1]

        set_user_state(
            chat_id,
            "shop_item|" + item["code"]
        )

        send_message(
            chat_id,
            shop_item_details(
                item,
                country["id"]
            )
        )

        return

    # =====================================================
    # SHOP ITEM
    # =====================================================

    if state.startswith("shop_item|"):

        code = state.split("|", 1)[1]

        item = get_item(code)

        if not item:

            set_user_state(
                chat_id,
                "shop"
            )

            send_message(
                chat_id,
                shop_menu()
            )

            return

        if text == "0":

            set_user_state(
                chat_id,
                "shop_category|" + item["category"]
            )

            send_message(
                chat_id,
                shop_category_menu(
                    item["category"]
                )
            )

            return

        if text == "1":

            set_user_state(
                chat_id,
                "shop_qty|" + item["code"]
            )

            send_message(
                chat_id,
                shop_qty_prompt(item, country["id"])
            )

            return

        send_message(
            chat_id,
            shop_item_details(
                item,
                country["id"]
            )
        )

        return

    # =====================================================
    # SHOP QTY (تعداد بسته)
    # =====================================================

    if state.startswith("shop_qty|"):

        code = state.split("|", 1)[1]
        item = get_item(code)

        if not item:
            set_user_state(chat_id, "shop")
            send_message(chat_id, shop_menu())
            return

        if text == "0":

            set_user_state(
                chat_id,
                "shop_item|" + item["code"]
            )

            send_message(
                chat_id,
                shop_item_details(item, country["id"])
            )

            return

        if not text.isdigit() or int(text) <= 0:

            send_message(
                chat_id,
                "❌ لطفاً یک عدد صحیح بزرگ‌تر از صفر ارسال کنید.\n\n" +
                shop_qty_prompt(item, country["id"])
            )

            return

        qty = int(text)

        current = get_equipment(country["id"], item["code"])

        if current + (item["unit"] * qty) > item["max"]:

            send_message(
                chat_id,
                "❌ این تعداد از حد مجاز بیشتر می‌شود.\n\n" +
                shop_qty_prompt(item, country["id"])
            )

            return

        set_user_state(
            chat_id,
            f"shop_confirm|{item['code']}|{qty}"
        )

        send_message(
            chat_id,
            shop_confirm_prompt(item, qty)
        )

        return

    # =====================================================
    # SHOP CONFIRM (تایید نهایی خرید)
    # =====================================================

    if state.startswith("shop_confirm|"):

        _, code, qty_str = state.split("|", 2)
        item = get_item(code)
        qty = int(qty_str)

        if not item:
            set_user_state(chat_id, "shop")
            send_message(chat_id, shop_menu())
            return

        if text == "1":

            ok, result = buy_item_qty(
                country["id"],
                item,
                qty
            )

            send_message(chat_id, result)

            if ok:
                set_user_state(
                    chat_id,
                    "shop_category|" + item["category"]
                )
                send_message(
                    chat_id,
                    "\n" + shop_category_menu(item["category"])
                )
            else:
                set_user_state(
                    chat_id,
                    "shop_item|" + item["code"]
                )

            return

        # هر چیزی جز "1" (از جمله "2" لغو) یعنی انصراف
        set_user_state(
            chat_id,
            "shop_item|" + item["code"]
        )

        send_message(
            chat_id,
            "❌ خرید لغو شد.\n\n" +
            shop_item_details(item, country["id"])
        )

        return

    # =====================================================
    # TOMAN
    # =====================================================

    if state == "toman":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        keys = list(TOMAN_ITEMS.keys())

        if text.isdigit():

            n = int(text)

            if 1 <= n <= len(keys):

                key = keys[n - 1]

                set_user_state(
                    chat_id,
                    "toman_item|" + key
                )

                send_message(
                    chat_id,
                    toman_details(key)
                )

                return

        send_message(
            chat_id,
            toman_menu()
        )

        return

    # =====================================================
    # TOMAN ITEM
    # =====================================================

    if state.startswith("toman_item|"):

        key = state.split("|", 1)[1]

        if text == "0":

            set_user_state(
                chat_id,
                "toman"
            )

            send_message(
                chat_id,
                toman_menu()
            )

            return

        send_message(
            chat_id,
            toman_details(key)
        )

        return

    # =====================================================
    # LOAN
    # =====================================================

    if state == "loan":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        if not is_enabled("loan_enabled"):

            send_message(
                chat_id,
                "🔴 سیستم وام خاموش است."
            )

            return

        if text == "1":

            set_user_state(
                chat_id,
                "loan_amount"
            )

            send_message(
                chat_id,
                "💰 مقدار وام را ارسال کنید:"
            )

            return

        if text == "2":
            send_message(chat_id, user_loans_text(country["id"]) + "\n\n0️⃣ بازگشت")
            return

        if text == "3":
            loan = active_loan(country["id"])
            if not loan:
                send_message(chat_id,"❌ وام فعالی ندارید.\n\n0️⃣ بازگشت")
                return
            remaining = max(0, loan["repayment"] - loan["paid_amount"])
            set_user_state(chat_id,"loan_payment")
            send_message(chat_id,"💳 پرداخت وام\n━━━━━━━━━━━━━━━━━━━━━━\n1️⃣ پرداخت کل هزینه\n2️⃣ پرداخت قسمتی از وام\n0️⃣ بازگشت\n\nباقی‌مانده: "+money(remaining))
            return

        send_message(chat_id, loan_menu())

        return

    # =====================================================
    # LOAN PAYMENT
    # =====================================================
    if state == "loan_payment":
        if text == "0": set_user_state(chat_id,"loan"); send_message(chat_id,loan_menu()); return
        loan=active_loan(country["id"])
        if not loan:
            set_user_state(chat_id,"loan"); send_message(chat_id,"❌ وام فعالی ندارید.\n\n"+loan_menu()); return
        remaining=max(0, loan["repayment"]-loan["paid_amount"])
        if text=="1":
            set_user_state(chat_id,f"loan_pay_confirm|{remaining}")
            send_message(chat_id,f"آیا مطمئن هستید مبلغ {money(remaining)} (همان بازپرداخت) بدهید؟\n\n1️⃣ تایید\n2️⃣ لغو")
            return
        if text=="2":
            set_user_state(chat_id,"loan_partial_amount")
            send_message(chat_id,"چه مقدار میخواهید پرداخت کنید؟\n0️⃣ بازگشت")
            return
        send_message(chat_id,"1️⃣ پرداخت کل هزینه\n2️⃣ پرداخت قسمتی از وام\n0️⃣ بازگشت"); return

    if state == "loan_partial_amount":
        if text=="0": set_user_state(chat_id,"loan_payment"); send_message(chat_id,"💳 پرداخت وام\n1️⃣ پرداخت کل هزینه\n2️⃣ پرداخت قسمتی از وام\n0️⃣ بازگشت"); return
        amount=parse_admin_money(text); loan=active_loan(country["id"])
        if amount is None or not loan: send_message(chat_id,"❌ مبلغ نامعتبر است."); return
        remaining=max(0,loan["repayment"]-loan["paid_amount"])
        if amount>remaining: send_message(chat_id,f"❌ بیشتر از باقی‌مانده است: {money(remaining)}"); return
        set_user_state(chat_id,f"loan_pay_confirm|{amount}")
        send_message(chat_id,f"آیا مایلید که مبلغ {money(amount)} را به عنوان قسمتی از وام پرداخت کنید\n1️⃣ تایید\n2️⃣ لغو"); return

    if state.startswith("loan_pay_confirm|"):
        amount=int(state.split("|",1)[1])
        if text=="2": set_user_state(chat_id,"loan_payment"); send_message(chat_id,"💳 پرداخت وام\n1️⃣ پرداخت کل هزینه\n2️⃣ پرداخت قسمتی از وام\n0️⃣ بازگشت"); return
        if text!="1": send_message(chat_id,"1️⃣ تایید\n2️⃣ لغو"); return
        loan=active_loan(country["id"])
        if not loan: set_user_state(chat_id,"loan"); send_message(chat_id,"❌ وام فعالی ندارید."); return
        remaining=max(0,loan["repayment"]-loan["paid_amount"])
        if amount>remaining: send_message(chat_id,"❌ مبلغ از باقی‌مانده بیشتر است."); return
        if country["money"]<amount:
            send_message(chat_id,f"❌ بودجه کافی نیست.\nبودجه فعلی: {money(country['money'])}"); return
        new_paid=loan["paid_amount"]+amount
        conn=db(); conn.execute("UPDATE countries SET money=money-? WHERE id=?",(amount,country["id"])); conn.execute("UPDATE loans SET paid_amount=?, paid=? WHERE id=?",(new_paid,1 if new_paid>=loan["repayment"] else 0,loan["id"])); conn.commit(); conn.close()
        set_user_state(chat_id,"loan"); send_message(chat_id,f"✅ مبلغ {money(amount)} پرداخت شد.\nباقی‌مانده: {money(max(0,loan['repayment']-new_paid))}\n\n{loan_menu()}"); return

    # =====================================================
    # LOAN AMOUNT
    # =====================================================

    if state == "loan_amount":

        value = parse_admin_money(text)

        if value is None:

            send_message(
                chat_id,
                "❌ فقط عدد صحیح وارد کنید."
            )

            return

        set_user_state(
            chat_id,
            "loan_days|" + str(value)
        )

        send_message(
            chat_id,
            "⏳ مدت وام را به روز وارد کنید:"
        )

        return

    # =====================================================
    # LOAN DAYS
    # =====================================================

    if state.startswith("loan_days|"):

        requested = int(
            state.split("|", 1)[1]
        )

        if not text.isdigit():

            send_message(
                chat_id,
                "❌ تعداد روز باید عدد باشد."
            )

            return

        days = int(text)

        if days <= 0:

            send_message(
                chat_id,
                "❌ مدت نامعتبر است."
            )

            return

        repayment = requested + int(
            requested * 0.5
        )

        set_user_state(
            chat_id,
            f"loan_confirm|{requested}|"
            f"{repayment}|{days}"
        )

        send_message(
            chat_id,
            "🏦 درخواست وام\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"کشور: {country['name']}\n"
            f"مقدار وام: {money(requested)}\n"
            f"بازپرداخت: {money(repayment)}\n"
            f"در چه مدت: {days} روز\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ تایید درخواست\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # LOAN CONFIRM
    # =====================================================

    if state.startswith("loan_confirm|"):

        if text == "0":

            set_user_state(
                chat_id,
                "loan"
            )

            send_message(
                chat_id,
                loan_menu()
            )

            return

        if text != "1":

            send_message(
                chat_id,
                "1️⃣ تایید\n0️⃣ بازگشت"
            )

            return

        _, requested, repayment, days = state.split("|")

        create_loan(
            country["id"],
            int(requested),
            int(days)
        )

        set_user_state(
            chat_id,
            "loan"
        )

        send_message(
            chat_id,
            "✅ درخواست وام برای مدیریت ارسال شد."
        )

        return

    # =====================================================
    # INVENTION
    # =====================================================

    if state == "invention":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        if not is_enabled("invention_enabled"):

            send_message(
                chat_id,
                "🔴 سیستم اختراعات خاموش است."
            )

            return

        if text == "1":

            set_user_state(
                chat_id,
                "invention_text"
            )

            send_message(
                chat_id,
                "🧪 اختراع خود را ارسال کنید:"
            )

            return

        if text == "2":

            conn = db()

            rows = conn.execute("""
                SELECT *
                FROM inventions
                WHERE country_id=?
                ORDER BY id DESC
            """, (country["id"],)).fetchall()

            conn.close()

            if not rows:

                send_message(
                    chat_id,
                    "🧪 اختراعی ثبت نشده است."
                )

            else:

                result = "🧪 وضعیت اختراعات\n━━━━━━━━━━━━━━━━━━━━━━\n"

                for row in rows:

                    status = {
                        "pending": "⏳ در انتظار بررسی",
                        "approved": "✅ اختراع قبول شد",
                        "rejected": "❌ اختراع لغو شد"
                    }.get(
                        row["status"],
                        row["status"]
                    )

                    result += (
                        f"▫️ {row['title']}\n"
                        f"{status}\n\n"
                    )

                send_message(
                    chat_id,
                    result
                )

            return

        if text == "3":

            send_message(
                chat_id,
                my_inventions(
                    country["id"]
                )
            )

            return

        send_message(
            chat_id,
            invention_menu()
        )

        return

    # =====================================================
    # INVENTION TEXT
    # =====================================================

    if state == "invention_text":

        if not text:

            send_message(
                chat_id,
                "❌ متن اختراع خالی است."
            )

            return

        conn = db()

        conn.execute("""
            INSERT INTO inventions
            (country_id, title, status)
            VALUES (?, ?, 'pending')
        """, (
            country["id"],
            text
        ))

        conn.commit()
        conn.close()

        set_user_state(
            chat_id,
            "invention"
        )

        send_message(
            chat_id,
            "✅ درخواست اختراع برای مدیریت ارسال شد."
        )

        return

    # =====================================================
    # ROLE
    # =====================================================

    if state == "role":

        if text == "0":

            set_user_state(
                chat_id,
                "main"
            )

            send_message(
                chat_id,
                main_menu()
            )

            return

        if text == "1":

            set_user_state(
                chat_id,
                "role_text"
            )

            send_message(
                chat_id,
                "🎭 رول خود را ارسال کنید:"
            )

            return

        if text == "2":

            conn = db()

            rows = conn.execute("""
                SELECT *
                FROM roles
                WHERE country_id=?
                ORDER BY id DESC
            """, (country["id"],)).fetchall()

            conn.close()

            if not rows:

                send_message(
                    chat_id,
                    "🎭 رولی ثبت نشده است."
                )

            else:

                result = "🎭 وضعیت رول‌ها\n━━━━━━━━━━━━━━━━━━━━━━\n"

                for row in rows:

                    status = {
                        "pending": "⏳ در انتظار بررسی",
                        "approved": "✅ تایید شد",
                        "rejected": "❌ لغو شد"
                    }.get(
                        row["status"],
                        row["status"]
                    )

                    result += (
                        f"▫️ {row['role_text']}\n"
                        f"{status}\n\n"
                    )

                send_message(
                    chat_id,
                    result
                )

            return

        if text == "3":

            send_message(
                chat_id,
                active_roles(
                    country["id"]
                )
            )

            return

        send_message(
            chat_id,
            role_menu()
        )

        return

    # =====================================================
    # ROLE TEXT
    # =====================================================

    if state == "role_text":

        conn = db()

        conn.execute("""
            INSERT INTO roles
            (country_id, role_text, status, created_at)
            VALUES (?, ?, 'pending', ?)
        """, (
            country["id"],
            text,
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        set_user_state(
            chat_id,
            "role"
        )

        send_message(
            chat_id,
            "✅ رول برای مدیریت ارسال شد."
        )

        return

    # =====================================================
    # حالت ناشناخته
    # =====================================================

    set_user_state(
        chat_id,
        "main"
    )

    send_message(
        chat_id,
        main_menu()
    )


# =========================================================
#                    پردازش ادمین
# =========================================================

def handle_admin(chat_id, text):

    ensure_user(chat_id)

    user = get_user(chat_id)

    state = user["state"]

    # ---------------------------------------------
    # ورود ادمین
    # ---------------------------------------------

    if state == "admin_login":

        if normalize_text(text).upper() == ADMIN_CODE.upper():

            conn = db()

            conn.execute("""
                UPDATE users
                SET is_admin=1,
                    state='admin_menu',
                    temp_data=''
                WHERE user_id=?
            """, (str(chat_id),))

            conn.commit()
            conn.close()

            send_message(
                chat_id,
                "✅ ورود مدیریت موفق بود.\n\n"
                + admin_menu()
            )

        else:

            send_message(
                chat_id,
                "❌ کد مدیریت اشتباه است."
            )

        return

    # ---------------------------------------------
    # admin menu
    # ---------------------------------------------

    if state == "admin_menu":

        if text == "0":

            conn = db()

            conn.execute("""
                UPDATE users
                SET is_admin=0,
                    state='login',
                    country_id=NULL,
                    temp_data=''
                WHERE user_id=?
            """, (str(chat_id),))

            conn.commit()
            conn.close()

            send_message(
                chat_id,
                "🚪 از پنل مدیریت خارج شدید."
            )

            return

        if text == "1":

            new_value = (
                "0"
                if is_enabled("bot_enabled")
                else "1"
            )

            set_setting(
                "bot_enabled",
                new_value
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text == "2":

            set_user_state(
                chat_id,
                "admin_budget_code"
            )

            send_message(
                chat_id,
                admin_budget_menu()
            )

            return

        if text == "3":

            set_user_state(
                chat_id,
                "admin_profit_code"
            )

            send_message(
                chat_id,
                "📈 مدیریت سود روزانه\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "کد کشور مورد نظر را ارسال کنید.\n"
                "0️⃣ بازگشت"
            )

            return

        if text == "4":

            set_user_state(
                chat_id,
                "admin_equipment_code"
            )

            send_message(
                chat_id,
                "🎒 مدیریت تجهیزات\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "کد کشور را وارد کنید.\n"
                "0️⃣ بازگشت"
            )

            return

        if text == "5":

            set_user_state(
                chat_id,
                "admin_loan"
            )

            send_message(
                chat_id,
                admin_loan_menu()
            )

            return

        if text == "6":

            set_user_state(
                chat_id,
                "admin_invention"
            )

            send_message(
                chat_id,
                admin_invention_menu()
            )

            return

        if text == "7":
            set_user_state(chat_id, "admin_role_menu")
            send_message(chat_id, admin_role_menu())

            return

        if text == "8":

            set_user_state(
                chat_id,
                "admin_countries"
            )

            send_message(
                chat_id,
                country_list()
            )

            return

        if text == "9":

            send_message(chat_id, global_stats())
            return

        if text == "10":
            set_user_state(chat_id, "admin_daily_deposit_confirm")
            send_message(chat_id, admin_daily_deposit_confirm_menu())
            return

        if text == "11":
            set_user_state(chat_id, "admin_nuclear_license")
            send_message(chat_id, nuclear_license_menu())
            return

        if text == "12":
            set_user_state(chat_id, "admin_toman_code")
            send_message(chat_id, "💰 مدیریت تجهیزات تومانی\n━━━━━━━━━━━━━━━━━━━━━━\nکد کشور را ارسال کنید.\n0️⃣ بازگشت")
            return

        if text == "13":
            set_user_state(chat_id, "admin_announcements")
            send_message(chat_id, admin_announcement_menu())
            return

        if text == "14":
            set_user_state(chat_id, "admin_shop")
            send_message(chat_id, admin_shop_menu())
            return

        if text == "15":
            set_user_state(chat_id, "admin_country_code_menu")
            send_message(chat_id, admin_country_code_menu())
            return

        if text == "16":
            set_user_state(chat_id, "admin_negotiation_menu")
            send_message(chat_id, admin_negotiation_menu())
            return

        if text == "17":
            set_user_state(chat_id, "admin_approval_code")
            send_message(chat_id, admin_approval_menu())
            return

        send_message(chat_id, admin_menu())

        return

    # =====================================================
    # ADMIN ANNOUNCEMENTS
    # =====================================================
    if state == "admin_announcements":
        if text == "0":
            set_user_state(chat_id,"admin_menu"); send_message(chat_id,admin_menu()); return
        if text == "1":
            set_user_state(chat_id,"admin_announcements_page|0"); send_message(chat_id,announcements_page(0)); return
        send_message(chat_id,admin_announcement_menu()); return

    if state.startswith("admin_announcements_page|"):
        page=int(state.split("|",1)[1])
        if text == "0":
            set_user_state(chat_id,"admin_announcements"); send_message(chat_id,admin_announcement_menu()); return
        if text == "1":
            nxt=page+1
            conn=db(); exists=conn.execute("SELECT 1 FROM announcements LIMIT 1 OFFSET ?",(nxt*10,)).fetchone(); conn.close()
            if exists: page=nxt
        elif text == "2" and page>0:
            page-=1
        else:
            send_message(chat_id,announcements_page(page)); return
        set_user_state(chat_id,f"admin_announcements_page|{page}"); send_message(chat_id,announcements_page(page)); return

    # =====================================================
    # ADMIN SHOP
    # =====================================================
    if state == "admin_shop":
        if text == "0":
            set_user_state(chat_id,"admin_menu"); send_message(chat_id,admin_menu()); return
        if text == "1":
            set_setting("shop_enabled","0"); send_message(chat_id,admin_shop_menu()); return
        if text == "2":
            set_setting("shop_enabled","1"); send_message(chat_id,admin_shop_menu()); return
        send_message(chat_id,admin_shop_menu()); return

    # =====================================================
    # ADMIN DAILY DEPOSIT
    # =====================================================
    if state == "admin_daily_deposit_confirm":
        if text == "0":
            set_user_state(chat_id, "admin_menu"); send_message(chat_id, admin_menu()); return
        if text != "1":
            send_message(chat_id, admin_daily_deposit_confirm_menu()); return
        day, count, total = advance_game_day()
        set_user_state(chat_id, "admin_menu")
        send_message(chat_id, f"✅ واریز سود روزانه انجام شد.\n\n📅 روز بازی: {day}\n🌍 تعداد کشورها: {count}\n💸 مجموع سود واریزشده: {money(total)}\n🏦 وام‌های سررسیدشده هم بررسی شدند.\n\n" + admin_menu())
        return

    # =====================================================
    # ADMIN NUCLEAR LICENSE
    # =====================================================
    if state == "admin_nuclear_license":
        if text == "0":
            set_user_state(chat_id, "admin_menu"); send_message(chat_id, admin_menu()); return
        if text == "1":
            set_user_state(chat_id, "admin_nuclear_license_country|grant"); send_message(chat_id, nuclear_license_country_menu("grant")); return
        if text == "2":
            set_user_state(chat_id, "admin_nuclear_license_country|revoke"); send_message(chat_id, nuclear_license_country_menu("revoke")); return
        send_message(chat_id, nuclear_license_menu()); return

    if state.startswith("admin_nuclear_license_country|"):
        action = state.split("|", 1)[1]
        if text == "0":
            set_user_state(chat_id, "admin_nuclear_license"); send_message(chat_id, nuclear_license_menu()); return
        country = country_by_code(text)
        if not country:
            send_message(chat_id, "❌ کد کشور نامعتبر است.\n\n" + nuclear_license_country_menu(action)); return
        value = 1 if action == "grant" else 0
        conn = db(); conn.execute("UPDATE countries SET nuclear_license=? WHERE id=?", (value, country["id"])); conn.commit(); conn.close()
        set_user_state(chat_id, "admin_nuclear_license")
        send_message(chat_id, f"✅ مجوز اتم {'داده شد' if value else 'گرفته شد'}.\n\n{country['flag']} {country['name']}\n☢️ مجوز اتم: {'دارد' if value else 'ندارد'}\n\n" + nuclear_license_menu())
        return

    # =====================================================
    # ADMIN BUDGET CODE
    # =====================================================

    if state == "admin_budget_code":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        country = country_by_code(text)

        if not country:

            send_message(
                chat_id,
                "❌ کد کشور نامعتبر است."
            )

            return

        set_user_state(
            chat_id,
            "admin_budget_action|" + str(country["id"])
        )

        send_message(
            chat_id,
            admin_budget_actions(country)
        )

        return

    # =====================================================
    # ADMIN BUDGET ACTION
    # =====================================================

    if state.startswith("admin_budget_action|"):

        country_id = int(
            state.split("|", 1)[1]
        )

        country = get_country_by_id(
            country_id
        )

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text not in ("1", "2"):

            send_message(
                chat_id,
                admin_budget_actions(country)
            )

            return

        operation = "add" if text == "1" else "remove"

        set_user_state(
            chat_id,
            f"admin_budget_amount|"
            f"{country_id}|{operation}"
        )

        send_message(
            chat_id,
            "💰 مقدار بودجه مورد نظر را بگویید:"
        )

        return

    # =====================================================
    # ADMIN BUDGET AMOUNT
    # =====================================================

    if state.startswith("admin_budget_amount|"):

        _, country_id, operation = state.split("|")

        value = parse_admin_money(text)

        if value is None:

            send_message(
                chat_id,
                "❌ فقط یک عدد صحیح مثبت وارد کنید."
            )

            return

        country = get_country_by_id(
            int(country_id)
        )

        word = (
            "اضافه شود"
            if operation == "add"
            else
            "کم شود"
        )

        set_user_state(
            chat_id,
            f"admin_budget_confirm|"
            f"{country_id}|{operation}|{value}"
        )

        send_message(
            chat_id,
            f"💰 مقدار: {money(value)}\n\n"
            f"آیا مطمئن هستید که این مقدار "
            f"به بودجه {country['name']} "
            f"{word}؟\n\n"
            "1️⃣ بله\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # ADMIN BUDGET CONFIRM
    # =====================================================

    if state.startswith("admin_budget_confirm|"):

        _, country_id, operation, value = state.split("|")

        country_id = int(country_id)
        value = int(value)

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text != "1":

            send_message(
                chat_id,
                "1️⃣ بله\n0️⃣ بازگشت"
            )

            return

        amount = value if operation == "add" else -value

        country = get_country_by_id(
            country_id
        )

        if operation == "remove" and country["money"] < value:

            send_message(
                chat_id,
                "❌ بودجه کشور برای این کاهش کافی نیست."
            )

            set_user_state(
                chat_id,
                "admin_menu"
            )

            return

        change_money(
            country_id,
            amount
        )

        country = get_country_by_id(
            country_id
        )

        set_user_state(
            chat_id,
            "admin_menu"
        )

        send_message(
            chat_id,
            f"✅ تغییر بودجه انجام شد.\n\n"
            f"{country['flag']} {country['name']}\n"
            f"💰 بودجه جدید: "
            f"{money(country['money'])}\n\n"
            f"{admin_menu()}"
        )

        return

    # =====================================================
    # ADMIN APPROVAL (رضایت مردمی) — همون ساختار بودجه
    # =====================================================

    if state == "admin_approval_code":

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        country = country_by_code(text)

        if not country:
            send_message(chat_id, "❌ کد کشور نامعتبر است.")
            return

        set_user_state(chat_id, "admin_approval_action|" + str(country["id"]))
        send_message(chat_id, admin_approval_actions(country))
        return

    if state.startswith("admin_approval_action|"):

        country_id = int(state.split("|", 1)[1])
        country = get_country_by_id(country_id)

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text not in ("1", "2"):
            send_message(chat_id, admin_approval_actions(country))
            return

        operation = "add" if text == "1" else "remove"

        set_user_state(chat_id, f"admin_approval_amount|{country_id}|{operation}")
        send_message(chat_id, "❤️ مقدار رضایت مردمی مورد نظر را بگویید (عدد بین ۰ تا ۱۰۰):")
        return

    if state.startswith("admin_approval_amount|"):

        _, country_id, operation = state.split("|")

        if not text.isdigit():
            send_message(chat_id, "❌ فقط یک عدد صحیح مثبت وارد کنید.")
            return

        value = int(text)
        country = get_country_by_id(int(country_id))

        word = "اضافه شود" if operation == "add" else "کم شود"

        set_user_state(chat_id, f"admin_approval_confirm|{country_id}|{operation}|{value}")
        send_message(
            chat_id,
            f"❤️ مقدار: {value}%\n\n"
            f"آیا مطمئن هستید که این مقدار به رضایت مردمی {country['name']} {word}؟\n\n"
            "1️⃣ بله\n0️⃣ بازگشت"
        )
        return

    if state.startswith("admin_approval_confirm|"):

        _, country_id, operation, value = state.split("|")
        country_id = int(country_id)
        value = int(value)

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text != "1":
            send_message(chat_id, "1️⃣ بله\n0️⃣ بازگشت")
            return

        amount = value if operation == "add" else -value
        change_approval(country_id, amount)
        country = get_country_by_id(country_id)

        set_user_state(chat_id, "admin_menu")
        send_message(
            chat_id,
            f"✅ تغییر رضایت مردمی انجام شد.\n\n"
            f"{country['flag']} {country['name']}\n"
            f"❤️ رضایت مردمی جدید: {country['approval']}%\n\n"
            f"{admin_menu()}"
        )
        return

    # =====================================================
    # ADMIN NEGOTIATION MANAGEMENT
    # =====================================================

    if state == "admin_negotiation_menu":

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text == "1":
            set_setting("negotiation_enabled", "0")
            send_message(chat_id, admin_negotiation_menu())
            return

        if text == "2":
            set_setting("negotiation_enabled", "1")
            send_message(chat_id, admin_negotiation_menu())
            return

        if text == "3":
            send_message(chat_id, admin_negotiation_accepted_list())
            return

        send_message(chat_id, admin_negotiation_menu())
        return

    # =====================================================
    # ADMIN COUNTRY CODE MANAGEMENT
    # =====================================================

    if state == "admin_country_code_menu":

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text == "1":
            set_user_state(chat_id, "admin_country_code_old")
            send_message(chat_id, "🔑 کد فعلی کشور را وارد کنید:")
            return

        if text == "2":
            send_message(chat_id, country_codes_list())
            return

        send_message(chat_id, admin_country_code_menu())
        return

    if state == "admin_country_code_old":

        if text == "0":
            set_user_state(chat_id, "admin_country_code_menu")
            send_message(chat_id, admin_country_code_menu())
            return

        country = country_by_code(text)

        if not country:
            send_message(chat_id, "❌ کشوری با این کد پیدا نشد. دوباره وارد کنید:")
            return

        set_user_state(chat_id, f"admin_country_code_new|{country['id']}")
        send_message(
            chat_id,
            f"{country['flag']} {country['name']}\n"
            f"🔑 کد فعلی: {country['code']}\n\n"
            "کد جدید را وارد کنید (۸ کاراکتر، فقط حروف بزرگ انگلیسی و عدد):"
        )
        return

    if state.startswith("admin_country_code_new|"):

        country_id = int(state.split("|", 1)[1])
        country = get_country_by_id(country_id)

        if text == "0":
            set_user_state(chat_id, "admin_country_code_menu")
            send_message(chat_id, admin_country_code_menu())
            return

        ok, result = validate_country_code_format(text)

        if not ok:
            send_message(chat_id, result + "\n\nدوباره وارد کنید:")
            return

        new_code = result

        conn = db()
        clash = conn.execute(
            "SELECT id FROM countries WHERE code=? AND id!=?",
            (new_code, country_id)
        ).fetchone()

        if clash:
            conn.close()
            send_message(chat_id, "❌ این کد قبلاً برای کشور دیگری استفاده شده است. کد دیگری وارد کنید:")
            return

        old_code = country["code"]
        conn.execute("UPDATE countries SET code=? WHERE id=?", (new_code, country_id))
        conn.commit()
        conn.close()

        set_user_state(chat_id, "admin_country_code_menu")
        send_message(
            chat_id,
            f"✅ کد کشور تغییر کرد.\n\n"
            f"{country['flag']} {country['name']}\n"
            f"🔑 کد قدیم: {old_code}\n"
            f"🔑 کد جدید: {new_code}\n\n"
            f"{admin_country_code_menu()}"
        )
        return

    # =====================================================
    # ADMIN PROFIT CODE
    # =====================================================

    if state == "admin_profit_code":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        country = country_by_code(text)

        if not country:

            send_message(
                chat_id,
                "❌ کد کشور نامعتبر است."
            )

            return

        sync_daily_profit(
            country["id"]
        )

        country = get_country_by_id(
            country["id"]
        )

        set_user_state(
            chat_id,
            "admin_profit_action|" +
            str(country["id"])
        )

        send_message(
            chat_id,
            admin_profit_actions(country)
        )

        return

    # =====================================================
    # ADMIN PROFIT ACTION
    # =====================================================

    if state.startswith("admin_profit_action|"):

        country_id = int(
            state.split("|", 1)[1]
        )

        country = get_country_by_id(
            country_id
        )

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text not in ("1", "2"):

            send_message(
                chat_id,
                admin_profit_actions(country)
            )

            return

        operation = (
            "add"
            if text == "1"
            else
            "remove"
        )

        set_user_state(
            chat_id,
            f"admin_profit_amount|"
            f"{country_id}|{operation}"
        )

        send_message(
            chat_id,
            "📈 مقدار سود روزانه را بگویید:"
        )

        return

    # =====================================================
    # ADMIN PROFIT AMOUNT
    # =====================================================

    if state.startswith("admin_profit_amount|"):

        _, country_id, operation = state.split("|")

        value = parse_admin_money(text)

        if value is None:

            send_message(
                chat_id,
                "❌ فقط عدد صحیح مثبت وارد کنید."
            )

            return

        country = get_country_by_id(
            int(country_id)
        )

        word = (
            "اضافه شود"
            if operation == "add"
            else
            "کم شود"
        )

        set_user_state(
            chat_id,
            f"admin_profit_confirm|"
            f"{country_id}|{operation}|{value}"
        )

        send_message(
            chat_id,
            f"📈 مقدار: {money(value)}\n\n"
            f"آیا مطمئن هستید که این مقدار "
            f"به سود روزانه {country['name']} "
            f"{word}؟\n\n"
            "1️⃣ بله\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # ADMIN PROFIT CONFIRM
    # =====================================================

    if state.startswith("admin_profit_confirm|"):

        _, country_id, operation, value = state.split("|")

        country_id = int(country_id)
        value = int(value)

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text != "1":

            send_message(
                chat_id,
                "1️⃣ بله\n0️⃣ بازگشت"
            )

            return

        country = get_country_by_id(
            country_id
        )

        if operation == "remove":

            if country["daily_profit"] < value:

                send_message(
                    chat_id,
                    "❌ سود روزانه نمی‌تواند منفی شود."
                )

                set_user_state(
                    chat_id,
                    "admin_menu"
                )

                return

            value = -value

        change_daily_profit(
            country_id,
            value
        )

        country = get_country_by_id(
            country_id
        )

        set_user_state(
            chat_id,
            "admin_menu"
        )

        send_message(
            chat_id,
            f"✅ سود روزانه تغییر کرد.\n\n"
            f"{country['flag']} {country['name']}\n"
            f"📈 سود روزانه جدید: "
            f"{money(country['daily_profit'])}\n\n"
            f"{admin_menu()}"
        )

        return

    # =====================================================
    # ADMIN EQUIPMENT CODE
    # =====================================================

    if state == "admin_equipment_code":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        country = country_by_code(text)

        if not country:

            send_message(
                chat_id,
                "❌ کد کشور نامعتبر است."
            )

            return

        set_user_state(
            chat_id,
            "admin_equipment_action|" +
            str(country["id"])
        )

        send_message(
            chat_id,
            admin_equipment_list(
                country["id"]
            )
        )

        return

    # =====================================================
    # ADMIN EQUIPMENT ACTION
    # =====================================================

    if state.startswith("admin_equipment_action|"):
        country_id = int(state.split("|", 1)[1])
        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return
        if text not in ("1", "2"):
            send_message(chat_id, admin_equipment_list(country_id))
            return
        operation = "add" if text == "1" else "remove"
        set_user_state(chat_id, f"admin_equipment_category|{country_id}|{operation}")
        send_message(chat_id, admin_category_list())
        return

    # =====================================================
    # ADMIN EQUIPMENT CATEGORY
    # =====================================================
    if state.startswith("admin_equipment_category|"):
        _, country_id, operation = state.split("|")
        country_id = int(country_id)
        if text == "0":
            set_user_state(chat_id, f"admin_equipment_action|{country_id}")
            send_message(chat_id, admin_equipment_list(country_id))
            return
        if not text.isdigit() or not (1 <= int(text) <= len(CATEGORIES)):
            send_message(chat_id, admin_category_list())
            return
        category = CATEGORIES[int(text)-1]
        set_user_state(chat_id, f"admin_equipment_items|{country_id}|{operation}|{category}")
        send_message(chat_id, admin_category_items(category, country_id))
        return

    # =====================================================
    # ADMIN EQUIPMENT ITEMS
    # =====================================================
    if state.startswith("admin_equipment_items|"):
        _, country_id, operation, category = state.split("|", 3)
        country_id = int(country_id)
        if text == "0":
            set_user_state(chat_id, f"admin_equipment_category|{country_id}|{operation}")
            send_message(chat_id, admin_category_list())
            return
        items = items_in_category(category)
        if not text.isdigit() or not (1 <= int(text) <= len(items)):
            send_message(chat_id, admin_category_items(category, country_id))
            return
        item = items[int(text)-1]
        set_user_state(chat_id, f"admin_equipment_amount|{country_id}|{operation}|{item['code']}")
        send_message(chat_id, f"🛠️ تجهیز: {item['name']}\n📦 موجودی فعلی: {get_equipment(country_id, item['code']):,}\n🔢 حداکثر: {item['max']:,}\n\nتعداد موردنظر را ارسال کنید.\n0️⃣ بازگشت")
        return

    # =====================================================
    # ADMIN EQUIPMENT AMOUNT
    # =====================================================

    if state.startswith("admin_equipment_amount|"):

        _, country_id, operation, code = state.split("|")
        country_id = int(country_id)

        if text == "0":
            item = get_item(code)
            category = item["category"] if item else CATEGORIES[0]
            set_user_state(chat_id, f"admin_equipment_items|{country_id}|{operation}|{category}")
            send_message(chat_id, admin_category_items(category, country_id))
            return

        if not text.isdigit():

            send_message(
                chat_id,
                "❌ تعداد باید عدد باشد."
            )

            return

        amount = int(text)

        if amount <= 0:

            send_message(
                chat_id,
                "❌ تعداد نامعتبر است."
            )

            return

        item = get_item(code)

        if not item:

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        delta = (
            amount
            if operation == "add"
            else
            -amount
        )

        current = get_equipment(
            country_id,
            code
        )

        new_amount = current + delta

        if new_amount < 0:

            send_message(
                chat_id,
                "❌ تجهیزات نمی‌تواند منفی باشد.\n\n0️⃣ بازگشت"
            )

            return

        if new_amount > item["max"]:

            send_message(
                chat_id,
                f"❌ بیشتر از حد مجاز است.\n"
                f"حداکثر: {item['max']:,}"
            )

            return

        set_equipment(
            country_id,
            item,
            new_amount
        )

        # سود درآمدزا از تجهیزات محاسبه می‌شود.
        sync_daily_profit(
            country_id
        )

        category = item["category"]
        set_user_state(chat_id, f"admin_equipment_action|{country_id}")
        country = get_country_by_id(country_id)
        send_message(chat_id, f"✅ تجهیزات تغییر کرد.\n\n{country['flag']} {country['name']}\n🛠️ {item['name']}\n📦 موجودی جدید: {new_amount:,}\n\n{admin_equipment_list(country_id)}")

        return

    # =====================================================
    # ADMIN TOMAN EQUIPMENT
    # =====================================================
    if state == "admin_toman_code":
        if text == "0":
            set_user_state(chat_id,"admin_menu"); send_message(chat_id,admin_menu()); return
        c=country_by_code(text)
        if not c:
            send_message(chat_id,"❌ کد کشور نامعتبر است.\n0️⃣ بازگشت"); return
        set_user_state(chat_id,f"admin_toman_action|{c['id']}")
        send_message(chat_id,admin_toman_list(c['id'])); return

    if state.startswith("admin_toman_action|"):
        cid=int(state.split("|",1)[1])
        if text=="0": set_user_state(chat_id,"admin_menu"); send_message(chat_id,admin_menu()); return
        if text not in ("1","2"): send_message(chat_id,admin_toman_list(cid)); return
        op="add" if text=="1" else "remove"
        set_user_state(chat_id,f"admin_toman_select|{cid}|{op}")
        send_message(chat_id,admin_toman_items(cid,op)); return

    if state.startswith("admin_toman_select|"):
        _,cid,op=state.split("|"); cid=int(cid)
        if text=="0": set_user_state(chat_id,f"admin_toman_action|{cid}"); send_message(chat_id,admin_toman_list(cid)); return
        if not text.isdigit() or not (1<=int(text)<=len(TOMAN_ITEMS)):
            send_message(chat_id,admin_toman_items(cid,op)); return
        key=list(TOMAN_ITEMS.keys())[int(text)-1]; item=TOMAN_ITEMS[key]; cur=get_toman_amount(cid,key)
        if op=="add" and cur>=item['limit']:
            send_message(chat_id,f"❌ این کشور حداکثر {item['name']} را خریداری کرده است.\n0️⃣ بازگشت"); return
        set_user_state(chat_id,f"admin_toman_amount|{cid}|{op}|{key}")
        send_message(chat_id,f"{item['name']}\nموجودی فعلی: {cur}\nحداکثر: {item['limit']}\nتعداد را ارسال کنید.\n0️⃣ بازگشت"); return

    if state.startswith("admin_toman_amount|"):
        _,cid,op,key=state.split("|"); cid=int(cid); item=TOMAN_ITEMS[key]
        if text=="0": set_user_state(chat_id,f"admin_toman_select|{cid}|{op}"); send_message(chat_id,admin_toman_items(cid,op)); return
        if not text.isdigit() or int(text)<=0: send_message(chat_id,"❌ تعداد نامعتبر است.\n0️⃣ بازگشت"); return
        amount=int(text); cur=get_toman_amount(cid,key); new=cur+(amount if op=="add" else -amount)
        if new<0: send_message(chat_id,"❌ تجهیزات تومانی نمی‌تواند منفی باشد.\n0️⃣ بازگشت"); return
        if new>item['limit']: send_message(chat_id,f"❌ بیشتر از حداکثر مجاز است: {item['limit']}\n0️⃣ بازگشت"); return
        # Stadium is a bonus, not a permanent change to base approval.
        if key=="international_stadium" and new==1: 
            conn=db(); conn.execute("UPDATE countries SET approval_bonus=50 WHERE id=?",(cid,)); conn.commit(); conn.close()
        if key=="international_stadium" and new==0:
            conn=db(); conn.execute("UPDATE countries SET approval_bonus=0 WHERE id=?",(cid,)); conn.commit(); conn.close()
        if key=="royal_treasury":
            pass
        if key=="all_bases" and new==1:
            for code in ["base_military","base_naval","base_air","base_missile","base_cyber","base_command","base_bio"]:
                it=get_item(code)
                if it: set_equipment(cid,it,1)
        if key=="all_bases" and new==0:
            for code in ["base_military","base_naval","base_air","base_missile","base_cyber","base_command","base_bio"]:
                it=get_item(code)
                if it: set_equipment(cid,it,0)
        set_toman_amount(cid,key,new)
        sync_daily_profit(cid)
        set_user_state(chat_id,f"admin_toman_action|{cid}")
        send_message(chat_id,"✅ تجهیزات تومانی تغییر کرد.\n\n"+admin_toman_list(cid)); return

    # =====================================================
    # ADMIN LOAN
    # =====================================================

    if state == "admin_loan":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text == "1":

            set_setting(
                "loan_enabled",
                "1"
            )

            send_message(
                chat_id,
                admin_loan_menu()
            )

            return

        if text == "2":

            set_setting(
                "loan_enabled",
                "0"
            )

            send_message(
                chat_id,
                admin_loan_menu()
            )

            return

        if text == "3":

            set_user_state(
                chat_id,
                "admin_pending_loans"
            )

            send_message(
                chat_id,
                pending_loans()
            )

            return

        if text == "4":

            send_message(
                chat_id,
                active_loans_text() + "\n0️⃣ بازگشت"
            )

            return

        send_message(
            chat_id,
            admin_loan_menu()
        )

        return

    # =====================================================
    # ADMIN PENDING LOANS
    # =====================================================

    if state == "admin_pending_loans":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if not text.isdigit():

            send_message(
                chat_id,
                pending_loans()
            )

            return

        number = int(text)

        conn = db()

        rows = conn.execute("""
            SELECT l.*, c.name, c.flag
            FROM loans l
            JOIN countries c
            ON c.id=l.country_id
            WHERE l.status='pending'
            ORDER BY l.id
        """).fetchall()

        conn.close()

        if not (1 <= number <= len(rows)):

            send_message(
                chat_id,
                pending_loans()
            )

            return

        loan = rows[number - 1]

        set_user_state(
            chat_id,
            f"admin_loan_confirm|{loan['id']}"
        )

        send_message(
            chat_id,
            f"🏦 درخواست وام\n"
            f"کشور: {loan['flag']} {loan['name']}\n"
            f"مبلغ: {money(loan['requested'])}\n"
            f"بازپرداخت: {money(loan['repayment'])}\n"
            f"مدت: {loan['days']} روز\n\n"
            "1️⃣ تایید\n"
            "2️⃣ رد\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # ADMIN LOAN CONFIRM
    # =====================================================

    if state.startswith("admin_loan_confirm|"):

        loan_id = int(
            state.split("|", 1)[1]
        )

        if text == "0":

            set_user_state(
                chat_id,
                "admin_loan"
            )

            send_message(
                chat_id,
                admin_loan_menu()
            )

            return

        conn = db()

        loan = conn.execute("""
            SELECT *
            FROM loans
            WHERE id=?
        """, (loan_id,)).fetchone()

        if not loan:

            conn.close()

            set_user_state(
                chat_id,
                "admin_loan"
            )

            send_message(
                chat_id,
                "❌ وام پیدا نشد."
            )

            return

        if text == "1":

            conn.execute("""
                UPDATE loans
                SET status='approved'
                WHERE id=?
            """, (loan_id,))

            conn.execute("""
                UPDATE countries
                SET money=money+?
                WHERE id=?
            """, (
                loan["requested"],
                loan["country_id"]
            ))

            conn.commit()

            conn.close()

            send_message(
                chat_id,
                "✅ وام تایید شد و مبلغ آن به بودجه کشور اضافه شد."
            )

        elif text == "2":

            conn.execute("""
                UPDATE loans
                SET status='rejected'
                WHERE id=?
            """, (loan_id,))

            conn.commit()
            conn.close()

            send_message(
                chat_id,
                "❌ درخواست وام رد شد."
            )

        else:

            conn.close()

            send_message(
                chat_id,
                "1️⃣ تایید\n2️⃣ رد\n0️⃣ بازگشت"
            )

            return

        set_user_state(
            chat_id,
            "admin_loan"
        )

        return

    # =====================================================
    # ADMIN INVENTION
    # =====================================================

    if state == "admin_invention":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        if text == "1":

            set_setting(
                "invention_enabled",
                "1"
            )

            send_message(
                chat_id,
                admin_invention_menu()
            )

            return

        if text == "2":

            set_setting(
                "invention_enabled",
                "0"
            )

            send_message(
                chat_id,
                admin_invention_menu()
            )

            return

        if text == "3":

            set_user_state(
                chat_id,
                "admin_pending_inventions"
            )

            send_message(
                chat_id,
                pending_inventions()
            )

            return

        if text == "4":
            set_user_state(chat_id, "admin_delete_invention")
            conn = db()
            rows = conn.execute("SELECT i.*, c.name, c.flag FROM inventions i JOIN countries c ON c.id=i.country_id WHERE i.status='approved' ORDER BY i.id").fetchall()
            conn.close()
            if rows:
                msg = "🗑️ اختراعات فعال\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"{number_sticker(i)} {r['flag']} {r['name']} — {r['title']}" for i,r in enumerate(rows,1)) + "\n\n0️⃣ بازگشت"
            else:
                msg = "❌ اختراع فعالی وجود ندارد.\n\n0️⃣ بازگشت"
            send_message(chat_id, msg)
            return

        send_message(
            chat_id,
            admin_invention_menu()
        )

        return

    # =====================================================
    # ADMIN DELETE INVENTION
    # =====================================================
    if state == "admin_delete_invention":
        if text == "0":
            set_user_state(chat_id, "admin_invention")
            send_message(chat_id, admin_invention_menu())
            return
        conn = db()
        rows = conn.execute("SELECT i.*, c.name, c.flag FROM inventions i JOIN countries c ON c.id=i.country_id WHERE i.status='approved' ORDER BY i.id").fetchall()
        conn.close()
        if not text.isdigit() or not (1 <= int(text) <= len(rows)):
            text_out = "🗑️ اختراعات فعال\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"{number_sticker(i)} {r['flag']} {r['name']} — {r['title']}" for i,r in enumerate(rows,1)) + "\n\n0️⃣ بازگشت"
            send_message(chat_id, text_out)
            return
        inv=rows[int(text)-1]
        set_user_state(chat_id, f"admin_delete_invention_confirm|{inv['id']}")
        send_message(chat_id, f"آیا مایلید اختراع {inv['title']} را حذف کنید؟\n\n1️⃣ تایید\n2️⃣ لغو")
        return

    if state.startswith("admin_delete_invention_confirm|"):
        inv_id=int(state.split("|",1)[1])
        if text == "2":
            set_user_state(chat_id,"admin_invention")
            send_message(chat_id,admin_invention_menu())
            return
        if text != "1":
            send_message(chat_id,"1️⃣ تایید\n2️⃣ لغو")
            return
        conn=db(); conn.execute("DELETE FROM inventions WHERE id=?",(inv_id,)); conn.commit(); conn.close()
        set_user_state(chat_id,"admin_invention")
        send_message(chat_id,"✅ اختراع حذف شد.\n\n"+admin_invention_menu())
        return

    # =====================================================
    # ADMIN PENDING INVENTIONS
    # =====================================================

    if state == "admin_pending_inventions":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_invention"
            )

            send_message(
                chat_id,
                admin_invention_menu()
            )

            return

        if not text.isdigit():

            send_message(
                chat_id,
                pending_inventions()
            )

            return

        number = int(text)

        conn = db()

        rows = conn.execute("""
            SELECT i.*, c.name, c.flag
            FROM inventions i
            JOIN countries c
            ON c.id=i.country_id
            WHERE i.status='pending'
            ORDER BY i.id
        """).fetchall()

        conn.close()

        if not (1 <= number <= len(rows)):

            send_message(
                chat_id,
                pending_inventions()
            )

            return

        invention = rows[number - 1]

        set_user_state(
            chat_id,
            f"admin_invention_choice|{invention['id']}"
        )

        send_message(
            chat_id,
            f"🧪 درخواست اختراع\n"
            f"کشور: {invention['flag']} "
            f"{invention['name']}\n\n"
            f"«{invention['title']}»\n\n"
            "1️⃣ ثبت (تعیین بودجه و تعداد)\n"
            "2️⃣ رد کردن\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # ADMIN INVENTION CHOICE (ثبت یا رد کردن)
    # =====================================================

    if state.startswith("admin_invention_choice|"):

        invention_id = int(
            state.split("|", 1)[1]
        )

        if text == "0":

            set_user_state(
                chat_id,
                "admin_pending_inventions"
            )

            send_message(
                chat_id,
                pending_inventions()
            )

            return

        conn = db()

        invention = conn.execute("""
            SELECT i.*, c.name, c.flag
            FROM inventions i
            JOIN countries c
            ON c.id=i.country_id
            WHERE i.id=?
        """, (invention_id,)).fetchone()

        if not invention:

            conn.close()

            set_user_state(
                chat_id,
                "admin_invention"
            )

            send_message(
                chat_id,
                "❌ اختراع پیدا نشد."
            )

            return

        if text == "2":

            conn.execute("""
                UPDATE inventions
                SET status='rejected'
                WHERE id=?
            """, (invention_id,))

            conn.commit()
            conn.close()

            set_user_state(
                chat_id,
                "admin_invention"
            )

            send_message(
                chat_id,
                f"❌ اختراع «{invention['title']}» "
                f"({invention['flag']} {invention['name']}) رد شد."
            )

            return

        if text == "1":

            conn.close()

            set_user_state(
                chat_id,
                f"admin_invention_input|{invention_id}"
            )

            send_message(
                chat_id,
                f"🧪 ثبت اختراع\n"
                f"کشور: {invention['flag']} "
                f"{invention['name']}\n\n"
                f"«{invention['title']}»\n\n"
                "فرمت را ارسال کنید:\n"
                "تعداد|قیمت\n\n"
                "مثال:\n"
                "100|50000"
            )

            return

        conn.close()

        send_message(
            chat_id,
            "1️⃣ ثبت (تعیین بودجه و تعداد)\n"
            "2️⃣ رد کردن\n"
            "0️⃣ بازگشت"
        )

        return

    # =====================================================
    # ADMIN INVENTION INPUT
    # =====================================================

    if state.startswith("admin_invention_input|"):

        invention_id = int(
            state.split("|", 1)[1]
        )

        match = re.fullmatch(
            r"\s*(\d+)\s*\|\s*(\d+)\s*",
            text
        )

        if not match:

            send_message(
                chat_id,
                "❌ فرمت اشتباه است.\n"
                "مثال: 100|50000"
            )

            return

        capacity = int(
            match.group(1)
        )

        price = int(
            match.group(2)
        )

        conn = db()

        invention = conn.execute("""
            SELECT i.*, c.name, c.flag
            FROM inventions i
            JOIN countries c
            ON c.id=i.country_id
            WHERE i.id=?
        """, (invention_id,)).fetchone()

        if not invention:

            conn.close()

            set_user_state(
                chat_id,
                "admin_invention"
            )

            send_message(
                chat_id,
                "❌ اختراع پیدا نشد."
            )

            return

        conn.execute("""
            UPDATE inventions
            SET capacity=?, price=?
            WHERE id=?
        """, (
            capacity,
            price,
            invention_id
        ))

        conn.commit()
        conn.close()

        set_user_state(
            chat_id,
            f"admin_invention_confirm|{invention_id}"
        )

        send_message(
            chat_id,
            f"{invention['flag']} {invention['name']} "
            f"توانایی ساخت {capacity:,} تا "
            f"از این دستگاه را دارد.\n"
            f"💰 قیمت هر کدام "
            f"{price:,} است.\n\n"
            "1️⃣ تایید\n"
            "2️⃣ لغو"
        )

        return

    # =====================================================
    # ADMIN INVENTION CONFIRM
    # =====================================================

    if state.startswith("admin_invention_confirm|"):

        invention_id = int(
            state.split("|", 1)[1]
        )

        if text not in ("1", "2"):

            send_message(
                chat_id,
                "1️⃣ تایید\n2️⃣ لغو"
            )

            return

        conn = db()

        if text == "1":

            conn.execute("""
                UPDATE inventions
                SET status='approved'
                WHERE id=?
            """, (invention_id,))

            message = "✅ اختراع قبول شد."

        else:

            conn.execute("""
                UPDATE inventions
                SET status='rejected'
                WHERE id=?
            """, (invention_id,))

            message = "❌ اختراع لغو شد."

        conn.commit()
        conn.close()

        set_user_state(
            chat_id,
            "admin_invention"
        )

        send_message(
            chat_id,
            message
        )

        return

    # =====================================================
    # ADMIN ROLE MENU / ACTIVE ROLES
    # =====================================================
    if state == "admin_role_menu":
        if text == "0":
            set_user_state(chat_id,"admin_menu"); send_message(chat_id,admin_menu()); return
        if text == "1":
            set_user_state(chat_id,"admin_active_roles")
            send_message(chat_id,admin_active_roles())
            return
        if text == "2":
            set_user_state(chat_id,"admin_role_list")
            send_message(chat_id,pending_roles())
            return
        if text == "3":
            new_value = "0" if is_enabled("role_enabled") else "1"
            set_setting("role_enabled", new_value)
            send_message(chat_id,admin_role_menu())
            return
        send_message(chat_id,admin_role_menu()); return

    if state == "admin_active_roles":
        if text == "0":
            set_user_state(chat_id,"admin_role_menu"); send_message(chat_id,admin_role_menu()); return
        send_message(chat_id,admin_active_roles()); return

    # =====================================================
    # ADMIN ROLE LIST
    # =====================================================

    if state == "admin_role_list":

        if text == "0":

            set_user_state(chat_id, "admin_role_menu")
            send_message(chat_id, admin_role_menu())
            return

        if not text.isdigit():

            send_message(
                chat_id,
                pending_roles()
            )

            return

        number = int(text)

        conn = db()

        rows = conn.execute("""
            SELECT r.*, c.name, c.flag
            FROM roles r
            JOIN countries c
            ON c.id=r.country_id
            WHERE r.status='pending'
            ORDER BY r.id
        """).fetchall()

        conn.close()

        if not (1 <= number <= len(rows)):

            send_message(
                chat_id,
                pending_roles()
            )

            return

        role = rows[number - 1]

        set_user_state(
            chat_id,
            f"admin_role_amount|{role['id']}"
        )

        send_message(
            chat_id,
            f"🎭 رول کشور "
            f"{role['flag']} {role['name']}\n\n"
            f"«{role['role_text']}»\n\n"
            "مقدار بودجه رول را ارسال کنید.\n"
            "مثال: 6000"
        )

        return

    # =====================================================
    # ADMIN ROLE AMOUNT
    # =====================================================

    if state.startswith("admin_role_amount|"):

        role_id = int(
            state.split("|", 1)[1]
        )

        value = parse_admin_money(text)

        if value is None:

            send_message(
                chat_id,
                "❌ فقط عدد مثبت وارد کنید."
            )

            return

        conn = db()

        role = conn.execute("""
            SELECT r.*, c.name, c.flag
            FROM roles r
            JOIN countries c
            ON c.id=r.country_id
            WHERE r.id=?
        """, (role_id,)).fetchone()

        conn.close()

        if not role:

            set_user_state(
                chat_id,
                "admin_role_list"
            )

            send_message(
                chat_id,
                "❌ رول پیدا نشد."
            )

            return

        conn = db()

        conn.execute("""
            UPDATE roles
            SET amount=?
            WHERE id=?
        """, (
            value,
            role_id
        ))

        conn.commit()
        conn.close()

        set_user_state(
            chat_id,
            f"admin_role_confirm|{role_id}"
        )

        send_message(
            chat_id,
            f"🎭 آیا مایلید به خاطر رول "
            f"{role['flag']} {role['name']}\n"
            f"مبلغ {value:,} IC به بودجه او اضافه شود؟\n\n"
            "1️⃣ تایید\n"
            "2️⃣ لغو"
        )

        return

    # =====================================================
    # ADMIN ROLE CONFIRM
    # =====================================================

    if state.startswith("admin_role_confirm|"):

        role_id = int(
            state.split("|", 1)[1]
        )

        if text not in ("1", "2"):

            send_message(
                chat_id,
                "1️⃣ تایید\n2️⃣ لغو"
            )

            return

        conn = db()

        role = conn.execute("""
            SELECT *
            FROM roles
            WHERE id=?
        """, (role_id,)).fetchone()

        if not role:

            conn.close()

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                "❌ رول پیدا نشد."
            )

            return

        if text == "1":

            conn.execute("""
                UPDATE countries
                SET money=money+?
                WHERE id=?
            """, (
                role["amount"],
                role["country_id"]
            ))

            conn.execute("""
                UPDATE roles
                SET status='approved'
                WHERE id=?
            """, (role_id,))

            message = (
                f"✅ {money(role['amount'])} "
                "به بودجه کشور اضافه شد."
            )

        else:

            conn.execute("""
                UPDATE roles
                SET status='rejected'
                WHERE id=?
            """, (role_id,))

            message = "❌ رول لغو شد."

        conn.commit()
        conn.close()

        set_user_state(chat_id, "admin_role_menu")
        send_message(chat_id, message + "\n\n" + admin_role_menu())
        return

    # =====================================================
    # ADMIN COUNTRIES
    # =====================================================

    if state == "admin_countries":

        if text == "0":

            set_user_state(
                chat_id,
                "admin_menu"
            )

            send_message(
                chat_id,
                admin_menu()
            )

            return

        send_message(
            chat_id,
            country_list()
        )

        return


# =========================================================
#                    هندلر اصلی
# =========================================================

def handle_update(update):

    if isinstance(update, dict) and "chat_id" in update:
        chat_id = update.get("chat_id")
        text = str(update.get("text", "") or "").strip()
    else:
        extracted = extract_message(update)
        if not extracted:
            return
        chat_id, text = extracted

    ensure_user(chat_id)

    user = get_user(chat_id)

    # /admin برای ورود
    if text == "/admin":

        set_user_state(
            chat_id,
            "admin_login"
        )

        send_message(
            chat_id,
            "👑 کد مدیریت را ارسال کنید:"
        )

        return

    # ورود ادمین باید قبل از بررسی is_admin انجام شود.
    if user and user["state"] == "admin_login":
        handle_admin(chat_id, text)
        return

    # ادمین
    if user and user["is_admin"]:

        handle_admin(
            chat_id,
            text
        )

        return

    # بات خاموش باشد، فقط ادمین اجازه کار دارد
    if not is_enabled("bot_enabled"):

        send_message(
            chat_id,
            "🔴 Infinity War در حال حاضر خاموش است."
        )

        return

    handle_user(
        chat_id,
        text
    )


# =========================================================
#                 ارسال بیانیه با اکانت
# =========================================================

async def _download_media_with_retry(message, retries=2, base_delay=1.0):
    """
    برخی نسخه‌های SPlusthon هنگام دانلود مدیا خطای
    RPCError 422: FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER
    می‌دهند، چون درخواست فایل روی کانکشن اصلی پیام‌ها ارسال شده
    نه کانکشن اختصاصی فایل. این یک باگ مسیر اتصال در خود کتابخانه است؛
    اینجا فقط چند بار با تاخیر کوتاه دوباره تلاش می‌کنیم تا اگر مشکل
    موقتی/رقابتی (race) باشد، دور زده شود.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return await message.download_media()
        except Exception as e:
            last_err = e
            is_conn_server_bug = "FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER" in str(e)
            try:
                print("MEDIA ERR DETAILS:", repr(e), "| dict:", getattr(e, "__dict__", None), "| dir:", [a for a in dir(e) if not a.startswith("_")])
                req = getattr(e, "request", None)
                if req is not None:
                    print("MEDIA ERR REQUEST:", repr(req), "| dict:", getattr(req, "__dict__", None))
            except Exception as debug_err:
                print("MEDIA ERR DEBUG PRINT FAILED:", repr(debug_err))
            if attempt < retries and (is_conn_server_bug or True):
                await asyncio.sleep(base_delay * attempt)
                continue
            raise last_err


async def _send_announcement(event):
    message = event.message
    chat_id = event.chat_id
    user = get_user(chat_id)
    if not user or user["country_id"] is None:
        set_user_state(chat_id, "main")
        await event.reply("❌ ابتدا باید وارد یک کشور شوید.\n\n" + main_menu())
        return
    country = get_country_by_id(user["country_id"])
    if not country:
        set_user_state(chat_id, "main")
        await event.reply("❌ کشور شما یافت نشد.\n\n" + main_menu())
        return
    if str(getattr(message, "message", "") or "").strip() == "0":
        set_user_state(chat_id, "main")
        await event.reply(main_menu())
        return
    text = str(getattr(message, "message", "") or "").strip()
    media = getattr(message, "media", None)
    header = announcement_tag(country["name"])
    prefix = f"{header}\n\n"
    suffix = f"\n\n𝐈𝐍𝐅𝐈𝐍𝐈𝐓𝐘 𝐖𝐀𝐑 | @{CHANNEL}"
    caption = prefix + text + suffix

    # حفظ بولد/نقل‌قول و سایر formatting entities پیام کاربر.
    # Offsetهای entity در پیام سروش بر اساس UTF-16 هستند.
    formatting_entities = getattr(message, "entities", None)
    if formatting_entities:
        try:
            shift = len(prefix.encode("utf-16-le")) // 2
            formatting_entities = [
                (lambda e: (setattr(e, "offset", int(getattr(e, "offset", 0)) + shift) or e))(copy.copy(e))
                for e in formatting_entities
            ]
        except Exception:
            formatting_entities = None

    try:
        file_path = None
        media_sent = False

        if media:
            # روش اول (بدون دانلود/آپلود): همون رفرنس مدیای موجود روی
            # سرور سروش رو مستقیم دوباره می‌فرستیم، دقیقاً شبیه فوروارد.
            # این اصلاً از مسیر GetFileRequest/SaveFilePart (جایی که باگ
            # FILE_REQUEST_RECEIVED_ON_CONNECTION_SERVER رخ می‌ده) رد نمیشه،
            # چون هیچ بایتی از فایل نه دانلود میشه نه آپلود — فقط یه
            # ارجاع (id/access_hash) به سرور پاس داده میشه.
            media_obj = (
                getattr(message, "photo", None)
                or getattr(message, "document", None)
                or media
            )
            try:
                try:
                    if formatting_entities:
                        sent_msg = await client.send_file(CHANNEL, media_obj, caption=caption, formatting_entities=formatting_entities)
                    else:
                        sent_msg = await client.send_file(CHANNEL, media_obj, caption=caption)
                except TypeError:
                    sent_msg = await client.send_file(CHANNEL, media_obj, caption=caption)
                media_sent = True

                # بعضی نسخه‌های splusthon هنگام دوباره‌فرستادن یه مدیای
                # موجود (بدون دانلود)، caption رو درست ضمیمه نمی‌کنن.
                # برای اطمینان، بلافاصله متن پیام رو صریح ویرایش می‌کنیم؛
                # edit_message هیچ ربطی به مسیر باگ‌دار فایل نداره.
                try:
                    sent_text = str(getattr(sent_msg, "message", "") or "")
                    if sent_msg and sent_text != caption:
                        if formatting_entities:
                            await client.edit_message(CHANNEL, sent_msg, text=caption, formatting_entities=formatting_entities)
                        else:
                            await client.edit_message(CHANNEL, sent_msg, text=caption)
                except Exception as edit_err:
                    print("CAPTION EDIT FAILED:", repr(edit_err))
            except Exception as reuse_err:
                print("MEDIA REUSE (no-download) FAILED:", repr(reuse_err))
                media_sent = False

        if not media_sent and media:
            # روش دوم (فال‌بک): دانلود و آپلود واقعی از طریق کلاینت
            # اختصاصی مدیا (اگه روش اول به هر دلیلی جواب نداد).
            try:
                mclient = await _ensure_media_client()
                fetched = await mclient.get_messages(chat_id, ids=message.id)
                media_message = fetched[0] if isinstance(fetched, list) else fetched
                if media_message:
                    file_path = await _download_media_with_retry(media_message)
            except Exception as dl_err:
                print("MEDIA DOWNLOAD FAILED, fallback to text-only:", repr(dl_err))
                file_path = None

            if file_path:
                try:
                    try:
                        if formatting_entities:
                            await mclient.send_file(CHANNEL, file_path, caption=caption, formatting_entities=formatting_entities)
                        else:
                            await mclient.send_file(CHANNEL, file_path, caption=caption)
                    except TypeError:
                        await mclient.send_file(CHANNEL, file_path, caption=caption)
                    media_sent = True
                except Exception as up_err:
                    print("MEDIA UPLOAD FAILED, fallback to text-only:", repr(up_err))
                    media_sent = False

        if not media_sent:
            # بدون مدیا، یا هیچ‌کدوم از دو روش بالا جواب نداد: فقط متن.
            try:
                if formatting_entities:
                    await client.send_message(CHANNEL, caption, formatting_entities=formatting_entities)
                else:
                    await client.send_message(CHANNEL, caption)
            except TypeError:
                await client.send_message(CHANNEL, caption)

        save_announcement(country["id"], chat_id, text)
        set_user_state(chat_id, "main")
        await event.reply("✅ بیانیه با موفقیت ارسال شد.\n\n" + main_menu())
    except Exception as e:
        print("ANNOUNCEMENT ERROR:", repr(e))
        await event.reply(
            "❌ ارسال بیانیه انجام نشد. دوباره تلاش کنید.\n\n"
            f"🛠 جزئیات خطا (موقت برای دیباگ): {type(e).__name__}: {e}"
        )


@client.on(events.NewMessage)
async def account_handler(event):
    try:
        # این اکانت روی همه‌ی پیام‌های همه‌ی چت‌هایی که عضوشونه گوش میده،
        # از جمله خودِ کانال بازی (چون بیانیه‌ها رو خودش اونجا پست می‌کنه).
        # بدون این فیلتر، وقتی یه پیام جدید توی کانال ظاهر میشه (حتی پست
        # خودِ ربات)، این هندلر اون رو مثل پیام یک «بازیکن» پردازش می‌کنه
        # و متن‌های منو/وضعیت (مثل «Infinity War خاموش است») رو با
        # send_message به همون چت_آیدی (که همون کانال باشه) پس می‌فرسته،
        # یعنی مستقیم توی کانال پابلیش میشه.
        # پس: پیام‌های خودِ اکانت (out) و هر چیزی که PV واقعی یک کاربر
        # نباشه (کانال/گروه/خودِ CHANNEL) اینجا نادیده گرفته میشه.
        if getattr(event, "out", False):
            return

        is_private = getattr(event, "is_private", None)
        if is_private is False:
            return

        chat_id = event.chat_id
        chat_username = None
        try:
            sender_chat = await event.get_chat()
            chat_username = getattr(sender_chat, "username", None)
        except Exception:
            chat_username = None

        if (
            str(chat_id) == str(CHANNEL)
            or (chat_username and str(chat_username).lstrip("@") == str(CHANNEL).lstrip("@"))
        ):
            return

        if is_private is None and (getattr(event, "is_channel", False) or getattr(event, "is_group", False)):
            return

        message = event.message
        text = str(getattr(message, "message", "") or "").strip()
        ensure_user(chat_id)
        user = get_user(chat_id)

        if user and user["state"] == "announcement":
            await _send_announcement(event)
            return

        # برای پیام‌های عادی، منطق قدیمی بازی بدون تغییر استفاده می‌شود.
        update = {"chat_id": chat_id, "text": text}
        handle_update(update)
    except Exception as e:
        print("EVENT ERROR:", repr(e))
        try:
            await event.reply("❌ یک خطا رخ داد. دوباره تلاش کنید.")
        except Exception:
            pass


# =========================================================
#      اجرای خودکار روی GitHub Actions (بدون سرور دائمی)
# =========================================================
# هر اجرا روی Actions زمان محدود داره؛ برای همین:
#  ۱) دیتابیس بازی (نه session) هر چند دقیقه خودکار کامیت/پوش میشه
#     تا بین اجراهای بعدی وضعیت بازی حفظ بشه.
#  ۲) بعد از RUNTIME_LIMIT_SECONDS ربات خودش تمیز خاموش میشه، قبل از
#     اینکه GitHub خودش با timeout جاب رو قطع کنه (که ممکنه وسط یه
#     نوشتن روی دیتابیس اتفاق بیفته و فایل رو خراب کنه).

RUNTIME_LIMIT_SECONDS = int(os.environ.get("RUNTIME_LIMIT_SECONDS", 5 * 3600 + 40 * 60))  # ۵ ساعت و ۴۰ دقیقه
DB_COMMIT_INTERVAL_SECONDS = int(os.environ.get("DB_COMMIT_INTERVAL_SECONDS", 5 * 60))  # هر ۵ دقیقه


GIT_TIMEOUT_SECONDS = 60  # حداکثر زمانی که هر دستور git تکی اجازه داره طول بکشه


def _run_git(*args, timeout=GIT_TIMEOUT_SECONDS):
    try:
        subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return True
    except subprocess.TimeoutExpired:
        print("GIT TIMEOUT:", args, "| after", timeout, "seconds")
        return False
    except subprocess.CalledProcessError as e:
        print("GIT ERROR:", args, "| stdout:", e.stdout, "| stderr:", e.stderr)
        return False


def commit_db(message="auto: update game db"):
    """فقط فایل دیتابیس بازی رو کامیت/پوش می‌کنه. session.txt هیچ‌وقت
    کامیت نمیشه (توی .gitignore هست).

    این تابع کاملاً synchronous/blocking هست (subprocess معمولی). هیچ‌وقت
    مستقیم توی event loop اصلی صداش نزن — همیشه از طریق commit_db_safe
    (که توی یه ترد جدا اجراش می‌کنه) استفاده کن، وگرنه اگه یکی از
    دستورهای git گیر کنه (مثلاً یه قطعی شبکه‌ی موقت)، کل ربات فریز
    می‌شه و دیگه هیچ پیامی جواب داده نمی‌شه."""
    if not os.path.exists(DB_NAME):
        return
    if not _run_git("add", DB_NAME):
        return
    try:
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print("GIT DIFF TIMEOUT")
        return
    if diff.returncode == 0:
        return  # چیزی تغییر نکرده، کامیت خالی نمی‌سازیم
    if _run_git("commit", "-m", message):
        if _run_git("push"):
            return
        # پوش رد شد (احتمالاً چون remote جلوتر از local رفته).
        # یه تلاش برای rebase روی آخرین نسخه‌ی remote و پوش دوباره:
        if _run_git("pull", "--rebase", "--autostash"):
            _run_git("push")
        else:
            print("GIT PUSH RETRY FAILED — تغییرات این دور کامیت محلی موندن، دفعه‌ی بعد دوباره تلاش میشه")


async def commit_db_safe(message="auto: update game db", overall_timeout=180):
    """نسخه‌ی امن برای صدا زدن از داخل event loop: commit_db رو توی یه
    ترد جدا اجرا می‌کنه (تا بلاک نشدن بقیه‌ی ربات) و یه سقف زمانی کلی
    هم روش می‌ذاره. اگه گیت بیش از حد طول بکشه یا گیر کنه، این فقط
    لاگ می‌کنه و برمی‌گرده، به‌جای اینکه ربات رو برای همیشه فریز کنه
    (باگی که قبلاً باعث می‌شد ربات بعد از یه گیرکردنِ push دیگه هیچ‌وقت
    خاموش/ری‌استارت نشه و تغییرات اخیر ذخیره نشن)."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(commit_db, message),
            timeout=overall_timeout,
        )
    except asyncio.TimeoutError:
        print(f"COMMIT DB OVERALL TIMEOUT after {overall_timeout}s")
    except Exception as e:
        print("COMMIT DB ERROR:", repr(e))


async def _auto_commit_loop():
    while True:
        await asyncio.sleep(DB_COMMIT_INTERVAL_SECONDS)
        await commit_db_safe()


async def _self_shutdown_after(seconds):
    await asyncio.sleep(seconds)
    print(f"⏱ زمان {seconds} ثانیه تموم شد — در حال خاموش کردن تمیز ربات...")
    await commit_db_safe("auto: final db save before shutdown", overall_timeout=120)
    try:
        await asyncio.wait_for(client.disconnect(), timeout=30)
    except Exception as e:
        print("DISCONNECT ERROR:", repr(e))


def print_startup_state():
    """چاپ وضعیت پول و تجهیزات همه‌ی کشورها موقع روشن شدن ربات،
    فقط برای دیباگ کردن مشکل ریست شدن تجهیزات/بودجه بعد از ری‌استارت.
    این لاگ‌ها فقط تو تب Actions دیده میشن و روی خود بازی اثری ندارن."""
    try:
        conn = db()
        countries = conn.execute(
            "SELECT id, name, money, daily_profit FROM countries ORDER BY id"
        ).fetchall()

        print("=" * 60)
        print("STARTUP STATE CHECK — این‌ها همون مقادیری هستن که ربات")
        print("همین الان، تازه از db خونده:")
        print("=" * 60)

        for c in countries:
            equip_rows = conn.execute(
                "SELECT code, amount FROM equipment WHERE country_id=? AND amount>0",
                (c["id"],)
            ).fetchall()

            if c["money"] == 20000 and not equip_rows:
                # این کشور دقیقاً مقدار پیش‌فرض اولیه رو داره — یعنی
                # یا واقعاً هیچ‌وقت توش بازی نشده، یا (اگه قبلاً توش
                # خرید انجام شده بود) ریست شده به حالت اولیه.
                continue

            equip_str = ", ".join(
                f"{r['code']}={r['amount']}" for r in equip_rows
            ) or "بدون تجهیزات"

            print(
                f"[{c['id']}] {c['name']} | money={c['money']} | "
                f"daily_profit={c['daily_profit']} | equipment: {equip_str}"
            )

        print("=" * 60)
        conn.close()
    except Exception as e:
        print("STARTUP STATE CHECK ERROR:", repr(e))


def merge_duplicate_country(dup_id, main_id):
    """یک‌بارمصرف: هرچی پول/تجهیزات روی رکورد تکراریِ dup_id هست رو
    منتقل می‌کنه به رکورد اصلیِ main_id، بعد رکورد تکراری رو پاک می‌کنه.
    اگه dup_id از قبل وجود نداشته باشه (چون قبلاً پاک شده)، کاری نمی‌کنه."""
    conn = db()

    dup = conn.execute("SELECT * FROM countries WHERE id=?", (dup_id,)).fetchone()
    if not dup:
        conn.close()
        return

    conn.execute(
        "UPDATE countries SET money = money + ? WHERE id=?",
        (dup["money"], main_id)
    )

    dup_equip = conn.execute(
        "SELECT code, amount FROM equipment WHERE country_id=?", (dup_id,)
    ).fetchall()

    for row in dup_equip:
        conn.execute("""
            INSERT INTO equipment (country_id, code, name, category, amount)
            SELECT ?, code, name, category, ?
            FROM equipment WHERE country_id=? AND code=?
            ON CONFLICT(country_id, code)
            DO UPDATE SET amount = amount + excluded.amount
        """, (main_id, row["amount"], dup_id, row["code"]))

    conn.execute("DELETE FROM equipment WHERE country_id=?", (dup_id,))
    conn.execute("DELETE FROM countries WHERE id=?", (dup_id,))

    conn.commit()
    conn.close()
    print(f"MERGE: کشور تکراری [{dup_id}] با موفقیت داخل [{main_id}] ادغام و حذف شد.")


def merge_all_duplicate_countries():
    """محافظ خودکار: هر بار ربات روشن میشه چک می‌کنه آیا به هر دلیلی
    (مثلاً همون مشکل قبلیِ push گیت‌هاب) دو تا رکورد برای یک کشور
    ساخته شده یا نه. اگه پیدا کرد، پول و تجهیزات رکوردهای تکراری رو
    داخل قدیمی‌ترین رکورد (کوچیک‌ترین id) ادغام می‌کنه و رکوردهای
    اضافه رو پاک می‌کنه — بدون نیاز به دخالت دستی."""

    conn = db()
    rows = conn.execute(
        "SELECT id, name FROM countries ORDER BY id"
    ).fetchall()
    conn.close()

    by_name = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row["id"])

    for name, ids in by_name.items():
        if len(ids) > 1:
            main_id = min(ids)
            for dup_id in ids:
                if dup_id != main_id:
                    merge_duplicate_country(dup_id, main_id)
                    print(
                        f"AUTO-MERGE: کشور تکراری «{name}» "
                        f"[{dup_id}] با موفقیت داخل [{main_id}] ادغام شد."
                    )


async def main():
    init_db()
    merge_all_duplicate_countries()
    print_startup_state()
    await client.start()
    try:
        new_session = client.session.save()
        if new_session:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                f.write(new_session)
    except Exception as e:
        print("SESSION SAVE ERROR:", repr(e))
    print("Infinity War is running without bot token...")

    asyncio.create_task(_auto_commit_loop())
    asyncio.create_task(_self_shutdown_after(RUNTIME_LIMIT_SECONDS))

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
