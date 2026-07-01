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

    A check passes iff its command exits 0. A missing tool or a timeout is a
    *failed* check, not a crash — so a misconfigured check never takes down a run.
    """
    solution_dir = Path(solution_dir)
    results: list[CheckResult] = []
    for check in checks:
        name = check.get("name", "check")
        command = check["command"]
        try:
            proc = subprocess.run(command, cwd=solution_dir, capture_output=True,
                                  text=True, timeout=timeout)
            passed = proc.returncode == 0
            detail = "" if passed else ((proc.stdout or "") + (proc.stderr or ""))[:800]
        except subprocess.TimeoutExpired:
            passed, detail = False, "check timed out"
        except FileNotFoundError:
            passed, detail = False, f"command not found: {command[0] if command else ''}"
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
