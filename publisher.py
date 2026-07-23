"""
🐋 Whale News Bot v3 - ناشر الرسائل
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
إرسال الرسائل المنسّقة إلى تيليجرام.

المكوّنات:
  - MessageQueue: طابور أولوية غير متزامن
  - send_to_telegram: إرسال رسالة واحدة مع rate limit و circuit breaker
  - add_watermark: إضافة علامة مائية على الصور
"""

import asyncio
import io
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from models import OutgoingMessage
from config import cfg, TELEGRAM_RATE_LIMITER, TELEGRAM_CB, log


# ═══════════════════════════════════════════════════════════
# 🌐 إعدادات Telegram API
# ═══════════════════════════════════════════════════════════
_TELEGRAM_BASE_URL = f"https://api.telegram.org/bot{cfg.TOKEN}/"
_SEND_PHOTO_URL = f"{_TELEGRAM_BASE_URL}sendPhoto"
_SEND_MESSAGE_URL = f"{_TELEGRAM_BASE_URL}sendMessage"

# حد أقصى لحجم الصورة المُرسلة (10 MB)
_MAX_PHOTO_BYTES = 10 * 1024 * 1024

# حد أقصى لطول نص الـ caption (1024 حرف)
_MAX_CAPTION_LENGTH = 1024


# ═══════════════════════════════════════════════════════════
# 🌊 طابور الرسائل (MessageQueue)
# ═══════════════════════════════════════════════════════════

