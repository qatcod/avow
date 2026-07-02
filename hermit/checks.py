from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermit.scoring import TestResult, FailureInfo

# Builder-authorable tool-config files that could silence a check (loosen a lint,
# relax a type gate) without fixing the code. Stripped in the sandbox when
# strip_config is on. pyproject.toml is deliberately NOT here — it commonly holds
# real dependencies and [tool.*] a goal legitimately needs; removing it would
# break honest projects. Stripping just its [tool.*] tables is a future refinement.
_STRIPPABLE_CONFIG = (
    ".ruff.toml", "ruff.toml", ".flake8", "setup.cfg", "tox.ini",
    "mypy.ini", ".mypy.ini", ".pylintrc", ".isort.cfg",
)


def _strip_config_sandbox(solution_dir: Path, tmp_root: str) -> Path:
    """Copy the solution into an ephemeral dir with builder-authorable tool-config
    removed (at every depth), so a check can't be silenced by loosened config.
    Broken symlinks/special files are tolerated rather than aborting the copy."""
    work = Path(tmp_root) / "solution"
    shutil.copytree(solution_dir, work, symlinks=True, ignore_dangling_symlinks=True)
    for name in _STRIPPABLE_CONFIG:
        for f in work.rglob(name):
            try:
                f.unlink()
            except OSError:
                pass
    return work


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


# A number: optional sign only when NOT glued to a preceding word char/dot/hyphen
# (so "utf-8", "x86-64", "3.12.4" don't yield bogus negatives / wrong tokens);
# digits with optional thousands separators; optional fraction; optional exponent.
_METRIC_NUMBER = re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?")


def _parse_metric(text: str, pattern: str | None) -> float | None:
    """Extract a numeric metric from command output. With ``pattern`` (a regex),
    use capture group 1 when it participated, else the whole match; otherwise the
    last numeric token. Best-effort — steer non-trivial output to an explicit
    ``pattern``. Returns None when no number can be read."""
    if pattern:
        m = re.search(pattern, text)
        if m is None:
            return None
        raw = m.group(1) if (m.groups() and m.group(1) is not None) else m.group(0)
    else:
        found = _METRIC_NUMBER.findall(text)
        if not found:
            return None
        raw = found[-1]
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _coerce_bound(value) -> tuple[bool, float | None]:
    """(ok, number). A present-but-non-numeric bound (e.g. YAML `max: abc`) is a
    misconfig → ok=False; absent/None → (True, None)."""
    if value is None:
        return True, None
    try:
        return True, float(value)
    except (ValueError, TypeError):
        return False, None


def _fmt_metric(v: float) -> str:
    return str(int(v)) if v == int(v) else repr(v)


def _evaluate_metric(output: str, check) -> tuple[bool, str]:
    ok_lo, lo = _coerce_bound(check.get("min"))
    ok_hi, hi = _coerce_bound(check.get("max"))
    if not ok_lo or not ok_hi:
        return False, "check misconfigured: max/min must be numeric"
    if lo is None and hi is None:
        return False, "check misconfigured: a metric check needs a numeric max or min"
    value = _parse_metric(output, check.get("pattern"))
    if value is None:
        return False, "could not parse a metric from the check output"
    reasons = []
    if hi is not None and value > hi:
        reasons.append(f"metric {_fmt_metric(value)} > max {_fmt_metric(hi)}")
    if lo is not None and value < lo:
        reasons.append(f"metric {_fmt_metric(value)} < min {_fmt_metric(lo)}")
    return (not reasons), ("" if not reasons else "; ".join(reasons))


def run_checks(solution_dir, checks, timeout: int = 120,
               strip_config: bool = False) -> list[CheckResult]:
    """Run each ``{name, command}`` check and return a CheckResult per check.

    A check passes iff its command exits 0 (or, when it carries ``max``/``min``,
    its parsed metric is within bounds). Anything that goes wrong — a missing
    tool, a non-executable file, a timeout, or a malformed check entry — is a
    *failed* check, never an exception that aborts the run. This guarantee is
    load-bearing: a single misconfigured check must not lose a long autonomous
    run's budget and progress. The per-check timeout is shared with the test
    timeout (``test_timeout_seconds``); N checks can take up to N×timeout.

    With ``strip_config`` on, checks run in ONE ephemeral copy of the solution (shared
    by all checks this call) with builder-authorable tool-config removed at every depth
    (see ``_STRIPPABLE_CONFIG``), so a check can't be silenced by loosened config; off
    (default) they run in the solution dir unchanged. The copy is per-run overhead —
    keep the solution dir free of large artifacts when enabling it.
    """
    solution_dir = Path(solution_dir)
    if not checks:
        return []

    tmp_root = None
    workdir = solution_dir
    if strip_config:
        try:
            tmp_root = tempfile.mkdtemp(prefix="hermit-check-")
            workdir = _strip_config_sandbox(solution_dir, tmp_root)
        except (OSError, shutil.Error) as e:
            if tmp_root is not None:
                shutil.rmtree(tmp_root, ignore_errors=True)
            # sandbox couldn't be built -> every check fails, but the run survives
            return [CheckResult(name=c.get("name", "check"), passed=False,
                                detail=f"could not build check sandbox: {e}") for c in checks]

    try:
        results: list[CheckResult] = []
        for check in checks:
            name = check.get("name", "check")
            command = check.get("command")
            if not isinstance(command, list) or not command:
                results.append(CheckResult(
                    name=name, passed=False,
                    detail=f"check misconfigured: `command` must be a non-empty list (got {command!r})"))
                continue
            try:
                proc = subprocess.run(command, cwd=workdir, capture_output=True,
                                      text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                results.append(CheckResult(name=name, passed=False, detail="check timed out"))
                continue
            except OSError as e:
                # missing tool, non-executable file, path is a directory, etc.
                results.append(CheckResult(name=name, passed=False,
                                           detail=f"could not run {command[0]!r}: {e}"))
                continue
            if "max" in check or "min" in check:
                # metric check: the command must SUCCEED, then its stdout number must be
                # in bounds. Honoring the exit code + reading stdout only stops a crashing
                # command's stderr traceback number from false-passing the budget.
                if proc.returncode != 0:
                    results.append(CheckResult(
                        name=name, passed=False,
                        detail=f"metric command exited {proc.returncode}: "
                               f"{(proc.stderr or proc.stdout or '').strip()[:400]}"))
                    continue
                passed, detail = _evaluate_metric(proc.stdout or "", check)
            else:
                # exit-code check: pass iff the command exits 0
                passed = proc.returncode == 0
                detail = "" if passed else ((proc.stdout or "") + (proc.stderr or ""))[:800]
            results.append(CheckResult(name=name, passed=passed, detail=detail))
        return results
    finally:
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)


def combine_checks(result: TestResult, check_results) -> TestResult:
    """Fold check outcomes into a new ``TestResult`` so ``score``/``is_green``
    and the Builder's failure feedback reflect the checks alongside the tests.

    Empty ``check_results`` returns ``result`` unchanged (zero behavior change
    when no checks are configured).
    """
    if not check_results:
        return result
    passed = sum(1 for c in check_results if c.passed)
    failed = sum(1 for c in check_results if not c.passed)
    extra = [FailureInfo(nodeid=f"check::{c.name}", message=c.detail)
             for c in check_results if not c.passed]
    return TestResult(
        passed=result.passed + passed,
        failed=result.failed + failed,
        errors=result.errors,
        total=result.total + len(check_results),
        failures=list(result.failures) + extra,
    )
