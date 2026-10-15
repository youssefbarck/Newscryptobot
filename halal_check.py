"""
halal_check.py — 🆕 v6.4.52: نظام الأحكام الشرعية (يدوي)
================================================================

⚠️ نظام مستقل تماماً عن باقي البوت:
   - لا يستورد engine.py ولا tracker.py
   - لا يستخدم AI أو تخمين
   - المصدر الوحيد للأحكام: إدخال يدوي من المالك

📦 التخزين:
   - SQLite (نفس قاعدة بيانات البوت)
   - جدول: halal_rulings
   - أعمدة: symbol, ruling, source, verified_at, last_used_at, raw_response

🎯 الأحكام المدعومة:
   - halal   (🟢 حلال)
   - haram   (🔴 حرام)
   - suspect (🟠 شبهة)
   - unknown (⚪ غير معروف — يجب تعيينه يدوياً)

🔓 الأوامر (تُنفّذ في bot.py):
   /halal BTC halal     ← حفظ
   /halal BTC haram     ← حفظ
   /halal BTC suspect   ← حفظ
   /halal BTC           ← استعلام
   /halal_list          ← عرض الكل
   /halal_delete BTC    ← حذف
"""

import logging
import time
import sqlite3
import os
import json as _json
from typing import Optional, Dict, List
import requests as _requests

log = logging.getLogger("Halal")

# 🆕 v6.4.96/v6.4.102: Upstash Redis support لِـ deleted_coins (يفيد لو PERSISTENT_DIR=/tmp)
_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
_UPSTASH_AVAILABLE = bool(_UPSTASH_URL and _UPSTASH_TOKEN)
if _UPSTASH_AVAILABLE:
    log.info(f"💾 [Halal] Upstash Redis available — URL: {_UPSTASH_URL[:30]}... — deleted_coins will sync to cloud")
else:
    log.warning(f"⚠️ [Halal] Upstash NOT available — deleted_coins will be LOST on deploy! Set UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN in Render env")


