"""Global kill switch — pause Eclipse from acting.

The security model promises a global kill switch. This is a persisted on/off
flag (a file): when engaged, the ``ToolRouter`` refuses to execute any action
and audits the attempt. The flag survives across processes, so the CLI can pause
a running daemon.
"""

from __future__ import annotations

import os
from pathlib import Path


class KillSwitch:
    """A persisted on/off flag. Engaged means Eclipse must not act."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_kill_switch_path()

    def engage(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("engaged", encoding="utf-8")

    def disengage(self) -> None:
        self.path.unlink(missing_ok=True)

    def is_engaged(self) -> bool:
        return self.path.exists()


def default_kill_switch_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "killswitch.flag"
