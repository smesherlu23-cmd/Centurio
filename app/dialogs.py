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


def confirm(app_ui, title, message, confirm_label, on_confirm, danger=True):
    """A small confirmation dialog (used before destructive actions)."""
    page = app_ui.page

    def do():
        page.close(dialog)
        on_confirm()

    confirm_btn = ft.Container(
        T(confirm_label, size=13, weight=ft.FontWeight.W_600, color="#fff" if danger else C.BG_1),
        height=40, padding=ft.padding.symmetric(0, 18),
        bgcolor=C.DANGER if danger else "#f5f5f7", border_radius=9,
        on_click=lambda e: do(), alignment=ft.alignment.center)
    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=T(title, size=17, weight=ft.FontWeight.BOLD, color=C.TEXT),
        content=ft.Container(T(message, size=13, color=C.MUTED), width=380),
        actions=[ft.Row([ft.Container(expand=True),
                         _outline_btn("Отмена", None, lambda: page.close(dialog)),
                         confirm_btn])],
        shape=ft.RoundedRectangleBorder(radius=16))
    page.open(dialog)


def _menu_item(icon, label, on_click, danger=False):
    color = "#e88" if danger else C.TEXT
    row = ft.Container(
        ft.Row([ft.Icon(icon, size=17, color="#e88" if danger else C.MUTED),
                T(label, size=13.5, color=color, weight=ft.FontWeight.W_500)],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.symmetric(10, 12), border_radius=9,
        on_click=lambda e: on_click())
    return row


def open_context_menu(app_ui, app):
    """Right-click menu for an app tile/row."""
    page = app_ui.page
    store = app_ui.store
    fav = app.get("favorite")
    quick = app.get("quick")

    def close_then(fn):
        def h():
            page.close(dialog)
            fn()
        return h

    def do_delete():
        confirm(app_ui, "Удалить приложение?",
                f"«{app['name']}» будет удалено из Centurio. Само приложение на диске не тронется.",
                "Удалить", lambda: (_remove(app_ui, app["id"])))

    items = [
        _menu_item(ft.Icons.PLAY_ARROW, "Открыть", close_then(lambda: app_ui._launch(app["id"]))),
        _menu_item(ft.Icons.STAR if fav else ft.Icons.STAR_BORDER,
                   "Убрать из избранного" if fav else "В избранное",
                   close_then(lambda: app_ui._toggle_fav(app["id"]))),
        _menu_item(ft.Icons.BOLT, "Убрать из быстрого запуска" if quick else "В быстрый запуск",
                   close_then(lambda: _toggle_quick(app_ui, app["id"]))),
        _menu_item(ft.Icons.FOLDER_OPEN, "Показать в папке",
                   close_then(lambda: app_ui._show_in_folder(app["id"]))),
        _menu_item(ft.Icons.EDIT_OUTLINED, "Изменить",
                   close_then(lambda: _open_detail_dialog(app_ui, store.get_app(app["id"]) or app))),
        ft.Divider(height=1, color=C.LINE_2),
        _menu_item(ft.Icons.DELETE_OUTLINE, "Удалить", close_then(do_delete), danger=True),
    ]
    for it in items:
        if isinstance(it, ft.Container):
            app_ui._hoverable(it, None, C.PANEL_2)

    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=ft.Row([app_ui._chip_visual(app, 30, 13, 8),
                      T(app["name"], size=15, weight=ft.FontWeight.BOLD, color=C.TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)], spacing=11),
        content=ft.Container(ft.Column(items, spacing=2, tight=True), width=300),
        shape=ft.RoundedRectangleBorder(radius=16))
    page.open(dialog)


def _remove(app_ui, app_id):
    app_ui.store.remove_app(app_id)
    app_ui._on_library_changed()
    app_ui._toast("Удалено")


def _toggle_quick(app_ui, app_id):
    a = app_ui.store.get_app(app_id)
    if a:
        app_ui.store.update_app(app_id, {"quick": not a.get("quick")})
    app_ui._on_library_changed()


def open_app_dialog(app_ui, existing=None):
    """Route: adding uses the installed-apps picker; editing uses the detail form."""
    if existing is None:
        open_add_picker(app_ui)
    else:
        _open_detail_dialog(app_ui, existing)


