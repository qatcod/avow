# tests/test_improve.py
from pathlib import Path
from types import SimpleNamespace
from forge.config import RunConfig
from forge.improve import improve, ImproveResult
from forge.examiner import ExaminerResult, TestSuite, TestFile
from forge.ideator import _IdeaSet, Idea
from forge.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


class StubExaminer:
    def write_tests(self, goal: str) -> ExaminerResult:
        suite = TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py",
            content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        return ExaminerResult(suite=suite, input_tokens=0, output_tokens=0)


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class IdeatorClient:
    """Always proposes one objective low-risk idea."""
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _IdeaSet(ideas=[Idea(description="also handle add(0, 0)",
                                  verifier="test passes", objective=True, risk="low")])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_improve_runs_one_expansion(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, max_expand_rounds=1)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(),
                ideator_client=IdeatorClient(), now=lambda: 0.0)
    assert isinstance(r, ImproveResult)
    assert r.success is True
    assert r.expansions == 1                      # round cap stops after one expansion
    assert len(r.rounds) == 2                     # initial converge + 1 re-converge
    # the chosen idea's test was appended to the frozen suite (renamed, collision-free):
    assert (tmp_path / "tests_frozen" / "test_e1_add.py").exists()


def test_improve_without_ideator_reduces_to_solve(tmp_path: Path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(), now=lambda: 0.0)
    assert r.success is True and r.expansions == 0 and len(r.rounds) == 1
