from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    builder_model: str = "claude-opus-4-8"
    examiner_model: str = "claude-sonnet-4-6"
    max_iterations: int = 12
    plateau_patience: int = 3
    max_cost_usd: float = 10.0
    max_wall_seconds: int = 3600
    test_command: list[str] = Field(default_factory=lambda: ["python", "-m", "pytest", "-q"])
    holdout_fraction: float = 0.25
    builder_timeout_seconds: int = 600
    test_timeout_seconds: int = 120

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RunConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text()) or {}
        return cls(**data)
