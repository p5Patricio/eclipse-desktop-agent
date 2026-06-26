from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from eclipse_agent.system_control import SystemAction

class WindowManager(ABC):
    @abstractmethod
    def list_windows(self) -> Any:
        """List active window titles or details."""
        pass

    @abstractmethod
    def focus_window(self, window_hint: str) -> Any:
        """Focus the target window by hint."""
        pass

class InputSynthesizer(ABC):
    @abstractmethod
    def move_mouse(self, x: int, y: int, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        """Move the mouse pointer to (x, y)."""
        pass

    @abstractmethod
    def click(self, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        """Perform a mouse click."""
        pass

    @abstractmethod
    def type_text(self, text: str, *, confirmed: bool = False, dry_run: bool = True) -> Any:
        """Type text input."""
        pass

class ScreenCapture(ABC):
    @abstractmethod
    def capture(
        self,
        *,
        output_path: str | Path | None = None,
        geometry: str | None = None,
        all_screens: bool = True,
        dry_run: bool = True,
    ) -> Any:
        """Capture the screen or a region of it.

        With no ``geometry``, captures every monitor when ``all_screens`` is true.
        """
        pass

    @abstractmethod
    def capture_selected_region(
        self,
        *,
        output_path: str | Path | None = None,
        dry_run: bool = True,
    ) -> Any:
        """Prompt region selection and capture it."""
        pass

class AppLauncher(ABC):
    @abstractmethod
    def discover_apps(self) -> tuple[Any, ...]:
        """Discover launchable applications."""
        pass

    @abstractmethod
    def find_app(self, query: str) -> Any | None:
        """Find an application by query."""
        pass

    @abstractmethod
    def launch(
        self,
        app_name: str,
        args: Iterable[str] = (),
        *,
        dry_run: bool = True,
    ) -> Any:
        """Launch the specified application."""
        pass

class NotificationDaemon(ABC):
    @abstractmethod
    def run(
        self,
        *,
        seconds: int | None = 30,
        speak: bool = False,
        dry_run: bool = True,
    ) -> Any:
        """Run the notification daemon listener."""
        pass

class TTSProvider(ABC):
    @abstractmethod
    def speak(self, text: str, *, dry_run: bool = True) -> Any:
        """Speak the text using the TTS engine."""
        pass

class AudioRecorder(ABC):
    @abstractmethod
    def record(
        self,
        audio_path: str | Path,
        *,
        seconds: int = 5,
        dry_run: bool = True,
    ) -> Any:
        """Record audio to a file."""
        pass

class DaemonManager(ABC):
    @abstractmethod
    def register_autostart(self, name: str, exec_path: str) -> Any:
        """Register the application to autostart."""
        pass

    @abstractmethod
    def remove_autostart(self, name: str) -> Any:
        """Remove the autostart registration."""
        pass

class SystemController(ABC):
    @abstractmethod
    def run(self, action: SystemAction, *, dry_run: bool = True) -> Any:
        """Run a system-control action (volume, media, lock, battery)."""
        pass
