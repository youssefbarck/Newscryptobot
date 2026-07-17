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

import os, asyncio

from config_v2 import config, state, log
from telegram_bot_v2 import run_bot, run_oneshot


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
    except Exception as e:
        log.error(f"Fatal error: {e}")
