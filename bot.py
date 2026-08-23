"""البوت الرئيسي — خبر عاجل واحد كل دورة"""

import os
import re
import asyncio
import time
import aiohttp
from typing import Optional

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MAX_POSTS_PER_RUN, MAX_NEWS_AGE_HOURS, log,
)
from sources import fetch_all_news, NewsItem
from translator import translate_news_item
from formatter import format_post, validate_post, is_banned_title, is_banned_title_ar
from dedup import (
    load_hashes, save_hashes, compute_hash, is_duplicate,
)


# ═══════════════════════════════════════════════════════════
# 🔥 نظام ترشيح الأخبار — أحداث محورية فقط
# ═══════════════════════════════════════════════════════════
_EVENT_KEYWORDS = {
    # اختراقات وسرقات — أعلى أولوية
    'hack': 5, 'hacked': 5, 'exploit': 5, 'breach': 5, 'stolen': 5,
    'drained': 5, 'theft': 5,
    # تنظيم حاسم
    'sec ': 4, 'approved': 4, 'approval': 4, 'banned': 4,
    'lawsuit': 4, 'sued': 4, 'subpoena': 4, 'indictment': 4,
    'arrested': 4, 'court order': 4,
    # تحركات سعرية صادمة
    'surge': 4, 'soar': 4, 'skyrocket': 4, 'plunge': 4, 'crash': 4,
    'all-time high': 4, 'record high': 4, 'record low': 4,
    'jumps': 3, 'drops': 2,
    # ETF واستثمار مؤسسي
    'etf': 3, 'inflow': 4, 'outflow': 4,
    'blackrock': 3, 'spot bitcoin': 4, 'spot eth': 4,
    # إفلاس وانهيار
    'bankrupt': 4, 'bankruptcy': 4, 'collapse': 4,
    # أحداث تقنية كبرى
    'halving': 4, 'mainnet': 2, 'airdrop': 2,
    # اقتصاد كلوي
    'fomc': 4, 'rate cut': 4, 'rate hike': 4,
    'federal reserve': 3, 'powell': 3,
    # شراء/بيع كبار
    'buys': 2, 'bought': 2, 'purchases': 3, 'acquires': 3,
    'invests': 2, 'sells': 2,
}

_PENALTY_KEYWORDS = {
    'study': -5, 'survey': -5, 'research': -3, 'report says': -3,
    'opinion': -5, 'analysis': -5, 'commentary': -5,
    'prediction': -4, 'forecast': -4, 'could': -1, 'may': -1,
    'weekly roundup': -6, 'daily digest': -6, 'state of crypto': -5,
    'what happened': -5, 'things to know': -5, 'top 10': -5,
    'top 5': -5, 'altcoins to watch': -5, 'price prediction': -5,
    "here's what": -4, 'everything you': -4,
    'wavers': -4, 'year-end call': -5, 'says it may': -3,
    'is it time': -4, 'will it': -3, 'should you': -4,
    'how a ': -3, 'how ': -2,
    "but altcoin": -2, 'but the ': -1,
}


def score_news_item(item: NewsItem) -> float:
    """
    تقييم أهمية الخبر:
    - حدث محوري (اختراق، قرار SEC، ارتفاع صادم) = نقاط عالية
    - تحليل/رأي/تلميح = عقوبة قاسية
    """
    score = 0.0
    text = (item.title + ' ' + item.summary).lower()
    title = item.title.strip()

    # 0) سؤال = ممنوع
    if '?' in title:
        return -100

    # 1) أحداث محورية
    for keyword, points in _EVENT_KEYWORDS.items():
        if keyword in text:
            score += points

    # 2) عقوبات (تحليلات / حشو / تلميحات)
    for keyword, points in _PENALTY_KEYWORDS.items():
        if keyword in text:
            score += points

    # 3) عملة رئيسية
    for coin in ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'xrp']:
        if coin in text:
            score += 1
            break

    # 4) حداثة الخبر
    if item.timestamp > 0:
        age_hours = (time.time() - item.timestamp) / 3600
        if age_hours < 1:
            score += 2
        elif age_hours < 2:
            score += 1

    return score


# ═══════════════════════════════════════════════════════════
# التحقق من إعدادات البوت
# ═══════════════════════════════════════════════════════════
def check_config() -> bool:
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID")
    if errors:
        log.error("❌ Missing env vars: " + ", ".join(errors))
        log.error("   تأكد من إضافتها في GitHub Secrets")
        return False
    return True


