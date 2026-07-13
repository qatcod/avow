# Avow v1 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest Avow that closes the loop end-to-end: an Examiner agent writes a frozen acceptance-test suite from a goal, a Builder agent (headless `claude -p`) edits code in an isolated workspace until those tests pass, with a deterministic outer loop enforcing non-regression, budget caps, and stop conditions — all observable in a run log.

**Architecture:** A deterministic Python outer loop drives two LLM agents through injectable interfaces. The Builder runs as a `claude -p --output-format json` subprocess in a snapshot-based workspace and never sees the tests. The Examiner uses the `anthropic` SDK's structured outputs to emit test files. Every LLM/subprocess boundary is injectable so the loop logic is fully unit-testable without network or tokens.

**Tech Stack:** Python 3.12 · `anthropic` SDK (structured outputs) · `claude` CLI subprocess · `pytest` + `pytest-json-report` · `pydantic` · `pyyaml`.

## Global Constraints

- Python **3.11+** (target 3.12; the local venv at `/Users/qatadaha/Coding/.venv` is 3.12).
- Model IDs are **exact strings, no date suffixes**: `claude-opus-4-8` (default), `claude-sonnet-4-6`, `claude-haiku-4-5`.
- Default Builder model: `claude-opus-4-8`. Default Examiner model: `claude-sonnet-4-6` (a *different* model from the Builder, for decorrelated blind spots).
- Examiner uses the `anthropic` SDK **structured outputs** path (`client.messages.parse(..., output_format=PydanticModel)` → `response.parsed_output`). Do **not** set `temperature`/`top_p`/`top_k` (rejected with 400 on Opus 4.8 / Sonnet 4.6).
- **Anti-cheat (load-bearing):** the Builder never sees or edits the tests. Test files live outside the Builder's workspace and are **restored fresh before every test run**.
- **Hard budget cap** (cost USD / iterations / wall-clock) — the loop must be physically unable to run away.
- Every LLM/subprocess call is behind an **injectable seam**; unit tests use fakes and never hit the network or spend tokens.
- Project home: `/Users/qatadaha/Coding/avow/`. Package: `avow/`. Tests: `tests/`.
- **No `git commit` without the user's explicit go-ahead** (standing user rule). Each task's final step prepares a commit; the human runs it only when greenlit.

---

### Task 1: Project scaffold + RunConfig

**Files:**
- Create: `/Users/qatadaha/Coding/avow/pyproject.toml`
- Create: `/Users/qatadaha/Coding/avow/avow/__init__.py`
- Create: `/Users/qatadaha/Coding/avow/avow/config.py`
- Create: `/Users/qatadaha/Coding/avow/tests/__init__.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- Produces: `RunConfig` (pydantic model) with fields `builder_model: str`, `examiner_model: str`, `max_iterations: int`, `plateau_patience: int`, `max_cost_usd: float`, `max_wall_seconds: int`, `test_command: list[str]`, `holdout_fraction: float`; classmethod `RunConfig.from_yaml(path: str | Path) -> RunConfig` (missing file → all defaults).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path
from avow.config import RunConfig


def test_defaults_are_sane():
    cfg = RunConfig()
    assert cfg.builder_model == "claude-opus-4-8"
    assert cfg.examiner_model == "claude-sonnet-4-6"
    assert cfg.max_iterations == 12
    assert cfg.plateau_patience == 3
    assert cfg.max_cost_usd == 10.0
    assert cfg.max_wall_seconds == 3600
    assert cfg.test_command == ["python", "-m", "pytest", "-q"]
    assert cfg.holdout_fraction == 0.25


def test_from_yaml_overrides_then_falls_back(tmp_path: Path):
    p = tmp_path / "avow.yaml"
    p.write_text("max_iterations: 5\nbuilder_model: claude-sonnet-4-6\n")
    cfg = RunConfig.from_yaml(p)
    assert cfg.max_iterations == 5
    assert cfg.builder_model == "claude-sonnet-4-6"
    assert cfg.examiner_model == "claude-sonnet-4-6"  # default retained


def test_from_yaml_missing_file_is_all_defaults(tmp_path: Path):
    cfg = RunConfig.from_yaml(tmp_path / "nope.yaml")
    assert cfg.max_iterations == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow'`.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
# pyproject.toml
[project]
name = "avow"
version = "0.1.0"
description = "Autonomous build-and-improve loop"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.69",
    "pydantic>=2.6",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-json-report>=1.5"]

[project.scripts]
avow = "avow.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["avow*"]
```

- [ ] **Step 4: Write the package init files**

```python
# avow/__init__.py
__all__ = []
```

```python
# tests/__init__.py
```

- [ ] **Step 5: Write `RunConfig`**

```python
# avow/config.py
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    builder_model: str = "claude-opus-4-8"
    examiner_model: str = "claude-sonnet-4-6"
    max_iterations: int = 12
    plateau_patience: int = 3
    max_cost_usd: float = 10.0
    max_wall_seconds: int = 3600
    test_command: list[str] = Field(default_factory=lambda: ["python", "-m", "pytest", "-q"])
    holdout_fraction: float = 0.25

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RunConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text()) or {}
        return cls(**data)
