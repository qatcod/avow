from avow.calibration import _load_module
from avow.calibration_benchmark import FAMILY_GOALS, FAMILY_FIXTURES
from avow.runner import Runner
from avow.config import RunConfig
from pathlib import Path
import tempfile


def _green_under_suite(goal, src):
    cfg = RunConfig()
    with tempfile.TemporaryDirectory() as sol, tempfile.TemporaryDirectory() as tst:
        (Path(sol) / "lib.py").write_text(src)
        for fn, content in goal.tests.items():
            (Path(tst) / fn).write_text(content)
        return Runner(Path(sol), Path(tst), cfg.test_command, timeout=cfg.test_timeout_seconds).run().is_green


def test_family_goals_are_well_formed_false_greens():
    assert {g.name for g in FAMILY_GOALS} == {"compare_semver", "max_version", "sort_versions", "is_newer"}
    for g in FAMILY_GOALS:
        ref = g.variants["reference"]
        # reference: green under the (imperfect) suite AND oracle-correct
        assert _green_under_suite(g, ref) is True
        assert g.oracle(_load_module(ref)) is True
        # the injected bug: green under the suite (survives it) BUT oracle-wrong -> a real false-green
        bug = g.variants["bug_lexical"]
        assert _green_under_suite(g, bug) is True
        assert g.oracle(_load_module(bug)) is False


def test_family_fixtures_cover_every_goal():
    for g in FAMILY_GOALS:
        f = FAMILY_FIXTURES[g.name]
        assert f.seed_bug in g.variants
        assert "known-tricky" not in f.diff_weak    # weak diff must not itself be a seeded/strong test
        assert f.reference_src.strip()
