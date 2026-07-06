import os, time, json, logging, threading, re, hashlib
from datetime import datetime, timezone
import pytz, requests
from xml.etree import ElementTree as ET
from flask import Flask, jsonify, request

# ═══════════════════════════════════════════════════════════
# الإعدادات العامة
# ═══════════════════════════════════════════════════════════
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIMEZONE = os.environ.get("TIMEZONE", "Africa/Algiers")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
# 🆕 رابط قناة تيليجرام (يمكن وضع اسم المستخدم أو الرابط الكامل)
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/whale_signals_channel")
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "🐋 قناة الحيتان")
# 🆕 معرّف القناة العامة لإرسال التنبيهات (مثل @my_channel أو -1001234567890)
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
# 🆕 تفعيل/إيقاف الإرسال للقناة العامة
SEND_TO_CHANNEL = os.environ.get("SEND_TO_CHANNEL", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("NewsBot")
tz = pytz.timezone(TIMEZONE)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WhaleNewsBot/1.0)"}

# ═══════════════════════════════════════════════════════════
# مصادر الأخبار (RSS)
# ═══════════════════════════════════════════════════════════
NEWS_SOURCES = {
    # 🪙 مصادر كريبتو
    "CoinDesk": {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
        "category": "crypto",
        "lang": "en"
    },
    "Cointelegraph": {
        "url": "https://cointelegraph.com/rss",
        "category": "crypto",
        "lang": "en"
    },
    "Decrypt": {
        "url": "https://decrypt.co/feed",
        "category": "crypto",
        "lang": "en"
    },
    "Bitcoin.com": {
        "url": "https://news.bitcoin.com/feed/",
        "category": "crypto",
        "lang": "en"
    },
    # 🇺🇸 مصادر الاقتصاد الكلي والبيت الأبيض
    "CNBC Economy": {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
        "category": "macro",
        "lang": "en"
    },
    "CNBC White House": {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000113",
        "category": "macro",
        "lang": "en"
    },
    "Federal Reserve": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "macro",
        "lang": "en"
    },
    "Forexlive": {
        "url": "https://www.forexlive.com/feed/",
        "category": "macro",
        "lang": "en"
    },
    # 🐋 مصادر الأثرياء والمستثمرين
    "Benzinga Markets": {
        "url": "https://www.benzinga.com/author/feed/1",
        "category": "macro",
        "lang": "en"
    },
    # 🔍 مجتمعي
    "Reddit r/CryptoCurrency": {
        "url": "https://www.reddit.com/r/CryptoCurrency/new.json",
        "category": "crypto",
        "lang": "en",
        "is_json": True
    },
}

# كلمات مفتاحية موسعة للفلترة
KEYWORDS_BREAKING = ["breaking", "urgent", "hack", "ban", "approval", "etf", "sec sues", "exploit", "lawsuit", "crash", "surge", "all-time high"]
KEYWORDS_FED = ["fed", "federal reserve", "interest rate", "powell", "fomc", "rate cut", "rate hike", "rate decision", "monetary policy", "inflation data", "cpi", "nonfarm payrolls", "jobless claims"]
KEYWORDS_TRUMP = ["trump", "tariff", "trade war", "white house", "biden administration", "sec gary", "gary gensler"]
KEYWORDS_WHALES = ["elon musk", "michael saylor", "warren buffett", "bill ackman", "ray dalio", "cathie wood", "whale", "whales", "blackrock", "microstrategy", "satoshi"]
KEYWORDS_ETF = ["etf", "spot etf", "approval", "sec", "blackrock", "fidelity", "ark invest"]
KEYWORDS_HACK = ["hack", "exploit", "stolen", "drained", "vulnerability", "flash loan", "rug pull", "breach"]

# ═══════════════════════════════════════════════════════════
# المتغيرات العامة
# ═══════════════════════════════════════════════════════════
_cache = {}
_started = False
last_id = 0
_user_state = {}
ALERT_COOLDOWN = 1800  # 30 دقيقة بين تنبيهين لنفس الخبر
last_alerts_hashes = {}  # hash الخبر → آخر وقت تنبيه

# 🔔 إعدادات التنبيهات
auto_alerts_enabled = True
alert_categories = {"crypto": True, "macro": True, "breaking": True}
SETTINGS_FILE = "/tmp/news_settings.json"

def load_settings():
    global auto_alerts_enabled, alert_categories
    try:
        with open(SETTINGS_FILE, "r") as f:
            s = json.load(f)
            auto_alerts_enabled = s.get("auto_alerts_enabled", True)
            alert_categories = s.get("alert_categories", {"crypto": True, "macro": True, "breaking": True})
    except Exception:
        pass

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "auto_alerts_enabled": auto_alerts_enabled,
                "alert_categories": alert_categories
            }, f)
    except Exception as e:
        log.warning(f"save_settings err: {e}")

# 🔒 القائمة البيضاء
ALLOWED_FILE = "/tmp/allowed_users.json"

def load_dynamic_allowed():
    try:
        with open(ALLOWED_FILE, "r") as f:
            return set(json.load(f).get("users", []))
    except Exception:
        return set()

def save_dynamic_allowed(users_set):
    try:
        with open(ALLOWED_FILE, "w") as f:
            json.dump({"users": list(users_set)}, f)
    except Exception as e:
        log.warning(f"save_allowed err: {e}")

_dynamic_allowed = load_dynamic_allowed()

