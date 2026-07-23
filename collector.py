"""
🐋 Whale News Bot v3 - جامع الأخبار (RSS Collector)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
هذه الوحدة مسؤولة فقط عن:
  1. جلب الأخبار من مصادر RSS (RSS 2.0 و Atom)
  2. جلب بيانات تدفقات ETF من farside.co.uk
  3. جلب التقويم الاقتصادي
لا تنظّف، لا تُصفّي، ولا تُعالج الأخبار — فقط تجمعها خام.
"""

import asyncio
import re
import time
import html
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector

# ═══════════════════════════════════════════════════════════
# 📦 الاستيرادات من المشروع
# ═══════════════════════════════════════════════════════════
from config import (
    log,
    NEWS_SOURCES,
    cfg,
    FARSIDE_RATE_LIMITER,
    FARSIDE_CB,
)

from models import NewsItem, SourceQuality

# رأس HTTP مخصص — نستخدمه بدلاً من أي شيء قادم من config
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/3.0)"}

# ═══════════════════════════════════════════════════════════
# ⚙️ ثوابت الوحدة
# ═══════════════════════════════════════════════════════════

MAX_ITEMS_PER_SOURCE: int = 15          # أقصى عدد أخبار من كل مصدر
CONCURRENCY_SEMAPHORE: int = 5         # حد الطلبات المتوازية
CONN_POOL_LIMIT: int = 50              # أقصى اتصالات في التجمع
CONN_PER_HOST_LIMIT: int = 10          # أقصى اتصال لكل مضيف
DNS_CACHE_TTL: int = 300               # كاش DNS — 5 دقائق
REQUEST_TIMEOUT: float = 20.0          # مهلة كل طلب HTTP
CB_FAIL_THRESHOLD: int = 3             # عتبة فشل قاطع الدائرة
CB_RESET_TIMEOUT: float = 300.0        # مدة إعادة تعيين قاطع الدائرة (5 دقائق)

# مساحات أسماء XML الشائعة — مهمة لتحليل Atom و media:content
XML_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss1": "http://purl.org/rss/1.0/",
}

# أنواع MIME المقبولة للصور
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}

# ═══════════════════════════════════════════════════════════
# 🗺️ خريطة مستوى الجودة → SourceQuality
# ═══════════════════════════════════════════════════════════
TIER_MAP: Dict[int, SourceQuality] = {
    1: SourceQuality.TIER_1,
    2: SourceQuality.TIER_2,
    3: SourceQuality.TIER_3,
}

# ═══════════════════════════════════════════════════════════
# 🌐 حالة الجلسة — مفردة على مستوى الوحدة
# ═══════════════════════════════════════════════════════════
_session: Optional[ClientSession] = None
_semaphore: Optional[asyncio.Semaphore] = None

# قواطع دوائر لكل مصدر RSS — منفصلة عن قواطع دوائر المشروع
_source_circuit_breakers: Dict[str, "CircuitBreaker"] = {}


# ═══════════════════════════════════════════════════════════
# 🪫 قاطع دائرة خفيف للاستخدام داخل الوحدة
# ═══════════════════════════════════════════════════════════
class _CircuitBreaker:
    """
    قاطع دائرة بسيط لكل مصدر RSS.
    يُمنع الطلب إذا فشل المصدر 3 مرات متتالية.
    يعود للحالة الطبيعية بعد 5 دقائق.
    """

    def __init__(self, name: str, fail_threshold: int = CB_FAIL_THRESHOLD,
                 reset_timeout: float = CB_RESET_TIMEOUT):
        self.name = name
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self._failures: int = 0
        self._last_failure: float = 0.0
        self._state: str = "closed"  # closed | open | half_open

    @property
    def is_open(self) -> bool:
        """هل قاطع الدائرة مفتوح (المصدر محظور)؟"""
        if self._state != "open":
            return False
        # نتحقق إن كان مضى وقت كافٍ لإعادة المحاولة
        if time.time() - self._last_failure >= self.reset_timeout:
            self._state = "half_open"
            return False
        return True

    def record_success(self) -> None:
        """تسجيل نجاح الطلب — إعادة تعيين العدّاد"""
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """تسجيل فشل الطلب — فتح القاطع عند تجاوز العتبة"""
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self.fail_threshold:
            self._state = "open"
            log.warning(
                f"⚡ قاطع الدائرة مفتوح للمصدر '{self.name}' "
                f"بعد {self._failures} إخفاقات — سيعاد بعد {self.reset_timeout:.0f}ث"
            )


