from __future__ import annotations

import colorsys
import re

BG_0 = "#08080a"
BG_1 = "#0b0b0d"
BG_2 = "#0a0a0c"
PANEL = "#111114"
PANEL_2 = "#141417"
PANEL_3 = "#17171b"
LINE = "#212126"
LINE_2 = "#17171b"
LINE_4 = "#2c2c33"
LINE_5 = "#33333a"
TEXT = "#e6e6e8"
TEXT_2 = "#c8ccd0"
MUTED = "#9aa0a6"
MUTED_2 = "#6b6b70"
MUTED_3 = "#3d3d43"
GREEN = "#4ade80"
DANGER = "#e34f4f"
STAR = "#f5c518"

# ---- Добавлено редизайном ----
# Имена ниже — из спецификации; старые константы выше остались как были, потому
# что раскладка библиотеки не менялась и продолжает ими пользоваться.

CONTROL = "#23232b"          # граница поля, кнопки, контрола — самый частый штрих
RAIL_BTN_BG = "#101014"      # круглая кнопка рельсы

ACCENT = "#f5f5f7"           # главная кнопка, бейдж разбора, активный переключатель
ON_ACCENT = "#0b0b0d"        # текст и глиф на акценте
WHITE = "#ffffff"            # цвет категории по умолчанию, глиф на цветной кнопке

# Площадка иконки приложения — она же заглушка, когда иконку достать не удалось.
SLOT_BG = "#15151b"
SLOT_BORDER = "#26262e"
SLOT_GLYPH = "#7f8590"

TEXT_DIM = "#5a5f68"         # пояснения в настройках и разборе
TEXT_FAINT = "#4a4f58"       # номера мест, счётчики в меню
TEXT_GHOST = "#2e2e37"       # пустой слот, тихие иконки в «Запуске»
HINT = "#33383f"             # строка подсказок в «Запуске»
WINDOW_BORDER = "#23232b"    # рамка окна «Запуска», трек спиннера
PANEL_ACTIVE = "#1e1e22"     # активная кнопка рельса, активный сегмент
DASHED_RAIL = "#3a3a44"      # пунктир вокруг значка разбора
MATCH_BG = "#2b2b33"         # подсветка совпавшей подстроки
TOGGLE_OFF = "#2a2a30"       # выключенный переключатель
DOT = "#43434c"              # точка у секции без категории
SEGMENT_BORDER = "#1e1e25"   # рамка сегментного переключателя
PROGRESS_TRACK = "#1a1a21"   # непройденная часть полосы разбора
SLOT_BORDER_SEL = "#2e2e38"  # площадка иконки на выбранной плитке
SLOT_GLYPH_SEL = "#8f959f"

SELECTED_BG = "#141418"      # выбранная плитка
MENU_BORDER = "#2c2c33"
TOAST_BG = "#17171b"
TOAST_BORDER = "#2e2e38"

BADGE_BG = "#0c100e"         # бейдж «Запущено»
BADGE_BORDER = "#2a5f42"
BADGE_TEXT = "#d8fce6"
GREEN_TEXT = "#7ee2a8"

# Трёхзначный #e88 из макета Flutter не понимает — он рисуется прозрачным.
ERR_TEXT = "#ee8888"
ERR_BG = "#1a1113"
ERR_BORDER = "#3a2222"
ERR_BTN_BORDER = "#5a2a2a"

# Карточка набора в ленте быстрого запуска — тише обычной.
SET_BG = "#0e0e12"
SET_BORDER = "#1c1c23"
SET_SLOT_BG = "#131318"
SET_SLOT_BORDER = "#202028"
DASHED = "#1f1f27"           # пустое место в ленте

# Палитра поиска — то, чем заменилось окно «Запуск».
PALETTE_BG = "#101015"
PALETTE_BORDER = "#2a2a33"
PALETTE_FOOT = "#0c0c10"
PALETTE_FOOT_BORDER = "#1c1c23"
PALETTE_ROW = "#1c1c23"       # выделенная строка
SCRIM_BODY = "#99050507"      # затемнение тела под палитрой
SHADOW_PALETTE = "#cc000000"  # 0 30px 70px rgba(0,0,0,.8)
FIELD_ACTIVE_BG = "#15151c"
FIELD_ACTIVE_BORDER = "#4a4f58"

# Плавающая панель массовых операций.
BAR_BG = "#16161d"
BAR_BORDER = "#33333a"
BAR_BTN = "#1f1f27"
SHADOW_BAR = "#a6000000"      # 0 18px 44px rgba(0,0,0,.65)

# Схема раскладки окон в наборе.
CANVAS_BG = "#0e0e12"
PRESET_ACTIVE_BG = "#16161c"   # выбранный пресет раскладки
WIN_BG = "#15151d"
WIN_BORDER = "#2c2c36"
WIN_BORDER_ACTIVE = "#3a3a44"

# Разбор
TRIAGE_SLOT_BORDER = "#2a2a33"
TRIAGE_PICK_BG = "#141418"
TRIAGE_PICK_BORDER = "#33333a"
TRIAGE_CHIP_BORDER = "#212128"
DONE_BG = "#0e130f"
DONE_BORDER = "#244530"

TRANSPARENT = "#00000000"
SCRIM = "#dd0c0c0e"          # подложка звезды поверх обложки
OVERLAY = "#99050506"        # затемнение под карточкой первого запуска
SHADOW_MENU = "#b3000000"    # 0 24px 60px rgba(0,0,0,0.7)
SHADOW_TOAST = "#99000000"   # 0 20px 50px rgba(0,0,0,0.6)

