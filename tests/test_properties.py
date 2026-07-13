from types import SimpleNamespace
from avow.properties import generate_property_tests, _PropertySet
from avow.examiner import TestFile


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._payload,
            usage=SimpleNamespace(input_tokens=15, output_tokens=25),
        )


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_generate_property_tests_returns_files_and_tokens():
    payload = _PropertySet(tests=[
        TestFile(path="test_prop_comm.py",
                 content="from lib import add\nfrom hypothesis import given, strategies as st\n"
                         "@given(st.integers(), st.integers())\n"
                         "def test_commutative(a, b):\n    assert add(a, b) == add(b, a)\n"),
    ])
    client = FakeClient(payload)
    files, in_tok, out_tok = generate_property_tests("build a commutative add(a, b)",
                                                     client, "claude-opus-4-8", 4)
    assert len(files) == 1 and isinstance(files[0], TestFile)
    assert files[0].path == "test_prop_comm.py"
    assert in_tok == 15 and out_tok == 25
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is _PropertySet
    content = sent["messages"][0]["content"]
    assert "build a commutative add(a, b)" in content
    assert "hypothesis" in content.lower()  # the prompt instructs Hypothesis usage


def test_generate_property_tests_noop_without_client_or_count():
    assert generate_property_tests("g", None, "m", 4) == ([], 0, 0)
    assert generate_property_tests("g", object(), "m", 0) == ([], 0, 0)
