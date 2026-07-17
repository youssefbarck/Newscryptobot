"""
🐋 Whale News Bot v2.0 - نقطة الدخول
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بنية async متكاملة مع queues، rate limiting، و circuit breaker

التحسينات الرئيسية:
- asyncio + aiohttp للجلب المتوازي
- Message queues للفصل بين الجلب والإرسال
- Semantic deduplication
- Circuit breaker للمصادر المتعثرة
- Rate limiting على Telegram API
- Memory-efficient image processing
- Structured logging
"""

import os, asyncio, traceback

from config import config, state, log, save_sent_news
from telegram_bot import run_bot, run_oneshot


async def main():
    """نقطة الدخول الرئيسية"""

    if config.GITHUB_ACTIONS or config.RUN_MODE == "oneshot":
        # وضع GitHub Actions
        await run_oneshot(config, state)
    else:
        # وضع التشغيل الدائم
        await run_bot(config, state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("🛑 Interrupted by user")
        save_sent_news(force=True)
    except Exception as e:
        log.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        save_sent_news(force=True)