# Avow — Autonomous Build-and-Improve Loop — Design Spec

**Status:** Approved (brainstorming, 2026-06-26)
**Working name:** Avow (rename freely)

## Goal

You hand Avow a goal. It autonomously writes code, has a *separate* adversarial QA agent test it against a frozen suite, reads its own failures and fixes them in a loop until the suite is green — then proposes its *own* next features/improvements, grounds each in a new verifier, and keeps going, until a hard budget or you stop it.

## The core insight (why this works at all)

Self-improving loops (AlphaEvolve, chip-design agents) work because of **one** thing: a fast, automatic, objective **verifier** that scores each attempt without a human and without the real world. The "thinking" is not the engine — the verifier is. Remove it and the loop has nothing to climb toward.

So Avow's job is to **synthesize a trustworthy verifier** for software goals, where no physics simulator exists.

## Scope

**In (v1):** goals with an automatic verifier — "build a tool/library/script that makes these tests pass." The loop genuinely closes by itself.

**Out (documented roadmap, NOT built):** real-world business outcomes (e.g. "$10K MRR Shopify store"). Those have no sandbox verifier; they require a human/market round and are a later strategy, not core scope. Avow can autonomously *build* such a system; it cannot autonomously *verify* the business outcome.

## The honest position on verification

You cannot reach **certainty** without ground truth (a human or a simulator). With two AI agents alone, "all tests pass" means "two AIs agreed," not "the goal was met." Avow does **not** pretend otherwise. Instead it drives the probability that *agreement ≈ correctness* as high as possible and **reports a calibrated confidence**, escalating to a human only at measured uncertainty. The verifier is treated as the product's hard part and its moat.

## Architecture

```
  ┌──────────────────────────── OUTER LOOP (Python, deterministic) ───────────────────────────┐
  │                                                                                            │
  │   ╔═══ CONVERGE ═══╗     suite green / plateau      ╔═══ EXPAND ═══╗                        │
  │   ║ build→test→fix ║ ──────────────────────────────▶║ ideator picks ║                       │
  │   ║ until green    ║                                 ║ next feature  ║                       │
  │   ╚════════╤═══════╝                                 ║ + a verifier  ║                       │
  │            ▲              examiner writes its test    ╚══════╤═══════╝                       │
  │            └────────────────── suite grows ◀─────────── leash gate ◀──┘                      │
  │                                                                                            │
  └── stops on: budget ($/tokens/time) · max iterations/expand rounds · "no valuable idea" ────┘
```

### Agents (LLM, judgment) — each one job

| Agent | Job | When it runs |
|---|---|---|
| **Builder** | write/edit code from (goal, current code, last failures); never sees the tests | every converge iteration |
| **Examiner / QA** | write *adversarial* acceptance tests from the goal; gets stricter over rounds | start of each phase (cross-model by default) |
| **Ideator** | propose next feature/improvement, each paired with a proposed verifier; self-labels risk | *between* goals (expand phase) |
| **Supervisor** | judge trajectory → redirect / change strategy / escalate; never enforces | *within* a goal, only when a trouble-signal fires |

### Deterministic floor (code — cannot hallucinate)

Outer loop · frozen-suite enforcement · non-regression gate · budget caps · stop conditions · signal/plateau detection · memory log. **Enforcement lives here, never in an agent.** You cannot fix "AIs hallucinate" by adding an AI to watch them — the floor must be code.

### The swappable seam

```
Strategy.run(goal, frozen_tests, builder, runner, scorer, memory, budget) -> Result
```
v1 ships `IterativeStrategy`. Population (many-ideas-in-parallel) and Hybrid (escalate on plateau) implement the **same signature** — config swaps, not rewrites.

## Verification subsystem (the moat)

Five layers, in order of power. v1 ships layers I + III (hold-out); II/IV/V are the v2 "verification hardening."

- **I. Ground checks in execution, not judgment.** Property/metamorphic tests (assert laws that hold for *all* inputs — `decompress(compress(x))==x` — no reference answer needed) + reference-oracle-by-simplicity (dumb-but-correct slow version the clever version must match on thousands of random inputs).
- **II. Decorrelate + weaponize judges.** Cross-family model panel for judgment checks; consensus required, disagreement = uncertainty; adversarial framing (Examiner rewarded for *breaking* the Builder); independent re-derivation.
- **III. Test the tests.** Mutation testing (inject bugs, confirm suite catches them — measures verifier rigor in execution) + hold-out split (Builder converges on visible tests; hidden set catches overfitting/gaming).
- **IV. Triangulate intent.** Back-translation: a third model reads the suite, restates the goal, compare to the original — catches "Examiner misread the goal" before burning budget.
- **V. Calibrated confidence.** Aggregate behavioral pass rate + property coverage + mutation score + hold-out rate + panel agreement + back-translation match → a single **verification confidence**. "Done" = confidence ≥ threshold. The system *knows when it doesn't know*; that's when the optional human glance is spent.

