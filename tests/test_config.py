from pathlib import Path
from forge.config import RunConfig


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


def test_from_yaml_overrides_then_falls_back(tmp_path: Path):
    p = tmp_path / "forge.yaml"
    p.write_text("max_iterations: 5\nbuilder_model: claude-sonnet-4-6\n")
    cfg = RunConfig.from_yaml(p)
    assert cfg.max_iterations == 5
    assert cfg.builder_model == "claude-sonnet-4-6"
    assert cfg.examiner_model == "claude-sonnet-4-6"  # default retained


def test_from_yaml_missing_file_is_all_defaults(tmp_path: Path):
    cfg = RunConfig.from_yaml(tmp_path / "nope.yaml")
    assert cfg.max_iterations == 12
