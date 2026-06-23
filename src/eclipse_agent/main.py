"""Minimal CLI entrypoint for Eclipse."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from eclipse_agent import __version__
from eclipse_agent.activation import ActivationMode, build_activation_policy
from eclipse_agent.agent_smoke import (
    build_agent_smoke_plan,
    render_agent_smoke_plan,
    render_agent_smoke_simulation,
    run_agent_smoke_simulation,
)
from eclipse_agent.browser_automation import (
    BrowserActionStatus,
    BrowserCommandKind,
    BrowserInteractionLoop,
    render_browser_interaction_plan,
)
from eclipse_agent.coding_agents import build_coding_agent_prompt, get_coding_agent
from eclipse_agent.config import EclipseConfig
from eclipse_agent.desktop_control import (
    DesktopControlAction,
    DesktopControlResult,
    render_desktop_control_result,
)
from eclipse_agent.pal.factory import PlatformFactory
from eclipse_agent.notification_intents import (
    execute_notification_voice_intent,
    parse_notification_voice_intent,
    render_notification_voice_intent_result,
)
from eclipse_agent.notification_replies import (
    NotificationReplyWorkflow,
    render_notification_reply_draft_result,
    resolve_reply_text,
)
from eclipse_agent.notifications import (
    NotificationAction,
    NotificationCenter,
    NotificationFocusMode,
    NotificationRule,
    NotificationStatus,
    NotificationStore,
    NotificationUrgency,
    build_notification_digest,
    create_notification_event,
    expires_after_minutes,
    render_notification_events,
    render_notification_processing_result,
)
from eclipse_agent.planner import (
    LLMPlannerConfig,
    build_planner_config_from_env,
    create_action_plan,
)
from eclipse_agent.resources import estimate_resource_profile
from eclipse_agent.runtime_diagnostics import collect_runtime_diagnostics
from eclipse_agent.telemetry import ExecutionTelemetryStore, render_telemetry_summary
from eclipse_agent.tool_router import ToolExecutionContext, ToolRouter, render_tool_results
from eclipse_agent.voice import ListenOnce, LocalWhisperSTT, OpenWakeWordTrigger, SystemTTS
from eclipse_agent.voice import render_listen_result, render_speech_result
from eclipse_agent.wake_runtime import (
    WakeRuntime,
    render_efficient_wake_loop_result,
    render_wake_command_result,
    render_wake_loop_result,
)

RUNTIME_MODES = ("observe", "draft", "copilot", "autonomous")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eclipse-agent",
        description="Eclipse Desktop Agent CLI skeleton.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--mode",
        choices=RUNTIME_MODES,
        default="draft",
        help="Runtime mode. MVP should use observe/draft/copilot only.",
    )
    parser.add_argument(
        "--activation-mode",
        choices=[mode.value for mode in ActivationMode],
        default=ActivationMode.WAKE_WORD.value,
        help="How Eclipse listens while its daemon is active.",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show the planned runtime policy.")
    subparsers.add_parser("resource-plan", help="Show planning-level resource estimates.")
    subparsers.add_parser("diagnostics", help="Show local runtime capability status.")

    smoke_plan = subparsers.add_parser(
        "smoke-plan",
        help="Show the manual checklist to test Eclipse as an agent.",
    )
    smoke_plan.add_argument("--store", help="Optional notification store path for commands.")

    smoke_simulate = subparsers.add_parser(
        "smoke-simulate",
        help="Run a dependency-free simulated notification/reply smoke flow.",
    )
    smoke_simulate.add_argument(
        "--store",
        help="SQLite store path. Defaults to a temp smoke database.",
    )

    say = subparsers.add_parser("say", help="Speak text using local TTS.")
    say.add_argument("--text", required=True, help="Text Eclipse should speak.")
    say.add_argument(
        "--execute",
        action="store_true",
        help="Actually speak instead of dry-running.",
    )

    subparsers.add_parser("listen-status", help="Show local STT readiness.")

    listen = subparsers.add_parser("listen", help="Record once and transcribe locally.")
    listen.add_argument(
        "--seconds",
        type=int,
        default=5,
        help="Seconds to record.",
    )
    listen.add_argument("--audio-path", help="Optional WAV output path.")
    listen.add_argument("--model", default="small", help="faster-whisper model name/path.")
    listen.add_argument("--language", default="es", help="Transcription language code.")
    listen.add_argument(
        "--execute",
        action="store_true",
        help="Actually record and transcribe instead of dry-running.",
    )

    transcribe = subparsers.add_parser("transcribe-file", help="Transcribe a WAV/audio file.")
    transcribe.add_argument("--audio-path", required=True, help="Audio file to transcribe.")
    transcribe.add_argument("--model", default="small", help="faster-whisper model name/path.")
    transcribe.add_argument("--language", default="es", help="Transcription language code.")

    wake_command = subparsers.add_parser(
        "wake-command",
        help="Handle an already-transcribed wake command through Eclipse runtime routing.",
    )
    _add_notification_store_arg(wake_command)
    wake_command.add_argument("--text", required=True, help="Transcribed command text.")
    wake_command.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak Eclipse's response with local TTS.",
    )
    wake_command.add_argument(
        "--route-execute",
        action="store_true",
        help="Actually execute low-risk routed desktop/browser actions.",
    )
    wake_command.add_argument(
        "--confirmed",
        action="store_true",
        help="Treat medium-risk routed actions as user-confirmed.",
    )
    wake_command.add_argument(
        "--mark-announced",
        action="store_true",
        help="When summarizing notifications, mark pending items as announced.",
    )

    wake_loop = subparsers.add_parser(
        "wake-loop",
        help="Run a bounded wake/listen/respond loop. Dry-run by default.",
    )
    _add_notification_store_arg(wake_loop)
    wake_loop.add_argument("--wake-phrase", default="Eclipse", help="Wake phrase to detect.")
    wake_loop.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Wake windows to process. Use 0 only for an unbounded daemon test.",
    )
    wake_loop.add_argument("--wake-seconds", type=int, default=2, help="Wake clip length.")
    wake_loop.add_argument(
        "--command-seconds",
        type=int,
        default=5,
        help="Command clip length when the wake clip only contains the wake phrase.",
    )
    wake_loop.add_argument("--audio-dir", help="Directory for temporary wake/command WAV files.")
    wake_loop.add_argument("--model", default="small", help="faster-whisper model name/path.")
    wake_loop.add_argument("--language", default="es", help="Transcription language code.")
    wake_loop.add_argument(
        "--execute",
        action="store_true",
        help="Actually record/transcribe microphone audio instead of dry-running.",
    )
    wake_loop.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak Eclipse's response with local TTS.",
    )
    wake_loop.add_argument(
        "--route-execute",
        action="store_true",
        help="Actually execute low-risk routed desktop/browser actions.",
    )
    wake_loop.add_argument(
        "--confirmed",
        action="store_true",
        help="Treat medium-risk routed actions as user-confirmed.",
    )
    wake_loop.add_argument(
        "--mark-announced",
        action="store_true",
        help="When summarizing notifications, mark pending items as announced.",
    )

    wake_efficient = subparsers.add_parser(
        "wake-efficient",
        help="Run an openwakeword daemon that starts Whisper only after the wake phrase.",
    )
    _add_notification_store_arg(wake_efficient)
    wake_efficient.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Wake detections to process. Use 0 only for an unbounded daemon test.",
    )
    wake_efficient.add_argument(
        "--wake-timeout-seconds",
        type=float,
        help="Optional timeout for each openwakeword wait.",
    )
    wake_efficient.add_argument(
        "--wake-threshold",
        type=float,
        default=0.5,
        help="openwakeword confidence threshold.",
    )
    wake_efficient.add_argument(
        "--wakeword-model",
        action="append",
        default=[],
        help="Custom openwakeword model path for the Eclipse phrase. Can be repeated.",
    )
    wake_efficient.add_argument(
        "--builtin-wakeword",
        default="hey_jarvis",
        help=(
            "Built-in openwakeword fallback model. Set to an empty string only when "
            "you intentionally want no builtin fallback."
        ),
    )
    wake_efficient.add_argument(
        "--command-seconds",
        type=int,
        default=5,
        help="Command clip length after the wake phrase is detected.",
    )
    wake_efficient.add_argument("--audio-dir", help="Directory for temporary command WAV files.")
    wake_efficient.add_argument("--model", default="small", help="faster-whisper model name/path.")
    wake_efficient.add_argument("--language", default="es", help="Transcription language code.")
    wake_efficient.add_argument(
        "--execute",
        action="store_true",
        help="Actually monitor the microphone and transcribe commands.",
    )
    wake_efficient.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak Eclipse's response with local TTS.",
    )
    wake_efficient.add_argument(
        "--route-execute",
        action="store_true",
        help="Actually execute low-risk routed desktop/browser actions.",
    )
    wake_efficient.add_argument(
        "--confirmed",
        action="store_true",
        help="Treat confirmation-gated routed actions as user-confirmed.",
    )
    wake_efficient.add_argument(
        "--mark-announced",
        action="store_true",
        help="When summarizing notifications, mark pending items as announced.",
    )

    open_app = subparsers.add_parser(
        "open-app",
        help="Prepare or execute a Windows app launch.",
    )
    open_app.add_argument("--app", required=True, help="Application name.")
    open_app.add_argument(
        "--execute",
        action="store_true",
        help="Actually launch the app instead of dry-running.",
    )

    subparsers.add_parser("list-windows", help="List open windows.")

    screenshot = subparsers.add_parser(
        "screenshot",
        help="Capture a screenshot. Dry-run by default.",
    )
    screenshot.add_argument("--output", help="Optional output PNG path.")
    screenshot.add_argument(
        "--geometry",
        help='Optional capture geometry, for example "10,20,800,600".',
    )
    screenshot.add_argument(
        "--select-region",
        action="store_true",
        help="Select a region before capturing.",
    )
    screenshot.add_argument(
        "--execute",
        action="store_true",
        help="Actually capture the screenshot instead of dry-running.",
    )

    type_text = subparsers.add_parser(
        "type-text",
        help="Type text into the focused window. Requires --confirmed even in dry-run.",
    )
    type_text.add_argument("--text", required=True, help="Text to type into the focused surface.")
    type_text.add_argument(
        "--confirmed",
        action="store_true",
        help="Required before Eclipse can simulate native input.",
    )
    type_text.add_argument(
        "--execute",
        action="store_true",
        help="Actually type the text instead of preparing the command.",
    )

    notifications_ingest = subparsers.add_parser(
        "notifications-ingest",
        help="Ingest one native/web notification through focus rules.",
    )
    _add_notification_store_arg(notifications_ingest)
    notifications_ingest.add_argument("--app", required=True, help="App reported by D-Bus.")
    notifications_ingest.add_argument(
        "--summary",
        required=True,
        help="Notification summary/title.",
    )
    notifications_ingest.add_argument("--body", default="", help="Notification body.")
    notifications_ingest.add_argument("--desktop-entry", help="Optional desktop entry id.")
    notifications_ingest.add_argument("--source-window", help="Optional source window/page title.")
    notifications_ingest.add_argument(
        "--urgency",
        choices=[urgency.value for urgency in NotificationUrgency],
        default=NotificationUrgency.NORMAL.value,
        help="Notification urgency.",
    )
    notifications_ingest.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak announcements. Without this, TTS is dry-run.",
    )
    notifications_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview decision without storing the notification.",
    )

    notifications_mode = subparsers.add_parser(
        "notifications-mode",
        help="Set Eclipse notification interruption mode.",
    )
    _add_notification_store_arg(notifications_mode)
    notifications_mode.add_argument(
        "--mode",
        required=True,
        choices=[mode.value for mode in NotificationFocusMode],
        help="normal, focus, game, or private.",
    )
    notifications_mode.add_argument(
        "--minutes",
        type=int,
        help="Optional duration before returning to normal mode.",
    )

    notifications_mute = subparsers.add_parser(
        "notifications-mute",
        help="Add a temporary/permanent rule for apps or web sources.",
    )
    _add_notification_store_arg(notifications_mute)
    notifications_mute.add_argument(
        "--app",
        action="append",
        required=True,
        help="App/source pattern to match. Can be repeated.",
    )
    notifications_mute.add_argument(
        "--action",
        choices=[action.value for action in NotificationAction],
        default=NotificationAction.QUEUE.value,
        help="Rule action. Default queues notifications for later summary.",
    )
    notifications_mute.add_argument(
        "--mode",
        default="any",
        help="Mode where the rule applies: any, normal, focus, game, or private.",
    )
    notifications_mute.add_argument(
        "--minutes",
        type=int,
        help="Optional rule duration.",
    )

    notifications_summary = subparsers.add_parser(
        "notifications-summary",
        help="Summarize queued/new notifications.",
    )
    _add_notification_store_arg(notifications_summary)
    notifications_summary.add_argument("--limit", type=int, default=10, help="Max items to read.")
    notifications_summary.add_argument(
        "--mark-announced",
        action="store_true",
        help="Mark summarized queued/new notifications as announced.",
    )

    notifications_list = subparsers.add_parser(
        "notifications-list",
        help="List stored notifications for review/debugging.",
    )
    _add_notification_store_arg(notifications_list)
    notifications_list.add_argument(
        "--status",
        choices=_notification_status_choices(),
        default="all",
        help="Filter by status, or all.",
    )
    notifications_list.add_argument("--limit", type=int, default=20, help="Max items to list.")

    notifications_clear = subparsers.add_parser(
        "notifications-clear",
        help="Delete stored notification events. Requires --confirmed.",
    )
    _add_notification_store_arg(notifications_clear)
    notifications_clear.add_argument(
        "--status",
        choices=_notification_status_choices(),
        default=NotificationStatus.ANNOUNCED.value,
        help="Delete events by status, or all.",
    )
    notifications_clear.add_argument(
        "--confirmed",
        action="store_true",
        help="Required to delete notification memory.",
    )

    notifications_mark = subparsers.add_parser(
        "notifications-mark",
        help="Mark one notification with a new lifecycle status.",
    )
    _add_notification_store_arg(notifications_mark)
    notifications_mark.add_argument("--event-id", required=True, help="Notification id.")
    notifications_mark.add_argument(
        "--status",
        required=True,
        choices=[status.value for status in NotificationStatus],
        help="New notification status.",
    )
    notifications_mark.add_argument(
        "--confirmed",
        action="store_true",
        help="Required for replied/dismissed status changes.",
    )

    notifications_listen = subparsers.add_parser(
        "notifications-listen",
        help="Run or prepare the live D-Bus notification listener.",
    )
    _add_notification_store_arg(notifications_listen)
    notifications_listen.add_argument(
        "--seconds",
        type=int,
        default=30,
        help="Bound execute mode with GNU timeout. Use 0 for unbounded.",
    )
    notifications_listen.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak announcements when rules allow it.",
    )
    notifications_listen.add_argument(
        "--execute",
        action="store_true",
        help="Actually run the notification listener instead of dry-running.",
    )

    notifications_intent = subparsers.add_parser(
        "notifications-intent",
        help="Parse and execute a spoken notification command.",
    )
    _add_notification_store_arg(notifications_intent)
    notifications_intent.add_argument("--text", required=True, help="Transcribed voice command.")
    notifications_intent.add_argument(
        "--mark-announced",
        action="store_true",
        help="When summarizing, mark pending notifications as announced.",
    )

    notifications_reply = subparsers.add_parser(
        "notifications-reply-draft",
        help="Prepare a safe browser draft reply for a stored notification.",
    )
    _add_notification_store_arg(notifications_reply)
    notifications_reply.add_argument("--event-id", required=True, help="Notification id.")
    notifications_reply.add_argument(
        "--message",
        help="Reply draft text. If omitted, use --audio-path for local STT.",
    )
    notifications_reply.add_argument(
        "--audio-path",
        help="Optional local audio file to transcribe as reply text.",
    )
    notifications_reply.add_argument(
        "--record-seconds",
        type=int,
        help="Record microphone audio and transcribe it as reply text.",
    )
    notifications_reply.add_argument(
        "--record-audio-path",
        help="Optional WAV path for --record-seconds.",
    )
    notifications_reply.add_argument("--model", default="small", help="faster-whisper model.")
    notifications_reply.add_argument("--language", default="es", help="STT language code.")
    notifications_reply.add_argument(
        "--selector",
        help="Optional agent-browser snapshot ref for the message input, e.g. @e12.",
    )
    notifications_reply.add_argument(
        "--snapshot-json",
        help="Optional agent-browser snapshot JSON file for automatic ref selection.",
    )
    notifications_reply.add_argument(
        "--auto-select",
        action="store_true",
        help="Choose the most plausible message input ref from --snapshot-json.",
    )
    notifications_reply.add_argument(
        "--confirmed",
        action="store_true",
        help="Required before filling a browser draft field.",
    )
    notifications_reply.add_argument(
        "--execute",
        action="store_true",
        help="Actually run agent-browser instead of dry-running.",
    )

    plan = subparsers.add_parser(
        "plan",
        help="Decompose a natural-language instruction into tool-level actions.",
    )
    plan.add_argument("--instruction", required=True, help="Instruction to decompose.")
    _add_planner_args(plan)

    route_plan = subparsers.add_parser(
        "route-plan",
        help="Route a natural-language instruction to local tools. Dry-run by default.",
    )
    route_plan.add_argument("--instruction", required=True, help="Instruction to route.")
    _add_planner_args(route_plan)
    route_plan.add_argument(
        "--execute",
        action="store_true",
        help="Actually launch low-risk tools instead of dry-running.",
    )
    route_plan.add_argument(
        "--confirmed",
        action="store_true",
        help="Mark medium-risk actions as confirmed for this run.",
    )

    telemetry_report = subparsers.add_parser(
        "telemetry-report",
        help="Show planning layer usage metrics.",
    )
    telemetry_report.add_argument(
        "--days",
        type=int,
        default=5,
        help="Number of days to include in the report.",
    )
    telemetry_report.add_argument(
        "--telemetry-store",
        help="Optional SQLite telemetry store path.",
    )

    browser_snapshot = subparsers.add_parser(
        "browser-snapshot",
        help="Prepare agent-browser open + interactive snapshot workflow.",
    )
    browser_snapshot.add_argument("--url", required=True, help="URL to open and snapshot.")
    browser_snapshot.add_argument(
        "--execute",
        action="store_true",
        help="Actually run agent-browser if installed.",
    )

    browser_action = subparsers.add_parser(
        "browser-action",
        help="Prepare a confirmed browser ref action from the latest snapshot.",
    )
    browser_action.add_argument(
        "--kind",
        required=True,
        choices=[
            BrowserCommandKind.CLICK.value,
            BrowserCommandKind.FILL.value,
            BrowserCommandKind.TYPE.value,
            BrowserCommandKind.PRESS.value,
        ],
        help="Browser action to prepare.",
    )
    browser_action.add_argument("--selector", help="Snapshot ref, e.g. @e1.")
    browser_action.add_argument("--text", help="Text for fill/type actions.")
    browser_action.add_argument("--key", help="Key for press actions, e.g. Enter.")
    browser_action.add_argument(
        "--confirmed",
        action="store_true",
        help="Required for active browser interactions.",
    )
    browser_action.add_argument(
        "--execute",
        action="store_true",
        help="Actually run agent-browser if installed.",
    )

    coding_prompt = subparsers.add_parser(
        "coding-prompt",
        help="Generate the structured prompt Eclipse will give a coding agent.",
    )
    coding_prompt.add_argument(
        "--agent",
        required=True,
        help="Claude Code, Gemini CLI, or Codex CLI.",
    )
    coding_prompt.add_argument(
        "--project",
        required=True,
        help="Project path to open in the agent.",
    )
    coding_prompt.add_argument("--idea", required=True, help="User idea/request to hand off.")
    coding_prompt.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Optional constraint to include. Can be repeated.",
    )

    return parser


def _add_notification_store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        help="Optional SQLite notification store path. Defaults to the LOCALAPPDATA folder.",
    )


def _add_planner_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--planner-endpoint",
        default=None,
        help="OpenAI-compatible local LLM base URL. Defaults to Ollama on localhost.",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="Local LLM model name. Defaults to qwen2.5:7b.",
    )
    parser.add_argument(
        "--planner-api-key",
        help="Planner API key. Prefer --planner-api-key-env for shell history safety.",
    )
    parser.add_argument(
        "--planner-api-key-env",
        default="ECLIPSE_LLM_API_KEY",
        help="Environment variable containing the planner API key.",
    )
    parser.add_argument(
        "--disable-smart-layer",
        action="store_true",
        help="Disable local LLM fallback and use only deterministic planning.",
    )
    parser.add_argument(
        "--telemetry-store",
        help="Optional SQLite telemetry store path.",
    )
    parser.add_argument(
        "--mcp-config",
        help="Optional JSON file containing local STDIO MCP server definitions.",
    )


def _notification_status_choices() -> tuple[str, ...]:
    return ("all", *(status.value for status in NotificationStatus))


def _notification_store(args: argparse.Namespace) -> NotificationStore:
    return NotificationStore(args.store) if args.store else NotificationStore()


def _notification_status_filter(status: str) -> tuple[NotificationStatus, ...] | None:
    if status == "all":
        return None
    return (NotificationStatus(status),)


def _read_optional_text_file(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).expanduser().read_text(encoding="utf-8")


def _build_config(args: argparse.Namespace) -> EclipseConfig:
    return EclipseConfig(
        default_mode=args.mode,
        activation_mode=ActivationMode(args.activation_mode),
    )


def _print_status(config: EclipseConfig) -> None:
    policy = build_activation_policy(config.activation_mode)
    print(f"Eclipse initialized in {config.default_mode!r} mode.")
    print(f"Activation mode: {config.activation_mode.value}")
    print(f"Always-on daemon: {policy.always_on_daemon}")
    wake_phrase = policy.wake_phrase if policy.requires_explicit_wake_phrase else "not required"
    print(f"Wake phrase: {wake_phrase}")
    print(f"Continuous transcription: {policy.records_continuously}")
    print("Next milestone: always-on daemon + local wake word + spoken response.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _build_config(args)

    if args.command == "resource-plan":
        print(estimate_resource_profile(config.activation_mode).render())
        return 0

    if args.command == "diagnostics":
        print(collect_runtime_diagnostics().render())
        return 0

    if args.command == "smoke-plan":
        print(render_agent_smoke_plan(build_agent_smoke_plan(store_path=args.store)))
        return 0

    if args.command == "smoke-simulate":
        store = args.store or str(Path(tempfile.gettempdir()) / "eclipse-smoke.sqlite3")
        result = run_agent_smoke_simulation(store_path=store)
        print(render_agent_smoke_simulation(result))
        return 0 if result.success else 1

    if args.command == "say":
        print(render_speech_result(SystemTTS().speak(args.text, dry_run=not args.execute)))
        return 0

    if args.command == "listen-status":
        status = LocalWhisperSTT().status()
        marker = "ready" if status.available else "missing"
        print(f"STT [{marker}] {status.provider}: {status.message}")
        return 0

    if args.command == "listen":
        result = ListenOnce(stt=LocalWhisperSTT(model_name=args.model, language=args.language)).run(
            seconds=args.seconds,
            audio_path=args.audio_path,
            dry_run=not args.execute,
        )
        print(render_listen_result(result))
        return 0

    if args.command == "transcribe-file":
        result = LocalWhisperSTT(
            model_name=args.model,
            language=args.language,
        ).transcribe_file(args.audio_path)
        marker = "ok" if result.success else "failed"
        print(f"STT [{marker}] {result.provider}: {result.message}")
        print(f"text: {result.text}")
        return 0

    if args.command == "wake-command":
        result = WakeRuntime(store=_notification_store(args)).handle_command(
            args.text,
            speak=args.speak,
            route_execute=args.route_execute,
            confirmed=args.confirmed,
            mark_announced=args.mark_announced,
        )
        print(render_wake_command_result(result))
        return 0 if result.success else 1

    if args.command == "wake-loop":
        runtime = WakeRuntime(
            listener=ListenOnce(
                stt=LocalWhisperSTT(model_name=args.model, language=args.language),
            ),
            store=_notification_store(args),
        )
        result = runtime.run(
            wake_phrase=args.wake_phrase,
            iterations=args.iterations,
            wake_seconds=args.wake_seconds,
            command_seconds=args.command_seconds,
            audio_dir=args.audio_dir,
            dry_run=not args.execute,
            speak=args.speak,
            route_execute=args.route_execute,
            confirmed=args.confirmed,
            mark_announced=args.mark_announced,
        )
        print(render_wake_loop_result(result))
        return 0 if result.success else 1

    if args.command == "wake-efficient":
        runtime = WakeRuntime(
            listener_factory=lambda: ListenOnce(
                stt=LocalWhisperSTT(model_name=args.model, language=args.language),
            ),
            wake_trigger=OpenWakeWordTrigger(
                model_paths=tuple(args.wakeword_model),
                builtin_model=args.builtin_wakeword or None,
                threshold=args.wake_threshold,
            ),
            store=_notification_store(args),
        )
        result = runtime.run_efficient(
            iterations=args.iterations,
            command_seconds=args.command_seconds,
            audio_dir=args.audio_dir,
            dry_run=not args.execute,
            speak=args.speak,
            route_execute=args.route_execute,
            confirmed=args.confirmed,
            mark_announced=args.mark_announced,
            wake_timeout_seconds=args.wake_timeout_seconds,
        )
        print(render_efficient_wake_loop_result(result))
        return 0 if result.success else 1

    if args.command == "open-app":
        launcher = PlatformFactory.get_app_launcher()
        pal_result = launcher.launch(args.app, dry_run=not args.execute)
        result = DesktopControlResult(
            success=pal_result.success,
            action=DesktopControlAction.OPEN_APP,
            command=pal_result.command,
            message=pal_result.message,
            dry_run=pal_result.dry_run,
            executed=not pal_result.dry_run and pal_result.success,
        )
        print(render_desktop_control_result(result))
        return 0

    if args.command == "list-windows":
        wm = PlatformFactory.get_window_manager()
        try:
            windows = wm.list_windows()
            result = DesktopControlResult(
                success=True,
                action=DesktopControlAction.LIST_WINDOWS,
                command=(),
                message=str(windows),
                dry_run=False,
                executed=True,
            )
        except Exception as e:  # noqa: BLE001
            result = DesktopControlResult(
                success=False,
                action=DesktopControlAction.LIST_WINDOWS,
                command=(),
                message=f"List windows failed: {e}",
                dry_run=False,
                executed=False,
            )
        print(render_desktop_control_result(result))
        return 0

    if args.command == "screenshot":
        capture = PlatformFactory.get_screen_capture()
        output_path = args.output
        try:
            if args.select_region:
                pal_result = capture.capture_selected_region(
                    output_path=output_path,
                    dry_run=not args.execute,
                )
            else:
                pal_result = capture.capture(
                    output_path=output_path,
                    geometry=args.geometry,
                    dry_run=not args.execute,
                )
            success = getattr(pal_result, "success", True)
            cmd = getattr(pal_result, "command", ())
            msg = getattr(pal_result, "message", "Screenshot captured.")
            dr = getattr(pal_result, "dry_run", not args.execute)
            exec_ok = getattr(pal_result, "executed", args.execute and success)
            out_p = getattr(pal_result, "output_path", Path(output_path) if output_path else None)

            result = DesktopControlResult(
                success=success,
                action=DesktopControlAction.SCREENSHOT,
                command=cmd,
                message=msg,
                dry_run=dr,
                executed=exec_ok,
                output_path=out_p,
            )
        except Exception as e:  # noqa: BLE001
            result = DesktopControlResult(
                success=False,
                action=DesktopControlAction.SCREENSHOT,
                command=(),
                message=f"Screenshot failed: {e}",
                dry_run=not args.execute,
                executed=False,
            )
        print(render_desktop_control_result(result))
        return 0 if result.success else 1

    if args.command == "type-text":
        syn = PlatformFactory.get_input_synthesizer()
        try:
            pal_result = syn.type_text(
                args.text,
                confirmed=args.confirmed,
                dry_run=not args.execute,
            )
            success = getattr(pal_result, "success", True)
            cmd = getattr(pal_result, "command", ())
            msg = getattr(pal_result, "message", "Text typed successfully.")
            dr = getattr(pal_result, "dry_run", not args.execute)
            exec_ok = getattr(pal_result, "executed", args.execute and success)

            result = DesktopControlResult(
                success=success,
                action=DesktopControlAction.TYPE_TEXT,
                command=cmd,
                message=msg,
                dry_run=dr,
                executed=exec_ok,
            )
        except Exception as e:  # noqa: BLE001
            result = DesktopControlResult(
                success=False,
                action=DesktopControlAction.TYPE_TEXT,
                command=(),
                message=f"Type text failed: {e}",
                dry_run=not args.execute,
                executed=False,
            )
        print(render_desktop_control_result(result))
        return 0 if result.success else 1

    if args.command == "notifications-ingest":
        store = _notification_store(args)
        event = create_notification_event(
            app_name=args.app,
            desktop_entry=args.desktop_entry,
            summary=args.summary,
            body=args.body,
            source_window=args.source_window,
            urgency=NotificationUrgency(args.urgency),
        )
        result = NotificationCenter(store=store).ingest(
            event,
            speak=args.speak,
            persist=not args.dry_run,
        )
        print(render_notification_processing_result(result))
        return 0

    if args.command == "notifications-mode":
        store = _notification_store(args)
        state = store.set_focus_mode(
            NotificationFocusMode(args.mode),
            expires_at=expires_after_minutes(args.minutes),
        )
        expires = state.mode_expires_at.isoformat() if state.mode_expires_at else "manual"
        print(f"Notification mode set to {state.mode.value}; expires: {expires}")
        return 0

    if args.command == "notifications-mute":
        store = _notification_store(args)
        expires_at = expires_after_minutes(args.minutes)
        rules = tuple(
            store.save_rule(
                NotificationRule(
                    app_pattern=app,
                    action=NotificationAction(args.action),
                    mode=args.mode,
                    expires_at=expires_at,
                )
            )
            for app in args.app
        )
        for rule in rules:
            expires = rule.expires_at.isoformat() if rule.expires_at else "manual"
            print(
                f"Rule #{rule.id}: {rule.app_pattern} -> {rule.action.value} "
                f"in {rule.mode} mode; expires: {expires}"
            )
        return 0

    if args.command == "notifications-summary":
        store = _notification_store(args)
        pending = store.list_pending(limit=args.limit)
        print(build_notification_digest(pending).render())
        if args.mark_announced:
            count = store.mark_events(
                (event.id for event in pending),
                NotificationStatus.ANNOUNCED,
            )
            print(f"Marked {count} notification(s) as announced.")
        return 0

    if args.command == "notifications-list":
        store = _notification_store(args)
        print(
            render_notification_events(
                store.list_events(
                    statuses=_notification_status_filter(args.status),
                    limit=args.limit,
                )
            )
        )
        return 0

    if args.command == "notifications-clear":
        if not args.confirmed:
            print("Blocked: deleting notification memory requires --confirmed.")
            return 1
        store = _notification_store(args)
        deleted = store.delete_events(statuses=_notification_status_filter(args.status))
        print(f"Deleted {deleted} notification event(s).")
        return 0

    if args.command == "notifications-mark":
        new_status = NotificationStatus(args.status)
        if new_status in {NotificationStatus.REPLIED, NotificationStatus.DISMISSED}:
            if not args.confirmed:
                print(f"Blocked: marking as {new_status.value} requires --confirmed.")
                return 1
        store = _notification_store(args)
        event = store.update_event_status(args.event_id, new_status)
        if event is None:
            print(f"Notification not found: {args.event_id}")
            return 1
        print(f"Marked {event.id} as {event.status.value}.")
        return 0

    if args.command == "notifications-listen":
        store = _notification_store(args)
        daemon = PlatformFactory.get_notification_daemon()
        if hasattr(daemon, "center"):
            daemon.center = NotificationCenter(store=store)
        result = daemon.run(
            seconds=args.seconds,
            speak=args.speak,
            dry_run=not args.execute,
        )
        status = "executed" if result.executed else "prepared"
        if not result.success:
            status = "failed"
        lines = [f"Windows notifications [{status}]: {result.message}"]
        for item in getattr(result, "results", ()):
            lines.append(
                f"- {item.stored_event.id if item.stored_event else item.event.id}: "
                f"{item.action.value} {item.event.display_source}"
            )
        print("\n".join(lines))
        return 0 if result.success else 1

    if args.command == "notifications-intent":
        store = _notification_store(args)
        intent = parse_notification_voice_intent(args.text)
        result = execute_notification_voice_intent(
            intent,
            store=store,
            mark_announced=args.mark_announced,
        )
        print(render_notification_voice_intent_result(result))
        return 0 if result.success else 1

    if args.command == "notifications-reply-draft":
        store = _notification_store(args)
        text_result = resolve_reply_text(
            message=args.message,
            audio_path=args.audio_path,
            record_seconds=args.record_seconds,
            record_audio_path=args.record_audio_path,
            transcriber=LocalWhisperSTT(model_name=args.model, language=args.language),
            listener=ListenOnce(
                stt=LocalWhisperSTT(model_name=args.model, language=args.language),
            ),
        )
        if not text_result.success:
            print(f"Notification reply draft [blocked]: {text_result.message}")
            return 1
        result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
            event_id=args.event_id,
            reply_text=text_result.text,
            selector=args.selector,
            snapshot_output=_read_optional_text_file(args.snapshot_json),
            auto_select=args.auto_select,
            confirmed=args.confirmed,
            dry_run=not args.execute,
        )
        print(render_notification_reply_draft_result(result))
        return 0 if result.success else 1

    if args.command == "plan":
        router = ToolRouter.from_config_file(args.mcp_config)
        print(
            create_action_plan(
                args.instruction,
                llm_config=_planner_config(args),
                available_tools=router.planner_tools(),
                telemetry_store=_telemetry_store(args),
                smart_layer_enabled=not args.disable_smart_layer,
            ).render()
        )
        return 0

    if args.command == "route-plan":
        router = ToolRouter.from_config_file(args.mcp_config)
        plan = create_action_plan(
            args.instruction,
            llm_config=_planner_config(args),
            available_tools=router.planner_tools(),
            telemetry_store=_telemetry_store(args),
            smart_layer_enabled=not args.disable_smart_layer,
        )
        context = ToolExecutionContext(
            dry_run=not args.execute,
            confirmed=args.confirmed,
        )
        print(render_tool_results(router.route_plan(plan, context)))
        return 0

    if args.command == "telemetry-report":
        print(render_telemetry_summary(_telemetry_store(args).summarize(days=args.days)))
        return 0

    if args.command == "browser-snapshot":
        interaction_plan = BrowserInteractionLoop().open_and_snapshot(
            args.url,
            dry_run=not args.execute,
        )
        print(render_browser_interaction_plan(interaction_plan))
        return _browser_plan_exit_code(interaction_plan.status)

    if args.command == "browser-action":
        interaction_plan = BrowserInteractionLoop().confirmed_ref_action(
            kind=BrowserCommandKind(args.kind),
            selector=args.selector,
            text=args.text,
            key=args.key,
            confirmed=args.confirmed,
            dry_run=not args.execute,
        )
        print(render_browser_interaction_plan(interaction_plan))
        return _browser_plan_exit_code(interaction_plan.status)

    if args.command == "coding-prompt":
        agent = get_coding_agent(args.agent)
        print(
            build_coding_agent_prompt(
                agent=agent,
                project_path=args.project,
                idea=args.idea,
                user_constraints=tuple(args.constraint),
            )
        )
        return 0

    _print_status(config)
    return 0


def _browser_plan_exit_code(status: BrowserActionStatus) -> int:
    return 0 if status in {BrowserActionStatus.PREPARED, BrowserActionStatus.EXECUTED} else 1


def _planner_config(args: argparse.Namespace) -> LLMPlannerConfig:
    return build_planner_config_from_env(
        endpoint_url=args.planner_endpoint,
        model=args.planner_model,
        api_key=args.planner_api_key,
        api_key_env=args.planner_api_key_env,
    )


def _telemetry_store(args: argparse.Namespace) -> ExecutionTelemetryStore:
    return ExecutionTelemetryStore(getattr(args, "telemetry_store", None))


if __name__ == "__main__":
    raise SystemExit(main())
