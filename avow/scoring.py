from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureInfo:
    nodeid: str
    message: str


@dataclass
class TestResult:
    __test__ = False
    passed: int
    failed: int
    errors: int
    total: int
    failures: list[FailureInfo] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def is_green(self) -> bool:
        return self.total > 0 and self.failed == 0 and self.errors == 0


def parse_report(report: dict) -> TestResult:
    tests = report.get("tests", [])
    passed = failed = errors = 0
    failures: list[FailureInfo] = []
    for t in tests:
        outcome = t.get("outcome")
        if outcome == "passed":
            passed += 1
        elif outcome == "error":
            errors += 1
            failures.append(FailureInfo(t.get("nodeid", "?"), _longrepr(t)))
        else:  # "failed" and any non-passing terminal outcome
            failed += 1
            failures.append(FailureInfo(t.get("nodeid", "?"), _longrepr(t)))
    return TestResult(passed=passed, failed=failed, errors=errors,
                      total=len(tests), failures=failures)


def _longrepr(test: dict) -> str:
    for phase in ("call", "setup", "teardown"):
        section = test.get(phase) or {}
        rep = section.get("longrepr")
        if rep:
            return str(rep)
    return test.get("outcome", "unknown")
