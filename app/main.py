from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import flet as ft

from app import autostart, log
from app import colors as C
from app.debounce import Debounce
from app.hotkeys import TOGGLE_LAUNCH, HotkeyManager, app_for_accel, quick_bindings
from app.iconify import ensure_icons
from app.launcher import Launcher
from app.store import DEFAULT_LAUNCH_HOTKEY, Store
from app.tray import TrayController
from app.ui import CenturioUI

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Window moves and resizes arrive in bursts; this is how long the last one
# waits before the geometry is written out.
GEOMETRY_FLUSH_DELAY = 0.5

# How often the "Проверять новое раз в 15 минут" setting is acted on.
AUTO_RESCAN_INTERVAL = 900


def shutdown(store=None, tray=None, launcher=None, hotkeys=None, geometry_flush=None,
             toast=None):
    """Release what the app grabbed, in an order that can't lose data.

    The store is flushed first, then the background machinery is told to stop.
    Everything is optional and every step is independently guarded: quitting
    must not be blocked by a tray icon that has already died.
    """
    for label, step in (("flushing the store", getattr(store, "flush", None)),
                        ("cancelling the geometry flush",
                         getattr(geometry_flush, "cancel", None)),
                        ("stopping the toast timer", getattr(toast, "stop", None)),
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
    log.setup(log_dir=Path(store.path).parent,
              debug=log.is_debug() or bool(store.state()["settings"].get("debug_log")))
    log.debug("Centurio starting (argv=%s)", sys.argv)

    icon_path = ensure_icons(ASSETS_DIR)
    is_web = page.web or os.environ.get("CENTURIO_WEB") == "1"
    start_hidden = "--hidden" in sys.argv

    page.title = "Centurio"
    page.bgcolor = C.BG_WINDOW
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
    page.theme = ft.Theme(color_scheme_seed=C.ACCENT, font_family="Inter")

    # «Запуск» is the mode the hotkey opens and the one the app lives in;
    # «Библиотека» is opened on purpose. Starting hidden means the first thing
    # the user will see is the launch surface.
    start_mode = "launch" if start_hidden else "library"

    if not is_web:
        page.window.title_bar_hidden = True
        page.window.frameless = True
        page.window.prevent_close = True

    launcher = Launcher()
    # Bound further down, but named here so quit_app can close over them and
    # still be safe if the tray's "Выход" fires before they exist.
    hotkeys = None
    geometry_flush = None
    ui_holder = {}

    def quit_app():
        ui = ui_holder.get("ui")
        shutdown(store=store, tray=tray, launcher=launcher, hotkeys=hotkeys,
                 geometry_flush=geometry_flush, toast=getattr(ui, "toast", None))
        _quit(page)

    def apply_window(mode: str):
        """Size the window for the mode it is about to show."""
        if is_web:
            return
        try:
            if mode == "launch":
                page.window.maximized = False
                page.window.resizable = False
                page.window.min_width = C.LAUNCH_W
                page.window.min_height = C.LAUNCH_H
                page.window.width = C.LAUNCH_W
                page.window.height = C.LAUNCH_H
                page.window.center()
            else:
                s = store.state()["settings"]
                page.window.resizable = True
                page.window.min_width = C.LIBRARY_MIN_W
                page.window.min_height = C.LIBRARY_MIN_H
                page.window.width = s.get("win_w") or C.LIBRARY_W
                page.window.height = s.get("win_h") or C.LIBRARY_H
                if s.get("win_x") is not None and s.get("win_y") is not None:
                    page.window.left = s["win_x"]
                    page.window.top = s["win_y"]
                else:
                    page.window.center()
                if s.get("win_max"):
                    page.window.maximized = True
            page.update()
        except Exception:
            log.exception("resizing the window for %s mode failed", mode)

    def show_window():
        _show_window(page)
        ui = ui_holder.get("ui")
        if ui is not None and ui.mode == "launch":
            try:
                ui.search_field.focus()
            except Exception:
                log.exception("focusing the search field failed")

    def open_launch():
        ui = ui_holder.get("ui")
        if ui is None:
            return
        if ui.mode != "launch":
            ui.set_mode("launch")
        show_window()

    def toggle_launch():
        """The global hotkey: show «Запуск», or put it away if it is up."""
        ui = ui_holder.get("ui")
        if ui is None:
            return
        visible = True if is_web else bool(page.window.visible)
        if visible and ui.mode == "launch":
            hide_to_tray()
        else:
            open_launch()

    def minimize():
        page.window.minimized = True
        page.update()

    def toggle_maximize():
        page.window.maximized = not page.window.maximized
        page.update()

    def close():
        if store.state()["settings"].get("close_to_tray") and tray.available:
            hide_to_tray()
        else:
            quit_app()

    def hide_to_tray():
        if is_web:
            return
        if tray.available:
            _hide_window(page)
        else:
            page.window.minimized = True
            page.update()

    def on_setting(key, value):
        if key == "autostart":
            autostart.set_autostart(bool(value))
        elif key == "launch_hotkey":
            refresh_runtime()
        elif key == "covers":
            # Turning covers back on is also a "try again" — the CDN circuit
            # breaker may have tripped while the machine was offline.
            if value:
                try:
                    from app import discovery
                    discovery.reset_cdn_state()
                except Exception:
                    log.exception("re-enabling artwork downloads failed")

    def on_hotkey(binding_id):
        if binding_id == TOGGLE_LAUNCH:
            toggle_launch()
            return
        ui = ui_holder.get("ui")
        if ui is not None:
            ui._launch(binding_id)

    hotkeys = HotkeyManager(on_trigger=on_hotkey)

    def refresh_runtime():
        settings = store.state()["settings"]
        apps = store.state()["apps"]
        launcher.set_apps(apps)
        tray.refresh()
        if not is_web:
            bindings = [(settings.get("launch_hotkey") or DEFAULT_LAUNCH_HOTKEY, TOGGLE_LAUNCH)]
            bindings += quick_bindings(apps)
            hotkeys.register(bindings)

    def set_mode(mode):
        apply_window(mode)

    controllers = {
        "minimize": minimize, "toggle_maximize": toggle_maximize, "close": close,
        "hide_to_tray": hide_to_tray, "on_setting": on_setting,
        "on_library_changed": refresh_runtime, "set_mode": set_mode,
    }

    def tray_menu():
        from app import dialogs
        items = [(item["label"], (lambda aid=item["id"]: on_hotkey(aid)))
                 for item in dialogs.tray_items(store)]
        return items, dialogs.library_summary(store)

    tray = TrayController(icon_path, on_show=open_launch, on_quit=quit_app,
                          on_open_library=lambda: _open_library(ui_holder, show_window),
                          menu_provider=tray_menu)

    ui = CenturioUI(page, store, launcher, controllers, mode=start_mode)
    ui_holder["ui"] = ui
    launcher.on_change = lambda ids: ui.set_running(ids)

    def on_key(e: ft.KeyboardEvent):
        try:
            ui.handle_key(e)
        except Exception:
            log.exception("handling a key press failed")
        # pynput's listener doesn't swallow the keystroke, so a focused window
        # sees Ctrl+N as well — handling it here too would launch twice. This
        # is the fallback for when the combo isn't registered globally.
        if e.ctrl and (e.key or "").isdigit():
            accel = f"Ctrl+{e.key}"
            if not hotkeys.handles(accel):
                app_id = app_for_accel(store.state()["apps"], accel)
                if app_id:
                    ui._launch(app_id)
    page.on_keyboard_event = on_key

    def _flush_geometry():
        try:
            store.flush()
        except Exception:
            log.exception("flushing window geometry failed")

    geometry_flush = Debounce(GEOMETRY_FLUSH_DELAY, _flush_geometry)

    def save_window(flush: bool = False):
        # Only the library's geometry is worth remembering: «Запуск» is always
        # the same size, in the middle of the screen.
        if ui.mode != "library":
            return
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

    apply_window(start_mode)
    ui.mount()

    def _backfill():
        try:
            from app import discovery
            cache = str(app_paths_dir(store))
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
                    ui.rescan(silent=True)
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
        if start_hidden:
            _hide_window(page)
    ui.maybe_onboard()


def _open_library(ui_holder, show_window):
    ui = ui_holder.get("ui")
    if ui is None:
        return
    ui._open_library()
    show_window()


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