```

- [ ] **Step 6: Install and run tests**

Run: `cd /Users/qatadaha/Coding/avow && pip install -e ".[dev]" && python -m pytest tests/test_config.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add pyproject.toml avow/__init__.py avow/config.py tests/__init__.py tests/test_config.py && git commit -m "feat: scaffold avow package and RunConfig"
```

---

### Task 2: Scoring — parse pytest-json-report into a TestResult

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/scoring.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_scoring.py`

**Interfaces:**
- Consumes: a pytest-json-report dict (from the `pytest-json-report` plugin's `.report.json`).
- Produces: `FailureInfo(nodeid: str, message: str)`; `TestResult(passed: int, failed: int, errors: int, total: int, failures: list[FailureInfo])` with `@property score: float` (passed/total, 0.0 if total==0) and `@property is_green: bool` (total>0 and failed==0 and errors==0); `parse_report(report: dict) -> TestResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring.py
from avow.scoring import parse_report, TestResult, FailureInfo


def _report(tests):
    return {"summary": {"total": len(tests)}, "tests": tests}


def test_all_pass_is_green():
    r = parse_report(_report([
        {"nodeid": "tests/test_a.py::test_one", "outcome": "passed"},
        {"nodeid": "tests/test_a.py::test_two", "outcome": "passed"},
    ]))
    assert r.passed == 2 and r.failed == 0 and r.errors == 0 and r.total == 2
    assert r.score == 1.0
    assert r.is_green is True
    assert r.failures == []


def test_partial_credit_and_failure_messages():
    r = parse_report(_report([
        {"nodeid": "t::a", "outcome": "passed"},
        {"nodeid": "t::b", "outcome": "failed",
         "call": {"longrepr": "AssertionError: expected 3 got 4"}},
        {"nodeid": "t::c", "outcome": "error",
         "setup": {"longrepr": "ImportError: no module foo"}},
    ]))
    assert r.passed == 1 and r.failed == 1 and r.errors == 1 and r.total == 3
    assert r.score == 1 / 3
    assert r.is_green is False
    msgs = {f.nodeid: f.message for f in r.failures}
    assert "expected 3 got 4" in msgs["t::b"]
    assert "no module foo" in msgs["t::c"]


def test_empty_suite_scores_zero_and_is_not_green():
    r = parse_report(_report([]))
    assert r.total == 0 and r.score == 0.0 and r.is_green is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.scoring'`.

- [ ] **Step 3: Write `scoring.py`**

```python
# avow/scoring.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureInfo:
    nodeid: str
    message: str


@dataclass
class TestResult:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_scoring.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/scoring.py tests/test_scoring.py && git commit -m "feat: parse pytest-json-report into TestResult with score/is_green"
```

---

### Task 3: Budget — hard caps on cost, iterations, wall-clock

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/budget.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_budget.py`

**Interfaces:**
- Produces: `PRICES: dict[str, tuple[float, float]]` (per-1M input,output USD); `Budget(max_cost_usd, max_iterations, max_wall_seconds, started_at: float | None = None)` with methods `charge_tokens(model, input_tokens, output_tokens) -> None`, `charge_usd(amount: float) -> None`, `tick_iteration() -> None`, properties `spent_usd: float`, `iterations: int`, and `exhausted(now: float) -> str | None` (returns a reason string or `None`). `now` is injected (monotonic seconds) for deterministic tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget.py
import pytest
from avow.budget import Budget, PRICES


def test_charge_tokens_uses_price_table():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    # opus 4.8 = $5/1M in, $25/1M out
    b.charge_tokens("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)
    assert b.spent_usd == pytest.approx(30.0)


def test_charge_usd_direct():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    b.charge_usd(2.5)
    assert b.spent_usd == pytest.approx(2.5)


def test_exhausted_reasons():
    b = Budget(max_cost_usd=1.0, max_iterations=2, max_wall_seconds=100, started_at=0.0)
    assert b.exhausted(now=10.0) is None
    b.charge_usd(1.0)
    assert b.exhausted(now=10.0) == "cost"
    b2 = Budget(max_cost_usd=100.0, max_iterations=2, max_wall_seconds=100, started_at=0.0)
    b2.tick_iteration(); b2.tick_iteration()
    assert b2.exhausted(now=10.0) == "iterations"
    b3 = Budget(max_cost_usd=100.0, max_iterations=9, max_wall_seconds=100, started_at=0.0)
    assert b3.exhausted(now=101.0) == "wall_clock"


def test_unknown_model_charges_zero_but_does_not_crash():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    b.charge_tokens("some-future-model", 1000, 1000)
    assert b.spent_usd == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_budget.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.budget'`.

- [ ] **Step 3: Write `budget.py`**

```python
# avow/budget.py
from __future__ import annotations

from dataclasses import dataclass

# (input $/1M, output $/1M) — from the Anthropic pricing table.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Budget:
    max_cost_usd: float
    max_iterations: int
    max_wall_seconds: int
    started_at: float | None = None
    _spent_usd: float = 0.0
    _iterations: int = 0

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def iterations(self) -> int:
        return self._iterations

    def charge_tokens(self, model: str, input_tokens: int, output_tokens: int) -> None:
        rate = PRICES.get(model)
        if rate is None:
            return
        in_rate, out_rate = rate
        self._spent_usd += (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

    def charge_usd(self, amount: float) -> None:
        self._spent_usd += amount

    def tick_iteration(self) -> None:
        self._iterations += 1

    def exhausted(self, now: float) -> str | None:
        if self._spent_usd >= self.max_cost_usd:
            return "cost"
        if self._iterations >= self.max_iterations:
            return "iterations"
        if self.started_at is not None and (now - self.started_at) >= self.max_wall_seconds:
            return "wall_clock"
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_budget.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/budget.py tests/test_budget.py && git commit -m "feat: Budget with hard cost/iteration/wall-clock caps"
```

---

### Task 4: Memory — append-only JSONL run log

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/memory.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_memory.py`

**Interfaces:**
- Produces: `AttemptRecord(iteration: int, score: float, is_green: bool, diff_summary: str, failing: list[str], plan: str, cost_usd: float)`; `RunLog(path: str | Path)` with `record(rec: AttemptRecord) -> None` (appends one JSON line, creating parent dirs) and `records() -> list[dict]` (reads all lines back).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory.py
from pathlib import Path
from avow.memory import RunLog, AttemptRecord


def test_records_round_trip(tmp_path: Path):
    log = RunLog(tmp_path / "nested" / "run.jsonl")
    log.record(AttemptRecord(
        iteration=1, score=0.5, is_green=False,
        diff_summary="added foo.py", failing=["t::b"], plan="try X", cost_usd=0.02,
    ))
    log.record(AttemptRecord(
        iteration=2, score=1.0, is_green=True,
        diff_summary="fixed foo.py", failing=[], plan="fix X", cost_usd=0.03,
    ))
    rows = log.records()
    assert len(rows) == 2
    assert rows[0]["iteration"] == 1 and rows[0]["is_green"] is False
    assert rows[1]["score"] == 1.0 and rows[1]["failing"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_memory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.memory'`.

- [ ] **Step 3: Write `memory.py`**

```python
# avow/memory.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AttemptRecord:
    iteration: int
    score: float
    is_green: bool
    diff_summary: str
    failing: list[str] = field(default_factory=list)
    plan: str = ""
    cost_usd: float = 0.0


class RunLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, rec: AttemptRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_memory.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/memory.py tests/test_memory.py && git commit -m "feat: append-only JSONL run log"
```

---

### Task 5: Workspace — snapshot-based sandbox with non-regression support

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/workspace.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_workspace.py`

> Note: v1 uses a plain directory snapshot (copytree) for isolation and non-regression. Git worktree / Docker is a v2 hardening behind this same interface.

**Interfaces:**
- Produces: `Workspace(root: Path)` with `solution_dir: Path` (== `root / "solution"`), `seed_from(best: Path | None) -> None` (reset `solution_dir`: empty if `best` is None or missing, else a fresh copy of `best`), and `promote_to(best: Path) -> None` (replace `best` with the current `solution_dir` contents).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workspace.py
from pathlib import Path
from avow.workspace import Workspace


def test_seed_empty_then_promote_then_reseed(tmp_path: Path):
    ws = Workspace(tmp_path / "ws")
    best = tmp_path / "best"

    ws.seed_from(None)
    assert ws.solution_dir.is_dir()
    assert list(ws.solution_dir.iterdir()) == []

    (ws.solution_dir / "main.py").write_text("print('v1')\n")
    ws.promote_to(best)
    assert (best / "main.py").read_text() == "print('v1')\n"

    # A regressing attempt writes junk, then we re-seed from best and the junk is gone.
    (ws.solution_dir / "junk.py").write_text("oops\n")
    ws.seed_from(best)
    assert (ws.solution_dir / "main.py").read_text() == "print('v1')\n"
    assert not (ws.solution_dir / "junk.py").exists()


def test_promote_overwrites_previous_best(tmp_path: Path):
    ws = Workspace(tmp_path / "ws")
    best = tmp_path / "best"
    ws.seed_from(None)
    (ws.solution_dir / "a.py").write_text("1\n")
    ws.promote_to(best)
    ws.seed_from(None)
    (ws.solution_dir / "b.py").write_text("2\n")
    ws.promote_to(best)
    assert not (best / "a.py").exists()
    assert (best / "b.py").read_text() == "2\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_workspace.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.workspace'`.

- [ ] **Step 3: Write `workspace.py`**

```python
# avow/workspace.py
from __future__ import annotations

import shutil
from pathlib import Path


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.solution_dir = self.root / "solution"
        self.root.mkdir(parents=True, exist_ok=True)

    def seed_from(self, best: Path | None) -> None:
        if self.solution_dir.exists():
            shutil.rmtree(self.solution_dir)
        if best is not None and Path(best).is_dir():
            shutil.copytree(best, self.solution_dir)
        else:
            self.solution_dir.mkdir(parents=True)

    def promote_to(self, best: Path) -> None:
        best = Path(best)
        if best.exists():
            shutil.rmtree(best)
        shutil.copytree(self.solution_dir, best)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_workspace.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/workspace.py tests/test_workspace.py && git commit -m "feat: snapshot-based Workspace with non-regression promote/reseed"
```

---

### Task 6: Runner — restore frozen tests and run pytest

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/runner.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_runner.py`

**Interfaces:**
- Consumes: `TestResult`/`parse_report` from `avow.scoring`.
- Produces: `Runner(solution_dir: Path, frozen_tests: Path, test_command: list[str])` with `run() -> TestResult`. `run()` (1) wipes and re-copies `frozen_tests` into `solution_dir / "tests"` (anti-cheat: the Builder's edits to tests are discarded every run), (2) runs `test_command + ["--json-report", "--json-report-file", <tmp>]` with `cwd=solution_dir`, (3) parses the report into a `TestResult`. On a collection crash (no report written), returns `TestResult(0, 0, 1, 1, [FailureInfo("collection", <stderr>)])`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
from pathlib import Path
from avow.runner import Runner


def _make_goal(tmp_path: Path, solution_src: str):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "lib.py").write_text(solution_src)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "test_lib.py").write_text(
        "from lib import add\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )
    return solution, frozen


def test_runner_reports_pass(tmp_path: Path):
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a + b\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    assert r.is_green is True and r.passed == 1


def test_runner_reports_fail(tmp_path: Path):
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a - b\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    assert r.is_green is False and r.failed == 1
    assert any("test_add" in f.nodeid for f in r.failures)


def test_runner_restores_tests_each_run(tmp_path: Path):
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a + b\n")
    # Builder tampering: overwrite the test with a trivially-passing fake.
    (solution / "tests").mkdir(exist_ok=True)
    (solution / "tests" / "test_lib.py").write_text("def test_add():\n    assert True\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    # The frozen (real) test was restored and still asserts add(2,3)==5.
    assert r.is_green is True and r.passed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.runner'`.

- [ ] **Step 3: Write `runner.py`**

```python
# avow/runner.py
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from avow.scoring import FailureInfo, TestResult, parse_report


class Runner:
    def __init__(self, solution_dir: Path, frozen_tests: Path, test_command: list[str]) -> None:
        self.solution_dir = Path(solution_dir)
        self.frozen_tests = Path(frozen_tests)
        self.test_command = list(test_command)

    def run(self) -> TestResult:
        self._restore_frozen_tests()
        fd, report_str = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        report_path = Path(report_str)
        cmd = self.test_command + ["--json-report", "--json-report-file", str(report_path)]
        proc = subprocess.run(
            cmd, cwd=self.solution_dir, capture_output=True, text=True
        )
        if not report_path.exists() or report_path.stat().st_size == 0:
            return TestResult(
                passed=0, failed=0, errors=1, total=1,
                failures=[FailureInfo("collection", proc.stderr or proc.stdout or "no report")],
            )
        report = json.loads(report_path.read_text())
        report_path.unlink(missing_ok=True)
        return parse_report(report)

    def _restore_frozen_tests(self) -> None:
        dest = self.solution_dir / "tests"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.frozen_tests, dest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_runner.py -q`
Expected: PASS (3 passed). (Requires `pytest-json-report`, installed via `.[dev]` in Task 1.)

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/runner.py tests/test_runner.py && git commit -m "feat: Runner restores frozen tests and runs pytest into a TestResult"
```

---

### Task 7: Examiner — write an acceptance-test suite via structured outputs

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/examiner.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_examiner.py`

**Interfaces:**
- Produces: pydantic models `TestFile(path: str, content: str)` and `TestSuite(test_plan: str, tests: list[TestFile])`; `ExaminerResult(suite: TestSuite, input_tokens: int, output_tokens: int)`; `Examiner(client, model: str)` with `write_tests(goal: str) -> ExaminerResult` (calls `client.messages.parse(model=..., max_tokens=16000, messages=[...], output_format=TestSuite)` and reads `response.parsed_output` + `response.usage`); and the pure helper `split_suite(tests: list[TestFile], holdout_fraction: float) -> tuple[list[TestFile], list[TestFile]]` (deterministic: sort by path, move the last `ceil(frac * n)` files to holdout; never empties the visible set).
- Consumes (by the loop, later): an `anthropic.Anthropic()` client passed as `client`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_examiner.py
from types import SimpleNamespace
from avow.examiner import Examiner, TestSuite, TestFile, split_suite


class FakeMessages:
    def __init__(self, suite):
        self._suite = suite
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._suite,
            usage=SimpleNamespace(input_tokens=11, output_tokens=22),
        )


