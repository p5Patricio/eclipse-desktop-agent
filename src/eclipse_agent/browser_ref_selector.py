"""Heuristic selector for agent-browser snapshot refs.

The selector is deliberately deterministic and conservative. It only chooses refs
from the accessibility snapshot, assigns transparent scores, and can abstain when
there is no plausible target. This keeps reply drafting safer than blind clicking
or coordinate-based automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from eclipse_agent.browser_automation import BrowserElement, BrowserSnapshot


class BrowserRefPurpose(StrEnum):
    """High-level ref-selection target."""

    MESSAGE_INPUT = "message_input"
    SEND_BUTTON = "send_button"
    SEARCH_INPUT = "search_input"


@dataclass(frozen=True, kw_only=True)
class BrowserRefCandidate:
    """One scored candidate from a browser snapshot."""

    element: BrowserElement
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class BrowserRefSelection:
    """Selection result for a browser ref."""

    selected: BrowserRefCandidate | None
    candidates: tuple[BrowserRefCandidate, ...]
    purpose: BrowserRefPurpose
    threshold: int
    source_backend: str = "normalized"

    @property
    def success(self) -> bool:
        """Return whether the selector found a plausible ref."""

        return self.selected is not None

    @property
    def selected_ref(self) -> str | None:
        """Return the selected snapshot ref, if any."""

        return self.selected.element.ref if self.selected else None


MESSAGE_INPUT_KEYWORDS = (
    "message",
    "mensaje",
    "write",
    "escribe",
    "reply",
    "respuesta",
    "responder",
    "chat",
    "text",
    "texto",
    "compose",
    "redactar",
)
SEND_BUTTON_KEYWORDS = ("send", "enviar", "mandar")
SEARCH_INPUT_KEYWORDS = ("search", "buscar", "busca")

TEXT_ENTRY_ROLES = {
    "textbox",
    "textarea",
    "combobox",
    "searchbox",
    "generic",
}
BUTTON_ROLES = {"button", "menuitem", "link"}


def select_browser_ref(
    snapshot: BrowserSnapshot,
    *,
    purpose: BrowserRefPurpose = BrowserRefPurpose.MESSAGE_INPUT,
    threshold: int = 50,
) -> BrowserRefSelection:
    """Select the best ref for a target purpose, or abstain."""

    candidates = tuple(
        sorted(
            (
                _score_element(element, purpose)
                for element in snapshot.elements
            ),
            key=lambda candidate: (
                candidate.score,
                _role_priority(candidate.element.role, purpose),
                -_ref_number(candidate.element.ref),
            ),
            reverse=True,
        )
    )
    plausible = tuple(candidate for candidate in candidates if candidate.score >= threshold)
    return BrowserRefSelection(
        selected=plausible[0] if plausible else None,
        candidates=candidates,
        purpose=purpose,
        threshold=threshold,
        source_backend=snapshot.source_backend,
    )


def render_browser_ref_selection(selection: BrowserRefSelection) -> str:
    """Render selection output for CLI/debugging."""

    if selection.selected:
        lines = [
            (
                f"Selected {selection.selected.element.ref} for {selection.purpose.value} "
                f"(score {selection.selected.score})."
            )
        ]
        lines.append(f"reasons: {', '.join(selection.selected.reasons)}")
    else:
        lines = [
            (
                f"No ref selected for {selection.purpose.value}; "
                f"best score below threshold {selection.threshold}."
            )
        ]

    lines.append(f"snapshot_backend: {getattr(selection, 'source_backend', '') or 'normalized'}")
    for candidate in selection.candidates[:5]:
        lines.append(
            f"- {candidate.element.ref} {candidate.element.role} "
            f"{candidate.element.name!r}: {candidate.score}"
        )
    return "\n".join(lines)


def _score_element(
    element: BrowserElement,
    purpose: BrowserRefPurpose,
) -> BrowserRefCandidate:
    role = element.role.casefold().strip()
    name = element.name.casefold().strip()
    reasons: list[str] = []
    score = 0

    if purpose is BrowserRefPurpose.MESSAGE_INPUT:
        score += _score_text_entry_role(role, reasons)
        score += _score_keywords(name, MESSAGE_INPUT_KEYWORDS, reasons)
        score -= _negative_keyword_penalty(name, SEARCH_INPUT_KEYWORDS, "search keyword", reasons)
        score -= _negative_keyword_penalty(name, SEND_BUTTON_KEYWORDS, "send keyword", reasons)
    elif purpose is BrowserRefPurpose.SEARCH_INPUT:
        score += _score_text_entry_role(role, reasons)
        score += _score_keywords(name, SEARCH_INPUT_KEYWORDS, reasons)
    else:
        if role in BUTTON_ROLES:
            score += 45
            reasons.append(f"button-like role {role}")
        score += _score_keywords(name, SEND_BUTTON_KEYWORDS, reasons)
        score -= _negative_keyword_penalty(name, SEARCH_INPUT_KEYWORDS, "search keyword", reasons)

    if not name:
        score -= 5
        reasons.append("empty accessible name")

    return BrowserRefCandidate(
        element=element,
        score=score,
        reasons=tuple(reasons) or ("no positive match",),
    )


def _score_text_entry_role(role: str, reasons: list[str]) -> int:
    if role in {"textbox", "textarea"}:
        reasons.append(f"strong text-entry role {role}")
        return 45
    if role in {"combobox", "searchbox"}:
        reasons.append(f"text-entry role {role}")
        return 30
    if role in TEXT_ENTRY_ROLES:
        reasons.append(f"possible text-entry role {role}")
        return 15
    return 0


def _score_keywords(
    name: str,
    keywords: tuple[str, ...],
    reasons: list[str],
) -> int:
    score = 0
    for keyword in keywords:
        if keyword in name:
            score += 20
            reasons.append(f"keyword {keyword!r}")
    return score


def _negative_keyword_penalty(
    name: str,
    keywords: tuple[str, ...],
    reason: str,
    reasons: list[str],
) -> int:
    penalty = 0
    for keyword in keywords:
        if keyword in name:
            penalty += 20
            reasons.append(f"penalty {reason} {keyword!r}")
    return penalty


def _role_priority(role: str, purpose: BrowserRefPurpose) -> int:
    normalized = role.casefold().strip()
    if purpose is BrowserRefPurpose.SEND_BUTTON:
        return 2 if normalized == "button" else 1 if normalized in BUTTON_ROLES else 0
    if normalized in {"textbox", "textarea"}:
        return 3
    if normalized in {"combobox", "searchbox"}:
        return 2
    if normalized in TEXT_ENTRY_ROLES:
        return 1
    return 0


def _ref_number(ref: str) -> int:
    digits = "".join(character for character in ref if character.isdigit())
    return int(digits or "0")
