from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from avow.oracle import generate_oracle
from avow.scoring import parse_report

_FALSIFYING_RE = re.compile(r"Falsifying example:\s*(.+)")


@dataclass
class Counterexample:
    input_repr: str        # the Hypothesis falsifying example, for the human-facing report
    reference_code: str    # a majority reference's implementation (the regression's ground truth)
    diff_test_code: str    # that reference's differential test (imports `from ref import ...`)


def _extract_falsifying_example(pytest_output: str) -> str:
    m = _FALSIFYING_RE.search(pytest_output or "")
    return m.group(1).strip() if m else ""


def _run_diff(solution_dir, reference_code, diff_test_code, examples, test_command, timeout) -> tuple:
    """Run ONE reference's differential test against the solution with a raised Hypothesis
    example count. Returns (outcome, falsifying): outcome in {'agree','diverge','unusable'}."""
    with tempfile.TemporaryDirectory(prefix="avow-gauntlet-") as tmp:
        work = Path(tmp)
        for p in Path(solution_dir).glob("*.py"):
            if p.name.startswith("test_") or p.name == "conftest.py":
                continue
            shutil.copy2(p, work / p.name)
        (work / "ref.py").write_text(reference_code, encoding="utf-8")
        (work / "test_gdiff.py").write_text(diff_test_code, encoding="utf-8")
        (work / "conftest.py").write_text(
            "from hypothesis import settings\n"
            f"settings.register_profile('g', max_examples={examples}, deadline=None)\n"
            "settings.load_profile('g')\n", encoding="utf-8")
        report = work / "report.json"
        try:
            proc = subprocess.run(
                [*test_command, "--json-report", f"--json-report-file={report}", "test_gdiff.py"],
                cwd=work, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "unusable", ""
        if not report.exists():
            return "unusable", ""
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "unusable", ""
        result = parse_report(data)
        if result.errors > 0 or result.total == 0:
            return "unusable", ""      # broken / wrong-interface reference is not a usable vote
        if result.failed > 0:
            msg = result.failures[0].message if result.failures else ""
            combined = (proc.stdout or "") + (proc.stderr or "") + (msg or "")
            return "diverge", _extract_falsifying_example(combined)
        if result.passed > 0:
            return "agree", ""
        return "unusable", ""
