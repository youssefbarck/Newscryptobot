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

from models import NewsItem, SourceQuality, NewsType
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
        # 3b. كيانة واحدة مشتركة + نفس نوع الخبر الهام (regulation, hack, etf)
        _IMPORTANT_TYPES = {NewsType.REGULATION, NewsType.HACK, NewsType.ETF,
                           NewsType.ECONOMIC_DATA, NewsType.FUNDING, NewsType.STABLECOIN}
        if entity_overlap >= 1 and a.news_type == b.news_type and a.news_type in _IMPORTANT_TYPES:
            return True
        # 4. عملتان مشتركتان → نفس الموضوع الكريبتوي
        if coin_overlap >= 2:
            return True

    # فحص التشابه النصي — احتواء الكلمات فقط
    # (الكيانات فُحصت بالفعل أعلاه — هنا نلتقط فقط ما فات)
    text_a = f"{a.clean_title or a.title} {a.clean_summary or a.summary}"
    text_b = f"{b.clean_title or b.title} {b.clean_summary or b.summary}"
    if text_a.strip() and text_b.strip():
        norm_a = _normalize_for_similarity(text_a)
        norm_b = _normalize_for_similarity(text_b)
        words_a = set(norm_a.split()) if norm_a else set()
        words_b = set(norm_b.split()) if norm_b else set()
        if words_a and words_b:
            intersection = len(words_a & words_b)
            smaller = min(len(words_a), len(words_b))
            containment = intersection / smaller if smaller > 0 else 0.0
            if containment >= 0.50:
                log.debug(
                    f"📊 Same event (word containment {containment:.0%}): "
                    f"{a.title[:40]} ≈ {b.title[:40]}"
                )
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

# كلمات وقف عربية للتطبيع
_ARABIC_STOPWORDS = {
    "في", "من", "إلى", "على", "عن", "مع", "هذا", "هذه", "ذلك", "تلك",
    "التي", "الذي", "هو", "هي", "هم", "هن", "نحن", "كان", "كانت",
    "يكون", "تكون", "قد", "لقد", "سوف", "منذ", "حتى", "خلال",
    "بعد", "قبل", "عند", "بين", "أو", "و", "ثم", "تم", "تمت", "يتم",
    "أي", "كل", "بعض", "كما", "لذلك", "أكثر", "أقل", "جدا", "لا",
    "لم", "لن", "إن", "أن", "ما", "ب", "ل", "ع", "ف", "ذات",
    "لها", "له", "لهم", "منها", "منه", "عليه", "عليها", "فيه", "فيها",
    "به", "بها", "مما", "مثل", "حيث", "حول", "ضد", "عبر", "وفق",
    "نحو", "لكن", "سوف", "الى", "علي", "انه", "انها", "عليه",
    "اي", "والتي", "والذي", "التى", "تم",
}

_EN_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "into", "through", "during", "before",
    "after", "between", "under", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "and",
    "but", "if", "or", "because", "until", "while", "this", "that",
})
_ALL_STOPWORDS = _EN_STOPWORDS | _ARABIC_STOPWORDS

# تطبيع أسماء العملات والشركات (كل الصيغ: Bitcoin/btc/BTC → btc)
_ENTITY_NORMALIZE = {
    "bitcoin": "btc", "btc": "btc",
    "ethereum": "eth", "eth": "eth",
    "solana": "sol", "sol": "sol",
    "ripple": "xrp", "xrp": "xrp",
    "cardano": "ada", "ada": "ada",
    "dogecoin": "doge", "doge": "doge",
    "avalanche": "avax", "avax": "avax",
    "polkadot": "dot", "dot": "dot",
    "chainlink": "link", "link": "link",
    "polygon": "pol", "pol": "pol",
    "litecoin": "ltc", "ltc": "ltc",
    "tron": "trx", "trx": "trx",
    "uniswap": "uni", "uni": "uni",
    "binance": "binance", "coinbase": "coinbase",
    "blackrock": "blackrock", "sec": "sec",
    "grayscale": "grayscale", "fidelity": "fidelity",
    "microstrategy": "microstrategy", "tether": "usdt",
    "usdt": "usdt", "usdc": "usdc",
    "cz": "cz", "van eck": "vaneck",
}


