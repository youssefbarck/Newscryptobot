# -*- coding: utf-8 -*-
"""
تطبيع النصوص العربية والإنجليزية + توليد البصمات (Hash) + استخراج الأرقام.

التطبيع يجعل المقارنة عادلة: إزالة التشكيل، توحيد الألف/الياء/التاء المربوطة،
توحيد الأرقام العربية والهندية، إزالة الروابط وعلامات الترقيم والمسافات الزائدة.
"""
from __future__ import annotations

import hashlib
import re

# تحويل الأرقام العربية الهندية (٠-٩) والفارسية (۰-۹) إلى ASCII
_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# التشكيل والتطويل
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")

# الروابط تُحذف قبل المقارنة (نسخ الخبر نفسه غالباً يستخدم روابط مختصرة مختلفة)
_URL = re.compile(r"(?:https?://\S+|www\.\S+|t\.me/\S+)", re.IGNORECASE)

# كل ما ليس حرفاً/رقماً/شرطة سفلية/حرفاً عربياً يُعتبر فاصلاً
_NON_WORD = re.compile(r"[^\w\u0600-\u06FF]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """نص مطبّع جاهز للمقارنة وتوليد البصمة."""
    if not text:
        return ""
    t = text.translate(_DIGIT_MAP)
    t = _DIACRITICS.sub("", t)
    t = t.replace("٪", "%")
    # توحيد الحروف العربية المتشابهة كتابةً
    t = (
        t.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
        .replace("ؤ", "و")
        .replace("ئ", "ي")
    )
    t = t.lower()
    t = _URL.sub(" ", t)
    t = _NON_WORD.sub(" ", t)
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def content_hash(text: str) -> str:
    """بصمة SHA-256 للنص المطبّع — تُستخدم لكشف النسخ المتطابقة حرفياً."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- الأرقام

_NUMBER = re.compile(r"[$€£]?\s?\d+(?:[.,]\d+)*\s*%?")


def number_tokens(text: str) -> set:
    """
    استخراج الرموز الرقمية من النص: أسعار، نسب، تواريخ، كميات.
    مثال: "ارتفع BTC بنسبة 3.5% ليصل إلى $64,200 في 2025" → {"3.5%", "$64,200", "2025"}
    """
    if not text:
        return set()
    t = text.translate(_DIGIT_MAP).replace("٪", "%")
    tokens = set()
    for match in _NUMBER.finditer(t):
        token = match.group(0).replace(" ", "").replace("\u00a0", "").strip()
        if token and not set(token) <= {"$"}:  # تجاهل رمز العملة الأرمل
            tokens.add(token)
    return tokens


def _token_variants(token: str) -> set:
    """
    صيغ مقارنة مقبولة لكل رقم: "$64,200" → {"$64200", "64200"} و"3.5%" → {"3.5%", "3.5"}.
    السبب: كتابة العملة ككلمة ("64,200 دولار") أو النسبة ككلمة ("3.5 بالمئة")
    تحفظ الحقيقة رغم اختلاف الرمز — والفحص يستهدف الأرقام لا الأسلوب.
    """
    base = token.replace(",", "")
    variants = {base}
    if base and base[0] in "$€£":
        variants.add(base[1:])
    if base.endswith("%"):
        variants.add(base[:-1])
    return variants


def tokens_missing_in(source_text: str, output_text: str) -> list:
    """
    فحص سلامة الأرقام: أي رقم ورد في المصدر ولم يظهر في المخرجات بأي صيغة مقبولة.
    يُقارن بعد إزالة الفواصل (64,200 == 64200) ورموز العملة والنسبة — تحذير منطقي لا حرفي.
    """
    if not source_text or not output_text:
        return []
    out = output_text.translate(_DIGIT_MAP).replace(",", "")
    missing = []
    for token in sorted(number_tokens(source_text)):
        if not any(variant and variant in out for variant in _token_variants(token)):
            missing.append(token)
    return missing
