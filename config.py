"""
⚙️ Whale News Bot v2.0 - الإعدادات والمتغيرات العامة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يجمع بين الإعدادات القديمة والبنية الجديدة (dataclasses)
"""

import os, time, json, logging, threading, re, hashlib, asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import pytz, requests


# ═══════════════════════════════════════════════════════════
# 📦 Dataclasses الجديدة (للتوافق مع Kimi v2)
# ═══════════════════════════════════════════════════════════
@dataclass
class BotConfig:
    """إعدادات البوت المجمّعة"""
    TOKEN: str = ""
    CHAT_ID: str = ""
    CHANNEL_ID: str = ""
    CHANNEL_NAME: str = ""
    CHANNEL_LINK: str = ""
    SEND_TO_CHANNEL: bool = False
    RENDER_URL: str = ""
    PORT: int = 10000
    TIMEZONE: str = "Africa/Algiers"
    GITHUB_ACTIONS: bool = False
    RUN_MODE: str = "polling"  # "polling" or "oneshot"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    GIST_ID_SETTINGS: str = ""
    GIST_ID_SENT_NEWS: str = ""
    GIST_ID_ALLOWED: str = ""

    def validate(self) -> List[str]:
        """فحص الإعدادات الأساسية"""
        errors = []
        if not self.TOKEN:
            errors.append("❌ TELEGRAM_BOT_TOKEN not set")
        if not self.CHAT_ID:
            errors.append("❌ TELEGRAM_CHAT_ID not set")
        return errors


@dataclass
class BotState:
    """حالة البوت العامّة — المتغيرات التي تتغيّر أثناء التشغيل"""
    sent_news_hashes: Set[str] = field(default_factory=set)
    last_alerts_hashes: Dict[str, float] = field(default_factory=dict)
    auto_alerts_enabled: bool = True
    daily_summary_enabled: bool = True
    bot_shutdown: bool = False
    channel_enabled: Optional[bool] = None
    bot_resume_time: float = 0.0
    allowed_users: Set[int] = field(default_factory=set)
    _skip_old_news_once: bool = False

    def is_channel_enabled(self, cfg: BotConfig) -> bool:
        """يعيد True إذا كان الإرسال للقناة مفعّل"""
        if self.channel_enabled is not None:
            return self.channel_enabled and bool(cfg.CHANNEL_ID)
        return cfg.SEND_TO_CHANNEL and bool(cfg.CHANNEL_ID)


# ═══════════════════════════════════════════════════════════
# ⏱️ Rate Limiter (Token Bucket مع asyncio)
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    """محدّد معدّل الطلبات — token bucket"""

    def __init__(self, rate: int, period: float):
        self.rate = rate
        self.period = period
        self._tokens = rate
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """انتظار حتى يتوفر توكن"""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            if elapsed >= self.period:
                self._tokens = self.rate
                self._last_refill = now

            if self._tokens <= 0:
                # حساب وقت الانتظار
                sleep_time = self.period - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                self._tokens = self.rate
                self._last_refill = time.time()

            self._tokens -= 1


# ═══════════════════════════════════════════════════════════
# 🔌 Circuit Breaker
# ═══════════════════════════════════════════════════════════
class CircuitBreaker:
    """قاطع الدائرة — يمنع تكرار الطلبات الفاشلة"""

    def __init__(self, fail_threshold: int = 3, reset_timeout: float = 60):
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._last_failure = 0.0
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """تنفيذ الدالة مع Circuit Breaker"""
        async with self._lock:
            if self._failures >= self.fail_threshold:
                if time.time() - self._last_failure < self.reset_timeout:
                    raise RuntimeError(f"Circuit breaker OPEN — {self._failures} failures")
                # إعادة تعيين بعد timeout
                self._failures = 0

        try:
            # إذا كانت الدالة async
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            # نجاح — إعادة تعيين
            async with self._lock:
                self._failures = 0
            return result
        except Exception as e:
            async with self._lock:
                self._failures += 1
                self._last_failure = time.time()
            raise


