# tests/test_loop.py
import pytest
from pathlib import Path
from avow.loop import solve, SolveResult
from avow.config import RunConfig
from avow.examiner import Examiner, ExaminerResult, TestSuite, TestFile
from avow.scoring import FailureInfo


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
        from avow.builder import BuilderOutcome
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
            from avow.builder import BuilderOutcome
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
    log = (tmp_path / ".avow" / "run.jsonl").read_text().strip().splitlines()
    assert len(log) >= 1


def test_loop_reports_mutation_score_on_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert result.success is True
    # best solution is `return a + b`; the frozen test `add(2,3)==5` kills Add->Sub and Return->None.
    assert result.mutation_score == 1.0
    assert result.survivors == 0


def test_loop_records_intent_score(tmp_path):
    from types import SimpleNamespace
    from avow.backtranslation import _InferredGoal, IntentMatch

    class FakeIntentClient:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            if output_format is _InferredGoal:
                po = _InferredGoal(inferred_goal="add two numbers")
            else:
                po = IntentMatch(score=0.83, divergences=["x"])
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=3, output_tokens=4))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(),
                   now=lambda: 0.0, intent_client=FakeIntentClient())
    assert result.success is True
    assert result.intent_score == 0.83


def test_loop_intent_score_none_without_client(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    result = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert result.success is True
    assert result.intent_score is None  # no intent_client → hook skipped


def _fake_intent_client(score):
    from types import SimpleNamespace
    from avow.backtranslation import _InferredGoal, IntentMatch

    class FakeIntentClient:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            if output_format is _InferredGoal:
                po = _InferredGoal(inferred_goal="add two numbers")
            else:
                po = IntentMatch(score=score, divergences=[])
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    return FakeIntentClient()


def test_loop_high_confidence_succeeds(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=_fake_intent_client(0.9))
    # mutation 1.0, holdout 1.0, intent 0.9 -> 0.9667 >= 0.7
    assert r.success is True and r.reason == "green"
    assert r.confidence == pytest.approx((1.0 + 1.0 + 0.9) / 3)
    assert set(r.confidence_breakdown) == {"holdout", "mutation", "intent"}


def test_loop_low_confidence_flags(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=_fake_intent_client(0.0))
    # (1 + 1 + 0) / 3 = 0.667 < 0.7
    assert r.success is False and r.reason == "low_confidence"
    assert r.confidence == pytest.approx((1.0 + 1.0 + 0.0) / 3)


def test_loop_low_confidence_escalation_override(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    calls = []
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=_fake_intent_client(0.0),
              escalate=lambda breakdown: calls.append(breakdown) or True)
    assert r.success is True and r.reason == "green_human_override"
    assert calls and set(calls[0]) == {"holdout", "mutation", "intent"}


def test_loop_gating_off_reports_only(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, confidence_gating=False)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=_fake_intent_client(0.0))
    assert r.success is True and r.reason == "green"  # low confidence, but not gated
    assert r.confidence == pytest.approx((1.0 + 1.0 + 0.0) / 3)


def test_loop_adds_property_tests_to_frozen_suite(tmp_path):
    from types import SimpleNamespace
    from avow.examiner import TestFile
    from avow.properties import _PropertySet

    class FakePropClient:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            # A SATISFIABLE property: commutativity holds for `add(a, b) = a + b`.
            po = _PropertySet(tests=[TestFile(
                path="test_prop_comm.py",
                content=("from lib import add\n"
                         "from hypothesis import given, strategies as st\n"
                         "@given(st.integers(), st.integers())\n"
                         "def test_commutative(a, b):\n    assert add(a, b) == add(b, a)\n"),
            )])
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=2, output_tokens=3))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              property_client=FakePropClient())
    # The commutativity property is satisfied by the converged `a + b`, so the run goes green.
    assert r.success is True and r.reason == "green"
    assert (tmp_path / "tests_frozen" / "test_prop_comm.py").exists()


def test_loop_no_property_client_skips(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True
    assert not (tmp_path / "tests_frozen" / "test_prop_comm.py").exists()


def test_loop_panel_disagreement_floor(tmp_path):
    from types import SimpleNamespace
    from avow.backtranslation import _InferredGoal, IntentMatch

    class DisagreeingPanel:
        @property
        def messages(self):
            return self

        def parse(self, *, model, output_format, **kwargs):
            if output_format is _InferredGoal:
                po = _InferredGoal(inferred_goal="add")
            else:
                # high consensus, high disagreement: spread 0.8 -> agreement 0.2 < floor 0.5
                score = {"claude-opus-4-8": 1.0, "claude-sonnet-4-6": 1.0, "claude-haiku-4-5": 0.2}[model]
                po = IntentMatch(score=score, divergences=[])
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=DisagreeingPanel())
    # consensus 0.733, confidence (1.0 + 1.0 + 0.733)/3 = 0.911 >= 0.7 (would be green),
    # but agreement 0.2 < 0.5 floor -> forced low_confidence.
    assert r.reason == "low_confidence" and r.success is False
    assert r.intent_score == pytest.approx((1.0 + 1.0 + 0.2) / 3)


