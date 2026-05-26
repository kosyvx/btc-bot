"""Database manager for SQLite."""
import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None

    async def update_order_status(self, order_id: int, status: str):
        """Update order status (OPEN/FILLED/CANCELED)."""
        await self.connection.execute(
            "UPDATE orders SET status=? WHERE id=?", (status, order_id)
        )
        await self.connection.commit()

    async def initialize(self):
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        await self._create_tables()
        await self._migrate()

    async def _migrate(self):
        """Add new columns to existing DB if they are missing."""
        migrations = [
            "ALTER TABLE bots ADD COLUMN mode TEXT DEFAULT 'simulator'",
            "ALTER TABLE bots ADD COLUMN order_usdt REAL DEFAULT 50",
            "ALTER TABLE bots ADD COLUMN theme TEXT DEFAULT 'dark'",
            "ALTER TABLE bots ADD COLUMN daily_report INTEGER DEFAULT 0",
            "ALTER TABLE bots ADD COLUMN grid_speed REAL DEFAULT 1.0",
            "ALTER TABLE bots ADD COLUMN grid_levels INTEGER DEFAULT 5",
            "ALTER TABLE bots ADD COLUMN ai_provider TEXT DEFAULT 'gemini'",
        ]
        for sql in migrations:
            try:
                await self.connection.execute(sql)
                await self.connection.commit()
            except Exception:
                pass

    async def _create_tables(self):
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                status TEXT DEFAULT 'stopped',
                symbol TEXT DEFAULT 'BTCUSDT',
                balance REAL DEFAULT 0,
                api_key TEXT DEFAULT '',
                secret_key TEXT DEFAULT '',
                center_price REAL,
                quantity REAL DEFAULT 0.001,
                mode TEXT DEFAULT 'simulator',
                order_usdt REAL DEFAULT 50,
                theme TEXT DEFAULT 'dark',
                daily_report INTEGER DEFAULT 0,
                grid_speed REAL DEFAULT 1.0,
                grid_levels INTEGER DEFAULT 5,
                ai_provider TEXT DEFAULT 'gemini',
                created_at TEXT NOT NULL
            )
        """)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                exchange_order_id TEXT,
                pair_id TEXT,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                status TEXT DEFAULT 'OPEN',
                created_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
        """)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                pair_name TEXT NOT NULL,
                buy_price REAL,
                sell_price REAL,
                quantity REAL,
                profit REAL DEFAULT 0,
                status TEXT DEFAULT 'OPEN',
                created_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
        """)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
        """)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS sim_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                buy_order_id TEXT,
                sell_order_id TEXT,
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                quantity REAL NOT NULL,
                profit REAL NOT NULL,
                profit_percent REAL NOT NULL,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
        """)
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                quantity REAL NOT NULL,
                profit REAL NOT NULL,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
        """)
        await self.connection.commit()

    async def close(self):
        if self.connection:
            await self.connection.close()

    # ─── BOTS ─────────────────────────────────────────────────────────────
    async def create_bot(self, name: str, symbol: str = "BTCUSDT") -> dict:
        now = datetime.now().isoformat()
        cur = await self.connection.execute(
            "INSERT INTO bots (name, symbol, created_at) VALUES (?,?,?)",
            (name, symbol, now)
        )
        await self.connection.commit()
        return await self.get_bot(cur.lastrowid)

    async def get_bot(self, bot_id: int) -> Optional[dict]:
        cur = await self.connection.execute(
            "SELECT * FROM bots WHERE id=?", (bot_id,)
        )
        row = await cur.fetchone()
        return self._bot_row(row) if row else None

    async def get_all_bots(self) -> List[dict]:
        cur = await self.connection.execute(
            "SELECT * FROM bots ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        return [self._bot_row(r) for r in rows]

    async def update_bot(self, bot_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [bot_id]
        await self.connection.execute(
            f"UPDATE bots SET {sets} WHERE id=?", vals
        )
        await self.connection.commit()

    async def delete_bot(self, bot_id: int):
        await self.connection.execute("DELETE FROM bots WHERE id=?", (bot_id,))
        await self.connection.commit()

    async def add_deposit(self, bot_id: int, amount: float):
        now = datetime.now().isoformat()
        await self.connection.execute(
            "INSERT INTO deposits (bot_id, amount, created_at) VALUES (?,?,?)",
            (bot_id, amount, now)
        )
        # Update bot balance
        bot = await self.get_bot(bot_id)
        new_balance = (bot["balance"] or 0) + amount
        await self.update_bot(bot_id, balance=new_balance)

    # ─── ORDERS ───────────────────────────────────────────────────────────
    async def add_order(self, bot_id: int, side: str, price: float,
                        quantity: float, exchange_id: str = "",
                        pair_id: str = "") -> dict:
        now = datetime.now().isoformat()
        cur = await self.connection.execute(
            """INSERT INTO orders
               (bot_id, exchange_order_id, pair_id, side, price, quantity, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (bot_id, exchange_id, pair_id, side, price, quantity, now)
        )
        await self.connection.commit()
        return {"id": cur.lastrowid, "side": side, "price": price,
                "quantity": quantity, "status": "OPEN"}

    async def get_bot_orders(self, bot_id: int) -> List[dict]:
        cur = await self.connection.execute(
            "SELECT * FROM orders WHERE bot_id=? ORDER BY created_at DESC",
            (bot_id,)
        )
        rows = await cur.fetchall()
        return [self._order_row(r) for r in rows]

    async def get_open_orders(self, bot_id: int) -> List[dict]:
        cur = await self.connection.execute(
            "SELECT * FROM orders WHERE bot_id=? AND status='OPEN' ORDER BY price DESC",
            (bot_id,)
        )
        rows = await cur.fetchall()
        return [self._order_row(r) for r in rows]

    async def update_order_status(self, order_id: int, status: str):
        """Update order status (e.g. OPEN -> FILLED)."""
        await self.connection.execute(
            "UPDATE orders SET status=? WHERE id=?",
            (status, order_id)
        )
        await self.connection.commit()

    # ─── PAIRS ────────────────────────────────────────────────────────────
    async def add_pair(self, bot_id: int, pair_name: str,
                       buy_price: float, sell_price: float,
                       quantity: float) -> dict:
        now = datetime.now().isoformat()
        cur = await self.connection.execute(
            """INSERT INTO pairs
               (bot_id, pair_name, buy_price, sell_price, quantity, created_at)
               VALUES (?,?,?,?,?,?)""",
            (bot_id, pair_name, buy_price, sell_price, quantity, now)
        )
        await self.connection.commit()
        return {"id": cur.lastrowid, "pair_name": pair_name,
                "buy_price": buy_price, "sell_price": sell_price}

    async def get_bot_pairs(self, bot_id: int) -> List[dict]:
        cur = await self.connection.execute(
            "SELECT * FROM pairs WHERE bot_id=? ORDER BY created_at DESC",
            (bot_id,)
        )
        rows = await cur.fetchall()
        return [self._pair_row(r) for r in rows]

    async def get_total_profit(self, bot_id: int) -> float:
        """Total profit from pairs (closed) + simulator trades."""
        cur = await self.connection.execute(
            "SELECT COALESCE(SUM(profit),0) FROM pairs WHERE bot_id=? AND status='CLOSED'",
            (bot_id,)
        )
        row = await cur.fetchone()
        pairs_profit = row[0] if row else 0.0

        cur2 = await self.connection.execute(
            "SELECT COALESCE(SUM(profit),0) FROM sim_trades WHERE bot_id=?",
            (bot_id,)
        )
        row2 = await cur2.fetchone()
        sim_profit = row2[0] if row2 else 0.0
        return pairs_profit + sim_profit


    async def reset_bot_stats(self, bot_id: int):
        """Полный сброс: ордера, пары, сделки. Баланс и настройки сохраняются."""
        await self.connection.execute("DELETE FROM orders WHERE bot_id=?", (bot_id,))
        await self.connection.execute("DELETE FROM pairs WHERE bot_id=?", (bot_id,))
        await self.connection.execute("DELETE FROM sim_trades WHERE bot_id=?", (bot_id,))
        await self.connection.execute("DELETE FROM trades WHERE bot_id=?", (bot_id,))
        await self.connection.execute(
            "UPDATE bots SET status='stopped', center_price=NULL WHERE id=?", (bot_id,)
        )
        await self.connection.commit()
    async def cancel_open_orders(self, bot_id: int):
        """Mark all OPEN orders as CANCELED (for rebalance)."""
        await self.connection.execute(
            "UPDATE orders SET status='CANCELED' WHERE bot_id=? AND status='OPEN'",
            (bot_id,)
        )
        await self.connection.commit()

    async def get_withdrawals_by_bot(self, bot_id: int) -> float:
        """Total withdrawals for a specific bot."""
        cur = await self.connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE bot_id=?",
            (bot_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0.0

    async def get_total_withdrawals(self, bot_id: int = None) -> float:
        """Total withdrawals globally or for a bot."""
        if bot_id:
            return await self.get_withdrawals_by_bot(bot_id)
        # Try withdrawals table first, fallback 0
        try:
            cur = await self.connection.execute(
                "SELECT COALESCE(SUM(amount),0) FROM withdrawals"
            )
            row = await cur.fetchone()
            return row[0] if row else 0.0
        except Exception:
            return 0.0


    # Alias used by simulator
    async def get_bot_by_id(self, bot_id: int):
        """Alias for get_bot — returns dict with is_running() helper."""
        row = await self.get_bot(bot_id)
        if row:
            # Attach is_running helper so simulator code works
            class _BotWrapper(dict):
                def is_running(self):
                    return self.get("status") == "running"
            return _BotWrapper(row)
        return None

    # ─── SIMULATOR TRADES ─────────────────────────────────────────────────
    async def create_trade(self, trade) -> object:
        """Save a simulated trade from TradingSimulator."""
        now = datetime.now().isoformat()
        executed = trade.executed_at.isoformat() if hasattr(trade.executed_at, 'isoformat') else now
        cur = await self.connection.execute(
            """INSERT INTO sim_trades
               (bot_id, buy_order_id, sell_order_id, buy_price, sell_price,
                quantity, profit, profit_percent, executed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (trade.bot_id, trade.buy_order_id, trade.sell_order_id,
             trade.buy_price, trade.sell_price, trade.quantity,
             trade.profit, trade.profit_percent, executed)
        )
        await self.connection.commit()
        trade.id = cur.lastrowid
        return trade

    async def get_trades(self, bot_id: int, limit: int = 50) -> list:
        """Реальные сделки (исполненные пары BUY→SELL)."""
        cur = await self.connection.execute(
            "SELECT * FROM trades WHERE bot_id=? ORDER BY executed_at DESC LIMIT ?",
            (bot_id, limit)
        )
        rows = await cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    async def get_filled_orders(self, bot_id: int, limit: int = 50) -> list:
        """Исполненные ордера."""
        cur = await self.connection.execute(
            "SELECT * FROM orders WHERE bot_id=? AND status='FILLED' ORDER BY created_at DESC LIMIT ?",
            (bot_id, limit)
        )
        rows = await cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    async def get_recent_trades(self, bot_id: int, limit: int = 5) -> list:
        """Get last N simulated trades for a bot."""
        cur = await self.connection.execute(
            """SELECT id, bot_id, buy_order_id, sell_order_id, buy_price, sell_price,
                      quantity, profit, profit_percent, executed_at
               FROM sim_trades WHERE bot_id=?
               ORDER BY executed_at DESC LIMIT ?""",
            (bot_id, limit)
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "bot_id": r[1], "buy_order_id": r[2],
                 "sell_order_id": r[3], "buy_price": r[4], "sell_price": r[5],
                 "quantity": r[6], "profit": r[7], "profit_percent": r[8],
                 "executed_at": r[9]} for r in rows]

    async def get_profit_since(self, bot_id: int, since) -> float:
        """Get simulated profit for a bot since a given datetime."""
        since_str = since.isoformat() if hasattr(since, 'isoformat') else str(since)
        cur = await self.connection.execute(
            """SELECT COALESCE(SUM(profit), 0) FROM sim_trades
               WHERE bot_id=? AND executed_at >= ?""",
            (bot_id, since_str)
        )
        row = await cur.fetchone()
        return row[0] if row else 0.0

    # ─── HELPERS ──────────────────────────────────────────────────────────
    def _bot_row(self, r) -> dict:
        keys = r.keys() if hasattr(r, "keys") else []
        def g(key, default=None):
            try:
                v = r[key]
                return v if v is not None else default
            except (IndexError, KeyError):
                return default
        return {
            "id": g("id"),
            "name": g("name", ""),
            "status": g("status", "stopped"),
            "symbol": g("symbol", "BTCUSDT"),
            "balance": g("balance", 0),
            "api_key": g("api_key", ""),
            "secret_key": g("secret_key", ""),
            "center_price": g("center_price"),
            "quantity": g("quantity", 0.001),
            "mode": g("mode", "simulator"),
            "order_usdt": g("order_usdt", 50),
            "theme": g("theme", "dark"),
            "daily_report": bool(g("daily_report", 0)),
            "grid_speed": float(g("grid_speed", 1.0)),
            "grid_levels": int(g("grid_levels", 5)),
            "ai_provider": g("ai_provider", "gemini"),
            "created_at": g("created_at", ""),
        }

    def _order_row(self, r) -> dict:
        def g(key, default=None):
            try:
                v = r[key]
                return v if v is not None else default
            except (IndexError, KeyError):
                return default
        return {
            "id": g("id"), "bot_id": g("bot_id"),
            "exchange_order_id": g("exchange_order_id", ""),
            "pair_id": g("pair_id", ""), "side": g("side", ""),
            "price": g("price", 0), "quantity": g("quantity", 0),
            "status": g("status", "OPEN"), "created_at": g("created_at", "")
        }

    def _pair_row(self, r) -> dict:
        def g(key, default=None):
            try:
                v = r[key]
                return v if v is not None else default
            except (IndexError, KeyError):
                return default
        return {
            "id": g("id"), "bot_id": g("bot_id"),
            "pair_name": g("pair_name", ""),
            "buy_price": g("buy_price", 0), "sell_price": g("sell_price", 0),
            "quantity": g("quantity", 0), "profit": g("profit", 0),
            "status": g("status", "OPEN"), "created_at": g("created_at", "")
        }