# ═══════════════════════════════════════════════════════════
# الإعدادات العامة (من البيئة)
# ═══════════════════════════════════════════════════════════
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIMEZONE = os.environ.get("TIMEZONE", "Africa/Algiers")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/whale_signals_channel")
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "🐋 قناة الحيتان")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
SEND_TO_CHANNEL = os.environ.get("SEND_TO_CHANNEL", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("NewsBot")
tz = pytz.timezone(TIMEZONE)

# 🔧 User-Agent مناسب
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0; +https://github.com/whale-news)"}
REDDIT_HEADERS = {"User-Agent": "WhaleNewsBot/1.0 by u/whale_news_bot"}

# ═══════════════════════════════════════════════════════════
# 🌐 مصادر الأخبار (RSS) — NewsSource dataclass
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsSource:
    """نموذج مصدر الخبر — يدعم الوصول بالخاصّية والقاموس"""
    name: str = ""
    url: str = ""
    category: str = "crypto"
    lang: str = "en"
    timeout: int = 15

    def __getitem__(self, key):
        return getattr(self, key, "")

    def get(self, key, default=None):
        return getattr(self, key, default)


_RAW_NEWS_SOURCES = {
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
    "CoinPedia": {
        "url": "https://coingeek.com/feed/",
        "category": "crypto", "lang": "en"
    },
    "Blockworks": {
        "url": "https://blockworks.co/feed",
        "category": "crypto", "lang": "en"
    },
    "Bitcoinist": {
        "url": "https://bitcoinist.com/feed/",
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

# تحويل القاموس إلى كائنات NewsSource
NEWS_SOURCES: Dict[str, NewsSource] = {}
for _name, _data in _RAW_NEWS_SOURCES.items():
    NEWS_SOURCES[_name] = NewsSource(
        name=_name,
        url=_data.get("url", ""),
        category=_data.get("category", "crypto"),
        lang=_data.get("lang", "en"),
        timeout=_data.get("timeout", 15),
    )

# ═══════════════════════════════════════════════════════════
# 🎯 الكلمات المفتاحية
# ═══════════════════════════════════════════════════════════
KEYWORDS_BREAKING = [
    "breaking", "urgent", "alert", "just in", "developing",
    "hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach", "cyberattack", "security breach",
    "ban", "banned", "prohibit", "lawsuit", "sues", "sued", "crackdown", "sanction", "penalty", "fraud", "charges", "arrest", "indictment",
    "approval", "approved", "reject", "rejected", "etf", "spot etf", "all-time high", "ath", "crash", "surge", "plunge", "pump", "dump",
    "announce", "announces", "launches", "unveils", "reveals", "partnership", "acquisition", "merger",
]

KEYWORDS_FED = [
    "fed", "federal reserve", "interest rate", "powell", "fomc", "rate cut", "rate hike", "rate decision", "monetary policy",
    "inflation", "inflation data", "cpi", "core cpi", "ppi", "nonfarm payrolls", "jobless claims", "unemployment", "recession",
    "qe", "quantitative easing", "qt", "balance sheet", "treasury", "treasury yields", "yields", "bonds", "minutes",
    "economic data", "gdp", "consumer spending", "retail sales", "consumer price index", "job report",
]

KEYWORDS_WHALES = [
    "elon musk", "michael saylor", "cathie wood", "whale", "whales",
    "blackrock", "microstrategy", "satoshi", "binance", "cz", "changpeng zhao",
    "sam bankman-fried", "sbf", "vitalik", "vitalik buterin",
    "charles hoskinson", "brian armstrong", "coinbase ceo",
    "institutional", "inflows", "outflows", "accumulation",
    "gary gensler", "sec chair", "sec chief",
    "larry fink", "blackrock ceo", "fink",
    "jack dorsey", "square ceo", "block ceo",
    "pro-crypto", "anti-crypto", "crypto advocate", "crypto critic",
]

KEYWORDS_TECH = [
    "upgrade", "roadmap", "merge", "the merge", "halving", "fork", "hard fork", "soft fork",
    "mainnet", "testnet", "layer 2", "l2", "scaling", "rollup", "zk", "zero-knowledge",
    "smart contract", "defi", "nft", "dao", "staking", "yield", "airdrop", "tokenomics",
    "consensus", "proof of stake", "proof of work", "pos", "pow", "validator", "node",
    "ethereum 2.0", "serenity", "sharding", "dencun", "pectra", "purge", "verge", "lean ethereum",
    "protocol", "blockchain", "decentralized", "ledger",
]

KEYWORDS_MARKET = [
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

# 🆕 KEYWORDS_CONFIG لـ Kimi v2 (يُستخدم في filters.py NewsScorer)
KEYWORDS_CONFIG: Dict[str, Dict] = {
    "breaking": {
        "words": KEYWORDS_BREAKING + KEYWORDS_HACK,
        "weight": 2.0,
    },
    "fed": {
        "words": KEYWORDS_FED,
        "weight": 1.5,
    },
    "whale": {
        "words": KEYWORDS_WHALES,
        "weight": 1.0,
    },
    "tech": {
        "words": KEYWORDS_TECH,
        "weight": 0.8,
    },
    "market": {
        "words": KEYWORDS_MARKET,
        "weight": 0.5,
    },
    "etf": {
        "words": KEYWORDS_ETF,
        "weight": 1.5,
    },
}

# 🆕 COIN_MAP — خريطة العملات
COIN_MAP: Dict[str, str] = {
    # عملات رئيسية
    "bitcoin": "BTC", "btc": "BTC", "bitcoin cash": "BCH",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "solana": "SOL", "sol": "SOL",
    "xrp": "XRP", "ripple": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "avalanche": "AVAX", "avax": "AVAX",
    "polkadot": "DOT", "dot": "DOT",
    "chainlink": "LINK", "link": "LINK",
    "polygon": "POL", "matic": "POL", "pol": "POL",
    "litecoin": "LTC", "ltc": "LTC",
    "tron": "TRX", "trx": "TRX",
    "uniswap": "UNI", "aave": "AAVE",
    "near protocol": "NEAR", "near": "NEAR",
    "aptos": "APT", "apt": "APT",
    "arbitrum": "ARB", "arb": "ARB",
    "optimism": "OP", "op": "OP",
    "sui": "SUI", "sei": "SEI",
    "pepe": "PEPE", "shiba inu": "SHIB", "shib": "SHIB",
    "toncoin": "TON", "ton": "TON",
    "fantom": "FTM", "ftm": "FTM",
    "cosmos": "ATOM", "atom": "ATOM",
    "stellar": "XLM", "xlm": "XLM",
    "hedera": "HBAR", "hbar": "HBAR",
    "binance coin": "BNB", "bnb": "BNB",
    "usdt": "USDT", "tether": "USDT",
    "usdc": "USDC",
    "dai": "DAI",
    # ملاحظة: "op" قد يتعارض مع كلمات أخرى، لكنه مطلوب
}

# ═══════════════════════════════════════════════════════════
# 🎯 كلمات مفتاحية إضافية (تُصدَّر للفلاتر)
# ═══════════════════════════════════════════════════════════
CRYPTO_CONTEXT_KEYWORDS = [
    # عملات رئيسية
    "bitcoin", "btc", "ethereum", "eth", "ether", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token", "coin",
    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "polygon", "matic",
    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
    "web3", "wallet", "staking", "mining", "halving", "smart contract",
    "decentralized", "dex", "cex", "ledger", "satoshi",
    # مؤسسات كريبتو مؤثرة
    "sec", "gensler", "spot etf", "blackrock bitcoin", "fidelity crypto",
    "grayscale", "microstrategy", "saylor", "cz", "vitalik",
    # عملات إضافية شائعة
    "litecoin", "ltc", "tron", "trx", "toncoin", "ton",
    "stellar", "xlm", "hedera", "hbar", "near protocol", "aptos", "apt",
    "arbitrum", "arb", "optimism", "sei", "sui",
    "pepe", "shiba", "memecoin", "shitcoin",
    # مصطلحات DeFi وبروتوكولات
    "aave", "uniswap", "compound", "makerdao", "lido", "rocket pool",
    "restaking", "ethereum etf", "bitcoin etf",
    "on-chain", "token burn", "airdrop", "ico", "ieo",
    # عربية
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
    "تيثر", "سولانا", "ريبل", "ألبتكوين", "عملات مستقرة",
]

REJECTION_KEYWORDS = [
    "price prediction", "price target",
    "top 10", "top 5", "best coins", "best crypto",
    "how to buy", "how to trade", "tutorial",
    "newsletter", "weekly recap", "daily recap",
    "guide", "explained", "what is",
    "5 coins", "10 coins", "3 coins",
    "[link]", "[تعليقات]", "[comments]", "/u/",
    "submitted by", "مقدم بواسطة",
    "crossposted from", "xposted from",
]

AR_CRITICAL_KEYWORDS = [
    "اختراق", "اخترق", "سرقة", "سُرق", "تم اختراق", "ثغرة", "احتيال",
    "استغلال", "اختراقات", "سايبر", "هجوم إلكتروني",
    "انهيار", "انهار", "تدهور", "هبوط حاد", "سقوط", "تراجع حاد",
    "بيع جماعي", "تصفية", "ضغط",
    "تدفقات", "تدفق", "استثمارات مؤسسية", "شراء كبير",
    "مايكروستراتيجي", "بلاك روك", "مؤسسي",
    "التنصيف", "انقسام", "تحديث الشبكة",
    "إطلاق الشبكة", "الشبكة الرئيسية",
    "فك توكن", "إلغاء تأمين", "حرق توكن", "حرق عملة", "إتلاف",
    "الفائدة", "الفيدرالي", "باول", "اجتماع الفيدرالي",
    "خفض الفائدة", "رفع الفائدة", "تثبيت الفائدة",
    "أسعار الفائدة", "الاحتياطي الفيدرالي",
    "موافقة", "رفض", "قانون", "تنظيم", "حظر", "عقوبات",
    "بيتكوين", "إيثيريوم", "بايننس", "كريبتو", "عملات رقمية",
    "عملات مشفرة", "البلوكتشين", "USDT", "USDC",
]

AR_REJECTION_KEYWORDS = [
    "تحليل", "توقعات", "متوقع", "قد يصل", "قد يصل إلى",
    "أفضل 10", "أفضل 5", "كيف تشتري", "شرح",
    "دليل", "ما هي", "تعرف على",
]

# ═══════════════════════════════════════════════════════════
# 🔧 إعدادات التشغيل
# ═══════════════════════════════════════════════════════════
MAX_NEWS_PER_SCAN = 40
MAX_NEWS_AGE = 10800  # 3 ساعات
SCAN_INTERVAL = 300   # 5 دقائق
SUMMARY_HOUR = 23
SUMMARY_MINUTE = 59

# ═══════════════════════════════════════════════════════════
# المتغيرات العامة
# ═══════════════════════════════════════════════════════════
_cache = {}
_started = False
last_id = 0
_user_state = {}
ALERT_COOLDOWN = 21600  # 6 ساعات بين تنبيهين لنفس الخبر
last_alerts_hashes = {}
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GIST_ID_SETTINGS = os.environ.get("GIST_ID_SETTINGS", "")
_GIST_ID_SENT_NEWS = os.environ.get("GIST_ID_SENT_NEWS", "")
_GIST_ID_ALLOWED = os.environ.get("GIST_ID_ALLOWED", "")

# 🔧 مسار التخزين
if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
    _PERSISTENT_DIR = os.getcwd()
else:
    _PERSISTENT_DIR = "/tmp"

SENT_NEWS_FILE = os.path.join(_PERSISTENT_DIR, "sent_news.json")
SETTINGS_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "news_settings.json")
ALLOWED_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "allowed_users.json")

# 🆕 ذاكرة الأخبار المُرسلة — ستُربط بـ BotState.sent_news_hashes
sent_news_hashes = set()
_sent_news_dirty = False
_last_sent_news_save = 0
_backup_hashes_loaded = False
_backup_hashes = set()

# ═══════════════════════════════════════════════════════════
# دوال GitHub Gist
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
    """تحميل الأخبار المُرسلة سابقاً — يجمع من كل المصادر المتاحة"""
    global sent_news_hashes, _backup_hashes, _backup_hashes_loaded
    all_hashes = set()

    # (1) محاولة من Gist
    if _GIST_ID_SENT_NEWS:
        content = _gist_get(_GIST_ID_SENT_NEWS, "sent_news.json")
        if content:
            try:
                data = json.loads(content)
                hashes = set(data.get("hashes", []))
                if hashes:
                    all_hashes.update(hashes)
                    log.info(f"✅ Gist: {len(hashes)} hashes")
            except Exception as e:
                log.warning(f"Gist parse err: {e}")

    # (2) محاولة من الملف المحلي
    try:
        with open(SENT_NEWS_FILE, "r") as f:
            data = json.load(f)
            hashes = set(data.get("hashes", []))
            if hashes:
                all_hashes.update(hashes)
                log.info(f"✅ Local file: {len(hashes)} hashes")
    except Exception:
        pass

    # (3) محاولة من ملف commit في الريبو (GitHub Actions)
    repo_file = os.path.join(os.getcwd(), "sent_news.json")
    if os.path.exists(repo_file) and repo_file != SENT_NEWS_FILE:
        try:
            with open(repo_file, "r") as f:
                data = json.load(f)
                hashes = set(data.get("hashes", []))
                if hashes:
                    all_hashes.update(hashes)
                    log.info(f"✅ Repo file: {len(hashes)} hashes")
        except Exception:
            pass

    # الدمج النهائي
    if all_hashes:
        sent_news_hashes = all_hashes
    else:
        log.warning("⚠️ No sent hashes found from ANY source — starting fresh")

    # حفظ نسخة احتياطية
    if not _backup_hashes_loaded:
        _backup_hashes = set(sent_news_hashes)
        _backup_hashes_loaded = True

    log.info(f"📊 Total loaded: {len(sent_news_hashes)} sent news hashes")

def save_sent_news(force=False):
    """حفظ الأخبار المُرسلة — فوري في الملف المحلي، مجمّع في Gist"""
    global _sent_news_dirty, _last_sent_news_save
    _sent_news_dirty = True
    now = time.time()

    # حفظ فوري في الملف المحلي
    try:
        content = json.dumps({"hashes": list(sent_news_hashes)[-500:]})
        with open(SENT_NEWS_FILE, "w") as f:
            f.write(content)
    except Exception:
        pass

    # Gist: مجمّع كل 60 ثانية أو عند الإجبار
    if not force and (now - _last_sent_news_save) < 60:
        return
    _sent_news_dirty = False
    _last_sent_news_save = now
    content = json.dumps({"hashes": list(sent_news_hashes)[-500:]})
    if _GIST_ID_SENT_NEWS:
        if _gist_set(_GIST_ID_SENT_NEWS, "sent_news.json", content):
            log.info(f"💾 Saved {len(sent_news_hashes)} hashes to Gist")
        else:
            log.warning("⚠️ Failed to save sent_news to Gist")

# 🔔 إعدادات التنبيهات
auto_alerts_enabled = True
alert_categories = {"crypto": True, "macro": True, "breaking": True, "tech": True, "market": True}
SETTINGS_FILE = os.path.join(_PERSISTENT_DIR, "news_settings.json")
channel_enabled = None
bot_shutdown = False
daily_summary_enabled = True
bot_resume_time = 0
_skip_old_news_once = False

def load_settings():
    """تحميل الإعدادات من Gist (مع fallback محلي)"""
    global auto_alerts_enabled, alert_categories, channel_enabled, bot_shutdown, bot_resume_time, daily_summary_enabled
    loaded = False
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
    """حفظ الإعدادات في Gist + محلي"""
    content = json.dumps({
        "auto_alerts_enabled": auto_alerts_enabled,
        "alert_categories": alert_categories,
        "channel_enabled": channel_enabled,
        "bot_shutdown": bot_shutdown,
        "bot_resume_time": bot_resume_time,
        "daily_summary_enabled": daily_summary_enabled,
    }, ensure_ascii=False, indent=2)
    if _GIST_ID_SETTINGS:
        if _gist_set(_GIST_ID_SETTINGS, "news_settings.json", content):
            log.info("💾 Settings saved to Gist")
        else:
            log.warning("⚠️ Failed to save settings to Gist")
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE_LOCAL), exist_ok=True)
        with open(SETTINGS_FILE_LOCAL, "w") as f:
            f.write(content)
    except Exception:
        pass

