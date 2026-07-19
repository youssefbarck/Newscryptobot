"""
📊 Whale News Bot v2.0 - التقرير اليومي للسوق (Daily Crypto Report)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
وحدة مستقلة تماماً عن نظام الأخبار.
تجلب البيانات من مصادر مجانية، تنسّقها كـ Dashboard، وترسلها مرة واحدة يومياً.
"""

import os, json, time, asyncio, logging, traceback
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

import aiohttp
from aiohttp import ClientTimeout

from config import log, BotConfig, BotState, tz, HEADERS

# ═══════════════════════════════════════════════════════════
# ⚙️ إعدادات التقرير
# ═══════════════════════════════════════════════════════════
REPORT_HOUR = 15          # 03:00 مساءً
REPORT_MINUTE = 0
REPORT_PAUSE_SECONDS = 60 # إيقاف الأخبار لمدة دقيقة
_STATE_FILE = "daily_report_state.json"

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
# 🌐 جلب البيانات — مصادر مجانية
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


# ─── Fear & Greed Index ───
async def fetch_fear_greed() -> Optional[Dict]:
    """مؤشر الخوف والطمع — alternative.me"""
    data = await _fetch_json("https://api.alternative.me/fng/?limit=1")
    if data and "data" in data and len(data["data"]) > 0:
        d = data["data"][0]
        return {
            "value": int(d.get("value", 0)),
            "label": d.get("value_classification", ""),
        }
    return None


# ─── بيانات السوق من CoinGecko ───
async def fetch_market_overview() -> Optional[Dict]:
    """القيمة السوقية، حجم التداول، هيمنة بيتكوين، أفضل/أسوأ عملات"""
    data = await _fetch_json(
        "https://api.coingecko.com/api/v3/global",
        timeout=20
    )
    if not data or "data" not in data:
        return None

    gd = data["data"]
    result: Dict[str, Any] = {}

    # القيمة السوقية
    mcap = gd.get("total_market_cap", {}) or {}
    usd_mcap = mcap.get("usd", 0)
    if usd_mcap:
        if usd_mcap >= 1e12:
            result["market_cap"] = f"{usd_mcap / 1e12:.2f}T$"
        elif usd_mcap >= 1e9:
            result["market_cap"] = f"{usd_mcap / 1e9:.2f}B$"
        else:
            result["market_cap"] = f"{usd_mcap / 1e6:.1f}M$"

    # حجم التداول
    vol = gd.get("total_volume", {}) or {}
    usd_vol = vol.get("usd", 0)
    if usd_vol:
        if usd_vol >= 1e12:
            result["volume"] = f"{usd_vol / 1e12:.2f}T$"
        elif usd_vol >= 1e9:
            result["volume"] = f"{usd_vol / 1e9:.1f}B$"
        else:
            result["volume"] = f"{usd_vol / 1e6:.1f}M$"

    # هيمنة بيتكوين
    btc_dom = gd.get("market_cap_percentage", {}) or {}
    if "btc" in btc_dom:
        result["btc_dominance"] = f"{btc_dom['btc']:.1f}%"

    # أفضل 3 مرتفعين وأسوأ 3 منخفضين (24h)
    try:
        top_data = await _fetch_json(
            "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h",
            timeout=20
        )
        if top_data and isinstance(top_data, list):
            sorted_by_change = sorted(
                top_data, key=lambda c: (c.get("price_change_percentage_24h") or 0), reverse=True
            )
            gainers = sorted_by_change[:3]
            losers = sorted_by_change[-3:][::-1]  # عكس لعرض الأسوأ أولاً

            result["gainers"] = []
            for c in gainers:
                chg = c.get("price_change_percentage_24h", 0) or 0
                symbol = c.get("symbol", "?").upper()
                result["gainers"].append({
                    "symbol": symbol,
                    "change": f"+{chg:.1f}%",
                })

            result["losers"] = []
            for c in losers:
                chg = c.get("price_change_percentage_24h", 0) or 0
                symbol = c.get("symbol", "?").upper()
                result["losers"].append({
                    "symbol": symbol,
                    "change": f"{chg:.1f}%",
                })
    except Exception as e:
        log.warning(f"📊 Top gainers/losers fetch error: {str(e)[:80]}")

    return result if result else None


