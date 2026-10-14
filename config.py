# -*- coding: utf-8 -*-
"""إعدادات بوت أخبار الكريبتو — تُقرأ من متغيرات البيئة أو ملف .env"""
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
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()

# ---------------------------------------------------------------- حساب تيليجرام
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ------------------------------------------------------- مفاتيح اختيارية
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "").strip()

# توقيع القناة يظهر أسفل كل خبر (اختياري) مثال: @MyCryptoNews
CHANNEL_SIGNATURE = os.getenv("CHANNEL_SIGNATURE", "").strip()

# ------------------------------------------------------------- إعدادات النشر
MIN_SCORE = int(os.getenv("MIN_SCORE", "7"))          # فلتر الجودة: أخبار قوية فقط (1-10)
MAX_NEWS_PER_RUN = int(os.getenv("MAX_NEWS_PER_RUN", "4"))  # أقصى عدد أخبار في الجولة
SEND_DELAY_SECONDS = float(os.getenv("SEND_DELAY_SECONDS", "2.5"))

# --------------------------------------------------------- إعدادات منع التكرار
STATE_FILE = os.getenv("STATE_FILE", "data/sent_news.json")
DEDUP_DAYS = int(os.getenv("DEDUP_DAYS", "14"))        # مدة حفظ بصمة الخبر (أيام)
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.8"))

# ------------------------------------------------------- المنطقة الزمنية للعرض
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "Africa/Algiers")

# ------------------------------------------------------------- مصادر RSS
RSS_FEEDS = [
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "Crypto.News", "url": "https://crypto.news/feed/"},
    {"name": "CryptoPotato", "url": "https://cryptopotato.com/feed/"},
    {"name": "U.Today", "url": "https://u.today/rss"},
    {"name": "Watcher.Guru", "url": "https://watcher.guru/feed"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/"},
    {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/"},
]

# ------------------------------------------------- أسعار السوق من CoinGecko
MARKET_COINS = [
    {"id": "bitcoin", "name": "بيتكوين", "symbol": "BTC"},
    {"id": "ethereum", "name": "إيثريوم", "symbol": "ETH"},
    {"id": "binancecoin", "name": "بينانس", "symbol": "BNB"},
    {"id": "solana", "name": "سولانا", "symbol": "SOL"},
    {"id": "ripple", "name": "ريبل", "symbol": "XRP"},
    {"id": "dogecoin", "name": "دوجكوين", "symbol": "DOGE"},
]

REQUEST_TIMEOUT = 20
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CryptoNewsBot/2.0; +https://github.com)"
}
