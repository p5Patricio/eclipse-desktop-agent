from types import SimpleNamespace

from eclipse_agent import main as main_module
from eclipse_agent.media_playback import (
    MediaPlaybackResult,
    build_media_search_url,
    open_media_search,
    render_media_playback_result,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter


class FakeLauncher:
    def __init__(self, *, success: bool = True, message: str = "opened") -> None:
        self.success = success
        self.message = message
        self.launched: str | None = None
        self.dry_run: bool | None = None

    def launch(self, target: str, dry_run: bool = True):
        self.launched = target
        self.dry_run = dry_run
        return SimpleNamespace(success=self.success, message=self.message)


# --- url building --------------------------------------------------------


def test_build_search_url_for_youtube_music_encodes_query():
    url = build_media_search_url("YouTube Music", "el lado oscuro")
    assert url == "https://music.youtube.com/search?q=el+lado+oscuro"


def test_build_search_url_unsupported_app_is_none():
    assert build_media_search_url("Winamp", "algo") is None


# --- open_media_search ---------------------------------------------------


def test_open_media_search_launches_url():
    launcher = FakeLauncher()
    result = open_media_search("YouTube Music", "lofi", launcher=launcher, dry_run=False)

    assert result.success is True
    assert result.opened is True
    assert launcher.launched == "https://music.youtube.com/search?q=lofi"
    assert "lofi" in result.message


def test_open_media_search_dry_run_does_not_open():
    launcher = FakeLauncher()
    result = open_media_search("YouTube Music", "lofi", launcher=launcher, dry_run=True)

    assert result.success is True
    assert result.opened is False
    assert launcher.dry_run is True


def test_open_media_search_keeps_indirect_play_behind_confirmation():
    launcher = FakeLauncher()

    result = open_media_search(
        "YouTube Music",
        "lofi",
        launcher=launcher,
        requested_interaction="play",
    )

    assert result.success is False
    assert result.requires_confirmation is True
    assert launcher.launched is None


def test_open_media_search_empty_query_fails():
    result = open_media_search("YouTube Music", "   ", launcher=FakeLauncher())
    assert result.success is False


def test_open_media_search_unsupported_app_fails():
    result = open_media_search("Winamp", "algo", launcher=FakeLauncher())
    assert result.success is False
    assert "supported" in result.message


def test_open_media_search_launcher_failure_is_graceful():
    launcher = FakeLauncher(success=False, message="no browser")
    result = open_media_search("YouTube Music", "lofi", launcher=launcher, dry_run=False)
    assert result.success is False
    assert "no browser" in result.message


def test_render_media_playback_result_shows_url():
    result = MediaPlaybackResult(True, "YouTube Music", "lofi", "https://x/y", "ok", opened=True)
    rendered = render_media_playback_result(result)
    assert "https://x/y" in rendered


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

    monkeypatch.setattr(
        mp,
        "open_media_search",
        lambda app, query, **kwargs: MediaPlaybackResult(
            True, app, query, "https://music.youtube.com/search?q=tema",
            f"Abrí la búsqueda de {query} en {app}. Dale play cuando quieras.",
            opened=True,
        ),
    )

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
    assert "Dale play" in result.structured_content["user_facts"]["spoken"]


def test_native_play_media_passes_interaction_and_confirmation(monkeypatch):
    import eclipse_agent.media_playback as mp

    captured = {}

    def fake_open_media_search(app, query, **kwargs):
        captured.update(kwargs)
        return MediaPlaybackResult(
            True,
            app,
            query,
            "https://music.youtube.com/search?q=tema",
            "ok",
            opened=True,
        )

    monkeypatch.setattr(mp, "open_media_search", fake_open_media_search)

    action = PlannedAction(
        id="pm-confirmed",
        kind=ActionKind.PLAY_MEDIA,
        description="Play media.",
        risk_level=RiskLevel.LOW,
        target="YouTube Music",
        parameters={
            "query": "tema",
            "app_name": "YouTube Music",
            "requested_interaction": "submit",
        },
        tool_name="native.play_media",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False, confirmed=True)
    )

    assert result.success is True
    assert captured["requested_interaction"] == "submit"
    assert captured["confirmed"] is True


# --- CLI -----------------------------------------------------------------


def test_cli_play_media_dry_run(monkeypatch, capsys):
    import eclipse_agent.main as main_mod

    monkeypatch.setattr(
        main_mod,
        "open_media_search",
        lambda app, query, **kwargs: MediaPlaybackResult(
            True, app, query, "https://music.youtube.com/search?q=algo", "ok"
        ),
    )

    assert main_module.main(["play-media", "--query", "algo"]) == 0
    assert "Media playback" in capsys.readouterr().out