# ═══════════════════════════════════════════════════════════
# 🏭 إدارة الجلسة والاتصالات
# ═══════════════════════════════════════════════════════════
def _get_or_create_session() -> ClientSession:
    """إنشاء أو إعادة استخدام جلسة aiohttp مفردة مع تجمع اتصالات"""
    global _session
    if _session is not None and not _session.closed:
        return _session

    # إعداد موزع الاتصالات — تجمع TCP متقدم
    connector = TCPConnector(
        limit=CONN_POOL_LIMIT,
        limit_per_host=CONN_PER_HOST_LIMIT,
        ttl_dns_cache=DNS_CACHE_TTL,
        use_dns_cache=True,
        force_close=False,
        enable_cleanup_closed=True,
        # تأخير إغلاق الاتصالات الخاملة للحفاظ على الأداء
        keepalive_timeout=30,
    )

    # مهلة عامة للجلسة
    timeout = ClientTimeout(
        total=REQUEST_TIMEOUT,
        connect=10.0,
        sock_read=15.0,
    )

    _session = ClientSession(
        connector=connector,
        timeout=timeout,
        headers=HEADERS,
        skip_auto_headers={"User-Agent"},
    )

    log.info(
        f"🌐 جلسة جديدة — تجمع اتصالات: limit={CONN_POOL_LIMIT}, "
        f"per_host={CONN_PER_HOST_LIMIT}, DNS_cache={DNS_CACHE_TTL}s"
    )
    return _session


async def close_session() -> None:
    """إغلاق جلسة aiohttp وتحرير الموارد"""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        log.info("🔒 تم إغلاق جلسة الجمع")
    _session = None


# ═══════════════════════════════════════════════════════════
# 📅 تحليل التواريخ — RSS / Atom / HTML
# ═══════════════════════════════════════════════════════════
# أنماط التاريخ الأكثر شيوعاً في البثّات RSS
_RFC822_PATTERN = re.compile(
    r"[A-Z][a-z]{2},\s+\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s*[A-Z]*"
)
_ISO8601_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)
_ISO8601_BASIC = re.compile(
    r"\d{8}T\d{6}"
)


def _parse_date(date_str: str) -> float:
    """
    تحويل سلسلة نصية للتاريخ إلى طابع زمني (epoch).
    يدعم: RFC 822, ISO 8601, وأنماط أخرى شائعة.
    في حال الفشل، يُرجع الطابع الزمني الحالي.
    """
    if not date_str or not date_str.strip():
        return time.time()

    date_str = date_str.strip()

    # محاولة 1: email.utils (RFC 822) — الأكثر شيوعاً في RSS 2.0
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, IndexError):
        pass

    # محاولة 2: fromisoformat — ISO 8601
    try:
        # Python 3.7+ يدعم fromisoformat جزئياً
        # نتعامل مع الحالة التي تحتوي على Z بدلاً من +00:00
        clean = date_str.replace("Z", "+00:00")
        # نزيل أجزاء الأجزاء الصغيرة إن وُجدت (microseconds)
        if "." in clean and "+" in clean:
            dot_idx = clean.index(".")
            plus_idx = clean.index("+")
            if plus_idx - dot_idx > 7:
                clean = clean[:dot_idx + 7] + clean[plus_idx:]
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError):
        pass

    # محاولة 3: أنماط يدوية — وقت Unix مباشر
    try:
        return float(date_str)
    except (ValueError, TypeError):
        pass

    # محاولة 4: سحب أول تاريخ قابل للتحليل من النص
    for pattern in [_RFC822_PATTERN, _ISO8601_PATTERN]:
        match = pattern.search(date_str)
        if match:
            return _parse_date(match.group())

    # فشل كل المحاولات — نستخدم الوقت الحالي
    log.debug(f"⏰ لم أتمكن من تحليل التاريخ: {date_str[:60]}")
    return time.time()


