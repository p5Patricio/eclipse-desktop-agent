from dataclasses import dataclass

from eclipse_agent.planner import (
    ActionKind,
    ActionPlan,
    AvailableTool,
    HybridPlanner,
    LLMPlanner,
    LLMPlannerConfig,
    PlannedAction,
    VisionAdapter,
    VisionAdapterConfig,
    build_vision_config_from_env,
    build_planner_config_from_env,
    create_action_plan,
)
from eclipse_agent.safety import RiskLevel
from eclipse_agent.telemetry import ExecutionTelemetryStore, TelemetryLayer


@dataclass
class FakeMessage:
    parsed: ActionPlan
    refusal: str | None = None
    content: str | None = None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeCompletion:
    choices: list[FakeChoice]


class FakeCompletions:
    def __init__(self, plan: ActionPlan) -> None:
        self.plan = plan
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(choices=[FakeChoice(message=FakeMessage(parsed=self.plan))])


class FakeChat:
    def __init__(self, plan: ActionPlan) -> None:
        self.completions = FakeCompletions(plan)


class FakeOpenAIClient:
    def __init__(self, plan: ActionPlan) -> None:
        self.chat = FakeChat(plan)


@dataclass
class FakeVisionMessage:
    content: str


@dataclass
class FakeVisionChoice:
    message: FakeVisionMessage


@dataclass
class FakeVisionCompletion:
    choices: list[FakeVisionChoice]


class FakeVisionCompletions:
    def __init__(self, text: str | None = "The screenshot shows a terminal.") -> None:
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.text is None:
            raise RuntimeError("model 'qwen2-vl:7b' not found, try pulling it")
        return FakeVisionCompletion(choices=[FakeVisionChoice(FakeVisionMessage(self.text))])


class FakeVisionChat:
    def __init__(self, text: str | None = "The screenshot shows a terminal.") -> None:
        self.completions = FakeVisionCompletions(text)


class FakeVisionClient:
    def __init__(self, text: str | None = "The screenshot shows a terminal.") -> None:
        self.chat = FakeVisionChat(text)


def test_plans_media_and_multiple_browser_apps_from_single_instruction():
    plan = create_action_plan(
        "Reproduce El lado oscuro de Jarabe de Palo en YouTube Music, "
        "también abre YouTube, Instagram y Messenger en el navegador."
    )

    assert [action.kind for action in plan.actions] == [
        ActionKind.PLAY_MEDIA,
        ActionKind.OPEN_WEB_APP,
        ActionKind.OPEN_WEB_APP,
        ActionKind.OPEN_WEB_APP,
    ]
    assert plan.actions[0].parameters["query"] == "El lado oscuro de Jarabe de Palo"
    assert {action.target for action in plan.actions[1:]} == {"Youtube", "Instagram", "Messenger"}
    assert plan.requires_confirmation is False
    assert len(plan.parallel_groups) == 1
    assert plan.planner_version == "fast-layer-v1"


def test_search_action_is_medium_risk_browser_work():
    plan = create_action_plan("Busca especificaciones de la RTX 5090 en YouTube")

    assert plan.actions[0].kind is ActionKind.BROWSER_SEARCH
    assert plan.actions[0].risk_level is RiskLevel.MEDIUM
    assert "RTX 5090" in plan.actions[0].parameters["query"]


def test_screen_question_plans_screenshot_action():
    plan = create_action_plan("What is on my screen?")

    assert plan.actions[0].kind is ActionKind.SCREENSHOT
    assert plan.actions[0].tool_name == "wayland.screenshot"
    assert "vision_prompt" in plan.actions[0].parameters


def test_coding_agent_action_requires_confirmation():
    plan = create_action_plan("Abre Cloud Code y desarrolla una landing")

    assert plan.actions[0].kind is ActionKind.OPEN_CODING_AGENT
    assert plan.actions[0].risk_level is RiskLevel.HIGH
    assert plan.requires_confirmation is True


