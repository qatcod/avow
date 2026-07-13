from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from avow.scoring import parse_report


class _OraclePair(BaseModel):
    reference_code: str
    diff_test_code: str


_ORACLE_PROMPT = """\
You are building a DIFFERENTIAL ORACLE for a piece of software. Given the GOAL, produce \
two things:

1. reference_code: the SIMPLEST, most OBVIOUSLY-CORRECT implementation of the goal — \
prioritize clarity and correctness over speed or elegance (a naive, slow, plainly-right \
version). It must expose the SAME public function(s) as the goal implies.

2. diff_test_code: a pytest module using the Hypothesis library that imports the clever \
implementation as `from lib import <name> as _sol` and your reference as \
`from ref import <name> as _ref`, then uses `@given(...)` from `hypothesis` with \
strategies matching the goal's input types to assert `_sol(x) == _ref(x)` for all inputs. \
One `@given` test per public function. Do not import anything else from lib/ref. \
If a function can return floats (or contains floats), compare with `math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)` (import `math`) instead of `==`, to avoid floating-point false mismatches; use `==` for exact types (ints, strings, lists, etc.).

The two implementations are written independently so that a disagreement reveals a bug in \
one of them. Make the reference genuinely independent (a different, simpler approach).

GOAL:
{goal}
"""


def generate_oracle(goal: str, client, model: str) -> tuple[_OraclePair | None, int, int]:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": _ORACLE_PROMPT.format(goal=goal)}],
        output_format=_OraclePair,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )


@dataclass
class OracleResult:
    agreement: float | None
    baseline_ok: bool
    counterexample: str
    checked: bool
    input_tokens: int
    output_tokens: int


def _inconclusive(in_tok, out_tok, *, counterexample="") -> "OracleResult":
    return OracleResult(agreement=None, baseline_ok=False, counterexample=counterexample,
                        checked=False, input_tokens=in_tok, output_tokens=out_tok)


def run_oracle_check(solution_dir, goal, client, model, test_command, timeout: int = 120) -> OracleResult:
    pair, in_tok, out_tok = generate_oracle(goal, client, model)
    if pair is None:
        return _inconclusive(in_tok, out_tok)

    with tempfile.TemporaryDirectory(prefix="avow-oracle-") as tmp:
        work = Path(tmp)
        for p in Path(solution_dir).glob("*.py"):
            if p.name.startswith("test_") or p.name == "conftest.py":
                continue
            shutil.copy2(p, work / p.name)
        (work / "ref.py").write_text(pair.reference_code, encoding="utf-8")
        (work / "test_oracle_diff.py").write_text(pair.diff_test_code, encoding="utf-8")
        report = work / "report.json"

        try:
            subprocess.run(
                [*test_command, "--json-report", f"--json-report-file={report}", "test_oracle_diff.py"],
                cwd=work, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _inconclusive(in_tok, out_tok, counterexample="timeout")

        if not report.exists():
            return _inconclusive(in_tok, out_tok)
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _inconclusive(in_tok, out_tok)

        result = parse_report(data)
        if result.errors > 0 or result.total == 0:
            return _inconclusive(in_tok, out_tok)  # broken reference / collection failure
        if result.failed > 0:
            cx = result.failures[0].message[:500] if result.failures else ""
            return OracleResult(0.0, True, cx, True, in_tok, out_tok)
        if result.passed > 0:
            return OracleResult(1.0, True, "", True, in_tok, out_tok)
        return _inconclusive(in_tok, out_tok)  # collected but nothing ran (all skipped/xfail)
