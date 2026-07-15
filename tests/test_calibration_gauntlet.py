from avow.calibration_gauntlet import score_with_gauntlet, GauntletScore
from avow.calibration_benchmark import FAMILY_GOALS, make_scoring_stub
from avow.config import RunConfig


def _goal(name):
    return next(g for g in FAMILY_GOALS if g.name == name)


def _cfg():
    # small + few references keeps the real subprocess gauntlet fast but still a majority (k=3)
    return RunConfig(gauntlet_references_k=3, gauntlet_examples=25)


def test_correct_variant_survives_the_gauntlet():
    g = _goal("compare_semver")
    s = score_with_gauntlet(g, g.variants["reference"], _cfg(), make_scoring_stub(g.name), patterns=[])
    assert s.green is True and s.survived is True


def test_false_green_survives_empty_but_is_killed_when_seeded():
    g = _goal("compare_semver")
    bug = g.variants["bug_lexical"]
    empty = score_with_gauntlet(g, bug, _cfg(), make_scoring_stub(g.name), patterns=[])
    seeded = score_with_gauntlet(g, bug, _cfg(), make_scoring_stub(g.name),
                                 patterns=["probe where a shorter numeric field meets a longer one"])
    assert empty.green is True and empty.survived is True     # weak references miss the boundary
    assert seeded.survived is False                            # seeded references probe the boundary -> kill


def test_non_green_source_never_reaches_the_gauntlet():
    g = _goal("compare_semver")
    s = score_with_gauntlet(g, "def compare_semver(a, b):\n    return 'oops'\n", _cfg(),
                            make_scoring_stub(g.name), patterns=[])
    assert s.green is False and s.survived is False