def test_hybrid_planner_uses_fast_layer_without_llm_for_known_instruction(tmp_path):
    smart_plan = _smart_browser_plan("Open Instagram")
    client = FakeOpenAIClient(smart_plan)
    telemetry = ExecutionTelemetryStore(tmp_path / "telemetry.sqlite3")
    planner = HybridPlanner(
        llm_planner=LLMPlanner(client=client),
        telemetry_store=telemetry,
    )

    plan = planner.create_action_plan("Abre Instagram en el navegador")

    assert plan.planner_version == "fast-layer-v1"
    assert client.chat.completions.calls == []
    summary = telemetry.summarize(days=1)
    assert summary.fast_layer_requests == 1
    assert summary.smart_layer_requests == 0


def test_hybrid_planner_falls_back_to_local_llm_for_unknown_instruction(tmp_path):
    smart_plan = _smart_browser_plan("Open calendar")
    client = FakeOpenAIClient(smart_plan)
    telemetry = ExecutionTelemetryStore(tmp_path / "telemetry.sqlite3")
    tool = AvailableTool(
        name="browser.open_url",
        description="Open a browser URL.",
        action_kinds=(ActionKind.OPEN_WEB_APP,),
        risk_level=RiskLevel.LOW,
    )
    planner = HybridPlanner(
        llm_planner=LLMPlanner(LLMPlannerConfig(), client=client),
        telemetry_store=telemetry,
    )

    plan = planner.create_action_plan("Open my calendar", available_tools=(tool,))

    assert plan.actions[0].tool_name == "browser.open_url"
    assert plan.actions[0].kind is ActionKind.OPEN_WEB_APP
    call = client.chat.completions.calls[0]
    assert call["model"] == "qwen2.5:7b"
    assert call["response_format"] is ActionPlan
    assert "available_tools" in call["messages"][1]["content"]
    summary = telemetry.summarize(days=1)
    assert summary.fast_layer_requests == 0
    assert summary.smart_layer_requests == 1


def test_build_planner_config_defaults_to_ollama_qwen(monkeypatch):
    monkeypatch.delenv("ECLIPSE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ECLIPSE_LLM_MODEL", raising=False)
    monkeypatch.delenv("ECLIPSE_LLM_API_KEY", raising=False)

    config = build_planner_config_from_env(
        endpoint_url=None,
        model=None,
        api_key=None,
        api_key_env="ECLIPSE_LLM_API_KEY",
    )

    assert config.base_url == "http://localhost:11434/v1"
    assert config.model == "qwen2.5:7b"
    assert config.api_key == "ollama"


def test_build_vision_config_defaults_to_ollama_qwen_vl(monkeypatch):
    monkeypatch.delenv("ECLIPSE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ECLIPSE_VISION_MODEL", raising=False)
    monkeypatch.delenv("ECLIPSE_LLM_API_KEY", raising=False)

    config = build_vision_config_from_env()

    assert config.base_url == "http://localhost:11434/v1"
    assert config.model == "qwen2-vl:7b"
    assert config.api_key == "ollama"


def test_vision_adapter_sends_openai_compatible_image_payload(tmp_path):
    image_path = tmp_path / "screen.jpg"
    image_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
    client = FakeVisionClient()
    adapter = VisionAdapter(VisionAdapterConfig(model="qwen2-vl:7b"), client=client)

    result = adapter.analyze_image(image_path, prompt="Describe the screen.")

    assert result.success is True
    assert result.text == "The screenshot shows a terminal."
    call = client.chat.completions.calls[0]
    assert call["model"] == "qwen2-vl:7b"
    content = call["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Describe the screen."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vision_adapter_reports_missing_ollama_model(tmp_path):
    image_path = tmp_path / "screen.jpg"
    image_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
    adapter = VisionAdapter(client=FakeVisionClient(text=None))

    result = adapter.analyze_image(image_path, prompt="Describe the screen.")

    assert result.success is False
    assert "ollama pull qwen2-vl:7b" in result.message


def _smart_browser_plan(instruction: str) -> ActionPlan:
    return ActionPlan(
        user_instruction=instruction,
        planner_version="smart-layer-v1",
        actions=(
            PlannedAction(
                id="action-1",
                kind=ActionKind.OPEN_WEB_APP,
                description="Open the requested web app in the browser.",
                risk_level=RiskLevel.LOW,
                target="Browser",
                parameters={"url": "https://calendar.google.com/"},
                tool_name="browser.open_url",
            ),
        ),
    )
