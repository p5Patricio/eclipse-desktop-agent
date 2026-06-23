import sys
import pytest
from unittest.mock import MagicMock

# Define global mock objects
mock_win32gui = MagicMock()
mock_win32process = MagicMock()
mock_win32con = MagicMock()
mock_winrt = MagicMock()
mock_winrt_notifications = MagicMock()
mock_win32com = MagicMock()
mock_win32com_client = MagicMock()
mock_sounddevice = MagicMock()
mock_soundfile = MagicMock()

# Inject them into sys.modules before any tests are imported
sys.modules["win32gui"] = mock_win32gui
sys.modules["win32process"] = mock_win32process
sys.modules["win32con"] = mock_win32con
sys.modules["winrt"] = mock_winrt
sys.modules["winrt.windows.ui.notifications.management"] = mock_winrt_notifications
sys.modules["win32com"] = mock_win32com
sys.modules["win32com.client"] = mock_win32com_client
sys.modules["sounddevice"] = mock_sounddevice
sys.modules["soundfile"] = mock_soundfile

# Establish attribute chains so nested mock imports resolve to correct children
mock_win32com.client = mock_win32com_client

mock_winrt_windows = MagicMock()
mock_winrt_ui = MagicMock()
mock_winrt_notifications_sub = MagicMock()
mock_winrt.windows = mock_winrt_windows
mock_winrt_windows.ui = mock_winrt_ui
mock_winrt_ui.notifications = mock_winrt_notifications_sub
mock_winrt_notifications_sub.management = mock_winrt_notifications


@pytest.fixture(autouse=True)
def reset_windows_mocks():
    # Reset all mocks before each test so assertions/calls don't leak
    mock_win32gui.reset_mock()
    mock_win32process.reset_mock()
    mock_win32con.reset_mock()
    mock_winrt.reset_mock()
    mock_winrt_notifications.reset_mock()
    mock_win32com.reset_mock()
    mock_win32com_client.reset_mock()
    mock_sounddevice.reset_mock()
    mock_soundfile.reset_mock()
    yield


@pytest.fixture(autouse=True)
def disable_wake_runtime_http_server(monkeypatch):
    from eclipse_agent.wake_runtime import WakeRuntime
    monkeypatch.setattr(WakeRuntime, "_start_status_server", lambda self: None)

