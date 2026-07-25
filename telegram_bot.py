"""
🤖 Whale News Bot — Telegram Bot (مبسّط)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بوت مبسّط: جلب → ترجمة → تنسيق → إرسال.
"""

import os, re, time, json, asyncio, hashlib
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientTimeout

from config import (
    log, BotConfig, BotState, TELEGRAM_RATE_LIMITER,
    MAX_NEWS_PER_SCAN, MAX_NEWS_AGE, SCAN_INTERVAL, tz,
    save_sent_news, sent_news_hashes,
)
from filters import NewsItem, filter_news_items
from rss import fetch_all_news, fetch_etf_flows, session_manager
from translate import TranslationManager, translation_cache, COIN_NAME_TO_TICKER


# ═══════════════════════════════════════════════════════════
# 📤 Message Queue
# ═══════════════════════════════════════════════════════════
@dataclass
class QueuedMessage:
    text: str
    image_url: Optional[str] = None
    chat_id: Optional[str] = None
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3


class MessageQueue:
    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._processed: Set[str] = set()
        self._stats = {"sent": 0, "failed": 0}

    async def put(self, msg: QueuedMessage):
        await self._queue.put((-msg.priority, time.time(), msg))

    async def get(self) -> Optional[QueuedMessage]:
        try:
            _, _, msg = await asyncio.wait_for(self._queue.get(), timeout=5)
            return msg
        except asyncio.TimeoutError:
            return None

    async def process(self):
        while True:
            msg = await self.get()
            if msg:
                await _send_telegram(msg)


message_queue = MessageQueue()


