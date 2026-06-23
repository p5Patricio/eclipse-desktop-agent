"""Notification capture, focus rules, and digest primitives for Eclipse.

This module is intentionally dependency-free. The first implementation focuses on
the deterministic core Eclipse needs before wiring a long-running D-Bus listener:

- normalize native and browser/web notifications into one event model,
- decide whether to announce, queue, ignore, or redact them,
- persist local state in SQLite,
- produce a human-friendly Spanish digest after focus/game mode.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from eclipse_agent.voice import SpeechResult, SystemTTS, shlex_join


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationStatus(StrEnum):
    """Lifecycle state for a captured notification."""

    NEW = "new"
    ANNOUNCED = "announced"
    QUEUED = "queued"
    DISMISSED = "dismissed"
    REPLIED = "replied"
    IGNORED = "ignored"


class NotificationPrivacyLevel(StrEnum):
    """How much notification content Eclipse is allowed to persist."""

    FULL = "full"
    METADATA_ONLY = "metadata_only"
    REDACTED = "redacted"


class NotificationUrgency(StrEnum):
    """Freedesktop notification urgency normalized for Eclipse."""

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


class NotificationFocusMode(StrEnum):
    """Modes that control whether Eclipse interrupts the user."""

    NORMAL = "normal"
    FOCUS = "focus"
    GAME = "game"
    PRIVATE = "private"


class NotificationAction(StrEnum):
    """Decision made for one incoming notification."""

    ANNOUNCE = "announce"
    QUEUE = "queue"
    IGNORE = "ignore"
    METADATA_ONLY = "metadata_only"


class NotificationSourceKind(StrEnum):
    """Best-effort source family for a notification."""

    WEB = "web"
    NATIVE = "native"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class NotificationSource:
    """Normalized source information for native and web notifications."""

    kind: NotificationSourceKind
    label: str


@dataclass(frozen=True, kw_only=True)
class NotificationEvent:
    """A normalized notification event captured from desktop or web apps."""

    app_name: str
    summary: str
    body: str = ""
    desktop_entry: str | None = None
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    source_window: str | None = None
    status: NotificationStatus = NotificationStatus.NEW
    privacy_level: NotificationPrivacyLevel = NotificationPrivacyLevel.FULL
    source_kind: NotificationSourceKind = NotificationSourceKind.UNKNOWN
    source_label: str | None = None
    received_at: datetime = field(default_factory=_utc_now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def display_source(self) -> str:
        """Return the most useful label to speak or show in digests."""

        return self.source_label or self.app_name

    def with_status(self, status: NotificationStatus) -> NotificationEvent:
        """Return this event with an updated status."""

        return replace(self, status=status)

    def as_metadata_only(self, *, status: NotificationStatus) -> NotificationEvent:
        """Return a privacy-preserving copy without message content."""

        return replace(
            self,
            summary=f"Notificación de {self.display_source}",
            body="",
            status=status,
            privacy_level=NotificationPrivacyLevel.METADATA_ONLY,
        )


@dataclass(frozen=True, kw_only=True)
class NotificationRule:
    """A user rule for an app/source in one mode or all modes."""

    app_pattern: str
    action: NotificationAction
    mode: str = "any"
    expires_at: datetime | None = None
    id: int | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        """Return whether the rule has not expired."""

        now = now or _utc_now()
        return self.expires_at is None or self.expires_at > now

    def matches(
        self,
        event: NotificationEvent,
        mode: NotificationFocusMode,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether this rule applies to the event and current mode."""

        if not self.is_active(now):
            return False
        normalized_mode = self.mode.casefold().strip()
        if normalized_mode not in {"any", "all", "*"} and normalized_mode != mode.value:
            return False
        return notification_matches_pattern(event, self.app_pattern)


@dataclass(frozen=True, kw_only=True)
class NotificationRuntimeState:
    """Persisted interruption mode for the notification engine."""

    mode: NotificationFocusMode = NotificationFocusMode.NORMAL
    mode_expires_at: datetime | None = None

    def active_mode(self, now: datetime | None = None) -> NotificationFocusMode:
        """Return normal mode if the temporary focus mode has expired."""

        now = now or _utc_now()
        if self.mode_expires_at and self.mode_expires_at <= now:
            return NotificationFocusMode.NORMAL
        return self.mode


