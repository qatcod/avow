from forge.ideator import select_idea, Idea


def _idea(objective, risk):
    return Idea(description="x", verifier="v", objective=objective, risk=risk)


def test_objective_low_risk_auto_pursues():
    top = _idea(True, "low")
    chosen, escalated = select_idea([top, _idea(True, "low")], escalate=None)
    assert chosen is top and escalated is False


def test_high_risk_escalates_accept():
    top = _idea(True, "high")
    chosen, escalated = select_idea([top], escalate=lambda idea: True)
    assert chosen is top and escalated is True


def test_high_risk_escalates_reject():
    chosen, escalated = select_idea([_idea(True, "high")], escalate=lambda idea: False)
    assert chosen is None and escalated is True


def test_non_objective_escalates():
    chosen, escalated = select_idea([_idea(False, "low")], escalate=lambda idea: False)
    assert chosen is None and escalated is True


def test_no_callback_does_not_auto_pursue_risky():
    chosen, escalated = select_idea([_idea(False, "low")], escalate=None)
    assert chosen is None and escalated is True


def test_empty_list():
    assert select_idea([], escalate=None) == (None, False)