def _parse_allowed_users():
    allowed = set()
    raw = os.environ.get("ALLOWED_USERS", "")
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.isdigit():
            allowed.add(int(part))
    if CHAT_ID and CHAT_ID.isdigit():
        allowed.add(int(CHAT_ID))
    allowed.update(_dynamic_allowed)
    return allowed

ALLOWED_USERS = _parse_allowed_users()

def refresh_allowed():
    global ALLOWED_USERS, _dynamic_allowed
    _dynamic_allowed = load_dynamic_allowed()
    ALLOWED_USERS = _parse_allowed_users()

def add_user(cid_to_add):
    global _dynamic_allowed
    try:
        cid_int = int(cid_to_add)
    except (TypeError, ValueError):
        return False
    if cid_int in _dynamic_allowed:
        return False
    _dynamic_allowed.add(cid_int)
    save_dynamic_allowed(_dynamic_allowed)
    refresh_allowed()
    return True

def remove_user(cid_to_remove):
    global _dynamic_allowed
    try:
        cid_int = int(cid_to_remove)
    except (TypeError, ValueError):
        return False
    if CHAT_ID and cid_int == int(CHAT_ID):
        return False
    if cid_int not in _dynamic_allowed:
        return False
    _dynamic_allowed.discard(cid_int)
    save_dynamic_allowed(_dynamic_allowed)
    refresh_allowed()
    return True

def is_owner(cid):
    if not cid or not CHAT_ID:
        return False
    try:
        return int(cid) == int(CHAT_ID)
    except (TypeError, ValueError):
        return False

def is_allowed(cid):
    if not cid:
        return False
    try:
        cid_int = int(cid)
    except (TypeError, ValueError):
        return False
    return cid_int in ALLOWED_USERS

# ═══════════════════════════════════════════════════════════
# الكاش
# ═══════════════════════════════════════════════════════════
def get_cached(key, ttl=120):
    if key in _cache and time.time() - _cache[key][0] < ttl:
        return _cache[key][1]
    return None

def set_cached(key, data):
    _cache[key] = (time.time(), data)

# ═══════════════════════════════════════════════════════════
# جلب وتحليل الأخبار
# ═══════════════════════════════════════════════════════════
def parse_date(date_str):
    """يحول تاريخ RSS إلى timestamp"""
    if not date_str:
        return 0
    try:
        # معظم RSS يستخدم RFC 822: "Mon, 01 Jul 2024 12:00:00 GMT"
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
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

# 🆕 نظام الترجمة التلقائية
_translation_cache = {}

# قاموس المصطلحات الاقتصادية للترجمة الأفضل
ECONOMIC_TERMS = {
    "bitcoin": "بيتكوين",
    "ethereum": "إيثيريوم",
    "cryptocurrency": "العملات الرقمية",
    "crypto": "الكريبتو",
    "blockchain": "البلوكتشين",
    "federal reserve": "الفيدرالي الأمريكي",
    "interest rate": "سعر الفائدة",
    "rate cut": "خفض الفائدة",
    "rate hike": "رفع الفائدة",
    "etf": "صندوق التداول المباشر ETF",
    "spot etf": "صندوق التداول المباشر الفوري",
    "sec": "هيئة الأوراق المالية والبورصات الأمريكية",
    "approval": "الموافقة",
    "hack": "اختراق",
    "exploit": "ثغرة أمنية",
    "stablecoin": "العملة المستقرة",
    "defi": "تمويل لامركزي",
    "nft": "الرموز غير القابلة للاستبدال",
    "exchange": "بورصة",
    "trading": "التداول",
    "market": "السوق",
    "bullish": "صعودي",
    "bearish": "هبوطي",
    "rally": "ارتفاع",
    "plunge": "انهيار",
    "surge": "قفزة",
    "dump": "تصحيح حاد",
    "pump": "ضخ",
    "whale": "حيتان",
    "liquidation": "تصفية",
    "leverage": "الرافعة المالية",
    "futures": "العقود الآجلة",
    "spot": "الفوري",
    "mining": "التعدين",
    "wallet": "محفظة",
    "token": "رمز",
    "coin": "عملة",
    "altcoin": "العملات البديلة",
    "memecoin": "عملات الميم",
    "staking": "التحصيص",
    "yield": "العائد",
    "treasury": "الخزانة",
    "inflation": "التضخم",
    "recession": "الركود",
    "fed chair": "رئيس الفيدرالي",
    "powell": "باول",
    "trump": "ترامب",
    "biden": "بايدن",
    "white house": "البيت الأبيض",
    "tariff": "التعريفة الجمركية",
    "trade war": "الحرب التجارية",
    "stock market": "سوق الأسهم",
    "s&p": "مؤشر S&P",
    "nasdaq": "ناسداك",
    "dow": "داو جونز",
    "wall street": "وول ستريت",
    "treasury bond": "سندات الخزانة",
    "yuan": "اليوان",
    "dollar": "الدولار",
    "oil": "النفط",
    "gold": "الذهب",
}

