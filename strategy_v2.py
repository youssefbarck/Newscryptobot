"""
strategy_v2.py — 🆕 v6.4.101: V2 = Dip Buying (شراء التصحيح)
================================================================

🎯 الاستراتيجية:
   شراء العملات التي هبطت ثم بدأت ترتد.
   - السعر هبط تحت EMA20 ثم ارتد
   - RSI بين 30-50 (تصحيح + ارتداد مبكر)
   - Volume spike عند الارتداد
   - BTC في اتجاه صاعد (دعم)

⚙️ Multi-Timeframe:
   - 4H: الاتجاه العام (يجب أن يكون صاعد أو محايد)
   - 1H: التصحيح (السعر هبط ثم بدأ يرتد)
   - 15M: إشارة الدخول (Volume spike + شمعة صاعدة)

⚠️ Spot فقط — لا Futures، لا Short، لا رافعة مالية.
"""

import logging
import time
import requests
from typing import Optional, Dict, List, Tuple

log = logging.getLogger("StrategyV2")

# ═══ Binance API ═══
_BINANCE_BASE = "https://api.binance.com"
_BINANCE_FALLBACK = "https://data-api.binance.vision"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

_CACHE: Dict = {}
_CACHE_TTL = 60


def _fetch_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict]:
    """يجلب الشموع من Binance (مع fallback)."""
    try:
        cache_key = f"{symbol}_{interval}"
        now = time.time()
        if cache_key in _CACHE:
            ts, candles = _CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                return candles

        for base in [_BINANCE_BASE, _BINANCE_FALLBACK]:
            try:
                url = f"{base}/api/v3/klines"
                r = requests.get(url, params={
                    "symbol": f"{symbol.upper()}USDT",
                    "interval": interval,
                    "limit": limit
                }, headers=_HEADERS, timeout=10)
                if r.status_code == 200:
                    candles = [{
                        "open_time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": int(k[6])
                    } for k in r.json()]
                    _CACHE[cache_key] = (now, candles)
                    return candles
                if r.status_code in (403, 418, 429, 451):
                    continue
                return []
            except Exception as e:
                log.warning(f"V2 fetch_klines {symbol} {interval} err: {e}")
                continue
        return []
    except Exception as e:
        log.warning(f"V2 fetch_klines outer err: {e}")
        return []


# ═══ المؤشرات ═══

