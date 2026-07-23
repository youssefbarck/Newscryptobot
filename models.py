"""
🐋 Whale News Bot v3 - نماذج البيانات
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
كل كائن بيانات مستقل — نقطة التقاء كل الوحدات
"""

import re, hashlib, time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from enum import Enum


# ═══════════════════════════════════════════════════════════
# 📰 أنواع الأخبار
# ═══════════════════════════════════════════════════════════
class NewsType(Enum):
    """أنواع الأخبار المحددة"""
    ETF = "etf"
    HACK = "hack"
    LISTING = "listing"
    PARTNERSHIP = "partnership"
    REGULATION = "regulation"
    MACRO = "macro"
    ON_CHAIN = "on_chain"
    TECHNICAL_ANALYSIS = "technical_analysis"
    FUNDING = "funding"
    STABLECOIN = "stablecoin"
    GENERAL = "general"
    ECONOMIC_DATA = "economic_data"
    ADOPTION = "adoption"


class SourceQuality(Enum):
    """جودة المصدر"""
    TIER_1 = "tier_1"   # CoinDesk, Cointelegraph, Blockworks
    TIER_2 = "tier_2"   # Decrypt, BeInCrypto, CoinPedia
    TIER_3 = "tier_3"   # Google News aggregated
    TIER_4 = "tier_4"   # Unknown / low quality


# ═══════════════════════════════════════════════════════════
# 📊 نموذج الحقائق المستخرجة
# ═══════════════════════════════════════════════════════════
@dataclass
class Fact:
    """حقيقة واحدة مستخرجة من الخبر"""
    entity: str = ""           # BlackRock, Bitcoin, SEC
    action: str = ""           # bought, hacked, approved, announced
    asset: str = ""            # BTC, ETH, USDT
    amount: float = 0.0        # 400, 48000000
    amount_display: str = ""    # "400 BTC", "$48M"
    value_usd: float = 0.0     # القيمة بالدولار
    platform: str = ""          # Binance, Ethereum
    consequence: str = ""       # positive, negative, neutral
    timeframe: str = ""         # Q4 2024, today, upcoming


