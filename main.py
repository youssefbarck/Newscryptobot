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
    # 🔧 إصلاح: Benzinga يحظر البوتات (403) → استبدلنا بـ Crypto.News
    "Crypto.News": {
        "url": "https://crypto.news/feed/",
        "category": "crypto",
        "lang": "en"
    },
    # 🔍 مجتمعي
    # 🚫 تم حذف Reddit - ينتج محتوى هواة مع metadata غريبة (مثل [link] [تعليقات] /u/username)
    # وليس أخباراً مهنية. البوت يحتاج مصادر إخبارية احترافية فقط.
    # "Reddit r/CryptoCurrency": {
    #     "url": "https://old.reddit.com/r/CryptoCurrency/.rss",
    #     "category": "crypto",
    #     "lang": "en",
    #     "is_reddit_rss": True
    # },
    # 🆕 مصدر إضافي: NewsBTC
    "NewsBTC": {
        "url": "https://www.newsbtc.com/feed/",
        "category": "crypto",
        "lang": "en"
    },
    # 🆕🆕 مصادر موثوقة وآنية (إضافة جديدة)
    # 🌍 الجزيرة - تغطية جيوسياسية ممتازة (الشرق الأوسط، إيران، إسرائيل)
    "Al Jazeera": {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "category": "geopolitics",
        "lang": "en"
    },
    # 💼 MarketWatch - أسواق مالية وأسهم
    "MarketWatch": {
        "url": "https://www.marketwatch.com/rss/topstories",
        "category": "stocks",
        "lang": "en"
    },
    # 💼 Yahoo Finance - أسواق واقتصاد
    "Yahoo Finance": {
        "url": "https://finance.yahoo.com/news/rssindex",
        "category": "stocks",
        "lang": "en"
    },
    # 🇺🇸 CNBC Top News - أخبار عامة واقتصادية
    "CNBC Top News": {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "category": "macro",
        "lang": "en"
    },
    # 🪙 BeInCrypto - مصدر كريبتو إضافي
    "BeInCrypto": {
        "url": "https://beincrypto.com/feed/",
        "category": "crypto",
        "lang": "en"
    },
    # ═══════════════════════════════════════════════════════════
    # 🌐 مصادر عربية أصلية (لا تحتاج ترجمة - عربية فصحى)
    # ═══════════════════════════════════════════════════════════
    # 📺 Sky News Arabia - Business (اقتصاد + أسواق + نفط + ذهب)
    "Sky News Arabia - Business": {
        "url": "https://www.skynewsarabia.com/rss/business.xml",
        "category": "macro",
        "lang": "ar"
    },
    # ⚡ Sky News Arabia - Energy - محذوف (نفط/غاز ليس كريبتو)
    # "Sky News Arabia - Energy": {
    #     "url": "https://www.skynewsarabia.com/rss/energy.xml",
    #     "category": "macro",
    #     "lang": "ar"
    # },
    # 💻 Sky News Arabia - Technology (كريبتو + blockchain)
    "Sky News Arabia - Technology": {
        "url": "https://www.skynewsarabia.com/rss/technology.xml",
        "category": "crypto",
        "lang": "ar"
    },
    # 💰 Investing.com SA - السلع (ذهب + نفط)
    "Investing.com SA - Commodities": {
        "url": "https://sa.investing.com/rss/news_11.rss",
        "category": "macro",
        "lang": "ar"
    },
    # 🏛️ Investing.com SA - Economy - محذوف (فيدرالي/فائدة ليس كريبتو)
    # "Investing.com SA - Economy": {
    #     "url": "https://sa.investing.com/rss/news_14.rss",
    #     "category": "fed",
    #     "lang": "ar"
    # },
    # 📊 Investing.com SA - أسواق الأسهم
    "Investing.com SA - Stocks": {
        "url": "https://sa.investing.com/rss/news_25.rss",
        "category": "stocks",
        "lang": "ar"
    },
    # 🌍 RT Arabic - عام + اقتصاد
    "RT Arabic": {
        "url": "https://arabic.rt.com/rss",
        "category": "macro",
        "lang": "ar"
    },
    # 📰 BBC Arabic - عام + اقتصاد
    "BBC Arabic": {
        "url": "https://feeds.bbci.co.uk/arabic/rss.xml",
        "category": "macro",
        "lang": "ar"
    },
    # 🔍 Google News Arabic - بيتكوين (يجمع من كل المصادر)
    "Google News AR - Bitcoin": {
        "url": "https://news.google.com/rss/search?q=بيتكوين+OR+العملات+الرقمية&hl=ar&gl=EG&ceid=EG:ar",
        "category": "crypto",
        "lang": "ar"
    },
    # 🔍 Google News AR - Fed - محذوف (فيدرالي ليس كريبتو)
    # "Google News AR - Fed": {
    #     "url": "https://news.google.com/rss/search?q=الفيدرالي+OR+أسعار+الفائدة&hl=ar&gl=EG&ceid=EG:ar",
    #     "category": "fed",
    #     "lang": "ar"
    # },
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
    # 🆕🆕 شخصيات مؤثرة جداً (تصريحات تتحرك بها الأسواق)
    "eric trump", "donald trump jr", "don jr", "ivanka trump", "jared kushner", "melania trump",
    "melania", "trump family", "trump organization", "truth social", "trump media",
    "jd vance", "vp pick", "vice president",
    "jerome powell", "powell", "fed chair", "federal reserve chair",
    "joe biden", "kamala harris", "harris",
    "netanyahu", "benjamin netanyahu", "khamenei", "ayatollah",
    "mbs", "mohammed bin salman", "crown prince",
    "schumer", "pelosi", "mccarthy", "mcconnell", "speaker",
    "gary gensler", "sec chair", "sec chief",
    "janet yellen", "treasury secretary", "yellen",
    "bill gates", "jeff bezzos", "mark zuckerberg", "zuckerberg",
    "sam altman", "openai ceo", "altman",
    "jensen huang", "nvidia ceo", "huang",
    "tim cook", "apple ceo",
    "sundar pichai", "google ceo",
    "satya nadella", "microsoft ceo",
    "larry fink", "blackrock ceo", "fink",
    "david einhorn", "paul tudor", "carl icahn",
    "naval ravikant", "balaji srinivasan", "balaji",
    "michael dell", "dell ceo",
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

# 🆕 فئة الجيوسياسة - الأحداث التي تؤثر على الكريبتو والأسهم والفيدرالي
KEYWORDS_GEOPOLITICS = [
    # حروب وصراعات
    "war", "conflict", "military", "strike", "airstrike", "attack", "invasion", "ceasefire",
    "missile", "drone strike", "escalation", "retaliation", "offensive", "troops", "deploy",
    "nuclear", "weapon", "armed", "combat", "frontline", "battlefield",
    # دول ومناطق ساخنة
    "iran", "israel", "gaza", "palestine", "hamas", "hezbollah", "houthi",
    "russia", "ukraine", "putin", "zelensky", "kyiv", "moscow", "crimea",
    "china", "taiwan", "beijing", "xi jinping", "ccp", "chinese communist",
    "north korea", "kim jong", "pyongyang",
    "middle east", "gulf", "red sea", "suez canal", " hormuz",
    "syria", "lebanon", "yemen", "iraq", "afghanistan",
    "india", "pakistan", "kashmir",
    # طاقة ونفط (مؤثر جداً على الأسواق)
    "oil", "crude", "crude oil", "opec", "opec+", "energy crisis", "pipeline",
    "oil price", "oil surge", "oil spike", "gas price", "natural gas",
    "petroleum", "refinery", "sanctions oil",
    # عقوبات اقتصادية
    "sanction", "sanctions", "embargo", "trade ban", "economic sanction",
    "swift", "freeze assets", "seize",
    # منظمات دولية
    "nato", "un security", "united nations", "eu summit", "g7", "g20",
    "opec meeting", "opec cut", "opec decision",
    # توترات دبلوماسية
    "diplomatic crisis", "expel ambassador", "sever ties", "recall ambassador",
    "diplomatic tension", "diplomatic row",
]

# 🆕 فئة الأسواق العالمية - الأسهم والسلع التي تؤثر على الكريبتو
KEYWORDS_STOCKS = [
    # مؤشرات الأسهم
    "s&p", "s&p 500", "nasdaq", "dow jones", "dow", "wall street",
    "stock market", "equities", "stock index", "index futures",
    "tech stocks", "ai stocks", "chip stocks", "semiconductor",
    "magnificent seven", "mag 7", "famg", "faang",
    # شركات كبرى مؤثرة
    "nvidia", "apple", "microsoft", "google", "alphabet", "amazon", "meta",
    "tesla", "jpmorgan", "goldman sachs", "berkshire",
    # سلع وذهب
    "gold", "gold price", "silver", "precious metal",
    "commodities", "commodity", "copper", "lithium",
    # سندات وعوائد
    "treasury yields", "bond market", "yields surge", "yields drop",
    "10-year yield", "2-year yield", "yield curve",
    # عملات
    "dollar index", "dxy", "usd strength", "dollar surge",
    "yen", "yuan", "euro", "pound",
    # بنوك مركزية أخرى
    "ecb", "european central bank", "boj", "bank of japan", "bank of england",
    "pboc", "people's bank of china",
    # بيانات اقتصادية مؤثرة
    "jobs report", "nonfarm", "non-farm", "unemployment claims",
    "consumer sentiment", "consumer confidence", "pmi", "manufacturing",
    "services pmi", "industrial production",
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
# 🔧 إصلاح: استخدام /tmp كـ fallback محلي (موجود دائماً على Render)
# 🆕 في GitHub Actions نحفظ في المجلد الحالي ليُcommit للريبو
if _os.environ.get("GITHUB_ACTIONS") == "true" or _os.environ.get("RUN_MODE") == "oneshot":
    _PERSISTENT_DIR = _os.getcwd()  # المجلد الحالي ليُcommit
else:
    _PERSISTENT_DIR = "/tmp"
SENT_NEWS_FILE = _os.path.join(_PERSISTENT_DIR, "sent_news.json")
SETTINGS_FILE_LOCAL = _os.path.join(_PERSISTENT_DIR, "news_settings.json")
ALLOWED_FILE_LOCAL = _os.path.join(_PERSISTENT_DIR, "allowed_users.json")
sent_news_hashes = set()  # كل أخبار تم إرسالها
# 🔧 إصلاح: علم لتأجيل الحفظ (batch save) لتقليل طلبات API
_sent_news_dirty = False  # True = يوجد تغييرات غير محفوظة
_last_sent_news_save = 0  # آخر وقت حفظ (timestamp)

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
alert_categories = {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True, "geopolitics": True, "stocks": True}
# 🔧 إصلاح: نقل الإعدادات للملف الدائم
SETTINGS_FILE = _os.path.join(_PERSISTENT_DIR, "news_settings.json")
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
        _os.makedirs(_os.path.dirname(SETTINGS_FILE_LOCAL), exist_ok=True)
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
        _os.makedirs(_os.path.dirname(ALLOWED_FILE_LOCAL), exist_ok=True)
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
    # 🆕 إضافات لتحسين جودة الترجمة
    "coinbase": "كوين بيس",
    "binance": "بايننس",
    "tether": "تيثر",
    "usdt": "USDT",
    "usdc": "USDC",
    "ripple": "ريبل",
    "xrp": "XRP",
    "solana": "سولانا",
    "cardano": "كاردانو",
    "avalanche": "أفالانش",
    "polygon": "بوليجون",
    "polkadot": "بولكادوت",
    "chainlink": "تشين لينك",
    "microstrategy": "مايكروستراتيجي",
    "blackrock": "بلاك روك",
    "grayscale": "جرايسكيل",
    "fidelity": "فيديليتي",
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "upgrade": "تحديث",
    "rollout": "إطلاق",
    "launch": "إطلاق",
    "release": "إصدار",
    "target": "يستهدف",
    "targets": "يستهدف",
    "ux": "تجربة المستخدم",
    "ui": "واجهة المستخدم",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "l2": "الطبقة الثانية",
    "scaling": "التوسع",
    "verification": "التحقق",
    "verify": "التحقق",
    "user experience": "تجربة المستخدم",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "protocol": "البروتوكول",
    "decentralized": "لامركزي",
    "decentralization": "اللامركزية",
    "institutional": "مؤسسي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "fund flow": "تدفق الأموال",
    "halving": "النصفية",
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "correction": "تصحيح",
    "crash": "انهيار",
    "all-time high": "أعلى مستوى تاريخي",
    "ath": "أعلى مستوى تاريخي",
    "support": "الدعم",
    "resistance": "المقاومة",
    "volume": "حجم التداول",
    "volatility": "التقلب",
    "sentiment": "التوجه",
    "fomc": "اللجنة الفيدرالية للسوق المفتوحة",
    "cpi": "مؤشر أسعار المستهلك",
    "ppi": "مؤشر أسعار المنتج",
    "nonfarm payrolls": "الوظائف غير الزراعية",
    "jobless claims": "طلبات إعانة البطالة",
    "quantitative easing": "التيسير الكمي",
    "balance sheet": "الميزانية العمومية",
    "monetary policy": "السياسة النقدية",
    "sanction": "عقوبة",
    "sanctions": "عقوبات",
    "embargo": "حظر",
}

