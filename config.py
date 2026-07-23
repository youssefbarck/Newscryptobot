"""
🐋 Whale News Bot v3 - الإعدادات المركزية
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
كل الإعدادات في ملف واحد — بدون تكرار
"""

import os, time, json, logging, threading, re, hashlib, asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import pytz, requests


# ═══════════════════════════════════════════════════════════
# 📦 الإعدادات الأساسية
# ═══════════════════════════════════════════════════════════
class Config:
    """إعدادات البوت — مركزية ومُدارة من مكان واحد"""
    # --- Telegram ---
    TOKEN: str = ""
    CHAT_ID: str = ""
    CHANNEL_ID: str = ""
    CHANNEL_NAME: str = "🐋 قناة أخبار الكريبتو"
    CHANNEL_LINK: str = "https://t.me/newscrypto1m"
    SEND_TO_CHANNEL: bool = False

    # --- البيئة ---
    TIMEZONE: str = "Africa/Algiers"
    RUN_MODE: str = "polling"  # "polling" or "oneshot"
    GITHUB_ACTIONS: bool = False
    RENDER_URL: str = ""
    PORT: int = 10000

    # --- مفاتيح API ---
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    COHERE_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    GIST_ID_SETTINGS: str = ""
    GIST_ID_SENT_NEWS: str = ""
    GIST_ID_ALLOWED: str = ""

    # --- إعدادات التشغيل ---
    SCAN_INTERVAL: int = 300          # 5 دقائق
    MAX_NEWS_PER_SCAN: int = 40
    MAX_NEWS_AGE: int = 10800          # 3 ساعات
    MIN_PUBLISH_SCORE: float = 60.0    # الحد الأدنى للنشر (من 100)
    SUMMARY_HOUR: int = 23
    SUMMARY_MINUTE: int = 59
    WATERMARK_TEXT: str = "@newscrypto1m"

    # --- Rate Limiting ---
    TELEGRAM_RATE_LIMIT: int = 25      # رسالة / 60 ثانية
    MAX_RETRIES: int = 3

    # --- مسارات التخزين ---
    PERSISTENT_DIR: str = "/tmp"

    # --- عتبات التقييم ---
    SCORE_THRESHOLDS = {
        "publish": 60.0,     # أدنى درجة للنشر
        "priority": 60.0,    # أخبار ذات أولوية عالية
        "breaking": 70.0,     # أخبار عاجلة
    }

    def __post_init__(self):
        pass

    @classmethod
    def from_env(cls):
        """تحميل الإعدادات من متغيرات البيئة"""
        c = cls()
        c.TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        c.CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
        c.CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
        c.CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "🐋 قناة أخبار الكريبتو")
        c.CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/newscrypto1m")
        c.SEND_TO_CHANNEL = os.environ.get("SEND_TO_CHANNEL", "false").lower() == "true"
        c.TIMEZONE = os.environ.get("TIMEZONE", "Africa/Algiers")
        c.PORT = int(os.environ.get("PORT", "10000"))
        c.RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
        c.RUN_MODE = os.environ.get("RUN_MODE", "polling")
        c.GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
        c.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        c.GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
        c.OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
        c.COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")
        c.GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
        c.GIST_ID_SETTINGS = os.environ.get("GIST_ID_SETTINGS", "")
        c.GIST_ID_SENT_NEWS = os.environ.get("GIST_ID_SENT_NEWS", "")
        c.GIST_ID_ALLOWED = os.environ.get("GIST_ID_ALLOWED", "")

        if c.GITHUB_ACTIONS or c.RUN_MODE == "oneshot":
            c.PERSISTENT_DIR = os.getcwd()
        else:
            c.PERSISTENT_DIR = "/tmp"

        return c


# ═══════════════════════════════════════════════════════════
# ⏱️ Rate Limiter
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
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_refill
            if elapsed >= self.period:
                self._tokens = self.rate
                self._last_refill = now
            if self._tokens <= 0:
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
    def __init__(self, fail_threshold: int = 3, reset_timeout: float = 300):
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._last_failure = 0.0
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            if self._failures >= self.fail_threshold:
                if time.time() - self._last_failure < self.reset_timeout:
                    raise RuntimeError(f"Circuit breaker OPEN — {self._failures} failures")
                self._failures = 0
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            async with self._lock:
                self._failures = 0
            return result
        except Exception as e:
            async with self._lock:
                self._failures += 1
                self._last_failure = time.time()
            raise


