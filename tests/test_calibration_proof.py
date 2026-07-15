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
