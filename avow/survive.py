from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from avow.loop import solve
from avow.gauntlet import run_gauntlet, _rename_ref_import
from avow.graveyard import recent, record, default_graveyard_path
from avow.coroner import abstract_counterexample


@dataclass
class SurviveResult:
    status: str        # verified_survivor | died | not_green | unverified
    rounds: int
    final: object
    death_counterexample: object = None


def survive(goal_dir, config, examiner, builder, *, gauntlet_client, coroner_client=None,
            mutation_client=None, intent_client=None, property_client=None, oracle_client=None,
            now=time.monotonic) -> SurviveResult:
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

    # The gauntlet is seeded with attack patterns learned from past deaths (global Graveyard). An
    # empty or unseeded graveyard leaves reference generation unchanged, so this is a no-op on first
    # runs. Patterns are reloaded at the top of every round so a kill recorded this run seeds the
    # very next fight-back gauntlet, not only future runs.
    graveyard_path = config.graveyard_path or str(default_graveyard_path())

    # Bounded strictly by gauntlet_max_rounds fight-backs. We run one MORE gauntlet than rebuilds so
    # the final rebuilt solution is itself gauntleted (not declared died while actually converged).
    # Cost is bounded: (gauntlet_max_rounds + 1) gauntlets (K references each) + gauntlet_max_rounds
    # re-solves; each re-solve is self-bounded by the config's own max_cost / iterations / wall.
    last_cx = None
    for rnd in range(config.gauntlet_max_rounds + 1):
        patterns = [p.description for p in recent(graveyard_path, config.graveyard_patterns_k)]
        g = run_gauntlet(best_src, goal, gauntlet_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds, patterns=patterns)
        if g.survived:
            return SurviveResult("verified_survivor", rnd, result)
        last_cx = g.counterexample
        # Autopsy: abstract this death into a transferable attack pattern and add it to the global
        # Graveyard. Strictly best-effort — the verdict is already decided by execution above, so an
        # LLM/network/disk failure here must NEVER change it or crash the run. Swallow everything.
        if coroner_client is not None:
            try:
                pat, _i, _o = abstract_counterexample(g.counterexample, goal, coroner_client,
                                                      config.coroner_model)
                if pat is not None:
                    record(pat, graveyard_path)
            except Exception:
                pass
        if rnd == config.gauntlet_max_rounds:
            return SurviveResult("died", rnd, result, last_cx)   # exhausted the fight-back budget
        # fight back: freeze the winning reference's differential test (uniquely named), then rebuild.
        (frozen / f"ref_g{rnd}.py").write_text(g.counterexample.reference_code, encoding="utf-8")
        (frozen / f"test_gauntlet_r{rnd}.py").write_text(
            _rename_ref_import(g.counterexample.diff_test_code, rnd), encoding="utf-8")
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        if not result.success:
            return SurviveResult("died", rnd + 1, result, last_cx)   # couldn't re-converge on the new test
    return SurviveResult("died", config.gauntlet_max_rounds, result, last_cx)   # unreachable
