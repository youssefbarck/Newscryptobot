"""
🤖 Whale News Bot v2.0 - Telegram Bot (Async)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بوت متقدم مع queues، rate limiting، و image processing فعال
يشمل: أوامر المستخدمين، broadcast، Flask webhook، Safety Mode
"""

import os, time, json, re, asyncio, hashlib, traceback
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientTimeout

from config import (
    log, BotConfig, BotState, TELEGRAM_RATE_LIMITER, TELEGRAM_CB,
    MAX_NEWS_PER_SCAN, MAX_NEWS_AGE, SCAN_INTERVAL,
    SUMMARY_HOUR, SUMMARY_MINUTE, tz,
    save_sent_news, load_sent_news, load_settings, save_settings,
    is_owner, is_allowed, add_user, remove_user, refresh_allowed,
    ALLOWED_USERS, CHANNEL_ID, CHANNEL_NAME, CHANNEL_LINK,
    RENDER_URL, PORT,
    CRYPTO_CONTEXT_KEYWORDS, REJECTION_KEYWORDS,
    AR_CRITICAL_KEYWORDS, AR_REJECTION_KEYWORDS,
)
from filters import (
    NewsItem, filter_news_items, time_ago, is_complete_news,
    news_hash,
)
from rss import fetch_all_news, fetch_etf_flows, session_manager
from translate import TranslationManager, translate_source_name, generate_etf_flow_report


# ═══════════════════════════════════════════════════════════
# 📤 Message Queue (Async Producer-Consumer)
# ═══════════════════════════════════════════════════════════
@dataclass
class QueuedMessage:
    """رسالة في الطابور"""
    text: str
    image_url: Optional[str] = None
    chat_id: Optional[str] = None
    priority: int = 0  # أعلى = أولوية أعلى
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)


class MessageQueue:
    """طابور رسائل async مع priority"""

    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._processed: Set[str] = set()
        self._lock = asyncio.Lock()
        self._stats = {"sent": 0, "failed": 0, "retried": 0}

    async def put(self, msg: QueuedMessage):
        """إضافة رسالة للطابور"""
        # تجنب التكرار
        msg_hash = hashlib.md5(f"{msg.chat_id}:{msg.text[:100]}".encode()).hexdigest()[:12]
        async with self._lock:
            if msg_hash in self._processed:
                return
            self._processed.add(msg_hash)
            # تنظيف القديم
            if len(self._processed) > 5000:
                self._processed.clear()

        await self._queue.put((-msg.priority, time.time(), msg))

    async def get(self) -> QueuedMessage:
        """سحب رسالة من الطابور"""
        _, _, msg = await self._queue.get()
        return msg

    async def mark_sent(self, success: bool = True):
        async with self._lock:
            if success:
                self._stats["sent"] += 1
            else:
                self._stats["failed"] += 1

    def size(self) -> int:
        return self._queue.qsize()

    def stats(self) -> Dict:
        return dict(self._stats)


message_queue = MessageQueue()


