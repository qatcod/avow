# forge/loop.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from forge.budget import Budget
from forge.config import RunConfig
from forge.examiner import Examiner, TestFile, split_suite
from forge.memory import AttemptRecord, RunLog
from forge.mutation import run_mutation_testing
from forge.runner import Runner
from forge.workspace import Workspace


@dataclass
class SolveResult:
    success: bool
    best_score: float
    iterations: int
    reason: str
    best_dir: Path | None
    mutation_score: float | None = None
    survivors: int = 0


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
    confirm=None,
    mutation_client=None,
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
        if confirm is not None and not confirm(ex.suite.test_plan):
            return SolveResult(False, 0.0, 0, "aborted", None)

    log = RunLog(forge_dir / "run.jsonl")
    workspace = Workspace(forge_dir / "ws")
    runner = Runner(workspace.solution_dir, frozen, config.test_command, timeout=config.test_timeout_seconds)

    best_score = -1.0
    have_best = False
    rounds_without_improvement = 0
    best_failures: list = []
    reason = "max_iterations"

    while True:
        stopped = budget.exhausted(now())
        if stopped is not None:
            reason = stopped
            break

        budget.tick_iteration()
        workspace.seed_from(best_dir if have_best else None)

        outcome = builder.attempt(workspace.solution_dir, goal, best_failures)
        budget.charge_usd(outcome.cost_usd)

        result = runner.run()

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
            best_failures = result.failures
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

        if result.is_green:
            if _holdout_green(holdout, best_dir, config):
                mscore: float | None = None
                surv = 0
                if config.mutation_enabled:
                    before = budget.spent_usd
                    mr = run_mutation_testing(
                        best_dir, frozen, config.test_command,
                        max_ast_mutants=config.max_ast_mutants,
                        llm_n=(config.llm_mutants_n if mutation_client is not None else 0),
                        timeout=config.test_timeout_seconds,
                        client=mutation_client, model=config.mutation_model, goal=goal,
                    )
                    budget.charge_tokens(config.mutation_model, mr.llm_input_tokens, mr.llm_output_tokens)
                    mscore, surv = mr.score, mr.survived
                    log.record(AttemptRecord(
                        iteration=budget.iterations, score=result.score, is_green=True,
                        diff_summary=f"mutation {mscore:.2f} ({mr.killed}/{mr.total}), {surv} survivors",
                        failing=[], plan="mutation testing", cost_usd=budget.spent_usd - before,
                    ))
                return SolveResult(True, best_score, budget.iterations, "green", best_dir, mscore, surv)
            return SolveResult(False, best_score, budget.iterations, "overfit_on_holdout", best_dir)

        if rounds_without_improvement >= config.plateau_patience:
            reason = "plateau"
            break
        if budget.iterations >= config.max_iterations:
            reason = "max_iterations"
            break

    return SolveResult(
        False, max(best_score, 0.0), budget.iterations, reason,
        best_dir if have_best else None,
    )


def _holdout_green(holdout: Path, best_dir: Path, config: RunConfig) -> bool:
    if not holdout.exists() or not any(holdout.iterdir()):
        return True  # no holdout configured → visible-green is the verdict
    return Runner(best_dir, holdout, config.test_command, timeout=config.test_timeout_seconds).run().is_green