# ─── ETF Flows (يُستخدم من rss.py إن وُجد) ───
async def fetch_etf_report() -> Optional[Dict]:
    """تدفقات ETF — من الوحدة الموجودة في rss.py"""
    try:
        from rss import fetch_etf_flows
        etf = await fetch_etf_flows()
        if etf:
            result: Dict[str, Any] = {"funds": []}
            btc_total = etf.get("btc_total", 0)
            eth_total = etf.get("eth_total", 0)
            date = etf.get("date", "")

            if btc_total != 0:
                sign = "+" if btc_total >= 0 else ""
                result["funds"].append({
                    "symbol": "BTC",
                    "flow": f"{sign}{btc_total:.1f}M$",
                    "positive": btc_total >= 0,
                })
            if eth_total != 0:
                sign = "+" if eth_total >= 0 else ""
                result["funds"].append({
                    "symbol": "ETH",
                    "flow": f"{sign}{eth_total:.1f}M$",
                    "positive": eth_total >= 0,
                })

            # تفاصيل الصناديق الفردية
            for fund_name, val in list((etf.get("btc_funds") or {}).items())[:2]:
                if val != 0:
                    sign = "+" if val >= 0 else ""
                    result["funds"].append({
                        "symbol": fund_name,
                        "flow": f"{sign}{val:.1f}M$",
                        "positive": val >= 0,
                    })
            for fund_name, val in list((etf.get("eth_funds") or {}).items())[:1]:
                if val != 0:
                    sign = "+" if val >= 0 else ""
                    result["funds"].append({
                        "symbol": fund_name,
                        "flow": f"{sign}{val:.1f}M$",
                        "positive": val >= 0,
                    })

            result["date"] = date
            return result if result["funds"] else None
    except Exception as e:
        log.warning(f"📊 ETF report error: {str(e)[:80]}")
    return None


# ─── التصفيات (Liquidations) ───
async def fetch_liquidations() -> Optional[Dict]:
    """تصفيات العقود — coinglass.com (مجاني)"""
    data = await _fetch_json(
        "https://open-api.coinglass.com/public/v2/liquidation?time_type=h24",
        timeout=15
    )
    if data and "data" in data:
        d = data["data"]
        result: Dict[str, Any] = {}

        # محاولة استخراج long/short
        for item in d if isinstance(d, list) else []:
            symbol = item.get("symbol", "")
            if symbol.upper() == "ALL":
                long_val = item.get("longLiquidationUsd", 0) or 0
                short_val = item.get("shortLiquidationUsd", 0) or 0
                if long_val:
                    result["long"] = f"${long_val / 1e6:.1f}M"
                if short_val:
                    result["short"] = f"${short_val / 1e6:.1f}M"
                break

        if not result:
            # محاولة صيغة أخرى
            if isinstance(d, dict):
                long_val = d.get("longLiquidationUsd", 0) or 0
                short_val = d.get("shortLiquidationUsd", 0) or 0
                if long_val:
                    result["long"] = f"${long_val / 1e6:.1f}M"
                if short_val:
                    result["short"] = f"${short_val / 1e6:.1f}M"

        return result if result else None
    return None


# ─── حركات الحيتان (Whale Transactions) ───
async def fetch_whale_activity() -> Optional[List[Dict]]:
    """أكبر تحويلات الحيتان — whale-alert.io API (مجاني محدود)"""
    api_key = os.environ.get("WHALE_ALERT_API_KEY", "")
    if not api_key:
        return None

    data = await _fetch_json(
        f"https://api.whale-alert.io/v1/transactions?api_key={api_key}&min_value=5000000&start={int(time.time()) - 86400}",
        timeout=15
    )
    if data and "transactions" in data:
        txs = []
        for tx in data["transactions"][:3]:
            symbol = tx.get("symbol", "?")
            value_usd = tx.get("usd_value", 0) or 0
            if value_usd >= 1e9:
                val_str = f"${value_usd / 1e9:.1f}B"
            else:
                val_str = f"${value_usd / 1e6:.1f}M"
            txs.append({
                "symbol": symbol,
                "value": val_str,
                "from": (tx.get("from", {}) or {}).get("owner", "?"),
                "to": (tx.get("to", {}) or {}).get("owner", "?"),
            })
        return txs if txs else None
    return None


# ─── أهم أخبار اليوم ───
async def fetch_top_news() -> Optional[List[str]]:
    """يعيد آخر 3 أخبار نُسّقت بالعربية من حالة البوت"""
    return None  # يُملأ وقت التجميع إن توفرت أخبار اليوم


# ═══════════════════════════════════════════════════════════
# 📐 تنسيق التقرير (Dashboard)
# ═══════════════════════════════════════════════════════════
SEP = "━━━━━━━━━━━━━━━━━━"

def _fmt_section(title: str, icon: str, content: str) -> Optional[str]:
    """بناء قسم — يرجع None إن كان المحتوى فارغاً"""
    if not content or not content.strip():
        return None
    return f"{icon} {title}\n\n{content.strip()}"


def _emoji(val: float) -> str:
    return "\U0001f7e2" if val >= 0 else "\U0001f534"  # green / red

