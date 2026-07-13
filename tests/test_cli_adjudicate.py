from pathlib import Path
from types import SimpleNamespace
import avow.cli as cli
from avow.oracle import _OraclePair


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        return SimpleNamespace(
            parsed_output=_OraclePair(reference_code="def add(a, b):\n    return a + b\n", diff_test_code="x"),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_adjudicate_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a + b\n")          # correct solution
    tests = tmp_path / "tests"; tests.mkdir()
    (tests / "test_bad.py").write_text("from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n")  # contradictory

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["adjudicate", str(sol), str(tests), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "test_bad" in out and "TEST BUG" in out.upper()
