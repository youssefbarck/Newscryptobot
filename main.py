"""
🐋 Whale News Bot — نقطة الدخول
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بوت مبسّط: جلب أخبار → ترجمة Google → إرسال.
"""

import os, asyncio, traceback

from config import config, state, log, save_sent_news
from telegram_bot import run_bot, run_oneshot
from translate import translation_cache


# حذف كاش الترجمة عند كل بدء تشغيل
_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translation_cache.json")
if os.path.exists(_cache_path):
    os.remove(_cache_path)
    print(f"🗑️ تم حذف كاش الترجمة: {_cache_path}")


async def main():
    if config.GITHUB_ACTIONS or config.RUN_MODE == "oneshot":
        await run_oneshot(config, state)
    else:
        await run_bot(config, state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Interrupted")
        save_sent_news(force=True)
        translation_cache.flush()
    except Exception as e:
        log.error(f"Fatal: {e}\n{traceback.format_exc()}")
        save_sent_news(force=True)
        translation_cache.flush()
