from types import SimpleNamespace

import pytest

from eclipse_agent import main as main_module
from eclipse_agent.push_to_talk import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    parse_hotkey,
)


# --- hotkey parsing ------------------------------------------------------


def test_parse_hotkey_ctrl_alt_space():
    modifiers, vk = parse_hotkey("ctrl+alt+space")
    assert modifiers == MOD_CONTROL | MOD_ALT
    assert vk == 0x20


def test_parse_hotkey_single_letter():
    modifiers, vk = parse_hotkey("ctrl+shift+a")
    assert modifiers == MOD_CONTROL | MOD_SHIFT
    assert vk == ord("A")


def test_parse_hotkey_function_key():
    modifiers, vk = parse_hotkey("f5")
    assert modifiers == 0
    assert vk == 0x74


@pytest.mark.parametrize("bad", ["", "ctrl+alt", "ctrl+nope"])
def test_parse_hotkey_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


# --- listen_and_handle ---------------------------------------------------


def test_listen_and_handle_transcribes_then_handles(tmp_path, monkeypatch):
    from eclipse_agent.notifications import NotificationStore
    from eclipse_agent.wake_runtime import WakeCommandResult, WakeRuntime

    class FakeListener:
        def run(self, *, seconds, audio_path, dry_run):
            return SimpleNamespace(
                success=True, transcription=SimpleNamespace(text="  qué hora es  "), message="ok"
            )

    runtime = WakeRuntime(
        listener=FakeListener(), store=NotificationStore(tmp_path / "n.sqlite3")
    )
    captured = {}

    def fake_handle(text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return WakeCommandResult(success=True, kind="x", command_text=text, message="ok")

    monkeypatch.setattr(runtime, "handle_command", fake_handle)

    result = runtime.listen_and_handle(route_execute=True)

    assert captured["text"] == "qué hora es"
    assert captured["kwargs"]["route_execute"] is True
    assert result.success is True


def test_listen_and_handle_reports_listen_failure(tmp_path):
    from eclipse_agent.notifications import NotificationStore
    from eclipse_agent.wake_runtime import WakeRuntime

    class FailListener:
        def run(self, *, seconds, audio_path, dry_run):
            return SimpleNamespace(success=False, transcription=None, message="mic error")

    runtime = WakeRuntime(
        listener=FailListener(), store=NotificationStore(tmp_path / "n.sqlite3")
    )

    result = runtime.listen_and_handle()
    assert result.success is False
    assert "mic error" in result.message


# --- CLI -----------------------------------------------------------------


def test_cli_push_to_talk_registers_hotkey(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    captured = {}
    monkeypatch.setattr(
        main_module,
        "run_push_to_talk",
        lambda on_activate, *, hotkey: captured.update(hotkey=hotkey),
    )

    assert main_module.main(["push-to-talk", "--hotkey", "ctrl+alt+p"]) == 0
    assert captured["hotkey"] == "ctrl+alt+p"
