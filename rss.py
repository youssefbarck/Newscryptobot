"""
📡 Whale News Bot v2.0 - جلب الأخبار (Async)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
جلب متوازي، connection pooling، و parsing متقدم
"""

import re, time, asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from xml.etree import ElementTree as ET
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientTimeout, TCPConnector

from config import (
    log, NEWS_SOURCES, HEADERS, REDDIT_HEADERS, 
    FARSIDE_RATE_LIMITER, FARSIDE_CB,
)
from filters import NewsItem


# ═══════════════════════════════════════════════════════════
# 🌐 Session Manager (Connection Pooling)
# ═══════════════════════════════════════════════════════════
class SessionManager:
    """مدير الجلسات مع connection pooling"""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector = TCPConnector(
            limit=50,           # إجمالي الاتصالات
            limit_per_host=10,  # لكل host
            ttl_dns_cache=300,  # cache DNS 5 دقائق
            use_dns_cache=True,
        )
        self._timeout = ClientTimeout(total=20, connect=10)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=self._timeout,
                headers=HEADERS,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


session_manager = SessionManager()


# ═══════════════════════════════════════════════════════════
# 📅 Date Parsing (محسّن)
# ═══════════════════════════════════════════════════════════
_DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
    "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
    "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 with Z
    "%Y-%m-%d %H:%M:%S",             # Simple
    "%Y-%m-%d",                       # Date only
]


def parse_date(date_str: str) -> float:
    """تحويل تاريخ RSS إلى timestamp"""
    if not date_str:
        return 0.0

    # محاولة RFC 822
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.timestamp()
    except Exception:
        pass

    # محاولة ISO 8601
    try:
        clean = date_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass

    # محاولة الصيغ الأخرى
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.timestamp()
        except Exception:
            pass

    return 0.0


# ═══════════════════════════════════════════════════════════
# 🧹 HTML Cleaning
# ═══════════════════════════════════════════════════════════
def clean_html(text: str) -> str:
    """تنظيف HTML"""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def extract_summary(text: str, max_len: int = 300) -> str:
    """اختصار النص"""
    clean = clean_html(text)
    if len(clean) <= max_len:
        return clean
    # قص عند نهاية جملة
    truncated = clean[:max_len]
    last_sentence = max(
        truncated.rfind('. '), truncated.rfind('! '), truncated.rfind('? ')
    )
    if last_sentence > max_len * 0.5:
        return truncated[:last_sentence + 1]
    return truncated[:max_len-3] + "..."


