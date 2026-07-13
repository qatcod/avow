# Avow — Reference-Oracle as a Converge Target — Design Spec

**Status:** Approved (2026-06-29). A beyond-design upgrade to the reference-oracle ([oracle spec](2026-06-27-avow-reference-oracle-design.md), which shipped the oracle as a *post-green signal* and named "the reference as a converge target" as explicit future work).

## Goal

Upgrade the reference oracle from **post-hoc detection** (flag a disagreement after the solution converges, when it's too late to fix) to **in-build prevention**: generate the independent reference + its Hypothesis differential test up front and fold the diff test into the **frozen suite**, so the Builder must make its solution **agree with the reference on thousands of fuzzed inputs *during* convergence**.

## Why this is safe and honest

- **Anti-cheat preserved.** `ref.py` and the differential test are written into `tests_frozen/` — the un-gameable suite the Builder never sees (the Runner grades in an ephemeral copy; the Builder only receives pass/fail + failure messages). `ref.py` is a plain module (no `test_` prefix → not collected as a test, but importable by the diff test, which sits in the same graded test dir). The Builder physically cannot read or edit the reference.
- **A wrong reference fails LOUDLY, not silently.** The reference is LLM-generated, so it can be wrong. But the solution must satisfy **both** the Examiner's suite **and** reference-agreement. If the reference contradicts the Examiner's tests, **no solution passes both → the build fails (plateau/no-green) and surfaces the conflict** — rather than silently corrupting the solution to match a bad reference. This is strictly safer than trusting the reference alone.
- **Opt-in, off by default** (`oracle_converge_target = False`). It trusts the reference more than the post-green signal does (it forces agreement rather than flagging), so it's a deliberate choice. The post-green oracle signal/floor (the existing `oracle_enabled` path) is unchanged and independent.

## Method

In `solve()`'s `write_tests` block (where the Examiner suite is written and the property hook folds in property tests), when `config.oracle_converge_target and oracle_client is not None`:
1. `generate_oracle(goal, oracle_client, config.oracle_model)` → an `_OraclePair(reference_code, diff_test_code)` (the same generator the post-green oracle uses; the diff test imports `from lib import … as _sol` / `from ref import … as _ref` and asserts agreement under `@given`).
2. Append the diff test to the **visible** set as a `TestFile(path="test_oracle_converge.py", content=diff_test_code)` (so it's written into `tests_frozen/` by `_write_tests` and becomes a converge target — visible, never held out).
3. After `_write_tests(frozen, visible)`, write the reference module to `frozen / "ref.py"` (so it's present in the graded copy for the diff test to import).
4. Charge the generation tokens to the budget.

The Builder then converges against the grown suite (Examiner tests + property tests + the reference-agreement diff test). If a `pair is None` (no client / generation failure), the hook is a no-op.

## Components

- `avow/loop.py`: the `write_tests` block gains the oracle-converge-target hook (imports `generate_oracle` from `avow.oracle` and `TestFile` from `avow.examiner`); `solve` already takes `oracle_client`. No new `solve` parameter.
- `RunConfig` gains `oracle_converge_target: bool = False`.

## Honest framing & limitations

- **Trusts the reference more** than the post-green signal: it forces agreement during the build rather than flagging it after. Mitigated by the both-suites-must-pass property (a wrong reference fails the build loudly) and by being off by default. Best used when the reference is likely correct (simple, well-specified goals) or alongside the Examiner's suite as one more constraint.
- **Cost:** one `generate_oracle` call per `solve` that regenerates tests (charged to the budget), plus the diff test runs every converge iteration (Hypothesis fuzzing during the build).
- **Interaction with the post-green oracle:** independent. `oracle_enabled` (post-green signal + floor) and `oracle_converge_target` (in-build) can both be on, both off, or either alone. With the converge target on, a converged solution already agrees with *a* reference; the post-green oracle (if on) generates a *fresh* reference for an independent post-hoc check.
- The reference shares the Builder/Examiner model family (the standing oracle caveat) — decorrelation comes from the different prompt (simplest-correct) and the differential fuzzing, not provider independence.

## Testing strategy

- Loop, converge-target ON: a fake `oracle_client` returning a pair whose reference is `add = a + b` and whose diff test asserts `_sol(a,b) == _ref(a,b)`. The `StubExaminer` writes `test_add` (satisfied by `a+b`); the `FlakyBuilder` converges to `a+b` → it passes the Examiner test AND agrees with the reference → green. Assert: the run is green, and `tests_frozen/test_oracle_converge.py` and `tests_frozen/ref.py` both exist. (Runs offline through the real Runner; `hypothesis` is installed.)
- Loop, converge-target OFF (default) or no `oracle_client`: the hook is a no-op; `tests_frozen/ref.py` does NOT exist; existing behavior unchanged.
- Config default `oracle_converge_target == False`.

## Out of scope (later)

- Multiple references / cross-reference agreement as converge targets.
- A cross-provider reference (needs non-Anthropic clients).
- Auto-detecting a contradictory reference and dropping it (currently it just fails the build, which surfaces the conflict).
