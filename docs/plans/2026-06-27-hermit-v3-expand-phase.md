# Hermit v3 — The Expand Phase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the one-shot converge loop into a two-phase self-improving loop: after converging, an Ideator proposes the next feature, it's folded into the suite (via the Examiner), and the loop re-converges — bounded by a round cap and a human leash.

**Architecture:** A new `hermit/ideator.py` (LLM proposes ranked ideas + a pure `select_idea` leash) and `hermit/improve.py` (an orchestrator that wraps the existing `solve()` — converge → ideate → leash → grow the frozen suite → re-converge). A `hermit improve` CLI. `solve()` itself is unchanged.

**Tech Stack:** Python 3.12 · `anthropic` structured outputs · reuses `hermit.loop.solve` / `hermit.examiner` / `hermit.config`.

## Global Constraints

- Python **3.11+** (Hermit-local venv at `/Users/qatadaha/Coding/hermit/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && <cmd>`.
- Model IDs exact, no date suffixes. `ideator_model` defaults to `claude-opus-4-8`.
- LLM call uses `client.messages.parse(..., output_format=_IdeaSet)` → `.parsed_output`, `.usage`; never set `temperature`/`top_p`/`top_k`. Injectable client; unit tests use fakes, spend no tokens.
- Reuses verified interfaces (do NOT modify them): `solve(goal_dir, config, examiner, builder, *, now=time.monotonic, write_tests=True, confirm=None, mutation_client=None, intent_client=None, escalate=None, property_client=None) -> SolveResult`; `goal` is read by `solve` from `goal_dir / "goal.md"`; the frozen suite lives at `goal_dir / "tests_frozen"`; `examiner.write_tests(goal) -> ExaminerResult(suite=TestSuite(test_plan: str, tests: list[TestFile(path: str, content: str)]), input_tokens: int, output_tokens: int)`; `SolveResult(success, best_score, iterations, reason, best_dir, intent_score=None, confidence=None, confidence_breakdown={})`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: The Ideator (`propose_ideas`)

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/ideator.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_ideator.py`

**Interfaces:**
- Produces: `Idea(BaseModel)` with `description: str, verifier: str, objective: bool, risk: str`; `_IdeaSet(BaseModel)` with `ideas: list[Idea]`; `propose_ideas(goal: str, current_tests: str, client, model: str, n: int) -> tuple[list[Idea], int, int]` returning up to `n` ranked ideas + `(input_tokens, output_tokens)`. `([], 0, 0)` when `n<=0` or `client is None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ideator.py
from types import SimpleNamespace
from hermit.ideator import propose_ideas, Idea, _IdeaSet


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._payload,
            usage=SimpleNamespace(input_tokens=11, output_tokens=22),
        )


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_propose_ideas_returns_ideas_and_tokens():
    payload = _IdeaSet(ideas=[
        Idea(description="handle unicode input", verifier="test_unicode passes", objective=True, risk="low"),
        Idea(description="make it 'nicer'", verifier="subjective", objective=False, risk="high"),
    ])
    client = FakeClient(payload)
    ideas, in_tok, out_tok = propose_ideas("build slugify", "def test_basic(): ...",
                                           client, "claude-opus-4-8", 3)
    assert len(ideas) == 2 and isinstance(ideas[0], Idea)
    assert ideas[0].objective is True and ideas[0].risk == "low"
    assert in_tok == 11 and out_tok == 22
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _IdeaSet
    content = sent["messages"][0]["content"]
    assert "build slugify" in content and "def test_basic" in content


