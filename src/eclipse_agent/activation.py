"""Activation policy for Eclipse's always-on runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActivationMode(StrEnum):
    """How Eclipse waits for the user while the daemon is running."""

    PUSH_TO_TALK = "push_to_talk"
    WAKE_WORD = "wake_word"
    CONTINUOUS_STT = "continuous_stt"


@dataclass(frozen=True)
class ActivationPolicy:
    """Product-level activation decision.

    ``always_on_daemon`` means Eclipse keeps a small local process alive for wake-word,
    notifications, focus mode, and safe tool routing. It does *not* mean full speech
    transcription or cloud calls are active all the time.
    """

    mode: ActivationMode = ActivationMode.WAKE_WORD
    always_on_daemon: bool = True
    local_only_until_invoked: bool = True
    requires_explicit_wake_phrase: bool = True
    wake_phrase: str = "Eclipse"

    @property
    def is_alexa_style(self) -> bool:
        """Return whether the policy behaves like an Alexa/Jarvis hotword flow."""

        return self.always_on_daemon and self.mode is ActivationMode.WAKE_WORD

    @property
    def records_continuously(self) -> bool:
        """Return whether Eclipse should continuously transcribe microphone audio."""

        return self.mode is ActivationMode.CONTINUOUS_STT


def build_activation_policy(
    mode: ActivationMode | str = ActivationMode.WAKE_WORD,
) -> ActivationPolicy:
    """Build the default activation policy for a mode."""

    mode = ActivationMode(mode)
    if mode is ActivationMode.PUSH_TO_TALK:
        return ActivationPolicy(
            mode=mode,
            always_on_daemon=True,
            local_only_until_invoked=True,
            requires_explicit_wake_phrase=False,
        )
    if mode is ActivationMode.CONTINUOUS_STT:
        return ActivationPolicy(
            mode=mode,
            always_on_daemon=True,
            local_only_until_invoked=True,
            requires_explicit_wake_phrase=False,
        )
    return ActivationPolicy(mode=mode)
