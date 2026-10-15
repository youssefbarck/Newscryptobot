"""
اختبارات نظام قفل الصفقة الواحدة لكل عملة (v6.1)
=================================================
7 اختبارات إلزامية:
  1) test_create_then_block_duplicate: إنشاء صفقة ثم منع التكرار
  2) test_persistent_storage_survives: الصفقة تبقى مقفولة بعد محو الذاكرة
  3) test_rebuild_cache_on_startup: إعادة بناء _active_cache عند الإقلاع
  4) test_tp1_keeps_lock: TP1 لا يحرر القفل (TP1 جزئي 20%)
  5) test_sl_releases_lock: SL يحرر القفل نهائياً
  6) test_tp3_releases_lock: TP3 (نهاية الصفقة) يحرر القفل
  7) test_atomic_concurrent_create: 10 threads تحاول إنشاء صفقة → واحد فقط ينجح
"""

import os, sys, json, time, threading, shutil

# استيراد tracker بعد ضبط LOCAL_FILE لمسار اختبار آمن
TEST_FILE = "/tmp/test_trades.json"
# استبدال المسار قبل الاستيراد
import tracker
tracker.LOCAL_FILE = TEST_FILE

# إعادة تعيين الحالة
if os.path.exists(TEST_FILE):
    os.remove(TEST_FILE)
tracker._active_cache.clear()


def _trade(symbol="BTC", signal_id=None):
    return {
        "signal_id": signal_id or f"{symbol}_{int(time.time()*1000)}",
        "symbol": symbol,
        "entry": 50000.0, "sl": 47000.0, "tp": 54000.0,
        "score": 75, "confirmed": ["EMA align", "BOS/CHOCH bullish"],
    }


# ─────────────────────────────────────────────────────────────
# 1) إنشاء صفقة ثم منع التكرار
# ─────────────────────────────────────────────────────────────
def test_create_then_block_duplicate():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "100"
    t1 = _trade("BTC", "btc_1")
    ok1 = tracker.try_create(cid, t1)
    assert ok1 is True, "First create should succeed"

    # محاولة تكرار لنفس العملة
    t2 = _trade("BTC", "btc_2")
    ok2 = tracker.try_create(cid, t2)
    assert ok2 is False, "Duplicate create should be blocked"

    # عملة مختلفة يجب أن تنجح
    t3 = _trade("ETH", "eth_1")
    ok3 = tracker.try_create(cid, t3)
    assert ok3 is True, "Different symbol should succeed"

    print("✅ Test 1 PASSED: create then block duplicate")


# ─────────────────────────────────────────────────────────────
# 2) التخزين الدائم: الصفقة تبقى مقفولة بعد محو الذاكرة
# ─────────────────────────────────────────────────────────────
def test_persistent_storage_survives():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "200"
    tracker.try_create(cid, _trade("SOL", "sol_1"))

    # محو الذاكرة (محاكاة restart بدون rebuild)
    tracker._active_cache.clear()
    assert "SOL" not in tracker._active_cache, "Cache should be cleared"

    # has_active_trade يجب أن يفحص persistent storage ويعثر على SOL
    has = tracker.has_active_trade("SOL", cid)
    assert has is True, "has_active_trade should find SOL in persistent storage"

    # try_create يجب أن يرفض التكرار (لأن persistent storage به SOL نشطة)
    ok = tracker.try_create(cid, _trade("SOL", "sol_2"))
    assert ok is False, "Duplicate from new instance must be blocked"

    print("✅ Test 2 PASSED: persistent storage survives memory wipe")


