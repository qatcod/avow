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
from avow.calibration import _evaluate_variant, is_trusted


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
    """A seed pattern was mined from the very goal it is about to be tested on. This is a
    defense-in-depth guard against a programming error (a caller that fails to exclude the held-out
    goal from `mine_goals`); in correct leave-one-out use it never fires."""


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


@dataclass
class Cohort:
    name: str
    wrong: int
    trusted: int


@dataclass
class CalibrationProof:
    plain: Cohort
    survived_empty: Cohort
    survived_seeded: Cohort
    seeded_ran: bool = True   # False when the proof ran without --seed; keeps honesty() from implying
                              # the seeded graveyard was tried and caught nothing

    def honesty(self, min_n: int = 8) -> str:
        """Raw counts always; an 'N x less likely' multiplier ONLY when both compared cohorts have
        trusted >= min_n AND the plain cohort actually had wrong-when-trusted cases to reduce."""
        cohorts = [self.plain, self.survived_empty]
        if self.seeded_ran:
            cohorts.append(self.survived_seeded)
        lines = [f"{c.name}: {c.wrong}/{c.trusted} wrong-when-trusted (n={c.trusted})" for c in cohorts]
        p, e = self.plain, self.survived_empty
        if p.wrong == 0:
            lines.append("no false-high-confidence in the plain cohort — every trusted plain-green "
                         "was correct, so there is nothing for the gauntlet to reduce")
        elif p.trusted >= min_n and e.trusted >= min_n:
            pr, er = p.wrong / p.trusted, e.wrong / e.trusted
            if er > 0:
                lines.append(f"survivors are {pr / er:.1f}x less likely to be wrong than a plain green")
            else:
                lines.append(f"survivors had zero wrong-when-trusted (plain: {pr:.0%})")
        else:
            lines.append(f"insufficient n for a multiplier (need >={min_n}, got "
                         f"plain={p.trusted}, survived={e.trusted}) -- raw counts only")
        if self.seeded_ran:
            lines.append(f"seeded vs empty wrong-when-trusted: {self.survived_seeded.wrong} vs {e.wrong}")
        else:
            lines.append("(seeded cohort not run; pass --seed to measure the graveyard's marginal value)")
        return "\n".join(lines)


@dataclass
class ProofClients:
    scoring_for: object    # goal -> reference client used when scoring a variant's gauntlet
    mining_for: object     # goal -> reference client used when mining a seed pattern
    coroner: object        # client for abstract_counterexample (or None)
    oracle: object         # client for the oracle floor (or None)


def run_calibration_proof(goals, seed_bug_for, config, clients, *, min_n=8, use_oracle=False,
                          with_seed=True) -> CalibrationProof:
    """Score every variant of every goal into three cohorts: plain-green-trusted, survived-trusted with
    an EMPTY graveyard, and survived-trusted with a graveyard SEEDED leave-one-out from the OTHER goals'
    deaths. A variant enters a survived cohort only if it is both trusted AND the gauntlet let it live."""
    plain = Cohort("plain-green", 0, 0)
    survived_empty = Cohort("survived (empty graveyard)", 0, 0)
    survived_seeded = Cohort("survived (seeded graveyard)", 0, 0)

    for g in goals:
        # Seeding is per-goal (leave-one-out over the OTHER goals), not per-variant: mine the seed
        # patterns once and reuse them for every variant of this goal (avoids re-mining N times).
        seed_descriptions = []
        if with_seed:
            mine_goals = [(og, seed_bug_for(og)) for og in goals if og.name != g.name]
            pats = build_seeded_patterns(mine_goals, g.name, config, clients.mining_for, clients.coroner)
            seed_descriptions = [p.description for p in pats]

        for vname, src in g.variants.items():
            row = _evaluate_variant(g, src, config, clients.oracle)
            row.variant = vname
            if not is_trusted(row, config.confidence_threshold, use_oracle):
                continue
            plain.trusted += 1
            plain.wrong += int(not row.correct)

            empty = score_with_gauntlet(g, src, config, clients.scoring_for(g), patterns=[])
            if empty.survived:
                survived_empty.trusted += 1
                survived_empty.wrong += int(not row.correct)

            if with_seed:
                seeded = score_with_gauntlet(g, src, config, clients.scoring_for(g),
                                             patterns=seed_descriptions)
                if seeded.survived:
                    survived_seeded.trusted += 1
                    survived_seeded.wrong += int(not row.correct)

    return CalibrationProof(plain, survived_empty, survived_seeded, seeded_ran=with_seed)
