# Apply Progress: Eclipse Chrome DevTools Browser Control

## Change

eclipse-chrome-devtools-browser-control

## Mode

Standard. No `openspec/config.yaml` was present, so strict TDD was not enabled.

## Current Work Unit

PR 3 routing/integrations/fallbacks completed on top of PR 2 adapter/service policy.

## Cumulative Completed Tasks

- [x] 1.1 Created `src/eclipse_agent/browser_control.py` with browser backend/session enums, request/result dataclasses, consent/confirmation/fallback policy shells, and redacted audit-detail helpers.
- [x] 1.2 Added browser-control settings fields in `src/eclipse_agent/settings.py` with native/simple default policy, disabled live access consent, and enabled safe fallbacks.
- [x] 1.3 Extended `src/eclipse_agent/settings_app.py` and `src/eclipse_agent/gui/settings.html` with browser backend/session settings, consent/fallback toggles, warning copy, and non-attaching diagnostics.
- [x] 1.4 Extended `tests/test_settings.py` and `tests/test_settings_gui.py` for persistence, diagnostics shape, default-off live access, and audit redaction.
- [x] 2.1 Created `src/eclipse_agent/chrome_devtools_mcp.py` with Chrome DevTools MCP session config, existing MCP client discovery, non-attaching health diagnostics, and logical-to-tool-name resolution.
- [x] 2.2 Implemented `BrowserControlService` policy in `src/eclipse_agent/browser_control.py` for least-powerful backend classification, consent fail-closed behavior, confirmation gates, safe fallback decisions, and redacted audit records.
- [x] 2.3 Added `tests/test_browser_control.py` for native simple selection, rich DevTools selection, missing/revoked consent fail-closed behavior, confirmation-required actions, fallback selection, and redacted audit details.
- [x] 2.4 Added `tests/test_chrome_devtools_mcp.py` with fake MCP clients covering configured/discovered/missing tools and managed/browser-url/ws-endpoint/auto-connect modes.
- [x] 3.1 Modified `src/eclipse_agent/tool_router.py` so rich browser actions route through `BrowserControlService` while simple open/search flows remain native.
- [x] 3.2 Updated `src/eclipse_agent/browser_automation.py`, `src/eclipse_agent/browser_ref_selector.py`, and `src/eclipse_agent/screen_ask.py` with fallback reason metadata, normalized snapshot handling, and privacy-preserving evidence.
- [x] 3.3 Updated `src/eclipse_agent/media_playback.py` and `src/eclipse_agent/notification_replies.py` so simple media/search remains native and indirect submit/send actions require confirmation.
- [x] 3.4 Extended router, browser automation, ref selector, screen fallback, media playback, and notification reply tests for PR3 spec scenarios.

## Current PR3 Changed Files

These are the files in the active PR3 routing/integrations/fallbacks slice, including
review-blocker fixes. Earlier PR1/PR2 files remain listed only in the cumulative task
history above.

| File | Action | Summary |
|------|--------|---------|
| `src/eclipse_agent/tool_router.py` | Modified | Routed rich browser interactions through browser-control policy, parsed bool-like parameters fail-closed, preserved simple browser search as native, removed raw browser targets/messages from router metadata and router audit entries, and forwarded media confirmation context. |
| `src/eclipse_agent/main.py` | Modified | Injected `BrowserControlService` wired with loaded `EclipseSettings` and `ChromeDevToolsMCPAdapter.from_settings(...)` into runtime routers. |
| `src/eclipse_agent/browser_automation.py` | Modified | Added fallback metadata and normalized browser result handling without storing raw page content. |
| `src/eclipse_agent/browser_ref_selector.py` | Modified | Accepted normalized snapshot structures for ref selection. |
| `src/eclipse_agent/screen_ask.py` | Modified | Returned fallback evidence metadata without raw page capture content. |
| `src/eclipse_agent/media_playback.py` | Modified | Kept simple media/search native while honoring browser-control confirmation for indirect rich actions. |
| `src/eclipse_agent/notification_replies.py` | Modified | Gated no-selector snapshot preparation through browser-control consent/audit before using legacy browser fallback, while preserving draft-first confirmation behavior. |
| `tests/test_tool_router.py` | Modified | Added coverage for safe browser metadata/audit targets/audit detail, fail-closed bool-like flags, simple browser-search native routing, and runtime browser-control service injection. |
| `tests/test_browser_automation.py` | Modified | Added fallback metadata and normalized result coverage. |
| `tests/test_browser_ref_selector.py` | Modified | Added normalized snapshot selection coverage. |
| `tests/test_screen_ask.py` | Modified | Added privacy-preserving fallback evidence coverage. |
| `tests/test_media_playback.py` | Modified | Added native media/search and router-to-media confirmation parameter coverage. |
| `tests/test_notification_replies.py` | Modified | Added browser-control gated/audited no-selector snapshot coverage and confirmation-gated submit/send behavior coverage. |
| `openspec/changes/eclipse-chrome-devtools-browser-control/tasks.md` | Modified | Marked Phase 1, Phase 2, and Phase 3 tasks complete. |
| `openspec/changes/eclipse-chrome-devtools-browser-control/apply-progress.md` | Modified | Split cumulative task history from PR3 changed-file scope for review readability. |

