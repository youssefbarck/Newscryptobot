"""
Engine — جلب البيانات + المؤشرات الفنية + SMC + Volume + Liquidity
=================================================================
🆕 v6.3: معمارية Funnel:
  1) prefilter رخيص (ticker مجمّع واحد) بدل تحليل عميق لكل العملات
  2) جلب متوازٍ (ThreadPoolExecutor) بدل التسلسل مع sleep 1.5s
  3) تحليل متعدد الفريمات MTF (15m + 1h + 4h + 1d) مع توافق حقيقي
كل التحليل الفني في ملف واحد نظيف.
"""

import logging, time, math, requests
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("Engine")

# ═══ Binance API ═══
# 🆕 v6.4.38: استخدام data-api.binance.vision ك fallback عند حظر api.binance.com
# - api.binance.com: الـ API الرسمي، يحظر أحياناً IPs خدمات الـ cloud (Render/Haroku/Railway)
# - data-api.binance.vision: موقع Binance العمومي للبيانات (لا يحظر IPs الخدمات)
#   ويستخدم نفس بنية REST — مثالي كـ fallback.
_BINANCE_PRIMARY = "https://api.binance.com"
_BINANCE_FALLBACK = "https://data-api.binance.vision"
_KLINES_URL = f"{_BINANCE_PRIMARY}/api/v3/klines"
_KLINES_URL_FALLBACK = f"{_BINANCE_FALLBACK}/api/v3/klines"
_TICKER_URL = f"{_BINANCE_PRIMARY}/api/v3/ticker/24hr"
_TICKER_URL_FALLBACK = f"{_BINANCE_FALLBACK}/api/v3/ticker/24hr"
_EXCHANGE_INFO_URL = f"{_BINANCE_PRIMARY}/api/v3/exchangeInfo"
_EXCHANGE_INFO_URL_FALLBACK = f"{_BINANCE_FALLBACK}/api/v3/exchangeInfo"
_banned_until = 0.0
_use_fallback = False  # 🆕 v6.4.38: تبديل ديناميكي إلى fallback عند الفشل


def _binance_get(url_primary: str, url_fallback: str, params: dict = None, timeout: int = 20):
    """🆕 v6.4.38: GET من Binance مع fallback تلقائي إلى data-api.binance.vision.
    🆕 v6.4.41: إضافة User-Agent header — يخفف HTTP 418 من bot detection.
    🆕 v6.4.124: silent mode — لا يكتب warning لكل طلب، فقط log واحد عند بدء الحظر.
    يرجع (response, used_url) أو (None, None) عند الفشل التام.
    """
    global _use_fallback, _banned_until
    # 🆕 v6.4.124: لو Binance محظور، ما نحاول أصلاً (نرجع None بصمت)
    if time.time() < _banned_until:
        return None, None
    urls_to_try = [url_fallback, url_primary] if _use_fallback else [url_primary, url_fallback]
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_err = None
    block_status = None
    for url in urls_to_try:
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=headers)
            if r.status_code == 200:
                if url == url_fallback:
                    _use_fallback = True
                return r, url
            if r.status_code in (403, 418, 429, 451):
                last_err = f"HTTP {r.status_code} from {url}"
                block_status = r.status_code
                continue
            return r, url
        except Exception as e:
            last_err = str(e)
            continue
    # 🆕 v6.4.124: لو حصلنا 418/403 → حظر Binance 30 دقيقة (كان 10) + log واحد فقط
    if block_status in (403, 418, 429, 451):
        _banned_until = time.time() + 1800  # 30 دقيقة
        log.warning(f"⛔ Binance IP-block (HTTP {block_status}) — pausing Binance 30min, using KuCoin/Coinbase silently")
    else:
        # 🆕 v6.4.124: silent — ما نكتب log لكل طلب، فقط لو كل المصادر فشلت
        pass
    return None, None


# 🆕 v6.4.41: CoinGecko as third data source when Binance is blocked
_COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
_COINGECKO_CACHE: Dict = {"data": None, "ts": 0.0}
_COINGECKO_TTL = 300  # 5 min cache

def get_market_tickers_coingecko() -> List[Dict]:
    """🆕 v6.4.41: Alternative to Binance ticker — uses CoinGecko free API.
    CoinGecko never blocks IPs and doesn't require authentication.
    Returns data in Binance ticker format for compatibility.
    """
    now = time.time()
    if _COINGECKO_CACHE["data"] and now - _COINGECKO_CACHE["ts"] < _COINGECKO_TTL:
        return _COINGECKO_CACHE["data"]
    try:
        # Get top 200 coins by market cap
        r = requests.get(_COINGECKO_URL, params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 200,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h"
        }, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }, timeout=20)
        if r.status_code != 200:
            log.warning(f"CoinGecko HTTP {r.status_code}")
            return _COINGECKO_CACHE["data"] or []
        # Convert CoinGecko format to Binance ticker format
        result = []
        for coin in r.json():
            sym = (coin.get("symbol") or "").upper()
            if not sym:
                continue
            price = coin.get("current_price") or 0
            change = coin.get("price_change_percentage_24h") or 0
            vol = coin.get("total_volume") or 0
            result.append({
                "symbol": f"{sym}USDT",
                "lastPrice": str(price),
                "priceChangePercent": str(change),
                "quoteVolume": str(vol),
                "_source": "coingecko"
            })
        if result:
            _COINGECKO_CACHE["data"] = result
            _COINGECKO_CACHE["ts"] = now
            log.info(f"🦎 [COINGECKO] {len(result)} ticker fetched successfully")
        return result
    except Exception as e:
        log.error(f"❌ [COINGECKO] error: {e}")
        return _COINGECKO_CACHE["data"] or []
# 🆕 v6.3: cache TTL حسب الفريم (شمعة 15m تتغير بسرعة، 1d بطيئة)
_CACHE: Dict[str, Tuple[float, List]] = {}
_CACHE_TTL_BY_TF = {"15m": 180, "1h": 600, "4h": 1200, "1d": 1800}
_DEFAULT_TTL = 300

def _cache_ttl(interval: str) -> int:
    return _CACHE_TTL_BY_TF.get(interval, _DEFAULT_TTL)

