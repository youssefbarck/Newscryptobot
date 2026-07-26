"""
📝 تنسيق المنشور — العنوان + النقاط + وسم القناة
"""

import re
from typing import Optional

from config import CHANNEL_TAG, MAX_BULLETS, log


# ═══════════════════════════════════════════════════════════
# استخراج النقاط من الملخص المترجم
# ═══════════════════════════════════════════════════════════
def extract_bullets(summary: str, max_bullets: int = MAX_BULLETS) -> list:
    """
    تحويل الملخص إلى نقاط واضحة:
    - تقسيم عند الجمل (. ! ؟)
    - فلترة الجمل القصيرة جداً
    - إزالة الجمل المكررة
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
        # تجاهل الجمل القصيرة جداً (أقل من 30 حرف)
        if len(sent) < 30:
            continue
        # تجاهل الجمل التي تبدأ بكلمات غير مفيدة
        skip_starts = ['طباعة', 'مشاركة', 'انقر', 'اقرأ المزيد', 'اشترك', 'تابعنا']
        if any(sent.lower().startswith(s.lower()) for s in skip_starts):
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
    # إزالة مسافات زائدة
    title = re.sub(r'\s+', ' ', title).strip()
    # إزالة علامات غريبة في البداية
    title = re.sub(r'^[•·▪►»«\-\s]+', '', title)
    # إزالة " - " في النهاية (بقايا اسم الموقع)
    title = re.sub(r'\s*[-|–—]\s*$', '', title)
    return title.strip()


# ═══════════════════════════════════════════════════════════
# بناء نص المنشور
# ═══════════════════════════════════════════════════════════
def format_post(item) -> Optional[str]:
    """
    بناء نص المنشور بالتنسيق المطلوب:
      العنوان الواضح
      • نقطة 1
      • نقطة 2
      • نقطة 3

      @newscrypto1m
    """
    title = clean_title(getattr(item, 'title_ar', '') or item.title)
    if not title:
        return None

    bullets = extract_bullets(getattr(item, 'summary_ar', '') or '')

    # بناء النص
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
    """فحص أن المنشور صالح للإرسال"""
    if not text or len(text) < 50:
        return False
    if CHANNEL_TAG not in text:
        return False
    # فحص نسبة الحروف العربية (يجب أن تكون > 30%)
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters > 0 and arabic_chars / total_letters < 0.3:
        log.warning(f"⚠️ Arabic ratio too low: {arabic_chars}/{total_letters}")
        return False
    return True
