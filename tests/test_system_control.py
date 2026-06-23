from eclipse_agent.main import main
from eclipse_agent.pal.windows.system_control import (
    VK_MEDIA_PLAY_PAUSE,
    VK_VOLUME_UP,
    WindowsSystemController,
)
from eclipse_agent.system_control import (
    SystemAction,
    SystemControlResult,
    render_system_control_result,
)


def test_render_shows_status_and_action():
    result = SystemControlResult(
        success=True,
        action=SystemAction.VOLUME_UP,
        message="Sent volume_up.",
        dry_run=False,
        executed=True,
    )

    assert "System control [executed] volume_up" in render_system_control_result(result)


def test_dry_run_does_not_press_any_key():
    presses: list[int] = []
    controller = WindowsSystemController(key_press=presses.append)

    result = controller.run(SystemAction.VOLUME_UP, dry_run=True)

    assert result.success is True
    assert result.executed is False
    assert presses == []


def test_execute_volume_up_presses_volume_key():
    presses: list[int] = []
    controller = WindowsSystemController(key_press=presses.append)

    result = controller.run(SystemAction.VOLUME_UP, dry_run=False)

    assert result.executed is True
    assert presses == [VK_VOLUME_UP]


def test_execute_media_play_pause_presses_media_key():
    presses: list[int] = []
    controller = WindowsSystemController(key_press=presses.append)

    controller.run(SystemAction.MEDIA_PLAY_PAUSE, dry_run=False)

    assert presses == [VK_MEDIA_PLAY_PAUSE]


def test_execute_lock_calls_lock_screen():
    locked: list[bool] = []
    controller = WindowsSystemController(lock_screen=lambda: locked.append(True))

    result = controller.run(SystemAction.LOCK, dry_run=False)

    assert result.executed is True
    assert locked == [True]


def test_battery_status_formats_percent_and_power_source():
    controller = WindowsSystemController(read_battery=lambda: (1, 73))

    result = controller.run(SystemAction.BATTERY)

    assert result.executed is True
    assert "73%" in result.message
    assert "on AC power" in result.message


def test_battery_unknown_percent_on_battery():
    controller = WindowsSystemController(read_battery=lambda: (0, 255))

    result = controller.run(SystemAction.BATTERY)

    assert "unknown" in result.message
    assert "on battery" in result.message


def test_key_press_failure_is_reported():
    def boom(vk: int) -> None:
        raise OSError("no input device")

    controller = WindowsSystemController(key_press=boom)

    result = controller.run(SystemAction.MUTE, dry_run=False)

    assert result.success is False
    assert "failed" in result.message


def test_cli_system_dry_run_returns_zero(capsys):
    code = main(["system", "--action", "volume_up"])

    assert code == 0
    assert "System control [prepared] volume_up" in capsys.readouterr().out


def test_cli_system_lock_requires_confirmed(capsys):
    code = main(["system", "--action", "lock", "--execute"])

    assert code == 1
    assert "requires --confirmed" in capsys.readouterr().out
