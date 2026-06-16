"""Bounded user-facing response formatting for routed voice actions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from eclipse_agent.tool_router import ToolExecutionResult

Polisher = Callable[[str, str, tuple[ToolExecutionResult, ...]], str]

_INTERNAL_PATTERNS = (
    re.compile(r"\bMCP\b", re.IGNORECASE),
    re.compile(r"structured result", re.IGNORECASE),
    re.compile(r"Traceback", re.IGNORECASE),
    re.compile(r"stderr|stdout", re.IGNORECASE),
    re.compile(r"\bnative\.[\w.-]+\b"),
    re.compile(r"[{}\[\]]"),
)
_SPANISH_MARKERS = (
    "abre",
    "abrir",
    "busca",
    "buscar",
    "busqué",
    "notificaciones",
    "dime",
    "qué",
    "modo",
)
_ENGLISH_MARKERS = ("open", "search", "google", "launch", "find", "browser")


class ActionResponseFormatter:
    """Format route results into concise speech-safe Spanish/English responses."""

    def __init__(
        self,
        *,
        max_sentences: int = 2,
        max_characters: int = 180,
        default_language: str = "es",
        polisher: Polisher | None = None,
    ) -> None:
        self.max_sentences = max(1, max_sentences)
        self.max_characters = max(24, max_characters)
        self.default_language = default_language
        self.polisher = polisher

    def format(
        self,
        *,
        command_text: str,
        route_results: tuple[ToolExecutionResult, ...],
        default_language: str | None = None,
    ) -> str:
        """Return bounded user-facing speech for routed action results."""

        language = _detect_language(command_text, default_language or self.default_language)
        template = self._template_response(language=language, route_results=route_results)
        bounded_template = self._bound(template)
        if self.polisher is None:
            return bounded_template
        try:
            polished = self.polisher(command_text, bounded_template, route_results)
        except Exception:  # noqa: BLE001
            return bounded_template
        bounded_polished = self._bound(str(polished).strip())
        if not bounded_polished or _contains_internal_text(bounded_polished):
            return bounded_template
        return bounded_polished

    def _template_response(
        self,
        *,
        language: str,
        route_results: tuple[ToolExecutionResult, ...],
    ) -> str:
        if not route_results:
            if language == "en":
                return (
                    "I could not find a safe action for that. "
                    "Ask me to open an app, search, or check notifications."
                )
            return (
                "No encontré una acción segura para eso. "
                "Pedime abrir una app, buscar algo o revisar notificaciones."
            )

        result = route_results[0]
        facts = _facts_for(result)
        target = _display_target(
            facts.get("target") or _safe_text(result.metadata.get("target", "")) or "eso"
        )
        action_type = str(facts.get("action_type") or "").strip()

        if result.success:
            return _success_template(language=language, action_type=action_type, target=target)

        reason = _safe_text(facts.get("failure_reason") or "")
        if not reason:
            reason = (
                "that action is not available yet"
                if language == "en"
                else "esa acción no está disponible todavía"
            )
        next_step = _safe_text(facts.get("next_step") or "")
        if action_type in {"browser_search", "google_search"}:
            response = (
                f"I could not search for {target}: {reason}."
                if language == "en"
                else f"No pude buscar {target}: {reason}."
            )
        elif language == "en":
            response = f"I could not open {target}: {reason}."
        else:
            response = f"No pude abrir {target}: {reason}."
        if next_step:
            response = f"{response} {next_step}."
        return response

    def _bound(self, text: str) -> str:
        sentences = _split_sentences(text)
        bounded = " ".join(sentences[: self.max_sentences]).strip() if sentences else text.strip()
        if len(bounded) <= self.max_characters:
            return bounded
        truncated = bounded[: self.max_characters].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return f"{truncated.rstrip('.')}…"


def _display_target(target: object) -> str:
    text = str(target).strip()
    if text.islower() and len(text.split()) <= 3:
        return text.title()
    return text


def _success_template(*, language: str, action_type: str, target: str) -> str:
    if action_type in {"browser_search", "google_search"}:
        return (
            f"Done, I searched for {target}."
            if language == "en"
            else f"Listo, busqué {target}."
        )
    return f"Done, I opened {target}." if language == "en" else f"Listo, abrí {target}."


def _facts_for(result: ToolExecutionResult) -> dict[str, Any]:
    structured = result.structured_content or {}
    facts = structured.get("user_facts")
    merged: dict[str, Any] = {}
    if isinstance(facts, dict):
        merged.update(facts)
    for key in ("success", "action_type", "target", "failure_reason", "next_step"):
        if key in structured:
            merged[key] = structured[key]
    return {key: value for key, value in merged.items() if isinstance(value, str | bool)}


def _safe_text(value: object) -> str:
    text = str(value).strip()
    if _contains_internal_text(text):
        return ""
    return text


def _contains_internal_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INTERNAL_PATTERNS)


def _detect_language(command_text: str, default_language: str) -> str:
    normalized = command_text.casefold()
    if any(marker in normalized for marker in _SPANISH_MARKERS):
        return "es"
    if any(marker in normalized for marker in _ENGLISH_MARKERS):
        return "en"
    return "en" if default_language.startswith("en") else "es"


def _split_sentences(text: str) -> list[str]:
    matches = re.findall(r"[^.!?]+[.!?]", text.strip())
    if matches:
        return [match.strip() for match in matches]
    return [text.strip()] if text.strip() else []
