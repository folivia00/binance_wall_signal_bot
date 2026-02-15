from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.polymarket_scorer import ScoreSnapshot


class Position(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class PmTickSnapshot:
    round_id: str
    ref_price: float
    t_left_sec: float
    d_bps: float
    t_frac: float
    mid: float


@dataclass(frozen=True)
class AgentAction:
    name: str
    reason: str
    rev_thr: float


@dataclass(frozen=True)
class ClosedTrade:
    side: Position
    entry_price: float
    exit_price: float
    entry_ts: float
    exit_ts: float
    pnl: float


@dataclass(frozen=True)
class RevThresholdConfig:
    base_rev_thr: float = 62.0
    distance_coef: float = 8.0
    distance_norm_bps: float = 10.0
    time_coef: float = 10.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calc_rev_threshold(d_bps: float, t_left_sec: float, cfg: RevThresholdConfig) -> float:
    t_frac = clamp(t_left_sec / 900.0, 0.0, 1.0)
    rev_thr = cfg.base_rev_thr + cfg.distance_coef * (d_bps / max(1e-6, cfg.distance_norm_bps)) + cfg.time_coef * (1.0 - t_frac)
    return clamp(rev_thr, 0.0, 98.0)


class PmAgent:
    def __init__(
        self,
        entry_long_thr: float = 60.0,
        entry_short_thr: float = 40.0,
        rev_cfg: RevThresholdConfig | None = None,
    ) -> None:
        self.entry_long_thr = entry_long_thr
        self.entry_short_thr = entry_short_thr
        self.rev_cfg = rev_cfg or RevThresholdConfig()

        self.position = Position.FLAT
        self.entry_price = 0.0
        self.entry_ts = 0.0
        self.closed_trades: list[ClosedTrade] = []
        self.num_reversals = 0
        self.num_trades = 0

    def on_tick(self, snapshot: PmTickSnapshot, score: ScoreSnapshot, ts: float) -> AgentAction:
        p_up = score.p_up
        rev_thr = calc_rev_threshold(snapshot.d_bps, snapshot.t_left_sec, self.rev_cfg)

        if self.position == Position.FLAT:
            if p_up >= self.entry_long_thr:
                self._open(Position.LONG, snapshot.mid, ts)
                return AgentAction("ENTER_LONG", "p_up_high", rev_thr)
            if p_up <= self.entry_short_thr:
                self._open(Position.SHORT, snapshot.mid, ts)
                return AgentAction("ENTER_SHORT", "p_up_low", rev_thr)
            return AgentAction("HOLD", "flat_wait", rev_thr)

        if self.position == Position.LONG:
            if p_up <= 100.0 - rev_thr:
                self._reverse(Position.SHORT, snapshot.mid, ts)
                return AgentAction("REVERSE_TO_SHORT", "strong_reverse_short", rev_thr)
            return AgentAction("HOLD", "hold_long", rev_thr)

        if p_up >= rev_thr:
            self._reverse(Position.LONG, snapshot.mid, ts)
            return AgentAction("REVERSE_TO_LONG", "strong_reverse_long", rev_thr)
        return AgentAction("HOLD", "hold_short", rev_thr)

    def summarize(self, final_mid: float | None = None, final_ts: float | None = None) -> dict[str, float | int]:
        closed = list(self.closed_trades)
        pseudo_pnl = sum(trade.pnl for trade in closed)

        if self.position != Position.FLAT and final_mid is not None and final_ts is not None:
            side_mult = 1.0 if self.position == Position.LONG else -1.0
            pseudo_pnl += (final_mid - self.entry_price) * side_mult

        avg_hold = sum(t.exit_ts - t.entry_ts for t in closed) / len(closed) if closed else 0.0
        wins = sum(1 for t in closed if t.pnl > 0)
        win_rate_like = wins / len(closed) if closed else 0.0

        return {
            "num_trades": self.num_trades,
            "num_reversals": self.num_reversals,
            "pseudo_pnl": round(pseudo_pnl, 8),
            "avg_hold_time": round(avg_hold, 4),
            "win_rate_like": round(win_rate_like, 4),
        }

    def _open(self, side: Position, price: float, ts: float) -> None:
        self.position = side
        self.entry_price = price
        self.entry_ts = ts
        self.num_trades += 1

    def _reverse(self, new_side: Position, price: float, ts: float) -> None:
        side_mult = 1.0 if self.position == Position.LONG else -1.0
        pnl = (price - self.entry_price) * side_mult
        self.closed_trades.append(
            ClosedTrade(
                side=self.position,
                entry_price=self.entry_price,
                exit_price=price,
                entry_ts=self.entry_ts,
                exit_ts=ts,
                pnl=pnl,
            )
        )
        self.num_reversals += 1
        self._open(new_side, price, ts)
