"""
Signals — Entry Zone + 3 Targets (TP1/TP2/TP3) + SL + Position Sizing
=====================================================================
🆕 v6.4 تحسينات كاملة:
  1) Entry Zone (low-high) بدل نقطة واحدة — يحترم مستويات الدعم
  2) 3 أهداف بدل 1:
     - TP1 = 1.5R — بِع 50% (جني أرباح أولي)
     - TP2 = 3R   — بِع 30% (انسحاب تدريجي)
     - TP3 = 5R   — بِع 20% الأخير (الـ moon)
  3) Position Sizing — مخاطرة 2% من رأس المال الافتراضي
  4) R/R واضح (1:5 لـ TP3)
  5) صلاحية 12 ساعة + expiry timestamp
  6) dedup_key لمنع تكرار نفس العملة قبل 6 ساعات
  7) لغة مبسّطة للمبتدئ + شرح كل مؤكد
  8) تنسيق TP/SL alerts محسّن — الربح بالدولار + الخطوة التالية
"""

import logging, time, os, math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger("Signals")

# 🆕 v6.4: إعدادات من env
# 🆕 v6.4.45: raised from 0.8 to 2.0 — 🆕 v6.4.85: تشديد صارم إلى 3.0
# 🆕 v6.4.94: تخفيف إلى 2.0 — 🆕 v6.4.101: مزامنة مع bot.py (كانت 3.0 هنا = سبب رفض 22 عملة!)
MIN_RR_RATIO = float(os.environ.get("MIN_RR_RATIO", "2.0"))
HQ_DEFAULT_CAPITAL = float(os.environ.get("HQ_DEFAULT_CAPITAL", "500"))
HQ_RISK_PER_TRADE = float(os.environ.get("HQ_RISK_PER_TRADE", "0.02"))  # 2%
HQ_SIGNAL_EXPIRY_HOURS = int(os.environ.get("HQ_SIGNAL_EXPIRY_HOURS", "12"))
HQ_DEDUP_HOURS = int(os.environ.get("HQ_DEDUP_HOURS", "6"))


# ═══ Signal ═══
@dataclass
class Signal:
    symbol: str
    entry: float                      # سعر الدخول المرجعي (منتصف zone)
    entry_low: float                 # 🆕 v6.4: أقل حد لمنطقة الدخول
    entry_high: float                # 🆕 v6.4: أعلى حد لمنطقة الدخول
    sl: float
    tp1: float                       # 🆕 v6.4.4: +1%
    tp2: float                       # 🆕 v6.4.4: +4%
    tp3: float                       # 🆕 v6.4.4: +8%
    tp4: float = 0.0                 # 🆕 v6.4.4: +12%
    tp5: float = 0.0                 # 🆕 v6.4.4: +15%
    tp6: float = 0.0                 # 🆕 v6.4.4: +20%+ (هدف قوي اختياري)
    tp_pct: float = 0.0              # للتوافق القديم = tp3_pct
    sl_pct: float = 0.0
    tp1_pct: float = 1.0
    tp2_pct: float = 4.0
    tp3_pct: float = 8.0
    tp4_pct: float = 12.0
    tp5_pct: float = 15.0
    tp6_pct: float = 0.0             # 🆕 v6.4.4: هدف قوي (لو >0)
    rr: float = 0.0                 # للتوافق القديم
    rr_tp1: float = 1.5
    rr_tp2: float = 3.0
    score: float = 0.0
    confirmed: List[str] = field(default_factory=list)
    created_at: int = 0
    signal_id: str = ""
    # 🆕 v6.4: Position Sizing
    risk_pct: float = 0.0
    position_size_usd: float = 0.0
    position_size_pct: float = 0.0
    risk_amount_usd: float = 0.0
    # 🆕 v6.4: Expiry
    valid_until: int = 0
    # 🆕 v6.4: BTC trend (إن وُجد)
    btc_trend: str = ""
    # 🆕 v6.4.4: علامة "صفقة مكررة" (عدد النجوم المكتسبة)
    is_update: bool = False
    update_stars: int = 0            # 1, 2, أو 3 (حد أقصى)


def fmt_price(p: float) -> str:
    if p >= 1000: return f"${p:,.2f}"
    if p >= 1: return f"${p:,.4f}"
    if p >= 0.01: return f"${p:,.6f}"
    if p > 0: return f"${p:,.8f}"
    return "$0"


def _calc_levels(entry: float, snap: Dict, score: float = 0) -> Optional[Tuple]:
    """🆕 v6.4.4: حساب كامل — entry_zone + SL + 5 أهداف ثابتة (1%, 4%, 8%, 12%, 15%).

    🆕 v6.4.4 تغيير جذري: الأهداف أصبحت نسب ثابتة بدل R-multiples.
    لو score >= 75 → أضف هدف 6 (TP4 — قوي، قابل للتحقق).

    يرجع: (entry_low, entry_high, sl, sl_pct,
            tp1..tp5, tp1_pct..tp5_pct,
            risk_pct, position_size_usd, position_size_pct, risk_amount_usd)
    أو None لو R/R مرفوض.
    """
    recent_low = snap.get("recent_low", entry * 0.92)
    atr = snap.get("atr", entry * 0.03)
    recent_high = snap.get("recent_high", entry * 1.05)

    # ── 🆕 v6.4.45: SL ديناميكي (ATR-based) بدل ثابت -8%
    # المنطق: SL = 1.5 × ATR تحت الدخول (يتناسب مع تقلب العملة)
    # حد أدنى: 5% (لا يقل) | حد أعلى: 25% (لا يزيد)
    sl_candidate_1 = recent_low * 0.98
    sl_candidate_2 = entry - 1.5 * atr
    sl = max(sl_candidate_1, sl_candidate_2)
    sl_pct = (sl - entry) / entry * 100
    # 🆕 v6.4.45: حدود ديناميكية بدل ثابت -8%
    if sl_pct < -25:
        sl = entry * 0.75; sl_pct = -25.0  # حد أقصى 25% (للعملات المتطرفة)
    if sl_pct > -5:
        sl = entry * 0.95; sl_pct = -5.0   # حد أدنى 5% (للعملات المستقرة)

    # ── 🆕 v6.4.28: Entry Zone محسّن — شراء عند الدعم/التصحيح، ليس عند القمة
    # المشكلة القديمة: entry_high = entry (السعر الحالي) → يشتري القمة
    # الحل: entry_high = entry - 0.3*ATR (أسفل السعر الحالي بقليل = انتظر تصحيح)
    # entry_low = entry - 1.5*ATR (الدعم الحقيقي)
    entry_high = entry - 0.3 * atr  # 🆕 v6.4.28: أسفل السعر بقليل
    entry_low = max(recent_low, entry - 1.5 * atr)  # 🆕 v6.4.28: الدعم
    if entry_low > entry_high:
        entry_low = entry_high * 0.97  # fallback: 3% تحت entry_high
    # 🆕 v6.4.28: لو السعر فوق recent_high (قمة) → لا تشتري — انتظر ارتداد
    # entry_high يجب أن يكون أقل من recent_high بـ 0.5% على الأقل
    if recent_high > 0 and entry_high >= recent_high * 0.995:
        entry_high = recent_high * 0.985  # 1.5% تحت القمة
        entry_low = max(recent_low, entry_high - 1.0 * atr)
        if entry_low > entry_high:
            entry_low = entry_high * 0.97

    risk_per_unit = abs(entry_high - sl)
    if risk_per_unit <= 0:
        return None

    # ── 🆕 v6.4.45: TPs ديناميكية (ATR multiples) بدل ثابتة %
    # المنطق: TPs = entry + (1, 2, 3, 4, 6) × ATR
    # هذا يضمن R/R ≥ 2.0 (TP3 / SL = 3/1.5 = 2.0)
    tp1 = entry + 1.0 * atr  # 1×ATR (~3% للـ BTC، ~15% للـ SOL)
    tp2 = entry + 2.0 * atr  # 2×ATR
    tp3 = entry + 3.0 * atr  # 3×ATR (R/R = 2.0 مع SL 1.5×ATR)
    tp4 = entry + 4.0 * atr  # 4×ATR
    tp5 = entry + 6.0 * atr  # 6×ATR (الهدف الطموح)
    tp1_pct = ((tp1 - entry) / entry) * 100
    tp2_pct = ((tp2 - entry) / entry) * 100
    tp3_pct = ((tp3 - entry) / entry) * 100
    tp4_pct = ((tp4 - entry) / entry) * 100
    tp5_pct = ((tp5 - entry) / entry) * 100

    # 🆕 v6.4.4: هدف إضافي "خارج النطاق" لو score قوي (≥75) + الـ ATR يدعمه
    # TP6 = +20% أو أعلى (محسوب من recent_high لو متاح، أو +20% افتراضياً)
    tp6 = 0.0
    tp6_pct = 0.0
    if score >= 75:
        # لو recent_high يبعد ≥ 18% → استخدمه كهدف قوي ( قابل للتحقق)
        potential_target = max(entry * 1.20, recent_high)
        if potential_target > entry * 1.18:
            tp6 = potential_target
            tp6_pct = ((tp6 - entry) / entry) * 100

    # ── 🆕 v6.4.45: فلتر R/R ديناميكي (ATR-based)
    # قبل: reward_tp3 = 8.0 ثابت (خاطئ — لا يتناسب مع ATR)
    # بعد: reward_tp3 = tp3_pct (محسوب من ATR)
    risk_for_rr = abs(entry - sl) / entry * 100
    reward_tp3 = tp3_pct  # 🆕 v6.4.45: ديناميكي من ATR
    rr_tp3 = reward_tp3 / risk_for_rr if risk_for_rr > 0 else 0
    # 🆕 v6.4.45: صحة floating point — استخدم 1.95 بدل 2.0 (يسمح لـ 1.9999)
    if rr_tp3 < (MIN_RR_RATIO * 0.975):
        return None

    # ── Position Sizing
    risk_pct = abs(sl_pct)
    if risk_pct > 0:
        risk_amount_usd = HQ_DEFAULT_CAPITAL * HQ_RISK_PER_TRADE
        position_size_usd = (risk_amount_usd / risk_pct) * 100
        position_size_usd = min(position_size_usd, HQ_DEFAULT_CAPITAL * 0.5)
    else:
        risk_amount_usd = HQ_DEFAULT_CAPITAL * HQ_RISK_PER_TRADE
        position_size_usd = HQ_DEFAULT_CAPITAL * 0.1
    position_size_pct = (position_size_usd / HQ_DEFAULT_CAPITAL) * 100

    return (entry_low, entry_high, sl, sl_pct,
            tp1, tp1_pct, tp2, tp2_pct, tp3, tp3_pct, tp4, tp4_pct, tp5, tp5_pct,
            tp6, tp6_pct,
            risk_pct, position_size_usd, position_size_pct, risk_amount_usd)


