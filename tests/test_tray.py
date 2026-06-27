from eclipse_agent import main as main_module
from eclipse_agent.killswitch import KillSwitch
from eclipse_agent.tray import (
    fetch_status,
    make_icon_image,
    poll_state,
    resolve_state,
    status_color,
    status_label,
)


# --- status mapping ------------------------------------------------------


def test_status_color_and_label_per_state():
    for state in ("idle", "listening", "thinking", "speaking", "paused", "offline"):
        assert isinstance(status_color(state), tuple)
        assert "Eclipse" in status_label(state)


def test_unknown_state_maps_to_offline():
    assert status_color("bogus") == status_color("offline")
    assert status_label("bogus") == status_label("offline")


# --- fetch / resolve -----------------------------------------------------


def test_fetch_status_parses_json():
    assert fetch_status(opener=lambda _url: '{"status": "listening"}') == "listening"


def test_fetch_status_offline_when_unreachable():
    def boom(_url):
        raise OSError("connection refused")

    assert fetch_status(opener=boom) == "offline"


def test_resolve_state_paused_overrides():
    assert resolve_state("listening", killed=True) == "paused"
    assert resolve_state("listening", killed=False) == "listening"
    assert resolve_state("", killed=False) == "offline"


def test_poll_state_reflects_kill_switch(tmp_path):
    switch = KillSwitch(tmp_path / "k.flag")

    def opener(_url):
        return '{"status": "thinking"}'

    assert poll_state(status_opener=opener, kill_switch=switch) == "thinking"
    switch.engage()
    assert poll_state(status_opener=opener, kill_switch=switch) == "paused"


# --- icon image ----------------------------------------------------------


def test_make_icon_image_is_rgba_with_colored_center():
    image = make_icon_image((255, 0, 0))
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getpixel((32, 32)) == (255, 0, 0, 255)
    assert image.getpixel((0, 0))[3] == 0  # transparent corner


# --- CLI -----------------------------------------------------------------


def test_cli_tray_invokes_run_tray(monkeypatch):
    called = []
    monkeypatch.setattr(main_module, "run_tray", lambda: called.append(True))

    assert main_module.main(["tray"]) == 0
    assert called == [True]
