"""Safety primitives and screenshot redaction for Eclipse tools."""

from dataclasses import dataclass
from enum import StrEnum
from .redactor import redact_screenshot

__all__ = ["RiskLevel", "SafetyDecision", "evaluate_risk", "redact_screenshot"]


class RiskLevel(StrEnum):
    """Coarse risk level for planned actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SafetyDecision:
    """Result of evaluating a planned action."""

    allowed: bool
    requires_confirmation: bool
    reason: str


def evaluate_risk(risk_level: RiskLevel) -> SafetyDecision:
    """Return a conservative safety decision for the given risk level."""

    if risk_level is RiskLevel.LOW:
        return SafetyDecision(True, False, "Low-risk action allowed with logging.")
    if risk_level is RiskLevel.MEDIUM:
        return SafetyDecision(True, True, "Medium-risk action requires confirmation.")
    if risk_level is RiskLevel.HIGH:
        return SafetyDecision(True, True, "High-risk action requires explicit confirmation.")
    return SafetyDecision(False, True, "Critical action blocked by default.")
