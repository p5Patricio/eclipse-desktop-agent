"""Media playback for Eclipse: open a search in the user's real browser.

Rather than driving a media app's hostile SPA through browser automation
(unreliable: bot detection, headless walls, frequently-changing DOM), Eclipse
opens the app's search URL in the user's default browser — where they are
already logged in — and lets them press play. Simple and reliable.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from eclipse_agent.pal.factory import PlatformFactory

MEDIA_SEARCH_URLS = {
    "YouTube Music": "https://music.youtube.com/search?q={query}",
    "YouTube": "https://www.youtube.com/results?search_query={query}",
    "Spotify": "https://open.spotify.com/search/{query}",
}


@dataclass(frozen=True)
class MediaPlaybackResult:
    """Result of opening a media search."""

    success: bool
    app_name: str
    query: str
    url: str
    message: str
    opened: bool = False
    requires_confirmation: bool = False


def build_media_search_url(app_name: str, query: str) -> str | None:
    """Build the app's search URL for a query, or None if unsupported."""

    template = MEDIA_SEARCH_URLS.get(app_name) or MEDIA_SEARCH_URLS.get(app_name.title())
    if not template:
        return None
    return template.format(query=quote_plus(query))


def open_media_search(
    app_name: str,
    query: str,
    *,
    launcher: object | None = None,
    dry_run: bool = True,
    requested_interaction: str = "",
    confirmed: bool = False,
) -> MediaPlaybackResult:
    """Open the app's search for ``query`` in the default browser."""

    cleaned = " ".join(query.split())
    if not cleaned:
        return MediaPlaybackResult(False, app_name, query, "", "Tell me what to play.")
    interaction = requested_interaction.casefold().strip()
    if interaction in {"play", "autoplay", "click_play", "submit", "send"} and not confirmed:
        return MediaPlaybackResult(
            False,
            app_name,
            cleaned,
            "",
            "Opening media search is native, but indirect play/submit actions require confirmation.",
            requires_confirmation=True,
        )
    url = build_media_search_url(app_name, cleaned)
    if url is None:
        return MediaPlaybackResult(
            False, app_name, cleaned, "", f"{app_name} is not a supported media app yet."
        )
    launch = launcher or PlatformFactory.get_app_launcher()
    try:
        result = launch.launch(url, dry_run=dry_run)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return MediaPlaybackResult(False, app_name, cleaned, url, str(exc))
    if not getattr(result, "success", True):
        return MediaPlaybackResult(
            False, app_name, cleaned, url, getattr(result, "message", "Could not open the browser.")
        )
    spoken = f"Abrí la búsqueda de {cleaned} en {app_name}. Dale play cuando quieras."
    return MediaPlaybackResult(True, app_name, cleaned, url, spoken, opened=not dry_run)


def render_media_playback_result(result: MediaPlaybackResult) -> str:
    """Render a media playback result for CLI output."""

    status = "ok" if result.success else "failed"
    lines = [f"Media playback [{status}]: {result.message}"]
    if result.requires_confirmation:
        lines.append("confirmation: required")
    if result.url:
        lines.append(f"url: {result.url}")
    return "\n".join(lines)
