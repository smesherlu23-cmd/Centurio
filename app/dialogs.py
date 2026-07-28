"""What used to be six modal windows.

Nothing here opens an ft.AlertDialog. Editing a category is a popover next to
its icon in the rail, adding programs and changing settings are screens inside
the library, and the first-run picker is a card over the window. Each builder
takes the UI object and returns a control; the UI decides where it goes.
"""
from __future__ import annotations

import time

import flet as ft

from . import colors as C
from . import queries
from .format import ICON_PACK, T, cat_icon, n_apps, plu_programs
from .hotkeys import format_accel

# Names for the four accents, in the order colors.ACCENT_CHOICES lists them.
ACCENT_NAMES = dict(zip(C.ACCENT_CHOICES, ("Белый", "Синий", "Бирюзовый", "Оранжевый")))


def _caps(text):
    return T(text, size=10.5, weight=ft.FontWeight.W_600, color=C.TEXT_4,
             style=ft.TextStyle(letter_spacing=0.85))


def _screen_header(title, subtitle, on_close, extra=None):
    right = [extra] if extra is not None else []
    right.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=19, color=C.TEXT_4),
                              width=32, height=32, alignment=ft.alignment.center,
                              on_click=lambda e: on_close(), tooltip="Закрыть"))
    return ft.Container(
        ft.Row([ft.Column([T(title, size=19, weight=ft.FontWeight.BOLD, color=C.TEXT_1),
                           T(subtitle, size=12.5, color=C.TEXT_4)],
                          spacing=4, expand=True, tight=True)] + right,
               spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(22, 18, 22, 14),
        border=ft.border.only(bottom=ft.BorderSide(1, C.BG_HOVER)))


# =========================================================================
# Поповер категории — вместо двух вложенных модальных окон
# =========================================================================
def build_category_popover(ui, cat):
    color = C.category_color(cat)

    name_field = ft.TextField(
        value=cat["name"], border=ft.InputBorder.NONE, filled=False, dense=True,
        text_size=13.5, color=C.TEXT_1, cursor_color=C.TEXT_1, expand=True,
        content_padding=ft.padding.only(0, 2, 0, 2),
        text_style=ft.TextStyle(weight=ft.FontWeight.W_600),
        on_blur=lambda e: ui.rename_category(cat["id"], e.control.value),
        on_submit=lambda e: ui.rename_category(cat["id"], e.control.value))

    header = ft.Row([
        ft.Container(ui.cat_glyph(cat, size=17), width=32, height=32, border_radius=10,
                     bgcolor=C.BG_HOVER, border=ft.border.all(1, C.BORDER_STRONG),
                     alignment=ft.alignment.center),
        ft.Container(name_field, expand=True,
                     border=ft.border.only(bottom=ft.BorderSide(1, C.BORDER))),
        ft.Container(ft.Icon(ft.Icons.CLOSE, size=17, color=C.TEXT_4),
                     on_click=lambda e: ui.close_popover()),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    swatches = []
    for hexval in C.CAT_PALETTE:
        picked = hexval.lower() == color.lower()
        swatches.append(ft.Container(
            width=26, height=26, border_radius=C.R_BTN, bgcolor=hexval,
            border=ft.border.all(2, C.ACCENT) if picked else None,
            on_click=lambda e, h=hexval: ui.set_category_color(cat["id"], h)))

    icon_query = ft.TextField(
        value=ui.view.icon_query, hint_text="Название иконки", border=ft.InputBorder.NONE,
        filled=False, dense=True, text_size=12.5, color=C.TEXT_1, cursor_color=C.TEXT_1,
        hint_style=ft.TextStyle(color=C.TEXT_4, size=12.5), expand=True,
        content_padding=ft.padding.symmetric(0, 0),
        on_submit=lambda e: ui.set_icon_query(e.control.value),
        on_blur=lambda e: ui.set_icon_query(e.control.value))

    query = (ui.view.icon_query or "").strip().lower()
    names = [n for n in ICON_PACK if not query or query in n]
    cells = [ft.Container(
        ft.Icon(cat_icon(name), size=16,
                color=color if name == cat.get("icon") else C.TEXT_2),
        width=32, height=32, border_radius=C.R_BTN, bgcolor=C.BG_WINDOW,
        border=ft.border.all(1, C.ACCENT if name == cat.get("icon") else C.BORDER),
        alignment=ft.alignment.center, tooltip=name,
        on_click=lambda e, n=name: ui.set_category_icon(cat["id"], n)) for name in names]
    if not cells:
        cells = [T("Ничего не нашлось", size=12, color=C.TEXT_4)]

    return ft.Container(
        ft.Column([
            header,
            _caps("ЦВЕТ"),
            ft.Row(swatches, spacing=8, wrap=True, run_spacing=8),
            _caps("ИКОНКА"),
            ft.Container(ft.Row([ft.Icon(ft.Icons.SEARCH, size=14, color=C.TEXT_4), icon_query],
                                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         height=C.H_FIELD, bgcolor=C.BG_WINDOW,
                         border=ft.border.all(1, C.BORDER), border_radius=C.R_BTN,
                         padding=ft.padding.symmetric(0, 10)),
            ft.Container(ft.Column([ft.Row(cells, spacing=6, wrap=True, run_spacing=6)],
                                   scroll=ft.ScrollMode.AUTO), height=110),
            ft.Container(
                ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=15, color=C.ERR_TEXT),
                        T("Удалить категорию", size=12, color=C.ERR_TEXT)],
                       spacing=6, tight=True),
                on_click=lambda e: ui.remove_category(cat["id"]),
                padding=ft.padding.only(0, 14, 0, 0), margin=ft.margin.only(top=12),
                border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER))),
        ], spacing=10, tight=True),
        width=C.POPOVER_W, bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER_STRONG),
        border_radius=C.R_CARD, padding=ft.padding.all(14),
        shadow=ft.BoxShadow(blur_radius=60, offset=ft.Offset(0, 24), color=C.SHADOW_CARD),
        animate_opacity=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT))


