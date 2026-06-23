"""Windows clipboard read/write for Eclipse.

Low-level read/write handlers are injectable so tests never touch the real
system clipboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ClipboardResult:
    """Result of a clipboard read or write."""

    success: bool
    action: str  # "read" or "write"
    text: str
    message: str


def _default_read() -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
        return ""
    finally:
        win32clipboard.CloseClipboard()


def _default_write(text: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class WindowsClipboard:
    """Read from and write to the Windows clipboard."""

    def __init__(
        self,
        *,
        reader: Callable[[], str] | None = None,
        writer: Callable[[str], None] | None = None,
    ) -> None:
        self._reader = reader or _default_read
        self._writer = writer or _default_write

    def read(self) -> ClipboardResult:
        try:
            text = self._reader()
        except Exception as exc:  # noqa: BLE001
            return ClipboardResult(False, "read", "", f"Could not read the clipboard: {exc}")
        if not text:
            return ClipboardResult(True, "read", "", "The clipboard is empty.")
        return ClipboardResult(True, "read", text, text)

    def write(self, text: str) -> ClipboardResult:
        if not text:
            return ClipboardResult(False, "write", "", "Cannot copy empty text.")
        try:
            self._writer(text)
        except Exception as exc:  # noqa: BLE001
            return ClipboardResult(False, "write", text, f"Could not write the clipboard: {exc}")
        return ClipboardResult(True, "write", text, "Copied to the clipboard.")


def render_clipboard_result(result: ClipboardResult) -> str:
    """Render a clipboard result for CLI display."""

    status = "ok" if result.success else "failed"
    return f"Clipboard [{status}] {result.action}: {result.message}"
