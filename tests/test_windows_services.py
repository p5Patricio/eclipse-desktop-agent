import sys
import pytest
from unittest.mock import MagicMock
from eclipse_agent.pal.windows.launcher import WindowsAppLauncher
from eclipse_agent.pal.windows.voice import WindowsTTSProvider

def test_windows_app_launcher_missing_graceful_error(tmp_path):
    launcher = WindowsAppLauncher(search_dirs=[tmp_path])
    res = launcher.launch("NonexistentApp", dry_run=False)
    assert res.success is False
    assert "not found" in res.message.lower()

def test_windows_tts_provider_graceful_dispatch_error(monkeypatch):
    import win32com.client
    mock_dispatch = MagicMock(side_effect=Exception("Failed to initialize SAPI"))
    monkeypatch.setattr(win32com.client, "Dispatch", mock_dispatch)
    
    tts = WindowsTTSProvider()
    res = tts.speak("Hello", dry_run=False)
    assert res.success is False
    assert "Failed to initialize SAPI" in res.message
