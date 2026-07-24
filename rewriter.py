"""
🐋 Whale News Bot v3 - وحدة إعادة الصياغة بالعربية
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
واحد فقط: إعادة كتابة الخبر بالعربية بأسلوب صحفي.
لا تصنيف، لا تقييم، لا هاشتاغات — فقط صياغة عربية نظيفة.
"""

import re
import json
import asyncio
import time
import aiohttp
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass

from config import log, cfg, CircuitBreaker
from models import NewsItem, NewsType


# ═══════════════════════════════════════════════════════════════
# 🔒 حماية الكيانات — منع ترجمة الأسماء الخاصة
# ═══════════════════════════════════════════════════════════════

# قائمة الكيانات المحمية: عملات، شركات، أشخاص
PROTECTED_ENTITIES: Dict[str, str] = {
    # --- عملات رقمية (tickers) ---
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "POL", "LTC", "TRX", "UNI", "AAVE", "NEAR", "APT", "ARB", "OP",
    "SUI", "SEI", "PEPE", "SHIB", "TON", "FTM", "ATOM", "XLM", "HBAR",
    "BNB", "USDT", "USDC", "DAI", "BCH", "BCH",
    # --- أسماء كاملة ---
    "Bitcoin", "Ethereum", "Solana", "Ripple", "Cardano", "Dogecoin",
    "Avalanche", "Polkadot", "Chainlink", "Polygon", "Litecoin", "Tron",
    "Uniswap", "Cosmos", "Stellar", "Hedera", "Binance Coin",
    "Tether", "USD Coin",
    # --- شركات ---
    "BlackRock", "Fidelity", "Grayscale", "MicroStrategy", "Coinbase",
    "Binance", "Kraken", "SEC", "Federal Reserve", "VanEck",
    "Franklin Templeton", "ARK Invest", "21Shares", "Bitwise",
    "OKX", "Bybit", "Circle", "Paxos", "BitGo", "Fireblocks",
    "Galaxy Digital", "DCG", "Genesis", "Three Arrows Capital",
    # --- أشخاص ---
    "Elon Musk", "Michael Saylor", "Cathie Wood", "Vitalik Buterin",
    "Gary Gensler", "CZ", "SBF", "Brian Armstrong", "Larry Fink",
    "Jerome Powell", "Jack Dorsey", "Charles Hoskinson",
    # --- مصطلحات تقنية/مالية يجب عدم ترجمتها ---
    "ETF", "DeFi", "NFT", "Web3", "DePIN", "RWA", "Layer 2", "Layer2",
    "Mainnet", "Testnet", "Hard Fork", "Soft Fork", "Airdrop",
    "Satoshi", "Satoshi Nakamoto", "FOMC", "CPI", "PPI", "GDP", "NFP",
    "PMI", "PCE", "API", "TVL", "APY", "APR", "KYC", "AML",
}

# كلمات إنجليزية مسموحة في النص العربي (لا نعتبرها خطأ)
ALLOWED_ENGLISH_TERMS: Set[str] = {
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "BNB", "USDT", "USDC", "DAI", "USD", "EUR", "GBP", "JPY", "CNY",
    "ETF", "DeFi", "NFT", "Web3", "TVL", "APY", "APR", "API", "KYC",
    "AML", "RWA", "DePIN", "CEO", "CTO", "CFO", "SEC", "FED", "FOMC",
    "CPI", "PPI", "GDP", "NFP", "PMI", "PCE", "ATH", "ATL", "ROI",
    "HODL", "FOMO", "YOLO", "ICO", "IDO", "IEO", "LTO", "L2",
    "Bull", "Bear", "Rally", "Crash", "Pump", "Dump", "Mainnet",
    "OKX", "DeFi", "AMM", "DEX", "CEX",
}

# مسرد المصطلحات الكريبتوية → ترجمتها العربية
CRYPTO_GLOSSARY: Dict[str, str] = {
    "smart wallet": "المحفظة الذكية",
    "flash loan": "قرض فلاش",
    "rug pull": "سحب سجادة",
    "yield farming": "زراعة العوائد",
    "liquidity pool": "تجمع السيولة",
    "market cap": "القيمة السوقية",
    "whale": "الحوت",
    "staking": "الستيكينغ",
    "mining": "التعدين",
    "halving": "التنصيف",
    "bull run": "الصعود",
    "bear market": "السوق الهابط",
    "bull market": "السوق الصاعد",
    "gas fee": "رسوم الغاز",
    "blockchain": "البلوكتشين",
    "decentralized": "لامركزي",
    "smart contract": "العقد الذكي",
    "token burn": "حرق التوكنز",
    "liquidity": "السيولة",
    "total value locked": "إجمالي القيمة المقفلة",
}

# نوع الخبر بالعربية
NEWS_TYPE_AR: Dict[str, str] = {
    "etf": "صناديق الاستثمار المتداولة (ETF)",
    "hack": "اختراق أمني",
    "listing": "إدراج في منصة تداول",
    "partnership": "شراكة",
    "regulation": "تنظيم وتشريعات",
    "macro": "اقتصاد كلي",
    "on_chain": "بيانات أون-تشين",
    "technical_analysis": "تحليل فني",
    "funding": "تمويل واستثمار",
    "stablecoin": "عملات مستقرة",
    "general": "أخبار عامة",
    "economic_data": "بيانات اقتصادية",
    "adoption": "اعتماد وتوسع",
}

