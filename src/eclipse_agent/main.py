"""Minimal CLI entrypoint for Eclipse."""

from __future__ import annotations

import argparse
from pathlib import Path

from eclipse_agent import __version__
from eclipse_agent.activation import ActivationMode, build_activation_policy
from eclipse_agent.browser_automation import (
    BrowserCommandKind,
    BrowserInteractionLoop,
    render_browser_interaction_plan,
)
from eclipse_agent.coding_agents import build_coding_agent_prompt, get_coding_agent
from eclipse_agent.config import EclipseConfig
from eclipse_agent.fedora_control import FedoraNativeController, render_fedora_control_result
from eclipse_agent.notification_daemon import (
    DBusNotificationDaemon,
    render_dbus_notification_daemon_result,
)
from eclipse_agent.notification_intents import (
    execute_notification_voice_intent,
    parse_notification_voice_intent,
    render_notification_voice_intent_result,
)
from eclipse_agent.notification_replies import (
    NotificationReplyWorkflow,
    render_notification_reply_draft_result,
)
from eclipse_agent.notification_service import (
    NotificationServiceSpec,
    NotificationUserServiceManager,
    render_notification_service_result,
)
from eclipse_agent.notifications import (
    DBusNotificationListenerPlan,
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
from eclipse_agent.planner import create_action_plan
from eclipse_agent.resources import estimate_resource_profile
from eclipse_agent.runtime_diagnostics import collect_runtime_diagnostics
from eclipse_agent.tool_router import ToolExecutionContext, ToolRouter, render_tool_results
from eclipse_agent.voice import ListenOnce, LocalWhisperSTT, SystemTTS
from eclipse_agent.voice import render_listen_result, render_speech_result

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

    fedora_open = subparsers.add_parser(
        "fedora-open",
        help="Prepare or execute a Fedora/KDE native app launch.",
    )
    fedora_open.add_argument("--app", required=True, help="Desktop app name.")
    fedora_open.add_argument(
        "--execute",
        action="store_true",
        help="Actually launch the app instead of dry-running.",
    )

    subparsers.add_parser("fedora-windows", help="Show planned KDE window-control strategy.")

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

    subparsers.add_parser(
        "notifications-dbus-command",
        help="Show the first D-Bus monitor command for native/web notifications.",
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
        help="Actually run dbus-monitor instead of dry-running.",
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
    notifications_reply.add_argument("--message", required=True, help="Reply draft text.")
    notifications_reply.add_argument(
        "--selector",
        help="Optional agent-browser snapshot ref for the message input, e.g. @e12.",
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

    notifications_service = subparsers.add_parser(
        "notifications-service",
        help="Render/install the systemd user service for notification listening.",
    )
    notifications_service.add_argument(
        "--action",
        choices=("render", "install", "enable-now"),
        default="render",
        help="Service management action. Defaults to rendering the unit.",
    )
    notifications_service.add_argument(
        "--seconds",
        type=int,
        default=0,
        help="Listener duration for ExecStart. Use 0 for long-running service.",
    )
    notifications_service.add_argument(
        "--speak",
        action="store_true",
        help="Allow the service to speak notifications when rules allow it.",
    )
    notifications_service.add_argument("--store", help="Optional SQLite notification store path.")
    notifications_service.add_argument(
        "--execute",
        action="store_true",
        help="Actually write or enable/start the user service.",
    )

    plan = subparsers.add_parser(
        "plan",
        help="Decompose a natural-language instruction into tool-level actions.",
    )
    plan.add_argument("--instruction", required=True, help="Instruction to decompose.")

    route_plan = subparsers.add_parser(
        "route-plan",
        help="Route a natural-language instruction to local tools. Dry-run by default.",
    )
    route_plan.add_argument("--instruction", required=True, help="Instruction to route.")
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
        help="Optional SQLite notification store path. Defaults to ~/.local/share.",
    )


def _notification_status_choices() -> tuple[str, ...]:
    return ("all", *(status.value for status in NotificationStatus))


def _notification_store(args: argparse.Namespace) -> NotificationStore:
    return NotificationStore(args.store) if args.store else NotificationStore()


def _notification_status_filter(status: str) -> tuple[NotificationStatus, ...] | None:
    if status == "all":
        return None
    return (NotificationStatus(status),)


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

    if args.command == "fedora-open":
        result = FedoraNativeController().open_app(args.app, dry_run=not args.execute)
        print(render_fedora_control_result(result))
        return 0

    if args.command == "fedora-windows":
        print(render_fedora_control_result(FedoraNativeController().list_windows_command()))
        return 0

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

    if args.command == "notifications-dbus-command":
        print(DBusNotificationListenerPlan().render())
        return 0

    if args.command == "notifications-listen":
        store = _notification_store(args)
        result = DBusNotificationDaemon(center=NotificationCenter(store=store)).run(
            seconds=args.seconds,
            speak=args.speak,
            dry_run=not args.execute,
        )
        print(render_dbus_notification_daemon_result(result))
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
        result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
            event_id=args.event_id,
            reply_text=args.message,
            selector=args.selector,
            confirmed=args.confirmed,
            dry_run=not args.execute,
        )
        print(render_notification_reply_draft_result(result))
        return 0 if result.success else 1

    if args.command == "notifications-service":
        manager = NotificationUserServiceManager(
            spec=NotificationServiceSpec(
                project_dir=Path.cwd(),
                seconds=args.seconds,
                speak=args.speak,
                store_path=Path(args.store).expanduser() if args.store else None,
            )
        )
        if args.action == "install":
            result = manager.install(dry_run=not args.execute)
        elif args.action == "enable-now":
            result = manager.enable_now(dry_run=not args.execute)
        else:
            result = manager.render()
        print(render_notification_service_result(result))
        return 0 if result.success else 1

    if args.command == "plan":
        print(create_action_plan(args.instruction).render())
        return 0

    if args.command == "route-plan":
        plan = create_action_plan(args.instruction)
        context = ToolExecutionContext(
            dry_run=not args.execute,
            confirmed=args.confirmed,
        )
        print(render_tool_results(ToolRouter().route_plan(plan, context)))
        return 0

    if args.command == "browser-snapshot":
        interaction_plan = BrowserInteractionLoop().open_and_snapshot(
            args.url,
            dry_run=not args.execute,
        )
        print(render_browser_interaction_plan(interaction_plan))
        return 0

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
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
