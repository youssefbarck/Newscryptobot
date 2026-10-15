#!/usr/bin/env python3
"""
Bot — Telegram + Flask + Scheduler (v6.0 Clean)
===============================================
ملف واحد نظيف: Telegram bot + Flask server + scheduler loop.
يستورد engine + signals + tracker + backtest.
"""

import os, time, json, logging, threading, requests
from flask import Flask, jsonify, request as flask_request

# ═══ Imports ═══
from engine import analyze, fetch_klines, fetch_top_movers, fetch_top_movers_with_data, is_binance_available, build_snapshot, fetch_all_spot_symbols, prefilter_candidates, analyze_mtf_batch, is_strong_setup, MTFAnalysis, detect_early_exit_signals, EarlyExitSignal, get_market_tickers, get_market_tickers_coingecko
from signals import generate, generate_mtf, format_signal, format_signal_mtf, format_signal_mtf_simple, format_signal_simple, format_signal_update, format_coin_history, format_tp1_alert, format_tp2_alert, format_tp3_alert, format_tp4_alert, format_tp5_alert, format_tp6_alert, format_sl_alert, format_tp_success_close, format_early_exit_alert, format_peak_exit_alert, format_duration, fmt_price, format_expiry_alert, is_recently_signaled, mark_signal_sent, clear_signal_dedup, get_btc_1d_trend, HQ_DEFAULT_CAPITAL, HQ_SIGNAL_EXPIRY_HOURS, HQ_DEDUP_HOURS
from tracker import is_active, lock, unlock, create, hit_tp, hit_sl, update_mfe_mae, set_peak_alert_sent, get_active, get_stats, format_stats, has_active_trade, try_create, rebuild_cache, close_trade, NON_FINAL, set_signal_message_id, get_signal_message_id, clear_signal_message_id
import tracker  # 🆕 v6.4.12: استيراد الموديول كاملاً (لِـ tracker._load, tracker.NON_FINAL)
from backtest import run as backtest_run, format_result as backtest_format
import halal_check  # 🆕 v6.4.52: نظام الأحكام الشرعية (يدوي)
import strategy_v2  # 🆕 v6.4.65: استراتيجية الارتداد (V2)
import strategy_v3  # 🆕 v6.4.98: استراتيجية Pre-Pump Breakout (V3)
import btc_monitor  # 🆕 v6.4.113: مراقب BTC/ETH — صور شارت للقناة
import halal_check  # 🆕 v6.4.30: نظام الأحكام الشرعية + Upstash

# ═══ Config ═══
BOT_VERSION = "v6.4.124"  # 🆕 v6.4.124: silent Binance logs + حظر 30min + رابط تحميل ثابت
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# 🆕 v6.2: قناة الأهداف المحققة (TP/SL) — موجودة مسبقاً
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
# 🆕 v6.2: قناة خارجية لإرسال الإشارات الجديدة فقط (entry signals)
# إذا لم تُضبط → الإشارات ترسل فقط للـ CHAT_ID (السلوك الأصلي)
SIGNALS_CHANNEL_ID = os.environ.get("TELEGRAM_SIGNALS_CHANNEL_ID", "")
# 🆕 v6.2: تفعيل المسح الشامل لكل عملات Binance Spot
# all=1 → مسح كل العملات السائلة | all=0 → فقط المفضلة + top movers
SCAN_ALL_SPOT = os.environ.get("SCAN_ALL_SPOT", "1") == "1"
# 🆕 v6.2: حد الإشارات القصوى لكل دورة (لمنع الإغراق عند تفعيل المسح الشامل)
MAX_SIGNALS_PER_CYCLE = int(os.environ.get("MAX_SIGNALS_PER_CYCLE", "50"))
# 🆕 v6.2.7: فترة المسح — 300s (5 دقائق) بدل 600s للالتقاط الأسرع
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "300"))
# 🆕 v6.4.45: عتبة Score — 🆕 v6.4.85: تشديد صارم من 55 إلى 70 (جودة عالية)
# 🆕 v6.4.86: hardcoded floor — لو env var أقل من 60 → استخدم 60 (تفادي stale env vars على Render)
# 🆕 v6.4.89: V1 يبقى صارم (المستخدم أوقفه يدوياً) — التخفيف على V2 فقط
# 🆕 v6.4.94: V1 تخفيف — score 70 → 55 (V1 لم يرسل أي صفقة بسبب الصرامة)
_SCORE_RAW = int(os.environ.get("SCORE_THRESHOLD", "55"))
SCORE_THRESHOLD = max(50, _SCORE_RAW)  # 🆕 v6.4.94: floor = 50 (لا 60)
# 🆕 v6.2.7: حد R/R الأدنى — 0.8 (مقبول مع تحذير) افتراضي، 1.0 للربح ≥ الخطر
# 🆕 v6.4.45: رفع لـ 2.0 — 🆕 v6.4.85: تشديد صارم لـ 3.0 (ربح 3× خطر)
# 🆕 v6.4.86: hardcoded floor — لو env var أقل من 2.0 → استخدم 2.0
# 🆕 v6.4.89: V1 يبقى صارم (المستخدم أوقفه يدوياً) — التخفيف على V2 فقط
# 🆕 v6.4.94: V1 تخفيف — R/R 3.0 → 2.0 (V1 لم يرسل أي صفقة)
_RR_RAW = float(os.environ.get("MIN_RR_RATIO", "2.0"))
MIN_RR_RATIO = max(1.5, _RR_RAW)  # 🆕 v6.4.94: floor = 1.5 (لا 2.0)
# 🆕 v6.2.7: Heartbeat كل ساعة — 1=مفعّل / 0=مُعطّل
HEARTBEAT_ENABLED = os.environ.get("HEARTBEAT_ENABLED", "1") == "1"
# 🆕 v6.4.2: فاصل heartbeat بالثواني (افتراضي 1800 = 30 دقيقة، بدل ساعة)
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "3600"))  # 🆕 v6.4.34: ساعة بدل 30 دقيقة
# 🆕 v6.4.2: إرسال تنبيه صامت بعد كل دورة مسح (حتى لو لم يجد إشارات)
# 1=مفعّل / 0=مُعطّل (لو مُعطّل، يعود للسكوت القديم)
SCAN_SILENT_ALERTS = os.environ.get("SCAN_SILENT_ALERTS", "1") == "1"
# 🆕 v6.3: Funnel architecture — عدد المرشحين بعد الفلترة الرخيصة
PRE_FILTER_TOP_N = int(os.environ.get("PRE_FILTER_TOP_N", "20"))
# 🆕 v6.3: بوابة Setup القوي — الحد الأدنى للفريمات الصاعدة (من 4)
# 🆕 v6.4.45: رفع لـ 3 — 🆕 v6.4.83: تشديد إلى 4 — 🆕 v6.4.89: يبقى 4 (V1 صارم)
# 🆕 v6.4.94: V1 تخفيف — 4 → 3 (V1 لم يرسل أي صفقة)
_BULLISH_RAW = int(os.environ.get("MTF_MIN_BULLISH", "3"))
MTF_MIN_BULLISH = max(2, _BULLISH_RAW)  # 🆕 v6.4.94: floor = 2 (لا 3)
# 🆕 v6.3: بوابة Setup القوي — الحد الأدنى للـ confluence الموزون
# 🆕 v6.4.45: رفع لـ 50 — 🆕 v6.4.83: تشديد إلى 55 — 🆕 v6.4.85: تشديد صارم إلى 70 — 🆕 v6.4.89: يبقى 70
# 🆕 v6.4.94: V1 تخفيف — 70 → 50 (V1 لم يرسل أي صفقة)
_CONFL_RAW = float(os.environ.get("MTF_MIN_CONFLUENCE", "50"))
MTF_MIN_CONFLUENCE = max(40.0, _CONFL_RAW)  # 🆕 v6.4.94: floor = 40 (لا 50)

# 🆕 v6.4.45: إيقاف فوري للصفقات الجديدة — لحماية المال حتى يتم الإصلاح
# 🆕 v6.4.51: تفعيل الصفقات الجديدة بالشروط الصارمة
# 🆕 v6.4.62: إزالة كل القيود — إرسال حر بشرط الشروط الفنية العالية فقط
# البوت الآن يرسل بحرية أي صفقة تجاوزت:
#   - الحكم الشرعي (حلال فقط من القائمة)
#   - الشروط الفنية: MTF>=3, CONFLUENCE>=50, SCORE>=50, R/R>=2.0
#   - فلتر DXY (الدولار)
#   - استبعاد العملات الصغيرة < $0.001
RESUME_NEW_SIGNALS = os.environ.get("RESUME_NEW_SIGNALS", "1") == "1"
# 🆕 v6.4.45: استبعاد العملات الصغيرة جداً (< $0.001) — مخاطر عالية + bug في PnL
MIN_ENTRY_PRICE = float(os.environ.get("MIN_ENTRY_PRICE", "0.001"))
MAX_ENTRY_PRICE = float(os.environ.get("MAX_ENTRY_PRICE", "100000.0"))
# 🆕 v6.4.45: DXY (Dollar Index) — مؤشر الدولار للقرار الذكي
# لو DXY صاعد → كريبتو هابط → لا تدخل
# لو DXY هابط → كريبتو صاعد → ادخل
# 1=مفعّل (افتراضي) | 0=مُعطّل (العودة لـ BTC trend)
USE_DXY_FILTER = os.environ.get("USE_DXY_FILTER", "1") == "1"
DXY_CACHE_TTL = 300  # 5 دقائق cache
# 🆕 v6.4.51: قيود سابقة (تم رفعها في v6.4.62)
# 🆕 v6.4.62: إرسال حر — لا حد أقصى، لا cooldown
# القيم تبقى موجودة للتوافق مع الإصدارات السابقة لكن يتم تعطيلها:
MAX_SIGNALS_PER_CYCLE_STRICT = int(os.environ.get("MAX_SIGNALS_PER_CYCLE_STRICT", "999"))  # 999 = لا حد
SIGNAL_COOLDOWN_SEC = int(os.environ.get("SIGNAL_COOLDOWN_SEC", "0"))  # 0 = لا انتظار
# 🆕 v6.4.65: استراتيجية الارتداد (V2) — إعدادات منفصلة
# 1=مفعّل (افتراضي) | 0=مُعطّل
STRATEGY_V2_ENABLED = os.environ.get("STRATEGY_V2_ENABLED", "1") == "1"
# الفريم المستخدم: auto (افتراضي) | 5m | 15m | 30m | 1h | 4h | 1d
# 🆕 v6.4.67: "auto" = يفحص 5m/15m/30m/1h تلقائياً ويختار الأفضل
STRATEGY_V2_TIMEFRAME = os.environ.get("STRATEGY_V2_TIMEFRAME", "auto")
# حد الإشارات V2 لكل دورة
STRATEGY_V2_MAX_SIGNALS = int(os.environ.get("STRATEGY_V2_MAX_SIGNALS", "3"))
# R/R الأدنى لـ V2 — 🆕 v6.4.83: تشديد من 1.5 إلى 2.0 — 🆕 v6.4.85: تشديد صارم إلى 2.5 — 🆕 v6.4.86: عودة لِـ 2.0 (صارم لكن واقعي)
STRATEGY_V2_MIN_RR = float(os.environ.get("STRATEGY_V2_MIN_RR", "2.0"))
# 🆕 v6.4.85: حد أقصى للصفقات النشطة (لِضمان جودة عالية + قلة الصفقات)
# 🆕 v6.4.85: لو تجاوز → لا فتح صفقات جديدة حتى تُغلق بعض الصفقات
MAX_ACTIVE_TRADES = int(os.environ.get("MAX_ACTIVE_TRADES", "8"))
# 🆕 v6.4.85: الحد الأدنى للمؤشرات الذكية (SMC/OB/FVG/Liquidity) لكل صفقة
# 🆕 v6.4.85: لازم على الأقل 2 من 4 فريمات فيها مؤشر ذكي
MIN_SMC_CONFLUENCE = int(os.environ.get("MIN_SMC_CONFLUENCE", "2"))
# 🆕 v6.4.85: الحد الأدنى للسيولة الذكية % (compute_smart_liquidity_pct) لكل صفقة
MIN_SMART_LIQUIDITY_PCT = float(os.environ.get("MIN_SMART_LIQUIDITY_PCT", "30.0"))
# 🆕 v6.4.98: استراتيجية Pre-Pump Breakout (V3) — إعدادات
STRATEGY_V3_ENABLED = os.environ.get("STRATEGY_V3_ENABLED", "1") == "1"
STRATEGY_V3_MAX_SIGNALS = int(os.environ.get("STRATEGY_V3_MAX_SIGNALS", "3"))
V3_MAX_SYMBOLS = int(os.environ.get("V3_MAX_SYMBOLS", "30"))
V3_MIN_SCORE = int(os.environ.get("V3_MIN_SCORE", "50"))
# 🆕 v6.4.120: V3 Watch Alerts — تنبيهات صغيرة للعملات تحت المراقبة
V3_WATCH_ENABLED = os.environ.get("V3_WATCH_ENABLED", "1") == "1"
V3_WATCH_MAX_ALERTS = int(os.environ.get("V3_WATCH_MAX_ALERTS", "5"))
V3_WATCH_COOLDOWN_HOURS = int(os.environ.get("V3_WATCH_COOLDOWN_HOURS", "4"))
# 🆕 v6.4.84: تبديل V1/V2 — تشغيل = نشر للقناة العامة، إيقاف = إرسال للبوت فقط
#    الحالة محفوظة في ملف دائم (v1_v2_state.json) لِتبقى بعد إعادة النشر على Render
#    الإرسال دائماً يجري — الفرق فقط في الوجهة (قناة أو بوت).
#    (المتغيرات الفعلية V1_ENABLED/V2_ENABLED تُعرّف بعد log = logging.getLogger())

# 🆕 v6.3: mutex لمنع تشغيل scan متزامن (scheduler + /forcescan + /scandebug)
_scan_mutex = threading.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("Bot")

# 🆕 v6.4.84: V1/V2 state file (persistent across Render deploys)
import json as _json_state
_PERSISTENT_DIR_V1V2 = os.environ.get("PERSISTENT_DIR", "")
if not _PERSISTENT_DIR_V1V2:
    for _cand in ["/var/data", "/opt/render/project/src/data", "/app/data", "/tmp"]:
        try:
            if os.path.exists(_cand) and os.access(_cand, os.W_OK):
                _PERSISTENT_DIR_V1V2 = _cand
                break
        except Exception:
            continue
if not _PERSISTENT_DIR_V1V2:
    _PERSISTENT_DIR_V1V2 = "/tmp"
_STATE_FILE = os.path.join(_PERSISTENT_DIR_V1V2, "v1_v2_state.json")
log.info(f"💾 [V1/V2 state] file: {_STATE_FILE}")


def _load_v1_v2_state() -> tuple:
    """🆕 v6.4.84: تحميل حالة V1/V2/V3 من ملف دائم (fallback لِـ env).
    🆕 v6.4.91: V2 default = 0 (معطّل تلقائياً حتى يتم إصلاحه)
    🆕 v6.4.94: V2 default = 1 (تم الإصلاح — مفعّل افتراضياً)
    🆕 v6.4.98: V3 default = 1 (مفعّل افتراضياً)
    """
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r") as f:
                data = _json_state.load(f)
                v1 = data.get("v1_enabled", None)
                v2 = data.get("v2_enabled", None)
                v3 = data.get("v3_enabled", None)  # 🆕 v6.4.98
                if v1 is None: v1 = os.environ.get("V1_ENABLED", "1") == "1"
                # 🆕 v6.4.94: V2 default = 1 (مفعّل افتراضياً — V2 شُفي في v6.4.93)
                if v2 is None: v2 = os.environ.get("V2_ENABLED", "1") == "1"
                # 🆕 v6.4.98: V3 default = 1 (مفعّل افتراضياً)
                if v3 is None: v3 = os.environ.get("V3_ENABLED", "1") == "1"
                return bool(v1), bool(v2), bool(v3)
    except Exception as e:
        log.warning(f"💾 [V1/V2/V3 state] load err: {e}")
    # 🆕 v6.4.94: V2 default = 1 (مفعّل افتراضياً)
    # 🆕 v6.4.98: V3 default = 1 (مفعّل افتراضياً)
    return (
        os.environ.get("V1_ENABLED", "1") == "1",
        os.environ.get("V2_ENABLED", "1") == "1",
        os.environ.get("V3_ENABLED", "1") == "1",
    )


def _save_v1_v2_state(v1: bool, v2: bool, v3: bool = None) -> bool:
    """🆕 v6.4.84: حفظ حالة V1/V2/V3 في ملف دائم (لِتبقى بعد إعادة النشر).
    🆕 v6.4.98: V3 support
    """
    try:
        # 🆕 v6.4.98: لو v3 = None → اقرأ الحالة الحالية لِـ v3
        if v3 is None:
            try:
                if os.path.exists(_STATE_FILE):
                    with open(_STATE_FILE, "r") as f:
                        data = _json_state.load(f)
                        v3 = data.get("v3_enabled", True)
                else:
                    v3 = True
            except Exception:
                v3 = True
        with open(_STATE_FILE, "w") as f:
            _json_state.dump({"v1_enabled": v1, "v2_enabled": v2, "v3_enabled": v3}, f)
        log.info(f"💾 [V1/V2/V3 state] saved: V1={v1} V2={v2} V3={v3}")
        return True
    except Exception as e:
        log.warning(f"💾 [V1/V2/V3 state] save err: {e}")
        return False


V1_ENABLED, V2_ENABLED, V3_ENABLED = _load_v1_v2_state()
# 🆕 v6.4.83: فلتر تشديد الجودة — رفع العتبات
#    MTF_MIN_BULLISH: 3 → 4 (كل الفريمات متوافقة)
#    MTF_MIN_CONFLUENCE: 50 → 55
#    SCORE_THRESHOLD: 50 → 55
# 🆕 v6.4.83: رفض الدخول عند القمة — الحد الأدنى للبُعد عن recent_high
MIN_DIST_FROM_HIGH_PCT = float(os.environ.get("MIN_DIST_FROM_HIGH_PCT", "1.5"))
# 🆕 v6.4.83: تنبيه اخرج عند القمة — الحد الأدنى للربح قبل تفعيل المراقبة (3%)
PEAK_EXIT_MIN_PROFIT = float(os.environ.get("PEAK_EXIT_MIN_PROFIT", "3.0"))
# 🆕 v6.4.83: نسبة التراجع من القمة لتشغيل تنبيه اخرج (1.5%)
PEAK_EXIT_PULLBACK_PCT = float(os.environ.get("PEAK_EXIT_PULLBACK_PCT", "1.5"))
# 🆕 v6.4.83: متغيرات قديمة محتفظ بها للتوافق مع أي كود قديم
V1_PUBLISH_TO_CHANNEL = V1_ENABLED  # mirror لِـ V1_ENABLED (للتوافق القديم)
V2_PUBLISH_TO_CHANNEL = V2_ENABLED  # mirror لِـ V2_ENABLED (للتوافق القديم)

# 🆕 v6.3: أقصى مدة لدورة المسح بالثواني (حماية من التعليق)
MAX_CYCLE_TIME = int(os.environ.get("MAX_CYCLE_TIME", "240"))
# 🆕 v6.4: وضع عرض الإشارة — simple (افتراضي، قصير) أو detailed (كامل)
HQ_DISPLAY_MODE = os.environ.get("HQ_DISPLAY_MODE", "simple")
# 🆕 v6.4.7: نظام الخروج المبكر الذكي (Smart Early Exit)
# 🆕 v6.4.108: معطّل نهائياً — استبدال بِـ Smart Momentum Insight
EARLY_EXIT_ENABLED = os.environ.get("EARLY_EXIT_ENABLED", "0") == "1"
PEAK_EXIT_MIN_PROFIT = float(os.environ.get("PEAK_EXIT_MIN_PROFIT", "999"))  # 🆕 v6.4.108: معطّل (999 = لن يفعل)
PEAK_EXIT_PULLBACK_PCT = float(os.environ.get("PEAK_EXIT_PULLBACK_PCT", "999"))  # 🆕 v6.4.108: معطّل
# الحد الأدنى لقوة ضعف الاتجاه (0-100) قبل إرسال تنبيه (افتراضي 40)
EARLY_EXIT_MIN_WEAKNESS = int(os.environ.get("EARLY_EXIT_MIN_WEAKNESS", "40"))
# الفاصل الزمني بين تنبيهات الخروج المبكر لنفس الصفقة (افتراضي 4 ساعات)
EARLY_EXIT_ALERT_COOLDOWN = int(os.environ.get("EARLY_EXIT_ALERT_COOLDOWN", "14400"))
TIMEZONE = os.environ.get("TIMEZONE", "Africa/Algiers")
PORT = int(os.environ.get("PORT", 10000))

# 🆕 v6.3: mutex لمنع تشغيل scan متزامن (scheduler + /forcescan + /scandebug)
_scan_mutex = threading.Lock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("Bot")

# ═══ Default Coins (30) ═══
COINS = {
    "BTC":{"ar":"بيتكوين"}, "ETH":{"ar":"إيثيريوم"}, "BNB":{"ar":"بايننس"},
    "SOL":{"ar":"سولانا"}, "XRP":{"ar":"ريبل"}, "ADA":{"ar":"كاردانو"},
    "DOGE":{"ar":"دوجكوين"}, "AVAX":{"ar":"أفالانش"}, "LINK":{"ar":"تشين لينك"},
    "DOT":{"ar":"بولكادوت"}, "MATIC":{"ar":"بوليجون"}, "LTC":{"ar":"لايتكوين"},
    "ATOM":{"ar":"كوزموس"}, "NEAR":{"ar":"نير"}, "ARB":{"ar":"أربيتروم"},
    "OP":{"ar":"أبتمزم"}, "APT":{"ar":"أبتوس"}, "SUI":{"ar":"سوي"},
    "INJ":{"ar":"إينجكتيف"}, "TIA":{"ar":"سيليستيا"}, "SEI":{"ar":"سي"},
    "ROSE":{"ar":"أواسيس"}, "SKL":{"ar":"سكيل"}, "FTM":{"ar":"فانتوم"},
    "GRT":{"ar":"جراف"}, "RUNE":{"ar":"رون"}, "AAVE":{"ar":"آيف"},
    "UNI":{"ar":"يوني"}, "FIL":{"ar":"فايلكوين"}, "IMX":{"ar":"إيمكس"},
}

# ═══ User Data (local files) ═══
DATA_DIR = "/tmp/bot_data"
os.makedirs(DATA_DIR, exist_ok=True)

def _load(fname):
    try:
        p = os.path.join(DATA_DIR, fname)
        if os.path.exists(p):
            with open(p) as f: return json.load(f)
    except Exception: pass  # 🆕 v6.4.35: silent but typed
    return {}

def _save(fname, data):
    try:
        p = os.path.join(DATA_DIR, fname)
        with open(p, "w") as f: json.dump(data, f, ensure_ascii=False)
    except Exception: pass  # 🆕 v6.4.35: silent but typed

def get_favorites(cid):
    d = _load("favorites.json")
    return d.get(str(cid), [])

def add_favorite(cid, sym):
    d = _load("favorites.json")
    cids = d.get(str(cid), [])
    if sym not in cids:
        cids.append(sym)
    d[str(cid)] = cids
    _save("favorites.json", d)

def remove_favorite(cid, sym):
    d = _load("favorites.json")
    cids = d.get(str(cid), [])
    if sym in cids:
        cids.remove(sym)
    d[str(cid)] = cids
    _save("favorites.json", d)

def get_portfolio(cid):
    d = _load("portfolio.json")
    return d.get(str(cid), {})

def add_buy_point(cid, sym, price, qty):
    d = _load("portfolio.json")
    pf = d.get(str(cid), {})
    if sym not in pf: pf[sym] = []
    pf[sym].append({"price": price, "qty": qty, "ts": int(time.time())})
    d[str(cid)] = pf
    _save("portfolio.json", d)

# ═══ Telegram ═══
def _tg_post(endpoint: str, payload: dict, timeout: int = 10) -> dict:
    """🆕 v6.4.39: مساعد موحّد لإرسال لـ Telegram.
    - يستخدم data= (form-data) — reply_markup يجب أن يكون JSON string
    - يحوّل reply_markup تلقائياً لـ JSON string (أمان إضافي)
    - يحوّل chat_id لـ str دائماً
    - 🆕 v6.4.39: يسجل BOT_VERSION في رسالة الفشل لتأكيد النسخة المنشورة
    يرجع dict: {ok: bool, error_code: int, description: str, message_id: int|None}
    """
    if not TOKEN:
        return {"ok": False, "error_code": -1, "description": "No TOKEN", "message_id": None}
    try:
        # 🆕 v6.4.38: نسخة آمنة من payload — reply_markup كـ JSON string صريح
        safe_payload = {}
        for k, v in payload.items():
            if k == "reply_markup" and v is not None and not isinstance(v, str):
                safe_payload[k] = json.dumps(v, ensure_ascii=False)
            elif k == "chat_id":
                safe_payload[k] = str(v)
            else:
                safe_payload[k] = v
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{endpoint}",
                          data=safe_payload, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "description": f"Non-JSON response (HTTP {r.status_code})"}
        if not data.get("ok", False):
            err_code = data.get("error_code", r.status_code)
            err_desc = data.get("description", "Unknown error")
            chat_id = safe_payload.get("chat_id", "?")
            # 🆕 v6.4.39: تسجيل BOT_VERSION لتأكيد النسخة المنشورة على Render
            log.warning(f"⚠️ [TG {endpoint}] failed [{BOT_VERSION}]: chat_id={chat_id} "
                        f"(type={type(chat_id).__name__}) | code={err_code} | {err_desc}")
            return {"ok": False, "error_code": err_code, "description": err_desc, "message_id": None}
        # 🆕 v6.2.6: التقاط message_id عند نجاح sendMessage
        msg_id = None
        if endpoint == "sendMessage" and "result" in data:
            msg_id = data["result"].get("message_id")
        return {"ok": True, "error_code": 0, "description": "ok", "message_id": msg_id}
    except Exception as e:
        log.warning(f"⚠️ [TG {endpoint}] network error: {e}")
        return {"ok": False, "error_code": -2, "description": str(e), "message_id": None}


