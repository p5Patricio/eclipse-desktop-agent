# Apply Progress: Eclipse Chrome DevTools Browser Control

## Change

eclipse-chrome-devtools-browser-control

## Mode

Standard. No `openspec/config.yaml` was present, so strict TDD was not enabled.

## Current Work Unit

PR 2 adapter/service policy only.

## Completed Tasks

- [x] 1.1 Created `src/eclipse_agent/browser_control.py` with browser backend/session enums, request/result dataclasses, consent/confirmation/fallback policy shells, and redacted audit-detail helpers.
- [x] 1.2 Added browser-control settings fields in `src/eclipse_agent/settings.py` with native/simple default policy, disabled live access consent, and enabled safe fallbacks.
- [x] 1.3 Extended `src/eclipse_agent/settings_app.py` and `src/eclipse_agent/gui/settings.html` with browser backend/session settings, consent/fallback toggles, warning copy, and non-attaching diagnostics.
- [x] 1.4 Extended `tests/test_settings.py` and `tests/test_settings_gui.py` for persistence, diagnostics shape, default-off live access, and audit redaction.
- [x] 2.1 Created `src/eclipse_agent/chrome_devtools_mcp.py` with Chrome DevTools MCP session config, existing MCP client discovery, non-attaching health diagnostics, and logical-to-tool-name resolution.
- [x] 2.2 Implemented `BrowserControlService` policy in `src/eclipse_agent/browser_control.py` for least-powerful backend classification, consent fail-closed behavior, confirmation gates, safe fallback decisions, and redacted audit records.
- [x] 2.3 Added `tests/test_browser_control.py` for native simple selection, rich DevTools selection, missing/revoked consent fail-closed behavior, confirmation-required actions, fallback selection, and redacted audit details.
- [x] 2.4 Added `tests/test_chrome_devtools_mcp.py` with fake MCP clients covering configured/discovered/missing tools and managed/browser-url/ws-endpoint/auto-connect modes.

## Files Changed

| File | Action | Summary |
|------|--------|---------|
| `src/eclipse_agent/browser_control.py` | Created | Added Phase 1 browser-control contracts and redacted audit helpers without DevTools attach/calls. |
| `src/eclipse_agent/settings.py` | Modified | Added safe-default browser-control persistence and env bridging fields. |
| `src/eclipse_agent/settings_app.py` | Modified | Added non-attaching browser-control diagnostics API. |
| `src/eclipse_agent/gui/settings.html` | Modified | Added Browser Control card, settings bindings, warning copy, and diagnostics rendering. |
| `tests/test_settings.py` | Modified | Added settings persistence, diagnostics, default-off live access, and audit-redaction coverage. |
| `tests/test_settings_gui.py` | Modified | Added GUI field binding and diagnostics/warning coverage. |
| `src/eclipse_agent/chrome_devtools_mcp.py` | Created | Added Chrome DevTools MCP adapter configuration, non-attaching health, discovery, and tool mapping. |
| `src/eclipse_agent/browser_control.py` | Modified | Added `BrowserControlService` backend policy, consent/confirmation gates, fallbacks, and audit recording. |
| `tests/test_browser_control.py` | Created | Added service policy tests for PR2 acceptance criteria. |
| `tests/test_chrome_devtools_mcp.py` | Created | Added adapter tests with fake MCP clients and session-mode coverage. |
| `openspec/changes/eclipse-chrome-devtools-browser-control/tasks.md` | Modified | Marked Phase 1 tasks 1.1-1.4 and Phase 2 tasks 2.1-2.4 complete. |

## Verification

- `python -m pytest tests/test_settings.py tests/test_settings_gui.py` could not run because `python` is not available on PATH in this environment.
- `py -m pytest tests/test_settings.py tests/test_settings_gui.py` passed: 23 tests.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/settings.py src/eclipse_agent/settings_app.py tests/test_settings.py tests/test_settings_gui.py` passed.
- `py -m pytest tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_settings.py tests/test_settings_gui.py` passed: 36 tests.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/chrome_devtools_mcp.py tests/test_browser_control.py tests/test_chrome_devtools_mcp.py tests/test_settings.py tests/test_settings_gui.py` passed.

## Boundaries Observed

- Implemented Phase 2 only.
- Did not modify `src/eclipse_agent/tool_router.py`.
- Did not remove `agent-browser`; it remains a fallback setting.
- Did not add real Chrome DevTools attach/tool calls; adapter health performs discovery only and service calls it only after consent/confirmation gates.
- Diagnostics are non-attaching.
- Live browser access defaults off.

## Deviations

None. Implementation stayed within PR 2 adapter/service policy and did not implement PR 3 routing/integrations.

## Remaining Tasks

- [ ] Phase 3 routing/integration/fallback tasks 3.1-3.4.
- [ ] Phase 4 verification/rollout tasks 4.1-4.2.
