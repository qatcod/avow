# tests/test_loop.py
from pathlib import Path
from forge.loop import solve, SolveResult
from forge.config import RunConfig
from forge.examiner import Examiner, ExaminerResult, TestSuite, TestFile
from forge.scoring import FailureInfo


# --- fakes ---------------------------------------------------------------

class StubExaminer(Examiner):
    def __init__(self):
        pass  # bypass client

    def write_tests(self, goal):
        suite = TestSuite(
            test_plan="verify add",
            tests=[TestFile(
                path="test_add.py",
                content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n",
            )],
        )
        return ExaminerResult(suite=suite, input_tokens=5, output_tokens=5)


class FlakyBuilder:
    """Fails on the first attempt (writes wrong code), fixes it on the second."""
    def __init__(self):
        self.calls = 0

    def attempt(self, solution_dir: Path, goal, failures):
        self.calls += 1
        src = "def add(a, b):\n    return a + b\n" if self.calls >= 2 else "def add(a, b):\n    return a - b\n"
        (Path(solution_dir) / "lib.py").write_text(src)
        from forge.builder import BuilderOutcome
        return BuilderOutcome(plan=f"attempt {self.calls}", cost_usd=0.01, raw={})


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


# --- tests ---------------------------------------------------------------

def test_loop_converges_to_green(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    builder = FlakyBuilder()
    result = solve(_goal(tmp_path), cfg, StubExaminer(), builder, now=lambda: 0.0)
    assert isinstance(result, SolveResult)
    assert result.success is True
    assert result.reason == "green"
    assert result.best_score == 1.0
    assert builder.calls == 2          # failed once, fixed on the second
    assert (result.best_dir / "lib.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_loop_stops_at_max_iterations_when_never_green(tmp_path: Path):
    class AlwaysWrong:
        def attempt(self, solution_dir, goal, failures):
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return 0\n")
            from forge.builder import BuilderOutcome
            return BuilderOutcome(plan="nope", cost_usd=0.01, raw={})

    cfg = RunConfig(max_iterations=3, plateau_patience=99, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrong(), now=lambda: 0.0)
    assert result.success is False
    assert result.reason in {"max_iterations", "plateau"}
    assert result.iterations == 3


def test_loop_writes_frozen_tests_and_run_log(tmp_path: Path):
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0)
    solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert (tmp_path / "tests_frozen" / "test_add.py").exists()
    log = (tmp_path / ".forge" / "run.jsonl").read_text().strip().splitlines()
    assert len(log) >= 1


def test_loop_reports_mutation_score_on_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert result.success is True
    # best solution is `return a + b`; the frozen test `add(2,3)==5` kills Add->Sub and Return->None.
    assert result.mutation_score == 1.0
    assert result.survivors == 0