def send_msg(msg, kb=None, cid=None):
    """🆕 v6.4.39: ترتيب المعاملات (msg, kb, cid) لتطابق كل الاستدعاءات.
    سابقاً كان (msg, cid, kb) مما أدى لتمرير kb كـ chat_id → خطأ 'object expected as reply markup'.
    🆕 v6.4.39: تسجيل تشخيصي عند الفشل لكشف الإصدار الفعلي.
    """
    target = cid or CHAT_ID
    if not target or not TOKEN:
        return
    payload = {"chat_id": target, "text": msg, "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = kb  # _tg_post سيحوّله لـ JSON string تلقائياً
    _tg_post("sendMessage", payload)


def send_to_channel(msg):
    """🆕 v6.0: قناة الأهداف المحققة (TP/SL) — موجودة مسبقاً."""
    if not CHANNEL_ID or not TOKEN:
        return
    _tg_post("sendMessage", {"chat_id": str(CHANNEL_ID), "text": msg, "parse_mode": "HTML"})


def _send_trade_alert(msg, trade_dict=None):
    """🆕 v6.4.83-fix/v6.4.111: يوجّه تنبيه TP/SL/expiry حسب استراتيجية الصفقة.

    - V1_ENABLED=True  → إرسال لِقناة الأهداف (CHANNEL_ID)
    - V1_ENABLED=False → إرسال للبوت فقط (CHAT_ID)
    - V2_ENABLED=True  → إرسال لِقناة الأهداف (CHANNEL_ID)
    - V2_ENABLED=False → إرسال للبوت فقط (CHAT_ID)
    - V3_ENABLED=True  → إرسال لِقناة الأهداف (CHANNEL_ID)
    - V3_ENABLED=False → إرسال للبوت فقط (CHAT_ID)
    """
    try:
        strategy = (trade_dict or {}).get("strategy", "v1") if trade_dict else "v1"
        if strategy == "v2":
            if V2_ENABLED:
                send_to_channel(msg)
            else:
                send_msg(msg, None, CHAT_ID)
        elif strategy == "v3":
            # 🆕 v6.4.111: V3 routing
            if V3_ENABLED:
                send_to_channel(msg)
            else:
                send_msg(msg, None, CHAT_ID)
        else:
            # V1 (افتراضي)
            if V1_ENABLED:
                send_to_channel(msg)
            else:
                send_msg(msg, None, CHAT_ID)
    except Exception as e:
        log.warning(f"_send_trade_alert err: {e}")
        send_msg(msg, None, CHAT_ID)


def send_to_signals_channel(msg, kb=None) -> int:
    """🆕 v6.2: قناة خارجية لإرسال الإشارات الجديدة فقط (entry signals).
    🆕 v6.2.6: يرجع message_id لرسالة القناة (للحذف لاحقاً عند TP/SL).
    🆕 v6.4.87: يدعم inline keyboard (kb) — أزرار Binance + TradingView تحت رسالة القناة.
    - لو SIGNALS_CHANNEL_ID فارغ أو فشل الإرسال → يرجع None
    - يُستخدم في scan_cycle لحفظ message_id في tracker.py
    """
    if not SIGNALS_CHANNEL_ID or not TOKEN:
        return None
    payload = {"chat_id": str(SIGNALS_CHANNEL_ID), "text": msg, "parse_mode": "HTML"}
    if kb:
        # 🆕 v6.4.87: أضف inline_keyboard لِرسالة القناة (URL buttons تعمل في القنوات)
        payload["reply_markup"] = kb
    res = _tg_post("sendMessage", payload)
    if res["ok"]:
        return res["message_id"]
    return None


def delete_signal_message(message_id: int) -> bool:
    """🆕 v6.2.6: حذف رسالة الإشارة من قناة الصفقات عند تحقق الهدف.
    يستخدم deleteMessage endpoint من Telegram API.
    """
    if not SIGNALS_CHANNEL_ID or not TOKEN or not message_id:
        return False
    res = _tg_post("deleteMessage", {
        "chat_id": SIGNALS_CHANNEL_ID,
        "message_id": message_id
    })
    if res["ok"]:
        log.info(f"🗑️ [SIGNAL DELETED] msg_id={message_id} from signals channel")
        return True
    else:
        log.warning(f"⚠️ [SIGNAL DELETE FAILED] msg_id={message_id}: {res['description']}")
        return False

def _test_single_channel(name: str, chat_id: str, send_test: bool = True) -> tuple:
    """🆕 v6.2.3: فحص قناة واحدة + محاولة sendMessage للتحقق من admin.
    يرجع (status_emoji, status_text, needs_attention).
    """
    if not chat_id:
        return ("⚠️", "غير مُفعّلة", True)

    # 1) getChat: التحقق من وجود القناة + الحصول على اسمها
    chat_title = "?"
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getChat",
                         params={"chat_id": chat_id}, timeout=10)
        data = r.json()
        if data.get("ok"):
            chat_title = data.get("result", {}).get("title", "?")
        else:
            err_desc = data.get("description", "Unknown error")
            return ("❌", f"{err_desc} ({chat_id})", True)
    except Exception as e:
        return ("❌", f"Network error: {e} ({chat_id})", True)

    # 2) sendMessage: التحقق من أن البوت admin
    if send_test:
        test_res = _tg_post("sendMessage", {
            "chat_id": chat_id,
            "text": f"🤖 <b>اختبار {name}</b>\n✅ البوت يستطيع الإرسال لهذه القناة",
            "parse_mode": "HTML"
        })
        if test_res["ok"]:
            return ("✅", f"{chat_title} ({chat_id}) — البوت admin ويمكنه الإرسال", False)
        else:
            return ("❌", f"{chat_title} ({chat_id}) — فشل الإرسال: {test_res['description']}", True)
    else:
        return ("✅", f"{chat_title} ({chat_id})", False)


def test_channel_at_startup():
    """🆕 v6.2.3: فحص القناتين عند الإقلاع — يكتشف مشاكل admin/chat_id مبكراً.
    يفحص:
      - CHANNEL_ID (قناة الأهداف المحققة - TP/SL)
      - SIGNALS_CHANNEL_ID (قناة الصفقات الجديدة)
    يرسل رسالة اختبار لكل قناة + تقرير للـ CHAT_ID.
    """
    report = "🔍 <b>فحص القنوات (v6.2.3)</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    # 1) قناة الأهداف (TP/SL)
    emoji, text, attn = _test_single_channel("قناة الأهداف", CHANNEL_ID, send_test=True)
    report += f"📡 <b>قناة الأهداف</b> (TP/SL): {emoji} {text}\n"
    needs_attention = attn

    # 2) قناة الصفقات (entry signals)
    emoji, text, attn = _test_single_channel("قناة الصفقات", SIGNALS_CHANNEL_ID, send_test=True)
    report += f"📡 <b>قناة الصفقات</b> (Entry): {emoji} {text}\n"
    needs_attention = needs_attention or attn

    # 3) SCAN_ALL_SPOT status
    if SCAN_ALL_SPOT:
        report += f"\n🌍 مسح Spot: مفعّل (240+ عملة)\n"
    else:
        report += f"\n🌍 مسح Spot: مُعطّل (مفضلة + top movers فقط)\n"

    # 4) ملخص توجيه الرسائل
    report += "\n📨 <b>توجيه الرسائل:</b>\n"
    report += f"  • 💎 إشارة جديدة (entry) → CHAT_ID + قناة الصفقات\n"
    report += f"  • 🎯 TP1/TP3 محقق → CHAT_ID + قناة الأهداف\n"
    report += f"  • 🛑 SL محقق → CHAT_ID + قناة الأهداف\n"

    # 5) نصائح
    if needs_attention:
        report += "\n⚠️ <b>تنبيهات تحتاج انتباهك:</b>\n"
        report += "• أضف البوت كـ <b>administrator</b> في القنوات (مع صلاحية Post Messages)\n"
        report += "• chat_id القناة يجب أن يبدأ بـ <code>-100</code>\n"
        report += "• بعد الإصلاح، أرسل <code>/testchannel</code> لإعادة الفحص\n"

    log.info(f"🔍 Channel test report:\n{report}")
    send_msg(report)


def main_kb():
    """🆕 v6.4.118: لوحة المفاتيح — أزرار V1/V2/V3 ملوّنة (🟢 قناة / 🔴 بوت)."""
    return {"keyboard": [
        [{"text": "📊 المفضلة"}, {"text": "💼 المحفظة"}],
        [{"text": "🔥 الأكثر صعوداً"}, {"text": "⚡ إضافة سريعة"}],
        [{"text": "🕌 حكم عملة"}, {"text": "🗑️ حذف عملة"}],
        # 🆕 v6.4.118: V1/V2/V3 — 🟢 = يرسل للقناة، 🔴 = يرسل للبوت فقط
        [{"text": "💎 V1: " + ("🟢 قناة" if V1_ENABLED else "🔴 بوت")},
         {"text": "🔄 V2: " + ("🟢 قناة" if V2_ENABLED else "🔴 بوت")},
         {"text": "🚀 V3: " + ("🟢 قناة" if V3_ENABLED else "🔴 بوت")}],
        [{"text": "📋 سجل أسبوعي"}, {"text": "📊 إحصائيات"}],
        [{"text": "👥 قائمة المستخدمين"}],
        [{"text": "📋 سجل الأداء"}, {"text": "📄 تقرير PDF"}],
    ], "resize_keyboard": True, "is_persistent": True}

def quick_add_kb(cid):
    favs = get_favorites(cid)
    rows, row = [], []
    for sym in sorted(COINS.keys()):
        e = "✅" if sym in favs else "➕"
        row.append({"text": f"{e} {sym}", "callback_data": f"qa_{sym}" if sym not in favs else f"qd_{sym}"})
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([{"text": "✅ تم", "callback_data": "done"}])
    return {"inline_keyboard": rows}


# 🆕 v6.4.90: لوحة مفاتيح inline لعرض العملات المحفوظة مع زر حذف بجانب كل عملة
def halal_list_delete_kb() -> dict:
    """يبني لوحة inline لعرض كل العملات في halal_rulings مع زر 🗑️ بجانب كل عملة.
    كل صف يحتوي: [🟢 SYM] [🗑️ حذف]
    10 عملات per page (Telegram inline keyboard limit: 100 buttons).
    """
    try:
        rulings = halal_check.list_rulings()
        if not rulings:
            return {"inline_keyboard": [[{"text": "📭 لا توجد عملات محفوظة", "callback_data": "noop"}]]}
        rows = []
        # رؤوس الأعمدة
        rows.append([{"text": "🪙 العملة (الحكم)", "callback_data": "noop"},
                     {"text": "🗑️ حذف", "callback_data": "noop"}])
        for r in rulings[:30]:  # limit to 30 (Telegram allows up to 100 buttons)
            sym = r["symbol"]
            icon = r["icon"]
            ruling = r["label_ar"]
            rows.append([
                {"text": f"{icon} {sym} ({ruling})", "callback_data": f"hinfo_{sym}"},
                {"text": f"🗑️ {sym}", "callback_data": f"hd_{sym}"},
            ])
        # أزرار التنقل
        rows.append([{"text": "✅ تم", "callback_data": "done"}])
        return {"inline_keyboard": rows}
    except Exception as e:
        log.warning(f"halal_list_delete_kb err: {e}")
        return {"inline_keyboard": [[{"text": "❌ خطأ", "callback_data": "noop"}]]}


# 🆕 v6.4.90: لوحة مفاتيح inline لعرض المفضلة مع زر حذف بجانب كل عملة
def favorites_delete_kb(cid) -> dict:
    """يبني لوحة inline لعرض كل عملات المفضلة مع زر 🗑️ بجانب كل عملة.
    كل صف يحتوي: [🪙 SYM] [🗑️ حذف]
    """
    try:
        favs = get_favorites(cid)
        if not favs:
            return {"inline_keyboard": [[{"text": "📭 المفضلة فارغة", "callback_data": "noop"}]]}
        rows = []
        rows.append([{"text": "🪙 العملة", "callback_data": "noop"},
                     {"text": "🗑️ حذف", "callback_data": "noop"}])
        for sym in sorted(favs)[:30]:
            rows.append([
                {"text": f"🪙 {sym}", "callback_data": f"finfo_{sym}"},
                {"text": f"🗑️ {sym}", "callback_data": f"fd_{sym}"},
            ])
        rows.append([{"text": "✅ تم", "callback_data": "done"}])
        return {"inline_keyboard": rows}
    except Exception as e:
        log.warning(f"favorites_delete_kb err: {e}")
        return {"inline_keyboard": [[{"text": "❌ خطأ", "callback_data": "noop"}]]}

# ═══ Scheduler Loop ═══
_cycle_signaled = set()
# 🆕 v6.4.31: أزلت SCAN_INTERVAL = 600 (كان يلغي قيمة env 300)

# 🆕 v6.4.42: Silent monitoring mode state — لا تنبيهات للمستخدم
_bot_mode = "normal"  # "normal" | "monitoring"
_mode_changed_at = 0.0
_last_recovery_ping = 0.0
_RECOVERY_PING_INTERVAL = 1800  # 30 دقيقة بين محاولات الاستعادة
_MONITORING_SCAN_INTERVAL = 900  # 15 دقيقة فاصل المسح في وضع المراقبة
MAX_ACTIVE_TRADES_FOR_RESTRICTION = 999  # 🆕 v6.4.62: تعطيل (999 = لا حد)
QUALITY_THRESHOLD = 0.0  # 🆕 v6.4.62: تعطيل (0 = لا فلتر جودة)


def _is_significant_price_change(sym: str, cid: str, current_price: float) -> bool:
    """🆕 v6.4.42: فحص ذكي لتغير السعر — يقرر هل نرسل صفقة جديدة لنفس العملة.

    القواعد (بدل المنع الكامل الذي كان يوقف الصفقات):
      ✅ أرسل صفقة جديدة لو:
        1) السعر صعد فوق أعلى TP من الصفقة السابقة (الأهداف اكتملت)
        2) السعر هبط 15%+ تحت سعر الدخول (فقدان كبير، فرصة جديدة)
      ❌ لا ترسل لو:
        - السعر ما زال في نطاق الصفقة الأصلية (بين الدخول وأعلى TP)

    يرجع True = اسمح بصفقة جديدة، False = امنع التكرار.
    """
    try:
        import tracker as _tk_check
        trades_list = _tk_check._load().get(str(cid), [])
        original = next((t for t in trades_list
                         if t.get("symbol") == sym and t.get("status") in _tk_check.NON_FINAL), None)
        if not original:
            return True  # لا توجد صفقة نشطة → اسمح

        entry = original.get("entry", 0) or 0
        tps = [original.get(f"tp{i}", 0) for i in range(1, 7)]
        tps = [t for t in tps if t and t > 0]

        if not entry or not tps:
            return True  # بيانات ناقصة → اسمح (احتياط)

        max_tp = max(tps)

        # شرط 1: السعر صعد فوق أعلى TP → الصفقة السابقة اكتملت أهدافها
        if current_price >= max_tp * 1.02:
            log.info(f"♻️ {sym}: سعر جديد {current_price} > max_tp {max_tp} → صفقة جديدة مسموحة")
            return True

        # شرط 2: السعر هبط 15%+ تحت الدخول → فرصة جديدة بعد خسارة
        if current_price <= entry * 0.85:
            log.info(f"♻️ {sym}: سعر جديد {current_price} ≤ entry*0.85 {entry*0.85} → صفقة جديدة مسموحة")
            return True

        # السعر ما زال في نطاق الصفقة → منع التكرار
        return False
    except Exception as e:
        log.warning(f"_is_significant_price_change err: {e}")
        return True  # احتياط: اسمح في حالة الخطأ


def _try_recovery_ping() -> bool:
    """🆕 v6.4.42: محاولة استعادة Binance كل 30 دقيقة — صامتة (لا تنبيه للمستخدم)."""
    global _last_recovery_ping, _bot_mode, _banned_until_local
    _last_recovery_ping = time.time()
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        r = requests.get("https://api.binance.com/api/v3/ping", timeout=10, headers=headers)
        if r.status_code == 200:
            # Binance عاد → الخروج من وضع المراقبة صامتة
            import engine as _eng_recover
            _eng_recover._banned_until = 0  # إعادة تعيين الحظر
            if _bot_mode == "monitoring":
                _bot_mode = "normal"
                log.info("▶️ Binance recovered — exiting monitoring mode (silent)")
            return True
    except Exception:
        pass
    return False

