import json

from eclipse_agent.audit import AuditLog
from eclipse_agent.browser_control import BrowserControlService
from eclipse_agent.notification_replies import (
    NotificationReplyWorkflow,
    reply_url_for_event,
    resolve_reply_text,
)
from eclipse_agent.notifications import NotificationStore, create_notification_event
from eclipse_agent.settings import EclipseSettings
from eclipse_agent.voice import TranscriptionResult
from eclipse_agent.voice import ListenResult, RecordingResult


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
    browser_control = BrowserControlService(
        settings=EclipseSettings(browser_live_access_consent=True)
    )

    result = NotificationReplyWorkflow(
        store=store, browser_control_service=browser_control
    ).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
    )

    assert result.success is True
    assert result.browser_plan is not None
    assert result.browser_plan.results[0].command[-1] == "snapshot -i"


def test_reply_draft_without_selector_is_gated_and_audited(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)
    audit_log = AuditLog(tmp_path / "audit.sqlite3")
    browser_control = BrowserControlService(
        settings=EclipseSettings(browser_live_access_consent=False),
        audit_log=audit_log,
    )

    result = NotificationReplyWorkflow(
        store=store, browser_control_service=browser_control
    ).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
    )

    assert result.success is False
    assert result.browser_plan is None
    assert "consent is required" in result.message
    entries = audit_log.recent()
    assert entries[0].action_kind == "browser_control"
    assert entries[0].target == "notification_reply_prepare"
    assert "instagram.com" not in entries[0].detail


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
    assert result.requires_confirmation is True


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


def test_reply_draft_send_after_fill_requires_confirmation(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event_id = _stored_instagram_event(store)

    result = NotificationReplyWorkflow(store=store).prepare_reply_draft(
        event_id=event_id,
        reply_text="Ahorita entro.",
        selector="@e7",
        send_after_fill=True,
    )

    assert result.success is False
    assert result.requires_confirmation is True
    assert "requires explicit confirmation" in result.message


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


def test_resolve_reply_text_records_and_transcribes_audio(tmp_path):
    audio_path = tmp_path / "reply.wav"

    class FakeListener:
        def run(self, *, seconds=5, audio_path=None, dry_run=True):
            return ListenResult(
                success=True,
                recording=RecordingResult(
                    success=True,
                    command=("fake-record",),
                    audio_path=audio_path,
                    message="recorded",
                    dry_run=False,
                    executed=True,
                ),
                transcription=TranscriptionResult(
                    success=True,
                    text=" Voy en camino ",
                    audio_path=audio_path,
                    provider="fake",
                    message="ok",
                ),
                message="ok",
            )

    result = resolve_reply_text(
        record_seconds=2,
        record_audio_path=audio_path,
        listener=FakeListener(),
    )

    assert result.success is True
    assert result.text == "Voy en camino"


def test_resolve_reply_text_rejects_invalid_record_duration():
    result = resolve_reply_text(record_seconds=0)

    assert result.success is False
    assert "positive" in result.message
