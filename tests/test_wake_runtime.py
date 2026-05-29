from pathlib import Path

from eclipse_agent.notifications import NotificationFocusMode, NotificationStore
from eclipse_agent.planner import ActionKind
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import MCPToolDefinition, ToolRouter
from eclipse_agent.voice import (
    ListenResult,
    RecordingResult,
    TranscriptionResult,
    WakeWordDetectionResult,
)
from eclipse_agent.wake_runtime import (
    WakeRuntime,
    contains_wake_phrase,
    extract_command_after_wake,
    render_efficient_wake_loop_result,
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


class StubMCPClient:
    def discover_tools(self):
        return (
            MCPToolDefinition(
                name="open_url",
                server_name="browser",
                description="Open a browser URL.",
                action_kinds=(ActionKind.OPEN_WEB_APP,),
                risk_level=RiskLevel.LOW,
            ),
        )

    def call_tool(self, tool, arguments):
        raise AssertionError("Wake runtime tests should not execute MCP tools")


class StubWakeTrigger:
    def __init__(self, result: WakeWordDetectionResult) -> None:
        self.result = result
        self.calls = []

    def listen(self, *, timeout_seconds=None, dry_run=True):
        self.calls.append((timeout_seconds, dry_run))
        return self.result


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
        router=ToolRouter(mcp_client=StubMCPClient()),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
    )

    result = runtime.run_turn(audio_dir=tmp_path, dry_run=False)

    assert result.success is True
    assert result.woke is True
    assert result.command_listen is None
    assert result.command_result is not None
    assert result.command_result.kind == "route"
    assert result.command_result.route_results[0].tool_name == "browser.open_url"
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


def test_efficient_wake_turn_does_not_touch_stt_until_wake_word_detected(tmp_path):
    listener = StubListener("Abre Instagram en navegador")
    trigger = StubWakeTrigger(
        WakeWordDetectionResult(
            success=True,
            detected=False,
            provider="openwakeword",
            message="No wake word.",
            dry_run=False,
            executed=True,
        )
    )
    runtime = WakeRuntime(listener=listener, wake_trigger=trigger)

    result = runtime.run_efficient_turn(audio_dir=tmp_path, dry_run=False)

    assert result.success is True
    assert result.detected is False
    assert listener.calls == []
    assert trigger.calls == [(None, False)]


def test_efficient_wake_turn_records_command_after_detection(tmp_path):
    listener = StubListener("Abre Instagram en navegador")
    trigger = StubWakeTrigger(
        WakeWordDetectionResult(
            success=True,
            detected=True,
            provider="openwakeword",
            message="Wake word detected.",
            dry_run=False,
            executed=True,
            label="Eclipse",
            score=0.91,
        )
    )
    runtime = WakeRuntime(
        listener=listener,
        wake_trigger=trigger,
        router=ToolRouter(mcp_client=StubMCPClient()),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
    )

    result = runtime.run_efficient_turn(audio_dir=tmp_path, dry_run=False)

    assert result.success is True
    assert result.detected is True
    assert result.command_result is not None
    assert result.command_result.kind == "route"
    assert len(listener.calls) == 1
    rendered = render_efficient_wake_loop_result(
        type("EfficientLoop", (), {"success": True, "turns": (result,)})()
    )
    assert "Efficient wake turn [ok/detected]" in rendered
