# -*- coding: utf-8 -*-
"""
اكتشاف التكرار والتشابه بين الأخبار.

طبقتان:
1. تطابق تام: نفس بصمة SHA-256 → نسخة مطابقة حرفياً.
2. تشابه دلالي تقريبي: RapidFuzz (token_sort_ratio) بين:
   - النص الخام الجديد ونصوص المصدر للأخبار المنشورة (يلتقط النسخ المنسوخة)
   - النص النهائي الجديد والنصوص النهائية المنشورة (يلتقط نفس الخبر بصياغتين مختلفتين)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

log = logging.getLogger("dedup")


def similarity_score(text_a: str, text_b: str) -> float:
    """درجة التشابه 0-100 بين نصين مطبّعين."""
    if not text_a or not text_b:
        return 0.0
    return float(fuzz.token_sort_ratio(text_a, text_b))


def find_similar(
    normalized_raw: str,
    normalized_final: str,
    published: Sequence[Tuple[int, str, str]],
    threshold: float,
) -> Optional[Tuple[int, float, str]]:
    """
    البحث عن خبر منشور مشابه.
    published: [(published_id, normalized_raw, normalized_final)]
    يعيد (id, الدرجة, نوع المقارنة) أو None.
    """
    best: Optional[Tuple[int, float, str]] = None

    for pub_id, pub_raw, pub_final in published:
        # مقارنة 1: خام جديد × خام منشور
        score = similarity_score(normalized_raw, pub_raw)
        if best is None or score > best[1]:
            best = (pub_id, score, "raw_vs_raw")
        # مقارنة 2: نهائي جديد × نهائي منشور (الأسلوب موحّد بعد AI → تشابه أعلى لنفس الخبر)
        if normalized_final:
            score = similarity_score(normalized_final, pub_final)
            if best is None or score > best[1]:
                best = (pub_id, score, "final_vs_final")

    if best and best[1] >= threshold:
        log.debug("تشابه مكتشف: خبر #%s بدرجة %.1f (%s)", best[0], best[1], best[2])
        return best
    return None
