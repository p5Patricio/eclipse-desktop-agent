"""SQLite telemetry for Eclipse planning and routing decisions."""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path


class TelemetryLayer(StrEnum):
    """Planning layer that handled a user instruction."""

    FAST_LAYER = "fast_layer"
    SMART_LAYER = "smart_layer"


@dataclass(frozen=True, kw_only=True)
class TelemetryRecord:
    """One completed planning request telemetry row."""

    id: str
    timestamp: datetime
    instruction: str
    layer_used: TelemetryLayer
    success_status: bool


@dataclass(frozen=True, kw_only=True)
class SmartLayerFallback:
    """Aggregated smart-layer fallback count for one instruction."""

    instruction: str
    count: int


@dataclass(frozen=True, kw_only=True)
class TelemetrySummary:
    """Aggregated telemetry metrics for CLI reporting."""

    days: int
    total_requests: int
    fast_layer_requests: int
    smart_layer_requests: int
    top_smart_layer_instructions: tuple[SmartLayerFallback, ...]

    @property
    def fast_layer_percentage(self) -> float:
        """Return fast-layer share as a percentage."""

        return _percentage(self.fast_layer_requests, self.total_requests)

    @property
    def smart_layer_percentage(self) -> float:
        """Return smart-layer share as a percentage."""

        return _percentage(self.smart_layer_requests, self.total_requests)


class ExecutionTelemetryStore:
    """SQLite-backed telemetry store for Eclipse execution metrics."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_telemetry_store_path()
        self._initialize()

    def log_execution(
        self,
        *,
        instruction: str,
        layer_used: TelemetryLayer,
        success_status: bool,
        timestamp: datetime | None = None,
    ) -> TelemetryRecord:
        """Persist telemetry for one completed instruction."""

        record = TelemetryRecord(
            id=uuid.uuid4().hex,
            timestamp=timestamp or _utc_now(),
            instruction=" ".join(instruction.strip().split()),
            layer_used=layer_used,
            success_status=success_status,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_telemetry (
                    id, timestamp, instruction, layer_used, success_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    _to_iso(record.timestamp),
                    record.instruction,
                    record.layer_used.value,
                    int(record.success_status),
                ),
            )
        return record

    def summarize(self, *, days: int = 5) -> TelemetrySummary:
        """Return aggregate telemetry metrics for the requested period."""

        bounded_days = max(1, days)
        since = _utc_now() - timedelta(days=bounded_days)
        with self._connect() as connection:
            layer_rows = connection.execute(
                """
                SELECT layer_used, COUNT(*) AS count
                FROM execution_telemetry
                WHERE timestamp >= ?
                GROUP BY layer_used
                """,
                (_to_iso(since),),
            ).fetchall()
            top_rows = connection.execute(
                """
                SELECT instruction, COUNT(*) AS count
                FROM execution_telemetry
                WHERE timestamp >= ? AND layer_used = ?
                GROUP BY instruction
                ORDER BY count DESC, instruction ASC
                LIMIT 5
                """,
                (_to_iso(since), TelemetryLayer.SMART_LAYER.value),
            ).fetchall()

        counts = {str(row["layer_used"]): int(row["count"]) for row in layer_rows}
        fast_count = counts.get(TelemetryLayer.FAST_LAYER.value, 0)
        smart_count = counts.get(TelemetryLayer.SMART_LAYER.value, 0)
        return TelemetrySummary(
            days=bounded_days,
            total_requests=fast_count + smart_count,
            fast_layer_requests=fast_count,
            smart_layer_requests=smart_count,
            top_smart_layer_instructions=tuple(
                SmartLayerFallback(
                    instruction=str(row["instruction"]),
                    count=int(row["count"]),
                )
                for row in top_rows
            ),
        )

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_telemetry (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    instruction TEXT NOT NULL,
                    layer_used TEXT NOT NULL CHECK (
                        layer_used IN ('fast_layer', 'smart_layer')
                    ),
                    success_status INTEGER NOT NULL CHECK (success_status IN (0, 1))
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_telemetry_timestamp
                ON execution_telemetry(timestamp)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_execution_telemetry_layer_timestamp
                ON execution_telemetry(layer_used, timestamp)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def render_telemetry_summary(summary: TelemetrySummary) -> str:
    """Render telemetry metrics for terminal output."""

    lines = [f"Eclipse telemetry report ({summary.days} day window)"]
    lines.append(f"Total requests: {summary.total_requests}")
    lines.append(
        f"Fast layer: {summary.fast_layer_requests} "
        f"({summary.fast_layer_percentage:.1f}%)"
    )
    lines.append(
        f"Smart layer: {summary.smart_layer_requests} "
        f"({summary.smart_layer_percentage:.1f}%)"
    )
    lines.append("Top smart-layer fallback instructions:")
    if not summary.top_smart_layer_instructions:
        lines.append("- None")
    else:
        for item in summary.top_smart_layer_instructions:
            lines.append(f"- {item.count}x — {item.instruction}")
    return "\n".join(lines)


def default_telemetry_store_path() -> Path:
    """Return the local-first telemetry database path under %LOCALAPPDATA%."""

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "telemetry.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _percentage(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (value / total) * 100
