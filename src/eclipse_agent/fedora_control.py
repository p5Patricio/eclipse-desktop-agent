"""Fedora/KDE native desktop control scaffolding for Eclipse."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from eclipse_agent.desktop_apps import DesktopAppLauncher


class FedoraControlAction(StrEnum):
    """Initial native-control action families."""

    OPEN_APP = "open_app"
    LIST_WINDOWS = "list_windows"
    FOCUS_WINDOW = "focus_window"


@dataclass(frozen=True)
class FedoraControlResult:
    """Result of preparing or running a Fedora desktop-control action."""

    success: bool
    action: FedoraControlAction
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False


class CommandRunner(Protocol):
    """Protocol for command runners used by tests and adapters."""

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Run a command and return its completed process."""


class FedoraNativeController:
    """Safe scaffolding for Fedora/KDE native control.

    Deep control is intentionally staged. The controller can prepare app launches
    now, and exposes future window-control command shapes without pretending they
    are already reliable across Wayland sessions.
    """

    def __init__(
        self,
        desktop_launcher: DesktopAppLauncher | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.desktop_launcher = desktop_launcher or DesktopAppLauncher()
        self.runner = runner or _default_runner

    def open_app(self, app_name: str, *, dry_run: bool = True) -> FedoraControlResult:
        """Open an installed desktop app via its `.desktop` Exec command."""

        launch_result = self.desktop_launcher.launch(app_name, dry_run=True)
        if not launch_result.success:
            return FedoraControlResult(
                success=False,
                action=FedoraControlAction.OPEN_APP,
                command=(),
                message=launch_result.message,
                dry_run=dry_run,
            )
        if dry_run:
            return FedoraControlResult(
                success=True,
                action=FedoraControlAction.OPEN_APP,
                command=launch_result.command,
                message=f"Prepared native app launch for {launch_result.app_name}.",
                dry_run=True,
            )
        completed = self.runner(launch_result.command)
        if completed.returncode == 0:
            message = "Native app launch command executed."
        else:
            message = completed.stderr
        return FedoraControlResult(
            success=completed.returncode == 0,
            action=FedoraControlAction.OPEN_APP,
            command=launch_result.command,
            message=message,
            dry_run=False,
            executed=completed.returncode == 0,
        )

    def list_windows_command(self) -> FedoraControlResult:
        """Prepare a best-effort KDE window listing command."""

        command = ("qdbus", "org.kde.KWin", "/KWin", "org.kde.KWin.queryWindowInfo")
        return FedoraControlResult(
            success=True,
            action=FedoraControlAction.LIST_WINDOWS,
            command=command,
            message="Prepared KWin window info query; exact strategy needs live validation.",
            dry_run=True,
        )

    def focus_window_placeholder(self, window_hint: str) -> FedoraControlResult:
        """Return a blocked placeholder for focus control until KWin strategy is validated."""

        return FedoraControlResult(
            success=False,
            action=FedoraControlAction.FOCUS_WINDOW,
            command=(),
            message=(
                "Window focus control is not enabled yet. Need KWin/AT-SPI validation "
                f"for hint: {window_hint}."
            ),
            dry_run=True,
        )


def render_fedora_control_result(result: FedoraControlResult) -> str:
    """Render Fedora control output for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = "blocked" if not result.command else "failed"
    lines = [f"Fedora control [{status}] {result.action.value}: {result.message}"]
    if result.command:
        lines.append(f"command: {shlex_join(result.command)}")
    return "\n".join(lines)


def _default_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)  # noqa: S603


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command for display only."""

    import shlex

    return shlex.join(command)
