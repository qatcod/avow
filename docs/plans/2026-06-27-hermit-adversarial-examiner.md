# Hermit — Adversarial-Escalating Examiner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** After a solution converges, have the Examiner read it and write harder tests aimed at its weak spots; the suite battle-hardens across escalation rounds via a `harden()` orchestrator + `hermit harden` CLI.

**Architecture:** A new `Examiner.write_adversarial_tests(goal, solution_code)` method and `hermit/harden.py` (wraps the existing `solve()`: converge → adversarial-escalate → re-converge), reusing `improve`'s suite-growth + last-known-good helpers. `solve()` is unchanged.

**Tech Stack:** Python 3.12 · `anthropic` structured outputs · reuses `hermit.examiner`/`hermit.improve`/`hermit.loop`/`hermit.config`.

## Global Constraints

- Python **3.11+** (Hermit-local venv at `/Users/qatadaha/Coding/hermit/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && <cmd>`.
- Model IDs exact, no date suffixes. The adversarial Examiner reuses the configured `examiner_model`.
- LLM call uses `client.messages.parse(..., output_format=TestSuite)` → `.parsed_output`, `.usage`; never set `temperature`/`top_p`/`top_k`. Injectable client; tests use fakes.
- Reuses verified interfaces (do NOT modify): `solve(goal_dir, config, examiner, builder, *, now, write_tests, ..., mutation_client, intent_client, escalate, property_client, oracle_client) -> SolveResult`; `solve` reads the goal from `goal_dir/"goal.md"`; frozen = `goal_dir/"tests_frozen"`, holdout = `goal_dir/"tests_holdout"`; `ExaminerResult(suite=TestSuite(test_plan, tests=[TestFile(path, content)]), input_tokens, output_tokens)`; `split_suite(tests, fraction)` from `hermit.examiner`; `_append_tests(dest_dir, tests, round_num)` / `_read_test_sources(frozen_dir)` / `_snapshot(src, dest)` from `hermit.improve`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `Examiner.write_adversarial_tests`

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/examiner.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_examiner_adversarial.py`

**Interfaces:**
- Produces: `Examiner.write_adversarial_tests(goal: str, solution_code: str) -> ExaminerResult`. Same return shape as `write_tests`; prompt forwards both the goal and the solution code, instructing tests that break this specific implementation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_examiner_adversarial.py
from types import SimpleNamespace
from hermit.examiner import Examiner, TestSuite, TestFile


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=7, output_tokens=8))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_write_adversarial_tests_forwards_goal_and_solution():
    suite = TestSuite(test_plan="break it", tests=[TestFile(path="test_adv_edges.py", content="# adv\n")])
    client = FakeClient(suite)
    ex = Examiner(client, "claude-opus-4-8")
    res = ex.write_adversarial_tests("build slugify(s)", "def slugify(s):\n    return s.lower()\n")
    assert res.suite is suite and res.input_tokens == 7 and res.output_tokens == 8
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is TestSuite
    content = sent["messages"][0]["content"]
    assert "build slugify(s)" in content              # goal forwarded
    assert "return s.lower()" in content               # solution code forwarded
    assert "break" in content.lower()                  # adversarial framing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_examiner_adversarial.py -q`
Expected: FAIL — `AttributeError: 'Examiner' object has no attribute 'write_adversarial_tests'`.

- [ ] **Step 3: Edit `hermit/examiner.py`**

Add the prompt near `_PROMPT`:

```python
_ADVERSARIAL_PROMPT = """\
You are a ruthless adversarial QA engineer. Below is a GOAL and an implementation that \
ALREADY PASSES the current test suite. Your job is to BREAK it: write NEW pytest tests \
that target THIS implementation's weak spots — boundary conditions, extreme/unusual \
inputs, error handling, and properties it might violate. Hunt for the inputs where it \
goes wrong.

Rules:
- Tests import the implementation from a top-level module (e.g. `from lib import add`).
- Do NOT include the implementation — only tests.
- Each file path is a bare filename like `test_adv_<area>.py` (no directories).
- Write tests a CORRECT implementation passes but a subtly-wrong one fails; do NOT assert \
behavior the goal does not require.

GOAL:
{goal}

CURRENT IMPLEMENTATION (passes the existing suite — find where it breaks):
{solution_code}
"""
```

Add the method to `Examiner` (after `write_tests`):

```python
    def write_adversarial_tests(self, goal: str, solution_code: str) -> ExaminerResult:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            messages=[{"role": "user",
                       "content": _ADVERSARIAL_PROMPT.format(goal=goal, solution_code=solution_code)}],
            output_format=TestSuite,
        )
        usage = response.usage
        return ExaminerResult(
            suite=response.parsed_output,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_examiner_adversarial.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/examiner.py tests/test_examiner_adversarial.py && git commit -m "feat: Examiner.write_adversarial_tests — harder tests targeting a passing solution"
```

---

### Task 2: `RunConfig.adversarial_rounds`

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/config.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `adversarial_rounds: int = 2`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.adversarial_rounds == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'adversarial_rounds'`.

- [ ] **Step 3: Edit `hermit/config.py`**

Add after the oracle fields (`oracle_floor`):

```python
    adversarial_rounds: int = 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/config.py tests/test_config.py && git commit -m "feat: adversarial_rounds setting on RunConfig"
```

---

### Task 3: The `harden()` orchestrator

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/harden.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_harden.py`

**Interfaces:**
- Produces: `HardenResult(success, rounds_run, rounds, final, best_round=-1, best_dir=None)`; `harden(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> HardenResult`; `_read_solution_code(best_dir) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_harden.py
from pathlib import Path
from hermit.config import RunConfig
from hermit.harden import harden, HardenResult
from hermit.examiner import ExaminerResult, TestSuite, TestFile
from hermit.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


def _add_suite():
    return ExaminerResult(suite=TestSuite(test_plan="add", tests=[TestFile(
        path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")]),
        input_tokens=0, output_tokens=0)


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class SurvivingExaminer:
    """Goal suite + adversarial tests the (correct) solution survives."""
    def write_tests(self, goal):
        return _add_suite()

    def write_adversarial_tests(self, goal, solution_code):
        return ExaminerResult(suite=TestSuite(test_plan="adv", tests=[TestFile(
            path="test_adv.py", content="from lib import add\ndef test_adv():\n    assert add(0, 0) == 0\n")]),
            input_tokens=0, output_tokens=0)


class BreakingExaminer:
    """The adversarial round writes an IMPOSSIBLE test (add=a+b can't satisfy)."""
    def write_tests(self, goal):
        return _add_suite()

    def write_adversarial_tests(self, goal, solution_code):
        return ExaminerResult(suite=TestSuite(test_plan="adv", tests=[TestFile(
            path="test_adv.py", content="from lib import add\ndef test_adv():\n    assert add(2, 3) == 999\n")]),
            input_tokens=0, output_tokens=0)


def test_harden_runs_escalation_rounds(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, adversarial_rounds=2)
    r = harden(_goal(tmp_path), cfg, SurvivingExaminer(), StubBuilder(), now=lambda: 0.0)
    assert isinstance(r, HardenResult)
    assert r.success is True
    assert r.rounds_run == 2                       # both escalation rounds ran
    assert len(r.rounds) == 3                       # initial converge + 2 escalations
    assert (tmp_path / "tests_frozen" / "test_e1_adv.py").exists()
    assert (tmp_path / "tests_frozen" / "test_e2_adv.py").exists()


def test_harden_preserves_last_known_good_when_adversary_wins(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, adversarial_rounds=2)
    r = harden(_goal(tmp_path), cfg, BreakingExaminer(), StubBuilder(), now=lambda: 0.0)
    assert r.rounds_run == 1                        # the impossible adversarial round fails -> stop
    assert r.final.success is False
    assert r.best_round == 0                         # last green was the initial converge
    assert r.best_dir is not None and Path(r.best_dir).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_harden.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.harden'`.

- [ ] **Step 3: Write `hermit/harden.py`**

```python
# hermit/harden.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from hermit.loop import solve
from hermit.examiner import split_suite
from hermit.improve import _append_tests, _snapshot


@dataclass
class HardenResult:
    success: bool
    rounds_run: int
    rounds: list
    final: object
    best_round: int = -1
    best_dir: object = None


def _read_solution_code(best_dir) -> str:
    best_dir = Path(best_dir)
    parts = []
    for f in sorted(best_dir.glob("*.py")):
        if f.name.startswith("test_") or f.name == "conftest.py":
            continue
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def harden(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None,
           property_client=None, oracle_client=None, now=time.monotonic) -> HardenResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_src = goal_dir / ".hermit" / "best"
    lkg = goal_dir / ".hermit" / "best_good"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    rounds = [result]
    rounds_run = 0
    best_round = -1
    best_dir = None
    if result.success and best_src.exists():
        _snapshot(best_src, lkg)
        best_round, best_dir = 0, lkg

    while result.success and rounds_run < config.adversarial_rounds:
        adv = examiner.write_adversarial_tests(goal, _read_solution_code(best_src))
        visible, held = split_suite(adv.suite.tests, config.holdout_fraction)
        _append_tests(frozen, visible, rounds_run + 1)
        _append_tests(holdout, held, rounds_run + 1)
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
        rounds.append(result)
        rounds_run += 1
        if result.success and best_src.exists():
            _snapshot(best_src, lkg)
            best_round, best_dir = rounds_run, lkg

    return HardenResult(success=result.success, rounds_run=rounds_run, rounds=rounds,
                        final=result, best_round=best_round, best_dir=best_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_harden.py -q`
Expected: PASS (2 passed). (Runs real pytest subprocesses via the Runner — venv must be active.)

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/harden.py tests/test_harden.py && git commit -m "feat: harden() — escalate the suite with adversarial tests, re-converge each round"
```

---

### Task 4: `hermit harden` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/cli.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_cli_harden.py`

**Interfaces:**
- New subcommand: `hermit harden <goal_dir> [--config hermit.yaml] [--no-llm-verify]`. Builds the Examiner + Builder + a shared verify client (unless `--no-llm-verify`), runs `harden(...)` passing the client as `intent_client`/`property_client`/`oracle_client`, prints the verdict + per-round lines. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_harden.py
from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.examiner import TestSuite, TestFile
from hermit.builder import BuilderOutcome


class DispatchClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        name = output_format.__name__
        if name == "TestSuite":
            po = TestSuite(test_plan="add", tests=[TestFile(
                path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        elif name == "_InferredGoal":
            from hermit.backtranslation import _InferredGoal
            po = _InferredGoal(inferred_goal="add two integers")
        elif name == "IntentMatch":
            from hermit.backtranslation import IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        elif name == "_PropertySet":
            from hermit.properties import _PropertySet
            po = _PropertySet(tests=[])
        else:  # _OraclePair
            from hermit.oracle import _OraclePair
            po = _OraclePair(reference_code="def add(a, b):\n    return a + b\n",
                             diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                             "from hypothesis import given, strategies as st\n"
                                             "@given(st.integers(), st.integers())\n"
                                             "def test_d(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_hermit_harden_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["harden", str(tmp_path), "--config", str(_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "adversarial_rounds=" in out
    assert "round 0" in out


def _cfg(tmp_path):
    p = tmp_path / "hermit.yaml"
    p.write_text("adversarial_rounds: 1\nholdout_fraction: 0.0\nmax_iterations: 5\n")
    return p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_harden.py -q`
Expected: FAIL — argparse `invalid choice: 'harden'`.

- [ ] **Step 3: Edit `hermit/cli.py`**

Add the subparser inside `main` (after the `oracle` subparser, before `parse_args`):

```python
    harden_p = sub.add_parser("harden",
                              help="build, then escalate the suite with adversarial tests over rounds")
    harden_p.add_argument("goal_dir")
    harden_p.add_argument("--config", default=None)
    harden_p.add_argument("--no-llm-verify", action="store_true")
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "harden":
        return _cmd_harden(args)
```

Add the handler at module level:

```python
def _cmd_harden(args) -> int:
    from hermit.harden import harden

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    result = harden(Path(args.goal_dir), config, examiner, builder,
                    intent_client=verify_client, property_client=verify_client,
                    oracle_client=verify_client)

    print(f"result: success={result.success} adversarial_rounds={result.rounds_run}")
    for i, r in enumerate(result.rounds):
        print(f"  round {i}: success={r.success} reason={r.reason} confidence={r.confidence}")
    return 0 if result.success else 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_harden.py tests/test_cli.py -q`
Expected: PASS (harden CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q && hermit --help`
Expected: all tests PASS, 0 warnings; `hermit --help` lists `solve`, `improve`, `harden`, `mutate`, `intent-check`, `verify`, `propertize`, `oracle`.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/cli.py tests/test_cli_harden.py && git commit -m "feat: hermit harden CLI — build + adversarially battle-harden the suite"
```

---

## Manual validation (after Task 4, with credentials)

`hermit harden ~/Coding/hermit-demo-full` → converges, then the Examiner reads the solution and writes harder tests targeting it; the suite grows and re-converges each round. Prints a line per round.

## What this deliberately does NOT do (later)

- A different-family adversary model (stronger decorrelation).
- Early stop when the adversary genuinely can't break the solution (vs. fixed `adversarial_rounds`).
- Budgeting the orchestrator-level `write_adversarial_tests` token cost (per-round budget only, like `improve`).
