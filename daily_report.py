"""
📊 Whale News Bot v2.0 - التقرير اليومي للسوق (Daily Crypto Report)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
وحدة مستقلة تماماً عن نظام الأخبار.
تجلب البيانات عبر Cohere API مع بحث الويب، تنسّقها كـ Dashboard، وترسلها مرة واحدة يومياً.
"""

import os, json, time, asyncio, logging, traceback
from datetime import datetime
from typing import Optional, Dict, List, Any

import aiohttp
from aiohttp import ClientTimeout

from config import log, BotConfig, BotState, tz, HEADERS

# ═══════════════════════════════════════════════════════════
# ⚙️ إعدادات التقرير
# ═══════════════════════════════════════════════════════════
REPORT_PAUSE_SECONDS = 60 # إيقاف الأخبار لمدة دقيقة
_STATE_FILE = "daily_report_state.json"
COHERE_API_URL = "https://api.cohere.com/v2/chat"
COHERE_MODEL = "command-r-plus"


# ═══════════════════════════════════════════════════════════
# 💾 إدارة حالة الإرسال
# ═══════════════════════════════════════════════════════════
class ReportStateManager:
    """يمنع إرسال التقرير مرتين في نفس اليوم — حتى بعد إعادة التشغيل"""

    def __init__(self):
        self._file = os.path.join(os.getcwd(), _STATE_FILE)
        self._last_date: str = ""

    def load(self):
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._last_date = data.get("last_report_date", "")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._last_date = ""

    def save(self, date_str: str):
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump({"last_report_date": date_str, "updated_at": time.time()}, f, indent=2)
        except OSError as e:
            log.warning(f"📊 Report state save error: {e}")

    def already_sent_today(self) -> bool:
        today = datetime.now(tz).strftime("%Y-%m-%d")
        return self._last_date == today

    def mark_sent(self):
        today = datetime.now(tz).strftime("%Y-%m-%d")
        self._last_date = today
        self.save(today)


report_state = ReportStateManager()


# ═══════════════════════════════════════════════════════════
# 🌐 جلب البيانات عبر Cohere Command R+ (طلب واحد يجمع كل شيء)
# ═══════════════════════════════════════════════════════════

_KIMI_SYSTEM_PROMPT = """أنت أداة لجمع بيانات السوق المشفرة. مهمتك فقط البحث في الويب وجمع الأرقام الحالية.

يجب أن تُرجع JSON فقط بدون أي نص إضافي أو شرح أو markdown.

البيانات المطلوبة:
{
  "etf": {
    "funds": [
      {"symbol": "IBIT", "flow": "+85.2M$", "positive": true},
      {"symbol": "FBTC", "flow": "+62.1M$", "positive": true},
      {"symbol": "GBTC", "flow": "-18.3M$", "positive": false},
      {"symbol": "ARKB", "flow": "+22.7M$", "positive": true},
      {"symbol": "BITB", "flow": "+15.4M$", "positive": true},
      {"symbol": "EZBC", "flow": "+8.9M$", "positive": true},
      {"symbol": "HODL", "flow": "+6.1M$", "positive": true},
      {"symbol": "BTCW", "flow": "+3.2M$", "positive": true},
      {"symbol": "ETHA", "flow": "+36.7M$", "positive": true},
      {"symbol": "FETH", "flow": "+12.8M$", "positive": true},
      {"symbol": "ETHE", "flow": "-45.2M$", "positive": false},
      {"symbol": "ETHX", "flow": "+4.5M$", "positive": true}
    ]
  },
  "liquidations": {
    "long": "$523.4M",
    "short": "$312.1M"
  },
  "market": {
    "gainers": [
      {"symbol": "PEPE", "change": "+18.2%"},
      {"symbol": "WIF", "change": "+12.5%"},
      {"symbol": "AVAX", "change": "+9.8%"}
    ],
    "losers": [
      {"symbol": "UNI", "change": "-7.3%"},
      {"symbol": "AAVE", "change": "-5.1%"},
      {"symbol": "RENDER", "change": "-4.2%"}
    ]
  }
}

القواعد:
- ابحث في الويب عن البيانات الحالية الآن.
- الأرقام فقط، لا تحليل ولا رأي.
- إن لم تجد بيانات قسم معين، ضع null.
- لعملات top gainers/losers: اختر من بين أكبر 100 عملة بحسب الحجم.
- لتدفقات ETF: اذكر كل صناديق Bitcoin ETF و Ethereum ETF المتداولة (IBIT, FBTC, GBTC, ARKB, BITB, EZBC, HODL, BTCW, BRRR, BTCO للبيتكوين) و (ETHA, FETH, ETHE, ETHX, CETH, EZET للإيثريوم). اذكر أكبر عدد ممكن من الصناديق مع تدفقاتها اليومية. إن وجدت صناديق أخرى (SOL, LTC, XRP) أضفها أيضاً.
- للتصفيات: إجمالي 24 ساعة لكل من Long و Short.
- أخرج JSON صالح فقط."""


