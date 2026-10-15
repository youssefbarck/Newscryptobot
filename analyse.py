"""
analyse.py — 🆕 v6.4.44: تحليل عملة من CoinGecko للمجتمع التفاعلي
================================================================

⚠️ ملف مستقل تماماً عن باقي البوت:
   - لا يستورد engine.py ولا tracker.py
   - لا يتأثر بـ scan_cycle ولا حظر Binance
   - لا يؤثر على بوت الصفقات أو الأهداف

📊 مصدر البيانات: CoinGecko (مجاني، لا يحظر IPs)
   - /coins/markets: top 200 + بيانات كاملة (price, volume, market_cap, ath, atl)
   - /search: للعثور على coin_id من symbol (لو ليس في top 200)

🧠 Score = Momentum(40) + Volume(30) + Market Rank(20) + Liquidity(10)

🛡️ احتياطات:
   - Rate limit: 10/ساعة لكل مستخدم (في bot.py)
   - Timeout: 8s (في bot.py)
   - Cache: 5 دقائق لكل عملة (في bot.py)
   - هنا: cache داخلي 60s + exception safety + symbol validation
"""

import logging
import time
import requests
from typing import Optional, Tuple

log = logging.getLogger("Analyse")

# CoinGecko endpoints
_CG_BASE = "https://api.coingecko.com/api/v3"
_CG_MARKETS = f"{_CG_BASE}/coins/markets"
_CG_SEARCH = f"{_CG_BASE}/search"

# Headers (User-Agent يخفف الـ bot detection)
_CG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Cache داخلي: {symbol: (ts, coin_data)}
# TTL 60 ثانية (مختلف عن cache bot.py)
_CG_CACHE: dict = {}
_CG_CACHE_TTL = 60  # 1 دقيقة

# قائمة Top 200 محفوظة لتفادي الـ search المتكرر
_TOP200_CACHE: dict = {}  # {symbol_upper: coin_data}
_TOP200_TS: float = 0.0
_TOP200_TTL = 300  # 5 دقائق


def _fetch_top200() -> dict:
    """يجلب قائمة Top 200 من CoinGecko (cache 5 دقائق).
    يرجع dict {SYMBOL: coin_data} للبحث السريع.
    """
    global _TOP200_TS
    now = time.time()
    if _TOP200_CACHE and now - _TOP200_TS < _TOP200_TTL:
        return _TOP200_CACHE
    try:
        r = requests.get(_CG_MARKETS, params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 200,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h,7d"
        }, headers=_CG_HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning(f"CoinGecko /markets HTTP {r.status_code}")
            return _TOP200_CACHE  # رجع القديم
        result = {}
        for coin in r.json():
            sym = (coin.get("symbol") or "").upper()
            if sym:
                # لو مكرر (مثل BTC تظهر بأكثر من id)، خد الأعلى market_cap
                if sym in result:
                    if coin.get("market_cap", 0) > result[sym].get("market_cap", 0):
                        result[sym] = coin
                else:
                    result[sym] = coin
        # تحديث cache
        _TOP200_CACHE.clear()
        _TOP200_CACHE.update(result)
        _TOP200_TS = now
        log.info(f"🦎 [CG] cached {len(result)} symbols (top 200)")
        return _TOP200_CACHE
    except Exception as e:
        log.warning(f"fetch_top200 err: {e}")
        return _TOP200_CACHE


