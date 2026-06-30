from types import SimpleNamespace
from hermit.examiner import Examiner, TestSuite, TestFile, split_suite


class FakeMessages:
    def __init__(self, suite):
        self._suite = suite
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            parsed_output=self._suite,
            usage=SimpleNamespace(input_tokens=11, output_tokens=22),
        )


class FakeClient:
    def __init__(self, suite):
        self.messages = FakeMessages(suite)


def test_write_tests_returns_suite_and_usage():
    suite = TestSuite(test_plan="verify add", tests=[TestFile(path="test_add.py", content="...")])
    client = FakeClient(suite)
    ex = Examiner(client, model="claude-sonnet-4-6")
    result = ex.write_tests("build an add() function")
    assert result.suite.tests[0].path == "test_add.py"
    assert result.input_tokens == 11 and result.output_tokens == 22
    # goal text is forwarded into the prompt
    sent = client.messages.last_kwargs
    assert sent["model"] == "claude-sonnet-4-6"
    assert sent["output_format"] is TestSuite
    assert "build an add() function" in sent["messages"][0]["content"]


def test_split_suite_is_deterministic_and_keeps_visible_nonempty():
    files = [TestFile(path=f"test_{c}.py", content="x") for c in "dcba"]
    visible, holdout = split_suite(files, holdout_fraction=0.25)
    assert [f.path for f in visible] == ["test_a.py", "test_b.py", "test_c.py"]
    assert [f.path for f in holdout] == ["test_d.py"]


def test_split_suite_zero_fraction_holds_out_nothing():
    files = [TestFile(path="test_a.py", content="x")]
    visible, holdout = split_suite(files, holdout_fraction=0.0)
    assert len(visible) == 1 and holdout == []


def test_split_suite_full_fraction_single_file_keeps_visible():
    # frac=1.0 on a single file must NOT empty the visible set (else the loop has nothing to converge on).
    files = [TestFile(path="test_a.py", content="x")]
    visible, holdout = split_suite(files, holdout_fraction=1.0)
    assert len(visible) == 1 and holdout == []


def test_split_suite_zero_fraction_multi_file_holds_out_nothing():
    files = [TestFile(path=f"test_{c}.py", content="x") for c in "dcba"]
    visible, holdout = split_suite(files, holdout_fraction=0.0)
    assert [f.path for f in visible] == ["test_a.py", "test_b.py", "test_c.py", "test_d.py"]
    assert holdout == []
