from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eclipse_agent.planner import (
    ActionKind,
    PlannedAction,
    VisionAnalysisResult,
    create_action_plan,
)
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import (
    MCPToolDefinition,
    NativeMCPClient,
    ToolExecutionContext,
    ToolRouter,
    load_mcp_server_configs,
)


@dataclass
class FakeMCPResult:
    structuredContent: dict[str, Any]
    isError: bool = False
    content: tuple[object, ...] = ()


class FakeMCPClient:
    def __init__(self, tools: tuple[MCPToolDefinition, ...]) -> None:
        self.tools = tools
        self.calls: list[tuple[MCPToolDefinition, dict[str, Any]]] = []

    def discover_tools(self) -> tuple[MCPToolDefinition, ...]:
        return self.tools

    def call_tool(self, tool: MCPToolDefinition, arguments: dict[str, Any]) -> FakeMCPResult:
        self.calls.append((tool, arguments))
        return FakeMCPResult({"ok": True, "tool": tool.qualified_name})


def _browser_open_tool() -> MCPToolDefinition:
    return MCPToolDefinition(
        name="open_url",
        server_name="browser",
        description="Open a browser URL.",
        input_schema={"type": "object"},
        action_kinds=(ActionKind.OPEN_WEB_APP,),
        risk_level=RiskLevel.LOW,
    )


def _browser_search_tool() -> MCPToolDefinition:
    return MCPToolDefinition(
        name="search",
        server_name="browser",
        description="Search the web in a controlled browser.",
        input_schema={"type": "object"},
        action_kinds=(ActionKind.BROWSER_SEARCH,),
        risk_level=RiskLevel.MEDIUM,
    )


def _native_type_tool() -> MCPToolDefinition:
    return MCPToolDefinition(
        name="type_text",
        server_name="native",
        description="Type text through native keyboard input.",
        input_schema={"type": "object"},
        action_kinds=(ActionKind.NATIVE_INPUT,),
        risk_level=RiskLevel.HIGH,
    )


def _native_screenshot_tool() -> MCPToolDefinition:
    return MCPToolDefinition(
        name="screenshot",
        server_name="native",
        description="Capture a screenshot of the screen.",
        input_schema={"type": "object"},
        action_kinds=(ActionKind.SCREENSHOT,),
        risk_level=RiskLevel.MEDIUM,
    )


class FakeVisionAdapter:
    def __init__(self, result: VisionAnalysisResult) -> None:
        self.result = result
        self.calls: list[tuple[str | Path, str]] = []

    def analyze_image(self, image_path: str | Path, *, prompt: str) -> VisionAnalysisResult:
        self.calls.append((image_path, prompt))
        return self.result


def test_tool_router_prepares_matching_mcp_tool_without_execution():
    client = FakeMCPClient((_browser_open_tool(),))
    router = ToolRouter(mcp_client=client)
    plan = create_action_plan("Abre Instagram en el navegador")

    result = router.route_plan(plan, ToolExecutionContext(dry_run=True))[0]

    assert result.tool_name == "browser.open_url"
    assert result.success is True
    assert result.executed is False
    assert client.calls == []
    assert "Prepared MCP tool call" in result.message


def test_tool_router_executes_confirmed_mcp_tool():
    client = FakeMCPClient((_browser_search_tool(),))
    router = ToolRouter(mcp_client=client)
    plan = create_action_plan("Busca especificaciones de Fedora 44")

    result = router.route_plan(
        plan,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )[0]

    assert result.tool_name == "browser.search"
    assert result.success is True
    assert result.executed is True
    assert result.structured_content == {"ok": True, "tool": "browser.search"}
    assert client.calls[0][1]["query"] == "especificaciones de Fedora 44"


def test_tool_router_blocks_medium_risk_search_without_confirmation():
    client = FakeMCPClient((_browser_search_tool(),))
    router = ToolRouter(mcp_client=client)
    plan = create_action_plan("Busca especificaciones de Fedora 44")

    result = router.route_plan(plan, ToolExecutionContext(dry_run=True))[0]

    assert result.tool_name == "safety_policy"
    assert result.requires_confirmation is True
    assert result.success is False
    assert client.calls == []


