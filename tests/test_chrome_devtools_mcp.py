from eclipse_agent.browser_control import BrowserSessionMode
from eclipse_agent.chrome_devtools_mcp import (
    ChromeDevToolsMCPAdapter,
    ChromeDevToolsSessionConfig,
)
from eclipse_agent.settings import EclipseSettings
from eclipse_agent.tool_router import MCPServerConfig, MCPToolDefinition


class FakeMCPClient:
    def __init__(self, tools: tuple[MCPToolDefinition, ...]) -> None:
        self.tools = tools
        self.discover_calls = 0

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        self.discover_calls += 1
        return self.tools

    def call_tool(self, tool: MCPToolDefinition, arguments: dict):
        raise AssertionError("Adapter health must not call MCP tools")


def _tool(name: str, server_name: str = "chrome-devtools") -> MCPToolDefinition:
    return MCPToolDefinition(name=name, server_name=server_name)


def test_session_config_from_settings_and_managed_launch_args():
    config = ChromeDevToolsSessionConfig.from_settings(
        EclipseSettings(
            browser_devtools_mcp_server="chrome-devtools",
            browser_session_mode="managed",
            browser_managed_profile="eclipse-profile",
        )
    )

    assert config.mode is BrowserSessionMode.MANAGED
    assert config.launch_args() == ("--user-data-dir", "eclipse-profile")


def test_session_config_browser_url_ws_endpoint_and_auto_connect_args():
    browser_url = ChromeDevToolsSessionConfig.from_settings(
        EclipseSettings(
            browser_session_mode="browser_url",
            browser_devtools_browser_url="http://127.0.0.1:9222",
        )
    )
    ws_endpoint = ChromeDevToolsSessionConfig.from_settings(
        EclipseSettings(
            browser_session_mode="ws_endpoint",
            browser_devtools_ws_endpoint="ws://127.0.0.1/devtools/browser/abc",
        )
    )
    auto_connect = ChromeDevToolsSessionConfig.from_settings(
        EclipseSettings(
            browser_session_mode="auto_connect",
            browser_devtools_auto_connect=True,
        )
    )

    assert browser_url.launch_args() == ("--browserUrl", "http://127.0.0.1:9222")
    assert ws_endpoint.launch_args() == (
        "--wsEndpoint",
        "ws://127.0.0.1/devtools/browser/abc",
    )
    assert auto_connect.launch_args() == ("--autoConnect",)


def test_non_attaching_health_does_not_discover_tools():
    client = FakeMCPClient((_tool("take_snapshot"),))
    adapter = ChromeDevToolsMCPAdapter(
        mcp_client=client,
        server_configs=(
            MCPServerConfig(name="chrome-devtools", command="npx", args=("chrome-devtools-mcp",)),
        ),
    )

    health = adapter.health(non_attaching=True, required_capabilities=("snapshot",))

    assert health.configured is True
    assert health.non_attaching is True
    assert health.discovered_tools == ()
    assert health.missing_tools == ("snapshot",)
    assert client.discover_calls == 0


def test_health_reports_configured_discovered_and_missing_tools_without_attach():
    client = FakeMCPClient((_tool("take_snapshot"), _tool("click")))
    adapter = ChromeDevToolsMCPAdapter(
        mcp_client=client,
        server_configs=(
            MCPServerConfig(name="chrome-devtools", command="npx", args=("chrome-devtools-mcp",)),
        ),
    )

    health = adapter.health(
        non_attaching=False,
        required_capabilities=("snapshot", "fill"),
    )

    assert health.configured is True
    assert health.non_attaching is False
    assert health.discovered_tools == ("click", "take_snapshot")
    assert health.missing_tools == ("fill",)
    assert health.available is False
    assert client.discover_calls == 1


def test_health_reports_missing_configuration():
    adapter = ChromeDevToolsMCPAdapter(
        mcp_client=FakeMCPClient(()),
        server_configs=(),
    )

    health = adapter.health(required_capabilities=("snapshot",))

    assert health.configured is False
    assert health.discovered_tools == ()
    assert health.missing_tools == ("snapshot",)
    assert "not configured" in health.messages[0]


def test_resolve_tools_maps_configured_names_and_ignores_other_servers():
    adapter = ChromeDevToolsMCPAdapter(
        mcp_client=FakeMCPClient(
            (
                _tool("take_snapshot"),
                _tool("fill_form"),
                _tool("take_snapshot", server_name="other"),
            )
        ),
        server_configs=(
            MCPServerConfig(name="chrome-devtools", command="npx", args=("chrome-devtools-mcp",)),
        ),
    )

    resolution = adapter.resolve_tools(("snapshot", "fill", "click"))

    assert resolution.resolved["snapshot"].qualified_name == "chrome-devtools.take_snapshot"
    assert resolution.resolved["fill"].qualified_name == "chrome-devtools.fill_form"
    assert resolution.missing == ("click",)