def is_channel_enabled():
    """يعيد True إذا كان الإرسال للقناة مفعّل"""
    global channel_enabled
    if channel_enabled is not None:
        result = channel_enabled and bool(CHANNEL_ID)
        log.info(f"📢 is_channel_enabled: channel_enabled={channel_enabled}, result={result}")
        return result
    result = SEND_TO_CHANNEL and bool(CHANNEL_ID)
    log.info(f"📢 is_channel_enabled: using env fallback SEND_TO_CHANNEL={SEND_TO_CHANNEL}, result={result}")
    return result

# 🔒 القائمة البيضاء
ALLOWED_FILE = ALLOWED_FILE_LOCAL

def load_dynamic_allowed():
    """تحميل القائمة البيضاء من Gist (مع fallback محلي)"""
    if _GIST_ID_ALLOWED:
        content = _gist_get(_GIST_ID_ALLOWED, "allowed_users.json")
        if content:
            try:
                return set(json.loads(content).get("users", []))
            except Exception as e:
                log.warning(f"gist allowed parse err: {e}")
    try:
        with open(ALLOWED_FILE_LOCAL, "r") as f:
            return set(json.load(f).get("users", []))
    except Exception:
        return set()

def save_dynamic_allowed(users_set):
    """حفظ القائمة البيضاء في Gist + محلي"""
    content = json.dumps({"users": list(users_set)})
    if _GIST_ID_ALLOWED:
        if not _gist_set(_GIST_ID_ALLOWED, "allowed_users.json", content):
            log.warning("⚠️ Failed to save allowed_users to Gist")
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

