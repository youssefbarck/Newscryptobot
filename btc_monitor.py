"""
btc_monitor.py — 🆕 v6.4.113: مراقب BTC/ETH — يرسل صور شارت عند تغيرات مؤثرة
================================================================================

🎯 المنطق:
   - يراقب BTC و ETH كل 5 دقائق
   - لو تغير السعر ≥ threshold (افتراضي 1.5%) منذ آخر تنبيه
   - يولّد صورة شارت احترافية (أخضر للصعود، أحمر للهبوط)
   - يرسلها لِـ قناة منفصلة (BTC_MONITOR_CHANNEL_ID)

⚙️ الإعدادات (env):
   - BTC_MONITOR_CHANNEL_ID = -100xxxx (قناة منفصلة)
   - BTC_MONITOR_THRESHOLD = 1.5 (نسبة التغير المطلوبة)
   - BTC_MONITOR_INTERVAL = 300 (فاصل الفحص بالثواني)
"""

import logging
import time
import os
import io
import requests

log = logging.getLogger("BTCMonitor")

# ═══ إعدادات ═══
BTC_MONITOR_CHANNEL_ID = os.environ.get("BTC_MONITOR_CHANNEL_ID", "")
BTC_MONITOR_THRESHOLD = float(os.environ.get("BTC_MONITOR_THRESHOLD", "1.5"))
BTC_MONITOR_INTERVAL = int(os.environ.get("BTC_MONITOR_INTERVAL", "300"))

# ═══ حالة ═══
_last_prices = {"BTC": 0.0, "ETH": 0.0}
_last_alert_time = {"BTC": 0.0, "ETH": 0.0}
_ALERT_COOLDOWN = 600  # 10 دقائق بين التنبيهات لنفس العملة

# ═══ Binance API ═══
_BINANCE_BASE = "https://api.binance.com"
_BINANCE_FALLBACK = "https://data-api.binance.vision"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 50) -> list:
    """يجلب الشموع من Binance."""
    try:
        for base in [_BINANCE_BASE, _BINANCE_FALLBACK]:
            try:
                url = f"{base}/api/v3/klines"
                r = requests.get(url, params={
                    "symbol": f"{symbol}USDT",
                    "interval": interval,
                    "limit": limit
                }, headers=_HEADERS, timeout=10)
                if r.status_code == 200:
                    return [{
                        "open_time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": int(k[6])
                    } for k in r.json()]
                if r.status_code in (403, 418, 429, 451):
                    continue
                return []
            except Exception:
                continue
        return []
    except Exception:
        return []


def _get_current_price(symbol: str) -> float:
    """سعر لحظي."""
    try:
        url = f"{_BINANCE_BASE}/api/v3/ticker/price?symbol={symbol}USDT"
        r = requests.get(url, headers=_HEADERS, timeout=5)
        if r.status_code == 200:
            return float(r.json()["price"])
        return 0
    except Exception:
        return 0


def _generate_chart_image(symbol: str, candles: list, is_up: bool, change_pct: float = 0) -> bytes:
    """يولّد صورة بسيطة: سعر كبير + سهم صعود/هبوط + لون خلفية."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams["axes.unicode_minus"] = False

        cur_price = candles[-1]["close"]
        last_price = candles[-1]["close"] / (1 + change_pct / 100) if change_pct != 0 else cur_price

        # الألوان
        if is_up:
            bg = "#0D2B0D"  # أخضر داكن
            text_color = "#00FF00"
            arrow = "▲"
        else:
            bg = "#2B0D0D"  # أحمر داكن
            text_color = "#FF4444"
            arrow = "▼"

        fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)
        ax.axis("off")

        # اسم العملة
        ax.text(0.5, 0.85, f"{symbol}/USDT", transform=ax.transAxes,
                fontsize=28, color="#FFFFFF", ha="center", va="center", fontweight="bold")

        # السهم + السعر الحالي (كبير جداً)
        ax.text(0.5, 0.5, f"{arrow} ${cur_price:,.2f}", transform=ax.transAxes,
                fontsize=48, color=text_color, ha="center", va="center", fontweight="bold")

        # نسبة التغير (كبير)
        sign = "+" if change_pct >= 0 else ""
        ax.text(0.5, 0.2, f"{sign}{change_pct:.2f}%", transform=ax.transAxes,
                fontsize=32, color=text_color, ha="center", va="center", fontweight="bold")

        # السعر السابق
        ax.text(0.5, 0.05, f"من ${last_price:,.2f}", transform=ax.transAxes,
                fontsize=14, color="#888888", ha="center", va="center")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, facecolor=bg)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        log.warning(f"btc_monitor chart err: {e}")
        return b""


def _send_photo_to_channel(token: str, chat_id: str, photo_bytes: bytes, caption: str) -> bool:
    """يرسل صورة لِـ قناة Telegram."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        files = {"photo": ("chart.png", photo_bytes, "image/png")}
        data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
        r = requests.post(url, files=files, data=data, timeout=30)
        if r.status_code == 200 and r.json().get("ok"):
            log.info(f"📊 [BTCMonitor] صورة أُرسلت لِـ {chat_id}")
            return True
        else:
            log.warning(f"📊 [BTCMonitor] فشل الإرسال: {r.text[:200]}")
            return False
    except Exception as e:
        log.warning(f"📊 [BTCMonitor] send err: {e}")
        return False


