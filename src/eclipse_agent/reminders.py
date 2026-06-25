"""Timers and reminders for Eclipse, persisted in SQLite.

A reminder is text plus a due time. Setting one is deterministic; firing one
(speaking it when it comes due) is done by ``fire_due_reminders``, which the
wake daemon polls and which the ``reminders-check`` command can also run.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_UNIT_SECONDS = {
    "s": 1, "seg": 1, "segs": 1, "segundo": 1, "segundos": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minuto": 60, "minutos": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hora": 3600, "horas": 3600, "hour": 3600, "hours": 3600,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class Reminder:
    """A scheduled reminder."""

    text: str
    due_at: datetime
    id: int | None = None
    created_at: datetime = field(default_factory=_utc_now)
    fired: bool = False


@dataclass(frozen=True)
class ReminderRequest:
    """A parsed request to set a reminder."""

    delay_seconds: int
    text: str


def parse_reminder_request(text: str, *, now: datetime | None = None) -> ReminderRequest | None:
    """Parse a spoken reminder like 'recordame en 10 minutos que saque la pizza'."""

    lowered = text.casefold()
    match = re.search(
        r"(\d+)\s*(segundos?|minutos?|horas?|seconds?|minutes?|hours?|segs?|mins?|hrs?|h|m|s)\b",
        lowered,
    )
    if not match:
        return None
    amount = int(match.group(1))
    seconds = amount * _UNIT_SECONDS.get(match.group(2), 0)
    if seconds <= 0:
        return None
    return ReminderRequest(delay_seconds=seconds, text=_extract_reminder_text(text))


def _extract_reminder_text(text: str) -> str:
    lowered = text.casefold()
    for marker in (" de que ", " que ", " to ", " para "):
        index = lowered.find(marker)
        if index != -1:
            candidate = text[index + len(marker):].strip(" .,")
            if candidate:
                return candidate
    return "recordatorio"


class ReminderStore:
    """SQLite-backed reminder memory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_reminder_store_path()
        self._initialize()

    def add(self, text: str, due_at: datetime) -> Reminder:
        cleaned = " ".join(text.strip().split()) or "recordatorio"
        reminder = Reminder(text=cleaned, due_at=due_at)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reminders (text, due_at, created_at, fired) VALUES (?, ?, ?, 0)",
                (reminder.text, _to_iso(reminder.due_at), _to_iso(reminder.created_at)),
            )
        return Reminder(
            id=int(cursor.lastrowid),
            text=reminder.text,
            due_at=reminder.due_at,
            created_at=reminder.created_at,
        )

    def list_pending(self) -> tuple[Reminder, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE fired = 0 ORDER BY due_at ASC",
            ).fetchall()
        return tuple(_row_to_reminder(row) for row in rows)

    def due(self, now: datetime | None = None) -> tuple[Reminder, ...]:
        moment = now or _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE fired = 0 AND due_at <= ? ORDER BY due_at ASC",
                (_to_iso(moment),),
            ).fetchall()
        return tuple(_row_to_reminder(row) for row in rows)

    def mark_fired(self, reminder_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM reminders")
            return int(cursor.rowcount)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    fired INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def fire_due_reminders(
    store: ReminderStore,
    speak: Callable[[str], object],
    *,
    now: datetime | None = None,
) -> tuple[Reminder, ...]:
    """Speak each due reminder and mark it fired. Returns the fired reminders."""

    fired: list[Reminder] = []
    for reminder in store.due(now):
        speak(f"Recordatorio: {reminder.text}")
        if reminder.id is not None:
            store.mark_fired(reminder.id)
        fired.append(reminder)
    return tuple(fired)


def render_reminders(reminders: Iterable[Reminder]) -> str:
    """Render pending reminders for CLI display."""

    ordered = tuple(reminders)
    if not ordered:
        return "No pending reminders."
    lines = ["Pending reminders:"]
    for reminder in ordered:
        lines.append(f"- #{reminder.id} at {reminder.due_at.isoformat()}: {reminder.text}")
    return "\n".join(lines)


def default_reminder_store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "reminders.sqlite3"


def expires_after_seconds(seconds: int, *, now: datetime | None = None) -> datetime:
    return (now or _utc_now()) + timedelta(seconds=seconds)


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=int(row["id"]),
        text=str(row["text"]),
        due_at=_from_iso(str(row["due_at"])),
        created_at=_from_iso(str(row["created_at"])),
        fired=bool(row["fired"]),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
