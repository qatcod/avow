from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class AttackPattern(BaseModel):
    category: str          # short slug, e.g. "numeric-boundary" | "empty-input" | "unicode-edge"
    description: str        # transferable attack strategy (NOT the literal input)
    origin_goal: str = ""   # one-line summary of the goal it arose from (provenance)
    example_input: str = ""  # the concrete falsifying example that spawned it


def default_graveyard_path() -> Path:
    return Path.home() / ".avow" / "graveyard.jsonl"


def _key(p: AttackPattern) -> tuple:
    return (p.category.strip().lower(), p.description.strip().lower())


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(AttackPattern(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue   # skip corrupt / incomplete lines — the store is best-effort
    return out


def record(pattern: AttackPattern, path) -> bool:
    """Append the pattern iff its (category, description) key is new. Returns whether it was recorded."""
    p = Path(path)
    if _key(pattern) in {_key(x) for x in load(p)}:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(pattern.model_dump_json() + "\n")
    return True


def recent(path, n: int) -> list:
    return load(path)[-n:] if n > 0 else []