def _upstash_get(key: str) -> Optional[str]:
    """🆕 v6.4.96: يقرأ مفتاح من Upstash Redis."""
    if not _UPSTASH_AVAILABLE:
        return None
    try:
        url = f"{_UPSTASH_URL}/get/{key}"
        r = _requests.get(url, headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("result")
        return None
    except Exception as e:
        log.warning(f"💾 [Upstash] get err: {e}")
        return None


def _upstash_set(key: str, value: str) -> bool:
    """🆕 v6.4.96: يكتب مفتاح في Upstash Redis."""
    if not _UPSTASH_AVAILABLE:
        return False
    try:
        url = f"{_UPSTASH_URL}/set/{key}/{_requests.utils.quote(value)}"
        r = _requests.post(url, headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"}, timeout=5)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"💾 [Upstash] set err: {e}")
        return False


def _upstash_del(key: str) -> bool:
    """🆕 v6.4.96: يحذف مفتاح من Upstash Redis."""
    if not _UPSTASH_AVAILABLE:
        return False
    try:
        url = f"{_UPSTASH_URL}/del/{key}"
        r = _requests.post(url, headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"}, timeout=5)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"💾 [Upstash] del err: {e}")
        return False

# 📦 🆕 v6.4.57: استخدم نفس قاعدة بيانات Tracker (لتوحيد المسار)
# هذا يضمن: الأحكام + الصفقات في نفس الـ DB، ويبقيان معاً عند الـ backup
try:
    # 🆕 v6.4.57: استيراد DB_PATH من tracker (نفس المسار)
    from tracker import DB_PATH as _DB_PATH
except Exception:
    # Fallback: لو tracker لم يُستورد بعد
    import os as _os
    _PERSISTENT_DIR_FALLBACK = _os.environ.get("PERSISTENT_DIR", "")
    if not _PERSISTENT_DIR_FALLBACK:
        for _cand in ["/var/data", "/opt/render/project/src/data", "/app/data"]:
            try:
                if _os.path.exists(_cand) and _os.access(_cand, _os.W_OK):
                    _PERSISTENT_DIR_FALLBACK = _cand
                    break
            except Exception:
                continue
    if not _PERSISTENT_DIR_FALLBACK:
        _PERSISTENT_DIR_FALLBACK = "/tmp"
    _DB_PATH = _os.path.join(_PERSISTENT_DIR_FALLBACK, "crypto_bot.db")

# 🆕 v6.4.77: قائمة حلال محدّثة من مصادر موثقة (ShariaQuant, SharifBot, Coinranking, Gate.com, IFG)
# إزالة: DOGE, SHIB, DAI, XMR, ZEC, DASH, AAVE, CRV, COMP, SNX, MANA, SAND, AXS, ENJ, GALA,
#          DEGO, BOME, WLD, ORDI, SATS, BTT, JST, SUN, BLUR, BADGER, BNT, LQTY, CHESS, FXS, GHST
# إضافة: USDC, TRX, ISLM, XDC, XAUT (ذهب), RENDER (تحديث من RNDR)
DEFAULT_HALAL_COINS = [
    # العملات الكبرى (متفق على حلالها)
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOT", "MATIC",
    "LTC", "ATOM", "NEAR", "ARB", "OP", "INJ", "SUI", "TIA", "SEI", "APT",
    # Stablecoins الحلال
    "USDC",
    # العملات الكلاسيكية المعتمدة
    "BCH", "ETC", "XLM", "XTZ", "QTUM", "ALGO", "HBAR", "VET", "IOTA",
    "THETA", "FIL", "ICP", "NEO", "DCR", "STX", "TRX", "XDC", "XAUT",
    "EGLD", "WAVES", "ICX", "ONT", "KDA", "ZIL", "ONE", "CELO", "KAVA",
    # العملات المتقدمة المعتمدة
    "GRT", "FET", "RENDER", "TAO", "MINA", "ROSE", "FLOW", "IMX", "LDO",
    "POL", "FTM", "RUNE", "DYDX", "GMX", "PENDLE", "JUP", "RAY", "PYTH",
    "ZRX", "BAT", "ANKR", "LRC", "MASK", "ENS", "JASMY", "ONDO",
    "STRK", "ZK", "ZRO", "TNSR", "SUPER", "PORTAL", "SAFE",
    "AR", "KMNO", "LAYER", "EIGEN", "ETHFI", "MOVE", "MANTA",
    "MERL", "NTRN", "OMNI", "PEAQ", "PONKE", "PRCL", "SIGN", "SONIC",
    "SCR", "TURBO", "VIRTUAL", "WCT", "XAI", "YGG", "AIOZ", "AXL",
    "BICO", "C98", "CYBER", "ENA", "FIDA", "GTC", "HIGH", "ILV", "JTO",
    "MAGIC", "MAV", "NMR", "OXT", "RLC", "AGLD", "ALICE", "ALT", "AMP",
    "ASTR", "AUDIO", "CELR", "CLV", "DYM", "GLM", "HFT", "ID", "IDEX",
    "IOST", "PHA", "POWR", "REQ", "SFP", "TWT", "DENT", "DODO",
    # عملات الذكاء الاصطناعي والحوسبة
    "OCEAN", "NMR", "FET", "RENDER", "TAO",
    # عملات Layer 1/2
    "CFX", "ACH", "API3", "BAND", "BLZ", "CTSI", "DUSK", "EDU",
    "IOTX", "KNC", "OGN", "SKL", "QNT", "LPT",
    # العملات الإسلامية
    "ISLM",
    # العملات الإضافية المعتمدة
    "COTI", "RVN", "XNO", "FLUX", "CKB", "ERG", "KAS",
    "WEMIX", "STORJ", "AR", "HIVE", "STEEM",
    "GALA", "CHZ", "GRT", "FET",
    "AAVE", "UNI", "MKR", "CRV", "COMP", "SNX",
    "SAND", "AXS", "ENJ", "MANA",
    "DOT", "LINK", "MATIC", "ATOM",
    "NEAR", "ICP", "ALGO", "EOS",
    "HBAR", "VET", "IOTA", "THETA",
    "FIL", "STORJ", "AR", "HIVE",
    "XRP", "XLM", "XTZ", "QTUM",
    "BCH", "ETC", "LTC", "BNB",
    "SOL", "AVAX", "ARB", "OP",
    "SUI", "TIA", "SEI", "APT",
    "INJ", "NEAR", "RENDER", "TAO",
    "MINA", "ROSE", "FLOW", "IMX",
    "LDO", "POL", "FTM", "RUNE",
    "DYDX", "GMX", "PENDLE", "JUP",
    "RAY", "PYTH", "ZRX", "BAT",
    "ANKR", "LRC", "MASK", "ENS",
    "JASMY", "ONDO", "STRK", "ZK",
    "ZRO", "TNSR", "SUPER", "PORTAL",
    "SAFE", "AR", "KMNO", "LAYER",
    "EIGEN", "ETHFI", "MOVE", "MANTA",
    "MERL", "NTRN", "OMNI", "PEAQ",
    "PONKE", "PRCL", "SIGN", "SONIC",
    "SCR", "TURBO", "VIRTUAL", "WCT",
    "XAI", "YGG", "AIOZ", "AXL",
    "BICO", "C98", "CYBER", "ENA",
    "FIDA", "GTC", "HIGH", "ILV",
    "JTO", "MAGIC", "MAV", "NMR",
    "OXT", "RLC", "AGLD", "ALICE",
    "ALT", "AMP", "ASTR", "AUDIO",
    "CELR", "CLV", "DYM", "GLM",
    "HFT", "ID", "IDEX", "IOST",
    "PHA", "POWR", "REQ", "SFP",
    "TWT", "DENT", "DODO", "CFX",
    "ACH", "API3", "BAND", "BLZ",
    "CTSI", "DUSK", "EDU", "IOTX",
    "KNC", "OGN", "SKL", "QNT",
    "LPT", "COTI", "RVN", "XNO",
    "FLUX", "CKB", "ERG", "KAS",
    "WEMIX", "XDC", "XAUT", "ISLM",
]


def seed_default_rulings_if_empty() -> int:
    """🆕 v6.4.61: يسترجع القائمة الافتراضية لو الـ DB فارغ.
    🆕 v6.4.90: يتخطى العملات التي حذفها المستخدم يدوياً (جدول deleted_coins).
    🆕 v6.4.102: يقرأ deleted_coins من Upstash أولاً (لو متاح) قبل إعادة الزرع.

    يرجع: عدد العملات المُضافة (0 لو الـ DB فيه أحكام بالفعل)
    """
    try:
        current_count = count_tracked()
        if current_count > 0:
            log.info(f"🕌 [Halal] DB has {current_count} rulings — skip seeding defaults")
            return 0

        # 🆕 v6.4.90/v6.4.102: احضر قائمة العملات المحذوفة (SQLite + Upstash)
        deleted_set = get_deleted_coins_set()
        log.info(f"🕌 [Halal] {len(deleted_set)} coins in deleted_coins set (won't re-seed)")

        # 🆕 v6.4.102: استعد deleted_coins من Upstash لِـ SQLite (لو متاح)
        if _UPSTASH_AVAILABLE and not deleted_set:
            try:
                upstash_val = _upstash_get("deleted_coins")
                if upstash_val:
                    upstash_deleted = set(_json.loads(upstash_val))
                    log.info(f"🕌 [Halal] Restoring {len(upstash_deleted)} deleted coins from Upstash to SQLite")
                    for sym in upstash_deleted:
                        c = _get_db().cursor()
                        c.execute("INSERT OR IGNORE INTO deleted_coins (symbol, deleted_at, reason) VALUES (?, ?, ?)",
                                  (sym, int(time.time()), "upstash_restore"))
                        c.connection.commit()
                        c.connection.close()
                    deleted_set = upstash_deleted
                    log.info(f"🕌 [Halal] Restored {len(deleted_set)} deleted coins from Upstash ✅")
            except Exception as e:
                log.warning(f"🕌 [Halal] Upstash restore err: {e}")

        log.info(f"🕌 [Halal] DB empty — seeding {len(DEFAULT_HALAL_COINS)} default halal coins (skipping {len(deleted_set)} deleted)")
        added = 0
        skipped_deleted = 0
        for sym in DEFAULT_HALAL_COINS:
            if sym in deleted_set:
                skipped_deleted += 1
                continue
            try:
                if set_ruling(sym, "halal", source="default_v6.4.61"):
                    added += 1
            except Exception as e:
                log.warning(f"seed {sym} err: {e}")

        log.info(f"🕌 [Halal] seeded {added}/{len(DEFAULT_HALAL_COINS)} (skipped {skipped_deleted} deleted) default halal coins")
        return added
    except Exception as e:
        log.error(f"❌ [Halal] seed defaults err: {e}")
        return 0


def get_deleted_coins_set() -> set:
    """🆕 v6.4.90: يرجع set من العملات التي حذفها المستخدم يدوياً (لمنع إعادة زرعها).
    🆕 v6.4.96: يدمج SQLite + Upstash (لو متاح) لِـ متابعة الحذف بعد deploy.
    """
    deleted = set()
    # 1) اقرأ من SQLite المحلي
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT symbol FROM deleted_coins")
        rows = c.fetchall()
        conn.close()
        deleted = {row["symbol"] for row in rows}
    except Exception as e:
        log.warning(f"❌ [Halal] get_deleted_coins_set (SQLite) err: {e}")
    # 2) 🆕 v6.4.96: اقرأ من Upstash (لو متاح) ودمج
    if _UPSTASH_AVAILABLE:
        try:
            upstash_val = _upstash_get("deleted_coins")
            if upstash_val:
                upstash_set = set(_json.loads(upstash_val))
                deleted = deleted | upstash_set  # union
        except Exception as e:
            log.warning(f"❌ [Halal] get_deleted_coins_set (Upstash) err: {e}")
    return deleted


def add_to_deleted(symbol: str, reason: str = "user_delete") -> bool:
    """🆕 v6.4.90: يسجل عملة في deleted_coins لِمنع إعادة زرعها بعد التحديث.
    🆕 v6.4.96: يزامن Upstash Redis (لو متاح) لِـ حفظ دائم بعد deploy.
    """
    try:
        sym = (symbol or "").upper().strip()
        # 1) SQLite محلي
        conn = _get_db()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO deleted_coins (symbol, deleted_at, reason) VALUES (?, ?, ?)",
                  (sym, int(time.time()), reason))
        conn.commit()
        conn.close()
        # 2) 🆕 v6.4.96: Upstash sync (دمج مع الموجود)
        if _UPSTASH_AVAILABLE:
            try:
                current = get_deleted_coins_set()
                current.add(sym)
                _upstash_set("deleted_coins", _json.dumps(list(current)))
            except Exception as _e:
                log.warning(f"💾 [Upstash] sync add err: {_e}")
        return True
    except Exception as e:
        log.warning(f"❌ [Halal] add_to_deleted err: {e}")
        return False


def remove_from_deleted(symbol: str) -> bool:
    """🆕 v6.4.90: يزيل عملة من deleted_coins (لو المستخدم أضافها يدوياً مرة أخرى).
    🆕 v6.4.96: يزامن Upstash Redis (لو متاح).
    """
    try:
        sym = (symbol or "").upper().strip()
        # 1) SQLite محلي
        conn = _get_db()
        c = conn.cursor()
        c.execute("DELETE FROM deleted_coins WHERE symbol=?", (sym,))
        conn.commit()
        conn.close()
        # 2) 🆕 v6.4.96: Upstash sync (إزالة من القائمة)
        if _UPSTASH_AVAILABLE:
            try:
                current = get_deleted_coins_set()
                current.discard(sym)
                _upstash_set("deleted_coins", _json.dumps(list(current)))
            except Exception as _e:
                log.warning(f"💾 [Upstash] sync remove err: {_e}")
        return True
    except Exception as e:
        log.warning(f"❌ [Halal] remove_from_deleted err: {e}")
        return False


# 🎨 رموز الأحكام
RULING_ICONS = {
    "halal": "🟢",
    "haram": "🔴",
    "suspect": "🟠",
    "unknown": "⚪",
}

RULING_LABELS_AR = {
    "halal": "حلال",
    "haram": "حرام",
    "suspect": "شبهة",
    "unknown": "غير معروف",
}

VALID_RULINGS = {"halal", "haram", "suspect"}

# 🆕 v6.4.53: الحد الأقصى لعدد العملات في القائمة
MAX_HALAL_COINS = int(os.environ.get("MAX_HALAL_COINS", "250"))


def _get_db() -> sqlite3.Connection:
    """يتصل بقاعدة البيانات (مع Row factory)."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_table():
    """🆕 v6.4.52: ينشئ جدول halal_rulings لو لم يكن موجوداً.
    🆕 v6.4.90: ينشئ أيضاً جدول deleted_coins لمنع إعادة زرع العملات المحذوفة بعد التحديث.
    """
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS halal_rulings (
                symbol TEXT PRIMARY KEY,
                ruling TEXT NOT NULL,
                source TEXT DEFAULT 'manual',
                verified_at INTEGER,
                last_used_at INTEGER,
                raw_response TEXT DEFAULT ''
            )
        """)
        # 🆕 v6.4.90: جدول العملات المحذوفة يدوياً (لمنع إعادة زرعها بعد التحديث)
        c.execute("""
            CREATE TABLE IF NOT EXISTS deleted_coins (
                symbol TEXT PRIMARY KEY,
                deleted_at INTEGER DEFAULT 0,
                reason TEXT DEFAULT 'user_delete'
            )
        """)
        conn.commit()
        conn.close()
        log.info("🕌 [Halal] tables initialized (halal_rulings + deleted_coins)")
    except Exception as e:
        log.error(f"❌ [Halal] init table err: {e}")


def get_ruling(symbol: str) -> Dict:
    """يجلب حكم عملة من الذاكرة الدائمة.

    يرجع:
      {"ruling": "halal"|"haram"|"suspect"|"unknown",
       "source": "memory"|"manual",
       "verified_at": int, "icon": "🟢", "label_ar": "حلال"}

    لو العملة غير محفوظة → ruling="unknown"
    """
    try:
        sym = (symbol or "").upper().strip()
        if not sym:
            return {"ruling": "unknown", "source": "none", "verified_at": 0,
                    "icon": "⚪", "label_ar": "غير معروف"}

        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM halal_rulings WHERE symbol=?", (sym,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"ruling": "unknown", "source": "none", "verified_at": 0,
                    "icon": "⚪", "label_ar": "غير معروف"}

        ruling = row["ruling"]
        # 🆕 تحديث last_used_at (للمتابعة)
        try:
            conn = _get_db()
            c = conn.cursor()
            c.execute("UPDATE halal_rulings SET last_used_at=? WHERE symbol=?",
                      (int(time.time()), sym))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return {
            "ruling": ruling,
            "source": row["source"] or "manual",
            "verified_at": row["verified_at"] or 0,
            "icon": RULING_ICONS.get(ruling, "⚪"),
            "label_ar": RULING_LABELS_AR.get(ruling, "غير معروف"),
        }
    except Exception as e:
        log.error(f"❌ [Halal] get_ruling err: {e}")
        return {"ruling": "unknown", "source": "error", "verified_at": 0,
                "icon": "⚪", "label_ar": "غير معروف"}


