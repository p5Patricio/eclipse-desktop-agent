"""Deterministic voice-intent handling for Eclipse notification commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from eclipse_agent.notifications import (
    NotificationAction,
    NotificationDigest,
    NotificationFocusMode,
    NotificationRule,
    NotificationStatus,
    NotificationStore,
    build_notification_digest,
    expires_after_minutes,
)


class NotificationVoiceIntentKind(StrEnum):
    """Supported notification voice intents."""

    SET_MODE = "set_mode"
    MUTE_SOURCES = "mute_sources"
    SUMMARIZE = "summarize"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class NotificationVoiceIntent:
    """Parsed notification command from a spoken/transcribed phrase."""

    kind: NotificationVoiceIntentKind
    original_text: str
    mode: NotificationFocusMode | None = None
    sources: tuple[str, ...] = ()
    minutes: int | None = None
    action: NotificationAction = NotificationAction.QUEUE
    message: str = ""


@dataclass(frozen=True, kw_only=True)
class NotificationVoiceIntentResult:
    """Execution result for a parsed notification voice intent."""

    success: bool
    intent: NotificationVoiceIntent
    message: str
    digest: NotificationDigest | None = None


KNOWN_NOTIFICATION_SOURCES = (
    "Instagram",
    "Messenger",
    "WhatsApp",
    "Gmail",
    "Telegram",
    "Signal",
    "Discord",
    "Slack",
    "YouTube",
    "YouTube Music",
    "Chrome",
)


def parse_notification_voice_intent(text: str) -> NotificationVoiceIntent:
    """Parse common Spanish notification commands without an LLM."""

    normalized = _normalize(text)
    if not normalized:
        return _unknown(text, "No entendí el comando de notificaciones.")

    minutes = _parse_duration_minutes(normalized)

    mode = _parse_mode(normalized)
    if mode is not None:
        return NotificationVoiceIntent(
            kind=NotificationVoiceIntentKind.SET_MODE,
            original_text=text,
            mode=mode,
            minutes=minutes,
            message=f"Cambiar modo de notificaciones a {mode.value}.",
        )

    if _looks_like_mute_command(normalized):
        sources = _extract_sources(normalized)
        if not sources:
            return _unknown(text, "No detecté qué app o página debo silenciar.")
        return NotificationVoiceIntent(
            kind=NotificationVoiceIntentKind.MUTE_SOURCES,
            original_text=text,
            sources=sources,
            minutes=minutes,
            action=NotificationAction.QUEUE,
            message="Silenciar fuentes y guardar eventos para resumen posterior.",
        )

    if _looks_like_summary_command(normalized):
        return NotificationVoiceIntent(
            kind=NotificationVoiceIntentKind.SUMMARIZE,
            original_text=text,
            message="Resumir notificaciones pendientes.",
        )

    return _unknown(text, "Comando de notificaciones no soportado todavía.")


def execute_notification_voice_intent(
    intent: NotificationVoiceIntent,
    *,
    store: NotificationStore | None = None,
    mark_announced: bool = False,
) -> NotificationVoiceIntentResult:
    """Apply a parsed notification intent to the local notification store."""

    store = store or NotificationStore()
    if intent.kind is NotificationVoiceIntentKind.SET_MODE and intent.mode:
        state = store.set_focus_mode(
            intent.mode,
            expires_at=expires_after_minutes(intent.minutes),
        )
        expires = state.mode_expires_at.isoformat() if state.mode_expires_at else "manual"
        return NotificationVoiceIntentResult(
            success=True,
            intent=intent,
            message=f"Modo de notificaciones: {state.mode.value}; expira: {expires}.",
        )

    if intent.kind is NotificationVoiceIntentKind.MUTE_SOURCES:
        rules = tuple(
            store.save_rule(
                NotificationRule(
                    app_pattern=source,
                    action=intent.action,
                    expires_at=expires_after_minutes(intent.minutes),
                )
            )
            for source in intent.sources
        )
        labels = ", ".join(rule.app_pattern for rule in rules)
        return NotificationVoiceIntentResult(
            success=True,
            intent=intent,
            message=f"Silencié {labels}; guardaré esas notificaciones para después.",
        )

    if intent.kind is NotificationVoiceIntentKind.SUMMARIZE:
        pending = store.list_pending()
        digest = build_notification_digest(pending)
        if mark_announced:
            store.mark_events((event.id for event in pending), NotificationStatus.ANNOUNCED)
        return NotificationVoiceIntentResult(
            success=True,
            intent=intent,
            digest=digest,
            message=digest.render(),
        )

    return NotificationVoiceIntentResult(
        success=False,
        intent=intent,
        message=intent.message,
    )


def render_notification_voice_intent_result(result: NotificationVoiceIntentResult) -> str:
    """Render voice-intent execution for CLI output."""

    status = "ok" if result.success else "blocked"
    lines = [f"Notification intent [{status}] {result.intent.kind.value}: {result.message}"]
    if result.intent.sources:
        lines.append(f"sources: {', '.join(result.intent.sources)}")
    if result.intent.minutes:
        lines.append(f"duration_minutes: {result.intent.minutes}")
    return "\n".join(lines)


def _parse_mode(normalized: str) -> NotificationFocusMode | None:
    if "modo juego" in normalized or "estoy jugando" in normalized:
        return NotificationFocusMode.GAME
    if "modo privado" in normalized or "privado" in normalized:
        return NotificationFocusMode.PRIVATE
    if "modo foco" in normalized or "no me molestes" in normalized:
        return NotificationFocusMode.FOCUS
    if "modo normal" in normalized or "vuelve a avisarme" in normalized:
        return NotificationFocusMode.NORMAL
    return None


def _looks_like_mute_command(normalized: str) -> bool:
    return any(
        phrase in normalized
        for phrase in (
            "no me avises",
            "no me notifiques",
            "silencia",
            "mutea",
            "guarda las notificaciones de",
        )
    )


def _looks_like_summary_command(normalized: str) -> bool:
    return any(
        phrase in normalized
        for phrase in (
            "dime que llego",
            "dime qué llegó",
            "que llego",
            "qué llegó",
            "resume mis notificaciones",
            "resumen de notificaciones",
            "notificaciones pendientes",
        )
    )


def _extract_sources(normalized: str) -> tuple[str, ...]:
    found = tuple(
        source
        for source in KNOWN_NOTIFICATION_SOURCES
        if _normalize(source) in normalized
    )
    return tuple(dict.fromkeys(found))


def _parse_duration_minutes(normalized: str) -> int | None:
    if "media hora" in normalized:
        return 30
    if "una hora" in normalized or "1 hora" in normalized:
        return 60

    match = re.search(r"(\d+)\s*(minuto|minutos|hora|horas)", normalized)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("hora"):
        return value * 60
    return value


def _unknown(text: str, message: str) -> NotificationVoiceIntent:
    return NotificationVoiceIntent(
        kind=NotificationVoiceIntentKind.UNKNOWN,
        original_text=text,
        message=message,
    )


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())
