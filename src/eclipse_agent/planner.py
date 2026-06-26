"""Hybrid planning primitives for Eclipse multi-action requests."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eclipse_agent.coding_agents import CODING_AGENTS, get_coding_agent
from eclipse_agent.memory import MemoryIntent, parse_memory_request
from eclipse_agent.reminders import parse_reminder_request
from eclipse_agent.routines import parse_routine_request
from eclipse_agent.safety import RiskLevel
from eclipse_agent.telemetry import ExecutionTelemetryStore, TelemetryLayer

DEFAULT_LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:7b"
DEFAULT_LOCAL_VISION_MODEL = "qwen2.5vl:7b"
DEFAULT_LOCAL_LLM_API_KEY = "ollama"

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER = "ollama"


class StructuredOutputMode(StrEnum):
    """How a provider is asked to return the structured ActionPlan JSON."""

    STRICT = "strict"  # OpenAI-style json_schema via chat.completions.parse
    JSON_OBJECT = "json_object"  # json_object mode + schema in the prompt


@dataclass(frozen=True)
class LLMProvider:
    """Preset describing one OpenAI-compatible LLM endpoint.

    DeepSeek, Ollama and OpenAI all speak the OpenAI HTTP API, so a provider is
    just data: where to connect, which model, and which structured-output mode
    the endpoint actually supports.
    """

    name: str
    base_url: str
    default_model: str
    api_key_env: str
    structured_output_mode: StructuredOutputMode
    supports_vision: bool


PROVIDERS: dict[str, LLMProvider] = {
    "ollama": LLMProvider(
        name="ollama",
        base_url=DEFAULT_LOCAL_LLM_BASE_URL,
        default_model=DEFAULT_LOCAL_LLM_MODEL,
        api_key_env="ECLIPSE_LLM_API_KEY",
        structured_output_mode=StructuredOutputMode.STRICT,
        supports_vision=True,
    ),
    "deepseek": LLMProvider(
        name="deepseek",
        base_url=DEFAULT_DEEPSEEK_BASE_URL,
        default_model=DEFAULT_DEEPSEEK_MODEL,
        api_key_env="DEEPSEEK_API_KEY",
        structured_output_mode=StructuredOutputMode.JSON_OBJECT,
        supports_vision=False,
    ),
    "openai": LLMProvider(
        name="openai",
        base_url=DEFAULT_OPENAI_BASE_URL,
        default_model=DEFAULT_OPENAI_MODEL,
        api_key_env="OPENAI_API_KEY",
        structured_output_mode=StructuredOutputMode.STRICT,
        supports_vision=True,
    ),
}


def resolve_provider(name: str | None) -> LLMProvider:
    """Return the provider preset for a name, falling back to the default."""

    key = (name or DEFAULT_PROVIDER).strip().casefold()
    return PROVIDERS.get(key, PROVIDERS[DEFAULT_PROVIDER])


class ActionKind(StrEnum):
    """High-level action families that Eclipse can route to tools."""

    PLAY_MEDIA = "play_media"
    OPEN_WEB_APP = "open_web_app"
    BROWSER_SEARCH = "browser_search"
    GOOGLE_SEARCH = "google_search"
    OPEN_DESKTOP_APP = "open_desktop_app"
    OPEN_CODING_AGENT = "open_coding_agent"
    MCP_TOOL = "mcp_tool"
    SCREENSHOT = "screenshot"
    NATIVE_INPUT = "native_input"
    SYSTEM_CONTROL = "system_control"
    READ_CLIPBOARD = "read_clipboard"
    ANSWER_QUESTION = "answer_question"
    SET_REMINDER = "set_reminder"
    ADD_ROUTINE = "add_routine"
    REMEMBER_FACT = "remember_fact"
    RECALL_MEMORY = "recall_memory"
    UNKNOWN = "unknown"


KNOWN_WEB_APPS: dict[str, str] = {
    "youtube": "https://www.youtube.com/",
    "youtube music": "https://music.youtube.com/",
    "instagram": "https://www.instagram.com/",
    "messenger": "https://www.messenger.com/",
}


class AvailableTool(BaseModel):
    """A tool descriptor exposed to the planner before it chooses actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    action_kinds: tuple[ActionKind, ...] = ()
    risk_level: RiskLevel = RiskLevel.MEDIUM
    server_name: str | None = None


