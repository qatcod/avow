# Forge — Population / Hybrid Search (v4 strategies) — Design Spec

**Status:** Approved (2026-06-28). Implements the **v4 search strategies** from the [design spec](2026-06-26-forge-design.md) §"The swappable seam": `IterativeStrategy` shipped in v1 (it's `solve()`); this adds **Population** (many candidates, verifier picks the winner) and **Hybrid** (escalate to population on plateau).

## Goal

Instead of a single converge attempt, run **N candidate solutions against the same frozen suite** and let the **verifier (calibrated confidence) pick the winner** — the AlphaEvolve move: generate diverse candidates, an objective scorer selects. **Hybrid**: a cheap single attempt first, escalate to the population only when it plateaus (fails to converge green-and-confident).

## Approach: reuse `solve()` unchanged (no risky refactor)

`solve()` is the heavily-tested converge engine. Population does **not** refactor it — it calls it per candidate with **isolated workspaces that share an identical copy of the suite**, so every candidate is judged by the same verifier:

- **Candidate 0:** `solve(goal_dir, write_tests=True, …)` — writes the suite (frozen + hold-out + property) once in `goal_dir`, converges candidate 0 in `goal_dir/.forge`.
- **Candidates 1…N−1:** for each, stage `goal_dir/.forge/candidates/{i}/` with a copy of `goal.md` + `tests_frozen/` + `tests_holdout/`, then `solve(candidate_dir, write_tests=False, …)` — converges independently against the **same** suite in its own `.forge`.
- **Select:** `select_best(results)` ranks by (`success` desc, then `confidence` desc with `None` last, then `best_score` desc); ties break to the lowest index (candidate 0 preferred). Promote the winner's `best_dir` to `goal_dir/.forge/best` so the goal dir ends holding the winning solution.

Diversity comes from builder stochasticity across independent runs (same suite). Forcing *distinct approaches* per candidate (varied builder prompts/seeds) is a noted refinement.

## Components

`forge/population.py`:

| Unit | Job |
|---|---|
| `Candidate(index: int, result, solution_dir)` | a candidate's `SolveResult` + the dir its `.forge/best` lives under |
| `PopulationResult(success, best, candidates, winner_index)` | overall verdict, the winning `SolveResult`, all candidate results, the winner's index |
| `select_best(results: list) -> int` | pure: returns the index of the best `SolveResult` by (success, confidence, best_score); empty → `-1` |
| `population_solve(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> PopulationResult` | the orchestrator above (`config.population_size` candidates) |
| `hybrid_solve(goal_dir, config, examiner, builder, *, …same clients…, now) -> PopulationResult` | run candidate 0 (`solve(write_tests=True)`); if it's green-and-confident (`success`), return it as a 1-candidate `PopulationResult`; else **escalate** to `population_solve` |

Reuses `solve()`/`SolveResult` (unchanged) and `_snapshot` from `forge.improve` (promote the winner). Injectable clients threaded into every `solve()`. `population_size == 1` reduces to a single `solve()`.

## Integration & config

- `RunConfig` gains `population_size: int = 3`.
- CLI: `forge population <goal_dir> [--config] [--no-llm-verify] [--hybrid]` — builds Examiner + Builder + a shared verify client (unless `--no-llm-verify`); runs `population_solve` (or `hybrid_solve` with `--hybrid`); prints the winner + a line per candidate.
- The whole moat runs per candidate's converge (each `solve()` call), so the verifier that picks the winner is the full confidence stack.

## Honest framing & limitations

- **Cost scales linearly with N** — N converge loops, each spawning the Builder + the moat. The budget is **per-candidate** (each `solve()` has its own caps); a shared global budget across candidates is a noted refinement. `population_size` defaults to a modest 3.
- Population is **only as good as the verifier** — it picks the highest-confidence candidate, so a weak moat would pick a confidently-wrong winner. The moat is complete, but this is the standing honest caveat (the verifier is the whole game).
- Candidates run **sequentially** in this slice (simple + safe workspace isolation); parallel candidate execution is a refinement.
- Diversity is from stochasticity only (same builder, same suite); per-candidate approach variation is future work.
- **Asymmetric judging (honest):** candidate 0 runs `write_tests=True`, so its converge includes the suite-level intent check + property generation; candidates 1…N−1 run `write_tests=False` (reusing the *same* suite), so they're judged by `hold-out + mutation + oracle` only. Because intent is a *suite-level* signal (the suite is identical across candidates, so intent is the same constant for all), its presence in candidate 0's average is a small bias, not a real discriminator — but it means confidences aren't composed identically across candidate 0 vs. the rest. The solution-specific signals (hold-out, mutation, oracle) that actually *differentiate* candidates are applied uniformly. Applying the suite-level signals uniformly across all candidates is a noted refinement.

## Testing strategy

- `select_best`: pure — a green high-confidence candidate beats a green low-confidence one beats a non-green one; `None` confidence ranks last among greens; empty list → `-1`; ties → lowest index.
- `population_solve`: offline, `StubExaminer` + `StubBuilder` (`add = a + b`), `population_size=2`, `holdout_fraction=0.0` → both candidates converge green; `len(candidates) == 2`, `success`, `goal_dir/.forge/best/lib.py` holds the winner; the candidate dirs were staged with copies of the suite (`candidates/1/tests_frozen/` exists).
- `hybrid_solve`: candidate 0 green → 1-candidate result (no escalation); plus a forced-escalation path (a `StubBuilder` that can't converge on the first attempt → escalates to population) is a nice-to-have.
- CLI: `forge population` offline (monkeypatched client + StubBuilder) → prints the winner + per-candidate lines; `--hybrid` runs the hybrid path.

## Out of scope (later)

- Parallel candidate execution; a shared global budget across candidates.
- Per-candidate approach/prompt diversity (distinct builder seeds).
- A full `Strategy.run(...)` class hierarchy (this ships Population/Hybrid as orchestrators reusing `solve()`, not a refactor of `solve()` into a strategy object).