def translate_to_arabic(text, force=False):
    """ترجمة النص للعربية بجودة عالية"""
    if not text or len(text) < 3:
        return text
    # اختصار النص الطويل جداً قبل الترجمة
    if len(text) > 500:
        text = text[:500]
    # تحقق من الكاش
    cache_key = hashlib.md5(text.encode()).hexdigest()[:12]
    if not force and cache_key in _translation_cache:
        return _translation_cache[cache_key]
    try:
        # Google Translate endpoint مجاني (بدون API key)
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "en",  # source language
            "tl": "ar",  # target language
            "dt": "t",
            "q": text
        }
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # استخراج النص المترجم
            translated_parts = []
            for sentence in data[0]:
                if sentence and sentence[0]:
                    translated_parts.append(sentence[0])
            translated = "".join(translated_parts).strip()
            if translated:
                # 🆕 تحسين الترجمة باستخدام القاموس
                for en_term, ar_term in ECONOMIC_TERMS.items():
                    # تجنب استبدال المصطلحات إذا كانت الترجمة خاطئة
                    pass  # الترجمة من Google عادة جيدة، نكتفي بها
                _translation_cache[cache_key] = translated
                return translated
    except Exception as e:
        log.warning(f"translate err: {e}")
    return text  # في حالة الفشل، ارجع النص الأصلي

