"""Desktop application discovery and launch helpers for Eclipse."""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_APPLICATION_DIRS = (
    Path.home() / ".local/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
)

_SINGLE_ARG_FIELD_CODES = {"%f", "%u"}
_MULTI_ARG_FIELD_CODES = {"%F", "%U"}
_DROP_FIELD_CODES = {"%i", "%d", "%D", "%n", "%N", "%v", "%m"}
_FIELD_CODE_PATTERN = re.compile(r"%[fFuUdDnNickvm]")


@dataclass(frozen=True)
class DesktopApp:
    """A parsed `.desktop` app entry."""

    name: str
    desktop_id: str
    path: Path
    exec_template: str
    startup_wm_class: str | None = None

    def build_command(self, args: Iterable[str] = ()) -> tuple[str, ...]:
        """Build a subprocess-safe command from the desktop Exec template."""

        return expand_exec_template(
            self.exec_template,
            args=tuple(args),
            name=self.name,
            desktop_file=self.path,
        )


@dataclass(frozen=True)
class DesktopLaunchResult:
    """Result of preparing or launching a desktop app."""

    success: bool
    app_name: str
    command: tuple[str, ...]
    message: str
    dry_run: bool
    pid: int | None = None


class DesktopAppLauncher:
    """Resolve and launch desktop apps without shell interpolation."""

    def __init__(self, search_dirs: Iterable[Path] = DEFAULT_APPLICATION_DIRS) -> None:
        self.search_dirs = tuple(Path(directory).expanduser() for directory in search_dirs)

    def discover_apps(self) -> tuple[DesktopApp, ...]:
        """Return launchable desktop entries from configured directories."""

        apps: list[DesktopApp] = []
        for directory in self.search_dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.desktop")):
                app = parse_desktop_entry(path)
                if app:
                    apps.append(app)
        return tuple(apps)

    def find_app(self, query: str) -> DesktopApp | None:
        """Find an app by exact or fuzzy name/desktop id."""

        normalized = _normalize(query)
        apps = self.discover_apps()
        for app in apps:
            if normalized in {_normalize(app.name), _normalize(app.desktop_id)}:
                return app
        for app in apps:
            if normalized in _normalize(app.name) or normalized in _normalize(app.desktop_id):
                return app
        return None

    def build_launch_command(self, app_name: str, args: Iterable[str] = ()) -> tuple[str, ...]:
        """Build the command for an app or raise ValueError if it is unavailable."""

        app = self.find_app(app_name)
        if not app:
            raise ValueError(f"Desktop app not found: {app_name}")
        return app.build_command(args)

    def launch(
        self,
        app_name: str,
        args: Iterable[str] = (),
        *,
        dry_run: bool = True,
    ) -> DesktopLaunchResult:
        """Prepare or launch an app. Dry-run is the safe default."""

        app = self.find_app(app_name)
        if not app:
            return DesktopLaunchResult(
                success=False,
                app_name=app_name,
                command=(),
                message=f"Desktop app not found: {app_name}",
                dry_run=dry_run,
            )

        command = app.build_command(args)
        if not command:
            return DesktopLaunchResult(
                success=False,
                app_name=app.name,
                command=(),
                message=f"Desktop app has no executable command: {app.name}",
                dry_run=dry_run,
            )

        if dry_run:
            return DesktopLaunchResult(
                success=True,
                app_name=app.name,
                command=command,
                message=f"Prepared desktop launch for {app.name}.",
                dry_run=True,
            )

        process = subprocess.Popen(command, start_new_session=True)  # noqa: S603
        return DesktopLaunchResult(
            success=True,
            app_name=app.name,
            command=command,
            message=f"Launched {app.name}.",
            dry_run=False,
            pid=process.pid,
        )


def parse_desktop_entry(path: Path) -> DesktopApp | None:
    """Parse the minimal fields Eclipse needs from a `.desktop` file."""

    fields: dict[str, str] = {}
    in_desktop_entry = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_desktop_entry = line == "[Desktop Entry]"
            if fields and not in_desktop_entry:
                break
            continue
        if not in_desktop_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key] = value

    if fields.get("Type") != "Application" or "Name" not in fields or "Exec" not in fields:
        return None
    if fields.get("NoDisplay", "false").casefold() == "true":
        return None

    return DesktopApp(
        name=fields["Name"],
        desktop_id=path.name,
        path=path,
        exec_template=fields["Exec"],
        startup_wm_class=fields.get("StartupWMClass"),
    )


def expand_exec_template(
    exec_template: str,
    *,
    args: tuple[str, ...] = (),
    name: str = "",
    desktop_file: Path | None = None,
) -> tuple[str, ...]:
    """Expand a freedesktop Exec template into argv without using a shell."""

    command: list[str] = []
    for token in shlex.split(exec_template):
        if token in _SINGLE_ARG_FIELD_CODES:
            if args:
                command.append(args[0])
            continue
        if token in _MULTI_ARG_FIELD_CODES:
            command.extend(args)
            continue
        if token in _DROP_FIELD_CODES:
            continue

        expanded = token.replace("%%", "%")
        expanded = expanded.replace("%c", name)
        if desktop_file:
            expanded = expanded.replace("%k", str(desktop_file))

        expanded = _expand_embedded_arg_codes(expanded, args)
        expanded = _FIELD_CODE_PATTERN.sub("", expanded)
        if expanded:
            command.append(expanded)

    return tuple(command)


def _expand_embedded_arg_codes(token: str, args: tuple[str, ...]) -> str:
    if not args:
        return token
    first_arg = args[0]
    joined_args = " ".join(args)
    return (
        token.replace("%f", first_arg)
        .replace("%u", first_arg)
        .replace("%F", joined_args)
        .replace("%U", joined_args)
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())