# ═══════════════════════════════════════════════════════════
# 📨 إرسال Telegram
# ═══════════════════════════════════════════════════════════
async def _send_telegram(msg: QueuedMessage):
    """إرسال رسالة إلى تيليجرام"""
    if not msg.text:
        return

    chat_id = msg.chat_id or config.CHAT_ID
    max_msg_len = 4096

    # تقسيم الرسائل الطويلة
    text = msg.text[:max_msg_len]

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }

    # إرسال الصورة مع النص
    if msg.image_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(msg.image_url, timeout=ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        img_data = await resp.read()
                        # إرسال كصورة
                        img_payload = {
                            "chat_id": chat_id,
                            "photo": aiohttp.payload.BytesPayload(img_data, content_type="image/jpeg"),
                            "caption": text[:1024],
                            "parse_mode": "HTML",
                        }
                        async with session.post(
                            f"https://api.telegram.org/bot{config.TOKEN}/sendPhoto",
                            data=img_payload,
                            timeout=ClientTimeout(total=30),
                        ) as resp:
                            if resp.status == 200:
                                message_queue._stats["sent"] += 1
                                log.info(f"✅ Sent (photo) to {chat_id}")
                                return
        except Exception as e:
            log.warning(f"Photo send failed: {e}")

    # إرسال كنص
    await TELEGRAM_RATE_LIMITER.acquire()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{config.TOKEN}/sendMessage",
                json=payload,
                timeout=ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    message_queue._stats["sent"] += 1
                    log.info(f"✅ Sent to {chat_id}")
                else:
                    error = await resp.text()
                    log.warning(f"❌ Send failed: {resp.status} {error[:200]}")
                    message_queue._stats["failed"] += 1
    except Exception as e:
        log.warning(f"Send error: {e}")
        message_queue._stats["failed"] += 1


# ═══════════════════════════════════════════════════════════
# 🧹 تنظيف بسيط قبل الإرسال
# ═══════════════════════════════════════════════════════════
def clean_message(text: str) -> Optional[str]:
    """تنظيف بسيط: إزالة الأشياء غير المفهومة"""
    if not text or not text.strip():
        return None

    lines = text.strip().split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # سطر فارغ
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        # توقيع
        if "@newscrypto1m" in stripped:
            continue

        # سكريبتات خاطئة (Telugu, Devanagari...)
        if re.search(r'[\u0C00-\u0C7F\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0E00-\u0E7F]', stripped):
            return None

        # كلمات إنجليزية مشبوهة (ليست أسماء عملات/بروتوكولات)
        # قائمة الأسماء المسموحة
        allowed = {
            "Bitcoin", "Ethereum", "Solana", "Binance", "Coinbase", "USDT", "USDC",
            "BlackRock", "MicroStrategy", "Grayscale", "Fidelity", "SEC", "ETF",
            "DeFi", "NFT", "Web3", "Litecoin", "Dogecoin", "Avalanche", "Polkadot",
            "Chainlink", "Polygon", "Tron", "Uniswap", "Aptos", "Arbitrum",
            "Optimism", "Stellar", "Hedera", "Cosmos", "Fantom", "Aave", "Tether",
            "Circle", "OKX", "Kraken", "Bybit", "Ripple", "Cardano", "Toncoin",
            "Near", "Sui", "Sei", "Shiba", "Pepe", "Vitalik", "Satoshi", "Saylor",
            "Gensler", "CZ", "Dorsey", "Buterin", "Musk",
            "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "DOT",
            "LINK", "POL", "LTC", "TRX", "UNI", "APT", "ARB", "SUI", "SEI",
            "TON", "FTM", "ATOM", "XLM", "HBAR", "SHIB", "PEPE", "DAI", "OP",
            "IBIT", "FBTC", "GBTC", "ETHA", "HODL", "NEAR",
        }

        english_words = re.findall(r'\b([a-zA-Z]{4,})\b', stripped)
        suspicious = [w for w in english_words if w not in allowed]
        if suspicious:
            log.info(f"🧹 Removed line with unknown English: {suspicious}")
            continue

        cleaned.append(stripped)

    if not cleaned:
        return None

    result = "\n".join(cleaned).strip()

    # فحص أدنى: يجب أن يكون فيه عربي
    arabic_chars = sum(1 for c in result if '\u0600' <= c <= '\u06FF')
    if arabic_chars < 10:
        return None

    return result if len(result) > 15 else None


# ═══════════════════════════════════════════════════════════
# 📝 تنسيق الخبر
# ═══════════════════════════════════════════════════════════
def format_news_item(item: NewsItem) -> Optional[str]:
    """تنسيق الخبر: عنوان فقط + هاشتاغات + توقيع"""
    title_ar = item.title_ar or item.title

    if not title_ar or title_ar == item.title:
        return None

    # التأكد أن العنوان ينتهي بنقطة
    title_clean = title_ar.strip()
    if title_clean and title_clean[-1] not in ".؟!؟.؟\u06d4":
        title_clean += "."

    # رمز بسيط
    msg = f"🔵 {title_clean}"

    # إضافة العملات
    if item.coins:
        seen = set()
        unique = []
        for c in item.coins:
            canonical = COIN_NAME_TO_TICKER.get(c.lower(), c.upper())
            if canonical not in seen:
                seen.add(canonical)
                unique.append(canonical)
        if unique:
            coins_str = " ".join([f"#{c}" for c in unique[:5]])
            msg += f"\n\n{coins_str}"

    msg += "\n\n✉️ @newscrypto1m"
    return msg


def format_etf_flows(etf_data: Dict) -> str:
    """تنسيق بيانات ETF"""
    from config import tz
    msg = "📊 تدفقات صناديق ETF\n"

    btc_total = etf_data.get("btc_total", 0)
    btc_dir = "إيجابي" if btc_total > 0 else ("سلبي" if btc_total < 0 else "تعادل")
    btc_sign = "+" if btc_total > 0 else ""
    msg += f"🔴 Bitcoin ETF — {btc_dir} {btc_sign}{btc_total:.1f}M\n"

    eth_total = etf_data.get("eth_total", 0)
    eth_dir = "إيجابي" if eth_total > 0 else ("سلبي" if eth_total < 0 else "تعادل")
    eth_sign = "+" if eth_total > 0 else ""
    msg += f"🔵 Ethereum ETF — {eth_dir} {eth_sign}{eth_total:.1f}M"

    msg += "\n\n✉️ @newscrypto1m"
    return msg


# ═══════════════════════════════════════════════════════════
# 🔍 حلقة فحص الأخبار
# ═══════════════════════════════════════════════════════════
async def scan_news_loop(config: BotConfig, state: BotState, translator: TranslationManager):
    """حلقة جلب ونشر الأخبار"""
    log.info("🔍 News scanner started")
    await asyncio.sleep(10)

    while True:
        try:
            if state.bot_shutdown or not state.auto_alerts_enabled:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            log.info("🔍 Scanning news...")

            # جلب الأخبار
            news = await fetch_all_news(max_concurrent=5)
            if not news:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # فلترة
            filtered = filter_news_items(news)

            now = time.time()
            alerts_sent = 0

            for item in filtered[:MAX_NEWS_PER_SCAN]:
                # فحص العمر
                if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
                    sent_news_hashes.add(item.hash)
                    continue

                # فحص الإرسال السابق
                if item.hash in sent_news_hashes:
                    continue

                # فحص cooldown
                if item.hash in state.last_alerts_hashes:
                    if now - state.last_alerts_hashes[item.hash] < 21600:
                        continue

                # ترجمة
                await translator.translate_item(item)
                if not item.title_ar:
                    continue

                # تنسيق
                msg = format_news_item(item)
                if not msg:
                    continue

                # تنظيف بسيط
                msg = clean_message(msg)
                if not msg:
                    log.info(f"🧹 Blocked: {item.title[:60]}")
                    continue

                # إرسال
                sent_news_hashes.add(item.hash)
                state.last_alerts_hashes[item.hash] = now

                # للقناة
                if state.is_channel_enabled(config):
                    await message_queue.put(QueuedMessage(
                        text=msg, image_url=item.image, chat_id=config.CHANNEL_ID, priority=2,
                    ))

                # للمالك
                await message_queue.put(QueuedMessage(
                    text=msg, image_url=item.image, chat_id=config.CHAT_ID, priority=2,
                ))

                alerts_sent += 1
                log.info(f"  ✉️ {item.title[:60]}")

            log.info(f"📊 Scan: {len(news)} fetched, {len(filtered)} filtered, {alerts_sent} sent")

            # حفظ الهاشات
            if alerts_sent > 0:
                save_sent_news()

            # ETF flows
            try:
                etf = await fetch_etf_flows()
                if etf:
                    etf_hash = f"etf_{etf['date']}"
                    if etf_hash not in sent_news_hashes:
                        sent_news_hashes.add(etf_hash)
                        msg = format_etf_flows(etf)
                        if state.is_channel_enabled(config):
                            await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHANNEL_ID, priority=1))
                        await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHAT_ID, priority=1))
            except Exception as e:
                log.warning(f"ETF flows error: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Scan loop error: {e}")
            await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════