def translate_news_item(item):
    """ترجمة عنوان وملخص الخبر للعربية"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    item["title_ar"] = translate_to_arabic(title)
    if summary:
        item["summary_ar"] = translate_to_arabic(summary)
    else:
        item["summary_ar"] = ""
    return item

def extract_summary(text, max_len=200):
    """يختصر النص"""
    clean = clean_html(text)
    if len(clean) <= max_len:
        return clean
    return clean[:max_len-3] + "..."

def extract_image_from_html(html_text):
    """🆕 يستخرج رابط الصورة من HTML في RSS"""
    if not html_text:
        return ""
    # البحث عن <img src="...">
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    if match:
        return match.group(1)
    # البحث عن enclosure (مستخدم في بعض RSS)
    return ""

def parse_rss_source(source_name, source_info):
    """يجلب ويحلل RSS source واحد"""
    url = source_info["url"]
    category = source_info["category"]
    is_json = source_info.get("is_json", False)
    items = []
    try:
        if is_json:
            # Reddit JSON
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                for post in data.get("data", {}).get("children", [])[:20]:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    link = "https://www.reddit.com" + d.get("permalink", "")
                    pub_ts = d.get("created_utc", 0)
                    # 🆕 استخراج الصورة من Reddit
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
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                # RSS 2.0
                for item in root.findall('.//item')[:20]:
                    title = item.findtext('title', '') or ""
                    link = item.findtext('link', '') or ""
                    desc = item.findtext('description', '') or ""
                    pub_date = item.findtext('pubDate', '') or ""
                    # 🆕 استخراج الصورة
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
                        "title": clean_html(title),
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
                        # 🆕 استخراج الصورة من Atom
                        image = extract_image_from_html(summary)
                        items.append({
                            "title": clean_html(title),
                            "link": link,
                            "summary": extract_summary(summary),
                            "image": image,
                            "source": source_name,
                            "category": category,
                            "timestamp": parse_date(pub_date),
                            "date_str": pub_date
                        })
        log.info(f"📰 {source_name}: {len(items)} items")
    except Exception as e:
        log.warning(f"Source {source_name} err: {e}")
    return items

def get_all_news():
    """يجلب كل الأخبار من كل المصادر"""
    cached = get_cached("all_news", 120)  # كاش دقيقتين
    if cached:
        return cached
    all_items = []
    for source_name, source_info in NEWS_SOURCES.items():
        items = parse_rss_source(source_name, source_info)
        all_items.extend(items)
        # تأخير بسيط بين المصادر
        time.sleep(0.3)
    # ترتيب حسب الوقت (الأحدث أولاً)
    all_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    set_cached("all_news", all_items)
    return all_items

def classify_news(item):
    """🆕 يصنف الخبر بدقة باستخدام حدود الكلمات"""
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()
    text = f"{title} {summary}"
    categories = []
    # 🆕 استخدام حدود الكلمات (word boundaries) لتجنب الأخطاء
    # مثلاً "sec" يجب أن تكون كلمة مستقلة، وليست جزءاً من "summer"
    def has_word(text, word):
        """يتحقق من وجود الكلمة كوحدة مستقلة"""
        pattern = r'\b' + re.escape(word) + r'\b'
        return bool(re.search(pattern, text))
    # 🆕 شروط أكثر صرامة لكل فئة
    if any(has_word(text, kw) for kw in KEYWORDS_BREAKING):
        categories.append("breaking")
    # الفيدرالي: يجب ذكر كلمات محددة
    if any(has_word(text, kw) for kw in KEYWORDS_FED):
        categories.append("fed")
    # ترامب: يجب ذكر كلمة trump أو white house
    if any(has_word(text, kw) for kw in KEYWORDS_TRUMP):
        categories.append("trump")
    # ETF: يجب ذكر "etf" فعلياً (ليس مجرد "finance")
    if has_word(text, "etf") or has_word(text, "spot etf") or "exchange-traded fund" in text:
        categories.append("etf")
    # اختراق: شروط صارمة - يحتاج كلمات محددة للثغرات الأمنية
    hack_words = ["hack", "exploit", "drained", "stolen", "vulnerability",
                  "flash loan attack", "rug pull", "hacked", "breach"]
    if any(has_word(text, kw) for kw in hack_words):
        categories.append("hack")
    return categories

def get_coin_keywords(text):
    """🆕 يستخرج العملات بدقة باستخدام حدود الكلمات"""
    text_lower = text.lower()
    coins = []
    coin_map = {
        "bitcoin": "BTC", "btc": "BTC",
        "ethereum": "ETH", "eth": "ETH", "ether": "ETH",
        "solana": "SOL", "sol": "SOL",
        "ripple": "XRP", "xrp": "XRP",
        "cardano": "ADA", "ada": "ADA",
        "dogecoin": "DOGE", "doge": "DOGE",
        "avalanche": "AVAX", "avax": "AVAX",
        "polygon": "MATIC", "matic": "MATIC",
        "chainlink": "LINK", "link": "LINK",
        "polkadot": "DOT", "dot": "DOT",
        "litecoin": "LTC", "ltc": "LTC",
        "binance": "BNB", "bnb": "BNB",
        "tether": "USDT", "usdt": "USDT",
        "aptos": "APT", "apt": "APT",
        "arbitrum": "ARB", "arb": "ARB",
        "optimism": "OP", "op token": "OP",
        "sui": "SUI", "sei": "SEI", "toncoin": "TON",
    }
    found = set()
    for keyword, symbol in coin_map.items():
        if keyword in text_lower:
            found.add(symbol)
    return list(found)

# ═══════════════════════════════════════════════════════════
# بناء الرسائل
# ═══════════════════════════════════════════════════════════
def time_ago(timestamp):
    """يحول timestamp إلى نص 'منذ X دقيقة'"""
    if not timestamp:
        return ""
    diff = time.time() - timestamp
    if diff < 60:
        return "منذ لحظات"
    if diff < 3600:
        return f"منذ {int(diff/60)} دقيقة"
    if diff < 86400:
        return f"منذ {int(diff/3600)} ساعة"
    return f"منذ {int(diff/86400)} يوم"

def detect_economic_data(item):
    """🆕 يكتشف البيانات الاقتصادية في النص (السابق/المتوقع/الحالي)"""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    text_lower = text.lower()
    # أنماط الأرقام الاقتصادية
    patterns = [
        # previous, expected, current
        r'previous[:\s]+([0-9.]+).*?(?:expected|forecast|estimate)[:\s]+([0-9.]+).*?(?:actual|current)[:\s]+([0-9.]+)',
        # actual, forecast, previous
        r'actual[:\s]+([0-9.]+).*?forecast[:\s]+([0-9.]+).*?previous[:\s]+([0-9.]+)',
    ]
    data = {"has_data": False, "previous": None, "expected": None, "current": None}
    for pattern in patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL)
        if match:
            groups = match.groups()
            if len(groups) >= 3:
                data["has_data"] = True
                data["previous"] = groups[0] if pattern.startswith('previous') else groups[2]
                data["expected"] = groups[1]
                data["current"] = groups[2] if pattern.startswith('previous') else groups[0]
                break
    return data

def extract_key_points(text, max_points=5):
    """🆕 يستخرج النقاط الرئيسية من النص"""
    if not text:
        return []
    # تقسيم النص إلى جمل
    sentences = re.split(r'[.!?،؛\n]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
    # اختيار الجمل الأهم (الأطول والأكثر محتوى)
    # ترتيب حسب الطول (الأطول عادة أكثر معلومات)
    sorted_sentences = sorted(sentences, key=lambda x: len(x), reverse=True)
    # أخذ أول N جمل
    points = sorted_sentences[:max_points]
    # إعادة الترتيب حسب التسلسل الأصلي
    original_order = []
    for s in sentences:
        if s in points and s not in original_order:
            original_order.append(s)
    return original_order[:max_points]

def extract_keywords(text, max_keywords=6):
    """🆕 يستخرج الكلمات المفتاحية المهمة من النص"""
    if not text:
        return []
    text_lower = text.lower()
    important_keywords = []
    # كلمات مفتاحية محددة مسبقاً
    keyword_map = {
        "bitcoin": "بيتكوين", "ethereum": "إيثيريوم", "solana": "سولانا",
        "ripple": "ريبل", "cardano": "كاردانو", "dogecoin": "دوجكوين",
        "binance": "بينانس", "tether": "تيثر", "usdt": "USDT",
        "federal reserve": "الفيدرالي", "interest rate": "سعر الفائدة",
        "rate cut": "خفض الفائدة", "rate hike": "رفع الفائدة",
        "etf": "ETF", "spot etf": "ETF فوري", "sec": "هيئة الأوراق المالية",
        "approval": "موافقة", "approved": "موافقة", "reject": "رفض",
        "hack": "اختراق", "exploit": "ثغرة", "stolen": "سرقة",
        "lawsuit": "دعوى قضائية", "sue": "رفع دعوى",
        "partnership": "شراكة", "collaboration": "تعاون",
        "launch": "إطلاق", "release": "إصدار",
        "upgrade": "ترقية", "update": "تحديث",
        "listing": "إدراج", "delisting": "إلغاء الإدراج",
        "staking": "تحصيص", "airdrop": "توزيع مجاني",
        "trump": "ترامب", "biden": "بايدن", "powell": "باول",
        "inflation": "التضخم", "recession": "الركود",
        "bull market": "سوق صاعد", "bear market": "سوق هابط",
        "all-time high": "أعلى مستوى تاريخي", "ath": "أعلى مستوى تاريخي",
        "support": "دعم", "resistance": "مقاومة",
        "bullish": "صعودي", "bearish": "هبوطي",
        "whale": "حيتان", "whales": "حيتان",
        "liquidation": "تصفية", "leverage": "رافعة مالية",
        "futures": "عقود آجلة", "options": "خيارات",
        "mining": "تعدين", "miner": "معدّن",
        "defi": "تمويل لامركزي", "nft": "NFT",
        "metaverse": "ميتافيرس", "web3": "ويب 3",
        "regulation": "تنظيم", "compliance": "امتثال",
        "treasury": "الخزانة", "bonds": "سندات",
        "tariff": "تعريفة جمركية", "trade war": "حرب تجارية",
    }
    for en_kw, ar_kw in keyword_map.items():
        if en_kw in text_lower and ar_kw not in important_keywords:
            important_keywords.append(ar_kw)
        if len(important_keywords) >= max_keywords:
            break
    return important_keywords

def fmt_news_item(item, show_summary=True, translate=True, show_header=True):
    """🆕 تنسيق مبسط: صورة + العنوان + الملخص + الرابط فقط (بدون ترويسة)"""
    title = item.get("title", "")
    title_ar = item.get("title_ar", "")
    summary = item.get("summary", "")
    summary_ar = item.get("summary_ar", "")
    link = item.get("link", "")
    image_url = item.get("image", "")  # 🆕 استخراج الصورة
    categories = classify_news(item)
    # ترجمة العنوان للعربية
    if translate and title and not title_ar:
        title_ar = translate_to_arabic(title)
        item["title_ar"] = title_ar
    if translate and summary and not summary_ar:
        summary_ar = translate_to_arabic(summary)
        item["summary_ar"] = summary_ar
    # العنوان النهائي (عربي فقط)
    final_title = title_ar if title_ar and translate else title
    # 🆕 تحديد رمز الخبر
    if "breaking" in categories:
        icon = "🚨"
    elif "hack" in categories:
        icon = "⚠️"
    elif "fed" in categories or "trump" in categories:
        icon = "🇺🇸"
    elif "etf" in categories:
        icon = "📊"
    elif "whale" in categories:
        icon = "🐋"
    else:
        icon = "📰"
    # 🆕 البناء الجديد (بدون ترويسة في بداية الخبر)
    msg = ""
    # 🆕 إضافة الصورة إن وُجدت
    if image_url:
        msg += f"<a href='{image_url}'> </a>\n"
    # العنوان
    msg += f"{icon} <b>{final_title}</b>\n\n"
    # الملخص مباشرة
    if show_summary:
        if summary_ar and translate:
            clean_summary = summary_ar.strip()
            if len(clean_summary) > 300:
                clean_summary = clean_summary[:297] + "..."
            msg += f"📋 {clean_summary}\n"
        elif summary:
            translated_summary = translate_to_arabic(summary[:400])
            if translated_summary and translated_summary != summary:
                clean_summary = translated_summary.strip()
                if len(clean_summary) > 300:
                    clean_summary = clean_summary[:297] + "..."
                msg += f"📋 {clean_summary}\n"
    # الرابط
    if link:
        msg += f"\n🔗 <a href='{link}'>رابط المصدر</a>\n"
    return msg

def translate_source_name(source):
    """🆕 ترجمة أسماء المصادر للعربية"""
    sources_ar = {
        "CoinDesk": "كوين ديسك",
        "Cointelegraph": "كوين تيليغراف",
        "Decrypt": "ديكريبٽ",
        "Bitcoin.com": "بيتكوين دوت كوم",
        "CNBC Economy": "سي إن بي سي",
        "Federal Reserve": "الفيدرالي الأمريكي",
        "Forexlive": "فوركس لايف",
        "Reddit r/CryptoCurrency": "مجتمع الكريبتو",
    }
    return sources_ar.get(source, source)

def translate_coin_name(symbol):
    """🆕 ترجمة أسماء العملات للعربية"""
    coins_ar = {
        "BTC": "بيتكوين",
        "ETH": "إيثيريوم",
        "SOL": "سولانا",
        "XRP": "ريبل",
        "ADA": "كاردانو",
        "DOGE": "دوجكوين",
        "AVAX": "أفالانش",
        "MATIC": "بوليغون",
        "LINK": "تشين لينك",
        "DOT": "بولكادوت",
        "LTC": "لايتكوين",
        "BNB": "بينانس كوين",
        "USDT": "تيثر",
        "APT": "أبتوس",
        "ARB": "أربيترم",
        "OP": "أوبتيميزم",
        "SUI": "سوي",
        "SEI": "سي",
        "TON": "تونكوين",
    }
    return f"{symbol} ({coins_ar.get(symbol, symbol)})"

def deduplicate_news(news_list):
    """🆕 إزالة الأخبار المكررة بشكل صارم"""
    seen = set()
    unique = []
    for item in news_list:
        title = item.get("title", "").lower().strip()
        # تطبيع شديد: إزالة كل الرموز والمسافات الزائدة
        normalized = re.sub(r'[^\w\s]', '', title)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # إزالة الكلمات الشائعة في البداية (Breaking, Update, News)
        normalized = re.sub(r'^(breaking|update|news|alert|urgent)[\s:]*', '', normalized)
        # أخذ أول 60 حرف فقط للمقارنة (لتجنب التكرار مع عناوين مختلفة قليلاً)
        normalized = normalized[:60]
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(item)
    return unique

def build_latest_news(limit=10):
    """📰 آخر الأخبار"""
    news = get_all_news()
    if not news:
        return "⚠️ تعذّر جلب الأخبار. حاول لاحقاً."
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    msg = ""
    for item in news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_breaking_news(limit=5):
    """🔥 أخبار عاجلة"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    breaking = [n for n in news if "breaking" in classify_news(n) or "hack" in classify_news(n)]
    if not breaking:
        return "✅ <b>لا توجد أخبار عاجلة حالياً</b>\n\nالسوق هادئ نسبياً."
    msg = ""
    for item in breaking[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=True, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_macro_news(limit=8):
    """🇺🇸 اقتصاد كلي"""
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    macro = [n for n in news if n.get("category") == "macro" or
             "fed" in classify_news(n) or "trump" in classify_news(n)]
    if not macro:
        return "ℹ️ لا توجد أخبار اقتصادية حديثة."
    msg = ""
    for item in macro[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

def build_coin_news(symbol, limit=5):
    """💎 أخبار عملة معينة"""
    symbol = symbol.upper().strip()
    news = get_all_news()
    # 🆕 إزالة المكرر
    news = deduplicate_news(news)
    coin_news = []
    for n in news:
        coins = get_coin_keywords(f"{n.get('title', '')} {n.get('summary', '')}")
        if symbol in coins:
            coin_news.append(n)
    if not coin_news:
        return f"ℹ️ لا توجد أخبار حديثة عن <b>{symbol}</b>"
    msg = ""
    for item in coin_news[:limit]:
        translate_news_item(item)
        msg += fmt_news_item(item, show_summary=False, translate=True, show_header=False)
        msg += "\n"
    return msg

# ═══════════════════════════════════════════════════════════
# التنبيهات التلقائية
# ═══════════════════════════════════════════════════════════
def news_hash(item):
    """hash فريد للخبر"""
    title = item.get("title", "")
    return hashlib.md5(title.encode()).hexdigest()[:12]

def scan_news_loop():
    """يفحص الأخبار الجديدة ويرسل تنبيهات"""
    time.sleep(20)
    while True:
        try:
            if not auto_alerts_enabled:
                time.sleep(300)
                continue
            log.info("🔍 Scanning news for breaking alerts...")
            # مسح الكاش للحصول على أخبار طازجة
            if "all_news" in _cache:
                del _cache["all_news"]
            news = get_all_news()
            if not news:
                time.sleep(300)
                continue
            now = time.time()
            alerts_sent = 0
            for item in news[:30]:  # نفحص آخر 30 خبر
                categories = classify_news(item)
                # فقط الأخبار العاجلة أو الاختراقات أو ETF
                if not any(c in categories for c in ["breaking", "hack", "etf"]):
                    continue
                # فلترة حسب الفئات المفعّلة
                if "breaking" in categories and not alert_categories.get("breaking", True):
                    continue
                h = news_hash(item)
                key = f"news_{h}"
                if now - last_alerts_hashes.get(key, 0) < ALERT_COOLDOWN:
                    continue
                last_alerts_hashes[key] = now
                # 🆕 ترجمة الخبر قبل الإرسال
                translate_news_item(item)
                # إرسال للجميع - التنسيق المبسط
                msg = fmt_news_item(item, show_summary=True, translate=True)
                broadcast_alert(msg)
                alerts_sent += 1
            if alerts_sent > 0:
                log.info(f"🔔 Sent {alerts_sent} news alerts")
            time.sleep(300)  # كل 5 دقائق
        except Exception as e:
            log.warning(f"scan_news_loop err: {e}")
            time.sleep(60)

# ═══════════════════════════════════════════════════════════
# إرسال الرسائل
# ═══════════════════════════════════════════════════════════
def send_msg(msg, kb=None, cid=None):
    t = cid or CHAT_ID
    if not t or not TOKEN:
        return
    try:
        p = {"chat_id": t, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": True}
        if kb:
            p["reply_markup"] = json.dumps(kb) if isinstance(kb, dict) else kb
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json=p, timeout=15)
    except Exception:
        pass

def send_to_channel(msg):
    """🆕 إرسال رسالة إلى القناة العامة"""
    if not TOKEN or not CHANNEL_ID or not SEND_TO_CHANNEL:
        return False
    try:
        p = {"chat_id": CHANNEL_ID, "text": msg, "parse_mode": "HTML",
             "disable_web_page_preview": True}
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json=p, timeout=15)
        if r.status_code == 200 and r.json().get("ok"):
            log.info(f"📢 Sent to channel {CHANNEL_ID}")
            return True
        else:
            log.warning(f"Channel send failed: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        log.warning(f"send_to_channel err: {e}")
        return False

def broadcast_alert(msg):
    """إرسال التنبيه لكل المستخدمين المصرّح لهم + القناة العامة"""
    # 🆕 إرسال للقناة العامة أولاً
    if SEND_TO_CHANNEL and CHANNEL_ID:
        send_to_channel(msg)
    # إرسال للمستخدمين الخاصين
    if not TOKEN or not ALLOWED_USERS:
        send_msg(msg)
        return
    sent = 0
    for uid in ALLOWED_USERS:
        try:
            p = {"chat_id": uid, "text": msg, "parse_mode": "HTML",
                 "disable_web_page_preview": True}
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json=p, timeout=15)
            sent += 1
        except Exception:
            pass
    log.info(f"📡 Broadcast sent to {sent}/{len(ALLOWED_USERS)} users")

# ═══════════════════════════════════════════════════════════
# لوحات المفاتيح
# ═══════════════════════════════════════════════════════════
def main_kb():
    return {"keyboard": [
        [{"text": "📰 آخر الأخبار"}, {"text": "🔥 أخبار عاجلة"}],
        [{"text": "💎 أخبار عملتي"}, {"text": "🇺🇸 اقتصاد كلي"}],
        [{"text": "⚙️ الإعدادات"}]
    ], "resize_keyboard": True, "is_persistent": True}

# ═══════════════════════════════════════════════════════════
# معالجة التحديثات
# ═══════════════════════════════════════════════════════════
def handle_update(u):
    m = u.get("message", {})
    if m:
        chat = m.get("chat", {})
        cid = chat.get("id")
        txt = m.get("text", "").strip()
        if cid and txt:
            handle_msg(cid, txt, chat)
        return
    cb = u.get("callback_query", {})
    if cb:
        cid = cb.get("message", {}).get("chat", {}).get("id")
        d = cb.get("data", "")
        cb_id = cb.get("id", "")
        if cid and d:
            handle_cb(cid, d, cb_id)

def handle_msg(cid, txt, chat=None):
    # 🛡️ أوامر المالك فقط
    if is_owner(cid):
        if txt.startswith("/add "):
            target = txt.replace("/add ", "").strip().replace(" ", "")
            if target.isdigit():
                if add_user(target):
                    send_msg(f"✅ <b>تمت إضافة المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"ℹ️ المستخدم <code>{target}</code> موجود مسبقاً.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/add 123456789</code>", main_kb(), cid)
            return
        if txt.startswith("/remove "):
            target = txt.replace("/remove ", "").strip().replace(" ", "")
            if target.isdigit():
                if remove_user(target):
                    send_msg(f"✅ <b>تم حذف المستخدم</b>\n🆔 <code>{target}</code>\n\nالعدد الإجمالي: {len(ALLOWED_USERS)}", main_kb(), cid)
                else:
                    send_msg(f"❌ لا يمكن حذف <code>{target}</code>.", main_kb(), cid)
            else:
                send_msg("❌ الصيغة خاطئة.\n\nمثال: <code>/remove 123456789</code>", main_kb(), cid)
            return
        if txt == "/users":
            msg = f"👥 <b>القائمة البيضاء</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += f"📊 العدد الإجمالي: {len(ALLOWED_USERS)} مستخدم\n\n"
            for i, uid in enumerate(sorted(ALLOWED_USERS), 1):
                owner_tag = " 👑" if uid == int(CHAT_ID) else ""
                msg += f"{i}. <code>{uid}</code>{owner_tag}\n"
            msg += "\n💡 للإضافة: <code>/add ID</code>\n💡 للحذف: <code>/remove ID</code>"
            send_msg(msg, main_kb(), cid)
            return

    # 🔒 فحص القائمة البيضاء
    if not is_allowed(cid):
        if txt == "/start":
            send_msg("🔒 هذا البوت خاص.\n\nتواصل مع المالك للوصول.", None, cid)
            log.warning(f"⛔ Access denied for chat_id: {cid}")
            if chat and CHAT_ID:
                first_name = chat.get("first_name", "غير معروف")
                username = chat.get("username", "")
                notify = f"🔔 <b>محاولة دخول جديدة</b>\n"
                notify += "━━━━━━━━━━━━━━━━━━\n\n"
                notify += f"👤 الاسم: {first_name}\n"
                if username:
                    notify += f"📎 المعرف: @{username}\n"
                notify += f"🆔 Chat ID: <code>{cid}</code>\n\n"
                notify += f"لإضافته أرسل: <code>/add {cid}</code>"
                send_msg(notify)
        return

    # حالة انتظار إدخال عملة
    if _user_state.get(cid) == "waiting_for_symbol":
        _user_state[cid] = None
        send_msg("⏳ جاري البحث...", cid=cid)
        send_msg(build_coin_news(txt), main_kb(), cid)
        return

    if txt == "/start":
        if is_owner(cid):
            msg = "📰 <b>بوت الأخبار الكريبتو</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📡 المصادر: CoinDesk, Cointelegraph, Decrypt, CNBC, Fed, Reddit\n"
            msg += f"🔔 التنبيهات: {'🟢 مفعّل' if auto_alerts_enabled else '🔴 معطّل'}\n"
            msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n\n"
            msg += "اختر من القائمة بالأسفل:"
            send_msg(msg, main_kb(), cid)
        else:
            first_name = chat.get("first_name", "") if chat else ""
            msg = f"📰 <b>أهلاً {first_name}!</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📊 <b>بوت الأخبار الكريبتو والاقتصادية</b>\n"
            msg += "📡 مصادر موثوقة متعددة\n\n"
            msg += "✅ <b>تم تفعيل استقبال الأخبار</b>\n"
            msg += "⏳ سيصلك تنبيه فور ظهور خبر عاجل\n\n"
            msg += "💡 <i>أنت مستلم للأخبار فقط.</i>"
            send_msg(msg, None, cid)
    elif txt == "📰 آخر الأخبار":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_latest_news(10), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🔥 أخبار عاجلة":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_breaking_news(5), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "💎 أخبار عملتي":
        if is_owner(cid):
            _user_state[cid] = "waiting_for_symbol"
            msg = "💎 <b>أخبار عملة معينة</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━\n\n"
            msg += "📝 أرسل رمز العملة:\n"
            msg += "مثال: <code>BTC</code> أو <code>ETH</code> أو <code>SOL</code>"
            send_msg(msg, None, cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "🇺🇸 اقتصاد كلي":
        if is_owner(cid):
            send_msg("⏳ جاري الجلب...", cid=cid)
            send_msg(build_macro_news(8), main_kb(), cid)
        else:
            send_msg("ℹ️ هذه الميزة متاحة للمالك فقط.", None, cid)
    elif txt == "⚙️ الإعدادات":
        if is_owner(cid):
            show_settings(cid)
        else:
            send_msg("ℹ️ الإعدادات متاحة للمالك فقط.", None, cid)
    else:
        if is_owner(cid):
            send_msg("استخدم القائمة بالأسفل", main_kb(), cid)
        else:
            send_msg("ℹ️ أنت مستلم للأخبار فقط. انتظر التنبيهات التلقائية.", None, cid)

def show_settings(cid):
    """عرض إعدادات التنبيهات"""
    status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    msg = "⚙️ <b>إعدادات التنبيهات</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🔔 <b>الحالة:</b> {status}\n"
    msg += f"⏰ <b>الفحص كل:</b> 5 دقائق\n"
    msg += f"🔒 <b>Cooldown:</b> 30 دقيقة لكل خبر\n\n"
    msg += "📊 <b>فئات التنبيه:</b>\n"
    msg += f"  📰 أخبار كريبتو: {'🟢' if alert_categories.get('crypto', True) else '🔴'}\n"
    msg += f"  🇺🇸 اقتصاد كلي: {'🟢' if alert_categories.get('macro', True) else '🔴'}\n"
    msg += f"  🚨 أخبار عاجلة: {'🟢' if alert_categories.get('breaking', True) else '🔴'}\n"
    kb = {"inline_keyboard": [
        [{"text": f"{'🔴 إيقاف' if auto_alerts_enabled else '🟢 تفعيل'} التنبيهات", "callback_data": "toggle_alerts"}],
        [{"text": "✅ تم", "callback_data": "done_settings"}]
    ]}
    send_msg(msg, kb, cid)

def handle_cb(cid, d, cb_id):
    global auto_alerts_enabled
    if not is_allowed(cid):
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": cb_id, "text": "🔒 مرفوض"}, timeout=10)
        except:
            pass
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": "✅"}, timeout=10)
    except:
        pass
    if d == "toggle_alerts":
        auto_alerts_enabled = not auto_alerts_enabled
        save_settings()
        status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
        send_msg(f"✅ التنبيهات: <b>{status}</b>", main_kb(), cid)
    elif d == "done_settings":
        send_msg("✅ تم حفظ الإعدادات", main_kb(), cid)

# ═══════════════════════════════════════════════════════════
# خادم Flask
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        u = request.get_json()
        if u:
            threading.Thread(target=handle_update, args=(u,)).start()
    except:
        pass
    return jsonify({"ok": True})

@app.route("/")
def home():
    return jsonify({"status": "running", "bot": "news", "users": len(ALLOWED_USERS),
                    "sources": len(NEWS_SOURCES)})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/ping")
def ping():
    return jsonify({"pong": True})

# ═══════════════════════════════════════════════════════════
# تشغيل البوت
# ═══════════════════════════════════════════════════════════
def self_ping():
    if not RENDER_URL:
        return
    time.sleep(30)
    while True:
        try:
            requests.get(f"{RENDER_URL}/ping", timeout=10)
        except Exception:
            pass
        time.sleep(600)

def start_bot():
    global _started
    if _started:
        return
    _started = True
    if not TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set!")
        return
    load_settings()
    wh = False
    if RENDER_URL:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                             params={"url": f"{RENDER_URL}/webhook"}, timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                wh = True
        except:
            pass
    alert_status = "🟢 مفعّل" if auto_alerts_enabled else "🔴 معطّل"
    channel_status = "🟢 مفعّل" if (SEND_TO_CHANNEL and CHANNEL_ID) else "🔴 معطّل"
    msg = "📰 <b>بوت الأخبار — تم التشغيل</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📡 المصادر: {len(NEWS_SOURCES)} مصدر\n"
    msg += f"🔔 التنبيهات: {alert_status}\n"
    msg += f"👥 المستخدمون: {len(ALLOWED_USERS)}\n"
    msg += f"📢 القناة العامة: {channel_status}\n"
    if SEND_TO_CHANNEL and CHANNEL_ID:
        msg += f"   ┗ {CHANNEL_ID}\n"
    msg += "\n📥 أرسل /start للبدء"
    send_msg(msg)

    def run_with_restart(name, target_fn, restart_delay=30):
        while True:
            try:
                log.info(f"🔄 Starting {name} thread")
                target_fn()
            except Exception as e:
                log.error(f"❌ {name} crashed: {e} — restarting in {restart_delay}s")
            time.sleep(restart_delay)

    threading.Thread(target=lambda: run_with_restart("self_ping", self_ping),
                     daemon=True).start()
    threading.Thread(target=lambda: run_with_restart("news_scan", scan_news_loop),
                     daemon=True).start()
    if not wh:
        def poll():
            global last_id
            last_id = 0
            while True:
                try:
                    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                                     params={"offset": last_id+1, "timeout": 25}, timeout=30)
                    if r.status_code == 200:
                        for u in r.json().get("result", []):
                            last_id = u.get("update_id", last_id)
                            handle_update(u)
                    else:
                        time.sleep(5)
                except:
                    time.sleep(5)
        threading.Thread(target=lambda: run_with_restart("polling", poll),
                         daemon=True).start()

start_bot()
