"""
ai_engine.py — ИИ на Google Gemini 2.0 Flash.
Ключ бесплатно: https://aistudio.google.com/app/apikey
Лимит бесплатного плана: 15 запросов/мин, 1500/день — этого хватает.
"""
import asyncio
import json
import os
import re
import logging
import aiohttp
import time
from typing import Optional

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# Защита от превышения лимита
_last_request_time = 0.0
_MIN_INTERVAL = 5.0  # минимум 5 сек между запросами


async def _ask(prompt: str, system: str = "", key: str = "") -> str:
    global _last_request_time

    k = key or os.getenv("GEMINI_API_KEY", "")
    if not k:
        return "❌ GEMINI_API_KEY не задан в .env\nПолучи бесплатно: https://aistudio.google.com/app/apikey"

    # Пауза если запросы идут слишком часто
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - elapsed)

    contents = []
    if system:
        contents.append({"role": "user",  "parts": [{"text": system}]})
        contents.append({"role": "model", "parts": [{"text": "Понял."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    body = {
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{GEMINI_URL}?key={k}", json=body,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                _last_request_time = time.time()

                if r.status == 429:
                    logger.warning("Gemini 429 — лимит, ждём 60 сек")
                    await asyncio.sleep(60)
                    async with s.post(
                        f"{GEMINI_URL}?key={k}", json=body,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as r2:
                        if r2.status != 200:
                            return f"❌ Gemini лимит исчерпан. Попробуй через 1 минуту. (статус {r2.status})"
                        d = await r2.json()
                        return d["candidates"][0]["content"]["parts"][0]["text"].strip()

                if r.status == 404:
                    return "❌ Модель Gemini не найдена. Проверь ключ на aistudio.google.com"
                if r.status != 200:
                    txt = await r.text()
                    return f"❌ Gemini ошибка {r.status}: {txt[:150]}"

                d = await r.json()
                return d["candidates"][0]["content"]["parts"][0]["text"].strip()

    except aiohttp.ClientConnectorError:
        return "❌ Нет соединения с интернетом"
    except Exception as e:
        logger.error(f"Gemini: {e}")
        return f"❌ Ошибка: {e}"


def _context(bot, orders, trades, profit_total, profit_day, price=None) -> str:
    buys  = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]
    lines = [
        f"Бот: {bot['name']} | Статус: {bot['status']} | Баланс: ${float(bot['balance']):.2f}",
        f"Прибыль за 24ч: ${profit_day:.2f} | Всего: ${profit_total:.2f}",
        f"Размер ордера: ${float(bot.get('order_usdt', 50)):.0f} USDT | Уровней: {bot.get('grid_levels', 5)}",
        f"Открытых ордеров: BUY={len(buys)}, SELL={len(sells)}",
    ]
    if price:
        lines.append(f"Текущая цена BTC: ${price:,.0f}")
    if trades:
        avg = sum(float(t["profit"]) for t in trades if t.get("profit")) / max(len(trades), 1)
        lines.append(f"Последних сделок: {len(trades)} | Средняя прибыль: ${avg:.4f}")
    return "\n".join(lines)


SYS_TRADER = (
    "Ты крипто-трейдер, специалист по grid trading BTC/USDT на фьючерсах Binance. "
    "Отвечай ТОЛЬКО на русском языке. Будь краток — максимум 5 предложений. "
    "В конце ОБЯЗАТЕЛЬНО верни блок ```json {...}```."
)

SYS_CHAT = (
    "Ты ИИ-ассистент трейдера. Знаешь весь контекст его BTC бота. "
    "Отвечай на русском, коротко и по делу."
)


async def analyse_and_rebalance(
    bot, orders, trades, profit_total, profit_day, current_price,
    user_note="", api_key=""
) -> dict:
    ctx = _context(bot, orders, trades, profit_total, profit_day, current_price)
    note = f"\nЗаметка: {user_note}" if user_note else ""
    prompt = (
        f"{ctx}{note}\n\n"
        "Проанализируй сетку (2-3 предложения), затем верни JSON:\n"
        "```json\n"
        "{\"new_center\": <цена>, \"new_speed\": <0.5-4.0>, "
        "\"new_levels\": <3-10>, \"action\": \"rebalance|keep|stop\", "
        "\"reason\": \"одно предложение\"}\n```"
    )
    raw = await _ask(prompt, SYS_TRADER, api_key)
    result = {
        "analysis":   raw,
        "new_center": current_price,
        "new_speed":  float(bot.get("grid_speed", 1.0)),
        "new_levels": int(bot.get("grid_levels", 5)),
        "action":     "keep",
        "reason":     "",
    }
    try:
        m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            j = json.loads(m.group(1))
            result["new_center"] = float(j.get("new_center", current_price))
            result["new_speed"]  = float(j.get("new_speed",  result["new_speed"]))
            result["new_levels"] = int(j.get("new_levels",   result["new_levels"]))
            result["action"]     = j.get("action", "keep")
            result["reason"]     = j.get("reason", "")
            result["analysis"]   = raw[:m.start()].strip()
    except Exception as e:
        logger.error(f"AI JSON parse: {e}")
    return result


async def chat(
    bot, orders, trades, profit_total, profit_day, current_price,
    user_message, history, api_key=""
) -> str:
    ctx  = _context(bot, orders, trades, profit_total, profit_day, current_price)
    hist = ""
    for m in history[-4:]:
        role = "Трейдер" if m["role"] == "user" else "ИИ"
        hist += f"{role}: {m['text']}\n"
    prompt = f"Контекст:\n{ctx}\n\n{hist}Трейдер: {user_message}"
    return await _ask(prompt, SYS_CHAT, api_key)


async def suggest_grid(current_price: float, balance: float, api_key="") -> str:
    prompt = (
        f"Цена BTC: ${current_price:,.0f}, баланс: ${balance:.0f} USDT.\n"
        "Дай конкретные параметры для grid-бота: размер ордера, уровней, стратегия. До 100 слов."
    )
    return await _ask(prompt, SYS_TRADER, api_key)
