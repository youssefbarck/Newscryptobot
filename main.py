import os, time, json, logging, threading, re, hashlib
from datetime import datetime, timezone
import pytz, requests
from xml.etree import ElementTree as ET
from flask import Flask, jsonify, request

# ═══════════════════════════════════════════════════════════
# الإعدادات العامة
# ═══════════════════════════════════════════════════════════
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIMEZONE = os.environ.get("TIMEZONE", "Africa/Algiers")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
# 🆕 رابط قناة تيليجرام (يمكن وضع اسم المستخدم أو الرابط الكامل)
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/whale_signals_channel")
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "🐋 قناة الحيتان")
# 🆕 معرّف القناة العامة لإرسال التنبيهات (مثل @my_channel أو -1001234567890)
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
# 🆕 تفعيل/إيقاف الإرسال للقناة العامة
SEND_TO_CHANNEL = os.environ.get("SEND_TO_CHANNEL", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("NewsBot")
tz = pytz.timezone(TIMEZONE)
# 🔧 إصلاح: User-Agent مناسب لتجنب حظر Reddit والمصادر الأخرى
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0; +https://github.com/whale-news)"}
# 🔧 إصلاح: User-Agent مخصص لـ Reddit (يتطلبه Reddit API)
REDDIT_HEADERS = {"User-Agent": "WhaleNewsBot/1.0 by u/whale_news_bot"}

# ═══════════════════════════════════════════════════════════
# مصادر الأخبار (RSS)
# ═══════════════════════════════════════════════════════════
NEWS_SOURCES = {
    # 🪙 مصادر كريبتو
    "CoinDesk": {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
        "category": "crypto",
        "lang": "en"
    },
    "Cointelegraph": {
        "url": "https://cointelegraph.com/rss",
        "category": "crypto",
        "lang": "en"
    },
    "Decrypt": {
        "url": "https://decrypt.co/feed",
        "category": "crypto",
        "lang": "en"
    },
    "Bitcoin.com": {
        "url": "https://news.bitcoin.com/feed/",
        "category": "crypto",
        "lang": "en"
    },
    # 🇺🇸 مصادر الاقتصاد الكلي والبيت الأبيض
    "CNBC Economy": {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
        "category": "macro",
        "lang": "en"
    },
    "CNBC White House": {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000113",
        "category": "macro",
        "lang": "en"
    },
    "Federal Reserve": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "macro",
        "lang": "en"
    },
    "Forexlive": {
        "url": "https://www.forexlive.com/feed/",
        "category": "macro",
        "lang": "en"
    },
    # 🐋 مصادر الأثرياء والمستثمرين
    # 🔧 إصلاح: تحديث رابط Benzinga (القديم لم يعد يعمل)
    "Benzinga Markets": {
        "url": "https://www.benzinga.com/feed/rss",
        "category": "macro",
        "lang": "en"
    },
    # 🔍 مجتمعي
    "Reddit r/CryptoCurrency": {
        "url": "https://www.reddit.com/r/CryptoCurrency/new.json?limit=20",
        "category": "crypto",
        "lang": "en",
        "is_json": True
    },
}

# 🆕 كلمات مفتاحية شاملة جداً للفلترة
KEYWORDS_BREAKING = [
    # عاجل
    "breaking", "urgent", "alert", "just in", "developing",
    # اختراقات وأمن
    "hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach", "cyberattack", "security breach",
    # حظر وتنظيم
    "ban", "banned", "prohibit", "lawsuit", "sues", "sued", "crackdown", "sanction", "penalty", "fraud", "charges", "arrest", "indictment",
    # موافقات وأخبار رئيسية
    "approval", "approved", "reject", "rejected", "etf", "spot etf", "all-time high", "ath", "crash", "surge", "plunge", "pump", "dump",
    # كلمات القنوات الإخبارية
    "announce", "announces", "launches", "unveils", "reveals", "partnership", "acquisition", "merger",
]

KEYWORDS_FED = [
    "fed", "federal reserve", "interest rate", "powell", "fomc", "rate cut", "rate hike", "rate decision", "monetary policy",
    "inflation", "inflation data", "cpi", "core cpi", "ppi", "nonfarm payrolls", "jobless claims", "unemployment", "recession",
    "qe", "quantitative easing", "qt", "balance sheet", "treasury", "treasury yields", "yields", "bonds", "minutes",
    "economic data", "gdp", "consumer spending", "retail sales", "consumer price index", "job report",
]

KEYWORDS_TRUMP = [
    "trump", "donald trump", "tariff", "trade war", "white house", "biden", "biden administration", "administration",
    "sec", "gary gensler", "gensler", "congress", "senate", "lawmaker", "regulation", "regulatory", "legislation",
    "election", "campaign", "presidential", "executive order",
]

KEYWORDS_WHALES = [
    "elon musk", "michael saylor", "warren buffett", "bill ackman", "ray dalio", "cathie wood", "whale", "whales",
    "blackrock", "microstrategy", "satoshi", "binance", "cz", "changpeng zhao", "sam bankman-fried", "sbf",
    "vitalik", "vitalik buterin", "charles hoskinson", "brian armstrong", "coinbase ceo",
    "institutional", "inflows", "outflows", "accumulation",
]

KEYWORDS_TECH = [  # 🆕 فئة جديدة للأخبار التقنية والتحديثات
    "upgrade", "roadmap", "merge", "the merge", "halving", "fork", "hard fork", "soft fork",
    "mainnet", "testnet", "layer 2", "l2", "scaling", "rollup", "zk", "zero-knowledge",
    "smart contract", "defi", "nft", "dao", "staking", "yield", "airdrop", "tokenomics",
    "consensus", "proof of stake", "proof of work", "pos", "pow", "validator", "node",
    "ethereum 2.0", "serenity", "sharding", "dencun", "pectra", "purge", "verge", "lean ethereum",
    "protocol", "blockchain", "decentralized", "ledger",
]

KEYWORDS_MARKET = [  # 🆕 فئة جديدة لحركة السوق
    "bull market", "bear market", "bullish", "bearish", "rally", "correction", "support", "resistance",
    "liquidation", "leverage", "futures", "options", "open interest", "funding rate", "long", "short",
    "volume", "volatility", "dominance", "market cap", "capitalization", "supply", "demand",
    "price", "target", "forecast", "prediction", "analysis", "outlook", "sentiment",
]

KEYWORDS_ETF = [
    "etf", "spot etf", "approval", "sec", "blackrock", "fidelity", "ark invest", "grayscale", "van eck", "franklin templeton",
    "19b-4", "s-1", "prospectus", "issuance", "redemption", "creation", "trust", "fund flow",
]

KEYWORDS_HACK = [
    "hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach", "cyberattack", "security breach",
    "rekt", "drained", "empty", "compromised", "attacker", "hacker", "malicious", "phishing",
]

# ═══════════════════════════════════════════════════════════
# المتغيرات العامة
# ═══════════════════════════════════════════════════════════
_cache = {}
_started = False
last_id = 0
_user_state = {}
# 🔧 إصلاح: تطبيق ALERT_COOLDOWN فعلياً (ساعات بين تنبيهين لنفس الخبر)
ALERT_COOLDOWN = 21600  # 6 ساعات بين تنبيهين لنفس الخبر
last_alerts_hashes = {}  # hash الخبر → آخر وقت تنبيه (يُستخدم الآن)
# 🆕 ذاكرة دائمة للأخبار المُرسلة (لن تُعاد أبداً)
# 🔧 إصلاح: استخدام GitHub Gist كمخزن دائم مجاني (لا يحتاج Disk مدفوع)
import os as _os
_GITHUB_TOKEN = _os.environ.get("GITHUB_TOKEN", "")
_GIST_ID_SETTINGS = _os.environ.get("GIST_ID_SETTINGS", "")  # Gist ID for news_settings.json
_GIST_ID_SENT_NEWS = _os.environ.get("GIST_ID_SENT_NEWS", "")  # Gist ID for sent_news.json
_GIST_ID_ALLOWED = _os.environ.get("GIST_ID_ALLOWED", "")  # Gist ID for allowed_users.json
# fallback محلي (للحالات الطارئة)
_PERSISTENT_DIR = _os.environ.get("PERSISTENT_DIR", "/tmp")
SENT_NEWS_FILE = _os.path.join(_PERSISTENT_DIR, "sent_news.json")
SETTINGS_FILE_LOCAL = _os.path.join(_PERSISTENT_DIR, "news_settings.json")
ALLOWED_FILE_LOCAL = _os.path.join(_PERSISTENT_DIR, "allowed_users.json")
sent_news_hashes = set()  # كل أخبار تم إرسالها

