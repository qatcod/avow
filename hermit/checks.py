from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hermit.scoring import TestResult, FailureInfo


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


_METRIC_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_metric(text: str, pattern: str | None) -> float | None:
    """Extract a numeric metric from command output. With ``pattern`` (a regex),
    use capture group 1 if present else the whole match; otherwise the last
    numeric token. Returns None when no number can be read."""
    if pattern:
        m = re.search(pattern, text)
        if m is None:
            return None
        raw = m.group(1) if m.groups() else m.group(0)
    else:
        found = _METRIC_NUMBER.findall(text)
        if not found:
            return None
        raw = found[-1]
    try:
        return float(raw)
    except ValueError:
        return None


def _evaluate_metric(output: str, check) -> tuple[bool, str]:
    value = _parse_metric(output, check.get("pattern"))
    if value is None:
        return False, "could not parse a metric from the check output"
    lo, hi = check.get("min"), check.get("max")
    reasons = []
    if hi is not None and value > hi:
        reasons.append(f"metric {value:g} > max {hi:g}")
    if lo is not None and value < lo:
        reasons.append(f"metric {value:g} < min {lo:g}")
    return (not reasons), ("" if not reasons else "; ".join(reasons))


def run_checks(solution_dir, checks, timeout: int = 120) -> list[CheckResult]:
    """Run each ``{name, command}`` check in ``solution_dir``.

    A check passes iff its command exits 0. Anything that goes wrong — a missing
    tool, a non-executable file, a timeout, or a malformed check entry — is a
    *failed* check, never an exception that aborts the run. This guarantee is
    load-bearing: a single misconfigured check must not lose a long autonomous
    run's budget and progress. The per-check timeout is shared with the test
    timeout (``test_timeout_seconds``); N checks can take up to N×timeout.
    """
    solution_dir = Path(solution_dir)
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
            proc = subprocess.run(command, cwd=solution_dir, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            results.append(CheckResult(name=name, passed=False, detail="check timed out"))
            continue
        except OSError as e:
            # missing tool, non-executable file, path is a directory, etc.
            results.append(CheckResult(name=name, passed=False,
                                       detail=f"could not run {command[0]!r}: {e}"))
            continue
        output = (proc.stdout or "") + (proc.stderr or "")
        if "max" in check or "min" in check:
            # metric check: pass iff the parsed number is within the given bound(s)
            passed, detail = _evaluate_metric(output, check)
        else:
            # exit-code check: pass iff the command exits 0
            passed = proc.returncode == 0
            detail = "" if passed else output[:800]
        results.append(CheckResult(name=name, passed=passed, detail=detail))
    return results


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
