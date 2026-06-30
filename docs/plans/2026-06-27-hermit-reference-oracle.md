# Hermit — Reference-Oracle Differential Testing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Generate an independent reference implementation of the goal and differential-test it against the Builder's solution over thousands of fuzzed inputs; disagreement becomes a confidence signal + a floor.

**Architecture:** A new `hermit/oracle.py` (LLM emits a reference + a Hypothesis diff test; `run_oracle_check` runs it in an ephemeral dir → agreement), wired into the loop's post-green block (a new `oracle` confidence signal + an `oracle_floor`). A `hermit oracle` CLI. Mirrors the mutation signal's shape.

**Tech Stack:** Python 3.12 · `anthropic` structured outputs · `hypothesis` · `pytest-json-report` · reuses `hermit.scoring`/`hermit.loop`/`hermit.config`/`hermit.confidence`.

## Global Constraints

- Python **3.11+** (Hermit-local venv at `/Users/qatadaha/Coding/hermit/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && <cmd>`.
- Model IDs exact, no date suffixes. `oracle_model` defaults to `claude-opus-4-8`.
- LLM call uses `client.messages.parse(..., output_format=_OraclePair)` → `.parsed_output`, `.usage`; never set `temperature`/`top_p`/`top_k`. Injectable client; unit tests use fakes for generation; the *run* path is tested offline with an injected pair (real pytest subprocess, no LLM).
- Reuses verified interfaces (do NOT modify): `parse_report(data) -> TestResult(passed, failed, errors, total, failures: list[FailureInfo(nodeid, message)])` from `hermit.scoring`; `aggregate_confidence(signals, weights)` already filters present (non-None, weight>0) signals and renormalizes; `RunConfig`; `Budget.charge_tokens`; `RunLog.record(AttemptRecord(...))`; `solve(...)`/`SolveResult` in `hermit.loop`.
- The differential test imports the solution as `from lib import …` and the reference as `from ref import …`; the oracle stages both in an ephemeral dir (never touches the frozen suite or the Runner).
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `generate_oracle` (the reference + diff-test pair)

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/oracle.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_oracle_gen.py`

**Interfaces:**
- Produces: `_OraclePair(BaseModel)` with `reference_code: str`, `diff_test_code: str`; `generate_oracle(goal: str, client, model: str) -> tuple[_OraclePair | None, int, int]`. `(None, 0, 0)` when `client is None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_gen.py
from types import SimpleNamespace
from hermit.oracle import generate_oracle, _OraclePair


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=9, output_tokens=13))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_generate_oracle_returns_pair_and_tokens():
    payload = _OraclePair(reference_code="def add(a, b):\n    return a + b\n",
                          diff_test_code="# diff test\n")
    client = FakeClient(payload)
    pair, in_tok, out_tok = generate_oracle("build add(a, b)", client, "claude-opus-4-8")
    assert pair is payload and in_tok == 9 and out_tok == 13
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _OraclePair
    content = sent["messages"][0]["content"]
    assert "build add(a, b)" in content
    assert "from lib import" in content and "from ref import" in content  # the prompt pins the imports


