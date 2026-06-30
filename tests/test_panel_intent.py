from pathlib import Path
from types import SimpleNamespace
import pytest
from hermit.panel import panel_intent_check, PanelIntentResult
from hermit.backtranslation import _InferredGoal, IntentMatch


class FakePanelClient:
    """Back-translate -> _InferredGoal; judge -> a per-model score + a per-model divergence."""
    def __init__(self, per_model):
        self.per_model = per_model

    @property
    def messages(self):
        return self

    def parse(self, *, model, output_format, **kwargs):
        if output_format is _InferredGoal:
            po = _InferredGoal(inferred_goal="add two numbers")
        else:
            po = IntentMatch(score=self.per_model[model], divergences=[f"div_{model}"])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=2, output_tokens=3))


def test_panel_intent_check_aggregates(tmp_path: Path):
    tests = tmp_path / "frozen"
    tests.mkdir()
    (tests / "test_add.py").write_text("def test_add():\n    assert add(2, 3) == 5\n")
    client = FakePanelClient({"m1": 0.9, "m2": 0.7, "m3": 0.8})
    r = panel_intent_check("build add", tests, client, ["m1", "m2", "m3"])
    assert isinstance(r, PanelIntentResult)
    assert r.score == pytest.approx((0.9 + 0.7 + 0.8) / 3)
    assert r.agreement == pytest.approx(1.0 - (0.9 - 0.7))  # 0.8
    assert r.inferred_goal == "add two numbers"
    assert set(r.divergences) == {"div_m1", "div_m2", "div_m3"}
    # usage: back_translate (m1) + 3 judges = 4 entries, each (model, 2, 3)
    assert len(r.usage) == 4
    assert ("m1", 2, 3) in r.usage and ("m3", 2, 3) in r.usage
