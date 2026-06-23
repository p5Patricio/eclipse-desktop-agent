"""Smoke-plan and simulated readiness checks for a testable Eclipse agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eclipse_agent.notification_replies import NotificationReplyWorkflow
from eclipse_agent.notifications import (
    NotificationCenter,
    NotificationFocusMode,
    NotificationStore,
    build_notification_digest,
    create_notification_event,
)


@dataclass(frozen=True, kw_only=True)
class AgentSmokeStep:
    """A manual command/check for the first real Eclipse agent test."""

    name: str
    goal: str
    command: tuple[str, ...]
    expected: str


@dataclass(frozen=True, kw_only=True)
class AgentSmokeSimulationResult:
    """Result of the dependency-free simulated smoke flow."""

    success: bool
    messages: tuple[str, ...]
    store_path: Path


def build_agent_smoke_plan(*, store_path: str | Path | None = None) -> tuple[AgentSmokeStep, ...]:
    """Return the manual real-world test checklist for Eclipse notifications/replies."""

    store_args = ("--store", str(Path(store_path).expanduser())) if store_path else ()
    return (
        AgentSmokeStep(
            name="diagnostics",
            goal="Confirm local voice/browser dependencies are visible.",
            command=("python", "-m", "eclipse_agent", "diagnostics"),
            expected="Reports local TTS/STT/browser capability status.",
        ),
        AgentSmokeStep(
            name="game-mode",
            goal="Put Eclipse into non-interrupting game mode.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "notifications-intent",
                *store_args,
                "--text",
                "Eclipse, modo juego por una hora",
            ),
            expected="Mode changes to game and notifications are queued.",
        ),
        AgentSmokeStep(
            name="capture-or-simulate-notification",
            goal="Capture a real Windows notification or simulate one if testing offline.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "notifications-ingest",
                *store_args,
                "--app",
                "Google Chrome",
                "--summary",
                "Instagram",
                "--body",
                "Nuevo mensaje",
                "--source-window",
                "Instagram - Google Chrome",
            ),
            expected="Notification is stored as queued while in game mode.",
        ),
        AgentSmokeStep(
            name="summarize-pending",
            goal="Verify Eclipse can summarize pending notifications.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "notifications-summary",
                *store_args,
                "--mark-announced",
            ),
            expected="Shows Instagram/Messenger digest and marks events announced.",
        ),
        AgentSmokeStep(
            name="wake-command-pipeline",
            goal="Verify the post-STT wake pipeline can route a spoken notification intent.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "wake-command",
                *store_args,
                "--text",
                "Eclipse, dime qué llegó",
            ),
            expected="Routes the command through notification intents without using the mic.",
        ),
        AgentSmokeStep(
            name="wake-loop-microphone",
            goal="Run one bounded real microphone wake/listen/respond pass.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "wake-loop",
                *store_args,
                "--iterations",
                "1",
                "--wake-seconds",
                "4",
                "--execute",
            ),
            expected="Say 'Eclipse, dime qué llegó'; Eclipse transcribes and responds safely.",
        ),
        AgentSmokeStep(
            name="browser-snapshot",
            goal="Open/snapshot the web app in the controlled browser.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "browser-snapshot",
                "--url",
                "https://www.instagram.com/",
            ),
            expected="Returns an agent-browser command or real snapshot when executed.",
        ),
        AgentSmokeStep(
            name="reply-draft",
            goal="Fill a reply draft using auto-selected snapshot ref, without sending.",
            command=(
                "python",
                "-m",
                "eclipse_agent",
                "notifications-reply-draft",
                *store_args,
                "--event-id",
                "EVENT_ID",
                "--message",
                "Ahorita entro",
                "--snapshot-json",
                "/tmp/instagram-snapshot.json",
                "--auto-select",
                "--confirmed",
            ),
            expected="Fills a draft field only; no send action is executed.",
        ),
    )


def run_agent_smoke_simulation(*, store_path: str | Path) -> AgentSmokeSimulationResult:
    """Run a local dependency-free notification/reply simulation."""

    path = Path(store_path).expanduser()
    store = NotificationStore(path)
    messages: list[str] = []

    store.set_focus_mode(NotificationFocusMode.GAME)
    messages.append("mode=game")

    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        body="Nuevo mensaje",
        source_window="Instagram - Google Chrome",
    )
    ingest_result = NotificationCenter(store=store).ingest(event)
    messages.append(f"ingest={ingest_result.action.value}:{ingest_result.mode.value}")

    digest = build_notification_digest(store.list_pending())
    messages.append(f"digest_total={digest.total}")

    snapshot_json = json.dumps(
        {
            "success": True,
            "data": {
                "origin": "https://www.instagram.com/",
                "refs": {
                    "e1": {"role": "button", "name": "Enviar"},
                    "e2": {"role": "textbox", "name": "Mensaje"},
                },
                "snapshot": "smoke fixture",
            },
            "error": None,
        }
    )
    reply_result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event.id,
        reply_text="Ahorita entro",
        snapshot_output=snapshot_json,
        auto_select=True,
        confirmed=True,
    )
    selected_ref = reply_result.ref_selection.selected_ref if reply_result.ref_selection else None
    messages.append(f"reply={reply_result.success}:{selected_ref}")

    success = (
        ingest_result.action.value == "queue"
        and digest.total == 1
        and reply_result.success
        and selected_ref == "@e2"
    )
    return AgentSmokeSimulationResult(
        success=success,
        messages=tuple(messages),
        store_path=path,
    )


def render_agent_smoke_plan(steps: tuple[AgentSmokeStep, ...]) -> str:
    """Render smoke-plan checklist for CLI output."""

    lines = ["Eclipse agent smoke plan:"]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step.name}: {step.goal}")
        lines.append(f"   command: {_shell_join(step.command)}")
        lines.append(f"   expected: {step.expected}")
    return "\n".join(lines)


def render_agent_smoke_simulation(result: AgentSmokeSimulationResult) -> str:
    """Render simulation output."""

    marker = "ok" if result.success else "failed"
    lines = [f"Eclipse smoke simulation [{marker}] store={result.store_path}"]
    lines.extend(f"- {message}" for message in result.messages)
    return "\n".join(lines)


def _shell_join(command: tuple[str, ...]) -> str:
    import shlex

    return shlex.join(command)
