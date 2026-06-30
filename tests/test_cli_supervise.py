import json
from pathlib import Path
from types import SimpleNamespace
import hermit.cli as cli
from hermit.supervisor import SupervisorVerdict


class FakeClient:
    @property
    def messages(self):
        return self

    def parse(self, **kwargs):
        return SimpleNamespace(
            parsed_output=SupervisorVerdict(assessment="goal underspecified", recommendation="escalate", escalate=True),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_supervise_cli(tmp_path, capsys, monkeypatch):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    run = tmp_path / "run.jsonl"
    run.write_text(
        json.dumps({"iteration": 1, "score": 0.0, "is_green": False, "plan": "tried subtract", "failing": ["test_add"]}) + "\n"
        + json.dumps({"iteration": 2, "score": 0.0, "is_green": False, "plan": "tried again", "failing": ["test_add"]}) + "\n")

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClient())

    rc = cli.main(["supervise", str(run), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "escalate" in out.lower()
    assert "goal underspecified" in out
