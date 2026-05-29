"""Wake/listen/respond runtime loop for Eclipse."""

from __future__ import annotations

import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from eclipse_agent.notification_intents import (
    NotificationVoiceIntentKind,
    NotificationVoiceIntentResult,
    execute_notification_voice_intent,
    parse_notification_voice_intent,
)
from eclipse_agent.notifications import NotificationStore
from eclipse_agent.planner import create_action_plan
from eclipse_agent.tool_router import ToolExecutionContext, ToolExecutionResult, ToolRouter
from eclipse_agent.voice import ListenOnce, ListenResult, SpeechResult, SystemTTS


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
        tts: SystemTTS | None = None,
        router: ToolRouter | None = None,
        store: NotificationStore | None = None,
    ) -> None:
        self.listener = listener or ListenOnce()
        self.tts = tts or SystemTTS()
        self.router = router or ToolRouter()
        self.store = store or NotificationStore()

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

        base_dir = Path(audio_dir).expanduser() if audio_dir else Path(tempfile.gettempdir())
        wake_audio = base_dir / f"eclipse-wake-{turn_index}.wav"
        wake_listen = self.listener.run(
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
            command_audio = base_dir / f"eclipse-command-{turn_index}.wav"
            command_listen = self.listener.run(
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

        normalized_command = command_text.strip()
        if not normalized_command:
            return WakeCommandResult(
                success=False,
                kind="empty",
                command_text=command_text,
                message="No escuché un comando después de la frase de activación.",
            )

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
            executed_count = sum(1 for result in route_results if result.executed)
            message = (
                f"Preparé {len(route_results)} acción(es)."
                if executed_count == 0
                else f"Ejecuté {executed_count} de {len(route_results)} acción(es)."
            )
        else:
            blocked = tuple(result for result in route_results if result.requires_confirmation)
            message = (
                "Necesito confirmación o todavía no tengo una herramienta segura para eso."
                if blocked
                else "No pude preparar una acción segura para ese comando."
            )
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
        speech = self.tts.speak(result.message, dry_run=False)
        return WakeCommandResult(
            success=result.success and speech.success,
            kind=result.kind,
            command_text=result.command_text,
            message=result.message,
            notification_result=result.notification_result,
            route_results=result.route_results,
            speech_result=speech,
        )


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


def _listen_text(result: ListenResult) -> str:
    if not result.transcription:
        return ""
    return result.transcription.text.strip()


def _normalize_for_match(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    without_punctuation = re.sub(r"[^\w\s]+", " ", without_accents, flags=re.UNICODE)
    return " ".join(without_punctuation.split())
