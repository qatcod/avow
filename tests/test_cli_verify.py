from pathlib import Path
from types import SimpleNamespace
import forge.cli as cli
from forge.backtranslation import _InferredGoal, IntentMatch


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        if output_format is _InferredGoal:
            po = _InferredGoal(inferred_goal="add two numbers")
        else:
            po = IntentMatch(score=0.8, divergences=[])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_verify_cli_offline(tmp_path: Path, capsys, monkeypatch):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    tests = tmp_path / "tests"; tests.mkdir()
    (tests / "test_add.py").write_text(
        "from lib import add\n"
        "def test_pos(): assert add(2, 3) == 5\n"
        "def test_neg(): assert add(-1, 1) == 0\n"
    )
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["verify", str(sol), str(tests), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    # mutation 1.0 (strong suite), intent 0.8 -> confidence 0.90
    assert "confidence: 0.90" in out
    assert "mutation:" in out
    assert "intent" in out
