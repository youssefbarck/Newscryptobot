"""
📝 تنسيق المنشور — صيغة عاجل قصيرة ومباشرة
"""

import re
from typing import Optional

from config import CHANNEL_TAG, MAX_BULLETS, log


# ═══════════════════════════════════════════════════════════
# أنماط محظورة في العناوين
# ═══════════════════════════════════════════════════════════
# 1) عناوين تنتهي بسؤال — ممنوعة باتاً
QUESTION_ENDINGS = re.compile(r'[?؟]\s*$')

# 2) عبارات ترويجية / تلميحية (تحتاج رابط للفهم)
TEASER_PATTERNS = [
    r'^here\b', r'^what\s+happened', r'^here\'?s\s+what',
    r'^things\s+to\s+know', r'^what\s+you\s+need',
    r'^everything\s+you', r'^all\s+you\s+need',
    r'^why\s+you\s+should', r'^should\s+you\b',
    r'^is\s+it\s+time\b', r'^will\s+\w+\s+(go|rise|fall|surge|crash)',
    r'^what\'s\s+next', r'^what\s+to\s+expect',
    r'\?$|؟\s*$',  # أي سؤال
]

# 3) عبارات تدل على تحليل/رأي وليس خبر
ANALYSIS_PATTERNS = [
    r'\bstudy\b', r'\bresearch\b', r'\bsurvey\b', r'\breport\s+says\b',
    r'\baccording\s+to\s+a\s+study\b', r'\bfinds\s+that\b',
    r'\bopinion\b', r'\banalysis\b', r'\bcommentary\b',
    r'^state\s+of\b', r'\bweekly\s+roundup\b', r'\bdaily\s+digest\b',
    r'\bprice\s+prediction\b', r'\bprice\s+forecast\b',
    r'\btop\s+\d+\s+(altcoins|coins|meme|gainers)',
    r'\b\d+\s+(crypto|bitcoin|altcoin)\s+to\s+watch\b',
]

# عبارات ترويجية عربية (بعد الترجمة)
PROMO_PATTERNS_AR = [
    r'اقرأ المزيد', r'تابع القراءة', r'اضغط هنا',
    r'للمزيد', r'لمشاهدة', r'للاطلاع',
    r'المصدر[:\s]', r'تابعنا',
]

PROMO_PATTERNS_EN = [
    r'read more', r'click here', r'learn more',
    r'subscribe', r'follow us', r'source[:\s]',
    r'disclaimer', r'related articles',
]


# ═══════════════════════════════════════════════════════════
# أيقونات نوع الخبر
# ═══════════════════════════════════════════════════════════
def _detect_news_type(title: str, summary: str) -> str:
    """تحديد نوع الخبر لإيقونة مناسبة"""
    text = (title + ' ' + summary).lower()
    
    # اختراق / سرقة
    if any(w in text for w in ['hack', 'hacked', 'exploit', 'breach', 'stolen', 'drained', 'theft']):
        return '🚨'
    # تنظيم / حظر
    if any(w in text for w in ['sec ', 'approved', 'banned', 'regulation', 'lawsuit', 'sued',
                                'subpoena', 'compliance', 'fine', 'penalty', 'indictment',
                                'legal', 'court', 'judge', 'arrested']):
        return '⚖️'
    # ETF / استثمار مؤسسي
    if any(w in text for w in ['etf', 'inflow', 'outflow', 'institutional', 'blackrock',
                                'fidelity', 'grayscale', 'spot bitcoin', 'spot eth']):
        return '📊'
    # ارتفاع حاد
    if any(w in text for w in ['surge', 'soar', 'skyrocket', 'rally', 'pump',
                                'all-time high', 'record high', 'ath', 'breaks']):
        return '📈'
    # هبوط حاد
    if any(w in text for w in ['plunge', 'crash', 'dump', 'slump', 'correction',
                                'record low', 'drop', 'tumble', 'freefall']):
        return '📉'
    # إفلاس / انهيار
    if any(w in text for w in ['bankrupt', 'bankruptcy', 'collapse', 'shut down', 'cease']):
        return '💀'
    # halving / ترقيات كبيرة
    if any(w in text for w in ['halving', 'fork', 'mainnet', 'upgrade', 'airdrop']):
        return '⚡'
    # FED / اقتصاد كلوي
    if any(w in text for w in ['federal reserve', 'rate cut', 'rate hike', 'fomc',
                                'interest rate', 'powell', 'inflation', 'recession']):
        return '🏦'
    # شراء/بيع كبار
    if any(w in text for w in ['buys', 'bought', 'sells', 'sold', 'purchases',
                                'acquires', 'invests', 'investment']):
        return '💰'
    # افتراضي
    return '🔴'


