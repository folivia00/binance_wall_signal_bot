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
    touch_bps: float
    age_sec: float
    best_bid: float
    best_ask: float
    full_remove: bool
    event_type: str


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
        max_touch_bps: float,
        price_cooldown_sec: float,
        price_bucket: float,
        full_remove_eps: float,
        only_full_remove: bool,
        major_drop_min_pct: float,
        min_touch_bps: float,
        min_wall_age_sec: float,
        global_cooldown_sec: float,
    ) -> None:
        self.n_levels = n_levels
        self.wall_mult = wall_mult
        self.min_wall_qty = min_wall_qty
        self.max_wall_dist_bps = max_wall_dist_bps
        self.event_ttl_sec = event_ttl_sec
        self.wall_drop_pct = wall_drop_pct
        self.imb_thr = imb_thr
        self.signal_cooldown_sec = signal_cooldown_sec
        self.max_touch_bps = max_touch_bps
        self.price_cooldown_sec = price_cooldown_sec
        self.price_bucket = max(price_bucket, 1e-8)
        self.full_remove_eps = full_remove_eps
        self.only_full_remove = only_full_remove
        self.major_drop_min_pct = major_drop_min_pct
        self.min_touch_bps = min_touch_bps
        self.min_wall_age_sec = min_wall_age_sec
        self.global_cooldown_sec = global_cooldown_sec
        self.walls: dict[str, dict[float, WallInfo]] = {"bid": {}, "ask": {}}
        self.last_signal_ts: dict[str, float] = {"LONG": 0.0, "SHORT": 0.0}
        self.last_global_signal_ts = 0.0
        self.last_level_signal_ts: dict[tuple[str, float], float] = {}

    def reset(self) -> None:
        self.walls = {"bid": {}, "ask": {}}
        self.last_signal_ts = {"LONG": 0.0, "SHORT": 0.0}
        self.last_global_signal_ts = 0.0
        self.last_level_signal_ts = {}

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
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        bid_event = self._check_drops("bid", imbalance, qty_at, now, mid, best_bid, best_ask)
        ask_event = self._check_drops("ask", imbalance, qty_at, now, mid, best_bid, best_ask)
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

    def _check_drops(
        self,
        side: str,
        imbalance: float,
        qty_at,
        now: float,
        mid: float,
        best_bid: float,
        best_ask: float,
    ) -> SignalEvent | None:
        side_walls = self.walls[side]
        direction = "SHORT" if side == "bid" else "LONG"

        best: SignalEvent | None = None
        best_price: float | None = None
        for price, info in list(side_walls.items()):
            age = now - info.first_seen_ts
            if age > self.event_ttl_sec:
                side_walls.pop(price, None)
                continue
            if age < self.min_wall_age_sec:
                continue

            current_qty = qty_at(side, price)
            if info.qty <= 0:
                side_walls.pop(price, None)
                continue

            drop_pct = (info.qty - current_qty) / info.qty
            is_zero = current_qty <= self.full_remove_eps
            is_big_wall = info.qty >= self.min_wall_qty
            full_remove = is_zero and is_big_wall and drop_pct >= self.major_drop_min_pct
            major_drop = drop_pct >= self.major_drop_min_pct
            if drop_pct < self.wall_drop_pct:
                continue

            if self.only_full_remove:
                if not full_remove:
                    continue
                event_type = "FULL_REMOVE"
            else:
                if full_remove:
                    event_type = "FULL_REMOVE"
                elif major_drop:
                    event_type = "MAJOR_DROP"
                else:
                    event_type = "DROP"

            if side == "ask" and imbalance < self.imb_thr:
                continue
            if side == "bid" and imbalance > -self.imb_thr:
                continue

            touch_ref = best_bid if side == "bid" else best_ask
            touch_bps = _calc_touch_bps(touch_ref, price, mid, side)
            if touch_bps < self.min_touch_bps:
                continue
            if touch_bps > self.max_touch_bps:
                continue

            if not self._allow_level_signal(side, price, now):
                continue

            imb_score = min(40.0, abs(imbalance) * 200)
            drop_score = min(40.0, drop_pct * 40)
            touch_score = max(0.0, 20.0 - touch_bps * 10)
            score = int(min(100.0, 10.0 + imb_score + drop_score + touch_score))
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
                touch_bps=touch_bps,
                age_sec=age,
                best_bid=best_bid,
                best_ask=best_ask,
                full_remove=full_remove,
                event_type=event_type,
            )
            if best is None or _is_better_event(event, best):
                best = event
                best_price = price

        if best is None:
            return None

        since_last = now - self.last_signal_ts[direction]
        if since_last < self.signal_cooldown_sec:
            return None
        if now - self.last_global_signal_ts < self.global_cooldown_sec:
            return None

        self.last_signal_ts[direction] = now
        self.last_global_signal_ts = now
        if best_price is not None:
            side_walls.pop(best_price, None)
        return best

    def _allow_level_signal(self, side: str, price: float, now: float) -> bool:
        price_key = round(round(price / self.price_bucket) * self.price_bucket, 8)
        level_key = (side, price_key)
        last_ts = self.last_level_signal_ts.get(level_key)
        if last_ts is not None and now - last_ts < self.price_cooldown_sec:
            return False
        self.last_level_signal_ts[level_key] = now
        return True


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


def _calc_touch_bps(reference_price: float, wall_price: float, mid: float, side: str) -> float:
    if reference_price <= 0 or mid <= 0:
        return float("inf")
    if side == "bid" and wall_price > reference_price:
        return float("inf")
    if side == "ask" and wall_price < reference_price:
        return float("inf")
    return abs(reference_price - wall_price) / mid * 10_000


def _is_better_event(candidate: SignalEvent, current_best: SignalEvent) -> bool:
    if candidate.event_type != current_best.event_type:
        return candidate.event_type == "FULL_REMOVE"
    if candidate.old_qty != current_best.old_qty:
        return candidate.old_qty > current_best.old_qty
    if candidate.touch_bps != current_best.touch_bps:
        return candidate.touch_bps < current_best.touch_bps
    return candidate.score > current_best.score