def generate(symbol: str, analysis) -> Optional[Signal]:
    """للتوافق مع الكود القديم (v6.3) — يستخدم 1d snapshot."""
    if not analysis or analysis.score < 50:  # 🆕 v6.4.45: raised from 40 to 50
        return None
    entry = analysis.price
    levels = _calc_levels(entry, analysis.snapshot, score=analysis.score)
    if not levels:
        return None
    (entry_low, entry_high, sl, sl_pct,
     tp1, tp1_pct, tp2, tp2_pct, tp3, tp3_pct,
     tp4, tp4_pct, tp5, tp5_pct, tp6, tp6_pct,
     risk_pct, position_size_usd, position_size_pct, risk_amount_usd) = levels

    sid = f"{symbol}_{int(time.time())}"
    valid_until = int(time.time()) + HQ_SIGNAL_EXPIRY_HOURS * 3600

    return Signal(
        symbol=symbol, entry=entry, entry_low=entry_low, entry_high=entry_high,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, tp4=tp4, tp5=tp5, tp6=tp6,
        tp_pct=tp3_pct, sl_pct=sl_pct,
        tp1_pct=tp1_pct, tp2_pct=tp2_pct, tp3_pct=tp3_pct,
        tp4_pct=tp4_pct, tp5_pct=tp5_pct, tp6_pct=tp6_pct,
        rr=5.0, rr_tp1=1.5, rr_tp2=3.0,
        score=analysis.score, confirmed=analysis.confirmed,
        created_at=int(time.time()), signal_id=sid,
        risk_pct=risk_pct, position_size_usd=position_size_usd,
        position_size_pct=position_size_pct, risk_amount_usd=risk_amount_usd,
        valid_until=valid_until,
    )


def generate_mtf(symbol: str, mtf) -> Optional[Signal]:
    """🆕 v6.3/v6.4.4: توليد إشارة من MTFAnalysis مع 5 أهداف ثابتة (+1%, +4%, +8%, +12%, +15%) + هدف قوي اختياري."""
    if mtf is None:
        return None
    entry = mtf.price
    levels = _calc_levels(entry, mtf.snapshot_1d, score=mtf.confluence)
    if not levels:
        return None
    (entry_low, entry_high, sl, sl_pct,
     tp1, tp1_pct, tp2, tp2_pct, tp3, tp3_pct,
     tp4, tp4_pct, tp5, tp5_pct, tp6, tp6_pct,
     risk_pct, position_size_usd, position_size_pct, risk_amount_usd) = levels

    sid = f"{symbol}_{int(time.time())}"
    valid_until = int(time.time()) + HQ_SIGNAL_EXPIRY_HOURS * 3600

    return Signal(
        symbol=symbol, entry=entry, entry_low=entry_low, entry_high=entry_high,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, tp4=tp4, tp5=tp5, tp6=tp6,
        tp_pct=tp3_pct, sl_pct=sl_pct,
        tp1_pct=tp1_pct, tp2_pct=tp2_pct, tp3_pct=tp3_pct,
        tp4_pct=tp4_pct, tp5_pct=tp5_pct, tp6_pct=tp6_pct,
        rr=5.0, rr_tp1=1.5, rr_tp2=3.0,
        score=mtf.confluence, confirmed=mtf.confirmed,
        created_at=int(time.time()), signal_id=sid,
        risk_pct=risk_pct, position_size_usd=position_size_usd,
        position_size_pct=position_size_pct, risk_amount_usd=risk_amount_usd,
        valid_until=valid_until,
    )


# ═══ 🆕 v6.4: BTC Trend Check (cache 30min) ═══
_btc_trend_cache: Dict = {"ts": 0.0, "trend": "unknown"}


def get_btc_1d_trend() -> str:
    """🆕 v6.4: يفحص اتجاه BTC على 1D (cache 30 دقيقة).
    يرجع: "صاعد" / "هابط" / "محايد" / "unknown"
    """
    from engine import fetch_klines, compute_ema  # lazy import
    now = time.time()
    if now - _btc_trend_cache["ts"] < 1800:
        return _btc_trend_cache["trend"]

    candles = fetch_klines("BTC", "1d", 60)
    if len(candles) < 30:
        return "unknown"
    closes = [c["close"] for c in candles]
    e20 = compute_ema(closes, 20)
    e50 = compute_ema(closes, 50)
    if not e20 or not e50:
        return "unknown"
    price = closes[-1]
    ema20 = e20[-1]
    ema50 = e50[-1]
    if price > ema20 > ema50:
        trend = "صاعد"
    elif price < ema20 < ema50:
        trend = "هابط"
    else:
        trend = "محايد"
    _btc_trend_cache["ts"] = now
    _btc_trend_cache["trend"] = trend
    return trend


# ═══ 🆕 v6.4: Dedup helper — منع تكرار الإشارة قبل HQ_DEDUP_HOURS ═══
_last_signal_ts: Dict[str, float] = {}


def is_recently_signaled(symbol: str) -> bool:
    """يفحص لو أُرسلت إشارة لنفس العملة قبل أقل من HQ_DEDUP_HOURS."""
    last = _last_signal_ts.get(symbol, 0)
    return (time.time() - last) < HQ_DEDUP_HOURS * 3600


def mark_signal_sent(symbol: str):
    """يسجّل أن إشارة أُرسلت للعملة الآن."""
    _last_signal_ts[symbol] = time.time()


