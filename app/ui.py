"""Centurio UI built with Flet.

A single CenturioUI object owns the page, builds the shell once, and repaints
the dynamic regions (rail, sidebar, content, status bar) on every state change.
Works on desktop (frameless window + tray) and, for preview, in web mode.
"""
from __future__ import annotations

import os

import flet as ft

from . import colors as C
from . import queries
from .format import (  # noqa: F401  (re-exported for dialogs/tests)
    CATEGORY_ICON_CHOICES, T, cat_icon, initials, plu_apps, plu_cats, time_ago)
from .images import (  # noqa: F401  (re-exported for tests)
    _img_size, _is_launcher_art, _MIN_ART_PX, app_hue, icon_image, img_b64)
from .store import Store
from .view_state import ViewState


class CenturioUI:
    def __init__(self, page: ft.Page, store: Store, launcher, controllers=None):
        self.page = page
        self.store = store
        self.launcher = launcher
        self.controllers = controllers or {}
        self.running: set[str] = set()

        # View state (filter/search/sort/mode/selection/panel) is owned by
        # ViewState, not CenturioUI — see app/view_state.py. The properties
        # below are a thin, stable delegation so the rest of this file (and
        # main.py, tests) can keep reading/writing self.filter etc. as plain
        # attributes without knowing where the state actually lives.
        self.view = ViewState(store)
        self._sel_id = None

        # Persistent controls
        self.search_field = ft.TextField(
            value="", hint_text="Поиск приложений…", border=ft.InputBorder.NONE,
            filled=False, dense=True, content_padding=ft.padding.symmetric(0, 0),
            text_size=13, color=C.TEXT, hint_style=ft.TextStyle(color=C.MUTED_2, size=13),
            cursor_color=C.TEXT, on_change=self._on_search, expand=True,
        )
        self.rail_container = ft.Container(width=76, bgcolor=C.BG_0)
        self.sidebar_container = ft.Container(width=236, bgcolor=C.BG_2)
        self.content_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
        self.status_container = ft.Container()

    # ---------- view-state delegation ----------
    # (kept as attributes, not `self.view.x`, so widget-building code below
    # reads naturally; the actual state + transitions live in ViewState.)
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

    # ---------- data helpers ----------
    def state(self):
        return self.store.state()

    def categories(self):
        return sorted(self.state()["categories"], key=lambda c: c.get("order", 0))

    def apps(self):
        return self.state()["apps"]

    # ---------- lifecycle ----------
    def mount(self):
        toolbar = self._build_toolbar()
        main = ft.Column(
            [toolbar, ft.Container(self.content_col, expand=True,
                                   padding=ft.padding.only(28, 8, 28, 8)),
             self.status_container],
            spacing=0, expand=True,
        )
        body = ft.Row([self.rail_container, self.sidebar_container, main],
                      spacing=0, expand=True)
        root = ft.Column([self._build_titlebar(), body], spacing=0, expand=True)
        self.page.add(root)
        self.refresh()

    def set_running(self, ids):
        self.running = set(ids)
        try:
            self.refresh()
        except Exception:
            pass

    def refresh(self):
        self.rail_container.content = self._build_rail()
        # The bar ("Показать" panel) is a standalone toggle now — independent
        # of which category/filter is currently selected — so it can be
        # opened while browsing any category.
        show_sidebar = self.sidebar_open
        self.sidebar_container.visible = show_sidebar
        self.sidebar_container.content = self._build_sidebar() if show_sidebar else None
        self.content_col.controls = self._build_content()
        self.status_container.content = self._build_statusbar()
        self.page.update()

    # ---------- small factory helpers ----------
    def _icon(self, name, size=16, color=C.MUTED):
        return ft.Icon(name, size=size, color=color)

    def _hoverable(self, container: ft.Container, normal, hover):
        def on_hover(e):
            container.bgcolor = hover if e.data == "true" else normal
            container.update()
        container.bgcolor = normal
        container.on_hover = on_hover
        return container

    def _chip_visual(self, a, size, letter_size, radius):
        """Square icon for small contexts: real app icon if available, else a
        coloured letter chip. Works for stored apps and discovered dicts."""
        # In a small square chip, launcher cover art reads best filling the
        # square; a plain app icon is shown whole (contain).
        fit = ft.ImageFit.COVER if _is_launcher_art(a) else ft.ImageFit.CONTAIN
        img = icon_image(a.get("icon"), width=size, height=size, fit=fit)
        if img:
            return ft.Container(
                img, width=size, height=size, border_radius=radius, bgcolor="#17171b",
                alignment=ft.alignment.center, clip_behavior=ft.ClipBehavior.HARD_EDGE)
        hue = app_hue(a)
        c1, c2 = C.chip_colors(hue)
        return ft.Container(
            T(initials(a["name"]), size=letter_size, weight=ft.FontWeight.BOLD, color=C.glyph_color(hue)),
            width=size, height=size, border_radius=radius, alignment=ft.alignment.center,
            gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                       colors=[c1, c2]))

    def _cover_content(self, a, cover_h):
        """The tile cover base container. What to render is decided from the
        *actual* image, not the stored icon_fit (which may be stale):

          * A landscape launcher banner fills the tile, cropping the overflow
            so there are no empty bands.
          * A game title logo (its path contains "logo") is shown whole and
            prominent on a subtle gradient — a composed cover for games with no
            banner, so they read as intentional rather than a lost square.
          * A small image — a plain app/exe icon, or a tiny Steam _icon.jpg
            fallback — is shown at natural small size, centred on a gradient,
            never upscaled into a blur.
        """
        icon_path = a.get("icon")
        size = _img_size(icon_path)
        if _is_launcher_art(a) and size and max(size) >= _MIN_ART_PX and icon_image(icon_path):
            if "logo" in os.path.basename(str(icon_path)).lower():
                return ft.Container(
                    icon_image(icon_path, fit=ft.ImageFit.CONTAIN, expand=True),
                    expand=True, alignment=ft.alignment.center,
                    padding=ft.padding.symmetric(cover_h * 0.16, cover_h * 0.12),
                    gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                               colors=["#23262e", "#121319"]))
            return ft.Container(icon_image(icon_path, fit=ft.ImageFit.COVER, expand=True),
                                expand=True, bgcolor="#131317")
        px = min(int(cover_h * 0.62), 88)
        img = icon_image(icon_path, width=px, height=px, fit=ft.ImageFit.CONTAIN)
        if img:
            return ft.Container(
                img, expand=True, alignment=ft.alignment.center,
                gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                           colors=["#1e1e24", "#131317"]))
        hue = app_hue(a)
        c1, c2 = C.cover_colors(hue)
        gsize = 34 if self.state()["settings"].get("tile_size") == "compact" else 46
        return ft.Container(
            T(initials(a["name"]), size=gsize, weight=ft.FontWeight.BOLD, color=C.glyph_color(hue)),
            expand=True, alignment=ft.alignment.center,
            gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                       colors=[c1, c2]))

    # ---------- titlebar ----------
    def _win_btn(self, icon_name, tooltip, handler, danger=False):
        c = ft.Container(
            ft.Icon(icon_name, size=14, color=C.MUTED),
            width=44, height=32, border_radius=6, alignment=ft.alignment.center,
            on_click=lambda e: handler(),
        )

        def on_hover(e):
            if e.data == "true":
                c.bgcolor = C.DANGER if danger else C.PANEL_3
                c.content.color = "#ffffff" if danger else C.TEXT
            else:
                c.bgcolor = None
                c.content.color = C.MUTED
            c.update()
        c.on_hover = on_hover
        c.tooltip = tooltip
        return c

    def _build_titlebar(self):
        brand = ft.Row([
            T("Centurio", size=13.5, weight=ft.FontWeight.BOLD, color=C.TEXT),
            ft.Container(width=1, height=14, bgcolor=C.LINE_4),
            T("быстрый запуск приложений", size=11, color=C.MUTED_2,
                    font_family="monospace"),
        ], spacing=10)
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

    # ---------- rail ----------
    def _cat_glyph(self, cat, size=19):
        """A category's rail/label glyph: a picked icon, else its first letter,
        tinted with the category colour (RGB/hex, user-editable)."""
        color = C.category_color(cat)
        if cat.get("icon"):
            return ft.Icon(cat_icon(cat.get("icon")), size=size, color=color)
        return T(initials(cat.get("name")), size=size - 1, weight=ft.FontWeight.BOLD, color=color)

    def _rail_item(self, glyph, active, on_click, tooltip, fixed_color=None, on_drop_app=None):
        inner = ft.Container(
            glyph, width=44, height=44, border_radius=14 if active else 22,
            bgcolor="#1e1e22" if active else C.PANEL_2,
            alignment=ft.alignment.center, on_click=lambda e: on_click(), tooltip=tooltip,
            animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
        )

        def on_hover(e):
            if active:
                return
            highlight = e.data == "true"
            inner.bgcolor = "#1e1e22" if highlight else C.PANEL_2
            inner.border_radius = 14 if highlight else 22
            if fixed_color is None:                 # default items tint on hover
                inner.content.color = C.TEXT if highlight else C.MUTED
            inner.update()
        inner.on_hover = on_hover

        # Categories accept dropped app tiles (drag-and-drop to move category).
        content = inner
        if on_drop_app is not None:
            def _accept(e):
                src = self.page.get_control(e.src_id)
                if src is not None and getattr(src, "data", None):
                    on_drop_app(src.data)
                inner.border = None
                inner.update()

            def _will(e):
                inner.border = ft.border.all(2, self._accent())
                inner.update()

            def _leave(e):
                inner.border = None
                inner.update()
            content = ft.DragTarget(group="apps", content=inner,
                                    on_accept=_accept, on_will_accept=_will, on_leave=_leave)

        bar = ft.Container(width=3, height=28, border_radius=ft.border_radius.only(0, 3, 0, 3),
                           bgcolor=self._accent()) if active else ft.Container(width=3)
        return ft.Row([bar, ft.Container(content, expand=True, alignment=ft.alignment.center)],
                      spacing=0)

    def _is_all_view(self):
        return self.view.is_all_view()

    def _build_rail(self):
        all_active = self._is_all_view()
        items = [
            # Toggles the floating bar panel (filters/recents/footer) — works
            # from any category, independent of the selected filter.
            self._rail_item(ft.Icon(ft.Icons.VIEW_SIDEBAR, size=19,
                                    color=C.TEXT if self.sidebar_open else C.MUTED),
                            self.sidebar_open, lambda: self._toggle_sidebar(), "Показать/скрыть панель"),
            # "Главное меню" — the system, non-editable pseudo-category that
            # shows every category's apps together (formerly "Все приложения").
            self._rail_item(ft.Icon(ft.Icons.GRID_VIEW, size=19, color=C.TEXT if all_active else C.MUTED),
                            all_active, lambda: self._set_filter("all"), "Главное меню"),
        ]
        for cat in self.categories():
            active = self.filter == f"category:{cat['id']}"
            items.append(self._rail_item(
                self._cat_glyph(cat), active,
                lambda cid=cat["id"]: self._set_filter(f"category:{cid}"), cat["name"],
                fixed_color=C.category_color(cat),
                on_drop_app=lambda aid, cid=cat["id"]: self._move_app_to_category(aid, cid)))
        items.append(ft.Container(expand=True))
        add = ft.Container(ft.Icon(ft.Icons.ADD, size=16, color=C.MUTED_2),
                           width=44, height=44, border_radius=22, alignment=ft.alignment.center,
                           border=ft.border.all(1.5, C.LINE_4), on_click=lambda e: self._open_categories(),
                           tooltip="Добавить категорию")
        settings = ft.Container(ft.Icon(ft.Icons.SETTINGS, size=18, color=C.MUTED),
                                width=44, height=44, border_radius=22, alignment=ft.alignment.center,
                                on_click=lambda e: self._open_settings(), tooltip="Настройки")
        items += [add, ft.Container(height=6), settings]
        return ft.Container(
            ft.Column(items, spacing=9, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      expand=True),
            padding=ft.padding.only(0, 14, 0, 12),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    # ---------- sidebar ----------
    def _sidebar_filter(self, icon_ctl, label, count, key, count_color=None):
        active = self.filter == key
        row = ft.Container(
            ft.Row([
                ft.Container(icon_ctl, width=16, height=16, alignment=ft.alignment.center),
                T(label, size=13, color=C.TEXT if active else C.TEXT_2,
                        weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400, expand=True),
                T(str(count), size=11, color=count_color or C.MUTED, font_family="monospace"),
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
            ft.Container(T(f"{len(apps)} {plu_apps(len(apps))} · "
                                 f"{len(self.categories())} {plu_cats(len(self.categories()))}",
                                 size=11, color=C.MUTED_2, font_family="monospace",
                                 no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                         padding=ft.padding.only(8, 5, 8, 0)),
            ft.Divider(height=1, color=C.LINE_2),
            ft.Container(T("ПОКАЗАТЬ", size=10.5, weight=ft.FontWeight.W_600,
                                 color=C.MUTED_2), padding=ft.padding.only(10, 0, 0, 8)),
            # "Все приложения" moved out of the bar — it's now the dedicated
            # "Главное меню" rail button (the system all-apps pseudo-category).
            self._sidebar_filter(ft.Icon(ft.Icons.STAR_BORDER, size=16, color=C.MUTED),
                                 "Избранное", fav, "favorites"),
            self._sidebar_filter(ft.Icon(ft.Icons.SCHEDULE, size=16, color=C.MUTED),
                                 "Недавние", recent_count, "recent"),
            self._sidebar_filter(ft.Container(width=8, height=8, border_radius=4, bgcolor=C.GREEN),
                                 "Запущено", len(self.running), "running", C.GREEN),
        ]

        recents = queries.recent_apps(apps, limit=4)
        if recents:
            top += [ft.Divider(height=1, color=C.LINE_2),
                    ft.Container(T("НЕДАВНИЕ", size=10.5, weight=ft.FontWeight.W_600,
                                         color=C.MUTED_2), padding=ft.padding.only(10, 0, 0, 8))]
            for a in recents:
                top.append(self._recent_row(a))

        footer = self._sidebar_footer()
        return ft.Container(
            ft.Column(top + [ft.Container(expand=True), footer], spacing=2, expand=True),
            padding=ft.padding.only(14, 20, 14, 14),
            border=ft.border.only(right=ft.BorderSide(1, C.LINE_2)), expand=True,
        )

    def _recent_row(self, a):
        row = ft.Container(
            ft.Row([
                self._chip_visual(a, 30, 13, 9),
                ft.Column([
                    T(a["name"], size=12.5, color=C.TEXT, weight=ft.FontWeight.W_500,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T(time_ago(a["last_launched"]), size=10.5, color=C.MUTED_2,
                            font_family="monospace"),
                ], spacing=1, expand=True, tight=True),
            ], spacing=10),
            padding=ft.padding.symmetric(7, 10), border_radius=9,
            on_click=lambda e, i=a["id"]: self._launch(i),
        )
        self._hoverable(row, None, C.PANEL_2)
        return row

    def _mini_toggle(self, value, on_toggle):
        """Compact pill toggle matching the design (smaller than a Material Switch)."""
        knob = ft.Container(width=13, height=13, border_radius=7,
                            bgcolor=C.BG_1 if value else C.MUTED)
        return ft.Container(
            ft.Row([knob], alignment=ft.MainAxisAlignment.END if value else ft.MainAxisAlignment.START),
            width=32, height=18, border_radius=9, padding=ft.padding.all(2.5),
            bgcolor=self._accent() if value else "#2a2a30",
            on_click=lambda e: on_toggle(not value),
        )

    def _sidebar_footer(self):
        s = self.state()["settings"]

        def toggle(label, key):
            sw = self._mini_toggle(s.get(key, False),
                                   lambda v, k=key: self._set_setting(k, v))
            return ft.Container(
                ft.Row([T(label, size=12.5, color=C.TEXT_2, expand=True, no_wrap=True,
                          overflow=ft.TextOverflow.ELLIPSIS), sw],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=8),
                padding=ft.padding.only(10, 3, 6, 3), border_radius=8,
            )

        return ft.Container(
            ft.Column([
                toggle("Автозапуск с Windows", "autostart"),
                toggle("Сворачивать в трей", "minimize_to_tray"),
                ft.Container(ft.Row([T("Centurio", size=11, color=C.MUTED_3, font_family="monospace"),
                                     T("v1.2.0", size=11, color=C.MUTED_3, font_family="monospace")],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                             padding=ft.padding.only(10, 6, 10, 0)),
            ], spacing=2),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)),
            padding=ft.padding.only(0, 10, 0, 0),
        )

    # ---------- toolbar ----------
    def _build_toolbar(self):
        search = ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.SEARCH, size=14, color=C.MUTED_2),
                self.search_field,
                ft.Container(T("Ctrl+K", size=10.5, color=C.MUTED_2, font_family="monospace"),
                             bgcolor=C.PANEL_3, border=ft.border.all(1, C.LINE),
                             border_radius=5, padding=ft.padding.symmetric(2, 6)),
            ], spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=38, width=440, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE),
            border_radius=10, padding=ft.padding.only(12, 0, 8, 0),
        )
        sort_labels = {"alpha": "По алфавиту", "recent": "Недавние",
                       "added": "Недавно добавленные", "manual": "Вручную"}
        sort_btn = ft.Container(
            ft.Row([T(sort_labels[self.sort], size=12.5, color=C.MUTED),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=14, color=C.MUTED)], spacing=7),
            height=36, padding=ft.padding.symmetric(0, 12), border=ft.border.all(1, C.LINE),
            border_radius=9, on_click=lambda e: self._cycle_sort(), alignment=ft.alignment.center,
        )
        self._hoverable(sort_btn, None, C.PANEL_2)

        def view_btn(icon_name, m, tip):
            active = self.mode == m
            return ft.Container(ft.Icon(icon_name, size=13, color=C.TEXT if active else C.MUTED_2),
                                width=36, height=36, alignment=ft.alignment.center,
                                bgcolor="#1e1e22" if active else None,
                                on_click=lambda e: self._set_mode(m), tooltip=tip)
        view_toggle = ft.Container(
            ft.Row([view_btn(ft.Icons.GRID_VIEW, "grid", "Сетка"),
                    view_btn(ft.Icons.VIEW_LIST, "list", "Список")], spacing=0),
            border=ft.border.all(1, C.LINE), border_radius=9, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        rescan_btn = ft.Container(
            ft.Icon(ft.Icons.REFRESH, size=17, color=C.MUTED),
            width=36, height=36, alignment=ft.alignment.center,
            border=ft.border.all(1, C.LINE), border_radius=9,
            on_click=lambda e: self._rescan(), tooltip="Пересканировать приложения и иконки")
        self._hoverable(rescan_btn, None, C.PANEL_2)
        add_btn = ft.Container(
            ft.Row([ft.Icon(ft.Icons.ADD, size=15, color=C.BG_1),
                    T("Добавить приложение", size=13, weight=ft.FontWeight.W_600, color=C.BG_1)],
                   spacing=7, alignment=ft.MainAxisAlignment.CENTER),
            height=36, padding=ft.padding.symmetric(0, 16), bgcolor=self._accent(),
            border_radius=9, on_click=lambda e: self._open_app_dialog(), alignment=ft.alignment.center,
        )
        return ft.Container(
            ft.Row([search, ft.Container(expand=True), sort_btn, view_toggle, rescan_btn, add_btn],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(28, 18, 28, 12),
        )

    # ---------- content ----------
    def _build_content(self):
        self._sel_id = self._selected_id()
        apps = self.apps()
        if not apps:
            return [self._empty("Библиотека пуста",
                                "Добавьте первое приложение — выберите его файл, и Centurio "
                                "закрепит его для быстрого запуска.", "Добавить приложение",
                                self._open_app_dialog)]

        controls = []
        is_all = self.filter == "all" and not self.query.strip()
        settings = self.state()["settings"]

        if is_all:
            # Placeholder — hero card functionality removed for now; the slot
            # stays put regardless of state (nothing to launch/hide it).
            controls.append(self._hero())

        if is_all and settings.get("show_quick_row"):
            quick = queries.quick_apps(apps)
            if quick:
                controls += self._quick_row(quick)

        sections = self._sections()
        if not sections or all(not s["apps"] for s in sections):
            controls.append(self._empty("Ничего не найдено",
                                        "Попробуйте изменить запрос." if self.query
                                        else "В этом разделе пока нет приложений.", None, None))
            return controls

        for sec in sections:
            if not sec["apps"]:
                continue
            controls.append(self._section_head(sec))
            controls.append(self._grid(sec["apps"]) if self.mode == "grid" else self._list(sec["apps"]))
        controls.append(ft.Container(height=10))
        return controls

    def _sections(self):
        return queries.build_sections(self.apps(), self.categories(), self.filter,
                                      self.query, self.sort, self.running)

    def _hero(self):
        # Placeholder slot — functionality stripped for now (was the
        # "Продолжить" card). Kept as an empty box that's always rendered.
        return ft.Container(
            bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=14,
            height=170, margin=ft.margin.only(0, 6, 0, 20),
        )

    def _quick_row(self, quick):
        cards = []
        for i, q in enumerate(quick):
            key = q.get("hotkey") or f"Ctrl+{i + 1}"
            card = ft.Container(
                ft.Stack([
                    ft.Column([
                        self._chip_visual(q, 44, 20, 12),
                        ft.Container(height=7),
                        T(q["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        T(q.get("sub") or "", size=11, color=C.MUTED_2, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=0, tight=True),
                    ft.Container(T(key, size=10, color=C.MUTED_2, font_family="monospace"),
                                 right=0, top=0, bgcolor=C.PANEL_3, border=ft.border.all(1, C.LINE),
                                 border_radius=5, padding=ft.padding.symmetric(1, 5)),
                ]),
                width=152, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=12,
                padding=ft.padding.only(14, 14, 14, 12),
                on_click=lambda e, i2=q["id"]: self._launch(i2),
            )
            self._hoverable(card, C.PANEL, C.PANEL_2)
            cards.append(ft.GestureDetector(card, on_secondary_tap=lambda e, ap=q: self._open_context_menu(ap)))
        head = ft.Container(
            ft.Row([T("Быстрый запуск", size=15, weight=ft.FontWeight.BOLD, color=C.TEXT),
                    T("закреплено · горячие клавиши", size=11.5, color=C.MUTED_2,
                            font_family="monospace")], spacing=10),
            padding=ft.padding.only(0, 12, 0, 12))
        return [head, ft.Container(ft.Row(cards, spacing=12, wrap=True),
                                   padding=ft.padding.only(0, 0, 0, 20))]

    def _section_head(self, sec):
        row = [ft.Container(width=9, height=9, border_radius=3, bgcolor="#43434c"),
               T(sec["name"], size=15, weight=ft.FontWeight.BOLD, color=C.TEXT),
               T(f"{len(sec['apps'])} {plu_apps(len(sec['apps']))}", size=11.5,
                       color=C.MUTED_2, font_family="monospace"),
               ft.Container(expand=True)]
        if sec.get("editable"):
            row.append(ft.Container(T("Изменить", size=12, color=C.MUTED_2),
                                    on_click=lambda e, cid=sec["cid"]: self._open_categories(cid)))
        return ft.Container(ft.Row(row, spacing=10), padding=ft.padding.only(0, 10, 0, 14))

    def _use_poster(self, a):
        """A game with a portrait poster renders as a tall poster tile when the
        poster layout is enabled (looks like a real game library)."""
        return bool(self.state()["settings"].get("game_posters", True)
                    and _is_launcher_art(a) and img_b64(a.get("poster")))

    def _grid(self, apps):
        # A wrapping row of fixed-size tiles flows and sizes to its content, so it
        # never clips rows regardless of window width (unlike a fixed-height GridView).
        tiles = [self._draggable_tile(a, apps) for a in apps]
        return ft.Container(ft.Row(tiles, wrap=True, spacing=15, run_spacing=15,
                                   vertical_alignment=ft.CrossAxisAlignment.START),
                            padding=ft.padding.only(0, 0, 0, 10))

    def _draggable_tile(self, a, section_apps):
        """A tile that can be dragged to reorder (drop on another tile) or moved
        to another category (drop on a rail category)."""
        base = self._poster_tile(a) if self._use_poster(a) else self._tile(a)
        drag = ft.Draggable(group="apps", content=base, data=a["id"])

        def on_accept(e):
            src = self.page.get_control(e.src_id)
            if src is not None and getattr(src, "data", None):
                self._reorder_app(section_apps, src.data, a["id"])
        return ft.DragTarget(group="apps", content=drag, on_accept=on_accept)

    def _poster_tile(self, a):
        """A 2:3 portrait poster tile for a game (Steam library_600x900)."""
        compact = self.state()["settings"].get("tile_size") == "compact"
        width = 128 if compact else 158
        height = round(width * 1.5)
        running = a["id"] in self.running
        poster = ft.Image(src_base64=img_b64(a.get("poster")), width=width, height=height,
                          fit=ft.ImageFit.COVER)
        # Gradient scrim + name at the bottom so the title stays readable.
        scrim = ft.Container(
            T(a["name"], size=12.5, weight=ft.FontWeight.W_600, color="#ffffff",
              max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            left=0, right=0, bottom=0, padding=ft.padding.only(10, 20, 10, 9),
            gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center,
                                       colors=["#00000000", "#000000e8"]))
        children = [poster, scrim]
        if running:
            children.append(ft.Container(
                ft.Row([ft.Container(width=5, height=5, border_radius=3, bgcolor=C.GREEN),
                        T("Запущено", size=10, weight=ft.FontWeight.W_600, color="#d8fce6")],
                       spacing=5, tight=True),
                left=8, top=8, bgcolor="#0c100e", border=ft.border.all(1, "#2a5f42"),
                border_radius=20, padding=ft.padding.symmetric(3, 8)))
        children.append(ft.Container(
            ft.Icon(ft.Icons.STAR if a.get("favorite") else ft.Icons.STAR_BORDER, size=14,
                    color=C.STAR if a.get("favorite") else "#ffffff"),
            right=8, top=8, width=26, height=26, border_radius=8, bgcolor="#0c0c0edd",
            alignment=ft.alignment.center, on_click=lambda e, i=a["id"]: self._toggle_fav(i)))

        selected = a["id"] == self._sel_id
        tile = ft.Container(
            ft.Stack(children), width=width, height=height, bgcolor=C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE)

        def on_hover(e):
            if a["id"] == self._sel_id:
                return
            tile.border = ft.border.all(1, C.LINE_5 if e.data == "true" else C.LINE)
            tile.update()
        tile.on_hover = on_hover
        return ft.GestureDetector(tile, on_tap=lambda e, i=a["id"]: self._launch(i),
                                  on_secondary_tap=lambda e, ap=a: self._open_context_menu(ap),
                                  mouse_cursor=ft.MouseCursor.CLICK)

    def _tile(self, a):
        compact = self.state()["settings"].get("tile_size") == "compact"
        width = 152 if compact else 196
        cover_h = round(width * 0.62)
        running = a["id"] in self.running
        cover_children = [self._cover_content(a, cover_h)]
        if running:
            cover_children.append(ft.Container(
                ft.Row([ft.Container(width=5, height=5, border_radius=3, bgcolor=C.GREEN),
                        T("Запущено", size=10, weight=ft.FontWeight.W_600, color="#d8fce6")],
                       spacing=5, tight=True),
                left=10, top=10, bgcolor="#0c100e", border=ft.border.all(1, "#2a5f42"),
                border_radius=20, padding=ft.padding.symmetric(3, 8)))
        star = ft.Container(
            ft.Icon(ft.Icons.STAR if a.get("favorite") else ft.Icons.STAR_BORDER, size=14,
                    color=C.STAR if a.get("favorite") else "#ffffff"),
            right=8, top=8, width=26, height=26, border_radius=8, bgcolor="#0c0c0edd",
            alignment=ft.alignment.center, on_click=lambda e, i=a["id"]: self._toggle_fav(i),
            tooltip="В избранное")
        cover_children.append(star)

        foot = ft.Container(
            ft.Row([
                ft.Column([T(a["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
                                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                           T(a.get("sub") or self._path_tail(a.get("path")), size=11,
                                   color=C.MUTED_2, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                          spacing=1, expand=True, tight=True),
                ft.Container(ft.Icon(ft.Icons.PLAY_ARROW, size=14, color=C.MUTED),
                             width=30, height=30, border_radius=9, bgcolor=C.PANEL_3,
                             alignment=ft.alignment.center,
                             on_click=lambda e, i=a["id"]: self._launch(i)),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(13, 11, 13, 12))

        selected = a["id"] == self._sel_id
        tile = ft.Container(
            ft.Column([ft.Container(ft.Stack(cover_children, expand=True), height=cover_h,
                                    clip_behavior=ft.ClipBehavior.HARD_EDGE), foot],
                      spacing=0, tight=True),
            width=width, bgcolor=C.PANEL,
            border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
            border_radius=14, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        def on_hover(e):
            if a["id"] == self._sel_id:
                return
            tile.border = ft.border.all(1, C.LINE_5 if e.data == "true" else C.LINE)
            tile.update()
        tile.on_hover = on_hover
        return ft.GestureDetector(tile, on_tap=lambda e, i=a["id"]: self._launch(i),
                                  on_secondary_tap=lambda e, ap=a: self._open_context_menu(ap),
                                  mouse_cursor=ft.MouseCursor.CLICK)

    def _list(self, apps):
        rows = []
        for a in apps:
            running = a["id"] in self.running
            controls = [
                self._chip_visual(a, 40, 17, 10),
                ft.Column([T(a["name"], size=13.5, weight=ft.FontWeight.W_600, color=C.TEXT),
                           T(a.get("sub") or self._path_tail(a.get("path")), size=11.5, color=C.MUTED_2)],
                          spacing=1, expand=True, tight=True),
            ]
            if running:
                controls.append(ft.Row([ft.Container(width=5, height=5, border_radius=3, bgcolor=C.GREEN),
                                         T("Запущено", size=10, color="#7ee2a8")], spacing=5, tight=True))
            controls.append(ft.Container(
                ft.Icon(ft.Icons.STAR if a.get("favorite") else ft.Icons.STAR_BORDER, size=15,
                        color=C.STAR if a.get("favorite") else C.MUTED),
                width=30, height=30, border_radius=9, alignment=ft.alignment.center,
                on_click=lambda e, i=a["id"]: self._toggle_fav(i)))
            controls.append(ft.Container(ft.Icon(ft.Icons.MORE_HORIZ, size=16, color=C.MUTED),
                                         width=30, height=30, border_radius=9, alignment=ft.alignment.center,
                                         on_click=lambda e, ap=a: self._open_context_menu(ap)))
            selected = a["id"] == self._sel_id
            row = ft.Container(ft.Row(controls, spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                               padding=ft.padding.symmetric(10, 14), border_radius=11,
                               border=ft.border.all(2, self._accent()) if selected else ft.border.all(1, C.LINE),
                               bgcolor=C.PANEL,
                               on_click=lambda e, i=a["id"]: self._launch(i))
            if not selected:
                self._hoverable(row, C.PANEL, C.PANEL_2)
            rows.append(ft.GestureDetector(row, on_secondary_tap=lambda e, ap=a: self._open_context_menu(ap)))
        return ft.Container(ft.Column(rows, spacing=6), padding=ft.padding.only(0, 0, 0, 10))

    def _empty(self, title, text, btn_label, on_click):
        controls = [
            ft.Container(ft.Icon(ft.Icons.GRID_VIEW, size=26, color=C.MUTED),
                         width=64, height=64, border_radius=18, bgcolor=C.PANEL,
                         border=ft.border.all(1, C.LINE), alignment=ft.alignment.center),
            ft.Container(height=18),
            T(title, size=17, weight=ft.FontWeight.BOLD, color=C.TEXT),
            ft.Container(height=8),
            T(text, size=13, color=C.MUTED_2, text_align=ft.TextAlign.CENTER, width=360),
        ]
        if btn_label:
            controls += [ft.Container(height=20),
                         ft.Container(ft.Row([ft.Icon(ft.Icons.ADD, size=15, color=C.BG_1),
                                              T(btn_label, size=13, weight=ft.FontWeight.W_600, color=C.BG_1)],
                                             spacing=7, tight=True),
                                      height=36, padding=ft.padding.symmetric(0, 16), bgcolor=self._accent(),
                                      border_radius=9, on_click=lambda e: on_click(),
                                      alignment=ft.alignment.center)]
        return ft.Container(
            ft.Column(controls, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
            alignment=ft.alignment.center, padding=ft.padding.only(0, 70, 0, 40))

    def _build_statusbar(self):
        parts = [ft.Row([ft.Container(width=6, height=6, border_radius=3, bgcolor=C.GREEN),
                         T("Centurio работает в фоне — значок в трее", size=11.5, color=C.MUTED_2)],
                        spacing=7)]
        if self.running:
            parts.append(T(f"{len(self.running)} запущено", size=11.5, color=C.MUTED_2,
                                 font_family="monospace"))
        parts += [ft.Container(expand=True),
                  T(f"{len(self.apps())} {plu_apps(len(self.apps()))} · "
                          f"{len(self.categories())} {plu_cats(len(self.categories()))}",
                          size=11.5, color=C.MUTED_2, font_family="monospace")]
        return ft.Container(ft.Row(parts, spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.padding.symmetric(9, 28), bgcolor=C.BG_2,
                            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

    # ---------- helpers ----------
    def _accent(self):
        return self.state()["settings"].get("accent", "#f5f5f7")

    def _current_title(self):
        return queries.current_title(self.filter, self.query, self.categories())

    def _path_tail(self, p):
        if not p:
            return ""
        return p.replace("\\", "/").rstrip("/").split("/")[-1]

    # ---------- actions ----------
    def _toggle_sidebar(self):
        """Open/close the floating bar panel — independent of the current
        category/filter, so it can be toggled while browsing anything."""
        self.view.toggle_sidebar()
        self.refresh()

    def _set_filter(self, f):
        self.view.set_filter(f)
        self.search_field.value = ""
        self.refresh()

    def _set_mode(self, m):
        self.view.set_mode(m)
        self.refresh()

    def _cycle_sort(self):
        self.view.cycle_sort()
        self.refresh()

    def _move_app_to_category(self, app_id, cid):
        a = self.store.get_app(app_id)
        if a and a.get("category_id") != cid:
            self.store.update_app(app_id, {"category_id": cid})
            cat = next((c for c in self.categories() if c["id"] == cid), None)
            self._toast(f"Перемещено в «{cat['name']}»" if cat else "Перемещено")
            self._on_library_changed()

    def _reorder_app(self, section_apps, dragged_id, target_id):
        """Place the dragged app just before the target within its section and
        switch to manual sort so the new order sticks and is visible."""
        ids = [a["id"] for a in section_apps]
        if dragged_id not in ids or dragged_id == target_id:
            return
        ids.remove(dragged_id)
        ids.insert(ids.index(target_id) if target_id in ids else len(ids), dragged_id)
        self.store.reorder_apps(ids)
        if self.sort != "manual":
            self.view.set_sort("manual")
        self.refresh()

    def _on_search(self, e):
        self.view.set_query(e.control.value)
        self.refresh()

    def _icon_cache_dir(self):
        from pathlib import Path
        return str(Path(self.store.path).parent / "icons")

    def _rescan(self, silent=False):
        """Re-resolve icons for existing apps and look for newly installed
        programs. Runs off the UI thread; toasts the result."""
        import threading

        if not silent:
            self._toast("Пересканирование…")

        def work():
            from . import discovery, log
            try:
                cache = self._icon_cache_dir()
                changed = discovery.backfill_icons(self.store, cache, refresh=True)
                found = discovery.discover_apps(cache)
                existing = {(a.get("path") or "").lower() for a in self.store.state()["apps"]}
                new = [a for a in found if (a.get("path") or "").lower() not in existing]
                self._new_installed = len(new)
                self._on_library_changed()
                if new:
                    self._toast(f"Найдено новых программ: {len(new)} — откройте «Добавить приложение»")
                elif not silent:
                    self._toast("Иконки обновлены" if changed else "Всё актуально")
            except Exception:
                log.exception("rescan failed")
                if not silent:
                    self._toast("Не удалось пересканировать", error=True)
        threading.Thread(target=work, daemon=True).start()

    # ---------- keyboard navigation ----------
    def _flat_apps(self):
        """Apps in on-screen order (the grid/list sections), for arrow-key nav."""
        return queries.flatten_sections(self._sections())

    def _selected_id(self):
        flat = self._flat_apps()
        if 0 <= self.selected < len(flat):
            return flat[self.selected]["id"]
        return None

    def move_selection(self, delta):
        flat = self._flat_apps()
        if not flat:
            self.selected = -1
            return
        self.view.move_selection(delta, len(flat))
        self.refresh()

    def activate_selected(self):
        flat = self._flat_apps()
        if not flat:
            return
        idx = self.selected if 0 <= self.selected < len(flat) else 0
        self._launch(flat[idx]["id"])

    def _launch(self, app_id):
        app = self.store.get_app(app_id)
        if not app:
            return
        res = self.launcher.launch(app)
        if res.get("ok"):
            self.store.mark_launched(app_id)
            self.running = set(self.launcher.running_ids())
            self._toast(f"Запуск: {app['name']}")
        else:
            self._toast(res.get("error", "Не удалось запустить"), error=True)
        self.refresh()

    def _toggle_fav(self, app_id):
        a = self.store.get_app(app_id)
        if a:
            self.store.update_app(app_id, {"favorite": not a.get("favorite")})
        self.refresh()

    def _on_library_changed(self):
        # A category can be deleted while it's the active filter (or renamed/
        # recolored elsewhere); make sure we're never pointed at a filter that
        # no longer resolves to anything, instead of showing a dead, empty view.
        self.view.revalidate(self.categories())
        cb = self.controllers.get("on_library_changed")
        if cb:
            cb()
        self.refresh()

    def _show_in_folder(self, app_id):
        a = self.store.get_app(app_id)
        if a:
            res = self.launcher.show_in_folder(a)
            if not res.get("ok"):
                self._toast(res.get("error", "Не найдено"), error=True)

    def _set_setting(self, key, value):
        self.store.set_setting(key, value)
        cb = self.controllers.get("on_setting")
        if cb:
            cb(key, value)
        self.refresh()

    def _toast(self, msg, error=False):
        self.page.open(ft.SnackBar(T(msg, color=C.TEXT), bgcolor=C.PANEL_2,
                                   duration=2200))

    # ---------- window ----------
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

    # ---------- dialogs ----------
    def _open_app_dialog(self, existing=None):
        from .dialogs import open_app_dialog
        open_app_dialog(self, existing)

    def _open_context_menu(self, app):
        from .dialogs import open_context_menu
        open_context_menu(self, app)

    def _open_categories(self, focus_id=None):
        from .dialogs import open_categories_dialog
        open_categories_dialog(self)

    def _open_settings(self):
        from .dialogs import open_settings_dialog
        open_settings_dialog(self)
