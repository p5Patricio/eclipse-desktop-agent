"""Configuration primitives for Eclipse.

This file intentionally avoids external dependencies while the architecture is still evolving.
"""

from dataclasses import dataclass

from eclipse_agent.activation import ActivationMode


@dataclass(frozen=True)
class EclipseConfig:
    """Runtime configuration for the early CLI skeleton."""

    environment: str = "development"
    log_level: str = "info"
    default_mode: str = "draft"
    activation_mode: ActivationMode = ActivationMode.WAKE_WORD
