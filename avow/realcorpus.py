"""Real-corpus calibration: build labeled green-but-wrong cases from REAL code.

The toy benchmark hand-authors bug variants. This builds them from a real library
instead, using a trick: a SURVIVING mutant of the library (a code change its own
test suite fails to catch) is a genuine green-but-wrong candidate. Ground truth is
free and independent of the suite: differential-test each surviving mutant against
the original on fuzzed inputs. If it diverges, it is genuinely wrong (this also
discards equivalent mutants, which never diverge). The original library is the
correct case. Scoring every case with the verifier's offline confidence yields a
reliability curve on real code, which is the evidence a calibrated-confidence claim
actually needs.

The caller supplies `agrees(original_dir, variant_dir) -> bool` (True = the variant
matches the original on fuzzed inputs), because how to call and fuzz a library is
library-specific. Everything else is generic.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from avow.runner import Runner
from avow.mutation import ast_mutants, run_mutation_testing
from avow.confidence import aggregate_confidence
from avow.calibration import CalibrationRow


def _offline_confidence(sol_dir, tests_dir, source_files, config) -> float | None:
    """The verifier's offline confidence for a solution: mutation strength, plus a
    hold-out signal when the suite has >= 2 files. None if the suite isn't green."""
    mr = run_mutation_testing(sol_dir, tests_dir, config.test_command,
                              max_ast_mutants=config.max_ast_mutants,
                              timeout=config.test_timeout_seconds, source_files=source_files)
    if not mr.baseline_green:
        return None
    holdout = None
    test_files = sorted(Path(tests_dir).rglob("*.py"))
    if len(test_files) >= 2:
        with tempfile.TemporaryDirectory() as ho:
            shutil.copy2(test_files[-1], Path(ho) / test_files[-1].name)
            holdout = Runner(sol_dir, Path(ho), config.test_command,
                             timeout=config.test_timeout_seconds).run().score
    return aggregate_confidence({"mutation": mr.score, "holdout": holdout},
                                config.confidence_weights).score


def build_real_corpus(source_dir, tests_dir, source_files, agrees, config, *,
                      library="lib", max_cases=12, max_candidates=400) -> list:
    """Return CalibrationRows: the original (correct) plus up to `max_cases` genuinely-
    wrong surviving mutants, each with the verifier's offline confidence. `source_files`
    are paths relative to source_dir; `agrees(original_dir, variant_dir)` compares them."""
    source_dir = Path(source_dir)
    rows = []
    conf0 = _offline_confidence(source_dir, tests_dir, source_files, config)
    rows.append(CalibrationRow(library, "original", green=conf0 is not None,
                               confidence=conf0, oracle_agreement=None, correct=True))

    tried = 0
    found = 0
    for rel in source_files:
        try:
            src = (source_dir / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in ast_mutants(src):
            if found >= max_cases or tried >= max_candidates:
                break
            tried += 1
            with tempfile.TemporaryDirectory() as td:
                variant = Path(td) / "variant"
                shutil.copytree(source_dir, variant)
                (variant / rel).write_text(m.source, encoding="utf-8")
                green = Runner(variant, tests_dir, config.test_command,
                               timeout=config.test_timeout_seconds).run().is_green
                if not green:
                    continue                       # the suite killed it -> correctly rejected, not a case
                if agrees(source_dir, variant):
                    continue                       # equivalent mutant -> not actually wrong, skip
                conf = _offline_confidence(variant, tests_dir, source_files, config)
                rows.append(CalibrationRow(
                    library, f"mut:{m.description}@L{m.line}", green=True,
                    confidence=conf, oracle_agreement=None, correct=False))
                found += 1
    return rows
