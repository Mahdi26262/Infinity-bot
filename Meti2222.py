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
#                  Soor War Bot
# =========================================================

DB_NAME = "infinity_war.db"
CHANNEL = "Soorwar"

# برای گزارش‌گیری خودکار AI (خبر جهانی هر ۱۰ بیانیه + تحلیل آمار هر ۳
# ساعت). مقدارش از GitHub Secret به‌نام OPENAI_API_KEY خونده میشه.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

# اگه GROQ_API_KEY تنظیم شده باشه، اولویت با Groq (رایگان) هست؛
# وگرنه از OpenAI استفاده میشه (اگه کلیدش تنظیم شده باشه).
if GROQ_API_KEY:
    AI_API_KEY = GROQ_API_KEY
    AI_MODEL = GROQ_MODEL
    AI_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
else:
    AI_API_KEY = OPENAI_API_KEY
    AI_MODEL = OPENAI_MODEL
    AI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
IRAN_OFFSET = timedelta(hours=3, minutes=30)

# برای debounce پیام وضعیت آنلاین/آفلاین تو کانال (فقط اگه ۱۵ دقیقه
# پایدار موند، پست بشه؛ تغییرات سریع/پشت‌سرهم نادیده گرفته میشن).
_status_toggle_token = 0
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


ADMIN_CODE = "SORMETI"
UN_PANEL_CODE = "SMSOR"
STARTING_MONEY = 0

# 🧪 تست موقت: وقتی True باشه، فقط کد کشور واگنر اجازه‌ی ورود داره
# (کد ادمین جداست و تحت تأثیر این فلگ نیست). برای برگردوندن به حالت
# عادی و باز شدن همه‌ی کشورها، این رو False کن.
TEST_MODE_ONLY_WAGNER = False

TOMAN_CONTACT = "@Meettiiiii"


# =========================================================
#                     کشورها
# =========================================================

COUNTRIES = {
    "USANV4GX": ("آمریکا", "🇺🇸"),
    "RUSTHA4N": ("روسیه", "🇷🇺"),
    "CHNFHXKP": ("چین", "🇨🇳"),
    "GBRCHSZ5": ("بریتانیا", "🇬🇧"),
    "FRAGD2JW": ("فرانسه", "🇫🇷"),
    "GERKDC2S": ("آلمان", "🇩🇪"),
    "IND8LKKQ": ("هند", "🇮🇳"),
    "JPNX9N25": ("ژاپن", "🇯🇵"),
    "KORPFE3F": ("کره جنوبی", "🇰🇷"),
    "TUR8VAWU": ("ترکیه", "🇹🇷"),
    "IRNN2LVH": ("ایران", "🇮🇷"),
    "SAUF5674": ("عربستان", "🇸🇦"),
    "ISRJRGVW": ("اسرائیل", "🇮🇱"),
    "PAKC5ER4": ("پاکستان", "🇵🇰"),
    "IDNJ2C4R": ("اندونزی", "🇮🇩"),
    "EGYDSUBX": ("مصر", "🇪🇬"),
    "UAEG7EF5": ("امارات", "🇦🇪"),
    "POL2G678": ("لهستان", "🇵🇱"),
    "UKRWPV5S": ("اوکراین", "🇺🇦"),
    "CANSUB7Y": ("کانادا", "🇨🇦"),
    "BRAC9J9V": ("برزیل", "🇧🇷"),
    "ARGSKK3F": ("آرژانتین", "🇦🇷"),
    "ITAQPAXJ": ("ایتالیا", "🇮🇹"),
    "ESPMX3PS": ("اسپانیا", "🇪🇸"),
    "NLD8WJAA": ("هلند", "🇳🇱"),
    "AUSZ7YTB": ("استرالیا", "🇦🇺"),
    "MEX7TYW9": ("مکزیک", "🇲🇽"),
    "WAGZ3SAP": ("واگنر", "🏴‍☠️"),
    "CENTM753": ("سنتکام", "🦅"),
    "SAVDYGV2": ("ساواک", "☠️"),
}

ENGLISH_NAMES = {
    "USANV4GX": "United States",
    "RUSTHA4N": "Russia",
    "CHNFHXKP": "China",
    "GBRCHSZ5": "United Kingdom",
    "FRAGD2JW": "France",
    "GERKDC2S": "Germany",
    "IND8LKKQ": "India",
    "JPNX9N25": "Japan",
    "KORPFE3F": "South Korea",
    "TUR8VAWU": "Turkey",
    "IRNN2LVH": "Iran",
    "SAUF5674": "Saudi Arabia",
    "ISRJRGVW": "Israel",
    "PAKC5ER4": "Pakistan",
    "IDNJ2C4R": "Indonesia",
    "EGYDSUBX": "Egypt",
    "UAEG7EF5": "UAE",
    "POL2G678": "Poland",
    "UKRWPV5S": "Ukraine",
    "CANSUB7Y": "Canada",
    "BRAC9J9V": "Brazil",
    "ARGSKK3F": "Argentina",
    "ITAQPAXJ": "Italy",
    "ESPMX3PS": "Spain",
    "NLD8WJAA": "Netherlands",
    "AUSZ7YTB": "Australia",
    "MEX7TYW9": "Mexico",
    "WAGZ3SAP": "Wagner",
    "CENTM753": "CENTCOM",
    "SAVDYGV2": "SAVAK",
}

NEGOTIATION_COUNTRY_ORDER = [
    "USANV4GX", "RUSTHA4N", "CHNFHXKP", "GBRCHSZ5", "FRAGD2JW", "GERKDC2S", 
    "IND8LKKQ", "JPNX9N25", "KORPFE3F", "TUR8VAWU", "IRNN2LVH", "SAUF5674", 
    "ISRJRGVW", "PAKC5ER4", "IDNJ2C4R", "EGYDSUBX", "UAEG7EF5", "POL2G678", 
    "UKRWPV5S", "CANSUB7Y", "BRAC9J9V", "ARGSKK3F", "ITAQPAXJ", "ESPMX3PS", 
    "NLD8WJAA", "AUSZ7YTB", "MEX7TYW9", 
]

NEWS_TAGS = {
    "آمریکا": "🇺🇸 United States | American Press",
    "روسیه": "🇷🇺 Russia | Moscow Report",
    "چین": "🇨🇳 China | China Daily",
    "بریتانیا": "🇬🇧 United Kingdom | London News",
    "فرانسه": "🇫🇷 France | France Press",
    "آلمان": "🇩🇪 Germany | Berlin Journal",
    "هند": "🇮🇳 India | India Today",
    "ژاپن": "🇯🇵 Japan | Tokyo News",
    "کره جنوبی": "🇰🇷 South Korea | Seoul Press",
    "ترکیه": "🇹🇷 Turkey | Ankara Report",
    "ایران": "🇮🇷 Iran | Iran Press",
    "عربستان": "🇸🇦 Saudi Arabia | Saudi Press",
    "اسرائیل": "🇮🇱 Israel | Jerusalem Post",
    "پاکستان": "🇵🇰 Pakistan | Pakistan News",
    "اندونزی": "🇮🇩 Indonesia | Jakarta Report",
    "مصر": "🇪🇬 Egypt | Cairo News",
    "امارات": "🇦🇪 UAE | Emirates Press",
    "لهستان": "🇵🇱 Poland | Warsaw Journal",
    "اوکراین": "🇺🇦 Ukraine | Kyiv Report",
    "کانادا": "🇨🇦 Canada | Canadian Press",
    "برزیل": "🇧🇷 Brazil | Brasil News",
    "آرژانتین": "🇦🇷 Argentina | Buenos Aires Press",
    "ایتالیا": "🇮🇹 Italy | Rome Journal",
    "اسپانیا": "🇪🇸 Spain | Madrid News",
    "هلند": "🇳🇱 Netherlands | Dutch Press",
    "استرالیا": "🇦🇺 Australia | Australia Report",
    "مکزیک": "🇲🇽 Mexico | Mexico Journal",
    "واگنر": "🏴‍☠️ Wagner | Wagner Press",
    "سنتکام": "🦅 CENTCOM | Military Brief",
    "ساواک": "☠️ SAVAK | Intelligence Report",
}

