"""
bybit_trader.py — 🆕 v6.4.119: تداول تلقائي على Bybit Testnet (دولار تجريبي)
================================================================================

🎯 المنطق:
   - ينصت لِـ الصفقات اللي تُرسل للقناة (V1/V2/V3)
   - يشتري تلقائياً على Bybit Testnet
   - يضع أوامر بيع عند TP1/TP2/TP3 و SL
   - يقسّم المحفظة التجريبية لِـ 20 صفقة (5% لِـ كل صفقة)
   - لا يرسل أي تنبيه للقنوات أو البوت
   - يسجل كل الصفقات في ملف JSON محلي

⚙️ الإعدادات (env):
   - BYBIT_TESTNET_API_KEY = API key من testnet.bybit.com
   - BYBIT_TESTNET_API_SECRET = API secret من testnet.bybit.com
   - BYBIT_AUTO_TRADE_ENABLED = 1 (تشغيل) / 0 (إيقاف)
   - BYBIT_TRADE_AMOUNT = 10 (مبلغ كل صفقة بالـ USDT)

🧱 إزالة: احذف bybit_trader.py + احذف import + احذف الاستدعاء من bot.py
"""

import logging
import time
import os
import json
import hmac
import hashlib
import requests
from typing import Optional, Dict

log = logging.getLogger("BybitTrader")

# ═══ إعدادات ═══
_API_KEY = os.environ.get("BYBIT_TESTNET_API_KEY", "").strip()
_API_SECRET = os.environ.get("BYBIT_TESTNET_API_SECRET", "").strip()
_AUTO_TRADE_ENABLED = os.environ.get("BYBIT_AUTO_TRADE_ENABLED", "0") == "1"
_TRADE_AMOUNT = float(os.environ.get("BYBIT_TRADE_AMOUNT", "10"))
_WALLET_DIVISION = int(os.environ.get("BYBIT_WALLET_DIVISION", "20"))  # 20 صفقة

# Bybit Testnet base URL
_BASE_URL = "https://api-testnet.bybit.com"

# ملف سجل الصفقات
_PERSISTENT_DIR = os.environ.get("PERSISTENT_DIR", "/tmp")
_TRADE_LOG_FILE = os.path.join(_PERSISTENT_DIR, "bybit_trades.json")

# قائمة الصفقات المُتابعة
_active_trades = {}

_AVAILABLE = bool(_API_KEY and _API_SECRET and _AUTO_TRADE_ENABLED)
if _AVAILABLE:
    log.info(f"💸 [BybitTrader] مفعّل — Testnet amount=${_TRADE_AMOUNT} division={_WALLET_DIVISION}")
else:
    log.info(f"💸 [BybitTrader] معطّل — BYBIT_AUTO_TRADE_ENABLED=0 أو مفاتيح ناقصة")


def _sign(params: Dict) -> str:
    """يوقّع طلب Bybit API."""
    try:
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hmac.new(_API_SECRET.encode(), param_str.encode(), hashlib.sha256).hexdigest()
    except Exception as e:
        log.warning(f"💸 [BybitTrader] sign err: {e}")
        return ""


def _api_call(method: str, endpoint: str, params: Dict = None) -> Optional[Dict]:
    """يرسل طلب لِـ Bybit Testnet API."""
    try:
        if not _API_KEY or not _API_SECRET:
            return None
        params = params or {}
        params["api_key"] = _API_KEY
        params["timestamp"] = int(time.time() * 1000)
        params["recv_window"] = 5000
        sign = _sign(params)
        params["sign"] = sign

        url = f"{_BASE_URL}{endpoint}"
        if method == "GET":
            r = requests.get(url, params=params, timeout=10)
        else:
            r = requests.post(url, data=params, timeout=10)

        if r.status_code == 200:
            data = r.json()
            if data.get("retCode") == 0 or data.get("ret_code") == 0:
                return data.get("result", {})
            else:
                log.warning(f"💸 [BybitTrader] API err: {data.get('retMsg', '')}")
                return None
        else:
            log.warning(f"💸 [BybitTrader] HTTP {r.status_code}")
            return None
    except Exception as e:
        log.warning(f"💸 [BybitTrader] API call err: {e}")
        return None


