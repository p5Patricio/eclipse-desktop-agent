from eclipse_agent import main as main_module
from eclipse_agent.browser_control import (
    BrowserBackend,
    BrowserSessionMode,
    browser_audit_detail,
    redact_browser_audit_payload,
)
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
    assert settings.browser_backend_policy == "native_simple_plus_fallback"
    assert settings.browser_session_mode == "managed"
    assert settings.browser_live_access_consent is False
    assert settings.browser_allow_vision_fallback is True
    assert settings.browser_allow_agent_browser_fallback is True


def test_settings_from_dict_coerces_and_ignores_unknown():
    settings = settings_from_dict(
        {"llm_model": "x", "tts_neural": False, "wake_threshold": "0.3", "bogus": "z"}
    )
    assert settings.llm_model == "x"
    assert settings.tts_neural is False
    assert settings.wake_threshold == 0.3  # coerced from string
    assert not hasattr(settings, "bogus")
    assert settings.llm_provider == "ollama"  # default kept


def test_settings_from_dict_coerces_false_strings_fail_closed():
    settings = settings_from_dict(
        {
            "browser_live_access_consent": "false",
            "browser_devtools_auto_connect": "0",
            "browser_allow_agent_browser_fallback": "off",
            "browser_confirm_sensitive_actions": "yes",
        }
    )

    assert settings.browser_live_access_consent is False
    assert settings.browser_devtools_auto_connect is False
    assert settings.browser_allow_agent_browser_fallback is False
    assert settings.browser_confirm_sensitive_actions is True


def test_apply_to_env_sets_vars_and_skips_blanks():
    env: dict[str, str] = {}
    apply_to_env(
        EclipseSettings(
            llm_model="qwen",
            tts_neural=False,
            imap_user="",
            openai_api_key="k",
            browser_live_access_consent=False,
        ),
        env=env,
    )
    assert env["ECLIPSE_LLM_MODEL"] == "qwen"
    assert env["ECLIPSE_TTS_NEURAL"] == "0"  # bool -> "0"/"1"
    assert env["OPENAI_API_KEY"] == "k"
    assert env["ECLIPSE_BROWSER_LIVE_ACCESS_CONSENT"] == "0"
    assert "ECLIPSE_IMAP_USER" not in env  # blank does not clobber


def test_browser_control_settings_roundtrip(tmp_path):
    settings = EclipseSettings(
        browser_backend_policy="chrome_devtools_when_consented",
        browser_session_mode="browser_url",
        browser_devtools_browser_url="http://127.0.0.1:9222",
        browser_devtools_ws_endpoint="ws://127.0.0.1:9222/devtools/browser/abc",
        browser_devtools_auto_connect=True,
        browser_devtools_mcp_server="chrome-devtools",
        browser_live_access_consent=True,
        browser_confirm_sensitive_actions=True,
        browser_allow_vision_fallback=True,
        browser_allow_agent_browser_fallback=False,
    )

    path = save_settings(settings, tmp_path / "config.json")
    loaded = load_settings(path)

    assert loaded.browser_backend_policy == "chrome_devtools_when_consented"
    assert loaded.browser_session_mode == "browser_url"
    assert loaded.browser_devtools_browser_url == "http://127.0.0.1:9222"
    assert loaded.browser_devtools_ws_endpoint.endswith("/abc")
    assert loaded.browser_devtools_auto_connect is True
    assert loaded.browser_live_access_consent is True
    assert loaded.browser_allow_agent_browser_fallback is False


def test_browser_audit_redacts_sensitive_payload():
    redacted = redact_browser_audit_payload(
        {
            "backend": "chrome_devtools",
            "cookie": "session=secret",
            "target_url": "https://example.com/callback?token=secret",
            "page_content": "<html>secret</html>",
            "nested": {"token": "abc", "safe": "kept"},
        }
    )

    assert redacted["backend"] == "chrome_devtools"
    assert redacted["cookie"] == "[redacted]"
    assert redacted["target_url"] == "[redacted]"
    assert redacted["page_content"] == "[redacted]"
    assert redacted["nested"]["token"] == "[redacted]"
    assert redacted["nested"]["safe"] == "kept"


def test_browser_audit_detail_shape():
    detail = browser_audit_detail(
        backend=BrowserBackend.CHROME_DEVTOOLS,
        mode=BrowserSessionMode.BROWSER_URL,
        consent_state="denied",
        confirmation_state="not_required",
        fallback_reason="missing_consent",
        outcome="blocked",
        extra={"browser_url": "http://127.0.0.1:9222"},
    )

    assert '"backend": "chrome_devtools"' in detail
    assert '"session_mode": "browser_url"' in detail
    assert "127.0.0.1" not in detail


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


def test_browser_control_diagnostics_default_off(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api = SettingsApi()

    diagnostics = api.browser_control_diagnostics()

    assert diagnostics["ok"] is True
    assert diagnostics["non_attaching"] is True
    assert diagnostics["session_mode"] == "managed"
    assert diagnostics["live_access_consent"] is False
    assert diagnostics["attach_allowed"] is False
    assert diagnostics["safe_fallbacks"] == {"vision": True, "agent_browser": True}


def test_browser_control_diagnostics_detects_devtools_mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    api = SettingsApi()
    api.save_mcp_servers(
        [{"name": "chrome-devtools", "command": "npx", "args": ["chrome-devtools-mcp"]}]
    )

    diagnostics = api.browser_control_diagnostics()

    assert diagnostics["devtools_mcp_configured"] is True
    assert diagnostics["matching_mcp_servers"] == ["chrome-devtools"]


# --- CLI -----------------------------------------------------------------


def test_cli_settings_invokes_app(monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "run_settings_app", lambda: called.append(True))

    assert main_module.main(["settings"]) == 0
    assert called == [True]