def fetch_klines(symbol: str, interval: str = "1d", limit: int = 90) -> List[Dict]:
    global _banned_until
    # 🆕 v6.4.124: silent mode — لو Binance محظور، نروح مباشرة لِـ KuCoin/Coinbase بدون log
    if time.time() < _banned_until:
        kc_candles = fetch_klines_kucoin(symbol, interval, limit)
        if kc_candles:
            return kc_candles
        cb_candles = fetch_klines_coinbase(symbol, interval, limit)
        if cb_candles:
            return cb_candles
        return _CACHE.get(f"{symbol}_{interval}", (0, []))[1]
    key = f"{symbol}_{interval}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _cache_ttl(interval):
        return _CACHE[key][1]
    try:
        r, used_url = _binance_get(_KLINES_URL, _KLINES_URL_FALLBACK,
                                   params={"symbol": f"{symbol.upper()}USDT", "interval": interval, "limit": limit},
                                   timeout=15)
        if r is None or r.status_code in (403, 418, 429, 451):
            # 🆕 v6.4.124: silent — ما نكتب warning لكل طلب (log واحد فقط من _binance_get)
            # جرّب KuCoin
            kc_candles = fetch_klines_kucoin(symbol, interval, limit)
            if kc_candles:
                _CACHE[key] = (now, kc_candles)
                return kc_candles
            # جرّب Coinbase
            cb_candles = fetch_klines_coinbase(symbol, interval, limit)
            if cb_candles:
                _CACHE[key] = (now, cb_candles)
                return cb_candles
            # 🆕 v6.4.124: فقط هنا نكتب log (كل المصادر فشلت)
            log.error(f"❌ [ALL FAIL] fetch_klines {symbol} {interval} — Binance + KuCoin + Coinbase all failed")
            return _CACHE.get(key, (0, []))[1]
        if r.status_code != 200:
            kc_candles = fetch_klines_kucoin(symbol, interval, limit)
            if kc_candles:
                _CACHE[key] = (now, kc_candles)
                return kc_candles
            cb_candles = fetch_klines_coinbase(symbol, interval, limit)
            if cb_candles:
                _CACHE[key] = (now, cb_candles)
                return cb_candles
            return _CACHE.get(key, (0, []))[1]
        candles = [{"open_time": int(k[0]),"open": float(k[1]),"high": float(k[2]),"low": float(k[3]),"close": float(k[4]),"volume": float(k[5]),"close_time": int(k[6])} for k in r.json()]
        _CACHE[key] = (now, candles)
        return candles
    except Exception as e:
        log.warning(f"fetch_klines {symbol}: {e}")
        kc_candles = fetch_klines_kucoin(symbol, interval, limit)
        if kc_candles:
            _CACHE[key] = (now, kc_candles)
            return kc_candles
        cb_candles = fetch_klines_coinbase(symbol, interval, limit)
        if cb_candles:
            _CACHE[key] = (now, cb_candles)
            return cb_candles
        return _CACHE.get(key, (0, []))[1]


# 🆕 v6.4.41: KuCoin as alternative source for klines (never blocks IPs)
_KUCOIN_KLINES_URL = "https://api.kucoin.com/api/v1/market/candles"
_KUCOIN_INTERVAL_MAP = {"15m": "15min", "1h": "1hour", "4h": "4hour", "1d": "1day"}

