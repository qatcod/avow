from pathlib import Path
from types import SimpleNamespace
import avow.cli as cli
from avow.properties import _PropertySet
from avow.examiner import TestFile


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _PropertySet(tests=[TestFile(
            path="test_prop_roundtrip.py",
            content="from lib import f\nfrom hypothesis import given, strategies as st\n"
                    "@given(st.text())\ndef test_roundtrip(x):\n    assert f(f(x)) == x\n")])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_propertize_cli(tmp_path: Path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build an involution f where f(f(x)) == x.")
    out = tmp_path / "props"

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["propertize", str(tmp_path / "goal.md"), str(out)])
    output = capsys.readouterr().out
    assert rc == 0
    assert (out / "test_prop_roundtrip.py").exists()
    assert "test_prop_roundtrip.py" in output