def _get_balance() -> Optional[float]:
    """يجلب رصيد USDT على Bybit Testnet."""
    try:
        result = _api_call("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        if not result:
            return None
        # ابحث عن USDT في القائمة
        for account in result.get("list", []):
            for coin in account.get("coin", []):
                if coin.get("coin") == "USDT":
                    return float(coin.get("walletBalance", 0))
        return None
    except Exception as e:
        log.warning(f"💸 [BybitTrader] balance err: {e}")
        return None


def _place_market_buy(symbol: str, qty: float) -> Optional[str]:
    """يضع أمر شراء سوقي على Bybit Testnet. يرجع order_id أو None."""
    try:
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": "Buy",
            "orderType": "Market",
            "qty": str(qty),
        }
        result = _api_call("POST", "/v5/order/create", params)
        if result:
            order_id = result.get("orderId", "")
            log.info(f"💸 [BybitTrader] شراء {symbol} qty={qty} — order_id={order_id}")
            return order_id
        return None
    except Exception as e:
        log.warning(f"💸 [BybitTrader] buy err: {e}")
        return None


def _place_limit_sell(symbol: str, qty: float, price: float) -> Optional[str]:
    """يضع أمر بيع محدد عند سعر معين (TP أو SL)."""
    try:
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": "Sell",
            "orderType": "Limit",
            "qty": str(qty),
            "price": str(price),
        }
        result = _api_call("POST", "/v5/order/create", params)
        if result:
            order_id = result.get("orderId", "")
            log.info(f"💸 [BybitTrader] بيع {symbol} qty={qty} @ {price} — order_id={order_id}")
            return order_id
        return None
    except Exception as e:
        log.warning(f"💸 [BybitTrader] sell err: {e}")
        return None


def _get_symbol_info(symbol: str) -> Optional[Dict]:
    """يجلب معلومات العملة (min qty, step size) من Bybit."""
    try:
        result = _api_call("GET", "/v5/market/instruments-info", {"category": "spot", "symbol": symbol})
        if result and result.get("list"):
            item = result["list"][0]
            lot = item.get("lotSizeFilter", {})
            return {
                "min_qty": float(lot.get("minOrderQty", "0")),
                "step_size": float(lot.get("qtyStep", "0")),
                "min_notional": float(lot.get("minNotionalValue", "0")),
            }
        return None
    except Exception:
        return None


def _format_symbol(symbol: str) -> str:
    """يحوّل رمز البوت لِـ رمز Bybit (مثلاً BTC → BTCUSDT)."""
    return f"{symbol.upper()}USDT"


def _round_qty(qty: float, step_size: float) -> float:
    """يقرّب الكمية لِـ step size المناسب."""
    if step_size <= 0:
        return round(qty, 4)
    return round(qty / step_size) * step_size


