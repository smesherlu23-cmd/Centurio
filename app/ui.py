"""Окно. Одно.

Сверху вниз: шапка 52px с поиском по центру, тело — рельса категорий 72px,
боковая панель 232px, контент, инспектор 300px. Поверх тела открываются палитра
поиска (то, чем заменилось окно «Запуск»), плавающая панель массовых операций,
поповер категории и карточка первого запуска. Модальных окон нет ни одного.
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
from . import layout as L
from . import log
from . import menus
from . import queries
from . import windows as W
from .format import (T, cat_icon, plu_apps, plu_hits, plu_programs, plu_windows,
                     short_ago, time_ago)
from .hotkeys import free_quick_slot, quick_accels, set_accels
from .images import icon_image, img_b64, is_launcher_art
from .menus import MenuHost
from .store import Store
from .toast import ToastHost
from .view_state import ViewState

# How long a discover_apps() result stays good enough to reuse. Long enough to
# cover "rescan, then open «Найти и добавить»", short enough that a program
# installed meanwhile still shows up.
DISCOVERY_TTL = 120.0

# Перечисление окон — системный вызов на каждое окно плюс имя процесса на
# каждый pid. Инспектор и палитра спрашивают «сколько окон» на каждый кадр, так
# что ответ живёт вот столько.
WINDOW_TTL = 2.0

# Ширина шапки, которую занимают логотип и кнопки окна: поле поиска сжимается,
# когда окно слишком узкое, вместо того чтобы лезть под кнопки.
HEADER_SIDES_W = 320

QUICK_H = 88


class CenturioUI:
    def __init__(self, page: ft.Page, store: Store, launcher, controllers=None):
        self.page = page
        self.store = store
        self.launcher = launcher
        self.controllers = controllers or {}
        self.running: set[str] = set()
        self.view = ViewState(store)
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
        self._set_accels: dict[str, str] = {}
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
        self._win_lock = threading.Lock()
        self._win_snapshot: list[dict] = []
        self._win_at = 0.0
        # Сколько строк в палитре — считает _render_palette, показывает шапка.
        self._palette_count = 0

        self.toast = ToastHost(page)
        self.menu = MenuHost(page, on_dismiss=self._on_menu_dismissed)

        # Одно поле на всю программу: и поиск, и лончер. Фокус в нём открывает
        # палитру, Esc её закрывает. Поле, его иконка и хвост справа — постоянные
        # контролы: набор текста меняет их свойства, а не пересобирает шапку,
        # иначе фокус улетал бы на каждой букве.
        self.search_field = ft.TextField(
            value="", hint_text="Найти или запустить", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=13.5, color=C.WHITE,
            hint_style=ft.TextStyle(color=C.MUTED_2, size=13.5),
            cursor_color=C.ACCENT, on_change=self._on_search,
            on_focus=lambda e: self._open_palette(), expand=True,
        )
        self.search_icon = ft.Icon(ft.Icons.SEARCH, size=15, color=C.MUTED_2)
        self.search_tail = ft.Container()
        self.search_box = ft.Container(
            ft.Row([self.search_icon, self.search_field, self.search_tail],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=36, border_radius=10, padding=ft.padding.only(12, 0, 8, 0))

        self.header_holder = ft.Container()
        self.rail_container = ft.Container(width=C.RAIL_W, bgcolor=C.BG_0)
        self.sidebar_container = ft.Container(width=C.SIDEBAR_W, bgcolor=C.BG_2)
        self.content_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.content_holder = ft.Container(self.content_col, expand=True,
                                           padding=ft.padding.only(22, 4, 22, 0))
        self.toolbar_holder = ft.Container()
        self.inspector_container = ft.Container(width=C.INSPECTOR_W, bgcolor=C.BG_2,
                                                visible=False)
        # Ниже 1200px инспектор ложится поверх контента: тот же контрол, другое
        # место в дереве. Тень — чтобы он читался как лежащий сверху, а не как
        # обрезанная сетка.
        self.inspector_overlay = ft.Container(
            width=C.INSPECTOR_W, bgcolor=C.BG_2, right=0, top=C.HEADER_H, bottom=0,
            visible=False,
            shadow=ft.BoxShadow(blur_radius=40, offset=ft.Offset(-10, 0),
                                color=C.SHADOW_BAR))
        self.library_body = ft.Container(expand=True)
        self.body = ft.Container(left=0, top=0, right=0, bottom=0)

        # Палитра и панель действий появляются анимацией, поэтому их контейнеры
        # живут между кадрами: меняется содержимое, opacity и смещение, а не сам
        # контрол — иначе Flutter анимировать нечему.
        self.palette_card = ft.Container(
            opacity=0, offset=ft.Offset(0, -0.02),
            animate_opacity=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT))
        # Затемнение не анимируется: прозрачность уже в цвете, а AnimatedOpacity
        # на слое, который только что стал видимым, гасил его совсем.
        self.palette_scrim = ft.Container(
            left=0, top=C.HEADER_H, right=0, bottom=0, bgcolor=C.SCRIM_BODY,
            on_click=lambda e: self._close_palette())
        self.palette_layer = ft.Container(
            ft.Stack([self.palette_scrim,
                      ft.Container(ft.Row([self.palette_card],
                                          alignment=ft.MainAxisAlignment.CENTER),
                                   left=0, right=0, top=60)]),
            left=0, top=0, right=0, bottom=0, visible=False)
        self.bulk_card = ft.Container(
            opacity=0, offset=ft.Offset(0, 0.3),
            animate_opacity=ft.Animation(C.ANIM_BAR, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(C.ANIM_BAR, ft.AnimationCurve.EASE_OUT))
        self.bulk_layer = ft.Container(
            ft.Row([self.bulk_card], alignment=ft.MainAxisAlignment.CENTER),
            left=0, right=0, bottom=26, visible=False)
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

    def _window_width(self) -> float:
        win = getattr(self.page, "window", None)
        return getattr(win, "width", None) or C.LIBRARY_W

    def _window_height(self) -> float:
        win = getattr(self.page, "window", None)
        return getattr(win, "height", None) or C.LIBRARY_H

    def _show_sidebar(self) -> bool:
        return self.sidebar_open and self._window_width() >= C.NARROW_SIDEBAR

    def _inspector_floats(self) -> bool:
        return self._window_width() < C.NARROW_INSPECTOR

    def _content_width(self) -> float:
        """How wide the middle column is right now, panels taken off the top.

        page.window.width is None in web mode and before the window is up, so
        the design width stands in — it only decides whether something shrinks.
        """
        width = self._window_width() - C.RAIL_W
        if self._show_sidebar():
            width -= C.SIDEBAR_W
        if self._inspector_visible() and not self._inspector_floats():
            width -= C.INSPECTOR_W
        return max(240.0, width)

    def _inspector_visible(self) -> bool:
        return bool(self.view.inspector and self.view.screen == "grid"
                    and not self.view.active_set and not self.view.select_mode)

    # ---- окна других программ ----
    def _windows_snapshot(self) -> list[dict]:
        if not W.available():
            return []
        now = time.monotonic()
        with self._win_lock:
            if now - self._win_at <= WINDOW_TTL:
                return self._win_snapshot
        snapshot = W.list_windows()
        with self._win_lock:
            self._win_snapshot = snapshot
            self._win_at = time.monotonic()
        return snapshot

    def window_count(self, app) -> int:
        """How many windows this program has open right now, 0 when unknown."""
        if app["id"] not in self.running:
            return 0
        return W.count_for(W.exe_names_for(app), self._windows_snapshot())

    def _app_windows(self, app) -> list[dict]:
        return W.windows_for(W.exe_names_for(app), self._windows_snapshot())

    def running_note(self, app) -> str:
        """«открыто» или «открыто · 2 окна» — ровно то, что известно."""
        count = self.window_count(app)
        return f"открыто · {count} {plu_windows(count)}" if count > 1 else "открыто"

    # ---- жизненный цикл ----
    def mount(self):
        # A failed save no longer kills the click that caused it, so it has to
        # be said out loud — otherwise the app looks like it saved fine.
        self.store.on_error = self._on_store_error
        main = ft.Column([self.toolbar_holder, self.content_holder], spacing=0, expand=True)
        body = ft.Row([self.rail_container, self.sidebar_container, main,
                       self.inspector_container], spacing=0, expand=True)
        self.library_body.content = ft.Column([self.header_holder, body],
                                              spacing=0, expand=True)
        root = ft.Stack([self.body, self.inspector_overlay, self.palette_layer,
                         self.bulk_layer, self.popover_layer, self.onboarding_layer,
                         self.menu.control, self.toast.shade, self.toast.control],
                        expand=True)
        self.page.add(root)
        self.refresh()

    def set_running(self, ids):
        self.running = set(ids)
        # Окна пересчитывать заново: программа только что открылась или ушла.
        with self._win_lock:
            self._win_at = 0.0
        try:
            self.refresh()
        except Exception:
            log.exception("refreshing after a running-state change failed")

    def refresh(self, content_only=False):
        with self._refresh_lock:
            self._snapshot = self.store.state()
            self._settings = self._snapshot["settings"]
            self._accels = quick_accels(self._snapshot["apps"])
            self._set_accels = set_accels(self.sets())
            try:
                self.view.drop_missing(a["id"] for a in self._snapshot["apps"])
                if self.view.active_set and not any(
                        s["id"] == self.view.active_set for s in self._snapshot["sets"]):
                    self.view.close_set()
                self._refresh_library(content_only)
                self.body.content = self.library_body
                self._render_palette()
                self._render_bulk_bar()
                self._sync_search_box(self._palette_count)
                self._render_popover()
                self._render_onboarding()
            finally:
                self._snapshot = None
            self.page.update()

    def _refresh_library(self, content_only: bool):
        if not content_only:
            self.header_holder.content = self._build_header()
            self.rail_container.content = self._build_rail()
        show_sidebar = self._show_sidebar()
        self.sidebar_container.visible = show_sidebar
        self.sidebar_container.content = self._build_sidebar() if show_sidebar else None
        screen = self.view.screen
        on_grid = screen == "grid" and not self.view.active_set
        self.toolbar_holder.visible = on_grid
        if on_grid:
            self.toolbar_holder.content = self._build_toolbar()
        self.content_col.controls = self._build_content()
        # Прокручивает сетку только сама сетка. Экраны занимают всю высоту и
        # катают своё содержимое сами, а внутри скроллящейся колонки `expand`
        # не растягивает — от этого «Разбор» и «Настройки» сжимались к шапке.
        self.content_col.scroll = ft.ScrollMode.AUTO if on_grid else None
        self.content_holder.padding = (ft.padding.only(22, 4, 22, 0) if on_grid
                                       else ft.padding.all(0))
        inspector = self._build_inspector() if self._inspector_visible() else None
        floating = inspector is not None and self._inspector_floats()
        self.inspector_container.visible = inspector is not None and not floating
        self.inspector_container.content = None if floating else inspector
        self.inspector_overlay.visible = floating
        self.inspector_overlay.content = inspector if floating else None

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

    def _key_chip(self, label, bright=False):
        """Бейдж хоткея: тёмный в шапке, светлый — «Enter» у строки палитры."""
        return ft.Container(
            T(label, size=10.5, weight=ft.FontWeight.W_600 if bright else None,
              color=C.ON_ACCENT if bright else C.SLOT_GLYPH, font_family="monospace"),
            bgcolor=self._accent() if bright else C.PANEL_3,
            border=None if bright else ft.border.all(1, C.CONTROL),
            border_radius=5, padding=ft.padding.symmetric(3, 7))

    def _toggle(self, value: bool, on_toggle):
        """The one switch in the program: 34×19, knob 14."""
        knob = ft.Container(width=14, height=14, border_radius=7,
                            bgcolor=C.ON_ACCENT if value else C.MUTED_2)
        return ft.Container(
            ft.Row([knob], alignment=ft.MainAxisAlignment.END if value
                   else ft.MainAxisAlignment.START),
            width=34, height=19, border_radius=10, padding=ft.padding.all(2.5),
            bgcolor=self._accent() if value else C.LINE_4,
            on_click=lambda e: on_toggle(not value),
            animate=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT))

    def primary_btn(self, label, on_click, icon=None, height=36, expand=False,
                    hint: str = ""):
        row = [T(label, size=13 if height >= 38 else 12.5, weight=ft.FontWeight.W_600,
                 color=C.ON_ACCENT)]
        if icon:
            row.insert(0, ft.Icon(icon, size=15, color=C.ON_ACCENT))
        if hint and not self.calm():
            row.append(T(hint, size=10.5, color=C.ON_ACCENT, opacity=0.55,
                         font_family="monospace"))
        btn = ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 14), bgcolor=self._accent(),
            border_radius=9, alignment=ft.alignment.center, expand=expand,
            on_click=lambda e: on_click())
        return self._hoverable(btn, self._accent(), C.WHITE)

    def icon_btn(self, icon, on_click, tooltip, accent=False, height=34, active=False,
                 size=15):
        """The label-less form of a button, for when the toolbar runs out of room."""
        color = C.ON_ACCENT if accent else (C.TEXT if active else C.MUTED)
        btn = ft.Container(
            ft.Icon(icon, size=size, color=color),
            width=height, height=height, alignment=ft.alignment.center,
            bgcolor=self._accent() if accent else (C.PANEL_ACTIVE if active else None),
            border=None if accent else ft.border.all(1, C.CONTROL),
            border_radius=9, tooltip=tooltip, on_click=lambda e: on_click())
        return btn if accent or active else self._hoverable(btn, None, C.SELECTED_BG)

    def outline_btn(self, label, on_click, icon=None, danger=False, height=34,
                    active=False, icon_color=None, weight=None):
        color = C.ERR_TEXT if danger else (C.TEXT if active else C.TEXT_2)
        row = [T(label, size=12.5,
                 weight=weight or (ft.FontWeight.W_600 if danger or active
                                   else ft.FontWeight.W_500), color=color)]
        if icon:
            row.insert(0, ft.Icon(icon, size=14,
                                  color=C.ERR_TEXT if danger
                                  else (icon_color or (C.TEXT if active else C.MUTED))))
        btn = ft.Container(
            ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            height=height, padding=ft.padding.symmetric(0, 12),
            bgcolor=C.PANEL_ACTIVE if active else None,
            border=ft.border.all(1, C.ERR_BORDER if danger
                                 else (C.LINE_5 if active else C.CONTROL)),
            border_radius=9, alignment=ft.alignment.center,
            on_click=lambda e: on_click())
        return btn if active else self._hoverable(btn, None, C.SELECTED_BG)

    def quiet_btn(self, label, on_click, size=12.5, color=C.MUTED):
        """Кнопка без рамки: «Сортировка», «Отмена», подписи-действия."""
        btn = ft.Container(
            T(label, size=size, color=color),
            height=34, padding=ft.padding.symmetric(0, 12), border_radius=9,
            alignment=ft.alignment.center, on_click=lambda e: on_click())
        return self._hoverable(btn, None, C.SET_SLOT_BG)

    def link_btn(self, label, on_click):
        return ft.Container(
            T(label, size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT),
            border=ft.border.only(bottom=ft.BorderSide(1, C.TEXT_FAINT)),
            padding=ft.padding.only(0, 0, 0, 2), on_click=lambda e: on_click())

    def spinner(self, size=38):
        """Всё, что показывает сканирование: кружок и слово рядом с ним."""
        return ft.ProgressRing(width=size, height=size, stroke_width=2.5,
                               color=C.TEXT, bgcolor=C.CONTROL)

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
                  border=None, glyph_color=None, bgcolor=None):
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
            inner, width=size, height=size, border_radius=radius,
            bgcolor=bgcolor or C.SLOT_BG,
            border=ft.border.all(1, border or C.SLOT_BORDER), alignment=ft.alignment.center,
            clip_behavior=ft.ClipBehavior.HARD_EDGE)

    def set_slot(self, size: int, radius: int, glyph: int, muted=False):
        """Плашка набора: layers вместо иконки, тише обычной."""
        return ft.Container(
            ft.Icon(ft.Icons.LAYERS, size=glyph, color=C.TEXT_FAINT if muted else C.MUTED),
            width=size, height=size, border_radius=radius, bgcolor=C.SET_SLOT_BG,
            border=ft.border.all(1, C.SET_SLOT_BORDER if muted else C.CONTROL),
            alignment=ft.alignment.center)

    def _dot(self, size=6, color=C.GREEN):
        return ft.Container(width=size, height=size, border_radius=4, bgcolor=color)

    # =====================================================================
    # Шапка
    # =====================================================================
    def _win_btn(self, icon_name, tooltip, handler, danger=False):
        c = ft.Container(
            ft.Icon(icon_name, size=14, color=C.MUTED),
            width=40, height=32, border_radius=6, alignment=ft.alignment.center,
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

    def _sync_search_box(self, matches: int = 0):
        """Поле поиска в двух состояниях — спокойном и открытом."""
        from .hotkeys import format_accel
        active = self.view.palette_open
        room = self._window_width() - HEADER_SIDES_W
        self.search_box.width = max(C.SEARCH_MIN_W, min(C.SEARCH_W, room))
        self.search_box.bgcolor = C.FIELD_ACTIVE_BG if active else C.PANEL
        self.search_box.border = ft.border.all(
            1, C.FIELD_ACTIVE_BORDER if active else C.CONTROL)
        self.search_icon.color = C.TEXT_2 if active else C.MUTED_2
        if active:
            tail = []
            # Счётчик — про набранное. На пустом запросе палитра просто предлагает
            # недавнее, и «6 совпадений» там означало бы совпадение ни с чем.
            if self.view.query.strip() and not self.calm():
                tail.append(T(f"{matches} {plu_hits(matches)}", size=11, color=C.MUTED_2))
            tail.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=15, color=C.MUTED_2),
                                     tooltip="Закрыть поиск",
                                     on_click=lambda e: self._close_palette()))
            self.search_tail.content = ft.Row(tail, spacing=10, tight=True,
                                              vertical_alignment=ft.CrossAxisAlignment.CENTER)
        elif self.calm():
            self.search_tail.content = None
        else:
            self.search_tail.content = self._key_chip(
                format_accel(self.setting("launch_hotkey")))

    def _build_header(self):
        logo = ft.WindowDragArea(
            ft.Container(T("Centurio", size=13.5, weight=ft.FontWeight.BOLD, color=C.TEXT),
                         width=150, padding=ft.padding.only(18, 0, 0, 0),
                         alignment=ft.alignment.center_left))
        centre = ft.Container(
            ft.Row([ft.WindowDragArea(ft.Container(height=36), expand=True),
                    self.search_box,
                    ft.WindowDragArea(ft.Container(height=36), expand=True)],
                   spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            expand=True)
        buttons = ft.Container(
            ft.Row([self._win_btn(ft.Icons.REMOVE, "Свернуть", self._minimize),
                    self._win_btn(ft.Icons.CROP_SQUARE, "Развернуть", self._toggle_maximize),
                    self._win_btn(ft.Icons.CLOSE, "Закрыть", self._close, danger=True)],
                   spacing=2, alignment=ft.MainAxisAlignment.END),
            width=150, alignment=ft.alignment.center_right)
        return ft.Container(
            ft.Row([logo, centre, buttons], spacing=16,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=C.HEADER_H, bgcolor=C.BG_1,
            border=ft.border.only(bottom=ft.BorderSide(1, C.LINE_2)),
            padding=ft.padding.only(0, 0, 6, 0),
        )

    # =====================================================================
    # Рельса категорий
    # =====================================================================
    def _rail_item(self, glyph, active, on_click, tooltip, fixed_color=None,
                   on_drop_app=None, on_context=None, badge=None, outlined=False):
        inner = ft.Container(
            glyph, width=C.RAIL_BTN, height=C.RAIL_BTN,
            border_radius=14 if active else 21,
            bgcolor=C.PANEL_ACTIVE if active else C.RAIL_BTN_BG,
            border=ft.border.all(1, C.LINE_4) if outlined else None,
            alignment=ft.alignment.center, tooltip=tooltip,
            animate=ft.Animation(C.ANIM_BAR, ft.AnimationCurve.EASE_OUT),
        )

        def on_hover(e):
            if active:
                return
            highlight = e.data == "true"
            inner.bgcolor = C.PANEL_ACTIVE if highlight else C.RAIL_BTN_BG
            inner.border_radius = 14 if highlight else 21
            if fixed_color is None and isinstance(inner.content, ft.Icon):
                inner.content.color = C.TEXT if highlight else C.MUTED
            inner.update()
        inner.on_hover = on_hover

        button = inner
        if badge is not None:
            button = ft.Stack([inner, ft.Container(badge, right=-3, top=-3)],
                              width=C.RAIL_BTN + 6, height=C.RAIL_BTN + 6)

        tapper = ft.GestureDetector(
            button, mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: on_click(),
            on_secondary_tap_down=(lambda e: on_context(e)) if on_context else None)

        content = tapper
        if on_drop_app is not None:
            def _accept(e):
                src = self.page.get_control(e.src_id)
                payload = getattr(src, "data", None) if src is not None else None
                inner.border = ft.border.all(1, C.LINE_4) if outlined else None
                inner.update()
                if isinstance(payload, dict) and payload.get("ids"):
                    on_drop_app(payload["ids"])
                elif payload:
                    on_drop_app([payload])

            def _will(e):
                inner.border = ft.border.all(2, self._accent())
                inner.update()

            def _leave(e):
                inner.border = ft.border.all(1, C.LINE_4) if outlined else None
                inner.update()
            content = ft.DragTarget(group="apps", content=tapper,
                                    on_accept=_accept, on_will_accept=_will, on_leave=_leave)

        bar = ft.Container(width=3, height=26, border_radius=ft.border_radius.only(0, 3, 0, 3),
                           bgcolor=self._accent()) if active else ft.Container(width=3)
        return ft.Row([bar, ft.Container(content, expand=True, alignment=ft.alignment.center)],
                      spacing=0)

    def _is_all_view(self):
        return self.view.is_all_view()

    def _inbox_badge(self, count: int):
        return ft.Container(
            T(str(count if count < 100 else 99), size=10, weight=ft.FontWeight.BOLD,
              color=C.ON_ACCENT, font_family="monospace"),
            height=17, border_radius=9, bgcolor=self._accent(),
            padding=ft.padding.symmetric(0, 5), alignment=ft.alignment.center)

    def _build_rail(self):
        on_grid = self.view.screen == "grid" and not self.view.active_set
        all_active = self._is_all_view() and on_grid
        waiting = len(self.inbox())
        # Кнопка панели переехала сюда со звезды: «Избранное» уже есть строкой в
        # самой панели, а показывать/скрывать её — такое же переключение вида,
        # как «Все программы», и место рядом с ним для этого естественное.
        items = [
            self._rail_item(ft.Icon(ft.Icons.GRID_VIEW, size=19,
                                    color=C.TEXT if all_active else C.MUTED),
                            all_active, lambda: self._set_filter("all"), "Все программы"),
            self._rail_item(ft.Icon(ft.Icons.VIEW_SIDEBAR, size=18,
                                    color=C.TEXT if self.sidebar_open else C.MUTED),
                            self.sidebar_open, lambda: self._toggle_sidebar(),
                            "Показать/скрыть панель"),
            ft.Container(width=30, height=1, bgcolor=C.LINE_2,
                         margin=ft.margin.symmetric(3, 0)),
        ]
        for cat in self.categories():
            active = self.filter == f"category:{cat['id']}" and on_grid
            items.append(self._rail_item(
                self._cat_glyph(cat, color=C.TEXT if active else None), active,
                lambda cid=cat["id"]: self._set_filter(f"category:{cid}"), cat["name"],
                fixed_color=C.category_color(cat),
                on_drop_app=lambda ids, cid=cat["id"]: self._move_apps_to_category(ids, cid),
                on_context=lambda e, c=cat: self._category_menu(c, e)))
        add = ft.Container(ft.Icon(ft.Icons.ADD, size=16, color=C.TEXT_FAINT),
                           width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=21,
                           alignment=ft.alignment.center,
                           border=ft.border.all(1.5, C.CONTROL),
                           on_click=lambda e: self._add_category(),
                           tooltip="Добавить категорию")
        items += [ft.Row([ft.Container(width=3),
                          ft.Container(add, expand=True, alignment=ft.alignment.center)],
                         spacing=0),
                  ft.Container(expand=True)]
        triage_active = self.view.screen == "triage"
        items.append(self._rail_item(
            ft.Icon(ft.Icons.INBOX, size=18, color=C.TEXT if triage_active else C.TEXT_2),
            triage_active, lambda: self._open_triage(),
            f"Разбор · {waiting}" if waiting and not self.calm() else "Разбор",
            badge=self._inbox_badge(waiting) if waiting and not self.calm() else None,
            outlined=True))
        settings = ft.Container(ft.Icon(ft.Icons.SETTINGS, size=18,
                                        color=C.TEXT if self.view.screen == "settings"
                                        else C.MUTED_2),
                                width=C.RAIL_BTN, height=C.RAIL_BTN, border_radius=21,
                                alignment=ft.alignment.center,
                                on_click=lambda e: self._open_settings(), tooltip="Настройки")
        items += [ft.Container(height=4), settings]
        return ft.Container(
            ft.Column(items, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      expand=True),
            padding=ft.padding.only(0, 14, 0, 12),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    # =====================================================================
    # Боковая панель
    # =====================================================================
    def _sidebar_filter(self, icon_ctl, label, count, key, count_color=None):
        active = self.filter == key and self.view.screen == "grid" and not self.view.active_set
        row = ft.Container(
            ft.Row([
                ft.Container(icon_ctl, width=16, height=16, alignment=ft.alignment.center),
                T(label, size=13, color=C.TEXT if active else C.TEXT_2,
                  weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400, expand=True),
                T("" if self.calm() else str(count), size=11,
                  color=count_color or C.MUTED_2, font_family="monospace"),
            ], spacing=11),
            padding=ft.padding.symmetric(7, 10), border_radius=9,
            bgcolor=C.SET_SLOT_BG if active else None,
            border=ft.border.all(1, C.CONTROL) if active else None,
            on_click=lambda e: self._set_filter(key),
        )
        if not active:
            self._hoverable(row, None, C.SET_SLOT_BG)
        return row

    def _build_sidebar(self):
        apps = self.apps()
        shown = queries.visible(apps)
        fav = sum(1 for a in shown if a.get("favorite"))
        recent_count = sum(1 for a in shown if a.get("last_launched"))
        buried = sum(1 for a in apps if a.get("hidden"))

        top = [ft.Container(T(self._current_title(), size=18, weight=ft.FontWeight.BOLD,
                              color=C.TEXT, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS),
                            padding=ft.padding.only(8, 0, 8, 0))]
        if not self.calm():
            total = len(self._visible_apps())
            subtitle = (f"{total} · выбрано {len(self.view.sel)}"
                        if self.view.select_mode else str(total))
            top.append(ft.Container(T(subtitle, size=11.5, color=C.MUTED_2, no_wrap=True,
                                      overflow=ft.TextOverflow.ELLIPSIS),
                                    padding=ft.padding.only(8, 4, 8, 0)))
        top += [
            ft.Container(height=1, bgcolor=C.LINE_2, margin=ft.margin.symmetric(10, 0)),
            self._sidebar_filter(ft.Icon(ft.Icons.STAR, size=16, color=C.STAR),
                                 "Избранное", fav, "favorites"),
            self._sidebar_filter(ft.Icon(ft.Icons.SCHEDULE, size=16, color=C.MUTED),
                                 "Недавние", recent_count, "recent"),
            self._sidebar_filter(self._dot(8), "Запущено", len(self.running), "running",
                                 C.GREEN),
        ]
        if buried:
            # Появляется только когда есть что показать: иначе «Скрыть» из
            # массовых операций был бы дорогой в одну сторону.
            top.append(self._sidebar_filter(
                ft.Icon(ft.Icons.VISIBILITY_OFF, size=16, color=C.MUTED),
                "Скрытые", buried, "hidden"))

        top += [ft.Container(height=1, bgcolor=C.LINE_2, margin=ft.margin.symmetric(10, 0)),
                ft.Container(ft.Row([self._caps("НАБОРЫ"), ft.Container(expand=True),
                                     ft.Container(ft.Icon(ft.Icons.ADD, size=15,
                                                          color=C.MUTED_2),
                                                  tooltip="Собрать набор из выбранного",
                                                  on_click=lambda e: self._new_set())],
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                             padding=ft.padding.only(10, 0, 10, 8))]

        sets_block = []
        if self.view.select_mode:
            sets_block.append(self._set_drop_hint())
        records = self.sets()
        for rec in records:
            sets_block.append(self._sidebar_set_row(rec))
        if not records and not self.view.select_mode:
            sets_block.append(ft.Container(
                T("Выберите плитки и нажмите «плюс»", size=11.5, color=C.TEXT_DIM),
                padding=ft.padding.only(10, 0, 10, 4)))

        # Прокручивается только список наборов. Заголовок раздела и подвал стоят
        # на своих местах, а `expand` внутри скроллящейся колонки Flet понимает
        # как «растянись» — от этого весь блок уезжал в середину панели.
        return ft.Container(
            ft.Column([ft.Column(top, spacing=3, tight=True),
                       ft.Column(sets_block, spacing=3, expand=True,
                                 scroll=ft.ScrollMode.AUTO),
                       self._sidebar_footer()],
                      spacing=3, expand=True),
            padding=ft.padding.only(14, 20, 14, 12),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    def _sidebar_set_row(self, rec):
        active = self.view.active_set == rec["id"]
        lines = [T(rec["name"], size=12.5, weight=ft.FontWeight.W_500,
                   color=C.TEXT if active else C.TEXT_2, max_lines=1,
                   overflow=ft.TextOverflow.ELLIPSIS)]
        if not (self.calm() or self.view.select_mode):
            lines.append(T(queries.set_summary(rec), size=10.5, color=C.MUTED_2,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        row = ft.Container(
            ft.Row([ft.Container(ft.Icon(ft.Icons.LAYERS, size=16,
                                         color=C.TEXT_2 if active else C.MUTED),
                                 width=16, height=16, alignment=ft.alignment.center),
                    ft.Column(lines, spacing=1, expand=True, tight=True)], spacing=10),
            padding=ft.padding.symmetric(8, 10), border_radius=9,
            bgcolor=C.SET_SLOT_BG if active else None,
            border=ft.border.all(1, C.CONTROL) if active else None,
            on_click=lambda e, sid=rec["id"]: self._open_set(sid))
        if not active:
            self._hoverable(row, None, C.SET_SLOT_BG)
        rest = C.CONTROL if active else None
        return ft.DragTarget(
            group="apps", content=ft.GestureDetector(
                row, on_secondary_tap_down=lambda e, r=rec: self._set_menu(r, e)),
            on_accept=lambda e, sid=rec["id"]: self._drop_on_set(sid, e, row, rest),
            on_will_accept=lambda e, r=row: self._highlight_drop(r, True, rest),
            on_leave=lambda e, r=row: self._highlight_drop(r, False, rest))

    def _set_drop_hint(self):
        row = ft.Container(
            ft.Row([ft.Container(ft.Icon(ft.Icons.LAYERS, size=16, color=C.MUTED),
                                 width=16, height=16, alignment=ft.alignment.center),
                    T("Перетащите сюда", size=12, color=C.MUTED, expand=True,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                   spacing=10),
            padding=ft.padding.symmetric(8, 10), border_radius=9,
            border=ft.border.all(1, C.BAR_BORDER),
            on_click=lambda e: self._new_set())
        return ft.DragTarget(
            group="apps", content=row,
            on_accept=lambda e, r=row: self._drop_new_set(e, r),
            on_will_accept=lambda e, r=row: self._highlight_drop(r, True, C.BAR_BORDER),
            on_leave=lambda e, r=row: self._highlight_drop(r, False, C.BAR_BORDER))

    def _highlight_drop(self, row, on: bool, rest=None):
        """Цель под грузом обводится акцентом и возвращается к своей рамке."""
        row.border = (ft.border.all(1, self._accent()) if on
                      else (ft.border.all(1, rest) if rest else None))
        try:
            row.update()
        except Exception:
            log.exception("highlighting a drop target failed")

    def drop_set_item(self, set_id, target_id, e, row, rest=C.LINE):
        """Строку набора уронили на другую — переставить перед ней."""
        self._highlight_drop(row, False, rest)
        src = self.page.get_control(e.src_id)
        moved = getattr(src, "data", None) if src is not None else None
        rec = self.store.get_set(set_id)
        if not rec or not isinstance(moved, str) or moved == target_id:
            return
        order = [i["app_id"] for i in rec["items"] if i["app_id"] != moved]
        if target_id not in order:
            return
        order.insert(order.index(target_id), moved)
        self.store.reorder_set_items(set_id, order)
        self.refresh()

    def _dropped_ids(self, e) -> list[str]:
        src = self.page.get_control(e.src_id)
        payload = getattr(src, "data", None) if src is not None else None
        if isinstance(payload, dict) and payload.get("ids"):
            return list(payload["ids"])
        return [payload] if payload else []

    def _drop_on_set(self, set_id, e, row, rest=None):
        self._highlight_drop(row, False, rest)
        ids = self._dropped_ids(e)
        if ids:
            self._add_to_set(set_id, ids)

    def _drop_new_set(self, e, row):
        self._highlight_drop(row, False, C.BAR_BORDER)
        ids = self._dropped_ids(e)
        if ids:
            self._make_set(ids)

    def _sidebar_footer(self):
        left = T("" if self.calm() or not self.running
                 else f"{len(self.running)} запущено", size=11, color=C.MUTED_3)
        return ft.Container(
            ft.Row([left,
                    T(f"v{__version__}", size=11, color=C.MUTED_3, font_family="monospace")],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)),
            padding=ft.padding.only(10, 10, 10, 0),
        )

    # =====================================================================
    # Тулбар контента
    # =====================================================================
    def _build_toolbar(self):
        select = self.outline_btn(
            "Выбрать",
            self._toggle_select_mode,
            ft.Icons.CHECK_BOX if self.view.select_mode
            else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
            active=self.view.select_mode)
        left = [select]
        if self.view.select_mode:
            label = ("Выбрать всё" if self._is_all_view()
                     else f"Выбрать всё в «{self._current_title()}»")
            left.append(self.outline_btn(label, self._select_all_visible))
        sort_btn = ft.Container(
            ft.Row([T(queries.SORT_LABELS[self.sort], size=12.5, color=C.MUTED),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.MUTED_2)],
                   spacing=7),
            height=34, padding=ft.padding.symmetric(0, 12),
            border=ft.border.all(1, C.CONTROL), border_radius=9,
            on_click=lambda e: self._sort_menu(e), alignment=ft.alignment.center,
            tooltip="Порядок плиток",
        )
        self._hoverable(sort_btn, None, C.SELECTED_BG)

        def view_btn(icon_name, m, tip):
            active = self.mode == m
            return ft.Container(ft.Icon(icon_name, size=13,
                                        color=C.TEXT if active else C.MUTED_2),
                                width=34, height=34, alignment=ft.alignment.center,
                                bgcolor=C.PANEL_ACTIVE if active else None,
                                on_click=lambda e: self._set_mode(m), tooltip=tip)
        view_toggle = ft.Container(
            ft.Row([view_btn(ft.Icons.GRID_VIEW, "grid", "Сетка"),
                    view_btn(ft.Icons.VIEW_LIST, "list", "Список")], spacing=0),
            border=ft.border.all(1, C.CONTROL), border_radius=9,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        # Подсказка описывает то, что действительно работает: модификаторов в
        # событии клика Flet не отдаёт, диапазон берут правой кнопкой.
        right = (T("Клик — отметить · Ctrl+A — всё · правая кнопка — до этой",
                   size=11.5, color=C.MUTED_2)
                 if self.view.select_mode and not self.calm() else
                 self.primary_btn("Добавить", self._open_add, ft.Icons.ADD, height=34))
        return ft.Container(
            ft.Row(left + [sort_btn, view_toggle, ft.Container(expand=True), right],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(22, 16, 22, 10),
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
        if self.view.active_set:
            rec = next((s for s in self.sets() if s["id"] == self.view.active_set), None)
            if rec is not None:
                return [dialogs.build_set_screen(self, rec)]

        apps = self.apps()
        if not apps and not self.sets():
            self._sel_id = None
            return [self._empty("Библиотека пуста",
                                "Centurio посмотрит, что установлено, и предложит отметить "
                                "нужное. Можно и указать файл вручную.",
                                "Найти и добавить", self._open_add)]

        # build_sections() filters and sorts the whole library, so it runs once
        # per pass and the keyboard selection reads the same result.
        sections = self._sections()
        self._sel_id = self._selected_id(sections)

        controls = []
        if self._is_all_view() and self.setting("show_quick_row", True) \
                and not self.view.select_mode:
            controls += self._quick_row()

        if not sections or all(not s["apps"] for s in sections):
            controls.append(self._empty_section())
            return controls

        for sec in sections:
            if not sec["apps"]:
                continue
            controls.append(self._section_head(sec))
            if sec.get("cid") and sec["cid"] in self.view.collapsed \
                    and not self.view.select_mode:
                continue
            controls.append(self._grid(sec["apps"]) if self.mode == "grid"
                            else self._list(sec["apps"]))
        controls.append(ft.Container(height=self._bottom_gap()))
        return controls

    def _bottom_gap(self) -> int:
        """Место под плавающей панелью, чтобы она не накрывала последний ряд."""
        return 96 if self.view.select_mode and self.view.sel else 12

    def _sections(self):
        return queries.build_sections(self.apps(), self.categories(), self.filter,
                                      self.sort, self.running)

    def _visible_apps(self):
        """Сколько программ в текущем разделе — число под заголовком панели."""
        return queries.flatten_sections(self._sections())

    def _empty_section(self):
        if self.filter == "hidden":
            return self._empty("Ничего не скрыто",
                               "«Скрыть» в панели массовых операций убирает плитки "
                               "отсюда, не удаляя их.", None, None)
        return self._empty("Здесь пока пусто",
                           "Добавьте программы — или перетащите плитку на значок "
                           "категории слева.", "Добавить", self._open_add)

    # ---- лента быстрого запуска ----
    def _quick_row(self):
        cards = [self._set_card(s) for s in self.sets() if s.get("quick")]
        for app in queries.quick_apps(queries.visible(self.apps())):
            # accels comes from hotkeys.quick_accels() — the same map the global
            # listener registers, so the number can't promise a key that
            # launches something else.
            cards.append(self._quick_card(app, self._accels.get(app["id"])))
        free = free_quick_slot(self.apps())
        if free and self._fits_in_row(len(cards)):
            # Пустое место дописывается только если оно встанет в тот же ряд:
            # одинокая пунктирная карточка на второй строке — это 98px пустоты
            # ради подсказки.
            cards.append(self._quick_empty(free))

        head_row = [T("Быстрый запуск", size=14.5, weight=ft.FontWeight.BOLD, color=C.TEXT)]
        if not self.calm():
            head_row.append(T("Ctrl+1…9", size=11, color=C.MUTED_2, font_family="monospace"))
        head = ft.Container(ft.Row(head_row, spacing=10), padding=ft.padding.only(0, 8, 0, 12))
        return [head, ft.Container(ft.Row(cards, spacing=10, wrap=True, run_spacing=10),
                                   padding=ft.padding.only(0, 0, 0, 18))]

    def _fits_in_row(self, count: int) -> bool:
        """Есть ли в текущем ряду ленты место для ещё одной карточки."""
        gap = 10
        per_row = max(1, int((self._content_width() - 44 + gap) // (C.QUICK_W + gap)))
        return count % per_row != 0

    def _quick_card(self, app, accel):
        layers = [ft.Column([
            self.icon_slot(app, 38, 11, glyph=20),
            ft.Container(height=8),
            T(app["name"], size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT,
              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=0, tight=True)]
        if accel and not self.calm():
            # The card shows the position, not the whole combination — the
            # header already says these are Ctrl+1…9.
            layers.append(ft.Container(
                T(accel.split("+")[-1], size=10.5, weight=ft.FontWeight.W_600,
                  color=C.TEXT_FAINT, font_family="monospace"), right=9, top=9))
        card = ft.Container(
            ft.Stack(layers), width=C.QUICK_W, height=QUICK_H, bgcolor=C.PANEL,
            border=ft.border.all(1, C.CONTROL), border_radius=12,
            padding=ft.padding.all(12),
            on_click=lambda e, i=app["id"]: self._launch(i))
        self._hoverable(card, C.PANEL, C.SELECTED_BG)
        return ft.GestureDetector(card,
                                  on_secondary_tap_down=lambda e, ap=app: self._app_menu(ap, e))

    def _set_card(self, rec):
        # Уголок карточки в этой ленте занят номером места, а номер означает
        # Ctrl+N и принадлежит программе. Ctrl+Alt+N набора не влезает туда, не
        # столкнувшись с плашкой, поэтому он в подсказке — а на виду он в
        # палитре и на экране набора.
        accel = self._set_accels.get(rec["id"])
        card = ft.Container(
            ft.Column([
                self.set_slot(38, 11, 19, muted=True),
                ft.Container(height=8),
                T(rec["name"], size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT_2,
                  max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=0, tight=True),
            width=C.QUICK_W, height=QUICK_H, bgcolor=C.SET_BG,
            border=ft.border.all(1, C.DASHED), border_radius=12,
            padding=ft.padding.all(12),
            tooltip=f"{rec['name']} · {accel}" if accel and not self.calm() else rec["name"],
            on_click=lambda e, sid=rec["id"]: self._launch_set(sid))
        self._hoverable(card, C.SET_BG, C.PANEL)
        return ft.GestureDetector(card,
                                  on_secondary_tap_down=lambda e, r=rec: self._set_menu(r, e))

    def _quick_empty(self, slot):
        return ft.Container(
            ft.Icon(ft.Icons.ADD, size=16, color=C.TEXT_GHOST),
            width=C.QUICK_W, height=QUICK_H, border_radius=12,
            border=ft.border.all(1, C.CONTROL), alignment=ft.alignment.center,
            tooltip=f"Закрепите приложение — оно встанет на Ctrl+{slot}",
            on_click=lambda e: self._toast_hint_quick())

    # ---- секции и плитки ----
    def _section_head(self, sec):
        cat = next((c for c in self.categories() if c["id"] == sec.get("cid")), None)
        collapsed = bool(sec.get("cid")) and sec["cid"] in self.view.collapsed
        row = [self._cat_glyph(cat, size=14) if cat
               else ft.Container(width=8, height=8, border_radius=4, bgcolor=C.DOT),
               T(sec["name"], size=14.5, weight=ft.FontWeight.BOLD, color=C.TEXT)]
        if not self.calm():
            total = len(sec["apps"])
            picked = sum(1 for a in sec["apps"] if a["id"] in self.view.sel)
            label = f"{total} · выбрано {picked}" if self.view.select_mode else str(total)
            row.append(T(label, size=11, color=C.MUTED_2))
        row.append(ft.Container(height=1, bgcolor=C.LINE_2, expand=True))
        if sec.get("cid") and not self.view.select_mode:
            row.append(ft.Container(
                ft.Icon(ft.Icons.EXPAND_MORE if collapsed else ft.Icons.EXPAND_LESS,
                        size=16, color=C.TEXT_FAINT),
                tooltip="Развернуть" if collapsed else "Свернуть",
                on_click=lambda e, cid=sec["cid"]: self._toggle_section(cid)))
        head = ft.Container(ft.Row(row, spacing=9,
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.only(0, 2, 0, 12))
        if not cat:
            return head
        return ft.GestureDetector(head,
                                  on_secondary_tap_down=lambda e, c=cat: self._category_menu(c, e))

    def _use_poster(self, a):
        return bool(self._settings.get("game_posters", True)
                    and is_launcher_art(a) and img_b64(a.get("poster")))

    def _grid(self, apps):
        tiles = [self._draggable_tile(a, apps) for a in apps]
        return ft.Container(ft.Row(tiles, wrap=True, spacing=12, run_spacing=12,
                                   vertical_alignment=ft.CrossAxisAlignment.START),
                            padding=ft.padding.only(0, 0, 0, 18))

    def _draggable_tile(self, a, section_apps):
        compact = self._settings.get("tile_size") == "compact"
        running = a["id"] in self.running
        picked = a["id"] in self.view.sel
        selected = picked or (not self.view.select_mode and a["id"] == self._sel_id)
        ids = [x["id"] for x in section_apps]
        base = (self._build_poster_tile(a, compact, running, selected, ids)
                if self._use_poster(a) else
                self._build_tile(a, compact, running, selected, ids))
        return ft.Draggable(group="apps", content=base,
                            data={"ids": self._drag_ids(a["id"])})

    def _tile_meta(self, app, cat) -> str:
        """Вторая строка плитки: хоткей, иначе когда открывали, иначе категория."""
        if self.calm():
            return ""
        if self.view.select_mode:
            return cat["name"] if cat else ""
        accel = self._accels.get(app["id"])
        if accel:
            return accel
        ago = short_ago(app.get("last_launched"))
        if ago:
            return ago
        if cat:
            return cat["name"]
        return (app.get("sub") or "").strip()

    def _tile_marks(self, a, running):
        """Уголки плитки: чекбокс в режиме выбора, иначе точка и звезда."""
        if self.view.select_mode:
            picked = a["id"] in self.view.sel
            box = ft.Container(
                ft.Icon(ft.Icons.CHECK, size=14, color=C.ON_ACCENT) if picked else None,
                width=20, height=20, border_radius=10,
                bgcolor=self._accent() if picked else None,
                border=None if picked else ft.border.all(1.5, C.TEXT_FAINT),
                alignment=ft.alignment.center)
            return [ft.Container(box, left=8, top=8)]
        marks = []
        if running:
            marks.append(ft.Container(self._dot(), left=9, top=9,
                                      tooltip=self.running_note(a)))
        if a.get("favorite"):
            marks.append(ft.Container(ft.Icon(ft.Icons.STAR, size=14, color=C.STAR),
                                      right=9, top=9, tooltip="В избранном"))
        return marks

    def _build_tile(self, a, compact, running, selected, ids):
        width = C.TILE_W_COMPACT if compact else C.TILE_W
        cover_h = C.TILE_COVER_H_COMPACT if compact else C.TILE_COVER_H
        slot = C.TILE_SLOT_COMPACT if compact else C.TILE_SLOT
        cat = self.cat_of(a)

        gradient = C.TILE_GRADIENT_SEL if selected else C.TILE_GRADIENT
        cover_children = [ft.Container(
            self.icon_slot(a, slot, 14, glyph=round(slot * 0.48),
                           border=C.SLOT_BORDER_SEL if selected else None,
                           glyph_color=C.SLOT_GLYPH_SEL if selected else None),
            expand=True, alignment=ft.alignment.center,
            gradient=ft.LinearGradient(begin=ft.alignment.top_left,
                                       end=ft.alignment.bottom_right,
                                       colors=list(gradient)))]
        cover_children += self._tile_marks(a, running)

        meta = self._tile_meta(a, cat)
        foot_lines = [T(a["name"], size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
        if meta:
            foot_lines.append(T(meta, size=10.5, color=C.MUTED_2, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                font_family="monospace" if meta.startswith("Ctrl") else None))
        foot = ft.Container(ft.Column(foot_lines, spacing=2, tight=True),
                            padding=ft.padding.only(11, 9, 11, 10))

        # Выбранная плитка теряет 1px на каждую сторону под вторую линию рамки —
        # обложка компенсирует это, чтобы ряд не поехал.
        tile = ft.Container(
            ft.Column([ft.Container(ft.Stack(cover_children, expand=True),
                                    height=cover_h - (2 if selected else 0),
                                    clip_behavior=ft.ClipBehavior.HARD_EDGE), foot],
                      spacing=0, tight=True),
            width=width, bgcolor=C.SELECTED_BG if selected else C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=14, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        def on_hover(e):
            if selected:
                return
            hot = e.data == "true"
            tile.border = ft.border.all(1, C.LINE_4 if hot else C.LINE)
            tile.bgcolor = C.SELECTED_BG if hot else C.PANEL
            tile.update()
        tile.on_hover = on_hover
        return self._tile_gestures(tile, a, ids)

    def _build_poster_tile(self, a, compact, running, selected, ids):
        width = C.POSTER_W_COMPACT if compact else C.POSTER_W
        height = C.POSTER_H_COMPACT if compact else C.POSTER_H
        poster = ft.Image(src_base64=img_b64(a.get("poster")), width=width, height=height,
                          fit=ft.ImageFit.COVER)
        scrim = ft.Container(
            T(a["name"], size=12, weight=ft.FontWeight.W_600, color=C.WHITE,
              max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            left=0, right=0, bottom=0, padding=ft.padding.only(9, 18, 9, 8),
            gradient=ft.LinearGradient(begin=ft.alignment.top_center,
                                       end=ft.alignment.bottom_center,
                                       colors=list(C.POSTER_SCRIM)))
        children = [poster, scrim] + self._tile_marks(a, running)

        tile = ft.Container(
            ft.Stack(children), width=width, height=height, bgcolor=C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE)

        def on_hover(e):
            if selected:
                return
            tile.border = ft.border.all(1, C.LINE_4 if e.data == "true" else C.LINE)
            tile.update()
        tile.on_hover = on_hover
        return self._tile_gestures(tile, a, ids)

    def _tile_gestures(self, tile, a, ids):
        # Клик уже запускает программу, второй по счёту (двойной тап) запускал
        # бы её ещё раз — обработчик не нужен.
        return ft.GestureDetector(
            tile, mouse_cursor=ft.MouseCursor.CLICK,
            on_tap_down=lambda e, i=a["id"]: self._tile_tap(i, ids, e),
            on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e))

    def _list(self, apps):
        rows = [self._list_row(a, [x["id"] for x in apps]) for a in apps]
        return ft.Container(ft.Column(rows, spacing=6), padding=ft.padding.only(0, 0, 0, 18))

    def _list_row(self, a, ids):
        running = a["id"] in self.running
        picked = a["id"] in self.view.sel
        selected = picked or (not self.view.select_mode and a["id"] == self._sel_id)
        cat = self.cat_of(a)
        lines = [T(a["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT)]
        meta = self._tile_meta(a, cat)
        if meta:
            lines.append(T(meta, size=11, color=C.MUTED_2,
                           font_family="monospace" if meta.startswith("Ctrl") else None))
        controls = []
        if self.view.select_mode:
            controls.append(ft.Icon(ft.Icons.CHECK_BOX if picked
                                    else ft.Icons.CHECK_BOX_OUTLINE_BLANK, size=18,
                                    color=self._accent() if picked else C.TEXT_FAINT))
        controls += [self.icon_slot(a, 32, 9, glyph=17),
                     ft.Column(lines, spacing=1, expand=True, tight=True)]
        if running:
            controls.append(ft.Row([self._dot(), T(self.running_note(a), size=11,
                                                   color=C.GREEN_TEXT)],
                                   spacing=6, tight=True))
        if a.get("favorite"):
            controls.append(ft.Icon(ft.Icons.STAR, size=15, color=C.STAR))
        controls.append(ft.Container(ft.Icon(ft.Icons.MORE_HORIZ, size=16, color=C.MUTED),
                                     width=30, height=30, border_radius=9,
                                     alignment=ft.alignment.center, tooltip="Меню",
                                     on_click=lambda e, ap=a: self._app_menu(ap, None)))
        row = ft.Container(ft.Row(controls, spacing=12,
                                  vertical_alignment=ft.CrossAxisAlignment.CENTER),
                           padding=ft.padding.symmetric(9, 12), border_radius=11,
                           border=ft.border.all(2, self._accent()) if selected
                           else ft.border.all(1, C.LINE),
                           bgcolor=C.SELECTED_BG if selected else C.PANEL)
        if not selected:
            self._hoverable(row, C.PANEL, C.SELECTED_BG)
        return ft.GestureDetector(row,
                                  on_tap_down=lambda e, i=a["id"]: self._tile_tap(i, ids, e),
                                  on_secondary_tap_down=lambda e, ap=a: self._app_menu(ap, e))

    def _empty(self, title, text, btn_label, on_click):
        controls = [
            T(title, size=15, weight=ft.FontWeight.W_600, color=C.TEXT_2),
            ft.Container(height=8),
            T(text, size=13, color=C.MUTED_2, text_align=ft.TextAlign.CENTER, width=380),
        ]
        if btn_label:
            controls += [ft.Container(height=18),
                         self.primary_btn(btn_label, on_click, ft.Icons.ADD)]
        return ft.Container(
            ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
            alignment=ft.alignment.center, padding=ft.padding.only(0, 80, 0, 40))

    # =====================================================================
    # Инспектор
    # =====================================================================
    def _build_inspector(self):
        app = next((a for a in self.apps() if a["id"] == self.view.inspector), None)
        if app is None:
            return None
        running = app["id"] in self.running
        cat = self.cat_of(app)

        status = ft.Row([self._dot(), T(self.running_note(app), size=11.5,
                                       color=C.GREEN_TEXT)],
                        spacing=6, tight=True) if running else \
            T(short_ago(app.get("last_launched")) or "ещё не открывали",
              size=11.5, color=C.MUTED_2)
        header = ft.Container(
            ft.Row([self.icon_slot(app, 46, 13, glyph=23),
                    ft.Column([T(app["name"], size=15.5, weight=ft.FontWeight.BOLD,
                                 color=C.TEXT, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS),
                               status], spacing=5, expand=True, tight=True),
                    ft.Container(ft.Icon(ft.Icons.CLOSE, size=18, color=C.MUTED_2),
                                 on_click=lambda e: self._close_inspector(),
                                 tooltip="Закрыть панель")],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=ft.padding.only(18, 18, 18, 16))

        def square(icon, tooltip, handler, color=C.MUTED):
            return ft.Container(ft.Icon(icon, size=16, color=color), width=38, height=36,
                                border=ft.border.all(1, C.LINE_4), border_radius=9,
                                alignment=ft.alignment.center, tooltip=tooltip,
                                on_click=lambda e: handler())

        # «Открыть ещё окно» и «От администратора» — запасные способы запуска,
        # реже нужные, чем сам запуск: они за «Ещё», а не отдельными кнопками.
        actions = ft.Container(
            ft.Row([
                self.primary_btn("Переключиться" if running else "Запустить",
                                 lambda: self._launch(app["id"]),
                                 ft.Icons.SYNC_ALT if running else ft.Icons.PLAY_ARROW,
                                 height=36, expand=True),
                square(ft.Icons.STAR if app.get("favorite") else ft.Icons.STAR_BORDER,
                       "В избранное", lambda: self._toggle_fav(app["id"]),
                       C.STAR if app.get("favorite") else C.MUTED),
                square(ft.Icons.FOLDER_OPEN, "Показать в папке",
                       lambda: self._show_in_folder(app["id"])),
                square(ft.Icons.MORE_HORIZ, "Ещё способы запуска",
                       lambda: self._launch_more_menu(app, None)),
            ], spacing=8), padding=ft.padding.only(18, 0, 18, 0))

        props = [
            self._insp_row("Категория", self._cat_selector(app, cat)),
            self._insp_row("Быстрый запуск",
                           self._toggle(bool(app.get("quick")),
                                        lambda v: self._toggle_quick(app["id"], v)),
                           sub=self._quick_sub(app)),
            self._insp_row("Своя горячая клавиша", self._hotkey_field(app),
                           sub="Нажмите комбинацию" if self.view.capture
                           else "Работает из любого окна"),
            self._insp_row("В наборах", self._set_chips(app)),
        ]
        props.append(ft.Container(height=1, bgcolor=C.LINE_2))
        props.append(self._insp_tech(app))
        placement = ft.Container(ft.Column(props, spacing=12),
                                 padding=ft.padding.only(18, 18, 18, 0))

        footer = ft.Container(
            ft.Row([T("" if self.calm() else "сохраняется само", size=10.5,
                      color=C.MUTED_3, expand=True),
                    self.outline_btn("Убрать", lambda: self._remove_apps([app["id"]]),
                                     ft.Icons.DELETE_OUTLINE, danger=True, height=30)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(14, 18),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

        # Прокручиваются только свойства: шапка с кнопками сверху и «Убрать»
        # снизу остаются на месте.
        return ft.Container(
            ft.Column([header, actions,
                       ft.Column([placement, self._insp_advanced(app),
                                  ft.Container(height=18)],
                                 spacing=0, expand=True, scroll=ft.ScrollMode.AUTO),
                       footer], spacing=0, expand=True),
            border=ft.border.only(left=ft.BorderSide(1, C.LINE_2)), expand=True)

    def _insp_row(self, label, control, sub=None):
        left = [T(label, size=12.5, color=C.TEXT_2)]
        if sub and not self.calm():
            left.append(T(sub, size=11, color=C.MUTED_2))
        return ft.Row([ft.Column(left, spacing=1, tight=True, expand=True), control],
                      spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _insp_tech(self, app):
        """Путь и статистика — то, что раньше пряталось в подзаголовке."""
        if self.calm():
            return ft.Container(height=0)
        lines = []
        if app.get("path"):
            lines.append(T(app["path"], size=10.5, color=C.MUTED_2))
        stats = []
        if app.get("launch_count"):
            stats.append(T(f"Запусков: {app['launch_count']}", size=11, color=C.MUTED))
        ago = time_ago(app.get("last_launched"))
        if ago:
            stats.append(T(f"Последний: {ago}", size=11, color=C.MUTED))
        if stats:
            lines.append(ft.Row(stats, spacing=14, wrap=True, run_spacing=4))
        if not lines:
            return ft.Container(height=0)
        return ft.Column(lines, spacing=7, tight=True)

    def _set_chips(self, app):
        """Чипы наборов, где есть программа, плюс «+» — заменяет «Добавить в
        набор…» из старого меню. Строка всегда на месте, даже без единого
        набора: иначе добавить программу в первый набор было бы неоткуда."""
        members = [rec for rec in self.sets() if app["id"] in rec.get("apps", [])]
        chips = [ft.Container(
            ft.Row([ft.Icon(ft.Icons.LAYERS, size=13, color=C.MUTED),
                    T(rec["name"], size=11.5, color=C.TEXT_2, max_lines=1,
                      overflow=ft.TextOverflow.ELLIPSIS)], spacing=6, tight=True),
            height=26, border_radius=13, bgcolor=C.SET_SLOT_BG,
            border=ft.border.all(1, C.CONTROL), padding=ft.padding.symmetric(0, 9),
            on_click=lambda e, sid=rec["id"]: self._open_set(sid)) for rec in members]
        chips.append(ft.Container(
            ft.Row([ft.Icon(ft.Icons.ADD, size=13, color=C.MUTED_2),
                    T("Ещё" if members else "В набор", size=11.5, color=C.MUTED_2)],
                   spacing=6, tight=True),
            height=26, border_radius=13, border=ft.border.all(1, C.DASHED),
            padding=ft.padding.symmetric(0, 9), tooltip="Добавить в набор",
            on_click=lambda e: self._add_to_set_menu(app, e)))
        return ft.Row(chips, spacing=6, wrap=True, run_spacing=6, tight=True)

    def _cat_selector(self, app, cat):
        return ft.Container(
            ft.Row([
                ft.Row([self._cat_glyph(cat, size=14) if cat
                        else ft.Icon(ft.Icons.FOLDER, size=14, color=C.MUTED),
                        T(cat["name"] if cat else "Без категории", size=12.5, color=C.TEXT,
                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                       spacing=6, tight=True, expand=True),
                ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.MUTED_2),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            width=160, height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.CONTROL),
            border_radius=8, padding=ft.padding.symmetric(0, 10),
            tooltip="Выбрать категорию",
            on_click=lambda e: self._category_picker(app, e))

    def _quick_sub(self, app) -> str:
        """Подпись под переключателем «Быстрый запуск»: что он даст."""
        accel = self._accels.get(app["id"])
        if app.get("quick") and accel:
            return f"Сейчас место {accel.split('+')[-1]}"
        if app.get("quick"):
            return "Свободных мест не осталось"
        return "Появится в ленте сверху"

    def _hotkey_field(self, app):
        """Своя комбинация клавиш — отдельно от закрепления в ленте выше.

        Именно `hotkey`, а не смешанный `_accels`: тот включает и авто-номер от
        закрепления в ленте, а это поле — только явно назначенная комбинация.
        Клик начинает запись комбинации. Пустое поле — «не задана».
        """
        explicit = app.get("hotkey")
        label = "нажмите…" if self.view.capture else (explicit or "не задана")
        row = [T(label, size=11.5, font_family="monospace",
                 color=C.TEXT if (explicit or self.view.capture) else C.MUTED_2),
               ft.Icon(ft.Icons.EDIT, size=14, color=C.MUTED_2)]
        field = ft.Container(
            ft.Row(row, spacing=8, tight=True,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=32, padding=ft.padding.symmetric(0, 10), bgcolor=C.PANEL,
            border=ft.border.all(1, self._accent() if self.view.capture else C.CONTROL),
            border_radius=8, alignment=ft.alignment.center,
            tooltip="Нажмите комбинацию" if self.view.capture
            else "Своя комбинация, работает из любого окна",
            on_click=lambda e: self._begin_capture())
        if app.get("hotkey") and not self.view.capture:
            return ft.Row([field,
                           ft.Container(ft.Icon(ft.Icons.CLOSE, size=14, color=C.MUTED_2),
                                        tooltip="Убрать комбинацию",
                                        on_click=lambda e: self._set_hotkey(app["id"], None))],
                          spacing=6, tight=True)
        return field

    def _insp_advanced(self, app):
        """«ПАРАМЕТРЫ ЗАПУСКА» — свёрнуты, открываются из меню или по заголовку."""
        args_value = " ".join(app.get("args") or []) if isinstance(app.get("args"), list) \
            else str(app.get("args") or "")
        open_now = self.view.adv or bool(args_value) or bool(app.get("run_as_admin")) \
            or bool(app.get("working_dir"))
        head = ft.Container(
            ft.Row([self._caps("ПАРАМЕТРЫ ЗАПУСКА"),
                    ft.Container(height=1, bgcolor=C.LINE_2, expand=True),
                    ft.Icon(ft.Icons.EXPAND_LESS if open_now else ft.Icons.EXPAND_MORE,
                            size=16, color=C.TEXT_FAINT)],
                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=lambda e: self._toggle_adv())
        if not open_now:
            return ft.Container(head, padding=ft.padding.only(18, 18, 18, 0))

        args_field = ft.TextField(
            value=args_value, hint_text="не заданы", height=32, text_size=11.5,
            color=C.TEXT, bgcolor=C.PANEL, border_color=C.CONTROL,
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
            height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.CONTROL), border_radius=8,
            padding=ft.padding.only(10, 0, 6, 0), expand=True)

        proc = (app.get("track_exe") or "").strip()
        proc_box = ft.Container(
            ft.Row([T(proc or "не определён", size=11.5, font_family="monospace",
                      color=C.TEXT if proc else C.MUTED_2, expand=True,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T("найден" if proc and app["id"] in self.running else "", size=11,
                      color=C.GREEN)],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=32, bgcolor=C.PANEL, border=ft.border.all(1, C.CONTROL), border_radius=8,
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
    # Слои поверх тела
    # =====================================================================
    def _palette_rows(self):
        """Строки палитры одним списком — по ним ходят стрелки.

        Программы, затем наборы; index сквозной, потому что ↑↓ ходят по группам
        подряд, не останавливаясь на заголовках.
        """
        apps = self.apps()
        rows = [dict(r, kind="app") for r in
                queries.search_rows(apps, self.view.query, self.running, self.categories())]
        for entry in queries.set_rows(self.sets(), apps, self.view.query):
            rows.append({"kind": "set", "set": entry["set"], "members": entry["members"]})
        for index, row in enumerate(rows):
            row["index"] = index
        return rows

    def palette_current(self, rows=None):
        """Строка под выделением, или None если палитра пуста."""
        rows = self._palette_rows() if rows is None else rows
        if not rows:
            return None
        if self.view.palette_focus == "actions":
            return next((r for r in rows if r["kind"] == "app"), None)
        return rows[min(self.view.palette_index, len(rows) - 1)]

    def _palette_app(self):
        """Программа, к которой относится группа «ДЕЙСТВИЯ»."""
        rows = self._palette_rows()
        current = self.palette_current(rows)
        if current is not None and current["kind"] == "app":
            return current["app"]
        return next((r["app"] for r in rows if r["kind"] == "app"), None)

    def _render_palette(self):
        from . import dialogs
        if not self.view.palette_open or self.view.onboarding:
            self._palette_count = 0
            self.palette_layer.visible = False
            self.palette_card.content = None
            self.palette_card.opacity = 0
            self.palette_card.offset = ft.Offset(0, -0.02)
            return
        rows = self._palette_rows()
        self._palette_count = len(rows)
        self.palette_card.content = dialogs.build_palette(self, rows)
        self.palette_card.opacity = 1
        self.palette_card.offset = ft.Offset(0, 0)
        self.palette_layer.visible = True

    def _render_bulk_bar(self):
        from . import dialogs
        showing = bool(self.view.select_mode and self.view.sel)
        # Тост встаёт выше панели: иначе «Вернуть» после массового действия
        # накрывало бы саму панель, которой его вызвали.
        self.toast.lift(showing)
        if not showing:
            self.bulk_layer.visible = False
            self.bulk_card.content = None
            self.bulk_card.opacity = 0
            self.bulk_card.offset = ft.Offset(0, 0.3)
            return
        self.bulk_card.content = dialogs.build_bulk_bar(self)
        self.bulk_card.opacity = 1
        self.bulk_card.offset = ft.Offset(0, 0)
        self.bulk_layer.visible = True

    # =====================================================================
    # Контекстные меню
    # =====================================================================
    def _menu_at(self, e):
        if e is None:
            return self._window_width() / 2, 180.0
        return float(getattr(e, "global_x", 0) or 0), float(getattr(e, "global_y", 0) or 0)

    def _on_menu_dismissed(self):
        # The shade swallowed the click that closed the menu, so the tree it
        # covered has to be redrawn without it.
        self._safe_refresh()

    def _app_menu(self, app, e):
        """ПКМ по плитке.

        Раньше здесь было контекстное меню одной программы; все его пункты
        (кроме «Скрыть») теперь живут в самом инспекторе, а правая кнопка
        просто его открывает — так же, как раньше открывал левый клик, пока
        сам левый клик не стал запускать программу напрямую. Меню выбора и
        меню выделения — отдельная история про массовые операции, они
        остаются меню.
        """
        app = self.store.get_app(app["id"]) or app
        if self.view.select_mode:
            self._select_mode_menu(app, e)
            return
        if app["id"] in self.view.sel and len(self.view.sel) > 1:
            self._selection_menu(e)
            return
        self._select_tile(app["id"])

    def _select_mode_menu(self, app, e):
        """ПКМ по плитке в режиме выбора.

        Здесь же живёт «до этой»: Flet не сообщает, был ли зажат Shift во время
        клика (в событии тапа нет модификаторов), так что диапазон должен быть
        доступен и мышью, а не только с клавиатурой.
        """
        x, y = self._menu_at(e)
        ids = list(self.view.sel)
        picked = app["id"] in ids
        anchor = self.view.selection_anchor
        rows = [
            menus.item(ft.Icons.CHECK_BOX if picked else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                       "Снять отметку" if picked else "Отметить",
                       lambda: self._toggle_pick(app["id"])),
            menus.item(ft.Icons.SELECT_ALL, "Выбрать до этой",
                       lambda: self._range_to(app["id"]),
                       disabled=not anchor or anchor == app["id"]),
            menus.item(ft.Icons.DONE_ALL, "Выбрать всё", self._select_all_visible,
                       hint="" if self.calm() else "Ctrl+A"),
        ]
        if ids:
            rows += [
                menus.separator(),
                menus.item(ft.Icons.FOLDER, "Переложить в…",
                           lambda: self.menu.toggle_submenu(
                               "cat", self._category_submenu(ids), y), submenu=True),
                menus.item(ft.Icons.LAYERS, "В набор…",
                           lambda: self.menu.toggle_submenu(
                               "set", self._set_submenu(ids), y), submenu=True),
                menus.item(ft.Icons.STAR_BORDER, "В избранное",
                           lambda: self._bulk_favorite(ids)),
                menus.item(ft.Icons.VISIBILITY if self.filter == "hidden"
                           else ft.Icons.VISIBILITY_OFF,
                           "Показать" if self.filter == "hidden" else "Скрыть из сетки",
                           lambda: self._hide_apps(ids, self.filter != "hidden")),
                menus.item(ft.Icons.DELETE_OUTLINE, f"Убрать · {len(ids)}",
                           lambda: self._remove_apps(ids), danger=True),
            ]
        rows += [menus.separator(),
                 menus.item(ft.Icons.CLOSE, "Выйти из режима", self._toggle_select_mode,
                            hint="" if self.calm() else "Esc")]
        header = (menus.text_header(f"Выбрано {len(ids)}") if ids
                  else menus.app_header(self, app, app["id"] in self.running))
        self.menu.show(x, y, rows, header=header)

    def _selection_menu(self, e):
        x, y = self._menu_at(e)
        ids = list(self.view.sel)
        count = len(ids)
        rows = [
            menus.item(ft.Icons.FOLDER, "Переложить в…",
                       lambda: self.menu.toggle_submenu("cat", self._category_submenu(ids), y),
                       submenu=True),
            menus.item(ft.Icons.LAYERS, "В набор…",
                       lambda: self.menu.toggle_submenu("set", self._set_submenu(ids), y),
                       submenu=True),
            menus.item(ft.Icons.STAR_BORDER, "В избранное", lambda: self._bulk_favorite(ids)),
            menus.item(ft.Icons.VISIBILITY if self.filter == "hidden"
                       else ft.Icons.VISIBILITY_OFF,
                       "Показать" if self.filter == "hidden" else "Скрыть из сетки",
                       lambda: self._hide_apps(ids, self.filter != "hidden")),
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
        accel = self._set_accels.get(rec["id"])
        rows = [
            menus.item(ft.Icons.PLAY_ARROW, "Запустить набор",
                       lambda: self._launch_set(rec["id"]),
                       hint="" if self.calm() else (accel or "")),
        ]
        if rec.get("close_together"):
            rows.append(menus.item(ft.Icons.CLOSE, "Закрыть набор",
                                   lambda: self.close_set_windows(rec["id"])))
        rows += [
            menus.item(ft.Icons.CROP_FREE, "Расставить окна",
                       lambda: self.arrange_set(rec["id"]),
                       disabled=not queries.has_layout(rec)),
            menus.item(ft.Icons.TUNE, "Раскладка и порядок",
                       lambda: self._open_set(rec["id"])),
            menus.item(ft.Icons.BOLT,
                       "Убрать из быстрого запуска" if rec.get("quick") else "В быстрый запуск",
                       lambda: self._toggle_set_quick(rec["id"], not rec.get("quick"))),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, "Удалить набор",
                       lambda: self._remove_set(rec["id"]), danger=True),
        ]
        self.menu.show(x, y, rows, header=menus.text_header(rec["name"]))

    def _set_item_menu(self, rec, entry, e):
        """Меню строки в «ПОРЯДКЕ ЗАПУСКА»."""
        x, y = self._menu_at(e)
        app = next((a for a in self.apps() if a["id"] == entry["app_id"]), None)
        preset = rec["layout"]["preset"]
        places = [menus.item(ft.Icons.CHECK if entry.get("slot") == i else None,
                             L.slot_label(preset, i, rec["layout"]["split"]).capitalize(),
                             lambda idx=i: self._set_item_slot(rec["id"], entry["app_id"], idx))
                  for i in range(L.slot_count(preset))]
        places.append(menus.item(ft.Icons.CHECK if entry.get("slot") is None
                                 and not entry.get("minimized") else None,
                                 "Без места", lambda: self._set_item_slot(
                                     rec["id"], entry["app_id"], None)))
        rows = [
            menus.item(ft.Icons.ARROW_UPWARD, "Запускать раньше",
                       lambda: self._move_set_item(rec["id"], entry["app_id"], -1)),
            menus.item(ft.Icons.ARROW_DOWNWARD, "Запускать позже",
                       lambda: self._move_set_item(rec["id"], entry["app_id"], 1)),
            menus.separator(),
            menus.item(ft.Icons.CROP_FREE, "Место в раскладке",
                       lambda: self.menu.toggle_submenu("slot", places, y), submenu=True),
            menus.item(ft.Icons.LAYERS_CLEAR if entry.get("minimized")
                       else ft.Icons.MINIMIZE,
                       "Открывать обычно" if entry.get("minimized") else "Запускать свёрнутым",
                       lambda: self._set_item_minimized(rec["id"], entry["app_id"],
                                                        not entry.get("minimized"))),
            menus.separator(),
            menus.item(ft.Icons.DELETE_OUTLINE, "Убрать из набора",
                       lambda: self._remove_from_set(rec["id"], entry["app_id"]),
                       danger=True),
        ]
        self.menu.show(x, y, rows,
                       header=menus.text_header(app["name"] if app else "Программа"))

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

    def _sort_menu(self, e):
        x, y = self._menu_at(e)
        self.menu.show(x, y, self._sort_submenu(), header=None)

    def _category_picker(self, app, e):
        x, y = self._menu_at(e)
        self.menu.show(x, y, self._category_submenu([app["id"]]),
                       header=menus.text_header("Переложить в…"))

    def _add_to_set_menu(self, app, e):
        x, y = self._menu_at(e)
        self.menu.show(x, y, self._set_submenu([app["id"]]),
                       header=menus.text_header("Добавить в набор"))

    def _launch_more_menu(self, app, e):
        """«Ещё способы запуска»: то, что раньше жило в контекстном меню
        плитки — второе окно и запуск от администратора."""
        x, y = self._menu_at(e)
        rows = [
            menus.item(ft.Icons.ADD, "Открыть ещё окно",
                       lambda: self._launch(app["id"], again=True)),
            menus.item(ft.Icons.SHIELD, "От имени администратора",
                       lambda: self._launch(app["id"], as_admin=True)),
        ]
        self.menu.show(x, y, rows, header=None)

    def _bulk_menu(self, kind: str):
        """Меню из плавающей панели — открывается вверх, над самой панелью."""
        ids = list(self.view.sel)
        if not ids:
            return
        rows = (self._category_submenu(ids) if kind == "cat" else self._set_submenu(ids))
        title = "Переложить в…" if kind == "cat" else "Добавить в набор…"
        self.menu.show(self._window_width() / 2 - 120, self._window_height() - 96,
                       rows, header=menus.text_header(title))

    def _preset_menu(self, rec, e):
        x, y = self._menu_at(e)
        rows = [menus.item(ft.Icons.CHECK if rec["layout"]["preset"] == key else None,
                           L.PRESET_LABELS[key],
                           lambda k=key: self.set_layout_preset(rec["id"], k))
                for key in L.PRESETS]
        self.menu.show(x, y, rows, header=menus.text_header("Раскладка"))

    def _monitor_menu(self, rec, e):
        x, y = self._menu_at(e)
        count = max(1, len(W.monitors()))
        rows = [menus.item(ft.Icons.CHECK if rec["monitor"] == i else None,
                           f"Монитор {i + 1}",
                           lambda idx=i: self.set_set_monitor(rec["id"], idx))
                for i in range(count)]
        self.menu.show(x, y, rows, header=menus.text_header("Куда расставлять"))

    def _delay_menu(self, rec, e):
        x, y = self._menu_at(e)
        rows = [menus.item(ft.Icons.CHECK if abs(rec["delay_seconds"] - value) < 0.01 else None,
                           "без паузы" if not value else f"{value:g} с",
                           lambda v=value: self.set_set_delay(rec["id"], v))
                for value in (0, 1, 2, 4, 8)]
        self.menu.show(x, y, rows, header=menus.text_header("Пауза между запусками"))

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
        if e.ctrl and key.lower() == "k":
            self._focus_search()
            return
        if e.ctrl and key == ",":
            self._open_settings()
            return
        if self.view.palette_open:
            self._palette_key(e, key)
            return
        self._library_key(e, key)

    def _palette_key(self, e, key):
        rows = self._palette_rows()
        actions = queries.palette_actions(self._palette_app())
        count = len(actions) if self.view.palette_focus == "actions" else len(rows)
        if key in ("Arrow Down", "Arrow Up"):
            self.view.move_palette(1 if key == "Arrow Down" else -1, count)
            self.refresh(content_only=True)
        elif key == "Tab":
            self.view.focus_palette_actions(len(rows))
            self.refresh(content_only=True)
        elif key in ("Enter", "Numpad Enter"):
            self._palette_activate(admin=bool(e.ctrl))
        elif key == "Escape":
            self._close_palette()

    def _palette_activate(self, admin: bool = False):
        if self.view.palette_focus == "actions":
            actions = queries.palette_actions(self._palette_app())
            if actions:
                index = min(self.view.palette_index, len(actions) - 1)
                self.run_palette_action(actions[index]["key"])
            return
        rows = self._palette_rows()
        if not rows:
            return
        row = rows[min(self.view.palette_index, len(rows) - 1)]
        if row["kind"] == "set":
            self._launch_set(row["set"]["id"], from_palette=True)
        else:
            self._launch(row["app"]["id"], from_palette=True, as_admin=admin)

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
            self._select_all_visible()
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

    def _focus_search(self):
        self.view.open_palette()
        self.refresh()
        self._focus(self.search_field)

    def toggle_search(self):
        """Ctrl+Пробел изнутри окна: открыть палитру или убрать её."""
        if self.view.palette_open:
            self._close_palette()
            return False
        self._focus_search()
        return True

    def _open_palette(self):
        if self.view.palette_open:
            return
        self.view.open_palette()
        self.refresh()

    def _close_palette(self):
        self.view.close_palette()
        self.search_field.value = ""
        self.refresh()

    def _toggle_sidebar(self):
        self.view.toggle_sidebar()
        self.refresh()

    def _set_filter(self, f):
        self.view.set_filter(f)
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

    def _toggle_section(self, cid):
        self.view.toggle_section(cid)
        self.refresh()

    def _on_search(self, e):
        self.view.set_query(e.control.value)
        if not self.view.palette_open:
            self.view.open_palette()
        # content_only: шапку не пересобирать. Поле поиска в ней, и хотя это тот
        # же контрол, лишний раз переносить его между деревьями на каждой букве
        # незачем — счётчик совпадений всё равно обновляется отдельно.
        self.refresh(content_only=True)

    def _toggle_select_mode(self):
        if self.view.select_mode:
            self.view.leave_select_mode()
        else:
            self.view.enter_select_mode()
        self.refresh()

    def _select_all_visible(self):
        flat = self._flat_apps()
        if not self.view.select_mode:
            self.view.enter_select_mode()
        self.view.select_many([a["id"] for a in flat])
        self.refresh()

    def _tile_tap(self, app_id, ids, e=None):
        """Клик по плитке — запускает программу.

        В режиме выбора клик отмечает одну, а не запускает. Ctrl и Shift
        читаются из события, если движок их вообще сообщает: в Flet 0.28 у
        события тапа модификаторов нет, поэтому «включить режим» и «взять
        диапазон» есть ещё и в меню по правой кнопке — на них и рассчитан
        мышиный путь.
        """
        ctrl = bool(getattr(e, "ctrl", False)) if e is not None else False
        shift = bool(getattr(e, "shift", False)) if e is not None else False
        if not self.view.select_mode and not (ctrl or shift):
            self._launch(app_id)
            return
        if not self.view.select_mode:
            self.view.enter_select_mode()
        if shift:
            self.view.select_range(ids, app_id)
        else:
            self.view.toggle_selection(app_id)
        self.refresh()

    def _toggle_pick(self, app_id):
        self.view.toggle_selection(app_id)
        self.refresh()

    def _range_to(self, app_id):
        self.view.select_range([a["id"] for a in self._flat_apps()], app_id)
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
    def _switch_to(self, app) -> bool:
        """Переключиться на уже открытое окно программы."""
        for win in self._app_windows(app):
            if W.activate(win["hwnd"]):
                return True
        return False

    def _launch(self, app_id, again: bool = False, as_admin: bool = False,
                from_palette: bool = False):
        app = self.store.get_app(app_id)
        if not app:
            return
        if not again and not as_admin and app_id in self.running and self._switch_to(app):
            self.toast.show(f"{app['name']} — переключились", icon=ft.Icons.SYNC_ALT,
                            icon_color=C.MUTED)
            self._after_launch(from_palette)
            return
        payload = dict(app, run_as_admin=True) if as_admin else app
        try:
            res = self.launcher.launch(payload)
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
        self._after_launch(from_palette)

    def _launch_failed(self, app, message):
        missing = "не найден" in message.lower()
        self.toast.error(f"{app['name']} не нашёлся на диске" if missing else message,
                         detail="Программу переустановили или перенесли" if missing else None,
                         action=(lambda: self._relocate(app["id"])) if missing else None,
                         action_label="Найти" if missing else None)
        self.refresh()

    def _launch_set(self, set_id, from_palette: bool = False):
        """Запустить набор: по порядку, с паузой, потом расставить окна.

        Пауза — смысл настройки «тяжёлые программы успевают открыться», поэтому
        вся последовательность идёт в отдельном потоке: спать в обработчике
        клика значило бы заморозить окно на эти секунды.
        """
        rec = self.store.get_set(set_id)
        if not rec:
            return
        if from_palette:
            # Палитру убираем сразу: ждать, пока откроется четвёртая программа,
            # чтобы она исчезла, было бы странно.
            self.view.close_palette()
            self.search_field.value = ""
        count = len(rec["items"])
        self.toast.show(f"Открываю «{rec['name']}» · {count} {plu_programs(count)}",
                        icon=ft.Icons.LAYERS)
        self.refresh()
        threading.Thread(target=lambda: self._run_set(rec, from_palette),
                         daemon=True).start()

    def _run_set(self, rec, from_palette: bool):
        delay = max(0.0, float(rec.get("delay_seconds") or 0.0))
        started, failed = [], 0
        try:
            for index, entry in enumerate(rec["items"]):
                app = self.store.get_app(entry["app_id"])
                if not app:
                    continue
                if index and delay:
                    time.sleep(delay)
                try:
                    res = self.launcher.launch(app)
                except Exception:
                    log.exception("launching %s from a set failed", app.get("path"))
                    res = {"ok": False}
                if res.get("ok"):
                    self.store.mark_launched(entry["app_id"])
                    started.append(app["name"])
                else:
                    failed += 1
            self.running = set(self.launcher.running_ids())
            if not started:
                self.toast.error(f"Ни одна программа из «{rec['name']}» не запустилась")
                self._safe_refresh()
                return
            text = "Открыто: " + ", ".join(started)
            if failed:
                text += f" · не удалось: {failed}"
            self.toast.show(text, icon=ft.Icons.LAYERS)
            if W.available() and queries.has_layout(rec):
                # Последняя программа ещё рисует своё окно — расставлять раньше
                # нечего.
                time.sleep(max(0.5, delay))
                self.arrange_set(rec["id"], quiet=True)
            self._after_launch(from_palette)
        except Exception:
            log.exception("running the set «%s» failed", rec.get("name"))
            self._safe_refresh()

    def arrange_set(self, set_id, quiet: bool = False):
        """Разложить окна запущенных программ набора по сохранённой раскладке."""
        rec = self.store.get_set(set_id)
        if not rec:
            return
        if not W.available():
            if not quiet:
                self.toast.error("Расставлять окна умеет только Windows-сборка")
            return
        area = W.work_area(rec["monitor"])
        fallback = False
        if area is None:
            area = W.work_area(0)
            fallback = rec["monitor"] != 0
        if area is None:
            if not quiet:
                self.toast.error("Не удалось прочитать размеры экрана")
            return
        snapshot = W.list_windows()
        placed = 0
        conf = rec["layout"]
        for entry in rec["items"]:
            app = self.store.get_app(entry["app_id"])
            if not app:
                continue
            wins = W.windows_for(W.exe_names_for(app), snapshot)
            if not wins:
                continue
            if entry.get("minimized"):
                if W.minimize(wins[0]["hwnd"]):
                    placed += 1
                continue
            rect = L.rect_for(entry, conf["preset"], conf["split"], conf["vsplit"])
            if rect is None:
                continue
            if W.place(wins[0]["hwnd"], L.to_pixels(rect, area)):
                placed += 1
        if fallback:
            self.toast.show(f"Монитора {rec['monitor'] + 1} нет — разложили на основном",
                            icon=ft.Icons.DESKTOP_WINDOWS, icon_color=C.MUTED)
        elif not quiet:
            self.toast.show(f"Окна расставлены: {placed}" if placed
                            else "Ни одно окно набора не открыто",
                            icon=ft.Icons.CROP_FREE, icon_color=C.MUTED)
        self._safe_refresh()

    def close_set_windows(self, set_id):
        """«Закрыть набор»: попросить закрыться окна всех его программ.

        Появляется в меню только когда включено «Закрывать набор целиком» — то
        есть когда пользователь сказал, что набор для него одно целое.
        """
        rec = self.store.get_set(set_id)
        if not rec:
            return
        if not W.available():
            self.toast.error("Закрывать окна умеет только Windows-сборка")
            return
        snapshot = W.list_windows()
        closed = 0
        for entry in rec["items"]:
            app = self.store.get_app(entry["app_id"])
            if not app:
                continue
            for win in W.windows_for(W.exe_names_for(app), snapshot):
                if W.close_window(win["hwnd"]):
                    closed += 1
        self.toast.show(f"Закрыто окон: {closed}" if closed
                        else "Окон этого набора не нашлось",
                        icon=ft.Icons.CLOSE, icon_color=C.MUTED)
        self._safe_refresh()

    def capture_set_layout(self, set_id):
        """«Снять с текущих окон»: запомнить, где окна стоят прямо сейчас."""
        rec = self.store.get_set(set_id)
        if not rec:
            return
        if not W.available():
            self.toast.error("Читать положение окон умеет только Windows-сборка")
            return
        area = W.work_area(rec["monitor"]) or W.work_area(0)
        if area is None:
            self.toast.error("Не удалось прочитать размеры экрана")
            return
        before = [dict(i) for i in rec["items"]]
        snapshot = W.list_windows()
        items, rects = [], []
        for entry in rec["items"]:
            app = self.store.get_app(entry["app_id"])
            fresh = dict(entry)
            wins = W.windows_for(W.exe_names_for(app or {}), snapshot) if app else []
            if wins and not wins[0]["minimized"]:
                rect = L.to_fractions(wins[0]["rect"], area)
                fresh.update({"rect": list(rect), "slot": None, "minimized": False})
                rects.append(rect)
            elif wins:
                fresh.update({"rect": None, "slot": None, "minimized": True})
            items.append(fresh)
        if not rects:
            self.toast.error("Ни одно окно набора не открыто")
            return
        preset, split, vsplit = L.nearest_preset(rects)
        self.store.update_set(set_id, {"items": items,
                                       "layout": {"preset": preset, "split": split,
                                                  "vsplit": vsplit}})
        self.toast.show(f"Раскладка снята с {len(rects)} {plu_windows(len(rects))}",
                        icon=ft.Icons.SAVE, icon_color=C.MUTED,
                        action=lambda: self._restore_set_items(set_id, before,
                                                               rec["layout"]),
                        action_label="Вернуть")
        self.refresh()

    def _restore_set_items(self, set_id, items, conf):
        self.store.update_set(set_id, {"items": items, "layout": conf})
        self.refresh()

    def _after_launch(self, from_palette: bool = False):
        # Прятать окно после запуска — только когда запускали из палитры: это
        # ровно тот жест, которым раньше пользовались в окне «Запуск».
        if from_palette:
            self.view.close_palette()
            self.search_field.value = ""
            if self.setting("hide_after", True):
                self._hide_to_tray()
        self._safe_refresh()

    def _relocate(self, app_id):
        """«Найти» on a missing program: point the entry at the file again."""
        self._relocating = app_id
        self.pick_file()

    # ---- палитра ----
    def run_palette_action(self, key: str):
        app = self._palette_app()
        if app is None:
            return
        if key == "folder":
            self._show_in_folder(app["id"])
        elif key == "admin":
            self._launch(app["id"], as_admin=True, from_palette=True)
        elif key == "set":
            self.view.close_palette()
            self.search_field.value = ""
            self.refresh()
            self.menu.show(self._window_width() / 2, 200.0, self._set_submenu([app["id"]]),
                           header=menus.text_header("Добавить в набор…"))

    def palette_click(self, row):
        if row["kind"] == "set":
            self._launch_set(row["set"]["id"], from_palette=True)
        else:
            self._launch(row["app"]["id"], from_palette=True)

    def palette_hover(self, index: int, e):
        if e.data == "true" and (self.view.palette_index != index
                                 or self.view.palette_focus != "results"):
            self.view.palette_index = index
            self.view.palette_focus = "results"
            self.refresh(content_only=True)

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

    def _hide_apps(self, ids, hidden: bool):
        """«Скрыть»: плитка уходит из сетки, запись и хоткей остаются."""
        ids = [i for i in ids if i]
        touched = self.store.update_apps(ids, {"hidden": bool(hidden)})
        if not touched:
            return
        self.view.clear_selection()
        text = (f"Скрыто {touched}" if hidden else f"Снова видно: {touched}")
        self.toast.show(text, icon=ft.Icons.VISIBILITY_OFF if hidden else ft.Icons.VISIBILITY,
                        icon_color=C.MUTED,
                        action=lambda: self._hide_apps(ids, not hidden),
                        action_label="Отменить")
        self._on_library_changed()

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
        before = [i for i in ids if not (self.store.get_app(i) or {}).get("favorite")]
        self.store.update_apps(ids, {"favorite": True})
        self.toast.show(f"В избранном: {len(ids)}", icon=ft.Icons.STAR, icon_color=C.STAR,
                        action=lambda: self._undo_favorite(before),
                        action_label="Отменить")
        self.refresh()

    def _undo_favorite(self, ids):
        self.store.update_apps(ids, {"favorite": False})
        self.refresh()

    # ---- наборы ----
    def _new_set(self):
        if self.view.sel:
            self._make_set(list(self.view.sel))
            return
        self.toast.show("Выберите плитки — из них и собирается набор",
                        icon=ft.Icons.LAYERS, icon_color=C.MUTED,
                        action=self._toggle_select_mode, action_label="Выбрать")

    def _make_set(self, ids):
        apps = [a for a in self.apps() if a["id"] in set(ids)]
        if len(apps) < 2:
            self.toast.error("Для набора нужно хотя бы две программы")
            return
        rec = self.store.add_set(queries.set_name_for(apps), [a["id"] for a in apps])
        if not rec:
            return
        self.view.clear_selection()
        self.view.select_mode = False
        self.view.open_set(rec["id"])
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

    def _remove_from_set(self, set_id, app_id):
        rec = self.store.get_set(set_id)
        if not rec:
            return
        before = [dict(i) for i in rec["items"]]
        rest = [i for i in rec["items"] if i["app_id"] != app_id]
        if len(rest) == len(before):
            return
        if not rest:
            self._remove_set(set_id)
            return
        self.store.update_set(set_id, {"items": rest})
        self.toast.show("Убрано из набора", icon=ft.Icons.LAYERS, icon_color=C.MUTED,
                        action=lambda: self._restore_set_items(set_id, before,
                                                               rec["layout"]),
                        action_label="Вернуть")
        self.refresh()

    def _restore_set_members(self, set_id, members):
        self.store.update_set(set_id, {"apps": members})
        self.refresh()

    def _undo_set(self, set_id):
        self.store.remove_set(set_id)
        self.view.close_set()
        self._on_library_changed()

    def _remove_set(self, set_id):
        rec = self.store.remove_set(set_id)
        if not rec:
            return
        if self.view.active_set == set_id:
            self.view.close_set()
        self.toast.show(f"Набор «{rec['name']}» удалён", icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=C.MUTED,
                        action=lambda: self._restore_set(rec), action_label="Вернуть")
        self._on_library_changed()

    def _restore_set(self, rec):
        self.store.restore_set(rec)
        self._on_library_changed()

    def rename_set(self, set_id, name):
        if (name or "").strip():
            self.store.update_set(set_id, {"name": name.strip()})
            self._on_library_changed()

    def set_layout_preset(self, set_id, preset):
        self.store.update_set(set_id, {"layout": {"preset": preset}})
        self.refresh()

    def set_layout_split(self, set_id, key, value):
        """Тянут край прямоугольника на схеме — меняется доля."""
        self.store.update_set(set_id, {"layout": {key: value}})
        self.refresh()

    def set_set_delay(self, set_id, seconds):
        self.store.update_set(set_id, {"delay_seconds": seconds})
        self.refresh()

    def set_set_monitor(self, set_id, index):
        self.store.update_set(set_id, {"monitor": index})
        self.refresh()

    def set_close_together(self, set_id, value):
        self.store.update_set(set_id, {"close_together": bool(value)})
        self.refresh()

    def _set_item_slot(self, set_id, app_id, slot):
        self.store.update_set_item(set_id, app_id, {"slot": slot, "minimized": False})
        self.refresh()

    def _set_item_minimized(self, set_id, app_id, value):
        self.store.update_set_item(set_id, app_id, {"minimized": bool(value)})
        self.refresh()

    def _move_set_item(self, set_id, app_id, delta):
        self.store.move_set_item(set_id, app_id, delta)
        self.refresh()

    def add_to_set_picker(self, set_id, e=None):
        """«Добавить программу» на экране набора: меню из того, чего в нём нет."""
        rec = self.store.get_set(set_id)
        if not rec:
            return
        inside = set(rec["apps"])
        rows = [menus.item(None, a["name"], lambda aid=a["id"]: self._add_to_set(set_id, [aid]))
                for a in sorted(queries.visible(self.apps()), key=lambda a: a["name"].lower())
                if a["id"] not in inside]
        if not rows:
            self.toast.show("В наборе уже всё, что есть в библиотеке",
                            icon=ft.Icons.LAYERS, icon_color=C.MUTED)
            return
        x, y = self._menu_at(e)
        self.menu.show(x, y, rows[:14], header=menus.text_header("Добавить в набор"))

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
        self.view.set_screen("add")
        self.view.reset_add()
        self.start_scan()
        self.refresh()

    def _open_settings(self):
        self.view.set_screen("settings")
        self.refresh()

    def _open_triage(self):
        self.view.set_screen("triage")
        self.refresh()

    def _open_set(self, set_id):
        self.view.open_set(set_id)
        self.refresh()

    def back_to_grid(self):
        self.view.set_screen("grid")
        self.refresh()

    def open_library(self):
        """Трей: показать окно на сетке, без палитры."""
        self.view.close_palette()
        self.view.set_screen("grid")
        self.refresh()

    # ---- настройки ----
    def set_setting(self, key, value):
        self.store.set_setting(key, value)
        cb = self.controllers.get("on_setting")
        if cb:
            cb(key, value)
        self.refresh()

    def cycle_launch_hotkey(self):
        """Step through the combinations that raise the window.

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
        return queries.current_title(self.filter, self.categories())

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
        if cat is None:
            self.popover_layer.visible = False
            self.popover_layer.content = None
            return
        index = [c["id"] for c in self.categories()].index(cat_id)
        # Rail geometry: the header, 14px of padding, the two fixed buttons and
        # a divider above the first category, then 42px rows with 8px gaps.
        top = C.HEADER_H + 14 + (2 + index) * (C.RAIL_BTN + 8) + 9
        height = self._window_height()
        self.popover_layer.left = C.RAIL_W + 8
        self.popover_layer.top = max(C.HEADER_H + 6, min(top, height - C.POPOVER_H - 8))
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
