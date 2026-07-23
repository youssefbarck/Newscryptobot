"""
🐋 Whale News Bot v3 - تصنيف الأخبار ونظام التقييم
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
مسؤول فقط عن:
1. تصنيف نوع الخبر (hack, ETF, regulation...)
2. تقييم أهمية الخبر بنظام نقاط (0-100)
3. قرار النشر أو الرفض
"""

import re
import time
from typing import Dict, List, Tuple

from models import NewsItem, NewsType, ScoreResult, SourceQuality
from config import TYPE_KEYWORDS, REJECTION_KEYWORDS, CRYPTO_CONTEXT_KEYWORDS, log


# ═══════════════════════════════════════════════════════════
# 🏷️ تصنيف الأخبار
# ═══════════════════════════════════════════════════════════

# compile أنماط الكلمات المفتاحية (مرة واحدة عند الاستيراد)
_TYPE_PATTERNS: Dict[str, List[re.Pattern]] = {}
for _type_name, _keywords in TYPE_KEYWORDS.items():
    _TYPE_PATTERNS[_type_name] = [
        re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
        for kw in _keywords
    ]

# خريطة من اسم النوع إلى NewsType enum
_TYPE_MAP = {
    "hack": NewsType.HACK,
    "etf": NewsType.ETF,
    "listing": NewsType.LISTING,
    "partnership": NewsType.PARTNERSHIP,
    "regulation": NewsType.REGULATION,
    "macro": NewsType.MACRO,
    "on_chain": NewsType.ON_CHAIN,
    "technical_analysis": NewsType.TECHNICAL_ANALYSIS,
    "funding": NewsType.FUNDING,
    "stablecoin": NewsType.STABLECOIN,
    "economic_data": NewsType.ECONOMIC_DATA,
    "adoption": NewsType.ADOPTION,
}

# أولوية الأنواع (أعلى = أكثر أهمية)
_TYPE_PRIORITY = {
    NewsType.HACK: 10,
    NewsType.ETF: 9,
    NewsType.REGULATION: 8,
    NewsType.ECONOMIC_DATA: 7,
    NewsType.LISTING: 6,
    NewsType.ON_CHAIN: 5,
    NewsType.FUNDING: 5,
    NewsType.STABLECOIN: 5,
    NewsType.PARTNERSHIP: 4,
    NewsType.ADOPTION: 4,
    NewsType.MACRO: 3,
    NewsType.TECHNICAL_ANALYSIS: 2,
    NewsType.GENERAL: 1,
}


def classify_news(item: NewsItem) -> NewsType:
    """
    تصنيف نوع الخبر بناءً على الكلمات المفتاحية.
    يعيد النوع ذو أعلى تطابق.
    """
    text = f"{item.clean_title or item.title} {item.clean_summary or item.summary}"
    text_lower = text.lower()

    scores: Dict[str, int] = {}

    for type_name, patterns in _TYPE_PATTERNS.items():
        match_count = 0
        for pattern in patterns:
            matches = pattern.findall(text_lower)
            match_count += len(matches)
        if match_count > 0:
            scores[type_name] = match_count

    if not scores:
        return NewsType.GENERAL

    # أفضل نوع = أعلى عدد تطابقات
    best_type_name = max(scores, key=scores.get)

    # إذا كان هناك تعادل → استخدم الأولوية
    max_score = scores[best_type_name]
    tied = [t for t, s in scores.items() if s == max_score]
    if len(tied) > 1:
        best_type_name = max(tied, key=lambda t: _TYPE_PRIORITY.get(_TYPE_MAP.get(t), 0))

    return _TYPE_MAP.get(best_type_name, NewsType.GENERAL)


# ═══════════════════════════════════════════════════════════
# 📊 نظام التقييم (0-100)
# ═══════════════════════════════════════════════════════════

# أوزان جودة المصدر
_SOURCE_SCORES = {
    SourceQuality.TIER_1: 30,
    SourceQuality.TIER_2: 20,
    SourceQuality.TIER_3: 10,
    SourceQuality.TIER_4: 5,
}

# أوزان الاستعجالية حسب نوع الخبر
_URGENCY_SCORES = {
    NewsType.HACK: 20,
    NewsType.ETF: 15,
    NewsType.REGULATION: 15,
    NewsType.LISTING: 12,
    NewsType.ECONOMIC_DATA: 15,
    NewsType.STABLECOIN: 10,
    NewsType.ON_CHAIN: 10,
    NewsType.FUNDING: 10,
    NewsType.PARTNERSHIP: 8,
    NewsType.ADOPTION: 8,
    NewsType.MACRO: 12,
    NewsType.GENERAL: 5,
    NewsType.TECHNICAL_ANALYSIS: 3,
}

