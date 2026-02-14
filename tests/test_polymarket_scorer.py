from __future__ import annotations

from src.orderbook import OrderBookState
from src.polymarket_scorer import PolymarketScorer
from src.wall_detector import SignalEvent


def _mk_scorer() -> PolymarketScorer:
    scorer = PolymarketScorer(
        pressure_ranges_bps=(5.0, 10.0, 20.0),
        pressure_weights=(1.0, 0.6, 0.3),
        base_scale=30.0,
        shock_half_life_sec=15.0,
        max_shock=35.0,
        shock_distance_bps_cap=20.0,
        shock_min_age_sec=0.2,
        shock_age_full_sec=1.0,
    )
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
