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
    max_ast_mutants: int = 50
    llm_mutants_n: int = 3
    mutation_model: str = "claude-sonnet-4-6"
    mutation_enabled: bool = True
    backtranslation_model: str = "claude-opus-4-8"
    intent_check_enabled: bool = True
    confidence_threshold: float = 0.7
    confidence_weights: dict[str, float] = Field(
        default_factory=lambda: {"holdout": 1.0, "mutation": 1.0, "intent": 1.0})
    confidence_gating: bool = True
    holdout_floor: float = 0.5
    panel_models: list[str] = Field(
        default_factory=lambda: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"])
    panel_enabled: bool = True
    panel_agreement_floor: float = 0.5
    property_tests_enabled: bool = True
    property_model: str = "claude-opus-4-8"
    property_tests_n: int = 4

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RunConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text()) or {}
        return cls(**data)
