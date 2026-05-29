import subprocess
from pathlib import Path

from eclipse_agent.desktop_apps import DesktopAppLauncher
from eclipse_agent.fedora_control import (
    FedoraControlAction,
    FedoraNativeController,
    WaylandNativeInput,
    WaylandScreenCapture,
)


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


def test_wayland_screen_capture_prepares_grim_command(tmp_path):
    capture = WaylandScreenCapture()

    result = capture.capture(output_path=tmp_path / "screen.png", dry_run=True)

    assert result.success is True
    assert result.action is FedoraControlAction.SCREENSHOT
    assert result.command == ("grim", str(tmp_path / "screen.png"))
    assert result.output_path == tmp_path / "screen.png"


def test_wayland_screen_capture_prepares_region_command(tmp_path):
    capture = WaylandScreenCapture()

    result = capture.capture(
        output_path=tmp_path / "region.png",
        geometry="10,20 300x400",
        dry_run=True,
    )

    assert result.command == ("grim", "-g", "10,20 300x400", str(tmp_path / "region.png"))


def test_wayland_region_selection_uses_slurp_then_grim(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "eclipse_agent.fedora_control.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    calls = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command == ("slurp",):
            return subprocess.CompletedProcess(command, 0, stdout="10,20 300x400\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    capture = WaylandScreenCapture(runner=runner)

    result = capture.capture_selected_region(output_path=tmp_path / "region.png", dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert calls == [
        ("slurp",),
        ("grim", "-g", "10,20 300x400", str(tmp_path / "region.png")),
    ]


def test_wayland_native_input_blocks_without_confirmation():
    native_input = WaylandNativeInput()

    result = native_input.type_text("hello", confirmed=False, dry_run=True)

    assert result.success is False
    assert result.action is FedoraControlAction.TYPE_TEXT
    assert "requires explicit confirmation" in result.message


def test_wayland_native_input_prepares_confirmed_type_command():
    native_input = WaylandNativeInput(socket_path="/tmp/eclipse.sock")

    result = native_input.type_text("hello", confirmed=True, dry_run=True)

    assert result.success is True
    assert result.command == ("env", "YDOTOOL_SOCKET=/tmp/eclipse.sock", "ydotool", "type", "hello")


def test_wayland_native_input_executes_confirmed_mouse_move(monkeypatch):
    monkeypatch.setattr(
        "eclipse_agent.fedora_control.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    calls = []

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    native_input = WaylandNativeInput(runner=runner, socket_path=None)

    result = native_input.move_mouse(100, 200, confirmed=True, dry_run=False)

    assert result.success is True
    assert result.executed is True
    assert calls == [("ydotool", "mousemove", "--absolute", "-x", "100", "-y", "200")]