# ═══════════════════════════════════════════════════════════════
# 🔌 Circuit Breakers لكل مزوّد
# ═══════════════════════════════════════════════════════════════

GEMINI_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)
GROQ_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)
OPENROUTER_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)
TRANSLATE_CB = CircuitBreaker(fail_threshold=3, reset_timeout=300)


# ═══════════════════════════════════════════════════════════════
# 🛡️ نظام حماية الكيانات
# ═══════════════════════════════════════════════════════════════

def _build_entity_map(item: NewsItem) -> Dict[str, str]:
    """
    بناء خريطة الكيانات من الخبر + القائمة الثابتة.
    يُرجع {اسم_الكيان: placeholder}
    """
    entities: Dict[str, str] = {}

    # الكيانات الثابتة
    for ent in PROTECTED_ENTITIES:
        placeholder = f"§ENT{len(entities):03d}§"
        entities[ent] = placeholder

    # الكيانات المستخرجة من الخبر
    if item.facts:
        for coin in item.facts.coins:
            if coin and coin not in entities:
                placeholder = f"§ENT{len(entities):03d}§"
                entities[coin] = placeholder
        for company in item.facts.companies:
            if company and company not in entities:
                placeholder = f"§ENT{len(entities):03d}§"
                entities[company] = placeholder
        for person in item.facts.people:
            if person and person not in entities:
                placeholder = f"§ENT{len(entities):03d}§"
                entities[person] = placeholder
        for entity in item.facts.main_entities:
            if entity and entity not in entities:
                placeholder = f"§ENT{len(entities):03d}§"
                entities[entity] = placeholder

    return entities


def _apply_glossary(text: str) -> str:
    """تطبيق المسرد قبل الحماية — المصطلحات التي نريد ترجمتها"""
    for en_term, ar_term in CRYPTO_GLOSSARY.items():
        # فقط المصطلحات الإنجليزية → نستبدلها بالعربية
        text = re.sub(
            re.escape(en_term),
            ar_term,
            text,
            flags=re.IGNORECASE,
        )
    return text


def _protect_entities(text: str, entity_map: Dict[str, str]) -> str:
    """
    استبدال أسماء الكيانات بـ placeholders.
    الترتيب: الأطول أولاً لمنع الاستبدال الجزئي.
    """
    # ترتيب حسب الطول (الأطول أولاً)
    sorted_entities = sorted(entity_map.items(), key=lambda x: len(x[0]), reverse=True)
    for entity, placeholder in sorted_entities:
        # استبدال الكلمة الكاملة فقط (case-sensitive للأسماء الخاصة)
        text = re.sub(
            r'\b' + re.escape(entity) + r'\b',
            placeholder,
            text,
        )
    return text


def _restore_entities(text: str, entity_map: Dict[str, str]) -> str:
    """استعادة أسماء الكيانات من الـ placeholders"""
    for entity, placeholder in entity_map.items():
        text = text.replace(placeholder, entity)
    return text


def _has_orphan_placeholders(text: str) -> bool:
    """هل يوجد placeholders لم تُستبدل (بقيت من الـ AI)؟"""
    return bool(re.search(r'§ENT\d{3}§', text))


