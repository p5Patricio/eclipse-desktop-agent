import sys
from unittest.mock import MagicMock, patch
import pytest
from eclipse_agent.pal.windows.window_manager import WindowsWindowManager
from eclipse_agent.pal.windows.input import WindowsInputSynthesizer
from eclipse_agent.pal.windows.launcher import WindowsAppLauncher
from eclipse_agent.pal.windows.notifications import WindowsNotificationDaemon
from eclipse_agent.pal.windows.voice import WindowsTTSProvider, WindowsAudioRecorder
from eclipse_agent.pal.windows.daemon import WindowsDaemonManager

def test_windows_window_manager_list_windows(monkeypatch):
    import win32gui
    wm = WindowsWindowManager()
    
    # Mock win32gui.EnumWindows to simulate finding windows
    def mock_enum(callback, extra):
        callback(101, extra)
        callback(102, extra)
        return True
    
    monkeypatch.setattr(win32gui, "EnumWindows", mock_enum)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "Test Window" if hwnd == 101 else "Other Window")
    
    res = wm.list_windows()
    assert res.success is True
    assert res.action == "list_windows"
    assert "Test Window" in res.message
    assert "Other Window" in res.message

def test_windows_window_manager_focus_window(monkeypatch):
    import win32gui
    wm = WindowsWindowManager()
    
    # Mock EnumWindows
    def mock_enum(callback, extra):
        callback(101, extra)
        return True
    
    monkeypatch.setattr(win32gui, "EnumWindows", mock_enum)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "Target Window")
    
    # Test focus success
    mock_set_foreground = MagicMock()
    monkeypatch.setattr(win32gui, "SetForegroundWindow", mock_set_foreground)
    res = wm.focus_window("target")
    assert res.success is True
    mock_set_foreground.assert_called_once_with(101)
    
    # Test focus fail when window not found
    res_fail = wm.focus_window("nonexistent")
    assert res_fail.success is False

def test_windows_input_synthesizer_move_mouse():
    syn = WindowsInputSynthesizer()
    with patch("ctypes.windll.user32.SetCursorPos") as mock_set_pos:
        mock_set_pos.return_value = 1
        res = syn.move_mouse(100, 200, confirmed=True, dry_run=False)
        assert res.success is True
        mock_set_pos.assert_called_once_with(100, 200)

def test_windows_input_synthesizer_click():
    syn = WindowsInputSynthesizer()
    with patch("ctypes.windll.user32.SendInput") as mock_send_input:
        mock_send_input.return_value = 2
        res = syn.click(confirmed=True, dry_run=False)
        assert res.success is True
        assert mock_send_input.called

def test_windows_input_synthesizer_type_text():
    syn = WindowsInputSynthesizer()
    with patch("ctypes.windll.user32.SendInput") as mock_send_input:
        mock_send_input.return_value = 10
        res = syn.type_text("abc", confirmed=True, dry_run=False)
        assert res.success is True
        assert mock_send_input.called

def test_windows_input_synthesizer_unconfirmed():
    syn = WindowsInputSynthesizer()
    res = syn.move_mouse(100, 200, confirmed=False, dry_run=False)
    assert res.success is False
    assert "confirmation" in res.message

    res = syn.click(confirmed=False, dry_run=False)
    assert res.success is False
    assert "confirmation" in res.message

    res = syn.type_text("abc", confirmed=False, dry_run=False)
    assert res.success is False
    assert "confirmation" in res.message

def test_windows_input_synthesizer_dry_run():
    syn = WindowsInputSynthesizer()
    res = syn.move_mouse(100, 200, confirmed=True, dry_run=True)
    assert res.success is True
    assert res.dry_run is True

    res = syn.click(confirmed=True, dry_run=True)
    assert res.success is True
    assert res.dry_run is True

    res = syn.type_text("abc", confirmed=True, dry_run=True)
    assert res.success is True
    assert res.dry_run is True

