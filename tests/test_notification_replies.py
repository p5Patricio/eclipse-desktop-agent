import json

from eclipse_agent.notification_replies import (
    NotificationReplyWorkflow,
    reply_url_for_event,
    resolve_reply_text,
)
from eclipse_agent.notifications import NotificationStore, create_notification_event
from eclipse_agent.voice import TranscriptionResult


def _stored_instagram_event(store: NotificationStore) -> str:
    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        body="Nuevo mensaje",
        source_window="Instagram - Google Chrome",
    )
    store.save_event(event)
    return event.id


def test_reply_url_for_web_instagram_event():
    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        source_window="Instagram - Google Chrome",
    )

    assert reply_url_for_event(event) == "https://www.instagram.com/"


def test_reply_draft_without_selector_prepares_snapshot(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
    )

    assert result.success is True
    assert result.browser_plan is not None
    assert result.browser_plan.results[0].command[-1] == "snapshot -i"


def test_reply_draft_with_selector_requires_confirmation(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
        selector="@e7",
    )

    assert result.success is False
    assert result.browser_plan is not None
    assert result.browser_plan.requires_confirmation is True


def test_confirmed_reply_draft_prepares_fill_action(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
        selector="@e7",
        confirmed=True,
    )

    assert result.success is True
    assert result.browser_plan is not None
    assert result.browser_plan.results[0].command[-3:] == (
        "fill",
        "@e7",
        "Ahorita entro.",
    )


def test_reply_draft_auto_selects_message_input_from_snapshot_json(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)
    snapshot_json = json.dumps(
        {
            "success": True,
            "data": {
                "origin": "https://www.instagram.com/",
                "refs": {
                    "e1": {"role": "button", "name": "Enviar"},
                    "e2": {"role": "textbox", "name": "Mensaje"},
                },
                "snapshot": "fixture",
            },
            "error": None,
        }
    )

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
        snapshot_output=snapshot_json,
        auto_select=True,
        confirmed=True,
    )

    assert result.success is True
    assert result.ref_selection is not None
    assert result.ref_selection.selected_ref == "@e2"
    assert result.browser_plan.results[0].command[-3:] == (
        "fill",
        "@e2",
        "Ahorita entro.",
    )


def test_reply_draft_auto_select_blocks_when_snapshot_has_no_input(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)
    snapshot_json = json.dumps(
        {
            "success": True,
            "data": {
                "origin": "https://www.instagram.com/",
                "refs": {"e1": {"role": "button", "name": "Enviar"}},
                "snapshot": "fixture",
            },
            "error": None,
        }
    )

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
        snapshot_output=snapshot_json,
        auto_select=True,
        confirmed=True,
    )

    assert result.success is False
    assert result.ref_selection is not None
    assert result.ref_selection.selected_ref is None


def test_resolve_reply_text_prefers_explicit_message():
    result = resolve_reply_text(message="  Ahorita   entro.  ")

    assert result.success is True
    assert result.text == "Ahorita entro."


def test_resolve_reply_text_blocks_without_message_or_audio():
    result = resolve_reply_text()

    assert result.success is False
    assert "required" in result.message


def test_resolve_reply_text_uses_transcribed_audio(tmp_path):
    audio_path = tmp_path / "reply.wav"
    audio_path.write_bytes(b"fake wav")

    class FakeTranscriber:
        def transcribe_file(self, path):
            return TranscriptionResult(
                success=True,
                text="  Ahorita   entro  ",
                audio_path=path,
                provider="fake",
                message="ok",
            )

    result = resolve_reply_text(audio_path=audio_path, transcriber=FakeTranscriber())

    assert result.success is True
    assert result.text == "Ahorita entro"
