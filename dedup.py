"""
🧹 منع التكرار — حفظ الهاشات في ملف JSON داخل الريبو
"""

import re
import json
import os
import hashlib
import time
from typing import Set

from config import DEDUP_FILE, SIMILARITY_THRESHOLD, log


# ═══════════════════════════════════════════════════════════
# تحميل الهاشات المحفوظة
# ═══════════════════════════════════════════════════════════
def load_hashes() -> Set[str]:
    """تحميل الهاشات المحفوظة من ملف JSON"""
    if not os.path.exists(DEDUP_FILE):
        log.info(f"📊 No dedup file yet — first run. Path: {DEDUP_FILE}")
        return set()
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            hashes = set(data.get("hashes", []))
            log.info(f"✅ Loaded {len(hashes)} hashes from {DEDUP_FILE}")
            return hashes
    except Exception as e:
        log.warning(f"❌ Dedup load error: {e}")
        return set()


# ═══════════════════════════════════════════════════════════
# حفظ الهاشات
# ═══════════════════════════════════════════════════════════
def save_hashes(hashes: Set[str]):
    """حفظ الهاشات في ملف JSON"""
    try:
        os.makedirs(os.path.dirname(DEDUP_FILE), exist_ok=True)
        # الاحتفاظ بآخر 3000 هاش فقط
        hash_list = list(hashes)[-3000:]
        content = {
            "hashes": hash_list,
            "last_updated": time.time(),
            "count": len(hash_list),
        }
        with open(DEDUP_FILE, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
        log.info(f"💾 Saved {len(hash_list)} hashes → {DEDUP_FILE}")
    except Exception as e:
        log.error(f"❌ Save error: {e}")


# ═══════════════════════════════════════════════════════════
# حساب هاش الخبر
# ═══════════════════════════════════════════════════════════
def compute_hash(title: str) -> str:
    """
    هاش مبني على العنوان المُطبّع:
    - أحرف صغيرة
    - إزالة علامات الترقيم والمسافات الزائدة
    - أخذ أول 100 حرف فقط (لتفادي اختلافات العنوان الطويل)
    """
    norm = re.sub(r'[^\w\s\u0600-\u06FF]', '', title.lower())
    norm = re.sub(r'\s+', ' ', norm).strip()
    norm = norm[:100]
    return hashlib.md5(norm.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════
# كشف التشابه — Jaccard Similarity
# ═══════════════════════════════════════════════════════════
def _normalize_text(t: str) -> str:
    """تطبيع النص لفحص التشابه"""
    if not t:
        return ""
    t = re.sub(r'[^\w\s\u0600-\u06FF]', ' ', t.lower())
    t = re.sub(r'\s+', ' ', t).strip()
    # إزالة الكلمات الشائعة (stop words)
    stop = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'of', 'for', 'and', 'or',
            'في', 'من', 'إلى', 'على', 'عن', 'أن', 'إن', 'ال', 'و', 'أو'}
    words = [w for w in t.split() if w not in stop and len(w) > 1]
    return ' '.join(words)


def is_similar(title: str, recent_titles: list, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """
    فحص تشابه العنوان مع العناوين الحديثة باستخدام Jaccard similarity.
    threshold: نسبة التشابه المطلوبة لاعتبار العنوان مكرراً (0.65 = 65%)
    """
    if not title:
        return False
    norm = _normalize_text(title)
    if not norm:
        return False
    words_new = set(norm.split())
    if len(words_new) < 3:
        return False
    for prev in recent_titles:
        words_prev = set(_normalize_text(prev).split())
        if not words_prev:
            continue
        intersection = len(words_new & words_prev)
        union = len(words_new | words_prev)
        if union > 0:
            sim = intersection / union
            if sim >= threshold:
                return True
    return False


# ═══════════════════════════════════════════════════════════
# فحص شامل للتكرار
# ═══════════════════════════════════════════════════════════
def is_duplicate(title: str, sent_hashes: Set[str], recent_titles: list) -> bool:
    """
    فحص شامل: هاش مباشر + تشابه مع آخر العناوين
    """
    if not title:
        return True

    h = compute_hash(title)
    if h in sent_hashes:
        log.info(f"🧹 Exact hash match: {title[:60]}")
        return True

    if is_similar(title, recent_titles):
        log.info(f"🧹 Similar to recent: {title[:60]}")
        return True

    return False