# ─────────────────────────────────────────────────────────────
# 3) إعادة بناء _active_cache عند الإقلاع
# ─────────────────────────────────────────────────────────────
def test_rebuild_cache_on_startup():
    # إعداد: ملف به 3 صفقات (2 نشطة + 1 منتهية)
    data = {
        "300": [
            {"signal_id": "a1", "symbol": "BTC", "status": "ACTIVE", "entry": 50000, "sl": 47000, "tp": 54000},
            {"signal_id": "a2", "symbol": "ETH", "status": "TP2_HIT", "entry": 3000, "sl": 2800, "tp": 3300},
            {"signal_id": "a3", "symbol": "XRP", "status": "STOP_LOSS", "entry": 0.6, "sl": 0.55, "tp": 0.7, "closed_at": 1},
        ]
    }
    with open(TEST_FILE, "w") as f:
        json.dump(data, f)
    tracker._active_cache.clear()

    # تنفيذ rebuild_cache
    tracker.rebuild_cache()

    # التحقق: BTC و ETH في الـ cache، XRP لا (لأن STOP_LOSS نهائي)
    assert "BTC" in tracker._active_cache, "BTC should be in cache (ACTIVE)"
    assert "ETH" in tracker._active_cache, "ETH should be in cache (TP2_HIT non-final)"
    assert "XRP" not in tracker._active_cache, "XRP should NOT be in cache (STOP_LOSS final)"
    assert len(tracker._active_cache) == 2, f"Expected 2 active, got {len(tracker._active_cache)}"

    print("✅ Test 3 PASSED: rebuild_cache restores non-final trades only")


# ─────────────────────────────────────────────────────────────
# 4) TP1 لا يحرر القفل (TP1 جزئي 20%)
# ─────────────────────────────────────────────────────────────
def test_tp1_keeps_lock():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "400"
    tracker.try_create(cid, _trade("ADA", "ada_1"))
    assert "ADA" in tracker._active_cache, "ADA should be locked after create"

    # TP1 hit
    ok = tracker.hit_tp(cid, "ada_1", 54000, 54500)
    assert ok is True, "hit_tp should return True"

    # التحقق: ADA ما يزال مقفولاً (TP1 جزئي)
    assert "ADA" in tracker._active_cache, "ADA should STAY locked after TP1 (partial exit)"

    # التحقق من status = TP1_HIT
    data = tracker._load()
    trade = next(t for t in data[cid] if t["signal_id"] == "ada_1")
    assert trade["status"] == "TP1_HIT", f"Expected TP1_HIT, got {trade['status']}"

    # 🆕 v6.2.1: التحقق أن hit_tp لا يطلق مرة أخرى بعد TP1_HIT
    ok2 = tracker.hit_tp(cid, "ada_1", 54000, 55000)
    assert ok2 is False, "hit_tp should NOT fire again after TP1_HIT (no duplicate)"

    # التحقق أن has_active_trade لا يزال يعود True
    assert tracker.has_active_trade("ADA", cid) is True, "ADA should still be active"

    print("✅ Test 4 PASSED: TP1 keeps lock + duplicate TP1 rejected")


# ─────────────────────────────────────────────────────────────
# 5) SL يحرر القفل نهائياً
# ─────────────────────────────────────────────────────────────
def test_sl_releases_lock():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "500"
    tracker.try_create(cid, _trade("DOT", "dot_1"))
    assert "DOT" in tracker._active_cache, "DOT should be locked"

    # SL hit
    ok = tracker.hit_sl(cid, "dot_1", 47000)
    assert ok is True, "hit_sl should return True"

    # التحقق: DOT تحرر من القفل
    assert "DOT" not in tracker._active_cache, "DOT should be UNLOCKED after SL"

    # التحقق من status = STOP_LOSS
    data = tracker._load()
    trade = next(t for t in data[cid] if t["signal_id"] == "dot_1")
    assert trade["status"] == "STOP_LOSS", f"Expected STOP_LOSS, got {trade['status']}"
    assert trade["closed_at"] is not None, "closed_at should be set"

    # التحقق أن has_active_trade يعود False الآن
    assert tracker.has_active_trade("DOT", cid) is False, "DOT should NOT be active after SL"

    # التحقق أن صفقة جديدة على DOT يمكن إنشاؤها الآن
    ok2 = tracker.try_create(cid, _trade("DOT", "dot_2"))
    assert ok2 is True, "Should be able to create new DOT trade after SL"

    print("✅ Test 5 PASSED: SL releases the lock (final)")