def fetch_klines_kucoin(symbol: str, interval: str = "1d", limit: int = 90) -> List[Dict]:
    """🆕 v6.4.41: KuCoin fallback for klines when Binance is blocked.
    KuCoin doesn't block Render/cloud IPs and has the same data quality.
    Returns candles in the same format as fetch_klines.
    """
    try:
        kc_interval = _KUCOIN_INTERVAL_MAP.get(interval, "1day")
        # 🆕 v6.4.123: Handle legacy symbol mapping (MATIC → POL on KuCoin)
        kc_symbol_raw = symbol.upper()
        kc_symbol_mapped = _LEGACY_SYMBOL_MAP.get(kc_symbol_raw, kc_symbol_raw)
        # KuCoin symbol format: BTC-USDT (with dash)
        kc_symbol = f"{kc_symbol_mapped}-USDT"
        r = requests.get(_KUCOIN_KLINES_URL, params={
            "symbol": kc_symbol,
            "type": kc_interval,
            "limit": min(limit, 1500)  # KuCoin max is 1500
        }, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json"
        }, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("code") != "200000" or not data.get("data"):
            return []
        # KuCoin returns candles in reverse order (newest first)
        # Format: [time, open, close, high, low, volume, turnover]
        candles = []
        for k in reversed(data["data"]):
            try:
                # KuCoin time is in milliseconds (string)
                t_ms = int(k[0])
                candles.append({
                    "open_time": t_ms // 1000,
                    "open": float(k[1]),
                    "high": float(k[3]),
                    "low": float(k[4]),
                    "close": float(k[2]),  # KuCoin: open=1, close=2, high=3, low=4
                    "volume": float(k[5]),
                    "close_time": (t_ms // 1000) + 60  # approximate
                })
            except (ValueError, TypeError, IndexError):
                continue
        if candles:
            mapped_note = f" (mapped to {kc_symbol_mapped})" if kc_symbol_mapped != kc_symbol_raw else ""
            log.info(f"🦎 [KUCOIN] {symbol}{mapped_note} {interval} → {len(candles)} candles")
        return candles
    except Exception as e:
        log.warning(f"KuCoin fetch_klines {symbol}: {e}")
        return []


# 🆕 v6.4.123: Mapping for legacy symbols (تم تغيير اسم MATIC إلى POL بعد Polygon 2.0)
_LEGACY_SYMBOL_MAP = {
    "MATIC": "POL",  # Polygon migrated from MATIC to POL on Sep 2024
}

# 🆕 v6.4.123: Coinbase as third fallback source (never blocks IPs, free)
_COINBASE_KLINES_URL = "https://api.exchange.coinbase.com/products/{symbol}/candles"
_COINBASE_GRANULARITY_MAP = {
    "5m": "300",     # 5 min
    "15m": "900",    # 15 min
    "1h": "3600",    # 1 hour
    "4h": "21600",   # 6 hours (closest to 4h)
    "1d": "86400",   # 1 day
}


def fetch_klines_coinbase(symbol: str, interval: str = "1d", limit: int = 90) -> List[Dict]:
    """🆕 v6.4.123: Coinbase fallback for klines (third source).
    Coinbase Pro/Advanced Trade API — never blocks IPs, free.
    Returns candles in the same format as fetch_klines.
    """
    try:
        # Handle legacy symbol mapping (MATIC → POL)
        cb_symbol_raw = symbol.upper()
        cb_symbol = _LEGACY_SYMBOL_MAP.get(cb_symbol_raw, cb_symbol_raw)
        cb_symbol = f"{cb_symbol}-USD"
        granularity = _COINBASE_GRANULARITY_MAP.get(interval, "86400")
        url = _COINBASE_KLINES_URL.format(symbol=cb_symbol)
        r = requests.get(url, params={
            "granularity": granularity,
            "limit": min(limit, 300)  # Coinbase max is 300
        }, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "application/json"
        }, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if not data:
            return []
        # Coinbase returns: [timestamp, low, high, open, close, volume] (newest first)
        candles = []
        for k in reversed(data):  # reverse to oldest-first (Binance convention)
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
            log.info(f"🪙 [COINBASE] {symbol} {interval} → {len(candles)} candles")
        return candles
    except Exception as e:
        log.warning(f"Coinbase fetch_klines {symbol}: {e}")
        return []


def is_binance_available() -> bool:
    return time.time() >= _banned_until

def fetch_top_movers(limit: int = 15, min_vol: float = 5e6, gainers: bool = True) -> List[str]:
    global _banned_until
    if not is_binance_available():
        return []
    try:
        r, used_url = _binance_get(_TICKER_URL, _TICKER_URL_FALLBACK, timeout=20)
        if r is None:
            log.error("❌ [BINANCE ALL FAIL] fetch_top_movers")
            return []
        if r.status_code != 200:
            log.error(f"❌ [BINANCE BLOCK?] fetch_top_movers HTTP {r.status_code}")
            if r.status_code in (403, 418, 429, 451):
                _banned_until = time.time() + 600
            return []
        stable = {"USDC","BUSD","DAI","TUSD","USDP","FDUSD","USDT","EUR","GBP","TRY","BIDR","AEUR","USDS","SUSD","PAXG","USTC","SOXLB","SOXL","SOXS","UP","DOWN","BULL","BEAR"}
        coins = []
        for c in r.json():
            sym = c.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym.replace("USDT", "")
            if base in stable:
                continue
            try:
                price = float(c["lastPrice"])
                change = float(c["priceChangePercent"])
                vol = float(c["quoteVolume"])
                if price > 0 and vol >= min_vol:
                    if gainers and change >= 5.0:
                        coins.append((base, change))
                    elif not gainers and change <= -5.0:
                        coins.append((base, change))
            except (ValueError, TypeError):
                continue
        coins.sort(key=lambda x: x[1], reverse=gainers)
        return [c[0] for c in coins[:limit]]
    except Exception as e:
        log.warning(f"fetch_top_movers: {e}")
        return []


def fetch_top_movers_with_data(limit: int = 15, min_vol: float = 5e6, gainers: bool = True) -> List[Tuple[str, float, float]]:
    """🆕 v6.4.49: مثل fetch_top_movers لكن يرجع (symbol, change_pct, price).
    مفيدة لعرض نسبة الصعود + السعر في واجهة المستخدم.
    """
    global _banned_until
    if not is_binance_available():
        return []
    try:
        r, used_url = _binance_get(_TICKER_URL, _TICKER_URL_FALLBACK, timeout=20)
        if r is None or r.status_code != 200:
            return []
        stable = {"USDC","BUSD","DAI","TUSD","USDP","FDUSD","USDT","EUR","GBP","TRY","BIDR","AEUR","USDS","SUSD","PAXG","USTC","SOXLB","SOXL","SOXS","UP","DOWN","BULL","BEAR"}
        coins = []
        for c in r.json():
            sym = c.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym.replace("USDT", "")
            if base in stable:
                continue
            try:
                price = float(c["lastPrice"])
                change = float(c["priceChangePercent"])
                vol = float(c["quoteVolume"])
                if price > 0 and vol >= min_vol:
                    if gainers and change >= 5.0:
                        coins.append((base, change, price))
                    elif not gainers and change <= -5.0:
                        coins.append((base, change, price))
            except (ValueError, TypeError):
                continue
        coins.sort(key=lambda x: x[1], reverse=gainers)
        return coins[:limit]
    except Exception as e:
        log.warning(f"fetch_top_movers_with_data: {e}")
        return []


# 🆕 v6.2: جلب كل عملات Binance Spot (USDT pairs)
_spot_symbols_cache: List[str] = []
_spot_symbols_ts: float = 0.0
_SPOT_CACHE_TTL = 3600  # 1 hour

def fetch_all_spot_symbols(min_quote_volume: float = 1e6, min_price: float = 0.0001) -> List[str]:
    """🆕 v6.2: يجلب كل رموز USDT Spot على Binance مع فلترة:
       - يستثني الـ stablecoins
       - يستثني العملات ذات السيولة المنخفضة (<1M USDT حجم 24h)
       - يستثني العملات ذات السعر شبه الصفري
       - يحتفظ بـ cache لمدة ساعة (لا يستدعى كل دورة)
    🆕 v6.4.38: fallback تلقائي إلى data-api.binance.vision عند الحظر
    """
    global _spot_symbols_cache, _spot_symbols_ts, _banned_until
    now = time.time()
    if _spot_symbols_cache and now - _spot_symbols_ts < _SPOT_CACHE_TTL:
        return _spot_symbols_cache
    if not is_binance_available():
        return _spot_symbols_cache or []
    try:
        # 1) exchangeInfo: قائمة كل الرموز المتاحة للتداول Spot
        r, used_url = _binance_get(_EXCHANGE_INFO_URL, _EXCHANGE_INFO_URL_FALLBACK,
                                    params={"permissions": "SPOT"}, timeout=30)
        if r is None:
            log.error("❌ [BINANCE ALL FAIL] exchangeInfo")
            return _spot_symbols_cache or []
        if r.status_code != 200:
            log.error(f"❌ [BINANCE BLOCK?] exchangeInfo HTTP {r.status_code}")
            if r.status_code in (403, 418, 429, 451):
                _banned_until = time.time() + 600
            return _spot_symbols_cache or []
        symbols_info = r.json().get("symbols", [])
        stable = {"USDC","BUSD","DAI","TUSD","USDP","FDUSD","USDT","EUR","GBP","TRY",
                  "BIDR","AEUR","USDS","SUSD","PAXG","USTC","SOXLB","SOXL","SOXS",
                  "UP","DOWN","BULL","BEAR","USDSB","USTCB"}
        spot_candidates = []
        for s in symbols_info:
            sym = s.get("symbol", "")
            status = s.get("status", "")
            quote = s.get("quoteAsset", "")
            base = s.get("baseAsset", "")
            # فلترة: USDT pairs only + TRADING status + not stablecoin
            if quote != "USDT":
                continue
            if status != "TRADING":
                continue
            if base in stable:
                continue
            spot_candidates.append(base)
        if not spot_candidates:
            log.warning("No spot symbols found in exchangeInfo")
            return _spot_symbols_cache or []
        # 2) 24hr ticker: فلترة بالسيولة والسعر
        r2, used_url2 = _binance_get(_TICKER_URL, _TICKER_URL_FALLBACK, timeout=30)
        if r2 is None or r2.status_code != 200:
            status2 = r2.status_code if r2 is not None else "N/A"
            log.error(f"❌ [BINANCE BLOCK?] 24hr ticker HTTP {status2}")
            # استخدم القائمة بدون فلترة سيولة
            _spot_symbols_cache = spot_candidates
            _spot_symbols_ts = now
            return _spot_symbols_cache
        liquid_symbols = []
        for c in r2.json():
            sym = c.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym.replace("USDT", "")
            if base not in spot_candidates:
                continue
            try:
                price = float(c["lastPrice"])
                vol = float(c["quoteVolume"])
                if price >= min_price and vol >= min_quote_volume:
                    liquid_symbols.append(base)
            except (ValueError, TypeError):
                continue
        _spot_symbols_cache = sorted(liquid_symbols)
        _spot_symbols_ts = now
        log.info(f"🌍 [SPOT UNIVERSE] {len(_spot_symbols_cache)} liquid USDT pairs loaded")
        return _spot_symbols_cache
    except Exception as e:
        log.warning(f"fetch_all_spot_symbols: {e}")
        return _spot_symbols_cache or []

# ═══ Indicators ═══
def compute_ema(values: List[float], period: int) -> List[float]:
    if not values or len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for i in range(period, len(values)):
        ema.append(values[i] * k + ema[-1] * (1 - k))
    return ema

def compute_macd(candles: List[Dict], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    if len(candles) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0, "trend": "flat", "bullish_cross": False, "bearish_cross": False}
    closes = [c["close"] for c in candles]
    ema_f = compute_ema(closes, fast)
    ema_s = compute_ema(closes, slow)
    macd_line = [ema_f[i] - ema_s[i] for i in range(len(ema_s))]
    sig_line = compute_ema(macd_line, signal)
    cur_macd, cur_sig = macd_line[-1], sig_line[-1]
    hist = cur_macd - cur_sig
    if len(macd_line) >= 3 and len(sig_line) >= 3:
        h1 = macd_line[-2] - sig_line[-2]
        h2 = macd_line[-3] - sig_line[-3]
        if hist > h1 > h2:
            trend = "increasing"
        elif hist < h1 < h2:
            trend = "decreasing"
        else:
            trend = "flat"
    else:
        trend = "flat"
    bull_cross = any(macd_line[i] <= sig_line[i] and macd_line[i+1] > sig_line[i+1] for i in range(-5, -1)) if len(macd_line) >= 6 else False
    bear_cross = any(macd_line[i] >= sig_line[i] and macd_line[i+1] < sig_line[i+1] for i in range(-5, -1)) if len(macd_line) >= 6 else False
    return {"macd": round(cur_macd, 6), "signal": round(cur_sig, 6), "histogram": round(hist, 6), "trend": trend, "bullish_cross": bull_cross, "bearish_cross": bear_cross}

def compute_rsi(candles: List[Dict], period: int = 14) -> Dict:
    if len(candles) < period + 1:
        return {"rsi": 50, "state": "neutral", "divergence": "none"}
    gains, losses = [], []
    for i in range(1, len(candles)):
        ch = candles[i]["close"] - candles[i-1]["close"]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    rsi = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    state = "oversold" if rsi < 30 else ("overbought" if rsi > 70 else "neutral")
    div = "none"
    if len(candles) >= 20:
        lows = [c["low"] for c in candles[-10:]]
        highs = [c["high"] for c in candles[-10:]]
        if lows[-1] < lows[-5] and rsi > 40:
            div = "bullish"
        elif highs[-1] > highs[-5] and rsi < 60:
            div = "bearish"
    return {"rsi": round(rsi, 2), "state": state, "divergence": div}

def compute_atr(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0
    trs = []
    for i in range(-period, 0):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0

# ═══ SMC ═══
def detect_bos_choch(candles: List[Dict], lookback: int = 5) -> List[Dict]:
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        wh = [candles[j]["high"] for j in range(i - lookback, i + lookback + 1)]
        wl = [candles[j]["low"] for j in range(i - lookback, i + lookback + 1)]
        if candles[i]["high"] == max(wh) and wh.count(candles[i]["high"]) == 1:
            highs.append({"index": i, "price": candles[i]["high"]})
        if candles[i]["low"] == min(wl) and wl.count(candles[i]["low"]) == 1:
            lows.append({"index": i, "price": candles[i]["low"]})
    structure = []
    trend = "neutral"
    for i in range(1, len(candles)):
        rh = [s for s in highs if s["index"] < i][-3:]
        rl = [s for s in lows if s["index"] < i][-3:]
        if not rh or not rl:
            continue
        lh, ll = rh[-1]["price"], rl[-1]["price"]
        if candles[i]["close"] > lh and candles[i-1]["close"] <= lh:
            if trend == "bearish":
                structure.append({"index": i, "price": candles[i]["close"], "type": "CHOCH", "direction": "bullish", "level": lh})
            else:
                structure.append({"index": i, "price": candles[i]["close"], "type": "BOS", "direction": "bullish", "level": lh})
            trend = "bullish"
        elif candles[i]["close"] < ll and candles[i-1]["close"] >= ll:
            if trend == "bullish":
                structure.append({"index": i, "price": candles[i]["close"], "type": "CHOCH", "direction": "bearish", "level": ll})
            else:
                structure.append({"index": i, "price": candles[i]["close"], "type": "BOS", "direction": "bearish", "level": ll})
            trend = "bearish"
    return structure

def detect_order_blocks(candles: List[Dict], lookback: int = 10) -> List[Dict]:
    obs = []
    for i in range(lookback, len(candles) - 1):
        cur, nxt = candles[i], candles[i+1]
        if cur["close"] < cur["open"] and nxt["close"] > nxt["open"]:
            move = (nxt["close"] - nxt["open"]) / cur["low"] * 100
            if move > 2.0:
                mit = any(candles[j]["low"] <= cur["high"] for j in range(i+2, min(i+20, len(candles))))
                obs.append({"index": i, "type": "bullish", "high": cur["high"], "low": cur["low"], "mitigated": mit})
        elif cur["close"] > cur["open"] and nxt["close"] < nxt["open"]:
            move = (nxt["open"] - nxt["close"]) / cur["high"] * 100
            if move > 2.0:
                mit = any(candles[j]["high"] >= cur["low"] for j in range(i+2, min(i+20, len(candles))))
                obs.append({"index": i, "type": "bearish", "high": cur["high"], "low": cur["low"], "mitigated": mit})
    return obs[-6:]

def detect_fvgs(candles: List[Dict], min_gap: float = 0.005) -> List[Dict]:
    fvgs = []
    for i in range(2, len(candles)):
        c1, c3 = candles[i-2], candles[i]
        if c3["low"] > c1["high"]:
            gap = (c3["low"] - c1["high"]) / candles[i-1]["close"] * 100
            if gap >= min_gap * 100:
                filled = any(candles[j]["low"] <= c1["high"] for j in range(i+1, len(candles)))
                fvgs.append({"index": i, "type": "bullish", "bottom": c1["high"], "top": c3["low"], "filled": filled})
        elif c3["high"] < c1["low"]:
            gap = (c1["low"] - c3["high"]) / candles[i-1]["close"] * 100
            if gap >= min_gap * 100:
                filled = any(candles[j]["high"] >= c1["low"] for j in range(i+1, len(candles)))
                fvgs.append({"index": i, "type": "bearish", "bottom": c3["high"], "top": c1["low"], "filled": filled})
    return fvgs[-8:]

def detect_liquidity_pools(candles: List[Dict]) -> List[Dict]:
    highs, lows = [], []
    for i in range(5, len(candles) - 5):
        wh = [candles[j]["high"] for j in range(i-5, i+6)]
        wl = [candles[j]["low"] for j in range(i-5, i+6)]
        if candles[i]["high"] == max(wh):
            highs.append({"index": i, "price": candles[i]["high"]})
        if candles[i]["low"] == min(wl):
            lows.append({"index": i, "price": candles[i]["low"]})
    pools = []
    for i in range(len(highs)):
        for j in range(i+1, len(highs)):
            tol = max(highs[i]["price"], highs[j]["price"]) * 0.01
            if abs(highs[i]["price"] - highs[j]["price"]) <= tol:
                swept = any(candles[k]["high"] > max(highs[i]["price"], highs[j]["price"]) * 1.005 for k in range(j+1, len(candles)))
                pools.append({"price": max(highs[i]["price"], highs[j]["price"]), "side": "buy", "swept": swept})
                break
    for i in range(len(lows)):
        for j in range(i+1, len(lows)):
            tol = max(lows[i]["price"], lows[j]["price"]) * 0.01
            if abs(lows[i]["price"] - lows[j]["price"]) <= tol:
                swept = any(candles[k]["low"] < min(lows[i]["price"], lows[j]["price"]) * 0.995 for k in range(j+1, len(candles)))
                pools.append({"price": min(lows[i]["price"], lows[j]["price"]), "side": "sell", "swept": swept})
                break
    return pools[-6:]

# ═══ Snapshot ═══
def build_snapshot(candles: List[Dict]) -> Dict:
    if not candles or len(candles) < 30:
        return {}
    closes = [c["close"] for c in candles]
    cur = closes[-1]
    e20 = compute_ema(closes, 20)
    e40 = compute_ema(closes, 40)
    e200 = compute_ema(closes, 200) if len(closes) >= 200 else []
    ema20, ema40, ema200 = (e20[-1] if e20 else 0), (e40[-1] if e40 else 0), (e200[-1] if e200 else 0)
    macd = compute_macd(candles)
    rsi = compute_rsi(candles)
    atr = compute_atr(candles)
    structure = detect_bos_choch(candles)
    obs = detect_order_blocks(candles)
    fvgs = detect_fvgs(candles)
    pools = detect_liquidity_pools(candles)
    obv = [0.0]
    for i in range(1, len(candles)):
        if candles[i]["close"] > candles[i-1]["close"]:
            obv.append(obv[-1] + candles[i]["volume"])
        elif candles[i]["close"] < candles[i-1]["close"]:
            obv.append(obv[-1] - candles[i]["volume"])
        else:
            obv.append(obv[-1])
    obv_trend = "up" if len(obv) >= 20 and obv[-1] > obv[-10] else ("down" if len(obv) >= 20 and obv[-1] < obv[-10] else "flat")
    trend = structure[-1]["direction"] if structure else "neutral"
    recent_ob = None
    for ob in obs:
        if not ob["mitigated"] and ob["type"] == "bullish":
            recent_ob = ob
            break
    recent_fvg = None
    for fvg in fvgs:
        if not fvg["filled"] and fvg["type"] == "bullish":
            recent_fvg = fvg
            break
    buy_liq = next((p for p in pools if p["side"] == "buy" and not p["swept"]), None)
    sell_liq = next((p for p in pools if p["side"] == "sell" and not p["swept"]), None)
    recent_low = min(c["low"] for c in candles[-20:]) if len(candles) >= 20 else cur * 0.92
    recent_high = max(c["high"] for c in candles[-20:]) if len(candles) >= 20 else cur * 1.05
    return {
        "price": cur, "ema20": round(ema20, 6), "ema40": round(ema40, 6),
        "ema200": round(ema200, 6) if ema200 else None,
        "ema_bull_align": ema20 > ema40 and (ema40 > ema200 if ema200 else True),
        "macd": macd, "rsi": rsi, "atr": round(atr, 6),
        "trend": trend, "obv_trend": obv_trend,
        "recent_ob": recent_ob, "recent_fvg": recent_fvg,
        "buy_liquidity": buy_liq, "sell_liquidity": sell_liq,
        "recent_low": recent_low, "recent_high": recent_high,
        "structure": structure[-1] if structure else None,
    }

# ═══ Analysis ═══
@dataclass
class Analysis:
    symbol: str
    price: float
    snapshot: Dict
    score: float = 0.0
    bias: str = "neutral"
    confirmed: List[str] = field(default_factory=list)

def analyze(symbol: str, interval: str = "1d", limit: int = 90) -> Optional[Analysis]:
    candles = fetch_klines(symbol, interval, limit)
    if len(candles) < 30:
        return None
    snap = build_snapshot(candles)
    if not snap:
        return None
    score = 0.0
    confirmed = []
    # EMA (20%)
    if snap["ema_bull_align"]:
        score += 20; confirmed.append("EMA align")
    # Structure (20%)
    if snap["trend"] == "bullish":
        score += 20; confirmed.append("BOS/CHOCH bullish")
    # Volume (15%)
    if snap["obv_trend"] == "up":
        score += 15; confirmed.append("OBV rising")
    # S/R (15%)
    if snap["recent_ob"] or snap["sell_liquidity"]:
        score += 15; confirmed.append("Support present")
    # MACD (10%)
    if snap["macd"]["bullish_cross"] or (snap["macd"]["histogram"] > 0 and snap["macd"]["trend"] == "increasing"):
        score += 10; confirmed.append("MACD bullish")
    # Liquidity (10%)
    if snap["sell_liquidity"] and snap["sell_liquidity"]["swept"]:
        score += 10; confirmed.append("Liquidity sweep")
    # RSI (5%)
    if snap["rsi"]["state"] == "oversold" or snap["rsi"]["divergence"] == "bullish":
        score += 5; confirmed.append("RSI oversold/divergence")
    # SMC (5%)
    if snap["recent_fvg"] or snap["recent_ob"]:
        score += 5; confirmed.append("OB/FVG present")
    bias = "long" if score >= 50 else ("neutral" if score >= 30 else "neutral")
    return Analysis(symbol=symbol, price=snap["price"], snapshot=snap, score=score, bias=bias, confirmed=confirmed)


# ═══ 🆕 v6.3: Prefilter رخيص + Multi-Timeframe Confluence ═══

_STABLE_BASES = {"USDC","BUSD","DAI","TUSD","USDP","FDUSD","USDT","EUR","GBP","TRY",
                 "BIDR","AEUR","USDS","SUSD","PAXG","USTC","SOXLB","SOXL","SOXS",
                 "UP","DOWN","BULL","BEAR","USDSB","USTCB"}

# Ticker مجمّع (استدعاء واحد weight=80) — cache 5 دقائق
_TICKERS_CACHE: Dict = {"data": None, "ts": 0.0}
_TTL_TICKERS = 300

def get_market_tickers() -> List[Dict]:
    """🆕 v6.3: ticker 24h لكل السوق في استدعاء واحد — رخيص جداً.
    🆕 v6.4.38: تشخيص صريح عند الفشل + fallback تلقائي.
    🆕 v6.4.41: Fallback إلى CoinGecko لو Binance محظور.
    """
    global _banned_until
    now = time.time()
    if _TICKERS_CACHE["data"] and now - _TICKERS_CACHE["ts"] < _TTL_TICKERS:
        return _TICKERS_CACHE["data"]
    # 🆕 v6.4.41: لو Binance محظور، جرّب CoinGecko مباشرة
    if not is_binance_available():
        log.warning(f"⛔ get_market_tickers: Binance banned → trying CoinGecko")
        cg = get_market_tickers_coingecko()
        if cg:
            _TICKERS_CACHE["data"] = cg
            _TICKERS_CACHE["ts"] = now
            return cg
        return _TICKERS_CACHE["data"] or []
    try:
        r, used_url = _binance_get(_TICKER_URL, _TICKER_URL_FALLBACK, timeout=20)
        if r is None or r.status_code != 200:
            status = r.status_code if r is not None else "N/A"
            log.error(f"❌ [BINANCE BLOCK?] get_market_tickers HTTP {status} → trying CoinGecko")
            if r is not None and r.status_code in (403, 418, 429, 451):
                _banned_until = time.time() + 600
                log.warning(f"⛔ Binance IP-block (HTTP {r.status_code}) — pausing 10min, using CoinGecko")
            # 🆕 v6.4.41: Fallback إلى CoinGecko
            cg = get_market_tickers_coingecko()
            if cg:
                _TICKERS_CACHE["data"] = cg
                _TICKERS_CACHE["ts"] = now
                return cg
            return _TICKERS_CACHE["data"] or []
        _TICKERS_CACHE["data"] = r.json()
        _TICKERS_CACHE["ts"] = now
        return _TICKERS_CACHE["data"]
    except Exception as e:
        log.error(f"❌ [BINANCE NET ERROR] get_market_tickers: {e} → trying CoinGecko")
        # 🆕 v6.4.41: Fallback أخير إلى CoinGecko
        cg = get_market_tickers_coingecko()
        if cg:
            _TICKERS_CACHE["data"] = cg
            _TICKERS_CACHE["ts"] = now
            return cg
        return _TICKERS_CACHE["data"] or []


def prefilter_candidates(top_n: int = 25, min_change: float = -30.0,
                         max_change: float = 30.0, min_vol: float = 1e7) -> List[Dict]:
    """🆕 v6.3: المرحلة الرخيصة من الـ Funnel — استدعاء API واحد للسوق كله.

    الفلاتر (بدون أي klines):
      - سيولة: quoteVolume ≥ min_vol (10M USDT افتراضياً)
      - زخم: min_change ≤ 24h change ≤ max_change (لا نطارد القمم)
      - ترتيب: change × log10(volume) تنازلياً
    ترجع أفضل top_n مرشح للتحليل العميق.
    """
    tickers = get_market_tickers()
    if not tickers:
        return []
    cands = []
    for c in tickers:
        sym = c.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        if base in _STABLE_BASES:
            continue
        try:
            change = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])
            price = float(c["lastPrice"])
        except (ValueError, TypeError):
            continue
        if price <= 0 or vol < min_vol:
            continue
        if not (min_change <= change <= max_change):
            continue
        # وزن مركب: زخم × سيولة (log لتفادي هيمنة العملات العملاقة)
        cands.append({
            "symbol": base, "change": round(change, 2),
            "volume": vol, "price": price,
            "weight": round(change * math.log10(max(vol, 10.0)), 1),
        })
    cands.sort(key=lambda x: -x["weight"])
    return cands[:top_n]