def _calc_ema(closes: List[float], period: int) -> float:
    if not closes or len(closes) < period:
        return 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def _calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_atr(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < period:
        return 0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _calc_volume_ratio(candles: List[Dict], period: int = 20) -> float:
    if len(candles) < period:
        return 1.0
    avg_vol = sum(c["volume"] for c in candles[-period:]) / period
    if avg_vol == 0:
        return 1.0
    return candles[-1]["volume"] / avg_vol


def _calc_macd(closes: List[float]) -> Tuple[float, float, float, bool]:
    if len(closes) < 35:
        return 0, 0, 0, False
    def ema(data, period):
        k = 2 / (period + 1)
        e = sum(data[:period]) / period
        for p in data[period:]:
            e = p * k + e * (1 - k)
        return e
    ema12 = ema(closes[-30:], 12)
    ema26 = ema(closes[-30:], 26)
    macd_line = ema12 - ema26
    macd_values = []
    for i in range(20, len(closes)):
        sub = closes[i-30:i] if i >= 30 else closes[:i+1]
        if len(sub) < 30:
            continue
        e12 = ema(sub, 12)
        e26 = ema(sub, 26)
        macd_values.append(e12 - e26)
    if len(macd_values) < 9:
        return macd_line, 0, macd_line, False
    signal_line = ema(macd_values, 9)
    prev_macd = macd_values[-2] if len(macd_values) >= 2 else 0
    bullish_cross = macd_line > signal_line and prev_macd <= signal_line
    return macd_line, signal_line, macd_line - signal_line, bullish_cross


# ═══ V2 = Dip Buying ═══

def _get_btc_trend() -> str:
    """🆕 v6.4.101: BTC trend filter — لو BTC هابط، لا تدخل."""
    try:
        candles = _fetch_klines("BTC", "4h", 100)
        if not candles or len(candles) < 30:
            return "unknown"
        closes = [c["close"] for c in candles]
        ema20 = _calc_ema(closes, 20)
        ema50 = _calc_ema(closes, 50)
        cur = closes[-1]
        if cur > ema20 > ema50:
            return "bullish"
        if cur < ema20 < ema50:
            return "bearish"
        return "neutral"
    except Exception:
        return "unknown"


def detect_dip_buying_signal(symbol: str) -> Optional[Dict]:
    """🆕 v6.4.101: يكتشف Dip Buying signal — شراء التصحيح.

    المنطق:
      1. 4h: الاتجاه العام صاعد أو محايد (لا هبوط قوي)
      2. 1h: السعر هبط تحت EMA20 ثم بدأ يرتد
      3. 15m: RSI بين 30-50 + شمعة صاعدة + Volume spike
      4. BTC: صاعد أو محايد (دعم)

    يرجع: Dict أو None
    """
    try:
        # 1) BTC trend filter
        btc_trend = _get_btc_trend()
        if btc_trend == "bearish":
            log.info(f"🔄 [V2] {symbol} — تخطي: BTC 4h هابط")
            return None

        # 2) 4h trend
        candles_4h = _fetch_klines(symbol, "4h", 100)
        if not candles_4h or len(candles_4h) < 50:
            return None
        closes_4h = [c["close"] for c in candles_4h]
        ema20_4h = _calc_ema(closes_4h, 20)
        ema50_4h = _calc_ema(closes_4h, 50)
        cur_4h = closes_4h[-1]
        # 4h يجب أن لا يكون في هبوط قوي (السعر فوق EMA50 أو قريب منه)
        if cur_4h < ema50_4h * 0.95:
            log.info(f"🔄 [V2] {symbol} — تخطي: 4h هبوط قوي (السعر تحت EMA50 بِـ 5%+)")
            return None

        # 3) 1h dip detection
        candles_1h = _fetch_klines(symbol, "1h", 100)
        if not candles_1h or len(candles_1h) < 50:
            return None
        closes_1h = [c["close"] for c in candles_1h]
        ema20_1h = _calc_ema(closes_1h, 20)
        cur_1h = closes_1h[-1]
        rsi_1h = _calc_rsi(closes_1h)
        # 1h: السعر هبط تحت EMA20 ثم بدأ يرتد (آخر 10 شمعات)
        last_10 = candles_1h[-10:]
        dipped_below = any(c["close"] < ema20_1h * 0.99 for c in last_10[:-1])
        recovering = cur_1h > last_10[-2]["close"]  # آخر شمعة صاعدة
        # 🆕 v6.4.101: لو السعر حالياً قريب من EMA20 (داخل 3%) → اعتبره dip recovery
        near_ema20 = abs(cur_1h - ema20_1h) / ema20_1h < 0.03 if ema20_1h > 0 else False
        if not (dipped_below and recovering) and not near_ema20:
            log.info(f"🔄 [V2] {symbol} — تخطي: 1h لا يوجد dip + recovery")
            return None

        # 4) 15m entry trigger
        candles_15m = _fetch_klines(symbol, "15m", 100)
        if not candles_15m or len(candles_15m) < 30:
            return None
        closes_15m = [c["close"] for c in candles_15m]
        rsi_15m = _calc_rsi(closes_15m)
        # RSI 15m بين 30-55 (تصحيح + ارتداد مبكر)
        if rsi_15m < 25 or rsi_15m > 65:
            log.info(f"🔄 [V2] {symbol} — تخطي: 15m RSI {rsi_15m:.0f} خارج النطاق (30-65)")
            return None
        # آخر شمعة صاعدة
        last_15m = candles_15m[-1]
        if last_15m["close"] < last_15m["open"]:
            log.info(f"🔄 [V2] {symbol} — تخطي: 15m آخر شمعة هابطة")
            return None
        # Volume spike
        vol_ratio = _calc_volume_ratio(candles_15m)
        if vol_ratio < 1.0:
            log.info(f"🔄 [V2] {symbol} — تخطي: 15m Volume {vol_ratio:.1f}x < 1.0x")
            return None

        # 5) MACD bullish (تأكيد إضافي)
        macd_line, signal_line, hist, bullish_cross = _calc_macd(closes_15m)
        macd_bullish = hist > 0 or bullish_cross

        # 6) Score
        score = 50  # base
        if btc_trend == "bullish":
            score += 10
        if cur_4h > ema20_4h:
            score += 10  # 4h صاعد
        if rsi_1h < 50:
            score += 10  # تصحيح
        if vol_ratio >= 1.5:
            score += 10  # Volume قوي
        if macd_bullish:
            score += 10  # MACD bullish
        # 🆕 v6.4.122: VWAP يومي — السعر فوق VWAP = دعم مؤسسي
        vwap_daily = 0
        vwap_above = False
        try:
            # حساب VWAP من آخر 24 شمعة 1h
            if len(candles_1h) >= 24:
                daily_candles = candles_1h[-24:]
                total_pv = sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in daily_candles)
                total_v = sum(c["volume"] for c in daily_candles)
                vwap_daily = total_pv / total_v if total_v > 0 else 0
                if vwap_daily > 0:
                    vwap_above = cur_1h > vwap_daily
                    if vwap_above:
                        score += 5  # السعر فوق VWAP = دعم
        except Exception:
            pass
        score = min(100, score)

        # 7) Entry + SL + TP
        cur_price = last_15m["close"]
        atr = _calc_atr(candles_15m, 14)
        # SL تحت آخر قاع 1h أو تحت VWAP (الأقل)
        recent_low = min(c["low"] for c in candles_1h[-10:])
        sl = recent_low * 0.995
        # 🆕 v6.4.122: لو VWAP تحت السعر → استخدمه كـ SL أعمق لو أحسن
        if vwap_daily > 0 and vwap_daily < cur_price and vwap_daily > sl:
            vwap_dist_pct = (cur_price - vwap_daily) / cur_price
            if 0.02 <= vwap_dist_pct <= 0.05:  # VWAP بين 2-5% تحت الدخول
                sl = vwap_daily  # SL عند VWAP (دعم قوي)
        sl_pct = ((sl - cur_price) / cur_price) * 100
        if sl_pct > -1:
            sl = cur_price - 1.5 * atr if atr > 0 else cur_price * 0.97
            sl_pct = ((sl - cur_price) / cur_price) * 100
        # TPs: 1.5%, 3%, 5% (Dip Buying — أهداف معقولة)
        tp1 = cur_price * 1.015  # +1.5%
        tp2 = cur_price * 1.03  # +3%
        tp3 = cur_price * 1.05  # +5%
        tp1_pct = 1.5
        tp2_pct = 3.0
        tp3_pct = 5.0
        rr = abs(tp3_pct / sl_pct) if sl_pct != 0 else 0
        if rr < 1.0:
            log.info(f"🔄 [V2] {symbol} — تخطي: R/R {rr:.1f} < 1.0")
            return None

        # 8) Reasons
        reasons = [
            f"BTC: {btc_trend}",
            f"4h: {'فوق EMA20' if cur_4h > ema20_4h else 'تحت EMA20'}",
            f"1h: Dip + Recovery (RSI {rsi_1h:.0f})",
            f"15m: RSI {rsi_15m:.0f} + Volume {vol_ratio:.1f}x",
        ]
        if macd_bullish:
            reasons.append("MACD: Bullish")
        # 🆕 v6.4.122: VWAP evidence
        if vwap_above:
            reasons.append(f"VWAP يومي: السعر فوق ({vwap_daily:.4f})")

        log.info(f"🔄 [V2] {symbol} — ✅ Dip Buying! Score={score}, R/R={rr:.1f}, RSI 1h={rsi_1h:.0f}, Vol={vol_ratio:.1f}x")

        return {
            "symbol": symbol,
            "timeframe": "Dip Buying (4h/1h/15m)",
            "entry": cur_price,
            "entry_low": cur_price * 0.998,
            "entry_high": cur_price * 1.005,
            "sl": sl, "sl_pct": sl_pct,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "tp1_pct": tp1_pct, "tp2_pct": tp2_pct, "tp3_pct": tp3_pct,
            "rr": rr, "rsi": rsi_15m, "atr": atr, "volume_ratio": vol_ratio,
            "support": recent_low, "resistances": [],
            "score": score, "conditions_met": 4,
            "reasons": reasons,
            "candle_pattern": "Dip + Recovery",
            "swing_low": recent_low, "swing_high": 0, "fib_level": 0,
        }
    except Exception as e:
        log.warning(f"V2 detect_dip {symbol} err: {e}")
        return None


