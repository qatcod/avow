# Avow — Survival Instinct — Backlog (sub-projects B & C)

Deferred from the survival-instinct design (2026-07-15). Sub-project A (the Gauntlet + fight-back loop) is specced and built first; B and C build on top of it, in order. Each gets its own spec → plan → build when picked up.

## B — The Coroner + the Graveyard (the "gets better over time" half)

**Goal:** make Avow globally harder to fool with every death, by remembering *how* it was fooled and reusing that on future runs (any project).

- **Coroner** (`avow/coroner.py`): given a `Counterexample` (concrete input + goal), produce a transferable **AttackPattern** — an abstracted failure class ("comparing multi-part identifiers → probe the numeric-vs-lexical boundary," not the literal "beta.2 vs beta.11"). This abstraction step is the crown jewel and the hardest part; it is LLM-driven and must be evaluated for whether the abstraction actually transfers.
- **Graveyard** (`avow/graveyard.py`): a persistent, global store (`~/.avow/graveyard.jsonl`) of every AttackPattern that ever killed a run, across all projects. API: `record(pattern)`, `relevant(goal, k) -> list[AttackPattern]` (retrieve patterns worth trying on the current goal — keyword/tag or embedding match).
- **Gauntlet seeding:** the Gauntlet (from A) gains graveyard-seeded attacks: for each relevant pattern, an LLM instantiates concrete attack inputs for the current goal, which execution then runs against the solution vs the references. LLM proposes, execution disposes.
- **Honesty:** the graveyard's value is an empirical claim ("harder to fool over time") that C must measure, not assert. Guard against the graveyard bloating with non-transferable or duplicate patterns (dedup + relevance threshold).

## C — The calibration proof (the evidence it works)

**Goal:** prove the survival instinct actually reduces confident-wrongness, and that the graveyard keeps improving it — otherwise it is theater.

- Extend `avow calibrate` (or add a mode) to score each benchmark case **plain-green** vs **gauntlet-survived**, and report false-high-confidence for each. The claim to validate: survivors have materially lower false-high-confidence than plain greens.
- Measure the graveyard's marginal value: run the benchmark with an empty graveyard vs a seeded one; the seeded gauntlet should catch strictly more, and the reliability curve should straighten further.
- Deliverable: the enterprise-grade evidence slide — "Avow's 'verified survivor' verdict is X× less likely to be wrong than a plain green, and it improves as the graveyard grows."

## Build order

A (specced) → B → C. A is standalone-valuable (kills false-greens and fights to fix them within a run). B adds the evolution. C is the proof. Do not start B until A is shipped and green; do not start C until B produces a non-empty graveyard.
