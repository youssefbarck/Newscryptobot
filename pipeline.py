# -*- coding: utf-8 -*-
"""
خط المعالجة الكامل لكل عنصر خبري:

تسجيل → تصفية مسبقة → منع التكرار (Hash ثم تشابه) → ذكاء اصطناعي (فهم وإعادة صياغة)
→ فحص سلامة الأرقام → التحقق من التشابه النهائي → بناء المنشور → النشر → تحديث الحالة.

حالة كل خطوة تُحفظ في القاعدة فوراً: أي انهيار لا يضيع خبراً ولا يعيد نشراً.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

from bot.ai import GeminiRewriter
from bot.config import Settings
from bot.db import ProcessedMessage, Repository
from bot.dedup import find_similar
from bot.monitor import NewsItem
from bot.normalizer import content_hash, normalize_text
from bot.publisher import Publisher

log = logging.getLogger("pipeline")


class IgnoreItem(Exception):
    """استثناء تحكم: تجاهل العنصر مع سبب واضح."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Counters:
    published: int = 0
    ignored: int = 0
    failed: int = 0
    skipped_existing: int = 0
    retried: int = 0
    published_titles: list = field(default_factory=list)

    def as_dict(self) -> Dict[str, int]:
        return {
            "published": self.published,
            "ignored": self.ignored,
            "failed": self.failed,
            "skipped_existing": self.skipped_existing,
            "retried": self.retried,
        }


_SENTENCE_END = re.compile(r"[.!؟?\n]")


def clip_body(body: str, max_chars: int) -> str:
    """قص النص عند حد الأحرف على حدود الجملة إن أمكن."""
    body = (body or "").strip()
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    matches = list(_SENTENCE_END.finditer(cut))
    if matches and len(matches[-1].group()) and matches[-1].end() > max_chars * 0.6:
        return cut[: matches[-1].end()].strip()
    return cut.rsplit(" ", 1)[0].strip() + "…"


def build_post_text(template: str, title: str, body: str, source_name: str, ticker: Optional[str]) -> str:
    """تجميع المنشور النهائي — القيم تُهرَّب HTML قبل إدخالها في القالب."""
    ticker_line = f"💠 <b>{html.escape(ticker)}</b>\n" if ticker else ""
    text = template.format(
        title=html.escape((title or "").strip()),
        body=html.escape(clip_body(body, 4096 - 300)),
        source=html.escape(source_name),
        ticker_line=ticker_line,
    )
    return text.strip()