def _normalize_for_similarity(text: str) -> str:
    """تطبيع النص — تطبيع الكيانات + إزالة stopwords + إزالة الأرقام والرموز"""
    import re
    text = text.lower().strip()
    # تطبيع أسماء الكيانات المعروفة
    for name, normalized in _ENTITY_NORMALIZE.items():
        text = re.sub(r'\b' + re.escape(name) + r'\b', normalized, text)
    # إزالة الأرقام والرموز — نبقي الكلمات المعنوية فقط
    text = re.sub(r'\d+[,\.]?\d*', ' ', text)
    text = re.sub(r'[$€£¥%#,.]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = [w for w in text.split() if w not in _ALL_STOPWORDS and len(w) > 1]
    return " ".join(sorted(set(words)))


def _extract_char_ngrams(text: str, n: int = 3) -> set:
    """استخراج character n-grams من نص — يربط بين الكلمات بمحدد"""
    import re
    text = text.lower().strip()
    # استبدال المسافات بـ _ لربط حدود الكلمات
    text = re.sub(r'\s+', '_', text)
    if len(text) < n:
        return set()
    return set(text[i:i+n] for i in range(len(text) - n + 1))


def _text_similarity_multi(text_a: str, text_b: str) -> float:
    """
    تشابه نصي متعدد الإشارات — يجمع 3 مقاييس:
    1. احتواء الكلمات (40%) — كلمات معنوية مشتركة
    2. character n-gram (40%) — تشابه في البنية
    3. تطابق الكيانات المطبعّة (20%) — أسماء معروفة
    """
    if not text_a or not text_b:
        return 0.0

    # إشارة 1: احتواء الكلمات المعنوية
    norm_a = _normalize_for_similarity(text_a)
    norm_b = _normalize_for_similarity(text_b)
    words_a = set(norm_a.split()) if norm_a else set()
    words_b = set(norm_b.split()) if norm_b else set()
    word_score = 0.0
    if words_a and words_b:
        intersection = len(words_a & words_b)
        smaller = min(len(words_a), len(words_b))
        word_score = intersection / smaller if smaller > 0 else 0.0

    # إشارة 2: character 3-gram containment
    ngrams_a = _extract_char_ngrams(text_a, n=3)
    ngrams_b = _extract_char_ngrams(text_b, n=3)
    char_score = 0.0
    if ngrams_a and ngrams_b:
        intersection = len(ngrams_a & ngrams_b)
        smaller = min(len(ngrams_a), len(ngrams_b))
        char_score = intersection / smaller if smaller > 0 else 0.0

    # إشارة 3: تطابق الكيانات المعروفة (أسماء الشركات/العملات)
    import re
    entities_a = set()
    entities_b = set()
    text_a_lower = text_a.lower()
    text_b_lower = text_b.lower()
    for name, normalized in _ENTITY_NORMALIZE.items():
        if name in text_a_lower:
            entities_a.add(normalized)
        if name in text_b_lower:
            entities_b.add(normalized)
    entity_score = 0.0
    if entities_a and entities_b:
        entity_score = len(entities_a & entities_b) / min(len(entities_a), len(entities_b))

    #加权组合
    # entity score is the strongest signal
    if entity_score >= 0.5:
        # Same entity detected → lower text threshold needed
        combined = 0.25 * word_score + 0.25 * char_score + 0.50 * entity_score
    else:
        combined = 0.40 * word_score + 0.40 * char_score + 0.20 * entity_score
    return combined


def compute_text_fingerprint(text: str) -> str:
    """حساب بصمة نصية مطبعّة لكشف التكرار — كلمات معنوية فقط"""
    return _normalize_for_similarity(text)


def check_text_similarity(text: str, stored_fingerprints: list, threshold: float = 0.50) -> bool:
    """
    فحص تشابه النص ضد بصمات مخزنة.
    يُستخدم لكشف التكرار الدلالي عبر الدورات.
    يُرجع True إذا وجد تشابه >= threshold.
    """
    if not text or not stored_fingerprints:
        return False

    norm_new = _normalize_for_similarity(text)
    words_new = set(norm_new.split()) if norm_new else set()
    if not words_new:
        return False

    for fp in stored_fingerprints:
        if not fp:
            continue
        words_stored = set(fp.split())
        if not words_stored:
            continue
        intersection = len(words_new & words_stored)
        smaller = min(len(words_new), len(words_stored))
        if smaller > 0 and (intersection / smaller) >= threshold:
            return True

    return False