# 🆕🆕 قاموس الاستثناءات: أسماء لا تُترجم (تبقى بالإنجليزية)
# يشمل: أسماء العملات، الشركات، البروتوكولات، الرموز، التوكنات
# الهدف: الحفاظ على السياق المعروف للمستخدمين
TRANSLATION_EXCEPTIONS = [
    # 🔥 أمثلة شائعة تُترجم خطأً
    "sauce", "saucer", "saucerswap",
    "shiba inu", "shib", "doge", "dogelon mars",
    "pepe", "wojak", "chad",
    # 🪙 أسماء العملات الرقمية (تبقى بالإنجليزية)
    "bitcoin", "btc", "ethereum", "eth", "ether",
    "binance", "bnb", "tether", "ripple", "xrp",
    "solana", "sol", "cardano", "ada", "dogecoin",
    "avalanche", "avax", "polygon", "matic", "polkadot", "dot",
    "chainlink", "link", "litecoin", "ltc",
    "tron", "trx", "eos", "fantom", "ftm",
    "near", "aptos", "apt", "sui", "arbitrum", "arb",
    "optimism", "op", "starknet", "zksync",
    "filecoin", "fil", "arweave", "ar",
    "the graph", "grt", "render", "rndr",
    "theta", "vechain", "vet", "tezos", "xtz",
    "decentraland", "mana", "sandbox", "sand", "axie infinity", "axs",
    "bitcoin cash", "bch", "ethereum classic", "etc",
    # 🪙 عملات مستقرة (تبقى بالرموز المعروفة)
    "usdt", "usdc", "tether", "busd", "dai", "tusd", "frax",
    # 🏛️ بروتوكولات DeFi ومنصات
    "uniswap", "uni", "pancakeswap", "cake", "sushiswap", "sushi",
    "curve", "crv", "aave", "aave", "compound", "comp",
    "maker", "mkr", "synthetix", "snx", "yearn", "yfi",
    "lido", "ldo", "rocket pool", "rpl",
    # 🏢 شركات وبورصات (تبقى بالإنجليزية)
    "coinbase", "kraken", "okx", "bybit", "kucoin",
    "huobi", "gemini", "bitfinex", "crypto.com",
    "grayscale", "blackrock", "fidelity",
    "microstrategy", "mstr", "truth social", "truth media",
    # 📱 تطبيقات ومحافظ
    "metamask", "trust wallet", "phantom", "rabby",
    # 🤖 مشاريع AI
    "fetch.ai", "fet", "ocean protocol", "ocean",
    "singularitynet", "agi", "bittensor", "tao",
    # 🎮 Gaming والميم
    "floki", "bonk", "pepecoin", "memecoin",
    "illuvium", "ilv",
    # 🔧 أدوات وخدمات
    "etherscan", "blockchain.com", "coingecko", "coinmarketcap",
    # 📊 مؤشرات ورموز مالية
    "s&p 500", "s&p", "nasdaq 100", "nasdaq", "dow jones", "dow",
    "vix", "dxy",
    # 🌐 اختصارات تقنية ومالية (تبقى بالإنجليزية)
    "web3", "dao", "ico", "ido", "ieo", "ipo",
    "erc20", "erc721", "bep20", "trc20",
    "etf", "spot etf", "sec", "cftc", "fomc",
    "cpi", "ppi", "gdp", "qe", "qt",
    "defi", "nft", "tvl", "apy", "apr",
    "kyc", "aml",
    "btc.d", "altseason",
    # 🏛️ بروتوكولات وشرائع
    "mica", "fit21", "genius act", "clarity act",
    "19b-4", "s-1",
    # 👤 شخصيات (تبقى بالإنجليزية)
    "kevin warsh", "warsh", "powell", "saylor", "gensler", "vitalik", "satoshi",
    "yellen", "lagarde",
]

# تحويل القائمة إلى set للبحث السريع
_EXC_SET = set(TRANSLATION_EXCEPTIONS)

# 🆕🆕 قاموس المصطلحات العامة التي تُترجم للعربية
# يشمل: مصطلحات مالية، أحداث، حركات سعرية (وليس أسماء عملات/شركات/بروتوكولات)
GLOSSARY_AR = {
    # 💻 مصطلحات تقنية مركبة (أوصاف وليست أسماء)
    "smart wallet": "المحفظة الذكية",
    "smart contract": "العقد الذكي",
    "multi-chain": "متعدد السلاسل",
    "cross-chain": "عبر السلاسل",
    "layer 2": "الطبقة الثانية",
    "layer 1": "الطبقة الأولى",
    "mainnet": "الشبكة الرئيسية",
    "testnet": "شبكة الاختبار",
    "hot wallet": "المحفظة الساخنة",
    "cold wallet": "المحفظة الباردة",
    "hardware wallet": "محفظة الأجهزة",
    "software wallet": "محفظة البرامج",
    # 📊 مصطلحات السوق
    "bull market": "السوق الصاعد",
    "bear market": "السوق الهابط",
    "all-time high": "أعلى مستوى تاريخي",
    "all-time low": "أدنى مستوى تاريخي",
    "market cap": "القيمة السوقية",
    "market capitalization": "القيمة السوقية",
    "open interest": "المركزيات المفتوحة",
    "funding rate": "سعر التمويل",
    "long squeeze": "ضغط المراكز الطويلة",
    "short squeeze": "ضغط المراكز القصيرة",
    # 🏛️ مصطلحات مالية
    "federal reserve": "الاحتياطي الفيدرالي",
    "interest rate": "سعر الفائدة",
    "rate cut": "خفض الفائدة",
    "rate hike": "رفع الفائدة",
    "rate decision": "قرار الفائدة",
    "rate pause": "تثبيت الفائدة",
    "rate hold": "تثبيت الفائدة",
    "monetary policy": "السياسة النقدية",
    "quantitative easing": "التيسير الكمي",
    "balance sheet": "الميزانية العمومية",
    "treasury bond": "سندات الخزانة",
    "treasury yields": "عوائد الخزانة",
    "inflation data": "بيانات التضخم",
    "nonfarm payrolls": "الوظائف غير الزراعية",
    "jobless claims": "طلبات إعانة البطالة",
    "fed chair": "رئيس الفيدرالي",
    "fed meeting": "اجتماع الفيدرالي",
    # 🌍 مصطلحات جيوسياسية
    "white house": "البيت الأبيض",
    "trade war": "الحرب التجارية",
    "stock market": "سوق الأسهم",
    "wall street": "وول ستريت",
    # 🔧 مصطلحات تقنية أخرى
    "user experience": "تجربة المستخدم",
    "user interface": "واجهة المستخدم",
    "verification": "التحقق",
    "upgrade": "تحديث",
    "rollout": "إطلاق",
    "launch": "إطلاق",
    "release": "إصدار",
    "roadmap": "خارطة الطريق",
    "whitepaper": "الورقة البيضاء",
    "airdrop": "إيردروب",
    "staking": "التحصيص",
    "mining": "التعدين",
    "halving": "التنصيف",
    "hard fork": "الانقسام الصلب",
    "soft fork": "الانقسام الناعم",
    "the merge": "الدمج",
    "network upgrade": "تحديث الشبكة",
    "protocol upgrade": "تحديث البروتوكول",
    "mainnet launch": "إطلاق الشبكة الرئيسية",
    "mainnet upgrade": "تحديث الشبكة الرئيسية",
    "consensus upgrade": "تحديث الإجماع",
    "smart contract upgrade": "تحديث العقود الذكية",
    "proof of stake": "إثبات الحصة",
    "proof of work": "إثبات العمل",
    "consensus": "الإجماع",
    "validator": "المُتحقق",
    "node": "العقدة",
    "decentralized": "لامركزي",
    "decentralization": "اللامركزية",
    "institutional": "مؤسسي",
    "inflows": "تدفقات داخلة",
    "outflows": "تدفقات خارجة",
    "fund flow": "تدفق الأموال",
    "accumulation": "التراكم",
    # 🆕 كلمات شائعة في الأخبار
    "etf inflows": "تدفقات صندوق ETF",
    "etf outflows": "تدفقات خارجة من صندوق ETF",
    "spot bitcoin etf": "صندوق Bitcoin الفوري ETF",
    "spot ethereum etf": "صندوق Ethereum الفوري ETF",
    "hack": "اختراق",
    "hacked": "اختراق",
    "exploit": "ثغرة أمنية",
    "stolen": "مُسروق",
    "drained": "تم تصريفه",
    "rug pull": "احتيال",
    "breach": "اختراق أمني",
    "cyberattack": "هجوم سيبراني",
    "vulnerability": "ثغرة",
    "phishing": "تصيد",
    "compromised": "مُخترق",
    "attacker": "المهاجم",
    "hacker": "الهاكر",
    # 📊 مصطلحات حركة السعر
    "surge": "قفزة",
    "plunge": "انهيار",
    "crash": "انهيار",
    "rally": "ارتفاع",
    "correction": "تصحيح",
    "dump": "هبوط حاد",
    "pump": "ضخ",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "options": "الخيارات",
    "long": "مراكز طويلة",
    "short": "مراكز قصيرة",
    # 🌍 مصطلحات إضافية
    "sanction": "عقوبة",
    "sanctions": "عقوبات",
    "embargo": "حظر",
    "tariff": "تعريفة جمركية",
    "recession": "الركود",
    "inflation": "التضخم",
    "yuan": "اليوان",
    "dollar": "الدولار",
    "oil": "النفط",
    "gold": "الذهب",
    # 🆕 مصطلحات فك وحرق التوكنات
    "token unlock": "فك توكن",
    "token unlocking": "فك التوكنات",
    "tokens unlocked": "تم فك التوكنات",
    "vesting unlock": "فك الاستحقاق",
    "cliff unlock": "فك التوكنات المتراكمة",
    "unlock schedule": "جدول فك التوكنات",
    "token release": "إطلاق التوكنات",
    "release schedule": "جدول الإطلاق",
    "token burn": "حرق توكن",
    "coin burn": "حرق عملة",
    "burn event": "حدث حرق",
    "buyback and burn": "إعادة الشراء والحرق",
    "deflationary burn": "حرق انكماشي",
    "burn mechanism": "آلية الحرق",
    "burned tokens": "توكنات محروقة",
    # 🆕 سيولة مؤسسية
    "institutional inflows": "تدفقات مؤسسية داخلة",
    "institutional outflows": "تدفقات مؤسسية خارجة",
    "record inflows": "تدفقات قياسية",
    "record outflows": "تدفقات خارجة قياسية",
    "treasury allocation": "تخصيص الخزانة",
    "bitcoin treasury": "خزانة Bitcoin",  # 🆕 Bitcoin تبقى بالإنجليزية
    # 🆕 انهيار وتصحيح
    "flash crash": "انهيار مفاجئ",
    "massive sell-off": "بيع جماعي",
    "capitulation": "استسلام",
    "bloodbath": "مذبحة",
    "meltdown": "انهيار",
    "sharp decline": "انخفاض حاد",
    "steep decline": "انخفاض حاد",
    # 🆕 شخصيات (تُترجم للعربية)
    "satoshi": "ساتوشي",
    "vitalik": "فيتاليك",
    "saylor": "سيلور",
    "gensler": "غنسلر",
    "powell": "باول",
    "yellen": "يلين",
    "lagarde": "لاجارد",
}


