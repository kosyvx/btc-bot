"""
Binance Futures Testnet client.
URL: https://testnet.binancefuture.com
Ключи: testnet.binancefuture.com → API Management
"""
import hashlib
import hmac
import time
import logging
import requests
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

BASE = "https://testnet.binancefuture.com"


class BinanceTestnetClient:

    def __init__(self, api_key: str, secret_key: str):
        self.api_key    = api_key.strip()
        self.secret_key = secret_key.strip()
        self.session    = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    # ── подпись ──────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> str:
        qs = urlencode(params)
        return hmac.new(self.secret_key.encode(), qs.encode(), hashlib.sha256).hexdigest()

    def _server_time_offset(self) -> int:
        """Получаем разницу между временем сервера Binance и локальным временем."""
        try:
            r = self.session.get(f"{BASE}/fapi/v1/time", timeout=5)
            server_ms = r.json()["serverTime"]
            local_ms  = int(time.time() * 1000)
            return server_ms - local_ms
        except Exception:
            return 0

    def _ts(self) -> int:
        """Метка времени синхронизированная с сервером Binance."""
        if not hasattr(self, "_time_offset"):
            self._time_offset = self._server_time_offset()
        return int(time.time() * 1000) + self._time_offset

    # ── http ─────────────────────────────────────────────────────────────

    def _get(self, path, params=None, signed=False):
        p = dict(params or {})
        if signed:
            p["timestamp"] = self._ts()
            p["signature"] = self._sign(p)
        try:
            r = self.session.get(f"{BASE}{path}", params=p, timeout=10)
            if not r.ok:
                logger.error(f"GET {path} {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            logger.error(f"GET {path}: {e}")
            return None

    def _post(self, path, params=None):
        p = dict(params or {})
        p["timestamp"] = self._ts()
        p["signature"] = self._sign(p)
        try:
            r = self.session.post(f"{BASE}{path}", params=p, timeout=10)
            if not r.ok:
                logger.error(f"POST {path} {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            logger.error(f"POST {path}: {e}")
            return None

    def _delete(self, path, params=None):
        p = dict(params or {})
        p["timestamp"] = self._ts()
        p["signature"] = self._sign(p)
        try:
            r = self.session.delete(f"{BASE}{path}", params=p, timeout=10)
            if not r.ok:
                logger.error(f"DELETE {path} {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            logger.error(f"DELETE {path}: {e}")
            return None

    # ── публичные ────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return self._get("/fapi/v1/ping") is not None

    def get_current_price(self, symbol="BTCUSDT") -> float:
        d = self._get("/fapi/v1/ticker/price", {"symbol": symbol})
        return float(d["price"]) if d else 0.0

    def get_usdt_balance(self) -> float:
        d = self._get("/fapi/v2/balance", signed=True)
        if not d:
            return 0.0
        for a in d:
            if a.get("asset") == "USDT":
                return float(a.get("balance", 0))
        return 0.0

    def get_balance(self) -> list:
        d = self._get("/fapi/v2/balance", signed=True)
        return [a for a in (d or []) if float(a.get("balance", 0)) > 0]

    def get_open_orders(self, symbol="BTCUSDT") -> list:
        d = self._get("/fapi/v1/openOrders", {"symbol": symbol}, signed=True)
        return d if d else []

    def get_all_orders(self, symbol="BTCUSDT", limit=20) -> list:
        d = self._get("/fapi/v1/allOrders", {"symbol": symbol, "limit": limit}, signed=True)
        return d if d else []

    def place_limit_buy(self, symbol: str, price: float, quantity: float) -> dict:
        """BUY лимит. One-Way mode — работает на testnet по умолчанию."""
        params = {
            "symbol":      symbol,
            "side":        "BUY",
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    f"{quantity:.3f}",
            "price":       f"{price:.1f}",
        }
        r = self._post("/fapi/v1/order", params)
        if r and r.get("orderId"):
            logger.info(f"[Binance] ✅ BUY {quantity:.3f} @ ${price:.1f}  orderId={r['orderId']}")
        else:
            logger.error(f"[Binance] ❌ BUY FAILED @ ${price:.1f}  ответ={r}")
        return r or {}

    def place_limit_sell(self, symbol: str, price: float, quantity: float) -> dict:
        """SELL лимит. One-Way mode."""
        params = {
            "symbol":      symbol,
            "side":        "SELL",
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    f"{quantity:.3f}",
            "price":       f"{price:.1f}",
        }
        r = self._post("/fapi/v1/order", params)
        if r and r.get("orderId"):
            logger.info(f"[Binance] ✅ SELL {quantity:.3f} @ ${price:.1f}  orderId={r['orderId']}")
        else:
            logger.error(f"[Binance] ❌ SELL FAILED @ ${price:.1f}  ответ={r}")
        return r or {}

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        r = self._delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
        if r:
            logger.info(f"[Binance] Отменён ордер {order_id}")
        return r or {}

    def cancel_all_orders(self, symbol="BTCUSDT"):
        r = self._delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
        logger.info(f"[Binance] Все ордера {symbol} отменены")
        return r or []

    def get_position(self, symbol="BTCUSDT") -> dict:
        d = self._get("/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
        return d[0] if d else {}


class MockBinanceClient:
    """Симулятор без ключей."""

    def __init__(self):
        self._price   = 105_000.0
        self._orders  = []
        self._counter = 1000

    def is_connected(self):                return True
    def get_usdt_balance(self):            return 10_000.0
    def get_balance(self):                 return [{"asset": "USDT", "balance": "10000"}]
    def get_position(self, s="BTCUSDT"):   return {"positionAmt": "0", "entryPrice": "0"}
    def cancel_all_orders(self, s="BTCUSDT"): return []

    def get_current_price(self, s="BTCUSDT") -> float:
        import random
        self._price += random.uniform(-80, 80)
        return round(self._price, 1)

    def get_open_orders(self, s="BTCUSDT"):
        return [o for o in self._orders if o["status"] == "NEW"]

    def get_all_orders(self, s="BTCUSDT", limit=20):
        return self._orders[-limit:]

    def _mk(self, s, side, price, qty):
        self._counter += 1
        o = {"orderId": self._counter, "symbol": s, "side": side,
             "type": "LIMIT", "price": str(price), "origQty": str(qty),
             "status": "NEW", "time": int(time.time()*1000)}
        self._orders.append(o)
        return o

    def place_limit_buy(self, s, price, qty):   return self._mk(s, "BUY",  price, qty)
    def place_limit_sell(self, s, price, qty):  return self._mk(s, "SELL", price, qty)

    def cancel_order(self, s, order_id):
        for o in self._orders:
            if o["orderId"] == order_id:
                o["status"] = "CANCELED"
        return {"orderId": order_id}