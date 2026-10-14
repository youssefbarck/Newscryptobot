# -*- coding: utf-8 -*-
"""تعريب العناوين الإنجليزية — سلسلة محاولات مع تراجع آمن إلى النص الأصلي"""
import logging
import re

import requests

from .categories import COIN_AR
from .config import HTTP_HEADERS

log = logging.getLogger("crypto-bot")

_CACHE: dict[str, str | None] = {}


def _looks_arabic(s: str) -> bool:
    arabic = sum(1 for c in s if "\u0600" <= c <= "\u06FF")
    return arabic >= max(1, len(s) // 4)


def _try_google(text: str) -> str | None:
    """ترجمة Google عبر نقطة نهاية dict-chrome-ex (سريعة وسخية بدون مفتاح)."""
    try:
        r = requests.get(
            "https://clients5.google.com/translate_a/t",
            params={"client": "dict-chrome-ex", "sl": "en", "tl": "ar", "q": text},
            headers=HTTP_HEADERS, timeout=15)
        if r.ok:
            data = r.json()
            parts = []
            for seg in (data if isinstance(data, list) else []):
                if isinstance(seg, str):
                    parts.append(seg)
                elif isinstance(seg, list) and seg and isinstance(seg[0], str):
                    parts.append(seg[0])
            out = re.sub(r"\s+", " ", "".join(parts)).strip()
            if out and _looks_arabic(out):
                return out
    except Exception:
        pass
    # خطة ثانية: نقطة النهاية التقليدية gtx
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "ar", "dt": "t", "q": text},
            headers=HTTP_HEADERS, timeout=15)
        if r.ok:
            data = r.json()
            parts = [seg[0] for seg in (data[0] or []) if seg and seg[0]]
            out = re.sub(r"\s+", " ", "".join(parts)).strip()
            if out and _looks_arabic(out):
                return out
    except Exception:
        pass
    return None


def _try_mymemory(text: str) -> str | None:
    """خطة بديلة: MyMemory API المجانية."""
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"langpair": "en|ar", "q": text[:500]},
            headers=HTTP_HEADERS, timeout=15)
        if r.ok:
            out = (r.json() or {}).get("responseData", {}).get("translatedText", "")
            out = (out or "").strip()
            if out and _looks_arabic(out) and "MYMEMORY WARNING" not in out.upper():
                return re.sub(r"\s+", " ", out)
    except Exception:
        pass
    return None


def _polish(text: str) -> str:
    """لمسات أخيرة: أسماء العملات بالعربية وتنظيف الفراغات."""
    for sym, ar in COIN_AR.items():
        text = re.sub(rf"\b{re.escape(sym)}\b", ar, text, flags=re.I)
    text = text.replace("دولار أمريكي", "دولار").replace("  ", " ")
    return text.strip()


def to_arabic(text: str) -> str | None:
    """يُرجع العنوان معرّبًا أو None إن فشلت كل المحاولات."""
    if not text or not text.strip():
        return None
    key = text.strip()
    if key in _CACHE:
        return _CACHE[key]

    result = _try_google(key) or _try_mymemory(key)
    if result:
        result = _polish(result)
    _CACHE[key] = result
    if not result:
        log.warning("تعذر تعريب: %s…", key[:60])
    return result
