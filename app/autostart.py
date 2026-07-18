"""Start-with-the-OS integration.

On Windows this writes an HKCU ...\\Run registry value. On Linux it drops a
.desktop file in ~/.config/autostart. macOS uses a LaunchAgent plist. All
paths fail soft — autostart is best-effort and never crashes the app.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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
    try:
        if os.name == "nt":
            return _set_windows(enabled)
        if sys.platform == "darwin":
            return _set_macos(enabled)
        return _set_linux(enabled)
    except Exception:
        return False


# ---- Windows ----
def _set_windows(enabled: bool) -> bool:
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


# ---- Linux ----
def _set_linux(enabled: bool) -> bool:
    autostart_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    desktop = autostart_dir / "centurio.desktop"
    if enabled:
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            f"Exec={_launch_command().replace(chr(34), '')}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n",
            encoding="utf-8",
        )
    elif desktop.exists():
        desktop.unlink()
    return True


# ---- macOS ----
def _set_macos(enabled: bool) -> bool:
    agents = Path.home() / "Library" / "LaunchAgents"
    plist = agents / "com.centurio.app.plist"
    if enabled:
        agents.mkdir(parents=True, exist_ok=True)
        exe = sys.executable
        script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
        args = "".join(f"<string>{a}</string>" for a in [exe, script, "--hidden"] if a)
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            '<key>Label</key><string>com.centurio.app</string>'
            f'<key>ProgramArguments</key><array>{args}</array>'
            '<key>RunAtLoad</key><true/></dict></plist>',
            encoding="utf-8",
        )
    elif plist.exists():
        plist.unlink()
    return True