def open_add_picker(app_ui):
    """Add apps by picking from a list of already-installed applications.

    The list is discovered automatically (Start Menu / .desktop / .app). The
    user just clicks an app to add it — no naming or describing needed. A
    manual file picker remains available for anything not in the list.
    """
    import threading
    from pathlib import Path

    from .discovery import discover_apps, extract_icon

    page = app_ui.page
    store = app_ui.store
    cats = app_ui.categories()
    icon_cache = str(Path(store.path).parent / "icons")

    # Category is chosen explicitly by the user (not inferred from the current view).
    ui_state = {"category_id": cats[0]["id"] if cats else "work", "query": "", "apps": None}

    existing_paths = {(a.get("path") or "").lower() for a in store.state()["apps"]}

    cat_dd = ft.Dropdown(
        value=ui_state["category_id"], width=200, bgcolor=C.BG_1, border_color=C.LINE,
        focused_border_color=C.LINE_5, color=C.TEXT, text_size=13, dense=True,
        options=[ft.dropdown.Option(key=c["id"], text=c["name"]) for c in cats],
        on_change=lambda e: ui_state.__setitem__("category_id", e.control.value))

    search = _text_input("", "Поиск среди установленных приложений…")
    status = T("Сканирование установленных приложений…", size=12, color=C.MUTED_2, font_family="monospace")
    list_view = ft.ListView(spacing=6, expand=True)

    def add_app(a):
        path = a.get("path") or ""
        if path.lower() in existing_paths:
            return
        store.add_app({"name": a["name"], "path": path, "icon": a.get("icon"),
                       "icon_fit": a.get("icon_fit"), "sub": a.get("sub", ""),
                       "category_id": ui_state["category_id"]})
        existing_paths.add(path.lower())
        app_ui._on_library_changed()
        app_ui._toast(f"Добавлено: {a['name']}")
        render()

    def make_row(a):
        added = (a.get("path") or "").lower() in existing_paths
        icon = app_ui._chip_visual(a, 34, 15, 9)
        trailing = ft.Icon(ft.Icons.CHECK_CIRCLE if added else ft.Icons.ADD_CIRCLE_OUTLINE,
                           size=20, color=C.GREEN if added else C.MUTED)
        row = ft.Container(
            ft.Row([icon,
                    ft.Column([T(a["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
                                 max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                               T(a.get("path") or "", size=10.5, color=C.MUTED_2, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS, font_family="monospace")],
                              spacing=1, expand=True, tight=True),
                    trailing], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(8, 12), border_radius=10, bgcolor=C.BG_1,
            border=ft.border.all(1, C.LINE), opacity=0.5 if added else 1,
            on_click=None if added else (lambda e, ap=a: add_app(ap)))
        if not added:
            app_ui._hoverable(row, C.BG_1, C.PANEL_2)
        return row

    def render():
        list_view.controls = []
        apps = ui_state["apps"]
        if apps is None:
            list_view.controls.append(ft.Row(
                [ft.ProgressRing(width=15, height=15, stroke_width=2, color=C.MUTED),
                 T("Сканирование…", size=12.5, color=C.MUTED_2)], spacing=10))
        else:
            q = ui_state["query"].strip().lower()
            shown = [a for a in apps if q in a["name"].lower() or q in (a.get("path") or "").lower()]
            if not shown:
                list_view.controls.append(ft.Container(
                    T("Установленные приложения не найдены — добавьте файл вручную." if not apps
                      else "Ничего не найдено.", size=12.5, color=C.MUTED_2),
                    padding=ft.padding.symmetric(16, 4)))
            for a in shown:
                list_view.controls.append(make_row(a))
        if list_view.page:
            list_view.update()

    def on_query(e):
        ui_state["query"] = e.control.value
        render()
    search.on_change = on_query

    def load():
        found = discover_apps(icon_cache)
        ui_state["apps"] = found
        status.value = (f"Найдено приложений: {len(found)}" if found
                        else "Ничего не нашлось автоматически — используйте «Указать файл вручную».")
        if status.page:
            status.update()
        render()

    # Manual fallback — still no naming: the file name becomes the app name.
    def on_pick(e):
        if not e.files:
            return
        f = e.files[0]
        path = f.path or f.name
        base = (f.name or "").rsplit(".", 1)[0].replace("-", " ").replace("_", " ").strip()
        name = (base[:1].upper() + base[1:]) if base else "Приложение"
        icon = extract_icon(path, icon_cache) if path else None
        store.add_app({"name": name, "path": path, "icon": icon,
                       "category_id": ui_state["category_id"]})
        existing_paths.add((path or "").lower())
        app_ui._on_library_changed()
        app_ui._toast(f"Добавлено: {name}")
        render()

    picker = getattr(app_ui, "_file_picker", None)
    if picker is None:
        picker = ft.FilePicker()
        app_ui._file_picker = picker
        page.overlay.append(picker)
        page.update()
    picker.on_result = on_pick

    def browse():
        picker.pick_files(dialog_title="Выберите приложение", allow_multiple=False)

    body = ft.Column([
        T("Выберите приложения из установленных — название подставится автоматически.",
          size=12.5, color=C.MUTED_2),
        ft.Row([T("Добавить в категорию", size=12.5, color=C.TEXT_2), cat_dd],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        search,
        ft.Container(list_view, height=300, bgcolor=C.BG_0, border_radius=10,
                     border=ft.border.all(1, C.LINE_2), padding=ft.padding.all(8)),
        status,
    ], spacing=10, tight=True, width=520)

    dialog = ft.AlertDialog(
        modal=True, bgcolor=C.PANEL,
        title=T("Добавить приложение", size=18, weight=ft.FontWeight.BOLD, color=C.TEXT),
        content=body,
        actions=[ft.Row([_outline_btn("Указать файл вручную", ft.Icons.FOLDER_OPEN, browse),
                         ft.Container(expand=True),
                         _primary_btn("Готово", lambda: page.close(dialog))])],
        shape=ft.RoundedRectangleBorder(radius=16))
    page.open(dialog)
    render()
    threading.Thread(target=load, daemon=True).start()


def _open_detail_dialog(app_ui, existing):
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
    hotkey_in = _text_input(draft.get("hotkey") or "", "Например, Ctrl+Shift+G")

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

    def on_hotkey(e):
        draft["hotkey"] = e.control.value.strip() or None
    hotkey_in.on_change = on_hotkey

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

    # Reuse a single FilePicker per session (don't stack a new one in the
    # overlay every time the dialog opens).
    picker = getattr(app_ui, "_file_picker", None)
    if picker is None:
        picker = ft.FilePicker()
        app_ui._file_picker = picker
        page.overlay.append(picker)
        page.update()
    picker.on_result = on_pick

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
            store.update_app(existing["id"], {k: draft.get(k) for k in
                             ("name", "path", "sub", "category_id", "hue", "favorite", "quick", "hotkey")})
        else:
            store.add_app(draft)
        page.close(dialog)
        app_ui._on_library_changed()
        app_ui._toast("Сохранено" if is_edit else "Приложение добавлено")

    def remove():
        def do():
            store.remove_app(existing["id"])
            page.close(dialog)
            app_ui._on_library_changed()
            app_ui._toast("Удалено")
        confirm(app_ui, "Удалить приложение?",
                f"«{existing['name']}» будет удалено из Centurio. Само приложение на диске не тронется.",
                "Удалить", do)

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
        ft.Container(height=6), _field_label("Горячая клавиша (глобальная)"), hotkey_in,
        check_row("В избранное", "Показывать в разделе «Избранное»", fav_sw),
        check_row("Быстрый запуск", "Закрепить сверху; без своей клавиши — Ctrl+1…9", quick_sw),
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
        cat = next((c for c in app_ui.categories() if c["id"] == cid), None)
        cnt = sum(1 for a in store.state()["apps"] if a.get("category_id") == cid)
        msg = (f"Категория «{cat['name'] if cat else ''}» будет удалена."
               + (f" {cnt} приложений будут перенесены в первую категорию." if cnt else ""))

        def do():
            store.remove_category(cid)
            rebuild()
            app_ui._on_library_changed()
        confirm(app_ui, "Удалить категорию?", msg, "Удалить", do)

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
