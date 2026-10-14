# -*- coding: utf-8 -*-
"""🖼 نظام الصور — كل خبر يصل بصورة جذابة مرتبطة بموضوعه، بلا أي روابط.

1) صورة الخبر من RSS/CryptoPanic إن وجدت
2) وإلا: فتح صفحة الخبر واستخراج og:image الأصلية
3) وإلا: صورة بديلة أنيقة خاصة بالتصنيف من مجلد assets/
تُحمّل الصورة وتُفحص (النوع/الحجم/السلامة) ثم تُرفع كمرفق حقيقي لتيليجرام.
"""
import logging
import os
import re
from pathlib import Path

import aiohttp

from config import BROWSER_UA, REQUEST_TIMEOUT

log = logging.getLogger("NewsBot")

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# بصمات الأنواع المقبولة في sendPhoto (JPG / PNG / WEBP)
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # يُدقق أن البايتات 8-11 هي WEBP
)

_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)'
    r'["\'][^>]*content=["\']([^"\']+)["\']', re.I)
_OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
    r'(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.I)


def _sniff_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


async def download_image(session: aiohttp.ClientSession, url: str,
                         max_bytes: int = 9_500_000) -> tuple[bytes, str] | None:
    """تحميل صورة والتحقق أنها صورة حقيقية صالحة لتيليجرام — لا استثناءات."""
    if not url or not url.startswith("http"):
        return None
    try:
        async with session.get(url, headers={"User-Agent": BROWSER_UA,
                                             "Accept": "image/*,*/*;q=0.8"},
                               timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT + 10),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                log.info("🖼 صورة غير متاحة (%s): %s", resp.status, url[:90])
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "image" not in ctype and "octet-stream" not in ctype:
                log.info("🖼 ليست صورة (%s): %s", ctype or "?", url[:90])
                return None
            data = await resp.read()
        if len(data) > max_bytes:
            log.info("🖼 صورة أكبر من الحد — تجاهل: %s", url[:90])
            return None
        if len(data) < 3_000:  # أصغر من أي صورة خبر حقيقية — غالبًا صفحة خطأ
            return None
        mime = _sniff_mime(data)
        if not mime:
            log.info("🖼 نوع غير مدعوم (ليس JPG/PNG/WEBP): %s", url[:90])
            return None
        return data, mime
    except Exception as exc:
        log.info("🖼 فشل تحميل الصورة: %s", exc)
        return None


async def fetch_og_image(session: aiohttp.ClientSession, article_url: str) -> str | None:
    """فتح صفحة الخبر واستخراج صورتها الأصلية (og:image / twitter:image)."""
    if not article_url or not article_url.startswith("http"):
        return None
    try:
        async with session.get(article_url,
                               headers={"User-Agent": BROWSER_UA,
                                        "Accept": "text/html,application/xhtml+xml"},
                               timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                               allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            body = (await resp.text())[:400_000]  # وسوم meta في أعلى الصفحة
        m = _OG_RE.search(body) or _OG_RE2.search(body)
        if not m:
            return None
        url = m.group(1).replace("&amp;", "&").strip()
        return url if url.startswith("http") else None
    except Exception:
        return None


def _fallback_card(category: str) -> str | None:
    """مسار صورة التصنيف البديلة إن وُجدت."""
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = ASSETS_DIR / f"{category}.{ext}"
        if p.exists() and p.stat().st_size > 100:
            return str(p)
    return None


async def resolve_photo(session: aiohttp.ClientSession, item) -> tuple[bytes, str] | None:
    """قرار الصورة النهائي للخبر: أصلية ← og:image ← بديلة أنيقة.

    يُرجع (بيانات الصورة، نوع MIME) أو None (يُرسل نصًا حينها).
    """
    # 1) صورة أصلية من RSS/CryptoPanic
    if item.image and item.image.startswith("http"):
        got = await download_image(session, item.image)
        if got:
            return got

    # 2) og:image من صفحة الخبر
    if item.link:
        og = await fetch_og_image(session, item.link)
        if og:
            got = await download_image(session, og)
            if got:
                log.info("🖼 og:image استُخرج من صفحة الخبر")
                return got

    # 3) الصورة البديلة حسب التصنيف
    path = _fallback_card(item.category or "price")
    if path:
        ext = os.path.splitext(path)[1].lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}.get(ext)
        if mime:
            try:
                return Path(path).read_bytes(), mime
            except OSError:
                pass
    return None