@dataclass(frozen=True, kw_only=True)
class NotificationProcessingResult:
    """Outcome of processing one notification."""

    event: NotificationEvent
    action: NotificationAction
    mode: NotificationFocusMode
    stored_event: NotificationEvent | None
    message: str
    speech: SpeechResult | None = None
    persisted: bool = False


@dataclass(frozen=True, kw_only=True)
class NotificationDigest:
    """Summary of queued/pending notifications."""

    total: int
    by_source: dict[str, int]
    items: tuple[NotificationEvent, ...]

    def render(self) -> str:
        """Render a compact Spanish digest for CLI/TTS."""

        if self.total == 0:
            return "No tienes notificaciones pendientes."

        source_bits = ", ".join(
            f"{count} de {source}" for source, count in sorted(self.by_source.items())
        )
        lines = [f"Tienes {self.total} notificación(es) pendiente(s): {source_bits}."]
        for event in self.items:
            detail = event.summary
            if event.privacy_level is NotificationPrivacyLevel.METADATA_ONLY:
                detail = "contenido privado oculto"
            elif event.body:
                detail = f"{event.summary}: {event.body}"
            lines.append(f"- {event.display_source}: {_truncate(detail, 160)}")
        return "\n".join(lines)


class NotificationRulesEngine:
    """Decide how Eclipse handles notifications in the current focus mode."""

    def __init__(self, rules: Iterable[NotificationRule] = ()) -> None:
        self.rules = tuple(rules)

    def decide(
        self,
        event: NotificationEvent,
        mode: NotificationFocusMode,
        *,
        now: datetime | None = None,
    ) -> NotificationAction:
        """Return the action for an event under the current mode."""

        for rule in self.rules:
            if rule.matches(event, mode, now=now):
                return rule.action

        if mode is NotificationFocusMode.NORMAL:
            return NotificationAction.ANNOUNCE
        if mode is NotificationFocusMode.PRIVATE:
            return NotificationAction.METADATA_ONLY
        return NotificationAction.QUEUE