def clear_signal_dedup(symbol: str):
    """🆕 v6.4.6: يمسح خريطة dedup للعملة — يُستدعى بعد إغلاق الصفقة كاملة.

    يسمح بإرسال إشارة جديدة فوراً بعد إغلاق الصفقة الحالية (TP5/TP6/SL).
    بدون هذا، يجب انتظار HQ_DEDUP_HOURS بعد الإشارة الأولى قبل سماح بإشارة جديدة.
    """
    _last_signal_ts.pop(symbol, None)


# ═══ 🆕 v6.4: تنسيق رسالة الإشارة المبسّطة ═══

def _tier_emoji(score: float) -> Tuple[str, str]:
    """يرجع (emoji, label) بناءً على score."""
    if score >= 85:
        return ("🟢", "ممتاز")
    if score >= 75:
        return ("🟢", "قوي جداً")
    if score >= 60:
        return ("🟡", "قوي")
    if score >= 50:
        return ("🟠", "متوسط")
    return ("🔴", "ضعيف")


def _trend_emoji(trend: str) -> str:
    return {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(trend, "➡️")


def _translate_confirmed(c: str) -> str:
    """ترجمة المؤشرات الفنية للعربية مبسّطة."""
    translations = {
        "EMA align": "المتوسطات صاعدة (EMA)",
        "BOS/CHOCH bullish": "هيكل السوق مكسور صاعد",
        "OBV rising": "تدفق الأموال داخل السوق (OBV)",
        "Support present": "يوجد دعم قوي تحت السعر",
        "MACD bullish": "زخم MACD إيجابي",
        "Liquidity sweep": "التقاط سيولة (Smart Money)",
        "RSI oversold/divergence": "مؤشر RSI في منطقة آمنة",
        "OB/FVG present": "أوردر بلوك أو فجوة (OB/FVG)",
    }
    # للـ MTF: prefix "1d: " أو "4h: " إلخ
    if c.startswith(("15m:", "1h:", "4h:", "1d:")):
        prefix, rest = c.split(":", 1)
        rest = rest.strip()
        return f"<code>{prefix.upper()}</code>: {translations.get(rest, rest)}"
    return translations.get(c, c)


def format_mtf_table(mtf) -> str:
    """جدول توافق الفريمات للرسالة."""
    rows = []
    for tf in ["1d", "4h", "1h", "15m"]:
        trend = mtf.tf_trends.get(tf, "?")
        score = mtf.tf_scores.get(tf, 0)
        icon = "🟢" if trend == "bullish" else ("🔴" if trend == "bearish" else "⚪")
        rows.append(f"  {icon} {tf.upper():>4}: {trend:<8} ({score:.0f})")
    return "\n".join(rows)


def format_signal_mtf_simple(sig: Signal, mtf, target: str = "channel") -> str:
    """🆕 v6.4.93: تنسيق مبسط ومرتب — فراغ بين كل قسم + فقط الأساسيات."""
    stars = "⭐⭐⭐" if mtf.bullish_count == 4 and sig.score >= 75 else (
            "⭐⭐" if mtf.bullish_count >= 3 else "⭐")
    btc_emoji = "✅" if sig.btc_trend == "صاعد" else ("⚠️" if sig.btc_trend == "هابط" else "➡️")

    # 🆕 v6.4.83: نسبة السيولة الذكية
    try:
        _smart_liq = compute_smart_liquidity_pct(mtf)
        _liq_label = "🟢 احترافي" if _smart_liq >= 50 else ("🟡 جيد" if _smart_liq >= 30 else "⚪ ضعيف")
    except Exception:
        _smart_liq = 0; _liq_label = "—"

    # 🆕 v6.4.93: تنسيق مبسط + فراغات واضحة بين الأقسام
    dot = "🟢" if target == "channel" else "🔴"
    msg = f"💎 {dot} <b>{sig.symbol}</b> 💎V1 {stars} {btc_emoji}\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"
    msg += f"💰 <b>الدخول:</b> {fmt_price(sig.entry_low)} - {fmt_price(sig.entry_high)}\n\n"
    msg += f"🛑 <b>الوقف:</b> {fmt_price(sig.sl)} ({sig.sl_pct:+.1f}%)\n\n"
    msg += f"🎯 <b>الأهداف</b>\n"
    msg += f"TP1: {fmt_price(sig.tp1)} (+{sig.tp1_pct:.0f}%)\n"
    msg += f"TP2: {fmt_price(sig.tp2)} (+{sig.tp2_pct:.0f}%)\n"
    msg += f"TP3: {fmt_price(sig.tp3)} (+{sig.tp3_pct:.0f}%)\n"
    msg += f"TP4: {fmt_price(sig.tp4)} (+{sig.tp4_pct:.0f}%)\n"
    msg += f"TP5: {fmt_price(sig.tp5)} (+{sig.tp5_pct:.0f}%)\n"
    if sig.tp6 > 0:
        msg += f"🎯 TP6: {fmt_price(sig.tp6)} (+{sig.tp6_pct:.0f}%) ⚡\n"
    msg += "\n"
    msg += f"📊 النجاح: {sig.score:.0f}%\n"
    msg += f"💧 السيولة: {_smart_liq:.0f}% {_liq_label}\n"
    # 🆕 v6.4.108: Smart Momentum Insight
    try:
        from signals import get_momentum_insight
        _insight = get_momentum_insight(sig.symbol, "1h", 60)
        msg += f"\n💡 {_insight}\n"
    except Exception:
        pass
    msg += "\n━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
    return msg


def format_signal_update(sig: Signal, original_trade: Dict, prev_score: float = 0) -> str:
    """🆕 v6.4.4: رسالة قصيرة للإشارة المكررة — تعرض ما تغيّر + ⭐ تراكمية (حد 3).

    🆕 v6.4.4: نجوم تراكمية — كل مرة تُكتشف فيها الصفقة، تضاف ⭐ حتى تصل لـ 3.
    تُحفظ في `update_stars` (0 → 1 → 2 → 3).

    المحتوى:
      - اسم العملة + 🔄 + ⭐ تراكمية
      - السعر الحالي vs الإشارة الأولى
      - الأهداف الثابتة (1%, 4%, 8%, 12%, 15%) + TP6 لو قوي
      - نسبة النجاح
    """
    sym = sig.symbol
    original_entry = original_trade.get("entry", 0)
    cur_price = sig.entry

    # ما تغيّر عن الصفقة الأصلية
    if original_entry > 0:
        price_change_pct = ((cur_price - original_entry) / original_entry) * 100
    else:
        price_change_pct = 0

    # 🆕 v6.4.4: نجوم تراكمية (من trade الأصلي)
    update_stars = original_trade.get("update_stars", 0)
    new_stars = min(update_stars + 1, 3)  # حد أقصى 3
    sig.update_stars = new_stars  # لِحفظها في trade
    sig.is_update = True

    # النجوم الحالية (نعرضها في الرسالة)
    stars_str = "⭐" * new_stars
    success_rate = sig.score

    msg = f"🔄 <b>{sym}</b> {stars_str}\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"
    # السعر: ما تغيّر
    if abs(price_change_pct) >= 0.5:
        direction = "📈" if price_change_pct > 0 else "📉"
        msg += f"💵 السعر: {fmt_price(cur_price)} {direction} ({price_change_pct:+.2f}%)\n"
        msg += f"  └ من {fmt_price(original_entry)} عند الإشارة الأولى\n\n"
    else:
        msg += f"💵 السعر: {fmt_price(cur_price)} ≈ الإشارة الأولى\n\n"
    # الأهداف المميّزة (5 ثابتة)
    msg += "🎯 <b>الأهداف</b>\n"
    msg += f"  TP1: {fmt_price(sig.tp1)} (+{sig.tp1_pct:.0f}%)\n"
    msg += f"  TP2: {fmt_price(sig.tp2)} (+{sig.tp2_pct:.0f}%)\n"
    msg += f"  TP3: {fmt_price(sig.tp3)} (+{sig.tp3_pct:.0f}%)\n"
    msg += f"  TP4: {fmt_price(sig.tp4)} (+{sig.tp4_pct:.0f}%)\n"
    msg += f"  TP5: {fmt_price(sig.tp5)} (+{sig.tp5_pct:.0f}%)\n"
    # 🆕 v6.4.4: هدف قوي اختياري (TP6)
    if sig.tp6 > 0:
        msg += f"  🎯 TP6: {fmt_price(sig.tp6)} (+{sig.tp6_pct:.0f}%) — <i>هدف قوي ⚡</i>\n"
    msg += "\n"
    # نسبة النجاح
    success_emoji = "🟢" if success_rate >= 70 else ("🟡" if success_rate >= 50 else "🟠")
    msg += f"📊 <b>نسبة النجاح:</b> {success_emoji} {success_rate:.0f}%\n"
    if prev_score > 0:
        delta = success_rate - prev_score
        if abs(delta) >= 5:
            trend_emoji = "📈" if delta > 0 else "📉"
            msg += f"  {trend_emoji} من {prev_score:.0f}% → {success_rate:.0f}%\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
    return msg


def format_signal_simple(sig: Signal) -> str:
    """🆕 v6.4.5: نسخة قصيرة من الإشارة العادية (مش MTF) — بدون مبالغ."""
    quality_emoji = "⭐⭐⭐" if sig.score >= 75 and sig.rr >= 2 else (
                    "⭐⭐" if sig.score >= 60 and sig.rr >= 1.5 else "⭐")

    _tv = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sig.symbol}USDT"
    msg = f"💎 <a href=\"{_tv}\"><b>{sig.symbol}</b></a> {quality_emoji}\n"
    msg += "━━━━━━━━━━━━━━━━\n\n"
    msg += "💰 <b>اشترِ بين</b>\n"
    msg += f"  {fmt_price(sig.entry_low)} - {fmt_price(sig.entry_high)}\n\n"
    msg += f"🛑 <b>وقف خسارة</b>: {fmt_price(sig.sl)} ({sig.sl_pct:+.1f}%)\n\n"
    msg += "🎯 <b>الأهداف</b>\n"
    msg += f"  TP1: {fmt_price(sig.tp1)} (+{sig.tp1_pct:.1f}%) — بِع 50%\n"
    msg += f"  TP2: {fmt_price(sig.tp2)} (+{sig.tp2_pct:.1f}%) — بِع 30%\n"
    msg += f"  TP3: {fmt_price(sig.tp3)} (+{sig.tp3_pct:.1f}%) — بِع 20%\n\n"
    # 🆕 v6.4.5: تمت إزالة 💼 ${position_size_usd}
    msg += f"📊 نسبة النجاح: {sig.score:.0f}%\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
    return msg


