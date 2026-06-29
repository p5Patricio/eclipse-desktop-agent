"""Hermetic tests for morning_briefing.py — no real network, no real TTS."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from eclipse_agent.morning_briefing import BriefingConfig, BriefingResult, compose_briefing


class _FakeAnswerer:
    def __init__(self, *, response: str = "Good morning! Here is your briefing.") -> None:
        self._response = response

    def answer(self, question: str) -> object:
        result = MagicMock()
        result.success = True
        result.answer = self._response
        return result


_DATE = datetime(2026, 6, 29, 8, 0, 0)


def test_briefing_all_sources_ok() -> None:
    result = compose_briefing(
        BriefingConfig(),
        agenda_fn=lambda: "Meeting at 10 AM.",
        inbox_fn=lambda: "3 new emails.",
        weather_fn=lambda: "Currently 20°C and clear sky.",
        answerer=_FakeAnswerer(response="Good morning! Today is Monday. It is 20°C outside."),
        date_override=_DATE,
    )
    assert isinstance(result, BriefingResult)
    assert result.success is True
    assert result.text != ""
    assert result.calendar_ok is True
    assert result.inbox_ok is True
    assert result.weather_ok is True


def test_briefing_weather_failure_graceful() -> None:
    def bad_weather() -> str:
        raise RuntimeError("network error")

    result = compose_briefing(
        BriefingConfig(),
        agenda_fn=lambda: "Meeting at 10 AM.",
        inbox_fn=lambda: "3 new emails.",
        weather_fn=bad_weather,
        answerer=_FakeAnswerer(),
        date_override=_DATE,
    )
    assert result.success is True
    assert result.weather_ok is False
    assert result.calendar_ok is True


def test_briefing_calendar_failure_graceful() -> None:
    def bad_calendar() -> str:
        raise RuntimeError("calendar unreachable")

    result = compose_briefing(
        BriefingConfig(),
        agenda_fn=bad_calendar,
        inbox_fn=lambda: "1 new email.",
        weather_fn=lambda: "Sunny, 25°C.",
        answerer=_FakeAnswerer(),
        date_override=_DATE,
    )
    assert result.success is True
    assert result.calendar_ok is False
    assert result.inbox_ok is True


def test_briefing_includes_user_name() -> None:
    result = compose_briefing(
        BriefingConfig(),
        agenda_fn=lambda: "No events.",
        inbox_fn=lambda: "Inbox empty.",
        weather_fn=lambda: "Overcast, 18°C.",
        answerer=_FakeAnswerer(response="Good morning, Patricio! Today is sunny."),
        date_override=_DATE,
    )
    assert result.success is True
    assert "Patricio" in result.text


def test_briefing_all_sources_fail() -> None:
    def fail() -> str:
        raise RuntimeError("all down")

    result = compose_briefing(
        BriefingConfig(),
        agenda_fn=fail,
        inbox_fn=fail,
        weather_fn=fail,
        answerer=_FakeAnswerer(),
        date_override=_DATE,
    )
    assert result.success is False
    assert result.error != ""
