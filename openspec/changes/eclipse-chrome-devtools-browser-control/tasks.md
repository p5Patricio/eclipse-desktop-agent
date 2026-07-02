# Tasks: Eclipse Chrome DevTools Browser Control

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1,400 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 foundation/settings/diagnostics -> PR 2 adapter/service -> PR 3 integrations/fallbacks/tests |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Settings, contracts, diagnostics, and non-attaching consent boundaries | PR 1 | Base `feat/chrome-devtools-browser-control`; no routing changes. |
| 2 | Chrome DevTools adapter and BrowserControlService policy | PR 2 | Base PR 1 branch; keep callers behind explicit contracts. |
| 3 | Feature integrations, fallback metadata, and regression coverage | PR 3 | Base PR 2 branch; verify native paths and safety gates. |

## Phase 1: Foundation / Settings / Diagnostics

- [x] 1.1 Create `src/eclipse_agent/browser_control.py` with `BrowserBackend`, `BrowserSessionMode`, request/result dataclasses, consent/confirmation policy shells, and redacted audit helpers.
- [x] 1.2 Add browser-control settings fields in `src/eclipse_agent/settings.py` with safe defaults: native/simple policy, disabled live attach consent, enabled safe fallbacks.
- [x] 1.3 Extend `src/eclipse_agent/settings_app.py` and `src/eclipse_agent/gui/settings.html` with backend mode, session parameters, consent, fallback toggles, diagnostics, and warning copy.
- [x] 1.4 Add/extend `tests/test_settings.py` and `tests/test_settings_gui.py` for persistence, diagnostics shape, and default-off live access.

## Phase 2: Chrome DevTools Adapter / Service Policy

- [x] 2.1 Create `src/eclipse_agent/chrome_devtools_mcp.py` using the existing MCP client path for tool discovery, non-attaching health, session mode config, and tool-name mapping.
- [x] 2.2 Implement `BrowserControlService` backend classification, pre-attach consent gates, confirmation gates, fallback decisions, and privacy-safe audit payloads in `src/eclipse_agent/browser_control.py`.
- [x] 2.3 Add unit tests for least-powerful backend selection, missing/revoked consent fail-closed behavior, confirmation-required actions, and redacted audit detail.
- [x] 2.4 Add adapter tests with fake MCP clients for configured/discovered/missing tools and managed/browser-url/ws-endpoint/auto-connect modes.

## Phase 3: Routing / Integrations / Fallbacks

- [ ] 3.1 Modify `src/eclipse_agent/tool_router.py` to route only rich browser actions through `BrowserControlService` while preserving native simple open/search.
- [ ] 3.2 Update `src/eclipse_agent/browser_automation.py`, `src/eclipse_agent/browser_ref_selector.py`, and `src/eclipse_agent/screen_ask.py` for fallback reason metadata, normalized snapshots, and evidence without raw page content.
- [ ] 3.3 Update `src/eclipse_agent/media_playback.py` and `src/eclipse_agent/notification_replies.py` so simple media/search stays native and indirect submit/send actions require confirmation.
- [ ] 3.4 Extend `tests/test_tool_router.py`, `tests/test_browser_automation.py`, `tests/test_browser_ref_selector.py`, `tests/test_screen_ask.py`, `tests/test_media_playback.py`, and `tests/test_notification_replies.py` for spec scenarios.

## Phase 4: Verification / Rollout

- [ ] 4.1 Run focused tests for settings, router, browser automation, snapshots, screen fallback, media playback, notification replies, and audit redaction.
- [ ] 4.2 Update `openspec/changes/eclipse-chrome-devtools-browser-control/tasks.md` checkboxes as PR slices complete; keep `agent-browser` fallback deprecation as warning-only.
