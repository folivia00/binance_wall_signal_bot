from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path


from src.config import AppConfig
from src.detectors import DetectorOutput


class Position(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class Thresholds:
    enter_long_thr: float
    enter_short_thr: float
    exit_thr: float
    rev_thr: float
    bias: float
    d_bps: float
    d_signed_bps: float
    t_frac: float
    rev_need: float


@dataclass(frozen=True)
class TradeClose:
    side: Position
    entry_price: float
    exit_price: float
    entry_ts: float
    exit_ts: float
    pnl: float
    kind: str


@dataclass(frozen=True)
class StepResult:
    action: str
    reason: str
    thresholds: Thresholds
    trade_close: TradeClose | None
    p_up: float
    phase: str


@dataclass(frozen=True)
class OutcomePhase:
    enter_delta: float = 0.0
    rev_delta: float = 0.0
    detector_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class OutcomeConfig:
    base_enter: float
    base_rev: float
    k: float
    m: float
    a: float
    b: float
    d0: float
    bmax: float
    min_edge: float
    min_reverse_tleft: float
    no_entry_last_seconds: float
    max_entries_per_round: int
    max_reversals_per_round: int
    allow_exit_flat: bool
    allow_stay_flat: bool
    phase_modifiers: dict[str, OutcomePhase]

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> OutcomeConfig:
        data = _parse_simple_yaml(Path(path).read_text(encoding="utf-8"))
        modifiers: dict[str, OutcomePhase] = {}
        for name in ("early", "mid", "end"):
            raw = data.get("phase_modifiers", {}).get(name, {})
            modifiers[name] = OutcomePhase(
                enter_delta=float(raw.get("enter_delta", 0.0)),
                rev_delta=float(raw.get("rev_delta", 0.0)),
                detector_weights={str(k): float(v) for k, v in raw.get("detector_weights", {}).items()},
            )

        return cls(
            base_enter=float(data["base_enter"]),
            base_rev=float(data["base_rev"]),
            k=float(data["K"]),
            m=float(data["M"]),
            a=float(data["A"]),
            b=float(data["B"]),
            d0=float(data["D0"]),
            bmax=float(data["Bmax"]),
            min_edge=float(data["MIN_EDGE"]),
            min_reverse_tleft=float(data["MIN_REVERSE_TLEFT"]),
            no_entry_last_seconds=float(data["NO_ENTRY_LAST_SECONDS"]),
            max_entries_per_round=int(data["MAX_ENTRIES_PER_ROUND"]),
            max_reversals_per_round=int(data["MAX_REVERSALS_PER_ROUND"]),
            allow_exit_flat=bool(data["ALLOW_EXIT_FLAT"]),
            allow_stay_flat=bool(data["ALLOW_STAY_FLAT"]),
            phase_modifiers=modifiers,
        )


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _coerce_scalar(raw: str) -> float | int | bool | str:
    value = raw.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        key, _, value = line.partition(":")
        key = key.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        if value.strip() == "":
            current[key] = {}
            stack.append((indent, current[key]))
            continue

        current[key] = _coerce_scalar(value.strip())

    return root


class PmAgent:
    def __init__(self, cfg: AppConfig | None = None) -> None:
        app_cfg = cfg or AppConfig()
        self.agent_mode = app_cfg.agent_mode
        self.position = Position.FLAT
        self.entry_price = 0.0
        self.entry_ts = 0.0

        self.round_pnl = 0.0
        self.total_pnl = 0.0
        self.trades_count = 0
        self.reversals_count = 0

        self.entries_used = 0
        self.reversals_used = 0
        self.entry_time: float | None = None
        self.reverse_time: float | None = None
        self.distance_at_entry: float | None = None
        self.distance_at_reverse: float | None = None
        self.p_up_at_entry: float | None = None
        self.p_up_at_reverse: float | None = None

        if self.agent_mode == "outcome":
            self.outcome_cfg = OutcomeConfig.from_file(app_cfg.outcome_config_path)
        else:
            self.outcome_cfg = None

    def force_flat(self) -> None:
        self.position = Position.FLAT
        self.entry_price = 0.0
        self.entry_ts = 0.0

    def reset_round(self) -> None:
        self.round_pnl = 0.0
        self.force_flat()
        self.entries_used = 0
        self.reversals_used = 0
        self.entry_time = None
        self.reverse_time = None
        self.distance_at_entry = None
        self.distance_at_reverse = None
        self.p_up_at_entry = None
        self.p_up_at_reverse = None

    def get_phase(self, t_left: float) -> str:
        if t_left > 600:
            return "early"
        if t_left > 180:
            return "mid"
        return "end"

    def aggregate_p_up(self, components: list[DetectorOutput], phase: str) -> float:
        if not components:
            return 50.0

        phase_cfg = self.outcome_cfg.phase_modifiers.get(phase, OutcomePhase()) if self.outcome_cfg else OutcomePhase()
        weighted_sum = 0.0
        weights = 0.0
        for comp in components:
            phase_weight = phase_cfg.detector_weights.get(comp.name, 1.0)
            w = comp.normalized_confidence() * max(0.0, phase_weight)
            weighted_sum += comp.normalized_component() * w
            weights += w

        if weights <= 1e-9:
            return 50.0
        return clamp(weighted_sum / weights, 0.0, 100.0)

    def compute_thresholds(self, mid: float, ref: float, t_left: float, p_up: float) -> Thresholds:
        _ = p_up
        outcome = self.outcome_cfg
        if outcome is None:
            raise RuntimeError("Outcome mode configuration is required")

        d_signed_bps = ((mid - ref) / ref * 10_000.0) if ref > 0 else 0.0
        d_bps = abs(d_signed_bps)
        t_frac = clamp(t_left / 900.0, 0.0, 1.0)
        phase = self.get_phase(t_left)
        phase_cfg = outcome.phase_modifiers.get(phase, OutcomePhase())

        bias = clamp(outcome.k * (d_bps / max(1e-6, outcome.d0)) + outcome.m * (1.0 - t_frac), 0.0, outcome.bmax)

        base_enter = outcome.base_enter + phase_cfg.enter_delta
        if mid >= ref:
            enter_long_thr = base_enter - bias
            enter_short_thr = base_enter + bias
        else:
            enter_long_thr = base_enter + bias
            enter_short_thr = base_enter - bias

        need = clamp(
            outcome.base_rev
            + phase_cfg.rev_delta
            + outcome.a * (d_bps / max(1e-6, outcome.d0))
            + outcome.b * (1.0 - t_frac),
            75.0,
            98.0,
        )

        exit_thr = clamp(
            (outcome.base_enter + phase_cfg.enter_delta) + 0.5 * bias + 4.0 * (1.0 - t_frac),
            50.0,
            95.0,
        )

        return Thresholds(
            enter_long_thr=clamp(enter_long_thr, 0.0, 100.0),
            enter_short_thr=clamp(enter_short_thr, 0.0, 100.0),
            exit_thr=exit_thr,
            rev_thr=need,
            bias=bias,
            d_bps=d_bps,
            d_signed_bps=d_signed_bps,
            t_frac=t_frac,
            rev_need=need,
        )

    def step(
        self,
        ts: float,
        mid: float,
        best_bid: float,
        best_ask: float,
        ref: float,
        t_left: float,
        p_up: float,
        base_raw: float,
        base_p_up: float,
        shock: float,
        detector_outputs: list[DetectorOutput] | None = None,
    ) -> StepResult:
        _ = (best_bid, best_ask, base_raw, shock)
        phase = self.get_phase(t_left)
        if detector_outputs is None:
            detector_outputs = [DetectorOutput(name="orderbook", p_up_component=base_p_up if base_p_up != 50.0 else p_up, confidence=1.0)]
        p_up = self.aggregate_p_up(detector_outputs, phase)

        thresholds = self.compute_thresholds(mid=mid, ref=ref, t_left=t_left, p_up=p_up)
        p_down = 100.0 - p_up
        outcome = self.outcome_cfg
        assert outcome is not None

        if self.position == Position.FLAT:
            if t_left <= outcome.no_entry_last_seconds:
                return StepResult("HOLD", "no_entry_window", thresholds, None, p_up, phase)
            if self.entries_used >= outcome.max_entries_per_round:
                return StepResult("HOLD", "max_entries_reached", thresholds, None, p_up, phase)
            if p_up >= thresholds.enter_long_thr and p_up >= (50.0 + outcome.min_edge):
                self._open(Position.LONG, mid, ts)
                self.entries_used += 1
                self.entry_time = ts
                self.distance_at_entry = thresholds.d_signed_bps
                self.p_up_at_entry = p_up
                return StepResult("ENTER_LONG", "entry_criteria_met", thresholds, None, p_up, phase)
            if p_down >= thresholds.enter_short_thr and p_down >= (50.0 + outcome.min_edge):
                self._open(Position.SHORT, mid, ts)
                self.entries_used += 1
                self.entry_time = ts
                self.distance_at_entry = thresholds.d_signed_bps
                self.p_up_at_entry = p_up
                return StepResult("ENTER_SHORT", "entry_criteria_met", thresholds, None, p_up, phase)
            return StepResult("HOLD", "flat_wait", thresholds, None, p_up, phase)

        if self.position == Position.LONG:
            if (
                p_down >= thresholds.rev_need
                and t_left > outcome.min_reverse_tleft
                and self.reversals_used < outcome.max_reversals_per_round
            ):
                trade_close = self._close(mid, ts, kind="REVERSE_TO_SHORT")
                self._open(Position.SHORT, mid, ts)
                self.reversals_count += 1
                self.reversals_used += 1
                self.reverse_time = ts
                self.distance_at_reverse = thresholds.d_signed_bps
                self.p_up_at_reverse = p_up
                return StepResult("REVERSE_TO_SHORT", "reverse_criteria_met", thresholds, trade_close, p_up, phase)
            if p_down >= thresholds.exit_thr and t_left > outcome.min_reverse_tleft:
                trade_close = self._close(mid, ts, kind="EXIT_LONG")
                return StepResult("EXIT_TO_FLAT", "exit_criteria_met", thresholds, trade_close, p_up, phase)
            return StepResult("HOLD", "hold_long", thresholds, None, p_up, phase)

        if (
            p_up >= thresholds.rev_need
            and t_left > outcome.min_reverse_tleft
            and self.reversals_used < outcome.max_reversals_per_round
        ):
            trade_close = self._close(mid, ts, kind="REVERSE_TO_LONG")
            self._open(Position.LONG, mid, ts)
            self.reversals_count += 1
            self.reversals_used += 1
            self.reverse_time = ts
            self.distance_at_reverse = thresholds.d_signed_bps
            self.p_up_at_reverse = p_up
            return StepResult("REVERSE_TO_LONG", "reverse_criteria_met", thresholds, trade_close, p_up, phase)
        if p_up >= thresholds.exit_thr and t_left > outcome.min_reverse_tleft:
            trade_close = self._close(mid, ts, kind="EXIT_SHORT")
            return StepResult("EXIT_TO_FLAT", "exit_criteria_met", thresholds, trade_close, p_up, phase)
        return StepResult("HOLD", "hold_short", thresholds, None, p_up, phase)

    def _open(self, side: Position, price: float, ts: float) -> None:
        self.position = side
        self.entry_price = price
        self.entry_ts = ts

    def _close(self, price: float, ts: float, kind: str) -> TradeClose:
        if self.position == Position.LONG:
            pnl = (price - self.entry_price) / max(1e-9, self.entry_price)
        else:
            pnl = (self.entry_price - price) / max(1e-9, self.entry_price)

        trade = TradeClose(
            side=self.position,
            entry_price=self.entry_price,
            exit_price=price,
            entry_ts=self.entry_ts,
            exit_ts=ts,
            pnl=pnl,
            kind=kind,
        )
        self.round_pnl += pnl
        self.total_pnl += pnl
        self.trades_count += 1
        self.force_flat()
        return trade

    def build_tick_log_row(
        self,
        round_id: str,
        ref: float,
        mid: float,
        t_left: float,
        result: StepResult,
    ) -> dict[str, str | float]:
        return {
            "round_id": round_id,
            "ref": ref,
            "mid": mid,
            "t_left": t_left,
            "phase": result.phase,
            "p_up": result.p_up,
            "bias": result.thresholds.bias,
            "enter_long_thr": result.thresholds.enter_long_thr,
            "enter_short_thr": result.thresholds.enter_short_thr,
            "exit_thr": result.thresholds.exit_thr,
            "rev_need": result.thresholds.rev_need,
            "position": self.position.value,
            "action": result.action,
            "reason": result.reason,
        }

    def build_round_summary(self, round_id: str, ref_price: float, close_price: float) -> dict[str, float | int | str | bool | None]:
        true_outcome = "UP" if close_price >= ref_price else "DOWN"
        final_position = self.position.value
        correct = (true_outcome == "UP" and self.position == Position.LONG) or (
            true_outcome == "DOWN" and self.position == Position.SHORT
        )

        summary = {
            "round_id": round_id,
            "ref_price": ref_price,
            "close_price": close_price,
            "true_outcome": true_outcome,
            "final_position": final_position,
            "correct": correct,
            "entry_time": self.entry_time,
            "reverse_time": self.reverse_time,
            "distance_at_entry": self.distance_at_entry,
            "distance_at_reverse": self.distance_at_reverse,
            "p_up_at_entry": self.p_up_at_entry,
            "p_up_at_reverse": self.p_up_at_reverse,
            "accuracy": 1 if correct else 0,
            "round_pnl": self.round_pnl,
            "trades_count": self.trades_count,
            "reversals_count": self.reversals_used,
        }
        return summary

    def summary_json(self, round_id: str, ref_price: float, close_price: float) -> str:
        return json.dumps(self.build_round_summary(round_id, ref_price, close_price), ensure_ascii=False)
