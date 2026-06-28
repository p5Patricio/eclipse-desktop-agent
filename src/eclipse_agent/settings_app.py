"""Desktop settings app for Eclipse, built with pywebview.

A native window hosts an HTML/CSS settings page; this ``SettingsApi`` is the
bridge the page calls (``window.pywebview.api.*``) to load, save and test the
configuration. The API methods are pure-Python and testable; only
``run_settings_app`` opens the window.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from eclipse_agent.audit import AuditLog
from eclipse_agent.killswitch import KillSwitch
from eclipse_agent.settings import (
    EclipseSettings,
    load_settings,
    save_settings,
    settings_from_dict,
)
from eclipse_agent.tray import fetch_status

GUI_DIR = Path(__file__).parent / "gui"


def daemon_command(settings: EclipseSettings) -> list[str]:
    """Build the always-on daemon command from settings."""

    command = [
        sys.executable, "-m", "eclipse_agent", "wake-efficient",
        "--iterations", "0", "--execute", "--speak", "--confirmed",
        "--builtin-wakeword", settings.builtin_wakeword or "hey_jarvis",
        "--model", settings.whisper_model or "small",
        "--wake-threshold", str(settings.wake_threshold),
    ]
    if settings.auto_execute:
        command.append("--route-execute")
    return command


def _default_spawn(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command)  # noqa: S603


class SettingsApi:
    """The Python API exposed to the settings web page."""

    def __init__(self, *, spawn: Callable[[list[str]], object] | None = None) -> None:
        self._spawn = spawn or _default_spawn
        self._daemon: object | None = None
        self._kill_switch = KillSwitch()
        self._audit_log = AuditLog()

    def get_settings(self) -> dict:
        return asdict(load_settings())

    def save_settings(self, data: dict) -> dict:
        try:
            path = save_settings(settings_from_dict(data))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"No se pudo guardar: {exc}"}
        return {"ok": True, "message": f"Configuración guardada en {path}."}

    def test_ollama(self, base_url: str = "http://localhost:11434") -> dict:
        url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
                payload = json.load(response)
        except Exception:  # noqa: BLE001
            return {"ok": False, "message": "Ollama no responde en esa dirección."}
        models = [model.get("name", "") for model in payload.get("models", [])]
        return {
            "ok": True,
            "message": "Ollama conectado. Modelos: " + (", ".join(models) or "ninguno"),
            "models": models,
        }

    # --- daemon control ---

    def _daemon_running(self) -> bool:
        return self._daemon is not None and self._daemon.poll() is None  # type: ignore[attr-defined]

    def daemon_status(self) -> dict:
        return {"running": self._daemon_running(), "status": fetch_status()}

    def start_daemon(self) -> dict:
        if self._daemon_running():
            return {"ok": False, "message": "Eclipse ya está corriendo."}
        try:
            self._daemon = self._spawn(daemon_command(load_settings()))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"No pude iniciar Eclipse: {exc}"}
        return {"ok": True, "message": "Eclipse iniciado."}

    def stop_daemon(self) -> dict:
        if not self._daemon_running():
            return {"ok": False, "message": "Eclipse no estaba corriendo."}
        try:
            self._daemon.terminate()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"No pude detener Eclipse: {exc}"}
        return {"ok": True, "message": "Eclipse detenido."}

    # --- safety ---

    def kill_switch_state(self) -> dict:
        return {"engaged": self._kill_switch.is_engaged()}

    def set_kill_switch(self, engaged: bool) -> dict:
        if engaged:
            self._kill_switch.engage()
        else:
            self._kill_switch.disengage()
        return {"engaged": self._kill_switch.is_engaged()}

    def recent_audit(self, limit: int = 15) -> list[dict]:
        return [
            {
                "timestamp": entry.timestamp.isoformat(),
                "status": entry.status,
                "action_kind": entry.action_kind,
                "target": entry.target,
                "risk_level": entry.risk_level,
            }
            for entry in self._audit_log.recent(limit=limit)
        ]

    def list_tts_voices(self) -> list[str]:
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer

            return [voice.display_name for voice in SpeechSynthesizer.all_voices]
        except Exception:  # noqa: BLE001
            pass
        try:
            import win32com.client

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            return [token.GetAttribute("Name") for token in speaker.GetVoices()]
        except Exception:  # noqa: BLE001
            return []


def run_settings_app() -> None:  # pragma: no cover - GUI window
    try:
        import webview
    except ModuleNotFoundError:
        print('The settings app needs the "gui" extra: pip install -e ".[gui]".')
        return
    html = (GUI_DIR / "settings.html").read_text(encoding="utf-8")
    webview.create_window(
        "Eclipse — Configuración",
        html=html,
        js_api=SettingsApi(),
        width=760,
        height=840,
        min_size=(640, 600),
    )
    webview.start()
