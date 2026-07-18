# Avow

**An autonomous build-and-improve loop that knows when not to trust itself.**

You hand Avow a goal. It writes a test suite, builds code until the tests pass, then — instead of declaring victory — it interrogates its own work: are the tests actually rigorous? Do they test the *right* goal? Does the solution hold up under fuzzing? It folds those signals into a single **calibrated confidence** and *flags or escalates a green it doesn't trust*.

The bet behind Avow: self-improving loops only work when something can objectively tell a good attempt from a bad one. For software there's no physics simulator — so Avow **synthesizes a verifier** out of execution-grounded signals and reports a confidence number, not a fake guarantee.

## Why this is different

Most "autonomous coder" demos stop at *the tests pass*. That's the easy 20%. The hard, valuable part is **trusting the result** — because a weak test suite, or a suite testing the wrong thing, makes "all green" a lie. Avow's whole design is the verification layer that turns "it passed" into "here's how much you should trust it, and why."

## The verification signals

| Signal | What it answers | How |
|---|---|---|
| **Behavioral** | Does it pass the suite? | the build loop converges to green |
| **Hold-out** | Did it overfit the visible tests? | a hidden split of the suite, with a hard floor |
| **Mutation** | Are the tests rigorous enough to catch bugs? | inject mutants, measure the kill rate |
| **Intent** | Do the tests test the *right* goal? | a different model reads the suite *blind*, restates the goal, compare |
| **Property** | Do invariants hold for *all* inputs? | Hypothesis property/metamorphic tests fuzzed during the build |
| **Reference oracle** | Does it match an *independent* implementation? | generate a simplest-correct reference; differential-test the solution against it on thousands of fuzzed inputs |
| **Adversarial escalation** | Can a QA adversary break it? | the Examiner reads the passing solution and writes harder tests targeting its weak spots; the suite battle-hardens over rounds (`avow harden`) |

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

Verification clients are injectable. To run a panel or other structured-output verifier across
providers, use `OpenRouterClient` with OpenRouter model IDs (the selected models must support
structured outputs):

```python
from avow.openrouter import OpenRouterClient
from avow.panel import panel_intent_check

client = OpenRouterClient()  # reads OPENROUTER_API_KEY
result = panel_intent_check(
    goal,
    tests_dir,
    client,
    ["google/gemini-2.5-flash", "anthropic/claude-sonnet-4.6"],
)
```

## CLI

```bash
avow solve <goal-dir>                       # the full loop: build → verify → confidence
avow improve <goal-dir>                     # self-improvement: converge, then propose & build the next feature, repeat
avow harden <goal-dir>                       # converge, then escalate: the Examiner writes harder tests targeting the solution, repeat
avow survive <goal-dir>                       # converge, then survive an execution gauntlet — one counterexample kills the green and it fights back
avow gauntlet <solution-dir> <goal.md>       # attack an existing solution once: K independent references vs it over a fuzzed input space
avow graveyard                               # list the global attack-pattern memory (what past deaths have taught Avow)
avow population <goal-dir> [--hybrid]        # run N candidate solutions; the verifier picks the winner (--hybrid escalates only on plateau)
avow mutate <solution-dir> <tests-dir>      # suite-strength score for any code (offline AST by default; --llm adds cross-model mutants)
avow intent-check <goal.md> <tests-dir>     # does this suite actually test this goal?
avow propertize <goal.md> <out-dir>         # generate Hypothesis property tests for a goal
avow oracle <solution-dir> <goal.md>        # differential-test a solution against an independent reference impl
avow supervise <run.jsonl> <goal.md>        # review a recorded run's trajectory; the Supervisor recommends continue/redirect/escalate
avow adjudicate <solution> <tests> <goal.md> # a stalled build: decide BY EXECUTION which failing tests are the Examiner's bug (run them vs K independent references)
avow check <solution-dir>                    # run the configured verifier checks (lint/typecheck/audit/...) on a solution
avow report <repo>                           # point-and-go: auto-detect a repo's code + tests and mutation-score its suite
avow calibrate [--llm]                       # measure whether the confidence number is trustworthy (reliability curve)
avow calibrate --gauntlet [--seed] [--llm]  # the survival-instinct proof: false-high-confidence for plain vs gauntlet-survived vs seeded-graveyard greens
avow verify <solution> <tests> <goal.md>    # one calibrated confidence number for any artifact
```

