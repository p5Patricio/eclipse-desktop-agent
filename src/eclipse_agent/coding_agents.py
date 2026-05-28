"""Coding-agent bridge primitives for Eclipse.

This module does not launch external agents yet. It defines the safe registry and the
prompt contract Eclipse will use before adding terminal/process control.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from eclipse_agent.safety import RiskLevel


class CodingAgentName(StrEnum):
    """Supported coding agents Eclipse can orchestrate."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"


@dataclass(frozen=True)
class CodingAgentSpec:
    """Description of a coding agent CLI that Eclipse can open in a project."""

    name: CodingAgentName
    display_name: str
    command: tuple[str, ...]
    aliases: tuple[str, ...]
    risk_level: RiskLevel = RiskLevel.HIGH


CODING_AGENTS: tuple[CodingAgentSpec, ...] = (
    CodingAgentSpec(
        name=CodingAgentName.CLAUDE,
        display_name="Claude Code",
        command=("claude",),
        aliases=("claude", "claude code", "cloud code", "clau code"),
    ),
    CodingAgentSpec(
        name=CodingAgentName.GEMINI,
        display_name="Gemini CLI",
        command=("gemini",),
        aliases=("gemini", "hemini", "jemini", "gemini cli"),
    ),
    CodingAgentSpec(
        name=CodingAgentName.CODEX,
        display_name="Codex CLI",
        command=("codex",),
        aliases=("codex", "openai codex", "codex cli"),
    ),
)


def get_coding_agent(name_or_alias: str) -> CodingAgentSpec:
    """Resolve an agent by canonical name or common voice-transcription alias."""

    normalized = " ".join(name_or_alias.casefold().strip().split())
    for agent in CODING_AGENTS:
        if normalized == agent.name.value or normalized in agent.aliases:
            return agent
    supported = ", ".join(agent.display_name for agent in CODING_AGENTS)
    raise ValueError(f"Unknown coding agent {name_or_alias!r}. Supported: {supported}.")


def build_coding_agent_prompt(
    *,
    agent: CodingAgentSpec | str,
    project_path: str,
    idea: str,
    user_constraints: tuple[str, ...] = (),
) -> str:
    """Build the structured prompt Eclipse will pass to a coding agent.

    The prompt is intentionally conservative: inspect first, protect secrets, avoid
    destructive commands, and keep the human in control for high-risk changes.
    """

    agent_spec = get_coding_agent(agent) if isinstance(agent, str) else agent
    project = Path(project_path).expanduser()
    project_name = project.name or str(project)
    constraints = "\n".join(f"- {constraint}" for constraint in user_constraints)
    if not constraints:
        constraints = "- No extra user constraints were provided."

    return f"""You are {agent_spec.display_name}, launched by Eclipse for a supervised coding task.

Project:
- Name: {project_name}
- Path: {project}

User idea/request:
{idea.strip()}

Operating rules:
1. Inspect the repository before editing; do not assume architecture.
2. Propose a concise plan before making broad changes.
3. Keep changes in reviewable work units with tests/docs beside the behavior they verify.
4. Do not read, print, modify, or commit secrets; avoid .env files unless explicitly requested.
5. Do not run destructive commands, installs, migrations, or networked deploys
   without explicit confirmation.
6. Prefer the project's existing conventions over introducing new frameworks.
7. If requirements are ambiguous or risky, ask a focused question before proceeding.
8. After implementation, report changed files, verification commands, and remaining risks.

User constraints:
{constraints}
""".strip()