def format_signal_mtf(sig: Signal, mtf) -> str:
    """🆕 v6.4: رسالة MTF المفصّلة — Entry Zone + 3 Targets + Position Size + جدول الفريمات."""
    tier_emoji, tier_label = _tier_emoji(sig.score)
    trend_emoji = _trend_emoji(mtf.tf_trends.get("1d", "neutral"))
    btc_trend = sig.btc_trend or get_btc_1d_trend()
    btc_note = ""
    if btc_trend == "هابط":
        btc_note = "⚠️ <b>BTC 1D هابط</b> — السوق ضعيف، حذار\n"
    elif btc_trend == "صاعد":
        btc_note = "✅ <b>BTC 1D صاعد</b> — دعم قوي للصفقة\n"

    # إعداد ممتاز/قوي/مقبول
    if mtf.bullish_count == 4 and sig.rr >= 5.0:
        stars, quality = "⭐⭐⭐", "إعداد ممتاز"
    elif mtf.bullish_count >= 3:
        stars, quality = "⭐⭐", "إعداد قوي"
    else:
        stars, quality = "⭐", "إعداد مقبول"

    # صلاحية
    from datetime import datetime
    valid_until_dt = datetime.fromtimestamp(sig.valid_until)

    # 🆕 v6.4.83: نسبة السيولة الذكية
    try:
        _smart_liq = compute_smart_liquidity_pct(mtf)
        _liq_label = "🟢 احترافي" if _smart_liq >= 50 else ("🟡 جيد" if _smart_liq >= 30 else "⚪ ضعيف")
        _liq_line = f"\n💧 <b>السيولة الذكية:</b> {_smart_liq:.0f}% {_liq_label}"
    except Exception:
        _liq_line = ""

    msg = f"💎 {sig.symbol} {stars} ({quality}) 💎V1\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"{tier_emoji} <b>الثقة:</b> <b>{sig.score:.0f}/100</b> ({tier_label})\n"
    msg += btc_note
    msg += _liq_line
    msg += "\n\n"

    # منطقة الدخول
    msg += "💰 <b>منطقة الدخول (Entry Zone)</b>\n"
    msg += f"  🟢 <b>اشترِ بين:</b> {fmt_price(sig.entry_low)} - {fmt_price(sig.entry_high)}\n"
    msg += f"  💵 <b>السعر الحالي:</b> {fmt_price(sig.entry)}\n\n"

    # وقف الخسارة
    msg += "🛑 <b>وقف الخسارة (Stop Loss)</b>\n"
    msg += f"  📍 <b>SL:</b> {fmt_price(sig.sl)} ({sig.sl_pct:+.2f}%)\n\n"

    # 3 أهداف
    msg += "🎯 <b>الأهداف (Take Profit) — R:R = 1:5</b>\n"
    msg += f"  ✅ <b>TP1</b> (1.5R): {fmt_price(sig.tp1)} (+{sig.tp1_pct:.1f}%) — <b>بِع 50%</b>\n"
    msg += f"  ✅ <b>TP2</b> (3R): {fmt_price(sig.tp2)} (+{sig.tp2_pct:.1f}%) — <b>بِع 30%</b>\n"
    msg += f"  ✅ <b>TP3</b> (5R): {fmt_price(sig.tp3)} (+{sig.tp3_pct:.1f}%) — <b>بِع 20%</b> 🏆\n\n"

    # 🆕 v6.4.5: تمت إزالة إدارة المركز + خسارة محتملة بالدولار

    # صلاحية
    msg += f"⏰ <b>صالحة لـ:</b> {HQ_SIGNAL_EXPIRY_HOURS} ساعة (حتى {valid_until_dt.strftime('%H:%M %d-%m')})\n\n"

    # 🆕 v6.4.8: تمت إزالة جدول الفريمات + قائمة المؤكدات الفنية (حسب طلب المستخدم)
    # فقط نسبة النجاح تبقى

    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية — تداول بمسؤوليتك</i>"
    return msg


def format_signal(sig: Signal) -> str:
    """🆕 v6.4: رسالة مبسّطة للإشارة العادية (مش MTF)."""
    tier_emoji, tier_label = _tier_emoji(sig.score)
    quality_emoji = "⭐⭐⭐" if sig.score >= 75 and sig.rr >= 2.0 else (
                    "⭐⭐" if sig.score >= 60 and sig.rr >= 1.5 else "⭐")
    quality_text = "ممتازة" if quality_emoji == "⭐⭐⭐" else (
                   "جيدة" if quality_emoji == "⭐⭐" else "مقبولة")

    from datetime import datetime
    valid_until_dt = datetime.fromtimestamp(sig.valid_until)

    msg = f"💎 {sig.symbol} {quality_emoji} ({quality_text})\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"{tier_emoji} <b>Score:</b> <b>{sig.score:.0f}/100</b> ({tier_label})\n\n"

    # منطقة الدخول
    msg += "💰 <b>منطقة الدخول</b>\n"
    msg += f"  🟢 <b>اشترِ بين:</b> {fmt_price(sig.entry_low)} - {fmt_price(sig.entry_high)}\n"
    msg += f"  💵 <b>السعر الحالي:</b> {fmt_price(sig.entry)}\n\n"

    # SL
    msg += "🛑 <b>وقف الخسارة</b>\n"
    msg += f"  📍 <b>SL:</b> {fmt_price(sig.sl)} ({sig.sl_pct:+.2f}%)\n\n"

    # 3 أهداف
    msg += "🎯 <b>الأهداف — R:R = 1:5</b>\n"
    msg += f"  ✅ <b>TP1</b> (1.5R): {fmt_price(sig.tp1)} (+{sig.tp1_pct:.1f}%) — بِع 50%\n"
    msg += f"  ✅ <b>TP2</b> (3R): {fmt_price(sig.tp2)} (+{sig.tp2_pct:.1f}%) — بِع 30%\n"
    msg += f"  ✅ <b>TP3</b> (5R): {fmt_price(sig.tp3)} (+{sig.tp3_pct:.1f}%) — بِع 20% 🏆\n\n"

    # صلاحية
    msg += f"⏰ صالحة لـ: {HQ_SIGNAL_EXPIRY_HOURS} ساعة (حتى {valid_until_dt.strftime('%H:%M %d-%m')})\n\n"

    # 🆕 v6.4.8: تمت إزالة قائمة المؤكدات الفنية (حسب طلب المستخدم)

    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
    return msg


