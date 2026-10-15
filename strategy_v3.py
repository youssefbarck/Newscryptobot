"""
strategy_v3.py — 🆕 v6.4.98: Pre-Pump Breakout Strategy (V3)
================================================================

🎯 الاستراتيجية:
   اكتشاف العملات قبل الانفجار السعري (Pre-Pump) عبر:
   - Accumulation (تجميع)
   - Higher Lows (قيعان مرتفعة)
   - Volatility Compression (انضغاط)
   - Resistance Pressure (ضغط على المقاومة)
   - Early Volume Expansion (توسع تدريجي في الحجم)
   - Liquidity Absorption (امتصاص السيولة)

⚙️ Multi-Timeframe:
   - 4H: الاتجاه العام (EMA20/40/200 filter)
   - 1H: بنية السوق + Accumulation + Higher Lows
   - 15M: Trigger / Entry (Breakout + Volume)

📊 Smart Scoring (100 نقطة):
   - Accumulation              +15
   - Higher Lows               +10
   - Clear Resistance          +10
   - Compression               +15
   - EMA Trend Improvement     +10
   - Price near EMA200         +5
   - Early Volume Expansion    +10
   - Breakout Volume ≥2x       +15
   - Successful Retest         +10

⚠️ Spot فقط — لا Futures، لا Short، لا رافعة مالية.
"""

import logging
import time
import os
import requests
from typing import Optional, Dict, List, Tuple

log = logging.getLogger("StrategyV3")

# ═══ Binance API (مباشر — لا dependency على engine.py) ═══
_BINANCE_BASE = "https://api.binance.com"
_BINANCE_FALLBACK = "https://data-api.binance.vision"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Cache داخلي (60s لكل رمز×فريم)
_CACHE: Dict = {}
_CACHE_TTL = 60


def _fetch_klines(symbol: str, interval: str, limit: int = 200) -> List[Dict]:
    """🆕 v6.4.125: يستخدم engine.fetch_klines (مصدر مركزي + cache مشترك).
    هذا يقلل طلبات Binance من 3× (V1+V2+V3 كل واحدة لوحدها) لِـ 1× (مصدر موحد).
    Cache محلي 60s لِـ V3 (لو نفس الرمز+الفريم طُلب مرتين في نفس الدقيقة).
    """
    try:
        cache_key = f"{symbol}_{interval}"
        now = time.time()
        if cache_key in _CACHE:
            ts, candles = _CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                return candles

        # استخدم engine.fetch_klines (لديه cache + KuCoin/Coinbase fallback + Binance block 30min)
        from engine import fetch_klines as _engine_fetch
        candles = _engine_fetch(symbol, interval, limit)
        if candles:
            _CACHE[cache_key] = (now, candles)
        return candles if candles else []
    except Exception as e:
        log.warning(f"V3 fetch_klines outer err: {e}")
        return []


# 🆕 v6.4.123: Legacy symbol mapping (MATIC → POL after Polygon 2.0 migration)
_V3_LEGACY_SYMBOL_MAP = {
    "MATIC": "POL",
}

# 🆕 v6.4.123: KuCoin fallback in V3 (independent from engine.py)
_V3_KUCOIN_URL = "https://api.kucoin.com/api/v1/market/candles"
_V3_KUCOIN_INTERVAL_MAP = {"5m": "5min", "15m": "15min", "1h": "1hour", "4h": "4hour", "1d": "1day"}


