from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_HTML = ROOT / "src" / "eclipse_agent" / "gui" / "settings.html"

REQUIRED_FIELDS = [
    "weather_lat",
    "weather_lon",
    "briefing_enabled",
    "briefing_time",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_use_tls",
    "telegram_bot_token",
    "telegram_allowed_chats",
]

SECRET_FIELDS = ["smtp_password", "telegram_bot_token"]


def _html() -> str:
    return SETTINGS_HTML.read_text(encoding="utf-8")


def test_settings_gui_binds_new_settings_fields() -> None:
    html = _html()

    for field in REQUIRED_FIELDS:
        assert f'id="{field}"' in html
        assert re.search(rf'const FIELDS = \[[^\]]*"{field}"', html, re.S)


def test_settings_gui_marks_secret_fields_as_password_inputs() -> None:
    html = _html()

    for field in SECRET_FIELDS:
        assert re.search(rf'<input[^>]*id="{field}"[^>]*type="password"', html)
