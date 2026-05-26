"""
BTC Trading Bot — полный ReplyKeyboard UI
Все функции: старт/стоп, пополнение, вывод, ордера, статистика,
AI анализ, AI чат, скорость, режим, API, тема, отчёт, клон, удаление, сброс.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import (
    BotCommand,
    Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

from database import DatabaseManager
from binance_client import BinanceTestnetClient, MockBinanceClient
from simulator.trading_simulator import TradingSimulator
from grid_engine import GridSimulator
from order_monitor import OrderMonitor
from ai_engine import analyse_and_rebalance, chat as ai_chat, chat, suggest_grid

load_dotenv()
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")

DATABASE_PATH   = os.getenv("DATABASE_PATH", "telegram_bot.db")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET  = os.getenv("BINANCE_SECRET_KEY", "")

MODE_SIMULATOR = "simulator"
MODE_TESTNET   = "testnet"
MODE_REAL      = "real"
MODE_LABELS    = {
    MODE_SIMULATOR: "🔵 Симулятор",
    MODE_TESTNET:   "🟡 Binance Testnet",
    MODE_REAL:      "🔴 Реальный Binance",
}
MODE_ICONS = {MODE_SIMULATOR: "🔵", MODE_TESTNET: "🟡", MODE_REAL: "🔴"}

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────

def kb_main():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🤖 Мои боты"),      KeyboardButton("➕ Добавить бота")],
        [KeyboardButton("📊 Общая статистика"), KeyboardButton("💰 Вывод средств")],
    ], resize_keyboard=True)

def kb_bot():
    return ReplyKeyboardMarkup([
        [KeyboardButton("▶️ Запустить"),  KeyboardButton("⏸ Остановить")],
        [KeyboardButton("💵 Пополнить"),  KeyboardButton("📊 Статистика")],
        [KeyboardButton("📌 Ордер"),      KeyboardButton("🤖 AI")],
        [KeyboardButton("📋 Данные"),     KeyboardButton("📜 Логи")],
        [KeyboardButton("⚙️ Настройки"), KeyboardButton("⬅️ Назад")],
    ], resize_keyboard=True)

def kb_data():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📋 Ордера"), KeyboardButton("✅ Выполненные")],
        [KeyboardButton("📈 График")],
        [KeyboardButton("⬅️ Назад к боту")],
    ], resize_keyboard=True)

def kb_ai_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🤖 AI Анализ"), KeyboardButton("💬 Чат с ИИ")],
        [KeyboardButton("⬅️ Назад к боту")],
    ], resize_keyboard=True)

def kb_settings():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🖥 Режим"),         KeyboardButton("⚡ Скорость"),      KeyboardButton("💲 Сумма ордера")],
        [KeyboardButton("📝 Переименовать"), KeyboardButton("🔗 Binance API")],
        [KeyboardButton("🎨 Тема"),          KeyboardButton("⏰ Дневной отчёт")],
        [KeyboardButton("📋 Дублировать"),   KeyboardButton("🗑 Удалить"),       KeyboardButton("🔄 Сброс")],
        [KeyboardButton("⬅️ Назад к боту")],
    ], resize_keyboard=True)

def kb_cancel():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)

def kb_order_place():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📥 BUY по рынку -$10"),  KeyboardButton("📤 SELL по рынку +$10")],
        [KeyboardButton("✏️ Своя цена BUY"), KeyboardButton("✏️ Своя цена SELL")],
        [KeyboardButton("🗑 Снять все ордера"), KeyboardButton("🗑 Снять один ордер")],
        [KeyboardButton("⬅️ Назад к боту")],
    ], resize_keyboard=True)

def kb_deposit():
    return ReplyKeyboardMarkup([
        [KeyboardButton("100 USDT"),  KeyboardButton("500 USDT")],
        [KeyboardButton("1000 USDT"), KeyboardButton("5000 USDT")],
        [KeyboardButton("🤖 Подобрать параметры сетки")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_mode():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔵 Симулятор")],
        [KeyboardButton("🟡 Binance Testnet")],
        [KeyboardButton("🔴 Реальный Binance")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_speed():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🐌 x0.25"),  KeyboardButton("🐢 x0.5")],
        [KeyboardButton("⚙️ x1.0 Стандарт"), KeyboardButton("⚡ x2.0")],
        [KeyboardButton("🚀 x4.0")],
        [KeyboardButton("📊 3 уровня"), KeyboardButton("📊 5 уровней"), KeyboardButton("📊 7 уровней"), KeyboardButton("📊 10 уровней")],
        [KeyboardButton("✏️ Своё значение")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_order_amt():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📦 10 USDT"),  KeyboardButton("📦 25 USDT")],
        [KeyboardButton("📦 50 USDT"),  KeyboardButton("📦 100 USDT")],
        [KeyboardButton("✏️ Своя сумма")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_theme():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🌙 Тёмная"),    KeyboardButton("☀️ Светлая")],
        [KeyboardButton("💜 Фиолетовая"), KeyboardButton("🌊 Синяя")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_api_manage():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔑 Изменить API"), KeyboardButton("👁 Показать API")],
        [KeyboardButton("🗑 Удалить API"),  KeyboardButton("⬅️ Назад к настройкам")],
    ], resize_keyboard=True)

def kb_ai():
    return ReplyKeyboardMarkup([
        [KeyboardButton("✅ Применить рекомендацию"), KeyboardButton("🔄 Обновить анализ")],
        [KeyboardButton("💬 Чат с ИИ")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

def kb_ai_chat():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🗑 Очистить историю")],
        [KeyboardButton("❌ Отмена")],
    ], resize_keyboard=True)

# ─── УТИЛИТЫ ──────────────────────────────────────────────────────────────────

def _usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"

def _pct(v) -> str:
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "0.00%"

# ─── КЛАСС БОТА ───────────────────────────────────────────────────────────────

class TradingBot:

    def __init__(self):
        self.db        = DatabaseManager(DATABASE_PATH)
        self.simulator = TradingSimulator(self.db)
        self.grid_sim  = GridSimulator(self.db, notify_callback=self._on_grid_fill)
        self.order_monitor = OrderMonitor(
            self.db,
            get_binance_client_func=self._get_client,
            notify_callback=self._notify_user,
        )
        self._app = None  # set in run()

    # ── контекст пользователя ─────────────────────────────────────────────

    @staticmethod
    def _uid(update: Update) -> int:
        return update.effective_user.id

    @staticmethod
    def _s(ctx) -> dict:
        """Shortcut to user_data dict."""
        return ctx.user_data

    def _bot_id(self, ctx) -> int | None:
        return ctx.user_data.get("bot_id")

    def _set_bot(self, ctx, bot_id: int):
        ctx.user_data["bot_id"] = bot_id

    def _screen(self, ctx) -> str:
        return ctx.user_data.get("screen", "main")

    def _set_screen(self, ctx, screen: str):
        ctx.user_data["screen"] = screen

    # ── Binance client ────────────────────────────────────────────────────

    def _client(self, bot: dict):
        mode = bot.get("mode") or MODE_SIMULATOR
        if mode == MODE_SIMULATOR:
            return MockBinanceClient()
        ak = bot.get("api_key") or BINANCE_API_KEY
        sk = bot.get("secret_key") or BINANCE_SECRET
        if mode == MODE_REAL:
            try:
                from binance_client import BinanceRealClient
                return BinanceRealClient(ak, sk)
            except Exception:
                pass
        return BinanceTestnetClient(ak, sk)

    def _get_client(self, bot: dict, uid: int = 0):
        """Adapter for OrderMonitor — wraps existing _client method."""
        return self._client(bot)

    async def _notify_user(self, bot_id: int, text: str):
        """Send notification to all users watching this bot."""
        try:
            for uid, data in (self._app.user_data or {}).items():
                if data.get("bot_id") == bot_id:
                    try:
                        await self._app.bot.send_message(
                            chat_id=uid, text=text, parse_mode="HTML"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"_notify_user error: {e}")

    # ── отправка ──────────────────────────────────────────────────────────

    async def _send(self, update: Update, text: str, kb=None):
        return await update.effective_message.reply_text(
            text, reply_markup=kb, parse_mode="HTML"
        )

    # ── экраны ────────────────────────────────────────────────────────────

    async def _screen_main(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "main")
        bots = await self.db.get_all_bots()
        if not bots:
            await self._send(update,
                "👋 <b>Добро пожаловать!</b>\n\nУ вас пока нет ботов.\nНажмите <b>➕ Добавить бота</b> чтобы начать.",
                kb_main()
            )
            return
        running = sum(1 for b in bots if b["status"] == "running")
        lines = [f"🤖 <b>Ваши торговые боты</b>  |  работает: {running}/{len(bots)}\n"]
        for b in bots:
            icon = "🟢" if b["status"] == "running" else "🔴"
            mi   = MODE_ICONS.get(b.get("mode") or MODE_SIMULATOR, "🔵")
            p    = await self.db.get_total_profit(b["id"])
            lines.append(f"{icon}{mi} <b>{b['name']}</b> — {_usd(b['balance'])} | прибыль: {_usd(p)}")
        await self._send(update, "\n".join(lines), kb_main())

    async def _screen_bot_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Показать список ботов через Inline кнопки для выбора."""
        bots = await self.db.get_all_bots()
        if not bots:
            await self._send(update, "🤖 У вас нет ботов.\nНажмите ➕ Добавить бота", kb_main())
            return
        keyboard = []
        for b in bots:
            icon = "🟢" if b["status"] == "running" else "🔴"
            mi   = MODE_ICONS.get(b.get("mode") or MODE_SIMULATOR, "🔵")
            p    = await self.db.get_total_profit(b["id"])
            keyboard.append([InlineKeyboardButton(
                f"{icon}{mi} {b['name']}  |  +{_usd(p)}",
                callback_data=f"sel:{b['id']}"
            )])
        await self._send(update, "🤖 <b>Выберите бота:</b>",
                         InlineKeyboardMarkup(keyboard))

    async def _screen_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "bot")
        bot_id = self._bot_id(ctx)
        if not bot_id:
            await self._send(update, "❌ Бот не выбран. Нажмите 🤖 Мои боты", kb_main())
            self._set_screen(ctx, "main")
            return
        bot = await self.db.get_bot(bot_id)
        if not bot:
            ctx.user_data.pop("bot_id", None)
            self._set_screen(ctx, "main")
            await self._send(update, "❌ Бот не найден или был удалён.\nВыберите бота из списка.", kb_main())
            return

        now = datetime.now()
        p_t = await self.db.get_total_profit(bot_id)
        p_d = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        orders = await self.db.get_open_orders(bot_id)
        mode   = bot.get("mode") or MODE_SIMULATOR
        icon   = "🟢" if bot["status"] == "running" else "🔴"

        price_line = ""
        try:
            price = self._client(bot).get_current_price(bot["symbol"])
            if price:
                price_line = f"\n💰 Цена BTC: <code>${price:,.0f}</code>"
        except Exception:
            pass

        text = (
            f"{icon} <b>{bot['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🖥 Режим:    {MODE_LABELS[mode]}\n"
            f"💼 Баланс:   <b>{_usd(bot['balance'])}</b>\n"
            f"📈 Прибыль:  <b>{_usd(p_t)}</b>  (за 24ч: {_usd(p_d)})\n"
            f"📋 Ордеров:  <b>{len(orders)}</b> открыто"
            + price_line
        )
        await self._send(update, text, kb_bot())

    async def _screen_orders(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Показываем ТОЛЬКО реальные ордера с биржи (не из БД)."""
        self._set_screen(ctx, "orders")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        mode   = bot.get("mode") or MODE_SIMULATOR

        # Получаем живые ордера с биржи
        live_orders = []
        error_msg   = ""
        try:
            live_orders = client.get_open_orders(bot["symbol"])
        except Exception as e:
            error_msg = str(e)

        sells = sorted([o for o in live_orders if o.get("side") == "SELL"],
                       key=lambda x: float(x.get("price", 0)), reverse=True)
        buys  = sorted([o for o in live_orders if o.get("side") == "BUY"],
                       key=lambda x: float(x.get("price", 0)), reverse=True)

        lines = [
            f"📋 <b>{bot['name']}</b> — Ордера на бирже",
            f"Режим: {MODE_LABELS[mode]}",
            f"━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if error_msg:
            lines.append(f"⚠️ Ошибка получения ордеров:\n{error_msg[:100]}")
        elif not live_orders:
            lines.append("📭 Нет открытых ордеров на бирже")
        else:
            if sells:
                lines.append(f"🔴 <b>SELL ордера ({len(sells)}):</b>")
                for o in sells[:10]:
                    px  = float(o.get("price", 0))
                    qty = float(o.get("origQty", 0))
                    oid = o.get("orderId", "")
                    lines.append(f"  📤 ${px:,.1f} × {qty:.4f} BTC  <code>#{oid}</code>")
                lines.append("")

            if buys:
                lines.append(f"🟢 <b>BUY ордера ({len(buys)}):</b>")
                for o in buys[:10]:
                    px  = float(o.get("price", 0))
                    qty = float(o.get("origQty", 0))
                    oid = o.get("orderId", "")
                    lines.append(f"  📥 ${px:,.1f} × {qty:.4f} BTC  <code>#{oid}</code>")

            lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"📊 Итого на бирже: <b>{len(live_orders)}</b> ордеров")

        await self._send(update, "\n".join(lines), kb_bot())

    async def _screen_filled(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Выполненные ордера и закрытые сделки."""
        self._set_screen(ctx, "filled")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)

        # Реальные сделки из таблицы trades
        try:
            real_trades = await self.db.get_trades(bot_id, 30)
        except Exception:
            real_trades = []

        # Симуляторные сделки
        sim_trades = await self.db.get_recent_trades(bot_id, 30)

        # Исполненные ордера
        try:
            filled_orders = await self.db.get_filled_orders(bot_id, 20)
        except Exception:
            filled_orders = []

        lines = [
            f"✅ <b>{bot['name']}</b> — Выполненные",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        # Реальные сделки (BUY→SELL пары)
        all_trades = real_trades + sim_trades
        if all_trades:
            total = sum(float(t.get("profit", 0)) for t in all_trades)
            lines.append(f"💰 <b>Закрытые сделки ({len(all_trades)}):</b>")
            for t in all_trades[:15]:
                profit = float(t.get("profit", 0))
                pstr   = f"<b>+{_usd(profit)}</b>" if profit >= 0 else f"<b>{_usd(profit)}</b>"
                bp     = float(t.get("buy_price", 0))
                sp     = float(t.get("sell_price", 0))
                qty    = float(t.get("quantity", 0))
                dt     = str(t.get("executed_at", ""))[:16]
                lines.append(
                    f"  📥 ${bp:,.1f} → 📤 ${sp:,.1f}\n"
                    f"     {qty:.4f} BTC | {pstr} | {dt}"
                )
            lines.append(f"\n💵 <b>Итого прибыль: {'+' if total>=0 else ''}{_usd(total)}</b>")
        else:
            lines.append("💰 Закрытых сделок пока нет")

        lines.append("")

        # Исполненные одиночные ордера
        if filled_orders:
            lines.append(f"📋 <b>Исполненные ордера ({len(filled_orders)}):</b>")
            for o in filled_orders[:10]:
                side = o.get("side", "?")
                px   = float(o.get("price", 0))
                qty  = float(o.get("quantity", 0))
                dt   = str(o.get("created_at", ""))[:16]
                icon = "📥" if side == "BUY" else "📤"
                lines.append(f"  {icon} {side} ${px:,.1f} × {qty:.5f} BTC | {dt}")
        else:
            lines.append("📋 Исполненных ордеров пока нет")

        if not all_trades and not filled_orders:
            lines.append("\nЗапустите бота и дождитесь первых сделок.")

        await self._send(update, "\n".join(lines), kb_data())

    async def _screen_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "stats")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        mode   = bot.get("mode") or MODE_SIMULATOR
        now    = datetime.now()

        p_d  = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        p_w  = await self.db.get_profit_since(bot_id, now - timedelta(weeks=1))
        p_m  = await self.db.get_profit_since(bot_id, now - timedelta(days=30))
        p_y  = await self.db.get_profit_since(bot_id, now - timedelta(days=365))
        p_t  = await self.db.get_total_profit(bot_id)
        orders  = await self.db.get_open_orders(bot_id)
        pairs   = await self.db.get_bot_pairs(bot_id)
        trades  = await self.db.get_recent_trades(bot_id, 5)
        order_usdt = bot.get("order_usdt") or 50

        price_line = live_line = ""
        try:
            price = client.get_current_price(bot["symbol"])
            if price:
                price_line = f"📈 Цена BTC:   <code>${price:,.2f}</code>\n"
        except Exception:
            pass
        try:
            lb = client.get_usdt_balance()
            if lb > 0 and mode != MODE_SIMULATOR:
                live_line = f"🌐 Binance:    <b>{_usd(lb)}</b>\n"
        except Exception:
            pass

        status = "🟢 Работает" if bot["status"] == "running" else "🔴 Остановлен"

        text = (
            f"📊 <b>{bot['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Статус:   {status}\n"
            f"Режим:    {MODE_LABELS[mode]}\n"
            f"Ордер:    <b>{_usd(order_usdt)}</b> USDT\n\n"
            f"💼 Баланс: <b>{_usd(bot['balance'])}</b>\n"
            + live_line + price_line +
            f"\n💵 <b>Прибыль:</b>\n"
            f"  24ч:      <b>{_usd(p_d)}</b>\n"
            f"  7 дней:   <b>{_usd(p_w)}</b>\n"
            f"  30 дней:  <b>{_usd(p_m)}</b>\n"
            f"  365 дней: <b>{_usd(p_y)}</b>\n"
            f"  Всего:    <b>{_usd(p_t)}</b>\n\n"
            f"Ордеров: {len(orders)}  |  Пар: {len(pairs)}\n"
        )

        if bot.get("center_price"):
            text += f"📍 Центр: <code>${bot['center_price']:,.2f}</code>\n"

        # Summa block
        if trades:
            percents = [t.get("profit_percent", 0) for t in trades]
            total_pct = sum(percents)
            summa = total_pct / 100 * order_usdt
            text += f"\n💡 <b>Summa (последние {len(trades)} сделок):</b>\n"
            for p in percents:
                text += f"  {p:+.2f}%\n"
            text += f"  ─────────\n  {total_pct:.2f}% × {_usd(order_usdt)} = <b>{_usd(summa)}</b>\n"

            text += "\n📜 <b>Последние сделки:</b>\n"
            for t in trades:
                dt = t.get("executed_at", "")
                if isinstance(dt, str) and dt:
                    try:
                        dt = datetime.fromisoformat(dt).strftime("%H:%M:%S")
                    except Exception:
                        dt = dt[:8]
                elif isinstance(dt, datetime):
                    dt = dt.strftime("%H:%M:%S")
                text += f"  ⏰ {dt}  +{_usd(t['profit'])} ({t['profit_percent']:.2f}%)\n"
        else:
            text += "\n<i>Сделок пока нет</i>"

        await self._send(update, text, kb_bot())

    async def _screen_overall(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bots = await self.db.get_all_bots()
        if not bots:
            await self._send(update, "📊 Нет ботов для статистики", kb_main())
            return
        now = datetime.now()
        p_d = p_w = p_m = p_y = p_t = 0.0
        total_balance = 0.0
        running = 0
        for b in bots:
            if b["status"] == "running":
                running += 1
            total_balance += b["balance"] or 0
            p_d += await self.db.get_profit_since(b["id"], now - timedelta(days=1))
            p_w += await self.db.get_profit_since(b["id"], now - timedelta(weeks=1))
            p_m += await self.db.get_profit_since(b["id"], now - timedelta(days=30))
            p_y += await self.db.get_profit_since(b["id"], now - timedelta(days=365))
            p_t += await self.db.get_total_profit(b["id"])

        text = (
            f"📊 <b>Общая статистика</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 Ботов: <b>{len(bots)}</b>  |  Работает: <b>{running}</b>\n"
            f"💼 Баланс: <b>{_usd(total_balance)}</b>\n\n"
            f"💵 <b>Прибыль:</b>\n"
            f"  24ч:      <b>{_usd(p_d)}</b>\n"
            f"  7 дней:   <b>{_usd(p_w)}</b>\n"
            f"  30 дней:  <b>{_usd(p_m)}</b>\n"
            f"  365 дней: <b>{_usd(p_y)}</b>\n"
            f"  Всего:    <b>{_usd(p_t)}</b>\n\n"
            f"<b>Боты:</b>\n"
        )
        for b in bots:
            icon = "🟢" if b["status"] == "running" else "🔴"
            mi   = MODE_ICONS.get(b.get("mode") or MODE_SIMULATOR, "🔵")
            pr   = await self.db.get_total_profit(b["id"])
            text += f"  {icon}{mi} {b['name']}: {_usd(b['balance'])} | +{_usd(pr)}\n"

        await self._send(update, text, kb_main())

    async def _screen_logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Читаемые логи — только важные события без технического мусора."""
        import os
        raw_lines = []
        for log_path in ["bot.log", "trading_bot.log", "logs/bot.log"]:
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        raw_lines = f.readlines()[-300:]
                    break
                except Exception:
                    pass

        if not raw_lines:
            await update.message.reply_text(
                "<b>📜 Логи</b>\n\nФайл bot.log не найден.\nПерезапусти бота — файл создастся автоматически.",
                parse_mode="HTML", reply_markup=kb_bot()
            )
            return

        skip_words = ["asyncio", "telegram.ext", "httpx", "aiohttp",
                      "urllib3", "charset", "werkzeug", "PTB", "Application"]
        icons = {
            "BUY":          "📥", "SELL":        "📤",
            "FILLED":       "✅", "FAILED":      "❌",
            "orderId":      "🔑", "profit":      "💰",
            "Прибыль":      "💰", "запущен":     "▶️",
            "остановлен":   "⏹", "Starting":    "🚀",
            "Пересоздаём":  "🔄", "Перевыставлен": "🔁",
            "Error":        "⚠️", "error":       "⚠️",
            "ошибка":       "⚠️", "Gemini":      "🤖",
            "Connected":    "🌐", "testnet":     "🌐",
        }

        readable = []
        seen = set()
        for line in reversed(raw_lines):
            line = line.strip()
            if not line or any(s in line for s in skip_words):
                continue
            parts    = line.split(" - ", 2)
            time_str = parts[0][:19] if parts else ""
            msg      = parts[-1] if len(parts) >= 2 else line
            key      = msg[:60]
            if key in seen:
                continue
            seen.add(key)
            icon = next((v for k, v in icons.items() if k in line), "📋")
            readable.append(f"{icon} <code>{time_str}</code>  {msg[:110]}")
            if len(readable) >= 20:
                break

        if readable:
            await update.message.reply_text(
                "<b>📜 Последние события:</b>\n\n" + "\n".join(readable),
                parse_mode="HTML", reply_markup=kb_bot()
            )
        else:
            await update.message.reply_text(
                "<b>📜 Логи</b>\n\nСобытий пока нет. Запусти бота и выставь ордера.",
                parse_mode="HTML", reply_markup=kb_bot()
            )

    async def _screen_order_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Меню ручного ордера и снятия ордеров."""
        self._set_screen(ctx, "order_menu")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        price  = client.get_current_price(bot["symbol"])
        open_orders = client.get_open_orders(bot["symbol"])
        text = (
            "<b>\U0001f4cc Ручные ордера</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4b0 Текущая цена: <b>${price:,.1f}</b>\n"
            f"\U0001f4cb Открытых ордеров на бирже: <b>{len(open_orders)}</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "Выбери действие:"
        )
        await self._send(update, text, kb_order_place())

    async def _place_manual_order(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                                   side: str, price: float):
        """Выставить ордер вручную и сразу попросить ИИ перестроить сетку."""
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        symbol = bot["symbol"]
        order_usdt = float(bot.get("order_usdt") or 50)
        qty    = max(round(order_usdt / price, 5), 0.001)

        await self._send(update, f"⏳ Выставляю {side} ордер @ ${price:,.1f}...")

        if side == "BUY":
            result = client.place_limit_buy(symbol, price, qty)
        else:
            result = client.place_limit_sell(symbol, price, qty)

        oid = result.get("orderId", "")
        if oid:
            msg = (
                "\u2705 <b>" + side + " \u043e\u0440\u0434\u0435\u0440 \u0432\u044b\u0441\u0442\u0430\u0432\u043b\u0435\u043d</b>\n"
                + f"\U0001f4b2 \u0426\u0435\u043d\u0430: ${price:,.1f}\n"
                + f"\U0001f4e6 \u041e\u0431\u044a\u0451\u043c: {qty:.5f} BTC\n"
                + f"\U0001f511 ID \u043e\u0440\u0434\u0435\u0440\u0430: {oid}\n\n"
                + "\U0001f916 \u0418\u0418 \u0430\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u0435\u0442 \u0438 \u043f\u0435\u0440\u0435\u0441\u0442\u0430\u0432\u043b\u044f\u0435\u0442 \u043e\u0441\u0442\u0430\u043b\u044c\u043d\u0443\u044e \u0441\u0435\u0442\u043a\u0443..."
            )
            await self._send(update, msg, kb_order_place())
            await self.db.add_order(bot_id, side, price, qty, str(oid), "MANUAL")
            # ИИ вызывается не чаще раза в 10 минут
            last_ai = ctx.user_data.get("last_ai_call", 0)
            import time
            if time.time() - last_ai > 600:
                ctx.user_data["last_ai_call"] = time.time()
                await self._ai_rebalance_after_manual(update, ctx, bot, side, price)
            else:
                mins = int((600 - (time.time() - last_ai)) / 60) + 1
                await self._send(update,
                    f"✅ Ордер выставлен.\n💡 ИИ перестроит сетку через ~{mins} мин (защита от лимита Gemini).",
                    kb_order_place()
                )
        else:
            msg = (
                "\u274c <b>\u041e\u0448\u0438\u0431\u043a\u0430 \u0432\u044b\u0441\u0442\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u043e\u0440\u0434\u0435\u0440\u0430</b>\n"
                + f"\u0411\u0438\u0440\u0436\u0430 \u0432\u0435\u0440\u043d\u0443\u043b\u0430: {result}\n\n"
                + "\u041f\u0440\u043e\u0432\u0435\u0440\u044c:\n"
                + "\u2022 \u041a\u043b\u044e\u0447\u0438 API \u0432 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430\u0445\n"
                + "\u2022 \u0414\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043b\u0438 \u0431\u0430\u043b\u0430\u043d\u0441\u0430\n"
                + "\u2022 \u0420\u0435\u0436\u0438\u043c: \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c Binance Testnet"
            )
            await self._send(update, msg, kb_order_place())

    async def _ai_rebalance_after_manual(self, update, ctx, bot, manual_side, manual_price):
        """ИИ переставляет сетку вокруг нового ордера. Вызывается не чаще 1 раза в 10 минут."""
        try:
            from ai_engine import analyse_and_rebalance
            bot_id = bot["id"]
            client = self._client(bot)
            symbol = bot["symbol"]
            orders = await self.db.get_open_orders(bot_id)
            trades = await self.db.get_trades(bot_id, limit=20)
            p_total, p_day = await self.db.get_total_profit(bot_id), await self.db.get_profit_since(bot_id, __import__('datetime').datetime.now() - __import__('datetime').timedelta(days=1))
            price = client.get_current_price(symbol)
            api_key = bot.get("gemini_api_key") or ""
            note = f"Трейдер вручную поставил {manual_side} @ ${manual_price:,.1f}. Перестрой сетку вокруг этой точки."
            rec = await analyse_and_rebalance(
                bot, orders, trades, p_total, p_day, price,
                user_note=note, api_key=api_key
            )
            analysis = rec.get("analysis", "")
            action   = rec.get("action", "keep")
            reason   = rec.get("reason", "")

            msg = "🤖 <b>ИИ-анализ после ручного ордера:</b>\n\n" + analysis
            if reason:
                msg += "\n\n📌 <b>Решение:</b> " + reason

            if action == "rebalance":
                new_center = rec["new_center"]
                msg += f"\n\n🔄 Пересоздаю сетку с центром ${new_center:,.0f}..."
                await self._send(update, msg, kb_order_place())
                await self.db.update_bot(bot_id, center_price=new_center,
                                          grid_speed=rec["new_speed"],
                                          grid_levels=rec["new_levels"])
                bot2 = await self.db.get_bot(bot_id)
                placed = await self._place_grid(bot2, client, new_center, clear_first=False)
                await self._send(update,
                    f"✅ ИИ выставил ещё {placed} ордеров вокруг ${new_center:,.0f}",
                    kb_order_place())
            else:
                await self._send(update, msg, kb_order_place())
        except Exception as e:
            logger.error(f"_ai_rebalance_after_manual: {e}")
            await self._send(update, f"⚠️ ИИ недоступен: {e}", kb_order_place())

    async def _cancel_all_orders_manual(self, update, ctx):
        """Снять все ордера с биржи."""
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        symbol = bot["symbol"]
        try:
            client.cancel_all_orders(symbol)
            await self.db.cancel_open_orders(bot_id)
            await self._send(
                update,
                f"✅ <b>Все ордера сняты</b>\n"
                f"Биржа: {symbol} — все открытые ордера отменены.\n"
                f"База данных очищена.",
                kb_order_place()
            )
        except Exception as e:
            await self._send(update, f"❌ Ошибка при снятии ордеров: {e}", kb_order_place())

    async def _screen_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "settings")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        mode   = bot.get("mode") or MODE_SIMULATOR
        dr     = "✅ Вкл" if bot.get("daily_report") else "❌ Выкл"
        theme  = bot.get("theme") or "dark"
        has_api = bool(bot.get("api_key"))
        spd    = bot.get("grid_speed") or 1.0
        lvl    = bot.get("grid_levels") or 5

        text = (
            f"⚙️ <b>Настройки — {bot['name']}</b>\n\n"
            f"🖥 Режим:          <b>{MODE_LABELS[mode]}</b>\n"
            f"💲 Сумма ордера:   <b>{_usd(bot.get('order_usdt', 50))}</b>\n"
            f"⚡ Скорость:       <b>×{spd:.2f}</b>  уровней: {lvl}\n"
            f"🎨 Тема:           <b>{theme}</b>\n"
            f"⏰ Дневной отчёт: <b>{dr}</b>\n"
            f"🔑 API ключи:     <b>{'✅ заданы' if has_api else '❌ нет'}</b>\n"
        )
        await self._send(update, text, kb_settings())

    async def _screen_speed(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "speed")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        speed  = bot.get("grid_speed") or 1.0
        lvl    = bot.get("grid_levels") or 5
        cp     = bot.get("center_price") or 100_000.0
        base   = 0.00175 * speed
        b1     = cp * (1 - base)
        s1     = cp * (1 + base)

        text = (
            f"⚡ <b>Скорость сетки — {bot['name']}</b>\n"
            f"Множитель: <b>×{speed:.2f}</b>  |  Уровней: <b>{lvl}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Центр:    <code>${cp:,.0f}</code>\n"
            f"🟢 1-й BUY:  <code>${b1:,.0f}</code>  ({base*100:.3f}%)\n"
            f"🔴 1-й SELL: <code>${s1:,.0f}</code>  ({base*100:.3f}%)\n\n"
            "Выберите пресет:"
        )
        await self._send(update, text, kb_speed())

    async def _screen_deposit(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "deposit")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        await self._send(update,
            f"💵 <b>Пополнение — {bot['name']}</b>\n\n"
            f"Текущий баланс: <b>{_usd(bot['balance'])}</b>\n\n"
            "Выберите сумму или введите своё значение:",
            kb_deposit()
        )

    async def _screen_ai_analyse(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "ai_analyse")
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        orders = await self.db.get_open_orders(bot_id)
        trades = await self.db.get_recent_trades(bot_id, 30)
        now    = datetime.now()
        p_t    = await self.db.get_total_profit(bot_id)
        p_d    = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        price  = self._client(bot).get_current_price(bot["symbol"]) or 0

        await self._send(update,
            f"🤖 <b>AI анализирует сетку...</b>\n"
            f"<i>Анализирую {len(orders)} ордеров и {len(trades)} сделок...</i>",
            kb_cancel()
        )

        api_key = os.getenv("GEMINI_API_KEY", "")
        result  = await analyse_and_rebalance(bot, orders, trades, p_t, p_d, price, api_key=api_key)

        action     = result.get("action", "keep")
        new_center = result.get("new_center", price)
        new_speed  = result.get("new_speed", bot.get("grid_speed", 1.0))
        new_levels = result.get("new_levels", bot.get("grid_levels", 5))
        analysis   = result.get("analysis", "")
        reason     = result.get("reason", "")

        ctx.user_data["ai_rec"] = {"bot_id": bot_id, "center": new_center, "speed": new_speed, "levels": new_levels}

        icons  = {"rebalance": "🔄", "keep": "✅", "stop": "⛔"}
        labels = {"rebalance": "Рекомендует пересоздать сетку", "keep": "Сетка в норме", "stop": "Рекомендует остановить"}

        text = (
            f"🤖 <b>AI Анализ — {bot['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{analysis}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{icons.get(action,'🔹')} <b>{labels.get(action, action)}</b>\n"
            f"<i>{reason}</i>\n\n"
            f"📌 Рекомендации:\n"
            f"  Центр:    <code>${new_center:,.0f}</code>\n"
            f"  Скорость: <b>×{new_speed:.2f}</b>\n"
            f"  Уровней:  <b>{new_levels}</b>"
        )

        keyboard = kb_ai() if action == "rebalance" else kb_bot()
        await self._send(update, text, keyboard)

    async def _screen_ai_chat(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._set_screen(ctx, "ai_chat")
        ctx.user_data["awaiting"] = "ai_chat"
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        if "ai_history" not in ctx.user_data:
            ctx.user_data["ai_history"] = []
        await self._send(update,
            f"💬 <b>Чат с ИИ — {bot['name']}</b>\n\n"
            "ИИ знает весь контекст бота.\n"
            "Задай вопрос о стратегии, рынке, настройках.\n\n"
            "<i>Напиши сообщение:</i>",
            kb_ai_chat()
        )

    # ── Запуск / остановка ────────────────────────────────────────────────

    async def _start_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        if not bot:
            return
        if bot["balance"] <= 0:
            await self._send(update,
                "❌ Баланс нулевой.\nСначала нажмите 💵 Пополнить.",
                kb_bot()
            )
            return

        order_usdt = float(bot.get("order_usdt") or 50)
        if bot["balance"] < order_usdt:
            await self._send(update,
                f"❌ Недостаточно средств!\n"
                f"Баланс: <b>{_usd(bot['balance'])}</b>\n"
                f"Минимум для запуска: <b>{_usd(order_usdt)}</b>\n\n"
                f"Пополните баланс или уменьшите сумму ордера в ⚙️ Настройки → 💲 Сумма ордера",
                kb_bot()
            )
            return

        mode   = bot.get("mode") or MODE_SIMULATOR
        client = self._client(bot)
        price  = client.get_current_price(bot["symbol"])

        # Перед запуском — отменяем всё старое на бирже и в базе
        if mode != MODE_SIMULATOR:
            try:
                client.cancel_all_orders(bot["symbol"])
                logger.info(f"[Start] Старые ордера на бирже отменены")
            except Exception as e:
                logger.error(f"[Start] cancel_all_orders: {e}")
        await self.db.reset_bot_stats(bot_id)

        await self.db.update_bot(bot_id, status="running", center_price=price)
        # Обновляем bot после reset
        bot = await self.db.get_bot(bot_id)
        orders_placed = await self._place_grid(bot, client, price, clear_first=False)

        if mode == MODE_SIMULATOR:
            speed = bot.get("grid_speed") or 1.0
            await self.grid_sim.start(bot_id, price, speed=speed)
            note = "🔄 Симулятор запущен — прибыль появится через 30–90 сек"
        else:
            uid = self._uid(update)
            await self.order_monitor.start_monitoring(bot_id, bot, uid)
            note = "📡 Мониторинг активен | Gemini следит за кризисами"

        await self._send(update,
            f"✅ <b>{bot['name']}</b> запущен!\n\n"
            f"📍 Центр сетки: <code>${price:,.2f}</code>\n"
            f"📊 Выставлено:  <b>{orders_placed}</b> ордеров\n"
            f"🖥 Режим:       {MODE_LABELS[mode]}\n"
            f"{note}",
            kb_bot()
        )

    async def _stop_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        await self.db.update_bot(bot_id, status="stopped")
        await self.grid_sim.stop(bot_id)
        await self.order_monitor.stop_monitoring(bot_id)
        await self._send(update, f"⏸ <b>{bot['name']}</b> остановлен.", kb_bot())

    # ── Пополнение ────────────────────────────────────────────────────────

    async def _do_deposit(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, amount: float):
        bot_id  = self._bot_id(ctx)
        bot     = await self.db.get_bot(bot_id)
        await self.db.add_deposit(bot_id, amount)
        new_bal = (bot["balance"] or 0) + amount
        await self._send(update,
            f"✅ Пополнено <b>+{_usd(amount)}</b>\nНовый баланс: <b>{_usd(new_bal)}</b>",
            kb_bot()
        )
        self._set_screen(ctx, "bot")

    # ── Вывод ─────────────────────────────────────────────────────────────

    async def _do_withdrawal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, amount: float):
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        balance = bot["balance"] or 0
        if amount > balance:
            await self._send(update,
                f"❌ Недостаточно средств!\nБаланс: <b>{_usd(balance)}</b>",
                kb_main()
            )
            return
        new_balance = balance - amount
        await self.db.update_bot(bot_id, balance=new_balance)
        await self._send(update,
            f"✅ Вывод <b>{_usd(amount)}</b> выполнен\nНовый баланс: <b>{_usd(new_balance)}</b>",
            kb_main()
        )
        self._set_screen(ctx, "main")

    # ── Сетка ─────────────────────────────────────────────────────────────

    async def _place_grid(self, bot: dict, client, center_price: float, clear_first: bool = False) -> int:
        """
        Сетка с фиксированным отступом $10 от центра.
        BUY:  center - $10, center - $20, center - $30 ...
        SELL: center + $10, center + $20, center + $30 ...
        """
        symbol     = bot["symbol"]
        bot_id     = bot["id"]
        order_usdt = float(bot.get("order_usdt") or 50)
        levels     = int(bot.get("grid_levels") or 5)
        step_usd   = 10.0  # отступ между уровнями в долларах

        quantity = max(round(order_usdt / center_price, 6), 0.00001)

        if clear_first:
            # Отменяем все ордера на бирже перед пересозданием
            try:
                client.cancel_all_orders(symbol)
            except Exception:
                pass
            await self.db.cancel_open_orders(bot_id)

        count = 0

        # BUY ордера: ниже центра на $10, $20, $30...
        for i in range(1, levels + 1):
            buy_price = round(center_price - step_usd * i, 2)
            pair_id   = f"PAIR_B{i}"
            eid = ""
            try:
                result = client.place_limit_buy(symbol, buy_price, quantity)
                if isinstance(result, dict) and result.get("orderId"):
                    eid = str(result["orderId"])
                    logger.info(f"✅ BUY #{i} ${buy_price} qty={quantity} eid={eid}")
                else:
                    logger.warning(f"⚠️ BUY #{i} ${buy_price} — нет orderId: {result}")
            except Exception as e:
                logger.error(f"❌ BUY #{i}: {e}")
            await self.db.add_order(bot_id, "BUY", buy_price, quantity, eid, pair_id)
            count += 1

        # SELL ордера: выше центра на $10, $20, $30...
        for i in range(1, levels + 1):
            sell_price = round(center_price + step_usd * i, 2)
            pair_id    = f"PAIR_S{i}"
            eid = ""
            try:
                result = client.place_limit_sell(symbol, sell_price, quantity)
                if isinstance(result, dict) and result.get("orderId"):
                    eid = str(result["orderId"])
                    logger.info(f"✅ SELL #{i} ${sell_price} qty={quantity} eid={eid}")
                else:
                    logger.warning(f"⚠️ SELL #{i} ${sell_price} — нет orderId: {result}")
            except Exception as e:
                logger.error(f"❌ SELL #{i}: {e}")
            await self.db.add_order(bot_id, "SELL", sell_price, quantity, eid, pair_id)
            count += 1

        # Пары для отображения
        for i in range(1, levels + 1):
            bp = round(center_price - step_usd * i, 2)
            sp = round(center_price + step_usd * i, 2)
            await self.db.add_pair(bot_id, f"PAIR{i}", bp, sp, quantity)

        return count

    # ── Главный обработчик сообщений ──────────────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        data = q.data

        if data.startswith("sel:"):
            bot_id = int(data.split(":")[1])
            self._set_bot(ctx, bot_id)
            self._set_screen(ctx, "bot")
            try:
                await q.message.delete()
            except Exception:
                pass
            await self._screen_bot(update, ctx)

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text     = update.message.text.strip()
        screen   = self._screen(ctx)
        bot_id   = self._bot_id(ctx)
        awaiting = ctx.user_data.get("awaiting")

        # ── Глобальные ────────────────────────────────────────────────────
        if text == "❌ Отмена":
            ctx.user_data.pop("awaiting", None)
            if screen in ("settings", "mode", "order_amt", "speed", "theme", "api"):
                await self._screen_settings(update, ctx)
            elif screen in ("deposit", "bot", "orders", "filled", "stats",
                            "ai_analyse", "ai_chat", "withdrawal",
                            "data_menu", "ai_menu"):
                await self._screen_bot(update, ctx)
            else:
                await self._screen_main(update, ctx)
            return

        if text == "⬅️ Назад":
            ctx.user_data.pop("awaiting", None)
            if screen in ("settings", "mode", "order_amt", "speed", "theme", "api", "api_manage"):
                await self._screen_bot(update, ctx)
            elif screen in ("bot", "orders", "filled", "stats",
                            "deposit", "ai_analyse", "ai_chat",
                            "data_menu", "ai_menu"):
                await self._screen_main(update, ctx)
            else:
                await self._screen_main(update, ctx)
            return

        if text == "⬅️ Назад к боту":
            ctx.user_data.pop("awaiting", None)
            await self._screen_bot(update, ctx)
            return

        if text == "⬅️ Назад к настройкам":
            ctx.user_data.pop("awaiting", None)
            await self._screen_settings(update, ctx)
            return

        # ── Главное меню ──────────────────────────────────────────────────
        if text == "🤖 Мои боты":
            await self._screen_bot_list(update, ctx)
            return
        if text == "➕ Добавить бота":
            ctx.user_data["awaiting"] = "new_bot_name"
            await self._send(update, "📝 Введите имя нового бота:", kb_cancel())
            return
        if text == "📊 Общая статистика":
            await self._screen_overall(update, ctx)
            return
        if text == "💰 Вывод средств":
            if not bot_id:
                await self._send(update, "❌ Сначала выберите бота из <b>🤖 Мои боты</b>", kb_main())
                return
            ctx.user_data["awaiting"] = "withdrawal"
            bot = await self.db.get_bot(bot_id)
            await self._send(update,
                f"💰 Вывод средств — <b>{bot['name']}</b>\n"
                f"Баланс: <b>{_usd(bot['balance'])}</b>\n\nВведите сумму в USDT:",
                kb_cancel()
            )
            return

        # ── Ожидаем ввод ──────────────────────────────────────────────────
        if awaiting == "new_bot_name":
            ctx.user_data.pop("awaiting")
            bot = await self.db.create_bot(text)
            self._set_bot(ctx, bot["id"])
            self._set_screen(ctx, "bot")
            await self._send(update,
                f"✅ Бот <b>{text}</b> создан!\n\n"
                "Следующие шаги:\n"
                "1️⃣ Нажмите <b>💵 Пополнить</b>\n"
                "2️⃣ В <b>⚙️ Настройки</b> выберите режим\n"
                "3️⃣ Нажмите <b>▶️ Запустить</b>",
                kb_bot()
            )
            return

        if awaiting == "withdrawal":
            ctx.user_data.pop("awaiting")
            try:
                amount = float(text.replace(",", "."))
                if amount <= 0:
                    raise ValueError
                await self._do_withdrawal(update, ctx, amount)
            except ValueError:
                await self._send(update, "❌ Некорректная сумма. Введите число:", kb_cancel())
            return

        if awaiting == "manual_buy_price":
            ctx.user_data.pop("awaiting")
            try:
                price = float(text.replace(",", ".").replace(" ", ""))
                if price <= 0:
                    raise ValueError
                await self._place_manual_order(update, ctx, "BUY", price)
            except ValueError:
                await self._send(update, "❌ Некорректная цена. Введи число, например: 103500", kb_cancel())
            return

        if awaiting == "manual_sell_price":
            ctx.user_data.pop("awaiting")
            try:
                price = float(text.replace(",", ".").replace(" ", ""))
                if price <= 0:
                    raise ValueError
                await self._place_manual_order(update, ctx, "SELL", price)
            except ValueError:
                await self._send(update, "❌ Некорректная цена. Введи число, например: 105500", kb_cancel())
            return

        if awaiting == "cancel_order_num":
            ctx.user_data.pop("awaiting")
            orders_list = ctx.user_data.pop("cancel_order_list", [])
            try:
                idx = int(text.strip()) - 1
                if idx < 0 or idx >= len(orders_list):
                    raise ValueError
                o      = orders_list[idx]
                oid    = o["orderId"]
                bot_id = self._bot_id(ctx)
                bot    = await self.db.get_bot(bot_id)
                client = self._client(bot)
                client.cancel_order(bot["symbol"], oid)
                await self._send(
                    update,
                    f"✅ <b>Ордер отменён</b>\n"
                    f"ID: {oid}\n"
                    f"Цена: ${float(o.get('price',0)):,.1f}\n"
                    f"Сторона: {o.get('side','')}",
                    kb_order_place()
                )
            except (ValueError, IndexError):
                await self._send(update, "❌ Неверный номер. Попробуй снова.", kb_order_place())
            return

        # ── Экран бота ────────────────────────────────────────────────────
        if screen == "bot" or text in (
            "▶️ Запустить", "⏸ Остановить",
            "📊 Статистика", "💵 Пополнить",
            "📋 Данные", "🤖 AI", "⚙️ Настройки",
            "📌 Ордер"
        ):
            if not bot_id:
                await self._send(update, "❌ Сначала выберите бота из <b>🤖 Мои боты</b>", kb_main())
                return
            bot = await self.db.get_bot(bot_id)
            if not bot:
                ctx.user_data.pop("bot_id", None)
                self._set_screen(ctx, "main")
                await self._send(update, "❌ Бот не найден или был удалён.\nВыберите другой бот.", kb_main())
                return

            if text == "▶️ Запустить":
                await self._start_bot(update, ctx)
            elif text == "⏸ Остановить":
                await self._stop_bot(update, ctx)
            elif text == "💵 Пополнить":
                await self._screen_deposit(update, ctx)
            elif text == "📊 Статистика":
                await self._screen_stats(update, ctx)
            elif text == "📋 Данные":
                self._set_screen(ctx, "data_menu")
                await self._send(update, "📋 <b>Данные бота</b>\nВыберите раздел:", kb_data())
            elif text == "🤖 AI":
                self._set_screen(ctx, "ai_menu")
                await self._send(update, "🤖 <b>AI-инструменты</b>\nВыберите режим:", kb_ai_menu())
            elif text == "⚙️ Настройки":
                await self._screen_settings(update, ctx)
            elif text == "📜 Логи":
                await self._screen_logs(update, ctx)
            elif text == "📌 Ордер":
                await self._screen_order_menu(update, ctx)
            else:
                await self._screen_bot(update, ctx)
            return

        # ── Меню ручных ордеров ───────────────────────────────────────────
        if screen == "order_menu" or text in (
            "📥 BUY по рынку -$10", "📤 SELL по рынку +$10",
            "✏️ Своя цена BUY", "✏️ Своя цена SELL",
            "🗑 Снять все ордера", "🗑 Снять один ордер",
        ):
            if not bot_id:
                await self._send(update, "❌ Сначала выберите бота", kb_main())
                return
            bot    = await self.db.get_bot(bot_id)
            client = self._client(bot)

            if text == "📥 BUY по рынку -$10":
                price = round(client.get_current_price(bot["symbol"]) - 10, 1)
                await self._place_manual_order(update, ctx, "BUY", price)

            elif text == "📤 SELL по рынку +$10":
                price = round(client.get_current_price(bot["symbol"]) + 10, 1)
                await self._place_manual_order(update, ctx, "SELL", price)

            elif text == "✏️ Своя цена BUY":
                ctx.user_data["awaiting"] = "manual_buy_price"
                await self._send(update,
                    f"💬 Введи цену для <b>BUY</b> ордера в USDT:\n"
                    f"(Текущая цена: ${client.get_current_price(bot['symbol']):,.1f})",
                    kb_cancel())

            elif text == "✏️ Своя цена SELL":
                ctx.user_data["awaiting"] = "manual_sell_price"
                await self._send(update,
                    f"💬 Введи цену для <b>SELL</b> ордера в USDT:\n"
                    f"(Текущая цена: ${client.get_current_price(bot['symbol']):,.1f})",
                    kb_cancel())

            elif text == "🗑 Снять все ордера":
                await self._cancel_all_orders_manual(update, ctx)

            elif text == "🗑 Снять один ордер":
                open_orders = client.get_open_orders(bot["symbol"])
                if not open_orders:
                    await self._send(update, "📭 Нет открытых ордеров на бирже.", kb_order_place())
                else:
                    lines = ["📋 <b>Открытые ордера — введи номер для отмены:</b>\n"]
                    for i, o in enumerate(open_orders[:10], 1):
                        side = o.get("side","?")
                        px   = float(o.get("price",0))
                        qty  = float(o.get("origQty",0))
                        oid  = o.get("orderId","?")
                        icon = "📥" if side == "BUY" else "📤"
                        lines.append(f"{i}. {icon} {side} ${px:,.1f} \u00d7 {qty:.5f} BTC  (ID:{oid})")
                    ctx.user_data["awaiting"]          = "cancel_order_num"
                    ctx.user_data["cancel_order_list"] = open_orders[:10]
                    await self._send(update, "\n".join(lines), kb_cancel())

            else:
                await self._screen_order_menu(update, ctx)
            return

        # ── Подменю Данные ────────────────────────────────────────────────
        if screen == "data_menu" or text in ("📋 Ордера", "✅ Выполненные", "📈 График"):
            if not bot_id:
                await self._send(update, "❌ Сначала выберите бота из <b>🤖 Мои боты</b>", kb_main())
                return
            if text == "📋 Ордера":
                await self._screen_orders(update, ctx)
            elif text == "✅ Выполненные":
                await self._screen_filled(update, ctx)
            elif text == "📈 График":
                await self._show_chart(update, ctx)
            else:
                self._set_screen(ctx, "data_menu")
                await self._send(update, "📋 <b>Данные бота</b>\nВыберите раздел:", kb_data())
            return

        # ── Подменю AI ────────────────────────────────────────────────────
        if screen == "ai_menu" or text in ("🤖 AI Анализ", "💬 Чат с ИИ"):
            if not bot_id:
                await self._send(update, "❌ Сначала выберите бота из <b>🤖 Мои боты</b>", kb_main())
                return
            if text == "🤖 AI Анализ":
                await self._screen_ai_analyse(update, ctx)
            elif text == "💬 Чат с ИИ":
                await self._screen_ai_chat(update, ctx)
            else:
                self._set_screen(ctx, "ai_menu")
                await self._send(update, "🤖 <b>AI-инструменты</b>\nВыберите режим:", kb_ai_menu())
            return

        # ── Экран пополнения ──────────────────────────────────────────────
        if screen == "deposit":
            deposit_map = {"100 USDT": 100, "500 USDT": 500, "1000 USDT": 1000, "5000 USDT": 5000}
            if text in deposit_map:
                await self._do_deposit(update, ctx, float(deposit_map[text]))
                return
            if text == "🤖 Подобрать параметры сетки":
                bot    = await self.db.get_bot(bot_id)
                client = self._client(bot)
                price  = client.get_current_price(bot["symbol"]) or 0
                await self._send(update, "🤖 <b>AI подбирает параметры...</b>", kb_cancel())
                api_key    = os.getenv("GEMINI_API_KEY", "")
                suggestion = await suggest_grid(price, bot["balance"], api_key)
                await self._send(update,
                    f"🤖 <b>Рекомендации AI</b>\n\n{suggestion}\n\n"
                    f"<i>Настройте параметры в ⚙️ Настройки после пополнения.</i>",
                    kb_deposit()
                )
                return
            if awaiting == "deposit_custom":
                ctx.user_data.pop("awaiting")
                try:
                    amount = float(text.replace(",", "."))
                    if amount <= 0:
                        raise ValueError
                    await self._do_deposit(update, ctx, amount)
                except ValueError:
                    await self._send(update, "❌ Некорректная сумма:", kb_cancel())
                return
            # Своя сумма или прочий ввод
            ctx.user_data["awaiting"] = "deposit_custom"
            await self._send(update, "💵 Введите сумму пополнения в USDT:", kb_cancel())
            return

        # ── Настройки ─────────────────────────────────────────────────────
        if screen == "settings":
            if text == "🖥 Режим":
                self._set_screen(ctx, "mode")
                ctx.user_data["awaiting"] = "set_mode"
                bot = await self.db.get_bot(bot_id)
                mode = bot.get("mode") or MODE_SIMULATOR
                await self._send(update,
                    f"🖥 <b>Режим работы</b>\nТекущий: <b>{MODE_LABELS[mode]}</b>\n\n"
                    "🔵 <b>Симулятор</b> — без API, виртуальные сделки\n"
                    "🟡 <b>Testnet</b> — ключи от testnet.binancefuture.com\n"
                    "🔴 <b>Реальный</b> — настоящие деньги ⚠️",
                    kb_mode()
                )
            elif text == "⚡ Скорость":
                await self._screen_speed(update, ctx)
            elif text == "💲 Сумма ордера":
                self._set_screen(ctx, "order_amt")
                ctx.user_data["awaiting"] = "set_order_amount"
                bot = await self.db.get_bot(bot_id)
                await self._send(update,
                    f"💲 <b>Сумма ордера</b>\nТекущая: <b>{_usd(bot.get('order_usdt', 50))}</b>\n\nВыберите:",
                    kb_order_amt()
                )
            elif text == "📝 Переименовать":
                ctx.user_data["awaiting"] = "rename"
                await self._send(update, "📝 Введите новое имя бота:", kb_cancel())
            elif text == "🔗 Binance API":
                await self._handle_api_menu(update, ctx)
            elif text == "🎨 Тема":
                self._set_screen(ctx, "theme")
                ctx.user_data["awaiting"] = "select_theme"
                await self._send(update,
                    "🎨 <b>Тема оформления:</b>\n\n"
                    "🌙 Тёмная\n☀️ Светлая\n💜 Фиолетовая\n🌊 Синяя",
                    kb_theme()
                )
            elif text == "⏰ Дневной отчёт":
                bot = await self.db.get_bot(bot_id)
                new_v = not bool(bot.get("daily_report"))
                await self.db.update_bot(bot_id, daily_report=int(new_v))
                status = "✅ Включён" if new_v else "❌ Выключен"
                await self._send(update,
                    f"⏰ <b>Дневной отчёт</b>\nСтатус: {status}\n\n"
                    + ("Каждый день в 00:00 вы будете получать отчёт по боту." if new_v else "Автоматические отчёты отключены."),
                    kb_settings()
                )
            elif text == "📋 Дублировать":
                await self._clone_bot(update, ctx)
            elif text == "🗑 Удалить":
                ctx.user_data["awaiting"] = "confirm_delete"
                bot = await self.db.get_bot(bot_id)
                await self._send(update,
                    f"⚠️ Удалить бота <b>{bot['name']}</b>?\nВсе данные будут потеряны!",
                    ReplyKeyboardMarkup([
                        [KeyboardButton("✅ Да, удалить"), KeyboardButton("❌ Отмена")]
                    ], resize_keyboard=True)
                )
            elif text == "🔄 Сброс":
                bot    = await self.db.get_bot(bot_id)
                orders = await self.db.get_open_orders(bot_id)
                profit = await self.db.get_total_profit(bot_id)
                ctx.user_data["awaiting"] = "confirm_reset"
                await self._send(update,
                    f"⚠️ <b>Сброс данных — {bot['name']}</b>\n\n"
                    f"Будет удалено:\n  • {len(orders)} ордеров\n  • Прибыль: {_usd(profit)}\n\n"
                    "Баланс и настройки сохранятся.",
                    ReplyKeyboardMarkup([
                        [KeyboardButton("✅ Сбросить"), KeyboardButton("❌ Отмена")]
                    ], resize_keyboard=True)
                )
            else:
                await self._screen_settings(update, ctx)
            return

        # ── Подтверждения ─────────────────────────────────────────────────
        if awaiting == "confirm_delete":
            ctx.user_data.pop("awaiting")
            if text == "✅ Да, удалить":
                bot = await self.db.get_bot(bot_id)
                name = bot["name"]
                await self.grid_sim.stop(bot_id)
                await self.order_monitor.stop_monitoring(bot_id)
                await self.db.delete_bot(bot_id)
                ctx.user_data.pop("bot_id", None)
                await self._send(update, f"🗑 Бот <b>{name}</b> удалён.", kb_main())
                self._set_screen(ctx, "main")
            else:
                await self._screen_settings(update, ctx)
            return

        if awaiting == "confirm_reset":
            ctx.user_data.pop("awaiting")
            if text == "✅ Сбросить":
                await self.grid_sim.stop(bot_id)
                await self.order_monitor.stop_monitoring(bot_id)
                # Отменяем ордера на бирже
                bot = await self.db.get_bot(bot_id)
                if bot and (bot.get("mode") or MODE_SIMULATOR) != MODE_SIMULATOR:
                    try:
                        client = self._client(bot)
                        client.cancel_all_orders(bot["symbol"])
                        logger.info(f"[Reset] Ордера на бирже отменены для бота {bot_id}")
                    except Exception as e:
                        logger.error(f"[Reset] Ошибка отмены на бирже: {e}")
                await self.db.reset_bot_stats(bot_id)
                await self._send(update,
                    "✅ <b>Сброс выполнен!</b>\n\n"
                    "Все ордера на бирже отменены.\n"
                    "Нажмите ▶️ Запустить чтобы начать заново.",
                    kb_bot()
                )
                self._set_screen(ctx, "bot")
            else:
                await self._screen_settings(update, ctx)
            return

        # ── Режим ─────────────────────────────────────────────────────────
        if awaiting == "set_mode":
            mode_map = {"🔵 Симулятор": MODE_SIMULATOR, "🟡 Binance Testnet": MODE_TESTNET, "🔴 Реальный Binance": MODE_REAL}
            if text in mode_map:
                ctx.user_data.pop("awaiting")
                mode = mode_map[text]
                await self.db.update_bot(bot_id, mode=mode)
                warn = "\n\n⚠️ <b>Осторожно!</b> Реальные деньги!" if mode == MODE_REAL else ""
                await self._send(update, f"✅ Режим: <b>{MODE_LABELS[mode]}</b>{warn}", kb_settings())
                self._set_screen(ctx, "settings")
            else:
                await self._send(update, "❓ Выберите режим из списка:", kb_mode())
            return

        # ── Сумма ордера ──────────────────────────────────────────────────
        if awaiting == "set_order_amount":
            amt_map = {"📦 10 USDT": 10, "📦 25 USDT": 25, "📦 50 USDT": 50, "📦 100 USDT": 100}
            if text in amt_map:
                ctx.user_data.pop("awaiting")
                await self.db.update_bot(bot_id, order_usdt=float(amt_map[text]))
                await self._send(update, f"✅ Сумма ордера: <b>{_usd(amt_map[text])}</b>", kb_settings())
                self._set_screen(ctx, "settings")
            elif text == "✏️ Своя сумма":
                ctx.user_data["awaiting"] = "order_custom"
                await self._send(update, "💲 Введите сумму ордера в USDT:", kb_cancel())
            else:
                await self._send(update, "❓ Выберите из списка:", kb_order_amt())
            return

        if awaiting == "order_custom":
            ctx.user_data.pop("awaiting")
            try:
                amount = float(text.replace(",", "."))
                if amount <= 0:
                    raise ValueError
                await self.db.update_bot(bot_id, order_usdt=amount)
                await self._send(update, f"✅ Сумма ордера: <b>{_usd(amount)}</b>", kb_settings())
                self._set_screen(ctx, "settings")
            except ValueError:
                await self._send(update, "❌ Некорректная сумма:", kb_cancel())
            return

        # ── Скорость ──────────────────────────────────────────────────────
        if screen == "speed":
            speed_map = {"🐌 x0.25": 0.25, "🐢 x0.5": 0.5, "⚙️ x1.0 Стандарт": 1.0, "⚡ x2.0": 2.0, "🚀 x4.0": 4.0}
            lvl_map   = {"📊 3 уровня": 3, "📊 5 уровней": 5, "📊 7 уровней": 7, "📊 10 уровней": 10}
            if text in speed_map:
                await self.db.update_bot(bot_id, grid_speed=speed_map[text])
                await self._send(update, f"✅ Скорость: <b>{text}</b>\nПерезапустите бота для применения.", kb_speed())
            elif text in lvl_map:
                await self.db.update_bot(bot_id, grid_levels=lvl_map[text])
                await self._send(update, f"✅ Уровней: <b>{lvl_map[text]}</b>\nПерезапустите бота для применения.", kb_speed())
            elif text == "✏️ Своё значение":
                ctx.user_data["awaiting"] = "speed_custom"
                await self._send(update, "⚡ Введите множитель (0.1–5.0):\n<i>Пример: 1.5</i>", kb_cancel())
            elif awaiting == "speed_custom":
                ctx.user_data.pop("awaiting")
                try:
                    val = float(text.replace(",", "."))
                    if not 0.1 <= val <= 5.0:
                        raise ValueError
                    await self.db.update_bot(bot_id, grid_speed=val)
                    await self._send(update, f"✅ Скорость: <b>×{val:.2f}</b>\nПерезапустите бота.", kb_speed())
                except ValueError:
                    await self._send(update, "❌ Введите число от 0.1 до 5.0", kb_cancel())
            return

        if awaiting == "speed_custom":
            ctx.user_data.pop("awaiting")
            try:
                val = float(text.replace(",", "."))
                if not 0.1 <= val <= 5.0:
                    raise ValueError
                await self.db.update_bot(bot_id, grid_speed=val)
                await self._send(update, f"✅ Скорость: <b>×{val:.2f}</b>\nПерезапустите бота.", kb_speed())
                self._set_screen(ctx, "speed")
            except ValueError:
                await self._send(update, "❌ Введите число от 0.1 до 5.0", kb_cancel())
            return

        # ── Тема ──────────────────────────────────────────────────────────
        if awaiting == "select_theme":
            themes = {"🌙 Тёмная": "dark", "☀️ Светлая": "light", "💜 Фиолетовая": "purple", "🌊 Синяя": "blue"}
            if text in themes:
                ctx.user_data.pop("awaiting")
                await self.db.update_bot(bot_id, theme=themes[text])
                await self._send(update, f"✅ Тема: <b>{text}</b>", kb_settings())
                self._set_screen(ctx, "settings")
            else:
                await self._send(update, "❓ Выберите тему из списка:", kb_theme())
            return

        # ── Переименовать ─────────────────────────────────────────────────
        if awaiting == "rename":
            ctx.user_data.pop("awaiting")
            await self.db.update_bot(bot_id, name=text)
            await self._send(update, f"✅ Переименован: <b>{text}</b>", kb_settings())
            return

        # ── API ───────────────────────────────────────────────────────────
        if text in ("🔑 Изменить API", "👁 Показать API", "🗑 Удалить API"):
            await self._handle_api_manage(update, ctx, text)
            return

        if awaiting == "api_key":
            ctx.user_data["_tmp_api_key"] = text
            ctx.user_data["awaiting"]     = "api_secret"
            await self._send(update, "🔑 Введите <b>Secret Key</b>:", kb_cancel())
            return

        if awaiting == "api_secret":
            ctx.user_data.pop("awaiting")
            api_key = ctx.user_data.pop("_tmp_api_key", "")
            await self.db.update_bot(bot_id, api_key=api_key, secret_key=text)
            await self._send(update, "✅ API ключи сохранены!", kb_settings())
            self._set_screen(ctx, "settings")
            return

        # ── AI анализ — кнопки ────────────────────────────────────────────
        if screen == "ai_analyse":
            if text == "✅ Применить рекомендацию":
                await self._ai_apply_rebalance(update, ctx)
            elif text == "🔄 Обновить анализ":
                await self._screen_ai_analyse(update, ctx)
            elif text == "💬 Чат с ИИ":
                await self._screen_ai_chat(update, ctx)
            return

        # ── AI чат ────────────────────────────────────────────────────────
        if screen == "ai_chat" or awaiting == "ai_chat":
            if text == "🗑 Очистить историю":
                ctx.user_data["ai_history"] = []
                await self._send(update, "✅ История очищена.", kb_ai_chat())
                return
            ctx.user_data["awaiting"] = "ai_chat"
            bot    = await self.db.get_bot(bot_id)
            now    = datetime.now()
            orders = await self.db.get_open_orders(bot_id)
            trades = await self.db.get_recent_trades(bot_id, 20)
            p_t    = await self.db.get_total_profit(bot_id)
            p_d    = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
            price  = self._client(bot).get_current_price(bot["symbol"]) or 0

            history = ctx.user_data.get("ai_history", [])
            history.append({"role": "user", "text": text})

            api_key = os.getenv("GEMINI_API_KEY", "")
            reply   = await ai_chat(bot, orders, trades, p_t, p_d, price, text, history, api_key)
            history.append({"role": "ai", "text": reply})
            ctx.user_data["ai_history"] = history[-20:]

            if len(reply) > 3800:
                reply = reply[:3800] + "…"

            await self._send(update,
                f"💬 <b>Чат с ИИ</b>\n\n"
                f"👤 <i>{text[:100]}</i>\n\n"
                f"🤖 {reply}\n\n"
                "<i>Напиши следующий вопрос:</i>",
                kb_ai_chat()
            )
            return

        # Fallback
        await self._screen_main(update, ctx)

    # ── Вспомогательные ───────────────────────────────────────────────────

    async def _handle_api_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id  = self._bot_id(ctx)
        bot     = await self.db.get_bot(bot_id)
        has_api = bool(bot.get("api_key"))
        if has_api:
            self._set_screen(ctx, "api_manage")
            await self._send(update,
                "🔗 <b>Binance API</b>\n\n✅ API ключи настроены\n\nВыберите действие:",
                kb_api_manage()
            )
        else:
            self._set_screen(ctx, "api")
            ctx.user_data["awaiting"] = "api_key"
            await self._send(update,
                "🔗 <b>Подключение Binance API</b>\n\n"
                "Testnet: <code>testnet.binancefuture.com</code>\n"
                "Real: <code>binance.com → API Management</code>\n\n"
                "🔑 Введите <b>API Key</b>:",
                kb_cancel()
            )

    async def _handle_api_manage(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str):
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        if action == "🔑 Изменить API":
            self._set_screen(ctx, "api")
            ctx.user_data["awaiting"] = "api_key"
            await self._send(update, "🔑 Введите новый <b>API Key</b>:", kb_cancel())
        elif action == "👁 Показать API":
            ak = bot.get("api_key", "") or "Не задан"
            sk = bot.get("secret_key", "")
            vis = (sk[:8] + "..." + sk[-4:]) if len(sk) > 12 else "Не задан"
            await self._send(update,
                f"🔗 <b>Binance API</b>\n\n"
                f"API Key:\n<code>{ak}</code>\n\n"
                f"Secret:\n<code>{vis}</code>",
                kb_api_manage()
            )
        elif action == "🗑 Удалить API":
            await self.db.update_bot(bot_id, api_key="", secret_key="")
            await self._send(update, "✅ API ключи удалены.", kb_settings())
            self._set_screen(ctx, "settings")

    async def _clone_bot(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id   = self._bot_id(ctx)
        orig     = await self.db.get_bot(bot_id)
        new_name = f"{orig['name']} (копия)"
        new_bot  = await self.db.create_bot(new_name, symbol=orig.get("symbol", "BTCUSDT"))
        await self.db.update_bot(new_bot["id"],
            mode=orig.get("mode", MODE_SIMULATOR),
            order_usdt=orig.get("order_usdt", 50),
            api_key=orig.get("api_key", ""),
            secret_key=orig.get("secret_key", ""),
            theme=orig.get("theme", "dark"),
            daily_report=orig.get("daily_report", 0),
        )
        await self._send(update,
            f"✅ Бот <b>{new_name}</b> создан!\n\n"
            f"Скопировано:\n"
            f"• Режим: {MODE_LABELS.get(orig.get('mode', MODE_SIMULATOR))}\n"
            f"• Сумма ордера: {_usd(orig.get('order_usdt', 50))}\n"
            f"• API: {'✅' if orig.get('api_key') else '❌'}\n\n"
            "💵 Не забудьте пополнить баланс!",
            kb_settings()
        )

    async def _ai_apply_rebalance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id = self._bot_id(ctx)
        rec    = ctx.user_data.pop("ai_rec", {})
        if not rec or rec.get("bot_id") != bot_id:
            await self._send(update, "❌ Рекомендация устарела. Запустите анализ заново.", kb_bot())
            return
        bot    = await self.db.get_bot(bot_id)
        client = self._client(bot)
        nc, ns, nl = rec["center"], rec["speed"], rec["levels"]
        await self.db.update_bot(bot_id, grid_speed=ns, grid_levels=nl, center_price=nc)
        bot = await self.db.get_bot(bot_id)
        placed = await self._place_grid(bot, client, nc, clear_first=True)
        await self._send(update,
            f"✅ <b>Сетка пересоздана</b>\n\n"
            f"📍 Центр:    <code>${nc:,.0f}</code>\n"
            f"⚡ Скорость: <b>×{ns:.2f}</b>\n"
            f"📊 Уровней:  <b>{nl}</b>\n"
            f"📋 Ордеров:  <b>{placed}</b>",
            kb_bot()
        )
        self._set_screen(ctx, "bot")

    async def _show_chart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        bot_id = self._bot_id(ctx)
        bot    = await self.db.get_bot(bot_id)
        # Собираем сделки из обеих таблиц: реальные (trades) и симуляторные (sim_trades)
        sim_trades  = await self.db.get_recent_trades(bot_id, 100)
        real_trades = await self.db.get_trades(bot_id, 100)
        all_trades  = real_trades + sim_trades
        try:
            from chart_generator import ChartGenerator
            buf = ChartGenerator().generate_profit_chart(all_trades, bot["name"])
            await update.message.reply_photo(photo=buf, caption=f"📈 <b>{bot['name']}</b>", parse_mode="HTML")
        except Exception as e:
            await self._send(update, f"❌ Ошибка графика: {e}", kb_bot())

    async def _on_grid_fill(self, bot_id: int, event: dict):
        """Called by GridSimulator when an order fills. Sends Telegram notification."""
        try:
            bot = await self.db.get_bot(bot_id)
            if not bot:
                return
            ev   = event.get('event', '')
            side = '📤 SELL' if ev == 'sell_filled' else '📥 BUY'
            price = event.get('filled_price', 0)
            order_usdt = bot.get('order_usdt', 50)
            qty = order_usdt / price if price else 0
            profit_pct = 0
            if ev == 'sell_filled':
                buy_p = event.get('new_buy', {}).get('price', price)
                profit_pct = ((price - buy_p) / buy_p * 100) if buy_p else 0
            elif ev == 'buy_filled':
                sell_p = event.get('new_sell', {}).get('price', price)
                profit_pct = ((sell_p - price) / price * 100) if price else 0

            text = (
                f"{side} ордер исполнен!\n"
                f"🤖 {bot['name']}\n"
                f"💰 Цена: <code>${price:,.2f}</code>\n"
                f"📈 Прибыль: <b>{profit_pct:+.3f}%</b>\n"
                f"💵 ≈ <b>${profit_pct / 100 * order_usdt:.4f}</b>"
            )
            # Find user_id for this bot — send notification
            for uid, data in (self._app.user_data or {}).items():
                if data.get('bot_id') == bot_id:
                    try:
                        await self._app.bot.send_message(
                            chat_id=uid, text=text,
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass
        except Exception as e:
            import logging as _l
            _l.getLogger(__name__).error(f'_on_grid_fill error: {e}')

    # ── Команды ───────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        name = update.effective_user.first_name
        await self._send(update,
            f"👋 Привет, <b>{name}</b>!\n\n"
            "🤖 <b>BTC Trading Bot</b>\n\n"
            "Управляй торговыми ботами прямо из Telegram.\n"
            "Режимы работы:\n"
            "🔵 <b>Симулятор</b> — без API, виртуальные сделки\n"
            "🟡 <b>Testnet</b> — тест с реальной биржей\n"
            "🔴 <b>Реальный</b> — настоящая торговля\n\n"
            "Выберите действие:",
            kb_main()
        )
        self._set_screen(ctx, "main")

    async def cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self._screen_main(update, ctx)

    # ── Запуск ────────────────────────────────────────────────────────────

    async def run(self):
        await self.db.initialize()

        for bot in await self.db.get_all_bots():
            if bot["status"] == "running" and (bot.get("mode") or MODE_SIMULATOR) == MODE_SIMULATOR:
                await self.simulator.start_bot_simulation(bot["id"], bot.get("center_price") or 100_000.0)

        app = Application.builder().token(BOT_TOKEN).build()
        self._app = app

        await app.bot.set_my_commands([
            BotCommand("start", "Главный экран"),
            BotCommand("menu",  "Открыть меню"),
        ])

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("menu",  self.cmd_menu))
        app.add_handler(CallbackQueryHandler(self.handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        logger.info("Bot started!")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            await asyncio.Event().wait()
        finally:
            await self.grid_sim.stop_all()
            await self.order_monitor.stop_all()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            await self.db.close()