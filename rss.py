import re, time, hashlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

from config import (log, tz, NEWS_SOURCES, HEADERS, REDDIT_HEADERS, get_cached, set_cached)
from filters import classify_news


def parse_date(date_str):
    """يحول تاريخ RSS إلى timestamp
    دعم صيغ متعددة (RFC 822, ISO 8601, Atom)
    """
    if not date_str:
        return 0
    # محاولة RFC 822 أولاً (الأكثر شيوعاً في RSS)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.timestamp()
    except Exception:
        pass
    # محاولة ISO 8601 (مثل 2024-07-01T12:00:00Z)
    try:
        # إزالة Z في النهاية إن وُجد
        clean = date_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    # محاولة صيغ أخرى شائعة
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.timestamp()
        except Exception:
            pass
    return 0


def clean_html(text):
    """يزيل HTML tags من النص"""
    if not text:
        return ""
    # إزالة HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # إزالة HTML entities شائعة
    clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # اختصار المسافات
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def extract_summary(text, max_len=200):
    """يختصر النص"""
    clean = clean_html(text)
    if len(clean) <= max_len:
        return clean
    return clean[:max_len-3] + "..."


def extract_image_from_html(html_text):
    """يستخرج رابط الصورة من HTML في RSS"""
    if not html_text:
        return ""
    # البحث عن <img src="...">
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    if match:
        return match.group(1)
    # البحث عن enclosure (مستخدم في بعض RSS)
    return ""


def _strip_source_from_title(title, source_name=""):
    """يزيل اسم المصدر من نهاية العنوان
    بعض مصادر RSS تضيف اسم المصدر في نهاية العنوان مثل:
    "Senate CLARITY Act... - Dow Jones" أو "Bitcoin crashes | CoinDesk"
    """
    if not title or not source_name:
        return title
    cleaned = title
    # أنماط شائعة: " - Dow Jones" أو " | CoinDesk" أو " — InvestingLive"
    # نبحث عن اسم المصدر في النهاية مع فاصل
    source_lower = source_name.lower()
    cleaned_lower = cleaned.lower()
    # أنماط الفواصل الشائعة
    separators = [" - ", " | ", " — ", " – ", " :: "]
    for sep in separators:
        if sep in cleaned_lower:
            parts = cleaned_lower.rsplit(sep, 1)
            if len(parts) == 2:
                last_part = parts[1].strip()
                # لو الجزء الأخير يحتوي على اسم المصدر (أو العكس)
                if (source_lower in last_part or last_part in source_lower
                    or len(last_part) < 30):  # جزء قصير = على الأغلب اسم المصدر
                    # أعد النص الأصلي بدون الجزء الأخير
                    idx = cleaned_lower.rfind(sep)
                    if idx > 10:  # تأكد أن العنوان ليس قصيراً جداً
                        cleaned = cleaned[:idx].strip()
                        break
    return cleaned


def parse_rss_source(source_name, source_info):
    """يجلب ويحلل RSS source واحد
    🔧 عزل كامل: أي خطأ في هذا المصدر لا يؤثر على البقية
    🔧 تسجيل سبب الفشل التفصيلي في السجل
    """
    url = source_info["url"]
    category = source_info["category"]
    is_json = source_info.get("is_json", False)
    is_reddit_rss = source_info.get("is_reddit_rss", False)
    items = []
    try:
        if is_json:
            # Reddit JSON
            r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for post in data.get("data", {}).get("children", [])[:20]:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    link = "https://www.reddit.com" + d.get("permalink", "")
                    pub_ts = d.get("created_utc", 0)
                    # استخراج الصورة من Reddit
                    image = ""
                    if d.get("preview"):
                        try:
                            image = d["preview"]["images"][0]["source"]["url"].replace("&amp;", "&")
                        except:
                            pass
                    if not image and d.get("thumbnail", "").startswith("http"):
                        image = d.get("thumbnail")
                    items.append({
                        "title": title,
                        "link": link,
                        "summary": d.get("selftext", "")[:200],
                        "image": image,
                        "source": source_name,
                        "category": category,
                        "timestamp": pub_ts,
                        "date_str": datetime.fromtimestamp(pub_ts, tz=tz).strftime('%Y-%m-%d %H:%M') if pub_ts else ""
                    })
        else:
            # RSS XML
            headers_to_use = REDDIT_HEADERS if is_reddit_rss else HEADERS
            r = requests.get(url, headers=headers_to_use, timeout=15)
            # Reddit قد يرجع 429 لكن مع محتوى صالح
            if r.status_code == 200 or (is_reddit_rss and r.status_code == 429 and r.text):
                root = ET.fromstring(r.content)
                # RSS 2.0
                for item in root.findall('.//item')[:20]:
                    title = item.findtext('title', '') or ""
                    link = item.findtext('link', '') or ""
                    desc = item.findtext('description', '') or ""
                    pub_date = item.findtext('pubDate', '') or ""
                    # استخراج الصورة
                    image = extract_image_from_html(desc)
                    # محاولة استخراج من media:content أو enclosure
                    if not image:
                        media = item.find('{http://search.yahoo.com/mrss/}content')
                        if media is not None and media.get('url'):
                            image = media.get('url')
                    if not image:
                        enclosure = item.find('enclosure')
                        if enclosure is not None and enclosure.get('type', '').startswith('image'):
                            image = enclosure.get('url')
                    items.append({
                        "title": _strip_source_from_title(clean_html(title), source_name),
                        "link": link,
                        "summary": extract_summary(desc),
                        "image": image,
                        "source": source_name,
                        "category": category,
                        "timestamp": parse_date(pub_date),
                        "date_str": pub_date
                    })
                # Atom (مثل some feeds)
                if not items:
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    for entry in root.findall('.//atom:entry', ns)[:20]:
                        title = entry.findtext('atom:title', '', ns) or ""
                        link_elem = entry.find('atom:link', ns)
                        link = link_elem.get('href', '') if link_elem is not None else ""
                        summary = entry.findtext('atom:summary', '', ns) or entry.findtext('atom:content', '', ns) or ""
                        pub_date = entry.findtext('atom:updated', '', ns) or entry.findtext('atom:published', '', ns) or ""
                        # استخراج الصورة من Atom
                        image = extract_image_from_html(summary)
                        items.append({
                            "title": _strip_source_from_title(clean_html(title), source_name),
                            "link": link,
                            "summary": extract_summary(summary),
                            "image": image,
                            "source": source_name,
                            "category": category,
                            "timestamp": parse_date(pub_date),
                            "date_str": pub_date
                        })
            else:
                log.warning(f"📰 {source_name}: HTTP {r.status_code} — فشل الاتصال")
        log.info(f"📰 {source_name}: {len(items)} items")
    except requests.exceptions.Timeout:
        log.warning(f"📰 {source_name}: timeout (15s) — المصدر بطيء")
    except requests.exceptions.ConnectionError as e:
        log.warning(f"📰 {source_name}: connection error — {type(e).__name__}")
    except ET.ParseError as e:
        log.warning(f"📰 {source_name}: XML parse error — قد لا يكون RSS صالح")
    except Exception as e:
        log.warning(f"📰 {source_name}: {type(e).__name__}: {e}")
    return items


