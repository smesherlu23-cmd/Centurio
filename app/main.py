"""Centurio — personal, always-in-the-tray hot panel of applications.

Entry point. Wires the Flet window (frameless, custom title bar), the system
tray, autostart, and the library UI together.

Run desktop:  python main.py
Run preview:  CENTURIO_WEB=1 python main.py   (serves the UI in a browser)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import flet as ft

from app import autostart, log
from app.hotkeys import HotkeyManager, quick_bindings
from app.iconify import ensure_icons
from app.launcher import Launcher
from app.store import Store
from app.tray import TrayController
from app.ui import CenturioUI

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def main(page: ft.Page):
    store = Store()
    log.setup(log_dir=Path(store.path).parent)
    log.debug("Centurio starting (argv=%s)", sys.argv)

    icon_path = ensure_icons(ASSETS_DIR)

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
        s = store.state()["settings"]
        page.window.title_bar_hidden = True
        page.window.frameless = True
        page.window.min_width = 940
        page.window.min_height = 620
        # Restore the last window geometry, else default-size and center.
        page.window.width = s.get("win_w") or 1400
        page.window.height = s.get("win_h") or 880
        if s.get("win_x") is not None and s.get("win_y") is not None:
            page.window.left = s["win_x"]
            page.window.top = s["win_y"]
        else:
            page.window.center()
        if s.get("win_max"):
            page.window.maximized = True
        page.window.prevent_close = True

    launcher = Launcher()

    def quit_app():
        # Make sure any pending debounced write (e.g. window geometry from a
        # resize/move right before quitting) actually reaches disk.
        try:
            store.flush()
        except Exception:
            log.exception("flushing store on quit failed")
        _quit(page)

    tray = TrayController(icon_path, on_show=lambda: _show_window(page), on_quit=quit_app)

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
            quit_app()

    def hide_to_tray():
        if tray.available:
            _hide_window(page)
        else:
            page.window.minimized = True
            page.update()

    def on_setting(key, value):
        if key == "autostart":
            autostart.set_autostart(bool(value))

    # Global hotkeys (best-effort). Trigger runs the app on the hotkey thread.
    hotkeys = HotkeyManager(on_trigger=lambda app_id: ui_holder["ui"]._launch(app_id))

    def refresh_runtime():
        """Re-index processes and re-register hotkeys after the library changes."""
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

    # Launcher running-state changes repaint the UI (from the watcher/monitor thread).
    launcher.on_change = lambda ids: ui.set_running(ids)

    # Keyboard shortcuts (in-app).
    def on_key(e: ft.KeyboardEvent):
        key = e.key
        if e.ctrl and key.lower() == "k":
            ui.search_field.focus()
        elif key == "Escape":
            if ui.query:
                ui.query = ""
                ui.search_field.value = ""
                ui.selected = -1
                ui.refresh()
            elif ui.selected >= 0:
                ui.selected = -1
                ui.refresh()
        elif e.ctrl and key.isdigit():
            idx = int(key) - 1
            quick = [a for a in store.state()["apps"] if a.get("quick")]
            if 0 <= idx < len(quick):
                ui._launch(quick[idx]["id"])
        # Arrow-key navigation over the visible apps; Enter launches the cursor.
        elif key in ("Arrow Right", "Arrow Down"):
            ui.move_selection(1)
        elif key in ("Arrow Left", "Arrow Up"):
            ui.move_selection(-1)
        elif key in ("Enter", "Numpad Enter"):
            ui.activate_selected()
    page.on_keyboard_event = on_key

    # Persist window geometry (best-effort) as the user resizes/moves/maximizes.
    #
    # A resize/move sends many OS events in a row (every pixel of a drag), and
    # each one used to trigger its own synchronous full-JSON write. Instead we
    # update the in-memory settings on every event but only write to disk once
    # the user has been idle for a short moment (debounced), plus always on
    # close/quit so nothing is lost.
    _GEOMETRY_FLUSH_DELAY = 0.5  # seconds of idle time before writing to disk
    geometry_timer_lock = threading.Lock()
    geometry_timer = {"handle": None}

    def _flush_geometry_now():
        with geometry_timer_lock:
            geometry_timer["handle"] = None
        try:
            store.flush()
        except Exception:
            log.exception("flushing window geometry failed")

    def _schedule_geometry_flush(immediate: bool):
        with geometry_timer_lock:
            if geometry_timer["handle"] is not None:
                geometry_timer["handle"].cancel()
                geometry_timer["handle"] = None
            if immediate:
                _flush_geometry_now()
                return
            t = threading.Timer(_GEOMETRY_FLUSH_DELAY, _flush_geometry_now)
            t.daemon = True
            geometry_timer["handle"] = t
            t.start()

    def save_window(flush: bool = False):
        try:
            w, h = page.window.width, page.window.height
            maximized = page.window.maximized
            store.set_setting("win_max", maximized, persist=False)
            if not maximized:
                if w and h:
                    store.set_setting("win_w", int(w), persist=False)
                    store.set_setting("win_h", int(h), persist=False)
                if page.window.left is not None and page.window.top is not None:
                    store.set_setting("win_x", int(page.window.left), persist=False)
                    store.set_setting("win_y", int(page.window.top), persist=False)
        except Exception:
            log.exception("saving window geometry failed")
            return
        _schedule_geometry_flush(immediate=flush)

    # OS-level window events (frameless still emits close via prevent_close).
    def on_win_event(e):
        if e.data in ("resized", "moved", "maximize", "unmaximize"):
            save_window()
        elif e.data == "close":
            save_window(flush=True)
            close()
    page.window.on_event = on_win_event if not is_web else None

    ui.mount()

    # Backfill icons for apps added before icons existed (e.g. Steam games whose
    # art wasn't found yet). When the icon pipeline has been upgraded since the
    # library was last touched, re-resolve existing icons once so already-added
    # apps pick up higher-res extraction / better Steam art. Runs off the UI
    # thread; repaints when done.
    def _backfill():
        try:
            from app import discovery
            cache = str(Path(app_paths_dir(store)))
            schema = store.state()["settings"].get("icon_schema", 0)
            refresh = schema < discovery.ICON_SCHEMA
            if discovery.backfill_icons(store, cache, refresh=refresh):
                ui.refresh()
            if refresh:
                store.set_setting("icon_schema", discovery.ICON_SCHEMA)
        except Exception:
            log.exception("icon backfill failed")
    threading.Thread(target=_backfill, daemon=True).start()

    # Index running processes + register global hotkeys, then keep them live.
    refresh_runtime()
    launcher.start_monitor()

    # Periodic auto-detection of newly installed programs (opt-in setting).
    def _auto_rescan_loop():
        import time as _t
        while True:
            _t.sleep(900)  # every 15 minutes
            try:
                if store.state()["settings"].get("auto_rescan"):
                    ui._rescan(silent=True)
            except Exception:
                log.exception("auto-rescan tick failed")
    threading.Thread(target=_auto_rescan_loop, daemon=True).start()

    # Apply persisted settings + start tray on desktop.
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
