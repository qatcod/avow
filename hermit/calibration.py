"""Calibration harness: measure whether the verifier's confidence is trustworthy.

The verifier reports a confidence number on green solutions. This harness checks
whether that number is CALIBRATED — when it says "trust this," how often is the
solution actually correct? It runs a labeled benchmark (each goal has a correct
reference, injected-bug variants, a deliberately imperfect test suite, and an
independent oracle for ground truth), scores every variant with the real verifier,
and reports the reliability curve plus the false-high-confidence rate — the fraction
of "trusted" solutions that are actually wrong. That last number is the one that
must not silently drift; run this whenever the confidence path changes.
"""
from __future__ import annotations

import importlib.util
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hermit.runner import Runner
from hermit.mutation import run_mutation_testing
from hermit.confidence import aggregate_confidence
from hermit.oracle import run_oracle_check

_BUCKETS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.01)]


@dataclass
class CalibrationGoal:
    name: str
    goal_text: str
    tests: dict            # filename -> content (a fixed, deliberately imperfect suite)
    variants: dict         # variant name -> solution source (1 correct + injected bugs)
    oracle: Callable       # (loaded module) -> bool  : ground-truth correctness, independent of the suite


@dataclass
class CalibrationRow:
    goal: str
    variant: str
    green: bool
    confidence: float | None
    oracle_agreement: float | None
    correct: bool


@dataclass
class CalibrationReport:
    rows: list
    threshold: float

    def _trusted(self, r: CalibrationRow, use_oracle: bool) -> bool:
        if not (r.green and r.confidence is not None and r.confidence >= self.threshold):
            return False
        if use_oracle and r.oracle_agreement == 0.0:
            return False  # oracle floor: an independent-reference disagreement forces not-trusted
        return True

    def false_high_confidence(self, use_oracle: bool = False) -> tuple[int, int]:
        """(# trusted-but-actually-wrong, # trusted). The first number should be ~0."""
        trusted = [r for r in self.rows if self._trusted(r, use_oracle)]
        wrong = [r for r in trusted if not r.correct]
        return len(wrong), len(trusted)

    def reliability(self, use_oracle: bool = False) -> list:
        """[( (lo,hi), (correct, total) )] over confidence buckets of green solutions."""
        green = [r for r in self.rows if r.green and r.confidence is not None
                 and not (use_oracle and r.oracle_agreement == 0.0)]
        out = []
        for lo, hi in _BUCKETS:
            b = [r for r in green if lo <= r.confidence < hi]
            out.append(((lo, hi), (sum(r.correct for r in b), len(b))))
        return out


def _load_module(src: str):
    d = tempfile.mkdtemp()
    p = Path(d) / "lib.py"
    p.write_text(src)
    spec = importlib.util.spec_from_file_location("cal_" + str(abs(hash(src))), p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _evaluate_variant(goal: CalibrationGoal, src: str, config, oracle_client) -> CalibrationRow:
    confidence = None
    oracle_agreement = None
    with tempfile.TemporaryDirectory() as sol, tempfile.TemporaryDirectory() as tst:
        (Path(sol) / "lib.py").write_text(src)
        for fn, content in goal.tests.items():
            (Path(tst) / fn).write_text(content)
        green = Runner(Path(sol), Path(tst), config.test_command,
                       timeout=config.test_timeout_seconds).run().is_green
        if green:
            mr = run_mutation_testing(Path(sol), Path(tst), config.test_command,
                                      max_ast_mutants=config.max_ast_mutants,
                                      timeout=config.test_timeout_seconds)
            mutation = mr.score if mr.baseline_green else None
            files = sorted(goal.tests)
            holdout = None
            if len(files) >= 2:
                with tempfile.TemporaryDirectory() as ho:
                    (Path(ho) / files[-1]).write_text(goal.tests[files[-1]])
                    holdout = Runner(Path(sol), Path(ho), config.test_command,
                                     timeout=config.test_timeout_seconds).run().score
            confidence = aggregate_confidence(
                {"mutation": mutation, "holdout": holdout}, config.confidence_weights).score
            if oracle_client is not None:
                oracle_agreement = run_oracle_check(
                    Path(sol), goal.goal_text, oracle_client, config.oracle_model,
                    config.test_command, config.test_timeout_seconds).agreement
    correct = bool(goal.oracle(_load_module(src)))
    return CalibrationRow(goal=goal.name, variant="", green=green, confidence=confidence,
                          oracle_agreement=oracle_agreement, correct=correct)


def run_calibration(goals, config, oracle_client=None) -> CalibrationReport:
    rows = []
    for g in goals:
        for vname, src in g.variants.items():
            row = _evaluate_variant(g, src, config, oracle_client)
            row.variant = vname
            rows.append(row)
    return CalibrationReport(rows=rows, threshold=config.confidence_threshold)
