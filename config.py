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
    WEBHOOK_URL: str = ""  # لوضع webhook (Vercel)
    CRON_SECRET: str = ""  # سر Vercel Cron

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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

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
    # ── العملات الرئيسية ──
    "bitcoin": "BTC", "btc": "BTC", "bitcoin cash": "BCH", "bch": "BCH",
    "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
    "ethereum classic": "ETC", "etc": "ETC",
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
    # ── عملات إضافية ──
    "monero": "XMR", "xmr": "XMR",
    "tezos": "XTZ", "xtz": "XTZ",
    "vechain": "VET", "vet": "VET",
    "theta": "THETA",
    "filecoin": "FIL", "fil": "FIL",
    "neo": "NEO",
    "iota": "IOTA", "miota": "IOTA",
    "zcash": "ZEC", "zec": "ZEC",
    "dash": "DASH",
    "eos": "EOS",
    "algorand": "ALGO", "algo": "ALGO",
    "flow": "FLOW",
    "celo": "CELO",
    "internet computer": "ICP", "icp": "ICP",
    "kaspa": "KAS", "kas": "KAS",
    "worldcoin": "WLD", "wld": "WLD",
    "starknet": "STRK", "strk": "STRK",
    "celestia": "TIA", "tia": "TIA",
    "injective": "INJ", "inj": "INJ",
    "render": "RENDER", "rndr": "RENDER",
    "fetch.ai": "FET", "fet": "FET",
    "thorchain": "RUNE", "rune": "RUNE",
    "ocean": "OCEAN",
    "kava": "KAVA",
    "lido dao": "LDO", "ldo": "LDO",
    "maker": "MKR", "mkr": "MKR",
    "curve": "CRV", "crv": "CRV",
    "synthetix": "SNX", "snx": "SNX",
    "compound": "COMP", "comp": "COMP",
    "yearn": "YFI", "yfi": "YFI",
    "balancer": "BAL", "bal": "BAL",
    "sushi": "SUSHI",
    "1inch": "1INCH",
    "pancake": "CAKE", "cake": "CAKE",
    "kyber": "KNC", "knc": "KNC",
    "loopring": "LRC", "lrc": "LRC",
    "gmx": "GMX",
    "dydx": "DYDX",
    "perp": "PERP",
    "rocket pool": "RPL", "rpl": "RPL",
    "jupiter": "JUP", "jup": "JUP",
    "raydium": "RAY", "ray": "RAY",
    "orca": "ORCA",
    "drift": "DRIFT",
    "hyperliquid": "HYPE", "hype": "HYPE",
    "pendle": "PENDLE",
    "jito": "JTO",
    "eigenlayer": "EIGEN", "eigen": "EIGEN",
    "etherfi": "ETHFI", "ethfi": "ETHFI",
    "renzo": "REZ", "renzo": "REZ",
    "puffer": "PUFFER",
    "morpho": "MORPHO",
    "aerodrome": "AERO", "aero": "AERO",
    "velodrome": "VELO", "velo": "VELO",
    "akasha": "AKT", "akash": "AKT", "akt": "AKT",
    "ondo": "ONDO",
    "io.net": "IO", "ionet": "IO",
    "grass": "GRASS",
    "aethir": "ATH",
    "bonk": "BONK",
    "wif": "WIF",
    "floki": "FLOKI",
    "bome": "BOME",
    "pengu": "PENGU",
    "peaq": "PEAQ",
    "berachain": "BERA", "bera": "BERA",
    "sonic": "SONIC",
    "virtuals": "VIRTUAL",
    "ai16z": "AI16Z",
    "bittensor": "TAO", "tao": "TAO",
    "decentraland": "MANA", "mana": "MANA",
    "sandbox": "SAND", "sand": "SAND",
    "axie infinity": "AXS", "axs": "AXS",
    "the graph": "GRT", "grt": "GRT",
    "livepeer": "LPT", "lpt": "LPT",
    "arweave": "AR", "ar": "AR",
    "helium": "HNT", "hnt": "HNT",
    "enjin": "ENJ", "enj": "ENJ",
    "gala": "GALA",
    "illuvium": "ILV", "ilv": "ILV",
    "immutable": "IMX", "imx": "IMX",
    "magic eden": "ME",
    "zk sync": "ZKS", "zks": "ZKS",
    "scroll": "SCR",
    "linea": "LINEA",
    "mantle": "MNT", "mnt": "MNT",
    "manta": "MANTA",
    "frax": "FRAX",
    "lusd": "LUSD",
    "pyusd": "PYUSD",
    "fdusd": "FDUSD",
    "first digital usd": "FDUSD",
    "wrapped bitcoin": "WBTC", "wbtc": "WBTC",
    "wrapped ether": "WETH", "weth": "WETH",
    "mantra": "OM", "om": "OM",
    "polyone": "POLY",
    "bitgert": "BRISE",
    "vite": "VITE",
    "xai": "XAI",
    "aleph zero": "AZERO",
    "radix": "XRD", "xrd": "XRD",
    "neon": "NEON",
    "zeta": "ZETA",
    "lumia": "LUMIA",
    "morpheus": "MNRS",
    "ritual": "RITUAL",
}