def _has_empty_entity_slots(text: str) -> bool:
    """هل يوجد فتحات فارغة تدل على أسماء كيانات محذوفة؟"""
    patterns = [
        r'\s،\s+(?:الرئيس|المدير|المؤسس|المالك|الرئيس التنفيذي)',
        r'أفاد\s+[،,]\s+',
        r'أكد\s+[،,]\s+',
        r'صرح\s+[،,]\s+',
        r'على\s+منصات?\s+[و]\s+[و]\s+',
        r'تطبيق\s+(?:الذي|المرتبط)\s+',
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _build_facts_summary(item: NewsItem) -> str:
    """بناء ملخص الحقائق للـ prompt — يشمل كل الكيانات التي يجب الحفاظ عليها"""
    if not item.facts:
        return "لا توجد حقائق مستخرجة"

    parts: List[str] = []
    if item.facts.main_entities:
        parts.append(f"الكيانات الرئيسية: {', '.join(item.facts.main_entities)}")
    if item.facts.coins:
        parts.append(f"العملات: {', '.join(item.facts.coins)}")
    if item.facts.companies:
        parts.append(f"الشركات: {', '.join(item.facts.companies)}")
    if item.facts.people:
        parts.append(f"الأشخاص: {', '.join(item.facts.people)}")
    if item.facts.platforms:
        parts.append(f"المنصات: {', '.join(item.facts.platforms)}")
    if item.facts.numbers:
        parts.append(f"الأرقام: {', '.join(item.facts.numbers[:5])}")
    if item.facts.sentiment and item.facts.sentiment != "neutral":
        parts.append(f"الاتجاه: {item.facts.sentiment}")

    return " | ".join(parts) if parts else "لا توجد حقائق مستخرجة"


# ═══════════════════════════════════════════════════════════════
# 📝 بناء الـ Prompt
# ═══════════════════════════════════════════════════════════════

def _build_prompt(item: NewsItem) -> str:
    """بناء الـ prompt البسيط والمركّز"""
    news_type_ar = NEWS_TYPE_AR.get(item.news_type.value, "أخبار عامة")
    facts_summary = _build_facts_summary(item)
    title = (item.clean_title or item.title)[:300]
    summary = (item.clean_summary or item.summary)[:800]

    prompt = (
        f"أنت محرر أخبار كريبتو محترف. أعد كتابة الخبر التالي باللغة العربية "
        f"بأسلوب صحفي واضح ومختصر.\n\n"
        f"نوع الخبر: {news_type_ar}\n"
        f"الحقائق المستخرجة: {facts_summary}\n"
        f"النص الأصلي:\n"
        f"العنوان: {title}\n"
        f"المحتوى: {summary}\n\n"
        f"القواعد الصارمة:\n"
        f"1. اكتب فقط: عنوان قصير جداً (سطر واحد فقط، أقل من 15 كلمة) + فقرة واحدة مختصرة (3-5 جمل)\n"
        f"2. لا تضف تعليقات أو تحليلات شخصية\n"
        f"3. لا تذكر اسم المصدر في النص (لا تقل 'وفقاً لمصادر' أو 'بحسب تقرير')\n"
        f"4. احتفظ بأسماء الأشخاص والشركات والعملات كما هي — لا تحذف أي اسم واستبدله بفارغ أو بفاصلة\n"
        f"5. لا تضيف هاشتاغ أو إيموجي أو تسميات مثل 'أخبار عاجلة'\n"
        f"6. لا تستخدم أي كلمة إنجليزية أو صينية أو يابانية إلا أسماء العملات والشركات (مثل BTC, BlackRock)\n"
        f"7. العنوان يجب أن يكون مختلفاً تماماً عن المحتوى — لا تكرر نفس الجمل أو الكلمات\n"
        f"8. لا تكرر نفس الجملة أو العبارة أكثر من مرة في المحتوى\n"
        f"9. اكتب بأسلوب عربي سليم — لا تخلط العربية بغيرها من اللغات\n"
        f'10. أعد النتيجة كـ JSON فقط:\n{{"headline": "...", "body": "..."}}'
    )
    return prompt


# ═══════════════════════════════════════════════════════════════
# 🧹 تنظيف النص المُترجم — طبقة حماية إضافية بعد الترجمة
# ═══════════════════════════════════════════════════════════════

# أنماط تسريبات التصنيف من AI (في النص العربي)
_RE_FORMAT_LABELS_AR = re.compile(
    r"(?:"
    r"أخبار عاجلة|أخبار عامة|أخبار الكريبتو|أخبار العملات المشفرة|"
    r"تقرير تحليلي|تقرير خاص|ملخص الأخبار|تحديث السوق|"
    r"منشور الأخبار العاجلة|أخبار مستعجلة|عاجل جداً|"
    r"آخر الأخبار|أحدث الأخبار|آخر المستجدات"
    r")[\s:]*",
    re.IGNORECASE,
)

# أنماط تسريبات المصادر في النص العربي
_RE_SOURCE_LEAKS_AR = re.compile(
    r"(?:"
    r"وفقاً\s+ل(?:ـ)?\s*(?:تقرير|مصادر?|المصادر?|التقارير?|وسائل\s+الإعلام)|"
    r"وفق[اًا]\s+ل(?:ـ)?\s*(?:تقرير|مصادر?|المصادر?|التقارير?)|"
    r"كشفت?\s+(?:المصادر?|التقارير?|وسائل\s+الإعلام)\s+(?:عن|أن)|"
    r"أفادت?\s+(?:المصادر?|التقارير?)\s+(?:عن|أن)|"
    r"أكدت?\s+(?:المصادر?|التقارير?)|"
    r"ذكرت?\s+(?:المصادر?|التقارير?|وسائل\s+الإعلام)|"
    r"نقلت?\s+(?:عن|وكالات|الأنباء)|"
    r"أشارت?\s+(?:المصادر?|التقارير?|لـ)|"
    r"بحسب\s+(?:تقرير|مصدر|المصادر?|التقارير?)"
    r")[\s:,،.]*",
    re.IGNORECASE,
)

# أنماط تسريبات المصادر في النص الإنجليزي (إن بقيت كلمات إنجليزية)
_RE_SOURCE_LEAKS_EN_IN_AR = re.compile(
    r"(?:"
    r"According\s+to\s+(?:a\s+)?(?:report|sources?|analysts?|data)|"
    r"Reported\s+by|"
    r"(?:said|reported|announced|revealed|stated|confirmed)\s+by"
    r")[\s:,]*",
    re.IGNORECASE,
)

# أنماط أسماء المصادر المعروفة في النص المُترجم
_RE_KNOWN_SOURCES_IN_TEXT = re.compile(
    r"(?:"
    r"CoinDesk|Cointelegraph|Blockworks|Decrypt|"
    r"BeInCrypto|Crypto\.News|CoinPedia|Bitcoinist|"
    r"The\s+Block|Bitcoin\s+Magazine|Bloomberg|Reuters|"
    r"CNBC|Forbes|CoinMarketCap|CoinGecko"
    r")[\s:,]",
    re.IGNORECASE,
)

# هاشتاقات مُضمّنة في النص (سيعيد formatter بناءها)
_RE_EMBEDDED_HASHTAGS = re.compile(r"#\w+")

# إيموجي زائدة (formatter يضيفها في بداية السطر)
_RE_EMOJI_PREFIX = re.compile(
    r"^[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA9F"
    r"\U0001FAD0-\U0001FAFF\u2702\u2705\u274c\u274e\u2753-\u2757"
    r"\u2763\u2764\u2795-\u2797\u2b50\u2b55\u2b1b\u2b1c"
    r"\ufe0f]{1,4}\s+",
)

# أقواس مربعة وعلامات markdown
_RE_BRACKETS_MARKDOWN = re.compile(
    r"(?:\[.*?\]|\(.*?\))",
)

# كلمات إنجليزية غير مسموحة (≥ 4 أحرف) — تُزال من النص العربي
# نستخدم نفس ALLOWED_ENGLISH_TERMS أعلاه


def _text_similarity(a: str, b: str) -> float:
    """حساب تشابه نصين بناءً على الكلمات المشتركة"""
    if not a or not b:
        return 0.0
    words_a = set(re.findall(r'[\w\u0600-\u06FF]+', a.lower()))
    words_b = set(re.findall(r'[\w\u0600-\u06FF]+', b.lower()))
    if not words_a or not words_b:
        return 0.0
    common = words_a & words_b
    return len(common) / min(len(words_a), len(words_b))


def _clean_translated_text(headline: str, body: str) -> Tuple[str, str]:
    """
    طبقة تنظيف نهائية AFTER الترجمة.
    تُنفّذ على النص العربي المُترجم قبل التنسيق.

    تحل 7 مشاكل:
    1. تسرب تصنيف المنشور ("أخبار عاجلة: ...")
    2. تسرب أسماء المصادر ("وفقاً لمصادر..." / "CoinDesk")
    3. كلمات إنجليزية فاسدة (market, exchange, platform)
    4. هاشتاقات مُضمّنة (#بيتكوين) — formatter يبنيها
    5. إيموجي زائدة — formatter يضيفها
    6. أحرف صينية/يابانية/كورية متسربة
    7. جمل مكررة داخل نفس المحتوى
    """
    # ── تنظيف العنوان ──
    headline = _clean_one_line(headline)

    # ── تنظيف المحتوى ──
    body_lines = body.split("\n")
    cleaned_lines = []
    for line in body_lines:
        line = _clean_one_line(line)
        if line.strip():
            cleaned_lines.append(line)
    body = "\n".join(cleaned_lines)

    # 6️⃣ إزالة الأحرف الصينية/اليابانية/الكورية (CJK)
    headline = re.sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+', '', headline)
    body = re.sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+', '', body)

    # 7️⃣ إزالة الجمل المكررة في المحتوى
    body = _deduplicate_sentences(body)

    # تنظيف المسافات الأخيرة
    headline = headline.strip()
    body = body.strip()

    # فحص تكرار العنوان في المحتوى — طبقة حماية أساسية
    if headline and body:
        similarity = _text_similarity(headline, body)
        if similarity > 0.6:
            log.debug(f"⏭️ تشابه headline/body: {similarity:.0%} — حذف المحتوى المكرر")
            body = ""

    return headline, body


def _clean_one_line(text: str) -> str:
    """تنظيف سطر واحد من النص المُترجم"""
    if not text:
        return text

    original = text

    # 1️⃣ إزالة تسميات التصنيف العربي
    text = _RE_FORMAT_LABELS_AR.sub("", text)

    # 2️⃣ إزالة تسريبات المصادر العربية
    text = _RE_SOURCE_LEAKS_AR.sub("", text)

    # 2️⃣b إزالة تسريبات المصادر الإنجليزية
    text = _RE_SOURCE_LEAKS_EN_IN_AR.sub("", text)

    # 2️⃣c إزالة أسماء المصادر المعروفة
    text = _RE_KNOWN_SOURCES_IN_TEXT.sub("", text)

    # 3️⃣ إزالة الكلمات الإنجليزية غير المسموحة
    text = _remove_unwanted_english_words(text)

    # 4️⃣ إزالة الهاشتاقات المُضمّنة
    text = _RE_EMBEDDED_HASHTAGS.sub("", text)

    # 5️⃣ إزالة الإيموجي من بداية السطر
    text = _RE_EMOJI_PREFIX.sub("", text)

    # 6️⃣ إزالة أقواس وعلامات markdown
    text = _RE_BRACKETS_MARKDOWN.sub("", text)

    # 6️⃣b إزالة الأحرف الصينية/اليابانية/الكورية (CJK)
    text = re.sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+', '', text)

    # تنظيف المسافات والفواصل المتروكة
    text = re.sub(r"\s*[.,،؛]\s*\.", ".", text)
    text = re.sub(r"^[.,،؛]\s+", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^\s*[-–—:،]\s*", "", text)
    text = text.strip()

    # 7️⃣ حذف الجمل الناقصة — تنتهي بحرف جر أو عطف ثم نقطة مباشرة
    # مثل: "نقل الأموال إلى ." أو "حسبما ذكر من ." أو "مع أنه ."
    text = re.sub(
        r"\s+(?:إلى|من|على|في|عن|مع|عبر|خلال|حتى|بعد|قبل|لـ|لكل|via|through|to|from|at)\s*\.\s*",
        " ", text
    )
    # تنظيف الفاصلة/العطف المتروك بعد حذف الجملة الناقصة
    text = re.sub(r"\s+[،,]\s*\.\s*", ".", text)
    text = re.sub(r"\s+[،,]\s*$", "", text)
    text = re.sub(r"^\s*[،,]\s+", "", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = text.strip()

    if text != original:
        log.debug(f"_clean_translated: '{original[:50]}...' → '{text[:50]}...'")

    return text


# كلمات إنجليزية قصيرة (1-3 حروف) تُظهر في النص العربي — تُحذف دائماً
_SHORT_ENGLISH_BLOCKLIST: Set[str] = {
    # حروف جر وأدوات ربط
    "the", "and", "for", "but", "not", "are", "was", "has", "had",
    "its", "all", "any", "out", "how", "who", "why", "can", "may",
    "our", "she", "his", "her", "him", "you", "they", "them",
    "this", "that", "with", "from", "into", "also", "just", "than",
    "been", "will", "would", "could", "should", "does", "done",
    # كلمات متداولة في الكريبتو
    "via", "cap", "fee", "gas", "key", "top", "new", "old", "now",
    "per", "yet", "set", "run", "buy", "sell", "hot", "low",
    "gap", "net", "cut", "bit", "lot", "way", "use", "put",
    "led", "saw", "met", "got", "let", "due", "mid",
}


def _remove_unwanted_english_words(text: str) -> str:
    """
    إزالة الكلمات الإنجليزية غير المسموحة من النص العربي.
    يزيل الكلمات 1-3 حروف من القائمة السوداء + 4+ حروف غير المسموحة.
    """
    # 1) إزالة الكلمات القصيرة (1-3 حروف) من القائمة السوداء
    for word in _SHORT_ENGLISH_BLOCKLIST:
        text = re.sub(r'\b' + re.escape(word) + r'\b', '', text, flags=re.IGNORECASE)

    # 2) إزالة الكلمات الطويلة (4+ حروف) غير المسموحة
    def _replace_word(match):
        word = match.group(0)
        if word.upper() in ALLOWED_ENGLISH_TERMS:
            return word  # مسموحة
        return ""  # غير مسموحة → حذف

    text = re.sub(r"\b[a-zA-Z]{4,}\b", _replace_word, text)
    return text


# ═══════════════════════════════════════════════════════════════
# 🔍 فحص جودة النتيجة
# ═══════════════════════════════════════════════════════════════

def _arabic_char_ratio(text: str) -> float:
    """نسبة الأحرف العربية في النص"""
    if not text:
        return 0.0
    arabic_count = sum(1 for c in text if '\u0600' <= c <= '\u06FF' or '\uFB50' <= c <= '\uFDFF')
    return arabic_count / len(text)


def _has_unwanted_english(text: str) -> bool:
    """هل يوجد كلمات إنجليزية غير مسموحة؟"""
    # فحص الكلمات القصيرة
    short_words = re.findall(r'\b[a-zA-Z]{1,3}\b', text)
    for word in short_words:
        if word.lower() in _SHORT_ENGLISH_BLOCKLIST:
            return True
    # فحص الكلمات الطويلة
    long_words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
    for word in long_words:
        if word.upper() not in ALLOWED_ENGLISH_TERMS:
            return True
    return False


def _deduplicate_sentences(body: str) -> str:
    """
    إزالة الجمل المكررة في المحتوى.
    يحتفظ بأول occurrence ويحذف المكررات.
    """
    if not body:
        return body
    sentences = re.split(r'[.。，]\s*', body)
    seen: List[str] = []
    unique: List[str] = []
    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent) < 10:
            continue
        normalized = sent.lower().strip()
        is_dup = False
        for prev in seen:
            words_s = set(re.findall(r'[\w\u0600-\u06FF]+', normalized))
            words_p = set(re.findall(r'[\w\u0600-\u06FF]+', prev))
            if not words_s or not words_p:
                continue
            common = words_s & words_p
            sim = len(common) / min(len(words_s), len(words_p))
            if sim > 0.75 and abs(len(sent) - len(prev)) < max(len(sent), len(prev)) * 0.3:
                is_dup = True
                log.debug(f"_deduplicate_sentences: حذف جملة مكررة: '{sent[:50]}...'")
                break
        if not is_dup:
            seen.append(normalized)
            unique.append(sent)
    return ". ".join(unique)


def _check_quality(headline: str, body: str) -> Tuple[bool, str]:
    """
    فحص جودة النتيجة — 7 طبقات حماية.
    يُرجع (مقبول، سبب_الرفض)
    """
    if not headline or len(headline.strip()) < 15:
        return False, f"العنوان قصير جداً ({len(headline) if headline else 0} حرف)"
    if not body or len(body.strip()) < 50:
        return False, f"المحتوى قصير جداً ({len(body) if body else 0} حرف)"
    combined = headline + " " + body

    # ── فحص 1: نسبة العربية ──
    ratio = _arabic_char_ratio(combined)
    if ratio < 0.40:
        return False, f"نسبة العربية منخفضة ({ratio:.0%})"

    # ── فحص 2: كلمات إنجليزية غير مسموحة ──
    if _has_unwanted_english(combined):
        return False, "يوجد كلمات إنجليزية غير مسموحة"

    # ── فحص 3: أحرف صينية/يابانية/كورية (CJK) ──
    if re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', combined):
        return False, "يوجد أحرف صينية أو يابانية في النص"

    # ── فحص 4: فتحات كيانات فارغة (أسماء محذوفة) ──
    empty_entity_patterns = [
        r'\s،\s+(?:الرئيس|المدير|المؤسس|المالك|الرئيس التنفيذي|المسؤول|المتحدث)',
        r'(?:الرئيس|المدير|المؤسس|المالك|الرئيس التنفيذي|المسؤول|المتحدث)\s+ل(?:ـ)?(?:شركة|مؤسسة|منصة|صندوق|مجموعة)\s+[.،]\s*',
        r'أفاد\s+[،,]\s+',                      # "أفاد ،" بدون اسم
        r'أكد\s+[،,]\s+',                      # "أكد ،" بدون اسم
        r'صرح\s+[،,]\s+',                      # "صرح ،" بدون اسم
        r'أعلن\s+[،,]\s+',                      # "أعلن ،" بدون اسم
        r'ذكر\s+[،,]\s+',                       # "ذكر ،" بدون اسم
        r'كشف\s+[،,]\s+',                       # "كشف ،" بدون اسم
        r'على\s+منصات?\s+[و]\s+[و]\s+',          # "على منصات و و" — أسماء منصات محذوفة
        r'تطبيق\s+(?:الذي|المرتبط|المشفر)\s+(?:بـ|ال)',  # "تطبيق الذي" بدون اسم التطبيق
        r'حصة\s+(?:فيه|فيها)\s+[،,]',           # حصة بدون وضوح
        r'واتسابت?\s+(?:الذي|المرتبط)\s+',       # واتساب بدون اسم التطبيق
    ]
    for pat in empty_entity_patterns:
        if re.search(pat, body):
            return False, "اسم كيان محذوف — فتحة فارغة في النص"

    # ── فحص 5: جمل ناقصة في نهاية المحتوى ──
    broken_patterns = [
        r'\s[a-zA-Z]\s*$',            # حرف إنجليزي وحيد في النهاية
        r'\s[أ-ي]\s*[.،]$',            # حرف عربي وحيد + نقطة/فاصلة
        r'\sفي\s*[.،]\s*$',          # "في." أو "في،" في النهاية
        r'\sمن\s*[.،]\s*$',          # "من." في النهاية
        r'\sإلى\s*[.،]\s*$',         # "إلى." في النهاية
        r'\sعلى\s*[.،]\s*$',         # "على." في النهاية
        r'\sفي\s+ال[.،]\s*$',        # "في ال." في النهاية
        r'\sأن\s+تم\s+[.،]\s*$',    # "أن تم." في النهاية بدون تفصيل
        r'\sوقد\s+تم\s+[.،]\s*$',   # "وقد تم." بدون تفصيل
    ]
    for pat in broken_patterns:
        if re.search(pat, body):
            return False, "جملة ناقصة في نهاية المحتوى"

    # ── فحص 6: تكرار مفرط لنفس العبارة ──
    words_body = re.findall(r'[\w\u0600-\u06FF]+', body)
    if len(words_body) >= 10:
        for i in range(len(words_body) - 3):
            phrase = " ".join(words_body[i:i+4])
            count = body.lower().count(phrase.lower())
            if count >= 3:
                return False, f"تكرار مفرط: '{phrase}' تكررت {count} مرات"

    # ── فحص 7: المحتوى المبهم بدون تفاصيل ──
    has_specifics = (
        re.search(r'[\$][\d,]+', combined) or       # مبالغ "$48M"
        re.search(r'\d{2,}', combined) or          # أرقام (تواريخ، كميات)
        re.search(r'(\d+\.\d+)%', combined) or   # نسب مئوية
        any(ent in combined for ent in ['Bitcoin', 'Ethereum', 'SEC', 'Binance', 'BTC', 'ETH', 'SOL', 'SUI'])
    )
    if not has_specifics:
        vague_words = ["شيء", "أمر", "عمل", "تطور", "حدث", "أحداث"]
        if sum(1 for w in vague_words if w in combined) >= 2:
            return False, "محتوى مبهم بدون تفاصيل محددة"

    return True, ""


def _clean_json_response(text: str) -> str:
    """تنظيف استجابة الـ AI — استخراج JSON فقط"""
    # إزالة markdown code blocks إن وُجدت
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()
    # محاولة العثور على JSON في النص
    match = re.search(r'\{[^{}]*"headline"[^{}]*"body"[^{}]*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    return text


def _parse_ai_response(raw: str) -> Optional[Tuple[str, str]]:
    """
    استخراج headline و body من استجابة الـ AI.
    يُرجع (headline, body) أو None إذا فشل.
    """
    raw = _clean_json_response(raw)
    try:
        data = json.loads(raw)
        headline = str(data.get("headline", "")).strip()
        body = str(data.get("body", "")).strip()
        if headline and body:
            return headline, body
    except json.JSONDecodeError:
        log.warning(f"فشل تحليل JSON: {raw[:100]}")
    return None


# ═══════════════════════════════════════════════════════════════
# 🤖 مزوّد 1: Google Gemini
# ═══════════════════════════════════════════════════════════════

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

async def _translate_with_gemini(prompt: str) -> Optional[Tuple[str, str]]:
    """ترجمة عبر Google Gemini — المزوّد الأساسي"""
    api_key = cfg.GEMINI_API_KEY
    if not api_key:
        return None

    for model in GEMINI_MODELS:
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 1024,
                    "responseMimeType": "application/json",
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        result = _parse_ai_response(text)
                        if result:
                            log.info(f"✅ Gemini ({model}) نجحت")
                            return result
                    elif resp.status == 404:
                        # النموذج غير موجود — نجّرب التالي
                        log.debug(f"⚠️ Gemini: النموذج {model} غير متاح")
                        continue
                    else:
                        log.warning(f"⚠️ Gemini ({model}) خطأ HTTP: {resp.status}")
                        continue
        except asyncio.TimeoutError:
            log.warning(f"⚠️ Gemini ({model}) انتهت المهلة")
            continue
        except Exception as e:
            log.warning(f"⚠️ Gemini ({model}) فشل: {e}")
            continue

    return None


# ═══════════════════════════════════════════════════════════════
# 🤖 مزوّد 2: Groq
# ═══════════════════════════════════════════════════════════════

GROQ_MODEL = "llama-3.3-70b-versatile"

async def _translate_with_groq(prompt: str) -> Optional[Tuple[str, str]]:
    """ترجمة عبر Groq — بديل أول"""
    api_key = cfg.GROQ_API_KEY
    if not api_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "أنت محرر أخبار. أجب بـ JSON فقط: {\"headline\": \"...\", \"body\": \"...\"}"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"]
                    result = _parse_ai_response(text)
                    if result:
                        log.info(f"✅ Groq ({GROQ_MODEL}) نجحت")
                        return result
                else:
                    error_text = await resp.text()
                    log.warning(f"⚠️ Groq خطأ HTTP {resp.status}: {error_text[:200]}")
    except asyncio.TimeoutError:
        log.warning("⚠️ Groq انتهت المهلة")
    except Exception as e:
        log.warning(f"⚠️ Groq فشل: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# 🤖 مزوّد 3: OpenRouter
# ═══════════════════════════════════════════════════════════════

OPENROUTER_MODEL = "qwen/qwen-2.5-72b-instruct"

async def _translate_with_openrouter(prompt: str) -> Optional[Tuple[str, str]]:
    """ترجمة عبر OpenRouter — بديل ثانٍ"""
    api_key = cfg.OPENROUTER_API_KEY
    if not api_key:
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "أنت محرر أخبار. أجب بـ JSON فقط: {\"headline\": \"...\", \"body\": \"...\"}"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/newscrypto1m",
        "X-Title": "Whale News Bot v3",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"]
                    result = _parse_ai_response(text)
                    if result:
                        log.info(f"✅ OpenRouter ({OPENROUTER_MODEL}) نجحت")
                        return result
                else:
                    error_text = await resp.text()
                    log.warning(f"⚠️ OpenRouter خطأ HTTP {resp.status}: {error_text[:200]}")
    except asyncio.TimeoutError:
        log.warning("⚠️ OpenRouter انتهت المهلة")
    except Exception as e:
        log.warning(f"⚠️ OpenRouter فشل: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# 🌐 بديل 4: Google Translate (مجاني)
# ═══════════════════════════════════════════════════════════════

async def _google_translate(text: str, entity_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    ترجمة مجانية عبر Google Translate مع حماية الكيانات.
    يستخدم translate.googleapis.com (بدون مفتاح API).
    """
    title = (text[:200] if text else "").strip()
    if not title:
        return None

    # حماية الكيانات قبل الترجمة
    protected_title = _protect_entities(title, entity_map)

    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "ar",
        "dt": "t",
        "q": protected_title,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # استخراج النص المترجم
                    translated_parts = []
                    for part in data[0]:
                        if part[0]:
                            translated_parts.append(part[0])
                    translated = "".join(translated_parts)
                    # استعادة الكيانات
                    translated = _restore_entities(translated, entity_map)
                    if translated and len(translated.strip()) >= 15:
                        log.info("✅ Google Translate نجحت")
                        return translated.strip(), translated.strip()
                else:
                    log.warning(f"⚠️ Google Translate خطأ HTTP: {resp.status}")
    except asyncio.TimeoutError:
        log.warning("⚠️ Google Translate انتهت المهلة")
    except Exception as e:
        log.warning(f"⚠️ Google Translate فشل: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# 🔄 المحاولة مع إعادة المحاولة
# ═══════════════════════════════════════════════════════════════

async def _retry_async(func, *args, max_retries: int = 2, delay: float = 1.0, **kwargs):
    """محاولة مع إعادة المحاولة مع تأخير تصاعدي"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await func(*args, **kwargs)
            if result is not None:
                return result
        except Exception as e:
            last_error = e
            log.debug(f"🔄 محاولة {attempt + 1}/{max_retries + 1} فشلت: {e}")
            if attempt < max_retries:
                await asyncio.sleep(delay * (attempt + 1))
    return None


# ═══════════════════════════════════════════════════════════════
# 🔗 سلسلة الترجمة الرئيسية
# ═══════════════════════════════════════════════════════════════

async def _rewrite_with_ai(item: NewsItem, entity_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """
    محاولة الترجمة عبر سلسلة المزوّدين.
    يُرجع (headline, body) أو None.
    """
    # بناء الـ prompt
    prompt = _build_prompt(item)

    # حماية الكيانات في الـ prompt
    protected_prompt = _protect_entities(prompt, entity_map)

    # 1️⃣ Primary: Gemini
    try:
        result = await GEMINI_CB.call(
            _retry_async, _translate_with_gemini, protected_prompt, max_retries=1
        )
        if result:
            headline, body = result
            headline = _restore_entities(headline, entity_map)
            body = _restore_entities(body, entity_map)
            # طبقة التنظيف بعد الترجمة
            headline, body = _clean_translated_text(headline, body)
            ok, reason = _check_quality(headline, body)
            if ok:
                return headline, body
            log.warning(f"⚠️ Gemini نتيجة غير مقبولة: {reason}")
    except RuntimeError as e:
        log.warning(f"⚠️ Gemini Circuit Breaker: {e}")

    # 2️⃣ Fallback 1: Groq
    try:
        result = await GROQ_CB.call(
            _retry_async, _translate_with_groq, protected_prompt, max_retries=1
        )
        if result:
            headline, body = result
            headline = _restore_entities(headline, entity_map)
            body = _restore_entities(body, entity_map)
            # طبقة التنظيف بعد الترجمة
            headline, body = _clean_translated_text(headline, body)
            ok, reason = _check_quality(headline, body)
            if ok:
                return headline, body
            log.warning(f"⚠️ Groq نتيجة غير مقبولة: {reason}")
    except RuntimeError as e:
        log.warning(f"⚠️ Groq Circuit Breaker: {e}")

    # 3️⃣ Fallback 2: OpenRouter
    try:
        result = await OPENROUTER_CB.call(
            _retry_async, _translate_with_openrouter, protected_prompt, max_retries=1
        )
        if result:
            headline, body = result
            headline = _restore_entities(headline, entity_map)
            body = _restore_entities(body, entity_map)
            # طبقة التنظيف بعد الترجمة
            headline, body = _clean_translated_text(headline, body)
            ok, reason = _check_quality(headline, body)
            if ok:
                return headline, body
            log.warning(f"⚠️ OpenRouter نتيجة غير مقبولة: {reason}")
    except RuntimeError as e:
        log.warning(f"⚠️ OpenRouter Circuit Breaker: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# 📰 الدالة الرئيسية
# ═══════════════════════════════════════════════════════════════

async def rewrite_news(item: NewsItem) -> NewsItem:
    """
    إعادة كتابة الخبر بالعربية بأسلوب صحفي.

    يأخذ NewsItem مع clean_title, clean_summary, facts, news_type
    يُرجع نفس العنصر مع title_ar و summary_ar مملوءة.

    سلسلة الترجمة:
    1. Gemini (primary)
    2. Groq (fallback 1)
    3. OpenRouter (fallback 2)
    4. Google Translate (fallback 3)
    """
    start = time.time()

    # --- التحقق من صحة المدخلات ---
    title = item.clean_title or item.title
    summary = item.clean_summary or item.summary
    if not title or len(title.strip()) < 10:
        log.debug("⏭️ تخطي: العنوان فارغ أو قصير جداً")
        return item

    log.info(f"✍️ إعادة صياغة: {title[:60]}...")

    # --- بناء خريطة حماية الكيانات ---
    entity_map = _build_entity_map(item)

    # --- محاولة الترجمة عبر AI ---
    result = await _rewrite_with_ai(item, entity_map)

    if result:
        headline, body = result
        item.title_ar = headline
        item.summary_ar = body
        elapsed = time.time() - start
        log.info(
            f"✅ صياغة ناجحة ({elapsed:.1f}s) — "
            f"عنوان: {headline[:40]}..."
        )
        return item

    # --- Fallback: Google Translate (مجاني) ---
    log.info("🔄 fallback: محاولة Google Translate...")
    try:
        translated = await TRANSLATE_CB.call(
            _google_translate, summary, entity_map
        )
        if translated:
            headline, body = translated
            # طبقة التنظيف بعد الترجمة — حتى لـ Google Translate
            headline, body = _clean_translated_text(headline, body)
            item.title_ar = headline
            item.summary_ar = body
            elapsed = time.time() - start
            log.info(f"✅ ترجمة Google نجحت ({elapsed:.1f}s)")
            return item
    except RuntimeError as e:
        log.warning(f"⚠️ Translate Circuit Breaker: {e}")

    # --- كل شيء فشل ---
    elapsed = time.time() - start
    log.error(
        f"❌ فشلت كل محاولات الصياغة ({elapsed:.1f}s) — "
        f"العنوان: {title[:60]}"
    )
    return item


# ═══════════════════════════════════════════════════════════════
# 🧪 صياغة مجموعة من الأخبار
# ═══════════════════════════════════════════════════════════════

async def rewrite_batch(items: List[NewsItem]) -> List[NewsItem]:
    """
    صياغة مجموعة من الأخبار بالتوازي (مع تحديد أقصى).
    """
    if not items:
        return items

    # تحديد أقصى عدد من المهام المتوازية
    semaphore = asyncio.Semaphore(3)

    async def _rewrite_one(item: NewsItem) -> NewsItem:
        async with semaphore:
            await asyncio.sleep(0.2)  # فاصل صغير بين الطلبات
            return await rewrite_news(item)

    results = await asyncio.gather(*[_rewrite_one(item) for item in items], return_exceptions=True)

    rewritten = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error(f"❌ خطأ في صياغة الخبر {i}: {result}")
            rewritten.append(items[i])
        else:
            rewritten.append(result)

    success_count = sum(1 for item in rewritten if item.title_ar)
    log.info(f"📊 صياغة المجموعة: {success_count}/{len(items)} نجحت")
    return rewritten
