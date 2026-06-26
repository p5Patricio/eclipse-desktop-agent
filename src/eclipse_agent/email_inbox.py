"""Read-only inbox access for Eclipse over IMAP.

Eclipse reads and summarizes recent mail and drafts replies, but NEVER sends:
there is no SMTP path here. Reading uses stdlib ``imaplib``/``email``; the IMAP
connection is injectable so the whole flow is testable without a real server.

Setup (Gmail): enable IMAP, turn on 2-step verification, and create an app
password. Configure ECLIPSE_IMAP_USER and ECLIPSE_IMAP_PASSWORD.
"""

from __future__ import annotations

import email
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from email.header import decode_header, make_header

from eclipse_agent.answer import QuestionAnswerer
from eclipse_agent.planner import build_planner_config_from_env

DEFAULT_IMAP_HOST = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993
SNIPPET_LIMIT = 280

INBOX_SUMMARY_PROMPT = (
    "You are Eclipse summarizing the user's inbox out loud. Given a list of recent "
    "emails (sender, subject, snippet), give a brief spoken summary in the same language "
    "as the emails: how many there are, who they are from, and what they are about. One "
    "short paragraph, no markdown, no lists."
)
REPLY_DRAFT_PROMPT = (
    "You are Eclipse drafting a reply to an email. Write a polite, concise reply draft in "
    "the same language as the original message. Output only the draft body, no markdown. "
    "Eclipse never sends mail; this is a draft for the user to review and send themselves."
)


@dataclass(frozen=True)
class EmailConfig:
    """IMAP connection settings."""

    host: str = DEFAULT_IMAP_HOST
    port: int = DEFAULT_IMAP_PORT
    username: str = ""
    password: str = ""


def build_email_config_from_env() -> EmailConfig:
    """Resolve IMAP settings from the environment."""

    return EmailConfig(
        host=os.environ.get("ECLIPSE_IMAP_HOST", DEFAULT_IMAP_HOST),
        port=int(os.environ.get("ECLIPSE_IMAP_PORT", str(DEFAULT_IMAP_PORT))),
        username=os.environ.get("ECLIPSE_IMAP_USER", ""),
        password=os.environ.get("ECLIPSE_IMAP_PASSWORD", ""),
    )


@dataclass(frozen=True)
class EmailMessage:
    """A parsed inbox message (headers + a body snippet)."""

    uid: str
    sender: str
    subject: str
    date: str
    snippet: str


@dataclass(frozen=True)
class InboxSummaryResult:
    """Result of summarizing the inbox."""

    success: bool
    count: int
    summary: str
    message: str


@dataclass(frozen=True)
class ReplyDraftResult:
    """Result of drafting a reply (never sent)."""

    success: bool
    uid: str
    draft: str
    message: str


class ImapMailbox:
    """Read-only IMAP mailbox access with an injectable connection."""

    def __init__(
        self,
        config: EmailConfig | None = None,
        *,
        connection_factory: Callable[[], object] | None = None,
    ) -> None:
        self.config = config or build_email_config_from_env()
        self._connection_factory = connection_factory

    def is_configured(self) -> bool:
        return bool(self.config.username and self.config.password)

    def _connect(self) -> object:
        if self._connection_factory is not None:
            return self._connection_factory()
        import imaplib

        connection = imaplib.IMAP4_SSL(self.config.host, self.config.port)
        connection.login(self.config.username, self.config.password)
        return connection

    def fetch_recent(self, *, limit: int = 5, unseen_only: bool = True) -> tuple[EmailMessage, ...]:
        """Fetch the most recent messages from the inbox, newest first."""

        connection = self._connect()
        try:
            connection.select("INBOX")
            _, data = connection.search(None, "UNSEEN" if unseen_only else "ALL")
            ids = data[0].split() if data and data[0] else []
            recent = ids[-limit:]
            messages: list[EmailMessage] = []
            for message_id in reversed(recent):
                _, payload = connection.fetch(message_id, "(RFC822)")
                raw = _raw_from_fetch(payload)
                if raw is not None:
                    messages.append(_parse_message(message_id, raw))
            return tuple(messages)
        finally:
            _safe_logout(connection)