# ═══ MTF: Multi-Timeframe Confluence ═══
# 🆕 v6.4.20: أضفنا فريمات سكالب (5m + 15m) — صفقات سريعة + تراكمية
MTF_TFS: List[Tuple[str, int]] = [("5m", 100), ("15m", 100), ("1h", 100), ("4h", 100)]
MTF_WEIGHTS: Dict[str, float] = {"4h": 0.35, "1h": 0.30, "15m": 0.20, "5m": 0.15}


def _score_from_snapshot(snap: Dict) -> Tuple[float, List[str]]:
    """🆕 v6.4.24: scoring مزدوج — استراتيجية صاعدة + استراتيجية انعكاس.

    🆕 v6.4.24: إضافة "Short-Term Reversal" — يكتشف فرص الشراء في السوق النازل.
    يحسب نقطتين منفصلتين:
      1) Trend Score (الاستراتيجية الصاعدة الأصلية)
      2) Reversal Score (استراتيجية الانعكاس الجديدة)
    يرجع أعلى نتيجة + الأسباب المناسبة.
    """
    score = 0.0
    confirmed = []

    # ═══ 1) Trend Score (الاستراتيجية الصاعدة) ═══
    trend_score = 0.0
    trend_confirmed = []

    if snap["ema_bull_align"]:
        trend_score += 20; trend_confirmed.append("EMA align")
    if snap["trend"] == "bullish":
        trend_score += 20; trend_confirmed.append("BOS/CHOCH bullish")
    if snap["obv_trend"] == "up":
        trend_score += 15; trend_confirmed.append("OBV rising")
    if snap["recent_ob"] or snap["sell_liquidity"]:
        trend_score += 15; trend_confirmed.append("Support present")
    m = snap["macd"]
    if m["bullish_cross"] or (m["histogram"] > 0 and m["trend"] == "increasing"):
        trend_score += 10; trend_confirmed.append("MACD bullish")
    if snap["sell_liquidity"] and snap["sell_liquidity"]["swept"]:
        trend_score += 10; trend_confirmed.append("Liquidity sweep")
    r = snap["rsi"]
    if r["state"] == "oversold" or r["divergence"] == "bullish":
        trend_score += 5; trend_confirmed.append("RSI oversold/divergence")
    if snap["recent_fvg"] or snap["recent_ob"]:
        trend_score += 5; trend_confirmed.append("OB/FVG present")

    # ═══ 2) Reversal Score (استراتيجية الانعكاس الجديدة) ═══
    rev_score = 0.0
    rev_confirmed = []

    # RSI oversold (تشبع بيعي = فرصة شراء)
    r = snap["rsi"]
    if r["state"] == "oversold":
        rev_score += 25; rev_confirmed.append("RSI تشبع بيعي (فرصة ارتداد)")
    elif r["rsi"] < 40:
        rev_score += 15; rev_confirmed.append(f"RSI {r['rsi']:.0f} قريب من تشبع بيعي")

    # Bullish Divergence (تباعد صاعد)
    if r["divergence"] == "bullish":
        rev_score += 20; rev_confirmed.append("RSI Divergence صاعدة (انعكاس محتمل)")

    # CHOCH bullish (انعكاس هيكلي من هابط → صاعد)
    structure = snap.get("structure")
    if structure and structure.get("type") == "CHOCH" and structure.get("direction") == "bullish":
        rev_score += 25; rev_confirmed.append("CHOCH bullish — انعكاس هيكلي (شراء)")
    elif structure and structure.get("direction") == "bullish":
        rev_score += 10; rev_confirmed.append("BOS bullish — هيكل صاعد")

    # دعم قوي (Order Block bullish)
    if snap.get("recent_ob") and not snap["recent_ob"].get("mitigated"):
        rev_score += 15; rev_confirmed.append("دعم قوي (Order Block bullish)")
    elif snap.get("buy_liquidity") and not snap["buy_liquidity"].get("swept"):
        rev_score += 10; rev_confirmed.append("سيولة شراء (دعم)")

    # FVG bullish (فجوة صاعدة غير مملوءة)
    if snap.get("recent_fvg") and not snap["recent_fvg"].get("filled"):
        rev_score += 10; rev_confirmed.append("FVG bullish (فجوة صاعدة)")

    # MACD histogram يتحسن (ينتقل من سلبي → أقل سلبياً)
    if m["histogram"] < 0 and m["trend"] == "increasing":
        rev_score += 10; rev_confirmed.append("MACD يتحسن (Histogram يضيق)")
    elif m["bullish_cross"]:
        rev_score += 15; rev_confirmed.append("MACD Bullish Cross")

    # Liquidity sweep (سحب سيولة بيعية = Smart Money يشتري)
    if snap.get("sell_liquidity") and snap["sell_liquidity"].get("swept"):
        rev_score += 10; rev_confirmed.append("Liquidity sweep (سحب سيولة)")

    # ═══ 3) اختر أعلى نتيجة ═══
    if rev_score > trend_score:
        return rev_score, rev_confirmed
    else:
        return trend_score, trend_confirmed


