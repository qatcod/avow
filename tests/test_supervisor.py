from types import SimpleNamespace
from avow.supervisor import review_trajectory, SupervisorVerdict


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=5, output_tokens=6))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def _rec(iteration, score, is_green, plan, failing):
    return SimpleNamespace(iteration=iteration, score=score, is_green=is_green, plan=plan, failing=failing)


def test_review_trajectory_returns_verdict():
    v = SupervisorVerdict(assessment="stuck on edge cases", recommendation="redirect", escalate=False)
    client = FakeClient(v)
    history = [_rec(1, 0.5, False, "tried X", ["test_a"]), _rec(2, 0.5, False, "tried Y", ["test_a"])]
    verdict, in_tok, out_tok = review_trajectory("build slugify", history, client, "claude-opus-4-8")
    assert verdict is v and in_tok == 5 and out_tok == 6
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is SupervisorVerdict
    content = sent["messages"][0]["content"]
    assert "build slugify" in content and "tried X" in content   # goal + trajectory forwarded


def test_review_trajectory_noop_without_client():
    assert review_trajectory("g", [], None, "m") == (None, 0, 0)
