"""
🐋 Whale News Bot v3 - المنسق الرئيسي
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
نقطة الدخول — يربط كل وحدات الـ Pipeline ببعض:

  RSS → تنظيف → استخراج حقائق → كشف تكرار → تصنيف → تقييم → صياغة → تنسيق → نشر
"""

import os, asyncio, time, json
from datetime import datetime
from typing import List, Optional, Dict

from config import (
    cfg, state, log, tz, load_sent_hashes, save_sent_hashes,
    load_settings, save_settings, is_channel_enabled,
)
from models import NewsItem, PipelineStats, NewsType, OutgoingMessage
from database import NewsDatabase, Analytics
from collector import fetch_all_news, close_session
from cleaner import clean_news_item
from fact_extractor import extract_facts
from deduplicator import check_duplicate, register_news, merge_sources, check_text_similarity, compute_text_fingerprint
from classifier import classify_news, score_news, should_reject
from rewriter import rewrite_news
from formatter import format_news
from publisher import MessageQueue, send_to_telegram


# خريطة أنواع الأخبار بالعربية (لرسائل المالك)
_NEWS_TYPE_AR = {
    "etf": "صناديق ETF", "hack": "اختراق", "listing": "إدراج",
    "partnership": "شراكة", "regulation": "تنظيم", "macro": "اقتصاد كلي",
    "on_chain": "أون-تشين", "technical_analysis": "تحليل فني",
    "funding": "تمويل", "stablecoin": "عملات مستقرة", "general": "أخبار عامة",
    "economic_data": "بيانات اقتصادية", "adoption": "اعتماد",
}


# ═══════════════════════════════════════════════════════════
# 🏗️ الـ Pipeline الرئيسي
# ═══════════════════════════════════════════════════════════

