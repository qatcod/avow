from pathlib import Path
from types import SimpleNamespace
from hermit.cli import main


def _stub_solve_captures(monkeypatch, tmp_path):
    import hermit.cli as cli
    monkeypatch.setattr(cli, "build_examiner", lambda cfg: object())
    monkeypatch.setattr(cli, "Builder", lambda *a, **k: object())
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: "CLIENT")
    captured = {}

    def fake_solve(goal_dir, config, examiner, builder, **k):
        captured.update(k)
        return SimpleNamespace(reason="green", success=True, best_score=1.0, iterations=1,
                               confidence=1.0, confidence_breakdown={}, best_dir=tmp_path)

    monkeypatch.setattr(cli, "solve", fake_solve)
    return captured


def test_solve_wires_oracle_client_by_default(tmp_path: Path, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    captured = _stub_solve_captures(monkeypatch, tmp_path)
    assert main(["solve", str(tmp_path), "--yes"]) == 0
    # the suite-independent oracle must run by default (it's the signal mutation/hold-out can't replace)
    assert captured["oracle_client"] == "CLIENT"
    assert captured["intent_client"] == "CLIENT"


def test_solve_no_oracle_with_no_llm_verify(tmp_path: Path, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    captured = _stub_solve_captures(monkeypatch, tmp_path)
    assert main(["solve", str(tmp_path), "--yes", "--no-llm-verify"]) == 0
    assert captured["oracle_client"] is None


def test_cli_runs_with_injected_no_regenerate(tmp_path: Path, monkeypatch, capsys):
    # Pre-seed a goal and frozen tests so --no-regenerate skips the Examiner (no network).
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    frozen = tmp_path / "tests_frozen"
    frozen.mkdir()
    (frozen / "test_add.py").write_text(
        "from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )

    # Patch the Builder so the CLI doesn't spawn `claude`.
    import hermit.cli as cli

    class StubBuilder:
        def __init__(self, *a, **k):
            self.calls = 0

        def attempt(self, solution_dir, goal, failures):
            self.calls += 1
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            from hermit.builder import BuilderOutcome
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = main(["solve", str(tmp_path), "--no-regenerate", "--yes"])
    assert rc == 0
    assert (tmp_path / ".hermit" / "best" / "lib.py").exists()
    out = capsys.readouterr().out
    assert "confidence:" in out
