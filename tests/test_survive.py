from pathlib import Path
from avow.survive import survive, SurviveResult
from avow.config import RunConfig
from avow.examiner import Examiner, ExaminerResult, TestSuite, TestFile
from avow.builder import BuilderOutcome
from avow.gauntlet import GauntletResult, Counterexample


class StubExaminer(Examiner):
    def __init__(self):
        pass

    def write_tests(self, goal):
        suite = TestSuite(test_plan="add", tests=[TestFile(
            path="test_add.py", content="from lib import add\ndef test_add():\n    assert add(2, 3) == 5\n")])
        return ExaminerResult(suite=suite, input_tokens=1, output_tokens=1)


class GoodBuilder:
    def attempt(self, solution_dir, goal, failures):
        (Path(solution_dir) / "lib.py").write_text("def add(a, b):\n    return a + b\n")
        return BuilderOutcome(plan="ok", cost_usd=0.0, raw={})


def _goal(tmp_path):
    (tmp_path / "goal.md").write_text("Build add(a, b) returning a + b.")
    return tmp_path


_CX = Counterexample(input_repr="test_diff(a=0, b=0)",
                     reference_code="def add(a, b):\n    return a + b\n",
                     diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                     "from hypothesis import given, strategies as st\n"
                                     "@given(st.integers(), st.integers())\n"
                                     "def test_g(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))


def test_survive_verified_when_gauntlet_survives(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: GauntletResult(True, None, 4, 4, 0, 0))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "verified_survivor" and r.rounds == 0


def test_survive_fights_back_then_survives(tmp_path, monkeypatch):
    import avow.survive as s
    calls = {"n": 0}

    def fake_gauntlet(*a, **k):
        calls["n"] += 1
        return GauntletResult(False, _CX, 4, 4, 0, 0) if calls["n"] == 1 else GauntletResult(True, None, 4, 4, 0, 0)

    monkeypatch.setattr(s, "run_gauntlet", fake_gauntlet)
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=3),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "verified_survivor" and r.rounds == 1
    # the counterexample was frozen into the suite as a differential regression test + its reference
    assert (tmp_path / "tests_frozen" / "test_gauntlet_r0.py").exists()
    assert (tmp_path / "tests_frozen" / "ref_g0.py").exists()
    assert "from ref_g0 import" in (tmp_path / "tests_frozen" / "test_gauntlet_r0.py").read_text()


def test_survive_dies_when_never_survives(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: GauntletResult(False, _CX, 4, 4, 0, 0))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=2),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), now=lambda: 0.0)
    assert r.status == "died" and r.death_counterexample is _CX


def test_survive_no_gauntlet_client_is_unverified(tmp_path, monkeypatch):
    import avow.survive as s
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    r = survive(_goal(tmp_path), RunConfig(max_iterations=5, holdout_fraction=0.0),
                StubExaminer(), GoodBuilder(), gauntlet_client=None, now=lambda: 0.0)
    assert r.status == "unverified" and r.rounds == 0   # green, but the gauntlet never ran
