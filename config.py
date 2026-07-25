"""
⚙️ Whale News Bot — الإعدادات المبسّطة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
إعدادات أساسية بدون تعقيدات.
"""

import os, time, json, logging, asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
import pytz, requests


# ═══════════════════════════════════════════════════════════
# 📦 إعدادات البوت
# ═══════════════════════════════════════════════════════════
@dataclass
class BotConfig:
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
    RUN_MODE: str = "polling"

    def validate(self) -> List[str]:
        errors = []
        if not self.TOKEN:
            errors.append("❌ TELEGRAM_BOT_TOKEN not set")
        if not self.CHAT_ID:
            errors.append("❌ TELEGRAM_CHAT_ID not set")
        return errors


@dataclass
class BotState:
    """حالة البوت"""
    sent_news_hashes: Set[str] = field(default_factory=set)
    last_alerts_hashes: Dict[str, float] = field(default_factory=dict)
    auto_alerts_enabled: bool = True
    daily_summary_enabled: bool = False
    bot_shutdown: bool = False
    channel_enabled: Optional[bool] = None
    bot_resume_time: float = 0.0
    allowed_users: Set[int] = field(default_factory=set)

    def is_channel_enabled(self, cfg: BotConfig) -> bool:
        if self.channel_enabled is not None:
            return self.channel_enabled and bool(cfg.CHANNEL_ID)
        return cfg.SEND_TO_CHANNEL and bool(cfg.CHANNEL_ID)


# ═══════════════════════════════════════════════════════════
# ⏱️ Rate Limiter
# ═══════════════════════════════════════════════════════════
class RateLimiter:
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
                self._tokens = rate
                self._last_refill = now
            if self._tokens <= 0:
                sleep_time = self.period - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                self._tokens = self.rate
                self._last_refill = time.time()
            self._tokens -= 1


# ═══════════════════════════════════════════════════════════
# الإعدادات العامة
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

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0)"}

TELEGRAM_RATE_LIMITER = RateLimiter(rate=20, period=60)
FARSIDE_RATE_LIMITER = RateLimiter(rate=2, period=30)


# ═══════════════════════════════════════════════════════════
# 🌐 مصادر الأخبار
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsSource:
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
        "url": "https://coinpedia.org/feed/",
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
    "Federal Reserve": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "fed", "lang": "en"
    },
    "Google News - Crypto": {
        "url": "https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+cryptocurrency+OR+crypto+regulation&hl=en&gl=US&ceid=US:en",
        "category": "crypto", "lang": "en"
    },
    "Google News - ETF": {
        "url": "https://news.google.com/rss/search?q=bitcoin+ETF+OR+ethereum+ETF+OR+spot+ETF&hl=en&gl=US&ceid=US:en",
        "category": "etf", "lang": "en"
    },
    "Google News AR - Bitcoin": {
        "url": "https://news.google.com/rss/search?q=بيتكوين+OR+العملات+الرقمية+OR+كريبتو&hl=ar&gl=EG&ceid=EG:ar",
        "category": "crypto", "lang": "ar"
    },
}

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
# 🪙 خريطة العملات
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


# ═══════════════════════════════════════════════════════════
# 🎯 كلمات الفلترة
# ═══════════════════════════════════════════════════════════
CRYPTO_CONTEXT_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "ether", "crypto", "cryptocurrency",
    "blockchain", "altcoin", "stablecoin", "defi", "nft", "token", "coin",
    "binance", "coinbase", "tether", "usdt", "usdc", "xrp", "ripple",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "polygon", "matic",
    "polkadot", "dot", "avalanche", "avax", "chainlink", "link",
    "web3", "wallet", "staking", "mining", "halving", "smart contract",
    "decentralized", "dex", "cex", "ledger", "satoshi",
    "sec", "gensler", "spot etf", "blackrock", "fidelity",
    "grayscale", "microstrategy", "saylor", "cz", "vitalik",
    "litecoin", "ltc", "tron", "trx", "toncoin", "ton",
    "stellar", "xlm", "hedera", "hbar", "near protocol", "aptos", "apt",
    "arbitrum", "arb", "optimism", "sei", "sui", "pepe", "shiba",
    "aave", "uniswap", "lido", "restaking", "on-chain",
    "token burn", "airdrop",
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
    "تيثر", "سولانا", "ريبل",
    # اقتصاد كلّي مؤثر
    "federal reserve", "fed", "interest rate", "powell", "fomc", "rate cut", "rate hike",
    "inflation", "cpi", "gdp", "recession", "monetary policy",
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


