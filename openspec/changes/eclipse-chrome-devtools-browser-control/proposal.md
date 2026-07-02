# Proposal: Eclipse Chrome DevTools Browser Control

## Intent

Make Chrome DevTools MCP Eclipse's primary backend for rich browser control, while preserving native open/search for safe launches and screenshot+vision as fallback.

## Scope

### In Scope
- Prefer Chrome DevTools MCP for page state, snapshots, clicks, forms, tabs, console/network/performance, screenshots, script evaluation, and authenticated sessions.
- Keep native `open_url`/search for simple low-risk launches.
- Keep screenshot+vision and `agent-browser` as fallbacks during gradual deprecation.
- Add consent, safe defaults, auditability, and confirmation gates.
- Support managed Chrome profile plus `--browser-url`, `--wsEndpoint`, and `--autoConnect` attach modes.

### Out of Scope
- Immediate `agent-browser` removal.
- Full automation for simple media/search flows.
- Bypassing Chrome remote-debugging consent or security prompts.

## Capabilities

### New Capabilities
- `browser-control`: Chrome DevTools MCP modes, actions, safety gates, fallbacks, and `agent-browser` deprecation.

### Modified Capabilities
- None. No existing OpenSpec capability was found; MCP/settings behavior belongs in `browser-control`.

## Approach

Add a browser-control router that selects the least-powerful sufficient backend: native open/search for simple actions, Chrome DevTools MCP for rich control, and screenshot+vision or `agent-browser` when MCP is unavailable or denied. Reuse STDIO MCP configuration and extend settings/UI for backend mode, attach parameters, and consent policy.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/eclipse_agent/browser_automation.py` | Modified | Backend routing and fallback behavior. |
| `src/eclipse_agent/tool_router.py` | Modified | Browser-control routing through MCP infrastructure. |
| `src/eclipse_agent/settings.py` | Modified | Persist backend/session/safety settings. |
| `src/eclipse_agent/settings_app.py` | Modified | Settings API for browser backend configuration. |
| `src/eclipse_agent/gui/settings.html` | Modified | Backend, consent, and safety controls. |
| `src/eclipse_agent/browser_ref_selector.py` | Modified | Prefer DevTools snapshots/selectors before vision. |
| `src/eclipse_agent/screen_ask.py` | Modified | Preserve screenshot+vision fallback evidence. |
| `src/eclipse_agent/media_playback.py` | Modified | Keep simple open/search behavior by default. |
| `src/eclipse_agent/notification_replies.py` | Modified | Apply safety gates to indirect browser actions. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Sensitive browser/session exposure. | High | Explicit consent, safe defaults, audit logs, confirmations. |
| Attach-mode brittleness. | Medium | Support managed profile, URL, WebSocket, auto-connect, and fallback. |
| Workflow regressions. | Medium | Keep native, vision, and `agent-browser` compatibility paths. |

## Rollback Plan

Disable Chrome DevTools MCP routing in settings and fall back to native open/search, screenshot+vision, and `agent-browser` without deleting compatibility code.

## Dependencies

- Official Chrome DevTools MCP configured as a STDIO MCP backend.
- User-approved Chrome remote debugging/session access.

## Success Criteria

- [ ] Rich browser tasks use Chrome DevTools MCP when consented.
- [ ] Simple URL/search actions remain native.
- [ ] Screenshot+vision and `agent-browser` remain fallbacks.
- [ ] Sensitive browser access is consented, confirmed, and auditable.

