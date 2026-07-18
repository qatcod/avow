# Lineage Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In `survive`'s fight-back loop, the rebuilt solution inherits an accumulating, abstract memory of why its predecessors were killed, passed to the Builder as anti-guidance so it avoids the failure *class* (not just the frozen instance).

**Architecture:** `solve()` gains an optional `builder_guidance` string that the loop folds into each attempt's goal (alongside the existing Supervisor hint). `survive` keeps an ephemeral in-memory ledger of the Coroner's per-kill `AttackPattern`s (already computed for the Graveyard) and formats them — category + description ONLY — into the guidance it hands the rebuild. Nothing is persisted; the Graveyard already handles cross-run memory.

**Tech Stack:** Python 3.11+, pytest.

## Global Constraints

- Abstract-only anti-cheat: the guidance carries a pattern's `category` and `description` ONLY. It must NEVER contain `counterexample.reference_code`, the differential test text, the expected output, or the literal falsifying input. The Builder never sees tests or references.
- Ephemeral: the ledger is an in-memory list in one `survive` call. No new persistent store; no change to the Graveyard, Coroner, or the calibration proof (C).
- Guidance, not a guarantee: naming/comments say "guidance"/"lessons", never "enforced"/"prevents". The frozen regression test remains the mechanical guarantee.
- Lineage accrues only when a Coroner client is present (same condition as Graveyard recording); with no Coroner, behavior is byte-identical to today.
- Same review-before-push bar as A/B/C and relevance: full-suite gate + adversarial whole-branch review, fix, push only on greenlight.

## File Structure

- `avow/loop.py` (modify) — add `builder_guidance: str = ""` to `solve()`; fold it into the attempt goal at the existing seam.
- `avow/survive.py` (modify) — accumulate `deaths: list[AttackPattern]`; add `_format_lineage`; pass `builder_guidance` on the rebuild `solve` call.
- Tests: append to `tests/test_loop.py` and `tests/test_survive.py`.

---

### Task 1: `solve(builder_guidance=...)` injects into the attempt goal

**Files:**
- Modify: `avow/loop.py`
- Test: `tests/test_loop.py` (append)

**Interfaces:**
- Consumes: existing `solve(goal_dir, config, examiner, builder, *, ...)`, `StubExaminer` (in test_loop.py).
- Produces: `solve(..., builder_guidance: str = "")` — when non-empty, `builder_guidance` is appended to every attempt's goal as a labeled block, coexisting with the Supervisor hint.

- [ ] **Step 1: Write the failing tests (append to `tests/test_loop.py`)**

```python
class _CapturingBuilder:
    """Goes green in one attempt; records every goal string it was handed."""
    def __init__(self):
        self.goals = []

    def attempt(self, solution_dir, goal, failures):
        self.goals.append(goal)
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        from avow.builder import BuilderOutcome
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_solve_injects_builder_guidance_into_attempt_goal(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    b = _CapturingBuilder()
    solve(_goal(tmp_path), cfg, StubExaminer(), b, now=lambda: 0.0, builder_guidance="LINEAGE-LESSON-XYZ")
    assert b.goals and all("LINEAGE-LESSON-XYZ" in g for g in b.goals)


def test_solve_without_guidance_leaves_goal_unchanged(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    b = _CapturingBuilder()
    solve(_goal(tmp_path), cfg, StubExaminer(), b, now=lambda: 0.0)
    assert b.goals and all(g.strip() == "Build add(a, b) returning a + b." for g in b.goals)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_loop.py::test_solve_injects_builder_guidance_into_attempt_goal -q`
Expected: FAIL with `TypeError: solve() got an unexpected keyword argument 'builder_guidance'`.

- [ ] **Step 3: Add the param + seam in `avow/loop.py`**

Add the keyword param to the `solve(` signature (next to `write_tests`):

```python
    write_tests: bool = True,
    builder_guidance: str = "",
```

Just before the `while True:` loop (where `supervisor_hint = None` is initialized), compute the static base goal once:

```python
    supervisor_hint = None
    base_goal = goal if not builder_guidance else f"{goal}\n\n{builder_guidance}"
```

Change the attempt-goal line inside the loop from:

```python
        attempt_goal = goal if supervisor_hint is None else f"{goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"
```

to:

```python
        attempt_goal = base_goal if supervisor_hint is None else f"{base_goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_loop.py -q`
Expected: PASS (existing loop tests + the 2 new).

- [ ] **Step 5: Commit**

```bash
git add avow/loop.py tests/test_loop.py
git commit -m "feat: solve(builder_guidance=...) folds caller guidance into the Builder's attempt goal (coexists with supervisor hint)"
```

---

### Task 2: `survive` accumulates death-lessons and hands them to the heir

**Files:**
- Modify: `avow/survive.py`
- Test: `tests/test_survive.py` (append)

**Interfaces:**
- Consumes: `solve(..., builder_guidance=...)` (Task 1); the Coroner `pat` (`AttackPattern`) already computed per kill; `AttackPattern.category`/`.description`.
- Produces: `_format_lineage(deaths: list) -> str`; `survive` passes `builder_guidance` on the rebuild `solve` call.

- [ ] **Step 1: Write the failing tests (append to `tests/test_survive.py`)**