# ═══════════════════════════════════════════════════════════
# 🔧 إعدادات التشغيل
# ═══════════════════════════════════════════════════════════
MAX_NEWS_PER_SCAN = 30
MAX_NEWS_AGE = 10800  # 3 ساعات
SCAN_INTERVAL = 300   # 5 دقائق
SUMMARY_HOUR = 23
SUMMARY_MINUTE = 59


# ═══════════════════════════════════════════════════════════
# 📦 كائن الإعدادات العام
# ═══════════════════════════════════════════════════════════
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GIST_ID_SENT_NEWS = os.environ.get("GIST_ID_SENT_NEWS", "")

if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("RUN_MODE") == "oneshot":
    _PERSISTENT_DIR = os.getcwd()
else:
    _PERSISTENT_DIR = "/tmp"

SENT_NEWS_FILE = os.path.join(_PERSISTENT_DIR, "sent_news.json")
sent_news_hashes = set()
_sent_news_dirty = False


def _gist_get(gist_id, filename):
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
    """تحميل الأخبار المُرسلة سابقاً"""
    global sent_news_hashes
    all_hashes = set()

    # Gist
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

    # ملف محلي
    try:
        with open(SENT_NEWS_FILE, "r") as f:
            data = json.load(f)
            hashes = set(data.get("hashes", []))
            if hashes:
                all_hashes.update(hashes)
                log.info(f"✅ Local: {len(hashes)} hashes")
    except Exception:
        pass

    # ملف الريبو
    repo_file = os.path.join(os.getcwd(), "sent_news.json")
    if os.path.exists(repo_file) and repo_file != SENT_NEWS_FILE:
        try:
            with open(repo_file, "r") as f:
                data = json.load(f)
                hashes = set(data.get("hashes", []))
                if hashes:
                    all_hashes.update(hashes)
        except Exception:
            pass

    sent_news_hashes = all_hashes
    log.info(f"📊 Dedup: {len(sent_news_hashes)} total loaded")


def save_sent_news(force: bool = False):
    """حفظ الأخبار المُرسلة"""
    global _sent_news_dirty
    import subprocess

    try:
        content = json.dumps(
            {"hashes": list(sent_news_hashes)[-2000:], "last_updated": time.time()},
            ensure_ascii=False, indent=2,
        )
        with open(SENT_NEWS_FILE, "w") as f:
            f.write(content)
    except Exception as e:
        log.warning(f"Local save error: {e}")

    # Git push (GitHub Actions)
    pushed = False
    if os.environ.get("GITHUB_ACTIONS") == "true":
        try:
            subprocess.run(["git", "config", "user.name", "news-bot[bot]"],
                           capture_output=True, check=True, timeout=10)
            subprocess.run(["git", "config", "user.email", "news-bot[bot]@users.noreply.github.com"],
                           capture_output=True, check=True, timeout=10)
            subprocess.run(["git", "add", "sent_news.json"],
                           capture_output=True, check=True, timeout=10)
            result = subprocess.run(["git", "status", "--porcelain", "sent_news.json"],
                                   capture_output=True, text=True, timeout=10)
            if result.stdout.strip():
                subprocess.run(["git", "commit", "-m", f"dedup: {len(sent_news_hashes)} hashes"],
                               capture_output=True, check=True, timeout=15)
                subprocess.run(["git", "push"],
                               capture_output=True, check=True, timeout=30)
                pushed = True
        except Exception as e:
            log.warning(f"Git push failed: {e}")

    # Gist
    if not pushed:
        _gist_set(_GIST_ID_SENT_NEWS, "sent_news.json",
                  json.dumps({"hashes": list(sent_news_hashes)[-2000:]}))


# ═══════════════════════════════════════════════════════════
# 🏭 كائن الإعدادات
# ═══════════════════════════════════════════════════════════
config = BotConfig(
    TOKEN=TOKEN, CHAT_ID=CHAT_ID, CHANNEL_ID=CHANNEL_ID,
    CHANNEL_NAME=CHANNEL_NAME, CHANNEL_LINK=CHANNEL_LINK,
    SEND_TO_CHANNEL=SEND_TO_CHANNEL, RENDER_URL=RENDER_URL,
    PORT=PORT, TIMEZONE=TIMEZONE,
    GITHUB_ACTIONS=os.environ.get("GITHUB_ACTIONS") == "true",
    RUN_MODE=os.environ.get("RUN_MODE", "polling"),
)

state = BotState()