def _protect_terms(text):
    """🆕 يستبدل المصطلحات المحمية بـ placeholders قبل الترجمة
    يعيد tuple: (النص مع placeholders, قاموس الاستعادة)
    🔧 إصلاح: حفظ النص الأصلي (بأحرفه الأصلية) للاستعادة
    🔧 إصلاح: استخدام placeholders برموز خاصة لا يترجمها أي محرك
    🆕 دمج: نحمي TRANSLATION_EXCEPTIONS (تبقى إنجليزية) + GLOSSARY_AR (تُستبدل بالعربية)
    """
    restore_map = {}  # placeholder → (original_text, arabic_translation_or_None)
    protected_text = text
    counter = 0

    # 🆕 دمج القائمتين
    all_terms = []
    for term in GLOSSARY_AR.keys():
        all_terms.append((term, "glossary"))
    for term in TRANSLATION_EXCEPTIONS:
        if term not in GLOSSARY_AR:
            all_terms.append((term, "keep"))

    # ترتيب: الأطول أولاً (لتجنب استبدال جزئي)
    all_terms.sort(key=lambda x: len(x[0]), reverse=True)

    for term, term_type in all_terms:
        if term in protected_text.lower():
            # 🔧 إصلاح: استخدام رموز خاصة «ZZ» + رقم + «ZZ» (Google لا يترجمها)
            placeholder = f"«ZZ{counter}ZZ»"
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            match = pattern.search(protected_text)
            if match:
                original_match = match.group()
                protected_text = pattern.sub(placeholder, protected_text, count=1)
                arabic_translation = GLOSSARY_AR.get(term.lower()) if term_type == "glossary" else None
                restore_map[placeholder] = (original_match, arabic_translation)
                counter += 1
    return protected_text, restore_map


def _restore_terms(translated_text, restore_map):
    """🆕 يعيد المصطلحات الأصلية مكان الـ placeholders بعد الترجمة
    🔧 إصلاح: الحفاظ على الأحرف الأصلية (USDT بدل usdt)
    🆕 دمج: استبدال ذكي - المختصرات تبقى إنجليزية، الأسماء تُستبدل بالعربية
    🔧 إصلاح: البحث عن أنماط متعددة للـ placeholder (قد يحرفها المترجم)
    """
    if not restore_map:
        return translated_text
    result = translated_text
    # رتّب الـ placeholders للاستبدال (الأكبر رقماً أولاً لتجنب التداخل)
    sorted_placeholders = sorted(restore_map.keys(),
                                  key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0,
                                  reverse=True)

    for placeholder in sorted_placeholders:
        original, arabic_translation = restore_map[placeholder]
        # ماذا نستبدل به؟
        replacement = arabic_translation if arabic_translation else original

        # استخراج الرقم من الـ placeholder
        match_num = re.search(r'(\d+)', placeholder)
        if not match_num:
            continue
        num_str = match_num.group(1)
        try:
            num = int(num_str)
            arabic_num = "".join("٠١٢٣٤٥٦٧٨٩"[int(d)] for d in str(num))

            # 🆕 أنماط كثيرة للبحث (Google/NLLB قد يحرف الـ placeholder)
            patterns_to_try = [
                # الشكل الأصلي «ZZ0ZZ»
                re.escape(placeholder),
                # بدون علامات «»
                re.escape(f"ZZ{num_str}ZZ"),
                # بأقواس مربعة [[0]] أو [0]
                re.escape(f"[[{num_str}]]"),
                re.escape(f"[{num_str}]"),
                re.escape(f"[[ {num_str} ]]"),
                re.escape(f"[ {num_str} ]"),
                # بأقواس مدورة ((0))
                re.escape(f"(({num_str}))"),
                # بأرقام عربية
                re.escape(f"«ZZ{arabic_num}ZZ»"),
                re.escape(f"[[{arabic_num}]]"),
                re.escape(f"[[ {arabic_num} ]]"),
                # أنماط مرنة (regex)
                r"«\s*ZZ\s*" + re.escape(num_str) + r"\s*ZZ\s*»",
                r"\[\[\s*" + re.escape(num_str) + r"\s*\]\]",
                r"\[\s*" + re.escape(num_str) + r"\s*\]",
                r"\(\s*" + re.escape(num_str) + r"\s*\)",
                r"«\s*ZZ\s*" + re.escape(arabic_num) + r"\s*ZZ\s*»",
                r"\[\[\s*" + re.escape(arabic_num) + r"\s*\]\]",
                # نمط عام: أي رمز غير حرفي + الرقم + أي رمز غير حرفي
                r"[«\[\(]{1,2}\s*" + re.escape(num_str) + r"\s*[»\]\)]{1,2}",
                r"[«\[\(]{1,2}\s*" + re.escape(arabic_num) + r"\s*[»\]\)]{1,2}",
            ]
            for pat in patterns_to_try:
                new_result = re.sub(pat, replacement, result, flags=re.IGNORECASE)
                if new_result != result:
                    result = new_result
                    break
        except Exception:
            result = re.sub(re.escape(placeholder), replacement, result, flags=re.IGNORECASE)

    # 🆕 تنظيف شامل لأي placeholders متبقية (أي شكل من الأشكال)
    result = re.sub(r"«\s*ZZ\s*\d+\s*ZZ\s*»", "", result)
    result = re.sub(r"«\s*ZZ\s*[٠-٩]+\s*ZZ\s*»", "", result)
    result = re.sub(r"\[\[\s*\d+\s*\]\]", "", result)
    result = re.sub(r"\[\[\s*[٠-٩]+\s*\]\]", "", result)
    result = re.sub(r"\[\s*\d+\s*\]", "", result)
    result = re.sub(r"\[\s*[٠-٩]+\s*\]", "", result)
    result = re.sub(r"ZZ\s*\d+\s*ZZ", "", result)
    result = re.sub(r"ZZ\s*[٠-٩]+\s*ZZ", "", result)
    return result


_deepl_disabled_until = 0  # 🆕 تعطيل DeepL مؤقتاً عند فشل الاتصال لتقليل التحذيرات

# ════════════════════════════════════════════════════════════════════
# 🌟 محرك الترجمة الوحيد: Gemini API (إعادة صياغة صحفية احترافية)
# ════════════════════════════════════════════════════════════════════
# ✅ يحوّل الخبر الإنجليزي إلى خبر صحفي عربي احترافي ومختصر
# ✅ يحافظ على جميع المعلومات دون إضافة أي معلومات جديدة
# ✅ يحافظ على أسماء العملات والشركات بالإنجليزية (Bitcoin, Binance, SEC)
# ✅ يتجاهل اسم المصدر إن وُجد في النهاية
# ✅ يتجاهل ميتاداتا Reddit ووسوم HTML
# 🚫 تم إزالة: Z.AI, deep-translator, Google REST, NLLB
_gemini_model = None
_gemini_init_failed = False