def _fetch_klines_kucoin_v3(symbol: str, interval: str, limit: int) -> List[Dict]:
    """🆕 v6.4.123: KuCoin fallback for V3 fetch_klines."""
    try:
        kc_interval = _V3_KUCOIN_INTERVAL_MAP.get(interval, "1day")
        sym_mapped = _V3_LEGACY_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        kc_symbol = f"{sym_mapped}-USDT"
        r = requests.get(_V3_KUCOIN_URL, params={
            "symbol": kc_symbol,
            "type": kc_interval,
            "limit": min(limit, 1500)
        }, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("code") != "200000" or not data.get("data"):
            return []
        candles = []
        for k in reversed(data["data"]):
            try:
                t_ms = int(k[0])
                candles.append({
                    "open_time": t_ms // 1000,
                    "open": float(k[1]),
                    "high": float(k[3]),
                    "low": float(k[4]),
                    "close": float(k[2]),
                    "volume": float(k[5]),
                    "close_time": (t_ms // 1000) + 60
                })
            except (ValueError, TypeError, IndexError):
                continue
        if candles:
            log.info(f"🦎 [V3-KUCOIN] {symbol} {interval} → {len(candles)} candles")
        return candles
    except Exception as e:
        log.warning(f"V3 KuCoin fetch {symbol}: {e}")
        return []


# 🆕 v6.4.123: Coinbase fallback in V3
_V3_COINBASE_URL = "https://api.exchange.coinbase.com/products/{symbol}/candles"
_V3_COINBASE_GRANULARITY = {
    "5m": "300", "15m": "900", "1h": "3600", "4h": "21600", "1d": "86400",
}


def _fetch_klines_coinbase_v3(symbol: str, interval: str, limit: int) -> List[Dict]:
    """🆕 v6.4.123: Coinbase fallback for V3 fetch_klines."""
    try:
        sym_mapped = _V3_LEGACY_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        cb_symbol = f"{sym_mapped}-USD"
        granularity = _V3_COINBASE_GRANULARITY.get(interval, "86400")
        url = _V3_COINBASE_URL.format(symbol=cb_symbol)
        r = requests.get(url, params={
            "granularity": granularity,
            "limit": min(limit, 300)
        }, headers=_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        if not data:
            return []
        candles = []
        for k in reversed(data):  # Coinbase: newest first
            try:
                t = int(k[0])
                candles.append({
                    "open_time": t,
                    "open": float(k[3]),
                    "high": float(k[2]),
                    "low": float(k[1]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": t + int(granularity)
                })
            except (ValueError, TypeError, IndexError):
                continue
        if candles:
            log.info(f"🪙 [V3-COINBASE] {symbol} {interval} → {len(candles)} candles")
        return candles
    except Exception as e:
        log.warning(f"V3 Coinbase fetch {symbol}: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# المؤشرات الفنية
# ═══════════════════════════════════════════════════════════

def _calc_ema(closes: List[float], period: int) -> float:
    """يحسب EMA لِآخر قيمة."""
    if not closes or len(closes) < period:
        return 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def _calc_ema_series(closes: List[float], period: int) -> List[float]:
    """يحسب EMA series (لكل قيمة)."""
    if not closes or len(closes) < period:
        return []
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    result = [0] * (period - 1) + [ema]
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
        result.append(ema)
    return result


def _calc_atr(candles: List[Dict], period: int = 14) -> float:
    """ATR (Average True Range)."""
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


def _calc_rsi(closes: List[float], period: int = 14) -> float:
    """RSI."""
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


def _calc_bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
    """Bollinger Bands → (middle, lower, upper)."""
    if len(closes) < period:
        sma = sum(closes) / len(closes) if closes else 0
        return sma, sma, sma
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std = variance ** 0.5
    return sma, sma - std_mult * std, sma + std_mult * std


def _calc_macd(closes: List[float]) -> Tuple[float, float, float, bool]:
    """MACD → (macd_line, signal_line, histogram, bullish_cross)."""
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
    # signal (9-period EMA of MACD)
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


def _calc_volume_ratio(candles: List[Dict], period: int = 20) -> float:
    """نسبة حجم الشمعة الأخيرة مقابل المتوسط."""
    if len(candles) < period:
        return 1.0
    avg_vol = sum(c["volume"] for c in candles[-period:]) / period
    if avg_vol == 0:
        return 1.0
    return candles[-1]["volume"] / avg_vol


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.122: Anchored VWAP (يومي + أسبوعي)
# ═══════════════════════════════════════════════════════════

def _calc_vwap(candles: List[Dict]) -> float:
    """🆕 v6.4.122: يحسب VWAP لِـ قائمة شمعات.
    VWAP = sum(typical_price * volume) / sum(volume)
    typical_price = (high + low + close) / 3
    """
    try:
        if not candles:
            return 0
        total_pv = 0
        total_v = 0
        for c in candles:
            tp = (c["high"] + c["low"] + c["close"]) / 3
            total_pv += tp * c["volume"]
            total_v += c["volume"]
        return total_pv / total_v if total_v > 0 else 0
    except Exception as e:
        log.warning(f"V3 _calc_vwap err: {e}")
        return 0


def _calc_anchored_vwap_daily(candles_1h: List[Dict]) -> Dict:
    """🆕 v6.4.122: VWAP يومي — يبدأ من بداية يوم UTC.
    يرجع: {vwap, distance_pct, position (above/below/at)}
    """
    try:
        if not candles_1h:
            return {"vwap": 0, "distance_pct": 0, "position": "unknown"}
        # ايجاد بداية اليوم UTC الحالي
        # نفترض آخر 24 شمعة 1h = يوم كامل
        daily_candles = candles_1h[-24:] if len(candles_1h) >= 24 else candles_1h
        vwap = _calc_vwap(daily_candles)
        if vwap <= 0:
            return {"vwap": 0, "distance_pct": 0, "position": "unknown"}
        cur = candles_1h[-1]["close"]
        dist_pct = ((cur - vwap) / vwap) * 100
        if abs(dist_pct) < 0.5:
            position = "at"
        elif dist_pct > 0:
            position = "above"
        else:
            position = "below"
        return {"vwap": vwap, "distance_pct": dist_pct, "position": position}
    except Exception as e:
        log.warning(f"V3 vwap_daily err: {e}")
        return {"vwap": 0, "distance_pct": 0, "position": "unknown"}


def _calc_anchored_vwap_weekly(candles_4h: List[Dict]) -> Dict:
    """🆕 v6.4.122: VWAP أسبوعي — يبدأ من بداية الأسبوع UTC.
    يرجع: {vwap, distance_pct, position (above/below/at)}
    """
    try:
        if not candles_4h:
            return {"vwap": 0, "distance_pct": 0, "position": "unknown"}
        # أسبوع = 7 أيام × 6 شمعات 4h = 42 شمعة
        weekly_candles = candles_4h[-42:] if len(candles_4h) >= 42 else candles_4h
        vwap = _calc_vwap(weekly_candles)
        if vwap <= 0:
            return {"vwap": 0, "distance_pct": 0, "position": "unknown"}
        cur = candles_4h[-1]["close"]
        dist_pct = ((cur - vwap) / vwap) * 100
        if abs(dist_pct) < 1.0:
            position = "at"
        elif dist_pct > 0:
            position = "above"
        else:
            position = "below"
        return {"vwap": vwap, "distance_pct": dist_pct, "position": position}
    except Exception as e:
        log.warning(f"V3 vwap_weekly err: {e}")
        return {"vwap": 0, "distance_pct": 0, "position": "unknown"}


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.122: Price Action — Market Structure (BOS/CHoCH)
# ═══════════════════════════════════════════════════════════

def _detect_market_structure(candles: List[Dict], lookback: int = 50) -> Dict:
    """🆕 v6.4.122: يحلل Market Structure (HH, HL, LH, LL, BOS, CHoCH).
    يرجع: {
        last_hh, last_hl, last_lh, last_ll,
        trend (uptrend/downtrend/range),
        bos (bool),  # Break of Structure (تأكيد الاتجاه)
        choch (bool),  # Change of Character (تغير الاتجاه)
        bos_level, choch_level
    }
    """
    try:
        if len(candles) < lookback:
            return {"trend": "unknown", "bos": False, "choch": False}
        recent = candles[-lookback:]
        # كشف swing highs/lows
        swing_highs = []
        swing_lows = []
        for i in range(2, len(recent) - 2):
            if (recent[i]["high"] > recent[i-1]["high"] and
                recent[i]["high"] > recent[i-2]["high"] and
                recent[i]["high"] > recent[i+1]["high"] and
                recent[i]["high"] > recent[i+2]["high"]):
                swing_highs.append((i, recent[i]["high"]))
            if (recent[i]["low"] < recent[i-1]["low"] and
                recent[i]["low"] < recent[i-2]["low"] and
                recent[i]["low"] < recent[i+1]["low"] and
                recent[i]["low"] < recent[i+2]["low"]):
                swing_lows.append((i, recent[i]["low"]))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {"trend": "insufficient", "bos": False, "choch": False}

        last_hh_idx, last_hh = swing_highs[-1]
        prev_hh_idx, prev_hh = swing_highs[-2]
        last_hl_idx, last_hl = swing_lows[-1]
        prev_hl_idx, prev_hl = swing_lows[-2]
        last_lh_idx, last_lh = swing_highs[0]
        last_ll_idx, last_ll = swing_lows[0]

        # اتجاه: HH + HL = صاعد | LH + LL = هابط | غير ذلك = range
        trend = "range"
        if last_hh > prev_hh and last_hl > prev_hl:
            trend = "uptrend"
        elif last_hh < prev_hh and last_hl < prev_hl:
            trend = "downtrend"

        # BOS: السعر كسر آخر swing high (صاعد) أو آخر swing low (هابط)
        cur = candles[-1]["close"]
        bos = False
        bos_level = 0
        choch = False
        choch_level = 0
        if trend == "uptrend":
            if cur > last_hh:
                bos = True
                bos_level = last_hh
            # CHoCH من هابط لِـ صاعد
            if len(swing_lows) >= 2 and cur > swing_highs[0][1]:
                choch = True
                choch_level = swing_highs[0][1]
        elif trend == "downtrend":
            if cur < last_hl:
                bos = True
                bos_level = last_hl
            if len(swing_highs) >= 2 and cur < swing_lows[0][1]:
                choch = True
                choch_level = swing_lows[0][1]

        return {
            "trend": trend,
            "last_hh": last_hh, "last_hl": last_hl,
            "last_lh": last_lh, "last_ll": last_ll,
            "bos": bos, "bos_level": bos_level,
            "choch": choch, "choch_level": choch_level,
            "swing_highs_count": len(swing_highs),
            "swing_lows_count": len(swing_lows),
        }
    except Exception as e:
        log.warning(f"V3 market_structure err: {e}")
        return {"trend": "unknown", "bos": False, "choch": False}


def _detect_candle_pattern(candles: List[Dict]) -> Dict:
    """🆕 v6.4.122: يكتشف أنماط الشموع (Engulfing, Pin Bar, Hammer, Doji).
    يرجع: {pattern, bullish, bearish, strength}
    """
    try:
        if len(candles) < 3:
            return {"pattern": "none", "bullish": False, "bearish": False, "strength": 0}
        last = candles[-1]
        prev = candles[-2]
        body_last = abs(last["close"] - last["open"])
        body_prev = abs(prev["close"] - prev["open"])
        range_last = last["high"] - last["low"]
        range_prev = prev["high"] - prev["low"]
        upper_wick = last["high"] - max(last["close"], last["open"])
        lower_wick = min(last["close"], last["open"]) - last["low"]

        pattern = "none"
        bullish = False
        bearish = False
        strength = 0

        # Bullish Engulfing
        if (prev["close"] < prev["open"] and  # prev red
            last["close"] > last["open"] and  # last green
            last["close"] >= prev["open"] and
            last["open"] <= prev["close"]):
            pattern = "Bullish Engulfing"
            bullish = True
            strength = 8

        # Bearish Engulfing
        elif (prev["close"] > prev["open"] and
              last["close"] < last["open"] and
              last["close"] <= prev["open"] and
              last["open"] >= prev["close"]):
            pattern = "Bearish Engulfing"
            bearish = True
            strength = 8

        # Hammer (bullish)
        elif (body_last < range_last * 0.3 and
              lower_wick > 2 * body_last and
              upper_wick < body_last):
            pattern = "Hammer"
            bullish = True
            strength = 6

        # Shooting Star (bearish)
        elif (body_last < range_last * 0.3 and
              upper_wick > 2 * body_last and
              lower_wick < body_last):
            pattern = "Shooting Star"
            bearish = True
            strength = 6

        # Doji (indecision)
        elif body_last < range_last * 0.1:
            pattern = "Doji"
            strength = 2

        # Bullish Marubozu (strong bullish)
        elif (last["close"] > last["open"] and
              body_last > range_last * 0.9):
            pattern = "Bullish Marubozu"
            bullish = True
            strength = 7

        # Bearish Marubozu
        elif (last["close"] < last["open"] and
              body_last > range_last * 0.9):
            pattern = "Bearish Marubozu"
            bearish = True
            strength = 7

        return {"pattern": pattern, "bullish": bullish, "bearish": bearish, "strength": strength}
    except Exception as e:
        log.warning(f"V3 candle_pattern err: {e}")
        return {"pattern": "none", "bullish": False, "bearish": False, "strength": 0}


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.122: Volume Profile (POC, VAH, VAL)
# ═══════════════════════════════════════════════════════════

def _calc_volume_profile(candles: List[Dict], num_bins: int = 50) -> Dict:
    """🆕 v6.4.122: يحسب Volume Profile من قائمة شمعات.
    يرجع: {
        poc,  # Point of Control (أعلى مستوى حجم)
        vah,  # Value Area High (70% من الحجم)
        val,  # Value Area Low (70% من الحجم)
        current_poc_position,  # above/below/at
        strongest_levels (list of (price, volume))
    }
    """
    try:
        if len(candles) < 20:
            return {"poc": 0, "vah": 0, "val": 0}
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        all_volumes = [c["volume"] for c in candles]
        price_min = min(lows)
        price_max = max(highs)
        if price_max <= price_min:
            return {"poc": 0, "vah": 0, "val": 0}
        # إنشاء bins
        bin_size = (price_max - price_min) / num_bins
        bins = [0.0] * num_bins
        for c in candles:
            # توزيع حجم الشمعة على bins
            low_bin = int((c["low"] - price_min) / bin_size)
            high_bin = int((c["high"] - price_min) / bin_size)
            low_bin = max(0, min(num_bins - 1, low_bin))
            high_bin = max(0, min(num_bins - 1, high_bin))
            if high_bin == low_bin:
                bins[low_bin] += c["volume"]
            else:
                per_bin = c["volume"] / (high_bin - low_bin + 1)
                for b in range(low_bin, high_bin + 1):
                    bins[b] += per_bin

        # POC = أعلى bin
        poc_bin = bins.index(max(bins))
        poc = price_min + (poc_bin + 0.5) * bin_size

        # Value Area = 70% من الحجم حول POC
        total_vol = sum(bins)
        target_va = total_vol * 0.70
        va_vol = bins[poc_bin]
        low_idx = poc_bin
        high_idx = poc_bin
        while va_vol < target_va and (low_idx > 0 or high_idx < num_bins - 1):
            # اختار الجانب الأعلى
            left_vol = bins[low_idx - 1] if low_idx > 0 else 0
            right_vol = bins[high_idx + 1] if high_idx < num_bins - 1 else 0
            if left_vol >= right_vol and low_idx > 0:
                low_idx -= 1
                va_vol += bins[low_idx]
            elif high_idx < num_bins - 1:
                high_idx += 1
                va_vol += bins[high_idx]
            else:
                break
        vah = price_min + (high_idx + 1) * bin_size
        val = price_min + low_idx * bin_size

        # موقع السعر الحالي من POC
        cur = candles[-1]["close"]
        if abs(cur - poc) / poc < 0.005:
            cur_pos = "at_poc"
        elif cur > poc:
            cur_pos = "above_poc"
        else:
            cur_pos = "below_poc"

        # أقوى 3 مستويات
        top_bins = sorted(range(len(bins)), key=lambda i: -bins[i])[:3]
        strongest = [(price_min + (b + 0.5) * bin_size, bins[b]) for b in top_bins]

        return {
            "poc": poc,
            "vah": vah,
            "val": val,
            "current_poc_position": cur_pos,
            "strongest_levels": strongest,
        }
    except Exception as e:
        log.warning(f"V3 volume_profile err: {e}")
        return {"poc": 0, "vah": 0, "val": 0}


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.98: Pre-Pump Detection Components
# ═══════════════════════════════════════════════════════════

def _find_swing_levels(candles: List[Dict], lookback: int = 30) -> Tuple[List[float], List[float]]:
    """يجد swing highs (resistances) و swing lows (supports)."""
    resistances = []
    supports = []
    for i in range(2, min(len(candles) - 2, lookback + 2)):
        if (candles[i]["high"] > candles[i-1]["high"] and
            candles[i]["high"] > candles[i-2]["high"] and
            candles[i]["high"] > candles[i+1]["high"] and
            candles[i]["high"] > candles[i+2]["high"]):
            resistances.append(candles[i]["high"])
        if (candles[i]["low"] < candles[i-1]["low"] and
            candles[i]["low"] < candles[i-2]["low"] and
            candles[i]["low"] < candles[i+1]["low"] and
            candles[i]["low"] < candles[i+2]["low"]):
            supports.append(candles[i]["low"])
    resistances.sort()
    supports.sort(reverse=True)
    return resistances, supports


def _detect_accumulation(candles: List[Dict], lookback: int = 30) -> Tuple[bool, float]:
    """🆕 v6.4.98: يكتشف Accumulation (تجميع بعد هبوط).
    يرجع: (is_accumulating, accumulation_score 0-1)
    """
    try:
        if len(candles) < lookback:
            return False, 0
        # آخر lookback شمعة
        recent = candles[-lookback:]
        # هل هبط سابقاً ثم استقر؟
        first_third = recent[:lookback // 3]
        last_third = recent[-lookback // 3:]
        first_low = min(c["low"] for c in first_third)
        last_low = min(c["low"] for c in last_third)
        first_high = max(c["high"] for c in first_third)
        last_high = max(c["high"] for c in last_third)
        # Accumulation: السعر استقر (النطاق ضيق + القاع لم يهبط أكثر)
        range_first = first_high - first_low
        range_last = last_high - last_low
        # النطاق الأخير يجب أن يكون أضيق أو مساوي
        if range_last <= range_first * 1.1:
            # القاع الأخير ≥ القاع الأول (لا هبوط جديد)
            if last_low >= first_low * 0.98:
                # حساب درجة التجميع
                compression_ratio = range_last / range_first if range_first > 0 else 1
                score = max(0, 1 - compression_ratio)  # 0-1
                return True, min(1.0, score + 0.3)  # +0.3 لِـ الاستقرار
        return False, 0
    except Exception as e:
        log.warning(f"V3 _detect_accumulation err: {e}")
        return False, 0


def _detect_higher_lows(candles: List[Dict], lookback: int = 30) -> Tuple[bool, int, List[float]]:
    """🆕 v6.4.98: يكتشف Higher Lows (قيعان مرتفعة).
    يرجع: (has_higher_lows, count, lows_list)
    """
    try:
        _, supports = _find_swing_levels(candles, lookback=lookback)
        if len(supports) < 2:
            return False, 0, []
        # supports مرتبة تنازلياً (الأقرب أولاً)
        # نريد: كل قاع أحدث ≥ القاع السابق (higher low)
        # supports[0] = الأحدث، supports[1] = الذي قبله...
        # Higher low: supports[0] > supports[1] > supports[2]...
        higher_count = 0
        for i in range(len(supports) - 1):
            if supports[i] > supports[i + 1]:
                higher_count += 1
            else:
                break
        # نحتاج على الأقل 2 higher lows متتالية
        if higher_count >= 2:
            return True, higher_count, supports[:higher_count + 1]
        return False, 0, []
    except Exception as e:
        log.warning(f"V3 _detect_higher_lows err: {e}")
        return False, 0, []


def _detect_compression(candles: List[Dict], lookback: int = 20) -> Tuple[bool, float, float]:
    """🆕 v6.4.98: يكتشف Volatility Compression (انضغاط ATR).
    يرجع: (is_compressing, current_atr, atr_ratio)
    atr_ratio = current_atr / avg_atr (< 1 = compression)
    """
    try:
        if len(candles) < lookback:
            return False, 0, 1.0
        atr_period = 14
        recent = candles[-lookback:]
        # ATR الحالي
        current_atr = _calc_atr(recent, atr_period)
        # ATR التاريخي (آخر 50 شمعة)
        if len(candles) >= 50:
            historical_atr = _calc_atr(candles[-50:], atr_period)
        else:
            historical_atr = current_atr
        if historical_atr == 0:
            return False, current_atr, 1.0
        atr_ratio = current_atr / historical_atr
        # Compression: ATR الحالي < 80% من التاريخي
        if atr_ratio < 0.8:
            return True, current_atr, atr_ratio
        return False, current_atr, atr_ratio
    except Exception as e:
        log.warning(f"V3 _detect_compression err: {e}")
        return False, 0, 1.0


def _detect_resistance_pressure(candles: List[Dict], resistance: float, lookback: int = 30) -> Tuple[bool, int, float]:
    """🆕 v6.4.98: يكتشف Resistance Pressure (السعر يقترب من المقاومة عدة مرات).
    يرجع: (has_pressure, touch_count, distance_pct)
    """
    try:
        if resistance <= 0:
            return False, 0, 100
        recent = candles[-lookback:]
        cur_price = recent[-1]["close"]
        # كم مرة السعر اقترب من المقاومة (داخل 2%)
        touch_count = 0
        for c in recent:
            if abs(c["high"] - resistance) / resistance < 0.02:
                touch_count += 1
        distance_pct = ((resistance - cur_price) / cur_price) * 100
        # Pressure: touch_count ≥ 2 و السعر قريب من المقاومة
        if touch_count >= 2 and distance_pct < 5:
            return True, touch_count, distance_pct
        return False, touch_count, distance_pct
    except Exception as e:
        log.warning(f"V3 _detect_resistance_pressure err: {e}")
        return False, 0, 100


def _detect_early_volume_expansion(candles: List[Dict], lookback: int = 10) -> Tuple[bool, float, List[float]]:
    """🆕 v6.4.98: يكتشف Early Volume Expansion (الحجم يرتفع تدريجياً قبل الانفجار).
    يرجع: (is_expanding, latest_ratio, volume_ratios)
    volume_ratios = آخر 5 شمعات (نسبة لِـ المتوسط)
    """
    try:
        if len(candles) < lookback + 20:
            return False, 1.0, []
        avg_vol = sum(c["volume"] for c in candles[-30:-5]) / 25  # متوسط آخر 25 شمعة (بدون آخر 5)
        if avg_vol == 0:
            return False, 1.0, []
        # آخر 5 شمعات: هل الحجم يرتفع تدريجياً؟
        last_5 = candles[-5:]
        ratios = [c["volume"] / avg_vol for c in last_5]
        # Early expansion: آخر 3 شمعات ≥ 1.0x وترتفع تدريجياً
        if (ratios[-1] >= 1.0 and ratios[-2] >= 1.0 and
            ratios[-3] >= 1.0 and ratios[-1] >= ratios[-3]):
            # هل النشاط يرتفع؟ (آخر > ثالث من آخر)
            if ratios[-1] >= ratios[-3]:
                return True, ratios[-1], ratios
        return False, ratios[-1] if ratios else 1.0, ratios
    except Exception as e:
        log.warning(f"V3 _detect_volume_expansion err: {e}")
        return False, 1.0, []


def _detect_breakout(candles: List[Dict], resistance: float) -> Tuple[bool, float, float]:
    """🆕 v6.4.98: يكتشف Breakout (إغلاق فوق المقاومة + volume).
    يرجع: (is_breakout, breakout_strength, volume_ratio)
    """
    try:
        if resistance <= 0 or len(candles) < 2:
            return False, 0, 1.0
        last = candles[-1]
        prev = candles[-2]
        # Breakout: إغلاق آخر شمعة فوق المقاومة
        if last["close"] > resistance:
            # Volume expansion
            vol_ratio = _calc_volume_ratio(candles, 20)
            # Strength = (close - resistance) / resistance
            strength = ((last["close"] - resistance) / resistance) * 100
            # Bullish candle (close > open)
            if last["close"] > last["open"] and vol_ratio >= 1.3:
                return True, strength, vol_ratio
        return False, 0, 1.0
    except Exception as e:
        log.warning(f"V3 _detect_breakout err: {e}")
        return False, 0, 1.0


def _detect_retest(candles: List[Dict], resistance: float, lookback: int = 10) -> Tuple[bool, str]:
    """🆕 v6.4.98: يكتشف Retest (السعر عاد لِـ المقاومة + ارتداد).
    يرجع: (is_retest, retest_type)
    retest_type: "successful" / "in_progress" / "none"
    """
    try:
        if resistance <= 0 or len(candles) < lookback:
            return False, "none"
        recent = candles[-lookback:]
        # هل السعر اخترق المقاومة ثم عاد إليها؟
        broke_above = False
        for c in recent:
            if c["close"] > resistance:
                broke_above = True
                break
        if not broke_above:
            return False, "none"
        # بعد الاختراق، هل عاد قرب المقاومة؟
        last = candles[-1]
        distance = abs(last["close"] - resistance) / resistance
        if distance < 0.01:  # داخل 1%
            # هل ارتد صعوداً؟
            if last["close"] > last["open"]:  # شمعة صاعدة
                return True, "successful"
            return True, "in_progress"
        return False, "none"
    except Exception as e:
        log.warning(f"V3 _detect_retest err: {e}")
        return False, "none"


def _detect_already_pumped(candles: List[Dict], lookback: int = 24) -> Tuple[bool, float]:
    """🆕 v6.4.98: يكتشف Already-Pumped (السعر ارتفع +20% أو أكثر).
    يرجع: (is_already_pumped, pump_pct)
    """
    try:
        if len(candles) < lookback:
            return False, 0
        recent = candles[-lookback:]
        low = min(c["low"] for c in recent)
        high = max(c["high"] for c in recent)
        cur = recent[-1]["close"]
        # Pump = ارتفاع ≥ 20% من القاع
        if low > 0:
            pump_pct = ((cur - low) / low) * 100
            if pump_pct >= 20:
                return True, pump_pct
        return False, 0
    except Exception as e:
        log.warning(f"V3 _detect_already_pumped err: {e}")
        return False, 0


# ═══════════════════════════════════════════════════════════
# 4H Trend Filter
# ═══════════════════════════════════════════════════════════

def _analyze_4h_trend(candles_4h: List[Dict]) -> Dict:
    """🆕 v6.4.98: يحلل 4h trend (EMA20/40/200 filter).
    يرجع: {trend, ema20, ema40, ema200, ema20_rising, ema40_stabilizing, near_ema200, score}
    """
    try:
        closes = [c["close"] for c in candles_4h]
        if len(closes) < 50:
            return {"trend": "unknown", "score": 0}
        ema20 = _calc_ema(closes, 20)
        ema40 = _calc_ema(closes, 40)
        ema200 = _calc_ema(closes, min(200, len(closes)))
        cur = closes[-1]
        # EMA20 rising? (يقارن بِـ EMA20 من 5 شمعات سابقة)
        ema20_series = _calc_ema_series(closes[-25:], 20)
        ema20_rising = len(ema20_series) >= 2 and ema20_series[-1] > ema20_series[-6] if len(ema20_series) >= 6 else False
        # EMA40 stabilizing? (لا يهبط بسرعة)
        ema40_series = _calc_ema_series(closes[-45:], 40)
        ema40_stabilizing = False
        if len(ema40_series) >= 6:
            recent_change = (ema40_series[-1] - ema40_series[-6]) / ema40_series[-6] if ema40_series[-6] > 0 else 0
            ema40_stabilizing = recent_change > -0.02  # لا يهبط أكثر من 2%
        # Near EMA200?
        near_ema200 = abs(cur - ema200) / ema200 < 0.05 if ema200 > 0 else False
        # Trend
        trend = "neutral"
        if cur > ema20 > ema40:
            trend = "bullish"
        elif cur < ema20 < ema40:
            trend = "bearish"
        # Score
        score = 0
        if ema20_rising:
            score += 5
        if ema40_stabilizing:
            score += 5
        if near_ema200:
            score += 5
        if trend == "bullish":
            score += 5
        return {
            "trend": trend,
            "ema20": ema20,
            "ema40": ema40,
            "ema200": ema200,
            "ema20_rising": ema20_rising,
            "ema40_stabilizing": ema40_stabilizing,
            "near_ema200": near_ema200,
            "score": min(15, score),  # max 15 نقطة
        }
    except Exception as e:
        log.warning(f"V3 _analyze_4h_trend err: {e}")
        return {"trend": "unknown", "score": 0}


# ═══════════════════════════════════════════════════════════
# 1H Accumulation Analysis
# ═══════════════════════════════════════════════════════════

def _analyze_1h_accumulation(candles_1h: List[Dict]) -> Dict:
    """🆕 v6.4.98: يحلل 1h accumulation (Higher Lows + Compression + Resistance).
    يرجع: {accumulation, higher_lows, compression, resistance, resistance_pressure, score}
    """
    try:
        score = 0
        # Accumulation
        is_acc, acc_score = _detect_accumulation(candles_1h, lookback=30)
        if is_acc:
            score += int(15 * acc_score)  # max 15
        # Higher Lows
        has_hl, hl_count, lows = _detect_higher_lows(candles_1h, lookback=30)
        if has_hl:
            score += min(10, hl_count * 3)  # max 10
        # Compression
        is_comp, atr_now, atr_ratio = _detect_compression(candles_1h, lookback=20)
        if is_comp:
            score += 15  # max 15
        # Resistance
        resistances, _ = _find_swing_levels(candles_1h, lookback=30)
        main_resistance = min(resistances, key=lambda r: abs(r - candles_1h[-1]["close"])) if resistances else 0
        # Resistance Pressure
        has_pressure, touch_count, distance = _detect_resistance_pressure(candles_1h, main_resistance, lookback=30)
        if has_pressure:
            score += min(10, touch_count * 2)  # max 10
        return {
            "accumulation": is_acc,
            "accumulation_score": acc_score,
            "higher_lows": has_hl,
            "higher_lows_count": hl_count,
            "higher_lows_list": lows,
            "compression": is_comp,
            "atr": atr_now,
            "atr_ratio": atr_ratio,
            "resistance": main_resistance,
            "resistance_pressure": has_pressure,
            "resistance_touches": touch_count,
            "distance_to_resistance_pct": distance,
            "score": min(50, score),  # max 50 (15+10+15+10)
        }
    except Exception as e:
        log.warning(f"V3 _analyze_1h_accumulation err: {e}")
        return {"score": 0}


# ═══════════════════════════════════════════════════════════
# 15M Trigger Analysis
# ═══════════════════════════════════════════════════════════

def _analyze_15m_trigger(candles_15m: List[Dict], resistance: float) -> Dict:
    """🆕 v6.4.98: يحلل 15m trigger (Breakout + Volume + Retest).
    يرجع: {breakout, volume_expansion, retest, entry_type, score}
    """
    try:
        score = 0
        entry_type = "EARLY"  # افتراضي
        # Early Volume Expansion
        is_vol_exp, vol_ratio, vol_ratios = _detect_early_volume_expansion(candles_15m)
        if is_vol_exp:
            score += min(10, int((vol_ratio - 1) * 10))  # max 10
        # Breakout
        is_breakout, breakout_strength, breakout_vol = _detect_breakout(candles_15m, resistance)
        if is_breakout:
            score += 15  # max 15
            if breakout_vol >= 2.0:
                score += 5  # bonus
            entry_type = "BREAKOUT"
        # Retest
        is_retest, retest_type = _detect_retest(candles_15m, resistance)
        if is_retest and retest_type == "successful":
            score += 10  # max 10
            entry_type = "RETEST"
        return {
            "breakout": is_breakout,
            "breakout_strength": breakout_strength,
            "breakout_volume": breakout_vol,
            "volume_expansion": is_vol_exp,
            "volume_ratio": vol_ratio,
            "volume_ratios": vol_ratios,
            "retest": is_retest,
            "retest_type": retest_type,
            "entry_type": entry_type,
            "score": min(30, score),  # max 30 (10+15+5+10)
        }
    except Exception as e:
        log.warning(f"V3 _analyze_15m_trigger err: {e}")
        return {"score": 0, "entry_type": "EARLY"}


# ═══════════════════════════════════════════════════════════
# Smart Scoring (100 points)
# ═══════════════════════════════════════════════════════════

def _classify_score(score: int) -> str:
    """🆕 v6.4.98: يصنف Score."""
    if score >= 80:
        return "VERY STRONG"
    if score >= 70:
        return "STRONG WATCH"
    if score >= 60:
        return "EARLY SETUP"
    return "IGNORE"


def _get_btc_trend_v3() -> str:
    """🆕 v6.4.109: BTC trend filter محلي لِـ V3 (لا dependency على strategy_v2)."""
    try:
        candles = _fetch_klines("BTC", "4h", 100)
        if not candles or len(candles) < 50:
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


# ═══════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════

def detect_pre_pump_signal(symbol: str) -> Optional[Dict]:
    """🆕 v6.4.117: V3 = Pre-Pump Detection Engine (إعادة بناء احترافية).

    يكتشف 3 مراحل:
      A. PRE-PUMP WATCH — إعداد مبكر بدلائل مؤكدة
      B. MOMENTUM IGNITION — تسارع السعر مع نشاط شراء فعلي
      C. CONFIRMED BREAKOUT — اختراق مؤكد فوق مقاومة

    المنطق:
      1. 4H: EMA20 > EMA50 (اتجاه صاعد) + BTC ليس هابط
      2. 1H: مقاومة + دعم + تصنيف المرحلة + فحص Already-Pumped
      3. 15M: Volume + شمعة + Momentum state
      4. 5M/1M: فحص مبكر للضغط الشرائي (إن أمكن)

    Score: 0-100 (Technical Setup Score — وليس احتمال نجاح)
    """
    try:
        # ═══ 1) BTC trend filter ═══
        btc_trend = _get_btc_trend_v3()
        if btc_trend == "bearish":
            log.info(f"🚀 [V3] {symbol} — تخطي: BTC 4h هابط")
            return None

        # ═══ 2) 4H trend ═══
        candles_4h = _fetch_klines(symbol, "4h", 100)
        if not candles_4h or len(candles_4h) < 50:
            return None
        closes_4h = [c["close"] for c in candles_4h]
        ema20_4h = _calc_ema(closes_4h, 20)
        ema50_4h = _calc_ema(closes_4h, 50)
        ema200_4h = _calc_ema(closes_4h, min(200, len(closes_4h)))
        cur_4h = closes_4h[-1]
        # 🆕 v6.4.120: 4h filter مرن — يقبل EMA20>EMA50 OR السعر فوق EMA200 (اتجاه صاعد على المدى الطويل)
        ema20_4h_series = _calc_ema_series(closes_4h[-25:], 20) if len(closes_4h) >= 25 else []
        ema20_4h_rising = len(ema20_4h_series) >= 6 and ema20_4h_series[-1] > ema20_4h_series[-6]
        _4h_strong_uptrend = ema20_4h > ema50_4h
        _4h_recovering = cur_4h > ema200_4h and ema20_4h_rising  # فوق EMA200 و EMA20 يرتفع
        if not (_4h_strong_uptrend or _4h_recovering):
            log.info(f"🚀 [V3] {symbol} — تخطي: 4h ليس صاعد ولا في مرحلة تعافي (EMA20={ema20_4h:.4f} EMA50={ema50_4h:.4f} EMA200={ema200_4h:.4f} cur={cur_4h:.4f})")
            return None

        # 🆕 v6.4.122: Anchored VWAP أسبوعي (4h candles)
        vwap_weekly = _calc_anchored_vwap_weekly(candles_4h)
        # 🆕 v6.4.122: Market Structure على 4h (BOS/CHoCH)
        ms_4h = _detect_market_structure(candles_4h, lookback=50)

        # ═══ 3) 1H: مقاومة + دعم + حالة السعر ═══
        candles_1h = _fetch_klines(symbol, "1h", 100)
        if not candles_1h or len(candles_1h) < 50:
            return None
        closes_1h = [c["close"] for c in candles_1h]
        resistances, supports = _find_swing_levels(candles_1h, lookback=30)
        # 🆕 v6.4.120: لو لا توجد مقاومة على 1h → استخدم ATR-based resistance
        if not resistances:
            atr_1h = _calc_atr(candles_1h, 14)
            if atr_1h > 0:
                resistances = [closes_1h[-1] + 2.5 * atr_1h]  # مقاومة افتراضية = السعر + 2.5*ATR
                log.info(f"🚀 [V3] {symbol} — لا توجد مقاومة على 1h → استخدام مقاومة ATR افتراضية")
            else:
                log.info(f"🚀 [V3] {symbol} — تخطي: لا توجد مقاومة و ATR=0 على 1h")
                return None

        cur_1h = closes_1h[-1]
        last_1h_candle = candles_1h[-1]

        # 🆕 v6.4.122: Anchored VWAP يومي (1h candles)
        vwap_daily = _calc_anchored_vwap_daily(candles_1h)
        # 🆕 v6.4.122: Volume Profile على 1h (POC, VAH, VAL)
        vp_1h = _calc_volume_profile(candles_1h[-50:], num_bins=50)
        # 🆕 v6.4.122: Candle Pattern على آخر شمعتين 1h
        cp_1h = _detect_candle_pattern(candles_1h)
        # 🆕 v6.4.122: Market Structure على 1h
        ms_1h = _detect_market_structure(candles_1h, lookback=30)

        # 🆕 v6.4.117: أقرب مقاومة فوق السعر الحالي فقط (ليست مكسورة)
        # 🆕 v6.4.120: لو لا توجد مقاومة فوق السعر → استخدم 1.05x السعر الحالي (مستوى نفسي)
        resistances_above = [r for r in resistances if r > cur_1h * 1.001]
        if not resistances_above:
            # السعر اخترق كل المقاومات المعروفة → استخدم 1.05x كـ مقاومة نفسية
            resistance = cur_1h * 1.05
            resistances_above = [resistance]
            log.info(f"🚀 [V3] {symbol} — لا توجد مقاومة فوق السعر → استخدام مقاومة نفسية 1.05x")
        else:
            resistance = min(resistances_above, key=lambda r: r - cur_1h)
        dist_to_res = (resistance - cur_1h) / cur_1h

        # 🆕 v6.4.117: تحديد مرحلة الإعداد
        # A. PRE-PUMP WATCH: السعر قرب المقاومة (داخل 5%) ولم يكسرها
        # B. MOMENTUM IGNITION: السعر بدأ يخترق + Volume مرتفع
        # C. CONFIRMED BREAKOUT: إغلاق فوق المقاومة + Volume ≥ 1.5x
        # 🆕 v6.4.120: PRE-PUMP WATCH يقبل حتى 8% (كان 5%)
        has_breakout = last_1h_candle["close"] > resistance
        has_bullish_candle = last_1h_candle["close"] > last_1h_candle["open"]

        if has_breakout and has_bullish_candle:
            # تحقق لو إغلاق مؤكد (وليس مجرد wick)
            if last_1h_candle["close"] > resistance * 1.005:
                stage = "CONFIRMED BREAKOUT"
            else:
                stage = "MOMENTUM IGNITION"
        elif dist_to_res < 0.08:
            stage = "PRE-PUMP WATCH"
        else:
            log.info(f"🚀 [V3] {symbol} — تخطي: بعيد عن المقاومة ({dist_to_res*100:.1f}% > 8%)")
            return None

        # 🆕 v6.4.117: Already-Pumped check (لا يدخل بعد +15%+)
        # 🆕 v6.4.120: رفع الحد لِـ +25% (كان +15%) — العديد من الـ pumps الحقيقية لها تصحيحات وسيطة
        is_pumped, pump_pct = _detect_already_pumped(candles_1h, lookback=24)
        if is_pumped and pump_pct >= 25:
            log.info(f"🚀 [V3] {symbol} — تخطي: Already Pumped (+{pump_pct:.1f}%)")
            return None

        # ═══ 4) 15M: Volume + Momentum ═══
        candles_15m = _fetch_klines(symbol, "15m", 100)
        if not candles_15m or len(candles_15m) < 30:
            return None
        closes_15m = [c["close"] for c in candles_15m]
        vol_ratio = _calc_volume_ratio(candles_15m)
        last_15m = candles_15m[-1]
        last_15m_bullish = last_15m["close"] > last_15m["open"]

        # 🆕 v6.4.117: RSI + MACD على 15m لِـ Momentum state
        rsi_15m = _calc_rsi(closes_15m)
        macd_line, signal_line, hist, bullish_cross = _calc_macd(closes_15m)
        rsi_prev = _calc_rsi(closes_15m[:-1]) if len(closes_15m) > 15 else rsi_15m
        rsi_rising = rsi_15m > rsi_prev

        # 🆕 v6.4.117: Momentum state classification
        momentum_evidence_bull = 0
        momentum_evidence_bear = 0
        if rsi_rising and rsi_15m > 50:
            momentum_evidence_bull += 2
        elif not rsi_rising and rsi_15m < 40:
            momentum_evidence_bear += 2
        if hist > 0 or bullish_cross:
            momentum_evidence_bull += 1
        elif hist < 0:
            momentum_evidence_bear += 1
        if last_15m_bullish:
            momentum_evidence_bull += 1
        else:
            momentum_evidence_bear += 1

        if momentum_evidence_bull >= 3 and momentum_evidence_bear <= 1:
            momentum_state = "STRENGTHENING"
        elif momentum_evidence_bull >= 2 and momentum_evidence_bear <= 2:
            momentum_state = "STABLE"
        elif momentum_evidence_bear >= 3 and momentum_evidence_bull <= 1:
            momentum_state = "WEAKENING"
        elif momentum_evidence_bear >= 2 and momentum_evidence_bull >= 2:
            momentum_state = "REVERSING"
        else:
            momentum_state = "INSUFFICIENT DATA"

        # 🆕 v6.4.117: لا تنشر لو الزخم ضعيف جداً
        # 🆕 v6.4.120: لا ترفض لو الزخم ضعيف لكن توجد أدلة قوية (Volume مرتفع أو قرب المقاومة جداً)
        if momentum_state == "WEAKENING" and stage != "CONFIRMED BREAKOUT":
            # استثناء: لو Volume ≥ 1.5x أو قرب المقاومة < 2% → اقبل
            if not (vol_ratio >= 1.5 or dist_to_res < 0.02):
                log.info(f"🚀 [V3] {symbol} — تخطي: Momentum {momentum_state} + stage {stage} + لا أدلة قوية")
                return None
            log.info(f"🚀 [V3] {symbol} — Momentum {momentum_state} لكن Volume {vol_ratio:.1f}x أو قرب المقاومة ({dist_to_res*100:.1f}%) → مقبول")
            momentum_state = f"STABLE (was WEAKENING)"

        # ═══ 5) Intelligent Confidence Scoring ═══
        score = 0
        # أدلة مستقلة (لا تكرار):
        # 1. 4h EMA20 > EMA50 (اتجاه صاعد قوي)
        if _4h_strong_uptrend:
            score += 10
        elif _4h_recovering:
            score += 7  # تعافي بدل اتجاه قوي
        # 2. BTC ليس هابط (سوق)
        if btc_trend != "bearish":
            score += 5
        if btc_trend == "bullish":
            score += 5
        # 3. Volume expansion (مشاركة)
        if vol_ratio >= 2.0:
            score += 15
        elif vol_ratio >= 1.5:
            score += 10
        elif vol_ratio >= 1.3:
            score += 5
        # 4. قرب المقاومة (ضغط)
        if dist_to_res < 0.02:
            score += 10
        elif dist_to_res < 0.05:
            score += 5
        elif dist_to_res < 0.08:  # 🆕 v6.4.120
            score += 3
        # 5. Breakout confirmed (اختراق)
        if stage == "CONFIRMED BREAKOUT":
            score += 15
        elif stage == "MOMENTUM IGNITION":
            score += 10
        # 6. Momentum state
        if momentum_state == "STRENGTHENING":
            score += 10
        elif momentum_state == "STABLE":
            score += 5
        # 7. Above EMA20 on 4h
        if cur_4h > ema20_4h:
            score += 5
        # 8. RSI 15m > 50
        if rsi_15m > 50:
            score += 5
        # 🆕 v6.4.122: 9. VWAP يومي — السعر فوق VWAP = المؤسسات في ربح
        vwap_d = vwap_daily.get("vwap", 0)
        vwap_d_pos = vwap_daily.get("position", "unknown")
        if vwap_d > 0 and vwap_d_pos == "above":
            score += 8
        elif vwap_d > 0 and vwap_d_pos == "at":
            score += 5  # عند VWAP = نقطة مراقبة
        # 🆕 v6.4.122: 10. VWAP أسبوعي — تأكيد الاتجاه على المدى الطويل
        vwap_w = vwap_weekly.get("vwap", 0)
        vwap_w_pos = vwap_weekly.get("position", "unknown")
        if vwap_w > 0 and vwap_w_pos == "above":
            score += 7
        # 🆕 v6.4.122: 11. Market Structure على 4h
        ms_4h_trend = ms_4h.get("trend", "unknown")
        ms_4h_bos = ms_4h.get("bos", False)
        if ms_4h_trend == "uptrend":
            score += 8
        elif ms_4h_trend == "range" and stage == "CONFIRMED BREAKOUT":
            score += 5
        if ms_4h_bos:
            score += 5  # BOS تأكيد إضافي
        # 🆕 v6.4.122: 12. Market Structure على 1h — صاعد = قوي
        ms_1h_trend = ms_1h.get("trend", "unknown")
        if ms_1h_trend == "uptrend":
            score += 5
        # 🆕 v6.4.122: 13. Candle Pattern (آخر شمعة 1h)
        cp_pattern = cp_1h.get("pattern", "none")
        cp_bullish = cp_1h.get("bullish", False)
        cp_strength = cp_1h.get("strength", 0)
        if cp_bullish:
            score += min(8, cp_strength)  # max 8 (Bullish Engulfing = 8)
        elif cp_1h.get("bearish", False):
            score -= min(5, cp_strength)
        # 🆕 v6.4.122: 14. Volume Profile — السعر فوق POC = سيولة محتكرة
        poc = vp_1h.get("poc", 0)
        vp_position = vp_1h.get("current_poc_position", "unknown")
        if poc > 0 and vp_position == "above_poc":
            score += 6
        elif poc > 0 and vp_position == "at_poc":
            score += 3  # عند POC = محتمل الارتداد

        # 🆕 v6.4.117: Penalties
        # لو السعر فوق EMA200 بِكثير (مبالغ فيه)
        if ema200_4h > 0 and cur_4h > ema200_4h * 1.5:
            score -= 10
        # لو Volume ضعيف جداً
        if vol_ratio < 1.0:
            score -= 10
        # لو المقاومة بعيدة
        if dist_to_res > 0.04:
            score -= 5
        # لو RSI مرتفع جداً (تشبع)
        if rsi_15m > 80:
            score -= 10
        # لو الزخم ضعيف
        if momentum_state in ("WEAKENING", "REVERSING"):
            score -= 15
        # لو BTC محايد فقط (ليس صاعد)
        if btc_trend == "neutral":
            score -= 5
        # 🆕 v6.4.122: VWAP penalties
        if vwap_d > 0 and vwap_d_pos == "below":
            score -= 8  # تحت VWAP اليومي = البائعين في السيطرة
        if vwap_w > 0 and vwap_w_pos == "below":
            score -= 5  # تحت VWAP الأسبوعي = اتجاه طويل ضعيف
        # 🆕 v6.4.122: Market Structure penalties
        if ms_4h_trend == "downtrend":
            score -= 10  # اتجاه هابط = تجنب
        if ms_1h_trend == "downtrend":
            score -= 5
        # 🆕 v6.4.122: Volume Profile penalties
        if poc > 0 and vp_position == "below_poc":
            score -= 5  # تحت POC = السيولة فوق السعر
        # 🆕 v6.4.122: Bearish candle pattern
        if cp_1h.get("bearish", False):
            score -= min(8, cp_strength)

        score = max(0, min(100, score))

        # 🆕 v6.4.117: تصنيف Score (Technical Setup Score — ليس احتمال نجاح)
        if score >= 75:
            score_class = "إعداد قوي جداً"
        elif score >= 60:
            score_class = "إعداد قوي"
        elif score >= 45:
            score_class = "إعداد متوسط"
        else:
            score_class = "إعداد ضعيف"

        # 🆕 v6.4.117: الحد الأدنى لِـ Score
        # 🆕 v6.4.120: الحد الأدنى = 35 (كان 40) — الفلاتر المرنة تنتج نقاط أقل لكنها صالحة
        if score < 35:
            log.info(f"🚀 [V3] {symbol} — تخطي: Score {score} < 35")
            return None

        # ═══ 6) Entry + SL + TP (Single Source of Truth) ═══
        cur_price = last_15m["close"]
        atr = _calc_atr(candles_15m, 14)
        if atr <= 0:
            log.info(f"🚀 [V3] {symbol} — تخطي: ATR = 0")
            return None

        # 🆕 v6.4.117: Entry zone حسب المرحلة
        if stage == "CONFIRMED BREAKOUT":
            # دخول بعد التأكيد — عند المقاومة المكسورة (التي أصبحت دعم)
            entry_ref = resistance
            entry_low = resistance * 0.995
            entry_high = resistance * 1.01
        else:
            # PRE-PUMP WATCH / MOMENTUM IGNITION — عند المقاومة
            entry_ref = resistance
            entry_low = resistance * 0.99
            entry_high = resistance * 1.005

        # 🆕 v6.4.117: Entry validity — هل السعر داخل منطقة الدخول؟
        if cur_price > entry_high * 1.02:
            # السعر فوق منطقة الدخول بِكثير — فرصة فائتة
            entry_status = "فرصة فائتة — انتظار تصحيح"
        elif cur_price > entry_high:
            entry_status = "انتظار تصحيح لِـ منطقة الدخول"
        elif cur_price < entry_low * 0.98:
            entry_status = "السعر تحت منطقة الدخول — انتظار ارتداد"
        else:
            entry_status = "داخل منطقة الدخول"

        # 🆕 v6.4.117: SL تحت آخر دعم (منطقي)
        if supports:
            sl = supports[0] * 0.99
        else:
            sl = entry_ref - 1.5 * atr
        # 🆕 v6.4.117: تأكيد SL تحت Entry
        if sl >= entry_ref:
            sl = entry_ref - 1.5 * atr

        # 🆕 v6.4.117: TPs — محسوبة من entry_ref (وليس cur_price)
        tp1 = entry_ref * 1.10  # +10%
        tp2 = entry_ref * 1.20  # +20%
        tp3 = entry_ref * 1.30  # +30%
        # لو توجد مقاومات أعلى → استخدمها
        for r in resistances_above:
            r_pct = ((r - entry_ref) / entry_ref) * 100
            if 8 <= r_pct <= 15 and r > tp1:
                tp1 = r
            elif 15 < r_pct <= 25 and r > tp2:
                tp2 = r
            elif r_pct > 25 and r > tp3:
                tp3 = r
        # 🆕 v6.4.122: Volume Profile — استخدم VAH كـ TP1 و VAL كـ SL المُحسّن
        vah = vp_1h.get("vah", 0)
        val = vp_1h.get("val", 0)
        if vah > entry_ref and vah < tp2:
            tp1 = max(tp1, vah)  # TP1 = أعلى مستوى سيولة قبل TP2
        if val > 0 and val < entry_ref:
            # VAL يمكن استخدامه لِـ SL أعمق لو تحت entry_ref
            val_dist = (entry_ref - val) / entry_ref
            if 0.03 <= val_dist <= 0.15:  # VAL بين 3-15% تحت الدخول
                sl = min(sl, val)  # SL أعمق عند مستوى السيولة الحقيقي

        # 🆕 v6.4.117: Mathematical Validation
        # تأكيد TP1 < TP2 < TP3
        if tp2 <= tp1:
            tp2 = tp1 * 1.10
        if tp3 <= tp2:
            tp3 = tp2 * 1.10
        # تأكيد SL < entry_ref < TP1 < TP2 < TP3
        if sl >= entry_ref or tp1 <= entry_ref or tp2 <= tp1 or tp3 <= tp2:
            log.warning(f"🚀 [V3] {symbol} — تخطي: فشل التحقق الرياضي (SL/TP غير منطقي)")
            return None

        # 🆕 v6.4.117: حسابات صحيحة من entry_ref
        sl_pct = ((entry_ref - sl) / entry_ref) * 100  # وقف الخسارة %
        tp1_pct = ((tp1 - entry_ref) / entry_ref) * 100  # ربح TP1 %
        tp2_pct = ((tp2 - entry_ref) / entry_ref) * 100
        tp3_pct = ((tp3 - entry_ref) / entry_ref) * 100
        # R/R لِـ كل هدف
        risk = entry_ref - sl
        if risk <= 0:
            log.warning(f"🚀 [V3] {symbol} — تخطي: Risk ≤ 0")
            return None
        rr_tp1 = (tp1 - entry_ref) / risk
        rr_tp2 = (tp2 - entry_ref) / risk
        rr_tp3 = (tp3 - entry_ref) / risk
        rr = rr_tp3  # R/R الرئيسي (TP3)

        if rr < 1.0:
            log.info(f"🚀 [V3] {symbol} — تخطي: R/R {rr:.1f} < 1.0")
            return None

        # ═══ 7) أدلة الصعود + المخاطر ═══
        bullish_evidence = []
        bearish_evidence = []

        if btc_trend == "bullish":
            bullish_evidence.append("BTC 4h صاعد")
        elif btc_trend == "neutral":
            bearish_evidence.append("BTC 4h محايد (ليس دعم قوي)")
        if ema20_4h > ema50_4h:
            bullish_evidence.append("4h: EMA20 > EMA50 (اتجاه صاعد)")
        if cur_4h > ema20_4h:
            bullish_evidence.append("4h: السعر فوق EMA20")
        if vol_ratio >= 1.5:
            bullish_evidence.append(f"15m: Volume {vol_ratio:.1f}x فوق المتوسط")
        if rsi_15m > 50:
            bullish_evidence.append(f"15m: RSI {rsi_15m:.0f} (زخم إيجابي)")
        if momentum_state == "STRENGTHENING":
            bullish_evidence.append("15m: الزخم يتعزز")
        if dist_to_res < 0.02:
            bullish_evidence.append(f"قرب المقاومة ({dist_to_res*100:.1f}%) — ضغط")
        # 🆕 v6.4.122: VWAP evidence
        if vwap_d > 0 and vwap_d_pos == "above":
            bullish_evidence.append(f"السعر فوق VWAP اليومي ({vwap_d:.4f})")
        elif vwap_d > 0 and vwap_d_pos == "below":
            bearish_evidence.append(f"السعر تحت VWAP اليومي ({vwap_d:.4f})")
        if vwap_w > 0 and vwap_w_pos == "above":
            bullish_evidence.append("السعر فوق VWAP الأسبوعي (اتجاه مؤسسي)")
        elif vwap_w > 0 and vwap_w_pos == "below":
            bearish_evidence.append("السعر تحت VWAP الأسبوعي (اتجاه طويل ضعيف)")
        # 🆕 v6.4.122: Market Structure evidence
        if ms_4h_trend == "uptrend":
            bullish_evidence.append("4h: Market Structure صاعد (HH+HL)")
        elif ms_4h_trend == "downtrend":
            bearish_evidence.append("4h: Market Structure هابط (LH+LL)")
        if ms_4h_bos:
            bullish_evidence.append("4h: BOS (Break of Structure) — تأكيد الاختراق")
        if ms_1h_trend == "uptrend":
            bullish_evidence.append("1h: Market Structure صاعد")
        elif ms_1h_trend == "downtrend":
            bearish_evidence.append("1h: Market Structure هابط")
        # 🆕 v6.4.122: Candle Pattern evidence
        if cp_bullish and cp_pattern != "none":
            bullish_evidence.append(f"1h: {cp_pattern} (نمط صعودي)")
        elif cp_1h.get("bearish", False) and cp_pattern != "none":
            bearish_evidence.append(f"1h: {cp_pattern} (نمط هبوطي)")
        # 🆕 v6.4.122: Volume Profile evidence
        if poc > 0 and vp_position == "above_poc":
            bullish_evidence.append(f"السعر فوق POC ({poc:.4f}) — سيولة محتكرة")
        elif poc > 0 and vp_position == "below_poc":
            bearish_evidence.append(f"السعر تحت POC ({poc:.4f}) — مقاومة سيولة فوق")

        if momentum_state in ("WEAKENING", "REVERSING"):
            bearish_evidence.append(f"الزخم: {momentum_state}")
        if rsi_15m > 75:
            bearish_evidence.append(f"RSI {rsi_15m:.0f} (تشبع شرائي)")
        if vol_ratio < 1.0:
            bearish_evidence.append("Volume ضعيف (تحت المتوسط)")
        if btc_trend == "neutral":
            bearish_evidence.append("BTC محايد — لا دعم سوقي قوي")
        if pump_pct > 5:
            bearish_evidence.append(f"ارتفاع سابق +{pump_pct:.1f}% — احتمال تصحيح")

        # 🆕 v6.4.117: شرط التأكيد + إبطال
        if stage == "CONFIRMED BREAKOUT":
            confirm_condition = "إغلاق 1h فوق المقاومة + Volume ≥ 1.5x"
            invalidation = "إغلاق 1h تحت المقاومة المكسورة"
        elif stage == "MOMENTUM IGNITION":
            confirm_condition = "استمرار Volume ≥ 1.5x + إغلاق فوق المقاومة"
            invalidation = "عودة السعر تحت المقاومة + Volume ضعيف"
        else:  # PRE-PUMP WATCH
            confirm_condition = "اختراق المقاومة + Volume ≥ 1.5x + شمعة صاعدة"
            invalidation = "هبوط تحت آخر دعم"

        # 🆕 v6.4.117: Liquidity assessment
        if vol_ratio >= 2.0:
            liquidity_class = "🟢 سيولة عالية"
        elif vol_ratio >= 1.3:
            liquidity_class = "🟡 سيولة متوسطة"
        else:
            liquidity_class = "⚪ سيولة منخفضة"

        log.info(f"🚀 [V3] {symbol} — ✅ {stage}! Score={score}/100, R/R={rr:.1f}x, Momentum={momentum_state}, Vol={vol_ratio:.1f}x")

        # ═══ 8) Signal object (Single Source of Truth) ═══
        return {
            "symbol": symbol,
            "timestamp": int(time.time()),
            "stage": stage,
            "score": score,
            "score_class": score_class,
            "entry_type": stage,
            "entry_status": entry_status,
            "entry_ref": entry_ref,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "current_price": cur_price,
            "sl": sl,
            "sl_pct": sl_pct,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "tp1_pct": tp1_pct, "tp2_pct": tp2_pct, "tp3_pct": tp3_pct,
            "rr_tp1": rr_tp1, "rr_tp2": rr_tp2, "rr_tp3": rr_tp3, "rr": rr,
            "momentum_state": momentum_state,
            "rsi_15m": rsi_15m,
            "volume_ratio": vol_ratio,
            "liquidity_class": liquidity_class,
            "resistance": resistance,
            "btc_trend": btc_trend,
            "bullish_evidence": bullish_evidence,
            "bearish_evidence": bearish_evidence,
            "confirm_condition": confirm_condition,
            "invalidation": invalidation,
            "pump_pct": pump_pct,
            "trend_4h": "bullish" if cur_4h > ema20_4h else "neutral",
            "ema20_rising": ema20_4h > ema50_4h,
            # 🆕 v6.4.122: VWAP + Volume Profile + Market Structure + Candle Pattern
            "vwap_daily": vwap_daily,
            "vwap_weekly": vwap_weekly,
            "market_structure_4h": ms_4h,
            "market_structure_1h": ms_1h,
            "candle_pattern_1h": cp_1h,
            "volume_profile_1h": vp_1h,
            # legacy fields for compatibility
            "ema40_stabilizing": True,
            "near_ema200": ema200_4h > 0 and abs(cur_4h - ema200_4h) / ema200_4h < 0.05,
            "accumulation": False,
            "higher_lows": False,
            "higher_lows_count": 0,
            "compression": False,
            "atr_ratio": 1.0,
            "resistance_pressure": dist_to_res < 0.05,
            "resistance_touches": 1,
            "distance_to_resistance_pct": dist_to_res * 100,
            "breakout": has_breakout,
            "volume_expansion": vol_ratio >= 1.3,
            "retest": False,
            "entry": cur_price,  # legacy
            "reasons": bullish_evidence + [f"⚠️ {r}" for r in bearish_evidence],
        }
    except Exception as e:
        log.warning(f"V3 detect_pre_pump {symbol} err: {e}")
        return None


def scan_v3_candidates(symbols: List[str]) -> List[Dict]:
    """🆕 v6.4.98: يفحص قائمة عملات ويجمع Pre-Pump signals.
    يرجع: قائمة dicts مرتبة حسب Score (الأعلى أولاً)
    """
    signals = []
    for sym in symbols:
        try:
            sig = detect_pre_pump_signal(sym)
            if sig:
                signals.append(sig)
                log.info(f"🚀 [V3] {sym} — Score={sig['score']}/100, Entry={sig['entry_type']}")
        except Exception as e:
            log.warning(f"V3 scan {sym} err: {e}")
    # رتّب حسب Score (الأعلى أولاً)
    signals.sort(key=lambda x: -x["score"])
    return signals


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.120: V3 Watch Alert — تنبيه صغير بدون أهداف للعملات تحت المراقبة
# ═══════════════════════════════════════════════════════════

def detect_v3_watch_candidate(symbol: str, already_signaled: set = None) -> Optional[Dict]:
    """🆕 v6.4.120: يكتشف عملة تُظهر إشارات إيجابية مبكرة لكنها لم تحقق شروط V3 الكاملة.

    المعايير:
      - 4h: السعر فوق EMA50 (لا هبوط قوي) — أقل صرامة من V3
      - 1h: توجد مقاومة فوق السعر
      - 15m: إشارات إيجابية مبكرة (واحدة على الأقل):
        • شمعة صاعدة مع Volume > 1.0x
        • RSI > 50
        • MACD histogram > 0
        • آخر 3 شمعات صاعدة
        • اختراق مقاومة 15m صغيرة
      - Not already-pumped (< +25% pump)
      - Distance to resistance < 15%

    يرجع: dict مع معلومات المراقبة، أو None لو لا تستحق المراقبة
    """
    try:
        if already_signaled and symbol in already_signaled:
            return None

        # ═══ 1) BTC trend filter (نفس V3) ═══
        btc_trend = _get_btc_trend_v3()
        if btc_trend == "bearish":
            return None

        # ═══ 2) 4H trend (مرن — السعر فوق EMA50 فقط) ═══
        candles_4h = _fetch_klines(symbol, "4h", 100)
        if not candles_4h or len(candles_4h) < 50:
            return None
        closes_4h = [c["close"] for c in candles_4h]
        ema50_4h = _calc_ema(closes_4h, 50)
        ema200_4h = _calc_ema(closes_4h, min(200, len(closes_4h)))
        cur_4h = closes_4h[-1]
        # شرط مرن: السعر فوق EMA50 OR فوق EMA200 (لا هبوط قوي)
        if not (cur_4h > ema50_4h or cur_4h > ema200_4h):
            return None

        # ═══ 3) 1H: مقاومة فوق السعر ═══
        candles_1h = _fetch_klines(symbol, "1h", 100)
        if not candles_1h or len(candles_1h) < 50:
            return None
        closes_1h = [c["close"] for c in candles_1h]
        resistances, _ = _find_swing_levels(candles_1h, lookback=30)
        cur_1h = closes_1h[-1]

        # لو لا توجد مقاومة → استخدم ATR-based
        if not resistances:
            atr_1h = _calc_atr(candles_1h, 14)
            if atr_1h > 0:
                resistances = [cur_1h + 2.5 * atr_1h]
            else:
                return None

        resistances_above = [r for r in resistances if r > cur_1h * 1.001]
        if not resistances_above:
            # السعر اخترق كل المقاومات → استخدم 1.05x
            resistance = cur_1h * 1.05
        else:
            resistance = min(resistances_above, key=lambda r: r - cur_1h)

        dist_to_res = (resistance - cur_1h) / cur_1h
        # Watch: يقبل حتى 15% من المقاومة (V3 يقبل 8% فقط)
        if dist_to_res > 0.15:
            return None

        # ═══ 4) Already-Pumped check (نفس V3 — +25%) ═══
        is_pumped, pump_pct = _detect_already_pumped(candles_1h, lookback=24)
        if is_pumped and pump_pct >= 25:
            return None

        # ═══ 5) 15M: إشارات إيجابية مبكرة ═══
        candles_15m = _fetch_klines(symbol, "15m", 100)
        if not candles_15m or len(candles_15m) < 30:
            return None
        closes_15m = [c["close"] for c in candles_15m]
        vol_ratio = _calc_volume_ratio(candles_15m)
        last_15m = candles_15m[-1]
        last_15m_bullish = last_15m["close"] > last_15m["open"]
        rsi_15m = _calc_rsi(closes_15m)
        _, _, macd_hist, _ = _calc_macd(closes_15m)

        # مقاومات 15m (لاختراقات فريم صغير)
        resistances_15m, _ = _find_swing_levels(candles_15m, lookback=20)
        resistances_15m_above = [r for r in resistances_15m if r > closes_15m[-1] * 1.001] if resistances_15m else []
        # آخر 3 شمعات صاعدة
        last_3_bullish = (
            len(candles_15m) >= 3 and
            candles_15m[-1]["close"] > candles_15m[-1]["open"] and
            candles_15m[-2]["close"] > candles_15m[-2]["open"] and
            candles_15m[-3]["close"] > candles_15m[-3]["open"]
        )
        # اختراق مقاومة 15m في آخر شمعة
        broke_15m_res = False
        if resistances_15m_above:
            nearest_15m_res = min(resistances_15m_above, key=lambda r: r - closes_15m[-1])
            if last_15m["close"] > nearest_15m_res and last_15m_bullish:
                broke_15m_res = True

        # ═══ 6) جمع أدلة إيجابية مبكرة ═══
        early_signals = []
        if cur_4h > ema50_4h:
            early_signals.append("4h: السعر فوق EMA50 (لا هبوط قوي)")
        elif cur_4h > ema200_4h:
            early_signals.append("4h: السعر فوق EMA200 (اتجاه طويل الأمد)")
        if vol_ratio >= 1.5:
            early_signals.append(f"15m: Volume {vol_ratio:.1f}x فوق المتوسط")
        elif vol_ratio >= 1.2:
            early_signals.append(f"15m: Volume {vol_ratio:.1f}x فوق المتوسط")
        if rsi_15m > 55:
            early_signals.append(f"15m: RSI {rsi_15m:.0f} (زخم إيجابي)")
        elif rsi_15m > 50:
            early_signals.append(f"15m: RSI {rsi_15m:.0f} (فوق المحايد)")
        if macd_hist > 0:
            early_signals.append("15m: MACD histogram موجب")
        if last_3_bullish:
            early_signals.append("15m: آخر 3 شمعات صاعدة")
        if last_15m_bullish and vol_ratio >= 1.0:
            early_signals.append("15m: شمعة صاعدة + Volume نشط")
        if broke_15m_res:
            early_signals.append("15m: اختراق مقاومة فريم صغير")
        if dist_to_res < 0.05:
            early_signals.append(f"قرب المقاومة ({dist_to_res*100:.1f}%) — ضغط")
        elif dist_to_res < 0.10:
            early_signals.append(f"مسافة متوسطة للمقاومة ({dist_to_res*100:.1f}%)")
        if btc_trend == "bullish":
            early_signals.append("BTC 4h صاعد")

        # مطلوب على الأقل 3 إشارات إيجابية مبكرة
        if len(early_signals) < 3:
            return None

        # ═══ 7) بناء Watch object ═══
        watch_score = min(100, len(early_signals) * 12)  # كل إشارة = 12 نقطة، max 100
        return {
            "symbol": symbol,
            "timestamp": int(time.time()),
            "watch_score": watch_score,
            "early_signals_count": len(early_signals),
            "early_signals": early_signals,
            "current_price": last_15m["close"],
            "resistance": resistance,
            "distance_to_resistance_pct": dist_to_res * 100,
            "btc_trend": btc_trend,
            "volume_ratio": vol_ratio,
            "rsi_15m": rsi_15m,
            "pump_pct": pump_pct,
            "type": "watch",
        }
    except Exception as e:
        log.warning(f"👀 [V3-WATCH] detect {symbol} err: {e}")
        return None


def scan_v3_watch_candidates(symbols: List[str], already_signaled: set = None) -> List[Dict]:
    """🆕 v6.4.120: يفحص قائمة عملات ويجمع V3 Watch candidates.
    يرجع: قائمة dicts مرتبة حسب watch_score (الأعلى أولاً)
    """
    watches = []
    already = already_signaled or set()
    for sym in symbols:
        try:
            watch = detect_v3_watch_candidate(sym, already)
            if watch:
                watches.append(watch)
                log.info(f"👀 [V3-WATCH] {sym} — Score={watch['watch_score']}/100, Signals={watch['early_signals_count']}")
        except Exception as e:
            log.warning(f"V3-WATCH scan {sym} err: {e}")
    watches.sort(key=lambda x: -x["watch_score"])
    return watches


def format_v3_watch_alert(watch: Dict, target: str = "bot") -> str:
    """🆕 v6.4.120: تنسيق تنبيه V3 Watch — مختصر جداً.
    🆕 v6.4.120-fix: مختصر — السعر + عدد الشروط + رسالة تحليلك الخاص فقط.
    لا ينشئ صفقة. مجرد إشعار للمراقبة.
    """
    try:
        sym = watch["symbol"]
        dot = "🟢" if target == "channel" else "🔴"
        signals_count = watch.get("early_signals_count", 0)
        cur_price = watch.get("current_price", 0)

        def _fmt_price(p):
            if p >= 1000: return f"${p:,.2f}"
            if p >= 1: return f"${p:,.4f}"
            if p >= 0.01: return f"${p:,.6f}"
            return f"${p:,.8f}"

        msg = f"👀 {dot} <b>V3 WATCH — {sym}</b>\n"
        msg += f"💰 السعر: {_fmt_price(cur_price)} · ⚡ {signals_count} شروط إيجابية\n"
        msg += "📌 عملة تحت المراقبة — يرجى عمل تحليلك الخاص"
        return msg
    except Exception as e:
        log.error(f"V3-WATCH format err: {e}")
        return f"👀 {watch.get('symbol', '?')} — خطأ في التنسيق"


# ═══════════════════════════════════════════════════════════
# Message Format
# ═══════════════════════════════════════════════════════════

def format_v3_signal(sig: Dict, halal_ruling: str = "halal", target: str = "bot") -> str:
    """🆕 v6.4.117: تنسيق V3 الجديد — من signal object واحد (Single Source of Truth)."""
    try:
        sym = sig["symbol"]
        dot = "🟢" if target == "channel" else "🔴"
        stage = sig.get("stage", "PRE-PUMP WATCH")
        score = sig["score"]
        score_class = sig.get("score_class", "—")
        entry_status = sig.get("entry_status", "داخل منطقة الدخول")
        cur_price = sig.get("current_price", sig.get("entry", 0))
        entry_low = sig["entry_low"]
        entry_high = sig["entry_high"]
        sl = sig["sl"]
        sl_pct = sig["sl_pct"]
        tp1, tp2, tp3 = sig["tp1"], sig["tp2"], sig["tp3"]
        tp1_pct, tp2_pct, tp3_pct = sig["tp1_pct"], sig["tp2_pct"], sig["tp3_pct"]
        rr = sig["rr"]
        rr_tp1 = sig.get("rr_tp1", 0)
        rr_tp2 = sig.get("rr_tp2", 0)
        rr_tp3 = sig.get("rr_tp3", 0)
        momentum = sig.get("momentum_state", "INSUFFICIENT DATA")
        liquidity = sig.get("liquidity_class", "غير متاح")
        resistance = sig.get("resistance", 0)
        btc_trend = sig.get("btc_trend", "unknown")
        bullish_ev = sig.get("bullish_evidence", [])
        bearish_ev = sig.get("bearish_evidence", [])
        confirm_cond = sig.get("confirm_condition", "—")
        invalid_cond = sig.get("invalidation", "—")

        # 🆕 v6.4.117: Publication validation
        # تحقق من تطابق الأرقام
        def _fmt_price(p):
            if p >= 1000: return f"${p:,.2f}"
            if p >= 1: return f"${p:,.4f}"
            if p >= 0.01: return f"${p:,.6f}"
            return f"${p:,.8f}"

        # تحقق SL < entry_ref < TP1 < TP2 < TP3
        entry_ref = sig.get("entry_ref", entry_high)
        if sl >= entry_ref or tp1 <= entry_ref or tp2 <= tp1 or tp3 <= tp2:
            log.warning(f"🚀 [V3] {sym} — فشل التحقق قبل النشر (SL/TP غير منطقي)")
            return f"🚀 {sym} — خطأ في التحقق الرياضي"

        msg = f"🚀 {dot} <b>{stage} — {sym}</b> 🚀V3\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 تقييم الإعداد: <b>{score}/100</b> — {score_class}\n"
        msg += f"📍 حالة السعر: {entry_status}\n\n"
        msg += f"💰 السعر الحالي: {_fmt_price(cur_price)}\n"
        msg += f"🎯 منطقة الدخول: {_fmt_price(entry_low)} - {_fmt_price(entry_high)}\n"
        msg += f"🛑 وقف الخسارة: {_fmt_price(sl)} ({sl_pct:+.1f}%)\n\n"
        msg += "🎯 الأهداف:\n"
        msg += f"TP1: {_fmt_price(tp1)} (+{tp1_pct:.1f}%)\n"
        msg += f"TP2: {_fmt_price(tp2)} (+{tp2_pct:.1f}%)\n"
        msg += f"TP3: {_fmt_price(tp3)} (+{tp3_pct:.1f}%)\n\n"
        msg += "⚖️ العائد إلى المخاطرة:\n"
        msg += f"TP1: {rr_tp1:.1f}x · TP2: {rr_tp2:.1f}x · TP3: {rr_tp3:.1f}x\n\n"
        msg += f"📈 الزخم: {momentum}\n"
        msg += f"💧 السيولة: {liquidity}\n"
        msg += f"🧱 المقاومة الأقرب: {_fmt_price(resistance)}\n"
        msg += f"₿ حالة BTC: {btc_trend}\n\n"

        if bullish_ev:
            msg += "✅ أدلة الصعود:\n"
            for e in bullish_ev[:5]:
                msg += f"  • {e}\n"

        if bearish_ev:
            msg += "\n⚠️ المخاطر والتناقضات:\n"
            for e in bearish_ev[:4]:
                msg += f"  • {e}\n"

        msg += f"\n📌 شرط التأكيد: {confirm_cond}\n"
        msg += f"❌ شرط الإبطال: {invalid_cond}\n"

        if halal_ruling == "halal":
            msg += "\n━━━━━━━━━━━━━━━━━━\n"
            msg += "🕌 <b>الحكم الشرعي: 🟢 حلال</b>\n"
        msg += "⚠️ <i>إشارة احتمالية وليست ضمانًا للصعود. لا تدخل إذا انتهت صلاحية منطقة الدخول.</i>"
        return msg
    except Exception as e:
        log.error(f"V3 format signal err: {e}")
        return f"🚀 {sig.get('symbol', '?')} — خطأ في التنسيق"


def _v3_smart_liquidity_pct(sig: Dict) -> float:
    """🆕 v6.4.98: نسبة السيولة الذكية لِـ V3 — تحسب من Pre-Pump quality.
    - Accumulation → +20
    - Higher Lows → +20
    - Compression → +15
    - Resistance Pressure → +15
    - Volume Expansion → +15
    - Breakout → +15
    - Retest → +10
    """
    try:
        score = 0
        if sig.get("accumulation"):
            score += 20
        if sig.get("higher_lows"):
            score += 20
        if sig.get("compression"):
            score += 15
        if sig.get("resistance_pressure"):
            score += 15
        if sig.get("volume_expansion"):
            score += 15
        if sig.get("breakout"):
            score += 15
        if sig.get("retest"):
            score += 10
        return min(100.0, float(score))
    except Exception:
        return 0.0
