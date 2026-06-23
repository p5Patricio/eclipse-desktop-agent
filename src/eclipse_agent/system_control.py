"""System-control primitives for Eclipse: volume, media, lock, and battery.

These types are platform-neutral so the rest of the codebase depends on a single
result contract; the Windows behavior lives in ``pal/windows/system_control.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SystemAction(StrEnum):
    """A system-control action Eclipse can perform."""

    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    MEDIA_PLAY_PAUSE = "media_play_pause"
    MEDIA_NEXT = "media_next"
    MEDIA_PREVIOUS = "media_previous"
    LOCK = "lock"
    BATTERY = "battery"


@dataclass(frozen=True)
class SystemControlResult:
    """Result of preparing or running a system-control action."""

    success: bool
    action: SystemAction
    message: str
    dry_run: bool
    executed: bool = False


def render_system_control_result(result: SystemControlResult) -> str:
    """Render a system-control result for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = "failed"
    return f"System control [{status}] {result.action.value}: {result.message}"
