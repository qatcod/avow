from types import SimpleNamespace
from avow.backtranslation import judge_intent_match, IntentMatch


class FakeMessages:
    def __init__(self, match):
        self._match = match
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._match,
            usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        )


class FakeClient:
    def __init__(self, match):
        self.messages = FakeMessages(match)


def test_judge_returns_match_and_tokens():
    client = FakeClient(IntentMatch(score=0.4, divergences=["missing negative-input handling"]))
    match, in_tok, out_tok = judge_intent_match(
        "Build a robust adder.", "Add two numbers.", client, "claude-opus-4-8")
    assert isinstance(match, IntentMatch)
    assert match.score == 0.4 and match.divergences == ["missing negative-input handling"]
    assert in_tok == 20 and out_tok == 5
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is IntentMatch
    content = sent["messages"][0]["content"]
    assert "Build a robust adder." in content and "Add two numbers." in content
