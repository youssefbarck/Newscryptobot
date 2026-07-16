import os, time, json, logging, threading, re, hashlib
from datetime import datetime, timezone
import pytz, requests

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
    # ═══════════════════════════════════════════════════════════
    # 🪙 مصادر كريبتو إنجليزية (مباشرة وسريعة)
    # ═══════════════════════════════════════════════════════════
    "CoinDesk": {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
        "category": "crypto", "lang": "en"
    },
    "Cointelegraph": {
        "url": "https://cointelegraph.com/rss",
        "category": "crypto", "lang": "en"
    },
    "Decrypt": {
        "url": "https://decrypt.co/feed",
        "category": "crypto", "lang": "en"
    },
    "BeInCrypto": {
        "url": "https://beincrypto.com/feed/",
        "category": "crypto", "lang": "en"
    },
    "Crypto.News": {
        "url": "https://crypto.news/feed/",
        "category": "crypto", "lang": "en"
    },
    "The Block": {
        "url": "https://www.theblock.co/rss",
        "category": "crypto", "lang": "en"
    },
    "Blockworks": {
        "url": "https://blockworks.co/feed",
        "category": "crypto", "lang": "en"
    },
    "Bitcoin Magazine": {
        "url": "https://bitcoinmagazine.com/.rss/",
        "category": "crypto", "lang": "en"
    },
    # ═══════════════════════════════════════════════════════════
    # 🏛️ اقتصاد كلّي (قرارات رسمية مؤثرة على الكريبتو)
    # ═══════════════════════════════════════════════════════════
    "Federal Reserve": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "fed", "lang": "en"
    },
    # ═══════════════════════════════════════════════════════════
    # 🌐 مصادر عامة RSS (أخبار كريبتو مُرشّحة بالبحث)
    # ═══════════════════════════════════════════════════════════
    "Google News - Crypto": {
        "url": "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+cryptocurrency+OR+crypto+regulation&hl=en&gl=US&ceid=US:en",
        "category": "crypto", "lang": "en"
    },
    "Google News - ETF": {
        "url": "https://news.google.com/rss/search?q=bitcoin+ETF+OR+ethereum+ETF+OR+spot+ETF&hl=en&gl=US&ceid=US:en",
        "category": "etf", "lang": "en"
    },
    # ═══════════════════════════════════════════════════════════
    # 🌐 مصادر عربية (كريبتو + فيدرالي فقط)
    # ═══════════════════════════════════════════════════════════
    "Google News AR - Bitcoin": {
        "url": "https://news.google.com/rss/search?q=بيتكوين+OR+العملات+الرقمية+OR+كريبتو&hl=ar&gl=EG&ceid=EG:ar",
        "category": "crypto", "lang": "ar"
    },
    "Google News AR - Fed": {
        "url": "https://news.google.com/rss/search?q=الفيدرالي+OR+أسعار+الفائدة+OR+باول&hl=ar&gl=EG&ceid=EG:ar",
        "category": "fed", "lang": "ar"
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

KEYWORDS_WHALES = [
    # 🐋 فقط شخصيات كريبتو مباشرة (تصريحاتهم تتحرك بالسوق)
    "elon musk", "michael saylor", "cathie wood", "whale", "whales",
    "blackrock", "microstrategy", "satoshi", "binance", "cz", "changpeng zhao",
    "sam bankman-fried", "sbf", "vitalik", "vitalik buterin",
    "charles hoskinson", "brian armstrong", "coinbase ceo",
    "institutional", "inflows", "outflows", "accumulation",
    # 🏛️ شخصيات تنظيمية مؤثرة مباشرة على الكريبتو
    "gary gensler", "sec chair", "sec chief",
    "larry fink", "blackrock ceo", "fink",
    # 🐋 شخصيات مؤيدة/معارضة للكريبتو
    "jack dorsey", "square ceo", "block ceo",
    "pro-crypto", "anti-crypto", "crypto advocate", "crypto critic",
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
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GIST_ID_SETTINGS = os.environ.get("GIST_ID_SETTINGS", "")  # Gist ID for news_settings.json
_GIST_ID_SENT_NEWS = os.environ.get("GIST_ID_SENT_NEWS", "")  # Gist ID for sent_news.json
_GIST_ID_ALLOWED = os.environ.get("GIST_ID_ALLOWED", "")  # Gist ID for allowed_users.json
# 🔧 إصلاح: استخدام /tmp كـ fallback محلي (موجود دائماً على Render)
# 🆕 في GitHub Actions نحفظ في المجلد الحالي ليُcommit للريبو
if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
    _PERSISTENT_DIR = os.getcwd()  # المجلد الحالي ليُcommit
else:
    _PERSISTENT_DIR = "/tmp"
SENT_NEWS_FILE = os.path.join(_PERSISTENT_DIR, "sent_news.json")
SETTINGS_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "news_settings.json")
ALLOWED_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "allowed_users.json")
sent_news_hashes = set()  # كل أخبار تم إرسالها
# 🔧 إصلاح: علم لتأجيل الحفظ (batch save) لتقليل طلبات API
_sent_news_dirty = False  # True = يوجد تغييرات غير محفوظة
_last_sent_news_save = 0  # آخر وقت حفظ (timestamp)

