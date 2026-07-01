# Hermit

**An autonomous build-and-improve loop that knows when not to trust itself.**

You hand Hermit a goal. It writes a test suite, builds code until the tests pass, then — instead of declaring victory — it interrogates its own work: are the tests actually rigorous? Do they test the *right* goal? Does the solution hold up under fuzzing? It folds those signals into a single **calibrated confidence** and *flags or escalates a green it doesn't trust*.

The bet behind Hermit: self-improving loops only work when something can objectively tell a good attempt from a bad one. For software there's no physics simulator — so Hermit **synthesizes a verifier** out of execution-grounded signals and reports a confidence number, not a fake guarantee.

## Why this is different

Most "autonomous coder" demos stop at *the tests pass*. That's the easy 20%. The hard, valuable part is **trusting the result** — because a weak test suite, or a suite testing the wrong thing, makes "all green" a lie. Hermit's whole design is the verification layer that turns "it passed" into "here's how much you should trust it, and why."

## The verification signals

| Signal | What it answers | How |
|---|---|---|
| **Behavioral** | Does it pass the suite? | the build loop converges to green |
| **Hold-out** | Did it overfit the visible tests? | a hidden split of the suite, with a hard floor |
| **Mutation** | Are the tests rigorous enough to catch bugs? | inject mutants, measure the kill rate |
| **Intent** | Do the tests test the *right* goal? | a different model reads the suite *blind*, restates the goal, compare |
| **Property** | Do invariants hold for *all* inputs? | Hypothesis property/metamorphic tests fuzzed during the build |
| **Reference oracle** | Does it match an *independent* implementation? | generate a simplest-correct reference; differential-test the solution against it on thousands of fuzzed inputs |
| **Adversarial escalation** | Can a QA adversary break it? | the Examiner reads the passing solution and writes harder tests targeting its weak spots; the suite battle-hardens over rounds (`hermit harden`) |

> Behavioral-green is the precondition (not a confidence input); property tests are folded into the frozen suite (they raise the bar for *green* and *mutation* rather than appearing as a separate number). The aggregated confidence breakdown is **hold-out + mutation + intent + reference-oracle** — each included only when it ran. Hold-out, panel-agreement, and oracle-disagreement each act as a hard floor (a breach forces `low_confidence` regardless of the average).

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
hermit solve <goal-dir>                       # the full loop: build → verify → confidence
hermit improve <goal-dir>                     # self-improvement: converge, then propose & build the next feature, repeat
hermit harden <goal-dir>                       # converge, then escalate: the Examiner writes harder tests targeting the solution, repeat
hermit population <goal-dir> [--hybrid]        # run N candidate solutions; the verifier picks the winner (--hybrid escalates only on plateau)
hermit mutate <solution-dir> <tests-dir>      # suite-strength score for any code (offline AST by default; --llm adds cross-model mutants)
hermit intent-check <goal.md> <tests-dir>     # does this suite actually test this goal?
hermit propertize <goal.md> <out-dir>         # generate Hypothesis property tests for a goal
hermit oracle <solution-dir> <goal.md>        # differential-test a solution against an independent reference impl
hermit supervise <run.jsonl> <goal.md>        # review a recorded run's trajectory; the Supervisor recommends continue/redirect/escalate
hermit adjudicate <solution> <tests> <goal.md> # a stalled build: decide BY EXECUTION which failing tests are the Examiner's bug (run them vs K independent references)
hermit check <solution-dir>                    # run the configured verifier checks (lint/typecheck/audit/...) on a solution
hermit verify <solution> <tests> <goal.md>    # one calibrated confidence number for any artifact
```

Beyond the pytest suite, a goal can require arbitrary **checks** — any command that exits 0 on pass (lint, typecheck, a security scan, a size/perf budget). Configure them in `hermit.yaml`:

```yaml
checks:
  - name: lint
    command: ["ruff", "check", "."]
  - name: types
    command: ["python", "-m", "mypy", "lib.py"]
```

During `hermit solve`, checks fold into the grade alongside the tests: the run is green only when the suite passes **and** every check exits 0, and a failing check feeds the Builder exactly like a failing test — so it iterates to fix lint/type/audit errors too. More verifier *types* → more product *types* Hermit can drive to perfect. `hermit check` runs them standalone. (Checks run on the solution dir, so they're a weaker anti-cheat than the hidden pytest suite — visible to a reviewer, not gameable in secret.)

When a build stalls just short of green, `hermit adjudicate` answers *"is this failing test the solution's bug or the Examiner's?"* by generating K independent reference implementations and **running each failing test against all of them** — if the independent correct implementations also fail it, the test contradicts correctness (a `TEST BUG`); if they pass it, the solution is the outlier. The verdict is decided by execution, not by an LLM's opinion. It's advisory (never auto-edits a test) and available in-loop via the opt-in `adjudicate_enabled`.

`hermit improve` runs the two-phase loop: converge on the goal, then an **Ideator** proposes the next feature (each with a verifier and a risk label), a **leash** auto-pursues objective low-risk ideas (and escalates the rest), the chosen idea's test joins the suite, and the loop re-converges — bounded by a round cap.

A goal directory holds a `goal.md` (and, optionally, a `hermit.yaml` to tune budgets/weights). `hermit solve` writes the suite, runs the loop, and reports the verdict plus the confidence breakdown.

```
$ hermit solve ./my-goal
result: success=True reason=green score=1.00 iterations=1
confidence: 1.00
  holdout: 1.00
  mutation: 1.00
best solution: ./my-goal/.hermit/best
```

## What it is — and isn't

Hermit is a **verifiable-domain solver**: its usefulness scales with how cheaply correctness can be *checked by execution* (code with clear I/O, algorithms, transforms, parsers). It is **not** a universal agent — it can't autonomously achieve fuzzy real-world outcomes (revenue, "make it good") because those have no sandbox verifier. It earns its keep on tasks that are both verifiable and tedious enough that looping beats hand-coding.

## Configuration (`hermit.yaml`)

Budgets (`max_iterations`, `max_cost_usd`, `max_wall_seconds`, timeouts), models per role, hold-out fraction and floor, confidence threshold and per-signal weights, and which verification hooks are enabled — all tunable. See `hermit/config.py` for the full set and defaults.

## Design docs

Architecture and per-feature specs/plans live in `docs/specs/` and `docs/plans/`.

## Status

**All five verification layers of the design are built**: execution-grounded checks (property + reference-oracle), decorrelated judges (cross-model panel + adversarial-escalating Examiner), test-the-tests (mutation + hold-out), intent triangulation (back-translation), and calibrated confidence (aggregation + hold-out/panel/oracle floors) — plus the self-improvement *expand phase* (`hermit improve`) and adversarial hardening (`hermit harden`). It also ships **Population / Hybrid search** (`hermit population` — run N candidate solutions *concurrently* (capped by `max_parallel_candidates`), the verifier picks the winner; `--hybrid` escalates only on plateau) and the **Supervisor** (`hermit supervise` / opt-in `supervisor_enabled` — an event-triggered trajectory guardian that judges a plateauing run and recommends redirect/escalate; never enforces). All four agents of the design (Builder · Examiner · Ideator · Supervisor) are built, and the **full moat is proven end-to-end against live Claude** (Examiner-written suite + property fuzzing + the 3-model intent panel + mutation + confidence). Roadmap: true cross-provider panels, learned signal weights, parallel candidate execution.
