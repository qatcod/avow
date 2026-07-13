from types import SimpleNamespace
from avow.oracle import generate_oracle, _OraclePair


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=9, output_tokens=13))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_generate_oracle_returns_pair_and_tokens():
    payload = _OraclePair(reference_code="def add(a, b):\n    return a + b\n",
                          diff_test_code="# diff test\n")
    client = FakeClient(payload)
    pair, in_tok, out_tok = generate_oracle("build add(a, b)", client, "claude-opus-4-8")
    assert pair is payload and in_tok == 9 and out_tok == 13
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _OraclePair
    content = sent["messages"][0]["content"]
    assert "build add(a, b)" in content
    assert "from lib import" in content and "from ref import" in content  # the prompt pins the imports


def test_generate_oracle_noop_without_client():
    assert generate_oracle("g", None, "m") == (None, 0, 0)
