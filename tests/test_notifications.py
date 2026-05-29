from datetime import UTC, datetime, timedelta

from eclipse_agent.notifications import (
    DBusNotificationListenerPlan,
    NotificationAction,
    NotificationCenter,
    NotificationFocusMode,
    NotificationPrivacyLevel,
    NotificationRule,
    NotificationSourceKind,
    NotificationStatus,
    NotificationStore,
    build_notification_digest,
    create_notification_event,
    normalize_notification_source,
    parse_dbus_monitor_notify,
)
from eclipse_agent.voice import SpeechResult


class FakeTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def speak(self, text: str, *, dry_run: bool = True) -> SpeechResult:
        self.calls.append((text, dry_run))
        return SpeechResult(
            success=True,
            provider="fake-tts",
            command=("fake-say", text),
            message="fake speech",
            dry_run=dry_run,
            executed=not dry_run,
        )


def test_browser_notification_source_detects_instagram_from_chrome():
    source = normalize_notification_source(
        app_name="Google Chrome",
        desktop_entry="google-chrome.desktop",
        summary="Instagram",
        body="Nuevo mensaje",
        source_window="Instagram - Google Chrome",
    )

    assert source.kind is NotificationSourceKind.WEB
    assert source.label == "Instagram"


def test_normal_mode_announces_and_persists_web_notification(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    tts = FakeTTS()
    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        body="Mensaje nuevo de Ana",
        source_window="Instagram - Google Chrome",
    )

    result = NotificationCenter(store=store, tts=tts).ingest(event)
    stored = store.get_event(event.id)

    assert result.action is NotificationAction.ANNOUNCE
    assert result.mode is NotificationFocusMode.NORMAL
    assert stored is not None
    assert stored.status is NotificationStatus.ANNOUNCED
    assert stored.source_kind is NotificationSourceKind.WEB
    assert tts.calls[0][1] is True


def test_game_mode_queues_notifications_for_later_digest(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    store.set_focus_mode(NotificationFocusMode.GAME)
    event = create_notification_event(
        app_name="Messenger",
        summary="Nuevo mensaje",
        body="¿Jugamos Rocket League?",
    )

    result = NotificationCenter(store=store, tts=FakeTTS()).ingest(event)
    pending = store.list_pending()
    digest = build_notification_digest(pending)

    assert result.action is NotificationAction.QUEUE
    assert pending[0].status is NotificationStatus.QUEUED
    assert digest.total == 1
    assert "Messenger" in digest.render()

    marked = store.mark_events((event.id for event in pending), NotificationStatus.ANNOUNCED)

    assert marked == 1
    assert store.list_pending() == ()


def test_private_mode_stores_metadata_only_without_message_body(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    store.set_focus_mode(NotificationFocusMode.PRIVATE)
    event = create_notification_event(
        app_name="Signal",
        summary="Mensaje privado",
        body="Contenido sensible",
    )

    result = NotificationCenter(store=store, tts=FakeTTS()).ingest(event)
    stored = store.get_event(event.id)

    assert result.action is NotificationAction.METADATA_ONLY
    assert stored is not None
    assert stored.privacy_level is NotificationPrivacyLevel.METADATA_ONLY
    assert stored.body == ""
    assert "Contenido sensible" not in build_notification_digest((stored,)).render()


def test_mute_rule_queues_instagram_even_in_normal_mode(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    store.save_rule(NotificationRule(app_pattern="Instagram", action=NotificationAction.QUEUE))
    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        body="Te escribió alguien",
        source_window="Instagram - Google Chrome",
    )

    result = NotificationCenter(store=store, tts=FakeTTS()).ingest(event)

    assert result.mode is NotificationFocusMode.NORMAL
    assert result.action is NotificationAction.QUEUE
    assert store.list_pending()[0].source_label == "Instagram"


def test_store_delete_events_by_status(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    queued = create_notification_event(app_name="Messenger", summary="Nuevo mensaje")
    announced = create_notification_event(app_name="Gmail", summary="Correo").with_status(
        NotificationStatus.ANNOUNCED
    )
    store.save_event(queued.with_status(NotificationStatus.QUEUED))
    store.save_event(announced)

    deleted = store.delete_events(statuses=(NotificationStatus.ANNOUNCED,))

    assert deleted == 1
    assert tuple(event.display_source for event in store.list_events()) == ("Messenger",)


def test_store_update_event_status_marks_replied(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event = create_notification_event(app_name="Messenger", summary="Nuevo mensaje")
    store.save_event(event)

    updated = store.update_event_status(event.id, NotificationStatus.REPLIED)

    assert updated is not None
    assert updated.status is NotificationStatus.REPLIED
    assert store.list_pending() == ()


def test_temporary_focus_mode_expires_back_to_normal(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    store.set_focus_mode(NotificationFocusMode.GAME, expires_at=now + timedelta(minutes=10))

    state = store.get_runtime_state(now=now + timedelta(minutes=11))

    assert state.mode is NotificationFocusMode.NORMAL


def test_dbus_notification_listener_plan_uses_freedesktop_notify_monitor():
    plan = DBusNotificationListenerPlan()

    assert "dbus-monitor" in plan.command
    assert "org.freedesktop.Notifications" in plan.command[1]


def test_parse_dbus_monitor_notify_block_extracts_event_fields():
    header = (
        "method call time=1710000000.1 sender=:1.42 -> destination=:1.99 serial=7 "
        "path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; "
        "member=Notify"
    )
    raw = f"""
{header}
   string "Google Chrome"
   uint32 0
   string "chrome"
   string "Instagram"
   string "Nuevo mensaje de Ana"
   array [
   ]
   array [
      dict entry(
         string "desktop-entry"
         variant             string "google-chrome"
      )
      dict entry(
         string "urgency"
         variant             byte 1
      )
   ]
   int32 -1
"""

    event = parse_dbus_monitor_notify(raw)

    assert event is not None
    assert event.app_name == "Google Chrome"
    assert event.desktop_entry == "google-chrome"
    assert event.summary == "Instagram"
    assert event.body == "Nuevo mensaje de Ana"
    assert event.source_kind is NotificationSourceKind.WEB
    assert event.source_label == "Instagram"
