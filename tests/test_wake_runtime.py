from pathlib import Path

from eclipse_agent.notifications import NotificationFocusMode, NotificationStore
from eclipse_agent.voice import ListenResult, RecordingResult, TranscriptionResult
from eclipse_agent.wake_runtime import (
    WakeRuntime,
    contains_wake_phrase,
    extract_command_after_wake,
    render_wake_loop_result,
)


class StubListener:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = []

    def run(self, *, seconds: int, audio_path: str | Path | None = None, dry_run: bool = True):
        self.calls.append((seconds, Path(audio_path) if audio_path else None, dry_run))
        text = self.texts.pop(0)
        path = Path(audio_path) if audio_path else Path("/tmp/eclipse-test.wav")
        recording = RecordingResult(
            success=True,
            command=("record", str(path)),
            audio_path=path,
            message="recorded",
            dry_run=dry_run,
            executed=not dry_run,
        )
        transcription = TranscriptionResult(
            success=True,
            text=text,
            audio_path=path,
            provider="stub",
            message="transcribed",
            segments=(text,),
        )
        return ListenResult(True, recording, transcription, "transcribed")


def test_contains_wake_phrase_matches_word_sequence_without_accents():
    assert contains_wake_phrase("Oye, Éclipse, dime qué llegó") is True
    assert contains_wake_phrase("eclipsed no debe despertar") is False


def test_extract_command_after_wake_normalizes_command_tail():
    assert extract_command_after_wake("Eclipse, dime qué llegó") == "dime que llego"


def test_handle_command_executes_notification_intent(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    runtime = WakeRuntime(store=store)

    result = runtime.handle_command("Eclipse, modo juego por una hora")

    assert result.success is True
    assert result.kind == "notification"
    assert store.get_runtime_state().mode is NotificationFocusMode.GAME


def test_wake_turn_routes_inline_command_without_recording_second_clip(tmp_path):
    runtime = WakeRuntime(
        listener=StubListener("Eclipse abre Instagram en navegador"),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
    )

    result = runtime.run_turn(audio_dir=tmp_path, dry_run=False)

    assert result.success is True
    assert result.woke is True
    assert result.command_listen is None
    assert result.command_result is not None
    assert result.command_result.kind == "route"
    assert result.command_result.route_results[0].tool_name == "browser_automation"
    rendered = render_wake_loop_result(type("Loop", (), {"success": True, "turns": (result,)})())
    assert "Wake command [ok] route" in rendered


def test_wake_turn_records_second_clip_when_only_wake_phrase_is_heard(tmp_path):
    runtime = WakeRuntime(
        listener=StubListener("Eclipse", "dime qué llegó"),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
    )

    result = runtime.run_turn(audio_dir=tmp_path, dry_run=False)

    assert result.success is True
    assert result.woke is True
    assert result.command_text == "dime qué llegó"
    assert result.command_listen is not None
    assert len(runtime.listener.calls) == 2
