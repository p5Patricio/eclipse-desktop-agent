"""Fedora/KDE native desktop control scaffolding for Eclipse."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from eclipse_agent.desktop_apps import DesktopAppLauncher

DEFAULT_YDOTOOL_SOCKET = "/run/ydotoold/eclipse.sock"


class FedoraControlAction(StrEnum):
    """Initial native-control action families."""

    OPEN_APP = "open_app"
    LIST_WINDOWS = "list_windows"
    FOCUS_WINDOW = "focus_window"
    SCREENSHOT = "screenshot"
    MOVE_MOUSE = "move_mouse"
    CLICK = "click"
    TYPE_TEXT = "type_text"


@dataclass(frozen=True)
class FedoraControlResult:
    """Result of preparing or running a Fedora desktop-control action."""

    success: bool
    action: FedoraControlAction
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False
    output_path: Path | None = None


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


class WaylandScreenCapture:
    """Wayland screenshot adapter backed by grim and optional slurp geometry."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or _default_runner

    def capture(
        self,
        *,
        output_path: str | Path | None = None,
        geometry: str | None = None,
        dry_run: bool = True,
    ) -> FedoraControlResult:
        """Capture a full-screen or fixed-region screenshot."""

        path = Path(output_path).expanduser() if output_path else _default_screenshot_path()
        command = self.build_grim_command(path, geometry=geometry)
        if dry_run:
            return FedoraControlResult(
                success=True,
                action=FedoraControlAction.SCREENSHOT,
                command=command,
                message="Prepared Wayland screenshot command.",
                dry_run=True,
                output_path=path,
            )
        missing = _missing_binaries(("grim",))
        if missing:
            return FedoraControlResult(
                success=False,
                action=FedoraControlAction.SCREENSHOT,
                command=command,
                message=f"Missing required command: {', '.join(missing)}.",
                dry_run=False,
                output_path=path,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        completed = self.runner(command)
        message = (
            "Wayland screenshot captured."
            if completed.returncode == 0
            else completed.stderr.strip() or "Wayland screenshot failed."
        )
        return FedoraControlResult(
            success=completed.returncode == 0,
            action=FedoraControlAction.SCREENSHOT,
            command=command,
            message=message,
            dry_run=False,
            executed=completed.returncode == 0,
            output_path=path,
        )

    def capture_selected_region(
        self,
        *,
        output_path: str | Path | None = None,
        dry_run: bool = True,
    ) -> FedoraControlResult:
        """Select a region with slurp and capture it with grim."""

        path = Path(output_path).expanduser() if output_path else _default_screenshot_path()
        if dry_run:
            command = ("sh", "-c", f"grim -g \"$(slurp)\" {shlex_join((str(path),))}")
            return FedoraControlResult(
                success=True,
                action=FedoraControlAction.SCREENSHOT,
                command=command,
                message="Prepared Wayland region screenshot command.",
                dry_run=True,
                output_path=path,
            )
        missing = _missing_binaries(("grim", "slurp"))
        if missing:
            return FedoraControlResult(
                success=False,
                action=FedoraControlAction.SCREENSHOT,
                command=(),
                message=f"Missing required command: {', '.join(missing)}.",
                dry_run=False,
                output_path=path,
            )
        slurp_result = self.runner(("slurp",))
        if slurp_result.returncode != 0:
            return FedoraControlResult(
                success=False,
                action=FedoraControlAction.SCREENSHOT,
                command=("slurp",),
                message=slurp_result.stderr.strip() or "Region selection failed.",
                dry_run=False,
                output_path=path,
            )
        geometry = slurp_result.stdout.strip()
        if not geometry:
            return FedoraControlResult(
                success=False,
                action=FedoraControlAction.SCREENSHOT,
                command=("slurp",),
                message="Region selection returned no geometry.",
                dry_run=False,
                output_path=path,
            )
        return self.capture(output_path=path, geometry=geometry, dry_run=False)

    def build_grim_command(
        self,
        output_path: str | Path,
        *,
        geometry: str | None = None,
    ) -> tuple[str, ...]:
        """Build a grim command for full-screen or region capture."""

        path = Path(output_path).expanduser()
        if geometry:
            return ("grim", "-g", geometry, str(path))
        return ("grim", str(path))


class WaylandNativeInput:
    """Wayland native input adapter backed by ydotool with explicit confirmation."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        socket_path: str | None = DEFAULT_YDOTOOL_SOCKET,
    ) -> None:
        self.runner = runner or _default_runner
        self.socket_path = socket_path

    def move_mouse(
        self,
        x: int,
        y: int,
        *,
        confirmed: bool = False,
        dry_run: bool = True,
    ) -> FedoraControlResult:
        """Move the pointer to an absolute screen position."""

        command = self._ydotool_command("mousemove", "--absolute", "-x", str(x), "-y", str(y))
        return self._run_native_input(
            action=FedoraControlAction.MOVE_MOUSE,
            command=command,
            confirmed=confirmed,
            dry_run=dry_run,
            success_message="Wayland mouse move executed.",
        )

    def click(
        self,
        *,
        confirmed: bool = False,
        dry_run: bool = True,
    ) -> FedoraControlResult:
        """Perform a left mouse click."""

        command = self._ydotool_command("click", "0xC0")
        return self._run_native_input(
            action=FedoraControlAction.CLICK,
            command=command,
            confirmed=confirmed,
            dry_run=dry_run,
            success_message="Wayland mouse click executed.",
        )

    def type_text(
        self,
        text: str,
        *,
        confirmed: bool = False,
        dry_run: bool = True,
    ) -> FedoraControlResult:
        """Type text into the currently focused surface."""

        command = self._ydotool_command("type", text)
        return self._run_native_input(
            action=FedoraControlAction.TYPE_TEXT,
            command=command,
            confirmed=confirmed,
            dry_run=dry_run,
            success_message="Wayland text input executed.",
        )

    def _run_native_input(
        self,
        *,
        action: FedoraControlAction,
        command: tuple[str, ...],
        confirmed: bool,
        dry_run: bool,
        success_message: str,
    ) -> FedoraControlResult:
        if not confirmed:
            return FedoraControlResult(
                success=False,
                action=action,
                command=command,
                message="Wayland native input requires explicit confirmation.",
                dry_run=dry_run,
            )
        if dry_run:
            return FedoraControlResult(
                success=True,
                action=action,
                command=command,
                message="Prepared confirmed Wayland native input command.",
                dry_run=True,
            )
        missing = _missing_binaries(("ydotool",))
        if missing:
            return FedoraControlResult(
                success=False,
                action=action,
                command=command,
                message=f"Missing required command: {', '.join(missing)}.",
                dry_run=False,
            )
        completed = self.runner(command)
        message = (
            success_message
            if completed.returncode == 0
            else (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Wayland native input failed."
            )
        )
        return FedoraControlResult(
            success=completed.returncode == 0,
            action=action,
            command=command,
            message=message,
            dry_run=False,
            executed=completed.returncode == 0,
        )

    def _ydotool_command(self, *args: str) -> tuple[str, ...]:
        if not self.socket_path:
            return ("ydotool", *args)
        return ("env", f"YDOTOOL_SOCKET={self.socket_path}", "ydotool", *args)


def render_fedora_control_result(result: FedoraControlResult) -> str:
    """Render Fedora control output for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = (
            "blocked"
            if "requires explicit confirmation" in result.message.casefold()
            else "failed"
        )
    lines = [f"Fedora control [{status}] {result.action.value}: {result.message}"]
    if result.command:
        lines.append(f"command: {shlex_join(result.command)}")
    if result.output_path:
        lines.append(f"output: {result.output_path}")
    return "\n".join(lines)


def _default_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)  # noqa: S603


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command for display only."""

    import shlex

    return shlex.join(command)


def _default_screenshot_path() -> Path:
    return Path(tempfile.gettempdir()) / "eclipse-wayland-screenshot.png"


def _missing_binaries(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if shutil.which(name) is None)
