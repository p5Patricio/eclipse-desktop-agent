"""Deterministic planning primitives for Eclipse multi-action requests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from eclipse_agent.coding_agents import CODING_AGENTS, get_coding_agent
from eclipse_agent.safety import RiskLevel


class ActionKind(StrEnum):
    """High-level action families that Eclipse can route to tools."""

    PLAY_MEDIA = "play_media"
    OPEN_WEB_APP = "open_web_app"
    BROWSER_SEARCH = "browser_search"
    OPEN_CODING_AGENT = "open_coding_agent"
    UNKNOWN = "unknown"


KNOWN_WEB_APPS: dict[str, str] = {
    "youtube": "https://www.youtube.com/",
    "youtube music": "https://music.youtube.com/",
    "instagram": "https://www.instagram.com/",
    "messenger": "https://www.messenger.com/",
}


@dataclass(frozen=True)
class PlannedAction:
    """A single tool-level action in a user request."""

    id: str
    kind: ActionKind
    description: str
    risk_level: RiskLevel
    target: str
    parameters: dict[str, str] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    @property
    def can_start_immediately(self) -> bool:
        """Return whether the action has no planned dependencies."""

        return not self.depends_on


@dataclass(frozen=True)
class ActionPlan:
    """A decomposed instruction that may contain multiple actions."""

    user_instruction: str
    actions: tuple[PlannedAction, ...]

    @property
    def requires_confirmation(self) -> bool:
        """Return whether the plan contains high/critical-risk actions."""

        high_risk_levels = {RiskLevel.HIGH, RiskLevel.CRITICAL}
        return any(action.risk_level in high_risk_levels for action in self.actions)

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

        lines = ["Eclipse action plan:"]
        for group_index, group in enumerate(self.parallel_groups, start=1):
            lines.append(f"Group {group_index}:")
            for action in group:
                lines.append(
                    f"  - {action.id}: {action.kind.value} -> {action.target} "
                    f"[{action.risk_level.value}] {action.description}"
                )
        lines.append(f"Requires confirmation: {self.requires_confirmation}")
        return "\n".join(lines)


def create_action_plan(instruction: str) -> ActionPlan:
    """Create a conservative deterministic plan from a natural-language instruction."""

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

    return ActionPlan(user_instruction=instruction, actions=tuple(actions))


def _split_instruction(instruction: str) -> tuple[str, ...]:
    normalized = " ".join(instruction.strip().split())
    if not normalized:
        return ()
    parts = re.split(
        r"\s*(?:,?\s+y\s+también|,?\s+también|,?\s+además|,?\s+luego|,?\s+después(?: de eso)?)\s+",
        normalized,
        flags=re.IGNORECASE,
    )
    return tuple(part.strip(" ,.") for part in parts if part.strip(" ,."))


def _plan_clause(clause: str, start_index: int) -> tuple[PlannedAction, ...]:
    lowered = clause.casefold()
    coding_action = _maybe_coding_agent_action(clause, lowered, start_index)
    if coding_action:
        return (coding_action,)

    media_action = _maybe_media_action(clause, lowered, start_index)
    if media_action:
        return (media_action,)

    web_actions = _maybe_web_open_actions(clause, lowered, start_index)
    if web_actions:
        return web_actions

    search_action = _maybe_browser_search_action(clause, lowered, start_index)
    if search_action:
        return (search_action,)

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
        parameters={"query": query},
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
    return PlannedAction(
        id=f"action-{index}",
        kind=ActionKind.BROWSER_SEARCH,
        description="Search or inspect requested information in the browser.",
        risk_level=RiskLevel.MEDIUM,
        target="browser",
        parameters={"query": query},
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
            )
    return None