class PlannedAction(BaseModel):
    """A single tool-level action in a user request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_.:-]+$")
    kind: ActionKind
    description: str = Field(min_length=1)
    risk_level: RiskLevel
    target: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    tool_name: str | None = Field(
        default=None,
        description="MCP tool name or qualified server.tool name selected by the planner.",
    )

    @field_validator("parameters", mode="before")
    @classmethod
    def _coerce_parameters(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        raise TypeError("parameters must be an object")

    @property
    def can_start_immediately(self) -> bool:
        """Return whether the action has no planned dependencies."""

        return not self.depends_on


class ActionPlan(BaseModel):
    """A decomposed instruction that may contain multiple actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_instruction: str = Field(min_length=1)
    actions: tuple[PlannedAction, ...] = Field(default_factory=tuple)
    planner_version: str = "hybrid-v1"

    @property
    def requires_confirmation(self) -> bool:
        """Return whether the plan contains high or critical risk actions."""

        high_risk_levels = {RiskLevel.HIGH, RiskLevel.CRITICAL}
        return any(action.risk_level in high_risk_levels for action in self.actions)

    @property
    def has_unknown_actions(self) -> bool:
        """Return whether this plan needs smart-layer fallback."""

        return any(action.kind is ActionKind.UNKNOWN for action in self.actions)

    @property
    def parallel_groups(self) -> tuple[tuple[PlannedAction, ...], ...]:
        """Group actions into a simple dependency-aware execution order."""

        immediate = tuple(action for action in self.actions if action.can_start_immediately)
        dependent = tuple(action for action in self.actions if not action.can_start_immediately)
        if immediate and dependent:
            return (immediate, dependent)
        if immediate:
            return (immediate,)
        if dependent:
            return (dependent,)
        return ()

    def render(self) -> str:
        """Render the plan for CLI output."""

        lines = [f"Eclipse action plan ({self.planner_version}):"]
        for group_index, group in enumerate(self.parallel_groups, start=1):
            lines.append(f"Group {group_index}:")
            for action in group:
                tool = f" via {action.tool_name}" if action.tool_name else ""
                lines.append(
                    f"  - {action.id}: {action.kind.value} -> {action.target}{tool} "
                    f"[{action.risk_level.value}] {action.description}"
                )
        lines.append(f"Requires confirmation: {self.requires_confirmation}")
        return "\n".join(lines)


class LLMPlannerConfig(BaseModel):
    """Configuration for Eclipse's local OpenAI-compatible planning endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = DEFAULT_LOCAL_LLM_BASE_URL
    model: str = DEFAULT_LOCAL_LLM_MODEL
    api_key: str = DEFAULT_LOCAL_LLM_API_KEY
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_tokens: int = Field(default=1500, gt=0)
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.STRICT


OpenAICompatiblePlannerConfig = LLMPlannerConfig


class VisionAdapterConfig(BaseModel):
    """Configuration for Eclipse's local OpenAI-compatible vision endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = DEFAULT_LOCAL_LLM_BASE_URL
    model: str = DEFAULT_LOCAL_VISION_MODEL
    api_key: str = DEFAULT_LOCAL_LLM_API_KEY
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_tokens: int = Field(default=1200, gt=0)


@dataclass(frozen=True)
class VisionAnalysisResult:
    """Result of sending an image to the local multimodal model."""

    success: bool
    model: str
    image_path: Path
    message: str
    text: str = ""


