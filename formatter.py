"""
🐋 Whale News Bot v3 - مُنسّق الأخبار
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
تحويل NewsItem إلى OutgoingMessage جاهز لتيليجرام
نظام قوالب ثابت — بدون أي تدخل AI
كل نوع خبر له قالب خاص بالتنسيق والهاشتاقات
"""

import time
from typing import Dict, List, Optional, Set

from models import NewsItem, NewsType, OutgoingMessage, Fact, ExtractedFacts
from config import COIN_NAME_TO_TICKER, COIN_MAP, cfg, log


# ═══════════════════════════════════════════════════════════
# 🏷️ خريطة نوع الخبر ← هاشتاق
# ═══════════════════════════════════════════════════════════
_NEWS_TYPE_HASHTAGS: Dict[NewsType, str] = {
    NewsType.GENERAL: "#أخبار_كريبتو",
    NewsType.HACK: "#اختراق",
    NewsType.ETF: "#ETF",
    NewsType.REGULATION: "#تنظيم",
    NewsType.TECHNICAL_ANALYSIS: "#تحليل",
    NewsType.MACRO: "#اقتصاد",
    NewsType.ECONOMIC_DATA: "#بيانات_اقتصادية",
    NewsType.ON_CHAIN: "#أون_تشين",
    NewsType.FUNDING: "#تمويل",
    NewsType.LISTING: "#إدراج",
    NewsType.PARTNERSHIP: "#شراكة",
    NewsType.STABLECOIN: "#ستيبلكوين",
    NewsType.ADOPTION: "#اعتماد",
}


# ═══════════════════════════════════════════════════════════
# 🎯 خريطة نوع الخبر ← نوع القالب
# ═══════════════════════════════════════════════════════════
#  A = أخبار عامة | H = اختراق | E = ETF | M = بيانات اقتصادية
_TEMPLATE_MAP: Dict[NewsType, str] = {
    NewsType.HACK: "H",
    NewsType.ETF: "E",
    NewsType.ECONOMIC_DATA: "M",
    # كل الأنواع الأخرى تستخدم القالب العام (A)
    NewsType.GENERAL: "A",
    NewsType.LISTING: "A",
    NewsType.PARTNERSHIP: "A",
    NewsType.REGULATION: "A",
    NewsType.MACRO: "A",
    NewsType.ON_CHAIN: "A",
    NewsType.TECHNICAL_ANALYSIS: "A",
    NewsType.FUNDING: "A",
    NewsType.STABLECOIN: "A",
    NewsType.ADOPTION: "A",
}


# ═══════════════════════════════════════════════════════════
# 🔧 دوال مساعدة
# ═══════════════════════════════════════════════════════════

def _extract_coin_hashtags(coins: List[str]) -> List[str]:
    """
    استخراج هاشتاقات العملات من قائمة العملات الخام.
    يحوّل الأسماء إلى tickers باستخدام COIN_NAME_TO_TICKER و COIN_MAP.
    """
    tickers: Set[str] = set()
    for coin in coins:
        coin_clean = coin.strip().lower()
        # البحث في خريطة الأسماء العربية أولاً
        if coin_clean in COIN_NAME_TO_TICKER:
            tickers.add(COIN_NAME_TO_TICKER[coin_clean])
        # ثم في خريطة العملات الإنجليزية
        elif coin_clean in COIN_MAP:
            tickers.add(COIN_MAP[coin_clean])
        # إذا كان الاسم نفسه ticker (مثل BTC, ETH)
        elif coin_clean.isupper() and len(coin_clean) <= 5:
            tickers.add(coin_clean.upper())
    return sorted(f"#{t}" for t in tickers)


