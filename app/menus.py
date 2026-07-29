"""Правый клик.

Четыре меню одной формы: по плитке, по нескольким выбранным, по категории и по
пустому месту сетки. Меню — не модальное окно: это слой поверх интерфейса,
который закрывается кликом мимо, Esc или выбором пункта.

Здесь только рисование и раскладка; что делает пункт, решает `ui.py`.
"""
from __future__ import annotations

import flet as ft

from . import colors as C
from .format import T, cat_icon

ROW_H = 36
HEADER_H = 44
SEPARATOR_H = 11
SUBMENU_W = 240


def item(icon, label, on_click, *, hint: str = "", danger: bool = False,
         submenu: bool = False, disabled: bool = False):
    """One menu row. `hint` is the quiet right-hand note («место 5», «Enter»).

    Keep hints to characters the bundled fonts actually carry: neither Inter nor
    Mono-Regular has the return arrow, and a missing glyph renders as a blank
    box, so the word «Enter» is spelled out instead.
    """
    return {"kind": "item", "icon": icon, "label": label, "on_click": on_click,
            "hint": hint, "danger": danger, "submenu": submenu, "disabled": disabled}


def separator():
    return {"kind": "sep"}


def height_of(rows) -> int:
    """How tall the menu will be, so it can be flipped up near the bottom edge."""
    return sum(SEPARATOR_H if r["kind"] == "sep" else ROW_H for r in rows)