def test_tool_router_blocks_high_risk_coding_agent_before_tool_selection():
    plan = create_action_plan("Abre Cloud Code y desarrolla una landing")
    router = ToolRouter(mcp_client=FakeMCPClient(()))

    result = router.route_plan(plan, ToolExecutionContext(dry_run=True))[0]

    assert result.tool_name == "safety_policy"
    assert result.requires_confirmation is True
    assert result.success is False


def test_tool_router_blocks_native_input_without_confirmation():
    action = PlannedAction(
        id="native-1",
        kind=ActionKind.NATIVE_INPUT,
        description="Type text into the focused window.",
        risk_level=RiskLevel.HIGH,
        target="focused-window",
        parameters={"text": "hello"},
        tool_name="native.type_text",
    )
    client = FakeMCPClient((_native_type_tool(),))

    result = ToolRouter(mcp_client=client).route_action(action, ToolExecutionContext(dry_run=True))

    assert result.tool_name == "safety_policy"
    assert result.requires_confirmation is True
    assert result.success is False
    assert client.calls == []


def test_tool_router_prepares_confirmed_native_input():
    action = PlannedAction(
        id="native-1",
        kind=ActionKind.NATIVE_INPUT,
        description="Type text into the focused window.",
        risk_level=RiskLevel.HIGH,
        target="focused-window",
        parameters={"text": "hello"},
        tool_name="native.type_text",
    )
    client = FakeMCPClient((_native_type_tool(),))

    result = ToolRouter(mcp_client=client).route_action(
        action,
        ToolExecutionContext(dry_run=True, confirmed=True),
    )

    assert result.tool_name == "native.type_text"
    assert result.success is True
    assert result.executed is False
    assert client.calls == []


def test_tool_router_reports_missing_mcp_tool_after_safety_passes():
    action = PlannedAction(
        id="action-1",
        kind=ActionKind.MCP_TOOL,
        description="Call a missing tool.",
        risk_level=RiskLevel.LOW,
        target="missing",
        tool_name="missing.tool",
    )

    result = ToolRouter(mcp_client=FakeMCPClient(())).route_action(
        action,
        ToolExecutionContext(dry_run=True),
    )

    assert result.tool_name == "missing.tool"
    assert result.success is False
    assert result.requires_confirmation is True


def test_tool_router_routes_screenshot_output_to_vision_adapter(tmp_path):
    image_path = tmp_path / "screen.jpg"
    image_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
    client = FakeMCPClient((_native_screenshot_tool(),))
    vision_adapter = FakeVisionAdapter(
        VisionAnalysisResult(
            success=True,
            model="qwen2.5vl:7b",
            image_path=image_path,
            message="Vision analysis completed.",
            text="The screenshot shows a browser window.",
        )
    )
    action = PlannedAction(
        id="screen-1",
        kind=ActionKind.SCREENSHOT,
        description="Capture and analyze the current screen.",
        risk_level=RiskLevel.MEDIUM,
        target="current-screen",
        parameters={"output_path": str(image_path), "vision_prompt": "Describe the screen."},
        tool_name="native.screenshot",
    )

    result = ToolRouter(mcp_client=client, vision_adapter=vision_adapter).route_action(
        action,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )

    assert result.success is True
    assert result.executed is True
    assert "Vision analysis:" in result.message
    assert result.structured_content["vision_analysis"]["text"] == (
        "The screenshot shows a browser window."
    )
    assert vision_adapter.calls == [(image_path, "Describe the screen.")]