def _fng_emoji(value: int) -> str:
    """لون مؤشر الخوف والطمع"""
    if value <= 25:
        return "\U0001f534"  # red - Extreme Fear
    elif value <= 45:
        return "\U0001f7e1"  # orange - Fear
    elif value <= 55:
        return "\U0001f7e1"  # yellow - Neutral
    elif value <= 75:
        return "\U0001f7e2"  # green - Greed
    else:
        return "\U0001f7e2"  # green - Extreme Greed


def build_report(
    etf: Optional[Dict] = None,
    fear_greed: Optional[Dict] = None,
    liquidations: Optional[Dict] = None,
    market: Optional[Dict] = None,
    whale: Optional[List[Dict]] = None,
    top_news: Optional[List[str]] = None,
) -> str:
    """بناء التقرير النهائي كنص جاهز للإرسال"""
    now = datetime.now(tz)
    date_str = now.strftime("%d-%m-%Y")
    time_str = now.strftime("%I:%M %p")

    lines: List[str] = []
    lines.append("\U0001f4f0 \u0627\u0644\u062a\u0642\u0631\u064a\u0631 \u0627\u0644\u064a\u0648\u0645\u064a \u0644\u0644\u0633\u0648\u0642")
    lines.append(f"\U0001f4c6 {date_str}")
    lines.append(f"\U0001f552 {time_str}")
    lines.append(SEP)
    sections: List[str] = []

    # ─── ETF ───
    if etf and etf.get("funds"):
        etf_lines = []
        for f in etf["funds"]:
            icon = "\U0001f7e2" if f["positive"] else "\U0001f534"
            etf_lines.append(f"{icon} {f['symbol']} {f['flow']}")
        sec = _fmt_section("\u062a\u062f\u0641\u0642\u0627\u062a \u0635\u0646\u0627\u062f\u064a\u0642 ETF", "\U0001f3c0", "\n".join(etf_lines))
        if sec:
            sections.append(sec)

    # ─── Fear & Greed ───
    if fear_greed and fear_greed.get("value"):
        v = fear_greed["value"]
        label = fear_greed.get("label", "")
        icon = _fng_emoji(v)
        sec = _fmt_section(
            "\u0645\u0624\u0634\u0631 \u0627\u0644\u062e\u0648\u0641 \u0648\u0627\u0644\u0637\u0645\u0639",
            "\U0001f628",
            f"{icon} {v} | {label}"
        )
        if sec:
            sections.append(sec)

    # ─── Liquidations ───
    if liquidations:
        liq_lines = []
        if liquidations.get("long"):
            liq_lines.append(f"\U0001f7e2 Long: {liquidations['long']}")
        if liquidations.get("short"):
            liq_lines.append(f"\U0001f534 Short: {liquidations['short']}")
        if liq_lines:
            sec = _fmt_section("\u0627\u0644\u062a\u0635\u0641\u064a\u0627\u062a (24H)", "\U0001f4b8", "\n".join(liq_lines))
            if sec:
                sections.append(sec)

    # ─── BTC Dominance ───
    if market and market.get("btc_dominance"):
        sec = _fmt_section(
            "\u0647\u064a\u0645\u0646\u0629 \u0628\u064a\u062a\u0643\u0648\u064a\u0646",
            "\u20bf",
            market["btc_dominance"]
        )
        if sec:
            sections.append(sec)

    # ─── Market Cap ───
    if market and market.get("market_cap"):
        sec = _fmt_section(
            "\u0627\u0644\u0642\u064a\u0645\u0629 \u0627\u0644\u0633\u0648\u0642\u064a\u0629",
            "\U0001f4b0",
            market["market_cap"]
        )
        if sec:
            sections.append(sec)

    # ─── Volume ───
    if market and market.get("volume"):
        sec = _fmt_section(
            "\u062d\u062c\u0645 \u0627\u0644\u062a\u062f\u0627\u0648\u0644",
            "\U0001f4ca",
            market["volume"]
        )
        if sec:
            sections.append(sec)

    # ─── Top Gainers ───
    if market and market.get("gainers"):
        g_lines = []
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, g in enumerate(market["gainers"]):
            g_lines.append(f"{medals[i]} {g['symbol']} {g['change']}")
        sec = _fmt_section("\u0623\u0641\u0636\u0644 \u0627\u0644\u0639\u0645\u0644\u0627\u062a", "\U0001f4c8", "\n".join(g_lines))
        if sec:
            sections.append(sec)

    # ─── Top Losers ───
    if market and market.get("losers"):
        l_lines = []
        for l in market["losers"]:
            l_lines.append(f"\U0001f53b {l['symbol']} {l['change']}")
        sec = _fmt_section("\u0623\u0633\u0648\u0623 \u0627\u0644\u0639\u0645\u0644\u0627\u062a", "\U0001f4c9", "\n".join(l_lines))
        if sec:
            sections.append(sec)

    # ─── Whale Transactions ───
    if whale:
        w_lines = []
        for w in whale:
            w_lines.append(f"{w['symbol']} — {w['value']} ({w['from']} \u2192 {w['to']})")
        sec = _fmt_section(
            "\u0623\u0643\u0628\u0631 \u062d\u0631\u0643\u0629 \u0644\u0644\u062d\u064a\u062a\u0627\u0646",
            "\U0001f40b",
            "\n".join(w_lines)
        )
        if sec:
            sections.append(sec)

    # ─── Top News ───
    if top_news:
        n_lines = []
        nums = ["\u2460", "\u2461", "\u2462", "\u2463", "\u2464"]
        for i, n in enumerate(top_news[:5]):
            n_lines.append(f"{nums[i]} {n}")
        sec = _fmt_section("\u0623\u0647\u0645 \u0623\u062e\u0628\u0627\u0631 \u0627\u0644\u064a\u0648\u0645", "\U0001f4f0", "\n".join(n_lines))
        if sec:
            sections.append(sec)

    # تجميع الأقسام مع الفواصل
    for i, section in enumerate(sections):
        lines.append(section)
        if i < len(sections) - 1:
            lines.append(SEP)

    lines.append(SEP)
    lines.append("\U0001f4cc Daily Crypto Report")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# ⏰ حلقة الجدولة
