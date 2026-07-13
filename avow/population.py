from __future__ import annotations

import concurrent.futures
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from avow.loop import solve
from avow.improve import _snapshot


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


def _solve_candidate(goal_dir, i, config, examiner, builder, clients, now) -> Candidate:
    cand_dir = Path(goal_dir) / ".avow" / "candidates" / str(i)
    _stage_candidate(goal_dir, cand_dir)
    ri = solve(cand_dir, config, examiner, builder, now=now, write_tests=False, **clients)
    return Candidate(i, ri, cand_dir / ".avow" / "best")


def _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now) -> PopulationResult:
    goal_dir = Path(goal_dir)
    indices = list(range(len(candidates), max(1, config.population_size)))
    if indices:
        max_workers = max(1, min(config.max_parallel_candidates, len(indices)))
        by_index: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_solve_candidate, goal_dir, i, config, examiner, builder, clients, now): i
                for i in indices
            }
            for fut in concurrent.futures.as_completed(futures):
                i = futures[fut]
                try:
                    by_index[i] = fut.result()
                except Exception as exc:  # one candidate crashing must not abort the others
                    by_index[i] = Candidate(
                        i,
                        SimpleNamespace(success=False, confidence=None, best_score=-1.0,
                                        reason=f"candidate_error: {exc}", confidence_breakdown={}),
                        None,
                    )
        for i in indices:                       # append in INDEX order -> deterministic selection
            candidates.append(by_index[i])

    results = [c.result for c in candidates]
    winner = select_best(results)
    dest = goal_dir / ".avow" / "best"
    if winner != 0:
        win_dir = candidates[winner].solution_dir
        if win_dir is not None and Path(win_dir).exists():
            _snapshot(win_dir, dest)
        else:
            winner = 0                          # winner has no promoted artifact -> best/ holds candidate 0
    return PopulationResult(success=results[winner].success, best=results[winner],
                            candidates=candidates, winner_index=winner)


def population_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                     intent_client=None, property_client=None, oracle_client=None,
                     now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".avow" / "best")]
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)


def hybrid_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                 intent_client=None, property_client=None, oracle_client=None,
                 now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".avow" / "best")]
    if r0.success:
        return PopulationResult(success=True, best=r0, candidates=candidates, winner_index=0)
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)