# ═══════════════════════════════════════════════════════════
# 🧹 تنظيف العناوين — إزالة اسم المصدر
# ═══════════════════════════════════════════════════════════
def _strip_source_from_title(title: str, source_name: str) -> str:
    """
    إزالة بادئة اسم المصدر من العنوان.
    مثال: "CoinDesk: Bitcoin rises" → "Bitcoin rises"
    """
    if not title or not source_name:
        return title or ""

    original = title

    # أنماط الإزالة: "Source: " أو "Source - " أو "[Source] "
    patterns = [
        re.compile(rf"^{re.escape(source_name)}\s*:\s*", re.IGNORECASE),
        re.compile(rf"^{re.escape(source_name)}\s*-\s*", re.IGNORECASE),
        re.compile(rf"^\[{re.escape(source_name)}\]\s*", re.IGNORECASE),
    ]

    for pattern in patterns:
        title = pattern.sub("", title).strip()

    return title if title else original


# ═══════════════════════════════════════════════════════════
# 🖼️ استخراج الصور من عنصر XML
# ═══════════════════════════════════════════════════════════
def _extract_image(item_element: ET.Element) -> str:
    """
    استخراج رابط الصورة الأول المناسب من عنصر RSS/Atom.
    يبحث في: <img>, <media:content>, <enclosure>, <content:encoded>
    """
    # 1. علامة <media:content> — الأكثر شيوعاً في بثّات Atom المتقدمة
    media_content = item_element.find("media:content", XML_NAMESPACES)
    if media_content is not None:
        url = media_content.get("url", "").strip()
        if url and _is_valid_image_url(url):
            return url
        medium = media_content.get("medium", "")
        mime = media_content.get("type", "")
        if (medium == "image" or mime in IMAGE_MIME_TYPES) and url:
            return url

    # 2. علامة <media:thumbnail>
    media_thumb = item_element.find("media:thumbnail", XML_NAMESPACES)
    if media_thumb is not None:
        url = media_thumb.get("url", "").strip()
        if url and _is_valid_image_url(url):
            return url

    # 3. علامة <enclosure> — شائعة في RSS 2.0
    enclosure = item_element.find("enclosure")
    if enclosure is not None:
        url = enclosure.get("url", "").strip()
        mime = enclosure.get("type", "").lower()
        if url and mime in IMAGE_MIME_TYPES:
            return url

    # 4. علامة <content:encoded> — تحتوي HTML
    content_encoded = item_element.find("content:encoded", XML_NAMESPACES)
    if content_encoded is not None and content_encoded.text:
        img_match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']', content_encoded.text
        )
        if img_match:
            return img_match.group(1).strip()

    # 5. علامة <description> — قد تحتوي HTML
    description = item_element.find("description")
    if description is not None and description.text:
        img_match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']', description.text
        )
        if img_match:
            return img_match.group(1).strip()

    # 6. علامة <summary> — Atom
    summary = item_element.find("summary")
    if summary is not None and summary.text:
        img_match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']', summary.text
        )
        if img_match:
            return img_match.group(1).strip()

    # 7. داخل <link rel="enclosure"> في Atom
    for link_el in item_element.findall("link"):
        rel = link_el.get("rel", "")
        mime = link_el.get("type", "").lower()
        href = link_el.get("href", "")
        if (rel == "enclosure" and mime in IMAGE_MIME_TYPES) and href:
            return href.strip()

    return ""


def _is_valid_image_url(url: str) -> bool:
    """تحقق بسيط أن الرابط يشبه صورة"""
    if not url or len(url) < 10:
        return False
    # نرفض البيانات المحلية و SVG بلا امتداد واضح
    if url.startswith("data:"):
        return False
    return True


