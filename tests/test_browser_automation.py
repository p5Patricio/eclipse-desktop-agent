from eclipse_agent.browser_automation import (
    AgentBrowserAdapter,
    BrowserActionStatus,
    BrowserAutomationProfile,
    BrowserAutomationRequest,
    BrowserAutomationResult,
    BrowserCommandKind,
    BrowserInteractionPlan,
    BrowserInteractionStep,
    BrowserInteractionLoop,
    domain_from_url,
    parse_agent_browser_snapshot_json,
    render_browser_interaction_plan,
    validate_browser_url,
    validate_snapshot_ref,
)


def test_agent_browser_open_url_builds_allowed_domain_command(tmp_path):
    adapter = AgentBrowserAdapter(
        BrowserAutomationProfile(
            binary="agent-browser",
            session="eclipse-test",
            action_policy=tmp_path / "policy.json",
        )
    )

    result = adapter.open_url("https://www.instagram.com/", dry_run=True)

    assert result.success is True
    assert result.kind is BrowserCommandKind.OPEN_URL
    assert result.command == (
        "agent-browser",
        "--session",
        "eclipse-test",
        "--allowed-domains",
        "localhost,127.0.0.1,www.instagram.com",
        "--action-policy",
        str(tmp_path / "policy.json"),
        "open",
        "https://www.instagram.com/",
    )


def test_agent_browser_search_builds_search_url(tmp_path):
    adapter = AgentBrowserAdapter(
        BrowserAutomationProfile(
            session="eclipse-test",
            action_policy=tmp_path / "policy.json",
        )
    )

    result = adapter.search("Fedora 44 KDE", dry_run=True)

    assert result.success is True
    assert result.command[-2:] == (
        "open",
        "https://www.google.com/search?q=Fedora+44+KDE",
    )
    assert "www.google.com" in result.command[4]


def test_agent_browser_rejects_unsafe_url_scheme():
    adapter = AgentBrowserAdapter()

    result = adapter.open_url("file:///etc/passwd", dry_run=True)

    assert result.success is False
    assert "Unsupported browser URL scheme" in result.message


def test_snapshot_command_uses_batch_open_then_interactive_snapshot(tmp_path):
    adapter = AgentBrowserAdapter(
        BrowserAutomationProfile(
            session="eclipse-test",
            action_policy=tmp_path / "policy.json",
        )
    )

    result = adapter.snapshot("https://example.com", dry_run=True)

    assert result.command[-5:] == (
        "batch",
        "--json",
        "--bail",
        "open https://example.com",
        "snapshot -i",
    )


def test_ref_click_command_requires_snapshot_ref():
    adapter = AgentBrowserAdapter()

    result = adapter.click("@e12", dry_run=True)

    assert result.success is True
    assert result.command[-2:] == ("click", "@e12")


def test_ref_fill_rejects_css_selector_for_mvp():
    adapter = AgentBrowserAdapter()

    result = adapter.fill("#email", "pat@example.com", dry_run=True)

    assert result.success is False
    assert "Only snapshot refs" in result.message


def test_browser_interaction_loop_blocks_ref_action_without_confirmation():
    loop = BrowserInteractionLoop()

    plan = loop.confirmed_ref_action(kind=BrowserCommandKind.CLICK, selector="@e1")

    assert plan.status is BrowserActionStatus.BLOCKED
    assert plan.requires_confirmation is True
    assert plan.results == ()


def test_browser_interaction_loop_prepares_confirmed_fill_action():
    loop = BrowserInteractionLoop()

    plan = loop.confirmed_ref_action(
        kind=BrowserCommandKind.FILL,
        selector="@e2",
        text="mensaje borrador",
        confirmed=True,
    )

    assert plan.status is BrowserActionStatus.PREPARED
    assert plan.results[0].command[-3:] == ("fill", "@e2", "mensaje borrador")


def test_browser_interaction_loop_open_and_snapshot():
    loop = BrowserInteractionLoop()

    plan = loop.open_and_snapshot("https://example.com")

    assert plan.status is BrowserActionStatus.PREPARED
    assert plan.requires_confirmation is False
    assert plan.results[0].command[-1] == "snapshot -i"


def test_render_browser_interaction_plan_includes_failure_detail():
    step = BrowserInteractionStep(
        kind=BrowserCommandKind.SNAPSHOT,
        description="Open URL and collect snapshot.",
        requires_confirmation=False,
        request=BrowserAutomationRequest(
            kind=BrowserCommandKind.SNAPSHOT,
            url="https://example.com",
        ),
    )
    result = BrowserAutomationResult(
        success=False,
        kind=BrowserCommandKind.SNAPSHOT,
        command=("agent-browser", "snapshot"),
        message="agent-browser command failed.",
        dry_run=False,
        stdout='{"success":false,"error":"sandbox blocked"}',
    )
    plan = BrowserInteractionPlan(
        steps=(step,),
        results=(result,),
        status=BrowserActionStatus.FAILED,
        message="Browser interaction failed to prepare.",
    )

    rendered = render_browser_interaction_plan(plan)

    assert "detail:" in rendered
    assert "sandbox blocked" in rendered


def test_domain_from_url_normalizes_hostname():
    assert domain_from_url("https://WWW.YouTube.com/watch?v=1") == "www.youtube.com"


def test_validate_browser_url_requires_hostname():
    try:
        validate_browser_url("https:///missing-host")
    except ValueError as exc:
        assert "hostname" in str(exc)
    else:
        raise AssertionError("Expected missing hostname to be rejected")


def test_validate_snapshot_ref_accepts_agent_browser_refs():
    assert validate_snapshot_ref("@e4") == "@e4"
    assert validate_snapshot_ref("e4") == "@e4"


def test_parse_agent_browser_snapshot_json_normalizes_refs():
    raw_output = """
{
  "success": true,
  "data": {
    "origin": "https://example.com/",
    "refs": {
      "e1": {"name": "Example Domain", "role": "heading"},
      "e2": {"name": "Learn more", "role": "link"}
    },
    "snapshot": "- heading \\"Example Domain\\" [ref=e1]"
  },
  "error": null
}
"""

    snapshot = parse_agent_browser_snapshot_json(raw_output)

    assert snapshot.origin == "https://example.com/"
    assert snapshot.elements[0].ref == "@e1"
    assert snapshot.elements[1].role == "link"



def test_parse_agent_browser_batch_json_output():
    import json

    raw_output = json.dumps(
        [
            {
                "command": ["open", "https://example.com"],
                "success": True,
                "result": {"title": "Example Domain"},
            },
            {
                "command": ["snapshot", "-i"],
                "success": True,
                "result": {
                    "origin": "https://example.com/",
                    "refs": {"e2": {"name": "Learn more", "role": "link"}},
                    "snapshot": "- link \"Learn more\" [ref=e2]",
                },
            },
        ]
    )

    snapshot = parse_agent_browser_snapshot_json(raw_output)

    assert snapshot.elements[0].ref == "@e2"
    assert snapshot.elements[0].name == "Learn more"