def _init_gemini():
    """تهيئة Gemini API - اكتشاف تلقائي للنموذج المتاح"""
    global _gemini_model, _gemini_init_failed
    if _gemini_model is not None or _gemini_init_failed:
        return
    try:
        import google.generativeai as genai
        # دعم عدة أسماء للمتغير
        api_key = (
            _os.environ.get("GEMINI_API_KEY") or
            _os.environ.get("gemini_api_key") or
            _os.environ.get("GEMINI_KEY") or
            _os.environ.get("gemini_key") or
            _os.environ.get("GOOGLE_API_KEY") or
            _os.environ.get("google_api_key") or
            ""
        )
        if not api_key:
            log.warning("⚠️ No Gemini API key found")
            _gemini_init_failed = True
            return
        genai.configure(api_key=api_key)

        system_prompt = (
            "أنت محرر صحفي محترف متخصص في أخبار الكريبتو والأسواق المالية. "
            "مهمتك: إعادة صياغة الأخبار الإنجليزية بالعربية الفصحى بأسلوب صحفي احترافي. "
            "قواعد صارمة: (1) اكتب بالعربية الفصحى فقط. "
            "(2) أعد الصياغة وليس ترجمة حرفية. "
            "(3) حافظ على جميع المعلومات والحقائق والأرقام دون إضافة. "
            "(4) اترك أسماء العملات والشركات والبروتوكولات بالإنجليزية: "
            "Bitcoin, Ethereum, Binance, USDT, USDC, SEC, ETF, MicroStrategy, "
            "BlackRock, Coinbase, Solana, Cardano, XRP, Tether, Ripple, Litecoin, "
            "Dogecoin, Polkadot, Chainlink, Avalanche, Polygon, Arbitrum, Uniswap, "
            "Aave, Curve, Grayscale, Fidelity, Kraken, Kevin Warsh, Powell. "
            "(5) ترجم المصطلحات: hack=اختراق, exploit=ثغرة, crash=انهيار, "
            "surge=قفزة, plunge=انهيار, stolen=مُسروقة, drained=تم تصريفها, "
            "token unlock=فك توكن, token burn=حرق توكن, hard fork=انقسام صلب. "
            "(6) تجاهل اسم المصدر في النهاية (CoinDesk, Reuters, CNBC). "
            "(7) تجاهل ميتاداتا Reddit: [link], [تعليقات], /u/username. "
            "(8) لا تضف إيموجي أو مقدمات. (9) أكمل كل جملة ولا تقطعها. "
            "(10) أعد فقط النص العربي المُعاد صياغته."
        )

        # اكتشاف النموذج المتاح
        candidate_models = [
            "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-exp",
            "gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-flash-latest",
        ]
        for model_name in candidate_models:
            try:
                _gemini_model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt
                )
                test_resp = _gemini_model.generate_content(
                    "test", generation_config={"max_output_tokens": 5}
                )
                if test_resp and test_resp.text:
                    log.info(f"✅ Gemini ready: {model_name}")
                    return
            except Exception as e:
                _gemini_model = None
                continue

        # اكتشاف تلقائي عبر list_models
        try:
            for m in genai.list_models():
                if ("generateContent" in [meth.name for meth in m.supported_generation_methods]
                        and "flash" in m.name.lower()):
                    _gemini_model = genai.GenerativeModel(
                        model_name=m.name, system_instruction=system_prompt
                    )
                    log.info(f"✅ Gemini ready (discovered): {m.name}")
                    return
        except Exception as e:
            log.warning(f"Model listing failed: {e}")

        log.warning("⚠️ No working Gemini model found")
        _gemini_init_failed = True
    except Exception as e:
        log.warning(f"⚠️ Gemini init failed: {e}")
        _gemini_init_failed = True


def _translate_with_gemini(text):
    """إعادة صياغة الخبر بالعربية الفصحى عبر Gemini API"""
    if _gemini_init_failed:
        return None
    _init_gemini()
    if _gemini_model is None:
        return None
    try:
        prompt = (
            f"أعد صياغة النص الإخباري التالي باللغة العربية الفصحى، "
            f"بأسلوب صحفي احترافي واضح ومختصر. "
            f"هذه إعادة صياغة وليست ترجمة حرفية. "
            f"حافظ على جميع المعلومات والحقائق والأرقام كما هي، "
            f"ولا تضف أي معلومات أو آراء من عندك. "
            f"اللغة الهدف: العربية الفصحى فقط. "
            f"اكتب 1 إلى 4 جمل كاملة (لا تقطع الجمل).\n\n"
            f"النص الأصلي:\n{text}\n\n"
            f"النص العربي المعاد صياغته:"
        )
        response = _gemini_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.3, "top_p": 0.8, "top_k": 40,
                "max_output_tokens": 2048,
            }
        )
        if response and response.text:
            result = response.text.strip().strip('"\'`')
            for prefix in ["النص العربي:", "النص العربي المعاد صياغته:", "الترجمة:", "الصياغة:"]:
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()
            return result if len(result) > 5 else None
        return None
    except Exception as e:
        log.warning(f"Gemini translate err: {e}")
        return None


def translate_to_arabic(text, force=False):
    """ترجمة النص للعربية - محرك وحيد: Gemini API (إعادة صياغة صحفية)"""
    if not text or len(text) < 3:
        return text
    if len(text) > 2000:
        text = text[:2000]
    cache_key = hashlib.md5(text.encode()).hexdigest()[:12]
    if not force and cache_key in _translation_cache:
        return _translation_cache[cache_key]

    translated = _translate_with_gemini(text)
    if translated:
        translated = _cleanup_translation(translated)
        _translation_cache[cache_key] = translated
        return translated

    log.warning("Gemini failed - returning placeholder")
    return None  # 🆕 نرجع None بدل النص الإنجليزي


    return text



def _cleanup_translation(text):
    """🆕 تنظيف شامل للنص المترجم من المخلفات والأخطاء الشائعة
    يزيل:
    - بقايا الـ placeholders (ar, ZZ, Uni, أرقام مفردة بين قوسين)
    - الكلمات الإنجليزية المعلقة التي تسربت
    - المسافات الزائدة
    - علامات الترقيم المكررة
    🆕🆕 قائمة موسعة جداً من الكلمات المتسربة المعروفة
    """
    if not text:
        return text

    result = text

    # 1️⃣ إزالة بقايا الـ placeholders
    result = re.sub(r"«\s*ZZ\s*\d+\s*ZZ\s*»", "", result)
    result = re.sub(r"ZZ\s*\d+\s*ZZ", "", result)
    result = re.sub(r"\[\[\s*\d+\s*\]\]", "", result)
    result = re.sub(r"\[\s*\d+\s*\]", "", result)
    result = re.sub(r"\(\s*\d+\s*\)", "", result)

    # 2️⃣ قائمة موسعة جداً من الكلمات الإنجليزية المتسربة المعروفة
    # هذه كلمات تظهر بسبب أخطاء الترجمة الآلية
    suspicious_words = [
        # رموز لغات (من NLLB/Google)
        "uni", "zzz", "zz", "xx", "yy", "arb", "latn", "arab", "eng",
        "eng_latn", "ar", "en", "fr", "de", "es", "zh", "ja", "ko", "ru",
        # رموز تقنية متسربة
        "tron", "sol", "link", "dot", "ada", "atom", "near", "sui", "apt",
        "rss", "xml", "html", "json", "http", "https", "url", "api",
        # كلمات meta
        "content", "title", "description", "summary", "image", "thumbnail",
        # كلمات قصيرة متسربة
        "tar", "raw", "src", "alt", "tag", "div", "span", "class",
    ]
    for word in suspicious_words:
        # فقط لو ظهرت ككلمة منفصلة (3 حروف أو أقل)
        if len(word) <= 4:
            result = re.sub(r"\b" + word + r"\b", "", result, flags=re.IGNORECASE)

    # 🆕 2.5️⃣ إزالة الكلمات الإنجليزية القصيرة المعلقة (1-4 حروف)
    # التي تظهر بين نص عربي (placeholder leaks من NLLB)
    # نمط: نص عربي + مسافة + كلمة إنجليزية قصيرة + مسافة + نص عربي
    result = re.sub(
        r"([\u0600-\u06FF])\s+[a-zA-Z]{1,4}\s+([\u0600-\u06FF])",
        r"\1 \2",
        result
    )
    # نمط: بداية النص + كلمة إنجليزية قصيرة + مسافة + نص عربي
    result = re.sub(
        r"^[a-zA-Z]{1,4}\s+([\u0600-\u06FF])",
        r"\1",
        result
    )
    # نمط: نص عربي + مسافة + كلمة إنجليزية قصيرة في النهاية
    result = re.sub(
        r"([\u0600-\u06FF])\s+[a-zA-Z]{1,4}$",
        r"\1",
        result
    )

    # 3️⃣ إزالة الأقواس الفارغة والعلامات الفارغة
    result = re.sub(r"\(\s*\)", "", result)
    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"«\s*»", "", result)
    result = re.sub(r"\{\s*\}", "", result)
    result = re.sub(r"'\s*'", "", result)
    result = re.sub(r'"\s*"', "", result)
    result = re.sub(r"''", "", result)
    result = re.sub(r'""', "", result)

    # 4️⃣ إزالة المسافات الزائدة
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+\.", ".", result)
    result = re.sub(r"\s+,", ",", result)
    result = re.sub(r"\.\s*\.\s*\.", ".", result)
    result = re.sub(r"\.\s*\.\s*", ". ", result)
    result = re.sub(r"\s*,\s*", "، ", result)
    result = re.sub(r"\s+،", "،", result)

    # 5️⃣ إزالة علامات الاقتباس الفردية الغريبة
    result = re.sub(r"''+", "", result)
    result = re.sub(r"'(?:\s*'')+", "", result)

    # 6️⃣ تنظيف البداية والنهاية
    result = result.strip()
    result = result.strip(" .,،:؛")
    result = result.strip()

    # 7️⃣ إزالة الكلمات المكررة المتجاورة
    result = re.sub(r"\b(\w+)\s+\1\b", r"\1", result)

    # 🆕 8️⃣ إزالة الكلمات الإنجليزية المعلقة المتبقية
    # (التي لا معنى لها في سياق عربي)
    # نمط: كلمة إنجليزية (1-4 حروف) محاطة بعلامات ترقيم عربية
    result = re.sub(
        r"([\u0600-\u06FF،؛.])\s+[a-zA-Z]{1,4}\s*([\u0600-\u06FF،؛.])",
        r"\1 \2",
        result
    )

    # 🆕 9️⃣ تنظيف نهائي للمسافات
    result = re.sub(r"\s+", " ", result)
    result = result.strip()

    return result

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

def _strip_source_from_title(title, source_name=""):
    """🆕 يزيل اسم المصدر من نهاية العنوان
    بعض مصادر RSS تضيف اسم المصدر في نهاية العنوان مثل:
    "Senate CLARITY Act... - Dow Jones" أو "Bitcoin crashes | CoinDesk"
    """
    if not title or not source_name:
        return title
    cleaned = title
    # أنماط شائعة: " - Dow Jones" أو " | CoinDesk" أو " — InvestingLive"
    # نبحث عن اسم المصدر في النهاية مع فاصل
    source_lower = source_name.lower()
    cleaned_lower = cleaned.lower()
    # أنماط الفواصل الشائعة
    separators = [" - ", " | ", " — ", " – ", " :: "]
    for sep in separators:
        if sep in cleaned_lower:
            parts = cleaned_lower.rsplit(sep, 1)
            if len(parts) == 2:
                last_part = parts[1].strip()
                # لو الجزء الأخير يحتوي على اسم المصدر (أو العكس)
                if (source_lower in last_part or last_part in source_lower
                    or len(last_part) < 30):  # جزء قصير = على الأغلب اسم المصدر
                    # أعد النص الأصلي بدون الجزء الأخير
                    idx = cleaned_lower.rfind(sep)
                    if idx > 10:  # تأكد أن العنوان ليس قصيراً جداً
                        cleaned = cleaned[:idx].strip()
                        break
    return cleaned