# كيانات رئيسية وأوزانها
_MAJOR_ENTITIES = {
    "blackrock": 15, "sec": 15, "federal reserve": 15, "jerome powell": 15,
    "binance": 12, "coinbase": 12, "grayscale": 12,
    "microstrategy": 12, "fidelity": 12, "gary gensler": 12,
    "tether": 10, "circle": 10,
    "van eck": 10, "franklin templeton": 10,
    "ark invest": 8, "bitwise": 8,
}
_MEDIUM_ENTITIES = {
    "solana": 8, "ethereum": 8, "bitcoin": 8,
    "uniswap": 6, "aave": 6,
}

# كلمات التحليل/الرأي (خصم)
_OPINION_WORDS = [
    "analysis", "opinion", "could", "might", "may", "potentially",
    "experts believe", "analysts say", "expected to", "likely to",
    "some analysts", "according to experts", "in our view",
    "تحليل", "توقعات", "متوقع", "قد يصل", "قد يكون",
]

# كلمات الإشاعة (خصم أكبر)
_RUMOR_WORDS = [
    "rumor", "unconfirmed", "reportedly", "allegedly", "sources say",
    "whispers", "speculation", "hoax",
    "شائعة", "غير مؤكد", "بحسب مصادر", "المفترض",
]


def score_news(item: NewsItem) -> ScoreResult:
    """
    تقييم أهمية الخبر بنظام نقاط (0-100).
    كل بُعد مستقل وقابل للتتبع.
    """
    result = ScoreResult()

    # ── 1. جودة المصدر (0-30) ──
    result.source_score = _SOURCE_SCORES.get(item.source_quality, 5)

    # ── 2. الاستعجالية (0-20) ──
    result.urgency_score = _URGENCY_SCORES.get(item.news_type, 5)

    # ── 3. بيانات مالية (0-20) ──
    if item.facts:
        has_dollar = any(f.value_usd > 0 for f in item.facts.facts)
        has_coins = any(f.amount > 0 for f in item.facts.facts)
        has_numbers = item.facts.has_financial_data

        if has_dollar and has_coins:
            result.financial_score = 20
        elif has_dollar or has_numbers:
            result.financial_score = 15
        elif has_coins:
            result.financial_score = 10
        else:
            result.financial_score = 0

    # ── 4. أهمية الكيانات (0-15) ──
    result.entity_score = _score_entities(item)

    # ── 5. عمر الخبر (0-10) ──
    if item.timestamp > 0:
        age_hours = (time.time() - item.timestamp) / 3600
        if age_hours < 1:
            result.age_score = 10
        elif age_hours < 3:
            result.age_score = 7
        elif age_hours < 6:
            result.age_score = 4
        elif age_hours < 12:
            result.age_score = 2
        else:
            result.age_score = 0

    # ── 6. مكافأة نوع الخبر (0-10) ──
    result.type_score = min(result.urgency_score / 2, 10)

    # ── خصومات ──
    text = f"{item.clean_title or item.title} {item.clean_summary or item.summary}".lower()

    # تحليل/رأي
    if any(w in text for w in _OPINION_WORDS):
        result.penalty -= 15

    # إشاعة
    if any(w in text for w in _RUMOR_WORDS):
        result.penalty -= 25

    # خبر قديم بدون كيان مهم
    if result.age_score <= 2 and result.entity_score < 8:
        result.penalty -= 10

    # بدون صورة
    if not item.image:
        result.penalty -= 5

    # محتوى قصير جداً
    content_len = len(item.clean_summary or item.summary or "")
    if content_len < 200:
        result.penalty -= 10

    # مكافأة الـ merged (من عدة مصادر)
    if item.is_merged and len(item.merged_sources) >= 3:
        result.bonus += 10

    # حساب المجموع
    result.total = (
        result.source_score + result.urgency_score + result.financial_score
        + result.entity_score + result.age_score + result.type_score
        + result.bonus + result.penalty
    )

    # لا يمكن أن يكون المجموع سالباً
    result.total = max(0, result.total)

    # قرار النشر
    result.should_publish = result.total >= 35.0
    result.reason = _explain_score(result)

    result.breakdown = {
        "مصدر": result.source_score,
        "استعجالية": result.urgency_score,
        "مالي": result.financial_score,
        "كيانات": result.entity_score,
        "عمر": result.age_score,
        "نوع": result.type_score,
        "مكافأة": result.bonus,
        "خصم": result.penalty,
        "المجموع": result.total,
    }

    return result


