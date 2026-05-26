"""
handlers/bot_handler.py — Redesigned Telegram menu

Навигационная иерархия:
  🏠 Главная (дашборд)
   ├── ➕ Создать бота
   ├── 📊 Общая статистика
   └── [Бот N] ──────────────────── Карточка бота
        ├── ▶️ / ⏸  Старт / Стоп
        ├── 💵 Пополнить          → выбор суммы
        ├── 📋 Ордера             → список сетки
        ├── 📈 Статистика         → прибыль / сделки
        ├── 📊 График             → chart image
        ├── ⚙️ Настройки ────────── Настройки бота
        │    ├── 🖥 Режим
        │    ├── 💲 Сумма ордера
        │    ├── 🔑 Binance API
        │    ├── 🎨 Тема
        │    ├── ⏰ Дневной отчёт
        │    ├── 📝 Переименовать
        │    └── 🔄 Сброс данных
        └── 📋 / 🗑  Дублировать / Удалить

Принципы:
  - Каждый экран знает где он находится (хлебная крошка в заголовке)
  - Кнопка «назад» всегда есть и всегда ведёт на 1 уровень вверх
  - Все экраны редактируют то же сообщение (in-place), чат не засоряется
  - Ввод текста: пользовательское сообщение сразу удаляется
  - ReplyKeyboard не используется — только InlineKeyboard
"""

import logging
from datetime import datetime, timedelta
from typing import Dict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from database import DatabaseManager
from config import is_user_allowed
from models import Withdrawal

logger = logging.getLogger(__name__)

# per-user state: {"awaiting": str, "bot_id": int, ...}
_state: Dict[int, dict] = {}


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return "$0.00"


def _pct(v) -> str:
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "+0.00%"


def _bar(value: float, total: float, length: int = 10) -> str:
    filled = min(length, int(round(value / max(total, 0.01) * length)))
    return "█" * filled + "░" * (length - filled)