class FakeClient:
    def __init__(self, suite):
        self.messages = FakeMessages(suite)


def test_write_tests_returns_suite_and_usage():
    suite = TestSuite(test_plan="verify add", tests=[TestFile(path="test_add.py", content="...")])
    client = FakeClient(suite)
    ex = Examiner(client, model="claude-sonnet-4-6")
    result = ex.write_tests("build an add() function")
    assert result.suite.tests[0].path == "test_add.py"
    assert result.input_tokens == 11 and result.output_tokens == 22
    # goal text is forwarded into the prompt
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-sonnet-4-6"
    assert sent["output_format"] is TestSuite
    assert "build an add() function" in sent["messages"][0]["content"]


def test_split_suite_is_deterministic_and_keeps_visible_nonempty():
    files = [TestFile(path=f"test_{c}.py", content="x") for c in "dcba"]
    visible, holdout = split_suite(files, holdout_fraction=0.25)
    assert [f.path for f in visible] == ["test_a.py", "test_b.py", "test_c.py"]
    assert [f.path for f in holdout] == ["test_d.py"]


def test_split_suite_zero_fraction_holds_out_nothing():
    files = [TestFile(path="test_a.py", content="x")]
    visible, holdout = split_suite(files, holdout_fraction=0.0)
    assert len(visible) == 1 and holdout == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_examiner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.examiner'`.

