from __future__ import annotations

from dataclasses import dataclass
import math

from src.orderbook import OrderBookState
from src.wall_detector import SignalEvent


@dataclass
class ScoreSnapshot:
    p_up: float
    p_down: float
    base_raw: float
    base_p_up: float
    shock_value: float
    ref_price: float
    round_id: str
    pressure_breakdown: list[dict[str, float]]


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

        self.ref_price = 0.0
        self.round_id = ""
        self._shock_value = 0.0
        self._last_ts: float | None = None

        self._event_shock_map = {
            ("ask", "FULL_REMOVE"): 12.0,
            ("ask", "MAJOR_DROP"): 7.0,
            ("ask", "DROP"): 4.0,
            ("bid", "FULL_REMOVE"): -12.0,
            ("bid", "MAJOR_DROP"): -7.0,
            ("bid", "DROP"): -4.0,
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

    def on_wall_event(self, event: SignalEvent, ts: float) -> None:
        self._decay_shock(ts)
        if self.ref_price <= 0:
            return
        base_shock = self._event_shock_map.get((event.side, event.event_type), 0.0)
        if base_shock == 0.0:
            return

        dist_bps = abs(event.price - self.ref_price) / self.ref_price * 10_000
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

    def _calc_base_raw(self, orderbook: OrderBookState) -> tuple[float, list[dict[str, float]]]:
        if self.ref_price <= 0:
            return 0.0, []

        weighted_buy = 0.0
        weighted_sell = 0.0
        breakdown: list[dict[str, float]] = []

        for range_bps, weight in zip(self.pressure_ranges_bps, self.pressure_weights):
            max_delta = self.ref_price * (range_bps / 10_000)
            buy_qty = sum(qty for price, qty in orderbook.bids if self.ref_price - max_delta <= price <= self.ref_price)
            sell_qty = sum(qty for price, qty in orderbook.asks if self.ref_price <= price <= self.ref_price + max_delta)
            weighted_buy += buy_qty * weight
            weighted_sell += sell_qty * weight
            breakdown.append(
                {
                    "range_bps": range_bps,
                    "weight": weight,
                    "buy_qty": buy_qty,
                    "sell_qty": sell_qty,
                }
            )

        denom = weighted_buy + weighted_sell + 1e-9
        raw = (weighted_buy - weighted_sell) / denom
        return _clamp(raw, -1.0, 1.0), breakdown


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