class NewsPipeline:
    """
    خط معالجة الأخبار — كل مرحلة مستقلة وقابلة للاستبدال.
    فلسفة النظام: "هل هذا الخبر يستحق النشر؟" بدلاً من "كيف أحسّنه؟"
    """

    def __init__(self):
        self.db = NewsDatabase(cfg.PERSISTENT_DIR)
        self.analytics = Analytics(cfg.PERSISTENT_DIR)
        self.message_queue = MessageQueue()
        self._running = False

    async def start(self):
        """تشغيل البوت"""
        log.info("🐋 Whale News Bot v3 — Starting...")
        log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # تحميل البيانات السابقة
        load_sent_hashes()
        load_settings()
        self.db.load()
        self.analytics.load()

        log.info(f"📊 Loaded: {len(state.sent_news_hashes)} sent hashes")
        log.info(f"📂 DB: {self.db.get_stats()}")
        log.info(f"📊 Analytics: {self.analytics.get_daily_summary()}")

        # فحص الإعدادات
        errors = []
        if not cfg.TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN not set")
        if not cfg.CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID not set")
        if errors:
            log.error(f"❌ Config errors: {'; '.join(errors)}")
            return

        # تشغيل queue المستهلك
        self._running = True
        await self.message_queue.start_consumer()

        log.info("✅ Bot is running!")

        if cfg.GITHUB_ACTIONS or cfg.RUN_MODE == "oneshot":
            # لمرة واحدة (GitHub Actions)
            await self._run_one_shot()
        else:
            # وضع Polling
            await self._run_loop()

    async def stop(self):
        """إيقاف البوت"""
        log.info("🛑 Stopping bot...")
        self._running = False
        await self.message_queue.stop()
        await close_session()
        self.db.save()
        self.analytics.save()
        save_sent_hashes()
        log.info("✅ Bot stopped")

    # ──────────────────────────────────────────────────────
    # وضع التشغيل المتواصل
    # ──────────────────────────────────────────────────────
    async def _run_loop(self):
        """حلقة التشغيل الرئيسية — كل 5 دقائق"""
        while self._running and not state.bot_shutdown:
            try:
                stats = await self._run_pipeline()
                log.info(f"📋 {stats.summary()}")
            except Exception as e:
                log.error(f"❌ Pipeline error: {e}", exc_info=True)

            # انتظار حتى الدورة التالية
            await asyncio.sleep(cfg.SCAN_INTERVAL)

        if state.bot_shutdown:
            log.info("⏸️ Bot shutdown requested")

    # ──────────────────────────────────────────────────────
    # لمرة واحدة (GitHub Actions)
    # ──────────────────────────────────────────────────────
    async def _run_one_shot(self):
        """تشغيل واحد — لـ GitHub Actions"""
        log.info("🏃 One-shot mode")
        stats = await self._run_pipeline()
        log.info(f"📋 {stats.summary()}")

        # انتظار حتى تُرسل كل الرسائل
        await asyncio.sleep(5)
        while self.message_queue._queue.qsize() > 0:
            await asyncio.sleep(2)

        # حفظ الحالة
        self.db.save()
        self.analytics.save()
        save_sent_hashes()

    # ──────────────────────────────────────────────────────
    # الـ Pipeline الكامل
    # ──────────────────────────────────────────────────────
    async def _run_pipeline(self) -> PipelineStats:
        """
        تنفيذ دورة كاملة لمعالجة الأخبار.
        كل مرحلة مسؤولة عن مهمة واحدة فقط.
        """
        stats = PipelineStats(
            cycle_id=f"{int(time.time())}",
            timestamp=time.time()
        )

        start_time = time.time()

        # ━━━ المرحلة 1: جمع الأخبار ━━━
        try:
            raw_items = await fetch_all_news()
            stats.collected = len(raw_items)
            log.info(f"📡 Collected {len(raw_items)} raw news items")
        except Exception as e:
            log.error(f"❌ Collection failed: {e}")
            return stats

        if not raw_items:
            log.info("📭 No news collected")
            return stats

        # ━━━ المرحلة 2: تنظيف النص ━━━
        cleaned_items = []
        for item in raw_items:
            try:
                cleaned = clean_news_item(item)
                cleaned_items.append(cleaned)
                stats.by_source[cleaned.source] = stats.by_source.get(cleaned.source, 0) + 1
            except Exception as e:
                log.warning(f"⚠️ Clean failed for '{item.title[:40]}': {e}")

        stats.cleaned = len(cleaned_items)
        log.info(f"🧹 Cleaned: {stats.collected} → {stats.cleaned}")

        # ━━━ المرحلة 3: استخراج الحقائق ━━━
        for item in cleaned_items:
            try:
                item.facts = extract_facts(
                    item.clean_summary or item.summary,
                    item.clean_title or item.title
                )
                if item.facts and (item.facts.main_entities or item.facts.coins):
                    stats.facts_extracted += 1
            except Exception as e:
                log.warning(f"⚠️ Fact extraction failed: {e}")

        log.info(f"🔍 Facts extracted from {stats.facts_extracted}/{stats.cleaned} items")

        # ━━━ المرحلة 4: فحص التكرار + دمج المصادر ━━━
        unique_items = []
        for item in cleaned_items:
            if check_duplicate(item, self.db):
                stats.deduplicated += 1
                continue
            # فحص hash المُرسلة سابقاً (title hash + fact hash)
            if item.hash in state.sent_news_hashes:
                stats.deduplicated += 1
                continue
            fact_hash = item.get_fact_hash()
            if fact_hash and fact_hash in state.sent_fact_hashes:
                stats.deduplicated += 1
                continue
            unique_items.append(item)

        # دمج المصادر المتعددة
        unique_items = merge_sources(unique_items)

        log.info(f"🔄 Dedup: removed {stats.deduplicated}, {len(unique_items)} unique remain")

        # ━━━ المرحلة 5: تصنيف + تقييم + فلترة ━━━
        scored_items = []
        for item in unique_items:
            # 5a. فحص الرفض المبكر
            rejected, reason = should_reject(item)
            if rejected:
                stats.rejected.append({
                    "title": item.title[:60],
                    "reason": reason,
                    "source": item.source,
                })
                self.analytics.record_rejected(reason)
                continue

            # 5b. تصنيف نوع الخبر
            try:
                item.news_type = classify_news(item)
                stats.by_type[item.news_type.value] = stats.by_type.get(item.news_type.value, 0) + 1
                stats.classified += 1
            except Exception as e:
                log.warning(f"⚠️ Classification failed: {e}")

            # 5c. تقييم الأهمية
            try:
                result = score_news(item)
                item.score = result.total
                item.score_breakdown = result.breakdown
                stats.scored += 1

                if not result.should_publish:
                    stats.rejected.append({
                        "title": item.title[:60],
                        "reason": f"درجة منخفضة: {result.total}/100 — {result.reason}",
                        "source": item.source,
                    })
                    self.analytics.record_rejected(f"low_score:{result.total}")
                    continue

                stats.scored_above_threshold += 1
                scored_items.append(item)
                log.info(
                    f"✅ {item.news_type.value}: {item.title[:50]}... "
                    f"[{result.total}/100] {result.reason}"
                )
            except Exception as e:
                log.warning(f"⚠️ Scoring failed: {e}")

        # ترتيب حسب الدرجة
        scored_items.sort(key=lambda x: -x.score)

        # حد أقصى للنشر
        to_publish = scored_items[:cfg.MAX_NEWS_PER_SCAN]

        # حد أقصى: خبران فقط لكل عملة في الدورة الواحدة
        _MAX_PER_COIN = 2
        coin_count: Dict[str, int] = {}
        # حد أقصى: خبر واحد فقط لكل كيان بشرية (شخص) في الدورة الواحدة
        _MAX_PER_PERSON = 1
        person_count: Dict[str, int] = {}
        filtered = []
        for item in to_publish:
            # فحص حد الكيانات البشرية أولاً (الأولوية)
            people = item.facts.people if item.facts else []
            dominant_person = ""
            if people:
                # تطبيع الاسم للمقارنة
                dominant_person = people[0].strip().lower()
                if person_count.get(dominant_person, 0) >= _MAX_PER_PERSON:
                    log.info(f"⏭️ تخطي: حد الأشخاص ({people[0]}): {item.title[:50]}")
                    stats.rejected.append({
                        "title": item.title[:60],
                        "reason": f"حد الأشخاص: {people[0]} ({person_count[dominant_person]}/{_MAX_PER_PERSON})",
                        "source": item.source,
                    })
                    continue

            # فحص حد العملات
            coins = item.facts.coins if item.facts else []
            # إذا لم تكن هناك عملات محددة → نسمح بها
            if not coins:
                filtered.append(item)
                if dominant_person:
                    person_count[dominant_person] = person_count.get(dominant_person, 0) + 1
                continue
            # إضافة خبر فقط إذا لم نتجاوز الحد
            dominant_coin = coins[0] if coins else ""
            if coin_count.get(dominant_coin, 0) < _MAX_PER_COIN:
                filtered.append(item)
                coin_count[dominant_coin] = coin_count.get(dominant_coin, 0) + 1
                if dominant_person:
                    person_count[dominant_person] = person_count.get(dominant_person, 0) + 1
            else:
                log.debug(f"⏭️ تخطي: حد العملات ({dominant_coin}): {item.title[:50]}")
                stats.rejected.append({
                    "title": item.title[:60],
                    "reason": f"حد العملات: {dominant_coin} ({coin_count[dominant_coin]}/{_MAX_PER_COIN})",
                    "source": item.source,
                })
        to_publish = filtered

        log.info(f"📊 Scored: {stats.scored_above_threshold}/{stats.scored} above threshold, publishing {len(to_publish)}")

        # ━━━ المرحلة 6: إعادة الصياغة بالعربية ━━━
        for item in to_publish:
            # تخطي إذا كانت عربية أصلاً
            if item.lang == "ar" and len(item.title) > 20:
                item.title_ar = item.clean_title or item.title
                item.summary_ar = item.clean_summary or item.summary
                stats.rewritten += 1
                continue

            try:
                item = await rewrite_news(item)
                if item.title_ar and len(item.title_ar) >= 10:
                    stats.rewritten += 1
                else:
                    log.warning(f"⚠️ Rewrite too short: {item.title[:40]}")
                    stats.failed += 1
            except Exception as e:
                log.error(f"❌ Rewrite failed: {item.title[:40]} — {e}")
                stats.failed += 1

        log.info(f"✍️ Rewritten: {stats.rewritten}/{len(to_publish)}")

        # ━━━ المرحلة 6.5: فحص التكرار النصي بعد الترجمة ━━━
        # كشف أخبار نفس الحدث من مصادر مختلفة بصياغات عربية متعددة
        _batch_fps = []
        _deduped_items = []
        for item in to_publish:
            if not item.title_ar:
                _deduped_items.append(item)
                continue
            ar_text = f"{item.title_ar} {item.summary_ar or ''}"
            fp = compute_text_fingerprint(ar_text)
            if not fp:
                _deduped_items.append(item)
                continue
            # فحص ضد منشورات سابقة + نفس الدورة
            all_fps = state.sent_text_fingerprints + _batch_fps
            if check_text_similarity(ar_text, all_fps, threshold=0.50):
                log.info(f"🔄 تكرار نصي بعد الترجمة: {item.title_ar[:50]}")
                stats.deduplicated += 1
                continue
            _batch_fps.append(fp)
            _deduped_items.append(item)
        to_publish = _deduped_items
        log.info(f"🔄 Post-rewrite dedup: {len(to_publish)} remain after text similarity check")

        # ━━━ المرحلة 7: تنسيق النشر ━━━
        for item in to_publish:
            if not item.title_ar:
                continue

            try:
                msg = format_news(item)
                if msg:
                    stats.formatted += 1

                    # تسجيل في hash المُرسلة (title + fact)
                    state.sent_news_hashes.add(item.hash)
                    fact_h = item.get_fact_hash()
                    if fact_h:
                        state.sent_fact_hashes.add(fact_h)
                    register_news(item, self.db)

                    # تسجيل بصمة نصية عربية لكشف التكرار مستقبلاً
                    ar_fp = compute_text_fingerprint(f"{item.title_ar} {item.summary_ar or ''}")
                    if ar_fp:
                        state.sent_text_fingerprints.append(ar_fp)

                    # إرسال للقناة
                    if is_channel_enabled():
                        channel_msg = OutgoingMessage(
                            text=msg.text,
                            image_url=msg.image_url,
                            chat_id=cfg.CHANNEL_ID,
                            priority=msg.priority,
                        )
                        await self.message_queue.put(channel_msg)

                    # إرسال نسخة للمالك (بدون معلومات التقييم)
                    if cfg.CHAT_ID:
                        owner_msg = OutgoingMessage(
                            text=msg.text,
                            image_url=msg.image_url,
                            chat_id=cfg.CHAT_ID,
                            priority=msg.priority,
                        )
                        await self.message_queue.put(owner_msg)

                    self.analytics.record_published(item.source, item.news_type.value, item.score)
                    stats.published += 1
            except Exception as e:
                log.error(f"❌ Format failed: {item.title[:40]} — {e}")
                stats.failed += 1

        # حفظ الحالة
        save_sent_hashes()

        elapsed = time.time() - start_time
        log.info(
            f"⚡ Pipeline completed in {elapsed:.1f}s — "
            f"Published: {stats.published}, Failed: {stats.failed}"
        )

        return stats

    # ──────────────────────────────────────────────────────
    # ملخص يومي
    # ──────────────────────────────────────────────────────
    async def _daily_summary(self):
        """إرسال ملخص يومي في الساعة 23:59"""
        now = datetime.now(tz)
        if now.hour != cfg.SUMMARY_HOUR or now.minute != cfg.SUMMARY_MINUTE:
            return

        summary = self.analytics.get_daily_summary()
        db_stats = self.db.get_stats()

        text = (
            f"📊 🐋 ملخص يومي — Whale News Bot v3\n\n"
            f"📨 جمع: {summary['collected']}\n"
            f"✅ نُشر: {summary['published']}\n"
            f"❌ رُفض: {summary['rejected']}\n"
            f"📈 نسبة النشر: {summary['publish_rate']:.1f}%\n"
            f"📂 قاعدة البيانات: {db_stats['total']} خبر ({db_stats['published']} منشور)\n\n"
        )

        # أفضل المصادر
        if summary['by_source']:
            top_sources = sorted(summary['by_source'].items(), key=lambda x: -x[1])[:5]
            text += "🏆 أفضل المصادر:\n"
            for source, count in top_sources:
                text += f"  • {source}: {count}\n"

        # أفضل الأنواع
        if summary['by_type']:
            text += "\n📋 حسب النوع:\n"
            for ntype, count in sorted(summary['by_type'].items(), key=lambda x: -x[1])[:5]:
                text += f"  • {ntype}: {count}\n"

        text += f"\n@{cfg.CHANNEL_NAME}"

        await send_to_telegram(text, cfg.CHAT_ID)
        if cfg.CHAT_ID:
            log.info("Daily summary sent")


# ═══════════════════════════════════════════════════════════
# 🚀 نقطة الدخول
# ═══════════════════════════════════════════════════════════

async def main():
    """نقطة الدخول الرئيسية"""
    pipeline = NewsPipeline()

    try:
        await pipeline.start()
    except KeyboardInterrupt:
        log.info("🛑 Interrupted by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await pipeline.stop()


def run_bot():
    """دالة التشغيل — تُستدعى من entry point"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Interrupted")


def run_oneshot():
    """دالة التشغيل لمرة واحدة — GitHub Actions"""
    cfg.GITHUB_ACTIONS = True
    cfg.RUN_MODE = "oneshot"
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Interrupted")


if __name__ == "__main__":
    run_bot()
