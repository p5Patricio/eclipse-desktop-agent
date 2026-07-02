"""Browser-control contracts, safety shells, and privacy-safe audit helpers.

This foundation module intentionally does not attach to Chrome or call DevTools.
It defines the shared contracts used by later browser-control slices while
keeping live browser access fail-closed by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BrowserBackend(StrEnum):
    """Supported browser-control backends."""

    NATIVE = "native"
    CHROME_DEVTOOLS = "chrome_devtools"
    VISION = "vision"
    AGENT_BROWSER = "agent_browser"


class BrowserSessionMode(StrEnum):
    """Chrome DevTools MCP session modes."""

    MANAGED = "managed"
    BROWSER_URL = "browser_url"
    WS_ENDPOINT = "ws_endpoint"
    AUTO_CONNECT = "auto_connect"


class BrowserBackendPolicy(StrEnum):
    """High-level backend policy persisted in settings."""

    NATIVE_SIMPLE_PLUS_FALLBACK = "native_simple_plus_fallback"
    CHROME_DEVTOOLS_WHEN_CONSENTED = "chrome_devtools_when_consented"


@dataclass(frozen=True)
class BrowserControlRequest:
    """A normalized browser-control request before backend routing."""

    intent: str
    url: str = ""
    action: str = ""
    selector: str = ""
    text: str = ""
    sensitive: bool = False
    requires_live_browser: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserControlResult:
    """Result of allowing, blocking, or completing a browser-control request."""

    success: bool
    backend: BrowserBackend
    mode: BrowserSessionMode | None
    message: str
    fallback_reason: str = ""
    requires_confirmation: bool = False
    audit_detail: str = ""


@dataclass(frozen=True)
class BrowserConsentPolicy:
    """Consent shell for any DevTools session that can inspect live browser state."""

    live_access_allowed: bool = False
    allowed_session_modes: tuple[BrowserSessionMode, ...] = tuple(BrowserSessionMode)

    def allows_live_access(self, mode: BrowserSessionMode) -> bool:
        """Return whether DevTools may attach or inspect in the selected mode."""

        return self.live_access_allowed and mode in self.allowed_session_modes


@dataclass(frozen=True)
class BrowserConfirmationPolicy:
    """Confirmation shell for sensitive browser actions."""

    require_sensitive_confirmation: bool = True
    sensitive_actions: tuple[str, ...] = (
        "submit",
        "post",
        "publish",
        "purchase",
        "delete",
        "send",
        "account",
        "payment",
    )

    def requires_confirmation(self, request: BrowserControlRequest) -> bool:
        """Return whether the request should be confirmed before execution."""

        if not self.require_sensitive_confirmation:
            return False
        action = request.action.casefold()
        return request.sensitive or any(token in action for token in self.sensitive_actions)


@dataclass(frozen=True)
class BrowserFallbackPolicy:
    """Fallback toggles used when DevTools is unavailable, denied, or insufficient."""

    allow_vision: bool = True
    allow_agent_browser: bool = True


_SECRET_KEY_TOKENS = (
    "authorization",
    "browser_url",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "target_url",
    "url",
    "ws_endpoint",
)
_CONTENT_KEY_TOKENS = (
    "dom",
    "html",
    "page_content",
    "screenshot",
    "snapshot",
    "text",
)
_MAX_AUDIT_VALUE_LENGTH = 160


def browser_audit_detail(
    *,
    backend: BrowserBackend,
    mode: BrowserSessionMode | None,
    consent_state: str,
    confirmation_state: str,
    fallback_reason: str = "",
    outcome: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Build a redacted JSON audit detail payload for browser-control events."""

    payload: dict[str, Any] = {
        "backend": backend.value,
        "session_mode": mode.value if mode else "",
        "consent_state": consent_state,
        "confirmation_state": confirmation_state,
        "fallback_reason": fallback_reason,
        "outcome": outcome,
    }
    if extra:
        payload["extra"] = extra
    return json.dumps(redact_browser_audit_payload(payload), sort_keys=True)


def redact_browser_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and page content from an audit payload."""

    return {
        str(key): _redact_value(str(key), value)
        for key, value in payload.items()
    }


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.casefold()
    if any(token in lowered for token in _SECRET_KEY_TOKENS):
        return "[redacted]"
    if any(token in lowered for token in _CONTENT_KEY_TOKENS):
        return "[redacted]"
    if isinstance(value, dict):
        return redact_browser_audit_payload(value)
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(key, item) for item in value)
    if isinstance(value, str) and len(value) > _MAX_AUDIT_VALUE_LENGTH:
        return f"{value[:_MAX_AUDIT_VALUE_LENGTH]}..."
    return value
