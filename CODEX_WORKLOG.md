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
