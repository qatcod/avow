# Avow — Verifier Checks (generalize beyond pytest) — Design Spec

**Status:** Approved (2026-07-01). The first slice of the "widen the verifier menu" direction: let Avow escape *code-with-unit-tests* by adding arbitrary verifier commands (lint, typecheck, security scan, metric/audit) as first-class gates alongside the pytest suite.

## Goal

Today Avow's only verifier is a pytest suite. Add **checks** — arbitrary verifier commands the solution must also pass — so a goal can require not just "the tests pass" but "the tests pass **and** it lints clean **and** it typechecks **and** it's under the size/perf budget." The same machinery extends to accessibility / SEO / schema / security audits: anything that runs and returns pass/fail. More verifier *types* → more product *types* Avow can drive to perfect.

## The check model

A **check** is `{name, command}`: a command run in the solution directory. **Exit code 0 = pass**, non-zero = fail (this is the universal convention for ruff, mypy, pytest, most audit tools). On failure, the command's captured stdout/stderr (truncated) becomes the failure detail fed to the Builder.

## Integration — fold into the grade (the whole moat stays unchanged)

`TestResult` has `passed/failed/errors/total/failures` fields with `score`/`is_green` as computed properties. Checks fold in by constructing a **combined `TestResult`**:
- `passed += #checks that passed`, `failed += #checks that failed`, `total += #checks`, `failures += [FailureInfo("check::<name>", detail) for each failed check]`.
- Then `score` (`passed/total`) and `is_green` (`failed==0 and errors==0`) automatically reflect the checks; the loop reads the same `result` and needs no other change.

In the loop, right after `result = runner.run()`: if `config.checks`, run them on `workspace.solution_dir` and `result = combine_checks(result, check_results)`. The Builder's `best_failures` then includes `check::lint: <ruff output>`, so it iterates to fix lint/type errors exactly as it fixes failing tests. **`checks == []` (default) → `combine_checks` returns the result unchanged → zero behavior change; every existing test is unaffected.**

## Components

`avow/checks.py`:

| Unit | Job |
|---|---|
| `CheckResult(name: str, passed: bool, detail: str)` | one check's outcome |
| `run_checks(solution_dir, checks, timeout=120) -> list[CheckResult]` | run each `{name, command}` in `solution_dir`; `passed = (returncode == 0)`; detail = truncated stdout+stderr on failure; guards TimeoutExpired / FileNotFoundError (missing tool → failed check, not a crash) |
| `combine_checks(result, check_results) -> TestResult` | fold checks into a new `TestResult` (as above); `check_results == []` → returns `result` unchanged |

- `RunConfig` gains `checks: list = Field(default_factory=list)` — each item a dict `{name, command}`.
- **Loop:** after `runner.run()`, when `config.checks`: `result = combine_checks(result, run_checks(workspace.solution_dir, config.checks, config.test_timeout_seconds))`. One inserted line; nothing else changes.
- **CLI:** `avow check <solution_dir> [--config]` — run the configured checks on a solution and print each check's pass/fail (standalone, like `mutate`/`verify`).

## Honesty & limitations

- **Execution-grounded, no LLM** — checks are deterministic commands; this is the strongest kind of verifier and fully offline-testable.
- **Weaker anti-cheat than tests.** Checks run on the solution dir, and the Builder sees the check failures — so a determined Builder could weaken a check via tool-config (a `# noqa`, a permissive `ruff.toml`/`mypy.ini`). This is weaker than the hidden pytest suite (which the Builder never sees), but such gaming is visible to a human reviewer. **Stripping builder-added tool-config before running checks (or passing explicit rules) is a noted refinement**, out of scope for this slice.
- **Exit-code semantics only** in this slice — a check passes iff the command exits 0. Threshold-on-a-metric checks (parse a number from output, compare to a budget) are a natural follow-up on the same `CheckResult` shape.
- Subjective quality (taste, brand voice) is NOT a check — that's the rubric-panel / cross-provider direction (separate; needs OpenRouter credits).

## Testing strategy

- `run_checks`: a passing check (`python -c "exit(0)"`) and a failing check (`python -c "exit(1)"`) → correct `passed`; a missing command → failed (not a crash); detail captured on failure.
- `combine_checks`: a `TestResult` (2 passed, 0 failed, total 2) + one passing + one failing check → combined (3 passed, 1 failed, total 4), `is_green False`, `failures` includes `check::<name>`; empty checks → returns the result object unchanged.
- Loop: `checks=[{always-fail}]` + a solution that passes the pytest suite → never green (the check gates it), the Builder's feedback carries the check failure; `checks=[{always-pass}]` → green; `checks=[]` (default) → existing behavior unchanged.
- CLI: `avow check` on a solution with a passing + a failing check → prints both outcomes.

## Out of scope (later)

- Metric-threshold checks (parse a number, compare to a budget).
- Stripping builder tool-config / sandboxed checks for stronger anti-cheat.
- The Ideator proposing checks (extend its verifier vocabulary to this menu).
- Rubric / cross-provider-panel checks for subjective quality.
