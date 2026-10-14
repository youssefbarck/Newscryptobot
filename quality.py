# -*- coding: utf-8 -*-
"""🧹 جودة النشر: منع العناوين الممنوعة + تقييم الأهمية + فحص سلامة المنشور.

موروث من ملفك القديم (منع الأسئلة/التحليلات/الإعلانات + نسبة العربية)
مدموجًا مع نظام النقاط من 10 والفحص النهائي للمنشور.
"""
import re
from datetime import datetime, timezone

from categories import CATEGORIES, COIN_AR, COIN_TICKERS_RE, MAJOR_COIN_NAMES_RE
from config import SIMILARITY_THRESHOLD, CHANNEL_TAG

# ---------------------------------------------------------- منع العناوين الفاسدة
QUESTION_ENDINGS = re.compile(r"[?؟]\s*$")
TEASER_PATTERNS = [
    r"^here\b", r"^what\s+happened", r"^here'?s\s+what",
    r"^things\s+to\s+know", r"^what\s+you\s+need",
    r"^everything\s+you", r"^all\s+you\s+need",
    r"^why\s+you\s+should", r"^should\s+you\b",
    r"^is\s+it\s+time\b", r"^will\s+\w+\s+(go|rise|fall|surge|crash)",
    r"^what'?s\s+next", r"^what\s+to\s+expect",
]
ANALYSIS_PATTERNS = [
    r"\bstudy\b", r"\bresearch\b", r"\bsurvey\b", r"\breport\s+says\b",
    r"\baccording\s+to\s+a\s+study\b", r"\bfinds\s+that\b",
    r"\bopinion\b", r"\bcommentary\b",
    r"^state\s+of\b", r"\bweekly\s+roundup\b", r"\bdaily\s+digest\b",
    r"\bprice\s+prediction\b", r"\bprice\s+forecast\b",
    r"\btop\s+\d+\s+(altcoins|coins|meme|gainers)",
    r"\b\d+\s+(crypto|bitcoin|altcoin)\s+to\s+watch\b",
]
PROMO_PATTERNS_AR = [
    r"اقرأ المزيد", r"تابع القراءة", r"اضغط هنا",
    r"للمزيد", r"لمشاهدة", r"للاطلاع",
    r"المصدر[:\s]", r"تابعنا",
]
PROMO_PATTERNS_EN = [
    r"read more", r"click here", r"learn more",
    r"subscribe", r"follow us", r"source[:\s]",
    r"disclaimer", r"related articles",
]


def is_banned_title(title: str) -> bool:
    """فحص صارم للعنوان الإنجليزي: سؤال / تلميح تشويقي / تحليل / قصير جدًا."""
    if not title:
        return True
    t = title.strip()
    t_lower = t.lower()
    if QUESTION_ENDINGS.search(t):
        return True
    if "?" in t or "؟" in t:
        return True
    for pat in TEASER_PATTERNS:
        if re.search(pat, t_lower):
            return True
    for pat in ANALYSIS_PATTERNS:
        if re.search(pat, t_lower):
            return True
    if len(t) < 20:
        return True
    return False


def is_banned_title_ar(title_ar: str) -> bool:
    """فحص العنوان المترجم بعد الترجمة (أسئلة/إعلانات)."""
    if not title_ar:
        return True
    t = title_ar.strip()
    if "?" in t or "؟" in t:
        return True
    for pat in PROMO_PATTERNS_AR:
        if re.search(pat, t, re.IGNORECASE):
            return True
    if len(t) < 15:
        return True
    return False


def clean_title_ar(title: str) -> str:
    """تنظيف العنوان المترجم من العيوب وبقايا placeholders."""
    if not title:
        return ""
    title = re.sub(r"\[\[\s*\d+\s*\]\]", "", title)
    title = re.sub(r"§\d+§?", "", title)
    for pat in PROMO_PATTERNS_AR + PROMO_PATTERNS_EN:
        title = re.sub(pat, "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s{2,}", " ", title).strip()
    title = re.sub(r"^[•·▪►»«\-\s]+", "", title)
    title = re.sub(r"\s*[\-|–—]\s*$", "", title)
    title = re.sub(r"\s+([.،,!؟?])", r"\1", title)
    title = re.sub(r"^(وفقا\s+لل?|كما\s+يوضح|يُظهر\s+أن|تشير\s+البيانات)\s*",
                   "", title, flags=re.IGNORECASE)
    return title.strip()


# ---------------------------------------------------------- استخراج الأرقام
_USD_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(trillion|billion|million|thousand|bn|b|m|k|t)?\b", re.I)
_COIN_AMOUNT_RE = re.compile(
    r"\b([\d,]{2,}(?:\.\d+)?)\s*(BTC|ETH|SOL|XRP|DOGE|ADA|BNB|TRX|DOT|LINK|AVAX|LTC|"
    r"SHIB|PEPE|XLM|ATOM|NEAR|ARB|OP|MATIC|POL|USDT|USDC|TON|SUI|APT|UNI|AAVE|XMR)\b", re.I)
_MULT = {"trillion": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
         "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_BUZZ_RE = re.compile(
    r"\b(breaking|urgent|just\s+in|alert|massive|huge|record|historic|shock\w*|"
    r"sensational|unprecedented|surprise|dramatic|stunning|bombshell)\b", re.I)
_PCT_RE = re.compile(r"\b\d{1,2}(?:\.\d+)?\s?%\b")


