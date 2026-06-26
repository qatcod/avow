# Forge

**An autonomous build-and-improve loop that knows when not to trust itself.**

You hand Forge a goal. It writes a test suite, builds code until the tests pass, then — instead of declaring victory — it interrogates its own work: are the tests actually rigorous? Do they test the *right* goal? Does the solution hold up under fuzzing? It folds those signals into a single **calibrated confidence** and *flags or escalates a green it doesn't trust*.

The bet behind Forge: self-improving loops only work when something can objectively tell a good attempt from a bad one. For software there's no physics simulator — so Forge **synthesizes a verifier** out of execution-grounded signals and reports a confidence number, not a fake guarantee.

## Why this is different

Most "autonomous coder" demos stop at *the tests pass*. That's the easy 20%. The hard, valuable part is **trusting the result** — because a weak test suite, or a suite testing the wrong thing, makes "all green" a lie. Forge's whole design is the verification layer that turns "it passed" into "here's how much you should trust it, and why."

## The verification signals

| Signal | What it answers | How |
|---|---|---|
| **Behavioral** | Does it pass the suite? | the build loop converges to green |
| **Hold-out** | Did it overfit the visible tests? | a hidden split of the suite, with a hard floor |
| **Mutation** | Are the tests rigorous enough to catch bugs? | inject mutants, measure the kill rate |
| **Intent** | Do the tests test the *right* goal? | a different model reads the suite *blind*, restates the goal, compare |
| **Property** | Do invariants hold for *all* inputs? | Hypothesis property/metamorphic tests fuzzed during the build |

> Behavioral-green is the precondition (not a confidence input); property tests are folded into the frozen suite (they raise the bar for *green* and *mutation* rather than appearing as a separate number). The aggregated confidence breakdown is **hold-out + mutation + intent**.

These combine into a **calibrated confidence** with a transparent per-signal breakdown. `done = green ∧ confidence ≥ threshold`; below it, the run is flagged `low_confidence` or escalated to a human.

## Anti-cheat & honesty (load-bearing)

- **The builder never sees the tests.** They're graded in an ephemeral copy and never enter the builder's workspace, so it can't hard-code to them.
- **Enforcement is deterministic code, never an agent.** Budget caps, the non-regression gate, the confidence floor, stop conditions — none of these are an LLM that could hallucinate. You can't fix "AIs hallucinate" by adding an AI to watch them.
- **Confidence is a calibrated signal, not certainty.** Two of its inputs are LLM-judged; the breakdown is always surfaced so the verdict is auditable. A `low_confidence` result is the system telling you it doesn't trust its own green — the most valuable thing it produces.

## Install

```bash
pip install -e ".[dev]"          # Python 3.11+
```

The builder drives the [`claude`](https://claude.com/claude-code) CLI (uses its login); the verification hooks use the `anthropic` SDK (`ANTHROPIC_API_KEY`).

## CLI

```bash
forge solve <goal-dir>                       # the full loop: build → verify → confidence
forge improve <goal-dir>                     # self-improvement: converge, then propose & build the next feature, repeat
forge mutate <solution-dir> <tests-dir>      # suite-strength score for any code (offline AST by default; --llm adds cross-model mutants)
forge intent-check <goal.md> <tests-dir>     # does this suite actually test this goal?
forge propertize <goal.md> <out-dir>         # generate Hypothesis property tests for a goal
forge verify <solution> <tests> <goal.md>    # one calibrated confidence number for any artifact
```

`forge improve` runs the two-phase loop: converge on the goal, then an **Ideator** proposes the next feature (each with a verifier and a risk label), a **leash** auto-pursues objective low-risk ideas (and escalates the rest), the chosen idea's test joins the suite, and the loop re-converges — bounded by a round cap.

A goal directory holds a `goal.md` (and, optionally, a `forge.yaml` to tune budgets/weights). `forge solve` writes the suite, runs the loop, and reports the verdict plus the confidence breakdown.

```
$ forge solve ./my-goal
result: success=True reason=green score=1.00 iterations=1
confidence: 1.00
  holdout: 1.00
  mutation: 1.00
best solution: ./my-goal/.forge/best
```

## What it is — and isn't

Forge is a **verifiable-domain solver**: its usefulness scales with how cheaply correctness can be *checked by execution* (code with clear I/O, algorithms, transforms, parsers). It is **not** a universal agent — it can't autonomously achieve fuzzy real-world outcomes (revenue, "make it good") because those have no sandbox verifier. It earns its keep on tasks that are both verifiable and tedious enough that looping beats hand-coding.

## Configuration (`forge.yaml`)

Budgets (`max_iterations`, `max_cost_usd`, `max_wall_seconds`, timeouts), models per role, hold-out fraction and floor, confidence threshold and per-signal weights, and which verification hooks are enabled — all tunable. See `forge/config.py` for the full set and defaults.

## Design docs

Architecture and per-feature specs/plans live in `docs/specs/` and `docs/plans/`.

## Status

Built and internally verified: the converge loop, mutation testing, back-translation/intent with a cross-model judgment panel (consensus + agreement floor), confidence aggregation with a hold-out floor, property generation, and the self-improvement *expand phase* (`forge improve`). The core loop is proven end-to-end against live Claude. Roadmap: the Supervisor (event-triggered trajectory guardian), true cross-provider panels, learned signal weights, reference-oracle differential testing.
