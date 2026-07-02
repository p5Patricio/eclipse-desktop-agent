# Design: Eclipse Chrome DevTools Browser Control

## Technical Approach

Add a browser-control capability layer above the existing `ToolRouter`, `MCPToolClient`, `AgentBrowserAdapter`, and screenshot+vision flow. The layer chooses the least-powerful backend per request: native open/search for simple launches, Chrome DevTools MCP for rich page interaction when consent is active, then screenshot+vision or legacy `agent-browser` as fallbacks. The first slice keeps `agent-browser` intact and routes only through explicit browser-control contracts.

## Architecture Decisions

| Decision | Choice | Tradeoff / Rationale |
|---|---|---|
| Backend routing | Create `BrowserControlService` instead of embedding policy in `ToolRouter`. | Keeps generic MCP routing stable while centralizing browser-specific consent, fallbacks, and diagnostics. |
| Primary rich backend | Add `ChromeDevToolsMCPAdapter` over existing STDIO MCP client discovery/calls. | Reuses `mcp-servers.json`; avoids a second MCP runtime. Tool-name mapping stays isolated because MCP tool names can evolve. |
| Safety model | Consent gates for live/attach modes; confirmation gates for submit/post/delete/purchase/send/account actions. | Matches current draft-first routing and prevents authenticated session exposure from becoming implicit. |
| Audit/privacy | Store redacted JSON in `AuditEntry.detail`, not page content. | Avoids DB migration while recording backend, mode, consent, confirmation, fallback reason, and outcome. |

## Data Flow

    Planner/feature module
          -> BrowserControlService.classify(request)
          -> consent/confirmation gate
          -> audit blocked-or-allowed decision
          -> native open/search OR ChromeDevToolsMCPAdapter attach/tool call
          -> fallback only when allowed: screen_ask then AgentBrowserAdapter
          -> audit final outcome

Simple `OPEN_WEB_APP`, `BROWSER_SEARCH`, `GOOGLE_SEARCH`, and media search keep native paths unless the caller asks for rich inspection or interaction.

## File Changes

| File | Action | Description |
|---|---|---|
| `src/eclipse_agent/browser_control.py` | Create | Backend selection, consent checks, fallback orchestration, redacted audit payloads. |
| `src/eclipse_agent/chrome_devtools_mcp.py` | Create | Adapter for Chrome DevTools MCP session modes, tool mapping, health checks, and privacy-safe launch args. |
| `src/eclipse_agent/settings.py` | Modify | Add browser-control fields: backend policy, session mode, browser URL, ws endpoint, managed profile, live-access consent, confirmation policy, fallback toggles. |
| `src/eclipse_agent/settings_app.py` | Modify | Expose browser settings, consent updates, diagnostics, and Chrome DevTools MCP config helper. |
| `src/eclipse_agent/gui/settings.html` | Modify | Add Browser Control card with mode, consent, fallback, diagnostics, and warning copy. |
| `src/eclipse_agent/tool_router.py` | Modify | Route rich browser planned actions through `BrowserControlService`; preserve native simple actions. |
| `src/eclipse_agent/browser_automation.py` | Modify | Mark `AgentBrowserAdapter` as fallback-capable and accept fallback reason metadata. |
| `src/eclipse_agent/browser_ref_selector.py` | Modify | Parse/select refs from a normalized snapshot shape usable by DevTools and agent-browser. |
| `src/eclipse_agent/screen_ask.py` | Modify | Surface fallback evidence without storing raw page content. |
| `src/eclipse_agent/media_playback.py` | Modify | Keep open-search as default; optionally expose rich control only behind explicit request. |
| `src/eclipse_agent/notification_replies.py` | Modify | Use browser-control service and keep draft-fill confirmation behavior. |

## Interfaces / Contracts

```python
class BrowserBackend(StrEnum): NATIVE="native"; CHROME_DEVTOOLS="chrome_devtools"; VISION="vision"; AGENT_BROWSER="agent_browser"
class BrowserSessionMode(StrEnum): MANAGED="managed"; BROWSER_URL="browser_url"; WS_ENDPOINT="ws_endpoint"; AUTO_CONNECT="auto_connect"
@dataclass(frozen=True)
class BrowserControlRequest:
    intent: str; url: str = ""; action: str = ""; selector: str = ""; text: str = ""; sensitive: bool = False
@dataclass(frozen=True)
class BrowserControlResult:
    success: bool; backend: BrowserBackend; mode: BrowserSessionMode | None; message: str; fallback_reason: str = ""
```

`BrowserControlService` MUST evaluate consent before any DevTools attach, health check that attaches, snapshot, inspection, or tool call. `ChromeDevToolsMCPAdapter.health()` returns configured/discovered/missing tools and MUST have a non-attaching mode for pre-consent diagnostics.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Backend selection, consent, confirmation, redacted audit payloads. | Fake settings, fake audit log, no real browser. |
| Unit | Chrome DevTools MCP adapter command/tool mapping and health states. | Fake `MCPClientProtocol` with discovered tools/results. |
| Integration | Settings UI/API persistence and diagnostics. | Extend `test_settings.py` and `test_settings_gui.py`. |
| Regression | Native open/search, media playback, notification draft, screen fallback. | Extend existing focused tests. |

## Migration / Rollout

No data migration required. Default policy is `native_simple_plus_fallback`; Chrome DevTools rich control is off until configured and consented. Roll out in slices: settings/diagnostics, adapter, service routing, feature integrations, then deprecation warnings for `agent-browser` fallback.

## Open Questions

- [ ] Which exact Chrome DevTools MCP CLI privacy flags are available in the installed version?
- [ ] Should live-access consent be session-only, persistent, or both?
