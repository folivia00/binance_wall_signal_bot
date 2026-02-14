from __future__ import annotations

from dataclasses import dataclass
import math

from src.orderbook import OrderBookState
from src.wall_detector import SignalEvent, WallEvent


@dataclass
class ScoreSnapshot:
    p_up: float
    p_down: float
    base_raw: float
    base_p_up: float
    shock_value: float
    ref_price: float
    round_id: str
    pressure_breakdown: list[dict[str, float | bool]]


class PolymarketScorer:
    def __init__(
        self,
        pressure_ranges_bps: tuple[float, ...],
        pressure_weights: tuple[float, ...],
        base_scale: float,
        shock_half_life_sec: float,
        max_shock: float,
        shock_distance_bps_cap: float,
        shock_min_age_sec: float,
        shock_age_full_sec: float,
        min_depth_sum: float,
        base_center_mode: str,
        base_ref_weight: float,
        shock_distance_mode: str,
        shock_full_remove: float,
        shock_major_drop: float,
        shock_drop: float,
    ) -> None:
        if len(pressure_ranges_bps) != len(pressure_weights):
            raise ValueError("pressure_ranges_bps and pressure_weights must have the same length")
        self.pressure_ranges_bps = pressure_ranges_bps
        self.pressure_weights = pressure_weights
        self.base_scale = base_scale
        self.shock_half_life_sec = max(0.1, shock_half_life_sec)
        self.max_shock = max(1.0, max_shock)
        self.shock_distance_bps_cap = max(1e-6, shock_distance_bps_cap)
        self.shock_min_age_sec = max(0.0, shock_min_age_sec)
        self.shock_age_full_sec = max(self.shock_min_age_sec + 1e-6, shock_age_full_sec)
        self.min_depth_sum = max(0.0, min_depth_sum)
        self.base_center_mode = base_center_mode
        self.base_ref_weight = _clamp(base_ref_weight, 0.0, 1.0)
        self.shock_distance_mode = shock_distance_mode

        self.ref_price = 0.0
        self.round_id = ""
        self._shock_value = 0.0
        self._last_ts: float | None = None

        self._event_shock_map = {
            ("ask", "FULL_REMOVE"): shock_full_remove,
            ("ask", "MAJOR_DROP"): shock_major_drop,
            ("ask", "DROP"): shock_drop,
            ("bid", "FULL_REMOVE"): -shock_full_remove,
            ("bid", "MAJOR_DROP"): -shock_major_drop,
            ("bid", "DROP"): -shock_drop,
        }

    def set_reference(self, price: float, ts: float, round_id: str | int) -> None:
        self.ref_price = max(0.0, price)
        self.round_id = str(round_id)
        self._shock_value = 0.0
        self._last_ts = ts

    def on_orderbook_update(self, orderbook: OrderBookState, ts: float) -> ScoreSnapshot:
        self._decay_shock(ts)
        base_raw, breakdown = self._calc_base_raw(orderbook)
        base_p_up = _clamp(50.0 + base_raw * self.base_scale, 0.0, 100.0)
        p_up = _clamp(base_p_up + self._shock_value, 0.0, 100.0)
        return ScoreSnapshot(
            p_up=p_up,
            p_down=100.0 - p_up,
            base_raw=base_raw,
            base_p_up=base_p_up,
            shock_value=self._shock_value,
            ref_price=self.ref_price,
            round_id=self.round_id,
            pressure_breakdown=breakdown,
        )

    def on_wall_event(self, event: SignalEvent | WallEvent, ts: float) -> None:
        self._decay_shock(ts)
        if self.ref_price <= 0:
            return
        base_shock = self._event_shock_map.get((event.side, event.event_type), 0.0)
        if base_shock == 0.0:
            return

        center_price = self._event_distance_center(event)
        if center_price <= 0:
            return
        dist_bps = abs(event.price - center_price) / center_price * 10_000
        distance_mult = _clamp(1.0 - dist_bps / self.shock_distance_bps_cap, 0.1, 1.0)
        if event.age_sec <= self.shock_min_age_sec:
            age_mult = 0.3
        elif event.age_sec >= self.shock_age_full_sec:
            age_mult = 1.0
        else:
            age_mult = 0.3 + 0.7 * (
                (event.age_sec - self.shock_min_age_sec) / (self.shock_age_full_sec - self.shock_min_age_sec)
            )

        self._shock_value = _clamp(self._shock_value + base_shock * distance_mult * age_mult, -self.max_shock, self.max_shock)

    def _decay_shock(self, ts: float) -> None:
        if self._last_ts is None:
            self._last_ts = ts
            return
        dt = max(0.0, ts - self._last_ts)
        if dt > 0:
            decay = math.exp(-dt * math.log(2.0) / self.shock_half_life_sec)
            self._shock_value *= decay
            self._last_ts = ts

    def _calc_base_raw(self, orderbook: OrderBookState) -> tuple[float, list[dict[str, float | bool]]]:
        if self.ref_price <= 0:
            return 0.0, []

        mid = _calc_mid(orderbook)
        raw_mid, buy_mid, sell_mid, breakdown_mid = self._calc_pressure_for_center(orderbook, mid)
        raw_ref, buy_ref, sell_ref, breakdown_ref = self._calc_pressure_for_center(orderbook, self.ref_price)

        center_mode = self.base_center_mode
        if center_mode == "mid":
            raw = raw_mid
            weighted_buy = buy_mid
            weighted_sell = sell_mid
            breakdown = breakdown_mid
            center_price = mid
        elif center_mode == "blend":
            w = self.base_ref_weight
            weighted_buy = buy_mid * (1.0 - w) + buy_ref * w
            weighted_sell = sell_mid * (1.0 - w) + sell_ref * w
            denom = weighted_buy + weighted_sell + 1e-9
            raw = (weighted_buy - weighted_sell) / denom
            center_price = mid * (1.0 - w) + self.ref_price * w if mid > 0 else self.ref_price
            breakdown = []
            for idx, range_bps in enumerate(self.pressure_ranges_bps):
                breakdown.append(
                    {
                        "range_bps": range_bps,
                        "weight": self.pressure_weights[idx],
                        "buy_qty_mid": breakdown_mid[idx]["buy_qty"],
                        "sell_qty_mid": breakdown_mid[idx]["sell_qty"],
                        "buy_qty_ref": breakdown_ref[idx]["buy_qty"],
                        "sell_qty_ref": breakdown_ref[idx]["sell_qty"],
                    }
                )
        else:
            raw = raw_ref
            weighted_buy = buy_ref
            weighted_sell = sell_ref
            breakdown = breakdown_ref
            center_price = self.ref_price

        depth_sum = weighted_buy + weighted_sell
        depth_ok = depth_sum >= self.min_depth_sum
        if not depth_ok:
            raw = 0.0

        breakdown.append(
            {
                "depth_sum": depth_sum,
                "depth_ok": depth_ok,
                "center_price": center_price,
                "raw_mid": raw_mid,
                "raw_ref": raw_ref,
            }
        )
        return _clamp(raw, -1.0, 1.0), breakdown

    def _calc_pressure_for_center(
        self,
        orderbook: OrderBookState,
        center_price: float,
    ) -> tuple[float, float, float, list[dict[str, float]]]:
        if center_price <= 0:
            return 0.0, 0.0, 0.0, [
                {"range_bps": range_bps, "weight": weight, "buy_qty": 0.0, "sell_qty": 0.0}
                for range_bps, weight in zip(self.pressure_ranges_bps, self.pressure_weights)
            ]
        weighted_buy = 0.0
        weighted_sell = 0.0
        breakdown: list[dict[str, float]] = []
        for range_bps, weight in zip(self.pressure_ranges_bps, self.pressure_weights):
            max_delta = center_price * (range_bps / 10_000)
            buy_qty = sum(qty for price, qty in orderbook.bids if center_price - max_delta <= price <= center_price)
            sell_qty = sum(qty for price, qty in orderbook.asks if center_price <= price <= center_price + max_delta)
            weighted_buy += buy_qty * weight
            weighted_sell += sell_qty * weight
            breakdown.append({"range_bps": range_bps, "weight": weight, "buy_qty": buy_qty, "sell_qty": sell_qty})
        denom = weighted_buy + weighted_sell + 1e-9
        raw = (weighted_buy - weighted_sell) / denom
        return _clamp(raw, -1.0, 1.0), weighted_buy, weighted_sell, breakdown

    def _event_distance_center(self, event: SignalEvent | WallEvent) -> float:
        if self.shock_distance_mode == "mid":
            return (event.best_bid + event.best_ask) / 2 if event.best_bid > 0 and event.best_ask > 0 else 0.0
        if self.shock_distance_mode == "blend":
            mid = (event.best_bid + event.best_ask) / 2 if event.best_bid > 0 and event.best_ask > 0 else 0.0
            return mid * (1.0 - self.base_ref_weight) + self.ref_price * self.base_ref_weight if mid > 0 else self.ref_price
        return self.ref_price


def _calc_mid(orderbook: OrderBookState) -> float:
    if not orderbook.bids or not orderbook.asks:
        return 0.0
    return (orderbook.bids[0][0] + orderbook.asks[0][0]) / 2


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
