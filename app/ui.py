"""Окно.

Раскладка библиотеки — исходная: титульная полоса, рельс, боковая панель,
тулбар, лента быстрого запуска, секции категорий, статус-бар. Редизайн
добавил внутрь неё инспектор справа вместо модального окна правки, значок
разбора со счётчиком в рельсе, «Наборы» в панели и правый клик везде, где
раньше приходилось искать кнопку.

Второй режим окна — «Запуск»: та же библиотека, но с одним полем поиска.
"""
from __future__ import annotations

import os
import shlex
import threading
import time
from pathlib import Path

import flet as ft

from . import __version__
from . import colors as C
from . import log
from . import menus
from . import queries
from .format import T, cat_icon, plu_apps, plu_cats, plu_programs, time_ago
from .hotkeys import free_quick_slot, quick_accels
from .images import icon_image, img_b64, is_launcher_art
from .menus import MenuHost
from .store import Store
from .toast import ToastHost
from .view_state import ViewState

# How long a discover_apps() result stays good enough to reuse. Long enough to
# cover "rescan, then open «Найти и добавить»", short enough that a program
# installed meanwhile still shows up.
DISCOVERY_TTL = 120.0

# The search field's preferred and smallest widths, and how much of the toolbar
# the rest of it takes: sort button + view toggle + «Найти и добавить» + the
# gaps and the outer padding. Used to shrink the field instead of letting the
# row slide under the inspector.
SEARCH_W = 380
SEARCH_MIN_W = 150
TOOLBAR_FIXED_W = 470


