# -*- coding: utf-8 -*-
"""التحليل: تصنيف الخبر، استخراج الأرقام، حساب الأهمية، بصمات منع التكرار"""
import hashlib
import re
from datetime import datetime, timezone

from .categories import (
    CATEGORY_ORDER,
    CATEGORIES,
    COIN_AR,
    COIN_TICKERS_RE,
    MAJOR_COIN_NAMES_RE,
)
from .config import SIMILARITY_THRESHOLD

# كلمات تضيف «حماس» للخبر
_BUZZ_RE = re.compile(
    r"\b(breaking|urgent|just\s+in|alert|massive|huge|record|historic|shock\w*|"
    r"sensational|unprecedented|surprise|dramatic|stunning|bombshell)\b", re.I)
_PCT_RE = re.compile(r"\b\d{1,2}(?:\.\d+)?\s?%\b")
_USD_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(trillion|billion|million|thousand|bn|b|m|k|t)?\b", re.I)
_COIN_AMOUNT_RE = re.compile(
    r"\b([\d,]{2,}(?:\.\d+)?)\s*(BTC|ETH|SOL|XRP|DOGE|ADA|BNB|TRX|DOT|LINK|AVAX|LTC|"
    r"SHIB|PEPE|XLM|ATOM|NEAR|ARB|OP|MATIC|POL|USDT|USDC|TON|SUI|APT|UNI|AAVE|XMR)\b", re.I)
_MULT = {"trillion": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
         "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_STOPWORDS = {"the", "a", "an", "of", "in", "to", "for", "on", "after", "as", "is",
              "are", "from", "with", "and", "or", "its", "his", "her", "new", "big",
              "at", "by", "amid", "over", "into", "up", "down", "was", "were", "be",
              "this", "that", "it", "has", "have", "had", "will", "not", "no"}


def human_usd(value: float) -> str:
    """780000000 → «780 مليون دولار»"""
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


# ------------------------------------------------------------- بصمات الخبر
def normalize_title(title: str) -> str:
    t = re.sub(r"https?://\S+", " ", title.lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_tokens(norm: str) -> set[str]:
    return {w for w in norm.split() if len(w) > 1 and w not in _STOPWORDS}


def similar(a: str, b: str) -> bool:
    """تشابه بين عنوانين (Jaccard على الكلمات المهمة)."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= SIMILARITY_THRESHOLD


def item_hashes(item: dict) -> list[str]:
    """بصمتان: من العنوان المُطبّع ومن رابط الخبر."""
    hashes = [hashlib.md5(item["norm"].encode("utf-8")).hexdigest()[:16]]
    url = item.get("url") or ""
    if url:
        path = re.sub(r"[?#].*$", "", url)
        hashes.append("u" + hashlib.md5(path.encode("utf-8")).hexdigest()[:15])
    return hashes


# --------------------------------------------------------------- التصنيف
# التصنيفات الحساسة (اختراق/حيتان) تُفحص في العنوان فقط،
# أما القوانين/التقنية/الأسعار فيمكن الاعتماد على نص الخبر أيضًا
_TITLE_ONLY_CATEGORIES = {"hack", "whale"}


def categorize(item: dict) -> str | None:
    title = item["title"]
    summary = (item.get("summary") or "")[:300]
    for key in CATEGORY_ORDER:
        if CATEGORIES[key]["keywords"].search(title):
            return key
    for key in CATEGORY_ORDER:
        if key in _TITLE_ONLY_CATEGORIES:
            continue
        if summary and CATEGORIES[key]["keywords"].search(summary):
            return key
    return None


# ------------------------------------------------------------- استخراج الأرقام
def extract_facts(title: str) -> list[str]:
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


# -------------------------------------------------------------- حساب الأهمية
def _max_usd(title: str) -> float:
    best = 0.0
    for m in _USD_RE.finditer(title):
        raw = m.group(1).replace(",", "")
        mult = _MULT.get((m.group(2) or "").lower(), 1)
        best = max(best, float(raw) * mult)
    return best


def score(item: dict, category: str) -> int:
    """درجة أهمية من 1 إلى 10 — فلتر الجودة يعتمد عليها."""
    title = item["title"]
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

    # نسبة مئوية حادة في العنوان (+1)
    if _PCT_RE.search(title):
        s += 1

    # نقاط التصنيف نفسه
    s += CATEGORIES[category]["score_bonus"]

    # طزاجة الخبر
    pub = item.get("published")
    if pub is None:
        s += 1
    else:
        age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        if age_hours <= 3:
            s += 2
        elif age_hours <= 8:
            s += 1

    # كلمات حماس
    if _BUZZ_RE.search(title):
        s += 1

    return max(1, min(10, s))


# --------------------------------------------------- التجهيز الشامل للخبر
def prepare(item: dict) -> dict | None:
    """يضيف norm/hashes/category/score/facts — يُرجع None إن كان فاسدًا."""
    title = (item.get("title") or "").strip()
    if not title:
        return None
    item["norm"] = normalize_title(title)
    if not item["norm"]:
        return None
    item["hashes"] = item_hashes(item)

    if item.get("whale_data"):
        # أخبار Whale Alert جاهزة التصنيف — أهمية عالية مضمونة
        item["category"] = "whale"
        item["score"] = 9
        wd = item["whale_data"]
        item["facts"] = [
            f"🪙 الكمية: {wd['amount']:,.0f} {COIN_AR.get(wd['symbol'], wd['symbol'])}",
            f"💰 القيمة: ≈ {human_usd(wd['amount_usd'])}",
            f"🔄 المسار: من {wd['from_txt']} إلى {wd['to_txt']}",
        ]
    else:
        cat = categorize(item)
        if not cat:
            return None  # خبر خارج اهتماماتنا — يُهمل
        item["category"] = cat
        item["score"] = score(item, cat)
        item["facts"] = extract_facts(title)
    return item
