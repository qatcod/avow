from pathlib import Path
from avow.report import discover, run_report
from avow.config import RunConfig


def _mini_repo(tmp_path: Path):
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("")
    (tmp_path / "mypkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from mypkg.calc import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    # noise that must be excluded from source discovery
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("x = 1\n")
    return tmp_path


def test_discover_separates_source_and_tests(tmp_path):
    _mini_repo(tmp_path)
    tests, sources = discover(tmp_path)
    assert any(f.name == "calc.py" for f in sources)
    assert Path("tests/test_calc.py") in tests
    assert not any(f.name.startswith("test_") for f in sources)   # tests excluded from source
    assert not any(".venv" in f.parts for f in sources)           # skip-dirs excluded


def test_report_on_package_repo_mutates_nested_source(tmp_path):
    _mini_repo(tmp_path)
    rep = run_report(tmp_path, RunConfig())
    assert rep.baseline_green is True                # the repo's own suite passes on its own code
    assert rep.total > 0                             # it found + mutated the NESTED package source
    assert any(f.name == "calc.py" for f in rep.source_files)
    # the strong little suite kills the add->sub and return->None mutants
    assert rep.score == 1.0 and not rep.survivors


def test_report_missing_tests_is_honest(tmp_path):
    (tmp_path / "lib.py").write_text("def f():\n    return 1\n")   # source but no tests
    rep = run_report(tmp_path, RunConfig())
    assert rep.baseline_green is False and "no test files" in rep.detail


def test_report_cli_prints_line_numbered_gaps(tmp_path, monkeypatch, capsys):
    import avow.report as rmod
    import avow.cli as cli
    from avow.report import RepoReport
    from avow.mutation import Survivor
    rep = RepoReport(True, 0.75, 4, 3,
                     survivors=[Survivor("mypkg/calc.py", "Const 0->1", "ast", 12)],
                     source_files=[Path("mypkg/calc.py")], test_files=[Path("tests/test_calc.py")])
    monkeypatch.setattr(rmod, "run_report",
                        lambda repo, config, max_ast_mutants=None, source_override=None, tests_override=None: rep)
    assert cli.main(["report", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "suite strength (mutation): 0.75" in out
    assert "mypkg/calc.py" in out and "line 12" in out


def test_report_baseline_not_green_is_actionable(tmp_path):
    (tmp_path / "lib.py").write_text("def f():\n    return 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_f.py").write_text("import totally_missing_dep_xyz\ndef test_f():\n    assert True\n")
    rep = run_report(tmp_path, RunConfig())
    assert rep.baseline_green is False
    # the report says WHY and points at a fix, not a bare "not green"
    assert "not green" in rep.detail
    assert "missing import" in rep.detail or "pip install" in rep.detail


def test_report_source_override_targets_given_files(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "m.py").write_text("def g(x):\n    return x + 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_g.py").write_text("from pkg.m import g\ndef test_g():\n    assert g(1) == 2\n")
    rep = run_report(tmp_path, RunConfig(), source_override=["pkg/m.py"])
    assert rep.baseline_green is True
    assert [f.name for f in rep.source_files] == ["m.py"]   # only the overridden file, not __init__


def test_report_cli_passes_overrides(tmp_path, monkeypatch):
    import avow.report as rmod
    import avow.cli as cli
    from avow.report import RepoReport
    captured = {}

    def fake(repo, config, max_ast_mutants=None, source_override=None, tests_override=None):
        captured.update(source=source_override, tests=tests_override)
        return RepoReport(True, 1.0, 1, 1)

    monkeypatch.setattr(rmod, "run_report", fake)
    cli.main(["report", str(tmp_path), "--source", "src/pkg", "--tests", "tests"])
    assert captured["source"] == ["src/pkg"] and captured["tests"] == ["tests"]
