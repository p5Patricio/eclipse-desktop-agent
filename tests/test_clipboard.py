from eclipse_agent import main as main_module
from eclipse_agent.clipboard import ClipboardResult, WindowsClipboard, render_clipboard_result


def test_render_clipboard_result_shows_status():
    rendered = render_clipboard_result(ClipboardResult(True, "read", "x", "x"))
    assert "Clipboard [ok] read" in rendered


def test_read_returns_clipboard_text():
    result = WindowsClipboard(reader=lambda: "hello world").read()

    assert result.success is True
    assert result.text == "hello world"


def test_read_empty_clipboard():
    result = WindowsClipboard(reader=lambda: "").read()

    assert result.success is True
    assert "empty" in result.message


def test_read_failure_is_reported():
    def boom() -> str:
        raise OSError("clipboard locked")

    result = WindowsClipboard(reader=boom).read()

    assert result.success is False
    assert "Could not read" in result.message


def test_write_copies_text():
    written: list[str] = []
    result = WindowsClipboard(writer=written.append).write("copy me")

    assert result.success is True
    assert written == ["copy me"]


def test_write_rejects_empty_text():
    result = WindowsClipboard(writer=lambda text: None).write("")

    assert result.success is False


def test_cli_clipboard_read(monkeypatch, capsys):
    class FakeClipboard:
        def read(self) -> ClipboardResult:
            return ClipboardResult(True, "read", "hola", "hola")

    monkeypatch.setattr(main_module, "WindowsClipboard", lambda: FakeClipboard())

    code = main_module.main(["clipboard", "--action", "read"])

    assert code == 0
    assert "Clipboard [ok] read: hola" in capsys.readouterr().out
