from eclipse_agent.agent_smoke import (
    build_agent_smoke_plan,
    render_agent_smoke_plan,
    run_agent_smoke_simulation,
)


def test_smoke_plan_contains_real_agent_test_steps(tmp_path):
    steps = build_agent_smoke_plan(store_path=tmp_path / "smoke.sqlite3")

    names = tuple(step.name for step in steps)

    assert "notification-service" in names
    assert "browser-snapshot" in names
    assert "reply-draft" in names
    assert "--store" in steps[2].command


def test_render_smoke_plan_includes_expected_commands(tmp_path):
    rendered = render_agent_smoke_plan(
        build_agent_smoke_plan(store_path=tmp_path / "smoke.sqlite3")
    )

    assert "Eclipse agent smoke plan" in rendered
    assert "notifications-reply-draft" in rendered
    assert "--auto-select" in rendered


def test_run_agent_smoke_simulation_exercises_queue_digest_and_reply(tmp_path):
    result = run_agent_smoke_simulation(store_path=tmp_path / "smoke.sqlite3")

    assert result.success is True
    assert "ingest=queue:game" in result.messages
    assert "digest_total=1" in result.messages
    assert "reply=True:@e2" in result.messages
