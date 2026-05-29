"""systemd user-service support for Eclipse's notification listener."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eclipse_agent.voice import shlex_join

DEFAULT_SERVICE_NAME = "eclipse-notifications.service"


class CommandRunner(Protocol):
    """Protocol for subprocess-compatible command runners."""

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Run a command and return its completed process."""


@dataclass(frozen=True, kw_only=True)
class NotificationServiceSpec:
    """Configuration for the systemd user unit."""

    project_dir: Path = field(default_factory=lambda: Path.cwd())
    python_executable: str = field(default_factory=lambda: sys.executable)
    service_name: str = DEFAULT_SERVICE_NAME
    seconds: int = 0
    speak: bool = False
    store_path: Path | None = None

    @property
    def unit_path(self) -> Path:
        """Return the default user-unit path for this service."""

        return Path.home() / ".config/systemd/user" / self.service_name

    @property
    def exec_start(self) -> tuple[str, ...]:
        """Build the ExecStart argv for the long-running notification listener."""

        command = (
            self.python_executable,
            "-m",
            "eclipse_agent",
            "notifications-listen",
            "--seconds",
            str(self.seconds),
            "--execute",
        )
        if self.speak:
            command = (*command, "--speak")
        if self.store_path:
            command = (*command, "--store", str(self.store_path))
        return command


@dataclass(frozen=True, kw_only=True)
class NotificationServiceResult:
    """Result of rendering/installing/enabling the user service."""

    success: bool
    action: str
    service_name: str
    unit_path: Path
    message: str
    dry_run: bool
    unit_content: str = ""
    commands: tuple[tuple[str, ...], ...] = ()
    stdout: str = ""
    stderr: str = ""


class NotificationUserServiceManager:
    """Render and optionally install Eclipse's notification systemd user unit."""

    def __init__(
        self,
        *,
        spec: NotificationServiceSpec | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.spec = spec or NotificationServiceSpec()
        self.runner = runner or _default_runner

    def render_unit(self) -> str:
        """Render the systemd user service content."""

        spec = self.spec
        return "\n".join(
            (
                "[Unit]",
                "Description=Eclipse notification listener",
                "Documentation=https://github.com/patodev/eclipse-desktop-agent",
                "After=graphical-session.target",
                "PartOf=graphical-session.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={_systemd_escape(spec.project_dir)}",
                "Environment=PYTHONPATH=src",
                f"ExecStart={_systemd_command(spec.exec_start)}",
                "Restart=on-failure",
                "RestartSec=5",
                "KillSignal=SIGINT",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            )
        )

    def render(self) -> NotificationServiceResult:
        """Return the unit content without touching disk."""

        return NotificationServiceResult(
            success=True,
            action="render",
            service_name=self.spec.service_name,
            unit_path=self.spec.unit_path,
            message="Rendered systemd user service unit.",
            dry_run=True,
            unit_content=self.render_unit(),
        )

    def install(self, *, dry_run: bool = True) -> NotificationServiceResult:
        """Write the user unit and prepare/reload systemd user state."""

        unit_content = self.render_unit()
        commands = (("systemctl", "--user", "daemon-reload"),)
        if dry_run:
            return NotificationServiceResult(
                success=True,
                action="install",
                service_name=self.spec.service_name,
                unit_path=self.spec.unit_path,
                message="Prepared service install; no files were written.",
                dry_run=True,
                unit_content=unit_content,
                commands=commands,
            )

        self.spec.unit_path.parent.mkdir(parents=True, exist_ok=True)
        self.spec.unit_path.write_text(unit_content, encoding="utf-8")
        completed = self.runner(commands[0])
        return NotificationServiceResult(
            success=completed.returncode == 0,
            action="install",
            service_name=self.spec.service_name,
            unit_path=self.spec.unit_path,
            message=(
                "Installed service unit and reloaded user systemd."
                if completed.returncode == 0
                else "Installed service unit but daemon-reload failed."
            ),
            dry_run=False,
            unit_content=unit_content,
            commands=commands,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def enable_now(self, *, dry_run: bool = True) -> NotificationServiceResult:
        """Prepare or run `systemctl --user enable --now` for the service."""

        commands = (
            ("systemctl", "--user", "enable", "--now", self.spec.service_name),
        )
        if dry_run:
            return NotificationServiceResult(
                success=True,
                action="enable_now",
                service_name=self.spec.service_name,
                unit_path=self.spec.unit_path,
                message="Prepared enable/start command; nothing was executed.",
                dry_run=True,
                commands=commands,
            )

        completed = self.runner(commands[0])
        return NotificationServiceResult(
            success=completed.returncode == 0,
            action="enable_now",
            service_name=self.spec.service_name,
            unit_path=self.spec.unit_path,
            message=(
                "Enabled and started service."
                if completed.returncode == 0
                else "Failed to enable/start service."
            ),
            dry_run=False,
            commands=commands,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def render_notification_service_result(result: NotificationServiceResult) -> str:
    """Render service-management output for the CLI."""

    status = "ok" if result.success else "failed"
    mode = "dry-run" if result.dry_run else "executed"
    lines = [
        f"Notification service [{status}/{mode}] {result.action}: {result.message}",
        f"unit: {result.unit_path}",
    ]
    if result.unit_content:
        lines.append("--- unit ---")
        lines.append(result.unit_content.rstrip())
    for command in result.commands:
        lines.append(f"command: {shlex_join(command)}")
    if result.stdout:
        lines.append(f"stdout: {result.stdout.strip()}")
    if result.stderr:
        lines.append(f"stderr: {result.stderr.strip()}")
    return "\n".join(lines)


def _systemd_command(command: tuple[str, ...]) -> str:
    return " ".join(_systemd_escape(part) for part in command)


def _systemd_escape(value: str | Path) -> str:
    text = str(value)
    if not text:
        return '""'
    if any(character.isspace() or character in {'"', "\\"} for character in text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _default_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)  # noqa: S603
