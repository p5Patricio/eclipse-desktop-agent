import sys
from PIL import Image, ImageFilter

if sys.platform == "win32":
    import win32gui


def redact_screenshot(image_path: str) -> None:
    """Load an image, check visible windows for sensitive terms on Windows, and blur them."""
    if sys.platform != "win32":
        return

    import os
    if not os.path.exists(image_path):
        return

    try:
        image = Image.open(image_path)
    except Exception:
        raise

    sensitive_terms = {"bank", "password", "login", "keepass", "bitwarden"}
    matched_hwnds = []

    def enum_callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                title_lower = title.lower()
                if any(term in title_lower for term in sensitive_terms):
                    matched_hwnds.append(hwnd)
        return True

    win32gui.EnumWindows(enum_callback, None)

    if not matched_hwnds:
        return

    img_width, img_height = image.size
    modified = False

    for hwnd in matched_hwnds:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            continue

        # Clip rect to image boundaries
        left = max(0, left)
        top = max(0, top)
        right = min(img_width, right)
        bottom = min(img_height, bottom)

        if left < right and top < bottom:
            box = (left, top, right, bottom)
            cropped = image.crop(box)
            blurred = cropped.filter(ImageFilter.GaussianBlur(radius=20))
            image.paste(blurred, box)
            modified = True

    if modified:
        image.save(image_path)
