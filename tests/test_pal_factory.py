import sys
import pytest
from unittest.mock import MagicMock

def test_factory_returns_windows_implementations_on_win32(monkeypatch):
    # Mock sys.platform to be win32
    monkeypatch.setattr(sys, "platform", "win32")

    # Stub out the windows modules in sys.modules so imports don't fail
    mock_window_manager = MagicMock()
    mock_input = MagicMock()
    mock_capture = MagicMock()
    mock_launcher = MagicMock()
    mock_notifications = MagicMock()
    mock_voice = MagicMock()
    mock_daemon = MagicMock()

    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.window_manager", mock_window_manager)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.input", mock_input)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.capture", mock_capture)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.launcher", mock_launcher)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.notifications", mock_notifications)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.voice", mock_voice)
    monkeypatch.setitem(sys.modules, "eclipse_agent.pal.windows.daemon", mock_daemon)

    from eclipse_agent.pal.factory import PlatformFactory

    # Call get_window_manager and verify it instantiates WindowsWindowManager
    PlatformFactory.get_window_manager()
    mock_window_manager.WindowsWindowManager.assert_called_once()

    PlatformFactory.get_input_synthesizer()
    mock_input.WindowsInputSynthesizer.assert_called_once()

    PlatformFactory.get_screen_capture()
    mock_capture.WindowsScreenCapture.assert_called_once()

    PlatformFactory.get_app_launcher()
    mock_launcher.WindowsAppLauncher.assert_called_once()

    PlatformFactory.get_notification_daemon()
    mock_notifications.WindowsNotificationDaemon.assert_called_once()

    PlatformFactory.get_tts_provider()
    mock_voice.WindowsTTSProvider.assert_called_once()

    PlatformFactory.get_audio_recorder()
    mock_voice.WindowsAudioRecorder.assert_called_once()

    PlatformFactory.get_daemon_manager()
    mock_daemon.WindowsDaemonManager.assert_called_once()


def test_factory_rejects_non_windows_platforms(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    from eclipse_agent.pal.factory import PlatformFactory

    with pytest.raises(RuntimeError, match="Windows-only"):
        PlatformFactory.get_window_manager()