# 🤖 أوامر البوت
# ═══════════════════════════════════════════════════════════
async def handle_command(text: str, chat_id: str) -> Optional[str]:
    """معالجة الأوامر"""
    text = text.strip()

    if text == "/start":
        return ("🤖 Whale News Bot\n\n"
                "أبسط بوت أخبار كريبتو.\n"
                "يُترجم الأخبار بالعربي ويُرسلها تلقائياً.\n\n"
                "الأوامر:\n"
                "/status — حالة البوت\n"
                "/pause — إيقاف مؤقت\n"
                "/resume — استئناف\n"
                "/stats — إحصائيات")

    elif text == "/status":
        enabled = "✅ يعمل" if config.state.auto_alerts_enabled else "⏸️ متوقف"
        channel = "✅" if config.state.is_channel_enabled(config) else "❌"
        return (f"📊 حالة البوت\n\n"
                f"الحالة: {enabled}\n"
                f"القناة: {channel}\n"
                f"المصادر: {len(NEWS_SOURCES)}\n"
                f"المُرسلة: {len(sent_news_hashes)}")

    elif text == "/pause":
        config.state.auto_alerts_enabled = False
        return "⏸️ تم الإيقاف المؤقت."

    elif text == "/resume":
        config.state.auto_alerts_enabled = True
        return "✅ تم الاستئناف."

    elif text == "/stats":
        return (f"📊 الإحصائيات\n\n"
                f"المُرسلة: {len(sent_news_hashes)}\n"
                f"الحالة: {'يعمل' if config.state.auto_alerts_enabled else 'متوقف'}")

    return None


