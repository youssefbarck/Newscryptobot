# -*- coding: utf-8 -*-
"""
نقطة التشغيل — تشغيلة واحدة (Run) على GitHub Actions أو محلياً:

1. تحميل الإعدادات والتحقق من الأسرار
2. الاتصال بحساب MTProto وحل القنوات
3. ضبط العلامات المائية عند أول تشغيل (بدون نشر أخبار قديمة)
4. إعادة محاولة الأخبار المعلقة/الفاشلة من التشغيلات السابقة
5. جلب الجديد فوق العلامة المائية → تسجيله في القاعدة → ترقية العلامة
6. معالجة كل عنصر (تصفية → تكرار → AI → نشر) مع سقف للنشر لكل تشغيلة
7. صيانة القاعدة + كتابة الملخص → خروج نظيف

الاستخدام:  python -m bot.main
"""
from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from telethon.errors import ChatWriteForbiddenError, UserBannedInChannelError

from bot.ai import GeminiRewriter
from bot.config import ConfigError, load_config, validate
from bot.db import Repository, create_engine, normalize_database_url
from bot.logging_setup import setup_logging
from bot.monitor import Monitor
from bot.normalizer import content_hash
from bot.pipeline import Counters, Pipeline
from bot.publisher import Publisher, RateLimiter
from bot.summary import write_run_summary
from bot.telegram_client import create_client, resolve_channel

log = logging.getLogger("main")

# أسماء Canonicals: معرف القناة الرقمي → (المرجع الأصلي، الكيان، الاسم الظاهر)
SourceMap = dict


def _database_label(db_url: str) -> str:
    if db_url.startswith("postgresql"):
        return "Postgres (Neon)"
    if db_url.startswith("sqlite"):
        return "SQLite"
    return db_url.split(":")[0]