class VisionAdapter:
    """Analyze screenshots with a local OpenAI-compatible multimodal model.

    Eclipse keeps the default text planner on ``qwen2.5:7b``. This adapter only
    overrides the model name to ``qwen2.5vl:7b`` for screenshot/image requests,
    allowing Ollama to unload the text model and load the vision model on demand.
    """

    def __init__(
        self,
        config: VisionAdapterConfig | None = None,
        *,
        client: object | None = None,
    ) -> None:
        self.config = config or VisionAdapterConfig()
        self._client = client

    @property
    def client(self) -> object:
        """Return the injected client or lazily construct the official OpenAI client."""

        if self._client is None:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "The official 'openai' Python package is required for vision routing."
                ) from exc
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def analyze_image(self, image_path: str | Path, *, prompt: str) -> VisionAnalysisResult:
        """Analyze one image with the configured local multimodal model."""

        path = Path(image_path).expanduser()
        if not path.exists():
            return VisionAnalysisResult(
                success=False,
                model=self.config.model,
                image_path=path,
                message=f"Screenshot image does not exist: {path}",
            )
        if not path.is_file():
            return VisionAnalysisResult(
                success=False,
                model=self.config.model,
                image_path=path,
                message=f"Screenshot path is not a file: {path}",
            )

        try:
            messages = build_vision_messages(prompt=prompt, image_path=path)
            completion = self.client.chat.completions.create(  # type: ignore[attr-defined]
                model=self.config.model,
                messages=messages,
                temperature=0,
                max_tokens=self.config.max_tokens,
            )
            text = _completion_text(completion)
        except Exception as exc:  # noqa: BLE001
            return VisionAnalysisResult(
                success=False,
                model=self.config.model,
                image_path=path,
                message=_vision_exception_message(exc, self.config.model),
            )

        if not text:
            return VisionAnalysisResult(
                success=False,
                model=self.config.model,
                image_path=path,
                message="Vision model returned an empty response.",
            )
        return VisionAnalysisResult(
            success=True,
            model=self.config.model,
            image_path=path,
            message="Vision analysis completed.",
            text=text,
        )


class LLMPlanner:
    """Smart-layer planner backed by a local OpenAI-compatible LLM endpoint."""

    def __init__(
        self,
        config: LLMPlannerConfig | None = None,
        *,
        client: object | None = None,
    ) -> None:
        self.config = config or LLMPlannerConfig()
        self._client = client

    @property
    def client(self) -> object:
        """Return the injected client or lazily construct the official OpenAI client."""

        if self._client is None:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "The official 'openai' Python package is required for smart-layer planning."
                ) from exc
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def create_action_plan(
        self,
        instruction: str,
        *,
        available_tools: Sequence[AvailableTool] = (),
        semantic_context: Sequence[str] = (),
    ) -> ActionPlan:
        """Create a validated plan using the provider's structured-output mode."""

        if self.config.structured_output_mode is StructuredOutputMode.JSON_OBJECT:
            return self._create_via_json_mode(instruction, available_tools, semantic_context)
        return self._create_via_strict_parse(instruction, available_tools, semantic_context)

    def _create_via_strict_parse(
        self,
        instruction: str,
        available_tools: Sequence[AvailableTool],
        semantic_context: Sequence[str],
    ) -> ActionPlan:
        """Use SDK-native Pydantic Structured Outputs (OpenAI/Ollama)."""

        completion = self.client.chat.completions.parse(  # type: ignore[attr-defined]
            model=self.config.model,
            messages=build_llm_planner_messages(
                instruction=instruction,
                available_tools=available_tools,
                semantic_context=semantic_context,
            ),
            response_format=ActionPlan,
            temperature=0,
            max_tokens=self.config.max_tokens,
        )
        message = completion.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise ValueError(f"LLM refused to create an action plan: {refusal}")
        parsed = getattr(message, "parsed", None)
        if isinstance(parsed, ActionPlan):
            return parsed
        if isinstance(parsed, dict):
            return ActionPlan.model_validate(parsed)
        return self._plan_from_content(getattr(message, "content", None))

    def _create_via_json_mode(
        self,
        instruction: str,
        available_tools: Sequence[AvailableTool],
        semantic_context: Sequence[str],
    ) -> ActionPlan:
        """Use JSON-object mode with the schema in the prompt (DeepSeek).

        DeepSeek does not support strict json_schema structured outputs, so the
        ActionPlan schema is injected into the prompt and the JSON response is
        validated manually with Pydantic.
        """

        completion = self.client.chat.completions.create(  # type: ignore[attr-defined]
            model=self.config.model,
            messages=build_llm_planner_messages(
                instruction=instruction,
                available_tools=available_tools,
                semantic_context=semantic_context,
                json_schema=ActionPlan.model_json_schema(),
            ),
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=self.config.max_tokens,
        )
        message = completion.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise ValueError(f"LLM refused to create an action plan: {refusal}")
        return self._plan_from_content(getattr(message, "content", None))

    @staticmethod
    def _plan_from_content(content: object) -> ActionPlan:
        if isinstance(content, str) and content.strip():
            return ActionPlan.model_validate_json(_strip_json_fences(content))
        raise ValueError("LLM did not return a structured ActionPlan.")