# ═══ 🆕 v6.4.5: تنسيق TP alerts — بدون مبالغ + ✅ أمام كل هدف محقق ═══

def _format_targets_with_checkmarks(sig_dict: Dict, achieved_level: str) -> str:
    """🆕 v6.4.5: يعرض الأهداف الخمسة (TP1-TP5) + TP6 (لو موجود) مع ✅ أمام المحقق منها.

    achieved_level: "TP1" / "TP2" / "TP3" / "TP4" / "TP5" / "TP6"
    """
    # ترتيب الأهداف
    levels = ["TP1", "TP2", "TP3", "TP4", "TP5"]
    prices = {f"TP1": sig_dict.get("tp1", 0), f"TP2": sig_dict.get("tp2", 0),
              f"TP3": sig_dict.get("tp3", 0), f"TP4": sig_dict.get("tp4", 0),
              f"TP5": sig_dict.get("tp5", 0)}
    pcts = {"TP1": 1, "TP2": 4, "TP3": 8, "TP4": 12, "TP5": 15}
    # 🆕 v6.4.4: TP6 لو موجود
    if sig_dict.get("tp6", 0) > 0:
        levels.append("TP6")
        prices["TP6"] = sig_dict.get("tp6", 0)
        pcts["TP6"] = sig_dict.get("tp6_pct", 0)

    achieved_idx = levels.index(achieved_level) if achieved_level in levels else -1
    lines = []
    for i, tp in enumerate(levels):
        checkmark = "✅" if i <= achieved_idx else "  "
        price = prices.get(tp, 0)
        pct = pcts.get(tp, 0)
        # 🆕 v6.4.5: TP6 — نضيف "هدف قوي ⚡"
        if tp == "TP6":
            lines.append(f"  {checkmark} <b>{tp}</b>: {fmt_price(price)} (+{pct:.0f}%) — <i>هدف قوي ⚡</i>")
        else:
            lines.append(f"  {checkmark} <b>{tp}</b>: {fmt_price(price)} (+{pct:.0f}%)")
    return "\n".join(lines)


def format_tp1_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP1. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    tp1 = sig_dict.get("tp1", sig_dict.get("tp", 0))
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🎉 <b>TP1 محقق</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += f"🔒 الستوب → نقطة الدخول ({fmt_price(entry)})\n"
    msg += "✅ رأس مالك محمي"
    return msg


def format_tp2_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP2. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    tp1 = sig_dict.get("tp1", 0)
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🎉 <b>TP2 محقق</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += f"🔒 الستوب → TP1 ({fmt_price(tp1)})\n"
    msg += "✅ ربحك مضمون"
    return msg


def format_tp3_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP3. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    tp2 = sig_dict.get("tp2", 0)
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🎉 <b>TP3 محقق</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += f"🔒 الستوب → TP2 ({fmt_price(tp2)})\n"
    msg += "✅ ربحك مضمون"
    return msg


def format_tp4_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP4. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    tp3 = sig_dict.get("tp3", 0)
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🎉 <b>TP4 محقق</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += f"🔒 الستوب → TP3 ({fmt_price(tp3)})\n"
    msg += "✅ ربحك مضمون"
    return msg


def format_tp5_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP5. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    tp4 = sig_dict.get("tp4", 0)
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🏆 <b>TP5 محقق — الإغلاق النهائي!</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += "🎉 أغلقت الصفقة كاملة — وصلت لآخر هدف!"
    return msg


def format_tp6_alert(sig_dict: Dict, cur: float, duration: str) -> str:
    """🆕 v6.4.73: تنبيه TP6. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    entry = sig_dict.get("entry", 0)
    profit_pct = ((cur - entry) / entry * 100) if entry > 0 else 0
    _strat = sig_dict.get("strategy", "v1")
    _strat_label = "🔄 V2" if _strat == "v2" else "💎 V1"

    msg = f"🏆🏆 <b>TP6 محقق — تجاوزت كل الأهداف!</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sig_dict.get('symbol', '?')}</b>\n\n"
    msg += f"💰 السعر: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>+{profit_pct:.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += "🎉 أغلقت الصفقة كاملة!"
    return msg


def format_sl_alert(sym: str, sl: float, cur: float, duration: str, strategy: str = "v1") -> str:
    """🆕 v6.4.9: تنبيه SL. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    _strat_label = "🔄 V2" if strategy == "v2" else "💎 V1"
    msg = f"🛑 <b>ضُرب وقف الخسارة</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"❌ <b>{sym}</b>\n\n"
    msg += f"🛑 سعر الوقف: {fmt_price(sl)}\n"
    msg += f"💰 السعر الحالي: {fmt_price(cur)}\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += "💡 احترم SL دائماً — يحمي رأس مالك"
    return msg


def format_tp_success_close(sym: str, n_targets: int, sl_price: float, cur: float,
                            duration: str, pnl_pct: float, strategy: str = "v1") -> str:
    """🆕 v6.4.82: إغلاق ناجح بعد أهداف. 🆕 v6.4.88: علامة V1/V2. 🆕 v6.4.93: تنسيق مبسط."""
    targets_ar = {
        1: "هدف واحد",
        2: "هدفين",
        3: "3 أهداف",
        4: "4 أهداف",
    }
    achieved_label = targets_ar.get(n_targets, f"{n_targets} أهداف")
    _strat_label = "🔄 V2" if strategy == "v2" else "💎 V1"

    msg = f"✅ <b>صفقة ناجحة بهدف</b> {_strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sym}</b>\n\n"
    msg += f"🎯 نجحت بِـ {achieved_label}\n"
    msg += f"💰 سعر الإغلاق: {fmt_price(cur)}\n"
    msg += f"📈 الربح: <b>{pnl_pct:+.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += "🛡️ الستوب ضُرب بعد تحقيق الأهداف — ليست خسارة"
    return msg


def format_tp_alert(sym: str, entry: float, tp: float, cur: float, duration: str) -> str:
    """للتوافق مع الكود القديم — يستدعي format_tp1_alert."""
    fake_sig = {"entry": entry, "tp1": tp, "tp": tp, "position_size_usd": 100,
                "signal_id": "?", "symbol": sym}
    return format_tp1_alert(fake_sig, cur, duration)


# ═══ 🆕 v6.4.7: تنسيق تنبيه الخروج المبكر الذكي ═══

