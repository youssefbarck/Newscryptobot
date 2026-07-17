# 🐋 Whale News Bot

بوت أخبار العملات الرقمية المتقدم — بنية async مع queues و circuit breaker.

## ✨ التحسينات الجديدة

| الميزة | الوصف |
|--------|-------|
| **Async Architecture** | asyncio + aiohttp للجلب المتوازي |
| **Message Queues** | فصل الجلب والمعالجة والإرسال |
| **Semantic Deduplication** | إزالة التكرار بذكاء |
| **Circuit Breaker** | حماية من المصادر المتعثرة |
| **Rate Limiting** | Token bucket للـ Telegram API |
| **Smart Scoring** | تقييم أهمية الخبر (0-10) |
| **Memory Efficient** | معالجة الصور بدون استهلاك RAM |

## 🚀 التشغيل

```bash
# تثبيت المتطلبات
pip install -r requirements.txt

# تشغيل
python main.py

# أو وضع GitHub Actions
RUN_MODE=oneshot python main.py
