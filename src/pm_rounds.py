from __future__ import annotations

from dataclasses import dataclass

from src.pm_agent import PmAgent


@dataclass(frozen=True)
class RoundState:
    round_id: int
    ref_price: float
    t_left_sec: float
    is_new_round: bool


class PmRoundManager:
    def __init__(self, interval_sec: int = 15 * 60) -> None:
        self.interval_sec = interval_sec
        self.round_id = -1
        self.ref_price = 0.0
        self.round_end_ts = 0.0

    def on_tick(self, ts: float, mid: float, agent: PmAgent | None = None) -> RoundState:
        round_start = int(ts // self.interval_sec) * self.interval_sec
        is_new_round = round_start != self.round_id
        if is_new_round:
            self.round_id = round_start
            self.ref_price = mid
            self.round_end_ts = float(round_start + self.interval_sec)
            if agent is not None:
                agent.reset_round()

        t_left_sec = max(0.0, self.round_end_ts - ts)
        return RoundState(round_id=self.round_id, ref_price=self.ref_price, t_left_sec=t_left_sec, is_new_round=is_new_round)
