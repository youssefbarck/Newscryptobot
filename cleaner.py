"""
🐋 Whale News Bot v3 - وحدة تنظيف النصوص
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
هذه الوحدة مسؤولة فقط عن تنظيف النصوص الخام.
لا تترجم، لا تصنّف، ولا تقيّم — فقط تنظّف.

المراحل:
  1. إزالة وسوم HTML وآثار RSS ومشاكل الترميز
  2. إزالة تواقيع القنوات (Follow us, Subscribe...)
  3. إزالة العناوين/الأسطر المكررة داخل نفس النص
  4. إزالة الهاشتاقات المزعجة (#sponsored, #ad...)
  5. تسوية المسافات البيضاء
  6. إزالة تسريبات اسم المصدر من النص
  7. إزالة بادئات الإيموجي المستخدمة كعلامات تنسيق
  8. تنظيف خاص للنص العربي (ألف/ياء، تطويل)
"""

import re
import html
import unicodedata
from typing import List, Tuple

from models import NewsItem
from config import log


# ═══════════════════════════════════════════════════════════
# 🏷️ ثوابت الأنماط — Patterns Constants
# ═══════════════════════════════════════════════════════════

# --- أسماء المصادر المعروفة — Known Source Names ---
# تُستخدم لكشف التسريبات داخل النص
KNOWN_SOURCES: List[str] = [
    "CoinDesk", "Cointelegraph", "Blockworks", "Decrypt",
    "BeInCrypto", "Crypto.News", "CoinPedia", "Bitcoinist",
    "The Block", "Bitcoin Magazine", "Bloomberg", "Reuters",
    "CNBC", "Forbes", "CoinMarketCap", "CoinGecko",
    "Federal Reserve", "Google News",
]

# --- أسماء المصادر العربية ---
KNOWN_SOURCES_AR: List[str] = [
    "كوينديسك", "كوين تلغراف", "ديكريبت", "بي إن كريبتو",
    "بلوك ووركس", "بيتكوينست",
]

# --- وسوم HTML وآثار RSS ---
RE_HTML_TAGS = re.compile(r"<[^>]+>")
RE_HTML_ENTITIES = re.compile(r"&[a-zA-Z]+;|&#[0-9]+;|&#x[0-9a-fA-F]+;")
RE_CDATA = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
RE_RSS_ARTIFACTS = re.compile(
    r"\[…\]|\[…\]|\.{3,}|&#8230;|&hellip;|"
    r"\[link\]|\[comments?\]|\[تعليقات?\]|"
    r"submitted by .*?(?:\n|$)|مقدم بواسطة .*?(?:\n|$)|"
    r"crossposted from .*?(?:\n|$)",
    re.IGNORECASE,
)

# --- مشاكل الترميز ---
RE_ENCODING_ISSUES = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|"        # control characters
    r"&amp;amp;|&amp;lt;|&amp;gt;|&amp;quot;",    # double-encoded entities
    re.IGNORECASE,
)
RE_ZERO_WIDTH = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u202a-\u202e\u2060-\u2069]",
)

# --- بادئات الإيموجي كعلامات تنسيق ---
# نمط: إيموجي (أو أكثر) + مسافة + نص التصنيف + نقطتين
RE_FORMAT_LABEL_PREFIX = re.compile(
    r"^[BLUE🔴🚨⚪📊⚠️🔥💡📰⬛️🟢🟡🟣🟠⚫️_pipeline"
    r"🔵🟢🔴⚪🟡🟣🟠⚫]+"
    r"\s*"
    r"(?:"
    r"منشور الأخبار العاجلة|تقرير تحليلي|أخبار العملات المشفرة|"
    r"أخبار عاجلة|تحديث السوق|تقرير خاص|ملخص الأخبار|"
    r"Breaking News|Market Update|Crypto News|"
    r"Just In|Flash|Alert|Urgent|Report|Exclusive|"
    r"News Alert|Latest|Update"
    r")"
    r"\s*[:\-\u200f]?\s*",
    re.IGNORECASE | re.UNICODE,
)

