from pathlib import Path
from typing import Any
from eclipse_agent.pal.base import ScreenCapture
from eclipse_agent.desktop_control import DesktopControlResult, DesktopControlAction

class WindowsScreenCapture(ScreenCapture):
    def capture(
        self,
        *,
        output_path: str | Path | None = None,
        geometry: str | None = None,
        all_screens: bool = True,
        dry_run: bool = True,
    ) -> Any:
        # Default output path
        if output_path is None:
            import tempfile
            output_path = Path(tempfile.gettempdir()) / "eclipse-screenshot.png"
        else:
            output_path = Path(output_path)

        if dry_run:
            return DesktopControlResult(
                success=True,
                action=DesktopControlAction.SCREENSHOT,
                command=("PIL.ImageGrab.grab",),
                message="Prepared Windows screenshot (ImageGrab).",
                dry_run=True,
                output_path=output_path,
            )

        try:
            from PIL import ImageGrab
            bbox = None
            if geometry:
                try:
                    parts = [int(p.strip()) for p in geometry.split(",")]
                    if len(parts) == 4:
                        x, y, w, h = parts
                        bbox = (x, y, x + w, y + h)
                except ValueError:
                    pass
            
            if bbox is not None:
                img = ImageGrab.grab(bbox=bbox)
            else:
                # all_screens spans every monitor (the full virtual desktop);
                # without it ImageGrab only captures the primary monitor.
                img = ImageGrab.grab(all_screens=all_screens)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path)
            return DesktopControlResult(
                success=True,
                action=DesktopControlAction.SCREENSHOT,
                command=("PIL.ImageGrab.grab",),
                message="Windows screenshot captured.",
                dry_run=False,
                executed=True,
                output_path=output_path,
            )
        except Exception as exc:
            return DesktopControlResult(
                success=False,
                action=DesktopControlAction.SCREENSHOT,
                command=("PIL.ImageGrab.grab",),
                message=f"Windows screenshot failed: {exc}",
                dry_run=False,
                output_path=output_path,
            )

    def capture_selected_region(
        self,
        *,
        output_path: str | Path | None = None,
        dry_run: bool = True,
    ) -> Any:
        # Active window or full screen capture fallback for region selection on Windows
        return self.capture(output_path=output_path, dry_run=dry_run)
