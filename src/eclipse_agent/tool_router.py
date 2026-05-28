"""Route planned Eclipse actions to executable local tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from eclipse_agent.browser_automation import AgentBrowserAdapter
from eclipse_agent.desktop_apps import DesktopAppLauncher
from eclipse_agent.planner import ActionKind, ActionPlan, PlannedAction
from eclipse_agent.safety import RiskLevel, evaluate_risk


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


class ToolRouter:
    """Map planned actions to local tools with safety gates."""

    def __init__(
        self,
        *,
        desktop_launcher: DesktopAppLauncher | None = None,
        browser_adapter: AgentBrowserAdapter | None = None,
    ) -> None:
        self.desktop_launcher = desktop_launcher or DesktopAppLauncher()
        self.browser_adapter = browser_adapter or AgentBrowserAdapter()

    def route_plan(
        self,
        plan: ActionPlan,
        context: ToolExecutionContext | None = None,
    ) -> tuple[ToolExecutionResult, ...]:
        """Route every action in a plan."""

        context = context or ToolExecutionContext()
        return tuple(self.route_action(action, context) for action in plan.actions)

    def route_action(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        """Route one planned action to its tool implementation."""

        blocked = self._blocked_by_confirmation(action, context)
        if blocked:
            return blocked

        if action.kind is ActionKind.PLAY_MEDIA:
            return self._route_play_media(action, context)
        if action.kind is ActionKind.OPEN_WEB_APP:
            return self._route_browser_open(action, context)
        if action.kind is ActionKind.BROWSER_SEARCH:
            return self._route_browser_search(action, context)
        if action.kind is ActionKind.OPEN_CODING_AGENT:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="coding_agent_launcher",
                success=False,
                executed=False,
                requires_confirmation=True,
                message="Coding-agent launch is high risk and not wired to a process yet.",
                metadata={"target": action.target},
            )

        return ToolExecutionResult(
            action_id=action.id,
            tool_name="unknown",
            success=False,
            executed=False,
            requires_confirmation=True,
            message="No tool is available for this action yet.",
            metadata={"target": action.target},
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

        if action.risk_level is RiskLevel.HIGH and not context.allow_high_risk:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="safety_policy",
                success=False,
                executed=False,
                requires_confirmation=True,
                message="High-risk action requires an explicit high-risk allowance.",
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

    def _route_play_media(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        launch_result = self.desktop_launcher.launch(
            "YouTube Music",
            dry_run=context.dry_run,
        )
        query = action.parameters.get("query", "")
        if not launch_result.success:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="desktop_app_launcher",
                success=False,
                executed=False,
                requires_confirmation=False,
                message=launch_result.message,
                metadata={"target": action.target, "query": query},
            )

        return ToolExecutionResult(
            action_id=action.id,
            tool_name="desktop_app_launcher",
            success=True,
            executed=not context.dry_run,
            requires_confirmation=False,
            command=launch_result.command,
            message=(
                f"{launch_result.message} Media search/play for {query!r} "
                "will be handled by the next browser/accessibility adapter."
            ),
            metadata={"target": action.target, "query": query},
        )

    def _route_browser_open(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        url = action.parameters.get("url", "")
        if not url:
            return ToolExecutionResult(
                action_id=action.id,
                tool_name="browser_automation",
                success=False,
                executed=False,
                requires_confirmation=True,
                message="Browser URL is missing.",
                metadata={"target": action.target},
            )

        browser_result = self.browser_adapter.open_url(url, dry_run=context.dry_run)
        return ToolExecutionResult(
            action_id=action.id,
            tool_name="browser_automation",
            success=browser_result.success,
            executed=browser_result.executed,
            requires_confirmation=False,
            command=browser_result.command,
            message="Open web app in controlled browser session.",
            metadata={"target": action.target, "url": url},
        )

    def _route_browser_search(
        self,
        action: PlannedAction,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        query = action.parameters.get("query", "")
        browser_result = self.browser_adapter.search(query, dry_run=context.dry_run)
        return ToolExecutionResult(
            action_id=action.id,
            tool_name="browser_automation",
            success=browser_result.success,
            executed=browser_result.executed,
            requires_confirmation=False,
            command=browser_result.command,
            message="Open browser search in controlled browser session.",
            metadata={"target": action.target, "query": query},
        )


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
    return "\n".join(lines)


def shlex_join(command: tuple[str, ...]) -> str:
    """Small wrapper to avoid importing shlex in callers."""

    import shlex

    return shlex.join(command)
