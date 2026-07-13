# Avow — Population / Hybrid Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run N candidate solutions against the same suite and let the verifier pick the winner (`population_solve`), plus an escalate-on-plateau wrapper (`hybrid_solve`) and a `avow population` CLI.

**Architecture:** A new `avow/population.py` reusing the unchanged `solve()` per candidate with isolated workspaces that share a copy of the suite; `select_best` ranks by confidence. `solve()` is not refactored.

**Tech Stack:** Python 3.12 · reuses `avow.loop.solve`/`SolveResult` · `avow.improve._snapshot` · integrates with `avow.config`/`avow.cli`.

## Global Constraints

- Python **3.11+** (Avow-local venv at `/Users/qatadaha/Coding/avow/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && <cmd>`.
- Reuses verified interfaces (do NOT modify): `solve(goal_dir, config, examiner, builder, *, now, write_tests, mutation_client, intent_client, property_client, oracle_client, ...) -> SolveResult`; `SolveResult(success, best_score, iterations, reason, best_dir, mutation_score=None, survivors=0, intent_score=None, confidence=None, confidence_breakdown={}, oracle_agreement=None)`; `solve` reads the goal from `goal_dir/"goal.md"`, writes `goal_dir/"tests_frozen"` + `goal_dir/"tests_holdout"`, and the best solution to `goal_dir/".avow"/"best"`; `_snapshot(src, dest)` from `avow.improve`.
- Candidates run **sequentially**; each `solve()` keeps its own per-candidate budget.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `select_best` + result dataclasses (pure)

**Files:**
- Create: `/Users/qatadaha/Coding/avow/avow/population.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_population_select.py`

**Interfaces:**
- Produces: `Candidate(index: int, result, solution_dir)`; `PopulationResult(success, best, candidates, winner_index)`; `select_best(results: list) -> int` — index of the best `SolveResult` by (`success` desc, `confidence` desc with `None` last, `best_score` desc); ties → lowest index; empty → `-1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_population_select.py
from avow.population import select_best
from avow.loop import SolveResult


def _r(success, confidence, score=1.0):
    return SolveResult(success, score, 1, "green" if success else "low_confidence", None,
                       confidence=confidence)


def test_green_high_confidence_wins():
    assert select_best([_r(True, 0.8), _r(True, 0.95), _r(False, None, 0.5)]) == 1


def test_green_beats_nongreen_even_at_lower_confidence():
    assert select_best([_r(False, 0.99), _r(True, 0.7)]) == 1


def test_none_confidence_ranks_last_among_greens():
    assert select_best([_r(True, None), _r(True, 0.5)]) == 1


def test_ties_break_to_lowest_index():
    assert select_best([_r(True, 0.9), _r(True, 0.9)]) == 0


def test_empty_is_minus_one():
    assert select_best([]) == -1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population_select.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'avow.population'`.

- [ ] **Step 3: Write `avow/population.py`**

```python
# avow/population.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Candidate:
    index: int
    result: object
    solution_dir: object


@dataclass
class PopulationResult:
    success: bool
    best: object
    candidates: list
    winner_index: int


def _rank_key(result) -> tuple:
    conf = result.confidence if result.confidence is not None else -1.0
    return (1 if result.success else 0, conf, result.best_score)


def select_best(results: list) -> int:
    if not results:
        return -1
    best_i = 0
    for i in range(1, len(results)):
        if _rank_key(results[i]) > _rank_key(results[best_i]):
            best_i = i
    return best_i
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population_select.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/population.py tests/test_population_select.py && git commit -m "feat: select_best — rank candidate solutions by success, confidence, score"
```

---

### Task 2: `RunConfig.population_size`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/config.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `population_size: int = 3`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.population_size == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'population_size'`.

- [ ] **Step 3: Edit `avow/config.py`**

Add after `adversarial_rounds`:

```python
    population_size: int = 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: population_size setting on RunConfig"
```

---

### Task 3: `population_solve` + `hybrid_solve`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/population.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_population.py`

**Interfaces:**
- Produces: `population_solve(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> PopulationResult`; `hybrid_solve(...same signature...) -> PopulationResult`; helpers `_stage_candidate(goal_dir, cand_dir)`, `_run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_population.py
from pathlib import Path
from avow.config import RunConfig
from avow.population import population_solve, hybrid_solve, PopulationResult
from avow.examiner import ExaminerResult, TestSuite, TestFile
from avow.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


class StubExaminer:
    def write_tests(self, goal):
        return ExaminerResult(suite=TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")]),
            input_tokens=0, output_tokens=0)


class GoodBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class BadBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a - b\n")  # wrong
        return BuilderOutcome(plan="nope", cost_usd=0.0, raw={})


def test_population_runs_candidates_and_selects(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=2)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert isinstance(r, PopulationResult)
    assert r.success is True
    assert len(r.candidates) == 2
    assert r.winner_index in (0, 1)
    assert (tmp_path / ".avow" / "best" / "lib.py").exists()           # winner promoted
    assert (tmp_path / ".avow" / "candidates" / "1" / "tests_frozen").exists()  # candidate 1 staged with a suite copy


def test_population_size_one_is_single_solve(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=1)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 1 and r.winner_index == 0


def test_hybrid_does_not_escalate_when_first_is_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=3)
    r = hybrid_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 1   # green on first -> no population


def test_hybrid_escalates_on_failure(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, population_size=2)
    r = hybrid_solve(_goal(tmp_path), cfg, StubExaminer(), BadBuilder(), now=lambda: 0.0)
    assert r.success is False and len(r.candidates) == 2   # first failed -> escalated to the pool
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population.py -q`
Expected: FAIL — `ImportError: cannot import name 'population_solve'`.

- [ ] **Step 3: Append to `avow/population.py`**

Add the imports at the top (with the existing ones):

```python
import shutil
import time
from pathlib import Path

from avow.loop import solve
from avow.improve import _snapshot
```

Append:

```python
def _stage_candidate(goal_dir, cand_dir) -> None:
    goal_dir, cand_dir = Path(goal_dir), Path(cand_dir)
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir(parents=True)
    shutil.copy2(goal_dir / "goal.md", cand_dir / "goal.md")
    for name in ("tests_frozen", "tests_holdout"):
        src = goal_dir / name
        if src.exists():
            shutil.copytree(src, cand_dir / name)


def _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now) -> PopulationResult:
    goal_dir = Path(goal_dir)
    for i in range(len(candidates), max(1, config.population_size)):
        cand_dir = goal_dir / ".avow" / "candidates" / str(i)
        _stage_candidate(goal_dir, cand_dir)
        ri = solve(cand_dir, config, examiner, builder, now=now, write_tests=False, **clients)
        candidates.append(Candidate(i, ri, cand_dir / ".avow" / "best"))

    results = [c.result for c in candidates]
    winner = select_best(results)
    win_dir = candidates[winner].solution_dir
    dest = goal_dir / ".avow" / "best"
    if winner != 0 and Path(win_dir).exists():
        _snapshot(win_dir, dest)
    return PopulationResult(success=results[winner].success, best=results[winner],
                            candidates=candidates, winner_index=winner)


def population_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                     intent_client=None, property_client=None, oracle_client=None,
                     now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".avow" / "best")]
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)


def hybrid_solve(goal_dir, config, examiner, builder, *, mutation_client=None,
                 intent_client=None, property_client=None, oracle_client=None,
                 now=time.monotonic) -> PopulationResult:
    goal_dir = Path(goal_dir)
    clients = dict(mutation_client=mutation_client, intent_client=intent_client,
                   property_client=property_client, oracle_client=oracle_client)
    r0 = solve(goal_dir, config, examiner, builder, now=now, write_tests=True, **clients)
    candidates = [Candidate(0, r0, goal_dir / ".avow" / "best")]
    if r0.success:
        return PopulationResult(success=True, best=r0, candidates=candidates, winner_index=0)
    return _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population.py -q`
Expected: PASS (4 passed). (Runs real pytest subprocesses via the Runner — venv must be active.)

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/population.py tests/test_population.py && git commit -m "feat: population_solve + hybrid_solve — N candidates, verifier picks the winner"
```

---

### Task 4: `avow population` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/cli.py`
- Test: `/Users/qatadaha/Coding/avow/tests/test_cli_population.py`

**Interfaces:**
- New subcommand: `avow population <goal_dir> [--config avow.yaml] [--no-llm-verify] [--hybrid]`. Builds the Examiner + Builder + a shared verify client (unless `--no-llm-verify`), runs `hybrid_solve` (with `--hybrid`) or `population_solve`, prints the winner + a line per candidate. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_population.py
from pathlib import Path
from types import SimpleNamespace
import avow.cli as cli
from avow.examiner import TestSuite, TestFile
from avow.builder import BuilderOutcome


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
            from avow.backtranslation import _InferredGoal
            po = _InferredGoal(inferred_goal="add two integers")
        elif name == "IntentMatch":
            from avow.backtranslation import IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        elif name == "_PropertySet":
            from avow.properties import _PropertySet
            po = _PropertySet(tests=[])
        else:  # _OraclePair
            from avow.oracle import _OraclePair
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


def _cfg(tmp_path):
    p = tmp_path / "avow.yaml"
    p.write_text("population_size: 2\nholdout_fraction: 0.0\nmax_iterations: 5\n")
    return p


def test_avow_population_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["population", str(tmp_path), "--config", str(_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "winner" in out.lower()
    assert "candidate 0" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_population.py -q`
Expected: FAIL — argparse `invalid choice: 'population'`.

- [ ] **Step 3: Edit `avow/cli.py`**

Add the subparser inside `main` (after the `harden` subparser, before `parse_args`):

```python
    pop_p = sub.add_parser("population",
                           help="run N candidate solutions and let the verifier pick the winner")
    pop_p.add_argument("goal_dir")
    pop_p.add_argument("--config", default=None)
    pop_p.add_argument("--no-llm-verify", action="store_true")
    pop_p.add_argument("--hybrid", action="store_true",
                       help="run one attempt first; escalate to the population only on failure")
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "population":
        return _cmd_population(args)
```

Add the handler at module level:

```python
def _cmd_population(args) -> int:
    from avow.population import population_solve, hybrid_solve

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    run = hybrid_solve if args.hybrid else population_solve
    result = run(Path(args.goal_dir), config, examiner, builder,
                 intent_client=verify_client, property_client=verify_client,
                 oracle_client=verify_client)

    print(f"result: success={result.success} winner=candidate {result.winner_index} "
          f"({len(result.candidates)} candidates)")
    for c in result.candidates:
        print(f"  candidate {c.index}: success={c.result.success} reason={c.result.reason} "
              f"confidence={c.result.confidence}")
    return 0 if result.success else 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_cli_population.py tests/test_cli.py -q`
Expected: PASS (population CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q && avow --help`
Expected: all tests PASS, 0 warnings; `avow --help` lists `solve`, `improve`, `harden`, `population`, `mutate`, `intent-check`, `verify`, `propertize`, `oracle`.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/cli.py tests/test_cli_population.py && git commit -m "feat: avow population CLI — N-candidate search, verifier picks the winner (--hybrid)"
```

---

## Manual validation (after Task 4, with credentials)

`avow population ~/Coding/avow-demo-full --config <caps>` → builds N candidate solutions against the same suite and reports which the verifier picked (and each candidate's confidence). `--hybrid` runs one attempt first and only escalates if it doesn't go green-and-confident.

## What this deliberately does NOT do (later)

- Parallel candidate execution; a shared global budget across candidates.
- Per-candidate approach/prompt diversity (distinct builder seeds).
- A `Strategy.run(...)` class hierarchy (Population/Hybrid ship as orchestrators reusing `solve()`).
