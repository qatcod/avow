from forge.population import select_best
from forge.loop import SolveResult


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
