# tests/test_improve.py
from pathlib import Path
from types import SimpleNamespace
from hermit.config import RunConfig
from hermit.improve import improve, ImproveResult
from hermit.examiner import ExaminerResult, TestSuite, TestFile
from hermit.ideator import _IdeaSet, Idea
from hermit.builder import BuilderOutcome


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


class CheckIdeatorClient:
    """Proposes a check-kind idea: an automated gate (here, one that always fails)."""
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _IdeaSet(ideas=[Idea(
            description="enforce a lint gate", verifier="the linter exits 0",
            objective=True, risk="low", kind="check",
            check_command=["python", "-c", "import sys; sys.exit(1)"])])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_improve_ideator_proposes_check_appended_to_config(tmp_path: Path):
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0, max_expand_rounds=1)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(),
                ideator_client=CheckIdeatorClient(), now=lambda: 0.0)
    assert r.expansions == 1
    # the check-idea was appended to config.checks (a standing gate), not written as a test
    assert any(c["command"] == ["python", "-c", "import sys; sys.exit(1)"] for c in cfg.checks)
    assert not (tmp_path / "tests_frozen" / "test_e1_add.py").exists()
    # the always-failing gate makes the expand round non-green
    assert r.rounds[-1].success is False


class EmptyCheckIdeatorClient:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        po = _IdeaSet(ideas=[Idea(description="x", verifier="y", objective=True, risk="low",
                                  kind="check", check_command=[])])
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_improve_check_idea_with_empty_command_is_skipped(tmp_path: Path):
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0, max_expand_rounds=2)
    r = improve(_goal(tmp_path), cfg, StubExaminer(), StubBuilder(),
                ideator_client=EmptyCheckIdeatorClient(), now=lambda: 0.0)
    assert r.expansions == 0        # a check-idea with no command is not actionable
    assert cfg.checks == []


def test_improve_preserves_last_known_good_on_failed_round(tmp_path):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")

    class FailingIdeaExaminer:
        """Round 0: a satisfiable test. The idea round: an IMPOSSIBLE test."""
        def __init__(self):
            self.calls = 0

        def write_tests(self, goal):
            self.calls += 1
            content = ("from lib import add\ndef test_x():\n    assert add(2, 3) == 5\n"
                       if self.calls == 1 else
                       "from lib import add\ndef test_x():\n    assert add(2, 3) == 999\n")
            return ExaminerResult(suite=TestSuite(test_plan="x", tests=[TestFile(path="test_x.py", content=content)]),
                                  input_tokens=0, output_tokens=0)

    class StubBuilder:
        def __init__(self, *a, **k): pass
        def attempt(self, solution_dir, goal, failures):
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    class IdeatorClient:
        @property
        def messages(self): return self
        def parse(self, *, output_format, **kwargs):
            po = _IdeaSet(ideas=[Idea(description="impossible", verifier="v", objective=True, risk="low")])
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, max_expand_rounds=1)
    r = improve(tmp_path, cfg, FailingIdeaExaminer(), StubBuilder(),
                ideator_client=IdeatorClient(), now=lambda: 0.0)
    assert r.expansions == 1
    assert r.final.success is False          # the impossible idea-test round never converges
    assert r.best_round == 0                 # last green round was the initial converge
    assert r.best_dir is not None and Path(r.best_dir).exists()   # round-0 green solution preserved