def parse_rss_source(source_name, source_info):
    """يجلب ويحلل RSS source واحد"""
    url = source_info["url"]
    category = source_info["category"]
    is_json = source_info.get("is_json", False)
    is_reddit_rss = source_info.get("is_reddit_rss", False)
    items = []
    try:
        if is_json:
            # Reddit JSON (قديم)
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
            # 🔧 إصلاح: استخدام REDDIT_HEADERS لمصادر Reddit RSS
            headers_to_use = REDDIT_HEADERS if is_reddit_rss else HEADERS
            r = requests.get(url, headers=headers_to_use, timeout=15)
            # Reddit قد يرجع 429 لكن مع محتوى صالح
            if r.status_code == 200 or (is_reddit_rss and r.status_code == 429 and r.text):
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
                        "title": _strip_source_from_title(clean_html(title), source_name),
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
                            "title": _strip_source_from_title(clean_html(title), source_name),
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
    """🆕 يصنف الخبر بدقة باستخدام حدود الكلمات وفئات موسعة
    🔧 إصلاح: إضافة فئتي الجيوسياسة والأسواق العالمية
    """
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
    # 🆕 فئة الجيوسياسة (حروب، إيران، إسرائيل، روسيا، نفط، إلخ)
    if any(has_word(text, kw) for kw in KEYWORDS_GEOPOLITICS):
        categories.append("geopolitics")
    # 🆕 فئة الأسواق العالمية (أسهم، ذهب، سندات، بنوك مركزية)
    if any(has_word(text, kw) for kw in KEYWORDS_STOCKS):
        categories.append("stocks")
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

def detect_content_type(item):
    """🆕 يكتشف طبيعة المنشور (خبر، تحذير، قصة شخصية) ويعيد ترويسة مميزة"""
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()
    source = item.get("source", "").lower()
    text = f"{title} {summary}"
    
    # 🚨 1. تحذير احتيال/اختراق
    scam_keywords = ["rug pull", "scam", "phishing", "fraud", "beware", "stay away", 
                     "do not use", "warning", "alert", "hacked", "stolen", "drained",
                     "lost my", "lost everything", "got scammed", "my funds", "drained",
                     "malicious", "fake", "impersonator", "drain"]
    if any(kw in text for kw in scam_keywords):
        return "🚨 <b>تحذير أمني / احتيال</b>"
    
    # 👤 2. قصة/تجربة شخصية (غالباً من Reddit)
    story_keywords = ["i lost", "i got", "my experience", "how i lost", "my mistake", 
                      "lesson learned", "i was", "i sent", "i accidentally", "my wallet",
                      "what i learned", "my story", "i fell for"]
    if "reddit" in source and any(kw in text for kw in story_keywords):
        return "👤 <b>قصة / تجربة شخصية</b>"
    
    # 📰 3. خبر عادي (افتراضي)
    return "📰 <b>خبر عام</b>"


def get_market_sentiment(item):
    """🆕 يحلل سياق الخبر لتحديد تأثيره على السوق (إيجابي/سلبي/معتدل)"""
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()
    text = f"{title} {summary}"
    
    # كلمات إيجابية (تأثير صاعد/طيب للسوق)
    positive_keywords = [
        "surge", "rally", "bullish", "soar", "pump", "breakout", "all-time high", "ath",
        "approval", "approved", "adopt", "adoption", "partnership", "accumulate", "accumulation",
        "inflows", "buy", "bull", "upside", "rally", "gain", "gains", "jump", "boom",
        "spot etf", "pro-crypto", "friendly", "support", "embrace", "mainstream",
        "upgrade", "milestone", "achievement", "launch", "success"
    ]
    
    # كلمات سلبية (تأثير هابط/سيئ للسوق)
    negative_keywords = [
        "crash", "plunge", "bearish", "dump", "bear", "selloff", "sell-off", "liquidation",
        "ban", "banned", "reject", "rejected", "lawsuit", "sues", "sued", "crackdown",
        "hack", "exploit", "stolen", "drained", "rug pull", "fraud", "scam", "outflows",
        "fine", "penalty", "arrest", "indictment", "sec", "gary gensler", "war", "attack",
        "miss", "missed", "delay", "postpone", "fear", "panic", "decline", "drop", "fall"
    ]
    
    pos_count = sum(1 for kw in positive_keywords if kw in text)
    neg_count = sum(1 for kw in negative_keywords if kw in text)
    
    if pos_count > neg_count:
        return "🟢 <b>تأثير متوقع: إيجابي صاعد 📈</b>"
    elif neg_count > pos_count:
        return "🔴 <b>تأثير متوقع: سلبي هابط 📉</b>"
    else:
        return "🟡 <b>تأثير متوقع: معتدل / محايد ➖</b>"


