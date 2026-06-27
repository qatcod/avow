from pathlib import Path
from types import SimpleNamespace
import forge.cli as cli
from forge.examiner import TestSuite, TestFile
from forge.builder import BuilderOutcome


class DispatchClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        name = output_format.__name__
        if name == "TestSuite":
            po = TestSuite(test_plan="add", tests=[TestFile(
                path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        elif name == "_InferredGoal":
            from forge.backtranslation import _InferredGoal
            po = _InferredGoal(inferred_goal="add two integers")
        elif name == "IntentMatch":
            from forge.backtranslation import IntentMatch
            po = IntentMatch(score=0.9, divergences=[])
        elif name == "_PropertySet":
            from forge.properties import _PropertySet
            po = _PropertySet(tests=[])
        else:  # _OraclePair
            from forge.oracle import _OraclePair
            po = _OraclePair(reference_code="def add(a, b):\n    return a + b\n",
                             diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                             "from hypothesis import given, strategies as st\n"
                                             "@given(st.integers(), st.integers())\n"
                                             "def test_d(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def test_forge_harden_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: DispatchClient())
    monkeypatch.setattr(cli, "Builder", StubBuilder)

    rc = cli.main(["harden", str(tmp_path), "--config", str(_cfg(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0
    assert "adversarial_rounds=" in out
    assert "round 0" in out


def _cfg(tmp_path):
    p = tmp_path / "forge.yaml"
    p.write_text("adversarial_rounds: 1\nholdout_fraction: 0.0\nmax_iterations: 5\n")
    return p
