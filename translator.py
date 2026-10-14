# -*- coding: utf-8 -*-
"""🌐 التعريب — Google مع حماية الكيانات ثم MyMemory احتياطيًا.

من ملفك القديم: نحمي الأسماء (Saylor, BlackRock...) والتوكنات (BTC...)
والأسعار ($100K, 5%) والروابط والهاشتاجات — كلها تُستبدل بـ [[0]], [[1]]…
قبل الترجمة ثم تُعاد بعدها، فلا تتشوه الأسماء والأرقام أبدًا.
"""
import asyncio
import html
import logging
import re

import aiohttp

from categories import COIN_AR
from config import BROWSER_UA, PROTECTED_NAMES, TICKER_PATTERN

log = logging.getLogger("NewsBot")

_PH_OPEN, _PH_CLOSE = "[[", "]]"
_PH_REGEX = re.compile(r"\[\[\s*(\d+)\s*\]\]")

_CACHE: dict[str, str | None] = {}


def _build_protected_entities(text: str) -> dict:
    """استبدال الكيانات المحمية بـ [[0]], [[1]], ... قبل الترجمة."""
    entities: dict[str, str] = {}
    counter = [0]

    def _add(match_str: str) -> str:
        key = f"{_PH_OPEN}{counter[0]}{_PH_CLOSE}"
        entities[key] = match_str
        counter[0] += 1
        return key

    # 1) الأسماء المحمية (الأطول أولًا حتى لا تُلتقط أجزاء منها)
    for name in sorted(PROTECTED_NAMES, key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(name) + r"\b",
                      lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    # 2) التوكنات
    text = re.sub(TICKER_PATTERN, lambda m: _add(m.group(0)), text)
    # 3) الأسعار والنسب — الكلمات الطويلة أولًا حتى لا تُلتقط حرف M فقط من million
    text = re.sub(r"\$\d[\d,.]*\s*(?:million|billion|trillion|thousand|[KMBT])?\b",
                  lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d[\d,.]*\s*(?:million|billion|thousand|[KMBT])\b",
                  lambda m: _add(m.group(0)), text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d[\d,.]*\s*%", lambda m: _add(m.group(0)), text)
    # 4) الروابط والهاشتاجات
    text = re.sub(r"https?://\S+", lambda m: _add(m.group(0)), text)
    text = re.sub(r"#\w+", lambda m: _add(m.group(0)), text)

    return {"text": text, "entities": entities}


def _restore_entities(translated: str, entities: dict) -> str:
    """إعادة الكيانات المحمية بعد الترجمة مع تنظيف الترجمات الركيكة."""
    if not entities:
        return translated

    # 1) الاستبدال المباشر
    for placeholder in sorted(entities.keys(), key=lambda p: -int(p[2:-2])):
        translated = translated.replace(placeholder, entities[placeholder])

    # 2) تنويعات بمسافات (خدمات الترجمة قد تشوّه الشكل بسبب RTL)
    for placeholder in sorted(entities.keys(), key=lambda p: -int(p[2:-2])):
        num = placeholder[2:-2]
        original = entities[placeholder]
        for variant in (f"[[ {num}]]", f"[[ {num} ]]", f"[[{num} ]]",
                        f"[[{num}] ]", f"[ [{num}]]"):
            if variant in translated:
                translated = translated.replace(variant, original)
                break

    # 3) بقايا placeholders تُحذف
    translated = _PH_REGEX.sub("", translated)
    # 4) كيانات HTML
    translated = html.unescape(translated)

    # 5) تنظيف ترجمات ركيكة (من الملف القديم)
    _CLUNKY = [
        (r"يؤدي الارتفاع إلى ارتفاع", "ارتفع"),
        (r"يؤدي إلى ارتفاع", "رفع"),
        (r"مع ارتفاع", "وارتفعت"),
        (r"حيث إن", "حيث"),
        (r"في حين أن", "بينما"),
        (r"على الرغم من أن", "رغم"),
        (r"من الممكن أن", "قد"),
        (r"في هذا السياق", ""),
        (r"من الجدير بالذكر", ""),
        (r"تجدر الإشارة إلى", ""),
        (r"يواصل الارتفاع", "يواصل الصعود"),
        (r"بشكل صحيح", ""),
    ]
    for pat, repl in _CLUNKY:
        translated = re.sub(pat, repl, translated)

    # 6) لمسات أخيرة: أسماء العملات بالعربية
    for sym, ar in COIN_AR.items():
        translated = re.sub(rf"\b{re.escape(sym)}\b", ar, translated, flags=re.I)
    translated = translated.replace("دولار أمريكي", "دولار")

    translated = re.sub(r"\s{2,}", " ", translated).strip()
    translated = re.sub(r"\s+([.,!,?،؟])", r"\1", translated)
    return translated


def _looks_arabic(s: str) -> bool:
    arabic = sum(1 for c in s if "\u0600" <= c <= "\u06FF")
    return arabic >= max(1, len(s) // 4)


async def _google_clients5(session, text: str) -> str | None:
    """نقطة نهاية dict-chrome-ex — سريعة و سخية بدون مفتاح."""
    try:
        async with session.get(
                "https://clients5.google.com/translate_a/t",
                params={"client": "dict-chrome-ex", "sl": "en", "tl": "ar", "q": text},
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            parts = []
            for seg in (data if isinstance(data, list) else []):
                if isinstance(seg, str):
                    parts.append(seg)
                elif isinstance(seg, list) and seg and isinstance(seg[0], str):
                    parts.append(seg[0])
            out = re.sub(r"\s+", " ", "".join(parts)).strip()
            return out if out and _looks_arabic(out) else None
    except Exception:
        return None


async def _google_gtx(session, text: str) -> str | None:
    """نقطة النهاية التقليدية gtx."""
    try:
        async with session.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text},
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            parts = [seg[0] for seg in ((data[0] or []) if isinstance(data, list) else [])
                     if seg and seg[0]]
            out = re.sub(r"\s+", " ", "".join(parts)).strip()
            return out if out and _looks_arabic(out) else None
    except Exception:
        return None


async def _mymemory(session, text: str) -> str | None:
    """خطة بديلة: MyMemory API المجانية."""
    try:
        async with session.get(
                "https://api.mymemory.translated.net/get",
                params={"langpair": "en|ar", "q": text[:500]},
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            out = ((await resp.json(content_type=None)).get("responseData") or {}).get("translatedText", "")
            out = (out or "").strip()
            if out and _looks_arabic(out) and "MYMEMORY WARNING" not in out.upper():
                return re.sub(r"\s+", " ", out)
    except Exception:
        pass
    return None


async def google_translate(text: str) -> str | None:
    """تعريب نص واحد: حماية الكيانات ← ثلاث خدمات ← استعادة وتنظيف."""
    if not text or not text.strip():
        return None
    key = text.strip()
    if key in _CACHE:
        return _CACHE[key]

    protected = _build_protected_entities(key)
    try:
        async with aiohttp.ClientSession() as session:
            out = (await _google_clients5(session, protected["text"])
                   or await _google_gtx(session, protected["text"])
                   or await _mymemory(session, protected["text"]))
    except Exception as exc:
        log.warning("🌐 خطأ ترجمة: %s", exc)
        out = None

    result = _restore_entities(out, protected["entities"]) if out else None
    _CACHE[key] = result
    if not result:
        log.warning("🌐 تعذر تعريب: %s…", key[:60])
    return result
