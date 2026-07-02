"""Minimal CLI entrypoint for Eclipse."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
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
from eclipse_agent.answer import answer_question_from_env, render_answer_result
from eclipse_agent.screen_ask import ask_about_screen, render_screen_ask_result
from eclipse_agent.morning_briefing import BriefingConfig, compose_briefing, render_briefing
from eclipse_agent.weather import WeatherConfig, get_weather, render_weather
from eclipse_agent.email_sender import EmailSender, SmtpConfigError
from eclipse_agent.clipboard import WindowsClipboard, render_clipboard_result
from eclipse_agent.audit import AuditLog, render_audit_entries
from eclipse_agent.browser_control import BrowserControlService
from eclipse_agent.chrome_devtools_mcp import ChromeDevToolsMCPAdapter
from eclipse_agent.calendar_agenda import read_agenda, render_agenda_cli
from eclipse_agent.killswitch import KillSwitch
from eclipse_agent.push_to_talk import run_push_to_talk
from eclipse_agent.telegram_bot import (
    TelegramBotConfig,
    parse_allowed_chat_ids,
    run_telegram_bot,
)
from eclipse_agent.settings import (
    apply_to_env,
    default_mcp_config_path,
    default_settings_path,
    load_mcp_servers,
    load_settings,
)
from eclipse_agent.settings_app import run_settings_app
from eclipse_agent.tray import run_tray
from eclipse_agent.documents import (
    DocumentStore,
    EmbeddingClient,
    answer_from_documents,
    ingest_path,
    render_document_answer,
    render_document_sources,
    render_ingest_result,
)
from eclipse_agent.email_inbox import (
    ImapMailbox,
    draft_reply,
    render_email_messages,
    render_inbox_summary,
    render_reply_draft,
    summarize_inbox,
)
from eclipse_agent.media_playback import (
    open_media_search,
    render_media_playback_result,
)
from eclipse_agent.memory import (
    MemoryIntent,
    MemoryStore,
    parse_memory_request,
    render_memory_facts,
)
from eclipse_agent.reminders import (
    ReminderStore,
    expires_after_seconds,
    fire_due_reminders,
    parse_reminder_request,
    render_reminders,
)
from eclipse_agent.routines import (
    RoutineAction,
    RoutineStore,
    ScheduleKind,
    fire_due_routines,
    parse_routine_request,
    render_routines,
)
from eclipse_agent.system_control import SystemAction, render_system_control_result
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
    PROVIDERS,
    LLMPlannerConfig,
    build_planner_config_from_env,
    create_action_plan,
)
from eclipse_agent.resources import estimate_resource_profile
from eclipse_agent.runtime_diagnostics import collect_runtime_diagnostics
from eclipse_agent.telemetry import ExecutionTelemetryStore, render_telemetry_summary
from eclipse_agent.tool_router import (
    CompositeMCPClient,
    MCPToolClient,
    NativeMCPClient,
    ToolExecutionContext,
    ToolRouter,
    load_mcp_server_configs,
    render_tool_results,
)
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

    system = subparsers.add_parser(
        "system",
        help="Run a system-control action: volume, media, lock, or battery.",
    )
    system.add_argument(
        "--action",
        required=True,
        choices=[action.value for action in SystemAction],
        help="System action to run.",
    )
    system.add_argument(
        "--execute",
        action="store_true",
        help="Actually run the action instead of dry-running.",
    )
    system.add_argument(
        "--confirmed",
        action="store_true",
        help="Required to execute disruptive actions such as lock.",
    )

    clipboard = subparsers.add_parser(
        "clipboard",
        help="Read or write the Windows clipboard.",
    )
    clipboard.add_argument("--action", required=True, choices=("read", "write"))
    clipboard.add_argument("--text", help="Text to copy when --action is write.")

    ask = subparsers.add_parser(
        "ask",
        help="Answer a question with the configured LLM provider.",
    )
    ask.add_argument("--question", required=True, help="The question to answer.")
    ask.add_argument(
        "--provider",
        default=None,
        choices=sorted(PROVIDERS),
        help="LLM provider preset. Defaults to ECLIPSE_LLM_PROVIDER or ollama.",
    )

    remind = subparsers.add_parser("remind", help="Set a reminder or timer.")
    remind.add_argument(
        "--text",
        required=True,
        help="Reminder text, or a phrase like 'en 10 minutos que saque la pizza'.",
    )
    remind.add_argument(
        "--seconds",
        type=int,
        help="Delay in seconds. Overrides parsing the delay from --text.",
    )

    subparsers.add_parser("reminders-list", help="List pending reminders.")

    remember = subparsers.add_parser(
        "remember",
        help="Remember a fact or preference across sessions.",
    )
    remember.add_argument(
        "--text",
        help="Natural phrase, e.g. 'mi nombre es Patricio'.",
    )
    remember.add_argument("--key", help="Explicit fact key (use with --value).")
    remember.add_argument("--value", help="Explicit fact value (use with --key).")

    subparsers.add_parser("memory-list", help="List remembered facts.")

    memory_recall = subparsers.add_parser("memory-recall", help="Recall a remembered fact.")
    memory_recall.add_argument("--key", required=True, help="The fact key to recall.")

    memory_forget = subparsers.add_parser("memory-forget", help="Forget a remembered fact.")
    memory_forget.add_argument("--key", required=True, help="The fact key to forget.")

    routine_add = subparsers.add_parser(
        "routine-add",
        help="Schedule a recurring proactive routine.",
    )
    routine_add.add_argument(
        "--text",
        help="Natural phrase, e.g. 'cada mañana a las 8 decime el resumen'.",
    )
    routine_add.add_argument("--name", help="Routine name. Auto-generated if omitted.")
    routine_add.add_argument("--message", help="What to say or ask when it fires.")
    routine_add.add_argument(
        "--action",
        default="say",
        choices=[action.value for action in RoutineAction],
        help="say speaks the message; ask answers it with the LLM provider.",
    )
    routine_add.add_argument("--daily-at", help="Daily local time, e.g. 08:00.")
    routine_add.add_argument("--every-seconds", type=int, help="Interval in seconds.")

    subparsers.add_parser("routines-list", help="List scheduled routines.")

    routine_remove = subparsers.add_parser("routine-remove", help="Remove a routine.")
    routine_remove.add_argument("--name", required=True, help="The routine name to remove.")

    routines_check = subparsers.add_parser(
        "routines-check",
        help="Fire routines that are due now.",
    )
    routines_check.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak due routines instead of dry-running.",
    )

    docs_add = subparsers.add_parser(
        "docs-add",
        help="Ingest notes/PDFs into the local document store for Q&A.",
    )
    docs_add.add_argument("--path", required=True, help="File or directory to ingest.")

    subparsers.add_parser("docs-list", help="List ingested documents.")
    subparsers.add_parser("docs-clear", help="Remove all ingested documents.")

    docs_ask = subparsers.add_parser(
        "docs-ask",
        help="Answer a question grounded in your ingested documents.",
    )
    docs_ask.add_argument("--query", required=True, help="The question to answer.")

    email_list = subparsers.add_parser(
        "email-list",
        help="List recent inbox messages over IMAP (read-only).",
    )
    email_list.add_argument("--limit", type=int, default=5, help="How many messages.")
    email_list.add_argument(
        "--all", action="store_true", help="Include read messages, not just unread."
    )

    email_summary = subparsers.add_parser(
        "email-summary",
        help="Read and summarize your inbox (read-only).",
    )
    email_summary.add_argument("--limit", type=int, default=5, help="How many messages.")
    email_summary.add_argument("--all", action="store_true", help="Include read messages.")

    email_draft = subparsers.add_parser(
        "email-draft",
        help="Draft a reply to a message. Never sends.",
    )
    email_draft.add_argument("--uid", required=True, help="Message UID from email-list.")
    email_draft.add_argument("--instruction", default="", help="Guidance for the reply.")

    agenda = subparsers.add_parser(
        "agenda",
        help="Read your upcoming calendar agenda from an iCal source (read-only).",
    )
    agenda.add_argument("--days", type=int, default=7, help="Horizon in days.")
    agenda.add_argument("--limit", type=int, default=10, help="Max events to show.")

    audit = subparsers.add_parser("audit", help="Show recently audited actions.")
    audit.add_argument("--limit", type=int, default=20, help="How many entries to show.")

    subparsers.add_parser("audit-clear", help="Clear the audit log.")

    subparsers.add_parser("kill", help="Engage the kill switch; Eclipse stops acting.")
    subparsers.add_parser("resume", help="Disengage the kill switch.")
    subparsers.add_parser("kill-status", help="Show whether the kill switch is engaged.")

    subparsers.add_parser("tray", help="Run a system-tray icon showing Eclipse's status.")
    subparsers.add_parser("settings", help="Open the Eclipse desktop settings app.")

    push_to_talk = subparsers.add_parser(
        "push-to-talk",
        help="Trigger Eclipse with a global hotkey instead of the wake word.",
    )
    _add_notification_store_arg(push_to_talk)
    push_to_talk.add_argument(
        "--hotkey", default="ctrl+alt+e", help="Global hotkey, e.g. ctrl+alt+e."
    )
    push_to_talk.add_argument("--command-seconds", type=int, default=5, help="Command clip length.")
    push_to_talk.add_argument("--model", default="small", help="faster-whisper model name/path.")
    push_to_talk.add_argument("--language", default="es", help="Transcription language code.")
    push_to_talk.add_argument("--speak", action="store_true", help="Speak Eclipse's response.")
    push_to_talk.add_argument(
        "--route-execute", action="store_true", help="Execute low-risk routed actions."
    )
    push_to_talk.add_argument(
        "--confirmed", action="store_true", help="Treat medium-risk actions as confirmed."
    )

    play_media = subparsers.add_parser(
        "play-media",
        help="Open a media search in your default browser (YouTube Music, etc.).",
    )
    play_media.add_argument(
        "--app",
        default="YouTube Music",
        help="Media app. Defaults to YouTube Music.",
    )
    play_media.add_argument("--query", required=True, help="What to play.")
    play_media.add_argument(
        "--execute",
        action="store_true",
        help="Actually open the browser instead of dry-running.",
    )

    reminders_check = subparsers.add_parser(
        "reminders-check",
        help="Fire reminders that are due now.",
    )
    reminders_check.add_argument(
        "--speak",
        action="store_true",
        help="Actually speak due reminders instead of dry-running.",
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

    screen_ask = subparsers.add_parser(
        "screen-ask",
        help="Capture the screen and ask the vision model about it.",
    )
    screen_ask.add_argument("question", nargs="?", default="", help="Question about the screen.")
    screen_ask.add_argument("--window", default=None, help="Optional window title to capture.")

    weather_cmd = subparsers.add_parser(
        "weather",
        help="Fetch and display current weather conditions.",
    )
    weather_cmd.add_argument("--format", choices=("brief", "full"), default="brief")
    weather_cmd.add_argument("--lat", type=float, default=None, help="Latitude override.")
    weather_cmd.add_argument("--lon", type=float, default=None, help="Longitude override.")

    subparsers.add_parser(
        "briefing",
        help="Compose and display the morning briefing.",
    )

    send_email_cmd = subparsers.add_parser(
        "send-email",
        help="Send an email via SMTP. Requires --confirmed to actually send.",
    )
    send_email_cmd.add_argument("--to", required=True, help="Recipient address.")
    send_email_cmd.add_argument("--subject", required=True, help="Email subject.")
    send_email_cmd.add_argument("--body", required=True, help="Email body (plain text).")
    send_email_cmd.add_argument(
        "--confirmed",
        action="store_true",
        help="Actually send the email. Without this flag, a preview is shown.",
    )

    telegram_bot = subparsers.add_parser(
        "telegram-bot",
        help="Run the Telegram bot remote-control adapter.",
    )
    _add_notification_store_arg(telegram_bot)
    telegram_bot.add_argument(
        "--token",
        help="Telegram bot token. Defaults to ECLIPSE_TELEGRAM_BOT_TOKEN.",
    )
    telegram_bot.add_argument(
        "--allowed-chats",
        help="Comma-separated chat IDs. Defaults to ECLIPSE_TELEGRAM_ALLOWED_CHATS.",
    )

    return parser


def _add_notification_store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        help="Optional SQLite notification store path. Defaults to the LOCALAPPDATA folder.",
    )


def _add_planner_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default=None,
        choices=sorted(PROVIDERS),
        help="LLM provider preset. Defaults to ECLIPSE_LLM_PROVIDER or ollama.",
    )
    parser.add_argument(
        "--planner-endpoint",
        default=None,
        help="OpenAI-compatible LLM base URL. Overrides the provider preset.",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="LLM model name. Overrides the provider preset default.",
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


def _cmd_resource_plan(args: argparse.Namespace) -> int:
    print(estimate_resource_profile(_build_config(args).activation_mode).render())
    return 0


def _cmd_diagnostics(args: argparse.Namespace) -> int:
    print(collect_runtime_diagnostics().render())
    return 0


def _cmd_smoke_plan(args: argparse.Namespace) -> int:
    print(render_agent_smoke_plan(build_agent_smoke_plan(store_path=args.store)))
    return 0


def _cmd_smoke_simulate(args: argparse.Namespace) -> int:
    store = args.store or str(Path(tempfile.gettempdir()) / "eclipse-smoke.sqlite3")
    result = run_agent_smoke_simulation(store_path=store)
    print(render_agent_smoke_simulation(result))
    return 0 if result.success else 1


def _cmd_say(args: argparse.Namespace) -> int:
    print(render_speech_result(SystemTTS().speak(args.text, dry_run=not args.execute)))
    return 0


def _cmd_listen_status(args: argparse.Namespace) -> int:
    status = LocalWhisperSTT().status()
    marker = "ready" if status.available else "missing"
    print(f"STT [{marker}] {status.provider}: {status.message}")
    return 0


def _cmd_listen(args: argparse.Namespace) -> int:
    result = ListenOnce(stt=LocalWhisperSTT(model_name=args.model, language=args.language)).run(
        seconds=args.seconds,
        audio_path=args.audio_path,
        dry_run=not args.execute,
    )
    print(render_listen_result(result))
    return 0


def _cmd_transcribe_file(args: argparse.Namespace) -> int:
    result = LocalWhisperSTT(
        model_name=args.model,
        language=args.language,
    ).transcribe_file(args.audio_path)
    marker = "ok" if result.success else "failed"
    print(f"STT [{marker}] {result.provider}: {result.message}")
    print(f"text: {result.text}")
    return 0


def _cmd_wake_command(args: argparse.Namespace) -> int:
    result = WakeRuntime(
        store=_notification_store(args), router=_build_router(args)
    ).handle_command(
        args.text,
        speak=args.speak,
        route_execute=args.route_execute,
        confirmed=args.confirmed,
        mark_announced=args.mark_announced,
    )
    print(render_wake_command_result(result))
    return 0 if result.success else 1


def _cmd_wake_loop(args: argparse.Namespace) -> int:
    runtime = WakeRuntime(
        listener=ListenOnce(
            stt=LocalWhisperSTT(model_name=args.model, language=args.language),
        ),
        store=_notification_store(args),
        router=_build_router(args),
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


def _cmd_wake_efficient(args: argparse.Namespace) -> int:
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
        router=_build_router(args),
    )
    runtime.start_reminder_poller(dry_run=not args.execute)
    runtime.start_routine_poller(dry_run=not args.execute)
    telegram_token = os.environ.get("ECLIPSE_TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chats = os.environ.get("ECLIPSE_TELEGRAM_ALLOWED_CHATS", "").strip()
    if telegram_token and telegram_chats:
        runtime.start_telegram_bot(
            TelegramBotConfig(
                token=telegram_token,
                allowed_chat_ids=parse_allowed_chat_ids(telegram_chats),
            )
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


def _cmd_open_app(args: argparse.Namespace) -> int:
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


def _cmd_list_windows(args: argparse.Namespace) -> int:
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


def _cmd_screenshot(args: argparse.Namespace) -> int:
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


def _cmd_type_text(args: argparse.Namespace) -> int:
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


def _cmd_system(args: argparse.Namespace) -> int:
    action = SystemAction(args.action)
    if action is SystemAction.LOCK and args.execute and not args.confirmed:
        print("Blocked: locking the workstation requires --confirmed.")
        return 1
    controller = PlatformFactory.get_system_controller()
    result = controller.run(action, dry_run=not args.execute)
    print(render_system_control_result(result))
    return 0 if result.success else 1


def _cmd_remind(args: argparse.Namespace) -> int:
    store = ReminderStore()
    if args.seconds is not None:
        if args.seconds <= 0:
            print("Reminder delay must be positive.")
            return 1
        reminder = store.add(args.text, expires_after_seconds(args.seconds))
    else:
        request = parse_reminder_request(args.text)
        if request is None:
            print("Could not find a delay. Use --seconds or include 'en N minutos'.")
            return 1
        reminder = store.add(request.text, expires_after_seconds(request.delay_seconds))
    print(f"Reminder set for {reminder.due_at.isoformat()}: {reminder.text}")
    return 0


def _cmd_reminders_list(args: argparse.Namespace) -> int:
    print(render_reminders(ReminderStore().list_pending()))
    return 0


def _cmd_reminders_check(args: argparse.Namespace) -> int:
    tts = SystemTTS()
    fired = fire_due_reminders(
        ReminderStore(),
        lambda text: tts.speak(text, dry_run=not args.speak),
    )
    if not fired:
        print("No reminders are due.")
        return 0
    for reminder in fired:
        print(f"Fired: {reminder.text}")
    return 0


def _cmd_remember(args: argparse.Namespace) -> int:
    store = MemoryStore()
    if args.key:
        if not args.value:
            print("Provide --value together with --key.")
            return 1
        fact = store.remember(args.key, args.value)
    elif args.text:
        request = parse_memory_request(args.text)
        if request is None or request.intent is not MemoryIntent.REMEMBER:
            print("Could not parse a fact. Use --key/--value or 'mi nombre es Patricio'.")
            return 1
        fact = store.remember(request.key, request.value)
    else:
        print("Provide --text or --key/--value.")
        return 1
    print(f"Remembered {fact.key}: {fact.value}")
    return 0


def _cmd_memory_list(args: argparse.Namespace) -> int:
    print(render_memory_facts(MemoryStore().list_all()))
    return 0


def _cmd_memory_recall(args: argparse.Namespace) -> int:
    fact = MemoryStore().recall(args.key)
    if fact is None:
        print(f"No memory for {args.key}.")
        return 1
    print(f"{fact.key}: {fact.value}")
    return 0


def _cmd_memory_forget(args: argparse.Namespace) -> int:
    if MemoryStore().forget(args.key):
        print(f"Forgot {args.key}.")
        return 0
    print(f"No memory for {args.key}.")
    return 1


def _cmd_routine_add(args: argparse.Namespace) -> int:
    store = RoutineStore()
    if args.text:
        request = parse_routine_request(args.text)
        if request is None:
            print("Could not parse a routine. Use --message with --daily-at or --every-seconds.")
            return 1
        routine = store.add(
            request.message,
            request.schedule_kind,
            request.schedule_value,
            name=args.name,
            action=request.action,
        )
    elif args.message and (args.daily_at or args.every_seconds):
        if args.daily_at:
            kind, value = ScheduleKind.DAILY, args.daily_at
        else:
            kind, value = ScheduleKind.INTERVAL, str(args.every_seconds)
        routine = store.add(
            args.message, kind, value, name=args.name, action=RoutineAction(args.action)
        )
    else:
        print("Provide --text, or --message with --daily-at or --every-seconds.")
        return 1
    print(f"Routine '{routine.name}' scheduled, next run {routine.next_run.isoformat()}")
    return 0


def _cmd_routines_list(args: argparse.Namespace) -> int:
    print(render_routines(RoutineStore().list_all()))
    return 0


def _cmd_routine_remove(args: argparse.Namespace) -> int:
    if RoutineStore().remove(args.name):
        print(f"Removed routine '{args.name}'.")
        return 0
    print(f"No routine named '{args.name}'.")
    return 1


def _cmd_routines_check(args: argparse.Namespace) -> int:
    tts = SystemTTS()
    fired = fire_due_routines(
        RoutineStore(),
        lambda text: tts.speak(text, dry_run=not args.speak),
    )
    if not fired:
        print("No routines are due.")
        return 0
    for routine in fired:
        print(f"Fired: {routine.name}")
    return 0


def _cmd_play_media(args: argparse.Namespace) -> int:
    result = open_media_search(args.app, args.query, dry_run=not args.execute)
    print(render_media_playback_result(result))
    return 0 if result.success else 1


def _cmd_docs_add(args: argparse.Namespace) -> int:
    result = ingest_path(args.path, DocumentStore(), EmbeddingClient().embed)
    print(render_ingest_result(result))
    return 0 if result.success else 1


def _cmd_docs_list(args: argparse.Namespace) -> int:
    print(render_document_sources(DocumentStore().sources()))
    return 0


def _cmd_docs_clear(args: argparse.Namespace) -> int:
    removed = DocumentStore().clear()
    print(f"Cleared {removed} document chunks.")
    return 0


def _cmd_docs_ask(args: argparse.Namespace) -> int:
    result = answer_from_documents(args.query, DocumentStore())
    print(render_document_answer(result))
    return 0 if result.success else 1


def _cmd_email_list(args: argparse.Namespace) -> int:
    box = ImapMailbox()
    if not box.is_configured():
        print("Configure ECLIPSE_IMAP_USER and ECLIPSE_IMAP_PASSWORD first.")
        return 1
    try:
        messages = box.fetch_recent(limit=args.limit, unseen_only=not args.all)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read inbox: {exc}")
        return 1
    print(render_email_messages(messages))
    return 0


def _cmd_email_summary(args: argparse.Namespace) -> int:
    result = summarize_inbox(limit=args.limit, unseen_only=not args.all)
    print(render_inbox_summary(result))
    return 0 if result.success else 1


def _cmd_email_draft(args: argparse.Namespace) -> int:
    box = ImapMailbox()
    if not box.is_configured():
        print("Configure ECLIPSE_IMAP_USER and ECLIPSE_IMAP_PASSWORD first.")
        return 1
    try:
        messages = box.fetch_recent(limit=20, unseen_only=False)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read inbox: {exc}")
        return 1
    target = next((message for message in messages if message.uid == args.uid), None)
    if target is None:
        print(f"No message with uid {args.uid} in the recent inbox.")
        return 1
    print(render_reply_draft(draft_reply(target, args.instruction)))
    return 0


def _cmd_agenda(args: argparse.Namespace) -> int:
    result = read_agenda(horizon_days=args.days, limit=args.limit)
    print(render_agenda_cli(result))
    return 0 if result.success else 1


def _cmd_audit(args: argparse.Namespace) -> int:
    print(render_audit_entries(AuditLog().recent(limit=args.limit)))
    return 0


def _cmd_audit_clear(args: argparse.Namespace) -> int:
    print(f"Cleared {AuditLog().clear()} audit entries.")
    return 0


def _cmd_kill(args: argparse.Namespace) -> int:
    KillSwitch().engage()
    print("Kill switch ENGAGED. Eclipse will not act until you resume.")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    KillSwitch().disengage()
    print("Kill switch released. Eclipse can act again.")
    return 0


def _cmd_kill_status(args: argparse.Namespace) -> int:
    engaged = KillSwitch().is_engaged()
    print("Kill switch: ENGAGED (Eclipse paused)." if engaged else "Kill switch: off.")
    return 0


def _cmd_tray(args: argparse.Namespace) -> int:
    run_tray()
    return 0


def _cmd_settings(args: argparse.Namespace) -> int:
    run_settings_app()
    return 0


def _cmd_push_to_talk(args: argparse.Namespace) -> int:
    runtime = WakeRuntime(
        listener=ListenOnce(
            stt=LocalWhisperSTT(model_name=args.model, language=args.language),
        ),
        store=_notification_store(args),
        router=_build_router(args),
    )

    def on_activate() -> None:
        result = runtime.listen_and_handle(
            command_seconds=args.command_seconds,
            speak=args.speak,
            route_execute=args.route_execute,
            confirmed=args.confirmed,
        )
        print(render_wake_command_result(result))

    run_push_to_talk(on_activate, hotkey=args.hotkey)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    result = answer_question_from_env(args.question, provider=getattr(args, "provider", None))
    print(render_answer_result(result))
    return 0 if result.success else 1


def _cmd_clipboard(args: argparse.Namespace) -> int:
    clip = WindowsClipboard()
    if args.action == "write":
        result = clip.write(args.text or "")
    else:
        result = clip.read()
    print(render_clipboard_result(result))
    return 0 if result.success else 1


def _cmd_notifications_ingest(args: argparse.Namespace) -> int:
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


def _cmd_notifications_mode(args: argparse.Namespace) -> int:
    store = _notification_store(args)
    state = store.set_focus_mode(
        NotificationFocusMode(args.mode),
        expires_at=expires_after_minutes(args.minutes),
    )
    expires = state.mode_expires_at.isoformat() if state.mode_expires_at else "manual"
    print(f"Notification mode set to {state.mode.value}; expires: {expires}")
    return 0


def _cmd_notifications_mute(args: argparse.Namespace) -> int:
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


def _cmd_notifications_summary(args: argparse.Namespace) -> int:
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


def _cmd_notifications_list(args: argparse.Namespace) -> int:
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


def _cmd_notifications_clear(args: argparse.Namespace) -> int:
    if not args.confirmed:
        print("Blocked: deleting notification memory requires --confirmed.")
        return 1
    store = _notification_store(args)
    deleted = store.delete_events(statuses=_notification_status_filter(args.status))
    print(f"Deleted {deleted} notification event(s).")
    return 0


def _cmd_notifications_mark(args: argparse.Namespace) -> int:
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


def _cmd_notifications_listen(args: argparse.Namespace) -> int:
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


def _cmd_notifications_intent(args: argparse.Namespace) -> int:
    store = _notification_store(args)
    intent = parse_notification_voice_intent(args.text)
    result = execute_notification_voice_intent(
        intent,
        store=store,
        mark_announced=args.mark_announced,
    )
    print(render_notification_voice_intent_result(result))
    return 0 if result.success else 1


def _cmd_notifications_reply_draft(args: argparse.Namespace) -> int:
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


def _cmd_plan(args: argparse.Namespace) -> int:
    router = _build_router(args)
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


def _cmd_route_plan(args: argparse.Namespace) -> int:
    router = _build_router(args)
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


def _cmd_telemetry_report(args: argparse.Namespace) -> int:
    print(render_telemetry_summary(_telemetry_store(args).summarize(days=args.days)))
    return 0


def _cmd_browser_snapshot(args: argparse.Namespace) -> int:
    interaction_plan = BrowserInteractionLoop().open_and_snapshot(
        args.url,
        dry_run=not args.execute,
    )
    print(render_browser_interaction_plan(interaction_plan))
    return _browser_plan_exit_code(interaction_plan.status)


def _cmd_browser_action(args: argparse.Namespace) -> int:
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


def _cmd_coding_prompt(args: argparse.Namespace) -> int:
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


def _cmd_screen_ask(args: argparse.Namespace) -> int:
    question = getattr(args, "question", "") or ""
    window = getattr(args, "window", None)
    result = ask_about_screen(question, window)
    print(render_screen_ask_result(result))
    return 0 if result.success else 1


def _cmd_weather(args: argparse.Namespace) -> int:
    import os

    lat = getattr(args, "lat", None)
    lon = getattr(args, "lon", None)
    if lat is None:
        lat = float(os.environ.get("ECLIPSE_WEATHER_LAT") or 0.0)
    if lon is None:
        lon = float(os.environ.get("ECLIPSE_WEATHER_LON") or 0.0)
    config = WeatherConfig(latitude=lat, longitude=lon)
    result = get_weather(config)
    print(render_weather(result))
    return 0 if result.success else 1


def _cmd_briefing(args: argparse.Namespace) -> int:
    result = compose_briefing(BriefingConfig())
    print(render_briefing(result))
    return 0 if result.success else 1


def _cmd_send_email(args: argparse.Namespace) -> int:
    if not args.confirmed:
        print(f"Preview — To: {args.to}")
        print(f"Subject: {args.subject}")
        print(f"Body: {args.body}")
        print("Add --confirmed to actually send.")
        return 0
    try:
        EmailSender().send(to=args.to, subject=args.subject, body=args.body)
        print(f"Email sent to {args.to}.")
        return 0
    except SmtpConfigError as exc:
        print(f"Send failed: {exc}")
        return 1


def _cmd_telegram_bot(args: argparse.Namespace) -> int:
    token = (args.token or os.environ.get("ECLIPSE_TELEGRAM_BOT_TOKEN", "")).strip()
    allowed_chats_raw = (
        args.allowed_chats or os.environ.get("ECLIPSE_TELEGRAM_ALLOWED_CHATS", "")
    ).strip()
    try:
        config = TelegramBotConfig(
            token=token,
            allowed_chat_ids=parse_allowed_chat_ids(allowed_chats_raw),
        )
        runtime = WakeRuntime(store=_notification_store(args), router=_build_router(args))
        run_telegram_bot(config, runtime, kill_switch=KillSwitch())
    except (RuntimeError, ValueError) as exc:
        print(f"Telegram bot failed: {exc}")
        return 1
    return 0

_COMMAND_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "resource-plan": _cmd_resource_plan,
    "diagnostics": _cmd_diagnostics,
    "smoke-plan": _cmd_smoke_plan,
    "smoke-simulate": _cmd_smoke_simulate,
    "say": _cmd_say,
    "listen-status": _cmd_listen_status,
    "listen": _cmd_listen,
    "transcribe-file": _cmd_transcribe_file,
    "wake-command": _cmd_wake_command,
    "wake-loop": _cmd_wake_loop,
    "wake-efficient": _cmd_wake_efficient,
    "open-app": _cmd_open_app,
    "list-windows": _cmd_list_windows,
    "screenshot": _cmd_screenshot,
    "type-text": _cmd_type_text,
    "system": _cmd_system,
    "clipboard": _cmd_clipboard,
    "ask": _cmd_ask,
    "remind": _cmd_remind,
    "reminders-list": _cmd_reminders_list,
    "reminders-check": _cmd_reminders_check,
    "remember": _cmd_remember,
    "memory-list": _cmd_memory_list,
    "memory-recall": _cmd_memory_recall,
    "memory-forget": _cmd_memory_forget,
    "routine-add": _cmd_routine_add,
    "routines-list": _cmd_routines_list,
    "routine-remove": _cmd_routine_remove,
    "routines-check": _cmd_routines_check,
    "play-media": _cmd_play_media,
    "docs-add": _cmd_docs_add,
    "docs-list": _cmd_docs_list,
    "docs-clear": _cmd_docs_clear,
    "docs-ask": _cmd_docs_ask,
    "email-list": _cmd_email_list,
    "email-summary": _cmd_email_summary,
    "email-draft": _cmd_email_draft,
    "agenda": _cmd_agenda,
    "audit": _cmd_audit,
    "audit-clear": _cmd_audit_clear,
    "kill": _cmd_kill,
    "resume": _cmd_resume,
    "kill-status": _cmd_kill_status,
    "tray": _cmd_tray,
    "settings": _cmd_settings,
    "push-to-talk": _cmd_push_to_talk,
    "notifications-ingest": _cmd_notifications_ingest,
    "notifications-mode": _cmd_notifications_mode,
    "notifications-mute": _cmd_notifications_mute,
    "notifications-summary": _cmd_notifications_summary,
    "notifications-list": _cmd_notifications_list,
    "notifications-clear": _cmd_notifications_clear,
    "notifications-mark": _cmd_notifications_mark,
    "notifications-listen": _cmd_notifications_listen,
    "notifications-intent": _cmd_notifications_intent,
    "notifications-reply-draft": _cmd_notifications_reply_draft,
    "plan": _cmd_plan,
    "route-plan": _cmd_route_plan,
    "telemetry-report": _cmd_telemetry_report,
    "browser-snapshot": _cmd_browser_snapshot,
    "browser-action": _cmd_browser_action,
    "coding-prompt": _cmd_coding_prompt,
    "screen-ask": _cmd_screen_ask,
    "weather": _cmd_weather,
    "briefing": _cmd_briefing,
    "send-email": _cmd_send_email,
    "telegram-bot": _cmd_telegram_bot,
}


def _load_settings_to_env() -> None:
    """Apply saved settings (config.json from the desktop app) to the environment."""

    path = default_settings_path()
    if path.exists():
        apply_to_env(load_settings(path))


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_output()
    _load_dotenv()
    _load_settings_to_env()
    args = build_parser().parse_args(argv)
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        _print_status(_build_config(args))
        return 0
    return handler(args)


def _browser_plan_exit_code(status: BrowserActionStatus) -> int:
    return 0 if status in {BrowserActionStatus.PREPARED, BrowserActionStatus.EXECUTED} else 1


def _build_router(args: argparse.Namespace) -> ToolRouter:
    """Build a tool router: native tools, plus any configured MCP servers."""

    audit_log = AuditLog()
    kill_switch = KillSwitch()
    settings = load_settings(default_settings_path())
    browser_control_service = BrowserControlService(
        settings=settings,
        devtools_adapter=ChromeDevToolsMCPAdapter.from_settings(settings),
        audit_log=audit_log,
    )
    mcp_config = getattr(args, "mcp_config", None)
    if not mcp_config and load_mcp_servers(default_mcp_config_path()):
        mcp_config = str(default_mcp_config_path())
    if mcp_config:
        configs = load_mcp_server_configs(mcp_config)
        if configs:
            client = CompositeMCPClient(NativeMCPClient(), MCPToolClient(configs))
            return ToolRouter(
                mcp_client=client,
                audit_log=audit_log,
                kill_switch=kill_switch,
                browser_control_service=browser_control_service,
            )
    return ToolRouter(
        mcp_client=NativeMCPClient(),
        audit_log=audit_log,
        kill_switch=kill_switch,
        browser_control_service=browser_control_service,
    )


def _load_dotenv() -> None:
    """Load a local .env file so provider keys and overrides are picked up."""

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv()


def _ensure_utf8_output() -> None:
    """Force UTF-8 stdout/stderr so accented output renders on the Windows console."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def _planner_config(args: argparse.Namespace) -> LLMPlannerConfig:
    return build_planner_config_from_env(
        endpoint_url=args.planner_endpoint,
        model=args.planner_model,
        api_key=args.planner_api_key,
        api_key_env=args.planner_api_key_env,
        provider=getattr(args, "provider", None),
    )


def _telemetry_store(args: argparse.Namespace) -> ExecutionTelemetryStore:
    return ExecutionTelemetryStore(getattr(args, "telemetry_store", None))


if __name__ == "__main__":
    raise SystemExit(main())