def _score_entities(item: NewsItem) -> float:
    """تقييم أهمية الكيانات المذكورة"""
    score = 0.0
    if not item.facts or not item.facts.main_entities:
        return score

    for entity in item.facts.main_entities:
        entity_lower = entity.lower()
        if entity_lower in _MAJOR_ENTITIES:
            score = max(score, _MAJOR_ENTITIES[entity_lower])
        elif entity_lower in _MEDIUM_ENTITIES:
            score = max(score, _MEDIUM_ENTITIES[entity_lower])
        else:
            score = max(score, 3)  # كيانات عادية

    # مكافأة إذا كان هناك عدة كيانات
    entity_count = len(item.facts.main_entities)
    if entity_count >= 3:
        score += 5
    elif entity_count >= 2:
        score += 3

    return min(score, 15)


def _explain_score(result: ScoreResult) -> str:
    """شرح مختصر لنتيجة التقييم"""
    parts = []
    if result.source_score >= 25:
        parts.append("مصدر موثوق")
    if result.urgency_score >= 15:
        parts.append("عاجل")
    if result.financial_score >= 15:
        parts.append("بيانات مالية مهمة")
    if result.entity_score >= 12:
        parts.append("كيانات كبيرة")
    if result.penalty < -10:
        parts.append("تحليل/إشاعة")

    if result.total >= 70:
        return f"أولوية عالية: {', '.join(parts) if parts else 'درجة عالية'}"
    elif result.total >= 35:
        return f"يستحق النشر: {', '.join(parts) if parts else 'درجة مقبولة'}"
    else:
        if result.penalty < -10:
            return f"مرفوض: {'، '.join(parts)}"
        return f"درجة منخفضة ({result.total}/100)"


# ═══════════════════════════════════════════════════════════
# 🚫 فلاتر الرفض
# ═══════════════════════════════════════════════════════════

def should_reject(item: NewsItem) -> Tuple[bool, str]:
    """
    فحص ما إذا كان يجب رفض الخبر قبل التقييم.
    يعيد (True, reason) إذا كان يجب الرفض.
    """
    text = f"{item.clean_title or item.title} {item.clean_summary or item.summary}"
    text_lower = text.lower()

    # 1. فحص الحد الأدنى للطول
    if not item.title or len(item.title.strip()) < 20:
        return True, "عنوان قصير جداً (< 20 حرف)"

    if not item.summary or len(item.summary.strip()) < 30:
        return True, "محتوى قصير جداً (< 30 حرف)"

    # 2. فحص السياق الكريبتوي
    has_context = any(kw in text_lower for kw in CRYPTO_CONTEXT_KEYWORDS)
    # استثناء: الأخبار الاقتصادية الكلية لا تحتاج سياق كريبتو مباشر
    is_macro = item.category in ("fed", "macro")
    if not has_context and not is_macro:
        return True, "لا سياق كريبتوي"

    # 3. كلمات الرفض
    for kw in REJECTION_KEYWORDS:
        if kw.lower() in text_lower:
            return True, f"كلمة رفض: {kw}"

    # 4. رفض Reddit
    if "reddit" in item.source.lower():
        return True, "مصدر Reddit"

    # 5. محتوى ترويجي
    promo_patterns = [
        r'(buy\s+now|click\s+here|sign\s+up|register\s+now)',
        r'(سجل\s+الآن|اشتري\s+الآن|اضغط\s+هنا)',
    ]
    for pattern in promo_patterns:
        if re.search(pattern, text_lower):
            return True, "محتوى ترويجي"

    # 6. عناوين مضللة (عنوان مختلف تماماً عن المحتوى)
    if item.title and item.summary:
        title_words = set(re.findall(r'\b\w+\b', item.title.lower()))
        summary_words = set(re.findall(r'\b\w+\b', item.summary.lower()))
        if title_words and summary_words:
            overlap = len(title_words & summary_words) / len(title_words)
            if overlap < 0.1 and len(title_words) > 3:
                return True, "عنوان مضلل"

    return False, ""
