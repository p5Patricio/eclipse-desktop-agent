import pytest

def test_pal_interfaces_exist_and_are_abstract():
    # Attempt to import interfaces from eclipse_agent.pal.base
    from eclipse_agent.pal.base import (
        WindowManager,
        InputSynthesizer,
        ScreenCapture,
        AppLauncher,
        NotificationDaemon,
        TTSProvider,
        AudioRecorder,
        DaemonManager,
    )

    # Verify that they are ABCs and cannot be instantiated directly
    for interface in [
        WindowManager,
        InputSynthesizer,
        ScreenCapture,
        AppLauncher,
        NotificationDaemon,
        TTSProvider,
        AudioRecorder,
        DaemonManager,
    ]:
        with pytest.raises(TypeError):
            interface()

def test_incomplete_window_manager_raises_type_error():
    from eclipse_agent.pal.base import WindowManager

    class IncompleteWindowManager(WindowManager):
        pass

    with pytest.raises(TypeError):
        IncompleteWindowManager()
