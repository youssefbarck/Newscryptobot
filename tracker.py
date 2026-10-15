"""
Tracker — متابعة الصفقات + Persistent SQLite Database
=====================================================
🆕 v6.4.18: تخزين دائم باستخدام SQLite (بدل JSON المؤقت).
  - SQLite مدمج في Python (لا يحتاج تثبيت)
  - البقاء بعد Restart/Deploy على Render
  - لا يفقد البيانات
  - يدعم الاستعلامات السريعة

كما يدعم:
  - One Active Trade Per Symbol
  - MFE/MAE tracking
  - إحصائيات تراكمية تلقائية
"""

import logging, json, os, time, threading, sqlite3
from typing import Dict, List, Optional
from datetime import datetime

log = logging.getLogger("Tracker")

# ═══ 🆕 v6.4.18/v6.4.57: SQLite Database — دائم بعد Restart/Deploy ═══
# 🆕 v6.4.57: أولوية المسار:
#   1) env var PERSISTENT_DIR (يضبطه المستخدم على Render → يربطه بـ Persistent Disk)
#   2) /opt/render/project/src/data (Render default persistent path)
#   3) /tmp (fallback — سيُمحى عند deploy لكن يعمل بين restarts)
# ⚠️ على Render، يجب إنشاء Persistent Disk وربطه بمسار مثل /var/data
#    ثم ضبط: PERSISTENT_DIR=/var/data في Environment Variables
_PERSISTENT_DIR = os.environ.get("PERSISTENT_DIR", "")
if not _PERSISTENT_DIR:
    # 🆕 v6.4.57: جرّب مسارات دائمة على Render تلقائياً
    for _candidate in ["/var/data", "/opt/render/project/src/data", "/app/data"]:
        try:
            if os.path.exists(_candidate) and os.access(_candidate, os.W_OK):
                _PERSISTENT_DIR = _candidate
                break
        except Exception:
            continue
if not _PERSISTENT_DIR:
    _PERSISTENT_DIR = "/tmp"
    try:
        if not os.path.exists(_PERSISTENT_DIR):
            os.makedirs(_PERSISTENT_DIR, exist_ok=True)
    except Exception:
        _PERSISTENT_DIR = "/tmp"

_DB_DIR = _PERSISTENT_DIR
try:
    if not os.path.exists(_DB_DIR):
        os.makedirs(_DB_DIR, exist_ok=True)
except Exception:
    _DB_DIR = "/tmp"
DB_PATH = os.path.join(_DB_DIR, "crypto_bot.db")
log.info(f"💾 [Tracker] DB path: {DB_PATH}")

_lock = threading.Lock()
_lock_lock = threading.Lock()
MAX_TRADES = 200

# Status sets
NON_FINAL = {"ACTIVE", "TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT"}
# 🆕 v6.4.82: TP{n}_DONE = صفقة أُغلقت عند الستوب الديناميكي بعد تحقيق n أهداف → نجاح وليس خسارة
FINAL = {"TP5_HIT", "TP6_HIT", "STOP_LOSS", "CANCELLED", "EXPIRED", "CLOSED",
         "TP1_DONE", "TP2_DONE", "TP3_DONE", "TP4_DONE"}

# 🆕 v6.4.82: نسب المركز المتبقي بعد كل هدف (حسب sell_pcts في hit_tp)
# بعد TP1 يُباع 50% → يتبقى 50% ... إلخ
REMAINING_PCT = {"ACTIVE": 1.0, "TP1_HIT": 0.50, "TP2_HIT": 0.25, "TP3_HIT": 0.15, "TP4_HIT": 0.05}
# 🆕 v6.4.82: عدد الأهداف المحققة حسب الحالة
TPS_ACHIEVED = {"TP1_HIT": 1, "TP2_HIT": 2, "TP3_HIT": 3, "TP4_HIT": 4}

# In-memory cache
_active_cache: set = set()


# ═══════════════════════════════════════════════════════════
# Database initialization
# ═══════════════════════════════════════════════════════════

