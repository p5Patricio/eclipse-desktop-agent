import os
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable
from eclipse_agent.pal.base import AppLauncher
from eclipse_agent.desktop_control import DesktopLaunchResult

@dataclass(frozen=True)
class WindowsApp:
    name: str
    path: Path
    target_path: str = ""

class WindowsAppLauncher(AppLauncher):
    def __init__(self, search_dirs: Iterable[str | Path] | None = None) -> None:
        if search_dirs is not None:
            self.search_dirs = tuple(Path(d) for d in search_dirs)
        else:
            common_start_menu = Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft\\Windows\\Start Menu\\Programs"
            user_start_menu = Path(os.environ.get("APPDATA", "C:\\Users\\Default\\AppData\\Roaming")) / "Microsoft\\Windows\\Start Menu\\Programs"
            self.search_dirs = (common_start_menu, user_start_menu)

    def discover_apps(self) -> tuple[WindowsApp, ...]:
        apps: list[WindowsApp] = []
        for directory in self.search_dirs:
            if not directory.exists():
                continue
            for path in directory.rglob("*.lnk"):
                try:
                    name = path.stem
                    apps.append(WindowsApp(name=name, path=path))
                except Exception:
                    pass
        return tuple(apps)

    def find_app(self, query: str) -> WindowsApp | None:
        normalized = query.lower()
        apps = self.discover_apps()
        # Exact match
        for app in apps:
            if app.name.lower() == normalized:
                return app
        # Substring match
        for app in apps:
            if normalized in app.name.lower():
                return app
        return None

    def _resolve_shortcut(self, lnk_path: Path) -> str:
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(lnk_path))
            return shortcut.TargetPath
        except Exception:
            return ""

    def launch(
        self,
        app_name: str,
        args: Iterable[str] = (),
        *,
        dry_run: bool = True,
    ) -> DesktopLaunchResult:
        if app_name.startswith(("http://", "https://")):
            command = ("start", app_name)
            if dry_run:
                return DesktopLaunchResult(
                    success=True,
                    app_name=app_name,
                    command=command,
                    message=f"Prepared desktop launch for URL {app_name}.",
                    dry_run=True,
                )
            try:
                os.startfile(app_name)
                return DesktopLaunchResult(
                    success=True,
                    app_name=app_name,
                    command=command,
                    message=f"Launched URL {app_name}.",
                    dry_run=False,
                )
            except Exception as e:
                return DesktopLaunchResult(
                    success=False,
                    app_name=app_name,
                    command=command,
                    message=f"Failed to launch URL: {e}",
                    dry_run=False,
                )

        app = self.find_app(app_name)
        if not app:
            return DesktopLaunchResult(
                success=False,
                app_name=app_name,
                command=(),
                message=f"File not found: application shortcut not found: {app_name}",
                dry_run=dry_run,
            )
        
        target = self._resolve_shortcut(app.path)
        command = (target,) if target else ()
        
        if dry_run:
            return DesktopLaunchResult(
                success=True,
                app_name=app.name,
                command=command,
                message=f"Prepared desktop launch for {app.name}.",
                dry_run=True,
            )
        
        try:
            os.startfile(str(app.path))
            return DesktopLaunchResult(
                success=True,
                app_name=app.name,
                command=command,
                message=f"Launched {app.name}.",
                dry_run=False,
            )
        except Exception as e:
            return DesktopLaunchResult(
                success=False,
                app_name=app.name,
                command=command,
                message=f"Failed to launch app: {e}",
                dry_run=False,
            )