async def fetch_all_via_cohere() -> Optional[Dict]:
    """طلب واحد لـ Cohere Command R+ مع بحث ويب يجمع كل بيانات التقرير"""
    api_key = os.environ.get("COHERE_API_KEY", "")
    if not api_key:
        log.warning("📊 COHERE_API_KEY not set")
        return None

    today = datetime.now(tz).strftime("%Y-%m-%d")
    user_msg = f"Search for today's crypto ETF flows data ({today}): Get daily flows for ALL spot Bitcoin ETFs (IBIT, FBTC, GBTC, ARKB, BITB, EZBC, HODL, BTCW, BRRR, BTCO) and ALL spot Ethereum ETFs (ETHA, FETH, ETHE, ETHX, CETH, EZET) and any other crypto ETFs (SOL, LTC, XRP). Also get 24h liquidations (long vs short), top 3 gainers and top 3 losers from top 100 coins by volume. Return ONLY valid JSON matching the required format."

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": COHERE_MODEL,
                "messages": [
                    {"role": "user", "content": user_msg},
                ],
                "system_prompt": _KIMI_SYSTEM_PROMPT,
                "temperature": 0.1,
                "max_tokens": 2000,
                "tools": [{"type": "web_search"}],
            }

            async with session.post(
                COHERE_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=ClientTimeout(total=90),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning(f"📊 Cohere API error {resp.status}: {body[:150]}")
                    return None

                data = await resp.json()

                # Cohere v2: content في message.text
                message = data.get("message", {})
                content = message.get("content", [])

                # استخراج النص من array of content blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                full_text = "\n".join(text_parts)

                if not full_text:
                    # fallback: جرب صيغة أقدم
                    full_text = message.get("text", "")

                if not full_text:
                    log.warning("📊 Cohere returned empty content")
                    return None

                # استخراج JSON من الرد
                parsed = _extract_json(full_text)
                if parsed:
                    log.info("📊 Cohere data fetched successfully")
                    return parsed

                log.warning(f"📊 Cohere response not valid JSON: {full_text[:150]}")
                return None

    except Exception as e:
        log.error(f"📊 Cohere fetch error: {str(e)[:120]}")
    return None


def _extract_json(text: str) -> Optional[Dict]:
    """استخراج JSON من رد Cohere (قد يحتوي على markdown أو نص إضافي)"""
    # محاولة 1: parse مباشر
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # محاولة 2: البحث عن ```json ... ```
    import re
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # محاولة 3: البحث عن { ... }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    return None


# ═══════════════════════════════════════════════════════════
# 🔄 Fallback: مصادر مجانية مباشرة (إن فشل Cohere)
# ═══════════════════════════════════════════════════════════

async def _fetch_json(url: str, timeout: int = 15) -> Optional[Any]:
    """جلب JSON من URL مع معالجة أخطاء"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=timeout), headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.json()
                log.warning(f"📊 API returned {resp.status}: {url[:60]}")
    except Exception as e:
        log.warning(f"📊 Fetch error ({url[:50]}): {str(e)[:80]}")
    return None


async def fetch_market_fallback() -> Optional[Dict]:
    """أفضل/أسوأ عملات — CoinGecko"""
    try:
        top_data = await _fetch_json(
            "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h",
            timeout=20
        )
        if top_data and isinstance(top_data, list):
            sorted_by_change = sorted(
                top_data, key=lambda c: (c.get("price_change_percentage_24h") or 0), reverse=True
            )
            result: Dict[str, Any] = {}
            result["gainers"] = []
            for c in sorted_by_change[:3]:
                chg = c.get("price_change_percentage_24h", 0) or 0
                symbol = c.get("symbol", "?").upper()
                result["gainers"].append({"symbol": symbol, "change": f"{chg:+.1f}%"})
            result["losers"] = []
            for c in sorted_by_change[-3:][::-1]:
                chg = c.get("price_change_percentage_24h", 0) or 0
                symbol = c.get("symbol", "?").upper()
                result["losers"].append({"symbol": symbol, "change": f"{chg:.1f}%"})
            return result
    except Exception as e:
        log.warning(f"📊 Gainers/losers fallback error: {str(e)[:80]}")
    return None


# ═══════════════════════════════════════════════════════════
# 📐 تنسيق التقرير (Dashboard)
# ═══════════════════════════════════════════════════════════
SEP = "\u2501" * 20  # ━━━━━━━━━━━━━━━━━━


def _fmt_section(title: str, icon: str, content: str) -> Optional[str]:
    """بناء قسم — يرجع None إن كان المحتوى فارغاً"""
    if not content or not content.strip():
        return None
    return f"{icon} {title}\n\n{content.strip()}"


def build_report(data: Dict) -> str:
    """بناء التقرير النهائي من البيانات المجمعّة"""
    now = datetime.now(tz)
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%I:%M %p")

    lines: List[str] = []
    lines.append(f"\U0001f4f0 \u0627\u0644\u062a\u0642\u0631\u064a\u0631 \u0627\u0644\u064a\u0648\u0645\u064a \u0644\u0644\u0633\u0648\u0642")
    lines.append(f"\U0001f4c6 {date_str}")
    lines.append(f"\U0001f552 {time_str}")
    lines.append(SEP)

    sections: List[str] = []

    # ─── ETF ───
    etf = data.get("etf")
    if etf and etf.get("funds"):
        etf_lines = []
        for f in etf["funds"]:
            icon = "\U0001f7e2" if f.get("positive") else "\U0001f534"
            sym = f.get("symbol", "?")
            flow = f.get("flow", "")
            etf_lines.append(f"{icon} {sym} {flow}")
        sec = _fmt_section("\u062a\u062f\u0641\u0642\u0627\u062a \u0635\u0646\u0627\u062f\u064a\u0642 ETF", "\U0001f3c0", "\n".join(etf_lines))
        if sec:
            sections.append(sec)

    # ─── Liquidations ───
    liq = data.get("liquidations")
    if liq and (liq.get("long") or liq.get("short")):
        liq_lines = []
        if liq.get("long"):
            liq_lines.append(f"\U0001f7e2 Long: {liq['long']}")
        if liq.get("short"):
            liq_lines.append(f"\U0001f534 Short: {liq['short']}")
        sec = _fmt_section("\u0627\u0644\u062a\u0635\u0641\u064a\u0627\u062a (24H)", "\U0001f4b8", "\n".join(liq_lines))
        if sec:
            sections.append(sec)

    # ─── Top Gainers ───
    mkt = data.get("market")
    if mkt and mkt.get("gainers"):
        g_lines = []
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, g in enumerate(mkt["gainers"][:3]):
            g_lines.append(f"{medals[i]} {g['symbol']} {g['change']}")
        sec = _fmt_section("\u0623\u0641\u0636\u0644 \u0627\u0644\u0639\u0645\u0644\u0627\u062a", "\U0001f4c8", "\n".join(g_lines))
        if sec:
            sections.append(sec)

    # ─── Top Losers ───
    if mkt and mkt.get("losers"):
        l_lines = []
        for l in mkt["losers"][:3]:
            l_lines.append(f"\U0001f53b {l['symbol']} {l['change']}")
        sec = _fmt_section("\u0623\u0633\u0648\u0623 \u0627\u0644\u0639\u0645\u0644\u0627\u062a", "\U0001f4c9", "\n".join(l_lines))
        if sec:
            sections.append(sec)

    # تجميع الأقسام مع الفواصل
    for i, section in enumerate(sections):
        lines.append(section)
        if i < len(sections) - 1:
            lines.append(SEP)

    lines.append(SEP)
    lines.append("@newscrypto1m")

    return "\n".join(lines)


async def _generate_and_send(config: BotConfig, state: BotState) -> bool:
    """توليد التقرير وإرساله — يُستخدم في polling و oneshot"""
    from telegram_bot import message_queue, QueuedMessage, send_telegram_message

    log.info("\U0001f4ca Generating daily crypto report...")

    # ═══ المرحلة 1: Cohere (طلب واحد + بحث ويب) ═══
    data = await fetch_all_via_cohere()

    # ═══ المرحلة 2: Fallback بالمصادر المجانية ═══
    if not data:
        log.info("\U0001f4ca Cohere failed, using fallback APIs...")
        data = {}
        mkt = await fetch_market_fallback()
        if mkt:
            data["market"] = mkt

    msg = build_report(data)
    if not msg or len(msg) < 50:
        log.warning("\U0001f4ca Report was empty, skipping")
        return False

    sent = False
    if state.is_channel_enabled(config) and config.CHANNEL_ID:
        await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHANNEL_ID, priority=5))
        sent = True
    if config.CHAT_ID:
        await message_queue.put(QueuedMessage(text=msg, chat_id=config.CHAT_ID, priority=5))
        sent = True

    if not sent:
        log.warning("\U0001f4ca Report not queued (no chat_id)")
        return False

    if sent:
        report_state.mark_sent()
        log.info("\U0001f4ca Daily report sent and state saved")
    return sent


# ═══════════════════════════════════════════════════════════
# ⏰ حلقة الجدولة (polling mode)
# ═══════════════════════════════════════════════════════════
async def daily_report_loop(config: BotConfig, state: BotState):
    """حلقة التقرير اليومي — مستقلة عن نظام الأخبار (polling mode)"""

    report_state.load()
    log.info(f"\U0001f4ca Daily Report module started \u2014 last sent: {report_state._last_date or 'never'}")

    while True:
        try:
            if state.bot_shutdown:
                await asyncio.sleep(60)
                continue

            if not report_state.already_sent_today():
                state.bot_resume_time = time.time() + REPORT_PAUSE_SECONDS
                await asyncio.sleep(REPORT_PAUSE_SECONDS)
                await _generate_and_send(config, state)
                await asyncio.sleep(120)
                continue

            await asyncio.sleep(30)

        except Exception as e:
            log.error(f"\U0001f4ca Daily report loop error: {e}\n{traceback.format_exc()[-300:]}")
            await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════
# 🔄 One-shot Mode (GitHub Actions)
# ═══════════════════════════════════════════════════════════
async def send_report_if_due(config: BotConfig, state: BotState):
    """إرسال التقرير — يُستدعى من run_oneshot (يرسل فوراً إن لم يُرسل اليوم)"""
    report_state.load()

    if report_state.already_sent_today():
        log.info("\U0001f4ca Report already sent today, skipping")
        return

    await _generate_and_send(config, state)