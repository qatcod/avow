from hermit.scoring import parse_report, TestResult, FailureInfo


def _report(tests):
    return {"summary": {"total": len(tests)}, "tests": tests}


def test_all_pass_is_green():
    r = parse_report(_report([
        {"nodeid": "tests/test_a.py::test_one", "outcome": "passed"},
        {"nodeid": "tests/test_a.py::test_two", "outcome": "passed"},
    ]))
    assert r.passed == 2 and r.failed == 0 and r.errors == 0 and r.total == 2
    assert r.score == 1.0
    assert r.is_green is True
    assert r.failures == []


def test_partial_credit_and_failure_messages():
    r = parse_report(_report([
        {"nodeid": "t::a", "outcome": "passed"},
        {"nodeid": "t::b", "outcome": "failed",
         "call": {"longrepr": "AssertionError: expected 3 got 4"}},
        {"nodeid": "t::c", "outcome": "error",
         "setup": {"longrepr": "ImportError: no module foo"}},
    ]))
    assert r.passed == 1 and r.failed == 1 and r.errors == 1 and r.total == 3
    assert r.score == 1 / 3
    assert r.is_green is False
    msgs = {f.nodeid: f.message for f in r.failures}
    assert "expected 3 got 4" in msgs["t::b"]
    assert "no module foo" in msgs["t::c"]


def test_empty_suite_scores_zero_and_is_not_green():
    r = parse_report(_report([]))
    assert r.total == 0 and r.score == 0.0 and r.is_green is False
