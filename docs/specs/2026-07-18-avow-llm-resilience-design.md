# Avow — Resilient LLM calls for long runs — design

Live validation (2026-07-18) surfaced this concretely: two real `calibrate --gauntlet --seed --llm`
sweeps (~100 calls, ~15 min each) both aborted on a single transient network failure — a connection
error, then a timeout *even with the Anthropic SDK set to 8 retries*. Every short run (gauntlet,
survive, coroner) succeeded. So a long multi-call run loses all of its expensive partial work when
one call ultimately fails, and the newly committed OpenRouter client has no network retry at all.

The load-bearing lesson: higher retries reduce *how often* a call fails, but a sustained network
stretch still exhausts them, so the sweep must also *survive* a fully-failed call. This feature does
both: reduce the failure rate (retries), and make the expensive sweep tolerant of the failures that
still get through (skip-and-continue with honest coverage reporting).

## Scope (three parts, one theme)

### A. Configurable Anthropic retries on the long-run verbs

- Add `llm_max_retries: int = 6` to `RunConfig` (the Anthropic SDK default is 2).
- Add a tiny CLI helper `_anthropic(config)` returning `anthropic.Anthropic(max_retries=config.llm_max_retries)`.
- Use it in the multi-call verbs that a transient blip is most likely to hit over their runtime:
  `_cmd_survive`, `_cmd_gauntlet`, `_cmd_calibrate_gauntlet` (both client sites). Single-call verbs
  (oracle, supervise, adjudicate) are left as-is; they would benefit marginally, but bounding the
  change keeps the diff reviewable. This reduces failure frequency; it does not, by itself, guarantee
  completion.

### B. Bounded network retry in the OpenRouter client (`_post`)

The OpenRouter `_post` does a single `httpx.post` and raises on any failure. Wrap the HTTP call in a
bounded retry loop with exponential backoff, retrying ONLY transient failures:
`httpx.TransportError` / `httpx.TimeoutException`, and HTTP status `429` or `5xx`. A `4xx` (a real
client error) is never retried — it is surfaced immediately, unchanged. Defaults: 4 attempts, base
backoff 0.5s doubling. Parse-level retry (the existing "reply with only JSON" correction) is a
separate concern and is unchanged.

### C. Per-item fault tolerance in the calibration proof (the load-bearing fix)

`run_calibration_proof` must complete even when individual calls fail after all retries, rather than
aborting the whole sweep. Wrap the two failure-prone units in try/except:

- **Per-goal seeding:** if `build_seeded_patterns(...)` raises, that goal contributes no seed
  patterns (its seeded cohort simply is not scored for that goal) and a `skipped` counter increments.
  Mining a goal is independent of scoring it, so a mining failure must not lose the goal's plain /
  empty cohorts.
- **Per-variant scoring:** wrap the whole `_evaluate_variant` + empty/seeded `score_with_gauntlet`
  block per variant. If it raises, skip that variant and increment `skipped`.

`CalibrationProof` gains `skipped: int = 0`. `honesty()` appends a coverage line whenever
`skipped > 0`: `"coverage: N item(s) skipped due to transient errors — cohorts are undercounted"`.
This keeps the report honest: a partial sweep is labeled partial, never presented as complete.

## Honesty

Resilience must not hide failures. A skipped item is counted and surfaced, never silently dropped, so
a reader always knows the sweep's coverage. Retries are bounded (no unbounded hang). None of this
changes any verdict: the calibration cohorts are still execution-decided; resilience only affects
whether the run *completes* and how honestly it reports partial coverage.

## Error handling

- Retry loops catch only transient classes; permanent errors (4xx, malformed schema, programming
  errors) propagate immediately. An exhausted retry budget re-raises the last transient error.
- The calibrate try/except catches broad `Exception` at the item boundary (a transient API error can
  surface as several SDK types), increments `skipped`, and continues. It never swallows a
  `KeyboardInterrupt`/`SystemExit`.

## Testing

- **A:** `_anthropic(RunConfig()).max_retries == 6`; a custom `llm_max_retries` is honored. (The
  Anthropic client constructs without a key; only calls need one.)
- **B:** an injected fake `http_client` that raises `httpx.ConnectError` on the first call then returns
  a valid response — `_post` retries and succeeds. A fake returning HTTP 400 — `_post` raises
  immediately with no retry. A fake that always times out — `_post` gives up after the attempt budget
  and re-raises.
- **C:** `run_calibration_proof` with a `scoring_for`/`mining_for` that raises for one goal — the proof
  completes, `skipped > 0`, the other goals' cohorts are still tallied, and `honesty()` shows the
  coverage line. A run with no failures has `skipped == 0` and no coverage line (unchanged output).

## Out of scope (YAGNI)

- Retrofitting retries onto the single-call CLI verbs.
- Checkpoint/resume of a partial sweep to disk (skip-and-continue is enough; a resumable sweep is a
  larger feature).
- Changing the Anthropic SDK's own backoff policy (we only set `max_retries`).

## Build order

Config knob + CLI helper (A) first, then the OpenRouter retry wrapper (B), then the calibrate
per-item tolerance + coverage reporting (C). Same review-before-push bar as the rest: full-suite gate
+ adversarial whole-branch review, fix, push only on greenlight.