# ═══════════════════════════════════════════════════════════
# 📡 تحليل بثّ RSS / Atom
# ═══════════════════════════════════════════════════════════
def _detect_feed_type(root: ET.Element) -> str:
    """
    تحديد نوع البث: RSS 1.0 (RDF), RSS 2.0, أو Atom.
    """
    tag = root.tag.lower()
    if tag == "{http://www.w3.org/2005/atom}feed" or tag.endswith("}feed"):
        return "atom"
    if tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}rss":
        return "rdf"
    # RSS 2.0 أو ما شابه
    return "rss"


def _parse_rss_items(root: ET.Element, source_name: str,
                     category: str, lang: str, tier: int) -> List[NewsItem]:
    """
    تحليل عنصر <rss> أو <RDF> واستخراج الأخبار.
    يدعم RSS 1.0 و RSS 2.0.
    """
    items: List[NewsItem] = []
    source_quality = TIER_MAP.get(tier, SourceQuality.TIER_3)

    # RSS 2.0 — العناصر داخل <channel>/<item>
    channel = root.find("channel")
    if channel is not None:
        raw_items = channel.findall("item")
    else:
        # RSS 1.0 (RDF) — العناصر مباشرة تحت الجذر
        raw_items = root.findall("item", XML_NAMESPACES)
        if not raw_items:
            raw_items = root.findall("rss1:item", XML_NAMESPACES)

    for elem in raw_items[:MAX_ITEMS_PER_SOURCE]:
        try:
            item = _parse_rss_item(elem, source_name, category, lang, source_quality)
            if item is not None:
                items.append(item)
        except Exception as e:
            log.debug(f"⚠️ خطأ في تحليل عنصر RSS من {source_name}: {e}")
            continue

    return items


def _parse_atom_items(root: ET.Element, source_name: str,
                     category: str, lang: str, tier: int) -> List[NewsItem]:
    """
    تحليل بث Atom واستخراج الأخبار.
    """
    items: List[NewsItem] = []
    source_quality = TIER_MAP.get(tier, SourceQuality.TIER_3)

    raw_items = root.findall("entry") or root.findall("atom:entry", XML_NAMESPACES)

    for elem in raw_items[:MAX_ITEMS_PER_SOURCE]:
        try:
            item = _parse_atom_entry(elem, source_name, category, lang, source_quality)
            if item is not None:
                items.append(item)
        except Exception as e:
            log.debug(f"⚠️ خطأ في تحليل عنصر Atom من {source_name}: {e}")
            continue

    return items


def _parse_rss_item(elem: ET.Element, source_name: str,
                   category: str, lang: str,
                   source_quality: SourceQuality) -> Optional[NewsItem]:
    """تحويل عنصر <item> RSS واحد إلى NewsItem"""
    # --- العنوان ---
    title_elem = elem.find("title")
    title = title_elem.text if title_elem is not None and title_elem.text else ""
    if not title or len(title.strip()) < 5:
        return None
    title = html.unescape(title).strip()

    # --- الرابط ---
    link_elem = elem.find("link")
    link = ""
    if link_elem is not None:
        link = (link_elem.text or link_elem.get("href", "")).strip()

    # --- الملخص ---
    summary_elem = elem.find("description")
    summary = ""
    if summary_elem is not None and summary_elem.text:
        summary = html.unescape(summary_elem.text.strip())
        # نزيل وسوم HTML إن وُجدت للحصول على نص نظيف كملخص
        summary = re.sub(r"<[^>]+>", "", summary).strip()

    # --- التاريخ ---
    pub_date_elem = elem.find("pubDate")
    pub_date = ""
    if pub_date_elem is not None and pub_date_elem.text:
        pub_date = pub_date_elem.text.strip()
    # بديل: dc:date
    if not pub_date:
        dc_date = elem.find("dc:date", XML_NAMESPACES)
        if dc_date is not None and dc_date.text:
            pub_date = dc_date.text.strip()

    timestamp = _parse_date(pub_date) if pub_date else time.time()

    # --- الصورة ---
    image = _extract_image(elem)

    # --- تنظيف العنوان من اسم المصدر ---
    clean_title = _strip_source_from_title(title, source_name)

    return NewsItem(
        title=clean_title,
        link=link,
        summary=summary,
        image=image,
        source=source_name,
        source_quality=source_quality,
        category=category,
        timestamp=timestamp,
        lang=lang,
    )