def _get_db() -> sqlite3.Connection:
    """يفتح اتصال SQLite — ينشئ الجداول لو غير موجودة."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """🆕 v6.4.18: ينشئ جداول SQLite لو غير موجودة."""
    try:
        conn = _get_db()
        c = conn.cursor()

        # جدول الصفقات — كل صفقة في صف واحد
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                signal_id TEXT PRIMARY KEY,
                cid TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry REAL DEFAULT 0,
                sl REAL DEFAULT 0,
                tp REAL DEFAULT 0,
                tp1 REAL DEFAULT 0, tp2 REAL DEFAULT 0, tp3 REAL DEFAULT 0,
                tp4 REAL DEFAULT 0, tp5 REAL DEFAULT 0, tp6 REAL DEFAULT 0,
                tp1_pct REAL DEFAULT 0, tp2_pct REAL DEFAULT 0, tp3_pct REAL DEFAULT 0,
                tp4_pct REAL DEFAULT 0, tp5_pct REAL DEFAULT 0, tp6_pct REAL DEFAULT 0,
                entry_low REAL DEFAULT 0, entry_high REAL DEFAULT 0,
                score REAL DEFAULT 0,
                confirmed TEXT DEFAULT '',
                risk_pct REAL DEFAULT 0,
                position_size_usd REAL DEFAULT 0,
                position_size_pct REAL DEFAULT 0,
                risk_amount_usd REAL DEFAULT 0,
                valid_until INTEGER DEFAULT 0,
                btc_trend TEXT DEFAULT '',
                update_stars INTEGER DEFAULT 0,
                signal_message_id INTEGER,
                last_early_exit_alert_ts INTEGER DEFAULT 0,
                last_reminder_ts INTEGER DEFAULT 0,
                last_dca_alert_ts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ACTIVE',
                pnl REAL DEFAULT 0,
                mfe REAL DEFAULT 0,
                mae REAL DEFAULT 0,
                created_at INTEGER DEFAULT 0,
                closed_at INTEGER,
                closing_price REAL DEFAULT 0,
                tp1_price REAL, tp2_price REAL, tp3_price REAL,
                tp4_price REAL, tp5_price REAL, tp6_price REAL,
                strategy TEXT DEFAULT 'v1'  -- 🆕 v6.4.68: v1 | v2 (فصل الاستراتيجيتين)
            )
        """)

        # 🆕 v6.4.19: أضف عمود tp لو الجدول قديم (migration safe)
        try:
            c.execute("ALTER TABLE trades ADD COLUMN tp REAL DEFAULT 0")
        except Exception as e:
            pass  # العمود موجود بالفعل

        # 🆕 v6.4.20: أضف عمود last_reminder_ts
        try:
            c.execute("ALTER TABLE trades ADD COLUMN last_reminder_ts INTEGER DEFAULT 0")
        except Exception as e:
            log.warning(f"err: {e}")

        # 🆕 v6.4.30: أضف عمود last_dca_alert_ts (cooldown لتنبيهات DCA)
        try:
            c.execute("ALTER TABLE trades ADD COLUMN last_dca_alert_ts INTEGER DEFAULT 0")
        except Exception as e:
            log.warning(f"err: {e}")

        # 🆕 v6.4.68: أضف عمود strategy (v1 | v2) — فصل الاستراتيجيتين
        try:
            c.execute("ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT 'v1'")
        except Exception as e:
            pass  # العمود موجود بالفعل

        # 🆕 v6.4.83: أضف عمود last_peak_alert_ts — لتنبيه القمة مرة واحدة
        try:
            c.execute("ALTER TABLE trades ADD COLUMN last_peak_alert_ts INTEGER DEFAULT 0")
        except Exception as e:
            pass  # العمود موجود بالفعل

        # جدول الإحصائيات التراكمية — عدّ كل هدف
        c.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        """)

        # مفاتيح الإحصائيات
        stat_keys = [
            "tp1_count", "tp2_count", "tp3_count", "tp4_count", "tp5_count", "tp6_count",
            "sl_count", "expired_count", "cancelled_count",
            "total_trades", "total_wins", "total_losses",
            # 🆕 v6.4.82: إغلاقات الستوب الديناميكي الرابحة (بعد أهداف)
            "sl_after_tp1_count", "sl_after_tp2_count", "sl_after_tp3_count", "sl_after_tp4_count",
            "total_pnl_x100"  # PnL مضروب في 100 (لتفادي أرقام عشرية)
        ]
        for key in stat_keys:
            c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)", (key,))

        conn.commit()
        conn.close()
        log.info(f"💾 [SQLite] Database initialized at {DB_PATH}")
    except Exception as e:
        log.error(f"💾 [SQLite] Init failed: {e}")


def _row_to_dict(row) -> Dict:
    """يحوّل صف SQLite إلى dict (للتوافق مع الكود القديم)."""
    d = dict(row)
    # confirmed: JSON string → list
    if d.get("confirmed"):
        try:
            d["confirmed"] = json.loads(d["confirmed"])
        except Exception as e:
            d["confirmed"] = []
    return d


def _dict_to_row(d: Dict) -> Dict:
    """يحوّل dict إلى صيغة SQLite (confirmed → JSON string)."""
    row = dict(d)
    if isinstance(row.get("confirmed"), list):
        row["confirmed"] = json.dumps(row["confirmed"], ensure_ascii=False)
    return row


# ═══════════════════════════════════════════════════════════
# Load / Save — compatibility with old JSON interface
# ═══════════════════════════════════════════════════════════

def _load() -> Dict:
    """🆕 v6.4.18: تحميل كل الصفقات من SQLite (يرجع dict {cid: [trades]})."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM trades ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()

        result: Dict[str, List[Dict]] = {}
        for row in rows:
            d = _row_to_dict(row)
            cid = d.get("cid", "")
            if cid not in result:
                result[cid] = []
            result[cid].append(d)
        return result
    except Exception as e:
        log.error(f"💾 [SQLite] Load failed: {e}")
        return {}


