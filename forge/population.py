from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from forge.loop import solve
from forge.improve import _snapshot


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


def _comparable_confidence(result) -> float:
    """Mean of the per-signal confidence breakdown EXCLUDING the suite-level `intent`
    term, so candidates judged with intent (candidate 0, write_tests=True) and without
    it (candidates 1..N, write_tests=False) are compared on the same solution-specific
    signals (hold-out / mutation / oracle). Falls back to `.confidence` when no breakdown."""
    breakdown = getattr(result, "confidence_breakdown", None) or {}
    common = [v for k, v in breakdown.items() if k != "intent"]
    if common:
        return sum(common) / len(common)
    conf = result.confidence
    return conf if conf is not None else -1.0


def _rank_key(result) -> tuple:
    return (1 if result.success else 0, _comparable_confidence(result), result.best_score)


def select_best(results: list) -> int:
    if not results:
        return -1
    best_i = 0
    for i in range(1, len(results)):
        if _rank_key(results[i]) > _rank_key(results[best_i]):
            best_i = i
    return best_i


def _stage_candidate(goal_dir, cand_dir) -> None:
    goal_dir, cand_dir = Path(goal_dir), Path(cand_dir)
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir(parents=True)
    shutil.copy2(goal_dir / "goal.md", cand_dir / "goal.md")
    for name in ("tests_frozen", "tests_holdout"):
        src = goal_dir / name
        if src.exists():
            shutil.copytree(src, cand_dir / name)


def _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now) -> PopulationResult:
    goal_dir = Path(goal_dir)
    for i in range(len(candidates), max(1, config.population_size)):
        cand_dir = goal_dir / ".forge" / "candidates" / str(i)
        _stage_candidate(goal_dir, cand_dir)
        ri = solve(cand_dir, config, examiner, builder, now=now, write_tests=False, **clients)
        candidates.append(Candidate(i, ri, cand_dir / ".forge" / "best"))

    results = [c.result for c in candidates]
    winner = select_best(results)
    dest = goal_dir / ".forge" / "best"
    if winner != 0:
        win_dir = candidates[winner].solution_dir
        if Path(win_dir).exists():
            _snapshot(win_dir, dest)
        else:
            winner = 0  # selected candidate has no promoted artifact; best/ holds candidate 0
    return PopulationResult(success=results[winner].success, best=results[winner],
                            candidates=candidates, winner_index=winner)


def population_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                     intent_client=None, property_client=None, oracle_client=None,
                     now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".forge" / "best")]
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)


def hybrid_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                 intent_client=None, property_client=None, oracle_client=None,
                 now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".forge" / "best")]
    if r0.success:
        return PopulationResult(success=True, best=r0, candidates=candidates, winner_index=0)
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)
