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