# 🆕 دوال GitHub Gist للمخزن الدائم المجاني
def _gist_get(gist_id, filename):
    """جلب محتوى ملف من Gist"""
    if not _GITHUB_TOKEN or not gist_id:
        return None
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {_GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            files = data.get("files", {})
            if filename in files:
                return files[filename].get("content", "")
        return None
    except Exception as e:
        log.warning(f"gist_get err: {e}")
        return None

def _gist_set(gist_id, filename, content):
    """حفظ محتوى ملف في Gist"""
    if not _GITHUB_TOKEN or not gist_id:
        return False
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {_GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={"files": {filename: {"content": content}}},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        log.warning(f"gist_set err: {e}")
        return False

def load_sent_news():
    """🆕 تحميل الأخبار المُرسلة سابقاً (من Gist أو محلي)"""
    global sent_news_hashes
    # محاولة من Gist أولاً
    if _GIST_ID_SENT_NEWS:
        content = _gist_get(_GIST_ID_SENT_NEWS, "sent_news.json")
        if content:
            try:
                data = json.loads(content)
                sent_news_hashes = set(data.get("hashes", []))
                log.info(f"✅ Loaded {len(sent_news_hashes)} sent news hashes from Gist")
                return
            except Exception as e:
                log.warning(f"gist sent_news parse err: {e}")
    # fallback محلي
    try:
        with open(SENT_NEWS_FILE, "r") as f:
            sent_news_hashes = set(json.load(f).get("hashes", []))
        log.info(f"✅ Loaded {len(sent_news_hashes)} sent news hashes from local")
    except Exception:
        sent_news_hashes = set()

def save_sent_news():
    """🆕 حفظ الأخبار المُرسلة (في Gist + محلي)"""
    content = json.dumps({"hashes": list(sent_news_hashes)[-500:]})
    # حفظ في Gist
    if _GIST_ID_SENT_NEWS:
        _gist_set(_GIST_ID_SENT_NEWS, "sent_news.json", content)
    # حفظ محلي كـ cache
    try:
        with open(SENT_NEWS_FILE, "w") as f:
            f.write(content)
    except Exception as e:
        log.warning(f"save_sent_news local err: {e}")

# 🔔 إعدادات التنبيهات
auto_alerts_enabled = True
alert_categories = {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True}
# 🔧 إصلاح: نقل الإعدادات للملف الدائم
SETTINGS_FILE = _os.path.join(_PERSISTENT_DIR, "news_settings.json")
# 🆕 متغيرات قابلة للتبديل وقت التشغيل
channel_enabled = None  # None = استخدم قيمة env var الافتراضية
bot_shutdown = False  # True = البوت متوقف تماماً (المالك فقط يمكنه إعادة تشغيله)
# 🆕 وقت إعادة التشغيل بعد إيقاف - لمنع إرسال الأخبار القديمة المتراكمة
bot_resume_time = 0  # timestamp لآخر مرة أُعيد فيها التشغيل
_skip_old_news_once = False  # علم لتجاوز الأخبار القديمة مرة واحدة بعد الاستئناف

def load_settings():
    """🔧 تحميل الإعدادات من Gist (مع fallback محلي)"""
    global auto_alerts_enabled, alert_categories, channel_enabled, bot_shutdown, bot_resume_time
    loaded = False
    # محاولة من Gist أولاً
    if _GIST_ID_SETTINGS:
        content = _gist_get(_GIST_ID_SETTINGS, "news_settings.json")
        if content:
            try:
                s = json.loads(content)
                auto_alerts_enabled = s.get("auto_alerts_enabled", True)
                alert_categories = s.get("alert_categories", {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True})
                channel_enabled = s.get("channel_enabled", None)
                bot_shutdown = s.get("bot_shutdown", False)
                bot_resume_time = s.get("bot_resume_time", 0)
                log.info(f"✅ Loaded settings from Gist (channel={channel_enabled}, shutdown={bot_shutdown})")
                loaded = True
            except Exception as e:
                log.warning(f"gist settings parse err: {e}")
    # fallback محلي
    if not loaded:
        try:
            with open(SETTINGS_FILE_LOCAL, "r") as f:
                s = json.load(f)
                auto_alerts_enabled = s.get("auto_alerts_enabled", True)
                alert_categories = s.get("alert_categories", {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True})
                channel_enabled = s.get("channel_enabled", None)
                bot_shutdown = s.get("bot_shutdown", False)
                bot_resume_time = s.get("bot_resume_time", 0)
                log.info(f"✅ Loaded settings from local file")
        except Exception:
            pass

def save_settings():
    """🔧 حفظ الإعدادات في Gist + محلي"""
    content = json.dumps({
        "auto_alerts_enabled": auto_alerts_enabled,
        "alert_categories": alert_categories,
        "channel_enabled": channel_enabled,
        "bot_shutdown": bot_shutdown,
        "bot_resume_time": bot_resume_time,
    }, ensure_ascii=False, indent=2)
    # حفظ في Gist
    if _GIST_ID_SETTINGS:
        if _gist_set(_GIST_ID_SETTINGS, "news_settings.json", content):
            log.info("💾 Settings saved to Gist")
        else:
            log.warning("⚠️ Failed to save settings to Gist")
    # حفظ محلي كـ cache
    try:
        with open(SETTINGS_FILE_LOCAL, "w") as f:
            f.write(content)
    except Exception as e:
        log.warning(f"save_settings local err: {e}")

def is_channel_enabled():
    """🆕 يعيد True إذا كان الإرسال للقناة مفعّل (يحترم التبديل وقت التشغيل)
    🔧 إصلاح: قراءة صريحة للمتغير العالمي + سجل للتشخيص
    """
    global channel_enabled
    # قراءة القيمة الحالية
    if channel_enabled is not None:
        result = channel_enabled and bool(CHANNEL_ID)
        log.info(f"📢 is_channel_enabled: channel_enabled={channel_enabled}, result={result}")
        return result
    # fallback إلى env var
    result = SEND_TO_CHANNEL and bool(CHANNEL_ID)
    log.info(f"📢 is_channel_enabled: using env fallback SEND_TO_CHANNEL={SEND_TO_CHANNEL}, result={result}")
    return result

# 🔒 القائمة البيضاء
# 🔧 إصلاح: استخدام Gist للقائمة البيضاء
ALLOWED_FILE = ALLOWED_FILE_LOCAL  # للتوافق مع الكود القديم

def load_dynamic_allowed():
    """تحميل القائمة البيضاء من Gist (مع fallback محلي)"""
    # محاولة من Gist
    if _GIST_ID_ALLOWED:
        content = _gist_get(_GIST_ID_ALLOWED, "allowed_users.json")
        if content:
            try:
                return set(json.loads(content).get("users", []))
            except Exception as e:
                log.warning(f"gist allowed parse err: {e}")
    # fallback محلي
    try:
        with open(ALLOWED_FILE_LOCAL, "r") as f:
            return set(json.load(f).get("users", []))
    except Exception:
        return set()

def save_dynamic_allowed(users_set):
    """حفظ القائمة البيضاء في Gist + محلي"""
    content = json.dumps({"users": list(users_set)})
    # حفظ في Gist
    if _GIST_ID_ALLOWED:
        if not _gist_set(_GIST_ID_ALLOWED, "allowed_users.json", content):
            log.warning("⚠️ Failed to save allowed_users to Gist")
    # حفظ محلي
    try:
        with open(ALLOWED_FILE_LOCAL, "w") as f:
            f.write(content)
    except Exception as e:
        log.warning(f"save_allowed local err: {e}")

_dynamic_allowed = load_dynamic_allowed()

def _parse_allowed_users():
    allowed = set()
    raw = os.environ.get("ALLOWED_USERS", "")
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.isdigit():
            allowed.add(int(part))
    if CHAT_ID and CHAT_ID.isdigit():
        allowed.add(int(CHAT_ID))
    allowed.update(_dynamic_allowed)
    return allowed

ALLOWED_USERS = _parse_allowed_users()

def refresh_allowed():
    global ALLOWED_USERS, _dynamic_allowed
    _dynamic_allowed = load_dynamic_allowed()
    ALLOWED_USERS = _parse_allowed_users()

def add_user(cid_to_add):
    global _dynamic_allowed
    try:
        cid_int = int(cid_to_add)
    except (TypeError, ValueError):
        return False
    if cid_int in _dynamic_allowed:
        return False
    _dynamic_allowed.add(cid_int)
    save_dynamic_allowed(_dynamic_allowed)
    refresh_allowed()
    return True

def remove_user(cid_to_remove):
    global _dynamic_allowed
    try:
        cid_int = int(cid_to_remove)
    except (TypeError, ValueError):
        return False
    if CHAT_ID and cid_int == int(CHAT_ID):
        return False
    if cid_int not in _dynamic_allowed:
        return False
    _dynamic_allowed.discard(cid_int)
    save_dynamic_allowed(_dynamic_allowed)
    refresh_allowed()
    return True

def is_owner(cid):
    if not cid or not CHAT_ID:
        return False
    try:
        return int(cid) == int(CHAT_ID)
    except (TypeError, ValueError):
        return False

def is_allowed(cid):
    if not cid:
        return False
    try:
        cid_int = int(cid)
    except (TypeError, ValueError):
        return False
    return cid_int in ALLOWED_USERS

# ═══════════════════════════════════════════════════════════
# الكاش
# ═══════════════════════════════════════════════════════════
def get_cached(key, ttl=120):
    if key in _cache and time.time() - _cache[key][0] < ttl:
        return _cache[key][1]
    return None

def set_cached(key, data):
    _cache[key] = (time.time(), data)

# ═══════════════════════════════════════════════════════════
# جلب وتحليل الأخبار
# ═══════════════════════════════════════════════════════════
def parse_date(date_str):
    """يحول تاريخ RSS إلى timestamp
    🔧 إصلاح: دعم صيغ متعددة (RFC 822, ISO 8601, Atom)
    """
    if not date_str:
        return 0
    # محاولة RFC 822 أولاً (الأكثر شيوعاً في RSS)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.timestamp()
    except Exception:
        pass
    # 🔧 إصلاح: محاولة ISO 8601 (مثل 2024-07-01T12:00:00Z)
    try:
        # إزالة Z في النهاية إن وُجد
        clean = date_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    # محاولة صيغ أخرى شائعة
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.timestamp()
        except Exception:
            pass
    return 0

def clean_html(text):
    """يزيل HTML tags من النص"""
    if not text:
        return ""
    # إزالة HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # إزالة HTML entities شائعة
    clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # اختصار المسافات
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

# 🆕 نظام الترجمة التلقائية
_translation_cache = {}

# قاموس المصطلحات الاقتصادية للترجمة الأفضل
ECONOMIC_TERMS = {
    "bitcoin": "بيتكوين",
    "ethereum": "إيثيريوم",
    "cryptocurrency": "العملات الرقمية",
    "crypto": "الكريبتو",
    "blockchain": "البلوكتشين",
    "federal reserve": "الفيدرالي الأمريكي",
    "interest rate": "سعر الفائدة",
    "rate cut": "خفض الفائدة",
    "rate hike": "رفع الفائدة",
    "etf": "صندوق التداول المباشر ETF",
    "spot etf": "صندوق التداول المباشر الفوري",
    "sec": "هيئة الأوراق المالية والبورصات الأمريكية",
    "approval": "الموافقة",
    "hack": "اختراق",
    "exploit": "ثغرة أمنية",
    "stablecoin": "العملة المستقرة",
    "defi": "تمويل لامركزي",
    "nft": "الرموز غير القابلة للاستبدال",
    "exchange": "بورصة",
    "trading": "التداول",
    "market": "السوق",
    "bullish": "صعودي",
    "bearish": "هبوطي",
    "rally": "ارتفاع",
    "plunge": "انهيار",
    "surge": "قفزة",
    "dump": "تصحيح حاد",
    "pump": "ضخ",
    "whale": "حيتان",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "spot": "الفوري",
    "mining": "التعدين",
    "wallet": "محفظة",
    "token": "رمز",
    "coin": "عملة",
    "altcoin": "العملات البديلة",
    "memecoin": "عملات الميم",
    "staking": "التحصيص",
    "yield": "العائد",
    "treasury": "الخزانة",
    "inflation": "التضخم",
    "recession": "الركود",
    "fed chair": "رئيس الفيدرالي",
    "powell": "باول",
    "trump": "ترامب",
    "biden": "بايدن",
    "white house": "البيت الأبيض",
    "tariff": "التعريفة الجمركية",
    "trade war": "الحرب التجارية",
    "stock market": "سوق الأسهم",
    "s&p": "مؤشر S&P",
    "nasdaq": "ناسداك",
    "dow": "داو جونز",
    "wall street": "وول ستريت",
    "treasury bond": "سندات الخزانة",
    "yuan": "اليوان",
    "dollar": "الدولار",
    "oil": "النفط",
    "gold": "الذهب",
}

def translate_to_arabic(text, force=False):
    """ترجمة النص للعربية بجودة عالية"""
    if not text or len(text) < 3:
        return text
    # اختصار النص الطويل جداً قبل الترجمة
    if len(text) > 500:
        text = text[:500]
    # تحقق من الكاش
    cache_key = hashlib.md5(text.encode()).hexdigest()[:12]
    if not force and cache_key in _translation_cache:
        return _translation_cache[cache_key]
    try:
        # Google Translate endpoint مجاني (بدون API key)
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",  # source language
            "tl": "ar",  # target language
            "dt": "t",
            "q": text
        }
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # استخراج النص المترجم
            translated_parts = []
            for sentence in data[0]:
                if sentence and sentence[0]:
                    translated_parts.append(sentence[0])
            translated = "".join(translated_parts).strip()
            if translated:
                # 🔧 إصلاح: تطبيق قاموس المصطلحات الاقتصادية لتحسين جودة الترجمة
                # نستبدل المصطلحات المغلوطة بالترجمة الصحيحة
                translated_lower = translated.lower()
                for en_term, ar_term in ECONOMIC_TERMS.items():
                    # استبدال المصطلح الإنجليزي إن ظهر في الترجمة (يحدث أحياناً)
                    if en_term in translated_lower:
                        # استبدال preserving case (مبدئي)
                        translated = re.sub(
                            re.escape(en_term),
                            ar_term,
                            translated,
                            flags=re.IGNORECASE
                        )
                _translation_cache[cache_key] = translated
                return translated
    except Exception as e:
        log.warning(f"translate err: {e}")
    return text  # في حالة الفشل، ارجع النص الأصلي

def translate_news_item(item):
    """ترجمة عنوان وملخص الخبر للعربية"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    item["title_ar"] = translate_to_arabic(title)
    if summary:
        item["summary_ar"] = translate_to_arabic(summary)
    else:
        item["summary_ar"] = ""
    return item

def extract_summary(text, max_len=200):
    """يختصر النص"""
    clean = clean_html(text)
    if len(clean) <= max_len:
        return clean
    return clean[:max_len-3] + "..."

def extract_image_from_html(html_text):
    """🆕 يستخرج رابط الصورة من HTML في RSS"""
    if not html_text:
        return ""
    # البحث عن <img src="...">
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    if match:
        return match.group(1)
    # البحث عن enclosure (مستخدم في بعض RSS)
    return ""

def parse_rss_source(source_name, source_info):
    """يجلب ويحلل RSS source واحد"""
    url = source_info["url"]
    category = source_info["category"]
    is_json = source_info.get("is_json", False)
    items = []
    try:
        if is_json:
            # Reddit JSON
            # 🔧 إصلاح: استخدام REDDIT_HEADERS المخصص لتجنب الحظر
            r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for post in data.get("data", {}).get("children", [])[:20]:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    link = "https://www.reddit.com" + d.get("permalink", "")
                    pub_ts = d.get("created_utc", 0)
                    # 🆕 استخراج الصورة من Reddit
                    image = ""
                    if d.get("preview"):
                        try:
                            image = d["preview"]["images"][0]["source"]["url"].replace("&amp;", "&")
                        except:
                            pass
                    if not image and d.get("thumbnail", "").startswith("http"):
                        image = d.get("thumbnail")
                    items.append({
                        "title": title,
                        "link": link,
                        "summary": d.get("selftext", "")[:200],
                        "image": image,
                        "source": source_name,
                        "category": category,
                        "timestamp": pub_ts,
                        "date_str": datetime.fromtimestamp(pub_ts, tz=tz).strftime('%Y-%m-%d %H:%M') if pub_ts else ""
                    })
        else:
            # RSS XML
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                # RSS 2.0
                for item in root.findall('.//item')[:20]:
                    title = item.findtext('title', '') or ""
                    link = item.findtext('link', '') or ""
                    desc = item.findtext('description', '') or ""
                    pub_date = item.findtext('pubDate', '') or ""
                    # 🆕 استخراج الصورة
                    image = extract_image_from_html(desc)
                    # محاولة استخراج من media:content أو enclosure
                    if not image:
                        media = item.find('{http://search.yahoo.com/mrss/}content')
                        if media is not None and media.get('url'):
                            image = media.get('url')
                    if not image:
                        enclosure = item.find('enclosure')
                        if enclosure is not None and enclosure.get('type', '').startswith('image'):
                            image = enclosure.get('url')
                    items.append({
                        "title": clean_html(title),
                        "link": link,
                        "summary": extract_summary(desc),
                        "image": image,
                        "source": source_name,
                        "category": category,
                        "timestamp": parse_date(pub_date),
                        "date_str": pub_date
                    })
                # Atom (مثل some feeds)
                if not items:
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    for entry in root.findall('.//atom:entry', ns)[:20]:
                        title = entry.findtext('atom:title', '', ns) or ""
                        link_elem = entry.find('atom:link', ns)
                        link = link_elem.get('href', '') if link_elem is not None else ""
                        summary = entry.findtext('atom:summary', '', ns) or entry.findtext('atom:content', '', ns) or ""
                        pub_date = entry.findtext('atom:updated', '', ns) or entry.findtext('atom:published', '', ns) or ""
                        # 🆕 استخراج الصورة من Atom
                        image = extract_image_from_html(summary)
                        items.append({
                            "title": clean_html(title),
                            "link": link,
                            "summary": extract_summary(summary),
                            "image": image,
                            "source": source_name,
                            "category": category,
                            "timestamp": parse_date(pub_date),
                            "date_str": pub_date
                        })
        log.info(f"📰 {source_name}: {len(items)} items")
    except Exception as e:
        log.warning(f"Source {source_name} err: {e}")
    return items

def get_all_news():
    """يجلب كل الأخبار من كل المصادر"""
    cached = get_cached("all_news", 120)  # كاش دقيقتين
    if cached:
        return cached
    all_items = []
    for source_name, source_info in NEWS_SOURCES.items():
        items = parse_rss_source(source_name, source_info)
        all_items.extend(items)
        # تأخير بسيط بين المصادر
        time.sleep(0.3)
    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    set_cached("all_news", all_items)
    return all_items

def classify_news(item):
    """🆕 يصنف الخبر بدقة باستخدام حدود الكلمات وفئات موسعة"""
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()
    text = f"{title} {summary}"
    categories = []
    # استخدام حدود الكلمات
    def has_word(text, word):
        pattern = r'\b' + re.escape(word) + r'\b'
        return bool(re.search(pattern, text))
    if any(has_word(text, kw) for kw in KEYWORDS_BREAKING):
        categories.append("breaking")
    if any(has_word(text, kw) for kw in KEYWORDS_FED):
        categories.append("fed")
    if any(has_word(text, kw) for kw in KEYWORDS_TRUMP):
        categories.append("trump")
    if any(has_word(text, kw) for kw in KEYWORDS_WHALES):
        categories.append("whale")
    if any(has_word(text, kw) for kw in KEYWORDS_ETF):
        categories.append("etf")
    if any(has_word(text, kw) for kw in KEYWORDS_HACK):
        categories.append("hack")
    # 🆕 فئات جديدة
    if any(has_word(text, kw) for kw in KEYWORDS_TECH):
        categories.append("tech")
    if any(has_word(text, kw) for kw in KEYWORDS_MARKET):
        categories.append("market")
    return categories

def get_coin_keywords(text):
    """🆕 يستخرج العملات بدقة باستخدام حدود الكلمات
    🔧 إصلاح: استخدام \b لتجنب المطابقة الجزئية (link في linktree)
    """
    text_lower = text.lower()
    coin_map = {
        "bitcoin": "BTC", "btc": "BTC",
        "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
        "solana": "SOL", "sol": "SOL",
        "ripple": "XRP", "xrp": "XRP",
        "cardano": "ADA", "ada": "ADA",
        "dogecoin": "DOGE", "doge": "DOGE",
        "avalanche": "AVAX", "avax": "AVAX",
        "polygon": "MATIC", "matic": "MATIC",
        "chainlink": "LINK",  # link محذوف من المفرد - يُطابق فقط كـ chainlink
        "polkadot": "DOT", "dot": "DOT",
        "litecoin": "LTC", "ltc": "LTC",
        "binance": "BNB", "bnb": "BNB",
        "tether": "USDT", "usdt": "USDT",
        "aptos": "APT", "apt": "APT",
        "arbitrum": "ARB", "arb": "ARB",
        "optimism": "OP",
        "sui": "SUI", "sei": "SEI", "toncoin": "TON",
    }
    found = set()
    for keyword, symbol in coin_map.items():
        # 🔧 إصلاح: حدود الكلمات (\b) لتجنب المطابقة الجزئية
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            found.add(symbol)
    return list(found)

# ═══════════════════════════════════════════════════════════
# بناء الرسائل
# ═══════════════════════════════════════════════════════════
def time_ago(timestamp):
    """يحول timestamp إلى نص 'منذ X دقيقة'"""
    if not timestamp:
        return ""
    diff = time.time() - timestamp
    if diff < 60:
        return "منذ لحظات"
    if diff < 3600:
        return f"منذ {int(diff/60)} دقيقة"
    if diff < 86400:
        return f"منذ {int(diff/3600)} ساعة"
    return f"منذ {int(diff/86400)} يوم"

def detect_economic_data(item):
    """🆕 يكتشف البيانات الاقتصادية في النص (السابق/المتوقع/الحالي)"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    text_lower = text.lower()
    # أنماط الأرقام الاقتصادية
    patterns = [
        # previous, expected, current
        r'previous[:\s]+([0-9.]+).*?(?:expected|forecast|estimate)[:\s]+([0-9.]+).*?(?:actual|current)[:\s]+([0-9.]+)',
        # actual, forecast, previous
        r'actual[:\s]+([0-9.]+).*?forecast[:\s]+([0-9.]+).*?previous[:\s]+([0-9.]+)',
    ]
    data = {"has_data": False, "previous": None, "expected": None, "current": None}
    for pattern in patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL)
        if match:
            groups = match.groups()
            if len(groups) >= 3:
                data["has_data"] = True
                data["previous"] = groups[0] if pattern.startswith('previous') else groups[2]
                data["expected"] = groups[1]
                data["current"] = groups[2] if pattern.startswith('previous') else groups[0]
                break
    return data