# ═══════════════════════════════════════════════════════════
async def daily_report_loop(config: BotConfig, state: BotState):
    """حلقة التقرير اليومي — مستقلة عن نظام الأخبار"""
    from telegram_bot import send_telegram_message, message_queue, QueuedMessage

    # تحميل الحالة السابقة
    report_state.load()
    log.info(f"📊 Daily Report module started — last sent: {report_state._last_date or 'never'}")

    while True:
        try:
            if state.bot_shutdown:
                await asyncio.sleep(60)
                continue

            now = datetime.now(tz)

            # فحص الوقت
            if now.hour == REPORT_HOUR and now.minute >= REPORT_MINUTE:
                if report_state.already_sent_today():
                    await asyncio.sleep(60)
                    continue

                log.info("📊 Generating daily crypto report...")

                # إيقاف الأخبار مؤقتاً
                state.bot_resume_time = time.time() + REPORT_PAUSE_SECONDS
                log.info("📊 Pausing news for 60s to send daily report")

                await asyncio.sleep(REPORT_PAUSE_SECONDS)

                # جلب البيانات بالتوازي
                etf_task = asyncio.create_task(fetch_etf_report())
                fng_task = asyncio.create_task(fetch_fear_greed())
                liq_task = asyncio.create_task(fetch_liquidations())
                mkt_task = asyncio.create_task(fetch_market_overview())
                whale_task = asyncio.create_task(fetch_whale_activity())

                etf, fng, liq, mkt, whale = await asyncio.gather(
                    etf_task, fng_task, liq_task, mkt_task, whale_task,
                    return_exceptions=True
                )

                # تحويل الأخطاء إلى None
                if isinstance(etf, Exception):
                    log.warning(f"📊 ETF error: {str(etf)[:80]}")
                    etf = None
                if isinstance(fng, Exception):
                    log.warning(f"📊 Fear&Greed error: {str(fng)[:80]}")
                    fng = None
                if isinstance(liq, Exception):
                    log.warning(f"📊 Liquidations error: {str(liq)[:80]}")
                    liq = None
                if isinstance(mkt, Exception):
                    log.warning(f"📊 Market error: {str(mkt)[:80]}")
                    mkt = None
                if isinstance(whale, Exception):
                    log.warning(f"📊 Whale error: {str(whale)[:80]}")
                    whale = None

                # بناء التقرير
                msg = build_report(
                    etf=etf,
                    fear_greed=fng,
                    liquidations=liq,
                    market=mkt,
                    whale=whale,
                )

                if not msg or len(msg) < 50:
                    log.warning("📊 Report was empty, skipping")
                    await asyncio.sleep(120)
                    continue

                # إرسال التقرير
                sent = False

                # للقناة
                if state.is_channel_enabled(config):
                    # التقرير طويل — إرسال كنص بدون صورة
                    await message_queue.put(QueuedMessage(
                        text=msg,
                        chat_id=config.CHANNEL_ID,
                        priority=5,  # أعلى أولوية
                    ))
                    sent = True

                # للمالك
                await message_queue.put(QueuedMessage(
                    text=msg,
                    chat_id=config.CHAT_ID,
                    priority=5,
                ))
                sent = True

                if sent:
                    report_state.mark_sent()
                    log.info("📊 Daily report sent and state saved")

                # انتظار حتى يمرّ الوقت
                await asyncio.sleep(120)
                continue

            # فحص كل 30 ثانية
            await asyncio.sleep(30)

        except Exception as e:
            log.error(f"📊 Daily report loop error: {e}\n{traceback.format_exc()[-300:]}")
            await asyncio.sleep(60)