def _search_symbol(sym: str) -> Optional[dict]:
    """Search CoinGecko لو العملة ليست في top 200.
    يرجع coin_data أو None.

    🛡️ احتياط: لو HTTP 429 (rate limit) → رجع None بدل إعادة المحاولة
    🛡️ احتياط: لو الـ coin_id مكرر (نفس الرمز لعملات كثيرة) → جرّب الأكثر شهرة
    """
    try:
        r = requests.get(_CG_SEARCH, params={"query": sym.lower()},
                        headers=_CG_HEADERS, timeout=10)
        if r.status_code == 429:
            log.warning("CoinGecko /search rate-limited (HTTP 429) — try later")
            return None
        if r.status_code != 200:
            log.warning(f"CoinGecko /search HTTP {r.status_code}")
            return None
        coins = r.json().get("coins", [])
        # اجمع كل التطابقات بنفس symbol
        matching = [c for c in coins if (c.get("symbol") or "").upper() == sym]
        if not matching:
            # لو لا يوجد تطابق دقيق، جرّب أول 3 (محاولة أفضل)
            matching = coins[:3]
        # رتّب حسب market_cap_rank (الأصغر = الأعلى شهرة) — None يروح للنهاية
        matching.sort(key=lambda c: c.get("market_cap_rank") or 99999)

        for c in matching[:3]:  # جرّب أعلى 3
            coin_id = c.get("id")
            if not coin_id:
                continue
            try:
                # 🆕 v6.4.44: استخدم /coins/{id} مع market_data فقط (lightweight)
                r3 = requests.get(f"{_CG_BASE}/coins/{coin_id}",
                                  params={"localization": False, "tickers": False,
                                          "market_data": True, "community_data": False,
                                          "developer_data": False, "sparkline": False},
                                  headers=_CG_HEADERS, timeout=10)
                if r3.status_code == 429:
                    log.warning(f"CoinGecko /coins/{coin_id} rate-limited")
                    continue
                if r3.status_code != 200:
                    continue
                coin = r3.json()
                md = coin.get("market_data", {})
                # 🛡️ تحقق من وجود سعر صالح
                price = md.get("current_price", {}).get("usd")
                if not price or price <= 0:
                    continue
                return {
                    "id": coin.get("id"),
                    "symbol": (coin.get("symbol") or "").upper(),
                    "name": coin.get("name"),
                    "current_price": price,
                    "market_cap": md.get("market_cap", {}).get("usd", 0) or 0,
                    "market_cap_rank": md.get("market_cap_rank"),
                    "total_volume": md.get("total_volume", {}).get("usd", 0) or 0,
                    "high_24h": md.get("high_24h", {}).get("usd", 0) or 0,
                    "low_24h": md.get("low_24h", {}).get("usd", 0) or 0,
                    "price_change_percentage_24h": md.get("price_change_percentage_24h", 0) or 0,
                    "price_change_percentage_7d_in_currency": md.get("price_change_percentage_7d_in_currency", {}).get("usd", 0) or 0,
                    "ath": md.get("ath", {}).get("usd", 0) or 0,
                    "ath_change_percentage": md.get("ath_change_percentage", {}).get("usd", 0) or 0,
                    "atl": md.get("atl", {}).get("usd", 0) or 0,
                }
            except Exception as e:
                log.warning(f"fetch {coin_id} err: {e}")
                continue
        return None
    except Exception as e:
        log.warning(f"search_symbol {sym} err: {e}")
        return None


def get_coin_data(sym: str) -> Optional[dict]:
    """يجلب بيانات عملة من CoinGecko.
    1) جرّب من Top 200 cache (سريع جداً)
    2) لو غير موجود → جرّب /search
    3) لو فشل كلاهما → None
    """
    sym = sym.upper().strip()
    if not sym:
        return None

    # 🛡️ cache داخلي (60s) — حتى لو bot.py cache نفذ
    now = time.time()
    if sym in _CG_CACHE:
        ts, data = _CG_CACHE[sym]
        if now - ts < _CG_CACHE_TTL:
            return data

    # 1) من Top 200
    top = _fetch_top200()
    if sym in top:
        coin = top[sym]
        _CG_CACHE[sym] = (now, coin)
        return coin

    # 2) /search — للعملات خارج Top 200
    coin = _search_symbol(sym)
    if coin:
        _CG_CACHE[sym] = (now, coin)
        return coin

    return None


