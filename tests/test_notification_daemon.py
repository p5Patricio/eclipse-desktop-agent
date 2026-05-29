from eclipse_agent.notification_daemon import DBusNotificationDaemon, iter_dbus_notify_blocks
from eclipse_agent.notifications import NotificationCenter, NotificationStore


def _notify_block(summary: str = "Instagram") -> str:
    header = (
        "method call time=1710000000.1 sender=:1.42 -> destination=:1.99 serial=7 "
        "path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; "
        "member=Notify"
    )
    return f"""
{header}
   string "Google Chrome"
   uint32 0
   string "chrome"
   string "{summary}"
   string "Nuevo mensaje"
   array [
   ]
   array [
      dict entry(
         string "desktop-entry"
         variant             string "google-chrome"
      )
   ]
   int32 -1
"""


def test_iter_dbus_notify_blocks_ignores_non_notify_messages():
    lines = (
        "signal time=1 sender=:1.1 path=/x; interface=other; member=Changed\n",
        *_notify_block().splitlines(keepends=True),
        "signal time=2 sender=:1.2 path=/x; interface=other; member=Changed\n",
    )

    blocks = iter_dbus_notify_blocks(lines)

    assert len(blocks) == 1
    assert "member=Notify" in blocks[0]


def test_dbus_daemon_process_lines_ingests_notifications(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    daemon = DBusNotificationDaemon(center=NotificationCenter(store=store))

    result = daemon.process_lines(_notify_block("Instagram").splitlines(keepends=True))

    assert result.success is True
    assert result.processed == 1
    assert store.list_events()[0].display_source == "Instagram"


def test_dbus_daemon_dry_run_uses_timeout_command():
    result = DBusNotificationDaemon().run(seconds=5, dry_run=True)

    assert result.command[:2] == ("timeout", "5s")
    assert "dbus-monitor" in result.command