def test_generate_oracle_noop_without_client():
    assert generate_oracle("g", None, "m") == (None, 0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_oracle_gen.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.oracle'`.

- [ ] **Step 3: Write `hermit/oracle.py`**

```python
# hermit/oracle.py
from __future__ import annotations

from pydantic import BaseModel


class _OraclePair(BaseModel):
    reference_code: str
    diff_test_code: str


_ORACLE_PROMPT = """\
You are building a DIFFERENTIAL ORACLE for a piece of software. Given the GOAL, produce \
two things:

1. reference_code: the SIMPLEST, most OBVIOUSLY-CORRECT implementation of the goal — \
prioritize clarity and correctness over speed or elegance (a naive, slow, plainly-right \
version). It must expose the SAME public function(s) as the goal implies.

2. diff_test_code: a pytest module using the Hypothesis library that imports the clever \
implementation as `from lib import <name> as _sol` and your reference as \
`from ref import <name> as _ref`, then uses `@given(...)` from `hypothesis` with \
strategies matching the goal's input types to assert `_sol(x) == _ref(x)` for all inputs. \
One `@given` test per public function. Do not import anything else from lib/ref.

The two implementations are written independently so that a disagreement reveals a bug in \
one of them. Make the reference genuinely independent (a different, simpler approach).

GOAL:
{goal}
"""


def generate_oracle(goal: str, client, model: str) -> tuple[_OraclePair | None, int, int]:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": _ORACLE_PROMPT.format(goal=goal)}],
        output_format=_OraclePair,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_oracle_gen.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/oracle.py tests/test_oracle_gen.py && git commit -m "feat: generate a reference impl + Hypothesis differential test for a goal"
```

---

### Task 2: `run_oracle_check` (differential run → agreement)

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/oracle.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_oracle_run.py`

**Interfaces:**
- Produces: `OracleResult(agreement: float | None, baseline_ok: bool, counterexample: str, checked: bool, input_tokens: int, output_tokens: int)`; `run_oracle_check(solution_dir, goal, client, model, test_command, timeout=120) -> OracleResult`. `agreement=1.0` (diff test passes), `0.0` (a counterexample found), `None` (inconclusive: no pair, error/collection failure, timeout, no report).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_run.py
from pathlib import Path
from types import SimpleNamespace
from hermit.oracle import run_oracle_check, _OraclePair

_DIFF = ("from lib import add as _sol\n"
         "from ref import add as _ref\n"
         "from hypothesis import given, strategies as st\n"
         "@given(st.integers(), st.integers())\n"
         "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


def _client(reference_code):
    pair = _OraclePair(reference_code=reference_code, diff_test_code=_DIFF)

    class C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(parsed_output=pair,
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return C()


def _solution(tmp_path):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path


CMD = ["python", "-m", "pytest", "-q"]


def test_oracle_agrees(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a + b\n"),
                         "m", CMD, timeout=120)
    assert r.agreement == 1.0 and r.baseline_ok is True and r.counterexample == ""


def test_oracle_disagrees(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a * b\n"),
                         "m", CMD, timeout=120)
    assert r.agreement == 0.0 and r.baseline_ok is True and r.counterexample != ""


def test_oracle_inconclusive_on_broken_reference(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a +\n"),  # syntax error
                         "m", CMD, timeout=120)
    assert r.agreement is None and r.baseline_ok is False


def test_oracle_inconclusive_without_client(tmp_path):
    r = run_oracle_check(_solution(tmp_path), "add", None, "m", CMD, timeout=120)
    assert r.agreement is None and r.checked is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_oracle_run.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_oracle_check'`.

- [ ] **Step 3: Append to `hermit/oracle.py`**

Add the imports at the top (with the existing ones):

```python
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermit.scoring import parse_report
```

Append:

```python
@dataclass
class OracleResult:
    agreement: float | None
    baseline_ok: bool
    counterexample: str
    checked: bool
    input_tokens: int
    output_tokens: int


def _inconclusive(in_tok, out_tok, *, counterexample="") -> "OracleResult":
    return OracleResult(agreement=None, baseline_ok=False, counterexample=counterexample,
                        checked=False, input_tokens=in_tok, output_tokens=out_tok)


def run_oracle_check(solution_dir, goal, client, model, test_command, timeout: int = 120) -> OracleResult:
    pair, in_tok, out_tok = generate_oracle(goal, client, model)
    if pair is None:
        return _inconclusive(in_tok, out_tok)

    with tempfile.TemporaryDirectory(prefix="hermit-oracle-") as tmp:
        work = Path(tmp)
        for p in Path(solution_dir).glob("*.py"):
            if p.name.startswith("test_") or p.name == "conftest.py":
                continue
            shutil.copy2(p, work / p.name)
        (work / "ref.py").write_text(pair.reference_code, encoding="utf-8")
        (work / "test_oracle_diff.py").write_text(pair.diff_test_code, encoding="utf-8")
        report = work / "report.json"

        try:
            subprocess.run(
                [*test_command, "--json-report", f"--json-report-file={report}", "test_oracle_diff.py"],
                cwd=work, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _inconclusive(in_tok, out_tok, counterexample="timeout")

        if not report.exists():
            return _inconclusive(in_tok, out_tok)
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _inconclusive(in_tok, out_tok)

        result = parse_report(data)
        if result.errors > 0 or result.total == 0:
            return _inconclusive(in_tok, out_tok)  # broken reference / collection failure
        if result.failed == 0 and result.passed > 0:
            return OracleResult(1.0, True, "", True, in_tok, out_tok)
        cx = result.failures[0].message[:500] if result.failures else ""
        return OracleResult(0.0, True, cx, True, in_tok, out_tok)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_oracle_run.py -q`
Expected: PASS (4 passed). (These run real pytest subprocesses with Hypothesis — the venv must be active.)

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/oracle.py tests/test_oracle_run.py && git commit -m "feat: run_oracle_check — differential-test a solution against an independent reference"
```

---

### Task 3: `RunConfig` oracle settings + `oracle` weight

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/config.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `oracle_enabled: bool = True`, `oracle_model: str = "claude-opus-4-8"`, `oracle_floor: float = 1.0`. The `confidence_weights` default gains `"oracle": 1.0`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.oracle_enabled is True
    assert cfg.oracle_model == "claude-opus-4-8"
    assert cfg.oracle_floor == 1.0
    assert cfg.confidence_weights["oracle"] == 1.0
```

Also UPDATE the existing exact-dict assertion on `confidence_weights` (if present in this test) to include `"oracle": 1.0` — search for `confidence_weights ==` and add the key so the dict matches.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'oracle_enabled'` (or a confidence_weights mismatch).

- [ ] **Step 3: Edit `hermit/config.py`**

Add the `"oracle": 1.0` entry to the `confidence_weights` default_factory dict (alongside `holdout`/`mutation`/`intent`). Add the three fields after the existing expand-phase fields (`ideas_n`):

```python
    oracle_enabled: bool = True
    oracle_model: str = "claude-opus-4-8"
    oracle_floor: float = 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/config.py tests/test_config.py && git commit -m "feat: reference-oracle settings + oracle confidence weight on RunConfig"
```

---

### Task 4: Loop — oracle signal + floor (post-green)

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/loop.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_loop.py`

**Interfaces:**
- `solve` gains a keyword-only `oracle_client=None` (after `property_client`). Imports `run_oracle_check` from `hermit.oracle`. `SolveResult` gains `oracle_agreement: float | None = None` (after `confidence_breakdown`).
- In the green branch: after the mutation block and before the `aggregate_confidence` call, when `config.oracle_enabled and oracle_client is not None`, run `run_oracle_check(best_dir, goal, oracle_client, config.oracle_model, config.test_command, config.test_timeout_seconds)`, charge `budget.charge_tokens(config.oracle_model, ...)`, set `oracle_agreement = orc.agreement`, and log an AttemptRecord. Add `"oracle": oracle_agreement` to the confidence signals dict. Extend `floor_breached` with `or (oracle_agreement is not None and oracle_agreement < config.oracle_floor)`. Pass `oracle_agreement=oracle_agreement` to all three SolveResult returns.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop.py`:

```python
def test_loop_oracle_disagreement_floor(tmp_path):
    from types import SimpleNamespace
    from hermit.oracle import _OraclePair

    class DisagreeingOracle:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            # reference DISAGREES with the converged solution (add = a + b): reference uses a - b
            pair = _OraclePair(
                reference_code="def add(a, b):\n    return a - b\n",
                diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                "from hypothesis import given, strategies as st\n"
                                "@given(st.integers(), st.integers())\n"
                                "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
            return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              oracle_client=DisagreeingOracle())
    # the solution converges green, but the independent reference disagrees (a+b vs a-b) ->
    # oracle agreement 0.0 < floor 1.0 -> forced low_confidence
    assert r.reason == "low_confidence" and r.success is False
    assert r.oracle_agreement == 0.0


def test_loop_no_oracle_client_unaffected(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True and r.oracle_agreement is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py::test_loop_oracle_disagreement_floor -q`
Expected: FAIL — `TypeError: solve() got an unexpected keyword argument 'oracle_client'`.

- [ ] **Step 3: Edit `hermit/loop.py`**

Add the import near the top:

```python
from hermit.oracle import run_oracle_check
```

Add `oracle_client=None` to `solve`'s keyword-only params (after `property_client=None`).

Add `oracle_agreement: float | None = None` to the `SolveResult` dataclass (after `confidence_breakdown`).

In the green branch, after the mutation block (the `if config.mutation_enabled:` block ending with `mscore, surv = mr.score, mr.survived`) and BEFORE the `conf = aggregate_confidence(...)` call, insert:

```python
            oracle_agreement: float | None = None
            if config.oracle_enabled and oracle_client is not None:
                before = budget.spent_usd
                orc = run_oracle_check(best_dir, goal, oracle_client, config.oracle_model,
                                       config.test_command, config.test_timeout_seconds)
                budget.charge_tokens(config.oracle_model, orc.input_tokens, orc.output_tokens)
                oracle_agreement = orc.agreement
                log.record(AttemptRecord(
                    iteration=budget.iterations, score=result.score, is_green=True,
                    diff_summary=f"oracle agreement {orc.agreement}; {orc.counterexample[:80]}",
                    failing=[], plan="oracle", cost_usd=budget.spent_usd - before,
                ))
```

Change the `aggregate_confidence` signals dict to include the oracle:

```python
            conf = aggregate_confidence(
                {"holdout": holdout_score, "mutation": mscore, "intent": intent_score,
                 "oracle": oracle_agreement},
                config.confidence_weights,
            )
```

Extend `floor_breached`:

```python
            floor_breached = config.confidence_gating and (
                holdout_score < config.holdout_floor
                or (panel_agreement is not None and panel_agreement < config.panel_agreement_floor)
                or (oracle_agreement is not None and oracle_agreement < config.oracle_floor)
            )
```

Add `oracle_agreement=oracle_agreement` to ALL THREE `SolveResult(...)` returns in the green branch (the `"green"`, `"green_human_override"`, and `"low_confidence"` returns).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py -q`
Expected: PASS — the two new tests + all existing loop tests (which pass no `oracle_client` → `oracle_agreement` None → filtered from confidence, no floor → identical behavior).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS (all prior + the oracle tests), 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/loop.py tests/test_loop.py && git commit -m "feat: reference-oracle as a post-green confidence signal + agreement floor"
```

---

### Task 5: `hermit oracle` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/cli.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_cli_oracle.py`

**Interfaces:**
- New subcommand: `hermit oracle <solution_dir> <goal_file> [--config hermit.yaml]`. Builds `anthropic.Anthropic()`, runs `run_oracle_check`, prints `oracle agreement: <x>` and any counterexample. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_oracle.py
from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.oracle import _OraclePair


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        pair = _OraclePair(
            reference_code="def add(a, b):\n    return a + b\n",
            diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                            "from hypothesis import given, strategies as st\n"
                            "@given(st.integers(), st.integers())\n"
                            "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
        return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_oracle_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["oracle", str(tmp_path), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "oracle agreement: 1.0" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_oracle.py -q`
Expected: FAIL — argparse `invalid choice: 'oracle'`.

- [ ] **Step 3: Edit `hermit/cli.py`**

Add the subparser inside `main` (after the `improve` subparser, before `parse_args`):

```python
    oracle_p = sub.add_parser("oracle",
                              help="differential-test a solution against an independent reference impl")
    oracle_p.add_argument("solution_dir")
    oracle_p.add_argument("goal_file")
    oracle_p.add_argument("--config", default=None)
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "oracle":
        return _cmd_oracle(args)
```

Add the handler at module level:

```python
def _cmd_oracle(args) -> int:
    import anthropic
    from hermit.oracle import run_oracle_check

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    res = run_oracle_check(Path(args.solution_dir), goal, anthropic.Anthropic(),
                           config.oracle_model, config.test_command, config.test_timeout_seconds)
    print(f"oracle agreement: {res.agreement}")
    if res.counterexample:
        print(f"counterexample:\n{res.counterexample}")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_oracle.py tests/test_cli.py -q`
Expected: PASS (oracle CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q && hermit --help`
Expected: all tests PASS, 0 warnings; `hermit --help` lists `solve`, `improve`, `mutate`, `intent-check`, `verify`, `propertize`, `oracle`.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/cli.py tests/test_cli_oracle.py && git commit -m "feat: hermit oracle CLI — differential-test any solution against a generated reference"
```

---

## Manual validation (after Task 5, with credentials)

`hermit oracle ~/Coding/hermit-demo-full/.hermit/best ~/Coding/hermit-demo-full/goal.md` → generates an independent reference slugify and fuzzes the built solution against it; prints `oracle agreement: 1.0` (or a counterexample if they diverge).

## What this deliberately does NOT do (later)

- Fractional agreement over N sampled inputs (Hypothesis stops at the first counterexample → binary {0,1}).
- Using the reference as a converge target (injecting `ref.py` into the grading env so the Builder fixes disagreements mid-build).
- Multiple references / cross-reference voting.
