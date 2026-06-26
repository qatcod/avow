from pathlib import Path
from forge.cli import main


def test_cli_runs_with_injected_no_regenerate(tmp_path: Path, monkeypatch, capsys):
    # Pre-seed a goal and frozen tests so --no-regenerate skips the Examiner (no network).
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    frozen = tmp_path / "tests_frozen"
    frozen.mkdir()
    (frozen / "test_add.py").write_text(
        "from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n"
    )

    # Patch the Builder so the CLI doesn't spawn `claude`.
    import forge.cli as cli

    class StubBuilder:
        def __init__(self, *a, **k):
            self.calls = 0

        def attempt(self, solution_dir, goal, failures):
            self.calls += 1
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            from forge.builder import BuilderOutcome
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = main(["solve", str(tmp_path), "--no-regenerate", "--yes"])
    assert rc == 0
    assert (tmp_path / ".forge" / "best" / "lib.py").exists()
    out = capsys.readouterr().out
    assert "confidence:" in out
