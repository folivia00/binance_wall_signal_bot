from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class OrderBookState:
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


class OrderBook:
    def __init__(self, n_levels: int) -> None:
        self.n_levels = n_levels
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def apply_depth_update(self, data: dict) -> OrderBookState:
        for price, qty in _iter_levels(data.get("b", [])):
            _apply_level(self._bids, price, qty)

        for price, qty in _iter_levels(data.get("a", [])):
            _apply_level(self._asks, price, qty)

        return self.top_levels()

    def top_levels(self) -> OrderBookState:
        bids = sorted(self._bids.items(), key=lambda x: x[0], reverse=True)[: self.n_levels]
        asks = sorted(self._asks.items(), key=lambda x: x[0])[: self.n_levels]
        return OrderBookState(bids=bids, asks=asks)



def _iter_levels(raw_levels: Iterable[Iterable[str]]) -> Iterable[tuple[float, float]]:
    for raw_price, raw_qty in raw_levels:
        yield float(raw_price), float(raw_qty)



def _apply_level(side_book: dict[float, float], price: float, qty: float) -> None:
    if qty <= 0:
        side_book.pop(price, None)
    else:
        side_book[price] = qty
