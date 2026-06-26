import pytest
from forge.confidence import aggregate_confidence, ConfidenceResult

W = {"holdout": 1.0, "mutation": 1.0, "intent": 1.0}


def test_equal_weights_average():
    r = aggregate_confidence({"holdout": 1.0, "mutation": 0.5, "intent": 0.0}, W)
    assert isinstance(r, ConfidenceResult)
    assert r.score == pytest.approx(0.5)  # (1 + 0.5 + 0) / 3
    assert r.breakdown == {"holdout": 1.0, "mutation": 0.5, "intent": 0.0}
    assert all(w == pytest.approx(1 / 3) for w in r.weights_used.values())


def test_missing_signal_renormalizes():
    r = aggregate_confidence({"holdout": 1.0, "mutation": None, "intent": 0.0}, W)
    assert r.score == pytest.approx(0.5)  # only holdout + intent, (1 + 0) / 2
    assert set(r.breakdown) == {"holdout", "intent"}
    assert r.weights_used == {"holdout": pytest.approx(0.5), "intent": pytest.approx(0.5)}


def test_custom_weights():
    r = aggregate_confidence({"a": 1.0, "b": 0.0}, {"a": 3.0, "b": 1.0})
    assert r.score == pytest.approx(0.75)  # (3*1 + 1*0) / 4


def test_zero_weight_signal_excluded():
    r = aggregate_confidence({"a": 0.2, "b": 1.0}, {"a": 0.0, "b": 1.0})
    assert r.score == pytest.approx(1.0)
    assert set(r.breakdown) == {"b"}


def test_all_missing_is_empty():
    r = aggregate_confidence({"holdout": None, "mutation": None}, W)
    assert r.score == 0.0 and r.breakdown == {} and r.weights_used == {}


def test_single_signal():
    r = aggregate_confidence({"mutation": 0.8}, W)
    assert r.score == pytest.approx(0.8)
    assert r.weights_used == {"mutation": pytest.approx(1.0)}
