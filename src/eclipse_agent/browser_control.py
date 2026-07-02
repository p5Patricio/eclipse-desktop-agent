"""Browser-control contracts, safety shells, and privacy-safe audit helpers.

This foundation module intentionally does not attach to Chrome or call DevTools.
It defines the shared contracts used by later browser-control slices while
keeping live browser access fail-closed by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from eclipse_agent.audit import AuditEntry, AuditLog
from eclipse_agent.settings import EclipseSettings


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


class DevToolsAdapterProtocol(Protocol):
    """Small adapter surface used by BrowserControlService policy checks."""

    def health(
        self,
        *,
        non_attaching: bool = True,
        required_capabilities: tuple[str, ...] = (),
    ) -> Any:
        """Return non-attaching Chrome DevTools MCP diagnostics."""


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
        "auth",
        "credential",
        "submit",
        "post",
        "publish",
        "purchase",
        "delete",
        "send",
        "account",
        "login",
        "payment",
        "password",
        "secret",
        "token",
    )

    def requires_confirmation(self, request: BrowserControlRequest) -> bool:
        """Return whether the request should be confirmed before execution."""

        if not self.require_sensitive_confirmation:
            return False
        action = request.action.casefold()
        selector = request.selector.casefold()
        metadata = " ".join(f"{key} {value}" for key, value in request.metadata.items()).casefold()
        haystack = " ".join((action, selector, metadata))
        return request.sensitive or any(token in haystack for token in self.sensitive_actions)


@dataclass(frozen=True)
class BrowserFallbackPolicy:
    """Fallback toggles used when DevTools is unavailable, denied, or insufficient."""

    allow_vision: bool = True
    allow_agent_browser: bool = True


class BrowserControlService:
    """Classify browser requests and enforce consent/confirmation/fallback policy.

    This PR2 service deliberately does not integrate with runtime callers yet. It
    makes the policy decision explicit and keeps DevTools attach/tool calls behind
    consent and confirmation gates for the later routing slice.
    """

    def __init__(
        self,
        *,
        settings: EclipseSettings | None = None,
        devtools_adapter: DevToolsAdapterProtocol | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.settings = settings or EclipseSettings()
        self.devtools_adapter = devtools_adapter
        self.audit_log = audit_log
        self.session_mode = _session_mode_from_settings(self.settings)
        self.consent_policy = BrowserConsentPolicy(
            live_access_allowed=bool(self.settings.browser_live_access_consent),
        )
        self.confirmation_policy = BrowserConfirmationPolicy(
            require_sensitive_confirmation=bool(
                self.settings.browser_confirm_sensitive_actions
            ),
        )
        self.fallback_policy = BrowserFallbackPolicy(
            allow_vision=bool(self.settings.browser_allow_vision_fallback),
            allow_agent_browser=bool(self.settings.browser_allow_agent_browser_fallback),
        )

    def classify_backend(self, request: BrowserControlRequest) -> BrowserBackend:
        """Return the least-powerful sufficient backend for the request."""

        if _is_simple_native_request(request):
            return BrowserBackend.NATIVE
        return BrowserBackend.CHROME_DEVTOOLS

    def evaluate_request(
        self,
        request: BrowserControlRequest,
        *,
        confirmed: bool = False,
    ) -> BrowserControlResult:
        """Evaluate routing policy without performing browser side effects."""

        backend = self.classify_backend(request)
        if backend is BrowserBackend.NATIVE:
            return self._finish(
                request,
                backend=BrowserBackend.NATIVE,
                success=True,
                message="Use native open/search for this simple browser action.",
                consent_state="not_required",
                confirmation_state="not_required",
                outcome="prepared",
            )

        consent_state = (
            "granted"
            if self.consent_policy.allows_live_access(self.session_mode)
            else "denied"
        )
        confirmation_required = self.confirmation_policy.requires_confirmation(request)
        confirmation_state = _confirmation_state(
            required=confirmation_required,
            confirmed=confirmed,
        )

        if consent_state != "granted":
            return self._finish(
                request,
                backend=BrowserBackend.CHROME_DEVTOOLS,
                success=False,
                message=(
                    "Live browser access consent is required before Chrome DevTools "
                    "MCP can inspect or control this browser session."
                ),
                consent_state=consent_state,
                confirmation_state=confirmation_state,
                fallback_reason="missing_consent",
                outcome="blocked",
            )

        if confirmation_required and not confirmed:
            return self._finish(
                request,
                backend=BrowserBackend.CHROME_DEVTOOLS,
                success=False,
                message=_confirmation_message(request),
                consent_state=consent_state,
                confirmation_state=confirmation_state,
                outcome="blocked",
                requires_confirmation=True,
            )

        required_capabilities = _required_devtools_capabilities(request)
        if self.devtools_adapter is None:
            fallback = self._fallback_result(
                request,
                reason="devtools_unavailable",
                consent_state=consent_state,
                confirmation_state=confirmation_state,
            )
            if fallback is not None:
                return fallback
            return self._finish(
                request,
                backend=BrowserBackend.CHROME_DEVTOOLS,
                success=False,
                message="Chrome DevTools MCP adapter is not available for this browser action.",
                consent_state=consent_state,
                confirmation_state=confirmation_state,
                fallback_reason="devtools_unavailable",
                outcome="failed",
            )
        else:
            health = self.devtools_adapter.health(
                non_attaching=False,
                required_capabilities=required_capabilities,
            )
            missing_tools = tuple(getattr(health, "missing_tools", ()))
            available = bool(getattr(health, "available", False))
            if not available:
                reason = "missing_devtools_tools" if missing_tools else "devtools_unavailable"
                fallback = self._fallback_result(
                    request,
                    reason=reason,
                    consent_state=consent_state,
                    confirmation_state=confirmation_state,
                )
                if fallback is not None:
                    return fallback
                return self._finish(
                    request,
                    backend=BrowserBackend.CHROME_DEVTOOLS,
                    success=False,
                    message="Chrome DevTools MCP is unavailable for this browser action.",
                    consent_state=consent_state,
                    confirmation_state=confirmation_state,
                    fallback_reason=reason,
                    outcome="failed",
                )

        return self._finish(
            request,
            backend=BrowserBackend.CHROME_DEVTOOLS,
            success=True,
            message="Chrome DevTools MCP is allowed for this rich browser action.",
            consent_state=consent_state,
            confirmation_state=confirmation_state,
            outcome="prepared",
        )

    def _fallback_result(
        self,
        request: BrowserControlRequest,
        *,
        reason: str,
        consent_state: str,
        confirmation_state: str,
    ) -> BrowserControlResult | None:
        if consent_state != "granted":
            return None
        if self.fallback_policy.allow_vision:
            return self._finish(
                request,
                backend=BrowserBackend.VISION,
                success=True,
                message="Use screenshot+vision fallback for this browser action.",
                consent_state=consent_state,
                confirmation_state=confirmation_state,
                fallback_reason=reason,
                outcome="fallback_prepared",
            )
        if self.fallback_policy.allow_agent_browser:
            return self._finish(
                request,
                backend=BrowserBackend.AGENT_BROWSER,
                success=True,
                message="Use legacy agent-browser fallback for this browser action.",
                consent_state=consent_state,
                confirmation_state=confirmation_state,
                fallback_reason=reason,
                outcome="fallback_prepared",
            )
        return None

    def _finish(
        self,
        request: BrowserControlRequest,
        *,
        backend: BrowserBackend,
        success: bool,
        message: str,
        consent_state: str,
        confirmation_state: str,
        outcome: str,
        fallback_reason: str = "",
        requires_confirmation: bool = False,
    ) -> BrowserControlResult:
        detail = browser_audit_detail(
            backend=backend,
            mode=self.session_mode if backend is BrowserBackend.CHROME_DEVTOOLS else None,
            consent_state=consent_state,
            confirmation_state=confirmation_state,
            fallback_reason=fallback_reason,
            outcome=outcome,
            extra={
                "intent": request.intent,
                "action": request.action,
                "url": request.url,
                "selector": request.selector,
                "text": request.text,
                **request.metadata,
            },
        )
        self._record_audit(
            request,
            backend=backend,
            success=success,
            requires_confirmation=requires_confirmation,
            detail=detail,
        )
        return BrowserControlResult(
            success=success,
            backend=backend,
            mode=self.session_mode if backend is BrowserBackend.CHROME_DEVTOOLS else None,
            message=message,
            fallback_reason=fallback_reason,
            requires_confirmation=requires_confirmation,
            audit_detail=detail,
        )

    def _record_audit(
        self,
        request: BrowserControlRequest,
        *,
        backend: BrowserBackend,
        success: bool,
        requires_confirmation: bool,
        detail: str,
    ) -> None:
        if self.audit_log is None:
            return
        status = "blocked" if requires_confirmation or not success else "prepared"
        try:
            self.audit_log.record(
                AuditEntry(
                    action_kind="browser_control",
                    target=request.intent or request.action or "browser",
                    risk_level="high" if request.sensitive else "medium",
                    status=status,
                    tool_name=backend.value,
                    detail=detail,
                )
            )
        except Exception:  # noqa: BLE001 - audit failures must not affect policy
            pass


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


def _session_mode_from_settings(settings: EclipseSettings) -> BrowserSessionMode:
    try:
        return BrowserSessionMode(settings.browser_session_mode)
    except ValueError:
        return BrowserSessionMode.MANAGED


def _is_simple_native_request(request: BrowserControlRequest) -> bool:
    action = request.action.casefold()
    intent = request.intent.casefold()
    if request.sensitive or request.requires_live_browser or request.selector or request.text:
        return False
    if action in {"open", "open_url", "search", "browser_search", "google_search"}:
        return True
    return intent in {"open_web_app", "open_url", "browser_search", "google_search"}


def _required_devtools_capabilities(request: BrowserControlRequest) -> tuple[str, ...]:
    action = request.action.casefold()
    if "click" in action:
        return ("snapshot", "click")
    if any(token in action for token in ("fill", "type", "submit", "send", "post")):
        return ("snapshot", "fill")
    if "screenshot" in action:
        return ("screenshot",)
    if any(token in action for token in ("evaluate", "script", "console")):
        return ("evaluate",)
    if any(token in action for token in ("navigate", "open")):
        return ("navigate",)
    return ("snapshot",)


def _confirmation_state(*, required: bool, confirmed: bool) -> str:
    if not required:
        return "not_required"
    return "confirmed" if confirmed else "required"


def _confirmation_message(request: BrowserControlRequest) -> str:
    action = request.action or request.intent or "browser action"
    target = request.metadata.get("target") or request.url or "the current browser page"
    return f"Confirmation required before Eclipse can {action} on {target}."
