# Hermit — Grounded Test-vs-Solution Conflict Adjudicator — Design Spec

**Status:** Approved (2026-07-01). A refinement that turns the moat's cross-checks into an *adjudicator*: when a build stalls just short of green, decide — by **execution, not opinion** — whether a failing test is the *solution's* bug or the *Examiner's* bug.

## Goal

A frozen test failing is *usually* the solution's fault — but sometimes the LLM Examiner writes a wrong/over-strict test that **no correct solution can pass** (e.g. the Roman-numeral demo's `test_m_count`, which forbids the correct `MMMCM`). Today Hermit correctly refuses a fake green but cannot tell the user *which side is wrong*. The adjudicator answers that, grounded in execution.

## The core idea (grounded, not an LLM opinion)

For each failing test, the verdict is decided by **running it against K independent reference implementations**, generated independently of the Builder's solution:

- Generate **K references** (simplest-correct implementations exposing the goal's public interface), via the existing `generate_oracle` reference generator.
- **Run each failing test against each reference** (reference written as `lib.py`, the failing test files copied in, graded by the configured test command).
- Tally, per failing test, how many of the K references **pass** vs **fail** it (plus the solution, which failed it by definition):
  - **≥ majority of references also FAIL** → `test_bug` (multiple independent correct impls can't pass it → the test contradicts correctness).
  - **≥ majority of references PASS** → `solution_bug` (independent impls satisfy it → the solution is the outlier).
  - **otherwise / references error** → `inconclusive`.

The LLM only *generates* the references; **execution casts every vote.** This is the reference oracle repurposed as a judge — fully consistent with "ground checks in execution, not judgment."

## Honesty (load-bearing)

- **Advisory, never auto-editing.** The adjudicator surfaces *suspected* bad tests for human keep/fix/skip; it never rewrites a frozen test. References are LLM-generated, so a verdict is "K of N independent implementations agree," not ground truth.
- **K-voting hardens it.** A single bad reference can't flip a verdict; the default K=3 means a `test_bug` verdict requires a majority of *independent* implementations to also fail the test.
- **Conservative trigger.** It only runs when the build got *close* (best score ≥ a threshold), so it's not second-guessing a solution that's broadly wrong — it's explaining the last mile.

## Components

`hermit/adjudicator.py`:

| Unit | Job |
|---|---|
| `TestVerdict(test_id: str, verdict: str, references_failed: int, references_total: int)` | per-failing-test grounded verdict (`"test_bug"`/`"solution_bug"`/`"inconclusive"`) + the evidence tally |
| `AdjudicationResult(verdicts: list[TestVerdict], references_ok: int, input_tokens: int, output_tokens: int)` | the report |
| `_run_tests_against(impl_code, frozen_dir, failing_nodeids, test_command, timeout) -> dict[nodeid,str]` | write `impl_code` as `lib.py` + the failing test files into a temp dir, run, return each failing nodeid's outcome (`passed`/`failed`/`error`/`missing`) |
| `adjudicate_failures(goal, frozen_dir, failing_nodeids, client, model, test_command, k=3, timeout=120) -> AdjudicationResult` | generate K references, run the failing tests against each, tally majority verdicts; `([],0,...)` when `client is None` or no failing nodeids |

Reuses `generate_oracle` (the simplest-correct reference generator) and `parse_report` (pytest-json-report). Injectable client; fully fake-tested offline (the references are injected; real pytest runs grade them — no live LLM).

## Integration

- **Loop hook (opt-in):** `solve` gains `adjudicator_client=None`. When the loop exits **not green** with `best_score >= config.adjudicate_threshold` and `config.adjudicate_enabled` and a client is provided, run `adjudicate_failures` on the best solution's failing tests, charge tokens, record the verdicts in `run.jsonl`, and attach them to the result. `SolveResult` gains `suspected_bad_tests: list` (the `test_bug` verdicts).
- `RunConfig` gains `adjudicate_enabled: bool = False`, `adjudicate_model: str = "claude-opus-4-8"`, `adjudicate_threshold: float = 0.9`, `adjudicate_references_k: int = 3`.
- **Standalone CLI:** `hermit adjudicate <solution_dir> <tests_dir> <goal_file>` — runs the solution against the suite to find failures, adjudicates them, and prints a report (`test_m_count: TEST BUG — 3/3 references also fail it`).
- **Backward compatible:** off by default; existing behavior unchanged when disabled / no client.

## Testing strategy

- `_run_tests_against`: a correct reference passes a satisfiable test, fails a contradictory one — verified by a real pytest run (offline).
- `adjudicate_failures`: a fake client returning a *correct* reference (e.g. `add = a + b`) + a failing test that **contradicts correctness** (asserts `add(2,3)==6`) → `test_bug` (the reference also fails it); a failing test the reference **passes** (the solution had a real bug) → `solution_bug`. K=3 → majority tally. `client is None` / no failures → empty.
- Loop: a `StubExaminer` whose suite includes one contradictory test + a builder that produces a correct-but-not-green solution → with the adjudicator on, `SolveResult.suspected_bad_tests` names that test; off by default → unchanged.
- CLI: offline (monkeypatched client) → prints the suspected-bad-test report.

## Out of scope (later)

- Auto-fixing a flagged test (it stays advisory + human-adjudicated).
- An interactive keep/fix/skip TUI (the CLI prints the report; the human acts).
- Adjudicating *property* tests by shrinking a counterexample to a specific input (here a property test is treated like any other failing test — does the reference also fail it).