def extract_key_points(text, max_points=5):
    """🆕 يستخرج النقاط الرئيسية من النص"""
    if not text:
        return []
    # تقسيم النص إلى جمل
    sentences = re.split(r'[.!?،؛\n]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
    # اختيار الجمل الأهم (الأطول والأكثر محتوى)
    # ترتيب حسب الطول (الأطول عادة أكثر معلومات)
    sorted_sentences = sorted(sentences, key=lambda x: len(x), reverse=True)
    # أخذ أول N جمل
    points = sorted_sentences[:max_points]
    # إعادة الترتيب حسب التسلسل الأصلي
    original_order = []
    for s in sentences:
        if s in points and s not in original_order:
            original_order.append(s)
    return original_order[:max_points]

def extract_keywords(text, max_keywords=6):
    """🆕 يستخرج الكلمات المفتاحية المهمة من النص"""
    if not text:
        return []
    text_lower = text.lower()
    important_keywords = []
    # كلمات مفتاحية محددة مسبقاً
    keyword_map = {
        "bitcoin": "بيتكوين", "ethereum": "إيثيريوم", "solana": "سولانا",
        "ripple": "ريبل", "cardano": "كاردانو", "dogecoin": "دوجكوين",
        "binance": "بينانس", "tether": "تيثر", "usdt": "USDT",
        "federal reserve": "الفيدرالي", "interest rate": "سعر الفائدة",
        "rate cut": "خفض الفائدة", "rate hike": "رفع الفائدة",
        "etf": "ETF", "spot etf": "ETF فوري", "sec": "هيئة الأوراق المالية",
        "approval": "موافقة", "approved": "موافقة", "reject": "رفض",
        "hack": "اختراق", "exploit": "ثغرة", "stolen": "سرقة",
        "lawsuit": "دعوى قضائية", "sue": "رفع دعوى",
        "partnership": "شراكة", "collaboration": "تعاون",
        "launch": "إطلاق", "release": "إصدار",
        "upgrade": "ترقية", "update": "تحديث",
        "listing": "إدراج", "delisting": "إلغاء الإدراج",
        "staking": "تحصيص", "airdrop": "توزيع مجاني",
        "trump": "ترامب", "biden": "بايدن", "powell": "باول",
        "inflation": "التضخم", "recession": "الركود",
        "bull market": "سوق صاعد", "bear market": "سوق هابط",
        "all-time high": "أعلى مستوى تاريخي", "ath": "أعلى مستوى تاريخي",
        "support": "دعم", "resistance": "مقاومة",
        "bullish": "صعودي", "bearish": "هبوطي",
        "whale": "حيتان", "whales": "حيتان",
        "liquidation": "تصفية", "leverage": "رافعة مالية",
        "futures": "عقود آجلة", "options": "خيارات",
        "mining": "تعدين", "miner": "معدّن",
        "defi": "تمويل لامركزي", "nft": "NFT",
        "metaverse": "ميتافيرس", "web3": "ويب 3",
        "regulation": "تنظيم", "compliance": "امتثال",
        "treasury": "الخزانة", "bonds": "سندات",
        "tariff": "تعريفة جمركية", "trade war": "حرب تجارية",
    }
    for en_kw, ar_kw in keyword_map.items():
        if en_kw in text_lower and ar_kw not in important_keywords:
            important_keywords.append(ar_kw)
        if len(important_keywords) >= max_keywords:
            break
    return important_keywords

def fmt_news_item(item, show_summary=True, translate=True, show_header=True):
    """🆕 تنسيق مبسط: صورة + العنوان + الملخص + الرابط فقط (بدون ترويسة)
    🔧 إصلاح: استخدام time_ago() و extract_keywords() و translate_source_name()
    """
    title = item.get("title", "")
    title_ar = item.get("title_ar", "")
    summary = item.get("summary", "")
    summary_ar = item.get("summary_ar", "")
    link = item.get("link", "")
    image_url = item.get("image", "")
    source = item.get("source", "")
    timestamp = item.get("timestamp", 0)
    categories = classify_news(item)
    # ترجمة العنوان للعربية
    if translate and title and not title_ar:
        title_ar = translate_to_arabic(title)
        item["title_ar"] = title_ar
    if translate and summary and not summary_ar:
        summary_ar = translate_to_arabic(summary)
        item["summary_ar"] = summary_ar
    # العنوان النهائي (عربي فقط)
    final_title = title_ar if title_ar and translate else title
    # تحديد رمز الخبر
    if "breaking" in categories:
        icon = "🚨"
    elif "hack" in categories:
        icon = "⚠️"
    elif "fed" in categories or "trump" in categories:
        icon = "🇺🇸"
    elif "etf" in categories:
        icon = "📊"
    elif "whale" in categories:
        icon = "🐋"
    elif "tech" in categories:
        icon = "🔧"
    elif "market" in categories:
        icon = "📈"
    else:
        icon = "📰"
    # 🔧 إصلاح: استخدام translate_source_name() و time_ago()
    source_ar = translate_source_name(source)
    time_str = time_ago(timestamp)
    # البناء
    msg = ""
    msg += f"{icon} <b>{final_title}</b>\n\n"
    if show_summary:
        if summary_ar and translate:
            clean_summary = summary_ar.strip()
            if len(clean_summary) > 300:
                clean_summary = clean_summary[:297] + "..."
            msg += f"📋 {clean_summary}\n"
        elif summary:
            translated_summary = translate_to_arabic(summary[:400])
            if translated_summary and translated_summary != summary:
                clean_summary = translated_summary.strip()
                if len(clean_summary) > 300:
                    clean_summary = clean_summary[:297] + "..."
                msg += f"📋 {clean_summary}\n"
    # 🔧 إصلاح: إضافة الكلمات المفتاحية المترجمة
    keywords = extract_keywords(f"{title} {summary}")
    if keywords:
        msg += f"\n🏷️ {' • '.join(keywords[:5])}\n"
    # 🔧 إصلاح: إضافة المصدر + الوقت
    if source_ar:
        msg += f"\n📡 {source_ar}"
        if time_str:
            msg += f" • {time_str}"
        msg += "\n"
    if link:
        msg += f"🔗 <a href='{link}'>رابط المصدر</a>\n"
    return msg

def translate_source_name(source):
    """🆕 ترجمة أسماء المصادر للعربية"""
    sources_ar = {
        "CoinDesk": "كوين ديسك",
        "Cointelegraph": "كوين تيليغراف",
        "Decrypt": "ديكريبٽ",
        "Bitcoin.com": "بيتكوين دوت كوم",
        "CNBC Economy": "سي إن بي سي",
        "Federal Reserve": "الفيدرالي الأمريكي",
        "Forexlive": "فوركس لايف",
        "Reddit r/CryptoCurrency": "مجتمع الكريبتو",
    }
    return sources_ar.get(source, source)

def translate_coin_name(symbol):
    """🆕 ترجمة أسماء العملات للعربية"""
    coins_ar = {
        "BTC": "بيتكوين",
        "ETH": "إيثيريوم",
        "SOL": "سولانا",
        "XRP": "ريبل",
        "ADA": "كاردانو",
        "DOGE": "دوجكوين",
        "AVAX": "أفالانش",
        "MATIC": "بوليغون",
        "LINK": "تشين لينك",
        "DOT": "بولكادوت",
        "LTC": "لايتكوين",
        "BNB": "بينانس كوين",
        "USDT": "تيثر",
        "APT": "أبتوس",
        "ARB": "أربيترم",
        "OP": "أوبتيميزم",
        "SUI": "سوي",
        "SEI": "سي",
        "TON": "تونكوين",
    }
    return f"{symbol} ({coins_ar.get(symbol, symbol)})"

def deduplicate_news(news_list):
    """🆕 إزالة الأخبار المكررة بشكل صارم"""
    seen = set()
    unique = []
    for item in news_list:
        title = item.get("title", "").lower().strip()
        # تطبيع شديد: إزالة كل الرموز والمسافات الزائدة
        normalized = re.sub(r'[^\w\s]', '', title)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # إزالة الكلمات الشائعة في البداية (Breaking, Update, News)
        normalized = re.sub(r'^(breaking|update|news|alert|urgent)[\s:]*', '', normalized)
        # أخذ أول 60 حرف فقط للمقارنة (لتجنب التكرار مع عناوين مختلفة قليلاً)
        normalized = normalized[:60]
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(item)
    return unique

def build_latest_news(limit=10):
    """📰 آخر الأخبار"""
    news = get_all_news()
    if not news:
        return "⚠️ تعذّر جلب الأخبار. حاول لاحقاً."
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    msg = ""
    for item in news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_breaking_news(limit=5):
    """🔥 أخبار عاجلة"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    breaking = [n for n in news if "breaking" in classify_news(n) or "hack" in classify_news(n)]
    if not breaking:
        return "✅ <b>لا توجد أخبار عاجلة حالياً</b>\n\nالسوق هادئ نسبياً."
    msg = ""
    for item in breaking[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=True, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_macro_news(limit=8):
    """🇺🇸 اقتصاد كلي"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    macro = [n for n in news if n.get("category") == "macro" or
             "fed" in classify_news(n) or "trump" in classify_news(n)]
    if not macro:
        return "ℹ️ لا توجد أخبار اقتصادية حديثة."
    msg = ""
    for item in macro[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_coin_news(symbol, limit=5):
    """💎 أخبار عملة معينة"""
    symbol = symbol.upper().strip()
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    coin_news = []
    for n in news:
        coins = get_coin_keywords(f"{n.get('title', '')} {n.get('summary', '')}")
        if symbol in coins:
            coin_news.append(n)
    if not coin_news:
        return f"ℹ️ لا توجد أخبار حديثة عن <b>{symbol}</b>"
    msg = ""
    for item in coin_news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

# ═══════════════════════════════════════════════════════════
# التنبيهات التلقائية
# ═══════════════════════════════════════════════════════════
def news_hash(item):
    """hash فريد للخبر
    🔧 إصلاح: hash أذكى - يشمل العنوان (مُطبّع) + المصدر
    """
    title = item.get("title", "").lower().strip()
    # تطبيع شديد: إزالة الرموز والمسافات الزائدة
    normalized = re.sub(r'[^\w\s]', '', title)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    # إزالة الكلمات الشائعة في البداية
    normalized = re.sub(r'^(breaking|update|news|alert|urgent|just in)[\s:]*', '', normalized)
    # إضافة المصدر للـ hash لتجنب التكرار عبر مصادر مختلفة بنفس العنوان
    source = item.get("source", "").lower()
    hash_input = f"{normalized[:80]}|{source}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:12]

def is_category_allowed(category):
    """🔧 إصلاح: فحص إن كانت الفئة مفعّلة في alert_categories"""
    # mapping: category → key in alert_categories
    cat_map = {
        "breaking": "breaking",
        "hack": "breaking",      # اختراقات تُعتبر عاجلة
        "etf": "crypto",
        "tech": "tech",
        "market": "market",
        "whale": "crypto",
        "fed": "macro",
        "trump": "macro",
    }
    key = cat_map.get(category, "crypto")
    return alert_categories.get(key, True)

def scan_news_loop():
    """يفحص الأخبار الجديدة ويرسل تنبيهات للأخبار المهمة (عاجل/اختراق/تقني/سوقي)
    🔧 إصلاحات:
    - احترام alert_categories
    - تطبيق ALERT_COOLDOWN
    - استخدام deduplicate_news قبل الفلترة
    - منع التكرار عبر المصادر
    - 🆕 احترام bot_shutdown
    - 🔧 إصلاح: قراءة channel_enabled مباشرة من globals في كل دورة
    - 🆕 منع إرسال الأخبار القديمة المتراكمة أثناء فترة الإيقاف
    """
    global bot_shutdown, channel_enabled, auto_alerts_enabled, alert_categories
    global bot_resume_time, _skip_old_news_once
    time.sleep(20)
    while True:
        try:
            # 🆕 احترام الإيقاف الكامل للبوت
            if bot_shutdown:
                log.info("🔇 Bot is shutdown — skipping news scan")
                time.sleep(300)
                continue
            if not auto_alerts_enabled:
                time.sleep(300)
                continue
            # 🔧 إصلاح: إعادة تحميل الإعدادات من Gist/محلي في كل دورة
            # هذا يضمن أن أي تغيير في channel_enabled يُقرأ حتى لو لم يُرَ من thread آخر
            load_settings()
            log.info(f"📊 Settings: channel_enabled={channel_enabled}, bot_shutdown={bot_shutdown}")
            # 🆕 فحص: هل نحن في أول دورة بعد استئناف البوت؟
            # إذا نعم، نضيف كل الأخبار الحالية (القديمة) لـ sent_news_hashes دون إرسال
            if bot_resume_time > 0 and not _skip_old_news_once:
                log.info(f"🔄 First scan after resume at {datetime.fromtimestamp(bot_resume_time, tz=tz).strftime('%H:%M:%S')} — marking old news as sent")
                # مسح الكاش للحصول على أخبار طازجة
                if "all_news" in _cache:
                    del _cache["all_news"]
                old_news = get_all_news()
                old_news = deduplicate_news(old_news)
                skipped_count = 0
                for item in old_news:
                    item_ts = item.get("timestamp", 0)
                    # الأخبار الأقدم من وقت الاستئناف = قديمة، تجاوزها
                    if item_ts > 0 and item_ts < bot_resume_time:
                        h = news_hash(item)
                        if h not in sent_news_hashes:
                            sent_news_hashes.add(h)
                            skipped_count += 1
                if skipped_count > 0:
                    save_sent_news()
                    log.info(f"⏭️ Skipped {skipped_count} old news items (accumulated during shutdown)")
                _skip_old_news_once = True
                # إعادة ضبط bot_resume_time بعد المعالجة
                bot_resume_time = 0
                save_settings()
                time.sleep(60)  # انتظر دقيقة قبل بدء الفحص الحقيقي
                continue
            log.info("🔍 Scanning news for important alerts...")
            # مسح الكاش للحصول على أخبار طازجة
            if "all_news" in _cache:
                del _cache["all_news"]
            news = get_all_news()
            if not news:
                time.sleep(300)
                continue
            # 🔧 إصلاح: إزالة المكرر قبل الفلترة
            news = deduplicate_news(news)
            now = time.time()
            alerts_sent = 0
            # نفحص آخر 40 خبر
            for item in news[:40]:
                # 🆕 فحص إضافي: تجاوز الأخبار القديمة (timestamp < 30 دقيقة)
                # هذا يمنع إرسال أخبار قديمة جداً حتى لو لم تكن في sent_news_hashes
                item_ts = item.get("timestamp", 0)
                if item_ts > 0 and (now - item_ts) > 1800:  # 30 دقيقة
                    # أضفها لـ sent_news_hashes حتى لا تُفحص مرة أخرى
                    h_old = news_hash(item)
                    if h_old not in sent_news_hashes:
                        sent_news_hashes.add(h_old)
                        save_sent_news()
                    continue
                categories = classify_news(item)
                # الأخبار المهمة
                important_cats = ["breaking", "hack", "etf", "tech", "market", "whale", "fed", "trump"]
                matched_cats = [c for c in categories if c in important_cats]
                if not matched_cats:
                    continue
                # 🔧 إصلاح: احترام alert_categories - إن كانت كل الفئات المطابقة معطّلة، تخطّي
                allowed_cats = [c for c in matched_cats if is_category_allowed(c)]
                if not allowed_cats:
                    continue
                h = news_hash(item)
                # 🆕 ذاكرة دائمة: إذا الخبر أُرسل من قبل، لا تعد إرساله أبداً
                if h in sent_news_hashes:
                    continue
                # 🔧 إصلاح: تطبيق ALERT_COOLDOWN - فحص آخر تنبيه
                if h in last_alerts_hashes:
                    last_time = last_alerts_hashes[h]
                    if now - last_time < ALERT_COOLDOWN:
                        continue
                # تحديث الذاكرة الدائمة + cooldown
                sent_news_hashes.add(h)
                save_sent_news()
                last_alerts_hashes[h] = now
                # ترجمة الخبر قبل الإرسال
                translate_news_item(item)
                # إرسال للجميع - التنسيق المبسط
                msg = fmt_news_item(item, show_summary=True, translate=True)
                image_url = item.get("image", "")
                broadcast_alert(msg, image_url)
                alerts_sent += 1
            if alerts_sent > 0:
                log.info(f"🔔 Sent {alerts_sent} news alerts")
            # 🔧 إصلاح: تنظيف last_alerts_hashes من المدخلات القديمة (>24 ساعة)
            old_hashes = [h for h, t in last_alerts_hashes.items() if now - t > 86400]
            for h in old_hashes:
                del last_alerts_hashes[h]
            time.sleep(300)  # كل 5 دقائق
        except Exception as e:
            log.warning(f"scan_news_loop err: {e}")
            time.sleep(60)

# ═══════════════════════════════════════════════════════════
# إرسال الرسائل
# ═══════════════════════════════════════════════════════════
def send_telegram(chat_id, msg, image_url=None):
    """🆕 إرسال موحد: sendPhoto إذا توفرت صورة، sendMessage إذا لا
    🔧 إصلاح: معالجة أفضل لأخطاء sendPhoto + سجل سبب الفشل
    """
    if not TOKEN or not chat_id:
        return False
    try:
        if image_url and image_url.startswith("http"):
            # 🆕 إرسال كصورة مع تعليق
            # 🔧 إصلاح: التحقق من صحة الرابط وتنظيفه
            clean_url = image_url.replace("&amp;", "&").strip()
            # تجاهل الروابط التي قد تكون غير صالحة (مثلاً تحتوي مسافات)
            if " " in clean_url or len(clean_url) > 2000:
                log.warning(f"sendPhoto skipped: invalid URL length or format")
            else:
                p = {"chat_id": chat_id, "photo": clean_url, "caption": msg[:1024],
                     "parse_mode": "HTML"}
                r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                  json=p, timeout=20)
                if r.status_code == 200:
                    try:
                        if r.json().get("ok"):
                            return True
                        else:
                            err_desc = r.json().get("description", "unknown")
                            log.warning(f"sendPhoto API error: {err_desc}")
                    except Exception:
                        pass
                else:
                    log.warning(f"sendPhoto HTTP {r.status_code}")
        # لو فشل sendPhoto (مثلاً رابط غير صالح)، نرسل كنص
        # 🔧 إصلاح: تفعيل web preview ليعرض الصورة تلقائياً إن أمكن
        p = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": False}
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json=p, timeout=15)
        return True
    except Exception as e:
        log.warning(f"send_telegram err: {e}")
        return False

