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
        from eclipse_agent.media_playback import MediaPlaybackWorkflow

        query = str(arguments.get("query", "") or "").strip()
        app_name = str(arguments.get("app_name", "") or "YouTube Music").strip()
        if not query:
            return _native_failure(
                action_type="play_media",
                target=app_name,
                reason="Tell me what you want to play.",
            )
        result = MediaPlaybackWorkflow().play(
            app_name, query, confirmed=True, dry_run=False
        )
        if result.success:
            return _native_success(
                action_type="play_media",
                target=app_name,
                message=result.message,
                extra_facts={"spoken": result.message},
            )
        reason = result.message
        if "binary not found" in reason.casefold():
            reason = "Necesito agent-browser instalado para reproducir música."
        return _native_failure(
            action_type="play_media",
            target=app_name,
            reason=reason,
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


class ToolRouter:
    """Map planned actions to discovered MCP tools with safety gates."""

    def __init__(
        self,
        *,
        mcp_client: MCPClientProtocol | None = None,
        static_tools: tuple[MCPToolDefinition, ...] = (),
        vision_adapter: VisionAdapterProtocol | None = None,
    ) -> None:
        self.mcp_client = mcp_client or MCPToolClient()
        self.static_tools = static_tools
        self.vision_adapter = vision_adapter or VisionAdapter()
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
        """Route one planned action to a discovered MCP tool."""

        blocked = self._blocked_by_confirmation(action, context)
        if blocked:
            return blocked

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
        if action.tool_name:
            for tool in tools:
                if action.tool_name in {tool.name, tool.qualified_name}:
                    return tool
        for tool in tools:
            if action.kind in tool.action_kinds:
                return tool
        return None

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
    return {
        "target": action.target,
        "kind": action.kind.value,
        "arguments": json.dumps(arguments, sort_keys=True),
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
