from __future__ import annotations

from dataclasses import dataclass

from src.pm_agent import clamp


@dataclass(frozen=True)
class RoundState:
    round_id: str
    ref_price: float
    t_left_sec: float
    d_bps: float
    t_frac: float


class PmRoundManager:
    def __init__(self, round_interval_sec: int = 15 * 60) -> None:
        self.round_interval_sec = round_interval_sec
        self.round_id = ""
        self.ref_price = 0.0
        self.round_end_ts = 0.0

    def on_tick(self, mid: float, ts: float) -> RoundState:
        round_start = int(ts // self.round_interval_sec) * self.round_interval_sec
        round_id = str(round_start)
        if round_id != self.round_id:
            self.round_id = round_id
            self.ref_price = mid
            self.round_end_ts = float(round_start + self.round_interval_sec)

        t_left_sec = max(0.0, self.round_end_ts - ts)
        d_bps = 0.0
        if self.ref_price > 0:
            d_bps = abs(mid - self.ref_price) / self.ref_price * 10_000.0
        t_frac = clamp(t_left_sec / self.round_interval_sec, 0.0, 1.0)
        return RoundState(round_id=self.round_id, ref_price=self.ref_price, t_left_sec=t_left_sec, d_bps=d_bps, t_frac=t_frac)
