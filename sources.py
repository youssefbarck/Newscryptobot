# -*- coding: utf-8 -*-
"""جلب الأخبار من مصادر RSS + Whale Alert (اختياري) + أسعار السوق من CoinGecko"""
import calendar
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .config import (
    HTTP_HEADERS,
    MARKET_COINS,
    REQUEST_TIMEOUT,
)

log = logging.getLogger("crypto-bot")

# ------------------------------------------------------------------- أدوات
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML_RE = re.compile(r"<[^>]+>")
_BRAND_RE = re.compile(
    r"\s*[-–|]\s*(CoinDesk|Cointelegraph|Decrypt|CryptoSlate|U\.Today|"
    r"Watcher\.Guru|NewsBTC|The\s+Block)\s*$", re.I)


def strip_html(text: str) -> str:
    """تنظيف النص من وسوم HTML وكياناتها."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = _HTML_RE.sub(" ", text)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(title: str) -> str:
    title = strip_html(title)
    return _BRAND_RE.sub("", title).strip()


def _parse_published(entry) -> datetime | None:
    pp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pp:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(pp), tz=timezone.utc)
    except (OverflowError, ValueError, OSError):
        return None


def _first_image(entry) -> str | None:
    """استخراج صورة الخبر من وسوم الوسائط إن وجدت."""
    try:
        for key in ("media_content", "media_thumbnail"):
            for m in (entry.get(key) or []):
                url = m.get("url")
                if url:
                    return url
        for m in (entry.get("enclosures") or []):
            url = m.get("href") or m.get("url") or ""
            if url and re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I):
                return url
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', entry.get("summary") or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


# ------------------------------------------------- صورة الخبر من صفحته
_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)'
    r'["\'][^>]*content=["\']([^"\']+)["\']', re.I)
_OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
    r'(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.I)


def fetch_og_image(article_url: str) -> str | None:
    """فتح صفحة الخبر واستخراج صورتها الأصلية (og:image / twitter:image).

    يُستدعى فقط للأخبار المختارة للنشر والتي بلا صورة في RSS —
    على الأكثر 4 طلبات في الجولة.
    """
    if not article_url or not article_url.startswith("http"):
        return None
    browser = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        r = requests.get(article_url, headers=browser,
                         timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if not r.ok:
            return None
        html_text = r.text[:400_000]  # الكافي: وسوم meta في أعلى الصفحة
        m = _OG_RE.search(html_text) or _OG_RE2.search(html_text)
        if not m:
            return None
        url = m.group(1).replace("&amp;", "&").strip()
        if not url.startswith("http"):
            return None
        log.info("🖼 og:image استُخرج من صفحة الخبر")
        return url
    except requests.RequestException:
        return None


# ------------------------------------------------------------------- RSS
def fetch_feeds(feeds: list[dict], limit_per_feed: int = 25) -> list[dict]:
    """جلب أحدث الأخبار من كل مصادر RSS مع تجاهل المصادر المعطوبة."""
    items: list[dict] = []
    for feed in feeds:
        name, url = feed["name"], feed["url"]
        try:
            parsed = feedparser.parse(url, request_headers=HTTP_HEADERS)
            entries = parsed.get("entries") or []
            if not entries:
                log.warning("المصدر %s أعاد 0 خبر", name)
                continue
            count = 0
            for e in entries[:limit_per_feed]:
                title = _clean_title(e.get("title", ""))
                if len(title) < 15:  # تجاهل العناوين الفاسدة/القصيرة جدًا
                    continue
                items.append({
                    "source": name,
                    "title": title,
                    "summary": strip_html(e.get("summary", ""))[:400],
                    "url": (e.get("link") or "").strip(),
                    "published": _parse_published(e),
                    "image": _first_image(e),
                })
                count += 1
            log.info("✔ %s: %s خبر", name, count)
        except Exception as exc:  # مصدر واحد معطوب لا يوقف البوت
            log.warning("✖ فشل جلب %s: %s", name, exc)
    return items


# ------------------------------------------------------- Whale Alert (اختياري)
def _owner_ar(owner: dict | None) -> str:
    if not owner:
        return "محفظة مجهولة"
    otype = (owner.get("owner_type") or "").lower()
    name = (owner.get("owner") or "").strip()
    if otype == "burn" or name.lower() in ("burn", "burned"):
        return "عنوان حرق"
    if otype == "exchange":
        return f"بورصة {name}" if name and name.lower() != "unknown" else "بورصة"
    if otype == "contract":
        return f"عقد ذكي ({name})" if name and name.lower() != "unknown" else "عقد ذكي"
    if name and name.lower() not in ("unknown", "wallet", ""):
        return name
    return "محفظة مجهولة"


def fetch_whale_alert(api_key: str, minutes: int = 60, min_usd: float = 5_000_000) -> list[dict]:
    """جلب تحركات الحيتان الكبيرة خلال آخر `minutes` دقيقة (يتطلب مفتاحًا مجانيًا)."""
    if not api_key:
        return []
    try:
        start = int(time.time()) - minutes * 60
        r = requests.get(
            "https://api.whale-alert.io/v1/transactions",
            params={"api_key": api_key, "min_value": int(min_usd), "start": start},
            headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        txs = (r.json() or {}).get("transactions") or []
    except Exception as exc:
        log.warning("Whale Alert فشل: %s", exc)
        return []

    items = []
    for tx in txs:
        try:
            symbol = (tx.get("symbol") or "").upper()
            amount = float(tx.get("amount") or 0)
            amount_usd = float(tx.get("amount_usd") or 0)
            if not symbol or amount_usd < min_usd:
                continue
            src, dst = tx.get("from") or {}, tx.get("to") or {}
            from_txt, to_txt = _owner_ar(src), _owner_ar(dst)
            title_en = (f"Whale Alert: {amount:,.0f} {symbol} "
                        f"(~${amount_usd:,.0f}) moved from {from_txt} to {to_txt}")
            items.append({
                "source": "Whale Alert",
                "title": title_en,
                "summary": "",
                "url": tx.get("hash") and f"https://whale-alert.io/transaction/{symbol.lower()}/{tx['hash']}" or "",
                "published": datetime.fromtimestamp(
                    int(tx.get("timestamp") or time.time()), tz=timezone.utc),
                "image": None,
                "whale_data": {
                    "symbol": symbol,
                    "amount": amount,
                    "amount_usd": amount_usd,
                    "from_txt": from_txt,
                    "to_txt": to_txt,
                    "to_type": (dst.get("owner_type") or "").lower(),
                    "from_type": (src.get("owner_type") or "").lower(),
                },
            })
        except Exception:
            continue
    log.info("✔ Whale Alert: %s حركة", len(items))
    return items


# ------------------------------------------------------------------ السوق
def _market_from_coingecko() -> list[dict] | None:
    try:
        ids = ",".join(c["id"] for c in MARKET_COINS)
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:  # الحد اليومي — جرّب مرة بعد ثوان
            time.sleep(3)
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
                headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json() or {}
    except Exception:
        return None
    stats = []
    for coin in MARKET_COINS:
        row = data.get(coin["id"]) or {}
        if row.get("usd") is None:
            continue
        stats.append({"name": coin["name"], "symbol": coin["symbol"],
                      "price": float(row["usd"]),
                      "change": float(row.get("usd_24h_change") or 0.0)})
    return stats or None


def _market_from_paprika() -> list[dict] | None:
    """بديل مجاني بلا مفتاح — CoinPaprika."""
    try:
        r = requests.get("https://api.coinpaprika.com/v1/tickers",
                         params={"quotes": "USD"}, headers=HTTP_HEADERS,
                         timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json() or []
    except Exception:
        return None
    wanted = {c["symbol"]: c["name"] for c in MARKET_COINS}
    best: dict[str, tuple] = {}  # أعلى عملة (أصغر rank) لكل رمز — بعض الرموز مكررة
    for row in data:
        sym = (row.get("symbol") or "").upper()
        if sym not in wanted:
            continue
        rank = row.get("rank") or 99999
        if sym in best and best[sym][0] <= rank:
            continue
        usd = (row.get("quotes") or {}).get("USD") or {}
        price = usd.get("price")
        if price is None:
            continue
        best[sym] = (rank, {"name": wanted[sym], "symbol": sym,
                            "price": float(price),
                            "change": float(usd.get("percent_change_24h")
                                            or usd.get("change_24h") or 0.0)})
    stats = [entry for _, entry in best.values()]
    # ترتيب حسب شهرة العملة (نفس ترتيب MARKET_COINS)
    order = {c["symbol"]: i for i, c in enumerate(MARKET_COINS)}
    stats.sort(key=lambda s: order.get(s["symbol"], 99))
    return stats or None


def fetch_market_stats() -> list[dict] | None:
    """أسعار أعلى العملات مع تغير 24 ساعة — CoinGecko ثم CoinPaprika كخطة بديلة."""
    stats = _market_from_coingecko() or _market_from_paprika()
    if not stats:
        log.warning("CoinGecko فشل: %s", "وCoinPaprika فشل أيضًا — لا أسعار هذه الجولة")
    return stats or None