@dataclass
class MTFAnalysis:
    """نتيجة تحليل متعدد الفريمات لعملة واحدة."""
    symbol: str
    price: float
    tf_scores: Dict[str, float]      # {"15m": 35, "1h": 55, "4h": 70, "1d": 75}
    tf_trends: Dict[str, str]        # {"15m": "neutral", ...}
    bullish_count: int               # كم فريم صاعد مؤكد (trend=bullish + score>=40)
    confluence: float                # weighted score النهائي
    snapshot_1d: Dict                # لاستخدام SL/TP
    confirmed: List[str]             # مؤكدات مجمعة من كل الفريمات


def analyze_mtf(symbol: str) -> Optional[MTFAnalysis]:
    """🆕 v6.3: تحليل عملة واحدة على 4 فريمات (يستخدم الـ cache)."""
    snaps: Dict[str, Dict] = {}
    for tf, limit in MTF_TFS:
        candles = fetch_klines(symbol, tf, limit)
        if len(candles) < 30:
            return None  # لا نقبل تحليلاً ناقص الفريمات
        snap = build_snapshot(candles)
        if not snap:
            return None
        snaps[tf] = snap
    tf_scores, tf_trends, confirmed = {}, {}, []
    for tf, snap in snaps.items():
        s, conf = _score_from_snapshot(snap)
        tf_scores[tf] = round(s, 1)
        tf_trends[tf] = snap["trend"]
        confirmed.extend(f"{tf}: {c}" for c in conf[:3])
    bullish_count = sum(
        1 for tf in tf_scores
        if tf_trends[tf] == "bullish" and tf_scores[tf] >= 40
    )
    confluence = sum(MTF_WEIGHTS[tf] * tf_scores[tf] for tf in MTF_WEIGHTS)
    # 🆕 v6.4.23: استخدم 4h كأعلى فريم (بدل 1d الذي أُزيل)
    _highest_tf = MTF_TFS[-1][0]  # آخر فريم في القائمة (4h)
    return MTFAnalysis(
        symbol=symbol, price=snaps[_highest_tf]["price"],
        tf_scores=tf_scores, tf_trends=tf_trends,
        bullish_count=bullish_count, confluence=round(confluence, 1),
        snapshot_1d=snaps[_highest_tf], confirmed=confirmed,
    )


