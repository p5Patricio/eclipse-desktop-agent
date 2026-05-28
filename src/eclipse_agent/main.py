"""Minimal CLI entrypoint for Eclipse."""

from __future__ import annotations

import argparse

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
