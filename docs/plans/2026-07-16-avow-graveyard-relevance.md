# Graveyard Relevance Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seed each gauntlet round with graveyard patterns relevant to the current goal (lexical keyword/tag overlap), not just the most recent, so the store stays useful as it grows.

**Architecture:** One new pure ranking function `graveyard.relevant(goal, path, n)` over `load(path)`, plus a private tokenizer; a one-line swap at `survive.py:49` from `recent` to `relevant`. `recent`/`load` and the calibration proof (C) are untouched.

**Tech Stack:** Python 3.11+, pytest, pydantic (existing `AttackPattern`), stdlib `re`.

## Global Constraints

- Keyword/tag overlap only — NO embeddings or semantic retrieval.
- Field weights: `category` ×3, `description` ×1, `origin_goal` ×1; `example_input` is NOT scored.
- Strict relevance: keep only `score > 0`; a novel goal (no overlap) returns `[]`.
- Rank by `(score desc, recency desc)` where recency = index in `load(path)` order (later = more recent).
- `relevant` is pure and total: `n <= 0` → `[]`, missing/empty store → `[]`, never raises.
- Do NOT change `record`/`load`/dedup, the `AttackPattern` schema, or `avow/calibration_gauntlet.py` (C).
- Same review-before-push bar as A/B/C: full-suite gate + adversarial whole-branch review, fix, push only on greenlight.

## File Structure

- `avow/graveyard.py` (modify) — add `_TOKEN_RE`, `_STOPWORDS`, `_tokenize`, and `relevant`. Existing `load`/`recent`/`record`/`AttackPattern` unchanged.
- `avow/survive.py` (modify) — line 49 swap; import `relevant` instead of `recent`.
- Tests: append to `tests/test_graveyard.py` and `tests/test_survive.py`.

---

### Task 1: `relevant(goal, path, n)` + tokenizer

**Files:**
- Modify: `avow/graveyard.py`
- Test: `tests/test_graveyard.py` (append)

**Interfaces:**
- Consumes: `load(path) -> list[AttackPattern]`, `AttackPattern(category, description, origin_goal, example_input)` (existing).
- Produces: `relevant(goal: str, path, n: int) -> list[AttackPattern]`; private `_tokenize(s) -> set[str]`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_graveyard.py`)**

```python
from avow.graveyard import relevant


def test_relevant_ranks_matching_pattern_above_unrelated(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="recursion-depth", description="probe deep recursion on factorial"), gy)
    record(AttackPattern(category="unicode-edge", description="probe emoji surrogate pairs"), gy)
    out = relevant("compute factorial with deep recursion for an integer", gy, 5)
    assert [p.category for p in out] == ["recursion-depth"]   # only the overlapping pattern, unrelated excluded


def test_relevant_category_outweighs_description(tmp_path):
    gy = tmp_path / "gy.jsonl"
    # cat_match: goal token "boundary" hits the CATEGORY (weight 3)
    record(AttackPattern(category="boundary-check", description="unrelated words here"), gy)
    # desc_match: goal token "boundary" hits only the DESCRIPTION (weight 1)
    record(AttackPattern(category="unrelated-slug", description="probe a boundary somewhere"), gy)
    out = relevant("test the boundary", gy, 5)
    assert [p.category for p in out] == ["boundary-check", "unrelated-slug"]   # 3 > 1


def test_relevant_strict_excludes_zero_score_and_novel_goal_is_empty(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe numeric boundaries"), gy)
    assert relevant("wholly unrelated xyzzy plover topic", gy, 5) == []   # no overlap -> empty (strict)


def test_relevant_recency_breaks_score_ties(tmp_path):
    gy = tmp_path / "gy.jsonl"
    older = AttackPattern(category="alpha-one", description="boundary check alpha")
    newer = AttackPattern(category="beta-two", description="boundary check beta")
    record(older, gy)
    record(newer, gy)   # more recent
    out = relevant("probe boundary conditions", gy, 5)
    # equal score (both match only 'boundary' in description) -> most-recent first
    assert [p.category for p in out] == ["beta-two", "alpha-one"]


def test_relevant_n_le_zero_and_missing_store_are_empty(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe numeric boundaries"), gy)
    assert relevant("numeric boundary", gy, 0) == []
    assert relevant("numeric boundary", tmp_path / "nope.jsonl", 5) == []


def test_relevant_does_not_score_example_input(tmp_path):
    gy = tmp_path / "gy.jsonl"
    # the only overlap ('plover') is in example_input, which is NOT scored -> excluded
    record(AttackPattern(category="c-slug", description="d words", example_input="plover"), gy)
    assert relevant("the plover flew", gy, 5) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_graveyard.py -q`
Expected: FAIL with `ImportError: cannot import name 'relevant'`.

- [ ] **Step 3: Implement in `avow/graveyard.py`**

Add `import re` at the top (next to `import json`), then add below `recent`:

```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "and", "for", "that", "with", "from", "into", "returns", "return",
    "given", "when", "then", "input", "value", "function", "true", "false", "none",
})


def _tokenize(s: str) -> set:
    """Lowercased alphanumeric tokens (>= 3 chars, minus a small stopword set). Splits kebab slugs
    for free, since '-' is not in [a-z0-9] (so 'numeric-boundary' -> {'numeric', 'boundary'})."""
    return {t for t in _TOKEN_RE.findall((s or "").lower()) if len(t) >= 3 and t not in _STOPWORDS}


