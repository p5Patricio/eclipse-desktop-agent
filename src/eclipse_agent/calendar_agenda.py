"""Read-only calendar agenda for Eclipse from an iCal (.ics) source.

Reading the agenda uses the calendar's private iCal URL (e.g. Google Calendar's
"secret address in iCal format") or a local .ics file — a plain HTTPS GET, no
CalDAV protocol or OAuth dance. Recurring events are expanded over the horizon
so daily/weekly events show their actual upcoming instances.

The fetcher is injectable, so parsing and rendering are testable without network.
Configure ECLIPSE_CALENDAR_ICS_URL.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

DEFAULT_HORIZON_DAYS = 7
DEFAULT_EVENT_LIMIT = 10
_SPANISH_WEEKDAYS = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _now_local() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True)
class CalendarConfig:
    """Where to read the agenda from (secret iCal URL or local .ics path)."""

    ics_source: str = ""


def build_calendar_config_from_env() -> CalendarConfig:
    return CalendarConfig(ics_source=os.environ.get("ECLIPSE_CALENDAR_ICS_URL", ""))


@dataclass(frozen=True)
class CalendarEvent:
    """A single upcoming event instance."""

    summary: str
    start: datetime
    end: datetime | None
    location: str
    all_day: bool


@dataclass(frozen=True)
class AgendaResult:
    """Result of reading the upcoming agenda."""

    success: bool
    events: tuple[CalendarEvent, ...]
    message: str


def fetch_ics(source: str, *, opener: Callable[[str], str] | None = None) -> str:
    """Fetch iCal text from a URL or local file."""

    if opener is not None:
        return opener(source)
    if re.match(r"^https?://", source, re.IGNORECASE):
        import urllib.request

        with urllib.request.urlopen(source, timeout=20) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    return Path(source).expanduser().read_text(encoding="utf-8", errors="replace")


def parse_upcoming_events(
    ics_text: str,
    *,
    now: datetime | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    limit: int = DEFAULT_EVENT_LIMIT,
) -> tuple[CalendarEvent, ...]:
    """Parse and expand events between now and the horizon, soonest first."""

    import recurring_ical_events
    from icalendar import Calendar

    calendar = Calendar.from_ical(ics_text)
    start = now or _now_local()
    end = start + timedelta(days=horizon_days)
    components = recurring_ical_events.of(calendar).between(start, end)
    events = [_to_event(component) for component in components]
    events = [event for event in events if event is not None]
    events.sort(key=lambda event: event.start)
    return tuple(events[:limit])


def read_agenda(
    config: CalendarConfig | None = None,
    *,
    opener: Callable[[str], str] | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    limit: int = DEFAULT_EVENT_LIMIT,
    now: datetime | None = None,
) -> AgendaResult:
    """Read the agenda from the configured iCal source."""

    resolved = config or build_calendar_config_from_env()
    if not resolved.ics_source:
        return AgendaResult(False, (), "Configurá ECLIPSE_CALENDAR_ICS_URL primero.")
    try:
        ics_text = fetch_ics(resolved.ics_source, opener=opener)
        events = parse_upcoming_events(
            ics_text, now=now, horizon_days=horizon_days, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        return AgendaResult(False, (), f"No pude leer tu agenda: {exc}")
    return AgendaResult(True, events, render_agenda(events))


def render_agenda(events: Iterable[CalendarEvent]) -> str:
    """Render upcoming events as a short spoken line."""

    ordered = tuple(events)
    if not ordered:
        return "No tenés eventos próximos."
    parts = []
    for event in ordered:
        location = f" en {event.location}" if event.location else ""
        parts.append(f"{_format_when(event)}: {event.summary}{location}")
    return "Tus próximos eventos: " + "; ".join(parts) + "."


def render_agenda_cli(result: AgendaResult) -> str:
    """Render agenda for CLI display."""

    if not result.success:
        return f"Agenda [failed]: {result.message}"
    if not result.events:
        return "No upcoming events."
    lines = ["Upcoming events:"]
    for event in result.events:
        location = f" — {event.location}" if event.location else ""
        lines.append(f"- {_format_when(event)}: {event.summary}{location}")
    return "\n".join(lines)


def _to_event(component: object) -> CalendarEvent | None:
    get = component.get  # type: ignore[attr-defined]
    raw_start = get("DTSTART")
    if raw_start is None:
        return None
    start_value = raw_start.dt
    all_day = isinstance(start_value, date) and not isinstance(start_value, datetime)
    raw_end = get("DTEND")
    end_value = raw_end.dt if raw_end is not None else None
    return CalendarEvent(
        summary=str(get("SUMMARY", "(sin título)")),
        start=_normalize(start_value),
        end=_normalize(end_value) if end_value is not None else None,
        location=str(get("LOCATION", "")).strip(),
        all_day=all_day,
    )


def _normalize(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_local_tz())
    return datetime.combine(value, time.min).replace(tzinfo=_local_tz())


def _format_when(event: CalendarEvent) -> str:
    local = event.start.astimezone(_local_tz())
    day = _SPANISH_WEEKDAYS[local.weekday()]
    if event.all_day:
        return f"{day} (todo el día)"
    return f"{day} {local.hour:02d}:{local.minute:02d}"
