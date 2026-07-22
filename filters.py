"""
🎯 Whale News Bot v2.0 - الفلاتر المتقدمة
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
فلترة ذكية مع semantic similarity، scoring، و deduplication متقدم
"""

import re, time, hashlib
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from difflib import SequenceMatcher

from config import (
    log, KEYWORDS_CONFIG, CRYPTO_CONTEXT_KEYWORDS, REJECTION_KEYWORDS,
    AR_CRITICAL_KEYWORDS, AR_REJECTION_KEYWORDS, COIN_MAP,
)


# ═══════════════════════════════════════════════════════════
# 📰 نموذج الخبر المحسّن
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    """نموذج الخبر مع metadata كاملة"""
    title: str
    link: str
    summary: str = ""
    image: str = ""
    source: str = ""
    category: str = ""
    timestamp: float = 0.0
    date_str: str = ""
    # حقول الترجمة
    title_ar: str = ""
    summary_ar: str = ""
    news_format: str = "standard"   # standard | bullets | economic
    importance: str = "medium"       # low | medium | high | breaking
    # حقول الفلترة
    categories: List[str] = None
    coins: List[str] = None
    score: float = 0.0
    hash: str = ""
    lang: str = "en"

    def __post_init__(self):
        if self.categories is None:
            self.categories = []
        if self.coins is None:
            self.coins = []
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """hash متقدم يعتمد على العنوان + المصدر"""
        title_norm = re.sub(r'[^\w\s]', '', self.title.lower())
        title_norm = re.sub(r'\s+', ' ', title_norm).strip()
        title_norm = re.sub(r'^(breaking|update|news|alert|urgent|just in|report)[\s:]*', '', title_norm)
        hash_input = title_norm[:60]
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict:
        return {
            "title": self.title, "link": self.link, "summary": self.summary,
            "image": self.image, "source": self.source, "category": self.category,
            "timestamp": self.timestamp, "date_str": self.date_str,
            "title_ar": self.title_ar, "summary_ar": self.summary_ar,
            "news_format": self.news_format, "importance": self.importance,
            "categories": self.categories, "coins": self.coins,
            "score": self.score, "hash": self.hash, "lang": self.lang,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "NewsItem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════
# 🔍 Semantic Deduplication
# ═══════════════════════════════════════════════════════════
class SemanticDeduplicator:
    """إزالة التكرار باستخدام semantic similarity"""

    def __init__(self, threshold: float = 0.82):
        self.threshold = threshold
        self._seen: Dict[str, Tuple[str, float]] = {}  # hash → (normalized_text, timestamp)

    def _normalize(self, text: str) -> str:
        """تطبيع النص للمقارنة"""
        text = text.lower()
        # إزالة الأرقام (تختلف بين المصادر)
        text = re.sub(r'\d+', ' ', text)
        # إزالة الرموز
        text = re.sub(r'[^\w\s]', ' ', text)
        # إزالة الكلمات الشائعة
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                     "being", "have", "has", "had", "do", "does", "did", "will",
                     "would", "could", "should", "may", "might", "must", "shall",
                     "can", "need", "dare", "ought", "used", "to", "of", "in",
                     "for", "on", "with", "at", "by", "from", "as", "into",
                     "through", "during", "before", "after", "above", "below",
                     "between", "under", "again", "further", "then", "once",
                     "here", "there", "when", "where", "why", "how", "all",
                     "each", "few", "more", "most", "other", "some", "such",
                     "no", "nor", "not", "only", "own", "same", "so", "than",
                     "too", "very", "just", "and", "but", "if", "or", "because",
                     "until", "while", "this", "that", "these", "those"}
        words = [w for w in text.split() if w not in stopwords and len(w) > 2]
        return " ".join(sorted(set(words)))

    def _similarity(self, text1: str, text2: str) -> float:
        """حساب التشابه بين نصين"""
        return SequenceMatcher(None, text1, text2).ratio()

    def is_duplicate(self, item: NewsItem) -> bool:
        """التحقق من التكرار"""
        normalized = self._normalize(item.title)
        if not normalized:
            return False

        # فحص سريع: hash مطابق
        if item.hash in self._seen:
            return True

        # فحص semantic: مقارنة مع آخر 100 خبر
        now = time.time()
        # تنظيف القديم (> 24 ساعة)
        old_hashes = [h for h, (_, ts) in self._seen.items() if now - ts > 86400]
        for h in old_hashes:
            del self._seen[h]

        # مقارنة مع كل الخبر السابق
        for existing_hash, (existing_text, _) in self._seen.items():
            sim = self._similarity(normalized, existing_text)
            if sim >= self.threshold:
                log.debug(f"Duplicate detected: sim={sim:.2f} | {item.title[:50]}...")
                return True

        self._seen[item.hash] = (normalized, now)
        return False

    def add(self, item: NewsItem):
        """إضافة خبر للذاكرة"""
        normalized = self._normalize(item.title)
        self._seen[item.hash] = (normalized, time.time())


