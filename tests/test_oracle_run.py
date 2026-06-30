# tests/test_oracle_run.py
from pathlib import Path
from types import SimpleNamespace
from hermit.oracle import run_oracle_check, _OraclePair

_DIFF = ("from lib import add as _sol\n"
         "from ref import add as _ref\n"
         "from hypothesis import given, strategies as st\n"
         "@given(st.integers(), st.integers())\n"
         "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


def _client(reference_code):
    pair = _OraclePair(reference_code=reference_code, diff_test_code=_DIFF)

    class C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(parsed_output=pair,
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return C()


def _solution(tmp_path):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    return tmp_path


CMD = ["python", "-m", "pytest", "-q"]


def test_oracle_agrees(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a + b\n"),
                         "m", CMD, timeout=120)
    assert r.agreement == 1.0 and r.baseline_ok is True and r.counterexample == ""


def test_oracle_disagrees(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a * b\n"),
                         "m", CMD, timeout=120)
    assert r.agreement == 0.0 and r.baseline_ok is True and r.counterexample != ""


def test_oracle_inconclusive_on_broken_reference(tmp_path):
    sol = _solution(tmp_path)
    r = run_oracle_check(sol, "add(a,b)", _client("def add(a, b):\n    return a +\n"),  # syntax error
                         "m", CMD, timeout=120)
    assert r.agreement is None and r.baseline_ok is False


def test_oracle_inconclusive_without_client(tmp_path):
    r = run_oracle_check(_solution(tmp_path), "add", None, "m", CMD, timeout=120)
    assert r.agreement is None and r.checked is False
