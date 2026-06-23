"""Voice input/output primitives for Eclipse."""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Protocol

if TYPE_CHECKING:
    from eclipse_agent.pal.base import AudioRecorder, TTSProvider

DEFAULT_WAKE_WORD_MODEL_NAME = "eclipse.onnx"


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


@dataclass(frozen=True)
class WakeWordStatus:
    """Availability status for efficient wake-word detection."""

    available: bool
    provider: str
    message: str


@dataclass(frozen=True)
class WakeWordDetectionResult:
    """Result of an openwakeword detection pass."""

    success: bool
    detected: bool
    provider: str
    message: str
    dry_run: bool
    executed: bool = False
    label: str = ""
    score: float = 0.0


class WakeWordModel(Protocol):
    """Protocol for openwakeword-compatible model objects."""

    def predict(self, frame: object) -> dict[str, float]:
        """Return wake-word confidence scores for one audio frame."""


WakeWordModelFactory = Callable[..., WakeWordModel]


class SystemTTS:
    """Local text-to-speech via the Windows platform layer (SAPI).

    Delegates to the platform TTS provider. A provider can be injected for tests.
    """

    def __init__(self, provider: TTSProvider | None = None) -> None:
        self._provider = provider

    def speak(self, text: str, *, dry_run: bool = True) -> SpeechResult:
        """Speak text using the Windows TTS provider."""

        provider = self._provider
        if provider is None:
            from eclipse_agent.pal.factory import PlatformFactory

            provider = PlatformFactory.get_tts_provider()
        return provider.speak(text, dry_run=dry_run)


class MicrophoneRecorder:
    """Record short microphone clips via the Windows platform layer.

    Delegates to the platform audio recorder. A recorder can be injected for tests.
    """

    def __init__(self, recorder: AudioRecorder | None = None) -> None:
        self._recorder = recorder

    def record(
        self,
        audio_path: str | Path,
        *,
        seconds: int = 5,
        dry_run: bool = True,
    ) -> RecordingResult:
        """Prepare or record a short microphone clip."""

        recorder = self._recorder
        if recorder is None:
            from eclipse_agent.pal.factory import PlatformFactory

            recorder = PlatformFactory.get_audio_recorder()
        return recorder.record(audio_path, seconds=seconds, dry_run=dry_run)


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