- [ ] **Step 3: Write `examiner.py`**

```python
# avow/examiner.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_examiner.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/examiner.py tests/test_examiner.py && git commit -m "feat: Examiner writes adversarial test suite via structured outputs; deterministic holdout split"
```

---

### Task 8: Builder — drive headless `claude -p` as the code-writing agent

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/builder.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_builder.py`

**Interfaces:**
- Consumes: `FailureInfo` from `avow.scoring`.
- Produces: `BuilderOutcome(plan: str, cost_usd: float, raw: dict)`; `Builder(model: str, runner=subprocess.run)` with `attempt(solution_dir: Path, goal: str, failures: list[FailureInfo]) -> BuilderOutcome`. `attempt` invokes `["claude", "-p", <prompt>, "--output-format", "json", "--dangerously-skip-permissions", "--model", model]` with `cwd=solution_dir`, then parses stdout JSON (`result` → `plan`, `total_cost_usd` → `cost_usd`). `runner` is injectable (defaults to `subprocess.run`) so tests don't spawn `claude`.

> Anti-cheat reinforcement: the prompt instructs the Builder to edit only solution code and never create/modify any `tests/` files; the Runner discards test edits regardless.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_builder.py
import json
import subprocess
from pathlib import Path
from avow.builder import Builder, BuilderOutcome
from avow.scoring import FailureInfo


def test_attempt_invokes_claude_and_parses_json(tmp_path: Path):
    captured = {}

    def fake_runner(cmd, cwd=None, capture_output=False, text=False):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(
            cmd, returncode=0,
            stdout=json.dumps({"result": "I added lib.py", "total_cost_usd": 0.04}),
            stderr="",
        )

    b = Builder(model="claude-opus-4-8", runner=fake_runner)
    out = b.attempt(tmp_path, "build add()", [FailureInfo("t::add", "expected 5 got -1")])

    assert isinstance(out, BuilderOutcome)
    assert out.plan == "I added lib.py"
    assert out.cost_usd == 0.04
    assert captured["cwd"] == tmp_path
    assert captured["cmd"][0] == "claude"
    assert "--dangerously-skip-permissions" in captured["cmd"]
    assert "claude-opus-4-8" in captured["cmd"]
    prompt = captured["cmd"][2]
    assert "build add()" in prompt
    assert "expected 5 got -1" in prompt  # failures fed back in


def test_attempt_tolerates_missing_cost_field(tmp_path: Path):
    def fake_runner(cmd, cwd=None, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "done"}), stderr="")

    out = Builder(model="claude-opus-4-8", runner=fake_runner).attempt(tmp_path, "goal", [])
    assert out.cost_usd == 0.0 and out.plan == "done"


def test_attempt_handles_nonjson_stdout(tmp_path: Path):
    def fake_runner(cmd, cwd=None, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, 1, stdout="boom not json", stderr="err")

    out = Builder(model="claude-opus-4-8", runner=fake_runner).attempt(tmp_path, "goal", [])
    assert out.cost_usd == 0.0
    assert "boom not json" in out.plan or "err" in out.plan
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_builder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.builder'`.

