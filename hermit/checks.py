from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from hermit.scoring import TestResult, FailureInfo


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


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
            passed = proc.returncode == 0
            detail = "" if passed else ((proc.stdout or "") + (proc.stderr or ""))[:800]
        except subprocess.TimeoutExpired:
            passed, detail = False, "check timed out"
        except OSError as e:
            # missing tool, non-executable file, path is a directory, etc.
            passed, detail = False, f"could not run {command[0]!r}: {e}"
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