def _since(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(str(dt_str))
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return str(dt_str)[:10]


# ─── Keyboard builder ─────────────────────────────────────────────────────────

def kb(*rows: list) -> InlineKeyboardMarkup:
    """Build InlineKeyboardMarkup from rows of (label, callback_data) tuples."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t, callback_data=d) for t, d in row]
        for row in rows
    ])


# ─── Edit-or-send helper ──────────────────────────────────────────────────────

async def _show(update: Update, text: str, markup: InlineKeyboardMarkup):
    """Edit the existing message in-place; send a new one only if needed."""
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            await update.callback_query.get_bot().send_message(
                update.callback_query.message.chat_id,
                text, reply_markup=markup, parse_mode="HTML",
            )
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="HTML"
        )


# ─── Mode constants ───────────────────────────────────────────────────────────

MODE_SIM  = "simulator"
MODE_TEST = "testnet"
MODE_REAL = "real"

MODE_LABEL = {
    MODE_SIM:  "🔵 Симулятор",
    MODE_TEST: "🟡 Testnet",
    MODE_REAL: "🔴 Реальный",
}
MODE_ICON = {MODE_SIM: "🔵", MODE_TEST: "🟡", MODE_REAL: "🔴"}


# ─── Bot ─────────────────────────────────────────────────────────────────────

class TradingTelegramBot:

    def __init__(self, token: str, db_manager: DatabaseManager):
        self.token = token
        self.db    = db_manager

    async def build_application(self) -> Application:
        app = Application.builder().token(self.token).build()

        await app.bot.set_my_commands([
            BotCommand("start", "Главный экран"),
            BotCommand("menu",  "Открыть меню"),
        ])

        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("menu",  self._cmd_menu))
        app.add_handler(CallbackQueryHandler(self._on_button))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._on_text
        ))
        return app

    # ─── Commands ──────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_user_allowed(update.effective_user.id):
            await update.message.reply_text("⛔ Нет доступа.")
            return
        name = update.effective_user.first_name
        await update.message.reply_text(
            f"👋 Привет, <b>{name}</b>!\n\n"
            "Добро пожаловать в BTC Grid Trading Bot.\n"
            "Всё управление — через кнопки ниже. 👇",
            parse_mode="HTML",
        )
        await self._screen_home(update)

    async def _cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self._screen_home(update)

    # ─── Callback router ───────────────────────────────────────────────────

    async def _on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        p  = q.data.split(":")
        a  = p[0]
        id_ = int(p[1]) if len(p) > 1 and p[1].lstrip("-").isdigit() else None

        # ── Level 0: Home ──────────────────────────────────────────────────
        if   a == "home":               await self._screen_home(update)
        elif a == "overall":            await self._screen_overall(update)

        # ── Level 1: Create bot ────────────────────────────────────────────
        elif a == "new_bot":
            _state[q.from_user.id] = {"awaiting": "bot_name"}
            await _show(update,
                "➕ <b>Новый бот</b>\n\nВведите имя:",
                kb([("✖ Отмена", "home")]),
            )

        # ── Level 1: Bot card ──────────────────────────────────────────────
        elif a == "bot":                await self._screen_bot(update, id_)
        elif a == "start_bot":          await self._do_start(update, ctx, id_)
        elif a == "stop_bot":           await self._do_stop(update, id_)

        # Deposit
        elif a == "deposit":
            await _show(update,
                f"💵 <b>Пополнить</b> — {await self._bot_name(id_)}\n\n"
                f"Баланс: <b>{_usd((await self.db.get_bot(id_))['balance'])}</b>\n\n"
                "Выберите сумму или введите свою:",
                InlineKeyboardMarkup([
                    [("100 USDT",   f"dep_q:{id_}:100"),
                     ("500 USDT",   f"dep_q:{id_}:500")],
                    [("1 000 USDT", f"dep_q:{id_}:1000"),
                     ("5 000 USDT", f"dep_q:{id_}:5000")],
                    [("✏️ Своя сумма", f"dep_c:{id_}"),
                     ("◀ Назад",        f"bot:{id_}")],
                ]),
            )
        elif a == "dep_q":
            await self._do_deposit(update, int(p[1]), float(p[2]))
        elif a == "dep_c":
            _state[q.from_user.id] = {"awaiting": "deposit", "bot_id": id_}
            await _show(update,
                "💵 Введите сумму в USDT:",
                kb([("◀ Отмена", f"bot:{id_}")]),
            )

        # Withdraw (global, from overall screen)
        elif a == "withdrawal":
            _state[q.from_user.id] = {"awaiting": "withdrawal"}
            await _show(update,
                "💸 <b>Записать вывод средств</b>\n\nВведите сумму в USD:",
                kb([("◀ Отмена", "overall")]),
            )

        # Orders
        elif a == "orders":             await self._screen_orders(update, id_)

        # Stats
        elif a == "stats":              await self._screen_stats(update, id_)

        # Chart
        elif a == "chart":              await self._screen_chart(update, id_)

        # Settings
        elif a == "settings":           await self._screen_settings(update, id_)
        elif a == "set_mode":           await self._screen_set_mode(update, id_)
        elif a == "mode":               await self._do_set_mode(update, id_, p[2])
        elif a == "set_order":          await self._screen_set_order(update, id_)
        elif a == "order_q":            await self._do_set_order(update, int(p[1]), float(p[2]))
        elif a == "order_c":
            _state[q.from_user.id] = {"awaiting": "order_amt", "bot_id": id_}
            await _show(update,
                "💲 Введите сумму ордера в USDT:",
                kb([("◀ Отмена", f"settings:{id_}")]),
            )
        elif a == "set_api":            await self._screen_set_api(update, id_)
        elif a == "api_change":
            _state[q.from_user.id] = {"awaiting": "api_key", "bot_id": id_}
            await _show(update,
                "🔑 Введите новый <b>API Key</b>:",
                kb([("◀ Отмена", f"settings:{id_}")]),
            )
        elif a == "api_del":
            await self.db.update_bot(id_, api_key="", secret_key="")
            await _show(update,
                "✅ API ключи удалены.",
                kb([("◀ Настройки", f"settings:{id_}")]),
            )
        elif a == "set_theme":          await self._screen_set_theme(update, id_)
        elif a == "theme":              await self._do_set_theme(update, id_, p[2])
        elif a == "toggle_report":      await self._do_toggle_report(update, id_)
        elif a == "rename":
            _state[q.from_user.id] = {"awaiting": "rename", "bot_id": id_}
            await _show(update,
                "📝 Введите новое имя бота:",
                kb([("◀ Отмена", f"settings:{id_}")]),
            )
        elif a == "reset_confirm":      await self._screen_reset_confirm(update, id_)
        elif a == "reset_do":           await self._do_reset(update, id_)

        # Clone / Delete
        elif a == "clone":              await self._do_clone(update, id_)
        elif a == "del_confirm":        await self._screen_del_confirm(update, id_)
        elif a == "del_do":             await self._do_delete(update, id_)

    # ─── Text input ────────────────────────────────────────────────────────

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid   = update.effective_user.id
        state = _state.pop(uid, None)
        text  = update.message.text.strip()

        # Always delete user message to keep chat clean
        try:
            await update.message.delete()
        except Exception:
            pass

        if not state:
            await self._screen_home(update)
            return

        action = state.get("awaiting")
        bot_id = state.get("bot_id")

        if action == "bot_name":
            bot = await self.db.create_bot(text)
            await _show(update,
                f"✅ Бот <b>{text}</b> создан!\n\n"
                "Следующие шаги:\n"
                "  1. 💵 Пополните баланс\n"
                "  2. ⚙️ Выберите режим\n"
                "  3. ▶️ Запустите",
                kb(
                    [("Открыть бота", f"bot:{bot['id']}")],
                    [("◀ На главную",  "home")],
                ),
            )

        elif action == "deposit":
            try:
                await self._do_deposit(update, bot_id, float(text.replace(",", ".")))
            except ValueError:
                await _show(update,
                    "❌ Некорректная сумма. Введите число, например: <code>250</code>",
                    kb([("◀ Отмена", f"bot:{bot_id}")]),
                )

        elif action == "order_amt":
            try:
                v = float(text.replace(",", "."))
                if v <= 0:
                    raise ValueError
                await self.db.update_bot(bot_id, order_usdt=v)
                await _show(update,
                    f"✅ Размер ордера: <b>{_usd(v)}</b>",
                    kb([("◀ Настройки", f"settings:{bot_id}")]),
                )
            except ValueError:
                await _show(update,
                    "❌ Некорректная сумма.",
                    kb([("◀ Отмена", f"settings:{bot_id}")]),
                )

        elif action == "rename":
            await self.db.update_bot(bot_id, name=text)
            await _show(update,
                f"✅ Переименован: <b>{text}</b>",
                kb([("◀ Настройки", f"settings:{bot_id}")]),
            )

        elif action == "api_key":
            _state[uid] = {"awaiting": "api_secret",
                           "bot_id": bot_id, "_api_key": text}
            await _show(update,
                "🔑 Введите <b>Secret Key</b>:",
                kb([("◀ Отмена", f"settings:{bot_id}")]),
            )

        elif action == "api_secret":
            api_key = state.get("_api_key", "")
            await self.db.update_bot(bot_id, api_key=api_key, secret_key=text)
            await _show(update,
                "✅ API ключи сохранены!",
                kb([("◀ Настройки", f"settings:{bot_id}")]),
            )

        elif action == "withdrawal":
            try:
                amount = float(text.replace(",", "."))
                if amount <= 0:
                    raise ValueError
                await self.db.create_withdrawal(Withdrawal(amount=amount))
                await _show(update,
                    f"✅ Вывод <b>{_usd(amount)}</b> записан.",
                    kb([("◀ Статистика", "overall")]),
                )
            except ValueError:
                await _show(update,
                    "❌ Некорректная сумма.",
                    kb([("◀ Отмена", "overall")]),
                )

        else:
            await self._screen_home(update)

    # ═══════════════════════════════════════════════════════════════════════
    # SCREENS
    # ═══════════════════════════════════════════════════════════════════════

    # ── 🏠 Home ────────────────────────────────────────────────────────────

    async def _screen_home(self, update: Update):
        bots = await self.db.get_all_bots()
        now  = datetime.now()

        total_balance = sum(b["balance"] for b in bots)
        profit_day = profit_total = 0.0
        for b in bots:
            profit_day   += await self.db.get_profit_since(b["id"], now - timedelta(days=1))
            profit_total += await self.db.get_total_profit(b["id"])
        running = sum(1 for b in bots if b["status"] == "running")

        # Header
        lines = [
            "🏠 <b>BTC Grid Trading Bot</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        if bots:
            lines += [
                f"💼 Баланс:       <b>{_usd(total_balance)}</b>",
                f"💹 Прибыль 24ч:  <b>{_usd(profit_day)}</b>",
                f"📈 Всего:        <b>{_usd(profit_total)}</b>",
                f"🤖 Работает:     <b>{running}</b> из {len(bots)}",
                "",
            ]
            for b in bots:
                icon = "🟢" if b["status"] == "running" else "⚪"
                m    = MODE_ICON.get(b.get("mode") or MODE_SIM, "🔵")
                prf  = await self.db.get_total_profit(b["id"])
                lines.append(
                    f"  {icon}{m} <b>{b['name']}</b>"
                    f"  {_usd(b['balance'])}  <i>+{_usd(prf)}</i>"
                )
        else:
            lines += [
                "",
                "Ботов нет. Нажмите <b>➕ Создать</b> чтобы начать.",
            ]

        # Buttons: one per bot, then actions
        bot_btns = [
            [(
                f"{'🟢' if b['status']=='running' else '⚪'}"
                f"{MODE_ICON.get(b.get('mode') or MODE_SIM, '🔵')} "
                f"{b['name']}",
                f"bot:{b['id']}"
            )]
            for b in bots
        ]

        markup = InlineKeyboardMarkup(
            bot_btns + [
                [("➕ Создать бота", "new_bot"),
                 ("📊 Общая статистика", "overall")],
                [("🔄 Обновить", "home")],
            ]
        )
        await _show(update, "\n".join(lines), markup)

    # ── 📊 Overall stats ───────────────────────────────────────────────────

    async def _screen_overall(self, update: Update):
        bots = await self.db.get_all_bots()
        now  = datetime.now()
        p_d = p_w = p_m = p_y = p_t = 0.0
        for b in bots:
            p_d += await self.db.get_profit_since(b["id"], now - timedelta(days=1))
            p_w += await self.db.get_profit_since(b["id"], now - timedelta(weeks=1))
            p_m += await self.db.get_profit_since(b["id"], now - timedelta(days=30))
            p_y += await self.db.get_profit_since(b["id"], now - timedelta(days=365))
            p_t += await self.db.get_total_profit(b["id"])

        wd  = await self.db.get_total_withdrawals()
        net = p_t - wd
        running   = sum(1 for b in bots if b["status"] == "running")
        total_bal = sum(b["balance"] for b in bots)

        lines = [
            "📊 <b>Общая статистика</b>",
            f"<i>🏠 Главная  /  Статистика</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🤖 Ботов: <b>{len(bots)}</b>  (🟢 {running} работает)",
            f"💼 Суммарный баланс: <b>{_usd(total_bal)}</b>",
            "",
            "💹 <b>Прибыль:</b>",
            f"   24 часа:  <b>{_usd(p_d)}</b>",
            f"   7 дней:   <b>{_usd(p_w)}</b>",
            f"   30 дней:  <b>{_usd(p_m)}</b>",
            f"   Год:      <b>{_usd(p_y)}</b>",
            f"   Всего:    <b>{_usd(p_t)}</b>",
            "",
            f"💸 Выводы:       <b>{_usd(wd)}</b>",
            f"✅ Чистая прибыль: <b>{_usd(net)}</b>",
        ]

        if bots:
            lines.append("")
            lines.append("<b>Боты:</b>")
            for b in bots:
                st  = "🟢" if b["status"] == "running" else "⚪"
                m   = MODE_ICON.get(b.get("mode") or MODE_SIM, "🔵")
                prf = await self.db.get_total_profit(b["id"])
                lines.append(
                    f"  {st}{m} {b['name']}:  "
                    f"{_usd(b['balance'])}  <i>+{_usd(prf)}</i>"
                )

        markup = kb(
            [("💸 Записать вывод", "withdrawal")],
            [("◀ На главную", "home"), ("🔄 Обновить", "overall")],
        )
        await _show(update, "\n".join(lines), markup)

    # ── 🤖 Bot card ────────────────────────────────────────────────────────

    async def _screen_bot(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        if not bot:
            await _show(update, "❌ Бот не найден.",
                        kb([("◀ На главную", "home")]))
            return

        now   = datetime.now()
        p_t   = await self.db.get_total_profit(bot_id)
        p_d   = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        orders = await self.db.get_open_orders(bot_id)
        mode  = bot.get("mode") or MODE_SIM
        bal   = bot["balance"]
        roi   = (p_t / max(bal, 0.01)) * 100

        status_icon = "🟢 Работает" if bot["status"] == "running" else "⚪ Остановлен"
        bar = _bar(max(p_t, 0), max(bal, 0.01))

        text = (
            f"🤖 <b>{bot['name']}</b>\n"
            f"<i>🏠 Главная  /  {bot['name']}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status_icon}  {MODE_LABEL.get(mode)}\n"
            f"\n"
            f"💼 Баланс:    <b>{_usd(bal)}</b>\n"
            f"💹 24ч:       <b>{_usd(p_d)}</b>\n"
            f"📈 Всего:     <b>{_usd(p_t)}</b>  ({roi:+.2f}%)\n"
            f"📊 {bar}\n"
            f"📋 Ордеров:   <b>{len(orders)}</b>"
        )
        if bot.get("center_price"):
            text += f"\n📍 Центр:     <code>${bot['center_price']:,.0f}</code>"

        is_running = bot["status"] == "running"
        run_btn = (("⏸ Остановить", f"stop_bot:{bot_id}")
                   if is_running
                   else ("▶️ Запустить", f"start_bot:{bot_id}"))

        markup = InlineKeyboardMarkup([
            [run_btn,                       ("💵 Пополнить",    f"deposit:{bot_id}")],
            [("📋 Ордера",   f"orders:{bot_id}"),  ("📈 Статистика",  f"stats:{bot_id}")],
            [("📊 График",   f"chart:{bot_id}"),   ("⚙️ Настройки",  f"settings:{bot_id}")],
            [("📋 Дублировать", f"clone:{bot_id}"), ("🗑 Удалить",    f"del_confirm:{bot_id}")],
            [("◀ На главную", "home"),              ("🔄",             f"bot:{bot_id}")],
        ])
        await _show(update, text, markup)

    # ── 📋 Orders ──────────────────────────────────────────────────────────

    async def _screen_orders(self, update: Update, bot_id: int):
        bot    = await self.db.get_bot(bot_id)
        orders = await self.db.get_open_orders(bot_id)
        pairs  = await self.db.get_bot_pairs(bot_id)

        sells = sorted([o for o in orders if o["side"] == "SELL"],
                       key=lambda x: x["price"], reverse=True)
        buys  = sorted([o for o in orders if o["side"] == "BUY"],
                       key=lambda x: x["price"], reverse=True)

        lines = [
            f"📋 <b>Ордера — {bot['name']}</b>",
            f"<i>🏠  /  {bot['name']}  /  Ордера</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if sells:
            lines.append("🔴 <b>SELL</b>")
            for o in sells[:6]:
                lines.append(
                    f"  📤 <code>${o['price']:>10,.0f}</code>  "
                    f"×{o['quantity']:.5f} BTC"
                )
        else:
            lines.append("🔴 <b>SELL:</b> нет")

        center = bot.get("center_price")
        if center:
            lines.append(f"\n  ┄┄ <code>${center:,.0f}</code> (центр) ┄┄\n")

        if buys:
            lines.append("🟢 <b>BUY</b>")
            for o in buys[:6]:
                lines.append(
                    f"  📥 <code>${o['price']:>10,.0f}</code>  "
                    f"×{o['quantity']:.5f} BTC"
                )
        else:
            lines.append("🟢 <b>BUY:</b> нет")

        closed = [p for p in pairs if p["status"] == "CLOSED"]
        open_p = [p for p in pairs if p["status"] != "CLOSED"]
        if pairs:
            lines.append(
                f"\n🔗 Пар: <b>{len(open_p)}</b> открыто"
                f" / <b>{len(closed)}</b> закрыто"
            )
            for p in closed[:4]:
                lines.append(
                    f"  ✅ {p['pair_name']}: "
                    f"<code>${p['buy_price']:,.0f} → ${p['sell_price']:,.0f}</code>"
                    f"  +{_usd(p['profit'])}"
                )

        markup = kb(
            [("🔄 Обновить", f"orders:{bot_id}"),
             ("◀ К боту",    f"bot:{bot_id}")],
        )
        await _show(update, "\n".join(lines), markup)

    # ── 📈 Stats ───────────────────────────────────────────────────────────

    async def _screen_stats(self, update: Update, bot_id: int):
        bot    = await self.db.get_bot(bot_id)
        now    = datetime.now()
        p_d    = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        p_w    = await self.db.get_profit_since(bot_id, now - timedelta(weeks=1))
        p_m    = await self.db.get_profit_since(bot_id, now - timedelta(days=30))
        p_y    = await self.db.get_profit_since(bot_id, now - timedelta(days=365))
        p_t    = await self.db.get_total_profit(bot_id)
        trades = await self.db.get_recent_trades(bot_id, 6)

        bal  = bot["balance"]
        roi  = (p_t / max(bal, 0.01)) * 100
        mode = bot.get("mode") or MODE_SIM

        lines = [
            f"📈 <b>Статистика — {bot['name']}</b>",
            f"<i>🏠  /  {bot['name']}  /  Статистика</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"{'🟢 Работает' if bot['status']=='running' else '⚪ Остановлен'}"
            f"  {MODE_LABEL.get(mode)}",
            "",
            f"💼 Баланс: <b>{_usd(bal)}</b>    ROI: <b>{roi:+.2f}%</b>",
            "",
            "💹 <b>Прибыль:</b>",
            f"   24 часа:  <b>{_usd(p_d)}</b>",
            f"   7 дней:   <b>{_usd(p_w)}</b>",
            f"   30 дней:  <b>{_usd(p_m)}</b>",
            f"   Год:      <b>{_usd(p_y)}</b>",
            f"   Всего:    <b>{_usd(p_t)}</b>",
        ]

        if bot.get("center_price"):
            lines.append(f"\n📍 Центр сетки: <code>${bot['center_price']:,.0f}</code>")
        lines.append(f"💲 Ордер: <b>{_usd(bot.get('order_usdt', 50))}</b>")

        if trades:
            lines.append("\n📜 <b>Последние сделки:</b>")
            for t in trades:
                lines.append(
                    f"  {_since(t['executed_at'])}  "
                    f"<b>+{_usd(t['profit'])}</b>  "
                    f"<i>{_pct(t['profit_percent'])}</i>"
                )
        else:
            lines.append("\n<i>Сделок пока нет — запустите бота</i>")

        markup = kb(
            [("📊 График",   f"chart:{bot_id}"),
             ("📋 Ордера",   f"orders:{bot_id}")],
            [("🔄 Обновить", f"stats:{bot_id}"),
             ("◀ К боту",   f"bot:{bot_id}")],
        )
        await _show(update, "\n".join(lines), markup)

    # ── 📊 Chart ───────────────────────────────────────────────────────────

    async def _screen_chart(self, update: Update, bot_id: int):
        bot    = await self.db.get_bot(bot_id)
        trades = await self.db.get_recent_trades(bot_id, 100)
        try:
            from chart_generator import ChartGenerator
            buf = ChartGenerator().generate_profit_chart(trades, bot["name"])
            if update.callback_query:
                await update.callback_query.message.reply_photo(
                    photo=buf,
                    caption=f"📊 <b>{bot['name']}</b>",
                    parse_mode="HTML",
                )
        except ImportError:
            await _show(update,
                "❌ Для графиков нужен matplotlib:\n<code>pip install matplotlib</code>",
                kb([("◀ К боту", f"bot:{bot_id}")]),
            )
        except Exception as e:
            logger.error(f"Chart error: {e}")
            await _show(update,
                f"❌ Ошибка графика: {e}",
                kb([("◀ К боту", f"bot:{bot_id}")]),
            )

    # ── ⚙️ Settings ────────────────────────────────────────────────────────

    async def _screen_settings(self, update: Update, bot_id: int):
        bot        = await self.db.get_bot(bot_id)
        mode       = bot.get("mode") or MODE_SIM
        theme      = bot.get("theme") or "dark"
        dr         = "✅" if bot.get("daily_report") else "❌"
        has_api    = bool(bot.get("api_key"))
        order_usdt = bot.get("order_usdt") or 50

        text = (
            f"⚙️ <b>Настройки — {bot['name']}</b>\n"
            f"<i>🏠  /  {bot['name']}  /  Настройки</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🖥 Режим:         <b>{MODE_LABEL.get(mode)}</b>\n"
            f"💲 Размер ордера: <b>{_usd(order_usdt)}</b>\n"
            f"🔑 API ключи:     {'✅ заданы' if has_api else '❌ не заданы'}\n"
            f"🎨 Тема:          <b>{theme}</b>\n"
            f"⏰ Дневной отчёт: {dr}\n"
        )

        markup = InlineKeyboardMarkup([
            [("🖥 Режим",         f"set_mode:{bot_id}"),
             ("💲 Размер ордера", f"set_order:{bot_id}")],
            [("🔑 Binance API",   f"set_api:{bot_id}"),
             ("🎨 Тема",          f"set_theme:{bot_id}")],
            [("⏰ Отчёт: " + dr,  f"toggle_report:{bot_id}"),
             ("📝 Переименовать", f"rename:{bot_id}")],
            [("🔄 Сброс данных",  f"reset_confirm:{bot_id}")],
            [("◀ К боту",         f"bot:{bot_id}")],
        ])
        await _show(update, text, markup)

    async def _screen_set_mode(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        cur = bot.get("mode") or MODE_SIM

        modes = [
            (MODE_SIM,  "🔵 Симулятор",      "без API, виртуальные сделки"),
            (MODE_TEST, "🟡 Binance Testnet", "ключи от testnet.binancefuture.com"),
            (MODE_REAL, "🔴 Реальный",        "настоящие деньги ⚠️"),
        ]
        rows = [
            [(
                f"{icon}{' ✓' if key == cur else ''}  {desc}",
                f"mode:{bot_id}:{key}"
            )]
            for key, icon, desc in modes
        ]
        rows.append([("◀ Назад", f"settings:{bot_id}")])

        await _show(update,
            f"🖥 <b>Режим работы</b>\n"
            f"<i>🏠  /  {bot['name']}  /  Настройки  /  Режим</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Текущий: <b>{MODE_LABEL.get(cur)}</b>",
            InlineKeyboardMarkup(rows),
        )

    async def _screen_set_order(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        markup = InlineKeyboardMarkup([
            [("10 USDT",  f"order_q:{bot_id}:10"),
             ("25 USDT",  f"order_q:{bot_id}:25")],
            [("50 USDT",  f"order_q:{bot_id}:50"),
             ("100 USDT", f"order_q:{bot_id}:100")],
            [("✏️ Своя сумма", f"order_c:{bot_id}"),
             ("◀ Назад",       f"settings:{bot_id}")],
        ])
        await _show(update,
            f"💲 <b>Размер ордера</b>\n"
            f"<i>🏠  /  {bot['name']}  /  Настройки  /  Размер</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Текущий: <b>{_usd(bot.get('order_usdt', 50))}</b>",
            markup,
        )

    async def _screen_set_api(self, update: Update, bot_id: int):
        bot     = await self.db.get_bot(bot_id)
        has_api = bool(bot.get("api_key"))

        if has_api:
            ak  = bot.get("api_key", "")
            sk  = bot.get("secret_key", "")
            vis = (sk[:6] + "…" + sk[-4:]) if len(sk) > 10 else "—"
            markup = InlineKeyboardMarkup([
                [("🔑 Изменить ключи", f"api_change:{bot_id}"),
                 ("🗑 Удалить API",    f"api_del:{bot_id}")],
                [("◀ Назад", f"settings:{bot_id}")],
            ])
            text = (
                f"🔑 <b>Binance API</b>\n"
                f"<i>🏠  /  {bot['name']}  /  Настройки  /  API</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"API Key:\n<code>{ak}</code>\n\n"
                f"Secret:\n<code>{vis}</code>"
            )
        else:
            _state[update.callback_query.from_user.id] = {
                "awaiting": "api_key", "bot_id": bot_id
            }
            markup = kb([("◀ Отмена", f"settings:{bot_id}")])
            text = (
                f"🔑 <b>Подключение API</b>\n"
                f"<i>🏠  /  {bot['name']}  /  Настройки  /  API</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Testnet: <code>testnet.binancefuture.com</code>\n"
                "Real:    <code>binance.com → API Management</code>\n\n"
                "Введите <b>API Key</b>:"
            )
        await _show(update, text, markup)

    async def _screen_set_theme(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        cur = bot.get("theme") or "dark"
        themes = [
            ("dark",   "🌙 Тёмная"),
            ("light",  "☀️ Светлая"),
            ("purple", "💜 Фиолетовая"),
            ("blue",   "🌊 Синяя"),
        ]
        rows = [
            [(f"{label}{' ✓' if key == cur else ''}", f"theme:{bot_id}:{key}")]
            for key, label in themes
        ]
        rows.append([("◀ Назад", f"settings:{bot_id}")])
        await _show(update,
            f"🎨 <b>Тема оформления</b>\n"
            f"<i>🏠  /  {bot['name']}  /  Настройки  /  Тема</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Текущая: <b>{cur}</b>",
            InlineKeyboardMarkup(rows),
        )

    async def _screen_reset_confirm(self, update: Update, bot_id: int):
        bot    = await self.db.get_bot(bot_id)
        orders = await self.db.get_open_orders(bot_id)
        profit = await self.db.get_total_profit(bot_id)
        await _show(update,
            f"⚠️ <b>Сброс данных — {bot['name']}</b>\n\n"
            f"Будет удалено:\n"
            f"  • <b>{len(orders)}</b> ордеров\n"
            f"  • Вся история сделок\n"
            f"  • Прибыль: <b>{_usd(profit)}</b>\n\n"
            "Баланс и настройки сохранятся.",
            kb(
                [("✅ Сбросить", f"reset_do:{bot_id}"),
                 ("❌ Отмена",   f"settings:{bot_id}")],
            ),
        )

    async def _screen_del_confirm(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        await _show(update,
            f"⚠️ Удалить <b>{bot['name']}</b>?\n\n"
            "Все ордера, сделки и настройки будут удалены.",
            kb(
                [("✅ Удалить", f"del_do:{bot_id}"),
                 ("❌ Отмена",  f"bot:{bot_id}")],
            ),
        )

    # ═══════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ═══════════════════════════════════════════════════════════════════════

    async def _do_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, bot_id: int):
        """Delegate to main TradingBot if available, else fallback."""
        # The main TradingBot (bot.py) handles this via "start_bot" callback.
        # Here we just update status — actual grid placement is in bot.py.
        bot = await self.db.get_bot(bot_id)
        if not bot:
            return
        if bot["balance"] <= 0:
            await _show(update,
                "❌ Баланс нулевой.\nСначала пополните через 💵 Пополнить.",
                kb([("◀ К боту", f"bot:{bot_id}")]),
            )
            return
        # Signal running — bot.py monitors this
        await self.db.update_bot(bot_id, status="running")
        await _show(update,
            f"✅ <b>{bot['name']}</b> запущен!",
            kb([("◀ К боту", f"bot:{bot_id}")]),
        )

    async def _do_stop(self, update: Update, bot_id: int):
        bot = await self.db.get_bot(bot_id)
        await self.db.update_bot(bot_id, status="stopped")
        await _show(update,
            f"⏸ <b>{bot['name']}</b> остановлен.",
            kb([("◀ К боту", f"bot:{bot_id}")]),
        )

    async def _do_deposit(self, update: Update, bot_id: int, amount: float):
        if amount <= 0:
            raise ValueError("amount must be positive")
        bot = await self.db.get_bot(bot_id)
        await self.db.add_deposit(bot_id, amount)
        new_bal = (bot["balance"] or 0) + amount
        await _show(update,
            f"✅ Пополнено <b>+{_usd(amount)}</b>\n"
            f"Новый баланс: <b>{_usd(new_bal)}</b>",
            kb([("◀ К боту", f"bot:{bot_id}")]),
        )

    async def _do_set_mode(self, update: Update, bot_id: int, mode: str):
        await self.db.update_bot(bot_id, mode=mode)
        warn = "\n\n⚠️ Реальные деньги! Убедитесь в правильности API ключей." \
               if mode == MODE_REAL else ""
        await _show(update,
            f"✅ Режим: <b>{MODE_LABEL[mode]}</b>{warn}",
            kb([("◀ Настройки", f"settings:{bot_id}")]),
        )

    async def _do_set_order(self, update: Update, bot_id: int, amount: float):
        await self.db.update_bot(bot_id, order_usdt=amount)
        await _show(update,
            f"✅ Размер ордера: <b>{_usd(amount)}</b>",
            kb([("◀ Настройки", f"settings:{bot_id}")]),
        )

    async def _do_set_theme(self, update: Update, bot_id: int, theme: str):
        await self.db.update_bot(bot_id, theme=theme)
        await _show(update,
            f"✅ Тема: <b>{theme}</b>",
            kb([("◀ Настройки", f"settings:{bot_id}")]),
        )

    async def _do_toggle_report(self, update: Update, bot_id: int):
        bot   = await self.db.get_bot(bot_id)
        new_v = not bool(bot.get("daily_report"))
        await self.db.update_bot(bot_id, daily_report=int(new_v))
        status = "включён ✅" if new_v else "выключен ❌"
        await _show(update,
            f"⏰ Дневной отчёт {status}.",
            kb([("◀ Настройки", f"settings:{bot_id}")]),
        )

    async def _do_clone(self, update: Update, orig_id: int):
        orig     = await self.db.get_bot(orig_id)
        new_name = f"{orig['name']} (копия)"
        new_bot  = await self.db.create_bot(new_name, symbol=orig.get("symbol", "BTCUSDT"))
        await self.db.update_bot(
            new_bot["id"],
            mode=orig.get("mode", MODE_SIM),
            order_usdt=orig.get("order_usdt", 50),
            api_key=orig.get("api_key", ""),
            secret_key=orig.get("secret_key", ""),
            theme=orig.get("theme", "dark"),
            daily_report=orig.get("daily_report", 0),
        )
        await _show(update,
            f"✅ Скопирован как <b>{new_name}</b>.\n"
            "💵 Не забудьте пополнить баланс!",
            kb(
                [("Открыть копию", f"bot:{new_bot['id']}")],
                [("◀ На главную",  "home")],
            ),
        )

    async def _do_delete(self, update: Update, bot_id: int):
        bot  = await self.db.get_bot(bot_id)
        name = bot["name"]
        await self.db.delete_bot(bot_id)
        await _show(update,
            f"🗑 Бот <b>{name}</b> удалён.",
            kb([("◀ На главную", "home")]),
        )

    async def _do_reset(self, update: Update, bot_id: int):
        await self.db.reset_bot_stats(bot_id)
        await _show(update,
            "✅ <b>Данные сброшены.</b>\n"
            "Нажмите ▶️ Запустить чтобы начать заново.",
            kb([("◀ К боту", f"bot:{bot_id}")]),
        )

    # ─── Utility ───────────────────────────────────────────────────────────

    async def _bot_name(self, bot_id: int) -> str:
        bot = await self.db.get_bot(bot_id)
        return bot["name"] if bot else str(bot_id)
