# -*- coding: utf-8 -*-
"""تصنيف الأخبار + القوالب العربية الجذابة — هنا يُصنع «الطعم» 🌶️"""
import re

# ---------------------------------------------------------------- أسماء العملات بالعربية
COIN_AR = {
    "BTC": "بيتكوين", "ETH": "إيثريوم", "SOL": "سولانا", "XRP": "ريبل",
    "BNB": "بينانس كوين", "DOGE": "دوجكوين", "ADA": "كاردانو", "TRX": "ترون",
    "DOT": "بولكادوت", "LINK": "تشين لينك", "AVAX": "أفالانش", "LTC": "لايتكوين",
    "SHIB": "شيبا إينو", "PEPE": "بيبي", "XLM": "ستيلار", "ATOM": "كوزموس",
    "NEAR": "نير", "ARB": "أربيتروم", "OP": "أوبتيميزم", "MATIC": "بوليغون",
    "POL": "بوليغون", "USDT": "تيثر", "USDC": "يو إس دي كوين", "TON": "تون كوين",
    "SUI": "سوي", "APT": "أبتوس", "UNI": "يوني سواب", "AAVE": "آفي", "MON": "مونيرو",
}

# رموز العملات في العناوين الإنجليزية (لحساب الأهمية)
COIN_TICKERS_RE = re.compile(
    r"\b(BTC|ETH|SOL|XRP|DOGE|ADA|BNB|TRX|DOT|LINK|AVAX|LTC|SHIB|PEPE|XLM|ATOM|"
    r"NEAR|ARB|OP|MATIC|POL|USDT|USDC|TON|SUI|APT|UNI|AAVE|XMR)\b", re.I)

# عملات مذكورة بالاسم الكامل في العنوان (تعطي نقاط أهمية أيضًا)
MAJOR_COIN_NAMES_RE = re.compile(
    r"\b(bitcoin|ethereum|solana|xrp|ripple|dogecoin|binance|bnb|cardano|tron|"
    r"chainlink|avalanche|litecoin|shiba|pepe|tether|usdt|usdc|polygon|"
    r"arbitrum|optimism|toncoin|uniswap|aave|aptos|sui|monero)\b", re.I)

