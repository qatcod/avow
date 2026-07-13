# tests/test_adjudicator.py
from pathlib import Path
from types import SimpleNamespace
from avow.adjudicator import adjudicate_failures
from avow.oracle import _OraclePair

CMD = ["python", "-m", "pytest", "-q"]


def _ref_client(reference_code="def add(a, b):\n    return a + b\n"):
    class C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=_OraclePair(reference_code=reference_code, diff_test_code="x"),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return C()


def test_flags_contradictory_test_as_test_bug(tmp_path):
    # a test that NO correct add can pass -> the independent references also fail it
    (tmp_path / "test_bad.py").write_text("from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n")
    r = adjudicate_failures("build add(a, b)", tmp_path, ["test_bad.py::test_bad"],
                            _ref_client(), "m", CMD, k=3)
    assert len(r.verdicts) == 1
    v = r.verdicts[0]
    assert v.verdict == "test_bug"
    assert v.references_failed == 3 and v.references_total == 3


def test_flags_real_failure_as_solution_bug(tmp_path):
    # a correct test the reference PASSES -> the solution that failed it is the outlier
    (tmp_path / "test_good.py").write_text("from lib import add\ndef test_good():\n    assert add(2, 3) == 5\n")
    r = adjudicate_failures("build add(a, b)", tmp_path, ["test_good.py::test_good"],
                            _ref_client(), "m", CMD, k=3)
    assert r.verdicts[0].verdict == "solution_bug"
    assert r.verdicts[0].references_failed == 0


def test_noop_without_client_or_failures(tmp_path):
    assert adjudicate_failures("g", tmp_path, ["x::y"], None, "m", CMD, k=3).verdicts == []
    assert adjudicate_failures("g", tmp_path, [], _ref_client(), "m", CMD, k=3).verdicts == []