# ═══════════════════════════════════════════════════════════
# دوال GitHub Gist للمخزن الدائم المجاني
# ═══════════════════════════════════════════════════════════
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

def save_sent_news(force=False):
    """🆕 حفظ الأخبار المُرسلة (في Gist + محلي)
    🔧 إصلاح: حفظ مجمّع (batch) - كل 60 ثانية أو عند الإجبار
    """
    global _sent_news_dirty, _last_sent_news_save
    _sent_news_dirty = True
    now = time.time()
    # 🔧 إصلاح: حفظ فقط كل 60 ثانية أو عند الإجبار (force=True)
    if not force and (now - _last_sent_news_save) < 60:
        return
    _sent_news_dirty = False
    _last_sent_news_save = now
    content = json.dumps({"hashes": list(sent_news_hashes)[-500:]})
    # حفظ في Gist
    if _GIST_ID_SENT_NEWS:
        if _gist_set(_GIST_ID_SENT_NEWS, "sent_news.json", content):
            log.info(f"💾 Saved {len(sent_news_hashes)} hashes to Gist")
        else:
            log.warning("⚠️ Failed to save sent_news to Gist")
    # حفظ محلي كـ cache (في /tmp الذي يوجد دائماً)
    try:
        with open(SENT_NEWS_FILE, "w") as f:
            f.write(content)
    except Exception:
        pass

# 🔔 إعدادات التنبيهات
auto_alerts_enabled = True
# 🆕 إضافة فئتي الجيوسياسة والأسواق العالمية
alert_categories = {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True}
# 🔧 إصلاح: نقل الإعدادات للملف الدائم
SETTINGS_FILE = os.path.join(_PERSISTENT_DIR, "news_settings.json")
# 🆕 متغيرات قابلة للتبديل وقت التشغيل
channel_enabled = None  # None = استخدم قيمة env var الافتراضية
bot_shutdown = False  # True = البوت متوقف تماماً (المالك فقط يمكنه إعادة تشغيله)
# 🆕 تفعيل/إيقاف الملخص اليومي
daily_summary_enabled = True  # True = يرسل ملخصاً في 23:59
# 🆕 وقت إعادة التشغيل بعد إيقاف - لمنع إرسال الأخبار القديمة المتراكمة
bot_resume_time = 0  # timestamp لآخر مرة أُعيد فيها التشغيل
_skip_old_news_once = False  # علم لتجاوز الأخبار القديمة مرة واحدة بعد الاستئناف

def load_settings():
    """🔧 تحميل الإعدادات من Gist (مع fallback محلي)"""
    global auto_alerts_enabled, alert_categories, channel_enabled, bot_shutdown, bot_resume_time, daily_summary_enabled
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
                daily_summary_enabled = s.get("daily_summary_enabled", True)
                log.info(f"✅ Loaded settings from Gist (channel={channel_enabled}, shutdown={bot_shutdown}, summary={daily_summary_enabled})")
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
                daily_summary_enabled = s.get("daily_summary_enabled", True)
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
        "daily_summary_enabled": daily_summary_enabled,
    }, ensure_ascii=False, indent=2)
    # حفظ في Gist
    if _GIST_ID_SETTINGS:
        if _gist_set(_GIST_ID_SETTINGS, "news_settings.json", content):
            log.info("💾 Settings saved to Gist")
        else:
            log.warning("⚠️ Failed to save settings to Gist")
    # حفظ محلي كـ cache - 🔧 إصلاح: إنشاء المجلد أولاً
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE_LOCAL), exist_ok=True)
        with open(SETTINGS_FILE_LOCAL, "w") as f:
            f.write(content)
    except Exception:
        pass

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
    # حفظ محلي - 🔧 إصلاح: إنشاء المجلد أولاً
    try:
        os.makedirs(os.path.dirname(ALLOWED_FILE_LOCAL), exist_ok=True)
        with open(ALLOWED_FILE_LOCAL, "w") as f:
            f.write(content)
    except Exception:
        pass

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