def _save(data: Dict) -> bool:
    """🆕 v6.4.18: حفظ كل الصفقات في SQLite (upsert)."""
    try:
        conn = _get_db()
        c = conn.cursor()
        for cid, trades in data.items():
            for t in trades:
                row = _dict_to_row(t)
                row["cid"] = cid
                # upsert (insert or replace)
                cols = ", ".join(row.keys())
                placeholders = ", ".join(["?" for _ in row])
                c.execute(
                    f"INSERT OR REPLACE INTO trades ({cols}) VALUES ({placeholders})",
                    list(row.values())
                )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.error(f"💾 [SQLite] Save failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Cache rebuild
# ═══════════════════════════════════════════════════════════

def rebuild_cache():
    """🆕 v6.1: إعادة بناء _active_cache من SQLite عند startup."""
    _active_cache.clear()
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT symbol FROM trades WHERE status IN ({})".format(
            ", ".join(["?" for _ in NON_FINAL])
        ), list(NON_FINAL))
        rows = c.fetchall()
        conn.close()
        for row in rows:
            sym = row["symbol"]
            if sym:
                _active_cache.add(sym)
                log.info(f"🔒 [STARTUP RESTORE] {sym} locked (status in NON_FINAL)")
        log.info(f"🔒 Cache rebuilt: {len(_active_cache)} active symbols: {_active_cache}")
    except Exception as e:
        log.warning(f"🔒 Cache rebuild failed: {e}")


# ═══════════════════════════════════════════════════════════
# Active trade check
# ═══════════════════════════════════════════════════════════

def has_active_trade(symbol: str, cid: str = None, strategy: str = None) -> bool:
    """🆕 v6.1: فحص مركزي — هل يوجد صفقة نشطة لهذه العملة؟
    🆕 v6.4.68: دعم فلتر strategy (لو strategy='v1' → فقط V1)
    """
    if strategy is None:
        # لو لا strategy محدد → استخدم cache (كل الصفقات)
        if symbol in _active_cache:
            return True
    try:
        conn = _get_db()
        c = conn.cursor()
        if cid and strategy:
            # 🆕 v6.4.68: فلتر بالـ strategy
            c.execute(
                "SELECT 1 FROM trades WHERE symbol=? AND cid=? AND strategy=? AND status IN ({}) LIMIT 1".format(
                    ", ".join(["?" for _ in NON_FINAL])
                ), [symbol, str(cid), strategy] + list(NON_FINAL)
            )
        elif cid:
            c.execute(
                "SELECT 1 FROM trades WHERE symbol=? AND cid=? AND status IN ({}) LIMIT 1".format(
                    ", ".join(["?" for _ in NON_FINAL])
                ), [symbol, str(cid)] + list(NON_FINAL)
            )
        elif strategy:
            c.execute(
                "SELECT 1 FROM trades WHERE symbol=? AND strategy=? AND status IN ({}) LIMIT 1".format(
                    ", ".join(["?" for _ in NON_FINAL])
                ), [symbol, strategy] + list(NON_FINAL)
            )
        else:
            c.execute(
                "SELECT 1 FROM trades WHERE symbol=? AND status IN ({}) LIMIT 1".format(
                    ", ".join(["?" for _ in NON_FINAL])
                ), [symbol] + list(NON_FINAL)
            )
        result = c.fetchone() is not None
        conn.close()
        if result and strategy is None:
            _active_cache.add(symbol)
        return result
    except Exception as e:
        log.warning(f"has_active_trade err: {e}")
        return symbol in _active_cache


