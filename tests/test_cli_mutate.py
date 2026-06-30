from pathlib import Path
from hermit.cli import main


def test_mutate_offline_ast_only(tmp_path: Path, capsys):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "test_lib.py").write_text(
        "from lib import add\n"
        "def test_identity(): assert add(5, 0) == 5\n"  # weak: lets Add->Sub survive
    )
    rc = main(["mutate", str(sol), str(frozen)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "mutation score:" in out
    assert "survivors" in out
    assert "BinOp Add->Sub" in out


def test_mutate_reports_unscorable_when_suite_red(tmp_path, capsys):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "test_lib.py").write_text(
        "from lib import add\ndef test_it(): assert add(2, 3) == 5\n"
    )
    rc = main(["mutate", str(sol), str(frozen)])
    out = capsys.readouterr().out
    assert rc != 0 and "not green" in out.lower()
