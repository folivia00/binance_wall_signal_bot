from __future__ import annotations

from src.config import AppConfig
from src.pm_agent import PmAgent, Position


def _agent() -> PmAgent:
    return PmAgent(AppConfig(agent_mode="outcome", outcome_config_path="configs/outcome.yaml"))


def test_bias_works_towards_reference() -> None:
    agent = _agent()

    up = agent.compute_thresholds(mid=101.0, ref=100.0, t_left=600.0, p_up=50.0)
    down = agent.compute_thresholds(mid=99.0, ref=100.0, t_left=600.0, p_up=50.0)

    assert up.enter_long_thr < up.enter_short_thr
    assert down.enter_short_thr < down.enter_long_thr


def test_reverse_not_allowed_in_last_seconds() -> None:
    agent = _agent()

    agent.step(10.0, 100.0, 99.9, 100.1, 100.0, 700.0, 90.0, 0.0, 90.0, 0.0)
    assert agent.position == Position.LONG

    res = agent.step(100.0, 99.0, 98.9, 99.1, 100.0, 40.0, 5.0, 0.0, 5.0, 0.0)
    assert res.action == "HOLD"
    assert agent.position == Position.LONG


def test_max_one_entry_per_round() -> None:
    agent = _agent()

    first = agent.step(10.0, 100.0, 99.9, 100.1, 100.0, 700.0, 80.0, 0.0, 80.0, 0.0)
    assert first.action == "ENTER_LONG"

    agent.force_flat()
    second = agent.step(20.0, 100.0, 99.9, 100.1, 100.0, 650.0, 80.0, 0.0, 80.0, 0.0)
    assert second.reason == "max_entries_reached"
    assert agent.position == Position.FLAT


def test_max_one_reverse_per_round() -> None:
    agent = _agent()

    agent.step(10.0, 100.0, 99.9, 100.1, 100.0, 800.0, 90.0, 0.0, 90.0, 0.0)
    r1 = agent.step(20.0, 99.0, 98.9, 99.1, 100.0, 700.0, 1.0, 0.0, 1.0, 0.0)
    assert r1.action == "REVERSE_TO_SHORT"

    r2 = agent.step(30.0, 101.5, 101.4, 101.6, 100.0, 650.0, 99.0, 0.0, 99.0, 0.0)
    assert r2.action == "EXIT_TO_FLAT"
    assert agent.position == Position.FLAT


def test_summary_correct_calculation() -> None:
    agent = _agent()
    agent.step(10.0, 100.0, 99.9, 100.1, 100.0, 800.0, 80.0, 0.0, 80.0, 0.0)

    summary = agent.build_round_summary(round_id="1", ref_price=100.0, close_price=101.0)

    assert summary["true_outcome"] == "UP"
    assert summary["final_position"] == "LONG"
    assert summary["correct"] is True
    assert summary["accuracy"] == 1