## Prior PR1/PR2 Files Already Accounted For

- `src/eclipse_agent/browser_control.py`
- `src/eclipse_agent/settings.py`
- `src/eclipse_agent/settings_app.py`
- `src/eclipse_agent/gui/settings.html`
- `src/eclipse_agent/chrome_devtools_mcp.py`
- `tests/test_settings.py`
- `tests/test_settings_gui.py`
- `tests/test_browser_control.py`
- `tests/test_chrome_devtools_mcp.py`

## Verification

- `python -m pytest tests/test_settings.py tests/test_settings_gui.py` could not run because `python` is not available on PATH in this environment.
- `py -m pytest tests/test_settings.py tests/test_settings_gui.py` passed: 23 tests.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/settings.py src/eclipse_agent/settings_app.py tests/test_settings.py tests/test_settings_gui.py` passed.
- `py -m pytest tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_settings.py tests/test_settings_gui.py` passed: 36 tests.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/chrome_devtools_mcp.py tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_settings.py tests/test_settings_gui.py` passed.
- `py -m pytest tests/test_tool_router.py tests/test_browser_automation.py tests/test_browser_ref_selector.py tests/test_screen_ask.py tests/test_media_playback.py tests/test_notification_replies.py -q` passed: 82 tests.
- `py -m ruff check src/eclipse_agent/tool_router.py src/eclipse_agent/browser_automation.py src/eclipse_agent/browser_ref_selector.py src/eclipse_agent/screen_ask.py src/eclipse_agent/media_playback.py src/eclipse_agent/notification_replies.py tests/test_tool_router.py tests/test_browser_automation.py tests/test_browser_ref_selector.py tests/test_screen_ask.py tests/test_media_playback.py tests/test_notification_replies.py` passed.
- `py -m pytest tests/test_tool_router.py tests/test_notification_replies.py tests/test_media_playback.py tests/test_browser_control.py tests/test_chrome_devtools_mcp.py -q` passed: 73 tests after PR3 router-audit redaction fix.
- `py -m ruff check src/eclipse_agent/tool_router.py src/eclipse_agent/main.py src/eclipse_agent/notification_replies.py src/eclipse_agent/media_playback.py src/eclipse_agent/browser_control.py tests/test_tool_router.py tests/test_notification_replies.py tests/test_media_playback.py` passed after PR3 review-blocker fixes.
- `py -m pytest tests/test_settings.py tests/test_settings_gui.py tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_tool_router.py tests/test_browser_automation.py tests/test_browser_ref_selector.py tests/test_screen_ask.py tests/test_media_playback.py tests/test_notification_replies.py -q` passed: 128 tests after the final router-audit redaction fix.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/chrome_devtools_mcp.py src/eclipse_agent/settings.py src/eclipse_agent/settings_app.py src/eclipse_agent/main.py src/eclipse_agent/tool_router.py src/eclipse_agent/browser_automation.py src/eclipse_agent/browser_ref_selector.py src/eclipse_agent/screen_ask.py src/eclipse_agent/media_playback.py src/eclipse_agent/notification_replies.py tests/test_settings.py tests/test_settings_gui.py tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_tool_router.py tests/test_browser_automation.py tests/test_browser_ref_selector.py tests/test_screen_ask.py tests/test_media_playback.py tests/test_notification_replies.py` passed after the final router-audit redaction fix.
- `py -m pytest tests/test_tool_router.py tests/test_browser_control.py -q` passed: 42 tests after router audit detail switched from human message to redacted browser-control audit detail.
- `git diff --check` passed with only line-ending normalization warnings.

## Boundaries Observed

- Implemented Phase 3 only in this work unit, preserving previous Phase 1 and Phase 2 work.
- Did not remove `agent-browser`; it remains a fallback setting.
- Did not bypass consent or confirmation gates for rich browser actions.
- Diagnostics are non-attaching.
- Live browser access defaults off.

## Deviations

None. Implementation stayed within PR 3 routing/integrations/fallback scope and preserved native simple browser paths.

## Remaining Tasks

- [ ] Phase 4 verification/rollout tasks 4.1-4.2.