class MessageQueue:
    """
    طابور أولوية غير متزامن لإرسال الرسائل إلى تيليجرام.
    
    - الأولوية: رقم أصغر = أسرع إرسال (الأخبار العاجلة أولاً)
    - يتبع الـ rate limiting و circuit breaker
    - يتتبع إحصائيات: مُرسلة، فاشلة، أُعيد محاولتها
    """

    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._consumer_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._counter: int = 0  # عدّاد لضمان فريدة المقارنة في Priority Queue

        # ── إحصائيات ──
        self._sent: int = 0
        self._failed: int = 0
        self._retried: int = 0

    # ───────────────────────────────────────────────────────
    # 📊 إحصائيات
    # ───────────────────────────────────────────────────────
    @property
    def stats(self) -> Dict[str, int]:
        """إحصائيات الطابور الحالية"""
        return {
            "sent": self._sent,
            "failed": self._failed,
            "retried": self._retried,
            "queued": self._queue.qsize(),
        }

    def stats_summary(self) -> str:
        """ملخص إحصائيات قابل للقراءة"""
        s = self.stats
        return (
            f"📨 الطابور: مُرسل={s['sent']} | فاشل={s['failed']} | "
            f"أُعيدت محاولة={s['retried']} | في الانتظار={s['queued']}"
        )

    # ───────────────────────────────────────────────────────
    # 📥 إضافة رسالة
    # ───────────────────────────────────────────────────────
    async def put(self, msg: OutgoingMessage) -> None:
        """
        إضافة رسالة إلى الطابور.
        
        Args:
            msg: الرسالة الجاهزة للنشر
        """
        self._counter += 1
        # العنصر: (أولوية, وقت الإنشاء, عدّاد فريد, الرسالة)
        # الأولوية الأصغر = أسرع، وقت الإنشاء الأقدم = أسرع
        await self._queue.put((msg.priority, msg.created_at, self._counter, msg))
        log.debug(f"📥 أُضيفت رسالة للطابور | أولوية={msg.priority} | في الانتظار={self._queue.qsize()}")

    # ───────────────────────────────────────────────────────
    # 🔄 تشغيل المستهلك (Consumer)
    # ───────────────────────────────────────────────────────
    async def start_consumer(self) -> None:
        """
        بدء مهمة استهلاك الرسائل في الخلفية.
        يُرسل الرسائل واحداً تلو الأخرى مع احترام rate limit.
        """
        if self._running:
            log.warning("⚠️ المستهلك يعمل بالفعل")
            return

        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        log.info("🚀 بدء مستهلك الطابور")

    async def _consume_loop(self) -> None:
        """حلقة استهلاك الرسائل الرئيسية"""
        while self._running:
            try:
                # انتظار رسالة من الطابور (timeout لتتمكن من التحقق من _running)
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                _, _, _, msg = item
                self._queue.task_done()

                # ── معالجة الصورة: إضافة علامة مائية إن وُجدت ──
                if msg.image_url and not msg.image_data:
                    try:
                        watermarked = await add_watermark(msg.image_url)
                        if watermarked:
                            msg.image_data = watermarked
                        else:
                            log.debug(f"🖼️ فشل إضافة العلامة المائية — إرسال بدون تعديل")
                    except Exception as e:
                        log.warning(f"⚠️ خطأ في العلامة المائية: {e}")

                # ── الإرسال ──
                success = await send_to_telegram(
                    text=msg.text,
                    chat_id=msg.chat_id,
                    image_url=msg.image_url if not msg.image_data else None,
                    image_data=msg.image_data,
                )

                if success:
                    self._sent += 1
                    log.info(f"✅ أُرسلت رسالة بنجاح | أولوية={msg.priority} | المجموع={self._sent}")
                else:
                    self._failed += 1
                    log.warning(
                        f"❌ فشل إرسال رسالة | أولوية={msg.priority} | "
                        f"محاولات={msg.retry_count + 1}/{msg.max_retries}"
                    )

                    # ── إعادة المحاولة ──
                    if msg.retry_count < msg.max_retries - 1:
                        msg.retry_count += 1
                        self._retried += 1
                        # تأخير تصاعدي قبل إعادة المحاولة
                        delay = 2 ** msg.retry_count  # 2s, 4s, 8s
                        log.info(f"🔄 إعادة المحاولة {msg.retry_count}/{msg.max_retries} بعد {delay} ثانية")
                        await asyncio.sleep(delay)
                        await self.put(msg)

            except asyncio.CancelledError:
                log.info("🛑 إلغاء مهمة المستهلك")
                break
            except Exception as e:
                log.error(f"💥 خطأ غير متوقع في مستهلك الطابور: {e}", exc_info=True)
                # انتظار قصير لتجنب حلقة الأخطاء المكثّفة
                await asyncio.sleep(5)

    # ───────────────────────────────────────────────────────
    # 🛑 إيقاف المستهلك
    # ───────────────────────────────────────────────────────
    async def stop(self) -> Dict[str, int]:
        """
        إيقاف مستهلك الطابور بأمان.
        ينتظر حتى يُرسل كل ما في الطابور أو ينتهي الوقت.
        
        Returns:
            إحصائيات الطابور النهائية
        """
        log.info(f"🛑 إيقاف الطابور | {self.stats_summary()}")
        self._running = False

        if self._consumer_task and not self._consumer_task.done():
            # انتظار حتى ينتهي الطابور أو 10 ثوانٍ كحد أقصى
            try:
                await asyncio.wait_for(self._consumer_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._consumer_task.cancel()
                try:
                    await self._consumer_task
                except asyncio.CancelledError:
                    pass
                log.warning("⏰ انتهى وقت الانتظار — تم إلغاء المستهلك")

        remaining = self._queue.qsize()
        if remaining > 0:
            log.warning(f"📦 {remaining} رسائل لم تُرسل عند الإيقاف")

        final_stats = self.stats
        log.info(f"📊 الإحصائيات النهائية: {self.stats_summary()}")
        return final_stats


# ═══════════════════════════════════════════════════════════
# 📤 إرسال إلى تيليجرام
# ═══════════════════════════════════════════════════════════

async def send_to_telegram(
    text: str,
    chat_id: str,
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> bool:
    """
    إرسال رسالة إلى تيليجرام.

    1. احترام rate limit عبر TELEGRAM_RATE_LIMITER
    2. حماية من الأعطال عبر TELEGRAM_CB (circuit breaker)
    3. محاولة الإرسال كصورة مع caption أولاً
    4. fallback إلى رسالة نصية عادية
    5. معالجة خطأ 429 (تجاوز معدل الطلبات)

    Args:
        text: نص الرسالة
        chat_id: معرّف المحادثة / القناة
        image_url: رابط الصورة (يُحمّل ويُرسل)
        image_data: بيانات الصورة الجاهزة (bytes)

    Returns:
        True إذا أُرسلت بنجاح
    """
    if not text or not chat_id:
        log.error("❌ نص أو chat_id فارغ — لا يمكن الإرسال")
        return False

    # ── احترام rate limit ──
    await TELEGRAM_RATE_LIMITER.acquire()

    # ── محاولة الإرسال عبر circuit breaker ──
    try:
        return await TELEGRAM_CB.call(_do_send, text, chat_id, image_url, image_data)
    except RuntimeError as e:
        # circuit breaker مفتوح
        log.error(f"🔌 {e}")
        return False
    except Exception as e:
        log.error(f"💥 خطأ في send_to_telegram: {e}", exc_info=True)
        return False


async def _do_send(
    text: str,
    chat_id: str,
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> bool:
    """
    التنفيذ الفعلي للإرسال — يُستدعى عبر circuit breaker.
    """
    has_image = bool(image_data) or bool(image_url)

    # ── المحاولة الأولى: إرسال كصورة مع caption ──
    if has_image:
        photo_sent = await _send_as_photo(text, chat_id, image_url, image_data)
        if photo_sent:
            return True
        log.warning("⚠️ فشل إرسال الصورة — fallback إلى نص عادي")

    # ─ـ المحاولة الثانية: إرسال كنص عادي ──
    text_sent = await _send_as_text(text, chat_id)
    return text_sent


async def _send_as_photo(
    text: str,
    chat_id: str,
    image_url: Optional[str] = None,
    image_data: Optional[bytes] = None,
) -> bool:
    """
    إرسال رسالة كصورة مع caption.
    
    يدعم:
    - image_data: bytes جاهزة (بعد watermark)
    - image_url: رابط يُحمّل أولاً
    """
    caption = text[:_MAX_CAPTION_LENGTH] if text else ""

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            form = aiohttp.FormData()
            form.add_field("chat_id", chat_id)
            form.add_field("parse_mode", "HTML")

            if image_data:
                # إرسال الصورة من bytes مباشرة
                form.add_field(
                    "photo",
                    io.BytesIO(image_data),
                    content_type="image/jpeg",
                    filename="photo.jpg",
                )
            elif image_url:
                # تحميل الصورة من الرابط ثم إرسالها
                try:
                    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            log.warning(f"⚠️ فشل تحميل الصورة: HTTP {resp.status}")
                            return False
                        img_bytes = await resp.read()
                        if len(img_bytes) > _MAX_PHOTO_BYTES:
                            log.warning(f"⚠️ حجم الصورة كبير جداً: {len(img_bytes)} bytes")
                            return False
                        form.add_field(
                            "photo",
                            io.BytesIO(img_bytes),
                            content_type="image/jpeg",
                            filename="photo.jpg",
                        )
                except Exception as e:
                    log.warning(f"⚠️ خطأ في تحميل الصورة من {image_url}: {e}")
                    return False

            if caption:
                form.add_field("caption", caption)

            async with session.post(_SEND_PHOTO_URL, data=form) as resp:
                result = await resp.json()

                if result.get("ok"):
                    log.debug(f"📸 أُرسلت كصورة بنجاح | msg_id={result.get('result', {}).get('message_id')}")
                    return True
                else:
                    error_code = result.get("error_code", 0)
                    error_desc = result.get("description", "مجهول")

                    # معالجة خطأ 429 (تجاوز معدل الطلبات)
                    if error_code == 429:
                        retry_after = int(result.get("parameters", {}).get("retry_after", 5))
                        log.warning(f"⏳ Telegram rate limit — انتظار {retry_after} ثانية")
                        await asyncio.sleep(retry_after)
                        # إعادة المحاولة مرة واحدة فقط
                        async with session.post(_SEND_PHOTO_URL, data=form) as retry_resp:
                            retry_result = await retry_resp.json()
                            if retry_result.get("ok"):
                                log.debug(f"📸 نجحت إعادة المحاولة كصورة")
                                return True
                            log.warning(f"❌ فشلت إعادة محاولة الصورة: {retry_result.get('description')}")
                            return False

                    log.warning(f"❌ فشل إرسال الصورة: [{error_code}] {error_desc}")
                    return False

    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"❌ خطأ في _send_as_photo: {e}")
        return False


async def _send_as_text(text: str, chat_id: str) -> bool:
    """
    إرسال رسالة كنص عادي.
    """
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(_SEND_MESSAGE_URL, json=payload) as resp:
                result = await resp.json()

                if result.get("ok"):
                    log.debug(f"💬 أُرسلت كنص بنجاح | msg_id={result.get('result', {}).get('message_id')}")
                    return True
                else:
                    error_code = result.get("error_code", 0)
                    error_desc = result.get("description", "مجهول")

                    # معالجة خطأ 429
                    if error_code == 429:
                        retry_after = int(result.get("parameters", {}).get("retry_after", 5))
                        log.warning(f"⏳ Telegram rate limit (text) — انتظار {retry_after} ثانية")
                        await asyncio.sleep(retry_after)
                        async with session.post(_SEND_MESSAGE_URL, json=payload) as retry_resp:
                            retry_result = await retry_resp.json()
                            if retry_result.get("ok"):
                                log.debug(f"💬 نجحت إعادة محاولة النص")
                                return True
                            log.warning(f"❌ فشلت إعادة محاولة النص: {retry_result.get('description')}")
                            return False

                    # خطأ 400: مشكلة في HTML — محاولة بدون parse_mode
                    if error_code == 400:
                        log.warning(f"⚠️ مشكلة HTML — محاولة إرسال بدون تنسيق")
                        plain_payload = {"chat_id": chat_id, "text": text}
                        async with session.post(_SEND_MESSAGE_URL, json=plain_payload) as plain_resp:
                            plain_result = await plain_resp.json()
                            if plain_result.get("ok"):
                                return True
                            log.warning(f"❌ فشل الإرسال حتى بدون تنسيق: {plain_result.get('description')}")
                            return False

                    log.warning(f"❌ فشل إرسال النص: [{error_code}] {error_desc}")
                    return False

    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"❌ خطأ في _send_as_text: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 🖼️ العلامة المائية (Watermark)
# ═══════════════════════════════════════════════════════════

async def add_watermark(image_url: str) -> Optional[bytes]:
    """
    تحميل صورة، تغيير حجمها، وإضافة علامة مائية.

    الخطوات:
    1. تحميل الصورة من الرابط
    2. تغيير الحجم إلى حد أقصى 1200px (مع الحفاظ على النسبة)
    3. إضافة نص "@newscrypto1m" في الزاوية السفلية اليمنى
    4. إرجاع الصورة كـ bytes (JPEG)

    Args:
        image_url: رابط الصورة الأصلية

    Returns:
        bytes الصورة بعد التعديل، أو None عند الفشل
    """
    if not image_url:
        return None

    watermark_text = cfg.WATERMARK_TEXT
    max_dimension = 1200

    try:
        # ── تحميل الصورة ──
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    log.warning(f"⚠️ فشل تحميل الصورة للعلامة المائية: HTTP {resp.status}")
                    return None
                img_bytes = await resp.read()

        # ── معالجة الصورة ──
        img = Image.open(io.BytesIO(img_bytes))

        # تحويل إلى RGB لو كانت PNG بشفافية
        if img.mode in ("RGBA", "P", "LA"):
            # إنشاء خلفية بيضاء لو PNG بشفافية
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])  # alpha كـ mask
                img = background
            else:
                img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # ── تغيير الحجم ──
        orig_w, orig_h = img.size
        if max(orig_w, orig_h) > max_dimension:
            if orig_w > orig_h:
                new_w = max_dimension
                new_h = int(orig_h * (max_dimension / orig_w))
            else:
                new_h = max_dimension
                new_w = int(orig_w * (max_dimension / orig_h))
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # ── إضافة العلامة المائية ──
        draw = ImageDraw.Draw(img)

        # حساب حجم الخط حسب حجم الصورة
        img_w, img_h = img.size
        font_size = max(16, min(36, img_w // 25))

        # محاولة تحميل خط عربي/إنجليزي مناسب
        font = _load_font(font_size)

        # حساب موقع النص في الزاوية السفلية اليمنى
        # ترك هامش 10px من الأسفل واليمين
        margin = 10
        try:
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except (AttributeError, TypeError):
            # PIL قديم — textbbox غير متاح
            text_w, text_h = draw.textsize(watermark_text, font=font)

        x = img_w - text_w - margin
        y = img_h - text_h - margin

        # ── رسم خلفية شبه شفافة خلف النص ──
        padding = 4
        bg_bbox = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)

        # إنشاء طبقة شبه شفافة
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(bg_bbox, fill=(0, 0, 0, 120))  # أسود شبه شفاف

        # دمج الطبقة
        img_rgba = img.convert("RGBA")
        img_rgba = Image.alpha_composite(img_rgba, overlay)
        img = img_rgba.convert("RGB")

        # ── رسم النص ──
        draw = ImageDraw.Draw(img)
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 230))

        # ── تحويل إلى bytes ──
        output_buffer = io.BytesIO()
        img.save(output_buffer, format="JPEG", quality=92)
        img_bytes = output_buffer.getvalue()

        log.debug(f"🖼️ تمت إضافة العلامة المائية | حجم={len(img_bytes)} bytes | أبعاد={img.size}")
        return img_bytes

    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"⚠️ فشل إضافة العلامة المائية: {e}")
        return None


def _load_font(font_size: int):
    """
    تحميل خط مناسب للعلامة المائية.
    يحاول استخدام خط DejaVu أولاً، ثم الخط الافتراضي.
    """
    font_paths = [
        # مسارات شائعة لخطوط DejaVu في Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        # خطوط macOS
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        # خطوط Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for path in font_paths:
        try:
            return ImageFont.truetype(path, font_size)
        except (OSError, IOError):
            continue

    # الخط الافتراضي — نص أصغر قليلاً لأنه قد لا يكون واضحاً
    log.debug("🔤 استخدام الخط الافتراضي للعلامة المائية")
    try:
        return ImageFont.truetype(font_size=font_size)
    except (OSError, AttributeError):
        return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════
# 🌐 نسخة عامة من MessageQueue
# ═══════════════════════════════════════════════════════════
# يمكن إنشاء نسخة واحدة و مشاركتها عبر المشروع
message_queue = MessageQueue()
