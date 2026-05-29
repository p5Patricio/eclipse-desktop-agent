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
        server_name="wayland",
        description="Type text through ydotool native keyboard input.",
        input_schema={"type": "object"},
        action_kinds=(ActionKind.NATIVE_INPUT,),
        risk_level=RiskLevel.HIGH,
    )


def _wayland_screenshot_tool() -> MCPToolDefinition:
    return MCPToolDefinition(
        name="screenshot",
        server_name="wayland",
        description="Capture a Wayland screenshot with grim.",
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
        tool_name="wayland.type_text",
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
        tool_name="wayland.type_text",
    )
    client = FakeMCPClient((_native_type_tool(),))

    result = ToolRouter(mcp_client=client).route_action(
        action,
        ToolExecutionContext(dry_run=True, confirmed=True),
    )

    assert result.tool_name == "wayland.type_text"
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
    client = FakeMCPClient((_wayland_screenshot_tool(),))
    vision_adapter = FakeVisionAdapter(
        VisionAnalysisResult(
            success=True,
            model="qwen2-vl:7b",
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
        tool_name="wayland.screenshot",
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
    client = FakeMCPClient((_wayland_screenshot_tool(),))
    vision_adapter = FakeVisionAdapter(
        VisionAnalysisResult(
            success=False,
            model="qwen2-vl:7b",
            image_path=image_path,
            message="Vision model 'qwen2-vl:7b' is not available in Ollama.",
        )
    )
    action = PlannedAction(
        id="screen-1",
        kind=ActionKind.SCREENSHOT,
        description="Capture and analyze the current screen.",
        risk_level=RiskLevel.MEDIUM,
        target="current-screen",
        parameters={"output_path": str(image_path)},
        tool_name="wayland.screenshot",
    )

    result = ToolRouter(mcp_client=client, vision_adapter=vision_adapter).route_action(
        action,
        ToolExecutionContext(dry_run=False, confirmed=True),
    )

    assert result.success is False
    assert result.executed is True
    assert "Vision analysis failed" in result.message
    assert "qwen2-vl:7b" in result.structured_content["vision_error"]["model"]


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
