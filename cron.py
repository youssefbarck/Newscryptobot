"""
⏰ Whale News Bot — Vercel Cron Job
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
يُشغّل كل 5 دقائق عبر Vercel Cron.
يجلب الأخبار → يترجمها → يرسلها مباشرة للقناة.
"""

import json
import asyncio
import sys
import os
import time

# إضافة المسار الجذري للمشروع
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from flask import Flask, request, jsonify

from config import config, state, log, load_sent_news, save_sent_news, sent_news_hashes, MAX_NEWS_PER_SCAN, MAX_NEWS_AGE
from rss import fetch_all_news, fetch_etf_flows, session_manager
from filters import filter_news_items
from translate import TranslationManager
from telegram_bot import format_news_item, clean_message, send_to_channel, _is_similar, _record_title

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def cron_handler():
    """تشغيل فحص الأخبار — يُستدعى بواسطة Vercel Cron كل 5 دقائق"""
    try:
        # التحقق من Vercel Cron Authorization header
        auth_header = request.headers.get('Authorization', '')
        cron_secret = os.environ.get('CRON_SECRET', '')
        if cron_secret and auth_header != f'Bearer {cron_secret}':
            return jsonify({'error': 'Unauthorized'}), 401

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run_scan())
        finally:
            loop.close()

        return jsonify({'ok': True, 'result': result}), 200

    except Exception as e:
        log.error(f"Cron error: {e}")
        return jsonify({'ok': True, 'error': str(e)}), 200


@app.route('/', methods=['GET'])
def health():
    """فحص صحة"""
    return jsonify({'status': 'ok', 'mode': 'cron'}), 200


async def _run_scan():
    """تشغيل دورة فحص واحدة — إرسال مباشر بدون أزرار مراجعة"""
    start_time = time.time()

    # تحميل الأخبار المُرسلة سابقاً
    load_sent_news()
    state.sent_news_hashes = sent_news_hashes

    # التحقق من حالة البوت
    if state.bot_shutdown or not state.auto_alerts_enabled:
        log.info("⏸️ Bot paused, skipping scan")
        return {'status': 'paused'}

    log.info("🔍 Cron scan started...")

    # جلب الأخبار
    news = await fetch_all_news(max_concurrent=5)
    if not news:
        return {'status': 'no_news', 'fetched': 0}

    # فلترة
    filtered = filter_news_items(news)

    # إعداد المترجم
    translator = TranslationManager(config)

    now = time.time()
    alerts_sent = 0
    errors = []

    for item in filtered[:MAX_NEWS_PER_SCAN]:
        try:
            # فحص العمر
            if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
                sent_news_hashes.add(item.hash)
                continue

            # فحص الإرسال السابق
            if item.hash in sent_news_hashes:
                continue

            # ترجمة
            await translator.translate_item(item)
            if not item.title_ar:
                log.debug(f"  ⏭️ No translation: {item.title[:60]}")
                continue

            # تنسيق
            msg = format_news_item(item)
            if not msg:
                log.debug(f"  ⏭️ No format: {item.title_ar[:60]}")
                continue

            # تنظيف
            msg = clean_message(msg)
            if not msg:
                log.info(f"  🧹 Cleaned out: {item.title[:60]}")
                continue

            # منع التكرار بعد الترجمة
            import hashlib
            title_ar_hash = hashlib.md5(item.title_ar.encode()).hexdigest()[:12]
            if title_ar_hash in sent_news_hashes:
                log.info(f"🧹 Duplicate after translation: {item.title[:60]}")
                continue

            # فحص التشابه
            if _is_similar(item.title_ar):
                log.info(f"🧹 Similar to recent (cron): {item.title_ar[:60]}")
                sent_news_hashes.add(item.hash)
                sent_news_hashes.add(title_ar_hash)
                _record_title(item.title_ar)
                continue

            # تسجيل كمرسّل
            sent_news_hashes.add(item.hash)
            sent_news_hashes.add(title_ar_hash)
            _record_title(item.title_ar)

            # إرسال مباشر للقناة
            if state.is_channel_enabled(config):
                await send_to_channel(msg, item.image)
                alerts_sent += 1
                log.info(f"  ✅ Sent to channel: {item.title[:60]}")

        except Exception as e:
            errors.append(str(e))
            log.warning(f"Error processing item: {e}")

    # بيانات ETF
    try:
        etf = await fetch_etf_flows()
        if etf:
            from telegram_bot import format_etf_flows
            etf_hash = f"etf_{etf['date']}"
            if etf_hash not in sent_news_hashes:
                sent_news_hashes.add(etf_hash)
                etf_msg = format_etf_flows(etf)
                if state.is_channel_enabled(config):
                    await send_to_channel(etf_msg)
                log.info(f"📊 ETF flows sent")
    except Exception as e:
        log.warning(f"ETF flows error: {e}")

    # حفظ الهاشات — دائماً وليس فقط عند الإرسال
    save_sent_news()

    # تنظيف الجلسة
    try:
        await session_manager.close()
    except Exception:
        pass

    elapsed = time.time() - start_time
    result = {
        'status': 'completed',
        'fetched': len(news),
        'filtered': len(filtered),
        'sent': alerts_sent,
        'elapsed': round(elapsed, 2),
    }
    if errors:
        result['errors'] = errors[:3]

    log.info(f"📊 Scan result: {result}")
    return result


if __name__ == '__main__':
    app.run(debug=True)