def _parse_atom_entry(elem: ET.Element, source_name: str,
                      category: str, lang: str,
                      source_quality: SourceQuality) -> Optional[NewsItem]:
    """تحويل عنصر <entry> Atom واحد إلى NewsItem"""
    # --- العنوان ---
    title_elem = elem.find("title") or elem.find("atom:title", XML_NAMESPACES)
    title = title_elem.text if title_elem is not None and title_elem.text else ""
    if not title or len(title.strip()) < 5:
        return None
    title = html.unescape(title).strip()

    # --- الرابط (Atom يستخدم <link href="..."> بدون نص) ---
    link = ""
    for link_elem in elem.findall("link"):
        rel = link_elem.get("rel", "alternate")
        href = link_elem.get("href", "")
        mime = link_elem.get("type", "")
        # نفضّل alternate أو أي رابط HTML
        if href and (rel == "alternate" or rel == "self" or not rel):
            if not link or rel == "alternate":
                link = href.strip()
            if not link:
                link = href.strip()

    # --- الملخص ---
    summary_elem = (elem.find("summary") or
                    elem.find("atom:summary", XML_NAMESPACES) or
                    elem.find("content") or
                    elem.find("atom:content", XML_NAMESPACES))
    summary = ""
    if summary_elem is not None and summary_elem.text:
        summary = html.unescape(summary_elem.text.strip())
        summary = re.sub(r"<[^>]+>", "", summary).strip()

    # --- التاريخ ---
    # Atom يستخدم <updated> أو <published> أو <published> أو <updated>
    date_elem = (elem.find("published") or
                 elem.find("atom:published", XML_NAMESPACES) or
                 elem.find("updated") or
                 elem.find("atom:updated", XML_NAMESPACES))
    pub_date = date_elem.text.strip() if date_elem is not None and date_elem.text else ""
    timestamp = _parse_date(pub_date) if pub_date else time.time()

    # --- الصورة ---
    image = _extract_image(elem)

    # --- تنظيف العنوان من اسم المصدر ---
    clean_title = _strip_source_from_title(title, source_name)

    return NewsItem(
        title=clean_title,
        link=link,
        summary=summary,
        image=image,
        source=source_name,
        source_quality=source_quality,
        category=category,
        timestamp=timestamp,
        lang=lang,
    )


# ═══════════════════════════════════════════════════════════
# 🔌 جلب مصدر واحد
# ═══════════════════════════════════════════════════════════
async def _fetch_single_source(source_name: str, source_info: Dict) -> List[NewsItem]:
    """
    جلب الأخبار من مصدر RSS واحد.
    يتضمن: قاطع دائرة، طلب HTTP، تحليل XML.
    """
    url = source_info.get("url", "")
    if not url:
        return []

    category = source_info.get("category", "general")
    lang = source_info.get("lang", "en")
    tier = source_info.get("tier", 3)

    # --- قاطع الدائرة ---
    cb = _source_circuit_breakers.get(source_name)
    if cb and cb.is_open:
        log.debug(f"⚡ قاطع الدائرة مفتوح — تخطي '{source_name}'")
        return []

    session = _get_or_create_session()

    try:
        # --- احترام إشارة التزامن ---
        sem = _get_semaphore()
        async with sem:
            async with session.get(url) as response:
                if response.status != 200:
                    log.warning(
                        f"❌ {source_name}: HTTP {response.status} — {url[:80]}"
                    )
                    if cb:
                        cb.record_failure()
                    return []

                # التحقق من نوع المحتوى
                content_type = response.headers.get("Content-Type", "").lower()
                if "xml" not in content_type and "rss" not in content_type:
                    log.debug(
                        f"⚠️ {source_name}: نوع محتوى غير متوقع: {content_type}"
                    )

                raw_xml = await response.text(errors="replace")

    except asyncio.TimeoutError:
        log.warning(f"⏱️ مهلة جلب '{source_name}' — {url[:80]}")
        if cb:
            cb.record_failure()
        return []
    except aiohttp.ClientError as e:
        log.warning(f"🔌 خطأ اتصال لـ '{source_name}': {e}")
        if cb:
            cb.record_failure()
        return []
    except Exception as e:
        log.error(f"💥 خطأ غير متوقع في جلب '{source_name}': {e}")
        if cb:
            cb.record_failure()
        return []

    # --- تحليل XML ---
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        log.warning(f"📄 خطأ تحليل XML من '{source_name}': {e}")
        if cb:
            cb.record_failure()
        return []

    # نجاح — نُسجّله في قاطع الدائرة
    if cb:
        cb.record_success()

    # --- تحديد نوع البث واستخراج العناصر ---
    feed_type = _detect_feed_type(root)

    if feed_type == "atom":
        items = _parse_atom_items(root, source_name, category, lang, tier)
    else:
        items = _parse_rss_items(root, source_name, category, lang, tier)

    log.info(f"📡 {source_name}: {len(items)} عنصر ({feed_type}) — {url[:60]}")
    return items