# ─────────────────────────────────────────────────────────────
# 6) TP3 (نهاية الصفقة) يحرر القفل
# ─────────────────────────────────────────────────────────────
def test_tp3_releases_lock():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "600"
    tracker.try_create(cid, _trade("LINK", "link_1"))
    assert "LINK" in tracker._active_cache, "LINK should be locked"

    # 🆕 v6.2.1: TP1 قبل TP3 (تسلسل طبيعي)
    ok_tp1 = tracker.hit_tp(cid, "link_1", 54000, 54500)
    assert ok_tp1 is True, "TP1 should fire"
    assert "LINK" in tracker._active_cache, "LINK should stay locked after TP1"

    # إغلاق نهائي عبر close_trade (TP3_HIT) — محاكاة سعر +5% فوق TP
    ok = tracker.close_trade(cid, "link_1", "TP3_HIT", 58000)
    assert ok is True, "close_trade should return True"

    # التحقق: LINK تحرر من القفل
    assert "LINK" not in tracker._active_cache, "LINK should be UNLOCKED after TP3_HIT"

    # التحقق من status
    data = tracker._load()
    trade = next(t for t in data[cid] if t["signal_id"] == "link_1")
    assert trade["status"] == "TP3_HIT", f"Expected TP3_HIT, got {trade['status']}"

    # 🆕 v6.2.1: PnL مركب — 20% عند TP1 + 80% عند TP3
    # entry=50000, tp1_price=54500, tp3_price=58000
    # pnl = 0.20 * (54500-50000)/50000 * 100 + 0.80 * (58000-50000)/50000 * 100
    #     = 0.20 * 9% + 0.80 * 16% = 1.8% + 12.8% = 14.6%
    expected_pnl = round(0.20 * (54500-50000)/50000 * 100 + 0.80 * (58000-50000)/50000 * 100, 2)
    assert trade["pnl"] == expected_pnl, f"PnL compound: expected {expected_pnl}, got {trade['pnl']}"

    # التحقق أن has_active_trade يعود False
    assert tracker.has_active_trade("LINK", cid) is False, "LINK should NOT be active after TP3"

    # أيضاً CANCELLED و EXPIRED يحرران القفل
    tracker.try_create(cid, _trade("LINK", "link_2"))
    assert "LINK" in tracker._active_cache
    tracker.close_trade(cid, "link_2", "CANCELLED", 50000)
    assert "LINK" not in tracker._active_cache, "CANCELLED should release lock"

    tracker.try_create(cid, _trade("LINK", "link_3"))
    tracker.close_trade(cid, "link_3", "EXPIRED", 50000)
    assert "LINK" not in tracker._active_cache, "EXPIRED should release lock"

    print("✅ Test 6 PASSED: TP3/CANCELLED/EXPIRED release lock + PnL compound correct")


# ─────────────────────────────────────────────────────────────
# 7) atomic: 10 threads تحاول إنشاء صفقة → واحد فقط ينجح
# ─────────────────────────────────────────────────────────────
def test_atomic_concurrent_create():
    tracker._active_cache.clear()
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)

    cid = "700"
    results = []
    lock_results = threading.Lock()

    def worker(i):
        t = _trade("ATOM", f"atom_{i}")
        ok = tracker.try_create(cid, t)
        with lock_results:
            results.append(ok)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    successes = sum(1 for r in results if r)
    failures = sum(1 for r in results if not r)

    assert successes == 1, f"Expected exactly 1 success, got {successes}"
    assert failures == 9, f"Expected 9 blocked, got {failures}"

    # التحقق أن صفقة واحدة فقط محفوظة في persistent storage لـ ATOM
    data = tracker._load()
    atom_trades = [t for t in data.get(cid, []) if t["symbol"] == "ATOM"]
    assert len(atom_trades) == 1, f"Expected 1 ATOM trade stored, got {len(atom_trades)}"

    print(f"✅ Test 7 PASSED: 10 concurrent attempts → 1 success + 9 blocked (atomic)")


# ─────────────────────────────────────────────────────────────
# تشغيل الكل
# ─────────────────────────────────────────────────────────────
def run_all():
    tests = [
        test_create_then_block_duplicate,
        test_persistent_storage_survives,
        test_rebuild_cache_on_startup,
        test_tp1_keeps_lock,
        test_sl_releases_lock,
        test_tp3_releases_lock,
        test_atomic_concurrent_create,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"❌ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__} ERROR: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"📊 Total: {len(tests)} | ✅ Passed: {passed} | ❌ Failed: {failed}")
    print(f"{'='*50}")
    # تنظيف
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
