"""
🐋 Whale News Bot v3 - كشف التكرار ودمج المصادر
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
مسؤول فقط عن:
1. فحص التكرار بناءً على حقائق الخبر (لا النص فقط)
2. دمج الأخبار من مصادر متعددة
"""

import time
from typing import List, Optional
from dataclasses import dataclass

from models import NewsItem, SourceQuality
from database import NewsDatabase, NewsRecord
from config import log, MERGE_SOURCE_GROUPS


# ═══════════════════════════════════════════════════════════
# 🔍 فحص التكرار
# ═══════════════════════════════════════════════════════════

def check_duplicate(item: NewsItem, db: NewsDatabase) -> bool:
    """
    فحص التكرار — 3 مستويات:
    1. hash النص (سريع)
    2. hash الحقائق (متوسط)
    3. تطابق الكيانات (عميق)
    """
    # المستوى 1: hash النص — فحص سريع
    if item.hash and db.is_duplicate(item.hash):
        log.debug(f"📊 Duplicate (text hash): {item.title[:60]}")
        return True

    # المستوى 2: hash الحقائق
    fact_hash = item.get_fact_hash()
    if fact_hash and fact_hash != item.hash:
        if db.is_duplicate(item.hash, fact_hash):
            log.debug(f"📊 Duplicate (fact hash): {item.title[:60]}")
            return True

    # المستوى 3: تطابق الكيانات (للأخبار بصياغات مختلفة)
    if item.facts and item.facts.main_entities:
        similar = db.find_similar(
            fact_hash=fact_hash,
            entities=item.facts.main_entities,
            coins=item.facts.coins
        )
        if similar:
            log.debug(
                f"📊 Duplicate (entities): {item.title[:60]} "
                f"≈ {similar.title[:60]}"
            )
            return True

    return False


def register_news(item: NewsItem, db: NewsDatabase):
    """تسجيل خبر في قاعدة البيانات بعد التأكد أنه ليس مكرراً"""
    record = NewsRecord(
        title=item.title,
        fact_hash=item.get_fact_hash(),
        text_hash=item.hash,
        entities=item.facts.main_entities if item.facts else [],
        coins=item.facts.coins if item.facts else [],
        news_type=item.news_type.value if item.news_type else "",
        source=item.source,
        timestamp=item.timestamp,
    )
    db.add(record)


# ═══════════════════════════════════════════════════════════
# 🔗 دمج المصادر
# ═══════════════════════════════════════════════════════════

# أوزان المصادر للدمج (أعلى = أفضل)
_SOURCE_WEIGHT = {
    SourceQuality.TIER_1: 3,
    SourceQuality.TIER_2: 2,
    SourceQuality.TIER_3: 1,
    SourceQuality.TIER_4: 0,
}


def merge_sources(items: List[NewsItem]) -> List[NewsItem]:
    """
    دمج الأخبار المتشابهة من مصادر متعددة.
    إذا وصل نفس الخبر من CoinDesk و Cointelegraph → خبر واحد مدمج.
    """
    if len(items) <= 1:
        return items

    now = time.time()
    merged_groups: List[List[NewsItem]] = []  # قائمة مجموعات
    used_indices: set = set()

    # تجميع الأخبار المتشابهة
    for i, item_a in enumerate(items):
        if i in used_indices:
            continue

        group = [item_a]
        used_indices.add(i)

        for j in range(i + 1, len(items)):
            if j in used_indices:
                continue

            item_b = items[j]

            # فحص: هل نفس الخبر؟
            if _is_same_event(item_a, item_b, now):
                group.append(item_b)
                used_indices.add(j)

        if len(group) > 1:
            merged_groups.append(group)

    # دمج كل مجموعة → خبر واحد
    result = []
    used_in_merge = set()

    for group in merged_groups:
        merged = _merge_group(group)
        result.append(merged)
        for g in group:
            used_in_merge.add(id(g))

    # إضافة الأخبار التي لم تُدمج
    for item in items:
        if id(item) not in used_in_merge:
            result.append(item)

    return result


