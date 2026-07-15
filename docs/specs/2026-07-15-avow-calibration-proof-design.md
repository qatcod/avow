# Avow — The Calibration Proof (sub-project C) — design

Third and final sub-project of the survival instinct. A built the Gauntlet + fight-back loop; B added the Coroner + Graveyard (learn from each death, seed future gauntlets). C is the **evidence** that A+B actually pay off: it measures, on a labeled benchmark, whether a gauntlet-survived green is materially less often wrong-when-trusted than a plain green, and whether a graveyard *seeded from other goals' deaths* catches more false-greens than an empty one.

The whole point of C is honesty. A calibration proof that overclaims is worse than none, because this is the number shown to design partners. Every claim here is a measured count with its `n`, and the report refuses to state an "N× less likely" multiplier the sample cannot support.

## What C measures

Three cohorts, scored over the same benchmark variants:

1. **plain-green + trusted** — green under the suite, confidence ≥ threshold (today's `false_high_confidence`). Baseline.
2. **survived (empty graveyard) + trusted** — additionally survived a gauntlet run with an empty graveyard.
3. **survived (seeded graveyard) + trusted** — additionally survived a gauntlet seeded (leave-one-out) from patterns mined on the *other* goals' deaths.

For each cohort the report gives `(wrong, trusted)` and `n`. The two claims:

- **Core claim:** cohort 2's false-high-confidence is materially below cohort 1's (the gauntlet catches false-greens the suite missed).
- **Over-time claim:** cohort 3 catches strictly more than cohort 2 (a graveyard learned across projects tightens the curve further).

## Architecture

Extend the existing calibration engine; do not fork it. `avow/calibration.py` (labeled goals → `CalibrationRow` of green/confidence/oracle_agreement/correct, plus `false_high_confidence` and `reliability`) stays as-is. C adds:

- **`avow/calibration_gauntlet.py`** — the gauntlet stage and the three-cohort proof report. Keeps `calibration.py` focused; C's logic is self-contained and independently testable.
- Additions to **`avow/calibration_benchmark.py`** — a related goal family so transfer can be observed.
- A `--gauntlet [--llm] [--seed]` extension to the existing `avow calibrate` CLI verb.

### Reused interfaces (verified against the code)

- `run_gauntlet(solution_dir, goal, client, model, test_command, *, k, examples, timeout, patterns) -> GauntletResult(survived, counterexample, references_ok, references_total, input_tokens, output_tokens)`
- `avow/graveyard.py`: `AttackPattern(category, description, origin_goal, example_input)`, `record`, `load`, `recent`
- `avow/coroner.py`: `abstract_counterexample(counterexample, goal, client, model) -> (AttackPattern | None, int, int)`
- `avow/calibration.py`: `CalibrationGoal(name, goal_text, tests, variants, oracle)`, `_evaluate_variant`, `CalibrationRow`, `_load_module`
- `RunConfig`: `test_command`, `test_timeout_seconds`, `confidence_threshold`, `confidence_weights`, `gauntlet_references_k`, `gauntlet_examples`, `gauntlet_model`, `graveyard_patterns_k`, `coroner_model`

## Components

### 1. The related goal family (shared failure class: numeric-vs-lexical boundary)

Four goals whose false-green all stem from applying **lexical string operations to dotted numeric version identifiers**. A pattern mined from any one ("when comparing multi-part numeric identifiers, probe where a shorter numeric component meets a longer one — e.g. 2.2 vs 2.11, 9.0 vs 10.0") should transfer to the others.

- **`compare_semver(a, b) -> int`** — -1/0/1 comparing dotted versions component-wise as ints. Bug variant: `return (a > b) - (a < b)` (lexical). Fooled by `("2.11","2.2")` (returns -1, oracle says 1).
- **`max_version(versions) -> str`** — the largest version. Bug variant: `max(versions)` (lexical). Fooled by `["9.0","10.0"]` (returns "9.0", oracle says "10.0").
- **`sort_versions(versions) -> list`** — ascending numeric order. Bug variant: `sorted(versions)` (lexical). Fooled by `["10.0","2.0"]` (puts "10.0" first).
- **`is_newer(a, b) -> bool`** — a strictly newer than b. Bug variant: `a > b` (lexical). Fooled by `("2.11","2.2")`.

Each goal ships: a correct reference; a deliberately imperfect suite whose cases are all single-digit (so the lexical bug stays green); one injected bug variant (green-under-suite, oracle-wrong — a real false-green); an independent `oracle` that checks the multi-digit boundary cases. This mirrors the existing `roman`/`leap_year`/`is_prime` construction exactly.

### 2. Gauntlet scoring — `score_with_gauntlet`

```
GauntletScore = dataclass(green: bool, survived: bool, references_ok: int)

def score_with_gauntlet(goal, src, config, ref_client, patterns) -> GauntletScore
```

Writes `src` to a solution dir, runs the suite to get `green`. If green, runs `run_gauntlet(sol_dir, goal.goal_text, ref_client, config.gauntlet_model, config.test_command, k=..., examples=..., timeout=..., patterns=patterns)` and records `survived`/`references_ok`. If not green, `survived=False` (a non-green never reaches the gauntlet). Execution decides survival; the ref client only proposes references.

**`ref_client`:**
- `--llm`: a real `anthropic.Anthropic()`.
- default (CI): a **deterministic stub**. The stub returns, per goal, a fixed correct reference and a Hypothesis diff test. Crucially the stub is *seeding-aware* for the mechanism test: when the seeded boundary pattern text is present in the reference-generation prompt, it returns a diff test whose strategy samples the multi-digit boundary (so the lexical bug is caught); when absent, a weak single-digit strategy (so the bug survives). This lets a hermetic CI test demonstrate end-to-end that seeding catches strictly more, with no API key and no flakiness.

### 3. Leave-one-out seeding — `build_seeded_patterns`

```
def build_seeded_patterns(goals, held_out_name, coroner_client, config) -> list[AttackPattern]
```

For every goal except `held_out_name`, take its known false-green bug, run it through the gauntlet to obtain a `Counterexample`, and abstract it with the Coroner into an `AttackPattern`. Return the deduped list. In stub/CI mode `coroner_client` is a fixed stub returning the family's boundary pattern; in `--llm` mode it is the real client.

**Leakage guard (the core honesty mechanism):** the returned patterns are asserted to contain none of the held-out goal's own falsifying `example_input` values. A dedicated unit test feeds a seed set that *does* leak and asserts the guard raises. Without this guard the seeded cohort could be trivially, dishonestly inflated.

### 4. The proof report — `CalibrationProof`

```
Cohort = dataclass(name: str, wrong: int, trusted: int)

CalibrationProof = dataclass(plain: Cohort, survived_empty: Cohort, survived_seeded: Cohort)
    def honesty(self, min_n: int) -> str
```

`honesty(min_n)` always prints each cohort's `wrong/trusted (n=…)`. It prints the "survivors are N× less likely to be wrong" multiplier **only** when both `plain.trusted` and `survived_empty.trusted` are ≥ `min_n` and `plain` has a nonzero wrong rate; otherwise it prints `insufficient n (got X, need ≥min_n) — raw counts only`. `MIN_N` default 8, configurable. Same gate applies to the seeded-vs-empty "catches more" line.

### 5. Orchestration — `run_calibration_proof`

```
def run_calibration_proof(goals, config, ref_client, coroner_client, min_n) -> CalibrationProof
```

For each goal, for each variant: compute the plain `CalibrationRow` (reuse `_evaluate_variant`); then `score_with_gauntlet` with empty patterns; then `score_with_gauntlet` with `build_seeded_patterns(goals, this_goal, ...)`. `trusted` uses the same threshold/oracle-floor definition as `CalibrationReport._trusted`. Tally the three cohorts. A variant only enters cohort 2/3 if it is both trusted *and* the gauntlet survived.

### 6. CLI

`avow calibrate --gauntlet [--llm] [--seed]`:
- `--gauntlet` switches to the proof path (`run_calibration_proof`) over `DEFAULT_GOALS + FAMILY_GOALS`.
- `--llm` uses real Anthropic clients for references and the Coroner; without it, the deterministic stubs (green CI, but only the mechanism is proven, not real numbers).
- `--seed` includes the seeded cohort; without it only plain vs survived-empty (cheaper).
- Output: the three cohorts, each `wrong/trusted (n=…)`, then the `honesty(min_n)` line. When `--llm`, label the block `n=…, LLM references, single run` so no one mistakes one run for a distribution.

## Honesty guards (summary)

- **Leakage guard** — held-out goal's falsifying inputs never seed its own cohort; unit-tested both ways.
- **Small-n guard** — no multiplier below `MIN_N`; always print raw counts + `n`.
- **Determinism** — stub clients make CI runs deterministic and green; real numbers only under `--llm`, explicitly labeled single-run.
- **No overclaim in copy** — "survived K references" is never printed as "correct"; the existing `calibrate` disclaimer is retained.

## Error handling

- Gauntlet/Coroner failures during the proof are the measurement itself, not best-effort side effects: if a real-LLM reference call fails, that variant's gauntlet result is recorded as `survived=False, references_ok=0` (a reference that could not run does not vote), consistent with `run_gauntlet`'s own "unusable reference" handling. The proof run never crashes on a single client error; it records and continues.
- An empty benchmark or all-non-green variants yields cohorts with `trusted=0` and the small-n guard fires — no division by zero.

## Testing

**Mechanism tests (stub clients, hermetic, CI-green, no API key):**
- Cohorts are tallied correctly for a hand-built goal set (a planted false-green that the seeding-aware stub catches moves from cohort-1 trusted-wrong to killed in cohort 3).
- Seeded cohort catches strictly more than empty cohort on the family (the end-to-end "seeding helps" plumbing).
- Leakage guard: a seed set containing the held-out goal's falsifying input raises; a clean set passes.
- Small-n guard: below `MIN_N`, no multiplier; at/above, the multiplier prints.
- `graveyard_path` and any store writes are hermetic (temp paths, never `~/.avow`).

**Benchmark-family tests:** for each family goal, the reference is green-under-suite and oracle-correct, and the injected bug is green-under-suite but oracle-wrong (a genuine false-green) — otherwise the goal proves nothing.

## Out of scope (YAGNI)

- Embedding/semantic pattern retrieval (keyword/tag only, matches B).
- Cross-provider references (OpenRouter).
- Multi-run distributions / confidence intervals under `--llm` (single labeled run for now; the guard prevents overclaiming from it).

## Build order

C depends on A (gauntlet) and B (graveyard/coroner), both shipped and green. Build the family goals first (they are pure data + oracles, independently testable), then the gauntlet scoring, then seeding + leakage guard, then the proof report + honesty guard, then the CLI. Same review-before-push bar as A and B: full-suite gate + adversarial whole-branch review, fix, then push only on greenlight.
