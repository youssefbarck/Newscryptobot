"""
🤖 Whale News Bot v2.0 - Telegram Bot (Async)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
بوت متقدم مع queues، rate limiting، و image processing فعال
"""

import os, re, time, json, asyncio, hashlib
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientTimeout

from config import (
    log, BotConfig, BotState, TELEGRAM_RATE_LIMITER, TELEGRAM_CB,
    MAX_NEWS_PER_SCAN, MAX_NEWS_AGE, SCAN_INTERVAL, NEWS_SOURCES,
    SUMMARY_HOUR, SUMMARY_MINUTE, tz,
)
import dedup
from filters import NewsItem, filter_news_items, is_complete_news
from rss import fetch_all_news, fetch_etf_flows, session_manager
from translate import TranslationManager, translation_cache
from source_quality import source_quality


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
# 🔍 Final Editorial Review (آخر طبقة أمان قبل الإرسال)
# ═══════════════════════════════════════════════════════════

# أسماء مصادر محظورة — لا يجب أن تظهر في الخبر المنشور
_BLOCKED_SOURCES = {
    "benzinga", "coindesk", "cointelegraph", "beincrypto",
    "decrypt", "cryptobriefing", "blockworks", "thedefiant",
    "bitcoinist", "cryptopotato", "newsbtc", "u.today",
}

# وسوم عربية يجب إزالتها من النص النهائي
_ARABIC_MARKERS = re.compile(
    r'(?:\s*)?'
    r'(?:الخبر|المصدر|كتابة|تحرير|نشر|إعداد|ترجمة)'
    r'(?:\s*[::\-])?\s*.*$',
    re.MULTILINE
)


def final_editorial_review(text: str) -> Optional[str]:
    """آخر طبقة أمان قبل إرسال الخبر إلى تيليجرام.

    وظائفها:
    1. إزالة أي تكرار بقي بعد الترجمة
    2. إزالة أي جملة فارغة أو تكرار العنوان في النص
    3. حذف أسماء المصادر الإنجليزية إن تسربت
    4. توحيد الهاشتاغ (حرف كبير، بدون تكرار)
    5. حذف الوسوم العربية الزائدة
    6. التأكد من بنية صحيحة: عنوان واحد + نص
    """
    if not text or not text.strip():
        return None

    lines = text.strip().split("\n")
    cleaned = []
    seen_lines = set()
    headline = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # لا أكثر من سطر فارغ متتالي
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        # 1. حذف أسماء المصادر الإنجليزية
        lower = stripped.lower()
        if any(src in lower for src in _BLOCKED_SOURCES):
            # لا تحذف السطر كله — فقط نظّفه من اسم المصدر
            for src in _BLOCKED_SOURCES:
                stripped = re.sub(rf'\b{re.escape(src)}\b', '', stripped, flags=re.IGNORECASE).strip()
            if not stripped:
                continue

        # 2. حذف الوسوم العربية (المصدر: ... / كتابة: ...)
        stripped = _ARABIC_MARKERS.sub('', stripped).strip()
        if not stripped:
            continue

        # 3. إزالة التكرار
        norm = re.sub(r'\s+', ' ', stripped).lower()
        if norm in seen_lines:
            continue
        seen_lines.add(norm)

        # 4. كشف العنوان (أول سطر فيه رمز)
        if headline is None and (stripped.startswith("🔵") or stripped.startswith("🚨") or stripped.startswith("🔴") or stripped.startswith("⚪") or stripped.startswith("📊")):
            headline = stripped
            cleaned.append(stripped)
            continue

        # 5. حذف تكرار العنوان في النص
        if headline:
            h_clean = headline.lstrip("🔵🚨🔴⚪📊 ").strip()
            s_clean = stripped.lstrip("0123456789.-) ").strip()
            if h_clean.lower() == s_clean.lower():
                continue
            # فحص احتواء جزئي (أكثر من 80% تطابق)
            shorter = min(len(h_clean), len(s_clean))
            if shorter > 10:
                common = sum(a == b for a, b in zip(h_clean.lower(), s_clean.lower()))
                if common / shorter > 0.8:
                    continue

        cleaned.append(stripped)

    # 6. توحيد الهاشتاغات في النهاية
    result_lines = []
    hashtags = []
    for line in cleaned:
        if re.match(r'^#\w+', line.strip()):
            tag = line.strip().upper()  # توحيد: أحرف كبيرة
            if tag not in hashtags:
                hashtags.append(tag)
            continue
        result_lines.append(line)

    # إضافة الهاشتاغات الموحدة
    if hashtags:
        if result_lines and result_lines[-1] != "":
            result_lines.append("")
        result_lines.extend(hashtags)

    result = "\n".join(result_lines).strip()

    # 7. فحص نهائي: يجب أن يكون هناك عنوان
    if not headline and not result:
        return None

    # 8. حذف سطور فارغة متعددة
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result if len(result) > 10 else None


