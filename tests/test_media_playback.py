import json

from eclipse_agent import main as main_module
from eclipse_agent.browser_automation import (
    BrowserAutomationResult,
    BrowserCommandKind,
    BrowserElement,
    BrowserSnapshot,
)
from eclipse_agent.browser_ref_selector import BrowserRefPurpose, select_browser_ref
from eclipse_agent.media_playback import (
    MediaPlaybackResult,
    MediaPlaybackWorkflow,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter


def _snapshot_json(refs: dict[str, dict[str, str]]) -> str:
    return json.dumps({"success": True, "data": {"origin": "music.youtube.com", "refs": refs}})


SEARCH_PAGE = _snapshot_json({"e1": {"role": "searchbox", "name": "Search"}})
RESULTS_PAGE = _snapshot_json({"e5": {"role": "button", "name": "Play"}})


class FakeAdapter:
    """Stand-in for AgentBrowserAdapter that returns canned snapshots."""

    def __init__(self, snapshots: list[str]) -> None:
        self.snapshots = list(snapshots)
        self.calls: list[tuple] = []

    def _ok(self, kind: BrowserCommandKind, *, dry_run: bool, stdout: str = "") -> BrowserAutomationResult:
        return BrowserAutomationResult(
            success=True,
            kind=kind,
            command=(),
            message="ok",
            dry_run=dry_run,
            executed=not dry_run,
            stdout=stdout,
        )

    def snapshot(self, url=None, *, dry_run=True):
        self.calls.append(("snapshot", url))
        stdout = self.snapshots.pop(0) if self.snapshots else ""
        return self._ok(BrowserCommandKind.SNAPSHOT, dry_run=dry_run, stdout=stdout)

    def fill(self, selector, text, *, dry_run=True):
        self.calls.append(("fill", selector, text))
        return self._ok(BrowserCommandKind.FILL, dry_run=dry_run)

    def press(self, key, *, dry_run=True):
        self.calls.append(("press", key))
        return self._ok(BrowserCommandKind.PRESS, dry_run=dry_run)

    def click(self, selector, *, dry_run=True):
        self.calls.append(("click", selector))
        return self._ok(BrowserCommandKind.CLICK, dry_run=dry_run)


# --- ref selection -------------------------------------------------------


def test_media_browser_profile_is_headed(monkeypatch):
    monkeypatch.setenv("ECLIPSE_CHROME_PROFILE", "MyProfile")
    from eclipse_agent.media_playback import media_browser_profile

    profile = media_browser_profile()
    assert profile.headed is True
    assert profile.chrome_profile == "MyProfile"


def test_select_play_control_prefers_play_button():
    snapshot = BrowserSnapshot(
        origin="x",
        elements=(
            BrowserElement(ref="@e1", role="searchbox", name="Search"),
            BrowserElement(ref="@e2", role="button", name="Play"),
        ),
        snapshot_text="",
    )

    selection = select_browser_ref(snapshot, purpose=BrowserRefPurpose.PLAY_CONTROL)
    assert selection.selected_ref == "@e2"


# --- workflow ------------------------------------------------------------


def test_play_full_flow_searches_and_clicks():
    adapter = FakeAdapter([SEARCH_PAGE, RESULTS_PAGE])
    workflow = MediaPlaybackWorkflow(adapter=adapter)

    result = workflow.play("YouTube Music", "El lado oscuro", confirmed=True, dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert "Reproduciendo El lado oscuro" in result.message
    assert ("fill", "@e1", "El lado oscuro") in adapter.calls
    assert ("click", "@e5") in adapter.calls


def test_play_unsupported_app_fails():
    result = MediaPlaybackWorkflow(adapter=FakeAdapter([])).play("Winamp", "algo")
    assert result.success is False
    assert "supported" in result.message


def test_play_empty_query_fails():
    result = MediaPlaybackWorkflow(adapter=FakeAdapter([SEARCH_PAGE])).play("YouTube Music", "   ")
    assert result.success is False


def test_play_without_snapshot_only_prepares():
    # No snapshot output (dry-run reality): can only prepare, not execute.
    result = MediaPlaybackWorkflow(adapter=FakeAdapter([])).play(
        "YouTube Music", "algo", dry_run=True
    )
    assert result.success is True
    assert result.executed is False
    assert "Prepared" in result.message


def test_play_blocks_without_confirmation():
    result = MediaPlaybackWorkflow(adapter=FakeAdapter([SEARCH_PAGE])).play(
        "YouTube Music", "algo", confirmed=False, dry_run=False
    )
    assert result.success is False
    assert result.blocked is True


def test_play_search_box_not_found_fails():
    no_search = _snapshot_json({"e9": {"role": "button", "name": "Settings"}})
    result = MediaPlaybackWorkflow(adapter=FakeAdapter([no_search])).play(
        "YouTube Music", "algo", confirmed=True, dry_run=False
    )
    assert result.success is False
    assert "search box" in result.message


# --- planner -------------------------------------------------------------


def test_plans_play_media_routes_to_native_play_media():
    plan = create_action_plan("Eclipse, reproduce El lado oscuro en YouTube Music")

    action = plan.actions[0]
    assert action.kind is ActionKind.PLAY_MEDIA
    assert action.tool_name == "native.play_media"
    assert action.parameters["query"] == "El lado oscuro"


# --- native tool ---------------------------------------------------------


def test_native_play_media_speaks_result(monkeypatch):
    import eclipse_agent.media_playback as mp

    class FakeWorkflow:
        def play(self, app, query, *, confirmed, dry_run):
            return MediaPlaybackResult(
                success=True,
                app_name=app,
                query=query,
                executed=True,
                message=f"Reproduciendo {query} en {app}.",
            )

    monkeypatch.setattr(mp, "MediaPlaybackWorkflow", lambda: FakeWorkflow())

    action = PlannedAction(
        id="pm-1",
        kind=ActionKind.PLAY_MEDIA,
        description="Play media.",
        risk_level=RiskLevel.LOW,
        target="YouTube Music",
        parameters={"query": "tema", "app_name": "YouTube Music"},
        tool_name="native.play_media",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )

    assert result.success is True
    assert "Reproduciendo tema" in result.structured_content["user_facts"]["spoken"]


# --- CLI -----------------------------------------------------------------


def test_cli_play_media_dry_run_prepares(capsys):
    assert main_module.main(["play-media", "--query", "algo"]) == 0
    assert "Media playback" in capsys.readouterr().out
