"""Route planned Eclipse actions through local MCP tools with safety gates."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

from eclipse_agent.audit import AuditEntry, AuditLog
from eclipse_agent.browser_control import (
    BrowserControlRequest,
    BrowserControlResult,
    BrowserControlService,
    redact_browser_audit_payload,
)
from eclipse_agent.killswitch import KillSwitch
from eclipse_agent.pal.factory import PlatformFactory
from eclipse_agent.planner import (
    ActionKind,
    ActionPlan,
    AvailableTool,
    PlannedAction,
    VisionAdapter,
    VisionAnalysisResult,
)
from eclipse_agent.safety import RiskLevel, evaluate_risk, redact_screenshot


@dataclass(frozen=True)
class ToolExecutionContext:
    """Execution policy for a tool-routing pass."""

    dry_run: bool = True
    confirmed: bool = False
    allow_high_risk: bool = False


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result of routing or executing a planned action."""

    action_id: str
    tool_name: str
    success: bool
    executed: bool
    requires_confirmation: bool
    message: str
    command: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    structured_content: dict[str, Any] | None = None


@dataclass(frozen=True)
class MCPServerConfig:
    """STDIO MCP server process configuration."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


@dataclass(frozen=True)
class MCPToolDefinition:
    """A discovered MCP tool with Eclipse routing metadata."""

    name: str
    server_name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    action_kinds: tuple[ActionKind, ...] = ()
    risk_level: RiskLevel = RiskLevel.MEDIUM

    @property
    def qualified_name(self) -> str:
        """Return a stable server-qualified tool name."""

        return f"{self.server_name}.{self.name}"

    def to_available_tool(self) -> AvailableTool:
        """Convert this MCP tool to the planner-facing schema."""

        return AvailableTool(
            name=self.qualified_name,
            description=self.description,
            input_schema=self.input_schema,
            action_kinds=self.action_kinds,
            risk_level=self.risk_level,
            server_name=self.server_name,
        )


class MCPClientProtocol(Protocol):
    """Protocol for MCP clients used by the router and tests."""

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        """Return tools available from configured MCP servers."""

    def call_tool(
        self,
        tool: MCPToolDefinition,
        arguments: dict[str, Any],
    ) -> object:
        """Call a discovered MCP tool and return the raw SDK result."""


class VisionAdapterProtocol(Protocol):
    """Protocol for screenshot analysis adapters."""

    def analyze_image(self, image_path: str | Path, *, prompt: str) -> VisionAnalysisResult:
        """Analyze a screenshot path and return a vision result."""


@dataclass(frozen=True)
class NativeToolResult:
    """Minimal result object returned by NativeMCPClient."""

    isError: bool = False
    _message: str = ""
    structuredContent: dict[str, Any] | None = None

    @property
    def content(self) -> list[dict[str, str]]:
        return [{"text": self._message}]


_KNOWN_URLS: dict[str, str] = {
    "youtube": "https://www.youtube.com/",
    "youtube music": "https://music.youtube.com/",
    "instagram": "https://www.instagram.com/",
    "messenger": "https://www.messenger.com/",
    "gmail": "https://mail.google.com/",
    "github": "https://github.com/",
    "google": "https://www.google.com/",
}

_DESKTOP_APP_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "browser": ("https://www.google.com/",),
    "terminal": ("wt.exe",),
    "files": ("explorer.exe",),
}


class NativeMCPClient:
    """Execute basic Eclipse actions natively without MCP servers.

    Handles open_web_app and browser_search via the default browser, and
    screenshot via the Windows screen-capture layer. Used as the default router
    backend for WakeRuntime so spoken commands work out of the box.
    """

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        return (
            MCPToolDefinition(
                name="open_url",
                server_name="native",
                description="Open a URL or web app in the default browser",
                action_kinds=(ActionKind.OPEN_WEB_APP, ActionKind.BROWSER_SEARCH),
                risk_level=RiskLevel.MEDIUM,
            ),
            MCPToolDefinition(
                name="google_search",
                server_name="native",
                description="Open a Google search in the default browser",
                action_kinds=(ActionKind.GOOGLE_SEARCH,),
                risk_level=RiskLevel.MEDIUM,
            ),
            MCPToolDefinition(
                name="open_desktop_app",
                server_name="native",
                description="Open an allowlisted desktop application",
                action_kinds=(ActionKind.OPEN_DESKTOP_APP,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="capture_screenshot",
                server_name="native",
                description="Capture a screenshot of the screen",
                action_kinds=(ActionKind.SCREENSHOT,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="system_control",
                server_name="native",
                description="Control system volume, media playback, lock, and battery",
                action_kinds=(ActionKind.SYSTEM_CONTROL,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="read_clipboard",
                server_name="native",
                description="Read the current clipboard text",
                action_kinds=(ActionKind.READ_CLIPBOARD,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="answer_question",
                server_name="native",
                description="Answer a question with the configured LLM provider",
                action_kinds=(ActionKind.ANSWER_QUESTION,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="query_documents",
                server_name="native",
                description="Answer a question grounded in the user's ingested documents",
                action_kinds=(ActionKind.QUERY_DOCUMENTS,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="summarize_inbox",
                server_name="native",
                description="Read and summarize the user's email inbox (read-only)",
                action_kinds=(ActionKind.SUMMARIZE_INBOX,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="read_agenda",
                server_name="native",
                description="Read the user's upcoming calendar agenda (read-only)",
                action_kinds=(ActionKind.READ_AGENDA,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="set_reminder",
                server_name="native",
                description="Set a reminder or timer",
                action_kinds=(ActionKind.SET_REMINDER,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="play_media",
                server_name="native",
                description="Search and play media in a web app like YouTube Music",
                action_kinds=(ActionKind.PLAY_MEDIA,),
                risk_level=RiskLevel.MEDIUM,
            ),
            MCPToolDefinition(
                name="add_routine",
                server_name="native",
                description="Schedule a recurring proactive routine",
                action_kinds=(ActionKind.ADD_ROUTINE,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="remember_fact",
                server_name="native",
                description="Remember a fact or preference the user shared",
                action_kinds=(ActionKind.REMEMBER_FACT,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="recall_memory",
                server_name="native",
                description="Recall a remembered fact or preference",
                action_kinds=(ActionKind.RECALL_MEMORY,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="screen_ask",
                server_name="native",
                description="Capture the screen and analyze it with the vision model",
                action_kinds=(ActionKind.SCREEN_ASK,),
                risk_level=RiskLevel.MEDIUM,
            ),
            MCPToolDefinition(
                name="weather_query",
                server_name="native",
                description="Fetch current weather conditions from Open-Meteo",
                action_kinds=(ActionKind.WEATHER_QUERY,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="morning_briefing",
                server_name="native",
                description="Compose and speak the morning briefing",
                action_kinds=(ActionKind.MORNING_BRIEFING,),
                risk_level=RiskLevel.LOW,
            ),
            MCPToolDefinition(
                name="send_email",
                server_name="native",
                description="Send an email via SMTP (requires confirmation)",
                action_kinds=(ActionKind.SEND_EMAIL,),
                risk_level=RiskLevel.HIGH,
            ),
        )

    def call_tool(self, tool: MCPToolDefinition, arguments: dict[str, Any]) -> NativeToolResult:
        if tool.name == "open_url":
            return self._open_url(arguments)
        if tool.name == "google_search":
            return self._google_search(arguments)
        if tool.name == "open_desktop_app":
            return self._open_desktop_app(arguments)
        if tool.name == "capture_screenshot":
            return self._capture_screenshot(arguments)
        if tool.name == "system_control":
            return self._system_control(arguments)
        if tool.name == "read_clipboard":
            return self._read_clipboard(arguments)
        if tool.name == "answer_question":
            return self._answer_question(arguments)
        if tool.name == "query_documents":
            return self._query_documents(arguments)
        if tool.name == "summarize_inbox":
            return self._summarize_inbox(arguments)
        if tool.name == "read_agenda":
            return self._read_agenda(arguments)
        if tool.name == "set_reminder":
            return self._set_reminder(arguments)
        if tool.name == "play_media":
            return self._play_media(arguments)
        if tool.name == "add_routine":
            return self._add_routine(arguments)
        if tool.name == "remember_fact":
            return self._remember_fact(arguments)
        if tool.name == "recall_memory":
            return self._recall_memory(arguments)
        if tool.name == "screen_ask":
            return self._screen_ask(arguments)
        if tool.name == "weather_query":
            return self._weather_query(arguments)
        if tool.name == "morning_briefing":
            return self._morning_briefing(arguments)
        if tool.name == "send_email":
            return self._send_email(arguments)
        return NativeToolResult(isError=True, _message=f"Unknown native tool: {tool.name}")

    def _open_url(self, arguments: dict[str, Any]) -> NativeToolResult:
        url = str(arguments.get("url", "") or arguments.get("target", "")).strip()
        if not url:
            return NativeToolResult(isError=True, _message="No URL or target provided.")
        resolved = self._resolve_url(url)
        try:
            launcher = PlatformFactory.get_app_launcher()
            res = launcher.launch(resolved, dry_run=False)
            if res.success:
                return NativeToolResult(_message=f"Opened {resolved} in the default browser.")
            return NativeToolResult(isError=True, _message=res.message)
        except Exception as exc:  # noqa: BLE001
            return NativeToolResult(isError=True, _message=str(exc))

    def _google_search(self, arguments: dict[str, Any]) -> NativeToolResult:
        query = str(arguments.get("query", "") or arguments.get("target", "")).strip()
        if not query or query.casefold() == "google":
            return _native_failure(
                action_type="google_search",
                target=query or "Google",
                reason="Tell me what you want to search for.",
            )
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        try:
            launcher = PlatformFactory.get_app_launcher()
            res = launcher.launch(url, dry_run=False)
            if res.success:
                return _native_success(
                    action_type="google_search",
                    target=query,
                    message=f"Opened Google search for {query}.",
                )
            return _native_failure(
                action_type="google_search",
                target=query,
                reason=res.message,
            )
        except Exception as exc:  # noqa: BLE001
            return _native_failure(
                action_type="google_search",
                target=query,
                reason=f"Could not search for {query}: {exc}",
            )

    def _open_desktop_app(self, arguments: dict[str, Any]) -> NativeToolResult:
        raw_target = str(arguments.get("target", "") or "").strip().casefold()
        raw_app = str(arguments.get("app_name", "") or "").strip().casefold()
        app_name = _resolve_app_alias(raw_target) or _resolve_app_alias(raw_app)
        requested = app_name or raw_target or raw_app or "app"
        if app_name is None:
            return _native_failure(
                action_type="desktop_open_app",
                target=requested,
                reason=f"{requested} is not in the supported app list.",
                next_step="Try browser, terminal, or files.",
            )
        try:
            launcher = PlatformFactory.get_app_launcher()
            res = launcher.launch(app_name, dry_run=False)
            if res.success:
                return _native_success(
                    action_type="desktop_open_app",
                    target=app_name,
                    message=res.message or f"Opened {app_name}.",
                )
            return _native_failure(
                action_type="desktop_open_app",
                target=app_name,
                reason=res.message or f"Could not launch {app_name}.",
            )
        except Exception as exc:  # noqa: BLE001
            return _native_failure(
                action_type="desktop_open_app",
                target=app_name,
                reason=f"Could not launch {app_name}: {exc}",
            )

    def _capture_screenshot(self, arguments: dict[str, Any]) -> NativeToolResult:
        output = str(arguments.get("output_path", "") or "").strip()
        if not output:
            output = str(Path(tempfile.gettempdir()) / "eclipse-screenshot.png")
        try:
            capture_device = PlatformFactory.get_screen_capture()
            res = capture_device.capture(output_path=output, dry_run=False)
            success = getattr(res, "success", True)
            msg = getattr(res, "message", f"Screenshot saved to {output}.")
            if not success:
                return NativeToolResult(isError=True, _message=msg)
            redact_screenshot(output)
            return NativeToolResult(_message=f"Screenshot saved to {output}.")
        except Exception as exc:  # noqa: BLE001
            return NativeToolResult(isError=True, _message=str(exc))

    def _system_control(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.system_control import SystemAction

        raw = str(arguments.get("system_action", "") or arguments.get("target", "")).strip()
        try:
            action = SystemAction(raw)
        except ValueError:
            return _native_failure(
                action_type="system_control",
                target=raw or "system",
                reason=f"{raw or 'that'} is not a supported system action.",
            )
        try:
            controller = PlatformFactory.get_system_controller()
            result = controller.run(action, dry_run=False)
        except Exception as exc:  # noqa: BLE001
            return _native_failure(
                action_type="system_control",
                target=action.value,
                reason=f"Could not run {action.value}: {exc}",
            )
        if result.success:
            return _native_success(
                action_type="system_control",
                target=action.value,
                message=result.message,
                extra_facts={"detail": result.message},
            )
        return _native_failure(
            action_type="system_control",
            target=action.value,
            reason=result.message,
        )

    def _set_reminder(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.reminders import ReminderStore, expires_after_seconds

        text = str(arguments.get("reminder_text", "") or arguments.get("target", "")).strip()
        try:
            delay = int(arguments.get("delay_seconds") or 0)
        except (TypeError, ValueError):
            delay = 0
        if delay <= 0:
            return _native_failure(
                action_type="set_reminder",
                target="reminder",
                reason="Tell me in how long, like in ten minutes.",
            )
        ReminderStore().add(text or "recordatorio", expires_after_seconds(delay))
        spoken = "Listo, te lo recuerdo."
        return _native_success(
            action_type="set_reminder",
            target="reminder",
            message=spoken,
            extra_facts={"spoken": spoken},
        )

    def _answer_question(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.answer import answer_question_from_env

        question = str(arguments.get("question", "") or arguments.get("target", "")).strip()
        if not question:
            return _native_failure(
                action_type="answer_question",
                target="answer",
                reason="Tell me what you want to know.",
            )
        result = answer_question_from_env(question)
        if result.success:
            return _native_success(
                action_type="answer_question",
                target="answer",
                message=result.answer,
                extra_facts={"spoken": result.answer},
            )
        return _native_failure(
            action_type="answer_question",
            target="answer",
            reason=result.message,
        )

    def _read_agenda(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.calendar_agenda import read_agenda

        result = read_agenda()
        if result.success:
            return _native_success(
                action_type="read_agenda",
                target="agenda",
                message=result.message,
                extra_facts={"spoken": result.message},
            )
        return _native_failure(
            action_type="read_agenda",
            target="agenda",
            reason=result.message,
        )

    def _summarize_inbox(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.email_inbox import summarize_inbox

        result = summarize_inbox()
        if result.success:
            return _native_success(
                action_type="summarize_inbox",
                target="inbox",
                message=result.summary,
                extra_facts={"spoken": result.summary},
            )
        return _native_failure(
            action_type="summarize_inbox",
            target="inbox",
            reason=result.message,
        )

    def _query_documents(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.documents import DocumentStore, answer_from_documents

        question = str(arguments.get("question", "") or arguments.get("target", "")).strip()
        if not question:
            return _native_failure(
                action_type="query_documents",
                target="documents",
                reason="Tell me what to look up in your documents.",
            )
        result = answer_from_documents(question, DocumentStore())
        if result.success:
            return _native_success(
                action_type="query_documents",
                target="documents",
                message=result.answer,
                extra_facts={"spoken": result.answer},
            )
        return _native_failure(
            action_type="query_documents",
            target="documents",
            reason=result.message,
        )

    def _read_clipboard(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.clipboard import WindowsClipboard

        result = WindowsClipboard().read()
        if not result.success:
            return _native_failure(
                action_type="read_clipboard",
                target="clipboard",
                reason=result.message,
            )
        spoken = result.text or "The clipboard is empty."
        return _native_success(
            action_type="read_clipboard",
            target="clipboard",
            message=spoken,
            extra_facts={"spoken": spoken},
        )

    def _play_media(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.media_playback import open_media_search

        query = str(arguments.get("query", "") or "").strip()
        app_name = str(arguments.get("app_name", "") or "YouTube Music").strip()
        if not query:
            return _native_failure(
                action_type="play_media",
                target=app_name,
                reason="Tell me what you want to play.",
            )
        result = open_media_search(
            app_name,
            query,
            dry_run=False,
            requested_interaction=str(
                arguments.get("requested_interaction")
                or arguments.get("interaction")
                or arguments.get("browser_action")
                or arguments.get("action")
                or ""
            ),
            confirmed=_bool_parameter(arguments.get("confirmed"))
            or _bool_parameter(arguments.get("_confirmed")),
        )
        if result.success:
            return _native_success(
                action_type="play_media",
                target=app_name,
                message=result.message,
                extra_facts={"spoken": result.message},
            )
        return _native_failure(
            action_type="play_media",
            target=app_name,
            reason=result.message,
        )

    def _add_routine(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.routines import RoutineAction, RoutineStore, ScheduleKind

        message = str(arguments.get("routine_message", "") or arguments.get("target", "")).strip()
        if not message:
            return _native_failure(
                action_type="add_routine",
                target="routine",
                reason="Tell me what to do, like 'cada mañana decime el resumen'.",
            )
        try:
            kind = ScheduleKind(str(arguments.get("schedule_kind", "")))
            action = RoutineAction(str(arguments.get("routine_action", "say")))
        except ValueError:
            return _native_failure(
                action_type="add_routine",
                target="routine",
                reason="That schedule is not supported yet.",
            )
        value = str(arguments.get("schedule_value", "")).strip()
        RoutineStore().add(message, kind, value, action=action)
        if kind is ScheduleKind.DAILY:
            spoken = f"Listo, te lo digo cada día a las {value}."
        else:
            spoken = "Listo, lo hago cada tanto."
        return _native_success(
            action_type="add_routine",
            target="routine",
            message=spoken,
            extra_facts={"spoken": spoken},
        )

    def _remember_fact(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.memory import MemoryStore

        key = str(arguments.get("memory_key", "") or "").strip()
        value = str(arguments.get("memory_value", "") or arguments.get("target", "")).strip()
        if not key or not value:
            return _native_failure(
                action_type="remember_fact",
                target=key or "memory",
                reason="Tell me what to remember, like 'mi nombre es Patricio'.",
            )
        MemoryStore().remember(key, value)
        spoken = "Listo, lo voy a recordar."
        return _native_success(
            action_type="remember_fact",
            target=key,
            message=spoken,
            extra_facts={"spoken": spoken},
        )

    def _recall_memory(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.memory import MemoryStore, spoken_fact, spoken_facts

        key = str(arguments.get("memory_key", "") or "").strip()
        store = MemoryStore()
        if not key:
            spoken = spoken_facts(store.list_all())
            return _native_success(
                action_type="recall_memory",
                target="memory",
                message=spoken,
                extra_facts={"spoken": spoken},
            )
        fact = store.recall(key)
        if fact is None:
            matches = store.search(key)
            fact = matches[0] if matches else None
        if fact is None:
            spoken = f"No tengo guardado tu {key} todavía."
        else:
            spoken = spoken_fact(fact.key, fact.value)
        return _native_success(
            action_type="recall_memory",
            target=key,
            message=spoken,
            extra_facts={"spoken": spoken},
        )

    def _screen_ask(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.screen_ask import ask_about_screen

        prompt = str(arguments.get("vision_prompt", "") or arguments.get("prompt", "")).strip()
        window_title = str(arguments.get("window_title", "") or "").strip() or None
        result = ask_about_screen(prompt or None, window_title)  # type: ignore[arg-type]
        if result.success:
            return _native_success(
                action_type="screen_ask",
                target="screen",
                message=result.answer,
                extra_facts={"spoken": result.answer},
            )
        return _native_failure(
            action_type="screen_ask",
            target="screen",
            reason=result.error,
        )

    def _weather_query(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.weather import WeatherConfig, get_weather, render_weather

        try:
            import os
            lat = float(arguments.get("latitude") or os.environ.get("ECLIPSE_WEATHER_LAT") or 0.0)
            lon = float(arguments.get("longitude") or os.environ.get("ECLIPSE_WEATHER_LON") or 0.0)
        except (TypeError, ValueError):
            lat, lon = 0.0, 0.0

        config = WeatherConfig(latitude=lat, longitude=lon)
        result = get_weather(config)
        spoken = render_weather(result)
        if result.success:
            return _native_success(
                action_type="weather_query",
                target="weather",
                message=spoken,
                extra_facts={"spoken": spoken},
            )
        return _native_failure(
            action_type="weather_query",
            target="weather",
            reason=result.error,
        )

    def _morning_briefing(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.morning_briefing import BriefingConfig, compose_briefing, render_briefing

        config = BriefingConfig()
        result = compose_briefing(config)
        spoken = render_briefing(result)
        if result.success:
            return _native_success(
                action_type="morning_briefing",
                target="briefing",
                message=spoken,
                extra_facts={"spoken": spoken},
            )
        return _native_failure(
            action_type="morning_briefing",
            target="briefing",
            reason=result.error,
        )

    def _send_email(self, arguments: dict[str, Any]) -> NativeToolResult:
        from eclipse_agent.email_sender import EmailSender, SmtpConfigError

        to = str(arguments.get("to", "") or "").strip()
        subject = str(arguments.get("subject", "") or "").strip()
        body = str(arguments.get("body", "") or "").strip()
        confirmed = bool(arguments.get("confirmed", False))

        if not confirmed:
            preview = f"Preview: To={to}, Subject={subject}"
            return _native_success(
                action_type="send_email",
                target=to or "email",
                message=preview,
                extra_facts={"spoken": "Email ready to send. Confirm to proceed."},
            )

        if not to:
            return _native_failure(
                action_type="send_email",
                target="email",
                reason="Recipient address is required.",
            )

        try:
            EmailSender().send(to=to, subject=subject, body=body)
            spoken = f"Email sent to {to}."
            return _native_success(
                action_type="send_email",
                target=to,
                message=spoken,
                extra_facts={"spoken": spoken},
            )
        except SmtpConfigError as exc:
            return _native_failure(
                action_type="send_email",
                target=to,
                reason=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return _native_failure(
                action_type="send_email",
                target=to,
                reason=f"Failed to send email: {exc}",
            )

    @staticmethod
    def _resolve_url(target: str) -> str:
        lower = target.casefold().strip()
        if lower in _KNOWN_URLS:
            return _KNOWN_URLS[lower]
        if re.match(r"^https?://", lower):
            return target
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", lower):
            return f"https://{target}"
        return f"https://www.google.com/search?q={target.replace(' ', '+')}"


class MCPToolClient:
    """Official MCP SDK client facade for local STDIO servers."""

    def __init__(self, server_configs: tuple[MCPServerConfig, ...] = ()) -> None:
        self.server_configs = server_configs

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        """Synchronously discover tools from all configured STDIO MCP servers."""

        if not self.server_configs:
            return ()
        return _run_async(self.discover_tools_async())

    async def discover_tools_async(self) -> tuple[MCPToolDefinition, ...]:
        """Discover tools from all configured STDIO MCP servers."""

        if not self.server_configs:
            return ()
        tools: list[MCPToolDefinition] = []
        for config in self.server_configs:
            tools.extend(await self._discover_server_tools(config))
        return tuple(tools)

    def call_tool(self, tool: MCPToolDefinition, arguments: dict[str, Any]) -> object:
        """Synchronously call an MCP tool on its source server."""

        return _run_async(self.call_tool_async(tool, arguments))

    async def call_tool_async(
        self,
        tool: MCPToolDefinition,
        arguments: dict[str, Any],
    ) -> object:
        """Call an MCP tool on its source server."""

        config = self._server_config_for(tool.server_name)
        ClientSession, StdioServerParameters, stdio_client = _require_mcp_sdk()
        server_params = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env=_merged_env(config.env),
            cwd=config.cwd,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool.name, arguments=arguments)

    async def _discover_server_tools(
        self,
        config: MCPServerConfig,
    ) -> tuple[MCPToolDefinition, ...]:
        ClientSession, StdioServerParameters, stdio_client = _require_mcp_sdk()
        server_params = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env=_merged_env(config.env),
            cwd=config.cwd,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                return tuple(_tool_from_sdk(config.name, tool) for tool in response.tools)

    def _server_config_for(self, server_name: str) -> MCPServerConfig:
        for config in self.server_configs:
            if config.name == server_name:
                return config
        raise ValueError(f"No MCP server is configured for {server_name!r}.")


class CompositeMCPClient:
    """Expose native tools and external MCP servers through one client.

    Native tools (``server_name == "native"``) always work; a failing MCP server
    never takes them down. ``call_tool`` routes to the owner of the tool.
    """

    def __init__(self, native: MCPClientProtocol, mcp: MCPClientProtocol) -> None:
        self.native = native
        self.mcp = mcp

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        native_tools = self.native.discover_tools()
        try:
            mcp_tools = self.mcp.discover_tools()
        except Exception:  # noqa: BLE001 - a broken MCP server must not hide native tools
            mcp_tools = ()
        return (*native_tools, *mcp_tools)

    def call_tool(self, tool: MCPToolDefinition, arguments: dict[str, Any]) -> object:
        if tool.server_name == "native":
            return self.native.call_tool(tool, arguments)
        return self.mcp.call_tool(tool, arguments)


class ToolRouter:
    """Map planned actions to discovered MCP tools with safety gates."""

    def __init__(
        self,
        *,
        mcp_client: MCPClientProtocol | None = None,
        static_tools: tuple[MCPToolDefinition, ...] = (),
        vision_adapter: VisionAdapterProtocol | None = None,
        audit_log: AuditLog | None = None,
        kill_switch: KillSwitch | None = None,
        browser_control_service: BrowserControlService | None = None,
    ) -> None:
        self.mcp_client = mcp_client or MCPToolClient()
        self.static_tools = static_tools
        self.vision_adapter = vision_adapter or VisionAdapter()
        self.audit_log = audit_log
        self.kill_switch = kill_switch
        self.browser_control_service = browser_control_service
        self._tool_cache: tuple[MCPToolDefinition, ...] | None = None

    @classmethod
    def from_config_file(cls, path: str | Path | None) -> ToolRouter:
        """Create a router from an optional MCP server configuration file."""

        return cls(mcp_client=MCPToolClient(load_mcp_server_configs(path)))

    def discover_tools(self, *, refresh: bool = False) -> tuple[MCPToolDefinition, ...]:
        """Return cached or freshly discovered MCP tools."""

        if self._tool_cache is None or refresh:
            discovered = self.mcp_client.discover_tools()
            self._tool_cache = (*self.static_tools, *discovered)
        return self._tool_cache

    def planner_tools(self, *, refresh: bool = False) -> tuple[AvailableTool, ...]:
        """Return planner-facing tool descriptors."""

        return tuple(tool.to_available_tool() for tool in self.discover_tools(refresh=refresh))

    def route_plan(
        self,
        plan: ActionPlan,
        context: ToolExecutionContext | None = None,
    ) -> tuple[ToolExecutionResult, ...]:
        """Route every action in a plan through discovered MCP tools."""

        context = context or ToolExecutionContext()
        return tuple(self.route_action(action, context) for action in plan.actions)

    def route_action(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """Route one action, honoring the kill switch and auditing the outcome."""

        if self.kill_switch is not None and self.kill_switch.is_engaged():
            result = ToolExecutionResult(
                action_id=action.id,
                tool_name="kill_switch",
                success=False,
                executed=False,
                requires_confirmation=False,
                message="Eclipse is paused; resume it to act.",
                metadata={"target": action.target, "kind": action.kind.value},
            )
            self._record_audit(action, result, "killed")
            return result

        result = self._route_action_inner(action, context)
        self._record_audit(action, result, _audit_status(result))
        return result

    def _record_audit(
        self, action: PlannedAction, result: ToolExecutionResult, status: str
    ) -> None:
        if self.audit_log is None:
            return
        try:
            self.audit_log.record(
                AuditEntry(
                    action_kind=action.kind.value,
                    target=_audit_target_for_result(action, result),
                    risk_level=action.risk_level.value,
                    status=status,
                    tool_name=result.tool_name,
                    detail=_audit_detail_for_result(result),
                )
            )
        except Exception:  # noqa: BLE001 - auditing must never break routing
            pass

    def _route_action_inner(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """Route one planned action to a discovered MCP tool."""

        blocked = self._blocked_by_confirmation(action, context)
        if blocked:
            return blocked

        browser_control_result = self._maybe_route_browser_control(action, context)
        if browser_control_result is not None:
            return browser_control_result

        tool = self._select_tool(action)
        if tool is None:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name=action.tool_name or "unavailable_mcp_tool",
                success=False,
                executed=False,
                requires_confirmation=True,
                message="No discovered MCP tool matches this planned action.",
                metadata={"target": action.target, "kind": action.kind.value},
            )

        arguments = {"target": action.target, **action.parameters}
        if tool.server_name == "native":
            arguments["_confirmed"] = context.confirmed
        if context.dry_run:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name=tool.qualified_name,
                success=True,
                executed=False,
                requires_confirmation=False,
                message="Prepared MCP tool call; draft mode did not execute it.",
                command=_server_command_for(self.mcp_client, tool),
                metadata=_string_metadata(action, arguments),
            )

        try:
            raw_result = self.mcp_client.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001
            return ToolExecutionResult(
                action_id=action.id,
                tool_name=tool.qualified_name,
                success=False,
                executed=False,
                requires_confirmation=False,
                message=f"MCP tool call failed: {exc}",
                command=_server_command_for(self.mcp_client, tool),
                metadata=_string_metadata(action, arguments),
            )

        structured_content = _structured_content(raw_result)
        message = _render_mcp_call_result(raw_result)
        success = not bool(getattr(raw_result, "isError", False))
        vision_result = self._maybe_analyze_screenshot(
            action=action,
            tool=tool,
            arguments=arguments,
            structured_content=structured_content,
            tool_success=success,
        )
        if vision_result is not None:
            structured_content = _merge_vision_result(structured_content, vision_result)
            success = success and vision_result.success
            if vision_result.success:
                message = f"{message}\nVision analysis: {vision_result.text}"
            else:
                message = f"{message}\nVision analysis failed: {vision_result.message}"

        return ToolExecutionResult(
            action_id=action.id,
            tool_name=tool.qualified_name,
            success=success,
            executed=True,
            requires_confirmation=False,
            message=message,
            command=_server_command_for(self.mcp_client, tool),
            metadata=_string_metadata(action, arguments),
            structured_content=structured_content,
        )

    def _blocked_by_confirmation(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult | None:
        decision = evaluate_risk(action.risk_level)
        if not decision.allowed:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="safety_policy",
                success=False,
                executed=False,
                requires_confirmation=decision.requires_confirmation,
                message=decision.reason,
                metadata={"risk_level": action.risk_level.value},
            )

        if decision.requires_confirmation and not context.confirmed:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="safety_policy",
                success=False,
                executed=False,
                requires_confirmation=True,
                message=decision.reason,
                metadata={"risk_level": action.risk_level.value},
            )
        return None

    def _select_tool(self, action: PlannedAction) -> MCPToolDefinition | None:
        tools = self.discover_tools()
        if action.kind in {
            ActionKind.OPEN_WEB_APP,
            ActionKind.BROWSER_SEARCH,
            ActionKind.GOOGLE_SEARCH,
        } and not _requires_rich_browser_control(action):
            native = _native_browser_tool_for(action, tools)
            if native is not None:
                return native
        if action.tool_name:
            for tool in tools:
                if action.tool_name in {tool.name, tool.qualified_name}:
                    return tool
        for tool in tools:
            if action.kind in tool.action_kinds:
                return tool
        return None

    def _maybe_route_browser_control(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult | None:
        request = _rich_browser_control_request(action)
        if request is None:
            return None

        service = self.browser_control_service or BrowserControlService(
            audit_log=self.audit_log
        )
        decision = service.evaluate_request(request, confirmed=context.confirmed)
        return _browser_control_execution_result(action, decision)

    def _maybe_analyze_screenshot(
        self,
        *,
        action: PlannedAction,
        tool: MCPToolDefinition,
        arguments: dict[str, Any],
        structured_content: dict[str, Any] | None,
        tool_success: bool,
    ) -> VisionAnalysisResult | None:
        if not tool_success or not _requires_vision(action, tool):
            return None
        image_path = _extract_image_path(action, arguments, structured_content)
        if image_path is None:
            return VisionAnalysisResult(
                success=False,
                model="unavailable",
                image_path=Path(""),
                message="Screenshot action did not return an image path for vision analysis.",
            )
        return self.vision_adapter.analyze_image(
            image_path,
            prompt=_vision_prompt_for(action),
        )


def load_mcp_server_configs(path: str | Path | None) -> tuple[MCPServerConfig, ...]:
    """Load MCP server configs from a JSON file.

    The expected shape is:
    {"servers": [{"name": "browser", "command": "python", "args": ["server.py"]}]}
    """

    if path is None:
        return ()
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return ()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    servers = payload.get("servers", [])
    configs: list[MCPServerConfig] = []
    for server in servers:
        configs.append(
            MCPServerConfig(
                name=str(server["name"]),
                command=str(server["command"]),
                args=tuple(str(arg) for arg in server.get("args", ())),
                env={str(key): str(value) for key, value in server.get("env", {}).items()},
                cwd=str(server["cwd"]) if server.get("cwd") else None,
            )
        )
    return tuple(configs)


def render_tool_results(results: tuple[ToolExecutionResult, ...]) -> str:
    """Render tool-routing results for CLI output."""

    lines = ["Eclipse tool routing:"]
    for result in results:
        status = "executed" if result.executed else "prepared"
        if not result.success:
            status = "blocked" if result.requires_confirmation else "failed"
        lines.append(f"- {result.action_id} [{status}] {result.tool_name}: {result.message}")
        if result.command:
            lines.append(f"  command: {shlex_join(result.command)}")
        if result.metadata:
            lines.append(f"  metadata: {json.dumps(result.metadata, sort_keys=True)}")
    return "\n".join(lines)


def _resolve_app_alias(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9_-]+", " ", value.casefold()).strip()
    normalized = re.sub(r"[\s_-]+", " ", normalized)
    aliases = {app_name: app_name for app_name in _DESKTOP_APP_ALLOWLIST}
    return aliases.get(normalized)


def _audit_status(result: ToolExecutionResult) -> str:
    if result.executed:
        return "executed"
    if result.requires_confirmation:
        return "blocked"
    if not result.success:
        return "failed"
    return "prepared"


def _native_browser_tool_for(
    action: PlannedAction,
    tools: tuple[MCPToolDefinition, ...],
) -> MCPToolDefinition | None:
    expected_names = {
        ActionKind.OPEN_WEB_APP: {"open_url"},
        ActionKind.BROWSER_SEARCH: {"open_url"},
        ActionKind.GOOGLE_SEARCH: {"google_search"},
    }.get(action.kind, set())
    for tool in tools:
        if tool.server_name == "native" and tool.name in expected_names:
            return tool
    return None


def _rich_browser_control_request(action: PlannedAction) -> BrowserControlRequest | None:
    if not _is_browser_action(action):
        return None
    parameters = action.parameters
    if not _requires_rich_browser_control(action):
        return None
    browser_action = str(
        parameters.get("browser_action")
        or parameters.get("action")
        or _action_name_for_browser_control(action)
    )
    return BrowserControlRequest(
        intent=action.kind.value,
        url=str(parameters.get("url") or parameters.get("target_url") or action.target or ""),
        action=browser_action,
        selector=str(parameters.get("selector") or ""),
        text=str(parameters.get("text") or parameters.get("value") or ""),
        sensitive=_bool_parameter(parameters.get("sensitive"))
        or action.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        requires_live_browser=True,
        metadata={
            "planned_action_id": action.id,
            "tool_name": action.tool_name or "",
        },
    )


def _is_browser_action(action: PlannedAction) -> bool:
    if action.kind in {
        ActionKind.OPEN_WEB_APP,
        ActionKind.BROWSER_SEARCH,
        ActionKind.GOOGLE_SEARCH,
    }:
        return True
    haystack = " ".join(
        (
            action.kind.value,
            action.tool_name or "",
            action.description,
            action.target,
            " ".join(f"{key} {value}" for key, value in action.parameters.items()),
        )
    ).casefold()
    return any(
        token in haystack
        for token in (
            "browser",
            "chrome",
            "devtools",
            "page",
            "tab",
            "snapshot",
            "selector",
        )
    )


def _requires_rich_browser_control(action: PlannedAction) -> bool:
    parameters = action.parameters
    if _bool_parameter(parameters.get("rich_browser_control")):
        return True
    if _bool_parameter(parameters.get("requires_live_browser")):
        return True
    if any(
        key in parameters
        for key in (
            "selector",
            "script",
            "expression",
            "snapshot",
            "inspect",
        )
    ):
        return True
    browser_action = str(parameters.get("browser_action") or parameters.get("action") or "").casefold()
    return any(
        token in browser_action
        for token in (
            "click",
            "fill",
            "type",
            "submit",
            "send",
            "snapshot",
            "inspect",
            "evaluate",
            "script",
            "console",
            "network",
            "performance",
        )
    )


def _bool_parameter(value: object) -> bool:
    """Parse planner bool-like parameters fail-closed."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 1
    return False