# ---------------------------------------------------------------- التصنيفات
# priority: ترتيب فحص التصنيفات (الأعلى أولًا) | score_bonus: نقاط تُضاف للأهمية
CATEGORIES = {
    "hack": {
        "emoji": "🚨",
        "label": "عاجل | اختراق وأمن",
        "priority": 5,
        "score_bonus": 2,
        "keywords": re.compile(
            r"\b(hack(?:ed|er|ers|ing|s)?|breach(?:ed)?|exploit(?:ed)?|drain(?:ed)?|"
            r"steal|stole|stolen|phish(?:ing)?|rug\s?pull|scam(?:med|mers?)?|heist|"
            r"attack(?:ed|ers?)?|compromis\w+|malware|security\s+(?:incident|breach)|"
            r"swindl\w+|ponzi|money\s+launder\w+|launder\w+)\b", re.I),
        "hooks": [
            "لصوص الكريبتو ضربوا مجددًا 😱",
            "منطقة حمراء — انتبه لمحفظتك 🔴",
            "تحديث أمني يستحق التوقف عنده ⚠️",
            "الثغرات تُصطاد ملايين اليوم 🎣",
        ],
        "why": [
            "اختراق بهذا الحجم يهز ثقة المتداولين ويضغط على سعر العملة المتأثرة خلال ساعات. فعّل التحقق بخطوتين وتجنّب إبقاء أموالك على المنصة المتأثرة.",
            "قاعدة الذهب في الكريبتو: «ليست مفاتيحك… ليست عملاتك». تابع البيانات الرسمية للمنصة قبل أي قرار.",
            "السوق عادةً يبتلع صدمات الاختراقات ويرتد، لكن الخسارة الكبرى تكون لمن ترك أمواله في المكان الخطأ وقتها.",
        ],
    },
    "whale": {
        "emoji": "🐋",
        "label": "عين الحيتان | حركة ضخمة",
        "priority": 4,
        "score_bonus": 2,
        "keywords": re.compile(
            r"\b(whales?|whale[- ]alerts?|dormant|sleeping|satoshi[- ]era|"
            r"old wallet|aged wallet|ancient wallet|decade[- ]old|years?[- ]old wallet|"
            r"moved\s+[\d,.]+\s*(btc|eth|sol|xrp|doge|bnb)|moves?\s+[\d,.]+\s*(btc|eth|sol|xrp|doge|bnb)|"
            r"transfer(?:s|red)?\s+[\d,.]+\s*(btc|eth|sol|xrp|doge|bnb)|"
            r"\$[\d,.]+\s*(billion|million)\s+(?:worth of\s+)?(?:in\s+)?(?:btc|bitcoin|eth|ethereum)|"
            r"giant|huge\s+(?:transfer|transaction|movement))\b", re.I),
        "hooks": [
            "عين على المحافظ العملاقة 👀",
            "حركة ضخمة رصدتها أجهزة التتبع 📡",
            "حوت يتقلب في الأعماق 🐋",
            "عند العملاق لا حركة اعتيادية 💪",
        ],
        "why": [
            "تحركات الحيتان كثيرًا ما تسبق تقلبات حادة: التحويل نحو البورصات إشارة بيع محتملة، والسحب نحو المحافظ الباردة يعني تجميعًا وثقة.",
            "عندما يتحرك هذا الحجم من العملات يتحرك السوق معه غالبًا — المحترفون يراقبون الحيتان قبل شموع الرسم البياني.",
            "الحيتان إما تعرف شيئًا أو تراهن على شيء. متابعة مساراتها تمنحك قراءة أعمق من مجرد أخبار السعر.",
        ],
    },
    "regulation": {
        "emoji": "⚖️",
        "label": "الأنظمة والقوانين",
        "priority": 3,
        "score_bonus": 1,
        "keywords": re.compile(
            r"\b(sec|cftc|regulat\w+|lawsuit|sue[sd]?|suing|court|judg\w+|verdict|"
            r"banned?|ban\b|legaliz\w+|legislation|government|treasury|central\s+bank|"
            r"senate|congress|parliament|compliance|mica|sanctions?|indict\w+|"
            r"charges?|settle\w+|approv\w+|greenlights?|authoriz\w+|license|cbdc)\b", re.I),
        "hooks": [
            "واشنطن والكريبتو… الفصل القادم 🏛️",
            "قرار قانوني قد يغيّر قواعد اللعبة 📜",
            "الدول الكبرى تتحرك الآن 🌍",
            "بين الضغط والتبني… المنظّمون يقررون 🎯",
        ],
        "why": [
            "القرارات التنظيمية هي البوصلة التي تحدد اتجاه السوق لأشهر: التسهيلات ترفع الأسعار والتقييدات تضغط عليها.",
            "هذا النوع من الأخبار يصنع اتجاهات طويلة الأمد وليس مجرد تقلب يومي — المؤسسات الكبرى تنتظر هذه الإشارات قبل الدخول.",
        ],
    },
    "tech": {
        "emoji": "🚀",
        "label": "تقنية ومشاريع",
        "priority": 2,
        "score_bonus": 1,
        "keywords": re.compile(
            r"\b(etf|upgrade|launch(?:es|ed|ing)?|mainnet|partnership|partner(?:s|ed|ship)?|"
            r"integrat\w+|listing|lists\b|listed\b|airdrop|fork|stablecoin|adopt\w*|"
            r"rollout|unveil\w*|announc\w+|deploy\w*|testnet|staking|burn(?:s|ed|ing)?|"
            r"acquisition|acquires?|investment|raises?\s+\$|funding|token\s+unlock)\b", re.I),
        "hooks": [
            "وقود جديد للسوق ⛽",
            "المطورون لا ينامون 👨‍💻",
            "خطوة قد تصنع قيمة طويلة الأمد 🧱",
            "مشهد البناء يتوسع 🏗️",
        ],
        "why": [
            "التطويرات التقنية والشراكات الكبرى هي وقود النمو الحقيقي للمشاريع — بعيدًا عن ضجيج التداول اليومي، هذه الأخبار تبني القيمة طويلة الأمد.",
            "الترقيات والتبنّي المؤسسي عادةً ما تنعكس على السعر قبل أن ينتبه الجميع — القصة الكبيرة تبدأ من هنا.",
        ],
    },
    "price": {
        "emoji": "📈",
        "label": "زعزعة السوق",
        "priority": 1,
        "score_bonus": 0,
        "keywords": re.compile(
            r"\b(surge[sd]?|soar\w*|plunge[sd]?|dump\w*|pump\w*|rall(?:y|ies|ied)|crash\w*|"
            r"spike[sd]?|slump\w*|jump[sd]?|skyrocket\w*|plummet\w*|sink[s]?|tumbl\w*|"
            r"dips?|drop(?:ped|s)?|slide[sd]?|all[- ]time\s+high|ath\b|atl\b|liquidat\w+|"
            r"volatile|volatility|greed|fear|correction|"
            r"(?:loses?|lost|slips?|retests?|bounces?)\s+(?:\$[\d,.]+\s+)?support)\b", re.I),
        "hooks": [
            "الأرقام تتقلب بسرعة ⚡",
            "تصحيح أم موجة جديدة؟ 🤔",
            "السوق في مزاج متقلب اليوم 🎢",
            "لافتات البيع والشراء مضاءة 🚦",
        ],
        "why": [
            "التحركات الحادة تجذب السيولة والمضاربين دفعة واحدة — إن كنت تتداول انتبه للسيولة، وإن كنت تستثمر طويل الأمد فقلّل الضجيج وفكر بوضوح.",
            "الحركات الكبيرة غالبًا ما تأتي بحجم تداول استثنائي — راقب حجم الصفقات قبل الانسياق وراء العنوان.",
        ],
    },
}