def get_all_news():
    """يجلب كل الأخبار من كل المصادر
    🔧 عزل كامل: تعطل أي مصدر لا يؤثر على البقية
    🔧 كل مصدر يُفحص بالتساوي مع try/except منفصل
    """
    cached = get_cached("all_news", 120)  # كاش دقيقتين
    if cached:
        return cached
    all_items = []
    for source_name, source_info in NEWS_SOURCES.items():
        try:
            items = parse_rss_source(source_name, source_info)
            all_items.extend(items)
        except Exception as e:
            log.warning(f"📰 {source_name}: فشل غير متوقع في الدالة الخارجية — {type(e).__name__}: {e}")
        # تأخير بسيط بين المصادر
        time.sleep(0.3)
    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    set_cached("all_news", all_items)
    return all_items


def deduplicate_news(news_list):
    """إزالة الأخبار المكررة عبر مصادر مختلفة
    🔧 محسّن: يمنع نفس الخبر من عدة مواقع، لكن لا يعتبر خبرين
       مختلفين مكررين بسبب تشابه جزئي في العنوان.
       مقارنة أول 40 حرف فقط عبر المصادر، و 80 حرف لنفس المصدر.
    """
    seen = set()       # (normalized_key) → عناوين متطابقة جداً
    seen_cross = set() # (normalized_key) بدون مصدر → لمنع التكرار عبر المصادر
    unique = []
    for item in news_list:
        title = item.get("title", "").lower().strip()
        source = item.get("source", "").lower()
        # تطبيع: إزالة الرموز والمسافات الزائدة
        normalized = re.sub(r'[^\w\s]', '', title)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # إزالة الكلمات الشائعة في البداية
        normalized = re.sub(r'^(breaking|update|news|alert|urgent|just in|report|analysis)[\s:]*', '', normalized)
        if not normalized:
            continue
        # مفتاح صارم: نفس المصدر + أول 80 حرف
        strict_key = f"{normalized[:80]}|{source}"
        # مفتاح متقاطع: بدون مصدر، أول 40 حرف فقط
        cross_key = normalized[:40]

        # (1) نفس المصدر + نفس العنوان → مكرر دائماً
        if strict_key in seen:
            continue
        # (2) مصدر مختلف + أول 40 حرف متطابقة → مكرر عبر مصادر
        if cross_key in seen_cross:
            continue

        seen.add(strict_key)
        seen_cross.add(cross_key)
        unique.append(item)
    return unique


def news_hash(item):
    """hash فريد للخبر
    🔧 محسّن: لا يعتمد على المصدر — حتى لو نفس الخبر جاء من مصدرين
       مختلفين، يُعتبر مكرراً (لمنع إرساله مرتين).
    """
    title = item.get("title", "").lower().strip()
    # تطبيع: إزالة الرموز والمسافات الزائدة
    normalized = re.sub(r'[^\w\s]', '', title)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    # إزالة الكلمات الشائعة في البداية
    normalized = re.sub(r'^(breaking|update|news|alert|urgent|just in|report)[\s:]*', '', normalized)
    # hash بدون مصدر — نفس الخبر من مصدرين = نفس الخبر
    hash_input = normalized[:50]
    return hashlib.md5(hash_input.encode()).hexdigest()[:12]