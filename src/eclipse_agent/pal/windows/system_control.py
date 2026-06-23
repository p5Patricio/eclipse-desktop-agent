"""Windows system control: volume and media keys, lock, and battery status."""

from __future__ import annotations

import ctypes
from typing import Callable

from eclipse_agent.pal.base import SystemController
from eclipse_agent.system_control import SystemAction, SystemControlResult

# Virtual-key codes for media/volume keys.
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002

_KEY_ACTIONS: dict[SystemAction, int] = {
    SystemAction.VOLUME_UP: VK_VOLUME_UP,
    SystemAction.VOLUME_DOWN: VK_VOLUME_DOWN,
    SystemAction.MUTE: VK_VOLUME_MUTE,
    SystemAction.MEDIA_PLAY_PAUSE: VK_MEDIA_PLAY_PAUSE,
    SystemAction.MEDIA_NEXT: VK_MEDIA_NEXT_TRACK,
    SystemAction.MEDIA_PREVIOUS: VK_MEDIA_PREV_TRACK,
}


def _default_key_press(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _default_lock_screen() -> None:
    ctypes.windll.user32.LockWorkStation()


def _default_read_battery() -> tuple[int, int]:
    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("SystemStatusFlag", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    status = SYSTEM_POWER_STATUS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.pointer(status))
    return int(status.ACLineStatus), int(status.BatteryLifePercent)


class WindowsSystemController(SystemController):
    """Control volume, media, lock, and battery on Windows.

    Low-level handlers are injectable so tests never touch the real machine
    (e.g. they never actually lock the screen or change the volume).
    """

    def __init__(
        self,
        *,
        key_press: Callable[[int], None] | None = None,
        lock_screen: Callable[[], None] | None = None,
        read_battery: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._key_press = key_press or _default_key_press
        self._lock_screen = lock_screen or _default_lock_screen
        self._read_battery = read_battery or _default_read_battery

    def run(self, action: SystemAction, *, dry_run: bool = True) -> SystemControlResult:
        if action is SystemAction.BATTERY:
            return self._battery_status()
        if dry_run:
            return SystemControlResult(
                success=True,
                action=action,
                message=f"Prepared {action.value}.",
                dry_run=True,
            )
        try:
            if action is SystemAction.LOCK:
                self._lock_screen()
                message = "Workstation locked."
            else:
                self._key_press(_KEY_ACTIONS[action])
                message = f"Sent {action.value}."
        except Exception as exc:  # noqa: BLE001
            return SystemControlResult(
                success=False,
                action=action,
                message=f"{action.value} failed: {exc}",
                dry_run=False,
            )
        return SystemControlResult(
            success=True,
            action=action,
            message=message,
            dry_run=False,
            executed=True,
        )

    def _battery_status(self) -> SystemControlResult:
        try:
            ac_line, percent = self._read_battery()
        except Exception as exc:  # noqa: BLE001
            return SystemControlResult(
                success=False,
                action=SystemAction.BATTERY,
                message=f"Battery read failed: {exc}",
                dry_run=False,
            )
        power = {0: "on battery", 1: "on AC power"}.get(ac_line, "unknown power source")
        percent_text = "unknown" if percent in (255, -1) else f"{percent}%"
        return SystemControlResult(
            success=True,
            action=SystemAction.BATTERY,
            message=f"Battery {percent_text}, {power}.",
            dry_run=False,
            executed=True,
        )
