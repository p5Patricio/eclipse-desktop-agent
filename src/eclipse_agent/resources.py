"""Resource guidance for Eclipse runtime profiles.

The numbers here are deliberately approximate planning ranges. They are intended to
keep product decisions explicit before we wire actual audio, STT, and notification
listeners into the daemon.
"""

from __future__ import annotations

from dataclasses import dataclass

from eclipse_agent.activation import ActivationMode


@dataclass(frozen=True)
class ResourceProfile:
    """Human-readable estimate for an activation mode."""

    activation_mode: ActivationMode
    idle_cpu: str
    active_cpu: str
    idle_ram_mb: tuple[int, int]
    active_ram_mb: tuple[int, int]
    disk_mb: tuple[int, int]
    recommendation: str
    notes: tuple[str, ...]

    def render(self) -> str:
        """Render a compact report for CLI output."""

        notes = "\n".join(f"  - {note}" for note in self.notes)
        return (
            f"Activation mode: {self.activation_mode.value}\n"
            f"Idle CPU: {self.idle_cpu}\n"
            f"Active CPU: {self.active_cpu}\n"
            f"Idle RAM: {self.idle_ram_mb[0]}-{self.idle_ram_mb[1]} MB\n"
            f"Active RAM: {self.active_ram_mb[0]}-{self.active_ram_mb[1]} MB\n"
            f"Disk: {self.disk_mb[0]}-{self.disk_mb[1]} MB\n"
            f"Recommendation: {self.recommendation}\n"
            f"Notes:\n{notes}"
        )


def estimate_resource_profile(mode: ActivationMode | str) -> ResourceProfile:
    """Return planning-level resource estimates for an activation mode."""

    mode = ActivationMode(mode)
    if mode is ActivationMode.PUSH_TO_TALK:
        return ResourceProfile(
            activation_mode=mode,
            idle_cpu="~0% while waiting",
            active_cpu="medium only during recording/transcription",
            idle_ram_mb=(40, 120),
            active_ram_mb=(400, 1400),
            disk_mb=(500, 1600),
            recommendation="Best for battery/privacy, but less Jarvis-like.",
            notes=(
                "No microphone processing until the user presses a key.",
                "Whisper model storage dominates disk usage once local STT is installed.",
            ),
        )
    if mode is ActivationMode.CONTINUOUS_STT:
        return ResourceProfile(
            activation_mode=mode,
            idle_cpu="medium/high because STT never stops",
            active_cpu="high for long conversations or CPU-only transcription",
            idle_ram_mb=(800, 2500),
            active_ram_mb=(1200, 4000),
            disk_mb=(500, 3000),
            recommendation="Avoid for MVP; expensive, hot, and privacy-sensitive.",
            notes=(
                "This means continuous transcription, not just a local wake-word detector.",
                "It can noticeably affect laptop thermals and battery life.",
                "Use only for explicit experiments with a visible privacy indicator.",
            ),
        )
    return ResourceProfile(
        activation_mode=mode,
        idle_cpu="low, typically wake-word/VAD only",
        active_cpu="medium/high only after wake phrase or notification workflow",
        idle_ram_mb=(80, 250),
        active_ram_mb=(500, 1800),
        disk_mb=(600, 1800),
        recommendation="Recommended default: always-on daemon + local wake word.",
        notes=(
            "Matches the Alexa/Jarvis feel without running full Whisper 24/7.",
            "Notification monitoring is lightweight compared with continuous STT.",
            "Keep all wake-word audio local until the user says 'Eclipse'.",
        ),
    )
