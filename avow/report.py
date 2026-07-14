"""Point-and-go verification report for an existing repository.

`avow report <repo>` takes a real repo — nested package, its own test suite —
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

from avow.mutation import run_mutation_testing
from avow.runner import Runner

# Directories that never contain the code-under-test.
_SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "build", "dist", "docs",
              ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules",
              ".avow", ".eggs", "site-packages"}
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


def _expand(repo, paths) -> list:
    """Expand override paths (relative to repo): a dir -> all non-test .py under it; a file -> itself."""
    out = []
    for p in paths:
        full = repo / p
        if full.is_dir():
            out.extend(f.relative_to(repo) for f in sorted(full.rglob("*.py"))
                       if not _is_test_file(f.relative_to(repo)))
        else:
            out.append(Path(p))
    return out


def _capture_baseline_error(repo, config) -> str:
    """Run the repo's own suite in a clean copy and return the tail of its output — so a red
    suite reports WHY (import errors are collection errors that never reach the JSON report)."""
    import subprocess
    with tempfile.TemporaryDirectory() as gd:
        graded = Path(gd) / "repo"
        shutil.copytree(repo, graded, ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", ".avow", ".hermit", "*.egg-info", ".pytest_cache"))
        try:
            proc = subprocess.run(config.test_command, cwd=graded, capture_output=True,
                                  text=True, timeout=config.test_timeout_seconds)
        except (subprocess.TimeoutExpired, OSError) as e:
            return str(e)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()[-2000:]


def _baseline_hint(diag: str) -> str:
    """An actionable message explaining why the suite isn't green, from the real pytest output."""
    head = "the test suite is not green on the unmutated repo, so no score is meaningful yet."
    low = diag.lower()
    last = diag.splitlines()[-1][:300] if diag.strip() else "(no output)"
    if any(k in low for k in ("modulenotfound", "no module named", "importerror")):
        return (head + "\n  -> missing import: install the project first (pip install -e .), or if it's a "
                "src/ layout point --source at the package.\n  " + last)
    if "fixture" in low and "not found" in low:
        return (head + "\n  -> a fixture is missing (likely a conftest that moved): try --tests <dir> to "
                "keep the suite's own layout.\n  " + last)
    if "no tests ran" in low or "collected 0 items" in low:
        return head + "\n  -> no tests were collected: point --tests at the right dir, or the suite needs a plugin/config."
    return head + "\n  first failure:\n  " + last


def run_report(repo, config, max_ast_mutants=None, source_override=None, tests_override=None) -> RepoReport:
    repo = Path(repo)
    if source_override is not None:
        source_files = _expand(repo, source_override)
    else:
        _t, source_files = discover(repo)
    if tests_override is not None:
        test_files = _expand(repo, tests_override) if any((repo / p).is_dir() for p in tests_override) \
            else [Path(p) for p in tests_override]
    else:
        test_files, _s = discover(repo)
    if not source_files:
        return RepoReport(False, 0.0, 0, 0, detail="no source .py files found (point --source at the package)")
    if not test_files:
        return RepoReport(False, 0.0, 0, 0, source_files=source_files,
                          detail="no test files found (point --tests at the test dir; looked for test_*.py / *_test.py / tests/)")
    # Grade against the repo's own tests, gathered into a clean dir (preserving layout).
    with tempfile.TemporaryDirectory() as td:
        tests_dir = Path(td) / "suite"
        for rel in test_files:
            src_path = repo / rel
            targets = sorted(src_path.rglob("*.py")) if src_path.is_dir() else [src_path]
            for f in targets:
                dest = tests_dir / f.relative_to(repo)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
        # Explicit baseline check first, so a red suite reports WHY (actionable) instead of a bare flag.
        baseline = Runner(repo, tests_dir, config.test_command, timeout=config.test_timeout_seconds).run()
        if not baseline.is_green:
            return RepoReport(False, 0.0, 0, 0, source_files=source_files, test_files=test_files,
                              detail=_baseline_hint(_capture_baseline_error(repo, config)))
        mr = run_mutation_testing(
            repo, tests_dir, config.test_command,
            max_ast_mutants=(max_ast_mutants or config.max_ast_mutants),
            timeout=config.test_timeout_seconds, source_files=source_files)
    return RepoReport(
        baseline_green=mr.baseline_green, score=mr.score, total=mr.total, killed=mr.killed,
        survivors=mr.survivors, source_files=source_files, test_files=test_files, detail="")
