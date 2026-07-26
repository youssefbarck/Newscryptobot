"""
🌐 الترجمة من الإنجليزية للعربية مع حماية الأسماء والتوكنات
"""

import re
import asyncio
import urllib.parse
import aiohttp
from typing import Optional

from config import PROTECTED_NAMES, TICKER_PATTERN, log


# ═══════════════════════════════════════════════════════════
# تجميع الـ Entities التي يجب حمايتها من الترجمة
# ═══════════════════════════════════════════════════════════
def _build_protected_entities(text: str) -> dict:
    """
    اكتشاف كل الكيانات المحمية في النص وإرجاع:
      {placeholder: original_text}
    """
    entities = {}
    counter = 0

    def _add(match_str: str) -> str:
        nonlocal counter
        if not match_str:
            return match_str
        key = f"§{counter}§"
        entities[key] = match_str
        counter += 1
        return key

    # 1) الأسماء المحمية (Michael Saylor, CZ, Vitalik Buterin...)
    # نرتبها بالطول التنازلي حتى نلتقط الأطول أولاً (Vitalik Buterin قبل Vitalik)
    sorted_names = sorted(PROTECTED_NAMES, key=len, reverse=True)
    for name in sorted_names:
        pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
        text = pattern.sub(lambda m: _add(m.group(0)), text)

    # 2) التوكنات (BTC, ETH, SOL...)
    text = re.sub(TICKER_PATTERN, lambda m: _add(m.group(0)), text)

    # 3) الأرقام والنسب المئوية والأسعار ($100K, 25%, 1.5B...)
    text = re.sub(r'\$\d[\d,.]*\s*(?:K|M|B|T|million|billion)?', lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d[\d,.]*\s*(?:K|M|B|T|million|billion)\b', lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d[\d,.]*\s*%', lambda m: _add(m.group(0)), text)

    # 4) الروابط
    text = re.sub(r'https?://\S+', lambda m: _add(m.group(0)), text)

    # 5) الهاشتاجات الإنجليزية (#Bitcoin, #ETH)
    text = re.sub(r'#\w+', lambda m: _add(m.group(0)), text)

    return {"text": text, "entities": entities}


def _restore_entities(translated: str, entities: dict) -> str:
    """إعادة الكيانات المحمية إلى مكانها في النص المترجم"""
    # نرتب الـ placeholders بالطول التنازلي حتى لا يحدث تعارض (§10§ قبل §1§)
    for placeholder in sorted(entities.keys(), key=len, reverse=True):
        original = entities[placeholder]
        translated = translated.replace(placeholder, original)
        # أحياناً Google Translate يضيف مسافات حول الـ placeholder
        translated = translated.replace(placeholder.replace("§", " § "), original)
        translated = translated.replace(placeholder.replace("§", "§ "), original)
        translated = translated.replace(placeholder.replace("§", " §"), original)
    return translated


# ═══════════════════════════════════════════════════════════
# Google Translate (مجاني عبر web API)
# ═══════════════════════════════════════════════════════════
async def google_translate(text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
    """
    ترجمة عبر Google Translate web API.
    يرجع النص المترجم أو None عند الفشل.
    """
    if not text or not text.strip():
        return None

    # حماية الكيانات
    protected = _build_protected_entities(text)
    text_to_translate = protected["text"]

    # تقسيم النص إذا كان طويلاً (Google limit ~2000 حرف لكل طلب)
    max_chunk = 1800
    chunks = []
    if len(text_to_translate) <= max_chunk:
        chunks = [text_to_translate]
    else:
        # تقسيم عند حدود الجمل
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
                        # الرد: [[[جملة مترجمة, جملة أصلية, ...], ...], ...]
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
                await asyncio.sleep(0.3)  # تجنب الحظر

            translated = " ".join(translated_chunks)
            # إعادة الكيانات
            return _restore_entities(translated, protected["entities"])
    except Exception as e:
        log.warning(f"🌐 Translate error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# ترجمة كائن الخبر
# ═══════════════════════════════════════════════════════════
async def translate_news_item(item) -> bool:
    """ترجمة عنوان الخبر وملخصه — يُعدّل الكائن مباشرة"""
    try:
        # ترجمة العنوان
        title_ar = await google_translate(item.title)
        if not title_ar:
            return False
        item.title_ar = title_ar.strip()

        # ترجمة الملخص (إن وُجد)
        if item.summary:
            summary_ar = await google_translate(item.summary)
            item.summary_ar = (summary_ar or "").strip()
        else:
            item.summary_ar = ""

        return True
    except Exception as e:
        log.warning(f"🌐 Translate item error: {e}")
        return False