# ═══════════════════════════════════════════════════════════
# Create trade
# ═══════════════════════════════════════════════════════════

def try_create(cid: str, trade: Dict, strategy: str = "v1") -> bool:
    """🆕 v6.1: Atomic CHECK + LOCK + CREATE.
    🆕 v6.4.68: دعم strategy (v1 | v2) — فصل الاستراتيجيتين.
    """
    sym = trade.get("symbol", "")
    _strategy = trade.get("strategy", strategy)  # 🆕 v6.4.68
    with _lock_lock:
        # 🆕 v6.4.68: فلتر بالـ strategy — V1 لا يمنع V2 والعكس
        if has_active_trade(sym, cid, strategy=_strategy):
            log.info(f"⛔ [DUPLICATE BLOCKED] {sym} already has active {_strategy} trade for cid={cid}")
            return False

        _active_cache.add(sym)
        log.info(f"🔒 [TRADE LOCK] {sym} locked by signal_id={trade.get('signal_id', '?')} strategy={_strategy}")

        trade["status"] = "ACTIVE"
        trade["created_at"] = int(time.time())
        trade["closed_at"] = None
        trade["mfe"] = 0.0
        trade["mae"] = 0.0
        trade["strategy"] = _strategy  # 🆕 v6.4.68

        row = _dict_to_row(trade)
        row["cid"] = str(cid)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?" for _ in row])

        try:
            conn = _get_db()
            c = conn.cursor()
            c.execute(f"INSERT OR REPLACE INTO trades ({cols}) VALUES ({placeholders})",
                      list(row.values()))
            # 🆕 v6.4.18: حدّث total_trades
            c.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_trades'")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            _active_cache.discard(sym)
            log.error(f"❌ [TRADE CREATE FAILED] {sym} — {e}")
            return False


# ═══════════════════════════════════════════════════════════
# Signal message ID helpers
# ═══════════════════════════════════════════════════════════

