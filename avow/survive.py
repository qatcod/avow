from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from avow.loop import solve
from avow.budget import Budget
from avow.gauntlet import run_gauntlet


@dataclass
class SurviveResult:
    status: str        # verified_survivor | died | not_green | unverified
    rounds: int
    final: object
    death_counterexample: object = None


def survive(goal_dir, config, examiner, builder, *, gauntlet_client, mutation_client=None,
            intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> SurviveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"
    best_src = goal_dir / ".avow" / "best"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    if not (result.success and best_src.exists()):
        return SurviveResult("not_green", 0, result)
    if gauntlet_client is None:
        return SurviveResult("unverified", 0, result)   # green, but no gauntlet ran

    budget = Budget(max_cost_usd=config.max_cost_usd, max_iterations=config.max_iterations,
                    max_wall_seconds=config.max_wall_seconds, started_at=now())
    last_cx = None
    for rnd in range(config.gauntlet_max_rounds):
        g = run_gauntlet(best_src, goal, gauntlet_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds)
        budget.charge_tokens(config.gauntlet_model, g.input_tokens, g.output_tokens)
        if g.survived:
            return SurviveResult("verified_survivor", rnd, result)
        last_cx = g.counterexample
        if budget.spent_usd >= config.max_cost_usd:
            return SurviveResult("died", rnd + 1, result, last_cx)
        # fight back: freeze the winning reference's differential test into the suite, then rebuild.
        (frozen / f"ref_g{rnd}.py").write_text(g.counterexample.reference_code, encoding="utf-8")
        (frozen / f"test_gauntlet_r{rnd}.py").write_text(
            g.counterexample.diff_test_code.replace("from ref import", f"from ref_g{rnd} import"),
            encoding="utf-8")
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        if not result.success:
            return SurviveResult("died", rnd + 1, result, last_cx)   # couldn't re-converge on the new test
    return SurviveResult("died", config.gauntlet_max_rounds, result, last_cx)
