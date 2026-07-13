# Avow — Parallel Candidate Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run Population's pool candidates concurrently (thread pool over the isolated per-candidate `solve()` calls), preserving deterministic index-ordered selection, capped by `max_parallel_candidates`.

**Architecture:** Rewrite `_run_candidate_pool` to submit the pool candidates to a `ThreadPoolExecutor` and gather results in candidate-index order. `solve()`/`select_best`/`population_solve`/`hybrid_solve` are unchanged.

**Tech Stack:** Python 3.12 · `concurrent.futures` (threads — `solve()` is subprocess-bound) · `avow.population` · `avow.config`.

## Global Constraints

- Python **3.11+** (Avow-local venv at `/Users/qatadaha/Coding/avow/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && <cmd>`.
- **Determinism is load-bearing:** results MUST be appended to `candidates` in candidate-INDEX order (not completion order), so `select_best` (ties → lowest index) returns the identical winner the sequential path does. Parallelism changes speed only, never outcome.
- Candidates are isolated (each writes only into its own `candidates/{i}/` dir); a worker exception must NOT abort the others.
- Reuses verified interfaces (do NOT modify): `solve(...)`, `select_best`, `_stage_candidate`, `_snapshot`, `Candidate`, `PopulationResult`. Candidate 0 is NOT parallelized (it writes the shared suite first, in `population_solve`/`hybrid_solve`).
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `RunConfig.max_parallel_candidates`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/config.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `max_parallel_candidates: int = 4`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.max_parallel_candidates == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'max_parallel_candidates'`.

- [ ] **Step 3: Edit `avow/config.py`**

Add after `population_size`:

```python
    max_parallel_candidates: int = 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: max_parallel_candidates setting on RunConfig"
```

---

### Task 2: Parallelize `_run_candidate_pool`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/population.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_population.py`

**Interfaces:**
- Produces: `_solve_candidate(goal_dir, i, config, examiner, builder, clients, now) -> Candidate` (stage + solve one pool candidate). `_run_candidate_pool` runs the pool candidates via `concurrent.futures.ThreadPoolExecutor`, collecting results in index order, tolerating a worker exception.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_population.py`:

```python
def test_population_parallel_outcome_matches(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=3, max_parallel_candidates=4)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True
    assert len(r.candidates) == 3
    assert [c.index for c in r.candidates] == [0, 1, 2]   # index order preserved (deterministic)
    assert (tmp_path / ".avow" / "best" / "lib.py").exists()
    assert (tmp_path / ".avow" / "candidates" / "1" / "tests_frozen").exists()
    assert (tmp_path / ".avow" / "candidates" / "2" / "tests_frozen").exists()


def test_population_sequential_when_max_parallel_one(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=2, max_parallel_candidates=1)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 2 and [c.index for c in r.candidates] == [0, 1]


def test_pool_tolerates_a_failing_candidate(tmp_path):
    from types import SimpleNamespace
    from avow.population import _run_candidate_pool, Candidate

    (tmp_path / "goal.md").write_text("Build add(a, b).")
    (tmp_path / "tests_frozen").mkdir()
    (tmp_path / "tests_frozen" / "test_add.py").write_text(
        "from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    (tmp_path / "tests_holdout").mkdir()
    best0 = tmp_path / ".avow" / "best"
    best0.mkdir(parents=True)
    (best0 / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    cand0 = Candidate(0, SimpleNamespace(success=True, confidence=1.0, best_score=1.0,
                                         reason="green", confidence_breakdown={}), best0)

    class RaisingBuilder:
        def __init__(self, *a, **k):
            pass

        def attempt(self, *a, **k):
            raise RuntimeError("boom")

    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0, population_size=2, max_parallel_candidates=2)
    clients = dict(mutation_client=None, intent_client=None, property_client=None, oracle_client=None)
    r = _run_candidate_pool(tmp_path, cfg, StubExaminer(), RaisingBuilder(), [cand0], clients, lambda: 0.0)
    # candidate 1 crashed but did not abort the pool; candidate 0 (green) wins.
    assert r.winner_index == 0 and r.success is True and len(r.candidates) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population.py::test_pool_tolerates_a_failing_candidate -q`
Expected: FAIL — `ImportError: cannot import name '_solve_candidate'` (or the failing-candidate path crashes the pool).

- [ ] **Step 3: Edit `avow/population.py`**

Add the import at the top (with the existing ones):

```python
import concurrent.futures
from types import SimpleNamespace
```

Add the per-candidate worker (near `_run_candidate_pool`):

```python
def _solve_candidate(goal_dir, i, config, examiner, builder, clients, now) -> Candidate:
    cand_dir = Path(goal_dir) / ".avow" / "candidates" / str(i)
    _stage_candidate(goal_dir, cand_dir)
    ri = solve(cand_dir, config, examiner, builder, now=now, write_tests=False, **clients)
    return Candidate(i, ri, cand_dir / ".avow" / "best")
```

Replace the body of `_run_candidate_pool` (keep the signature) with the parallel version:

```python
def _run_candidate_pool(goal_dir, config, examiner, builder, candidates, clients, now) -> PopulationResult:
    goal_dir = Path(goal_dir)
    indices = list(range(len(candidates), max(1, config.population_size)))
    if indices:
        max_workers = max(1, min(config.max_parallel_candidates, len(indices)))
        by_index: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_solve_candidate, goal_dir, i, config, examiner, builder, clients, now): i
                for i in indices
            }
            for fut in concurrent.futures.as_completed(futures):
                i = futures[fut]
                try:
                    by_index[i] = fut.result()
                except Exception as exc:  # one candidate crashing must not abort the others
                    by_index[i] = Candidate(
                        i,
                        SimpleNamespace(success=False, confidence=None, best_score=-1.0,
                                        reason="candidate_error", confidence_breakdown={}),
                        None,
                    )
        for i in indices:                       # append in INDEX order -> deterministic selection
            candidates.append(by_index[i])

    results = [c.result for c in candidates]
    winner = select_best(results)
    dest = goal_dir / ".avow" / "best"
    if winner != 0:
        win_dir = candidates[winner].solution_dir
        if win_dir is not None and Path(win_dir).exists():
            _snapshot(win_dir, dest)
        else:
            winner = 0                          # winner has no promoted artifact -> best/ holds candidate 0
    return PopulationResult(success=results[winner].success, best=results[winner],
                            candidates=candidates, winner_index=winner)
```

(Note the added `win_dir is not None` guard — a failed candidate's `solution_dir` is `None`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_population.py -q`
Expected: PASS — the 3 new tests + the existing population tests (which now run through the parallel pool with identical, index-ordered outcomes).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/population.py tests/test_population.py && git commit -m "feat: run Population candidates in parallel (thread pool, deterministic index-ordered selection)"
```

---

## Manual validation (after Task 2, with credentials)

`avow population <goal-dir>` on a real goal with `population_size: 3` now runs the 3 candidates concurrently — wall-time ≈ the slowest single candidate rather than the sum. Set `max_parallel_candidates: 1` in `avow.yaml` to fall back to sequential on a constrained machine or tight rate limit.

## What this deliberately does NOT do (later)

- Parallelize candidate 0 (it must write the shared suite first).
- Process-based / multi-machine parallelism; a shared global budget accounting concurrent spend.
- Cross-provider panels (separate beyond-design extension; needs non-Anthropic clients).
