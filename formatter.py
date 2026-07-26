"""
📝 تنسيق المنشور — العنوان + النقاط + وسم القناة
"""

import re
from typing import Optional

from config import CHANNEL_TAG, MAX_BULLETS, log


# ═══════════════════════════════════════════════════════════
# أنماط للجمل الترويجية / غير المفيدة (تُستبعد)
# ═══════════════════════════════════════════════════════════
# عبارات عربية (مترجمة) تشير إلى ترويج للرابط أو المصدر
PROMO_PATTERNS_AR = [
    r'اقرأ المزيد', r'اقرأ كامل', r'اقرأ التفاصيل',
    r'تابع القراءة', r'اكمل القراءة', r'تتمة',
    r'اضغط هنا', r'انقر هنا', r'اضغط على',
    r'للمزيد', r'لقراءة', r'لمشاهدة', r'للاطلاع',
    r'اشترك', r'سجل الآن', r'انضم',
    r'مشاركة', r'شارك', r'طباعة',
    r'المصدر[:\s]', r'اقرأ أيضا', r'اقرأ أيضاً',
    r'تابعنا', r'زورونا', r'تابع',
    r'صورة[:\s]', r'الصورة[:\s]',
    r'تنويه[:\s]', r'إخلاء مسؤولية',
    r'محتويات الصفحة', r'انتقل إلى',
    r'حجم الخط', r'كبر الخط', r'صغر الخط',
    r'نسخ الرابط', r'شارك المقال',
    r'مقالات ذات صلة', r'أخبار ذات صلة',
    r'الوسوم[:\s]', r'كلمات مفتاحية',
]

# عبارات إنجليزية شائعة قبل الترجمة (نطبقها على النص الأصلي ثم المترجم)
PROMO_PATTERNS_EN = [
    r'read more', r'read the full', r'continue reading',
    r'click here', r'click to', r'learn more',
    r'subscribe', r'sign up', r'join us',
    r'share this', r'follow us', r'visit us',
    r'source[:\s]', r'image[:\s]', r'photo[:\s]',
    r'disclaimer', r'disclosure',
    r'related articles', r'related posts',
    r'tags[:\s]', r'keywords[:\s]',
]


def _is_promotional(text: str) -> bool:
    """فحص إن كانت الجملة ترويجية أو غير مفيدة"""
    if not text:
        return True
    text_lower = text.lower().strip()

    # 1) عبارات ترويجية عربية
    for pat in PROMO_PATTERNS_AR:
        if re.search(pat, text_lower):
            return True

    # 2) عبارات ترويجية إنجليزية (قد تبقى بعد الترجمة)
    for pat in PROMO_PATTERNS_EN:
        if re.search(pat, text_lower):
            return True

    return False


# ═══════════════════════════════════════════════════════════
# فحص جودة الجملة العربية
# ═══════════════════════════════════════════════════════════
def _has_arabic_verb_like(text: str) -> bool:
    """
    فحص بدائي: هل يحتوي النص على فعل عربي أو تركيب جملة طبيعي؟
    الجمل المترجمة سيئة عادةً تكون مجرد أسماء متتابعة بدون أفعال.
    """
    if not text:
        return False
    # أنماط شائعة للأفعال العربية وأدوات الربط
    verb_patterns = [
        # أفعال ماضية شائعة في الأخبار
        r'(?:كان|كانت|يكون|تكون|أصبح|أصبحت|صار|صارت)',
        r'(?:قال|يقول|قالت|تقول|أعلن|أعلنت|يعلن|تعلن)',
        r'(?:رفض|يقبل|وافق|قرر|أكد|نفى|أشار|أوضح|ذكر|أبلغ)',
        r'(?:شهد|سجل|بلغ|وصل|ارتفع|انخفض|تراجع|قفز|هبط|نمو|نمت)',
        r'(?:بدأ|انطلق|أطلق|أسس|أقام|فتح|غادر|دخل|خرج|وصل)',
        r'(?:كشف|كشفت|أظهرت|أظهر|أوضحت|بينت|أكدت|لفت|لفتت)',
        r'(?:يعد|تعد|يعتبر|تعتبر|يمثل|تمثل|يشكل|تشكل)',
        r'(?:توقع|يتوقع|تتوقع|توقعوا|يتوقعون)',
        # أدوات الربط (تدل على جملة كاملة)
        r'(?:قد|سي|سوف|ثم|حيث|عندما|بعد|قبل|خلال|بينما|فيما|إذ|لكن|إلا)',
        # ضمائر + يبدأ بعدها فعل
        r'(?:هو|هي|هم|هن|نحن|أنا)\s+\w{3,}',
        # اسم إشارة + فعل
        r'(?:هذا|هذه|ذلك|تلك|هؤلاء)\s+\w{3,}',
    ]
    for pat in verb_patterns:
        if re.search(pat, text):
            return True
    return False


def _has_leaked_placeholder(text: str) -> bool:
    """فحص إن كان النص يحتوي على placeholder متسرب"""
    if not text:
        return False
    if re.search(r'\[\[\d+\]\]', text):
        return True
    if '§' in text:  # أي رمز § متبقي = تسرب
        return True
    if re.search(r'\bXX\d+XX\b', text):
        return True
    return False