def _action_name_for_browser_control(action: PlannedAction) -> str:
    if action.kind is ActionKind.OPEN_WEB_APP:
        return "open"
    if action.kind in {ActionKind.BROWSER_SEARCH, ActionKind.GOOGLE_SEARCH}:
        return "search"
    return "browser_control"


def _browser_control_execution_result(
    action: PlannedAction,
    decision: BrowserControlResult,
) -> ToolExecutionResult:
    metadata = {
        "backend": decision.backend.value,
        "fallback_reason": decision.fallback_reason,
        "kind": action.kind.value,
    }
    if decision.mode is not None:
        metadata["session_mode"] = decision.mode.value
    return ToolExecutionResult(
        action_id=action.id,
        tool_name=f"browser_control.{decision.backend.value}",
        success=decision.success,
        executed=False,
        requires_confirmation=decision.requires_confirmation,
        message=decision.message,
        metadata=metadata,
        structured_content={
            "browser_control": {
                "backend": decision.backend.value,
                "session_mode": decision.mode.value if decision.mode else "",
                "fallback_reason": decision.fallback_reason,
                "requires_confirmation": decision.requires_confirmation,
                "audit_detail": decision.audit_detail,
            }
        },
    )


def _audit_target_for_result(action: PlannedAction, result: ToolExecutionResult) -> str:
    """Return a privacy-safe audit target for router-level audit entries."""

    if result.tool_name.startswith("browser_control."):
        redacted = redact_browser_audit_payload({"target": action.target})
        value = redacted.get("target", "[redacted]")
        return str(value)
    return str(action.target)


