"""Platform-neutral desktop-control result types for Eclipse.

These types are shared across the Windows platform abstraction layer and the CLI.
They intentionally carry no Windows- or Linux-specific behavior so the rest of the
codebase can depend on a single, stable result contract.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DesktopControlAction(StrEnum):
    """Native desktop-control action families."""

    OPEN_APP = "open_app"
    LIST_WINDOWS = "list_windows"
    FOCUS_WINDOW = "focus_window"
    SCREENSHOT = "screenshot"
    MOVE_MOUSE = "move_mouse"
    CLICK = "click"
    TYPE_TEXT = "type_text"


@dataclass(frozen=True)
class DesktopControlResult:
    """Result of preparing or running a native desktop-control action."""

    success: bool
    action: DesktopControlAction
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False
    output_path: Path | None = None


@dataclass(frozen=True)
class DesktopLaunchResult:
    """Result of preparing or launching a desktop application."""

    success: bool
    app_name: str
    command: tuple[str, ...]
    message: str
    dry_run: bool
    pid: int | None = None


def render_desktop_control_result(result: DesktopControlResult) -> str:
    """Render a desktop-control result for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = (
            "blocked"
            if "requires explicit confirmation" in result.message.casefold()
            else "failed"
        )
    lines = [f"Desktop control [{status}] {result.action.value}: {result.message}"]
    if result.command:
        lines.append(f"command: {shlex_join(result.command)}")
    if result.output_path:
        lines.append(f"output: {result.output_path}")
    return "\n".join(lines)


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command tuple for display only."""

    return shlex.join(command)