def send_msg(msg, kb=None, cid=None):
    """إرسال رسالة عادية (للمالك أو مستخدم محدد)
    🔧 إصلاح: تسجيل الأخطاء بدلاً من إخفائها
    """
    t = cid or CHAT_ID
    if not t or not TOKEN:
        return
    try:
        p = {"chat_id": t, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": True}
        if kb:
            p["reply_markup"] = json.dumps(kb) if isinstance(kb, dict) else kb
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json=p, timeout=15)
    except Exception as e:
        log.warning(f"send_msg err: {e}")

def send_to_channel(msg, image_url=None):
    """🆕 إرسال رسالة إلى القناة العامة (مع صورة إن وُجدت)
    🔧 إصلاح: فحص مزدوج + سجل عند الحظر
    """
    if not TOKEN or not CHANNEL_ID:
        log.info("📢 send_to_channel: BLOCKED (no TOKEN or CHANNEL_ID)")
        return False
    if not is_channel_enabled():
        log.info("📢 send_to_channel: BLOCKED by is_channel_enabled()=False")
        return False
    result = send_telegram(CHANNEL_ID, msg, image_url)
    if result:
        log.info(f"📢 Sent to channel {CHANNEL_ID}")
    return result

def broadcast_alert(msg, image_url=None):
    """🆕 إرسال التنبيه لكل المستخدمين + القناة (مع صورة إن وُجدت)
    🔧 إصلاح: احترام is_channel_enabled() و bot_shutdown + سجلات تشخيص
    """
    global bot_shutdown, channel_enabled
    # 🆕 احترام إيقاف البوت الكامل
    if bot_shutdown:
        log.info("🔇 Bot is shutdown — skipping broadcast")
        return
    # 🔧 إصلاح: فحص صريح قبل الإرسال للقناة
    channel_ok = is_channel_enabled()
    log.info(f"📡 broadcast_alert: channel_ok={channel_ok}, channel_enabled={channel_enabled}")
    if channel_ok:
        send_to_channel(msg, image_url)
    else:
        log.info("📡 broadcast_alert: SKIPPED channel (disabled by owner)")
    # إرسال للمستخدمين الخاصين
    if not TOKEN or not ALLOWED_USERS:
        send_msg(msg)
        return
    sent = 0
    for uid in ALLOWED_USERS:
        try:
            send_telegram(uid, msg, image_url)
            sent += 1
        except Exception:
            pass
    log.info(f"📡 Broadcast sent to {sent}/{len(ALLOWED_USERS)} users")

