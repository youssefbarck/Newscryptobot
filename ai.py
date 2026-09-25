# -*- coding: utf-8 -*-
"""
تكامل Gemini — إعادة صياغة الخبر كصحافة عربية احترافية (ليست ترجمة).

- إخراج JSON مُقيّد بمخطط Pydantic → لا انهيار بسبب نص خارج المخطط.
- إعادة محاولة تلقائية بتراجع أُسّي عند فشل النداء.
- فحص سلامة الأرقام بعد كل صياغة، مع محاولة تصحيحية واحدة عند سقوط أرقام.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import List, Optional

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from bot.config import AISettings
from bot.normalizer import tokens_missing_in

log = logging.getLogger("ai")


class NewsDraft(BaseModel):
    """مخطط مخرجات الذكاء الاصطناعي — JSON صارم."""
    is_news: bool = Field(description="صحيح فقط إذا كان المنشور خبراً حقيقياً يستحق النشر")
    title: Optional[str] = Field(default=None, description="عنوان عربي قصير وواضح")
    body: Optional[str] = Field(default=None, description="نص الخبر بصياغة عربية احترافية")
    ticker: Optional[str] = Field(default=None, description="رمز العملة إذا ذُكر صراحة، وإلا null")
    reason: Optional[str] = Field(default=None, description="سبب الرفض عند is_news=false")


# ---------------------------------------------------------------- البرومبت

PROMPT_TEMPLATE = """أنت محرر أخبار عربي محترف في منصة رقمية متخصصة بأخبار العملات الرقمية والتقنية (بأسلوب CoinDesk وThe Block بالعربية).
ستستلم منشوراً خاماً من قناة تيليجرام باسم "{source_name}". مهمتك: أن تفهم الخبر، تستخرج المعلومة الأساسية، ثم تعيد كتابته كخبر عربي قصير احترافي.

القواعد الصارمة (غير قابلة للتفاوض):
1. أعد الكتابة بأسلوبك الصحفي — ممنوع الترجمة الحرفية أو الترجمة الآلية أو نسخ الجمل كما هي.
2. الحقائق مقدسة: احفظ كل الأرقام والأسعار والنسب والمواعيد وأسماء الأشخاص والشركات والمشاريع والعملات حرفياً دون أي تغيير أو تقريب.
3. لا تختلق أي معلومة. لا تضف تحليلاً أو رأياً أو خلفية أو سياقاً غير موجود في المنشور. إذا كان المصدر غامضاً فاجعل الخبر غامضاً بنفس الدرجة.
4. احذف الحشو والتكرار وعبارات الترحيب وعبارات الترويج الدعائية.
5. إذا كان المنشور بالعربية أصلاً فحسّن صياغته فقط — لا تعده ترجمة.
6. العنوان (title): عربي، واضح، مباشر، من 4 إلى 12 كلمة، بدون مبالغة أو clickbait.
7. نص الخبر (body): من {min_body} إلى {max_body} حرف تقريباً، بجُمل قصيرة ولغة عربية سليمة. إذا كان الخبر قصيراً أصلاً فلا تمدّه بلا داعٍ.
8. لا تضع روابط أو هاشتاقات أو إيموجي داخل title أو body.
9. حقل ticker: رمز العملة (بدون $) فقط إذا ذُكر صراحة أو كان مؤكداً بلا شك من نص الخبر. في أي حالة شك → null. ممنوع التخمين أبداً.
10. إذا كان المنشور إعلاناً أو دعاية أو سبارم أو استفتاءً أو رأياً شخصياً أو تعليقاً غير إخباري أو محتوى غير لائق: اجعل is_news=false واكتب السبب المختصر في reason، واترك الحقول الأخرى null.

المنشور الخام من قناة "{source_name}":
<<<
{text}
>>>