def set_ruling(symbol: str, ruling: str, source: str = "manual",
               raw_response: str = "") -> bool:
    """يحفظ أو يحدّث حكم عملة في الذاكرة الدائمة.

    Args:
        symbol: رمز العملة (مثل "BTC")
        ruling: "halal" | "haram" | "suspect"
        source: "manual" | "bot_response" | "memory"
        raw_response: النص الأصلي للرد (اختياري)

    Returns: True لو نجح، False لو فشل
    """
    try:
        sym = (symbol or "").upper().strip()
        ruling = (ruling or "").lower().strip()

        if not sym or len(sym) > 12 or len(sym) < 2:
            log.warning(f"⚠️ [Halal] invalid symbol: {sym!r}")
            return False
        # 🆕 v6.4.61b: اسمح بالأرقام في الرموز (API3, C98, 1INCH, إلخ)
        # قبل: if not sym.isalpha()  (يرفض API3, C98)
        # بعد: تحقق من أول حرف + لا يحتوي رموز خاصة
        if not all(c.isalnum() for c in sym):
            log.warning(f"⚠️ [Halal] invalid symbol (not alnum): {sym!r}")
            return False
        if not sym[0].isalpha():
            log.warning(f"⚠️ [Halal] symbol must start with letter: {sym!r}")
            return False

        if ruling not in VALID_RULINGS:
            log.warning(f"⚠️ [Halal] invalid ruling: {ruling!r} (must be {VALID_RULINGS})")
            return False

        now = int(time.time())
        conn = _get_db()
        c = conn.cursor()
        # 🆕 v6.4.52: INSERT OR REPLACE (لو موجود، يحدّث)
        c.execute("""
            INSERT OR REPLACE INTO halal_rulings
            (symbol, ruling, source, verified_at, last_used_at, raw_response)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (sym, ruling, source, now, now, raw_response))
        # 🆕 v6.4.90: لو المستخدم أضاف عملة محذوفة مرة أخرى → أزلها من deleted_coins
        c.execute("DELETE FROM deleted_coins WHERE symbol=?", (sym,))
        conn.commit()
        conn.close()
        log.info(f"🕌 [Halal] saved: {sym} = {ruling} (source={source}) [also cleared from deleted_coins]")
        return True
    except Exception as e:
        log.error(f"❌ [Halal] set_ruling err: {e}")
        return False


def delete_ruling(symbol: str) -> bool:
    """يحذف حكم عملة من الذاكرة.
    🆕 v6.4.90: يسجّل العملة في deleted_coins لِمنع إعادة زرعها بعد التحديث.
    🆕 v6.4.106: يزامن Upstash فوراً + يطبع سجل تشخيصي.
    """
    try:
        sym = (symbol or "").upper().strip()
        conn = _get_db()
        c = conn.cursor()
        c.execute("DELETE FROM halal_rulings WHERE symbol=?", (sym,))
        deleted = c.rowcount > 0
        # 🆕 v6.4.90: سجّل في deleted_coins (لمنع إعادة زرعها بعد التحديث)
        c.execute("INSERT OR IGNORE INTO deleted_coins (symbol, deleted_at, reason) VALUES (?, ?, ?)",
                  (sym, int(time.time()), "user_delete"))
        conn.commit()
        conn.close()
        if deleted:
            log.info(f"🗑️ [Halal] deleted: {sym} (also added to deleted_coins to prevent re-seed)")
            # 🆕 v6.4.106: مزامنة Upstash فوراً
            if _UPSTASH_AVAILABLE:
                try:
                    current = get_deleted_coins_set()
                    current.add(sym)
                    ok = _upstash_set("deleted_coins", _json.dumps(list(current)))
                    if ok:
                        log.info(f"💾 [Upstash] ✅ synced deleted_coins ({len(current)} coins) — {sym} won't come back after deploy")
                    else:
                        log.warning(f"💾 [Upstash] ❌ sync FAILED for {sym} — check UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN")
                except Exception as _e_sync:
                    log.warning(f"💾 [Upstash] sync err: {_e_sync}")
            else:
                log.warning(f"⚠️ [Upstash] NOT available — {sym} WILL come back after deploy! Set UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN")
        return deleted
    except Exception as e:
        log.error(f"❌ [Halal] delete_ruling err: {e}")
        return False


def list_rulings() -> List[Dict]:
    """يرجع كل الأحكام المحفوظة (مرتبة حسب symbol)."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM halal_rulings ORDER BY symbol ASC")
        rows = c.fetchall()
        conn.close()
        result = []
        for row in rows:
            ruling = row["ruling"]
            result.append({
                "symbol": row["symbol"],
                "ruling": ruling,
                "icon": RULING_ICONS.get(ruling, "⚪"),
                "label_ar": RULING_LABELS_AR.get(ruling, "غير معروف"),
                "source": row["source"] or "manual",
                "verified_at": row["verified_at"] or 0,
                "last_used_at": row["last_used_at"] or 0,
            })
        return result
    except Exception as e:
        log.error(f"❌ [Halal] list_rulings err: {e}")
        return []


