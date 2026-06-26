from email.message import EmailMessage as RawEmail

from eclipse_agent import main as main_module
from eclipse_agent.answer import AnswerResult
from eclipse_agent.email_inbox import (
    EmailConfig,
    EmailMessage,
    ImapMailbox,
    InboxSummaryResult,
    draft_reply,
    render_email_messages,
    summarize_inbox,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter


def _raw(sender: str, subject: str, body: str) -> bytes:
    msg = RawEmail()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Mon, 01 Jan 2026 12:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


class FakeIMAP:
    def __init__(self, messages: dict[bytes, bytes]) -> None:
        self.messages = messages
        self.logged_out = False

    def select(self, mailbox):
        return ("OK", [str(len(self.messages)).encode()])

    def search(self, charset, criteria):
        return ("OK", [b" ".join(self.messages.keys())])

    def fetch(self, message_id, parts):
        raw = self.messages[message_id]
        return ("OK", [(message_id + b" (RFC822 {x}", raw), b")"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])


class FakeAnswerer:
    def __init__(self, text: str = "Tenés 2 correos nuevos.") -> None:
        self.text = text
        self.seen = ""

    def answer(self, prompt: str) -> AnswerResult:
        self.seen = prompt
        return AnswerResult(True, prompt, self.text, "ok")


def _mailbox(messages: dict[bytes, bytes]) -> ImapMailbox:
    return ImapMailbox(
        EmailConfig(username="me@example.com", password="app-pass"),
        connection_factory=lambda: FakeIMAP(messages),
    )


# --- fetch / parse -------------------------------------------------------


def test_fetch_recent_parses_and_orders_newest_first():
    messages = {
        b"1": _raw("Ana <ana@x.com>", "Hola", "Primer mensaje de prueba."),
        b"2": _raw("Beto <beto@x.com>", "Reunión", "¿Nos juntamos el martes?"),
    }
    fetched = _mailbox(messages).fetch_recent(limit=5, unseen_only=False)

    assert len(fetched) == 2
    assert fetched[0].subject == "Reunión"  # newest (id 2) first
    assert "Beto" in fetched[0].sender
    assert "martes" in fetched[0].snippet


def test_fetch_recent_respects_limit():
    messages = {str(i).encode(): _raw(f"S{i}", f"Subj{i}", f"Body {i}") for i in range(1, 6)}
    fetched = _mailbox(messages).fetch_recent(limit=2, unseen_only=False)
    assert [m.subject for m in fetched] == ["Subj5", "Subj4"]


def test_is_configured_requires_credentials():
    assert ImapMailbox(EmailConfig(username="", password="")).is_configured() is False
    assert ImapMailbox(EmailConfig(username="u", password="p")).is_configured() is True


# --- summarize -----------------------------------------------------------


def test_summarize_inbox_uses_messages_and_answerer():
    messages = {
        b"1": _raw("Ana", "Factura", "Te paso la factura de marzo."),
        b"2": _raw("Beto", "Reunión", "Movamos la reunión."),
    }
    answerer = FakeAnswerer("Tenés 2 correos: una factura y una reunión.")

    result = summarize_inbox(_mailbox(messages), answerer=answerer)

    assert result.success is True
    assert result.count == 2
    assert "factura" in answerer.seen.casefold()  # message content fed to the LLM
    assert "2 correos" in result.summary


def test_summarize_inbox_not_configured_is_graceful(monkeypatch):
    monkeypatch.delenv("ECLIPSE_IMAP_USER", raising=False)
    monkeypatch.delenv("ECLIPSE_IMAP_PASSWORD", raising=False)
    result = summarize_inbox(ImapMailbox(EmailConfig()))
    assert result.success is False
    assert "ECLIPSE_IMAP_USER" in result.message


def test_summarize_inbox_empty():
    result = summarize_inbox(_mailbox({}))
    assert result.success is True
    assert result.count == 0
    assert "nuevos" in result.summary


def test_summarize_inbox_imap_error_is_graceful():
    def boom():
        raise OSError("connection refused")

    box = ImapMailbox(
        EmailConfig(username="u", password="p"), connection_factory=boom
    )
    result = summarize_inbox(box)
    assert result.success is False
    assert "No pude leer" in result.message


def test_draft_reply_never_sends_and_uses_instruction():
    message = EmailMessage(
        uid="2", sender="Ana", subject="Factura", date="", snippet="Te paso la factura."
    )
    answerer = FakeAnswerer("Hola Ana, gracias por la factura.")

    result = draft_reply(message, "agradecé y pedí el detalle", answerer=answerer)

    assert result.success is True
    assert result.uid == "2"
    assert "gracias" in result.draft.casefold()
    assert "agradecé" in answerer.seen


def test_render_email_messages_empty():
    assert render_email_messages(()) == "No messages."


# --- planner -------------------------------------------------------------


def test_inbox_phrase_routes_to_summarize_inbox():
    plan = create_action_plan("Eclipse, resumime mi bandeja de entrada")

    action = plan.actions[0]
    assert action.kind is ActionKind.SUMMARIZE_INBOX
    assert action.tool_name == "native.summarize_inbox"


# --- native tool ---------------------------------------------------------


def test_native_summarize_inbox_speaks_summary(monkeypatch):
    import eclipse_agent.email_inbox as mail_mod

    monkeypatch.setattr(
        mail_mod,
        "summarize_inbox",
        lambda *a, **k: InboxSummaryResult(True, 3, "Tenés 3 correos sin leer.", "ok"),
    )

    action = PlannedAction(
        id="mail-1",
        kind=ActionKind.SUMMARIZE_INBOX,
        description="Summarize inbox.",
        risk_level=RiskLevel.LOW,
        target="inbox",
        tool_name="native.summarize_inbox",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )

    assert result.success is True
    assert "3 correos" in result.structured_content["user_facts"]["spoken"]


# --- CLI -----------------------------------------------------------------


def test_cli_email_summary_not_configured(monkeypatch, capsys):
    monkeypatch.delenv("ECLIPSE_IMAP_USER", raising=False)
    monkeypatch.delenv("ECLIPSE_IMAP_PASSWORD", raising=False)

    assert main_module.main(["email-summary"]) == 1
    assert "failed" in capsys.readouterr().out