- [ ] **Step 3: Write `builder.py`**

```python
# avow/builder.py
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from avow.scoring import FailureInfo

_PROMPT = """\
You are an autonomous software builder working inside the current directory.

Your goal:
{goal}

A hidden, frozen acceptance-test suite grades your work. You CANNOT see or edit the \
tests, and any file you place under a `tests/` directory will be discarded before \
grading. Edit only the implementation/solution code in this directory.

{failures_block}

Implement or fix the code so the acceptance tests pass. Make the smallest change that \
could plausibly work. Do not add features, abstractions, or error handling beyond what \
the goal requires.
"""


@dataclass
class BuilderOutcome:
    plan: str
    cost_usd: float
    raw: dict


class Builder:
    def __init__(self, model: str, runner=subprocess.run) -> None:
        self.model = model
        self.runner = runner

    def attempt(self, solution_dir: Path, goal: str, failures: list[FailureInfo]) -> BuilderOutcome:
        prompt = _PROMPT.format(goal=goal, failures_block=self._failures_block(failures))
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--model", self.model,
        ]
        proc = self.runner(cmd, cwd=Path(solution_dir), capture_output=True, text=True)
        return self._parse(proc)

    @staticmethod
    def _failures_block(failures: list[FailureInfo]) -> str:
        if not failures:
            return "This is the first attempt; no failures yet."
        lines = ["The previous attempt failed these tests — fix them:"]
        for f in failures:
            lines.append(f"- {f.nodeid}: {f.message}")
        return "\n".join(lines)

    @staticmethod
    def _parse(proc: subprocess.CompletedProcess) -> BuilderOutcome:
        try:
            data = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return BuilderOutcome(
                plan=(proc.stdout or proc.stderr or "").strip(), cost_usd=0.0, raw={}
            )
        return BuilderOutcome(
            plan=str(data.get("result", "")),
            cost_usd=float(data.get("total_cost_usd", 0.0)),
            raw=data,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_builder.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/builder.py tests/test_builder.py && git commit -m "feat: Builder drives headless claude -p with injectable runner"
```

