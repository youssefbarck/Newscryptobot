"""
🌐 الترجمة من الإنجليزية للعربية مع حماية الأسماء والتوكنات
يدعم: Google Translate (أساسي) + MyMemory (احتياطي عند 429)
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
    """
    if not entities:
        return translated

    # 1) الاستبدال المباشر (الأطول أولاً لتفادي تعارض [[10]] مع [[1]])
    for placeholder in sorted(entities.keys(), key=lambda p: -int(p[2:-2])):
        original = entities[placeholder]
        translated = translated.replace(placeholder, original)

    # 2) تنظيف أي بقايا placeholder لم تُستبدل
    remaining_placeholders = _PH_REGEX.findall(translated)
    if remaining_placeholders:
        log.warning(f"⚠️ Leaked placeholders: {remaining_placeholders}")
        translated = _PH_REGEX.sub("", translated)
        translated = re.sub(r'\s{2,}', ' ', translated).strip()
        translated = re.sub(r'\s+([.،,!؟?])', r'\1', translated)

    return translated


def _split_chunks(text: str, max_chunk: int) -> list:
    """تقسيم النص الطويل إلى أجزاء عند الجمل"""
    if len(text) <= max_chunk:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
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
    return chunks


# ═══════════════════════════════════════════════════════════
# MyMemory API — بديل مجاني (لا يحتاج مفتاح)
# ═══════════════════════════════════════════════════════════
async def _mymemory_translate(text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
    """ترجمة عبر MyMemory API"""
    if not text or not text.strip():
        return None

    chunks = _split_chunks(text, 500)

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            translated_chunks = []
            for chunk in chunks:
                if not chunk.strip():
                    continue
                url = "https://api.mymemory.translated.net/get"
                params = {
                    "q": chunk,
                    "langpair": f"{source_lang}|{target_lang}",
                }
                headers = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0)"}
                try:
                    async with session.get(url, params=params, headers=headers) as resp:
                        if resp.status != 200:
                            log.warning(f"🌐 MyMemory HTTP {resp.status}")
                            return None
                        data = await resp.json(content_type=None)
                        translated_text = data.get("responseData", {}).get("translatedText", "")
                        if translated_text:
                            translated_chunks.append(translated_text)
                        else:
                            log.warning(f"🌐 MyMemory empty: {str(data)[:200]}")
                            return None
                except Exception as e:
                    log.warning(f"🌐 MyMemory chunk error: {e}")
                    return None
                await asyncio.sleep(0.5)

            return " ".join(translated_chunks)
    except Exception as e:
        log.warning(f"🌐 MyMemory error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# Google Translate (أساسي) + MyMemory (احتياطي)
# ═══════════════════════════════════════════════════════════
async def google_translate(text: str, source_lang: str = "en", target_lang: str = "ar") -> Optional[str]:
    """
    ترجمة عبر Google Translate مع احتياطي MyMemory عند الحجب (429).
    """
    if not text or not text.strip():
        return None

    # حماية الكيانات
    protected = _build_protected_entities(text)
    text_to_translate = protected["text"]
    chunks = _split_chunks(text_to_translate, 1800)

    # ═══════════════════════════════════════════════
    # المحاولة 1: Google Translate
    # ═══════════════════════════════════════════════
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            translated_chunks = []
            google_ok = True
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
                        if resp.status == 429:
                            log.warning(f"🌐 Google 429 — switching to MyMemory")
                            google_ok = False
                            break
                        if resp.status != 200:
                            log.warning(f"🌐 Translate HTTP {resp.status}")
                            google_ok = False
                            break
                        data = await resp.json(content_type=None)
                        if isinstance(data, list) and data and isinstance(data[0], list):
                            translated_text = "".join(
                                sentence[0] for sentence in data[0] if sentence and sentence[0]
                            )
                            translated_chunks.append(translated_text)
                        else:
                            log.warning(f"🌐 Unexpected response: {str(data)[:200]}")
                            google_ok = False
                            break
                except Exception as e:
                    log.warning(f"🌐 Translate chunk error: {e}")
                    google_ok = False
                    break
                await asyncio.sleep(0.3)

            if google_ok and translated_chunks:
                translated = " ".join(translated_chunks)
                return _restore_entities(translated, protected["entities"])
    except Exception as e:
        log.warning(f"🌐 Google Translate error: {e}")

    # ═══════════════════════════════════════════════
    # المحاولة 2: MyMemory (بديل مجاني)
    # ═══════════════════════════════════════════════
    log.info(f"🌐 Trying MyMemory fallback...")
    full_text = " ".join(chunks)
    result = await _mymemory_translate(full_text, source_lang, target_lang)
    if result:
        return _restore_entities(result, protected["entities"])

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
