# Avow — The Survival Gauntlet (sub-project A) — Design Spec

**Status:** Approved (2026-07-15). Sub-project A of the "survival instinct." B (the Coroner + Graveyard) and C (the calibration proof) are backlogged in `2026-07-15-avow-survival-instinct-backlog.md`.

## Goal

Give Avow a survival instinct. After it declares a solution green + high-confidence, a deliberately harder **execution gauntlet** hunts for a single mistake. One real counterexample kills the "perfect," and the run must **fight back**: turn the counterexample into a frozen test, rebuild, re-converge, and face a fresh gauntlet — until it survives a full gauntlet clean (a **verified survivor**) or dies honestly at the budget (**died**, with the counterexample that killed it). Ships dormant.

## Why (the thesis)

The worst failure is a confident false-green; calibration measured it at 62%. Behavioral-green plus the confidence floors are the *cheap* verifier. The gauntlet is an *expensive* verifier that runs only on the small set of solutions Avow already believes are perfect. It converts "I think this is right" into "this survived a much harder attack than the one that convinced me."

## The kill signal (execution-grounded, never opinion)

A kill is decided by execution:

1. Generate **K independent reference implementations** of the goal (reuse `oracle.generate_oracle` with varied prompts for independence, exactly as `adjudicator` already does).
2. Each reference ships a Hypothesis **differential test** (`assert solution(x) == reference(x)`) that fuzzes type-appropriate inputs. Run each against the solution with a raised example count (`gauntlet_examples`).
3. **Majority vote:** if MORE than half the references diverge from the solution on some input, the solution is the outlier → **KILL**. (Majority-of-K, like the adjudicator, stops one bad reference from a false kill.)
4. If the majority of references AGREE with the solution across the fuzzed space → the solution **survives** this gauntlet.

The counterexample is the Hypothesis falsifying example (the minimal input) plus the reference-majority's output (expected) vs the solution's output (actual).

## Components

### `avow/gauntlet.py`

| Unit | Job |
|---|---|
| `Counterexample(input_repr: str, expected: str, actual: str, regression_test: str)` | one execution-proven mistake + a runnable pytest regression test asserting the expected (reference-majority) output |
| `GauntletResult(survived: bool, counterexample, references_ok: int, references_total: int, input_tokens: int, output_tokens: int)` | outcome of one gauntlet |
| `run_gauntlet(solution_dir, goal, client, model, test_command, *, k, examples, timeout) -> GauntletResult` | generate K references, run their differential fuzz tests against the solution, majority-vote, extract the counterexample on a kill |
| `_extract_falsifying_example(pytest_output: str) -> str` | parse Hypothesis's `Falsifying example: ...` line from a failed diff-test run |

The diff tests run with a Hypothesis example count of `examples` (via an injected `@settings(max_examples=examples, deadline=None)` on the generated test, or a `HYPOTHESIS_PROFILE`), so the gauntlet fuzzes far harder than a normal build.

### `avow/survive.py`

| Unit | Job |
|---|---|
| `SurviveResult(status: str, rounds: int, final, death_counterexample)` | `status ∈ {verified_survivor, died, not_green, aborted}` |
| `survive(goal_dir, config, examiner, builder, *, gauntlet_client, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> SurviveResult` | run `solve`; if green + `gauntlet_client`, run the survival loop |

### `avow/config.py`

`survival_enabled: bool = False` · `gauntlet_references_k: int = 4` · `gauntlet_max_rounds: int = 3` · `gauntlet_examples: int = 200` · `gauntlet_model: str = "claude-opus-4-8"`.

### `avow/cli.py`

- `avow survive <goal-dir>` — the full survival loop (mirrors `harden`; `--no-llm-verify` and `--yes` like `solve`).
- `avow gauntlet <solution-dir> <goal.md>` — attack an existing artifact once and print `verified survivor` or the counterexample (standalone, like `oracle`/`adjudicate`).

## The survival loop (`survive()`)

1. `result = solve(goal_dir, config, examiner, builder, ...)` — green + confidence, as today.
2. If not green → `SurviveResult("not_green", 0, result, None)` (nothing to attack).
3. `round = 0`; loop while `round < config.gauntlet_max_rounds` (the primary bound; a shared `Budget` on `max_cost_usd`/`max_wall_seconds` can also terminate early, yielding `died`):
   - `g = run_gauntlet(best_dir, goal, gauntlet_client, config.gauntlet_model, config.test_command, k=config.gauntlet_references_k, examples=config.gauntlet_examples, timeout=config.test_timeout_seconds)`
   - charge `g`'s tokens to the run's `Budget` (for cost reporting + the early-stop guard).
   - if `g.survived` → `SurviveResult("verified_survivor", round, result, None)`.
   - else (hit): write `g.counterexample.regression_test` into `tests_frozen/` as `test_gauntlet_r{round}.py` (collision-free); re-run `solve(..., write_tests=False)` so the Builder must satisfy the counterexample too; `round += 1`.
4. Loop exits (hit `gauntlet_max_rounds` or budget) without surviving → `SurviveResult("died", round, result, last_counterexample)` — honest: low confidence + the counterexample that killed it.

## Anti-cheat & honesty (load-bearing)

- The Builder never sees the gauntlet's references or counterexamples during a build; a counterexample enters only as a frozen regression test, graded in the ephemeral copy — the same anti-cheat as the Examiner's tests.
- A kill is an execution divergence from the reference **majority** (or a property violation / crash), never an LLM's opinion. References are independently generated and never shown the solution.
- **"verified survivor" is not "provably correct."** It means "survived a K-reference execution gauntlet over a large fuzzed input space." Labeled honestly in the CLI output, `SurviveResult`, and docs.
- Ships **dormant** (`survival_enabled=False`); the `survive`/`gauntlet` verbs are opt-in. `solve` is unchanged — proven by an off-path test.

## Testing strategy

- `run_gauntlet` (offline, fake client returning known reference code + diff tests): a solution that agrees with the references → `survived=True`; a green-but-wrong solution that diverges from a majority of references on a fuzzed input → `survived=False` with a `Counterexample` whose `regression_test` runs and fails on the wrong solution, passes on a correct one. `_extract_falsifying_example` parses a sample Hypothesis failure string.
- `survive` (fake solve/builder/examiner + fake gauntlet client): (a) a correct solution → `verified_survivor` at round 0; (b) a green-but-wrong solution the builder fixes when handed the counterexample → `verified_survivor` after N rounds, and the gauntlet regression test is present in `tests_frozen/`; (c) a green-but-wrong solution the builder can't fix → `died` at `gauntlet_max_rounds` with `death_counterexample`; (d) no `gauntlet_client` → identical to `solve` (proven).
- CLI: `avow survive` and `avow gauntlet` smoke tests with the fakes.
- Full suite green; `survival_enabled` off path unaffected.

## Explicitly out of scope (backlog)

- **B — Coroner + Graveyard:** abstract each counterexample into a transferable AttackPattern, persist globally (`~/.avow/graveyard.jsonl`), seed future gauntlets with relevant patterns (LLM instantiates concrete attacks from patterns). The "gets better over time" half.
- **C — Calibration proof:** extend `avow calibrate` to show survivors beat plain greens on false-high-confidence, and that a growing graveyard keeps moving the curve.
- Cross-provider gauntlet (decorrelated references from different model families) once OpenRouter credits land.
- Type-aware input generation beyond what `generate_oracle`'s Hypothesis strategies already cover.