class Pipeline:
    def __init__(self, settings: Settings, repo: Repository, rewriter: Optional[GeminiRewriter],
                 publisher: Publisher):
        self.settings = settings
        self.repo = repo
        self.rewriter = rewriter
        self.publisher = publisher
        self.counters = Counters()

    # ------------------------------------------------------------------ جديد

    async def handle_item(self, row: ProcessedMessage, item: NewsItem) -> str:
        """معالجة عنصر جديد مرتبط بصف pending. يعيد الحالة النهائية."""
        row_id = row.id
        text = item.text
        try:
            self._prefilters(text, item)
            await self._dedup_by_raw(text, row.source_channel_id)
            title, body, ticker = await self._produce_content(text, item)
            final_text = build_post_text(
                self.settings.post_template, title, body, item.source_name, ticker
            )
            await self._dedup_by_final(final_text)

            dest_id = await self.publisher.publish(item, final_text)
            await self.repo.mark_state(
                row_id, "published",
                title=title, final_text=final_text, ticker=ticker,
                retry_count=row.retry_count,
            )
            await self.repo.add_published(
                content_hash=row.content_hash,
                normalized_raw=normalize_text(text),
                normalized_final=normalize_text(final_text),
                title=title,
                source_channel_id=row.source_channel_id,
                dest_message_id=dest_id,
            )
            self.counters.published += 1
            self.counters.published_titles.append(title)
            log.info("✅ نُشر: %s (من #%s)", title[:60], item.max_message_id)
            return "published"

        except IgnoreItem as exc:
            await self.repo.mark_state(row_id, "ignored", ignore_reason=exc.reason)
            self.counters.ignored += 1
            log.info("🚫 تجاهل #%s: %s", item.max_message_id, exc.reason)
            return "ignored"

        except Exception as exc:  # noqa: BLE001 — أي فشل يُسجّل ويُعاد لاحقاً
            error = f"{type(exc).__name__}: {exc}"
            await self.repo.mark_state(
                row_id, "failed", error=error[:900], retry_count=row.retry_count + 1
            )
            self.counters.failed += 1
            log.error("❌ فشل معالجة #%s: %s", item.max_message_id, error)
            return "failed"

    # ------------------------------------------------------------------ إعادة

    async def handle_retry_row(self, row: ProcessedMessage) -> str:
        """
        إعادة معالجة صف pending/failed من بياناته المحفوظة.
        ملاحظة: الوسائط غير متاحة في الإعادة → نشر نصي فقط (موثق في README).
        """
        item = NewsItem(
            source_channel_id=row.source_channel_id,
            source_name=row.source_channel_id,  # الاسم الأصلي غير محفوظ — يُستخدم المعرف
            message_ids=[row.source_message_id],
            text=row.raw_text or "",
            media_type="none",
            media_messages=[],
        )
        self.counters.retried += 1
        if row.has_media:
            log.info("إعادة #%s: النشر سيكون نصياً فقط (وسائط غير قابلة لإعادة التنزيل)", row.id)
        return await self.handle_item(row, item)

    # ------------------------------------------------------------------ مراحل

    def _prefilters(self, text: str, item: NewsItem) -> None:
        """فلاتر رخيصة قبل أي نداء AI."""
        if self.settings.processing.media.include_media_only_posts is False \
                and not text.strip() and item.media_type != "none":
            raise IgnoreItem("media_only: منشور وسائط بدون نص")
        if len(text.strip()) < self.settings.processing.min_post_length:
            raise IgnoreItem(f"too_short: {len(text.strip())} حرف (< {self.settings.processing.min_post_length})")
        if len(text.strip()) > self.settings.processing.max_post_length:
            raise IgnoreItem(f"too_long: {len(text.strip())} حرف (> {self.settings.processing.max_post_length})")
        lowered = normalize_text(text)
        for keyword in self.settings.filters.ignore_keywords:
            if normalize_text(keyword) and normalize_text(keyword) in lowered:
                raise IgnoreItem(f"keyword: {keyword}")

    async def _dedup_by_raw(self, text: str, channel_id: str) -> None:
        """منع التكرار قبل النداء المكلف على AI."""
        digest = content_hash(text)
        exact_id = await self.repo.find_published_by_hash(digest)
        if exact_id is not None:
            raise IgnoreItem(f"duplicate_exact: مطابق للخبر المنشور #{exact_id}")
        recent = await self.repo.recent_published(self.settings.dedup.window_hours)
        match = find_similar(
            normalize_text(text), "", recent, self.settings.dedup.similarity_threshold
        )
        if match:
            raise IgnoreItem(f"similar: يشبه الخبر المنشور #{match[0]} (درجة {match[1]:.0f})")

    async def _dedup_by_final(self, final_text: str) -> None:
        """منع التكرار بعد الصياغة: نفس الخبر من مصدرين مختلفين بصياغتين متقاربتين."""
        recent = await self.repo.recent_published(self.settings.dedup.window_hours)
        match = find_similar(
            "", normalize_text(final_text), recent, self.settings.dedup.similarity_threshold
        )
        if match:
            raise IgnoreItem(f"similar_final: يشبه المنشور #{match[0]} بعد الصياغة (درجة {match[1]:.0f})")

    async def _produce_content(self, text: str, item: NewsItem):
        """إنتاج (العنوان، النص، التكرام) — إما عبر AI أو تنظيف مباشر."""
        if not self.settings.processing.rewrite_enabled or self.rewriter is None:
            first_line = text.strip().splitlines()[0][:80]
            return first_line, text.strip(), None

        draft, missing = await self.rewriter.rewrite_with_number_check(item.source_name, text)

        if not draft.is_news:
            raise IgnoreItem(f"ai_not_news: {draft.reason or 'ليس خبراً'}")
        if missing and self.settings.processing.strict_numbers:
            raise IgnoreItem(f"numbers_missing: سقطت القيم {missing} بعد إعادة المحاولة")
        if missing:
            log.warning("نُشر رغم سقوط الأرقام %s — فعّل strict_numbers للرفض الكامل", missing)

        title = (draft.title or "").strip()
        body = (draft.body or "").strip()
        if not title or not body:
            # لا يفترض الوصول إلى هنا (المدقق يرفض في ai.rewrite) — حماية إضافية
            raise IgnoreItem("ai_empty: مخرجات الذكاء الاصطناعي فارغة")

        ticker = self._confirm_ticker(draft.ticker, text)
        return title, body, ticker

    @staticmethod
    def _confirm_ticker(ticker: Optional[str], source_text: str) -> Optional[str]:
        """التحقق النهائي من الـ Ticker: يُقبل فقط إذا ورد حرفياً في نص المصدر."""
        if not ticker:
            return None
        clean = ticker.strip().lstrip("$").upper()
        if 1 <= len(clean) <= 12 and clean in source_text.upper():
            return clean
        log.warning("تجاهل Ticker غير المؤكد: %s", ticker)
        return None
