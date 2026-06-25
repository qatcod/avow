from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel

_PROMPT = """\
You are an adversarial QA engineer. Write a rigorous pytest acceptance-test suite \
that verifies the following goal. Your job is to catch every way an implementation \
could be wrong: happy path, edge cases, invalid input, and invariants/properties \
that must hold for ALL inputs (e.g. round-trips, ordering, idempotence) rather than \
only specific input/output pairs.

Rules:
- Tests import the implementation from a top-level module (e.g. `from lib import add`).
- Do NOT include the implementation itself — only tests.
- Each file path is a bare filename like `test_<area>.py` (no directories).
- Prefer property-style assertions over a single hard-coded example where possible.

GOAL:
{goal}
"""


class TestFile(BaseModel):
    path: str
    content: str


class TestSuite(BaseModel):
    test_plan: str
    tests: list[TestFile]


@dataclass
class ExaminerResult:
    suite: TestSuite
    input_tokens: int
    output_tokens: int


class Examiner:
    def __init__(self, client, model: str) -> None:
        self.client = client
        self.model = model

    def write_tests(self, goal: str) -> ExaminerResult:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            messages=[{"role": "user", "content": _PROMPT.format(goal=goal)}],
            output_format=TestSuite,
        )
        usage = response.usage
        return ExaminerResult(
            suite=response.parsed_output,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
        )


def split_suite(tests: list[TestFile], holdout_fraction: float) -> tuple[list[TestFile], list[TestFile]]:
    ordered = sorted(tests, key=lambda t: t.path)
    n = len(ordered)
    k = math.ceil(holdout_fraction * n) if holdout_fraction > 0 else 0
    k = min(k, max(n - 1, 0))  # never empty the visible set
    if k == 0:
        return ordered, []
    return ordered[:-k], ordered[-k:]
