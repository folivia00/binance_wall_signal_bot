from __future__ import annotations

from src.config import AppConfig
from src.pm_agent import PmAgent, Position


def _agent() -> PmAgent:
    return PmAgent(AppConfig())


def test_bias_direction() -> None:
    agent = _agent()

    up = agent.compute_thresholds(mid=101.0, ref=100.0, t_left=600.0, p_up=50.0)
    down = agent.compute_thresholds(mid=99.0, ref=100.0, t_left=600.0, p_up=50.0)

    assert up.enter_long_thr < up.enter_short_thr
    assert down.enter_short_thr < down.enter_long_thr


def test_rev_thr_strict_end() -> None:
    agent = _agent()
    d_bps = 150.0
    ref = 100.0
    mid = ref * (1.0 + d_bps / 10_000.0)

    thr = agent.compute_thresholds(mid=mid, ref=ref, t_left=120.0, p_up=50.0)

    assert thr.rev_thr >= 90.0


def test_exit_easier_when_more_time() -> None:
    agent = _agent()
    ref = 100.0
    mid = 101.5

    thr_more_time = agent.compute_thresholds(mid=mid, ref=ref, t_left=600.0, p_up=50.0)
    thr_less_time = agent.compute_thresholds(mid=mid, ref=ref, t_left=60.0, p_up=50.0)

    assert thr_more_time.exit_thr < thr_less_time.exit_thr


def test_state_machine() -> None:
    agent = _agent()

    enter = agent.step(
        ts=10.0,
        mid=100.0,
        best_bid=99.9,
        best_ask=100.1,
        ref=100.0,
        t_left=700.0,
        p_up=70.0,
        base_raw=0.0,
        base_p_up=50.0,
        shock=0.0,
    )
    assert enter.action == "ENTER_LONG"
    assert agent.position == Position.LONG

    moderate = agent.step(
        ts=20.0,
        mid=100.2,
        best_bid=100.1,
        best_ask=100.3,
        ref=100.0,
        t_left=700.0,
        p_up=40.0,
        base_raw=0.0,
        base_p_up=50.0,
        shock=0.0,
    )
    assert moderate.action == "EXIT_LONG"
    assert moderate.trade_close is not None
    assert agent.position == Position.FLAT

    agent.step(
        ts=40.0,
        mid=100.0,
        best_bid=99.9,
        best_ask=100.1,
        ref=100.0,
        t_left=700.0,
        p_up=70.0,
        base_raw=0.0,
        base_p_up=50.0,
        shock=0.0,
    )
    assert agent.position == Position.LONG

    extreme = agent.step(
        ts=50.0,
        mid=99.7,
        best_bid=99.6,
        best_ask=99.8,
        ref=100.0,
        t_left=700.0,
        p_up=5.0,
        base_raw=0.0,
        base_p_up=50.0,
        shock=0.0,
    )
    assert extreme.action == "REVERSE_TO_SHORT"
    assert extreme.trade_close is not None
    assert agent.position == Position.SHORT
