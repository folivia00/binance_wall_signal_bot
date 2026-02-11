from __future__ import annotations

from dataclasses import dataclass
from statistics import median
import time

from src.orderbook import OrderBookState


@dataclass
class WallInfo:
    qty: float
    first_seen_ts: float
    dist_bps: float


@dataclass
class SignalEvent:
    ts: float
    side: str
    direction: str
    price: float
    old_qty: float
    current_qty: float
    drop_pct: float
    imbalance: float
    score: int
    dist_bps: float


class WallDetector:
    def __init__(
        self,
        n_levels: int,
        wall_mult: float,
        min_wall_qty: float,
        max_wall_dist_bps: float,
        event_ttl_sec: float,
        wall_drop_pct: float,
        imb_thr: float,
        signal_cooldown_sec: float,
    ) -> None:
        self.n_levels = n_levels
        self.wall_mult = wall_mult
        self.min_wall_qty = min_wall_qty
        self.max_wall_dist_bps = max_wall_dist_bps
        self.event_ttl_sec = event_ttl_sec
        self.wall_drop_pct = wall_drop_pct
        self.imb_thr = imb_thr
        self.signal_cooldown_sec = signal_cooldown_sec
        self.walls: dict[str, dict[float, WallInfo]] = {"bid": {}, "ask": {}}
        self.last_signal_ts: dict[str, float] = {"LONG": 0.0, "SHORT": 0.0}

    def reset(self) -> None:
        self.walls = {"bid": {}, "ask": {}}

    def process(self, state: OrderBookState, qty_at) -> tuple[list[SignalEvent], float, float, int]:
        now = time.time()
        bids = state.bids[: self.n_levels]
        asks = state.asks[: self.n_levels]

        imbalance = _calc_imbalance(bids, asks)
        spread_bps = _calc_spread_bps(bids, asks)
        mid = _calc_mid(bids, asks)

        bid_median = median([qty for _, qty in bids]) if bids else 0.0
        ask_median = median([qty for _, qty in asks]) if asks else 0.0

        self._track_new_walls("bid", bids, bid_median, mid, now)
        self._track_new_walls("ask", asks, ask_median, mid, now)

        events: list[SignalEvent] = []
        bid_event = self._check_drops("bid", imbalance, qty_at, now)
        ask_event = self._check_drops("ask", imbalance, qty_at, now)
        if bid_event:
            events.append(bid_event)
        if ask_event:
            events.append(ask_event)

        wall_candidates = len(self.walls["bid"]) + len(self.walls["ask"])
        return events, imbalance, spread_bps, wall_candidates

    def _track_new_walls(
        self,
        side: str,
        levels: list[tuple[float, float]],
        median_qty: float,
        mid: float,
        now: float,
    ) -> None:
        if median_qty <= 0 or mid <= 0:
            return

        threshold = max(self.min_wall_qty, self.wall_mult * median_qty)
        side_walls = self.walls[side]
        for price, qty in levels:
            dist_bps = abs(price - mid) / mid * 10_000
            if dist_bps > self.max_wall_dist_bps:
                continue
            if qty >= threshold and price not in side_walls:
                side_walls[price] = WallInfo(qty=qty, first_seen_ts=now, dist_bps=dist_bps)

    def _check_drops(self, side: str, imbalance: float, qty_at, now: float) -> SignalEvent | None:
        side_walls = self.walls[side]
        direction = "SHORT" if side == "bid" else "LONG"

        best: SignalEvent | None = None
        for price, info in list(side_walls.items()):
            age = now - info.first_seen_ts
            if age > self.event_ttl_sec:
                side_walls.pop(price, None)
                continue

            current_qty = qty_at(side, price)
            if info.qty <= 0:
                side_walls.pop(price, None)
                continue

            drop_pct = (info.qty - current_qty) / info.qty
            if drop_pct < self.wall_drop_pct:
                continue

            if side == "ask" and imbalance < self.imb_thr:
                side_walls.pop(price, None)
                continue
            if side == "bid" and imbalance > -self.imb_thr:
                side_walls.pop(price, None)
                continue

            score = min(100, int(50 + abs(imbalance) * 200))
            event = SignalEvent(
                ts=now,
                side=side,
                direction=direction,
                price=price,
                old_qty=info.qty,
                current_qty=current_qty,
                drop_pct=drop_pct,
                imbalance=imbalance,
                score=score,
                dist_bps=info.dist_bps,
            )
            if best is None or event.score > best.score:
                best = event
            side_walls.pop(price, None)

        if best is None:
            return None

        since_last = now - self.last_signal_ts[direction]
        if since_last < self.signal_cooldown_sec:
            return None

        self.last_signal_ts[direction] = now
        return best


def _calc_imbalance(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    bids_qty = sum(qty for _, qty in bids)
    asks_qty = sum(qty for _, qty in asks)
    total = bids_qty + asks_qty
    if total <= 0:
        return 0.0
    return (bids_qty - asks_qty) / total


def _calc_mid(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    if not bids or not asks:
        return 0.0
    return (bids[0][0] + asks[0][0]) / 2


def _calc_spread_bps(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    mid = _calc_mid(bids, asks)
    if mid <= 0:
        return 0.0
    return (asks[0][0] - bids[0][0]) / mid * 10_000
