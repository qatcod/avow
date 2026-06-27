# Forge — Adversarial-Escalating Examiner (Layer II completion) — Design Spec

**Status:** Approved (2026-06-27). Completes **Layer II** of the verification moat ([design spec](2026-06-26-forge-design.md) §"Verification subsystem" → "Decorrelate + weaponize judges"): the cross-model panel shipped in v2.5; this adds the **adversarial Examiner that gets stricter over rounds** ("Examiner rewarded for *breaking* the Builder").

## Goal

The Examiner currently writes the acceptance suite **once**, from the goal alone. The plan calls for it to **escalate**: after a solution converges green, the Examiner reads *that specific passing solution* and writes **harder tests aimed at its weak spots** — boundaries, extremes, error paths, properties it might violate — trying to break it. Those tests join the suite and the loop re-converges. Repeat for a few escalation rounds, so the suite **battle-hardens against the actual solution**, not just the goal.

## Honest framing (stated up front)

The adversary is the **same model family** as the Examiner, so this is **not** a truly independent attacker — the decorrelation is weaker than the cross-model panel. The escalation's power comes from a different lever: feeding the adversary the **concrete solution code** and prompting it to break *that* lets it target real weak spots a goal-only prompt cannot find. It is a genuine increase in suite rigor (the suite gets strictly harder each round), framed as that — not as independent ground truth.

## Method (a sibling of `forge improve` — the proven wrap-solve pattern)

1. **Converge** the initial goal (`solve(write_tests=True)`).
2. **Escalate** (×`adversarial_rounds`, while green): read the green solution's code from `.forge/best`; `examiner.write_adversarial_tests(goal, solution_code)` → a `TestSuite` of breaking tests; split + **append** to `tests_frozen/` (visible) and `tests_holdout/` (held); **re-converge** (`solve(write_tests=False)`) against the grown, harder suite.
3. Stop on: a re-converge that fails (the adversary exposed something the Builder can't fix → reported, last-known-good preserved) or `adversarial_rounds` exhausted.

The anti-cheat is preserved: adversarial tests join the **frozen suite the Builder never sees** (graded ephemerally by the Runner); the suite is frozen within each converge and grows across escalation rounds — exactly the original rule. The whole moat (mutation/oracle/confidence) runs on each converge; intent/property generation run on the initial converge (same `write_tests` gating as `improve`).

## Components

`forge/examiner.py`:

| Unit | Job |
|---|---|
| `Examiner.write_adversarial_tests(goal: str, solution_code: str) -> ExaminerResult` | LLM reads the goal + the passing solution → a `TestSuite` of tests designed to break *this* implementation (`test_adv_*.py` files); same `messages.parse(... output_format=TestSuite)` shape as `write_tests`, different prompt |

`forge/harden.py`:

| Unit | Job |
|---|---|
| `HardenResult(success, rounds_run, rounds, final, best_round, best_dir)` | verdict, number of escalation rounds, per-round `SolveResult`s, the final result, and the last-known-good round/dir (same shape as `ImproveResult`) |
| `_read_solution_code(best_dir) -> str` | concatenate the solution's non-test `*.py` (skip `test_*.py`/`conftest.py`) with per-file headers |
| `harden(goal_dir, config, examiner, builder, *, mutation_client=None, intent_client=None, property_client=None, oracle_client=None, now=time.monotonic) -> HardenResult` | the orchestrator above |

Reuses `improve`'s `_append_tests` / `_read_test_sources` / `_snapshot` and `examiner.split_suite` (siblings in the same package — intentional reuse, not duplication). `solve()` is unchanged.

`forge harden <goal_dir> [--config] [--no-llm-verify]` CLI — the "build + battle-harden the suite" spin-out.

## Integration & config

- `RunConfig` gains `adversarial_rounds: int = 2`.
- `harden` threads the verification clients (`mutation`/`intent`/`property`/`oracle`) into every `solve()` call, exactly like `improve`.
- Injectable; offline runs (no clients) still converge and escalate (the adversarial Examiner is the injected `examiner`, fake in tests).

## Honest scope & limitations

- **Per-round budget**, bounded by `adversarial_rounds` (same as `improve`); the orchestrator-level `write_adversarial_tests` token cost is **not** separately budgeted (consistent with `improve`'s Ideator calls) — a noted refinement.
- **Last-known-good** is preserved across a failed escalation round (`.forge/best_good`), same as `improve`.
- The adversary shares the Examiner's model family (weaker decorrelation than the panel) — disclosed above.
- Using a *different-family* model as the adversary, and stopping early when the adversary genuinely can't break the solution (rather than a fixed round count), are later refinements.

## Testing strategy

- `write_adversarial_tests`: fake client returning a `TestSuite` + usage → assert the goal AND the solution code are forwarded into the prompt, the suite + tokens flow through.
- `harden`: a `StubExaminer` with both `write_tests` (the goal suite) and `write_adversarial_tests` (a *satisfiable* harder test) + a `StubBuilder` (`add = a + b`) → the solution survives each escalation → `rounds_run == adversarial_rounds`, `len(rounds) == adversarial_rounds + 1`, the appended adversarial test present in `tests_frozen/`, `success`. Plus: a failing adversarial round (an *impossible* adversarial test) → `final.success is False`, `best_round` = the last green round, `best_dir` preserved.
- CLI: `forge harden` offline (monkeypatched client + StubBuilder) → runs and prints per-round lines.

## Out of scope (later)

- A different-family adversary model (stronger decorrelation).
- Early stop when the adversary can't break the solution (vs. fixed `adversarial_rounds`).
- Folding `harden` and `improve` into one configurable two-phase orchestrator.