def fmt_news_item(item, show_summary=True, translate=True, show_header=True):
    """🆕 تنسيق جديد مبسط:
    🔵 [العنوان المترجم مع إيموجي العملات 💰]
    ✉️
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
    # العنوان النهائي - 🆕🆕 إجبار الترجمة بالعربية (لا نستخدم النص الإنجليزي أبداً)
    # لو فشل Gemini، نحاول مرة ثانية، ولو فشل نضع علامة واضحة
    if (not title_ar or title_ar == title) and translate and title:
        title_ar = translate_to_arabic(title, force=True)
    final_title = title_ar if title_ar and title_ar != title else "⚠️ تعذرت ترجمة هذا الخبر"

    # 🚫 تم حذف نظام إيموجي العملات - كان يسبب أخطاء كارثية
    # (يطابق "sol" في "Solomon"، "tron" في "Patron"، "link" في "LinkedIn")

    # البناء بالشكل الجديد المبسط
    msg = ""
    msg += f"🔵 {final_title}\n"

    # إضافة الملخص إن وُجد (مترجم للعربية)
    if show_summary:
        if summary_ar and translate:
            clean_summary = summary_ar.strip()
            # 🆕 إزالة أي نقاط معلقة في النهاية (من قص الكلمات)
            clean_summary = clean_summary.rstrip("…")
            clean_summary = clean_summary.rstrip(" ")
            # 🆕🆕 لا نقص - نعرض الملخص كاملاً (Gemini يكتبه مختصراً)
            # فقط لو كان طويلاً جداً (> 800 حرف)، نقص عند آخر نقطة كاملة
            if len(clean_summary) > 800:
                cut_at = clean_summary[:800].rfind(".")
                if cut_at > 200:
                    clean_summary = clean_summary[:cut_at + 1]
                else:
                    # لو ما فيش نقطة، نقص عند آخر مسافة
                    cut_at = clean_summary[:800].rfind(" ")
                    if cut_at > 200:
                        clean_summary = clean_summary[:cut_at] + "..."
                    else:
                        clean_summary = clean_summary[:800] + "..."
            if clean_summary:
                msg += f"\n{clean_summary}\n"
        elif summary:
            translated_summary = translate_to_arabic(summary[:1500])
            if translated_summary and translated_summary != summary:
                clean_summary = translated_summary.strip()
                clean_summary = clean_summary.rstrip("…")
                clean_summary = clean_summary.rstrip(" ")
                if len(clean_summary) > 800:
                    cut_at = clean_summary[:800].rfind(".")
                    if cut_at > 200:
                        clean_summary = clean_summary[:cut_at + 1]
                    else:
                        cut_at = clean_summary[:800].rfind(" ")
                        if cut_at > 200:
                            clean_summary = clean_summary[:cut_at] + "..."
                        else:
                            clean_summary = clean_summary[:800] + "..."
                if clean_summary:
                    msg += f"\n{clean_summary}\n"

    # 🚫 تم حذف رابط المصدر بناءً على طلب المستخدم

    # ✉️ في النهاية
    msg += "\n✉️\n"

    return msg

def translate_source_name(source):
    """🆕 ترجمة أسماء المصادر للعربية
    🆕🆕 إضافة المصادر الجديدة الموثوقة
    """
    sources_ar = {
        "CoinDesk": "كوين ديسك",
        "Cointelegraph": "كوين تيليغراف",
        "Decrypt": "ديكريبٽ",
        "Bitcoin.com": "بيتكوين دوت كوم",
        "CNBC Economy": "سي إن بي سي - اقتصاد",
        "CNBC White House": "سي إن بي سي - البيت الأبيض",
        "CNBC Top News": "سي إن بي سي - عام",
        "Federal Reserve": "الفيدرالي الأمريكي",
        "Forexlive": "فوركس لايف",
        "Reddit r/CryptoCurrency": "مجتمع الكريبتو",
        "Crypto.News": "كريبتو نيوز",
        "NewsBTC": "نيوز بي تي سي",
        # 🆕 مصادر جديدة
        "Al Jazeera": "الجزيرة",
        "MarketWatch": "ماركت ووتش",
        "Yahoo Finance": "ياهو فاينانس",
        "BeInCrypto": "بي إن كريبتو",
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
    """🔧 إصلاح: فحص إن كانت الفئة مفعّلة في alert_categories
    🆕 إضافة فئتي الجيوسياسة والأسواق العالمية
    """
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
        # 🆕 فئات جديدة
        "geopolitics": "geopolitics",  # حروب، إيران، نفط، إلخ
        "stocks": "stocks",            # أسهم، ذهب، سندات
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
            # 🆕 سجل تشخيصي: كم خبراً متاحاً وكم مستوفياً للشروط
            total_news = len(news)
            important_news = 0
            already_sent = 0
            old_news_skipped = 0
            # نفحص آخر 40 خبر
            for item in news[:40]:
                # 🆕 فحص إضافي: تجاوز الأخبار القديمة (timestamp < 30 دقيقة)
                # هذا يمنع إرسال أخبار قديمة جداً حتى لو لم تكن في sent_news_hashes
                item_ts = item.get("timestamp", 0)
                if item_ts > 0 and (now - item_ts) > 1800:  # 30 دقيقة
                    old_news_skipped += 1
                    # أضفها لـ sent_news_hashes حتى لا تُفحص مرة أخرى
                    h_old = news_hash(item)
                    if h_old not in sent_news_hashes:
                        sent_news_hashes.add(h_old)
                        save_sent_news()
                    continue
                categories = classify_news(item)
                # الأخبار المهمة
                important_cats = ["breaking", "hack", "etf", "tech", "market", "whale", "fed", "trump", "geopolitics", "stocks"]
                matched_cats = [c for c in categories if c in important_cats]
                if not matched_cats:
                    continue
                # 🚨 فلتر صارم جداً: فقط الأحداث المحددة
                # 1) اختراق/سرقة  2) انهيار/تصحيح حاد  3) سيولة مؤسسية كبيرة
                # 4) تحديث برمجي  5) فك توكن  6) حرق توكن  7) قرارات الفائدة
                news_text = (item.get("title", "") + " " + item.get("summary", "")).lower()

                # 🆕🆕 مسار خاص للأخبار العربية (تتخطى الفلترة الإنجليزية)
                # الأخبار العربية أصلية ولا تحتاج ترجمة، فلترتها مختلفة
                source_lang = ""
                for src_name, src_info in NEWS_SOURCES.items():
                    if src_name == item.get("source", ""):
                        source_lang = src_info.get("lang", "en")
                        break

                if source_lang == "ar":
                    # فلترة عربية صارمة - فقط الأحداث المهمة
                    ar_critical_keywords = [
                        # 1) اختراق وسرقة
                        "اختراق", "اخترق", "سرقة", "سُرق", "تم اختراق", "ثغرة", "احتيال",
                        "استغلال", "اختراقات", "سايبر", "هجوم إلكتروني",
                        # 2) انهيار وتصحيح
                        "انهيار", "انهار", "تدهور", "هبوط حاد", "سقوط", "تراجع حاد",
                        "بيع جماعي", "تصحيح", "تصفية", "ضغط",
                        # 3) سيولة مؤسسية
                        "تدفقات", "تدفق", "استثمارات مؤسسية", "شراء كبير",
                        "مايكروستراتيجي", "بلاك روك", "مؤسسي",
                        # 4) تحديث برمجي
                        "تحديث", "ترقية", "التنصيف", "انقسام", "تحديث الشبكة",
                        "إطلاق الشبكة", "الشبكة الرئيسية",
                        # 5) فك/حرق توكن
                        "فك توكن", "إلغاء تأمين", "حرق توكن", "حرق عملة", "إتلاف",
                        # 🆕 6) تصريحات كيفن وارش (المرشح لرئاسة الفيدرالي)
                        "كيفن وارش", "وارش", "kevin warsh", "warsh",
                        # 🚫 تم إلغاء أخبار الفائدة والفيدرالي - فقط كريبتو
                        # 7) عملات وأسماء مهمة
                        "بيتكوين", "إيثيريوم", "بايننس", "كريبتو", "عملات رقمية",
                        "عملات مشفرة", "البلوكتشين", "USDT", "USDC",
                        # 8) تنظيم
                        "موافقة", "رفض", "قانون", "تنظيم", "حظر", "عقوبات",
                    ]
                    ar_rejection_keywords = [
                        "تحليل", "توقعات", "متوقع", "قد يصل", "قد يصل إلى",
                        "أفضل 10", "أفضل 5", "كيف تشتري", "شرح",
                        "دليل", "ما هي", "تعرف على",
                    ]
                    has_ar_critical = any(kw in news_text for kw in ar_critical_keywords)
                    has_ar_rejection = any(kw in news_text for kw in ar_rejection_keywords)
                    if not has_ar_critical or has_ar_rejection:
                        continue
                    # ✅ خبر عربي مهم - تم القبول (بدون حاجة للترجمة)
                    important_news += 1
                    allowed_cats = [c for c in matched_cats if is_category_allowed(c)]
                    if not allowed_cats:
                        continue
                    h = news_hash(item)
                    if h in sent_news_hashes:
                        already_sent += 1
                        continue
                    sent_news_hashes.add(h)
                    save_sent_news()
                    last_alerts_hashes[h] = now
                    # ⚠️ تخطي الترجمة للخبر العربي (عربي أصلي)
                    item["title_ar"] = item.get("title", "")
                    item["summary_ar"] = item.get("summary", "")
                    msg = fmt_news_item(item, show_summary=True, translate=False)
                    image_url = item.get("image", "")
                    broadcast_alert(msg, image_url)
                    alerts_sent += 1
                    print(f"  ✉️ [AR] {item.get('title', '')[:60]}...")
                    time.sleep(1.5)
                    continue

                # (1) سياق الكريبتو إجباري
                crypto_context_keywords = [
                    "bitcoin", "btc", "ethereum", "eth", "ether", "crypto", "cryptocurrency",
                    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token", "coin",
                    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
                    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "polygon", "matic",
                    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
                    "web3", "wallet", "staking", "mining", "halving", "smart contract",
                    "decentralized", "dex", "cex", "ledger", "satoshi",
                    "sec", "gensler", "spot etf", "blackrock bitcoin", "fidelity crypto",
                    "grayscale", "microstrategy", "saylor", "cz", "vitalik",
                    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
                    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
                ]
                has_crypto_context = any(kw in news_text for kw in crypto_context_keywords)

                # (2) حدث جوهري صارم - فقط 7 فئات محددة
                critical_event_keywords = [
                    # 1️⃣ اختراق/سرقة (Hacks & Exploits)
                    "hack", "hacked", "exploit", "stolen", "drained", "drain",
                    "vulnerability", "flash loan", "rug pull", "breach", "cyberattack",
                    "security breach", "rekt", "compromised", "attacker", "hacker",
                    "phishing", "empty", "lost funds", "$10m", "$50m", "$100m", "$500m",
                    "million stolen", "billion stolen", "funds drained",

                    # 2️⃣ انهيار/تصحيح حاد (Crash & Plunge)
                    "crash", "plunge", "dump", "collapse", "liquidation",
                    "long squeeze", "short squeeze", "flash crash",
                    "10% drop", "15% drop", "20% drop", "30% drop",
                    "10% plunge", "15% plunge", "20% plunge",
                    "sharp decline", "steep decline", "massive sell-off",
                    "capitulation", "bloodbath", "meltdown",

                    # 3️⃣ سيولة مؤسسية كبيرة (Institutional Flows)
                    "institutional inflows", "institutional outflows",
                    "record inflows", "record outflows",
                    "blackrock buys", "microstrategy buys", "saylor buys",
                    "purchases bitcoin", "adds bitcoin", "buying bitcoin",
                    "$100m bitcoin", "$500m bitcoin", "$1b bitcoin", "$1 billion bitcoin",
                    "treasury allocation", "bitcoin treasury",
                    "etf inflows", "etf outflows", "fund flow",
                    "accumulation", "whale accumulat",

                    # 4️⃣ تحديث برمجي (Protocol Upgrades)
                    "halving", "hard fork", "soft fork", "the merge",
                    "ethereum 2.0", "mainnet launch", "mainnet upgrade",
                    "network upgrade", "protocol upgrade",
                    "shapella", "dencun", "pectra", "purge", "verge",
                    "smart contract upgrade", "consensus upgrade",

                    # 5️⃣ فك توكن (Token Unlock)
                    "token unlock", "unlocking", "unlocked",
                    "vesting unlock", "cliff unlock",
                    "$unlock", "tokens unlocked", "unlock schedule",
                    "linear unlock", "token release", "release schedule",

                    # 6️⃣ حرق توكن (Token Burn)
                    "burn", "burned", "burning",
                    "token burn", "coin burn", "buyback and burn",
                    "deflationary burn", "burn mechanism",
                    "burned tokens", "burn event",

                    # 7️⃣ قرارات تنظيمية كبرى (تكميلي)
                    "approval", "approved", "reject", "rejected",
                    "sec approves", "sec rejects", "sec sues", "sec charges",
                    "spot etf", "19b-4", "s-1",
                    "lawsuit", "crackdown", "ban", "banned",
                    "mica", "clarity act", "genius act", "fit21",

                    # 8️⃣ تصريحات كيفن وارش (Kevin Warsh) - المرشح لرئاسة الفيدرالي
                    # تصريحاته عن الفائدة والكريبتو تتحرك بها الأسواق
                    "kevin warsh", "warsh fed", "warsh crypto",
                    "warsh bitcoin", "warsh says", "warsh signals",
                    "warsh rate", "warsh interest",
                    "fed chair nominee", "fed chair pick",
                    "warsh nomination", "warsh nominated",
                ]
                has_critical_event = any(kw in news_text for kw in critical_event_keywords)

                # 🆕 استثناء: تصريحات كيفن وارش عن الكريبتو تُقبل بدون شرط سياق الكريبتو
                warsh_keywords = [
                    "warsh crypto", "warsh bitcoin",
                    "kevin warsh crypto", "kevin warsh bitcoin",
                    "warsh fed", "warsh says", "warsh signals",
                ]
                has_warsh_context = any(kw in news_text for kw in warsh_keywords)

                # 🚫 تم إلغاء أخبار الفيدرالي/الفائدة بناءً على طلب المستخدم
                # نلتزم بأخبار الكريبتو فقط
                # القبول: (سياق كريبتو + حدث جوهري) أو تصريحات وارش
                if not ((has_crypto_context and has_critical_event) or has_warsh_context):
                    continue

                # (4) كلمات ترفض الخبر تلقائياً (حتى لو طابق الكلمات أعلاه)
                rejection_keywords = [
                    "price prediction", "price target", "forecast",
                    "analyst says", "analyst predicts", "analyst expects",
                    "could reach", "might reach", "may hit",
                    "top 10", "top 5", "best coins", "best crypto",
                    "how to buy", "how to trade", "tutorial",
                    "watch these", "watch list", "watchlist",
                    "newsletter", "weekly recap", "daily recap",
                    "interview", "podcast", "review",
                    "guide", "explained", "what is",
                    "5 coins", "10 coins", "3 coins",
                    # 🆕 رفض إضافي للأخبار الجانبية
                    "minor upgrade", "minor update", "minor bug",
                    "small purchase", "minor hack",
                    # 🚫 رفض ميتاداتا Reddit ومنصات المجتمع
                    "[link]", "[تعليقات]", "[comments]", "/u/",
                    "submitted by", "مقدم بواسطة",
                    "crossposted from", "xposted from",
                ]
                has_rejection = any(kw in news_text for kw in rejection_keywords)
                if has_rejection:
                    continue
                # 🚫 رفض إضافي: أي مصدر Reddit (احتياط)
                if "reddit" in (item.get("source", "") or "").lower():
                    continue

                important_news += 1
                # 🔧 إصلاح: احترام alert_categories - إن كانت كل الفئات المطابقة معطّلة، تخطّي
                allowed_cats = [c for c in matched_cats if is_category_allowed(c)]
                if not allowed_cats:
                    continue
                h = news_hash(item)
                # 🆕 ذاكرة دائمة: إذا الخبر أُرسل من قبل، لا تعد إرساله أبداً
                if h in sent_news_hashes:
                    already_sent += 1
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
            # 🆕 سجل تشخيصي شامل
            log.info(f"📊 News scan: total={total_news}, important={important_news}, already_sent={already_sent}, old_skipped={old_news_skipped}, alerts_sent={alerts_sent}, sent_hashes={len(sent_news_hashes)}")
            # 🆕 تحديث الإحصائيات اليومية
            try:
                # جمع فئات الأخبار المهمة في هذه الدورة
                cats_today = []
                for item in news[:40]:
                    if item.get("timestamp", 0) > 0:
                        cats_today.extend(classify_news(item))
                update_daily_stats(alerts_sent=alerts_sent, important=important_news, total=total_news, categories=cats_today)
            except Exception:
                pass
            if alerts_sent > 0:
                log.info(f"🔔 Sent {alerts_sent} news alerts")
            elif important_news > 0:
                log.info(f"ℹ️ Found {important_news} important news but all already sent or in cooldown")
            else:
                log.info("ℹ️ No important news found in this scan")
            # 🔧 إصلاح: حفظ مجمّع إجباري في نهاية كل دورة
            save_sent_news(force=True)
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
    🆕🆕 إضافة شعار القناة newscrypto1m@ على الصور
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
                # 🆕🆕 محاولة تحميل الصورة وإضافة الشعار عليها
                watermarked_image = _add_watermark_to_image(clean_url)
                if watermarked_image:
                    # إرسال الصورة المعدّلة كملف (multipart/form-data)
                    p_data = {
                        "chat_id": chat_id,
                        "caption": msg[:1024],
                        "parse_mode": "HTML"
                    }
                    files = {"photo": ("image.jpg", watermarked_image, "image/jpeg")}
                    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                                      data=p_data, files=files, timeout=30)
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
                else:
                    # fallback: إرسال الرابط مباشرة (بدون شعار)
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


def _add_watermark_to_image(image_url):
    """🆕🆕 يحمل الصورة من URL ويضيف شعار القناة newscrypto1m@ عليها
    يعيد الصورة كـ bytes (JPEG) جاهزة للإرسال
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        # تحميل الصورة من URL
        r = requests.get(image_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None

        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        width, height = img.size

        # محاولة تحميل خط عربي (إن وُجد) أو خط افتراضي
        try:
            # ابحث عن خط في النظام
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            ]
            font = None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, max(20, width // 25))
                    break
                except:
                    continue
            if not font:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()

        # إنشاء طبقة شفافة للشعار
        draw = ImageDraw.Draw(img)
        watermark_text = "@newscrypto1m"

        # حساب حجم النص
        try:
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except:
            text_width, text_height = 200, 30

        # موقع الشعار: أسفل اليمين مع padding
        padding = 15
        x = width - text_width - padding - 10
        y = height - text_height - padding - 10

        # خلفية شبه شفافة خلف النص (للوضوح)
        bg_padding = 8
        draw.rectangle(
            [x - bg_padding, y - bg_padding,
             x + text_width + bg_padding, y + text_height + bg_padding],
            fill=(0, 0, 0, 180)
        )

        # النص بالأبيض
        draw.text((x, y), watermark_text, fill=(255, 255, 255), font=font)

        # حفظ كـ bytes
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        return output.getvalue()

    except Exception as e:
        log.warning(f"watermark err: {e}")
        return None

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
    msg += f"  🌍 جيوسياسة (حروب/نفط): {'🟢' if alert_categories.get('geopolitics', True) else '🔴'}\n"
    msg += f"  💼 أسواق عالمية (أسهم/ذهب): {'🟢' if alert_categories.get('stocks', True) else '🔴'}\n"
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
            # 🆕 زر الجيوسياسة
            {"text": f"{'🟢' if alert_categories.get('geopolitics', True) else '🔴'} جيوسياسة", "callback_data": "toggle_geopolitics"},
        ],
        [
            # 🆕 زر الأسواق العالمية
            {"text": f"{'🟢' if alert_categories.get('stocks', True) else '🔴'} أسواق", "callback_data": "toggle_stocks"},
        ],
        # 🆕 زر تبديل الإرسال للقناة (يظهر فقط إذا كان CHANNEL_ID مضبوطاً)
    ]
    if CHANNEL_ID:
        kb_buttons.append([
            {"text": f"{'🔴 إيقاف' if is_channel_enabled() else '🟢 تفعيل'} الإرسال للقناة",
             "callback_data": "toggle_channel"}
        ])
    # 🆕 زر تبديل الملخص اليومي
    kb_buttons.append([
        {"text": f"{'🔴 إيقاف' if daily_summary_enabled else '🟢 تفعيل'} الملخص اليومي",
         "callback_data": "toggle_summary"}
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
    global auto_alerts_enabled, channel_enabled, bot_shutdown, bot_resume_time, _skip_old_news_once, daily_summary_enabled
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
        "toggle_geopolitics": "geopolitics",
        "toggle_stocks": "stocks",
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
    elif d == "toggle_summary":
        # 🆕 تبديل الملخص اليومي (المالك فقط)
        if not is_owner(cid):
            send_msg("🔒 هذا الخيار للمالك فقط.", main_kb(), cid)
            return
        daily_summary_enabled = not daily_summary_enabled
        save_settings()
        status = "🟢 مفعّل" if daily_summary_enabled else "🔴 معطّل"
        send_msg(f"📅 الملخص اليومي: <b>{status}</b>", main_kb(), cid)
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

# 🆕 endpoint خاص للـ keepalive - خفيف وسريع
@app.route("/keepalive")
def keepalive():
    return jsonify({"status": "alive", "ts": int(time.time())})

# ═══════════════════════════════════════════════════════════
# تشغيل البوت
# ═══════════════════════════════════════════════════════════
def self_ping():
    """🔧 إصلاح: ping كل 5 دقائق (Render ينام بعد 15 دقيقة)"""
    if not RENDER_URL:
        log.warning("RENDER_URL not set - self_ping disabled")
        return
    time.sleep(30)
    ping_count = 0
    while True:
        try:
            # 🔧 إصلاح: استخدام /keepalive (أخف) + ping كل 5 دقائق
            r = requests.get(f"{RENDER_URL}/keepalive", timeout=10)
            ping_count += 1
            if ping_count % 12 == 0:  # سجل كل ساعة (12 ping × 5 دقائق)
                log.info(f"💓 Keepalive: {ping_count} pings sent (status: {r.status_code})")
        except Exception as e:
            log.warning(f"self_ping err: {e}")
        # 🔧 إصلاح: 5 دقائق بدلاً من 10 (آمن ضد النوم)
        time.sleep(300)


# 🆕 إحصائيات يومية للملخص
_daily_stats = {
    "alerts_sent": 0,
    "important_found": 0,
    "total_scanned": 0,
    "categories": {"breaking": 0, "hack": 0, "etf": 0, "fed": 0, "trump": 0, "whale": 0, "tech": 0, "market": 0, "geopolitics": 0, "stocks": 0},
    "date": datetime.now(tz).strftime("%Y-%m-%d")
}

def update_daily_stats(alerts_sent=0, important=0, total=0, categories=None):
    """🆕 تحديث إحصائيات اليوم"""
    global _daily_stats
    # تحقق من تغير اليوم (إعادة تعيين الإحصائيات)
    today = datetime.now(tz).strftime("%Y-%m-%d")
    if _daily_stats["date"] != today:
        log.info(f"📅 New day - resetting daily stats (was {_daily_stats['date']})")
        _daily_stats = {
            "alerts_sent": 0, "important_found": 0, "total_scanned": 0,
            "categories": {"breaking": 0, "hack": 0, "etf": 0, "fed": 0, "trump": 0, "whale": 0, "tech": 0, "market": 0, "geopolitics": 0, "stocks": 0},
            "date": today
        }
    _daily_stats["alerts_sent"] += alerts_sent
    _daily_stats["important_found"] += important
    _daily_stats["total_scanned"] += total
    if categories:
        for cat in categories:
            if cat in _daily_stats["categories"]:
                _daily_stats["categories"][cat] += 1


def build_daily_summary():
    """🆕 بناء ملخص يومي للأخبار"""
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M")
    msg = "📊 <b>الملخص اليومي للأخبار</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📅 التاريخ: {today}\n"
    msg += f"⏰ الوقت: {now_str}\n\n"
    msg += "📈 <b>إحصائيات اليوم:</b>\n"
    msg += f"   🔔 تنبيهات مُرسَلة: <b>{_daily_stats['alerts_sent']}</b>\n"
    msg += f"   📰 أخبار مهمة: <b>{_daily_stats['important_found']}</b>\n"
    msg += f"   📊 إجمالي فُحصت: <b>{_daily_stats['total_scanned']}</b>\n\n"
    # توزيع الفئات
    cats = _daily_stats["categories"]
    total_cats = sum(cats.values())
    if total_cats > 0:
        msg += "🏷️ <b>توزيع الفئات:</b>\n"
        # ترتيب الفئات تنازلياً
        sorted_cats = sorted(cats.items(), key=lambda x: -x[1])
        for cat, count in sorted_cats:
            if count > 0:
                icon = {"breaking": "🚨", "hack": "⚠️", "etf": "📊", "fed": "🏛️",
                        "trump": "🇺🇸", "whale": "🐋", "tech": "🔧", "market": "📈",
                        "geopolitics": "🌍", "stocks": "💼"}.get(cat, "📰")
                cat_name = {"breaking": "عاجل", "hack": "اختراق", "etf": "ETF", "fed": "الفيدرالي",
                            "trump": "ترامب", "whale": "حيتان", "tech": "تقني", "market": "سوقي",
                            "geopolitics": "جيوسياسة", "stocks": "أسواق عالمية"}.get(cat, cat)
                pct = (count / total_cats) * 100
                msg += f"   {icon} {cat_name}: {count} ({pct:.0f}%)\n"
    else:
        msg += "ℹ️ لم تُرصد فئات محددة اليوم\n"
    msg += "\n"
    # آخر أخبار اليوم (آخر 5) - 🆕 فقط الأخبار المهمة المُصنَّفة
    try:
        news = get_all_news()
        if news:
            news = deduplicate_news(news)
            # فلترة أخبار اليوم فقط
            today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            today_news = [n for n in news if n.get("timestamp", 0) >= today_start]
            # 🆕 فلترة: فقط الأخبار المهمة المُصنَّفة (استبعاد Reddit والإعلانات)
            important_today = []
            for item in today_news:
                source = item.get("source", "").lower()
                title = item.get("title", "").lower()
                # استبعاد Reddit والمحتوى الترويجي
                if "reddit" in source:
                    continue
                if any(spam in title for spam in ["tap to enter", "raffle", "giveaway", "win free"]):
                    continue
                # فقط الأخبار المُصنَّفة
                cats = classify_news(item)
                if cats:
                    important_today.append(item)
            if important_today:
                msg += f"📰 <b>آخر {min(5, len(important_today))} أخبار مهمة اليوم:</b>\n\n"
                for item in important_today[:5]:
                    title = item.get("title", "")
                    title_ar = item.get("title_ar", "")
                    if not title_ar:
                        title_ar = translate_to_arabic(title, force=True)
                    final_title = title_ar if title_ar else "⚠️ تعذرت الترجمة"
                    if len(final_title) > 80:
                        final_title = final_title[:77] + "..."
                    source = translate_source_name(item.get("source", ""))
                    msg += f"• {final_title}\n"
                    msg += f"  📡 {source}\n"
            else:
                msg += "ℹ️ لا توجد أخبار مهمة مُصنَّفة اليوم\n"
    except Exception as e:
        log.warning(f"daily summary news err: {e}")
    msg += "\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 <i>تم إنشاء هذا الملخص تلقائياً بواسطة البوت</i>"
    return msg


def daily_summary_loop():
    """🆕 يرسل ملخصاً يومياً في الساعة 23:59 بتوقيت المستخدم
    🔧 إصلاح: احترام daily_summary_enabled
    """
    global daily_summary_enabled
    log.info("📅 Daily summary loop started - will send at 23:59 daily")
    last_summary_date = None
    while True:
        try:
            # 🆕 إعادة تحميل الإعدادات
            load_settings()
            # 🆕 إذا كان الملخص معطّل، تخطّي
            if not daily_summary_enabled:
                time.sleep(300)
                continue
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            # تحقق: هل الساعة 23:59 (أو 23:58-00:02 للتسامح)؟
            # وهل لم نرسل الملخص اليوم؟
            if now.hour == 23 and now.minute >= 58 and last_summary_date != today:
                log.info(f"📅 Sending daily summary for {today}")
                # بناء الملخص
                msg = build_daily_summary()
                # إرسال لكل المستخدمين + القناة
                broadcast_alert(msg, None)
                last_summary_date = today
                log.info("📅 Daily summary sent successfully")
                # انتظر 5 دقائق قبل الفحص التالي (تجاوز نافذة 23:58-00:02)
                time.sleep(300)
                continue
            # فحص كل دقيقة
            time.sleep(60)
        except Exception as e:
            log.warning(f"daily_summary_loop err: {e}")
            time.sleep(60)

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
    # 🆕 thread الملخص اليومي (23:59)
    threading.Thread(target=lambda: run_with_restart("daily_summary", daily_summary_loop),
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

# ═══════════════════════════════════════════════════════════
# نقطة الدخول (Entry point)
# ═══════════════════════════════════════════════════════════
# يدعم وضعين:
# 1) Render (افتراضي): start_bot() - بوت دائم التشغيل مع Flask + webhook/polling
# 2) GitHub Actions: GITHUB_ACTIONS=true → دورة واحدة فقط ثم خروج
#    (يتجنب Flask والـ threads والـ webhook لأن GA يقتل العملية بعد دقائق)

if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
        # === وضع GitHub Actions: دورة واحدة ===
        print("=" * 60)
        print("🤖 Running in GitHub Actions mode (one-shot)")
        print("=" * 60)

        if not TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN not set!")
            exit(1)

        # تحميل الإعدادات والأخبار المُرسلة سابقاً
        load_settings()
        load_sent_news()

        # تفعيل القناة إذا كانت معطّلة في الإعدادات المحفوظة
        # (في GA نريد دائماً الإرسال إن وُجد CHANNEL_ID)
        if CHANNEL_ID and not channel_enabled:
            channel_enabled = True
            save_settings()

        # فحص دورة واحدة (بدون while True)
        try:
            # مسح الكاش
            if "all_news" in _cache:
                del _cache["all_news"]
            news = get_all_news()
            if not news:
                print("⚠️ لا أخبار متاحة. إعادة المحاولة بعد 5 دقائق.")
                exit(0)

            news = deduplicate_news(news)
            now = time.time()
            alerts_sent = 0
            total_news = len(news)
            important_news = 0
            already_sent = 0
            old_news_skipped = 0

            print(f"📰 إجمالي الأخبار: {total_news}")

            # نفحص آخر 40 خبر
            for item in news[:40]:
                item_ts = item.get("timestamp", 0)
                # تجاهل الأخبار الأقدم من 30 دقيقة
                if item_ts > 0 and (now - item_ts) > 1800:
                    old_news_skipped += 1
                    h_old = news_hash(item)
                    if h_old not in sent_news_hashes:
                        sent_news_hashes.add(h_old)
                    continue

                categories = classify_news(item)
                important_cats = ["breaking", "hack", "etf", "tech", "market", "whale",
                                  "fed", "trump", "geopolitics", "stocks"]
                matched_cats = [c for c in categories if c in important_cats]
                if not matched_cats:
                    continue

                # 🚨 فلتر صارم جداً: فقط الأحداث المحددة
                # 1) اختراق/سرقة  2) انهيار/تصحيح حاد  3) سيولة مؤسسية كبيرة
                # 4) تحديث برمجي  5) فك توكن  6) حرق توكن  7) قرارات الفائدة
                news_text = (item.get("title", "") + " " + item.get("summary", "")).lower()

                # (1) سياق الكريبتو إجباري
                crypto_context_keywords = [
                    "bitcoin", "btc", "ethereum", "eth", "ether", "crypto", "cryptocurrency",
                    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token", "coin",
                    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
                    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "polygon", "matic",
                    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
                    "web3", "wallet", "staking", "mining", "halving", "smart contract",
                    "decentralized", "dex", "cex", "ledger", "satoshi",
                    "sec", "gensler", "spot etf", "blackrock bitcoin", "fidelity crypto",
                    "grayscale", "microstrategy", "saylor", "cz", "vitalik",
                    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
                    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
                ]
                has_crypto_context = any(kw in news_text for kw in crypto_context_keywords)

                # (2) حدث جوهري صارم - فقط 7 فئات محددة
                critical_event_keywords = [
                    # 1️⃣ اختراق/سرقة (Hacks & Exploits)
                    "hack", "hacked", "exploit", "stolen", "drained", "drain",
                    "vulnerability", "flash loan", "rug pull", "breach", "cyberattack",
                    "security breach", "rekt", "compromised", "attacker", "hacker",
                    "phishing", "empty", "lost funds", "$10m", "$50m", "$100m", "$500m",
                    "million stolen", "billion stolen", "funds drained",

                    # 2️⃣ انهيار/تصحيح حاد (Crash & Plunge)
                    "crash", "plunge", "dump", "collapse", "liquidation",
                    "long squeeze", "short squeeze", "flash crash",
                    "10% drop", "15% drop", "20% drop", "30% drop",
                    "10% plunge", "15% plunge", "20% plunge",
                    "sharp decline", "steep decline", "massive sell-off",
                    "capitulation", "bloodbath", "meltdown",

                    # 3️⃣ سيولة مؤسسية كبيرة (Institutional Flows)
                    "institutional inflows", "institutional outflows",
                    "record inflows", "record outflows",
                    "blackrock buys", "microstrategy buys", "saylor buys",
                    "purchases bitcoin", "adds bitcoin", "buying bitcoin",
                    "$100m bitcoin", "$500m bitcoin", "$1b bitcoin", "$1 billion bitcoin",
                    "treasury allocation", "bitcoin treasury",
                    "etf inflows", "etf outflows", "fund flow",
                    "accumulation", "whale accumulat",

                    # 4️⃣ تحديث برمجي (Protocol Upgrades)
                    "halving", "hard fork", "soft fork", "the merge",
                    "ethereum 2.0", "mainnet launch", "mainnet upgrade",
                    "network upgrade", "protocol upgrade",
                    "shapella", "dencun", "pectra", "purge", "verge",
                    "smart contract upgrade", "consensus upgrade",

                    # 5️⃣ فك توكن (Token Unlock)
                    "token unlock", "unlocking", "unlocked",
                    "vesting unlock", "cliff unlock",
                    "$unlock", "tokens unlocked", "unlock schedule",
                    "linear unlock", "token release", "release schedule",

                    # 6️⃣ حرق توكن (Token Burn)
                    "burn", "burned", "burning",
                    "token burn", "coin burn", "buyback and burn",
                    "deflationary burn", "burn mechanism",
                    "burned tokens", "burn event",

                    # 7️⃣ قرارات تنظيمية كبرى (تكميلي)
                    "approval", "approved", "reject", "rejected",
                    "sec approves", "sec rejects", "sec sues", "sec charges",
                    "spot etf", "19b-4", "s-1",
                    "lawsuit", "crackdown", "ban", "banned",
                    "mica", "clarity act", "genius act", "fit21",

                    # 8️⃣ تصريحات كيفن وارش (Kevin Warsh) - المرشح لرئاسة الفيدرالي
                    "kevin warsh", "warsh fed", "warsh crypto",
                    "warsh bitcoin", "warsh says", "warsh signals",
                    "warsh rate", "warsh interest",
                    "fed chair nominee", "fed chair pick",
                    "warsh nomination", "warsh nominated",
                ]
                has_critical_event = any(kw in news_text for kw in critical_event_keywords)

                # 🆕 استثناء: تصريحات كيفن وارش عن الكريبتو تُقبل بدون شرط سياق الكريبتو
                warsh_keywords = [
                    "warsh crypto", "warsh bitcoin",
                    "kevin warsh crypto", "kevin warsh bitcoin",
                    "warsh fed", "warsh says", "warsh signals",
                ]
                has_warsh_context = any(kw in news_text for kw in warsh_keywords)

                # 🚫 تم إلغاء أخبار الفيدرالي/الفائدة بناءً على طلب المستخدم
                # نلتزم بأخبار الكريبتو فقط
                # القبول: (سياق كريبتو + حدث جوهري) أو تصريحات وارش
                if not ((has_crypto_context and has_critical_event) or has_warsh_context):
                    continue

                # (4) كلمات ترفض الخبر تلقائياً
                rejection_keywords = [
                    "price prediction", "price target", "forecast",
                    "analyst says", "analyst predicts", "analyst expects",
                    "could reach", "might reach", "may hit",
                    "top 10", "top 5", "best coins", "best crypto",
                    "how to buy", "how to trade", "tutorial",
                    "watch these", "watch list", "watchlist",
                    "newsletter", "weekly recap", "daily recap",
                    "interview", "podcast", "review",
                    "guide", "explained", "what is",
                    "5 coins", "10 coins", "3 coins",
                    "minor upgrade", "minor update", "minor bug",
                    "small purchase", "minor hack",
                    # 🚫 رفض ميتاداتا Reddit ومنصات المجتمع
                    "[link]", "[تعليقات]", "[comments]", "/u/",
                    "submitted by", "مقدم بواسطة",
                    "crossposted from", "xposted from",
                ]
                has_rejection = any(kw in news_text for kw in rejection_keywords)
                if has_rejection:
                    continue
                # 🚫 رفض إضافي: أي مصدر Reddit (احتياط)
                if "reddit" in (item.get("source", "") or "").lower():
                    continue

                important_news += 1
                allowed_cats = [c for c in matched_cats if is_category_allowed(c)]
                if not allowed_cats:
                    continue

                h = news_hash(item)
                if h in sent_news_hashes:
                    already_sent += 1
                    continue

                # تحديث الذاكرة
                sent_news_hashes.add(h)
                save_sent_news()

                # ترجمة الخبر قبل الإرسال
                translate_news_item(item)

                # إرسال للقناة والمستخدمين
                msg = fmt_news_item(item, show_summary=True, translate=True)
                image_url = item.get("image", "")
                broadcast_alert(msg, image_url)
                alerts_sent += 1
                print(f"  ✉️ [{','.join(matched_cats)}] {item.get('title', '')[:60]}...")
                time.sleep(1.5)  # تجنب flood limit

            print("=" * 60)
            print(f"📊 النتائج:")
            print(f"   • إجمالي الأخبار: {total_news}")
            print(f"   • أخبار مهمة: {important_news}")
            print(f"   • تم إرسالها: {alerts_sent}")
            print(f"   • أُرسلت سابقاً: {already_sent}")
            print(f"   • أخبار قديمة: {old_news_skipped}")
            print("=" * 60)

            save_sent_news(force=True)
            print("✅ انتهى. سيتم التشغيل التالي بعد 5 دقائق.")

        except Exception as e:
            import traceback
            print(f"❌ خطأ: {e}")
            traceback.print_exc()
            exit(1)
    else:
        # === وضع Render: تشغيل دائم ===
        start_bot()