def _audit_detail_for_result(result: ToolExecutionResult) -> str:
    """Return privacy-safe detail for router-level audit entries."""

    if result.tool_name.startswith("browser_control."):
        browser_control = result.structured_content.get("browser_control")
        if isinstance(browser_control, dict):
            audit_detail = browser_control.get("audit_detail")
            if audit_detail:
                return str(audit_detail)[:500]
        return "[redacted]"
    return str(result.message)[:500]


def _native_success(
    *,
    action_type: str,
    target: str,
    message: str,
    extra_facts: dict[str, Any] | None = None,
) -> NativeToolResult:
    user_facts: dict[str, Any] = {"target": target, "action_type": action_type}
    if extra_facts:
        user_facts.update(extra_facts)
    return NativeToolResult(
        _message=message,
        structuredContent={
            "success": True,
            "action_type": action_type,
            "target": target,
            "user_facts": user_facts,
        },
    )


def _native_failure(
    *,
    action_type: str,
    target: str,
    reason: str,
    next_step: str | None = None,
) -> NativeToolResult:
    structured: dict[str, Any] = {
        "success": False,
        "action_type": action_type,
        "target": target,
        "failure_reason": reason,
        "user_facts": {"target": target, "action_type": action_type},
    }
    if next_step:
        structured["next_step"] = next_step
        structured["user_facts"]["next_step"] = next_step
    return NativeToolResult(isError=True, _message=reason, structuredContent=structured)


