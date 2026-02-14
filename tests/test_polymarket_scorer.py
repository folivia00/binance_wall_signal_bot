from __future__ import annotations

from src.orderbook import OrderBookState
from src.polymarket_scorer import PolymarketScorer
from src.wall_detector import SignalEvent, WallDetector


def _mk_scorer(**overrides: float | str) -> PolymarketScorer:
    kwargs: dict[str, float | str | tuple[float, ...]] = {
        "pressure_ranges_bps": (5.0, 10.0, 20.0),
        "pressure_weights": (1.0, 0.6, 0.3),
        "base_scale": 30.0,
        "shock_half_life_sec": 15.0,
        "max_shock": 35.0,
        "shock_distance_bps_cap": 20.0,
        "shock_min_age_sec": 0.2,
        "shock_age_full_sec": 1.0,
        "min_depth_sum": 1.0,
        "base_center_mode": "blend",
        "base_ref_weight": 0.3,
        "shock_distance_mode": "blend",
        "shock_full_remove": 12.0,
        "shock_major_drop": 7.0,
        "shock_drop": 4.0,
    }
    kwargs.update(overrides)
    scorer = PolymarketScorer(**kwargs)
    scorer.set_reference(price=100.0, ts=0.0, round_id="0")
    return scorer


def _mk_event(side: str, event_type: str, price: float, age_sec: float = 1.2) -> SignalEvent:
    return SignalEvent(
        ts=0.0,
        side=side,
        direction="LONG" if side == "ask" else "SHORT",
        price=price,
        old_qty=10.0,
        current_qty=0.0,
        drop_pct=1.0,
        imbalance=0.2,
        score=90,
        dist_bps=1.0,
        touch_bps=1.0,
        age_sec=age_sec,
        best_bid=99.9,
        best_ask=100.1,
        full_remove=event_type == "FULL_REMOVE",
        event_type=event_type,
    )


def test_pressure_balanced() -> None:
    scorer = _mk_scorer()
    state = OrderBookState(
        bids=[(99.95, 10.0), (99.90, 10.0), (99.80, 10.0)],
        asks=[(100.05, 10.0), (100.10, 10.0), (100.20, 10.0)],
    )
    score = scorer.on_orderbook_update(state, ts=1.0)
    assert 49.0 <= score.p_up <= 51.0
    assert 49.0 <= score.p_down <= 51.0


def test_pressure_buy_dominant() -> None:
    scorer = _mk_scorer()
    state = OrderBookState(
        bids=[(99.95, 40.0), (99.90, 35.0), (99.80, 20.0)],
        asks=[(100.05, 5.0), (100.10, 4.0), (100.20, 2.0)],
    )
    score = scorer.on_orderbook_update(state, ts=1.0)
    assert score.p_up > 50.0
    assert score.base_raw > 0.0


def test_base_depth_too_low_returns_zero_raw() -> None:
    scorer = _mk_scorer(min_depth_sum=10.0)
    state = OrderBookState(
        bids=[(99.95, 0.2)],
        asks=[(100.05, 0.2)],
    )
    score = scorer.on_orderbook_update(state, ts=1.0)
    assert score.base_raw == 0.0
    assert score.pressure_breakdown[-1]["depth_ok"] is False


def test_base_blend_reduces_extremes() -> None:
    state = OrderBookState(
        bids=[(99.99, 20.0), (99.95, 15.0)],
        asks=[(100.25, 20.0), (100.30, 15.0)],
    )
    ref_scorer = _mk_scorer(base_center_mode="ref")
    blend_scorer = _mk_scorer(base_center_mode="blend", base_ref_weight=0.3)

    ref_score = ref_scorer.on_orderbook_update(state, ts=1.0)
    blend_score = blend_scorer.on_orderbook_update(state, ts=1.0)
    assert abs(blend_score.base_raw) < abs(ref_score.base_raw)


def test_wall_remove_ask_increases_up() -> None:
    scorer = _mk_scorer()
    state = OrderBookState(
        bids=[(99.95, 10.0)],
        asks=[(100.05, 10.0)],
    )
    before = scorer.on_orderbook_update(state, ts=1.0)
    scorer.on_wall_event(_mk_event(side="ask", event_type="FULL_REMOVE", price=100.05), ts=1.1)
    after = scorer.on_orderbook_update(state, ts=1.1)
    assert after.p_up > before.p_up


def test_shock_decay() -> None:
    scorer = _mk_scorer()
    state = OrderBookState(
        bids=[(99.95, 10.0)],
        asks=[(100.05, 10.0)],
    )
    base = scorer.on_orderbook_update(state, ts=1.0)
    scorer.on_wall_event(_mk_event(side="ask", event_type="FULL_REMOVE", price=100.05), ts=1.1)
    shocked = scorer.on_orderbook_update(state, ts=1.1)
    decayed = scorer.on_orderbook_update(state, ts=80.0)
    assert shocked.p_up > base.p_up
    assert abs(decayed.p_up - base.p_up) < 0.3


def test_raw_events_trigger_shock_even_if_imbalance_bad() -> None:
    detector = WallDetector(
        n_levels=5,
        wall_mult=1.0,
        min_wall_qty=5.0,
        max_wall_dist_bps=50.0,
        event_ttl_sec=5.0,
        wall_drop_pct=0.9,
        imb_thr=0.2,
        signal_cooldown_sec=10.0,
        max_touch_bps=5.0,
        price_cooldown_sec=60.0,
        price_bucket=0.1,
        full_remove_eps=1e-6,
        only_full_remove=False,
        major_drop_min_pct=0.95,
        min_touch_bps=0.0,
        min_wall_age_sec=0.0,
        global_cooldown_sec=0.0,
    )

    state = OrderBookState(
        bids=[(99.9, 5.0), (99.8, 5.0)],
        asks=[(100.1, 12.0), (100.2, 10.0)],
    )
    detector.process(state, lambda side, price: next((qty for p, qty in (state.bids if side == "bid" else state.asks) if p == price), 0.0))

    removed_state = OrderBookState(
        bids=[(99.9, 5.0), (99.8, 5.0)],
        asks=[(100.1, 0.0), (100.2, 10.0)],
    )

    scorer = _mk_scorer()
    scorer.on_orderbook_update(OrderBookState(bids=[(99.95, 10.0)], asks=[(100.05, 10.0)]), ts=1.0)

    trade_events, raw_events, *_ = detector.process(
        removed_state,
        lambda side, price: next((qty for p, qty in (removed_state.bids if side == "bid" else removed_state.asks) if p == price), 0.0),
    )

    assert not trade_events
    assert raw_events
    before = scorer.on_orderbook_update(OrderBookState(bids=[(99.95, 10.0)], asks=[(100.05, 10.0)]), ts=1.1)
    scorer.on_wall_event(raw_events[0], ts=1.1)
    after = scorer.on_orderbook_update(OrderBookState(bids=[(99.95, 10.0)], asks=[(100.05, 10.0)]), ts=1.1)
    assert after.p_up != before.p_up
