"""Chrome DevTools MCP adapter helpers for browser-control policy.

The adapter intentionally separates non-attaching diagnostics/tool discovery from
execution. Phase 2 only exposes configuration, health, and tool-name resolution;
runtime routing is introduced by the later integration slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eclipse_agent.browser_control import BrowserSessionMode
from eclipse_agent.settings import EclipseSettings, default_mcp_config_path
from eclipse_agent.tool_router import (
    MCPClientProtocol,
    MCPServerConfig,
    MCPToolClient,
    MCPToolDefinition,
    load_mcp_server_configs,
)


DEFAULT_TOOL_NAME_MAP: dict[str, tuple[str, ...]] = {
    "list_pages": ("list_pages", "pages", "list_tabs"),
    "select_page": ("select_page", "select_tab"),
    "navigate": ("navigate_page", "navigate", "open_page"),
    "snapshot": ("take_snapshot", "snapshot", "accessibility_snapshot"),
    "click": ("click", "click_element"),
    "fill": ("fill", "fill_form", "type_text"),
    "evaluate": ("evaluate_script", "evaluate", "run_script"),
    "screenshot": ("take_screenshot", "screenshot"),
}


@dataclass(frozen=True)
class ChromeDevToolsSessionConfig:
    """Session configuration derived from persisted browser-control settings."""

    server_name: str = "chrome-devtools"
    mode: BrowserSessionMode = BrowserSessionMode.MANAGED
    managed_profile: str = "eclipse-browser-control"
    browser_url: str = ""
    ws_endpoint: str = ""
    auto_connect: bool = False

    @classmethod
    def from_settings(cls, settings: EclipseSettings) -> "ChromeDevToolsSessionConfig":
        """Build a safe session config from user settings, falling back to managed mode."""

        try:
            mode = BrowserSessionMode(settings.browser_session_mode)
        except ValueError:
            mode = BrowserSessionMode.MANAGED
        return cls(
            server_name=settings.browser_devtools_mcp_server or "chrome-devtools",
            mode=mode,
            managed_profile=settings.browser_managed_profile,
            browser_url=settings.browser_devtools_browser_url,
            ws_endpoint=settings.browser_devtools_ws_endpoint,
            auto_connect=bool(settings.browser_devtools_auto_connect),
        )

    def launch_args(self) -> tuple[str, ...]:
        """Return privacy-safe mode arguments for a future MCP server launch."""

        if self.mode is BrowserSessionMode.MANAGED:
            return ("--user-data-dir", self.managed_profile) if self.managed_profile else ()
        if self.mode is BrowserSessionMode.BROWSER_URL:
            return ("--browserUrl", self.browser_url) if self.browser_url else ()
        if self.mode is BrowserSessionMode.WS_ENDPOINT:
            return ("--wsEndpoint", self.ws_endpoint) if self.ws_endpoint else ()
        if self.mode is BrowserSessionMode.AUTO_CONNECT:
            return ("--autoConnect",) if self.auto_connect else ()
        return ()


@dataclass(frozen=True)
class ChromeDevToolsHealth:
    """Non-attaching diagnostics for Chrome DevTools MCP."""

    configured: bool
    session_mode: BrowserSessionMode
    non_attaching: bool
    discovered_tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """Return whether the configured server exposed all required tools."""

        return self.configured and not self.missing_tools


@dataclass(frozen=True)
class ToolResolution:
    """Resolved logical browser-control capabilities to concrete MCP tools."""

    resolved: dict[str, MCPToolDefinition] = field(default_factory=dict)
    missing: tuple[str, ...] = ()


class ChromeDevToolsMCPAdapter:
    """Adapter over the existing MCP client path for Chrome DevTools MCP."""

    def __init__(
        self,
        *,
        session_config: ChromeDevToolsSessionConfig | None = None,
        mcp_client: MCPClientProtocol | None = None,
        server_configs: tuple[MCPServerConfig, ...] | None = None,
        tool_name_map: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.session_config = session_config or ChromeDevToolsSessionConfig()
        self.server_configs = (
            server_configs if server_configs is not None else self._load_selected_server_configs()
        )
        self.mcp_client = mcp_client or MCPToolClient(self.server_configs)
        self.tool_name_map = tool_name_map or DEFAULT_TOOL_NAME_MAP

    @classmethod
    def from_settings(
        cls,
        settings: EclipseSettings,
        *,
        mcp_client: MCPClientProtocol | None = None,
    ) -> "ChromeDevToolsMCPAdapter":
        """Create an adapter for the selected Chrome DevTools MCP server."""

        session_config = ChromeDevToolsSessionConfig.from_settings(settings)
        configs = tuple(
            config
            for config in load_mcp_server_configs(default_mcp_config_path())
            if config.name == session_config.server_name
        )
        return cls(session_config=session_config, mcp_client=mcp_client, server_configs=configs)

    def health(
        self,
        *,
        non_attaching: bool = True,
        required_capabilities: tuple[str, ...] = (),
    ) -> ChromeDevToolsHealth:
        """Return configured/discovered/missing tool diagnostics without attaching."""

        configured = bool(self.server_configs)
        messages: list[str] = []
        if not configured:
            messages.append("Chrome DevTools MCP server is not configured.")

        if non_attaching:
            if required_capabilities:
                messages.append(
                    "Tool discovery skipped in non-attaching diagnostics; "
                    "capabilities require post-consent discovery."
                )
            return ChromeDevToolsHealth(
                configured=configured,
                session_mode=self.session_config.mode,
                non_attaching=True,
                discovered_tools=(),
                missing_tools=required_capabilities,
                messages=tuple(messages),
            )

        try:
            tools = self._discover_server_tools()
        except Exception as exc:  # noqa: BLE001 - diagnostics must fail closed
            messages.append(f"Chrome DevTools MCP discovery failed: {exc}")
            tools = ()

        resolution = self.resolve_tools(required_capabilities, tools=tools)
        return ChromeDevToolsHealth(
            configured=configured,
            session_mode=self.session_config.mode,
            non_attaching=non_attaching,
            discovered_tools=tuple(sorted(tool.name for tool in tools)),
            missing_tools=resolution.missing,
            messages=tuple(messages),
        )

    def resolve_tools(
        self,
        required_capabilities: tuple[str, ...],
        *,
        tools: tuple[MCPToolDefinition, ...] | None = None,
    ) -> ToolResolution:
        """Resolve logical browser-control capabilities to discovered MCP tools."""

        discovered = tools if tools is not None else self._discover_server_tools()
        by_name = {
            name: tool
            for tool in discovered
            for name in (tool.name, tool.qualified_name)
            if tool.server_name == self.session_config.server_name
        }
        resolved: dict[str, MCPToolDefinition] = {}
        missing: list[str] = []
        for capability in required_capabilities:
            match = self._match_tool(capability, by_name)
            if match is None:
                missing.append(capability)
            else:
                resolved[capability] = match
        return ToolResolution(resolved=resolved, missing=tuple(missing))

    def _match_tool(
        self,
        capability: str,
        by_name: dict[str, MCPToolDefinition],
    ) -> MCPToolDefinition | None:
        candidates = self.tool_name_map.get(capability, (capability,))
        for name in candidates:
            if name in by_name:
                return by_name[name]
            qualified = f"{self.session_config.server_name}.{name}"
            if qualified in by_name:
                return by_name[qualified]
        return None

    def _discover_server_tools(self) -> tuple[MCPToolDefinition, ...]:
        return tuple(
            tool
            for tool in self.mcp_client.discover_tools()
            if tool.server_name == self.session_config.server_name
        )

    def _load_selected_server_configs(self) -> tuple[MCPServerConfig, ...]:
        return tuple(
            config
            for config in load_mcp_server_configs(default_mcp_config_path())
            if config.name == self.session_config.server_name
        )