# ═══════════════════════════════════════════════════════════
# استخراج النقاط من الملخص المترجم
# ═══════════════════════════════════════════════════════════
def extract_bullets(summary: str, max_bullets: int = MAX_BULLETS) -> list:
    """
    تحويل الملخص إلى نقاط واضحة وعالية الجودة:
    - تقسيم عند الجمل (. ! ؟)
    - فلترة الجمل القصيرة
    - فلترة الجمل الترويجية
    - فلترة الجمل بدون فعل عربي
    - فلترة الجمل التي تسربت placeholders
    """
    if not summary or not summary.strip():
        return []

    # تقسيم عند الجمل
    sentences = re.split(r'(?<=[.!?؟])\s+', summary.strip())

    bullets = []
    seen_lower = set()
    for sent in sentences:
        sent = sent.strip().strip('.').strip()
        if not sent:
            continue

        # طول أدنى
        if len(sent) < 30:
            continue

        # طول أقصى (جمل طويلة جداً = سيئة)
        if len(sent) > 250:
            # محاولة اقتطاع عند أول فاصلة منطقية
            cut = sent[:250].rsplit('،', 1)[0].rsplit(',', 1)[0]
            if len(cut) < 35:
                continue
            sent = cut

        # فلترة ترويجية
        if _is_promotional(sent):
            continue

        # فلترة placeholder متسرب
        if _has_leaked_placeholder(sent):
            continue

        # فلترة بدون فعل عربي (ترجمة سيئة)
        if not _has_arabic_verb_like(sent):
            continue

        # إزالة التكرار
        sent_key = re.sub(r'[^\w\s\u0600-\u06FF]', '', sent.lower())[:80]
        if sent_key in seen_lower:
            continue
        seen_lower.add(sent_key)

        bullets.append(sent)
        if len(bullets) >= max_bullets:
            break

    return bullets


# ═══════════════════════════════════════════════════════════
# تنظيف العنوان المترجم
# ═══════════════════════════════════════════════════════════
def clean_title(title: str) -> str:
    """تنظيف العنوان المترجم"""
    if not title:
        return ""

    # إزالة placeholders متسربة
    title = re.sub(r'\[\[\d+\]\]', '', title)
    title = re.sub(r'§\d+§?', '', title)

    # إزالة أسماء مصادر شائعة من النهاية (بعد الترجمة)
    source_patterns = [
        r'\s*[—–\-|]\s*(Cryptonews(?:\.net)?|CryptoRank|CoinDesk|Cointelegraph|Decrypt|The Block|Blockworks|Bitcoin\.com|NewsBTC|CryptoNews|BeInCrypto|CryptoPotato|Reuters|Bloomberg|CNBC|Forbes)\s*$',
        r'\s*(Cryptonews\.net|CryptoRank)\s*$',
    ]
    for pat in source_patterns:
        title = re.sub(pat, '', title, flags=re.IGNORECASE)

    # إزالة مسافات زائدة
    title = re.sub(r'\s+', ' ', title).strip()

    # إزالة علامات غريبة في البداية
    title = re.sub(r'^[•·▪►»«\-\s]+', '', title)

    # إزالة " - " في النهاية
    title = re.sub(r'\s*[-|–—]\s*$', '', title)

    # إزالة مسافات قبل علامات الترقيم
    title = re.sub(r'\s+([.،,!؟?])', r'\1', title)

    return title.strip()


# ═══════════════════════════════════════════════════════════
# بناء نص المنشور
# ═══════════════════════════════════════════════════════════
def format_post(item) -> Optional[str]:
    """
    بناء نص المنشور:
      العنوان الواضح
      • نقطة 1
      • نقطة 2
      @newscrypto1m
    """
    title = clean_title(getattr(item, 'title_ar', '') or item.title)
    if not title or len(title) < 15:
        return None

    bullets = extract_bullets(getattr(item, 'summary_ar', '') or '')

    lines = [title, ""]

    if bullets:
        for b in bullets:
            lines.append(f"• {b}")
        lines.append("")

    lines.append(CHANNEL_TAG)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# التحقق من جودة المنشور
# ═══════════════════════════════════════════════════════════
def validate_post(text: str) -> bool:
    """فحص صارم أن المنشور صالح للإرسال"""
    if not text or len(text) < 50:
        return False
    if CHANNEL_TAG not in text:
        return False

    # فحص placeholder متسرب
    if _has_leaked_placeholder(text):
        log.warning(f"⚠️ Leaked placeholder in post")
        return False

    # فحص نسبة الحروف العربية (> 30%)
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters > 0 and arabic_chars / total_letters < 0.3:
        log.warning(f"⚠️ Arabic ratio too low: {arabic_chars}/{total_letters}")
        return False

    # فحص اسم مصدر متسرب
    if re.search(r'(Cryptonews\.net|CryptoRank|CoinDesk|Cointelegraph)\b', text):
        log.warning(f"⚠️ Source name leaked in post")
        return False

    return True
