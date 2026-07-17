"""
🐋 Whale News Bot v2.0 - الإعدادات المتقدمة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بنية async، تخزين ذكي، circuit breaker، rate limiting
"""

import os, time, json, logging, hashlib, asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Set, Optional, Any, Callable
from collections import defaultdict
import pytz

# ═══════════════════════════════════════════════════════════
# 🔧 إعدادات اللوج المتقدمة (Structured Logging)
# ═══════════════════════════════════════════════════════════
class StructuredFormatter(logging.Formatter):
    """Formatter يُخرج JSON للـ production"""
    def format(self, record):
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data, ensure_ascii=False, default=str)

# تبديل بين JSON (production) و text (development)
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text")
if LOG_FORMAT == "json":
    formatter = StructuredFormatter()
else:
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

handler = logging.StreamHandler()
handler.setFormatter(formatter)
log = logging.getLogger("WhaleBot")
log.setLevel(logging.INFO)
log.handlers = [handler]

# ═══════════════════════════════════════════════════════════
# 🔑 المتغيرات البيئية (مع validation)
# ═══════════════════════════════════════════════════════════
@dataclass(frozen=True)
class BotConfig:
    """إعدادات ثابتة للبوت - immutable للأمان"""
    TOKEN: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    CHAT_ID: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    CHANNEL_ID: str = field(default_factory=lambda: os.environ.get("CHANNEL_ID", ""))
    TIMEZONE: str = field(default_factory=lambda: os.environ.get("TIMEZONE", "Africa/Algiers"))
    PORT: int = field(default_factory=lambda: int(os.environ.get("PORT", 10000)))
    RENDER_URL: str = field(default_factory=lambda: os.environ.get("RENDER_EXTERNAL_URL", ""))
    CHANNEL_LINK: str = field(default_factory=lambda: os.environ.get("CHANNEL_LINK", "https://t.me/whale_signals_channel"))
    CHANNEL_NAME: str = field(default_factory=lambda: os.environ.get("CHANNEL_NAME", "🐋 قناة الحيتان"))

    # API Keys
    GEMINI_API_KEY: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    GROQ_API_KEY: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    OPENROUTER_API_KEY: str = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", ""))
    GITHUB_TOKEN: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""))

    # Gist IDs
    GIST_ID_SETTINGS: str = field(default_factory=lambda: os.environ.get("GIST_ID_SETTINGS", ""))
    GIST_ID_SENT_NEWS: str = field(default_factory=lambda: os.environ.get("GIST_ID_SENT_NEWS", ""))
    GIST_ID_ALLOWED: str = field(default_factory=lambda: os.environ.get("GIST_ID_ALLOWED", ""))

    # Flags
    SEND_TO_CHANNEL: bool = field(default_factory=lambda: os.environ.get("SEND_TO_CHANNEL", "false").lower() == "true")
    GITHUB_ACTIONS: bool = field(default_factory=lambda: os.environ.get("GITHUB_ACTIONS", "").lower() == "true")
    RUN_MODE: str = field(default_factory=lambda: os.environ.get("RUN_MODE", ""))

    def validate(self) -> List[str]:
        """التحقق من الإعدادات الضرورية"""
        errors = []
        if not self.TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN مفقود!")
        if not self.CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID مفقود!")
        return errors

