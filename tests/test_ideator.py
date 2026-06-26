from types import SimpleNamespace
from forge.ideator import propose_ideas, Idea, _IdeaSet


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._payload,
            usage=SimpleNamespace(input_tokens=11, output_tokens=22),
        )


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_propose_ideas_returns_ideas_and_tokens():
    payload = _IdeaSet(ideas=[
        Idea(description="handle unicode input", verifier="test_unicode passes", objective=True, risk="low"),
        Idea(description="make it 'nicer'", verifier="subjective", objective=False, risk="high"),
    ])
    client = FakeClient(payload)
    ideas, in_tok, out_tok = propose_ideas("build slugify", "def test_basic(): ...",
                                           client, "claude-opus-4-8", 3)
    assert len(ideas) == 2 and isinstance(ideas[0], Idea)
    assert ideas[0].objective is True and ideas[0].risk == "low"
    assert in_tok == 11 and out_tok == 22
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _IdeaSet
    content = sent["messages"][0]["content"]
    assert "build slugify" in content and "def test_basic" in content


def test_propose_ideas_noop_without_client_or_count():
    assert propose_ideas("g", "t", None, "m", 3) == ([], 0, 0)
    assert propose_ideas("g", "t", object(), "m", 0) == ([], 0, 0)