def summarize_inbox(
    mailbox: ImapMailbox | None = None,
    *,
    limit: int = 5,
    unseen_only: bool = True,
    answerer: QuestionAnswerer | None = None,
) -> InboxSummaryResult:
    """Fetch recent mail and produce a brief spoken summary."""

    box = mailbox or ImapMailbox()
    if not box.is_configured():
        return InboxSummaryResult(
            False, 0, "", "Configurá ECLIPSE_IMAP_USER y ECLIPSE_IMAP_PASSWORD primero."
        )
    try:
        messages = box.fetch_recent(limit=limit, unseen_only=unseen_only)
    except Exception as exc:  # noqa: BLE001
        return InboxSummaryResult(False, 0, "", f"No pude leer tu bandeja: {exc}")
    if not messages:
        return InboxSummaryResult(True, 0, "No tenés correos nuevos.", "No tenés correos nuevos.")

    listing = "\n".join(
        f"De {m.sender}, asunto '{m.subject}': {m.snippet}" for m in messages
    )
    resolver = answerer or QuestionAnswerer(
        build_planner_config_from_env(endpoint_url=None, model=None),
        system_prompt=INBOX_SUMMARY_PROMPT,
    )
    answer = resolver.answer(f"Resumí estos correos:\n{listing}")
    return InboxSummaryResult(answer.success, len(messages), answer.answer, answer.message)


def draft_reply(
    message: EmailMessage,
    instruction: str,
    *,
    answerer: QuestionAnswerer | None = None,
) -> ReplyDraftResult:
    """Draft (never send) a reply to a message, guided by an instruction."""

    resolver = answerer or QuestionAnswerer(
        build_planner_config_from_env(endpoint_url=None, model=None),
        system_prompt=REPLY_DRAFT_PROMPT,
    )
    prompt = (
        f"Original email from {message.sender}, subject '{message.subject}':\n"
        f"{message.snippet}\n\nWrite a reply. Guidance: {instruction or 'reply appropriately'}."
    )
    answer = resolver.answer(prompt)
    return ReplyDraftResult(answer.success, message.uid, answer.answer, answer.message)


def render_email_messages(messages: Iterable[EmailMessage]) -> str:
    """Render inbox messages for CLI display."""

    ordered = tuple(messages)
    if not ordered:
        return "No messages."
    lines = ["Inbox:"]
    for message in ordered:
        lines.append(f"- [{message.uid}] {message.sender} — {message.subject}")
    return "\n".join(lines)


def render_inbox_summary(result: InboxSummaryResult) -> str:
    if not result.success:
        return f"Inbox summary [failed]: {result.message}"
    return f"Inbox summary ({result.count} messages): {result.summary}"


def render_reply_draft(result: ReplyDraftResult) -> str:
    if not result.success:
        return f"Reply draft [failed]: {result.message}"
    return f"Reply draft for [{result.uid}] (not sent):\n{result.draft}"


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return " ".join(str(make_header(decode_header(value))).split())
    except Exception:  # noqa: BLE001
        return value


def _parse_message(uid: bytes | str, raw: bytes) -> EmailMessage:
    parsed = email.message_from_bytes(raw)
    return EmailMessage(
        uid=uid.decode() if isinstance(uid, bytes) else str(uid),
        sender=_decode_header(parsed.get("From")),
        subject=_decode_header(parsed.get("Subject")),
        date=_decode_header(parsed.get("Date")),
        snippet=_extract_body(parsed)[:SNIPPET_LIMIT],
    )


def _extract_body(message: email.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if part.get_content_type() == "text/plain" and "attachment" not in disposition:
                text = _decode_payload(part)
                if text:
                    return text
        return ""
    return _decode_payload(message)


def _decode_payload(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return " ".join(payload.decode(charset, errors="replace").split())


def _raw_from_fetch(payload: object) -> bytes | None:
    if not payload:
        return None
    for item in payload:  # type: ignore[union-attr]
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes | bytearray):
            return bytes(item[1])
    return None


def _safe_logout(connection: object) -> None:
    try:
        connection.logout()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
