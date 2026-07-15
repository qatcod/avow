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


def _rename_ref_import(code: str, n: int) -> str:
    """Rewrite a diff test's reference import to a unique per-round module (`ref_g{n}`), so
    freezing several gauntlet references into tests_frozen/ never collides — and never accidentally
    binds to an `oracle_converge_target` `ref.py`. Handles `from ref import ...` and `import ref`."""
    code = re.sub(r"\bfrom\s+ref\s+import\b", f"from ref_g{n} import", code)
    code = re.sub(r"(?<!\w)import\s+ref\b(?!\s+as)", f"import ref_g{n} as ref", code)
    return code


def _run_diff(solution_dir, reference_code, diff_test_code, examples, test_command, timeout) -> tuple:
    """Run ONE reference's differential test against the solution with a raised Hypothesis
    example count. Returns (outcome, falsifying): outcome in {'agree','diverge','unusable'}."""
    # Strip any LLM-authored @settings so the injected high-example profile actually governs the
    # fuzz (a test-level @settings would otherwise override load_profile and silently weaken it).
    diff_test_code = re.sub(r"@settings\([^)]*\)\s*\n?", "", diff_test_code)
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


@dataclass
class GauntletResult:
    survived: bool
    counterexample: Counterexample | None
    references_ok: int
    references_total: int
    input_tokens: int
    output_tokens: int


def run_gauntlet(solution_dir, goal, client, model, test_command, *,
                 k: int = 4, examples: int = 200, timeout: int = 120) -> GauntletResult:
    """Generate K independent references and differential-fuzz each against the solution. If a
    MAJORITY of usable references diverge, the solution is the outlier -> KILL (with a counterexample
    from a diverging reference). Otherwise it survives. A kill is decided purely by execution."""
    if client is None:
        return GauntletResult(True, None, 0, k, 0, 0)   # cannot attack -> survives, nothing gained
    in_tok = out_tok = 0
    agree = 0
    diverging = []   # list of (reference_code, diff_test_code, falsifying)
    for _ in range(max(1, k)):
        pair, i_tok, o_tok = generate_oracle(goal, client, model)
        in_tok += i_tok
        out_tok += o_tok
        if pair is None:
            continue
        outcome, falsifying = _run_diff(solution_dir, pair.reference_code, pair.diff_test_code,
                                        examples, test_command, timeout)
        if outcome == "agree":
            agree += 1
        elif outcome == "diverge":
            diverging.append((pair.reference_code, pair.diff_test_code, falsifying))
        # "unusable" references do not vote
    usable = agree + len(diverging)
    # KILL only when a genuine MAJORITY of USABLE references diverge, AND enough references actually
    # voted. One lone divergent reference (the rest unusable) must never revoke a green: references
    # are LLM-generated and any single one can be the buggy party.
    min_usable = max(2, (k + 1) // 2)
    if usable >= min_usable and len(diverging) * 2 > usable:
        # The majority establishes the SOLUTION is the outlier. We freeze the first diverging
        # reference's test as the regression; it is one of the diverging majority (not cross-vetted
        # as the single most-correct — that refinement is the Coroner's job, sub-project B).
        ref_code, diff_code, falsifying = diverging[0]
        cx = Counterexample(input_repr=falsifying, reference_code=ref_code, diff_test_code=diff_code)
        return GauntletResult(False, cx, usable, k, in_tok, out_tok)
    return GauntletResult(True, None, usable, k, in_tok, out_tok)
