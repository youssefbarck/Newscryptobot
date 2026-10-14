# -*- coding: utf-8 -*-
"""🚀 الدورة الرئيسية للبوت: جلب ← ترشيح ← ترجمة ← صور ← إرسال.

ترتيب مرتفع الجودة: كل منشور يمر بأكثر من 8 بوابات قبل وصوله لقناتك.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from config import (
    DISPLAY_TZ,
    MAX_NEWS_AGE_HOURS,
    MAX_POSTS_PER_RUN,
    MIN_SCORE,
    SEND_DELAY_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from categories import categorize
from dedup import item_hashes, is_duplicate, load_hashes, mark, save_hashes
from formatter import batch_header, doctor_message, format_post, test_message, whale_post
from images import resolve_photo
from quality import (extract_facts, is_banned_title, is_banned_title_ar,
                     normalize_title, score_news, validate_post)
from sources import fetch_all_news, fetch_market_stats
from telegram_client import check_config, send_post, verify_credentials
from translator import google_translate

log = logging.getLogger("NewsBot")


def _prepare(item) -> bool:
    """تجهيز الخبر: بصمات + تصنيف + نقاط + أرقام. False = يُهمل."""
    if item.whale_data:
        # أخبار Whale Alert جاهزة التصنيف — أهمية عالية مضمونة
        item.category = "whale"
        item.score = 9
        wd = item.whale_data
        from categories import COIN_AR
        from quality import human_usd
        item.facts = [
            f"🪙 الكمية: {wd['amount']:,.0f} {COIN_AR.get(wd['symbol'], wd['symbol'])}",
            f"💰 القيمة: ≈ {human_usd(wd['amount_usd'])}",
            f"🔄 المسار: من {wd['from_txt']} إلى {wd['to_txt']}",
        ]
    else:
        item.category = categorize(item.title, item.summary) or ""
        if not item.category:
            return False  # خبر خارج اهتماماتنا
        item.score = score_news(item, item.category)
        item.facts = extract_facts(item.title)
    item.norm = normalize_title(item.title)
    item.hashes = item_hashes(item)
    return bool(item.norm)


def _select_candidates(candidates: list, limit: int) -> list:
    """ترتيب بالأهمية + منع التشابه داخل الجولة الواحدة."""
    candidates.sort(key=lambda x: (-x.score, -x.timestamp))
    selected, norms = [], []
    for item in candidates:
        if any(_norms_similar(item.norm, n) for n in norms):
            continue  # نفس القصة من مصدر آخر
        selected.append(item)
        norms.append(item.norm)
        if len(selected) >= limit:
            break
    return selected


def _norms_similar(a: str, b: str) -> bool:
    from quality import similar
    return similar(a, b)


async def run_cycle(dry_run: bool = False, limit: int | None = None,
                    min_score: int | None = None) -> int:
    """دورة واحدة كاملة — تُرجع كود الخروج: 0 نجاح، 1 فشل الإرسال، 2 إعداد ناقص."""
    limit = limit or MAX_POSTS_PER_RUN
    min_score = min_score or MIN_SCORE
    log.info("=" * 56)
    log.info("🚀 بدأت الجولة")

    state = load_hashes()

    # ---------------------------------------------------------- 1) الجلب
    try:
        news = await fetch_all_news()
    except Exception as exc:
        log.error("❌ فشل الجلب: %s", exc)
        return 1
    if not news:
        log.info("ℹ️ لا أخبار في هذه الجولة — ليس خطأ")
        save_hashes(state)
        return 0

    # ----------------------------------------------------- 2) فلتر العمر
    now = datetime.now(ZoneInfo("UTC")).timestamp()
    max_age = MAX_NEWS_AGE_HOURS * 3600
    fresh = [n for n in news if n.timestamp == 0 or (now - n.timestamp) <= max_age]
    log.info("📅 فلتر العمر: %s طازة من أصل %s", len(fresh), len(news))

    # ------------------------------------- 3) التحضير + الفلاتر الصارمة
    candidates = []
    for item in fresh:
        if not _prepare(item):
            continue
        if item.score < min_score:
            continue
        if not item.whale_data and is_banned_title(item.title):
            log.info("🚫 عنوان ممنوع: %s", item.title[:60])
            continue
        candidates.append(item)
    log.info("🔥 المرشحون بعد الفلاتر: %s", len(candidates))

    selected = _select_candidates(candidates, limit)
    if not selected:
        log.info("🎯 لا أخبار جديدة قوية (≥%s/10) في هذه الجولة", min_score)
        save_hashes(state)
        return 0
    log.info("🏆 المختار للنشر: %s خبر", len(selected))

    # -------------------------------------------------- 4) التعريب
    async with aiohttp.ClientSession() as session:
        for item in selected:
            if item.whale_data:
                item.title_ar = ""  # العنوان يُبنى داخل whale_post
                continue
            ar = await google_translate(item.title)
            if not ar:
                log.warning("🌐 تعذر تعريب خبر — يُستبدل بمرشح آخر: %s", item.title[:50])
                item.title_ar = ""
                continue
            ar = ar.strip()
            if is_banned_title_ar(ar):
                log.info("🚫 عنوان ممنوع بعد التعريب: %s", ar[:60])
                item.title_ar = ""
                continue
            from quality import clean_title_ar
            item.title_ar = clean_title_ar(ar)
            await asyncio.sleep(0.3)

        # ------------------------------------------------ 5) بناء المنشورات
        posts = []  # (item, text)
        for item in selected:
            if not item.whale_data and not item.title_ar:
                continue
            text = whale_post(item) if item.whale_data else format_post(item)
            if not text or not validate_post(text):
                log.warning("📝 منشور غير صالح — مُهمل: %s",
                            (item.title_ar or item.title)[:60])
                continue
            posts.append((item, text))

        if not posts:
            log.info("🎯 لا منشورات صالحة في هذه الجولة")
            save_hashes(state)
            return 0

        # ------------------------------------------- 6) جلب الصور (قبل الإرسال)
        photos = []
        for item, _text in posts:
            photos.append(await resolve_photo(session, item))
            await asyncio.sleep(0.2)

        # --------------------------------------------------- 7) وضع التجربة
        now_local = datetime.now(ZoneInfo(DISPLAY_TZ))
        header = batch_header(len(posts), now_local, None)
        if dry_run:
            print("\n" + "=" * 52)
            print("[وضع تجربة — هذه الرسائل لن تُرسل]")
            print("=" * 52)
            print(header.replace("<b>", "").replace("</b>", ""))
            for (item, text), photo in zip(posts, photos):
                note = "🖼 صورة مرفوعة كمرفق" if photo else "🖼 نص فقط (لا صورة متاحة)"
                print("-" * 52)
                print(f"[{note}]")
                print(text.replace("<b>", "").replace("</b>", ""))
            print("=" * 52)
            for item, _t in posts:
                mark(item, state)
            save_hashes(state)
            return 0

        # ------------------------------------------------------ 8) الإرسال
        ok, err = check_config()
        if not ok:
            log.error(err)
            return 2
        ok, err = verify_credentials(session)
        if not ok:
            log.error(err)
            log.error("💡 شغّل الوضع التشخيصي: python main.py --doctor")
            return 3

        # ترويسة الجولة مع أسعار السوق
        market = await fetch_market_stats()
        header = batch_header(len(posts), now_local, market)
        header_ok = await send_post(session, header)
        log.info("%s ترويسة الجولة", "✔ أُرسلت" if header_ok else "✖ فشلت")
        await asyncio.sleep(SEND_DELAY_SECONDS)

        sent = 0
        for (item, text), photo in zip(posts, photos):
            if await send_post(session, text, photo):
                sent += 1
                mark(item, state)
                log.info("✅ [%s/%s] %s", sent, len(posts),
                         (item.title_ar or item.title)[:60])
            else:
                log.warning("✖ فشل إرسال: %s…", (item.title_ar or item.title)[:50])
            await asyncio.sleep(SEND_DELAY_SECONDS)

        save_hashes(state)
        if sent == 0:
            log.error("❌ فشل إرسال كل الرسائل رغم نجاح الفحص — راجع الأخطاء أعلاه")
            return 1
        log.info("🏁 انتهت الجولة: %s/%s نُشرت بنجاح", sent, len(posts))
        return 0


async def send_test(dry_run: bool = False) -> int:
    """رسالة تجربة قصيرة للتأكد من الإعداد."""
    msg = test_message()
    if dry_run:
        print(msg.replace("<b>", "").replace("</b>", ""))
        return 0
    ok, err = check_config()
    if not ok:
        log.error(err)
        return 2
    async with aiohttp.ClientSession() as session:
        ok, err = verify_credentials(session)
        if not ok:
            log.error(err)
            return 3
        sent = await send_post(session, msg)
    log.info("%s رسالة التجربة", "✔ وصلت" if sent else "✖ فشلت")
    return 0 if sent else 1


async def run_doctor(dry_run: bool = False) -> int:
    """🩺 فحص تشخيصي شامل — يكشف المشكلة بدقة ويرسل رسالة اختبار."""
    log.info("🩺 الفحص التشخيصي للبوت…")
    ok, err = check_config()
    if not ok:
        log.error(err)
        return 2
    async with aiohttp.ClientSession() as session:
        ok, err = verify_credentials(session)
        if not ok:
            log.error(err)
            return 3
        if dry_run:
            log.info("🩺 (وضع تجربة) الفحص انتهى بنجاح — كل شيء جاهز ✅")
            return 0
        sent = await send_post(session, doctor_message())
    if not sent:
        log.error("❌ الفحص نجح لكن النشر الفعلي رُفض — تأكد من صلاحية «نشر الرسائل» للبوت كمشرف")
        return 3
    log.info("🩺 الفحص اكتمل بنجاح — كل شيء جاهز ✅")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# حارس ضد التشغيل الصامت: لو نفّذ workflow قديم «python bot.py» مباشرة
# فسيظهر تحذير واضح ويفشل التشغيل بدل علامة خضراء كاذبة بلا أي إرسال.
if __name__ == "__main__":
    print(
        "\n"
        "⚠️  توقف — bot.py وحدة داخلية وليست نقطة تشغيل، لذلك لا يرسل شيئًا إذا شُغّل مباشرة.\n"
        "\n"
        "   ✅ نقطة الدخول الصحيحة محليًا:      python main.py\n"
        "   ✅ أوامر مفيدة:                     python main.py --doctor | --dry-run | --test\n"
        "   ✅ وعلى GitHub Actions:             شغّل workflow «📰 Crypto News Bot» (news.yml)\n"
        "\n"
        "   🔧 إن كان هذا التشغيل من workflow قديم (مثل cron.yml) يشغل «python bot.py»:\n"
        "      احذف ملفات الـ workflows القديمة من .github/workflows/ وأبقِ الأربعة الجديدة فقط.\n"
        "\n",
        flush=True,
    )
    raise SystemExit(2)
