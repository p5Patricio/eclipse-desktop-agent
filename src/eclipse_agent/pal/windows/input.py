from dataclasses import dataclass
from typing import Any
import ctypes
from ctypes import Structure, Union, c_ulong, c_short, c_ushort, c_long, pointer, sizeof
from eclipse_agent.pal.base import InputSynthesizer

@dataclass(frozen=True)
class WindowsControlResult:
    success: bool
    action: str
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False

# Windows structures for SendInput
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_long),
        ("dy", c_long),
        ("mouseData", c_ulong),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", ctypes.c_void_p)
    ]

class KEYBDINPUT(Structure):
    _fields_ = [
        ("wVk", c_ushort),
        ("wScan", c_ushort),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", ctypes.c_void_p)
    ]

class HARDWAREINPUT(Structure):
    _fields_ = [
        ("uMsg", c_ulong),
        ("wParamL", c_ushort),
        ("wParamH", c_ushort)
    ]

class INPUT_UNION(Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(Structure):
    _fields_ = [
        ("type", c_ulong),
        ("ii", INPUT_UNION)
    ]

def _send_input(inputs: list[INPUT]):
    if not inputs:
        return
    n_inputs = len(inputs)
    input_array = (INPUT * n_inputs)(*inputs)
    ctypes.windll.user32.SendInput(n_inputs, pointer(input_array), sizeof(INPUT))

class WindowsInputSynthesizer(InputSynthesizer):
    def move_mouse(self, x: int, y: int, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        if not confirmed:
            return WindowsControlResult(False, "move_mouse", (), "Requires explicit confirmation.", dry_run)
        if dry_run:
            return WindowsControlResult(True, "move_mouse", (), "Prepared mouse movement.", True)
        
        try:
            ctypes.windll.user32.SetCursorPos(x, y)
            return WindowsControlResult(True, "move_mouse", (), f"Mouse moved to ({x}, {y}).", False, True)
        except Exception as e:
            return WindowsControlResult(False, "move_mouse", (), f"Failed to move mouse: {e}", False)

    def click(self, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        if not confirmed:
            return WindowsControlResult(False, "click", (), "Requires explicit confirmation.", dry_run)
        if dry_run:
            return WindowsControlResult(True, "click", (), "Prepared mouse click.", True)
        
        try:
            inp_down = INPUT(type=INPUT_MOUSE, ii=INPUT_UNION(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTDOWN, time=0, dwExtraInfo=None)))
            inp_up = INPUT(type=INPUT_MOUSE, ii=INPUT_UNION(mi=MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_LEFTUP, time=0, dwExtraInfo=None)))
            _send_input([inp_down, inp_up])
            return WindowsControlResult(True, "click", (), "Mouse click executed.", False, True)
        except Exception as e:
            return WindowsControlResult(False, "click", (), f"Failed to click mouse: {e}", False)

    def type_text(self, text: str, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        if not confirmed:
            return WindowsControlResult(False, "type_text", (), "Requires explicit confirmation.", dry_run)
        if dry_run:
            return WindowsControlResult(True, "type_text", (), "Prepared text typing.", True)
        
        try:
            inputs = []
            for char in text:
                code = ord(char)
                inputs.append(INPUT(type=INPUT_KEYBOARD, ii=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None))))
                inputs.append(INPUT(type=INPUT_KEYBOARD, ii=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None))))
            _send_input(inputs)
            return WindowsControlResult(True, "type_text", (), f"Typed text: {text}", False, True)
        except Exception as e:
            return WindowsControlResult(False, "type_text", (), f"Failed to type text: {e}", False)