Beyond the pytest suite, a goal can require arbitrary **checks** — any command that exits 0 on pass (lint, typecheck, a security scan, a size/perf budget). Configure them in `avow.yaml`:

```yaml
checks:
  - name: lint
    command: ["ruff", "check", "."]
  - name: types
    command: ["python", "-m", "mypy", "lib.py"]
  - name: bundle-size          # a metric check: pass iff the parsed number is within bounds
    command: ["wc", "-c", "dist/app.js"]
    max: 500000
  - name: coverage
    command: ["coverage", "report", "--format=total"]
    min: 90
strip_check_config: false      # opt-in anti-cheat (see below)
```

During `avow solve`, checks fold into the grade alongside the tests: the run is green only when the suite passes **and** every check passes, and a failing check feeds the Builder exactly like a failing test — so it iterates to fix lint/type/budget errors too. More verifier *types* → more product *types* Avow can drive to perfect. `avow check` runs them standalone.

- **Exit-code checks** pass iff the command exits 0. **Metric checks** (a check carrying `max` and/or `min`) require the command to succeed, then parse a number from its **stdout** — the last numeric token by default (thousands separators and scientific notation handled), or a `pattern` regex for non-trivial output — and pass iff it's within bounds (inclusive). That covers size/coverage/latency/complexity budgets, not just pass/fail gates.
- **Anti-cheat:** checks run on the solution dir, so by default they're a weaker anti-cheat than the hidden pytest suite (visible to a reviewer, but a Builder could loosen a check's own tool-config). Set `strip_check_config: true` to run each check in an ephemeral copy with builder-authorable config (`.ruff.toml`, `mypy.ini`, `.flake8`, …) stripped, so a check can't be silenced by loosened config. (`pyproject.toml` is deliberately preserved — it can hold real dependencies.)

When a build stalls just short of green, `avow adjudicate` answers *"is this failing test the solution's bug or the Examiner's?"* by generating K independent reference implementations and **running each failing test against all of them** — if the independent correct implementations also fail it, the test contradicts correctness (a `TEST BUG`); if they pass it, the solution is the outlier. The verdict is decided by execution, not by an LLM's opinion. It's advisory (never auto-edits a test) and available in-loop via the opt-in `adjudicate_enabled`.

`avow improve` runs the two-phase loop: converge on the goal, then an **Ideator** proposes the next improvement (each with a verifier and a risk label), a **leash** auto-pursues objective low-risk ideas (and escalates the rest), the chosen idea joins the verifier — as a **test** the Examiner writes, or, when the idea is a standing quality **gate** (`kind: "check"`), as a new entry in `config.checks` — and the loop re-converges, bounded by a round cap. So Avow widens its own verifier menu as it self-improves.

`avow survive` is the survival instinct. After a green, it throws the solution into an **execution gauntlet**: K independently generated reference implementations, differential-fuzzed against it over a large input space. If a *majority* of references diverge on any input, the solution is the outlier and the green is **killed** — the winning reference's differential test is frozen into the suite, the Builder rebuilds, and it faces a fresh gauntlet. It keeps fighting until it survives a full gauntlet clean (`verified_survivor`) or dies honestly at the round cap (`died`, with the exact counterexample). The kill is decided by *execution* against a reference majority, never by opinion, and `verified_survivor` means "survived a K-reference execution gauntlet," not "provably correct." `avow gauntlet` runs one attack on an existing artifact. Ships dormant.

Avow also gets **harder to fool over time**. Every kill is sent to a **Coroner**, which abstracts the concrete counterexample into a transferable *attack pattern* (a class of tricky inputs, not the one literal case), stored in a global **Graveyard** (`~/.avow/graveyard.jsonl`, deduped). Future gauntlets are seeded from it: for a new goal, `avow survive` retrieves the patterns most *relevant* to that goal by keyword overlap (not just the most recent) and steers reference generation to probe those known-tricky input classes. The autopsy is strictly best-effort, so it can never change or crash the execution-decided verdict. `avow graveyard` lists what it has learned. This is a lexical heuristic, not semantic retrieval; it improves on recency without pretending to understand meaning.

That memory arms the *attacker*. Avow also arms the *defender*: within a single `avow survive` run, each kill's abstract lesson is accumulated into an ephemeral **lineage memory** and handed to the Builder on the rebuild, so the heir inherits *why its predecessors died* and steers away from the whole failure class, not just the one input the frozen test already blocks. The inherited lesson is abstract only (the failure class and its description, never the reference implementation or a concrete input), preserving the rule that the Builder never sees tests or references. It is guidance, not a guarantee: the frozen regression test remains the mechanical backstop.

