from eclipse_agent.voice import (
    ListenOnce,
    LocalWhisperSTT,
    MicrophoneRecorder,
    OpenWakeWordTrigger,
    SystemTTS,
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


def test_system_tts_dry_run_delegates_to_sapi():
    result = SystemTTS().speak("Hola Eclipse", dry_run=True)

    assert result.success is True
    assert result.executed is False
    assert result.provider == "sapi"


def test_system_tts_execute_speaks_via_sapi(monkeypatch):
    calls = []

    class MockSpVoice:
        def Speak(self, text):
            calls.append(text)

    import sys as sys_module
    from unittest.mock import MagicMock

    mock_win32com = MagicMock()
    mock_win32com.client.Dispatch.return_value = MockSpVoice()
    monkeypatch.setitem(sys_module.modules, "win32com", mock_win32com)
    monkeypatch.setitem(sys_module.modules, "win32com.client", mock_win32com.client)

    result = SystemTTS().speak("Hola", dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert calls == ["Hola"]


def test_microphone_recorder_dry_run_prepares_recording(tmp_path):
    result = MicrophoneRecorder().record(tmp_path / "listen.wav", seconds=2, dry_run=True)

    assert result.success is True
    assert result.executed is False
    assert str(result.audio_path).endswith("listen.wav")


def test_microphone_recorder_execute_records_via_sounddevice(tmp_path, monkeypatch):
    import sys as sys_module
    from unittest.mock import MagicMock

    import numpy as np

    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.read.return_value = (np.zeros((1600, 1), dtype="int16"), False)

    mock_sd = MagicMock()
    mock_sd.InputStream.return_value = mock_stream
    mock_sf = MagicMock()

    monkeypatch.setitem(sys_module.modules, "sounddevice", mock_sd)
    monkeypatch.setitem(sys_module.modules, "soundfile", mock_sf)

    result = MicrophoneRecorder().record(tmp_path / "listen.wav", seconds=1, dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert mock_sd.InputStream.called
    assert mock_stream.read.called
    assert mock_sf.write.called



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


def test_windows_audio_recorder_vad_stops_early(tmp_path, monkeypatch):
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    from unittest.mock import MagicMock
    from eclipse_agent.pal.windows.voice import WindowsAudioRecorder

    rec = WindowsAudioRecorder()
    audio_file = tmp_path / "vad_test.wav"

    active_chunk = np.ones((1600, 1), dtype='int16') * 300
    silent_chunk = np.ones((1600, 1), dtype='int16') * 10
    
    chunk_index = 0
    def mock_read(size):
        nonlocal chunk_index
        if chunk_index < 5:
            res = (active_chunk, False)
        else:
            res = (silent_chunk, False)
        chunk_index += 1
        return res

    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.read.side_effect = mock_read

    mock_input_stream = MagicMock(return_value=mock_stream)
    monkeypatch.setattr(sd, "InputStream", mock_input_stream)

    mock_write = MagicMock()
    monkeypatch.setattr(sf, "write", mock_write)

    res = rec.record(audio_file, seconds=5, dry_run=False)

    assert res.success is True
    assert res.dry_run is False
    assert res.executed is True

    # 5 active chunks + 15 silent chunks = 20 chunks total before VAD trigger
    assert chunk_index == 20
    mock_write.assert_called_once()
    
    written_data = mock_write.call_args[0][1]
    assert len(written_data) == 20 * 1600

