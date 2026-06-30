from pathlib import Path
from hermit.config import RunConfig


def test_defaults_are_sane():
    cfg = RunConfig()
    assert cfg.builder_model == "claude-opus-4-8"
    assert cfg.examiner_model == "claude-sonnet-4-6"
    assert cfg.max_iterations == 12
    assert cfg.plateau_patience == 3
    assert cfg.max_cost_usd == 10.0
    assert cfg.max_wall_seconds == 3600
    assert cfg.test_command == ["python", "-m", "pytest", "-q"]
    assert cfg.holdout_fraction == 0.25
    assert cfg.builder_timeout_seconds == 600
    assert cfg.test_timeout_seconds == 120
    assert cfg.max_ast_mutants == 50
    assert cfg.llm_mutants_n == 3
    assert cfg.mutation_model == "claude-sonnet-4-6"
    assert cfg.mutation_enabled is True
    assert cfg.backtranslation_model == "claude-opus-4-8"
    assert cfg.intent_check_enabled is True
    assert cfg.confidence_threshold == 0.7
    assert cfg.confidence_weights == {"holdout": 1.0, "mutation": 1.0, "intent": 1.0, "oracle": 1.0}
    assert cfg.confidence_gating is True
    assert cfg.holdout_floor == 0.5
    assert cfg.property_tests_enabled is True
    assert cfg.property_model == "claude-opus-4-8"
    assert cfg.property_tests_n == 4
    assert cfg.panel_models == ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"]
    assert cfg.panel_enabled is True
    assert cfg.panel_agreement_floor == 0.5
    assert cfg.max_expand_rounds == 3
    assert cfg.ideator_model == "claude-opus-4-8"
    assert cfg.ideas_n == 3
    assert cfg.oracle_enabled is True
    assert cfg.oracle_model == "claude-opus-4-8"
    assert cfg.oracle_floor == 1.0
    assert cfg.oracle_converge_target is False
    assert cfg.adversarial_rounds == 2
    assert cfg.population_size == 3
    assert cfg.max_parallel_candidates == 4
    assert cfg.supervisor_enabled is False        # ships dormant
    assert cfg.supervisor_model == "claude-opus-4-8"
    assert cfg.supervisor_patience == 2
    assert cfg.confidence_weights["oracle"] == 1.0


def test_from_yaml_overrides_then_falls_back(tmp_path: Path):
    p = tmp_path / "hermit.yaml"
    p.write_text("max_iterations: 5\nbuilder_model: claude-sonnet-4-6\n")
    cfg = RunConfig.from_yaml(p)
    assert cfg.max_iterations == 5
    assert cfg.builder_model == "claude-sonnet-4-6"
    assert cfg.examiner_model == "claude-sonnet-4-6"  # default retained


def test_from_yaml_missing_file_is_all_defaults(tmp_path: Path):
    cfg = RunConfig.from_yaml(tmp_path / "nope.yaml")
    assert cfg.max_iterations == 12


def test_supervisor_patience_must_be_below_plateau_when_enabled():
    import pytest

    # enabled + supervisor_patience >= plateau_patience -> the redirect would never reach the
    # builder, so this is rejected loudly.
    with pytest.raises(ValueError):
        RunConfig(supervisor_enabled=True, supervisor_patience=3, plateau_patience=3)
    # disabled -> no constraint; the dormant default is fine.
    RunConfig(supervisor_enabled=False, supervisor_patience=5, plateau_patience=3)
    # enabled + below plateau -> fine.
    RunConfig(supervisor_enabled=True, supervisor_patience=2, plateau_patience=3)
