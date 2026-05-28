from pathlib import Path

from eclipse_agent.desktop_apps import DesktopAppLauncher, expand_exec_template, parse_desktop_entry


def _write_desktop_file(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_desktop_entry_and_build_command(tmp_path):
    desktop_file = _write_desktop_file(
        tmp_path,
        "youtube-music.desktop",
        """
[Desktop Entry]
Type=Application
Name=YouTube Music
Exec=/opt/google/chrome/google-chrome --profile-directory=Default --app-id=abc123
StartupWMClass=crx_abc123
""".strip(),
    )

    app = parse_desktop_entry(desktop_file)

    assert app is not None
    assert app.name == "YouTube Music"
    assert app.startup_wm_class == "crx_abc123"
    assert app.build_command() == (
        "/opt/google/chrome/google-chrome",
        "--profile-directory=Default",
        "--app-id=abc123",
    )


def test_desktop_app_launcher_finds_app_by_name_in_search_dir(tmp_path):
    _write_desktop_file(
        tmp_path,
        "youtube-music.desktop",
        """
[Desktop Entry]
Type=Application
Name=YouTube Music
Exec=/usr/bin/ytmusic
""".strip(),
    )
    launcher = DesktopAppLauncher(search_dirs=(tmp_path,))

    result = launcher.launch("youtube music", dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.command == ("/usr/bin/ytmusic",)


def test_expand_exec_template_replaces_url_field_codes():
    command = expand_exec_template(
        "/usr/bin/google-chrome-stable %U",
        args=("https://example.com",),
    )

    assert command == ("/usr/bin/google-chrome-stable", "https://example.com")
