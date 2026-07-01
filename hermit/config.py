from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


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
        default_factory=lambda: {"holdout": 1.0, "mutation": 1.0, "intent": 1.0, "oracle": 1.0})
    confidence_gating: bool = True
    holdout_floor: float = 0.5
    panel_models: list[str] = Field(
        default_factory=lambda: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"])
    panel_enabled: bool = True
    panel_agreement_floor: float = 0.5
    max_expand_rounds: int = 3
    ideator_model: str = "claude-opus-4-8"
    ideas_n: int = 3
    oracle_enabled: bool = True
    oracle_model: str = "claude-opus-4-8"
    oracle_floor: float = 1.0
    oracle_converge_target: bool = False
    adjudicate_enabled: bool = False
    adjudicate_model: str = "claude-opus-4-8"
    adjudicate_threshold: float = 0.9
    adjudicate_references_k: int = 3
    adversarial_rounds: int = 2
    population_size: int = 3
    max_parallel_candidates: int = 4
    supervisor_enabled: bool = False
    supervisor_model: str = "claude-opus-4-8"
    supervisor_patience: int = 2
    property_tests_enabled: bool = True
    property_model: str = "claude-opus-4-8"
    property_tests_n: int = 4

    @model_validator(mode="after")
    def _supervisor_patience_below_plateau(self) -> "RunConfig":
        # The Supervisor fires at supervisor_patience and (for a redirect) hands the Builder a
        # guided attempt. If supervisor_patience >= plateau_patience, the loop plateaus the same
        # iteration the hint is set, so the redirect would never reach the Builder. Make that
        # misconfiguration a loud error rather than a silent no-op.
        if self.supervisor_enabled and self.supervisor_patience >= self.plateau_patience:
            raise ValueError(
                "supervisor_patience must be < plateau_patience when supervisor_enabled "
                f"(got supervisor_patience={self.supervisor_patience}, "
                f"plateau_patience={self.plateau_patience})"
            )
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RunConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text()) or {}
        return cls(**data)
