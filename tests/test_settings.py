from eclipse_agent import main as main_module
from eclipse_agent.settings import (
    EclipseSettings,
    apply_to_env,
    load_settings,
    save_settings,
    settings_from_dict,
)
from eclipse_agent.settings_app import SettingsApi


# --- settings model + IO -------------------------------------------------


def test_settings_roundtrip(tmp_path):
    settings = EclipseSettings(
        llm_model="my-model", tts_neural=False, wake_threshold=0.7, imap_user="me@x.com"
    )
    path = save_settings(settings, tmp_path / "config.json")
    loaded = load_settings(path)

    assert loaded.llm_model == "my-model"
    assert loaded.tts_neural is False
    assert loaded.wake_threshold == 0.7
    assert loaded.imap_user == "me@x.com"


def test_load_missing_returns_defaults(tmp_path):
    settings = load_settings(tmp_path / "nope.json")
    assert settings.llm_provider == "ollama"
    assert settings.tts_neural is True


def test_settings_from_dict_coerces_and_ignores_unknown():
    settings = settings_from_dict(
        {"llm_model": "x", "tts_neural": False, "wake_threshold": "0.3", "bogus": "z"}
    )
    assert settings.llm_model == "x"
    assert settings.tts_neural is False
    assert settings.wake_threshold == 0.3  # coerced from string
    assert not hasattr(settings, "bogus")
    assert settings.llm_provider == "ollama"  # default kept


def test_apply_to_env_sets_vars_and_skips_blanks():
    env: dict[str, str] = {}
    apply_to_env(
        EclipseSettings(llm_model="qwen", tts_neural=False, imap_user="", openai_api_key="k"),
        env=env,
    )
    assert env["ECLIPSE_LLM_MODEL"] == "qwen"
    assert env["ECLIPSE_TTS_NEURAL"] == "0"  # bool -> "0"/"1"
    assert env["OPENAI_API_KEY"] == "k"
    assert "ECLIPSE_IMAP_USER" not in env  # blank does not clobber


# --- settings API --------------------------------------------------------


def test_api_get_and_save_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api = SettingsApi()

    data = api.get_settings()
    assert data["llm_provider"] == "ollama"

    result = api.save_settings({**data, "llm_model": "custom-model"})
    assert result["ok"] is True
    assert api.get_settings()["llm_model"] == "custom-model"


def test_api_test_ollama_unreachable():
    result = SettingsApi().test_ollama("http://localhost:1")
    assert result["ok"] is False


# --- daemon control + safety ---------------------------------------------


class FakeProc:
    def __init__(self) -> None:
        self._alive = True
        self.terminated = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False


def test_daemon_command_respects_auto_execute():
    from eclipse_agent.settings import EclipseSettings
    from eclipse_agent.settings_app import daemon_command

    assert "--route-execute" in daemon_command(EclipseSettings(auto_execute=True))
    no_auto = daemon_command(EclipseSettings(auto_execute=False))
    assert "--route-execute" not in no_auto
    assert "wake-efficient" in no_auto


def test_daemon_command_frozen_drops_module_flag(monkeypatch):
    import sys

    from eclipse_agent.settings import EclipseSettings
    from eclipse_agent.settings_app import daemon_command

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = daemon_command(EclipseSettings())
    assert "-m" not in command
    assert "wake-efficient" in command


def test_start_stop_daemon(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    procs: list[FakeProc] = []

    def spawn(_cmd):
        proc = FakeProc()
        procs.append(proc)
        return proc

    api = SettingsApi(spawn=spawn)
    assert api.daemon_status()["running"] is False

    assert api.start_daemon()["ok"] is True
    assert api.daemon_status()["running"] is True
    assert api.start_daemon()["ok"] is False  # already running

    assert api.stop_daemon()["ok"] is True
    assert procs[0].terminated is True
    assert api.daemon_status()["running"] is False


def test_kill_switch_via_api(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api = SettingsApi()

    assert api.kill_switch_state()["engaged"] is False
    assert api.set_kill_switch(True)["engaged"] is True
    assert api.kill_switch_state()["engaged"] is True
    assert api.set_kill_switch(False)["engaged"] is False


def test_recent_audit_via_api(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from eclipse_agent.audit import AuditEntry

    api = SettingsApi()
    api._audit_log.record(
        AuditEntry(
            action_kind="system_control",
            target="battery",
            risk_level="low",
            status="executed",
            tool_name="native.system_control",
        )
    )

    rows = api.recent_audit()
    assert rows[0]["action_kind"] == "system_control"
    assert rows[0]["status"] == "executed"


# --- MCP servers ---------------------------------------------------------


def test_mcp_servers_roundtrip_and_validation(tmp_path):
    from eclipse_agent.settings import load_mcp_servers, save_mcp_servers

    path = tmp_path / "mcp.json"
    save_mcp_servers(
        [
            {"name": "browser", "command": "python", "args": ["server.py"]},
            {"name": "", "command": "x"},  # dropped: no name
            {"name": "y", "command": ""},  # dropped: no command
        ],
        path,
    )
    servers = load_mcp_servers(path)

    assert len(servers) == 1
    assert servers[0]["name"] == "browser"
    assert servers[0]["args"] == ["server.py"]


def test_load_mcp_servers_missing_returns_empty(tmp_path):
    from eclipse_agent.settings import load_mcp_servers

    assert load_mcp_servers(tmp_path / "nope.json") == []


def test_api_mcp_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api = SettingsApi()

    assert api.list_mcp_servers() == []
    result = api.save_mcp_servers([{"name": "browser", "command": "python", "args": []}])
    assert result["ok"] is True
    assert api.list_mcp_servers()[0]["name"] == "browser"


# --- CLI -----------------------------------------------------------------


def test_cli_settings_invokes_app(monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "run_settings_app", lambda: called.append(True))

    assert main_module.main(["settings"]) == 0
    assert called == [True]