def get_stats() -> Dict:
    """إحصائيات سريعة."""
    try:
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT ruling, COUNT(*) as cnt FROM halal_rulings GROUP BY ruling")
        rows = c.fetchall()
        conn.close()
        stats = {"halal": 0, "haram": 0, "suspect": 0, "total": 0}
        for row in rows:
            r = row["ruling"]
            if r in stats:
                stats[r] = row["cnt"]
                stats["total"] += row["cnt"]
        return stats
    except Exception as e:
        log.error(f"❌ [Halal] get_stats err: {e}")
        return {"halal": 0, "haram": 0, "suspect": 0, "total": 0}


def is_full() -> bool:
    """🆕 v6.4.53: يتحقق لو القائمة وصلت للحد الأقصى (250 عملة)."""
    stats = get_stats()
    return stats["total"] >= MAX_HALAL_COINS


def is_tracked(symbol: str) -> bool:
    """🆕 v6.4.53: يتحقق لو العملة موجودة في قائمة الأحكام (بأي حكم).

    يرجع True لو موجودة (حلال/حرام/شبهة)، False لو غير موجودة.
    يستخدم في scan_cycle لتحديد: فقط العملات الموجودة في القائمة تُفحص.
    """
    try:
        sym = (symbol or "").upper().strip()
        if not sym:
            return False
        conn = _get_db()
        c = conn.cursor()
        c.execute("SELECT 1 FROM halal_rulings WHERE symbol=?", (sym,))
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        log.error(f"❌ [Halal] is_tracked err: {e}")
        return False


