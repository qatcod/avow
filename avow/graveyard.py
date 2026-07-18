"""The Graveyard: a global, append-only JSONL memory of attack patterns learned from past deaths.

Two deliberate simplifications for v1, documented so contributors don't "fix" them by accident:
  - Dedup is EXACT-match on the normalized (category, description) key — near-duplicate LLM wordings
    ("probe empty strings" vs "probe empty string") are stored as distinct patterns by design. The
    deterministic dedup tests depend on this; fuzzy matching would break them.
  - record() is read-check-append with no file lock, so two processes writing the SAME graveyard
    concurrently can each append the same pattern (a harmless duplicate — load()/recent() still work,
    seeding is just slightly noisier). Cross-process locking is out of scope for v1.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError


class AttackPattern(BaseModel):
    category: str          # short slug, e.g. "numeric-boundary" | "empty-input" | "unicode-edge"
    description: str        # transferable attack strategy (NOT the literal input)
    origin_goal: str = ""   # one-line summary of the goal it arose from (provenance)
    example_input: str = ""  # the concrete falsifying example that spawned it


def default_graveyard_path() -> Path:
    return Path.home() / ".avow" / "graveyard.jsonl"


def pattern_key(p: AttackPattern) -> tuple[str, str]:
    """Return the normalized identity used for exact pattern deduplication."""
    return (p.category.strip().lower(), p.description.strip().lower())


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        # The graveyard is optional, best-effort memory. A damaged or temporarily
        # unreadable store must never prevent a solve or gauntlet from running.
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(AttackPattern(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
            continue   # skip corrupt / incomplete / schema-drifted lines — the store is best-effort
    return out


def record(pattern: AttackPattern, path) -> bool:
    """Append the pattern iff its (category, description) key is new. Returns whether it was recorded."""
    p = Path(path)
    if pattern_key(pattern) in {pattern_key(x) for x in load(p)}:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(pattern.model_dump_json() + "\n")
    return True


def recent(path, n: int) -> list:
    return load(path)[-n:] if n > 0 else []


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "and", "for", "that", "with", "from", "into", "returns", "return",
    "given", "when", "then", "input", "value", "function", "true", "false", "none",
    "probe",   # near-universal in Coroner-authored attack descriptions -> carries no discrimination
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