def _tool_from_sdk(server_name: str, sdk_tool: object) -> MCPToolDefinition:
    schema = _jsonable(getattr(sdk_tool, "inputSchema", None) or {})
    name = str(getattr(sdk_tool, "name"))
    description = str(getattr(sdk_tool, "description", "") or "")
    return MCPToolDefinition(
        name=name,
        server_name=server_name,
        description=description,
        input_schema=schema,
        action_kinds=_infer_action_kinds(name, description, schema),
        risk_level=_infer_risk_level(name, description, schema),
    )


def _infer_action_kinds(
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> tuple[ActionKind, ...]:
    explicit = input_schema.get("x-eclipse-action-kinds") or input_schema.get(
        "x_eclipse_action_kinds"
    )
    if isinstance(explicit, list):
        return tuple(ActionKind(value) for value in explicit)

    haystack = f"{name} {description}".casefold()
    kinds: list[ActionKind] = []
    if "browser" in haystack and "search" in haystack:
        kinds.append(ActionKind.BROWSER_SEARCH)
    if "google" in haystack and "search" in haystack:
        kinds.append(ActionKind.GOOGLE_SEARCH)
    if "browser" in haystack and any(token in haystack for token in ("open", "url", "web")):
        kinds.append(ActionKind.OPEN_WEB_APP)
    if "desktop" in haystack and any(token in haystack for token in ("open", "launch", "app")):
        kinds.append(ActionKind.OPEN_DESKTOP_APP)
    if "coding" in haystack or "agent" in haystack:
        kinds.append(ActionKind.OPEN_CODING_AGENT)
    if any(token in haystack for token in ("native input", "mouse", "keyboard")):
        kinds.append(ActionKind.NATIVE_INPUT)
    if any(token in haystack for token in ("screenshot", "screen capture")):
        kinds.append(ActionKind.SCREENSHOT)
    if not kinds:
        kinds.append(ActionKind.MCP_TOOL)
    return tuple(dict.fromkeys(kinds))


def _infer_risk_level(
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> RiskLevel:
    explicit = input_schema.get("x-eclipse-risk-level") or input_schema.get("x_eclipse_risk_level")
    if isinstance(explicit, str):
        return RiskLevel(explicit)

    haystack = f"{name} {description}".casefold()
    if any(
        token in haystack
        for token in (
            "delete",
            "send",
            "submit",
            "write",
            "input",
            "keyboard",
            "type",
            "mouse",
            "click",
        )
    ):
        return RiskLevel.HIGH
    if any(token in haystack for token in ("search", "read", "snapshot", "inspect", "screenshot")):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _render_mcp_call_result(raw_result: object) -> str:
    structured = _structured_content(raw_result)
    if structured:
        return f"MCP tool executed with structured result: {json.dumps(structured)}"
    content = getattr(raw_result, "content", None)
    if isinstance(content, list):
        text_parts = [
            str(getattr(item, "text", ""))
            for item in content
            if getattr(item, "text", "")
        ]
        if text_parts:
            return "\n".join(text_parts)
    return "MCP tool executed."


def _structured_content(raw_result: object) -> dict[str, Any] | None:
    structured = getattr(raw_result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    return None


def _server_command_for(client: MCPClientProtocol, tool: MCPToolDefinition) -> tuple[str, ...]:
    if not isinstance(client, MCPToolClient):
        return ()
    try:
        config = client._server_config_for(tool.server_name)  # noqa: SLF001
    except ValueError:
        return ()
    return (config.command, *config.args)


def _string_metadata(action: PlannedAction, arguments: dict[str, Any]) -> dict[str, str]:
    if _is_browser_action(action):
        return {
            "kind": action.kind.value,
            "arguments": json.dumps(
                _privacy_safe_router_arguments(arguments),
                sort_keys=True,
            ),
        }
    return {
        "target": action.target,
        "kind": action.kind.value,
        "arguments": json.dumps(arguments, sort_keys=True),
    }


def _privacy_safe_router_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    redacted_keys = {"target", "url", "target_url", "browser_url", "ws_endpoint"}
    return {
        key: "[redacted]" if str(key).casefold() in redacted_keys else value
        for key, value in arguments.items()
    }


def _requires_vision(action: PlannedAction, tool: MCPToolDefinition) -> bool:
    if action.kind is ActionKind.SCREENSHOT:
        return True
    haystack = " ".join(
        (
            action.tool_name or "",
            action.target,
            action.description,
            tool.qualified_name,
            tool.description,
        )
    )
    return any(
        token in haystack.casefold()
        for token in (
            "screenshot",
            "screen capture",
            "vision",
            "visual",
            "analyze screen",
        )
    )


def _extract_image_path(
    action: PlannedAction,
    arguments: dict[str, Any],
    structured_content: dict[str, Any] | None,
) -> Path | None:
    for source in (structured_content or {}, arguments, action.parameters):
        for key in (
            "image_path",
            "screenshot_path",
            "output_path",
            "path",
            "file_path",
            "filename",
        ):
            value = source.get(key)
            path = _path_if_image(value)
            if path is not None:
                return path
    return None


def _path_if_image(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return None
    return path


def _vision_prompt_for(action: PlannedAction) -> str:
    prompt = action.parameters.get("vision_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    return (
        "Analyze this screenshot for the user's request and return concise, actionable "
        f"observations. Action target: {action.target}. Action description: {action.description}."
    )


def _merge_vision_result(
    structured_content: dict[str, Any] | None,
    vision_result: VisionAnalysisResult,
) -> dict[str, Any]:
    merged = dict(structured_content or {})
    if vision_result.success:
        merged["vision_analysis"] = {
            "model": vision_result.model,
            "image_path": str(vision_result.image_path),
            "text": vision_result.text,
        }
    else:
        merged["vision_error"] = {
            "model": vision_result.model,
            "image_path": str(vision_result.image_path),
            "message": vision_result.message,
        }
    return merged


def _jsonable(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return {}


def _merged_env(env: dict[str, str]) -> dict[str, str] | None:
    if not env:
        return None
    return {**os.environ, **env}


def _run_async(awaitable: object) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)  # type: ignore[arg-type]
    raise RuntimeError("Synchronous MCP routing cannot run inside an active event loop.")


def _require_mcp_sdk() -> tuple[type[Any], type[Any], Any]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The official 'mcp' Python SDK is required for MCP routing. "
            "Install project dependencies before configuring MCP servers."
        ) from exc
    return ClientSession, StdioServerParameters, stdio_client


def shlex_join(command: tuple[str, ...]) -> str:
    """Small wrapper to avoid importing shlex in callers."""

    import shlex

    return shlex.join(command)
