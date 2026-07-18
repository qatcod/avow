from avow.calibration_gauntlet import Cohort, CalibrationProof


def _proof(plain, se, ss):
    return CalibrationProof(Cohort("plain-green", *plain),
                            Cohort("survived (empty graveyard)", *se),
                            Cohort("survived (seeded graveyard)", *ss))


def test_honesty_prints_raw_counts_always():
    out = _proof((2, 10), (2, 10), (0, 8)).honesty(min_n=8)
    assert "plain-green: 2/10" in out
    assert "survived (seeded graveyard): 0/8" in out


def test_honesty_prints_multiplier_when_n_sufficient():
    # plain 2/10 wrong (0.20), survived-empty 1/10 wrong (0.10) -> 2.0x
    out = _proof((2, 10), (1, 10), (0, 10)).honesty(min_n=8)
    assert "2.0x less likely" in out


def test_honesty_suppresses_multiplier_below_min_n():
    out = _proof((1, 4), (0, 3), (0, 3)).honesty(min_n=8)
    assert "insufficient n" in out
    assert "less likely" not in out


def test_honesty_reports_seeded_vs_empty_catch():
    out = _proof((2, 10), (2, 10), (0, 8)).honesty(min_n=8)
    assert "seeded vs empty" in out and "0 vs 2" in out


def test_honesty_omits_seeded_line_when_seeding_not_run():
    p = CalibrationProof(Cohort("plain-green", 2, 10), Cohort("survived (empty graveyard)", 1, 10),
                         Cohort("survived (seeded graveyard)", 0, 0), seeded_ran=False)
    out = p.honesty(min_n=8)
    assert "survived (seeded graveyard):" not in out   # not implying it ran and caught nothing
    assert "seeded vs empty" not in out
    assert "not run" in out and "--seed" in out


def test_honesty_zero_plain_wrong_is_not_insufficient_n():
    out = _proof((0, 10), (0, 10), (0, 10)).honesty(min_n=8)
    assert "insufficient n" not in out          # n is fine; there is simply nothing wrong to reduce
    assert "less likely" not in out
    assert "nothing for the gauntlet to reduce" in out


from avow.calibration_gauntlet import run_calibration_proof, ProofClients
from avow.calibration_benchmark import FAMILY_GOALS, make_scoring_stub, make_mining_stub
from avow.config import RunConfig
from types import SimpleNamespace
from avow.graveyard import AttackPattern


def _coroner_stub():
    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category="numeric-boundary",
                               description="probe where a shorter numeric field meets a longer one",
                               origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_run_proof_seeded_catches_more_false_greens_than_empty():
    goals = [g for g in FAMILY_GOALS if g.name in ("compare_semver", "max_version")]
    cfg = RunConfig(gauntlet_references_k=3, gauntlet_examples=25)
    clients = ProofClients(scoring_for=lambda g: make_scoring_stub(g.name),
                           mining_for=lambda g: make_mining_stub(g.name),
                           coroner=_coroner_stub(), oracle=None)
    proof = run_calibration_proof(goals, lambda g: "bug_lexical", cfg, clients, min_n=1, with_seed=True)
    # each goal contributes one false-green (bug_lexical) that is trusted-but-wrong under the suite
    assert proof.plain.wrong >= 2
    # the empty (weak) gauntlet misses them; the seeded (strong) gauntlet kills them
    assert proof.survived_seeded.wrong < proof.survived_empty.wrong


def test_run_proof_tolerates_a_failing_item(monkeypatch):
    import avow.calibration_gauntlet as cg
    from avow.calibration import CalibrationRow
    from avow.calibration_benchmark import FAMILY_GOALS
    from avow.config import RunConfig

    goals = [g for g in FAMILY_GOALS if g.name in ("compare_semver", "max_version")]

    def flaky_eval(goal, src, config, oracle_client):
        if goal.name == "compare_semver":
            raise RuntimeError("transient API error")
        return CalibrationRow(goal=goal.name, variant="", green=True, confidence=1.0,
                              oracle_agreement=None, correct=True)

    monkeypatch.setattr(cg, "_evaluate_variant", flaky_eval)
    monkeypatch.setattr(cg, "score_with_gauntlet", lambda *a, **k: cg.GauntletScore(True, True, 3))
    monkeypatch.setattr(cg, "build_seeded_patterns", lambda *a, **k: [])

    clients = cg.ProofClients(scoring_for=lambda g: object(), mining_for=lambda g: object(),
                              coroner=object(), oracle=None)
    proof = cg.run_calibration_proof(goals, lambda g: "bug_lexical", RunConfig(), clients, with_seed=True)
    assert proof.skipped == 2                      # compare_semver's 2 variants both skipped
    assert proof.plain.trusted == 2                # max_version's 2 variants still scored -> run completed
    assert "skipped due to transient errors" in proof.honesty()


def test_run_proof_no_failures_has_no_coverage_line():
    from avow.calibration_gauntlet import Cohort, CalibrationProof
    out = CalibrationProof(Cohort("plain-green", 0, 2), Cohort("survived (empty graveyard)", 0, 2),
                           Cohort("survived (seeded graveyard)", 0, 2)).honesty()
    assert "skipped" not in out                    # skipped defaults to 0 -> unchanged output


def test_mining_failure_excludes_goal_from_seeded_cohort(monkeypatch):
    # A transient MINING failure must undercount the seeded cohort (drop that goal's variants),
    # never contaminate it with empty-gauntlet results scored as if seeded.
    import avow.calibration_gauntlet as cg
    from avow.calibration import CalibrationRow
    from avow.calibration_benchmark import FAMILY_GOALS
    from avow.config import RunConfig

    goals = [g for g in FAMILY_GOALS if g.name in ("compare_semver", "max_version")]
    monkeypatch.setattr(cg, "_evaluate_variant",
                        lambda goal, src, config, oc: CalibrationRow(goal=goal.name, variant="", green=True,
                                                                     confidence=1.0, oracle_agreement=None,
                                                                     correct=True))
    monkeypatch.setattr(cg, "score_with_gauntlet", lambda *a, **k: cg.GauntletScore(True, True, 3))

    def flaky_mine(mine_goals, held_out_name, config, mining_client_for, coroner_client):
        if held_out_name == "compare_semver":
            raise RuntimeError("transient mining failure")
        return []

    monkeypatch.setattr(cg, "build_seeded_patterns", flaky_mine)
    clients = cg.ProofClients(scoring_for=lambda g: object(), mining_for=lambda g: object(),
                              coroner=object(), oracle=None)
    proof = cg.run_calibration_proof(goals, lambda g: "bug_lexical", RunConfig(), clients, with_seed=True)
    assert proof.plain.trusted == 4 and proof.survived_empty.trusted == 4   # both goals still scored
    assert proof.survived_seeded.trusted == 2   # compare_semver EXCLUDED from seeded (mining failed)
    assert proof.skipped == 1
    assert "undercounted" in proof.honesty()
