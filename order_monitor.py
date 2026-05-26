"""
Order Monitor — Real Grid Logic for Binance Testnet / Real Binance
==================================================================

Normal mode:
  - Polls Binance every POLL_INTERVAL seconds
  - Detects filled orders (disappeared from open orders)
  - Rebalances grid according to exact rules:
      SELL filled → new BUY at nearest_buy + buy_after_sell%, rebuild all BUYs,
                    new SELL at top + sell_step%
      BUY  filled → new SELL at nearest_buy + sell_after_buy%, rebuild all SELLs,
                    new BUY at bottom - buy_step%
  - Always keeps exactly 5 BUY and 5 SELL orders open

Crisis mode (Gemini):
  - Triggered when price goes BELOW lowest BUY or ABOVE highest SELL
  - Gemini gets full market context + current grid state
  - Gemini decides what orders to cancel/place
  - Gemini decides when crisis is over → returns to normal grid logic
  - All offsets respect the speed multiplier

Speed multiplier divides ALL offsets:
  x1 = base, x2 = all steps /2, x4 = all steps /4, x0.5 = all steps *2
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Base offsets (%) ──────────────────────────────────────────────────────────
BASE_CENTER_OFFSET  = 0.35
BASE_BUY_STEP       = 0.15
BASE_SELL_STEP      = 0.19
BASE_BUY_AFTER_SELL = 0.17
BASE_SELL_AFTER_BUY = 0.53

GRID_SIZE      = 5
POLL_INTERVAL  = 8    # seconds between Binance polls (normal mode)
CRISIS_INTERVAL = 20  # seconds between Gemini checks during crisis
HISTORY_FILE   = "grid_history.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _p(pct: float) -> float:
    """Percent → decimal multiplier."""
    return pct / 100.0


def scaled(base_pct: float, speed: float) -> float:
    """Scale a base offset by speed multiplier."""
    return base_pct / max(speed, 0.01)


# ── Gemini client ─────────────────────────────────────────────────────────────

def gemini_ask(prompt: str) -> str:
    """Send prompt to Gemini, return text response."""
    if not GEMINI_API_KEY:
        logger.warning("[Gemini] No API key — crisis mode disabled")
        return ""
    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        data = resp.json()
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    except Exception as e:
        logger.error(f"[Gemini] Request failed: {e}")
        return ""


# ── Grid state (in-memory, per bot) ──────────────────────────────────────────

class GridBook:
    """
    Tracks which exchange order IDs are our BUY/SELL grid orders.
    Maps exchange_order_id → side + price.
    """

    def __init__(self):
        # {exchange_order_id: {"side": "BUY"/"SELL", "price": float}}
        self.orders: dict[str, dict] = {}

    def add(self, exchange_id: str, side: str, price: float):
        self.orders[exchange_id] = {"side": side, "price": price}

    def remove(self, exchange_id: str):
        self.orders.pop(exchange_id, None)

    def clear(self):
        self.orders.clear()

    def buys(self) -> list[dict]:
        """All BUY orders sorted desc by price (nearest to market first)."""
        return sorted(
            [{"id": k, **v} for k, v in self.orders.items() if v["side"] == "BUY"],
            key=lambda x: x["price"], reverse=True
        )

    def sells(self) -> list[dict]:
        """All SELL orders sorted asc by price (nearest to market first)."""
        return sorted(
            [{"id": k, **v} for k, v in self.orders.items() if v["side"] == "SELL"],
            key=lambda x: x["price"]
        )

    def lowest_buy(self) -> Optional[float]:
        b = self.buys()
        return b[-1]["price"] if b else None

    def highest_sell(self) -> Optional[float]:
        s = self.sells()
        return s[-1]["price"] if s else None

    def nearest_buy(self) -> Optional[dict]:
        b = self.buys()
        return b[0] if b else None

    def summary(self) -> str:
        buys  = [f"${o['price']:.2f}" for o in self.buys()]
        sells = [f"${o['price']:.2f}" for o in self.sells()]
        return f"BUY: {buys}\nSELL: {sells}"


# ── Order monitor ─────────────────────────────────────────────────────────────

class OrderMonitor:

    def __init__(self, db, get_binance_client_func, notify_callback=None):
        """
        db                    — DatabaseManager
        get_binance_client_func(bot, uid) → BinanceTestnetClient | MockBinanceClient
        notify_callback       — async fn(bot_id, text) for Telegram notifications
        """
        self.db         = db
        self.get_client = get_binance_client_func
        self.notify     = notify_callback

        self._tasks:  dict[int, asyncio.Task] = {}
        self._books:  dict[int, GridBook]     = {}
        self._crisis: dict[int, bool]         = {}   # bot_id → in_crisis
        self._uid:    dict[int, int]          = {}   # bot_id → telegram user id

    # ── Public API ────────────────────────────────────────────────────────

    async def start_monitoring(self, bot_id: int, bot: dict, uid: int):
        if bot_id in self._tasks:
            return
        self._uid[bot_id]    = uid
        self._books[bot_id]  = GridBook()
        self._crisis[bot_id] = False
        task = asyncio.create_task(self._main_loop(bot_id))
        self._tasks[bot_id] = task
        logger.info(f"[Monitor {bot_id}] Started")

    async def stop_monitoring(self, bot_id: int):
        task = self._tasks.pop(bot_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._books.pop(bot_id, None)
        self._crisis.pop(bot_id, None)
        logger.info(f"[Monitor {bot_id}] Stopped")

    async def stop_all(self):
        for bot_id in list(self._tasks.keys()):
            await self.stop_monitoring(bot_id)

    # ── Main loop ─────────────────────────────────────────────────────────

    async def _main_loop(self, bot_id: int):
        # First: build initial grid
        try:
            bot    = await self.db.get_bot(bot_id)
            uid    = self._uid[bot_id]
            client = self.get_client(bot, uid)
            await self._build_initial_grid(bot_id, bot, client)
        except Exception as e:
            logger.error(f"[Monitor {bot_id}] Initial grid failed: {e}", exc_info=True)

        while True:
            try:
                bot = await self.db.get_bot(bot_id)
                if not bot or bot.get("status") != "running":
                    break

                mode = bot.get("mode", "simulator")
                if mode == "simulator":
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                uid    = self._uid.get(bot_id, 0)
                client = self.get_client(bot, uid)
                speed  = float(bot.get("grid_speed") or 1.0)

                if self._crisis.get(bot_id):
                    await self._crisis_loop(bot_id, bot, client, speed)
                else:
                    await self._normal_poll(bot_id, bot, client, speed)
                    await asyncio.sleep(POLL_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Monitor {bot_id}] Loop error: {e}", exc_info=True)
                await asyncio.sleep(10)

    # ── Initial grid placement ────────────────────────────────────────────

    async def _build_initial_grid(self, bot_id: int, bot: dict, client):
        """Place N BUY + N SELL orders on Binance from center price (N = grid_levels)."""
        speed      = float(bot.get("grid_speed") or 1.0)
        grid_size  = int(bot.get("grid_levels") or GRID_SIZE)
        symbol     = bot.get("symbol", "BTCUSDT")
        order_usdt = float(bot.get("order_usdt") or 50)
        center     = bot.get("center_price") or client.get_current_price(symbol)

        co   = scaled(BASE_CENTER_OFFSET,  speed)
        bs   = scaled(BASE_BUY_STEP,       speed)
        ss   = scaled(BASE_SELL_STEP,      speed)

        qty = round(order_usdt / center, 6)
        qty = max(qty, 0.001)

        book = self._books[bot_id]
        book.clear()

        # Cancel all existing orders first
        try:
            client.cancel_all_orders(symbol)
        except Exception:
            pass

        first_buy  = center * (1 - _p(co))
        first_sell = center * (1 + _p(co))

        logger.info(
            f"[Monitor {bot_id}] Building initial grid. "
            f"Center=${center:.2f} Speed=x{speed} Levels={grid_size} "
            f"CO={co:.4f}% BS={bs:.4f}% SS={ss:.4f}%"
        )

        # Place BUY orders
        for i in range(grid_size):
            price = first_buy * (1 - _p(bs)) ** i
            price = round(price, 1)
            r = client.place_limit_buy(symbol, price, qty)
            eid = str(r.get("orderId", "")) if r else ""
            if eid:
                book.add(eid, "BUY", price)
                await self.db.add_order(bot_id, "BUY", price, qty, eid)

        # Place SELL orders
        for i in range(grid_size):
            price = first_sell * (1 + _p(ss)) ** i
            price = round(price, 1)
            r = client.place_limit_sell(symbol, price, qty)
            eid = str(r.get("orderId", "")) if r else ""
            if eid:
                book.add(eid, "SELL", price)
                await self.db.add_order(bot_id, "SELL", price, qty, eid)

        logger.info(f"[Monitor {bot_id}] Initial grid:\n{book.summary()}")
        await self._notify(bot_id, f"✅ Сетка выставлена\n{self._grid_text(book)}")

    # ── Normal poll ───────────────────────────────────────────────────────

    async def _normal_poll(self, bot_id: int, bot: dict, client, speed: float):
        """Check for filled orders and rebalance. Also check for crisis trigger."""
        symbol = bot.get("symbol", "BTCUSDT")
        book   = self._books[bot_id]

        # Current price
        price = client.get_current_price(symbol)
        if not price:
            return

        # ── Crisis trigger: price outside grid bounds ──
        lowest_buy   = book.lowest_buy()
        highest_sell = book.highest_sell()

        if lowest_buy and price < lowest_buy:
            logger.warning(
                f"[Monitor {bot_id}] CRISIS: price ${price:.2f} below lowest BUY ${lowest_buy:.2f}"
            )
            self._crisis[bot_id] = True
            await self._notify(
                bot_id,
                f"⚠️ <b>Кризис!</b> Цена ${price:,.2f} упала ниже нижнего BUY ${lowest_buy:,.2f}\n"
                f"🤖 Gemini берёт управление..."
            )
            return

        if highest_sell and price > highest_sell:
            logger.warning(
                f"[Monitor {bot_id}] CRISIS: price ${price:.2f} above highest SELL ${highest_sell:.2f}"
            )
            self._crisis[bot_id] = True
            await self._notify(
                bot_id,
                f"⚠️ <b>Кризис!</b> Цена ${price:,.2f} выросла выше верхнего SELL ${highest_sell:,.2f}\n"
                f"🤖 Gemini берёт управление..."
            )
            return

        # ── Check filled orders ──
        live = client.get_open_orders(symbol)
        live_ids = {str(o.get("orderId", "")) for o in live}
        our_ids  = set(book.orders.keys())
        filled_ids = our_ids - live_ids

        if not filled_ids:
            return

        order_usdt = float(bot.get("order_usdt") or 50)

        for eid in filled_ids:
            info = book.orders.get(eid)
            if not info:
                continue
            side  = info["side"]
            fprice = info["price"]
            book.remove(eid)

            logger.info(f"[Monitor {bot_id}] {side} FILLED @ ${fprice:.2f}")

            if side == "SELL":
                await self._after_sell_filled(bot_id, bot, client, speed, fprice, order_usdt)
            else:
                await self._after_buy_filled(bot_id, bot, client, speed, fprice, order_usdt)

            # Record trade in DB
            await self._record_trade(bot_id, side, fprice, price, order_usdt)
            await self._notify(
                bot_id,
                f"{'📤' if side == 'SELL' else '📥'} <b>{side} исполнен</b> @ ${fprice:,.2f}\n"
                f"Сетка перестроена ✅"
            )

    # ── Rebalance: SELL filled ────────────────────────────────────────────

    async def _after_sell_filled(self, bot_id, bot, client, speed, filled_price, order_usdt):
        """
        SELL filled:
        1. New BUY at nearest_buy + buy_after_sell% above
        2. Rebuild all BUYs from new_buy downward with buy_step
        3. New SELL at top_sell + sell_step%
        4. Remove overflow BUYs (>5), save to history
        """
        symbol = bot.get("symbol", "BTCUSDT")
        book   = self._books[bot_id]
        grid_size = int(bot.get("grid_levels") or GRID_SIZE)

        bas = scaled(BASE_BUY_AFTER_SELL, speed)
        bs  = scaled(BASE_BUY_STEP,       speed)
        ss  = scaled(BASE_SELL_STEP,      speed)

        current_price = client.get_current_price(symbol)
        qty = max(round(order_usdt / current_price, 6), 0.001)

        # 1. New BUY above nearest buy
        nb = book.nearest_buy()
        new_buy_price = (
            round(nb["price"] * (1 + _p(bas)), 1) if nb
            else round(filled_price * (1 - _p(bas)), 1)
        )

        # 2. Rebuild all BUYs
        #    Cancel existing buys, place fresh set from new_buy_price downward
        for o in book.buys():
            try:
                client.cancel_order(symbol, int(o["id"]))
            except Exception:
                pass
            book.remove(o["id"])

        new_buys = []
        for i in range(grid_size + 1):   # +1 so we can detect overflow
            price = round(new_buy_price * (1 - _p(bs)) ** i, 1)
            new_buys.append(price)

        overflow_buys = new_buys[grid_size:]
        active_buys   = new_buys[:grid_size]

        for price in active_buys:
            r = client.place_limit_buy(symbol, price, qty)
            eid = str(r.get("orderId", "")) if r else ""
            if eid:
                book.add(eid, "BUY", price)
                await self.db.add_order(bot_id, "BUY", price, qty, eid)

        self._save_overflow(bot_id, "BUY", overflow_buys, "sell_filled")

        # 3. New SELL at top
        sells = book.sells()
        top_price = (
            round(sells[-1]["price"] * (1 + _p(ss)), 1) if sells
            else round(filled_price * (1 + _p(ss)), 1)
        )
        r = client.place_limit_sell(symbol, top_price, qty)
        eid = str(r.get("orderId", "")) if r else ""
        if eid:
            book.add(eid, "SELL", top_price)
            await self.db.add_order(bot_id, "SELL", top_price, qty, eid)

        logger.info(f"[Monitor {bot_id}] After SELL fill:\n{book.summary()}")

    # ── Rebalance: BUY filled ─────────────────────────────────────────────

    async def _after_buy_filled(self, bot_id, bot, client, speed, filled_price, order_usdt):
        """
        BUY filled:
        1. New SELL at nearest_buy + sell_after_buy% above
        2. Rebuild all SELLs from new_sell upward with sell_step
        3. New BUY at bottom_buy - buy_step%
        4. Remove overflow SELLs (>5), save to history
        """
        symbol = bot.get("symbol", "BTCUSDT")
        book   = self._books[bot_id]
        grid_size = int(bot.get("grid_levels") or GRID_SIZE)

        sab = scaled(BASE_SELL_AFTER_BUY, speed)
        ss  = scaled(BASE_SELL_STEP,      speed)
        bs  = scaled(BASE_BUY_STEP,       speed)

        current_price = client.get_current_price(symbol)
        qty = max(round(order_usdt / current_price, 6), 0.001)

        # 1. New SELL above nearest buy
        nb = book.nearest_buy()
        new_sell_price = (
            round(nb["price"] * (1 + _p(sab)), 1) if nb
            else round(filled_price * (1 + _p(sab)), 1)
        )

        # 2. Rebuild all SELLs
        for o in book.sells():
            try:
                client.cancel_order(symbol, int(o["id"]))
            except Exception:
                pass
            book.remove(o["id"])

        new_sells = []
        for i in range(grid_size + 1):
            price = round(new_sell_price * (1 + _p(ss)) ** i, 1)
            new_sells.append(price)

        overflow_sells = new_sells[grid_size:]
        active_sells   = new_sells[:grid_size]

        for price in active_sells:
            r = client.place_limit_sell(symbol, price, qty)
            eid = str(r.get("orderId", "")) if r else ""
            if eid:
                book.add(eid, "SELL", price)
                await self.db.add_order(bot_id, "SELL", price, qty, eid)

        self._save_overflow(bot_id, "SELL", overflow_sells, "buy_filled")

        # 3. New BUY at bottom
        buys = book.buys()
        bottom_price = (
            round(buys[-1]["price"] * (1 - _p(bs)), 1) if buys
            else round(filled_price * (1 - _p(bs)), 1)
        )
        r = client.place_limit_buy(symbol, bottom_price, qty)
        eid = str(r.get("orderId", "")) if r else ""
        if eid:
            book.add(eid, "BUY", bottom_price)
            await self.db.add_order(bot_id, "BUY", bottom_price, qty, eid)

        logger.info(f"[Monitor {bot_id}] After BUY fill:\n{book.summary()}")

    # ── Crisis mode (Gemini) ──────────────────────────────────────────────

    async def _crisis_loop(self, bot_id: int, bot: dict, client, speed: float):
        """
        Gemini monitors the market, places/cancels orders.
        Exits when Gemini says crisis is over.
        """
        symbol = bot.get("symbol", "BTCUSDT")
        book   = self._books[bot_id]

        price = client.get_current_price(symbol)
        live  = client.get_open_orders(symbol)

        # Build context for Gemini
        prompt = f"""You are managing a BTC grid trading bot in CRISIS mode.
