from pathlib import Path
from types import SimpleNamespace
import forge.cli as cli
from forge.oracle import _OraclePair


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        pair = _OraclePair(
            reference_code="def add(a, b):\n    return a + b\n",
            diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                            "from hypothesis import given, strategies as st\n"
                            "@given(st.integers(), st.integers())\n"
                            "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
        return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_oracle_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["oracle", str(tmp_path), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "oracle agreement: 1.0" in out
