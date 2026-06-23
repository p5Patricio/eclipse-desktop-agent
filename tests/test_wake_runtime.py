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


class CapturingTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str, *, dry_run: bool = True):
        self.spoken.append(text)
        from eclipse_agent.voice import SpeechResult

        return SpeechResult(
            success=True,
            provider="fake-tts",
            command=("speak", text),
            message="spoken",
            dry_run=dry_run,
            executed=not dry_run,
        )


def test_handle_command_speaks_formatted_route_success_not_router_summary(tmp_path):
    tts = CapturingTTS()
    runtime = WakeRuntime(
        router=ToolRouter(mcp_client=StubMCPClient()),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
        tts=tts,
    )

    result = runtime.handle_command("Eclipse, abre Instagram en navegador", speak=True)

    assert result.success is True
    assert tts.spoken == ["Listo, abrí Instagram."]
    assert result.message == "Listo, abrí Instagram."
    assert "Prepared 1 action(s)" not in tts.spoken[0]
    assert "browser.open_url" not in tts.spoken[0]


def test_handle_command_speaks_formatted_route_failure_not_raw_tool_error(tmp_path):
    tts = CapturingTTS()
    runtime = WakeRuntime(
        router=ToolRouter(mcp_client=FakeFailingMCPClient()),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
        tts=tts,
    )

    result = runtime.handle_command(
        "Eclipse, abre Instagram en navegador",
        speak=True,
        route_execute=True,
        confirmed=True,
    )

    assert result.success is False
    assert tts.spoken == ["No pude abrir Instagram: esa acción no está disponible todavía."]
    assert "Traceback" not in tts.spoken[0]
    assert "stderr" not in tts.spoken[0]


class FakeFailingMCPClient(StubMCPClient):
    def call_tool(self, tool, arguments):
        class RawResult:
            isError = True
            content = []

        return RawResult()


def test_handle_command_speaks_formatted_no_action_response(tmp_path):
    tts = CapturingTTS()
    runtime = WakeRuntime(
        router=ToolRouter(mcp_client=FakeNoToolsClient()),
        store=NotificationStore(tmp_path / "notifications.sqlite3"),
        tts=tts,
    )

    result = runtime.handle_command("Eclipse, haz magia", speak=True)

    assert result.success is False
    assert tts.spoken == [
        "No encontré una acción segura para eso. "
        "Pedime abrir una app, buscar algo o revisar notificaciones."
    ]
    assert "Listo" not in tts.spoken[0]


class FakeNoToolsClient:
    def discover_tools(self):
        return ()

    def call_tool(self, tool, arguments):
        raise AssertionError("No tool should be called")


def test_wake_runtime_status_http_api(tmp_path, monkeypatch):
    import urllib.request
    import json
    from http.server import HTTPServer
    import threading
    from eclipse_agent.wake_runtime import StatusHandler
    
    def real_start_server(self):
        handler = lambda *args, **kwargs: StatusHandler(*args, runtime=self, **kwargs)
        self._http_server = HTTPServer(("127.0.0.1", 11438), handler)
        self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        self._server_thread.start()
        
    monkeypatch.setattr(WakeRuntime, "_start_status_server", real_start_server)
    
    runtime = WakeRuntime(store=NotificationStore(tmp_path / "notifications.sqlite3"))
    try:
        assert runtime.status == "idle"
        
        response = urllib.request.urlopen("http://127.0.0.1:11438/status", timeout=2.0)
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data == {"status": "idle"}
        
        runtime.status = "listening"
        response = urllib.request.urlopen("http://127.0.0.1:11438/status", timeout=2.0)
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data == {"status": "listening"}
        
        runtime.status = "thinking"
        response = urllib.request.urlopen("http://127.0.0.1:11438/status", timeout=2.0)
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data == {"status": "thinking"}
    finally:
        runtime.stop_server()


def test_confirmation_loop_successful_confirm(tmp_path):
    from eclipse_agent.tool_router import ToolExecutionResult
    
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    runtime = WakeRuntime(store=store)
    
    calls = []
    def mock_route_plan(plan, context):
        calls.append(context)
        return (
            ToolExecutionResult(
                action_id="act-1",
                tool_name="test_tool",
                success=context.confirmed,
                executed=context.confirmed,
                requires_confirmation=not context.confirmed,
                message="requires confirmation" if not context.confirmed else "executed",
            ),
        )
        
    runtime.router.route_plan = mock_route_plan
    
    # Turn 1: Send a command requiring confirmation
    res1 = runtime.handle_command("haz algo riesgoso")
    assert res1.success is False
    assert runtime.pending_command == "haz algo riesgoso"
    assert len(calls) == 1
    assert calls[0].confirmed is False
    
    # Turn 2: Send confirmation
    res2 = runtime.handle_command("sí")
    assert res2.success is True
    assert runtime.pending_command is None
    assert len(calls) == 2
    assert calls[1].confirmed is True


def test_confirmation_loop_unrelated_command_clears_pending_to_none(tmp_path):
    from eclipse_agent.tool_router import ToolExecutionResult
    
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    runtime = WakeRuntime(store=store)
    
    results = [
        (
            ToolExecutionResult(
                action_id="act-1",
                tool_name="test_tool",
                success=False,
                executed=False,
                requires_confirmation=True,
                message="requires confirmation",
            ),
        ),
        (
            ToolExecutionResult(
                action_id="act-2",
                tool_name="test_tool2",
                success=True,
                executed=True,
                requires_confirmation=False,
                message="done",
            ),
        )
    ]
    
    def mock_route_plan(plan, context):
        return results.pop(0)
        
    runtime.router.route_plan = mock_route_plan
    
    # Turn 1: Requires confirmation
    runtime.handle_command("haz algo riesgoso")
    assert runtime.pending_command == "haz algo riesgoso"
    
    # Turn 2: Unrelated command, does not require confirmation
    runtime.handle_command("haz algo facil")
    assert runtime.pending_command is None


def test_confirmation_loop_confirm_without_pending(tmp_path):
    from eclipse_agent.tool_router import ToolExecutionResult
    
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    runtime = WakeRuntime(store=store)
    
    calls = []
    def mock_route_plan(plan, context):
        calls.append(plan.user_instruction)
        return (
            ToolExecutionResult(
                action_id="act-1",
                tool_name="test_tool",
                success=True,
                executed=True,
                requires_confirmation=False,
                message="handled",
            ),
        )
        
    runtime.router.route_plan = mock_route_plan
    
    # Send "yes" when pending_command is None
    res = runtime.handle_command("yes")
    assert res.success is True
    assert runtime.pending_command is None
    assert len(calls) == 1
    assert "yes" in calls[0].lower()



