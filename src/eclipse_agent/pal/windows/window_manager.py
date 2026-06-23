from dataclasses import dataclass
from typing import Any
import win32gui
from eclipse_agent.pal.base import WindowManager

@dataclass(frozen=True)
class WindowsControlResult:
    success: bool
    action: str
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False

class WindowsWindowManager(WindowManager):
    def list_windows(self) -> Any:
        windows = []
        def enum_cb(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    extra.append((hwnd, title))
            return True
        win32gui.EnumWindows(enum_cb, windows)
        
        details = [f"HWND: {hwnd}, Title: {title}" for hwnd, title in windows]
        message = "Active windows:\n" + "\n".join(details)
        return WindowsControlResult(
            success=True,
            action="list_windows",
            command=(),
            message=message,
            dry_run=False,
            executed=True,
        )

    def focus_window(self, window_hint: str) -> Any:
        windows = []
        def enum_cb(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and window_hint.lower() in title.lower():
                    extra.append((hwnd, title))
            return True
        win32gui.EnumWindows(enum_cb, windows)
        if not windows:
            return WindowsControlResult(
                success=False,
                action="focus_window",
                command=(),
                message=f"No visible window found matching hint: {window_hint}",
                dry_run=False,
            )
        hwnd, title = windows[0]
        try:
            win32gui.SetForegroundWindow(hwnd)
            return WindowsControlResult(
                success=True,
                action="focus_window",
                command=(),
                message=f"Focused window: {title} (HWND: {hwnd})",
                dry_run=False,
                executed=True,
            )
        except Exception as e:
            return WindowsControlResult(
                success=False,
                action="focus_window",
                command=(),
                message=f"Failed to focus window {title}: {e}",
                dry_run=False,
            )

