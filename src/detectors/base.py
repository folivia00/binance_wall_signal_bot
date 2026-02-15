from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DetectorOutput:
    name: str
    p_up_component: float
    confidence: float
    meta: dict[str, float | str | int | bool] = field(default_factory=dict)

    def normalized_component(self) -> float:
        return max(0.0, min(100.0, self.p_up_component))

    def normalized_confidence(self) -> float:
        return max(0.0, min(1.0, self.confidence))
