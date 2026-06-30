# tests/test_harden.py
from pathlib import Path
from hermit.config import RunConfig
from hermit.harden import harden, HardenResult
from hermit.examiner import ExaminerResult, TestSuite, TestFile
from hermit.builder import BuilderOutcome


def _goal(tmp_path: Path) -> Path:
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


def _add_suite():
    return ExaminerResult(suite=TestSuite(test_plan="add", tests=[TestFile(
        path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")]),
        input_tokens=0, output_tokens=0)


class StubBuilder:
    def __init__(self, *a, **k):
        pass

    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


class SurvivingExaminer:
    """Goal suite + adversarial tests the (correct) solution survives."""
    def write_tests(self, goal):
        return _add_suite()

    def write_adversarial_tests(self, goal, solution_code):
        return ExaminerResult(suite=TestSuite(test_plan="adv", tests=[TestFile(
            path="test_adv.py", content="from lib import add\ndef test_adv():\n    assert add(0, 0) == 0\n")]),
            input_tokens=0, output_tokens=0)


class BreakingExaminer:
    """The adversarial round writes an IMPOSSIBLE test (add=a+b can't satisfy)."""
    def write_tests(self, goal):
        return _add_suite()

    def write_adversarial_tests(self, goal, solution_code):
        return ExaminerResult(suite=TestSuite(test_plan="adv", tests=[TestFile(
            path="test_adv.py", content="from lib import add\ndef test_adv():\n    assert add(2, 3) == 999\n")]),
            input_tokens=0, output_tokens=0)


def test_harden_runs_escalation_rounds(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, adversarial_rounds=2)
    r = harden(_goal(tmp_path), cfg, SurvivingExaminer(), StubBuilder(), now=lambda: 0.0)
    assert isinstance(r, HardenResult)
    assert r.success is True
    assert r.rounds_run == 2                       # both escalation rounds ran
    assert len(r.rounds) == 3                       # initial converge + 2 escalations
    assert (tmp_path / "tests_frozen" / "test_e1_adv.py").exists()
    assert (tmp_path / "tests_frozen" / "test_e2_adv.py").exists()


def test_harden_preserves_last_known_good_when_adversary_wins(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, adversarial_rounds=2)
    r = harden(_goal(tmp_path), cfg, BreakingExaminer(), StubBuilder(), now=lambda: 0.0)
    assert r.rounds_run == 1                        # the impossible adversarial round fails -> stop
    assert r.final.success is False
    assert r.best_round == 0                         # last green was the initial converge
    assert r.best_dir is not None and Path(r.best_dir).exists()
