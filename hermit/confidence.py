from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceResult:
    score: float
    breakdown: dict
    weights_used: dict


def aggregate_confidence(signals: dict, weights: dict) -> ConfidenceResult:
    present = {
        k: v for k, v in signals.items()
        if v is not None and weights.get(k, 0.0) > 0.0
    }
    if not present:
        return ConfidenceResult(score=0.0, breakdown={}, weights_used={})
    total = sum(weights[k] for k in present)
    weights_used = {k: weights[k] / total for k in present}
    score = sum(weights_used[k] * present[k] for k in present)
    return ConfidenceResult(score=score, breakdown=dict(present), weights_used=weights_used)