def _save_trade_log(trade: Dict):
    """يسجل صفقة في ملف JSON."""
    try:
        trades = []
        if os.path.exists(_TRADE_LOG_FILE):
            with open(_TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
        trades.append(trade)
        with open(_TRADE_LOG_FILE, "w") as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        log.warning(f"💸 [BybitTrader] save log err: {e}")


def execute_trade(signal: Dict) -> bool:
    """🆕 v6.4.119: ينفذ صفقة شراء + أهداف + ستوب على Bybit Testnet.

    لا يرسل أي تنبيه للقنوات أو البوت — فقط يسجل في log + ملف JSON.

    Args:
        signal: dict فيه symbol, entry, entry_low, entry_high, sl, tp1, tp2, tp3
    Returns:
        True لو نجح الشراء، False لو فشل
    """
    if not _AVAILABLE:
        return False

    try:
        symbol = signal.get("symbol", "")
        if not symbol:
            return False

        bybit_symbol = _format_symbol(symbol)
        entry_price = signal.get("entry", 0) or signal.get("entry_high", 0)
        sl_price = signal.get("sl", 0)
        tp1_price = signal.get("tp1", 0)
        tp2_price = signal.get("tp2", 0)
        tp3_price = signal.get("tp3", 0)

        if entry_price <= 0 or sl_price <= 0 or tp1_price <= 0:
            log.warning(f"💸 [BybitTrader] {symbol} — أسعار ناقصة")
            return False

        # 1) معلومات العملة
        sym_info = _get_symbol_info(bybit_symbol)
        if not sym_info:
            log.warning(f"💸 [BybitTrader] {symbol} — غير متاح على Bybit Testnet")
            return False

        # 2) حساب الكمية (مبلغ / سعر الدخول)
        amount = _TRADE_AMOUNT
        qty = amount / entry_price
        qty = _round_qty(qty, sym_info["step_size"])
        if qty < sym_info["min_qty"]:
            log.warning(f"💸 [BybitTrader] {symbol} — qty {qty} < min {sym_info['min_qty']}")
            return False

        # 3) شراء سوقي
        buy_order_id = _place_market_buy(bybit_symbol, qty)
        if not buy_order_id:
            log.warning(f"💸 [BybitTrader] {symbol} — فشل الشراء")
            return False

        # 4) ضع أوامر البيع (TP1, TP2, TP3, SL)
        # نقسّم الكمية: 40% TP1, 30% TP2, 20% TP3, 10% SL
        qty_tp1 = _round_qty(qty * 0.40, sym_info["step_size"])
        qty_tp2 = _round_qty(qty * 0.30, sym_info["step_size"])
        qty_tp3 = _round_qty(qty * 0.20, sym_info["step_size"])
        qty_sl = _round_qty(qty * 0.10, sym_info["step_size"])

        sell_orders = []
        if tp1_price > 0 and qty_tp1 > 0:
            oid = _place_limit_sell(bybit_symbol, qty_tp1, tp1_price)
            if oid:
                sell_orders.append({"type": "TP1", "price": tp1_price, "qty": qty_tp1, "order_id": oid})

        if tp2_price > 0 and qty_tp2 > 0:
            oid = _place_limit_sell(bybit_symbol, qty_tp2, tp2_price)
            if oid:
                sell_orders.append({"type": "TP2", "price": tp2_price, "qty": qty_tp2, "order_id": oid})

        if tp3_price > 0 and qty_tp3 > 0:
            oid = _place_limit_sell(bybit_symbol, qty_tp3, tp3_price)
            if oid:
                sell_orders.append({"type": "TP3", "price": tp3_price, "qty": qty_tp3, "order_id": oid})

        if sl_price > 0 and qty_sl > 0:
            oid = _place_limit_sell(bybit_symbol, qty_sl, sl_price)
            if oid:
                sell_orders.append({"type": "SL", "price": sl_price, "qty": qty_sl, "order_id": oid})

        # 5) سجل
        trade_record = {
            "timestamp": int(time.time()),
            "symbol": symbol,
            "bybit_symbol": bybit_symbol,
            "buy_order_id": buy_order_id,
            "buy_price": entry_price,
            "buy_qty": qty,
            "amount_usd": amount,
            "sell_orders": sell_orders,
            "strategy": signal.get("strategy", "v1"),
            "sl": sl_price,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "tp3": tp3_price,
        }
        _save_trade_log(trade_record)

        log.info(f"💸 [BybitTrader] ✅ {symbol} — شراء {qty} @ ~${entry_price:.4f} + {len(sell_orders)} أوامر بيع")
        return True

    except Exception as e:
        log.warning(f"💸 [BybitTrader] execute err: {e}")
        return False


def get_trade_stats() -> Dict:
    """🆕 v6.4.119: يجلب إحصائيات الصفقات التجريبية."""
    try:
        if not os.path.exists(_TRADE_LOG_FILE):
            return {"total": 0, "total_amount": 0}
        with open(_TRADE_LOG_FILE, "r") as f:
            trades = json.load(f)
        total = len(trades)
        total_amount = sum(t.get("amount_usd", 0) for t in trades)
        return {
            "total": total,
            "total_amount": total_amount,
            "remaining_budget": max(0, _WALLET_DIVISION * _TRADE_AMOUNT - total_amount),
        }
    except Exception:
        return {"total": 0, "total_amount": 0, "remaining_budget": 0}
