"""
🎯 Whale News Bot — فلاتر مبسّطة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
فلترة أساسية: إزالة التكرار + فحص السياق الكريبتوي + استخراج العملات.
بدون تقييم، بدون تعقيد.
"""

import re, time, hashlib
from typing import List, Dict, Set, Optional
from dataclasses import dataclass

from config import log, CRYPTO_CONTEXT_KEYWORDS, REJECTION_KEYWORDS, COIN_MAP


# ═══════════════════════════════════════════════════════════
# 📰 نموذج الخبر
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    title: str
    link: str
    summary: str = ""
    image: str = ""
    source: str = ""
    category: str = ""
    timestamp: float = 0.0
    date_str: str = ""
    title_ar: str = ""
    summary_ar: str = ""
    coins: List[str] = None
    hash: str = ""
    lang: str = "en"

    def __post_init__(self):
        if self.coins is None:
            self.coins = []
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        title_norm = re.sub(r'[^\w\s]', '', self.title.lower())
        title_norm = re.sub(r'\s+', ' ', title_norm).strip()
        title_norm = re.sub(r'^(breaking|update|news|alert|urgent|just in|report)[\s:]*', '', title_norm)
        return hashlib.md5(title_norm[:100].encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════
# 🔍 إزالة التكرار
# ═══════════════════════════════════════════════════════════
class SimpleDeduplicator:
    """إزالة التكرار بالهاش + تشابه بسيط"""

    def __init__(self):
        self._seen: Set[str] = set()
        self._texts: Dict[str, str] = {}  # hash → normalized text
        self._timestamps: Dict[str, float] = {}

    def is_duplicate(self, item: NewsItem) -> bool:
        # فحص سريع بالهاش
        if item.hash in self._seen:
            return True

        # تنظيف القديم (> 24 ساعة)
        now = time.time()
        old = [h for h, ts in self._timestamps.items() if now - ts > 86400]
        for h in old:
            self._seen.discard(h)
            self._texts.pop(h, None)
            del self._timestamps[h]

        self._seen.add(item.hash)
        self._texts[item.hash] = item.title.lower()
        self._timestamps[item.hash] = now
        return False


# ═══════════════════════════════════════════════════════════
# 🪙 استخراج العملات
# ═══════════════════════════════════════════════════════════
_AMBIGUOUS = {
    "near", "op", "sol", "dot", "link", "apt", "sei", "ton",
    "mat", "avax", "arb", "run", "sui", "sea", "top", "fit",
    "meta", "atom", "one", "all", "sun", "moon", "star", "es",
}

def extract_coins(text: str, original: str = "") -> List[str]:
    """استخراج العملات المذكورة في النص"""
    original = original or text
    text_lower = text.lower()
    found = set()

    for keyword, symbol in sorted(COIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
        if pattern.search(text_lower):
            kw_lower = keyword.lower()
            if kw_lower in _AMBIGUOUS:
                has_context = (
                    re.search(rf'\b{re.escape(kw_lower.upper())}\b', original)
                    or f'${kw_lower.upper()}' in original
                    or f'#{kw_lower.upper()}' in original
                    or f'{kw_lower} protocol' in text_lower
                    or f'{kw_lower} token' in text_lower
                    or f'{kw_lower} blockchain' in text_lower
                    or f'{kw_lower} network' in text_lower
                )
                if not has_context:
                    continue
            found.add(symbol)
    return sorted(found)


# ═══════════════════════════════════════════════════════════
# 🔧 فلاتر أساسية
# ═══════════════════════════════════════════════════════════
def has_crypto_context(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in CRYPTO_CONTEXT_KEYWORDS)

def has_rejection_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in REJECTION_KEYWORDS)


# ═══════════════════════════════════════════════════════════
# 🏭 فلترة مبسّطة
# ═══════════════════════════════════════════════════════════
_deduplicator = SimpleDeduplicator()


def filter_news_items(items: List[NewsItem]) -> List[NewsItem]:
    """فلترة قائمة أخبار — إزالة التكرار + فحص السياق + استخراج العملات"""
    result = []
    for item in items:
        text = f"{item.title} {item.summary}".lower()
        text_original = f"{item.title} {item.summary}"

        # (1) إزالة التكرار
        if _deduplicator.is_duplicate(item):
            continue

        # (2) فحص السياق الكريبتوي
        if not has_crypto_context(text):
            continue

        # (3) فحص كلمات الرفض
        if has_rejection_keywords(text):
            continue

        # (4) رفض Reddit
        if "reddit" in item.source.lower():
            continue

        # (5) استخراج العملات
        item.coins = extract_coins(text, original=text_original)

        result.append(item)

    # ترتيب حسب الوقت (الأحدث أولاً)
    result.sort(key=lambda x: -x.timestamp)
    return result
