"""
📡 جلب الأخبار من مصادر متعددة:
   1) CryptoPanic API (مدفوع — أقوى مصدر)
   2) CoinGecko News API (مجاني — بدون مفتاح)
   3) RSS feeds (احتياطي دائم)
"""

import re
import asyncio
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from typing import List, Optional
import aiohttp

from config import RSS_SOURCES, log

# مفاتيح API — تُقرأ من البيئة
import os
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")


# ═══════════════════════════════════════════════════════════
# نموذج الخبر
# ═══════════════════════════════════════════════════════════
class NewsItem:
    def __init__(self, title, link, summary, image, source, timestamp,
                 original_title="", sentiment="", currencies=None):
        self.title = title.strip()
        self.link = link.strip()
        self.summary = summary.strip()
        self.image = image.strip()
        self.source = source
        self.timestamp = timestamp
        self.original_title = original_title or title
        self.sentiment = sentiment or ""  # bullish/bearish/important/hot/rising
        self.currencies = currencies or []  # ["BTC", "ETH"] من CryptoPanic

    def __repr__(self):
        return f"<News: {self.title[:60]}... sentiment={self.sentiment}>"


# ═══════════════════════════════════════════════════════════
# أدوات XML
# ═══════════════════════════════════════════════════════════
def clean_html(text: str) -> str:
    """إزالة وسوم HTML وفك الكيانات"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_date(date_str: str) -> float:
    """تحويل تاريخ RSS إلى timestamp"""
    if not date_str:
        return 0.0
    try:
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
        return 0.0


# أسماء مصادر معروفة — تُزال من نهاية العنوان
KNOWN_SOURCE_NAMES = [
    "Cryptonews.net", "Cryptonews", "CryptoRank", "CryptoSlate",
    "CoinDesk", "Cointelegraph", "Decrypt", "The Block", "Blockworks",
    "Bitcoin.com", "Bitcoinist", "NewsBTC", "CryptoNews",
    "BeInCrypto", "CryptoPotato", "CoinGape", "CoinQuora",
    "The Daily Hodl", "Live Bitcoin News", "CryptoGlobe",
    "FXStreet", "Benzinga", "Yahoo Finance", "MarketWatch",
    "Bloomberg", "Reuters", "CNBC", "Forbes", "The Street",
    "Investing.com", "CoinJournal", "CryptoBriefing",
    "WatcherGuru", "Watcher.Guru", "CryptoPanic",
    ".com", ".net", ".io", ".org", ".co",
]


def strip_source_from_title(title: str, source_name: str) -> str:
    """إزالة اسم الموقع من نهاية العنوان"""
    if not title:
        return title

    title_lower = title.lower()
    source_lower = (source_name or "").lower()
    for sep in [" - ", " | ", " — ", " – ", " — ", " - "]:
        if sep in title_lower:
            parts = title_lower.rsplit(sep, 1)
            if len(parts) == 2:
                last_part = parts[1].strip()
                if (source_lower and source_lower in last_part) or len(last_part) < 30:
                    idx = title_lower.rfind(sep)
                    if idx > 10:
                        return title[:idx].strip()

    for src in KNOWN_SOURCE_NAMES:
        if title.endswith(src):
            new_title = title[:-len(src)].rstrip(" -|–—").strip()
            if len(new_title) > 10:
                return new_title
        if title_lower.endswith(src.lower()):
            new_title = title[:-len(src)].rstrip(" -|–—").strip()
            if len(new_title) > 10:
                return new_title

    title = re.sub(r'\s*[—–\-]\s*(?:Source|via|Image)[:\s].*$', '', title, flags=re.IGNORECASE)
    return title.strip()


def extract_image(item_elem) -> str:
    """استخراج رابط الصورة من عنصر RSS"""
    media = item_elem.find('{http://search.yahoo.com/mrss/}content')
    if media is not None and media.get('url'):
        return media.get('url', '')
    thumb = item_elem.find('{http://search.yahoo.com/mrss/}thumbnail')
    if thumb is not None and thumb.get('url'):
        return thumb.get('url', '')
    enclosure = item_elem.find('enclosure')
    if enclosure is not None:
        if enclosure.get('type', '').startswith('image'):
            return enclosure.get('url', '')
    desc = item_elem.findtext('description', '') or ''
    match = re.search(r"""<img[^>]+src=['"]([^'"]+)['"]""", desc)
    if match:
        return match.group(1)
    return ""


def extract_summary(text: str, max_len: int = 400) -> str:
    """تنظيف واقتطاع الملخص"""
    clean = clean_html(text)
    if len(clean) <= max_len:
        return clean
    truncated = clean[:max_len]
    last_sentence = max(truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? '))
    if last_sentence > max_len * 0.5:
        return truncated[:last_sentence + 1].strip()
    return truncated[:max_len-3].strip() + "..."


# ═══════════════════════════════════════════════════════════
# 🔥 CryptoPanic API — أقوى مصدر (مدفوع)
# ═══════════════════════════════════════════════════════════
async def fetch_cryptopanic(session: aiohttp.ClientSession) -> List[NewsItem]:
    """
    جلب الأخبار من CryptoPanic API v2.
    يطلب عدة فلترات: important, rising, hot, bullish, bearish
    ويدمج النتائج مع وسم الشعور.
    """
    if not CRYPTOPANIC_API_KEY:
        log.info("📰 CryptoPanic: لا يوجد مفتاح — تخطي")
        return []

    all_items = []
    seen_ids = set()

    # نطلب الأخبار المهمة والصاعدة أولاً
    filters_to_try = ["important", "rising", "hot", "bullish", "bearish"]

    for filt in filters_to_try:
        try:
            url = "https://cryptopanic.com/api/developer/v2/posts/"
            params = {
                "auth_token": CRYPTOPANIC_API_KEY,
                "filter": filt,
                "kind": "news",
                "public": "true",
                "currencies": "BTC,ETH,SOL,XRP,ADA,DOGE,AVAX",
            }
            headers = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/2.0)"}
            timeout = aiohttp.ClientTimeout(total=10)

            async with session.get(url, params=params, headers=headers, timeout=timeout) as resp:
                if resp.status != 200:
                    log.warning(f"📰 CryptoPanic [{filt}]: HTTP {resp.status}")
                    continue

                data = await resp.json(content_type=None)
                results = data.get("results", [])

                for post in results:
                    post_id = post.get("id")
                    if post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    title = post.get("title", "").strip()
                    if not title:
                        continue

                    # استخراج البيانات الغنية
                    description = post.get("description", "") or ""
                    image = post.get("image", "") or ""
                    original_url = post.get("original_url", "") or ""
                    published_at = post.get("published_at", "") or ""
                    source_info = post.get("source", {})
                    source_name = source_info.get("title", "CryptoPanic")

                    # وسم الشعور
                    votes = post.get("votes", {})
                    sentiment = filt  # important/rising/hot/bullish/bearish
                    if votes.get("important", 0) > 0:
                        sentiment = "important"

                    # العملات المرتبطة
                    instruments = post.get("instruments", [])
                    currencies = [inst.get("code", "") for inst in instruments if inst.get("code")]

                    timestamp = parse_date(published_at)
                    title = strip_source_from_title(title, source_name)

                    all_items.append(NewsItem(
                        title=title,
                        link=original_url,
                        summary=description[:400],
                        image=image,
                        source=f"CP:{source_name}",
                        timestamp=timestamp,
                        original_title=title,
                        sentiment=sentiment,
                        currencies=currencies,
                    ))

            await asyncio.sleep(0.5)  # احترام حدود الطلبات

        except asyncio.TimeoutError:
            log.warning(f"📰 CryptoPanic [{filt}]: timeout")
        except Exception as e:
            log.warning(f"📰 CryptoPanic [{filt}]: {e}")

    log.info(f"📰 CryptoPanic: {len(all_items)} items")
    return all_items


# ═══════════════════════════════════════════════════════════
# 🆓 CoinGecko News API — مجاني (بدون مفتاح أو معه)
# ═══════════════════════════════════════════════════════════
async def fetch_coingecko_news(session: aiohttp.ClientSession) -> List[NewsItem]:
    """
    جلب الأخبار من CoinGecko News API.
    يتطلب مفتاح API (حتى المجاني محدود الآن).
    بدون مفتاح: تخطي صامت.
    """
    if not COINGECKO_API_KEY:
        log.info("📰 CoinGecko: لا يوجد مفتاح — تخطي (أضف COINGECKO_API_KEY في Secrets)")
        return []

    items = []
    try:
        url = "https://api.coingecko.com/api/v3/news"
        params = {
            "type": "news",
            "per_page": 20,
            "page": 1,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/2.0)",
            "Accept": "application/json",
            "x-cg-demo-api-key": COINGECKO_API_KEY,
        }

        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(url, params=params, headers=headers, timeout=timeout) as resp:
            if resp.status == 429:
                log.warning(f"📰 CoinGecko: 429 rate limit")
                return items
            if resp.status != 200:
                log.warning(f"📰 CoinGecko: HTTP {resp.status}")
                return items

            data = await resp.json(content_type=None)

            # CoinGecko قد يرجع dict مع "data" أو list مباشرة
            news_list = data if isinstance(data, list) else data.get("data", [])

            for article in news_list:
                try:
                    title = article.get("title", "").strip()
                    if not title:
                        continue

                    description = article.get("description", "") or ""
                    image = article.get("image_url", "") or article.get("thumb_2x", "") or ""
                    link = article.get("url", "") or ""
                    published_at = article.get("updated_at", "") or article.get("published_at", "") or ""
                    source_name = article.get("author", "") or article.get("source", "") or "CoinGecko"

                    # عملات مرتبطة إن وجدت
                    currencies = []
                    coins = article.get("coins", []) or article.get("related_coins", [])
                    for coin in coins:
                        code = coin.get("symbol", "").upper() if isinstance(coin, dict) else str(coin).upper()
                        if code:
                            currencies.append(code)

                    timestamp = parse_date(published_at)
                    title = strip_source_from_title(title, source_name)

                    items.append(NewsItem(
                        title=title,
                        link=link,
                        summary=description[:400],
                        image=image,
                        source=f"CG:{source_name}",
                        timestamp=timestamp,
                        original_title=title,
                        sentiment="",  # CoinGecko لا يوفر شعور
                        currencies=currencies,
                    ))
                except Exception:
                    continue

        log.info(f"📰 CoinGecko: {len(items)} items")
    except asyncio.TimeoutError:
        log.warning(f"📰 CoinGecko: timeout")
    except Exception as e:
        log.warning(f"📰 CoinGecko: {e}")
    return items


# ═══════════════════════════════════════════════════════════
# 📡 RSS feeds — احتياطي دائم
# ═══════════════════════════════════════════════════════════
async def fetch_rss_source(session: aiohttp.ClientSession, source: dict) -> List[NewsItem]:
    """جلب الأخبار من مصدر RSS واحد"""
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/2.0)"}
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(source["url"], timeout=timeout, headers=headers) as response:
            if response.status != 200:
                log.warning(f"📰 {source['name']}: HTTP {response.status}")
                return items
            content = await response.text()
            try:
                root = ET.fromstring(content.encode())
            except ET.ParseError as e:
                log.warning(f"📰 {source['name']}: XML parse error: {e}")
                return items

            # RSS 2.0
            for item_elem in root.findall('.//item')[:15]:
                try:
                    title = item_elem.findtext('title', '') or ""
                    link = item_elem.findtext('link', '') or ""
                    desc = item_elem.findtext('description', '') or ''
                    pub_date = item_elem.findtext('pubDate', '') or ''

                    if not title:
                        continue
                    title = strip_source_from_title(clean_html(title), source["name"])
                    summary = extract_summary(desc)
                    image = extract_image(item_elem)
                    timestamp = parse_date(pub_date)

                    items.append(NewsItem(
                        title=title, link=link, summary=summary,
                        image=image, source=source["name"], timestamp=timestamp,
                        original_title=title,
                    ))
                except Exception:
                    continue

            # Atom fallback
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('.//atom:entry', ns)[:15]:
                    try:
                        title = entry.findtext('atom:title', '', ns) or ""
                        link_elem = entry.find('atom:link', ns)
                        link = link_elem.get('href', '') if link_elem is not None else ""
                        summary = entry.findtext('atom:summary', '', ns) or ''
                        pub_date = entry.findtext('atom:updated', '', ns) or ''

                        if not title:
                            continue
                        title = strip_source_from_title(clean_html(title), source["name"])
                        summary = extract_summary(summary)
                        image = extract_image(entry)
                        timestamp = parse_date(pub_date)

                        items.append(NewsItem(
                            title=title, link=link, summary=summary,
                            image=image, source=source["name"], timestamp=timestamp,
                            original_title=title,
                        ))
                    except Exception:
                        continue

        log.info(f"📰 {source['name']}: {len(items)} items")
    except asyncio.TimeoutError:
        log.warning(f"📰 {source['name']}: timeout")
    except Exception as e:
        log.warning(f"📰 {source['name']}: {e}")
    return items


# ═══════════════════════════════════════════════════════════
# 🚀 جلب كل المصادر — CryptoPanic → CoinGecko → RSS
# ═══════════════════════════════════════════════════════════
async def fetch_all_news() -> List[NewsItem]:
    """
    جلب الأخبار من كل المصادر بالأولوية:
    1) CryptoPanic API (أقوى — بيانات شعور + عملات)
    2) CoinGecko News API (مجاني — 100+ مصدر)
    3) RSS feeds (احتياطي — دائماً متاح)
    """
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=3, ttl_dns_cache=300)

    all_items = []

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # ═══════ 1) CryptoPanic API ═══════
        if CRYPTOPANIC_API_KEY:
            try:
                cp_items = await fetch_cryptopanic(session)
                all_items.extend(cp_items)
                log.info(f"🔥 CryptoPanic contributed {len(cp_items)} items")
            except Exception as e:
                log.warning(f"📰 CryptoPanic failed: {e}")

        # ═══════ 2) CoinGecko News ═══════
        try:
            cg_items = await fetch_coingecko_news(session)
            all_items.extend(cg_items)
            log.info(f"🆓 CoinGecko contributed {len(cg_items)} items")
        except Exception as e:
            log.warning(f"📰 CoinGecko failed: {e}")

        # ═══════ 3) RSS fallback ═══════
        rss_tasks = [fetch_rss_source(session, src) for src in RSS_SOURCES]
        rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)
        for result in rss_results:
            if isinstance(result, list):
                all_items.extend(result)

    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: -x.timestamp)

    sources_summary = {}
    for item in all_items:
        src = item.source.split(":")[0] if ":" in item.source else item.source
        sources_summary[src] = sources_summary.get(src, 0) + 1

    log.info(f"📊 Total: {len(all_items)} items | Sources: {sources_summary}")
    return all_items
