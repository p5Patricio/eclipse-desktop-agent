"""Reviewable audit log of the actions Eclipse routes.

The security model promises a record of intent, plan, tool, result and
confirmation for every action. The ``ToolRouter`` writes one ``AuditEntry`` per
routed action (executed, prepared, blocked, failed or killed) to a local SQLite
log the user can review or clear.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class AuditEntry:
    """One audited action."""

    action_kind: str
    target: str
    risk_level: str
    status: str  # executed | prepared | blocked | failed | killed
    tool_name: str
    detail: str = ""
    id: int | None = None
    timestamp: datetime = field(default_factory=_utc_now)


class AuditLog:
    """SQLite-backed audit log of routed actions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_audit_log_path()
        self._initialize()

    def record(self, entry: AuditEntry) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit
                    (timestamp, action_kind, target, risk_level, status, tool_name, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _to_iso(entry.timestamp),
                    entry.action_kind,
                    entry.target,
                    entry.risk_level,
                    entry.status,
                    entry.tool_name,
                    entry.detail,
                ),
            )

    def recent(self, limit: int = 20) -> tuple[AuditEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(_row_to_entry(row) for row in rows)

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0])

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM audit")
            return int(cursor.rowcount)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action_kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def render_audit_entries(entries: Iterable[AuditEntry]) -> str:
    """Render audit entries for CLI display, newest first."""

    ordered = tuple(entries)
    if not ordered:
        return "No audited actions yet."
    lines = ["Recent actions:"]
    for entry in ordered:
        lines.append(
            f"- {entry.timestamp.isoformat()} [{entry.status}] {entry.action_kind} "
            f"-> {entry.target} ({entry.risk_level}) via {entry.tool_name}"
        )
    return "\n".join(lines)


def default_audit_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "audit.sqlite3"


def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        id=int(row["id"]),
        timestamp=_from_iso(str(row["timestamp"])),
        action_kind=str(row["action_kind"]),
        target=str(row["target"]),
        risk_level=str(row["risk_level"]),
        status=str(row["status"]),
        tool_name=str(row["tool_name"]),
        detail=str(row["detail"]),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
