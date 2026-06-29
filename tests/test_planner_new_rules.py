"""Tests for the new planner fast-layer rules added in PR 2."""

from __future__ import annotations

import pytest

from eclipse_agent.planner import ActionKind, _plan_clause


def _kind(clause: str) -> ActionKind:
    actions = _plan_clause(clause, 1)
    assert actions, f"No actions planned for: {clause!r}"
    return actions[0].kind


# --- WEATHER_QUERY tests ---

def test_weather_query_not_swallowed_by_qa() -> None:
    """CRITICAL: temperature/weather queries must NOT fall through to ANSWER_QUESTION."""
    assert _kind("qué temperatura hace hoy") is ActionKind.WEATHER_QUERY


def test_weather_query_english() -> None:
    assert _kind("what's the weather?") is ActionKind.WEATHER_QUERY


def test_weather_query_forecast() -> None:
    assert _kind("forecast for today") is ActionKind.WEATHER_QUERY


def test_weather_query_lluvia() -> None:
    assert _kind("va a llover hoy?") is ActionKind.WEATHER_QUERY


def test_weather_query_hace_calor() -> None:
    assert _kind("hace calor hoy") is ActionKind.WEATHER_QUERY


# --- SCREEN_ASK tests ---

def test_screen_ask_matches_what_on_screen() -> None:
    assert _kind("qué dice mi pantalla") is ActionKind.SCREEN_ASK


def test_screen_ask_matches_english() -> None:
    assert _kind("what's on my screen?") is ActionKind.SCREEN_ASK


def test_screen_ask_analyze() -> None:
    assert _kind("analyze my screen") is ActionKind.SCREEN_ASK


def test_screenshot_bare_not_screen_ask() -> None:
    """Bare 'screenshot' must still match SCREENSHOT, not SCREEN_ASK."""
    assert _kind("screenshot") is ActionKind.SCREENSHOT


# --- MORNING_BRIEFING tests ---

def test_morning_briefing_buenos_dias() -> None:
    assert _kind("buenos dias") is ActionKind.MORNING_BRIEFING


def test_morning_briefing_good_morning() -> None:
    assert _kind("good morning") is ActionKind.MORNING_BRIEFING


def test_morning_briefing_keyword() -> None:
    assert _kind("morning briefing") is ActionKind.MORNING_BRIEFING


def test_morning_briefing_briefing_keyword() -> None:
    assert _kind("briefing") is ActionKind.MORNING_BRIEFING


# --- SEND_EMAIL tests ---

def test_send_email_matches_english() -> None:
    assert _kind("send email to boss about the meeting") is ActionKind.SEND_EMAIL


def test_send_email_matches_spanish() -> None:
    assert _kind("mandá un email a juan") is ActionKind.SEND_EMAIL


def test_send_email_mandar_mail() -> None:
    assert _kind("mandar mail a maria sobre el proyecto") is ActionKind.SEND_EMAIL


# --- Priority / regression tests ---

def test_what_time_is_it_still_qa() -> None:
    """'what time is it' must NOT match weather."""
    assert _kind("what time is it") is ActionKind.ANSWER_QUESTION


def test_buenos_dias_not_agenda() -> None:
    """'buenos dias' should be MORNING_BRIEFING, not READ_AGENDA."""
    assert _kind("buenos dias") is not ActionKind.READ_AGENDA
