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


# --- CLI -----------------------------------------------------------------


def test_cli_settings_invokes_app(monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "run_settings_app", lambda: called.append(True))

    assert main_module.main(["settings"]) == 0
    assert called == [True]