# ═══════════════════════════════════════════════════════════
# 🌐 مصادر الأخبار
# ═══════════════════════════════════════════════════════════
NEWS_SOURCES: Dict[str, Dict] = {
    # مصادر كريبتو إنجليزية (Tier 1-2)
    "CoinDesk": {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml", "category": "crypto", "lang": "en", "tier": 1},
    "Cointelegraph": {"url": "https://cointelegraph.com/rss", "category": "crypto", "lang": "en", "tier": 1},
    "Blockworks": {"url": "https://blockworks.co/feed", "category": "crypto", "lang": "en", "tier": 1},
    "Decrypt": {"url": "https://decrypt.co/feed", "category": "crypto", "lang": "en", "tier": 2},
    "BeInCrypto": {"url": "https://beincrypto.com/feed/", "category": "crypto", "lang": "en", "tier": 2},
    "Crypto.News": {"url": "https://crypto.news/feed/", "category": "crypto", "lang": "en", "tier": 2},
    "CoinPedia": {"url": "https://coinpedia.org/feed/", "category": "crypto", "lang": "en", "tier": 2},
    "Bitcoinist": {"url": "https://bitcoinist.com/feed/", "category": "crypto", "lang": "en", "tier": 2},
    # اقتصاد كلّي
    "Federal Reserve": {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "category": "fed", "lang": "en", "tier": 1},
    # Google News (Tier 3)
    "Google News - Crypto": {"url": "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+cryptocurrency+OR+crypto+regulation&hl=en&gl=US&ceid=US:en", "category": "crypto", "lang": "en", "tier": 3},
    "Google News - ETF": {"url": "https://news.google.com/rss/search?q=bitcoin+ETF+OR+ethereum+ETF+OR+spot+ETF&hl=en&gl=US&ceid=US:en", "category": "etf", "lang": "en", "tier": 3},
    "Google News - CPI": {"url": "https://news.google.com/rss/search?q=CPI+inflation+consumer+price+index+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - PPI": {"url": "https://news.google.com/rss/search?q=PPI+producer+price+index+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - NFP": {"url": "https://news.google.com/rss/search?q=nonfarm+payrolls+OR+NFP+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - GDP": {"url": "https://news.google.com/rss/search?q=GDP+gross+domestic+product+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - FOMC": {"url": "https://news.google.com/rss/search?q=FOMC+OR+federal+reserve+rate+decision+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - PCE": {"url": "https://news.google.com/rss/search?q=PCE+price+expenditures+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News - PMI": {"url": "https://news.google.com/rss/search?q=PMI+purchasing+managers+index+released&hl=en&gl=US&ceid=US:en", "category": "macro", "lang": "en", "tier": 3},
    "Google News AR - Bitcoin": {"url": "https://news.google.com/rss/search?q=بيتكوين+OR+العملات+الرقمية+OR+كريبتو&hl=ar&gl=EG&ceid=EG:ar", "category": "crypto", "lang": "ar", "tier": 3},
    "Google News AR - Fed": {"url": "https://news.google.com/rss/search?q=الفيدرالي+OR+أسعار+الفائدة+OR+باول&hl=ar&gl=EG&ceid=EG:ar", "category": "fed", "lang": "ar", "tier": 3},
}

# مصادر يمكن دمجها (نفس الخبر من هذه = خبر واحد مدمج)
MERGE_SOURCE_GROUPS = {
    "crypto_general": {"CoinDesk", "Cointelegraph", "Blockworks", "Decrypt", "BeInCrypto"},
}


# ═══════════════════════════════════════════════════════════
# 🗺️ خريطة العملات
# ═══════════════════════════════════════════════════════════
COIN_MAP: Dict[str, str] = {
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
    "usdc": "USDC", "dai": "DAI",
}

# أسماء العملات المعروفة → ticker (للـ dedup)
COIN_NAME_TO_TICKER: Dict[str, str] = {
    "بيتكوين": "BTC", "بتكوين": "BTC",
    "إيثيريوم": "ETH", "إيثereum": "ETH",
    "سولانا": "SOL", "ريبل": "XRP",
    "كاردانو": "ADA", "دوجكوين": "DOGE",
    "أفالانش": "AVAX", "بولكادوت": "DOT",
    "تثيلر": "USDT", "باينانس": "BNB",
}


# ═══════════════════════════════════════════════════════════
# 🏢 كيانات مهمة
# ═══════════════════════════════════════════════════════════
COMPANIES: Dict[str, str] = {
    "blackrock": "BlackRock", "black rock": "BlackRock",
    "fidelity": "Fidelity", "grayscale": "Grayscale",
    "microstrategy": "MicroStrategy", "coinbase": "Coinbase",
    "binance": "Binance", "kraken": "Kraken",
    "sec": "SEC", "securities and exchange commission": "SEC",
    "federal reserve": "Federal Reserve", "the fed": "Federal Reserve",
    "van eck": "VanEck", "franklin templeton": "Franklin Templeton",
    "ark invest": "ARK Invest", "21shares": "21Shares",
    "bitwise": "Bitwise",
}

PEOPLE: Dict[str, str] = {
    "elon musk": "Elon Musk", "musk": "Elon Musk",
    "michael saylor": "Michael Saylor", "saylor": "Michael Saylor",
    "cathie wood": "Cathie Wood",
    "vitalik": "Vitalik Buterin", "vitalik buterin": "Vitalik Buterin",
    "gary gensler": "Gary Gensler", "gensler": "Gary Gensler",
    "cz": "CZ", "changpeng zhao": "CZ",
    "sam bankman-fried": "SBF", "sbf": "SBF",
    "brian armstrong": "Brian Armstrong",
    "larry fink": "Larry Fink", "fink": "Larry Fink",
    "jerome powell": "Jerome Powell", "powell": "Jerome Powell",
    "jack dorsey": "Jack Dorsey",
    "charles hoskinson": "Charles Hoskinson",
}


# ═══════════════════════════════════════════════════════════
# 🎯 كلمات مفتاحية للتصنيف
# ═══════════════════════════════════════════════════════════
TYPE_KEYWORDS: Dict[str, List[str]] = {
    "hack": ["hack", "exploit", "stolen", "drained", "vulnerability", "flash loan",
             "rug pull", "breach", "cyberattack", "security breach", "rekt",
             "compromised", "attacker", "hacker", "malicious", "phishing"],
    "etf": ["etf", "spot etf", "19b-4", "s-1", "prospectus", "issuance",
            "redemption", "fund flow", "grayscale", "bitcoin etf", "ethereum etf"],
    "listing": ["listing", "listed", "lists", "delist", "delisted", "trading goes live",
                "launches trading", "new pair", "perpetual futures"],
    "partnership": ["partnership", "partner", "collaboration", "integrates",
                    "teams up", "joint venture", "strategic partnership"],
    "regulation": ["sec", "regulation", "regulatory", "compliance", "banned",
                   "ban", "lawsuit", "sues", "sued", "crackdown", "sanction",
                   "approved", "approval", "reject", "rejected", "legislation"],
    "macro": ["federal reserve", "interest rate", "powell", "fomc", "rate cut",
              "rate hike", "inflation", "cpi", "ppi", "gdp", "nfp", "recession",
              "treasury", "yields", "bonds", "monetary policy", "qe", "qt"],
    "on_chain": ["on-chain", "whale", "whales", "accumulation", "wallet movement",
                 "transfer", "burn", "token burn", "liquidation", "leverage"],
    "technical_analysis": ["analysis", "support", "resistance", "bullish", "bearish",
                           "chart", "pattern", "breakout", "golden cross", "death cross"],
    "funding": ["funding", "funded", "investment", "invests", "series a", "series b",
                "seed round", "vc", "venture capital", "fundraise"],
    "stablecoin": ["stablecoin", "usdt", "usdc", "dai", "depeg", "peg",
                  "tether", "circle", "usdc depeg"],
    "economic_data": ["cpi data", "inflation data", "employment data", "gdp data",
                      "pmi data", "economic data", "nfp", "adp", "jobless claims"],
    "adoption": ["adoption", "accepts", "accepts crypto", "payment", "integrates",
                 "mainstream", "institutional adoption"],
}

# كلمات الرفض
REJECTION_KEYWORDS = [
    "price prediction", "price target", "top 10", "top 5", "best coins",
    "how to buy", "how to trade", "tutorial", "guide", "explained",
    "what is", "newsletter", "weekly recap", "daily recap",
    "[link]", "[تعليقات]", "[comments]", "/u/", "submitted by",
    "مقدم بواسطة", "crossposted from",
]

# أنماط أخبار تغير السعر الروتينية — تُرفض تلقائياً
_PRICE_NOISE_PATTERNS = [
    # أنماط إنجليزية
    r"(bitcoin|btc|ethereum|eth|solana|sol|xrp|bnb|doge|dogecoin)\s+(?:price\s+)?(?:rises?|falls?|drops?|gains?|climbs?|surges?|dips?|slides?|slumps?)\s+(?:to|above|below|past|near|by|over|under)",
    r"(bitcoin|btc|ethereum|eth|solana|sol|xrp|bnb)\s+(?:trading\s+(?:at|near|around|above|below)|hovering\s+(?:near|around|at)|reaches?\s+(?:new|a|all-time|weekly|monthly))",
    r"(?:trading|currently|now)\s+at\s+\$[\d,]+(?:\.[\d]+)?",
    r"(?:price\s+(?:of|for|action|update|movement|watch|analysis))",
    r"(?:drops?|gains?|rises?|falls?)\s+(?:\d+\.?\d*)%",
    r"(?:hits|touches|reaches|breaks|crosses)\s+\$[\d,]+",
    r"(?:bullish|bearish)\s+(?:momentum|trend|signal|bias|outlook)",
    r"(?:support|resistance)\s+(?:level|zone|at|held|broken)",
    r"(?:slight|small|modest|minor)\s+(?:(?:price\s+)?(?:change|move|shift|drop|gain|rise|fall))",
    r"(?:daily|weekly|monthly)\s+(?:price\s+)?(?:chart|analysis|outlook)",
    # أنماط عربية
    r"(?:سعر|أسعار)\s+(?:البيتكوين|الإيثيريوم|بيتكوين|إيثيريوم|سولانا|العملات)\s+(?:يرتفع|ينخفض|يتراجع|يصل|يصل إلى)",
    r"(?:يرتفع|ينخفض|يتراجع|يستقر)\s+(?:سعر|بـ|إلى)\s+(?:\d|%)",
    r"(?:تحليل|توقعات|توقعات?)\s+(?:السعر|الأسعار|الفني|سعر|أسعار)",
    r"(?:مستوى|منطقة)\s+(?:الدعم|المقاومة)",
    r"(?:تغير\s+)?(?:طفيف|بسيط|محدود|سلس|سلس?)\s+(?:في\s+)?(?:السعر|الأسعار|سعر|أسعار)",
    r"(?:سعر|أسعار)\s+(?:يرتفع|ينخفض|يتراجع|يستقر|يشهد|يسجل)",
]

# كلمات السياق الكريبتوي
CRYPTO_CONTEXT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token",
    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
    "solana", "sol", "cardano", "ada", "dogecoin", "polygon",
    "polkadot", "avalanche", "chainlink", "web3", "wallet", "staking",
    "mining", "halving", "smart contract", "decentralized", "dex",
    "cex", "satoshi", "sec", "etf", "blackrock", "fidelity",
    "grayscale", "microstrategy", "vitalik", "cz",
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة",
    "بلوكتشين", "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
]


# ═══════════════════════════════════════════════════════════
# 🏗️ إنشاء النسخة المفردة
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("WhaleBot")
tz = pytz.timezone("Africa/Algiers")

cfg = Config.from_env()

TELEGRAM_RATE_LIMITER = RateLimiter(cfg.TELEGRAM_RATE_LIMIT, 60)
TELEGRAM_CB = CircuitBreaker(fail_threshold=5, reset_timeout=120)
FARSIDE_RATE_LIMITER = RateLimiter(2, 60)
FARSIDE_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)

# كاش بسيط
_cache: Dict[str, Tuple[Any, float]] = {}

def get_cached(key: str, ttl: int = 120) -> Optional[Any]:
    if key in _cache and time.time() - _cache[key][0] < ttl:
        return _cache[key][1]
    return None

def set_cached(key: str, data: Any):
    _cache[key] = (time.time(), data)

# ═══════════════════════════════════════════════════════════
# دوال GitHub Gist
# ═══════════════════════════════════════════════════════════
def gist_get(gist_id: str, filename: str) -> Optional[str]:
    if not cfg.GITHUB_TOKEN or not gist_id:
        return None
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {cfg.GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            timeout=10
        )
        if r.status_code == 200:
            files = r.json().get("files", {})
            if filename in files:
                return files[filename].get("content", "")
    except Exception as e:
        log.warning(f"gist_get err: {e}")
    return None

def gist_set(gist_id: str, filename: str, content: str) -> bool:
    if not cfg.GITHUB_TOKEN or not gist_id:
        return False
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"token {cfg.GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={"files": {filename: {"content": content}}},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        log.warning(f"gist_set err: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# إدارة حالة البوت
# ═══════════════════════════════════════════════════════════
class State:
    """حالة البوت العامّة"""
    sent_news_hashes: Set[str] = set()       # title hashes
    sent_fact_hashes: Set[str] = set()       # fact hashes — لكشف التكرار الدلالي
    sent_text_fingerprints: list = []         # بصمات نصية عربية — لكشف التكرار عبر الدورات
    bot_shutdown: bool = False
    channel_enabled: Optional[bool] = None
    allowed_users: Set[int] = set()

state = State()


def load_sent_hashes():
    """تحميل الأخبار المُرسلة سابقاً"""
    all_hashes = set()
    all_fact_hashes = set()
    all_fingerprints = []
    # Gist
    if cfg.GIST_ID_SENT_NEWS:
        content = gist_get(cfg.GIST_ID_SENT_NEWS, "sent_news.json")
        if content:
            try:
                data = json.loads(content)
                all_hashes.update(set(data.get("hashes", [])))
                all_fact_hashes.update(set(data.get("fact_hashes", [])))
                fps = data.get("text_fingerprints", [])
                if fps:
                    all_fingerprints = fps
            except:
                pass
    # محلي
    try:
        with open(os.path.join(cfg.PERSISTENT_DIR, "sent_news.json"), "r") as f:
            data = json.load(f)
            all_hashes.update(set(data.get("hashes", [])))
            all_fact_hashes.update(set(data.get("fact_hashes", [])))
            if not all_fingerprints:
                fps = data.get("text_fingerprints", [])
                if fps:
                    all_fingerprints = fps
    except:
        pass
    state.sent_news_hashes = all_hashes
    state.sent_fact_hashes = all_fact_hashes
    state.sent_text_fingerprints = all_fingerprints
    log.info(f"📊 Loaded {len(state.sent_news_hashes)} text hashes + {len(state.sent_fact_hashes)} fact hashes + {len(all_fingerprints)} text fingerprints")


def save_sent_hashes():
    """حفظ الأخبار المُرسلة"""
    fps_to_save = state.sent_text_fingerprints[-300:] if state.sent_text_fingerprints else []
    content = json.dumps({
        "hashes": list(state.sent_news_hashes)[-500:],
        "fact_hashes": list(state.sent_fact_hashes)[-500:],
        "text_fingerprints": fps_to_save,
    })
    try:
        with open(os.path.join(cfg.PERSISTENT_DIR, "sent_news.json"), "w") as f:
            f.write(content)
    except:
        pass
    if cfg.GIST_ID_SENT_NEWS:
        gist_set(cfg.GIST_ID_SENT_NEWS, "sent_news.json", content)


def load_settings():
    """تحميل الإعدادات من Gist"""
    if cfg.GIST_ID_SETTINGS:
        content = gist_get(cfg.GIST_ID_SETTINGS, "news_settings.json")
        if content:
            try:
                s = json.loads(content)
                state.channel_enabled = s.get("channel_enabled", None)
                state.bot_shutdown = s.get("bot_shutdown", False)
                return
            except:
                pass
    try:
        with open(os.path.join(cfg.PERSISTENT_DIR, "news_settings.json"), "r") as f:
            s = json.load(f)
            state.channel_enabled = s.get("channel_enabled", None)
            state.bot_shutdown = s.get("bot_shutdown", False)
    except:
        pass


def save_settings():
    """حفظ الإعدادات"""
    content = json.dumps({
        "channel_enabled": state.channel_enabled,
        "bot_shutdown": state.bot_shutdown,
    }, ensure_ascii=False, indent=2)
    if cfg.GIST_ID_SETTINGS:
        gist_set(cfg.GIST_ID_SETTINGS, "news_settings.json", content)
    try:
        with open(os.path.join(cfg.PERSISTENT_DIR, "news_settings.json"), "w") as f:
            f.write(content)
    except:
        pass


def is_channel_enabled() -> bool:
    if state.channel_enabled is not None:
        return state.channel_enabled and bool(cfg.CHANNEL_ID)
    return cfg.SEND_TO_CHANNEL and bool(cfg.CHANNEL_ID)