# ═══ cooldown (مُتبقى من v6.4.91) ═══
_SL_COOLDOWN_SEC = 24 * 3600
_sl_cooldown_db: Dict[str, float] = {}


def _mark_sl_hit(symbol: str):
    try:
        _sl_cooldown_db[(symbol or "").upper()] = time.time()
    except Exception:
        pass


def _is_in_cooldown_after_sl(symbol: str) -> bool:
    try:
        sym = (symbol or "").upper()
        ts = _sl_cooldown_db.get(sym, 0)
        if ts == 0:
            return False
        if time.time() - ts < _SL_COOLDOWN_SEC:
            return True
        _sl_cooldown_db.pop(sym, None)
        return False
    except Exception:
        return False


# ═══ Main entry (compatibility) ═══

def detect_reversal_signal(symbol: str, timeframe: str = "15m", limit: int = 100) -> Optional[Dict]:
    """🆕 v6.4.101: V2 = Dip Buying — يستدعي detect_dip_buying_signal."""
    try:
        if _is_in_cooldown_after_sl(symbol):
            log.info(f"🔄 [V2] {symbol} — تخطي: cooldown 24h بعد SL")
            return None
        return detect_dip_buying_signal(symbol)
    except Exception as e:
        log.warning(f"V2 detect_reversal {symbol} err: {e}")
        return None