async def run() -> int:
    settings, secrets = load_config()
    setup_logging()
    log.info("الأسرار: %s", secrets.masked_summary())

    try:
        validate(settings, secrets)
    except ConfigError as exc:
        log.error("خطأ إعدادات:\n%s", exc)
        return 2
    log.info(
        "الإعدادات: مصادر=%s | وجهة=%s | إعادة صياغة=%s | وسائط=%s | حد/تشغيلة=%s",
        settings.source_channels, settings.destination_channel,
        settings.processing.rewrite_enabled, settings.processing.media.enabled,
        settings.limits.max_posts_per_run,
    )

    # ---------- قاعدة البيانات ----------
    db_url = normalize_database_url(secrets.database_url, settings.data_dir)
    engine = create_engine(db_url)
    repo = Repository(engine)
    await repo.create_all()
    log.info("قاعدة البيانات جاهزة (%s)", _database_label(db_url))

    # ---------- اتصال Telegram ----------
    client = create_client(secrets)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        log.error(
            "جلسة TELEGRAM_SESSION غير صالحة أو منتهية.\n"
            "→ ولّد جلسة جديدة من جهازك:  python scripts/login.py\n"
            "→ ثم حدّث السر TELEGRAM_SESSION في GitHub Secrets."
        )
        return 2
    me = await client.get_me()
    log.info("متصل بحساب: %s (@%s)", getattr(me, "first_name", "?"), getattr(me, "username", "?"))

    # ---------- حل القنوات ----------
    sources: SourceMap = {}
    names: dict = {}
    for ref in settings.source_channels:
        if ref in settings.filters.ignore_channels:
            log.info("تخطي القناة المعطلة: %s", ref)
            continue
        try:
            entity = await resolve_channel(client, ref, settings.auto_join)
            channel_id = str(entity.id)
            sources[channel_id] = entity
            names[channel_id] = getattr(entity, "title", None) or ref
        except RuntimeError as exc:
            log.error("قناة مصدر متعطلة — %s", exc)
    if not sources:
        log.error("لا توجد قنوات مصدر صالحة — أصلح source_channels في settings.yaml.")
        await client.disconnect()
        return 2

    try:
        dest_entity = await resolve_channel(
            client, settings.destination_channel, auto_join=False
        )
    except RuntimeError as exc:
        log.error("قناة النشر — %s", exc)
        await client.disconnect()
        return 2
    log.info("قناة النشر: %s", getattr(dest_entity, "title", settings.destination_channel))

    counters = Counters()
    try:
        monitor = Monitor(client, repo, settings)

        # ---------- 1) العلامات المائية لأول تشغيل ----------
        await monitor.ensure_watermarks(sources)

        # ---------- 2) إعادة المحاولة من تشغيلات سابقة ----------
        retry_rows = await repo.fetch_retryable(
            max_retries=settings.retries.max_retries,
            max_age_hours=settings.retries.max_age_hours,
            batch_size=settings.retries.batch_size,
        )
        if retry_rows:
            log.info("إعادة معالجة %s خبراً من تشغيلات سابقة", len(retry_rows))

        rewriter = None
        if settings.processing.rewrite_enabled:
            rewriter = GeminiRewriter(
                api_key=secrets.gemini_api_key,
                settings=settings.ai,
                max_body_chars=settings.processing.max_body_chars,
            )

        with tempfile.TemporaryDirectory(prefix="newsbot_") as tmp:
            limiter = RateLimiter(
                per_minute=settings.limits.max_posts_per_minute,
                delay_seconds=settings.limits.post_delay_seconds,
            )
            publisher = Publisher(
                client=client, dest_entity=dest_entity,
                media_settings=settings.processing.media,
                rate_limiter=limiter, tmp_dir=Path(tmp),
            )
            pipeline = Pipeline(settings=settings, repo=repo,
                                rewriter=rewriter, publisher=publisher)

            for row in retry_rows:
                if counters.published >= settings.limits.max_posts_per_run:
                    log.info("بلوغ سقف النشر لهذه التشغيلة — البقية في الدورة القادمة")
                    break
                await pipeline.handle_retry_row(row)

            # ---------- 3) جلب الجديد وتسجيله قبل المعالجة ----------
            items = await monitor.fetch_new_items(sources, names)
            rows_by_key: dict = {}
            if items:
                record_rows = [
                    {
                        "source_channel_id": item.source_channel_id,
                        "source_message_id": item.max_message_id,
                        "source_name": item.source_name,
                        "raw_text": item.text,
                        "content_hash": content_hash(item.text),
                        "state": "pending",
                        "media_type": item.media_type,
                        "has_media": 1 if item.media_messages else 0,
                    }
                    for item in items
                ]
                new_ids = await repo.record_items(record_rows)
                rows = await repo.load_rows(new_ids)
                rows_by_key = {(r.source_channel_id, r.source_message_id): r for r in rows}
                counters.skipped_existing = len(items) - len(new_ids)
                if counters.skipped_existing:
                    log.info("تخطي %s عنصراً مسجلاً مسبقاً (من تشغيلة انهارت قبل اكتمالها)",
                             counters.skipped_existing)

            # ---------- 4) المعالجة والنشر ----------
            for item in items:
                if counters.published >= settings.limits.max_posts_per_run:
                    log.info("بلوغ سقف النشر لهذه التشغيلة — البقية تبقى pending للدورة القادمة")
                    break
                row = rows_by_key.get((item.source_channel_id, item.max_message_id))
                if row is None:
                    continue  # مسجل مسبقاً — سيلتقطه مسار إعادة المحاولة إن احتاج
                await pipeline.handle_item(row, item)

            # ---------- 5) صيانة ----------
            if settings.housekeeping.enabled:
                deleted = await repo.housekeeping(settings.housekeeping.retention_days)
                if any(deleted.values()):
                    log.info("صيانة: حذف %s", deleted)

        totals = await repo.counts_by_state()
        log.info("إجماليات القاعدة: %s", totals)

    except (ChatWriteForbiddenError, UserBannedInChannelError) as exc:
        log.error(
            "الحساب لا يستطيع النشر في قناة الوجهة (%s).\n"
            "→ أضف الحساب أدمن في القناة بصلاحية نشر الرسائل.", exc,
        )
        counters.failed += 1

    finally:
        await client.disconnect()
        await repo.dispose()

    write_run_summary(
        counters_dict=counters.as_dict(),
        published_titles=counters.published_titles,
        sources_count=len(sources),
        database_label=_database_label(db_url),
    )
    log.info(
        "انتهت التشغيلة: نُشر=%s، تجاهل=%s، فشل=%s",
        counters.published, counters.ignored, counters.failed,
    )
    return 0


def main() -> None:
    exit_code = asyncio.run(run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
