from __future__ import annotations

from src.pm_agent import PmAgent, PmTickSnapshot, RevThresholdConfig, calc_rev_threshold
from src.polymarket_scorer import ScoreSnapshot


def _score(p_up: float) -> ScoreSnapshot:
    return ScoreSnapshot(
        p_up=p_up,
        p_down=100.0 - p_up,
        base_raw=0.0,
        base_p_up=p_up,
        shock_value=0.0,
        ref_price=0.0,
        round_id="",
        pressure_breakdown=[],
    )


def _snap(t_left_sec: float = 900.0, d_bps: float = 0.0, mid: float = 100.0) -> PmTickSnapshot:
    return PmTickSnapshot(round_id="0", ref_price=100.0, t_left_sec=t_left_sec, d_bps=d_bps, t_frac=t_left_sec / 900.0, mid=mid)


def test_rev_threshold_grows_with_distance_and_time_pressure() -> None:
    cfg = RevThresholdConfig(base_rev_thr=60.0, distance_coef=10.0, distance_norm_bps=10.0, time_coef=12.0)
    near_early = calc_rev_threshold(d_bps=1.0, t_left_sec=900.0, cfg=cfg)
    far_early = calc_rev_threshold(d_bps=20.0, t_left_sec=900.0, cfg=cfg)
    near_late = calc_rev_threshold(d_bps=1.0, t_left_sec=30.0, cfg=cfg)

    assert far_early > near_early
    assert near_late > near_early


def test_enter_long_when_probability_high() -> None:
    agent = PmAgent(entry_long_thr=60.0, entry_short_thr=40.0)
    action = agent.on_tick(_snap(), _score(72.0), ts=1.0)

    assert action.name == "ENTER_LONG"
    assert agent.position.value == "LONG"


def test_no_reverse_when_signal_not_strong_enough_under_stress() -> None:
    agent = PmAgent(entry_long_thr=60.0, entry_short_thr=40.0)
    agent.on_tick(_snap(), _score(75.0), ts=1.0)

    stressed = _snap(t_left_sec=30.0, d_bps=35.0, mid=99.8)
    action = agent.on_tick(stressed, _score(20.0), ts=2.0)

    assert action.name == "HOLD"
    assert agent.position.value == "LONG"


def test_reverse_triggers_when_threshold_is_met() -> None:
    agent = PmAgent(entry_long_thr=60.0, entry_short_thr=40.0)
    agent.on_tick(_snap(), _score(75.0), ts=1.0)

    relaxed = _snap(t_left_sec=850.0, d_bps=0.5, mid=99.5)
    action = agent.on_tick(relaxed, _score(18.0), ts=2.0)

    assert action.name == "REVERSE_TO_SHORT"
    assert agent.position.value == "SHORT"