def _get_semaphore() -> asyncio.Semaphore:
    """الحصول على إشارة التزامن أو إنشاء واحدة جديدة"""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(CONCURRENCY_SEMAPHORE)
    return _semaphore


# ═══════════════════════════════════════════════════════════
# 📰 الوظائف العامة — جلب كل الأخبار
# ═══════════════════════════════════════════════════════════
async def fetch_all_news() -> List[NewsItem]:
    """
    جلب الأخبار من كل مصادر RSS بشكل متوازي.
    يُرجع قائمة مسطّحة بكل NewsItem بلا ترتيب مضمون.
    """
    log.info(f"📡 بدء جلب الأخبار من {len(NEWS_SOURCES)} مصدر...")

    # إنشاء قواطع الدوائر لكل مصدر إن لم تكن موجودة
    for name in NEWS_SOURCES:
        if name not in _source_circuit_breakers:
            _source_circuit_breakers[name] = _CircuitBreaker(name)

    # تجميع المهام المتوازية
    tasks = []
    for source_name, source_info in NEWS_SOURCES.items():
        tasks.append(
            _fetch_single_source(source_name, source_info)
        )

    # تنفيذ المتوازي — نستخدم gather مع return_exceptions لعدم قطع الباقي
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # تجميع النتائج
    all_items: List[NewsItem] = []
    success_count = 0
    fail_count = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            source_name = list(NEWS_SOURCES.keys())[i]
            log.error(f"💥 فشل غير متوقع في جلب '{source_name}': {result}")
            fail_count += 1
        elif isinstance(result, list):
            all_items.extend(result)
            if result:
                success_count += 1
        else:
            fail_count += 1

    log.info(
        f"📡 انتهى الجمع: {len(all_items)} خبر خام | "
        f"✅ {success_count} مصدر نجح | ❌ {fail_count} فشل"
    )

    return all_items


# ═══════════════════════════════════════════════════════════
# 💰 جلب بيانات تدفقات ETF
# ═══════════════════════════════════════════════════════════
_FARSIDE_URLS = {
    "btc": "https://www.farside.co.uk/btc/",
    "eth": "https://www.farside.co.uk/eth/",
}


async def fetch_etf_flows() -> Optional[Dict]:
    """
    جلب بيانات تدفقات ETF من farside.co.uk.
    يُرجع قاموساً يحتوي بيانات BTC و ETH أو None عند الفشل.
    يستخدم FARSIDE_CB و FARSIDE_RATE_LIMITER من config.
    """
    result: Dict[str, Any] = {"btc": [], "eth": [], "timestamp": time.time()}

    for asset, url in _FARSIDE_URLS.items():
        try:
            data = await _fetch_farside_table(asset, url)
            result[asset] = data
        except Exception as e:
            log.warning(f"💰 خطأ في جلب تدفقات ETF {asset.upper()}: {e}")

    # نتحقق إن كان لدينا أي بيانات
    total_rows = len(result.get("btc", [])) + len(result.get("eth", []))
    if total_rows == 0:
        log.debug("💰 لا توجد بيانات تدفقات ETF متاحة")
        return None

    log.info(f"💰 تدفقات ETF: {len(result.get('btc', []))} BTC + "
             f"{len(result.get('eth', []))} ETH صف")
    return result


