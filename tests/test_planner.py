from eclipse_agent.planner import ActionKind, create_action_plan
from eclipse_agent.safety import RiskLevel


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


def test_search_action_is_medium_risk_browser_work():
    plan = create_action_plan("Busca especificaciones de la RTX 5090 en YouTube")

    assert plan.actions[0].kind is ActionKind.BROWSER_SEARCH
    assert plan.actions[0].risk_level is RiskLevel.MEDIUM
    assert "RTX 5090" in plan.actions[0].parameters["query"]


def test_coding_agent_action_requires_confirmation():
    plan = create_action_plan("Abre Cloud Code y desarrolla una landing")

    assert plan.actions[0].kind is ActionKind.OPEN_CODING_AGENT
    assert plan.actions[0].risk_level is RiskLevel.HIGH
    assert plan.requires_confirmation is True
