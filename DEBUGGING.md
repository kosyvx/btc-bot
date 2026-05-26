# 🔧 Отладка - Почему не выставляются ордера

## 📝 Проверка логов

### 1. Запустите бота:
```bash
python main.py
```

### 2. В другом терминале смотрите логи в реальном времени:
```bash
tail -f telegram_bot.log
```

### 3. Создайте и запустите бота в Telegram

### 4. В логах найдите:

```
[CLIENT] Bot: BTC Bot 1, Mode: testnet
[CLIENT] API Key: SET / NONE
[CLIENT] Secret Key: SET / NONE
[CLIENT] → Using BinanceTestnetClient / MockBinanceClient

[PLACE_GRID] Bot: BTC Bot 1, Mode: testnet
[PLACE_GRID] Center: $100,000.00, Quantity: 0.0005
[PLACE_GRID] Client type: BinanceTestnetClient / MockBinanceClient

[BUY 1] Placing BUY @ $99,825.00, qty: 0.0005
[BUY 1] Result: {'orderId': 12345, ...}
[BUY 1] ✅ Order ID: 12345
```

---

## ❓ Если видите MockBinanceClient:

### Проблема: Бот использует симулятор вместо Binance!

### Решение:

#### A) Проверьте режим бота:
1. Telegram → выберите бота
2. **⚙️ Настройки** → **🖥 Режим работы**
3. Выберите **🟡 Binance Testnet**

#### B) Добавьте API ключи:
1. **⚙️ Настройки** → **🔗 Binance API**
2. Вставьте API Key
3. Вставьте Secret Key

#### C) Или добавьте в .env:
```env
BINANCE_API_KEY=ваш_ключ
BINANCE_SECRET_KEY=ваш_секрет
```

---

## ❌ Если видите ошибки:

### Ошибка: "No order ID returned!"
```
[BUY 1] ⚠️ No order ID returned!
```

**Причина:** Binance вернул пустой ответ или ошибку

**Проверьте:**
1. API ключи правильные?
2. Есть баланс на Testnet? (https://testnet.binancefuture.com)
3. Правильный символ? (BTCUSDT)

---

### Ошибка: "Exception: ..."
```
[BUY 1] ❌ Exception: Invalid API-key, IP, or permissions for action
```

**Решение:**
1. Проверьте API Key - скопируйте заново
2. Проверьте Secret Key - скопируйте заново
3. Убедитесь что ключи от **Binance Futures TESTNET**

---

### Ошибка: "Signature failed"
```
[BUY 1] ❌ Exception: Signature for this request is not valid
```

**Решение:**
Secret Key неправильный - создайте новые ключи на Testnet

---

## ✅ Если всё правильно, должны видеть:

```log
2026-02-23 15:30:00 - INFO - [CLIENT] Bot: My Bot, Mode: testnet
2026-02-23 15:30:00 - INFO - [CLIENT] API Key: SET
2026-02-23 15:30:00 - INFO - [CLIENT] Secret Key: SET
2026-02-23 15:30:00 - INFO - [CLIENT] → Using BinanceTestnetClient (bot keys)

2026-02-23 15:30:01 - INFO - [PLACE_GRID] Bot: My Bot, Mode: testnet
2026-02-23 15:30:01 - INFO - [PLACE_GRID] Center: $100,234.50, Quantity: 0.0005
2026-02-23 15:30:01 - INFO - [PLACE_GRID] Client type: BinanceTestnetClient

2026-02-23 15:30:01 - INFO - [BUY 1] Placing BUY @ $99,059.25, qty: 0.0005
2026-02-23 15:30:02 - INFO - [BUY 1] Result: {'orderId': 123456789, 'symbol': 'BTCUSDT', ...}
2026-02-23 15:30:02 - INFO - [BUY 1] ✅ Order ID: 123456789

2026-02-23 15:30:02 - INFO - [BUY 2] Placing BUY @ $98,985.00, qty: 0.0005
...
```

---

## 🌐 Проверка на Binance Testnet:

1. Откройте https://testnet.binancefuture.com
2. Login → Orders → Open Orders
3. Должны видеть ваши ордера!

---

## 📊 Полезные команды:

### Смотреть только ошибки:
```bash
grep "ERROR\|❌" telegram_bot.log
```

### Смотреть только успешные ордера:
```bash
grep "✅ Order ID" telegram_bot.log
```

### Смотреть тип клиента:
```bash
grep "Client type:" telegram_bot.log
```

### Последние 50 строк:
```bash
tail -50 telegram_bot.log
```

---

## 🔍 Пошаговая проверка:

1. **Режим бота** → должен быть **testnet** (не simulator!)
2. **API ключи** → должны быть SET в логах
3. **Client type** → должен быть **BinanceTestnetClient**
4. **Order ID** → должен быть номер (не пустая строка)
5. **Binance Web** → ордера видны на бирже

---

**Если всё равно не работает - пришлите лог!** 📝