# ═══════════════════════════════════════════════════════════
# ⚡ Rate Limiting & Circuit Breaker
# ═══════════════════════════════════════════════════════════
@dataclass
class RateLimiter:
    """Rate limiter بسيط باستخدام token bucket"""
    rate: float  # طلبات في الثانية
    burst: int   # الحد الأقصى للـ burst
    _tokens: float = field(default=0, repr=False)
    _last_update: float = field(default_factory=time.time, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def acquire(self):
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1

@dataclass  
class CircuitBreaker:
    """Circuit Breaker pattern للمصادر المتعثرة"""
    failure_threshold: int = 5
    recovery_timeout: float = 300  # 5 دقائق
    half_open_max_calls: int = 3

    _failures: int = field(default=0, repr=False)
    _last_failure: float = field(default=0, repr=False)
    _state: str = field(default="closed", repr=False)  # closed, open, half-open
    _half_open_calls: int = field(default=0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def call(self, fn: Callable, *args, **kwargs):
        async with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure > self.recovery_timeout:
                    self._state = "half-open"
                    self._half_open_calls = 0
                    log.info("🔓 Circuit breaker: half-open")
                else:
                    raise CircuitBreakerOpen("الدائرة مفتوحة - المصدر متعثر")

            if self._state == "half-open" and self._half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpen("الدائرة نصف مفتوحة - انتظار المزيد من الوقت")

            if self._state == "half-open":
                self._half_open_calls += 1

        try:
            result = await fn(*args, **kwargs)
            async with self._lock:
                self._failures = 0
                if self._state == "half-open":
                    self._state = "closed"
                    log.info("🔒 Circuit breaker: closed (recovered)")
            return result
        except Exception as e:
            async with self._lock:
                self._failures += 1
                self._last_failure = time.time()
                if self._failures >= self.failure_threshold:
                    self._state = "open"
                    log.warning(f"🔴 Circuit breaker: OPEN after {self._failures} failures")
            raise

class CircuitBreakerOpen(Exception):
    pass

# ═══════════════════════════════════════════════════════════
# 📰 مصادر الأخبار (مع circuit breaker لكل مصدر)
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsSource:
    name: str
    url: str
    category: str
    lang: str
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    timeout: float = 15.0
    weight: int = 1  # أولوية المصدر (أعلى = أهم)

NEWS_SOURCES: Dict[str, NewsSource] = {
    "CoinDesk": NewsSource("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml", "crypto", "en", weight=3),
    "Cointelegraph": NewsSource("Cointelegraph", "https://cointelegraph.com/rss", "crypto", "en", weight=3),
    "Decrypt": NewsSource("Decrypt", "https://decrypt.co/feed", "crypto", "en", weight=2),
    "BeInCrypto": NewsSource("BeInCrypto", "https://beincrypto.com/feed/", "crypto", "en", weight=2),
    "Crypto.News": NewsSource("Crypto.News", "https://crypto.news/feed/", "crypto", "en", weight=2),
    "Blockworks": NewsSource("Blockworks", "https://blockworks.co/feed", "crypto", "en", weight=2),
    "Bitcoinist": NewsSource("Bitcoinist", "https://bitcoinist.com/feed/", "crypto", "en", weight=1),
    "Federal Reserve": NewsSource("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "fed", "en", weight=3),
    "Google News - Crypto": NewsSource("Google News - Crypto", "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+cryptocurrency+OR+crypto+regulation&hl=en&gl=US&ceid=US:en", "crypto", "en", weight=1),
    "Google News - ETF": NewsSource("Google News - ETF", "https://news.google.com/rss/search?q=bitcoin+ETF+OR+ethereum+ETF+OR+spot+ETF&hl=en&gl=US&ceid=US:en", "etf", "en", weight=2),
    "Google News AR - Bitcoin": NewsSource("Google News AR - Bitcoin", "https://news.google.com/rss/search?q=بيتكوين+OR+العملات+الرقمية+OR+كريبتو&hl=ar&gl=EG&ceid=EG:ar", "crypto", "ar", weight=2),
    "Google News AR - Fed": NewsSource("Google News AR - Fed", "https://news.google.com/rss/search?q=الفيدرالي+OR+أسعار+الفائدة+OR+باول&hl=ar&gl=EG&ceid=EG:ar", "fed", "ar", weight=2),
}

# ═══════════════════════════════════════════════════════════
# 🎯 الكلمات المفتاحية (مُحسّنة مع weights)
# ═══════════════════════════════════════════════════════════
KEYWORDS_CONFIG = {
    "breaking": {
        "words": ["breaking", "urgent", "alert", "just in", "developing", "hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach", "cyberattack", "security breach", "ban", "banned", "prohibit", "lawsuit", "sues", "sued", "crackdown", "sanction", "penalty", "fraud", "charges", "arrest", "indictment", "approval", "approved", "reject", "rejected", "etf", "spot etf", "all-time high", "ath", "crash", "surge", "plunge", "pump", "dump", "announce", "announces", "launches", "unveils", "reveals", "partnership", "acquisition", "merger"],
        "weight": 3,
    },
    "fed": {
        "words": ["fed", "federal reserve", "interest rate", "powell", "fomc", "rate cut", "rate hike", "rate decision", "monetary policy", "inflation", "cpi", "core cpi", "ppi", "nonfarm payrolls", "jobless claims", "unemployment", "recession", "qe", "quantitative easing", "qt", "balance sheet", "treasury", "treasury yields", "yields", "bonds", "minutes", "economic data", "gdp", "consumer spending", "retail sales", "consumer price index", "job report"],
        "weight": 2,
    },
    "whale": {
        "words": ["elon musk", "michael saylor", "cathie wood", "whale", "whales", "blackrock", "microstrategy", "satoshi", "binance", "cz", "changpeng zhao", "sam bankman-fried", "sbf", "vitalik", "vitalik buterin", "charles hoskinson", "brian armstrong", "coinbase ceo", "institutional", "inflows", "outflows", "accumulation", "gary gensler", "sec chair", "sec chief", "larry fink", "blackrock ceo", "fink", "jack dorsey", "square ceo", "block ceo", "pro-crypto", "anti-crypto", "crypto advocate", "crypto critic"],
        "weight": 2,
    },
    "tech": {
        "words": ["upgrade", "roadmap", "merge", "the merge", "halving", "fork", "hard fork", "soft fork", "mainnet", "testnet", "layer 2", "l2", "scaling", "rollup", "zk", "zero-knowledge", "smart contract", "defi", "nft", "dao", "staking", "yield", "airdrop", "tokenomics", "consensus", "proof of stake", "proof of work", "pos", "pow", "validator", "node", "ethereum 2.0", "serenity", "sharding", "dencun", "pectra", "purge", "verge", "lean ethereum", "protocol", "blockchain", "decentralized", "ledger"],
        "weight": 1,
    },
    "market": {
        "words": ["bull market", "bear market", "bullish", "bearish", "rally", "correction", "support", "resistance", "liquidation", "leverage", "futures", "options", "open interest", "funding rate", "long", "short", "volume", "volatility", "dominance", "market cap", "capitalization", "supply", "demand", "price", "target", "forecast", "prediction", "analysis", "outlook", "sentiment"],
        "weight": 1,
    },
    "etf": {
        "words": ["etf", "spot etf", "approval", "sec", "blackrock", "fidelity", "ark invest", "grayscale", "van eck", "franklin templeton", "19b-4", "s-1", "prospectus", "issuance", "redemption", "creation", "trust", "fund flow"],
        "weight": 2,
    },
    "hack": {
        "words": ["hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach", "cyberattack", "security breach", "rekt", "drained", "empty", "compromised", "attacker", "hacker", "malicious", "phishing"],
        "weight": 3,
    },
}

# ═══════════════════════════════════════════════════════════
# 🪙 العملات (مع metadata)
# ═══════════════════════════════════════════════════════════
COIN_MAP = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "avalanche": "AVAX", "avax": "AVAX",
    "polygon": "MATIC", "matic": "MATIC",
    "chainlink": "LINK",
    "polkadot": "DOT", "dot": "DOT",
    "litecoin": "LTC", "ltc": "LTC",
    "binance": "BNB", "bnb": "BNB",
    "tether": "USDT", "usdt": "USDT",
    "aptos": "APT", "apt": "APT",
    "arbitrum": "ARB", "arb": "ARB",
    "optimism": "OP",
    "sui": "SUI", "sei": "SEI", "toncoin": "TON",
    "tron": "TRX", "trx": "TRX",
    "near": "NEAR", "fantom": "FTM", "ftm": "FTM",
    "stellar": "XLM", "xlm": "XLM",
    "hedera": "HBAR", "hbar": "HBAR",
    "pepe": "PEPE", "shiba": "SHIB", "memecoin": "MEME",
}

# ═══════════════════════════════════════════════════════════
# 🌍 السياق والرفض
# ═══════════════════════════════════════════════════════════
CRYPTO_CONTEXT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "ether", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token", "coin",
    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "polygon", "matic",
    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
    "web3", "wallet", "staking", "mining", "halving", "smart contract",
    "decentralized", "dex", "cex", "ledger", "satoshi",
    "sec", "gensler", "spot etf", "blackrock bitcoin", "fidelity crypto",
    "grayscale", "microstrategy", "saylor", "cz", "vitalik",
    "litecoin", "ltc", "tron", "trx", "toncoin", "ton",
    "stellar", "xlm", "hedera", "hbar", "near protocol", "aptos", "apt",
    "arbitrum", "arb", "optimism", "op", "sei", "sui",
    "pepe", "shiba", "memecoin", "shitcoin",
    "aave", "uniswap", "compound", "makerdao", "lido", "rocket pool",
    "restaking", "ethereum etf", "bitcoin etf",
    "on-chain", "token burn", "airdrop", "ico", "ieo",
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
# ⚙️ إعدادات التشغيل
# ═══════════════════════════════════════════════════════════
ALERT_COOLDOWN = 21600  # 6 ساعات
MAX_NEWS_PER_SCAN = 40
MAX_NEWS_AGE = 10800    # 3 ساعات
SCAN_INTERVAL = 300     # 5 دقائق
SUMMARY_HOUR = 23
SUMMARY_MINUTE = 58

# ═══════════════════════════════════════════════════════════
# 📂 التخزين الدائم (Gist + Local)
# ═══════════════════════════════════════════════════════════
if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
    _PERSISTENT_DIR = os.getcwd()
else:
    _PERSISTENT_DIR = "/tmp"

SENT_NEWS_FILE = os.path.join(_PERSISTENT_DIR, "sent_news.json")
SETTINGS_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "news_settings.json")
ALLOWED_FILE_LOCAL = os.path.join(_PERSISTENT_DIR, "allowed_users.json")

# ═══════════════════════════════════════════════════════════
# 🌐 Headers
# ═══════════════════════════════════════════════════════════
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/2.0; +https://github.com/whale-news)"}
REDDIT_HEADERS = {"User-Agent": "WhaleNewsBot/2.0 by u/whale_news_bot"}

# ═══════════════════════════════════════════════════════════
# 🕐 Timezone
# ═══════════════════════════════════════════════════════════
tz = pytz.timezone(os.environ.get("TIMEZONE", "Africa/Algiers"))

# ═══════════════════════════════════════════════════════════
# 📊 إعدادات التنبيهات (mutable - تُحمّل/تُحفظ)
# ═══════════════════════════════════════════════════════════
class BotState:
    """حالة البوت القابلة للتبديل"""
    def __init__(self):
        self.auto_alerts_enabled: bool = True
        self.alert_categories: Dict[str, bool] = {
            "crypto": True, "macro": True, "breaking": True, 
            "tech": True, "market": True
        }
        self.channel_enabled: Optional[bool] = None
        self.bot_shutdown: bool = False
        self.daily_summary_enabled: bool = True
        self.bot_resume_time: float = 0.0
        self._skip_old_news_once: bool = False
        self.sent_news_hashes: Set[str] = set()
        self.last_alerts_hashes: Dict[str, float] = {}
        self.allowed_users: Set[int] = set()

    def is_channel_enabled(self, config: BotConfig) -> bool:
        if self.channel_enabled is not None:
            return self.channel_enabled and bool(config.CHANNEL_ID)
        return config.SEND_TO_CHANNEL and bool(config.CHANNEL_ID)

# ═══════════════════════════════════════════════════════════
# 🗄️ Gist Manager (async)
# ═══════════════════════════════════════════════════════════
class GistManager:
    """مدير Gist مع batching و caching"""
    def __init__(self, token: str):
        self.token = token
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, float] = {}
        self._pending_writes: Dict[str, str] = {}
        self._write_lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """طلب HTTP مع retry"""
        import aiohttp
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(method, url, headers=headers, **kwargs, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        elif resp.status == 403:
                            retry_after = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60)) - int(time.time())
                            log.warning(f"Gist rate limited, waiting {retry_after}s")
                            await asyncio.sleep(min(retry_after, 60))
                        else:
                            log.warning(f"Gist HTTP {resp.status}")
                            return None
            except Exception as e:
                log.warning(f"Gist request attempt {attempt+1} failed: {e}")
                await asyncio.sleep(2 ** attempt)
        return None

    async def get(self, gist_id: str, filename: str) -> Optional[str]:
        """جلب محتوى ملف من Gist مع caching"""
        cache_key = f"{gist_id}:{filename}"
        now = time.time()
        if cache_key in self._cache and now - self._cache_ttl.get(cache_key, 0) < 60:
            return self._cache[cache_key]

        data = await self._request("GET", f"https://api.github.com/gists/{gist_id}")
        if data:
            files = data.get("files", {})
            if filename in files:
                content = files[filename].get("content", "")
                self._cache[cache_key] = content
                self._cache_ttl[cache_key] = now
                return content
        return None

    async def set(self, gist_id: str, filename: str, content: str):
        """حفظ محتوى في Gist مع batching"""
        async with self._write_lock:
            self._pending_writes[cache_key] = content
            if self._batch_task is None or self._batch_task.done():
                self._batch_task = asyncio.create_task(self._flush_writes(gist_id, filename))

    async def _flush_writes(self, gist_id: str, filename: str):
        """تفريغ الكتابات المجمعة"""
        await asyncio.sleep(30)  # انتظر 30 ثانية لتجميع الكتابات
        async with self._write_lock:
            if not self._pending_writes:
                return
            content = self._pending_writes.pop(cache_key, None)
            if content:
                await self._request("PATCH", f"https://api.github.com/gists/{gist_id}",
                                   json={"files": {filename: {"content": content}}})

# ═══════════════════════════════════════════════════════════
# 📦 إنشاء instances
# ═══════════════════════════════════════════════════════════
config = BotConfig()
state = BotState()
gist_manager = GistManager(config.GITHUB_TOKEN) if config.GITHUB_TOKEN else None

# Rate limiters
TELEGRAM_RATE_LIMITER = RateLimiter(rate=30, burst=30)  # 30 msg/sec
FARSIDE_RATE_LIMITER = RateLimiter(rate=0.5, burst=2)   # 2 req/sec

# Circuit breakers
TELEGRAM_CB = CircuitBreaker(failure_threshold=10, recovery_timeout=60)
FARSIDE_CB = CircuitBreaker(failure_threshold=5, recovery_timeout=300)