def analyze_mtf_batch(symbols: List[str], deadline: float = None,
                      max_workers: int = 4) -> List[MTFAnalysis]:
    """🆕 v6.3: الجلب متوازٍ (⚡ ~15s بدل ~6 دقائق) ثم التحليل التسلسلي السريع.
    🆕 v6.4.36: max_workers=2 (بدل 4) لتفادي Binance rate limit
    🆕 v6.4.103: max_workers=4 (رفع من 2) — 63 عملة × 4 فريمات = 252 طلب / 4 = 63 فقط

    - ThreadPoolExecutor(max_workers) يجلب كل (symbol × 4 TFs) بالتوازي
    - 100 طلب × 2 weight = 200 weight — آمن جداً ضمن 6000/min
    - deadline: لو انتهى الوقت نتوقف فوراً (حماية من التعليق)
    """
    if not symbols:
        return []
    # 1) جلب متوازٍ لكل (symbol, tf)
    tasks = [(s, tf, limit) for s in symbols for tf, limit in MTF_TFS]
    fetched: Dict[Tuple[str, str], List] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_klines, s, tf, lim): (s, tf) for s, tf, lim in tasks}
        for fut in as_completed(futures):
            s, tf = futures[fut]
            try:
                fetched[(s, tf)] = fut.result()
            except Exception as e:
                log.warning(f"batch fetch {s} {tf}: {e}")
                fetched[(s, tf)] = []
    # 2) تحليل تسلسلي (CPU سريع) مع احترام deadline
    results: List[MTFAnalysis] = []
    for s in symbols:
        if deadline and time.time() > deadline:
            log.warning(f"⏰ MTF deadline hit — stopping at {len(results)} results")
            break
        snaps: Dict[str, Dict] = {}
        ok = True
        for tf, _limit in MTF_TFS:
            candles = fetched.get((s, tf), [])
            if len(candles) < 30:
                ok = False
                break
            snap = build_snapshot(candles)
            if not snap:
                ok = False
                break
            snaps[tf] = snap
        if not ok:
            continue
        tf_scores, tf_trends, confirmed = {}, {}, []
        for tf, snap in snaps.items():
            sc, conf = _score_from_snapshot(snap)
            tf_scores[tf] = round(sc, 1)
            tf_trends[tf] = snap["trend"]
            confirmed.extend(f"{tf}: {c}" for c in conf[:3])
        bullish_count = sum(
            1 for tf in tf_scores
            if tf_trends[tf] == "bullish" and tf_scores[tf] >= 40
        )
        confluence = sum(MTF_WEIGHTS[tf] * tf_scores[tf] for tf in MTF_WEIGHTS)
        _highest_tf = MTF_TFS[-1][0]
        results.append(MTFAnalysis(
            symbol=s, price=snaps[_highest_tf]["price"],
            tf_scores=tf_scores, tf_trends=tf_trends,
            bullish_count=bullish_count, confluence=round(confluence, 1),
            snapshot_1d=snaps[_highest_tf], confirmed=confirmed,
        ))
    return results


