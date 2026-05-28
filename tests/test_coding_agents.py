from eclipse_agent.coding_agents import CodingAgentName, build_coding_agent_prompt, get_coding_agent


def test_voice_alias_resolves_claude_code():
    agent = get_coding_agent("Cloud Code")

    assert agent.name is CodingAgentName.CLAUDE


def test_voice_alias_resolves_gemini_transcription_variant():
    agent = get_coding_agent("Hemini")

    assert agent.name is CodingAgentName.GEMINI


def test_coding_agent_prompt_contains_safety_contract():
    prompt = build_coding_agent_prompt(
        agent="codex",
        project_path="/home/patodev/example",
        idea="Build a dashboard",
        user_constraints=("Keep it local-first",),
    )

    assert "Build a dashboard" in prompt
    assert "Keep it local-first" in prompt
    assert "Do not read, print, modify, or commit secrets" in prompt
    assert "verification commands" in prompt
