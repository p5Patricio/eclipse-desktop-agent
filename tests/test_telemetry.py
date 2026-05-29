from datetime import UTC, datetime, timedelta

import pytest

from eclipse_agent.telemetry import (
    ExecutionTelemetryStore,
    TelemetryLayer,
    render_telemetry_summary,
)


def test_telemetry_store_logs_and_summarizes_layer_usage(tmp_path):
    store = ExecutionTelemetryStore(tmp_path / "telemetry.sqlite3")
    now = datetime.now(UTC)

    store.log_execution(
        instruction="Open Instagram",
        layer_used=TelemetryLayer.FAST_LAYER,
        success_status=True,
        timestamp=now,
    )
    store.log_execution(
        instruction="Open calendar",
        layer_used=TelemetryLayer.SMART_LAYER,
        success_status=True,
        timestamp=now,
    )
    store.log_execution(
        instruction="Open calendar",
        layer_used=TelemetryLayer.SMART_LAYER,
        success_status=True,
        timestamp=now,
    )
    store.log_execution(
        instruction="Old request",
        layer_used=TelemetryLayer.SMART_LAYER,
        success_status=True,
        timestamp=now - timedelta(days=10),
    )

    summary = store.summarize(days=5)

    assert summary.total_requests == 3
    assert summary.fast_layer_requests == 1
    assert summary.smart_layer_requests == 2
    assert summary.fast_layer_percentage == pytest.approx(100 / 3)
    assert summary.top_smart_layer_instructions[0].instruction == "Open calendar"
    assert summary.top_smart_layer_instructions[0].count == 2


def test_render_telemetry_summary_outputs_clean_terminal_report(tmp_path):
    store = ExecutionTelemetryStore(tmp_path / "telemetry.sqlite3")
    store.log_execution(
        instruction="Open calendar",
        layer_used=TelemetryLayer.SMART_LAYER,
        success_status=False,
    )

    output = render_telemetry_summary(store.summarize(days=5))

    assert "Eclipse telemetry report (5 day window)" in output
    assert "Total requests: 1" in output
    assert "Smart layer: 1 (100.0%)" in output
    assert "1x — Open calendar" in output
