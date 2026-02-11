# binance_wall_signal_bot

Минимальный Python-бот для Binance USDT-M Futures, который отслеживает изменения стакана (`btcusdt@depth@100ms`) и выдаёт сигналы разворота по логике исчезновения крупных стен.

## Что делает

- Подключается к публичному Binance Futures WebSocket (`fstream`).
- Поддерживает мультистрим формат сообщений `{"stream": "...", "data": {...}}`.
- Ведёт локальный топ-стакан по `bids/asks`.
- Ищет стены среди top-N уровней:
  - `qty >= WALL_MULT * median_qty`.
- Ловит событие `wall_drop`, если стена быстро исчезла/сильно уменьшилась:
  - возраст стены `<= EVENT_TTL_SEC`;
  - падение объёма `>= WALL_DROP_PCT` (или уровень пропал из top-N).
- Подтверждает сигнал дисбалансом:
  - `abs(imbalance) >= IMB_THR`,
  - `imbalance = (sum(bids)-sum(asks))/(sum(bids)+sum(asks))`.
- Направление сигнала:
  - `ask wall drop -> LONG`
  - `bid wall drop -> SHORT`
- Считает score:
  - `score = min(100, int(50 + abs(imbalance)*200))`
- Печатает heartbeat раз в 2 секунды (`best bid/ask + imbalance`).
- Пишет всё в `logs/signals.log`.

## Структура

```
binance_wall_signal_bot/
  src/
    main.py
    config.py
    ws_client.py
    orderbook.py
    wall_detector.py
    logger.py
  requirements.txt
  README.md
```

## Запуск

Требования: Python 3.11+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Конфигурация

Все основные параметры вынесены в `src/config.py`:

- `N_LEVELS = 20`
- `WALL_MULT = 5.0`
- `EVENT_TTL_SEC = 2.0`
- `WALL_DROP_PCT = 0.70`
- `IMB_THR = 0.12`
- `HEARTBEAT_INTERVAL_SEC = 2.0`

`aggTrade` поток заложен архитектурно и может быть включён через `ENABLE_AGG_TRADE = True`.

## Примечания

- Боту не нужны API-ключи (только публичные market stream).
- Реализован реконнект с экспоненциальной задержкой при обрыве соединения.
