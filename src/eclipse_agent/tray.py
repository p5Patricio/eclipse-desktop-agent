"""System-tray icon for Eclipse showing live runtime status.

Reads the daemon's status server (http://127.0.0.1:11438/status) and shows a
colored tray icon: idle, listening, thinking, speaking, paused (kill switch) or
offline. The menu can pause/resume Eclipse (the kill switch) or quit. The status
and image logic is pure and testable; only ``run_tray`` touches the GUI.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from PIL import Image, ImageDraw

from eclipse_agent.killswitch import KillSwitch

STATUS_URL = "http://127.0.0.1:11438/status"
POLL_INTERVAL_SECONDS = 1.5

_STATUS_COLORS = {
    "idle": (120, 120, 130),
    "listening": (46, 204, 113),
    "thinking": (241, 196, 15),
    "speaking": (52, 152, 219),
    "paused": (231, 76, 60),
    "offline": (90, 90, 90),
}
_STATUS_LABELS = {
    "idle": "Eclipse: en reposo",
    "listening": "Eclipse: escuchando",
    "thinking": "Eclipse: pensando",
    "speaking": "Eclipse: hablando",
    "paused": "Eclipse: en pausa",
    "offline": "Eclipse: sin conexión",
}


def status_color(state: str) -> tuple[int, int, int]:
    return _STATUS_COLORS.get(state, _STATUS_COLORS["offline"])


def status_label(state: str) -> str:
    return _STATUS_LABELS.get(state, _STATUS_LABELS["offline"])


def fetch_status(*, opener: Callable[[str], str] | None = None) -> str:
    """Fetch the daemon status, or 'offline' if the server is unreachable."""

    try:
        if opener is not None:
            raw = opener(STATUS_URL)
        else:
            with urllib.request.urlopen(STATUS_URL, timeout=2) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        return str(json.loads(raw).get("status", "idle"))
    except Exception:  # noqa: BLE001 - server down or unreachable
        return "offline"


def resolve_state(status: str, *, killed: bool) -> str:
    """The displayed state: paused overrides everything; empty means offline."""

    if killed:
        return "paused"
    return status or "offline"


def poll_state(
    *,
    status_opener: Callable[[str], str] | None = None,
    kill_switch: KillSwitch | None = None,
) -> str:
    killed = (kill_switch or KillSwitch()).is_engaged()
    return resolve_state(fetch_status(opener=status_opener), killed=killed)


def make_icon_image(color: tuple[int, int, int], *, size: int = 64) -> Image.Image:
    """Render a filled circle of ``color`` on a transparent square."""

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(2, size // 10)
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(*color, 255))
    return image


def run_tray() -> None:  # pragma: no cover - GUI loop
    import threading

    try:
        import pystray
    except ModuleNotFoundError:
        print('The tray needs the "tray" extra: pip install -e ".[tray]".')
        return

    kill_switch = KillSwitch()
    stop = threading.Event()

    icon = pystray.Icon(
        "eclipse",
        make_icon_image(status_color("offline")),
        status_label("offline"),
        menu=pystray.Menu(
            pystray.MenuItem("Pausar Eclipse", lambda *_: kill_switch.engage()),
            pystray.MenuItem("Reanudar Eclipse", lambda *_: kill_switch.disengage()),
            pystray.MenuItem("Salir", lambda i, *_: (stop.set(), i.stop())),
        ),
    )

    def loop(icon_ref) -> None:
        icon_ref.visible = True
        while not stop.wait(POLL_INTERVAL_SECONDS):
            state = poll_state(kill_switch=kill_switch)
            icon_ref.icon = make_icon_image(status_color(state))
            icon_ref.title = status_label(state)

    icon.run(setup=loop)
