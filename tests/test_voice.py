import subprocess
from pathlib import Path

from eclipse_agent.voice import (
    ListenOnce,
    LocalWhisperSTT,
    MicrophoneRecorder,
    SystemTTS,
    TTSProvider,
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