The price has moved outside the grid boundaries.

Current market situation:
- Symbol: {symbol}
- Current price: ${price:,.2f}
- Speed multiplier: x{speed} (all grid steps are divided by this)

Current open orders on exchange:
{json.dumps([{"side": o.get("side"), "price": float(o.get("price",0)), "qty": float(o.get("origQty",0))} for o in live], indent=2)}

Our tracked grid:
{book.summary()}

Grid parameters (already scaled by speed x{speed}):
- BUY step between orders: {scaled(BASE_BUY_STEP, speed):.4f}%
- SELL step between orders: {scaled(BASE_SELL_STEP, speed):.4f}%
- BUY after SELL fill offset: {scaled(BASE_BUY_AFTER_SELL, speed):.4f}%
- SELL after BUY fill offset: {scaled(BASE_SELL_AFTER_BUY, speed):.4f}%
- Orders per side: {GRID_SIZE}

Your job:
1. Analyze if the situation is still dangerous or stabilizing
2. If dangerous: decide which orders to cancel and where to place new ones
3. If stable: declare crisis over so normal grid logic resumes

Respond with ONLY valid JSON, no markdown, no explanation:
{{
  "crisis_over": true or false,
  "reason": "brief explanation in English",
  "cancel_all": true or false,
  "new_grid_center": <price as number or null>,
  "buy_orders": [<list of prices to place BUY limit orders>],
  "sell_orders": [<list of prices to place SELL limit orders>]
}}