class NotificationStore:
    """SQLite-backed local notification memory.

    SQLite remains the default operational store because notification handling is a
    small transactional workload: insert events, update status/rules, and read the
    pending queue. DuckDB is still a good candidate later for analytical exports
    over larger histories, but not for this hot application-state path.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_notification_store_path()
        self._initialize()

    def save_event(self, event: NotificationEvent) -> NotificationEvent:
        """Persist or replace a notification event."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO notifications (
                    id, received_at, app_name, desktop_entry, summary, body, urgency,
                    source_window, status, privacy_level, source_kind, source_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    _to_iso(event.received_at),
                    event.app_name,
                    event.desktop_entry,
                    event.summary,
                    event.body,
                    event.urgency.value,
                    event.source_window,
                    event.status.value,
                    event.privacy_level.value,
                    event.source_kind.value,
                    event.source_label,
                ),
            )
        return event

    def update_event_status(
        self,
        event_id: str,
        status: NotificationStatus,
    ) -> NotificationEvent | None:
        """Update one event status and return the refreshed event."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE notifications SET status = ? WHERE id = ?",
                (status.value, event_id),
            )
        return self.get_event(event_id)

    def get_event(self, event_id: str) -> NotificationEvent | None:
        """Load one event by id."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notifications WHERE id = ?",
                (event_id,),
            ).fetchone()
        return _row_to_event(row) if row else None

    def list_events(
        self,
        *,
        statuses: Iterable[NotificationStatus] | None = None,
        limit: int = 50,
    ) -> tuple[NotificationEvent, ...]:
        """List events, newest first."""

        query = "SELECT * FROM notifications"
        params: list[str | int] = []
        if statuses:
            status_values = [status.value for status in statuses]
            placeholders = ",".join("?" for _ in status_values)
            query += f" WHERE status IN ({placeholders})"
            params.extend(status_values)
        query += " ORDER BY received_at DESC LIMIT ?"
        params.append(max(1, limit))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_row_to_event(row) for row in rows)

    def list_pending(self, *, limit: int = 50) -> tuple[NotificationEvent, ...]:
        """Return queued/new notifications for a later digest."""

        return self.list_events(
            statuses=(NotificationStatus.NEW, NotificationStatus.QUEUED),
            limit=limit,
        )

    def delete_events(
        self,
        *,
        statuses: Iterable[NotificationStatus] | None = None,
    ) -> int:
        """Delete events matching statuses, or all events when statuses is None."""

        with self._connect() as connection:
            if not statuses:
                cursor = connection.execute("DELETE FROM notifications")
                return int(cursor.rowcount)

            status_values = tuple(status.value for status in statuses)
            cursor = connection.executemany(
                "DELETE FROM notifications WHERE status = ?",
                tuple((status,) for status in status_values),
            )
            return int(cursor.rowcount)

    def mark_events(
        self,
        event_ids: Iterable[str],
        status: NotificationStatus,
    ) -> int:
        """Update multiple events and return how many rows changed."""

        ids = tuple(event_ids)
        if not ids:
            return 0
        with self._connect() as connection:
            cursor = connection.executemany(
                "UPDATE notifications SET status = ? WHERE id = ?",
                tuple((status.value, event_id) for event_id in ids),
            )
            return int(cursor.rowcount)

    def save_rule(self, rule: NotificationRule) -> NotificationRule:
        """Persist a notification rule."""

        with self._connect() as connection:
            if rule.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO notification_rules (
                        app_pattern, action, mode, expires_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        rule.app_pattern,
                        rule.action.value,
                        rule.mode,
                        _to_iso(rule.expires_at),
                    ),
                )
                return replace(rule, id=int(cursor.lastrowid))

            connection.execute(
                """
                INSERT OR REPLACE INTO notification_rules (
                    id, app_pattern, action, mode, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.app_pattern,
                    rule.action.value,
                    rule.mode,
                    _to_iso(rule.expires_at),
                ),
            )
        return rule

    def list_rules(self, *, include_expired: bool = False) -> tuple[NotificationRule, ...]:
        """Return persisted rules."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notification_rules ORDER BY id ASC",
            ).fetchall()
        rules = tuple(_row_to_rule(row) for row in rows)
        if include_expired:
            return rules
        now = _utc_now()
        return tuple(rule for rule in rules if rule.is_active(now))

    def set_focus_mode(
        self,
        mode: NotificationFocusMode,
        *,
        expires_at: datetime | None = None,
    ) -> NotificationRuntimeState:
        """Persist the current interruption mode."""

        self._set_state_value("focus_mode", mode.value)
        self._set_state_value("focus_mode_expires_at", _to_iso(expires_at) or "")
        return NotificationRuntimeState(mode=mode, mode_expires_at=expires_at)

    def get_runtime_state(self, *, now: datetime | None = None) -> NotificationRuntimeState:
        """Return the persisted focus state, resetting expired modes to normal."""

        raw_mode = self._get_state_value("focus_mode") or NotificationFocusMode.NORMAL.value
        raw_expires_at = self._get_state_value("focus_mode_expires_at") or None
        state = NotificationRuntimeState(
            mode=NotificationFocusMode(raw_mode),
            mode_expires_at=_from_iso(raw_expires_at),
        )
        expired = state.active_mode(now) is NotificationFocusMode.NORMAL
        if expired and state.mode is not NotificationFocusMode.NORMAL:
            return self.set_focus_mode(NotificationFocusMode.NORMAL)
        return state

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    app_name TEXT NOT NULL,
                    desktop_entry TEXT,
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    source_window TEXT,
                    status TEXT NOT NULL,
                    privacy_level TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_label TEXT
                );

                CREATE TABLE IF NOT EXISTS notification_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    expires_at TEXT
                );

                CREATE TABLE IF NOT EXISTS notification_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _set_state_value(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO notification_state (key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )

    def _get_state_value(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM notification_state WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else None


class NotificationCenter:
    """Orchestrate notification decisions, persistence, and announcements."""

    def __init__(
        self,
        *,
        store: NotificationStore | None = None,
        tts: SystemTTS | None = None,
    ) -> None:
        self.store = store or NotificationStore()
        self.tts = tts or SystemTTS()

    def ingest(
        self,
        event: NotificationEvent,
        *,
        speak: bool = False,
        persist: bool = True,
        now: datetime | None = None,
    ) -> NotificationProcessingResult:
        """Process one notification through rules, store, and optional TTS."""

        now = now or _utc_now()
        state = self.store.get_runtime_state(now=now)
        mode = state.active_mode(now)
        action = NotificationRulesEngine(self.store.list_rules()).decide(event, mode, now=now)

        stored_event: NotificationEvent | None
        speech: SpeechResult | None = None
        if action is NotificationAction.ANNOUNCE:
            stored_event = event.with_status(NotificationStatus.ANNOUNCED)
            speech = self.tts.speak(build_notification_announcement(event), dry_run=not speak)
            message = (
                "Notification announced."
                if speak
                else "Notification prepared for announcement."
            )
        elif action is NotificationAction.QUEUE:
            stored_event = event.with_status(NotificationStatus.QUEUED)
            message = "Notification queued because Eclipse should not interrupt now."
        elif action is NotificationAction.METADATA_ONLY:
            stored_event = event.as_metadata_only(status=NotificationStatus.QUEUED)
            message = "Notification queued with metadata only for privacy."
        else:
            stored_event = event.as_metadata_only(status=NotificationStatus.IGNORED)
            message = "Notification ignored by rule; metadata retained for audit."

        if persist:
            self.store.save_event(stored_event)

        return NotificationProcessingResult(
            event=event,
            action=action,
            mode=mode,
            stored_event=stored_event if persist else None,
            speech=speech,
            message=message,
            persisted=persist,
        )


def create_notification_event(
    *,
    app_name: str,
    summary: str,
    body: str = "",
    desktop_entry: str | None = None,
    urgency: NotificationUrgency | str = NotificationUrgency.NORMAL,
    source_window: str | None = None,
    received_at: datetime | None = None,
) -> NotificationEvent:
    """Normalize raw desktop/web notification fields into an Eclipse event."""

    source = normalize_notification_source(
        app_name=app_name,
        desktop_entry=desktop_entry,
        summary=summary,
        body=body,
        source_window=source_window,
    )
    return NotificationEvent(
        app_name=_clean_required(app_name, "app_name"),
        desktop_entry=_clean_optional(desktop_entry),
        summary=_clean_required(summary, "summary"),
        body=_clean_optional(body) or "",
        urgency=NotificationUrgency(urgency),
        source_window=_clean_optional(source_window),
        source_kind=source.kind,
        source_label=source.label,
        received_at=received_at or _utc_now(),
    )


def normalize_notification_source(
    *,
    app_name: str,
    desktop_entry: str | None = None,
    summary: str = "",
    body: str = "",
    source_window: str | None = None,
) -> NotificationSource:
    """Best-effort source normalization for browser web notifications and native apps."""

    app = _clean_required(app_name, "app_name")
    haystack = " ".join(
        value
        for value in (app, desktop_entry or "", summary, body, source_window or "")
        if value
    ).casefold()
    app_haystack = " ".join(value for value in (app, desktop_entry or "") if value).casefold()

    web_label = _detect_known_web_label(haystack)
    if _looks_like_browser(app_haystack):
        return NotificationSource(
            kind=NotificationSourceKind.WEB,
            label=web_label or _title_label(source_window) or app,
        )
    if web_label:
        return NotificationSource(kind=NotificationSourceKind.WEB, label=web_label)
    return NotificationSource(kind=NotificationSourceKind.NATIVE, label=app)


def notification_matches_pattern(event: NotificationEvent, pattern: str) -> bool:
    """Match a user app/source pattern against all source-identifying fields."""

    normalized_pattern = _normalize_match_text(pattern)
    if not normalized_pattern:
        return False
    fields = (
        event.app_name,
        event.desktop_entry or "",
        event.source_window or "",
        event.source_label or "",
        event.summary,
    )
    return any(normalized_pattern in _normalize_match_text(field) for field in fields)


def build_notification_announcement(event: NotificationEvent) -> str:
    """Build the short text Eclipse should speak for one notification."""

    source_type = "web" if event.source_kind is NotificationSourceKind.WEB else "de app"
    detail = event.summary
    if event.body:
        detail = f"{event.summary}: {event.body}"
    return _truncate(
        f"Tienes una notificación {source_type} de {event.display_source}. {detail}",
        260,
    )


def build_notification_digest(
    events: Iterable[NotificationEvent],
    *,
    max_items: int = 5,
) -> NotificationDigest:
    """Build a digest for queued notifications."""

    ordered = tuple(events)
    by_source: dict[str, int] = {}
    for event in ordered:
        by_source[event.display_source] = by_source.get(event.display_source, 0) + 1
    return NotificationDigest(
        total=len(ordered),
        by_source=by_source,
        items=ordered[: max(1, max_items)],
    )


def render_notification_processing_result(result: NotificationProcessingResult) -> str:
    """Render notification processing for CLI output."""

    status = "stored" if result.persisted else "preview"
    lines = [
        (
            f"Notification [{status}] {result.action.value} in {result.mode.value} mode: "
            f"{result.message}"
        )
    ]
    lines.append(f"source: {result.event.display_source} ({result.event.source_kind.value})")
    if result.stored_event:
        lines.append(f"event_id: {result.stored_event.id}")
        lines.append(f"status: {result.stored_event.status.value}")
        lines.append(f"privacy: {result.stored_event.privacy_level.value}")
    if result.speech:
        speech_status = "executed" if result.speech.executed else "prepared"
        if not result.speech.success:
            speech_status = "failed"
        lines.append(f"tts: {speech_status} via {result.speech.provider}")
        if result.speech.command:
            lines.append(f"tts_command: {shlex_join(result.speech.command)}")
    return "\n".join(lines)


def render_notification_events(events: Iterable[NotificationEvent]) -> str:
    """Render notifications for CLI review."""

    ordered = tuple(events)
    if not ordered:
        return "No notifications found."

    lines = ["Eclipse notifications:"]
    for event in ordered:
        detail = event.summary
        if event.privacy_level is NotificationPrivacyLevel.METADATA_ONLY:
            detail = "contenido privado oculto"
        elif event.body:
            detail = f"{event.summary}: {event.body}"
        lines.append(
            f"- {event.id} [{event.status.value}] {event.display_source} "
            f"({event.source_kind.value}) — {_truncate(detail, 140)}"
        )
    return "\n".join(lines)


def default_notification_store_path() -> Path:
    """Return the local-first notification database path under %LOCALAPPDATA%."""

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "notifications.sqlite3"


def expires_after_minutes(minutes: int | None, *, now: datetime | None = None) -> datetime | None:
    """Return an expiration timestamp for temporary rules/modes."""

    if minutes is None or minutes <= 0:
        return None
    return (now or _utc_now()) + timedelta(minutes=minutes)


def _row_to_event(row: sqlite3.Row) -> NotificationEvent:
    return NotificationEvent(
        id=str(row["id"]),
        received_at=_from_iso(str(row["received_at"])) or _utc_now(),
        app_name=str(row["app_name"]),
        desktop_entry=row["desktop_entry"],
        summary=str(row["summary"]),
        body=str(row["body"]),
        urgency=NotificationUrgency(str(row["urgency"])),
        source_window=row["source_window"],
        status=NotificationStatus(str(row["status"])),
        privacy_level=NotificationPrivacyLevel(str(row["privacy_level"])),
        source_kind=NotificationSourceKind(str(row["source_kind"])),
        source_label=row["source_label"],
    )


def _row_to_rule(row: sqlite3.Row) -> NotificationRule:
    return NotificationRule(
        id=int(row["id"]),
        app_pattern=str(row["app_pattern"]),
        action=NotificationAction(str(row["action"])),
        mode=str(row["mode"]),
        expires_at=_from_iso(row["expires_at"]),
    )


def _looks_like_browser(value: str) -> bool:
    return any(
        browser in value
        for browser in (
            "chrome",
            "chromium",
            "firefox",
            "brave",
            "vivaldi",
            "edge",
            "browser",
        )
    )


def _detect_known_web_label(value: str) -> str | None:
    known = {
        "instagram": "Instagram",
        "messenger": "Messenger",
        "facebook": "Facebook",
        "whatsapp": "WhatsApp",
        "gmail": "Gmail",
        "youtube music": "YouTube Music",
        "youtube": "YouTube",
        "x.com": "X",
        "twitter": "X",
        "discord": "Discord",
        "slack": "Slack",
    }
    for needle, label in known.items():
        if needle in value:
            return label
    return None


def _title_label(value: str | None) -> str | None:
    cleaned = _clean_optional(value)
    if not cleaned:
        return None
    if " - " in cleaned:
        return cleaned.split(" - ", 1)[0].strip() or cleaned
    return cleaned


def _normalize_match_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _clean_required(value: str, field_name: str) -> str:
    cleaned = _clean_optional(value)
    if not cleaned:
        raise ValueError(f"{field_name} is required.")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def _truncate(value: str, max_length: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
