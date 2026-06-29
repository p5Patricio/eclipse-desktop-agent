"""SMTP email sending module for Eclipse.

Sends plain-text email via STARTTLS SMTP. Passwords are never logged or
surfaced in error messages.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any


class SmtpConfigError(Exception):
    """Raised when SMTP configuration is missing or invalid."""


@dataclass
class SmtpConfig:
    host: str
    username: str
    password: str
    port: int = 587
    use_tls: bool = True
    timeout_seconds: float = 30.0


@dataclass
class SendEmailRequest:
    to: str
    subject: str
    body: str
    from_address: str = ""
    cc: str = ""
    reply_to: str = ""


@dataclass
class SendEmailResult:
    success: bool
    to: str
    subject: str
    message_id: str = ""
    error: str = ""


def _redact(password: str, text: str) -> str:
    """Remove any occurrence of password from text."""
    if not password:
        return text
    return text.replace(password, "***")


def send(
    *,
    to: str,
    subject: str,
    body: str,
    settings: Any = None,
    smtp_class: type | None = None,
) -> None:
    """Send an email using settings from EclipseSettings.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        settings: EclipseSettings instance. Loaded from default path if None.
        smtp_class: Injectable SMTP class (defaults to smtplib.SMTP).

    Raises:
        SmtpConfigError: When SMTP is not properly configured.
    """
    if settings is None:
        from eclipse_agent.settings import load_settings

        settings = load_settings()

    smtp_host = settings.smtp_host
    smtp_user = settings.smtp_user
    smtp_password = settings.smtp_password
    port = settings.smtp_port
    use_tls = getattr(settings, "smtp_use_tls", True)

    if not smtp_host and settings.imap_host:
        imap = settings.imap_host
        if imap.startswith("imap."):
            smtp_host = "smtp." + imap[len("imap."):]
        else:
            raise SmtpConfigError(
                f"Cannot derive SMTP host from imap_host '{imap}'. Set ECLIPSE_SMTP_HOST."
            )

    if not smtp_user:
        smtp_user = settings.imap_user

    if not smtp_password:
        raise SmtpConfigError("SMTP password not configured. Set ECLIPSE_SMTP_PASSWORD.")

    if not smtp_host:
        raise SmtpConfigError(
            "SMTP host not configured. Set ECLIPSE_SMTP_HOST."
        )

    _cls = smtp_class or smtplib.SMTP
    try:
        with _cls(smtp_host, port, timeout=30) as conn:
            if use_tls:
                conn.starttls()
            conn.login(smtp_user, smtp_password)
            msg = EmailMessage()
            msg["From"] = smtp_user
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            conn.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise SmtpConfigError(
            "SMTP authentication failed. Check ECLIPSE_SMTP_USER and ECLIPSE_SMTP_PASSWORD."
        )
    except smtplib.SMTPException as exc:
        safe_msg = _redact(smtp_password, str(exc))
        raise SmtpConfigError(f"SMTP error sending to {to}: {safe_msg}") from exc


class EmailSender:
    """Stateful SMTP email sender bound to EclipseSettings."""

    def __init__(
        self,
        settings: Any = None,
        *,
        smtp_class: type | None = None,
    ) -> None:
        if settings is None:
            from eclipse_agent.settings import load_settings

            settings = load_settings()
        self._settings = settings
        self._smtp_class = smtp_class

    def send(self, *, to: str, subject: str, body: str) -> None:
        """Send a plain-text email.

        Raises:
            SmtpConfigError: If configuration is invalid or SMTP connection fails.
        """
        send(
            to=to,
            subject=subject,
            body=body,
            settings=self._settings,
            smtp_class=self._smtp_class,
        )


def draft_and_send(
    *,
    to: str,
    subject: str,
    body: str,
    settings: Any = None,
) -> str:
    """Send an email and return a confirmation message string.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        settings: EclipseSettings instance. Loaded from default path if None.

    Returns:
        Confirmation string on success.

    Raises:
        SmtpConfigError: If configuration is invalid or sending fails.
    """
    send(to=to, subject=subject, body=body, settings=settings)
    return f"Email sent to {to}."
