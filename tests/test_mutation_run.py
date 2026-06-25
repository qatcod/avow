from pathlib import Path
from forge.mutation import run_mutation_testing


CMD = ["python", "-m", "pytest", "-q"]


def _make(tmp_path: Path, solution_src: str, test_src: str):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text(solution_src)
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "test_lib.py").write_text(test_src)
    return sol, frozen


def test_strong_suite_kills_all(tmp_path: Path):
    sol, frozen = _make(
        tmp_path, "def add(a, b):\n    return a + b\n",
        "from lib import add\n"
        "def test_pos(): assert add(2, 3) == 5\n"
        "def test_neg(): assert add(-1, 1) == 0\n",
    )
    r = run_mutation_testing(sol, frozen, CMD)
    assert r.total >= 1
    assert r.score == 1.0 and r.survivors == []


def test_weak_suite_leaves_a_survivor(tmp_path: Path):
    # add(5, 0) == 5 holds for BOTH a+b and a-b, so the Add->Sub mutant survives.
    sol, frozen = _make(
        tmp_path, "def add(a, b):\n    return a + b\n",
        "from lib import add\n"
        "def test_identity(): assert add(5, 0) == 5\n",
    )
    r = run_mutation_testing(sol, frozen, CMD)
    assert r.survived >= 1 and r.score < 1.0
    assert any("BinOp Add->Sub" in s.description for s in r.survivors)
    assert all(s.origin == "ast" for s in r.survivors)


def test_no_mutants_scores_vacuously_one(tmp_path: Path):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("import os\n")  # no mutatable nodes
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "test_x.py").write_text("def test_ok(): assert True\n")
    r = run_mutation_testing(sol, frozen, CMD)
    assert r.total == 0 and r.score == 1.0 and r.survivors == []
