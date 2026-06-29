"""Morning briefing module for Eclipse.

Composes a spoken daily summary from calendar events, inbox highlights, and
weather conditions. All three data sources are fetched concurrently; a failure
in any one degrades gracefully so the briefing always returns something useful.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


BRIEFING_SYSTEM_PROMPT = (
    "You are Eclipse, a voice assistant composing the user's morning briefing. "
    "Write one natural-language paragraph suitable for reading aloud. "
    "Do NOT use markdown, lists, bullet points, or headings. "
    "Start with 'Good morning' or a greeting, then mention the date, weather, "
    "calendar events, and inbox highlights in a friendly, concise way."
)


@dataclass
class BriefingConfig:
    briefing_time: str = "07:00"
    include_calendar: bool = True
    include_inbox: bool = True
    include_weather: bool = True
    weather_latitude: float = 0.0
    weather_longitude: float = 0.0


@dataclass
class BriefingResult:
    success: bool
    text: str
    calendar_ok: bool
    inbox_ok: bool
    weather_ok: bool
    error: str = ""


def compose_briefing(
    config: BriefingConfig | None = None,
    *,
    agenda_fn: Callable[[], Any] | None = None,
    inbox_fn: Callable[[], Any] | None = None,
    weather_fn: Callable[[], str] | None = None,
    answerer: Any = None,
    date_override: datetime | None = None,
) -> BriefingResult:
    """Compose a natural-language morning briefing.

    Fetches calendar, inbox, and weather concurrently. Each source failure is
    caught gracefully; the briefing only fails entirely when all three are down.
    """
    if config is None:
        config = BriefingConfig()

    if agenda_fn is None:
        from eclipse_agent.calendar_agenda import read_agenda

        def _default_agenda() -> str:
            result = read_agenda()
            return result.message if result.success else ""

        agenda_fn = _default_agenda

    if inbox_fn is None:
        from eclipse_agent.email_inbox import summarize_inbox

        def _default_inbox() -> str:
            result = summarize_inbox()
            return result.summary if result.success else ""

        inbox_fn = _default_inbox

    if weather_fn is None:
        from eclipse_agent.weather import WeatherConfig, get_weather, render_weather

        def _default_weather() -> str:
            wc = WeatherConfig(
                latitude=config.weather_latitude,
                longitude=config.weather_longitude,
            )
            return render_weather(get_weather(wc))

        weather_fn = _default_weather

    calendar_text = ""
    inbox_text = ""
    weather_text = ""
    calendar_ok = False
    inbox_ok = False
    weather_ok = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_calendar = executor.submit(agenda_fn)
        future_inbox = executor.submit(inbox_fn)
        future_weather = executor.submit(weather_fn)

        try:
            calendar_text = str(future_calendar.result() or "")
            calendar_ok = bool(calendar_text)
        except Exception:  # noqa: BLE001
            calendar_text = ""
            calendar_ok = False

        try:
            inbox_text = str(future_inbox.result() or "")
            inbox_ok = bool(inbox_text)
        except Exception:  # noqa: BLE001
            inbox_text = ""
            inbox_ok = False

        try:
            weather_text = str(future_weather.result() or "")
            weather_ok = bool(weather_text) and "unavailable" not in weather_text.lower()
        except Exception:  # noqa: BLE001
            weather_text = ""
            weather_ok = False

    if not calendar_ok and not inbox_ok and not weather_ok:
        return BriefingResult(
            success=False,
            text="",
            calendar_ok=False,
            inbox_ok=False,
            weather_ok=False,
            error="All briefing sources were unavailable.",
        )

    now = date_override or datetime.now()
    weekday = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")

    sections: list[str] = [f"Today is {weekday}, {date_str}."]
    if weather_ok:
        sections.append(weather_text)
    else:
        sections.append("Weather information was unavailable.")

    if calendar_ok:
        sections.append(calendar_text)
    else:
        sections.append("Calendar information was unavailable today.")

    if inbox_ok:
        sections.append(inbox_text)
    else:
        sections.append("Inbox information was unavailable today.")

    raw_data = " ".join(sections)
    prompt = (
        f"Morning briefing data for {weekday}, {date_str}: {raw_data}\n\n"
        "Write a one-paragraph spoken morning briefing from this data."
    )

    if answerer is None:
        from eclipse_agent.answer import QuestionAnswerer
        from eclipse_agent.planner import build_planner_config_from_env

        answerer = QuestionAnswerer(
            build_planner_config_from_env(endpoint_url=None, model=None),
            system_prompt=BRIEFING_SYSTEM_PROMPT,
        )

    try:
        result = answerer.answer(prompt)
        text = result.answer if result.success else raw_data
    except Exception:  # noqa: BLE001
        text = f"Good morning! {raw_data}"

    return BriefingResult(
        success=True,
        text=text,
        calendar_ok=calendar_ok,
        inbox_ok=inbox_ok,
        weather_ok=weather_ok,
    )


def render_briefing(result: BriefingResult) -> str:
    if not result.success:
        return f"Morning briefing failed: {result.error}"
    return result.text


def ensure_briefing_routine(store: Any, settings: Any) -> None:
    """Upsert a DAILY routine named 'morning-briefing' if briefing_enabled.

    No-ops if a routine named 'morning-briefing' already exists.
    """
    from eclipse_agent.routines import RoutineAction, ScheduleKind

    time_value = getattr(settings, "briefing_time", "07:00") or "07:00"
    existing = [r for r in store.list_all() if r.name == "morning-briefing"]
    if existing:
        return
    store.add(
        "morning briefing",
        ScheduleKind.DAILY,
        time_value,
        name="morning-briefing",
        action=RoutineAction.ASK,
    )
