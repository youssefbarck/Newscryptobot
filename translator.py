"""
🌐 الترجمة من الإنجليزية للعربية مع حماية الأسماء والتوكنات
"""

import re
import asyncio
import aiohttp
from typing import Optional

from config import PROTECTED_NAMES, TICKER_PATTERN, log


# ═══════════════════════════════════════════════════════════
#_placeholder format: [[N]]  (لا تترجمه Google لأنه يبدو كود)
# ملاحظة: كان السابق §N§ لكن § تُترجم لـ "الفقرة"!
# ═══════════════════════════════════════════════════════════
_PH_OPEN = "[["
_PH_CLOSE = "]]"
_PH_REGEX = re.compile(r'\[\[(\d+)\]\]')


def _build_protected_entities(text: str) -> dict:
    """
    استبدال كل الكيانات المحمية بـ [[0]], [[1]], ...
    يرجع {"text": ..., "entities": {"[[0]]": "Ethereum", ...}}
    """
    entities = {}
    counter = [0]  # closure-friendly

    def _add(match_str: str) -> str:
        if not match_str:
            return match_str
        key = f"{_PH_OPEN}{counter[0]}{_PH_CLOSE}"
        entities[key] = match_str
        counter[0] += 1
        return key

    # 1) الأسماء المحمية (الأطول أولاً)
    sorted_names = sorted(PROTECTED_NAMES, key=len, reverse=True)
    for name in sorted_names:
        pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
        text = pattern.sub(lambda m: _add(m.group(0)), text)

    # 2) التوكنات (BTC, ETH...)
    text = re.sub(TICKER_PATTERN, lambda m: _add(m.group(0)), text)

    # 3) الأسعار والنسب
    text = re.sub(r'\$\d[\d,.]*\s*(?:K|M|B|T|million|billion)?',
                  lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d[\d,.]*\s*(?:K|M|B|T|million|billion)\b',
                  lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d[\d,.]*\s*%', lambda m: _add(m.group(0)), text)

    # 4) الروابط
    text = re.sub(r'https?://\S+', lambda m: _add(m.group(0)), text)

    # 5) الهاشتاجات
    text = re.sub(r'#\w+', lambda m: _add(m.group(0)), text)

    return {"text": text, "entities": entities}


def _restore_entities(translated: str, entities: dict) -> str:
    """
    إعادة الكيانات المحمية إلى مكانها.
    Google Translate يحافظ عادةً على [[N]] كما هو.
    نتعامل أيضاً مع الحالات الشاذة (مسافات إضافية، إزاحة).
    """
    if not entities:
        return translated

    # 1) الاستبدال المباشر (الأطول أولاً لتفادي تعارض [[10]] مع [[1]])
    for placeholder in sorted(entities.keys(), key=lambda p: -int(p[2:-2])):
        original = entities[placeholder]
        translated = translated.replace(placeholder, original)

    # 2) تنظيف أي بقايا placeholder لم تُستبدل
    #    (قد يحدث لو Google حذف الرقم أو عدّله)
    #    نحاول إيجاد أي [[digit]] متبقي ونستبدله بأقرب entity غير مستخدم
    remaining_placeholders = _PH_REGEX.findall(translated)
    if remaining_placeholders:
        log.warning(f"⚠️ Leaked placeholders: {remaining_placeholders}")
        # إزالة أي placeholder متبقي (نُبقي النص نظيفاً)
        translated = _PH_REGEX.sub("", translated)
        # تنظيف مسافات مزدوجة ناتجة
        translated = re.sub(r'\s{2,}', ' ', translated).strip()
        translated = re.sub(r'\s+([.،,!؟?])', r'\1', translated)

    return translated


# ═══════════════════════════════════════════════════════════
# Google Translate (مجاني عبر web API)
# ═══════════════════════════════════════════════════════════
async def google_translate(text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
    """ترجمة عبر Google Translate web API مع حماية الكيانات"""
    if not text or not text.strip():
        return None

    # حماية الكيانات
    protected = _build_protected_entities(text)
    text_to_translate = protected["text"]

    # تقسيم النص الطويل
    max_chunk = 1800
    chunks = []
    if len(text_to_translate) <= max_chunk:
        chunks = [text_to_translate]
    else:
        sentences = re.split(r'(?<=[.!?])\s+', text_to_translate)
        current = ""
        for sent in sentences:
            if len(current) + len(sent) + 1 <= max_chunk:
                current = (current + " " + sent).strip()
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            translated_chunks = []
            for chunk in chunks:
                if not chunk.strip():
                    continue
                url = "https://translate.googleapis.com/translate_a/single"
                params = {
                    "client": "gtx",
                    "sl": source_lang,
                    "tl": target_lang,
                    "dt": "t",
                    "q": chunk,
                }
                headers = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0)"}
                try:
                    async with session.get(url, params=params, headers=headers) as resp:
                        if resp.status != 200:
                            log.warning(f"🌐 Translate HTTP {resp.status}")
                            return None
                        data = await resp.json(content_type=None)
                        if isinstance(data, list) and data and isinstance(data[0], list):
                            translated_text = "".join(
                                sentence[0] for sentence in data[0] if sentence and sentence[0]
                            )
                            translated_chunks.append(translated_text)
                        else:
                            log.warning(f"🌐 Unexpected response: {str(data)[:200]}")
                            return None
                except Exception as e:
                    log.warning(f"🌐 Translate chunk error: {e}")
                    return None
                await asyncio.sleep(0.3)

            translated = " ".join(translated_chunks)
            return _restore_entities(translated, protected["entities"])
    except Exception as e:
        log.warning(f"🌐 Translate error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# ترجمة كائن الخبر
# ═══════════════════════════════════════════════════════════
async def translate_news_item(item) -> bool:
    """ترجمة عنوان الخبر وملخصه"""
    try:
        title_ar = await google_translate(item.title)
        if not title_ar:
            return False
        item.title_ar = title_ar.strip()

        if item.summary:
            summary_ar = await google_translate(item.summary)
            item.summary_ar = (summary_ar or "").strip()
        else:
            item.summary_ar = ""

        return True
    except Exception as e:
        log.warning(f"🌐 Translate item error: {e}")
        return False
