import subprocess
from pathlib import Path

from eclipse_agent.voice import (
    ListenOnce,
    LocalWhisperSTT,
    MicrophoneRecorder,
    OpenWakeWordTrigger,
    SystemTTS,
    TTSProvider,
    default_wake_word_model_path,
    normalize_spoken_text,
)


def test_normalize_spoken_text_collapses_whitespace():
    assert normalize_spoken_text("  Hola   Eclipse  ") == "Hola Eclipse"


def test_normalize_spoken_text_rejects_empty_text():
    try:
        normalize_spoken_text("   ")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("Expected empty text to be rejected")


def test_system_tts_dry_run_prepares_command():
    tts = SystemTTS(TTSProvider.ESPEAK_NG)

    result = tts.speak("Hola Eclipse", dry_run=True)

    assert result.success is True
    assert result.executed is False
    assert result.command[-1] == "Hola Eclipse"


def test_system_tts_execute_uses_injected_runner():
    calls = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    tts = SystemTTS(TTSProvider.ESPEAK_NG, runner=runner)

    result = tts.speak("Hola", dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert calls


def test_microphone_recorder_dry_run_prepares_wav_command(tmp_path):
    recorder = MicrophoneRecorder()

    result = recorder.record(tmp_path / "listen.wav", seconds=2, dry_run=True)

    assert result.success is True
    assert result.executed is False
    assert str(result.audio_path).endswith("listen.wav")
    assert "16000" in result.command


def test_microphone_recorder_execute_uses_runner(tmp_path):
    calls = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        Path(command[-1]).write_bytes(b"fake wav")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    recorder = MicrophoneRecorder(runner=runner)

    result = recorder.record(tmp_path / "listen.wav", seconds=1, dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert calls


def test_local_whisper_status_reports_boolean():
    status = LocalWhisperSTT().status()

    assert isinstance(status.available, bool)
    assert status.provider == "faster-whisper"


def test_listen_once_dry_run_prepares_recording(tmp_path):
    result = ListenOnce().run(seconds=1, audio_path=tmp_path / "listen.wav", dry_run=True)

    assert result.success is True
    assert result.transcription is None
    assert result.recording.audio_path == tmp_path / "listen.wav"


class FakeWakeWordModel:
    def __init__(self, *scores: float, label: str = "eclipse") -> None:
        self.scores = list(scores)
        self.label = label

    def predict(self, frame: object) -> dict[str, float]:
        del frame
        score = self.scores.pop(0) if self.scores else 0.0
        return {self.label: score}


def test_openwakeword_trigger_dry_run_does_not_load_audio_stack():
    trigger = OpenWakeWordTrigger()

    result = trigger.listen(dry_run=True)

    assert result.success is True
    assert result.detected is False
    assert result.executed is False
    assert "Prepared openwakeword" in result.message


def test_openwakeword_trigger_defaults_to_custom_eclipse_model():
    trigger = OpenWakeWordTrigger()

    assert trigger.model_paths == ()
    assert trigger.builtin_model == "hey_jarvis"
    assert "hey_jarvis" in trigger.status().message


def test_openwakeword_trigger_prefers_valid_custom_model_and_keeps_builtin_fallback(tmp_path):
    custom_model = tmp_path / "eclipse.onnx"
    custom_model.write_bytes(b"fake onnx")

    trigger = OpenWakeWordTrigger(model_paths=(custom_model,))

    assert trigger.model_paths == (custom_model,)
    assert trigger.builtin_model == "hey_jarvis"
    assert "preferred custom" in trigger.status().message
    assert "fallback hey_jarvis" in trigger.status().message


def test_openwakeword_trigger_missing_custom_model_continues_with_visible_fallback(tmp_path):
    missing_model = tmp_path / "missing-eclipse.onnx"

    trigger = OpenWakeWordTrigger(model_paths=(missing_model,))
    status = trigger.status()

    assert status.available is True
    assert "missing" in status.message
    assert str(missing_model) in status.message
    assert "fallback hey_jarvis" in status.message


def test_openwakeword_trigger_invalid_custom_model_falls_back_to_builtin(tmp_path):
    custom_model = tmp_path / "eclipse.onnx"
    custom_model.write_bytes(b"invalid")
    calls = []

    def model_factory(*, wakeword_models: list[str], inference_framework: str):
        calls.append((wakeword_models, inference_framework))
        if wakeword_models == [str(custom_model)]:
            raise ValueError("invalid ONNX graph with internal loader detail")
        return FakeWakeWordModel(0.8, label="hey_jarvis")

    trigger = OpenWakeWordTrigger(
        model_paths=(custom_model,),
        model_factory=model_factory,
        frame_source=(object(),),
        threshold=0.5,
    )

    result = trigger.listen(dry_run=False)

    assert result.success is True
    assert result.detected is True
    assert result.label == "hey_jarvis"
    assert calls == [([str(custom_model)], "onnx"), (["hey_jarvis"], "onnx")]
    assert "custom wake-word model failed" in result.message
    assert "fallback hey_jarvis" in result.message


def test_openwakeword_trigger_detects_matching_wake_phrase():
    trigger = OpenWakeWordTrigger(
        model=FakeWakeWordModel(0.1, 0.8, label="Eclipse"),
        frame_source=(object(), object()),
        threshold=0.5,
    )

    result = trigger.listen(dry_run=False)

    assert result.success is True
    assert result.detected is True
    assert result.executed is True
    assert result.label == "Eclipse"
    assert result.score == 0.8


def test_openwakeword_trigger_ignores_unrelated_default_model_label():
    trigger = OpenWakeWordTrigger(
        model=FakeWakeWordModel(0.9, label="hey_jarvis"),
        frame_source=(object(),),
        threshold=0.5,
        builtin_model=None,
    )

    result = trigger.listen(dry_run=False)

    assert result.success is True
    assert result.detected is False
    assert result.score == 0.0