def test_propose_ideas_noop_without_client_or_count():
    assert propose_ideas("g", "t", None, "m", 3) == ([], 0, 0)
    assert propose_ideas("g", "t", object(), "m", 0) == ([], 0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_ideator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.ideator'`.

- [ ] **Step 3: Write `hermit/ideator.py`**

```python
# hermit/ideator.py
from __future__ import annotations

from pydantic import BaseModel


class Idea(BaseModel):
    description: str
    verifier: str
    objective: bool
    risk: str  # "low" | "high"


class _IdeaSet(BaseModel):
    ideas: list[Idea]


_IDEATOR_PROMPT = """\
You are improving a software artifact. Given its GOAL and the tests that already \
exist, propose up to {n} concrete NEXT features or improvements — ranked best-first \
— that would make it genuinely better or more complete. For each, give:
- description: the feature/improvement, concretely.
- verifier: how it would be checked — ideally an objective behavioral test.
- objective: true if the verifier is an objective pass/fail test (not a matter of taste).
- risk: "low" if it is a safe, well-scoped addition; "high" if it is broad, ambiguous, \
or could break existing behavior.

Prefer improvements that are objectively verifiable and not already covered by the \
existing tests. Do NOT propose things the tests already check.

GOAL:
{goal}

EXISTING TESTS:
{current_tests}
"""


def propose_ideas(goal: str, current_tests: str, client, model: str, n: int):
    if n <= 0 or client is None:
        return [], 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": _IDEATOR_PROMPT.format(
            n=n, goal=goal, current_tests=current_tests)}],
        output_format=_IdeaSet,
    )
    usage = response.usage
    return (
        list(response.parsed_output.ideas[:n]),
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_ideator.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/ideator.py tests/test_ideator.py && git commit -m "feat: Ideator — propose ranked next-feature ideas with verifier + risk"
```

---

### Task 2: The leash (`select_idea`)

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/ideator.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_select_idea.py`

**Interfaces:**
- Produces: `select_idea(ideas: list[Idea], escalate) -> tuple[Idea | None, bool]`. Take the top idea; if `objective and risk == "low"` → `(top, False)` (auto). Else call `escalate(top)` (if `escalate` is not None): truthy → `(top, True)`; falsy/`None` callback → `(None, True)`. Empty list → `(None, False)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_select_idea.py
from hermit.ideator import select_idea, Idea


def _idea(objective, risk):
    return Idea(description="x", verifier="v", objective=objective, risk=risk)


def test_objective_low_risk_auto_pursues():
    top = _idea(True, "low")
    chosen, escalated = select_idea([top, _idea(True, "low")], escalate=None)
    assert chosen is top and escalated is False


def test_high_risk_escalates_accept():
    top = _idea(True, "high")
    chosen, escalated = select_idea([top], escalate=lambda idea: True)
    assert chosen is top and escalated is True


def test_high_risk_escalates_reject():
    chosen, escalated = select_idea([_idea(True, "high")], escalate=lambda idea: False)
    assert chosen is None and escalated is True


def test_non_objective_escalates():
    chosen, escalated = select_idea([_idea(False, "low")], escalate=lambda idea: False)
    assert chosen is None and escalated is True


def test_no_callback_does_not_auto_pursue_risky():
    chosen, escalated = select_idea([_idea(False, "low")], escalate=None)
    assert chosen is None and escalated is True


def test_empty_list():
    assert select_idea([], escalate=None) == (None, False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_select_idea.py -q`
Expected: FAIL — `ImportError: cannot import name 'select_idea'`.

- [ ] **Step 3: Append to `hermit/ideator.py`**

```python
def select_idea(ideas, escalate):
    if not ideas:
        return None, False
    top = ideas[0]
    if top.objective and top.risk == "low":
        return top, False
    if escalate is not None and escalate(top):
        return top, True
    return None, True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_select_idea.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/ideator.py tests/test_select_idea.py && git commit -m "feat: select_idea leash — auto-pursue objective low-risk, escalate the rest"
```

---

### Task 3: `RunConfig` expand settings

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/config.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `max_expand_rounds: int = 3`, `ideator_model: str = "claude-opus-4-8"`, `ideas_n: int = 3`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.max_expand_rounds == 3
    assert cfg.ideator_model == "claude-opus-4-8"
    assert cfg.ideas_n == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'max_expand_rounds'`.

- [ ] **Step 3: Add the fields to `RunConfig` in `hermit/config.py`**

Add after the panel fields (`panel_agreement_floor`):

```python
    max_expand_rounds: int = 3
    ideator_model: str = "claude-opus-4-8"
    ideas_n: int = 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/config.py tests/test_config.py && git commit -m "feat: expand-phase settings on RunConfig"
```

---

### Task 4: The `improve()` orchestrator

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/improve.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_improve.py`

**Interfaces:**
- Produces: `ImproveResult(success: bool, expansions: int, rounds: list, final)`; `improve(goal_dir, config, examiner, builder, *, ideator_client=None, escalate=None, mutation_client=None, intent_client=None, property_client=None, now=time.monotonic) -> ImproveResult`.
- Helpers: `_read_test_sources(frozen_dir) -> str` (sorted `test_*.py`, per-file header); `_append_tests(frozen_dir, tests, round_num)` (writes each `TestFile`, renaming `test_<x>.py` → `test_e<round_num>_<x>.py` so it stays pytest-collectable and never collides across rounds).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_improve.py
from pathlib import Path
from types import SimpleNamespace
from hermit.config import RunConfig
from hermit.improve import improve, ImproveResult
from hermit.examiner import ExaminerResult, TestSuite, TestFile
from hermit.ideator import _IdeaSet, Idea
from hermit.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


class StubExaminer:
    def write_tests(self, goal: str) -> ExaminerResult:
        suite = TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py",
            content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        return ExaminerResult(suite=suite, input_tokens=0, output_tokens=0)


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class IdeatorClient:
    """Always proposes one objective low-risk idea."""
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _IdeaSet(ideas=[Idea(description="also handle add(0, 0)",
                                  verifier="test passes", objective=True, risk="low")])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_improve_runs_one_expansion(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, max_expand_rounds=1)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(),
                ideator_client=IdeatorClient(), now=lambda: 0.0)
    assert isinstance(r, ImproveResult)
    assert r.success is True
    assert r.expansions == 1                      # round cap stops after one expansion
    assert len(r.rounds) == 2                     # initial converge + 1 re-converge
    # the chosen idea's test was appended to the frozen suite (renamed, collision-free):
    assert (tmp_path / "tests_frozen" / "test_e1_add.py").exists()


def test_improve_without_ideator_reduces_to_solve(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(), now=lambda: 0.0)
    assert r.success is True and r.expansions == 0 and len(r.rounds) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_improve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.improve'`.

- [ ] **Step 3: Write `hermit/improve.py`**

```python
# hermit/improve.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from hermit.loop import solve
from hermit.ideator import propose_ideas, select_idea


@dataclass
class ImproveResult:
    success: bool
    expansions: int
    rounds: list
    final: object


def _read_test_sources(frozen_dir) -> str:
    frozen_dir = Path(frozen_dir)
    parts = []
    for f in sorted(frozen_dir.glob("test_*.py")):
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _append_tests(frozen_dir, tests, round_num) -> None:
    frozen_dir = Path(frozen_dir)
    frozen_dir.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(tests):
        stem = Path(t.path).name
        if stem.startswith("test_"):
            name = f"test_e{round_num}_{stem[len('test_'):]}"
        else:
            name = f"test_e{round_num}_{i}_{stem}"
        (frozen_dir / name).write_text(t.content, encoding="utf-8")


def improve(goal_dir, config, examiner, builder, *, ideator_client=None, escalate=None,
            mutation_client=None, intent_client=None, property_client=None, now=time.monotonic):
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()
    frozen = goal_dir / "tests_frozen"

    result = solve(goal_dir, config, examiner, builder, now=now, write_tests=True,
                   mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client)
    rounds = [result]
    expansions = 0

    while (result.success and ideator_client is not None
           and expansions < config.max_expand_rounds):
        ideas, _i, _o = propose_ideas(
            goal, _read_test_sources(frozen), ideator_client, config.ideator_model, config.ideas_n)
        chosen, _escalated = select_idea(ideas, escalate)
        if chosen is None:
            break
        ex = examiner.write_tests(chosen.description)
        _append_tests(frozen, ex.suite.tests, expansions + 1)
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client)
        rounds.append(result)
        expansions += 1

    return ImproveResult(success=result.success, expansions=expansions, rounds=rounds, final=result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_improve.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS (all prior + v3), 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/improve.py tests/test_improve.py && git commit -m "feat: improve() orchestrator — converge, ideate, grow the suite, re-converge"
```

---

### Task 5: `hermit improve` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/cli.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_cli_improve.py`

**Interfaces:**
- New subcommand: `hermit improve <goal_dir> [--config hermit.yaml] [--no-llm-verify]`. Builds the Examiner + Builder + a shared verify client (unless `--no-llm-verify`), runs `improve(...)` passing the client as `ideator_client`/`intent_client`/`property_client`, prints the verdict + per-round lines. The existing `solve`/`mutate`/`intent-check`/`verify`/`propertize` subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_improve.py
from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.examiner import TestSuite, TestFile
from hermit.ideator import _IdeaSet
from hermit.builder import BuilderOutcome


class DispatchClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        name = output_format.__name__
        if name == "TestSuite":
            po = TestSuite(test_plan="add", tests=[TestFile(
                path="test_add.py",
                content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        elif name == "_IdeaSet":
            po = _IdeaSet(ideas=[])           # no ideas -> 0 expansions, exercises the round-0 path
        elif name == "_InferredGoal":
            from hermit.backtranslation import _InferredGoal
            po = _InferredGoal(inferred_goal="add two integers")
        elif name == "IntentMatch":
            from hermit.backtranslation import IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        else:  # _PropertySet
            from hermit.properties import _PropertySet
            po = _PropertySet(tests=[])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_hermit_improve_cli(tmp_path: Path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["improve", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "expansions=0" in out
    assert "round 0" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_improve.py -q`
Expected: FAIL — argparse `invalid choice: 'improve'`.

- [ ] **Step 3: Edit `hermit/cli.py`**

Add the subparser inside `main` (after the `propertize` subparser, before `parse_args`):

```python
    improve_p = sub.add_parser("improve",
                               help="self-improvement loop: converge, then propose & build next features")
    improve_p.add_argument("goal_dir")
    improve_p.add_argument("--config", default=None)
    improve_p.add_argument("--no-llm-verify", action="store_true")
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "improve":
        return _cmd_improve(args)
```

Add the handler at module level:

```python
def _cmd_improve(args) -> int:
    from hermit.improve import improve

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    result = improve(Path(args.goal_dir), config, examiner, builder,
                     ideator_client=verify_client, intent_client=verify_client,
                     property_client=verify_client)

    print(f"result: success={result.success} expansions={result.expansions}")
    for i, r in enumerate(result.rounds):
        print(f"  round {i}: success={r.success} reason={r.reason} confidence={r.confidence}")
    return 0 if result.success else 2
```

(Use the existing module-level imports for `RunConfig`, `build_examiner`, `Builder`, `Path` — they are already imported in `cli.py`. Confirm by reading the top of the file; only add what's missing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_improve.py tests/test_cli.py -q`
Expected: PASS (improve CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q && hermit --help`
Expected: all tests PASS, 0 warnings; `hermit --help` lists `solve`, `mutate`, `intent-check`, `verify`, `propertize`, `improve`.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/cli.py tests/test_cli_improve.py && git commit -m "feat: hermit improve CLI — the self-improvement expand loop"
```

---

## Manual validation (after Task 5, with credentials)

`hermit improve ~/Coding/hermit-demo-full` → converges on the goal, then the Ideator proposes the next feature; objective low-risk ones auto-pursue (the suite grows and re-converges), riskier ones would escalate. Prints a line per round.

## What v3 deliberately does NOT do (later)

- The Supervisor (event-triggered trajectory guardian) and Population/Hybrid strategies.
- A single shared global budget across expand rounds (v3 uses per-round caps bounded by `max_expand_rounds`).
- Persisting the idea history / north-star tracking beyond the per-run `ImproveResult`.
