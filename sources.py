# -*- coding: utf-8 -*-
"""📡 جلب الأخبار من كل المصادر + أسعار السوق + تحركات الحيتان.

الأولوية (من ملفك القديم):
  1) CryptoPanic API  (اختياري — شعور السوق والعملات المرتبطة)
  2) CoinGecko News    (اختياري)
  3) RSS Feeds         (احتياطي دائم — 10 مصادر كبرى)
  4) Whale Alert       (اختياري — حركات الحيتان اللحظية)
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp
import feedparser

from config import (
    BROWSER_UA,
    CRYPTOPANIC_API_KEY,
    COINGECKO_API_KEY,
    MARKET_COINS,
    REQUEST_TIMEOUT,
    RSS_SOURCES,
    WHALE_ALERT_API_KEY,
)
from categories import COIN_AR

log = logging.getLogger("NewsBot")

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML_RE = re.compile(r"<[^>]+>")
_BRAND_RE = re.compile(
    r"\s*[-–|]\s*(CoinDesk|Cointelegraph|Decrypt|CryptoSlate|U\.Today|"
    r"Watcher\.Guru|WatcherGuru|NewsBTC|BeInCrypto|The\s+Block|CryptoPotato)\s*$", re.I)


def clean_html(text: str) -> str:
    """إزالة وسوم HTML وفك الكيانات."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = _HTML_RE.sub(" ", text)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()


def parse_date(date_str: str) -> float:
    """تحويل تاريخ RSS/ISO إلى timestamp (بالثواني). 0 = غير معروف."""
    if not date_str:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).timestamp()
    except Exception:
        pass
    try:
        clean = date_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    try:
        parsed = feedparser.datetimes._parse_date(date_str)
        if parsed:
            return time.mktime(parsed)
    except Exception:
        pass
    return 0.0


def strip_source_from_title(title: str) -> str:
    """إزالة اسم المصدر من نهاية العنوان (من الملف القديم)."""
    title = clean_html(title)
    title = _BRAND_RE.sub("", title).strip()
    title = re.sub(r"\s*[—–\-]\s*(?:Source|via|Image)[:\s].*$", "", title,
                   flags=re.IGNORECASE)
    return title.strip()


@dataclass
class NewsItem:
    """تمثيل خبر واحد — يحمل كل البيانات الوصفية."""
    title: str
    link: str = ""
    summary: str = ""
    image: str = ""
    source: str = ""
    timestamp: float = 0.0
    sentiment: str = ""          # important/hot/rising/bullish/bearish من CryptoPanic
    currencies: list = field(default_factory=list)
    whale_data: dict | None = None   # لأخبار Whale Alert الجاهزة
    # تُملأ لاحقًا في خط التحضير
    norm: str = ""
    hashes: list = field(default_factory=list)
    category: str = ""
    score: int = 0
    facts: list = field(default_factory=list)
    title_ar: str = ""

    def __repr__(self):
        return f"<News: {self.title[:60]}>"


