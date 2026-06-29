"""Proactive routines for Eclipse, persisted in SQLite.

A routine is a recurring action ("cada mañana decime el resumen") that the wake
daemon fires when it comes due, recomputing the next run each time. Adding one is
deterministic; firing is done by ``fire_due_routines``, which the daemon polls
and which the ``routines-check`` command can also run.

Routines mirror reminders, but recur (daily at a local time, or every N seconds)
instead of firing once.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

_UNIT_SECONDS = {
    "s": 1, "seg": 1, "segs": 1, "segundo": 1, "segundos": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minuto": 60, "minutos": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hora": 3600, "horas": 3600, "hour": 3600, "hours": 3600,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RoutineAction(StrEnum):
    """What a routine does when it fires."""

    SAY = "say"
    ASK = "ask"


class ScheduleKind(StrEnum):
    """How a routine recurs."""

    DAILY = "daily"
    INTERVAL = "interval"


@dataclass(frozen=True, kw_only=True)
class Routine:
    """A recurring proactive routine."""

    name: str
    action: RoutineAction
    message: str
    schedule_kind: ScheduleKind
    schedule_value: str  # "HH:MM" for daily, seconds for interval
    next_run: datetime
    enabled: bool = True
    id: int | None = None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class RoutineRequest:
    """A parsed natural-language request to add a routine."""

    action: RoutineAction
    message: str
    schedule_kind: ScheduleKind
    schedule_value: str


def compute_next_run(
    kind: ScheduleKind, value: str, *, now: datetime | None = None
) -> datetime:
    """Compute the next UTC run time for a schedule.

    Daily times are interpreted in the machine's local timezone, so "08:00"
    means 8 AM where the user is, then stored as UTC.
    """

    moment = now or _utc_now()
    if kind is ScheduleKind.INTERVAL:
        return moment + timedelta(seconds=int(value))
    hour, _, minute = value.partition(":")
    local_now = moment.astimezone()
    candidate = local_now.replace(
        hour=int(hour), minute=int(minute or 0), second=0, microsecond=0
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


_ECLIPSE_PREFIX = re.compile(r"^\s*eclipse[,!.]?\s*", re.IGNORECASE)
_DAILY_TOKENS = (
    "cada mañana", "cada manana", "todas las mañanas", "todas las mananas",
    "cada día", "cada dia", "todos los días", "todos los dias",
    "cada noche", "todas las noches", "every morning", "every day",
)
_INTERVAL_RE = re.compile(
    r"\bcada\s+(\d+)\s*(segundos?|minutos?|horas?|seconds?|minutes?|hours?|"
    r"segs?|mins?|hrs?)\b",
    re.IGNORECASE,
)
_AT_TIME_RE = re.compile(r"\ba\s+las?\s+(\d{1,2})(?::(\d{2}))?\b", re.IGNORECASE)
_AT_TIME_EN_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", re.IGNORECASE)
_MESSAGE_MARKERS = (
    " decime que ", " decime ", " contame que ", " contame ",
    " recordame que ", " recordame ", " recuérdame ", " avisame que ", " avisame ",
    " tell me to ", " tell me ", " remind me to ", " remind me ",
)


def parse_routine_request(text: str) -> RoutineRequest | None:
    """Parse a spoken routine like 'cada mañana a las 8 decime el resumen'.

    Returns ``None`` unless the phrase recurs (``cada``/``todos los``/``every``),
    so one-shot reminders fall through to the reminder parser instead.
    """

    stripped = _ECLIPSE_PREFIX.sub("", text).strip()
    lowered = stripped.casefold()
    interval = _INTERVAL_RE.search(lowered)
    is_daily = any(token in lowered for token in _DAILY_TOKENS)
    if not interval and not is_daily:
        return None

    message = _extract_routine_message(stripped)
    if not message:
        return None

    if interval:
        seconds = int(interval.group(1)) * _UNIT_SECONDS.get(interval.group(2), 0)
        if seconds <= 0:
            return None
        return RoutineRequest(
            action=RoutineAction.SAY,
            message=message,
            schedule_kind=ScheduleKind.INTERVAL,
            schedule_value=str(seconds),
        )

    hour, minute = _parse_daily_time(lowered)
    return RoutineRequest(
        action=RoutineAction.SAY,
        message=message,
        schedule_kind=ScheduleKind.DAILY,
        schedule_value=f"{hour:02d}:{minute:02d}",
    )


def _parse_daily_time(lowered: str) -> tuple[int, int]:
    match = _AT_TIME_RE.search(lowered) or _AT_TIME_EN_RE.search(lowered)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if hour < 12 and ("noche" in lowered or "tarde" in lowered):
            hour += 12
        return hour % 24, minute
    if "noche" in lowered:
        return 21, 0
    if "tarde" in lowered:
        return 15, 0
    return 8, 0


def _extract_routine_message(text: str) -> str:
    lowered = text.casefold()
    for marker in _MESSAGE_MARKERS:
        index = lowered.find(marker)
        if index != -1:
            candidate = text[index + len(marker):].strip(" .,")
            if candidate:
                return candidate
    return ""


class RoutineStore:
    """SQLite-backed routine memory, keyed by name."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_routine_store_path()
        self._initialize()

    def add(
        self,
        message: str,
        schedule_kind: ScheduleKind,
        schedule_value: str,
        *,
        name: str | None = None,
        action: RoutineAction = RoutineAction.SAY,
        now: datetime | None = None,
    ) -> Routine:
        cleaned = " ".join(message.strip().split()) or "rutina"
        resolved_name = name or self._next_name()
        next_run = compute_next_run(schedule_kind, schedule_value, now=now)
        created = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO routines
                    (name, action, message, schedule_kind, schedule_value,
                     next_run, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(name) DO UPDATE SET
                    action = excluded.action,
                    message = excluded.message,
                    schedule_kind = excluded.schedule_kind,
                    schedule_value = excluded.schedule_value,
                    next_run = excluded.next_run,
                    enabled = 1
                """,
                (
                    resolved_name, str(action), cleaned, str(schedule_kind),
                    schedule_value, _to_iso(next_run), _to_iso(created),
                ),
            )
            row = connection.execute(
                "SELECT * FROM routines WHERE name = ?", (resolved_name,)
            ).fetchone()
        return _row_to_routine(row)

    def list_all(self) -> tuple[Routine, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM routines ORDER BY next_run ASC"
            ).fetchall()
        return tuple(_row_to_routine(row) for row in rows)

    def due(self, now: datetime | None = None) -> tuple[Routine, ...]:
        moment = now or _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM routines WHERE enabled = 1 AND next_run <= ? "
                "ORDER BY next_run ASC",
                (_to_iso(moment),),
            ).fetchall()
        return tuple(_row_to_routine(row) for row in rows)

    def mark_ran(self, name: str, next_run: datetime) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE routines SET next_run = ? WHERE name = ?",
                (_to_iso(next_run), name),
            )

    def remove(self, name: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM routines WHERE name = ?", (name,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM routines")
            return int(cursor.rowcount)

    def _next_name(self) -> str:
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM routines").fetchone()[0]
        return f"rutina-{int(count) + 1}"

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule_value TEXT NOT NULL,
                    next_run TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def fire_due_routines(
    store: RoutineStore,
    speak: Callable[[str], object],
    *,
    answer: Callable[[str], str] | None = None,
    briefing_resolver: Callable[[object], str | None] | None = None,
    now: datetime | None = None,
) -> tuple[Routine, ...]:
    """Run each due routine, speak its output, and reschedule it.

    ``answer`` resolves ``ask`` routines to spoken text; when omitted, an ``ask``
    routine just speaks its prompt.
    """

    moment = now or _utc_now()
    fired: list[Routine] = []
    for routine in store.due(moment):
        if briefing_resolver is not None:
            resolved = briefing_resolver(routine)
            if resolved is not None:
                speak(resolved)
                next_run = compute_next_run(
                    routine.schedule_kind, routine.schedule_value, now=moment
                )
                store.mark_ran(routine.name, next_run)
                fired.append(routine)
                continue
        speak(_routine_spoken(routine, answer))
        next_run = compute_next_run(
            routine.schedule_kind, routine.schedule_value, now=moment
        )
        store.mark_ran(routine.name, next_run)
        fired.append(routine)
    return tuple(fired)


def _routine_spoken(routine: Routine, answer: Callable[[str], str] | None) -> str:
    if routine.action is RoutineAction.ASK and answer is not None:
        try:
            return answer(routine.message)
        except Exception:  # noqa: BLE001
            return routine.message
    return routine.message


def default_routine_answer(prompt: str) -> str:
    """Resolve an ``ask`` routine through the configured LLM provider."""

    from eclipse_agent.answer import answer_question_from_env

    result = answer_question_from_env(prompt)
    return result.answer if result.success else result.message


def render_routines(routines: Iterable[Routine]) -> str:
    """Render routines for CLI display."""

    ordered = tuple(routines)
    if not ordered:
        return "No routines scheduled."
    lines = ["Scheduled routines:"]
    for routine in ordered:
        when = (
            f"daily at {routine.schedule_value}"
            if routine.schedule_kind is ScheduleKind.DAILY
            else f"every {routine.schedule_value}s"
        )
        lines.append(f"- {routine.name} [{when}] {routine.action}: {routine.message}")
    return "\n".join(lines)


def default_routine_store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "routines.sqlite3"


def _row_to_routine(row: sqlite3.Row) -> Routine:
    return Routine(
        id=int(row["id"]),
        name=str(row["name"]),
        action=RoutineAction(str(row["action"])),
        message=str(row["message"]),
        schedule_kind=ScheduleKind(str(row["schedule_kind"])),
        schedule_value=str(row["schedule_value"]),
        next_run=_from_iso(str(row["next_run"])),
        enabled=bool(row["enabled"]),
        created_at=_from_iso(str(row["created_at"])),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
