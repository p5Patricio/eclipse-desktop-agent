from eclipse_agent.runtime_diagnostics import CapabilityStatus, RuntimeDiagnostics


def test_runtime_diagnostics_counts_ready_capabilities():
    diagnostics = RuntimeDiagnostics(
        capabilities=(
            CapabilityStatus("a", True, "ok"),
            CapabilityStatus("b", False, "missing", "install b"),
        )
    )

    output = diagnostics.render()

    assert diagnostics.ready_count == 1
    assert "1/2 ready" in output
    assert "install b" in output


def test_collect_runtime_diagnostics_on_windows(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "win32")

    from eclipse_agent.runtime_diagnostics import collect_runtime_diagnostics

    # We mock find_spec to return spec/None for target modules
    import importlib.util

    def mock_find_spec(name, package=None):
        if name in (
            "win32gui",
            "winrt.windows.ui.notifications.management",
            "sounddevice",
            "faster_whisper",
        ):
            class DummySpec:
                pass
            return DummySpec()
        return None

    monkeypatch.setattr(importlib.util, "find_spec", mock_find_spec)

    # Mock win32com.client Dispatch to avoid real COM calls
    import sys as sys_module
    from unittest.mock import MagicMock
    mock_win32com = MagicMock()
    monkeypatch.setitem(sys_module.modules, "win32com", mock_win32com)
    monkeypatch.setitem(sys_module.modules, "win32com.client", mock_win32com.client)

    diagnostics = collect_runtime_diagnostics()
    names = [c.name for c in diagnostics.capabilities]

    # Verify that Windows-specific capabilities are present
    assert "win32gui" in names
    assert "winrt.windows.ui.notifications.management" in names
    assert "sounddevice" in names
    assert "sapi_tts" in names

    # Verify that Linux-specific capabilities are NOT present on Windows
    assert "spd-say" not in names
    assert "espeak-ng" not in names
    assert "arecord" not in names
    assert "pw-record" not in names
    assert "dbus-monitor" not in names