def set_signal_message_id(cid: str, signal_id: str, message_id: int) -> bool:
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("UPDATE trades SET signal_message_id=? WHERE signal_id=? AND cid=?",
                  (message_id, signal_id, str(cid)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning(f"set_signal_message_id err: {e}")
        return False


def get_signal_message_id(cid: str, signal_id: str) -> Optional[int]:
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT signal_message_id FROM trades WHERE signal_id=? AND cid=?",
                  (signal_id, str(cid)))
        row = c.fetchone()
        conn.close()
        return row["signal_message_id"] if row else None
    except Exception as e:
        log.warning(f"get_signal_message_id err: {e}")
        return None


def clear_signal_message_id(cid: str, signal_id: str) -> bool:
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("UPDATE trades SET signal_message_id=NULL WHERE signal_id=? AND cid=?",
                  (signal_id, str(cid)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning(f"clear_signal_message_id err: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Compat functions
# ═══════════════════════════════════════════════════════════

def is_active(symbol: str) -> bool:
    return symbol in _active_cache

def lock(symbol: str):
    _active_cache.add(symbol)
    log.info(f"🔒 {symbol} locked")

def unlock(symbol: str):
    _active_cache.discard(symbol)
    log.info(f"🔓 {symbol} unlocked")

def create(cid: str, trade: Dict) -> bool:
    return try_create(cid, trade)


# ═══════════════════════════════════════════════════════════
# MFE/MAE
# ═══════════════════════════════════════════════════════════

def update_mfe_mae(cid: str, signal_id: str, current_price: float):
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT entry, mfe, mae FROM trades WHERE signal_id=? AND cid=? AND status IN ({})".format(
            ", ".join(["?" for _ in NON_FINAL])
        ), [signal_id, str(cid)] + list(NON_FINAL))
        row = c.fetchone()
        if not row:
            conn.close()
            return
        entry = row["entry"]
        mfe = row["mfe"]
        mae = row["mae"]
        unrealized = (current_price - entry) / entry * 100 if entry > 0 else 0
        if unrealized > mfe:
            mfe = round(unrealized, 2)
        if unrealized < mae:
            mae = round(unrealized, 2)
        c.execute("UPDATE trades SET mfe=?, mae=? WHERE signal_id=? AND cid=?",
                  (mfe, mae, signal_id, str(cid)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"update_mfe_mae err: {e}")


def set_peak_alert_sent(cid: str, signal_id: str, ts: int = None):
    """🆕 v6.4.83: علّم أنه تم إرسال تنبيه القمة لهذه الصفقة (لمنع التكرار)."""
    try:
        if ts is None:
            ts = int(time.time())
        conn = _get_db()
        c = conn.cursor()
        c.execute("UPDATE trades SET last_peak_alert_ts=? WHERE signal_id=? AND cid=?",
                  (ts, signal_id, str(cid)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"set_peak_alert_sent err: {e}")


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.18: TP/SL with cumulative stats
# ═══════════════════════════════════════════════════════════

def _update_stats(key: str, delta: int = 1, conn=None):
    """🆕 v6.4.18: تحديث إحصائية تراكمية — يستخدم نفس الاتصال لو متاح."""
    try:
        own_conn = conn is None
        if own_conn:
            conn = _get_db()
        c = conn.cursor()
        c.execute("UPDATE stats SET value = value + ? WHERE key = ?", (int(delta), key))
        if own_conn:
            conn.commit()
            conn.close()
    except Exception as e:
        log.warning(f"_update_stats err: {e}")


def _update_pnl_stat(pnl_pct: float, conn=None):
    """🆕 v6.4.18: تحديث إجمالي PnL."""
    try:
        own_conn = conn is None
        if own_conn:
            conn = _get_db()
        c = conn.cursor()
        c.execute("UPDATE stats SET value = value + ? WHERE key = 'total_pnl_x100'",
                  (int(pnl_pct * 100),))
        if own_conn:
            conn.commit()
            conn.close()
    except Exception as e:
        log.warning(f"_update_pnl_stat err: {e}")


def hit_tp(cid: str, signal_id: str, tp_price: float, cur: float, level: str = "TP1") -> bool:
    """🆕 v6.4.5/v6.4.18: تحقق هدف — يدعم TP1-TP6 + إحصائيات تراكمية.
    🆕 v6.4.73: Trailing Stop تلقائي — عند تحقق كل هدف، يُرفع الـ SL:
      - TP1 hit → SL = نقطة الدخول (حماية رأس المال)
      - TP2 hit → SL = TP1 (قفل ربح TP1)
      - TP3 hit → SL = TP2 (قفل ربح TP2)
      - TP4 hit → SL = TP3 (قفل ربح TP3)
      - وهكذا... لو ضُرب الـ SL → المستخدم رابح دائماً
    """
    sell_pcts = {"TP1": 0.50, "TP2": 0.25, "TP3": 0.10, "TP4": 0.10, "TP5": 0.05, "TP6": 0.05}
    next_statuses = {"TP1": "TP1_HIT", "TP2": "TP2_HIT", "TP3": "TP3_HIT",
                     "TP4": "TP4_HIT", "TP5": "TP5_HIT", "TP6": "TP6_HIT"}
    expected_prevs = {"TP1": "ACTIVE", "TP2": "TP1_HIT", "TP3": "TP2_HIT",
                      "TP4": "TP3_HIT", "TP5": "TP4_HIT", "TP6": "TP5_HIT"}
    sell_pct = sell_pcts.get(level, 0.10)
    next_status = next_statuses.get(level, "TP1_HIT")
    expected_prev = expected_prevs.get(level, "ACTIVE")

    # 🆕 v6.4.73: Trailing SL — كل هدف يرفع الـ SL للمستوى السابق
    trailing_sl_map = {
        "TP1": "entry",      # SL → نقطة الدخول (حماية رأس المال)
        "TP2": "tp1",        # SL → TP1 (قفل ربح TP1)
        "TP3": "tp2",        # SL → TP2 (قفل ربح TP2)
        "TP4": "tp3",        # SL → TP3 (قفل ربح TP3)
        "TP5": "tp4",        # SL → TP4 (قفل ربح TP4)
    }

    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE signal_id=? AND cid=? AND status=?",
                  (signal_id, str(cid), expected_prev))
        row = c.fetchone()
        if not row:
            conn.close()
            return False

        t = _row_to_dict(row)
        entry = t["entry"]
        prev_pnl = t.get("pnl", 0)
        incremental_pnl = sell_pct * ((cur - entry) / entry * 100)
        pnl = prev_pnl + incremental_pnl

        # 🆕 v6.4.73: احسب الـ trailing SL الجديد
        new_sl = None
        sl_source = trailing_sl_map.get(level)
        if sl_source and sl_source in t:
            new_sl = t[sl_source]
            if new_sl and new_sl > 0:
                log.info(f"🔒 [TRAILING SL] {t['symbol']} {level} → SL moved to {sl_source}={new_sl}")

        # 🆕 v6.4.73: حدّث SL في DB + status + pnl
        if new_sl and new_sl > 0:
            c.execute(f"UPDATE trades SET status=?, pnl=?, closing_price=?, {level.lower()}_price=?, sl=? WHERE signal_id=? AND cid=?",
                       (next_status, round(pnl, 2), cur, cur, new_sl, signal_id, str(cid)))
        else:
            c.execute(f"UPDATE trades SET status=?, pnl=?, closing_price=?, {level.lower()}_price=? WHERE signal_id=? AND cid=?",
                       (next_status, round(pnl, 2), cur, cur, signal_id, str(cid)))

        # 🆕 v6.4.18: سجّل إحصائية تراكمية لكل هدف (نفس الاتصال)
        stat_key = f"{level.lower()}_count"
        _update_stats(stat_key, conn=conn)

        conn.commit()
        conn.close()

        if level in ("TP5", "TP6"):
            _active_cache.discard(t["symbol"])
            _update_stats("total_wins")
            _update_pnl_stat(pnl)
            log.info(f"🏆 {t['symbol']} {level} hit — final close (pnl=+{pnl:.2f}%)")
        else:
            log.info(f"🎯 {t['symbol']} {level} hit (pnl=+{pnl:.2f}%, sell {sell_pct*100:.0f}%)")
        return True
    except Exception as e:
        log.error(f"hit_tp err: {e}")
        return False


def hit_sl(cid: str, signal_id: str, cur: float) -> bool:
    """ضرب الستوب — خروج كامل + إحصائيات.

    🆕 v6.4.82: الستوب الديناميكي — لو الصفقة حققت ≥1 هدف قبل ضرب الستوب،
    فالنتيجة **نجاح** (أُغلقت بربح بعد n أهداف) وليست خسارة:
      - TP1_HIT → SL=entry → ضربه = خروج بدون خسارة + ربح TP1 المحقق → TP1_DONE (win)
      - TP2_HIT → SL=TP1  → ضربه = قفل ربح TP1 أيضاً → TP2_DONE (win)
      - وهكذا... الـ pnl = الربح المتراكم من الأهداف المباعة + المتبقي عند سعر الستوب
    فقط الصفقات التي لم تحقق أي هدف تُسجّل STOP_LOSS (خسارة فعلية).
    """
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE signal_id=? AND cid=? AND status IN ({})".format(
            ", ".join(["?" for _ in NON_FINAL])
        ), [signal_id, str(cid)] + list(NON_FINAL))
        row = c.fetchone()
        if not row:
            conn.close()
            return False

        t = _row_to_dict(row)
        entry = t["entry"]
        status = t.get("status", "ACTIVE")

        # 🆕 v6.4.82: هل الصفقة حققت أهدافاً قبل ضرب الستوب الديناميكي؟
        n_tps = TPS_ACHIEVED.get(status, 0)
        if n_tps > 0:
            remaining = REMAINING_PCT.get(status, 0.0)
            # pnl = أرباح الأجزاء المباعة عند الأهداف (مخزّنة) + الجزء المتبقي عند سعر الستوب
            pnl = t.get("pnl", 0) + remaining * ((cur - entry) / entry * 100) if entry > 0 else t.get("pnl", 0)
            new_status = f"TP{n_tps}_DONE"
            c.execute("UPDATE trades SET status=?, closed_at=?, pnl=?, closing_price=? WHERE signal_id=? AND cid=?",
                      (new_status, int(time.time()), round(pnl, 2), cur, signal_id, str(cid)))
            conn.commit()
            conn.close()

            _active_cache.discard(t["symbol"])
            # 🆕 v6.4.82: ناجحة — تُحسب win وليس loss
            _update_stats("total_wins")
            _update_stats(f"sl_after_tp{n_tps}_count")
            _update_pnl_stat(pnl)
            log.info(f"🏆 [TRAILING CLOSE] {t['symbol']} — dynamic SL hit after {n_tps} TP(s) → {new_status} SUCCESS (pnl={pnl:+.2f}%)")
            return True

        # خسارة فعلية — لم يتحقق أي هدف قبل ضرب الستوب
        pnl = (cur - entry) / entry * 100 if entry > 0 else 0

        c.execute("UPDATE trades SET status='STOP_LOSS', closed_at=?, pnl=?, closing_price=? WHERE signal_id=? AND cid=?",
                  (int(time.time()), round(pnl, 2), cur, signal_id, str(cid)))
        conn.commit()
        conn.close()

        _active_cache.discard(t["symbol"])
        _update_stats("sl_count")
        _update_stats("total_losses")
        _update_pnl_stat(pnl)
        log.info(f"🔓 [TRADE UNLOCK] {t['symbol']} STOP_LOSS (pnl={pnl:.2f}%)")
        return True
    except Exception as e:
        log.error(f"hit_sl err: {e}")
        return False


def close_trade(cid: str, signal_id: str, status: str, cur: float) -> bool:
    """إغلاق نهائي لأي سبب (EXPIRED/CANCELLED)."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE signal_id=? AND cid=? AND status IN ({})".format(
            ", ".join(["?" for _ in NON_FINAL])
        ), [signal_id, str(cid)] + list(NON_FINAL))
        row = c.fetchone()
        if not row:
            conn.close()
            return False

        t = _row_to_dict(row)
        entry = t["entry"]
        tp1_price = t.get("tp1_price")
        if tp1_price:
            pnl = 0.50 * ((tp1_price - entry) / entry * 100) + \
                  0.50 * ((cur - entry) / entry * 100)
        else:
            pnl = (cur - entry) / entry * 100

        c.execute("UPDATE trades SET status=?, closed_at=?, pnl=?, closing_price=? WHERE signal_id=? AND cid=?",
                  (status, int(time.time()), round(pnl, 2), cur, signal_id, str(cid)))
        conn.commit()
        conn.close()

        _active_cache.discard(t["symbol"])
        if status == "EXPIRED":
            _update_stats("expired_count")
        elif status == "CANCELLED":
            _update_stats("cancelled_count")
        log.info(f"🔓 [TRADE UNLOCK] {t['symbol']} {status} (pnl={pnl:.2f}%)")
        return True
    except Exception as e:
        log.error(f"close_trade err: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Queries
# ═══════════════════════════════════════════════════════════

def get_active(cid: str, strategy: str = None) -> List[Dict]:
    """يجلب الصفقات النشطة.
    🆕 v6.4.68: فلتر strategy (v1 | v2) — لو محدد، يرجع فقط صفقات تلك الاستراتيجية.
    """
    try:
        conn = _get_db()
        c = conn.cursor()
        if strategy:
            # 🆕 v6.4.68: فلتر بالـ strategy
            c.execute("SELECT * FROM trades WHERE cid=? AND strategy=? AND status IN ({}) ORDER BY created_at DESC".format(
                ", ".join(["?" for _ in NON_FINAL])
            ), [str(cid), strategy] + list(NON_FINAL))
        else:
            c.execute("SELECT * FROM trades WHERE cid=? AND status IN ({}) ORDER BY created_at DESC".format(
                ", ".join(["?" for _ in NON_FINAL])
            ), [str(cid)] + list(NON_FINAL))
        rows = c.fetchall()
        conn.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.warning(f"get_active err: {e}")
        return []


def get_stats(cid: str) -> Dict:
    """🆕 v6.4.18: إحصائيات شاملة — من SQLite + جدول stats."""
    try:
        conn = _get_db()
        c = conn.cursor()

        # إحصائيات تراكمية من جدول stats
        c.execute("SELECT key, value FROM stats")
        stats_rows = c.fetchall()
        cumulative = {row["key"]: row["value"] for row in stats_rows}

        # إحصائيات من الصفقات المغلقة
        c.execute("SELECT * FROM trades WHERE cid=?", (str(cid),))
        all_trades = [_row_to_dict(r) for r in c.fetchall()]

        total = len(all_trades)
        active_count = sum(1 for t in all_trades if t.get("status") in NON_FINAL)
        closed = [t for t in all_trades if t.get("status") not in NON_FINAL]

        wins = sum(1 for t in closed if t.get("status", "").startswith("TP"))
        losses = sum(1 for t in closed if t.get("status") == "STOP_LOSS")
        wr = (wins / max(wins + losses, 1)) * 100
        avg_pnl = sum(t.get("pnl", 0) for t in closed if t.get("pnl")) / max(len(closed), 1)

        mfe_trades = [t for t in all_trades if t.get("mfe", 0) != 0]
        mae_trades = [t for t in all_trades if t.get("mae", 0) != 0]
        avg_mfe = sum(t["mfe"] for t in mfe_trades) / max(len(mfe_trades), 1)
        avg_mae = sum(t["mae"] for t in mae_trades) / max(len(mae_trades), 1)

        cur_w = cur_l = max_w = max_l = 0
        for t in closed:
            p = t.get("pnl", 0)
            if p > 0: cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
            elif p < 0: cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)

        conn.close()

        return {
            "total": total, "active": active_count,
            "wins": wins, "losses": losses,
            "win_rate": round(wr, 1), "avg_pnl": round(avg_pnl, 2),
            "avg_mfe": round(avg_mfe, 2), "avg_mae": round(avg_mae, 2),
            "max_win_streak": max_w, "max_loss_streak": max_l,
            # 🆕 v6.4.18: إحصائيات تراكمية
            "cumulative": cumulative,
            "total_pnl": cumulative.get("total_pnl_x100", 0) / 100.0,
        }
    except Exception as e:
        log.warning(f"get_stats err: {e}")
        return {
            "total": 0, "active": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "avg_pnl": 0, "avg_mfe": 0, "avg_mae": 0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "cumulative": {}, "total_pnl": 0,
        }


def format_stats(stats: Dict) -> str:
    msg = "📊 <b>إحصائيات الصفقات</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"  • إجمالي: {stats['total']} | 🟢 نشطة: {stats['active']}\n"
    wr_emoji = "🟢" if stats['win_rate'] > 60 else ("🟡" if stats['win_rate'] > 40 else "🔴")
    msg += f"  • Win Rate: {wr_emoji} {stats['win_rate']}%\n"
    msg += f"  • Avg PnL: {stats['avg_pnl']:+.2f}%\n"
    msg += f"  • ✅ رابحة: {stats['wins']} | ❌ خاسرة: {stats['losses']}\n"
    if stats.get('avg_mfe', 0) != 0:
        msg += f"  • 📈 MFE avg: +{stats['avg_mfe']:.1f}% | 📉 MAE avg: {stats['avg_mae']:.1f}%\n"
    msg += f"  • 🔥 Max Win Streak: {stats['max_win_streak']}\n"
    msg += f"  • 💔 Max Loss Streak: {stats['max_loss_streak']}"
    # 🆕 v6.4.18: إحصائيات تراكمية
    cum = stats.get("cumulative", {})
    if cum:
        msg += "\n\n📊 <b>إحصائيات تراكمية:</b>\n"
        for key in ["tp1_count", "tp2_count", "tp3_count", "tp4_count", "tp5_count", "tp6_count",
                     "sl_after_tp1_count", "sl_after_tp2_count", "sl_after_tp3_count", "sl_after_tp4_count",
                     "sl_count", "expired_count"]:
            val = cum.get(key, 0)
            if val > 0:
                # 🆕 v6.4.82: ترجمة عربية واضحة لمفاتيح الستوب الديناميكي
                labels = {
                    "sl_after_tp1_count": "🎯 أُغلقت عند الستوب بعد هدف واحد (نجاح)",
                    "sl_after_tp2_count": "🎯🎯 أُغلقت عند الستوب بعد هدفين (نجاح)",
                    "sl_after_tp3_count": "🎯🎯🎯 أُغلقت عند الستوب بعد 3 أهداف (نجاح)",
                    "sl_after_tp4_count": "🏆 أُغلقت عند الستوب بعد 4 أهداف (نجاح)",
                }
                msg += f"  • {labels.get(key, key)}: {val}\n"
    return msg


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.18: Migration from old JSON to SQLite
# ═══════════════════════════════════════════════════════════

def migrate_from_json():
    """🆕 v6.4.18: هجرة البيانات من JSON القديم إلى SQLite."""
    old_file = "/tmp/trades.json"
    old_backup = "/tmp/trades_backup.json"

    for f in [old_file, old_backup]:
        if os.path.exists(f):
            try:
                with open(f, "r") as fh:
                    data = json.load(fh)
                if data:
                    log.info(f"📦 [MIGRATION] Found {sum(len(v) for v in data.values())} trades in {f}")
                    _save(data)
                    log.info(f"📦 [MIGRATION] Migrated to SQLite successfully")
                    # احذف القديم لتفادي التكرار
                    os.rename(f, f + ".migrated")
                    return True
            except Exception as e:
                log.warning(f"📦 [MIGRATION] Failed to migrate from {f}: {e}")
    return False


# ═══════════════════════════════════════════════════════════
# Initialize on import
# ═══════════════════════════════════════════════════════════

_init_db()
migrate_from_json()
