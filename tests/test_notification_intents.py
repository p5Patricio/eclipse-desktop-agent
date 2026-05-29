from eclipse_agent.notification_intents import (
    NotificationVoiceIntentKind,
    execute_notification_voice_intent,
    parse_notification_voice_intent,
)
from eclipse_agent.notifications import (
    NotificationFocusMode,
    NotificationStatus,
    NotificationStore,
    create_notification_event,
)


def test_parse_game_mode_voice_intent_with_duration():
    intent = parse_notification_voice_intent("Eclipse, modo juego por una hora")

    assert intent.kind is NotificationVoiceIntentKind.SET_MODE
    assert intent.mode is NotificationFocusMode.GAME
    assert intent.minutes == 60


def test_execute_mute_sources_voice_intent_persists_rules(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    intent = parse_notification_voice_intent("No me avises de Instagram ni Messenger")

    result = execute_notification_voice_intent(intent, store=store)

    assert result.success is True
    assert tuple(rule.app_pattern for rule in store.list_rules()) == ("Instagram", "Messenger")


def test_execute_summary_intent_can_mark_pending_as_announced(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    event = create_notification_event(
        app_name="Google Chrome",
        summary="Instagram",
        body="Nuevo mensaje",
        source_window="Instagram - Google Chrome",
    ).with_status(NotificationStatus.QUEUED)
    store.save_event(event)
    intent = parse_notification_voice_intent("Dime qué llegó")

    result = execute_notification_voice_intent(
        intent,
        store=store,
        mark_announced=True,
    )

    assert result.success is True
    assert "Instagram" in result.message
    assert store.list_pending() == ()
