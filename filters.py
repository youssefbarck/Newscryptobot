import re
import time

from config import (
    log, KEYWORDS_BREAKING, KEYWORDS_FED, KEYWORDS_WHALES, KEYWORDS_ETF,
    KEYWORDS_HACK, KEYWORDS_TECH, KEYWORDS_MARKET, alert_categories, NEWS_SOURCES,
)


# ═══════════════════════════════════════════════════════════
# كلمات مفتاحية مشتركة للسياق الكريبتوي
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
    "بيتكوين", "إيثيريوم", "كريبتو", "عملة رقمية", "عملة مشفرة", "بلوكتشين",
    "بايننس", "كوين بيس", "توكين", "تعدين", "محفظة",
]

# ═══════════════════════════════════════════════════════════
# كلمات مفتاحية للرفض / فلترة السبام
# ═══════════════════════════════════════════════════════════
REJECTION_KEYWORDS = [
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
    "[link]", "[تعليقات]", "[comments]", "/u/",
    "submitted by", "مقدم بواسطة",
    "crossposted from", "xposted from",
    "military strike", "airstrike", "drone strike",
    "gaza", "palestine", "hamas", "hezbollah", "houthi",
    "ukraine war", "zelensky", "kyiv", "moscow",
    "north korea", "kim jong",
    "syria", "lebanon", "yemen", "afghanistan",
    "ceasefire", "invasion", "nuclear weapon",
    "death toll", "casualties", "refugees",
    "حرب", "عسكرية", "صاروخ", "غزة", "فلسطين", "حماس",
    "أوكرانيا", "روسيا", "بوتين", "تايوان", "كوريا الشمالية",
    "سوريا", "لبنان", "اليمن", "ضحايا", "قتلى",
    "oil price", "crude oil", "opec", "barrel of oil",
    "refinery", "petroleum", "energy crisis",
    "النفط", "أوبك", "بترول",
    "dividend", "earnings report", "quarterly results",
    "apple stock", "tesla stock", "nvidia stock",
]

# ═══════════════════════════════════════════════════════════
# كلمات مفتاحية عربية حرجة (أخبار عربية مهمة)
# ═══════════════════════════════════════════════════════════
AR_CRITICAL_KEYWORDS = [
    "اختراق", "اخترق", "سرقة", "سُرق", "تم اختراق", "ثغرة", "احتيال",
    "استغلال", "اختراقات", "سايبر", "هجوم إلكتروني",
    "انهيار", "انهار", "تدهور", "هبوط حاد", "سقوط", "تراجع حاد",
    "بيع جماعي", "تصحيح", "تصفية", "ضغط",
    "تدفقات", "تدفق", "استثمارات مؤسسية", "شراء كبير",
    "مايكروستراتيجي", "بلاك روك", "مؤسسي",
    "تحديث", "ترقية", "التنصيف", "انقسام", "تحديث الشبكة",
    "إطلاق الشبكة", "الشبكة الرئيسية",
    "فك توكن", "إلغاء تأمين", "حرق توكن", "حرق عملة", "إتلاف",
    "كيفن وارش", "وارش", "kevin warsh", "warsh",
    "الفائدة", "الفيدرالي", "باول", "اجتماع الفيدرالي",
    "خفض الفائدة", "رفع الفائدة", "تثبيت الفائدة",
    "أسعار الفائدة", "الاحتياطي الفيدرالي",
    "بيتكوين", "إيثيريوم", "بايننس", "كريبتو", "عملات رقمية",
    "عملات مشفرة", "البلوكتشين", "USDT", "USDC",
    "موافقة", "رفض", "قانون", "تنظيم", "حظر", "عقوبات",
]

AR_REJECTION_KEYWORDS = [
    "تحليل", "توقعات", "متوقع", "قد يصل", "قد يصل إلى",
    "أفضل 10", "أفضل 5", "كيف تشتري", "شرح",
    "دليل", "ما هي", "تعرف على",
]


# ═══════════════════════════════════════════════════════════
# تصنيف الأخبار
# ═══════════════════════════════════════════════════════════
def classify_news(item):
    """🆕 يصنف الخبر بدقة باستخدام حدود الكلمات
    الفئات: breaking, fed, whale, etf, hack, tech, market
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
    # 🚫 تم حذف فئة trump (لا نرسل أخبار سياسة)
    if any(has_word(text, kw) for kw in KEYWORDS_WHALES):
        categories.append("whale")
    if any(has_word(text, kw) for kw in KEYWORDS_ETF):
        categories.append("etf")
    if any(has_word(text, kw) for kw in KEYWORDS_HACK):
        categories.append("hack")
    # فئات تقنية وسوقية
    if any(has_word(text, kw) for kw in KEYWORDS_TECH):
        categories.append("tech")
    if any(has_word(text, kw) for kw in KEYWORDS_MARKET):
        categories.append("market")
    # 🚫 تم حذف فئتي geopolitics و stocks (لا نرسل هذه الأخبار)
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
        # 🚫 تم حذف: trump, geopolitics, stocks
    }
    key = cat_map.get(category, "crypto")
    return alert_categories.get(key, True)