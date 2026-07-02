import json

from eclipse_agent.audit import AuditLog
from eclipse_agent.browser_control import (
    BrowserBackend,
    BrowserControlRequest,
    BrowserControlService,
    BrowserSessionMode,
)
from eclipse_agent.settings import EclipseSettings


class FakeHealth:
    def __init__(self, *, available: bool, missing_tools: tuple[str, ...] = ()) -> None:
        self.available = available
        self.missing_tools = missing_tools


class FakeDevToolsAdapter:
    def __init__(self, health: FakeHealth) -> None:
        self.health_result = health
        self.calls: list[dict] = []

    def health(self, **kwargs):
        self.calls.append(kwargs)
        return self.health_result


def _settings(**overrides) -> EclipseSettings:
    return EclipseSettings(**overrides)


def test_service_uses_native_for_simple_open_without_live_consent():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=False),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(intent="open_url", action="open", url="https://example.com")
    )

    assert result.success is True
    assert result.backend is BrowserBackend.NATIVE
    assert result.mode is None
    assert adapter.calls == []


def test_service_routes_rich_request_to_devtools_when_consented():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(
            browser_live_access_consent=True,
            browser_session_mode=BrowserSessionMode.BROWSER_URL.value,
        ),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(intent="inspect", action="snapshot", requires_live_browser=True)
    )

    assert result.success is True
    assert result.backend is BrowserBackend.CHROME_DEVTOOLS
    assert result.mode is BrowserSessionMode.BROWSER_URL
    assert adapter.calls == [
        {"non_attaching": False, "required_capabilities": ("snapshot",)}
    ]


def test_service_missing_or_revoked_consent_fails_closed_before_adapter_health():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=False),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(intent="inspect", action="snapshot", requires_live_browser=True)
    )

    assert result.success is False
    assert result.backend is BrowserBackend.CHROME_DEVTOOLS
    assert result.fallback_reason == "missing_consent"
    assert "consent is required" in result.message
    assert adapter.calls == []


def test_service_blocks_confirmation_required_action_before_adapter_health():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=True),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(
            intent="message",
            action="send",
            text="hello",
            sensitive=True,
            requires_live_browser=True,
        ),
        confirmed=False,
    )

    assert result.success is False
    assert result.requires_confirmation is True
    assert result.backend is BrowserBackend.CHROME_DEVTOOLS
    assert "Confirmation required" in result.message
    assert adapter.calls == []


def test_service_allows_confirmed_sensitive_action():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=True),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(
            intent="message",
            action="send",
            text="hello",
            sensitive=True,
            requires_live_browser=True,
        ),
        confirmed=True,
    )

    assert result.success is True
    assert result.backend is BrowserBackend.CHROME_DEVTOOLS
    assert adapter.calls == [
        {"non_attaching": False, "required_capabilities": ("snapshot", "fill")}
    ]


def test_service_requires_confirmation_for_credential_fields_without_sensitive_flag():
    adapter = FakeDevToolsAdapter(FakeHealth(available=True))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=True),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(
            intent="login",
            action="fill",
            selector='input[name="password"]',
            requires_live_browser=True,
        ),
        confirmed=False,
    )

    assert result.success is False
    assert result.requires_confirmation is True
    assert adapter.calls == []


def test_service_falls_back_to_vision_when_devtools_tools_are_missing():
    adapter = FakeDevToolsAdapter(FakeHealth(available=False, missing_tools=("click",)))
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=True),
        devtools_adapter=adapter,
    )

    result = service.evaluate_request(
        BrowserControlRequest(intent="interact", action="click", requires_live_browser=True)
    )

    assert result.success is True
    assert result.backend is BrowserBackend.VISION
    assert result.fallback_reason == "missing_devtools_tools"


def test_service_redacts_audit_detail_and_records_privacy_safe_audit(tmp_path):
    audit_log = AuditLog(tmp_path / "audit.sqlite3")
    service = BrowserControlService(
        settings=_settings(browser_live_access_consent=False),
        audit_log=audit_log,
    )

    result = service.evaluate_request(
        BrowserControlRequest(
            intent="inspect",
            action="snapshot",
            url="https://example.com/account?token=secret",
            text="secret page text",
            metadata={"safe_fact": "kept"},
            requires_live_browser=True,
        )
    )

    detail = json.loads(result.audit_detail)
    assert detail["extra"]["url"] == "[redacted]"
    assert detail["extra"]["text"] == "[redacted]"
    assert detail["extra"]["safe_fact"] == "kept"
    assert "example.com" not in result.audit_detail
    assert "secret page text" not in result.audit_detail

    entries = audit_log.recent()
    assert entries[0].target == "inspect"
    assert entries[0].tool_name == "chrome_devtools"
    assert "example.com" not in entries[0].detail
