from pathlib import Path

from eclipse_agent.desktop_apps import DesktopAppLauncher
from eclipse_agent.planner import create_action_plan
from eclipse_agent.tool_router import ToolExecutionContext, ToolRouter


def _launcher_with_youtube_music(tmp_path: Path) -> DesktopAppLauncher:
    (tmp_path / "youtube-music.desktop").write_text(
        """
[Desktop Entry]
Type=Application
Name=YouTube Music
Exec=/usr/bin/ytmusic
""".strip(),
        encoding="utf-8",
    )
    return DesktopAppLauncher(search_dirs=(tmp_path,))


def test_tool_router_prepares_desktop_and_browser_actions(tmp_path):
    plan = create_action_plan(
        "Reproduce El lado oscuro de Jarabe de Palo en YouTube Music, "
        "también abre Instagram y Messenger en el navegador."
    )
    router = ToolRouter(desktop_launcher=_launcher_with_youtube_music(tmp_path))

    results = router.route_plan(plan, ToolExecutionContext(dry_run=True))

    assert [result.tool_name for result in results] == [
        "desktop_app_launcher",
        "browser_automation",
        "browser_automation",
    ]
    assert results[0].success is True
    assert results[0].executed is False
    assert results[0].command == ("/usr/bin/ytmusic",)
    assert results[1].command[-2:] == ("open", "https://www.instagram.com/")
    assert results[2].command[-2:] == ("open", "https://www.messenger.com/")


def test_tool_router_blocks_medium_risk_search_without_confirmation():
    plan = create_action_plan("Busca especificaciones de Fedora 44")
    router = ToolRouter()

    result = router.route_plan(plan, ToolExecutionContext(dry_run=True))[0]

    assert result.tool_name == "safety_policy"
    assert result.requires_confirmation is True
    assert result.success is False


def test_tool_router_prepares_confirmed_browser_search():
    plan = create_action_plan("Busca especificaciones de Fedora 44")
    router = ToolRouter()

    result = router.route_plan(
        plan,
        ToolExecutionContext(dry_run=True, confirmed=True),
    )[0]

    assert result.tool_name == "browser_automation"
    assert result.success is True
    assert result.command[0] == "agent-browser"
    assert "Fedora+44" in result.command[-1]


def test_tool_router_blocks_high_risk_coding_agent():
    plan = create_action_plan("Abre Cloud Code y desarrolla una landing")
    router = ToolRouter()

    result = router.route_plan(plan, ToolExecutionContext(dry_run=True))[0]

    assert result.tool_name == "safety_policy"
    assert result.requires_confirmation is True
    assert result.success is False
