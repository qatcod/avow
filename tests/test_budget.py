import pytest
from avow.budget import Budget, PRICES


def test_charge_tokens_uses_price_table():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    # opus 4.8 = $5/1M in, $25/1M out
    b.charge_tokens("claude-opus-4-8", input_tokens=1_000_000, output_tokens=1_000_000)
    assert b.spent_usd == pytest.approx(30.0)


def test_charge_usd_direct():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    b.charge_usd(2.5)
    assert b.spent_usd == pytest.approx(2.5)


def test_exhausted_reasons():
    b = Budget(max_cost_usd=1.0, max_iterations=2, max_wall_seconds=100, started_at=0.0)
    assert b.exhausted(now=10.0) is None
    b.charge_usd(1.0)
    assert b.exhausted(now=10.0) == "cost"
    b2 = Budget(max_cost_usd=100.0, max_iterations=2, max_wall_seconds=100, started_at=0.0)
    b2.tick_iteration(); b2.tick_iteration()
    assert b2.exhausted(now=10.0) == "iterations"
    b3 = Budget(max_cost_usd=100.0, max_iterations=9, max_wall_seconds=100, started_at=0.0)
    assert b3.exhausted(now=101.0) == "wall_clock"


def test_unknown_model_charges_zero_but_does_not_crash():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=999, started_at=0.0)
    b.charge_tokens("some-future-model", 1000, 1000)
    assert b.spent_usd == 0.0


def test_started_at_none_disables_wall_clock():
    b = Budget(max_cost_usd=100.0, max_iterations=10, max_wall_seconds=1, started_at=None)
    assert b.exhausted(now=9999.0) is None
