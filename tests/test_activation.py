from eclipse_agent.activation import ActivationMode, build_activation_policy
from eclipse_agent.resources import estimate_resource_profile


def test_default_activation_is_alexa_style_without_continuous_transcription():
    policy = build_activation_policy()

    assert policy.mode is ActivationMode.WAKE_WORD
    assert policy.always_on_daemon is True
    assert policy.is_alexa_style is True
    assert policy.records_continuously is False


def test_continuous_stt_profile_is_not_recommended_for_mvp():
    profile = estimate_resource_profile(ActivationMode.CONTINUOUS_STT)

    assert "Avoid for MVP" in profile.recommendation
    assert profile.idle_ram_mb[0] >= 800
