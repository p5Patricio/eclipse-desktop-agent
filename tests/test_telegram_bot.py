import importlib
import sys

import pytest


class FakeRuntime:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def handle_command(self, text, **kwargs):
        self.calls.append((text, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return "ok"


class FakeKillSwitch:
    def __init__(self, active=False):
        self.active = active

    def is_active(self):
        return self.active


def test_parse_allowed_chat_ids_ignores_blanks_and_requires_int_tokens():
    from eclipse_agent.telegram_bot import parse_allowed_chat_ids

    assert parse_allowed_chat_ids("123, ,456\n789") == frozenset({123, 456, 789})

    with pytest.raises(ValueError, match="Invalid Telegram chat id"):
        parse_allowed_chat_ids("123,abc")


def test_empty_token_and_allowlist_validate_before_telegram_import(monkeypatch):
    from eclipse_agent.telegram_bot import TelegramBotConfig, run_telegram_bot

    blocked_imports = []
    original_import = importlib.import_module

    def guarded_import(name, *args, **kwargs):
        if name.startswith("telegram"):
            blocked_imports.append(name)
            raise AssertionError("telegram must not be imported before validation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", guarded_import)

    with pytest.raises(ValueError, match="Telegram bot token is required"):
        run_telegram_bot(
            TelegramBotConfig(token="", allowed_chat_ids=frozenset({1})),
            FakeRuntime(),
        )

    with pytest.raises(ValueError, match="At least one allowed Telegram chat id"):
        run_telegram_bot(
            TelegramBotConfig(token="token", allowed_chat_ids=frozenset()),
            FakeRuntime(),
        )

    assert blocked_imports == []
    assert "telegram" not in sys.modules


def test_mask_token_never_returns_raw_full_token():
    from eclipse_agent.telegram_bot import _mask_token

    raw = "123456:ABCDEF-secret-token"

    assert _mask_token(raw) != raw
    assert raw not in _mask_token(raw)
    assert _mask_token("abc") != "abc"


def test_unauthorized_chat_is_ignored_without_runtime_call_or_reply():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    runtime = FakeRuntime()
    handler = TelegramMessageHandler(
        TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})), runtime
    )

    assert handler.handle_text(2, "turn on lights") is None
    assert runtime.calls == []


def test_kill_switch_replies_without_runtime_call():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    runtime = FakeRuntime()
    handler = TelegramMessageHandler(
        TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})),
        runtime,
        kill_switch=FakeKillSwitch(active=True),
    )

    assert (
        handler.handle_text(1, "turn on lights")
        == "Kill switch is active. Eclipse is not acting."
    )
    assert runtime.calls == []


def test_pending_confirmation_stores_command_and_affirmative_confirms():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    runtime = FakeRuntime(
        responses=[
            {"reply": "Confirm shutdown?", "requires_confirmation": True},
            "Executed",
        ]
    )
    handler = TelegramMessageHandler(
        TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})), runtime
    )

    assert handler.handle_text(1, "shutdown") == "Confirm shutdown?"
    assert runtime.calls == [("shutdown", {"speak": False, "route_execute": True})]

    assert handler.handle_text(1, "sí") == "Executed"
    assert runtime.calls[-1] == (
        "shutdown",
        {"speak": False, "route_execute": True, "confirmed": True},
    )


def test_pending_confirmation_times_out_and_drops_saved_command():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    now = 100.0
    runtime = FakeRuntime(
        responses=[
            {"reply": "Confirm shutdown?", "requires_confirmation": True},
            "new command handled",
        ]
    )
    handler = TelegramMessageHandler(
        TelegramBotConfig(
            token="token", allowed_chat_ids=frozenset({1}), confirmation_timeout_seconds=5.0
        ),
        runtime,
        clock=lambda: now,
    )

    assert handler.handle_text(1, "shutdown") == "Confirm shutdown?"
    now = 106.0

    assert handler.handle_text(1, "yes") == "new command handled"
    assert runtime.calls[-1] == ("yes", {"speak": False, "route_execute": True})


def test_pending_confirmation_negative_reply_cancels_saved_command():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    runtime = FakeRuntime(
        responses=[
            {"reply": "Confirm shutdown?", "requires_confirmation": True},
        ]
    )
    handler = TelegramMessageHandler(
        TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})), runtime
    )

    assert handler.handle_text(1, "shutdown") == "Confirm shutdown?"
    assert handler.handle_text(1, "no") == "Command cancelled."
    assert runtime.calls == [("shutdown", {"speak": False, "route_execute": True})]


def test_pending_confirmation_ambiguous_reply_does_not_run_new_command():
    from eclipse_agent.telegram_bot import TelegramBotConfig, TelegramMessageHandler

    runtime = FakeRuntime(
        responses=[
            {"reply": "Confirm shutdown?", "requires_confirmation": True},
        ]
    )
    handler = TelegramMessageHandler(
        TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})), runtime
    )

    assert handler.handle_text(1, "shutdown") == "Confirm shutdown?"
    assert handler.handle_text(1, "what time is it") == "Reply YES to confirm or NO to cancel."
    assert runtime.calls == [("shutdown", {"speak": False, "route_execute": True})]


def test_start_thread_reports_missing_telegram_after_validation(monkeypatch):
    from eclipse_agent.telegram_bot import TelegramBotConfig, start_telegram_bot_thread

    original_import = importlib.import_module

    def missing_telegram(name, *args, **kwargs):
        if name.startswith("telegram"):
            raise ModuleNotFoundError("No module named 'telegram'", name="telegram")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing_telegram)

    with pytest.raises(RuntimeError, match="telegram extra"):
        start_telegram_bot_thread(
            TelegramBotConfig(token="token", allowed_chat_ids=frozenset({1})),
            FakeRuntime(),
        )