class HybridPlanner:
    """Two-tier planner that uses deterministic rules before local LLM fallback."""

    def __init__(
        self,
        *,
        llm_planner: LLMPlanner | None = None,
        telemetry_store: ExecutionTelemetryStore | None = None,
        smart_layer_enabled: bool = True,
    ) -> None:
        self.llm_planner = llm_planner or LLMPlanner()
        self.telemetry_store = telemetry_store
        self.smart_layer_enabled = smart_layer_enabled

    def create_action_plan(
        self,
        instruction: str,
        *,
        available_tools: Sequence[AvailableTool] = (),
        semantic_context: Sequence[str] = (),
    ) -> ActionPlan:
        """Create a plan with fast deterministic rules and smart local LLM fallback."""

        fast_plan = create_local_fallback_action_plan(instruction)
        if not fast_plan.has_unknown_actions:
            self._record(instruction, TelemetryLayer.FAST_LAYER, True)
            return fast_plan

        if not self.smart_layer_enabled:
            self._record(instruction, TelemetryLayer.FAST_LAYER, False)
            return fast_plan

        try:
            smart_plan = self.llm_planner.create_action_plan(
                instruction,
                available_tools=available_tools,
                semantic_context=semantic_context,
            )
        except Exception:
            self._record(instruction, TelemetryLayer.SMART_LAYER, False)
            return fast_plan

        success = not smart_plan.has_unknown_actions
        self._record(instruction, TelemetryLayer.SMART_LAYER, success)
        return smart_plan

    def _record(
        self,
        instruction: str,
        layer_used: TelemetryLayer,
        success_status: bool,
    ) -> None:
        if self.telemetry_store is None:
            return
        self.telemetry_store.log_execution(
            instruction=instruction,
            layer_used=layer_used,
            success_status=success_status,
        )


def create_action_plan(
    instruction: str,
    *,
    llm_config: LLMPlannerConfig | None = None,
    available_tools: Sequence[AvailableTool] = (),
    semantic_context: Sequence[str] = (),
    llm_client: object | None = None,
    telemetry_store: ExecutionTelemetryStore | None = None,
    smart_layer_enabled: bool = True,
) -> ActionPlan:
    """Create an action plan through the hybrid deterministic/local-LLM planner."""

    return HybridPlanner(
        llm_planner=LLMPlanner(llm_config or LLMPlannerConfig(), client=llm_client),
        telemetry_store=telemetry_store,
        smart_layer_enabled=smart_layer_enabled,
    ).create_action_plan(
        instruction,
        available_tools=available_tools,
        semantic_context=semantic_context,
    )


def build_planner_config_from_env(
    *,
    endpoint_url: str | None,
    model: str | None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    provider: str | None = None,
) -> LLMPlannerConfig:
    """Build planner config from CLI values, a provider preset, and environment.

    The provider preset (ollama by default) supplies the base URL, default model,
    API-key environment variable, and structured-output mode. Explicit CLI values
    and ECLIPSE_LLM_* environment variables override the preset.
    """

    preset = resolve_provider(provider or os.environ.get("ECLIPSE_LLM_PROVIDER"))

    resolved_key = api_key
    if not resolved_key and api_key_env:
        resolved_key = os.environ.get(api_key_env)
    if not resolved_key:
        resolved_key = os.environ.get(preset.api_key_env)
    if not resolved_key:
        resolved_key = os.environ.get("ECLIPSE_LLM_API_KEY", DEFAULT_LOCAL_LLM_API_KEY)

    return LLMPlannerConfig(
        base_url=endpoint_url or os.environ.get("ECLIPSE_LLM_BASE_URL") or preset.base_url,
        model=model or os.environ.get("ECLIPSE_LLM_MODEL") or preset.default_model,
        api_key=resolved_key,
        structured_output_mode=preset.structured_output_mode,
    )


