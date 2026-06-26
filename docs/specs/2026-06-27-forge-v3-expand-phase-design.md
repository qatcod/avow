# Forge v3 — The Expand Phase (Ideator + Self-Improvement Loop) — Design Spec

**Status:** Approved (derives from the original [Forge design spec](2026-06-26-forge-design.md) — the converge/expand two-phase loop, the Ideator, and the leash were designed and approved at the start; this implements that part now that the verification moat is built).

## Goal

Turn the one-shot converge loop into a **two-phase self-improving loop**. After Forge converges (green + confidence) on the initial goal, an **Ideator** proposes its own next feature/improvement; the chosen idea is turned into a verifier (a test), folded into the suite, and the loop **re-converges**. Repeat until budget / round cap / "no valuable idea" / the leash stops it. This is the "think of an idea → build → fix → think of *another* idea → again and again" the project set out to do.

## The two-phase loop

```
  CONVERGE (build → test → fix → confidence)  ──green──▶  EXPAND (Ideator proposes next feature)
          ▲                                                          │
          └──────────── suite grows (Examiner writes its test) ◀──── leash gate
   stops on: converge fails (not green) · max_expand_rounds · "no valuable idea" · leash rejects
```

The suite is **frozen within a converge phase** (un-gameable) but **grows across expand phases** — exactly the original anti-cheat rule. Each expand round adds the chosen idea's acceptance test, so the builder must keep satisfying everything as the spec grows.

## Components

`forge/ideator.py`:

| Unit | Job |
|---|---|
| `Idea(description: str, verifier: str, objective: bool, risk: str)` | a proposed next feature/improvement + how to verify it + whether the verifier is objective + a `"low"`/`"high"` risk label |
| `_IdeaSet(BaseModel)` with `ideas: list[Idea]` | structured-output schema (ranked, best first) |
| `propose_ideas(goal, current_tests, client, model, n) -> tuple[list[Idea], int, int]` | LLM reads the goal + what's already tested → up to `n` ranked next ideas + token usage; `([], 0, 0)` for `n<=0`/`client is None` |
| `select_idea(ideas, escalate) -> tuple[Idea \| None, bool]` | **the leash** (pure): take the top idea; if `objective and risk == "low"` → auto-pursue `(idea, False)`; else call `escalate(idea)` — accepted → `(idea, True)`, rejected/no-callback → `(None, True)`. Empty list → `(None, False)`. |

`forge/improve.py`:

| Unit | Job |
|---|---|
| `ImproveResult(success, expansions, rounds, final)` | overall verdict, number of expand rounds done, per-round `SolveResult`s, the final `SolveResult` |
| `improve(goal_dir, config, examiner, builder, *, ideator_client=None, escalate=None, mutation_client=None, intent_client=None, property_client=None, now=time.monotonic) -> ImproveResult` | the orchestrator: initial `solve(write_tests=True)`; then while green and `expansions < config.max_expand_rounds` and `ideator_client`: `propose_ideas` → `select_idea` → (if chosen) `examiner.write_tests(idea.description)` → **append** those test files to `tests_frozen/` → `solve(write_tests=False)` (re-converge on the grown suite). Stops on not-green / round cap / no idea / leash reject. |

`forge improve <goal_dir> [--config] [--no-llm-verify]` CLI — the expand-phase entry point (builds the clients like `forge solve`, runs `improve`).

## Integration & reuse

