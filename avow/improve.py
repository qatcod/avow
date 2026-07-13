# avow/improve.py
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from avow.loop import solve
from avow.ideator import propose_ideas, select_idea
from avow.examiner import split_suite


@dataclass
class ImproveResult:
    success: bool
    expansions: int
    rounds: list
    final: object
    best_round: int = -1
    best_dir: object = None


def _read_test_sources(frozen_dir) -> str:
    frozen_dir = Path(frozen_dir)
    parts = []
    for f in sorted(frozen_dir.glob("test_*.py")):
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _append_tests(dest_dir, tests, round_num) -> None:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(tests):
        stem = Path(t.path).name
        if stem.startswith("test_"):
            name = f"test_e{round_num}_{stem[len('test_'):]}"
        else:
            name = f"test_e{round_num}_{i}_{stem}"
        (dest_dir / name).write_text(t.content, encoding="utf-8")


def _snapshot(src, dest) -> None:
    src, dest = Path(src), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def improve(goal_dir, config, examiner, builder, *, ideator_client=None, escalate=None,
            mutation_client=None, intent_client=None, property_client=None,
            oracle_client=None, now=time.monotonic) -> ImproveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_src = goal_dir / ".avow" / "best"
    lkg = goal_dir / ".avow" / "best_good"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    rounds = [result]
    expansions = 0
    best_round = -1
    best_dir = None
    if result.success and best_src.exists():
        _snapshot(best_src, lkg)
        best_round, best_dir = 0, lkg

    while (result.success and ideator_client is not None
           and expansions < config.max_expand_rounds):
        ideas, _i, _o = propose_ideas(
            goal, _read_test_sources(frozen), ideator_client, config.ideator_model, config.ideas_n)
        chosen, _escalated = select_idea(ideas, escalate)
        if chosen is None:
            break
        if getattr(chosen, "kind", "test") == "check":
            # A check-idea widens the verifier menu: it becomes a standing gate in
            # config.checks (enforced from this round on), not a bespoke test. An
            # empty command is not actionable — stop expanding.
            #
            # Trust note: check_command is LLM-authored and executed by run_checks,
            # the SAME untrusted-code-execution boundary as the Builder (which already
            # runs LLM-written code). The leash (objective + low-risk) gates the idea's
            # SCOPE/RISK, not the command's capability; run it only where you'd run the
            # Builder. A tool allowlist for auto-pursued check-ideas is a future guard.
            if not chosen.check_command:
                break
            config.checks = list(config.checks) + [
                {"name": f"idea_e{expansions + 1}", "command": list(chosen.check_command)}]
        else:
            ex = examiner.write_tests(chosen.description)
            visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
            _append_tests(frozen, visible, expansions + 1)
            _append_tests(holdout, held, expansions + 1)
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        rounds.append(result)
        expansions += 1
        if result.success and best_src.exists():
            _snapshot(best_src, lkg)
            best_round, best_dir = expansions, lkg

    return ImproveResult(success=result.success, expansions=expansions, rounds=rounds,
                         final=result, best_round=best_round, best_dir=best_dir)
