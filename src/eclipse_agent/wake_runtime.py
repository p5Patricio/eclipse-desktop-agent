"""Wake/listen/respond runtime loop for Eclipse."""

from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from eclipse_agent.notification_intents import (
    NotificationVoiceIntentKind,
    NotificationVoiceIntentResult,
    execute_notification_voice_intent,
    parse_notification_voice_intent,
)
from eclipse_agent.notifications import NotificationStore
from eclipse_agent.planner import create_action_plan
from eclipse_agent.reminders import ReminderStore, fire_due_reminders
from eclipse_agent.routines import (
    RoutineStore,
    default_routine_answer,
    fire_due_routines,
)
from eclipse_agent.response_formatter import ActionResponseFormatter
from eclipse_agent.tool_router import (
    NativeMCPClient,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolRouter,
)
from eclipse_agent.voice import (
    ListenOnce,
    ListenResult,
    OpenWakeWordTrigger,
    SpeechResult,
    SystemTTS,
    WakeWordDetectionResult,
)


class StatusHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the status API."""

    def __init__(self, *args, runtime: WakeRuntime | None = None, **kwargs) -> None:
        self.runtime = runtime
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_val = self.runtime.status if self.runtime else "idle"
            response = {"status": status_val}
            self.wfile.write(json.dumps(response).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@dataclass(frozen=True, kw_only=True)
class WakeCommandResult:
    """Result of handling one transcribed command after the wake phrase."""

    success: bool
    kind: str
    command_text: str
    message: str
    notification_result: NotificationVoiceIntentResult | None = None
    route_results: tuple[ToolExecutionResult, ...] = ()
    speech_result: SpeechResult | None = None


@dataclass(frozen=True, kw_only=True)
class WakeTurnResult:
    """Result of one wake/listen/respond turn."""

    success: bool
    woke: bool
    wake_text: str
    wake_listen: ListenResult
    message: str
    command_text: str = ""
    command_listen: ListenResult | None = None
    command_result: WakeCommandResult | None = None


@dataclass(frozen=True, kw_only=True)
class WakeLoopResult:
    """Result of a bounded wake loop."""

    success: bool
    turns: tuple[WakeTurnResult, ...]


@dataclass(frozen=True, kw_only=True)
class EfficientWakeTurnResult:
    """Result of one openwakeword-triggered command turn."""

    success: bool
    detected: bool
    wake_word: WakeWordDetectionResult
    message: str
    command_text: str = ""
    command_listen: ListenResult | None = None
    command_result: WakeCommandResult | None = None


@dataclass(frozen=True, kw_only=True)
class EfficientWakeLoopResult:
    """Result of a bounded efficient wake loop."""

    success: bool
    turns: tuple[EfficientWakeTurnResult, ...]


class WakeRuntime:
    """Bounded always-on style wake loop.

    The current MVP uses local short-window STT to detect the wake phrase. This is
    intentionally conservative and testable: by default it only prepares recording
    commands; `--execute` is required before touching the microphone, and routed
    desktop/browser actions remain dry-run unless separately enabled.
    """

    def __init__(
        self,
        *,
        listener: ListenOnce | None = None,
        listener_factory: Callable[[], ListenOnce] | None = None,
        wake_trigger: OpenWakeWordTrigger | None = None,
        tts: SystemTTS | None = None,
        router: ToolRouter | None = None,
        store: NotificationStore | None = None,
        response_formatter: ActionResponseFormatter | None = None,
        reminder_store: ReminderStore | None = None,
        routine_store: RoutineStore | None = None,
    ) -> None:
        self.listener = listener
        self.listener_factory = listener_factory
        self.wake_trigger = wake_trigger or OpenWakeWordTrigger()
        self.tts = tts or SystemTTS()
        self.router = router or ToolRouter(mcp_client=NativeMCPClient())
        self.store = store or NotificationStore()
        self.response_formatter = response_formatter or ActionResponseFormatter()
        self.reminder_store = reminder_store
        self.routine_store = routine_store

        self.status = "idle"
        self.pending_command = None
        self._http_server = None
        self._server_thread = None
        self._reminder_thread = None
        self._reminder_stop = None
        self._routine_thread = None
        self._routine_stop = None
        try:
            self._start_status_server()
        except OSError:
            pass

    def _start_status_server(self) -> None:
        def handler(*args, **kwargs):
            return StatusHandler(*args, runtime=self, **kwargs)

        self._http_server = HTTPServer(("127.0.0.1", 11438), handler)
        self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
        self._server_thread.start()

    def stop_server(self) -> None:
        """Stop the HTTP status server if it is running."""
        if self._http_server:
            try:
                self._http_server.shutdown()
                self._http_server.server_close()
            except Exception:
                pass
            self._http_server = None
        if self._server_thread:
            try:
                self._server_thread.join(timeout=0.5)
            except Exception:
                pass
            self._server_thread = None

    def _poll_reminders_once(self, *, dry_run: bool) -> tuple:
        """Fire any due reminders once, speaking each. Returns the fired reminders."""
        if self.reminder_store is None:
            return ()
        return fire_due_reminders(
            self.reminder_store,
            lambda text: self.tts.speak(text, dry_run=dry_run),
        )

    def start_reminder_poller(self, *, dry_run: bool, interval: float = 20.0) -> None:
        """Start a background thread that speaks reminders as they come due."""
        if self.reminder_store is None:
            self.reminder_store = ReminderStore()
        self._reminder_stop = threading.Event()

        def loop() -> None:
            while not self._reminder_stop.wait(interval):
                try:
                    self._poll_reminders_once(dry_run=dry_run)
                except Exception:
                    pass

        self._reminder_thread = threading.Thread(target=loop, daemon=True)
        self._reminder_thread.start()

    def stop_reminder_poller(self) -> None:
        """Stop the reminder poller thread if it is running."""
        if self._reminder_stop is not None:
            self._reminder_stop.set()
        if self._reminder_thread is not None:
            try:
                self._reminder_thread.join(timeout=0.5)
            except Exception:
                pass
            self._reminder_thread = None

    def _poll_routines_once(self, *, dry_run: bool) -> tuple:
        """Fire any due routines once, speaking each. Returns the fired routines."""
        if self.routine_store is None:
            return ()
        return fire_due_routines(
            self.routine_store,
            lambda text: self.tts.speak(text, dry_run=dry_run),
            answer=default_routine_answer,
        )

    def start_routine_poller(self, *, dry_run: bool, interval: float = 20.0) -> None:
        """Start a background thread that runs routines as they come due."""
        if self.routine_store is None:
            self.routine_store = RoutineStore()
        self._routine_stop = threading.Event()

        def loop() -> None:
            while not self._routine_stop.wait(interval):
                try:
                    self._poll_routines_once(dry_run=dry_run)
                except Exception:
                    pass

        self._routine_thread = threading.Thread(target=loop, daemon=True)
        self._routine_thread.start()

    def stop_routine_poller(self) -> None:
        """Stop the routine poller thread if it is running."""
        if self._routine_stop is not None:
            self._routine_stop.set()
        if self._routine_thread is not None:
            try:
                self._routine_thread.join(timeout=0.5)
            except Exception:
                pass
            self._routine_thread = None


    def run(
        self,
        *,
        wake_phrase: str = "Eclipse",
        iterations: int = 1,
        wake_seconds: int = 2,
        command_seconds: int = 5,
        audio_dir: str | Path | None = None,
        dry_run: bool = True,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
        sleep_seconds: float = 0.0,
    ) -> WakeLoopResult:
        """Run a bounded wake loop.

        `iterations=0` runs forever; CLI callers should prefer a positive number
        for first real tests.
        """

        if iterations < 0:
            raise ValueError("iterations must be zero or positive.")
        turns: list[WakeTurnResult] = []
        index = 0
        while iterations == 0 or index < iterations:
            index += 1
            turns.append(
                self.run_turn(
                    wake_phrase=wake_phrase,
                    wake_seconds=wake_seconds,
                    command_seconds=command_seconds,
                    audio_dir=audio_dir,
                    turn_index=index,
                    dry_run=dry_run,
                    speak=speak,
                    route_execute=route_execute,
                    confirmed=confirmed,
                    mark_announced=mark_announced,
                )
            )
            if iterations == 0 and sleep_seconds > 0:
                time.sleep(sleep_seconds)
            elif index < iterations and sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return WakeLoopResult(success=all(turn.success for turn in turns), turns=tuple(turns))

    def run_efficient(
        self,
        *,
        iterations: int = 1,
        command_seconds: int = 5,
        audio_dir: str | Path | None = None,
        dry_run: bool = True,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
        wake_timeout_seconds: float | None = None,
        sleep_seconds: float = 0.0,
    ) -> EfficientWakeLoopResult:
        """Run an openwakeword loop that starts Whisper only after detection."""

        if iterations < 0:
            raise ValueError("iterations must be zero or positive.")
        turns: list[EfficientWakeTurnResult] = []
        index = 0
        while iterations == 0 or index < iterations:
            index += 1
            turns.append(
                self.run_efficient_turn(
                    command_seconds=command_seconds,
                    audio_dir=audio_dir,
                    turn_index=index,
                    dry_run=dry_run,
                    speak=speak,
                    route_execute=route_execute,
                    confirmed=confirmed,
                    mark_announced=mark_announced,
                    wake_timeout_seconds=wake_timeout_seconds,
                )
            )
            if iterations == 0 and sleep_seconds > 0:
                time.sleep(sleep_seconds)
            elif index < iterations and sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return EfficientWakeLoopResult(
            success=all(turn.success for turn in turns),
            turns=tuple(turns),
        )

    def run_efficient_turn(
        self,
        *,
        command_seconds: int = 5,
        audio_dir: str | Path | None = None,
        turn_index: int = 1,
        dry_run: bool = True,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
        wake_timeout_seconds: float | None = None,
    ) -> EfficientWakeTurnResult:
        """Wait on openwakeword, then record/transcribe one command chunk."""
        self.status = "listening"
        try:
            wake_word = self.wake_trigger.listen(
                timeout_seconds=wake_timeout_seconds,
                dry_run=dry_run,
            )
            if dry_run or not wake_word.detected:
                return EfficientWakeTurnResult(
                    success=wake_word.success,
                    detected=wake_word.detected,
                    wake_word=wake_word,
                    message=wake_word.message,
                )
            if not wake_word.success:
                return EfficientWakeTurnResult(
                    success=False,
                    detected=False,
                    wake_word=wake_word,
                    message=wake_word.message,
                )

            base_dir = Path(audio_dir).expanduser() if audio_dir else Path(tempfile.gettempdir())
            command_audio = base_dir / f"eclipse-efficient-command-{turn_index}.wav"
            listener = self._get_listener()
            self.status = "listening"
            command_listen = listener.run(
                seconds=command_seconds,
                audio_path=command_audio,
                dry_run=False,
            )
            if not command_listen.success:
                return EfficientWakeTurnResult(
                    success=False,
                    detected=True,
                    wake_word=wake_word,
                    command_listen=command_listen,
                    message=command_listen.message,
                )

            command_text = _listen_text(command_listen)
            command_result = self.handle_command(
                command_text,
                speak=speak,
                route_execute=route_execute,
                confirmed=confirmed,
                mark_announced=mark_announced,
            )
            return EfficientWakeTurnResult(
                success=command_result.success,
                detected=True,
                wake_word=wake_word,
                command_text=command_text,
                command_listen=command_listen,
                command_result=command_result,
                message=command_result.message,
            )
        finally:
            self.status = "idle"

    def run_turn(
        self,
        *,
        wake_phrase: str = "Eclipse",
        wake_seconds: int = 2,
        command_seconds: int = 5,
        audio_dir: str | Path | None = None,
        turn_index: int = 1,
        dry_run: bool = True,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
    ) -> WakeTurnResult:
        """Record/transcribe one wake window and handle a command when awakened."""
        self.status = "listening"
        try:
            base_dir = Path(audio_dir).expanduser() if audio_dir else Path(tempfile.gettempdir())
            wake_audio = base_dir / f"eclipse-wake-{turn_index}.wav"
            wake_listen = self._get_listener().run(
                seconds=wake_seconds,
                audio_path=wake_audio,
                dry_run=dry_run,
            )
            wake_text = _listen_text(wake_listen)

            if dry_run:
                return WakeTurnResult(
                    success=wake_listen.success,
                    woke=False,
                    wake_text=wake_text,
                    wake_listen=wake_listen,
                    message="Prepared wake listen window; use --execute for microphone/STT.",
                )

            if not wake_listen.success:
                return WakeTurnResult(
                    success=False,
                    woke=False,
                    wake_text=wake_text,
                    wake_listen=wake_listen,
                    message=wake_listen.message,
                )

            if not contains_wake_phrase(wake_text, wake_phrase):
                return WakeTurnResult(
                    success=True,
                    woke=False,
                    wake_text=wake_text,
                    wake_listen=wake_listen,
                    message=f"Wake phrase {wake_phrase!r} was not detected.",
                )

            command_text = extract_command_after_wake(wake_text, wake_phrase)
            command_listen: ListenResult | None = None
            if not command_text:
                self.status = "listening"
                command_audio = base_dir / f"eclipse-command-{turn_index}.wav"
                command_listen = self._get_listener().run(
                    seconds=command_seconds,
                    audio_path=command_audio,
                    dry_run=False,
                )
                if not command_listen.success:
                    return WakeTurnResult(
                        success=False,
                        woke=True,
                        wake_text=wake_text,
                        wake_listen=wake_listen,
                        command_listen=command_listen,
                        message=command_listen.message,
                    )
                command_text = _listen_text(command_listen)

            command_result = self.handle_command(
                command_text,
                speak=speak,
                route_execute=route_execute,
                confirmed=confirmed,
                mark_announced=mark_announced,
            )
            return WakeTurnResult(
                success=command_result.success,
                woke=True,
                wake_text=wake_text,
                wake_listen=wake_listen,
                command_text=command_text,
                command_listen=command_listen,
                command_result=command_result,
                message=command_result.message,
            )
        finally:
            self.status = "idle"

    def listen_and_handle(
        self,
        *,
        command_seconds: int = 5,
        audio_dir: str | Path | None = None,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
    ) -> WakeCommandResult:
        """Record one command (no wake word), transcribe it, and handle it.

        This is the push-to-talk path: a global hotkey triggers it directly.
        """
        base_dir = Path(audio_dir).expanduser() if audio_dir else Path(tempfile.gettempdir())
        self.status = "listening"
        listener = self._get_listener()
        command_listen = listener.run(
            seconds=command_seconds,
            audio_path=base_dir / "eclipse-ptt-command.wav",
            dry_run=False,
        )
        if not command_listen.success:
            self.status = "idle"
            return WakeCommandResult(
                success=False,
                kind="listen-failed",
                command_text="",
                message=command_listen.message,
            )
        result = self.handle_command(
            _listen_text(command_listen),
            speak=speak,
            route_execute=route_execute,
            confirmed=confirmed,
            mark_announced=mark_announced,
        )
        self.status = "idle"
        return result

    def handle_command(
        self,
        command_text: str,
        *,
        speak: bool = False,
        route_execute: bool = False,
        confirmed: bool = False,
        mark_announced: bool = False,
    ) -> WakeCommandResult:
        """Handle one already-transcribed command."""
        self.status = "thinking"

        normalized_command = command_text.strip()
        if not normalized_command:
            return WakeCommandResult(
                success=False,
                kind="empty",
                command_text=command_text,
                message="No command was heard after the wake phrase.",
            )

        clean_cmd = normalized_command.lower().rstrip(".,!?¿¡")
        if clean_cmd in ("sí", "yes", "confirmar", "dale", "ok", "claro") and self.pending_command is not None:
            cmd = self.pending_command
            self.pending_command = None
            return self.handle_command(
                cmd,
                speak=speak,
                route_execute=route_execute,
                confirmed=True,
                mark_announced=mark_announced,
            )

        self.pending_command = None

        notification_intent = parse_notification_voice_intent(normalized_command)
        if notification_intent.kind is not NotificationVoiceIntentKind.UNKNOWN:
            notification_result = execute_notification_voice_intent(
                notification_intent,
                store=self.store,
                mark_announced=mark_announced,
            )
            return self._with_optional_speech(
                WakeCommandResult(
                    success=notification_result.success,
                    kind="notification",
                    command_text=normalized_command,
                    message=notification_result.message,
                    notification_result=notification_result,
                ),
                speak=speak,
            )

        plan = create_action_plan(normalized_command)
        route_results = self.router.route_plan(
            plan,
            ToolExecutionContext(
                dry_run=not route_execute,
                confirmed=confirmed,
            ),
        )
        success = bool(route_results) and all(result.success for result in route_results)
        if success:
            message = self.response_formatter.format(
                command_text=normalized_command,
                route_results=route_results,
            )
        else:
            blocked = tuple(result for result in route_results if result.requires_confirmation)
            format_results = () if blocked else route_results
            message = self.response_formatter.format(
                command_text=normalized_command,
                route_results=format_results,
            )

        if route_results and any(result.requires_confirmation for result in route_results):
            self.pending_command = normalized_command

        return self._with_optional_speech(
            WakeCommandResult(
                success=success,
                kind="route",
                command_text=normalized_command,
                message=message,
                route_results=route_results,
            ),
            speak=speak,
        )

    def _with_optional_speech(
        self,
        result: WakeCommandResult,
        *,
        speak: bool,
    ) -> WakeCommandResult:
        if not speak:
            return result
        self.status = "speaking"
        try:
            speech = self.tts.speak(result.message, dry_run=False)
        finally:
            self.status = "thinking"
        return WakeCommandResult(
            success=result.success and speech.success,
            kind=result.kind,
            command_text=result.command_text,
            message=result.message,
            notification_result=result.notification_result,
            route_results=result.route_results,
            speech_result=speech,
        )

    def _get_listener(self) -> ListenOnce:
        if self.listener is None:
            self.listener = self.listener_factory() if self.listener_factory else ListenOnce()
        return self.listener


def contains_wake_phrase(text: str, wake_phrase: str = "Eclipse") -> bool:
    """Return whether text contains the configured wake phrase as a word sequence."""

    normalized_text = _normalize_for_match(text)
    normalized_wake = _normalize_for_match(wake_phrase)
    if not normalized_text or not normalized_wake:
        return False
    return re.search(rf"(^|\s){re.escape(normalized_wake)}($|\s)", normalized_text) is not None


def extract_command_after_wake(text: str, wake_phrase: str = "Eclipse") -> str:
    """Extract the words after the wake phrase from a transcribed utterance."""

    normalized_text = _normalize_for_match(text)
    normalized_wake = _normalize_for_match(wake_phrase)
    if not normalized_text or not normalized_wake:
        return ""
    match = re.search(rf"(^|\s){re.escape(normalized_wake)}($|\s)(?P<rest>.*)", normalized_text)
    if not match:
        return ""
    return match.group("rest").strip()


def render_wake_command_result(result: WakeCommandResult) -> str:
    """Render command handling output for CLI."""

    status = "ok" if result.success else "blocked"
    lines = [f"Wake command [{status}] {result.kind}: {result.message}"]
    lines.append(f"command: {result.command_text}")
    if result.route_results:
        lines.append("Routed actions:")
        for route in result.route_results:
            route_status = "executed" if route.executed else "prepared"
            if not route.success:
                route_status = "blocked" if route.requires_confirmation else "failed"
            lines.append(f"- {route.action_id} [{route_status}] {route.tool_name}: {route.message}")
    if result.speech_result:
        speech_status = "executed" if result.speech_result.executed else "prepared"
        if not result.speech_result.success:
            speech_status = "failed"
        lines.append(
            f"TTS [{speech_status}] {result.speech_result.provider}: "
            f"{result.speech_result.message}"
        )
    return "\n".join(lines)


def render_wake_turn_result(result: WakeTurnResult) -> str:
    """Render one wake-loop turn for CLI."""

    status = "ok" if result.success else "failed"
    woke = "woke" if result.woke else "idle"
    lines = [f"Wake turn [{status}/{woke}]: {result.message}"]
    if result.wake_text:
        lines.append(f"wake_text: {result.wake_text}")
    lines.append(f"wake_audio: {result.wake_listen.recording.audio_path}")
    if result.command_listen:
        lines.append(f"command_audio: {result.command_listen.recording.audio_path}")
    if result.command_result:
        lines.append(render_wake_command_result(result.command_result))
    return "\n".join(lines)


def render_wake_loop_result(result: WakeLoopResult) -> str:
    """Render a bounded wake loop result."""

    status = "ok" if result.success else "failed"
    lines = [f"Eclipse wake loop [{status}] turns={len(result.turns)}"]
    for index, turn in enumerate(result.turns, start=1):
        lines.append(f"\nTurn {index}:")
        lines.append(render_wake_turn_result(turn))
    return "\n".join(lines)


def render_efficient_wake_turn_result(result: EfficientWakeTurnResult) -> str:
    """Render one efficient wake-loop turn for CLI."""

    status = "ok" if result.success else "failed"
    detected = "detected" if result.detected else "idle"
    lines = [f"Efficient wake turn [{status}/{detected}]: {result.message}"]
    lines.append(f"wake_provider: {result.wake_word.provider}")
    if result.wake_word.label or result.wake_word.score:
        lines.append(f"wake_label: {result.wake_word.label or '<unknown>'}")
        lines.append(f"wake_score: {result.wake_word.score:.3f}")
    if result.command_listen:
        lines.append(f"command_audio: {result.command_listen.recording.audio_path}")
    if result.command_text:
        lines.append(f"command_text: {result.command_text}")
    if result.command_result:
        lines.append(render_wake_command_result(result.command_result))
    return "\n".join(lines)


def render_efficient_wake_loop_result(result: EfficientWakeLoopResult) -> str:
    """Render a bounded efficient wake loop result."""

    status = "ok" if result.success else "failed"
    lines = [f"Eclipse efficient wake loop [{status}] turns={len(result.turns)}"]
    for index, turn in enumerate(result.turns, start=1):
        lines.append(f"\nTurn {index}:")
        lines.append(render_efficient_wake_turn_result(turn))
    return "\n".join(lines)


def _listen_text(result: ListenResult) -> str:
    if not result.transcription:
        return ""
    return result.transcription.text.strip()


def _normalize_for_match(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_punctuation = re.sub(r"[^\w\s]+", " ", without_accents, flags=re.UNICODE)
    return " ".join(without_punctuation.split())