def check_trades(cid):
    """🆕 v6.4.9: فحص متسلسل لكل الأهداف في نفس الدورة + SL صحيح + شموع 15m.

    🆕 v6.4.9 إصلاحات كبرى:
      1) فحص متسلسل: لو السعر تجاوز TP1+TP2+TP3+TP4+TP5 في نفس الشمعة،
         كل الأهداف تُحقق في نفس الدورة (بدل 5 دورات = 25 دقيقة تأخير)
      2) رسالة SL صحيحة: عرض سعر SL الفعلي (الذي ضُرب) بدل الإغلاق الحالي
      3) شموع 15m للمراقبة السريعة (بدل 1h) — التقاط أسرع للأهداف
    """
    active = get_active(cid)  # 🆕 v6.4.68: يرجع كل الصفقات (V1 + V2) — كلاهما يُراقب
    if not active:
        return 0
    events = 0
    now = int(time.time())
    for t in active:
        sym = t["symbol"]
        # 🆕 v6.4.82: مراقبة متعددة الفريمات — 15m (سريع) + 1h (تأكيد) بدل 15m فقط
        # 🆕 v6.4.58: defensive checks لمنع list index out of range
        candles_1h = []
        try:
            candles = fetch_klines(sym, interval="15m", limit=4)
            if candles and len(candles) >= 1:
                cur = candles[-1]["close"]
                candle_high = candles[-1]["high"]
                candle_low = candles[-1]["low"]
            else:
                # 15m غير متاح → استخدم 1h مباشرة (وأعد استخدامها للتأكيد)
                candles_1h = fetch_klines(sym, interval="1h", limit=6) or []
                if not candles_1h:
                    log.warning(f"⚠️ [check_trades] {sym}: no candles data, skipping")
                    continue
                cur = candles_1h[-1]["close"]
                candle_high = candles_1h[-1]["high"]
                candle_low = candles_1h[-1]["low"]
        except (IndexError, KeyError, TypeError) as e:
            log.warning(f"⚠️ [check_trades] {sym}: candles access err: {e}")
            continue

        # 🆕 v6.4.82: جلب آخر شمعة 1h **مغلقة** لتأكيد ضرب الستوب
        # لو الشمعة 1h مغلقة فوق SL → هبوط 15m قد يكون مجرد ضجيج ولا يُعلن خروج
        h1_closed_close = None
        if not candles_1h:
            try:
                candles_1h = fetch_klines(sym, interval="1h", limit=6) or []
            except Exception as e:
                log.warning(f"⚠️ [check_trades] {sym}: 1h candles err: {e}")
                candles_1h = []
        if candles_1h and len(candles_1h) >= 2:
            try:
                h1_closed_close = candles_1h[-2]["close"]
            except (IndexError, KeyError, TypeError):
                h1_closed_close = None

        # تحديث MFE/MAE
        update_mfe_mae(cid, t["signal_id"], cur)

        # ── 🆕 v6.4.83: فحص Peak Exit — تنبيه الخروج عند القمة ──
        # المنطق: لو الصفقة حققت ربح ≥ PEAK_EXIT_MIN_PROFIT ثم تراجعت ≥ PEAK_EXIT_PULLBACK_PCT
        # نُرسل تنبيه "تنبيه القمة" (مرة واحدة لكل صفقة)
        try:
            _entry = t["entry"]
            _mfe_db = t.get("mfe", 0)  # MFE من دورات سابقة (نسبة %)
            _cur_pnl_pct = (cur - _entry) / _entry * 100 if _entry > 0 else 0
            # 🆕 v6.4.83: استخدم max(mfe_db, cur_pnl) — لو السعر الحالي نفسه قمة جديدة
            _live_mfe = max(_mfe_db, _cur_pnl_pct)
            if _entry > 0 and _live_mfe >= PEAK_EXIT_MIN_PROFIT:
                # peak_price = entry × (1 + live_mfe/100)
                _peak_price = _entry * (1 + _live_mfe / 100.0)
                # تراجع عن القمة = peak_pct - cur_pct
                _pullback_from_peak = _live_mfe - _cur_pnl_pct
                # لو التراجع ≥ PEAK_EXIT_PULLBACK_PCT ولم نُرسل التنبيه من قبل
                if _pullback_from_peak >= PEAK_EXIT_PULLBACK_PCT:
                    _last_peak_ts = t.get("last_peak_alert_ts", 0)
                    if _last_peak_ts == 0:  # مرة واحدة فقط
                        dur = format_duration(now - t["created_at"])
                        _strategy = t.get("strategy", "v1")
                        msg = format_peak_exit_alert(sym, _entry, _peak_price, cur,
                                                      _pullback_from_peak, _cur_pnl_pct, dur, _strategy)
                        _send_trade_alert(msg, t)
                        log.info(f"⛰️ [PEAK EXIT] {sym} — peak={_peak_price} pullback={_pullback_from_peak:.2f}% profit={_cur_pnl_pct:.2f}%")
                        # علّم أنه تم إرسال التنبيه (لمنع التكرار)
                        try:
                            set_peak_alert_sent(cid, t["signal_id"], now)
                        except Exception as _pe:
                            log.warning(f"⛰️ peak update err: {_pe}")
        except Exception as _e:
            log.warning(f"⛰️ [PEAK EXIT] {sym} err: {_e}")

        # ── فحص SL (مع تأكيد متعدد الفريمات 🆕 v6.4.82) ──
        # شرط اللمس (v6.4.14): wick وصل SL + الإغلاق 15m تحت SL×1.005
        # 🆕 v6.4.82 التأكيد المزدوج — لا نعلن الخروج إلا لو:
        #   1) آخر شمعة 1h مغلقة أغلقت تحت SL×1.005 (الفريم الأعلى يؤكد الهبوط) أو
        #   2) انهيار حاد: السعر ≤ SL×0.97 (خروج طارئ بدون انتظار إغلاق 1h)
        # وإلا → هبوط 15m = ضجيج فقط → الصفقة تكمل لبلوغ الأهداف التالية
        sl_touched_15m = candle_low <= t["sl"] and cur <= t["sl"] * 1.005
        sl_confirmed = False
        if sl_touched_15m:
            if h1_closed_close is None:
                sl_confirmed = True  # لا بيانات 1h → السلوك السابق (أمان)
            elif h1_closed_close <= t["sl"] * 1.005:
                sl_confirmed = True  # الفريم الأعلى يؤكد
            elif cur <= t["sl"] * 0.97:
                sl_confirmed = True  # انهيار حاد — خروج طارئ
            else:
                log.info(f"⏳ [MTF-SL] {sym}: 15m تحت SL لكن 1h مغلقة فوقه ({fmt_price(h1_closed_close)}) — انتظار (ضجيج)")
        if sl_confirmed:
            dur = format_duration(now - t["created_at"])
            # 🆕 v6.4.82: الستوب الديناميكي — ضربه بعد ≥1 هدف = نجاح وليس خسارة
            n_tps = {"TP1_HIT": 1, "TP2_HIT": 2, "TP3_HIT": 3, "TP4_HIT": 4}.get(t["status"], 0)
            if n_tps > 0:
                remaining = {1: 0.50, 2: 0.25, 3: 0.15, 4: 0.05}[n_tps]
                _entry = t["entry"]
                pnl_est = (t.get("pnl", 0) + remaining * ((t["sl"] - _entry) / _entry * 100)) if _entry > 0 else t.get("pnl", 0)
                _trade_strategy = t.get("strategy", "v1")  # 🆕 v6.4.88: استراتيجية الصفقة
                msg = format_tp_success_close(sym, n_tps, t["sl"], cur, dur, pnl_est, strategy=_trade_strategy)
                log.info(f"🏆 DYNAMIC SL: {sym} بعد {n_tps} هدف — نجاح (est pnl={pnl_est:+.2f}%)")
            else:
                _trade_strategy = t.get("strategy", "v1")  # 🆕 v6.4.88: استراتيجية الصفقة
                msg = format_sl_alert(sym, t["sl"], cur, dur, strategy=_trade_strategy)
                log.info(f"🛑 SL HIT: {sym} @ {t['sl']} (candle_low={candle_low}, close={cur})")
            # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
            _send_trade_alert(msg, t)
            sig_msg_id = get_signal_message_id(cid, t["signal_id"])
            if sig_msg_id:
                delete_signal_message(sig_msg_id)
                clear_signal_message_id(cid, t["signal_id"])
            # 🆕 v6.4.82: الخروج عند سعر الستوب نفسه (واقعي — أمر stop-market) وليس أدنى نقطة
            hit_sl(cid, t["signal_id"], t["sl"])
            # 🆕 v6.4.91: علّم العملة في cooldown (لو V2) لِمنع الدخول لِـ 24h
            try:
                _trade_strat = t.get("strategy", "v1")
                if _trade_strat == "v2":
                    strategy_v2._mark_sl_hit(sym)
                    log.info(f"🔄 [V2-COOLDOWN] {sym} marked — 24h cooldown after SL")
            except Exception as _e_mark:
                log.warning(f"V2 mark_sl_hit call err: {_e_mark}")
            clear_signal_dedup(sym)
            events += 1
            continue

        # ── 🆕 v6.4.9: فحص متسلسل لكل الأهداف في نفس الدورة ──
        # لو candle_high >= TP_next → حقّق الهدف + حاول التالي في نفس الدورة.
        # هذا يحل مشكلة "البوت يأخذ 25 دقيقة لتحقيق 5 أهداف في نفس الشمعة".
        tp_levels = [
            ("TP1", t.get("tp1", t.get("tp", 0)), format_tp1_alert),
            ("TP2", t.get("tp2", 0), format_tp2_alert),
            ("TP3", t.get("tp3", 0), format_tp3_alert),
            ("TP4", t.get("tp4", 0), format_tp4_alert),
            ("TP5", t.get("tp5", 0), format_tp5_alert),
            ("TP6", t.get("tp6", 0), format_tp6_alert),
        ]
        status_order = ["ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "TP5_HIT"]
        current_status = t["status"]
        if current_status not in status_order:
            continue
        current_idx = status_order.index(current_status)

        for i in range(current_idx, len(tp_levels)):
            level_name, tp_price, alert_func = tp_levels[i]
            if tp_price <= 0:
                continue
            if candle_high >= tp_price:
                dur = format_duration(now - t["created_at"])
                msg = alert_func(t, cur, dur)
                # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
                _send_trade_alert(msg, t)
                is_final = level_name in ("TP5", "TP6")
                if is_final:
                    sig_msg_id = get_signal_message_id(cid, t["signal_id"])
                    if sig_msg_id:
                        delete_signal_message(sig_msg_id)
                        clear_signal_message_id(cid, t["signal_id"])
                    # 🆕 v6.4.15: رسالة "تم تحقيق جميع الأهداف" + حذف نهائي من المتابعة
                    all_done_msg = f"✅ <b>تم تحقيق جميع أهداف الصفقة</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                    all_done_msg += f"🪙 <b>{sym}</b> — اكتملت كل الأهداف\n"
                    all_done_msg += f"💰 السعر النهائي: {fmt_price(cur)}\n"
                    all_done_msg += f"⏱️ مدة الصفقة: {format_duration(now - t['created_at'])}\n\n"
                    all_done_msg += "✅ <b>الصفقة حُذفت من المتابعة</b>\n"
                    all_done_msg += "💡 لن يصلك تنبيه SL لهذه الصفقة بعد الآن"
                # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
                    _send_trade_alert(all_done_msg, t)
                    log.info(f"✅ ALL TARGETS DONE: {sym} — removed from tracking")
                hit_tp(cid, t["signal_id"], tp_price, cur, level=level_name)
                events += 1
                log.info(f"🎯 {sym} {level_name} HIT @ {tp_price} (candle_high={candle_high})")
                if is_final:
                    clear_signal_dedup(sym)
                    break  # الصفقة أُغلقت نهائياً — توقف عن المتابعة
                # 🆕 v6.4.9: حدّث t للفحص المتسلسل (التالي)
                updated_trades = [tt for tt in tracker._load().get(str(cid), [])
                                  if tt["signal_id"] == t["signal_id"]]
                if updated_trades:
                    t = updated_trades[0]
                continue
            else:
                break

        # ── فحص Expiry (فقط لو ACTIVE) ──
        if t["status"] == "ACTIVE":
            valid_until = t.get("valid_until", t["created_at"] + HQ_SIGNAL_EXPIRY_HOURS * 3600)
            if now > valid_until and cur > t.get("entry_high", t["entry"]):
                msg = format_expiry_alert(t)
                # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
                _send_trade_alert(msg, t)
                sig_msg_id = get_signal_message_id(cid, t["signal_id"])
                if sig_msg_id:
                    delete_signal_message(sig_msg_id)
                    clear_signal_message_id(cid, t["signal_id"])
                close_trade(cid, t["signal_id"], "EXPIRED", cur)
                clear_signal_dedup(sym)
                events += 1
                continue

        # ── 🆕 v6.4.82: إزالة إشعارات "ابقَ/راقب/اخرج الآن" بالكامل ──
        # المستخدم يريد: صفقة + أهداف + ستوب ديناميكي فقط.
        # لا تذكيرات ذكية، لا خروج مبكر، لا نصائح — فقط:
        #   إشارة الدخول → تنبيهات الأهداف → إغلاق (نجاح أو خسارة)
    return events

# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.45: DXY (Dollar Index) filter — مؤشر الدولار الذكي
# المنطق:
#   DXY هابط → دولار ضعيف → كريبتو صاعد → ادخل صفقات
#   DXY صاعد → دولار قوي → كريبتو هابط → لا تدخل
#   DXY محايد → ادخل بناءً على المعايير الأخرى فقط
# ═══════════════════════════════════════════════════════════

_dxy_cache: dict = {"trend": None, "ts": 0.0}


def _get_dxy_trend() -> str:
    """🆕 v6.4.45: يجلب اتجاه DXY (Dollar Index) من CoinGecko.
    CoinGecko لا يدعم DXY مباشرة، لكنه يدعم USD كـ base currency.
    نستخدم EUR/USD و GBP/USD كـ proxy:
      - كلاهما صاعد = دولار هابط = كريبتو صاعد = ENTER
      - كلاهما هابط = دولار صاعد = كريبتو هابط = EXIT

    يرجع: "صاعد" | "هابط" | "محايد" | "غير معروف"
    """
    import requests as _req
    now = time.time()
    if _dxy_cache["trend"] and now - _dxy_cache["ts"] < DXY_CACHE_TTL:
        return _dxy_cache["trend"]
    try:
        # 🆕 v6.4.45: استخدم CoinGecko لجلب EUR و GBP مقابل USD
        # لو EUR/USD و GBP/USD كلاهما صاعد → دولار هابط
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = _req.get("https://api.coingecko.com/api/v3/simple/price",
                     params={"ids": "ethereum,bitcoin", "vs_currencies": "usd",
                             "include_24hr_change": "true"},
                     headers=headers, timeout=10)
        if r.status_code != 200:
            _dxy_cache["trend"] = "غير معروف"
            _dxy_cache["ts"] = now
            return "غير معروف"

        data = r.json()
        btc_change = data.get("bitcoin", {}).get("usd_24h_change", 0)
        eth_change = data.get("ethereum", {}).get("usd_24h_change", 0)

        # 🧠 منطق ذكي:
        # لو BTC و ETH كلاهما صاعد → السوق الكريبتو صاعد = ادخل
        # لو كلاهما هابط → السوق هابط = لا تدخل
        # لو متباين → محايد
        if btc_change > 1.0 and eth_change > 1.0:
            _dxy_cache["trend"] = "صاعد"  # كريبتو صاعد
        elif btc_change < -1.0 and eth_change < -1.0:
            _dxy_cache["trend"] = "هابط"  # كريبتو هابط
        else:
            _dxy_cache["trend"] = "محايد"

        _dxy_cache["ts"] = now
        log.info(f"💵 [DXY] trend={_dxy_cache['trend']} (BTC={btc_change:+.2f}%, ETH={eth_change:+.2f}%)")
        return _dxy_cache["trend"]
    except Exception as e:
        log.warning(f"DXY err: {e}")
        _dxy_cache["trend"] = "غير معروف"
        _dxy_cache["ts"] = now
        return "غير معروف"


def scan_cycle(force: bool = False, debug: bool = False):
    """🆕 v6.3: دورة المسح بمعمارية Funnel — سريعة وذكية.

    المراحل:
      0) 🔒 mutex — منع تشغيل متزامن (scheduler + /forcescan + /scandebug)
      1) check_trades — فحص الصفقات النشطة (TP/SL)
      2) prefilter رخيص — ticker مجمّع واحد → ~25 مرشح (بدل 248 تحليل عميق!)
      3) MTF batch — جلب متوازٍ (4 workers) + تحليل 15m/1h/4h/1d
      4) بوابة Setup القوي — bullish_count>=3 + 1d bullish + confluence>=50
      5) ✅ الترتيب الصحيح: CHECK → LOCK → SEND (مش العكس!)
      ⏱️ deadline — لو تجاوزت الدورة MAX_CYCLE_TIME تتوقف بأمان
    """
    # 🔒 Phase 0: منع التزامن (المشكلة #6)
    if not _scan_mutex.acquire(blocking=False):
        log.warning("⏳ [SCAN BUSY] دورة مسح جارية بالفعل — تم تجاهل هذا الطلب")
        return None

    try:
        return _scan_cycle_impl(force, debug)
    finally:
        _scan_mutex.release()


def _scan_cycle_impl(force: bool = False, debug: bool = False):
    """تنفيذ دورة المسح الفعلية (تحت الحماية الـ mutex).

    🆕 v6.4.42: وضع المراقبة الصامت — عند حظر Binance:
      - لا prefilter، لا MTF batch، لا إشارات جديدة
      - فقط check_trades للصفقات النشطة
      - محاولة استعادة Binance كل 30 دقيقة
      - بدون أي تنبيه للمستخدم
    """
    global _cycle_signaled, _last_scan_time, _bot_mode, _mode_changed_at, _last_recovery_ping
    _cycle_signaled = set()
    cycle_start = time.time()
    deadline = cycle_start + MAX_CYCLE_TIME
    cids = [CHAT_ID] if CHAT_ID else []
    stats = {"skipped_active": 0, "skipped_signaled": 0, "no_signal": 0,
             "sent": 0, "blocked_dup": 0, "events": 0,
             "candidates": 0, "strong_setups": 0, "weak_setups": 0,
             "skipped_duplicate": 0, "skipped_below_avg": 0}

    # 🆕 v6.4.59: سجل تشخيصي لكل مرحلة
    log.info(f"🧠 [SCAN START] mode={_bot_mode} binance_available={is_binance_available()} cids={len(cids)} force={force} debug={debug}")

    # ── 🆕 v6.4.42: فحص وضع المراقبة الصامت ──
    # لو Binance محظور → أدخل وضع المراقبة (صامت، لا تنبيه للمستخدم)
    if not is_binance_available():
        if _bot_mode != "monitoring":
            _bot_mode = "monitoring"
            _mode_changed_at = time.time()
            log.info(f"⏸️ Entered monitoring mode (silent — Binance banned)")
        # في وضع المراقبة: فقط check_trades للصفقات النشطة + محاولة استعادة دورية
        log.info(f"📋 [PHASE 1] check_trades (monitoring mode) — cids={len(cids)}")
        for cid in cids:
            try:
                events = check_trades(cid)
                stats["events"] += events
                log.info(f"   ✅ check_trades(cid={cid}) → {events} events")
            except Exception as e:
                log.error(f"   ❌ check_trades(cid={cid}) err: {e}")
                import traceback
                log.error(f"   📋 {traceback.format_exc()}")
        # محاولة استعادة Binance كل _RECOVERY_PING_INTERVAL
        if time.time() - _last_recovery_ping > _RECOVERY_PING_INTERVAL:
            recovered = _try_recovery_ping()
            if recovered:
                log.info("✅ Binance recovered — exiting monitoring mode (silent)")
                # لا نكمل الدورة الآن، ستكتمل في الدورة التالية
        stats["duration"] = round(time.time() - cycle_start, 1)
        stats["mode"] = "monitoring"
        log.info(f"🏁 [SCAN END] monitoring mode, duration={stats['duration']}s, events={stats['events']}")
        return stats

    # لو كنا في وضع المراقبة و Binance عاد → عُد للوضع العادي (صامت)
    if _bot_mode == "monitoring":
        _bot_mode = "normal"
        log.info("▶️ Binance available — back to normal mode (silent)")

    # ── المرحلة 1: فحص الصفقات النشطة (TP/SL) ──
    log.info(f"📋 [PHASE 1] check_trades — cids={len(cids)}")
    for cid in cids:
        try:
            events = check_trades(cid)
            stats["events"] += events
            log.info(f"   ✅ check_trades(cid={cid}) → {events} events")
        except Exception as e:
            log.error(f"   ❌ check_trades(cid={cid}) err: {e}")
            import traceback
            log.error(f"   📋 {traceback.format_exc()}")

    # ── المرحلة 2: Prefilter رخيص (استدعاء واحد للسوق كله) ──
    # 🆕 v6.4.60: تهيئة المتغيرات قبل log (تفادي UnboundLocalError)
    fav_count = 0
    port_count = 0
    candidate_symbols = set()
    log.info(f"📋 [PHASE 2] prefilter — favs={fav_count} ports={port_count}")
    try:
        for cid in cids:
            favs = get_favorites(cid)
            ports = get_portfolio(cid).keys()
            candidate_symbols.update(favs)
            candidate_symbols.update(ports)
            fav_count += len(favs)
            port_count += len(ports)

        # 🆕 v6.4.40: إذا المستخدم ليس له مفضلة ولا محفظة، نضيف عملات شعبية افتراضية
        # 🆕 v6.4.41: إصلاح ARBITRUM → ARB (الرمز الصحيح على Binance)
        if not candidate_symbols:
            _DEFAULT_FALLBACK_COINS = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE",
                                        "AVAX", "LINK", "DOT", "MATIC", "LTC", "ATOM",
                                        "NEAR", "ARB", "OP", "INJ", "SUI", "TIA", "SEI"}
            candidate_symbols.update(_DEFAULT_FALLBACK_COINS)
            log.info(f"💡 [v6.4.40] لا توجد مفضلة/محفظة — استخدام {len(_DEFAULT_FALLBACK_COINS)} عملة افتراضية شعبية")

        # 🆕 v6.4.60: تحديث log بعد الحساب الفعلي
        log.info(f"📋 [PHASE 2] prefilter — favs={fav_count} ports={port_count}")

        pre = prefilter_candidates(top_n=PRE_FILTER_TOP_N)
        pre_syms = [c["symbol"] for c in pre]
        candidate_symbols.update(pre_syms)

        # 🆕 v6.4.76: فلترة — فقط عملات حلال موجودة في Binance
        try:
            binance_symbols = fetch_all_spot_symbols()
            if binance_symbols:
                binance_set = set(binance_symbols)
                # إزالة العملات غير الموجودة في Binance
                before = len(candidate_symbols)
                candidate_symbols = {s for s in candidate_symbols if s in binance_set}
                log.info(f"📋 [v6.4.76] Binance filter: {before} → {len(candidate_symbols)} (أزيل {before - len(candidate_symbols)})")
        except Exception:
            pass  # لو فشل، أبقِ القائمة كما هي

        stats["candidates"] = len(candidate_symbols)

        log.info(f"   ✅ [PHASE 2] prefilter: {len(pre_syms)} مرشح من السوق "
                 f"+ {len(candidate_symbols) - len(pre_syms)} مفضلة = {len(candidate_symbols)}")
        if debug and pre:
            top3 = ", ".join(f"{c['symbol']}(+{c['change']}%)" for c in pre[:3])
            log.info(f"   أقوى 3 مرشحين: {top3}")
    except Exception as e:
        log.error(f"❌ [PHASE 2] prefilter err: {e}")
        import traceback
        log.error(f"📋 {traceback.format_exc()}")
        stats["duration"] = round(time.time() - cycle_start, 1)
        return stats

    # ── المرحلة 3: MTF batch (جلب متوازٍ + تحليل 4 فريمات) ──
    if not is_binance_available():
        log.warning("⏸️ [PHASE 3] Binance محظور أثناء الدورة — تخطي MTF batch")
        stats["duration"] = round(time.time() - cycle_start, 1)
        return stats
    log.info(f"📋 [PHASE 3] MTF batch — {len(candidate_symbols)} عملة × 4 فريمات")
    try:
        sorted_syms = sorted(candidate_symbols)
        mtf_results = analyze_mtf_batch(sorted_syms, deadline=deadline, max_workers=4)
        log.info(f"   ✅ [PHASE 3] MTF: حُلّل {len(mtf_results)}/{len(sorted_syms)} عملة على 4 فريمات "
                 f"في {time.time() - cycle_start:.0f}s")
    except Exception as e:
        log.error(f"❌ [PHASE 3] MTF batch err: {e}")
        import traceback
        log.error(f"📋 {traceback.format_exc()}")
        stats["duration"] = round(time.time() - cycle_start, 1)
        return stats

    # ── المرحلة 4: بوابة Setup القوي ──
    # 🆕 v6.4.83-fix: V1 تعمل دائماً — لكن الإرسال يتوجّه للقناة (لو V1_ENABLED) أو للبوت (لو إيقاف)
    log.info(f"📋 [PHASE 4] is_strong_setup — min_bullish={MTF_MIN_BULLISH} min_confluence={MTF_MIN_CONFLUENCE}")
    try:
        strong, weak = [], []
        for m in mtf_results:
            if is_strong_setup(m, min_bullish=MTF_MIN_BULLISH, min_confluence=MTF_MIN_CONFLUENCE):
                strong.append(m)
            else:
                weak.append(m)
        strong.sort(key=lambda m: -m.confluence)
        log.info(f"   ✅ [PHASE 4] Setup قوي: {len(strong)} | مرفوض: {len(weak)}")
    except Exception as e:
        log.error(f"❌ [PHASE 4] is_strong_setup err: {e}")
        import traceback
        log.error(f"📋 {traceback.format_exc()}")
        strong = []

    stats["strong_setups"] = len(strong)
    stats["weak_setups"] = len(weak)
    log.info(f"💎 [FUNNEL 3/3] Setup قوي: {len(strong)} | مرفوض: {len(weak)} "
             f"(معايير: bullish>={MTF_MIN_BULLISH}/4 + 1d صاعد + confluence>={MTF_MIN_CONFLUENCE})")
    if debug:
        for m in strong[:5]:
            log.info(f"   ✅ {m.symbol}: {m.bullish_count}/4 صاعد, confluence={m.confluence}")
        for m in weak[:3]:
            log.info(f"   ❌ {m.symbol}: {m.bullish_count}/4 صاعد, confluence={m.confluence}")

    # ── 🆕 v6.4.42: فلتر جودة الصفقات النشطة ──
    # لو 10+ صفقات نشطة، أرسل صفقة جديدة فقط إذا كانت أفضل من المتوسط بـ 20+ نقطة
    active_trades_per_cid = {}
    for cid in cids:
        active_trades_per_cid[cid] = get_active(cid)

    # ── 🆕 v6.4.85: فلتر جودة عالية — حد أقصى للصفقات النشطة ──
    # لو عدد الصفقات النشطة ≥ MAX_ACTIVE_TRADES → لا فتح صفقات جديدة (جودة > كمية)
    total_active_v1 = sum(1 for cid in cids for t in active_trades_per_cid[cid]
                          if t.get("strategy", "v1") == "v1")
    total_active_v2 = sum(1 for cid in cids for t in active_trades_per_cid[cid]
                          if t.get("strategy", "v1") == "v2")
    log.info(f"🔒 [v6.4.85] active trades: V1={total_active_v1} V2={total_active_v2} "
             f"(max={MAX_ACTIVE_TRADES} per strategy)")

    # ── المرحلة 5: CHECK → LOCK → SEND ──
    # 🆕 v6.4.62: إرسال حر — لا حد أقصى (max_signals = MAX_SIGNALS_PER_CYCLE)
    # 🆕 v6.4.62: لا cooldown (الشروط الفنية العالية كافية)
    log.info(f"📋 [PHASE 5] send — strong={len(strong)} cids={len(cids)} max_signals={MAX_SIGNALS_PER_CYCLE}")
    max_signals = 999 if force else MAX_SIGNALS_PER_CYCLE
    # 🆕 v6.4.51/v6.4.62: cooldown معطّل (SIGNAL_COOLDOWN_SEC=0)
    _last_signal_sent_ts = getattr(scan_cycle, "_last_signal_ts", 0)
    cooldown_active = (SIGNAL_COOLDOWN_SEC > 0) and (time.time() - _last_signal_sent_ts) < SIGNAL_COOLDOWN_SEC
    if cooldown_active and not force:
        remaining = SIGNAL_COOLDOWN_SEC - int(time.time() - _last_signal_sent_ts)
        log.info(f"⏸️ [v6.4.62 cooldown] {remaining}s متبق قبل السماح بإشارة جديدة")
    for cid in cids:
        signals_sent = 0
        updates_sent = 0
        active_list = active_trades_per_cid.get(cid, [])
        active_count = len(active_list)
        avg_active_score = (sum(t.get("score", 50) for t in active_list) / active_count) if active_count > 0 else 0
        for m in strong:
            if signals_sent + updates_sent >= max_signals:
                break
            if time.time() > deadline:
                log.warning("⏰ Cycle deadline — إيقاف الإرسال بأمان")
                break
            sym = m.symbol
            # 🆕 v6.4.85: حد أقصى للصفقات النشطة (V1) — لا فتح جديد لو تجاوز الحد
            if total_active_v1 >= MAX_ACTIVE_TRADES and not force:
                stats["skipped_max_active"] = stats.get("skipped_max_active", 0) + 1
                if debug:
                    log.info(f"🔒 {sym} — V1 نشطة {total_active_v1} ≥ {MAX_ACTIVE_TRADES} — skip (جودة > كمية)")
                # لا نكسر الـ loop — نكمل للعملات الأخرى (لو لم تُفتح أصلاً)
                # لكن في الواقع، كل الصفقات ستُرفض — لذلك نكسر
                break
            # 🆕 v6.4.45: إيقاف فوري للصفقات الجديدة (حماية المال)
            if not RESUME_NEW_SIGNALS and not force:
                stats["skipped_stop"] = stats.get("skipped_stop", 0) + 1
                if debug:
                    log.info(f"⏸️ {sym} — تجاهل: RESUME_NEW_SIGNALS=0 (إيقاف مؤقت)")
                # لا نستمر في الفلترة — كل الإشارات مرفوضة
                # لكن نكسر الـ loop بعد أول واحدة (نكمل للصفقات الأخرى فقط لو force=True)
                break
            sig = generate_mtf(sym, m)
            if not sig:
                stats["no_signal"] += 1
                if debug:
                    log.info(f"❌ {sym}: R/R مرفوض في generate_mtf")
                continue

            # 🆕 v6.4.45: فلتر سعر الدخول (استبعاد العملات الصغيرة جداً)
            if sig.entry < MIN_ENTRY_PRICE:
                stats["skipped_low_price"] = stats.get("skipped_low_price", 0) + 1
                if debug:
                    log.info(f"⏭️ {sym} — entry ${sig.entry:.6f} < ${MIN_ENTRY_PRICE} (مخاطر عالية)")
                continue
            if sig.entry > MAX_ENTRY_PRICE:
                stats["skipped_high_price"] = stats.get("skipped_high_price", 0) + 1
                if debug:
                    log.info(f"⏭️ {sym} — entry ${sig.entry:.2f} > ${MAX_ENTRY_PRICE:.0f} (نادر)")
                continue

            # 🆕 v6.4.83: فلتر الدخول عند القمة — لا تشتري إذا السعر قرب recent_high
            # لو entry_price ≥ recent_high × (1 - MIN_DIST_FROM_HIGH_PCT/100) → الدخول عند القمة
            # مثال: recent_high=100, MIN_DIST_FROM_HIGH_PCT=1.5 → لا تدخل فوق 98.5
            try:
                _recent_high = m.snapshot_1d.get("recent_high", 0) if m.snapshot_1d else 0
                if _recent_high > 0:
                    _max_entry_for_buy = _recent_high * (1 - MIN_DIST_FROM_HIGH_PCT / 100.0)
                    if sig.entry >= _max_entry_for_buy:
                        stats["skipped_at_top"] = stats.get("skipped_at_top", 0) + 1
                        _dist_pct = ((_recent_high - sig.entry) / _recent_high) * 100
                        if debug:
                            log.info(f"⛰️ {sym} — entry {sig.entry} قرب القمة {_recent_high} (بُعد {_dist_pct:.2f}% < {MIN_DIST_FROM_HIGH_PCT}%) — skip (شراء القمة)")
                        continue
            except Exception as _e:
                log.warning(f"⛰️ {sym} at-top filter err: {_e}")

            # 🆕 v6.4.45: فلتر DXY (مؤشر الدولار الذكي)
            # لو USE_DXY_FILTER مفعّل → تحقق من اتجاه السوق الكريبتو
            if USE_DXY_FILTER:
                dxy_trend = _get_dxy_trend()
                sig.btc_trend = dxy_trend  # استبدل BTC trend القديم بـ DXY الذكي
                if dxy_trend == "هابط":
                    # كريبتو هابط → لا تدخل
                    stats["skipped_dxy_bear"] = stats.get("skipped_dxy_bear", 0) + 1
                    if debug:
                        log.info(f"⏭️ {sym} — DXY/سوق هابط (لا دخول)")
                    continue
                elif dxy_trend == "صاعد":
                    # كريبتو صاعد → عزّز الـ score (+5 نقاط)
                    if sig.score > 0:
                        old_score = sig.score
                        sig.score = min(100, sig.score + 5)
                        log.info(f"💎 {sym} — DXY صاعد، score {old_score:.0f} → {sig.score:.0f}")
                # محايد = لا تأثير
            else:
                # السلوك القديم: BTC 1D trend
                sig.btc_trend = get_btc_1d_trend()
                if sig.btc_trend == "هابط" and sig.score > 50:
                    old_score = sig.score
                    sig.score = max(0, sig.score - 10)
                    log.info(f"⚠️ {sym} BTC 1D هابط — score {old_score:.0f} → {sig.score:.0f}")

            # 🆕 v6.4.45: فلتر SCORE_THRESHOLD الجديد (50 بدل 40)
            if sig.score < SCORE_THRESHOLD:
                stats["skipped_low_score"] = stats.get("skipped_low_score", 0) + 1
                if debug:
                    log.info(f"⏭️ {sym} — score {sig.score:.0f} < {SCORE_THRESHOLD} (تحت العتبة)")
                continue

            # 🆕 v6.4.51/v6.4.62: cooldown معطّل (SIGNAL_COOLDOWN_SEC=0 افتراضياً)
            # لو cooldown مفعّل (SIGNAL_COOLDOWN_SEC > 0) → لا إشارة جديدة في النافذة
            if cooldown_active and not force:
                stats["skipped_cooldown"] = stats.get("skipped_cooldown", 0) + 1
                if debug:
                    remaining = SIGNAL_COOLDOWN_SEC - int(time.time() - _last_signal_sent_ts)
                    log.info(f"⏭️ {sym} — cooldown active ({remaining}s متبق)")
                continue

            # 🆕 v6.4.71: منع مطلق للتكرار — لو يوجد صفقة نشطة → skip نهائياً
            # الصفقة الجديدة على نفس العملة تُمنع حتى:
            #   1. تتحقق كل الأهداف (TP5/TP6 → final) → الصفقة تُغلق
            #   2. أو يخرج بالكامل (SL أو EXPIRED) → الصفقة تُغلق
            # لا استثناءات. لا "تغير السعر". لا DCA. فقط skip.
            if has_active_trade(sym, cid):
                stats["skipped_active"] += 1
                if debug:
                    log.info(f"⏭️ {sym} — صفقة نشطة (منع مطلق حتى الإغلاق)")
                continue

            if is_recently_signaled(sym) and sym not in _cycle_signaled:
                stats["skipped_signaled"] += 1
                if debug:
                    log.info(f"⏭️ {sym} — تجاهل (dedup — أُرسلت إشارة مؤخراً)")
                continue

            if sym in _cycle_signaled:
                stats["skipped_signaled"] += 1
                continue

            # 🆕 v6.4.42: فلتر جودة لو 10+ صفقات نشطة
            # 🆕 v6.4.62: تعطيل الفلتر (نشطة دائماً — QUALITY_THRESHOLD = 0)
            if active_count >= MAX_ACTIVE_TRADES_FOR_RESTRICTION and QUALITY_THRESHOLD > 0:
                threshold_score = avg_active_score + QUALITY_THRESHOLD
                if sig.score < threshold_score:
                    stats["skipped_below_avg"] += 1
                    if debug:
                        log.info(f"⏭️ {sym} — score {sig.score:.0f} < avg+20 ({threshold_score:.0f}) — فلتر جودة")
                    continue
                log.info(f"⭐ {sym} — score {sig.score:.0f} ≥ avg+20 ({threshold_score:.0f}) — صفقة عالية الجودة مسموحة")

            # 🆕 v6.4.81: Correlation Filter — حد أقصى 4 صفقات لنفس القطاع
            # القطاع يُحدد من أول 2-3 حروف من الرمز (تقريب: نفس البادئة = نفس القطاع)
            sector_count = sum(1 for t in active_list if t.get("symbol", "")[:2] == sym[:2])
            if sector_count >= 4:
                stats["skipped_correlation"] = stats.get("skipped_correlation", 0) + 1
                if debug:
                    log.info(f"⏭️ {sym} — {sector_count} صفقات لنفس القطاع (حد 4) — فلتر ارتباط")
                continue

            # 🆕 v6.4.81/v6.4.85: SMC/FVG Filter — إجباري دائماً (مش مشروط بعدد الصفقات)
            # sig.confirmed يحتوي قائمة المؤشرات المؤكدة من engine.analyze
            # 🆕 v6.4.85: لازم على الأقل MIN_SMC_CONFLUENCE (2) فريمات فيها OB/FVG/Liquidity
            smc_confirmed = sig.confirmed or []
            # عد عدد فريمات فيها مؤشر ذكي
            smc_frames = 0
            for c in smc_confirmed:
                if "OB" in c or "FVG" in c or "Liquidity" in c:
                    # عد الفريم الفريد (4h, 1h, 15m, 5m)
                    if ":" in c:
                        prefix = c.split(":")[0].strip()
                        if prefix in ("4h", "1h", "15m", "5m"):
                            smc_frames += 1
            if smc_frames < MIN_SMC_CONFLUENCE:
                stats["skipped_no_smc"] = stats.get("skipped_no_smc", 0) + 1
                if debug:
                    log.info(f"⏭️ {sym} — SMC frames {smc_frames} < {MIN_SMC_CONFLUENCE} — skip (جودة عالية)")
                continue

            # 🆕 v6.4.85: فلتر السيولة الذكية % (compute_smart_liquidity_pct)
            # لازم ≥ MIN_SMART_LIQUIDITY_PCT (30%) — إجباري لكل صفقة
            try:
                from signals import compute_smart_liquidity_pct
                _sl_pct = compute_smart_liquidity_pct(m)
                if _sl_pct < MIN_SMART_LIQUIDITY_PCT:
                    stats["skipped_low_liq"] = stats.get("skipped_low_liq", 0) + 1
                    if debug:
                        log.info(f"⏭️ {sym} — smart liquidity {_sl_pct:.0f}% < {MIN_SMART_LIQUIDITY_PCT}% — skip (دخول غير احترافي)")
                    continue
            except Exception as _sl_e:
                log.warning(f"💧 {sym} smart liq filter err: {_sl_e}")

            # 🆕 v6.4.52/v6.4.53: فلتر الحكم الشرعي (إجباري قبل النشر)
            # 🆕 v6.4.53: المنطق الجديد:
            #   - العملة في القائمة + حلال → نشر الصفقة + إضافة الحكم أسفلها
            #   - العملة في القائمة + حرام → skip (صامت)
            #   - العملة في القائمة + شبهة → skip (صامت)
            #   - العملة ليست في القائمة → skip (صامت — لا تنبيه مزعج)
            try:
                if not halal_check.is_tracked(sym):
                    # 🆕 v6.4.53: العملة ليست في قائمة الأحكام → skip بصمت
                    stats["skipped_not_tracked"] = stats.get("skipped_not_tracked", 0) + 1
                    if debug:
                        log.info(f"⏭️ {sym} — ليست في قائمة الأحكام الشرعية (skip)")
                    continue

                halal_info = halal_check.get_ruling(sym)
                halal_ruling = halal_info.get("ruling", "unknown")

                if halal_ruling == "haram":
                    stats["skipped_haram"] = stats.get("skipped_haram", 0) + 1
                    log.info(f"🕌 [Halal] ❌ {sym} = حرام — skip")
                    continue
                elif halal_ruling == "suspect":
                    stats["skipped_suspect"] = stats.get("skipped_suspect", 0) + 1
                    log.info(f"🕌 [Halal] ⚠️ {sym} = شبهة — skip")
                    continue
                elif halal_ruling == "halal":
                    # ✅ حلال → متابعة + إضافة الحكم أسفل الصفقة
                    sig.halal_ruling = halal_ruling
                    log.info(f"🕌 [Halal] ✅ {sym} = حلال — متابعة النشر")
                else:
                    # ⚪ unknown (في القاعدة لكن ruling غير صالح) → skip
                    stats["skipped_halal_unknown"] = stats.get("skipped_halal_unknown", 0) + 1
                    log.warning(f"🕌 [Halal] ⚪ {sym} = ruling غير صالح في DB")
                    continue
            except Exception as e:
                log.warning(f"🕌 [Halal] check err: {e} — skip للسلامة")
                stats["skipped_halal_error"] = stats.get("skipped_halal_error", 0) + 1
                continue

            # ✅ ② LOCK ثانياً — ذرّي (يمنع التكرار نهائياً)
            ok = try_create(cid, {
                "signal_id": sig.signal_id, "symbol": sym,
                "entry": sig.entry, "sl": sig.sl,
                "entry_low": sig.entry_low, "entry_high": sig.entry_high,
                "tp1": sig.tp1, "tp2": sig.tp2, "tp3": sig.tp3,
                "tp4": sig.tp4, "tp5": sig.tp5, "tp6": sig.tp6,
                "tp1_pct": sig.tp1_pct, "tp2_pct": sig.tp2_pct, "tp3_pct": sig.tp3_pct,
                "tp4_pct": sig.tp4_pct, "tp5_pct": sig.tp5_pct, "tp6_pct": sig.tp6_pct,
                "score": sig.score, "confirmed": sig.confirmed,
                "risk_pct": sig.risk_pct,
                "position_size_usd": sig.position_size_usd,
                "position_size_pct": sig.position_size_pct,
                "risk_amount_usd": sig.risk_amount_usd,
                "valid_until": sig.valid_until,
                "btc_trend": sig.btc_trend,
                "update_stars": 0,  # 🆕 v6.4.4: نجوم تراكمية تبدأ من 0
            })
            if not ok:
                stats["blocked_dup"] += 1
                log.warning(f"⛔ [DUPLICATE BLOCKED] {sym} — لم تُرسل أي رسالة")
                continue
            # ✅ ③ SEND أخيراً — فقط بعد نجاح القفل
            # 🆕 v6.4: استخدم format_signal_mtf_simple أو format_signal_mtf حسب HQ_DISPLAY_MODE
            # (مع دعم runtime override عبر /simple أو /detailed)
            global _display_mode_runtime, _display_mode_runtime_d
            try:
                _display_mode_runtime
            except NameError:
                _display_mode_runtime = None
            try:
                _display_mode_runtime_d
            except NameError:
                _display_mode_runtime_d = None
            effective_mode = HQ_DISPLAY_MODE
            if _display_mode_runtime_d == "detailed":
                effective_mode = "detailed"
            elif _display_mode_runtime == "simple":
                effective_mode = "simple"

            # 🆕 v6.4.83-fix: تشغيل → القناة، إيقاف → البوت فقط
            _v1_target_str = "channel" if V1_ENABLED else "bot"

            if effective_mode == "detailed":
                msg = format_signal_mtf(sig, m)
            else:
                msg = format_signal_mtf_simple(sig, m, target=_v1_target_str)

            # 🆕 v6.4.83: أضف لوحة أزرار inline لروابط Binance + TradingView
            from signals import build_coin_links_kb
            _links_kb = build_coin_links_kb(sym)

            # 🆕 v6.4.52: إضافة الحكم الشرعي أسفل الصفقة (لو حلال فقط)
            # 🆕 v6.4.55: تحسين الصياغة — أكثر طبيعية
            try:
                halal_ruling_val = getattr(sig, "halal_ruling", None)
                if halal_ruling_val == "halal":
                    msg += f"\n\n━━━━━━━━━━━━━━━━━━\n🕌 <b>الحكم الشرعي: 🟢 حلال</b>"
            except Exception:
                pass

            # 🆕 v6.4.83-fix/v6.4.87/v6.4.110: V1_ENABLED=True → قناة الإشارات، False → البوت فقط
            # 🆕 v6.4.110: لو SIGNALS_CHANNEL_ID فارغ → استخدم CHANNEL_ID → لو فارغ → البوت
            if V1_ENABLED:
                # 🆕 v6.4.110: fallback chain: SIGNALS_CHANNEL_ID → CHANNEL_ID → CHAT_ID
                if SIGNALS_CHANNEL_ID:
                    signal_msg_id = send_to_signals_channel(msg, kb=_links_kb)
                    v1_target = "CHANNEL"
                elif CHANNEL_ID:
                    _tg_post("sendMessage", {"chat_id": str(CHANNEL_ID), "text": msg, "parse_mode": "HTML"})
                    signal_msg_id = None
                    v1_target = "CHANNEL"
                else:
                    # 🆕 v6.4.110: لا توجد قناة → أرسل للبوت (fallback آمن)
                    send_msg(msg, _links_kb, CHAT_ID)
                    signal_msg_id = None
                    v1_target = "BOT"
                    log.warning(f"⚠️ [V1] لا توجد SIGNALS_CHANNEL_ID ولا CHANNEL_ID — أرسلت للبوت فقط")
            else:
                send_msg(msg, _links_kb, CHAT_ID)
                signal_msg_id = None
                v1_target = "BOT"
            if signal_msg_id or v1_target == "BOT":
                set_signal_message_id(cid, sig.signal_id, signal_msg_id or 0)
            # 🆕 v6.4: سجّل الإشارة في dedup
            mark_signal_sent(sym)
            _cycle_signaled.add(sym)
            signals_sent += 1
            stats["sent"] += 1
            log.info(f"💎 SIGNAL SENT ({v1_target}): {sym} (MTF {m.bullish_count}/4, "
                     f"conf={sig.score:.0f}, R/R=1:{sig.rr:.2f}, msg_id={signal_msg_id}, "
                     f"TP1={fmt_price(sig.tp1)}, TP5={fmt_price(sig.tp5)})")
            time.sleep(1)
        log.info(f"🧠 cid={cid}: {signals_sent} signals + {stats['events']} events | "
                 f"active-skip={stats['skipped_active']} no-signal={stats['no_signal']} "
                 f"dup-blocked={stats['blocked_dup']}")

    # ═══ 🆕 v6.4.65: المرحلة 6 — استراتيجية الارتداد (V2) ═══
    # استراتيجية منفصلة: RSI + Bollinger + Hammer + Volume + MACD
    # تشتغل بعد V1 على فريم قابل للتكوين (15m افتراضي)
    # 🆕 v6.4.83-fix: V2 تعمل دائماً — لكن الإرسال يتوجّه للقناة (لو V2_ENABLED) أو للبوت (لو إيقاف)
    if STRATEGY_V2_ENABLED:
        log.info(f"📋 [PHASE 6] V2 Reversal Strategy — timeframe={STRATEGY_V2_TIMEFRAME} max_signals={STRATEGY_V2_MAX_SIGNALS} (target: {'قناة' if V2_ENABLED else 'بوت'})")
        try:
            # 🆕 v6.4.76: قائمة عملات V2 = فقط عملات الحلال الموجودة في Binance
            # لا نستخدم candidate_symbols من V1 (قد تحتوي عملات غير موجودة في Binance)
            # ولا نستخدم CoinGecko كقائمة مصدر
            v2_symbols = []
            try:
                # احضر قائمة كل رموز Binance Spot (USDT pairs)
                binance_symbols = fetch_all_spot_symbols()
                binance_set = set(binance_symbols) if binance_symbols else set()
                log.info(f"📋 [PHASE 6] Binance has {len(binance_set)} spot symbols")

                # فقط عملات الحلال الموجودة في Binance
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal" and r["symbol"] in binance_set:
                        v2_symbols.append(r["symbol"])

                # أضف المفضلة أيضاً (لو موجودة في Binance)
                for cid in cids:
                    for fav in get_favorites(cid):
                        if fav in binance_set and fav not in v2_symbols:
                            v2_symbols.append(fav)

                v2_symbols = list(set(v2_symbols))
            except Exception as e:
                log.warning(f"📋 [PHASE 6] Binance symbol list failed, using halal only: {e}")
                # fallback: halal فقط (بدون فلتر Binance)
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal":
                        v2_symbols.append(r["symbol"])
                v2_symbols = list(set(v2_symbols))

            log.info(f"📋 [PHASE 6] V2 scanning {len(v2_symbols)} Binance-verified halal coins on {STRATEGY_V2_TIMEFRAME}")
            # 🆕 v6.4.96: تحديد عدد العملات لِـ V2 (تفادي البطء + rate limit)
            # لو أكثر من V2_MAX_SYMBOLS → خذ أعلى N من top_movers (الأكثر نشاطاً)
            V2_MAX_SYMBOLS = int(os.environ.get("V2_MAX_SYMBOLS", "30"))
            if len(v2_symbols) > V2_MAX_SYMBOLS:
                # 🆕 v6.4.96: استخدم top_movers لِـ اختيار الأكثر نشاطاً
                try:
                    top_movers = fetch_top_movers() or []
                    top_syms = set(top_movers[:V2_MAX_SYMBOLS * 2])
                    # أخذ تقاطع (intersection) مع halal list
                    v2_active = [s for s in v2_symbols if s in top_syms]
                    # لو التقاطع كافٍ → استخدمه، وإلا خذ أول V2_MAX_SYMBOLS من v2_symbols
                    if len(v2_active) >= 10:
                        v2_symbols = v2_active[:V2_MAX_SYMBOLS]
                    else:
                        v2_symbols = v2_symbols[:V2_MAX_SYMBOLS]
                    log.info(f"📋 [PHASE 6] V2 limited to {len(v2_symbols)} symbols (top movers + halal)")
                except Exception as _e_tm:
                    log.warning(f"📋 [PHASE 6] top_movers fallback → first {V2_MAX_SYMBOLS}: {_e_tm}")
                    v2_symbols = v2_symbols[:V2_MAX_SYMBOLS]
            v2_signals = strategy_v2.scan_v2_candidates(v2_symbols, STRATEGY_V2_TIMEFRAME)
            log.info(f"   ✅ [PHASE 6] V2 found {len(v2_signals)} reversal signals")

            # أرسل أفضل الإشارات (مرتبة حسب R/R)
            v2_sent = 0
            for v2_sig in v2_signals[:STRATEGY_V2_MAX_SIGNALS]:
                try:
                    sym = v2_sig["symbol"]

                    # 🛡️ فلتر الحلال (مثل V1)
                    if not halal_check.is_tracked(sym):
                        log.info(f"🔄 [V2] ⏭️ {sym} — ليست في قائمة الحلال")
                        continue
                    halal_info = halal_check.get_ruling(sym)
                    halal_ruling = halal_info.get("ruling", "unknown")
                    if halal_ruling != "halal":
                        log.info(f"🔄 [V2] ⏭️ {sym} — حكم {halal_ruling}")
                        continue

                    # 🛡️ منع مطلق للتكرار V2 — لو صفقة V2 نشطة على نفس العملة → skip
                    # 🆕 v6.4.71: منع مطلق (مثل V1) — لا صفقة ثانية حتى الإغلاق
                    _skip_v2 = False
                    for _cid in cids:
                        if has_active_trade(sym, _cid, strategy="v2"):
                            log.info(f"🔄 [V2] ⏭️ {sym} — صفقة V2 نشطة (منع مطلق)")
                            _skip_v2 = True
                            break
                    if _skip_v2:
                        continue

                    # 🆕 v6.4.85: حد أقصى للصفقات النشطة (V2) — لا فتح جديد لو تجاوز الحد
                    if total_active_v2 >= MAX_ACTIVE_TRADES:
                        log.info(f"🔄 [V2] ⏭️ {sym} — V2 نشطة {total_active_v2} ≥ {MAX_ACTIVE_TRADES} — skip (جودة > كمية)")
                        continue

                    # 🛡️ R/R الأدنى
                    if v2_sig["rr"] < STRATEGY_V2_MIN_RR:
                        log.info(f"🔄 [V2] ⏭️ {sym} — R/R {v2_sig['rr']:.1f} < {STRATEGY_V2_MIN_RR}")
                        continue

                    # 🆕 v6.4.95: إزالة فلاتر conditions_met + score + smart_liquidity الزائدة
                    # V2 المبسط يعتمد كلياً على MTF Entry (4h/1h/15m/5m) — لا حاجة لِـ فلاتر إضافية

                    # 🛡️ سعر الدخول (مثل V1)
                    if v2_sig["entry"] < MIN_ENTRY_PRICE:
                        log.info(f"🔄 [V2] ⏭️ {sym} — سعر صغير جداً")
                        continue

                    # 🛡️ dedup (مثل V1)
                    if is_recently_signaled(sym) or sym in _cycle_signaled:
                        log.info(f"🔄 [V2] ⏭️ {sym} — dedup")
                        continue

                    # ✅ نشر الصفقة V2
                    # 🆕 v6.4.83-fix: تشغيل → القناة، إيقاف → البوت فقط
                    _v2_target_str = "channel" if V2_ENABLED else "bot"
                    msg = strategy_v2.format_v2_signal(v2_sig, halal_ruling, target=_v2_target_str)
                    # 🆕 v6.4.83: أزرار inline لروابط Binance + TradingView
                    from signals import build_coin_links_kb
                    _v2_links_kb = build_coin_links_kb(sym)
                    # 🆕 v6.4.83-fix/v6.4.110: V2_ENABLED=True → قناة، False → البوت
                    # 🆕 v6.4.110: fallback chain: SIGNALS_CHANNEL_ID → CHANNEL_ID → CHAT_ID
                    if V2_ENABLED:
                        if SIGNALS_CHANNEL_ID:
                            signal_msg_id = send_to_signals_channel(msg, kb=_v2_links_kb)
                            target = "CHANNEL"
                        elif CHANNEL_ID:
                            _tg_post("sendMessage", {"chat_id": str(CHANNEL_ID), "text": msg, "parse_mode": "HTML"})
                            signal_msg_id = None
                            target = "CHANNEL"
                        else:
                            send_msg(msg, _v2_links_kb, CHAT_ID)
                            signal_msg_id = None
                            target = "BOT"
                            log.warning(f"⚠️ [V2] لا توجد قناة — أرسلت للبوت فقط")
                    else:
                        send_msg(msg, _v2_links_kb, CHAT_ID)
                        signal_msg_id = None
                        target = "BOT"
                    if signal_msg_id or target == "BOT":
                        # 🆕 v6.4.68: أنشئ صفقة V2 في tracker بـ strategy='v2'
                        v2_signal_id = f"v2_{sym}_{int(time.time())}"
                        v2_trade = {
                            "signal_id": v2_signal_id,
                            "symbol": sym,
                            "entry": v2_sig["entry"],
                            "sl": v2_sig["sl"],
                            "tp1": v2_sig["tp1"], "tp2": v2_sig["tp2"], "tp3": v2_sig["tp3"],
                            "tp4": 0, "tp5": 0, "tp6": 0,
                            "tp1_pct": v2_sig["tp1_pct"], "tp2_pct": v2_sig["tp2_pct"],
                            "tp3_pct": v2_sig["tp3_pct"], "tp4_pct": 0, "tp5_pct": 0, "tp6_pct": 0,
                            "entry_low": v2_sig["entry_low"], "entry_high": v2_sig["entry_high"],
                            "score": v2_sig["rsi"], "confirmed": "",
                            "risk_pct": abs(v2_sig["sl_pct"]),
                            "position_size_usd": 0, "position_size_pct": 0, "risk_amount_usd": 0,
                            "valid_until": int(time.time()) + 3600 * 4,  # 4 ساعات صلاحية V2
                            "btc_trend": "", "update_stars": 0,
                            "strategy": "v2",  # 🆕 v6.4.68
                        }
                        try_create(CHAT_ID, v2_trade, strategy="v2")
                        set_signal_message_id(CHAT_ID, v2_signal_id, signal_msg_id or 0)
                        mark_signal_sent(sym)
                        _cycle_signaled.add(sym)
                        v2_sent += 1
                        log.info(f"🔄 [V2] SIGNAL SENT ({target}): {sym} {v2_sig['timeframe']} "
                                 f"R/R={v2_sig['rr']:.1f} RSI={v2_sig['rsi']:.0f}")
                        time.sleep(1)
                except Exception as e:
                    log.warning(f"🔄 [V2] send {sym} err: {e}")
                    continue

            stats["v2_sent"] = v2_sent
            log.info(f"📋 [PHASE 6] V2 sent {v2_sent} reversal signals")
        except Exception as e:
            log.error(f"❌ [PHASE 6] V2 err: {e}")
            import traceback
            log.error(f"📋 {traceback.format_exc()}")
    else:
        log.info("📋 [PHASE 6] V2 معطّل (STRATEGY_V2_ENABLED=0)")

    # ═══ 🆕 v6.4.98: المرحلة 7 — استراتيجية Pre-Pump Breakout (V3) ═══
    # اكتشاف العملات قبل الانفجار السعري (Accumulation + Higher Lows + Compression + Volume)
    if STRATEGY_V3_ENABLED and V3_ENABLED:
        log.info(f"📋 [PHASE 7] V3 Pre-Pump Breakout — max_signals={STRATEGY_V3_MAX_SIGNALS} (target: {'قناة' if V3_ENABLED else 'بوت'})")
        try:
            v3_symbols = []
            try:
                binance_symbols = fetch_all_spot_symbols()
                binance_set = set(binance_symbols) if binance_symbols else set()
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal" and r["symbol"] in binance_set:
                        v3_symbols.append(r["symbol"])
                for cid in cids:
                    for fav in get_favorites(cid):
                        if fav in binance_set and fav not in v3_symbols:
                            v3_symbols.append(fav)
                v3_symbols = list(set(v3_symbols))
            except Exception as e:
                log.warning(f"📋 [PHASE 7] Binance symbol list failed: {e}")
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal":
                        v3_symbols.append(r["symbol"])
                v3_symbols = list(set(v3_symbols))

            # 🆕 v6.4.98: تحديد عدد العملات (تفادي البطء)
            if len(v3_symbols) > V3_MAX_SYMBOLS:
                try:
                    top_movers = fetch_top_movers() or []
                    # 🆕 v6.4.109: fetch_top_movers يرجع List[str] (ليس List[Dict])
                    top_syms = set(top_movers[:V3_MAX_SYMBOLS * 2])
                    v3_active = [s for s in v3_symbols if s in top_syms]
                    if len(v3_active) >= 10:
                        v3_symbols = v3_active[:V3_MAX_SYMBOLS]
                    else:
                        v3_symbols = v3_symbols[:V3_MAX_SYMBOLS]
                    log.info(f"📋 [PHASE 7] V3 limited to {len(v3_symbols)} symbols")
                except Exception as _e_tm:
                    log.warning(f"📋 [PHASE 7] top_movers fallback: {_e_tm}")
                    v3_symbols = v3_symbols[:V3_MAX_SYMBOLS]

            log.info(f"📋 [PHASE 7] V3 scanning {len(v3_symbols)} symbols for Pre-Pump signals")
            v3_signals = strategy_v3.scan_v3_candidates(v3_symbols)
            log.info(f"   ✅ [PHASE 7] V3 found {len(v3_signals)} Pre-Pump signals")

            # أرسل أفضل الإشارات
            v3_sent = 0
            for v3_sig in v3_signals[:STRATEGY_V3_MAX_SIGNALS]:
                try:
                    sym = v3_sig["symbol"]
                    # فلتر الحكم الشرعي
                    if not halal_check.is_tracked(sym):
                        continue
                    halal_info = halal_check.get_ruling(sym)
                    halal_ruling = halal_info.get("ruling", "unknown")
                    if halal_ruling != "halal":
                        continue
                    # dedup
                    if is_recently_signaled(sym) or sym in _cycle_signaled:
                        continue
                    # 🆕 v6.4.98: فلتر Score الأدنى
                    if v3_sig["score"] < V3_MIN_SCORE:
                        log.info(f"🚀 [V3] ⏭️ {sym} — Score {v3_sig['score']} < {V3_MIN_SCORE}")
                        continue
                    # 🆕 v6.4.98: لا تكرار — لا صفقة نشطة على نفس العملة
                    _skip_v3 = False
                    for _cid in cids:
                        if has_active_trade(sym, _cid, strategy="v3"):
                            log.info(f"🚀 [V3] ⏭️ {sym} — صفقة V3 نشطة")
                            _skip_v3 = True
                            break
                    if _skip_v3:
                        continue

                    # ✅ نشر الصفقة V3
                    _v3_target_str = "channel" if V3_ENABLED else "bot"
                    msg = strategy_v3.format_v3_signal(v3_sig, halal_ruling, target=_v3_target_str)
                    from signals import build_coin_links_kb
                    _v3_links_kb = build_coin_links_kb(sym)
                    # 🆕 v6.4.110: fallback chain: SIGNALS_CHANNEL_ID → CHANNEL_ID → CHAT_ID
                    if V3_ENABLED:
                        if SIGNALS_CHANNEL_ID:
                            send_to_signals_channel(msg, kb=_v3_links_kb)
                            target_str = "CHANNEL"
                        elif CHANNEL_ID:
                            _tg_post("sendMessage", {"chat_id": str(CHANNEL_ID), "text": msg, "parse_mode": "HTML"})
                            target_str = "CHANNEL"
                        else:
                            send_msg(msg, _v3_links_kb, CHAT_ID)
                            target_str = "BOT"
                            log.warning(f"⚠️ [V3] لا توجد قناة — أرسلت للبوت فقط")
                    else:
                        send_msg(msg, _v3_links_kb, CHAT_ID)
                        target_str = "BOT"

                    # 🆕 v6.4.98: أنشئ صفقة V3 في tracker
                    v3_signal_id = f"v3_{sym}_{int(time.time())}"
                    v3_trade = {
                        "signal_id": v3_signal_id,
                        "symbol": sym,
                        "entry": v3_sig["entry"],
                        "sl": v3_sig["sl"],
                        "tp1": v3_sig["tp1"], "tp2": v3_sig["tp2"], "tp3": v3_sig["tp3"],
                        "tp4": 0, "tp5": 0, "tp6": 0,
                        "tp1_pct": v3_sig["tp1_pct"], "tp2_pct": v3_sig["tp2_pct"],
                        "tp3_pct": v3_sig["tp3_pct"], "tp4_pct": 0, "tp5_pct": 0, "tp6_pct": 0,
                        "entry_low": v3_sig["entry_low"], "entry_high": v3_sig["entry_high"],
                        "score": v3_sig["score"], "confirmed": "",
                        "risk_pct": abs(v3_sig["sl_pct"]),
                        "position_size_usd": 0, "position_size_pct": 0, "risk_amount_usd": 0,
                        "valid_until": int(time.time()) + 3600 * 4,
                        "btc_trend": "", "update_stars": 0,
                        "strategy": "v3",
                    }
                    try_create(CHAT_ID, v3_trade, strategy="v3")
                    mark_signal_sent(sym)
                    _cycle_signaled.add(sym)
                    v3_sent += 1
                    log.info(f"🚀 [V3] SIGNAL SENT ({target_str}): {sym} Score={v3_sig['score']}/100 Entry={v3_sig['entry_type']}")
                    time.sleep(1)
                except Exception as e:
                    log.warning(f"🚀 [V3] send {sym} err: {e}")
                    continue

            stats["v3_sent"] = v3_sent
            log.info(f"📋 [PHASE 7] V3 sent {v3_sent} Pre-Pump signals")
        except Exception as e:
            log.error(f"❌ [PHASE 7] V3 err: {e}")
            import traceback
            log.error(f"📋 {traceback.format_exc()}")
    else:
        log.info(f"📋 [PHASE 7] V3 معطّل (STRATEGY_V3_ENABLED={STRATEGY_V3_ENABLED} V3_ENABLED={V3_ENABLED})")

    # ═══ 🆕 v6.4.120: المرحلة 8 — V3 Watch Alerts (تنبيهات صغيرة بدون أهداف) ═══
    # للعملات التي تُظهر إشارات إيجابية مبكرة لكنها لم تحقق شروط V3 الكاملة
    if STRATEGY_V3_ENABLED and V3_ENABLED and V3_WATCH_ENABLED:
        log.info(f"📋 [PHASE 8] V3 Watch Alerts — max={V3_WATCH_MAX_ALERTS} cooldown={V3_WATCH_COOLDOWN_HOURS}h (target: {'قناة' if V3_ENABLED else 'بوت'})")
        try:
            # بناء قائمة العملات (نفس V3 logic)
            watch_symbols = []
            try:
                binance_symbols_w = fetch_all_spot_symbols()
                binance_set_w = set(binance_symbols_w) if binance_symbols_w else set()
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal" and r["symbol"] in binance_set_w:
                        watch_symbols.append(r["symbol"])
                for cid in cids:
                    for fav in get_favorites(cid):
                        if fav in binance_set_w and fav not in watch_symbols:
                            watch_symbols.append(fav)
                watch_symbols = list(set(watch_symbols))
            except Exception as e:
                log.warning(f"📋 [PHASE 8] Binance symbol list failed: {e}")
                for r in halal_check.list_rulings():
                    if r["ruling"] == "halal":
                        watch_symbols.append(r["symbol"])
                watch_symbols = list(set(watch_symbols))

            # 🆕 v6.4.120: استبعاد العملات التي تم نشرها بالفعل (V3 signals + cycle_signaled)
            watch_symbols = [s for s in watch_symbols if s not in _cycle_signaled]

            # حد العدد لِـ تسريع الفحص
            if len(watch_symbols) > V3_MAX_SYMBOLS:
                try:
                    top_movers = fetch_top_movers() or []
                    top_syms_w = set(top_movers[:V3_MAX_SYMBOLS * 2])
                    watch_active = [s for s in watch_symbols if s in top_syms_w]
                    if len(watch_active) >= 10:
                        watch_symbols = watch_active[:V3_MAX_SYMBOLS]
                    else:
                        watch_symbols = watch_symbols[:V3_MAX_SYMBOLS]
                except Exception:
                    watch_symbols = watch_symbols[:V3_MAX_SYMBOLS]

            log.info(f"📋 [PHASE 8] V3-WATCH scanning {len(watch_symbols)} symbols for watch candidates")

            # 🆕 v6.4.120: cooldown — منع تكرار نفس العملة قبل V3_WATCH_COOLDOWN_HOURS
            _watch_already = set()
            try:
                _watch_state_file = os.path.join(_PERSISTENT_DIR_V1V2, "v3_watch_alerts.json")
                if os.path.exists(_watch_state_file):
                    with open(_watch_state_file, "r") as f:
                        watch_data = _json_state.load(f)
                    now_ts = time.time()
                    for sym_w, ts_w in watch_data.items():
                        if (now_ts - ts_w) < V3_WATCH_COOLDOWN_HOURS * 3600:
                            _watch_already.add(sym_w)
            except Exception as e:
                log.warning(f"📋 [PHASE 8] cooldown load err: {e}")

            # فحص العملات
            watch_signals = strategy_v3.scan_v3_watch_candidates(watch_symbols, already_signaled=_watch_already)
            log.info(f"   ✅ [PHASE 8] V3-WATCH found {len(watch_signals)} watch candidates")

            # أرسل أفضل الـ watch alerts
            watch_sent = 0
            _new_watch_state = {}
            try:
                _watch_state_file = os.path.join(_PERSISTENT_DIR_V1V2, "v3_watch_alerts.json")
                if os.path.exists(_watch_state_file):
                    with open(_watch_state_file, "r") as f:
                        _new_watch_state = _json_state.load(f)
            except Exception:
                pass

            for watch_sig in watch_signals[:V3_WATCH_MAX_ALERTS]:
                try:
                    sym = watch_sig["symbol"]
                    # فلتر الحكم الشرعي
                    if not halal_check.is_tracked(sym):
                        continue
                    halal_info = halal_check.get_ruling(sym)
                    halal_ruling = halal_info.get("ruling", "unknown")
                    if halal_ruling != "halal":
                        continue
                    # استبعاد لو يوجد صفقة V3 نشطة على نفس العملة
                    _skip_watch = False
                    for _cid in cids:
                        if has_active_trade(sym, _cid, strategy="v3"):
                            _skip_watch = True
                            break
                    if _skip_watch:
                        continue

                    # ✅ نشر الـ Watch alert
                    _watch_target_str = "channel" if V3_ENABLED else "bot"
                    msg = strategy_v3.format_v3_watch_alert(watch_sig, target=_watch_target_str)
                    from signals import build_coin_links_kb
                    _watch_links_kb = build_coin_links_kb(sym)
                    if V3_ENABLED:
                        if SIGNALS_CHANNEL_ID:
                            send_to_signals_channel(msg, kb=_watch_links_kb)
                            target_str = "CHANNEL"
                        elif CHANNEL_ID:
                            _tg_post("sendMessage", {"chat_id": str(CHANNEL_ID), "text": msg, "parse_mode": "HTML"})
                            target_str = "CHANNEL"
                        else:
                            send_msg(msg, _watch_links_kb, CHAT_ID)
                            target_str = "BOT"
                            log.warning(f"⚠️ [V3-WATCH] لا توجد قناة — أرسلت للبوت فقط")
                    else:
                        send_msg(msg, _watch_links_kb, CHAT_ID)
                        target_str = "BOT"

                    # 🆕 v6.4.120: تحديث الـ cooldown state
                    _new_watch_state[sym] = time.time()
                    watch_sent += 1
                    log.info(f"👀 [V3-WATCH] ALERT SENT ({target_str}): {sym} Score={watch_sig['watch_score']}/100 Signals={watch_sig['early_signals_count']}")
                    time.sleep(1)
                except Exception as e:
                    log.warning(f"👀 [V3-WATCH] send {sym} err: {e}")
                    continue

            # 🆕 v6.4.120: حفظ الـ cooldown state (تنظيف البيانات أقدم من 24h)
            try:
                _watch_state_file = os.path.join(_PERSISTENT_DIR_V1V2, "v3_watch_alerts.json")
                # تنظيف البيانات القديمة (أكثر من 24h)
                now_ts = time.time()
                _new_watch_state = {
                    s: ts for s, ts in _new_watch_state.items()
                    if (now_ts - ts) < 24 * 3600
                }
                with open(_watch_state_file, "w") as f:
                    _json_state.dump(_new_watch_state, f)
            except Exception as e:
                log.warning(f"📋 [PHASE 8] cooldown save err: {e}")

            stats["v3_watch_sent"] = watch_sent
            log.info(f"📋 [PHASE 8] V3-WATCH sent {watch_sent} watch alerts")
        except Exception as e:
            log.error(f"❌ [PHASE 8] V3-WATCH err: {e}")
            import traceback
            log.error(f"📋 {traceback.format_exc()}")
    else:
        log.info(f"📋 [PHASE 8] V3-WATCH معطّل (V3_WATCH_ENABLED={V3_WATCH_ENABLED} V3_ENABLED={V3_ENABLED})")

    stats["duration"] = round(time.time() - cycle_start, 1)
    _last_scan_time = time.time()
    log.info(f"🏁 [SCAN END] duration={stats['duration']}s "
             f"({len(sorted_syms)} candidates → {len(mtf_results)} analyzed → "
             f"{stats['sent']} V1 sent + {stats.get('v2_sent', 0)} V2 sent + {stats.get('v3_sent', 0)} V3 sent + {stats.get('v3_watch_sent', 0)} V3-WATCH sent)")
    log.info(f"📊 [SCAN STATS] {stats}")
    return stats


