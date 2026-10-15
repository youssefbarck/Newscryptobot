"""
Backtest — اختبار استراتيجية باستخدام engine.analyze الحقيقي
=============================================================
🆕 v6.0: يستدعي engine.analyze() (نفس محرك الإشارات الفعلي)
لا يستخدم SL/TP ثابت — يستخدم logic من signals.generate()
"""

import logging, time
from typing import Dict, List
from engine import fetch_klines, analyze, is_binance_available
from signals import generate, fmt_price

log = logging.getLogger("Backtest")

def run(strategy_filter: str, symbol: str, timeframe: str = "1d", limit: int = 90) -> Dict:
    """يختبر استراتيجية باستخدام engine.analyze (محرك الإشارات الحقيقي).

    strategy_filter: "ALL" | "EMA" | "MACD" | "RSI" | "Structure"
    يحلل كل شمعة كنقطة دخول محتملة باستخدام نفس analyze() المستخدم في البوت.
    """
    if not is_binance_available():
        return {"error": "Binance unavailable"}
    candles = fetch_klines(symbol, timeframe, limit + 50)
    if len(candles) < 50:
        return {"error": f"insufficient candles ({len(candles)})"}

    trades = []
    for i in range(50, len(candles) - 5):
        # 🆕 v6.0: استدعاء engine.analyze على البيانات حتى شمعة i (no look-ahead)
        hist = candles[:i+1]
        # محاكاة: نستبدل fetch_klines بتمرير candles مباشرة
        # engine.analyze يستدعي fetch_klines داخلياً، لكن في backtest نمرر البيانات يدوياً
        # لذلك نستخدم build_snapshot مباشرة
        from engine import build_snapshot, detect_bos_choch, compute_macd, compute_rsi, compute_ema
        snap = build_snapshot(hist)
        if not snap:
            continue

        # 🆕 v6.0: نفس منطق scoring في engine.analyze
        score = 0.0
        confirmed = []
        if strategy_filter == "EMA" or strategy_filter == "ALL":
            if snap["ema_bull_align"]:
                score += 20; confirmed.append("EMA")
        if strategy_filter == "Structure" or strategy_filter == "ALL":
            if snap["trend"] == "bullish":
                score += 20; confirmed.append("Structure")
        if strategy_filter == "MACD" or strategy_filter == "ALL":
            if snap["macd"]["bullish_cross"] or (snap["macd"]["histogram"] > 0 and snap["macd"]["trend"] == "increasing"):
                score += 10; confirmed.append("MACD")
        if strategy_filter == "RSI" or strategy_filter == "ALL":
            if snap["rsi"]["state"] == "oversold" or snap["rsi"]["divergence"] == "bullish":
                score += 5; confirmed.append("RSI")
        if strategy_filter == "Volume" or strategy_filter == "ALL":
            if snap["obv_trend"] == "up":
                score += 15; confirmed.append("Volume")
        if strategy_filter == "ALL":
            if snap["recent_ob"] or snap["sell_liquidity"]:
                score += 15; confirmed.append("S/R")
            if snap["recent_fvg"]:
                score += 5; confirmed.append("SMC")

        if score < 40:
            continue

        # 🆕 v6.0: نفس منطق SL/TP من signals.py (مش ثابت)
        entry = candles[i]["close"]
        sl = snap["recent_low"] * 0.98
        sl_pct = (sl - entry) / entry * 100
        if sl_pct < -12:
            sl = entry * 0.88; sl_pct = -12.0
        tp = snap["recent_high"] if snap["recent_high"] > entry * 1.03 else entry * 1.05
        tp_pct = (tp - entry) / entry * 100
        if tp_pct > 15:
            tp = entry * 1.05; tp_pct = 5.0
        if tp_pct < 3:
            tp = entry * 1.03; tp_pct = 3.0
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        if rr < 0.3:
            continue

        # محاكاة multi-stage TP
        pnl = 0.0
        tp1_hit = False
        for j in range(i + 1, min(i + 30, len(candles))):
            high, low = candles[j]["high"], candles[j]["low"]
            # SL check (محافظ)
            if low <= sl and not tp1_hit:
                pnl = sl_pct
                break
            if high >= tp and not tp1_hit:
                tp1_hit = True
                pnl += 0.20 * tp_pct
            if low <= sl and tp1_hit:
                pnl += 0.80 * sl_pct
                break
            if high >= tp * 1.10 and tp1_hit:
                pnl += 0.30 * (tp_pct * 1.5)
                # Check TP3
                if high >= tp * 1.15:
                    pnl += 0.50 * (tp_pct * 2.0)
                    break
        else:
            # انتهاء الصلاحية
            exit_price = candles[min(i + 30, len(candles) - 1)]["close"]
            pnl = (exit_price - entry) / entry * 100

        trades.append({"entry": entry, "sl": sl, "tp": tp, "pnl": round(pnl, 2),
                       "score": score, "confirmed": confirmed})

    total = len(trades)
    if total == 0:
        return {"error": "no trades generated — strategy too strict"}

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    wr = len(wins) / total * 100
    avg_pnl = sum(t["pnl"] for t in trades) / total
    gross_p = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_l = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    pf = gross_p / gross_l if gross_l > 0 else 999.0
    # Streaks
    cur_w = cur_l = max_w = max_l = 0
    for t in trades:
        if t["pnl"] > 0: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
        elif t["pnl"] < 0: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
        else: cur_w = cur_l = 0
    # Drawdown
    eq = pk = dd = 0
    for t in trades:
        eq += t["pnl"]
        if eq > pk: pk = eq
        dd = max(dd, pk - eq)

    return {
        "strategy": strategy_filter, "symbol": symbol, "timeframe": timeframe,
        "total_trades": total, "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1), "avg_pnl": round(avg_pnl, 2),
        "profit_factor": round(pf, 2), "max_drawdown": round(dd, 2),
        "max_winning_streak": max_w, "max_losing_streak": max_l,
        "total_pnl": round(sum(t["pnl"] for t in trades), 2),
    }

def format_result(r: Dict) -> str:
    if "error" in r:
        return f"❌ <b>Backtest</b>\n\n{r['error']}"
    msg = f"📊 <b>Backtest: {r['strategy']} على {r['symbol']}/{r['timeframe']}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"  • الصفقات: {r['total_trades']}\n"
    wr = r['win_rate']
    e = "🟢" if wr > 60 else ("🟡" if wr > 40 else "🔴")
    msg += f"  • Win Rate: {e} {wr:.1f}%\n"
    msg += f"  • ✅ رابحة: {r['wins']} | ❌ خاسرة: {r['losses']}\n"
    msg += f"  • Avg PnL: {r['avg_pnl']:+.2f}%\n"
    pf = r['profit_factor']
    pf_e = "🟢" if pf > 1.5 else ("🟡" if pf > 1.0 else "🔴")
    msg += f"  • Profit Factor: {pf_e} {pf:.2f}\n"
    msg += f"  • Max Drawdown: {r['max_drawdown']:.2f}%\n"
    msg += f"  • Max Loss Streak: {r['max_losing_streak']}\n"
    pnl = r['total_pnl']
    pe = "🟢" if pnl > 0 else "🔴"
    msg += f"  • Total PnL: {pe} {pnl:+.2f}%\n"
    msg += "\n⚠️ نتائج تاريخية — ليست ضماناً"
    return msg
