# Hermit — The Supervisor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** An event-triggered, judges-not-enforces, off-by-default Supervisor that reviews a plateauing run's trajectory and recommends continue/redirect/escalate; the deterministic loop adjudicates.

**Architecture:** A new `hermit/supervisor.py` (`review_trajectory`), an opt-in loop hook that fires once on plateau (redirect-hint or escalate-stop), and a `hermit supervise` CLI. `solve()`'s floor (budget/plateau/stops) is unchanged and remains authoritative.

**Tech Stack:** Python 3.12 · `anthropic` structured outputs · integrates with `hermit.loop`/`hermit.config`/`hermit.cli`.

## Global Constraints

- Python **3.11+** (Hermit-local venv at `/Users/qatadaha/Coding/hermit/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && <cmd>`.
- Model IDs exact, no date suffixes. `supervisor_model` defaults to `claude-opus-4-8`.
- LLM call uses `client.messages.parse(..., output_format=SupervisorVerdict)` → `.parsed_output`, `.usage`; never set `temperature`/`top_p`/`top_k`. Injectable client; tests use fakes.
- **The Supervisor ships DORMANT** (`supervisor_enabled = False`); it must NOT change default loop behavior. Reuses verified interfaces (do NOT modify their contracts): `solve(...)`/`SolveResult`/`AttemptRecord`/`RunLog`/`Budget.charge_tokens`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `review_trajectory` + `SupervisorVerdict`

**Files:**
- Create: `/Users/qatadaha/Coding/hermit/hermit/supervisor.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_supervisor.py`

**Interfaces:**
- Produces: `SupervisorVerdict(BaseModel)` with `assessment: str`, `recommendation: str`, `escalate: bool`; `review_trajectory(goal, history, client, model) -> tuple[SupervisorVerdict | None, int, int]`. `(None, 0, 0)` when `client is None`. `history` items are read for `.iteration`, `.score`, `.is_green`, `.failing`, `.plan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_supervisor.py
from types import SimpleNamespace
from hermit.supervisor import review_trajectory, SupervisorVerdict


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=5, output_tokens=6))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def _rec(iteration, score, is_green, plan, failing):
    return SimpleNamespace(iteration=iteration, score=score, is_green=is_green, plan=plan, failing=failing)


def test_review_trajectory_returns_verdict():
    v = SupervisorVerdict(assessment="stuck on edge cases", recommendation="redirect", escalate=False)
    client = FakeClient(v)
    history = [_rec(1, 0.5, False, "tried X", ["test_a"]), _rec(2, 0.5, False, "tried Y", ["test_a"])]
    verdict, in_tok, out_tok = review_trajectory("build slugify", history, client, "claude-opus-4-8")
    assert verdict is v and in_tok == 5 and out_tok == 6
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is SupervisorVerdict
    content = sent["messages"][0]["content"]
    assert "build slugify" in content and "tried X" in content   # goal + trajectory forwarded


def test_review_trajectory_noop_without_client():
    assert review_trajectory("g", [], None, "m") == (None, 0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_supervisor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermit.supervisor'`.

- [ ] **Step 3: Write `hermit/supervisor.py`**

```python
# hermit/supervisor.py
from __future__ import annotations

from pydantic import BaseModel


class SupervisorVerdict(BaseModel):
    assessment: str
    recommendation: str  # "continue" | "redirect" | "escalate" | "abort"
    escalate: bool


_SUPERVISOR_PROMPT = """\
You are the Supervisor of an autonomous build loop. The Builder has been trying to make a \
frozen test suite pass and is now PLATEAUING (no recent improvement). Read the GOAL and the \
recent attempt trajectory, then judge whether the run is recoverable.

Emit:
- assessment: a concise diagnosis of what's going wrong; if you recommend "redirect", make \
this the concrete guidance the Builder should follow next.
- recommendation: exactly one of "continue" (plateau looks temporary, keep going), \
"redirect" (the Builder is on the wrong track — your assessment is handed to it as \
guidance), "escalate" (a human should look), or "abort" (the goal looks unreachable as stated).
- escalate: true if a human should be pulled in.

GOAL:
{goal}

RECENT ATTEMPTS (oldest first):
{trajectory}
"""


def _format_history(history) -> str:
    lines = []
    for h in history[-8:]:
        failing = ", ".join(list(getattr(h, "failing", []))[:5])
        lines.append(f"iter {h.iteration}: score={h.score:.2f} green={h.is_green} "
                     f"plan={(h.plan or '')[:120]} failing=[{failing}]")
    return "\n".join(lines)


def review_trajectory(goal, history, client, model) -> tuple:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": _SUPERVISOR_PROMPT.format(
            goal=goal, trajectory=_format_history(history))}],
        output_format=SupervisorVerdict,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_supervisor.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/supervisor.py tests/test_supervisor.py && git commit -m "feat: Supervisor review_trajectory — judge a plateauing run and recommend"
```

---

### Task 2: `RunConfig` supervisor settings (dormant)

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/config.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `supervisor_enabled: bool = False`, `supervisor_model: str = "claude-opus-4-8"`, `supervisor_patience: int = 2`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.supervisor_enabled is False        # ships dormant
    assert cfg.supervisor_model == "claude-opus-4-8"
    assert cfg.supervisor_patience == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'supervisor_enabled'`.

- [ ] **Step 3: Edit `hermit/config.py`**

Add after `population_size`:

```python
    supervisor_enabled: bool = False
    supervisor_model: str = "claude-opus-4-8"
    supervisor_patience: int = 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/config.py tests/test_config.py && git commit -m "feat: dormant Supervisor settings on RunConfig"
```

---

### Task 3: Loop hook — event-triggered Supervisor (dormant by default)

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/loop.py`
- Modify: `/Users/qatadaha/Coding/hermit/tests/test_loop.py`

**Interfaces:**
- `solve` gains keyword-only `supervisor_client=None` (after `oracle_client`). Imports `review_trajectory` from `hermit.supervisor`.

**Edits (read `hermit/loop.py` to confirm the exact current lines first):**
1. Import: `from hermit.supervisor import review_trajectory`.
2. Add `supervisor_client=None` to `solve`'s keyword-only params (after `oracle_client=None`).
3. Before the `while True:` loop, initialize: `attempt_history: list = []`, `supervisor_fired = False`, `supervisor_hint = None`.
4. The builder attempt currently reads `outcome = builder.attempt(workspace.solution_dir, goal, best_failures)`. Replace with:
   ```python
   attempt_goal = goal if supervisor_hint is None else f"{goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"
   outcome = builder.attempt(workspace.solution_dir, attempt_goal, best_failures)
   ```
5. The per-iteration record is currently `log.record(AttemptRecord(...))`. Change to capture + append:
   ```python
   rec = AttemptRecord(
       iteration=budget.iterations,
       score=result.score,
       is_green=result.is_green,
       diff_summary=outcome.plan[:200],
       failing=[f.nodeid for f in result.failures],
       plan=outcome.plan,
       cost_usd=outcome.cost_usd,
   )
   log.record(rec)
   attempt_history.append(rec)
   ```
6. Insert the Supervisor hook AFTER the `if result.is_green:` green branch (which returns) and BEFORE the `if rounds_without_improvement >= config.plateau_patience:` plateau check:
   ```python
   if (config.supervisor_enabled and supervisor_client is not None and not supervisor_fired
           and rounds_without_improvement >= config.supervisor_patience):
       supervisor_fired = True
       before = budget.spent_usd
       verdict, s_in, s_out = review_trajectory(goal, attempt_history, supervisor_client, config.supervisor_model)
       budget.charge_tokens(config.supervisor_model, s_in, s_out)
       if verdict is not None:
           log.record(AttemptRecord(
               iteration=budget.iterations, score=best_score, is_green=False,
               diff_summary=f"supervisor: {verdict.recommendation}; {verdict.assessment[:80]}",
               failing=[], plan="supervisor", cost_usd=budget.spent_usd - before))
           if verdict.escalate or verdict.recommendation == "abort":
               reason = "supervisor_escalate"
               break
           if verdict.recommendation == "redirect":
               supervisor_hint = verdict.assessment
   ```
   (The post-loop return already builds `SolveResult(False, best_score, …, reason, …)` from `reason`, so `"supervisor_escalate"` flows through with no new return — confirm by reading the post-loop return.)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop.py`:

```python
class AlwaysWrongBuilder:
    """Never converges: writes a wrong implementation every attempt."""
    def attempt(self, solution_dir, goal, failures):
        from pathlib import Path as _P
        from hermit.builder import BuilderOutcome
        (_P(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a - b\n")
        return BuilderOutcome(plan="still wrong", cost_usd=0.0, raw={})


def _fake_supervisor(recommendation, escalate):
    from types import SimpleNamespace
    from hermit.supervisor import SupervisorVerdict

    class _C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=SupervisorVerdict(assessment="stuck", recommendation=recommendation, escalate=escalate),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_loop_supervisor_escalates(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=5,
                    supervisor_enabled=True, supervisor_patience=1)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0,
              supervisor_client=_fake_supervisor("abort", True))
    assert r.reason == "supervisor_escalate" and r.success is False


def test_loop_supervisor_continue_falls_through_to_plateau(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=3,
                    supervisor_enabled=True, supervisor_patience=1)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0,
              supervisor_client=_fake_supervisor("continue", False))
    assert r.reason == "plateau" and r.success is False   # supervisor advised continue -> normal stop


def test_loop_supervisor_dormant_by_default(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=2)  # supervisor off
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0)
    assert r.reason == "plateau"   # no supervisor_client + disabled -> unchanged behavior
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py::test_loop_supervisor_escalates -q`
Expected: FAIL — `TypeError: solve() got an unexpected keyword argument 'supervisor_client'`.

- [ ] **Step 3: Apply the edits above to `hermit/loop.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_loop.py -q`
Expected: PASS — the three new tests + all existing loop tests (which pass no `supervisor_client` and leave it disabled → the hook never fires → identical behavior).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/loop.py tests/test_loop.py && git commit -m "feat: event-triggered Supervisor hook in the loop (dormant by default; redirect/escalate)"
```