# ═══════════════════════════════════════════════════════════
# فلتر العناوين — يرفض الخبر إذا كان غير صالح
# ═══════════════════════════════════════════════════════════
def is_banned_title(title: str) -> bool:
    """فحص صارم: هل العنوان ممنوع؟ (سؤال / تلميح / تحليل)"""
    if not title:
        return True
    
    t = title.strip()
    t_lower = t.lower()
    
    # 1) سؤال في النهاية — ممنوع باتاً
    if QUESTION_ENDINGS.search(t):
        return True
    
    # 2) سؤال في أي مكان
    if '?' in t or '؟' in t:
        return True
    
    # 3) تلميح / إعلان
    for pat in TEASER_PATTERNS:
        if re.search(pat, t_lower):
            return True
    
    # 4) تحليل / رأي / ملخص أسبوعي
    for pat in ANALYSIS_PATTERNS:
        if re.search(pat, t_lower):
            return True
    
    # 5) قصير جداً (أقل من 20 حرف = غالباً غير مفيد)
    if len(t) < 20:
        return True
    
    return False


def is_banned_title_ar(title_ar: str) -> bool:
    """فحص العنوان المترجم (بعد الترجمة)"""
    if not title_ar:
        return True
    
    t = title_ar.strip()
    
    # سؤال — ممنوع باتاً
    if '?' in t or '؟' in t:
        return True
    
    # ترويجي
    for pat in PROMO_PATTERNS_AR:
        if re.search(pat, t, re.IGNORECASE):
            return True
    
    # قصير جداً
    if len(t) < 20:
        return True
    
    return False


# ═══════════════════════════════════════════════════════════
# تنظيف العنوان المترجم
# ═══════════════════════════════════════════════════════════
def clean_title(title: str) -> str:
    """تنظيف العنوان المترجم من العيوب"""
    if not title:
        return ""

    # إزالة placeholders متسربة
    title = re.sub(r'\[\[\s*\d+\s*\]\]', '', title)
    title = re.sub(r'§\d+§?', '', title)

    # إزالة أسماء مصادر من النهاية
    source_patterns = [
        r'\s*[—–\-|]\s*(?:Cryptonews(?:\.net)?|CryptoRank|CoinDesk|Cointelegraph|Decrypt|The Block|Blockworks|Bitcoin\.com|NewsBTC|BeInCrypto|CryptoPotato|Reuters|Bloomberg|CNBC|Forbes|WatcherGuru)\s*$',
    ]
    for pat in source_patterns:
        title = re.sub(pat, '', title, flags=re.IGNORECASE)

    # إزالة عبارات ترويجية
    for pat in PROMO_PATTERNS_AR + PROMO_PATTERNS_EN:
        title = re.sub(pat, '', title, flags=re.IGNORECASE)

    # إزالة مسافات زائدة
    title = re.sub(r'\s{2,}', ' ', title).strip()
    title = re.sub(r'^[•·▪►»«\-\s]+', '', title)
    title = re.sub(r'\s*[\-|–—]\s*$', '', title)
    title = re.sub(r'\s+([.،,!؟?])', r'\1', title)
    
    # إزالة "كما هو موضح" و "وفقا لـ" في البداية
    title = re.sub(r'^(وفقا\s+لل?|كما\s+يوضح|يُظهر\s+أن|تشير\s+البيانات)\s*', '', title, flags=re.IGNORECASE)
    
    return title.strip()