# ═══════════════════════════════════════════════════════════
# 📸 Image Processing (Memory Efficient)
# ═══════════════════════════════════════════════════════════
async def add_watermark(image_url: str, watermark: str = "@newscrypto1m") -> Optional[bytes]:
    """إضافة شعار على الصورة - async"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=ClientTimeout(total=15), headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status != 200:
                    return None

                img_data = await resp.read()
                img = Image.open(io.BytesIO(img_data)).convert("RGB")

                # Resize للحد من استهلاك الذاكرة
                max_size = (1200, 1200)
                img.thumbnail(max_size, Image.LANCZOS)

                width, height = img.size

                # خط
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(16, width // 30))
                except:
                    font = ImageFont.load_default()

                draw = ImageDraw.Draw(img)

                try:
                    bbox = draw.textbbox((0, 0), watermark, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except:
                    text_width, text_height = 150, 20

                padding = 10
                x = width - text_width - padding - 5
                y = height - text_height - padding - 5

                # خلفية شفافة
                draw.rectangle(
                    [x - 5, y - 5, x + text_width + 5, y + text_height + 5],
                    fill=(0, 0, 0, 160)
                )
                draw.text((x, y), watermark, fill=(255, 255, 255), font=font)

                output = io.BytesIO()
                img.save(output, format="JPEG", quality=80, optimize=True)
                return output.getvalue()
    except Exception as e:
        log.warning(f"Watermark error: {e}")
    return None


# ═══════════════════════════════════════════════════════════
# 📤 Telegram Sender (Async with Rate Limiting)
# ═══════════════════════════════════════════════════════════
async def send_telegram_message(
    chat_id: str,
    text: str,
    image_url: Optional[str] = None,
    token: str = ""
) -> bool:
    """إرسال رسالة تيليجرام مع rate limiting"""
    if not token or not chat_id:
        return False

    await TELEGRAM_RATE_LIMITER.acquire()

    try:
        async with aiohttp.ClientSession() as session:
            if image_url and image_url.startswith("http"):
                # محاولة إضافة watermark
                watermarked = await add_watermark(image_url)

                if watermarked:
                    data = aiohttp.FormData()
                    data.add_field("chat_id", str(chat_id))
                    data.add_field("caption", text[:1024])
                    data.add_field("parse_mode", "HTML")
                    data.add_field("photo", watermarked, filename="image.jpg", content_type="image/jpeg")

                    async with session.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data=data,
                        timeout=ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 200:
                            data_resp = await resp.json()
                            return data_resp.get("ok", False)

                # fallback: إرسال الرابط مباشرة
                payload = {
                    "chat_id": chat_id,
                    "photo": image_url.replace("&amp;", "&").strip()[:2000],
                    "caption": text[:1024],
                    "parse_mode": "HTML",
                }
                async with session.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    json=payload,
                    timeout=ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        data_resp = await resp.json()
                        return data_resp.get("ok", False)

            # إرسال كنص
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
                timeout=ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data_resp = await resp.json()
                    return data_resp.get("ok", False)
                elif resp.status == 429:
                    retry_after = int((await resp.json()).get("parameters", {}).get("retry_after", 30))
                    log.warning(f"Telegram rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)

    except Exception as e:
        log.warning(f"send_telegram error: {e}")

    return False


async def message_consumer(config: BotConfig, state: BotState):
    """مستهلك الطابور - يرسل الرسائل بشكل مستمر"""
    log.info("📤 Message consumer started")

    while True:
        try:
            msg = await message_queue.get()

            # فحص الإيقاف
            if state.bot_shutdown and msg.chat_id != config.CHAT_ID:
                continue

            success = await TELEGRAM_CB.call(
                send_telegram_message,
                msg.chat_id or config.CHAT_ID,
                msg.text,
                msg.image_url,
                config.TOKEN,
            )

            await message_queue.mark_sent(success)

            if not success and msg.retry_count < msg.max_retries:
                msg.retry_count += 1
                await asyncio.sleep(2 ** msg.retry_count)
                await message_queue.put(msg)

        except Exception as e:
            log.warning(f"Message consumer error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════
# 📢 Broadcast Alert (للقناة + المالك + كل المستخدمين المسموحين)
# ═══════════════════════════════════════════════════════════
async def broadcast_alert(
    text: str,
    config: BotConfig,
    state: BotState,
    image_url: Optional[str] = None,
    skip_users: bool = False,
    priority: int = 2,
):
    """إرسال تنبيه لكل المستلمين: القناة + المالك + المستخدمون المسموحون"""
    # للقناة
    if state.is_channel_enabled(config):
        await message_queue.put(QueuedMessage(
            text=text, image_url=image_url,
            chat_id=config.CHANNEL_ID, priority=priority,
        ))

    # للمالك
    await message_queue.put(QueuedMessage(
        text=text, image_url=image_url,
        chat_id=config.CHAT_ID, priority=priority,
    ))

    # للمستخدمين المسموحين (اختياري)
    if not skip_users:
        for uid in state.allowed_users:
            uid_str = str(uid)
            if uid_str != config.CHAT_ID and uid_str != config.CHANNEL_ID:
                await message_queue.put(QueuedMessage(
                    text=text, image_url=image_url,
                    chat_id=uid_str, priority=priority - 1,
                ))


# ═══════════════════════════════════════════════════════════
# 📝 News Formatting
# ═══════════════════════════════════════════════════════════
def format_news_item(item: NewsItem, show_summary: bool = True) -> Optional[str]:
    """تنسيق الخبر للإرسال"""
    title_ar = item.title_ar or item.title
    summary_ar = item.summary_ar or item.summary

    # فحص الجودة
    if not title_ar or title_ar == item.title:
        return None

    # بناء الرسالة
    msg = f"\U0001f535 {title_ar}\n"

    if show_summary and summary_ar:
        clean_summary = summary_ar.strip()
        if is_complete_news(clean_summary):
            if len(clean_summary) > 800:
                cut_at = clean_summary[:800].rfind(".")
                if cut_at > 200:
                    clean_summary = clean_summary[:cut_at + 1]
                else:
                    cut_at = clean_summary[:800].rfind(" ")
                    if cut_at > 200:
                        clean_summary = clean_summary[:cut_at] + "..."
                    else:
                        clean_summary = clean_summary[:800] + "..."
            if clean_summary:
                msg += f"\n{clean_summary}\n"

    # إضافة العملات إن وُجدت
    if item.coins:
        coins_str = " ".join([f"#{c}" for c in item.coins[:5]])
        msg += f"\n{coins_str}"

    msg += "\n\n\u2709\ufe0f"

    return msg


def format_etf_flows(etf_data: Dict) -> str:
    """تنسيق بيانات ETF"""
    btc_sign = "+" if etf_data['btc_total'] >= 0 else ""
    eth_sign = "+" if etf_data['eth_total'] >= 0 else ""
    btc_emoji = "\U0001f4c8" if etf_data['btc_total'] >= 0 else "\U0001f4c9"
    eth_emoji = "\U0001f4c8" if etf_data['eth_total'] >= 0 else "\U0001f4c9"

    msg = f"📊 صافي تدفقات صناديق ETF — {etf_data['date']}\n\n"
    msg += f"{btc_emoji} Bitcoin ETF: {btc_sign}{etf_data['btc_total']:.1f} مليون $"

    top_btc = sorted(etf_data['btc_funds'].items(), key=lambda x: -x[1])[:3]
    btc_parts = [f"{t} {v:+.1f}M" for t, v in top_btc if v != 0]
    if btc_parts:
        msg += f"  ({', '.join(btc_parts)})"
    msg += "\n"

    msg += f"{eth_emoji} Ethereum ETF: {eth_sign}{etf_data['eth_total']:.1f} مليون $"
    top_eth = sorted(etf_data['eth_funds'].items(), key=lambda x: -x[1])[:3]
    eth_parts = [f"{t} {v:+.1f}M" for t, v in top_eth if v != 0]
    if eth_parts:
        msg += f"  ({', '.join(eth_parts)})"
    msg += "\n\n\u2709\ufe0f"

    return msg


# ═══════════════════════════════════════════════════════════
# 🛡️ Safety Mode
# ═══════════════════════════════════════════════════════════
_session_start: float = 0.0

def _init_safety_mode(state: BotState):
    """تفعيل وضع الحماية إذا لم تُحمَّل أي هاشات"""
    global _session_start
    if len(state.sent_news_hashes) == 0:
        _session_start = time.time()
        log.warning(f"\u26a0\ufe0f Safety Mode: لا توجد هاشات محفوظة — رفض الأخبار قبل {_session_start}")
    else:
        _session_start = 0.0


def _is_safe_timestamp(timestamp: float) -> bool:
    """فحص هل الخبر أحدث من بداية الجلسة (Safety Mode)"""
    if _session_start <= 0:
        return True
    return timestamp >= _session_start


# ═══════════════════════════════════════════════════════════
# 🤖 User Commands (أوامر المستخدمين)
# ═══════════════════════════════════════════════════════════
async def handle_update(update: Dict, config: BotConfig, state: BotState):
    """معالجة تحديث من Telegram (polling/webhook)"""
    try:
        message = update.get("message", {})
        if not message:
            return

        text = message.get("text", "")
        chat_id = str(message.get("from", {}).get("id", ""))
        username = message.get("from", {}).get("username", "")

        if not text.startswith("/"):
            return

        command = text.split()[0].lower().split("@")[0]
        args = text.split()[1:] if len(text.split()) > 1 else []

        log.info(f"\U0001f4e4 Command: {command} from {chat_id} ({username})")

        # ─── /start ───
        if command == "/start":
            if is_owner(chat_id):
                msg = "\U0001f40b <b>Whale News Bot v2.0</b>\n\n\U0001f4cb الأوامر:\n"
                msg += "/status - حالة البوت\n"
                msg += "/allow [id] - إضافة مستخدم\n"
                msg += "/remove [id] - إزالة مستخدم\n"
                msg += "/toggle channel - تفعيل/إيقاف القناة\n"
                msg += "/toggle alerts - تفعيل/إيقاف التنبيهات\n"
                msg += "/toggle summary - تفعيل/إيقاف الملخص اليومي\n"
                msg += "/shutdown - إيقاف البوت\n"
                msg += "/restart - إعادة تشغيل البوت"
                await send_telegram_message(chat_id, msg, token=config.TOKEN)
            else:
                msg = "\U0001f40b مرحباً! هذا بوت أخبار كريبتو.\nللوصول للأوامر، تواصل مع المالك."
                await send_telegram_message(chat_id, msg, token=config.TOKEN)

        # ─── /help ───
        elif command == "/help":
            await handle_update({"message": {"text": "/start", "from": message.get("from", {})}}, config, state)

        # ─── /status ─── (الملك فقط)
        elif command == "/status":
            if not is_owner(chat_id):
                return
            total_hashes = len(state.sent_news_hashes)
            users_count = len(state.allowed_users)
            queue_stats = message_queue.stats()
            safety = "\u26a0\ufe0f ON" if _session_start > 0 else "\u2705 OFF"

            msg = "\U0001f4ca <b>حالة البوت</b>\n\n"
            msg += f"\U0001f504 الإصدار: v2.0\n"
            msg += f"\U0001f4e1 القناة: {'\u2705 مفعّلة' if state.is_channel_enabled(config) else '\u274c مُوقفة'}\n"
            msg += f"\U0001f514 التنبيهات: {'\u2705' if state.auto_alerts_enabled else '\u274c'}\n"
            msg += f"\U0001f4c5 الملخص: {'\u2705' if state.daily_summary_enabled else '\u274c'}\n"
            msg += f"\U0001f4cb Hashes محفوظة: {total_hashes}\n"
            msg += f"\U0001f465 مستخدمون: {users_count}\n"
            msg += f"\U0001f4e4 طابور: {message_queue.size()} رسالة\n"
            msg += f"\u2709 إجمالي مُرسل: {queue_stats.get('sent', 0)}\n"
            msg += f"\u274c فشل: {queue_stats.get('failed', 0)}\n"
            msg += f"\U0001f6e1 Safety Mode: {safety}\n"
            msg += f"\U0001f552 الوقت: {datetime.now(tz).strftime('%H:%M:%S')}"

            await send_telegram_message(chat_id, msg, token=config.TOKEN)

        # ─── /allow [id] ─── (الملك فقط)
        elif command == "/allow":
            if not is_owner(chat_id):
                return
            if not args:
                await send_telegram_message(chat_id, "\u274c الاستخدام: /allow [user_id]", token=config.TOKEN)
                return
            target_id = args[0]
            if add_user(target_id):
                await send_telegram_message(chat_id, f"\u2705 تم إضافة {target_id}", token=config.TOKEN)
            else:
                await send_telegram_message(chat_id, f"\u26a0\ufe0f {target_id} مُضاف بالفعل أو غير صالح", token=config.TOKEN)

        # ─── /remove [id] ─── (الملك فقط)
        elif command == "/remove":
            if not is_owner(chat_id):
                return
            if not args:
                await send_telegram_message(chat_id, "\u274c الاستخدام: /remove [user_id]", token=config.TOKEN)
                return
            target_id = args[0]
            if remove_user(target_id):
                await send_telegram_message(chat_id, f"\u2705 تمت إزالة {target_id}", token=config.TOKEN)
            else:
                await send_telegram_message(chat_id, f"\u26a0\ufe0f لا يمكن إزالة {target_id}", token=config.TOKEN)

        # ─── /toggle ─── (الملك فقط)
        elif command == "/toggle":
            if not is_owner(chat_id):
                return
            if not args:
                await send_telegram_message(
                    chat_id,
                    "\u274c الاستخدام:\n/toggle channel\n/toggle alerts\n/toggle summary",
                    token=config.TOKEN,
                )
                return

            what = args[0].lower()

            if what == "channel":
                if state.channel_enabled is None:
                    state.channel_enabled = True
                else:
                    state.channel_enabled = not state.channel_enabled
                save_settings()
                status = "\u2705 مفعّلة" if state.channel_enabled else "\u274c مُوقفة"
                await send_telegram_message(chat_id, f"\U0001f4e1 القناة: {status}", token=config.TOKEN)

            elif what == "alerts":
                state.auto_alerts_enabled = not state.auto_alerts_enabled
                save_settings()
                status = "\u2705 مفعّلة" if state.auto_alerts_enabled else "\u274c مُوقفة"
                await send_telegram_message(chat_id, f"\U0001f514 التنبيهات: {status}", token=config.TOKEN)

            elif what == "summary":
                state.daily_summary_enabled = not state.daily_summary_enabled
                save_settings()
                status = "\u2705 مفعّل" if state.daily_summary_enabled else "\u274c مُوقف"
                await send_telegram_message(chat_id, f"\U0001f4c5 الملخص اليومي: {status}", token=config.TOKEN)

            else:
                await send_telegram_message(chat_id, f"\u274c خيار غير معروف: {what}", token=config.TOKEN)

        # ─── /shutdown ─── (الملك فقط)
        elif command == "/shutdown":
            if not is_owner(chat_id):
                return
            state.bot_shutdown = True
            save_settings()
            await send_telegram_message(chat_id, "\U0001f6d1 البوت متوقف. /restart لإعادة التشغيل.", token=config.TOKEN)

        # ─── /restart ─── (الملك فقط)
        elif command == "/restart":
            if not is_owner(chat_id):
                return
            state.bot_shutdown = False
            state.bot_resume_time = time.time()
            save_settings()
            await send_telegram_message(chat_id, "\u2705 تم إعادة تشغيل البوت.", token=config.TOKEN)

        # ─── /summary ─── (الملك فقط — إرسال ملخص فوري)
        elif command == "/summary":
            if not is_owner(chat_id):
                return
            msg = build_daily_summary()
            await send_telegram_message(chat_id, msg, token=config.TOKEN)

    except Exception as e:
        log.error(f"handle_update error: {e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════
# 🔄 Polling Loop
# ═══════════════════════════════════════════════════════════
async def polling_loop(config: BotConfig, state: BotState):
    """حلقة polling لاستقبال الأوامر"""
    log.info("\U0001f50d Polling loop started")
    offset = 0

    while True:
        try:
            if config.RENDER_URL:
                # في Render نستخدم webhook، لا polling
                await asyncio.sleep(60)
                continue

            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{config.TOKEN}/getUpdates"
                params = {"offset": offset, "timeout": 30, "allowed_updates": ["message"]}
                async with session.get(url, params=params, timeout=ClientTimeout(total=35)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            for update in data.get("result", []):
                                offset = update["update_id"] + 1
                                await handle_update(update, config, state)
        except Exception as e:
            log.warning(f"Polling error: {e}")
            await asyncio.sleep(5)


# ═══════════════════════════════════════════════════════════
# 🌐 Flask Webhook (لـ Render)
# ═══════════════════════════════════════════════════════════
_flask_app = None

def create_flask_app(config: BotConfig, state: BotState):
    """إنشاء تطبيق Flask للـ webhook"""
    global _flask_app
    from flask import Flask, request, jsonify

    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "bot": "Whale News Bot v2.0"})

    @app.route(f"/webhook/{config.TOKEN}", methods=["POST"])
    def webhook():
        """استقبال التحديثات من Telegram"""
        try:
            update = request.get_json(force=True)
            if update:
                # معالجة غير متزامنة في event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(handle_update(update, config, state))
                    else:
                        loop.run_until_complete(handle_update(update, config, state))
                except RuntimeError:
                    # إنشاء loop جديد إذا لم يكن موجوداً
                    asyncio.run(handle_update(update, config, state))
            return jsonify({"ok": True})
        except Exception as e:
            log.error(f"Webhook error: {e}")
            return jsonify({"ok": False}), 500

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "running",
            "hashes": len(state.sent_news_hashes),
            "queue": message_queue.size(),
            "shutdown": state.bot_shutdown,
        })

    _flask_app = app
    return app


async def run_flask(config: BotConfig, state: BotState):
    """تشغيل Flask في thread منفصل"""
    if not config.RENDER_URL:
        return

    log.info(f"\U0001f310 Starting Flask webhook on port {config.PORT}")

    app = create_flask_app(config, state)

    # تعيين webhook
    try:
        webhook_url = f"{config.RENDER_URL}/webhook/{config.TOKEN}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{config.TOKEN}/setWebhook",
                json={"url": webhook_url, "allowed_updates": ["message"]},
                timeout=ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    log.info(f"\u2705 Webhook set: {webhook_url}")
                else:
                    log.warning(f"\u26a0\ufe0f Webhook set failed: {data}")
    except Exception as e:
        log.warning(f"Webhook setup error: {e}")

    # تشغيل Flask في thread
    import threading
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=config.PORT, debug=False, use_reloader=False),
        daemon=True,
    ).start()


# ═══════════════════════════════════════════════════════════
# 🔍 News Scanner (Async)
# ═══════════════════════════════════════════════════════════
async def scan_news_loop(config: BotConfig, state: BotState, translator: TranslationManager):
    """حلقة فحص الأخبار"""
    log.info("\U0001f50d News scanner started")
    await asyncio.sleep(10)  # انتظار بدء التشغيل

    while True:
        try:
            if state.bot_shutdown:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            if not state.auto_alerts_enabled:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            log.info("\U0001f50d Scanning news...")

            # جلب الأخبار
            news = await fetch_all_news(max_concurrent=5)
            if not news:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # فلترة
            filtered = filter_news_items(news, min_score=1.5)

            now = time.time()
            alerts_sent = 0
            important_found = 0
            scan_categories = []

            for item in filtered[:MAX_NEWS_PER_SCAN]:
                # Safety Mode: رفض الأخبار القديمة
                if item.timestamp > 0 and not _is_safe_timestamp(item.timestamp):
                    log.debug(f"Safety: rejecting old news {item.title[:50]}...")
                    state.sent_news_hashes.add(item.hash)
                    continue

                # فحص العمر
                if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
                    state.sent_news_hashes.add(item.hash)
                    continue

                # فحص الإرسال السابق
                if item.hash in state.sent_news_hashes:
                    continue

                # فحص cooldown
                if item.hash in state.last_alerts_hashes:
                    if now - state.last_alerts_hashes[item.hash] < 21600:  # 6 ساعات
                        continue

                # ─── مسار الأخبار العربية ───
                if item.lang == "ar":
                    news_text = f"{item.title} {item.summary}".lower()
                    has_ar_critical = any(kw in news_text for kw in AR_CRITICAL_KEYWORDS)
                    has_ar_rejection = any(kw in news_text for kw in AR_REJECTION_KEYWORDS)
                    has_crypto = any(kw in news_text for kw in CRYPTO_CONTEXT_KEYWORDS)

                    if has_ar_critical and not has_ar_rejection and has_crypto:
                        item.title_ar = item.title
                        item.summary_ar = item.summary
                    else:
                        state.sent_news_hashes.add(item.hash)
                        continue
                else:
                    # ─── مسار الأخبار الإنجليزية: ترجمة ───
                    await translator.translate_item(item)
                    if not item.title_ar:
                        continue

                # تنسيق
                msg = format_news_item(item)
                if not msg:
                    continue

                important_found += 1
                scan_categories.extend(item.categories)

                # إرسال
                state.sent_news_hashes.add(item.hash)
                state.last_alerts_hashes[item.hash] = now

                # تحديد الأولوية
                is_breaking = "breaking" in item.categories or "hack" in item.categories
                priority = 3 if is_breaking else 2

                # broadcast
                await broadcast_alert(msg, config, state, image_url=item.image, priority=priority)

                alerts_sent += 1
                log.info(f"  \u2709\ufe0f {item.title[:60]}...")

            # تحديث الإحصائيات
            update_daily_stats(
                alerts_sent=alerts_sent,
                important=important_found,
                total=len(news),
                categories=scan_categories,
            )

            log.info(f"\U0001f4ca Scan complete: {len(news)} fetched, {len(filtered)} important, {alerts_sent} sent")

            # حفظ دوري
            save_sent_news()

            # ETF flows (مرة واحدة يومياً)
            try:
                etf = await fetch_etf_flows()
                if etf:
                    etf_hash = f"etf_{etf['date']}"
                    if etf_hash not in state.sent_news_hashes:
                        state.sent_news_hashes.add(etf_hash)
                        msg = format_etf_flows(etf)
                        await broadcast_alert(msg, config, state, priority=1)
            except Exception as e:
                log.warning(f"ETF flows error: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Scan loop error: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════
# 📅 Daily Summary
# ═══════════════════════════════════════════════════════════
_daily_stats = {
    "alerts_sent": 0,
    "important_found": 0,
    "total_scanned": 0,
    "categories": {},
    "date": datetime.now(tz).strftime("%Y-%m-%d"),
}


def update_daily_stats(alerts_sent: int = 0, important: int = 0, total: int = 0, categories: List[str] = None):
    """تحديث الإحصائيات"""
    global _daily_stats
    today = datetime.now(tz).strftime("%Y-%m-%d")

    if _daily_stats["date"] != today:
        _daily_stats = {
            "alerts_sent": 0, "important_found": 0, "total_scanned": 0,
            "categories": {}, "date": today,
        }

    _daily_stats["alerts_sent"] += alerts_sent
    _daily_stats["important_found"] += important
    _daily_stats["total_scanned"] += total

    if categories:
        for cat in categories:
            _daily_stats["categories"][cat] = _daily_stats["categories"].get(cat, 0) + 1


async def daily_summary_loop(config: BotConfig, state: BotState):
    """حلقة الملخص اليومي"""
    log.info("\U0001f4c5 Daily summary loop started")
    last_summary_date = None

    while True:
        try:
            if not state.daily_summary_enabled:
                await asyncio.sleep(300)
                continue

            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")

            if now.hour == SUMMARY_HOUR and now.minute >= SUMMARY_MINUTE and last_summary_date != today:
                msg = build_daily_summary()

                await broadcast_alert(msg, config, state, priority=1, skip_users=True)

                last_summary_date = today
                log.info("\U0001f4c5 Daily summary sent")
                await asyncio.sleep(300)
                continue

            await asyncio.sleep(60)

        except Exception as e:
            log.warning(f"Daily summary error: {e}")
            await asyncio.sleep(60)


def build_daily_summary() -> str:
    """بناء الملخص اليومي"""
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M")

    msg = f"\U0001f4ca <b>\u0627\u0644\u0645\u0644\u062e\u0635 \u0627\u0644\u064a\u0648\u0645\u064a \u0644\u0644\u0623\u062e\u0628\u0627\u0631</b>\n"
    msg += "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
    msg += f"\U0001f4c5 \u0627\u0644\u062a\u0627\u0631\u064a\u062e: {today}\n"
    msg += f"\u23f0 \u0627\u0644\u0648\u0642\u062a: {now_str}\n\n"
    msg += "\U0001f4c8 <b>\u0625\u062d\u0635\u0627\u0626\u064a\u0627\u062a \u0627\u0644\u064a\u0648\u0645:</b>\n"
    msg += f"   \U0001f514 \u062a\u0646\u0628\u064a\u0647\u0627\u062a \u0645\u064f\u0631\u0633\u064e\u0644\u0629: <b>{_daily_stats['alerts_sent']}</b>\n"
    msg += f"   \U0001f4f0 \u0623\u062e\u0628\u0627\u0631 \u0645\u0647\u0645\u0629: <b>{_daily_stats['important_found']}</b>\n"
    msg += f"   \U0001f4ca \u0625\u062c\u0645\u0627\u0644\u064a \u0641\u064f\u062d\u0635\u062a: <b>{_daily_stats['total_scanned']}</b>\n\n"

    cats = _daily_stats["categories"]
    if cats:
        msg += "\U0001f3f7\ufe0f <b>\u062a\u0648\u0632\u064a\u0639 \u0627\u0644\u0641\u0626\u0627\u062a:</b>\n"
        sorted_cats = sorted(cats.items(), key=lambda x: -x[1])
        for cat, count in sorted_cats:
            if count > 0:
                icon = {"breaking": "\U0001f6a8", "hack": "\u26a0\ufe0f", "etf": "\U0001f4ca",
                        "whale": "\U0001f40b", "tech": "\U0001f527", "market": "\U0001f4c8"}.get(cat, "\U0001f4f0")
                msg += f"   {icon} {cat}: {count}\n"

    msg += "\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    msg += "\U0001f916 <i>\u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0647\u0630\u0627 \u0627\u0644\u0645\u0644\u062e\u0635 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b</i>"
    return msg


# ═══════════════════════════════════════════════════════════
# 🚀 Main Entry Point
# ═══════════════════════════════════════════════════════════
async def run_bot(config: BotConfig, state: BotState):
    """تشغيل البوت"""
    errors = config.validate()
    if errors:
        for error in errors:
            log.error(error)
        return

    # تحميل البيانات
    load_sent_news()
    load_settings()
    refresh_allowed()
    _init_safety_mode(state)

    translator = TranslationManager(config)

    log.info("=" * 60)
    log.info("\U0001f916 Whale News Bot v2.0 - Starting")
    log.info("=" * 60)
    log.info(f"\U0001f4e1 Sources: {len(config.__class__.__name__)}")

    # تشغيل المهام
    tasks = [
        asyncio.create_task(message_consumer(config, state)),
        asyncio.create_task(scan_news_loop(config, state, translator)),
        asyncio.create_task(daily_summary_loop(config, state)),
        asyncio.create_task(polling_loop(config, state)),
    ]

    # Flask webhook (إذا كان Render)
    if config.RENDER_URL:
        await run_flask(config, state)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("\U0001f6d1 Bot shutting down...")
    finally:
        save_sent_news(force=True)
        await session_manager.close()


# ═══════════════════════════════════════════════════════════
# 🔄 One-shot Mode (GitHub Actions)
# ═══════════════════════════════════════════════════════════
async def run_oneshot(config: BotConfig, state: BotState):
    """وضع التشغيل لمرة واحدة"""
    errors = config.validate()
    if errors:
        for error in errors:
            print(f"\u274c {error}")
        return

    # تحميل البيانات
    load_sent_news()
    load_settings()
    refresh_allowed()
    _init_safety_mode(state)

    translator = TranslationManager(config)

    print("=" * 60)
    print("\U0001f916 Running in one-shot mode")
    print("=" * 60)

    try:
        # جلب الأخبار
        news = await fetch_all_news(max_concurrent=5)
        if not news:
            print("\u26a0\ufe0f No news available")
            return

        filtered = filter_news_items(news, min_score=1.5)
        now = time.time()
        alerts_sent = 0

        for item in filtered[:MAX_NEWS_PER_SCAN]:
            # Safety Mode
            if item.timestamp > 0 and not _is_safe_timestamp(item.timestamp):
                state.sent_news_hashes.add(item.hash)
                continue

            if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
                continue

            if item.hash in state.sent_news_hashes:
                continue

            # ترجمة
            if item.lang == "ar":
                item.title_ar = item.title
                item.summary_ar = item.summary
            else:
                await translator.translate_item(item)
                if not item.title_ar:
                    continue

            msg = format_news_item(item)
            if not msg:
                continue

            # إرسال
            state.sent_news_hashes.add(item.hash)

            if state.is_channel_enabled(config):
                await send_telegram_message(config.CHANNEL_ID, msg, item.image, config.TOKEN)
            await send_telegram_message(config.CHAT_ID, msg, item.image, config.TOKEN)

            alerts_sent += 1
            print(f"  \u2709\ufe0f {item.title[:60]}...")
            await asyncio.sleep(1.5)

        # ETF
        try:
            etf = await fetch_etf_flows()
            if etf:
                etf_hash = f"etf_{etf['date']}"
                if etf_hash not in state.sent_news_hashes:
                    state.sent_news_hashes.add(etf_hash)
                    msg = format_etf_flows(etf)
                    if state.is_channel_enabled(config):
                        await send_telegram_message(config.CHANNEL_ID, msg, None, config.TOKEN)
                    await send_telegram_message(config.CHAT_ID, msg, None, config.TOKEN)
                    print(f"  \U0001f4ca ETF flows: {etf['date']}")
        except Exception as e:
            print(f"  \u26a0\ufe0f ETF error: {e}")

        print("=" * 60)
        print(f"\U0001f4ca Results: {len(news)} fetched, {len(filtered)} important, {alerts_sent} sent")
        print("=" * 60)

    finally:
        # 🔧 حفظ فوري قبل الخروج
        save_sent_news(force=True)
        print("\U0001f4be Saved sent_news hashes before exit")
        await session_manager.close()