from __future__ import annotations

from dataclasses import dataclass
from statistics import median
import time

from src.orderbook import OrderBookState


@dataclass
class WallInfo:
    qty: float
    first_seen_ts: float


@dataclass
class SignalEvent:
    ts: float
    side: str
    direction: str
    price: float
    wall_qty: float
    current_qty: float
    drop_pct: float
    imbalance: float
    score: int


class WallDetector:
    def __init__(self, n_levels: int, wall_mult: float, event_ttl_sec: float, wall_drop_pct: float, imb_thr: float) -> None:
        self.n_levels = n_levels
        self.wall_mult = wall_mult
        self.event_ttl_sec = event_ttl_sec
        self.wall_drop_pct = wall_drop_pct
        self.imb_thr = imb_thr
        self.walls: dict[str, dict[float, WallInfo]] = {"bid": {}, "ask": {}}

    def process(self, state: OrderBookState) -> tuple[list[SignalEvent], float]:
        now = time.time()
        bids = state.bids[: self.n_levels]
        asks = state.asks[: self.n_levels]

        bid_map = {price: qty for price, qty in bids}
        ask_map = {price: qty for price, qty in asks}

        bid_median = median([qty for _, qty in bids]) if bids else 0.0
        ask_median = median([qty for _, qty in asks]) if asks else 0.0

        self._track_new_walls("bid", bid_map, bid_median, now)
        self._track_new_walls("ask", ask_map, ask_median, now)

        imbalance = _calc_imbalance(bids, asks)
        events: list[SignalEvent] = []
        events.extend(self._check_drops("bid", bid_map, imbalance, now))
        events.extend(self._check_drops("ask", ask_map, imbalance, now))
        return events, imbalance

    def _track_new_walls(self, side: str, levels: dict[float, float], median_qty: float, now: float) -> None:
        if median_qty <= 0:
            return

        threshold = self.wall_mult * median_qty
        side_walls = self.walls[side]
        for price, qty in levels.items():
            if qty >= threshold and price not in side_walls:
                side_walls[price] = WallInfo(qty=qty, first_seen_ts=now)

    def _check_drops(self, side: str, levels: dict[float, float], imbalance: float, now: float) -> list[SignalEvent]:
        side_walls = self.walls[side]
        events: list[SignalEvent] = []

        for price, info in list(side_walls.items()):
            age = now - info.first_seen_ts
            if age > self.event_ttl_sec:
                side_walls.pop(price, None)
                continue

            current_qty = levels.get(price, 0.0)
            if info.qty <= 0:
                continue

            drop_pct = (info.qty - current_qty) / info.qty
            if drop_pct < self.wall_drop_pct:
                continue

            if abs(imbalance) < self.imb_thr:
                side_walls.pop(price, None)
                continue

            direction = "SHORT" if side == "bid" else "LONG"
            score = min(100, int(50 + abs(imbalance) * 200))
            events.append(
                SignalEvent(
                    ts=now,
                    side=side,
                    direction=direction,
                    price=price,
                    wall_qty=info.qty,
                    current_qty=current_qty,
                    drop_pct=drop_pct,
                    imbalance=imbalance,
                    score=score,
                )
            )
            side_walls.pop(price, None)

        return events


def _calc_imbalance(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    bids_qty = sum(qty for _, qty in bids)
    asks_qty = sum(qty for _, qty in asks)
    total = bids_qty + asks_qty
    if total <= 0:
        return 0.0
    return (bids_qty - asks_qty) / total
