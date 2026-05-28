"""Voice input/output primitives for Eclipse."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class TTSProvider(StrEnum):
    """Supported local text-to-speech providers."""

    SPD_SAY = "spd-say"
    ESPEAK_NG = "espeak-ng"


@dataclass(frozen=True)
class SpeechResult:
    """Result of preparing or running text-to-speech."""

    success: bool
    provider: str
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False


@dataclass(frozen=True)
class STTStatus:
    """Availability status for local speech-to-text."""

    available: bool
    provider: str
    message: str


@dataclass(frozen=True)
class RecordingResult:
    """Result of preparing or recording microphone audio."""

    success: bool
    command: tuple[str, ...]
    audio_path: Path
    message: str
    dry_run: bool
    executed: bool = False


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of transcribing an audio file."""

    success: bool
    text: str
    audio_path: Path
    provider: str
    message: str
    segments: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListenResult:
    """Result of a one-shot listen/transcribe attempt."""

    success: bool
    recording: RecordingResult
    transcription: TranscriptionResult | None
    message: str


class CommandRunner(Protocol):
    """Protocol for subprocess-compatible command runners."""

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Run a command and return its completed process."""


class SystemTTS:
    """Small local TTS wrapper around `spd-say`/`espeak-ng`."""

    def __init__(
        self,
        preferred_provider: TTSProvider | str = TTSProvider.SPD_SAY,
        runner: CommandRunner | None = None,
    ) -> None:
        self.preferred_provider = TTSProvider(preferred_provider)
        self.runner = runner or _default_runner

    def build_command(self, text: str) -> tuple[str, ...]:
        """Build a command for the first available local TTS provider."""

        normalized = normalize_spoken_text(text)
        provider = self.select_provider()
        if provider is TTSProvider.SPD_SAY:
            return (provider.value, normalized)
        return (provider.value, "-v", "es-mx", normalized)

    def select_provider(self) -> TTSProvider:
        """Return the preferred provider if available, otherwise fallback."""

        providers = (self.preferred_provider, TTSProvider.ESPEAK_NG, TTSProvider.SPD_SAY)
        for provider in dict.fromkeys(providers):
            if shutil.which(provider.value):
                return provider
        raise RuntimeError("No local TTS provider found. Install spd-say or espeak-ng.")

    def speak(self, text: str, *, dry_run: bool = True) -> SpeechResult:
        """Speak text locally. Dry-run is default for safe CLI tests."""

        try:
            command = self.build_command(text)
        except ValueError as exc:
            return SpeechResult(
                success=False,
                provider=self.preferred_provider.value,
                command=(),
                message=str(exc),
                dry_run=dry_run,
            )
        except RuntimeError as exc:
            return SpeechResult(
                success=False,
                provider="unavailable",
                command=(),
                message=str(exc),
                dry_run=dry_run,
            )

        provider = command[0]
        if dry_run:
            return SpeechResult(
                success=True,
                provider=provider,
                command=command,
                message="Prepared local TTS command.",
                dry_run=True,
            )

        completed = self.runner(command)
        if completed.returncode != 0:
            return SpeechResult(
                success=False,
                provider=provider,
                command=command,
                message=completed.stderr.strip() or "TTS command failed.",
                dry_run=False,
            )
        return SpeechResult(
            success=True,
            provider=provider,
            command=command,
            message="Spoken response sent to local TTS.",
            dry_run=False,
            executed=True,
        )


class MicrophoneRecorder:
    """Record short microphone clips with local Linux audio tools."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or _default_runner

    def build_record_command(self, audio_path: str | Path, *, seconds: int = 5) -> tuple[str, ...]:
        """Build a 16 kHz mono WAV recording command."""

        if seconds <= 0:
            raise ValueError("Recording duration must be positive.")
        output = Path(audio_path).expanduser()
        if shutil.which("arecord"):
            return (
                "arecord",
                "-q",
                "-f",
                "S16_LE",
                "-r",
                "16000",
                "-c",
                "1",
                "-d",
                str(seconds),
                str(output),
            )
        if shutil.which("pw-record"):
            return ("pw-record", "--rate", "16000", "--channels", "1", str(output))
        raise RuntimeError("No microphone recorder found. Install alsa-utils or pipewire tools.")

    def record(
        self,
        audio_path: str | Path,
        *,
        seconds: int = 5,
        dry_run: bool = True,
    ) -> RecordingResult:
        """Prepare or record a short microphone clip."""

        path = Path(audio_path).expanduser()
        try:
            command = self.build_record_command(path, seconds=seconds)
        except (RuntimeError, ValueError) as exc:
            return RecordingResult(False, (), path, str(exc), dry_run=dry_run)
        if dry_run:
            return RecordingResult(True, command, path, "Prepared microphone recording.", True)
        path.parent.mkdir(parents=True, exist_ok=True)
        completed = self.runner(command)
        if completed.returncode != 0:
            message = completed.stderr.strip() or "Microphone recording failed."
            return RecordingResult(False, command, path, message, dry_run=False)
        return RecordingResult(True, command, path, "Microphone audio recorded.", False, True)