def format_early_exit_alert(exit_signal, trade_dict: Dict, cur_price: float, profit_pct: float) -> str:
    """🆕 v6.4.72: رسالة خروج مبكر مبسّطة — نصيحة واضحة للمتداول العادي.
    - لو ربح موجب + ضعف → انقل الستوب لنقطة الدخول (حماية رأس المال)
    - لو خسارة + ضعف شديد → اخرج
    - لو ضعف متوسط → راقب فقط
    """
    sym = exit_signal.symbol
    weakness = exit_signal.weakness_score
    entry = trade_dict.get("entry", 0)

    # 🎯 نصيحة حسب الحالة
    if profit_pct > 1.0 and weakness >= 40:
        advice = (
            f"💡 <b>نصيحة:</b> أنت في ربح {profit_pct:+.1f}% لكن المؤشرات ضعيفة\n"
            f"   — انقل الستوب لنقطة الدخول ({fmt_price(entry)}) لحماية رأس مالك\n"
            f"   — أو خذ أرباحك الآن وانتظر فرصة أفضل"
        )
    elif profit_pct > 1.0 and weakness >= 20:
        advice = (
            f"💡 <b>نصيحة:</b> ربحك {profit_pct:+.1f}% والاتجاه يضعف\n"
            f"   — راقب عن قرب وكن جاهزاً للخروج\n"
            f"   — انقل الستوب فوق نقطة الدخول لحماية رأس مالك"
        )
    elif weakness >= 40:
        advice = (
            f"💡 <b>نصيحة:</b> المؤشرات ضعيفة على عدة فريمات\n"
            f"   — فكّر في الخروج لتقليل الخسارة\n"
            f"   — الصبر قد يكلفك أكثر"
        )
    else:
        advice = (
            f"💡 <b>نصيحة:</b> الاتجاه بدأ يضعف قليلاً\n"
            f"   — راقب الصفقة لكن لا داعي للتصرف الآن"
        )

    # 📊 ملخص الفريمات (سطر واحد)
    tf_summary = []
    for tf in ["1d", "4h", "1h", "15m"]:
        tf_data = exit_signal.tf_analysis.get(tf, {})
        score = tf_data.get("score", 0)
        if score >= 20:
            tf_summary.append(f"{tf.upper()} ضعيف ({score})")
    tf_line = " · ".join(tf_summary) if tf_summary else "كل الفريمات مستقرة"

    # 📨 الرسالة
    icon = "👀" if weakness < 40 else "⚠️"
    msg = f"{icon} <b>{sym}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📊 الحالة: {trade_dict.get('status', 'ACTIVE')}\n"
    msg += f"💰 السعر: {fmt_price(cur_price)} · الربح: {'🟢' if profit_pct >= 0 else '🔴'} {profit_pct:+.1f}%\n"
    msg += f"⚡ قوة الضعف: {weakness}/100\n"
    msg += f"📉 الفريمات: {tf_line}\n\n"
    msg += f"{advice}\n"
    msg += "⚠️ <i>ليس نصيحة استثمارية</i>"
    return msg


def format_duration(seconds: int) -> str:
    if seconds < 60: return f"{seconds} ثانية"
    if seconds < 3600:
        m = seconds // 60
        return "دقيقة واحدة" if m == 1 else (f"دقيقتين" if m == 2 else f"{m} دقيقة")
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        hs = "ساعة" if h == 1 else ("ساعتين" if h == 2 else f"{h} ساعات")
        if m > 0:
            ms = "دقيقة" if m == 1 else (f"دقيقتين" if m == 2 else f"{m} دقيقة")
            return f"{hs} و{ms}"
        return hs
    d = seconds // 86400
    return "يوم واحد" if d == 1 else (f"يومين" if d == 2 else f"{d} أيام")


def format_expiry_alert(sig_dict: Dict) -> str:
    """🆕 v6.4: تنبيه انتهاء صلاحية الإشارة (لم يدخل المستخدم)."""
    msg = "⏰ <b>إشارة منتهية الصلاحية</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <a href=\"https://www.tradingview.com/chart/?symbol=BINANCE:{sig_dict.get('symbol', '.')}USDT\"><b>{sig_dict.get('symbol', '?')}</b></a>\n"
    msg += f"⏱️ مرت {HQ_SIGNAL_EXPIRY_HOURS} ساعة دون تأكيد دخول\n\n"
    msg += f"💰 السعر وقت الإشارة: {fmt_price(sig_dict.get('entry', 0))}\n"
    msg += "💡 <b>السبب:</b> لم يصل السعر لمنطقة الدخول أو تجاوزها\n"
    msg += "━━━━━━━━━━━━━━━━━━"
    return msg


def format_coin_history(symbol: str, all_trades: List[Dict]) -> str:
    """🆕 v6.4.3: عرض كل صفقات عملة واحدة — نشطة + مغلقة + تاريخ."""
    if not all_trades:
        return f"📭 <b>{symbol}</b> — لا توجد صفقات سابقة."

    from datetime import datetime
    active = [t for t in all_trades if t.get("status") in {"ACTIVE", "TP1_HIT", "TP2_HIT"}]
    closed = [t for t in all_trades if t.get("status") not in {"ACTIVE", "TP1_HIT", "TP2_HIT"}]

    status_emoji = {
        "ACTIVE": "🟢", "TP1_HIT": "✅", "TP2_HIT": "✅✅",
        "TP3_HIT": "🏆", "STOP_LOSS": "🛑", "EXPIRED": "⏰",
        "CANCELLED": "❌", "CLOSED": "•",
    }

    msg = f"📊 <b>كل صفقات {symbol}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📈 إجمالي: {len(all_trades)} | 🟢 نشطة: {len(active)} | 🔒 مغلقة: {len(closed)}\n\n"

    # الصفقات النشطة أولاً (أهم)
    if active:
        msg += "<b>🟢 الصفقات النشطة:</b>\n"
        msg += "─────────────────────\n"
        for t in active[:5]:
            status = t.get("status", "?")
            emoji = status_emoji.get(status, "•")
            entry = t.get("entry", 0)
            tp1 = t.get("tp1", 0)
            tp2 = t.get("tp2", 0)
            tp3 = t.get("tp3", 0)
            sl = t.get("sl", 0)
            score = t.get("score", 0)
            dt = datetime.fromtimestamp(t.get("created_at", 0)).strftime("%m-%d %H:%M")
            msg += f"{emoji} <b>{symbol}</b> [{status}]\n"
            msg += f"  💰 دخول: {fmt_price(entry)}\n"
            msg += f"  🎯 TP1: {fmt_price(tp1)} | TP2: {fmt_price(tp2)} | TP3: {fmt_price(tp3)}\n"
            msg += f"  🛑 SL: {fmt_price(sl)} | 📊 {score:.0f}%\n"
            msg += f"  🕐 {dt}\n\n"

    # آخر 5 صفقات مغلقة
    if closed:
        msg += "<b>🔒 آخر الصفقات المغلقة:</b>\n"
        msg += "─────────────────────\n"
        for t in closed[:5]:
            status = t.get("status", "?")
            emoji = status_emoji.get(status, "•")
            entry = t.get("entry", 0)
            closing = t.get("closing_price", 0)
            pnl = t.get("pnl", 0)
            pnl_emoji = "📈" if pnl > 0 else "📉"
            dt = datetime.fromtimestamp(t.get("created_at", 0)).strftime("%m-%d %H:%M")
            msg += f"{emoji} <b>{symbol}</b> [{status}] {pnl_emoji} {pnl:+.2f}%\n"
            msg += f"  دخول: {fmt_price(entry)} | خروج: {fmt_price(closing)}\n"
            msg += f"  🕐 {dt}\n"

    if len(all_trades) > 10:
        msg += f"\n... و {len(all_trades) - 10} صفقة قديمة"

    return msg


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.83: أزرار Inline لروابط Binance + TradingView
# ═══════════════════════════════════════════════════════════

def build_coin_links_kb(symbol: str):
    """🆕 v6.4.83: يبني لوحة أزرار inline تحت رسالة الصفقة.

    الأزرار:
      - 🟠 Binance (الأولوية الأولى — لتسريع الدخول للشراء/البيع)
      - 📈 TradingView (للتحليل والرسم البياني)

    الرابط المستخدم:
      - Binance: https://www.binance.com/en/trade/{SYMBOL}_USDT  (لو الحرف الأول من symbol حرف)
      - Binance (fallback): https://trade.binance.com/en/trade/{SYMBOL}_USDT
      - TradingView: https://www.tradingview.com/chart/?symbol=BINANCE:{SYMBOL}USDT

    يرجع dict بـ inline_keyboard (متوافق مع _tg_post في bot.py).
    """
    sym = (symbol or "").upper()
    if not sym:
        return None
    # رابط Binance المباشر للـ spot trading
    binance_url = f"https://www.binance.com/en/trade/{sym}_USDT"
    # رابط TradingView
    tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}USDT"
    return {
        "inline_keyboard": [[
            {"text": "🟠 Binance", "url": binance_url, "callback_data": "ignore"},
            {"text": "📈 TradingView", "url": tv_url, "callback_data": "ignore"},
        ]]
    }


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.83: تنبيه الخروج عند القمة (Peak Exit Alert)
# ═══════════════════════════════════════════════════════════