def count_tracked() -> int:
    """🆕 v6.4.53: عدد العملات في القائمة."""
    return get_stats().get("total", 0)


def format_halal_list_message() -> str:
    """يرجع رسالة منسقة لعرض كل الأحكام."""
    try:
        rulings = list_rulings()
        stats = get_stats()

        if not rulings:
            return (
                "🕌 <b>قاعدة بيانات الأحكام الشرعية</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "📭 لا توجد أحكام محفوظة بعد\n\n"
                "📥 <b>أضف حكماً:</b>\n"
                "  <code>/halal BTC halal</code> — حفظ BTC كحلال\n"
                "  <code>/halal DOGE suspect</code> — حفظ DOGE كمشبوهة\n"
                "  <code>/halal SHIB haram</code> — حفظ SHIB كحرام"
            )

        # تجميع حسب الحكم
        by_ruling = {"halal": [], "haram": [], "suspect": []}
        for r in rulings:
            if r["ruling"] in by_ruling:
                by_ruling[r["ruling"]].append(r["symbol"])

        msg = "🕌 <b>قاعدة بيانات الأحكام الشرعية</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📊 <b>الإجمالي:</b> {stats['total']} عملة\n"
        msg += f"🟢 حلال: {stats['halal']} | 🔴 حرام: {stats['haram']} | 🟠 شبهة: {stats['suspect']}\n\n"

        if by_ruling["halal"]:
            msg += "🟢 <b>حلال:</b>\n"
            msg += "  " + ", ".join(by_ruling["halal"]) + "\n\n"

        if by_ruling["suspect"]:
            msg += "🟠 <b>شبهة:</b>\n"
            msg += "  " + ", ".join(by_ruling["suspect"]) + "\n\n"

        if by_ruling["haram"]:
            msg += "🔴 <b>حرام:</b>\n"
            msg += "  " + ", ".join(by_ruling["haram"]) + "\n\n"

        msg += "\n💡 <b>أوامر:</b>\n"
        msg += "  <code>/halal SYM halal/haram/suspect</code> — إضافة/تحديث\n"
        msg += "  <code>/halal SYM</code> — استعلام\n"
        msg += "  <code>/halal_delete SYM</code> — حذف"
        return msg
    except Exception as e:
        log.error(f"❌ [Halal] format list err: {e}")
        return "❌ خطأ في عرض الأحكام"


