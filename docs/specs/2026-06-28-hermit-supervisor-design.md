# Hermit — The Supervisor (event-triggered trajectory guardian) — Design Spec

**Status:** Approved (2026-06-28). The last agent of the original [4-agent design](2026-06-26-hermit-design.md) (§"Agents"): "Supervisor — judge trajectory → redirect / change strategy / escalate; never enforces; runs only when a trouble-signal fires."

## Goal

When a run is **plateauing** (a deterministic trouble signal), have an LLM **judge the trajectory** — read the recent attempts and decide whether the run is recoverable, needs a redirect, or should escalate to a human — and emit a **recommendation**. The deterministic loop adjudicates the recommendation. The Supervisor never enforces.

## The honest position (this is the flagged risk — mitigations are structural)

The original design names **agent proliferation as the project's #1 self-risk**, and the Supervisor is a 4th agent. The mitigations are built into its shape, not bolted on:
- **Off by default** (`supervisor_enabled = False`) — the default loop is unchanged; the Supervisor is strictly opt-in.
- **Event-triggered, fires once** — it runs only when `rounds_without_improvement` reaches `supervisor_patience`, not every iteration, and only once per run.
- **Judges, never enforces** — it emits a `SupervisorVerdict`; deterministic loop code decides what to do with it. The budget caps + plateau/stop conditions remain the hard floor; the Supervisor **cannot extend a run**, only flag or redirect it earlier than the plateau would.

## Method

1. **Trigger (deterministic):** inside the loop, while **not green**, when `config.supervisor_enabled and supervisor_client is not None and not already-fired and rounds_without_improvement >= config.supervisor_patience` (default 2, below `plateau_patience` 3).
2. **Judge:** `review_trajectory(goal, history)` — a model reads the goal + the recent `AttemptRecord`s (iteration, score, is_green, failing tests, the builder's stated plan) and emits `SupervisorVerdict(assessment, recommendation, escalate)`.
3. **Adjudicate (deterministic):**
   - `escalate == True` or `recommendation == "abort"` → the loop stops with reason `"supervisor_escalate"` (`success=False`).
   - `recommendation == "redirect"` → the `assessment` becomes a **guidance hint** appended to the goal passed to subsequent builder attempts.
   - `recommendation == "continue"` → no change (the plateau stop still fires at `plateau_patience` if no improvement).

## Components

`hermit/supervisor.py`:

| Unit | Job |
|---|---|
| `SupervisorVerdict(BaseModel)` with `assessment: str`, `recommendation: str` (`"continue"`/`"redirect"`/`"escalate"`/`"abort"`), `escalate: bool` | structured-output schema |
| `review_trajectory(goal, history, client, model) -> tuple[SupervisorVerdict \| None, int, int]` | format the recent attempts into a prompt → a verdict + token usage; `(None, 0, 0)` when `client is None` |

`history` is a list of `AttemptRecord`-like objects (read `.iteration`, `.score`, `.is_green`, `.failing`, `.plan`).

## Integration (loop)

- `solve` gains a keyword-only `supervisor_client=None` (after `oracle_client`).
- The loop maintains `attempt_history: list[AttemptRecord]` (appended alongside each `log.record(...)`), `supervisor_fired = False`, `supervisor_hint: str | None = None`.
- The builder is called with `goal if supervisor_hint is None else f"{goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"`.
- The hook (above) sits **after the green-branch return and before the plateau check**, fires once, records the verdict via `RunLog`, and applies the deterministic adjudication.
- New stop reason `"supervisor_escalate"` (returned as `SolveResult(False, …, "supervisor_escalate", …)`); all other returns unchanged.
- `RunConfig` gains `supervisor_enabled: bool = False`, `supervisor_model: str = "claude-opus-4-8"`, `supervisor_patience: int = 2`.
- **Backward compatibility:** `supervisor_enabled` defaults False, so the hook never fires by default and existing loop behavior/tests are unchanged. The `attempt_history` accumulation and the unhinted `attempt_goal` are inert when the Supervisor is off.

`hermit supervise <run_jsonl> <goal_file> [--config]` CLI — reads a recorded `run.jsonl`, reconstructs the trajectory, and prints the Supervisor's verdict for any past run.

## Honest scope & limitations

- The Supervisor shares the Examiner/Builder model family (not an independent overseer) — its judgment is advisory, and the redirect hint is just appended guidance the Builder may ignore.
- Fires **once** per run (no repeated reprieves → can't cause runaway). Multiple firings / strategy-switching (escalate to Population on the Supervisor's call) are future refinements.
- The redirect hint is plain-text guidance appended to the goal; structured strategy changes are out of scope.
- It does not (and by design must not) override the budget/plateau/stop floor.

## Testing strategy

- `review_trajectory`: fake client returning a `SupervisorVerdict` + usage → goal + trajectory forwarded into the prompt, verdict + tokens flow through, `None`-client no-op.
- Loop (Supervisor **enabled** in the test config): an `AlwaysWrongBuilder` (never green) + a fake supervisor returning `escalate=True` → the run stops with reason `"supervisor_escalate"` before plateau; a fake returning `recommendation="continue"` → the run proceeds to the normal `"plateau"` stop. Dormant: default config (supervisor off, no client) → `AlwaysWrongBuilder` → normal `"plateau"`, Supervisor never fires (existing tests unchanged).
- CLI: `hermit supervise` offline (monkeypatched client) reading a small `run.jsonl` → prints the verdict.

## Out of scope (later)

- Repeated Supervisor firings / a Supervisor-triggered strategy switch (e.g. escalate to `population_solve`).
- A different-family overseer model.
- Structured (non-text) redirect actions.
