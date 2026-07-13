# Avow — Grounded Conflict Adjudicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** When a build stalls just short of green, decide *by execution* whether each failing test is a `solution_bug` or a `test_bug` — by running the failing tests against K independent reference implementations and taking the majority.

**Architecture:** A new `avow/adjudicator.py` (reuses `generate_oracle` for references + `parse_report`), a loop hook that surfaces suspected bad tests at a non-green exit, and a `avow adjudicate` CLI. The verdict is grounded in execution; the LLM only generates references.

**Tech Stack:** Python 3.12 · `anthropic` (via `generate_oracle`) · `pytest-json-report` · reuses `avow.oracle`/`avow.scoring`/`avow.loop`/`avow.config`.

## Global Constraints

- Python **3.11+** (Avow-local venv at `/Users/qatadaha/Coding/avow/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && <cmd>`.
- **The verdict is execution-grounded** — the LLM (`generate_oracle`) only *generates* references; whether a reference passes/fails a test is decided by *running* it. Advisory only (never edits a test).
- **Off by default** (`adjudicate_enabled=False`) — existing behavior unchanged when disabled / no client.
- Reuses verified interfaces (do NOT modify): `generate_oracle(goal, client, model) -> (_OraclePair|None, int, int)` from `avow.oracle` (`_OraclePair.reference_code` is a `lib.py`-compatible simplest-correct impl); `parse_report` from `avow.scoring`; `solve(...)`/`SolveResult`; `Runner`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `adjudicator.py` — grounded adjudication core

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/adjudicator.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_adjudicator.py`

**Interfaces:**
- Produces: `TestVerdict(test_id, verdict, references_failed, references_total)`; `AdjudicationResult(verdicts, references_ok, input_tokens, output_tokens)`; `_run_tests_against(impl_code, frozen_dir, failing_nodeids, test_command, timeout) -> dict[nodeid,str]`; `adjudicate_failures(goal, frozen_dir, failing_nodeids, client, model, test_command, k=3, timeout=120) -> AdjudicationResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adjudicator.py
from pathlib import Path
from types import SimpleNamespace
from avow.adjudicator import adjudicate_failures
from avow.oracle import _OraclePair

CMD = ["python", "-m", "pytest", "-q"]


def _ref_client(reference_code="def add(a, b):\n    return a + b\n"):
    class C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=_OraclePair(reference_code=reference_code, diff_test_code="x"),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return C()


def test_flags_contradictory_test_as_test_bug(tmp_path):
    # a test that NO correct add can pass -> the independent references also fail it
    (tmp_path / "test_bad.py").write_text("from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n")
    r = adjudicate_failures("build add(a, b)", tmp_path, ["test_bad.py::test_bad"],
                            _ref_client(), "m", CMD, k=3)
    assert len(r.verdicts) == 1
    v = r.verdicts[0]
    assert v.verdict == "test_bug"
    assert v.references_failed == 3 and v.references_total == 3


def test_flags_real_failure_as_solution_bug(tmp_path):
    # a correct test the reference PASSES -> the solution that failed it is the outlier
    (tmp_path / "test_good.py").write_text("from lib import add\ndef test_good():\n    assert add(2, 3) == 5\n")
    r = adjudicate_failures("build add(a, b)", tmp_path, ["test_good.py::test_good"],
                            _ref_client(), "m", CMD, k=3)
    assert r.verdicts[0].verdict == "solution_bug"
    assert r.verdicts[0].references_failed == 0


def test_noop_without_client_or_failures(tmp_path):
    assert adjudicate_failures("g", tmp_path, ["x::y"], None, "m", CMD, k=3).verdicts == []
    assert adjudicate_failures("g", tmp_path, [], _ref_client(), "m", CMD, k=3).verdicts == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_adjudicator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.adjudicator'`.

- [ ] **Step 3: Write `avow/adjudicator.py`**

```python
# avow/adjudicator.py
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from avow.oracle import generate_oracle


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
    with tempfile.TemporaryDirectory(prefix="avow-adj-") as tmp:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_adjudicator.py -q`
Expected: PASS (3 passed). (Runs real pytest subprocesses per reference — venv must be active.)

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/adjudicator.py tests/test_adjudicator.py && git commit -m "feat: grounded conflict adjudicator — run failing tests against K independent references"
```

---

### Task 2: `RunConfig` adjudicator settings

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/config.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `adjudicate_enabled: bool = False`, `adjudicate_model: str = "claude-opus-4-8"`, `adjudicate_threshold: float = 0.9`, `adjudicate_references_k: int = 3`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.adjudicate_enabled is False
    assert cfg.adjudicate_model == "claude-opus-4-8"
    assert cfg.adjudicate_threshold == 0.9
    assert cfg.adjudicate_references_k == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'adjudicate_enabled'`.

- [ ] **Step 3: Edit `avow/config.py`**

Add after `oracle_converge_target`:

```python
    adjudicate_enabled: bool = False
    adjudicate_model: str = "claude-opus-4-8"
    adjudicate_threshold: float = 0.9
    adjudicate_references_k: int = 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: conflict-adjudicator settings on RunConfig (off by default)"
```

---

### Task 3: Loop hook — surface suspected bad tests at a non-green exit

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/loop.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_loop.py`

**Interfaces:**
- `solve` gains keyword-only `adjudicator_client=None` (after `supervisor_client=None`). Imports `adjudicate_failures` from `avow.adjudicator`. `SolveResult` gains `suspected_bad_tests: list = field(default_factory=list)` (after the last field).

**Edits (read `avow/loop.py` to confirm the exact lines first):**
- The loop's non-green exit is the single `return SolveResult(False, best_score, budget.iterations, reason, best_dir if have_best else None, ...)` AFTER the `while True:` loop (the plateau/budget/supervisor exit). Immediately BEFORE that return, insert:
  ```python
  suspected_bad_tests = []
  if (config.adjudicate_enabled and adjudicator_client is not None
          and have_best and best_score >= config.adjudicate_threshold and best_failures):
      before = budget.spent_usd
      adj = adjudicate_failures(
          goal, frozen, [f.nodeid for f in best_failures], adjudicator_client,
          config.adjudicate_model, config.test_command,
          k=config.adjudicate_references_k, timeout=config.test_timeout_seconds)
      budget.charge_tokens(config.adjudicate_model, adj.input_tokens, adj.output_tokens)
      suspected_bad_tests = [v.test_id for v in adj.verdicts if v.verdict == "test_bug"]
      log.record(AttemptRecord(
          iteration=budget.iterations, score=best_score, is_green=False,
          diff_summary=f"adjudicated {len(adj.verdicts)} failing test(s); suspected bad: {suspected_bad_tests}",
          failing=suspected_bad_tests, plan="adjudicate", cost_usd=budget.spent_usd - before))
  ```
  and pass `suspected_bad_tests=suspected_bad_tests` to that `SolveResult(...)` return.
- (`best_failures` is the list of `FailureInfo` for the best solution — already tracked by the loop. `frozen` and `log` and `goal` are in scope.)
- Add `from avow.adjudicator import adjudicate_failures` near the top.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop.py`:

```python
def test_loop_adjudicator_flags_examiner_bad_test(tmp_path):
    from types import SimpleNamespace
    from avow.oracle import _OraclePair

    class BadTestExaminer:
        def write_tests(self, goal):
            return ExaminerResult(suite=TestSuite(test_plan="add", tests=[
                TestFile(path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n"),
                TestFile(path="test_bad.py", content="from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n"),
            ]), input_tokens=0, output_tokens=0)

    class CorrectBuilder:
        def attempt(self, solution_dir, goal, failures):
            from pathlib import Path as _P
            from avow.builder import BuilderOutcome
            (_P(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    class RefClient:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=_OraclePair(reference_code="def add(a, b):\n    return a + b\n", diff_test_code="x"),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0,
                    adjudicate_enabled=True, adjudicate_threshold=0.4, adjudicate_references_k=2)
    r = solve(_goal(tmp_path), cfg, BadTestExaminer(), CorrectBuilder(), now=lambda: 0.0,
              adjudicator_client=RefClient())
    # the correct a+b solution can't pass the contradictory test_bad -> never green
    assert r.success is False
    # ...but the adjudicator ran a reference and flagged test_bad as the Examiner's bug:
    assert any("test_bad" in t for t in r.suspected_bad_tests)


def test_loop_adjudicator_off_by_default(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, plateau_patience=2)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.suspected_bad_tests == []   # disabled + no client -> never runs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_loop.py::test_loop_adjudicator_flags_examiner_bad_test -q`
Expected: FAIL — `TypeError: solve() got an unexpected keyword argument 'adjudicator_client'`.

- [ ] **Step 3: Apply the edits above to `avow/loop.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_loop.py -q`
Expected: PASS — the two new tests + all existing loop tests (which pass no `adjudicator_client` + leave it disabled → the hook never fires → identical behavior).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/loop.py tests/test_loop.py && git commit -m "feat: loop surfaces suspected Examiner-bad tests via the adjudicator on a close non-green exit"
```

---

### Task 4: `avow adjudicate` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/cli.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_cli_adjudicate.py`

**Interfaces:**
- New subcommand: `avow adjudicate <solution_dir> <tests_dir> <goal_file> [--config]`. Grades the solution against the tests (via `Runner`) to find failures, runs `adjudicate_failures`, and prints a per-failing-test verdict. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_adjudicate.py
from pathlib import Path
from types import SimpleNamespace
import avow.cli as cli
from avow.oracle import _OraclePair


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        return SimpleNamespace(
            parsed_output=_OraclePair(reference_code="def add(a, b):\n    return a + b\n", diff_test_code="x"),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_adjudicate_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a + b\n")          # correct solution
    tests = tmp_path / "tests"; tests.mkdir()
    (tests / "test_bad.py").write_text("from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n")  # contradictory

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["adjudicate", str(sol), str(tests), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "test_bad" in out and "TEST BUG" in out.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_adjudicate.py -q`
Expected: FAIL — argparse `invalid choice: 'adjudicate'`.

- [ ] **Step 3: Edit `avow/cli.py`**

Add the subparser inside `main` (after the `supervise` subparser, before `parse_args`):

```python
    adj_p = sub.add_parser("adjudicate",
                           help="for a stalled build: decide (by execution) which failing tests are the Examiner's bug")
    adj_p.add_argument("solution_dir")
    adj_p.add_argument("tests_dir")
    adj_p.add_argument("goal_file")
    adj_p.add_argument("--config", default=None)
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "adjudicate":
        return _cmd_adjudicate(args)
```

Add the handler at module level:

```python
def _cmd_adjudicate(args) -> int:
    import anthropic
    from avow.adjudicator import adjudicate_failures
    from avow.runner import Runner

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    result = Runner(Path(args.solution_dir), Path(args.tests_dir), config.test_command,
                    timeout=config.test_timeout_seconds).run()
    if not result.failures:
        print("no failing tests — nothing to adjudicate")
        return 0
    failing = [f.nodeid for f in result.failures]
    adj = adjudicate_failures(goal, Path(args.tests_dir), failing, anthropic.Anthropic(),
                              config.adjudicate_model, config.test_command,
                              k=config.adjudicate_references_k, timeout=config.test_timeout_seconds)
    labels = {"test_bug": "TEST BUG", "solution_bug": "solution bug", "inconclusive": "inconclusive"}
    for v in adj.verdicts:
        print(f"  {v.test_id}: {labels[v.verdict]}  "
              f"({v.references_failed}/{v.references_total} independent references also fail it)")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_adjudicate.py tests/test_cli.py -q`
Expected: PASS (adjudicate CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q && avow --help`
Expected: all tests PASS, 0 warnings; `avow --help` lists `adjudicate` among the verbs.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/cli.py tests/test_cli_adjudicate.py && git commit -m "feat: avow adjudicate CLI — grounded test-vs-solution conflict report"
```

---

## Manual validation (after Task 4, with credentials)

Point it at the Roman-numeral stall: `avow adjudicate <best> <tests_frozen> goal.md` → it should print `test_m_count: TEST BUG — k/k independent references also fail it`, proving by execution that no correct implementation passes that test.

## What this deliberately does NOT do (later)

- Auto-fix a flagged test (stays advisory + human-adjudicated).
- An interactive keep/fix/skip TUI.
- Shrinking a failing property test to a specific counterexample input.