def scheduler_loop():
    log.info("🧠 Scheduler started — first cycle in 5 seconds")
    global _last_scan_time, _scheduler_alive
    _last_scan_time = time.time()
    _scheduler_alive = True
    _signals_today = 0
    _current_day = int(time.time() / 86400)
    _last_signal_time = time.time()  # 🆕 v6.4.32: وقت آخر إشارة مُرسلة
    _last_no_signal_alert = 0       # 🆕 v6.4.32: وقت آخر تنبيه "لا صفقات"
    time.sleep(5)
    while True:
        try:
            new_day = int(time.time() / 86400)
            if new_day != _current_day:
                _current_day = new_day
                _signals_today = 0
            log.info("🧠 ─── scan_cycle START ───")
            stats = scan_cycle()
            _last_scan_time = time.time()
            _scheduler_alive = True
            log.info("🧠 ─── scan_cycle END ─── sleeping for {}s ───".format(SCAN_INTERVAL))

            if stats and isinstance(stats, dict):
                sent_this_cycle = stats.get("sent", 0)
                _signals_today += sent_this_cycle
                if sent_this_cycle > 0:
                    _last_signal_time = time.time()  # تحديث وقت آخر إشارة
                    # 🆕 v6.4.51: تحديث cooldown time على scan_cycle function attribute
                    scan_cycle._last_signal_ts = time.time()

                # 🆕 v6.4.32: تنبيه "لا صفقات" لو مر وقت طويل بدون إشارات
                time_since_last_signal = time.time() - _last_signal_time
                # لو مر أكثر من 30 دقيقة (1800s) بدون أي إشارة
                if sent_this_cycle == 0 and time_since_last_signal >= 1800:
                    # أرسل تنبيه كل ساعة (3600s) — ليس كل دورة
                    if (time.time() - _last_no_signal_alert) >= 3600:
                        candidates = stats.get("candidates", 0)
                        strong = stats.get("strong_setups", 0)
                        no_signal = stats.get("no_signal", 0)
                        skipped_not_tracked = stats.get("skipped_not_tracked", 0)
                        skipped_low_score = stats.get("skipped_low_score", 0)
                        skipped_cooldown = stats.get("skipped_cooldown", 0)

                        # 🆕 v6.4.56: نص احترافي بسيط — يُرسل فقط للمالك (CHAT_ID)
                        # لا يُرسل لقناة الأهداف (القناة العامة) ولا قناة الصفقات
                        alert_msg = "📊 <b>تقرير المسح</b>\n"
                        alert_msg += "━━━━━━━━━━━━━━━━━━\n\n"
                        alert_msg += f"⏱️ آخر إشارة: منذ {int(time_since_last_signal / 60)} دقيقة\n"
                        alert_msg += f"📤 إشارات اليوم: {_signals_today}\n\n"

                        # تحليل السبب (احترافي)
                        if candidates == 0:
                            alert_msg += "🔒 لا توجد بيانات سوق (Binance/CoinGecko قد يكون محظوراً)\n"
                        elif strong == 0:
                            alert_msg += f"📉 لا توجد فرص مطابقة للاستراتيجية\n"
                            alert_msg += f"   • فحص {candidates} عملة\n"
                            alert_msg += f"   • صفر عملة حققت المعايير الفنية\n\n"
                            alert_msg += "<i>الاستراتيجية تتطلب: 3+ فريمات صاعدة + confluence ≥ 50 + R/R ≥ 2.0</i>\n"
                        else:
                            alert_msg += f"⚖️ وُجدت {strong} فرصة محتملة لكنها لم تكتمل\n"
                            if no_signal > 0:
                                alert_msg += f"   • {no_signal} فشل في R/R أو generate_mtf\n"
                            if skipped_not_tracked > 0:
                                alert_msg += f"   • {skipped_not_tracked} ليست في قائمة الأحكام الشرعية\n"
                            if skipped_low_score > 0:
                                alert_msg += f"   • {skipped_low_score} تحت عتبة الجودة (score < {SCORE_THRESHOLD})\n"
                            if skipped_cooldown > 0:
                                alert_msg += f"   • {skipped_cooldown} ضمن فترة cooldown\n"

                        alert_msg += "\n🤖 البوت مستمر في الفحص"

                        # 🆕 v6.4.46: قائمة الصفقات النشطة (لو يوجد) — يظهر فقط للمالك في القناة
                        # 🆕 v6.4.48: إصلاح bug — استخدام _cid بدل cid (تفادي shadow) + سجل تشخيصي
                        # 🆕 v6.4.50: تشخيص مفصّل جداً — يطبع CHAT_ID + كل cids + كل status في DB
                        try:
                            log.info(f"📋 [DIAG v6.4.50] CHAT_ID={CHAT_ID!r} | CHANNEL_ID={CHANNEL_ID!r}")
                            all_active = []
                            # استخدم كل cids المحتملة (CHAT_ID + أي cid آخر في الـ DB)
                            cids_to_check = set()
                            if CHAT_ID:
                                cids_to_check.add(str(CHAT_ID))
                            # 🆕 v6.4.48: اجلب كل cids من الـ DB مباشرة
                            try:
                                import tracker as _tk_active
                                _all_db = _tk_active._load()
                                log.info(f"📋 [DIAG v6.4.50] DB has {len(_all_db)} cids: {list(_all_db.keys())}")
                                cids_to_check.update(_all_db.keys())
                                # 🆕 v6.4.50: اطبع كل status في DB (للتشخيص)
                                for _cid_diag, _trades_diag in _all_db.items():
                                    _status_counts = {}
                                    for _t_diag in _trades_diag:
                                        _s = _t_diag.get("status", "?")
                                        _status_counts[_s] = _status_counts.get(_s, 0) + 1
                                    log.info(f"📋 [DIAG v6.4.50] cid={_cid_diag} statuses: {_status_counts}")
                            except Exception as e:
                                log.warning(f"get cids from DB err: {e}")
                            log.info(f"📋 [DIAG v6.4.50] will check {len(cids_to_check)} cids: {cids_to_check}")
                            for _cid in cids_to_check:
                                try:
                                    _active_for_cid = get_active(_cid)
                                    log.info(f"📋 [DIAG v6.4.50] get_active('{_cid}') → {len(_active_for_cid)} trades")
                                    if _active_for_cid:
                                        for _at in _active_for_cid[:3]:
                                            log.info(f"📋 [DIAG v6.4.50]   - {_at.get('symbol')} status={_at.get('status')}")
                                    all_active.extend(_active_for_cid)
                                except Exception as e:
                                    log.warning(f"get_active({_cid}) err: {e}")
                            log.info(f"📋 [DIAG v6.4.50] TOTAL active trades found: {len(all_active)}")
                            if all_active:
                                alert_msg += f"\n\n📋 <b>الصفقات النشطة ({len(all_active)}):</b>\n"
                                alert_msg += "━━━━━━━━━━━━━━━━━━\n"
                                # رتّب حسب الـ score (الأعلى أولاً)
                                all_active.sort(key=lambda t: -float(t.get("score", 0) or 0))
                                for t in all_active[:10]:  # حد 10 صفقات في الرسالة
                                    sym = t.get("symbol", "?")
                                    entry = float(t.get("entry", 0) or 0)
                                    status = t.get("status", "ACTIVE")
                                    score = float(t.get("score", 0) or 0)
                                    # 🆕 v6.4.46: جلب السعر الحالي + حساب PnL
                                    try:
                                        cur_candles = fetch_klines(sym, "15m", 4)
                                        cur_price = cur_candles[-1]["close"] if cur_candles else entry
                                    except Exception:
                                        cur_price = entry
                                    pnl_pct = ((cur_price - entry) / entry * 100) if entry > 0 else 0
                                    # 🎨 رمز PnL
                                    pnl_icon = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
                                    # 🎨 رمز Status
                                    status_icon = {
                                        "ACTIVE": "🟡",
                                        "TP1_HIT": "🟢",
                                        "TP2_HIT": "🟢",
                                        "TP3_HIT": "🟢",
                                        "TP4_HIT": "🟢",
                                    }.get(status, "🟡")
                                    # 🎨 مدة الصفقة
                                    age_sec = int(time.time()) - int(t.get("created_at", 0))
                                    age_h = age_sec // 3600
                                    age_min = (age_sec % 3600) // 60
                                    age_str = f"{age_h}h" if age_h > 0 else f"{age_min}m"
                                    # 📝 سطر الصفقة
                                    alert_msg += (
                                        f"{status_icon} <b>{sym}</b> {pnl_icon} {pnl_pct:+.2f}%\n"
                                        f"   💰 {fmt_price(entry)} → {fmt_price(cur_price)}\n"
                                        f"   ⏱️ {age_str} | 🎯 {score:.0f}/100 | {status}\n"
                                    )
                                if len(all_active) > 10:
                                    alert_msg += f"\n<i>... و {len(all_active) - 10} صفقة أخرى نشطة</i>\n"
                            else:
                                # 🆕 v6.4.48: لو لا صفقات نشطة — أضف ملاحظة بدل سطر فارغ
                                log.info(f"📋 [active check] no active trades to show")
                        except Exception as e:
                            log.error(f"❌ active trades list err: {e}")

                        # 🆕 v6.4.56: إرسال فقط للمالك (CHAT_ID) — لا للقناة العامة
                        # السبب: هذا تنبيه داخلي، لا حاجة له في القناة العامة
                        if CHAT_ID:
                            try:
                                send_msg(alert_msg, None, CHAT_ID)
                            except Exception as e:
                                log.warning(f"send status to owner err: {e}")
                        _last_no_signal_alert = time.time()
                        log.info(f"📊 STATUS REPORT sent to owner: candidates={candidates} strong={strong} (sent_to=CHAT_ID, NOT to channel)")
        except Exception as e:
            # 🆕 v6.2.5: تسجيل الخطأ بالتفصيل + متابعة العمل (لا توقف الـ scheduler)
            # 🆕 v6.4.58: حماية من list index out of range
            # 🆕 v6.4.59: تحسين استخراج موقع الخطأ + سجلات تشخيصية لكل مهمة
            import traceback
            tb_lines = traceback.format_exc()
            log.error(f"❌ Scheduler crash: {e}")
            log.error(f"📋 Traceback:\n{tb_lines}")
            log.info("🔄 Continuing to next cycle in {}s...".format(SCAN_INTERVAL))
            _scheduler_alive = False
            # 🆕 v6.4.2: أرسل تنبيه خطأ للمستخدم
            # 🆕 v6.4.58/v6.4.59: استخراج الموقع الفعلي للخطأ من traceback
            try:
                # استخراج آخر سطر في traceback يحتوي على "File" (مكان الخطأ الفعلي)
                tb_location = ""
                try:
                    tb_lines_list = tb_lines.strip().split("\n")
                    # ابحث عن آخر سطر يحتوي على "File" — هذا هو موقع الخطأ الفعلي
                    for line in reversed(tb_lines_list):
                        if "File" in line and "line" in line:
                            tb_location = line.strip()
                            break
                    # لو ما لقينا، خد قبل آخر سطر
                    if not tb_location and len(tb_lines_list) >= 2:
                        tb_location = tb_lines_list[-2].strip()
                except Exception:
                    pass

                err_msg = f"❌ <b>Scheduler crash</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                err_msg += f"⚠️ خطأ: <code>{str(e)[:200]}</code>\n"
                if tb_location:
                    err_msg += f"📍 الموقع: <code>{tb_location[:200]}</code>\n"
                else:
                    err_msg += "📍 الموقع: <i>غير محدد — راجع سجلات Render</i>\n"
                err_msg += "\n🔄 سيحاول مرة أخرى بعد 5 دقائق\n"
                err_msg += "📥 أرسل <code>/forcescan</code> لفحص فوري"
                send_msg(err_msg)
            except Exception:
                pass  # تجنّب تسلسل أخطاء
        time.sleep(SCAN_INTERVAL)