# ═══════════════════════════════════════════════════════════
# 🏗️ إنشاء النسخ المفردة (Singletons)
# ═══════════════════════════════════════════════════════════
#Rate limiters و circuit breakers
TELEGRAM_RATE_LIMITER = RateLimiter(25, 60)
TELEGRAM_CB = CircuitBreaker(fail_threshold=5, reset_timeout=120)
FARSIDE_RATE_LIMITER = RateLimiter(2, 60)
FARSIDE_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)

# إنشاء config و state — يجب أن يأتيا AFTER تعريف الدوال
config = BotConfig(
    TOKEN=TOKEN,
    CHAT_ID=CHAT_ID,
    CHANNEL_ID=CHANNEL_ID,
    CHANNEL_NAME=CHANNEL_NAME,
    CHANNEL_LINK=CHANNEL_LINK,
    SEND_TO_CHANNEL=SEND_TO_CHANNEL,
    RENDER_URL=RENDER_URL,
    PORT=PORT,
    TIMEZONE=TIMEZONE,
    GITHUB_ACTIONS=os.environ.get("GITHUB_ACTIONS") == "true",
    RUN_MODE=os.environ.get("RUN_MODE", "polling"),
    GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", ""),
    GROQ_API_KEY=os.environ.get("GROQ_API_KEY", ""),
    OPENROUTER_API_KEY=os.environ.get("OPENROUTER_API_KEY", ""),
    GITHUB_TOKEN=_GITHUB_TOKEN,
    GIST_ID_SETTINGS=_GIST_ID_SETTINGS,
    GIST_ID_SENT_NEWS=_GIST_ID_SENT_NEWS,
    GIST_ID_ALLOWED=_GIST_ID_ALLOWED,
)

# ربط sent_news_hashes بمستوى الوحدة مع state.sent_news_hashes
# نعطي state نفس مرجع set
state = BotState(
    sent_news_hashes=sent_news_hashes,
    last_alerts_hashes=last_alerts_hashes,
    auto_alerts_enabled=auto_alerts_enabled,
    daily_summary_enabled=daily_summary_enabled,
    bot_shutdown=bot_shutdown,
    channel_enabled=channel_enabled,
    bot_resume_time=bot_resume_time,
    allowed_users=ALLOWED_USERS,
    _skip_old_news_once=_skip_old_news_once,
)