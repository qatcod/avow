"""The calibration proof (sub-project C): does the survival gauntlet actually reduce
confident-wrongness, and does a seeded graveyard reduce it further?

This module adds a gauntlet stage and a three-cohort comparison on top of the existing
calibration engine (`avow/calibration.py`, unchanged). It scores each benchmark variant as a
plain green, as a gauntlet-survivor with an EMPTY graveyard, and as a survivor with a graveyard
SEEDED (leave-one-out) from other goals' deaths, then reports false-high-confidence per cohort.

Honesty is the whole point: the report never states an "N x less likely" multiplier the sample
cannot support, and seeding is leave-one-out with a provenance leakage guard so the seeded cohort
cannot be dishonestly inflated. This module MUST NOT import avow/calibration_benchmark.py -- the
CLI wires benchmark data (goals, stub clients) into these generic functions.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from avow.runner import Runner
from avow.gauntlet import run_gauntlet
from avow.coroner import abstract_counterexample


@dataclass
class GauntletScore:
    green: bool
    survived: bool
    references_ok: int


def score_with_gauntlet(goal, src, config, ref_client, patterns) -> GauntletScore:
    """Write `src` as the solution, check it is green under the goal's suite, and if so run the
    gauntlet (K references differentially fuzzed). A non-green source never reaches the gauntlet."""
    with tempfile.TemporaryDirectory() as sol, tempfile.TemporaryDirectory() as tst:
        (Path(sol) / "lib.py").write_text(src)
        for fn, content in goal.tests.items():
            (Path(tst) / fn).write_text(content)
        green = Runner(Path(sol), Path(tst), config.test_command,
                       timeout=config.test_timeout_seconds).run().is_green
        if not green:
            return GauntletScore(green=False, survived=False, references_ok=0)
        g = run_gauntlet(Path(sol), goal.goal_text, ref_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds, patterns=patterns)
        return GauntletScore(green=True, survived=g.survived, references_ok=g.references_ok)


class LeakageError(Exception):
    """A seed pattern was mined from the very goal it is about to be tested on."""


def assert_no_leakage(patterns, held_out_name: str) -> None:
    """Provenance guard: leakage is a seed pattern whose origin IS the held-out goal. Token overlap
    between goals is NOT leakage -- the family deliberately shares boundary tokens, and a pattern from
    another goal helping here is exactly the transfer being measured."""
    for p in patterns:
        if p.origin_goal == held_out_name:
            raise LeakageError(
                f"seed pattern mined from held-out goal '{held_out_name}' -- leave-one-out violated")


def mine_pattern(goal, seed_bug, config, ref_client, coroner_client):
    """Run the gauntlet on `goal`'s known false-green bug to obtain a counterexample, then abstract it
    into a transferable AttackPattern. Provenance is stamped authoritatively (the source goal's name,
    not the LLM's guess) so the leakage guard is reliable."""
    bug_src = goal.variants[seed_bug]
    with tempfile.TemporaryDirectory() as sol:
        (Path(sol) / "lib.py").write_text(bug_src)
        g = run_gauntlet(Path(sol), goal.goal_text, ref_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds, patterns=[])
    if g.counterexample is None:
        return None
    pat, _i, _o = abstract_counterexample(g.counterexample, goal.goal_text, coroner_client, config.coroner_model)
    if pat is None:
        return None
    pat.origin_goal = goal.name
    return pat


def build_seeded_patterns(mine_goals, held_out_name, config, mining_client_for, coroner_client):
    """mine_goals: list of (goal, seed_bug_variant_name), already excluding the held-out goal (the
    caller does the leave-one-out selection). Mines one pattern per goal, enforces the provenance
    leakage guard, and dedups by description."""
    pats = []
    for goal, seed_bug in mine_goals:
        p = mine_pattern(goal, seed_bug, config, mining_client_for(goal), coroner_client)
        if p is not None:
            pats.append(p)
    assert_no_leakage(pats, held_out_name)
    seen, out = set(), []
    for p in pats:
        key = p.description.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
