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


from types import SimpleNamespace
from avow.gauntlet import run_gauntlet, GauntletResult
from avow.oracle import _OraclePair


class _RefClient:
    """generate_oracle client that always returns the same correct reference for f(x)=x+1."""
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _OraclePair(reference_code="def f(x):\n    return x + 1\n", diff_test_code=_DIFF)
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_run_gauntlet_survives_correct_solution(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    g = run_gauntlet(tmp_path, "f(x) returns x+1", _RefClient(), "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is True and g.counterexample is None
    assert g.references_ok == 3 and g.references_total == 3


def test_run_gauntlet_kills_wrong_solution(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 2\n")   # majority will diverge
    g = run_gauntlet(tmp_path, "f(x) returns x+1", _RefClient(), "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is False
    assert g.counterexample is not None and "test_diff(" in g.counterexample.input_repr
    assert g.counterexample.reference_code.strip().endswith("return x + 1")


def test_run_gauntlet_no_client_cannot_attack(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x\n")
    g = run_gauntlet(tmp_path, "goal", None, "m", TEST_CMD, k=3, examples=50, timeout=60)
    assert g.survived is True and g.references_ok == 0   # no attack ran -> nothing gained


class _MostlyBrokenClient:
    """One correct reference (diverges from a wrong solution) + K-1 broken (unusable) references."""
    def __init__(self):
        self.n = 0

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        self.n += 1
        if self.n == 1:
            po = _OraclePair(reference_code="def f(x):\n    return x + 1\n", diff_test_code=_DIFF)
        else:
            po = _OraclePair(reference_code="def broken(:\n", diff_test_code=_DIFF)  # syntax error -> unusable
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_run_gauntlet_lone_divergence_does_not_kill(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 2\n")   # wrong, but only 1 usable ref
    g = run_gauntlet(tmp_path, "f(x) returns x+1", _MostlyBrokenClient(), "m", TEST_CMD, k=4, examples=30, timeout=60)
    # 1 usable reference diverges, 3 unusable -> below the usable floor -> NOT a kill (no false revoke)
    assert g.survived is True and g.references_ok == 1


class _CapturingClient:
    def __init__(self):
        self.last_content = None

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        self.last_content = kwargs["messages"][0]["content"]
        po = _OraclePair(reference_code="def f(x):\n    return x + 1\n", diff_test_code=_DIFF)
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_run_gauntlet_seeds_references_with_patterns(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    c = _CapturingClient()
    run_gauntlet(tmp_path, "f(x) returns x+1", c, "m", TEST_CMD, k=1, examples=20, timeout=60,
                 patterns=["probe empty and boundary inputs"])
    assert "probe empty and boundary inputs" in c.last_content


def test_run_gauntlet_no_patterns_is_unchanged(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    c = _CapturingClient()
    run_gauntlet(tmp_path, "GOALTEXT_MARKER", c, "m", TEST_CMD, k=1, examples=20, timeout=60)
    assert "GOALTEXT_MARKER" in c.last_content and "known-tricky" not in c.last_content
