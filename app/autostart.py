"""Start-with-Windows integration.

Writes an ``HKCU\\...\\Run`` registry value so Centurio launches (hidden to the
tray) when the user signs in. Best-effort — it never crashes the app, and on a
non-Windows host (e.g. during tests) it simply does nothing.
"""
from __future__ import annotations

import os
import sys

from . import log

APP_NAME = "Centurio"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    """Best guess at the command that relaunches Centurio (hidden to tray)."""
    exe = sys.executable
    # When frozen (PyInstaller/flet pack) argv[0] is the app itself.
    if getattr(sys, "frozen", False):
        return f'"{exe}" --hidden'
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if script:
        return f'"{exe}" "{script}" --hidden'
    return f'"{exe}" --hidden'


def set_autostart(enabled: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg  # type: ignore

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
