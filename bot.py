"""
🤖 البوت الرئيسي — ينسق بين كل الوحدات
"""

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
from formatter import format_post, validate_post
from dedup import (
    load_hashes, save_hashes, compute_hash, is_duplicate,
)


# ═══════════════════════════════════════════════════════════
# التحقق من إعدادات البوت
# ═══════════════════════════════════════════════════════════
def check_config() -> bool:
    """فحص أن كل المتغيرات اللازمة موجودة"""
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
# إرسال المنشور للقناة مع الصورة
# ═══════════════════════════════════════════════════════════
async def send_post(text: str, image_url: str = "") -> bool:
    """
    إرسال المنشور للقناة:
    - إذا وُجدت صورة صالحة → sendPhoto مع caption
    - وإلا → sendMessage
    """
    if not text:
        return False

    # التحقق من الصورة أولاً
    has_valid_image = False
    if image_url and image_url.startswith("http"):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as resp:
                    if resp.status == 200 and "image" in resp.headers.get("Content-Type", ""):
                        has_valid_image = True
        except Exception:
            has_valid_image = False

    try:
        async with aiohttp.ClientSession() as session:
            # محاولة إرسال كصورة
            if has_valid_image:
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                    data = aiohttp.FormData()
                    data.add_field("chat_id", TELEGRAM_CHAT_ID)
                    data.add_field("photo", image_url)
                    data.add_field("caption", text[:1024])  # حد caption للصور 1024
                    data.add_field("parse_mode", "HTML")
                    async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            log.info(f"📸 Sent with image")
                            return True
                        else:
                            err = await resp.text()
                            log.warning(f"📸 Photo failed: {err[:200]}")
                except Exception as e:
                    log.warning(f"📸 Photo error: {e}")

            # إرسال كنص (احتياطي أو لا توجد صورة)
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text[:4096],
            }
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
    """دورة واحدة كاملة: جلب → فلترة → ترجمة → تنسيق → إرسال"""
    log.info("=" * 60)
    log.info("🚀 Cycle started")
    start_time = time.time()

    if not check_config():
        return

    # 1) تحميل الهاشات المحفوظة
    sent_hashes = load_hashes()
    recent_titles = []  # العناوين المُرسلة في هذه الدورة فقط
    sent_count = 0

    # 2) جلب الأخبار
    try:
        news = await fetch_all_news()
    except Exception as e:
        log.error(f"❌ Fetch error: {e}")
        return

    if not news:
        log.info("ℹ️ No news fetched")
        return

    # 3) فلترة العمر
    now = time.time()
    max_age_seconds = MAX_NEWS_AGE_HOURS * 3600
    fresh_news = [
        n for n in news
        if n.timestamp == 0 or (now - n.timestamp) <= max_age_seconds
    ]
    log.info(f"📅 After age filter: {len(fresh_news)} fresh / {len(news)} total")

    # 4) معالجة كل خبر
    for item in fresh_news:
        if sent_count >= MAX_POSTS_PER_RUN:
            log.info(f"✅ Reached MAX_POSTS_PER_RUN ({MAX_POSTS_PER_RUN})")
            break

        title = item.title.strip()
        if not title:
            continue

        # فحص التكرار قبل الترجمة
        if is_duplicate(title, sent_hashes, recent_titles):
            continue

        # ترجمة
        success = await translate_news_item(item)
        if not success or not getattr(item, 'title_ar', ''):
            log.warning(f"🌐 Translation failed: {title[:60]}")
            continue

        # تنسيق المنشور
        post_text = format_post(item)
        if not post_text or not validate_post(post_text):
            log.warning(f"📝 Invalid post: {getattr(item, 'title_ar', '')[:60]}")
            continue

        # فحص التكرار بعد الترجمة (للعناوين العربية)
        if is_duplicate(item.title_ar, sent_hashes, recent_titles):
            continue

        # إرسال
        ok = await send_post(post_text, item.image)
        if ok:
            sent_count += 1
            # تسجيل الهاشات
            sent_hashes.add(compute_hash(title))
            sent_hashes.add(compute_hash(item.title_ar))
            recent_titles.append(title)
            recent_titles.append(item.title_ar)
            log.info(f"✅ [{sent_count}/{MAX_POSTS_PER_RUN}] {item.title_ar[:60]}")
            # انتظار قصير بين المنشورات (لتجنب rate limit)
            await asyncio.sleep(3)
        else:
            log.error(f"❌ Send failed: {item.title_ar[:60]}")

    # 5) حفظ الهاشات (دائماً، حتى لو لم نرسل شيئاً — لتحديث الأ timestamp)
    save_hashes(sent_hashes)

    elapsed = time.time() - start_time
    log.info(f"📊 Done: {sent_count} posts sent in {elapsed:.1f}s")
    log.info("=" * 60)


# ═══════════════════════════════════════════════════════════
# نقطة الدخول
# ═══════════════════════════════════════════════════════════
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