# ═══════════════════════════════════════════════════════════
# استخراج سطر التفاصيل (بديل النقاط)
# ═══════════════════════════════════════════════════════════
def _is_promotional(text: str) -> bool:
    if not text:
        return True
    t = text.lower().strip()
    for pat in PROMO_PATTERNS_AR + PROMO_PATTERNS_EN:
        if re.search(pat, t):
            return True
    return False


def extract_detail_lines(summary: str, max_lines: int = MAX_BULLETS) -> list:
    """
    استخراج أقوى سطر أو سطرين من الملخص.
    نبحث عن جمل تحتوي أرقام/نسب/أسماء — ليست حشواً.
    """
    if not summary or not summary.strip():
        return []

    sentences = re.split(r'(?<=[.!?؟])\s+', summary.strip())
    
    lines = []
    for sent in sentences:
        sent = sent.strip().strip('.').strip()
        if not sent:
            continue
        if len(sent) < 25:
            continue
        if len(sent) > 200:
            continue
        if _is_promotional(sent):
            continue
        # يجب أن يحتوي على معلومة ملموسة (رقم أو اسم محمي أو نسبة)
        if not re.search(r'\d|[%$]', sent):
            continue
        lines.append(sent)
        if len(lines) >= max_lines:
            break

    return lines


# ═══════════════════════════════════════════════════════════
# بناء نص المنشور الجديد
# ═══════════════════════════════════════════════════════════
def format_post(item) -> Optional[str]:
    """
    صيغة عاجل قصيرة ومباشرة:
      🔴 عاجل | Bitcoin يتخطى 82,000$ للمرة الأولى

      ارتفع BTC بنسبة 5% خلال ساعات...

      @newscrypto1m
    """
    title_ar = clean_title(getattr(item, 'title_ar', '') or item.title)
    if not title_ar or len(title_ar) < 20:
        return None

    # تحديد أيقونة نوع الخبر
    icon = _detect_news_type(item.title, item.summary)

    # بناء العنوان مع الأيقونة
    header = f"{icon} {title_ar}"

    # تفاصيل موجزة (سطر أو سطرين فقط)
    details = extract_detail_lines(getattr(item, 'summary_ar', '') or '')

    lines = [header]
    
    if details:
        lines.append('')
        for d in details:
            lines.append(f"▸ {d}")
    
    lines.append('')
    lines.append(CHANNEL_TAG)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# التحقق من جودة المنشور
# ═══════════════════════════════════════════════════════════
def _has_leaked_placeholder(text: str) -> bool:
    if not text:
        return False
    if re.search(r'\[\[\s*\d+\s*\]\]', text):
        return True
    if '§' in text:
        return True
    if re.search(r'\bXX\d+XX\b', text):
        return True
    return False


def validate_post(text: str) -> bool:
    """فحص صارم أن المنشور صالح للإرسال"""
    if not text or len(text) < 30:
        return False
    if CHANNEL_TAG not in text:
        return False

    # فحص placeholder متسرب
    if _has_leaked_placeholder(text):
        log.warning(f"⚠️ Leaked placeholder in post")
        return False

    # فحص سؤال — ممنوع باتاً
    if '?' in text or '؟' in text:
        log.warning(f"⚠️ Question mark in post — BANNED")
        return False

    # فحص نسبة الحروف العربية (> 25%)
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters > 0 and arabic_chars / total_letters < 0.25:
        log.warning(f"⚠️ Arabic ratio too low: {arabic_chars}/{total_letters}")
        return False

    # فحص اسم مصدر متسرب
    if re.search(r'(Cryptonews\.net|CryptoRank|CoinDesk|Cointelegraph)\b', text):
        log.warning(f"⚠️ Source name leaked in post")
        return False

    return True
