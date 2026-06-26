from pathlib import Path
from types import SimpleNamespace
import forge.cli as cli
from forge.examiner import TestSuite, TestFile
from forge.properties import _PropertySet
from forge.backtranslation import _InferredGoal, IntentMatch
from forge.builder import BuilderOutcome


class DispatchClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        if output_format is TestSuite:
            po = TestSuite(test_plan="add", tests=[TestFile(
                path="test_add.py",
                content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        elif output_format is _PropertySet:
            po = _PropertySet(tests=[TestFile(
                path="test_prop_comm.py",
                content=("from lib import add\nfrom hypothesis import given, strategies as st\n"
                         "@given(st.integers(), st.integers())\n"
                         "def test_comm(a, b):\n    assert add(a, b) == add(b, a)\n"))])
        elif output_format is _InferredGoal:
            po = _InferredGoal(inferred_goal="add two integers")
        else:  # IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_forge_solve_activates_intent_and_property(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["solve", str(tmp_path), "--yes"])
    out = capsys.readouterr().out
    # property test was generated INTO the frozen suite (the build had to satisfy it):
    assert (tmp_path / "tests_frozen" / "test_prop_comm.py").exists()
    # confidence is surfaced and the run succeeded (intent 0.9 + mutation 1.0 + holdout 1.0):
    assert rc == 0
    assert "confidence:" in out