# ═══════════════════════════════════════════════════════════
# 🚀 تشغيل البوت
# ═══════════════════════════════════════════════════════════
async def run_bot(config: BotConfig, state: BotState):
    """تشغيل البوت الدائم"""
    translator = TranslationManager(config)

    # تحميل الأخبار المُرسلة
    from config import load_sent_news
    load_sent_news()
    state.sent_news_hashes = sent_news_hashes

    # بدء حلقة الفحص
    asyncio.create_task(scan_news_loop(config, state, translator))
    asyncio.create_task(message_queue.process())

    # Polling
    offset = 0
    log.info("🤖 Bot started (polling)")

    while not state.bot_shutdown:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.telegram.org/bot{config.TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=ClientTimeout(total=35),
                ) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(5)
                        continue

                    data = await resp.json()
                    if not data.get("ok"):
                        await asyncio.sleep(5)
                        continue

                    for update in data.get("result", []):
                        offset = update.get("update_id", 0) + 1
                        message = update.get("message", {})
                        text = message.get("text", "")
                        chat_id = str(message.get("chat", {}).get("id", ""))

                        if text.startswith("/"):
                            reply = await handle_command(text, chat_id)
                            if reply:
                                await TELEGRAM_RATE_LIMITER.acquire()
                                try:
                                    await session.post(
                                        f"https://api.telegram.org/bot{config.TOKEN}/sendMessage",
                                        json={"chat_id": chat_id, "text": reply},
                                        timeout=ClientTimeout(total=10),
                                    )
                                except Exception:
                                    pass
        except Exception as e:
            log.warning(f"Polling error: {e}")
            await asyncio.sleep(10)

    # تنظيف
    await session_manager.close()


async def run_oneshot(config: BotConfig, state: BotState):
    """تشغيل دورة واحدة (GitHub Actions)"""
    log.info("🎯 Oneshot mode")

    translator = TranslationManager(config)

    # تحميل الأخبار المُرسلة
    from config import load_sent_news
    load_sent_news()
    state.sent_news_hashes = sent_news_hashes

    # جلب
    news = await fetch_all_news(max_concurrent=5)
    filtered = filter_news_items(news)

    now = time.time()
    alerts_sent = 0

    for item in filtered[:MAX_NEWS_PER_SCAN]:
        if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
            sent_news_hashes.add(item.hash)
            continue
        if item.hash in sent_news_hashes:
            continue

        await translator.translate_item(item)
        if not item.title_ar:
            continue

        msg = format_news_item(item)
        if not msg:
            continue

        msg = clean_message(msg)
        if not msg:
            continue

        sent_news_hashes.add(item.hash)

        if state.is_channel_enabled(config):
            await message_queue.put(QueuedMessage(text=msg, image_url=item.image, chat_id=config.CHANNEL_ID))
        await message_queue.put(QueuedMessage(text=msg, image_url=item.image, chat_id=config.CHAT_ID))

        alerts_sent += 1
        log.info(f"  ✉️ {item.title[:60]}")

    # معالجة الطابور
    for _ in range(50):
        msg = await message_queue.get()
        if msg:
            await _send_telegram(msg)

    if alerts_sent > 0:
        save_sent_news()

    log.info(f"📊 Oneshot: {len(news)} fetched, {len(filtered)} filtered, {alerts_sent} sent")
    await session_manager.close()


# ═══ للتوافق مع handle_command
from config import NEWS_SOURCES, config
