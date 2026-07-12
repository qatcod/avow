"""Point-and-go verification report for an existing repository.

`hermit report <repo>` takes a real repo — nested package, its own test suite —
and produces a suite-strength report with no setup: no flat-module surgery, no
hand-written goal. It discovers the source modules and the tests, confirms the
suite is green, mutation-tests the real sources, and reports the score plus the
line-numbered gaps. If the suite is not green on the unmutated repo (missing deps,
fixtures), it says so plainly instead of pretending to have a number.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from hermit.mutation import run_mutation_testing

# Directories that never contain the code-under-test.
_SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "build", "dist", "docs",
              ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules",
              ".hermit", ".eggs", "site-packages"}
_SKIP_NAMES = {"setup.py", "conftest.py"}


def _is_test_file(rel: Path) -> bool:
    return (rel.name.startswith("test_") or rel.name.endswith("_test.py")
            or rel.name == "conftest.py"
            or any(part in ("tests", "test") for part in rel.parts))


def discover(repo) -> tuple[list, list]:
    """(test_files, source_files) for a repo, each a list of paths relative to repo.
    Source excludes tests, setup/conftest, and non-source dirs; tests are the test
    files (and conftest) wherever they live."""
    repo = Path(repo)
    test_files, source_files = [], []
    for p in sorted(repo.rglob("*.py")):
        rel = p.relative_to(repo)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if _is_test_file(rel):
            test_files.append(rel)
        elif rel.name not in _SKIP_NAMES:
            source_files.append(rel)
    return test_files, source_files


@dataclass
class RepoReport:
    baseline_green: bool
    score: float
    total: int
    killed: int
    survivors: list = field(default_factory=list)
    source_files: list = field(default_factory=list)
    test_files: list = field(default_factory=list)
    detail: str = ""


def run_report(repo, config, max_ast_mutants=None) -> RepoReport:
    repo = Path(repo)
    test_files, source_files = discover(repo)
    if not source_files:
        return RepoReport(False, 0.0, 0, 0, detail="no source .py files found under the repo")
    if not test_files:
        return RepoReport(False, 0.0, 0, 0, source_files=source_files,
                          detail="no test files found (looked for test_*.py / *_test.py / tests/)")
    # Grade against the repo's own tests, gathered into a clean dir (preserving layout).
    with tempfile.TemporaryDirectory() as td:
        tests_dir = Path(td) / "suite"
        for rel in test_files:
            dest = tests_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / rel, dest)
        mr = run_mutation_testing(
            repo, tests_dir, config.test_command,
            max_ast_mutants=(max_ast_mutants or config.max_ast_mutants),
            timeout=config.test_timeout_seconds, source_files=source_files)
    return RepoReport(
        baseline_green=mr.baseline_green, score=mr.score, total=mr.total, killed=mr.killed,
        survivors=mr.survivors, source_files=source_files, test_files=test_files,
        detail="" if mr.baseline_green else "the test suite is not green on the unmutated repo "
               "(install deps / fix the suite first) — no score is meaningful until it is")
