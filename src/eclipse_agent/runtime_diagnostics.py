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
    """Collect local Windows runtime availability for the next implementation blocks."""

    capabilities = (
        _python_module_status("win32gui", "Windows window management via win32gui."),
        _python_module_status(
            "winrt.windows.ui.notifications.management",
            "Windows notification listener via winrt.",
            next_step="Install the listener extra: pip install -e .[notifications]",
        ),
        _python_module_status("sounddevice", "Audio recording via sounddevice."),
        _sapi_tts_status(),
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
    )
    return RuntimeDiagnostics(capabilities=capabilities)


def _sapi_tts_status() -> CapabilityStatus:
    try:
        import win32com.client
        win32com.client.Dispatch("SAPI.SpVoice")
        return CapabilityStatus(name="sapi_tts", available=True, detail="SAPI speech synthesis ready.")
    except Exception as exc:  # noqa: BLE001
        return CapabilityStatus(
            name="sapi_tts",
            available=False,
            detail="SAPI speech synthesis.",
            next_step=f"SAPI error: {exc}",
        )


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