def build_vision_config_from_env(
    *,
    endpoint_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> VisionAdapterConfig:
    """Build local vision config from CLI values and environment defaults."""

    resolved_key = api_key
    if not resolved_key and api_key_env:
        resolved_key = os.environ.get(api_key_env)
    return VisionAdapterConfig(
        base_url=endpoint_url or os.environ.get("ECLIPSE_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL),
        model=model or os.environ.get("ECLIPSE_VISION_MODEL", DEFAULT_LOCAL_VISION_MODEL),
        api_key=resolved_key or os.environ.get("ECLIPSE_LLM_API_KEY", DEFAULT_LOCAL_LLM_API_KEY),
    )


def build_vision_messages(*, prompt: str, image_path: str | Path) -> list[dict[str, Any]]:
    """Build an OpenAI-compatible multimodal chat payload for one image."""

    normalized_prompt = " ".join(prompt.strip().split())
    if not normalized_prompt:
        raise ValueError("Vision prompt cannot be empty.")
    path = Path(image_path).expanduser()
    image_data_url = encode_image_as_data_url(path)
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": normalized_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]


def encode_image_as_data_url(image_path: str | Path) -> str:
    """Read an image and encode it as an OpenAI-compatible data URL."""

    path = Path(image_path).expanduser()
    mime_type = _image_mime_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_llm_planner_messages(
    *,
    instruction: str,
    available_tools: Sequence[AvailableTool],
    semantic_context: Sequence[str],
    json_schema: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build LLM messages for structured planning.

    When ``json_schema`` is provided (json_object mode), the schema is appended to
    the system prompt so providers without strict structured-output support still
    return a conforming JSON object.
    """

    system_content = STRUCTURED_PLANNER_SYSTEM_PROMPT
    if json_schema is not None:
        system_content = (
            f"{system_content}\n"
            "Return ONLY a single JSON object that conforms to this JSON schema:\n"
            f"{json.dumps(json_schema, ensure_ascii=False)}"
        )
    user_payload = {
        "instruction": instruction,
        "available_tools": [tool.model_dump(mode="json") for tool in available_tools],
        "semantic_context": list(semantic_context),
    }
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def create_local_fallback_action_plan(instruction: str) -> ActionPlan:
    """Create a conservative offline plan using deterministic rules."""

    clauses = _split_instruction(instruction)
    actions: list[PlannedAction] = []
    for clause in clauses:
        actions.extend(_plan_clause(clause, len(actions) + 1))

    if not actions:
        actions.append(
            PlannedAction(
                id="action-1",
                kind=ActionKind.UNKNOWN,
                description="Ask a focused clarification before acting.",
                risk_level=RiskLevel.MEDIUM,
                target="unknown",
                parameters={"clause": instruction.strip()},
            )
        )

    return ActionPlan(
        user_instruction=instruction.strip() or "empty instruction",
        actions=tuple(actions),
        planner_version="fast-layer-v1",
    )


def _split_instruction(instruction: str) -> tuple[str, ...]:
    normalized = " ".join(instruction.strip().split())
    if not normalized:
        return ()
    parts = re.split(
        r"\s*(?:,?\s+y\s+también|,?\s+también|,?\s+además|,?\s+luego|"
        r",?\s+después(?: de eso)?)\s+",
        normalized,
        flags=re.IGNORECASE,
    )
    return tuple(part.strip(" ,.") for part in parts if part.strip(" ,."))


def _plan_clause(clause: str, start_index: int) -> tuple[PlannedAction, ...]:
    lowered = clause.casefold()
    coding_action = _maybe_coding_agent_action(clause, lowered, start_index)
    if coding_action:
        return (coding_action,)

    routine_action = _maybe_routine_action(clause, lowered, start_index)
    if routine_action:
        return (routine_action,)

    reminder_action = _maybe_set_reminder_action(clause, lowered, start_index)
    if reminder_action:
        return (reminder_action,)

    system_action = _maybe_system_control_action(clause, lowered, start_index)
    if system_action:
        return (system_action,)

    clipboard_action = _maybe_read_clipboard_action(clause, lowered, start_index)
    if clipboard_action:
        return (clipboard_action,)

    memory_action = _maybe_memory_action(clause, lowered, start_index)
    if memory_action:
        return (memory_action,)

    media_action = _maybe_media_action(clause, lowered, start_index)
    if media_action:
        return (media_action,)

    web_actions = _maybe_web_open_actions(clause, lowered, start_index)
    if web_actions:
        return web_actions

    google_search_action = _maybe_google_search_action(clause, lowered, start_index)
    if google_search_action:
        return (google_search_action,)

    desktop_app_action = _maybe_desktop_app_action(clause, lowered, start_index)
    if desktop_app_action:
        return (desktop_app_action,)

    search_action = _maybe_browser_search_action(clause, lowered, start_index)
    if search_action:
        return (search_action,)

    screenshot_action = _maybe_screenshot_action(clause, lowered, start_index)
    if screenshot_action:
        return (screenshot_action,)

    answer_action = _maybe_answer_question_action(clause, lowered, start_index)
    if answer_action:
        return (answer_action,)

    return (
        PlannedAction(
            id=f"action-{start_index}",
            kind=ActionKind.UNKNOWN,
            description="Unsupported clause; ask before acting.",
            risk_level=RiskLevel.MEDIUM,
            target="unknown",
            parameters={"clause": clause},
        ),
    )


def _maybe_media_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(verb in lowered for verb in ("reproduce", "pon ", "toca ")):
        return None
    if "youtube music" not in lowered:
        return None

    query = re.sub(
        r"^(eclipse,?\s*)?(reproduce|pon|toca)\s+",
        "",
        clause,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+en\s+youtube music\s*$", "", query, flags=re.IGNORECASE).strip()
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.PLAY_MEDIA,
        description="Open YouTube Music and play the requested media.",
        risk_level=RiskLevel.LOW,
        target="YouTube Music",
        parameters={"query": query, "app_name": "YouTube Music"},
        tool_name="native.play_media",
    )


def _maybe_web_open_actions(
    clause: str,
    lowered: str,
    start_index: int,
) -> tuple[PlannedAction, ...]:
    if not any(verb in lowered for verb in ("abre", "abrir", "open")):
        return ()
    if "navegador" not in lowered and "browser" not in lowered:
        return ()

    actions: list[PlannedAction] = []
    for name, url in KNOWN_WEB_APPS.items():
        if name in lowered and name != "youtube music":
            action_index = start_index + len(actions)
            actions.append(
                PlannedAction(
                    id=f"action-{action_index}",
                    kind=ActionKind.OPEN_WEB_APP,
                    description="Open a requested web app in the browser.",
                    risk_level=RiskLevel.LOW,
                    target=name.title(),
                    parameters={"url": url},
                    tool_name="browser.open_url",
                )
            )
    return tuple(actions)


def _maybe_browser_search_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(verb in lowered for verb in ("busca", "buscar", "investiga")):
        return None
    query = re.sub(
        r"^(eclipse,?\s*)?(busca|buscar|investiga)\s+",
        "",
        clause,
        flags=re.IGNORECASE,
    ).strip()
    if query.casefold().strip(" ,.") in {"en google", "google"}:
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.BROWSER_SEARCH,
        description="Search or inspect requested information in the browser.",
        risk_level=RiskLevel.MEDIUM,
        target="browser",
        parameters={"query": query},
        tool_name="browser.search",
    )


def _maybe_google_search_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if "google" not in lowered:
        return None
    if not any(verb in lowered for verb in ("busca", "buscar", "search", "find")):
        return None
    query = re.sub(
        r"^(eclipse,?\s*)?(busca|buscar|search|find)(\s+(en|on))?\s+google(\s+(for|por))?\s*",
        "",
        clause,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    if not query:
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.GOOGLE_SEARCH,
        description="Search Google for the requested query.",
        risk_level=RiskLevel.MEDIUM,
        target="Google",
        parameters={"query": query},
        tool_name="native.google_search",
    )


def _maybe_desktop_app_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(verb in lowered for verb in ("abre", "abrir", "open", "lanza", "launch", "inicia")):
        return None
    if any(token in lowered for token in ("navegador", "browser", "http://", "https://")):
        return None
    target = re.sub(
        r"^(eclipse,?\s*)?(abre|abrir|open|lanza|launch|inicia)\s+",
        "",
        clause,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    if not target:
        return None
    if target.casefold().startswith(("my ", "mi ")):
        return None
    if _is_ambiguous_desktop_app_target(target):
        return None
    app_name = target.casefold()
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.OPEN_DESKTOP_APP,
        description="Open a supported desktop application.",
        risk_level=RiskLevel.LOW,
        target=app_name,
        parameters={"app_name": app_name},
        tool_name="native.open_desktop_app",
    )


def _is_ambiguous_desktop_app_target(target: str) -> bool:
    normalized = re.sub(r"\s+", " ", target.casefold()).strip()
    return bool(re.search(r"\b(or|o)\b|[;&|]", normalized))


def _maybe_screenshot_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(
        token in lowered
        for token in (
            "screenshot",
            "screen shot",
            "captura",
            "pantalla",
            "what is on my screen",
            "what's on my screen",
            "look at my screen",
        )
    ):
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.SCREENSHOT,
        description="Capture and analyze the current screen with the local vision model.",
        risk_level=RiskLevel.MEDIUM,
        target="current-screen",
        parameters={
            "vision_prompt": (
                "Analyze this screenshot for the user's request and return concise, "
                f"actionable observations. User request: {clause}"
            )
        },
        tool_name="native.capture_screenshot",
    )


def _maybe_coding_agent_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(verb in lowered for verb in ("abre", "abrir", "lanza", "inicia")):
        return None

    for agent in CODING_AGENTS:
        if agent.name.value in lowered or any(alias in lowered for alias in agent.aliases):
            resolved = get_coding_agent(agent.name.value)
            return PlannedAction(
                id=f"action-{index}",
                kind=ActionKind.OPEN_CODING_AGENT,
                description="Open a supervised coding agent with a structured prompt.",
                risk_level=RiskLevel.HIGH,
                target=resolved.display_name,
                parameters={"command": " ".join(resolved.command), "request": clause},
                tool_name="coding.open_agent",
            )
    return None


def _maybe_system_control_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    action = _match_system_action(lowered)
    if action is None:
        return None
    risk = RiskLevel.MEDIUM if action == "lock" else RiskLevel.LOW
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.SYSTEM_CONTROL,
        description="Control system volume, media playback, lock, or battery.",
        risk_level=risk,
        target=action,
        parameters={"system_action": action},
        tool_name="native.system_control",
    )


def _maybe_routine_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    request = parse_routine_request(clause)
    if request is None:
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.ADD_ROUTINE,
        description="Schedule a recurring proactive routine.",
        risk_level=RiskLevel.LOW,
        target="routine",
        parameters={
            "routine_message": request.message,
            "routine_action": request.action.value,
            "schedule_kind": request.schedule_kind.value,
            "schedule_value": request.schedule_value,
        },
        tool_name="native.add_routine",
    )


_REMINDER_TOKENS = (
    "recordame", "recuérdame", "recuerdame", "recordatorio", "remind me",
    "avisame", "avísame", "temporizador", "timer", "alarma",
)


def _maybe_set_reminder_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(token in lowered for token in _REMINDER_TOKENS):
        return None
    request = parse_reminder_request(clause)
    if request is None:
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.SET_REMINDER,
        description="Set a reminder or timer.",
        risk_level=RiskLevel.LOW,
        target="reminder",
        parameters={"reminder_text": request.text, "delay_seconds": request.delay_seconds},
        tool_name="native.set_reminder",
    )


def _maybe_memory_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    request = parse_memory_request(clause)
    if request is None:
        return None
    if request.intent is MemoryIntent.REMEMBER:
        return PlannedAction(
            id=f"action-{index}",
            kind=ActionKind.REMEMBER_FACT,
            description="Remember a fact or preference the user shared.",
            risk_level=RiskLevel.LOW,
            target=request.key,
            parameters={"memory_key": request.key, "memory_value": request.value},
            tool_name="native.remember_fact",
        )
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.RECALL_MEMORY,
        description="Recall a remembered fact or preference.",
        risk_level=RiskLevel.LOW,
        target=request.key or "memory",
        parameters={"memory_key": request.key},
        tool_name="native.recall_memory",
    )


_QUESTION_TOKENS = (
    "qué", "cuál", "cuánt", "cómo", "por qué", "porqué", "quién", "dónde", "cuándo",
    "explica", "explicá", "definí", "define", "calcul", "traducí", "traduce",
    "what", "how", "why", "who", "where", "when", "explain", "translate",
)


def _maybe_answer_question_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    is_question = "?" in clause or any(token in lowered for token in _QUESTION_TOKENS)
    if not is_question:
        return None
    question = re.sub(r"^\s*eclipse,?\s*", "", clause, flags=re.IGNORECASE).strip()
    if not question:
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.ANSWER_QUESTION,
        description="Answer the user's question with the LLM provider.",
        risk_level=RiskLevel.LOW,
        target="answer",
        parameters={"question": question},
        tool_name="native.answer_question",
    )


def _maybe_read_clipboard_action(clause: str, lowered: str, index: int) -> PlannedAction | None:
    if not any(
        token in lowered for token in ("portapapeles", "clipboard", "copiado", "copied")
    ):
        return None
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.READ_CLIPBOARD,
        description="Read the current clipboard contents.",
        risk_level=RiskLevel.LOW,
        target="clipboard",
        parameters={},
        tool_name="native.read_clipboard",
    )


def _match_system_action(lowered: str) -> str | None:
    """Map a spoken phrase to a system-control action value, or None."""

    if "volumen" in lowered or "volume" in lowered:
        if any(token in lowered for token in ("sub", "más", "mas", "aument", "up", "louder")):
            return "volume_up"
        if any(token in lowered for token in ("baj", "menos", "down", "reduc", "lower")):
            return "volume_down"
    if any(token in lowered for token in ("silenci", "mute", "mutea", "muteá")):
        return "mute"
    if any(
        token in lowered
        for token in ("siguiente canción", "próxima canción", "proxima canción",
                      "siguiente tema", "next track", "next song", "skip")
    ):
        return "media_next"
    if any(
        token in lowered
        for token in ("canción anterior", "tema anterior", "previous track",
                      "previous song", "canción previa")
    ):
        return "media_previous"
    if any(
        token in lowered
        for token in ("pausa", "pausá", "pausar", "reanud", "resume", "pause", "play/pause")
    ):
        return "media_play_pause"
    if any(token in lowered for token in ("bloque", "lock screen", "lock the", "lockear")):
        return "lock"
    if any(token in lowered for token in ("batería", "bateria", "battery")):
        return "battery"
    return None


def _strip_json_fences(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _completion_text(completion: object) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif hasattr(item, "text"):
                text = getattr(item, "text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part.strip())
    return ""


def _image_mime_type(path: Path) -> str:
    mime_type, _encoding = mimetypes.guess_type(path.name)
    if mime_type in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return mime_type
    return "image/jpeg"


def _vision_exception_message(exc: Exception, model: str) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    lowered = detail.casefold()
    if "model" in lowered and any(token in lowered for token in ("not found", "404", "pull")):
        return (
            f"Vision model '{model}' is not available in Ollama. "
            f"Run scripts/setup_local_llm.sh or 'ollama pull {model}'. "
            f"Provider error: {detail}"
        )
    return f"Vision analysis failed with model '{model}': {detail}"


STRUCTURED_PLANNER_SYSTEM_PROMPT = """You are Eclipse's local deterministic desktop-agent planner.
Return only an object matching the supplied ActionPlan schema.
Use the available_tools list whenever possible. Prefer selecting a concrete
MCP tool name in PlannedAction.tool_name. Never invent secret values.
For visual questions about the current screen or screenshots, choose the
screenshot action kind and a concrete screenshot tool when available.
Preserve Safety-first and Draft-first behavior: classify risk conservatively.
Use medium, high, or critical risk when an action can affect external state,
requires credentials, sends messages, controls native input, modifies files,
or launches autonomous coding agents. Use critical for destructive or secret-
exfiltration requests. Unknown or unsupported instructions must become one
medium-risk clarification action instead of unsafe execution.
All descriptions and targets must be written in English.
"""
