from __future__ import annotations

import os
import sys
from pathlib import Path

import flet as ft

from app import autostart
from app.hotkeys import HotkeyManager, quick_bindings
from app.iconify import ensure_icons
from app.launcher import Launcher
from app.store import Store
from app.tray import TrayController
from app.ui import CenturioUI

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def main(page: ft.Page):
    icon_path = ensure_icons(ASSETS_DIR)

    store = Store()

    is_web = page.web or os.environ.get("CENTURIO_WEB") == "1"

    page.title = "Centurio"
    page.bgcolor = "#0b0b0d"
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK

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

    hotkeys = HotkeyManager(on_trigger=lambda app_id: ui_holder["ui"]._launch(app_id))

    def refresh_runtime():
        apps = store.state()["apps"]
        launcher.set_apps(apps)
        if not is_web:
            hotkeys.register(quick_bindings(apps))

    controllers = {
        "minimize": minimize, "toggle_maximize": toggle_maximize, "close": close,
        "hide_to_tray": hide_to_tray, "on_setting": on_setting,
        "on_library_changed": refresh_runtime,
    }

    ui = CenturioUI(page, store, launcher, controllers)
    ui_holder["ui"] = ui

    launcher.on_change = lambda ids: ui.set_running(ids)

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

    def on_win_event(e):
        if e.data == "close":
            close()
    page.window.on_event = on_win_event if not is_web else None

    ui.mount()

    def _backfill():
        try:
            from app import discovery
            cache = str(Path(app_paths_dir(store)))
            if discovery.backfill_icons(store, cache):
                ui.refresh()
        except Exception:
            pass
    import threading
    threading.Thread(target=_backfill, daemon=True).start()

    refresh_runtime()
    launcher.start_monitor()

    if not is_web:
        autostart.set_autostart(store.state()["settings"].get("autostart", False))
        tray.start()
        if "--hidden" in sys.argv:
            _hide_window(page)


def app_paths_dir(store):
    return Path(store.path).parent / "icons"


def _show_window(page):
    try:
        page.window.visible = True
        page.window.minimized = False
        page.update()
    except Exception:
        pass
    try:
        page.window.to_front()
        page.window.focused = True
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


if __name__ == "__main__":
    web = os.environ.get("CENTURIO_WEB") == "1"
    port = int(os.environ.get("CENTURIO_PORT", "0") or 0)
    if web:
        ft.app(target=main, view=None, port=port or 8550, assets_dir=str(ASSETS_DIR))
    else:
        ft.app(target=main, assets_dir=str(ASSETS_DIR))
