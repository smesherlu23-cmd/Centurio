"""The window: two modes, one control tree, no modal dialogs.

«Запуск» is the compact surface the global hotkey opens — a search box, the
pinned tiles, the sets, and what is open or was open recently. «Библиотека» is
the full window where programs are added, sorted into categories and
configured; editing happens in the inspector on the right, never in a dialog.

Everything both modes draw comes from `colors.py` — no hex literals here.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import flet as ft

from . import colors as C
from . import log
from . import queries
from .format import (T, cat_icon, initials, n_apps, plu_apps, plu_matches,
                     plu_programs, time_ago)
from .hotkeys import quick_accels
from .images import icon_image, img_b64, is_launcher_art
from .store import Store
from .toast import ToastHost
from .view_state import ViewState

# How long a discover_apps() result stays good enough to reuse. Long enough to
# cover "rescan, then open «Найти и добавить»", short enough that a program
# installed meanwhile still shows up.
DISCOVERY_TTL = 120.0


class CenturioUI:
    def __init__(self, page: ft.Page, store: Store, launcher, controllers=None,
                 mode: str = "library"):
        self.page = page
        self.store = store
        self.launcher = launcher
        self.controllers = controllers or {}
        self.running: set[str] = set()
        self.view = ViewState(store, mode=mode)
        # refresh() runs from five places — the UI thread, the process monitor,
        # the rescan worker, the icon backfill and the pynput listener — and
        # they all rebuild the same control tree. The lock serialises a whole
        # pass (snapshot, build, page.update) so two threads can't interleave
        # halves of two different libraries.
        self._refresh_lock = threading.RLock()
        # store.state() deep-copies the whole library. refresh() takes one
        # snapshot and every helper below reads it for the duration of that
        # pass. It lives in thread-local storage: a background refresh must
        # never hand its snapshot to a reader on another thread.
        self._local = threading.local()
        self._settings = self.store.state()["settings"]
        # Recomputed once per refresh: quick_accels() walks the whole library,
        # and every tile asks for the badge it should show.
        self._accels: dict[str, str] = {}

        # Result of the last discover_apps() run, plus what the "Найти и
        # добавить" screen shows while it is still running or after it failed.
        self._discovered = None
        self._discovered_at = 0.0
        self._scan = {"state": "idle", "label": "", "done": 0, "total": 0,
                      "found": 0, "started": 0.0, "errors": []}
        self._scan_lock = threading.Lock()

        self.toast = ToastHost(page)

        self.search_field = ft.TextField(
            value="", hint_text="Что запустить?", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=17, color=C.TEXT_1, hint_style=ft.TextStyle(color=C.TEXT_4, size=17),
            cursor_color=C.TEXT_1, on_change=self._on_query, expand=True, autofocus=True,
        )
        self.lib_search_field = ft.TextField(
            value="", hint_text="Поиск в библиотеке", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=12.5, color=C.TEXT_1, hint_style=ft.TextStyle(color=C.TEXT_4, size=12.5),
            cursor_color=C.TEXT_1, on_change=self._on_lib_query, expand=True,
        )

        # Positioned children of the root Stack: the mode fills the window, the
        # popover and the first-run card sit above it, the toast above both.
        self.body = ft.Container(left=0, top=0, right=0, bottom=0)
        self.popover_layer = ft.Container(visible=False)
        self.onboarding_layer = ft.Container(left=0, top=0, right=0, bottom=0, visible=False)

    # ---- snapshot plumbing ----
    @property
    def _snapshot(self):
        return getattr(self._local, "snapshot", None)

    @_snapshot.setter
    def _snapshot(self, value):
        self._local.snapshot = value

    def state(self):
        return self._snapshot if self._snapshot is not None else self.store.state()

    def categories(self):
        return sorted(self.state()["categories"], key=lambda c: c.get("order", 0))

    def apps(self):
        return self.state()["apps"]

    def sets(self):
        return sorted(self.state()["sets"], key=lambda s: s.get("order", 0))

    def setting(self, key, default=None):
        return self._settings.get(key, default)

    def calm(self) -> bool:
        """«Спокойный вид»: one flag, every technical caption obeys it."""
        return bool(self._settings.get("calm"))

    def accent(self) -> str:
        return self._settings.get("accent") or C.ACCENT

    @property
    def mode(self):
        return self.view.mode

    # ---- lifecycle ----
    def mount(self):
        # A failed save no longer kills the click that caused it, so it has to
        # be said out loud — otherwise the app looks like it saved fine.
        self.store.on_error = self._on_store_error
        root = ft.Stack([self.body, self.popover_layer, self.onboarding_layer,
                         self.toast.control], expand=True)
        self.page.add(root)
        self.refresh()

    def set_running(self, ids):
        self.running = set(ids)
        try:
            self.refresh()
        except Exception:
            log.exception("refreshing after a running-state change failed")

    def refresh(self, content_only: bool = False):
        with self._refresh_lock:
            self._snapshot = self.store.state()
            self._settings = self._snapshot["settings"]
            self._accels = quick_accels(self._snapshot["apps"])
            try:
                self.view.drop_missing(a["id"] for a in self._snapshot["apps"])
                self.body.content = (self._build_launch() if self.view.mode == "launch"
                                     else self._build_library())
                self._render_popover()
                self._render_onboarding()
            finally:
                self._snapshot = None
            self.page.update()

    # ---- small shared pieces ----
    def _hoverable(self, container: ft.Container, normal, hover):
        def on_hover(e):
            container.bgcolor = hover if e.data == "true" else normal
            container.update()
        container.bgcolor = normal
        container.on_hover = on_hover
        return container

    def _caps(self, text):
        return T(text, size=10.5, weight=ft.FontWeight.W_600, color=C.TEXT_4,
                 style=ft.TextStyle(letter_spacing=0.85))

    def _key_chip(self, label, on_click=None):
        chip = ft.Container(
            T(label, size=10.5, color=C.TEXT_3, font_family="monospace"),
            bgcolor=C.BG_TILE, border=ft.border.all(1, C.BORDER),
            border_radius=C.R_CHIP, padding=ft.padding.symmetric(3, 7),
            on_click=(lambda e: on_click()) if on_click else None)
        return chip

    def _toggle(self, value: bool, on_toggle):
        """The one switch in the program: 34×19, knob 14."""
        knob = ft.Container(width=14, height=14, border_radius=7,
                            bgcolor=C.ON_ACCENT if value else C.TEXT_3)
        return ft.Container(
            ft.Row([knob], alignment=ft.MainAxisAlignment.END if value
                   else ft.MainAxisAlignment.START),
            width=34, height=19, border_radius=10, padding=ft.padding.all(2.5),
            bgcolor=self.accent() if value else C.TOGGLE_OFF,
            on_click=lambda e: on_toggle(not value),
            animate=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT))

    def primary_btn(self, label, on_click, icon=None, height=C.H_BTN, expand=False):
        row = [T(label, size=12.5, weight=ft.FontWeight.W_600, color=C.ON_ACCENT)]
        if icon:
            row.insert(0, ft.Icon(icon, size=15, color=C.ON_ACCENT))
        return ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 14), bgcolor=self.accent(),
            border_radius=9, alignment=ft.alignment.center, expand=expand,
            on_click=lambda e: on_click())

    def outline_btn(self, label, on_click, icon=None, danger=False, height=C.H_FIELD):
        color = C.ERR_TEXT if danger else C.TEXT_1
        row = [T(label, size=12.5, weight=ft.FontWeight.W_600 if danger else ft.FontWeight.W_400,
                 color=color)]
        if icon:
            row.insert(0, ft.Icon(icon, size=15, color=C.ERR_TEXT if danger else C.TEXT_3))
        btn = ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 12),
            border=ft.border.all(1, C.ERR_BTN_BORDER if danger else C.BORDER_STRONG),
            border_radius=C.R_BTN, alignment=ft.alignment.center,
            on_click=lambda e: on_click())
        return self._hoverable(btn, None, C.BG_HOVER)

    def link_btn(self, label, on_click):
        """A word with a rule under it — the design's third button weight."""
        return ft.Container(
            T(label, size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT_1),
            border=ft.border.only(bottom=ft.BorderSide(1, C.BORDER_ACTIVE)),
            padding=ft.padding.only(0, 0, 0, 2), on_click=lambda e: on_click())

    # ---- icons ----
    def cat_of(self, app) -> dict | None:
        cid = app.get("category_id")
        return next((c for c in self.categories() if c["id"] == cid), None)

    def cat_glyph_name(self, cat) -> str:
        return (cat or {}).get("icon") or "folder"

    def cat_glyph(self, cat, size=19, color=None):
        """A category's mark. Letters are allowed here — only here."""
        col = color or C.category_color(cat) if cat else C.TEXT_3
        if not cat:
            return ft.Icon(ft.Icons.FOLDER, size=size, color=col)
        if cat.get("icon"):
            return ft.Icon(cat_icon(cat["icon"]), size=size, color=col)
        return T(initials(cat.get("name")), size=size - 2, weight=ft.FontWeight.BOLD, color=col)

    def icon_slot(self, app, size: int, radius: int, glyph: int | None = None):
        """The app's real icon, or a neutral pad with its category's glyph.

        There are no letter placeholders any more: a tile either shows the
        icon extracted from the executable or says "an icon belongs here".
        """
        fit = ft.ImageFit.COVER if is_launcher_art(app) else ft.ImageFit.CONTAIN
        inner = icon_image(app.get("icon"), width=size - 8, height=size - 8, fit=fit)
        if inner is None:
            cat = self.cat_of(app)
            inner = ft.Icon(cat_icon(self.cat_glyph_name(cat)),
                            size=glyph or round(size * 0.46), color=C.GLYPH_PLACEHOLDER)
        return ft.Container(
            inner, width=size, height=size, border_radius=radius, bgcolor=C.BG_SLOT,
            border=ft.border.all(1, C.BORDER_SLOT), alignment=ft.alignment.center,
            clip_behavior=ft.ClipBehavior.HARD_EDGE)

    def running_badge(self, small=False):
        return ft.Container(
            ft.Row([ft.Container(width=5, height=5, border_radius=3, bgcolor=C.OK),
                    T("открыто", size=10, weight=ft.FontWeight.W_600, color=C.BADGE_TEXT)],
                   spacing=5, tight=True),
            bgcolor=C.BADGE_BG, border=ft.border.all(1, C.BADGE_BORDER),
            border_radius=20, padding=ft.padding.symmetric(3, 8))

    # =====================================================================
    # «Запуск»
    # =====================================================================
    def _build_launch(self):
        apps = self.apps()
        rows = queries.launch_rows(apps, self.view.query, self.running, self.categories())
        app_rows = [r for r in rows if r["kind"] == "app"]
        if self.view.hi >= len(app_rows):
            self.view.hi = max(0, len(app_rows) - 1)

        column = [self._launch_header(len(app_rows))]
        if not self.view.query.strip():
            pins = queries.quick_apps(apps)
            if pins:
                column.append(self._launch_pinned(pins, self._accels))
            if self.sets():
                column.append(self._launch_sets())
        column.append(self._launch_list(rows, app_rows))
        if self.setting("hints", True) and not self.calm():
            column.append(self._launch_hints(len(apps)))

        return ft.Container(
            ft.Column(column, spacing=0, expand=True),
            bgcolor=C.BG_WINDOW, border=ft.border.all(1, C.BORDER_WINDOW),
            border_radius=C.R_WINDOW, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def _launch_header(self, matches: int):
        right = (T(f"{matches} {plu_matches(matches)}", size=11.5, color=C.TEXT_4)
                 if self.view.query.strip()
                 else self._key_chip("Esc", on_click=self._hide_window))
        # No drag area here: the whole header is the search box, and wrapping a
        # text field in one costs the click that focuses it.
        return ft.Container(
            ft.Row([ft.Icon(ft.Icons.SEARCH, size=20, color=C.TEXT_3), self.search_field, right],
                   spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=C.LAUNCH_HEAD_H, padding=ft.padding.symmetric(0, 20),
            border=ft.border.only(bottom=ft.BorderSide(1, C.BG_HOVER)))

    def _launch_pinned(self, pins, accels):
        tiles = []
        for index, app in enumerate(pins[:9]):
            accel = accels.get(app["id"])
            layers = [ft.Column([
                self.icon_slot(app, 52, 15, glyph=24),
                T(app["name"], size=11, color=C.TEXT_2, width=76, max_lines=1,
                  text_align=ft.TextAlign.CENTER, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=7, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)]
            if accel and not self.calm():
                # The badge shows the accelerator the listener actually holds,
                # never a number the tile made up.
                layers.append(ft.Container(
                    T(accel.split("+")[-1], size=9.5, color=C.TEXT_3, font_family="monospace"),
                    right=8, top=-2, bgcolor=C.BG_HOVER, border=ft.border.all(1, C.BORDER_STRONG),
                    border_radius=4, padding=ft.padding.symmetric(1, 4)))
            tiles.append(ft.Container(ft.Stack(layers, width=76, height=82),
                                      on_click=lambda e, i=app["id"]: self._launch(i),
                                      tooltip=None if self.calm() else app["name"]))
        return ft.Container(
            ft.Column([self._caps("ЗАКРЕПЛЕНО"), ft.Row(tiles, spacing=10, wrap=True)],
                      spacing=10),
            padding=ft.padding.only(20, 16, 20, 4))

    def _launch_sets(self):
        chips = []
        for s in self.sets():
            count = len(s["apps"])
            chips.append(ft.Container(
                ft.Row([ft.Icon(ft.Icons.LAYERS, size=16, color=C.TEXT_3),
                        T(s["name"], size=13, color=C.TEXT_1),
                        T("" if self.calm() else f"{count} {plu_programs(count)}",
                          size=11.5, color=C.TEXT_4)],
                       spacing=10, tight=True),
                bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER), border_radius=11,
                padding=ft.padding.symmetric(8, 12),
                on_click=lambda e, sid=s["id"]: self._launch_set(sid),
                tooltip="Запустить набор"))
        return ft.Container(
            ft.Column([self._caps("НАБОРЫ"), ft.Row(chips, spacing=10, wrap=True)], spacing=8),
            padding=ft.padding.only(20, 14, 20, 0))

    def _launch_list(self, rows, app_rows):
        if not rows:
            body = (self._launch_empty() if self.view.query.strip()
                    else self._launch_nothing_yet())
            return ft.Container(body, expand=True, padding=ft.padding.only(20, 14, 20, 10))
        controls = []
        for row in rows:
            if row["kind"] == "head":
                controls.append(ft.Container(self._caps(row["title"]),
                                             padding=ft.padding.only(12, 8, 0, 4)))
            else:
                controls.append(self._launch_row(row, row["index"] == self.view.hi))
        return ft.Container(
            ft.Column(controls, spacing=2, scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True, padding=ft.padding.only(20, 14, 20, 10))

    def _launch_row(self, row, active: bool):
        app = row["app"]
        running = app["id"] in self.running
        controls = [self.icon_slot(app, 32, 9, glyph=17)]

        name = T(spans=[
            ft.TextSpan(text, ft.TextStyle(bgcolor=C.BG_MATCH) if hit else None)
            for text, hit in queries.match_spans(app["name"], self.view.query)
        ], size=14, color=C.TEXT_1, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        lines = [name]
        if not self.calm():
            bits = [row["cat"]] if row["cat"] else []
            bits.append("сейчас открыто" if running else (time_ago(app.get("last_launched"))
                                                          or "ещё не запускалось"))
            lines.append(T(" · ".join(b for b in bits if b), size=11, color=C.TEXT_4,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        controls.append(ft.Column(lines, spacing=2, expand=True, tight=True))

        if running:
            controls += [ft.Container(width=5, height=5, border_radius=3, bgcolor=C.OK),
                         T("открыто", size=11.5, color=C.OK_TEXT)]
        if active:
            controls.append(ft.Container(
                T("Настроить", size=11.5, color=C.TEXT_3),
                border=ft.border.all(1, C.BORDER_STRONG), border_radius=7,
                padding=ft.padding.symmetric(4, 9),
                on_click=lambda e, i=app["id"]: self._tune(i)))
            controls.append(ft.Container(
                T("Переключиться" if running else "Открыть", size=11.5,
                  weight=ft.FontWeight.W_600, color=C.ON_ACCENT),
                bgcolor=self.accent(), border_radius=7, padding=ft.padding.symmetric(5, 10),
                on_click=lambda e, i=app["id"]: self._launch(i)))

        container = ft.Container(
            ft.Row(controls, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(0, 12), border_radius=C.R_ROW,
            bgcolor=C.BG_ROW_ACTIVE if active else None,
            border=ft.border.all(1, C.BORDER_ACTIVE) if active else None,
            height=48, on_click=lambda e, i=app["id"]: self._launch(i))
        # Hovering moves the keyboard selection too, so mouse and keyboard
        # never disagree about which row Enter would run.
        container.on_hover = lambda e, i=row["index"]: self._hover_row(i, e)
        return container

    def _launch_empty(self):
        query = self.view.query.strip()
        return ft.Column([
            T(f"По запросу «{query}» ничего нет", size=15, weight=ft.FontWeight.W_600,
              color=C.TEXT_1),
            T("В библиотеке ничего похожего нет. Можно поискать среди установленных программ.",
              size=12.5, color=C.TEXT_3),
            ft.Container(ft.Row([
                self.primary_btn("Искать в системе", self._open_add),
                self.outline_btn("Сбросить", self._clear_query, height=C.H_BTN),
            ], spacing=8), padding=ft.padding.only(0, 4, 0, 0)),
        ], spacing=10, tight=True)

    def _launch_nothing_yet(self):
        return ft.Column([
            T("Здесь будет ваша библиотека", size=15, weight=ft.FontWeight.W_600, color=C.TEXT_1),
            T("Centurio может посмотреть, что установлено, и предложить отметить нужное.",
              size=12.5, color=C.TEXT_3),
            ft.Container(ft.Row([
                self.primary_btn("Показать найденное", self._open_add),
                self.outline_btn("Библиотека", self._open_library, height=C.H_BTN),
            ], spacing=8), padding=ft.padding.only(0, 4, 0, 0)),
        ], spacing=10, tight=True)

    def _launch_hints(self, total: int):
        def hint(key, label, on_click=None):
            return ft.Container(ft.Row([self._key_chip(key), T(label, size=11.5, color=C.TEXT_4)],
                                       spacing=6, tight=True),
                                on_click=(lambda e: on_click()) if on_click else None)
        return ft.Container(
            ft.Row([hint("↑↓", "выбрать"), hint("Enter", "запустить"),
                    hint("Ctrl+L", "библиотека", self._open_library),
                    ft.Container(expand=True),
                    T(n_apps(total), size=11.5, color=C.TEXT_6)],
                   spacing=18, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=C.LAUNCH_HINTS_H, padding=ft.padding.symmetric(0, 20), bgcolor=C.BG_PANEL,
            border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER)))

    # =====================================================================
    # «Библиотека»
    # =====================================================================
    def _build_library(self):
        body = [self.rail(), self.center()]
        if self.view.inspector and self.view.screen == "grid":
            inspector = self.inspector()
            if inspector is not None:
                body.append(inspector)
        return ft.Container(
            ft.Column([self.titlebar(), ft.Row(body, spacing=0, expand=True)],
                      spacing=0, expand=True),
            bgcolor=C.BG_WINDOW, border=ft.border.all(1, C.BORDER_WINDOW),
            border_radius=C.R_CARD, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def titlebar(self):
        def segment(label, active, on_click):
            return ft.Container(
                T(label, size=12, weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
                  color=C.TEXT_1 if active else C.TEXT_3),
                height=26, padding=ft.padding.symmetric(0, 12), border_radius=6,
                bgcolor=C.BG_ACTIVE if active else None, alignment=ft.alignment.center,
                on_click=None if active else (lambda e: on_click()))

        switch = ft.Container(
            ft.Row([segment("Запуск", False, self._open_launch),
                    segment("Библиотека", True, lambda: None)], spacing=0),
            bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER), border_radius=C.R_BTN,
            padding=ft.padding.all(2))

        drag = ft.WindowDragArea(
            ft.Container(ft.Row([T("Centurio", size=13.5, weight=ft.FontWeight.BOLD,
                                   color=C.TEXT_1), switch], spacing=16),
                         padding=ft.padding.only(18, 0, 0, 0),
                         alignment=ft.alignment.center_left, expand=True),
            expand=True)
        buttons = ft.Row([
            self._win_btn(ft.Icons.REMOVE, "Свернуть", self._call("minimize")),
            self._win_btn(ft.Icons.CROP_SQUARE, "Развернуть", self._call("toggle_maximize")),
            self._win_btn(ft.Icons.CLOSE, "Закрыть", self._call("close"), danger=True),
        ], spacing=0)
        return ft.Container(
            ft.Row([drag, buttons], spacing=0),
            height=C.TITLEBAR_H, padding=ft.padding.only(0, 0, 10, 0),
            border=ft.border.only(bottom=ft.BorderSide(1, C.BG_HOVER)))

    def _win_btn(self, icon_name, tooltip, handler, danger=False):
        btn = ft.Container(ft.Icon(icon_name, size=14, color=C.TEXT_3),
                           width=40, height=30, border_radius=6,
                           alignment=ft.alignment.center, tooltip=tooltip,
                           on_click=lambda e: handler())

        def on_hover(e):
            over = e.data == "true"
            btn.bgcolor = (C.ERR if danger else C.BG_HOVER) if over else None
            btn.content.color = (C.WHITE if danger else C.TEXT_1) if over else C.TEXT_3
            btn.update()
        btn.on_hover = on_hover
        return btn

    # ---- рельс ----
    def rail(self):
        apps = self.apps()
        counts = {}
        for a in apps:
            counts[a.get("category_id")] = counts.get(a.get("category_id"), 0) + 1

        totals = {
            "all": len(apps),
            "favorites": sum(1 for a in apps if a.get("favorite")),
            "running": len(self.running),
            "pinned": sum(1 for a in apps if a.get("quick")),
        }
        glyphs = {"all": ft.Icons.APPS, "favorites": ft.Icons.STAR_BORDER,
                  "running": ft.Icons.CIRCLE, "pinned": ft.Icons.BOLT}

        items = []
        for key in queries.FIXED_FILTERS:
            active = self.view.filter == key
            items.append(self._rail_item(
                ft.Icon(glyphs[key], size=19 if key != "running" else 11,
                        color=C.TEXT_1 if active else C.TEXT_3),
                active=active, bar_color=C.ACCENT, bg_when_idle=None,
                tooltip=self._rail_tip(queries.FILTER_TITLES[key], totals[key]),
                on_click=lambda k=key: self._set_filter(k)))

        items.append(ft.Container(width=32, height=1, bgcolor=C.BG_HOVER,
                                  margin=ft.margin.symmetric(2, 0)))

        cats = self.categories()
        for index, cat in enumerate(cats):
            active = self.view.filter == f"category:{cat['id']}"
            items.append(self._rail_category(cat, index, active,
                                             counts.get(cat["id"], 0)))

        items.append(ft.Container(
            ft.Icon(ft.Icons.ADD, size=16, color=C.TEXT_4),
            width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=C.R_CARD,
            border=ft.border.all(1.5, C.BORDER_STRONG), alignment=ft.alignment.center,
            on_click=lambda e: self._add_category(), tooltip="Новая категория"))
        items.append(ft.Container(expand=True))
        items.append(ft.Container(
            ft.Icon(ft.Icons.SETTINGS, size=18, color=C.TEXT_3),
            width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=C.R_CARD,
            alignment=ft.alignment.center, on_click=lambda e: self._open_settings(),
            tooltip="Настройки"))

        return ft.Container(
            ft.Column(items, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      expand=True),
            width=C.RAIL_W, bgcolor=C.BG_RAIL, padding=ft.padding.only(0, 14, 0, 12),
            border=ft.border.only(right=ft.BorderSide(1, C.BG_HOVER)))

    def _rail_tip(self, label, count, active=False):
        tip = label if self.calm() else f"{label} · {count}"
        return f"{tip} — ещё раз, чтобы настроить" if active else tip

    def _rail_item(self, glyph, active, bar_color, bg_when_idle, tooltip, on_click,
                   button=None):
        inner = button or ft.Container(
            glyph, width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=C.R_CARD,
            bgcolor=C.BG_ACTIVE if active else bg_when_idle,
            alignment=ft.alignment.center, tooltip=tooltip,
            on_click=lambda e: on_click(),
            animate=ft.Animation(C.ANIM_HOVER, ft.AnimationCurve.EASE_OUT))
        if not active and button is None:
            base = bg_when_idle

            def on_hover(e):
                inner.bgcolor = C.BG_HOVER if e.data == "true" else base
                inner.update()
            inner.on_hover = on_hover
        bar = ft.Container(width=C.RAIL_BAR_W, height=C.RAIL_BAR_H,
                           border_radius=ft.border_radius.only(0, 3, 0, 3),
                           bgcolor=bar_color if active else None)
        return ft.Row([bar, ft.Container(inner, expand=True, alignment=ft.alignment.center)],
                      spacing=0, width=C.RAIL_W)

    def _rail_category(self, cat, index, active, count):
        color = C.category_color(cat)
        button = ft.Container(
            self.cat_glyph(cat, size=19, color=C.WHITE),
            width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=C.R_CARD, bgcolor=C.BG_TILE,
            border=ft.border.all(1.5, C.ACCENT) if active else None,
            alignment=ft.alignment.center, tooltip=self._rail_tip(cat["name"], count, active),
            animate=ft.Animation(C.ANIM_HOVER, ft.AnimationCurve.EASE_OUT))

        gesture = ft.GestureDetector(
            button, mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, cid=cat["id"]: self._tap_category(cid, active),
            on_secondary_tap=lambda e, cid=cat["id"]: self._open_popover(cid),
            on_double_tap=lambda e, cid=cat["id"]: self._open_popover(cid))

        def accept(e):
            src = self.page.get_control(e.src_id)
            payload = getattr(src, "data", None) if src is not None else None
            button.border = ft.border.all(1.5, C.ACCENT) if active else None
            button.bgcolor = C.BG_TILE
            button.update()
            if isinstance(payload, dict) and payload.get("kind") == "category":
                self._reorder_category(payload["id"], index)
            elif isinstance(payload, dict) and payload.get("kind") == "apps":
                self._move_apps_to_category(payload["ids"], cat["id"])

        def will_accept(e):
            button.bgcolor = C.BG_HOVER
            button.border = ft.border.all(1.5, C.BORDER_DRAG)
            button.update()

        def leave(e):
            button.bgcolor = C.BG_TILE
            button.border = ft.border.all(1.5, C.ACCENT) if active else None
            button.update()

        target = ft.DragTarget(group="library", content=gesture, on_accept=accept,
                               on_will_accept=will_accept, on_leave=leave)
        draggable = ft.Draggable(group="library", content=target,
                                 data={"kind": "category", "id": cat["id"]})
        return self._rail_item(None, active, color, C.BG_TILE, cat["name"],
                               lambda: None, button=draggable)

    # ---- центр ----
    def center(self):
        from . import dialogs
        if self.view.screen == "add":
            content = dialogs.build_add_screen(self)
        elif self.view.screen == "settings":
            content = dialogs.build_settings_screen(self)
        else:
            content = self._grid()
        return ft.Container(content, expand=True)

    def _grid(self):
        apps = self.apps()
        visible = queries.visible_apps(apps, self.view.filter, self.view.lib_query, self.running)
        sections = queries.build_sections(apps, self.categories(), self.view.filter,
                                          self.view.lib_query, self.running)
        body = ([self._grid_group(sec) for sec in sections] if visible
                else [self._grid_empty()])
        scroller = ft.Column(body, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        layers = [ft.Container(
            ft.Column([self._grid_header(visible), ft.Container(
                scroller, expand=True, padding=ft.padding.only(22, 0, 22, 22))],
                spacing=0, expand=True),
            left=0, top=0, right=0, bottom=0)]
        if len(self.view.sel) > 1:
            layers.append(ft.Container(self._bulk_bar(), left=0, right=0, bottom=16))
        return ft.Stack(layers, expand=True)

    def _grid_header(self, visible):
        title = queries.current_title(self.view.filter, self.categories())
        if self.view.lib_query.strip():
            title = "Поиск"
        heading = [T(title, size=19, weight=ft.FontWeight.BOLD, color=C.TEXT_1)]
        if not self.calm():
            open_now = sum(1 for a in visible if a["id"] in self.running)
            sub = n_apps(len(visible))
            if open_now:
                sub += f", из них {open_now} открыто"
            heading.append(T(sub, size=11.5, color=C.TEXT_4))

        search = ft.Container(
            ft.Row([ft.Icon(ft.Icons.SEARCH, size=14, color=C.TEXT_4), self.lib_search_field]
                   + ([] if self.calm() else [self._key_chip("Ctrl+K")]), spacing=8,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            width=240, height=C.H_BTN, bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER),
            border_radius=C.R_BTN, padding=ft.padding.only(10, 0, 6, 0))

        return ft.Container(
            ft.Row([ft.Column(heading, spacing=3, tight=True), ft.Container(expand=True), search,
                    self.primary_btn("Найти и добавить", self._open_add, ft.Icons.SEARCH)],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(22, 18, 22, 12))

    def _grid_group(self, sec):
        cat = sec["cat"]
        head = [self.cat_glyph(cat, size=15) if cat
                else ft.Icon(ft.Icons.FOLDER, size=15, color=C.TEXT_4),
                T(sec["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT_2)]
        if not self.calm():
            head.append(T(str(len(sec["apps"])), size=11, color=C.TEXT_6,
                          font_family="monospace"))
        head.append(ft.Container(height=1, bgcolor=C.BG_HOVER, expand=True))
        ids = [a["id"] for a in sec["apps"]]
        tiles = [self._tile(a) for a in sec["apps"]]
        return ft.Container(
            ft.Column([
                ft.Container(ft.Row(head, spacing=10,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.only(0, 8, 0, 0),
                            tooltip="Выбрать всю группу",
                            on_click=lambda e, g=ids: self._select_group(g)),
                ft.Row(tiles, spacing=14, run_spacing=14, wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.START),
            ], spacing=12), padding=ft.padding.only(0, 0, 0, 14))

    def _select_group(self, ids):
        self.view.add_many(ids)
        self.refresh()

    def _use_poster(self, app) -> bool:
        return bool(self.setting("game_posters", True) and is_launcher_art(app)
                    and img_b64(app.get("poster")))

    def _tile(self, app):
        compact = self.setting("tile_size") == "compact"
        selected = app["id"] in self.view.sel
        card = (self._poster_tile(app, compact, selected) if self._use_poster(app)
                else self._icon_tile(app, compact, selected))
        gesture = ft.GestureDetector(
            card, mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e, i=app["id"]: self._select_tile(i),
            on_double_tap=lambda e, i=app["id"]: self._launch(i))
        return ft.Draggable(group="library", content=gesture,
                            data={"kind": "apps", "ids": self._drag_ids(app["id"])})

    def _pick_box(self, app, selected):
        """The corner check that builds a multi-selection.

        Flet's tap events carry no keyboard modifiers, so Ctrl+click can't be
        told from a plain click. The check is that affordance made visible: the
        tile body selects one, this adds and removes. It only appears once
        something is selected — an idle grid stays as clean as the mockup.
        """
        if not self.view.sel:
            return None
        icon = ft.Icons.CHECK if selected else ft.Icons.ADD
        return ft.Container(
            ft.Icon(icon, size=14, color=C.ON_ACCENT if selected else C.TEXT_2),
            width=20, height=20, border_radius=6,
            bgcolor=self.accent() if selected else C.SCRIM,
            border=None if selected else ft.border.all(1, C.BORDER_STRONG),
            alignment=ft.alignment.center,
            tooltip="Убрать из выбора" if selected else "Добавить к выбору",
            on_click=lambda e, i=app["id"]: self._toggle_tile(i))

    def _star(self, app, size=15, background=False):
        """Favourite toggle. Over a poster it needs its own dark disc to read."""
        favorite = bool(app.get("favorite"))
        idle = C.WHITE if background else C.TEXT_6
        star = ft.Icon(ft.Icons.STAR if favorite else ft.Icons.STAR_BORDER, size=size,
                       color=C.STAR if favorite else idle)
        extras = dict(width=26, height=26, border_radius=8, bgcolor=C.SCRIM,
                      alignment=ft.alignment.center) if background else {}
        return ft.Container(star, tooltip="В избранное",
                            on_click=lambda e, i=app["id"]: self._toggle_fav(i), **extras)

    def _tile_meta(self, app, accels) -> str:
        if self.calm():
            return ""
        accel = accels.get(app["id"])
        if accel:
            return accel
        return (app.get("sub") or "").strip()

    def _icon_tile(self, app, compact, selected):
        width = C.TILE_W_COMPACT if compact else C.TILE_W
        top_h = C.TILE_TOP_H_COMPACT if compact else C.TILE_TOP_H
        slot = C.TILE_SLOT_COMPACT if compact else C.TILE_SLOT

        top_layers = [ft.Container(
            self.icon_slot(app, slot, C.R_WINDOW, glyph=round(slot * 0.47)),
            expand=True, alignment=ft.alignment.center,
            gradient=ft.LinearGradient(begin=ft.alignment.top_left,
                                       end=ft.alignment.bottom_right,
                                       colors=list(C.TILE_GRADIENT)))]
        if app["id"] in self.running:
            top_layers.append(ft.Container(self.running_badge(), right=8, top=8))
        pick = self._pick_box(app, selected)
        if pick is not None:
            top_layers.append(ft.Container(pick, left=8, top=8))

        meta = self._tile_meta(app, self._accels)
        lines = [T(app["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT_1,
                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
        if meta:
            lines.append(T(meta, size=10.5, color=C.TEXT_4, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS,
                           font_family="monospace" if meta.startswith("Ctrl") else None))

        card = ft.Container(
            ft.Column([
                ft.Container(ft.Stack(top_layers, expand=True), height=top_h,
                             clip_behavior=ft.ClipBehavior.HARD_EDGE),
                ft.Container(ft.Row([ft.Column(lines, spacing=2, expand=True, tight=True),
                                     self._star(app)], spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                             height=C.TILE_FOOT_H,
                             padding=ft.padding.only(12, 10, 12, 11)),
            ], spacing=0, tight=True),
            width=width, bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER),
            border_radius=C.R_CARD, clip_behavior=ft.ClipBehavior.HARD_EDGE)
        return self._select_frame(card, selected, width, C.R_CARD, hoverable=True)

    def _poster_tile(self, app, compact, selected):
        width = C.POSTER_W_COMPACT if compact else C.POSTER_W
        height = C.POSTER_H_COMPACT if compact else C.POSTER_H
        layers = [ft.Image(src_base64=img_b64(app.get("poster")), width=width, height=height,
                           fit=ft.ImageFit.COVER)]
        layers.append(ft.Container(
            T(app["name"], size=12.5, weight=ft.FontWeight.W_600, color=C.WHITE,
              max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            left=0, right=0, bottom=0, padding=ft.padding.only(10, 20, 10, 9),
            gradient=ft.LinearGradient(begin=ft.alignment.top_center,
                                       end=ft.alignment.bottom_center,
                                       colors=list(C.POSTER_SCRIM))))
        if app["id"] in self.running:
            layers.append(ft.Container(self.running_badge(), left=8, top=36))
        pick = self._pick_box(app, selected)
        if pick is not None:
            layers.append(ft.Container(pick, left=8, top=8))
        layers.append(ft.Container(self._star(app, size=14, background=True), right=8, top=8))
        card = ft.Container(ft.Stack(layers), width=width, height=height, bgcolor=C.BG_CARD,
                            border=ft.border.all(1, C.BORDER), border_radius=12,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE)
        return self._select_frame(card, selected, width, 12, hoverable=True, height=height)

    def _select_frame(self, card, selected, width, radius, hoverable=False, height=None):
        """The selection ring is an overlay, so it never moves the layout."""
        if hoverable:
            def on_hover(e):
                if selected:
                    return
                card.border = ft.border.all(1, C.BORDER_ACTIVE if e.data == "true" else C.BORDER)
                card.update()
            card.on_hover = on_hover
        if not selected:
            return card
        ring = ft.Container(width=width, height=height, border=ft.border.all(2, C.ACCENT),
                            border_radius=radius, left=0, top=0, right=0, bottom=0)
        return ft.Stack([card, ring], width=width, height=height)

    def _grid_empty(self):
        query = self.view.lib_query.strip()
        cats = self.categories()
        if query:
            return self._empty_card(
                f"По запросу «{query}» ничего нет",
                f"В библиотеке {n_apps(len(self.apps()))}, среди них похожего нет. "
                "Можно поискать среди установленных программ.",
                [("Искать в системе", self._open_add, True),
                 ("Сбросить", self._clear_lib_query, False)])
        if not self.apps():
            return self._empty_card(
                "Здесь будет ваша библиотека",
                "Centurio посмотрит, что установлено, и предложит отметить те программы, "
                "которые вы запускаете каждый день.",
                [("Показать найденное", self._open_add, True),
                 ("Выбрать файл", self.pick_file, False)],
                footer="Вызов окна — Ctrl+Пробел, спрятать — Esc")
        if self.view.filter.startswith("category:"):
            cid = self.view.filter.split(":", 1)[1]
            cat = next((c for c in cats if c["id"] == cid), None)
            name = cat["name"] if cat else "категории"
            return self._empty_card(
                f"В «{name}» пока пусто",
                "Перетащите плитки на значок категории слева или выберите несколько "
                "и нажмите «В категорию».",
                [("Показать все", lambda: self._set_filter("all"), False)])
        return self._empty_card(
            "Здесь пока пусто",
            "Ничего не подходит под этот фильтр.",
            [("Найти и добавить", self._open_add, True),
             ("Показать все", lambda: self._set_filter("all"), False)])

    def _empty_card(self, title, text, actions, footer=None):
        buttons = []
        for action in actions:
            label, callback = action[0], action[1]
            primary = action[2] if len(action) > 2 else False
            buttons.append(self.primary_btn(label, callback, height=C.H_BTN_LG) if primary
                           else self.outline_btn(label, callback, height=C.H_BTN_LG))
        column = [T(title, size=16, weight=ft.FontWeight.BOLD, color=C.TEXT_1),
                  T(text, size=12.5, color=C.TEXT_3),
                  ft.Container(ft.Row(buttons, spacing=8), padding=ft.padding.only(0, 6, 0, 0))]
        if footer and not self.calm():
            column.append(ft.Container(
                T(footer, size=10.5, color=C.TEXT_6, font_family="monospace"),
                padding=ft.padding.only(0, 14, 0, 0), margin=ft.margin.only(top=6),
                border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER))))
        return ft.Container(ft.Column(column, spacing=10, tight=True), width=440,
                            padding=ft.padding.only(4, 40, 4, 4))

    # ---- групповая полоса ----
    def _bulk_bar(self):
        count = len(self.view.sel)
        cats = self.categories()
        target = self._bulk_target_category(cats)
        buttons = []
        if target:
            buttons.append(self.outline_btn(
                f"В «{target['name']}»", lambda: self._move_apps_to_category(
                    list(self.view.sel), target["id"]), ft.Icons.FOLDER))
        buttons += [
            self.outline_btn("В избранное", self._bulk_favorite, ft.Icons.STAR_BORDER),
            self.outline_btn("Собрать набор", self._bulk_make_set, ft.Icons.LAYERS),
            self.outline_btn("Убрать", self._remove_selected, ft.Icons.DELETE_OUTLINE,
                             danger=True),
        ]
        bar = ft.Container(
            ft.Row([T(f"Выбрано {count}", size=13, weight=ft.FontWeight.W_600, color=C.TEXT_1),
                    ft.Container(width=1, height=20, bgcolor=C.BORDER_STRONG,
                                 margin=ft.margin.symmetric(0, 2))] + buttons,
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            height=50, bgcolor=C.BG_HOVER, border=ft.border.all(1, C.BORDER_ACTIVE),
            border_radius=C.R_CARD, padding=ft.padding.only(16, 0, 12, 0),
            shadow=ft.BoxShadow(blur_radius=50, offset=ft.Offset(0, 20), color=C.SHADOW_BAR))
        return ft.Row([bar], alignment=ft.MainAxisAlignment.CENTER)

    def _bulk_target_category(self, cats):
        """Offer the category the selection isn't already in."""
        if not cats:
            return None
        chosen = {a.get("category_id") for a in self.apps() if a["id"] in self.view.sel}
        if self.view.filter.startswith("category:"):
            current = self.view.filter.split(":", 1)[1]
            others = [c for c in cats if c["id"] != current]
            if others:
                return others[0]
        if len(chosen) == 1:
            others = [c for c in cats if c["id"] not in chosen]
            if others:
                return others[0]
        return cats[0]

    # ---- инспектор ----
    def inspector(self):
        app = next((a for a in self.apps() if a["id"] == self.view.inspector), None)
        if app is None:
            return None
        running = app["id"] in self.running
        cat = self.cat_of(app)
        accels = self._accels

        header = [self.icon_slot(app, 42, 12, glyph=21)]
        title_lines = [T(app["name"], size=15, weight=ft.FontWeight.BOLD, color=C.TEXT_1,
                         max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
        if not self.calm() and app.get("path"):
            title_lines.append(T(app["path"], size=10.5, color=C.TEXT_4, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS))
        header.append(ft.Column(title_lines, spacing=4, expand=True, tight=True))
        header.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=18, color=C.TEXT_4),
                                   on_click=lambda e: self._close_inspector()))

        rows = [
            ft.Container(ft.Row(header, spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.START),
                         padding=ft.padding.symmetric(14, 16),
                         border=ft.border.only(bottom=ft.BorderSide(1, C.BG_HOVER))),
            ft.Container(ft.Row([
                self.primary_btn("Переключиться" if running else "Открыть",
                                 lambda: self._launch(app["id"]), ft.Icons.PLAY_ARROW,
                                 expand=True),
                ft.Container(ft.Icon(ft.Icons.STAR if app.get("favorite")
                                     else ft.Icons.STAR_BORDER, size=16,
                                     color=C.STAR if app.get("favorite") else C.TEXT_3),
                             width=38, height=C.H_BTN, border_radius=9,
                             border=ft.border.all(1, C.BORDER_STRONG),
                             alignment=ft.alignment.center,
                             on_click=lambda e: self._toggle_fav(app["id"])),
            ], spacing=8), padding=ft.padding.only(16, 14, 16, 0)),
            ft.Container(ft.Column([
                self._caps("РАЗМЕЩЕНИЕ"),
                self._insp_row("Категория", self._cat_selector(app, cat)),
                self._insp_toggle_row(
                    "Закрепить в «Запуске»",
                    (f"Сейчас это {accels[app['id']]}" if app.get("quick") and accels.get(app["id"])
                     else "Появится в «Запуске» первым" if not app.get("quick")
                     else "Свободных Ctrl+N не осталось"),
                    bool(app.get("quick")), lambda v: self._toggle_pin(app["id"], v)),
                self._insp_row(
                    "Своя горячая клавиша", self._hotkey_field(app),
                    sub="ждём комбинацию" if self.view.capture else "работает из любого окна"),
            ], spacing=12), padding=ft.padding.only(16, 16, 16, 0)),
            self._insp_advanced(app),
            ft.Container(expand=True),
            ft.Container(
                ft.Row([T("" if self.calm() else "сохраняется само", size=10.5, color=C.TEXT_6,
                          expand=True),
                        self.outline_btn("Убрать", lambda: self._remove_apps([app["id"]]),
                                         ft.Icons.DELETE_OUTLINE, danger=True)],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(14, 16),
                border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER))),
        ]
        return ft.Container(
            ft.Column(rows, spacing=0, expand=True),
            width=C.INSPECTOR_W, bgcolor=C.BG_PANEL,
            border=ft.border.only(left=ft.BorderSide(1, C.BG_HOVER)))

    def _insp_row(self, label, control, sub=None):
        left = [T(label, size=12.5, color=C.TEXT_2)]
        if sub and not self.calm():
            left.append(T(sub, size=11, color=C.TEXT_4))
        return ft.Row([ft.Column(left, spacing=1, tight=True, expand=True), control],
                      spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _insp_toggle_row(self, label, sub, value, on_toggle):
        return self._insp_row(label, self._toggle(value, on_toggle), sub=sub)

    def _cat_selector(self, app, cat):
        return ft.Container(
            ft.Row([
                ft.Row([self.cat_glyph(cat, size=14),
                        T(cat["name"] if cat else "Без категории", size=12.5, color=C.TEXT_1,
                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                       spacing=7, tight=True, expand=True),
                ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.TEXT_4),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            width=170, height=C.H_FIELD, bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER),
            border_radius=C.R_BTN, padding=ft.padding.symmetric(0, 10),
            on_click=lambda e: self._cycle_category(app["id"]),
            tooltip="Следующая категория")

    def _hotkey_field(self, app):
        label = "нажмите…" if self.view.capture else (app.get("hotkey") or "не задана")
        field = ft.Container(
            T(label, size=11.5, color=C.TEXT_2 if app.get("hotkey") or self.view.capture
              else C.TEXT_4, font_family="monospace"),
            height=C.H_FIELD, padding=ft.padding.symmetric(0, 10), bgcolor=C.BG_CARD,
            border=ft.border.all(1, C.ACCENT if self.view.capture else C.BORDER_ACTIVE),
            border_radius=C.R_BTN, alignment=ft.alignment.center,
            on_click=lambda e: self._begin_capture())
        row = [field]
        if app.get("hotkey") and not self.view.capture:
            row.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=14, color=C.TEXT_4),
                                    on_click=lambda e: self._set_hotkey(app["id"], None),
                                    tooltip="Убрать комбинацию"))
        return ft.Row(row, spacing=6, tight=True)

    def _insp_advanced(self, app):
        args_value = " ".join(app.get("args") or []) if isinstance(app.get("args"), list) \
            else str(app.get("args") or "")
        open_now = self.view.adv or bool(args_value) or bool(app.get("run_as_admin"))
        head = ft.Container(
            ft.Row([self._caps("ПАРАМЕТРЫ ЗАПУСКА"),
                    ft.Container(height=1, bgcolor=C.BG_HOVER, expand=True),
                    ft.Icon(ft.Icons.EXPAND_LESS if open_now else ft.Icons.EXPAND_MORE,
                            size=16, color=C.TEXT_4)],
                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=lambda e: self._toggle_adv())
        if not open_now:
            return ft.Container(head, padding=ft.padding.only(16, 18, 16, 0))

        args_field = ft.TextField(
            value=args_value, hint_text="--profile work", height=C.H_FIELD, text_size=11.5,
            color=C.TEXT_1, bgcolor=C.BG_CARD, border_color=C.BORDER,
            focused_border_color=C.BORDER_ACTIVE, border_radius=C.R_BTN,
            content_padding=ft.padding.symmetric(0, 10), cursor_color=C.TEXT_1,
            hint_style=ft.TextStyle(color=C.TEXT_4, size=11.5),
            text_style=ft.TextStyle(font_family="mono"), expand=True, on_blur=lambda e: self._set_args(app["id"], e.control.value),
            on_submit=lambda e: self._set_args(app["id"], e.control.value))

        proc = (app.get("track_exe") or "").strip()
        proc_box = ft.Container(
            ft.Row([T(proc or "не определён", size=11.5,
                      color=C.TEXT_2 if proc else C.TEXT_4, font_family="monospace",
                      expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T("найден" if proc and app["id"] in self.running else "", size=11,
                      color=C.OK)],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=C.H_FIELD, bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER),
            border_radius=C.R_BTN, padding=ft.padding.symmetric(0, 10), expand=True)

        def labelled(label, control):
            return ft.Row([T(label, size=12, color=C.TEXT_3, width=74), control],
                          spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Container(ft.Column([
            head,
            labelled("Аргументы", args_field),
            labelled("Процесс", proc_box),
            self._insp_toggle_row("Запуск от администратора", "Будет запрос UAC",
                                  bool(app.get("run_as_admin")),
                                  lambda v: self._set_admin(app["id"], v)),
        ], spacing=10), padding=ft.padding.only(16, 18, 16, 0))

    # =====================================================================
    # Слои поверх окна
    # =====================================================================
    def _render_popover(self):
        from . import dialogs
        cat_id = self.view.popover
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        if cat is None:
            self.popover_layer.visible = False
            self.popover_layer.content = None
            return
        index = [c["id"] for c in self.categories()].index(cat_id)
        # Rail geometry: title bar, 14px of padding, four fixed filters and a
        # divider above the first category, then 44px rows with 8px gaps.
        top = C.TITLEBAR_H + 14 + (len(queries.FIXED_FILTERS) + index) * (C.RAIL_BTN + 8) + 9
        height = getattr(getattr(self.page, "window", None), "height", None) or C.LIBRARY_H
        self.popover_layer.left = C.RAIL_W + 8
        self.popover_layer.top = max(C.TITLEBAR_H + 8, min(top, height - 430))
        self.popover_layer.content = dialogs.build_category_popover(self, cat)
        self.popover_layer.visible = True

    def _render_onboarding(self):
        from . import dialogs
        if not self.view.onboarding:
            self.onboarding_layer.visible = False
            self.onboarding_layer.content = None
            return
        self.onboarding_layer.content = dialogs.build_onboarding(self)
        self.onboarding_layer.visible = True

    # =====================================================================
    # Клавиатура
    # =====================================================================
    def handle_key(self, e: ft.KeyboardEvent) -> None:
        key = e.key or ""
        if self.view.capture:
            self._capture_key(e)
            return
        if e.ctrl and key.lower() == "l":
            self._open_library()
            return
        if e.ctrl and key == ",":
            self._open_settings()
            return
        if e.ctrl and key.lower() == "k":
            self._focus(self.search_field if self.view.mode == "launch"
                        else self.lib_search_field)
            return
        if self.view.mode == "launch":
            self._launch_key(e, key)
        else:
            self._library_key(e, key)

    def _launch_key(self, e, key):
        if key in ("Arrow Down", "Arrow Up"):
            rows = queries.launch_rows(self.apps(), self.view.query, self.running,
                                       self.categories())
            self.view.move_hi(1 if key == "Arrow Down" else -1,
                              sum(1 for r in rows if r["kind"] == "app"))
            self.refresh()
        elif key in ("Enter", "Numpad Enter"):
            self.activate_selected()
        elif key == "Escape":
            if self.view.query:
                self._clear_query()
            else:
                self._hide_window()

    def _library_key(self, e, key):
        if key == "Escape":
            if self.view.escape():
                self.refresh()
            else:
                self._hide_window()
        elif e.ctrl and key.lower() == "a" and self.view.screen == "grid":
            sections = queries.build_sections(self.apps(), self.categories(), self.view.filter,
                                              self.view.lib_query, self.running)
            self.view.select_all([a["id"] for a in queries.flatten_sections(sections)])
            self.refresh()
        elif key == "Delete" and self.view.sel:
            self._remove_selected()
        elif e.ctrl and key in ("Enter", "Numpad Enter") and self.view.screen == "add":
            self.commit_add()

    def _capture_key(self, e):
        """Record the next combination the user presses into the app's hotkey."""
        key = e.key or ""
        if key in ("Control", "Alt", "Shift", "Meta"):
            return
        if key == "Escape":
            self.view.capture = False
            self.refresh()
            return
        parts = [name for flag, name in ((e.ctrl, "Ctrl"), (e.alt, "Alt"), (e.shift, "Shift"))
                 if flag]
        if not parts:
            self.toast.error("Нужна комбинация с Ctrl, Alt или Shift")
            return
        accel = "+".join(parts + [key if len(key) > 1 else key.upper()])
        self.view.capture = False
        self._set_hotkey(self.view.inspector, accel)

    def activate_selected(self):
        rows = queries.launch_rows(self.apps(), self.view.query, self.running, self.categories())
        app_rows = [r for r in rows if r["kind"] == "app"]
        if not app_rows:
            return
        index = min(self.view.hi, len(app_rows) - 1)
        self._launch(app_rows[index]["app"]["id"])

    # =====================================================================
    # Действия
    # =====================================================================
    def _call(self, name, *args):
        def run():
            cb = self.controllers.get(name)
            if cb:
                cb(*args)
        return run

    def _hover_row(self, index, e):
        if e.data == "true" and self.view.hi != index:
            self.view.hi = index
            self.refresh()

    def _on_query(self, e):
        self.view.set_query(e.control.value)
        self.refresh()

    def _on_lib_query(self, e):
        self.view.set_lib_query(e.control.value)
        self.refresh()

    def _clear_query(self):
        self.view.set_query("")
        self.search_field.value = ""
        self.refresh()
        self._focus(self.search_field)

    def _focus(self, field):
        # focus() asserts the control is on the page; it may not be during a
        # rebuild, and that must not kill the key press that asked for it.
        try:
            if field.page:
                field.focus()
        except Exception:
            log.exception("focusing a field failed")

    def _clear_lib_query(self):
        self.view.set_lib_query("")
        self.lib_search_field.value = ""
        self.refresh()

    def _set_filter(self, key):
        self.view.set_filter(key)
        self.lib_search_field.value = ""
        self.refresh()

    def set_mode(self, mode):
        self.view.set_mode(mode)
        cb = self.controllers.get("set_mode")
        if cb:
            cb(mode)
        self.refresh()
        if mode == "launch":
            self._focus(self.search_field)

    def _open_launch(self):
        self.set_mode("launch")

    def _open_library(self):
        self.view.screen = "grid"
        self.set_mode("library")

    def _hide_window(self):
        cb = self.controllers.get("hide_to_tray")
        if cb:
            cb()

    def _open_add(self):
        self.view.set_mode("library")
        self.view.set_screen("add")
        self.view.reset_add()
        cb = self.controllers.get("set_mode")
        if cb:
            cb("library")
        self.start_scan()
        self.refresh()

    def _open_settings(self):
        self.view.set_mode("library")
        self.view.set_screen("settings")
        cb = self.controllers.get("set_mode")
        if cb:
            cb("library")
        self.refresh()

    def back_to_grid(self):
        self.view.set_screen("grid")
        self.refresh()

    def _tune(self, app_id):
        """«Настроить» in «Запуск»: the library, this app, inspector open."""
        self.view.set_mode("library")
        self.view.screen = "grid"
        self.view.select_one(app_id)
        cb = self.controllers.get("set_mode")
        if cb:
            cb("library")
        self.refresh()

    def _select_tile(self, app_id):
        self.view.select_one(app_id)
        app = next((a for a in self.apps() if a["id"] == app_id), None)
        # "Параметры запуска" opens by itself when there is something in it.
        self.view.adv = bool(app and (app.get("args") or app.get("run_as_admin")))
        self.refresh()

    def _toggle_tile(self, app_id):
        self.view.toggle_selection(app_id)
        self.refresh()

    def _drag_ids(self, app_id):
        return list(self.view.sel) if app_id in self.view.sel else [app_id]

    def _close_inspector(self):
        self.view.close_inspector()
        self.refresh()

    def _toggle_adv(self):
        self.view.adv = not self.view.adv
        self.refresh()

    def _begin_capture(self):
        self.view.capture = not self.view.capture
        self.refresh()

    # ---- запуск ----
    def _launch(self, app_id):
        app = self.store.get_app(app_id)
        if not app:
            return
        try:
            res = self.launcher.launch(app)
        except Exception as exc:
            # launch() reports failure in its return value, but it shells out to
            # the OS — an unforeseen error must still become a message, not a
            # traceback inside a Flet event handler.
            log.exception("launching %s failed", app.get("path"))
            res = {"ok": False, "error": str(exc)}
        if not res.get("ok"):
            self._launch_failed(app, res.get("error", "Не удалось запустить"))
            return
        self.store.mark_launched(app_id)
        self.running = set(self.launcher.running_ids())
        self.toast.show(f"Открыт {app['name']}", icon=ft.Icons.PLAY_ARROW)
        self._after_launch()

    def _launch_failed(self, app, message):
        missing = "не найден" in message.lower()
        self.toast.error(message,
                         action=(lambda: self._tune(app["id"])) if missing else None,
                         action_label="Указать путь" if missing else None)
        self.refresh()

    def _launch_set(self, set_id):
        rec = self.store.get_set(set_id)
        if not rec:
            return
        started, failed = [], 0
        for app_id in rec["apps"]:
            app = self.store.get_app(app_id)
            if not app:
                continue
            try:
                res = self.launcher.launch(app)
            except Exception:
                log.exception("launching %s from a set failed", app.get("path"))
                res = {"ok": False}
            if res.get("ok"):
                self.store.mark_launched(app_id)
                started.append(app["name"])
            else:
                failed += 1
        self.running = set(self.launcher.running_ids())
        if started:
            text = "Открыто: " + ", ".join(started)
            if failed:
                text += f" · не удалось: {failed}"
            self.toast.show(text, icon=ft.Icons.LAYERS)
            self._after_launch()
        else:
            self.toast.error(f"Ни одна программа из «{rec['name']}» не запустилась")
            self.refresh()

    def _after_launch(self):
        if self.setting("hide_after", True) and self.view.mode == "launch":
            self.view.set_query("")
            self.search_field.value = ""
            self._hide_window()
        self.refresh()

    # ---- правка ----
    def _toggle_fav(self, app_id):
        app = self.store.get_app(app_id)
        if app:
            self.store.update_app(app_id, {"favorite": not app.get("favorite")})
        self.refresh()

    def _toggle_pin(self, app_id, value):
        self.store.update_app(app_id, {"quick": bool(value)})
        self.on_library_changed()
        self.toast.show("Закреплено в «Запуске»" if value else "Открепили",
                        icon=ft.Icons.BOLT, icon_color=C.TEXT_3)

    def _set_hotkey(self, app_id, accel):
        if not app_id:
            self.refresh()
            return
        if accel:
            clash = next((a for a in self.apps()
                          if a["id"] != app_id
                          and (a.get("hotkey") or "").lower() == accel.lower()), None)
            if clash:
                self.toast.error(f"{accel} уже занята «{clash['name']}»")
                self.refresh()
                return
        self.store.update_app(app_id, {"hotkey": accel})
        self.on_library_changed()
        self.toast.show(f"Горячая клавиша: {accel}" if accel else "Горячая клавиша убрана",
                        icon=ft.Icons.BOLT, icon_color=C.TEXT_3)

    def _set_args(self, app_id, value):
        import shlex
        text = (value or "").strip()
        try:
            args = shlex.split(text, posix=False) if text else []
        except ValueError:
            args = text.split()
        self.store.update_app(app_id, {"args": args})
        self.refresh()

    def _set_admin(self, app_id, value):
        self.store.update_app(app_id, {"run_as_admin": bool(value)})
        self.refresh()

    def _cycle_category(self, app_id):
        cats = self.categories()
        if len(cats) < 2:
            self.toast.show("Создайте вторую категорию, чтобы было куда переносить",
                            icon=ft.Icons.FOLDER, icon_color=C.TEXT_3)
            return
        app = self.store.get_app(app_id)
        ids = [c["id"] for c in cats]
        current = app.get("category_id") if app else None
        index = ids.index(current) if current in ids else -1
        nxt = cats[(index + 1) % len(cats)]
        self.store.update_app(app_id, {"category_id": nxt["id"]})
        self.toast.show(f"Теперь в «{nxt['name']}»", icon=ft.Icons.FOLDER, icon_color=C.TEXT_3)
        self.refresh()

    def _move_apps_to_category(self, app_ids, cat_id):
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        if not cat or not app_ids:
            return
        before = {a["id"]: a.get("category_id") for a in self.apps() if a["id"] in set(app_ids)}
        moved = self.store.update_apps(app_ids, {"category_id": cat_id})
        if not moved:
            return

        def undo():
            for app_id, old in before.items():
                self.store.update_app(app_id, {"category_id": old}, persist=False)
            self.store.flush()
            self.on_library_changed()

        self.toast.show(f"Перемещено в «{cat['name']}»" if moved == 1
                        else f"Перемещено {moved} в «{cat['name']}»",
                        icon=ft.Icons.FOLDER, icon_color=C.TEXT_3,
                        action=undo, action_label="Отменить")
        self.on_library_changed()

    def _bulk_favorite(self):
        ids = list(self.view.sel)
        self.store.update_apps(ids, {"favorite": True})
        self.toast.show(f"Добавлено в избранное: {len(ids)}", icon=ft.Icons.STAR,
                        icon_color=C.STAR)
        self.refresh()

    def _bulk_make_set(self):
        apps = [a for a in self.apps() if a["id"] in set(self.view.sel)]
        if len(apps) < 2:
            self.toast.error("Выберите хотя бы две программы")
            return
        rec = self.store.add_set(queries.set_name_for(apps), [a["id"] for a in apps])
        if not rec:
            return
        self.view.clear_selection()
        self.toast.show(f"Набор «{rec['name']}» собран — он в «Запуске»", icon=ft.Icons.LAYERS,
                        icon_color=C.TEXT_3,
                        action=lambda: self._undo_set(rec["id"]), action_label="Отменить")
        self.refresh()

    def _undo_set(self, set_id):
        self.store.remove_set(set_id)
        self.refresh()

    def _remove_selected(self):
        self._remove_apps(list(self.view.sel))

    def _remove_apps(self, app_ids):
        if not app_ids:
            return
        gone = self.store.remove_apps(app_ids)
        if not gone:
            return
        self.view.close_inspector()
        text = (f"«{gone[0]['name']}» убран из библиотеки" if len(gone) == 1
                else f"Убрано {len(gone)} {plu_apps(len(gone))}")
        self.toast.show(text, icon=ft.Icons.DELETE_OUTLINE, icon_color=C.TEXT_3,
                        action=lambda: self._restore_apps(gone), action_label="Отменить")
        self.on_library_changed()

    def _restore_apps(self, records):
        self.store.restore_apps(records)
        self.on_library_changed()

    # ---- категории ----
    def _add_category(self):
        cat = self.store.add_category("Новая категория")
        self.view.set_filter(f"category:{cat['id']}")
        self.view.open_popover(cat["id"])
        self.on_library_changed()

    def _reorder_category(self, cat_id, to_index):
        ids = [c["id"] for c in self.categories()]
        if cat_id not in ids:
            return
        ids.remove(cat_id)
        ids.insert(max(0, min(len(ids), to_index)), cat_id)
        self.store.reorder_categories(ids)
        self.refresh()

    def _tap_category(self, cat_id, active):
        """Click filters; clicking the category you are already in edits it.

        The design opens the popover on a double click. Inside the drag
        wrappers the rail needs for reordering, Flutter's arena hands the
        second tap to the drag recogniser often enough that a double click
        can't be the only way in — so the second click on the active category
        does it too, and the tooltip says so.
        """
        if active:
            self._open_popover(cat_id)
        else:
            self._set_filter(f"category:{cat_id}")

    def _open_popover(self, cat_id):
        self.view.open_popover(cat_id)
        self.refresh()

    def close_popover(self):
        self.view.close_popover()
        self.refresh()

    def rename_category(self, cat_id, name):
        if (name or "").strip():
            self.store.update_category(cat_id, {"name": name.strip()})
            self.on_library_changed()

    def set_category_color(self, cat_id, color):
        self.store.update_category(cat_id, {"color": color})
        self.refresh()

    def set_category_icon(self, cat_id, icon):
        self.store.update_category(cat_id, {"icon": icon})
        self.refresh()

    def set_icon_query(self, text):
        self.view.icon_query = text or ""
        self.refresh()

    def remove_category(self, cat_id):
        if len(self.categories()) <= 1:
            self.toast.error("Это последняя категория — программам нужно куда-то деться")
            return
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        undo = self.store.remove_category(cat_id)
        if not undo:
            return
        self.view.close_popover()
        moved = len(undo["apps"])
        text = f"Категория «{cat['name']}» удалена" if cat else "Категория удалена"
        if moved:
            text += f", {moved} {plu_apps(moved)} перенесено"
        self.toast.show(text, icon=ft.Icons.DELETE_OUTLINE, icon_color=C.TEXT_3,
                        action=lambda: self._restore_category(undo), action_label="Отменить")
        self.on_library_changed()

    def _restore_category(self, undo):
        self.store.restore_category(undo)
        self.on_library_changed()

    # ---- наборы ----
    def remove_set(self, set_id):
        rec = self.store.remove_set(set_id)
        if not rec:
            return
        self.toast.show(f"Набор «{rec['name']}» убран", icon=ft.Icons.LAYERS,
                        icon_color=C.TEXT_3,
                        action=lambda: self._restore_set(rec), action_label="Отменить")
        self.refresh()

    def _restore_set(self, rec):
        self.store.restore_set(rec)
        self.refresh()

    # ---- настройки ----
    def set_setting(self, key, value):
        self.store.set_setting(key, value)
        cb = self.controllers.get("on_setting")
        if cb:
            cb(key, value)
        self.refresh()

    def on_library_changed(self):
        self.view.revalidate(self.categories())
        cb = self.controllers.get("on_library_changed")
        if cb:
            cb()
        self.refresh()

    def _on_store_error(self, message):
        try:
            self.toast.error(f"Не удалось сохранить данные: {message}")
        except Exception:
            log.exception("reporting a store write failure to the user failed")

    # =====================================================================
    # Сканирование и добавление
    # =====================================================================
    def icon_cache_dir(self) -> str:
        return str(Path(self.store.path).parent / "icons")

    def cached_discovery(self):
        """The last scan result, or None once it is too old to trust."""
        if self._discovered is None:
            return None
        if time.monotonic() - self._discovered_at > DISCOVERY_TTL:
            return None
        return self._discovered

    def _remember_discovery(self, found):
        self._discovered = found
        self._discovered_at = time.monotonic()

    def scan_state(self) -> dict:
        with self._scan_lock:
            return dict(self._scan)

    def start_scan(self, force: bool = False):
        """Fill the add screen. Reuses a fresh result instead of rescanning."""
        with self._scan_lock:
            if self._scan["state"] == "running":
                return
            if not force and self.cached_discovery() is not None:
                self._scan.update(state="done", found=len(self._discovered), errors=[])
                return
            self._scan.update(state="running", label="", done=0, total=3, found=0,
                              started=time.monotonic(), errors=[])

        def progress(label, done, total):
            with self._scan_lock:
                self._scan.update(label=label, done=done, total=total)
            self._safe_refresh()

        def work():
            from . import discovery
            report = {}
            try:
                if force:
                    # An explicit rescan is the user's way of saying "try
                    # again" — give artwork downloads another chance in case
                    # they were switched off while the machine was offline.
                    discovery.reset_cdn_state()
                found = discovery.discover_apps(self.icon_cache_dir(), on_progress=progress,
                                                report=report)
            except Exception as exc:
                log.exception("scanning for installed programs failed")
                with self._scan_lock:
                    self._scan.update(state="error", errors=[
                        {"source": "", "label": "Поиск программ", "error": str(exc)}])
                self._safe_refresh()
                return
            self._remember_discovery(found)
            with self._scan_lock:
                self._scan.update(state="done", found=len(found),
                                  errors=report.get("errors") or [])
            self._safe_refresh()

        threading.Thread(target=work, daemon=True).start()

    def dismiss_scan_errors(self):
        with self._scan_lock:
            self._scan["errors"] = []
        self.refresh()

    def found_groups(self):
        found = self.cached_discovery() or []
        existing = {(a.get("path") or "").lower() for a in self.apps()}
        return queries.group_found(found, existing, self.categories(),
                                   only_new=self.view.only_new)

    def toggle_only_new(self):
        self.view.only_new = not self.view.only_new
        self.refresh()

    def toggle_add_row(self, row):
        if not row["is_new"]:
            self.toast.show(f"«{row['name']}» уже в библиотеке", icon=ft.Icons.CHECK_CIRCLE,
                            icon_color=C.TEXT_3)
            return
        self.view.toggle_add(row["key"])
        self.refresh()

    def toggle_add_group(self, group):
        keys = [r["key"] for r in group["rows"] if r["is_new"]]
        checked = all(k in self.view.add_sel for k in keys) if keys else False
        self.view.set_add_group(keys, not checked)
        self.refresh()

    def cycle_add_category(self, row):
        cats = self.categories()
        if len(cats) < 2:
            return
        ids = [c["id"] for c in cats]
        current = self.view.add_cat.get(row["key"], row["cat"])
        index = ids.index(current) if current in ids else -1
        self.view.add_cat[row["key"]] = ids[(index + 1) % len(ids)]
        self.refresh()

    def add_category_for(self, row) -> str | None:
        return self.view.add_cat.get(row["key"], row["cat"])

    def commit_add(self):
        groups = self.found_groups()
        rows = {r["key"]: r for g in groups for r in g["rows"]}
        chosen = [rows[k] for k in self.view.add_sel if k in rows and rows[k]["is_new"]]
        if not chosen:
            self.toast.show("Отметьте хотя бы одну программу", icon=ft.Icons.CHECK_CIRCLE,
                            icon_color=C.TEXT_3)
            return
        added = []
        for row in chosen:
            item = row["item"]
            record = self.store.add_app({
                "name": item.get("name"), "path": item.get("path"), "icon": item.get("icon"),
                "icon_fit": item.get("icon_fit"), "sub": item.get("sub", ""),
                "track_exe": item.get("track_exe"), "poster": item.get("poster"),
                "category_id": self.add_category_for(row),
            })
            added.append(record)
        self.view.reset_add()
        # Back to the whole library, so what was just added is on screen.
        self.view.set_filter("all")
        self.toast.show(f"Добавлено {len(added)} {plu_apps(len(added))}",
                        action=lambda: self._restore_added(added), action_label="Отменить")
        self.on_library_changed()
        self._backfill_icons_async()

    def _restore_added(self, records):
        self.store.remove_apps([r["id"] for r in records])
        self.on_library_changed()

    def pick_file(self):
        """Add a program by hand — the escape hatch when a scan misses one."""
        picker = getattr(self, "_file_picker", None)
        if picker is None:
            picker = ft.FilePicker()
            self._file_picker = picker
            self.page.overlay.append(picker)
            self.page.update()
        picker.on_result = self._on_file_picked
        picker.pick_files(dialog_title="Выберите программу", allow_multiple=False)

    def _on_file_picked(self, e):
        if not e.files:
            return
        from . import discovery
        picked = e.files[0]
        path = picked.path or picked.name
        base = (picked.name or "").rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        name = (base[:1].upper() + base[1:]) if base else "Приложение"
        item = {"name": name, "path": path, "source": ""}
        cat_id = queries.suggest_category(item, self.categories())
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        icon = discovery.extract_icon(path, self.icon_cache_dir()) if path else None
        record = self.store.add_app({"name": name, "path": path, "icon": icon,
                                     "category_id": cat_id})
        self.view.select_one(record["id"])
        self.view.set_mode("library")
        self.view.screen = "grid"
        self.toast.show(f"«{name}» добавлен в «{cat['name']}»" if cat else f"«{name}» добавлен",
                        icon=ft.Icons.AUTO_AWESOME, icon_color=C.TEXT_3,
                        action=lambda: self._change_category_of(record["id"]),
                        action_label="Другая")
        self.on_library_changed()

    def _change_category_of(self, app_id):
        self._cycle_category(app_id)

    def _backfill_icons_async(self):
        """Re-resolve icons off the UI thread — extracting one shells out."""
        def work():
            from . import discovery
            try:
                if discovery.backfill_icons(self.store, self.icon_cache_dir()):
                    self.on_library_changed()
            except Exception:
                log.exception("re-resolving icons after an add failed")
        threading.Thread(target=work, daemon=True).start()

    def rescan(self, silent: bool = False):
        """The 15-minute tick and the explicit «Проверить сейчас»."""
        if not silent:
            self.toast.show("Смотрю, что установлено", icon=ft.Icons.SEARCH,
                            icon_color=C.TEXT_3)

        def work():
            from . import discovery
            try:
                cache = self.icon_cache_dir()
                if not silent:
                    discovery.reset_cdn_state()
                # refresh=True re-resolves every icon, and on Windows that is
                # one PowerShell process per .exe. Worth it when the user asked
                # for it; not something the background tick should do.
                changed = discovery.backfill_icons(self.store, cache, refresh=not silent)
                found = discovery.discover_apps(cache)
                self._remember_discovery(found)
                existing = {(a.get("path") or "").lower() for a in self.store.state()["apps"]}
                new = [a for a in found if (a.get("path") or "").lower() not in existing]
                self.on_library_changed()
                if new:
                    self.toast.show(f"Нашлось нового: {len(new)}", icon=ft.Icons.SEARCH,
                                    icon_color=C.TEXT_3, action=self._open_add,
                                    action_label="Показать")
                elif not silent:
                    self.toast.show("Иконки обновлены" if changed else "Всё актуально")
            except Exception:
                log.exception("rescan failed")
                if not silent:
                    self.toast.error("Не удалось пересканировать",
                                     action=lambda: self.rescan(), action_label="Повторить")
        threading.Thread(target=work, daemon=True).start()

    def cycle_launch_hotkey(self):
        """Step through the combinations that open «Запуск».

        A capture field would need the window focused to read the combination
        that is supposed to work when it isn't, so this offers the few that are
        known to register cleanly instead.
        """
        from .hotkeys import LAUNCH_HOTKEYS
        current = self.setting("launch_hotkey") or LAUNCH_HOTKEYS[0]
        index = LAUNCH_HOTKEYS.index(current) if current in LAUNCH_HOTKEYS else -1
        self.set_setting("launch_hotkey", LAUNCH_HOTKEYS[(index + 1) % len(LAUNCH_HOTKEYS)])

    # ---- первый запуск ----
    def maybe_onboard(self):
        """Offer the first-run screen once, and only with something to offer."""
        if self.setting("onboarded") or self.apps():
            return
        self.show_onboarding()

    def show_onboarding(self):
        self.view.onboarding = True
        self.view.onboarding_sel = set()
        self.start_scan()
        self.refresh()

    def close_onboarding(self):
        self.view.onboarding = False
        self.set_setting("onboarded", True)

    def onboarding_items(self):
        from . import discovery
        found = self.cached_discovery()
        if found is None:
            return []
        existing = {(a.get("path") or "").lower() for a in self.apps()}
        fresh = [f for f in found if (f.get("path") or "").lower() not in existing]
        return discovery.suggest_first_run(fresh)

    def toggle_onboarding(self, key):
        if key in self.view.onboarding_sel:
            self.view.onboarding_sel.discard(key)
        else:
            self.view.onboarding_sel.add(key)
        self.refresh()

    def commit_onboarding_selection(self):
        picked = self.view.onboarding_sel
        chosen = [s["app"] for s in self.onboarding_items()
                  if (s["app"].get("path") or "").lower() in picked]
        if not chosen:
            self.close_onboarding()
            return
        self.commit_onboarding(chosen)

    def commit_onboarding(self, chosen):
        added = 0
        for item in chosen:
            self.store.add_app({
                "name": item.get("name"), "path": item.get("path"), "icon": item.get("icon"),
                "icon_fit": item.get("icon_fit"), "sub": item.get("sub", ""),
                "track_exe": item.get("track_exe"), "poster": item.get("poster"),
                "category_id": queries.suggest_category(item, self.categories()),
                "quick": True,
            })
            added += 1
        self.view.onboarding = False
        self.store.set_setting("onboarded", True)
        if added:
            self.toast.show(f"Готово — {added} {plu_programs(added)} закреплено в «Запуске»")
            self._backfill_icons_async()
        self.on_library_changed()

    # ---- служебное ----
    def _safe_refresh(self):
        try:
            self.refresh()
        except Exception:
            log.exception("background refresh failed")

    def backup(self):
        try:
            path = self.store.backup()
        except Exception:
            log.exception("creating a backup failed")
            self.toast.error("Не удалось создать копию",
                             action=self.backup, action_label="Повторить")
            return
        self.toast.show(f"Копия сохранена: {path.name}", icon=ft.Icons.BACKUP,
                        icon_color=C.TEXT_3)

    def show_data_folder(self):
        res = self.launcher.show_in_folder({"path": str(self.store.path)})
        if not res.get("ok"):
            self.toast.error(res.get("error", "Папка не найдена"))

    def icon_cache_size(self) -> int:
        total = 0
        try:
            for entry in Path(self.icon_cache_dir()).glob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            return 0
        return total

    def clear_icon_cache(self):
        removed = 0
        try:
            for entry in Path(self.icon_cache_dir()).glob("*"):
                if entry.is_file():
                    entry.unlink()
                    removed += 1
        except OSError:
            log.exception("clearing the icon cache failed")
            self.toast.error("Не удалось очистить кэш")
            return
        # The library still points at the files that were just deleted, so the
        # icons have to be resolved again before the grid is drawn from them.
        self.store.update_apps([a["id"] for a in self.apps()], {"icon": None, "poster": None})
        self.toast.show(f"Кэш очищен, файлов удалено: {removed}")
        self._backfill_icons_async()
        self.refresh()