## Two load-bearing anti-cheat rules

1. **Builder never sees or writes the tests.** Test files live outside the Builder's worktree and are restored fresh before every test run, so the Builder physically cannot read or tamper with them — it only ever receives the runner's pass/fail + failure messages.
2. **No idea enters the build loop without a verifier.** "Improve" only counts when measurable. The suite is **frozen within a converge phase** (un-gameable) but **grows across expand phases** (open-ended). Metric tests (faster/smaller/cheaper) give a continuous axis to climb forever.

## The leash (expansion autonomy)

Each Ideator idea carries `(proposed_verifier, risk_label)`. Then:
- **Auto-pursue** if the verifier is **objective** (behavioral or metric test) **and** `risk_label == low`.
- **Pause for human approval** if the verifier is qualitative/"needs human judgment", **or** `risk_label == high` (deletes passing behavior, changes a public interface, or adds an external dependency).

## Stops & safety

Converge ends on: green / max_iterations / plateau-N / budget. The run ends on: budget exhausted / max_expand_rounds / Ideator returns "nothing valuable left" / optional top-level "north star" met. **Hard budget cap (tokens / $ / wall-clock) means the loop physically cannot run away.**

## Observability ("watch it think")

Live console + `run.jsonl`: per iteration → number, score, one-line diff summary, failing tests, the agent's stated plan, tokens/cost. Runs are **reproducible** (log full prompts/inputs) and **resumable** (checkpoint best-so-far) so a crash at iteration 40 doesn't burn the whole run. Observability is a v1 feature, not an afterthought.

## Tech stack

- Python 3.11+ (target 3.12 to match the local venv).
- **Builder** = headless `claude -p --output-format json` subprocess (full coder for free; uses existing Claude Code auth; version-stable; runs with `cwd` = the attempt's git worktree). The Claude Agent SDK is a documented drop-in alternative behind the same `Builder` interface.
- **Examiner / Ideator / Supervisor** = `anthropic` Python SDK with **structured outputs** (`messages.parse` + Pydantic). Default model `claude-opus-4-8`; configurable per agent; Examiner defaults to a *different* model from the Builder for decorrelated blind spots; cheaper sub-agents may use `claude-sonnet-4-6` / `claude-haiku-4-5`.
- `pytest` + `pytest-json-report` as the default runner (configurable command → structured JSON the scorer parses).
- `git worktree` for per-attempt sandboxing.
- `pydantic` (config + schemas), `pyyaml` (run config).

## Phased build order (designed whole, built in slices)

The full system above is the target. We build the smallest slice that proves the loop, then *earn* each later slice when v1 shows we need it.

- **v1 — Skeleton (this plan's scope).** Builder (subprocess) + Examiner (behavioral + property tests, human-approved once) + Runner (worktree + pytest) + Scorer (% passing) + Budget + Memory/log + CLI + `IterativeStrategy`. Hold-out split included (cheap, high-value). Single-solution converge loop only. **Deliverable: a working tool you point at a goal dir and watch close the loop.**
- **v2 — Verification hardening.** Mutation testing, cross-model panel, back-translation, confidence aggregation. (The moat + the sellable "mutation-tested test-suite generator" spin-out.)
- **v3 — Expand phase.** Ideator + the converge/expand two-phase loop + the leash.
- **v4 — Supervisor + strategies.** Event-triggered Supervisor; Population/Hybrid strategies behind the existing seam.

## Positioning (market)

The orchestration loop is commodity (Devin/OpenHands/SWE-agent/Cursor). The moat is the **verification/confidence layer** — *trustworthy* autonomy is rare. **Open-core:** open-source the loop (reputation/adoption), monetize the verification layer, hosted runs, and team features. The immediately-sellable wedge that falls out of the same machinery: point the verification subsystem at an existing repo → a **mutation-tested, hold-out-validated test suite + confidence report**, sidestepping the crowded "autonomous coder" fight.

## Known risks (eyes open)

- **Verifier weakness fails silently** (weak tests → green → confident garbage). Mitigated by layers III–V; never fully eliminated without a human/simulator.
- **It's a verifiable-domain solver, not universal.** Usefulness ∝ how cheaply correctness is checkable for *this* goal. Pick targets inside that envelope.
- **Cost.** Multi-agent loops burn tokens; the budget cap is the primary economic control. For many tasks a skilled dev is cheaper by hand — Avow earns its keep on tasks that are *both* verifiable *and* tedious/large.
- **Plateaus / local optima.** A relentless optimizer, not a creative one. Expect it to crush well-scoped verifiable tasks and to spin on conceptual leaps.
- **Agent proliferation is the project's own biggest risk.** Order of resort: can a rule do it? → can an existing agent's prompt do it? → only then a new agent. The best version is the smallest one that works.
