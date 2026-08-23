"""
⚙️ إعدادات البوت — تُقرأ من متغيرات البيئة (GitHub Secrets)
"""

import os
import logging

# ═══════════════════════════════════════════════════════════
# 📝 Logging
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("NewsBot")

# ═══════════════════════════════════════════════════════════
# 🔑 المفاتيح (تُضبط في GitHub Secrets)
# ═══════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")  # معرّف القناة مثل -1001234567890

# ═══════════════════════════════════════════════════════════
# 📢 وسم القناة — يُضاف في نهاية كل منشور
# ═══════════════════════════════════════════════════════════
CHANNEL_TAG = "@newscrypto1m"

# ═══════════════════════════════════════════════════════════
# 📰 مصادر RSS
# ═══════════════════════════════════════════════════════════
RSS_SOURCES = [
    # ⭐ 1) CoinDesk — المصدر الأول
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
        "type": "news",
    },
    # ⭐ 2) Watcher Guru — المصدر الثاني
    {
        "name": "WatcherGuru",
        "url": "https://watcher.guru/news/feed",
        "type": "news",
    },
    # ⭐ 3) Cointelegraph — المصدر الثالث (بدلاً من The Block المحجوب)
    {
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
        "type": "news",
    },
]

# ═══════════════════════════════════════════════════════════
# 🎯 الكلمات المفتاحية (للحفاظ عليها كما هي بالإنجليزية)
# ═══════════════════════════════════════════════════════════
PROTECTED_NAMES = {
    # شخصيات
    "Michael Saylor", "Saylor",
    "Changpeng Zhao", "CZ",
    "Vitalik Buterin", "Vitalik",
    "Elon Musk", "Musk",
    "Jerome Powell", "Powell",
    "Gary Gensler", "Gensler",
    "Brian Armstrong", "Armstrong",
    "Brad Garlinghouse", "Garlinghouse",
    "Janet Yellen", "Yellen",
    "Sam Bankman-Fried", "SBF",
    "Jack Dorsey", "Dorsey",
    "Cathie Wood", "Wood",
    # شركات ومنصات
    "MicroStrategy", "Strategy",
    "BlackRock", "Fidelity", "Grayscale",
    "Binance", "Coinbase", "Kraken", "Bybit", "OKX",
    "Bitwise", "VanEck", "Invesco",
    "Tesla", "SpaceX",
    "Galaxy Digital", "Blockstream",
    # صناديق ETF
    "IBIT", "FBTC", "GBTC", "ETHA", "EZET",
    # عملات رقمية (نُبقيها بالإنجليزية كما طلب المستخدم)
    "Bitcoin", "Ethereum", "Solana", "Ripple", "Cardano",
    "Dogecoin", "Avalanche", "Polkadot", "Chainlink",
    "Polygon", "Litecoin", "Tron", "Uniswap", "Aave",
    "Stellar", "Hedera", "Cosmos", "Toncoin",
    "Binance Coin", "Tether", "USDT", "USDC",
    "Shiba Inu", "Pepe", "Worldcoin", "Near Protocol",
    "Aptos", "Arbitrum", "Optimism", "Sui",
    # مصطلحات كريبتو
    "DeFi", "NFT", "NFTs", "Web3", "DAO", "ICO",
    "ETF", "ETFs", "Spot ETF",
    "Layer 1", "Layer 2", "Mainnet", "Testnet",
    "BlackRock", "Federal Reserve", "Fed", "SEC", "CFTC",
    "FOMC", "CPI", "GDP",
    "Bull Run", "Bear Market",
}

# التوكنات (BTC, ETH, SOL...) — تُكتشف تلقائياً عبر regex
TICKER_PATTERN = r'\b(?:BTC|ETH|BNB|SOL|XRP|ADA|DOGE|AVAX|DOT|LINK|MATIC|LTC|TRX|UNI|AAVE|NEAR|APT|ARB|OP|SUI|SEI|TON|ATOM|XLM|HBAR|USDT|USDC|DAI|SHIB|PEPE|WLD|TIA|INJ|RNDR|RENDER|FET|RUNE|GMX|DYDX|EIGEN|ETHFI|PENDLE|JTO|JUP|RAY|BONK|WIF|FLOKI|IBIT|FBTC|GBTC|ETHA|EZET)\b'

# ═══════════════════════════════════════════════════════════
# ⚙️ إعدادات التشغيل
# ═══════════════════════════════════════════════════════════
MAX_POSTS_PER_RUN = 2        # أقصى عدد منشورات كل دورة (الأهم فقط)
MAX_NEWS_AGE_HOURS = 6       # لا نرسل خبراً أقدم من 6 ساعات
SIMILARITY_THRESHOLD = 0.65  # عتبة التشابه (65% — فوقها يُعتبر مكرراً)
MAX_BULLETS = 4              # أقصى عدد نقاط في المنشور

# ═══════════════════════════════════════════════════════════
# 📁 ملف حفظ الهاشات (يُcommit في الريبو)
# ═══════════════════════════════════════════════════════════
import os.path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEDUP_FILE = os.path.join(PROJECT_DIR, "sent_news.json")
