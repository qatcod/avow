from pathlib import Path
from types import SimpleNamespace
import avow.cli as cli
from avow.examiner import TestSuite, TestFile
from avow.properties import _PropertySet
from avow.backtranslation import _InferredGoal, IntentMatch
from avow.oracle import _OraclePair
from avow.builder import BuilderOutcome


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
        elif output_format is _OraclePair:
            # the suite-independent oracle: an independent (correct) reference + a diff test
            po = _OraclePair(
                reference_code="def add(a, b):\n    return a + b\n",
                diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                "from hypothesis import given, strategies as st\n"
                                "@given(st.integers(), st.integers())\n"
                                "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
        else:  # IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_avow_solve_activates_intent_property_and_oracle(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["solve", str(tmp_path), "--yes"])
    out = capsys.readouterr().out
    # property test was generated INTO the frozen suite (the build had to satisfy it):
    assert (tmp_path / "tests_frozen" / "test_prop_comm.py").exists()
    # the run succeeded with all default LLM signals active — intent 0.9, mutation/holdout 1.0,
    # AND the reference oracle (correct reference agrees, so it doesn't flag the correct solution):
    assert rc == 0
    assert "confidence:" in out
