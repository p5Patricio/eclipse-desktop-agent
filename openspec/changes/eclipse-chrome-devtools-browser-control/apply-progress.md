# Apply Progress: Eclipse Chrome DevTools Browser Control

## Change

eclipse-chrome-devtools-browser-control

## Mode

Standard. No `openspec/config.yaml` was present, so strict TDD was not enabled.

## Current Work Unit

PR 1 foundation/settings/diagnostics only.

## Completed Tasks

- [x] 1.1 Created `src/eclipse_agent/browser_control.py` with browser backend/session enums, request/result dataclasses, consent/confirmation/fallback policy shells, and redacted audit-detail helpers.
- [x] 1.2 Added browser-control settings fields in `src/eclipse_agent/settings.py` with native/simple default policy, disabled live access consent, and enabled safe fallbacks.
- [x] 1.3 Extended `src/eclipse_agent/settings_app.py` and `src/eclipse_agent/gui/settings.html` with browser backend/session settings, consent/fallback toggles, warning copy, and non-attaching diagnostics.
- [x] 1.4 Extended `tests/test_settings.py` and `tests/test_settings_gui.py` for persistence, diagnostics shape, default-off live access, and audit redaction.

## Files Changed

| File | Action | Summary |
|------|--------|---------|
| `src/eclipse_agent/browser_control.py` | Created | Added Phase 1 browser-control contracts and redacted audit helpers without DevTools attach/calls. |
| `src/eclipse_agent/settings.py` | Modified | Added safe-default browser-control persistence and env bridging fields. |
| `src/eclipse_agent/settings_app.py` | Modified | Added non-attaching browser-control diagnostics API. |
| `src/eclipse_agent/gui/settings.html` | Modified | Added Browser Control card, settings bindings, warning copy, and diagnostics rendering. |
| `tests/test_settings.py` | Modified | Added settings persistence, diagnostics, default-off live access, and audit-redaction coverage. |
| `tests/test_settings_gui.py` | Modified | Added GUI field binding and diagnostics/warning coverage. |
| `openspec/changes/eclipse-chrome-devtools-browser-control/tasks.md` | Modified | Marked Phase 1 tasks 1.1-1.4 complete. |

## Verification

- `python -m pytest tests/test_settings.py tests/test_settings_gui.py` could not run because `python` is not available on PATH in this environment.
- `py -m pytest tests/test_settings.py tests/test_settings_gui.py` passed: 23 tests.
- `py -m ruff check src/eclipse_agent/browser_control.py src/eclipse_agent/settings.py src/eclipse_agent/settings_app.py tests/test_settings.py tests/test_settings_gui.py` passed.

## Boundaries Observed

- Did not implement Phase 2 or Phase 3.
- Did not create `src/eclipse_agent/chrome_devtools_mcp.py`.
- Did not modify `src/eclipse_agent/tool_router.py`.
- Did not remove `agent-browser`; it remains a fallback setting.
- Did not add real Chrome DevTools attach/tool calls.
- Diagnostics are non-attaching.
- Live browser access defaults off.

## Deviations

None. Implementation stayed within PR 1 foundation/settings/diagnostics.

## Remaining Tasks

- [ ] Phase 2 Chrome DevTools adapter/service policy tasks 2.1-2.4.
- [ ] Phase 3 routing/integration/fallback tasks 3.1-3.4.
- [ ] Phase 4 verification/rollout tasks 4.1-4.2.
