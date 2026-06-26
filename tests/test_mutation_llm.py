from types import SimpleNamespace
from forge.mutation import llm_mutants, Mutant, _MutantList, _MutantSpec


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._payload,
            usage=SimpleNamespace(input_tokens=30, output_tokens=40),
        )


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_llm_mutants_returns_mutants_and_tokens():
    payload = _MutantList(mutants=[
        _MutantSpec(description="off-by-one", source="def add(a, b):\n    return a + b + 1\n"),
        _MutantSpec(description="swapped", source="def add(a, b):\n    return a - b\n"),
    ])
    client = FakeClient(payload)
    mutants, in_tok, out_tok = llm_mutants("def add(a, b):\n    return a + b\n",
                                           "build add", client, "claude-sonnet-4-6", 2)
    assert len(mutants) == 2
    assert all(isinstance(m, Mutant) and m.origin == "llm" for m in mutants)
    assert mutants[0].description.startswith("LLM: ")
    assert in_tok == 30 and out_tok == 40
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-sonnet-4-6"
    assert sent["output_format"] is _MutantList
    assert "build add" in sent["messages"][0]["content"]


def test_llm_mutants_noop_without_client_or_count():
    assert llm_mutants("x", "g", None, "m", 3) == ([], 0, 0)
    assert llm_mutants("x", "g", object(), "m", 0) == ([], 0, 0)
