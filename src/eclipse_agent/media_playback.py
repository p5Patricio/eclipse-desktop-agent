"""Search-and-play workflow for web media apps (YouTube Music, etc.).

This is the orchestration layer the browser adapter was scaffolded for: it opens
a media web app, snapshots it, picks the search box, types the query, snapshots
the results, picks a play control, and clicks it. Each active step is gated and
only runs when explicitly confirmed and executed; real execution needs
``agent-browser`` installed and a logged-in session.

The flow reads accessibility snapshots from ``agent-browser`` output, so the
whole orchestration is deterministic and testable with a fake adapter.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from eclipse_agent.browser_automation import (
    AgentBrowserAdapter,
    BrowserAutomationProfile,
    BrowserAutomationResult,
    BrowserSnapshot,
    parse_agent_browser_snapshot_json,
)
from eclipse_agent.browser_ref_selector import (
    BrowserRefPurpose,
    select_browser_ref,
)

MEDIA_WEB_TARGETS = {
    "YouTube Music": "https://music.youtube.com/",
    "YouTube": "https://www.youtube.com/",
    "Spotify": "https://open.spotify.com/",
}


def media_browser_profile() -> BrowserAutomationProfile:
    """Browser profile for media playback.

    Media sites (YouTube Music) serve a "get Chrome" wall to headless browsers,
    so run headed. Set ECLIPSE_CHROME_PROFILE to reuse a logged-in Chrome profile.
    """

    return BrowserAutomationProfile(
        headed=True,
        chrome_profile=os.environ.get("ECLIPSE_CHROME_PROFILE", ""),
    )


@dataclass(frozen=True, kw_only=True)
class MediaPlaybackResult:
    """Result of preparing or running a search-and-play flow."""

    success: bool
    app_name: str
    query: str
    message: str
    executed: bool = False
    blocked: bool = False
    steps: tuple[BrowserAutomationResult, ...] = field(default_factory=tuple)


class MediaPlaybackWorkflow:
    """Open a media web app, search for a track, and play the first result."""

    def __init__(self, adapter: AgentBrowserAdapter | None = None) -> None:
        self.adapter = adapter or AgentBrowserAdapter(media_browser_profile())

    def play(
        self,
        app_name: str,
        query: str,
        *,
        confirmed: bool = True,
        dry_run: bool = True,
    ) -> MediaPlaybackResult:
        """Run the full open -> search -> play flow with safety gates."""

        url = _resolve_media_url(app_name)
        if url is None:
            return MediaPlaybackResult(
                success=False,
                app_name=app_name,
                query=query,
                message=f"{app_name} is not a supported media web app yet.",
            )
        cleaned_query = " ".join(query.split())
        if not cleaned_query:
            return MediaPlaybackResult(
                success=False,
                app_name=app_name,
                query=query,
                message="Tell me what to play.",
            )

        steps: list[BrowserAutomationResult] = []
        opened = self.adapter.snapshot(url=url, dry_run=dry_run)
        steps.append(opened)
        if not opened.success:
            return _failure(app_name, cleaned_query, steps, opened.message)

        search_page = _parse_snapshot(opened.stdout)
        if search_page is None:
            return MediaPlaybackResult(
                success=True,
                app_name=app_name,
                query=cleaned_query,
                executed=False,
                message=(
                    f"Prepared to open {app_name} and search '{cleaned_query}'. "
                    "Run with --execute and agent-browser installed to play."
                ),
                steps=tuple(steps),
            )

        search_ref = select_browser_ref(
            search_page, purpose=BrowserRefPurpose.SEARCH_INPUT
        ).selected_ref
        if not search_ref:
            return _failure(
                app_name, cleaned_query, steps, "Could not find the search box."
            )
        if not confirmed:
            return MediaPlaybackResult(
                success=False,
                app_name=app_name,
                query=cleaned_query,
                blocked=True,
                message="Playing media needs confirmation before typing and clicking.",
                steps=tuple(steps),
            )

        steps.append(self.adapter.fill(search_ref, cleaned_query, dry_run=dry_run))
        steps.append(self.adapter.press("Enter", dry_run=dry_run))
        results = self.adapter.snapshot(dry_run=dry_run)
        steps.append(results)
        if not results.success:
            return _failure(app_name, cleaned_query, steps, results.message)

        results_page = _parse_snapshot(results.stdout)
        if results_page is None:
            return _failure(
                app_name, cleaned_query, steps, "Could not read the search results."
            )

        play_ref = select_browser_ref(
            results_page, purpose=BrowserRefPurpose.PLAY_CONTROL
        ).selected_ref
        if not play_ref:
            return _failure(
                app_name, cleaned_query, steps, "Could not find a play control."
            )

        clicked = self.adapter.click(play_ref, dry_run=dry_run)
        steps.append(clicked)
        if not clicked.success:
            return _failure(app_name, cleaned_query, steps, clicked.message)
        return MediaPlaybackResult(
            success=True,
            app_name=app_name,
            query=cleaned_query,
            executed=clicked.executed,
            message=f"Reproduciendo {cleaned_query} en {app_name}.",
            steps=tuple(steps),
        )


def render_media_playback_result(result: MediaPlaybackResult) -> str:
    """Render a media playback result for CLI output."""

    status = "ok" if result.success else ("blocked" if result.blocked else "failed")
    lines = [f"Media playback [{status}]: {result.message}"]
    for step in result.steps:
        marker = "executed" if step.executed else "prepared"
        if not step.success:
            marker = "failed"
        lines.append(f"- {step.kind.value} [{marker}]: {step.message}")
    return "\n".join(lines)


def _resolve_media_url(app_name: str) -> str | None:
    if app_name in MEDIA_WEB_TARGETS:
        return MEDIA_WEB_TARGETS[app_name]
    return MEDIA_WEB_TARGETS.get(app_name.title())


def _parse_snapshot(raw_output: str) -> BrowserSnapshot | None:
    if not raw_output.strip():
        return None
    try:
        return parse_agent_browser_snapshot_json(raw_output)
    except (ValueError, json.JSONDecodeError):
        return None


def _failure(
    app_name: str,
    query: str,
    steps: list[BrowserAutomationResult],
    message: str,
) -> MediaPlaybackResult:
    return MediaPlaybackResult(
        success=False,
        app_name=app_name,
        query=query,
        message=message,
        steps=tuple(steps),
    )
