"""Runtime diagnostics for Eclipse local capabilities."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityStatus:
    """One runtime capability status line."""

    name: str
    available: bool
    detail: str
    next_step: str = ""


@dataclass(frozen=True)
class RuntimeDiagnostics:
    """Collection of runtime capability statuses."""

    capabilities: tuple[CapabilityStatus, ...]

    @property
    def ready_count(self) -> int:
        return sum(1 for capability in self.capabilities if capability.available)

    def render(self) -> str:
        """Render diagnostics for CLI output."""

        lines = [f"Eclipse runtime diagnostics: {self.ready_count}/{len(self.capabilities)} ready"]
        for capability in self.capabilities:
            marker = "OK" if capability.available else "MISSING"
            lines.append(f"- [{marker}] {capability.name}: {capability.detail}")
            if capability.next_step and not capability.available:
                lines.append(f"  next: {capability.next_step}")
        return "\n".join(lines)


def collect_runtime_diagnostics() -> RuntimeDiagnostics:
    """Collect local runtime availability for the next implementation blocks."""

    capabilities = (
        _binary_status("spd-say", "Local TTS via Speech Dispatcher."),
        _binary_status("espeak-ng", "Fallback local TTS."),
        _binary_status("arecord", "Microphone capture via ALSA WAV recording."),
        _binary_status("pw-record", "Microphone capture via PipeWire recording."),
        _python_module_status("pyaudio", "Optional Python microphone capture dependency."),
        _python_module_status(
            "faster_whisper",
            "Local Whisper STT runtime.",
            next_step="Install faster-whisper or wire whisper.cpp.",
        ),
        _binary_status(
            "agent-browser",
            "Vercel browser automation CLI.",
            next_step="Install agent-browser and run agent-browser install.",
        ),
        _binary_status("dbus-monitor", "D-Bus notification observation."),
        _binary_status("gdbus", "D-Bus method calls and inspection."),
        _binary_status(
            "ydotool",
            "Last-resort Wayland keyboard/mouse automation.",
            next_step="Use only after semantic APIs/AT-SPI/KWin are insufficient.",
        ),
        _binary_status(
            "kdotool",
            "KDE window control helper if installed.",
            next_step="Optional; KWin scripts/D-Bus may be used instead.",
        ),
    )
    return RuntimeDiagnostics(capabilities=capabilities)


def _binary_status(name: str, detail: str, next_step: str = "") -> CapabilityStatus:
    path = shutil.which(name)
    if path:
        return CapabilityStatus(name=name, available=True, detail=f"{detail} Found at {path}.")
    return CapabilityStatus(name=name, available=False, detail=detail, next_step=next_step)


def _python_module_status(name: str, detail: str, next_step: str = "") -> CapabilityStatus:
    if importlib.util.find_spec(name):
        status_detail = f"{detail} Python module importable."
        return CapabilityStatus(name=name, available=True, detail=status_detail)
    return CapabilityStatus(name=name, available=False, detail=detail, next_step=next_step)
