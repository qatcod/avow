from types import SimpleNamespace
from hermit.examiner import Examiner, TestSuite, TestFile


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=7, output_tokens=8))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_write_adversarial_tests_forwards_goal_and_solution():
    suite = TestSuite(test_plan="break it", tests=[TestFile(path="test_adv_edges.py", content="# adv\n")])
    client = FakeClient(suite)
    ex = Examiner(client, "claude-opus-4-8")
    res = ex.write_adversarial_tests("build slugify(s)", "def slugify(s):\n    return s.lower()\n")
    assert res.suite is suite and res.input_tokens == 7 and res.output_tokens == 8
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-opus-4-8"
    assert sent["output_format"] is TestSuite
    content = sent["messages"][0]["content"]
    assert "build slugify(s)" in content              # goal forwarded
    assert "return s.lower()" in content               # solution code forwarded
    assert "break" in content.lower()                  # adversarial framing