def is_strong_setup(mtf: MTFAnalysis, min_bullish: int = 3,
                    min_confluence: float = 50.0) -> bool:
    """🆕 v6.3/v6.4.23: بوابة Setup القوي.

    🆕 v6.4.23: لا نتحقق من "1d" — تم استبداله بـ 4h كأعلى فريم.
    الشروط:
      1) ≥ min_bullish فريمات صاعدة (من 4)
      2) confluence ≥ min_confluence
    """
    return (
        mtf.bullish_count >= min_bullish
        and mtf.confluence >= min_confluence
    )


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.7: نظام الخروج المبكر الذكي (Smart Early Exit)
# ═══════════════════════════════════════════════════════════
# يراقب الصفقات النشطة ويكتشف علامات ضعف الاتجاه قبل وصول السعر لـ SL.
# يستخدم Confirmation متعدد المؤشرات والفريمات لتقليل الخروج الكاذب.
# لا يؤثر على نظام TP/SL الحالي — فقط يضيف تنبيه "⚠️ خروج مبكر محتمل".
# ═══════════════════════════════════════════════════════════

@dataclass
class EarlyExitSignal:
    """نتيجة تحليل الخروج المبكر — تُرسل لو بلغت قوة الإشارة الحد الأدنى."""
    symbol: str
    current_price: float
    weakness_score: int               # 0-100 (نسبة ضعف الاتجاه)
    weakness_reasons: List[str]       # قائمة بالأسباب
    bullish_count_weakening: int      # كم فريم بدأ يضعف (من 4)
    tf_analysis: Dict[str, Dict]      # تفصيل لكل فريم
    recommendation: str              # "EXIT_NOW" / "REDUCE_50%" / "WATCH" / "HOLD"
    strength: str                    # "STRONG" / "MODERATE" / "WEAK"


