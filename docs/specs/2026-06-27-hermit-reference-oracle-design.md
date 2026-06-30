# Hermit — Reference-Oracle Differential Testing (Layer I completion) — Design Spec

**Status:** Approved (2026-06-27). Completes **Layer I** of the verification moat ([design spec](2026-06-26-hermit-design.md) §"Verification subsystem"): property/metamorphic tests shipped in v2.4; this adds the **reference-oracle-by-simplicity** half.

## Goal

Alongside the Builder's clever solution, generate a **second, independent, simplest-possible** implementation of the same goal, then **differential-test** the two against thousands of random inputs. If they ever disagree, at least one is wrong — a strong, decorrelated bug signal that needs no human and no reference answer baked in by hand.

## Honest calibration (stated up front)

The reference implementation is **also LLM-generated**, so it is **not literal ground truth**. A disagreement means *"two independently-derived implementations disagree → one of them is wrong → investigate"*, not *"the solution is definitely wrong."* The strength comes from **decorrelation**: a different model, prompted for the simplest-correct version rather than the clever one, has different blind spots than the Builder — so agreement across thousands of fuzzed inputs is strong evidence of correctness, and disagreement is strong evidence of a real problem in one of them. The system surfaces it as measured uncertainty (a confidence penalty + a floor + the counterexample), never as certainty.

## Method (mirrors the mutation signal — post-green, self-contained)

1. **Generate the oracle pair** (one LLM structured call): `reference_code` — the simplest, most obviously-correct implementation of the goal, same public interface as the solution, clarity over speed — **and** `diff_test_code` — a Hypothesis test that imports `from lib import …` (the solution) and `from ref import …` (the reference) and asserts they agree under `@given` over the goal's input types.
2. **Run the differential test** in an ephemeral dir holding the solution's modules (`lib.py` etc.) + the generated `ref.py` + the diff test → pytest.
3. **Score:** `agreement = 1.0` if the diff test passes (no disagreement in the fuzz budget), `0.0` if Hypothesis finds + shrinks a counterexample (recorded). A **baseline guard**: if the diff test *errors* (broken reference, import failure) rather than cleanly passing/failing, the result is **inconclusive** (`baseline_ok=False`, `agreement=None`) — never a false alarm.

## Components

`hermit/oracle.py`:

| Unit | Job |
|---|---|
| `_OraclePair(BaseModel)` with `reference_code: str`, `diff_test_code: str` | structured-output schema |
| `generate_oracle(goal, client, model) -> tuple[_OraclePair \| None, int, int]` | LLM emits the matched reference + diff test + token usage; `(None, 0, 0)` when `client is None` |
| `OracleResult(agreement, baseline_ok, counterexample, checked, input_tokens, output_tokens)` | `agreement: float \| None` (None when inconclusive); `counterexample: str` (the shrunk disagreeing input, or "") |
| `run_oracle_check(solution_dir, goal, client, model, test_command, timeout) -> OracleResult` | generate the pair, stage an ephemeral dir (solution modules + `ref.py` + diff test), run pytest, parse → agreement / inconclusive |

Reuses `scoring.parse_report` (pytest-json-report) to classify the diff test's outcome; reuses the ephemeral-dir + subprocess-timeout pattern from `Runner`/`mutation`. Injectable client; fully fake-tested (the *run* path is tested with a real tiny solution+reference offline — no LLM, the pair is injected).

## Integration (a confidence signal + a floor — same pattern as hold-out)

- **Loop hook (post-green, like mutation):** when `config.oracle_enabled and oracle_client is not None`, after the solution goes green run `run_oracle_check(best_dir, goal, oracle_client, config.oracle_model, …)`, charge tokens, and feed `agreement` into the confidence aggregate as a new **`oracle`** signal. When the oracle isn't run, the signal is **absent** — `aggregate_confidence` filters present signals and renormalizes, so the existing 3-signal confidence math is **unchanged** (existing tests stay green).
- **Oracle floor:** when gating is on and the oracle ran and `agreement is not None and agreement < config.oracle_floor`, force `low_confidence` (a hard disagreement can't be averaged away), with the counterexample recorded in the run log. Mirrors the hold-out / panel-agreement floors. An **inconclusive** oracle (`agreement is None`) neither scores nor floors — it's logged and skipped.
- `RunConfig` gains `oracle_enabled: bool = True`, `oracle_model: str = "claude-opus-4-8"`, `oracle_floor: float = 1.0` (binary agreement → any disagreement breaches); `confidence_weights` gains `"oracle": 1.0`.
- `SolveResult` gains `oracle_agreement: float | None = None`.
- **Standalone:** `hermit oracle <solution_dir> <goal_file>` — generate a reference and differential-test any solution; prints agreement + any counterexample.
- Injectable `oracle_client`; offline / no-client runs skip the hook.

## Testing strategy

- `generate_oracle`: fake client returning an `_OraclePair` + usage → goal forwarded, pair + tokens flow through, `None`-client no-op.
- `run_oracle_check`: **offline**, with an injected fake client returning a fixed `_OraclePair`:
  - *agree* — solution `lib.py` (`add=a+b`) + reference (`add=a+b`) + a diff test → `agreement == 1.0`.
  - *disagree* — solution (`add=a+b`) + reference (`add=a*b`) + a diff test → `agreement == 0.0`, `counterexample` non-empty.
  - *inconclusive* — a syntactically broken reference → `baseline_ok is False`, `agreement is None`.
- `aggregate_confidence`: oracle present → 4-signal mean; oracle `None`/absent → unchanged 3-signal (renormalized).
- Loop: an `oracle_client` whose pair *disagrees* with the converged solution → `agreement 0.0` → floor → `low_confidence` even with the other signals high; existing loop tests (no `oracle_client`) unchanged.
- CLI: `hermit oracle` offline via a monkeypatched client → prints agreement.

## Out of scope (later)

- A *fractional* agreement (Hypothesis stops at the first counterexample, so agreement is binary {0,1}); a sampling loop counting agreement over N inputs is a later refinement.
- Using the reference as a *converge target* (injecting `ref.py` into the grading env so the Builder fixes disagreements during the build) — deferred; the post-green signal is the clean first slice.
- Multiple references / voting across reference implementations.
