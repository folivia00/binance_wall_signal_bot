from __future__ import annotations

from src.detectors.base import DetectorOutput


class OrderbookDetector:
    """Simple adapter detector that converts an already computed p_up into detector format."""

    def evaluate(self, p_up: float, confidence: float = 1.0) -> DetectorOutput:
        return DetectorOutput(
            name="orderbook",
            p_up_component=p_up,
            confidence=confidence,
            meta={"source": "polymarket_scorer"},
        )
