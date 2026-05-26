"""
grid_engine.py — симулятор грид-сетки для режима Simulator.
Имитирует исполнение BUY/SELL ордеров на основе случайного движения цены.
"""
import asyncio
import logging
import random
from datetime import datetime

logger = logging.getLogger(__name__)


class GridSimulator:
    """
    Запускает фоновую задачу для каждого бота в режиме симулятора.
    Каждые N секунд «двигает» цену и исполняет ордера.
    """

    def __init__(self, db, notify_callback=None):
        self.db = db
        self.notify_callback = notify_callback
        self._tasks: dict[int, asyncio.Task] = {}

    async def start(self, bot_id: int, center_price: float, speed: float = 1.0):
        """Запустить симуляцию для бота."""
        await self.stop(bot_id)
        self._tasks[bot_id] = asyncio.create_task(
            self._simulate(bot_id, center_price, speed)
        )
        logger.info(f"[GridSim] Бот {bot_id} запущен (center={center_price}, speed={speed})")

    async def stop(self, bot_id: int):
        """Остановить симуляцию для бота."""
        task = self._tasks.pop(bot_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"[GridSim] Бот {bot_id} остановлен")

    async def stop_all(self):
        """Остановить все симуляции."""
        for bot_id in list(self._tasks):
            await self.stop(bot_id)

    async def _simulate(self, bot_id: int, center_price: float, speed: float):
        """Основной цикл симуляции."""
        # Интервал: базово 30 сек, делим на speed
        interval = max(5.0, 30.0 / speed)
        price = center_price
        drift = 0.0

        while True:
            try:
                await asyncio.sleep(interval)

                bot = await self.db.get_bot(bot_id)
                if not bot or bot["status"] != "running":
                    break

                # Случайное движение цены (±0.3%)
                drift += random.uniform(-0.15, 0.15)
                drift = max(-2.0, min(2.0, drift))  # ограничиваем дрейф
                price_change = price * (random.uniform(-0.003, 0.003) + drift * 0.001)
                price = round(price + price_change, 2)

                # Получаем открытые ордера
                orders = await self.db.get_open_orders(bot_id)
                if not orders:
                    continue

                for order in orders:
                    o_price = float(order["price"])
                    side = order["side"]

                    # BUY исполняется когда цена падает до уровня
                    if side == "BUY" and price <= o_price:
                        await self._fill_order(bot_id, order, price, "buy_filled")

                    # SELL исполняется когда цена растёт до уровня
                    elif side == "SELL" and price >= o_price:
                        await self._fill_order(bot_id, order, price, "sell_filled")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[GridSim] Ошибка бота {bot_id}: {e}")
                await asyncio.sleep(10)

    async def _fill_order(self, bot_id: int, order: dict, fill_price: float, event_type: str):
        """Исполнить симулированный ордер и выставить встречный."""
        try:
            order_id = order["id"]
            side = order["side"]
            qty = float(order["quantity"])
            o_price = float(order["price"])
            pair_id = order.get("pair_id", "")

            # Обновляем статус ордера
            await self.db.update_order_status(order_id, "FILLED")

            bot = await self.db.get_bot(bot_id)
            step_usd = 10.0  # стандартный шаг сетки

            if side == "BUY":
                # BUY исполнен → создаём SELL выше
                sell_price = round(o_price + step_usd * 2, 2)
                await self.db.add_order(bot_id, "SELL", sell_price, qty, "", pair_id)
                logger.info(f"[GridSim] BUY ${o_price} → SELL ${sell_price}")

                event = {
                    "event": event_type,
                    "filled_price": fill_price,
                    "new_sell": {"price": sell_price},
                }

            else:
                # SELL исполнен → считаем прибыль и создаём BUY ниже
                buy_price = round(o_price - step_usd * 2, 2)
                profit = round((o_price - buy_price) * qty, 6)

                # Записываем прибыль в баланс
                try:
                    await self.db.connection.execute(
                        "UPDATE bots SET balance = balance + ? WHERE id = ?",
                        (profit, bot_id)
                    )
                    await self.db.connection.execute(
                        "INSERT INTO trades (bot_id, buy_price, sell_price, quantity, profit, executed_at)"
                        " VALUES (?,?,?,?,?,?)",
                        (bot_id, buy_price, o_price, qty, profit, datetime.now().isoformat())
                    )
                    await self.db.connection.commit()
                except Exception as e:
                    logger.error(f"[GridSim] Запись прибыли: {e}")

                await self.db.add_order(bot_id, "BUY", buy_price, qty, "", pair_id)
                logger.info(f"[GridSim] SELL ${o_price} → прибыль ${profit:.4f}, BUY ${buy_price}")

                event = {
                    "event": event_type,
                    "filled_price": fill_price,
                    "new_buy": {"price": buy_price},
                }

            # Уведомление в Telegram
            if self.notify_callback:
                await self.notify_callback(bot_id, event)

        except Exception as e:
            logger.error(f"[GridSim] _fill_order error: {e}")
