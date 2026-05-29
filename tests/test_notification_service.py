import subprocess
from pathlib import Path

from eclipse_agent.notification_service import (
    NotificationServiceSpec,
    NotificationUserServiceManager,
    render_notification_service_result,
)


def test_notification_service_renders_long_running_listener_unit(tmp_path):
    manager = NotificationUserServiceManager(
        spec=NotificationServiceSpec(
            project_dir=tmp_path,
            python_executable="/usr/bin/python",
            seconds=0,
            speak=True,
            store_path=tmp_path / "notifications.sqlite3",
        )
    )

    unit = manager.render_unit()

    assert "Description=Eclipse notification listener" in unit
    assert f"WorkingDirectory={tmp_path}" in unit
    assert "Environment=PYTHONPATH=src" in unit
    assert "notifications-listen --seconds 0 --execute --speak" in unit
    assert f"--store {tmp_path / 'notifications.sqlite3'}" in unit
    assert "Restart=on-failure" in unit


def test_notification_service_install_dry_run_does_not_write_file(tmp_path, monkeypatch):
    spec = NotificationServiceSpec(project_dir=tmp_path, python_executable="/usr/bin/python")
    unit_path = tmp_path / "eclipse-notifications.service"
    monkeypatch.setattr(type(spec), "unit_path", property(lambda _self: unit_path))
    manager = NotificationUserServiceManager(spec=spec)

    result = manager.install(dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.commands == (("systemctl", "--user", "daemon-reload"),)
    assert unit_path.exists() is False


def test_notification_service_install_execute_writes_unit_and_reloads(tmp_path, monkeypatch):
    calls = []
    unit_path = tmp_path / "eclipse-notifications.service"

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    spec = NotificationServiceSpec(project_dir=tmp_path, python_executable="/usr/bin/python")
    monkeypatch.setattr(type(spec), "unit_path", property(lambda _self: unit_path))
    manager = NotificationUserServiceManager(spec=spec, runner=runner)

    result = manager.install(dry_run=False)

    assert result.success is True
    assert unit_path.exists() is True
    assert calls == [("systemctl", "--user", "daemon-reload")]


def test_notification_service_enable_now_prepares_safe_command(tmp_path):
    manager = NotificationUserServiceManager(
        spec=NotificationServiceSpec(project_dir=tmp_path, service_name="eclipse-test.service")
    )

    result = manager.enable_now(dry_run=True)

    assert result.commands == (("systemctl", "--user", "enable", "--now", "eclipse-test.service"),)


def test_render_notification_service_result_includes_unit_and_commands(tmp_path):
    manager = NotificationUserServiceManager(spec=NotificationServiceSpec(project_dir=tmp_path))
    result = manager.install(dry_run=True)

    rendered = render_notification_service_result(result)

    assert "Notification service [ok/dry-run] install" in rendered
    assert "systemctl --user daemon-reload" in rendered
