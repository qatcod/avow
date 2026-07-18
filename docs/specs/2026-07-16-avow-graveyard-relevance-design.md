# Avow — Graveyard Relevance Retrieval — design

A follow-on to the survival instinct (sub-projects A/B/C). Today `survive()` seeds each gauntlet
round with `graveyard.recent(path, k)` — the N most-recent `AttackPattern`s, regardless of the
current goal. As the global graveyard grows across many projects, "recent" becomes mostly noise:
a lesson learned on a date-parsing goal does nothing for a graph-traversal goal. This feature adds
relevance retrieval so the gauntlet is seeded with the failure classes that actually apply here.

Scope is deliberately small and isolated: one new pure function, a one-line swap in `survive`, and
no change to the calibration proof (C).

## Goal

`relevant(goal, path, n)` returns the up-to-`n` stored `AttackPattern`s most relevant to `goal`,
ranked by lexical keyword/tag overlap. `survive` seeds from it instead of `recent`. Strict
relevance: a goal with no matching past lessons gets an empty list (no seeding), rather than being
diluted with recent-but-irrelevant patterns.

## Non-goals / out of scope (YAGNI)

- Embedding or semantic retrieval — keyword/tag overlap only; embeddings remain the backlog upgrade.
- Any change to `record`/`load`/dedup, or the `AttackPattern` schema.
- Any change to the calibration proof (C). Verified: `calibration_gauntlet.py` never calls
  `load`/`recent`/`relevant` and never reads `graveyard_path` — it mines fresh per-goal. So
  relevance in `survive`'s production path cannot reach C's leave-one-out or its leakage guard.

## Architecture

- **New:** `graveyard.relevant(goal, path, n) -> list[AttackPattern]` — a pure ranking function over
  `load(path)`. Self-contained; depends only on `load` and a small tokenizer helper.
- **Changed:** `survive.py` line 49 swaps `recent(graveyard_path, k)` for
  `relevant(goal, graveyard_path, k)`. `goal` is already in scope, so no signature change.
- **Unchanged:** `recent` and `load` stay (the `avow graveyard` CLI lists via `load`; `recent`
  remains a public helper and the ranking tiebreak reuses recency order).

## Relevance scoring

Deterministic, dependency-free lexical overlap:

1. **Tokenize** a string into lowercased tokens of `[a-z0-9]+`, drop tokens shorter than 3 chars and
   a small built-in stopword set (`the, and, for, that, with, returns, return, given, when, then,
   input, value, function`, etc. — a short curated list, not a linguistics project).
2. **Goal tokens** = tokenize(goal), as a set.
3. **Pattern signal tokens**, weighted by how curated the field is:
   - `category` slug, split on `-` then tokenized — weight **3** (the deliberate failure-class tag).
   - `description` — weight **1**.
   - `origin_goal` — weight **1** (provenance; weakly indicative of a similar source goal).
   - `example_input` is **excluded** (a literal falsifying input like `test_diff(a='2', b='11')` —
     noise, not about the goal).
4. **Score** = sum over the pattern's signal tokens that appear in the goal-token set, of that
   token's field weight. (A token appearing in multiple fields contributes each field's weight.)
5. **Rank** by `(score desc, recency desc)` where recency = position in `load(path)` order (later =
   more recent). **Strict:** keep only `score > 0`; return the first `n`.

Edge cases: `n <= 0` → `[]`; missing/empty store → `[]` (via `load`); no pattern overlaps → `[]`.

## Data flow

`survive` → `relevant(goal, graveyard_path, k)` → `load(path)` → tokenize + score + rank → top-k
`AttackPattern`s → `[p.description for p in ...]` → `run_gauntlet(patterns=...)`. Reloaded each
round (as today), so a kill recorded this run can surface as relevant in the next round.

## Honesty

Lexical overlap is a heuristic, not semantic understanding: a `numeric-boundary` pattern will not
match a goal phrased purely as "version comparison" unless they share surface tokens. This is a
deliberate v1 — it strictly improves on recency (which ignores the goal entirely) without
pretending to be semantic. The limitation is documented in the function docstring so a contributor
does not mistake it for semantic retrieval or "fix" it by bolting on an unrequested embedding path.

## Error handling

`relevant` is pure and total: it never raises on a missing file, empty store, or malformed goal
(all degrade to `[]` or a lower score). It inherits `load`'s corrupt-line skipping. It performs no
I/O beyond `load`. A failure here can only reduce seeding quality, never change a verdict — same
best-effort posture as the rest of the graveyard path.

## Testing

- `relevant` ranks a goal-matching pattern above an unrelated one.
- `category` tokens outweigh `description` tokens: a pattern whose *category* matches the goal
  outranks one whose only match is a single description word.
- Strict relevance: patterns with score 0 are excluded; a novel goal (no token overlap) → `[]`.
- Deterministic tiebreak: two equal-score patterns return most-recent-first.
- `n <= 0` → `[]`; missing/empty store → `[]`.
- `example_input` is not scored: a pattern whose only goal-overlap is in `example_input` scores 0.
- `survive` integration (hermetic, monkeypatched `run_gauntlet` capturing `patterns`): with a store
  holding one goal-relevant and one irrelevant pattern, `survive` seeds the gauntlet with the
  relevant description and not the irrelevant one.

## Build order

Pure `relevant` + its unit tests first (fast), then the one-line `survive` swap + its integration
test. Same review-before-push bar as A/B/C: full-suite gate + adversarial whole-branch review, fix,
then push only on greenlight.