# ═══════════════════════════════════════════════════════════
# لوحات المفاتيح
# ═══════════════════════════════════════════════════════════
def main_kb():
    return {"keyboard": [
        [{"text": "📰 آخر الأخبار"}, {"text": "🔥 أخبار عاجلة"}],
        [{"text": "💎 أخبار عملتي"}, {"text": "🇺🇸 اقتصاد كلي"}],
        [{"text": "⚙️ الإعدادات"}]
    ], "resize_keyboard": True, "is_persistent": True}

# ═══════════════════════════════════════════════════════════
# معالجة التحديثات
# ═══════════════════════════════════════════════════════════
def handle_update(u):
    m = u.get("message", {})
    if m:
        chat = m.get("chat", {})
        cid = chat.get("id")
        txt = m.get("text", "").strip()
        if cid and txt:
            handle_msg(cid, txt, chat)
        return
    cb = u.get("callback_query", {})
    if cb:
        cid = cb.get("message", {}).get("chat", {}).get("id")
        d = cb.get("data", "")
        cb_id = cb.get("id", "")
        if cid and d:
            handle_cb(cid, d, cb_id)

def handle_msg(cid, txt, chat=None):
    # 🆕 احترام الإيقاف الكامل للبوت (فقط المالك يمكنه استخدام البوت)
    if bot_shutdown and not is_owner(cid):
        # رد مرة واحدة فقط برسالة الإيقاف (لتفادي الإزعاج)
        if txt == "/start":
            send_msg("🔇 <b>البوت متوقف حالياً للصيانة.</b>\n\nيرجى المحاولة لاحقاً.", None, cid)
        return
    # 🛡️ أوامر المالك فقط
    if is_owner(cid):
        if txt.startswith("/add "):
            target = txt.replace("/add ", "").strip().replace(" ", "")
            if target.isdigit():
                if add_user(target):
                    send_msg(f"✅ <b>تمت إضافة المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"ℹ️ المستخدم <code>{target}</code> موجود مسبقاً.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/add 123456789</code>", main_kb(), cid)
            return
        if txt.startswith("/remove "):
            target = txt.replace("/remove ", "").strip().replace(" ", "")
            if target.isdigit():
                if remove_user(target):
                    send_msg(f"✅ <b>تم حذف المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"❌ لا يمكن حذف <code>{target}</code>.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/remove 123456789</code>", main_kb(), cid)
            return
        if txt == "/users":
            msg = f"👥 <b>القائمة البيضاء</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += f"📊 العدد الإجمالي: {len(ALLOWED_USERS)} مستخدم\n\n"
            for i, uid in enumerate(sorted(ALLOWED_USERS), 1):
                owner_tag = " 👑" if uid == int(CHAT_ID) else ""
                msg += f"{i}. <code>{uid}</code>{owner_tag}\n"
            msg += "\n💡 للإضافة: <code>/add ID</code>\n💡 للحذف: <code>/remove ID</code>"
            send_msg(msg, main_kb(), cid)
            return

    # 🔒 فحص القائمة البيضاء
    if not is_allowed(cid):
        if txt == "/start":
            send_msg("🔒 هذا البوت خاص.\n\nتواصل مع المالك للوصول.", None, cid)
            log.warning(f"⛔ Access denied for chat_id: {cid}")
            if chat and CHAT_ID:
                first_name = chat.get("first_name", "غير معروف")
                username = chat.get("username", "")
                notify = f"🔔 <b>محاولة دخول جديدة</b>\n"
                notify += "━━━━━━━━━━━━━━━━━━\n\n"
                notify += f"👤 الاسم: {first_name}\n"
                if username:
                    notify += f"📎 المعرف: @{username}\n"
                notify += f"🆔 Chat ID: <code>{cid}</code>\n\n"
                notify += f"لإضافته أرسل: <code>/add {cid}</code>"
                send_msg(notify)
        return

    # حالة انتظار إدخال عملة
    if _user_state.get(cid) == "waiting_for_symbol":
        _user_state[cid] = None
        send_msg("⏳ جاري البحث...", cid=cid)
        send_msg(build_coin_news(txt), main_kb(), cid)
        return

    if txt == "/start":
        if is_owner(cid):
            msg = "📰 <b>بوت الأخبار الكريبتو</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📡 المصادر: CoinDesk, Cointelegraph, Decrypt, CNBC, Fed, Reddit\n"
            msg += f"🔔 التنبيهات: {'🟢 مفعّل' if auto_alerts_enabled else '🔴 معطّل'}\n"
            msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n"
            # 🔧 إصلاح: استخدام CHANNEL_LINK و CHANNEL_NAME بدلاً من كونها ميتة
            if CHANNEL_LINK:
                msg += f"📢 القناة: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>\n"
            msg += "\nاختر من القائمة بالأسفل:"
            send_msg(msg, main_kb(), cid)
        else:
            first_name = chat.get("first_name", "") if chat else ""
            msg = f"📰 <b>أهلاً {first_name}!</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📊 <b>بوت الأخبار الكريبتو والاقتصادية</b>\n"
            msg += "📡 مصادر موثوقة متعددة\n\n"
            msg += "✅ <b>تم تفعيل استقبال الأخبار</b>\n"
            msg += "⏳ سيصلك تنبيه فور ظهور خبر عاجل\n\n"
            # 🔧 إصلاح: عرض رابط القناة العامة للمستخدمين العاديين
            if CHANNEL_LINK:
                msg += f"📢 انضم لقناتنا: <a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a>\n\n"
            msg += "💡 <i>أنت مستلم للأخبار فقط.</i>"
            send_msg(msg, None, cid)
    elif txt == "📰 آخر الأخبار":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_latest_news(10), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🔥 أخبار عاجلة":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_breaking_news(5), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "💎 أخبار عملتي":
        if is_owner(cid):
            _user_state[cid] = "waiting_for_symbol"
            msg = "💎 <b>أخبار عملة معينة</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📝 أرسل رمز العملة:\n"
            msg += "مثال: <code>BTC</code> أو <code>ETH</code> أو <code>SOL</code>"
            send_msg(msg, None, cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🇺🇸 اقتصاد كلي":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_macro_news(8), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "⚙️ الإعدادات":
        if is_owner(cid):
            show_settings(cid)
        else:
            send_msg("ℹ️ الإعدادات متاحة للمالك فقط.", None, cid)
    else:
        if is_owner(cid):
            send_msg("استخدم القائمة بالأسفل", main_kb(), cid)
        else:
            send_msg("ℹ️ أنت مستلم للأخبار فقط. انتظر التنبيهات التلقائية.", None, cid)

def show_settings(cid):
    """عرض إعدادات التنبيهات
    🔧 إصلاح: عرض الفئات الحقيقية المحترمة + إضافة أزرار تبديل
    🆕 إضافة زر تبديل الإرسال للقناة + زر إيقاف البوت الكامل (للمالك فقط)
    """
    status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    shutdown_status = "🔴 متوقف" if bot_shutdown else "🟢 يعمل"
    channel_status = "🟢 مفعّل" if is_channel_enabled() else "🔴 معطّل"
    msg = "⚙️ <b>إعدادات التنبيهات</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🔔 <b>التنبيهات:</b> {status}\n"
    msg += f"🔇 <b>حالة البوت:</b> {shutdown_status}\n"
    msg += f"📢 <b>القناة العامة:</b> {channel_status}\n"
    if CHANNEL_ID:
        msg += f"   ┗ المعرف: <code>{CHANNEL_ID}</code>\n"
    msg += f"⏰ <b>الفحص كل:</b> 5 دقائق\n"
    msg += f"🔒 <b>Cooldown:</b> 6 ساعات لكل خبر\n\n"
    msg += "📊 <b>فئات التنبيه (محترمة فعلياً):</b>\n"
    msg += f"  🚨 أخبار عاجلة: {'🟢' if alert_categories.get('breaking', True) else '🔴'}\n"
    msg += f"  📰 كريبتو (ETF/حيتان): {'🟢' if alert_categories.get('crypto', True) else '🔴'}\n"
    msg += f"  🇺🇸 اقتصاد كلي (Fed/Trump): {'🟢' if alert_categories.get('macro', True) else '🔴'}\n"
    msg += f"  🔧 تقني: {'🟢' if alert_categories.get('tech', True) else '🔴'}\n"
    msg += f"  📈 سوقي: {'🟢' if alert_categories.get('market', True) else '🔴'}\n"
    # بناء لوحة المفاتيح
    kb_buttons = [
        [{"text": f"{'🔴 إيقاف' if auto_alerts_enabled else '🟢 تفعيل'} التنبيهات", "callback_data": "toggle_alerts"}],
        [
            {"text": f"{'🟢' if alert_categories.get('breaking', True) else '🔴'} عاجل", "callback_data": "toggle_breaking"},
            {"text": f"{'🟢' if alert_categories.get('crypto', True) else '🔴'} كريبتو", "callback_data": "toggle_crypto"},
        ],
        [
            {"text": f"{'🟢' if alert_categories.get('macro', True) else '🔴'} اقتصاد", "callback_data": "toggle_macro"},
            {"text": f"{'🟢' if alert_categories.get('tech', True) else '🔴'} تقني", "callback_data": "toggle_tech"},
        ],
        [
            {"text": f"{'🟢' if alert_categories.get('market', True) else '🔴'} سوقي", "callback_data": "toggle_market"},
        ],
        # 🆕 زر تبديل الإرسال للقناة (يظهر فقط إذا كان CHANNEL_ID مضبوطاً)
    ]
    if CHANNEL_ID:
        kb_buttons.append([
            {"text": f"{'🔴 إيقاف' if is_channel_enabled() else '🟢 تفعيل'} الإرسال للقناة",
             "callback_data": "toggle_channel"}
        ])
    # 🆕 زر إيقاف/تشغيل البوت الكامل (المالك فقط)
    if is_owner(cid):
        if bot_shutdown:
            kb_buttons.append([
                {"text": "🟢 تشغيل البوت (إلغاء الإيقاف)", "callback_data": "toggle_shutdown"}
            ])
        else:
            kb_buttons.append([
                {"text": "🔴 إيقاف البوت نهائياً (المالك فقط)", "callback_data": "toggle_shutdown"}
            ])
    kb_buttons.append([{"text": "✅ تم", "callback_data": "done_settings"}])
    kb = {"inline_keyboard": kb_buttons}
    send_msg(msg, kb, cid)

def handle_cb(cid, d, cb_id):
    global auto_alerts_enabled, channel_enabled, bot_shutdown, bot_resume_time, _skip_old_news_once
    if not is_allowed(cid):
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": cb_id, "text": "🔒 مرفوض"}, timeout=10)
        except Exception as e:
            log.warning(f"answerCallbackQuery err: {e}")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": "✅"}, timeout=10)
    except Exception as e:
        log.warning(f"answerCallbackQuery err: {e}")
    # 🔧 إصلاح: تبديل الفئات الفردية فعلياً
    category_toggles = {
        "toggle_breaking": "breaking",
        "toggle_crypto": "crypto",
        "toggle_macro": "macro",
        "toggle_tech": "tech",
        "toggle_market": "market",
    }
    if d == "toggle_alerts":
        auto_alerts_enabled = not auto_alerts_enabled
        save_settings()
        status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
        send_msg(f"✅ التنبيهات: <b>{status}</b>", main_kb(), cid)
    elif d in category_toggles:
        cat_key = category_toggles[d]
        alert_categories[cat_key] = not alert_categories.get(cat_key, True)
        save_settings()
        status = "🟢 مفعّل" if alert_categories[cat_key] else "🔴 معطّل"
        send_msg(f"✅ فئة {cat_key}: <b>{status}</b>", main_kb(), cid)
    elif d == "toggle_channel":
        # 🆕 تبديل الإرسال للقناة (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        if not CHANNEL_ID:
            send_msg("❌ لم يتم ضبط CHANNEL_ID في الإعدادات.", main_kb(), cid)
            return
        # تبديل القيمة: None → False, False → True, True → False
        current = is_channel_enabled()
        channel_enabled = not current
        save_settings()
        log.info(f"📢 Channel toggle: was={current}, now={channel_enabled}, saved to {SETTINGS_FILE}")
        # 🔧 إصلاح: تأكيد الحفظ
        try:
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                log.info(f"📢 Verified saved channel_enabled={saved.get('channel_enabled')}")
        except Exception as e:
            log.warning(f"📢 Could not verify save: {e}")
        status = "🟢 مفعّل" if channel_enabled else "🔴 معطّل"
        send_msg(f"📢 الإرسال للقناة: <b>{status}</b>\n\n💾 تم الحفظ في: <code>{SETTINGS_FILE}</code>", main_kb(), cid)
    elif d == "toggle_shutdown":
        # 🆕 إيقاف/تشغيل البوت الكامل (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        bot_shutdown = not bot_shutdown
        # 🆕 عند إعادة التشغيل، سجّل وقت الاستئناف لمنع إرسال الأخبار القديمة
        if not bot_shutdown:
            bot_resume_time = time.time()
            _skip_old_news_once = False  # إعادة ضبط العلم
            log.info(f"🔄 Bot resumed at {bot_resume_time} — old news will be skipped")
        else:
            log.warning(f"🛑 Bot SHUTDOWN by owner {cid}")
        save_settings()
        if bot_shutdown:
            send_msg("🔴 <b>تم إيقاف البوت نهائياً!</b>\n\n❌ لن تُرسل أي تنبيهات.\n❌ لن يستجيب لأي مستخدم (إلا المالك).\n\n💡 لإعادة التشغيل: الإعدادات → تشغيل البوت\n\nℹ️ عند إعادة التشغيل، لن تُرسل الأخبار القديمة المتراكمة أثناء الإيقاف.", main_kb(), cid)
            log.warning(f"🛑 Bot SHUTDOWN by owner {cid}")
        else:
            send_msg("🟢 <b>تم تشغيل البوت من جديد!</b>\n\n✅ التنبيهات مفعّلة.\n✅ الاستجابة عادية.\n⏭️ تم تجاوز الأخبار القديمة المتراكمة أثناء الإيقاف.", main_kb(), cid)
            log.info(f"✅ Bot RESTARTED by owner {cid}")
    elif d == "done_settings":
        send_msg("✅ تم حفظ الإعدادات", main_kb(), cid)

# ═══════════════════════════════════════════════════════════
# خادم Flask
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        u = request.get_json()
        if u:
            threading.Thread(target=handle_update, args=(u,)).start()
    except:
        pass
    return jsonify({"ok": True})

@app.route("/")
def home():
    return jsonify({"status": "running", "bot": "news", "users": len(ALLOWED_USERS),
                    "sources": len(NEWS_SOURCES)})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/ping")
def ping():
    return jsonify({"pong": True})

# ═══════════════════════════════════════════════════════════
# تشغيل البوت
# ═══════════════════════════════════════════════════════════
def self_ping():
    if not RENDER_URL:
        return
    time.sleep(30)
    while True:
        try:
            requests.get(f"{RENDER_URL}/ping", timeout=10)
        except Exception:
            pass
        time.sleep(600)

def start_bot():
    global _started
    if _started:
        return
    _started = True
    if not TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set!")
        return
    load_settings()
    load_sent_news()  # 🆕 تحميل الأخبار المُرسلة سابقاً
    wh = False
    if RENDER_URL:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                             params={"url": f"{RENDER_URL}/webhook"}, timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                wh = True
        except:
            pass
    alert_status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    channel_status = "🟢 مفعّل" if (SEND_TO_CHANNEL and CHANNEL_ID) else "🔴 معطّل"
    msg = "📰 <b>بوت الأخبار — تم التشغيل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📡 المصادر: {len(NEWS_SOURCES)} مصدر\n"
    msg += f"🔔 التنبيهات: {alert_status}\n"
    msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n"
    msg += f"📢 القناة العامة: {channel_status}\n"
    if SEND_TO_CHANNEL and CHANNEL_ID:
        msg += f"   ┗ {CHANNEL_ID}\n"
    msg += "\n📥 أرسل /start للبدء"
    send_msg(msg)

    def run_with_restart(name, target_fn, restart_delay=30):
        while True:
            try:
                log.info(f"🔄 Starting {name} thread")
                target_fn()
            except Exception as e:
                log.error(f"❌ {name} crashed: {e} — restarting in {restart_delay}s")
            time.sleep(restart_delay)

    threading.Thread(target=lambda: run_with_restart("self_ping", self_ping),
                     daemon=True).start()
    threading.Thread(target=lambda: run_with_restart("news_scan", scan_news_loop),
                     daemon=True).start()
    if not wh:
        def poll():
            global last_id
            last_id = 0
            while True:
                try:
                    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                                     params={"offset": last_id+1, "timeout": 25}, timeout=30)
                    if r.status_code == 200:
                        for u in r.json().get("result", []):
                            last_id = u.get("update_id", last_id)
                            handle_update(u)
                    else:
                        time.sleep(5)
                except:
                    time.sleep(5)
        threading.Thread(target=lambda: run_with_restart("polling", poll),
                         daemon=True).start()

start_bot()
