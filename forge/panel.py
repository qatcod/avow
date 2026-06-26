from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PanelResult:
    mean: float
    scores: dict
    agreement: float


def aggregate_panel(scores: dict) -> PanelResult:
    if not scores:
        return PanelResult(mean=0.0, scores={}, agreement=1.0)
    vals = list(scores.values())
    mean = sum(vals) / len(vals)
    agreement = 1.0 if len(vals) <= 1 else max(0.0, 1.0 - (max(vals) - min(vals)))
    return PanelResult(mean=mean, scores=dict(scores), agreement=agreement)