def detect_reversal_signal_auto(symbol: str, timeframes: List[str] = None) -> Optional[Dict]:
    """🆕 v6.4.101: V2 = Dip Buying — يستدعي detect_dip_buying_signal."""
    return detect_reversal_signal(symbol)


def scan_v2_candidates(symbols: List[str], timeframe: str = "auto") -> List[Dict]:
    """🆕 v6.4.101: يفحص قائمة عملات لِـ Dip Buying signals."""
    signals = []
    for sym in symbols:
        try:
            sig = detect_reversal_signal(sym)
            if sig:
                signals.append(sig)
                log.info(f"🔄 [V2] {sym} — Dip Buying! Score={sig['score']}, R/R={sig['rr']:.1f}")
        except Exception as e:
            log.warning(f"V2 scan {sym} err: {e}")
    signals.sort(key=lambda x: -x["score"])
    return signals


# ═══ Message Format ═══

def format_v2_signal(sig: Dict, halal_ruling: str = "halal", target: str = "bot") -> str:
    """🆕 v6.4.101: تنسيق V2 (Dip Buying)."""
    try:
        sym = sig["symbol"]
        dot = "🟢" if target == "channel" else "🔴"
        _smart_liq = _v2_smart_liquidity_pct(sig)
        _liq_label = "🟢 احترافي" if _smart_liq >= 50 else ("🟡 جيد" if _smart_liq >= 30 else "⚪ ضعيف")

        msg = f"🔄 {dot} <b>Dip Buying — {sym}</b> 🔄V2\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 Score: <b>{sig['score']}/100</b>\n\n"
        msg += f"💰 الدخول: {sig['entry_low']:.6f} - {sig['entry_high']:.6f}\n\n"
        msg += f"🛑 الوقف: {sig['sl']:.6f} ({sig['sl_pct']:+.1f}%)\n\n"
        msg += f"🎯 الأهداف\n"
        msg += f"TP1: {sig['tp1']:.6f} (+{sig['tp1_pct']:.1f}%)\n"
        msg += f"TP2: {sig['tp2']:.6f} (+{sig['tp2_pct']:.1f}%)\n"
        msg += f"TP3: {sig['tp3']:.6f} (+{sig['tp3_pct']:.1f}%)\n\n"
        msg += f"⚖️ R/R: <b>{sig['rr']:.1f}x</b>\n"
        msg += f"💧 السيولة: {_smart_liq:.0f}% {_liq_label}\n"
        # 🆕 v6.4.108: Smart Momentum Insight
        try:
            from signals import get_momentum_insight
            _insight = get_momentum_insight(sym, "1h", 60)
            msg += f"💡 {_insight}\n"
        except Exception:
            pass
        msg += "\n📋 التفاصيل:\n"
        for r in sig["reasons"][:5]:
            msg += f"  • {r}\n"
        if halal_ruling == "halal":
            msg += "\n━━━━━━━━━━━━━━━━━━\n"
            msg += "🕌 <b>الحكم الشرعي: 🟢 حلال</b>\n"
        msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
        return msg
    except Exception as e:
        log.error(f"V2 format signal err: {e}")
        return f"🔄 {sig.get('symbol', '?')} — خطأ في التنسيق"


def _v2_smart_liquidity_pct(sig: Dict) -> float:
    """🆕 v6.4.101: نسبة السيولة الذكية لِـ V2 (Dip Buying)."""
    try:
        score = 0
        reasons = sig.get("reasons", [])
        # BTC bullish → +25
        if any("BTC: bullish" in r for r in reasons):
            score += 25
        # 4h فوق EMA20 → +20
        if any("فوق EMA20" in r for r in reasons):
            score += 20
        # 1h Dip + Recovery → +25
        if any("Dip + Recovery" in r for r in reasons):
            score += 25
        # Volume ≥ 1.5x → +15
        vol = sig.get("volume_ratio", 1.0)
        if vol >= 1.5:
            score += 15
        elif vol >= 1.0:
            score += 10
        # MACD bullish → +15
        if any("MACD" in r for r in reasons):
            score += 15
        return min(100.0, float(score))
    except Exception:
        return 0.0
