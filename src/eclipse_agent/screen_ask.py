"""Screen analysis module for Eclipse.

Captures a screenshot and sends it to the configured vision model for analysis.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_VISION_PROMPT = "Describe what you see on the screen and answer the user's question."


def _is_local_endpoint(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


@dataclass
class ScreenAskResult:
    success: bool
    answer: str
    model: str
    image_path: Path
    error: str = ""
    window_title: str | None = None
    fallback_reason: str = ""
    evidence: dict[str, str] = field(default_factory=dict)


def ask_about_screen(
    prompt: str,
    window_title: str | None = None,
    *,
    capture: Any = None,
    vision: Any = None,
    fallback_reason: str = "",
) -> ScreenAskResult:
    """Capture a screenshot then ask the vision model about it.

    Args:
        prompt: Question or instruction for the vision model.
        window_title: Optional window to capture (falls back to full screen).
        capture: Injectable screen capture device (PlatformFactory.get_screen_capture()).
        vision: Injectable VisionAdapter instance.
    """
    from eclipse_agent.planner import VisionAdapter, build_vision_config_from_env
    from eclipse_agent.pal.factory import PlatformFactory
    from eclipse_agent.safety import redact_screenshot

    if capture is None:
        capture = PlatformFactory.get_screen_capture()
    if vision is None:
        config = build_vision_config_from_env()
        vision = VisionAdapter(config)

    vision_model = vision.config.model if hasattr(vision, "config") else ""
    image_path = Path(tempfile.gettempdir()) / "eclipse-screen-ask.png"
    answer_prefix = ""

    try:
        res = capture.capture(output_path=str(image_path), dry_run=False)
        success = getattr(res, "success", True)
        if not success:
            msg = getattr(res, "message", "Screen capture failed.")
            return ScreenAskResult(
                success=False,
                answer="",
                model=vision_model,
                image_path=image_path,
                error=msg,
                window_title=window_title,
                fallback_reason=fallback_reason,
                evidence=_screen_fallback_evidence(
                    fallback_reason=fallback_reason,
                    window_title=window_title,
                    image_path=image_path,
                    outcome="capture_failed",
                ),
            )
        redact_screenshot(str(image_path))
    except Exception as exc:  # noqa: BLE001
        return ScreenAskResult(
            success=False,
            answer="",
            model=vision_model,
            image_path=image_path,
            error=str(exc),
            window_title=window_title,
            fallback_reason=fallback_reason,
            evidence=_screen_fallback_evidence(
                fallback_reason=fallback_reason,
                window_title=window_title,
                image_path=image_path,
                outcome="capture_failed",
            ),
        )

    if window_title:
        answer_prefix = f"[window '{window_title}' not found, used full screen] "

    full_prompt = prompt or DEFAULT_VISION_PROMPT
    try:
        result = vision.analyze_image(image_path, prompt=full_prompt)
    except Exception as exc:  # noqa: BLE001
        return ScreenAskResult(
            success=False,
            answer="",
            model=vision_model,
            image_path=image_path,
            error=str(exc),
            window_title=window_title,
            fallback_reason=fallback_reason,
            evidence=_screen_fallback_evidence(
                fallback_reason=fallback_reason,
                window_title=window_title,
                image_path=image_path,
                outcome="vision_failed",
            ),
        )

    if not result.success:
        return ScreenAskResult(
            success=False,
            answer="",
            model=result.model,
            image_path=image_path,
            error=result.message,
            window_title=window_title,
            fallback_reason=fallback_reason,
            evidence=_screen_fallback_evidence(
                fallback_reason=fallback_reason,
                window_title=window_title,
                image_path=image_path,
                outcome="vision_failed",
            ),
        )

    return ScreenAskResult(
        success=True,
        answer=answer_prefix + result.text,
        model=result.model,
        image_path=image_path,
        window_title=window_title,
        fallback_reason=fallback_reason,
        evidence=_screen_fallback_evidence(
            fallback_reason=fallback_reason,
            window_title=window_title,
            image_path=image_path,
            outcome="answered",
        ),
    )


def render_screen_ask_result(result: ScreenAskResult) -> str:
    if not result.success:
        return f"Screen ask failed: {result.error}"
    return result.answer


def _screen_fallback_evidence(
    *,
    fallback_reason: str,
    window_title: str | None,
    image_path: Path,
    outcome: str,
) -> dict[str, str]:
    """Return privacy-safe fallback evidence without page or OCR content."""

    return {
        "backend": "vision",
        "fallback_reason": fallback_reason,
        "window_title": window_title or "",
        "image_path": str(image_path),
        "outcome": outcome,
    }
