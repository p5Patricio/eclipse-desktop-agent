"""Hermetic tests for screen_ask.py — no real screenshots, no real vision model."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from eclipse_agent.screen_ask import ScreenAskResult, ask_about_screen


def _write_valid_png(path: str) -> None:
    """Write a 1x1 white PNG using PIL (available in the venv)."""
    try:
        import io
        from PIL import Image
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        Path(path).write_bytes(buf.getvalue())
    except Exception:
        # Fallback: write a minimal valid PNG (1x1 white pixel)
        # This is the actual binary of a valid 1x1 white PNG
        PNG_1X1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        Path(path).write_bytes(PNG_1X1)


class _FakeCapture:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def capture(self, *, output_path: str, dry_run: bool = False) -> object:
        if self._fail:
            raise RuntimeError("capture device error")
        result = MagicMock()
        result.success = True
        result.message = f"Screenshot saved to {output_path}."
        _write_valid_png(output_path)
        return result


class _FakeVision:
    def __init__(self, *, success: bool = True, text: str = "There is an error dialog.") -> None:
        self._success = success
        self._text = text
        self.config = MagicMock()
        self.config.model = "fake-vision-model"

    def analyze_image(self, image_path: object, *, prompt: str) -> object:
        result = MagicMock()
        result.success = self._success
        result.model = "fake-vision-model"
        result.text = self._text if self._success else ""
        result.message = "" if self._success else "Vision model unavailable."
        return result


def test_screen_ask_no_vision_model_returns_error(tmp_path: Path) -> None:
    """When vision is unavailable, returns error result."""
    vision = _FakeVision(success=False)
    capture = _FakeCapture()
    result = ask_about_screen("what error is showing?", capture=capture, vision=vision)
    assert isinstance(result, ScreenAskResult)
    assert result.success is False
    assert result.error != ""
    assert result.answer == ""


def test_screen_ask_calls_vision_api(tmp_path: Path) -> None:
    """With injected capture and vision, returns the model's text."""
    vision = _FakeVision(success=True, text="I see a Python traceback.")
    capture = _FakeCapture()
    result = ask_about_screen("describe this", capture=capture, vision=vision)
    assert result.success is True
    assert "traceback" in result.answer.lower() or "I see" in result.answer
    assert result.error == ""


def test_screen_ask_handles_capture_error(tmp_path: Path) -> None:
    """If capture raises, returns an error result without crashing."""
    vision = _FakeVision(success=True)
    capture = _FakeCapture(fail=True)
    result = ask_about_screen("what's on screen?", capture=capture, vision=vision)
    assert result.success is False
    assert "capture device error" in result.error


def test_screen_ask_window_not_found_prefix() -> None:
    """Window title provided → prefix added to answer."""
    vision = _FakeVision(success=True, text="Full screen content.")
    capture = _FakeCapture()
    result = ask_about_screen(
        "what do you see?",
        window_title="Nonexistent App",
        capture=capture,
        vision=vision,
    )
    assert result.success is True
    assert "Nonexistent App" in result.answer
    assert "not found" in result.answer
