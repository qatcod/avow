from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    index: int
    result: object
    solution_dir: object


@dataclass
class PopulationResult:
    success: bool
    best: object
    candidates: list
    winner_index: int


def _rank_key(result) -> tuple:
    conf = result.confidence if result.confidence is not None else -1.0
    return (1 if result.success else 0, conf, result.best_score)


def select_best(results: list) -> int:
    if not results:
        return -1
    best_i = 0
    for i in range(1, len(results)):
        if _rank_key(results[i]) > _rank_key(results[best_i]):
            best_i = i
    return best_i