def human_usd(value: float) -> str:
    """780000000 → «780 مليون دولار»."""
    v = float(value)
    if v >= 1e12:
        return f"{v / 1e12:.1f}".rstrip("0").rstrip(".") + " تريليون دولار"
    if v >= 1e9:
        return f"{v / 1e9:.1f}".rstrip("0").rstrip(".") + " مليار دولار"
    if v >= 1e6:
        return f"{v / 1e6:.1f}".rstrip("0").rstrip(".") + " مليون دولار"
    if v >= 1e3:
        return f"{v / 1e3:.1f}".rstrip("0").rstrip(".") + " ألف دولار"
    return f"{v:,.0f} دولار"


def _max_usd(title: str) -> float:
    best = 0.0
    for m in _USD_RE.finditer(title):
        raw = m.group(1).replace(",", "")
        mult = _MULT.get((m.group(2) or "").lower(), 1)
        best = max(best, float(raw) * mult)
    return best


def extract_facts(title: str) -> list[str]:
    """استخراج الأرقام من العنوان: القيمة بالدولار + الكميات."""
    facts: list[str] = []
    for m in _USD_RE.finditer(title):
        raw = m.group(1).replace(",", "")
        mult = _MULT.get((m.group(2) or "").lower(), 1)
        value = float(raw) * mult
        if value >= 1_000_000:
            facts.append(f"💰 القيمة التقديرية: {human_usd(value)}")
    for m in _COIN_AMOUNT_RE.finditer(title):
        sym = m.group(2).upper()
        amount = m.group(1)
        if sym in COIN_AR:
            facts.append(f"🪙 الكمية: {amount} {COIN_AR[sym]}")
    # إزالة التكرار مع الحفاظ على الترتيب، وبحد أقصى 3 أسطر
    seen, unique = set(), []
    for f in facts:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique[:3]


# ---------------------------------------------------------- حساب الأهمية
def score_news(item, category: str) -> int:
    """درجة أهمية من 1 إلى 10 — فلتر الجودة يعتمد عليها."""
    title = item.title
    s = 4  # أساس

    # حجم المبلغ المذكور
    usd = _max_usd(title)
    if usd >= 1e9:
        s += 3
    elif usd >= 1e8:
        s += 2
    elif usd >= 1e7:
        s += 1

    # عملة مشهورة مذكورة؟
    if COIN_TICKERS_RE.search(title) or MAJOR_COIN_NAMES_RE.search(title):
        s += 2

    # نسبة مئوية حادة في العنوان
    if _PCT_RE.search(title):
        s += 1

    # نقاط التصنيف نفسه
    s += CATEGORIES[category]["score_bonus"]

    # طزاجة الخبر
    if item.timestamp > 0:
        age_hours = (datetime.now(timezone.utc).timestamp() - item.timestamp) / 3600
        if age_hours <= 1:
            s += 3
        elif age_hours <= 3:
            s += 2
        elif age_hours <= 8:
            s += 1

    # شعور CryptoPanic (من الملف القديم)
    sentiment = (getattr(item, "sentiment", "") or "").lower()
    if sentiment == "important":
        s += 2
    elif sentiment in ("hot", "rising"):
        s += 1

    # كلمات حماس
    if _BUZZ_RE.search(title):
        s += 1

    return max(1, min(10, s))


# ---------------------------------------------------------- فحص سلامة المنشور
_PLACEHOLDER_RE = re.compile(r"\[\[\s*\d+\s*\]\]")
_SOURCE_LEAK_RE = re.compile(
    r"\b(Cryptonews\.net|CryptoRank|CoinDesk|Cointelegraph|Decrypt|The Block|"
    r"Blockworks|Bitcoinist|NewsBTC|BeInCrypto|CryptoPotato|WatcherGuru|U\.Today)\b")


def validate_post(text: str) -> bool:
    """فحص نهائي صارم: عربي كافٍ، بلا أسئلة، بلا روابط، بلا بقايا ترجمة."""
    if not text or len(text) < 40:
        return False
    if CHANNEL_TAG and CHANNEL_TAG not in text:
        return False
    if _PLACEHOLDER_RE.search(text) or "§" in text:
        return False
    if "?" in text or "؟" in text:
        return False
    if "http" in text.lower():  # سياسة بلا روابط نهائيًا
        return False
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters > 0 and arabic_chars / total_letters < 0.25:
        return False
    if _SOURCE_LEAK_RE.search(text):
        return False
    return True


# ---------------------------------------------------------- بصمات منع التكرار
def normalize_title(title: str) -> str:
    t = re.sub(r"https?://\S+", " ", title.lower())
    t = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_STOPWORDS = {"the", "a", "an", "of", "in", "to", "for", "on", "after", "as", "is",
              "are", "from", "with", "and", "or", "its", "his", "her", "new", "big",
              "at", "by", "amid", "over", "into", "up", "down", "was", "were", "be",
              "this", "that", "it", "has", "have", "had", "will", "not", "no",
              "في", "من", "إلى", "على", "عن", "أن", "إن", "و", "أو"}


def title_tokens(norm: str) -> set[str]:
    return {w for w in norm.split() if len(w) > 1 and w not in _STOPWORDS}


def similar(a: str, b: str) -> bool:
    """تشابه بين عنوانين (Jaccard على الكلمات المهمة)."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= SIMILARITY_THRESHOLD
