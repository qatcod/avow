from types import SimpleNamespace
from avow.backtranslation import back_translate, _InferredGoal


class FakeMessages:
    def __init__(self, inferred):
        self._inferred = inferred
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=_InferredGoal(inferred_goal=self._inferred),
            usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        )


class FakeClient:
    def __init__(self, inferred):
        self.messages = FakeMessages(inferred)


def test_back_translate_returns_goal_and_tokens():
    client = FakeClient("Add two integers and return the sum.")
    inferred, in_tok, out_tok = back_translate(
        "def test_add():\n    assert add(2, 3) == 5\n", client, "claude-opus-4-8")
    assert inferred == "Add two integers and return the sum."
    assert in_tok == 12 and out_tok == 8
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _InferredGoal
    # The suite text is forwarded; the prompt must NOT contain a separate goal.
    assert "assert add(2, 3) == 5" in sent["messages"][0]["content"]
