import sys
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

from eclipse_agent.safety.redactor import redact_screenshot

def test_redact_screenshot_blurs_sensitive_window(tmp_path):
    """Test that a sensitive window title (e.g. 'My Bank') causes its rect to be blurred."""
    image_path = tmp_path / "screenshot.png"
    
    # Create an image (100x100) with a black square in the middle (40, 40, 60, 60) on a white background.
    img = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 60, 60], fill="black")
    img.save(image_path)
    
    # We will mock win32gui to simulate finding a sensitive window.
    mock_hwnd = 12345
    
    def mock_enum_windows(callback, extra):
        # Call the callback with the mock hwnd
        callback(mock_hwnd, extra)
        return True
        
    with patch("sys.platform", "win32"), \
         patch("eclipse_agent.safety.redactor.win32gui") as mock_win32gui:
        
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "Keepass - Passwords"
        mock_win32gui.GetWindowRect.return_value = (30, 30, 70, 70)  # over the black square
        mock_win32gui.EnumWindows = mock_enum_windows
        
        redact_screenshot(str(image_path))
        
    # Load image back and verify the pixel changes.
    result_img = Image.open(image_path)
    
    # The pixel at (50, 50) was solid black (0, 0, 0) and should be blurred (no longer solid black).
    # The pixel at (5, 5) was white and should remain solid white (255, 255, 255).
    center_pixel = result_img.getpixel((50, 50))
    corner_pixel = result_img.getpixel((5, 5))
    
    assert center_pixel != (0, 0, 0)
    assert corner_pixel == (255, 255, 255)


def test_redact_screenshot_does_not_blur_non_sensitive_window(tmp_path):
    """Test that non-sensitive window titles do not trigger redaction."""
    image_path = tmp_path / "screenshot.png"
    
    # Create an image (100x100) with a black square in the middle on a white background.
    img = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 60, 60], fill="black")
    img.save(image_path)
    
    mock_hwnd = 12345
    def mock_enum_windows(callback, extra):
        callback(mock_hwnd, extra)
        return True
        
    with patch("sys.platform", "win32"), \
         patch("eclipse_agent.safety.redactor.win32gui") as mock_win32gui:
        
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "Untitled - Notepad"
        mock_win32gui.GetWindowRect.return_value = (30, 30, 70, 70)
        mock_win32gui.EnumWindows = mock_enum_windows
        
        redact_screenshot(str(image_path))
        
    result_img = Image.open(image_path)
    center_pixel = result_img.getpixel((50, 50))
    corner_pixel = result_img.getpixel((5, 5))
    
    # Since it was not sensitive, no blurring should occur.
    # Center pixel should remain solid black (0, 0, 0)
    assert center_pixel == (0, 0, 0)
    assert corner_pixel == (255, 255, 255)


def test_redact_screenshot_clips_out_of_bounds_rect(tmp_path):
    """Test that rect is clipped properly when it is out of image boundary."""
    image_path = tmp_path / "screenshot.png"
    
    # Create a solid black image (100x100)
    img = Image.new("RGB", (100, 100), "black")
    img.save(image_path)
    
    mock_hwnd = 12345
    def mock_enum_windows(callback, extra):
        callback(mock_hwnd, extra)
        return True
        
    with patch("sys.platform", "win32"), \
         patch("eclipse_agent.safety.redactor.win32gui") as mock_win32gui:
        
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "Bank Account"
        # Bounding box is way out of bounds (-50, -50, 150, 150)
        mock_win32gui.GetWindowRect.return_value = (-50, -50, 150, 150)
        mock_win32gui.EnumWindows = mock_enum_windows
        
        # This should execute and clip/blur without raising ValueError or other exceptions.
        redact_screenshot(str(image_path))
        
    result_img = Image.open(image_path)
    assert result_img.size == (100, 100)


def test_redact_screenshot_does_nothing_on_non_windows_platforms(tmp_path):
    """Test that on non-Windows platforms, we don't query or blur anything."""
    image_path = tmp_path / "screenshot.png"
    img = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 60, 60], fill="black")
    img.save(image_path)
    
    # On linux, platform is 'linux'
    with patch("sys.platform", "linux"), \
         patch("eclipse_agent.safety.redactor.win32gui") as mock_win32gui:
         
        redact_screenshot(str(image_path))
        
        # win32gui shouldn't be called at all
        mock_win32gui.EnumWindows.assert_not_called()
        
    result_img = Image.open(image_path)
    center_pixel = result_img.getpixel((50, 50))
    assert center_pixel == (0, 0, 0)