أعد النتيجة بصيغة JSON فقط وفق المخطط المطلوب، بدون أي شرح إضافي."""


STRICT_NUMBERS_NOTE = """
⚠️ تنبيه تصحيحي: نسختك السابقة أسقطت أو عدّلت هذه القيم الموجودة في المصدر: {missing}.
أعد كتابة الخبر مع الحفاظ على كل قيمة من القيم السابقة حرفياً كما وردت في المنشور الأصلي (بما فيها رمز العملة والنسبة إن وجد)."""

MIN_BODY_CHARS = 120


def build_prompt(source_name: str, text: str, max_body_chars: int) -> str:
    return PROMPT_TEMPLATE.format(
        source_name=source_name,
        text=text,
        min_body=MIN_BODY_CHARS,
        max_body=max_body_chars,
    )


def build_retry_prompt(base_prompt: str, missing: List[str]) -> str:
    return base_prompt + STRICT_NUMBERS_NOTE.format(missing=", ".join(missing))


# ---------------------------------------------------------------- العميل

class GeminiRewriter:
    """غلاف غير متزامن حول Gemini مع إعادة المحاولة وفحص الأرقام."""

    def __init__(self, api_key: str, settings: AISettings, max_body_chars: int = 900):
        self.settings = settings
        self.max_body_chars = max_body_chars
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=settings.timeout_seconds * 1000),
        )

    async def rewrite(
        self, source_name: str, text: str, extra_note: Optional[str] = None
    ) -> NewsDraft:
        """نداء واحد للنموذج مع إعادة المحاولة — يرفع RuntimeError عند استنفاد المحاولات."""
        prompt = build_prompt(source_name, text, self.max_body_chars)
        if extra_note:
            prompt += extra_note

        last_error: Optional[str] = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.settings.model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        temperature=self.settings.temperature,
                        max_output_tokens=self.settings.max_output_tokens,
                        response_mime_type="application/json",
                        response_schema=NewsDraft,
                    ),
                )
                draft = self._parse_response(response)
                if draft is None:
                    last_error = "استجابة فارغة أو محجوبة من النموذج"
                elif draft.is_news and (not (draft.body or "").strip() or not (draft.title or "").strip()):
                    last_error = "مخرجات ناقصة: العنوان أو النص فارغ رغم is_news=true"
                else:
                    return draft
            except Exception as exc:  # noqa: BLE001 — أي خطأ شبكة/SDK يستحق محاولة أخرى
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.settings.max_retries:
                delay = min(2 ** attempt + random.uniform(0, 1), 15)
                log.warning(
                    "محاولة AI رقم %s/%s فشلت (%s) — إعادة بعد %.1fs",
                    attempt, self.settings.max_retries, last_error, delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"فشل نداء الذكاء الاصطناعي بعد كل المحاولات: {last_error}")

    async def rewrite_with_number_check(self, source_name: str, text: str) -> tuple:
        """
        صياغة كاملة مع فحص سلامة الأرقام ومحاولة تصحيحية واحدة.
        يعيد (draft, missing_tokens_after_retry).
        """
        draft = await self.rewrite(source_name, text)
        missing = tokens_missing_in(text, draft.body or "")
        if not missing:
            return draft, []

        log.warning("سقطت أرقام من الصياغة الأولى: %s — محاولة تصحيحية", missing)
        base_prompt = build_prompt(source_name, text, self.max_body_chars)
        try:
            draft = await self._rewrite_with_note(base_prompt, missing)
            missing = tokens_missing_in(text, draft.body or "")
        except RuntimeError as exc:
            log.error("المحاولة التصحيحية فشلت أيضاً: %s", exc)
        return draft, missing

    async def _rewrite_with_note(self, base_prompt: str, missing: List[str]) -> NewsDraft:
        """نداء ببرومبت التصحيح مباشرة (نفس منطق إعادة المحاولة)."""
        prompt = build_retry_prompt(base_prompt, missing)
        last_error: Optional[str] = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.settings.model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        temperature=self.settings.temperature,
                        max_output_tokens=self.settings.max_output_tokens,
                        response_mime_type="application/json",
                        response_schema=NewsDraft,
                    ),
                )
                draft = self._parse_response(response)
                if draft is not None and draft.is_news and (draft.body or "").strip():
                    return draft
                last_error = "استجابة غير صالحة في المحاولة التصحيحية"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.settings.max_retries:
                await asyncio.sleep(min(2 ** attempt + random.uniform(0, 1), 15))
        raise RuntimeError(f"فشلت المحاولة التصحيحية: {last_error}")

    # ---------------------------------------------------------------- parsing

    @staticmethod
    def _parse_response(response) -> Optional[NewsDraft]:
        """قراءة الاستجابة: أولاً كـ Pydantic مباشرة، ثم JSON يدوياً كخطة بديلة."""
        try:
            parsed = getattr(response, "parsed", None)
            if parsed is not None:
                return parsed if isinstance(parsed, NewsDraft) else NewsDraft.model_validate(parsed)
        except Exception:  # noqa: BLE001 — نُكمل إلى التحليل اليدوي
            pass
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            return None
        # بعض النماذج تلتف بالـ ```json ... ```
        if text.startswith("```"):
            text = text.strip("`\n ")
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
            return NewsDraft.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("تعذر تحليل مخرجات JSON: %s | المقتطف: %.200s", exc, text)
            return None
