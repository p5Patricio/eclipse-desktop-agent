"""Telegram transport adapter for Eclipse remote control."""

from __future__ import annotations

import importlib
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


AFFIRMATIVE_REPLIES = frozenset({"yes", "si", "dale", "ok", "confirmar", "claro"})
NEGATIVE_REPLIES = frozenset({"no", "cancel", "cancelar"})


@dataclass(frozen=True, kw_only=True)
class TelegramBotConfig:
    """Configuration for the Telegram polling bot."""

    token: str
    allowed_chat_ids: frozenset[int]
    confirmation_timeout_seconds: float = 60.0


def parse_allowed_chat_ids(raw: str) -> frozenset[int]:
    """Parse comma/newline separated Telegram chat IDs."""

    ids: set[int] = set()
    for token in raw.replace("\n", ",").split(","):
        value = token.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram chat id: {value}") from exc
    return frozenset(ids)


def _mask_token(token: str) -> str:
    """Return a diagnostic-safe token representation."""

    if not token:
        return "***"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...***...{token[-4:]}"


def _normalize_reply(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _is_kill_switch_active(kill_switch: Any) -> bool:
    if kill_switch is None:
        return False
    checker = getattr(kill_switch, "is_engaged", None) or getattr(kill_switch, "is_active", None)
    if checker is None:
        return False
    return bool(checker())


def _reply_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("reply") or result.get("message") or "")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        spoken = structured.get("spoken")
        if spoken:
            return str(spoken)
    return str(getattr(result, "message", result))


def _requires_confirmation(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("requires_confirmation"))
    if bool(getattr(result, "requires_confirmation", False)):
        return True
    for route in getattr(result, "route_results", ()) or ():
        if bool(getattr(route, "requires_confirmation", False)):
            return True
    return False


class TelegramMessageHandler:
    """Small, testable message-to-runtime adapter."""

    def __init__(
        self,
        config: TelegramBotConfig,
        runtime: Any,
        *,
        kill_switch: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.kill_switch = kill_switch
        self.clock = clock
        self._pending: dict[int, tuple[str, float]] = {}

    def handle_text(self, chat_id: int, text: str) -> str | None:
        if chat_id not in self.config.allowed_chat_ids:
            return None
        if _is_kill_switch_active(self.kill_switch):
            return "Kill switch is active. Eclipse is not acting."

        now = self.clock()
        pending = self._pending.get(chat_id)
        if pending is not None:
            pending_text, expires_at = pending
            normalized_reply = _normalize_reply(text)
            if now <= expires_at and normalized_reply in AFFIRMATIVE_REPLIES:
                self._pending.pop(chat_id, None)
                return _reply_text(
                    self.runtime.handle_command(
                        pending_text,
                        speak=False,
                        route_execute=True,
                        confirmed=True,
                    )
                )
            if now <= expires_at and normalized_reply in NEGATIVE_REPLIES:
                self._pending.pop(chat_id, None)
                return "Command cancelled."
            if now <= expires_at:
                return "Reply YES to confirm or NO to cancel."
            if now > expires_at:
                self._pending.pop(chat_id, None)

        result = self.runtime.handle_command(text, speak=False, route_execute=True)
        if _requires_confirmation(result):
            self._pending[chat_id] = (
                text,
                now + self.config.confirmation_timeout_seconds,
            )
        return _reply_text(result)


class TelegramBot:
    """Thin wrapper around python-telegram-bot polling."""

    def __init__(self, config: TelegramBotConfig, runtime: Any, *, kill_switch: Any = None) -> None:
        self.config = config
        self.handler = TelegramMessageHandler(config, runtime, kill_switch=kill_switch)

    async def _on_message(  # pragma: no cover - library glue
        self,
        update: Any,
        _context: Any,
    ) -> None:
        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        if message is None or chat is None:
            return
        text = getattr(message, "text", "") or ""
        reply = self.handler.handle_text(int(chat.id), text)
        if reply:
            await message.reply_text(reply)

    def run_polling(self) -> None:  # pragma: no cover - library glue
        ext = _load_telegram_ext()
        application = ext.Application.builder().token(self.config.token).build()
        application.add_handler(
            ext.MessageHandler(
                ext.filters.TEXT & ~ext.filters.COMMAND,
                self._on_message,
            )
        )
        application.run_polling()


def _validate_config(config: TelegramBotConfig) -> None:
    if not config.token.strip():
        raise ValueError("Telegram bot token is required.")
    if not config.allowed_chat_ids:
        raise ValueError("At least one allowed Telegram chat id is required.")


def _load_telegram_ext() -> Any:
    try:
        return importlib.import_module("telegram.ext")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("telegram"):
            raise RuntimeError("Install Eclipse with the telegram extra to run the bot.") from exc
        raise


def render_telegram_bot_start(config: TelegramBotConfig) -> str:
    return (
        "Telegram bot ready. "
        f"Allowed chats: {len(config.allowed_chat_ids)}. Token: {_mask_token(config.token)}."
    )


def run_telegram_bot(config: TelegramBotConfig, runtime: Any, *, kill_switch: Any = None) -> None:
    """Validate config and run Telegram polling in the foreground."""

    _validate_config(config)
    TelegramBot(config, runtime, kill_switch=kill_switch).run_polling()


def start_telegram_bot_thread(
    config: TelegramBotConfig,
    runtime: Any,
    *,
    kill_switch: Any = None,
) -> threading.Thread:
    """Start Telegram polling in a daemon thread."""

    _validate_config(config)
    _load_telegram_ext()
    thread = threading.Thread(
        target=run_telegram_bot,
        args=(config, runtime),
        kwargs={"kill_switch": kill_switch},
        daemon=True,
    )
    thread.start()
    return thread
