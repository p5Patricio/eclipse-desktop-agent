from eclipse_agent.notification_replies import (
    NotificationReplyWorkflow,
    reply_url_for_event,
)
from eclipse_agent.notifications import NotificationStore, create_notification_event


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