# ═══════════════════════════════════════════════════════════
# 📝 News Formatting
# ═══════════════════════════════════════════════════════════
def format_news_item(item: NewsItem, show_summary: bool = True) -> Optional[str]:
    """تنسيق الخبر للإرسال — يستخدم news_format و importance من JSON"""
    title_ar = item.title_ar or item.title
    summary_ar = item.summary_ar or item.summary

    # فحص الجودة
    if not title_ar or title_ar == item.title:
        return None

    # رمز الأهمية
    importance = getattr(item, 'importance', 'medium') or 'medium'
    emoji_map = {"breaking": "🚨", "high": "🔴", "medium": "🔵", "low": "⚪"}
    emoji = emoji_map.get(importance, "🔵")

    # نوع التنسيق
    news_format = getattr(item, 'news_format', 'standard') or 'standard'

    # بناء الرسالة حسب نوع التنسيق
    if news_format == "economic" and summary_ar:
        prefix = "🚨" if importance == "breaking" else "📊"
        msg = f"{prefix} {title_ar.strip()}\n\n{summary_ar.strip()}"
    elif news_format == "bullets" and summary_ar:
        msg = f"{emoji} {title_ar.strip()}\n\n{summary_ar.strip()}"
    else:
        msg = f"{emoji} {title_ar.strip()}"
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
                    msg += f"\n\n{clean_summary}"

    # إضافة العملات إن وُجدت (فريد، case-insensitive)
    if item.coins:
        seen = set()
        unique_coins = []
        for c in item.coins:
            cl = c.lower()
            if cl not in seen:
                seen.add(cl)
                unique_coins.append(c)
        coins_str = " ".join([f"#{c}" for c in unique_coins[:5]])
        msg += f"\n\n{coins_str}"

    msg += "\n\n✉️ @newscrypto1m"

    return msg


def format_etf_flows(etf_data: Dict) -> str:
    """تنسيق بيانات ETF"""
    btc_sign = "+" if etf_data['btc_total'] >= 0 else ""
    eth_sign = "+" if etf_data['eth_total'] >= 0 else ""
    btc_emoji = "📈" if etf_data['btc_total'] >= 0 else "📉"
    eth_emoji = "📈" if etf_data['eth_total'] >= 0 else "📉"

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
    msg += "\n\n✉️ @newscrypto1m"

    return msg


