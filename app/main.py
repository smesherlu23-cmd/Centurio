from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import flet as ft

from app import autostart, log
from app.debounce import Debounce
from app.hotkeys import HotkeyManager, app_for_accel, quick_bindings
from app.iconify import ensure_icons
from app.launcher import Launcher
from app.store import Store
from app.tray import TrayController
from app.ui import CenturioUI

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Window moves and resizes arrive in bursts; this is how long the last one
# waits before the geometry is written out.
GEOMETRY_FLUSH_DELAY = 0.5

# How often the "Автообновление списка" setting is acted on, when it is on.
AUTO_RESCAN_INTERVAL = 900


def shutdown(store=None, tray=None, launcher=None, hotkeys=None, geometry_flush=None):
    """Release what the app grabbed, in an order that can't lose data.

    The store is flushed first, then the background machinery is told to stop.
    Everything is optional and every step is independently guarded: quitting
    must not be blocked by a tray icon that has already died, and until this
    existed nothing ever called TrayController.stop() or stop_monitor() at all
    — shutdown relied entirely on daemon threads and os._exit.
    """
    for label, step in (("flushing the store", getattr(store, "flush", None)),
                        ("cancelling the geometry flush",
                         getattr(geometry_flush, "cancel", None)),
                        ("stopping the hotkey listener", getattr(hotkeys, "stop", None)),
                        ("stopping the process monitor",
                         getattr(launcher, "stop_monitor", None)),
                        ("stopping the tray icon", getattr(tray, "stop", None))):
        if step is None:
            continue
        try:
            step()
        except Exception:
            log.exception("%s on quit failed", label)


def main(page: ft.Page):
    store = Store()
    log.setup(log_dir=Path(store.path).parent)
    log.debug("Centurio starting (argv=%s)", sys.argv)

    icon_path = ensure_icons(ASSETS_DIR)

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
        s = store.state()["settings"]
        page.window.title_bar_hidden = True
        page.window.frameless = True
        page.window.min_width = 940
        page.window.min_height = 620
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
    # Bound further down, but named here so quit_app can close over them and
    # still be safe if the tray's "Выход" somehow fires before they exist.
    hotkeys = None
    geometry_flush = None

    def quit_app():
        shutdown(store=store, tray=tray, launcher=launcher,
                 hotkeys=hotkeys, geometry_flush=geometry_flush)
        _quit(page)

    tray = TrayController(icon_path, on_show=lambda: _show_window(page), on_quit=quit_app)
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
        # The page keeps receiving key events while a modal dialog is up, and
        # the window behind it acted on every one: arrows moved a selection
        # nobody could see, Enter launched whatever they landed on.
        if ui.dialog_open:
            return
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
            # pynput's listener doesn't swallow the keystroke, so a focused
            # window sees it as well — handling it here too would launch twice.
            # This branch is the fallback for when the combo isn't registered
            # globally (no pynput, web mode, a rejected accelerator).
            accel = f"Ctrl+{key}"
            if not hotkeys.handles(accel):
                app_id = app_for_accel(store.state()["apps"], accel)
                if app_id:
                    ui._launch(app_id)
        elif key in ("Arrow Right", "Arrow Down"):
            ui.move_selection(1)
        elif key in ("Arrow Left", "Arrow Up"):
            ui.move_selection(-1)
        elif key in ("Enter", "Numpad Enter"):
            ui.activate_selected()
    page.on_keyboard_event = on_key

    def _flush_geometry():
        try:
            store.flush()
        except Exception:
            log.exception("flushing window geometry failed")

    geometry_flush = Debounce(GEOMETRY_FLUSH_DELAY, _flush_geometry)

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
        geometry_flush.schedule(immediate=flush)

    def on_win_event(e):
        if e.data in ("resized", "moved", "maximize", "unmaximize"):
            save_window()
        elif e.data == "close":
            save_window(flush=True)
            close()
    page.window.on_event = on_win_event if not is_web else None
    ui.mount()

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
    refresh_runtime()
    launcher.start_monitor()

    def _auto_rescan_loop():
        while True:
            time.sleep(AUTO_RESCAN_INTERVAL)
            try:
                if store.state()["settings"].get("auto_rescan"):
                    ui._rescan(silent=True)
            except Exception:
                log.exception("auto-rescan tick failed")
    threading.Thread(target=_auto_rescan_loop, daemon=True).start()

    if not is_web:
        # The installer's optional "launch at login" shortcut is invisible to
        # the in-app toggle: sync() adopts it as an explicit preference and then
        # leaves the registry key as the only mechanism, so the toggle and
        # Windows can't disagree (and Centurio can't start twice at login).
        want = bool(store.state()["settings"].get("autostart", False))
        effective = autostart.sync(want)
        if effective != want:
            store.set_setting("autostart", effective)
            ui.refresh()
        tray.start()
        if "--hidden" in sys.argv:
            _hide_window(page)


def app_paths_dir(store):
    return Path(store.path).parent / "icons"


def _show_window(page):
    # Both halves are guarded separately and neither is fatal: restoring a
    # window can fail on a disconnected session or a torn-down page, and the
    # tray click that asked for it must not die with a traceback.
    try:
        page.window.visible = True
        page.window.minimized = False
        page.update()
    except Exception:
        log.exception("restoring the window failed")
    try:
        page.window.to_front()
        page.window.focused = True
        page.update()
    except Exception:
        log.exception("bringing the window to the front failed")


def _hide_window(page):
    try:
        page.window.visible = False
        page.update()
    except Exception:
        log.exception("hiding the window failed")


def _quit(page):
    try:
        page.window.prevent_close = False
        page.window.destroy()
    except Exception:
        log.exception("closing the window failed, exiting the hard way")
        os._exit(0)

# The launcher lives in the repository-root main.py — this module only builds
# the page. Running `python app/main.py` never worked anyway (its imports are
# absolute), so a second copy of the ft.app() call here was one more place to
# forget when the startup options change.