def _is_same_event(a: NewsItem, b: NewsItem, now: float) -> bool:
    """هل الخبران يمثلان نفس الحدث؟"""
    # فحص الوقت: لا تدمج أخبار يفصل بينها أكثر من 6 ساعات
    if a.timestamp and b.timestamp:
        if abs(a.timestamp - b.timestamp) > 21600:
            return False

    # فحص hash الحقائق
    fact_a = a.get_fact_hash()
    fact_b = b.get_fact_hash()
    if fact_a and fact_b and fact_a == fact_b:
        return True

    # فحص الكيانات المشتركة
    if a.facts and b.facts:
        entities_a = set(a.facts.main_entities) if a.facts.main_entities else set()
        entities_b = set(b.facts.main_entities) if b.facts.main_entities else set()
        coins_a = set(a.facts.coins) if a.facts.coins else set()
        coins_b = set(b.facts.coins) if b.facts.coins else set()

        entity_overlap = len(entities_a & entities_b)
        coin_overlap = len(coins_a & coins_b)

        # شرط الدمج الموسع:
        # 1. كيانتان مشتركتان
        if entity_overlap >= 2:
            return True
        # 2. كيانة + عملة (مثل: Bitcoin + SEC)
        if entity_overlap >= 1 and coin_overlap >= 1:
            return True
        # 3. عملة واحدة مشتركة + نفس نوع الخبر → نفس الموضوع
        if coin_overlap >= 1 and a.news_type == b.news_type:
            return True
        # 4. عملتان مشتركتان → نفس الموضوع الكريبتوي
        if coin_overlap >= 2:
            return True

    # فحص التشابه النصي — آخر طبقة حماية
    text_a = _normalize_for_similarity(f"{a.clean_title or a.title} {a.clean_summary or a.summary}")
    text_b = _normalize_for_similarity(f"{b.clean_title or b.title} {b.clean_summary or b.summary}")
    if text_a and text_b and text_a == text_b:
        return True

    return False


def _merge_group(group: List[NewsItem]) -> NewsItem:
    """
    دمج مجموعة أخبار → خبر واحد.
    يُحافظ على الأفضل من كل مصدر.
    """
    # ترتيب حسب جودة المصدر (الأفضل أولاً)
    group.sort(key=lambda x: _SOURCE_WEIGHT.get(x.source_quality, 0), reverse=True)

    best = group[0]
    sources = [item.source for item in group]

    # استخدام أطول محتوى متاح
    if any(item.summary for item in group):
        best.summary = max(
            (item.summary for item in group if item.summary),
            key=len
        )

    # تعليم كمرجع مدمج
    best.is_merged = True
    best.merged_sources = sources

    # تعزيز الدرجة إذا جاء من 3+ مصادر
    if len(group) >= 3:
        best.score = getattr(best, 'score', 0) + 10
        log.info(f"🔗 Merged {len(group)} sources: {', '.join(sources)} → {best.title[:60]}")
    elif len(group) >= 2:
        log.info(f"🔗 Merged 2 sources: {', '.join(sources)} → {best.title[:60]}")

    return best


# ═══════════════════════════════════════════════════════════
# 📊 Semantic Deduplication (مكمل — للتشابه النصي)
# ═══════════════════════════════════════════════════════════

def _normalize_for_similarity(text: str) -> str:
    """تطبيع النص للمقارنة الدلالية"""
    import re
    text = text.lower()
    text = re.sub(r'\d+', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "to", "of", "in", "for", "on", "with", "at",
        "by", "from", "as", "into", "through", "during", "before",
        "after", "between", "under", "then", "once", "here", "there",
        "when", "where", "why", "how", "all", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only",
        "own", "same", "so", "than", "too", "very", "just", "and",
        "but", "if", "or", "because", "until", "while", "this", "that",
    }
    words = [w for w in text.split() if w not in stopwords and len(w) > 2]
    return " ".join(sorted(set(words)))