def calculate_score(coin: dict) -> Tuple[float, dict]:
    """يحسب Score من 100 بناءً على:
    - Momentum (40 نقطة): تغير 24h + 7d
    - Volume (30 نقطة): حجم 24h
    - Market Rank (20 نقطة): ترتيب market cap
    - Liquidity (10 نقطة): Volume / Market Cap

    يرجع (score, breakdown_dict)
    """
    breakdown = {"momentum": 0, "volume": 0, "rank": 0, "liquidity": 0}

    # 1) Momentum (40 نقطة) — أهم مؤشر
    chg_24h = coin.get("price_change_percentage_24h") or 0
    chg_7d = coin.get("price_change_percentage_7d_in_currency") or 0
    # مزج 24h (70%) + 7d (30%)
    momentum_combined = (chg_24h * 0.7) + (chg_7d * 0.3)
    if momentum_combined >= 8:  # زخم قوي جداً
        breakdown["momentum"] = 40
    elif momentum_combined >= 3:
        breakdown["momentum"] = 30
    elif momentum_combined >= 0:
        breakdown["momentum"] = 20
    elif momentum_combined >= -3:
        breakdown["momentum"] = 10
    else:
        breakdown["momentum"] = 0

    # 2) Volume (30 نقطة) — السيولة
    vol = coin.get("total_volume") or 0
    if vol >= 100e6:  # $100M+
        breakdown["volume"] = 30
    elif vol >= 30e6:  # $30M+
        breakdown["volume"] = 25
    elif vol >= 10e6:  # $10M+
        breakdown["volume"] = 20
    elif vol >= 1e6:  # $1M+
        breakdown["volume"] = 10
    else:
        breakdown["volume"] = 3

    # 3) Market Rank (20 نقطة) — الاستقرار
    rank = coin.get("market_cap_rank") or 9999
    if rank <= 10:
        breakdown["rank"] = 20
    elif rank <= 50:
        breakdown["rank"] = 18
    elif rank <= 100:
        breakdown["rank"] = 14
    elif rank <= 200:
        breakdown["rank"] = 10
    elif rank <= 500:
        breakdown["rank"] = 6
    else:
        breakdown["rank"] = 3

    # 4) Liquidity (10 نقطة) — Volume / Market Cap ratio
    mcap = coin.get("market_cap") or 0
    if mcap > 0:
        ratio = vol / mcap
        if ratio >= 0.15:  # سيولة عالية جداً
            breakdown["liquidity"] = 10
        elif ratio >= 0.08:
            breakdown["liquidity"] = 8
        elif ratio >= 0.04:
            breakdown["liquidity"] = 5
        elif ratio >= 0.01:
            breakdown["liquidity"] = 3
        else:
            breakdown["liquidity"] = 1
    else:
        breakdown["liquidity"] = 0

    total = sum(breakdown.values())
    return total, breakdown


def get_recommendation(score: float, chg_24h: float, vol: float) -> Tuple[str, str, float, float, float, float]:
    """يرجع (recommendation_icon, action_text, entry_low, entry_high, sl_pct, tp_pct).

    🧠 4 مستويات:
    - 🟢 شراء مباشر:    score ≥ 80 + momentum قوي
    - 🟡 شراء مع حذر:   score ≥ 55
    - 🟠 انتظر تصحيح:   score ≥ 30
    - ❌ لا تدخل:       score < 30
    """
    price = 1.0  # placeholder — سيُضرب في السعر الحقيقي
    has_momentum = chg_24h > 1.5  # زخم 24h إيجابي
    has_volume = vol >= 10e6  # سيولة كافية

    if score >= 80 and has_momentum and has_volume:
        rec = "🟢 شراء مباشر"
        action = "الفرصة جيدة — ادخل الآن"
        entry_low = 0.99   # -1% من السعر
        entry_high = 1.01  # +1%
        sl_pct = 0.08      # -8%
        tp_pct = 0.25     # +25% (هدف طموح لكن واقعي مع زخم قوي)
    elif score >= 55 and has_volume:
        rec = "🟡 شراء مع حذر"
        action = "نص حجم فقط — انتظر تأكيد السوق"
        entry_low = 0.98
        entry_high = 1.00
        sl_pct = 0.08
        tp_pct = 0.15  # +15% (أكثر تحفظاً)
    elif score >= 30:
        rec = "🟠 انتظر تصحيح"
        action = "انتظر انخفاض 5% قبل الدخول"
        entry_low = 0.93
        entry_high = 0.95
        sl_pct = 0.07  # SL أضيق (لأن الدخول بعد تصحيح)
        tp_pct = 0.12  # +12%
    else:
        rec = "❌ لا تدخل الآن"
        action = "العملة ضعيفة — ابحث عن فرصة أخرى"
        entry_low = 0.90
        entry_high = 0.95
        sl_pct = 0.05  # SL ضيق (لو دخلت، تحكم سريع)
        tp_pct = 0.08  # هدف صغير

    return rec, action, entry_low, entry_high, sl_pct, tp_pct