@dataclass
class ExtractedFacts:
    """كل الحقائق المستخرجة من خبر واحد"""
    facts: List[Fact] = field(default_factory=list)
    main_entities: List[str] = field(default_factory=list)
    coins: List[str] = field(default_factory=list)
    companies: List[str] = field(default_factory=list)
    people: List[str] = field(default_factory=list)
    numbers: List[str] = field(default_factory=list)
    has_financial_data: bool = False
    sentiment: str = "neutral"  # positive, negative, neutral

    def to_fact_key(self) -> str:
        """مفتاح فريد لكشف التكرار — يعتمد على الحقائق لا النص"""
        entities = sorted(set(self.main_entities))
        coins = sorted(set(self.coins))
        key = "|".join(entities + coins)
        return hashlib.md5(key.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════
# 📰 نموذج الخبر الكامل
# ═══════════════════════════════════════════════════════════
@dataclass
class NewsItem:
    """نموذج الخبر — يمر عبر كل مراحل الـ Pipeline"""
    # --- البيانات الخام ---
    title: str = ""
    link: str = ""
    summary: str = ""
    image: str = ""
    source: str = ""
    source_quality: SourceQuality = SourceQuality.TIER_3
    category: str = ""
    timestamp: float = 0.0
    lang: str = "en"

    # --- بيانات التنظيف ---
    clean_title: str = ""
    clean_summary: str = ""

    # --- الحقائق المستخرجة ---
    facts: ExtractedFacts = field(default_factory=ExtractedFacts)

    # --- التصنيف ---
    news_type: NewsType = NewsType.GENERAL
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # --- الترجمة ---
    title_ar: str = ""
    summary_ar: str = ""

    # --- التنسيق ---
    formatted_text: str = ""
    format_type: str = ""

    # --- حالة النشر ---
    is_duplicate: bool = False
    is_merged: bool = False
    merged_sources: List[str] = field(default_factory=list)
    hash: str = ""

    def __post_init__(self):
        if not self.hash and self.title:
            self.hash = self._compute_hash()
        if self.facts is None:
            self.facts = ExtractedFacts()

    def _compute_hash(self) -> str:
        """hash يعتمد على العنوان فقط (للـ dedup السريع)"""
        title_norm = re.sub(r'[^\w\s]', '', self.title.lower())
        title_norm = re.sub(r'\s+', ' ', title_norm).strip()
        title_norm = re.sub(
            r'^(breaking|update|news|alert|urgent|just in|report|exclusiv)[\s:]*',
            '', title_norm
        )
        hash_input = title_norm[:100]
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def get_fact_hash(self) -> str:
        """hash يعتمد على الحقائق (للـ dedup الذكي)"""
        if self.facts and self.facts.main_entities:
            return self.facts.to_fact_key()
        return self.hash

    def is_valid(self) -> bool:
        """هل الخبر صالح للنشر؟"""
        if not self.title or len(self.title.strip()) < 15:
            return False
        if not self.title_ar and not self.summary_ar:
            return False
        if not self.title_ar or len(self.title_ar.strip()) < 10:
            return False
        return True


# ═══════════════════════════════════════════════════════════
# 📊 نموذج التقييم
# ═══════════════════════════════════════════════════════════
@dataclass
class ScoreResult:
    """نتيجة تقييم الخبر"""
    total: float = 0.0
    source_score: float = 0.0
    urgency_score: float = 0.0
    financial_score: float = 0.0
    entity_score: float = 0.0
    age_score: float = 0.0
    type_score: float = 0.0
    bonus: float = 0.0
    penalty: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    should_publish: bool = False
    reason: str = ""

    def __post_init__(self):
        self.total = (
            self.source_score + self.urgency_score + self.financial_score
            + self.entity_score + self.age_score + self.type_score
            + self.bonus + self.penalty
        )
        self.total = max(0, self.total)
        self.should_publish = self.total >= 35.0
        self.breakdown = {
            "source": self.source_score,
            "urgency": self.urgency_score,
            "financial": self.financial_score,
            "entity": self.entity_score,
            "age": self.age_score,
            "type": self.type_score,
            "bonus": self.bonus,
            "penalty": self.penalty,
        }


# ═══════════════════════════════════════════════════════════
# 📤 نموذج الرسالة
# ═══════════════════════════════════════════════════════════
@dataclass
class OutgoingMessage:
    """رسالة جاهزة للنشر"""
    text: str = ""
    image_url: Optional[str] = None
    image_data: Optional[bytes] = None  # صورة بعد إضافة الـ watermark
    chat_id: str = ""
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# 📈 نموذج الإحصائيات
# ═══════════════════════════════════════════════════════════
@dataclass
class PipelineStats:
    """إحصائيات دورة واحدة"""
    cycle_id: str = ""
    timestamp: float = field(default_factory=time.time)
    collected: int = 0
    cleaned: int = 0
    facts_extracted: int = 0
    classified: int = 0
    deduplicated: int = 0  # عدد الأخبار المكررة المحذوفة
    scored: int = 0
    scored_above_threshold: int = 0
    rewritten: int = 0
    formatted: int = 0
    published: int = 0
    failed: int = 0
    by_source: Dict[str, int] = field(default_factory=dict)
    by_type: Dict[str, int] = field(default_factory=dict)
    rejected: List[Dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"📊 Pipeline: جمع={self.collected} → نظف={self.cleaned} → "
            f"حقائق={self.facts_extracted} → صنف={self.classified} → "
            f"حذف مكرر={self.deduplicated} → "
            f"فوق العتبة={self.scored_above_threshold}/{self.scored} → "
            f"أُعيدت صياغته={self.rewritten} → نُشر={self.published}"
        )
