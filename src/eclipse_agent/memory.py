"""Persistent fact and preference memory for Eclipse, stored in SQLite.

Eclipse remembers facts the user shares ("my name is Patricio", "my favourite
colour is blue") and recalls them across sessions. Storing and recalling are
deterministic; the natural-language layer lives in ``parse_memory_request``,
mirroring how reminders are parsed in :mod:`eclipse_agent.reminders`.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryIntent(StrEnum):
    """What the user wants to do with their stored memory."""

    REMEMBER = "remember"
    RECALL = "recall"


@dataclass(frozen=True, kw_only=True)
class MemoryFact:
    """A single remembered fact, keyed by a normalized topic."""

    key: str
    value: str
    id: int | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class MemoryRequest:
    """A parsed natural-language memory request."""

    intent: MemoryIntent
    key: str
    value: str = ""


_ECLIPSE_PREFIX = re.compile(r"^\s*eclipse[,!.]?\s*", re.IGNORECASE)
_FORGET_RE = re.compile(
    r"^(?:olvid[aá]te?(?:\s+de)?|olvid[aá]|forget)\s+(?:mi|my)\s+(.+)$",
    re.IGNORECASE,
)
_RECALL_ALL_TOKENS = (
    "qué recordás", "que recordas", "qué sabés de mí", "que sabes de mi",
    "qué sabes de mí", "what do you remember", "what do you know about me",
)
_CALL_ME_RE = re.compile(r"\bc[oó]mo\s+me\s+llamo\b", re.IGNORECASE)
_RECALL_ES_RE = re.compile(r"\b(?:cu[aá]l|qu[eé])\s+es\s+mi\s+(.+)$", re.IGNORECASE)
_RECALL_EN_RE = re.compile(r"\bwhat(?:'?s| is)\s+my\s+(.+)$", re.IGNORECASE)
_CALL_ME_NAME_RE = re.compile(r"\bme\s+llamo\s+(.+)$", re.IGNORECASE)
_MI_ES_RE = re.compile(r"\bmi\s+(.+?)\s+es\s+(.+)$", re.IGNORECASE)
_MY_IS_RE = re.compile(r"\bmy\s+(.+?)\s+is\s+(.+)$", re.IGNORECASE)


def normalize_key(key: str) -> str:
    """Normalize a memory key for stable, case-insensitive lookup."""

    cleaned = " ".join(key.casefold().split())
    return cleaned.strip(" ?!.,¿¡")


def _clean_value(value: str) -> str:
    return value.strip().strip("\"'").strip(" .?!,")


def parse_memory_request(text: str) -> MemoryRequest | None:
    """Parse a spoken memory request like 'mi nombre es Patricio'.

    Recall is checked before remember so that questions such as
    "¿cuál es mi nombre?" are not mistaken for an assignment.
    """

    stripped = _ECLIPSE_PREFIX.sub("", text).strip()
    if not stripped:
        return None
    lowered = stripped.casefold()

    if any(token in lowered for token in _RECALL_ALL_TOKENS):
        return MemoryRequest(intent=MemoryIntent.RECALL, key="")
    if _CALL_ME_RE.search(stripped):
        return MemoryRequest(intent=MemoryIntent.RECALL, key="nombre")
    recall = _RECALL_ES_RE.search(stripped) or _RECALL_EN_RE.search(stripped)
    if recall:
        return MemoryRequest(intent=MemoryIntent.RECALL, key=normalize_key(recall.group(1)))

    name = _CALL_ME_NAME_RE.search(stripped)
    if name:
        return MemoryRequest(
            intent=MemoryIntent.REMEMBER, key="nombre", value=_clean_value(name.group(1))
        )
    assign = _MI_ES_RE.search(stripped) or _MY_IS_RE.search(stripped)
    if assign:
        value = _clean_value(assign.group(2))
        if value:
            return MemoryRequest(
                intent=MemoryIntent.REMEMBER,
                key=normalize_key(assign.group(1)),
                value=value,
            )
    return None


class MemoryStore:
    """SQLite-backed fact memory, keyed by a normalized topic."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_memory_store_path()
        self._initialize()

    def remember(self, key: str, value: str) -> MemoryFact:
        normalized = normalize_key(key)
        cleaned_value = " ".join(value.strip().split())
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO facts (key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (normalized, cleaned_value, _to_iso(now), _to_iso(now)),
            )
            row = connection.execute(
                "SELECT * FROM facts WHERE key = ?", (normalized,)
            ).fetchone()
        return _row_to_fact(row)

    def recall(self, key: str) -> MemoryFact | None:
        normalized = normalize_key(key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM facts WHERE key = ?", (normalized,)
            ).fetchone()
        return _row_to_fact(row) if row else None

    def search(self, query: str) -> tuple[MemoryFact, ...]:
        needle = f"%{query.casefold().strip()}%"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY key ASC",
                (needle, needle),
            ).fetchall()
        return tuple(_row_to_fact(row) for row in rows)

    def list_all(self) -> tuple[MemoryFact, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM facts ORDER BY key ASC").fetchall()
        return tuple(_row_to_fact(row) for row in rows)

    def forget(self, key: str) -> bool:
        normalized = normalize_key(key)
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM facts WHERE key = ?", (normalized,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM facts")
            return int(cursor.rowcount)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def spoken_fact(key: str, value: str) -> str:
    """A natural spoken sentence for a single recalled fact."""

    if key == "nombre":
        return f"Te llamás {value}."
    return f"Tu {key} es {value}."


def spoken_facts(facts: Iterable[MemoryFact]) -> str:
    """A spoken summary of every remembered fact."""

    ordered = tuple(facts)
    if not ordered:
        return "Todavía no tengo nada guardado sobre vos."
    parts = [f"tu {fact.key} es {fact.value}" for fact in ordered]
    return "Esto es lo que recuerdo: " + ", ".join(parts) + "."


def render_memory_facts(facts: Iterable[MemoryFact]) -> str:
    """Render remembered facts for CLI display."""

    ordered = tuple(facts)
    if not ordered:
        return "No remembered facts yet."
    lines = ["Remembered facts:"]
    for fact in ordered:
        lines.append(f"- {fact.key}: {fact.value}")
    return "\n".join(lines)


def default_memory_store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "memory.sqlite3"


def _row_to_fact(row: sqlite3.Row) -> MemoryFact:
    return MemoryFact(
        id=int(row["id"]),
        key=str(row["key"]),
        value=str(row["value"]),
        created_at=_from_iso(str(row["created_at"])),
        updated_at=_from_iso(str(row["updated_at"])),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