def test_windows_screen_capture():
    from eclipse_agent.pal.windows.capture import WindowsScreenCapture
    cap = WindowsScreenCapture()

    # Dry run
    res_dry = cap.capture(dry_run=True)
    assert res_dry.success is True
    assert res_dry.dry_run is True

    # Real run with mocked PIL
    mock_grab = MagicMock()
    with patch("PIL.ImageGrab.grab", mock_grab):
        res = cap.capture(dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        mock_grab.assert_called_once_with(bbox=None)

    # Test selected region
    with patch("PIL.ImageGrab.grab", mock_grab) as mock_grab_reg:
        res_reg = cap.capture_selected_region(dry_run=False)
        assert res_reg.success is True

def test_windows_app_launcher_discover_and_launch(tmp_path, monkeypatch):
    # Create a dummy .lnk file
    lnk_file = tmp_path / "TestApp.lnk"
    lnk_file.touch()
    
    import win32com.client
    mock_shortcut = MagicMock()
    mock_shortcut.TargetPath = "C:\\Program Files\\TestApp\\app.exe"
    mock_dispatch = MagicMock()
    mock_dispatch.return_value.CreateShortcut.return_value = mock_shortcut
    monkeypatch.setattr(win32com.client, "Dispatch", mock_dispatch)
    
    launcher = WindowsAppLauncher(search_dirs=[tmp_path])
    
    # Test discover
    apps = launcher.discover_apps()
    assert len(apps) == 1
    assert apps[0].name == "TestApp"
    
    # Test find
    app = launcher.find_app("TestApp")
    assert app is not None
    assert app.name == "TestApp"
    
    # Test launch dry run
    res = launcher.launch("TestApp", dry_run=True)
    assert res.success is True
    assert res.app_name == "TestApp"
    assert res.command == ("C:\\Program Files\\TestApp\\app.exe",)
    assert res.dry_run is True
    
    # Test launch execute
    with patch("os.startfile") as mock_startfile:
        res = launcher.launch("TestApp", dry_run=False)
        assert res.success is True
        assert res.dry_run is False
        mock_startfile.assert_called_once_with(str(lnk_file))

def test_windows_app_launcher_missing():
    launcher = WindowsAppLauncher(search_dirs=[])
    res = launcher.launch("NonexistentApp")
    assert res.success is False
    assert "not found" in res.message or "file-not-found" in res.message

def test_windows_notification_daemon_run(monkeypatch):
    import winrt.windows.ui.notifications.management as mgmt
    from eclipse_agent.notifications import NotificationCenter
    
    center = MagicMock(spec=NotificationCenter)
    center.ingest.return_value = MagicMock()
    
    mock_listener = MagicMock()
    monkeypatch.setattr(mgmt.UserNotificationListener, "current", mock_listener)
    
    # 1 represents ALLOWED
    mock_listener.get_access_status.return_value = 1
    
    mock_notification = MagicMock()
    mock_notification.id = 999
    mock_notification.app_info.display_info.display_name = "MockApp"
    
    mock_binding = MagicMock()
    mock_text_1 = MagicMock()
    mock_text_1.text = "Hello Title"
    mock_text_2 = MagicMock()
    mock_text_2.text = "Hello Body"
    mock_binding.get_text_elements.return_value = [mock_text_1, mock_text_2]
    
    mock_notification.notification.visual.get_binding.return_value = mock_binding
    mock_listener.get_notifications.return_value = [mock_notification]
    
    daemon = WindowsNotificationDaemon(center=center)
    res = daemon.run(seconds=1, dry_run=False)
    
    assert res.success is True
    assert res.processed == 1
    assert "MockApp" in res.message or "processed" in res.message.lower()
    center.ingest.assert_called_once()

def test_windows_notification_daemon_permission_denied(caplog, monkeypatch):
    import logging
    import winrt.windows.ui.notifications.management as mgmt
    
    mock_listener = MagicMock()
    monkeypatch.setattr(mgmt.UserNotificationListener, "current", mock_listener)
    # 2 represents DENIED
    mock_listener.get_access_status.return_value = 2
    
    daemon = WindowsNotificationDaemon()
    with caplog.at_level(logging.WARNING):
        res = daemon.run(seconds=1, dry_run=False)
        assert res.success is False
        assert any("permission denied" in record.message.lower() for record in caplog.records)

def test_windows_tts_provider_speak(monkeypatch):
    import win32com.client
    mock_speaker = MagicMock()
    mock_dispatch = MagicMock(return_value=mock_speaker)
    monkeypatch.setattr(win32com.client, "Dispatch", mock_dispatch)
    
    tts = WindowsTTSProvider()
    # Test dry run
    res = tts.speak("Hello world", dry_run=True)
    assert res.success is True
    assert res.provider == "sapi"
    assert res.dry_run is True
    mock_speaker.Speak.assert_not_called()
    
    # Test real run
    mock_speaker.Speak.reset_mock()
    res = tts.speak("Hello world", dry_run=False)
    assert res.success is True
    assert res.provider == "sapi"
    assert res.dry_run is False
    assert res.executed is True
    mock_speaker.Speak.assert_called_once_with("Hello world")

def test_windows_tts_provider_speak_error(monkeypatch):
    import win32com.client
    mock_speaker = MagicMock()
    mock_speaker.Speak.side_effect = Exception("SAPI error")
    mock_dispatch = MagicMock(return_value=mock_speaker)
    monkeypatch.setattr(win32com.client, "Dispatch", mock_dispatch)
    
    tts = WindowsTTSProvider()
    res = tts.speak("Hello", dry_run=False)
    assert res.success is False
    assert "SAPI error" in res.message

def test_windows_audio_recorder_record(tmp_path, monkeypatch):
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    
    rec = WindowsAudioRecorder()
    audio_file = tmp_path / "test.wav"
    
    # Test dry run
    res = rec.record(audio_file, seconds=2, dry_run=True)
    assert res.success is True
    assert res.dry_run is True
    
    # Test real run
    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.read.return_value = (np.zeros((1600, 1), dtype='int16'), False)
    
    mock_input_stream = MagicMock(return_value=mock_stream)
    monkeypatch.setattr(sd, "InputStream", mock_input_stream)
    
    mock_write = MagicMock()
    monkeypatch.setattr(sf, "write", mock_write)
    
    res = rec.record(audio_file, seconds=2, dry_run=False)
    assert res.success is True
    assert res.dry_run is False
    assert res.executed is True
    
    mock_input_stream.assert_called_once()
    mock_stream.read.assert_called()
    mock_write.assert_called_once()

def test_windows_audio_recorder_record_error(tmp_path, monkeypatch):
    import sounddevice as sd
    mock_input_stream = MagicMock(side_effect=Exception("device error"))
    monkeypatch.setattr(sd, "InputStream", mock_input_stream)
    
    rec = WindowsAudioRecorder()
    res = rec.record(tmp_path / "fail.wav", seconds=1, dry_run=False)
    assert res.success is False
    assert "device error" in res.message

def test_windows_daemon_manager():
    daemon = WindowsDaemonManager()

    # On non-Windows platform it should return a mocked success
    with patch("sys.platform", "linux"):
        res = daemon.register_autostart("name", "path")
        assert res.success is True
        assert "Mocked" in res.message

        res_rem = daemon.remove_autostart("name")
        assert res_rem.success is True
        assert "Mocked" in res_rem.message

    # On Windows platform, let's mock winreg
    with patch("sys.platform", "win32"):
        mock_winreg = MagicMock()
        sys.modules["winreg"] = mock_winreg
        try:
            res = daemon.register_autostart("name", "path")
            assert res.success is True
            mock_winreg.OpenKey.assert_called_once()
            mock_winreg.SetValueEx.assert_called_once()

            res_rem = daemon.remove_autostart("name")
            assert res_rem.success is True
            mock_winreg.DeleteValue.assert_called_once()
        finally:
            if "winreg" in sys.modules:
                del sys.modules["winreg"]