- **`solve()` is the converge engine, called per round** — unchanged (no refactor). The first call regenerates the suite (`write_tests=True`); each re-converge reuses the grown frozen suite (`write_tests=False`).
- **The Examiner turns the chosen idea into the new test** — `examiner.write_tests(idea.description)` → its files are *appended* to `tests_frozen/` (a new `_append_tests` helper; the existing `_write_tests` overwrites, so append is distinct).
- **What runs on the initial converge vs. expand rounds (honest):** the initial converge (`write_tests=True`) runs the full moat — Examiner suite, hold-out split, property generation, the intent check (panel), then the builder loop, mutation, and the confidence gate. Expand rounds call `solve(write_tests=False)`, and in `loop.py` the suite-generation + intent-check + property/hold-out block is gated behind `if write_tests:`. So an expand round re-grades the **grown frozen suite** with the **builder loop + mutation testing + confidence gate + hold-out floor** (using the round-0 hold-out/property tests that persist in the dirs) — but it does **not** re-run the intent check and does **not** generate new hold-out/property tests for the new idea. (`improve()` still passes `intent_client`/`property_client` to the re-converge call, but they are inert there; only `mutation_client` is effective on re-converge.) This is deliberate: the intent check compares the suite to the *original* `goal.md`, which an idea-grown suite legitimately exceeds, so re-running it would report spurious divergences.
- **The leash** is the "autonomous with a leash" policy: objective + low-risk ideas auto-pursue; qualitative or high-risk ideas escalate to a human callback.
- `RunConfig` gains `max_expand_rounds: int = 3`, `ideator_model: str = "claude-opus-4-8"`, `ideas_n: int = 3`.
- **Injectable** `ideator_client` (fake-tested, spends no tokens in tests); `improve()` with `ideator_client=None` → no expansion → reduces to a single `solve()`.

## Honest framing & scope

- **Budget is per-round** (each `solve()` keeps its own caps), bounded by `max_expand_rounds`. A single shared global budget across all rounds is a noted refinement (it would require threading an external budget into `solve()`); per-round caps + the round cap bound the total for v3. Cost is multiplicative: up to `max_expand_rounds + 1` full converges.
- The Ideator can propose a **wrong or impossible** improvement; its verifier is then a test the builder can't satisfy → that converge round fails → the loop stops and reports it. Same risk class the moat already handles (a bad idea-test is caught by failing to converge + the human gate via the leash).
- **No last-known-good rollback across a failed expand round.** All `solve()` calls share one `.forge/best`; a failed expand round overwrites the prior round's green solution. `ImproveResult.success`/`rounds` report the failure honestly, but the earlier green artifact is not retained — a noted refinement.
- **Idea-tests are not held out.** Appended idea-tests join `tests_frozen/` only (never `tests_holdout/`), so a new feature gets no overfit/hold-out coverage of its own; the round-0 hold-out still guards the base goal. (And mutation testing does cover the new idea-test each round.)
- **The CLI leash halts rather than prompts.** `forge improve` passes no `escalate` callback, so a high-risk / non-objective top idea routes to `(None, True)` → the loop stops (safe default: halt when unsure). An interactive human-prompt escalate (like `solve`'s confirm gate) is a noted refinement; the `improve()` API already accepts an `escalate` callback for programmatic use.
- `improve()`'s `escalate` is the **idea-leash** hook (receives an `Idea`); it is intentionally *not* `solve()`'s confidence-override `escalate` (different callback shape). A low-confidence converge therefore stops the expand loop rather than auto-overriding — the safer behavior for an autonomous loop.
- The Supervisor (event-triggered trajectory guardian) and Population/Hybrid strategies remain future work — v3 is the converge/expand loop + the Ideator + the leash.

## Testing strategy

- `propose_ideas`: fake client returning an `_IdeaSet` + usage → assert the ideas flow through, goal + current tests forwarded, tokens captured, `n<=0`/`None` no-op.
- `select_idea`: pure — objective+low → auto (escalated False); high-risk → escalate(accept) → `(idea, True)`; high-risk → escalate(reject) → `(None, True)`; non-objective → escalate; empty → `(None, False)`.
- `improve`: a fake `ideator_client` returning one low-risk objective idea on round 1 then `[]` → exactly 1 expansion; a `StubExaminer` writing a *satisfiable* test for the idea; `FlakyBuilder` converges; assert `expansions == 1`, the idea's test is appended to `tests_frozen/`, `success`. Plus: no `ideator_client` → 0 expansions, reduces to `solve()`.
- CLI: offline (monkeypatched client + StubBuilder) → `forge improve` runs and reports rounds.
