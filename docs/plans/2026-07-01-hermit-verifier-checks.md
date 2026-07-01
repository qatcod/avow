# Hermit — Verifier Checks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add arbitrary verifier commands (`checks`) as first-class gates alongside the pytest suite — the solution is green only when the tests pass AND every check exits 0; check failures feed the Builder like test failures.

**Architecture:** A new `hermit/checks.py` folds check outcomes into a combined `TestResult`, so the whole moat (score/green/feedback/confidence) works unchanged. One inserted line in the loop. Empty checks (default) → zero behavior change.

**Tech Stack:** Python 3.12 · stdlib `subprocess` · reuses `hermit.scoring`/`hermit.loop`/`hermit.config`.

## Global Constraints

- Python **3.11+** (Hermit-local venv at `/Users/qatadaha/Coding/hermit/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && <cmd>`.
- A check passes iff its command exits 0. `checks` is a list of `{name, command}` (command = list of strings). Default `[]` → no checks → unchanged behavior.
- Reuses `TestResult(passed, failed, errors, total, failures)` (`score`/`is_green` are properties) and `FailureInfo(nodeid, message)` from `hermit.scoring` — do NOT modify scoring.
- **UNTRACKED files must stay uncommitted:** `hermit/openrouter.py`, `tests/test_openrouter.py`. Use SPECIFIC `git add` per task; never `git add -A`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit. Local commits only unless told to push.

---

### Task 1: `checks.py` — run + combine

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/checks.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_checks.py`

**Interfaces:**
- Produces: `CheckResult(name: str, passed: bool, detail: str)`; `run_checks(solution_dir, checks, timeout=120) -> list[CheckResult]`; `combine_checks(result, check_results) -> TestResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checks.py
from hermit.checks import run_checks, combine_checks, CheckResult
from hermit.scoring import TestResult


def test_run_checks_pass_and_fail(tmp_path):
    checks = [
        {"name": "ok", "command": ["python", "-c", "import sys; sys.exit(0)"]},
        {"name": "bad", "command": ["python", "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"]},
    ]
    results = run_checks(tmp_path, checks)
    assert [(c.name, c.passed) for c in results] == [("ok", True), ("bad", False)]
    assert "boom" in results[1].detail


def test_run_checks_missing_command_is_failed_not_crash(tmp_path):
    results = run_checks(tmp_path, [{"name": "nope", "command": ["this_tool_does_not_exist_xyz123"]}])
    assert results[0].passed is False


def test_combine_checks_folds_into_result():
    base = TestResult(passed=2, failed=0, errors=0, total=2, failures=[])
    combined = combine_checks(base, [CheckResult("a", True, ""), CheckResult("b", False, "bad")])
    assert combined.passed == 3 and combined.failed == 1 and combined.total == 4
    assert combined.is_green is False
    assert any("check::b" in f.nodeid for f in combined.failures)


def test_combine_checks_empty_returns_unchanged():
    base = TestResult(passed=1, failed=0, errors=0, total=1, failures=[])
    assert combine_checks(base, []) is base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_checks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.checks'`.

- [ ] **Step 3: Write `hermit/checks.py`**

```python
# hermit/checks.py
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


def run_checks(solution_dir, checks, timeout: int = 120) -> list:
    solution_dir = Path(solution_dir)
    results = []
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_checks.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/checks.py tests/test_checks.py && git commit -m "feat: verifier checks — run arbitrary commands + fold outcomes into the grade"
```

---

### Task 2: `RunConfig.checks`

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/config.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `checks: list = Field(default_factory=list)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.checks == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'checks'`.

- [ ] **Step 3: Edit `hermit/config.py`**

Add after `adjudicate_references_k` (`Field` is already imported):

```python
    checks: list = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/config.py tests/test_config.py && git commit -m "feat: checks setting on RunConfig (empty by default)"
```

---

### Task 3: Loop — fold checks into the grade each iteration

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/loop.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_loop.py`

**Interfaces:**
- No signature change. Imports `run_checks, combine_checks` from `hermit.checks`.

**Edit (read `hermit/loop.py` to confirm the line first):**
- Immediately AFTER `result = runner.run()`, insert:
  ```python
  if config.checks:
      result = combine_checks(result, run_checks(workspace.solution_dir, config.checks, config.test_timeout_seconds))
  ```
  Everything downstream (`result.score`, `result.is_green`, `result.failures`, `best_failures`) then reflects the checks with no other change.
- Add `from hermit.checks import run_checks, combine_checks` near the top.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop.py`:

```python
def test_loop_failing_check_gates_green(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0,
                    checks=[{"name": "gate", "command": ["python", "-c", "import sys; sys.exit(1)"]}])
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    # the solution passes the pytest suite, but the always-failing check gates green
    assert r.success is False


def test_loop_passing_check_stays_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0,
                    checks=[{"name": "ok", "command": ["python", "-c", "import sys; sys.exit(0)"]}])
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True and r.reason == "green"


def test_loop_no_checks_unchanged(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)   # checks=[] default
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py::test_loop_failing_check_gates_green -q`
Expected: FAIL — the run goes green (checks not wired → the always-fail check is ignored).

- [ ] **Step 3: Apply the edits to `hermit/loop.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py -q`
Expected: PASS — the three new tests + all existing loop tests (which use `checks=[]` → `combine_checks` returns the result unchanged → identical behavior).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/loop.py tests/test_loop.py && git commit -m "feat: fold verifier checks into the grade each iteration (checks gate green + feed the Builder)"
```

---

### Task 4: `hermit check` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/cli.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_cli_check.py`

**Interfaces:**
- New subcommand: `hermit check <solution_dir> [--config forge.yaml]`. Runs the configured checks on the solution and prints each pass/fail; exit 0 if all pass, 2 otherwise. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_check.py
from pathlib import Path
import hermit.cli as cli


def test_check_cli(tmp_path, capsys):
    cfg = tmp_path / "hermit.yaml"
    cfg.write_text(
        'checks:\n'
        '  - name: ok\n'
        '    command: ["python", "-c", "import sys; sys.exit(0)"]\n'
        '  - name: bad\n'
        '    command: ["python", "-c", "import sys; sys.exit(1)"]\n')
    sol = tmp_path / "sol"
    sol.mkdir()
    rc = cli.main(["check", str(sol), "--config", str(cfg)])
    out = capsys.readouterr().out
    assert "ok: PASS" in out
    assert "bad: FAIL" in out
    assert rc == 2   # a check failed


def test_check_cli_no_checks(tmp_path, capsys):
    rc = cli.main(["check", str(tmp_path)])   # no --config -> default RunConfig, checks=[]
    out = capsys.readouterr().out
    assert rc == 0 and "no checks" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_check.py -q`
Expected: FAIL — argparse `invalid choice: 'check'`.

- [ ] **Step 3: Edit `hermit/cli.py`**

Add the subparser inside `main` (after the `adjudicate` subparser, before `parse_args`):

```python
    check_p = sub.add_parser("check", help="run the configured verifier checks (lint/typecheck/audit/...) on a solution")
    check_p.add_argument("solution_dir")
    check_p.add_argument("--config", default=None)
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "check":
        return _cmd_check(args)
```

Add the handler at module level:

```python
def _cmd_check(args) -> int:
    from hermit.checks import run_checks

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    if not config.checks:
        print("no checks configured (add a `checks:` list to your config)")
        return 0
    results = run_checks(Path(args.solution_dir), config.checks, config.test_timeout_seconds)
    for c in results:
        line = f"  {c.name}: {'PASS' if c.passed else 'FAIL'}"
        if not c.passed and c.detail:
            line += f"  — {c.detail.strip().splitlines()[0][:140]}"
        print(line)
    return 0 if all(c.passed for c in results) else 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_check.py tests/test_cli.py -q`
Expected: PASS (check CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q && hermit --help`
Expected: all tests PASS, 0 warnings; `hermit --help` lists `check` among the verbs.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/cli.py tests/test_cli_check.py && git commit -m "feat: hermit check CLI — run the configured verifier checks on a solution"
```

---

## Manual validation (after Task 4)

Write a `hermit.yaml` with `checks: [{name: lint, command: ["ruff", "check", "."]}, {name: types, command: ["python","-m","mypy","lib.py"]}]`, then `hermit solve <goal>` — the Builder must now produce code that passes the tests AND lints clean AND typechecks. `hermit check <solution>` reports the checks standalone.

## What this deliberately does NOT do (later)

- Metric-threshold checks (parse a number, compare to a budget).
- Stripping builder tool-config for stronger anti-cheat.
- The Ideator proposing checks; rubric / cross-provider-panel checks for subjective quality.