def build_response(sym: str, coin: dict) -> str:
    """يبني رد Telegram HTML منسق للتحليل.
    يعمل بشكل مستقل — لا يستدعي engine.py ولا tracker.py.
    """
    try:
        price = coin.get("current_price") or 0
        if not price or price <= 0:
            return f"❌ لا توجد بيانات سعر لـ {sym}"

        chg_24h = coin.get("price_change_percentage_24h") or 0
        chg_7d = coin.get("price_change_percentage_7d_in_currency") or 0
        vol = coin.get("total_volume") or 0
        mcap = coin.get("market_cap") or 0
        rank = coin.get("market_cap_rank") or 9999
        ath = coin.get("ath") or 0
        ath_chg = coin.get("ath_change_percentage") or 0
        high_24 = coin.get("high_24h") or 0
        low_24 = coin.get("low_24h") or 0
        name = coin.get("name") or sym

        # حساب Score + breakdown
        score, breakdown = calculate_score(coin)

        # توليد التوصية
        rec, action, entry_low_pct, entry_high_pct, sl_pct, tp_pct = get_recommendation(score, chg_24h, vol)

        entry_low = price * entry_low_pct
        entry_high = price * entry_high_pct
        sl_price = price * (1 - sl_pct)
        tp_price = price * (1 + tp_pct)
        rr = tp_pct / sl_pct if sl_pct > 0 else 0

        # تنسيق الأرقام
        def fmt(p):
            if p >= 1000:
                return f"{p:,.2f}"
            elif p >= 1:
                return f"{p:,.4f}"
            else:
                return f"{p:,.6f}"

        # لون الرمز للتغير 24h
        chg_icon = "🟢" if chg_24h > 0 else "🔴" if chg_24h < 0 else "⚪"
        vol_str = f"${vol/1e6:.1f}M" if vol < 1e9 else f"${vol/1e9:.2f}B"
        mcap_str = f"${mcap/1e9:.2f}B" if mcap >= 1e9 else f"${mcap/1e6:.0f}M"
        rank_str = f"#{rank}" if rank <= 200 else "خارج Top 200"

        # مؤشرات إضافية
        range_24h_pct = ((high_24 - low_24) / low_24 * 100) if low_24 > 0 else 0
        vol_mcap_ratio = (vol / mcap * 100) if mcap > 0 else 0

        response = (
            f"📊 <b>تحليل {sym}/USDT</b>\n"
            f"<i>{name}</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 السعر: <code>${fmt(price)}</code> {chg_icon} {chg_24h:+.2f}%\n"
            f"📈 7d: {chg_7d:+.2f}% | نطاق 24h: {range_24h_pct:.1f}%\n"
            f"📊 Volume: <b>{vol_str}</b> | MCap: {mcap_str} ({rank_str})\n\n"
            f"🎯 <b>Score: {score:.0f}/100</b>\n"
            f"  • Momentum: <b>+{breakdown['momentum']}</b>/40 ({chg_24h:+.1f}%)\n"
            f"  • Volume:   <b>+{breakdown['volume']}</b>/30\n"
            f"  • Rank:     <b>+{breakdown['rank']}</b>/20\n"
            f"  • Liquidity:<b>+{breakdown['liquidity']}</b>/10 ({vol_mcap_ratio:.1f}% V/MC)\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 <b>التوصية: {rec}</b>\n"
            f"💡 {action}\n\n"
            f"📍 دخول: <code>${fmt(entry_low)} - ${fmt(entry_high)}</code>\n"
            f"🛑 SL: <code>${fmt(sl_price)}</code> ({-sl_pct*100:+.0f}%)\n"
            f"🎯 TP: <code>${fmt(tp_price)}</code> (+{tp_pct*100:.0f}%)\n"
            f"⚖️ R/R: <b>{rr:.2f}</b> {'✅' if rr >= 2 else '⚠️' if rr >= 1 else '❌'}\n"
        )

        # معلومات إضافية (ATH/ATL) — مفيدة للمجتمع
        if ath > 0:
            response += f"\n📊 ATH: ${fmt(ath)} ({ath_chg:+.1f}% من القمة)\n"

        response += "\n⚠️ <i>تحليل فني فقط — ليس نصيحة استثمارية</i>"

        # 🛡️ احتياط: طول الرسالة (Telegram 4096)
        if len(response) > 4000:
            response = response[:3990] + "\n\n[...]"

        return response
    except Exception as e:
        log.error(f"❌ build_response err: {e}")
        return f"❌ خطأ داخلي في تحليل {sym}"


def analyse_symbol(sym: str) -> Optional[str]:
    """نقطة الدخول الوحيدة — يُستدعى من bot.py.
    يرجع نص الرد أو None لو فشل.
    """
    try:
        # تحقق صحة الرمز (defensive)
        sym = (sym or "").upper().strip().replace("/", "").replace("-", "").replace("$", "")
        if not sym or not sym.isalpha() or len(sym) > 12 or len(sym) < 2:
            return None

        coin = get_coin_data(sym)
        if not coin:
            return f"❌ لا توجد بيانات لـ <b>{sym}</b>\n\n💡 جرّب عملة من CoinGecko Top 200 (BTC, ETH, SOL, BNB, XRP...)"

        return build_response(sym, coin)
    except Exception as e:
        log.error(f"❌ analyse_symbol err: {e}")
        return f"❌ خطأ في تحليل {sym}"