Rules:
- If crisis_over is true, set new_grid_center to the price you want the new grid centered at
- If crisis_over is false, provide the orders you want placed right now
- buy_orders and sell_orders can be empty lists if no new orders needed yet
- Maximum {GRID_SIZE} buy and {GRID_SIZE} sell orders
- All prices must be realistic given current price ${price:,.2f}
"""

        logger.info(f"[Monitor {bot_id}] Asking Gemini (crisis)...")
        raw = await asyncio.get_event_loop().run_in_executor(None, gemini_ask, prompt)
        logger.info(f"[Monitor {bot_id}] Gemini response: {raw[:300]}")

        if not raw:
            await asyncio.sleep(CRISIS_INTERVAL)
            return

        # Parse Gemini JSON
        try:
            # Strip any accidental markdown
            clean = re.sub(r"```[a-z]*", "", raw).strip().strip("`").strip()
            decision = json.loads(clean)
        except Exception as e:
            logger.error(f"[Monitor {bot_id}] Gemini JSON parse error: {e} | raw: {raw[:200]}")
            await asyncio.sleep(CRISIS_INTERVAL)
            return

        order_usdt = float(bot.get("order_usdt") or 50)
        qty = max(round(order_usdt / price, 6), 0.001)

        # Cancel all if Gemini says so
        if decision.get("cancel_all"):
            try:
                client.cancel_all_orders(symbol)
                book.clear()
                logger.info(f"[Monitor {bot_id}] Gemini: cancelled all orders")
            except Exception as e:
                logger.error(f"[Monitor {bot_id}] cancel_all error: {e}")

        # Place orders Gemini decided on
        for bp in decision.get("buy_orders", []):
            try:
                r = client.place_limit_buy(symbol, round(float(bp), 1), qty)
                eid = str(r.get("orderId", "")) if r else ""
                if eid:
                    book.add(eid, "BUY", float(bp))
                    await self.db.add_order(bot_id, "BUY", float(bp), qty, eid)
            except Exception as e:
                logger.error(f"[Monitor {bot_id}] Gemini BUY place error: {e}")

        for sp in decision.get("sell_orders", []):
            try:
                r = client.place_limit_sell(symbol, round(float(sp), 1), qty)
                eid = str(r.get("orderId", "")) if r else ""
                if eid:
                    book.add(eid, "SELL", float(sp))
                    await self.db.add_order(bot_id, "SELL", float(sp), qty, eid)
            except Exception as e:
                logger.error(f"[Monitor {bot_id}] Gemini SELL place error: {e}")

        reason = decision.get("reason", "")
        await self._notify(
            bot_id,
            f"🤖 <b>Gemini:</b> {reason}\n"
            f"{'✅ Кризис завершён — возврат к сетке' if decision.get('crisis_over') else '⚠️ Кризис продолжается...'}"
        )

        # Crisis over — rebuild normal grid from Gemini's chosen center
        if decision.get("crisis_over"):
            new_center = decision.get("new_grid_center") or price
            logger.info(
                f"[Monitor {bot_id}] Gemini declared crisis over. "
                f"Rebuilding grid from ${new_center:.2f}"
            )
            self._crisis[bot_id] = False
            await self.db.update_bot(bot_id, center_price=new_center)
            # Rebuild fresh grid
            bot["center_price"] = new_center
            client.cancel_all_orders(symbol)
            book.clear()
            await self.db.connection.execute(
                "DELETE FROM orders WHERE bot_id=? AND status='OPEN'", (bot_id,)
            )
            await self.db.connection.commit()
            await self._build_initial_grid(bot_id, bot, client)
        else:
            await asyncio.sleep(CRISIS_INTERVAL)

    # ── Trade recording ───────────────────────────────────────────────────

    async def _record_trade(self, bot_id: int, side: str,
                            filled_price: float, market_price: float,
                            order_usdt: float):
        try:
            qty = order_usdt / filled_price
            if side == "SELL":
                buy_p  = filled_price * (1 - _p(scaled(BASE_BUY_AFTER_SELL, 1.0)))
                sell_p = filled_price
            else:
                buy_p  = filled_price
                sell_p = filled_price * (1 + _p(scaled(BASE_SELL_AFTER_BUY, 1.0)))

            profit_pct  = (sell_p - buy_p) / buy_p * 100
            profit_usdt = (sell_p - buy_p) * qty
            now = datetime.now().isoformat()

            await self.db.connection.execute(
                """INSERT INTO sim_trades
                   (bot_id, buy_order_id, sell_order_id, buy_price, sell_price,
                    quantity, profit, profit_percent, executed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (bot_id,
                 f"BUY_{bot_id}_{int(time.time())}",
                 f"SELL_{bot_id}_{int(time.time())}",
                 round(buy_p, 2), round(sell_p, 2),
                 round(qty, 6),
                 round(profit_usdt, 4),
                 round(profit_pct, 4),
                 now)
            )
            await self.db.connection.commit()

            bot = await self.db.get_bot(bot_id)
            new_bal = (bot.get("balance") or 0) + profit_usdt
            await self.db.update_bot(bot_id, balance=new_bal)
        except Exception as e:
            logger.error(f"[Monitor {bot_id}] record_trade error: {e}")

    # ── Overflow history ──────────────────────────────────────────────────

    def _save_overflow(self, bot_id: int, side: str,
                       prices: list[float], reason: str):
        if not prices:
            return
        try:
            history = []
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            for p in prices:
                entry = {
                    "bot_id": bot_id, "side": side,
                    "price": p, "reason": reason,
                    "removed_at": datetime.now().isoformat(),
                }
                history.append(entry)
                logger.info(
                    f"[Monitor {bot_id}] ORDER REMOVED FROM GRID — "
                    f"side={side} price=${p:.2f} reason={reason} — saved to history"
                )
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Monitor {bot_id}] save_overflow error: {e}")

    # ── Notifications ─────────────────────────────────────────────────────

    async def _notify(self, bot_id: int, text: str):
        if self.notify:
            try:
                await self.notify(bot_id, text)
            except Exception as e:
                logger.error(f"[Monitor {bot_id}] notify error: {e}")

    # ── Display helpers ───────────────────────────────────────────────────

    @staticmethod
    def _grid_text(book: GridBook) -> str:
        lines = []
        for o in reversed(book.sells()):
            lines.append(f"  📤 SELL ${o['price']:,.1f}")
        lines.append("  ── market ──")
        for o in book.buys():
            lines.append(f"  📥 BUY  ${o['price']:,.1f}")
        return "\n".join(lines)