class LocalWhisperSTT:
    """Local Whisper STT facade backed by `faster-whisper` when installed."""

    provider = "faster-whisper"

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "es",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language

    def status(self) -> STTStatus:
        """Return whether the local Whisper runtime is importable."""

        try:
            import faster_whisper  # noqa: F401
        except ModuleNotFoundError:
            return STTStatus(False, self.provider, "faster-whisper is not installed.")
        return STTStatus(True, self.provider, "faster-whisper is available.")

    def transcribe_file(self, audio_path: str | Path) -> TranscriptionResult:
        """Transcribe an audio file with faster-whisper."""

        path = Path(audio_path).expanduser()
        if not path.exists():
            return TranscriptionResult(False, "", path, self.provider, "Audio file does not exist.")
        status = self.status()
        if not status.available:
            return TranscriptionResult(False, "", path, self.provider, status.message)

        from faster_whisper import WhisperModel

        model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        segments_iter, _info = model.transcribe(
            str(path),
            beam_size=1,
            language=self.language,
            vad_filter=True,
        )
        segments = tuple(segment.text.strip() for segment in segments_iter if segment.text.strip())
        text = " ".join(segments).strip()
        return TranscriptionResult(True, text, path, self.provider, "Audio transcribed.", segments)


class ListenOnce:
    """Record once and transcribe once."""

    def __init__(
        self,
        recorder: MicrophoneRecorder | None = None,
        stt: LocalWhisperSTT | None = None,
    ) -> None:
        self.recorder = recorder or MicrophoneRecorder()
        self.stt = stt or LocalWhisperSTT()

    def run(
        self,
        *,
        seconds: int = 5,
        audio_path: str | Path | None = None,
        dry_run: bool = True,
    ) -> ListenResult:
        """Record one clip and transcribe it."""

        path = Path(audio_path).expanduser() if audio_path else _default_audio_path()
        recording = self.recorder.record(path, seconds=seconds, dry_run=dry_run)
        if dry_run or not recording.success:
            return ListenResult(recording.success, recording, None, recording.message)
        transcription = self.stt.transcribe_file(recording.audio_path)
        return ListenResult(
            transcription.success,
            recording,
            transcription,
            transcription.message if transcription else recording.message,
        )


def normalize_spoken_text(text: str) -> str:
    """Normalize and validate text before passing it to local TTS."""

    normalized = " ".join(text.strip().split())
    if not normalized:
        raise ValueError("Cannot speak empty text.")
    return normalized


def render_speech_result(result: SpeechResult) -> str:
    """Render speech output for CLI display."""

    status = "executed" if result.executed else "prepared"
    if not result.success:
        status = "failed"
    lines = [f"TTS [{status}] {result.provider}: {result.message}"]
    if result.command:
        lines.append(f"command: {shlex_join(result.command)}")
    return "\n".join(lines)


def render_listen_result(result: ListenResult) -> str:
    """Render listen/transcription output for CLI display."""

    recording_status = "recorded" if result.recording.executed else "prepared"
    if not result.recording.success:
        recording_status = "failed"
    lines = [f"Listen [{recording_status}]: {result.recording.message}"]
    if result.recording.command:
        lines.append(f"record command: {shlex_join(result.recording.command)}")
    lines.append(f"audio: {result.recording.audio_path}")
    if result.transcription:
        marker = "ok" if result.transcription.success else "failed"
        lines.append(
            f"STT [{marker}] {result.transcription.provider}: "
            f"{result.transcription.message}"
        )
        lines.append(f"text: {result.transcription.text}")
    return "\n".join(lines)


def _default_audio_path() -> Path:
    return Path(tempfile.gettempdir()) / "eclipse-listen.wav"


def _default_runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)  # noqa: S603


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command for display only."""

    import shlex

    return shlex.join(command)
