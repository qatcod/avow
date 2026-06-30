from hermit.population import select_best
from hermit.loop import SolveResult


def _r(success, confidence, score=1.0):
    return SolveResult(success, score, 1, "green" if success else "low_confidence", None,
                       confidence=confidence)


def test_green_high_confidence_wins():
    assert select_best([_r(True, 0.8), _r(True, 0.95), _r(False, None, 0.5)]) == 1


def test_green_beats_nongreen_even_at_lower_confidence():
    assert select_best([_r(False, 0.99), _r(True, 0.7)]) == 1


def test_none_confidence_ranks_last_among_greens():
    assert select_best([_r(True, None), _r(True, 0.5)]) == 1


def test_ties_break_to_lowest_index():
    assert select_best([_r(True, 0.9), _r(True, 0.9)]) == 0


def test_empty_is_minus_one():
    assert select_best([]) == -1


def test_ranks_on_common_signals_excluding_intent():
    from hermit.loop import SolveResult
    # cand 0's raw confidence is inflated by a high suite-level intent term; cand 1 has
    # strictly better SOLUTION signals. Excluding intent, cand 1 wins.
    c0 = SolveResult(True, 1.0, 1, "green", None, confidence=0.95,
                     confidence_breakdown={"holdout": 0.9, "mutation": 0.9, "intent": 1.0, "oracle": 1.0})
    c1 = SolveResult(True, 1.0, 1, "green", None, confidence=0.95,
                     confidence_breakdown={"holdout": 1.0, "mutation": 1.0, "oracle": 1.0})
    assert select_best([c0, c1]) == 1
