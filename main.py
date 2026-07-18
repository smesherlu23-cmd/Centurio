"""Centurio — personal, always-in-the-tray hot panel of applications.

Entry point. Wires the Flet window (frameless, custom title bar), the system
tray, autostart, and the library UI together.

Run desktop:  python main.py
Run preview:  CENTURIO_WEB=1 python main.py   (serves the UI in a browser)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft

from app import autostart
from app.iconify import ensure_icons
from app.launcher import Launcher
from app.store import Store
from app.tray import TrayController
from app.ui import CenturioUI

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def main(page: ft.Page):
    icon_path = ensure_icons(ASSETS_DIR)

    store = Store()
    _seed_if_requested(store)

    is_web = page.web or os.environ.get("CENTURIO_WEB") == "1"

    # Window chrome (desktop only).
    page.title = "Centurio"
    page.bgcolor = "#0b0b0d"
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK
    # Bundled fonts keep the app self-contained (design uses Inter + a mono face)
    # and make text render identically everywhere, without touching system fonts.
    page.fonts = {
        "Inter": "fonts/Inter-Regular.ttf",
        "Inter SemiBold": "fonts/Inter-SemiBold.ttf",
        "Inter Bold": "fonts/Inter-Bold.ttf",
        "Inter ExtraBold": "fonts/Inter-ExtraBold.ttf",
        "mono": "fonts/Mono-Regular.ttf",
    }
    page.theme = ft.Theme(color_scheme_seed="#f5f5f7", font_family="Inter")
    if not is_web:
        page.window.title_bar_hidden = True
        page.window.frameless = True
        page.window.width = 1400
        page.window.height = 880
        page.window.min_width = 940
        page.window.min_height = 620
        page.window.center()
        page.window.prevent_close = True

    launcher = Launcher()
    tray = TrayController(icon_path, on_show=lambda: _show_window(page), on_quit=lambda: _quit(page))

    # ---- window controllers passed to the UI ----
    ui_holder = {}

    def minimize():
        if store.state()["settings"].get("minimize_to_tray") and tray.available:
            _hide_window(page)
        else:
            page.window.minimized = True
            page.update()

    def toggle_maximize():
        page.window.maximized = not page.window.maximized
        page.update()

    def close():
        if store.state()["settings"].get("close_to_tray") and tray.available:
            _hide_window(page)
        else:
            _quit(page)

    def hide_to_tray():
        if tray.available:
            _hide_window(page)
        else:
            page.window.minimized = True
            page.update()

    def on_setting(key, value):
        if key == "autostart":
            autostart.set_autostart(bool(value))

    controllers = {
        "minimize": minimize, "toggle_maximize": toggle_maximize, "close": close,
        "hide_to_tray": hide_to_tray, "on_setting": on_setting,
    }

    ui = CenturioUI(page, store, launcher, controllers)
    ui_holder["ui"] = ui

    # Launcher running-state changes repaint the UI (from the watcher thread).
    launcher.on_change = lambda ids: ui.set_running(ids)

    # Keyboard shortcuts (in-app).
    def on_key(e: ft.KeyboardEvent):
        if e.ctrl and e.key.lower() == "k":
            ui.search_field.focus()
        elif e.key == "Escape" and ui.query:
            ui.query = ""
            ui.search_field.value = ""
            ui.refresh()
        elif e.ctrl and e.key.isdigit():
            idx = int(e.key) - 1
            quick = [a for a in store.state()["apps"] if a.get("quick")]
            if 0 <= idx < len(quick):
                ui._launch(quick[idx]["id"])
    page.on_keyboard_event = on_key

    # OS-level window close (frameless still emits it via prevent_close).
    def on_win_event(e):
        if e.data == "close":
            close()
    page.window.on_event = on_win_event if not is_web else None

    ui.mount()

    # Apply persisted settings + start tray on desktop.
    if not is_web:
        autostart.set_autostart(store.state()["settings"].get("autostart", False))
        tray.start()
        if "--hidden" in sys.argv:
            _hide_window(page)


def _show_window(page):
    try:
        page.window.visible = True
        page.window.minimized = False
        page.window.to_front()
        page.update()
    except Exception:
        pass


def _hide_window(page):
    try:
        page.window.visible = False
        page.update()
    except Exception:
        pass


def _quit(page):
    try:
        page.window.prevent_close = False
        page.window.destroy()
    except Exception:
        os._exit(0)


def _seed_if_requested(store: Store):
    """Populate a demo library (for preview/screenshots) when asked and empty."""
    if os.environ.get("CENTURIO_SEED") != "1":
        return
    if store.state()["apps"]:
        return
    from app.seed import seed_demo
    seed_demo(store)


if __name__ == "__main__":
    web = os.environ.get("CENTURIO_WEB") == "1"
    port = int(os.environ.get("CENTURIO_PORT", "0") or 0)
    if web:
        ft.app(target=main, view=None, port=port or 8550, assets_dir=str(ASSETS_DIR))
    else:
        ft.app(target=main, assets_dir=str(ASSETS_DIR))