class MenuHost:
    """The menu layer. One menu at a time, plus at most one open submenu."""

    def __init__(self, page: ft.Page, on_dismiss=None):
        self.page = page
        self.on_dismiss = on_dismiss
        self.open = False
        self._rows: list[dict] = []
        self._header = None
        self._x = 0.0
        self._y = 0.0
        self._submenu: dict | None = None

        # A full-window catcher under the menu: clicking anywhere else closes
        # it, which is what makes this a menu and not a floating panel.
        self.shade = ft.Container(left=0, top=0, right=0, bottom=0, bgcolor=C.TRANSPARENT,
                                  on_click=lambda e: self.close())
        self.card = ft.Container(visible=False)
        self.sub_card = ft.Container(visible=False)
        self.control = ft.Stack([self.shade, self.card, self.sub_card],
                                left=0, top=0, right=0, bottom=0, visible=False)

    # ---- открытие и закрытие ----
    def show(self, x: float, y: float, rows, header=None):
        self._rows = [r for r in rows if r]
        self._header = header
        self._x, self._y = x, y
        self._submenu = None
        self.open = True
        self._render()

    def close(self):
        if not self.open:
            return
        self.open = False
        self._submenu = None
        self.control.visible = False
        self.card.visible = False
        self.sub_card.visible = False
        self._safe_update()
        if self.on_dismiss:
            self.on_dismiss()

    def toggle_submenu(self, key: str, rows, anchor_y: float):
        if self._submenu and self._submenu["key"] == key:
            self._submenu = None
        else:
            self._submenu = {"key": key, "rows": rows, "y": anchor_y}
        self._render()

    # ---- раскладка ----
    def _window(self) -> tuple[float, float]:
        win = getattr(self.page, "window", None)
        return (getattr(win, "width", None) or C.LIBRARY_W,
                getattr(win, "height", None) or C.LIBRARY_H)

    def _place(self, x, y, width, height):
        """Keep the menu inside the window: flip it left/up when it wouldn't fit."""
        win_w, win_h = self._window()
        left = x if x + width + 8 <= win_w else max(8.0, x - width)
        top = y if y + height + 8 <= win_h else max(8.0, win_h - height - 8)
        return left, top

    def _render(self):
        width = C.MENU_W if self._header else SUBMENU_W + 22
        height = height_of(self._rows) + (HEADER_H if self._header else 0) + 16
        left, top = self._place(self._x, self._y, width, height)

        self.card.content = self._card(self._rows, self._header, width)
        self.card.left, self.card.top = left, top
        self.card.width = width
        self.card.visible = True

        if self._submenu:
            rows = self._submenu["rows"]
            sub_h = height_of(rows) + 16
            sub_left, sub_top = self._place(left + width + 6, self._submenu["y"],
                                            SUBMENU_W, sub_h)
            self.sub_card.content = self._card(rows, None, SUBMENU_W)
            self.sub_card.left, self.sub_card.top = sub_left, sub_top
            self.sub_card.width = SUBMENU_W
            self.sub_card.visible = True
        else:
            self.sub_card.visible = False

        self.control.visible = True
        self._safe_update()

    def _card(self, rows, header, width):
        children = []
        if header is not None:
            children += [header, ft.Container(height=1, bgcolor=C.LINE_2,
                                              margin=ft.margin.only(4, 0, 4, 6))]
        for row in rows:
            children.append(self._row(row) if row["kind"] == "item" else
                            ft.Container(height=1, bgcolor=C.LINE_2,
                                         margin=ft.margin.symmetric(5, 4)))
        return ft.Container(
            ft.Column(children, spacing=1, tight=True),
            width=width, bgcolor=C.PANEL, border=ft.border.all(1, C.MENU_BORDER),
            border_radius=14, padding=ft.padding.all(8),
            shadow=ft.BoxShadow(blur_radius=60, offset=ft.Offset(0, 24),
                                color=C.SHADOW_MENU))

    def _row(self, row):
        color = C.ERR_TEXT if row["danger"] else C.TEXT_2
        icon_color = C.ERR_TEXT if row["danger"] else C.MUTED
        if row["disabled"]:
            color = icon_color = C.MUTED_3
        controls = []
        if row["icon"]:
            # Flet takes both ft.Icons.X and its plain name, so callers can pass
            # either — including a category's stored icon name.
            controls.append(ft.Icon(row["icon"], size=17, color=icon_color))
        controls.append(T(row["label"], size=13.5, color=color, expand=True,
                          max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        if row["hint"]:
            controls.append(T(row["hint"], size=11, color=C.TEXT_FAINT,
                              font_family="monospace" if len(row["hint"]) <= 3 else None))
        if row["submenu"]:
            controls.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=C.TEXT_FAINT))

        container = ft.Container(
            ft.Row(controls, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(9, 12), border_radius=9,
            on_click=None if row["disabled"] else (lambda e, r=row: self._fire(r)))
        if not row["disabled"]:
            def on_hover(e, c=container):
                c.bgcolor = C.PANEL_3 if e.data == "true" else None
                c.update()
            container.on_hover = on_hover
        return container

    def _fire(self, row):
        # A row that opens a submenu keeps the menu up; everything else is a
        # command, so the menu gets out of the way before it runs.
        if not row["submenu"]:
            self.close()
        handler = row["on_click"]
        if handler:
            handler()

    def _safe_update(self):
        try:
            if self.control.page:
                self.control.update()
        except Exception:
            from . import log
            log.exception("updating the context menu failed")


def app_header(ui, app, running: bool):
    """Шапка меню приложения: иконка, имя и точка «запущено»."""
    row = [ui.icon_slot(app, 30, 9, glyph=16),
           T(app["name"], size=14, weight=ft.FontWeight.BOLD, color=C.TEXT, expand=True,
             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
    if running:
        row.append(ft.Container(width=6, height=6, border_radius=3, bgcolor=C.GREEN))
    return ft.Container(ft.Row(row, spacing=11,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.padding.only(12, 10, 12, 12))


def text_header(label: str, count: str = ""):
    row = [T(label, size=13.5, weight=ft.FontWeight.BOLD, color=C.TEXT, expand=True)]
    if count:
        row.append(T(count, size=11, color=C.TEXT_FAINT))
    return ft.Container(ft.Row(row, spacing=10), padding=ft.padding.only(12, 10, 12, 12))


def category_header(ui, cat, count: int):
    return ft.Container(
        ft.Row([ft.Icon(cat_icon(cat.get("icon")), size=16, color=C.category_color(cat)),
                T(cat["name"], size=13.5, weight=ft.FontWeight.BOLD, color=C.TEXT,
                  expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                T(str(count), size=11, color=C.TEXT_FAINT)],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(12, 10, 12, 12))
