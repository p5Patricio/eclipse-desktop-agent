"""Reply-draft workflow for notifications.

Eclipse must never send messages automatically. This module only prepares browser
state or fills a confirmed draft field. Sending remains a separate explicit action.
"""

from __future__ import annotations

from dataclasses import dataclass

from eclipse_agent.browser_automation import (
    BrowserCommandKind,
    BrowserInteractionLoop,
    BrowserInteractionPlan,
    render_browser_interaction_plan,
)
from eclipse_agent.notifications import (
    NotificationEvent,
    NotificationSourceKind,
    NotificationStore,
)


WEB_REPLY_TARGETS = {
    "Instagram": "https://www.instagram.com/",
    "Messenger": "https://www.messenger.com/",
    "WhatsApp": "https://web.whatsapp.com/",
    "Gmail": "https://mail.google.com/",
}


@dataclass(frozen=True, kw_only=True)
class NotificationReplyDraftResult:
    """Result of preparing a notification reply draft."""

    success: bool
    event: NotificationEvent | None
    message: str
    browser_plan: BrowserInteractionPlan | None = None
    reply_text: str = ""


class NotificationReplyWorkflow:
    """Prepare a safe reply workflow for a stored notification."""

    def __init__(
        self,
        *,
        store: NotificationStore | None = None,
        browser_loop: BrowserInteractionLoop | None = None,
    ) -> None:
        self.store = store or NotificationStore()
        self.browser_loop = browser_loop or BrowserInteractionLoop()

    def prepare_reply_draft(
        self,
        *,
        event_id: str,
        reply_text: str,
        selector: str | None = None,
        confirmed: bool = False,
        dry_run: bool = True,
    ) -> NotificationReplyDraftResult:
        """Open the source web app or fill a confirmed draft field.

        Without a selector, Eclipse opens/snapshots the web app so a later selector
        layer can choose the message input. With a selector, Eclipse may fill/type
        the draft only when `confirmed=True`.
        """

        event = self.store.get_event(event_id)
        if event is None:
            return NotificationReplyDraftResult(
                success=False,
                event=None,
                message=f"Notification not found: {event_id}.",
                reply_text=reply_text,
            )

        url = reply_url_for_event(event)
        if url is None:
            return NotificationReplyDraftResult(
                success=False,
                event=event,
                message=(
                    "Reply workflow is only wired for supported web sources "
                    "right now; native app replies need an app-specific adapter."
                ),
                reply_text=reply_text,
            )

        if selector:
            plan = self.browser_loop.confirmed_ref_action(
                kind=BrowserCommandKind.FILL,
                selector=selector,
                text=reply_text,
                confirmed=confirmed,
                dry_run=dry_run,
            )
            success = plan.status.value in {"prepared", "executed"}
            return NotificationReplyDraftResult(
                success=success,
                event=event,
                browser_plan=plan,
                message=(
                    "Prepared confirmed browser fill for reply draft."
                    if success
                    else "Browser draft fill is blocked until --confirmed is provided."
                ),
                reply_text=reply_text,
            )

        plan = self.browser_loop.open_and_snapshot(url, dry_run=dry_run)
        return NotificationReplyDraftResult(
            success=plan.status.value in {"prepared", "executed"},
            event=event,
            browser_plan=plan,
            message=(
                "Opened/snapshotted the source web app. Choose the message input "
                "ref, then run again with --selector and --confirmed to fill a draft."
            ),
            reply_text=reply_text,
        )


def reply_url_for_event(event: NotificationEvent) -> str | None:
    """Return the safest web URL to prepare a reply for this notification."""

    if event.source_kind is not NotificationSourceKind.WEB:
        return None
    return WEB_REPLY_TARGETS.get(event.display_source)


def render_notification_reply_draft_result(result: NotificationReplyDraftResult) -> str:
    """Render reply-draft workflow output."""

    status = "prepared" if result.success else "blocked"
    lines = [f"Notification reply draft [{status}]: {result.message}"]
    if result.event:
        lines.append(f"event: {result.event.id} from {result.event.display_source}")
    if result.reply_text:
        lines.append(f"draft: {result.reply_text}")
    if result.browser_plan:
        lines.append(render_browser_interaction_plan(result.browser_plan))
    lines.append("Safety: Eclipse prepared a draft only; it did not send the message.")
    return "\n".join(lines)