# ═══════════════════════════════════════════════════════════
# 🔍 News Scanner (Async)
# ═══════════════════════════════════════════════════════════
async def scan_news_loop(config: BotConfig, state: BotState, translator: TranslationManager):
    """حلقة فحص الأخبار"""
    log.info("🔍 News scanner started")
    await asyncio.sleep(10)  # انتظار بدء التشغيل

    while True:
        try:
            if state.bot_shutdown:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            if not state.auto_alerts_enabled:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            log.info("🔍 Scanning news...")

            # جلب الأخبار
            news = await fetch_all_news(max_concurrent=5)
            if not news:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # فلترة
            filtered = filter_news_items(news, min_score=1.5)

            now = time.time()
            alerts_sent = 0

            for item in filtered[:MAX_NEWS_PER_SCAN]:
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

                # ترجمة
                if item.lang == "ar":
                    item.title_ar = item.title
                    item.summary_ar = item.summary
                else:
                    await translator.translate_item(item)
                    if not item.title_ar:
                        continue

                # تنسيق
                msg = format_news_item(item)
                if not msg:
                    continue

                # طبقة الأمان الأخيرة: المراجعة التحريرية النهائية
                msg = final_editorial_review(msg)
                if not msg:
                    log.info(f"   🧹 Blocked by editorial review: {item.title[:60]}")
                    if item.source:
                        source_quality.record_rejection(item.source, "Blocked by editorial review")
                    continue

                # إرسال
                state.sent_news_hashes.add(item.hash)
                state.last_alerts_hashes[item.hash] = now

                # تسجيل نجاح المصدر
                if item.source:
                    source_quality.record_success(item.source)

                # للأولوية: importance هو المصدر الموحد
                imp = getattr(item, 'importance', 'medium') or 'medium'
                priority = 3 if imp in ("breaking", "high") else 2

                # للقناة
                if state.is_channel_enabled(config):
                    await message_queue.put(QueuedMessage(
                        text=msg,
                        image_url=item.image,
                        chat_id=config.CHANNEL_ID,
                        priority=priority,
                    ))

                # للمالك
                await message_queue.put(QueuedMessage(
                    text=msg,
                    image_url=item.image,
                    chat_id=config.CHAT_ID,
                    priority=priority,
                ))

                alerts_sent += 1
                log.info(f"  ✉️ {item.title[:60]}...")

            update_daily_stats(
                alerts_sent=alerts_sent,
                important=len([i for i in filtered[:MAX_NEWS_PER_SCAN] if i.score >= 3.0]),
                total=len(news),
                categories=sum([i.categories or [] for i in filtered[:MAX_NEWS_PER_SCAN]], []),
            )
            log.info(f"📊 Scan complete: {len(news)} fetched, {len(filtered)} important, {alerts_sent} sent")

            # ETF flows (مرة واحدة يومياً)
            try:
                etf = await fetch_etf_flows()
                if etf:
                    etf_hash = f"etf_{etf['date']}"
                    if etf_hash not in state.sent_news_hashes:
                        state.sent_news_hashes.add(etf_hash)
                        msg = format_etf_flows(etf)
                        if state.is_channel_enabled(config):
                            await message_queue.put(QueuedMessage(
                                text=msg, chat_id=config.CHANNEL_ID, priority=1
                            ))
                        await message_queue.put(QueuedMessage(
                            text=msg, chat_id=config.CHAT_ID, priority=1
                        ))
            except Exception as e:
                log.warning(f"ETF flows error: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

        except Exception as e:
            log.error(f"Scan loop error: {e}")
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
    log.info("📅 Daily summary loop started")
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

                if state.is_channel_enabled(config):
                    await message_queue.put(QueuedMessage(
                        text=msg, chat_id=config.CHANNEL_ID, priority=1
                    ))
                await message_queue.put(QueuedMessage(
                    text=msg, chat_id=config.CHAT_ID, priority=1
                ))

                last_summary_date = today
                log.info("📅 Daily summary sent")
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

    msg = f"📊 <b>الملخص اليومي للأخبار</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📅 التاريخ: {today}\n"
    msg += f"⏰ الوقت: {now_str}\n\n"
    msg += "📈 <b>إحصائيات اليوم:</b>\n"
    msg += f"   🔔 تنبيهات مُرسَلة: <b>{_daily_stats['alerts_sent']}</b>\n"
    msg += f"   📰 أخبار مهمة: <b>{_daily_stats['important_found']}</b>\n"
    msg += f"   📊 إجمالي فُحصت: <b>{_daily_stats['total_scanned']}</b>\n\n"

    cats = _daily_stats["categories"]
    if cats:
        msg += "🏷️ <b>توزيع الفئات:</b>\n"
        sorted_cats = sorted(cats.items(), key=lambda x: -x[1])
        for cat, count in sorted_cats:
            if count > 0:
                icon = {"breaking": "🚨", "hack": "⚠️", "etf": "📊",
                        "whale": "🐋", "tech": "🔧", "market": "📈"}.get(cat, "📰")
                msg += f"   {icon} {cat}: {count}\n"

    msg += "\n━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 <i>تم إنشاء هذا الملخص تلقائياً</i>\n@newscrypto1m"
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

    translator = TranslationManager(config)

    log.info("=" * 60)
    log.info("🤖 Whale News Bot v2.0 - Starting")
    log.info("=" * 60)
    log.info(f"📡 Sources: {len(NEWS_SOURCES)}")
    log.info(f"👥 Users: {len(state.allowed_users)}")
    log.info(f"📢 Channel: {config.CHANNEL_ID or 'Not set'}")

    # تشغيل المهام
    tasks = [
        asyncio.create_task(message_consumer(config, state)),
        asyncio.create_task(scan_news_loop(config, state, translator)),
        asyncio.create_task(daily_summary_loop(config, state)),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("🛑 Bot shutting down...")
    finally:
        source_quality.flush()
        await session_manager.close()
        translation_cache.flush()


# ═══════════════════════════════════════════════════════════
# 🔄 One-shot Mode (GitHub Actions)
# ═══════════════════════════════════════════════════════════
async def run_oneshot(config: BotConfig, state: BotState):
    """وضع التشغيل لمرة واحدة"""
    errors = config.validate()
    if errors:
        for error in errors:
            print(f"❌ {error}")
        return

    translator = TranslationManager(config)

    print("=" * 60)
    print("🤖 Running in one-shot mode")
    print("=" * 60)

    # تحميل الأخبار المُرسلة سابقاً
    sent_hashes = dedup.load()
    print(f"📊 Loaded {len(sent_hashes)} sent hashes")

    # جلب الأخبار
    news = await fetch_all_news(max_concurrent=5)
    if not news:
        print("⚠️ No news available")
        return

    filtered = filter_news_items(news, min_score=1.5)
    now = time.time()
    alerts_sent = 0

    for item in filtered[:MAX_NEWS_PER_SCAN]:
        if item.timestamp > 0 and (now - item.timestamp) > MAX_NEWS_AGE:
            continue

        if dedup.is_sent(sent_hashes, item.hash):
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

        # طبقة الأمان الأخيرة: المراجعة التحريرية النهائية
        msg = final_editorial_review(msg)
        if not msg:
            print(f"   🧹 Blocked by editorial review: {item.title[:60]}")
            if item.source:
                source_quality.record_rejection(item.source, "Blocked by editorial review")
            continue

        # إرسال
        dedup.mark_sent(sent_hashes, item.hash)

        if state.is_channel_enabled(config):
            await send_telegram_message(config.CHANNEL_ID, msg, item.image, config.TOKEN)
        await send_telegram_message(config.CHAT_ID, msg, item.image, config.TOKEN)

        # تسجيل نجاح المصدر
        if item.source:
            source_quality.record_success(item.source)

        alerts_sent += 1
        print(f"  ✉️ {item.title[:60]}...")

    # ETF
    try:
        etf = await fetch_etf_flows()
        if etf:
            etf_hash = f"etf_{etf['date']}"
            if not dedup.is_sent(sent_hashes, etf_hash):
                dedup.mark_sent(sent_hashes, etf_hash)
                msg = format_etf_flows(etf)
                if state.is_channel_enabled(config):
                    await send_telegram_message(config.CHANNEL_ID, msg, None, config.TOKEN)
                await send_telegram_message(config.CHAT_ID, msg, None, config.TOKEN)
                print(f"  📊 ETF flows: {etf['date']}")
    except Exception as e:
        print(f"  ⚠️ ETF error: {e}")

    # حفظ الهاشات (محلي + commit للريبو)
    dedup.save_to_repo(sent_hashes)
    print(f"💾 Saved {len(sent_hashes)} hashes")

    print("=" * 60)
    print(f"📊 Results: {len(news)} fetched, {len(filtered)} important, {alerts_sent} sent")
    print("=" * 60)

    await session_manager.close()
    translation_cache.flush()
    source_quality.flush()
