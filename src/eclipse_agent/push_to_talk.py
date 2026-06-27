"""Global push-to-talk hotkey for Eclipse.

Registers ONE system-wide hotkey via the Win32 ``RegisterHotKey`` API (not a
global keyboard hook, so it never sees other keystrokes), letting the user
trigger Eclipse without the wake word. When the hotkey fires, an activation
callback runs (record -> transcribe -> handle). Parsing is pure and testable;
only ``run_push_to_talk`` touches the OS message loop.
"""

from __future__ import annotations

from collections.abc import Callable

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}
_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    **{f"f{number}": 0x70 + (number - 1) for number in range(1, 13)},
}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse a spec like 'ctrl+alt+space' into (modifier flags, virtual key)."""

    parts = [part.strip().casefold() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError("Hotkey is empty.")
    modifiers = 0
    vk: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        else:
            raise ValueError(f"Unknown hotkey token: {part!r}")
    if vk is None:
        raise ValueError("Hotkey needs a non-modifier key, e.g. ctrl+alt+space.")
    return modifiers, vk


def run_push_to_talk(
    on_activate: Callable[[], object],
    *,
    hotkey: str = "ctrl+alt+e",
) -> None:  # pragma: no cover - OS message loop
    import ctypes
    from ctypes import wintypes

    modifiers, vk = parse_hotkey(hotkey)
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, 1, modifiers, vk):
        print(f"Could not register hotkey {hotkey!r} (already in use?).")
        return
    print(f"Push-to-talk active on {hotkey}. Press it to talk; Ctrl+C to quit.")
    try:
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
            if message.message == WM_HOTKEY:
                try:
                    on_activate()
                except Exception as exc:  # noqa: BLE001 - keep listening after a failure
                    print(f"Activation failed: {exc}")
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnregisterHotKey(None, 1)