def detect_early_exit_signals(symbol: str, entry_price: float) -> Optional[EarlyExitSignal]:
    """🆕 v6.4.11: يكتشف علامات ضعف الاتجاه — فحص سريع بفريمين فقط (4h + 1h).

    🆕 v6.4.11 تحسين الأداء: فحص 2 فريمات فقط (4h + 1h) بدل 4.
    السبب: 4 فريمات × كل صفقة نشطة = استدعاءات API كثيرة → بطء + حظر Binance.
    4h + 1h كافيان لرؤية انعكاس الاتجاه قصير/متوسط المدى.

    يرجع EarlyExitSignal لو weakness_score ≥ 40 (Confirmation متعدد)، أو None.
    """
    try:
        # 🆕 v6.4.11: فحص فريمين فقط (4h + 1h) — أسرع بكثير
        early_exit_tfs = [("4h", 100), ("1h", 100)]
        snaps: Dict[str, Dict] = {}
        tf_results: Dict[str, Dict] = {}
        for tf, limit in early_exit_tfs:
            candles = fetch_klines(symbol, tf, limit)
            if len(candles) < 30:
                return None
            snap = build_snapshot(candles)
            if not snap:
                return None
            snaps[tf] = snap

        weakness_score = 0
        weakness_reasons: List[str] = []
        tf_weakening_count = 0

        # ── لكل فريم، افحص علامات الضعف ──
        for tf, snap in snaps.items():
            tf_score = 0
            tf_reasons: List[str] = []

            # 1) MACD Bearish Cross / Histogram Declining
            macd_data = snap.get("macd", {})
            if macd_data.get("bearish_cross"):
                tf_score += 15
                tf_reasons.append(f"{tf}: MACD Bearish Cross")
            elif macd_data.get("trend") == "decreasing" and macd_data.get("histogram", 0) < 0:
                tf_score += 10
                tf_reasons.append(f"{tf}: MACD Histogram يتراجع (سلبي)")
            elif macd_data.get("trend") == "decreasing":
                tf_score += 5
                tf_reasons.append(f"{tf}: MACD يتراجع")

            # 2) تراجع OBV / Volume
            if snap.get("obv_trend") == "down":
                tf_score += 12
                tf_reasons.append(f"{tf}: OBV هابط (تدفق أموال خارج السوق)")

            # 3) كسر EMA20 / EMA40
            price = snap.get("price", 0)
            ema20 = snap.get("ema20", 0)
            ema40 = snap.get("ema40", 0)
            if price < ema20 < ema40:
                tf_score += 15
                tf_reasons.append(f"{tf}: كسر EMA20 + EMA40 (هيكل صاعد مكسور)")
            elif price < ema20:
                tf_score += 8
                tf_reasons.append(f"{tf}: كسر EMA20")

            # 4) CHOCH / BOS هابط
            structure = snap.get("structure")
            if structure and structure.get("direction") == "bearish":
                if structure.get("type") == "CHOCH":
                    tf_score += 20
                    tf_reasons.append(f"{tf}: CHOCH هابط (انعكاس محتمل)")
                else:  # BOS bearish
                    tf_score += 12
                    tf_reasons.append(f"{tf}: BOS هابط")

            # 5) سحب السيولة / ضغط بيعي
            sell_liq = snap.get("sell_liquidity")
            if sell_liq and sell_liq.get("swept"):
                tf_score += 8
                tf_reasons.append(f"{tf}: سحب سيولة بيعية")
            buy_liq = snap.get("buy_liquidity")
            if buy_liq and not buy_liq.get("swept") and buy_liq.get("price", 0) > price * 0.99:
                tf_score += 5
                tf_reasons.append(f"{tf}: دعم قريب (سيولة شراء)")

            # 6) RSI Overbought + Divergence Bearish
            rsi_data = snap.get("rsi", {})
            if rsi_data.get("state") == "overbought":
                tf_score += 8
                tf_reasons.append(f"{tf}: RSI تشبع شرائي")
            if rsi_data.get("divergence") == "bearish":
                tf_score += 12
                tf_reasons.append(f"{tf}: RSI Divergence هابطة")

            # 7) EMA Bearish Alignment
            if not snap.get("ema_bull_align"):
                tf_score += 10
                tf_reasons.append(f"{tf}: EMA bearish alignment")

            tf_results[tf] = {
                "score": tf_score,
                "reasons": tf_reasons,
                "trend": snap.get("trend", "neutral"),
            }

            # لو الفريم فيه ≥ 20 نقطة ضعف → يُعد "ضعيف"
            if tf_score >= 20:
                tf_weakening_count += 1

            weakness_score += tf_score * MTF_WEIGHTS.get(tf, 0.25)
            weakness_reasons.extend(tf_reasons)

        # ── تحويل weakness_score إلى نسبة (0-100) ──
        weakness_score = min(100, int(weakness_score))

        # ── Confirmation متعدد: لازم ≥ 2 فريمات ضعيفة + score ≥ 40 ──
        if weakness_score < 40 or tf_weakening_count < 2:
            return None  # ليس قوياً بما يكفي

        # ── Recommendation حسب القوة ──
        if weakness_score >= 70:
            recommendation = "EXIT_NOW"
            strength = "STRONG"
        elif weakness_score >= 55:
            recommendation = "REDUCE_50%"
            strength = "MODERATE"
        else:
            recommendation = "WATCH"
            strength = "WEAK"

        return EarlyExitSignal(
            symbol=symbol,
            current_price=snaps[list(snaps.keys())[-1]]["price"],
            weakness_score=weakness_score,
            weakness_reasons=weakness_reasons[:8],  # حد أقصى 8 أسباب
            bullish_count_weakening=tf_weakening_count,
            tf_analysis=tf_results,
            recommendation=recommendation,
            strength=strength,
        )
    except Exception as e:
        log.warning(f"detect_early_exit_signals {symbol} err: {e}")
        return None
