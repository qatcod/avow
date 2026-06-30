# hermit/adjudicator.py
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermit.oracle import generate_oracle


@dataclass
class TestVerdict:
    test_id: str
    verdict: str  # "test_bug" | "solution_bug" | "inconclusive"
    references_failed: int
    references_total: int


@dataclass
class AdjudicationResult:
    verdicts: list
    references_ok: int
    input_tokens: int
    output_tokens: int


def _basename_key(nodeid: str) -> str:
    # nodeids may carry a directory prefix from the grading cwd (e.g. "tests/test_x.py::t");
    # the adjudicator runs tests top-level, so match on basename::testfunc.
    parts = nodeid.split("::")
    return "::".join([Path(parts[0]).name, *parts[1:]])


def _run_tests_against(impl_code, frozen_dir, failing_nodeids, test_command, timeout: int = 120) -> dict:
    """Write `impl_code` as lib.py + the failing test files into a temp dir, run them, and
    return {nodeid: outcome} ('passed'/'failed'/'error'/'missing') for each failing nodeid,
    matched by basename::testfunc so a grading-cwd prefix on the nodeid doesn't break lookup."""
    frozen_dir = Path(frozen_dir)
    files = sorted({Path(nid.split("::")[0]).name for nid in failing_nodeids})
    with tempfile.TemporaryDirectory(prefix="hermit-adj-") as tmp:
        work = Path(tmp)
        (work / "lib.py").write_text(impl_code, encoding="utf-8")
        for fname in files:
            src = frozen_dir / fname
            if src.exists():
                shutil.copy2(src, work / fname)
        for helper in ("ref.py", "conftest.py"):  # support modules the tests may import
            h = frozen_dir / helper
            if h.exists():
                shutil.copy2(h, work / helper)
        report = work / "report.json"
        try:
            subprocess.run(
                [*test_command, "--json-report", f"--json-report-file={report}", *files],
                cwd=work, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {nid: "error" for nid in failing_nodeids}
        if not report.exists():
            return {nid: "error" for nid in failing_nodeids}
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {nid: "error" for nid in failing_nodeids}
        by_key = {_basename_key(t.get("nodeid", "")): t.get("outcome", "error")
                  for t in data.get("tests", [])}
        return {nid: by_key.get(_basename_key(nid), "missing") for nid in failing_nodeids}


def adjudicate_failures(goal, frozen_dir, failing_nodeids, client, model, test_command,
                        k: int = 3, timeout: int = 120) -> AdjudicationResult:
    if client is None or not failing_nodeids:
        return AdjudicationResult(verdicts=[], references_ok=0, input_tokens=0, output_tokens=0)

    in_tok = out_tok = 0
    ref_outcomes = []
    for _ in range(max(1, k)):
        pair, i_tok, o_tok = generate_oracle(goal, client, model)
        in_tok += i_tok
        out_tok += o_tok
        if pair is None:
            continue
        outcomes = _run_tests_against(pair.reference_code, frozen_dir, failing_nodeids, test_command, timeout)
        if all(v in ("error", "missing") for v in outcomes.values()):
            continue  # a broken / wrong-interface reference is not a usable vote
        ref_outcomes.append(outcomes)

    verdicts = []
    for nid in failing_nodeids:
        usable = [ro[nid] for ro in ref_outcomes if ro.get(nid) in ("passed", "failed")]
        failed = sum(1 for v in usable if v == "failed")
        passed = sum(1 for v in usable if v == "passed")
        if failed > passed:
            verdict = "test_bug"
        elif passed > failed:
            verdict = "solution_bug"
        else:
            verdict = "inconclusive"
        verdicts.append(TestVerdict(test_id=nid, verdict=verdict,
                                    references_failed=failed, references_total=len(usable)))
    return AdjudicationResult(verdicts=verdicts, references_ok=len(ref_outcomes),
                              input_tokens=in_tok, output_tokens=out_tok)
