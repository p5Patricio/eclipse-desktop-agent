from eclipse_agent import main as main_module
from eclipse_agent.audit import AuditEntry, AuditLog, render_audit_entries
from eclipse_agent.killswitch import KillSwitch
from eclipse_agent.planner import ActionKind, PlannedAction
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import (
    NativeMCPClient,
    ToolExecutionContext,
    ToolRouter,
)


def _battery_action() -> PlannedAction:
    return PlannedAction(
        id="sys-1",
        kind=ActionKind.SYSTEM_CONTROL,
        description="Battery.",
        risk_level=RiskLevel.LOW,
        target="battery",
        parameters={"system_action": "battery"},
        tool_name="native.system_control",
    )


# --- audit log -----------------------------------------------------------


def test_audit_log_records_and_lists_newest_first(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite3")
    log.record(AuditEntry(action_kind="a", target="t1", risk_level="low", status="executed", tool_name="x"))
    log.record(AuditEntry(action_kind="b", target="t2", risk_level="high", status="blocked", tool_name="y"))

    recent = log.recent()
    assert [e.action_kind for e in recent] == ["b", "a"]
    assert log.count() == 2


def test_audit_log_clear(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite3")
    log.record(AuditEntry(action_kind="a", target="t", risk_level="low", status="executed", tool_name="x"))
    assert log.clear() == 1
    assert log.count() == 0


def test_render_audit_entries_empty():
    assert "No audited" in render_audit_entries(())


# --- kill switch ---------------------------------------------------------


def test_kill_switch_engage_disengage(tmp_path):
    switch = KillSwitch(tmp_path / "kill.flag")
    assert switch.is_engaged() is False
    switch.engage()
    assert switch.is_engaged() is True
    # A new instance sees the persisted state.
    assert KillSwitch(tmp_path / "kill.flag").is_engaged() is True
    switch.disengage()
    assert switch.is_engaged() is False


# --- router integration --------------------------------------------------


def test_router_audits_routed_action(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite3")
    router = ToolRouter(mcp_client=NativeMCPClient(), audit_log=log)

    router.route_action(_battery_action(), ToolExecutionContext(dry_run=True))

    entries = log.recent()
    assert len(entries) == 1
    assert entries[0].action_kind == "system_control"
    assert entries[0].status == "prepared"


def test_router_kill_switch_blocks_and_audits(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite3")
    switch = KillSwitch(tmp_path / "kill.flag")
    switch.engage()
    router = ToolRouter(mcp_client=NativeMCPClient(), audit_log=log, kill_switch=switch)

    # dry_run=False would normally execute, but the kill switch must block it first.
    result = router.route_action(_battery_action(), ToolExecutionContext(dry_run=False))

    assert result.success is False
    assert result.executed is False
    assert result.tool_name == "kill_switch"
    assert "paused" in result.message
    assert log.recent()[0].status == "killed"


def test_router_without_audit_log_is_silent(tmp_path):
    # No audit_log/kill_switch → behaves exactly as before (no crash).
    router = ToolRouter(mcp_client=NativeMCPClient())
    result = router.route_action(_battery_action(), ToolExecutionContext(dry_run=True))
    assert result.success is True


def test_formatter_announces_kill_switch_pause():
    from eclipse_agent.response_formatter import ActionResponseFormatter
    from eclipse_agent.tool_router import ToolExecutionResult

    result = ToolExecutionResult(
        action_id="x",
        tool_name="kill_switch",
        success=False,
        executed=False,
        requires_confirmation=False,
        message="Eclipse is paused; resume it to act.",
        metadata={"target": "battery", "kind": "system_control"},
    )
    spoken = ActionResponseFormatter().format(
        command_text="cuánta batería tengo", route_results=(result,)
    )
    assert "pausa" in spoken.casefold()


# --- CLI -----------------------------------------------------------------


def test_cli_kill_resume_and_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["kill-status"]) == 0
    assert "off" in capsys.readouterr().out

    assert main_module.main(["kill"]) == 0
    assert "ENGAGED" in capsys.readouterr().out

    assert main_module.main(["kill-status"]) == 0
    assert "ENGAGED" in capsys.readouterr().out

    assert main_module.main(["resume"]) == 0
    capsys.readouterr()
    assert main_module.main(["kill-status"]) == 0
    assert "off" in capsys.readouterr().out


def test_cli_audit_and_clear(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["audit"]) == 0
    assert "No audited" in capsys.readouterr().out

    AuditLog().record(
        AuditEntry(
            action_kind="system_control",
            target="battery",
            risk_level="low",
            status="executed",
            tool_name="native.system_control",
        )
    )
    assert main_module.main(["audit"]) == 0
    assert "system_control" in capsys.readouterr().out

    assert main_module.main(["audit-clear"]) == 0
    assert "Cleared 1" in capsys.readouterr().out
