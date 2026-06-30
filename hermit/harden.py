# hermit/harden.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from hermit.loop import solve
from hermit.examiner import split_suite
from hermit.improve import _append_tests, _snapshot


@dataclass
class HardenResult:
    success: bool
    rounds_run: int
    rounds: list
    final: object
    best_round: int = -1
    best_dir: object = None


def _read_solution_code(best_dir) -> str:
    best_dir = Path(best_dir)
    parts = []
    for f in sorted(best_dir.glob("*.py")):
        if f.name.startswith("test_") or f.name == "conftest.py":
            continue
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def harden(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None,
           property_client=None, oracle_client=None, now=time.monotonic) -> HardenResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_src = goal_dir / ".hermit" / "best"
    lkg = goal_dir / ".hermit" / "best_good"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    rounds = [result]
    rounds_run = 0
    best_round = -1
    best_dir = None
    if result.success and best_src.exists():
        _snapshot(best_src, lkg)
        best_round, best_dir = 0, lkg

    while result.success and rounds_run < config.adversarial_rounds:
        adv = examiner.write_adversarial_tests(goal, _read_solution_code(best_src))
        visible, held = split_suite(adv.suite.tests, config.holdout_fraction)
        _append_tests(frozen, visible, rounds_run + 1)
        _append_tests(holdout, held, rounds_run + 1)
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        rounds.append(result)
        rounds_run += 1
        if result.success and best_src.exists():
            _snapshot(best_src, lkg)
            best_round, best_dir = rounds_run, lkg

    return HardenResult(success=result.success, rounds_run=rounds_run, rounds=rounds,
                        final=result, best_round=best_round, best_dir=best_dir)