def test_tool_router_reports_vision_model_failure_for_screenshot(tmp_path):
    image_path = tmp_path / "screen.jpg"
    image_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
    client = FakeMCPClient((_native_screenshot_tool(),))
    vision_adapter = FakeVisionAdapter(
        VisionAnalysisResult(
            success=False,
            model="qwen2.5vl:7b",
            image_path=image_path,
            message="Vision model 'qwen2.5vl:7b' is not available in Ollama.",
        )
    )
    action = PlannedAction(
        id="screen-1",
        kind=ActionKind.SCREENSHOT,
        description="Capture and analyze the current screen.",
        risk_level=RiskLevel.MEDIUM,
        target="current-screen",
        parameters={"output_path": str(image_path)},
        tool_name="native.screenshot",
    )

    result = ToolRouter(mcp_client=client, vision_adapter=vision_adapter).route_action(
        action,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )

    assert result.success is False
    assert result.executed is True
    assert "Vision analysis failed" in result.message
    assert "qwen2.5vl:7b" in result.structured_content["vision_error"]["model"]


def test_native_google_search_encodes_query_and_returns_user_facts(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls = []

    class FakeAppLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True,
                app_name=app_name,
                command=(),
                message=f"Opened Google search for {app_name}.",
                dry_run=dry_run,
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: FakeAppLauncher())

    action = PlannedAction(
        id="search-1",
        kind=ActionKind.GOOGLE_SEARCH,
        description="Search Google.",
        risk_level=RiskLevel.MEDIUM,
        target="Google",
        parameters={"query": "Fedora 44 & PipeWire"},
        tool_name="native.google_search",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )

    assert result.success is True
    assert result.executed is True
    assert calls == ["https://www.google.com/search?q=Fedora+44+%26+PipeWire"]
    assert result.structured_content == {
        "success": True,
        "action_type": "google_search",
        "target": "Fedora 44 & PipeWire",
        "user_facts": {"target": "Fedora 44 & PipeWire", "action_type": "google_search"},
    }


def test_native_google_search_rejects_empty_query_without_opening(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls: list[str] = []

    class _RecordingLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True, app_name=app_name, command=(), message="", dry_run=dry_run
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: _RecordingLauncher())
    action = PlannedAction(
        id="search-1",
        kind=ActionKind.GOOGLE_SEARCH,
        description="Search Google.",
        risk_level=RiskLevel.MEDIUM,
        target="Google",
        parameters={"query": "   "},
        tool_name="native.google_search",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )

    assert result.success is False
    assert result.executed is True
    assert calls == []
    assert result.structured_content["action_type"] == "google_search"
    assert result.structured_content["failure_reason"] == "Tell me what you want to search for."


def test_native_app_launch_uses_allowlisted_argv_and_structured_result(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls = []

    class FakeAppLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True,
                app_name=app_name,
                command=("wt.exe",),
                message=f"Opened {app_name}.",
                dry_run=dry_run,
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: FakeAppLauncher())

    action = PlannedAction(
        id="app-1",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open Terminal.",
        risk_level=RiskLevel.LOW,
        target="terminal",
        parameters={"app_name": "terminal; rm -rf /"},
        tool_name="native.open_desktop_app",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False),
    )

    assert result.success is True
    assert calls == ["terminal"]
    assert result.structured_content == {
        "success": True,
        "action_type": "desktop_open_app",
        "target": "terminal",
        "user_facts": {"target": "terminal", "action_type": "desktop_open_app"},
    }


def test_native_app_launch_rejects_unsupported_app_without_execution(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls: list[str] = []

    class _RecordingLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True, app_name=app_name, command=(), message="", dry_run=dry_run
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: _RecordingLauncher())
    action = PlannedAction(
        id="app-1",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open Slack.",
        risk_level=RiskLevel.LOW,
        target="slack",
        parameters={"app_name": "slack"},
        tool_name="native.open_desktop_app",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False),
    )

    assert result.success is False
    assert calls == []
    assert result.structured_content["action_type"] == "desktop_open_app"
    assert result.structured_content["failure_reason"] == (
        "slack is not in the supported app list."
    )



def test_native_app_launch_rejects_ambiguous_allowlisted_targets_without_execution(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls: list[str] = []

    class _RecordingLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True, app_name=app_name, command=(), message="", dry_run=dry_run
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: _RecordingLauncher())
    action = PlannedAction(
        id="app-ambiguous",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open Terminal or Files.",
        risk_level=RiskLevel.LOW,
        target="terminal or files",
        parameters={"app_name": "terminal or files"},
        tool_name="native.open_desktop_app",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False),
    )

    assert result.success is False
    assert calls == []
    assert result.structured_content["failure_reason"] == (
        "terminal or files is not in the supported app list."
    )