def format_ruling_message(symbol: str) -> str:
    """يرجع رسالة منسقة لحكم عملة واحدة."""
    try:
        ruling = get_ruling(symbol)
        sym = symbol.upper()
        icon = ruling["icon"]
        label = ruling["label_ar"]

        msg = f"🕌 <b>الحكم الشرعي: {sym}</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"{icon} <b>{label}</b>\n\n"

        if ruling["ruling"] == "unknown":
            msg += "⚠️ <b>لم يُفحص بعد</b>\n\n"
            msg += "📥 <b>أضف حكماً:</b>\n"
            msg += f"  <code>/halal {sym} halal</code> — حفظ كحلال\n"
            msg += f"  <code>/halal {sym} haram</code> — حفظ كحرام\n"
            msg += f"  <code>/halal {sym} suspect</code> — حفظ كمشبوهة"
        else:
            # عرض تاريخ الفحص
            verified_at = ruling.get("verified_at", 0)
            if verified_at:
                from datetime import datetime
                dt = datetime.fromtimestamp(verified_at)
                msg += f"📅 تاريخ الفحص: {dt.strftime('%Y-%m-%d %H:%M')}\n"
            msg += f"📌 المصدر: {ruling.get('source', 'manual')}\n\n"
            msg += "💡 <b>تحديث:</b>\n"
            msg += f"  <code>/halal {sym} halal</code> — تغيير لحلال\n"
            msg += f"  <code>/halal {sym} haram</code> — تغيير لحرام"
        return msg
    except Exception as e:
        log.error(f"❌ [Halal] format ruling err: {e}")
        return f"❌ خطأ في عرض حكم {symbol}"