`avow report <repo>` is the point-and-go entry point: aim it at an existing repository and it auto-detects the source modules (including code nested in packages) and the test suite, confirms the suite is green, mutation-tests the real code, and prints the suite-strength score with the surviving mutants pinned to `file:line` (the faults no test caught). No goal file, no flat-module layout, no configuration. If the suite isn't green on the unmutated repo, it reports *why* (the actual pytest failure with a hint — a missing import means `pip install -e .` first; a `src/` layout means point `--source` at the package) rather than a meaningless number. When auto-detection guesses wrong, override it: `avow report <repo> --source src/mypkg --tests tests` (both repeatable).

`avow calibrate` measures whether the confidence number can be *trusted*. It runs a labeled benchmark (goals with a correct reference, injected-bug variants, and an independent oracle for ground truth), scores every variant with the real verifier, and reports the reliability curve plus the **false-high-confidence rate** — the fraction of "trusted" solutions that are actually wrong. Run it whenever the confidence path changes. It's what proved that suite-derived signals alone (mutation + hold-out) miss green-but-wrong solutions whose bugs live in the suite's blind spots, and that folding in the suite-independent reference oracle drives false-high-confidence toward zero — which is why `avow solve` runs the oracle by default.

`avow calibrate --gauntlet` extends that into the survival-instinct proof: it scores the benchmark across three cohorts (plain green, gauntlet-survived with an empty graveyard, and survived with a graveyard **seeded** leave-one-out from *other* goals' deaths) and compares their false-high-confidence. The seeding is leave-one-out with a provenance leakage guard, so a pattern mined from the goal being scored can never inflate its own result. The report is deliberately honest: it prints raw `wrong/trusted (n=...)` counts and refuses to state an "N times less likely" multiplier unless the sample is large enough. Without `--llm` it runs a deterministic stub that demonstrates the mechanism with no API key (labeled `STUB MODE`); with `--llm` it produces real numbers from a single labeled run.

A goal directory holds a `goal.md` (and, optionally, a `avow.yaml` to tune budgets/weights). `avow solve` writes the suite, runs the loop, and reports the verdict plus the confidence breakdown.

```
$ avow solve ./my-goal
result: success=True reason=green score=1.00 iterations=1
confidence: 1.00
  holdout: 1.00
  mutation: 1.00
best solution: ./my-goal/.avow/best
```

## What it is — and isn't

Avow is a **verifiable-domain solver**: its usefulness scales with how cheaply correctness can be *checked by execution* (code with clear I/O, algorithms, transforms, parsers). It is **not** a universal agent — it can't autonomously achieve fuzzy real-world outcomes (revenue, "make it good") because those have no sandbox verifier. It earns its keep on tasks that are both verifiable and tedious enough that looping beats hand-coding.

## Configuration (`avow.yaml`)

Budgets (`max_iterations`, `max_cost_usd`, `max_wall_seconds`, timeouts), models per role, hold-out fraction and floor, confidence threshold and per-signal weights, and which verification hooks are enabled — all tunable. See `avow/config.py` for the full set and defaults.

## Design docs

Architecture and per-feature specs/plans live in `docs/specs/` and `docs/plans/`.

## Status

**All five verification layers of the design are built**: execution-grounded checks (property + reference-oracle), decorrelated judges (cross-model panel + adversarial-escalating Examiner), test-the-tests (mutation + hold-out), intent triangulation (back-translation), and calibrated confidence (aggregation + hold-out/panel/oracle floors) — plus the self-improvement *expand phase* (`avow improve`) and adversarial hardening (`avow harden`). It also ships **Population / Hybrid search** (`avow population` — run N candidate solutions *concurrently* (capped by `max_parallel_candidates`), the verifier picks the winner; `--hybrid` escalates only on plateau) and the **Supervisor** (`avow supervise` / opt-in `supervisor_enabled` — an event-triggered trajectory guardian that judges a plateauing run and recommends redirect/escalate; never enforces). All four agents of the design (Builder · Examiner · Ideator · Supervisor) are built, and the **full moat is proven end-to-end against live Claude** (Examiner-written suite + property fuzzing + the 3-model intent panel + mutation + confidence). Roadmap: true cross-provider panels, learned signal weights, parallel candidate execution.