async def _fetch_farside_table(asset: str, url: str) -> List[Dict]:
    """
    جلب وتحليل صفحة واحدة من farside.co.uk.
    يُرجع قائمة بالصفوف: [{"date": "...", "fund": "...", "flow": "..."}]
    """
    # احترام محدد المعدّل وقاطع الدائرة
    await FARSIDE_RATE_LIMITER.acquire()

    session = _get_or_create_session()

    try:
        async with FARSIDE_CB.call(session.get, url) as response:
            if response.status != 200:
                log.warning(f"💰 farside {asset}: HTTP {response.status}")
                return []

            raw_html = await response.text(errors="replace")
    except RuntimeError as e:
        # قاطع الدائرة مفتوح
        log.warning(f"⚡ قاطع الدائرة مفتوح لـ farside {asset}: {e}")
        return []
    except Exception as e:
        log.warning(f"💰 خطأ في جلب farside {asset}: {e}")
        return []

    # --- تحليل جدول HTML ---
    return _parse_farside_html(raw_html, asset)


def _parse_farside_html(html_text: str, asset: str) -> List[Dict]:
    """
    تحليل HTML من farside.co.uk واستخراج جدول التدفقات.
    كل صف يحتوي: التاريخ | اسم الصندوق | قيمة التدفق
    """
    rows: List[Dict] = []

    try:
        # نبحث عن الجداول — farside تستخدم جداول HTML بسيطة
        # نمط: <table> ... <tr> ... </tr> ... </table>
        table_pattern = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)

        tables = table_pattern.findall(html_text)
        if not tables:
            log.debug(f"💰 لا توجد جداول في صفحة farside {asset}")
            return rows

        # نأخذ آخر جدول عادةً (الأحدث)
        table_html = tables[-1] if len(tables) > 1 else tables[0]
        tr_matches = row_pattern.findall(table_html)

        for tr_html in tr_matches:
            cells = cell_pattern.findall(tr_html)
            if len(cells) < 2:
                continue

            # تنظيف خلايا HTML
            clean_cells = []
            for cell in cells:
                clean = re.sub(r"<[^>]+>", "", cell).strip()
                clean = html.unescape(clean)
                clean_cells.append(clean)

            # أول خلية عادةً التاريخ، الباقي أسماء الصناديق والقيم
            # في farside: Date | Fund1 | Fund2 | Fund3 | ...
            if len(clean_cells) < 2:
                continue

            date_val = clean_cells[0]
            if not date_val or len(date_val) < 4:
                continue  # رأس الجدول أو صف فارغ

            # كل خلية بعد التاريخ تمثل صندوقاً
            # لكن في farside الأعمدة ثابتة — نحتاج الأسماء من رأس الجدول
            # نبني سجلاً مبسطاً: التاريخ + الصف الكامل
            row_data = {
                "date": date_val,
                "asset": asset,
                "raw_values": clean_cells[1:],
                "funds": {},
            }

            # نحاول مطابقة الأعمدة مع الأسماء المعروفة
            # الصفوف بعد الرأس: التاريخ + قيمة لكل صندوق
            rows.append(row_data)

    except Exception as e:
        log.warning(f"💰 خطأ في تحليل HTML لـ farside {asset}: {e}")

    return rows


# ═══════════════════════════════════════════════════════════
# 📅 جلب التقويم الاقتصادي
# ═══════════════════════════════════════════════════════════
# مصادر التقويم الاقتصادي (يمكن إضافتها للمشروع لاحقاً)
_ECON_CALENDAR_URLS = [
    "https://www.forexfactory.com/calendar",
]

