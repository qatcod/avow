# Avow — Lineage Memory (the defender's inherited death-knowledge) — design

A refinement of the survival instinct. When the gauntlet kills a solution, the rebuild (its "heir")
should inherit an accumulating memory of *why its predecessors died and what failure classes to
avoid* — not start amnesiac. This is the defender-side twin of the Graveyard.

## The gap it fills

The Coroner already abstracts every death into a transferable lesson (an `AttackPattern`: a failure
`category` + a `description` of the class of input that fooled the solution). Today that lesson flows
in only ONE direction:

- **Attacker (has memory):** the lesson is recorded to the global Graveyard, which seeds future
  gauntlets so the *attacker* comes back and probes that failure class harder.
- **Defender (amnesiac):** the Builder rebuilding the heir receives none of it. It inherits a frozen
  differential *test* (the mechanical tombstone that blocks the exact input) and re-derives from raw
  pytest output what went wrong. It never sees the Coroner's actual lesson.

Lineage memory closes that asymmetry: the same Coroner abstraction that arms the attacker also arms
the defender. Same lesson, second consumer.

## What it is NOT (scope honesty)

The frozen differential test already prevents the heir from repeating the *exact* death (input X goes
red instantly). So lineage memory is not about re-blocking the instance. Its value is proactive
avoidance of the *class*: dying on X in round 0, then X' (same class, new input) in round 1, then X''
in round 2 is the whack-a-mole the frozen tests do not stop. Lineage memory earns its keep only if it
helps the Builder generalize away from the failure class and converge faster / more robustly. It is
**guidance, not a guarantee** — the frozen test remains the mechanical guarantee.

## Design

### Ephemeral per-run ledger in `survive`

`survive` maintains an in-memory list `deaths: list[AttackPattern]` across its fight-back rounds. After
each kill's Coroner abstraction (the `pat` already computed for the Graveyard), if `pat` is not None it
is appended to `deaths` in addition to being recorded to the Graveyard — one Coroner call feeds both,
no extra LLM cost. The ledger accumulates: the heir inherits round 0's death; the grandchild inherits
rounds 0 and 1; and so on.

This is **ephemeral** — one `survive` invocation's bloodline. It is NOT persisted; the global Graveyard
already handles cross-run persistence. Building a second store would be a worse-scoped duplicate.

### Abstract-only guidance (the load-bearing anti-cheat constraint)

Before each rebuild, `deaths` is formatted into a Builder-facing guidance block containing ONLY each
pattern's `category` and `description`:

```
LESSONS FROM 2 PRIOR ATTEMPT(S) ON THIS GOAL THAT WERE KILLED (do not reintroduce these failure classes):
  - [numeric-boundary] a shorter numeric field compared against a longer one was mishandled
  - [empty-input] the zero-length case returned a value instead of raising
```

It MUST NEVER contain `counterexample.reference_code`, the differential test, the expected output, or
the literal falsifying input. The Builder is never allowed to see tests or references; lineage memory
passes *lessons, not answers*. Because the Coroner's `description` is already an abstract strategy and
nothing more, this is safe by construction as long as the formatter reads only `category`/`description`.

### Injection via the existing Builder-guidance seam

`solve()` gains one optional keyword param `builder_guidance: str = ""`. The loop already builds each
attempt's goal at one place (combining `goal` with the Supervisor's `redirect` hint); it is extended to
fold in `builder_guidance` too, coexisting with the supervisor hint:

```python
base_goal = goal if not builder_guidance else f"{goal}\n\n{builder_guidance}"
attempt_goal = base_goal if supervisor_hint is None else f"{base_goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"
```

`survive` passes `builder_guidance=<formatted deaths>` on the rebuild `solve(..., write_tests=False)`
call. The initial converge has no prior deaths, so it passes nothing (behavior unchanged).

## Error handling

Lineage accumulates only when a Coroner client is present (same condition as Graveyard recording); with
no Coroner, `deaths` stays empty, no guidance is produced, and behavior is identical to today. The
formatting is pure string work over already-validated `AttackPattern` fields — it cannot raise on a
normal ledger and never touches the verdict. Same best-effort posture as the rest of the autopsy path.

## Honesty

The feature is a build-time nudge, not a guarantee. No output may claim it "prevents" deaths — the
frozen regression test is what prevents repeats; lineage memory only steers the rebuild away from the
failure class. Naming and comments say "guidance" / "lessons," never "enforced."

## Testing

- `solve(builder_guidance=...)`: a capturing Builder records the attempt goal it received; assert the
  guidance text appears in it, and that an empty `builder_guidance` leaves the goal unchanged.
- `survive` accumulates across rounds: with a stubbed Coroner and a gauntlet that kills round 0 then
  lets round 1 survive, assert the round-1 rebuild's `builder_guidance` contains round 0's death class,
  and that a two-kill run's final rebuild contains BOTH classes in order.
- Abstract-only: assert the guidance string contains the pattern `category`/`description` but NOT the
  counterexample's `reference_code` or diff-test text (anti-cheat regression).
- No Coroner: `deaths` stays empty, rebuild `builder_guidance` is empty, verdict unchanged.

## Out of scope (YAGNI)

- Persisting lineage across runs (the Graveyard already does cross-run memory).
- Including the concrete falsifying input in the lesson (abstract-only chosen deliberately; the frozen
  test already carries the instance).
- Any change to the Graveyard, the Coroner, or the calibration proof (C).

## Build order

`solve`/loop `builder_guidance` injection + its test first (the seam), then `survive` accumulation +
abstract-only formatting + its tests. Same review-before-push bar as A/B/C and relevance: full-suite
gate + adversarial whole-branch review, fix, then push only on greenlight.