def relevant(goal: str, path, n: int) -> list:
    """The up-to-n stored patterns most relevant to `goal`, by weighted lexical overlap: a token
    shared with the goal scores 3 in `category` (the curated failure-class tag), 1 in `description`,
    1 in `origin_goal`; `example_input` is not scored. STRICT: only patterns with score > 0 are
    returned (a novel goal gets []); ties break toward the most recent. Pure lexical heuristic, not
    semantic retrieval — it strictly improves on recency without pretending to understand meaning."""
    if n <= 0:
        return []
    gtok = _tokenize(goal)
    if not gtok:
        return []
    scored = []
    for i, p in enumerate(load(path)):   # load() order is oldest-first, so a larger i is more recent
        score = (3 * len(_tokenize(p.category) & gtok)
                 + len(_tokenize(p.description) & gtok)
                 + len(_tokenize(p.origin_goal) & gtok))
        if score > 0:
            scored.append((score, i, p))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [p for _, _, p in scored[:n]]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_graveyard.py -q`
Expected: PASS (existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add avow/graveyard.py tests/test_graveyard.py
git commit -m "feat: graveyard.relevant — rank patterns by weighted lexical overlap with the goal (strict, category-weighted)"
```

---

### Task 2: Seed `survive` from relevance, not recency

**Files:**
- Modify: `avow/survive.py`
- Test: `tests/test_survive.py` (append)

**Interfaces:**
- Consumes: `relevant(goal, path, n)` (Task 1); existing `survive(goal_dir, config, ...)`, `GauntletResult`.
- Produces: no new interface; `survive` now seeds from `relevant`.

- [ ] **Step 1: Write the failing test (append to `tests/test_survive.py`)**

```python
def test_survive_seeds_gauntlet_with_relevant_not_recent_patterns(tmp_path, monkeypatch):
    import avow.survive as s
    from avow.graveyard import record, AttackPattern
    gy = tmp_path / "gy.jsonl"
    # a goal-relevant pattern and an irrelevant (more-recent) one
    record(AttackPattern(category="recursion-depth", description="probe deep recursion on factorial"), gy)
    record(AttackPattern(category="unicode-edge", description="probe emoji surrogate pairs"), gy)
    (tmp_path / "goal.md").write_text("compute factorial with deep recursion for an integer")

    seen = {}

    def fake_g(*a, **k):
        seen["patterns"] = list(k.get("patterns") or [])
        return GauntletResult(True, None, 4, 4, 0, 0)   # survives immediately, round 0

    monkeypatch.setattr(s, "run_gauntlet", fake_g)
    r = survive(tmp_path, RunConfig(max_iterations=5, holdout_fraction=0.0, graveyard_path=str(gy)),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "verified_survivor"
    assert "probe deep recursion on factorial" in seen["patterns"]     # relevant one seeded
    assert "probe emoji surrogate pairs" not in seen["patterns"]       # irrelevant one NOT seeded
```

Note: `tests/test_survive.py` already defines `StubExaminer`, `GoodBuilder`, and imports `survive`, `RunConfig`, `GauntletResult`. The stubs build a green `add` solution regardless of `goal.md`'s text (the gauntlet is monkeypatched), so `goal.md` here exists only to drive relevance.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_survive.py::test_survive_seeds_gauntlet_with_relevant_not_recent_patterns -q`
Expected: FAIL — currently `survive` seeds via `recent`, which returns BOTH patterns (so the irrelevant one IS in `seen["patterns"]`), failing the last assertion.

- [ ] **Step 3: Swap `recent` for `relevant` in `avow/survive.py`**

Change the import (line ~9) from:

```python
from avow.graveyard import recent, record, default_graveyard_path
```

to:

```python
from avow.graveyard import relevant, record, default_graveyard_path
```

Change the seeding line (line ~49) from:

```python
        patterns = [p.description for p in recent(graveyard_path, config.graveyard_patterns_k)]
```

to:

```python
        patterns = [p.description for p in relevant(goal, graveyard_path, config.graveyard_patterns_k)]
```

`goal` is already read at the top of `survive` (`goal = (goal_dir / "goal.md").read_text()`), so it is in scope. Update the nearby comment if it says "recent".

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_survive.py -q`
Expected: PASS (existing survive tests + the new one). The relevant pattern is seeded; the irrelevant one is not.

- [ ] **Step 5: Commit**

```bash
git add avow/survive.py tests/test_survive.py
git commit -m "feat: survive seeds the gauntlet from goal-relevant graveyard patterns (was recency)"
```

---

## Self-review checklist (run after Task 2)

- Full-suite gate: `python -m pytest -q` → all green, 0 warnings.
- Confirm `avow/calibration_gauntlet.py` is unchanged (`git diff --stat` shows only graveyard.py, survive.py, and the two test files).
- Confirm `avow graveyard` CLI still lists via `load` (untouched) and `recent` is still importable (kept for the public API / possible callers).

## Out of scope (backlog)

- Embedding/semantic retrieval.
- Measuring relevance's marginal calibration value (a C extension: relevant-seeded vs recency-seeded false-high-confidence).