def test_loop_oracle_disagreement_floor(tmp_path):
    from types import SimpleNamespace
    from avow.oracle import _OraclePair

    class DisagreeingOracle:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            # reference DISAGREES with the converged solution (add = a + b): reference uses a - b
            pair = _OraclePair(
                reference_code="def add(a, b):\n    return a - b\n",
                diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                "from hypothesis import given, strategies as st\n"
                                "@given(st.integers(), st.integers())\n"
                                "def test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
            return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              oracle_client=DisagreeingOracle())
    # the solution converges green, but the independent reference disagrees (a+b vs a-b) ->
    # oracle agreement 0.0 < floor 1.0 -> forced low_confidence
    assert r.reason == "low_confidence" and r.success is False
    assert r.oracle_agreement == 0.0


def test_loop_no_oracle_client_unaffected(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True and r.oracle_agreement is None


def test_loop_holdout_floor_vetoes_high_average(tmp_path):
    class FloorExaminer(Examiner):
        def __init__(self):
            pass

        def write_tests(self, goal):
            def t(name, rhs):
                return TestFile(path=name,
                                content=f"from lib import add\ndef test():\n    assert add(2, 3) == {rhs}\n")
            suite = TestSuite(test_plan="add", tests=[t("test_a_ok.py", 5), t("test_z1.py", 5), t("test_z2.py", 6)])
            return ExaminerResult(suite=suite, input_tokens=1, output_tokens=1)

    # holdout_fraction 0.5 over 3 sorted tests holds out the last 2 (test_z1 pass, test_z2 fail) -> holdout 0.5;
    # visible (test_a_ok) passes so the loop converges green.
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.5, holdout_floor=0.6)
    r = solve(_goal(tmp_path), cfg, FloorExaminer(), FlakyBuilder(), now=lambda: 0.0,
              intent_client=_fake_intent_client(1.0))
    assert r.confidence_breakdown["holdout"] == pytest.approx(0.5)
    assert r.confidence == pytest.approx((0.5 + 1.0 + 1.0) / 3)  # 0.833 — would clear the threshold
    assert r.reason == "low_confidence" and r.success is False   # but the 0.5 < 0.6 floor vetoes it


class AlwaysWrongBuilder:
    """Never converges: writes a wrong implementation every attempt."""
    def attempt(self, solution_dir, goal, failures):
        from pathlib import Path as _P
        from avow.builder import BuilderOutcome
        (_P(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a - b\n")
        return BuilderOutcome(plan="still wrong", cost_usd=0.0, raw={})


def _fake_supervisor(recommendation, escalate):
    from types import SimpleNamespace
    from avow.supervisor import SupervisorVerdict

    class _C:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=SupervisorVerdict(assessment="stuck", recommendation=recommendation, escalate=escalate),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_loop_supervisor_escalates(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=5,
                    supervisor_enabled=True, supervisor_patience=1)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0,
              supervisor_client=_fake_supervisor("abort", True))
    assert r.reason == "supervisor_escalate" and r.success is False


def test_loop_supervisor_continue_falls_through_to_plateau(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=3,
                    supervisor_enabled=True, supervisor_patience=1)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0,
              supervisor_client=_fake_supervisor("continue", False))
    assert r.reason == "plateau" and r.success is False   # supervisor advised continue -> normal stop


def test_loop_supervisor_dormant_by_default(tmp_path):
    cfg = RunConfig(max_iterations=6, holdout_fraction=0.0, plateau_patience=2)  # supervisor off
    r = solve(_goal(tmp_path), cfg, StubExaminer(), AlwaysWrongBuilder(), now=lambda: 0.0)
    assert r.reason == "plateau"   # no supervisor_client + disabled -> unchanged behavior


