"""
📡 جلب الأخبار من مصادر RSS
"""

import re
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from typing import List, Optional
import aiohttp

from config import RSS_SOURCES, log


# ═══════════════════════════════════════════════════════════
# نموذج الخبر
# ═══════════════════════════════════════════════════════════
class NewsItem:
    def __init__(self, title, link, summary, image, source, timestamp, original_title=""):
        self.title = title.strip()
        self.link = link.strip()
        self.summary = summary.strip()
        self.image = image.strip()
        self.source = source
        self.timestamp = timestamp
        self.original_title = original_title or title

    def __repr__(self):
        return f"<News: {self.title[:60]}...>"


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


# أسماء مصادر معروفة — تُزال من نهاية العنوان (مع أو بدون فاصل)
KNOWN_SOURCE_NAMES = [
    # مواقع أخبار كريبتو
    "Cryptonews.net", "Cryptonews", "CryptoRank", "CryptoSlate",
    "CoinDesk", "Cointelegraph", "Decrypt", "The Block", "Blockworks",
    "Bitcoin.com", "Bitcoinist", "NewsBTC", "CryptoNews",
    "BeInCrypto", "CryptoPotato", "CoinGape", "CoinQuora",
    "The Daily Hodl", "Live Bitcoin News", "CryptoGlobe",
    "FXStreet", "Benzinga", "Yahoo Finance", "MarketWatch",
    "Bloomberg", "Reuters", "CNBC", "Forbes", "The Street",
    "Investing.com", "CoinJournal", "CryptoBriefing",
    "WatcherGuru", "Watcher.Guru",
    # امتدادات شائعة
    ".com", ".net", ".io", ".org", ".co",
]


def strip_source_from_title(title: str, source_name: str) -> str:
    """
    إزالة اسم الموقع من نهاية العنوان بثلاث طرق:
    1) الفواصل: " - CoinDesk" / " | Reuters"
    2) بدون فاصل: "...Big Deal Cryptonews.net"
    3) امتدادات: "...report.com"
    """
    if not title:
        return title

    # 1) الفواصل الكلاسيكية
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

    # 2) إزالة أسماء المصادر المعروفة من النهاية (بدون فاصل)
    for src in KNOWN_SOURCE_NAMES:
        if title.endswith(src):
            new_title = title[:-len(src)].rstrip(" -|–—").strip()
            if len(new_title) > 10:
                return new_title
        # حالة insensitive
        if title_lower.endswith(src.lower()):
            new_title = title[:-len(src)].rstrip(" -|–—").strip()
            if len(new_title) > 10:
                return new_title

    # 3) إزالة "Source: XXX" أو "via XXX" في النهاية
    title = re.sub(r'\s*[—–\-]\s*(?:Source|via|Image)[:\s].*$', '', title, flags=re.IGNORECASE)

    return title.strip()


def extract_image(item_elem) -> str:
    """استخراج رابط الصورة من عنصر RSS"""
    # 1) media:content
    media = item_elem.find('{http://search.yahoo.com/mrss/}content')
    if media is not None and media.get('url'):
        return media.get('url', '')
    # 2) media:thumbnail
    thumb = item_elem.find('{http://search.yahoo.com/mrss/}thumbnail')
    if thumb is not None and thumb.get('url'):
        return thumb.get('url', '')
    # 3) enclosure (image type)
    enclosure = item_elem.find('enclosure')
    if enclosure is not None:
        if enclosure.get('type', '').startswith('image'):
            return enclosure.get('url', '')
    # 4) <img> داخل description
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
    # اقتطاع عند آخر جملة كاملة
    truncated = clean[:max_len]
    last_sentence = max(truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? '))
    if last_sentence > max_len * 0.5:
        return truncated[:last_sentence + 1].strip()
    return truncated[:max_len-3].strip() + "..."


# ═══════════════════════════════════════════════════════════
# جلب مصدر واحد
# ═══════════════════════════════════════════════════════════
async def fetch_source(session: aiohttp.ClientSession, source: dict) -> List[NewsItem]:
    """جلب الأخبار من مصدر RSS واحد"""
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0)"}
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
# جلب كل المصادر بالتوازي
# ═══════════════════════════════════════════════════════════
async def fetch_all_news() -> List[NewsItem]:
    """جلب كل الأخبار من كل المصادر بالتوازي"""
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=3, ttl_dns_cache=300)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        tasks = [fetch_source(session, src) for src in RSS_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for result in results:
        if isinstance(result, list):
            all_items.extend(result)

    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: -x.timestamp)
    log.info(f"📊 Total fetched: {len(all_items)} items from {len(RSS_SOURCES)} sources")
    return all_items
