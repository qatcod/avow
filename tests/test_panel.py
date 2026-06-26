import pytest
from forge.panel import aggregate_panel, PanelResult


def test_identical_scores_full_agreement():
    r = aggregate_panel({"opus": 0.8, "sonnet": 0.8, "haiku": 0.8})
    assert isinstance(r, PanelResult)
    assert r.mean == pytest.approx(0.8) and r.agreement == 1.0
    assert r.scores == {"opus": 0.8, "sonnet": 0.8, "haiku": 0.8}


def test_spread_lowers_agreement():
    r = aggregate_panel({"a": 0.9, "b": 0.5, "c": 1.0})
    assert r.mean == pytest.approx((0.9 + 0.5 + 1.0) / 3)
    assert r.agreement == pytest.approx(1.0 - (1.0 - 0.5))  # 0.5


def test_full_spread_zero_agreement():
    r = aggregate_panel({"a": 0.0, "b": 1.0})
    assert r.agreement == 0.0 and r.mean == pytest.approx(0.5)


def test_single_score_full_agreement():
    r = aggregate_panel({"opus": 0.6})
    assert r.mean == pytest.approx(0.6) and r.agreement == 1.0


def test_empty():
    r = aggregate_panel({})
    assert r.mean == 0.0 and r.scores == {} and r.agreement == 1.0
