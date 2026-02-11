# binance_wall_signal_bot

Python-бот для Binance USDT-M Futures, который поддерживает **корректный локальный стакан** (`snapshot + diff updates`) и выдаёт более строгие сигналы по исчезновению крупных стен.

## Что делает

- Подключается к `btcusdt@depth@100ms` (Binance Futures diff depth).
- Перед обработкой сигналов синхронизирует локальный стакан по официальной схеме:
  - буферизует WS события;
  - берёт REST snapshot (`/fapi/v1/depth?limit=1000`);
  - отбрасывает события с `u < lastUpdateId`;
  - стартует применение с первого события, где `U <= lastUpdateId <= u`;
  - дальше применяет дифы строго по цепочке update id (`pu`/`U`/`u`), при разрыве запускает ресинк.
- Ищет стены только в top-N уровнях (`N_LEVELS=100`) и фильтрует:
  - `qty >= max(MIN_WALL_QTY, WALL_MULT * median_qty)`;
  - расстояние до mid не больше `MAX_WALL_DIST_BPS`.
- Генерирует `wall_drop` если объём на **той же цене** в полном локальном стакане упал на `>= WALL_DROP_PCT` в пределах `EVENT_TTL_SEC`.
- Подтверждает направление imbalance:
  - `ask wall drop -> LONG`, только если `imbalance >= IMB_THR`;
  - `bid wall drop -> SHORT`, только если `imbalance <= -IMB_THR`.
- Включает anti-spam:
  - cooldown `SIGNAL_COOLDOWN_SEC` отдельно для LONG/SHORT;
  - максимум 1 сигнал на сторону за тик.
- Пишет heartbeat каждые 2 секунды: `best_bid/best_ask`, `imbalance`, `spread_bps`, число wall-кандидатов.

## Запуск

Требования: Python 3.11+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Конфигурация

Параметры находятся в `src/config.py`:

- `N_LEVELS = 100`
- `WALL_MULT = 5.0`
- `MIN_WALL_QTY = 1.0`
- `MAX_WALL_DIST_BPS = 15.0`
- `EVENT_TTL_SEC = 2.0`
- `WALL_DROP_PCT = 0.70`
- `IMB_THR = 0.12`
- `SIGNAL_COOLDOWN_SEC = 2.0`
- `HEARTBEAT_INTERVAL_SEC = 2.0`

## Примечания

- API-ключи не нужны (только публичный market data stream).
- Реализован реконнект с экспоненциальной задержкой.
- При любом рассинхроне update id запускается пересборка локального стакана.
