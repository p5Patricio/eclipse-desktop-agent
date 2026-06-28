"""Desktop settings app for Eclipse, built with pywebview.

A native window hosts an HTML/CSS settings page; this ``SettingsApi`` is the
bridge the page calls (``window.pywebview.api.*``) to load, save and test the
configuration. The API methods are pure-Python and testable; only
``run_settings_app`` opens the window.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict
from pathlib import Path

from eclipse_agent.settings import load_settings, save_settings, settings_from_dict

GUI_DIR = Path(__file__).parent / "gui"


class SettingsApi:
    """The Python API exposed to the settings web page."""

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
