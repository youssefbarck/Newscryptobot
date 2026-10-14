# -*- coding: utf-8 -*-
"""⚙️ الإعدادات المركزية للبوت — تُقرأ من متغيرات البيئة أو ملف .env"""
import os


def _load_dotenv(path: str = ".env") -> None:
    """تحميل بسيط لملف .env إن وجد (بدون مكتبات خارجية)."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()

# ------------------------------------------------------------ حساب تيليجرام
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ------------------------------------------------------- مفاتيح API اختيارية
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "").strip()
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "").strip()

# 📢 وسم القناة — يظهر أسفل كل خبر (من ملفك القديم، قابل للتغيير عبر env)
CHANNEL_TAG = os.environ.get("CHANNEL_TAG", "@newscrypto1m").strip()

# ------------------------------------------------------------ إعدادات النشر
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "4"))   # أقصى أخبار بالجولة
MIN_SCORE = int(os.environ.get("MIN_SCORE", "7"))                   # فلتر الجودة (1-10)
MAX_NEWS_AGE_HOURS = int(os.environ.get("MAX_NEWS_AGE_HOURS", "4")) # لا أخبار أقدم من هذا
SEND_DELAY_SECONDS = float(os.environ.get("SEND_DELAY_SECONDS", "2.5"))
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "Africa/Algiers")

# --------------------------------------------------------- إعدادات منع التكرار
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.65"))
DEDUP_DAYS = int(os.environ.get("DEDUP_DAYS", "14"))                # مدة حفظ البصمة (أيام)

# ------------------------------------------------------------- مسارات الملفات
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEDUP_FILE = os.path.join(PROJECT_DIR, "data", "sent_news.json")

# --------------------------------------------------------------- مصادر RSS
RSS_SOURCES = [
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Decrypt",       "url": "https://decrypt.co/feed"},
    {"name": "Crypto.News",   "url": "https://crypto.news/feed/"},
    {"name": "CryptoPotato",  "url": "https://cryptopotato.com/feed/"},
    {"name": "U.Today",       "url": "https://u.today/rss"},
    {"name": "WatcherGuru",   "url": "https://watcher.guru/feed"},
    {"name": "NewsBTC",       "url": "https://www.newsbtc.com/feed/"},
    {"name": "Bitcoinist",    "url": "https://bitcoinist.com/feed/"},
    {"name": "BeInCrypto",    "url": "https://beincrypto.com/feed/"},
]

# --------------------------------- الكلمات المحمية من الترجمة (تبقى كما هي)
PROTECTED_NAMES = {
    # شخصيات
    "Michael Saylor", "Saylor", "Changpeng Zhao", "CZ",
    "Vitalik Buterin", "Vitalik", "Elon Musk", "Musk",
    "Jerome Powell", "Powell", "Gary Gensler", "Gensler",
    "Brian Armstrong", "Armstrong", "Brad Garlinghouse", "Garlinghouse",
    "Janet Yellen", "Yellen", "Sam Bankman-Fried", "SBF",
    "Jack Dorsey", "Dorsey", "Cathie Wood", "Donald Trump", "Trump",
    # شركات ومنصات
    "MicroStrategy", "Strategy", "BlackRock", "Fidelity", "Grayscale",
    "Binance", "Coinbase", "Kraken", "Bybit", "OKX",
    "Bitwise", "VanEck", "Invesco", "Tesla", "SpaceX",
    "Galaxy Digital", "Blockstream", "Tether", "Jump Trading",
    # صناديق ETF
    "IBIT", "FBTC", "GBTC", "ETHA", "EZET",
    # عملات رقمية
    "Bitcoin", "Ethereum", "Solana", "Ripple", "Cardano",
    "Dogecoin", "Avalanche", "Polkadot", "Chainlink",
    "Polygon", "Litecoin", "Tron", "Uniswap", "Aave",
    "Stellar", "Hedera", "Cosmos", "Toncoin",
    "Binance Coin", "USDT", "USDC",
    "Shiba Inu", "Pepe", "Worldcoin", "Near Protocol",
    "Aptos", "Arbitrum", "Optimism", "Sui",
    # مصطلحات كريبتو
    "DeFi", "NFT", "NFTs", "Web3", "DAO", "ICO",
    "ETF", "ETFs", "Spot ETF", "Layer 1", "Layer 2",
    "Mainnet", "Testnet", "Federal Reserve", "Fed",
    "SEC", "CFTC", "FOMC", "CPI", "GDP",
    "Bull Run", "Bear Market",
}

# التوكنات (BTC, ETH...) — تُكتشف تلقائيًا عبر regex
TICKER_PATTERN = (
    r"\b(?:BTC|ETH|BNB|SOL|XRP|ADA|DOGE|AVAX|DOT|LINK|MATIC|POL|LTC|TRX|UNI|AAVE|NEAR|"
    r"APT|ARB|OP|SUI|SEI|TON|ATOM|XLM|HBAR|USDT|USDC|DAI|SHIB|PEPE|WLD|TIA|INJ|RNDR|"
    r"RENDER|FET|RUNE|GMX|DYDX|EIGEN|ETHFI|PENDLE|JTO|JUP|RAY|BONK|WIF|FLOKI|"
    r"IBIT|FBTC|GBTC|ETHA|EZET|XMR)\b"
)

# ------------------------------------------------- أسعار السوق (ترويسة الجولة)
MARKET_COINS = [
    {"id": "bitcoin", "name": "بيتكوين", "symbol": "BTC"},
    {"id": "ethereum", "name": "إيثريوم", "symbol": "ETH"},
    {"id": "binancecoin", "name": "بينانس", "symbol": "BNB"},
    {"id": "solana", "name": "سولانا", "symbol": "SOL"},
    {"id": "ripple", "name": "ريبل", "symbol": "XRP"},
    {"id": "dogecoin", "name": "دوجكوين", "symbol": "DOGE"},
]

# ------------------------------------------------------------------ الشبكة
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
REQUEST_TIMEOUT = 20