# ═══════════════════════════════════════════════════════════
# 🎯 Scoring Engine
# ═══════════════════════════════════════════════════════════
class NewsScorer:
    """محرك تقييم أهمية الخبر"""

    def __init__(self):
        self._keyword_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[str, List[Tuple[re.Pattern, int]]]:
        """تجميع أنماط الكلمات المفتاحية"""
        patterns = {}
        for category, config in KEYWORDS_CONFIG.items():
            patterns[category] = []
            for word in config["words"]:
                pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
                patterns[category].append((pattern, config["weight"]))
        return patterns

    def score(self, item: NewsItem) -> Tuple[float, List[str]]:
        """
        تقييم الخبر وإرجاع (الدرجة, الفئات)
        الدرجة: 0-10
        """
        text = f"{item.title} {item.summary}".lower()
        score = 0.0
        categories = []

        for category, patterns in self._keyword_patterns.items():
            cat_score = 0
            for pattern, weight in patterns:
                matches = len(pattern.findall(text))
                if matches > 0:
                    cat_score += matches * weight

            if cat_score > 0:
                categories.append(category)
                score += cat_score

        # مكافأة للأخبار العاجلة
        if "breaking" in categories or "hack" in categories:
            score *= 1.5

        # مكافأة للمصادر الموثوقة
        trusted_sources = {"CoinDesk", "Cointelegraph", "Federal Reserve", "Blockworks"}
        if item.source in trusted_sources:
            score *= 1.2

        # خصم للأخبار القديمة
        if item.timestamp > 0:
            age_hours = (time.time() - item.timestamp) / 3600
            if age_hours > 1:
                score *= max(0.5, 1 - (age_hours / 24))

        return min(score, 10.0), categories

    def extract_coins(self, text: str) -> List[str]:
        """استخراج العملات بدقة"""
        text_lower = text.lower()
        found = set()
        # ترتيب: الأطول أولاً
        for keyword, symbol in sorted(COIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            if pattern.search(text_lower):
                found.add(symbol)
        return sorted(found)


# ═══════════════════════════════════════════════════════════
# 🔧 فلاتر إضافية
# ═══════════════════════════════════════════════════════════
def is_complete_news(text: str) -> bool:
    """فحص اكتمال النص"""
    if not text or len(text.strip()) < 15:
        return False

    trimmed = text.strip()

    incomplete_endings = [
        "على", "في", "من", "إلى", "عن", "مع", "حتى", "خلال",
        "بعد", "قبل", "بين", "ضد", "عبر", "نحو", "لدى", "بسبب",
        "وذلك على", "وذلك في", "وذلك من",
        "✉️", "...", "،",
    ]

    for ending in incomplete_endings:
        if trimmed.endswith(ending):
            return False

    if len(trimmed) < 250:
        return True

    if len(trimmed) >= 250 and not re.search(r'[.!؟!\u06d4]$', trimmed):
        return False

    return True


def has_crypto_context(text: str) -> bool:
    """التحقق من السياق الكريبتوي"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in CRYPTO_CONTEXT_KEYWORDS)


def has_rejection_keywords(text: str) -> bool:
    """التحقق من كلمات الرفض"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in REJECTION_KEYWORDS)


def time_ago(timestamp: float) -> str:
    """تحويل timestamp إلى نص"""
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


# ═══════════════════════════════════════════════════════════
# 🏭 Factory
# ═══════════════════════════════════════════════════════════
_deduplicator = SemanticDeduplicator()
_scorer = NewsScorer()


def process_news_item(item: NewsItem) -> Optional[NewsItem]:
    """
    معالجة خبر واحد: فلترة + تقييم + استخراج العملات
    يعيد None إذا لم يمر بالفلترة
    """
    text = f"{item.title} {item.summary}".lower()

    # (1) فحص التكرار
    if _deduplicator.is_duplicate(item):
        log.debug(f"Duplicate skipped: {item.title[:60]}...")
        return None

    # (2) فحص السياق الكريبتوي
    if not has_crypto_context(text):
        return None

    # (3) فحص كلمات الرفض
    if has_rejection_keywords(text):
        return None

    # (4) رفض Reddit
    if "reddit" in item.source.lower():
        return None

    # (5) تقييم + استخراج الفئات
    score, categories = _scorer.score(item)
    item.score = score
    item.categories = categories

    # (6) استخراج العملات
    item.coins = _scorer.extract_coins(text)

    # (7) التسجيل في deduplicator
    _deduplicator.add(item)

    return item


def filter_news_items(items: List[NewsItem], min_score: float = 1.5) -> List[NewsItem]:
    """فلترة قائمة أخبار"""
    processed = []
    for item in items:
        result = process_news_item(item)
        if result and result.score >= min_score:
            processed.append(result)

    # ترتيب حسب الدرجة (الأعلى أولاً) ثم الوقت
    processed.sort(key=lambda x: (-x.score, -x.timestamp))
    return processed