---

### Task 9: The loop — `solve()` with non-regression and stop conditions

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/loop.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_loop.py`

**Interfaces:**
- Consumes: `RunConfig`, `Budget`, `Workspace`, `Runner`, `RunLog`/`AttemptRecord`, `Examiner`/`ExaminerResult`/`split_suite`, `Builder`/`BuilderOutcome`, `TestResult`.
- Produces: `SolveResult(success: bool, best_score: float, iterations: int, reason: str, best_dir: Path)`; `solve(goal_dir: Path, config: RunConfig, examiner: Examiner, builder: Builder, *, now=time.monotonic, write_tests: bool = True) -> SolveResult`. Behavior:
  1. Read `goal_dir/goal.md`.
  2. If `write_tests`, call `examiner.write_tests(goal)`, `split_suite` by `config.holdout_fraction`, write visible files to `goal_dir/tests_frozen/` and holdout files to `goal_dir/tests_holdout/`; charge the examiner tokens to the budget.
  3. Iterate up to `config.max_iterations`: check budget → seed workspace from best → builder attempt (charge cost) → runner.run() → record → non-regression promote-if-improved → stop on green (then verify holdout) / plateau / budget.
  - `reason` ∈ `{"green", "overfit_on_holdout", "plateau", "max_iterations", "cost", "iterations", "wall_clock"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop.py
from pathlib import Path
from avow.loop import solve, SolveResult
from avow.config import RunConfig
from avow.examiner import Examiner, ExaminerResult, TestSuite, TestFile
from avow.scoring import FailureInfo


# --- fakes ---------------------------------------------------------------

class StubExaminer(Examiner):
    def __init__(self):
        pass  # bypass client

    def write_tests(self, goal):
        suite = TestSuite(
            test_plan="verify add",
            tests=[TestFile(
                path="test_add.py",
                content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n",
            )],
        )
        return ExaminerResult(suite=suite, input_tokens=5, output_tokens=5)


class FlakyBuilder:
    """Fails on the first attempt (writes wrong code), fixes it on the second."""
    def __init__(self):
        self.calls = 0

    def attempt(self, solution_dir: Path, goal, failures):
        self.calls += 1
        src = "def add(a, b):\n    return a + b\n" if self.calls >= 2 else "def add(a, b):\n    return a - b\n"
        (Path(solution_dir) / "lib.py").write_text(src)
        from avow.builder import BuilderOutcome
        return BuilderOutcome(plan=f"attempt {self.calls}", cost_usd=0.01, raw={})


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


# --- tests ---------------------------------------------------------------

def test_loop_converges_to_green(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    builder = FlakyBuilder()
    result = solve(_goal(tmp_path), cfg, StubExaminer(), builder, now=lambda: 0.0)
    assert isinstance(result, SolveResult)
    assert result.success is True
    assert result.reason == "green"
    assert result.best_score == 1.0
    assert builder.calls == 2          # failed once, fixed on the second
    assert (result.best_dir / "lib.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_loop_stops_at_max_iterations_when_never_green(tmp_path: Path):
    class AlwaysWrong:
        def attempt(self, solution_dir, goal, failures):
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return 0\n")
            from avow.builder import BuilderOutcome
            return BuilderOutcome(plan="nope", cost_usd=0.01, raw={})

    cfg = RunConfig(max_iterations=3, plateau_patience=99, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrong(), now=lambda: 0.0)
    assert result.success is False
    assert result.reason in {"max_iterations", "plateau"}
    assert result.iterations == 3


def test_loop_writes_frozen_tests_and_run_log(tmp_path: Path):
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0)
    solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert (tmp_path / "tests_frozen" / "test_add.py").exists()
    log = (tmp_path / ".avow" / "run.jsonl").read_text().strip().splitlines()
    assert len(log) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_loop.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.loop'`.

- [ ] **Step 3: Write `loop.py`**

```python
# avow/loop.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from avow.budget import Budget
from avow.config import RunConfig
from avow.examiner import Examiner, TestFile, split_suite
from avow.memory import AttemptRecord, RunLog
from avow.runner import Runner
from avow.workspace import Workspace


@dataclass
class SolveResult:
    success: bool
    best_score: float
    iterations: int
    reason: str
    best_dir: Path


def _write_tests(dest: Path, tests: list[TestFile]) -> None:
    if dest.exists():
        import shutil
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for t in tests:
        (dest / Path(t.path).name).write_text(t.content)


def solve(
    goal_dir: Path,
    config: RunConfig,
    examiner: Examiner,
    builder,
    *,
    now=time.monotonic,
    write_tests: bool = True,
) -> SolveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()

    avow_dir = goal_dir / ".avow"
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_dir = avow_dir / "best"

    budget = Budget(
        max_cost_usd=config.max_cost_usd,
        max_iterations=config.max_iterations,
        max_wall_seconds=config.max_wall_seconds,
        started_at=now(),
    )

    if write_tests:
        ex = examiner.write_tests(goal)
        budget.charge_tokens(config.examiner_model, ex.input_tokens, ex.output_tokens)
        visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
        _write_tests(frozen, visible)
        _write_tests(holdout, held)

    log = RunLog(avow_dir / "run.jsonl")
    workspace = Workspace(avow_dir / "ws")
    runner = Runner(workspace.solution_dir, frozen, config.test_command)

    best_score = -1.0
    have_best = False
    rounds_without_improvement = 0
    last_failures: list = []
    reason = "max_iterations"

    while True:
        stopped = budget.exhausted(now())
        if stopped is not None:
            reason = stopped
            break

        budget.tick_iteration()
        workspace.seed_from(best_dir if have_best else None)

        outcome = builder.attempt(workspace.solution_dir, goal, last_failures)
        budget.charge_usd(outcome.cost_usd)

        result = runner.run()
        last_failures = result.failures

        log.record(AttemptRecord(
            iteration=budget.iterations,
            score=result.score,
            is_green=result.is_green,
            diff_summary=outcome.plan[:200],
            failing=[f.nodeid for f in result.failures],
            plan=outcome.plan,
            cost_usd=outcome.cost_usd,
        ))

        improved = result.score > best_score
        if improved:
            workspace.promote_to(best_dir)
            best_score = result.score
            have_best = True
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

        if result.is_green:
            if _holdout_green(holdout, best_dir, config):
                return SolveResult(True, best_score, budget.iterations, "green", best_dir)
            return SolveResult(False, best_score, budget.iterations, "overfit_on_holdout", best_dir)

        if rounds_without_improvement >= config.plateau_patience:
            reason = "plateau"
            break
        if budget.iterations >= config.max_iterations:
            reason = "max_iterations"
            break

    return SolveResult(False, max(best_score, 0.0), budget.iterations, reason, best_dir)


def _holdout_green(holdout: Path, best_dir: Path, config: RunConfig) -> bool:
    if not holdout.exists() or not any(holdout.iterdir()):
        return True  # no holdout configured → visible-green is the verdict
    return Runner(best_dir, holdout, config.test_command).run().is_green
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_loop.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest -q`
Expected: PASS (all tasks' tests green).

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/loop.py tests/test_loop.py && git commit -m "feat: iterative solve() loop with non-regression, holdout check, and stop conditions"
```

---

### Task 10: CLI — `avow solve <goal-dir>`

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/cli.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_examiner(config) -> Examiner` (constructs an `anthropic.Anthropic()` client) and `main(argv: list[str] | None = None) -> int`. CLI: `avow solve <goal-dir> [--config avow.yaml] [--no-regenerate] [--yes]`. Without `--yes`, after the Examiner writes the suite the CLI prints the test plan and pauses for confirmation before the build loop (the one human gate on the verifier). `--no-regenerate` reuses existing `tests_frozen/` and skips the Examiner.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from pathlib import Path
from avow.cli import main


def test_cli_runs_with_injected_no_regenerate(tmp_path: Path, monkeypatch):
    # Pre-seed a goal and frozen tests so --no-regenerate skips the Examiner (no network).
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    frozen = tmp_path / "tests_frozen"
    frozen.mkdir()
    (frozen / "test_add.py").write_text(
        "from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )

    # Patch the Builder so the CLI doesn't spawn `claude`.
    import avow.cli as cli

    class StubBuilder:
        def __init__(self, *a, **k):
            self.calls = 0

        def attempt(self, solution_dir, goal, failures):
            self.calls += 1
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            from avow.builder import BuilderOutcome
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = main(["solve", str(tmp_path), "--no-regenerate", "--yes"])
    assert rc == 0
    assert (tmp_path / ".avow" / "best" / "lib.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.cli'`.

- [ ] **Step 3: Write `cli.py`**

```python
# avow/cli.py
from __future__ import annotations

import argparse
from pathlib import Path

from avow.builder import Builder
from avow.config import RunConfig
from avow.examiner import Examiner
from avow.loop import solve


def build_examiner(config: RunConfig) -> Examiner:
    import anthropic  # imported lazily so unit tests don't need network/creds
    return Examiner(anthropic.Anthropic(), model=config.examiner_model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avow")
    sub = parser.add_subparsers(dest="command", required=True)
    solve_p = sub.add_parser("solve", help="run the build-and-improve loop on a goal dir")
    solve_p.add_argument("goal_dir")
    solve_p.add_argument("--config", default=None)
    solve_p.add_argument("--no-regenerate", action="store_true",
                         help="reuse existing tests_frozen/ instead of calling the Examiner")
    solve_p.add_argument("--yes", action="store_true",
                         help="skip the human approval gate on the generated test plan")
    args = parser.parse_args(argv)

    goal_dir = Path(args.goal_dir)
    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    write_tests = not args.no_regenerate

    examiner = build_examiner(config) if write_tests else _NullExaminer()

    if write_tests and not args.yes:
        ex = examiner.write_tests((goal_dir / "goal.md").read_text())
        print("=== proposed test plan ===")
        print(ex.suite.test_plan)
        if input("Approve and start the build loop? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1
        # Re-use the just-written suite by persisting it and switching off regeneration.
        from avow.examiner import split_suite
        from avow.loop import _write_tests
        visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
        _write_tests(goal_dir / "tests_frozen", visible)
        _write_tests(goal_dir / "tests_holdout", held)
        write_tests = False

    builder = Builder(model=config.builder_model)
    result = solve(goal_dir, config, examiner, builder, write_tests=write_tests)

    print(f"\nresult: success={result.success} reason={result.reason} "
          f"score={result.best_score:.2f} iterations={result.iterations}")
    print(f"best solution: {result.best_dir}")
    return 0 if result.success else 2


class _NullExaminer:
    def write_tests(self, goal):  # pragma: no cover - never called when write_tests=False
        raise RuntimeError("Examiner should not run when tests are reused")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest tests/test_cli.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the whole suite + smoke-check the entry point**

Run: `cd /Users/qatadaha/Coding/avow && python -m pytest -q && avow --help`
Expected: all tests PASS; `avow --help` prints usage with the `solve` subcommand.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/cli.py tests/test_cli.py && git commit -m "feat: avow solve CLI with human approval gate on the generated test plan"
```

---

## Manual end-to-end validation (after Task 10, with real credentials)

This is the moment the loop closes for real — run it once by hand, not in CI:

1. Create a goal dir: `mkdir -p ~/Coding/avow-demo && printf 'Build a module `lib.py` exposing `def slugify(s: str) -> str` that lowercases, trims, and replaces runs of non-alphanumeric characters with single hyphens.' > ~/Coding/avow-demo/goal.md`
2. Ensure `claude` is installed/authenticated and `ANTHROPIC_API_KEY` is set (Examiner uses the SDK; Builder uses the CLI).
3. Run: `avow solve ~/Coding/avow-demo`
4. Approve the printed test plan, then watch `~/Coding/avow-demo/.avow/run.jsonl` — score should climb to 1.0 and the run should end `success=True reason=green`.
5. Inspect `~/Coding/avow-demo/.avow/best/lib.py` — the autonomously-built, test-passing artifact.

## What v1 deliberately does NOT do (earned in later plans)

- No Supervisor, Ideator, or expand phase (v3/v4) — single converge loop only.
- No mutation testing, cross-model panel, back-translation, or confidence score (v2 — the verification moat).
- Plain-directory snapshot sandbox, not git worktree/Docker (v2 hardening).
- Holdout split is present but single-model; full hold-out hardening is v2.
