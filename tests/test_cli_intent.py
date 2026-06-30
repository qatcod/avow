from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.backtranslation import _InferredGoal, IntentMatch


class DispatchingClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        if output_format is _InferredGoal:
            po = _InferredGoal(inferred_goal="add two numbers and return the sum")
        else:
            po = IntentMatch(score=0.9, divergences=["no overflow handling"])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_intent_check_cli(tmp_path: Path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_add.py").write_text("def test_add():\n    assert add(2, 3) == 5\n")

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchingClient())

    rc = cli.main(["intent-check", str(tmp_path / "goal.md"), str(tests)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "intent match: 0.90" in out
    assert "add two numbers and return the sum" in out
    assert "no overflow handling" in out
