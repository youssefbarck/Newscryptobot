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


def _build_facts_summary(item: NewsItem) -> str:
    """بناء ملخص الحقائق للـ prompt"""
    if not item.facts:
        return "لا توجد حقائق مستخرجة"

    parts: List[str] = []
    if item.facts.main_entities:
        parts.append(f"الكيانات: {', '.join(item.facts.main_entities)}")
    if item.facts.coins:
        parts.append(f"العملات: {', '.join(item.facts.coins)}")
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
        f"القواعد:\n"
        f"1. اكتب فقط: عنوان + فقرة واحدة مختصرة (3-5 جمل)\n"
        f"2. لا تضف تعليقات أو تحليلات شخصية\n"
        f"3. لا تذكر اسم المصدر في النص\n"
        f"4. احتفظ بأسماء الأشخاص والشركات والعملات كما هي (لا تترجمها)\n"
        f"5. لا تضيف هاشتاغ أو إيموجي\n"
        f'6. أعد النتيجة كـ JSON فقط:\n{{"headline": "...", "body": "..."}}'
    )
    return prompt


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
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text)
    for word in words:
        if word.upper() not in ALLOWED_ENGLISH_TERMS:
            return True
    return False


def _check_quality(headline: str, body: str) -> Tuple[bool, str]:
    """
    فحص جودة النتيجة.
    يُرجع (مقبول، سبب_الرفض)
    """
    if not headline or len(headline.strip()) < 15:
        return False, f"العنوان قصير جداً ({len(headline) if headline else 0} حرف)"
    if not body or len(body.strip()) < 50:
        return False, f"المحتوى قصير جداً ({len(body) if body else 0} حرف)"
    combined = headline + " " + body
    ratio = _arabic_char_ratio(combined)
    if ratio < 0.40:
        return False, f"نسبة العربية منخفضة ({ratio:.0%})"
    if _has_unwanted_english(combined):
        return False, "يوجد كلمات إنجليزية غير مسموحة"
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
