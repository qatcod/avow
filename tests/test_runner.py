from pathlib import Path
from forge.runner import Runner


def _make_goal(tmp_path: Path, solution_src: str):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "lib.py").write_text(solution_src)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "test_lib.py").write_text(
        "from lib import add\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )
    return solution, frozen


def test_runner_reports_pass(tmp_path: Path):
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a + b\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    assert r.is_green is True and r.passed == 1


def test_runner_reports_fail(tmp_path: Path):
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a - b\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    assert r.is_green is False and r.failed == 1
    assert any("test_add" in f.nodeid for f in r.failures)


def test_runner_restores_tests_each_run(tmp_path: Path):
    # Broken solution: the REAL frozen test (add(2, 3) == 5) must FAIL.
    solution, frozen = _make_goal(tmp_path, "def add(a, b):\n    return a - b\n")
    # Builder tampering: a trivially-passing fake that would hide the bug if it survived the run.
    (solution / "tests").mkdir(exist_ok=True)
    (solution / "tests" / "test_lib.py").write_text("def test_add():\n    assert True\n")
    r = Runner(solution, frozen, ["python", "-m", "pytest", "-q"]).run()
    # The frozen test was restored over the fake, so the real (failing) assertion ran.
    assert r.is_green is False and r.failed == 1
    assert any("test_add" in f.nodeid for f in r.failures)
