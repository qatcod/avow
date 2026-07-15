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


from avow.calibration_gauntlet import assert_no_leakage, LeakageError, build_seeded_patterns
from avow.calibration_benchmark import make_mining_stub
from avow.graveyard import AttackPattern
from types import SimpleNamespace


def _coroner_stub(category="numeric-boundary", desc="probe the numeric-vs-lexical boundary"):
    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category=category, description=desc, origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_leakage_guard_rejects_a_pattern_mined_from_the_held_out_goal():
    good = [AttackPattern(category="c", description="d", origin_goal="max_version", example_input="x")]
    assert_no_leakage(good, "compare_semver")          # different origin -> fine
    leak = [AttackPattern(category="c", description="d", origin_goal="compare_semver", example_input="x")]
    try:
        assert_no_leakage(leak, "compare_semver")
        assert False, "expected LeakageError"
    except LeakageError:
        pass


def test_build_seeded_patterns_is_leave_one_out_and_stamps_provenance():
    cfg = RunConfig(gauntlet_references_k=3, gauntlet_examples=25)
    held = "compare_semver"
    mine_goals = [(g, "bug_lexical") for g in FAMILY_GOALS if g.name != held]
    pats = build_seeded_patterns(mine_goals, held, cfg, lambda g: make_mining_stub(g.name), _coroner_stub())
    assert pats and all(isinstance(p, AttackPattern) for p in pats)
    origins = {p.origin_goal for p in pats}
    assert held not in origins                          # never mined from the held-out goal
    assert origins <= {"max_version", "sort_versions", "is_newer"}
