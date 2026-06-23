"""Construction point for the Windows platform abstraction layer.

Eclipse targets Windows exclusively. The factory remains the single place that
builds platform implementations so the rest of the codebase depends on the PAL
interfaces (``eclipse_agent.pal.base``) instead of concrete classes, which keeps
the system testable through dependency injection.
"""

from __future__ import annotations

import sys

from eclipse_agent.pal.base import (
    AppLauncher,
    AudioRecorder,
    DaemonManager,
    InputSynthesizer,
    NotificationDaemon,
    ScreenCapture,
    SystemController,
    TTSProvider,
    WindowManager,
)


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "Eclipse is a Windows-only desktop agent. "
            f"Unsupported platform: {sys.platform!r}."
        )


class PlatformFactory:
    """Build Windows platform-layer implementations."""

    @staticmethod
    def get_window_manager() -> WindowManager:
        _require_windows()
        from eclipse_agent.pal.windows.window_manager import WindowsWindowManager

        return WindowsWindowManager()

    @staticmethod
    def get_input_synthesizer() -> InputSynthesizer:
        _require_windows()
        from eclipse_agent.pal.windows.input import WindowsInputSynthesizer

        return WindowsInputSynthesizer()

    @staticmethod
    def get_screen_capture() -> ScreenCapture:
        _require_windows()
        from eclipse_agent.pal.windows.capture import WindowsScreenCapture

        return WindowsScreenCapture()

    @staticmethod
    def get_app_launcher() -> AppLauncher:
        _require_windows()
        from eclipse_agent.pal.windows.launcher import WindowsAppLauncher

        return WindowsAppLauncher()

    @staticmethod
    def get_notification_daemon() -> NotificationDaemon:
        _require_windows()
        from eclipse_agent.pal.windows.notifications import WindowsNotificationDaemon

        return WindowsNotificationDaemon()

    @staticmethod
    def get_tts_provider() -> TTSProvider:
        _require_windows()
        from eclipse_agent.pal.windows.voice import WindowsTTSProvider

        return WindowsTTSProvider()

    @staticmethod
    def get_audio_recorder() -> AudioRecorder:
        _require_windows()
        from eclipse_agent.pal.windows.voice import WindowsAudioRecorder

        return WindowsAudioRecorder()

    @staticmethod
    def get_daemon_manager() -> DaemonManager:
        _require_windows()
        from eclipse_agent.pal.windows.daemon import WindowsDaemonManager

        return WindowsDaemonManager()

    @staticmethod
    def get_system_controller() -> SystemController:
        _require_windows()
        from eclipse_agent.pal.windows.system_control import WindowsSystemController

        return WindowsSystemController()