# رهبر / عنوان و نام سمت حکومتی / وزیر خارجه / عنوان و نام فرمانده
LEADERS = {
    "آمریکا": {"leader": "دونالد ترامپ", "gov_title": "رئیس جمهور", "gov_name": "دونالد ترامپ", "fm": "مارکو روبیو", "cmd_title": "رئیس کل قوا", "cmd_name": "دونالد ترامپ"},
    "روسیه": {"leader": "ولادیمیر پوتین", "gov_title": "رئیس جمهور", "gov_name": "ولادیمیر پوتین", "fm": "سرگئی لاوروف", "cmd_title": "رئیس کل قوا", "cmd_name": "ولادیمیر پوتین"},
    "چین": {"leader": "شی جین‌پینگ", "gov_title": "رئیس جمهور", "gov_name": "شی جین‌پینگ", "fm": "وانگ یی", "cmd_title": "رئیس کل قوا", "cmd_name": "شی جین‌پینگ"},
    "بریتانیا": {"leader": "اندی برنهام", "gov_title": "نخست وزیر", "gov_name": "اندی برنهام", "fm": "اد میلیبند", "cmd_title": "رئیس کل قوا", "cmd_name": "پادشاه چارلز سوم"},
    "فرانسه": {"leader": "امانوئل مکرون", "gov_title": "رئیس جمهور", "gov_name": "امانوئل مکرون", "fm": "ژان نوئل بارو", "cmd_title": "رئیس کل قوا", "cmd_name": "امانوئل مکرون"},
    "آلمان": {"leader": "فریدریش مرتس", "gov_title": "صدراعظم", "gov_name": "فریدریش مرتس", "fm": "یوهان ویدفول", "cmd_title": "وزیر دفاع", "cmd_name": "بوریس پیستوریوس"},
    "هند": {"leader": "نارندرا مودی", "gov_title": "نخست وزیر", "gov_name": "نارندرا مودی", "fm": "سوبرامانیام جایشانکار", "cmd_title": "رئیس کل قوا", "cmd_name": "دروپادی مورمو"},
    "ژاپن": {"leader": "سانائه تاکائیچی", "gov_title": "نخست وزیر", "gov_name": "سانائه تاکائیچی", "fm": "توشیمیتسو موتگی", "cmd_title": "وزیر دفاع", "cmd_name": "شینجیرو کویزومی"},
    "کره جنوبی": {"leader": "لی جه میونگ", "gov_title": "رئیس جمهور", "gov_name": "لی جه میونگ", "fm": "چو هیون", "cmd_title": "وزیر دفاع", "cmd_name": "آن گیو بک"},
    "ترکیه": {"leader": "رجب طیب اردوغان", "gov_title": "رئیس جمهور", "gov_name": "رجب طیب اردوغان", "fm": "هاکان فیدان", "cmd_title": "وزیر دفاع", "cmd_name": "یاشار گولر"},
    "ایران": {"leader": "مجتبی خامنه‌ای", "gov_title": "رئیس جمهور", "gov_name": "مسعود پزشکیان", "fm": "عباس عراقچی", "cmd_title": "رئیس کل قوا", "cmd_name": "مجتبی خامنه‌ای"},
    "عربستان": {"leader": "محمد بن سلمان", "gov_title": "پادشاه", "gov_name": "سلمان بن عبدالعزیز", "fm": "فیصل بن فرحان", "cmd_title": "رئیس کل قوا", "cmd_name": "محمد بن سلمان"},
    "اسرائیل": {"leader": "بنیامین نتانیاهو", "gov_title": "نخست وزیر", "gov_name": "بنیامین نتانیاهو", "fm": "گیدئون ساعر", "cmd_title": "رئیس ستاد ارتش", "cmd_name": "ایال زمیر"},
    "پاکستان": {"leader": "شهباز شریف", "gov_title": "نخست وزیر", "gov_name": "شهباز شریف", "fm": "اسحاق دار", "cmd_title": "رئیس کل قوا", "cmd_name": "آصف علی زرداری"},
    "اندونزی": {"leader": "پرابوو سوبیانتو", "gov_title": "رئیس جمهور", "gov_name": "پرابوو سوبیانتو", "fm": "سوجیونو", "cmd_title": "رئیس کل قوا", "cmd_name": "پرابوو سوبیانتو"},
    "مصر": {"leader": "عبدالفتاح السیسی", "gov_title": "رئیس جمهور", "gov_name": "عبدالفتاح السیسی", "fm": "بدر عبدالعاطی", "cmd_title": "رئیس کل قوا", "cmd_name": "عبدالفتاح السیسی"},
    "امارات": {"leader": "محمد بن زاید آل نهیان", "gov_title": "رئیس جمهور", "gov_name": "محمد بن زاید آل نهیان", "fm": "عبدالله بن زاید آل نهیان", "cmd_title": "رئیس کل قوا", "cmd_name": "محمد بن زاید آل نهیان"},
    "لهستان": {"leader": "دونالد توسک", "gov_title": "نخست وزیر", "gov_name": "دونالد توسک", "fm": "رادوسواف سیکورسکی", "cmd_title": "رئیس کل قوا", "cmd_name": "کارول ناوروتسکی"},
    "اوکراین": {"leader": "ولودیمیر زلنسکی", "gov_title": "رئیس جمهور", "gov_name": "ولودیمیر زلنسکی", "fm": "آندری سیبیها", "cmd_title": "فرمانده کل نیروهای مسلح", "cmd_name": "الکساندر سیرسکی"},
    "کانادا": {"leader": "مارک کارنی", "gov_title": "نخست وزیر", "gov_name": "مارک کارنی", "fm": "آنیتا آناند", "cmd_title": "رئیس کل قوا", "cmd_name": "پادشاه چارلز سوم"},
    "برزیل": {"leader": "لوئیز ایناسیو لولا داسیلوا", "gov_title": "رئیس جمهور", "gov_name": "لوئیز ایناسیو لولا داسیلوا", "fm": "مائورو ویرا", "cmd_title": "رئیس کل قوا", "cmd_name": "لوئیز ایناسیو لولا داسیلوا"},
    "آرژانتین": {"leader": "خاویر میلی", "gov_title": "رئیس جمهور", "gov_name": "خاویر میلی", "fm": "خراردو ورتهاین", "cmd_title": "رئیس کل قوا", "cmd_name": "خاویر میلی"},
    "ایتالیا": {"leader": "جورجیا ملونی", "gov_title": "نخست وزیر", "gov_name": "جورجیا ملونی", "fm": "آنتونیو تاجانی", "cmd_title": "رئیس کل قوا", "cmd_name": "سرجیو ماتارلا"},
    "اسپانیا": {"leader": "پدرو سانچز", "gov_title": "نخست وزیر", "gov_name": "پدرو سانچز", "fm": "خوزه مانوئل آلبارس", "cmd_title": "رئیس کل قوا", "cmd_name": "فیلیپه ششم"},
    "هلند": {"leader": "دیک شوف", "gov_title": "نخست وزیر", "gov_name": "دیک شوف", "fm": "کاسپار ولدکمپ", "cmd_title": "رئیس کل قوا", "cmd_name": "ویلم الکساندر"},
    "استرالیا": {"leader": "آنتونی آلبانیزی", "gov_title": "نخست وزیر", "gov_name": "آنتونی آلبانیزی", "fm": "پنی وانگ", "cmd_title": "رئیس کل قوا", "cmd_name": "پادشاه چارلز سوم"},
    "مکزیک": {"leader": "کلودیا شینباوم", "gov_title": "رئیس جمهور", "gov_name": "کلودیا شینباوم", "fm": "خوان رامون د لا فوئنته", "cmd_title": "رئیس کل قوا", "cmd_name": "کلودیا شینباوم"},
    "واگنر": {"leader": "الکساندر سولودکوف", "gov_title": "رئیس", "gov_name": "الکساندر سولودکوف", "fm": "—", "cmd_title": "فرمانده کل", "cmd_name": "—"},
    "سنتکام": {"leader": "—", "gov_title": "فرمانده سنتکام", "gov_name": "—", "fm": "—", "cmd_title": "فرمانده نیروها", "cmd_name": "—"},
    "ساواک": {"leader": "—", "gov_title": "رئیس ساواک", "gov_name": "—", "fm": "—", "cmd_title": "فرمانده نیروها", "cmd_name": "—"},
}


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
    add_column_if_missing(conn, "loans", "reminder_sent", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "code_version", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "users", "joined_code_version", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "gov_title", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "countries", "commander_title", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "countries", "faction_host_id", "INTEGER")
    add_column_if_missing(conn, "countries", "leader_status", "TEXT DEFAULT 'زنده'")
    add_column_if_missing(conn, "countries", "gov_status", "TEXT DEFAULT 'زنده'")
    add_column_if_missing(conn, "countries", "fm_status", "TEXT DEFAULT 'زنده'")
    add_column_if_missing(conn, "countries", "commander_status", "TEXT DEFAULT 'زنده'")
    add_column_if_missing(conn, "countries", "negotiation_status", "TEXT DEFAULT 'زنده'")
    add_column_if_missing(conn, "countries", "sanction_economic_pct", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "countries", "sanction_locked_categories", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "countries", "sanction_reason", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "inventions", "created_at", "TEXT DEFAULT ''")

    # کشورها
    # نکته‌ی مهم: چک می‌کنیم کشور با این «اسم» از قبل وجود داره یا نه،
    # نه با «کد». چون اگه بر اساس کد چک کنیم، وقتی ادمین کد یه کشور رو
    # از پنل ادمین عوض می‌کنه، کد اصلی و قدیمی دیگه تو دیتابیس نیست،
    # و دفعه‌ی بعد که ربات روشن بشه، این حلقه فکر می‌کنه اون کشور اصلاً
    # وجود نداشته و یه رکورد کاملاً جدید و تکراری براش می‌سازه (همون
    # باگ «کشور تکراری» که قبلاً می‌دیدیم). چک کردن با اسم، این مشکل
    # رو برای همیشه حل می‌کنه چون اسم کشور هیچ‌وقت توسط ادمین عوض نمیشه.
    for code, data in COUNTRIES.items():

        name, flag = data

        already_exists = conn.execute(
            "SELECT id FROM countries WHERE name=?", (name,)
        ).fetchone()

        if already_exists:
            continue

        l = LEADERS.get(name, {})

        conn.execute("""
            INSERT OR IGNORE INTO countries
            (code, name, flag, money, approval,
             leader, gov_title, president, foreign_minister,
             commander_title, commander, negotiation_team)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code,
            name,
            flag,
            STARTING_MONEY,
            100,
            l.get("leader", "—"),
            l.get("gov_title", "رئیس جمهور"),
            l.get("gov_name", "—"),
            l.get("fm", "—"),
            l.get("cmd_title", "رئیس کل قوا"),
            l.get("cmd_name", "—"),
            "—",
        ))

    # تنظیمات پیش‌فرض
    defaults = {
        "bot_enabled": "1",
        "un_ai_enabled": "0",
        "un_ai_difficulty": "عادی",
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
    return f"{int(value):,} CS"


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
    if TEST_MODE_ONLY_WAGNER and code != "WAGZ3SAP":
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

    country = conn.execute(
        "SELECT code_version FROM countries WHERE id=?", (country_id,)
    ).fetchone()

    conn.execute("""
        UPDATE users
        SET country_id=?, state='main', temp_data='', joined_code_version=?
        WHERE user_id=?
    """, (
        country_id,
        country["code_version"] if country else 0,
        str(user_id)
    ))

    conn.commit()
    conn.close()


def submitted_today(table, country_id):
    """چک می‌کنه آیا این کشور امروز (بر اساس تاریخ سرور) از قبل تو این
    جدول (roles یا inventions) یک ردیف با created_at امروز ثبت کرده یا نه.
    برای محدودیت «روزی فقط ۱ درخواست» استفاده میشه."""

    today = datetime.now().date().isoformat()

    conn = db()
    row = conn.execute(f"""
        SELECT COUNT(*) AS n
        FROM {table}
        WHERE country_id=?
          AND substr(created_at, 1, 10)=?
    """, (country_id, today)).fetchone()
    conn.close()

    return row["n"] > 0


async def _delayed_status_post(token, is_online):
    """۱۵ دقیقه صبر می‌کنه؛ اگه تا اون موقع وضعیت دوباره toggle نشده
    باشه (یعنی token هنوز جدیدترینه)، وضعیت رو تو کانال پست می‌کنه."""

    await asyncio.sleep(900)  # ۱۵ دقیقه

    global _status_toggle_token
    if token != _status_toggle_token:
        return  # یه توگل جدیدتر اتفاق افتاده، این یکی منقضی شده

    status_text = (
        "🔺بات همه‌کاره اینفینیتی وار\n\n"
        "وضعیت : Online🟢"
        if is_online else
        "🔺بات همه‌کاره اینفینیتی وار\n\n"
        "وضعیت : Offline🔴"
    )

    try:
        await client.send_message(CHANNEL, status_text)
    except Exception as e:
        print("STATUS POST ERROR:", repr(e))


def schedule_status_post(is_online):
    global _status_toggle_token
    _status_toggle_token += 1
    asyncio.create_task(
        _delayed_status_post(_status_toggle_token, is_online)
    )


def iran_time_str():
    return (datetime.utcnow() + IRAN_OFFSET).strftime("%H:%M")


def _ask_chatgpt_sync(system_prompt, user_prompt):
    """درخواست synchronous (بلاک‌کننده) به سرویس هوش مصنوعی (Groq یا
    OpenAI، هرکدوم که کلیدش تنظیم شده باشه). هیچ‌وقت مستقیم توی event
    loop اصلی صداش نزن — همیشه از طریق asyncio.to_thread تا ربات وسط
    این درخواست فریز نشه."""
    if not AI_API_KEY:
        return None
    try:
        resp = requests.post(
            AI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 900,
                "temperature": 0.7,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("CHATGPT ERROR:", repr(e))
        return None


async def summarize_last_announcements(batch_size=10):
    """آخرین batch_size تا بیانیه رو می‌خونه، با ChatGPT یه گزارش خبری
    ازشون می‌سازه (به سبک خبرگزاری، طبق فرمت توافق‌شده) و تو کانال
    بازی پست می‌کنه."""

    conn = db()
    rows = conn.execute("""
        SELECT a.*, c.name, c.flag
        FROM announcements a
        JOIN countries c
        ON c.id=a.country_id
        ORDER BY a.id DESC
        LIMIT ?
    """, (batch_size,)).fetchall()
    conn.close()

    if not rows:
        return

    rows = list(reversed(rows))  # ترتیب زمانی درست، قدیمی به جدید

    prompt = "بیانیه‌های اخیر کشورهای مختلف:\n\n"
    for row in rows:
        prompt += f"— {row['flag']} {row['name']}:\n{row['text']}\n\n"

    system = (
        "تو خبرنگار رسمی خبرگزاری جهانی بازی جنگی «Soor War» هستی. "
        "بر اساس بیانیه‌های رسمی‌ای که کشورهای مختلف داده‌ن، یه گزارش خبری "
        "کامل و روان به فارسی بنویس. قوانین سختگیرانه:\n"
        "- فقط از محتوای واقعی همین بیانیه‌ها استفاده کن؛ هیچ اتفاق، اتحاد "
        "یا تصمیمی که توی بیانیه‌ها نیومده رو اختراع نکن.\n"
        "- پرچم و اسم دقیق هر کشور رو همون‌طور که تو ورودی اومده به کار "
        "ببر، حدس نزن.\n"
        "- طول متن باید متناسب با محتوای واقعی باشه — نه کوتاه‌تر از "
        "چیزی که هست، نه با آب‌بندی و تکرار طولانی‌ترش کن.\n"
        "- لحن باید خبری، روایی و پیوسته باشه (نه فهرست بولت‌وار خشک).\n\n"
        "دقیقاً از این قالب استفاده کن (فقط بخش‌های داخل [] رو خودت "
        "بر اساس بیانیه‌ها پر کن، بقیه رو عیناً همین‌طور بنویس):\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌍 𝐒𝐎𝐎𝐑 𝐖𝐀𝐑 | 𝐖𝐎𝐑𝐋𝐃 𝐍𝐄𝐖𝐒\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📰 [یه تیتر جذاب و خبری، برگرفته از مهم‌ترین اتفاق این بیانیه‌ها]\n\n"
        "[۱ خط مقدمه‌ی کلی راجع به فضای این دوره]\n\n"
        "[روایت پیوسته و خبری از اتفاقات، به ترتیب اهمیت، با ذکر پرچم و "
        "اسم دقیق هر کشور، شامل هر گونه تنش/تهدید/اختلاف، هر گونه "
        "پیشنهاد اتحاد/مذاکره/آشتی، و هر تصمیم یا موضع مهمی که یه کشور "
        "اعلام کرده]\n\n"
        "🔴 جمع‌بندی: [۲-۳ خط جمع‌بندی و این‌که این تحولات چه معنایی برای "
        "صف‌بندی قدرت‌ها تو دنیای Soor War داره]\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📰 𝐖𝐎𝐑𝐋𝐃 𝐍𝐄𝐖𝐒 📡 پوشش تحولات جهانی Soor War\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

    report = await asyncio.to_thread(_ask_chatgpt_sync, system, prompt)

    if not report:
        print("CHATGPT SUMMARY SKIPPED (no API key or request failed)")
        return

    try:
        await client.send_message(CHANNEL, report)
    except Exception as e:
        print("SUMMARY SEND ERROR:", repr(e))


async def _ai_stats_loop():
    """هر ۳ ساعت اطلاعات همه‌ی کشورها (پول، سود روزانه، تجهیزات) رو
    می‌فرسته به ChatGPT و ازش می‌خواد رتبه‌بندی ابرقدرت اقتصادی و
    نظامی بسازه؛ نتیجه رو کش می‌کنه تا پنل ادمین (گزینه‌ی آمار) نمایش
    بده، بدون این‌که هر بار که ادمین باز می‌کنه دوباره درخواست بزنه."""

    while True:

        try:
            conn = db()
            countries = conn.execute(
                "SELECT * FROM countries ORDER BY id"
            ).fetchall()

            lines = []
            for c in countries:
                equip_rows = conn.execute(
                    "SELECT code, amount FROM equipment "
                    "WHERE country_id=? AND amount>0",
                    (c["id"],)
                ).fetchall()

                equip_str = ", ".join(
                    f"{r['code']}={r['amount']}" for r in equip_rows
                ) or "بدون تجهیزات"

                lines.append(
                    f"{c['flag']} {c['name']}: پول={c['money']}, "
                    f"سود روزانه={c['daily_profit']}, تجهیزات: {equip_str}"
                )
            conn.close()

            prompt = "اطلاعات کشورها:\n\n" + "\n".join(lines)

            system = (
                "تو تحلیلگر اقتصادی-نظامی بازی Soor War هستی. بر اساس "
                "اطلاعات داده‌شده (پول، سود روزانه، و تجهیزات نظامی هر "
                "کشور)، دو تا رتبه‌بندی بساز. فقط کشورهایی که پول یا "
                "تجهیزات قابل‌توجهی دارن رو لیست کن؛ کشورهای کاملاً "
                "خالی/پیش‌فرض رو حذف کن. دقیقاً همین قالب رو رعایت کن، "
                "بدون هیچ توضیح اضافه قبل یا بعدش، و برای شماره‌گذاری "
                "دقیقاً از همین کاراکترهای دایره‌ای استفاده کن "
                "(① ② ③ ④ ⑤ ⑥ ⑦ ⑧ ⑨ ⑩ ...)، نه ایموجی رقم:\n\n"
                "💰 ابرقدرت‌های اقتصادی\n"
                "① [پرچم] [اسم] — [یک جمله‌ی کوتاه دلیل]\n"
                "② ...\n\n"
                "⚔️ ابرقدرت‌های نظامی\n"
                "① [پرچم] [اسم] — [یک جمله‌ی کوتاه دلیل]\n"
                "② ..."
            )

            result = await asyncio.to_thread(
                _ask_chatgpt_sync, system, prompt
            )

            if result:
                set_setting("ai_stats_text", result)
                set_setting("ai_stats_updated", iran_time_str())

        except Exception as e:
            print("AI STATS ERROR:", repr(e))

        await asyncio.sleep(3 * 3600)  # هر ۳ ساعت


# سطح سخت‌گیری AI سازمان ملل: توضیح متفاوت برای هر درجه
UN_DIFFICULTY_RULES = {
    "عادی": (
        "فقط بیانیه‌هایی که صریحاً و مستقیماً تهدید به حمله‌ی نظامی یا "
        "جنگ می‌کنن رو تهدیدآمیز در نظر بگیر. لحن تند دیپلماتیک یا "
        "انتقاد سیاسی تهدید حساب نمیشه."
    ),
    "متوسط": (
        "علاوه بر تهدید مستقیم، هشدارهای نسبتاً صریح یا اولتیماتوم‌های "
        "ضمنی علیه کشور دیگه رو هم تهدیدآمیز در نظر بگیر."
    ),
    "سخت": (
        "حتی لحن تند دیپلماتیک، هشدار غیرمستقیم، یا کنایه‌ی تهدیدآمیز "
        "رو هم تهدیدآمیز در نظر بگیر. سخت‌گیر باش."
    ),
}

UN_SANCTION_CATEGORIES = ["جنگنده‌ها", "بمب‌افکن‌ها", "موشکی", "دریایی", "اتمی"]


def _parse_ai_json(raw):
    if not raw:
        return None
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        return None


async def un_ai_check_announcement(country, text):
    """وقتی AI سازمان ملل روشنه، هر بیانیه‌ی جدید رو می‌خونه و تشخیص
    می‌ده تهدیدآمیزه یا نه. اگه تهدیدآمیز بود، خودکار تحریم اعمال
    می‌کنه و اطلاعیه رو تو کانال پست می‌کنه."""

    if not is_enabled("un_ai_enabled"):
        return

    difficulty = get_setting("un_ai_difficulty", "عادی")

    system = (
        "تو ناظر امنیتی سازمان ملل تو بازی جنگی «Soor War» هستی. "
        "وظیفه‌ات اینه که بیانیه‌ی رسمی یه کشور رو بخونی و تشخیص بدی "
        "تهدیدآمیزه یا صلح‌آمیز.\n\n"
        f"سطح سخت‌گیری فعلی: {difficulty}\n{UN_DIFFICULTY_RULES.get(difficulty, '')}\n\n"
        "خروجی رو فقط و فقط به این فرمت JSON بده، بدون هیچ توضیح اضافه:\n"
        '{"threat": true/false, "reason": "یک جمله‌ی کوتاه دلیل، به فارسی"}'
    )

    raw = await asyncio.to_thread(_ask_chatgpt_sync, system, text)
    data = _parse_ai_json(raw)

    if not data or not data.get("threat"):
        return

    reason = data.get("reason", "محتوای تهدیدآمیز")

    conn = db()
    conn.execute("""
        UPDATE countries
        SET sanction_locked_categories=?, sanction_reason=?
        WHERE id=?
    """, (",".join(UN_SANCTION_CATEGORIES), reason, country["id"]))
    conn.commit()
    conn.close()

    locked_text = "، ".join(UN_SANCTION_CATEGORIES)

    notice = (
        "🇺🇳 اطلاعیه رسمی سازمان ملل\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ کشور {country['flag']} {country['name']} به دلیل انتشار "
        "بیانیه‌ای با محتوای تهدیدآمیز، مشمول تحریم‌های سازمان ملل شد.\n\n"
        f"📋 دلیل: {reason}\n\n"
        "🔒 پیامدها:\n"
        f"• دسترسی به دسته‌های {locked_text} قفل شد\n\n"
        "🕊️ برای لغو تحریم، این کشور می‌تواند از منوی اصلی درخواست "
        "بخشش به سازمان ملل ارسال کند.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🇺🇳 UNITED NATIONS | Soor War"
    )

    try:
        await client.send_message(CHANNEL, notice)
    except Exception as e:
        print("UN SANCTION NOTICE ERROR:", repr(e))


async def un_ai_check_pardon(country, text):
    """بررسی درخواست بخشش یه کشور تحریم‌شده با AI سازمان ملل."""

    difficulty = get_setting("un_ai_difficulty", "عادی")

    pardon_rules = {
        "عادی": "هر عذرخواهی‌ی معقول و صادقانه رو بپذیر.",
        "متوسط": "عذرخواهی باید صریح باشه و بهانه‌تراشی نداشته باشه.",
        "سخت": "عذرخواهی باید صریح باشه و تعهد مشخص به عدم تکرار هم داشته باشه، وگرنه رد کن.",
    }

    system = (
        "تو داور سازمان ملل تو بازی جنگی «Soor War» هستی. یه کشور که "
        "قبلاً تحریم شده، الان یه بیانیه‌ی طلب بخشش فرستاده.\n\n"
        f"دلیل تحریم قبلی: {country['sanction_reason']}\n"
        f"سطح سخت‌گیری: {difficulty}\n{pardon_rules.get(difficulty, '')}\n"
        "اگه بیانیه‌ی جدید خودش دوباره تهدیدآمیز یا کنایه‌دار باشه، قطعاً رد کن.\n\n"
        "خروجی رو فقط و فقط به این فرمت JSON بده:\n"
        '{"pardoned": true/false, "message": "یک پیام کوتاه رسمی از طرف سازمان ملل، به فارسی"}'
    )

    raw = await asyncio.to_thread(_ask_chatgpt_sync, system, text)
    data = _parse_ai_json(raw) or {"pardoned": False, "message": "درخواست رد شد."}

    pardoned = bool(data.get("pardoned"))
    ai_message = data.get("message", "")

    if pardoned:

        conn = db()
        conn.execute("""
            UPDATE countries
            SET sanction_economic_pct=0, sanction_locked_categories='', sanction_reason=''
            WHERE id=?
        """, (country["id"],))
        conn.commit()
        conn.close()

        notice = (
            "🇺🇳 اطلاعیه رسمی سازمان ملل\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🕊️ درخواست بخشش کشور {country['flag']} {country['name']} "
            "بررسی و پذیرفته شد.\n\n"
            "✅ تمام تحریم‌های اعمال‌شده لغو گردید.\n\n"
            f"📋 {ai_message}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇺🇳 UNITED NATIONS | Soor War"
        )

    else:

        notice = (
            "🇺🇳 اطلاعیه رسمی سازمان ملل\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ درخواست بخشش کشور {country['flag']} {country['name']} "
            "بررسی شد اما پذیرفته نشد.\n\n"
            f"📋 {ai_message}\n\n"
            "⚠️ تحریم‌ها همچنان پابرجاست.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇺🇳 UNITED NATIONS | Soor War"
        )

    try:
        await client.send_message(CHANNEL, notice)
    except Exception as e:
        print("UN PARDON NOTICE ERROR:", repr(e))

    return pardoned


def send_to_country(country_id, text):
    """پیام رو به تمام کاربرانی که به این کشور وارد شدن می‌فرسته."""

    conn = db()
    rows = conn.execute(
        "SELECT user_id FROM users WHERE country_id=?", (country_id,)
    ).fetchall()
    conn.close()

    for row in rows:
        send_message(row["user_id"], text)


async def _loan_reminder_loop():
    """هر ساعت چک می‌کنه: اگه یک روز مونده به سررسید یه وام فعال باشه
    و قبلاً یادآوری نفرستاده باشیم، یه پیام به کشور می‌فرسته."""

    while True:

        try:
            conn = db()
            rows = conn.execute("""
                SELECT l.*, c.name, c.flag
                FROM loans l
                JOIN countries c ON c.id=l.country_id
                WHERE l.status='approved'
                  AND l.paid=0
                  AND l.reminder_sent=0
            """).fetchall()
            conn.close()

            now = datetime.now()

            for loan in rows:
                try:
                    due = datetime.fromisoformat(loan["due_date"])
                except Exception:
                    continue

                remaining = (due - now).total_seconds()

                if 0 <= remaining <= 86400:

                    send_to_country(
                        loan["country_id"],
                        "⏰ یادآوری وام\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "فقط ۱ روز تا سررسید وام شما مانده است.\n"
                        f"💳 مبلغ بازپرداخت: {money(loan['repayment'])}\n"
                        "لطفاً برای جلوگیری از جریمه، به‌موقع بازپرداخت را انجام دهید."
                    )

                    conn = db()
                    conn.execute(
                        "UPDATE loans SET reminder_sent=1 WHERE id=?",
                        (loan["id"],)
                    )
                    conn.commit()
                    conn.close()

        except Exception as e:
            print("LOAN REMINDER ERROR:", repr(e))

        await asyncio.sleep(3600)


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

    # ---------------- پایگاه‌ها ----------------

    {
        "code": "air_base",
        "name": "پایگاه هوایی",
        "category": "پایگاه‌ها",
        "price": 4000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "heli_base",
        "name": "پایگاه بالگردی",
        "category": "پایگاه‌ها",
        "price": 2500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "drone_base",
        "name": "پایگاه پهپادی",
        "category": "پایگاه‌ها",
        "price": 2500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "missile_base",
        "name": "پایگاه موشکی",
        "category": "پایگاه‌ها",
        "price": 4500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "defense_base",
        "name": "پایگاه پدافندی",
        "category": "پایگاه‌ها",
        "price": 3500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "ground_base",
        "name": "پایگاه زمینی",
        "category": "پایگاه‌ها",
        "price": 2000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "troop_base",
        "name": "پایگاه نیروهای زمینی",
        "category": "پایگاه‌ها",
        "price": 1500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "naval_base",
        "name": "پایگاه دریایی",
        "category": "پایگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "sub_base",
        "name": "پایگاه زیردریایی",
        "category": "پایگاه‌ها",
        "price": 6000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "cyber_base",
        "name": "مرکز سایبری",
        "category": "پایگاه‌ها",
        "price": 3000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "space_base",
        "name": "مرکز فضایی",
        "category": "پایگاه‌ها",
        "price": 7000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "weapons_factory",
        "name": "کارخانه تسلیحات",
        "category": "پایگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },

    # ---------------- درآمدزا ----------------

    {
        "code": "income_steel",
        "name": "کارخانه فولاد",
        "category": "درآمدزا",
        "price": 4000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 700,
    },
    {
        "code": "income_auto",
        "name": "کارخانه خودرو",
        "category": "درآمدزا",
        "price": 6000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 950,
    },
    {
        "code": "income_electronics",
        "name": "کارخانه لوازم الکترونیکی",
        "category": "درآمدزا",
        "price": 7000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1100,
    },
    {
        "code": "income_food",
        "name": "کارخانه مواد غذایی",
        "category": "درآمدزا",
        "price": 2500,
        "unit": 1,
        "max": 5,
        "requires": None,
        "daily_profit": 500,
    },
    {
        "code": "income_gas_plant",
        "name": "نیروگاه گازی",
        "category": "درآمدزا",
        "price": 4500,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 750,
    },
    {
        "code": "income_solar",
        "name": "نیروگاه خورشیدی",
        "category": "درآمدزا",
        "price": 3500,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 600,
    },
    {
        "code": "income_oil_refinery",
        "name": "پالایشگاه نفت",
        "category": "درآمدزا",
        "price": 8000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1300,
    },
    {
        "code": "income_petrochem",
        "name": "مجتمع پتروشیمی",
        "category": "درآمدزا",
        "price": 10000,
        "unit": 1,
        "max": 2,
        "requires": None,
        "daily_profit": 1600,
    },
    {
        "code": "income_iron_mine",
        "name": "معدن آهن",
        "category": "درآمدزا",
        "price": 1800,
        "unit": 1,
        "max": 5,
        "requires": None,
        "daily_profit": 400,
    },
    {
        "code": "income_copper_mine",
        "name": "معدن مس",
        "category": "درآمدزا",
        "price": 2800,
        "unit": 1,
        "max": 5,
        "requires": None,
        "daily_profit": 550,
    },
    {
        "code": "income_gold_mine",
        "name": "معدن طلا",
        "category": "درآمدزا",
        "price": 5000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 900,
    },
    {
        "code": "income_diamond_mine",
        "name": "معدن الماس",
        "category": "درآمدزا",
        "price": 7500,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1300,
    },
    {
        "code": "income_port",
        "name": "بندر تجاری",
        "category": "درآمدزا",
        "price": 6000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1000,
    },
    {
        "code": "income_trade_airport",
        "name": "فرودگاه تجاری",
        "category": "درآمدزا",
        "price": 7000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1100,
    },
    {
        "code": "income_logistics",
        "name": "مرکز لجستیک",
        "category": "درآمدزا",
        "price": 4000,
        "unit": 1,
        "max": 4,
        "requires": None,
        "daily_profit": 700,
    },
    {
        "code": "income_free_zone",
        "name": "منطقه آزاد تجاری",
        "category": "درآمدزا",
        "price": 8000,
        "unit": 1,
        "max": 3,
        "requires": None,
        "daily_profit": 1400,
    },

    # ---------------- موشکی ----------------

    {
        "code": "missile_short",
        "name": "موشک کوتاه‌برد",
        "category": "موشکی",
        "price": 100,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_tactical",
        "name": "موشک تاکتیکی",
        "category": "موشکی",
        "price": 120,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_ballistic_short",
        "name": "موشک بالستیک کوتاه‌برد",
        "category": "موشکی",
        "price": 150,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_cruise",
        "name": "موشک کروز",
        "category": "موشکی",
        "price": 180,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_antiship",
        "name": "موشک ضدکشتی",
        "category": "موشکی",
        "price": 200,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_gtg",
        "name": "موشک زمین‌به‌زمین",
        "category": "موشکی",
        "price": 220,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_eskandar",
        "name": "موشک اسکندر",
        "category": "موشکی",
        "price": 250,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_fateh110",
        "name": "موشک فاتح-۱۱۰",
        "category": "موشکی",
        "price": 280,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_fateh313",
        "name": "موشک فاتح-۳۱۳",
        "category": "موشکی",
        "price": 300,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_zolfaghar",
        "name": "موشک ذوالفقار",
        "category": "موشکی",
        "price": 350,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_dezful",
        "name": "موشک دزفول",
        "category": "موشکی",
        "price": 400,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_khorramshahr",
        "name": "موشک خرمشهر",
        "category": "موشکی",
        "price": 450,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_kalibr",
        "name": "موشک کالیبر",
        "category": "موشکی",
        "price": 350,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_tomahawk",
        "name": "موشک توماهاوک",
        "category": "موشکی",
        "price": 400,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_harpoon",
        "name": "موشک هارپون",
        "category": "موشکی",
        "price": 300,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_patriot_m",
        "name": "موشک پاتریوت",
        "category": "موشکی",
        "price": 350,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_s300_m",
        "name": "موشک اس-۳۰۰",
        "category": "موشکی",
        "price": 400,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_s400_m",
        "name": "موشک اس-۴۰۰",
        "category": "موشکی",
        "price": 450,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_thaad_m",
        "name": "موشک تاد",
        "category": "موشکی",
        "price": 500,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_kinzhal",
        "name": "موشک کینژال",
        "category": "موشکی",
        "price": 550,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_yars",
        "name": "موشک یارس",
        "category": "موشکی",
        "price": 600,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_minuteman3",
        "name": "موشک مینوتمن-۳",
        "category": "موشکی",
        "price": 650,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_trident2",
        "name": "موشک تریدنت-۲",
        "category": "موشکی",
        "price": 700,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },
    {
        "code": "missile_onyx",
        "name": "موشک اونیکس",
        "category": "موشکی",
        "price": 450,
        "unit": 1,
        "max": 200,
        "requires": "missile_base",
    },

    # ---------------- جنگنده‌ها ----------------

    {
        "code": "fighter_light",
        "name": "جنگنده سبک",
        "category": "جنگنده‌ها",
        "price": 800,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_multirole",
        "name": "جنگنده چندمنظوره",
        "category": "جنگنده‌ها",
        "price": 1000,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f5",
        "name": "اف-۵",
        "category": "جنگنده‌ها",
        "price": 1100,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f4",
        "name": "اف-۴",
        "category": "جنگنده‌ها",
        "price": 1200,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_mig29",
        "name": "میگ-۲۹",
        "category": "جنگنده‌ها",
        "price": 1400,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f16_n",
        "name": "اف-۱۶",
        "category": "جنگنده‌ها",
        "price": 1600,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f14",
        "name": "اف-۱۴",
        "category": "جنگنده‌ها",
        "price": 1800,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_mirage2000",
        "name": "میراژ ۲۰۰۰",
        "category": "جنگنده‌ها",
        "price": 1900,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_su27",
        "name": "سوخو-۲۷",
        "category": "جنگنده‌ها",
        "price": 2000,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f18",
        "name": "اف-۱۸",
        "category": "جنگنده‌ها",
        "price": 2200,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_rafale",
        "name": "رافال",
        "category": "جنگنده‌ها",
        "price": 2400,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_typhoon",
        "name": "یوروفایتر تایفون",
        "category": "جنگنده‌ها",
        "price": 2600,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f15",
        "name": "اف-۱۵",
        "category": "جنگنده‌ها",
        "price": 2800,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_su30",
        "name": "سوخو-۳۰",
        "category": "جنگنده‌ها",
        "price": 3000,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_su35_n",
        "name": "سوخو-۳۵",
        "category": "جنگنده‌ها",
        "price": 3200,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_j20",
        "name": "جی-۲۰",
        "category": "جنگنده‌ها",
        "price": 3400,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f35_n",
        "name": "اف-۳۵",
        "category": "جنگنده‌ها",
        "price": 3600,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_su57",
        "name": "سوخو-۵۷",
        "category": "جنگنده‌ها",
        "price": 3800,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_f22_n",
        "name": "اف-۲۲",
        "category": "جنگنده‌ها",
        "price": 4000,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },
    {
        "code": "fighter_gen6",
        "name": "جنگنده نسل ششم",
        "category": "جنگنده‌ها",
        "price": 5000,
        "unit": 1,
        "max": 250,
        "requires": "air_base",
    },

    # ---------------- سایبری ----------------

    {
        "code": "cyber_hacker_beginner",
        "name": "هکر مبتدی",
        "category": "سایبری",
        "price": 600,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_infiltration_team",
        "name": "تیم نفوذ سایبری",
        "category": "سایبری",
        "price": 900,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_network_infil",
        "name": "سامانه نفوذ شبکه",
        "category": "سایبری",
        "price": 1200,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_attack_system",
        "name": "سامانه حمله سایبری",
        "category": "سایبری",
        "price": 1500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_ops_center",
        "name": "مرکز عملیات سایبری",
        "category": "سایبری",
        "price": 2000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_ew_system",
        "name": "سامانه جنگ الکترونیک سایبری",
        "category": "سایبری",
        "price": 2500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_jamming",
        "name": "سامانه اختلال ارتباطی",
        "category": "سایبری",
        "price": 2800,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_adv_ops_unit",
        "name": "واحد عملیات سایبری پیشرفته",
        "category": "سایبری",
        "price": 3200,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_attack_network",
        "name": "شبکه حمله سایبری",
        "category": "سایبری",
        "price": 3600,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_command_center",
        "name": "مرکز فرماندهی سایبری",
        "category": "سایبری",
        "price": 4000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_antihacker",
        "name": "ضد هکر",
        "category": "سایبری",
        "price": 700,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_firewall_adv",
        "name": "دیواره آتش پیشرفته",
        "category": "سایبری",
        "price": 1000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_intrusion_detect",
        "name": "سامانه تشخیص نفوذ",
        "category": "سایبری",
        "price": 1300,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_network_protect",
        "name": "سامانه محافظت شبکه",
        "category": "سایبری",
        "price": 1600,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_defense_center",
        "name": "مرکز دفاع سایبری",
        "category": "سایبری",
        "price": 2000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_national_security",
        "name": "سامانه امنیت ملی",
        "category": "سایبری",
        "price": 2500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_defense_network",
        "name": "شبکه دفاع سایبری",
        "category": "سایبری",
        "price": 3000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_info_security_center",
        "name": "مرکز امنیت اطلاعات",
        "category": "سایبری",
        "price": 3500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_adv_defense_sys",
        "name": "سامانه دفاع سایبری پیشرفته",
        "category": "سایبری",
        "price": 4000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_national_shield",
        "name": "سپر سایبری ملی",
        "category": "سایبری",
        "price": 5000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_comm_satellite",
        "name": "ماهواره ارتباطی (سایبری)",
        "category": "سایبری",
        "price": 2500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_intel_center",
        "name": "مرکز اطلاعات سایبری",
        "category": "سایبری",
        "price": 2000,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_network_control",
        "name": "مرکز کنترل شبکه",
        "category": "سایبری",
        "price": 2800,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_secure_network",
        "name": "شبکه ارتباطی امن",
        "category": "سایبری",
        "price": 3200,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },
    {
        "code": "cyber_digital_command",
        "name": "مرکز فرماندهی دیجیتال",
        "category": "سایبری",
        "price": 4500,
        "unit": 1,
        "max": 150,
        "requires": "cyber_base",
    },

    # ---------------- پهپادها ----------------

    {
        "code": "drone_recon_light",
        "name": "پهپاد شناسایی سبک",
        "category": "پهپادها",
        "price": 300,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_patrol",
        "name": "پهپاد گشتی",
        "category": "پهپادها",
        "price": 350,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_recon_tactical",
        "name": "پهپاد شناسایی تاکتیکی",
        "category": "پهپادها",
        "price": 400,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_surveillance",
        "name": "پهپاد مراقبتی",
        "category": "پهپادها",
        "price": 450,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_combat_light",
        "name": "پهپاد رزمی سبک",
        "category": "پهپادها",
        "price": 500,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_mohajer",
        "name": "پهپاد مهاجر",
        "category": "پهپادها",
        "price": 600,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_shahed129",
        "name": "پهپاد شاهد-۱۲۹",
        "category": "پهپادها",
        "price": 700,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_shahed136_n",
        "name": "پهپاد شاهد-۱۳۶",
        "category": "پهپادها",
        "price": 550,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_tb2",
        "name": "پهپاد بیرقدار تی‌بی۲",
        "category": "پهپادها",
        "price": 750,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_akinci",
        "name": "پهپاد آکینجی",
        "category": "پهپادها",
        "price": 900,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_mq9",
        "name": "پهپاد ام‌کیو-۹ ریپر",
        "category": "پهپادها",
        "price": 1100,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_rq4",
        "name": "پهپاد آرکیو-۴ گلوبال هاوک",
        "category": "پهپادها",
        "price": 1200,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_hermes900",
        "name": "پهپاد هرمس-۹۰۰",
        "category": "پهپادها",
        "price": 1000,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_orlan10",
        "name": "پهپاد اورلان-۱۰",
        "category": "پهپادها",
        "price": 500,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_lancet",
        "name": "پهپاد لانست",
        "category": "پهپادها",
        "price": 450,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_recon_heavy",
        "name": "پهپاد شناسایی سنگین",
        "category": "پهپادها",
        "price": 800,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_combat_heavy",
        "name": "پهپاد رزمی سنگین",
        "category": "پهپادها",
        "price": 1200,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_kamikaze_adv",
        "name": "پهپاد انتحاری پیشرفته",
        "category": "پهپادها",
        "price": 700,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_ew",
        "name": "پهپاد جنگ الکترونیک",
        "category": "پهپادها",
        "price": 1400,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },
    {
        "code": "drone_c2",
        "name": "پهپاد فرماندهی و کنترل",
        "category": "پهپادها",
        "price": 1600,
        "unit": 1,
        "max": 800,
        "requires": "drone_base",
    },

    # ---------------- بمب‌افکن‌ها ----------------

    {
        "code": "bomber_light",
        "name": "بمب‌افکن سبک",
        "category": "بمب‌افکن‌ها",
        "price": 800,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_tactical",
        "name": "بمب‌افکن تاکتیکی",
        "category": "بمب‌افکن‌ها",
        "price": 1000,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_b1",
        "name": "بی-۱ لنسر",
        "category": "بمب‌افکن‌ها",
        "price": 1400,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_b2",
        "name": "بی-۲ اسپیریت",
        "category": "بمب‌افکن‌ها",
        "price": 2000,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_b52",
        "name": "بی-۵۲ استراتوفورترس",
        "category": "بمب‌افکن‌ها",
        "price": 1800,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_tu95",
        "name": "توپولف-۹۵",
        "category": "بمب‌افکن‌ها",
        "price": 1500,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_tu160",
        "name": "توپولف-۱۶۰",
        "category": "بمب‌افکن‌ها",
        "price": 2200,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_h6",
        "name": "اچ-۶",
        "category": "بمب‌افکن‌ها",
        "price": 1300,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_tu22m",
        "name": "توپولف-۲۲ام",
        "category": "بمب‌افکن‌ها",
        "price": 1600,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_su24",
        "name": "سوخو-۲۴",
        "category": "بمب‌افکن‌ها",
        "price": 1200,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_su34",
        "name": "سوخو-۳۴",
        "category": "بمب‌افکن‌ها",
        "price": 1400,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_mirage2000n",
        "name": "میراژ ۲۰۰۰ ان",
        "category": "بمب‌افکن‌ها",
        "price": 1500,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_f111",
        "name": "اف-۱۱۱",
        "category": "بمب‌افکن‌ها",
        "price": 1300,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_b17",
        "name": "بی-۱۷",
        "category": "بمب‌افکن‌ها",
        "price": 1000,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_b24",
        "name": "بی-۲۴",
        "category": "بمب‌افکن‌ها",
        "price": 1100,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },
    {
        "code": "bomber_strategic_heavy",
        "name": "بمب‌افکن استراتژیک سنگین",
        "category": "بمب‌افکن‌ها",
        "price": 2500,
        "unit": 1,
        "max": 120,
        "requires": "air_base",
    },

    # ---------------- مین و بمب‌ها ----------------

    {
        "code": "bomb_light",
        "name": "بمب سبک",
        "category": "مین و بمب‌ها",
        "price": 80,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_heavy",
        "name": "بمب سنگین",
        "category": "مین و بمب‌ها",
        "price": 120,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_explosive",
        "name": "بمب انفجاری",
        "category": "مین و بمب‌ها",
        "price": 150,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_guided",
        "name": "بمب هدایت‌شونده",
        "category": "مین و بمب‌ها",
        "price": 200,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_smart",
        "name": "بمب هوشمند",
        "category": "مین و بمب‌ها",
        "price": 250,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_cluster",
        "name": "بمب خوشه‌ای",
        "category": "مین و بمب‌ها",
        "price": 280,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_penetrator",
        "name": "بمب نفوذگر",
        "category": "مین و بمب‌ها",
        "price": 300,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_bunker_buster",
        "name": "بمب سنگرشکن",
        "category": "مین و بمب‌ها",
        "price": 350,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_standoff",
        "name": "بمب دورایستا",
        "category": "مین و بمب‌ها",
        "price": 400,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "bomb_super_heavy",
        "name": "بمب فوق‌سنگین",
        "category": "مین و بمب‌ها",
        "price": 500,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_light",
        "name": "مین زمینی سبک",
        "category": "مین و بمب‌ها",
        "price": 30,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_antitank",
        "name": "مین ضدتانک",
        "category": "مین و بمب‌ها",
        "price": 50,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_antivehicle",
        "name": "مین ضدخودرو",
        "category": "مین و بمب‌ها",
        "price": 60,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_naval",
        "name": "مین دریایی",
        "category": "مین و بمب‌ها",
        "price": 80,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_smart",
        "name": "مین هوشمند",
        "category": "مین و بمب‌ها",
        "price": 100,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_antiarmor",
        "name": "مین ضدزره",
        "category": "مین و بمب‌ها",
        "price": 120,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_defense_adv",
        "name": "مین دفاعی پیشرفته",
        "category": "مین و بمب‌ها",
        "price": 150,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_naval_adv",
        "name": "مین دریایی پیشرفته",
        "category": "مین و بمب‌ها",
        "price": 180,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_smart_adv",
        "name": "مین هوشمند پیشرفته",
        "category": "مین و بمب‌ها",
        "price": 220,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },
    {
        "code": "mine_heavy",
        "name": "مین سنگین",
        "category": "مین و بمب‌ها",
        "price": 250,
        "unit": 1,
        "max": 1000000,
        "requires": "weapons_factory",
    },

    # ---------------- اتمی ----------------

    {
        "code": "nuke_factory",
        "name": "کارخانه تسلیحات هسته‌ای",
        "category": "اتمی",
        "price": 20000,
        "unit": 1,
        "max": 2,
        "requires": "nuclear_license",
    },
    {
        "code": "nuke_bomb",
        "name": "بمب هسته‌ای راهبردی",
        "category": "اتمی",
        "price": 30000,
        "unit": 1,
        "max": 5,
        "requires": "nuke_factory",
    },

    # ---------------- دریایی ----------------

    {
        "code": "navy_patrol_boat",
        "name": "قایق گشتی",
        "category": "دریایی",
        "price": 500,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_speedboat",
        "name": "قایق تندرو",
        "category": "دریایی",
        "price": 700,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_corvette_light",
        "name": "ناوچه سبک",
        "category": "دریایی",
        "price": 1200,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_corvette_adv",
        "name": "ناوچه پیشرفته",
        "category": "دریایی",
        "price": 1500,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_corvette_class",
        "name": "کوروت",
        "category": "دریایی",
        "price": 1800,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_destroyer_n",
        "name": "ناوشکن",
        "category": "دریایی",
        "price": 2500,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_destroyer_adv",
        "name": "ناوشکن پیشرفته",
        "category": "دریایی",
        "price": 3000,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_sub_diesel",
        "name": "زیردریایی دیزلی",
        "category": "دریایی",
        "price": 2000,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_sub_adv",
        "name": "زیردریایی پیشرفته",
        "category": "دریایی",
        "price": 3000,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_supply_ship",
        "name": "کشتی تدارکاتی",
        "category": "دریایی",
        "price": 1000,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_command_ship",
        "name": "کشتی فرماندهی",
        "category": "دریایی",
        "price": 2500,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_support_ship",
        "name": "کشتی پشتیبانی",
        "category": "دریایی",
        "price": 1500,
        "unit": 1,
        "max": 200,
        "requires": "naval_base",
    },
    {
        "code": "navy_destroyer_burke",
        "name": "ناوشکن آرلی برک",
        "category": "دریایی",
        "price": 3500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_destroyer_zumwalt",
        "name": "ناوشکن زوموالت",
        "category": "دریایی",
        "price": 4000,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_battleship",
        "name": "رزم‌ناو",
        "category": "دریایی",
        "price": 3500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_sub_nuclear",
        "name": "زیردریایی اتمی",
        "category": "دریایی",
        "price": 5000,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_sub_virginia",
        "name": "زیردریایی کلاس ویرجینیا",
        "category": "دریایی",
        "price": 5500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_helicopter_carrier",
        "name": "ناو بالگردبر",
        "category": "دریایی",
        "price": 4500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_carrier",
        "name": "ناو هواپیمابر",
        "category": "دریایی",
        "price": 7000,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_carrier_ford_n",
        "name": "ناو هواپیمابر جرالد آر. فورد",
        "category": "دریایی",
        "price": 9000,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_carrier_lincoln_n",
        "name": "ناو هواپیمابر آبراهام لینکلن",
        "category": "دریایی",
        "price": 8500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },
    {
        "code": "navy_amphibious_ship",
        "name": "کشتی آبی-خاکی",
        "category": "دریایی",
        "price": 3500,
        "unit": 1,
        "max": 10,
        "requires": "naval_base",
    },

    # ---------------- نیروی انسانی ----------------

    {
        "code": "troop_conscript",
        "name": "سرباز وظیفه",
        "category": "نیروی انسانی",
        "price": 1,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_trained",
        "name": "نیروی پیاده آموزش‌دیده",
        "category": "نیروی انسانی",
        "price": 2,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_heavy",
        "name": "سرباز سنگین",
        "category": "نیروی انسانی",
        "price": 3,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_rifleman",
        "name": "تیرانداز",
        "category": "نیروی انسانی",
        "price": 3,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_border",
        "name": "نیروی مرزی",
        "category": "نیروی انسانی",
        "price": 4,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_recon",
        "name": "نیروی شناسایی",
        "category": "نیروی انسانی",
        "price": 5,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_mountain",
        "name": "نیروی کوهستان",
        "category": "نیروی انسانی",
        "price": 6,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_desert",
        "name": "نیروی بیابانی",
        "category": "نیروی انسانی",
        "price": 6,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_marine",
        "name": "تفنگدار دریایی",
        "category": "نیروی انسانی",
        "price": 7,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_airborne",
        "name": "نیروی هوابرد",
        "category": "نیروی انسانی",
        "price": 8,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_commando",
        "name": "کماندو",
        "category": "نیروی انسانی",
        "price": 9,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_special",
        "name": "نیروی ویژه",
        "category": "نیروی انسانی",
        "price": 12,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_engineer",
        "name": "مهندس نظامی",
        "category": "نیروی انسانی",
        "price": 7,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_medic",
        "name": "پزشک نظامی",
        "category": "نیروی انسانی",
        "price": 6,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_drone_operator",
        "name": "اپراتور پهپاد",
        "category": "نیروی انسانی",
        "price": 8,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_field_officer",
        "name": "افسر میدانی",
        "category": "نیروی انسانی",
        "price": 20,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_unit_commander",
        "name": "فرمانده یگان",
        "category": "نیروی انسانی",
        "price": 35,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },
    {
        "code": "troop_senior_commander",
        "name": "فرمانده ارشد",
        "category": "نیروی انسانی",
        "price": 60,
        "unit": 5,
        "max": 1000000,
        "requires": "troop_base",
    },

    # ---------------- بالگردها ----------------

    {
        "code": "heli_light",
        "name": "هلیکوپتر سبک",
        "category": "بالگردها",
        "price": 450,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_transport",
        "name": "هلیکوپتر ترابری",
        "category": "بالگردها",
        "price": 600,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_recon",
        "name": "هلیکوپتر شناسایی",
        "category": "بالگردها",
        "price": 700,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_attack_light",
        "name": "هلیکوپتر تهاجمی سبک",
        "category": "بالگردها",
        "price": 800,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_mi8",
        "name": "هلیکوپتر میل-۸",
        "category": "بالگردها",
        "price": 900,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_apache",
        "name": "هلیکوپتر آپاچی",
        "category": "بالگردها",
        "price": 1200,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_cobra",
        "name": "هلیکوپتر کبرا",
        "category": "بالگردها",
        "price": 1000,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_blackhawk",
        "name": "هلیکوپتر بلک هاوک",
        "category": "بالگردها",
        "price": 1100,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_chinook",
        "name": "هلیکوپتر چینوک",
        "category": "بالگردها",
        "price": 1300,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_ka52",
        "name": "هلیکوپتر کاموف-۵۲",
        "category": "بالگردها",
        "price": 1400,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_mi28",
        "name": "هلیکوپتر میل-۲۸",
        "category": "بالگردها",
        "price": 1300,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_tiger",
        "name": "هلیکوپتر تایگر",
        "category": "بالگردها",
        "price": 1500,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_ka27",
        "name": "هلیکوپتر کا-۲۷",
        "category": "بالگردها",
        "price": 1200,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_heavy",
        "name": "هلیکوپتر سنگین",
        "category": "بالگردها",
        "price": 1600,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },
    {
        "code": "heli_attack_adv",
        "name": "هلیکوپتر تهاجمی پیشرفته",
        "category": "بالگردها",
        "price": 1800,
        "unit": 1,
        "max": 250,
        "requires": "heli_base",
    },

    # ---------------- پدافند هوایی ----------------

    {
        "code": "defense_short",
        "name": "پدافند کوتاه‌برد",
        "category": "پدافند هوایی",
        "price": 300,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_antidrone",
        "name": "پدافند ضدپهپاد",
        "category": "پدافند هوایی",
        "price": 400,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_mid",
        "name": "پدافند میان‌برد",
        "category": "پدافند هوایی",
        "price": 600,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_long",
        "name": "پدافند بردبلند",
        "category": "پدافند هوایی",
        "price": 900,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_hawk",
        "name": "پدافند هاوک",
        "category": "پدافند هوایی",
        "price": 1000,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_patriot",
        "name": "پدافند پاتریوت",
        "category": "پدافند هوایی",
        "price": 1400,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_s300",
        "name": "پدافند اس-۳۰۰",
        "category": "پدافند هوایی",
        "price": 1600,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_s400",
        "name": "پدافند اس-۴۰۰",
        "category": "پدافند هوایی",
        "price": 2000,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_thaad",
        "name": "پدافند تاد",
        "category": "پدافند هوایی",
        "price": 2200,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_arrow",
        "name": "پدافند ارو",
        "category": "پدافند هوایی",
        "price": 2500,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_iron_dome",
        "name": "پدافند گنبد آهنین",
        "category": "پدافند هوایی",
        "price": 1800,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_david_sling",
        "name": "پدافند فلاخن داوود",
        "category": "پدافند هوایی",
        "price": 2000,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_laser",
        "name": "پدافند لیزری",
        "category": "پدافند هوایی",
        "price": 2800,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },
    {
        "code": "defense_missile_adv",
        "name": "پدافند موشکی پیشرفته",
        "category": "پدافند هوایی",
        "price": 3000,
        "unit": 1,
        "max": 150,
        "requires": "defense_base",
    },

    # ---------------- پناهگاه‌ها ----------------

    {
        "code": "shelter_small",
        "name": "پناهگاه کوچک",
        "category": "پناهگاه‌ها",
        "price": 500,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_urban",
        "name": "پناهگاه شهری",
        "category": "پناهگاه‌ها",
        "price": 900,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_military",
        "name": "پناهگاه نظامی",
        "category": "پناهگاه‌ها",
        "price": 1500,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_reinforced",
        "name": "پناهگاه تقویت‌شده",
        "category": "پناهگاه‌ها",
        "price": 2000,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_underground",
        "name": "پناهگاه زیرزمینی",
        "category": "پناهگاه‌ها",
        "price": 2800,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_command",
        "name": "پناهگاه فرماندهی",
        "category": "پناهگاه‌ها",
        "price": 3500,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_national",
        "name": "پناهگاه ملی",
        "category": "پناهگاه‌ها",
        "price": 4500,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_ultra",
        "name": "پناهگاه فوق‌مقاوم",
        "category": "پناهگاه‌ها",
        "price": 6000,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_underground_adv",
        "name": "پناهگاه زیرزمینی پیشرفته",
        "category": "پناهگاه‌ها",
        "price": 7500,
        "unit": 1,
        "max": 30,
        "requires": None,
    },
    {
        "code": "shelter_complex",
        "name": "مجتمع پناهگاهی",
        "category": "پناهگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 30,
        "requires": None,
    },

    # ---------------- تانک‌ها ----------------

    {
        "code": "tank_light",
        "name": "تانک سبک",
        "category": "تانک‌ها",
        "price": 700,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_recon",
        "name": "تانک شناسایی",
        "category": "تانک‌ها",
        "price": 800,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_support",
        "name": "تانک پشتیبانی",
        "category": "تانک‌ها",
        "price": 900,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_t55",
        "name": "تی-۵۵",
        "category": "تانک‌ها",
        "price": 1000,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_t72",
        "name": "تی-۷۲",
        "category": "تانک‌ها",
        "price": 1200,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_t80",
        "name": "تی-۸۰",
        "category": "تانک‌ها",
        "price": 1400,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_t90",
        "name": "تی-۹۰",
        "category": "تانک‌ها",
        "price": 1600,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_leopard2",
        "name": "لئوپارد ۲",
        "category": "تانک‌ها",
        "price": 1800,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_challenger2",
        "name": "چلنجر ۲",
        "category": "تانک‌ها",
        "price": 1900,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_abrams",
        "name": "آبرامز M1A2",
        "category": "تانک‌ها",
        "price": 2100,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_leclerc",
        "name": "لکلرک",
        "category": "تانک‌ها",
        "price": 2000,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_merkava",
        "name": "مرکاوا",
        "category": "تانک‌ها",
        "price": 2000,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_k2",
        "name": "کی۲ بلک پنتر",
        "category": "تانک‌ها",
        "price": 2200,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_type99",
        "name": "تایپ ۹۹",
        "category": "تانک‌ها",
        "price": 1700,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },
    {
        "code": "tank_newgen",
        "name": "تانک نسل جدید",
        "category": "تانک‌ها",
        "price": 2500,
        "unit": 1,
        "max": 250,
        "requires": "ground_base",
    },

    # ---------------- فرودگاه‌ها ----------------

    {
        "code": "airport_small_strip",
        "name": "باند پرواز کوچک",
        "category": "فرودگاه‌ها",
        "price": 800,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_regional",
        "name": "فرودگاه منطقه‌ای",
        "category": "فرودگاه‌ها",
        "price": 1500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_military",
        "name": "فرودگاه نظامی",
        "category": "فرودگاه‌ها",
        "price": 2500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_advanced",
        "name": "فرودگاه هوایی پیشرفته",
        "category": "فرودگاه‌ها",
        "price": 3500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_big_base",
        "name": "پایگاه هوایی بزرگ",
        "category": "فرودگاه‌ها",
        "price": 5000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_international",
        "name": "فرودگاه بین‌المللی",
        "category": "فرودگاه‌ها",
        "price": 6500,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_military_big",
        "name": "فرودگاه نظامی بزرگ",
        "category": "فرودگاه‌ها",
        "price": 8000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_strategic",
        "name": "پایگاه هوایی راهبردی",
        "category": "فرودگاه‌ها",
        "price": 10000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_ultra",
        "name": "فرودگاه فوق‌پیشرفته",
        "category": "فرودگاه‌ها",
        "price": 13000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },
    {
        "code": "airport_national_complex",
        "name": "مجتمع هوایی ملی",
        "category": "فرودگاه‌ها",
        "price": 16000,
        "unit": 1,
        "max": 1,
        "requires": None,
    },

    # ---------------- ماهواره‌ها ----------------

    {
        "code": "sat_comm",
        "name": "ماهواره ارتباطی",
        "category": "ماهواره‌ها",
        "price": 1500,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_weather",
        "name": "ماهواره هواشناسی",
        "category": "ماهواره‌ها",
        "price": 1800,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_navigation",
        "name": "ماهواره ناوبری",
        "category": "ماهواره‌ها",
        "price": 2200,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_imaging",
        "name": "ماهواره تصویربرداری",
        "category": "ماهواره‌ها",
        "price": 2500,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_earth_observe",
        "name": "ماهواره رصد زمین",
        "category": "ماهواره‌ها",
        "price": 3000,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_recon",
        "name": "ماهواره شناسایی",
        "category": "ماهواره‌ها",
        "price": 3500,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_early_warning",
        "name": "ماهواره هشدار زودهنگام",
        "category": "ماهواره‌ها",
        "price": 4000,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_advanced",
        "name": "ماهواره پیشرفته",
        "category": "ماهواره‌ها",
        "price": 5000,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_network",
        "name": "شبکه ماهواره‌ای",
        "category": "ماهواره‌ها",
        "price": 7000,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },
    {
        "code": "sat_control_center",
        "name": "مرکز کنترل ماهواره",
        "category": "ماهواره‌ها",
        "price": 6000,
        "unit": 1,
        "max": 10,
        "requires": "space_base",
    },

    # ---------------- رضایت مردمی ----------------

    {
        "code": "happy_rec_center",
        "name": "مرکز تفریحی شهری",
        "category": "رضایت مردمی",
        "price": 1200,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 5,
    },
    {
        "code": "happy_sports",
        "name": "مجموعه ورزشی",
        "category": "رضایت مردمی",
        "price": 1500,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 7,
    },
    {
        "code": "happy_hospital",
        "name": "بیمارستان عمومی",
        "category": "رضایت مردمی",
        "price": 2000,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 9,
    },
    {
        "code": "happy_edu_center",
        "name": "مرکز آموزشی",
        "category": "رضایت مردمی",
        "price": 1500,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 7,
    },
    {
        "code": "happy_park",
        "name": "پارک شهری",
        "category": "رضایت مردمی",
        "price": 800,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 4,
    },
    {
        "code": "happy_social_center",
        "name": "مرکز خدمات اجتماعی",
        "category": "رضایت مردمی",
        "price": 1200,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 5,
    },
    {
        "code": "happy_transit",
        "name": "شبکه حمل‌ونقل عمومی",
        "category": "رضایت مردمی",
        "price": 2500,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 10,
    },
    {
        "code": "happy_culture_center",
        "name": "مرکز فرهنگی ملی",
        "category": "رضایت مردمی",
        "price": 2800,
        "unit": 1,
        "max": 20,
        "requires": None,
        "approval": 12,
    },
]


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

    if req in names:
        return names[req]

    item = get_item(req)
    if item:
        return item["name"]

    return req or ""


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

    # هر کد دیگه‌ای (مثل air_base، naval_base، weapons_factory، ...) رو
    # مستقیماً به‌عنوان کد یه آیتم/پایگاه در نظر می‌گیریم: کافیه کشور
    # حداقل ۱ دونه از اون آیتم داشته باشه.
    return has_base(country_id, req)


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

    for key, titem in TOMAN_ITEMS.items():

        profit = int(titem.get("profit", 0))

        if profit <= 0:
            continue

        total += get_toman_amount(country_id, key) * profit

    cap_bonus = get_toman_amount(country_id, "special_factory") * TOMAN_ITEMS["special_factory"]["cap_bonus"]
    daily_cap = 20000 + cap_bonus

    if total > daily_cap:
        total = daily_cap

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

    locked = (country["sanction_locked_categories"] or "").split(",")
    if item["category"] in locked:
        return False, (
            "🇺🇳 دسترسی به این دسته به‌دلیل تحریم سازمان ملل قفل شده است.\n"
            f"📋 دلیل تحریم: {country['sanction_reason'] or '—'}"
        )

    total_price = item["price"] * qty
    econ_pct = int(country["sanction_economic_pct"] or 0)
    if econ_pct:
        total_price = int(total_price * (100 + econ_pct) / 100)

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
        "🌍 𝐒𝐎𝐎𝐑 𝐖𝐀𝐑\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① 🏳️ کشور من\n"
        "② 🎒 تجهیزات من\n"
        "③ 🛒 فروشگاه\n"
        "④ 💳 پنل وام\n"
        "⑤ 🧪 اختراع\n"
        "⑥ 🎭 رول\n"
        "⑦ 💰 تجهیزات تومانی\n"
        "⑧ 📝 ارسال بیانیه\n"
        "⑨ 🤝 مذاکره\n"
        f"{number_sticker(10)} 🇺🇳 درخواست بخشش از سازمان ملل\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⓪ 🚪 خروج"
    )


FACTION_NAMES = {"واگنر", "سنتکام", "ساواک"}


def un_ai_menu():

    status = "🟢 روشن" if is_enabled("un_ai_enabled") else "🔴 خاموش"
    difficulty = get_setting("un_ai_difficulty", "عادی")

    return (
        "🇺🇳 مدیریت AI سازمان ملل\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت: {status}\n"
        f"سطح سخت‌گیری: {difficulty}\n\n"
        "① روشن / خاموش کردن\n"
        "② سطح: عادی\n"
        "③ سطح: متوسط\n"
        "④ سطح: سخت\n"
        "⓪ بازگشت"
    )


def admin_status_role_menu(country):

    text = (
        "① رهبر\n"
        "② " + country["gov_title"] + "\n"
        "③ وزیر خارجه\n"
        "④ " + country["commander_title"] + "\n"
        "⑤ تیم مذاکره\n"
    )

    if country["name"] in FACTION_NAMES:
        text += "⑥ گروهک ساکن\n"

    text += "⓪ بازگشت"

    return text


def status_icon(status):
    return "🟢" if status == "زنده" else "❓"


def approval_bar(pct):
    pct = max(0, min(100, int(pct)))
    filled = pct // 10
    return "█" * filled + "░" * (10 - filled)


def show_country(country):

    cid = country["id"]
    lines = []

    lines.append("◈━━━━━━━━━━━━━━━━━━━━◈")
    lines.append(f"      {country['flag']} {country['name']}")
    lines.append("◈━━━━━━━━━━━━━━━━━━━━◈")
    lines.append("")

    if country["name"] in FACTION_NAMES:
        host = get_country_by_id(country["faction_host_id"]) if country["faction_host_id"] else None
        host_text = f"مستقر در {host['flag']} {host['name']}" if host else "ندارد"
        lines.append(f"🪖 گروهک ساکن: {host_text}")
        lines.append("")

    lines.append("👑 هیئت حاکمه")
    lines.append("┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈")
    lines.append(f"🎖️ رهبر: {country['leader']} {status_icon(country['leader_status'])} {country['leader_status']}")
    lines.append(f"🏛️ {country['gov_title']}: {country['president']} {status_icon(country['gov_status'])} {country['gov_status']}")
    lines.append(f"🤝 وزیر خارجه: {country['foreign_minister']} {status_icon(country['fm_status'])} {country['fm_status']}")
    lines.append(f"⚔️ {country['commander_title']}: {country['commander']} {status_icon(country['commander_status'])} {country['commander_status']}")
    lines.append(f"🕊️ تیم مذاکره: {country['negotiation_team']} {status_icon(country['negotiation_status'])} {country['negotiation_status']}")
    lines.append("")

    approval = int(country["approval"]) + int(country["approval_bonus"] or 0)
    lines.append(f"❤️ رضایت مردمی: {approval}%")
    lines.append(approval_bar(approval))
    lines.append("")

    lines.append("🛡️ وضعیت امنیتی")
    conn = db()
    active_role = conn.execute(
        "SELECT role_text FROM roles WHERE country_id=? AND status='approved' ORDER BY id DESC LIMIT 1",
        (cid,)
    ).fetchone()
    lines.append(active_role["role_text"] if active_role else "رول امنیتی فعال نیست.")
    lines.append("")

    nuclear_status = (
        "دارای مجوز ساخت ✅" if int(country["nuclear_license"] or 0) else "فاقد مجوز ساخت ❌"
    )
    lines.append(f"☢️ برنامه هسته‌ای: {nuclear_status}")
    bomb_count = get_equipment(cid, "nuke_bomb")
    lines.append(f"🚫 تجهیزات هسته‌ای: {bomb_count if bomb_count else '—'}")
    lines.append("")

    inventions = conn.execute(
        "SELECT title FROM inventions WHERE country_id=? AND status='approved'",
        (cid,)
    ).fetchall()
    lines.append("🛠️ اختراعات ثبت‌شده:")
    lines.append(", ".join(r["title"] for r in inventions) if inventions else "—")
    lines.append("")

    income_rows = conn.execute(
        "SELECT code, amount FROM equipment WHERE country_id=? AND amount>0", (cid,)
    ).fetchall()
    conn.close()
    income_names = []
    for row in income_rows:
        it = get_item(row["code"])
        if it and it.get("category") == "درآمدزا":
            income_names.append(f"{it['name']} ×{row['amount']}")
    lines.append("💳 منابع درآمدی:")
    lines.append(", ".join(income_names) if income_names else "—")
    lines.append("")

    lines.append(f"💰 بودجه: {money(country['money'])}")
    lines.append(f"📈 سود روزانه: {money(country['daily_profit'])}")

    loan = active_loan(cid)
    if loan:
        try:
            due = datetime.fromisoformat(loan["due_date"])
            remaining_days = (due - datetime.now()).days
        except Exception:
            remaining_days = None
        remaining_label = (
            f"{remaining_days} روز"
            if isinstance(remaining_days, int) and remaining_days >= 0
            else "سررسید گذشته ⚠️"
        )
        lines.append(f"🏦 وام فعال: {money(loan['repayment'])} | باقی‌مانده: {remaining_label}")

    lines.append("◈━━━━━━━━━━━━━━━━━━━━◈")
    lines.append("⓪ بازگشت")

    return "\n".join(lines)


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
    i = 0

    for row in rows:

        if row["category"] != current_category:

            current_category = row["category"]

            text += (
                f"\n📂 {current_category}\n"
            )

        i += 1

        text += (
            f"{number_sticker(i)} {display_equipment_name(row['name'], row['category'])}: "
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
        "㉑", "㉒", "㉓", "㉔", "㉕",
    ]
    if 0 <= number < len(circled):
        return circled[number]
    return "\u2066(" + str(number) + ")\u2069"

CATEGORY_EMOJI = {
    "پهپادها": "🛸",
    "بمب‌افکن‌ها": "🛫",
    "بالگردها": "🚁",
    "مین و بمب‌ها": "🧨",
    "تانک‌ها": "🛡️",
    "جنگنده‌ها": "🛩️",
    "نیروی انسانی": "🪖",
    "پناهگاه‌ها": "🏠",
    "درآمدزا": "💰",
    "دریایی": "🚢",
    "رضایت مردمی": "❤️",
    "سایبری": "💻",
    "فرودگاه‌ها": "✈️",
    "پایگاه‌ها": "🏭",
    "اتمی": "☢️",
    "موشکی": "🚀",
    "پدافند هوایی": "📡",
    "ماهواره‌ها": "🛰️",
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
        "⓪ بازگشت"
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

    text += "⓪ بازگشت"

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
        "① خرید\n"
        "⓪ بازگشت"
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
        "⓪ بازگشت"
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
        "① خرید\n"
        "② لغو"
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
        "description": "📈 سود: ۲۰,۰۰۰ CS",
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
    "black_bank": {
        "name": "🏦 بانک سیاه",
        "price": 60000,
        "limit": 1,
        "profit": 15000,
        "description": "📈 سود: +۱۵,۰۰۰ CS",
    },
    "national_shield": {
        "name": "🛡️ سپر ملی",
        "price": 40000,
        "limit": 1,
        "profit": 0,
        "description": "🛡️ توانایی: دفاع خودکار در برابر حملات هوایی و موشکی",
    },
    "special_factory": {
        "name": "🏭 کارخانه ویژه",
        "price": 30000,
        "limit": 2,
        "profit": 0,
        "cap_bonus": 5000,
        "description": "💵 افزایش ۵,۰۰۰ به سقف درآمد روزانه (به سود اضافه نمی‌شود، فقط سقف را بیشتر می‌کند)",
    },
    "equipment_pack": {
        "name": "📦 بسته تجهیزات",
        "price": 20000,
        "limit": 10,
        "profit": 0,
        "description": "🎁 دریافت ۳ تا ۸ تجهیز تصادفی",
    },
}


def toman_menu():

    text = (
        "💰 تجهیزات تومانی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, (key, item) in enumerate(TOMAN_ITEMS.items(), 1):
        text += (
            f"{number_sticker(i)} {item['name']} = {toman(item['price'])}\n"
            f"   {item['description']}\n"
            f"   حداکثر: {item['limit']}\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "شماره تجهیز را ارسال کنید.\n"
        "⓪ بازگشت"
    )

    return text


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
        "⓪ بازگشت"
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
            "⓪ بازگشت"
        )

    return (
        "🏦 پنل وام\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① درخواست وام\n"
        "② وام من\n"
        "③ پرداخت وام\n"
        "⓪ بازگشت"
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
            "⓪ بازگشت"
        )

    return (
        "🧪 اختراعات\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① اختراع جدید\n"
        "② وضعیت اختراع\n"
        "③ اختراع من\n"
        "⓪ بازگشت"
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
        "① رول جدید\n"
        "② وضعیت رول\n"
        "③ رول‌های فعال\n"
        "⓪ بازگشت"
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
        return "🎭 رول فعال وجود ندارد.\n\n⓪ بازگشت"
    text = "🎭 رول‌های فعال\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows, 1):
        text += f"{number_sticker(i)} {row['flag']} {row['name']}\n💰 بودجه گرفته شده: {money(row['amount'])}\n\n"
    text += "⓪ بازگشت"
    return text


def admin_role_menu():
    status = "🟢 روشن" if is_enabled("role_enabled") else "🔴 خاموش"
    return (
        "🎭 مدیریت رول‌ها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت: {status}\n\n"
        "① رول‌های فعال\n"
        "② درخواست‌های رول\n"
        "③ روشن / خاموش کردن رول‌ها\n"
        "⓪ بازگشت"
    )


# =========================================================
#                      مذاکره (منو)
# =========================================================

def negotiation_menu():
    return (
        "🤝 مذاکره\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① مذاکره با یک کشور\n"
        "② مذاکره بین چند کشور\n"
        "③ وضعیت مذاکرات\n"
        "④ بایگانی\n"
        "⓪ بازگشت"
    )


def negotiation_country_list(prompt):
    text = f"{prompt}\n\n"
    for idx, code in enumerate(NEGOTIATION_COUNTRY_ORDER, start=1):
        name, flag = COUNTRIES[code]
        en = ENGLISH_NAMES[code]
        text += f"{number_sticker(idx)} {flag} {name} — {en}\n\n"
    text += "⓪ بازگشت"
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
        return "🤝 وضعیت مذاکرات\n━━━━━━━━━━━━━━━━━━━━━━\nهیچ مذاکره‌ای ثبت نشده.\n\n⓪ بازگشت"

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

    text += "⓪ بازگشت"
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
        return "🗂 بایگانی\n━━━━━━━━━━━━━━━━━━━━━━\nدرخواستی در انتظار پاسخ نیست.\n\n⓪ بازگشت"

    text = "🗂 بایگانی\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, r in enumerate(rows, start=1):
        req = get_country_by_id(r["requester_country_id"])
        text += f"{number_sticker(idx)} درخواست مذاکره از {req['flag']} {req['name']}\n"
    text += "\nشماره‌ی درخواست را ارسال کنید.\n⓪ بازگشت"
    return text


def negotiation_archive_respond_menu(neg_id, requester):
    return (
        f"شما یک درخواست مذاکره از کشور {requester['flag']} {requester['name']} دارید.\n\n"
        "① تایید\n"
        "② لغو\n"
        "⓪ بازگشت"
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
        "① بستن مذاکرات\n"
        "② باز کردن مذاکرات\n"
        "③ مذاکرات قبول‌شده\n"
        "⓪ بازگشت"
    )


def admin_negotiation_accepted_list():
    conn = db()
    rows = conn.execute("""
        SELECT * FROM negotiations WHERE status='accepted' ORDER BY id DESC
    """).fetchall()
    conn.close()

    if not rows:
        return "🤝 مذاکرات قبول‌شده\n━━━━━━━━━━━━━━━━━━━━━━\nهنوز مذاکره‌ای قبول نشده.\n\n⓪ بازگشت"

    text = "🤝 مذاکرات قبول‌شده\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for neg in rows:
        text += f"🔗 {neg['code']}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "⓪ بازگشت"
    return text


# =========================================================
#          مدیریت کد کشورها (ادمین)
# =========================================================

def admin_country_code_menu():
    return (
        "🔑 مدیریت کد کشورها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① عوض کردن کد کشور\n"
        "② کد کشورها\n"
        "⓪ بازگشت"
    )


def country_codes_list():
    conn = db()
    rows = conn.execute("SELECT * FROM countries ORDER BY name").fetchall()
    conn.close()
    text = "🔑 کد کشورها\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for c in rows:
        text += f"{c['flag']} {c['name']}: {c['code']}\n"
    text += "\n⓪ بازگشت"
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
        "⓪ بازگشت"
    )


def admin_approval_actions(country):
    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️ رضایت مردمی فعلی: {country['approval']}%\n\n"
        "① اضافه کردن رضایت مردمی\n"
        "② کم کردن رضایت مردمی\n"
        "⓪ بازگشت"
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
        "① تایید واریز\n⓪ بازگشت"
    )

def nuclear_license_menu():
    return ("☢️ مجوز اتم\n━━━━━━━━━━━━━━━━━━━━━━\n① دادن مجوز اتم\n② گرفتن مجوز اتم\n⓪ بازگشت")

def nuclear_license_country_menu(action):
    title = "دادن" if action == "grant" else "گرفتن"
    return f"☢️ {title} مجوز اتم\n━━━━━━━━━━━━━━━━━━━━━━\nکد کشور را ارسال کنید.\n⓪ بازگشت"

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
        "⓪ بازگشت"
    )

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
        return "📝 بیانیه های ارسالی\n━━━━━━━━━━━━━━━━━━━━━━\nهیچ بیانیه‌ای ثبت نشده است.\n\n⓪ بازگشت"
    out=f"📝 بیانیه های ارسالی — صفحه {page+1}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i,row in enumerate(rows,offset+1):
        out += f"\n{number_sticker(i)} کشور : {row['name']}\nمتن بیانیه:\n{row['text']}\n"
    out += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if offset+10 < total: out += "① صفحه بعد\n"
    if page>0: out += "② صفحه قبل\n"
    out += "⓪ بازگشت"
    return out

def admin_announcement_menu():
    return "📝 مدیریت بیانیه ها\n━━━━━━━━━━━━━━━━━━━━━━\n① بیانیه های ارسالی\n⓪ بازگشت"

def admin_shop_menu():
    status="🟢 روشن" if is_enabled("shop_enabled") else "🔴 خاموش"
    return f"🛒 مدیریت شاپ\n━━━━━━━━━━━━━━━━━━━━━━\nوضعیت شاپ: {status}\n\n① خاموش کردن شاپ\n② روشن کردن شاپ\n⓪ بازگشت"

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
        "① روشن / خاموش کردن بات\n"
        "② 💰 مدیریت بودجه\n"
        "③ 📈 مدیریت سود روزانه\n"
        "④ 🎒 مدیریت تجهیزات\n"
        "⑤ 🏦 مدیریت وام\n"
        "⑥ 🧪 مدیریت اختراعات\n"
        "⑦ 🎭 مدیریت رول‌ها\n"
        "⑧ 🌍 مدیریت کشورها\n"
        "⑨ 📊 آمار کلی\n"
        f"{number_sticker(10)} 💸 واریز سود روزانه\n"
        f"{number_sticker(11)} ☢️ مجوز اتم\n"
        f"{number_sticker(12)} 💰 مدیریت تجهیزات تومانی\n"
        f"{number_sticker(13)} 📝 مدیریت بیانیه ها\n"
        f"{number_sticker(14)} 🛒 مدیریت شاپ\n"
        f"{number_sticker(15)} 🔑 مدیریت کد کشورها\n"
        f"{number_sticker(16)} 🤝 مدیریت مذاکره\n"
        f"{number_sticker(17)} ❤️ مدیریت رضایت مردمی\n"
        f"{number_sticker(18)} 🧬 تغییر وضعیت کشورها\n"
        f"{number_sticker(19)} 🇺🇳 مدیریت AI سازمان ملل\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⓪ 🚪 خروج"
    )


def admin_budget_menu():

    return (
        "💰 مدیریت بودجه\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "کد کشور مورد نظر را ارسال کنید.\n"
        "⓪ بازگشت"
    )


def admin_budget_actions(country):

    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 بودجه فعلی: {money(country['money'])}\n\n"
        "① اضافه کردن بودجه\n"
        "② کم کردن بودجه\n"
        "⓪ بازگشت"
    )


def admin_profit_actions(country):

    return (
        f"{country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 سود روزانه فعلی: {money(country['daily_profit'])}\n\n"
        "① اضافه کردن سود روزانه\n"
        "② کم کردن سود روزانه\n"
        "⓪ بازگشت"
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
    text += f"\n❤️ رضایت مردمی: {c['approval']}%" + (f" (+{bonus})" if bonus else "") + "\n\n① اضافه کردن\n② کم کردن\n⓪ بازگشت"
    return text


def admin_toman_items(country_id, operation):
    text="💰 انتخاب تجهیزات تومانی\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i,(key,item) in enumerate(TOMAN_ITEMS.items(),1):
        text += f"{number_sticker(i)} {item['name']} — {get_toman_amount(country_id,key)}/{item['limit']}\n"
    return text+"\n⓪ بازگشت"

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
        "① اضافه کردن تجهیزات\n"
        "② کم کردن تجهیزات\n"
        "⓪ بازگشت"
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
        "⓪ بازگشت"
    )
    return text


def admin_category_items(category, country_id):
    items = items_in_category(category)
    text = f"🛒 {category}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, item in enumerate(items, 1):
        text += f"{number_sticker(i)} {display_equipment_name(item['name'], item['category'])} | موجودی: {get_equipment(country_id, item['code']):,}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\nشماره تجهیز را ارسال کنید.\n⓪ بازگشت"
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

    text += "⓪ بازگشت"

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


def ai_or_fallback_stats():

    cached = get_setting("ai_stats_text", "")

    if cached:

        updated = get_setting("ai_stats_updated", "")

        return (
            "📊 تحلیل هوش مصنوعی — Soor War\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{cached}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 آخرین به‌روزرسانی: ساعت {updated} (به وقت ایران)\n"
            "⓪ بازگشت"
        )

    # هنوز اولین تحلیل AI انجام نشده (یا کلید API تنظیم نشده) —
    # به‌عنوان جایگزین، نسخه‌ی الگوریتمی رو نشون بده.
    return global_stats()


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
        "📊 آمار کلی — Soor War\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 ابرقدرت‌های اقتصادی\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, country in enumerate(economic):

        medal = (
            medals[i]
            if i < 3
            else number_sticker(i + 1)
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
            else number_sticker(i + 1)
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

    text += "━━━━━━━━━━━━━━━━━━━━━━\n⓪ بازگشت"

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
        "① روشن کردن اختراع\n"
        "② خاموش کردن اختراع\n"
        "③ درخواست‌های اختراع\n"
        "④ حذف اختراع\n"
        "⓪ بازگشت"
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
        "① روشن کردن وام\n"
        "② خاموش کردن وام\n"
        "③ درخواست‌های وام\n"
        "④ وام‌های فعال\n"
        "⓪ بازگشت"
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
            "🌍 𝐒𝐎𝐎𝐑 𝐖𝐀𝐑\n"
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
                + "\n\n⓪ بازگشت"
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

        if text == "10":

            if not (country["sanction_locked_categories"] or country["sanction_economic_pct"]):
                send_message(chat_id, "✅ کشور شما در حال حاضر تحریم نیست.")
                return

            set_user_state(chat_id, "pardon_request_text")
            send_message(
                chat_id,
                "🇺🇳 درخواست بخشش از سازمان ملل\n"
                f"📋 دلیل تحریم فعلی: {country['sanction_reason'] or '—'}\n\n"
                "متن درخواست بخشش خود را ارسال کنید.\n"
                "⓪ بازگشت"
            )
            return

        send_message(
            chat_id,
            main_menu()
        )

        return

    # =====================================================
    # PARDON REQUEST (درخواست بخشش از سازمان ملل)
    # =====================================================

    if state == "pardon_request_text":

        if text == "0":
            set_user_state(chat_id, "main")
            send_message(chat_id, main_menu())
            return

        if not text:
            send_message(chat_id, "❌ متن درخواست خالی است.")
            return

        send_message(chat_id, "⏳ درخواست شما در حال بررسی توسط سازمان ملل است...")
        set_user_state(chat_id, "main")

        asyncio.create_task(un_ai_check_pardon(country, text))

        send_message(chat_id, main_menu())
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
            + "\n\n⓪ بازگشت"
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
            send_message(chat_id, user_loans_text(country["id"]) + "\n\n⓪ بازگشت")
            return

        if text == "3":
            loan = active_loan(country["id"])
            if not loan:
                send_message(chat_id,"❌ وام فعالی ندارید.\n\n⓪ بازگشت")
                return
            remaining = max(0, loan["repayment"] - loan["paid_amount"])
            set_user_state(chat_id,"loan_payment")
            send_message(chat_id,"💳 پرداخت وام\n━━━━━━━━━━━━━━━━━━━━━━\n① پرداخت کل هزینه\n② پرداخت قسمتی از وام\n⓪ بازگشت\n\nباقی‌مانده: "+money(remaining))
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
            send_message(chat_id,f"آیا مطمئن هستید مبلغ {money(remaining)} (همان بازپرداخت) بدهید؟\n\n① تایید\n② لغو")
            return
        if text=="2":
            set_user_state(chat_id,"loan_partial_amount")
            send_message(chat_id,"چه مقدار میخواهید پرداخت کنید؟\n⓪ بازگشت")
            return
        send_message(chat_id,"① پرداخت کل هزینه\n② پرداخت قسمتی از وام\n⓪ بازگشت"); return

    if state == "loan_partial_amount":
        if text=="0": set_user_state(chat_id,"loan_payment"); send_message(chat_id,"💳 پرداخت وام\n① پرداخت کل هزینه\n② پرداخت قسمتی از وام\n⓪ بازگشت"); return
        amount=parse_admin_money(text); loan=active_loan(country["id"])
        if amount is None or not loan: send_message(chat_id,"❌ مبلغ نامعتبر است."); return
        remaining=max(0,loan["repayment"]-loan["paid_amount"])
        if amount>remaining: send_message(chat_id,f"❌ بیشتر از باقی‌مانده است: {money(remaining)}"); return
        set_user_state(chat_id,f"loan_pay_confirm|{amount}")
        send_message(chat_id,f"آیا مایلید که مبلغ {money(amount)} را به عنوان قسمتی از وام پرداخت کنید\n① تایید\n② لغو"); return

    if state.startswith("loan_pay_confirm|"):
        amount=int(state.split("|",1)[1])
        if text=="2": set_user_state(chat_id,"loan_payment"); send_message(chat_id,"💳 پرداخت وام\n① پرداخت کل هزینه\n② پرداخت قسمتی از وام\n⓪ بازگشت"); return
        if text!="1": send_message(chat_id,"① تایید\n② لغو"); return
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
            "① تایید درخواست\n"
            "⓪ بازگشت"
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
                "① تایید\n⓪ بازگشت"
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

            if submitted_today("inventions", country["id"]):

                send_message(
                    chat_id,
                    "❌ شما امروز قبلاً یک درخواست اختراع ثبت کرده‌اید.\n"
                    "فردا دوباره امکان ثبت خواهید داشت."
                )

                return

            if country["money"] < 5000:

                send_message(
                    chat_id,
                    "❌ برای ثبت درخواست اختراع به ۵,۰۰۰ کوین نیاز دارید.\n"
                    f"💰 بودجه فعلی: {money(country['money'])}"
                )

                return

            set_user_state(
                chat_id,
                "invention_text"
            )

            send_message(
                chat_id,
                "🧪 اختراع خود را ارسال کنید:\n"
                "💰 هزینه‌ی ثبت: 5,000 کوین"
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

        if submitted_today("inventions", country["id"]):

            send_message(
                chat_id,
                "❌ شما امروز قبلاً یک درخواست اختراع ثبت کرده‌اید.\n"
                "فردا دوباره امکان ثبت خواهید داشت."
            )

            set_user_state(chat_id, "invention")

            return

        if country["money"] < 5000:

            send_message(
                chat_id,
                "❌ برای ثبت درخواست اختراع به ۵,۰۰۰ کوین نیاز دارید.\n"
                f"💰 بودجه فعلی: {money(country['money'])}"
            )

            set_user_state(chat_id, "invention")

            return

        change_money(country["id"], -5000)

        conn = db()

        conn.execute("""
            INSERT INTO inventions
            (country_id, title, status, created_at)
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
            "invention"
        )

        send_message(
            chat_id,
            "✅ درخواست اختراع برای مدیریت ارسال شد.\n"
            "💰 هزینه‌ی ۵,۰۰۰ کوین کسر شد."
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

            if submitted_today("roles", country["id"]):

                send_message(
                    chat_id,
                    "❌ شما امروز قبلاً یک رول ثبت کرده‌اید.\n"
                    "فردا دوباره امکان ثبت خواهید داشت."
                )

                return

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

        if submitted_today("roles", country["id"]):

            send_message(
                chat_id,
                "❌ شما امروز قبلاً یک رول ثبت کرده‌اید.\n"
                "فردا دوباره امکان ثبت خواهید داشت."
            )

            set_user_state(chat_id, "role")

            return

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

def un_panel_menu():
    return (
        "🇺🇳 پنل سازمان ملل\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① 📝 ارسال بیانیه رسمی\n"
        "② 🤖 مدیریت AI سازمان ملل\n"
        "③ 🚫 مدیریت تحریم‌ها\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⓪ بازگشت"
    )


def un_sanctions_country_menu(country):

    has_sanction = bool(country["sanction_locked_categories"] or country["sanction_economic_pct"])

    text = (
        f"🚫 تحریم‌های {country['flag']} {country['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if has_sanction:
        text += f"📋 دلیل: {country['sanction_reason'] or '—'}\n"
        if country["sanction_economic_pct"]:
            text += f"💰 تحریم اقتصادی: +{country['sanction_economic_pct']}٪ روی قیمت‌ها\n"
        if country["sanction_locked_categories"]:
            text += f"🔒 دسته‌های قفل‌شده: {country['sanction_locked_categories'].replace(',', '، ')}\n"
    else:
        text += "✅ این کشور تحریم نیست.\n"

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "① تنظیم تحریم اقتصادی (٪)\n"
        "② تنظیم تحریم نظامی (قفل دسته‌ها)\n"
        "③ برداشتن همه‌ی تحریم‌ها\n"
        "⓪ بازگشت"
    )

    return text


def handle_admin(chat_id, text):

    ensure_user(chat_id)

    user = get_user(chat_id)

    state = user["state"]

    # ---------------------------------------------
    # ورود ادمین
    # ---------------------------------------------

    if state == "admin_login":

        entered = normalize_text(text).upper()

        if entered == ADMIN_CODE.upper():

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

        elif entered == UN_PANEL_CODE.upper():

            conn = db()

            conn.execute("""
                UPDATE users
                SET state='un_panel_menu',
                    temp_data=''
                WHERE user_id=?
            """, (str(chat_id),))

            conn.commit()
            conn.close()

            send_message(
                chat_id,
                un_panel_menu()
            )

        else:

            send_message(
                chat_id,
                "❌ کد مدیریت اشتباه است."
            )

        return

    # ---------------------------------------------
    # پنل سازمان ملل (جزئیات بعداً اضافه میشه)
    # ---------------------------------------------

    if state == "un_panel_menu":

        if text == "0":

            conn = db()

            conn.execute("""
                UPDATE users
                SET state='login',
                    temp_data=''
                WHERE user_id=?
            """, (str(chat_id),))

            conn.commit()
            conn.close()

            send_message(
                chat_id,
                "🚪 از پنل سازمان ملل خارج شدید."
            )

            return

        if text == "1":
            set_user_state(chat_id, "un_announcement_text")
            send_message(chat_id, "📝 متن بیانیه‌ی رسمی سازمان ملل را ارسال کنید.\n⓪ بازگشت")
            return

        if text == "2":
            set_user_state(chat_id, "un_ai_menu")
            send_message(chat_id, un_ai_menu())
            return

        if text == "3":
            set_user_state(chat_id, "un_sanctions_code")
            send_message(chat_id, "🚫 مدیریت تحریم‌ها\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        send_message(
            chat_id,
            un_panel_menu()
        )

        return

    # ---------------------------------------------
    # ارسال بیانیه‌ی رسمی سازمان ملل
    # ---------------------------------------------

    if state == "un_announcement_text":

        if text == "0":
            set_user_state(chat_id, "un_panel_menu")
            send_message(chat_id, un_panel_menu())
            return

        if not text:
            send_message(chat_id, "❌ متن بیانیه خالی است.")
            return

        notice = (
            "🇺🇳 اطلاعیه رسمی سازمان ملل\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🇺🇳 UNITED NATIONS | Soor War"
        )

        try:
            asyncio.create_task(client.send_message(CHANNEL, notice))
        except Exception as e:
            print("UN ANNOUNCEMENT SEND ERROR:", repr(e))

        set_user_state(chat_id, "un_panel_menu")
        send_message(chat_id, "✅ بیانیه ارسال شد.\n\n" + un_panel_menu())
        return

    # ---------------------------------------------
    # مدیریت تحریم‌ها
    # ---------------------------------------------

    if state == "un_sanctions_code":

        if text == "0":
            set_user_state(chat_id, "un_panel_menu")
            send_message(chat_id, un_panel_menu())
            return

        target = country_by_code(text)

        if not target:
            send_message(chat_id, "❌ کد کشور نامعتبر است.\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        set_user_state(chat_id, f"un_sanctions_menu|{target['id']}")
        send_message(chat_id, un_sanctions_country_menu(target))
        return

    if state.startswith("un_sanctions_menu|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if not target:
            set_user_state(chat_id, "un_panel_menu")
            send_message(chat_id, un_panel_menu())
            return

        if text == "0":
            set_user_state(chat_id, "un_sanctions_code")
            send_message(chat_id, "🚫 مدیریت تحریم‌ها\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        if text == "1":
            set_user_state(chat_id, f"un_sanctions_econ|{cid}")
            send_message(chat_id, "💰 درصد افزایش قیمت را ارسال کنید (مثلاً 30):\n⓪ بازگشت")
            return

        if text == "2":
            cat_list = "\n".join(
                f"{number_sticker(i)} {category_emoji(c)} {c}"
                for i, c in enumerate(CATEGORIES, 1)
            )
            set_user_state(chat_id, f"un_sanctions_military|{cid}")
            send_message(
                chat_id,
                "🔒 شماره‌ی دسته‌هایی که می‌خواهید قفل شوند را با کاما ارسال کنید (مثلاً 3,5,9):\n\n"
                + cat_list + "\n\n⓪ بازگشت"
            )
            return

        if text == "3":
            conn = db()
            conn.execute("""
                UPDATE countries
                SET sanction_economic_pct=0, sanction_locked_categories='', sanction_reason=''
                WHERE id=?
            """, (cid,))
            conn.commit()
            conn.close()
            target = get_country_by_id(cid)
            send_message(chat_id, "✅ همه‌ی تحریم‌ها برداشته شد.\n\n" + un_sanctions_country_menu(target))
            return

        send_message(chat_id, un_sanctions_country_menu(target))
        return

    if state.startswith("un_sanctions_econ|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if text == "0" or not target:
            set_user_state(chat_id, f"un_sanctions_menu|{cid}")
            send_message(chat_id, un_sanctions_country_menu(target) if target else un_panel_menu())
            return

        if not text.isdigit():
            send_message(chat_id, "❌ لطفاً یک عدد ارسال کنید.\n⓪ بازگشت")
            return

        conn = db()
        conn.execute("UPDATE countries SET sanction_economic_pct=?, sanction_reason=? WHERE id=?",
                      (int(text), "تحریم اقتصادی توسط سازمان ملل", cid))
        conn.commit()
        conn.close()

        target = get_country_by_id(cid)
        set_user_state(chat_id, f"un_sanctions_menu|{cid}")
        send_message(chat_id, f"✅ تحریم اقتصادی {text}٪ اعمال شد.\n\n" + un_sanctions_country_menu(target))
        return

    if state.startswith("un_sanctions_military|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if text == "0" or not target:
            set_user_state(chat_id, f"un_sanctions_menu|{cid}")
            send_message(chat_id, un_sanctions_country_menu(target) if target else un_panel_menu())
            return

        try:
            numbers = [int(x.strip()) for x in text.split(",") if x.strip()]
            selected = [CATEGORIES[n - 1] for n in numbers if 1 <= n <= len(CATEGORIES)]
        except Exception:
            selected = []

        if not selected:
            send_message(chat_id, "❌ ورودی نامعتبر است. دوباره امتحان کنید.\n⓪ بازگشت")
            return

        conn = db()
        conn.execute("UPDATE countries SET sanction_locked_categories=?, sanction_reason=? WHERE id=?",
                      (",".join(selected), "تحریم نظامی توسط سازمان ملل", cid))
        conn.commit()
        conn.close()

        target = get_country_by_id(cid)
        set_user_state(chat_id, f"un_sanctions_menu|{cid}")
        send_message(chat_id, "✅ تحریم نظامی اعمال شد.\n\n" + un_sanctions_country_menu(target))
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

            schedule_status_post(new_value == "1")

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
                "⓪ بازگشت"
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
                "⓪ بازگشت"
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

            send_message(chat_id, ai_or_fallback_stats())
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
            send_message(chat_id, "💰 مدیریت تجهیزات تومانی\n━━━━━━━━━━━━━━━━━━━━━━\nکد کشور را ارسال کنید.\n⓪ بازگشت")
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

        if text == "18":
            set_user_state(chat_id, "admin_status_code")
            send_message(chat_id, "🧬 تغییر وضعیت کشورها\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        if text == "19":
            set_user_state(chat_id, "un_ai_menu")
            send_message(chat_id, un_ai_menu())
            return

        send_message(chat_id, admin_menu())

        return

    # =====================================================
    # UN AI MANAGEMENT (مدیریت AI سازمان ملل)
    # =====================================================

    if state == "un_ai_menu":

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text == "1":
            new_value = "0" if is_enabled("un_ai_enabled") else "1"
            set_setting("un_ai_enabled", new_value)
            send_message(chat_id, un_ai_menu())
            return

        if text in ("2", "3", "4"):
            level = {"2": "عادی", "3": "متوسط", "4": "سخت"}[text]
            set_setting("un_ai_difficulty", level)
            send_message(chat_id, un_ai_menu())
            return

        send_message(chat_id, un_ai_menu())
        return

    # =====================================================
    # ADMIN COUNTRY STATUS CHANGE
    # =====================================================

    if state == "admin_status_code":

        if text == "0":
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        target = country_by_code(text)

        if not target:
            send_message(chat_id, "❌ کد کشور نامعتبر است.\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        set_user_state(chat_id, f"admin_status_menu|{target['id']}")
        send_message(chat_id, show_country(target) + "\n\n" + admin_status_role_menu(target))
        return

    if state.startswith("admin_status_menu|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if not target:
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, "❌ کشور پیدا نشد.\n\n" + admin_menu())
            return

        if text == "0":
            set_user_state(chat_id, "admin_status_code")
            send_message(chat_id, "🧬 تغییر وضعیت کشورها\nکد کشور را ارسال کنید.\n⓪ بازگشت")
            return

        role_map = {
            "1": "leader", "2": "gov", "3": "fm", "4": "commander", "5": "negotiation",
        }

        if target["name"] in FACTION_NAMES and text == "6":
            set_user_state(chat_id, f"admin_status_faction|{cid}")
            send_message(
                chat_id,
                "🪖 گروهک ساکن\n"
                "① تنظیم محل استقرار\n"
                "② حذف (ندارد)\n"
                "⓪ بازگشت"
            )
            return

        if text in role_map:
            role = role_map[text]
            set_user_state(chat_id, f"admin_status_role|{cid}|{role}")
            send_message(
                chat_id,
                "① تغییر نام\n"
                "② تغییر وضعیت\n"
                "⓪ بازگشت"
            )
            return

        send_message(chat_id, admin_status_role_menu(target))
        return

    if state.startswith("admin_status_role|"):

        _, cid, role = state.split("|", 2)
        cid = int(cid)
        target = get_country_by_id(cid)

        if not target:
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, "❌ کشور پیدا نشد.\n\n" + admin_menu())
            return

        if text == "0":
            set_user_state(chat_id, f"admin_status_menu|{cid}")
            send_message(chat_id, admin_status_role_menu(target))
            return

        name_col = {"leader": "leader", "gov": "president", "fm": "foreign_minister", "commander": "commander", "negotiation": "negotiation_team"}[role]
        status_col = {"leader": "leader_status", "gov": "gov_status", "fm": "fm_status", "commander": "commander_status", "negotiation": "negotiation_status"}[role]

        if text == "1":
            set_user_state(chat_id, f"admin_status_name_input|{cid}|{role}")
            send_message(chat_id, "✏️ نام جدید را ارسال کنید.\n⓪ بازگشت")
            return

        if text == "2":
            set_user_state(chat_id, f"admin_status_status_input|{cid}|{role}")
            send_message(chat_id, "① زنده\n② وضعیت نامشخص\n⓪ بازگشت")
            return

        send_message(chat_id, "① تغییر نام\n② تغییر وضعیت\n⓪ بازگشت")
        return

    if state.startswith("admin_status_name_input|"):

        _, cid, role = state.split("|", 2)
        cid = int(cid)
        target = get_country_by_id(cid)

        if text == "0" or not target:
            set_user_state(chat_id, f"admin_status_role|{cid}|{role}")
            send_message(chat_id, "① تغییر نام\n② تغییر وضعیت\n⓪ بازگشت")
            return

        name_col = {"leader": "leader", "gov": "president", "fm": "foreign_minister", "commander": "commander", "negotiation": "negotiation_team"}[role]

        conn = db()
        conn.execute(f"UPDATE countries SET {name_col}=? WHERE id=?", (text, cid))
        conn.commit()
        conn.close()

        target = get_country_by_id(cid)
        set_user_state(chat_id, f"admin_status_menu|{cid}")
        send_message(chat_id, "✅ نام به‌روزرسانی شد.\n\n" + show_country(target) + "\n\n" + admin_status_role_menu(target))
        return

    if state.startswith("admin_status_status_input|"):

        _, cid, role = state.split("|", 2)
        cid = int(cid)
        target = get_country_by_id(cid)

        if not target:
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text == "0":
            set_user_state(chat_id, f"admin_status_role|{cid}|{role}")
            send_message(chat_id, "① تغییر نام\n② تغییر وضعیت\n⓪ بازگشت")
            return

        if text not in ("1", "2"):
            send_message(chat_id, "① زنده\n② وضعیت نامشخص\n⓪ بازگشت")
            return

        status_col = {"leader": "leader_status", "gov": "gov_status", "fm": "fm_status", "commander": "commander_status", "negotiation": "negotiation_status"}[role]
        new_status = "زنده" if text == "1" else "نامشخص"

        conn = db()
        conn.execute(f"UPDATE countries SET {status_col}=? WHERE id=?", (new_status, cid))
        conn.commit()
        conn.close()

        target = get_country_by_id(cid)
        set_user_state(chat_id, f"admin_status_menu|{cid}")
        send_message(chat_id, "✅ وضعیت به‌روزرسانی شد.\n\n" + show_country(target) + "\n\n" + admin_status_role_menu(target))
        return

    if state.startswith("admin_status_faction|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if not target:
            set_user_state(chat_id, "admin_menu")
            send_message(chat_id, admin_menu())
            return

        if text == "0":
            set_user_state(chat_id, f"admin_status_menu|{cid}")
            send_message(chat_id, admin_status_role_menu(target))
            return

        if text == "2":
            conn = db()
            conn.execute("UPDATE countries SET faction_host_id=NULL WHERE id=?", (cid,))
            conn.commit()
            conn.close()
            target = get_country_by_id(cid)
            set_user_state(chat_id, f"admin_status_menu|{cid}")
            send_message(chat_id, "✅ محل استقرار حذف شد.\n\n" + show_country(target) + "\n\n" + admin_status_role_menu(target))
            return

        if text == "1":
            set_user_state(chat_id, f"admin_status_faction_code|{cid}")
            send_message(chat_id, "کد کشور مورد نظر را ارسال کنید.\n⓪ بازگشت")
            return

        send_message(chat_id, "① تنظیم محل استقرار\n② حذف (ندارد)\n⓪ بازگشت")
        return

    if state.startswith("admin_status_faction_code|"):

        cid = int(state.split("|", 1)[1])
        target = get_country_by_id(cid)

        if text == "0" or not target:
            set_user_state(chat_id, f"admin_status_menu|{cid}")
            send_message(chat_id, admin_status_role_menu(target) if target else admin_menu())
            return

        host = country_by_code(text)

        if not host:
            send_message(chat_id, "❌ کد کشور نامعتبر است.\nکد کشور مورد نظر را ارسال کنید.\n⓪ بازگشت")
            return

        conn = db()
        conn.execute("UPDATE countries SET faction_host_id=? WHERE id=?", (host["id"], cid))
        conn.commit()
        conn.close()

        target = get_country_by_id(cid)
        set_user_state(chat_id, f"admin_status_menu|{cid}")
        send_message(chat_id, f"✅ محل استقرار تنظیم شد: {host['flag']} {host['name']}\n\n" + show_country(target) + "\n\n" + admin_status_role_menu(target))
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
            "① بله\n"
            "⓪ بازگشت"
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
                "① بله\n⓪ بازگشت"
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
            "① بله\n⓪ بازگشت"
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
            send_message(chat_id, "① بله\n⓪ بازگشت")
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
        conn.execute(
            "UPDATE countries SET code=?, code_version=code_version+1 WHERE id=?",
            (new_code, country_id)
        )
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
            "① بله\n"
            "⓪ بازگشت"
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
                "① بله\n⓪ بازگشت"
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
        send_message(chat_id, f"🛠️ تجهیز: {item['name']}\n📦 موجودی فعلی: {get_equipment(country_id, item['code']):,}\n🔢 حداکثر: {item['max']:,}\n\nتعداد موردنظر را ارسال کنید.\n⓪ بازگشت")
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
                "❌ تجهیزات نمی‌تواند منفی باشد.\n\n⓪ بازگشت"
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
            send_message(chat_id,"❌ کد کشور نامعتبر است.\n⓪ بازگشت"); return
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
            send_message(chat_id,f"❌ این کشور حداکثر {item['name']} را خریداری کرده است.\n⓪ بازگشت"); return
        set_user_state(chat_id,f"admin_toman_amount|{cid}|{op}|{key}")
        send_message(chat_id,f"{item['name']}\nموجودی فعلی: {cur}\nحداکثر: {item['limit']}\nتعداد را ارسال کنید.\n⓪ بازگشت"); return

    if state.startswith("admin_toman_amount|"):
        _,cid,op,key=state.split("|"); cid=int(cid); item=TOMAN_ITEMS[key]
        if text=="0": set_user_state(chat_id,f"admin_toman_select|{cid}|{op}"); send_message(chat_id,admin_toman_items(cid,op)); return
        if not text.isdigit() or int(text)<=0: send_message(chat_id,"❌ تعداد نامعتبر است.\n⓪ بازگشت"); return
        amount=int(text); cur=get_toman_amount(cid,key); new=cur+(amount if op=="add" else -amount)
        if new<0: send_message(chat_id,"❌ تجهیزات تومانی نمی‌تواند منفی باشد.\n⓪ بازگشت"); return
        if new>item['limit']: send_message(chat_id,f"❌ بیشتر از حداکثر مجاز است: {item['limit']}\n⓪ بازگشت"); return
        # Stadium is a bonus, not a permanent change to base approval.
        if key=="international_stadium" and new==1: 
            conn=db(); conn.execute("UPDATE countries SET approval_bonus=50 WHERE id=?",(cid,)); conn.commit(); conn.close()
        if key=="international_stadium" and new==0:
            conn=db(); conn.execute("UPDATE countries SET approval_bonus=0 WHERE id=?",(cid,)); conn.commit(); conn.close()
        if key=="royal_treasury":
            pass
        if key=="all_bases" and new==1:
            for code in ["air_base","heli_base","drone_base","missile_base","defense_base","ground_base","troop_base","naval_base","sub_base","cyber_base","space_base","weapons_factory"]:
                it=get_item(code)
                if it: set_equipment(cid,it,1)
        if key=="all_bases" and new==0:
            for code in ["air_base","heli_base","drone_base","missile_base","defense_base","ground_base","troop_base","naval_base","sub_base","cyber_base","space_base","weapons_factory"]:
                it=get_item(code)
                if it: set_equipment(cid,it,0)
        if key=="equipment_pack" and new>cur:
            import random as _rnd
            gained = []
            for _ in range(new-cur):
                k = _rnd.randint(3,8)
                picks = _rnd.sample(SHOP_ITEMS, min(k, len(SHOP_ITEMS)))
                for p in picks:
                    change_equipment(cid, p, p["unit"])
                    gained.append(p["name"])
            sync_daily_profit(cid)
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
                active_loans_text() + "\n⓪ بازگشت"
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
            "① تایید\n"
            "② رد\n"
            "⓪ بازگشت"
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
                "① تایید\n② رد\n⓪ بازگشت"
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
                msg = "🗑️ اختراعات فعال\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"{number_sticker(i)} {r['flag']} {r['name']} — {r['title']}" for i,r in enumerate(rows,1)) + "\n\n⓪ بازگشت"
            else:
                msg = "❌ اختراع فعالی وجود ندارد.\n\n⓪ بازگشت"
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
            text_out = "🗑️ اختراعات فعال\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(f"{number_sticker(i)} {r['flag']} {r['name']} — {r['title']}" for i,r in enumerate(rows,1)) + "\n\n⓪ بازگشت"
            send_message(chat_id, text_out)
            return
        inv=rows[int(text)-1]
        set_user_state(chat_id, f"admin_delete_invention_confirm|{inv['id']}")
        send_message(chat_id, f"آیا مایلید اختراع {inv['title']} را حذف کنید؟\n\n① تایید\n② لغو")
        return

    if state.startswith("admin_delete_invention_confirm|"):
        inv_id=int(state.split("|",1)[1])
        if text == "2":
            set_user_state(chat_id,"admin_invention")
            send_message(chat_id,admin_invention_menu())
            return
        if text != "1":
            send_message(chat_id,"① تایید\n② لغو")
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
            "① ثبت (تعیین بودجه و تعداد)\n"
            "② رد کردن\n"
            "⓪ بازگشت"
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
            "① ثبت (تعیین بودجه و تعداد)\n"
            "② رد کردن\n"
            "⓪ بازگشت"
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
            "① تایید\n"
            "② لغو"
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
                "① تایید\n② لغو"
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
            "① تایید\n"
            "② لغو"
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
                "① تایید\n② لغو"
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

    # اگه ادمین کد این کشور رو عوض کرده باشه (و این کاربر با کد قدیمی
    # وارد شده بوده)، از پنل بندازیمش بیرون برای امنیت.
    if user and user["country_id"] and user["state"] != "admin_login" and not user["is_admin"]:

        conn = db()
        _c = conn.execute(
            "SELECT code_version FROM countries WHERE id=?",
            (user["country_id"],)
        ).fetchone()
        conn.close()

        if _c and _c["code_version"] != user["joined_code_version"]:

            logout_user(chat_id)

            send_message(
                chat_id,
                "🚪 به دلیل تغییر کد این کشور توسط مدیریت، از پنل خارج شدید.\n"
                "🔐 لطفاً با کد جدید دوباره وارد شوید."
            )

            return

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
    if user and user["state"] in ("admin_login", "un_panel_menu"):
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
            "🔴 Soor War در حال حاضر خاموش است."
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
    prefix = f"{header}\n\nبیانیه رسمی {country['name']}\n\n"
    suffix = "\n\n╰┈➤ ⚜️ 𝗦𝗢𝗢𝗥 𝗪𝗔𝗥\n🔗 https://splus.ir/Soorwar"
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

        conn = db()
        total_announcements = conn.execute(
            "SELECT COUNT(*) AS n FROM announcements"
        ).fetchone()["n"]
        conn.close()

        if total_announcements % 10 == 0:
            await summarize_last_announcements(10)

        await un_ai_check_announcement(country, text)
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
        # و متن‌های منو/وضعیت (مثل «Soor War خاموش است») رو با
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
    print("Soor War is running without bot token...")

    asyncio.create_task(_auto_commit_loop())
    asyncio.create_task(_loan_reminder_loop())
    asyncio.create_task(_ai_stats_loop())
    asyncio.create_task(_self_shutdown_after(RUNTIME_LIMIT_SECONDS))

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
