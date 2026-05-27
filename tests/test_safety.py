from eclipse_agent.safety import RiskLevel, evaluate_risk


def test_low_risk_does_not_require_confirmation():
    decision = evaluate_risk(RiskLevel.LOW)
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_critical_risk_blocked_by_default():
    decision = evaluate_risk(RiskLevel.CRITICAL)
    assert decision.allowed is False
    assert decision.requires_confirmation is True