# Единственные цвета, которыми может быть категория. Три RGB-ползунка позволяли
# выбрать в том числе цвет, неразличимый на #08080a. Четыре последних — цвета
# категорий по умолчанию из макета.
CAT_PALETTE = ("#e6e6e8", "#f5c518", "#f0a020", "#e34f4f",
               "#b06cf0", "#4f7dff", "#3ecfaf", "#7a8290",
               "#b98cff", "#ff9f6e")
ACCENT_CHOICES = ("#f5f5f7", "#4f7dff", "#3ecfaf", "#f0a020")

TILE_GRADIENT = ("#191920", "#111116")
TILE_GRADIENT_SEL = ("#1d1d26", "#141419")
POSTER_SCRIM = ("#00000000", "#e8000000")
HUE_STRIP = ("#e34f4f", "#f0a020", "#f5c518", "#4ade80",
             "#3ecfaf", "#4f7dff", "#b06cf0", "#e34f4f")

# ---- Размеры ----
HEADER_H = 52
RAIL_W = 72
RAIL_BTN = 42
SIDEBAR_W = 232
INSPECTOR_W = 300
SEARCH_W = 560
SEARCH_MIN_W = 220
PALETTE_W = 640
TILE_W = 164
TILE_W_COMPACT = 140
TILE_COVER_H = 90
TILE_COVER_H_COMPACT = 78
TILE_SLOT = 50
TILE_SLOT_COMPACT = 42
QUICK_W = 132
POSTER_W = 132
POSTER_H = 198
POSTER_W_COMPACT = 112
POSTER_H_COMPACT = 168
LIBRARY_W = 1400
LIBRARY_H = 880
LIBRARY_MIN_W = 940
LIBRARY_MIN_H = 620
MENU_W = 300
POPOVER_W = 330
TOAST_MIN_W = 360
TOAST_MAX_W = 520
SET_SIDE_W = 300      # колонка «Порядок запуска» на экране набора
CANVAS_H = 280        # полотно монитора на схеме раскладки

# Ниже этой ширины окна инспектор ложится поверх контента, а не рядом с ним;
# ниже второй — боковая панель уходит совсем, остаётся рельса.
NARROW_INSPECTOR = 1200
NARROW_SIDEBAR = 1000

# ---- Анимация ----
ANIM_FAST = 120
ANIM_HOVER = 80
ANIM_BAR = 140


def _hex(rgb) -> str:
    r, g, b = rgb
    return "#%02x%02x%02x" % (max(0, min(255, round(r * 255))),
                              max(0, min(255, round(g * 255))),
                              max(0, min(255, round(b * 255))))


def cover_colors(hue: int) -> tuple[str, str]:
    h = (hue % 360) / 360.0
    top = colorsys.hls_to_rgb(h, 0.58, 0.62)
    bottom = colorsys.hls_to_rgb(h, 0.42, 0.60)
    return _hex(top), _hex(bottom)


def chip_colors(hue: int) -> tuple[str, str]:
    h = (hue % 360) / 360.0
    top = colorsys.hls_to_rgb(h, 0.62, 0.62)
    bottom = colorsys.hls_to_rgb(h, 0.48, 0.60)
    return _hex(top), _hex(bottom)


def glyph_color(hue: int) -> str:
    """Initials/icon colour for a chip_colors()/cover_colors() gradient.

    White reads fine on most hues at the lightness those gradients use, but
    the yellow-through-cyan band (~40-195°) is perceptually bright enough at
    the same HLS lightness that white text washes out — those get a dark
    glyph instead.
    """
    h = (hue % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.55, 0.61)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return BG_1 if luminance > 0.6 else "#ffffff"


def parse_hex(text) -> str | None:
    if not text:
        return None
    s = str(text).strip().lower()
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$", s)
    if not m:
        m = re.match(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$", s)
    if m:
        return rgb_to_hex(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    s = s.lstrip("#")
    if len(s) == 3 and all(c in "0123456789abcdef" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) == 6 and all(c in "0123456789abcdef" for c in s):
        return "#" + s
    return None


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (parse_hex(hex_color) or "#888888").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    clamp = lambda v: max(0, min(255, int(v)))
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


def with_alpha(hex_color: str, alpha: float) -> str:
    """#rrggbb -> #aarrggbb, for scrims Flet can't express as opacity.

    Alpha goes first: Flutter reads an eight-digit colour as #AARRGGBB. Written
    the CSS way (#RRGGBBAA) every shadow in the program came out with alpha 00 —
    that is, invisible — and every scrim turned into a faint blue tint.
    """
    base = (parse_hex(hex_color) or "#000000").lstrip("#")
    return "#%02x%s" % (max(0, min(255, round(alpha * 255))), base)


def hsl_to_hex(hue: float, lightness: float, saturation: float = 0.62) -> str:
    """The two sliders the category popover offers, turned back into a colour."""
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0,
                                  max(0.0, min(1.0, lightness)),
                                  max(0.0, min(1.0, saturation)))
    return _hex((r, g, b))


def hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (v / 255 for v in hex_to_rgb(hex_color))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, lightness, s


def category_color(cat: dict) -> str:
    """A category's colour: whatever was explicitly set, white otherwise.

    White is the theme's own colour, not a placeholder — a new or default
    category stays white until someone picks something else in the popover.
    """
    return parse_hex(cat.get("color")) or WHITE
