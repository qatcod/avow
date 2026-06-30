# Hermit — Parallel Candidate Execution — Design Spec

**Status:** Approved (2026-06-28). A beyond-design extension to the v4 Population strategy ([Population spec](2026-06-28-hermit-population-search-design.md), which shipped candidates running *sequentially* and named parallel execution as a refinement).

## Goal

Run Population's candidate converge loops **concurrently** instead of sequentially, so a Population/Hybrid run takes ~1× the wall-time of a single candidate instead of N×. This is what makes multi-candidate search practical for real (live) runs where each candidate is minutes of `claude -p` + test execution.

## Why this is safe and correct

- **Candidates are already fully isolated** — candidate 0 in `goal_dir/.hermit`, candidates 1…N−1 each in their own `goal_dir/.hermit/candidates/{i}/.hermit` with a private copied suite. No shared mutable state, so they can run concurrently without interfering.
- **`solve()` is subprocess-bound** — it spends its time in `claude -p` and `pytest` subprocesses, which release the GIL, so a thread pool gives real concurrency for this workload without `solve()` changes.
- **Determinism is preserved** — results are collected **in candidate-index order** (not completion order), and `select_best` ranks deterministically (ties → lowest index). So parallelism changes *only the speed*, never *which candidate wins* or *what lands at `goal_dir/.hermit/best`*. Existing Population tests produce identical outcomes.

## Method

In `_run_candidate_pool`:
1. **Candidate 0 has already run** (sequentially, in the caller — it wrote the shared suite). The pool handles candidates `len(candidates) … max(1, population_size) − 1`.
2. Each pool candidate `i`: `_stage_candidate(goal_dir, cand_dir)` then `solve(cand_dir, write_tests=False, …)`. Staging writes only into `candidates/{i}/` (disjoint per i), so staging is also concurrency-safe.
3. Submit the pool candidates to a `concurrent.futures.ThreadPoolExecutor(max_workers=min(config.max_parallel_candidates, n_pool))`; gather results **indexed by candidate i** so the final `candidates` list is in index order regardless of completion order.
4. `select_best` + promote the winner — unchanged.

When `max_parallel_candidates == 1` (or only one pool candidate), behavior is exactly the current sequential path.

## Components

- `hermit/population.py`: `_run_candidate_pool` rewritten to submit the pool candidates to a `ThreadPoolExecutor` and collect results in index order. A small helper `_solve_candidate(goal_dir, i, config, examiner, builder, clients, now) -> Candidate` runs one staged candidate (callable per worker). `select_best` / promotion / `population_solve` / `hybrid_solve` signatures unchanged.
- `RunConfig` gains `max_parallel_candidates: int = 4`.

## Honest framing & limitations

- **Live resource/rate-limit pressure:** N concurrent candidates means N concurrent `claude -p` sessions + pytest runs. `max_parallel_candidates` (default 4) caps it; set it to `1` for the old sequential behavior on constrained machines or tight rate limits.
- **Per-candidate budget still applies** (each `solve()` keeps its own caps); there is still no shared global budget across candidates. Concurrency doesn't change the budgeting *model*, but it does interact with the *wall-clock* budget: under N saturating candidates a single candidate may hit `max_wall_seconds` at fewer iterations than it would run sequentially, so a candidate's *content* can differ from a sequential run (selection stays deterministic given the results; the per-candidate work can be shorter under load).
- **A crashed candidate records why:** a worker exception is captured into the failed candidate's `reason` (`"candidate_error: <exc>"`) so a live crash is debuggable, not silently swallowed.
- **Thread-safety scope:** safe *because* each candidate writes only into its own disjoint directory and `solve()`/`Runner` use per-call `TemporaryDirectory`s. This relies on no candidate touching another's paths (true by construction here). Candidate 0 is deliberately NOT parallelized — it must finish writing the shared suite before any pool candidate copies it.
- Exceptions in a worker propagate as a failed candidate; `_run_candidate_pool` must not let one candidate's crash abort the others (collect per-candidate, tolerate a `None`/failed result, and let `select_best` ignore it).

## Testing strategy

- `_run_candidate_pool` / `population_solve` with `max_parallel_candidates=4`, `population_size=3`, a `StubBuilder` → all 3 candidates run, results are index-ordered, the winner is promoted, `candidates/{1,2}/` staged. Same assertions as the sequential test (outcome-identical).
- Determinism: a builder whose candidates would finish out of order still yields a deterministic `winner_index` (results indexed, not completion-ordered).
- `max_parallel_candidates=1` → behaves exactly like the sequential path (regression pin).
- A worker that raises (one candidate's `solve` throws) → the pool tolerates it (that candidate is a failed/None result), the others still complete, and selection proceeds.
- Config default `max_parallel_candidates == 4`.

## Out of scope (later)

- Parallelizing candidate 0 with the pool (it must write the suite first).
- Process-based parallelism / distributing candidates across machines.
- A shared global budget that accounts concurrent spend.
- Cross-provider panels (needs non-Anthropic clients/keys — a separate beyond-design extension).