def _build_hashtags(item: NewsItem) -> str:
    """
    بناء سطر الهاشتاقات.
    1. هاشتاق من نوع الخبر
    2. هاشتاقات من العملات المذكورة
    3. إزالة التكرار — حد أقصى 5 هاشتاقات
    """
    tags: List[str] = []

    # 1) هاشتاق نوع الخبر
    type_tag = _NEWS_TYPE_HASHTAGS.get(item.news_type, "#أخبار_كريبتو")
    tags.append(type_tag)

    # 2) هاشتاقات العملات (مسبوقة بـ #)
    coin_tags = _extract_coin_hashtags(item.facts.coins)
    tags.extend(coin_tags)

    # 3) إزالة التكرار مع الحفاظ على الترتيب
    seen: Set[str] = set()
    unique: List[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    # 4) حد أقصى 5 هاشتاقات
    unique = unique[:5]

    return " ".join(unique)


def _get_financial_detail(facts: ExtractedFacts) -> str:
    """
    استخراج التفاصيل المالية من الحقائق.
    يجمع amount_display للحقائق التي تحتوي على بيانات مالية.
    """
    if not facts or not facts.has_financial_data:
        return ""
    parts: List[str] = []
    for f in facts.facts:
        if f.amount_display:
            parts.append(f.amount_display)
    return " | ".join(parts) if parts else ""


def _get_consequence_detail(facts: ExtractedFacts) -> str:
    """
    استخراج تفاصيل العواقب من الحقائق.
    يجمع الحقائق التي تحتوي على consequences.
    """
    if not facts:
        return ""
    consequences: List[str] = []
    entities_seen: Set[str] = set()
    for f in facts.facts:
        if f.consequence and f.consequence != "neutral" and f.entity:
            # تجنب تكرار نفس الكيان
            if f.entity not in entities_seen:
                entities_seen.add(f.entity)
                cons_ar = {
                    "negative": "تأثير سلبي",
                    "positive": "تأثير إيجابي",
                    "neutral": "تأثير محايد",
                }.get(f.consequence, f.consequence)
                consequences.append(f"{f.entity}: {cons_ar}")
    return "\n".join(consequences) if consequences else ""


def _get_flow_detail(facts: ExtractedFacts) -> str:
    """
    استخراج تفاصيل التدفقات للـ ETF.
    يبحث عن حقائق تحتوي على action مثل inflow/outflow.
    """
    if not facts:
        return ""
    flows: List[str] = []
    for f in facts.facts:
        action_lower = f.action.lower()
        if "inflow" in action_lower or "outflow" in action_lower:
            if f.amount_display:
                flows.append(f.amount_display)
    return " | ".join(flows) if flows else ""


def _get_value_detail(facts: ExtractedFacts) -> str:
    """
    استخراج التفاصيل القيمية للـ ETF.
    يجمع قيم value_usd مع عرضها بشكل مقروء.
    """
    if not facts:
        return ""
    values: List[str] = []
    for f in facts.facts:
        if f.value_usd > 0:
            if f.value_usd >= 1_000_000_000:
                display = f"${f.value_usd / 1_000_000_000:.1f}B"
            elif f.value_usd >= 1_000_000:
                display = f"${f.value_usd / 1_000_000:.1f}M"
            elif f.value_usd >= 1_000:
                display = f"${f.value_usd / 1_000:.0f}K"
            else:
                display = f"${f.value_usd:,.0f}"
            values.append(display)
    return " | ".join(values) if values else ""


def _get_economic_indicator(facts: ExtractedFacts) -> Dict[str, str]:
    """
    استخراج بيانات المؤشر الاقتصادي من الحقائق.
    يُرجع dict يحتوي على: indicator_name, actual, previous, forecast
    """
    result: Dict[str, str] = {
        "indicator_name": "",
        "actual": "",
        "previous": "",
        "forecast": "",
    }
    if not facts or not facts.facts:
        return result

    # أول حقيقة هي عادة المؤشر الرئيسي
    main_fact = facts.facts[0]
    result["indicator_name"] = main_fact.entity or main_fact.platform or ""

    for f in facts.facts:
        action_lower = f.action.lower()
        # أفضلية: amount_display أولاً، ثم amount، ثم فارغ
        value = f.amount_display or (str(int(f.amount)) if f.amount else "")
        if not value:
            continue
        if "actual" in action_lower or "reported" in action_lower:
            result["actual"] = value
        elif "previous" in action_lower or "prior" in action_lower:
            result["previous"] = value
        elif "forecast" in action_lower or "expected" in action_lower or "estimate" in action_lower:
            result["forecast"] = value

    # لو لم نجد قيماً مفصّلة، نستخدم الأرقام المتاحة
    if not result["actual"] and main_fact.amount_display:
        result["actual"] = main_fact.amount_display

    return result


# ═══════════════════════════════════════════════════════════
# 📝 قوالب التنسيق
# ═══════════════════════════════════════════════════════════

def _format_general(item: NewsItem) -> str:
    """قالب A — أخبار عامة (GENERAL, LISTING, PARTNERSHIP, ...)"""
    headline = item.title_ar or item.title
    body = item.summary_ar or ""
    hashtags = _build_hashtags(item)
    channel = cfg.WATERMARK_TEXT

    parts: List[str] = [f"🔵 {headline}"]
    if body:
        parts.append("")
        parts.append(body)
    parts.append("")
    parts.append(hashtags)
    parts.append(channel)
    return "\n".join(parts)


def _format_hack(item: NewsItem) -> str:
    """قالب H — أخبار الاختراقات"""
    headline = item.title_ar or item.title
    body = item.summary_ar or ""
    hashtags = _build_hashtags(item)
    channel = cfg.WATERMARK_TEXT

    parts: List[str] = [f"🔴 {headline}"]

    # بيانات مالية إن وُجدت
    financial = _get_financial_detail(item.facts)
    if financial:
        parts.append(f"💰 {financial}")

    # تفاصيل العواقب
    consequence = _get_consequence_detail(item.facts)
    if consequence:
        parts.append(f"⚠️ {consequence}")

    if body:
        parts.append("")
        parts.append(body)

    parts.append("")
    parts.append(hashtags)
    parts.append(channel)
    return "\n".join(parts)


def _format_etf(item: NewsItem) -> str:
    """قالب E — أخبار ETF"""
    headline = item.title_ar or item.title
    body = item.summary_ar or ""
    hashtags = _build_hashtags(item)
    channel = cfg.WATERMARK_TEXT

    parts: List[str] = [f"📊 {headline}"]

    # تفاصيل التدفقات إن وُجدت
    flow = _get_flow_detail(item.facts)
    if flow:
        parts.append(f"📈 {flow}")

    # تفاصيل القيمة
    value = _get_value_detail(item.facts)
    if value:
        parts.append(f"💵 {value}")

    if body:
        parts.append("")
        parts.append(body)

    parts.append("")
    parts.append(hashtags)
    parts.append(channel)
    return "\n".join(parts)


def _format_economic(item: NewsItem) -> str:
    """قالب M — بيانات اقتصادية"""
    channel = cfg.WATERMARK_TEXT
    indicator = _get_economic_indicator(item.facts)
    body = item.summary_ar or ""
    hashtags = _build_hashtags(item)

    parts: List[str] = []

    # السطر الأول: اسم المؤشر والقيمة الفعلية
    indicator_name = indicator["indicator_name"]
    actual = indicator["actual"]
    if indicator_name and actual:
        parts.append(f"🔴 {indicator_name} — {actual}")
    else:
        # بدون بيانات هيكلية، نستخدم العنوان
        headline = item.title_ar or item.title
        parts.append(f"🔴 {headline}")

    # السطر الثاني: مقارنة القيم
    prev = indicator["previous"]
    forecast = indicator["forecast"]
    if prev or forecast:
        comparison_parts: List[str] = []
        if prev:
            comparison_parts.append(f"السابق: {prev}")
        if forecast:
            comparison_parts.append(f"التوقع: {forecast}")
        if actual:
            comparison_parts.append(f"الفعلي: {actual}")
        elif comparison_parts:
            # لو ما عندنا actual، نحذفه من المقارنة
            comparison_parts = [p for p in comparison_parts if not p.startswith("الفعلي")]
        if comparison_parts:
            parts.append(" | ".join(comparison_parts))

    if body:
        parts.append("")
        parts.append(body)

    parts.append("")
    parts.append(hashtags)
    parts.append(channel)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# 🏭 مصنّف القوالب
# ═══════════════════════════════════════════════════════════
_FORMATTERS: Dict[str, callable] = {
    "A": _format_general,
    "H": _format_hack,
    "E": _format_etf,
    "M": _format_economic,
}


# ═══════════════════════════════════════════════════════════
# 📤 الدالة العامة
# ═══════════════════════════════════════════════════════════

def format_news(item: NewsItem) -> Optional[OutgoingMessage]:
    """
    تنسيق خبر لتيليجرام.

    يختار القالب المناسب حسب نوع الخبر، يبني النص والهاشتاقات،
    ويعيد OutgoingMessage جاهز للنشر.

    يعيد None إذا كان الخبر غير صالح (بدون عنوان، قصير جداً، إلخ).

    Args:
        item: نموذج الخبر الكامل (NewsItem)

    Returns:
        OutgoingMessage جاهز للنشر، أو None إذا فشل التنسيق
    """
    # ── التحقق من صحة الخبر ──
    headline_ar = item.title_ar.strip() if item.title_ar else ""
    headline_en = item.title.strip() if item.title else ""

    # يجب أن يكون هناك عنوان عربي (≥10 حروف) أو عنوان إنجليزي كبديل
    if not headline_ar and not headline_en:
        log.debug(f"⏭️ تخطّي: بدون عنوان [hash={item.hash}]")
        return None

    if headline_ar and len(headline_ar) < 10:
        log.debug(f"⏭️ تخطّي: عنوان عربي قصير ({len(headline_ar)} حرف) [hash={item.hash}]")
        return None

    if not headline_ar and headline_en and len(headline_en) < 15:
        log.debug(f"⏭️ تخطّي: عنوان إنجليزي قصير ({len(headline_en)} حرف) [hash={item.hash}]")
        return None

    # ── اختيار القالب ──
    template_key = _TEMPLATE_MAP.get(item.news_type, "A")
    formatter_fn = _FORMATTERS.get(template_key)
    if not formatter_fn:
        log.warning(f"⚠️ قالب غير معروف: {template_key} — استخدام القالب العام")
        formatter_fn = _format_general

    try:
        formatted_text = formatter_fn(item)
    except Exception as e:
        log.error(f"❌ خطأ في تنسيق الخبر [hash={item.hash}]: {e}")
        return None

    # التحقق من أن النص النهائي ليس فارغاً
    if not formatted_text or len(formatted_text.strip()) < 15:
        log.debug(f"⏭️ تخطّي: نص منسّق فارغ أو قصير [hash={item.hash}]")
        return None

    # ── تحديد الأولوية حسب نوع الخبر ──
    priority_map = {
        NewsType.HACK: 1,          # أعلى أولوية
        NewsType.ECONOMIC_DATA: 2,  # بيانات اقتصادية عاجلة
        NewsType.ETF: 3,            # أخبار ETF مهمة
        NewsType.REGULATION: 4,     # تنظيم
        NewsType.MACRO: 5,
        NewsType.GENERAL: 7,
        NewsType.LISTING: 6,
        NewsType.PARTNERSHIP: 8,
        NewsType.ON_CHAIN: 8,
        NewsType.TECHNICAL_ANALYSIS: 9,
        NewsType.FUNDING: 8,
        NewsType.STABLECOIN: 8,
        NewsType.ADOPTION: 8,
    }
    priority = priority_map.get(item.news_type, 7)

    # ── بناء الرسالة ──
    msg = OutgoingMessage(
        text=formatted_text,
        image_url=item.image if item.image else None,
        image_data=None,  # يتم ملؤها لاحقاً في publisher (watermark)
        chat_id=cfg.CHANNEL_ID,
        priority=priority,
        retry_count=0,
        max_retries=cfg.MAX_RETRIES,
        created_at=time.time(),
    )

    log.info(
        f"✅ تنسيق بنجاح: قالب={template_key} | "
        f"نوع={item.news_type.value} | أولوية={priority} | "
        f"طول={len(formatted_text)} | صورة={'نعم' if msg.image_url else 'لا'}"
    )
    return msg