# =========================================================== CryptoPanic
async def fetch_cryptopanic(session: aiohttp.ClientSession) -> list[NewsItem]:
    """🔥 CryptoPanic API — يوفر شعور السوق والعملات المرتبطة (يتطلب مفتاحًا)."""
    if not CRYPTOPANIC_API_KEY:
        return []
    all_items: list[NewsItem] = []
    seen_ids: set = set()
    for filt in ("important", "rising", "hot", "bullish", "bearish"):
        try:
            params = {
                "auth_token": CRYPTOPANIC_API_KEY,
                "filter": filt, "kind": "news", "public": "true",
                "currencies": "BTC,ETH,SOL,XRP,ADA,DOGE,AVAX",
            }
            async with session.get("https://cryptopanic.com/api/developer/v2/posts/",
                                   params=params,
                                   headers={"User-Agent": BROWSER_UA},
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    log.warning("📰 CryptoPanic [%s]: HTTP %s", filt, resp.status)
                    continue
                data = await resp.json(content_type=None)
                for post in data.get("results", []):
                    pid = post.get("id")
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    title = strip_source_from_title(post.get("title", "") or "")
                    if len(title) < 15:
                        continue
                    votes = post.get("votes", {}) or {}
                    sentiment = filt if votes.get(filt, 0) > 0 else ""
                    currencies = [i.get("code", "") for i in (post.get("instruments") or [])
                                  if i.get("code")]
                    all_items.append(NewsItem(
                        title=title,
                        link=(post.get("original_url") or "").strip(),
                        summary=clean_html(post.get("description") or "")[:400],
                        image=(post.get("image") or "").strip(),
                        source=f"CP:{(post.get('source') or {}).get('title', 'CryptoPanic')}",
                        timestamp=parse_date(post.get("published_at") or ""),
                        sentiment=sentiment, currencies=currencies,
                    ))
            await asyncio.sleep(0.4)
        except Exception as exc:
            log.warning("📰 CryptoPanic [%s]: %s", filt, exc)
    log.info("✔ CryptoPanic: %s خبر", len(all_items))
    return all_items


# =========================================================== CoinGecko News
async def fetch_coingecko_news(session: aiohttp.ClientSession) -> list[NewsItem]:
    """🆓 CoinGecko News API — يجمع 100+ مصدر (يتطلب مفتاحًا الآن)."""
    if not COINGECKO_API_KEY:
        return []
    items: list[NewsItem] = []
    try:
        headers = {"User-Agent": BROWSER_UA, "Accept": "application/json",
                   "x-cg-demo-api-key": COINGECKO_API_KEY}
        async with session.get(
                "https://api.coingecko.com/api/v3/news",
                params={"per_page": 20, "page": 1}, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("📰 CoinGecko News: HTTP %s", resp.status)
                return items
            data = await resp.json(content_type=None)
            news_list = data if isinstance(data, list) else data.get("data", [])
            for article in news_list:
                try:
                    title = strip_source_from_title(article.get("title", "") or "")
                    if len(title) < 15:
                        continue
                    coins = article.get("coins", []) or article.get("related_coins", []) or []
                    currencies = [
                        (c.get("symbol", "") if isinstance(c, dict) else str(c)).upper()
                        for c in coins]
                    items.append(NewsItem(
                        title=title,
                        link=(article.get("url") or "").strip(),
                        summary=clean_html(article.get("description") or "")[:400],
                        image=(article.get("image_url") or article.get("thumb_2x") or "").strip(),
                        source=f"CG:{article.get('author') or 'CoinGecko'}",
                        timestamp=parse_date(article.get("updated_at")
                                             or article.get("published_at") or ""),
                        currencies=[c for c in currencies if c],
                    ))
                except Exception:
                    continue
        log.info("✔ CoinGecko News: %s خبر", len(items))
    except Exception as exc:
        log.warning("📰 CoinGecko News: %s", exc)
    return items


# =========================================================== RSS
def _first_image(entry) -> str:
    """استخراج صورة الخبر من وسوم الوسائط في RSS."""
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
        m = re.search(r"""<img[^>]+src=["']([^"']+)["']""",
                      entry.get("summary") or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


async def fetch_rss_source(session: aiohttp.ClientSession, source: dict) -> list[NewsItem]:
    """📡 جلب وتحليل مصدر RSS واحد — التحميل عبر aiohttp والتحليل عبر feedparser."""
    items: list[NewsItem] = []
    try:
        async with session.get(source["url"], headers={"User-Agent": BROWSER_UA},
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("✖ %s: HTTP %s", source["name"], resp.status)
                return items
            content = await resp.read()
        parsed = feedparser.parse(content)
        entries = parsed.get("entries") or []
        for e in entries[:15]:
            title = strip_source_from_title(e.get("title", "") or "")
            if len(title) < 15:
                continue
            pub = e.get("published_parsed") or e.get("updated_parsed")
            ts = 0.0
            if pub:
                try:
                    ts = datetime.fromtimestamp(
                        time.mktime(pub), tz=timezone.utc).timestamp()
                except (OverflowError, ValueError, OSError):
                    ts = 0.0
            items.append(NewsItem(
                title=title,
                link=(e.get("link") or "").strip(),
                summary=clean_html(e.get("summary", ""))[:400],
                image=_first_image(e),
                source=source["name"],
                timestamp=ts,
            ))
        log.info("✔ %s: %s خبر", source["name"], len(items))
    except Exception as exc:
        log.warning("✖ فشل جلب %s: %s", source["name"], exc)
    return items


async def fetch_all_news() -> list[NewsItem]:
    """🚀 جلب كل المصادر — CryptoPanic ثم CoinGecko ثم RSS ثم Whale Alert."""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=3, ttl_dns_cache=300)
    all_items: list[NewsItem] = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            all_items += await fetch_cryptopanic(session)
        except Exception as exc:
            log.warning("CryptoPanic failed: %s", exc)
        try:
            all_items += await fetch_coingecko_news(session)
        except Exception as exc:
            log.warning("CoinGecko failed: %s", exc)
        rss_results = await asyncio.gather(
            *(fetch_rss_source(session, src) for src in RSS_SOURCES),
            return_exceptions=True)
        for result in rss_results:
            if isinstance(result, list):
                all_items += result
        if WHALE_ALERT_API_KEY:
            try:
                all_items += await fetch_whale_alert(session)
            except Exception as exc:
                log.warning("Whale Alert failed: %s", exc)

    all_items.sort(key=lambda x: -x.timestamp)
    log.info("📥 إجمالي الأخبار الخام: %s", len(all_items))
    return all_items


# =========================================================== Whale Alert
async def _owner_ar(owner: dict | None) -> str:
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


async def fetch_whale_alert(session: aiohttp.ClientSession, minutes: int = 60,
                            min_usd: float = 5_000_000) -> list[NewsItem]:
    """🐋 تحركات الحيتان الكبيرة خلال آخر ساعة (يتطلب مفتاحًا مجانيًا)."""
    if not WHALE_ALERT_API_KEY:
        return []
    items: list[NewsItem] = []
    try:
        start = int(time.time()) - minutes * 60
        async with session.get(
                "https://api.whale-alert.io/v1/transactions",
                params={"api_key": WHALE_ALERT_API_KEY, "min_value": int(min_usd),
                        "start": start},
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
            if resp.status != 200:
                log.warning("Whale Alert: HTTP %s", resp.status)
                return items
            txs = (await resp.json(content_type=None)).get("transactions") or []
        for tx in txs:
            try:
                symbol = (tx.get("symbol") or "").upper()
                amount = float(tx.get("amount") or 0)
                amount_usd = float(tx.get("amount_usd") or 0)
                if not symbol or amount_usd < min_usd:
                    continue
                src, dst = tx.get("from") or {}, tx.get("to") or {}
                from_txt, to_txt = _owner_ar(src), _owner_ar(dst)
                items.append(NewsItem(
                    title=(f"Whale Alert: {amount:,.0f} {symbol} "
                           f"(~${amount_usd:,.0f}) moved from {from_txt} to {to_txt}"),
                    link=f"https://whale-alert.io/transaction/{symbol.lower()}/{tx.get('hash')}"
                         if tx.get("hash") else "",
                    source="Whale Alert",
                    timestamp=float(tx.get("timestamp") or time.time()),
                    whale_data={
                        "symbol": symbol, "amount": amount, "amount_usd": amount_usd,
                        "from_txt": from_txt, "to_txt": to_txt,
                        "to_type": (dst.get("owner_type") or "").lower(),
                        "from_type": (src.get("owner_type") or "").lower(),
                    },
                ))
            except Exception:
                continue
        log.info("✔ Whale Alert: %s حركة", len(items))
    except Exception as exc:
        log.warning("Whale Alert فشل: %s", exc)
    return items


# =========================================================== أسعار السوق
async def _market_from_coingecko(session: aiohttp.ClientSession) -> list[dict] | None:
    try:
        ids = ",".join(c["id"] for c in MARKET_COINS)
        params = {"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"}
        headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
        if COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
        async with session.get("https://api.coingecko.com/api/v3/simple/price",
                               params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
            if resp.status == 429:
                await asyncio.sleep(3)
                async with session.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params=params, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp2:
                    if resp2.status != 200:
                        return None
                    data = await resp2.json(content_type=None)
            elif resp.status != 200:
                return None
            else:
                data = await resp.json(content_type=None)
    except Exception:
        return None
    stats = []
    for coin in MARKET_COINS:
        row = (data or {}).get(coin["id"]) or {}
        if row.get("usd") is None:
            continue
        stats.append({"name": coin["name"], "symbol": coin["symbol"],
                      "price": float(row["usd"]),
                      "change": float(row.get("usd_24h_change") or 0.0)})
    return stats or None


async def _market_from_paprika(session: aiohttp.ClientSession) -> list[dict] | None:
    """بديل مجاني بلا مفتاح — CoinPaprika."""
    try:
        async with session.get("https://api.coinpaprika.com/v1/tickers",
                               params={"quotes": "USD"},
                               headers={"User-Agent": BROWSER_UA},
                               timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None) or []
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
    order = {c["symbol"]: i for i, c in enumerate(MARKET_COINS)}
    stats.sort(key=lambda s: order.get(s["symbol"], 99))
    return stats or None


async def fetch_market_stats() -> list[dict] | None:
    """📊 أسعار أعلى العملات مع تغير 24 ساعة — CoinGecko ثم CoinPaprika."""
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT + 10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        stats = await _market_from_coingecko(session) or await _market_from_paprika(session)
    if not stats:
        log.warning("📊 فشل جلب أسعار السوق — ترويسة الجولة بدون أسعار")
    return stats or None
