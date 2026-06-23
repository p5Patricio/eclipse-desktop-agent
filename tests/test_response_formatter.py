from eclipse_agent.response_formatter import ActionResponseFormatter
from eclipse_agent.tool_router import ToolExecutionResult


def _route_result(
    *,
    success: bool = True,
    message: str = 'MCP tool executed with structured result: {"secret": "raw"}',
    structured_content: dict | None = None,
    requires_confirmation: bool = False,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        action_id='action-1',
        tool_name='native.open_url',
        success=success,
        executed=success,
        requires_confirmation=requires_confirmation,
        message=message,
        metadata={'arguments': '{"raw": true}'},
        structured_content=structured_content,
    )


def test_successful_action_summary_uses_user_facts_and_hides_router_internals():
    formatter = ActionResponseFormatter()
    result = _route_result(
        structured_content={
            'success': True,
            'action_type': 'open_web_app',
            'target': 'Instagram',
            'user_facts': {'target': 'Instagram'},
        },
    )

    spoken = formatter.format(command_text='Eclipse, abre Instagram', route_results=(result,))

    assert spoken == 'Listo, abrí Instagram.'
    assert 'MCP' not in spoken
    assert 'structured result' not in spoken
    assert '{' not in spoken
    assert 'native.open_url' not in spoken


def test_read_clipboard_speaks_the_content_verbatim():
    formatter = ActionResponseFormatter()
    result = _route_result(
        structured_content={
            'success': True,
            'action_type': 'read_clipboard',
            'target': 'clipboard',
            'user_facts': {
                'action_type': 'read_clipboard',
                'target': 'clipboard',
                'spoken': 'hola mundo',
            },
        },
    )

    spoken = formatter.format(command_text='Eclipse, qué tengo copiado', route_results=(result,))

    assert spoken == 'hola mundo'


def test_system_control_volume_speaks_localized_confirmation():
    formatter = ActionResponseFormatter()
    result = _route_result(
        structured_content={
            'success': True,
            'action_type': 'system_control',
            'target': 'volume_up',
            'user_facts': {
                'action_type': 'system_control',
                'target': 'volume_up',
                'detail': 'Sent volume_up.',
            },
        },
    )

    spoken = formatter.format(command_text='Eclipse, subí el volumen', route_results=(result,))

    assert spoken == 'Listo, subí el volumen.'


def test_system_control_battery_speaks_the_status_detail():
    formatter = ActionResponseFormatter()
    result = _route_result(
        structured_content={
            'success': True,
            'action_type': 'system_control',
            'target': 'battery',
            'user_facts': {
                'action_type': 'system_control',
                'target': 'battery',
                'detail': 'Battery 72%, on AC power.',
            },
        },
    )

    spoken = formatter.format(command_text='Eclipse, cuánta batería tengo', route_results=(result,))

    assert '72%' in spoken


def test_recoverable_failure_uses_safe_reason_and_one_next_step_only():
    formatter = ActionResponseFormatter()
    result = _route_result(
        success=False,
        message='Traceback (most recent call last): File secret.py stderr raw dump',
        structured_content={
            'success': False,
            'action_type': 'desktop_open_app',
            'target': 'Slack',
            'failure_reason': 'Slack is not in the supported app list.',
            'next_step': 'Try browser, terminal, or files.',
        },
    )

    spoken = formatter.format(command_text='Eclipse, abre Slack', route_results=(result,))

    assert spoken == 'No pude abrir Slack: Slack is not in the supported app list. Try browser, terminal, or files.'
    assert 'Traceback' not in spoken
    assert 'stderr' not in spoken
    assert spoken.count('.') <= 2


def test_no_action_response_asks_for_clear_supported_command_without_claiming_success():
    formatter = ActionResponseFormatter()

    spoken = formatter.format(command_text='Eclipse, haz magia', route_results=())

    assert spoken == 'No encontré una acción segura para eso. Pedime abrir una app, buscar algo o revisar notificaciones.'
    assert 'abrí' not in spoken
    assert 'Listo' not in spoken


def test_formatter_preserves_spanish_and_english_language_and_bounds_text():
    formatter = ActionResponseFormatter(max_sentences=1, max_characters=48)
    spanish = _route_result(
        structured_content={
            'success': True,
            'action_type': 'browser_search',
            'target': 'Fedora 44',
            'user_facts': {'target': 'Fedora 44'},
        },
    )
    english = _route_result(
        structured_content={
            'success': True,
            'action_type': 'browser_search',
            'target': 'Fedora 44',
            'user_facts': {'target': 'Fedora 44'},
        },
    )

    spanish_spoken = formatter.format(command_text='Eclipse, busca Fedora 44', route_results=(spanish,))
    english_spoken = formatter.format(command_text='Eclipse, search Google for Fedora 44', route_results=(english,))

    assert spanish_spoken == 'Listo, busqué Fedora 44.'
    assert english_spoken == 'Done, I searched for Fedora 44.'
    assert len(spanish_spoken) <= 48
    assert len(english_spoken) <= 48
    assert spanish_spoken.count('.') <= 1
    assert english_spoken.count('.') <= 1


def test_unsafe_polished_output_falls_back_to_deterministic_template():
    formatter = ActionResponseFormatter(polisher=lambda *_args, **_kwargs: 'MCP says {"raw": true}')
    result = _route_result(
        structured_content={
            'success': True,
            'action_type': 'open_web_app',
            'target': 'GitHub',
            'user_facts': {'target': 'GitHub'},
        },
    )

    spoken = formatter.format(command_text='Eclipse, open GitHub', route_results=(result,))

    assert spoken == 'Done, I opened GitHub.'


def test_failure_response_uses_search_specific_verb():
    formatter = ActionResponseFormatter()
    result = _route_result(
        success=False,
        structured_content={
            'success': False,
            'action_type': 'google_search',
            'target': 'Fedora 44',
            'failure_reason': 'Tell me what you want to search for.',
        },
    )

    spoken = formatter.format(command_text='Eclipse, search Google', route_results=(result,))

    assert spoken == 'I could not search for Fedora 44: Tell me what you want to search for.'


def test_failure_response_uses_app_launch_specific_verb():
    formatter = ActionResponseFormatter()
    result = _route_result(
        success=False,
        structured_content={
            'success': False,
            'action_type': 'desktop_open_app',
            'target': 'Slack',
            'failure_reason': 'Slack is not in the supported app list.',
        },
    )

    spoken = formatter.format(command_text='Eclipse, abre Slack', route_results=(result,))

    assert spoken == 'No pude abrir Slack: Slack is not in the supported app list.'