def format_peak_exit_alert(sym: str, entry: float, peak_price: float, cur: float,
                            pullback_pct: float, profit_from_entry: float, duration: str,
                            strategy: str = "v1") -> str:
    """🆕 v6.4.83: تنبيه الخروج عند القمة. 🆕 v6.4.93: تنسيق مبسط."""
    strat_icon = "💎" if strategy == "v1" else "🔄"
    strat_label = "V1" if strategy == "v1" else "V2"

    msg = f"🚨 <b>تنبيه القمة</b> {strat_icon}{strat_label}\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"🪙 <b>{sym}</b>\n\n"
    msg += f"⛰️ القمة: {fmt_price(peak_price)}\n"
    msg += f"📉 تراجع: <b>{pullback_pct:+.2f}%</b>\n"
    msg += f"💰 السعر الحالي: {fmt_price(cur)}\n"
    msg += f"📈 الربح من الدخول: <b>{profit_from_entry:+.2f}%</b>\n"
    msg += f"⏱️ المدة: {duration}\n\n"
    msg += "🟢 فكر بالخروج الآن لحفظ الربح"
    return msg


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.83: السجل الأسبوعي — إحصائيات الصفقات لآخر N يوم
# ═══════════════════════════════════════════════════════════

def format_weekly_logs(cid: str, days: int = 7) -> str:
    """🆕 v6.4.83: السجل الأسبوعي — يجمع كل الصفقات لآخر N يوم ويعرض:

      - إجمالي الصفقات
      - ناجحة (تحقق أهداف) vs خاسرة (ضرب ستوب قبل أي هدف)
      - أهداف محققة (TP1..TP5) — عد كل واحد
      - ستوبات ضُربت قبل أي هدف (خسارة فعلية)
      - ستوبات ضُربت بعد أهداف (نجاح بهدف أو هدفين)
      - Win Rate، Avg PnL
      - تفصيل V1 / V2
    """
    try:
        import tracker as _tk
        from datetime import datetime
        conn = _tk._get_db()
        c = conn.cursor()
        cutoff = int((datetime.now().timestamp())) - days * 86400
        # كل الصفقات المغلقة بعد cutoff + كل الصفقات النشطة
        c.execute("SELECT * FROM trades WHERE cid=? AND (closed_at >= ? OR status IN (?, ?, ?, ?, ?)) ORDER BY created_at DESC",
                  (str(cid), cutoff, "ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT"))
        rows = [_tk._row_to_dict(r) for r in c.fetchall()]
        # إحصائيات تراكمية
        c.execute("SELECT key, value FROM stats")
        stats_rows = c.fetchall()
        cumulative = {row["key"]: row["value"] for row in stats_rows}
        conn.close()

        if not rows:
            return f"📋 <b>السجل الأسبوعي ({days} أيام)</b>\n━━━━━━━━━━━━━━━━━━\n\n📭 لا توجد صفقات في هذه الفترة."

        # فصل V1 و V2
        v1_trades = [t for t in rows if t.get("strategy", "v1") == "v1"]
        v2_trades = [t for t in rows if t.get("strategy", "v1") == "v2"]

        # ناجح = حالة تبدأ بـ TP (TP{n}_DONE, TP5_HIT, TP6_HIT)
        # خاسر = STOP_LOSS فقط
        # مغلق = EXPIRED, CANCELLED, CLOSED
        def _classify(t):
            st = t.get("status", "ACTIVE")
            if st.startswith("TP") and "DONE" in st:
                return "win_partial"  # نجاح بهدف/هدفين (الستوب الديناميكي ضُرب بعد أهداف)
            if st in ("TP5_HIT", "TP6_HIT"):
                return "win_full"  # كل الأهداف تحققت
            if st in ("TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "ACTIVE"):
                return "active"
            if st == "STOP_LOSS":
                return "loss"
            if st == "EXPIRED":
                return "expired"
            if st == "CANCELLED":
                return "cancelled"
            return "other"

        categories = {"win_full": 0, "win_partial": 0, "loss": 0, "expired": 0, "cancelled": 0, "active": 0, "other": 0}
        for t in rows:
            categories[_classify(t)] += 1

        # عد الأهداف المحققة (التراكمية من جدول stats)
        tp_counts = {k: cumulative.get(k, 0) for k in
                     ["tp1_count", "tp2_count", "tp3_count", "tp4_count", "tp5_count", "tp6_count"]}
        # الستوبات (الخسارات قبل أي هدف)
        sl_pure_count = cumulative.get("sl_count", 0)
        # الستوبات الرابحة (ضُربت بعد أهداف)
        sl_after_tp_counts = {k: cumulative.get(k, 0) for k in
                              ["sl_after_tp1_count", "sl_after_tp2_count", "sl_after_tp3_count", "sl_after_tp4_count"]}
        sl_after_tp_total = sum(sl_after_tp_counts.values())

        total = len(rows)
        wins = categories["win_full"] + categories["win_partial"]
        losses = categories["loss"]
        wr = (wins / max(wins + losses, 1)) * 100

        # PnL
        closed_pnl_sum = sum(t.get("pnl", 0) for t in rows if t.get("status") not in ("ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT") and t.get("pnl"))
        avg_pnl = closed_pnl_sum / max(wins + losses + categories["expired"] + categories["cancelled"], 1)

        msg = f"📋 <b>السجل الأسبوعي ({days} أيام)</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 <b>إجمالي الصفقات:</b> {total}\n"
        msg += f"   • 💎 V1 (MTF): {len(v1_trades)}\n"
        msg += f"   • 🔄 V2 (Reversal): {len(v2_trades)}\n\n"

        msg += f"<b>📈 النتائج:</b>\n"
        msg += f"   • ✅ ناجحة: <b>{wins}</b>\n"
        msg += f"   • ❌ خاسرة (ستوب قبل أي هدف): <b>{losses}</b>\n"
        wr_emoji = "🟢" if wr >= 60 else ("🟡" if wr >= 40 else "🔴")
        msg += f"   • 📊 Win Rate: {wr_emoji} <b>{wr:.1f}%</b>\n"
        msg += f"   • 💰 Avg PnL: <b>{avg_pnl:+.2f}%</b>\n\n"

        msg += f"<b>🎯 الأهداف المحققة (تراكمي):</b>\n"
        for k, v in tp_counts.items():
            if v > 0:
                num = k.replace("tp", "").replace("_count", "")
                msg += f"   • {num} محققة: <b>{v}</b>\n"

        msg += f"\n<b>🏆 نجاحات الستوب الديناميكي (ضُرب بعد أهداف):</b>\n"
        if sl_after_tp_total > 0:
            for k, v in sl_after_tp_counts.items():
                if v > 0:
                    num = k.replace("sl_after_tp", "").replace("_count", "")
                    label = {"1": "🎯 بهدف واحد", "2": "🎯🎯 بهدفين", "3": "🎯🎯🎯 بثلاثة أهداف", "4": "🏆 بأربعة أهداف"}.get(num, num)
                    msg += f"   • {label}: <b>{v}</b>\n"
        else:
            msg += "   • (لا يوجد — كل الصفقات إما كل الأهداف أو ستوب مبكر)\n"

        msg += f"\n<b>🛑 الستوبات الخاسرة (قبل أي هدف):</b> <b>{sl_pure_count}</b>\n"
        msg += f"<b>⏰ انتهت صلاحية:</b> {categories['expired']}\n"
        msg += f"<b>🟢 نشطة حالياً:</b> {categories['active']}\n\n"
        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += "💡 راجع الاستراتيجية الأكثر ربحاً وابحث عن نقاط ضعف الأخرى"
        return msg
    except Exception as e:
        log.error(f"format_weekly_logs err: {e}")
        return f"❌ خطأ في السجل الأسبوعي: {e}"


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.83: نسبة السيولة الذكية (Smart Liquidity %)
# ═══════════════════════════════════════════════════════════

def compute_smart_liquidity_pct(mtf) -> float:
    """🆕 v6.4.83: يحسب نسبة السيولة الذكية الداخلة احترافياً.

    المنطق:
      - لكل فريم (4h, 1h, 15m, 5m) افحص confirmed لِـ:
        * "Liquidity sweep" → +25 (لكل فريم)
        * "OB/FVG present" → +20 (لكل فريم)
        * "BOS/CHOCH bullish" → +15 (لكل فريم)
        * "RSI oversold/divergence" → +10 (لكل فريم)
      - المجموع موزون بـ MTF_WEIGHTS (4h أهم من 5m)
      - يرجع نسبة 0-100

    هذه النسبة تعكس: "كم نسبة المؤشرات الذكية للسيولة متوفرة في هذه الصفقة؟"
    كلما زادت النسبة → دخول احترافي على سيولة ذكية (Smart Money).

    يقبل mtf كـ MTFAnalysis من engine.py أو dict بمفاتيح: confirmed, tf_scores.
    """
    try:
        # لو MTFAnalysis (dataclass)
        confirmed = getattr(mtf, "confirmed", None) or []
        tf_scores = getattr(mtf, "tf_scores", None) or {}
        if not confirmed and isinstance(mtf, dict):
            confirmed = mtf.get("confirmed", [])
            tf_scores = mtf.get("tf_scores", {})

        # وزن لكل فريم (مثل MTF_WEIGHTS)
        weights = {"4h": 0.35, "1h": 0.30, "15m": 0.20, "5m": 0.15}

        # نقاط لكل فريم
        per_tf_score = {tf: 0 for tf in weights}
        for c in confirmed:
            # c بصيغة "4h: Liquidity sweep" أو "1h: OB/FVG present"
            if not isinstance(c, str):
                continue
            if ":" in c:
                prefix, rest = c.split(":", 1)
                tf = prefix.strip().lower()
                rest = rest.strip()
            else:
                tf = "4h"  # افتراض أعلى فريم لو بدون prefix
                rest = c
            if tf not in per_tf_score:
                continue
            # احسب النقاط
            if "Liquidity" in rest:
                per_tf_score[tf] += 25
            if "OB" in rest or "FVG" in rest:
                per_tf_score[tf] += 20
            if "BOS" in rest or "CHOCH" in rest:
                per_tf_score[tf] += 15
            if "RSI" in rest:
                per_tf_score[tf] += 10

        # موزون
        weighted = sum(per_tf_score[tf] * weights[tf] for tf in weights)
        # cap at 100
        return min(100.0, round(weighted, 0))
    except Exception as e:
        log.warning(f"compute_smart_liquidity_pct err: {e}")
        return 0.0


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.108: Smart Momentum Insight — ملاحظة قصيرة عن الزخم
# ═══════════════════════════════════════════════════════════

def _calc_momentum_insight(candles: List[Dict], symbol: str = "") -> str:
    """🆕 v6.4.108: ينتج ملاحظة قصيرة (5-12 كلمة) عن حالة الزخم.

    يحلل: السعر + الحجم + RSI + MACD + EMA + ATR
    يميز: ضعف حقيقي / انقباض مؤقت / ضغط صاعد ناشئ
    لا يستخدم: RSI < 50 = bearish، volume down = sell، MACD down = sell

    يرجع: جملة قصيرة بالعربية
    """
    try:
        if not candles or len(candles) < 30:
            return "الزخم غير واضح؛ بانتظار التأكيد."

        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        # 1) PRICE ACTION
        last_5_closes = closes[-5:]
        higher_highs = all(last_5_closes[i] >= last_5_closes[i-1] for i in range(1, min(4, len(last_5_closes))))
        lower_lows = all(last_5_closes[i] <= last_5_closes[i-1] for i in range(1, min(4, len(last_5_closes))))
        last_candle = candles[-1]
        body_size = abs(last_candle["close"] - last_candle["open"])
        range_size = last_candle["high"] - last_candle["low"]
        close_position = (last_candle["close"] - last_candle["low"]) / range_size if range_size > 0 else 0.5

        # 2) VOLUME
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
        current_vol = volumes[-1]
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        vol_expanding = vol_ratio > 1.3

        # 3) RSI
        rsi = _calc_simple_rsi(closes, 14)
        rsi_prev = _calc_simple_rsi(closes[:-1], 14) if len(closes) > 15 else rsi
        rsi_rising = rsi > rsi_prev

        # 4) EMA
        ema20 = _calc_simple_ema(closes, 20)
        ema50 = _calc_simple_ema(closes, 50) if len(closes) >= 50 else ema20
        price_above_ema = closes[-1] > ema20
        ema20_above_ema50 = ema20 > ema50

        # 5) ATR (volatility)
        atr = _calc_simple_atr(candles, 14)
        avg_atr = _calc_simple_atr(candles[-30:], 14) if len(candles) >= 30 else atr
        atr_contracting = atr < avg_atr * 0.8 if avg_atr > 0 else False
        atr_expanding = atr > avg_atr * 1.2 if avg_atr > 0 else False

        # ═══ تحليل الأدلة ═══
        bullish_evidence = 0
        bearish_evidence = 0
        neutral_evidence = 0

        # Price structure
        if higher_highs:
            bullish_evidence += 2
        if lower_lows:
            bearish_evidence += 2
        if close_position > 0.7:
            bullish_evidence += 1
        elif close_position < 0.3:
            bearish_evidence += 1

        # Volume
        if vol_expanding and last_candle["close"] > last_candle["open"]:
            bullish_evidence += 2  # Volume + bullish candle
        elif vol_expanding and last_candle["close"] < last_candle["open"]:
            bearish_evidence += 2  # Volume + bearish candle
        elif vol_ratio < 0.7:
            neutral_evidence += 1  # Volume fading

        # RSI
        if rsi_rising and rsi > 50:
            bullish_evidence += 1
        elif not rsi_rising and rsi < 40:
            bearish_evidence += 1
        # لا نعتبر RSI < 50 = bearish وحده

        # EMA
        if price_above_ema and ema20_above_ema50:
            bullish_evidence += 1
        elif not price_above_ema and not ema20_above_ema50:
            bearish_evidence += 1

        # Volatility
        if atr_contracting:
            neutral_evidence += 2  # انقباض = انتظار
        if atr_expanding and last_candle["close"] > last_candle["open"]:
            bullish_evidence += 1

        # ═══ توليد الملاحظة ═══
        if bullish_evidence >= 4 and bearish_evidence <= 1:
            if atr_contracting:
                return "الزخم يهدأ؛ الضغط الشرائي يتحسن."
            elif vol_expanding:
                return "الزخم يشتد؛ المشترون يسيطرون."
            else:
                return "الزخم يتعزز؛ بنية صاعدة سليمة."
        elif bearish_evidence >= 4 and bullish_evidence <= 1:
            if vol_expanding:
                return "ضغط بيع يشتد؛ الدعم يضعف."
            else:
                return "الزخم يضعف؛ ضغط البيع يتصاعد."
        elif bullish_evidence >= 2 and bearish_evidence >= 2:
            return "إشارات متضاربة؛ الاتجاه غير مؤكد."
        elif neutral_evidence >= 3 and atr_contracting:
            if close_position > 0.6:
                return "انضغاط قرب المقاومة؛ الاختراق غير مؤكد."
            else:
                return "الزخم يبرد؛ البنية قصيرة المدى سليمة."
        elif neutral_evidence >= 2 and vol_ratio < 0.7:
            return "الحجم يتراجع؛ الاستمرار الصاعد يفقد التأكيد."
        else:
            return "الزخم غير واضح؛ بانتظار التأكيد."
    except Exception as e:
        log.warning(f"_calc_momentum_insight err: {e}")
        return "الزخم غير واضح؛ بانتظار التأكيد."


def _calc_simple_rsi(closes: List[float], period: int = 14) -> float:
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


def _calc_simple_ema(closes: List[float], period: int) -> float:
    if not closes or len(closes) < period:
        return 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def _calc_simple_atr(candles: List[Dict], period: int = 14) -> float:
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


def get_momentum_insight(symbol: str, timeframe: str = "1h", limit: int = 60) -> str:
    """🆕 v6.4.108: يحضر الشموع ويحسب Momentum Insight لِـ عملة."""
    try:
        from engine import fetch_klines
        candles = fetch_klines(symbol, timeframe, limit)
        if not candles or len(candles) < 30:
            return "الزخم غير واضح؛ بانتظار التأكيد."
        return _calc_momentum_insight(candles, symbol)
    except Exception:
        return "الزخم غير واضح؛ بانتظار التأكيد."
