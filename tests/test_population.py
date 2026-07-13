# tests/test_population.py
from pathlib import Path
from avow.config import RunConfig
from avow.population import population_solve, hybrid_solve, PopulationResult
from avow.examiner import ExaminerResult, TestSuite, TestFile
from avow.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


class StubExaminer:
    def write_tests(self, goal):
        return ExaminerResult(suite=TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")]),
            input_tokens=0, output_tokens=0)


class GoodBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class BadBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a - b\n")  # wrong
        return BuilderOutcome(plan="nope", cost_usd=0.0, raw={})


def test_population_runs_candidates_and_selects(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=2)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert isinstance(r, PopulationResult)
    assert r.success is True
    assert len(r.candidates) == 2
    assert r.winner_index in (0, 1)
    assert (tmp_path / ".avow" / "best" / "lib.py").exists()           # winner promoted
    assert (tmp_path / ".avow" / "candidates" / "1" / "tests_frozen").exists()  # candidate 1 staged with a suite copy


def test_population_size_one_is_single_solve(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=1)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 1 and r.winner_index == 0


def test_hybrid_does_not_escalate_when_first_is_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=3)
    r = hybrid_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 1   # green on first -> no population


def test_hybrid_escalates_on_failure(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, population_size=2)
    r = hybrid_solve(_goal(tmp_path), cfg, StubExaminer(), BadBuilder(), now=lambda: 0.0)
    assert r.success is False and len(r.candidates) == 2   # first failed -> escalated to the pool


def test_population_parallel_outcome_matches(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=3, max_parallel_candidates=4)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True
    assert len(r.candidates) == 3
    assert [c.index for c in r.candidates] == [0, 1, 2]   # index order preserved (deterministic)
    assert (tmp_path / ".avow" / "best" / "lib.py").exists()
    assert (tmp_path / ".avow" / "candidates" / "1" / "tests_frozen").exists()
    assert (tmp_path / ".avow" / "candidates" / "2" / "tests_frozen").exists()


def test_population_sequential_when_max_parallel_one(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, population_size=2, max_parallel_candidates=1)
    r = population_solve(_goal(tmp_path), cfg, StubExaminer(), GoodBuilder(), now=lambda: 0.0)
    assert r.success is True and len(r.candidates) == 2 and [c.index for c in r.candidates] == [0, 1]


def test_pool_tolerates_a_failing_candidate(tmp_path):
    from types import SimpleNamespace
    from avow.population import _run_candidate_pool, Candidate

    (tmp_path / "goal.md").write_text("Build add(a, b).")
    (tmp_path / "tests_frozen").mkdir()
    (tmp_path / "tests_frozen" / "test_add.py").write_text(
        "from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    (tmp_path / "tests_holdout").mkdir()
    best0 = tmp_path / ".avow" / "best"
    best0.mkdir(parents=True)
    (best0 / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    cand0 = Candidate(0, SimpleNamespace(success=True, confidence=1.0, best_score=1.0,
                                         reason="green", confidence_breakdown={}), best0)

    class RaisingBuilder:
        def __init__(self, *a, **k):
            pass

        def attempt(self, *a, **k):
            raise RuntimeError("boom")

    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0, population_size=2, max_parallel_candidates=2)
    clients = dict(mutation_client=None, intent_client=None, property_client=None, oracle_client=None)
    r = _run_candidate_pool(tmp_path, cfg, StubExaminer(), RaisingBuilder(), [cand0], clients, lambda: 0.0)
    # candidate 1 crashed but did not abort the pool; candidate 0 (green) wins.
    assert r.winner_index == 0 and r.success is True and len(r.candidates) == 2
