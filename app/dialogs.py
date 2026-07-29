"""Экраны и поповеры — то, что раньше было модальными окнами.

Ни один builder здесь не открывает `ft.AlertDialog`. «Найти и добавить»,
«Настройки» и «Разбор» — экраны внутри окна библиотеки; цвет и иконка
категории — поповер у её значка; первый запуск — карточка поверх окна.

Каждая функция принимает объект интерфейса и возвращает контрол; куда его
положить, решает `ui.py`.
"""
from __future__ import annotations

import flet as ft

from . import colors as C
from . import queries
from .format import ICON_PACK, T, cat_icon, plu_apps, plu_programs
from .hotkeys import format_accel

ACCENT_NAMES = dict(zip(C.ACCENT_CHOICES, ("Белый", "Синий", "Бирюзовый", "Оранжевый")))


def _caps(text):
    return T(text, size=10.5, weight=ft.FontWeight.W_600, color=C.MUTED_2,
             style=ft.TextStyle(letter_spacing=0.85))


def _screen_header(title, subtitle, on_close, extra=None):
    right = list(extra or [])
    right.append(ft.Container(ft.Icon(ft.Icons.CLOSE, size=20, color=C.MUTED_2),
                              width=32, height=32, alignment=ft.alignment.center,
                              on_click=lambda e: on_close(), tooltip="Закрыть"))
    lines = [T(title, size=19, weight=ft.FontWeight.BOLD, color=C.TEXT)]
    if subtitle:
        lines.append(T(subtitle, size=12.5, color=C.MUTED_2))
    return ft.Container(
        ft.Row([ft.Column(lines, spacing=4, expand=True, tight=True)] + right,
               spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(24, 20, 24, 16),
        border=ft.border.only(bottom=ft.BorderSide(1, C.LINE_2)))


def _field(value, hint, on_change=None, on_submit=None, mono=False, size=13):
    return ft.TextField(
        value=value or "", hint_text=hint, border=ft.InputBorder.NONE, filled=False,
        dense=True, text_size=size, color=C.TEXT, cursor_color=C.TEXT, expand=True,
        hint_style=ft.TextStyle(color=C.MUTED_2, size=size),
        text_style=ft.TextStyle(font_family="mono") if mono else None,
        content_padding=ft.padding.symmetric(0, 0),
        on_change=on_change, on_submit=on_submit)


# =========================================================================
# 04 · Найти и добавить
# =========================================================================
def build_add_screen(ui):
    if ui.scanning():
        body = _scanning(ui)
    else:
        body = _found_list(ui)
    return ft.Column([_add_header(ui), _add_search(ui), body, _add_footer(ui)],
                     spacing=0, expand=True)


def _add_header(ui):
    groups = [] if ui.scanning() else ui.found_groups()
    total = sum(g["total"] for g in groups)
    fresh = sum(g["new"] for g in groups)
    if ui.scanning():
        subtitle = "Смотрим, что установлено"
    elif total:
        subtitle = f"{total} {plu_programs(total)} на компьютере, {fresh} из них новые"
    else:
        subtitle = "Установленных программ не нашлось"

    rescan = ft.Container(
        ft.Row([ui.spinner(15) if ui.scanning()
                else ft.Icon(ft.Icons.REFRESH, size=15, color=C.MUTED),
                T("Сканировать снова", size=12.5, color=C.TEXT)],
               spacing=7, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=34, padding=ft.padding.symmetric(0, 12),
        border=ft.border.all(1, C.LINE_4), border_radius=8,
        alignment=ft.alignment.center,
        on_click=None if ui.scanning() else (lambda e: ui.start_scan(force=True)))
    return _screen_header("Найти и добавить", subtitle if not ui.calm() else None,
                          ui.back_to_grid, extra=[rescan])


def _add_search(ui):
    """Поиск по найденному и поле для пути — две дороги к одному списку."""
    if ui.scanning():
        return ft.Container(height=0)
    search = ft.Container(
        ft.Row([ft.Icon(ft.Icons.SEARCH, size=15, color=C.MUTED_2),
                _field(ui.view.add_query, "Название программы",
                       on_change=lambda e: ui.set_add_query(e.control.value))],
               spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=36, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE), border_radius=9,
        padding=ft.padding.symmetric(0, 12), expand=True)
    only_new = ft.Container(
        ft.Row([T("Только новые", size=12.5, color=C.TEXT),
                ui._toggle(ui.view.only_new, lambda v: ui.toggle_only_new())],
               spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=36, padding=ft.padding.symmetric(0, 12),
        border=ft.border.all(1, C.LINE), border_radius=9,
        on_click=lambda e: ui.toggle_only_new())

    path_field = ft.Container(
        ft.Row([ft.Icon(ft.Icons.LINK, size=15, color=C.MUTED_2),
                _field(ui.view.manual_path,
                       r"Или вставьте путь: C:\Program Files\…\app.exe",
                       on_change=lambda e: ui.set_manual_path(e.control.value),
                       on_submit=lambda e: ui.add_manual_path(e.control.value),
                       mono=True, size=11.5)],
               spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=36, bgcolor=C.SET_BG, border=ft.border.all(1, C.LINE_4), border_radius=9,
        padding=ft.padding.symmetric(0, 12), expand=True)

    return ft.Column([
        ft.Container(ft.Row([search, only_new], spacing=10),
                     padding=ft.padding.only(24, 14, 24, 6)),
        ft.Container(ft.Row([path_field,
                             ui.outline_btn("Обзор", ui.pick_file, ft.Icons.FOLDER_OPEN),
                             ui.outline_btn("Добавить путь", ui.add_manual_path)],
                            spacing=10),
                     padding=ft.padding.only(24, 0, 24, 12)),
    ], spacing=0, tight=True)


def _scanning(ui):
    """05 · Сканирование: кружок и слово, больше ничего."""
    return ft.Container(
        ft.Column([ui.spinner(38), T("Сканирование", size=15, color=C.TEXT_2)],
                  spacing=22, tight=True,
                  horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                  alignment=ft.MainAxisAlignment.CENTER),
        expand=True, alignment=ft.alignment.center)


def _found_list(ui):
    groups = ui.found_groups()
    rows = [_inline_error(ui, err) for err in ui.scan_errors()]
    if not groups:
        rows.append(_add_empty(ui))
    for group in groups:
        rows.append(_add_group(ui, group))
    return ft.Container(ft.Column(rows, spacing=2, scroll=ft.ScrollMode.AUTO, expand=True),
                        expand=True, padding=ft.padding.only(24, 0, 24, 8))


def _inline_error(ui, err):
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=C.DANGER),
                ft.Column([T(f"{err.get('label') or 'Источник'} не отдал список программ",
                             size=13, color=C.TEXT),
                           T("Остальные источники прочитались", size=11.5, color=C.MUTED)],
                          spacing=3, expand=True, tight=True),
                ui.link_btn("Повторить", lambda: ui.start_scan(force=True)),
                ft.Container(T("Скрыть", size=12.5, color=C.MUTED_2),
                             on_click=lambda e: ui.dismiss_scan_errors())],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=C.ERR_BG, border=ft.border.all(1, C.ERR_BORDER), border_radius=12,
        padding=ft.padding.symmetric(13, 16), margin=ft.margin.only(bottom=8))


def _add_empty(ui):
    only_new = ui.view.only_new
    return ft.Container(
        ft.Column([
            T("Новых программ не нашлось" if only_new else "Ничего не нашлось",
              size=16, weight=ft.FontWeight.BOLD, color=C.TEXT),
            T("Всё установленное уже в библиотеке." if only_new
              else "Автоматический поиск ничего не дал — программу можно указать файлом "
                   "или вставить путь выше.", size=12.5, color=C.MUTED),
            ft.Container(ft.Row([
                ui.outline_btn("Показать все найденные" if only_new else "Повторить поиск",
                               ui.toggle_only_new if only_new
                               else (lambda: ui.start_scan(force=True))),
                ui.outline_btn("Выбрать файл", ui.pick_file, ft.Icons.FOLDER_OPEN),
            ], spacing=8), padding=ft.padding.only(0, 6, 0, 0)),
        ], spacing=10, tight=True), width=460, padding=ft.padding.only(0, 30, 0, 0))


def _add_group(ui, group):
    keys = [r["key"] for r in group["rows"] if r["is_new"]]
    picked = [k for k in keys if k in ui.view.add_sel]
    if keys and len(picked) == len(keys):
        box = ft.Icons.CHECK_BOX
        box_color = C.ACCENT
    elif picked:
        box = ft.Icons.INDETERMINATE_CHECK_BOX
        box_color = C.MUTED
    else:
        box = ft.Icons.CHECK_BOX_OUTLINE_BLANK
        box_color = C.MUTED

    head = [ft.Icon(box, size=18, color=box_color),
            ft.Icon(cat_icon(group["icon"]), size=16, color=C.MUTED_2),
            T(group["label"], size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT)]
    if not ui.calm():
        head.append(T(f"{group['total']} · новых {group['new']}", size=11, color=C.MUTED_2))
    head.append(ft.Container(height=1, bgcolor=C.LINE_2, expand=True))

    rows = [ft.Container(ft.Row(head, spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         height=36, on_click=lambda e, g=group: ui.toggle_add_group(g))]
    rows += [_add_row(ui, row) for row in group["rows"]]
    return ft.Container(ft.Column(rows, spacing=2), padding=ft.padding.only(0, 0, 0, 8))


def _add_row(ui, row):
    checked = row["key"] in ui.view.add_sel
    if not row["is_new"]:
        box = ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=C.GREEN)
    else:
        box = ft.Icon(ft.Icons.CHECK_BOX if checked else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                      size=18, color=C.ACCENT if checked else C.MUTED)

    item = row["item"]
    sub = row["path"]
    if not row["is_new"]:
        cat = next((c for c in ui.categories()
                    if any(a.get("category_id") == c["id"] and
                           (a.get("path") or "").lower() == row["key"] for a in ui.apps())), None)
        sub = "уже в библиотеке" + (f" · {cat['name']}" if cat else "")
    elif item.get("sub"):
        sub = f"{item['sub']} · обложка найдена" if item.get("poster") else item["sub"]

    controls = [box, ui.icon_slot(item, 30, 8, glyph=16),
                ft.Column([
                    T(row["name"], size=13, weight=ft.FontWeight.W_600, color=C.TEXT,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    T("" if ui.calm() else sub, size=10.5, color=C.MUTED_2, max_lines=1,
                      overflow=ft.TextOverflow.ELLIPSIS,
                      font_family="monospace" if sub is row["path"] else None),
                ], spacing=1, expand=True, tight=True)]

    if row["is_new"]:
        cat_id = ui.add_category_for(row)
        cat = next((c for c in ui.categories() if c["id"] == cat_id), None)
        controls.append(ft.Container(
            ft.Row([ui._cat_glyph(cat, size=13) if cat
                    else T("Категория", size=11.5, color=C.MUTED_2),
                    T(cat["name"], size=11.5, color=C.TEXT_2) if cat else ft.Container(),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=13, color=C.MUTED_2)],
                   spacing=6, tight=True),
            height=28, padding=ft.padding.symmetric(0, 10),
            bgcolor=C.PANEL_3 if cat else None,
            border=ft.border.all(1, C.LINE if cat else C.LINE_4), border_radius=7,
            tooltip="Другая категория",
            on_click=lambda e, r=row: ui.cycle_add_category(r)))

    return ft.Container(
        ft.Row(controls, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=46, padding=ft.padding.symmetric(0, 12), border_radius=10,
        bgcolor=C.PANEL if checked else None,
        border=ft.border.all(1, C.LINE_5) if checked else None,
        opacity=0.45 if not row["is_new"] else 1,
        on_click=lambda e, r=row: ui.toggle_add_row(r))


def _add_footer(ui):
    count = len(ui.view.add_sel)
    left = [T(f"Выбрано {count}" if count else "Ничего не выбрано", size=13,
              weight=ft.FontWeight.W_600, color=C.TEXT)]
    if not ui.calm():
        left.append(T("Категория предложена по источнику — поменяйте в строке",
                      size=12, color=C.MUTED_2))
    add_label = f"Добавить {count}" if count else "Добавить"
    add_row = [T(add_label, size=13, weight=ft.FontWeight.W_600, color=C.ON_ACCENT)]
    if not ui.calm():
        add_row.append(T("Ctrl+Enter", size=10.5, color=C.ON_ACCENT, opacity=0.55,
                         font_family="monospace"))
    return ft.Container(
        ft.Row(left + [
            ft.Container(expand=True),
            ui.outline_btn("Отложить в разбор", ui.defer_add, ft.Icons.INBOX),
            ft.Container(ft.Row(add_row, spacing=8, tight=True), height=36,
                         padding=ft.padding.symmetric(0, 16), bgcolor=ui._accent(),
                         border_radius=9, alignment=ft.alignment.center,
                         on_click=lambda e: ui.commit_add()),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=64, bgcolor=C.BG_2, padding=ft.padding.symmetric(0, 24),
        border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))


# =========================================================================
# 06–07 · Разбор
# =========================================================================
def build_triage_screen(ui):
    queue = ui.inbox()
    if not queue:
        return _triage_done(ui)

    item = queue[0]
    total = len(queue)
    done = getattr(ui, "_triage_done_count", 0)
    picks = queries.suggest_categories(item, ui.categories())

    head = ft.Container(
        ft.Row([ft.Column([
            T("Разбор", size=16, weight=ft.FontWeight.BOLD, color=C.TEXT),
            T("" if ui.calm() else f"Осталось {total} · разобрано {done}",
              size=12, color=C.TEXT_DIM),
        ], spacing=4, tight=True, expand=True),
            ft.Container(T("Отложить всё", size=12.5, color=C.MUTED_2),
                         on_click=lambda e: ui.triage_defer_all())],
            spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(26, 22, 26, 0))

    bar = ft.Container(
        ft.Row([ft.Container(height=3, border_radius=2, bgcolor=C.ACCENT, expand=max(done, 0) or 1
                             if done else 1, visible=bool(done)),
                ft.Container(height=3, border_radius=2, bgcolor=C.PROGRESS_TRACK, expand=total)],
               spacing=3), padding=ft.padding.only(26, 16, 26, 0))

    chips = []
    for index, cat in enumerate(picks):
        first = index == 0
        row = [T(str(index + 1), size=11, weight=ft.FontWeight.BOLD,
                 color=C.MUTED if first else C.TEXT_FAINT, font_family="monospace"),
               ui._cat_glyph(cat, size=17, color=C.category_color(cat) if first else C.TEXT_2),
               T(cat["name"], size=13.5, weight=ft.FontWeight.W_600 if first else None,
                 color=C.TEXT if first else C.TEXT_2)]
        if first and not ui.calm():
            row.append(T("похоже", size=11, color=C.MUTED_2))
        chips.append(ft.Container(
            ft.Row(row, spacing=9, tight=True,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=44, padding=ft.padding.symmetric(0, 16), border_radius=12,
            bgcolor=C.TRIAGE_PICK_BG if first else None,
            border=ft.border.all(1, C.TRIAGE_PICK_BORDER if first else C.TRIAGE_CHIP_BORDER),
            on_click=lambda e, cid=cat["id"], iid=item["id"]: ui.triage_place(iid, cid)))

    source = queries.SOURCES.get(item.get("source") or "", {}).get("label", "")
    card = ft.Column([
        ft.Container(ui.icon_slot(item, 92, 24, glyph=42, border=C.TRIAGE_SLOT_BORDER),
                     alignment=ft.alignment.center),
        ft.Column([
            T(item["name"], size=22, weight=ft.FontWeight.BOLD, color=C.TEXT,
              text_align=ft.TextAlign.CENTER),
            T("" if ui.calm() else source, size=12, color=C.TEXT_DIM),
        ], spacing=7, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(ft.Row(chips, spacing=9, wrap=True, run_spacing=9,
                            alignment=ft.MainAxisAlignment.CENTER),
                     padding=ft.padding.only(0, 2, 0, 0)),
    ], spacing=20, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER)

    def hint(key, label):
        return ft.Row([ft.Container(T(key, size=10.5, color=C.MUTED, font_family="monospace"),
                                    bgcolor=C.PANEL_2, border=ft.border.all(1, C.LINE),
                                    border_radius=4, padding=ft.padding.symmetric(2, 6)),
                       T(label, size=11.5, color=C.MUTED_2)], spacing=7, tight=True)

    footer = ft.Container(
        ft.Row([hint("1–4", "положить в категорию"), hint("Enter", "взять предложенную"),
                hint("→", "пропустить"), ft.Container(expand=True),
                ft.Container(hint("Del", "не нужно"),
                             on_click=lambda e, iid=item["id"]: ui.triage_drop(iid))],
               spacing=20, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=52, bgcolor=C.BG_2, padding=ft.padding.symmetric(0, 26),
        border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)),
        visible=not ui.calm())

    return ft.Column([head, bar,
                      ft.Container(card, expand=True, padding=ft.padding.symmetric(0, 26),
                                   alignment=ft.alignment.center),
                      footer], spacing=0, expand=True)


def _triage_done(ui):
    done = getattr(ui, "_triage_done_count", 0)
    text = (f"{done} {plu_programs(done)} лежат по местам. " if done else "")
    return ft.Container(
        ft.Column([
            ft.Container(ft.Icon(ft.Icons.CHECK, size=28, color=C.GREEN),
                         width=64, height=64, border_radius=20, bgcolor=C.DONE_BG,
                         border=ft.border.all(1, C.DONE_BORDER),
                         alignment=ft.alignment.center),
            T("Всё разобрано", size=18, weight=ft.FontWeight.BOLD, color=C.TEXT),
            T(text + "Новое появится здесь само — заходить специально не нужно.",
              size=13, color=C.MUTED_2, width=300, text_align=ft.TextAlign.CENTER),
            ft.Container(ft.Row([
                ui.primary_btn("К библиотеке", ui.back_to_grid),
                ui.outline_btn("Поискать ещё", ui._open_add),
            ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
                padding=ft.padding.only(0, 8, 0, 0)),
        ], spacing=16, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER),
        expand=True, alignment=ft.alignment.center, padding=ft.padding.all(36))


# =========================================================================
# 08 · Цвет и иконка категории
# =========================================================================
def build_category_popover(ui, cat):
    color = C.category_color(cat)
    hue, lightness, _sat = C.hex_to_hsl(color)

    name_field = ft.TextField(
        value=cat["name"], border=ft.InputBorder.NONE, filled=False, dense=True,
        text_size=13.5, color=C.TEXT, cursor_color=C.TEXT, expand=True,
        content_padding=ft.padding.symmetric(0, 0),
        text_style=ft.TextStyle(weight=ft.FontWeight.W_600),
        on_blur=lambda e: ui.rename_category(cat["id"], e.control.value),
        on_submit=lambda e: ui.rename_category(cat["id"], e.control.value))

    header = ft.Row([
        ft.Container(ui._cat_glyph(cat, size=18), width=34, height=34, border_radius=10,
                     bgcolor=C.PANEL_3, border=ft.border.all(1, C.LINE_4),
                     alignment=ft.alignment.center),
        ft.Container(name_field, height=30, bgcolor=C.BG_1,
                     border=ft.border.all(1, C.SLOT_BORDER), border_radius=7,
                     padding=ft.padding.symmetric(0, 9), expand=True),
        ft.Container(ft.Icon(ft.Icons.CLOSE, size=17, color=C.MUTED_2),
                     on_click=lambda e: ui.close_popover()),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    swatches = [ft.Container(
        width=28, height=28, border_radius=8, bgcolor=hexval,
        border=ft.border.all(2, C.ACCENT) if hexval.lower() == color.lower() else None,
        tooltip=hexval.upper(),
        on_click=lambda e, h=hexval: ui.set_category_color(cat["id"], h))
        for hexval in C.CAT_PALETTE]

    hex_box = ft.Container(
        ft.Row([ft.Container(width=14, height=14, border_radius=4, bgcolor=color),
                _field(color.upper(), "#RRGGBB", mono=True, size=12,
                       on_submit=lambda e: ui.set_category_color(
                           cat["id"], C.parse_hex(e.control.value) or color))],
               spacing=7, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        width=104, height=32, bgcolor=C.BG_1, border=ft.border.all(1, C.SLOT_BORDER),
        border_radius=8, padding=ft.padding.symmetric(0, 9))

    def slider_row(label, value, maximum, gradient, on_change):
        return ft.Row([
            T(label, size=10.5, color=C.TEXT_DIM, width=26),
            ft.Container(
                ft.Slider(min=0, max=maximum, value=value, on_change_end=on_change,
                          active_color=C.ACCENT, inactive_color=C.TRANSPARENT,
                          thumb_color=color, height=18, expand=True),
                gradient=ft.LinearGradient(begin=ft.alignment.center_left,
                                           end=ft.alignment.center_right,
                                           colors=list(gradient)),
                border_radius=3, height=18, expand=True,
                padding=ft.padding.symmetric(0, 0)),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Тон и яркость вместо трёх RGB-ползунков: так цвет подбирают, а не смешивают.
    sliders = ft.Column([
        slider_row("тон", hue, 359, C.HUE_STRIP,
                   lambda e: ui.set_category_color(
                       cat["id"], C.hsl_to_hex(float(e.control.value), lightness))),
        slider_row("ярк.", lightness * 100, 100, (C.BG_1, color, C.WHITE),
                   lambda e: ui.set_category_color(
                       cat["id"], C.hsl_to_hex(hue, float(e.control.value) / 100))),
    ], spacing=5, tight=True, expand=True)

    query = (ui.view.icon_query or "").strip().lower()
    names = [n for n in ICON_PACK if not query or query in n][:24]
    cells = [ft.Container(
        ft.Icon(cat_icon(name), size=17,
                color=color if name == cat.get("icon") and not cat.get("image") else C.TEXT_2),
        width=34, height=34, border_radius=9,
        bgcolor=C.PANEL_3 if name == cat.get("icon") else C.BG_1,
        border=ft.border.all(2, C.ACCENT) if name == cat.get("icon") and not cat.get("image")
        else ft.border.all(1, C.LINE),
        alignment=ft.alignment.center, tooltip=name,
        on_click=lambda e, n=name: ui.set_category_icon(cat["id"], n)) for name in names]
    if not cells:
        cells = [T("Ничего не нашлось", size=12, color=C.MUTED_2)]

    image_row = ft.Container(
        ft.Row([ft.Icon(ft.Icons.IMAGE, size=17, color=C.MUTED),
                ft.Column([T("Своя картинка", size=12.5, color=C.TEXT_2),
                           T("PNG или SVG" if cat.get("image") else
                             "PNG или SVG, кнопкой «Выбрать»", size=10.5, color=C.TEXT_DIM)],
                          spacing=1, expand=True, tight=True),
                ft.Container(T("Убрать" if cat.get("image") else "Выбрать", size=11.5,
                               color=C.TEXT),
                             border=ft.border.all(1, C.LINE_4), border_radius=7,
                             padding=ft.padding.symmetric(5, 10),
                             on_click=lambda e: (ui.clear_category_image(cat["id"])
                                                 if cat.get("image")
                                                 else ui.pick_category_image(cat["id"])))],
               spacing=9, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=44, border=ft.border.all(1, C.LINE_4), border_radius=10,
        padding=ft.padding.symmetric(0, 12), margin=ft.margin.only(top=10))

    footer = ft.Container(
        ft.Row([ft.Container(
            ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, size=15, color=C.ERR_TEXT),
                    T("Удалить категорию", size=12, color=C.ERR_TEXT)], spacing=6, tight=True),
            on_click=lambda e: ui._remove_category(cat["id"])),
            ft.Container(expand=True),
            T("" if ui.calm() else "Esc", size=10.5, color=C.MUTED_3,
              font_family="monospace")],
            vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(0, 14, 0, 0), margin=ft.margin.only(top=12),
        border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)))

    return ft.Container(
        ft.Column([
            header,
            _caps("ЦВЕТ"),
            ft.Row(swatches, spacing=8, wrap=True, run_spacing=8),
            ft.Row([hex_box, sliders], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=1, bgcolor=C.LINE_2, margin=ft.margin.symmetric(10, 0)),
            _caps("ИКОНКА"),
            ft.Container(ft.Row([ft.Icon(ft.Icons.SEARCH, size=14, color=C.MUTED_2),
                                 _field(ui.view.icon_query, "Название иконки", size=12.5,
                                        on_submit=lambda e: ui.set_icon_query(e.control.value),
                                        on_change=None)],
                                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         height=32, bgcolor=C.BG_1, border=ft.border.all(1, C.LINE),
                         border_radius=8, padding=ft.padding.symmetric(0, 10)),
            ft.Container(ft.Column([ft.Row(cells, spacing=6, wrap=True, run_spacing=6)],
                                   scroll=ft.ScrollMode.AUTO), height=120),
            image_row,
            footer,
        ], spacing=10, tight=True),
        width=C.POPOVER_W, bgcolor=C.PANEL, border=ft.border.all(1, C.LINE_4),
        border_radius=14, padding=ft.padding.all(16),
        shadow=ft.BoxShadow(blur_radius=60, offset=ft.Offset(0, 24), color=C.SHADOW_MENU))


# =========================================================================
# 09 · Настройки
# =========================================================================
def build_settings_screen(ui):
    rows = [
        _row(ui, "Вызов окна", "Работает из любой программы",
             ft.Container(T(format_accel(ui.setting("launch_hotkey")), size=11.5,
                            color=C.TEXT, font_family="monospace"),
                          height=32, padding=ft.padding.symmetric(0, 12), bgcolor=C.PANEL,
                          border=ft.border.all(1, C.TOAST_BORDER), border_radius=8,
                          alignment=ft.alignment.center, tooltip="Другая комбинация",
                          on_click=lambda e: ui.cycle_launch_hotkey())),
        _switch(ui, "Прятать окно после запуска", "Открыл — запустил — окно ушло", "hide_after"),
        _switch(ui, "Запускать с Windows", "Свёрнутым в трей", "autostart"),
        _switch(ui, "Крестик сворачивает в трей", "Иначе Centurio завершается", "close_to_tray"),
        _switch(ui, "Складывать новое в разбор",
                "Иначе новые программы не появляются сами", "triage"),
        _switch(ui, "Спокойный вид", "Скрыть счётчики, пути и подсказки клавиш", "calm"),
        _row(ui, "Размер плиток", "Плотность сетки библиотеки", _tile_segments(ui)),
    ]
    return ft.Column([
        _screen_header("Настройки", "Всё сохраняется само", ui.back_to_grid),
        ft.Container(
            ft.Column(rows + [_rare_block(ui)], spacing=17, scroll=ft.ScrollMode.AUTO,
                      expand=True),
            expand=True, padding=ft.padding.only(24, 20, 24, 24)),
    ], spacing=0, expand=True)


def _row(ui, title, sub, control, on_click=None):
    left = [T(title, size=13, color=C.TEXT_2)]
    if sub and not ui.calm():
        left.append(T(sub, size=11, color=C.TEXT_DIM))
    return ft.Container(
        ft.Row([ft.Column(left, spacing=2, tight=True, expand=True), control],
               spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=(lambda e: on_click()) if on_click else None)


def _switch(ui, title, sub, key):
    value = bool(ui.setting(key))
    return _row(ui, title, sub, ui._toggle(value, lambda v, k=key: ui.set_setting(k, v)),
                on_click=lambda k=key, v=value: ui.set_setting(k, not v))


def _tile_segments(ui):
    def segment(label, value):
        active = ui.setting("tile_size", "large") == value
        return ft.Container(
            T(label, size=12, weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
              color=C.TEXT if active else C.MUTED),
            height=26, padding=ft.padding.symmetric(0, 12), border_radius=6,
            bgcolor=C.PANEL_ACTIVE if active else None, alignment=ft.alignment.center,
            on_click=lambda e: ui.set_setting("tile_size", value))
    return ft.Container(ft.Row([segment("Крупные", "large"), segment("Плотные", "compact")],
                               spacing=0),
                        bgcolor=C.PANEL, border=ft.border.all(1, C.SEGMENT_BORDER),
                        border_radius=8, padding=ft.padding.all(2))


def _rare_block(ui):
    """Свёрнутая строка: то, что настраивают раз в жизни."""
    open_now = getattr(ui, "_settings_rare_open", False)
    head = ft.Container(
        ft.Row([T("Акцент, обложки игр, кэш иконок, резервная копия, лог",
                  size=12.5, color=C.TEXT_DIM, expand=True),
                ft.Icon(ft.Icons.EXPAND_LESS if open_now else ft.Icons.EXPAND_MORE,
                        size=18, color=C.TEXT_FAINT)],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.only(0, 15, 0, 0),
        border=ft.border.only(top=ft.BorderSide(1, C.LINE_2)),
        on_click=lambda e: _toggle_rare(ui))
    if not open_now:
        return head

    size = ui.icon_cache_size()
    cache_label = f"{size / (1024 * 1024):.0f} МБ" if size else "пусто"
    swatches = ft.Row([
        ft.Container(width=28, height=28, border_radius=8, bgcolor=col,
                     border=ft.border.all(2, C.ACCENT) if col == ui._accent() else None,
                     tooltip=ACCENT_NAMES.get(col),
                     on_click=lambda e, c=col: ui.set_setting("accent", c))
        for col in C.ACCENT_CHOICES], spacing=8, tight=True)
    return ft.Column([
        head,
        _row(ui, "Акцент", None, swatches),
        _switch(ui, "Постеры вместо иконок у игр", "Вертикальные обложки в сетке",
                "game_posters"),
        _switch(ui, "Показывать «Быстрый запуск»", "Лента карточек сверху", "show_quick_row"),
        _switch(ui, "Проверять новое раз в 15 минут", "Тихо, в фоне", "auto_rescan"),
        _switch(ui, "Подсказки клавиш", "Строка снизу в режиме «Запуск»", "hints"),
        _row(ui, "Кэш иконок", None,
             ft.Row([T(cache_label, size=11, color=C.MUTED_2, font_family="monospace"),
                     ui.link_btn("Очистить", ui.clear_icon_cache)], spacing=10, tight=True)),
        _row(ui, "Копия библиотеки", "Рядом с файлом данных",
             ui.outline_btn("Сохранить", ui.backup, ft.Icons.BACKUP, height=32)),
        _row(ui, "Файл библиотеки", str(ui.store.path),
             ui.link_btn("Показать в папке", ui.show_data_folder)),
        _switch(ui, "Подробный лог", "Для отчёта о проблеме — нужен перезапуск", "debug_log"),
        ft.Container(ui.outline_btn("Показать первый запуск", ui.show_onboarding,
                                    ft.Icons.FLAG, height=34),
                     alignment=ft.alignment.center_left,
                     padding=ft.padding.only(0, 4, 0, 0)),
    ], spacing=17, tight=True)


def _toggle_rare(ui):
    ui._settings_rare_open = not getattr(ui, "_settings_rare_open", False)
    ui.refresh()


# =========================================================================
# 12 · Первый запуск
# =========================================================================
def build_onboarding(ui):
    items = ui.onboarding_items()
    scanning = ui.scanning() and not items
    picked = getattr(ui.view, "onboarding_sel", set())

    rows = []
    for suggestion in items:
        app = suggestion["app"]
        key = (app.get("path") or "").lower()
        checked = key in picked
        rows.append(ft.Container(
            ft.Row([
                ft.Icon(ft.Icons.CHECK_BOX if checked else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                        size=18, color=C.ACCENT if checked else C.MUTED),
                ui.icon_slot(app, 30, 9, glyph=16),
                T(app.get("name") or "", size=13, color=C.TEXT, expand=True, max_lines=1,
                  overflow=ft.TextOverflow.ELLIPSIS),
                T(suggestion["hint"], size=11.5, color=C.MUTED_2),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=44, padding=ft.padding.symmetric(0, 10), border_radius=10,
            bgcolor=C.PANEL if checked else None,
            border=ft.border.all(1, C.LINE_4) if checked else None,
            on_click=lambda e, k=key: ui.toggle_onboarding(k)))

    if scanning:
        rows = [ft.Container(ft.Row([ui.spinner(15),
                                     T("Смотрю, что установлено…", size=12.5, color=C.MUTED)],
                                    spacing=10, tight=True),
                             padding=ft.padding.symmetric(18, 0))]
    elif not rows:
        rows = [ft.Container(T("Ничего подходящего не нашлось — добавьте программы вручную.",
                               size=12.5, color=C.MUTED),
                             padding=ft.padding.symmetric(18, 0))]

    card = ft.Container(
        ft.Column([
            T("Отметьте, чем пользуетесь каждый день", size=18, weight=ft.FontWeight.BOLD,
              color=C.TEXT),
            T("Отмеченные сразу попадут в быстрый запуск. Остальное можно добавить когда "
              "угодно.", size=12.5, color=C.MUTED),
            ft.Container(ft.Column(rows, spacing=2, tight=True),
                         padding=ft.padding.only(0, 4, 0, 0)),
            ft.Row([T(f"Отмечено {len(picked)} из {len(items)}" if items else "", size=12,
                      color=C.MUTED_2, expand=True),
                    ft.Container(T("Позже", size=12.5, color=C.MUTED),
                                 padding=ft.padding.symmetric(9, 12),
                                 on_click=lambda e: ui.close_onboarding()),
                    ui.primary_btn("Добавить и начать", ui.commit_onboarding)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=14, tight=True),
        width=520, bgcolor=C.BG_1, border=ft.border.all(1, C.SLOT_BORDER),
        border_radius=16, padding=ft.padding.all(24),
        shadow=ft.BoxShadow(blur_radius=100, offset=ft.Offset(0, 40), color=C.SHADOW_MENU))
    return ft.Container(card, bgcolor=C.OVERLAY, alignment=ft.alignment.center, expand=True)


# =========================================================================
# Мини-лаунчер в трее
# =========================================================================
def tray_items(store) -> list[dict]:
    """Закреплённые программы, которые меню значка запускает без окна."""
    from .hotkeys import quick_accels
    apps = store.state()["apps"]
    accels = quick_accels(apps)
    out = []
    for app in queries.quick_apps(apps)[:6]:
        accel = accels.get(app["id"])
        out.append({"id": app["id"], "name": app["name"],
                    "label": f"{app['name']}   {accel}" if accel else app["name"]})
    return out


def library_summary(store) -> str:
    apps = store.state()["apps"]
    waiting = len(store.state()["inbox"])
    if not apps:
        return "библиотека пуста"
    text = f"{len(apps)} {plu_apps(len(apps))}"
    return f"{text} · {waiting} в разборе" if waiting else text


__all__ = ["build_add_screen", "build_triage_screen", "build_category_popover",
           "build_settings_screen", "build_onboarding", "tray_items", "library_summary"]
