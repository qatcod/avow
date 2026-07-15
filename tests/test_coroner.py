from types import SimpleNamespace
from avow.coroner import abstract_counterexample
from avow.graveyard import AttackPattern
from avow.gauntlet import Counterexample


class _FakeCoroner:
    def __init__(self):
        self.last_content = None

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        assert output_format is AttackPattern
        self.last_content = kwargs["messages"][0]["content"]
        po = AttackPattern(category="numeric-boundary",
                           description="probe where a numeric field meets a longer numeric field",
                           origin_goal="semver compare", example_input="test_diff(a='2', b='11')")
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=3, output_tokens=4))


def _cx():
    return Counterexample(input_repr="test_diff(a='2', b='11')",
                          reference_code="def cmp(a, b): ...", diff_test_code="...")


def test_abstract_produces_pattern_and_tokens():
    client = _FakeCoroner()
    pattern, i, o = abstract_counterexample(_cx(), "compare semver strings", client, "m")
    assert isinstance(pattern, AttackPattern)
    assert pattern.category == "numeric-boundary" and pattern.description
    assert i == 3 and o == 4
    assert "compare semver strings" in client.last_content and "test_diff(a='2', b='11')" in client.last_content


def test_abstract_no_client_is_noop():
    assert abstract_counterexample(_cx(), "goal", None, "m") == (None, 0, 0)