```python
def _spy_solve(monkeypatch):
    import avow.survive as s
    real = s.solve
    seen = []

    def spy(*a, **k):
        seen.append(k.get("builder_guidance", ""))
        return real(*a, **k)

    monkeypatch.setattr(s, "solve", spy)
    return seen


def test_survive_rebuild_inherits_abstract_death_lessons(tmp_path, monkeypatch):
    import avow.survive as s
    gy = tmp_path / "gy.jsonl"
    seen = _spy_solve(monkeypatch)
    kills = {"n": 0}

    def fake_g(*a, **k):
        kills["n"] += 1
        return GauntletResult(False, _CX, 4, 4, 0, 0) if kills["n"] == 1 else GauntletResult(True, None, 4, 4, 0, 0)

    monkeypatch.setattr(s, "run_gauntlet", fake_g)
    r = survive(_goal(tmp_path),
                RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=3, graveyard_path=str(gy)),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), coroner_client=_FakeCoroner(),
                now=lambda: 0.0)
    assert r.status == "verified_survivor"
    assert seen[0] == ""                                   # initial converge: no prior deaths
    rebuild = seen[1]                                      # the heir's rebuild
    assert "numeric-add" in rebuild and "probe add overflow" in rebuild   # abstract class + description
    # anti-cheat: the reference implementation / counterexample is NEVER handed to the Builder
    assert "def add" not in rebuild and _CX.reference_code not in rebuild


def test_survive_no_coroner_gives_no_lineage_guidance(tmp_path, monkeypatch):
    import avow.survive as s
    gy = tmp_path / "gy.jsonl"
    seen = _spy_solve(monkeypatch)
    kills = {"n": 0}

    def fake_g(*a, **k):
        kills["n"] += 1
        return GauntletResult(False, _CX, 4, 4, 0, 0) if kills["n"] == 1 else GauntletResult(True, None, 4, 4, 0, 0)

    monkeypatch.setattr(s, "run_gauntlet", fake_g)
    survive(_goal(tmp_path),
            RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=3, graveyard_path=str(gy)),
            StubExaminer(), GoodBuilder(), gauntlet_client=object(), coroner_client=None, now=lambda: 0.0)
    assert all(g == "" for g in seen)                     # no Coroner -> no lineage, byte-identical to before
```

Note: `_FakeCoroner` (already in `tests/test_survive.py`) yields `category="numeric-add"`, `description="probe add overflow on large operands"`. `_CX.reference_code` is `"def add(a, b):\n    return a + b\n"`.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_survive.py::test_survive_rebuild_inherits_abstract_death_lessons -q`
Expected: FAIL — `survive` does not yet pass `builder_guidance`, so `seen[1]` is `""` and the `"numeric-add"` assertion fails.

- [ ] **Step 3: Add the ledger + formatter + rebuild wiring in `avow/survive.py`**

Add the formatter near the top of the module (after the imports, before `survive`):

```python
def _format_lineage(deaths: list) -> str:
    """Abstract-only anti-guidance for the Builder: the failure CLASS of each prior killed attempt,
    never the reference code / test / expected output. Empty when there are no prior deaths."""
    if not deaths:
        return ""
    lines = [f"LESSONS FROM {len(deaths)} PRIOR ATTEMPT(S) ON THIS GOAL THAT WERE KILLED "
             "(do not reintroduce these failure classes):"]
    for d in deaths:
        lines.append(f"  - [{d.category}] {d.description}")
    return "\n".join(lines)
```

In `survive`, initialize the ledger just before the fight-back loop (next to `last_cx = None`):

```python
    last_cx = None
    deaths: list = []   # ephemeral per-run lineage: the abstract cause-of-death of each killed ancestor
```

In the Coroner block, append the pattern to the ledger wherever it is recorded to the Graveyard:

```python
                if pat is not None:
                    record(pat, graveyard_path)
                    deaths.append(pat)
```

On the rebuild `solve(...)` call (the `write_tests=False` one), pass the formatted lineage:

```python
        result = solve(goal_dir, config, examiner, builder, now=now, write_tests=False,
                       builder_guidance=_format_lineage(deaths),
                       mutation_client=mutation_client, intent_client=intent_client,
                       property_client=property_client, oracle_client=oracle_client)
```

(Leave the initial `write_tests=True` converge call unchanged — it has no prior deaths.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_survive.py -q`
Expected: PASS (existing survive tests + the 2 new). The heir's rebuild carries the abstract class; the no-Coroner path carries nothing.

- [ ] **Step 5: Commit**

```bash
git add avow/survive.py tests/test_survive.py
git commit -m "feat: lineage memory — the heir inherits abstract death-lessons as Builder anti-guidance"
```

---

## Self-review checklist (run after Task 2)

- Full-suite gate: `python -m pytest -q` → all green, 0 warnings.
- `git diff --stat` shows only `loop.py`, `survive.py`, and the two test files (Graveyard / Coroner / calibration_gauntlet.py untouched).
- Grep the diff: the guidance path references only `pat.category` / `pat.description` (or `d.category` / `d.description`), never `reference_code` / `diff_test_code`.

## Out of scope (backlog)

- Persisting lineage across runs (the Graveyard already does).
- Including the concrete falsifying input in the lesson (abstract-only chosen deliberately).
- Measuring lineage memory's marginal convergence benefit (a future calibration/benchmark extension).