# --- الإيموجي المفردة كبادئة (مثل 🔵 أو 🚨 في بداية السطر) ---
RE_LEADING_EMOJI_CLUSTER = re.compile(
    r"^[\U0001F300-\U0001F9FF\U00002600-\U000027BF"
    r"\U0001FA00-\U0001FA9F\U0001FAD0-\U0001FAFF"
    r"\u200d\ufe0f"
    r"\u2702\u2705\u2708-\u270d\u2712\u2714\u2716\u2718\u271d\u2721\u2728\u2733\u2734\u2744\u2747\u274c\u274e\u2753-\u2755\u2757"
    r"\u2763\u2764\u2795-\u2797\u27a1\u27b0\u27bf\u2934\u2935\u2b05-\u2b07\u2b1b\u2b1c\u2b50\u2b55"
    r"]{1,4}\s+",
)

# --- تواقيع القنوات الإنجليزية ---
RE_SIGNATURES_EN = re.compile(
    r"(?:"
    # متابعة
    r"Follow\s+us\s+on\s+(?:Twitter|X|Telegram|YouTube|Facebook|Instagram)(?:\s+@\S+)?|"
    r"Subscribe\s+to\s+(?:our\s+)?(?:newsletter|channel|podcast)|"
    r"Read\s+more\s+at\s+\S+|"
    r"Learn\s+more\s+(?:at|about)|"
    # تنويه
    r"Disclaimer[:\s].*?(?:\n|$)|"
    r"Terms\s+of\s+(?:Service|Use)|"
    r"Privacy\s+Policy|"
    r"All\s+rights\s+reserved|"
    r"\[Advertisement\]|\[Promoted\]|"
    # ملاحظات المحرر
    r"Editor['']?\s*(?:Note|Alert)[:\s].*?(?:\n|$)|"
    r"Sponsored\s+(?:content|post|article)|"
    # طلب إجراء
    r"Click\s+here\s+to|Visit\s+\S+\s+for\s+more|"
    # رابط عاري في نهاية النص
    r"https?://\S+$"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# --- تواقيع القنوات العربية ---
RE_SIGNATURES_AR = re.compile(
    r"(?:"
    r"تابعنا\s+على\s+(?:تويتر|تيجرام|يوتيوب|فيسبوك|القناة)(?:\s+@\S+)?|"
    r"اشترك\s+في\s+(?:القناة|النشرة|البودكاست)|"
    r"اقرأ\s+المزيد\s+على\s+\S+|"
    r"للمزيد\s+(?:من|عن)|"
    r"تنويه[:\s].*?(?:\n|$)|"
    r"إخلاء\s+مسؤولية[:\s].*?(?:\n|$)|"
    r"جميع\s+الحقوق\s+محفوظة|"
    r"\[إعلان\]|\[مُروَّج\]|"
    r"ملاحظة\s+(?:المحرر|التحرير)[:\s].*?(?:\n|$)|"
    r"محتوى\s+(?:ممول|مُروج)|"
    r"اضغط\s+هنا\s+لـ|زُر\s+\S+\s+للمزيد|"
    # رابط عاري في نهاية النص
    r"https?://\S+$"
    r")",
    re.IGNORECASE | re.DOTALL,
)

# --- هاشتاقات مزعجة ---
RE_BAD_HASHTAGS = re.compile(
    r"(?:"
    r"#\s*(?:sponsored|ad|promoted|promotion|affiliate|partnered|"
    r"paidad|spon|adv|advertisement|promo)"
    r")\b",
    re.IGNORECASE,
)
RE_BAD_HASHTAGS_AR = re.compile(
    r"#\s*(?:ممول|إعلان|مروج|دعاية|إعلاني|مُروَّج)\b",
)

# --- تسريبات اسم المصدر — Source Name Leaks ---
# أنماط إنجليزية عامّة: "{Source} said/reported/..."
RE_SOURCE_LEAK_GENERAL = re.compile(
    r"(?:"
    r"According\s+to\s+(?:the\s+)?(?:report|sources|analysts|data|a\s+\S+)|"
    r"Reported\s+by\s+\S+|"
    r"\S+\s+(?:said|reported|announced|revealed|wrote|stated|"
    r"confirmed|noted|explained|added|pointed\s+out|"
    r"highlighted|mentioned|emphasized|warned|tweeted)"
    r")",
    re.IGNORECASE,
)

# --- تسريبات أسماء المصادر المعروفة ---
# تُبنى ديناميكياً حسب المصادر المعروفة
def _build_source_leak_patterns() -> List[re.Pattern]:
    """بناء أنماط regex لتسريبات المصادر المعروفة

    الترتيب مهم: أنماط المقال (article) قبل أنماط الفعل (verb)
    حتى يتم التقاط "A CoinDesk report" قبل أن يلتقط الفعل "CoinDesk report".
    """
    patterns: List[re.Pattern] = []

    for source in KNOWN_SOURCES:
        # "a CoinDesk report/article/..." — أبداً بأسماء المقالات
        patterns.append(re.compile(
            rf"(?:a|an|the)\s+{re.escape(source)}\s+(?:report|article|analysis|source)\b[,.]?\s*",
            re.IGNORECASE,
        ))
        # "According to CoinDesk, ..."  — يلتقط الألفة والنقطة بعده
        patterns.append(re.compile(
            rf"According\s+to\s+{re.escape(source)}\b[,:]?\s*",
            re.IGNORECASE,
        ))
        # "CoinDesk reported/announced/revealed..." — يلتقط كلمة الفعل
        # ملاحظة: نستخدم reports بدلاً من reports? لتفادي الإمساك بـ "report" الاسم
        patterns.append(re.compile(
            rf"{re.escape(source)}\s+(?:reports|reported|reporting|writes?|"
            rf"announces?|reveals?|states?|notes?|explains?|confirms?|"
            rf"adds?|points?\s+out|tweets?)\b[,.]?\s*",
            re.IGNORECASE,
        ))
        # "– CoinDesk", "— CoinDesk", "via CoinDesk", "via CoinDesk."
        patterns.append(re.compile(
            rf"(?:[-–—:,]?\s*via?\s+){re.escape(source)}\b[,.]?\s*",
            re.IGNORECASE,
        ))

    return patterns


def _build_source_leak_patterns_ar() -> List[re.Pattern]:
    """بناء أنماط تسريبات المصادر بالعربية"""
    patterns: List[re.Pattern] = []

    for source in KNOWN_SOURCES_AR:
        patterns.append(re.compile(
            rf"وفقاً\s+ل(?:ـ)?(?:\s+{re.escape(source)})",
            re.IGNORECASE,
        ))
        patterns.append(re.compile(
            rf"وفقًا\s+ل(?:ـ)?(?:\s+{re.escape(source)})",
            re.IGNORECASE,
        ))

    # أنماط عربية عامّة لا تحتاج اسم مصدر محدد
    patterns.append(re.compile(
        r"نشرت?\s+المقال\s+على\b", re.IGNORECASE,
    ))
    patterns.append(re.compile(
        r"وفق[اًا]\s+ل(?:ـ)?\s*\S+", re.IGNORECASE,
    ))
    patterns.append(re.compile(
        r"كشفت?\s+(?:المصادر?|التقارير?)\b", re.IGNORECASE,
    ))
    patterns.append(re.compile(
        r"أفادت?\s+(?:المصادر?|التقارير?)\b", re.IGNORECASE,
    ))
    patterns.append(re.compile(
        r"أكدت?\s+(?:المصادر?|التقارير?|لل)\b", re.IGNORECASE,
    ))
    patterns.append(re.compile(
        r"ذكرت?\s+(?:المصادر?|التقارير?|لل)\b", re.IGNORECASE,
    ))

    return patterns


# بناء الأنماط مرة واحدة عند الاستيراد
_SOURCE_LEAK_PATTERNS: List[re.Pattern] = _build_source_leak_patterns()
_SOURCE_LEAK_PATTERNS_AR: List[re.Pattern] = _build_source_leak_patterns_ar()


# --- الأحرف العربية للتسوية ---
# ألف: ا آ أ إ ٱ → ا
ALEF_NORMALIZATION = str.maketrans(
    "إأآٱ",
    "اااا",
)
# ياء: ى → ي
YA_NORMALIZATION = str.maketrans(
    "ى",
    "ي",
)
# تطويل: ـ (tatweel/kashida)
TATWEEL = "\u0640"
# هاء/ة تقريبية — نحتفظ بهما لأنهما مختلفان معنوياً


# ═══════════════════════════════════════════════════════════
# 🔧 دوال التنظيف الداخلية — Internal Cleaning Helpers
# ═══════════════════════════════════════════════════════════

def _remove_html_and_encoding(text: str) -> str:
    """
    إزالة وسوم HTML، آثار RSS، ومشاكل الترميز.
    Removes HTML tags, RSS artifacts, and encoding issues.
    """
    if not text:
        return text

    original = text

    # إزالة CDATA sections
    text = RE_CDATA.sub("", text)

    # إزالة وسوم HTML
    text = RE_HTML_TAGS.sub(" ", text)

    # فك ترميز HTML entities (&amp; → &, &#39; → ')
    text = html.unescape(text)

    # إزالة double-encoded entities
    text = RE_ENCODING_ISSUES.sub("", text)

    # إزالة zero-width characters
    text = RE_ZERO_WIDTH.sub("", text)

    # إزالة آثار RSS
    text = RE_RSS_ARTIFACTS.sub(" ", text)

    if text != original:
        log.debug(f"HTML/encoding cleaned: {len(original)} → {len(text)} chars")

    return text


def _remove_signatures(text: str) -> str:
    """
    إزالة تواقيع القنوات وروابط المتابعة والتنويهات.
    Removes channel signatures, follow links, disclaimers.
    """
    if not text:
        return text

    original = text

    # إزالة بالأحرف الصغيرة أولاً لأن الأنماط case-insensitive
    # إزالة التواقيع الإنجليزية
    text = RE_SIGNATURES_EN.sub("", text)

    # إزالة التواقيع العربية
    text = RE_SIGNATURES_AR.sub("", text)

    # تنظيف الفواصل والنقاط المتروكة
    text = re.sub(r"\s*[—\-–]\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-•*]\s*$", "", text, flags=re.MULTILINE)

    if text != original:
        log.debug(f"Signatures removed: trimmed {len(original) - len(text)} chars")

    return text


def _remove_duplicate_lines(text: str) -> str:
    """
    إزالة الأسطر/العناوين المكررة داخل نفس النص.
    Removes duplicate headlines/lines within same text.
    يُحتفظ بالسطر الأول ويُحذف المكرر.
    """
    if not text:
        return text

    lines = text.split("\n")
    seen: List[str] = []
    unique: List[str] = []

    for line in lines:
        # تسوية السطر للمقارنة: lowercase + إزالة مسافات زائدة
        normalized = re.sub(r"\s+", " ", line.strip().lower())
        if not normalized:
            continue
        if normalized in seen:
            log.debug(f"Duplicate line removed: {line.strip()[:60]}...")
            continue
        seen.append(normalized)
        unique.append(line.strip())

    result = "\n".join(unique)
    if len(result) != len(text):
        log.debug(f"Dedup lines: {len(lines)} → {len(unique)} lines")

    return result


def _remove_bad_hashtags(text: str) -> str:
    """
    إزالة الهاشتاقات المزعجة (إعلانات، ترويج).
    Removes promotional/advertising hashtags.
    """
    if not text:
        return text

    text = RE_BAD_HASHTAGS.sub("", text)
    text = RE_BAD_HASHTAGS_AR.sub("", text)

    return text


def _normalize_whitespace(text: str) -> str:
    """
    تسوية المسافات البيضاء — مسافات متعددة → مسافة واحدة،
    أسطر فارغة متتالية → سطر واحد، إزالة مسافات البداية والنهاية.
    Normalizes whitespace: multiple spaces → single, etc.
    """
    if not text:
        return text

    # إزالة أسطر فارغة متعددة (أكثر من سطرين فارغين متتاليين)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # إزالة مسافات متعددة داخل كل سطر
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # إزالة مسافات قبل علامات الترقيم العربية/الإنجليزية
    text = re.sub(r"\s+([،؛؟.!:,;\-–—])", r"\1", text)
    # إزالة مسافات بعد علامات الترقيم (في بداية سطر)
    text = re.sub(r"^([。，؛؟!?,;\-–—])\s+", r"\1", text, flags=re.MULTILINE)

    # إزالة مسافات من البداية والنهاية
    text = text.strip()

    return text


def _remove_source_leaks(text: str) -> str:
    """
    إزالة تسريبات اسم المصدر من النص.
    Removes source name leaks like "According to CoinDesk", "CoinDesk reported".
    """
    if not text:
        return text

    original = text

    # تطبيق أنماط المصادر الإنجليزية
    for pattern in _SOURCE_LEAK_PATTERNS:
        text = pattern.sub("", text)

    # تطبيق أنماط المصادر العربية
    for pattern in _SOURCE_LEAK_PATTERNS_AR:
        text = pattern.sub("", text)

    # تطبيق النمط العام
    text = RE_SOURCE_LEAK_GENERAL.sub("", text)

    # تنظيف الفواصل/المسافات المتروكة بعد الحذف
    text = re.sub(r"\s*[.,;،؛]\s*\.", ".", text)
    text = re.sub(r"^\s*[.,،]\s+", "", text, flags=re.MULTILINE)  # بداية سطر بنقطة/فاصلة
    text = re.sub(r"\s{2,}", " ", text)

    if text != original:
        log.debug(f"Source leaks removed: trimmed {len(original) - len(text)} chars")

    return text


def _strip_format_labels(text: str) -> str:
    """
    إزالة بادئات الإيموجي وعلامات التصنيف من بداية النص.
    Strips emoji prefixes and format labels (e.g., "🔵🚨 Breaking News:").
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned: List[str] = []

    for i, line in enumerate(lines):
        original_line = line

        # السطر الأول فقط: إزالة بادئة التصنيف الكاملة
        if i == 0:
            line = RE_FORMAT_LABEL_PREFIX.sub("", line)

        # إزالة عناقيد الإيموجي من بداية أي سطر
        line = RE_LEADING_EMOJI_CLUSTER.sub("", line)

        # إزالة إيموجي فردية كاملة من بداية السطر (تكرار للأنماط التي لم تُلتقط)
        line = re.sub(r"^[\u2702-\u27bf\U0001f300-\U0001f9ff\U0001fa00-\U0001fa9f]+", "", line)
        line = re.sub(r"^[\u2b05-\u2b55\u2600-\u26ff]+", "", line)
        line = re.sub(r"^\ufe0f", "", line)  # variation selector

        line = line.lstrip(" :-–—\u200f")

        if line != original_line:
            log.debug(f"Format label stripped from line: '{original_line[:50]}...'")
            cleaned.append(line)
        else:
            cleaned.append(line)

    return "\n".join(cleaned)


def _clean_arabic_text(text: str) -> str:
    """
    تنظيف خاص للنص العربي.
    - تسوية أشكال الألف (إ أ آ ٱ → ا)
    - تسوية الياء (ى → ي)
    - إزالة حرف التطويل (tatweel/kashida ـ)
    - إزالة التشكيل (diacritics)
    """
    if not text:
        return text

    # كشف هل النص يحتوي عربية
    if not re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text):
        return text

    original = text

    # تسوية الألف
    text = text.translate(ALEF_NORMALIZATION)

    # تسوية الياء
    text = text.translate(YA_NORMALIZATION)

    # إزالة التطويل
    text = text.replace(TATWEEL, "")

    # إزالة التشكيل (Fathatan, Dammatan, Kasratan, Fatha, Damma, Kasra, Shadda, Sukun)
    DIACRITICS = (
        "\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652"  # تشكيل عربي
        "\u0670"  # small alef above
        "\u0656\u0657"  # subscript alef, inverted damma
        "\u0653\u0654\u0655"  # madda, hamza above, hamza below
    )
    text = text.translate(str.maketrans("", "", DIACRITICS))

    # إزالة Unicode normalization issues
    text = unicodedata.normalize("NFC", text)

    if text != original:
        log.debug(f"Arabic text cleaned: {len(original)} → {len(text)} chars")

    return text


def _clean_bare_urls(text: str) -> str:
    """
    إزالة الروابط العارية (URLs) من نهاية النص أو من الأسطر المنفصلة.
    Removes bare URLs at end of text or standalone lines.
    """
    if not text:
        return text

    # إزالة الروابط من نهاية كل سطر
    text = re.sub(r"\s*https?://\S+\s*$", "", text, flags=re.MULTILINE)

    # إزالة أسطر تحتوي فقط على رابط
    text = re.sub(r"^\s*https?://\S+\s*$", "", text, flags=re.MULTILINE)

    # إزالة أنماط "Read more at URL" أو "اقرأ المزيد على URL"
    text = re.sub(
        r"(?:Read\s+more|اقرأ\s+المزيد)\s+(?:at|على)\s+\S+",
        "", text, flags=re.IGNORECASE,
    )

    return text


# ═══════════════════════════════════════════════════════════
# 🧼 خط أنابيب التنظيف — Cleaning Pipeline
# ═══════════════════════════════════════════════════════════

def _strip_source_prefix(text: str) -> str:
    """
    إزالة بادئة اسم المصدر من بداية النص.
    "CoinDesk: Bitcoin Surges" → "Bitcoin Surges"
    "Cointelegraph - ETH Rallies" → "ETH Rallies"
    """
    # بناء أنماط من أسماء المصادر المعروفة
    for source in KNOWN_SOURCES + KNOWN_SOURCES_AR:
        escaped = re.escape(source)
        # "{Source}: " أو "{Source} - " أو "{Source} — "
        for sep in [r":\s*", r"\s*[-–—]\s*"]:
            pattern = re.compile(rf"^{escaped}{sep}", re.IGNORECASE)
            text = pattern.sub("", text).strip()
    return text


def _run_cleaning_pipeline(text: str) -> str:
    """
    تنفيذ كامل مراحل التنظيف على نص واحد.
    Runs all cleaning stages on a single text string.

    الترتيب مهم — كل مرحلة تُعدّ للمرحلة التالية:
      1. HTML/ترميز
      2. علامات التنسيق والإيموجي
      3. تواقيع القنوات
      4. روابط عارية
      5. هاشتاقات مزعجة
      6. تسريبات المصادر
      7. أسطر مكررة
      8. تنظيف عربي
      9. تسوية المسافات
    """
    if not text:
        return ""

    # 1. تنظيف HTML وآثار RSS ومشاكل الترميز
    text = _remove_html_and_encoding(text)

    # 2. إزالة بادئة اسم المصدر ("CoinDesk: ...")
    # يجب أن تكون قبل إزالة علامات التنسيق لكي تزيل "CoinDesk: 🔵 ..."
    text = _strip_source_prefix(text)

    # 3. إزالة علامات التنسيق والإيموجي
    text = _strip_format_labels(text)

    # 4. إزالة تواقيع القنوات
    text = _remove_signatures(text)

    # 4. إزالة الروابط العارية
    text = _clean_bare_urls(text)

    # 5. إزالة الهاشتاقات المزعجة
    text = _remove_bad_hashtags(text)

    # 6. إزالة تسريبات اسم المصدر
    text = _remove_source_leaks(text)

    # 7. إزالة الأسطر المكررة
    text = _remove_duplicate_lines(text)

    # 8. تنظيف النص العربي
    text = _clean_arabic_text(text)

    # 9. تسوية المسافات البيضاء (أخيراً)
    text = _normalize_whitespace(text)

    return text


# ═══════════════════════════════════════════════════════════
# 📰 الوظيفة الرئيسية — Main Public Function
# ═══════════════════════════════════════════════════════════

def clean_news_item(item: NewsItem) -> NewsItem:
    """
    تنظيف عنصر خبر واحد — تنظيف العنوان والملخص.
    Cleans a news item's title and summary, sets clean_title and clean_summary.

    هذه الوظيفة تقوم فقط بالتنظيف — لا تترجم ولا تصنّف.
    Args:
        item: عنصر NewsItem يحتوي على title و summary خام.

    Returns:
        نفس عنصر NewsItem مع clean_title و clean_summary مملوءة.
    """
    if not isinstance(item, NewsItem):
        log.error(f"clean_news_item: invalid type {type(item)}, expected NewsItem")
        return item

    try:
        # --- تنظيف العنوان ---
        raw_title = item.title or ""
        if raw_title:
            item.clean_title = _run_cleaning_pipeline(raw_title)
            # العناوين: إزالة فواصل الأسطر وإزالة نقاط نهاية السطر
            item.clean_title = item.clean_title.replace("\n", " ")
            item.clean_title = item.clean_title.strip()
        else:
            item.clean_title = ""

        # --- تنظيف الملخص ---
        raw_summary = item.summary or ""
        if raw_summary:
            item.clean_summary = _run_cleaning_pipeline(raw_summary)
            item.clean_summary = item.clean_summary.strip()
        else:
            item.clean_summary = ""

        # --- تحقق أساسي ---
        if not item.clean_title and not item.clean_summary:
            log.warning(
                f"clean_news_item: item became empty after cleaning. "
                f"Source={item.source}, hash={item.hash}"
            )

        log.debug(
            f"clean_news_item: source={item.source}, "
            f"title: '{item.clean_title[:60]}...' "
            f"({len(raw_title)}→{len(item.clean_title)} chars)"
        )

    except Exception as e:
        log.error(
            f"clean_news_item FAILED for source={item.source}, "
            f"hash={item.hash}: {e}",
            exc_info=True,
        )
        # في حالة الفشل — نستخدم النص الخام كـ fallback
        item.clean_title = item.title or ""
        item.clean_summary = item.summary or ""

    return item