def check_and_alert(token: str, symbol: str):
    """يفحص سعر symbol ويُرسل تنبيه صورة لو تغير ≥ threshold."""
    try:
        if not BTC_MONITOR_CHANNEL_ID:
            return

        # cooldown
        now = time.time()
        if now - _last_alert_time.get(symbol, 0) < _ALERT_COOLDOWN:
            return

        cur_price = _get_current_price(symbol)
        if cur_price <= 0:
            return

        last_price = _last_prices.get(symbol, 0)
        if last_price <= 0:
            _last_prices[symbol] = cur_price
            return

        change_pct = ((cur_price - last_price) / last_price) * 100
        if abs(change_pct) < BTC_MONITOR_THRESHOLD:
            return

        # تغير مؤثر — أرسل تنبيه
        is_up = change_pct > 0
        candles = _fetch_klines(symbol, "15m", 50)
        if not candles:
            return

        # ولّد صورة
        photo = _generate_chart_image(symbol, candles, is_up)
        if not photo:
            return

        # رسالة
        arrow = "📈" if is_up else "📉"
        direction = "صعود" if is_up else "هبوط"
        color_text = "🟢" if is_up else "🔴"
        caption = (
            f"{arrow} <b>{symbol}/USDT — {direction}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 السعر الحالي: <b>${cur_price:,.2f}</b>\n"
            f"{color_text} التغير: <b>{change_pct:+.2f}%</b>\n"
            f"💵 السعر السابق: ${last_price:,.2f}\n"
        )

        # أرسل
        ok = _send_photo_to_channel(token, BTC_MONITOR_CHANNEL_ID, photo, caption)
        if ok:
            _last_prices[symbol] = cur_price
            _last_alert_time[symbol] = now
            log.info(f"📊 [BTCMonitor] {symbol} {direction} {change_pct:+.2f}% — صورة أُرسلت ✅")
    except Exception as e:
        log.warning(f"📊 [BTCMonitor] check {symbol} err: {e}")


def send_test_message(token: str):
    """🆕 v6.4.114: رسالة اختبار فورية — BTC + ETH + صورة."""
    try:
        if not BTC_MONITOR_CHANNEL_ID:
            log.warning("📊 [BTCMonitor] لا توجد قناة — معطّل")
            return

        # BTC
        btc_price = _get_current_price("BTC")
        btc_candles = _fetch_klines("BTC", "15m", 50)
        if btc_price > 0 and btc_candles:
            photo = _generate_chart_image("BTC", btc_candles, True, 0.5)
            if photo:
                caption = f"BTC/USDT — ${btc_price:,.2f}"
                ok = _send_photo_to_channel(token, BTC_MONITOR_CHANNEL_ID, photo, caption)
                if ok:
                    log.info(f"📊 [BTCMonitor] رسالة اختبار BTC أُرسلت ✅")
                else:
                    log.warning(f"📊 [BTCMonitor] فشل إرسال BTC — تحقق من channel ID = {BTC_MONITOR_CHANNEL_ID}")

        time.sleep(2)

        # ETH
        eth_price = _get_current_price("ETH")
        eth_candles = _fetch_klines("ETH", "15m", 50)
        if eth_price > 0 and eth_candles:
            photo = _generate_chart_image("ETH", eth_candles, True, 0.5)
            if photo:
                caption = f"ETH/USDT — ${eth_price:,.2f}"
                ok = _send_photo_to_channel(token, BTC_MONITOR_CHANNEL_ID, photo, caption)
                if ok:
                    log.info(f"📊 [BTCMonitor] رسالة اختبار ETH أُرسلت ✅")
                else:
                    log.warning(f"📊 [BTCMonitor] فشل إرسال ETH")
    except Exception as e:
        log.warning(f"📊 [BTCMonitor] test msg err: {e}")


def btc_monitor_loop(token: str):
    """حلقة مراقبة BTC + ETH — تعمل في thread منفصل."""
    log.info(f"📊 [BTCMonitor] بدء المراقبة — interval={BTC_MONITOR_INTERVAL}s threshold={BTC_MONITOR_THRESHOLD}%")
    while True:
        try:
            check_and_alert(token, "BTC")
            time.sleep(2)
            check_and_alert(token, "ETH")
            time.sleep(BTC_MONITOR_INTERVAL)
        except Exception as e:
            log.warning(f"📊 [BTCMonitor] loop err: {e}")
            time.sleep(60)
