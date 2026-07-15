from types import SimpleNamespace
from pathlib import Path
import avow.cli as cli


def test_survive_cli_reports_status(tmp_path, monkeypatch, capsys):
    (tmp_path / "goal.md").write_text("Build add(a, b).")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: "CLIENT")
    monkeypatch.setattr(cli, "build_examiner", lambda cfg: object())
    monkeypatch.setattr(cli, "Builder", lambda *a, **k: object())
    import avow.survive as s
    monkeypatch.setattr(s, "survive",
                        lambda *a, **k: SimpleNamespace(status="verified_survivor", rounds=2,
                                                        death_counterexample=None))
    rc = cli.main(["survive", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "status=verified_survivor" in out and "not a proof of correctness" in out.lower()


def test_gauntlet_cli_reports_kill(tmp_path, monkeypatch, capsys):
    (tmp_path / "goal.md").write_text("f(x) returns x+1")
    (tmp_path / "lib.py").write_text("def f(x):\n    return x\n")
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: "CLIENT")
    import avow.gauntlet as gt
    from avow.gauntlet import Counterexample
    cx = Counterexample("test_diff(x=0)", "def f(x):\n    return x + 1\n", "diff")
    monkeypatch.setattr(gt, "run_gauntlet",
                        lambda *a, **k: SimpleNamespace(survived=False, counterexample=cx,
                                                        references_ok=3, references_total=4,
                                                        input_tokens=0, output_tokens=0))
    rc = cli.main(["gauntlet", str(tmp_path), str(tmp_path / "goal.md")])
    out = capsys.readouterr().out
    assert rc == 2 and "KILLED" in out and "test_diff(x=0)" in out


def test_graveyard_cli_lists_patterns(tmp_path, capsys):
    from avow.graveyard import record, AttackPattern
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe range boundaries"), gy)
    record(AttackPattern(category="empty-input", description="probe empty and null inputs"), gy)
    rc = cli.main(["graveyard", "--graveyard", str(gy)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 patterns" in out
    assert "numeric-boundary" in out and "probe empty and null inputs" in out