def play_sound_cue(frequency: float, duration: float) -> None:
    """Play a sound cue at the specified frequency and duration using numpy and sounddevice.
    Includes a fade-out to prevent pops.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        return

    sample_rate = 44100
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave = np.sin(2 * np.pi * frequency * t)
    
    # Fade out
    fade_duration = min(0.01, duration / 2.0)
    fade_samples = int(sample_rate * fade_duration)
    if fade_samples > 0:
        fade_out = np.linspace(1.0, 0.0, fade_samples)
        wave[-fade_samples:] *= fade_out

    sd.play(wave, sample_rate)
    sd.wait()


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
        if not dry_run:
            play_sound_cue(880.0, 0.1)
        recording = self.recorder.record(path, seconds=seconds, dry_run=dry_run)
        if not dry_run:
            play_sound_cue(440.0, 0.1)
        if dry_run or not recording.success:
            return ListenResult(recording.success, recording, None, recording.message)
        transcription = self.stt.transcribe_file(recording.audio_path)
        return ListenResult(
            transcription.success,
            recording,
            transcription,
            transcription.message if transcription else recording.message,
        )



class OpenWakeWordTrigger:
    """Efficient wake-word trigger backed by openwakeword.

    This class only runs lightweight wake-word inference on short PCM frames.
    Full Whisper transcription is deliberately left to `ListenOnce` after a
    positive wake-word detection.
    """

    provider = "openwakeword"

    def __init__(
        self,
        *,
        wake_phrase: str = "Eclipse",
        model_paths: tuple[str | Path, ...] = (),
        builtin_model: str | None = "hey_jarvis",
        threshold: float = 0.5,
        sample_rate: int = 16000,
        frame_duration_ms: int = 80,
        model: WakeWordModel | None = None,
        model_factory: WakeWordModelFactory | None = None,
        frame_source: Iterable[object] | None = None,
    ) -> None:
        self.wake_phrase = wake_phrase
        self.builtin_model = builtin_model
        explicit_model_paths = tuple(Path(path).expanduser() for path in model_paths)
        if explicit_model_paths:
            self.model_paths = explicit_model_paths
        else:
            self.model_paths = ()
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.model = model
        self.model_factory = model_factory
        self.frame_source = frame_source
        self._startup_warnings: list[str] = []

    @property
    def frame_size(self) -> int:
        """Return the number of samples per wake-word frame."""

        return int(self.sample_rate * self.frame_duration_ms / 1000)

    def status(self) -> WakeWordStatus:
        """Return whether openwakeword, audio streaming, and the Eclipse model are ready."""

        dependency_warning = _dependency_warning()
        if self.model_paths:
            missing = tuple(path for path in self.model_paths if not path.exists())
            if missing:
                labels = ", ".join(str(path) for path in missing)
                if self.builtin_model:
                    return WakeWordStatus(
                        True,
                        self.provider,
                        (
                            f"Custom wake-word model missing: {labels}; "
                            f"using fallback {self.builtin_model}. {dependency_warning}"
                        ).strip(),
                    )
                return WakeWordStatus(
                    False,
                    self.provider,
                    (
                        "Custom Eclipse wake-word model is missing. "
                        f"Expected: {labels}. Generate it with scripts/generate_wakeword.py."
                    ),
                )
            if self.builtin_model:
                return WakeWordStatus(
                    True,
                    self.provider,
                    (
                        "Configured preferred custom wake-word model; "
                        f"fallback {self.builtin_model} remains available. {dependency_warning}"
                    ).strip(),
                )
            return WakeWordStatus(
                True,
                self.provider,
                f"Configured custom wake-word model. {dependency_warning}".strip(),
            )
        if self.builtin_model:
            return WakeWordStatus(
                True,
                self.provider,
                f"Using builtin wake-word fallback {self.builtin_model}. {dependency_warning}".strip(),
            )
        return WakeWordStatus(False, self.provider, "No wake-word model is configured.")

    def listen(
        self,
        *,
        timeout_seconds: float | None = None,
        dry_run: bool = True,
    ) -> WakeWordDetectionResult:
        """Wait for the wake word without running Whisper transcription."""

        if dry_run:
            return WakeWordDetectionResult(
                success=True,
                detected=False,
                provider=self.provider,
                message="Prepared openwakeword listener; use --execute to monitor the microphone.",
                dry_run=True,
            )

        try:
            model = self.model or self._load_model()
            frames = self.frame_source or self._microphone_frames(timeout_seconds=timeout_seconds)
            return self._detect_from_frames(model, frames, timeout_seconds=timeout_seconds)
        except (RuntimeError, ValueError) as exc:
            return WakeWordDetectionResult(
                success=False,
                detected=False,
                provider=self.provider,
                message=str(exc),
                dry_run=False,
                executed=False,
            )

    def _detect_from_frames(
        self,
        model: WakeWordModel,
        frames: Iterable[object],
        *,
        timeout_seconds: float | None,
    ) -> WakeWordDetectionResult:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        best_label = ""
        best_score = 0.0
        for frame in frames:
            prediction = model.predict(frame)
            label, score = self._best_relevant_prediction(prediction)
            if score > best_score:
                best_label = label
                best_score = score
            if score >= self.threshold:
                message = f"Wake word detected for {self.wake_phrase}."
                if self._startup_warnings:
                    message = f"{message} {' '.join(self._startup_warnings)}"
                return WakeWordDetectionResult(
                    success=True,
                    detected=True,
                    provider=self.provider,
                    message=message,
                    dry_run=False,
                    executed=True,
                    label=label or self.wake_phrase,
                    score=score,
                )
            if deadline and time.monotonic() >= deadline:
                break
        return WakeWordDetectionResult(
            success=True,
            detected=False,
            provider=self.provider,
            message="Wake word was not detected before timeout.",
            dry_run=False,
            executed=True,
            label=best_label,
            score=best_score,
        )

    def _load_model(self) -> WakeWordModel:
        Model = self.model_factory or self._import_openwakeword_model()

        if self.model_paths:
            missing = tuple(path for path in self.model_paths if not path.exists())
            if missing:
                labels = ", ".join(str(path) for path in missing)
                warning = (
                    f"Custom wake-word model missing: {labels}; "
                    f"using fallback {self.builtin_model}."
                )
                if not self.builtin_model:
                    raise ValueError(
                        "Wake-word model file does not exist: "
                        f"{labels}. Generate the Eclipse model with scripts/generate_wakeword.py."
                    )
                self._startup_warnings.append(warning)
                return Model(wakeword_models=[self.builtin_model], inference_framework="onnx")

            has_onnx = any(str(p).endswith(".onnx") for p in self.model_paths)
            framework = "onnx" if has_onnx else "tflite"
            try:
                return Model(
                    wakeword_models=[str(path) for path in self.model_paths],
                    inference_framework=framework,
                )
            except Exception as exc:
                if not self.builtin_model:
                    raise RuntimeError("Custom wake-word model failed to load.") from exc
                self._startup_warnings.append(
                    f"custom wake-word model failed to load; using fallback {self.builtin_model}."
                )
                return Model(wakeword_models=[self.builtin_model], inference_framework="onnx")

        if self.builtin_model:
            return Model(wakeword_models=[self.builtin_model], inference_framework="onnx")
        raise RuntimeError("No wake-word model is configured.")

    def _import_openwakeword_model(self) -> WakeWordModelFactory:
        try:
            from openwakeword.model import Model
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"Missing Python module: {exc.name}.") from exc
        return Model

    def _best_relevant_prediction(self, prediction: dict[str, float]) -> tuple[str, float]:
        """Return the highest wake-phrase score from one model prediction."""

        if self.model_paths or self.builtin_model:
            return _best_prediction(prediction)

        normalized_phrase = _normalize_prediction_label(self.wake_phrase)
        relevant = {
            label: score
            for label, score in prediction.items()
            if normalized_phrase and normalized_phrase in _normalize_prediction_label(label)
        }
        return _best_prediction(relevant)

    def _microphone_frames(self, *, timeout_seconds: float | None) -> Iterable[object]:
        try:
            import numpy as np
            import sounddevice as sd
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"Missing Python module: {exc.name}.") from exc

        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_size,
        ) as stream:
            while True:
                data, overflowed = stream.read(self.frame_size)
                if overflowed:
                    continue
                yield np.frombuffer(data, dtype=np.int16)
                if deadline and time.monotonic() >= deadline:
                    return


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


def render_wake_word_result(result: WakeWordDetectionResult) -> str:
    """Render wake-word detection output for CLI display."""

    status = "detected" if result.detected else "idle"
    if not result.success:
        status = "failed"
    elif result.dry_run:
        status = "prepared"
    lines = [f"Wake word [{status}] {result.provider}: {result.message}"]
    if result.label or result.score:
        lines.append(f"label: {result.label or '<unknown>'}")
        lines.append(f"score: {result.score:.3f}")
    return "\n".join(lines)


def _default_audio_path() -> Path:
    return Path(tempfile.gettempdir()) / "eclipse-listen.wav"


def default_wake_word_model_path() -> Path:
    """Return the designated custom openwakeword model path for the Eclipse phrase."""

    explicit_path = _path_from_env("ECLIPSE_WAKEWORD_MODEL_PATH")
    if explicit_path:
        return explicit_path

    models_dir = _path_from_env("ECLIPSE_MODELS_DIR")
    if models_dir:
        return models_dir / DEFAULT_WAKE_WORD_MODEL_NAME

    project_root = Path(__file__).resolve().parents[2]
    return project_root / "models" / DEFAULT_WAKE_WORD_MODEL_NAME


def _path_from_env(name: str) -> Path | None:
    import os

    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command for display only."""

    import shlex

    return shlex.join(command)


def _best_prediction(prediction: dict[str, float]) -> tuple[str, float]:
    if not prediction:
        return "", 0.0
    label, score = max(prediction.items(), key=lambda item: float(item[1]))
    return str(label), float(score)


def _normalize_prediction_label(label: str) -> str:
    return " ".join(label.casefold().replace("_", " ").replace("-", " ").split())


def _dependency_warning() -> str:
    missing = []
    try:
        import openwakeword  # noqa: F401
    except ModuleNotFoundError:
        missing.append("openwakeword")
    try:
        import sounddevice  # noqa: F401
    except ModuleNotFoundError:
        missing.append("sounddevice")
    if not missing:
        return "openwakeword and sounddevice are available."
    return f"Runtime dependency check: missing {', '.join(missing)}."