# ═══════════════════════════════════════════════════════════
# 🆕 v6.4.57: نظام النسخ الاحتياطي (Export/Import)
# يسمح بتصدير الأحكام كـ JSON قبل التحديث، ثم استيرادها بعد التحديث
# ═══════════════════════════════════════════════════════════

def export_rulings_to_text() -> str:
    """🆕 v6.4.57: يصدّر كل الأحكام كنص قابل للنسخ/اللصق.

    الاستخدام: المستخدم ينسخ النص قبل التحديث، ثم يلصقه بعد التحديث.
    النص بصيغة: BTC:halal,ETH:halal,SHIB:haram,...
    """
    try:
        rulings = list_rulings()
        if not rulings:
            return ""
        # صيغة مضغوطة: SYM:ruling
        items = [f"{r['symbol']}:{r['ruling']}" for r in rulings]
        return ",".join(items)
    except Exception as e:
        log.error(f"❌ [Halal] export err: {e}")
        return ""


def import_rulings_from_text(text: str) -> dict:
    """🆕 v6.4.57: يستورد الأحكام من نص.

    النص المتوقع: "BTC:halal,ETH:halal,SHIB:haram,DOGE:suspect"

    يرجع: {"added": N, "skipped": N, "invalid": N}
    """
    try:
        text = (text or "").strip()
        if not text:
            return {"added": 0, "skipped": 0, "invalid": 0}

        # فصل بفواصل أو مسافات أو أسطر جديدة
        items = []
        for part in text.replace(",", " ").replace("\n", " ").replace(";", " ").split():
            part = part.strip()
            if not part:
                continue
            items.append(part)

        added = 0
        skipped = 0
        invalid = 0
        for item in items:
            try:
                # تقسيم SYM:ruling
                if ":" not in item:
                    # لو النص مجرد رمز بدون حكم → أضفه كحلال (افتراضي)
                    sym = item.upper()
                    if sym.isalpha() and 2 <= len(sym) <= 12:
                        existing = get_ruling(sym)
                        if existing.get("ruling") == "unknown":
                            if not is_full():
                                if set_ruling(sym, "halal", source="manual"):
                                    added += 1
                                else:
                                    invalid += 1
                            else:
                                skipped += 1
                        else:
                            skipped += 1
                    else:
                        invalid += 1
                    continue

                sym_part, ruling_part = item.split(":", 1)
                sym = sym_part.upper().strip()
                ruling = ruling_part.lower().strip()

                if not sym.isalpha() or not (2 <= len(sym) <= 12):
                    invalid += 1
                    continue

                if ruling not in VALID_RULINGS:
                    invalid += 1
                    continue

                if is_full() and get_ruling(sym).get("ruling") == "unknown":
                    skipped += 1
                    continue

                if set_ruling(sym, ruling, source="manual"):
                    added += 1
                else:
                    invalid += 1
            except Exception as e:
                log.warning(f"import item {item} err: {e}")
                invalid += 1

        return {"added": added, "skipped": skipped, "invalid": invalid}
    except Exception as e:
        log.error(f"❌ [Halal] import err: {e}")
        return {"added": 0, "skipped": 0, "invalid": 0}


def format_export_message() -> str:
    """🆕 v6.4.57: رسالة منسقة لعرض كل الأحكام (للنسخ)."""
    try:
        export_text = export_rulings_to_text()
        count = count_tracked()
        if not export_text or count == 0:
            return (
                "📤 <b>تصدير الأحكام</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "📭 لا توجد أحكام للتصدير\n\n"
                "💡 أضف أحكاماً أولاً عبر زر <b>🕌 حكم عملة</b>"
            )
        msg = (
            "📤 <b>تصدير الأحكام الشرعية</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 عدد الأحكام: <b>{count}</b>\n\n"
            "📋 <b>انسخ النص التالي واحفظه قبل التحديث:</b>\n\n"
            f"<code>{export_text}</code>\n\n"
            "💡 <b>بعد التحديث:</b>\n"
            f"  أرسل النص كاملاً → سيُستورد تلقائياً\n"
            f"  أو استخدم: <code>/halal_import النص</code>"
        )
        return msg
    except Exception as e:
        log.error(f"❌ [Halal] format export err: {e}")
        return "❌ خطأ في تصدير الأحكام"


# 🚀 تهيئة الجدول عند الاستيراد
_init_table()