---

### Task 4: `hermit supervise` CLI

**Files:**
- Modify: `/Users/qatadaha/Coding/hermit/hermit/cli.py`
- Test: `/Users/qatadaha/Coding/hermit/tests/test_cli_supervise.py`

**Interfaces:**
- New subcommand: `hermit supervise <run_jsonl> <goal_file> [--config]`. Reads the recorded `run.jsonl` into a trajectory, runs `review_trajectory`, prints the verdict. The existing subcommands are unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_supervise.py
import json
from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.supervisor import SupervisorVerdict


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        return SimpleNamespace(
            parsed_output=SupervisorVerdict(assessment="goal underspecified", recommendation="escalate", escalate=True),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_supervise_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    run = tmp_path / "run.jsonl"
    run.write_text(
        json.dumps({"iteration": 1, "score": 0.0, "is_green": False, "plan": "tried subtract", "failing": ["test_add"]}) + "\n"
        + json.dumps({"iteration": 2, "score": 0.0, "is_green": False, "plan": "tried again", "failing": ["test_add"]}) + "\n")

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["supervise", str(run), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "escalate" in out.lower()
    assert "goal underspecified" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_supervise.py -q`
Expected: FAIL — argparse `invalid choice: 'supervise'`.

- [ ] **Step 3: Edit `hermit/cli.py`**

Add the subparser inside `main` (after the `population` subparser, before `parse_args`):

```python
    sup_p = sub.add_parser("supervise",
                           help="review a recorded run's trajectory and print the Supervisor's verdict")
    sup_p.add_argument("run_jsonl")
    sup_p.add_argument("goal_file")
    sup_p.add_argument("--config", default=None)
```

Add the dispatch next to the others (after `parse_args`):

```python
    if args.command == "supervise":
        return _cmd_supervise(args)
```

Add the handler at module level:

```python
def _cmd_supervise(args) -> int:
    import json
    from types import SimpleNamespace
    import anthropic
    from hermit.supervisor import review_trajectory

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    history = []
    for line in Path(args.run_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        history.append(SimpleNamespace(
            iteration=d.get("iteration", 0), score=d.get("score", 0.0),
            is_green=d.get("is_green", False), plan=d.get("plan", ""),
            failing=d.get("failing", [])))

    verdict, _in, _out = review_trajectory(goal, history, anthropic.Anthropic(), config.supervisor_model)
    print(f"supervisor recommendation: {verdict.recommendation} (escalate={verdict.escalate})")
    print(f"assessment: {verdict.assessment}")
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest tests/test_cli_supervise.py tests/test_cli.py -q`
Expected: PASS (supervise CLI + the unchanged subcommands).

- [ ] **Step 5: Run the whole suite + smoke the entry point**

Run: `cd /Users/qatadaha/Coding/hermit && source .venv/bin/activate && python -m pytest -q && hermit --help`
Expected: all tests PASS, 0 warnings; `hermit --help` lists `solve`, `improve`, `harden`, `population`, `mutate`, `intent-check`, `verify`, `propertize`, `oracle`, `supervise`.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/hermit && git add hermit/cli.py tests/test_cli_supervise.py && git commit -m "feat: hermit supervise CLI — review a recorded run's trajectory"
```

---

## Manual validation (after Task 4)

`hermit supervise ~/Coding/hermit-demo-full/.hermit/run.jsonl ~/Coding/hermit-demo-full/goal.md` → prints the Supervisor's read of that run. To see it in-loop, run `hermit solve` on a hard goal with a `hermit.yaml` setting `supervisor_enabled: true` (then it fires once on plateau and may redirect or escalate).

## What this deliberately does NOT do (later)

- Repeated firings / a Supervisor-triggered strategy switch (e.g. escalate to `population_solve`).
- A different-family overseer model.
- Overriding the budget/plateau/stop floor (by design it cannot).
