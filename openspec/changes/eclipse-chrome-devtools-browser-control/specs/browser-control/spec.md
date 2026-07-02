# Browser Control Specification

## Purpose

Define Eclipse browser-control behavior for backend selection, Chrome DevTools MCP session modes, safety gates, fallbacks, and auditability.

## Requirements

### Requirement: Least-Powerful Browser Backend Selection

The system MUST choose the least-powerful backend that can satisfy the requested browser action. Native open/search SHALL remain preferred for simple low-risk launches. Chrome DevTools MCP MUST be preferred for rich browser control when the user has consented.

#### Scenario: Native simple launch

- GIVEN a user asks Eclipse to open a URL or perform a simple web search
- WHEN the action does not require page inspection, interaction, authenticated state, or automation
- THEN Eclipse MUST use native open/search rather than Chrome DevTools MCP
- AND no live browser attach consent is required

#### Scenario: Rich browser control

- GIVEN Chrome DevTools MCP is configured and browser-control consent is active
- WHEN a request needs page state, snapshots, clicks, forms, tabs, console, network, performance, screenshots, script evaluation, or authenticated sessions
- THEN Eclipse MUST route the action through Chrome DevTools MCP

### Requirement: Chrome DevTools Session Modes

The system MUST support managed profile, browser URL, WebSocket endpoint, and autoConnect remote-debugging modes. The selected mode SHALL be visible in settings and auditable at execution time.

#### Scenario: Managed profile session

- GIVEN the user selects managed profile mode
- WHEN Eclipse starts rich browser control
- THEN Eclipse MUST launch or reuse the configured managed Chrome profile without attaching to unrelated live browser windows

#### Scenario: Attach session

- GIVEN the user selects browser URL, WebSocket endpoint, or autoConnect mode
- WHEN Eclipse attempts to attach to Chrome remote debugging
- THEN Eclipse MUST verify that the user explicitly allowed live browser access for that mode
- AND Eclipse MUST fail closed if consent is missing or revoked

### Requirement: Sensitive Access Safety Gates

The system MUST treat live browser contents, authenticated sessions, credential fields, payments, account settings, destructive actions, and cross-site posting as sensitive. Sensitive actions MUST require explicit consent and SHOULD require action confirmation before execution.

#### Scenario: Sensitive live browser access

- GIVEN a rich-control request may inspect authenticated or live browser content
- WHEN consent has not been granted for the active session mode
- THEN Eclipse MUST not attach to or inspect the browser
- AND Eclipse SHOULD explain the required consent without exposing page contents

#### Scenario: Action confirmation

- GIVEN an action may submit a form, change account data, publish content, purchase, delete, or send a message
- WHEN Chrome DevTools MCP can perform the action
- THEN Eclipse MUST ask for confirmation before performing it
- AND the confirmation prompt MUST summarize the target and action

### Requirement: Fallbacks and Safe Privacy Defaults

The system MUST fall back safely when Chrome DevTools MCP is unavailable, denied, unhealthy, or insufficient. Screenshot+vision and legacy `agent-browser` MAY be used only as fallback paths and MUST NOT bypass consent, confirmations, or audit logging.

#### Scenario: DevTools unavailable or denied

- GIVEN rich browser control is requested
- WHEN Chrome DevTools MCP is unavailable, denied, or fails to attach
- THEN Eclipse SHOULD try screenshot+vision when it can answer safely
- AND Eclipse MAY use legacy `agent-browser` only if enabled and suitable

#### Scenario: Auditable privacy-preserving execution

- GIVEN Eclipse executes or declines a browser-control action
- WHEN the action completes, falls back, or is blocked
- THEN Eclipse MUST record backend, session mode, consent state, confirmation state, fallback reason, and outcome
- AND logs MUST avoid storing page secrets, credentials, cookies, tokens, and full page content by default