def test_loop_oracle_converge_target(tmp_path):
    from types import SimpleNamespace
    from avow.oracle import _OraclePair

    class FakeOracle:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            pair = _OraclePair(
                reference_code="def add(a, b):\n    return a + b\n",
                diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                "from hypothesis import given, strategies as st\n"
                                "@given(st.integers(), st.integers())\n"
                                "def test_conv(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
            return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, oracle_converge_target=True)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              oracle_client=FakeOracle())
    # the converged solution (a + b) passes the Examiner test AND agrees with the reference (a + b)
    assert r.success is True and r.reason == "green"
    assert (tmp_path / "tests_frozen" / "test_oracle_converge.py").exists()
    assert (tmp_path / "tests_frozen" / "ref.py").exists()


def test_loop_oracle_converge_target_off_by_default(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)  # oracle_converge_target defaults False
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True
    assert not (tmp_path / "tests_frozen" / "ref.py").exists()


def test_loop_adjudicator_flags_examiner_bad_test(tmp_path):
    from types import SimpleNamespace
    from avow.oracle import _OraclePair

    class BadTestExaminer:
        def write_tests(self, goal):
            return ExaminerResult(suite=TestSuite(test_plan="add", tests=[
                TestFile(path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n"),
                TestFile(path="test_bad.py", content="from lib import add\ndef test_bad():\n    assert add(2, 3) == 6\n"),
            ]), input_tokens=0, output_tokens=0)

    class CorrectBuilder:
        def attempt(self, solution_dir, goal, failures):
            from pathlib import Path as _P
            from avow.builder import BuilderOutcome
            (_P(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})

    class RefClient:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            return SimpleNamespace(
                parsed_output=_OraclePair(reference_code="def add(a, b):\n    return a + b\n", diff_test_code="x"),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0,
                    adjudicate_enabled=True, adjudicate_threshold=0.4, adjudicate_references_k=2)
    r = solve(_goal(tmp_path), cfg, BadTestExaminer(), CorrectBuilder(), now=lambda: 0.0,
              adjudicator_client=RefClient())
    # the correct a+b solution can't pass the contradictory test_bad -> never green
    assert r.success is False
    # ...but the adjudicator ran a reference and flagged test_bad as the Examiner's bug:
    assert any("test_bad" in t for t in r.suspected_bad_tests)


def test_loop_adjudicator_off_by_default(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0, plateau_patience=2)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.suspected_bad_tests == []   # disabled + no client -> never runs


def test_loop_failing_check_gates_green(tmp_path):
    cfg = RunConfig(max_iterations=3, holdout_fraction=0.0,
                    checks=[{"name": "gate", "command": ["python", "-c", "import sys; sys.exit(1)"]}])
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    # the solution passes the pytest suite, but the always-failing check gates green
    assert r.success is False


def test_loop_passing_check_stays_green(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0,
                    checks=[{"name": "ok", "command": ["python", "-c", "import sys; sys.exit(0)"]}])
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True and r.reason == "green"


def test_loop_no_checks_unchanged(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)   # checks=[] default
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True


class _EmptySuiteExaminer(Examiner):
    """Produces a frozen suite that collects zero tests."""
    def __init__(self):
        pass

    def write_tests(self, goal):
        suite = TestSuite(test_plan="none", tests=[
            TestFile(path="test_none.py", content="# a suite that collects no tests\n")])
        return ExaminerResult(suite=suite, input_tokens=0, output_tokens=0)


def test_loop_forwards_strip_check_config(tmp_path):
    # The builder writes correct code AND plants a ruff.toml. The check passes only
    # when ruff.toml is present. With strip on, the loop must run the check in a
    # sandbox where the planted config is gone -> check fails -> never green.
    class ConfigCheatBuilder:
        def attempt(self, solution_dir, goal, failures):
            from avow.builder import BuilderOutcome
            (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
            (Path(solution_dir) / "ruff.toml").write_text("# silence the linter\n")
            return BuilderOutcome(plan="cheat", cost_usd=0.0, raw={})

    needs_cfg = {"name": "needs_cfg",
                 "command": ["python", "-c", "import os,sys; sys.exit(0 if os.path.exists('ruff.toml') else 1)"]}
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0, checks=[needs_cfg],
                    strip_check_config=True)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), ConfigCheatBuilder(), now=lambda: 0.0)
    assert r.success is False   # the builder's config is stripped -> check fails -> not green


def test_loop_checks_cannot_green_zero_test_suite(tmp_path):
    # A zero-test suite is never verified. Passing checks must NOT manufacture a
    # green out of it — "no tests = not verified" is the guard checks must respect.
    cfg = RunConfig(max_iterations=2, holdout_fraction=0.0,
                    checks=[{"name": "ok", "command": ["python", "-c", "import sys; sys.exit(0)"]}])
    r = solve(_goal(tmp_path), cfg, _EmptySuiteExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is False
