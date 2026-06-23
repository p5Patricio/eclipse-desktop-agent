import sys
import subprocess
from dataclasses import dataclass
from typing import Any
from eclipse_agent.pal.base import DaemonManager


@dataclass(frozen=True)
class AutostartResult:
    """Result of registering or removing a Windows autostart entry."""

    success: bool
    action: str
    service_name: str
    message: str
    dry_run: bool = False


class WindowsDaemonManager(DaemonManager):
    def register_autostart(self, name: str, exec_path: str) -> Any:
        dry_run = False
        message = ""
        success = False

        if sys.platform != "win32":
            return AutostartResult(
                success=True,
                action="register",
                service_name=name,
                message="Mocked Windows register_autostart (non-Windows platform).",
                dry_run=True,
            )

        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, exec_path)
            winreg.CloseKey(key)
            message = "Registered via HKEY_CURRENT_USER Run key."
            success = True
        except Exception as reg_exc:
            try:
                cmd = ["schtasks", "/create", "/tn", name, "/tr", f'"{exec_path}"', "/sc", "onlogon", "/f"]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    message = "Registered via Task Scheduler (schtasks)."
                    success = True
                else:
                    message = f"Registry failed ({reg_exc}) and schtasks failed ({res.stderr.strip()})."
            except Exception as task_exc:
                message = f"Registry failed ({reg_exc}) and schtasks raised ({task_exc})."

        return AutostartResult(
            success=success,
            action="register",
            service_name=name,
            message=message,
            dry_run=dry_run,
        )

    def remove_autostart(self, name: str) -> Any:
        dry_run = False
        message = ""
        success = False

        if sys.platform != "win32":
            return AutostartResult(
                success=True,
                action="remove",
                service_name=name,
                message="Mocked Windows remove_autostart (non-Windows platform).",
                dry_run=True,
            )

        reg_deleted = False
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
            reg_deleted = True
            message = "Removed from HKEY_CURRENT_USER Run key."
            success = True
        except FileNotFoundError:
            reg_deleted = True
            success = True
            message = "Not found in Run key."
        except Exception as reg_exc:
            message = f"Registry delete failed ({reg_exc})."

        try:
            cmd = ["schtasks", "/delete", "/tn", name, "/f"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                message = "Removed from Task Scheduler (schtasks)." + (" " + message if message else "")
                success = True
            elif not reg_deleted:
                message += f" Schtasks delete failed ({res.stderr.strip()})."
        except Exception as task_exc:
            if not reg_deleted:
                message += f" Schtasks delete raised ({task_exc})."

        return AutostartResult(
            success=success,
            action="remove",
            service_name=name,
            message=message,
            dry_run=dry_run,
        )