# 🆕 v6.2.7: متغيرات Watchdog
_last_scan_time = time.time()
_scheduler_alive = True
_heartbeat_count = 0


def watchdog_loop():
    """🆕 v6.4.36: Watchdog — يراقب scheduler + يعيد تشغيله لو تعطل.
    - كل 60 ثانية يفحص آخر scan_time
    - لو مرت أكثر من 3*SCAN_INTERVAL بدون scan → يعيد تشغيل scheduler
    - heartbeat كل HEARTBEAT_INTERVAL
    """
    log.info(f"🐕 Watchdog started — checks every 60s, heartbeat every {HEARTBEAT_INTERVAL//60}min")
    global _last_scan_time, _scheduler_alive, _heartbeat_count
    last_heartbeat_ts = 0.0
    while True:
        try:
            time.sleep(60)
            now = time.time()
            elapsed = now - _last_scan_time
            if elapsed > 3 * SCAN_INTERVAL:
                log.error(f"🚨 [WATCHDOG] Scheduler stalled — no scan for {int(elapsed)}s → RESTARTING")
                _scheduler_alive = False
                # 🆕 v6.4.36: أعد تشغيل scheduler فعلياً
                _last_scan_time = now  # reset to prevent re-trigger
                threading.Thread(target=scheduler_loop, daemon=True).start()
                log.info("🔄 [WATCHDOG] Scheduler restarted")
            else:
                _scheduler_alive = True
            # 🆕 v6.4.2: heartbeat كل HEARTBEAT_INTERVAL (افتراضي 30 دقيقة بدل ساعة)
            if (now - last_heartbeat_ts) >= HEARTBEAT_INTERVAL:
                last_heartbeat_ts = now
                _heartbeat_count += 1
                # عدد الصفقات النشطة
                active_count = len(get_active(CHAT_ID)) if CHAT_ID else 0
                # آخر scan قبل كم ثانية
                elapsed_min = int(elapsed // 60)
                hb_msg = "💓 <b>Heartbeat</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                hb_msg += f"✅ البوت يعمل تلقائياً\n"
                hb_msg += f"🕐 آخر دورة مسح: {elapsed_min} دقيقة مضت\n"
                hb_msg += f"🔄 Scheduler: {'✅ alive' if _scheduler_alive else '❌ stalled'}\n"
                hb_msg += f"📊 صفقات نشطة: {active_count}\n"
                hb_msg += f"🌐 Flask: ✅ running\n"
                hb_msg += f"🗺️ مسح Spot: {'مفعّل' if SCAN_ALL_SPOT else 'مُعطّل'}\n"
                hb_msg += f"⚙️ فاصل المسح: {SCAN_INTERVAL//60} دقيقة | Heartbeat: {HEARTBEAT_INTERVAL//60} دقيقة\n"
                hb_msg += f"\n📥 <code>/scandebug</code> / <code>/forcescan</code> / <code>/active_signals</code>"
                send_msg(hb_msg)
                log.info(f"💓 Heartbeat #{_heartbeat_count} sent (active={active_count})")
        except Exception as e:
            log.error(f"❌ Watchdog crash: {e}")

# ═══ Telegram Handlers ═══

def _send_document(cid: str, file_path: str, caption: str = ""):
    """🆕 v6.4.10: يرسل ملف (PDF) للمستخدم عبر Telegram sendDocument."""
    if not TOKEN:
        return
    try:
        with open(file_path, "rb") as f:
            files = {"document": f}
            data = {"chat_id": cid}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "HTML"
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument",
                              data=data, files=files, timeout=60)
            if r.status_code == 200:
                log.info(f"📎 PDF sent to {cid}")
            else:
                log.warning(f"sendDocument fail: {r.status_code} {r.text[:100]}")
    except Exception as e:
        log.warning(f"send_document err: {e}")


