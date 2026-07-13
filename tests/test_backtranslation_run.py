from pathlib import Path
from types import SimpleNamespace
from avow.backtranslation import run_intent_check, IntentResult, _InferredGoal, IntentMatch


class DispatchingClient:
    """Returns an _InferredGoal for step 1, an IntentMatch for step 2; tracks call order."""
    def __init__(self, inferred, score, divergences):
        self.inferred, self.score, self.divergences = inferred, score, divergences
        self.formats = []

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        self.formats.append(output_format)
        if output_format is _InferredGoal:
            po = _InferredGoal(inferred_goal=self.inferred)
        else:
            po = IntentMatch(score=self.score, divergences=self.divergences)
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=7, output_tokens=9))


def test_run_intent_check_aggregates(tmp_path: Path):
    tests = tmp_path / "frozen"
    tests.mkdir()
    (tests / "test_add.py").write_text("def test_add():\n    assert add(2, 3) == 5\n")
    (tests / "test_neg.py").write_text("def test_neg():\n    assert add(-1, 1) == 0\n")
    client = DispatchingClient("Add two integers.", 0.75, ["no overflow check"])
    r = run_intent_check("Build add(a, b).", tests, client, "claude-opus-4-8")
    assert isinstance(r, IntentResult)
    assert r.score == 0.75
    assert r.inferred_goal == "Add two integers."
    assert r.divergences == ["no overflow check"]
    assert r.input_tokens == 14 and r.output_tokens == 18  # 7+7, 9+9
    assert client.formats == [_InferredGoal, IntentMatch]  # blind first, then judge