async def fetch_economic_calendar() -> List[Dict]:
    """
    جلب أحداث التقويم الاقتصادي.
    حالياً يُرجع قائمة فارغة أو بيانات محدودة.
    يمكن توسيعه باستخدام API متخصص مثل Investing.com أو ForexFactory.
    """
    log.debug("📅 جلب التقويم الاقتصادي...")

    events: List[Dict] = []

    for url in _ECON_CALENDAR_URLS:
        try:
            session = _get_or_create_session()
            sem = _get_semaphore()

            async with sem:
                async with session.get(url) as response:
                    if response.status != 200:
                        log.debug(f"📅 تقويم: HTTP {response.status}")
                        continue

                    raw_html = await response.text(errors="replace")
                    parsed = _parse_economic_calendar_html(raw_html)

                    if parsed:
                        events.extend(parsed)
                        log.info(f"📅 التقويم الاقتصادي: {len(parsed)} حدث")
                        break  # نكتفي بأول مصدر ناجح

        except Exception as e:
            log.debug(f"📅 خطأ في جلب التقويم الاقتصادي: {e}")
            continue

    return events


def _parse_economic_calendar_html(html_text: str) -> List[Dict]:
    """
    تحليل HTML بسيط لاستخراج أحداث التقويم.
    هذا محلل بدائي — يُحسّن لاحقاً باستخدام API متخصص.
    """
    events: List[Dict] = []

    # نمط بسيط لاستخراج الأحداث — يعتمد على بنية forexfactory
    # في الإنتاج: استخدم API متخصص مثل tradingeconomics.com
    event_pattern = re.compile(
        r"calendar__event\b[^>]*>.*?"
        r"calendar__date[^>]*>(?P<date>[^<]+)<.*?"
        r"calendar__currency[^>]*>(?P<currency>[^<]+)<.*?"
        r"calendar__event-title[^>]*>(?P<title>[^<]+)<.*?"
        r"calendar__impact[^>]*>(?P<impact>[^<]*)<.*?"
        r"calendar__actual[^>]*>(?P<actual>[^<]*)<.*?"
        r"calendar__forecast[^>]*>(?P<forecast>[^<]*)<",
        re.DOTALL | re.IGNORECASE
    )

    # محاولة استخراج أي جداول بيانات اقتصادية موجودة
    # بديل: نبحث عن أنماط نصية شائعة
    high_impact_keywords = [
        "CPI", "PPI", "NFP", "GDP", "FOMC", "Rate Decision",
        "Employment", "Inflation", "PMI", "PCE",
    ]

    for match in event_pattern.finditer(html_text):
        try:
            event = {
                "date": html.unescape(match.group("date").strip()),
                "currency": html.unescape(match.group("currency").strip()),
                "title": html.unescape(match.group("title").strip()),
                "impact": html.unescape(match.group("impact").strip()),
                "actual": html.unescape(match.group("actual").strip()),
                "forecast": html.unescape(match.group("forecast").strip()),
            }
            if event["title"] and len(event["title"]) > 3:
                events.append(event)
        except (AttributeError, IndexError):
            continue

    return events


# ═══════════════════════════════════════════════════════════
# 🧪 للتصحيح والاختبار
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    async def _main():
        """اختبار سريع لكل وظائف الجمع"""
        log.info("🧪 تشغيل اختبار الجمع...")

        # 1. جلب الأخبار
        news = await fetch_all_news()
        log.info(f"📰 النتيجة: {len(news)} خبر")
        for item in news[:3]:
            log.info(f"  • [{item.source}] {item.title[:60]}")

        # 2. جلب تدفقات ETF
        etf = await fetch_etf_flows()
        if etf:
            log.info(f"💰 ETF: BTC={len(etf.get('btc', []))} ETH={len(etf.get('eth', []))}")
        else:
            log.info("💰 ETF: لا بيانات متاحة")

        # 3. التقويم الاقتصادي
        cal = await fetch_economic_calendar()
        log.info(f"📅 التقويم: {len(cal)} حدث")

        # إغلاق الجلسة
        await close_session()

    asyncio.run(_main())
