# forge/loop.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from forge.budget import Budget
from forge.config import RunConfig
from forge.examiner import Examiner, TestFile, split_suite
from forge.memory import AttemptRecord, RunLog
from forge.runner import Runner
from forge.workspace import Workspace


@dataclass
class SolveResult:
    success: bool
    best_score: float
    iterations: int
    reason: str
    best_dir: Path


def _write_tests(dest: Path, tests: list[TestFile]) -> None:
    if dest.exists():
        import shutil
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for t in tests:
        (dest / Path(t.path).name).write_text(t.content)


def solve(
    goal_dir: Path,
    config: RunConfig,
    examiner: Examiner,
    builder,
    *,
    now=time.monotonic,
    write_tests: bool = True,
) -> SolveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()

    forge_dir = goal_dir / ".forge"
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_dir = forge_dir / "best"

    budget = Budget(
        max_cost_usd=config.max_cost_usd,
        max_iterations=config.max_iterations,
        max_wall_seconds=config.max_wall_seconds,
        started_at=now(),
    )

    if write_tests:
        ex = examiner.write_tests(goal)
        budget.charge_tokens(config.examiner_model, ex.input_tokens, ex.output_tokens)
        visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
        _write_tests(frozen, visible)
        _write_tests(holdout, held)

    log = RunLog(forge_dir / "run.jsonl")
    workspace = Workspace(forge_dir / "ws")
    runner = Runner(workspace.solution_dir, frozen, config.test_command)

    best_score = -1.0
    have_best = False
    rounds_without_improvement = 0
    last_failures: list = []
    reason = "max_iterations"

    while True:
        stopped = budget.exhausted(now())
        if stopped is not None:
            reason = stopped
            break

        budget.tick_iteration()
        workspace.seed_from(best_dir if have_best else None)

        outcome = builder.attempt(workspace.solution_dir, goal, last_failures)
        budget.charge_usd(outcome.cost_usd)

        result = runner.run()
        last_failures = result.failures

        log.record(AttemptRecord(
            iteration=budget.iterations,
            score=result.score,
            is_green=result.is_green,
            diff_summary=outcome.plan[:200],
            failing=[f.nodeid for f in result.failures],
            plan=outcome.plan,
            cost_usd=outcome.cost_usd,
        ))

        improved = result.score > best_score
        if improved:
            workspace.promote_to(best_dir)
            best_score = result.score
            have_best = True
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

        if result.is_green:
            if _holdout_green(holdout, best_dir, config):
                return SolveResult(True, best_score, budget.iterations, "green", best_dir)
            return SolveResult(False, best_score, budget.iterations, "overfit_on_holdout", best_dir)

        if rounds_without_improvement >= config.plateau_patience:
            reason = "plateau"
            break
        if budget.iterations >= config.max_iterations:
            reason = "max_iterations"
            break

    return SolveResult(False, max(best_score, 0.0), budget.iterations, reason, best_dir)


def _holdout_green(holdout: Path, best_dir: Path, config: RunConfig) -> bool:
    if not holdout.exists() or not any(holdout.iterdir()):
        return True  # no holdout configured → visible-green is the verdict
    return Runner(best_dir, holdout, config.test_command).run().is_green