def test_native_app_launch_rejects_shell_like_multi_token_alias_without_execution(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    calls: list[str] = []

    class _RecordingLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            calls.append(app_name)
            return DesktopLaunchResult(
                success=True, app_name=app_name, command=(), message="", dry_run=dry_run
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: _RecordingLauncher())
    action = PlannedAction(
        id="app-shell-like",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open a suspicious alias.",
        risk_level=RiskLevel.LOW,
        target="terminal && files",
        parameters={"app_name": "terminal && files"},
        tool_name="native.open_desktop_app",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False),
    )

    assert result.success is False
    assert calls == []
    assert result.structured_content["failure_reason"] == (
        "terminal && files is not in the supported app list."
    )

def test_native_app_launch_failure_sanitizes_command_output(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    class FakeAppLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            return DesktopLaunchResult(
                success=False,
                app_name=app_name,
                command=(),
                message=f"Could not launch {app_name}.",
                dry_run=dry_run,
            )

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: FakeAppLauncher())

    action = PlannedAction(
        id="app-1",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open Files.",
        risk_level=RiskLevel.LOW,
        target="files",
        parameters={"app_name": "files"},
        tool_name="native.open_desktop_app",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action,
        ToolExecutionContext(dry_run=False),
    )

    assert result.success is False
    assert result.structured_content["failure_reason"] == "Could not launch files."
    assert "stderr" not in result.structured_content["user_facts"].values()
    assert "Traceback" not in result.message


def test_load_mcp_server_configs_reads_stdio_servers(tmp_path):
    path = tmp_path / "mcp-servers.json"
    path.write_text(
        '{"servers":[{"name":"browser","command":"python","args":["server.py"]}]}',
        encoding="utf-8",
    )

    configs = load_mcp_server_configs(path)

    assert configs[0].name == "browser"
    assert configs[0].command == "python"
    assert configs[0].args == ("server.py",)


def test_native_mcp_client_routes_via_pal(monkeypatch):
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.desktop_control import DesktopLaunchResult

    launched_apps = []
    captured_paths = []

    class FakeAppLauncher:
        def launch(self, app_name, args=(), *, dry_run=True):
            launched_apps.append((app_name, dry_run))
            return DesktopLaunchResult(
                success=True,
                app_name=app_name,
                command=(),
                message=f"Launched {app_name}",
                dry_run=dry_run,
            )

    class FakeScreenCapture:
        def capture(self, *, output_path=None, geometry=None, dry_run=True):
            captured_paths.append((output_path, dry_run))

            class FakeCaptureResult:
                success = True
                message = f"Screenshot saved to {output_path}."

            return FakeCaptureResult()

    monkeypatch.setattr(PlatformFactory, "get_app_launcher", lambda: FakeAppLauncher())
    monkeypatch.setattr(PlatformFactory, "get_screen_capture", lambda: FakeScreenCapture())

    client = NativeMCPClient()

    # 1. Test URL opening
    res = client.call_tool(
        MCPToolDefinition(name="open_url", server_name="native"),
        {"url": "https://example.com"}
    )
    assert res.isError is False
    assert ("https://example.com", False) in launched_apps

    # 2. Test Google search
    res = client.call_tool(
        MCPToolDefinition(name="google_search", server_name="native"),
        {"query": "hello"}
    )
    assert res.isError is False
    assert ("https://www.google.com/search?q=hello", False) in launched_apps

    # 3. Test open app
    res = client.call_tool(
        MCPToolDefinition(name="open_desktop_app", server_name="native"),
        {"app_name": "terminal"}
    )
    assert res.isError is False
    assert ("terminal", False) in launched_apps

    # 4. Test screenshot
    res = client.call_tool(
        MCPToolDefinition(name="capture_screenshot", server_name="native"),
        {"output_path": "test.png"}
    )
    assert res.isError is False
    assert ("test.png", False) in captured_paths