class CenturioUI:
    def __init__(self, page: ft.Page, store: Store, launcher, controllers=None,
                 window: str = "library"):
        self.page = page
        self.store = store
        self.launcher = launcher
        self.controllers = controllers or {}
        self.running: set[str] = set()
        self.view = ViewState(store, window=window)
        self._sel_id = None
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
        self._accels: dict[str, str] = {}
        # Result of the last discover_apps() run, so an explicit rescan
        # followed by «Найти и добавить» doesn't scan the machine twice.
        self._discovered = None
        self._discovered_at = 0.0
        self._scanning = False
        self._scan_errors: list[dict] = []
        # Set while a file picker is being used to re-point an entry that moved.
        self._relocating: str | None = None
        self._manual_found: list[dict] = []
        # How many the triage queue has placed this session — the progress bar
        # and the "Всё разобрано" screen both read it.
        self._triage_done_count = 0
        self._scan_lock = threading.Lock()

        self.toast = ToastHost(page)
        self.menu = MenuHost(page, on_dismiss=self._on_menu_dismissed)

        self.search_field = ft.TextField(
            value="", hint_text="Поиск по библиотеке", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=13, color=C.TEXT, hint_style=ft.TextStyle(color=C.MUTED_2, size=13),
            cursor_color=C.TEXT, on_change=self._on_search, expand=True,
        )
        self.launch_field = ft.TextField(
            value="", hint_text="Что запустить?", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=17.5, color=C.TEXT, hint_style=ft.TextStyle(color=C.TEXT_FAINT, size=17.5),
            cursor_color=C.TEXT, on_change=self._on_launch_query, expand=True, autofocus=True,
        )

        self.rail_container = ft.Container(width=C.RAIL_W, bgcolor=C.BG_0)
        self.sidebar_container = ft.Container(width=C.SIDEBAR_W, bgcolor=C.BG_2)
        self.content_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.content_holder = ft.Container(self.content_col, expand=True,
                                           padding=ft.padding.only(24, 8, 24, 8))
        self.toolbar_holder = ft.Container()
        self.status_container = ft.Container()
        self.inspector_container = ft.Container(width=C.INSPECTOR_W, bgcolor=C.BG_2,
                                                visible=False)
        self.titlebar_holder = ft.Container()
        self.library_body = ft.Container(expand=True)
        self.body = ft.Container(left=0, top=0, right=0, bottom=0)
        self.popover_layer = ft.Container(visible=False)
        self.onboarding_layer = ft.Container(left=0, top=0, right=0, bottom=0, visible=False)

    # ---- совместимость со старым API ----
    @property
    def filter(self):
        return self.view.filter

    @filter.setter
    def filter(self, value):
        self.view.filter = value

    @property
    def query(self):
        return self.view.query

    @query.setter
    def query(self, value):
        self.view.query = value

    @property
    def sort(self):
        return self.view.sort

    @sort.setter
    def sort(self, value):
        self.view.sort = value

    @property
    def mode(self):
        return self.view.mode

    @mode.setter
    def mode(self, value):
        self.view.mode = value

    @property
    def selected(self):
        return self.view.selected

    @selected.setter
    def selected(self, value):
        self.view.selected = value

    @property
    def sidebar_open(self):
        return self.view.sidebar_open

    @sidebar_open.setter
    def sidebar_open(self, value):
        self.view.sidebar_open = value

    # ---- снимок библиотеки ----
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

    def inbox(self):
        return sorted(self.state()["inbox"], key=lambda i: i.get("order", 0))

    def setting(self, key, default=None):
        return self._settings.get(key, default)

    def calm(self) -> bool:
        """«Спокойный вид»: one flag, every technical caption obeys it."""
        return bool(self._settings.get("calm"))

    def _accent(self):
        return self._settings.get("accent", C.ACCENT)

    def _content_width(self) -> float:
        """How wide the middle column is right now, panels taken off the top.

        page.window.width is None in web mode and before the window is up, so
        the design width stands in — it only decides whether something shrinks.
        """
        win = getattr(self.page, "window", None)
        total = getattr(win, "width", None) or C.LIBRARY_W
        width = total - C.RAIL_W
        if self.sidebar_open:
            width -= C.SIDEBAR_W
        if self.view.inspector and self.view.screen == "grid":
            width -= C.INSPECTOR_W
        return max(240.0, width)

    # ---- жизненный цикл ----
    def mount(self):
        # A failed save no longer kills the click that caused it, so it has to
        # be said out loud — otherwise the app looks like it saved fine.
        self.store.on_error = self._on_store_error
        main = ft.Column(
            [self.toolbar_holder,
             ft.GestureDetector(self.content_holder, expand=True,
                                on_secondary_tap_down=self._grid_background_menu),
             self.status_container],
            spacing=0, expand=True,
        )
        body = ft.Row([self.rail_container, self.sidebar_container, main,
                       self.inspector_container], spacing=0, expand=True)
        self.library_body.content = ft.Column([self.titlebar_holder, body],
                                              spacing=0, expand=True)
        root = ft.Stack([self.body, self.popover_layer, self.onboarding_layer,
                         self.menu.control, self.toast.control], expand=True)
        self.page.add(root)
        self.refresh()

    def set_running(self, ids):
        self.running = set(ids)
        try:
            self.refresh()
        except Exception:
            log.exception("refreshing after a running-state change failed")

    def refresh(self, content_only=False):
        with self._refresh_lock:
            self._snapshot = self.store.state()
            self._settings = self._snapshot["settings"]
            self._accels = quick_accels(self._snapshot["apps"])
            try:
                self.view.drop_missing(a["id"] for a in self._snapshot["apps"])
                if self.view.window == "launch":
                    self.body.content = self._build_launch()
                else:
                    self._refresh_library(content_only)
                    self.body.content = self.library_body
                self._render_popover()
                self._render_onboarding()
            finally:
                self._snapshot = None
            self.page.update()

    def _refresh_library(self, content_only: bool):
        if not content_only:
            self.titlebar_holder.content = self._build_titlebar()
            self.rail_container.content = self._build_rail()
        show_sidebar = self.sidebar_open
        self.sidebar_container.visible = show_sidebar
        self.sidebar_container.content = self._build_sidebar() if show_sidebar else None
        screen = self.view.screen
        self.toolbar_holder.visible = screen == "grid"
        if screen == "grid":
            self.toolbar_holder.content = self._build_toolbar()
        self.content_col.controls = self._build_content()
        self.content_holder.padding = (ft.padding.only(24, 8, 24, 8) if screen == "grid"
                                       else ft.padding.all(0))
        if not content_only:
            self.status_container.content = self._build_statusbar()
        self.status_container.visible = screen == "grid"
        inspector = self._build_inspector() if self.view.inspector and screen == "grid" else None
        self.inspector_container.visible = inspector is not None
        self.inspector_container.content = inspector

    # =====================================================================
    # Мелкие общие детали
    # =====================================================================
    def _icon(self, name, size=16, color=C.MUTED):
        return ft.Icon(name, size=size, color=color)

    def _hoverable(self, container: ft.Container, normal, hover):
        def on_hover(e):
            container.bgcolor = hover if e.data == "true" else normal
            container.update()
        container.bgcolor = normal
        container.on_hover = on_hover
        return container

    def _caps(self, text):
        return T(text, size=10.5, weight=ft.FontWeight.W_600, color=C.MUTED_2,
                 style=ft.TextStyle(letter_spacing=0.85))

    def _key_chip(self, label):
        return ft.Container(
            T(label, size=10.5, color=C.MUTED, font_family="monospace"),
            bgcolor=C.PANEL_2, border=ft.border.all(1, C.LINE),
            border_radius=4, padding=ft.padding.symmetric(2, 6))

    def _toggle(self, value: bool, on_toggle):
        """The one switch in the program: 34×19, knob 14."""
        knob = ft.Container(width=14, height=14, border_radius=7,
                            bgcolor=C.ON_ACCENT if value else C.MUTED)
        return ft.Container(
            ft.Row([knob], alignment=ft.MainAxisAlignment.END if value
                   else ft.MainAxisAlignment.START),
            width=34, height=19, border_radius=10, padding=ft.padding.all(2.5),
            bgcolor=self._accent() if value else C.TOGGLE_OFF,
            on_click=lambda e: on_toggle(not value),
            animate=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT))

    def primary_btn(self, label, on_click, icon=None, height=36, expand=False):
        row = [T(label, size=13 if height >= 36 else 12.5, weight=ft.FontWeight.W_600,
                 color=C.ON_ACCENT)]
        if icon:
            row.insert(0, ft.Icon(icon, size=15, color=C.ON_ACCENT))
        return ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 16), bgcolor=self._accent(),
            border_radius=9, alignment=ft.alignment.center, expand=expand,
            on_click=lambda e: on_click())

    def icon_btn(self, icon, on_click, tooltip, accent=False, height=36):
        """The label-less form of a button, for when the toolbar runs out of room."""
        btn = ft.Container(
            ft.Icon(icon, size=15, color=C.ON_ACCENT if accent else C.MUTED),
            width=height, height=height, alignment=ft.alignment.center,
            bgcolor=self._accent() if accent else None,
            border=None if accent else ft.border.all(1, C.LINE_4),
            border_radius=9, tooltip=tooltip, on_click=lambda e: on_click())
        return btn if accent else self._hoverable(btn, None, C.PANEL_2)

    def outline_btn(self, label, on_click, icon=None, danger=False, height=36):
        color = C.ERR_TEXT if danger else C.TEXT
        row = [T(label, size=12.5, weight=ft.FontWeight.W_600 if danger else ft.FontWeight.W_400,
                 color=color)]
        if icon:
            row.insert(0, ft.Icon(icon, size=15, color=C.ERR_TEXT if danger else C.MUTED))
        btn = ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 12),
            border=ft.border.all(1, C.ERR_BTN_BORDER if danger else C.LINE_4),
            border_radius=9, alignment=ft.alignment.center,
            on_click=lambda e: on_click())
        return self._hoverable(btn, None, C.PANEL_2)

    def link_btn(self, label, on_click):
        return ft.Container(
            T(label, size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT),
            border=ft.border.only(bottom=ft.BorderSide(1, C.TEXT_FAINT)),
            padding=ft.padding.only(0, 0, 0, 2), on_click=lambda e: on_click())

    def spinner(self, size=38):
        """Всё, что показывает сканирование: кружок и слово рядом с ним."""
        return ft.ProgressRing(width=size, height=size, stroke_width=2.5,
                               color=C.TEXT, bgcolor=C.WINDOW_BORDER)

    # ---- иконки ----
    def cat_of(self, app) -> dict | None:
        cid = app.get("category_id")
        return next((c for c in self.categories() if c["id"] == cid), None)

    def _cat_glyph_name(self, cat) -> str:
        return (cat or {}).get("icon") or "folder"

    def _cat_glyph(self, cat, size=19, color=None):
        """A category's mark. Its own image wins, then its icon."""
        col = color or (C.category_color(cat) if cat else C.MUTED)
        if cat:
            custom = icon_image(cat.get("image"), width=size + 3, height=size + 3,
                                fit=ft.ImageFit.CONTAIN)
            if custom is not None:
                return custom
        return ft.Icon(cat_icon(self._cat_glyph_name(cat)), size=size, color=col)

    def icon_slot(self, app, size: int, radius: int, glyph: int | None = None,
                  border=None, glyph_color=None):
        """The app's real icon, or a neutral pad with its category's glyph.

        There are no letter placeholders anywhere: a tile either shows the icon
        extracted from the executable or says "an icon belongs here".
        """
        fit = ft.ImageFit.COVER if is_launcher_art(app) else ft.ImageFit.CONTAIN
        inner = icon_image(app.get("icon"), width=size - 8, height=size - 8, fit=fit)
        if inner is None:
            cat = self.cat_of(app) if app.get("category_id") else None
            name = self._cat_glyph_name(cat) if cat else _source_glyph(app.get("source"))
            inner = ft.Icon(cat_icon(name), size=glyph or round(size * 0.46),
                            color=glyph_color or C.SLOT_GLYPH)
        return ft.Container(
            inner, width=size, height=size, border_radius=radius, bgcolor=C.SLOT_BG,
            border=ft.border.all(1, border or C.SLOT_BORDER), alignment=ft.alignment.center,
            clip_behavior=ft.ClipBehavior.HARD_EDGE)

    def _running_badge(self):
        return ft.Container(
            ft.Row([ft.Container(width=5, height=5, border_radius=3, bgcolor=C.GREEN),
                    T("Запущено", size=10, weight=ft.FontWeight.W_600, color=C.BADGE_TEXT)],
                   spacing=5, tight=True),
            bgcolor=C.BADGE_BG, border=ft.border.all(1, C.BADGE_BORDER),
            border_radius=20, padding=ft.padding.symmetric(3, 8))

    # =====================================================================
    # Титульная полоса
    # =====================================================================
    def _win_btn(self, icon_name, tooltip, handler, danger=False):
        c = ft.Container(
            ft.Icon(icon_name, size=14, color=C.MUTED),
            width=44, height=32, border_radius=6, alignment=ft.alignment.center,
            on_click=lambda e: handler(),
        )

        def on_hover(e):
            if e.data == "true":
                c.bgcolor = C.DANGER if danger else C.PANEL_3
                c.content.color = C.WHITE if danger else C.TEXT
            else:
                c.bgcolor = None
                c.content.color = C.MUTED
            c.update()
        c.on_hover = on_hover
        c.tooltip = tooltip
        return c

    def _mode_switch(self):
        from .hotkeys import format_accel

        def segment(label, active, on_click, hint=""):
            row = [T(label, size=12,
                     weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
                     color=C.TEXT if active else C.MUTED)]
            if hint and not self.calm():
                row.append(T(hint, size=10, color=C.MUTED_3, font_family="monospace"))
            return ft.Container(
                ft.Row(row, spacing=6, tight=True), height=26,
                padding=ft.padding.symmetric(0, 12), border_radius=6,
                bgcolor=C.PANEL_ACTIVE if active else None, alignment=ft.alignment.center,
                on_click=None if active else (lambda e: on_click()))

        accel = format_accel(self.setting("launch_hotkey"))
        return ft.Container(
            ft.Row([segment("Запуск", False, self._open_launch, accel),
                    segment("Библиотека", True, lambda: None)], spacing=0),
            bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=8,
            padding=ft.padding.all(2))

    def _build_titlebar(self):
        brand = ft.Row([
            T("Centurio", size=13.5, weight=ft.FontWeight.BOLD, color=C.TEXT),
            self._mode_switch(),
        ], spacing=16)
        drag = ft.WindowDragArea(
            ft.Container(brand, padding=ft.padding.only(18, 0, 0, 0),
                         alignment=ft.alignment.center_left, expand=True),
            expand=True,
        )
        buttons = ft.Row([
            self._win_btn(ft.Icons.SOUTH, "Свернуть в трей", self._hide_to_tray),
            ft.Container(width=1, height=16, bgcolor=C.LINE_4, margin=ft.margin.symmetric(0, 4)),
            self._win_btn(ft.Icons.REMOVE, "Свернуть", self._minimize),
            self._win_btn(ft.Icons.CROP_SQUARE, "Развернуть", self._toggle_maximize),
            self._win_btn(ft.Icons.CLOSE, "Закрыть", self._close, danger=True),
        ], spacing=2)
        return ft.Container(
            ft.Row([drag, buttons], spacing=0),
            height=46, bgcolor=C.BG_1,
            border=ft.border.only(bottom=ft.BorderSide(1, C.LINE_2)),
            padding=ft.padding.only(0, 0, 6, 0),
        )

    # =====================================================================
    # Рельс
    # =====================================================================
    def _rail_item(self, glyph, active, on_click, tooltip, fixed_color=None,
                   on_drop_app=None, on_context=None, badge=None, dashed=False):
        inner = ft.Container(
            glyph, width=C.RAIL_BTN, height=C.RAIL_BTN,
            border_radius=14 if active else 22,
            bgcolor=C.PANEL_ACTIVE if active else C.PANEL_2,
            border=ft.border.all(1, C.DASHED_RAIL) if dashed else None,
            alignment=ft.alignment.center, tooltip=tooltip,
            animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
        )

        def on_hover(e):
            if active:
                return
            highlight = e.data == "true"
            inner.bgcolor = C.PANEL_ACTIVE if highlight else C.PANEL_2
            inner.border_radius = 14 if highlight else 22
            if fixed_color is None and isinstance(inner.content, ft.Icon):
                inner.content.color = C.TEXT if highlight else C.MUTED
            inner.update()
        inner.on_hover = on_hover

        button = inner
        if badge is not None:
            button = ft.Stack([inner, ft.Container(badge, right=-4, top=-4)],
                              width=C.RAIL_BTN + 8, height=C.RAIL_BTN + 8)

        tapper = ft.GestureDetector(
            button, mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: on_click(),
            on_secondary_tap_down=(lambda e: on_context(e)) if on_context else None)

        content = tapper
        if on_drop_app is not None:
            def _accept(e):
                src = self.page.get_control(e.src_id)
                payload = getattr(src, "data", None) if src is not None else None
                inner.border = ft.border.all(1, C.DASHED_RAIL) if dashed else None
                inner.update()
                if isinstance(payload, dict) and payload.get("ids"):
                    on_drop_app(payload["ids"])
                elif payload:
                    on_drop_app([payload])

            def _will(e):
                inner.border = ft.border.all(2, self._accent())
                inner.update()

            def _leave(e):
                inner.border = ft.border.all(1, C.DASHED_RAIL) if dashed else None
                inner.update()
            content = ft.DragTarget(group="apps", content=tapper,
                                    on_accept=_accept, on_will_accept=_will, on_leave=_leave)

        bar = ft.Container(width=3, height=28, border_radius=ft.border_radius.only(0, 3, 0, 3),
                           bgcolor=self._accent()) if active else ft.Container(width=3)
        return ft.Row([bar, ft.Container(content, expand=True, alignment=ft.alignment.center)],
                      spacing=0)

    def _is_all_view(self):
        return self.view.is_all_view()

    def _inbox_badge(self, count: int):
        return ft.Container(
            T(str(count if count < 100 else 99), size=10, weight=ft.FontWeight.BOLD,
              color=C.ON_ACCENT, font_family="monospace"),
            height=18, border_radius=9, bgcolor=self._accent(),
            padding=ft.padding.symmetric(0, 5), alignment=ft.alignment.center)

    def _build_rail(self):
        all_active = self._is_all_view() and self.view.screen == "grid"
        waiting = len(self.inbox())
        items = [
            self._rail_item(ft.Icon(ft.Icons.VIEW_SIDEBAR, size=19,
                                    color=C.TEXT if self.sidebar_open else C.MUTED),
                            self.sidebar_open, lambda: self._toggle_sidebar(),
                            "Показать/скрыть панель"),
            self._rail_item(ft.Icon(ft.Icons.GRID_VIEW, size=19,
                                    color=C.TEXT if all_active else C.MUTED),
                            all_active, lambda: self._set_filter("all"), "Главное меню"),
            self._rail_item(ft.Icon(ft.Icons.INBOX, size=19,
                                    color=C.TEXT_2 if waiting else C.MUTED),
                            self.view.screen == "triage", lambda: self._open_triage(),
                            f"Разбор · {waiting}" if waiting and not self.calm() else "Разбор",
                            badge=self._inbox_badge(waiting) if waiting and not self.calm() else None,
                            dashed=bool(waiting)),
            ft.Container(width=32, height=1, bgcolor=C.LINE_2,
                         margin=ft.margin.symmetric(3, 0)),
        ]
        for cat in self.categories():
            active = self.filter == f"category:{cat['id']}" and self.view.screen == "grid"
            items.append(self._rail_item(
                self._cat_glyph(cat, color=C.WHITE), active,
                lambda cid=cat["id"]: self._set_filter(f"category:{cid}"), cat["name"],
                fixed_color=C.category_color(cat),
                on_drop_app=lambda ids, cid=cat["id"]: self._move_apps_to_category(ids, cid),
                on_context=lambda e, c=cat: self._category_menu(c, e)))
        items.append(ft.Container(expand=True))
        add = ft.Container(ft.Icon(ft.Icons.ADD, size=16, color=C.MUTED_2),
                           width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=22,
                           alignment=ft.alignment.center,
                           border=ft.border.all(1.5, C.LINE_4),
                           on_click=lambda e: self._add_category(),
                           tooltip="Добавить категорию")
        settings = ft.Container(ft.Icon(ft.Icons.SETTINGS, size=18, color=C.MUTED),
                                width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=22,
                                alignment=ft.alignment.center,
                                on_click=lambda e: self._open_settings(), tooltip="Настройки")
        items += [add, ft.Container(height=6), settings]
        return ft.Container(
            ft.Column(items, spacing=9, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      expand=True),
            padding=ft.padding.only(0, 14, 0, 12),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    # =====================================================================
    # Боковая панель
    # =====================================================================
    def _sidebar_filter(self, icon_ctl, label, count, key, count_color=None):
        active = self.filter == key and self.view.screen == "grid"
        row = ft.Container(
            ft.Row([
                ft.Container(icon_ctl, width=16, height=16, alignment=ft.alignment.center),
                T(label, size=13, color=C.TEXT if active else C.TEXT_2,
                        weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400, expand=True),
                T("" if self.calm() else str(count), size=11,
                  color=count_color or C.MUTED, font_family="monospace"),
            ], spacing=11),
            padding=ft.padding.symmetric(8, 10), border_radius=9,
            bgcolor=C.PANEL_3 if active else None, on_click=lambda e: self._set_filter(key),
        )
        if not active:
            self._hoverable(row, None, C.PANEL_2)
        return row

    def _build_sidebar(self):
        apps = self.apps()
        fav = sum(1 for a in apps if a.get("favorite"))
        recent_count = sum(1 for a in apps if a.get("last_launched"))
        title = self._current_title()

        top = [
            ft.Container(T(title, size=19, weight=ft.FontWeight.BOLD, color=C.TEXT),
                         padding=ft.padding.only(8, 0, 8, 0)),
        ]
        if not self.calm():
            top.append(ft.Container(
                T(f"{len(apps)} {plu_apps(len(apps))} · "
                  f"{len(self.categories())} {plu_cats(len(self.categories()))}",
                  size=11.5, color=C.MUTED_2, no_wrap=True,
                  overflow=ft.TextOverflow.ELLIPSIS),
                padding=ft.padding.only(8, 5, 8, 0)))
        top += [
            ft.Divider(height=1, color=C.LINE_2),
            ft.Container(self._caps("ПОКАЗАТЬ"), padding=ft.padding.only(10, 0, 0, 8)),
            self._sidebar_filter(ft.Icon(ft.Icons.STAR_BORDER, size=16, color=C.MUTED),
                                 "Избранное", fav, "favorites"),
            self._sidebar_filter(ft.Icon(ft.Icons.SCHEDULE, size=16, color=C.MUTED),
                                 "Недавние", recent_count, "recent"),
            self._sidebar_filter(ft.Container(width=8, height=8, border_radius=4, bgcolor=C.GREEN),
                                 "Запущено", len(self.running), "running", C.GREEN),
            self._sidebar_filter(ft.Icon(ft.Icons.LAYERS, size=16, color=C.MUTED),
                                 "Наборы", len(self.sets()), "sets"),
        ]

        recents = queries.recent_apps(apps, limit=4)
        if recents:
            top += [ft.Divider(height=1, color=C.LINE_2),
                    ft.Container(self._caps("НЕДАВНИЕ"), padding=ft.padding.only(10, 0, 0, 8))]
            for a in recents:
                top.append(self._recent_row(a))

        return ft.Container(
            ft.Column(top + [ft.Container(expand=True), self._sidebar_footer()],
                      spacing=2, expand=True),
            padding=ft.padding.only(14, 20, 14, 14),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    def _recent_row(self, a):
        lines = [T(a["name"], size=12.5, color=C.TEXT, weight=ft.FontWeight.W_500,
                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
        if not self.calm():
            lines.append(T(time_ago(a["last_launched"]), size=10.5, color=C.MUTED_2))
        row = ft.Container(
            ft.Row([self.icon_slot(a, 30, 9, glyph=16),
                    ft.Column(lines, spacing=1, expand=True, tight=True)], spacing=10),
            padding=ft.padding.symmetric(7, 10), border_radius=9,
            on_click=lambda e, i=a["id"]: self._launch(i),
        )
        self._hoverable(row, None, C.PANEL_2)
        return ft.GestureDetector(row, on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e))

    def _sidebar_footer(self):
        # The autostart/tray toggles that used to live here are gone: every
        # setting has exactly one home now, and it is the settings screen.
        return ft.Container(
            ft.Row([T("Centurio", size=11, color=C.MUTED_3),
                    T(f"v{__version__}", size=11, color=C.MUTED_3, font_family="monospace")],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)),
            padding=ft.padding.only(10, 10, 10, 0),
        )

    # =====================================================================
    # Тулбар
    # =====================================================================
    def _build_toolbar(self):
        search_row = [ft.Icon(ft.Icons.SEARCH, size=14, color=C.MUTED_2), self.search_field]
        if not self.calm():
            search_row.append(ft.Container(
                T("Ctrl+K", size=10.5, color=C.MUTED_2, font_family="monospace"),
                bgcolor=C.PANEL_3, border=ft.border.all(1, C.LINE),
                border_radius=5, padding=ft.padding.symmetric(2, 6)))
        # The field is 380 wide when there is room and shrinks when there isn't.
        # Flet has no max-width, and a fixed width here would slide under the
        # inspector as soon as it opens — the toolbar has to give way first.
        room = self._content_width() - TOOLBAR_FIXED_W
        search = ft.Container(
            ft.Row(search_row, spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=38, width=max(SEARCH_MIN_W, min(SEARCH_W, room)),
            bgcolor=C.PANEL, border=ft.border.all(1, C.LINE),
            border_radius=10, padding=ft.padding.only(12, 0, 8, 0),
        )
        sort_btn = ft.Container(
            ft.Row([T(queries.SORT_LABELS[self.sort], size=12.5, color=C.MUTED),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.MUTED)], spacing=7),
            height=36, padding=ft.padding.symmetric(0, 12), border=ft.border.all(1, C.LINE),
            border_radius=9, on_click=lambda e: self._cycle_sort(), alignment=ft.alignment.center,
            tooltip="Порядок плиток",
        )
        self._hoverable(sort_btn, None, C.PANEL_2)

        def view_btn(icon_name, m, tip):
            active = self.mode == m
            return ft.Container(ft.Icon(icon_name, size=13, color=C.TEXT if active else C.MUTED_2),
                                width=36, height=36, alignment=ft.alignment.center,
                                bgcolor=C.PANEL_ACTIVE if active else None,
                                on_click=lambda e: self._set_mode(m), tooltip=tip)
        view_toggle = ft.Container(
            ft.Row([view_btn(ft.Icons.GRID_VIEW, "grid", "Сетка"),
                    view_btn(ft.Icons.VIEW_LIST, "list", "Список")], spacing=0),
            border=ft.border.all(1, C.LINE), border_radius=9,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        # Below this the label is dropped and the button becomes its icon, which
        # is still the same button in the same place.
        add = (self.primary_btn("Найти и добавить", self._open_add, ft.Icons.SEARCH)
               if room >= SEARCH_MIN_W else
               self.icon_btn(ft.Icons.SEARCH, self._open_add, "Найти и добавить",
                             accent=True))
        # The two refresh buttons are gone: rescanning moved to the right-click
        # menu on empty space, where it is asked for once in a while.
        return ft.Container(
            ft.Row([search, ft.Container(expand=True), sort_btn, view_toggle, add],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(24, 18, 24, 12),
        )

    # =====================================================================
    # Содержимое
    # =====================================================================
    def _build_content(self):
        from . import dialogs
        screen = self.view.screen
        if screen == "add":
            return [dialogs.build_add_screen(self)]
        if screen == "settings":
            return [dialogs.build_settings_screen(self)]
        if screen == "triage":
            return [dialogs.build_triage_screen(self)]

        apps = self.apps()
        if not apps and not self.sets():
            self._sel_id = None
            return [self._empty("Библиотека пуста",
                                "Centurio посмотрит, что установлено, и предложит отметить "
                                "нужное. Можно и указать файл вручную.",
                                "Найти и добавить", self._open_add)]

        if self.filter == "sets":
            return self._sets_content()

        # build_sections() filters and sorts the whole library, so it runs once
        # per pass and the keyboard selection reads the same result.
        sections = self._sections()
        self._sel_id = self._selected_id(sections)

        controls = []
        is_all = self.filter == "all" and not self.query.strip()
        if is_all and self.setting("show_quick_row", True):
            controls += self._quick_row()

        if not sections or all(not s["apps"] for s in sections):
            controls.append(self._empty("Ничего не найдено",
                                        "Попробуйте изменить запрос." if self.query
                                        else "В этом разделе пока нет приложений.", None, None))
            return controls

        for sec in sections:
            if not sec["apps"]:
                continue
            controls.append(self._section_head(sec))
            controls.append(self._grid(sec["apps"]) if self.mode == "grid"
                            else self._list(sec["apps"]))
        controls.append(ft.Container(height=10))
        return controls

    def _sections(self):
        return queries.build_sections(self.apps(), self.categories(), self.filter,
                                      self.query, self.sort, self.running)

    # ---- лента быстрого запуска ----
    def _quick_row(self):
        cards = [self._set_card(s) for s in self.sets() if s.get("quick")]
        for app in queries.quick_apps(self.apps()):
            # accels comes from hotkeys.quick_accels() — the same map the global
            # listener registers, so the number can't promise a key that
            # launches something else.
            cards.append(self._quick_card(app, self._accels.get(app["id"])))
        free = free_quick_slot(self.apps())
        if free:
            cards.append(self._quick_empty(free))

        head_row = [T("Быстрый запуск", size=15, weight=ft.FontWeight.BOLD, color=C.TEXT)]
        if not self.calm():
            head_row.append(T("Ctrl+1…9", size=11.5, color=C.MUTED_2))
        head = ft.Container(ft.Row(head_row, spacing=10), padding=ft.padding.only(0, 12, 0, 12))
        return [head, ft.Container(ft.Row(cards, spacing=12, wrap=True, run_spacing=12),
                                   padding=ft.padding.only(0, 0, 0, 20))]

    def _quick_card(self, app, accel):
        cat = self.cat_of(app)
        layers = [ft.Column([
            self.icon_slot(app, 44, 12, glyph=22),
            ft.Container(height=9),
            T(app["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            T(cat["name"] if cat else (app.get("sub") or ""), size=11, color=C.MUTED_2,
              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=0, tight=True)]
        if accel and not self.calm():
            # The card shows the position, not the whole combination — the
            # header already says these are Ctrl+1…9.
            layers.append(ft.Container(
                T(accel.split("+")[-1], size=11, weight=ft.FontWeight.W_600,
                  color=C.TEXT_FAINT, font_family="monospace"), right=10, top=11))
        card = ft.Container(
            ft.Stack(layers), width=C.QUICK_W, bgcolor=C.PANEL,
            border=ft.border.all(1, C.LINE), border_radius=12,
            padding=ft.padding.only(14, 14, 14, 12),
            on_click=lambda e, i=app["id"]: self._launch(i))
        self._hoverable(card, C.PANEL, C.PANEL_2)
        return ft.GestureDetector(card, on_secondary_tap_down=lambda e, ap=app: self._app_menu(ap, e))

    def _set_card(self, rec):
        members = [a for a in self.apps() if a["id"] in set(rec["apps"])]
        count = len(members)
        # No number in the corner: the badge on a quick card means «Ctrl+N», and
        # a set has no hotkey. Numbering it would point at whichever app really
        # owns that combination.
        return ft.GestureDetector(self._set_body(rec, count),
                                  on_secondary_tap_down=lambda e, r=rec: self._set_menu(r, e))

    def _set_body(self, rec, count):
        layers = [ft.Column([
            ft.Container(ft.Icon(ft.Icons.LAYERS, size=20, color=C.TEXT_FAINT),
                         width=44, height=44, border_radius=12, bgcolor=C.SET_SLOT_BG,
                         border=ft.border.all(1, C.SET_SLOT_BORDER),
                         alignment=ft.alignment.center),
            ft.Container(height=9),
            T(rec["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT_2,
              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            T(f"набор · {count} {plu_programs(count)}", size=11, color=C.MUTED_2,
              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=0, tight=True)]
        card = ft.Container(
            ft.Stack(layers), width=C.QUICK_W, bgcolor=C.SET_BG,
            border=ft.border.all(1, C.SET_BORDER), border_radius=12,
            padding=ft.padding.only(14, 14, 14, 12),
            on_click=lambda e, sid=rec["id"]: self._launch_set(sid))
        self._hoverable(card, C.SET_BG, C.PANEL)
        return card

    def _quick_empty(self, slot):
        body = [ft.Icon(ft.Icons.ADD, size=17, color=C.TEXT_GHOST)]
        if not self.calm():
            body.append(T(str(slot), size=11, color=C.TEXT_GHOST, font_family="monospace"))
        return ft.Container(
            ft.Column(body, spacing=7, tight=True,
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      alignment=ft.MainAxisAlignment.CENTER),
            width=C.QUICK_W, height=112, border_radius=12,
            border=ft.border.all(1, C.DASHED), alignment=ft.alignment.center,
            tooltip="Закрепите приложение — оно встанет сюда",
            on_click=lambda e: self._toast_hint_quick())

    # ---- секции и плитки ----
    def _section_head(self, sec):
        cat = next((c for c in self.categories() if c["id"] == sec.get("cid")), None)
        row = [self._cat_glyph(cat, size=15) if cat
               else ft.Container(width=9, height=9, border_radius=3, bgcolor=C.DOT),
               T(sec["name"], size=15, weight=ft.FontWeight.BOLD, color=C.TEXT)]
        if not self.calm():
            row.append(T(f"{len(sec['apps'])} {plu_apps(len(sec['apps']))}", size=11.5,
                         color=C.MUTED_2))
        row.append(ft.Container(height=1, bgcolor=C.LINE_2, expand=True))
        head = ft.Container(ft.Row(row, spacing=10,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.only(0, 10, 0, 14))
        if not cat:
            return head
        return ft.GestureDetector(head, on_secondary_tap_down=lambda e, c=cat: self._category_menu(c, e))

    def _use_poster(self, a):
        return bool(self._settings.get("game_posters", True)
                    and is_launcher_art(a) and img_b64(a.get("poster")))

    def _grid(self, apps):
        tiles = [self._draggable_tile(a, apps) for a in apps]
        return ft.Container(ft.Row(tiles, wrap=True, spacing=15, run_spacing=15,
                                   vertical_alignment=ft.CrossAxisAlignment.START),
                            padding=ft.padding.only(0, 0, 0, 10))

    def _draggable_tile(self, a, section_apps):
        compact = self._settings.get("tile_size") == "compact"
        running = a["id"] in self.running
        selected = a["id"] in self.view.sel or a["id"] == self._sel_id
        base = (self._build_poster_tile(a, compact, running, selected)
                if self._use_poster(a) else
                self._build_tile(a, compact, running, selected))
        return ft.Draggable(group="apps", content=base,
                            data={"ids": self._drag_ids(a["id"])})

    def _tile_meta(self, app, cat) -> str:
        if self.calm():
            return ""
        accel = self._accels.get(app["id"])
        if accel:
            return accel
        if cat:
            return cat["name"]
        return (app.get("sub") or "").strip()

    def _build_tile(self, a, compact, running, selected):
        width = C.TILE_W_COMPACT if compact else C.TILE_W
        cover_h = C.TILE_COVER_H_COMPACT if compact else C.TILE_COVER_H
        slot = C.TILE_SLOT_COMPACT if compact else C.TILE_SLOT
        cat = self.cat_of(a)

        cover_children = [ft.Container(
            self.icon_slot(a, slot, 16, glyph=round(slot * 0.47),
                           border=C.SLOT_BORDER_SEL if selected else None,
                           glyph_color=C.SLOT_GLYPH_SEL if selected else None),
            expand=True, alignment=ft.alignment.center,
            gradient=ft.LinearGradient(begin=ft.alignment.top_left,
                                       end=ft.alignment.bottom_right,
                                       colors=list(C.TILE_GRADIENT)))]
        if running:
            cover_children.append(ft.Container(self._running_badge(), left=10, top=10))
        if a.get("favorite"):
            cover_children.append(ft.Container(
                ft.Icon(ft.Icons.STAR, size=14, color=C.STAR),
                right=8, top=8, width=26, height=26, border_radius=8, bgcolor=C.SCRIM,
                alignment=ft.alignment.center, tooltip="Убрать из избранного",
                on_click=lambda e, i=a["id"]: self._toggle_fav(i)))

        meta = "выбрано" if selected and not self.calm() else self._tile_meta(a, cat)
        foot_lines = [T(a["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
        if meta:
            foot_lines.append(T(meta, size=11, color=C.MUTED_2, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                font_family="monospace" if meta.startswith("Ctrl") else None))
        foot = ft.Container(ft.Column(foot_lines, spacing=1, tight=True),
                            padding=ft.padding.only(13, 11, 13, 12))

        tile = ft.Container(
            ft.Column([ft.Container(ft.Stack(cover_children, expand=True), height=cover_h,
                                    clip_behavior=ft.ClipBehavior.HARD_EDGE), foot],
                      spacing=0, tight=True),
            width=width, bgcolor=C.SELECTED_BG if selected else C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=14, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        def on_hover(e):
            if selected:
                return
            tile.border = ft.border.all(1, C.LINE_5 if e.data == "true" else C.LINE)
            tile.update()
        tile.on_hover = on_hover
        return ft.GestureDetector(tile, on_tap=lambda e, i=a["id"]: self._select_tile(i),
                                  on_double_tap=lambda e, i=a["id"]: self._launch(i),
                                  on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e),
                                  mouse_cursor=ft.MouseCursor.CLICK)

    def _build_poster_tile(self, a, compact, running, selected):
        width = C.POSTER_W_COMPACT if compact else C.POSTER_W
        height = C.POSTER_H_COMPACT if compact else C.POSTER_H
        poster = ft.Image(src_base64=img_b64(a.get("poster")), width=width, height=height,
                          fit=ft.ImageFit.COVER)
        scrim = ft.Container(
            T(a["name"], size=12.5, weight=ft.FontWeight.W_600, color=C.WHITE,
              max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            left=0, right=0, bottom=0, padding=ft.padding.only(10, 20, 10, 9),
            gradient=ft.LinearGradient(begin=ft.alignment.top_center,
                                       end=ft.alignment.bottom_center,
                                       colors=list(C.POSTER_SCRIM)))
        children = [poster, scrim]
        if running:
            children.append(ft.Container(self._running_badge(), left=8, top=8))
        children.append(ft.Container(
            ft.Icon(ft.Icons.STAR if a.get("favorite") else ft.Icons.STAR_BORDER, size=14,
                    color=C.STAR if a.get("favorite") else C.WHITE),
            right=8, top=8, width=26, height=26, border_radius=8, bgcolor=C.SCRIM,
            alignment=ft.alignment.center, tooltip="В избранное",
            on_click=lambda e, i=a["id"]: self._toggle_fav(i)))

        tile = ft.Container(
            ft.Stack(children), width=width, height=height, bgcolor=C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE)

        def on_hover(e):
            if selected:
                return
            tile.border = ft.border.all(1, C.LINE_5 if e.data == "true" else C.LINE)
            tile.update()
        tile.on_hover = on_hover
        return ft.GestureDetector(tile, on_tap=lambda e, i=a["id"]: self._select_tile(i),
                                  on_double_tap=lambda e, i=a["id"]: self._launch(i),
                                  on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e),
                                  mouse_cursor=ft.MouseCursor.CLICK)

    def _list(self, apps):
        rows = [self._list_row(a) for a in apps]
        return ft.Container(ft.Column(rows, spacing=6), padding=ft.padding.only(0, 0, 0, 10))

    def _list_row(self, a):
        running = a["id"] in self.running
        selected = a["id"] in self.view.sel or a["id"] == self._sel_id
        cat = self.cat_of(a)
        lines = [T(a["name"], size=13.5, weight=ft.FontWeight.W_600, color=C.TEXT)]
        meta = self._tile_meta(a, cat)
        if meta:
            lines.append(T(meta, size=11.5, color=C.MUTED_2))
        controls = [self.icon_slot(a, 40, 10, glyph=20),
                    ft.Column(lines, spacing=1, expand=True, tight=True)]
        if running:
            controls.append(ft.Row([ft.Container(width=5, height=5, border_radius=3,
                                                 bgcolor=C.GREEN),
                                    T("Запущено", size=10, color=C.GREEN_TEXT)],
                                   spacing=5, tight=True))
        controls.append(ft.Container(
            ft.Icon(ft.Icons.STAR if a.get("favorite") else ft.Icons.STAR_BORDER, size=15,
                    color=C.STAR if a.get("favorite") else C.MUTED),
            width=30, height=30, border_radius=9, alignment=ft.alignment.center,
            on_click=lambda e, i=a["id"]: self._toggle_fav(i)))
        controls.append(ft.Container(ft.Icon(ft.Icons.MORE_HORIZ, size=16, color=C.MUTED),
                                     width=30, height=30, border_radius=9,
                                     alignment=ft.alignment.center, tooltip="Меню",
                                     on_click=lambda e, ap=a: self._app_menu(ap, None)))
        row = ft.Container(ft.Row(controls, spacing=14,
                                  vertical_alignment=ft.CrossAxisAlignment.CENTER),
                           padding=ft.padding.symmetric(10, 14), border_radius=11,
                           border=ft.border.all(2, self._accent()) if selected
                           else ft.border.all(1, C.LINE),
                           bgcolor=C.SELECTED_BG if selected else C.PANEL,
                           on_click=lambda e, i=a["id"]: self._select_tile(i))
        if not selected:
            self._hoverable(row, C.PANEL, C.PANEL_2)
        return ft.GestureDetector(row, on_double_tap=lambda e, i=a["id"]: self._launch(i),
                                  on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e))

    # ---- наборы ----
    def _sets_content(self):
        records = self.sets()
        if not records:
            return [self._empty("Наборов пока нет",
                                "Выберите несколько плиток, нажмите правую кнопку и "
                                "«Собрать набор» — он запустит их разом.", None, None)]
        controls = [ft.Container(
            ft.Row([T("Наборы", size=15, weight=ft.FontWeight.BOLD, color=C.TEXT),
                    ft.Container(height=1, bgcolor=C.LINE_2, expand=True)], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(0, 10, 0, 14))]
        for rec in records:
            controls.append(self._set_row(rec))
        return controls

    def _set_row(self, rec):
        members = [a for a in self.apps() if a["id"] in set(rec["apps"])]
        stack = []
        for index, app in enumerate(members[:4]):
            stack.append(ft.Container(self.icon_slot(app, 26, 8, glyph=14),
                                      margin=ft.margin.only(left=0 if not index else -7)))
        lines = [T(rec["name"], size=13.5, weight=ft.FontWeight.W_600, color=C.TEXT)]
        if not self.calm():
            lines.append(T(", ".join(a["name"] for a in members) or "пусто",
                           size=11.5, color=C.MUTED_2, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS))
        row = ft.Container(
            ft.Row([ft.Row(stack, spacing=0, tight=True),
                    ft.Column(lines, spacing=1, expand=True, tight=True),
                    ft.Container(ft.Icon(ft.Icons.MORE_HORIZ, size=16, color=C.MUTED),
                                 width=30, height=30, border_radius=9,
                                 alignment=ft.alignment.center, tooltip="Меню",
                                 on_click=lambda e, r=rec: self._set_menu(r, None))],
                   spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(10, 14), border_radius=11, bgcolor=C.PANEL,
            border=ft.border.all(1, C.LINE),
            on_click=lambda e, sid=rec["id"]: self._launch_set(sid))
        self._hoverable(row, C.PANEL, C.PANEL_2)
        return ft.GestureDetector(row, on_secondary_tap_down=lambda e, r=rec: self._set_menu(r, e))

    def _empty(self, title, text, btn_label, on_click):
        controls = [
            ft.Container(ft.Icon(ft.Icons.GRID_VIEW, size=26, color=C.MUTED),
                         width=64, height=64, border_radius=18, bgcolor=C.PANEL,
                         border=ft.border.all(1, C.LINE), alignment=ft.alignment.center),
            ft.Container(height=18),
            T(title, size=17, weight=ft.FontWeight.BOLD, color=C.TEXT),
            ft.Container(height=8),
            T(text, size=13, color=C.MUTED_2, text_align=ft.TextAlign.CENTER, width=380),
        ]
        if btn_label:
            controls += [ft.Container(height=20),
                         self.primary_btn(btn_label, on_click, ft.Icons.SEARCH)]
        return ft.Container(
            ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
            alignment=ft.alignment.center, padding=ft.padding.only(0, 70, 0, 40))

    # =====================================================================
    # Статус-бар
    # =====================================================================
    def _build_statusbar(self):
        if self.calm():
            return ft.Container(height=0)
        parts = []
        if self.running:
            parts.append(T(f"{len(self.running)} запущено", size=11.5, color=C.MUTED_2))
        waiting = len(self.inbox())
        if waiting:
            if parts:
                parts.append(ft.Container(width=1, height=12, bgcolor=C.LINE))
            parts.append(ft.Container(
                T(f"{waiting} {'ждёт' if waiting == 1 else 'ждут'} разбора", size=11.5,
                  color=C.MUTED_2), on_click=lambda e: self._open_triage()))
        parts.append(ft.Container(expand=True))
        return ft.Container(ft.Row(parts, spacing=16,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.symmetric(9, 24), bgcolor=C.BG_2,
                            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

    # =====================================================================
    # Инспектор
    # =====================================================================
    def _build_inspector(self):
        app = next((a for a in self.apps() if a["id"] == self.view.inspector), None)
        if app is None:
            return None
        running = app["id"] in self.running
        cat = self.cat_of(app)

        title_line = [T(app["name"], size=15.5, weight=ft.FontWeight.BOLD, color=C.TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)]
        title_lines = [ft.Row(title_line, spacing=6)]
        if not self.calm() and app.get("path"):
            title_lines.append(T(_short_path(app["path"]), size=10.5, color=C.MUTED_2,
                                 max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        header = ft.Container(
            ft.Row([self.icon_slot(app, 44, 12, glyph=22),
                    ft.Column(title_lines, spacing=4, expand=True, tight=True),
                    ft.Container(ft.Icon(ft.Icons.CLOSE, size=18, color=C.MUTED_2),
                                 on_click=lambda e: self._close_inspector(),
                                 tooltip="Закрыть панель")],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=ft.padding.only(18, 16, 18, 14),
            border=ft.border.only(bottom=ft.BorderSide(1, C.LINE_2)))

        def square(icon, tooltip, handler, color=C.MUTED):
            return ft.Container(ft.Icon(icon, size=16, color=color), width=38, height=34,
                                border=ft.border.all(1, C.LINE_4), border_radius=9,
                                alignment=ft.alignment.center, tooltip=tooltip,
                                on_click=lambda e: handler())

        actions = ft.Container(
            ft.Row([
                self.primary_btn("Переключиться" if running else "Открыть",
                                 lambda: self._launch(app["id"]),
                                 ft.Icons.SYNC_ALT if running else ft.Icons.PLAY_ARROW,
                                 height=34, expand=True),
                square(ft.Icons.STAR if app.get("favorite") else ft.Icons.STAR_BORDER,
                       "В избранное", lambda: self._toggle_fav(app["id"]),
                       C.STAR if app.get("favorite") else C.MUTED),
                square(ft.Icons.FOLDER_OPEN, "Показать в папке",
                       lambda: self._show_in_folder(app["id"])),
            ], spacing=8), padding=ft.padding.only(18, 14, 18, 0))

        placement = ft.Container(ft.Column([
            self._caps("РАЗМЕЩЕНИЕ"),
            self._insp_row("Категория", self._cat_selector(app, cat)),
            self._insp_row("Быстрый запуск", self._toggle(
                bool(app.get("quick")), lambda v: self._toggle_quick(app["id"], v)),
                sub=self._quick_sub(app)),
            self._insp_row("Своя горячая клавиша", self._hotkey_field(app),
                           sub="Нажмите комбинацию" if self.view.capture
                           else "Работает из любого окна"),
        ], spacing=11), padding=ft.padding.only(18, 16, 18, 0))

        footer = ft.Container(
            ft.Row([T("" if self.calm() else "сохраняется само", size=10.5,
                      color=C.MUTED_3, expand=True),
                    self.outline_btn("Убрать", lambda: self._remove_apps([app["id"]]),
                                     ft.Icons.DELETE_OUTLINE, danger=True, height=32)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(14, 18),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

        return ft.Container(
            ft.Column([header, actions, placement, self._insp_advanced(app),
                       ft.Container(expand=True), footer], spacing=0, expand=True),
            border=ft.border.only(left=ft.BorderSide(1, C.LINE_2)), expand=True)

    def _insp_row(self, label, control, sub=None):
        left = [T(label, size=12.5, color=C.TEXT_2)]
        if sub and not self.calm():
            left.append(T(sub, size=11, color=C.MUTED_2))
        return ft.Row([ft.Column(left, spacing=1, tight=True, expand=True), control],
                      spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _quick_sub(self, app) -> str:
        accel = self._accels.get(app["id"])
        if app.get("quick") and accel:
            return f"Сейчас место {accel.split('+')[-1]}"
        if app.get("quick"):
            return "Свободных мест не осталось"
        return "Появится в ленте сверху"

    def _cat_selector(self, app, cat):
        return ft.Container(
            ft.Row([
                ft.Row([self._cat_glyph(cat, size=14) if cat
                        else ft.Icon(ft.Icons.FOLDER, size=14, color=C.MUTED),
                        T(cat["name"] if cat else "Без категории", size=12.5, color=C.TEXT,
                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                       spacing=7, tight=True, expand=True),
                ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.MUTED_2),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            width=170, height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE),
            border_radius=8, padding=ft.padding.symmetric(0, 10),
            tooltip="Выбрать категорию",
            on_click=lambda e: self._category_picker(app, e))

    def _hotkey_field(self, app):
        label = "нажмите…" if self.view.capture else (app.get("hotkey") or "не задана")
        field = ft.Container(
            T(label, size=11.5, font_family="monospace",
              color=C.TEXT_2 if (app.get("hotkey") or self.view.capture) else C.MUTED_2),
            height=32, padding=ft.padding.symmetric(0, 10), bgcolor=C.PANEL,
            border=ft.border.all(1, self._accent() if self.view.capture else C.LINE_5),
            border_radius=8, alignment=ft.alignment.center,
            on_click=lambda e: self._begin_capture())
        row = [field]
        if app.get("hotkey") and not self.view.capture:
            row.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=14, color=C.MUTED_2),
                                    tooltip="Убрать комбинацию",
                                    on_click=lambda e: self._set_hotkey(app["id"], None)))
        return ft.Row(row, spacing=6, tight=True)

    def _insp_advanced(self, app):
        args_value = " ".join(app.get("args") or []) if isinstance(app.get("args"), list) \
            else str(app.get("args") or "")
        open_now = self.view.adv or bool(args_value) or bool(app.get("run_as_admin")) \
            or bool(app.get("working_dir"))
        head = ft.Container(
            ft.Row([self._caps("ПАРАМЕТРЫ ЗАПУСКА"),
                    ft.Container(height=1, bgcolor=C.LINE_2, expand=True),
                    ft.Icon(ft.Icons.EXPAND_LESS if open_now else ft.Icons.EXPAND_MORE,
                            size=16, color=C.MUTED_2)],
                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=lambda e: self._toggle_adv())
        if not open_now:
            return ft.Container(head, padding=ft.padding.only(18, 18, 18, 0))

        args_field = ft.TextField(
            value=args_value, hint_text="не заданы", height=32, text_size=11.5,
            color=C.TEXT, bgcolor=C.PANEL, border_color=C.LINE,
            focused_border_color=C.LINE_5, border_radius=8,
            content_padding=ft.padding.symmetric(0, 10), cursor_color=C.TEXT,
            hint_style=ft.TextStyle(color=C.MUTED_2, size=11.5),
            text_style=ft.TextStyle(font_family="mono"), expand=True,
            on_blur=lambda e: self._set_args(app["id"], e.control.value),
            on_submit=lambda e: self._set_args(app["id"], e.control.value))

        workdir = (app.get("working_dir") or "").strip()
        folder = ft.Container(
            ft.Row([T(_short_path(workdir) if workdir else "как у файла", size=11.5,
                      color=C.TEXT_2 if workdir else C.MUTED_2, font_family="monospace",
                      expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Container(ft.Icon(ft.Icons.FOLDER_OPEN, size=15, color=C.MUTED_2),
                                 on_click=lambda e: self._pick_working_dir(app["id"]))],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=8,
            padding=ft.padding.only(10, 0, 6, 0), expand=True)

        proc = (app.get("track_exe") or "").strip()
        proc_box = ft.Container(
            ft.Row([T(proc or "не определён", size=11.5, font_family="monospace",
                      color=C.TEXT if proc else C.MUTED_2, expand=True,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T("найден" if proc and app["id"] in self.running else "", size=11,
                      color=C.GREEN)],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=8,
            padding=ft.padding.symmetric(0, 10), expand=True)

        def labelled(label, control):
            return ft.Row([T(label, size=12, color=C.MUTED, width=74), control],
                          spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Container(ft.Column([
            head,
            labelled("Аргументы", args_field),
            labelled("Папка", folder),
            labelled("Процесс", proc_box),
            self._insp_row("От администратора",
                           self._toggle(bool(app.get("run_as_admin")),
                                        lambda v: self._set_admin(app["id"], v)),
                           sub="Будет запрос UAC"),
        ], spacing=9), padding=ft.padding.only(18, 18, 18, 0))

    # =====================================================================
    # Режим «Запуск»
    # =====================================================================
    def _build_launch(self):
        apps = self.apps()
        rows = queries.launch_rows(apps, self.view.launch_query, self.running,
                                   self.categories())
        if self.view.hi >= len(rows):
            self.view.hi = max(0, len(rows) - 1)

        waiting = len(self.inbox())
        head_right = []
        if waiting:
            head_right.append(ft.Container(
                ft.Stack([ft.Icon(ft.Icons.INBOX, size=17, color=C.MUTED),
                          ft.Container(ft.Container(width=6, height=6, border_radius=3,
                                                    bgcolor=self._accent()),
                                       right=0, top=0)], width=20, height=20),
                tooltip=f"Разбор · {waiting}", on_click=lambda e: self._open_triage()))
        else:
            head_right.append(ft.Container(ft.Icon(ft.Icons.INBOX, size=17, color=C.TEXT_GHOST),
                                           tooltip="Разбор", on_click=lambda e: self._open_triage()))
        head_right.append(ft.Container(ft.Icon(ft.Icons.GRID_VIEW, size=17, color=C.TEXT_GHOST),
                                       tooltip="Библиотека · Ctrl+L",
                                       on_click=lambda e: self._open_library()))

        head = ft.Container(
            ft.Row([ft.Icon(ft.Icons.SEARCH, size=20, color=C.TEXT_FAINT), self.launch_field]
                   + head_right, spacing=14,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=66, padding=ft.padding.symmetric(0, 26))

        column = [head]
        if not self.view.launch_query.strip():
            pinned = self._launch_pinned()
            if pinned is not None:
                column.append(pinned)
        column.append(self._launch_list(rows))
        if self.setting("hints", True) and not self.calm():
            column.append(ft.Container(
                ft.Row([T("↑↓ выбрать · Enter запустить · Ctrl+L библиотека",
                          size=11, color=C.HINT),
                        ft.Container(expand=True),
                        T(f"{len(apps)} {plu_apps(len(apps))}", size=11, color=C.TEXT_GHOST)],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                height=40, padding=ft.padding.symmetric(0, 26)))

        return ft.Container(
            ft.Column(column, spacing=0, expand=True),
            bgcolor=C.BG_1, border=ft.border.all(1, C.WINDOW_BORDER), border_radius=16,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def _launch_pinned(self):
        # Sets carry no number here either — only an app that Ctrl+N really
        # launches gets a badge.
        cards = [self._launch_tile(rec["name"], "", is_set=True,
                                   on_click=lambda sid=rec["id"]: self._launch_set(sid))
                 for rec in self.sets() if rec.get("quick")]
        for app in queries.quick_apps(self.apps()):
            accel = self._accels.get(app["id"])
            cards.append(self._launch_tile(app["name"], accel.split("+")[-1] if accel else "",
                                           app=app,
                                           on_click=lambda i=app["id"]: self._launch(i)))
        if not cards:
            return None
        free = free_quick_slot(self.apps())
        if free:
            cards.append(self._launch_empty(free))
        return ft.Container(ft.Row(cards, spacing=14, wrap=True, run_spacing=14),
                            padding=ft.padding.only(26, 6, 26, 0))

    def _launch_tile(self, name, number, on_click, app=None, is_set=False):
        if is_set:
            slot = ft.Container(ft.Icon(ft.Icons.LAYERS, size=24, color=C.TEXT_FAINT),
                                width=58, height=58, border_radius=17, bgcolor=C.SET_SLOT_BG,
                                border=ft.border.all(1, C.SET_SLOT_BORDER),
                                alignment=ft.alignment.center)
        else:
            slot = self.icon_slot(app, 58, 17, glyph=27)
        column = [slot, T(name, size=11.5, color=C.MUTED if is_set else C.TEXT_2, width=96,
                          text_align=ft.TextAlign.CENTER, max_lines=1,
                          overflow=ft.TextOverflow.ELLIPSIS)]
        layers = [ft.Column(column, spacing=9, tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER)]
        if number and not self.calm():
            layers.append(ft.Container(T(str(number), size=10, color=C.TEXT_FAINT,
                                         font_family="monospace"), right=14, top=-1))
        return ft.Container(ft.Stack(layers, width=96, height=92),
                            on_click=lambda e: on_click(), tooltip=None if self.calm() else name)

    def _launch_empty(self, slot):
        column = [ft.Container(ft.Icon(ft.Icons.ADD, size=18, color=C.TEXT_GHOST),
                               width=58, height=58, border_radius=17,
                               border=ft.border.all(1, C.WINDOW_BORDER),
                               alignment=ft.alignment.center),
                  T("" if self.calm() else f"место {slot}", size=11.5, color=C.TEXT_GHOST)]
        return ft.Container(ft.Column(column, spacing=9, tight=True,
                                      horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            width=96, height=92)

    def _launch_list(self, rows):
        if not rows:
            return ft.Container(self._launch_empty_state(), expand=True,
                                padding=ft.padding.only(26, 22, 26, 0))
        controls = [self._launch_row(r, r["index"] == self.view.hi) for r in rows]
        return ft.Container(
            ft.Column(controls, spacing=2, scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True, padding=ft.padding.only(26, 22, 26, 0))

    def _launch_row(self, row, active: bool):
        app = row["app"]
        controls = [self.icon_slot(app, 30, 9, glyph=16)]
        name = T(spans=[
            ft.TextSpan(text, ft.TextStyle(bgcolor=C.MATCH_BG) if hit else None)
            for text, hit in queries.match_spans(app["name"], self.view.launch_query)
        ], size=14, color=C.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        controls.append(name)
        if row["note"] == "открыто":
            controls += [ft.Container(width=5, height=5, border_radius=3, bgcolor=C.GREEN),
                         T("открыто", size=11.5, color=C.GREEN_TEXT)]
        elif not self.calm():
            ago = time_ago(app.get("last_launched"))
            if ago:
                controls.append(T(ago, size=11, color=C.TEXT_FAINT))

        container = ft.Container(
            ft.Row(controls, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=46, padding=ft.padding.symmetric(0, 12), border_radius=12,
            bgcolor=C.PANEL if active else None,
            on_click=lambda e, i=app["id"]: self._launch(i))
        # Hovering moves the keyboard selection too, so mouse and keyboard never
        # disagree about which row Enter would run.
        container.on_hover = lambda e, i=row["index"]: self._hover_row(i, e)
        return ft.GestureDetector(container,
                                  on_secondary_tap_down=lambda e, ap=app: self._app_menu(ap, e))

    def _launch_empty_state(self):
        query = self.view.launch_query.strip()
        if query:
            return ft.Column([
                T(f"По запросу «{query}» ничего нет", size=15, weight=ft.FontWeight.W_600,
                  color=C.TEXT),
                T("В библиотеке ничего похожего нет. Можно поискать среди установленных "
                  "программ.", size=12.5, color=C.MUTED),
                ft.Container(ft.Row([
                    self.primary_btn("Искать в системе", self._open_add),
                    self.outline_btn("Сбросить", self._clear_launch_query),
                ], spacing=8), padding=ft.padding.only(0, 4, 0, 0)),
            ], spacing=10, tight=True)
        return ft.Column([
            T("Пока нечего запускать", size=15, weight=ft.FontWeight.W_600, color=C.TEXT),
            T("Добавьте программы — и они появятся здесь, как только вы их откроете.",
              size=12.5, color=C.MUTED),
            ft.Container(self.primary_btn("Найти и добавить", self._open_add),
                         padding=ft.padding.only(0, 4, 0, 0)),
        ], spacing=10, tight=True)

    # =====================================================================
    # Контекстные меню
    # =====================================================================
    def _menu_at(self, e):
        if e is None:
            win = getattr(self.page, "window", None)
            return (getattr(win, "width", C.LIBRARY_W) or C.LIBRARY_W) / 2, 180.0
        return float(getattr(e, "global_x", 0) or 0), float(getattr(e, "global_y", 0) or 0)

    def _on_menu_dismissed(self):
        # The shade swallowed the click that closed the menu, so the tree it
        # covered has to be redrawn without it.
        self._safe_refresh()

    def _app_menu(self, app, e):
        app = self.store.get_app(app["id"]) or app
        selection = [i for i in self.view.sel if i != app["id"]]
        if selection and app["id"] in self.view.sel and len(self.view.sel) > 1:
            self._selection_menu(e)
            return
        x, y = self._menu_at(e)
        running = app["id"] in self.running
        free = free_quick_slot(self.apps())
        rows = [
            menus.item(ft.Icons.SYNC_ALT if running else ft.Icons.PLAY_ARROW,
                       "Переключиться" if running else "Открыть",
                       lambda: self._launch(app["id"]), hint="Enter"),
            menus.item(ft.Icons.ADD, "Открыть ещё окно",
                       lambda: self._launch(app["id"], again=True)),
            menus.separator(),
            menus.item(ft.Icons.STAR if app.get("favorite") else ft.Icons.STAR_BORDER,
                       "Убрать из избранного" if app.get("favorite") else "В избранное",
                       lambda: self._toggle_fav(app["id"])),
            menus.item(ft.Icons.BOLT,
                       "Убрать из быстрого запуска" if app.get("quick") else "В быстрый запуск",
                       lambda: self._toggle_quick(app["id"], not app.get("quick")),
                       hint="" if app.get("quick") or self.calm()
                       else (f"место {free}" if free else "мест нет")),
            menus.item(ft.Icons.FOLDER, "Переложить в…",
                       lambda: self.menu.toggle_submenu(
                           "cat", self._category_submenu([app["id"]]), y),
                       submenu=True),
            menus.item(ft.Icons.LAYERS, "Добавить в набор…",
                       lambda: self.menu.toggle_submenu(
                           "set", self._set_submenu([app["id"]]), y),
                       submenu=True),
            menus.separator(),
            menus.item(ft.Icons.FOLDER_OPEN, "Показать в папке",
                       lambda: self._show_in_folder(app["id"])),
            menus.item(ft.Icons.TUNE, "Настроить", lambda: self._select_tile(app["id"]),
                       hint="" if self.calm() else "панель"),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, "Убрать из библиотеки",
                       lambda: self._remove_apps([app["id"]]), danger=True),
        ]
        self.menu.show(x, y, rows, header=menus.app_header(self, app, running))

    def _selection_menu(self, e):
        x, y = self._menu_at(e)
        ids = list(self.view.sel)
        count = len(ids)
        rows = [
            menus.item(ft.Icons.FOLDER, "Переложить в…",
                       lambda: self.menu.toggle_submenu("cat", self._category_submenu(ids), y),
                       submenu=True),
            menus.item(ft.Icons.STAR_BORDER, "В избранное", lambda: self._bulk_favorite(ids)),
            menus.item(ft.Icons.LAYERS, "Собрать набор", lambda: self._make_set(ids)),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, f"Убрать · {count}",
                       lambda: self._remove_apps(ids), danger=True),
        ]
        self.menu.show(x, y, rows, header=menus.text_header(f"Выбрано {count}"))

    def _category_menu(self, cat, e):
        x, y = self._menu_at(e)
        cats = self.categories()
        index = [c["id"] for c in cats].index(cat["id"]) if cat["id"] in [c["id"] for c in cats] else 0
        count = sum(1 for a in self.apps() if a.get("category_id") == cat["id"])
        rows = [
            menus.item(ft.Icons.EDIT, "Переименовать", lambda: self._open_popover(cat["id"])),
            menus.item(ft.Icons.PALETTE, "Цвет и иконка", lambda: self._open_popover(cat["id"])),
            menus.item(ft.Icons.ARROW_UPWARD, "Переместить выше",
                       lambda: self._move_category(cat["id"], -1), disabled=index == 0),
            menus.item(ft.Icons.ARROW_DOWNWARD, "Переместить ниже",
                       lambda: self._move_category(cat["id"], 1),
                       disabled=index >= len(cats) - 1),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, "Удалить категорию",
                       lambda: self._remove_category(cat["id"]), danger=True),
        ]
        self.menu.show(x, y, rows, header=menus.category_header(self, cat, count))

    def _set_menu(self, rec, e):
        x, y = self._menu_at(e)
        rows = [
            menus.item(ft.Icons.PLAY_ARROW, "Запустить набор",
                       lambda: self._launch_set(rec["id"]), hint="Enter"),
            menus.item(ft.Icons.BOLT,
                       "Убрать из быстрого запуска" if rec.get("quick") else "В быстрый запуск",
                       lambda: self._toggle_set_quick(rec["id"], not rec.get("quick"))),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, "Удалить набор",
                       lambda: self._remove_set(rec["id"]), danger=True),
        ]
        self.menu.show(x, y, rows, header=menus.text_header(rec["name"]))

    def _grid_background_menu(self, e):
        """ПКМ по пустому месту сетки — только на самой сетке."""
        if self.view.window == "library" and self.view.screen == "grid":
            self._empty_menu(e)

    def _empty_menu(self, e):
        x, y = self._menu_at(e)
        waiting = len(self.inbox())
        rows = [
            menus.item(ft.Icons.SEARCH, "Найти и добавить", self._open_add),
            menus.item(ft.Icons.FOLDER_OPEN, "Указать файл вручную", self.pick_file),
            menus.item(ft.Icons.INBOX, "Открыть разбор", self._open_triage,
                       hint="" if self.calm() or not waiting else str(waiting),
                       disabled=not waiting),
            menus.separator(),
            menus.item(ft.Icons.SORT, "Сортировка",
                       lambda: self.menu.toggle_submenu("sort", self._sort_submenu(), y),
                       submenu=True),
            menus.item(ft.Icons.REFRESH, "Обновить список", lambda: self.rescan()),
        ]
        self.menu.show(x, y, rows, header=None)

    def _category_submenu(self, app_ids):
        rows = []
        for cat in self.categories():
            rows.append(menus.item(cat.get("icon") or "folder", cat["name"],
                                   lambda cid=cat["id"]: self._move_apps_to_category(app_ids, cid)))
        return rows or [menus.item(None, "Категорий нет", None, disabled=True)]

    def _set_submenu(self, app_ids):
        rows = [menus.item(ft.Icons.ADD, "Новый набор…", lambda: self._make_set(app_ids))]
        records = self.sets()
        if records:
            rows.append(menus.separator())
        for rec in records:
            rows.append(menus.item(ft.Icons.LAYERS, rec["name"],
                                   lambda sid=rec["id"]: self._add_to_set(sid, app_ids)))
        return rows

    def _sort_submenu(self):
        return [menus.item(ft.Icons.CHECK if self.sort == key else None,
                           queries.SORT_LABELS[key], lambda k=key: self._set_sort(k))
                for key in queries.SORT_KEYS]

    def _category_picker(self, app, e):
        x, y = self._menu_at(e)
        self.menu.show(x, y, self._category_submenu([app["id"]]),
                       header=menus.text_header("Переложить в…"))

    # =====================================================================
    # Клавиатура
    # =====================================================================
    def handle_key(self, e: ft.KeyboardEvent) -> None:
        key = e.key or ""
        if self.view.capture:
            self._capture_key(e)
            return
        if self.menu.open and key == "Escape":
            self.menu.close()
            return
        if self.view.onboarding:
            if key == "Escape":
                self.close_onboarding()
            return
        if e.ctrl and key.lower() == "l":
            self._open_library()
            return
        if e.ctrl and key == ",":
            self._open_settings()
            return
        if e.ctrl and key.lower() == "k":
            self._focus(self.launch_field if self.view.window == "launch" else self.search_field)
            return
        if self.view.window == "launch":
            self._launch_key(e, key)
        else:
            self._library_key(e, key)

    def _launch_key(self, e, key):
        if key in ("Arrow Down", "Arrow Up"):
            rows = queries.launch_rows(self.apps(), self.view.launch_query, self.running,
                                       self.categories())
            self.view.move_hi(1 if key == "Arrow Down" else -1, len(rows))
            self.refresh()
        elif key in ("Enter", "Numpad Enter"):
            self.activate_selected()
        elif key == "Escape":
            if self.view.launch_query:
                self._clear_launch_query()
            else:
                self._hide_to_tray()

    def _library_key(self, e, key):
        if self.view.screen == "triage":
            if self._triage_key(key):
                return
        if key == "Escape":
            if self.view.escape():
                self.refresh()
            else:
                self._hide_to_tray()
        elif e.ctrl and key.lower() == "a" and self.view.screen == "grid":
            flat = self._flat_apps()
            self.view.select_many([a["id"] for a in flat])
            self.refresh()
        elif key == "Delete" and self.view.sel:
            self._remove_apps(list(self.view.sel))
        elif e.ctrl and key in ("Enter", "Numpad Enter") and self.view.screen == "add":
            self.commit_add()
        elif key in ("Arrow Right", "Arrow Down"):
            self.move_selection(1)
        elif key in ("Arrow Left", "Arrow Up"):
            self.move_selection(-1)
        elif key in ("Enter", "Numpad Enter"):
            self.activate_selected()

    def _triage_key(self, key) -> bool:
        """1–4 категория, Enter предложенная, → пропустить, Del не нужно."""
        queue = self.inbox()
        if not queue:
            return False
        item = queue[0]
        picks = queries.suggest_categories(item, self.categories())
        if key in ("1", "2", "3", "4"):
            index = int(key) - 1
            if index < len(picks):
                self.triage_place(item["id"], picks[index]["id"])
            return True
        if key in ("Enter", "Numpad Enter"):
            if picks:
                self.triage_place(item["id"], picks[0]["id"])
            return True
        if key == "Arrow Right":
            self.triage_skip(item["id"])
            return True
        if key == "Delete":
            self.triage_drop(item["id"])
            return True
        return False

    def _capture_key(self, e):
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

    def _flat_apps(self, sections=None):
        return queries.flatten_sections(self._sections() if sections is None else sections)

    def _selected_id(self, sections=None):
        if self.view.inspector:
            return self.view.inspector
        flat = self._flat_apps(sections)
        if 0 <= self.selected < len(flat):
            return flat[self.selected]["id"]
        return None

    def move_selection(self, delta):
        # Same lock as refresh(): the list the selection indexes into and the
        # redraw that renders it must see one library, not two.
        with self._refresh_lock:
            flat = self._flat_apps()
            if not flat:
                self.selected = -1
                return
            self.view.move_selection(delta, len(flat))
            self.refresh()

    def activate_selected(self):
        if self.view.window == "launch":
            rows = queries.launch_rows(self.apps(), self.view.launch_query, self.running,
                                       self.categories())
            if not rows:
                return
            self._launch(rows[min(self.view.hi, len(rows) - 1)]["app"]["id"])
            return
        with self._refresh_lock:
            flat = self._flat_apps()
            if not flat:
                return
            idx = self.selected if 0 <= self.selected < len(flat) else 0
        self._launch(flat[idx]["id"])

    # =====================================================================
    # Действия
    # =====================================================================
    def _focus(self, field):
        # focus() asserts the control is on the page; it may not be mid-rebuild,
        # and that must not kill the key press that asked for it.
        try:
            if field.page:
                field.focus()
        except Exception:
            log.exception("focusing a field failed")

    def _toggle_sidebar(self):
        self.view.toggle_sidebar()
        self.refresh()

    def _set_filter(self, f):
        self.view.set_filter(f)
        self.search_field.value = ""
        self.refresh()

    def _set_mode(self, m):
        self.view.set_mode(m)
        self.refresh()

    def _set_sort(self, key):
        self.view.set_sort(key)
        self.refresh()

    def _cycle_sort(self):
        self.view.cycle_sort()
        self.refresh()

    def _on_search(self, e):
        self.view.set_query(e.control.value)
        self.refresh(content_only=True)

    def _on_launch_query(self, e):
        self.view.set_launch_query(e.control.value)
        self.refresh()

    def _clear_launch_query(self):
        self.view.set_launch_query("")
        self.launch_field.value = ""
        self.refresh()
        self._focus(self.launch_field)

    def _hover_row(self, index, e):
        if e.data == "true" and self.view.hi != index:
            self.view.hi = index
            self.refresh()

    def _select_tile(self, app_id):
        self.view.select_one(app_id)
        app = next((a for a in self.apps() if a["id"] == app_id), None)
        # "Параметры запуска" opens by itself when there is something in it.
        self.view.adv = bool(app and (app.get("args") or app.get("run_as_admin")
                                      or app.get("working_dir")))
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

    def _toast_hint_quick(self):
        self.toast.show("Закрепить можно правой кнопкой по плитке — «В быстрый запуск»",
                        icon=ft.Icons.BOLT, icon_color=C.MUTED)

    # ---- запуск ----
    def _launch(self, app_id, again: bool = False):
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
        if not again:
            self.toast.show(f"{app['name']} открыт", icon=ft.Icons.PLAY_ARROW)
        self._after_launch()

    def _launch_failed(self, app, message):
        missing = "не найден" in message.lower()
        self.toast.error(f"{app['name']} не нашёлся на диске" if missing else message,
                         detail="Программу переустановили или перенесли" if missing else None,
                         action=(lambda: self._relocate(app["id"])) if missing else None,
                         action_label="Найти" if missing else None)
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
        if self.setting("hide_after", True) and self.view.window == "launch":
            self.view.set_launch_query("")
            self.launch_field.value = ""
            self._hide_to_tray()
        self.refresh()

    def _relocate(self, app_id):
        """«Найти» on a missing program: point the entry at the file again."""
        self._relocating = app_id
        self.pick_file()

    # ---- правка ----
    def _toggle_fav(self, app_id):
        a = self.store.get_app(app_id)
        if a:
            self.store.update_app(app_id, {"favorite": not a.get("favorite")})
        self.refresh()

    def _toggle_quick(self, app_id, value):
        self.store.update_app(app_id, {"quick": bool(value)})
        self._on_library_changed()
        accel = quick_accels(self.store.state()["apps"]).get(app_id)
        self.toast.show(f"Закреплено · {accel}" if value and accel
                        else "Закреплено" if value else "Откреплено",
                        icon=ft.Icons.BOLT, icon_color=C.MUTED)

    def _toggle_set_quick(self, set_id, value):
        self.store.update_set(set_id, {"quick": bool(value)})
        self.refresh()

    def _set_hotkey(self, app_id, accel):
        if not app_id:
            self.refresh()
            return
        if accel:
            clash = next((a for a in self.apps()
                          if a["id"] != app_id
                          and (a.get("hotkey") or "").lower() == accel.lower()), None)
            if clash:
                self.toast.error(f"{accel} уже занята — «{clash['name']}»")
                self.refresh()
                return
        self.store.update_app(app_id, {"hotkey": accel})
        self._on_library_changed()
        self.toast.show(f"Горячая клавиша: {accel}" if accel else "Горячая клавиша убрана",
                        icon=ft.Icons.BOLT, icon_color=C.MUTED)

    def _set_args(self, app_id, value):
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

    def _pick_working_dir(self, app_id):
        picker = getattr(self, "_dir_picker", None)
        if picker is None:
            picker = ft.FilePicker()
            self._dir_picker = picker
            self.page.overlay.append(picker)
            self.page.update()

        def on_result(e):
            if e.path:
                self.store.update_app(app_id, {"working_dir": e.path})
                self.refresh()
        picker.on_result = on_result
        picker.get_directory_path(dialog_title="Выберите рабочую папку")

    def _move_apps_to_category(self, app_ids, cat_id):
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        ids = [i for i in app_ids if i]
        if not cat or not ids:
            return
        before = {a["id"]: a.get("category_id") for a in self.apps() if a["id"] in set(ids)}
        moved = self.store.update_apps(ids, {"category_id": cat_id})
        if not moved:
            return

        def undo():
            for app_id, old in before.items():
                self.store.update_app(app_id, {"category_id": old}, persist=False)
            self.store.flush()
            self._on_library_changed()

        first = next((a["name"] for a in self.apps() if a["id"] == ids[0]), "")
        text = (f"{first} переложен в «{cat['name']}»" if moved == 1
                else f"Переложено {moved} в «{cat['name']}»")
        self.toast.show(text, icon=ft.Icons.FOLDER, icon_color=C.MUTED,
                        action=undo, action_label="Вернуть")
        self._on_library_changed()

    def _bulk_favorite(self, ids):
        self.store.update_apps(ids, {"favorite": True})
        self.toast.show(f"В избранном: {len(ids)}", icon=ft.Icons.STAR, icon_color=C.STAR)
        self.refresh()

    def _make_set(self, ids):
        apps = [a for a in self.apps() if a["id"] in set(ids)]
        if len(apps) < 2:
            self.toast.error("Для набора нужно хотя бы две программы")
            return
        rec = self.store.add_set(queries.set_name_for(apps), [a["id"] for a in apps])
        if not rec:
            return
        self.view.clear_selection()
        self.toast.show(f"Набор «{rec['name']}» собран", icon=ft.Icons.LAYERS,
                        icon_color=C.MUTED,
                        action=lambda: self._undo_set(rec["id"]), action_label="Вернуть")
        self._on_library_changed()

    def _add_to_set(self, set_id, app_ids):
        rec = self.store.get_set(set_id)
        if not rec:
            return
        before = list(rec["apps"])
        merged = before + [i for i in app_ids if i not in before]
        if merged == before:
            self.toast.show(f"Уже в наборе «{rec['name']}»", icon=ft.Icons.LAYERS,
                            icon_color=C.MUTED)
            return
        self.store.update_set(set_id, {"apps": merged})
        self.toast.show(f"Добавлено в «{rec['name']}»", icon=ft.Icons.LAYERS,
                        icon_color=C.MUTED,
                        action=lambda: self._restore_set_members(set_id, before),
                        action_label="Вернуть")
        self.refresh()

    def _restore_set_members(self, set_id, members):
        self.store.update_set(set_id, {"apps": members})
        self.refresh()

    def _undo_set(self, set_id):
        self.store.remove_set(set_id)
        self._on_library_changed()

    def _remove_set(self, set_id):
        rec = self.store.remove_set(set_id)
        if not rec:
            return
        self.toast.show(f"Набор «{rec['name']}» удалён", icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=C.MUTED,
                        action=lambda: self._restore_set(rec), action_label="Вернуть")
        self.refresh()

    def _restore_set(self, rec):
        self.store.restore_set(rec)
        self.refresh()

    def _remove_apps(self, app_ids):
        if not app_ids:
            return
        gone = self.store.remove_apps(app_ids)
        if not gone:
            return
        self.view.close_inspector()
        text = (f"{gone[0]['name']} убран из библиотеки" if len(gone) == 1
                else f"Убрано {len(gone)} {plu_apps(len(gone))}")
        self.toast.show(text, icon=ft.Icons.DELETE_OUTLINE, icon_color=C.MUTED,
                        action=lambda: self._restore_apps(gone), action_label="Вернуть")
        self._on_library_changed()

    def _restore_apps(self, records):
        self.store.restore_apps(records)
        self._on_library_changed()

    # ---- категории ----
    def _add_category(self):
        cat = self.store.add_category("Новая категория")
        self.view.set_filter(f"category:{cat['id']}")
        self.view.open_popover(cat["id"])
        self._on_library_changed()

    def _move_category(self, cat_id, delta):
        self.store.move_category(cat_id, delta)
        self.refresh()

    def _open_popover(self, cat_id):
        self.view.open_popover(cat_id)
        self.refresh()

    def close_popover(self):
        self.view.close_popover()
        self.refresh()

    def rename_category(self, cat_id, name):
        if (name or "").strip():
            self.store.update_category(cat_id, {"name": name.strip()})
            self._on_library_changed()

    def set_category_color(self, cat_id, color):
        self.store.update_category(cat_id, {"color": color})
        self.refresh()

    def set_category_icon(self, cat_id, icon):
        self.store.update_category(cat_id, {"icon": icon, "image": None})
        self.refresh()

    def set_icon_query(self, text):
        self.view.icon_query = text or ""
        self.refresh()

    def pick_category_image(self, cat_id):
        """«Своя картинка»: copy the file next to the library and point at it."""
        picker = getattr(self, "_image_picker", None)
        if picker is None:
            picker = ft.FilePicker()
            self._image_picker = picker
            self.page.overlay.append(picker)
            self.page.update()

        def on_result(e):
            if not e.files:
                return
            src = e.files[0].path or e.files[0].name
            stored = self._store_category_image(cat_id, src)
            if stored:
                self.store.update_category(cat_id, {"image": stored})
                self.refresh()
        picker.on_result = on_result
        picker.pick_files(dialog_title="Картинка категории", allow_multiple=False,
                          allowed_extensions=["png", "svg"])

    def _store_category_image(self, cat_id, src) -> str | None:
        import shutil
        suffix = Path(src).suffix.lower()
        if suffix not in (".png", ".svg"):
            self.toast.error("Подойдёт PNG или SVG")
            return None
        dest_dir = Path(self.icon_cache_dir()) / "categories"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{cat_id}{suffix}"
            shutil.copyfile(src, dest)
        except OSError:
            log.exception("copying the category image failed")
            self.toast.error("Не удалось прочитать файл")
            return None
        return str(dest)

    def clear_category_image(self, cat_id):
        self.store.update_category(cat_id, {"image": None})
        self.refresh()

    def _remove_category(self, cat_id):
        if len(self.categories()) <= 1:
            self.toast.error("Это последняя категория — программам некуда деться")
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
        self.toast.show(text, icon=ft.Icons.DELETE_OUTLINE, icon_color=C.MUTED,
                        action=lambda: self._restore_category(undo), action_label="Вернуть")
        self._on_library_changed()

    def _restore_category(self, undo):
        self.store.restore_category(undo)
        self._on_library_changed()

    # ---- экраны ----
    def _open_add(self):
        self.view.set_window("library")
        self.view.set_screen("add")
        self.view.reset_add()
        self._notify_window()
        self.start_scan()
        self.refresh()

    def _open_settings(self):
        self.view.set_window("library")
        self.view.set_screen("settings")
        self._notify_window()
        self.refresh()

    def _open_triage(self):
        self.view.set_window("library")
        self.view.set_screen("triage")
        self._notify_window()
        self.refresh()

    def back_to_grid(self):
        self.view.set_screen("grid")
        self.refresh()

    def _open_launch(self):
        self.view.set_window("launch")
        self._notify_window()
        self.refresh()
        self._focus(self.launch_field)

    def _open_library(self):
        self.view.set_window("library")
        self.view.set_screen("grid")
        self._notify_window()
        self.refresh()

    def _notify_window(self):
        cb = self.controllers.get("set_window")
        if cb:
            cb(self.view.window)

    # ---- настройки ----
    def set_setting(self, key, value):
        self.store.set_setting(key, value)
        cb = self.controllers.get("on_setting")
        if cb:
            cb(key, value)
        self.refresh()

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

    def _on_library_changed(self):
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

    def _show_in_folder(self, app_id):
        a = self.store.get_app(app_id)
        if a:
            res = self.launcher.show_in_folder(a)
            if not res.get("ok"):
                self.toast.error(res.get("error", "Не найдено"))

    def _minimize(self):
        cb = self.controllers.get("minimize")
        if cb:
            cb()

    def _toggle_maximize(self):
        cb = self.controllers.get("toggle_maximize")
        if cb:
            cb()

    def _close(self):
        cb = self.controllers.get("close")
        if cb:
            cb()

    def _hide_to_tray(self):
        cb = self.controllers.get("hide_to_tray")
        if cb:
            cb()

    def _current_title(self):
        return queries.current_title(self.filter, self.query, self.categories())

    # =====================================================================
    # Сканирование, добавление, разбор
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

    def scanning(self) -> bool:
        with self._scan_lock:
            return self._scanning

    def scan_errors(self) -> list[dict]:
        with self._scan_lock:
            return list(self._scan_errors)

    def start_scan(self, force: bool = False):
        """Fill the add screen. Reuses a fresh result instead of rescanning."""
        with self._scan_lock:
            if self._scanning:
                return
            if not force and self.cached_discovery() is not None:
                return
            self._scanning = True
            self._scan_errors = []

        def work():
            from . import discovery
            report = {}
            try:
                if force:
                    # An explicit rescan is the user's way of saying "try
                    # again" — give artwork downloads another chance in case
                    # they were switched off while the machine was offline.
                    discovery.reset_cdn_state()
                found = discovery.discover_apps(self.icon_cache_dir(), report=report)
                self._remember_discovery(found)
                errors = report.get("errors") or []
            except Exception as exc:
                log.exception("scanning for installed programs failed")
                errors = [{"source": "", "label": "Поиск программ", "error": str(exc)}]
            with self._scan_lock:
                self._scanning = False
                self._scan_errors = errors
            self._safe_refresh()

        threading.Thread(target=work, daemon=True).start()

    def dismiss_scan_errors(self):
        with self._scan_lock:
            self._scan_errors = []
        self.refresh()

    def found_groups(self):
        found = self.cached_discovery() or []
        found = list(found) + list(getattr(self, "_manual_found", []))
        existing = {(a.get("path") or "").lower() for a in self.apps()}
        return queries.group_found(found, existing, self.categories(),
                                   only_new=self.view.only_new, query=self.view.add_query)

    def toggle_only_new(self):
        self.view.only_new = not self.view.only_new
        self.refresh()

    def set_add_query(self, text):
        self.view.add_query = text or ""
        self.refresh()

    def set_manual_path(self, text):
        self.view.manual_path = text or ""

    def add_manual_path(self, text=None):
        """The path field: type or paste an .exe instead of hunting for it."""
        raw = (text if text is not None else self.view.manual_path or "").strip().strip('"')
        if not raw:
            self.toast.error("Вставьте путь к программе")
            return
        if not os.path.isfile(raw):
            self.toast.error("Файл не найден", detail=raw)
            return
        from . import discovery
        name = Path(raw).stem.replace("-", " ").replace("_", " ").strip()
        item = {"name": (name[:1].upper() + name[1:]) if name else "Программа",
                "path": raw, "source": "manual",
                "icon": discovery.extract_icon(raw, self.icon_cache_dir())}
        found = list(getattr(self, "_manual_found", []))
        if any((f.get("path") or "").lower() == raw.lower() for f in found):
            self.toast.show("Этот путь уже в списке", icon=ft.Icons.CHECK_CIRCLE,
                            icon_color=C.MUTED)
            return
        found.append(item)
        self._manual_found = found
        self.view.manual_path = ""
        self.view.add_sel.add(raw.lower())
        self.toast.show(f"{item['name']} добавлен в список", icon=ft.Icons.LINK,
                        icon_color=C.MUTED)
        self.refresh()

    def toggle_add_row(self, row):
        if not row["is_new"]:
            self.toast.show(f"{row['name']} уже в библиотеке", icon=ft.Icons.CHECK_CIRCLE,
                            icon_color=C.MUTED)
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

    def _chosen_add_rows(self):
        rows = {r["key"]: r for g in self.found_groups() for r in g["rows"]}
        return [rows[k] for k in self.view.add_sel if k in rows and rows[k]["is_new"]]

    def commit_add(self):
        chosen = self._chosen_add_rows()
        if not chosen:
            self.toast.show("Отметьте хотя бы одну программу", icon=ft.Icons.CHECK_CIRCLE,
                            icon_color=C.MUTED)
            return
        added = []
        for row in chosen:
            item = row["item"]
            added.append(self.store.add_app({
                "name": item.get("name"), "path": item.get("path"), "icon": item.get("icon"),
                "icon_fit": item.get("icon_fit"), "sub": item.get("sub", ""),
                "track_exe": item.get("track_exe"), "poster": item.get("poster"),
                "category_id": self.add_category_for(row),
            }))
        self.view.reset_add()
        self._manual_found = []
        self.view.set_screen("grid")
        self.view.filter = "all"
        self.toast.show(f"Добавлено {len(added)} {plu_apps(len(added))}",
                        action=lambda: self._restore_added(added), action_label="Вернуть")
        self._on_library_changed()
        self._backfill_icons_async()

    def defer_add(self):
        """«Отложить в разбор»: queue the ticked rows instead of placing them."""
        chosen = self._chosen_add_rows()
        if not chosen:
            self.toast.show("Отметьте, что отложить", icon=ft.Icons.INBOX, icon_color=C.MUTED)
            return
        queued = self.store.queue_inbox([r["item"] for r in chosen])
        self.view.reset_add()
        self.view.set_screen("grid")
        self.toast.show(f"В разборе: {queued}", icon=ft.Icons.INBOX, icon_color=C.MUTED,
                        action=self._open_triage, action_label="Разобрать")
        self._on_library_changed()

    def _restore_added(self, records):
        self.store.remove_apps([r["id"] for r in records])
        self._on_library_changed()

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
        target = getattr(self, "_relocating", None)
        if target:
            # This picker was opened by «Найти» on a program that moved.
            self._relocating = None
            self.store.update_app(target, {"path": path, "icon": None, "poster": None})
            self.toast.show("Путь обновлён", icon=ft.Icons.CHECK)
            self._on_library_changed()
            self._backfill_icons_async()
            return
        if self.view.screen == "add":
            self.add_manual_path(path)
            return
        base = Path(path).stem.replace("-", " ").replace("_", " ").strip()
        name = (base[:1].upper() + base[1:]) if base else "Программа"
        item = {"name": name, "path": path, "source": "manual"}
        cat_id = queries.suggest_category(item, self.categories())
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        icon = discovery.extract_icon(path, self.icon_cache_dir()) if path else None
        record = self.store.add_app({"name": name, "path": path, "icon": icon,
                                     "category_id": cat_id})
        self.view.select_one(record["id"])
        self.toast.show(f"{name} добавлен в «{cat['name']}»" if cat else f"{name} добавлен",
                        icon=ft.Icons.AUTO_AWESOME, icon_color=C.MUTED,
                        action=lambda: self._cycle_category(record["id"]),
                        action_label="Другая")
        self._on_library_changed()

    def _cycle_category(self, app_id):
        cats = self.categories()
        if len(cats) < 2:
            return
        app = self.store.get_app(app_id)
        ids = [c["id"] for c in cats]
        current = app.get("category_id") if app else None
        index = ids.index(current) if current in ids else -1
        nxt = cats[(index + 1) % len(cats)]
        self.store.update_app(app_id, {"category_id": nxt["id"]})
        self.toast.show(f"Теперь в «{nxt['name']}»", icon=ft.Icons.FOLDER, icon_color=C.MUTED)
        self.refresh()

    def _backfill_icons_async(self):
        """Re-resolve icons off the UI thread — extracting one shells out."""
        def work():
            from . import discovery
            try:
                if discovery.backfill_icons(self.store, self.icon_cache_dir()):
                    self._on_library_changed()
            except Exception:
                log.exception("re-resolving icons after an add failed")
        threading.Thread(target=work, daemon=True).start()

    def rescan(self, silent: bool = False):
        """«Обновить список» and the 15-minute tick."""
        if not silent:
            self.toast.show("Смотрю, что установлено", icon=ft.Icons.SEARCH, icon_color=C.MUTED)

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
                if new and self.store.state()["settings"].get("triage", True):
                    queued = self.store.queue_inbox(new)
                    self._on_library_changed()
                    if queued:
                        word = "новая программа ждёт" if queued == 1 else "новые программы ждут"
                        self.toast.show(f"{queued} {word} в разборе", icon=ft.Icons.INBOX,
                                        icon_color=C.GREEN, action=self._open_triage,
                                        action_label="Разобрать")
                    return
                self._on_library_changed()
                if new:
                    self.toast.show(f"Нашлось нового: {len(new)}", icon=ft.Icons.SEARCH,
                                    icon_color=C.MUTED, action=self._open_add,
                                    action_label="Показать")
                elif not silent:
                    self.toast.show("Иконки обновлены" if changed else "Всё актуально")
            except Exception:
                log.exception("rescan failed")
                if not silent:
                    self.toast.error("Не удалось пересканировать",
                                     action=lambda: self.rescan(), action_label="Повторить")
        threading.Thread(target=work, daemon=True).start()

    # ---- разбор ----
    def triage_place(self, item_id, cat_id):
        item = self.store.take_inbox(item_id)
        if not item:
            return
        record = self.store.add_app({
            "name": item.get("name"), "path": item.get("path"), "icon": item.get("icon"),
            "icon_fit": item.get("icon_fit"), "sub": item.get("sub", ""),
            "track_exe": item.get("track_exe"), "poster": item.get("poster"),
            "category_id": cat_id})
        self._triage_done_count += 1
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        self.toast.show(f"{record['name']} → «{cat['name']}»" if cat else record["name"],
                        icon=ft.Icons.FOLDER, icon_color=C.MUTED,
                        action=lambda: self._undo_triage(record["id"], item),
                        action_label="Вернуть")
        self._on_library_changed()

    def _undo_triage(self, app_id, item):
        self._triage_done_count = max(0, self._triage_done_count - 1)
        self.store.remove_apps([app_id])
        self.store.restore_inbox(item)
        self._on_library_changed()

    def triage_skip(self, item_id):
        """→ : leave it in the queue, but stop showing it first."""
        item = self.store.take_inbox(item_id)
        if not item:
            return
        item["order"] = int(time.time() * 1000)
        self.store.restore_inbox(item)
        self.refresh()

    def triage_drop(self, item_id):
        item = self.store.take_inbox(item_id)
        if not item:
            return
        self.toast.show(f"{item['name']} не нужен", icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=C.MUTED,
                        action=lambda: self._restore_inbox(item), action_label="Вернуть")
        self.refresh()

    def _restore_inbox(self, item):
        self.store.restore_inbox(item)
        self.refresh()

    def triage_defer_all(self):
        gone = self.store.clear_inbox()
        if not gone:
            return
        self.view.set_screen("grid")
        self.toast.show(f"Очередь очищена · {len(gone)}", icon=ft.Icons.INBOX,
                        icon_color=C.MUTED,
                        action=lambda: self._restore_all_inbox(gone), action_label="Вернуть")
        self.refresh()

    def _restore_all_inbox(self, items):
        for item in items:
            self.store.restore_inbox(item)
        self.refresh()

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
        picked = getattr(self.view, "onboarding_sel", set())
        if key in picked:
            picked.discard(key)
        else:
            picked.add(key)
        self.view.onboarding_sel = picked
        self.refresh()

    def commit_onboarding(self):
        picked = getattr(self.view, "onboarding_sel", set())
        chosen = [s["app"] for s in self.onboarding_items()
                  if (s["app"].get("path") or "").lower() in picked]
        if not chosen:
            self.close_onboarding()
            return
        for item in chosen:
            self.store.add_app({
                "name": item.get("name"), "path": item.get("path"), "icon": item.get("icon"),
                "icon_fit": item.get("icon_fit"), "sub": item.get("sub", ""),
                "track_exe": item.get("track_exe"), "poster": item.get("poster"),
                "category_id": queries.suggest_category(item, self.categories()),
                "quick": True})
        self.view.onboarding = False
        self.store.set_setting("onboarded", True)
        self.toast.show(f"Готово — {len(chosen)} {plu_programs(len(chosen))} в быстром запуске")
        self._on_library_changed()
        self._backfill_icons_async()

    # ---- слои поверх окна ----
    def _render_popover(self):
        from . import dialogs
        cat_id = self.view.popover
        cat = next((c for c in self.categories() if c["id"] == cat_id), None)
        if cat is None or self.view.window != "library":
            self.popover_layer.visible = False
            self.popover_layer.content = None
            return
        index = [c["id"] for c in self.categories()].index(cat_id)
        # Rail geometry: title bar, 14px of padding, the three fixed buttons and
        # a divider above the first category, then 44px rows with 9px gaps.
        top = 46 + 14 + (3 + index) * (C.RAIL_BTN + 9) + 10
        height = getattr(getattr(self.page, "window", None), "height", None) or C.LIBRARY_H
        self.popover_layer.left = C.RAIL_W + 8
        self.popover_layer.top = max(54, min(top, height - 470))
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
            self.toast.error("Не удалось создать копию", action=self.backup,
                             action_label="Повторить")
            return
        self.toast.show(f"Копия сохранена: {path.name}", icon=ft.Icons.BACKUP,
                        icon_color=C.MUTED)

    def show_data_folder(self):
        res = self.launcher.show_in_folder({"path": str(self.store.path)})
        if not res.get("ok"):
            self.toast.error(res.get("error", "Папка не найдена"))

    def icon_cache_size(self) -> int:
        total = 0
        try:
            for entry in Path(self.icon_cache_dir()).rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            return 0
        return total

    def clear_icon_cache(self):
        removed = 0
        keep = {(c.get("image") or "") for c in self.categories()}
        try:
            for entry in Path(self.icon_cache_dir()).rglob("*"):
                if entry.is_file() and str(entry) not in keep:
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


def _short_path(path: str) -> str:
    """…\\Office16\\EXCEL.EXE — enough to tell two copies apart, no more."""
    if not path:
        return ""
    if "://" in path:
        return path
    parts = str(path).replace("/", "\\").split("\\")
    tail = "\\".join(parts[-2:]) if len(parts) > 2 else "\\".join(parts)
    return f"…\\{tail}" if len(parts) > 2 else tail


def _source_glyph(source: str) -> str:
    return queries.SOURCES.get(source or "", {}).get("icon", "apps")