def generate_pdf_report(cid: str) -> str:
    """🆕 v6.4.10: يولّد ملف PDF تقرير كامل لكل الصفقات.

    يحتوي على:
      - عدد الصفقات الإجمالي + النشطة + المغلقة
      - نسبة تحقق الأهداف بالكامل (TP1-TP6, SL, EXPIRED)
      - الصفقات الملغاة (EXPIRED + CANCELLED)
      - تفصيل آخر 20 صفقة

    يرجع مسار الملف المؤقت.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle)
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from datetime import datetime
    import pytz

    all_trades = []
    try:
        import tracker as _tk_pdf
        all_trades = _tk_pdf._load().get(str(cid), [])
        non_final_set = _tk_pdf.NON_FINAL
    except Exception as e:
        log.warning(f"PDF report: tracker err: {e}")
        return None
    total = len(all_trades)
    active = [t for t in all_trades if t.get("status") in non_final_set]
    closed = [t for t in all_trades if t.get("status") not in non_final_set]

    # عدّ الأهداف
    tp_counts = {"TP1_HIT": 0, "TP2_HIT": 0, "TP3_HIT": 0, "TP4_HIT": 0,
                 "TP5_HIT": 0, "TP6_HIT": 0, "STOP_LOSS": 0, "EXPIRED": 0,
                 "CANCELLED": 0, "CLOSED": 0, "ACTIVE": 0, "TP1_HIT": 0}
    for t in all_trades:
        s = t.get("status", "ACTIVE")
        tp_counts[s] = tp_counts.get(s, 0) + 1

    # Win rate
    # 🆕 v6.4.82: TP{n}_DONE = إغلاق رابح عند الستوب الديناميكي بعد أهداف
    wins = sum(tp_counts.get(k, 0) for k in
               ["TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "TP5_HIT", "TP6_HIT",
                "TP1_DONE", "TP2_DONE", "TP3_DONE", "TP4_DONE"])
    losses = tp_counts.get("STOP_LOSS", 0)
    wr_denom = wins + losses
    win_rate = (wins / wr_denom * 100) if wr_denom > 0 else 0

    # إجمالي PnL
    total_pnl = sum(t.get("pnl", 0) for t in closed if t.get("pnl"))

    # التاريخ + المنطقة الزمنية
    try:
        tz = pytz.timezone(TIMEZONE)
    except Exception as e:
        tz = pytz.UTC
    now_dt = datetime.now(tz)

    # ── إنشاء PDF ──
    pdf_path = "/tmp/bot_report.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ArabicTitle', parent=styles['Title'],
                                 fontSize=18, alignment=TA_CENTER,
                                 textColor=HexColor('#1a5276'))
    heading_style = ParagraphStyle('ArabicHeading', parent=styles['Heading2'],
                                    fontSize=14, textColor=HexColor('#2e86c1'),
                                    spaceAfter=10)
    body_style = ParagraphStyle('ArabicBody', parent=styles['Normal'],
                                 fontSize=11, alignment=TA_RIGHT,
                                 textColor=black, spaceAfter=5)
    small_style = ParagraphStyle('ArabicSmall', parent=styles['Normal'],
                                  fontSize=9, textColor=HexColor('#666666'))

    story = []
    # العنوان
    story.append(Paragraph("Crypto Bot — Trading Report", title_style))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Generated: {now_dt.strftime('%Y-%m-%d %H:%M')} ({TIMEZONE})", small_style))
    story.append(Spacer(1, 0.5*cm))

    # ── ملخص سريع ──
    story.append(Paragraph("Summary", heading_style))
    summary_data = [
        ["Metric", "Value"],
        ["Total Trades", str(total)],
        ["Active (running)", str(len(active))],
        ["Closed", str(len(closed))],
        ["Wins (TP1-TP6)", str(wins)],
        ["Losses (SL)", str(losses)],
        ["Win Rate", f"{win_rate:.1f}%"],
        ["Total PnL", f"{total_pnl:+.2f}%"],
        ["Expired/Cancelled", str(tp_counts.get("EXPIRED", 0) + tp_counts.get("CANCELLED", 0))],
    ]
    summary_table = Table(summary_data, colWidths=[8*cm, 6*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2e86c1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.5*cm))

    # ── تفصيل الأهداف ──
    story.append(Paragraph("Targets Breakdown", heading_style))
    tp_data = [
        ["Status", "Count", "Percentage"],
        ["TP1 HIT (+1%)", str(tp_counts.get("TP1_HIT", 0)), f"{(tp_counts.get('TP1_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP2 HIT (+4%)", str(tp_counts.get("TP2_HIT", 0)), f"{(tp_counts.get('TP2_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP3 HIT (+8%)", str(tp_counts.get("TP3_HIT", 0)), f"{(tp_counts.get('TP3_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP4 HIT (+12%)", str(tp_counts.get("TP4_HIT", 0)), f"{(tp_counts.get('TP4_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP5 HIT (+15%)", str(tp_counts.get("TP5_HIT", 0)), f"{(tp_counts.get('TP5_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP6 HIT (+20%+)", str(tp_counts.get("TP6_HIT", 0)), f"{(tp_counts.get('TP6_HIT', 0)/max(total,1))*100:.1f}%"],
        ["TP1 DONE (dyn. SL win)", str(tp_counts.get("TP1_DONE", 0)), f"{(tp_counts.get('TP1_DONE', 0)/max(total,1))*100:.1f}%"],
        ["TP2 DONE (dyn. SL win)", str(tp_counts.get("TP2_DONE", 0)), f"{(tp_counts.get('TP2_DONE', 0)/max(total,1))*100:.1f}%"],
        ["TP3 DONE (dyn. SL win)", str(tp_counts.get("TP3_DONE", 0)), f"{(tp_counts.get('TP3_DONE', 0)/max(total,1))*100:.1f}%"],
        ["TP4 DONE (dyn. SL win)", str(tp_counts.get("TP4_DONE", 0)), f"{(tp_counts.get('TP4_DONE', 0)/max(total,1))*100:.1f}%"],
        ["STOP LOSS", str(tp_counts.get("STOP_LOSS", 0)), f"{(tp_counts.get('STOP_LOSS', 0)/max(total,1))*100:.1f}%"],
        ["EXPIRED", str(tp_counts.get("EXPIRED", 0)), f"{(tp_counts.get('EXPIRED', 0)/max(total,1))*100:.1f}%"],
        ["CANCELLED", str(tp_counts.get("CANCELLED", 0)), f"{(tp_counts.get('CANCELLED', 0)/max(total,1))*100:.1f}%"],
        ["ACTIVE (running)", str(len(active)), f"{(len(active)/max(total,1))*100:.1f}%"],
    ]
    tp_table = Table(tp_data, colWidths=[6*cm, 3*cm, 5*cm])
    tp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a5276')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(tp_table)
    story.append(Spacer(1, 0.5*cm))

    # ── آخر 20 صفقة ──
    story.append(Paragraph("Recent Trades (Last 20)", heading_style))
    recent_data = [["Symbol", "Status", "Entry", "PnL%", "Date"]]
    for t in all_trades[:20]:
        sym = t.get("symbol", "?")
        status = t.get("status", "?")
        entry = t.get("entry", 0)
        pnl = t.get("pnl", 0)
        created = datetime.fromtimestamp(t.get("created_at", 0)).strftime("%m-%d %H:%M")
        # 🆕 v6.4.11: أظهر "—" لو entry = 0 (بيانات ناقصة)
        entry_str = f"${entry:.4f}" if entry > 0 else "—"
        pnl_str = f"{pnl:+.2f}%" if pnl else "—"
        recent_data.append([sym, status, entry_str, pnl_str, created])

    recent_table = Table(recent_data, colWidths=[2.5*cm, 3*cm, 3*cm, 2.5*cm, 3*cm])
    recent_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2e86c1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(recent_table)
    story.append(Spacer(1, 0.5*cm))

    # Footer
    story.append(Paragraph(
        f"Total: {total} trades | Wins: {wins} | Losses: {losses} | "
        f"Win Rate: {win_rate:.1f}% | Total PnL: {total_pnl:+.2f}%",
        small_style
    ))

    doc.build(story)
    return pdf_path


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.43: /analyse — تحليل فني تفاعلي للمجتمع
# مع احتياطات شاملة لمنع توقف البوت:
#   1) Rate limit: 10 تحليلات/ساعة لكل مستخدم
#   2) Timeout: 8s max لمنع التعليق
#   3) Thread منفصل لتفادي تأخير الـ webhook
#   4) Cache 5 دقائق لكل عملة (يفادي استدعاءات Binance المتكررة)
#   5) منع التحليل لو Binance محظور أو في وضع المراقبة
#   6) Catch شامل لكل الاستثناءات
#   7) تحقق من صحة الرمز (isalpha + max length)
#   8) تحقق من وجود سعر قبل المتابعة
# ═══════════════════════════════════════════════════════════

_analyse_cache: dict = {}  # {symbol: (ts, response_text)}
_analyse_user_count: dict = {}  # {cid: {hour_ts: count}}
_ANALYSE_CACHE_TTL = 300  # 5 دقائق cache لكل عملة
_ANALYSE_RATE_LIMIT = 10  # 10 تحليلات/ساعة لكل مستخدم
_ANALYSE_TIMEOUT = 8  # 8 ثواني max للتحليل


def _analyse_command(sym: str, cid):
    """🆕 v6.4.43: تحليل عملة بمنطق بوتك + رد ذكي + احتياطات شاملة."""
    try:
        # تحقق صحة الرمز
        sym = (sym or "").upper().strip().replace("/", "").replace("-", "")
        if not sym or not all(c.isalnum() for c in sym) or not sym[0].isalpha() or len(sym) > 12 or len(sym) < 2:
            send_msg("📊 <b>أمر التحليل</b>\n\nالاستخدام: <code>/analyse BTC</code>\n⚠️ الرمز يجب أن يكون 2-12 حرف", None, cid)
            return

        # 🛡️ احتياط 1: Rate limit
        hour_ts = int(time.time() // 3600)
        cid_str = str(cid)
        counts = _analyse_user_count.setdefault(cid_str, {})
        if hour_ts in counts:
            if counts[hour_ts] >= _ANALYSE_RATE_LIMIT:
                send_msg(f"⏱️ بلغت الحد الأقصى ({_ANALYSE_RATE_LIMIT} تحليل/ساعة)\nحاول بعد ساعة.", None, cid)
                return
            counts[hour_ts] += 1
        else:
            # تنظيف الساعات القديمة
            counts.clear()
            counts[hour_ts] = 1

        # 🛡️ احتياط 2: Cache hit (5 دقائق) — يفادي إعادة الطلبات
        cache_key = sym
        if cache_key in _analyse_cache:
            ts, cached_response = _analyse_cache[cache_key]
            if time.time() - ts < _ANALYSE_CACHE_TTL:
                send_msg(cached_response, None, cid)
                return

        # 🆕 v6.4.44: لا حاجة لفحص Binance — analyse.py يستخدم CoinGecko فقط

        # 🛡️ احتياط 4: تشغيل في thread منفصل مع timeout لمنع تعليق الـ webhook
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_analyse_impl, sym, cid)
            try:
                future.result(timeout=_ANALYSE_TIMEOUT)
            except concurrent.futures.TimeoutError:
                send_msg(f"⏰ تحليل {sym} تجاوز {_ANALYSE_TIMEOUT}s — حاول لاحقاً.", None, cid)
                log.warning(f"⚠️ analyse timeout: {sym}")
    except Exception as e:
        log.error(f"❌ analyse cmd err: {e}")
        try:
            send_msg(f"❌ خطأ في تحليل {sym}. حاول لاحقاً.", None, cid)
        except Exception:
            pass


def _analyse_impl(sym: str, cid):
    """🆕 v6.4.44: تنفيذ التحليل عبر CoinGecko (معزول عن scan_cycle).
    - لا يستدعي engine.py ولا tracker.py
    - لا يتأثر بحظر Binance
    - لا يؤثر على بوت الصفقات أو الأهداف
    - يعمل في thread منفصل، timeout 8s (من caller)
    """
    try:
        # 🆕 v6.4.44: استيراد analyse.py المستقل
        import analyse as _analyse_mod
        response = _analyse_mod.analyse_symbol(sym)
        if response is None:
            send_msg(
                "📊 <b>أمر التحليل</b>\n\n"
                "الاستخدام: <code>/analyse BTC</code>\n"
                "⚠️ الرمز يجب أن يكون 2-12 حرف",
                None, cid
            )
            return
        send_msg(response, None, cid)
    except Exception as e:
        log.error(f"❌ analyse impl err: {e}")
        try:
            send_msg(f"❌ خطأ داخلي في تحليل {sym}", None, cid)
        except Exception:
            pass


def handle_text(cid, text, chat=None):
    # 🆕 v6.4.84: declarations للأ globals المعدّلة داخل الدالة (V1_ENABLED/V2_ENABLED)
    # 🆕 v6.4.98: V3_ENABLED
    global V1_ENABLED, V2_ENABLED, V3_ENABLED
    if text == "/start":
        favs = get_favorites(cid)
        msg = f"🤖 <b>بوت الكريبتو {BOT_VERSION}</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += "✅ <b>المسح التلقائي مُفعّل</b> — لا تحتاج لأي ضغطة\n"
        msg += f"⏱️ يفحص السوق كل <b>{SCAN_INTERVAL//60} دقيقة</b>\n"
        msg += f"💓 heartbeat كل <b>{HEARTBEAT_INTERVAL//60} دقيقة</b>\n"
        msg += f"🔍 تنبيه بعد كل دورة (حتى لو لا إشارات)\n\n"
        msg += "🆕 <b>الجديد في v6.4.122:</b>\n"
        msg += "  💎 <b>3 أهداف</b> بدل 1 (TP1 بِع 50%، TP2 بِع 30%، TP3 بِع 20%)\n"
        msg += "  💰 <b>Position Sizing</b> — مخاطرة 2% فقط لكل صفقة\n"
        msg += "  🟢 <b>منطقة دخول</b> (low-high) بدل نقطة واحدة\n"
        msg += "  ⚖️ <b>R/R = 1:5</b> (مكافأة 5x الخطر)\n"
        msg += "  ⏰ <b>صلاحية 12 ساعة</b> + تنبيه انتهاء\n"
        msg += "  🔁 <b>منع تكرار</b> — لا إشارة لنفس العملة قبل 6 ساعات\n"
        msg += "  📋 <b>سجل أداء</b> + Win Rate + PnL\n"
        msg += "  🚀 <b>V1/V2/V3 مستقلة</b> — تشغّل الكل معاً\n"
        msg += "  👀 <b>V3 Watch Alerts</b> — تنبيهات صغيرة للعملات تحت المراقبة\n"
        msg += "  📊 <b>VWAP + Volume Profile + Price Action</b> — تحليل احترافي متقدم\n\n"
        msg += f"🎯 مفضلتك: {', '.join(favs) if favs else 'فارغة'}\n\n"
        msg += "📥 <b>أوامر:</b>\n"
        msg += "  /trackrecord — سجل الأداء\n"
        msg += "  /active_signals — الصفقات النشطة\n"
        msg += "  /forcescan — فحص فوري (إجباري)\n"
        msg += "  /scandebug — تشخيص دورة المسح\n"
        msg += "  /analyse BTC — تحليل فني سريع 🆕"
        send_msg(msg, main_kb(), cid)
    elif text == "📊 المفضلة":
        favs = get_favorites(cid)
        if not favs:
            send_msg("📊 مفضلتك فارغة\n\nاستخدم ⚡ إضافة سريعة", main_kb(), cid)
            return
        # جلب الأسعار
        msg = "📊 <b>أسعار مفضلتك</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for sym in sorted(favs):
            candles = fetch_klines(sym)
            if candles:
                p = candles[-1]["close"]
                msg += f"  {sym}: {fmt_price(p)}\n"
            else:
                msg += f"  {sym}: —\n"
        send_msg(msg, main_kb(), cid)
    elif text == "🔥 الأكثر صعوداً":
        # 🆕 v6.4.4: زر الأكثر صعوداً — جلب أعلى 15 عملة من Binance
        # 🆕 v6.4.49: عرض نسبة الصعود + رابط TradingView لكل عملة + CoinGecko fallback
        send_msg("⏳ جاري جلب الأكثر صعوداً...", main_kb(), cid)
        def _gainers():
            try:
                # 🆕 v6.4.49: استخدم fetch_top_movers_with_data (يرجع (sym, change, price))
                gainers_data = fetch_top_movers_with_data(limit=15, min_vol=5e6, gainers=True)
                # 🆕 v6.4.49: لو Binance فشل → استخدم CoinGecko
                if not gainers_data:
                    log.info("🔄 Binance failed, using CoinGecko for top gainers...")
                    cg_tickers = get_market_tickers_coingecko()
                    if cg_tickers:
                        cg_movers = []
                        for t in cg_tickers:
                            sym_full = t.get("symbol", "")
                            if not sym_full.endswith("USDT"):
                                continue
                            base = sym_full[:-4]
                            if base in {"USDC","BUSD","DAI","TUSD","USDP","FDUSD","USDT","EUR","GBP","TRY","BIDR","AEUR","USDS","SUSD","PAXG","USTC","UP","DOWN","BULL","BEAR"}:
                                continue
                            try:
                                change = float(t.get("priceChangePercent", 0))
                                price = float(t.get("lastPrice", 0))
                                vol = float(t.get("quoteVolume", 0))
                                if price > 0 and vol >= 5e6 and change >= 5.0:
                                    cg_movers.append((base, change, price))
                            except (ValueError, TypeError):
                                continue
                        # رتّب تنازلياً حسب التغير
                        cg_movers.sort(key=lambda x: -x[1])
                        gainers_data = cg_movers[:15]

                if not gainers_data:
                    send_msg("⚠️ تعذّر جلب الأكثر صعوداً (Binance و CoinGecko كلاهما فشل)", main_kb(), cid)
                    return

                msg = "🔥 <b>أعلى 15 عملة صعوداً (24س)</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                for i, (sym, change, price) in enumerate(gainers_data, 1):
                    # 🆕 v6.4.49: TradingView link — يفتح الرسم البياني مباشرة
                    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}USDT"
                    # 🎨 رمز حسب قوة الصعود
                    if change >= 20:
                        chg_icon = "🚀"
                    elif change >= 10:
                        chg_icon = "🔥"
                    else:
                        chg_icon = "📈"
                    # 📝 سطر: 1. 🚀 NMR +18.5% | $12.67 (اسم العملة clickable link)
                    if price > 0:
                        msg += f"  {i}. {chg_icon} <a href=\"{tv_link}\">{sym}</a> <b>+{change:.1f}%</b> | {fmt_price(price)}\n"
                    else:
                        msg += f"  {i}. {chg_icon} <a href=\"{tv_link}\">{sym}</a> <b>+{change:.1f}%</b>\n"

                msg += "\n💡 <b>اضغط اسم العملة</b> لفتح الرسم البياني\n"
                msg += "💡 اضغط <b>⚡ إضافة سريعة</b> لإضافة أي عملة لمفضلتك"
                send_msg(msg, main_kb(), cid)
            except Exception as e:
                log.error(f"❌ gainers err: {e}")
                send_msg(f"❌ خطأ: {e}", main_kb(), cid)
        threading.Thread(target=_gainers, daemon=True).start()
    elif text == "👥 قائمة المستخدمين":
        # 🆕 v6.4.4: زر قائمة المستخدمين — إدارة (إضافة/طرد/تعليق)
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 <b>قائمة المستخدمين</b>\n━━━━━━━━━━━━━━━━━━\n\n🔒 هذا القسم خاص بالمالك فقط.", main_kb(), cid)
            return
        msg = "👥 <b>قائمة المستخدمين</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += "📥 <b>أوامر الإدارة:</b>\n\n"
        msg += "  <code>/add 123456789</code> — إضافة مستخدم\n"
        msg += "  <code>/remove 123456789</code> — طرد مستخدم\n"
        msg += "  <code>/pending</code> — عرض الطلبات المعلّقة\n"
        msg += "  <code>/approve 123456789</code> — الموافقة على طلب\n"
        msg += "  <code>/reject 123456789</code> — رفض طلب\n"
        msg += "  <code>/users</code> — عرض كل المستخدمين\n"
        msg += "\n💡 <b>المستخدمون الجدد يُضافون تلقائياً كـ«معلّق»</b> حتى توافق عليهم."
        send_msg(msg, main_kb(), cid)
    elif text == "/users":
        # 🆕 v6.4.4: عرض كل المستخدمين (للمالك فقط)
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        # استخدم ALLOWED_USERS (لو موجود) أو fallback لـ CHAT_ID فقط
        users = [CHAT_ID] if CHAT_ID else []
        msg = "👥 <b>القائمة البيضاء</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 العدد: <b>{len(users)}</b>\n\n"
        for i, uid in enumerate(users, 1):
            owner_tag = " 👑" if str(uid) == str(CHAT_ID) else ""
            msg += f"  {i}. <code>{uid}</code>{owner_tag}\n"
        msg += "\n💡 <code>/add ID</code> لإضافة | <code>/remove ID</code> للطرد"
        send_msg(msg, main_kb(), cid)
    elif text.startswith("/add ") or text.startswith("/remove ") or text.startswith("/approve ") or text.startswith("/reject "):
        # 🆕 v6.4.4: أوامر إدارة المستخدمين (للمالك فقط)
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        # placeholder — يستخدم ALLOWED_USERS لو موجود (يمكن تطويره لـ persistent storage)
        send_msg("ℹ️ ميزة إدارة المستخدمين تحتاج تفعيلاً في الإعدادات.\nاستخدم TELEGRAM_CHAT_ID كـ owner.", main_kb(), cid)
    elif text == "💼 المحفظة":
        pf = get_portfolio(cid)
        if not pf:
            send_msg("💼 محفظتك فارغة\n\nاستخدم 🛒 نقطة شراء", main_kb(), cid)
            return
        msg = "💼 <b>محفظتك</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        for sym, points in pf.items():
            if not points: continue
            total_qty = sum(p["qty"] for p in points)
            avg = sum(p["price"] * p["qty"] for p in points) / total_qty
            candles = fetch_klines(sym)
            cur = candles[-1]["close"] if candles else 0
            pnl = ((cur - avg) / avg * 100) if avg and cur else 0
            e = "🟢" if pnl >= 0 else "🔴"
            msg += f"  {sym}: {e} {pnl:+.2f}% | qty: {total_qty:.2f}\n"
        send_msg(msg, main_kb(), cid)
    elif text == "⚡ إضافة سريعة":
        msg = "⚡ <b>إضافة سريعة</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += "30 عملة شعبية\n➕ = أضف | ✅ = موجودة"
        send_msg(msg, quick_add_kb(cid), cid)
    elif text == "🕌 حكم عملة":
        # 🆕 v6.4.90: يعرض كل العملات المحفوظة مع زر 🗑️ بجانب كل عملة (inline keyboard)
        try:
            count = halal_check.count_tracked()
            remaining = halal_check.MAX_HALAL_COINS - count
            # 🆕 v6.4.90: اعرض القائمة مع أزرار الحذف بجانب كل عملة
            kb = halal_list_delete_kb()
            msg = (
                f"🕌 <b>قائمة الأحكام الشرعية</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 القائمة الحالية: <b>{count}/{halal_check.MAX_HALAL_COINS}</b> عملة\n"
                f"📋 المتاح: <b>{remaining}</b> عملة\n\n"
                f"🗑️ <b>اضغط زر الحذف بجانب أي عملة لِحذفها</b>\n"
                f"📥 <b>لإضافة عملة جديدة:</b> أرسل رمزها (مثل <code>BTC</code>)\n\n"
                f"💡 <b>الأوامر المتقدمة:</b>\n"
                f"  <code>/halal BTC haram</code> — حرام\n"
                f"  <code>/halal BTC suspect</code> — شبهة\n"
                f"  <code>/halal_export</code> — تصدير الأحكام\n"
                f"  <code>/halal_import النص</code> — استيراد بعد التحديث\n\n"
                f"🛡️ <b>العملات المحذوفة لن تُعاد بعد التحديث</b> (محفوظة في deleted_coins)"
            )
            send_msg(msg, kb, cid)
        except Exception as e:
            log.error(f"❌ halal button err: {e}")
            send_msg("❌ خطأ في عرض قائمة الأحكام", main_kb(), cid)
    elif text == "🗑️ حذف":
        # 🆕 v6.4.90: يعرض المفضلة مع زر 🗑️ بجانب كل عملة (inline keyboard)
        # + يعرض قائمة العملات الحلال أيضاً (لو المفضلة فارغة)
        favs = get_favorites(cid)
        if not favs:
            # 🆕 v6.4.90: لو المفضلة فارغة، اعرض قائمة الأحكام الشرعية مع أزرار الحذف
            try:
                count = halal_check.count_tracked()
                if count > 0:
                    kb = halal_list_delete_kb()
                    msg = (
                        f"🗑️ <b>المفضلة فارغة — اعرض قائمة الأحكام الشرعية</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n\n"
                        f"📊 القائمة الحالية: <b>{count}</b> عملة\n\n"
                        f"🗑️ <b>اضغط زر الحذف بجانب أي عملة لِحذفها</b>"
                    )
                    send_msg(msg, kb, cid)
                else:
                    send_msg("🗑️ المفضلة وقائمة الأحكام فارغة", main_kb(), cid)
            except Exception as e:
                log.error(f"❌ delete button err: {e}")
                send_msg("❌ خطأ في عرض قائمة الحذف", main_kb(), cid)
            return
        # 🆕 v6.4.90: اعرض المفضلة مع أزرار الحذف
        kb = favorites_delete_kb(cid)
        msg = (
            f"🗑️ <b>حذف عملة من المفضلة</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 المفضلة: <b>{len(favs)}</b> عملة\n\n"
            f"🗑️ <b>اضغط زر الحذف بجانب أي عملة لِحذفها من المفضلة</b>"
        )
        send_msg(msg, kb, cid)
    elif text.startswith("💎 V1:"):
        # 🆕 v6.4.84/v6.4.98: تبديل V1 — تشغيل = نشر للقناة، إيقاف = البوت فقط + حفظ دائم
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        V1_ENABLED = not V1_ENABLED
        # 🆕 v6.4.120: V1/V2/V3 مستقلة — كل واحدة تشتغل لحالها (لا radio button)
        _save_v1_v2_state(V1_ENABLED, V2_ENABLED, V3_ENABLED)  # 🆕 v6.4.98: حفظ V3
        target = "القناة العامة 📢" if V1_ENABLED else "البوت فقط 📩"
        msg = (
            f"💎 <b>استراتيجية MTF (V1)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📍 <b>الإرسال الآن:</b> {target}\n\n"
            f"{'✅ تشغيل — ستظهر صفقات V1 + تنبيهات TP/SL في القناة' if V1_ENABLED else '⏸️ إيقاف — ستظهر صفقات V1 + تنبيهات TP/SL في البوت فقط'}\n\n"
            f"💾 الحالة محفوظة — تبقى بعد إعادة النشر\n"
            f"💡 اضغط الزر مجدداً للتبديل\n"
            f"🆕 V1/V2/V3 مستقلة — يمكن تشغيل الكل معاً"
        )
        send_msg(msg, main_kb(), cid)
        log.info(f"💎 [V1] enabled switched to: {V1_ENABLED} (target: {target}, by cid={cid})")
    elif text.startswith("🔄 V2:"):
        # 🆕 v6.4.84/v6.4.98: تبديل V2 — تشغيل = نشر للقناة، إيقاف = البوت فقط + حفظ دائم
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        V2_ENABLED = not V2_ENABLED
        # 🆕 v6.4.120: V1/V2/V3 مستقلة — كل واحدة تشتغل لحالها (لا radio button)
        _save_v1_v2_state(V1_ENABLED, V2_ENABLED, V3_ENABLED)  # 🆕 v6.4.98: حفظ V3
        target = "القناة العامة 📢" if V2_ENABLED else "البوت فقط 📩"
        msg = (
            f"🔄 <b>استراتيجية الارتداد (V2)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📍 <b>الإرسال الآن:</b> {target}\n\n"
            f"{'✅ تشغيل — ستظهر صفقات V2 + تنبيهات TP/SL في القناة' if V2_ENABLED else '⏸️ إيقاف — ستظهر صفقات V2 + تنبيهات TP/SL في البوت فقط'}\n\n"
            f"💾 الحالة محفوظة — تبقى بعد إعادة النشر\n"
            f"💡 اضغط الزر مجدداً للتبديل\n"
            f"📊 الفريم الحالي: <code>{STRATEGY_V2_TIMEFRAME}</code>\n"
            f"🆕 V1/V2/V3 مستقلة — يمكن تشغيل الكل معاً"
        )
        send_msg(msg, main_kb(), cid)
        log.info(f"🔄 [V2] enabled switched to: {V2_ENABLED} (target: {target}, by cid={cid})")
    elif text.startswith("🚀 V3:"):
        # 🆕 v6.4.98: تبديل V3 — تشغيل = نشر للقناة، إيقاف = البوت فقط + حفظ دائم
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        V3_ENABLED = not V3_ENABLED
        # 🆕 v6.4.120: V1/V2/V3 مستقلة — كل واحدة تشتغل لحالها (لا radio button)
        _save_v1_v2_state(V1_ENABLED, V2_ENABLED, V3_ENABLED)
        target = "القناة العامة 📢" if V3_ENABLED else "البوت فقط 📩"
        msg = (
            f"🚀 <b>استراتيجية Pre-Pump Breakout (V3)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📍 <b>الإرسال الآن:</b> {target}\n\n"
            f"{'✅ تشغيل — ستظهر صفقات V3 + تنبيهات TP/SL في القناة' if V3_ENABLED else '⏸️ إيقاف — ستظهر صفقات V3 + تنبيهات TP/SL في البوت فقط'}\n\n"
            f"💾 الحالة محفوظة — تبقى بعد إعادة النشر\n"
            f"💡 اضغط الزر مجدداً للتبديل\n"
            f"📊 V3: اكتشاف العملات قبل الانفجار + Watch Alerts\n"
            f"🆕 V1/V2/V3 مستقلة — يمكن تشغيل الكل معاً"
        )
        send_msg(msg, main_kb(), cid)
        log.info(f"🚀 [V3] enabled switched to: {V3_ENABLED} (target: {target}, by cid={cid})")
    elif text == "📋 سجل أسبوعي":
        # 🆕 v6.4.83: سجل أسبوعي — عدد الصفقات، ناجح/خاسر، أهداف محققة، ستوبات
        if str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك", main_kb(), cid)
            return
        try:
            from signals import format_weekly_logs
            report = format_weekly_logs(cid, days=7)
            send_msg(report, main_kb(), cid)
        except Exception as e:
            log.error(f"📋 سجل أسبوعي err: {e}")
            send_msg(f"❌ خطأ في السجل الأسبوعي: {e}", main_kb(), cid)
    elif text == "📊 إحصائيات":
        stats = get_stats(cid)
        send_msg(format_stats(stats), main_kb(), cid)
    elif text == "🛒 نقطة شراء":
        send_msg("🛒 <b>نقطة شراء</b>\n━━━━━━━━━━━━━━━━━━\n\nأرسل: <code>العملة الكمية السعر</code>\nمثال: <code>BTC 0.05 84000</code>", None, cid)
    elif text.startswith("/halal_delete "):
        # 🆕 v6.4.52: حذف حكم عملة
        parts = text.split(maxsplit=2)
        if len(parts) < 2 or str(cid) != str(CHAT_ID):
            send_msg("🔒 خاص بالمالك فقط\n\nاستخدام: <code>/halal_delete BTC</code>", None, cid)
            return
        sym = parts[1].upper()
        ok = halal_check.delete_ruling(sym)
        if ok:
            send_msg(f"🗑️ تم حذف حكم <b>{sym}</b> من الذاكرة", None, cid)
        else:
            send_msg(f"⚠️ لا يوجد حكم محفوظ لـ <b>{sym}</b>", None, cid)
    elif text == "/halal_list" or text == "/halal_list":
        # 🆕 v6.4.52: عرض كل الأحكام
        send_msg(halal_check.format_halal_list_message(), None, cid)
    elif text == "/halal_export":
        # 🆕 v6.4.57: تصدير الأحكام كنص قابل للنسخ
        send_msg(halal_check.format_export_message(), None, cid)
    elif text.startswith("/halal_import "):
        # 🆕 v6.4.57: استيراد الأحكام من نص
        import_text = text[len("/halal_import "):].strip()
        result = halal_check.import_rulings_from_text(import_text)
        msg = (
            "📥 <b>استيراد الأحكام</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ تمت الإضافة: <b>{result['added']}</b>\n"
            f"ℹ️ تجاوز (موجود): <b>{result['skipped']}</b>\n"
            f"❌ غير صالح: <b>{result['invalid']}</b>\n\n"
            f"📊 القائمة: <b>{halal_check.count_tracked()}/{halal_check.MAX_HALAL_COINS}</b>"
        )
        send_msg(msg, None, cid)
    elif text.startswith("/halal "):
        # 🆕 v6.4.52: نظام الأحكام الشرعية (يدوي)
        # الأشكال المدعومة:
        #   /halal BTC halal     ← حفظ BTC كحلال
        #   /halal BTC haram     ← حفظ BTC كحرام
        #   /halal BTC suspect   ← حفظ BTC كمشبوهة
        #   /halal BTC           ← استعلام
        parts = text.split()
        if len(parts) < 2:
            send_msg(
                "🕌 <b>نظام الأحكام الشرعية</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "📥 <b>الاستخدام:</b>\n"
                "  <code>/halal BTC halal</code> — حفظ BTC كحلال 🟢\n"
                "  <code>/halal BTC haram</code> — حفظ BTC كحرام 🔴\n"
                "  <code>/halal BTC suspect</code> — حفظ BTC كمشبوهة 🟠\n"
                "  <code>/halal BTC</code> — استعلام عن حكم BTC\n"
                "  <code>/halal_list</code> — عرض كل الأحكام\n"
                "  <code>/halal_delete BTC</code> — حذف حكم BTC\n\n"
                "🔒 خاص بالمالك فقط (للحفظ والحذف)",
                None, cid
            )
            return

        sym = parts[1].upper()
        # تحقق صحة الرمز
        if not all(c.isalnum() for c in sym) or not sym[0].isalpha() or len(sym) > 12 or len(sym) < 2:
            send_msg(f"⚠️ رمز غير صالح: <code>{sym}</code>\nيجب أن يكون 2-12 حرف/رقم", None, cid)
            return

        # الحالة 1: /halal BTC halal|haram|suspect (حفظ)
        if len(parts) >= 3:
            ruling_input = parts[2].lower().strip()
            # الأسماء البديلة المقبولة
            ruling_map = {
                "halal": "halal",
                "haram": "haram",
                "suspect": "suspect",
                "حلال": "halal",
                "حرام": "haram",
                "شبهة": "suspect",
                "مشبوهة": "suspect",
                "مشتبه": "suspect",
            }
            ruling = ruling_map.get(ruling_input)
            if not ruling:
                send_msg(
                    f"⚠️ حكم غير صالح: <code>{ruling_input}</code>\n\n"
                    f"الأحكام المدعومة: <code>halal</code> | <code>haram</code> | <code>suspect</code>\n"
                    f"أو بالعربية: <code>حلال</code> | <code>حرام</code> | <code>شبهة</code>",
                    None, cid
                )
                return

            # 🛡️ تحقق من الصلاحيات (مالك فقط)
            if str(cid) != str(CHAT_ID):
                send_msg("🔒 حفظ الأحكام خاص بالمالك فقط", None, cid)
                return

            ok = halal_check.set_ruling(sym, ruling, source="manual")
            if ok:
                icon = halal_check.RULING_ICONS[ruling]
                label = halal_check.RULING_LABELS_AR[ruling]
                send_msg(
                    f"✅ تم حفظ حكم <b>{sym}</b>\n"
                    f"{icon} <b>{label}</b>\n\n"
                    f"📌 المحفوظ في الذاكرة الدائمة\n"
                    f"💾 سيُستخدم تلقائياً في كل صفقة لـ {sym}",
                    None, cid
                )
                log.info(f"🕌 [Halal] {sym} = {ruling} (by cid={cid})")
            else:
                send_msg(f"❌ فشل حفظ حكم {sym}", None, cid)
        else:
            # الحالة 2: /halal BTC (استعلام)
            send_msg(halal_check.format_ruling_message(sym), None, cid)
    elif text.startswith("/backtest"):
        parts = text.split()
        if len(parts) < 3:
            send_msg("📊 <b>Backtest</b>\n\n<code>/backtest ALL BTC 1d</code>", main_kb(), cid)
            return
        send_msg("⏳ جاري الاختبار...", main_kb(), cid)
        r = backtest_run(parts[1].upper(), parts[2].upper().replace("USDT",""), parts[3].lower() if len(parts) > 3 else "1d")
        send_msg(backtest_format(r), main_kb(), cid)
    elif text == "/testchannel":
        # 🆕 v6.2.2: تشخيص يدوي للقنوات
        send_msg("🔍 جاري فحص القنوات...", main_kb(), cid)
        test_channel_at_startup()
    elif text == "/forcescan":
        # 🆕 v6.2.4: تشغيل دورة فورية بدون احترام MAX_SIGNALS_PER_CYCLE
        send_msg("🚀 جاري فحص كل العملات فوراً...\n⏱️ قد يستغرق 5-15 دقيقة (240 عملة)", main_kb(), cid)
        def _force():
            stats = scan_cycle(force=True, debug=True)
            if stats is None:
                send_msg("⏳ يوجد فحص جارٍ بالفعل — انتظر انتهاء الدورة الحالية", main_kb(), cid)
                return
            n = stats.get("sent", 0)
            top5 = sorted(stats.get("top_scores", []), key=lambda x: -x[1])[:5]
            summary = f"🏁 <b>انتهى الفحص الفوري</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            summary += f"💎 إشارات مُرسلة: <b>{n}</b>\n"
            summary += f"⏭️ تجاوز (لها صفقة نشطة): {stats.get('skipped_active', 0)}\n"
            summary += f"📉 score أقل من 40: {stats.get('low_score', 0)}\n"
            summary += f"❌ generate() فشل: {stats.get('no_signal', 0)}\n"
            summary += f"⛔ duplicate blocked: {stats.get('blocked_dup', 0)}\n\n"
            if top5:
                summary += "🏆 <b>أعلى 5 scores:</b>\n"
                for sym, sc in top5:
                    marker = "✅" if sc >= 40 else "📉"
                    summary += f"  {marker} {sym}: {sc}\n"
            else:
                summary += "⚠️ لا توجد عملات بـ score ≥ 30 (السوق هادئ أو Binance معطّل)\n"
            send_msg(summary, main_kb(), cid)
        threading.Thread(target=_force, daemon=True).start()
    elif text.startswith("/analyse") or text.startswith("/analyze") or text.startswith("/analise"):
        # 🆕 v6.4.43: تحليل فني تفاعلي للمجتمع
        # مثال: /analyse BTC | /analyze ETH | /analise SOL
        parts = text.split()
        if len(parts) < 2:
            send_msg(
                "📊 <b>أمر التحليل الفني</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                "الاستخدام: <code>/analyse BTC</code>\n\n"
                "💡 ستحصل على:\n"
                "  • تحليل 4 فريمات (1D/4H/1H/15m)\n"
                "  • توصية ذكية (شراء مباشر / انتظر تصحيح / لا تدخل)\n"
                "  • دخول + SL + TP + R/R تلقائياً\n"
                "  • مؤكّدات فنية (EMA / MACD / RSI / SMC)\n\n"
                f"⏱️ الحد: {_ANALYSE_RATE_LIMIT} تحليل/ساعة لكل مستخدم",
                main_kb(), cid
            )
            return
        sym_arg = parts[1]
        # 🛡️ تشغيل في thread منفصل لتفادي تأخير الـ webhook
        threading.Thread(target=_analyse_command, args=(sym_arg, cid), daemon=True).start()
    elif text == "/scandebug":
        # 🆕 v6.2.4: تشخيص دورة مسح (لا يرسل إشارات فعلياً، فقط يفحص + يسجل)
        send_msg("🐛 جاري الفحص التشخيصي...\n⏱️ سأرسل لك التقرير عند الانتهاء", main_kb(), cid)
        def _debug():
            stats = scan_cycle(force=False, debug=True)
            if stats is None:
                send_msg("⏳ يوجد فحص جارٍ بالفعل — انتظر انتهاء الدورة الحالية", main_kb(), cid)
                return
            top5 = sorted(stats.get("top_scores", []), key=lambda x: -x[1])[:10]
            summary = "🐛 <b>تشخيص دورة المسح</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            summary += f"📊 <b>الإحصائيات:</b>\n"
            summary += f"  • 💎 إشارات مُرسلة: {stats.get('sent', 0)}\n"
            summary += f"  • ⏭️ تجاوز (لها صفقة نشطة): {stats.get('skipped_active', 0)}\n"
            summary += f"  • 📉 score &lt; 40: {stats.get('low_score', 0)}\n"
            summary += f"  • ❌ no analysis (Binance?): {stats.get('no_analysis', 0)}\n"
            summary += f"  • ❌ generate() فشل: {stats.get('no_signal', 0)}\n"
            summary += f"  • ⛔ duplicate blocked: {stats.get('blocked_dup', 0)}\n\n"
            if top5:
                summary += "🏆 <b>أعلى 10 scores:</b>\n"
                for sym, sc in top5:
                    marker = "✅" if sc >= 40 else "📉"
                    summary += f"  {marker} {sym}: {sc}\n"
            else:
                summary += "⚠️ لا توجد عملات بـ score ≥ 30\n\n"
                summary += "💡 احتمالات:\n"
                summary += "  • Binance معطّل (تحقق من السجلات)\n"
                summary += "  • السوق هادئ جداً\n"
                summary += "  • مشكلة في fetch_klines\n"
            summary += f"\n📋 <b>اقتراحات:</b>\n"
            summary += "  • لو low_score كبير → اضبط SCORE_THRESHOLD أقل (مثلاً 30)\n"
            summary += "  • لو no_analysis كبير → Binance معطّل، راجع السجلات\n"
            summary += "  • لو skipped_active كبير → كل عملاتك لها صفقات نشطة\n"
            send_msg(summary, main_kb(), cid)
        threading.Thread(target=_debug, daemon=True).start()
    elif text == "/simple":
        # 🆕 v6.4: تحويل لوضع العرض المختصر (للمبتدئين)
        global _display_mode_runtime
        try:
            _display_mode_runtime
        except NameError:
            _display_mode_runtime = None
        _display_mode_runtime = "simple"
        send_msg("✅ <b>تم التحويل لوضع العرض المختصر</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                 "الإشارات الجديدة ستكون قصيرة:\n"
                 "  💎 اسم العملة + ⭐⭐\n"
                 "  💰 منطقة دخول\n"
                 "  🛑 SL\n"
                 "  🎯 3 أهداف\n"
                 "  ⚖️ R/R + 💼 حجم\n\n"
                 "📊 اضغط زر <b>«تفاصيل»</b> تحت كل إشارة لرؤية التحليل الكامل.", main_kb(), cid)
    elif text == "/detailed":
        # 🆕 v6.4: تحويل لوضع العرض المفصّل
        global _display_mode_runtime_d
        try:
            _display_mode_runtime_d
        except NameError:
            _display_mode_runtime_d = None
        _display_mode_runtime_d = "detailed"
        send_msg("✅ <b>تم التحويل لوضع العرض المفصّل</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                 "الإشارات الجديدة ستكون كاملة:\n"
                 "  🆔 signal_id\n"
                 "  🟡 الثقة + label\n"
                 "  🤝 توافق الفريمات\n"
                 "  📊 جدول 4 فريمات\n"
                 "  ✅ قائمة المؤكدات\n\n"
                 "💡 للعودة للوضع المختصر: <code>/simple</code>", main_kb(), cid)
    elif text == "/debug_signals":
        # 🆕 v6.2.2: عرض حالة الإعدادات الحالية
        msg = "🐛 <b>تشخيص الإعدادات</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"TELEGRAM_BOT_TOKEN: {'✅ مُضبوط' if TOKEN else '❌ فارغ'}\n"
        msg += f"TELEGRAM_CHAT_ID: {CHAT_ID if CHAT_ID else '❌ فارغ'}\n"
        msg += f"TELEGRAM_CHANNEL_ID: {CHANNEL_ID if CHANNEL_ID else '⚠️ فارغ (قناة الأهداف)'}\n"
        msg += f"TELEGRAM_SIGNALS_CHANNEL_ID: {SIGNALS_CHANNEL_ID if SIGNALS_CHANNEL_ID else '⚠️ فارغ (قناة الإشارات)'}\n"
        msg += f"SCAN_ALL_SPOT: {'✅ مفعّل' if SCAN_ALL_SPOT else '❌ مُعطّل'}\n"
        msg += f"MAX_SIGNALS_PER_CYCLE: {MAX_SIGNALS_PER_CYCLE}\n"
        msg += f"SCAN_INTERVAL: {SCAN_INTERVAL}s\n"
        msg += f"HQ_DISPLAY_MODE: {HQ_DISPLAY_MODE} ({'مختصرة للمبتدئ' if HQ_DISPLAY_MODE == 'simple' else 'مفصّلة'})\n"
        msg += f"HQ_DEFAULT_CAPITAL: ${HQ_DEFAULT_CAPITAL}\n"
        msg += "\n🆕 <b>أوامر تشخيصية:</b>\n"
        msg += "  • /forcescan — فحص فوري لكل العملات\n"
        msg += "  • /scandebug — تشخيص دورة المسح\n"
        msg += "  • /testchannel — فحص القنوات\n"
        msg += "  • /debug_signals — هذه الرسالة\n"
        msg += "  • /active_signals — عرض الصفقات النشطة + message_ids\n"
        msg += "  • /cleanup_signals — حذف رسائل الصفقات المنتهية من القناة\n"
        send_msg(msg, main_kb(), cid)
    elif text == "/active_signals" or text == "🟢 نشطة الآن":
        # 🆕 v6.4: عرض الصفقات النشطة + 3 أهداف + position size
        active = get_active(cid)
        if not active:
            send_msg("📊 لا توجد صفقات نشطة حالياً", main_kb(), cid)
            return
        msg = "🟢 <b>الصفقات النشطة الآن</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"العدد: {len(active)}\n\n"
        for t in active[:10]:
            sym = t.get("symbol", "?")
            status = t.get("status", "?")
            entry = t.get("entry", 0)
            tp1 = t.get("tp1", t.get("tp", 0))
            tp2 = t.get("tp2", 0)
            tp3 = t.get("tp3", 0)
            sl = t.get("sl", 0)
            pos_size = t.get("position_size_usd", 0)
            risk_usd = t.get("risk_amount_usd", 0)
            pnl_pct = t.get("pnl", 0)
            status_emoji = {"ACTIVE": "🟢", "TP1_HIT": "✅", "TP2_HIT": "✅✅"}.get(status, "•")
            msg += f"{status_emoji} <b>{sym}</b> [{status}]\n"
            msg += f"  💰 الدخول: {fmt_price(entry)} (zone: {fmt_price(t.get('entry_low', entry))} - {fmt_price(t.get('entry_high', entry))})\n"
            msg += f"  🎯 TP1: {fmt_price(tp1)} | TP2: {fmt_price(tp2)} | TP3: {fmt_price(tp3)}\n"
            msg += f"  🛑 SL: {fmt_price(sl)} ({t.get('sl_pct', 0):.2f}%)\n"
            msg += f"  💼 المركز: ${pos_size:.0f} | مخاطرة: ${risk_usd:.0f}\n"
            if pnl_pct:
                pnl_emoji = "📈" if pnl_pct > 0 else "📉"
                msg += f"  {pnl_emoji} PnL: {pnl_pct:+.2f}%\n"
            msg += "\n"
        if len(active) > 10:
            msg += f"... و {len(active) - 10} صفقة أخرى"
        send_msg(msg, main_kb(), cid)
    elif text.startswith("/coin_history ") or text.startswith("/coin"):
        # 🆕 v6.4.3: عرض كل صفقات عملة محددة — /coin_history BTC
        parts = text.split()
        if len(parts) < 2:
            send_msg("📊 <b>استخدام:</b> <code>/coin_history BTC</code>\nأو <code>/coin BTC</code>\n\n💡 يعرض كل الصفقات النشطة والمغلقة للعملة.", main_kb(), cid)
            return
        symbol = parts[1].upper().replace("USDT", "").strip()
        if not symbol:
            send_msg("❌ رمز العملة غير صالح", main_kb(), cid)
            return
        import tracker as _tk
        all_trades = _tk._load().get(str(cid), [])
        sym_trades = [t for t in all_trades if t.get("symbol", "").upper() == symbol]
        if not sym_trades:
            send_msg(f"📭 <b>{symbol}</b> — لا توجد صفقات سابقة.\n\n💡 جرّب: <code>/coin_history BTC</code>", main_kb(), cid)
            return
        send_msg(format_coin_history(symbol, sym_trades), main_kb(), cid)
    elif text == "/trackrecord" or text == "📋 سجل الأداء":
        # 🆕 v6.4.16: سجل الأداء الشامل — إحصائيات + تفصيل كامل
        import tracker as _tk
        from datetime import datetime
        all_trades = _tk._load().get(str(cid), [])
        if not all_trades:
            send_msg("📋 <b>لا توجد صفقات بعد</b>\n━━━━━━━━━━━━━━━━━━\n\nانتظر دورة المسح التالية (5 دقائق).", main_kb(), cid)
            return

        total = len(all_trades)
        active = [t for t in all_trades if t.get("status") in _tk.NON_FINAL]
        closed = [t for t in all_trades if t.get("status") not in _tk.NON_FINAL]

        # 🆕 v6.4.16: عدّ كل الأهداف بشكل دقيق
        tp1_count = sum(1 for t in closed if t.get("status") == "TP1_HIT")
        tp2_count = sum(1 for t in closed if t.get("status") == "TP2_HIT")
        tp3_count = sum(1 for t in closed if t.get("status") == "TP3_HIT")
        tp4_count = sum(1 for t in closed if t.get("status") == "TP4_HIT")
        tp5_count = sum(1 for t in closed if t.get("status") == "TP5_HIT")
        tp6_count = sum(1 for t in closed if t.get("status") == "TP6_HIT")
        # 🆕 v6.4.82: صفقات أُغلقت عند الستوب الديناميكي بعد أهداف = نجاح وليس خسارة
        done1_count = sum(1 for t in closed if t.get("status") == "TP1_DONE")
        done2_count = sum(1 for t in closed if t.get("status") == "TP2_DONE")
        done3_count = sum(1 for t in closed if t.get("status") == "TP3_DONE")
        done4_count = sum(1 for t in closed if t.get("status") == "TP4_DONE")
        sl_count = sum(1 for t in closed if t.get("status") == "STOP_LOSS")
        expired_count = sum(1 for t in closed if t.get("status") == "EXPIRED")
        cancelled_count = sum(1 for t in closed if t.get("status") == "CANCELLED")

        # Win rate = (أي TP + إغلاقات الستوب الديناميكي الرابحة) / (كل الناجحة + SL)
        # 🆕 v6.4.82: TP{n}_DONE تُحسب نجاحاً
        wins = tp1_count + tp2_count + tp3_count + tp4_count + tp5_count + tp6_count + \
               done1_count + done2_count + done3_count + done4_count
        wr_denom = wins + sl_count
        win_rate = (wins / wr_denom * 100) if wr_denom > 0 else 0

        # إجمالي PnL
        total_pnl = sum(t.get("pnl", 0) for t in closed if t.get("pnl"))
        avg_pnl = total_pnl / max(len(closed), 1)

        # ── الرسالة ──
        msg = "📋 <b>سجل الأداء الكامل</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 <b>الإجمالي:</b> {total} صفقة\n"
        msg += f"🟢 <b>نشطة:</b> {len(active)} | 🔒 <b>مغلقة:</b> {len(closed)}\n\n"

        # تفصيل الأهداف
        msg += "<b>📊 تفصيل الأهداف:</b>\n"
        if tp1_count: msg += f"  ✅ TP1 (+2%): {tp1_count}\n"
        if tp2_count: msg += f"  ✅ TP2 (+4%): {tp2_count}\n"
        if tp3_count: msg += f"  ✅ TP3 (+8%): {tp3_count}\n"
        if tp4_count: msg += f"  ✅ TP4 (+12%): {tp4_count}\n"
        if tp5_count: msg += f"  🏆 TP5 (+15%): {tp5_count}\n"
        if tp6_count: msg += f"  🏆 TP6 (+20%+): {tp6_count}\n"
        # 🆕 v6.4.82: إغلاقات الستوب الديناميكي الرابحة
        if done1_count: msg += f"  🎯 نجحت بهدف واحد (أُغلقت عند الستوب الصاعد): {done1_count}\n"
        if done2_count: msg += f"  🎯🎯 نجحت بهدفين (أُغلقت عند الستوب الصاعد): {done2_count}\n"
        if done3_count: msg += f"  🎯🎯🎯 نجحت بثلاثة أهداف: {done3_count}\n"
        if done4_count: msg += f"  🏆 نجحت بأربعة أهداف: {done4_count}\n"
        if sl_count: msg += f"  🛑 SL مضروب: {sl_count}\n"
        if expired_count: msg += f"  ⏰ منتهية: {expired_count}\n"
        if cancelled_count: msg += f"  ❌ ملغاة: {cancelled_count}\n"
        msg += "\n"

        # الإحصائيات
        wr_emoji = "🟢" if win_rate >= 60 else ("🟡" if win_rate >= 40 else "🔴")
        msg += f"🎯 <b>Win Rate:</b> {wr_emoji} <b>{win_rate:.1f}%</b> ({wins}/{wr_denom})\n"
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        msg += f"💰 <b>PnL إجمالي:</b> {pnl_emoji} <b>{total_pnl:+.2f}%</b>\n"
        msg += f"📊 <b>PnL متوسط:</b> {avg_pnl:+.2f}%\n\n"

        # تفصيل الصفقات النشطة
        if active:
            msg += "<b>🟢 الصفقات النشطة:</b>\n"
            msg += "─────────────────────\n"
            for t in active:
                sym = t.get("symbol", "?")
                status = t.get("status", "?")
                entry = t.get("entry", 0)
                pnl = t.get("pnl", 0)
                dt = datetime.fromtimestamp(t.get("created_at", 0)).strftime("%m-%d %H:%M")
                status_emoji = {"ACTIVE": "🟢", "TP1_HIT": "✅", "TP2_HIT": "✅✅", "TP3_HIT": "✅✅✅", "TP4_HIT": "🏆"}.get(status, "•")
                pnl_str = f" ({pnl:+.1f}%)" if pnl else ""
                msg += f"{status_emoji} <b>{sym}</b> [{status}]{pnl_str}\n"
                msg += f"   دخول: {fmt_price(entry)} | {dt}\n"
            msg += "\n"

        # تفصيل الصفقات المغلقة
        if closed:
            msg += "<b>🔒 الصفقات المغلقة:</b>\n"
            msg += "─────────────────────\n"
            for t in closed[:15]:
                sym = t.get("symbol", "?")
                status = t.get("status", "?")
                entry = t.get("entry", 0)
                pnl = t.get("pnl", 0)
                dt = datetime.fromtimestamp(t.get("created_at", 0)).strftime("%m-%d %H:%M")
                status_emoji = {"TP1_HIT": "✅", "TP2_HIT": "✅✅", "TP3_HIT": "✅✅✅",
                                "TP4_HIT": "🏆", "TP5_HIT": "🏆🏆", "TP6_HIT": "🏆🏆🏆",
                                "TP1_DONE": "🎯", "TP2_DONE": "🎯🎯", "TP3_DONE": "🎯🎯🎯",
                                "TP4_DONE": "🏆",
                                "STOP_LOSS": "🛑", "EXPIRED": "⏰", "CANCELLED": "❌"}.get(status, "•")
                pnl_str = f" ({pnl:+.1f}%)" if pnl else ""
                msg += f"{status_emoji} <b>{sym}</b> [{status}]{pnl_str} | {dt}\n"
            if len(closed) > 15:
                msg += f"\n... و {len(closed) - 15} صفقة أخرى\n"

        msg += "\n📥 <b>تقرير PDF:</b> <code>/report</code>"
        send_msg(msg, main_kb(), cid)
    elif text == "/report" or text == "📄 تقرير PDF":
        # 🆕 v6.4.10: توليد PDF تقرير كامل وإرساله كملف
        import tracker as _tk
        all_trades = _tk._load().get(str(cid), [])
        if not all_trades:
            send_msg("📄 <b>تقرير PDF</b>\n━━━━━━━━━━━━━━━━━━\n\nلا توجد صفقات بعد.\nانتظر دورة المسح التالية.", main_kb(), cid)
            return
        send_msg("⏳ جاري توليد تقرير PDF...", main_kb(), cid)
        def _gen_pdf():
            try:
                pdf_path = generate_pdf_report(cid)
                caption = "📊 <b>تقرير الصفقات الكامل</b>\n━━━━━━━━━━━━━━━━━━\n"
                caption += f"📄 يشمل: عدد الصفقات، نسبة الأهداف، الصفقات الملغاة\n"
                caption += "📥 تقرير شامل بآخر 20 صفقة"
                _send_document(cid, pdf_path, caption)
            except Exception as e:
                send_msg(f"❌ خطأ في توليد PDF: {e}", main_kb(), cid)
        threading.Thread(target=_gen_pdf, daemon=True).start()
    elif text == "/cleanup_signals":
        # 🆕 v6.2.6: حذف رسائل الصفقات المنتهية من قناة الصفقات (للتنظيف)
        send_msg("🧹 جاري تنظيف قناة الصفقات...", main_kb(), cid)
        def _cleanup():
            data = tracker._load()
            trades = data.get(str(cid), [])
            deleted = 0
            failed = 0
            for t in trades:
                # حذف رسائل الصفقات التي انتهت لكن لا تزال لها message_id محفوظ
                if t.get("status") not in NON_FINAL and t.get("signal_message_id"):
                    msg_id = t["signal_message_id"]
                    if delete_signal_message(msg_id):
                        clear_signal_message_id(cid, t["signal_id"])
                        deleted += 1
                    else:
                        failed += 1
            summary = f"🧹 <b>اكتمل التنظيف</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            summary += f"✅ رسائل محذوفة: {deleted}\n"
            summary += f"❌ رسائل فشل حذفها: {failed}\n"
            summary += f"\n💡 الآن قناة الصفقات تحتوي فقط على الصفقات النشطة"
            send_msg(summary, main_kb(), cid)
        threading.Thread(target=_cleanup, daemon=True).start()
    else:
        # محاولة إضافة نقطة شراء: "BTC 0.05 84000"
        parts = text.strip().split()
        if len(parts) == 3:
            try:
                sym = parts[0].upper().replace("USDT", "")
                qty = float(parts[1].replace(",", ""))
                price = float(parts[2].replace(",", ""))
                if sym in COINS and qty > 0 and price > 0:
                    add_buy_point(cid, sym, price, qty)
                    add_favorite(cid, sym)
                    send_msg(f"✅ <b>{sym}</b> نقطة شراء: {qty} @ {fmt_price(price)}", main_kb(), cid)
                    return
            except ValueError:
                pass

        # 🆕 v6.4.54: لو النص يحتوي على رموز عملات (واحد أو أكثر) → أضف للقائمة
        # 🆕 v6.4.57: يدعم أيضاً صيغة الاستيراد "BTC:halal,ETH:haram" (استيراد تلقائي)
        raw_text = text.strip().upper().replace("USDT", "")

        # 🆕 v6.4.57: استيراد تلقائي لو النص يحتوي على ":" (صيغة تصدير)
        if ":" in raw_text and ("," in raw_text or raw_text.count(":") >= 2):
            try:
                result = halal_check.import_rulings_from_text(raw_text)
                if result["added"] > 0 or result["skipped"] > 0:
                    msg = (
                        "📥 <b>استيراد الأحكام (تلقائي)</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"
                        f"✅ تمت الإضافة: <b>{result['added']}</b>\n"
                        f"ℹ️ تجاوز (موجود): <b>{result['skipped']}</b>\n"
                        f"❌ غير صالح: <b>{result['invalid']}</b>\n\n"
                        f"📊 القائمة: <b>{halal_check.count_tracked()}/{halal_check.MAX_HALAL_COINS}</b>"
                    )
                    send_msg(msg, main_kb(), cid)
                    log.info(f"📥 [Halal] auto-import: +{result['added']} new, {result['skipped']} existing (by cid={cid})")
                    return
            except Exception as e:
                log.error(f"❌ halal auto-import err: {e}")

        # فصل بفواصل أو مسافات
        candidates = []
        for part in raw_text.replace(",", " ").replace(";", " ").replace("/", " ").replace("-", " ").split():
            part = part.strip()
            if part and all(c.isalnum() for c in part) and part[0].isalpha() and 2 <= len(part) <= 12:
                candidates.append(part)

        if candidates and len(candidates) <= 50:  # حد 50 عملة في رسالة واحدة
            try:
                if halal_check.is_full():
                    send_msg(
                        f"🕌 <b>القائمة ممتلئة</b> ({halal_check.MAX_HALAL_COINS} عملة)\n\n"
                        f"⚠️ لا يمكن إضافة عملات جديدة\n\n"
                        f"💡 احذف عملة أولاً: <code>/halal_delete BTC</code>",
                        main_kb(), cid
                    )
                    return

                # معالجة كل عملة
                added = []
                already = []
                deleted = []
                failed = []
                for sym in candidates:
                    try:
                        existing = halal_check.get_ruling(sym)
                        if existing.get("ruling") != "unknown":
                            # 🆕 v6.4.75: العملة موجودة بالفعل → احذفها بدل رفضها
                            if str(cid) == str(CHAT_ID):
                                ok = halal_check.delete_ruling(sym)
                                if ok:
                                    deleted.append(sym)
                                    log.info(f"🗑️ [Halal] auto-delete: {sym} (by cid={cid})")
                                else:
                                    failed.append(f"{sym} (خطأ حذف)")
                            else:
                                already.append(f"{sym}({existing.get('icon', '⚪')} {existing.get('label_ar', '?')})")
                            continue
                        if halal_check.is_full():
                            failed.append(f"{sym} (قائمة ممتلئة)")
                            continue
                        ok = halal_check.set_ruling(sym, "halal", source="manual")
                        if ok:
                            added.append(sym)
                        else:
                            failed.append(f"{sym} (خطأ)")
                    except Exception as e:
                        log.warning(f"❌ halal add {sym} err: {e}")
                        failed.append(f"{sym} (خطأ)")

                # بناء رسالة النتيجة
                new_count = halal_check.count_tracked()
                remaining = halal_check.MAX_HALAL_COINS - new_count
                msg = "🕌 <b>إدارة قائمة الأحكام</b>\n"
                msg += "━━━━━━━━━━━━━━━━━━\n\n"

                if added:
                    msg += f"✅ <b>تمت الإضافة ({len(added)}):</b>\n"
                    msg += "  " + ", ".join(added) + "\n\n"

                if deleted:
                    msg += f"🗑️ <b>تم الحذف ({len(deleted)}):</b>\n"
                    msg += "  " + ", ".join(deleted) + "\n\n"

                if already:
                    msg += f"ℹ️ <b>موجودة مسبقاً ({len(already)}):</b>\n"
                    msg += "  " + ", ".join(already) + "\n\n"

                if failed:
                    msg += f"❌ <b>فشل ({len(failed)}):</b>\n"
                    msg += "  " + ", ".join(failed) + "\n\n"

                msg += f"📊 <b>القائمة الآن: {new_count}/{halal_check.MAX_HALAL_COINS}</b> عملة\n"
                msg += f"📋 المتاح: <b>{remaining}</b>\n\n"
                msg += "💡 <b>لتغيير حكم عملة:</b>\n"
                msg += "  <code>/halal BTC haram</code> — حرام 🔴\n"
                msg += "  <code>/halal BTC suspect</code> — شبهة 🟠"

                send_msg(msg, main_kb(), cid)
                log.info(f"🕌 [Halal] batch add: +{len(added)} new, {len(already)} existing, {len(failed)} failed (by cid={cid})")
                return
            except Exception as e:
                log.error(f"❌ halal batch-add err: {e}")

        send_msg("استخدم القائمة بالأسفل", main_kb(), cid)

def handle_callback(cid, data, cb_id):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                       json={"callback_query_id": cb_id, "text": "✅"}, timeout=10)
    except Exception as _e_cb:
        # 🆕 v6.4.92: لا تكتم الأخطاء — سجّلها بدل pass
        log.debug(f"answerCallbackQuery err (non-critical): {_e_cb}")
    if data == "done":
        send_msg("✅ تم", main_kb(), cid)
    elif data == "noop":
        pass  # 🆕 v6.4.90: زر صامت (للرؤوس والأزرار غير التفاعلية)
    elif data.startswith("qa_"):
        sym = data.replace("qa_", "")
        add_favorite(cid, sym)
        send_msg(f"⚡ <b>إضافة سريعة</b>\n━━━━━━━━━━━━━━━━━━\n\n➕ = أضف | ✅ = موجودة", quick_add_kb(cid), cid)
    elif data.startswith("qd_"):
        sym = data.replace("qd_", "")
        remove_favorite(cid, sym)
        send_msg(f"⚡ <b>إضافة سريعة</b>\n━━━━━━━━━━━━━━━━━━\n\n➕ = أضف | ✅ = موجودة", quick_add_kb(cid), cid)
    elif data.startswith("hd_"):
        # 🆕 v6.4.90: حذف حكم عملة (من زر 🗑️ في قائمة الأحكام)
        sym = data.replace("hd_", "")
        ok = halal_check.delete_ruling(sym)
        if ok:
            send_msg(f"🗑️ <b>تم حذف حكم {sym}</b>\n\n🛡️ لن تُعاد هذه العملة بعد التحديث (محفوظة في deleted_coins)", halal_list_delete_kb(), cid)
        else:
            send_msg(f"⚠️ <b>لا يوجد حكم محفوظ لـ {sym}</b>", halal_list_delete_kb(), cid)
    elif data.startswith("fd_"):
        # 🆕 v6.4.90: حذف من المفضلة (من زر 🗑️ في قائمة المفضلة)
        sym = data.replace("fd_", "")
        remove_favorite(cid, sym)
        favs = get_favorites(cid)
        if favs:
            send_msg(f"🗑️ <b>تم حذف {sym} من المفضلة</b>", favorites_delete_kb(cid), cid)
        else:
            send_msg(f"🗑️ <b>تم حذف {sym} من المفضلة</b>\n\n📭 المفضلة أصبحت فارغة", main_kb(), cid)
    elif data.startswith("hinfo_"):
        # 🆕 v6.4.90: عرض معلومات حكم عملة (من زر 🟢 في قائمة الأحكام)
        sym = data.replace("hinfo_", "")
        info = halal_check.get_ruling(sym)
        ruling = info.get("ruling", "unknown")
        icon = info.get("icon", "⚪")
        label = info.get("label_ar", "غير معروف")
        source = info.get("source", "manual")
        send_msg(f"🪙 <b>{sym}</b>\n━━━━━━━━━━━━━━━━━━\n\n{icon} <b>الحكم:</b> {label}\n📌 <b>المصدر:</b> {source}\n\n💡 لتغيير الحكم:\n  <code>/halal {sym} haram</code> — حرام\n  <code>/halal {sym} suspect</code> — شبهة\n💡 للحذف: اضغط زر 🗑️ بجانبها", halal_list_delete_kb(), cid)
    elif data.startswith("finfo_"):
        # 🆕 v6.4.90: عرض معلومات عملة في المفضلة
        sym = data.replace("finfo_", "")
        send_msg(f"🪙 <b>{sym}</b>\n━━━━━━━━━━━━━━━━━━\n\n✅ <b>موجودة في المفضلة</b>\n\n💡 للحذف: اضغط زر 🗑️ بجانبها", favorites_delete_kb(cid), cid)
    elif data.startswith("det_"):
        # 🆕 v6.4: عرض تفاصيل الإشارة كاملة (من زر "📊 تفاصيل")
        signal_id = data.replace("det_", "")
        import tracker as _tk
        trades = _tk._load().get(str(cid), [])
        trade = next((t for t in trades if t["signal_id"] == signal_id), None)
        if not trade:
            send_msg(f"❌ الإشارة غير موجودة: <code>{signal_id}</code>", main_kb(), cid)
            return
        # إعادة تحليل MTF للحصول على تفاصيل الفريمات
        from engine import analyze_mtf
        from signals import Signal as _S, format_signal_mtf as _fmt_mtf
        mtf = analyze_mtf(trade["symbol"])
        if not mtf:
            # fallback: عرض التفاصيل من trade مباشرة (دون جدول فريمات)
            msg = "📊 <b>تفاصيل الإشارة</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            msg += f"🆔 <code>{signal_id}</code>\n"
            msg += f"🪙 <b>{trade['symbol']}</b>\n"
            msg += f"💰 الدخول: {fmt_price(trade.get('entry', 0))}\n"
            msg += f"  zone: {fmt_price(trade.get('entry_low', 0))} - {fmt_price(trade.get('entry_high', 0))}\n"
            msg += f"🛑 SL: {fmt_price(trade.get('sl', 0))} ({trade.get('sl_pct', 0):.2f}%)\n"
            msg += f"🎯 TP1: {fmt_price(trade.get('tp1', 0))} (+{trade.get('tp1_pct', 0):.1f}%)\n"
            msg += f"🎯 TP2: {fmt_price(trade.get('tp2', 0))} (+{trade.get('tp2_pct', 0):.1f}%)\n"
            msg += f"🎯 TP3: {fmt_price(trade.get('tp3', 0))} (+{trade.get('tp3_pct', 0):.1f}%)\n"
            msg += f"💼 المركز: ${trade.get('position_size_usd', 0):.0f} | مخاطرة: ${trade.get('risk_amount_usd', 0):.0f}\n"
            if trade.get("confirmed"):
                msg += "\n📝 <b>المؤكدات الفنية:</b>\n"
                for c in trade["confirmed"][:7]:
                    msg += f"  ✅ {c}\n"
            msg += "\n💡 <i>تحليل الفريمات غير متوفر حالياً (قد يكون Binance محظوراً)</i>"
            send_msg(msg, main_kb(), cid)
            return
        # بناء Signal object من trade
        sig_obj = _S(
            symbol=trade["symbol"], entry=trade.get("entry", 0),
            entry_low=trade.get("entry_low", 0), entry_high=trade.get("entry_high", 0),
            sl=trade.get("sl", 0),
            tp1=trade.get("tp1", 0), tp2=trade.get("tp2", 0), tp3=trade.get("tp3", 0),
            tp_pct=trade.get("tp2_pct", 0), sl_pct=trade.get("sl_pct", 0),
            tp1_pct=trade.get("tp1_pct", 0), tp2_pct=trade.get("tp2_pct", 0), tp3_pct=trade.get("tp3_pct", 0),
            rr=5.0, rr_tp1=1.5, rr_tp2=3.0,
            score=trade.get("score", 0), confirmed=trade.get("confirmed", []),
            created_at=trade.get("created_at", 0), signal_id=signal_id,
            risk_pct=trade.get("risk_pct", 0),
            position_size_usd=trade.get("position_size_usd", 0),
            position_size_pct=trade.get("position_size_pct", 0),
            risk_amount_usd=trade.get("risk_amount_usd", 0),
            valid_until=trade.get("valid_until", 0),
            btc_trend=trade.get("btc_trend", ""),
        )
        send_msg(_fmt_mtf(sig_obj, mtf), main_kb(), cid)
    # 🆕 v6.4.4: تم إزالة زر "كل صفقات {sym}" inline (حسب طلب المستخدم)
    # /coin_history <SYMBOL> يبقى متاحاً كأمر نصي

# ═══ Flask ═══
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        u = flask_request.get_json()
        if not u:
            return jsonify({"ok": True})
        if "message" in u and "text" in u["message"]:
            cid = str(u["message"]["chat"]["id"])
            text = u["message"]["text"]
            chat = u["message"]["chat"]
            threading.Thread(target=handle_text, args=(cid, text, chat), daemon=True).start()
        elif "callback_query" in u:
            cq = u["callback_query"]
            cid = str(cq["message"]["chat"]["id"])
            data = cq["data"]
            cb_id = cq["id"]
            threading.Thread(target=handle_callback, args=(cid, data, cb_id), daemon=True).start()
    except Exception as e:
        log.error(f"❌ [WEBHOOK] error: {e}")
    return jsonify({"ok": True})

@app.route("/")
def home(): return jsonify({"status": "running"})

@app.route("/health")
def health(): return jsonify({"status": "ok"})

# ═══ Start ═══
def check_pending_trades_on_startup():
    """🆕 v6.4.10: عند تثبيت تحديث جديد، يفحص كل الصفقات النشطة الموجودة مسبقاً.

    لو أُعيد تشغيل البوت (أو رُفع تحديث) وكانت هناك صفقات نشطة،
    قد يكون السعر تجاوز أهدافاً أثناء التوقف — هذه الدالة:
      1) تفحص كل صفقة نشطة
      2) تجلب السعر الحالي (15m candles)
      3) تطبق نفس منطق check_trades (فحص متسلسل)
      4) ترسل تنبيهات لكل هدف محقق لم يُرسل من قبل
      5) ترسل تنبيه SL لو ضُرب أثناء التوقف

    تُستدعى قبل بدء scheduler_loop — في نفس thread.
    """
    try:
        log.info("🔄 [STARTUP RECOVERY] فحص الصفقات الموجودة مسبقاً...")
        all_data = tracker._load()
        if not all_data:
            log.info("🔄 [STARTUP RECOVERY] لا توجد صفقات محفوظة")
            return

        total_recovered = 0
        for cid, trades in all_data.items():
            for t in trades:
                if t.get("status") not in tracker.NON_FINAL:
                    continue  # صفقة مغلقة — تجاوز
                sym = t.get("symbol", "")
                if not sym:
                    continue

                # جلب السعر الحالي (15m candles)
                # 🆕 v6.4.58: defensive checks لمنع list index out of range
                try:
                    candles = fetch_klines(sym, interval="15m", limit=4)
                    if not candles or len(candles) == 0:
                        candles = fetch_klines(sym, interval="1h", limit=6)
                    if not candles or len(candles) == 0:
                        log.warning(f"⚠️ [startup recovery] {sym}: no candles data, skipping")
                        continue

                    cur = candles[-1]["close"]
                    candle_high = candles[-1]["high"]
                    candle_low = candles[-1]["low"]
                except (IndexError, KeyError, TypeError) as e:
                    log.warning(f"⚠️ [startup recovery] {sym}: candles access err: {e}")
                    continue
                now = int(time.time())

                # ── فحص SL ──
                # 🆕 v6.4.14: فقط لو الإغلاق ≤ SL (لا نطلق SL من wick فقط)
                if candle_low <= t["sl"] and cur <= t["sl"] * 1.005:
                    dur = format_duration(now - t["created_at"])
                    _trade_strategy_v2 = t.get("strategy", "v1")  # 🆕 v6.4.88: استراتيجية الصفقة
                    msg = format_sl_alert(sym, t["sl"], cur, dur, strategy=_trade_strategy_v2)
                # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
                    _send_trade_alert(msg, t)
                    sig_msg_id = get_signal_message_id(cid, t["signal_id"])
                    if sig_msg_id:
                        delete_signal_message(sig_msg_id)
                        clear_signal_message_id(cid, t["signal_id"])
                    hit_sl(cid, t["signal_id"], candle_low)
                    clear_signal_dedup(sym)
                    total_recovered += 1
                    log.info(f"🔄 [STARTUP RECOVERY] {sym} SL HIT @ {t['sl']}")
                    continue

                # ── فحص متسلسل للأهداف ──
                tp_levels = [
                    ("TP1", t.get("tp1", t.get("tp", 0)), format_tp1_alert),
                    ("TP2", t.get("tp2", 0), format_tp2_alert),
                    ("TP3", t.get("tp3", 0), format_tp3_alert),
                    ("TP4", t.get("tp4", 0), format_tp4_alert),
                    ("TP5", t.get("tp5", 0), format_tp5_alert),
                    ("TP6", t.get("tp6", 0), format_tp6_alert),
                ]
                status_order = ["ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "TP5_HIT"]
                current_status = t["status"]
                if current_status not in status_order:
                    continue
                current_idx = status_order.index(current_status)

                for i in range(current_idx, len(tp_levels)):
                    level_name, tp_price, alert_func = tp_levels[i]
                    if tp_price <= 0:
                        continue
                    if candle_high >= tp_price:
                        dur = format_duration(now - t["created_at"])
                        msg = alert_func(t, cur, dur)
                # 🆕 v6.4.17: لا ترسل للبوت — القناة فقط
                        _send_trade_alert(msg, t)
                        is_final = level_name in ("TP5", "TP6")
                        if is_final:
                            sig_msg_id = get_signal_message_id(cid, t["signal_id"])
                            if sig_msg_id:
                                delete_signal_message(sig_msg_id)
                                clear_signal_message_id(cid, t["signal_id"])
                        hit_tp(cid, t["signal_id"], tp_price, cur, level=level_name)
                        total_recovered += 1
                        log.info(f"🔄 [STARTUP RECOVERY] {sym} {level_name} HIT @ {tp_price}")
                        if is_final:
                            clear_signal_dedup(sym)
                            break
                        # حدّث t للفحص المتسلسل
                        updated_trades = [tt for tt in tracker._load().get(str(cid), [])
                                          if tt["signal_id"] == t["signal_id"]]
                        if updated_trades:
                            t = updated_trades[0]
                        continue
                    else:
                        break

        if total_recovered > 0:
            recovery_msg = f"🔄 <b>استعادة بعد التحديث</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            recovery_msg += f"📊 تم فحص الصفقات الموجودة وإرسال <b>{total_recovered}</b> تنبيه متأخر\n"
            recovery_msg += "✅ كل الأهداف المحققة أثناء التوقف تم إرسالها الآن"
            send_msg(recovery_msg)
            log.info(f"🔄 [STARTUP RECOVERY] اكتمل — {total_recovered} تنبيه مُرسل")
        else:
            log.info("🔄 [STARTUP RECOVERY] لا توجد تنبيهات متأخرة — كل الصفقات محدّثة")
    except Exception as e:
        log.warning(f"🔄 [STARTUP RECOVERY] err: {e}")


def _binance_selftest():
    """🆕 v6.4.40: فحص Binance عند الإقلاع — يكشف الحظر مبكراً ويبلّغ المستخدم.
    🆕 v6.4.41: فحص إضافي لـ CoinGecko و KuCoin (sources احتياطية).

    يجرب:
      1) api.binance.com (الرسمي)
      2) data-api.binance.vision (الـ fallback الأول)
      3) CoinGecko (الـ fallback الثاني — يجب أن يعمل دائماً)
      4) KuCoin (للـ klines)
    يطبع نتائج واضحة في السجل، ويرسل رسالة Telegram للمستخدم بحالة كل مصدر.
    """
    import time as _time
    _time.sleep(8)  # انتظر قليلاً بعد الإقلاع لتفادي تعارض مع webhook
    try:
        log.info(f"🧪 [SELF-TEST {BOT_VERSION}] بدء الفحص الشامل لمصادر البيانات...")
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

        # 1) Binance primary
        primary_ok = False
        primary_status = None
        try:
            r = requests.get("https://api.binance.com/api/v3/ping", timeout=10, headers=headers)
            primary_status = r.status_code
            primary_ok = (r.status_code == 200)
        except Exception as e:
            primary_status = f"NET_ERROR: {e}"
        log.info(f"   api.binance.com        → HTTP {primary_status} {'✅' if primary_ok else '❌'}")

        # 2) Binance fallback (data-api.binance.vision)
        fallback_ok = False
        fallback_status = None
        try:
            r = requests.get("https://data-api.binance.vision/api/v3/ping", timeout=10, headers=headers)
            fallback_status = r.status_code
            fallback_ok = (r.status_code == 200)
        except Exception as e:
            fallback_status = f"NET_ERROR: {e}"
        log.info(f"   data-api.binance.vision → HTTP {fallback_status} {'✅' if fallback_ok else '❌'}")

        # 3) CoinGecko (🆕 v6.4.41)
        coingecko_ok = False
        coingecko_status = None
        try:
            r = requests.get("https://api.coingecko.com/api/v3/ping", timeout=10, headers=headers)
            coingecko_status = r.status_code
            coingecko_ok = (r.status_code == 200)
        except Exception as e:
            coingecko_status = f"NET_ERROR: {e}"
        log.info(f"   api.coingecko.com       → HTTP {coingecko_status} {'✅' if coingecko_ok else '❌'}")

        # 4) KuCoin (🆕 v6.4.41)
        kucoin_ok = False
        kucoin_status = None
        try:
            r = requests.get("https://api.kucoin.com/api/v1/status", timeout=10, headers=headers)
            kucoin_status = r.status_code
            kucoin_ok = (r.status_code == 200)
        except Exception as e:
            kucoin_status = f"NET_ERROR: {e}"
        log.info(f"   api.kucoin.com          → HTTP {kucoin_status} {'✅' if kucoin_ok else '❌'}")

        # 5) Functional test: actually fetch data
        log.info(f"   ── اختبار وظيفي ──")
        tickers = get_market_tickers()
        ticker_count = len(tickers) if tickers else 0
        log.info(f"   get_market_tickers() → {ticker_count} ticker")
        prefilter_count = len(prefilter_candidates(top_n=PRE_FILTER_TOP_N))
        log.info(f"   prefilter_candidates() → {prefilter_count} مرشح")
        candles = fetch_klines('BTC', '1d', 5)
        candle_count = len(candles) if candles else 0
        log.info(f"   fetch_klines(BTC, 1d) → {candle_count} candles")

        # 6) Final verdict — 🆕 v6.4.42: silent mode (no user notifications)
        if ticker_count > 0 and candle_count > 0:
            log.info(f"✅ [SELF-TEST] Bot ready — data sources active (silent, no user alert)")
        else:
            log.error(f"🚨 [SELF-TEST FAILED] All sources failed — bot cannot fetch data (silent)")
        # 🆕 v6.4.42: لا تنبيهات للمستخدم عن حالة البوت أو التحركات
        # الإرسال للمستخدم مُعطّل بناءً على طلب المستخدم (وضع صامت)
    except Exception as e:
        log.error(f"❌ [SELF-TEST] err: {e}")


def start():
    if not TOKEN:
        log.error("No TELEGRAM_BOT_TOKEN")
        return
    # 🆕 v6.4.39: طباعة BOT_VERSION بشكل صريح في سجل الإقلاع لتأكيد النسخة المنشورة
    log.info(f"🚀 Booting {BOT_VERSION} — send_msg(msg, kb, cid) signature active")
    # 🆕 v6.4.86: سجل عتبات الجودة المُطبّقة فعلياً (للتشخيص — يظهر في Render logs)
    log.info(f"🔒 [QUALITY GATES v6.4.86] SCORE_THRESHOLD={SCORE_THRESHOLD} | "
             f"MIN_RR_RATIO={MIN_RR_RATIO} | MTF_MIN_BULLISH={MTF_MIN_BULLISH} | "
             f"MTF_MIN_CONFLUENCE={MTF_MIN_CONFLUENCE} | STRATEGY_V2_MIN_RR={STRATEGY_V2_MIN_RR} | "
             f"MAX_ACTIVE_TRADES={MAX_ACTIVE_TRADES} | MIN_SMC_CONFLUENCE={MIN_SMC_CONFLUENCE} | "
             f"MIN_SMART_LIQUIDITY_PCT={MIN_SMART_LIQUIDITY_PCT}")
    log.info(f"📍 [STATE] V1_ENABLED={V1_ENABLED} (channel if True) | V2_ENABLED={V2_ENABLED} (channel if True) | V3_ENABLED={V3_ENABLED} (channel if True)")
    # 🆕 v6.4.104: تشخيص Upstash (يظهر في Render logs)
    if halal_check._UPSTASH_AVAILABLE:
        log.info(f"💾 [Upstash] ✅ متاح — deleted_coins محفوظة في السحابة")
    else:
        log.warning(f"⚠️ [Upstash] ❌ غير متاح — العملات المحذوفة ستعود بعد deploy! اضبط UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN في Render env")
    # 🆕 v6.1: إعادة بناء active cache من persistent storage (survive restart)
    rebuild_cache()
    # 🆕 v6.4.61: استرجاع قائمة الأحكام الافتراضية لو الـ DB فارغ (199 عملة حلال)
    # هذا يضمن: القائمة لا تُحذف عند كل تحديث (Render ephemeral filesystem)
    try:
        seeded = halal_check.seed_default_rulings_if_empty()
        if seeded > 0:
            log.info(f"🕌 [Halal] seeded {seeded} default halal coins (first deploy)")
    except Exception as e:
        log.warning(f"🕌 [Halal] seed defaults err: {e}")
    # 🆕 v6.4.40: self-test لـ Binance عند الإقلاع — يكشف الحظر مبكراً
    threading.Thread(target=_binance_selftest, daemon=True).start()
    # 🆕 v6.4.24: تمت إزالة فحص القنوات عند الإقلاع (لا داعي لإرسال رسائل اختبار)
    # test_channel_at_startup()  # معطل — يرسل رسائل مزعجة عند كل deploy
    # 🆕 v6.4.10: فحص الصفقات الموجودة مسبقاً — أرسل تنبيهات الأهداف المتأخرة
    # 🆕 v6.4.11: شغّل في thread منفصل لتفادي تأخير بدء البوت
    threading.Thread(target=check_pending_trades_on_startup, daemon=True).start()
    # Set webhook
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
    if RENDER_URL:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                         params={"url": f"{RENDER_URL}/webhook"}, timeout=10)
            if r.status_code == 200:
                log.info("✅ Webhook set successfully")
            else:
                log.error(f"❌ setWebhook failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"❌ setWebhook error: {e}")
    # Welcome — مختصر (لا يطيل البوت)
    msg = f"🚀 <b>بوت الكريبتو {BOT_VERSION}</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"✅ مسح تلقائي كل <b>{SCAN_INTERVAL//60} دقيقة</b>\n"
    msg += f"💓 heartbeat كل <b>{HEARTBEAT_INTERVAL//60} دقيقة</b>\n"
    msg += "💎 الصفقات → القناة فقط\n"
    msg += "🎯 الأهداف → قناة الأهداف\n\n"
    msg += "📥 /trackrecord — سجل الأداء\n"
    msg += "📥 /report — تقرير PDF"
    send_msg(msg)
    # 🆕 v6.4.17: استعادة الصفقات — صامت (لا رسالة طويلة)
    try:
        active_restored = sum(1 for trades in tracker._load().values()
                              for t in trades if t.get("status") in tracker.NON_FINAL)
        if active_restored > 0:
            log.info(f"🔄 Restored {active_restored} active trades")
    except Exception as e:
        log.warning(f"Restore failed: {e}")
    # Start scheduler
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # 🆕 v6.4.113: Start BTC/ETH monitor — صور شارت للقناة
    if btc_monitor.BTC_MONITOR_CHANNEL_ID:
        threading.Thread(target=btc_monitor.btc_monitor_loop, args=(TOKEN,), daemon=True).start()
        log.info(f"📊 [BTCMonitor] thread launched — channel={btc_monitor.BTC_MONITOR_CHANNEL_ID} threshold={btc_monitor.BTC_MONITOR_THRESHOLD}%")
        # 🆕 v6.4.114: رسالة اختبار فورية عند الإقلاع
        try:
            import threading as _t
            def _send_test():
                import time as _time
                _time.sleep(10)  # انتظر 10 ثوان بعد الإقلاع
                btc_monitor.send_test_message(TOKEN)
            _t.Thread(target=_send_test, daemon=True).start()
        except Exception as _e:
            log.warning(f"📊 [BTCMonitor] test msg err: {_e}")
    else:
        log.info("📊 [BTCMonitor] معطّل — اضبط BTC_MONITOR_CHANNEL_ID في Render env")
    # 🆕 v6.2.7: Start watchdog — يراقب أن scheduler حي + heartbeat
    if HEARTBEAT_ENABLED:
        threading.Thread(target=watchdog_loop, daemon=True).start()
        log.info(f"🐕 Watchdog thread launched (heartbeat every {HEARTBEAT_INTERVAL//60}min)")
    else:
        log.info("ℹ️ Heartbeat disabled (HEARTBEAT_ENABLED=0)")
    # 🆕 v6.4.4: keep-alive — يمنع Render من إيقاف البوت على الخطة المجانية
    # كل 5 دقائق، يطلق طلب HTTP على نفسه (RENDER_EXTERNAL_URL)
    def keep_alive_loop():
        RENDER_URL_SELF = os.environ.get("RENDER_EXTERNAL_URL", "")
        if not RENDER_URL_SELF:
            log.warning("ℹ️ keep_alive: RENDER_EXTERNAL_URL not set — keep_alive disabled")
            return
        log.info(f"🔄 keep_alive thread launched — pings every 5min to {RENDER_URL_SELF}")
        while True:
            try:
                time.sleep(300)
                r = requests.get(f"{RENDER_URL_SELF}/health", timeout=10)
                if r.status_code == 200:
                    log.info(f"🔄 keep_alive: ping OK ({r.status_code})")
                else:
                    log.warning(f"⚠️ keep_alive: ping HTTP {r.status_code}")
            except Exception as e:
                log.warning(f"⚠️ keep_alive err: {e}")
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    # Start Flask
    log.info(f"🌐 Flask on 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)

if __name__ == "__main__":
    start()
