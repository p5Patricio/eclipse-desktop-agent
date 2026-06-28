"""User-facing settings for Eclipse, persisted as JSON.

The desktop settings app reads and writes this ``config.json``. The rest of
Eclipse keeps reading ``ECLIPSE_*`` environment variables, so ``apply_to_env``
bridges the saved settings into the environment at startup. Settings the user
left blank do not clobber an existing env value, so a hand-written ``.env`` still
fills any gaps.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class EclipseSettings:
    """All user-configurable Eclipse settings."""

    # LLM / reasoning
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5vl:7b"
    llm_base_url: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    # Embeddings (document Q&A)
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = ""
    # Vision
    vision_model: str = "qwen2.5vl:7b"
    # Voice
    tts_neural: bool = True
    tts_voice: str = ""
    whisper_model: str = "small"
    wake_threshold: float = 0.5
    builtin_wakeword: str = "hey_jarvis"
    # Email (read-only IMAP)
    imap_host: str = "imap.gmail.com"
    imap_user: str = ""
    imap_password: str = ""
    # Calendar (read-only iCal)
    calendar_ics_url: str = ""
    # Safety: whether the always-on daemon executes low-risk actions automatically
    auto_execute: bool = False


_ENV_MAP: dict[str, str] = {
    "llm_provider": "ECLIPSE_LLM_PROVIDER",
    "llm_model": "ECLIPSE_LLM_MODEL",
    "llm_base_url": "ECLIPSE_LLM_BASE_URL",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "embed_model": "ECLIPSE_EMBED_MODEL",
    "embed_base_url": "ECLIPSE_EMBED_BASE_URL",
    "vision_model": "ECLIPSE_VISION_MODEL",
    "tts_neural": "ECLIPSE_TTS_NEURAL",
    "tts_voice": "ECLIPSE_TTS_VOICE",
    "whisper_model": "ECLIPSE_WHISPER_MODEL",
    "wake_threshold": "ECLIPSE_WAKE_THRESHOLD",
    "builtin_wakeword": "ECLIPSE_BUILTIN_WAKEWORD",
    "imap_host": "ECLIPSE_IMAP_HOST",
    "imap_user": "ECLIPSE_IMAP_USER",
    "imap_password": "ECLIPSE_IMAP_PASSWORD",
    "calendar_ics_url": "ECLIPSE_CALENDAR_ICS_URL",
}


def settings_from_dict(data: dict) -> EclipseSettings:
    """Build settings from a dict, ignoring unknown keys and keeping defaults."""

    known = {field.name for field in fields(EclipseSettings)}
    defaults = EclipseSettings()
    values: dict[str, object] = {}
    for name in known:
        if name not in data:
            continue
        current = getattr(defaults, name)
        raw = data[name]
        if isinstance(current, bool):
            values[name] = bool(raw)
        elif isinstance(current, float):
            try:
                values[name] = float(raw)
            except (TypeError, ValueError):
                values[name] = current
        else:
            values[name] = "" if raw is None else str(raw)
    return EclipseSettings(**values)


def load_settings(path: str | Path | None = None) -> EclipseSettings:
    """Load settings from JSON, falling back to defaults."""

    resolved = Path(path).expanduser() if path else default_settings_path()
    if not resolved.exists():
        return EclipseSettings()
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return EclipseSettings()
    return settings_from_dict(data if isinstance(data, dict) else {})


def save_settings(settings: EclipseSettings, path: str | Path | None = None) -> Path:
    """Persist settings to JSON."""

    resolved = Path(path).expanduser() if path else default_settings_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return resolved


def apply_to_env(settings: EclipseSettings, env: dict | None = None) -> None:
    """Apply settings to environment variables (blank values are left alone)."""

    target = env if env is not None else os.environ
    for name, env_name in _ENV_MAP.items():
        value = getattr(settings, name)
        if isinstance(value, bool):
            target[env_name] = "1" if value else "0"
        elif value == "" or value is None:
            continue
        else:
            target[env_name] = str(value)


def default_settings_path() -> Path:
    return _config_dir() / "config.json"


def default_mcp_config_path() -> Path:
    return _config_dir() / "mcp-servers.json"


def load_mcp_servers(path: str | Path | None = None) -> list[dict]:
    """Load configured MCP servers as a list of {name, command, args}."""

    resolved = Path(path).expanduser() if path else default_mcp_config_path()
    if not resolved.exists():
        return []
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    servers = data.get("servers", []) if isinstance(data, dict) else []
    return [s for s in servers if isinstance(s, dict)]


def save_mcp_servers(servers: list[dict], path: str | Path | None = None) -> Path:
    """Persist MCP servers, keeping only entries with a name and command."""

    resolved = Path(path).expanduser() if path else default_mcp_config_path()
    cleaned = [
        {
            "name": str(server["name"]).strip(),
            "command": str(server["command"]).strip(),
            "args": list(server.get("args", []) or []),
        }
        for server in servers
        if str(server.get("name", "")).strip() and str(server.get("command", "")).strip()
    ]
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps({"servers": cleaned}, indent=2), encoding="utf-8")
    return resolved


def _config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent"