# ترتيب الفحص حسب priority (hack أولًا ثم whale…)
CATEGORY_ORDER = sorted(CATEGORIES.keys(), key=lambda k: CATEGORIES[k]["priority"], reverse=True)

# التصنيفات الحساسة (اختراق/حيتان) تُفحص في العنوان فقط لتجنب الإيجابيات الكاذبة
TITLE_ONLY_CATEGORIES = {"hack", "whale"}

# --------------------------------------------------- قوالب اتجاه تحركات الحيتان (Whale Alert)
WHALE_DIRECTION_WHY = {
    "to_exchange": "التحويل نحو البورصة يُقرأ غالبًا كإشارة بيع محتملة — الحيتان لا تحوّل ملايين الدولارات للزينة. راقب السعر خلال الساعات القادمة.",
    "from_exchange": "سحب عملات من البورصة نحو محفظة خاصة يعني غالبًا تجميعًا أو تحصينًا طويل الأمد — قراءة إيجابية يفسّرها المتداولون كثقة.",
    "unknown": "نقل بين محافظ غير معروفة — قد يكون إعادة ترتيب حماية أو تمهيدًا لخطوة قادمة. الأهم أين يهبط المبلغ في النهاية.",
}


def categorize(title: str, summary: str = "") -> str | None:
    """تصنيف الخبر حسب أولوية التصنيفات — hack ثم whale ثم regulation…"""
    for key in CATEGORY_ORDER:
        if CATEGORIES[key]["keywords"].search(title):
            return key
    if summary:
        for key in CATEGORY_ORDER:
            if key in TITLE_ONLY_CATEGORIES:
                continue
            if CATEGORIES[key]["keywords"].search(summary[:300]):
                return key
    return None
