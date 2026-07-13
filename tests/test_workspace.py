from pathlib import Path
from avow.workspace import Workspace


def test_seed_empty_then_promote_then_reseed(tmp_path: Path):
    ws = Workspace(tmp_path / "ws")
    best = tmp_path / "best"

    ws.seed_from(None)
    assert ws.solution_dir.is_dir()
    assert list(ws.solution_dir.iterdir()) == []

    (ws.solution_dir / "main.py").write_text("print('v1')\n")
    ws.promote_to(best)
    assert (best / "main.py").read_text() == "print('v1')\n"

    # A regressing attempt writes junk, then we re-seed from best and the junk is gone.
    (ws.solution_dir / "junk.py").write_text("oops\n")
    ws.seed_from(best)
    assert (ws.solution_dir / "main.py").read_text() == "print('v1')\n"
    assert not (ws.solution_dir / "junk.py").exists()


def test_promote_overwrites_previous_best(tmp_path: Path):
    ws = Workspace(tmp_path / "ws")
    best = tmp_path / "best"
    ws.seed_from(None)
    (ws.solution_dir / "a.py").write_text("1\n")
    ws.promote_to(best)
    ws.seed_from(None)
    (ws.solution_dir / "b.py").write_text("2\n")
    ws.promote_to(best)
    assert not (best / "a.py").exists()
    assert (best / "b.py").read_text() == "2\n"
