from datetime import UTC, datetime, timedelta

from icalendar import Calendar, Event

from eclipse_agent import main as main_module
from eclipse_agent.calendar_agenda import (
    AgendaResult,
    CalendarConfig,
    CalendarEvent,
    parse_upcoming_events,
    read_agenda,
    render_agenda,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter

NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _make_ics(now: datetime) -> str:
    cal = Calendar()
    cal.add("prodid", "-//eclipse test//")
    cal.add("version", "2.0")

    timed = Event()
    timed.add("summary", "Retro")
    timed.add("dtstart", now + timedelta(days=1, hours=6))
    timed.add("dtend", now + timedelta(days=1, hours=7))
    timed.add("location", "Sala Andrómeda")
    cal.add_component(timed)

    all_day = Event()
    all_day.add("summary", "Feriado")
    all_day.add("dtstart", (now + timedelta(days=2)).date())
    cal.add_component(all_day)

    recurring = Event()
    recurring.add("summary", "Standup")
    recurring.add("dtstart", now + timedelta(hours=2))
    recurring.add("rrule", {"freq": "daily", "count": 10})
    cal.add_component(recurring)

    return cal.to_ical().decode()


# --- parsing -------------------------------------------------------------


def test_parse_expands_recurrence_and_sorts():
    events = parse_upcoming_events(_make_ics(NOW), now=NOW, horizon_days=3)

    summaries = [event.summary for event in events]
    assert summaries.count("Standup") >= 2  # recurrence expanded over the horizon
    assert "Retro" in summaries
    assert events == tuple(sorted(events, key=lambda e: e.start))  # soonest first


def test_parse_marks_all_day_event():
    events = parse_upcoming_events(_make_ics(NOW), now=NOW, horizon_days=3)
    feriado = next(event for event in events if event.summary == "Feriado")
    assert feriado.all_day is True


def test_parse_respects_limit():
    events = parse_upcoming_events(_make_ics(NOW), now=NOW, horizon_days=10, limit=2)
    assert len(events) == 2


# --- read_agenda ---------------------------------------------------------


def test_read_agenda_with_injected_opener():
    ics = _make_ics(NOW)
    result = read_agenda(
        CalendarConfig(ics_source="cal.ics"),
        opener=lambda _source: ics,
        now=NOW,
        horizon_days=3,
    )
    assert result.success is True
    assert any(event.summary == "Retro" for event in result.events)
    assert "Retro" in result.message


def test_read_agenda_not_configured_is_graceful():
    result = read_agenda(CalendarConfig(ics_source=""))
    assert result.success is False
    assert "ECLIPSE_CALENDAR_ICS_URL" in result.message


def test_read_agenda_fetch_error_is_graceful():
    def boom(_source):
        raise OSError("network down")

    result = read_agenda(CalendarConfig(ics_source="cal.ics"), opener=boom)
    assert result.success is False
    assert "No pude leer tu agenda" in result.message


def test_render_agenda_empty():
    assert "No tenés eventos" in render_agenda(())


def test_render_agenda_lists_events():
    event = CalendarEvent(
        summary="Retro",
        start=datetime(2026, 6, 2, 15, 30, tzinfo=UTC),
        end=None,
        location="Sala Andrómeda",
        all_day=False,
    )
    rendered = render_agenda((event,))
    assert "Retro" in rendered
    assert "Sala Andrómeda" in rendered


# --- planner -------------------------------------------------------------


def test_agenda_phrase_routes_to_read_agenda():
    plan = create_action_plan("Eclipse, qué tengo en mi agenda")

    action = plan.actions[0]
    assert action.kind is ActionKind.READ_AGENDA
    assert action.tool_name == "native.read_agenda"


# --- native tool ---------------------------------------------------------


def test_native_read_agenda_speaks_agenda(monkeypatch):
    import eclipse_agent.calendar_agenda as cal_mod

    monkeypatch.setattr(
        cal_mod,
        "read_agenda",
        lambda *a, **k: AgendaResult(True, (), "Tus próximos eventos: martes 15:30: Retro."),
    )

    action = PlannedAction(
        id="cal-1",
        kind=ActionKind.READ_AGENDA,
        description="Read agenda.",
        risk_level=RiskLevel.LOW,
        target="agenda",
        tool_name="native.read_agenda",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )

    assert result.success is True
    assert "Retro" in result.structured_content["user_facts"]["spoken"]


# --- CLI -----------------------------------------------------------------


def test_cli_agenda_not_configured(monkeypatch, capsys):
    monkeypatch.delenv("ECLIPSE_CALENDAR_ICS_URL", raising=False)

    assert main_module.main(["agenda"]) == 1
    assert "failed" in capsys.readouterr().out
