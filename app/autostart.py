from __future__ import annotations

import os
import sys
from pathlib import Path

from . import log

APP_NAME = "Centurio"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{exe}" --hidden'
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if script:
        return f'"{exe}" "{script}" --hidden'
    return f'"{exe}" --hidden'


def startup_shortcut() -> Path | None:
    """Path of the installer's optional "launch at login" shortcut."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / "Startup" / f"{APP_NAME}.lnk")


def remove_startup_shortcut() -> bool:
    """Drop the installer's shortcut. True if one was actually removed."""
    path = startup_shortcut()
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        log.exception("removing the startup shortcut failed: %s", path)
        return False


def _run_key_set() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        log.exception("reading the autostart registry value failed")
        return False


def is_enabled() -> bool:
    """True when Windows starts Centurio at login by *either* mechanism."""
    if os.name != "nt":
        return False
    if _run_key_set():
        return True
    path = startup_shortcut()
    return bool(path and path.exists())


def set_autostart(enabled: bool) -> bool:
    """Apply the preference, leaving the Run key as the only mechanism.

    The installer's Startup shortcut is always removed: keeping both would
    start two copies of Centurio at login, and the shortcut is invisible to
    the in-app toggle.
    """
    if os.name != "nt":
        return False
    remove_startup_shortcut()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        log.exception("set_autostart failed")
        return False


def sync(preference: bool) -> bool:
    """Reconcile the stored preference with what Windows actually does.

    Ticking "launch at login" in the installer left a Startup shortcut the app
    never knew about: the toggle read "off" while Centurio kept starting
    itself, and turning the toggle on and off again didn't stop it. Adopt that
    as an explicit "on" once, then apply it through the Run key alone. Returns
    the effective preference for the caller to store back.
    """
    if os.name != "nt":
        return bool(preference)
    effective = bool(preference) or is_enabled()
    set_autostart(effective)
    return effective
