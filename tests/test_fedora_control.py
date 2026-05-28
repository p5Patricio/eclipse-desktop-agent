import subprocess
from pathlib import Path

from eclipse_agent.desktop_apps import DesktopAppLauncher
from eclipse_agent.fedora_control import FedoraControlAction, FedoraNativeController


def _launcher_with_app(tmp_path: Path) -> DesktopAppLauncher:
    (tmp_path / "app.desktop").write_text(
        """
[Desktop Entry]
Type=Application
Name=Example App
Exec=/usr/bin/example-app
""".strip(),
        encoding="utf-8",
    )
    return DesktopAppLauncher(search_dirs=(tmp_path,))


def test_fedora_controller_prepares_app_launch(tmp_path):
    controller = FedoraNativeController(desktop_launcher=_launcher_with_app(tmp_path))

    result = controller.open_app("Example App", dry_run=True)

    assert result.success is True
    assert result.action is FedoraControlAction.OPEN_APP
    assert result.command == ("/usr/bin/example-app",)


def test_fedora_controller_execute_uses_runner(tmp_path):
    calls = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    controller = FedoraNativeController(
        desktop_launcher=_launcher_with_app(tmp_path),
        runner=runner,
    )

    result = controller.open_app("Example App", dry_run=False)

    assert result.executed is True
    assert calls == [("/usr/bin/example-app",)]


def test_fedora_focus_is_blocked_until_validated():
    controller = FedoraNativeController()

    result = controller.focus_window_placeholder("YouTube Music")

    assert result.success is False
    assert result.action is FedoraControlAction.FOCUS_WINDOW
    assert "not enabled" in result.message