# ═══════════════════════════════════════════════════════════
# 🎯 كلمات الفلترة
# ═══════════════════════════════════════════════════════════
CRYPTO_CONTEXT_KEYWORDS = [
    # ── عملات رئيسية ──
    "bitcoin", "btc", "bitcoin cash", "bch", "ethereum", "eth", "ether", "etc",
    "solana", "sol", "xrp", "ripple", "cardano", "ada", "dogecoin", "doge",
    "avalanche", "avax", "polkadot", "dot", "chainlink", "link",
    "polygon", "matic", "litecoin", "ltc", "tron", "trx",
    "uniswap", "aave", "near protocol", "near", "aptos", "apt",
    "arbitrum", "arb", "optimism", "op", "sui", "sei",
    "pepe", "shiba inu", "shib", "toncoin", "ton",
    "fantom", "ftm", "cosmos", "atom", "stellar", "xlm",
    "hedera", "hbar", "binance coin", "bnb", "usdt", "usdc", "tether", "dai",
    "monero", "xmr", "tezos", "xtz", "vechain", "vet", "filecoin", "fil",
    "neo", "iota", "zcash", "zec", "eos", "algorand", "algo",
    "flow", "celo", "internet computer", "icp", "kaspa", "kas",
    "worldcoin", "wld", "starknet", "celestia", "tia", "injective", "inj",
    "render", "rndr", "fetch.ai", "fet", "thorchain", "rune",
    "jupiter", "jup", "raydium", "ray", "orca", "drift", "hyperliquid",
    "eigenlayer", "eigen", "etherfi", "renzo", "pendle",
    "ondo", "berachain", "bera", "sonic", "virtuals",
    "bittensor", "tao", "ai16z", "bonk", "wif", "floki",
    "bome", "pengu", "decentraland", "mana", "sandbox", "sand",
    "axie infinity", "axs", "the graph", "grt", "helium", "hnt",
    "maker", "mkr", "lido", "curve", "crv", "synthetix", "snx",
    "compound", "comp", "gmx", "dydx", "jito",
    # ── مصطلحات كريبتو عامة ──
    "crypto", "cryptocurrency", "blockchain", "altcoin", "stablecoin",
    "defi", "nft", "token", "coin", "web3", "dao",
    "memecoin", "shitcoin", "meme coin",
    "dex", "cex", "cefi",
    "etf", "etfs", "spot etf", "bitcoin etf", "ethereum etf",
    "hodl", "fomo", "fud", "rekt",
    # ── منصات ──
    "binance", "coinbase", "kraken", "bybit", "okx", "kucoin",
    "bitfinex", "bitstamp", "gemini", "crypto.com", "huobi", "htx",
    "bitget", "mexc", "upbit", "bithumb", "deribit", "bitmex",
    "uniswap", "sushiswap", "pancakeswap", "raydium", "jupiter exchange",
    "opensea", "magic eden", "blur",
    "metamask", "trust wallet", "ledger", "trezor",
    # ── بروتوكولات ──
    "eigenlayer", "lido", "rocket pool", "aave", "compound",
    "curve finance", "synthetix", "yearn finance",
    "chainlink", "pyth", "band protocol",
    "wormhole", "layerzero", "stargate",
    "arbitrum", "optimism", "base", "polygon",
    "solana", "ethereum", "bitcoin", "avalanche", "polkadot",
    # ── شركات ──
    "blackrock", "fidelity", "grayscale", "microstrategy", "strategy",
    "bitwise", "vaneck", "invesco", "21shares",
    "coinshares", "galaxy digital", "proshares",
    "blockstream", "digital currency group", "consensys",
    "circle", "paxos", "tether limited",
    "paypal", "visa", "mastercard",
    # ── صناديق ETF ──
    "ibit", "fbtc", "gbtc", "etha", "ezet",
    "hodl", "spot bitcoin", "bitcoin etf", "ethereum etf",
    # ── أشخاص ──
    "satoshi", "vitalik", "buterin", "saylor",
    "changpeng zhao", "cz", "musk", "dorsey",
    "brian armstrong", "brad garlinghouse",
    "sam bankman-fried", "sbf",
    # ── تنظيم ──
    "sec", "gensler", "cftc",
    "federal reserve", "fed", "powell", "fomc",
    "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "gdp", "recession", "monetary policy",
    # ── مصطلحات تقنية ──
    "staking", "restaking", "mining", "halving", "smart contract",
    "decentralized", "ledger", "wallet", "on-chain",
    "token burn", "airdrop", "token unlock",
    "liquidity", "tvl", "yield", "farming",
    "liquidation", "leverage", "futures",
    "hack", "exploit", "vulnerability", "rug pull",
    "inflows", "outflows", "whale", "whales",
    "layer 2", "layer 1", "mainnet", "testnet",
    "rollup", "zk", "zero-knowledge",
    "oracle", "bridge", "nft marketplace",
    "play-to-earn", "gamefi", "depin",
    "memecoin", "stablecoin", "defi",
    # ── اقتصاد كلّي ──
    "federal reserve", "fed", "interest rate", "powell", "fomc",
    "rate cut", "rate hike", "inflation", "cpi", "gdp",
    "recession", "monetary policy", "quantitative easing",
    "treasury", "yellen", "dollar", "nasdaq", "s&p",
    # ── عربي ──
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
    "تيثر", "سولانا", "ريبل", "تحصيص", "تنصيف",
    "إيردروب", "سوق صاعد", "سوق هابط", "قيمة سوقية",
    "استثمار", "مؤسسي", "تدفقات",
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

# ⚠️ مهم: مجلد ثابت لحفظ sent_news.json — لا نستخدم /tmp لأنه يُمحى عند إعادة التشغيل
# نستخدم مجلد المشروع نفسه دائماً
_PERSISTENT_DIR = os.path.dirname(os.path.abspath(__file__))

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


# ═══════════════════════════════════════════════════════════
# 🔄 Auto-Gist Discovery — إنشاء/بحث تلقائي (يحتاج GITHUB_TOKEN فقط)
# ═══════════════════════════════════════════════════════════
_AUTO_GIST_ID = None  # يُخزّن مؤقتاً أثناء التشغيل
_AUTO_GIST_SEARCHED = False
_GIST_LABEL = "whale-news-bot-hashes"


def _find_or_create_storage_gist():
    """البحث عن Gist تخزين تلقائياً أو إنشاء واحد جديد"""
    global _AUTO_GIST_ID, _AUTO_GIST_SEARCHED
    if _AUTO_GIST_ID:
        return _AUTO_GIST_ID
    if _AUTO_GIST_SEARCHED:
        return _AUTO_GIST_ID
    _AUTO_GIST_SEARCHED = True

    if not _GITHUB_TOKEN:
        log.warning("⚠️ GITHUB_TOKEN غير موجود — لن يتم حفظ الهاشات بين مرات التشغيل!")
        log.warning("   ➜ اذهب: https://github.com/settings/tokens")
        log.warning("   ➤ أنشئ توكن → أضفه في Vercel كـ GITHUB_TOKEN")
        return None

    try:
        # 1) البحث عن Gist موجود بالوصف المميز
        page = 1
        while page <= 3:  # أقصى 3 صفحات = 300 gist
            try:
                r = requests.get(
                    "https://api.github.com/gists",
                    headers={
                        "Authorization": f"token {_GITHUB_TOKEN}",
                        "Accept": "application/vnd.github.v3+json"
                    },
                    params={"per_page": 100, "page": page},
                    timeout=10
                )
                if r.status_code != 200:
                    break
                gists = r.json()
                if not gists:
                    break
                for gist in gists:
                    if isinstance(gist, dict) and gist.get("description") == _GIST_LABEL:
                        _AUTO_GIST_ID = gist["id"]
                        log.info(f"✅ Auto-Gist found: {_AUTO_GIST_ID}")
                        return _AUTO_GIST_ID
                page += 1
            except Exception:
                break

        # 2) إنشاء Gist جديد
        r = requests.post(
            "https://api.github.com/gists",
            headers={
                "Authorization": f"token {_GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={
                "description": _GIST_LABEL,
                "public": False,
                "files": {
                    "sent_news.json": {
                        "content": json.dumps({"hashes": [], "last_updated": 0})
                    }
                }
            },
            timeout=15
        )
        if r.status_code == 201:
            _AUTO_GIST_ID = r.json()["id"]
            log.info(f"✅ Auto-Gist created: {_AUTO_GIST_ID}")
            return _AUTO_GIST_ID
        else:
            log.warning(f"Gist create failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log.warning(f"Auto-Gist error: {e}")

    return None


def _get_active_gist_id():
    """إرجاع معرّف الـ Gist النشط — يدووي أو تلقائي"""
    if _GIST_ID_SENT_NEWS:
        return _GIST_ID_SENT_NEWS
    return _find_or_create_storage_gist()


def load_sent_news():
    """تحميل الأخبار المُرسلة سابقاً — من ملف محلي ثابت
    
    ⚠️ مهم: نستخدم clear()+update() بدلاً من = لإبقاء نفس المرجع
    لأن باقي الملفات تستورد sent_news_hashes مرة واحدة عند بدء التشغيل.
    """
    global sent_news_hashes
    all_hashes = set()

    # المصدر الأساسي: ملف محلي ثابت في مجلد المشروع
    try:
        if os.path.exists(SENT_NEWS_FILE):
            with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                hashes = set(data.get("hashes", []))
                if hashes:
                    all_hashes.update(hashes)
                    log.info(f"✅ Local file: {len(hashes)} hashes from {SENT_NEWS_FILE}")
                else:
                    log.info(f"ℹ️ Local file exists but empty: {SENT_NEWS_FILE}")
        else:
            log.info(f"ℹ️ No sent_news.json yet — first run. Path: {SENT_NEWS_FILE}")
    except Exception as e:
        log.warning(f"❌ Local load error: {e}")

    # ⚠️ الإصلاح: تحديث المجموعة الموجودة بدلاً من إنشاء واحدة جديدة
    sent_news_hashes.clear()
    sent_news_hashes.update(all_hashes)
    log.info(f"📊 Dedup loaded: {len(sent_news_hashes)} hashes total")


def save_sent_news(force: bool = False):
    """حفظ الأخبار المُرسلة — ملف محلي ثابت فقط"""
    global _sent_news_dirty

    try:
        content = json.dumps(
            {"hashes": list(sent_news_hashes)[-2000:], "last_updated": time.time()},
            ensure_ascii=False, indent=2,
        )
        # التأكد من أن المجلد موجود
        os.makedirs(os.path.dirname(SENT_NEWS_FILE), exist_ok=True)
        with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        log.info(f"💾 Saved {len(sent_news_hashes)} hashes → {SENT_NEWS_FILE}")
    except Exception as e:
        log.error(f"❌ Save error: {e}")
        log.error(f"   Path: {SENT_NEWS_FILE}")
        log.error(f"   Dir exists: {os.path.exists(os.path.dirname(SENT_NEWS_FILE))}")
        log.error(f"   Writable: {os.access(os.path.dirname(SENT_NEWS_FILE), os.W_OK)}")


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
    WEBHOOK_URL=WEBHOOK_URL, CRON_SECRET=CRON_SECRET,
)

state = BotState()
