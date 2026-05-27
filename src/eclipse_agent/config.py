"""Configuration primitives for Eclipse.

This file intentionally avoids external dependencies while the architecture is still evolving.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EclipseConfig:
    """Runtime configuration for the early CLI skeleton."""

    environment: str = "development"
    log_level: str = "info"
    default_mode: str = "draft"
