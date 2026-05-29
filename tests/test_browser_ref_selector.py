import json

from eclipse_agent.browser_automation import parse_agent_browser_snapshot_json
from eclipse_agent.browser_ref_selector import (
    BrowserRefPurpose,
    render_browser_ref_selection,
    select_browser_ref,
)


def _snapshot(elements: dict[str, dict[str, str]]):
    return parse_agent_browser_snapshot_json(
        json.dumps(
            {
                "success": True,
                "data": {
                    "origin": "https://www.instagram.com/",
                    "refs": elements,
                    "snapshot": "fixture",
                },
                "error": None,
            }
        )
    )


def test_select_message_input_prefers_textbox_with_message_keyword():
    snapshot = _snapshot(
        {
            "e1": {"role": "button", "name": "Enviar"},
            "e2": {"role": "textbox", "name": "Mensaje"},
            "e3": {"role": "textbox", "name": "Buscar"},
        }
    )

    selection = select_browser_ref(snapshot)

    assert selection.success is True
    assert selection.selected_ref == "@e2"
    assert "keyword 'mensaje'" in selection.selected.reasons


def test_select_message_input_abstains_when_only_send_button_exists():
    snapshot = _snapshot({"e1": {"role": "button", "name": "Enviar"}})

    selection = select_browser_ref(snapshot)

    assert selection.success is False
    assert selection.selected_ref is None


def test_select_send_button_for_send_purpose():
    snapshot = _snapshot(
        {
            "e1": {"role": "textbox", "name": "Mensaje"},
            "e2": {"role": "button", "name": "Enviar"},
        }
    )

    selection = select_browser_ref(snapshot, purpose=BrowserRefPurpose.SEND_BUTTON)

    assert selection.success is True
    assert selection.selected_ref == "@e2"


def test_render_browser_ref_selection_shows_candidates():
    snapshot = _snapshot({"e7": {"role": "textbox", "name": "Write a message"}})
    rendered = render_browser_ref_selection(select_browser_ref(snapshot))

    assert "Selected @e7" in rendered
    assert "Write a message" in rendered
