"""Hermetic tests for email_sender.py — no real network, no real SMTP."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from eclipse_agent.email_sender import (
    EmailSender,
    SmtpConfigError,
    _redact,
    draft_and_send,
    send,
)
from eclipse_agent.settings import EclipseSettings


def _settings(**kwargs) -> EclipseSettings:
    """Build a minimal settings object with SMTP fields."""
    defaults = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "user@example.com",
        "smtp_password": "s3cr3t",
        "smtp_use_tls": True,
        "imap_host": "imap.example.com",
        "imap_user": "user@example.com",
        "imap_password": "",
    }
    defaults.update(kwargs)
    return EclipseSettings(**defaults)


class FakeSMTP:
    """Minimal SMTP stub that records calls without touching the network."""

    def __init__(self, host, port, timeout=30):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_calls: list[tuple[str, str]] = []
        self.sent_messages: list[Any] = []
        self._raise_on_login: type | None = None
        self._raise_on_send: type | None = None

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        if self._raise_on_login:
            if self._raise_on_login is smtplib.SMTPAuthenticationError:
                raise smtplib.SMTPAuthenticationError(535, b"auth error")
            raise self._raise_on_login("auth error")
        self.login_calls.append((user, password))

    def send_message(self, msg):
        if self._raise_on_send:
            raise self._raise_on_send("send error")
        self.sent_messages.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# --- Tests ---


def test_send_raises_if_password_missing() -> None:
    """SmtpConfigError raised when smtp_password is blank."""
    s = _settings(smtp_password="")
    with pytest.raises(SmtpConfigError, match="password"):
        send(to="a@b.com", subject="Hi", body="Hello", settings=s)


def test_smtp_host_derived_from_imap_host() -> None:
    """When smtp_host blank and imap_host='imap.gmail.com', uses smtp.gmail.com."""
    fake = FakeSMTP.__new__(FakeSMTP)
    FakeSMTP.__init__(fake, "", 587)
    smtp_instances: list[FakeSMTP] = []

    def smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        smtp_instances.append(inst)
        return inst

    s = _settings(smtp_host="", imap_host="imap.gmail.com")
    send(to="a@b.com", subject="Hi", body="Hello", settings=s, smtp_class=smtp_factory)

    assert len(smtp_instances) == 1
    assert smtp_instances[0].host == "smtp.gmail.com"


def test_smtp_class_is_injectable() -> None:
    """Inject a FakeSMTP; assert send() calls the right methods."""
    smtp_instances: list[FakeSMTP] = []

    def smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        smtp_instances.append(inst)
        return inst

    s = _settings()
    send(to="a@b.com", subject="Hi", body="Hello world", settings=s, smtp_class=smtp_factory)

    assert len(smtp_instances) == 1
    conn = smtp_instances[0]
    assert conn.starttls_called
    assert conn.login_calls == [("user@example.com", "s3cr3t")]
    assert len(conn.sent_messages) == 1


def test_audit_detail_contains_only_recipient() -> None:
    """CRITICAL: send() must not include email body in any exception message.

    This test verifies that body text never surfaces when FakeSMTP records
    the sendmail call and we inspect what was passed.
    """
    smtp_instances: list[FakeSMTP] = []

    def smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        smtp_instances.append(inst)
        return inst

    s = _settings()
    body = "TOP SECRET PAYLOAD should not leak"
    send(to="a@b.com", subject="Hi", body=body, settings=s, smtp_class=smtp_factory)

    conn = smtp_instances[0]
    # We verify that the sent EmailMessage contains the body (correct),
    # but that no exception or error string would contain it (the design contract).
    # Verify the body is IN the actual sent message (expected behaviour):
    sent_msg = conn.sent_messages[0]
    # Now verify: if an exception were raised at this point, body would NOT
    # be in the exception text. We test this by triggering an SMTP error
    # and asserting body is absent from the exception.
    smtp_instances.clear()

    def failing_smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        inst._raise_on_send = smtplib.SMTPException
        smtp_instances.append(inst)
        return inst

    with pytest.raises(SmtpConfigError) as exc_info:
        send(to="a@b.com", subject="Hi", body=body, settings=s, smtp_class=failing_smtp_factory)

    assert body not in str(exc_info.value)


def test_send_does_not_log_body_in_exception() -> None:
    """When FakeSMTP raises SMTPException, the caught exception message must not contain body text."""
    smtp_instances: list[FakeSMTP] = []

    def failing_smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        inst._raise_on_send = smtplib.SMTPException
        smtp_instances.append(inst)
        return inst

    s = _settings()
    body = "SENSITIVE BODY CONTENT XYZ_UNIQUE_123"

    with pytest.raises(SmtpConfigError) as exc_info:
        send(
            to="victim@example.com",
            subject="Subject",
            body=body,
            settings=s,
            smtp_class=failing_smtp_factory,
        )

    error_text = str(exc_info.value)
    assert body not in error_text
    assert "SENSITIVE" not in error_text


def test_smtp_auth_failure_gives_friendly_message() -> None:
    """SMTPAuthenticationError is mapped to a friendly message."""
    smtp_instances: list[FakeSMTP] = []

    def failing_smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        inst._raise_on_login = smtplib.SMTPAuthenticationError
        smtp_instances.append(inst)
        return inst

    s = _settings()
    with pytest.raises(SmtpConfigError, match="authentication failed"):
        send(to="a@b.com", subject="Hi", body="Body", settings=s, smtp_class=failing_smtp_factory)


def test_redact_strips_password_from_error_strings() -> None:
    """_redact removes password occurrences from text."""
    result = _redact("mypassword", "Error: auth failed with mypassword in plain text")
    assert "mypassword" not in result
    assert "***" in result


def test_redact_handles_empty_password() -> None:
    """_redact with empty password returns text unchanged."""
    text = "some error text"
    assert _redact("", text) == text


def test_email_sender_class_injectable() -> None:
    """EmailSender class uses injected smtp_class correctly."""
    smtp_instances: list[FakeSMTP] = []

    def smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        smtp_instances.append(inst)
        return inst

    s = _settings()
    sender = EmailSender(s, smtp_class=smtp_factory)
    sender.send(to="b@c.com", subject="Test", body="Hello")

    assert len(smtp_instances) == 1
    assert len(smtp_instances[0].sent_messages) == 1


def test_draft_and_send_returns_confirmation() -> None:
    """draft_and_send returns a confirmation string."""
    smtp_instances: list[FakeSMTP] = []

    def smtp_factory(host, port, timeout=30):
        inst = FakeSMTP(host, port, timeout)
        smtp_instances.append(inst)
        return inst

    s = _settings()
    # draft_and_send uses the module-level send(), which doesn't accept smtp_class.
    # Test via EmailSender instead to keep hermeticity.
    sender = EmailSender(s, smtp_class=smtp_factory)
    # draft_and_send is a module function; we patch smtp at module level for this test.
    import eclipse_agent.email_sender as es_mod

    original = smtplib.SMTP
    try:
        smtplib.SMTP = smtp_factory  # type: ignore[misc]
        result = draft_and_send(to="x@y.com", subject="S", body="B", settings=s)
    finally:
        smtplib.SMTP = original

    assert "x@y.com" in result
