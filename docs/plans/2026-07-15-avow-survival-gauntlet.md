# Avow — Survival Gauntlet (sub-project A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** After Avow converges to a green + high-confidence solution, subject it to a harder execution gauntlet (K independent references differential-fuzzed against it). A majority of references diverging kills the green; the run then freezes the winning reference's diff test into the suite, rebuilds, and faces a fresh gauntlet — until it survives clean (`verified_survivor`) or dies honestly at the round cap (`died`, with the counterexample).

**Architecture:** Two new modules. `avow/gauntlet.py` runs the execution-decided attack (reusing `oracle.generate_oracle` for references and `scoring.parse_report` for outcomes; majority vote like `adjudicator`). `avow/survive.py` mirrors `harden.py`: converge via `loop.solve`, then loop the gauntlet, feeding each kill back as a frozen differential test (the same `ref.py` + diff-test mechanism `solve`'s `oracle_converge_target` already uses). Ships dormant.

**Tech Stack:** Python 3.11+, pytest + pytest-json-report, Hypothesis, the `anthropic` SDK (structured outputs via `messages.parse`).

## Global Constraints

- Python **3.11+**. Avow-local venv at `/Users/qatadaha/Coding/avow/.venv`; activate before every command: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && <cmd>`.
- **Ships dormant:** `survival_enabled` defaults `False`; the `survive`/`gauntlet` verbs are opt-in; `solve` is unchanged. A run with `gauntlet_client=None` must NOT claim survival.
- **A kill is execution-decided, never opinion:** a majority of independent references must diverge from the solution on a fuzzed input. Majority-of-K (mirrors `adjudicator`) stops one bad reference from a false kill.
- **Honest labels:** `verified_survivor` means "survived a K-reference execution gauntlet," NOT "provably correct." Say so in CLI output and docstrings.
- **UNTRACKED files stay uncommitted:** `avow/openrouter.py`, `tests/test_openrouter.py`. Use SPECIFIC `git add` per task; never `git add -A`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run only when greenlit. Local commits only unless told to push.
- Reuse, don't reinvent: `oracle.generate_oracle(goal, client, model) -> (_OraclePair|None, in_tok, out_tok)` where `_OraclePair` has `.reference_code` and `.diff_test_code` (a Hypothesis `@given` diff test importing `from lib import <fn> as _sol` / `from ref import <fn> as _ref`). `scoring.parse_report(json) -> TestResult` with `.passed/.failed/.errors/.total/.failures` (each `FailureInfo(nodeid, message)`).

## File Structure

- `avow/gauntlet.py` (new) — the predator: `Counterexample`, `GauntletResult`, `run_gauntlet`, and the internals `_run_diff`, `_extract_falsifying_example`.
- `avow/survive.py` (new) — the survival loop: `SurviveResult`, `survive`.
- `avow/config.py` (modify) — five `RunConfig` fields.
- `avow/cli.py` (modify) — `avow survive` and `avow gauntlet` verbs.
- Tests: `tests/test_gauntlet.py`, `tests/test_survive.py`, additions to `tests/test_config.py` and `tests/test_cli.py`-style CLI tests.

---

### Task 1: Config knobs

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/config.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- Produces: `RunConfig.survival_enabled: bool = False`, `.gauntlet_references_k: int = 4`, `.gauntlet_max_rounds: int = 3`, `.gauntlet_examples: int = 200`, `.gauntlet_model: str = "claude-opus-4-8"`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.survival_enabled is False
    assert cfg.gauntlet_references_k == 4
    assert cfg.gauntlet_max_rounds == 3
    assert cfg.gauntlet_examples == 200
    assert cfg.gauntlet_model == "claude-opus-4-8"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'survival_enabled'`.

- [ ] **Step 3: Add the fields** — in `avow/config.py`, add after the `adjudicate_references_k`/`checks`/`strip_check_config` block (anywhere in the field list; `Field` already imported):

```python
    survival_enabled: bool = False
    gauntlet_references_k: int = 4
    gauntlet_max_rounds: int = 3
    gauntlet_examples: int = 200
    gauntlet_model: str = "claude-opus-4-8"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: survival/gauntlet config knobs (dormant by default)"
```

---

### Task 2: Gauntlet internals — falsifying-example parse + single-reference diff run

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/gauntlet.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_gauntlet.py`

**Interfaces:**
- Produces: `Counterexample(input_repr: str, reference_code: str, diff_test_code: str)`; `_extract_falsifying_example(pytest_output: str) -> str`; `_run_diff(solution_dir, reference_code, diff_test_code, examples, test_command, timeout) -> tuple[str, str]` returning `(outcome, falsifying)` with `outcome ∈ {"agree","diverge","unusable"}`.

> **Spec refinement (intentional, not a gap):** the spec sketched `Counterexample(input_repr, expected, actual, regression_test)` — a synthesized concrete assertion. This plan instead carries `reference_code` + `diff_test_code` so the fight-back can freeze the winning reference's differential test into `tests_frozen/` (a `ref_g{n}.py` + its diff test), reusing the already-proven `oracle_converge_target` mechanism rather than synthesizing/executing a minimal assertion. Same requirement (a kill becomes a frozen regression the Builder must satisfy), simpler and execution-grounded. `input_repr` still carries the human-facing falsifying example.

- [ ] **Step 1: Write the failing tests** — create `tests/test_gauntlet.py`:

```python
from pathlib import Path
from avow.gauntlet import _extract_falsifying_example, _run_diff, Counterexample

TEST_CMD = ["python", "-m", "pytest", "-q"]

_DIFF = ("from lib import f as _sol\nfrom ref import f as _ref\n"
         "from hypothesis import given, strategies as st\n"
         "@given(st.integers())\ndef test_diff(x):\n    assert _sol(x) == _ref(x)\n")


def test_extract_falsifying_example():
    out = "some noise\nFalsifying example: test_diff(x=0)\nmore noise\n"
    assert _extract_falsifying_example(out) == "test_diff(x=0)"
    assert _extract_falsifying_example("no example here") == ""


def test_run_diff_agree(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    outcome, _ = _run_diff(tmp_path, "def f(x):\n    return x + 1\n", _DIFF, 50, TEST_CMD, 60)
    assert outcome == "agree"


def test_run_diff_diverge_gives_falsifying(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 2\n")   # WRONG vs reference
    outcome, falsifying = _run_diff(tmp_path, "def f(x):\n    return x + 1\n", _DIFF, 50, TEST_CMD, 60)
    assert outcome == "diverge"
    assert "test_diff(" in falsifying


def test_run_diff_broken_reference_is_unusable(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    outcome, _ = _run_diff(tmp_path, "def broken(:\n", _DIFF, 50, TEST_CMD, 60)  # syntax error
    assert outcome == "unusable"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_gauntlet.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.gauntlet'`.

- [ ] **Step 3: Write `avow/gauntlet.py`** (internals only for this task):

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_gauntlet.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/gauntlet.py tests/test_gauntlet.py && git commit -m "feat: gauntlet internals — single-reference differential run + falsifying-example parse"
```

---

### Task 3: `run_gauntlet` — K references, majority vote, counterexample

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/gauntlet.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_gauntlet.py`

**Interfaces:**
- Consumes: `generate_oracle`, `_run_diff`, `Counterexample`.
- Produces: `GauntletResult(survived: bool, counterexample, references_ok: int, references_total: int, input_tokens: int, output_tokens: int)`; `run_gauntlet(solution_dir, goal, client, model, test_command, *, k=4, examples=200, timeout=120) -> GauntletResult`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_gauntlet.py`:

```python
from types import SimpleNamespace
from avow.gauntlet import run_gauntlet, GauntletResult
from avow.oracle import _OraclePair


class _RefClient:
    """generate_oracle client that always returns the same correct reference for f(x)=x+1."""
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _OraclePair(reference_code="def f(x):\n    return x + 1\n", diff_test_code=_DIFF)
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_run_gauntlet_survives_correct_solution(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    g = run_gauntlet(tmp_path, "f(x) returns x+1", _RefClient(), "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is True and g.counterexample is None
    assert g.references_ok == 3 and g.references_total == 3


def test_run_gauntlet_kills_wrong_solution(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 2\n")   # majority will diverge
    g = run_gauntlet(tmp_path, "f(x) returns x+1", _RefClient(), "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is False
    assert g.counterexample is not None and "test_diff(" in g.counterexample.input_repr
    assert g.counterexample.reference_code.strip().endswith("return x + 1")


def test_run_gauntlet_no_client_cannot_attack(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x\n")
    g = run_gauntlet(tmp_path, "goal", None, "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is True and g.references_ok == 0   # no attack ran -> nothing gained
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_gauntlet.py -q -k run_gauntlet`
Expected: FAIL — `cannot import name 'run_gauntlet'`.

- [ ] **Step 3: Add `GauntletResult` + `run_gauntlet`** to `avow/gauntlet.py`:

```python
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
    if diverging and len(diverging) > agree:
        ref_code, diff_code, falsifying = diverging[0]
        cx = Counterexample(input_repr=falsifying, reference_code=ref_code, diff_test_code=diff_code)
        return GauntletResult(False, cx, usable, k, in_tok, out_tok)
    return GauntletResult(True, None, usable, k, in_tok, out_tok)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_gauntlet.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/gauntlet.py tests/test_gauntlet.py && git commit -m "feat: run_gauntlet — K references, majority-diverge kill, execution-decided counterexample"
```

---

### Task 4: `survive` — the fight-back loop

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/survive.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_survive.py`

**Interfaces:**
- Consumes: `loop.solve`, `budget.Budget`, `run_gauntlet`/`Counterexample` (Tasks 2–3), `RunConfig` (Task 1).
- Produces: `SurviveResult(status: str, rounds: int, final, death_counterexample=None)` with `status ∈ {"verified_survivor","died","not_green","unverified"}`; `survive(goal_dir, config, examiner, builder, *, gauntlet_client, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> SurviveResult`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_survive.py`. Reuses the `StubExaminer`/`FlakyBuilder` fakes (copied here so the test is self-contained), and monkeypatches `avow.survive.run_gauntlet` so the loop logic is deterministic (Task 3 already tested the real gauntlet):

```python
from pathlib import Path
from avow.survive import survive, SurviveResult
from avow.config import RunConfig
from avow.examiner import Examiner, ExaminerResult, TestSuite, TestFile
from avow.builder import BuilderOutcome
from avow.gauntlet import GauntletResult, Counterexample


class StubExaminer(Examiner):
    def __init__(self):
        pass

    def write_tests(self, goal):
        suite = TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        return ExaminerResult(suite=suite, input_tokens=1, output_tokens=1)


class GoodBuilder:
    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def _goal(tmp_path):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


_CX = Counterexample(input_repr="test_diff(a=0, b=0)",
                     reference_code="def add(a, b):\n    return a + b\n",
                     diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                     "from hypothesis import given, strategies as st\n"
                                     "@given(st.integers(), st.integers())\n"
                                     "def test_g(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))


def test_survive_verified_when_gauntlet_survives(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: GauntletResult(True, None, 4, 4, 0, 0))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "verified_survivor" and r.rounds == 0


def test_survive_fights_back_then_survives(tmp_path, monkeypatch):
    import avow.survive as s
    calls = {"n": 0}

    def fake_gauntlet(*a, **k):
        calls["n"] += 1
        return GauntletResult(False, _CX, 4, 4, 0, 0) if calls["n"] == 1 else GauntletResult(True, None, 4, 4, 0, 0)

    monkeypatch.setattr(s, "run_gauntlet", fake_gauntlet)
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=3),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "verified_survivor" and r.rounds == 1
    # the counterexample was frozen into the suite as a differential regression test + its reference
    assert (tmp_path / "tests_frozen" / "test_gauntlet_r0.py").exists()
    assert (tmp_path / "tests_frozen" / "ref_g0.py").exists()
    assert "from ref_g0 import" in (tmp_path / "tests_frozen" / "test_gauntlet_r0.py").read_text()


def test_survive_dies_when_never_survives(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: GauntletResult(False, _CX, 4, 4, 0, 0))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=2),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "died" and r.death_counterexample is _CX


def test_survive_no_gauntlet_client_is_unverified(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0),
                StubExaminer(), GoodBuilder(), gauntlet_client=None, now=lambda: 0.0)
    assert r.status == "unverified" and r.rounds == 0   # green, but the gauntlet never ran
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_survive.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.survive'`.

- [ ] **Step 3: Write `avow/survive.py`**:

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from avow.loop import solve
from avow.budget import Budget
from avow.gauntlet import run_gauntlet


@dataclass
class SurviveResult:
    status: str        # verified_survivor | died | not_green | unverified
    rounds: int
    final: object
    death_counterexample: object = None


def survive(goal_dir, config, examiner, builder, *, gauntlet_client, mutation_client=None,
            intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> SurviveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"
    best_src = goal_dir / ".avow" / "best"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    if not (result.success and best_src.exists()):
        return SurviveResult("not_green", 0, result)
    if gauntlet_client is None:
        return SurviveResult("unverified", 0, result)   # green, but no gauntlet ran

    budget = Budget(max_cost_usd=config.max_cost_usd, max_iterations=config.max_iterations,
                    max_wall_seconds=config.max_wall_seconds, started_at=now())
    last_cx = None
    for rnd in range(config.gauntlet_max_rounds):
        g = run_gauntlet(best_src, goal, gauntlet_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds)
        budget.charge_tokens(config.gauntlet_model, g.input_tokens, g.output_tokens)
        if g.survived:
            return SurviveResult("verified_survivor", rnd, result)
        last_cx = g.counterexample
        if budget.spent_usd >= config.max_cost_usd:   # spent_usd is a @property
            return SurviveResult("died", rnd + 1, result, last_cx)
        # fight back: freeze the winning reference's differential test into the suite, then rebuild.
        (frozen / f"ref_g{rnd}.py").write_text(g.counterexample.reference_code, encoding="utf-8")
        (frozen / f"test_gauntlet_r{rnd}.py").write_text(
            g.counterexample.diff_test_code.replace("from ref import", f"from ref_g{rnd} import"),
            encoding="utf-8")
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        if not result.success:
            return SurviveResult("died", rnd + 1, result, last_cx)   # couldn't re-converge on the new test
    return SurviveResult("died", config.gauntlet_max_rounds, result, last_cx)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_survive.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/survive.py tests/test_survive.py && git commit -m "feat: survive() — gauntlet fight-back loop (verified_survivor / died / unverified)"
```

---

### Task 5: CLI — `avow survive` and `avow gauntlet`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/cli.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_cli_survive.py`

**Interfaces:**
- Consumes: `survive.survive`, `gauntlet.run_gauntlet`, existing `build_examiner`, `Builder`, `RunConfig`.
- Produces: subcommands `avow survive <goal_dir> [--config] [--no-llm-verify]` and `avow gauntlet <solution_dir> <goal_file> [--config]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_cli_survive.py` (monkeypatch the orchestrators so it's fast and offline):

```python
from types import SimpleNamespace
from pathlib import Path
import avow.cli as cli


def test_survive_cli_reports_status(tmp_path, monkeypatch, capsys):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: "CLIENT")
    monkeypatch.setattr(cli, "build_examiner", lambda cfg: object())
    monkeypatch.setattr(cli, "Builder", lambda *a, **k: object())
    import avow.survive as s
    monkeypatch.setattr(s, "survive",
                        lambda *a, **k: SimpleNamespace(status="verified_survivor", rounds=2,
                                                        death_counterexample=None))
    rc = cli.main(["survive", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "status=verified_survivor" in out and "not a proof of correctness" in out.lower()


def test_gauntlet_cli_reports_kill(tmp_path, monkeypatch, capsys):
    (tmp_path / "goal.md").write_text("f(x) returns x+1")
    (tmp_path / "lib.py").write_text("def f(x):\n    return x\n")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: "CLIENT")
    import avow.gauntlet as gt
    from avow.gauntlet import Counterexample
    cx = Counterexample("test_diff(x=0)", "def f(x):\n    return x + 1\n", "diff")
    monkeypatch.setattr(gt, "run_gauntlet",
                        lambda *a, **k: SimpleNamespace(survived=False, counterexample=cx,
                                                        references_ok=3, references_total=4,
                                                        input_tokens=0, output_tokens=0))
    rc = cli.main(["gauntlet", str(tmp_path), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 2 and "KILLED" in out and "test_diff(x=0)" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_survive.py -q`
Expected: FAIL — argparse `invalid choice: 'survive'`.

- [ ] **Step 3: Add handlers** to `avow/cli.py` (place next to `_cmd_harden` / `_cmd_oracle`):

```python
def _cmd_survive(args) -> int:
    from avow.survive import survive

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)
    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()
    result = survive(Path(args.goal_dir), config, examiner, builder,
                     gauntlet_client=verify_client, intent_client=verify_client,
                     property_client=verify_client, oracle_client=verify_client)
    print(f"result: status={result.status} gauntlet_rounds={result.rounds}")
    if result.status == "died" and result.death_counterexample is not None:
        print(f"  killed by counterexample: {result.death_counterexample.input_repr}")
    print("note: 'verified_survivor' means it survived a K-reference execution gauntlet, "
          "not a proof of correctness.")
    return 0 if result.status in ("verified_survivor", "unverified") else 2


def _cmd_gauntlet(args) -> int:
    import anthropic
    from avow.gauntlet import run_gauntlet

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    g = run_gauntlet(Path(args.solution_dir), goal, anthropic.Anthropic(), config.gauntlet_model,
                     config.test_command, k=config.gauntlet_references_k,
                     examples=config.gauntlet_examples, timeout=config.test_timeout_seconds)
    if g.survived:
        print(f"VERIFIED SURVIVOR — agreed with {g.references_ok}/{g.references_total} independent "
              f"references across the fuzzed space (survived the gauntlet; not a proof of correctness)")
        return 0
    print("KILLED — a majority of independent references diverge from this solution.")
    print(f"  counterexample: {g.counterexample.input_repr}")
    return 2
```

- [ ] **Step 4: Add subparsers + dispatch** in `main()` of `avow/cli.py`. Next to the `harden_p` subparser block:

```python
    survive_p = sub.add_parser(
        "survive", help="converge, then survive a harder execution gauntlet — one counterexample kills the green and it fights back")
    survive_p.add_argument("goal_dir")
    survive_p.add_argument("--config", default=None)
    survive_p.add_argument("--no-llm-verify", action="store_true")
    gauntlet_p = sub.add_parser(
        "gauntlet", help="attack an existing solution once: K independent references vs the solution over a fuzzed input space")
    gauntlet_p.add_argument("solution_dir")
    gauntlet_p.add_argument("goal_file")
    gauntlet_p.add_argument("--config", default=None)
```

And next to the `if args.command == "harden":` dispatch:

```python
    if args.command == "survive":
        return _cmd_survive(args)

    if args.command == "gauntlet":
        return _cmd_gauntlet(args)
```

- [ ] **Step 5: Run to verify they pass + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_survive.py -q && avow --help | grep -E "survive|gauntlet"`
Expected: PASS (2 passed); `--help` lists `survive` and `gauntlet`.

- [ ] **Step 6: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings. (`survival_enabled` off path unaffected; `solve` unchanged.)

- [ ] **Step 7: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/cli.py tests/test_cli_survive.py && git commit -m "feat: avow survive + avow gauntlet CLI verbs"
```

---

## Manual validation (after Task 5, needs ANTHROPIC_API_KEY)

Point `avow gauntlet` at a known-wrong-but-green solution and a correct one:
- correct SemVer comparator (from the earlier live run) → `VERIFIED SURVIVOR`.
- a solution with a deliberate pre-release-ordering bug the visible suite misses → `KILLED` with the counterexample.
Then `avow survive` on a goal whose first green hides a gap → watch it kill, freeze the diff test, rebuild, and either earn `verified_survivor` or die honestly at `gauntlet_max_rounds`.

## Out of scope (backlog — see `2026-07-15-avow-survival-instinct-backlog.md`)

- **B: Coroner + Graveyard** — abstract each counterexample into a transferable AttackPattern, persist globally, seed future gauntlets.
- **C: Calibration proof** — show `verified_survivor` beats plain green on false-high-confidence via `avow calibrate`.
