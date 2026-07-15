# Avow — The Coroner + The Graveyard (sub-project B) — Design Spec

**Status:** Approved (2026-07-15). Sub-project B of the survival instinct. Builds on A (the gauntlet + `survive` loop). C (the calibration proof) stays backlogged.

## Goal

Make Avow globally harder to fool over time. Every gauntlet kill is abstracted (the **Coroner**) into a transferable **AttackPattern** and persisted in a global **Graveyard**. Future gauntlets — on any project — are **seeded** with the graveyard's patterns, so the references they generate deliberately probe the ways Avow has been fooled before. Backward-compatible: an empty graveyard leaves the gauntlet exactly as A shipped it.

## Design principles carried from A

- **Execution still decides every kill.** The graveyard only makes the gauntlet's references *pattern-aware* (biases reference generation toward known-tricky input classes); a kill is still a majority-of-usable-references execution divergence. The graveyard never kills on its own.
- **Reuse A's machinery.** Seeding augments the goal passed to `oracle.generate_oracle`; it adds no new voting logic. Recording happens in `survive`'s existing fight-back. No embeddings, no vector DB.
- **Opt-in, no dead config.** Recording happens only when a `coroner_client` is supplied (i.e. during `avow survive` without `--no-llm-verify`); an empty/absent graveyard file is a no-op everywhere.
- **Honest limits.** Whether the graveyard actually reduces confident-wrongness is an *empirical* claim that sub-project C must measure (survivors' false-high-confidence with an empty vs a seeded graveyard). Until C, we claim only "the gauntlet probes past failure modes," not "it is measurably harder to fool."

## Components

### `avow/graveyard.py` — the persistent global store (pure, no LLM)

```python
class AttackPattern(BaseModel):
    category: str        # short slug, e.g. "numeric-boundary" | "empty-input" | "unicode-edge"
    description: str     # transferable attack strategy (NOT the literal input)
    origin_goal: str     # one-line summary of the goal it arose from (provenance)
    example_input: str   # the concrete falsifying example that spawned it
```

| Unit | Job |
|---|---|
| `default_graveyard_path() -> Path` | `Path.home() / ".avow" / "graveyard.jsonl"` |
| `record(pattern, path) -> bool` | append the pattern as one JSON line iff its dedup key `(category, description.strip().lower())` is not already present; returns whether it was newly recorded. Creates parent dirs. |
| `load(path) -> list[AttackPattern]` | read all lines in append order (skips blank/corrupt lines); missing file → `[]` |
| `recent(path, n) -> list[AttackPattern]` | the last `n` patterns (recency = file order, no timestamps) |

### `avow/coroner.py` — the autopsy (LLM)

| Unit | Job |
|---|---|
| `abstract_counterexample(counterexample, goal, client, model) -> tuple[AttackPattern | None, int, int]` | LLM (`messages.parse`, `output_format=AttackPattern`): given the goal + the concrete `Counterexample` (`input_repr` + `reference_code`), produce a *transferable* AttackPattern — abstract the failure class, do NOT just echo the literal input. Returns `(None, 0, 0)` when `client is None`. |

### `avow/gauntlet.py` — seeding (one-line change)

`run_gauntlet(..., patterns: list | None = None)`: when `patterns` is non-empty, reference generation uses a goal augmented with a section listing the pattern descriptions ("A rigorous differential test MUST cover these known-tricky input classes: …"). The K references' diff tests then probe those classes. `patterns=None`/`[]` → behavior identical to A.

### `avow/survive.py` — wire it in

`survive(..., coroner_client=None)`:
- Before the gauntlet loop, load `patterns = [p.description for p in recent(graveyard_path, config.graveyard_patterns_k)]` and pass to every `run_gauntlet`.
- On each kill, if `coroner_client` is set: `pattern, i, o = abstract_counterexample(g.counterexample, goal, coroner_client, config.coroner_model)`; if `pattern`, `record(pattern, graveyard_path)`. (Recording is best-effort; a Coroner failure never changes the survive verdict.)
- `graveyard_path = config.graveyard_path or default_graveyard_path()`.

### `avow/config.py`

`coroner_model: str = "claude-opus-4-8"` · `graveyard_patterns_k: int = 20` · `graveyard_path: str = ""` (empty → `default_graveyard_path()`).

### `avow/cli.py`

`avow survive` passes `coroner_client=verify_client`. New `avow graveyard` verb: `list` the stored patterns (count + category/description), so the memory is inspectable. `--graveyard <path>` override on `survive`/`graveyard` (defaults to `~/.avow/graveyard.jsonl`).

## Data flow

`survive` → kill → `abstract_counterexample` → `AttackPattern` → `record` (global JSONL). Next `run_gauntlet` (this run or any future run) → `recent(...)` descriptions → seeded reference generation → pattern-aware diff tests → execution-decided kill.

## Anti-cheat & honesty (load-bearing)

- The graveyard only *proposes* what to probe; the kill remains an execution divergence from a reference majority (A's guardrails unchanged).
- Patterns are abstracted, not the literal solution/tests — the Builder never sees them (they influence only reference generation, in the ephemeral gauntlet grade).
- Dedup + `recent(k)` cap bound graveyard bloat; a non-transferable or duplicate pattern is dropped at record time or simply never fires.
- Backward compatible: empty graveyard → `run_gauntlet` is byte-for-byte A's behavior (proven by an off-path test).

## Testing strategy

- **Graveyard** (pure, offline): `record` then `load` round-trips; a duplicate `(category, description)` is not re-recorded (`record` returns False); `recent(n)` returns the last n in order; missing file → `[]`; a corrupt line is skipped.
- **Coroner** (fake client): a `Counterexample` + goal → an `AttackPattern` with non-empty category/description; `client=None` → `(None, 0, 0)`.
- **Seeding** (`run_gauntlet` with `patterns`): with a fake oracle client that records the goal it received, assert the augmented goal contains the pattern descriptions; `patterns=None` → the goal is unchanged (A's behavior).
- **survive record-on-kill** (monkeypatched gauntlet + fake coroner): a kill records exactly one pattern to a temp graveyard; a survive records nothing; a Coroner that returns None records nothing and doesn't change the verdict.
- **CLI**: `avow graveyard --graveyard <tmp>` lists the stored patterns; `avow survive` passes a coroner_client.
- Full suite green; empty-graveyard path proven identical to A.

## Out of scope (still backlog)

- **C — Calibration proof**: extend `avow calibrate` to measure survivors' false-high-confidence with an empty vs seeded graveyard (the evidence B works).
- LLM- or embedding-based *relevance* retrieval (v1 seeds with recency; the reference-gen LLM naturally focuses on relevant classes).
- Cross-provider seeded references (needs OpenRouter).
