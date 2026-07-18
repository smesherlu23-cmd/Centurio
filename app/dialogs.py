"""Modal dialogs: add/edit app, category management, settings."""
from __future__ import annotations

import flet as ft

from . import colors as C
from .store import hue_from_string
from .ui import CATEGORY_ICON_CHOICES, cat_icon, initials, T


def _field_label(text):
    return T(text, size=11.5, weight=ft.FontWeight.W_600, color=C.MUTED)


def _text_input(value, hint, on_change=None):
    return ft.TextField(
        value=value or "", hint_text=hint, on_change=on_change,
        bgcolor=C.BG_1, border_color=C.LINE, focused_border_color=C.LINE_5,
        color=C.TEXT, text_size=13, height=42, content_padding=ft.padding.symmetric(6, 12),
        cursor_color=C.TEXT, hint_style=ft.TextStyle(color=C.MUTED_2, size=13),
    )


def _outline_btn(label, icon, on_click):
    row = [T(label, size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT)]
    if icon:
        row.insert(0, ft.Icon(icon, size=14, color=C.TEXT))
    return ft.Container(ft.Row(row, spacing=7, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                        height=40, padding=ft.padding.symmetric(0, 14),
                        border=ft.border.all(1, C.LINE_4), border_radius=9,
                        on_click=lambda e: on_click(), alignment=ft.alignment.center)


def _primary_btn(label, on_click):
    return ft.Container(T(label, size=13, weight=ft.FontWeight.W_600, color=C.BG_1),
                        height=40, padding=ft.padding.symmetric(0, 18),
                        bgcolor="#f5f5f7", border_radius=9,
                        on_click=lambda e: on_click(), alignment=ft.alignment.center)


def open_app_dialog(app_ui, existing=None):
    page = app_ui.page
    store = app_ui.store
    is_edit = existing is not None
    cats = app_ui.categories()
    draft = dict(existing) if existing else {
        "name": "", "path": "", "sub": "",
        "category_id": cats[0]["id"] if cats else "work",
        "hue": hue_from_string(str(id(object()))), "favorite": False, "quick": False,
    }
    if not isinstance(draft.get("hue"), int):
        draft["hue"] = 210

    def _preview_bits():
        c1, c2 = C.chip_colors(draft["hue"])
        return (ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                                  colors=[c1, c2]),
                T(initials(draft["name"]), size=20, weight=ft.FontWeight.BOLD,
                  color=C.glyph_color(draft["hue"])))

    _grad, _glyph = _preview_bits()
    preview = ft.Container(width=46, height=46, border_radius=12, alignment=ft.alignment.center,
                           gradient=_grad, content=_glyph)

    def refresh_preview():
        preview.gradient, preview.content = _preview_bits()
        if preview.page:
            preview.update()

    name_in = _text_input(draft["name"], "Например, Visual Studio Code")
    path_in = _text_input(draft["path"], "Путь к файлу приложения")
    sub_in = _text_input(draft["sub"], "Короткое описание (необязательно)")

    def on_name(e):
        draft["name"] = e.control.value
        refresh_preview()
    name_in.on_change = on_name

    def on_path(e):
        draft["path"] = e.control.value
    path_in.on_change = on_path

    def on_sub(e):
        draft["sub"] = e.control.value
    sub_in.on_change = on_sub

    cat_dd = ft.Dropdown(
        value=draft["category_id"], bgcolor=C.BG_1, border_color=C.LINE,
        focused_border_color=C.LINE_5, color=C.TEXT, text_size=13,
        options=[ft.dropdown.Option(key=c["id"], text=c["name"]) for c in cats],
        on_change=lambda e: draft.__setitem__("category_id", e.control.value),
    )

    def on_hue(e):
        draft["hue"] = int(e.control.value)
        refresh_preview()
    hue_slider = ft.Slider(min=0, max=359, value=draft["hue"], on_change=on_hue,
                           active_color="#ffffff", expand=True)

    # File picker (desktop). Added to page overlay.
    def on_pick(e: ft.FilePickerResultEvent):
        if e.files:
            f = e.files[0]
            draft["path"] = f.path or f.name
            path_in.value = draft["path"]
            path_in.update()
            if not draft["name"]:
                base = (f.name or "").rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
                if base:
                    draft["name"] = base[:1].upper() + base[1:]
                    name_in.value = draft["name"]
                    name_in.update()
                    refresh_preview()

    picker = ft.FilePicker(on_result=on_pick)
    if picker not in page.overlay:
        page.overlay.append(picker)
        page.update()

    def browse():
        picker.pick_files(dialog_title="Выберите приложение", allow_multiple=False)

    fav_sw = ft.Switch(value=draft["favorite"], scale=0.75, active_track_color="#f5f5f7",
                       active_color=C.BG_1, inactive_thumb_color=C.MUTED,
                       inactive_track_color="#2a2a30",
                       on_change=lambda e: draft.__setitem__("favorite", e.control.value))
    quick_sw = ft.Switch(value=draft["quick"], scale=0.75, active_track_color="#f5f5f7",
                         active_color=C.BG_1, inactive_thumb_color=C.MUTED,
                         inactive_track_color="#2a2a30",
                         on_change=lambda e: draft.__setitem__("quick", e.control.value))

    def check_row(title, hint, sw):
        return ft.Container(
            ft.Row([ft.Column([T(title, size=13, color=C.TEXT_2),
                               T(hint, size=11, color=C.MUTED_2)], spacing=1, expand=True, tight=True), sw],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(10, 0),
            border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

    def save():
        if not draft["name"].strip():
            app_ui._toast("Укажите название", error=True)
            return
        if not draft["path"].strip():
            app_ui._toast("Выберите файл приложения", error=True)
            return
        if is_edit:
            store.update_app(existing["id"], {k: draft[k] for k in
                             ("name", "path", "sub", "category_id", "hue", "favorite", "quick")})
        else:
            store.add_app(draft)
        page.close(dialog)
        app_ui._on_library_changed()
        app_ui._toast("Сохранено" if is_edit else "Приложение добавлено")

    def remove():
        store.remove_app(existing["id"])
        page.close(dialog)
        app_ui._on_library_changed()
        app_ui._toast("Удалено")

    body = ft.Column([
        T("Закрепите программу для быстрого запуска из Centurio.", size=12.5, color=C.MUTED_2),
        ft.Container(height=6),
        _field_label("Файл приложения"),
        ft.Row([path_in, _outline_btn("Обзор", ft.Icons.FOLDER_OPEN, browse)], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(height=6), _field_label("Название"), name_in,
        ft.Container(height=6), _field_label("Описание"), sub_in,
        ft.Container(height=6), _field_label("Категория"), cat_dd,
        ft.Container(height=6), _field_label("Цвет плитки"),
        ft.Row([preview, hue_slider], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        check_row("В избранное", "Показывать в разделе «Избранное»", fav_sw),
        check_row("Быстрый запуск", "Закрепить сверху и назначить горячую клавишу", quick_sw),
    ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO, width=460)

    actions = []
    if is_edit:
        actions.append(ft.Container(T("Удалить", size=12.5, weight=ft.FontWeight.W_600, color="#e88"),
                                    height=40, padding=ft.padding.symmetric(0, 14),
                                    border=ft.border.all(1, "#5a2a2a"), border_radius=9,
                                    on_click=lambda e: remove(), alignment=ft.alignment.center))
    actions += [ft.Container(expand=True),
                _outline_btn("Отмена", None, lambda: page.close(dialog)),
                _primary_btn("Сохранить" if is_edit else "Добавить", save)]

    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=T("Изменить приложение" if is_edit else "Добавить приложение",
                      size=18, weight=ft.FontWeight.BOLD, color=C.TEXT),
        content=body,
        actions=[ft.Row(actions, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)],
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    page.open(dialog)


def open_categories_dialog(app_ui):
    page = app_ui.page
    store = app_ui.store
    list_col = ft.Column(spacing=8, tight=True)

    def rebuild():
        list_col.controls = []
        for c in app_ui.categories():
            count = sum(1 for a in store.state()["apps"] if a.get("category_id") == c["id"])
            name_field = ft.TextField(
                value=c["name"], bgcolor="transparent", border=ft.InputBorder.NONE,
                color=C.TEXT, text_size=13, dense=True, content_padding=ft.padding.only(0, 0, 0, 0),
                on_blur=lambda e, cid=c["id"]: store.update_category(cid, {"name": e.control.value.strip() or "Категория"}),
                expand=True)
            list_col.controls.append(ft.Container(
                ft.Row([ft.Icon(cat_icon(c.get("icon")), size=16, color=C.MUTED),
                        name_field,
                        T(str(count), size=11, color=C.MUTED_2, font_family="monospace"),
                        ft.Container(ft.Icon(ft.Icons.DELETE_OUTLINE, size=15, color=C.MUTED_2),
                                     width=26, height=26, border_radius=7, alignment=ft.alignment.center,
                                     on_click=lambda e, cid=c["id"]: remove_cat(cid))],
                       spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(8, 12), border_radius=10, bgcolor=C.BG_1,
                border=ft.border.all(1, C.LINE)))
        if page.controls:
            page.update()

    def remove_cat(cid):
        store.remove_category(cid)
        rebuild()
        app_ui._on_library_changed()

    new_field = _text_input("", "Название категории")

    def add_cat():
        name = new_field.value.strip()
        if not name:
            return
        icon = CATEGORY_ICON_CHOICES[len(app_ui.categories()) % len(CATEGORY_ICON_CHOICES)]
        store.add_category(name, icon)
        new_field.value = ""
        new_field.update()
        rebuild()
        app_ui._on_library_changed()

    new_field.on_submit = lambda e: add_cat()
    rebuild()

    body = ft.Column([
        T("Группируйте приложения по смыслу — «Работа», «Игры», «Разработка».",
                size=12.5, color=C.MUTED_2),
        ft.Container(height=6), list_col, ft.Container(height=6),
        _field_label("Новая категория"),
        ft.Row([new_field, _outline_btn("Добавить", ft.Icons.ADD, add_cat)], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
    ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO, width=480)

    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=T("Категории", size=18, weight=ft.FontWeight.BOLD, color=C.TEXT),
        content=body,
        actions=[ft.Row([ft.Container(expand=True), _primary_btn("Готово", lambda: page.close(dialog))])],
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    page.open(dialog)


def open_settings_dialog(app_ui):
    page = app_ui.page
    store = app_ui.store
    s = store.state()["settings"]
    accents = ["#f5f5f7", "#4f7dff", "#3ecfaf", "#f0a020"]

    swatch_row = ft.Row(spacing=10)

    def set_accent(color):
        app_ui._set_setting("accent", color)
        build_swatches()
        swatch_row.update()

    def build_swatches():
        swatch_row.controls = []
        for col in accents:
            active = store.state()["settings"].get("accent") == col
            swatch_row.controls.append(ft.Container(
                width=34, height=34, border_radius=9, bgcolor=col,
                border=ft.border.all(2, "#ffffff" if active else "transparent"),
                on_click=lambda e, c=col: set_accent(c)))
    build_swatches()

    tile_dd = ft.Dropdown(
        value=s.get("tile_size", "large"), bgcolor=C.BG_1, border_color=C.LINE,
        focused_border_color=C.LINE_5, color=C.TEXT, text_size=13,
        options=[ft.dropdown.Option(key="large", text="Крупные"),
                 ft.dropdown.Option(key="compact", text="Компактные")],
        on_change=lambda e: app_ui._set_setting("tile_size", e.control.value))

    def setting_switch(title, hint, key):
        sw = ft.Switch(value=store.state()["settings"].get(key, False), scale=0.75,
                       active_track_color="#f5f5f7", active_color=C.BG_1,
                       inactive_thumb_color=C.MUTED, inactive_track_color="#2a2a30",
                       on_change=lambda e, k=key: app_ui._set_setting(k, e.control.value))
        return ft.Container(
            ft.Row([ft.Column([T(title, size=13, color=C.TEXT_2),
                               T(hint, size=11, color=C.MUTED_2)], spacing=1, expand=True, tight=True), sw],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(10, 0), border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

    body = ft.Column([
        T("Centurio — ваш пульт управления приложениями.", size=12.5, color=C.MUTED_2),
        ft.Container(height=8), _field_label("Акцентный цвет"), swatch_row,
        ft.Container(height=12), _field_label("Размер плиток"), tile_dd,
        setting_switch("Показывать «Быстрый запуск»", "Ряд закреплённых приложений сверху", "show_quick_row"),
        setting_switch("Автозапуск с Windows", "Запускать Centurio при входе в систему", "autostart"),
        setting_switch("Сворачивать в трей", "Кнопка «свернуть» прячет окно в трей", "minimize_to_tray"),
        setting_switch("Закрывать в трей", "Крестик не закрывает приложение, а прячет его", "close_to_tray"),
        ft.Container(height=12),
        _outline_btn("Управление категориями", ft.Icons.FOLDER,
                     lambda: (page.close(dialog), open_categories_dialog(app_ui))),
    ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO, width=460)

    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=T("Настройки", size=18, weight=ft.FontWeight.BOLD, color=C.TEXT),
        content=body,
        actions=[ft.Row([ft.Container(expand=True), _primary_btn("Готово", lambda: page.close(dialog))])],
        shape=ft.RoundedRectangleBorder(radius=16),
    )
    page.open(dialog)
