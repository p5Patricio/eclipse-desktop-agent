from datetime import UTC, datetime, timedelta

from eclipse_agent import main as main_module
from eclipse_agent.reminders import (
    ReminderStore,
    fire_due_reminders,
    parse_reminder_request,
    render_reminders,
)


def test_parse_minutes_and_text():
    request = parse_reminder_request("recordame en 10 minutos que saque la pizza")
    assert request is not None
    assert request.delay_seconds == 600
    assert request.text == "saque la pizza"


def test_parse_seconds_and_hours():
    assert parse_reminder_request("avisame en 30 segundos").delay_seconds == 30
    english = parse_reminder_request("remind me in 2 hours to call mom")
    assert english.delay_seconds == 7200
    assert english.text == "call mom"


def test_parse_without_delay_returns_none():
    assert parse_reminder_request("recordame que saque la pizza") is None


def test_store_add_list_and_clear(tmp_path):
    store = ReminderStore(tmp_path / "r.sqlite3")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    store.add("sacar la pizza", now + timedelta(minutes=10))
    pending = store.list_pending()

    assert len(pending) == 1
    assert pending[0].text == "sacar la pizza"
    assert store.clear() == 1


def test_store_due_and_mark_fired(tmp_path):
    store = ReminderStore(tmp_path / "r.sqlite3")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    past = store.add("pasada", now - timedelta(minutes=1))
    store.add("futura", now + timedelta(minutes=10))

    due = store.due(now)
    assert [r.text for r in due] == ["pasada"]

    store.mark_fired(past.id)
    assert store.due(now) == ()


def test_fire_due_reminders_speaks_and_marks(tmp_path):
    store = ReminderStore(tmp_path / "r.sqlite3")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.add("tomar agua", now - timedelta(seconds=1))
    spoken: list[str] = []

    fired = fire_due_reminders(store, spoken.append, now=now)

    assert len(fired) == 1
    assert any("tomar agua" in line for line in spoken)
    assert store.due(now) == ()


def test_render_reminders_empty():
    assert "No pending" in render_reminders(())


def test_cli_remind_and_list(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["remind", "--text", "saque la pizza", "--seconds", "600"]) == 0
    assert "Reminder set for" in capsys.readouterr().out

    assert main_module.main(["reminders-list"]) == 0
    assert "saque la pizza" in capsys.readouterr().out


def test_cli_remind_parses_natural_phrase(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["remind", "--text", "en 5 minutos que llame a Ana"]) == 0
    assert "llame a Ana" in capsys.readouterr().out


def test_cli_reminders_check_fires_due(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ReminderStore().add("recordatorio viejo", datetime.now(UTC) - timedelta(seconds=5))

    assert main_module.main(["reminders-check"]) == 0
    assert "Fired: recordatorio viejo" in capsys.readouterr().out
