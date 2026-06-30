import json
import subprocess
from pathlib import Path
from hermit.builder import Builder, BuilderOutcome
from hermit.scoring import FailureInfo


def test_attempt_invokes_claude_and_parses_json(tmp_path: Path):
    captured = {}

    def fake_runner(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(
            cmd, returncode=0,
            stdout=json.dumps({"result": "I added lib.py", "total_cost_usd": 0.04}),
            stderr="",
        )

    b = Builder(model="claude-opus-4-8", runner=fake_runner)
    out = b.attempt(tmp_path, "build add()", [FailureInfo("t::add", "expected 5 got -1")])

    assert isinstance(out, BuilderOutcome)
    assert out.plan == "I added lib.py"
    assert out.cost_usd == 0.04
    assert captured["cwd"] == tmp_path
    assert captured["cmd"][0] == "claude"
    assert "--dangerously-skip-permissions" in captured["cmd"]
    assert "claude-opus-4-8" in captured["cmd"]
    prompt = captured["cmd"][2]
    assert "build add()" in prompt
    assert "expected 5 got -1" in prompt  # failures fed back in


def test_attempt_tolerates_missing_cost_field(tmp_path: Path):
    def fake_runner(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "done"}), stderr="")

    out = Builder(model="claude-opus-4-8", runner=fake_runner).attempt(tmp_path, "goal", [])
    assert out.cost_usd == 0.0 and out.plan == "done"


def test_attempt_handles_nonjson_stdout(tmp_path: Path):
    def fake_runner(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, stdout="boom not json", stderr="err")

    out = Builder(model="claude-opus-4-8", runner=fake_runner).attempt(tmp_path, "goal", [])
    assert out.cost_usd == 0.0
    assert "boom not json" in out.plan or "err" in out.plan
