## Day/Session 2026-02-14

### Changes
- Added `src/polymarket_scorer.py` with `PolymarketScorer` and `ScoreSnapshot` for continuous `p_up/p_down` scoring.
- Extended `src/config.py` with scorer and round-manager parameters (range bps, weights, half-life, shock caps, round interval).
- Integrated scorer into `src/main.py`:
  - 15-minute round reference management (`round_id`, `ref_price`),
  - event-driven shock updates,
  - heartbeat logging for `p_up/p_down`, `base_raw`, and `shock`.
- Added unit tests in `tests/test_polymarket_scorer.py`.
- Added live smoke runner `scripts/live_smoke_scorer.py` for 1-2 minute runtime checks.

### Rationale
- Baseline pressure uses weighted bps bands (5/10/20 bps with 1.0/0.6/0.3) to prioritize near-reference liquidity.
- Base mapping `50 + raw*30` keeps the base signal bounded and not too jumpy.
- Shock events map to signed values by side/type and are scaled by distance from reference plus wall age to reduce spoof sensitivity.
- Exponential half-life decay (15s default) avoids persistent bias from old events while preserving short-term momentum.

### How to test
- `python -m pytest -q`
- `python scripts/live_smoke_scorer.py --duration 90`
- `python -m src.main`

### Notes
- Risk: if reference source uses mid during spread spikes, short-term ref drift can impact score symmetry.
- Risk: distance/age multipliers are heuristic and should be calibrated on replay/live samples.
- Improvement ideas: integrate mark price as optional reference source, persist per-round analytics, add confidence metric from liquidity depth quality.
- Known issues / TODO:
  - Add deterministic tests for distance and age multipliers.
  - Add replay backtest harness for event-to-outcome calibration.
  - Consider protecting `on_wall_event`/`on_orderbook_update` ordering with explicit event timestamps in runner.

## Session 2026-02-14 v2

### Какие файлы менял
- `src/polymarket_scorer.py`
- `src/wall_detector.py`
- `src/main.py`
- `src/config.py`
- `tests/test_polymarket_scorer.py`

### Почему ref drift и почему raw events
- `base_raw` теперь не клипуется в ±1 из-за «уехавшего» `ref_price`: добавлен blend-центр (`mid/ref`) и минимальный порог ликвидности `min_depth_sum`.
- Добавлен quality-gate глубины: при недостаточной суммарной взвешенной глубине база возвращается к `0.0` и отдаёт диагностику `depth_ok/depth_sum`.
- Wall events для скорера развязаны с imbalance-гейтом: детектор возвращает `events_trade` (как раньше, gated) и `events_raw` (для shock, без imbalance/cooldown, но с TTL/age/touch фильтрами).

### Новые конфиги / профили
- Скорер:
  - `base_center_mode` (`ref|mid|blend`)
  - `base_ref_weight`
  - `min_depth_sum`
  - `shock_distance_mode` (`ref|mid|blend`)
  - `shock_full_remove`, `shock_major_drop`, `shock_drop`
- Профили:
  - `balanced`: `base_scale=30`, `shock=12/7/4`, `half_life=15`, `min_depth_sum=1.0`, `base_ref_weight=0.3`
  - `strict`: `base_scale=20`, `shock=8/5/2`, `half_life=10`, `min_depth_sum=2.0`, `base_ref_weight=0.2`

### Команды тестов
- `PYTHONPATH=. pytest -q`

### Известные риски / параметры для калибровки
- В blend-режиме итог чувствителен к `base_ref_weight`; для разных рынков значение может отличаться.
- При очень редком стакане `min_depth_sum` может часто прибивать базу к нулю — для low-liquidity рынков порог нужно снижать.
- Raw events теперь «съедают» стенку сразу после детекта drop/remove; если нужен повторный сигнал от того же уровня, потребуется отдельная логика re-arm.

## Session 2026-02-14 v3

### Что сделал
- Добавил `requirements-dev.txt` с `pytest` (и включением `requirements.txt`) для явной dev-установки тестовых зависимостей.
- Обновил `README.md`:
  - добавил Windows-инструкции для `PROFILE=strict` (CMD / PowerShell / Git Bash);
  - добавил раздел `Tests` с командами установки dev-зависимостей и запуска `python -m pytest -q`;
  - зафиксировал выбор отдельного dev-файла вместо добавления `pytest` в runtime-зависимости.
- Обновил `scripts/live_smoke_scorer.py`:
  - подавил шумное завершение по `CancelledError` внутри async-runner;
  - добавил перехват `KeyboardInterrupt` в `main()`, чтобы прерывание завершалось тихо с кодом 0.

### Почему
- `pytest` нужен только для разработки/CI, поэтому вынесен в `requirements-dev.txt`, чтобы не раздувать production-окружение бота.
- Live smoke должен быть операционно «тихим» при ручном stop/timeout; traceback на Ctrl+C мешает чистому smoke-проходу.

### Команды проверки
- `python -m venv .venv --system-site-packages`
- `source .venv/bin/activate && python -m pytest -q`
- `source .venv/bin/activate && python scripts/live_smoke_scorer.py --duration 2`
- Проверка SIGINT через subprocess (send_signal SIGINT) для `scripts/live_smoke_scorer.py`.

### Риски / TODO
- В офлайн-средах `pip install -r requirements-dev.txt` может не проходить без локального индекса/кэша (это ограничение окружения, не кода).
- При необходимости можно добавить `constraints.txt`/pin версий для полной воспроизводимости CI.