# =========================================================================
# «Найти и добавить» — экран, а не диалог
# =========================================================================
def build_add_screen(ui):
    scan = ui.scan_state()
    if scan["state"] == "running":
        body = _scanning_card(ui, scan)
    elif scan["state"] == "error":
        body = _error_card(ui, scan["errors"][0] if scan["errors"] else {})
    else:
        body = _found_list(ui, scan)
    return ft.Column([_add_header(ui), body, _add_footer(ui)], spacing=0, expand=True)


def _add_header(ui):
    groups = ui.found_groups() if ui.scan_state()["state"] == "done" else []
    total = sum(g["total"] for g in groups)
    fresh = sum(g["new"] for g in groups)
    if total:
        subtitle = f"{total} {plu_programs(total)} найдено, {fresh} из них новые"
    elif ui.scan_state()["state"] == "done":
        subtitle = "Установленных программ не нашлось"
    else:
        subtitle = "Смотрим, что установлено"

    toggle = ft.Container(
        ft.Row([T("Только новые", size=12.5, color=C.TEXT_1),
                ui._toggle(ui.view.only_new, lambda v: ui.toggle_only_new())],
               spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=C.H_FIELD, padding=ft.padding.symmetric(0, 12),
        border=ft.border.all(1, C.BORDER), border_radius=C.R_BTN,
        on_click=lambda e: ui.toggle_only_new())
    return _screen_header("Найти и добавить", subtitle, ui.back_to_grid, extra=toggle)


def _scanning_card(ui, scan):
    total = max(1, scan["total"])
    ratio = min(1.0, scan["done"] / total)
    elapsed = max(0, int(time.monotonic() - (scan["started"] or time.monotonic())))
    card = ft.Container(
        ft.Column([
            ft.Row([
                ft.Container(ft.Icon(ft.Icons.SEARCH, size=18, color=C.TEXT_3),
                             width=36, height=36, border_radius=11, bgcolor=C.BG_CARD,
                             border=ft.border.all(1, C.BORDER), alignment=ft.alignment.center),
                ft.Column([T("Смотрю, что установлено", size=14, weight=ft.FontWeight.W_600,
                             color=C.TEXT_1),
                           T(f"{scan['label'] or 'источники'} · {scan['done']} из {total}",
                             size=11, color=C.TEXT_4, font_family="monospace")],
                          spacing=2, expand=True, tight=True),
                ft.Container(T("Прервать", size=12, color=C.TEXT_4),
                             on_click=lambda e: ui.back_to_grid()),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                ft.Stack([
                    ft.Container(height=4, border_radius=2, bgcolor=C.BG_HOVER,
                                 left=0, right=0, top=0),
                    ft.Container(height=4, border_radius=2, bgcolor=C.ACCENT, left=0, top=0,
                                 width=max(6.0, 396 * ratio)),
                ], height=4), margin=ft.margin.only(top=16)),
            ft.Row([T(f"найдено {scan['found']}", size=10.5, color=C.TEXT_4,
                      font_family="monospace"),
                    ft.Container(expand=True),
                    T(f"{elapsed} сек", size=10.5, color=C.TEXT_4, font_family="monospace")]),
        ], spacing=8, tight=True),
        width=440, bgcolor=C.BG_WINDOW, border=ft.border.all(1, C.BORDER),
        border_radius=C.R_CARD, padding=ft.padding.all(22))
    return ft.Container(card, expand=True, padding=ft.padding.only(22, 22, 22, 22),
                        alignment=ft.alignment.top_left)


def _error_card(ui, error):
    label = error.get("label") or "Источник"
    card = ft.Container(
        ft.Row([
            ft.Container(ft.Icon(ft.Icons.ERROR_OUTLINE, size=18, color=C.ERR),
                         width=36, height=36, border_radius=11, bgcolor=C.ERR_BG,
                         border=ft.border.all(1, C.ERR_BORDER), alignment=ft.alignment.center),
            ft.Column([
                T(f"{label} не отдал список программ", size=14, weight=ft.FontWeight.W_600,
                  color=C.TEXT_1),
                T(error.get("error") or "Остальные источники прочитались — их видно в списке. "
                  "Программу можно добавить и вручную.", size=12.5, color=C.TEXT_3),
                ft.Container(ft.Row([
                    ui.outline_btn("Повторить", lambda: ui.start_scan(force=True)),
                    ui.outline_btn("Выбрать файл", ui.pick_file),
                    ft.Container(T("Пропустить", size=12.5, color=C.TEXT_4),
                                 height=C.H_FIELD, padding=ft.padding.symmetric(0, 12),
                                 alignment=ft.alignment.center,
                                 on_click=lambda e: ui.dismiss_scan_errors()),
                ], spacing=8), padding=ft.padding.only(0, 6, 0, 0)),
            ], spacing=6, expand=True, tight=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
        width=440, bgcolor=C.BG_WINDOW, border=ft.border.all(1, C.ERR_BORDER),
        border_radius=C.R_CARD, padding=ft.padding.all(22))
    return ft.Container(card, expand=True, padding=ft.padding.all(22),
                        alignment=ft.alignment.top_left)


def _found_list(ui, scan):
    groups = ui.found_groups()
    rows = []
    for err in scan.get("errors") or []:
        rows.append(_inline_error(ui, err))
    if not groups:
        rows.append(_add_empty(ui))
    for group in groups:
        rows.append(_add_group(ui, group))
    return ft.Container(ft.Column(rows, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
                        expand=True, padding=ft.padding.only(22, 12, 22, 16))


def _inline_error(ui, err):
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=C.ERR),
                T(f"{err.get('label') or 'Источник'} не прочитался — остальное в списке",
                  size=12.5, color=C.TEXT_1, expand=True),
                ui.link_btn("Повторить", lambda: ui.start_scan(force=True)),
                ft.Container(T("Скрыть", size=12.5, color=C.TEXT_4),
                             on_click=lambda e: ui.dismiss_scan_errors())],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=C.ERR_BG, border=ft.border.all(1, C.ERR_BORDER), border_radius=C.R_ROW,
        padding=ft.padding.symmetric(10, 14), margin=ft.margin.only(bottom=8))


def _add_empty(ui):
    only_new = ui.view.only_new
    return ft.Container(
        ft.Column([
            T("Новых программ не нашлось" if only_new else "Ничего не нашлось",
              size=16, weight=ft.FontWeight.BOLD, color=C.TEXT_1),
            T("Всё установленное уже в библиотеке." if only_new
              else "Автоматический поиск ничего не дал — программу можно указать файлом.",
              size=12.5, color=C.TEXT_3),
            ft.Container(ft.Row([
                ui.outline_btn("Показать все найденные" if only_new else "Повторить поиск",
                               ui.toggle_only_new if only_new
                               else (lambda: ui.start_scan(force=True)), height=C.H_BTN_LG),
                ui.outline_btn("Выбрать файл", ui.pick_file, ft.Icons.FOLDER_OPEN,
                               height=C.H_BTN_LG),
            ], spacing=8), padding=ft.padding.only(0, 6, 0, 0)),
        ], spacing=10, tight=True), width=440, padding=ft.padding.only(0, 30, 0, 0))


def _add_group(ui, group):
    keys = [r["key"] for r in group["rows"] if r["is_new"]]
    picked = [k for k in keys if k in ui.view.add_sel]
    if keys and len(picked) == len(keys):
        box = ft.Icons.CHECK_BOX
    elif picked:
        box = ft.Icons.INDETERMINATE_CHECK_BOX
    else:
        box = ft.Icons.CHECK_BOX_OUTLINE_BLANK

    head = [ft.Icon(box, size=17, color=C.TEXT_2),
            ft.Icon(cat_icon(group["icon"]), size=16, color=C.TEXT_4),
            T(group["label"], size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT_1)]
    if not ui.calm():
        head.append(T(f"{group['total']} · новых {group['new']}", size=11, color=C.TEXT_4))
    head.append(ft.Container(height=1, bgcolor=C.BG_HOVER, expand=True))

    rows = [ft.Container(ft.Row(head, spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         height=34, on_click=lambda e, g=group: ui.toggle_add_group(g))]
    rows += [_add_row(ui, row) for row in group["rows"]]
    return ft.Container(ft.Column(rows, spacing=3), padding=ft.padding.only(0, 0, 0, 10))


def _add_row(ui, row):
    checked = row["key"] in ui.view.add_sel
    if not row["is_new"]:
        box = ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=C.OK)
    else:
        box = ft.Icon(ft.Icons.CHECK_BOX if checked else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                      size=18, color=C.ACCENT if checked else C.TEXT_3)

    item = row["item"]
    controls = [box, ui.icon_slot(item, 30, C.R_BTN, glyph=16),
                ft.Column([
                    T(row["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT_1,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T(row["path"] if not ui.calm() else "", size=10.5, color=C.TEXT_4,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=1, expand=True, tight=True)]

    if row["is_new"]:
        cat_id = ui.add_category_for(row)
        cat = next((c for c in ui.categories() if c["id"] == cat_id), None)
        controls.append(ft.Container(
            ft.Row([ui.cat_glyph(cat, size=13),
                    T(cat["name"] if cat else "Без категории", size=11.5, color=C.TEXT_2),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=13, color=C.TEXT_4)],
                   spacing=6, tight=True),
            height=28, padding=ft.padding.symmetric(0, 10), bgcolor=C.BG_HOVER,
            border=ft.border.all(1, C.BORDER), border_radius=7,
            tooltip="Другая категория",
            on_click=lambda e, r=row: ui.cycle_add_category(r)))

    return ft.Container(
        ft.Row(controls, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=46, padding=ft.padding.symmetric(0, 12), border_radius=10,
        bgcolor=C.BG_CARD if checked else None,
        border=ft.border.all(1, C.BORDER_STRONG) if checked else None,
        opacity=0.45 if not row["is_new"] else 1,
        on_click=lambda e, r=row: ui.toggle_add_row(r))


def _add_footer(ui):
    count = len(ui.view.add_sel)
    return ft.Container(
        ft.Row([
            T(f"Выбрано {count}" if count else "Ничего не выбрано", size=13,
              weight=ft.FontWeight.W_600, color=C.TEXT_1),
            T("" if ui.calm() else "Категория предложена по источнику — "
              "можно поменять в строке", size=12, color=C.TEXT_4),
            ft.Container(expand=True),
            ui.outline_btn("Выбрать файл", ui.pick_file, ft.Icons.FOLDER_OPEN),
            ui.primary_btn(f"Добавить {count}" if count else "Добавить", ui.commit_add,
                           height=C.H_BTN_LG),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=60, bgcolor=C.BG_PANEL, padding=ft.padding.symmetric(0, 22),
        border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER)))


# =========================================================================
# Настройки — экран, а не диалог
# =========================================================================
def build_settings_screen(ui):
    left = ft.Column([_group("ВЫЗОВ", _call_rows(ui)),
                      _group("СПИСОК ПРОГРАММ", _library_rows(ui))],
                     spacing=22, tight=True, expand=True)
    right = ft.Column([_group("ВИД", _look_rows(ui)),
                       _group("ДАННЫЕ", _data_rows(ui))],
                      spacing=22, tight=True, expand=True)
    columns = ft.Row([left, ft.Container(width=1, bgcolor=C.BG_HOVER), right],
                     spacing=24, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    footer = ft.Container(
        ft.Row([ui.outline_btn("Показать первый запуск", ui.show_onboarding, ft.Icons.FLAG,
                               height=C.H_BTN)], tight=True),
        padding=ft.padding.only(0, 18, 0, 0), margin=ft.margin.only(top=4),
        border=ft.border.only(top=ft.BorderSide(1, C.BG_HOVER)))
    return ft.Column([
        _screen_header("Настройки", "Всё сохраняется само", ui.back_to_grid),
        ft.Container(ft.Column([columns, footer], spacing=22, scroll=ft.ScrollMode.AUTO,
                               expand=True),
                     expand=True, padding=ft.padding.only(22, 18, 22, 22)),
    ], spacing=0, expand=True)


def _group(title, rows):
    return ft.Column([_caps(title)] + rows, spacing=12, tight=True)


def _row(title, sub, control, ui=None, on_click=None):
    left = [T(title, size=13, color=C.TEXT_2)]
    if sub and not (ui and ui.calm()):
        left.append(T(sub, size=11, color=C.TEXT_4))
    return ft.Container(
        ft.Row([ft.Column(left, spacing=1, tight=True, expand=True), control],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=(lambda e: on_click()) if on_click else None)


def _switch_row(ui, title, sub, key):
    value = bool(ui.setting(key))
    return _row(title, sub, ui._toggle(value, lambda v, k=key: ui.set_setting(k, v)), ui=ui,
                on_click=lambda k=key, v=value: ui.set_setting(k, not v))


def _call_rows(ui):
    accel = format_accel(ui.setting("launch_hotkey"))
    hotkey_field = ft.Container(
        T(accel, size=11.5, color=C.TEXT_1, font_family="monospace"),
        height=C.H_FIELD, padding=ft.padding.symmetric(0, 12), bgcolor=C.BG_CARD,
        border=ft.border.all(1, C.BORDER_ACTIVE), border_radius=C.R_BTN,
        alignment=ft.alignment.center, tooltip="Другая комбинация",
        on_click=lambda e: ui.cycle_launch_hotkey())
    return [
        _row("Открыть «Запуск»", "Глобальная комбинация", hotkey_field, ui=ui),
        _switch_row(ui, "Прятать после запуска", "Окно уходит в трей само", "hide_after"),
        _switch_row(ui, "Запускать с Windows", "Свёрнутым в трей", "autostart"),
        _switch_row(ui, "Крестик сворачивает в трей", "Иначе Centurio завершается",
                    "close_to_tray"),
    ]


def _library_rows(ui):
    size = ui.icon_cache_size()
    megabytes = f"{size / (1024 * 1024):.0f} МБ" if size else "пусто"
    cache = ft.Row([T(megabytes, size=11, color=C.TEXT_4, font_family="monospace"),
                    ui.link_btn("Очистить", ui.clear_icon_cache)],
                   spacing=10, tight=True)
    return [
        _switch_row(ui, "Проверять новое раз в 15 минут",
                    "Только новые записи, без переиконивания", "auto_rescan"),
        _switch_row(ui, "Скачивать обложки игр", "Если нет в кэше Steam", "covers"),
        _row("Кэш иконок", None, cache, ui=ui),
        _row("Список программ", "Пересобрать прямо сейчас",
             ui.outline_btn("Проверить сейчас", lambda: ui.rescan(), ft.Icons.REFRESH), ui=ui),
    ]


def _look_rows(ui):
    current = ui.accent()
    swatches = ft.Row([
        ft.Container(width=28, height=28, border_radius=C.R_BTN, bgcolor=col,
                     border=ft.border.all(2, C.ACCENT) if col == current else None,
                     tooltip=ACCENT_NAMES.get(col),
                     on_click=lambda e, c=col: ui.set_setting("accent", c))
        for col in C.ACCENT_CHOICES], spacing=8, tight=True)

    def segment(label, value):
        active = ui.setting("tile_size", "large") == value
        return ft.Container(
            T(label, size=12, weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
              color=C.TEXT_1 if active else C.TEXT_3),
            height=26, padding=ft.padding.symmetric(0, 12), border_radius=6,
            bgcolor=C.BG_ACTIVE if active else None, alignment=ft.alignment.center,
            on_click=lambda e: ui.set_setting("tile_size", value))
    tiles = ft.Container(ft.Row([segment("Крупные", "large"), segment("Плотные", "compact")],
                                spacing=0),
                         bgcolor=C.BG_CARD, border=ft.border.all(1, C.BORDER),
                         border_radius=C.R_BTN, padding=ft.padding.all(2))
    return [
        _row("Акцент", None, swatches, ui=ui),
        _row("Плитки", None, tiles, ui=ui),
        _switch_row(ui, "Постеры вместо иконок у игр", "Вертикальные обложки в сетке",
                    "game_posters"),
        _switch_row(ui, "Подсказки клавиш", "Полоса снизу в режиме «Запуск»", "hints"),
        _switch_row(ui, "Спокойный вид", "Скрыть счётчики, пути и подсказки клавиш", "calm"),
    ]


def _data_rows(ui):
    return [
        _row("Копия библиотеки", "Рядом с файлом данных",
             ui.outline_btn("Сохранить", ui.backup, ft.Icons.BACKUP), ui=ui),
        _row("Файл библиотеки", str(ui.store.path),
             ui.link_btn("Показать в папке", ui.show_data_folder), ui=ui),
        _switch_row(ui, "Подробный лог", "Для отчёта о проблеме — нужен перезапуск",
                    "debug_log"),
    ]


# =========================================================================
# Первый запуск
# =========================================================================
def build_onboarding(ui):
    items = ui.onboarding_items()
    scanning = ui.scan_state()["state"] == "running" and not items

    rows = []
    for suggestion in items:
        app = suggestion["app"]
        key = (app.get("path") or "").lower()
        checked = key in ui.view.onboarding_sel
        rows.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.CHECK_BOX if checked else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                        size=18, color=C.ACCENT if checked else C.TEXT_3),
                ui.icon_slot(app, 28, C.R_BTN, glyph=15),
                T(app.get("name") or "", size=13, color=C.TEXT_1, expand=True, max_lines=1,
                  overflow=ft.TextOverflow.ELLIPSIS),
                T(suggestion["hint"], size=11.5, color=C.TEXT_4),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=44, padding=ft.padding.symmetric(0, 10), border_radius=10,
            bgcolor=C.BG_CARD if checked else None,
            border=ft.border.all(1, C.BORDER_STRONG) if checked else None,
            on_click=lambda e, k=key: ui.toggle_onboarding(k)))

    if scanning:
        rows = [ft.Container(ft.Row([ft.ProgressRing(width=15, height=15, stroke_width=2,
                                                     color=C.TEXT_3),
                                     T("Смотрю, что установлено…", size=12.5, color=C.TEXT_3)],
                                    spacing=10, tight=True),
                             padding=ft.padding.symmetric(18, 0))]
    elif not rows:
        rows = [ft.Container(T("Ничего подходящего не нашлось — добавьте программы вручную.",
                               size=12.5, color=C.TEXT_3),
                             padding=ft.padding.symmetric(18, 0))]

    picked = len(ui.view.onboarding_sel)
    card = ft.Container(
        ft.Column([
            T("Отметьте, чем пользуетесь каждый день", size=18, weight=ft.FontWeight.BOLD,
              color=C.TEXT_1),
            T("Это всё, что нужно для начала — остальные программы можно добавить когда угодно.",
              size=12.5, color=C.TEXT_3),
            ft.Container(ft.Column(rows, spacing=2, tight=True),
                         padding=ft.padding.only(0, 4, 0, 0)),
            ft.Row([T(f"Отмечено {picked} из {len(items)}" if items else "", size=12,
                      color=C.TEXT_4, expand=True),
                    ft.Container(T("Позже", size=12.5, color=C.TEXT_3),
                                 padding=ft.padding.symmetric(9, 12),
                                 on_click=lambda e: ui.close_onboarding()),
                    ui.primary_btn("Добавить и начать", ui.commit_onboarding_selection,
                                   height=C.H_BTN_LG)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=14, tight=True),
        width=520, bgcolor=C.BG_WINDOW, border=ft.border.all(1, C.BORDER_SLOT),
        border_radius=C.R_WINDOW, padding=ft.padding.all(24),
        shadow=ft.BoxShadow(blur_radius=100, offset=ft.Offset(0, 40), color=C.SHADOW_CARD))
    return ft.Container(card, bgcolor=C.OVERLAY, alignment=ft.alignment.center,
                        expand=True)


# =========================================================================
# Мини-лаунчер в трее
# =========================================================================
def tray_items(store) -> list[dict]:
    """The five pinned programs the tray menu launches without opening a window."""
    from .hotkeys import quick_accels
    apps = store.state()["apps"]
    accels = quick_accels(apps)
    out = []
    for app in queries.quick_apps(apps)[:5]:
        accel = accels.get(app["id"])
        out.append({"id": app["id"], "name": app["name"],
                    "label": f"{app['name']}   {accel}" if accel else app["name"]})
    return out


def library_summary(store) -> str:
    apps = store.state()["apps"]
    return n_apps(len(apps)) if apps else "библиотека пуста"


__all__ = ["build_category_popover", "build_add_screen", "build_settings_screen",
           "build_onboarding", "tray_items", "library_summary"]
