# -*- coding: utf-8 -*-
"""نقطة انطلاق بوت أخبار الكريبتو 🐋

التشغيل:
    python -m bot.main             ← جولة كاملة (إرسال فعلي)
    python -m bot.main --dry-run   ← طباعة الرسائل دون إرسال
    python -m bot.main --test      ← رسالة تجربة للتحقق من الإعداد
    python -m bot.main --doctor    ← فحص تشخيصي: التوكن والمحادثة والاتصال
"""
import argparse
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .analysis import prepare, similar
from .config import (
    DISPLAY_TZ,
    MAX_NEWS_PER_RUN,
    MIN_SCORE,
    SEND_DELAY_SECONDS,
    STATE_FILE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WHALE_ALERT_API_KEY,
)
from .formatter import batch_header, news_message, test_message, whale_message
from .sources import fetch_feeds, fetch_market_stats, fetch_whale_alert
from .state import already_seen, load_state, mark, save_state
from .telegram_sender import send_news, verify_credentials
from .translate import to_arabic

from .config import RSS_FEEDS  # noqa: E402  (تُستورد بعد الإعدادات عمدًا)

log = logging.getLogger("crypto-bot")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def _select_candidates(prepared: list[dict], min_score: int, limit: int) -> list[dict]:
    """فلترة الجودة + منع التكرار داخل الجولة الواحدة."""
    qualified = sorted(
        (p for p in prepared if p["score"] >= min_score),
        key=lambda x: (x["score"], x.get("published") is not None, x.get("published")),
        reverse=True,
    )
    selected: list[dict] = []
    for item in qualified:
        if any(similar(item["norm"], s["norm"]) for s in selected):
            continue  # نفس القصة من مصدر آخر
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def run(dry_run: bool = False, limit: int | None = None, min_score: int | None = None) -> int:
    limit = limit or MAX_NEWS_PER_RUN
    min_score = min_score or MIN_SCORE
    now_local = datetime.now(ZoneInfo(DISPLAY_TZ))

    # ------------------------------------------------------------ 1) الجلب
    log.info("🌐 جلب الأخبار من %s مصادر…", len(RSS_FEEDS))
    items = fetch_feeds(RSS_FEEDS)
    if WHALE_ALERT_API_KEY:
        items += fetch_whale_alert(WHALE_ALERT_API_KEY)
    log.info("📥 إجمالي الأخبار الخام: %s", len(items))
    if not items:
        log.error("لا توجد أخبار على الإطلاق — تحقق من الاتصال أو من المصادر")
        return 1

    market = fetch_market_stats()
    log.info("📊 أسعار السوق: %s", "تمت" if market else "غير متاحة")

    # ------------------------------------------------------- 2) التحليل
    prepared = [p for p in (prepare(i) for i in items) if p]
    if not prepared:
        log.info("لا خبر واحد يخص مجال اهتمامنا في هذه الجولة ✅")
        return 0

    # ------------------------------------- 3) فلترة الجودة + منع التكرار
    state = load_state(STATE_FILE)
    fresh = [p for p in prepared if not already_seen(p, state)]
    log.info("🆕 أخبار لم تُرسل من قبل: %s من أصل %s", len(fresh), len(prepared))

    selected = _select_candidates(fresh, min_score, limit)
    if not selected:
        log.info("🎯 لا أخبار جديدة تتجاوز فلتر الجودة (%s/10) في هذه الجولة", min_score)
        save_state(STATE_FILE, state)
        return 0
    log.info("🏆 المختار للنشر: %s خبر", len(selected))

    # -------------------------------------------------- 4) التعريب
    for item in selected:
        if item.get("whale_data"):
            item["ar_title"] = None  # يُبنى العنوان داخل whale_message
        else:
            item["ar_title"] = to_arabic(item["title"]) or item["title"]
            time.sleep(0.4)  # أدب مع خدمة الترجمة 🙏

    # -------------------------------------------------- 5) الإرسال
    # فحص تشخيصي مسبق — يكشف المشكلة بدقة قبل إرسال أي شيء
    ok, err = verify_credentials(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    if not ok:
        log.error(err)
        log.error("💡 شغّل الوضع التشخيصي: python -m bot.main --doctor")
        return 3

    header = batch_header(len(selected), now_local, market)
    if dry_run:
        print("\n" + "=" * 52)
        print("[وضع تجربة — هذه الرسائل لن تُرسل]")
        print("=" * 52)
        print(header.replace("<b>", "").replace("</b>", ""))
        for item in selected:
            msg = whale_message(item) if item.get("whale_data") else news_message(item, item["ar_title"])
            print("-" * 52)
            print(msg.replace("<b>", "").replace("</b>", ""))
        print("=" * 52)
        for item in selected:
            mark(item, state)
        save_state(STATE_FILE, state)
        return 0

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("❌ بيانات تيليجرام ناقصة! عيّن TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID")
        return 2

    ok = send_news(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, header)
    log.info("%s ترويسة الجولة", "✔ أُرسلت" if ok else "✖ فشلت")
    time.sleep(SEND_DELAY_SECONDS)

    sent = 0
    for item in selected:
        msg = whale_message(item) if item.get("whale_data") else news_message(item, item["ar_title"])
        if send_news(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg,
                     image_url=item.get("image"), source_url=item.get("url") or None):
            sent += 1
            mark(item, state)
        else:
            log.warning("✖ فشل إرسال خبر: %s…", item["title"][:50])
        time.sleep(SEND_DELAY_SECONDS)

    save_state(STATE_FILE, state)
    if sent == 0:
        log.error("❌ فشل إرسال كل الرسائل رغم أن الفحص التشخيصي نجح — راجع رسائل الأخطاء أعلاه")
        return 1
    log.info("🏁 انتهت الجولة: %s/%s خبرًا نُشرت بنجاح", sent, len(selected))
    return 0


def send_test(dry_run: bool = False) -> int:
    msg = test_message()
    if dry_run:
        print(msg.replace("<b>", "").replace("</b>", ""))
        return 0
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("❌ عيّن TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID أولًا")
        return 2
    ok = send_news(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
    log.info("%s رسالة التجربة", "✔ وصلت" if ok else "✖ فشلت")
    return 0 if ok else 1


def run_doctor(dry_run: bool = False) -> int:
    """فحص تشخيصي شامل يُطبع في سجل GitHub Actions أو محليًا."""
    log.info("🩺 الفحص التشخيصي للبوت…")

    # 1) متغيرات تيليجرام
    ok, err = verify_credentials(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    if not ok:
        log.error(err)
        return 3

    if dry_run:
        log.info("🩺 (وضع تجربة) الفحص انتهى بنجاح — كل شيء جاهز للإرسال ✅")
        return 0

    # 2) رسالة تجريبية صغيرة للتأكد من صلاحية النشر فعليًا
    ok = send_news(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                   "🩺 <b>فحص تشخيصي:</b> البوت قادر على النشر في هذه المحادثة ✅")
    if not ok:
        log.error("❌ الفحص نجح لكن النشر الفعلي رُفض — تأكد من صلاحية «نشر الرسائل» للبوت كمشرف")
        return 3
    log.info("🩺 الفحص اكتمل بنجاح — كل شيء جاهز ✅")
    return 0


def main(argv=None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="بوت أخبار الكريبتو 🐋")
    parser.add_argument("--dry-run", action="store_true", help="طباعة الرسائل دون إرسال")
    parser.add_argument("--test", action="store_true", help="إرسال رسالة تجربة فقط")
    parser.add_argument("--doctor", action="store_true", help="فحص تشخيصي للتوكن والمحادثة")
    parser.add_argument("--limit", type=int, default=None, help="أقصى عدد أخبار في هذه الجولة")
    parser.add_argument("--min-score", type=int, default=None, help="حد فلتر الجودة (1-10)")
    args = parser.parse_args(argv)

    try:
        if args.doctor:
            return run_doctor(dry_run=args.dry_run)
        if args.test:
            return send_test(dry_run=args.dry_run)
        return run(dry_run=args.dry_run, limit=args.limit, min_score=args.min_score)
    except KeyboardInterrupt:
        log.info("توقف يدوي")
        return 130


if __name__ == "__main__":
    sys.exit(main())
