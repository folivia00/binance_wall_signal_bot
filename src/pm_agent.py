from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.config import AppConfig


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PmAgent:
    def __init__(self, cfg: AppConfig | None = None) -> None:
        app_cfg = cfg or AppConfig()
        self.base_enter = app_cfg.pm_base_enter
        self.base_exit = app_cfg.pm_base_exit
        self.base_rev = app_cfg.pm_base_rev
        self.d0_bps = app_cfg.pm_d0_bps

        self.bias_k = app_cfg.pm_bias_k
        self.bias_m = app_cfg.pm_bias_m
        self.bias_max = app_cfg.pm_bias_bmax

        self.exit_a = app_cfg.pm_exit_a
        self.exit_b = app_cfg.pm_exit_b

        self.rev_a = app_cfg.pm_rev_a
        self.rev_b = app_cfg.pm_rev_b

        self.cooldown_sec = app_cfg.pm_cooldown_sec

        self.position = Position.FLAT
        self.entry_price = 0.0
        self.entry_ts = 0.0
        self.cooldown_until = 0.0

        self.round_pnl = 0.0
        self.total_pnl = 0.0
        self.trades_count = 0
        self.reversals_count = 0

    def force_flat(self) -> None:
        self.position = Position.FLAT
        self.entry_price = 0.0
        self.entry_ts = 0.0

    def reset_round(self) -> None:
        self.round_pnl = 0.0
        self.force_flat()

    def compute_thresholds(self, mid: float, ref: float, t_left: float, p_up: float) -> Thresholds:
        _ = p_up
        d_signed_bps = 0.0
        if ref > 0:
            d_signed_bps = (mid - ref) / ref * 10_000.0
        d_bps = abs(d_signed_bps)
        t_frac = clamp(t_left / 900.0, 0.0, 1.0)

        bias = clamp(self.bias_k * (d_bps / max(1e-6, self.d0_bps)) + self.bias_m * (1.0 - t_frac), 0.0, self.bias_max)

        if mid >= ref:
            enter_long_thr = self.base_enter - bias
            enter_short_thr = self.base_enter + bias
        else:
            enter_long_thr = self.base_enter + bias
            enter_short_thr = self.base_enter - bias

        exit_thr = self.base_exit + self.exit_a * (d_bps / max(1e-6, self.d0_bps)) - self.exit_b * t_frac
        rev_thr = self.base_rev + self.rev_a * (d_bps / max(1e-6, self.d0_bps)) + self.rev_b * (1.0 - t_frac)

        return Thresholds(
            enter_long_thr=clamp(enter_long_thr, 0.0, 100.0),
            enter_short_thr=clamp(enter_short_thr, 0.0, 100.0),
            exit_thr=clamp(exit_thr, 0.0, 100.0),
            rev_thr=clamp(rev_thr, 0.0, 100.0),
            bias=bias,
            d_bps=d_bps,
            d_signed_bps=d_signed_bps,
            t_frac=t_frac,
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
    ) -> StepResult:
        _ = (best_bid, best_ask, base_raw, base_p_up, shock)
        thresholds = self.compute_thresholds(mid=mid, ref=ref, t_left=t_left, p_up=p_up)
        s_dn = 100.0 - p_up

        if self.position == Position.FLAT:
            if ts < self.cooldown_until:
                return StepResult("HOLD", "cooldown", thresholds, None)
            if p_up >= thresholds.enter_long_thr:
                self._open(Position.LONG, mid, ts)
                return StepResult("ENTER_LONG", "p_up>=enter_long_thr", thresholds, None)
            if s_dn >= thresholds.enter_short_thr:
                self._open(Position.SHORT, mid, ts)
                return StepResult("ENTER_SHORT", "p_down>=enter_short_thr", thresholds, None)
            return StepResult("HOLD", "flat_wait", thresholds, None)

        if self.position == Position.LONG:
            if s_dn >= thresholds.rev_thr:
                trade_close = self._close(mid, ts, kind="REVERSE_TO_SHORT")
                self._open(Position.SHORT, mid, ts)
                self.reversals_count += 1
                return StepResult("REVERSE_TO_SHORT", "p_down>=rev_thr", thresholds, trade_close)
            if s_dn >= thresholds.exit_thr:
                trade_close = self._close(mid, ts, kind="EXIT_LONG")
                self.cooldown_until = ts + self.cooldown_sec
                return StepResult("EXIT_LONG", "p_down>=exit_thr", thresholds, trade_close)
            return StepResult("HOLD", "hold_long", thresholds, None)

        if p_up >= thresholds.rev_thr:
            trade_close = self._close(mid, ts, kind="REVERSE_TO_LONG")
            self._open(Position.LONG, mid, ts)
            self.reversals_count += 1
            return StepResult("REVERSE_TO_LONG", "p_up>=rev_thr", thresholds, trade_close)
        if p_up >= thresholds.exit_thr:
            trade_close = self._close(mid, ts, kind="EXIT_SHORT")
            self.cooldown_until = ts + self.cooldown_sec
            return StepResult("EXIT_SHORT", "p_up>=exit_thr", thresholds, trade_close)
        return StepResult("HOLD", "hold_short", thresholds, None)

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
