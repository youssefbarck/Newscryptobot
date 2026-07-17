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
    "arbitrum", "arb", "optimism", "op", "sei", "sui",
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

# ═══════════════════════════════════════════════════════════
# كلمات مفتاحية للرفض / فلترة السبام
# ═══════════════════════════════════════════════════════════
REJECTION_KEYWORDS = [
    # سبام ومحتوى منخفض القيمة فقط
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
# كلمات مفتاحية عربية حرجة (أخبار عربية مهمة)
# ═══════════════════════════════════════════════════════════
AR_CRITICAL_KEYWORDS = [
    # أمن واختراقات
    "اختراق", "اخترق", "سرقة", "سُرق", "تم اختراق", "ثغرة", "احتيال",
    "استغلال", "اختراقات", "سايبر", "هجوم إلكتروني",
    # حركة السوق
    "انهيار", "انهار", "تدهور", "هبوط حاد", "سقوط", "تراجع حاد",
    "بيع جماعي", "تصفية", "ضغط",
    # مؤسسات وتدفقات
    "تدفقات", "تدفق", "استثمارات مؤسسية", "شراء كبير",
    "مايكروستراتيجي", "بلاك روك", "مؤسسي",
    # تحديثات تقنية
    "التنصيف", "انقسام", "تحديث الشبكة",
    "إطلاق الشبكة", "الشبكة الرئيسية",
    "فك توكن", "إلغاء تأمين", "حرق توكن", "حرق عملة", "إتلاف",
    # اقتصاد كلّي مؤثر
    "الفائدة", "الفيدرالي", "باول", "اجتماع الفيدرالي",
    "خفض الفائدة", "رفع الفائدة", "تثبيت الفائدة",
    "أسعار الفائدة", "الاحتياطي الفيدرالي",
    # تنظيم وقانون
    "موافقة", "رفض", "قانون", "تنظيم", "حظر", "عقوبات",
    # عملات (مطلوبة كسياق)
    "بيتكوين", "إيثيريوم", "بايننس", "كريبتو", "عملات رقمية",
    "عملات مشفرة", "البلوكتشين", "USDT", "USDC",
]

AR_REJECTION_KEYWORDS = [
    "تحليل", "توقعات", "متوقع", "قد يصل", "قد يصل إلى",
    "أفضل 10", "أفضل 5", "كيف تشتري", "شرح",
    "دليل", "ما هي", "تعرف على",
]


# ═══════════════════════════════════════════════════════════
# فحص اكتمال الخبر
# ═══════════════════════════════════════════════════════════
def is_complete_news(text):
    """يفحص هل النص مكتمل أم مقطوع
    يُستخدم بعد الترجمة لتجنب إرسال أخبار ناقصة.
    يعيد True إذا كان النص مكتملاً.
    
    القاعدة: العناوين الإخبارية عادة لا تنتهي بنقطة، لكنها مكتملة.
    نرفض فقط النصوص المنتهية بكلمات ناقصة واضحة.
    """
    if not text or len(text.strip()) < 15:
        return False

    trimmed = text.strip()

    # كلمات/رموز نهاية غير مكتملة (حروف جر وأدوات عربية شائعة)
    incomplete_endings = [
        "على", "في", "من", "إلى", "عن", "مع", "حتى", "خلال",
        "بعد", "قبل", "بين", "ضد", "عبر", "نحو", "لدى", "بسبب",
        "وذلك على", "وذلك في", "وذلك من",
        "✉️", "...", "،",
    ]

    # لو ينتهي بكلمة ناقصة → غير مكتمل
    for ending in incomplete_endings:
        if trimmed.endswith(ending):
            return False

    # نصوص قصيرة (عناوين) بدون نقطة = عادية ومقبولة
    if len(trimmed) < 250:
        return True

    # نصوص طويلة بدون نقطة نهائية → غالباً مقطوعة
    if len(trimmed) >= 250 and not re.search(r'[.!؟!]$', trimmed):
        return False

    return True


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