# ═══════════════════════════════════════════════════════════
# إرسال المنشور للقناة
# ═══════════════════════════════════════════════════════════
async def send_post(text: str, image: str = "", is_file: bool = False) -> bool:
    if not text:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            # صورة من ملف محلي (chart)
            if is_file and image and os.path.exists(image):
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                    with open(image, 'rb') as f:
                        data = aiohttp.FormData()
                        data.add_field("chat_id", TELEGRAM_CHAT_ID)
                        data.add_field("photo", f, filename='chart.png', content_type='image/png')
                        data.add_field("caption", text[:1024])
                        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                log.info(f"📊 Sent chart image")
                                return True
                            else:
                                err = await resp.text()
                                log.warning(f"📊 Chart photo failed: {err[:200]}")
                except Exception as e:
                    log.warning(f"📊 Chart photo error: {e}")

            # صورة من URL
            elif image and image.startswith("http"):
                has_valid_image = False
                try:
                    async with session.head(image, timeout=aiohttp.ClientTimeout(total=5),
                                            headers={"User-Agent": "Mozilla/5.0"}) as resp:
                        if resp.status == 200 and "image" in resp.headers.get("Content-Type", ""):
                            has_valid_image = True
                except Exception:
                    has_valid_image = False

                if has_valid_image:
                    try:
                        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                        data = aiohttp.FormData()
                        data.add_field("chat_id", TELEGRAM_CHAT_ID)
                        data.add_field("photo", image)
                        data.add_field("caption", text[:1024])
                        async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                log.info(f"📸 Sent with image")
                                return True
                            else:
                                err = await resp.text()
                                log.warning(f"📸 Photo failed: {err[:200]}")
                    except Exception as e:
                        log.warning(f"📸 Photo error: {e}")

            # نص فقط
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]}
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    log.info(f"💬 Sent as text")
                    return True
                else:
                    err = await resp.text()
                    log.error(f"❌ Send failed: {err[:300]}")
                    return False
    except Exception as e:
        log.error(f"❌ Send exception: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# الدورة الرئيسية
# ═══════════════════════════════════════════════════════════
async def run_cycle():
    """دورة واحدة: جلب → ترشيح صارم → ترجمة الأهم → إرسال واحد"""
    log.info("=" * 60)
    log.info("🚀 Cycle started")
    start_time = time.time()

    if not check_config():
        return

    # 1) تحميل الهاشات
    sent_hashes = load_hashes()
    recent_titles = []
    sent_count = 0

    # 2) جلب الأخبار
    try:
        news = await fetch_all_news()
    except Exception as e:
        log.error(f"❌ Fetch error: {e}")
        return

    if not news:
        log.info("ℹ️ No news fetched")
        save_hashes(sent_hashes)
        elapsed = time.time() - start_time
        log.info(f"📊 Done: {sent_count} posts sent in {elapsed:.1f}s")
        log.info("=" * 60)
        return

    # 3) فلترة العمر
    now = time.time()
    max_age_seconds = MAX_NEWS_AGE_HOURS * 3600
    fresh_news = [
        n for n in news
        if n.timestamp == 0 or (now - n.timestamp) <= max_age_seconds
    ]
    log.info(f"📅 Age filter: {len(fresh_news)} fresh / {len(news)} total")

    # 4) فلتر صارم: مكرر + ممنوع
    candidates = []
    for item in fresh_news:
        title = item.title.strip()
        if not title:
            continue
        if is_duplicate(title, sent_hashes, recent_titles):
            continue
        if is_banned_title(title):
            log.info(f"🚫 Banned: {title[:60]}")
            continue
        candidates.append(item)

    # 5) ترتيب بالأهمية
    candidates.sort(key=lambda x: -score_news_item(x))
    log.info(f"🔥 Ranked {len(candidates)} candidates")
    for i, c in enumerate(candidates[:5]):
        s = score_news_item(c)
        log.info(f"   [{i+1}] score={s:.1f} | {c.title[:60]}")

    # 6) ترجمة وإرسال الأهم فقط (خبر واحد)
    for item in candidates:
        if sent_count >= MAX_POSTS_PER_RUN:
            break

        # ترجمة
        success = await translate_news_item(item)
        if not success or not getattr(item, 'title_ar', ''):
            log.warning(f"🌐 Translation failed: {item.title[:60]}")
            continue

        # فلتر العنوان المترجم
        if is_banned_title_ar(item.title_ar):
            log.info(f"🚫 Banned AR: {item.title_ar[:60]}")
            continue

        # تنسيق المنشور
        post_text = format_post(item)
        if not post_text or not validate_post(post_text):
            log.warning(f"📝 Invalid post: {getattr(item, 'title_ar', '')[:60]}")
            continue

        # فحص التكرار بعد الترجمة
        if is_duplicate(item.title_ar, sent_hashes, recent_titles):
            continue

        # إرسال
        ok = await send_post(post_text, item.image)
        if ok:
            sent_count += 1
            sent_hashes.add(compute_hash(item.title))
            sent_hashes.add(compute_hash(item.title_ar))
            recent_titles.append(item.title)
            recent_titles.append(item.title_ar)
            log.info(f"✅ [{sent_count}/{MAX_POSTS_PER_RUN}] {item.title_ar[:60]}")
            await asyncio.sleep(3)
        else:
            log.error(f"❌ Send failed: {item.title_ar[:60]}")

    # 7) حفظ الهاشات
    save_hashes(sent_hashes)

    elapsed = time.time() - start_time
    log.info(f"📊 Done: {sent_count} posts sent in {elapsed:.1f}s")
    log.info("=" * 60)


def main():
    """نقطة دخول البوت — تُستدعى من GitHub Actions"""
    try:
        asyncio.run(run_cycle())
    except KeyboardInterrupt:
        log.info("🛑 Interrupted")
    except Exception as e:
        import traceback
        log.error(f"❌ Fatal: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
