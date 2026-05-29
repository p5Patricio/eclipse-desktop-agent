"""Live notification listener scaffolding for Fedora/KDE D-Bus notifications."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Iterable, Protocol

from eclipse_agent.notifications import (
    DBusNotificationListenerPlan,
    NotificationCenter,
    NotificationProcessingResult,
    parse_dbus_monitor_notify,
)
from eclipse_agent.voice import shlex_join


class PopenFactory(Protocol):
    """Factory protocol for tests and subprocess integration."""

    def __call__(
        self,
        command: tuple[str, ...],
    ) -> subprocess.Popen[str]:
        """Start a process that yields text stdout."""


@dataclass(frozen=True, kw_only=True)
class DBusNotificationDaemonResult:
    """Result of running or dry-running the D-Bus notification listener."""

    success: bool
    command: tuple[str, ...]
    processed: int
    message: str
    dry_run: bool
    executed: bool = False
    results: tuple[NotificationProcessingResult, ...] = ()
    stderr: str = ""


class DBusNotificationDaemon:
    """Connect `dbus-monitor` output to `NotificationCenter`.

    This is still a lightweight first daemon slice. It uses `dbus-monitor` because it
    is available on Fedora/KDE and keeps the Python package dependency-free. A later
    iteration can replace this with a native D-Bus library while keeping the same
    NotificationCenter/store/rules behavior.
    """

    def __init__(
        self,
        *,
        center: NotificationCenter | None = None,
        popen_factory: PopenFactory | None = None,
    ) -> None:
        self.center = center or NotificationCenter()
        self.popen_factory = popen_factory or _default_popen

    def command(self, *, seconds: int | None = None) -> tuple[str, ...]:
        """Return the process command, optionally bounded by GNU timeout."""

        base_command = DBusNotificationListenerPlan().command
        if seconds and seconds > 0:
            return ("timeout", f"{seconds}s", *base_command)
        return base_command

    def process_lines(
        self,
        lines: Iterable[str],
        *,
        speak: bool = False,
        persist: bool = True,
    ) -> DBusNotificationDaemonResult:
        """Process already-open dbus-monitor lines.

        Tests and future daemons can feed fixture lines here without spawning a real
        session-bus monitor.
        """

        results: list[NotificationProcessingResult] = []
        for block in iter_dbus_notify_blocks(lines):
            event = parse_dbus_monitor_notify(block)
            if event is None:
                continue
            results.append(self.center.ingest(event, speak=speak, persist=persist))

        return DBusNotificationDaemonResult(
            success=True,
            command=DBusNotificationListenerPlan().command,
            processed=len(results),
            message=f"Processed {len(results)} notification(s) from D-Bus stream.",
            dry_run=False,
            executed=False,
            results=tuple(results),
        )

    def run(
        self,
        *,
        seconds: int | None = 30,
        speak: bool = False,
        dry_run: bool = True,
    ) -> DBusNotificationDaemonResult:
        """Run the D-Bus listener.

        Dry-run is the safe default and only returns the command. In execute mode,
        `seconds` defaults to 30 so development runs do not accidentally block
        forever. Use `seconds=0` for an unbounded daemon process.
        """

        command = self.command(seconds=seconds)
        if dry_run:
            return DBusNotificationDaemonResult(
                success=True,
                command=command,
                processed=0,
                message="Prepared D-Bus notification listener command.",
                dry_run=True,
            )

        process = self.popen_factory(command)
        if process.stdout is None:
            return DBusNotificationDaemonResult(
                success=False,
                command=command,
                processed=0,
                message="D-Bus monitor did not expose stdout.",
                dry_run=False,
                executed=True,
            )

        result = self.process_lines(process.stdout, speak=speak, persist=True)
        stderr = ""
        if process.stderr:
            stderr = process.stderr.read().strip()
        returncode = process.wait()
        timed_out = returncode == 124 and bool(seconds and seconds > 0)
        success = returncode == 0 or timed_out
        message = result.message
        if timed_out:
            message += " Listener stopped after requested timeout."
        elif not success:
            message += f" Listener exited with code {returncode}."
        return DBusNotificationDaemonResult(
            success=success,
            command=command,
            processed=result.processed,
            message=message,
            dry_run=False,
            executed=True,
            results=result.results,
            stderr=stderr,
        )


def iter_dbus_notify_blocks(lines: Iterable[str]) -> tuple[str, ...]:
    """Yield complete `org.freedesktop.Notifications.Notify` blocks."""

    blocks: list[str] = []
    current: list[str] = []
    capturing = False
    for line in lines:
        if _is_new_dbus_message(line):
            if capturing and current:
                blocks.append("".join(current))
            capturing = _is_notify_header(line)
            current = [line] if capturing else []
            continue
        if capturing:
            current.append(line)

    if capturing and current:
        blocks.append("".join(current))
    return tuple(blocks)


def render_dbus_notification_daemon_result(result: DBusNotificationDaemonResult) -> str:
    """Render listener output for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = "failed"
    lines = [
        f"D-Bus notifications [{status}]: {result.message}",
        f"command: {shlex_join(result.command)}",
    ]
    if result.stderr:
        lines.append(f"stderr: {result.stderr}")
    for item in result.results:
        lines.append(
            f"- {item.stored_event.id if item.stored_event else item.event.id}: "
            f"{item.action.value} {item.event.display_source}"
        )
    return "\n".join(lines)


def _is_new_dbus_message(line: str) -> bool:
    return line.startswith(("method call ", "signal ", "method return ", "error "))


def _is_notify_header(line: str) -> bool:
    return "org.freedesktop.Notifications" in line and "member=Notify" in line


def _default_popen(command: tuple[str, ...]) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
