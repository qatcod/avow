from pathlib import Path
from avow.gauntlet import _extract_falsifying_example, _run_diff, Counterexample

TEST_CMD = ["python", "-m", "pytest", "-q"]

_DIFF = ("from lib import f as _sol\nfrom ref import f as _ref\n"
         "from hypothesis import given, strategies as st\n"
         "@given(st.integers())\ndef test_diff(x):\n    assert _sol(x) == _ref(x)\n")


def test_extract_falsifying_example():
    out = "some noise\nFalsifying example: test_diff(x=0)\nmore noise\n"
    assert _extract_falsifying_example(out) == "test_diff(x=0)"
    assert _extract_falsifying_example("no example here") == ""


def test_run_diff_agree(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    outcome, _ = _run_diff(tmp_path, "def f(x):\n    return x + 1\n", _DIFF, 50, TEST_CMD, 60)
    assert outcome == "agree"


def test_run_diff_diverge_gives_falsifying(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 2\n")   # WRONG vs reference
    outcome, falsifying = _run_diff(tmp_path, "def f(x):\n    return x + 1\n", _DIFF, 50, TEST_CMD, 60)
    assert outcome == "diverge"
    assert "test_diff(" in falsifying


def test_run_diff_broken_reference_is_unusable(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    outcome, _ = _run_diff(tmp_path, "def broken(:\n", _DIFF, 50, TEST_CMD, 60)  # syntax error
    assert outcome == "unusable"