def extract_image_from_html(html_text: str) -> str:
    """استخراج رابط الصورة من HTML"""
    if not html_text:
        return ""
    # img src
    match = re.search(r'<img[^>]+src=["']([^"']+)["']', html_text)
    if match:
        return match.group(1)
    return ""


def strip_source_from_title(title: str, source_name: str = "") -> str:
    """إزالة اسم المصدر من العنوان"""
    if not title or not source_name:
        return title

    source_lower = source_name.lower()
    cleaned = title
    separators = [" - ", " | ", " — ", " – ", " :: "]

    for sep in separators:
        if sep in cleaned.lower():
            parts = cleaned.lower().rsplit(sep, 1)
            if len(parts) == 2:
                last_part = parts[1].strip()
                if (source_lower in last_part or len(last_part) < 30):
                    idx = cleaned.lower().rfind(sep)
                    if idx > 10:
                        cleaned = cleaned[:idx].strip()
                        break
    return cleaned


# ═══════════════════════════════════════════════════════════
# 📰 RSS Parser (Async)
# ═══════════════════════════════════════════════════════════
async def parse_rss_source(source: "NewsSource") -> List[NewsItem]:
    """جلب وتحليل مصدر RSS واحد (async)"""
    items = []

    try:
        session = await session_manager.get_session()

        async with session.get(
            source.url, 
            headers=REDDIT_HEADERS if "reddit" in source.url.lower() else HEADERS,
            timeout=ClientTimeout(total=source.timeout)
        ) as response:

            if response.status != 200:
                log.warning(f"📰 {source.name}: HTTP {response.status}")
                return items

            content = await response.text()

            # محاولة parse كـ RSS 2.0
            try:
                root = ET.fromstring(content.encode())
            except ET.ParseError:
                log.warning(f"📰 {source.name}: XML parse error")
                return items

            # RSS 2.0
            for item_elem in root.findall('.//item')[:15]:
                try:
                    title = item_elem.findtext('title', '') or ""
                    link = item_elem.findtext('link', '') or ""
                    desc = item_elem.findtext('description', '') or ""
                    pub_date = item_elem.findtext('pubDate', '') or ""

                    # استخراج الصورة
                    image = extract_image_from_html(desc)
                    if not image:
                        media = item_elem.find('{http://search.yahoo.com/mrss/}content')
                        if media is not None and media.get('url'):
                            image = media.get('url')
                    if not image:
                        enclosure = item_elem.find('enclosure')
                        if enclosure is not None and enclosure.get('type', '').startswith('image'):
                            image = enclosure.get('url', '')

                    items.append(NewsItem(
                        title=strip_source_from_title(clean_html(title), source.name),
                        link=link,
                        summary=extract_summary(desc),
                        image=image,
                        source=source.name,
                        category=source.category,
                        timestamp=parse_date(pub_date),
                        date_str=pub_date,
                        lang=source.lang,
                    ))
                except Exception as e:
                    log.debug(f"Parse item error in {source.name}: {e}")
                    continue

            # Atom fallback
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('.//atom:entry', ns)[:15]:
                    try:
                        title = entry.findtext('atom:title', '', ns) or ""
                        link_elem = entry.find('atom:link', ns)
                        link = link_elem.get('href', '') if link_elem is not None else ""
                        summary = entry.findtext('atom:summary', '', ns) or entry.findtext('atom:content', '', ns) or ""
                        pub_date = entry.findtext('atom:updated', '', ns) or entry.findtext('atom:published', '', ns) or ""

                        items.append(NewsItem(
                            title=strip_source_from_title(clean_html(title), source.name),
                            link=link,
                            summary=extract_summary(summary),
                            image=extract_image_from_html(summary),
                            source=source.name,
                            category=source.category,
                            timestamp=parse_date(pub_date),
                            date_str=pub_date,
                            lang=source.lang,
                        ))
                    except Exception as e:
                        log.debug(f"Parse atom error in {source.name}: {e}")
                        continue

        log.info(f"📰 {source.name}: {len(items)} items")

    except asyncio.TimeoutError:
        log.warning(f"📰 {source.name}: timeout ({source.timeout}s)")
    except Exception as e:
        log.warning(f"📰 {source.name}: {type(e).__name__}: {e}")

    return items


# ═══════════════════════════════════════════════════════════
# 🚀 Parallel Fetching
# ═══════════════════════════════════════════════════════════
async def fetch_all_news(max_concurrent: int = 5) -> List[NewsItem]:
    """جلب كل الأخبار بشكل متوازي مع semaphore"""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_with_limit(source):
        async with semaphore:
            # circuit breaker
            try:
                return await source.circuit_breaker.call(parse_rss_source, source)
            except Exception as e:
                log.warning(f"Circuit breaker for {source.name}: {e}")
                return []

    tasks = [fetch_with_limit(source) for source in NEWS_SOURCES.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for result in results:
        if isinstance(result, list):
            all_items.extend(result)

    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: x.timestamp, reverse=True)
    return all_items


# ═══════════════════════════════════════════════════════════
# 📊 ETF Flows (Async)
# ═══════════════════════════════════════════════════════════
_FARSIDE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _parse_farside_table(html: str, etf_type: str = "btc") -> Optional[Dict]:
    """تحليل جدول Farside"""
    tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not tables:
        return None

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tables[0], re.DOTALL | re.IGNORECASE)
    if len(rows) < 4:
        return None

    fund_cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', rows[1], re.DOTALL | re.IGNORECASE)
    fund_names = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ').replace('&amp;', '&').strip() 
                  for c in fund_cells]
    fund_names = [f for f in fund_names if f]

    data_start = 4 if etf_type == "eth" else 3
    latest_date = None
    latest_flows = None

    for row_idx in range(data_start, len(rows)):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', rows[row_idx], re.DOTALL | re.IGNORECASE)
        clean = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ').replace(',', '') for c in cells]
        if not clean:
            continue

        label = clean[0].strip()
        if label in ('Total', 'Average', 'Maximum', 'Minimum', 'Fee', 'Staking fee'):
            continue

        date_match = re.match(r'(\d{1,2})\s+(\w{3})\s+(\d{4})', label)
        if not date_match:
            continue

        total_str = clean[-1].strip() if clean else ''
        if total_str == '-' or total_str == '0.0' or not total_str:
            break

        latest_date = label
        latest_flows = clean[1:]

    if not latest_date or not latest_flows:
        return None

    funds = {}
    for i, name in enumerate(fund_names):
        if i < len(latest_flows):
            val_str = latest_flows[i].strip()
            if val_str and val_str != '-':
                try:
                    is_negative = val_str.startswith('(')
                    val_str = val_str.strip('()')
                    val = float(val_str)
                    funds[name.strip()] = -val if is_negative else val
                except ValueError:
                    funds[name.strip()] = 0.0

    total_str = latest_flows[-1].strip() if latest_flows else '0'
    try:
        is_negative = total_str.startswith('(')
        total_str = total_str.strip('()')
        net_total = float(total_str)
        if is_negative:
            net_total = -net_total
    except ValueError:
        net_total = 0.0

    return {"date": latest_date, "total": net_total, "funds": funds}


async def fetch_etf_flows() -> Optional[Dict]:
    """جلب بيانات ETF بشكل async"""
    result = {"date": None, "btc_total": 0.0, "eth_total": 0.0, "btc_funds": {}, "eth_funds": {}}

    await FARSIDE_RATE_LIMITER.acquire()

    try:
        session = await session_manager.get_session()

        # BTC
        try:
            async with session.get("https://farside.co.uk/btc/", timeout=ClientTimeout(total=15), headers=_FARSIDE_HEADERS) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    btc_data = _parse_farside_table(html, "btc")
                    if btc_data:
                        result["date"] = btc_data["date"]
                        result["btc_total"] = btc_data["total"]
                        result["btc_funds"] = btc_data["funds"]
                        log.info(f"✅ Farside BTC: {btc_data['date']} → {btc_data['total']}M")
        except Exception as e:
            log.warning(f"⚠️ Farside BTC: {e}")

        await FARSIDE_RATE_LIMITER.acquire()

        # ETH
        try:
            async with session.get("https://farside.co.uk/eth/", timeout=ClientTimeout(total=15), headers=_FARSIDE_HEADERS) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    eth_data = _parse_farside_table(html, "eth")
                    if eth_data:
                        if eth_data["date"] and (not result["date"] or eth_data["date"] >= result["date"]):
                            result["date"] = eth_data["date"]
                        result["eth_total"] = eth_data["total"]
                        result["eth_funds"] = eth_data["funds"]
                        log.info(f"✅ Farside ETH: {eth_data['date']} → {eth_data['total']}M")
        except Exception as e:
            log.warning(f"⚠️ Farside ETH: {e}")

    except Exception as e:
        log.warning(f"⚠️ ETF flows error: {e}")

    return result if result["date"] else None
