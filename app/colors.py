"""Design tokens.

Every colour, size and radius the interface draws lives here — the UI modules
import this and never spell a hex value out. The values come from the design
handoff ("Дизайн-токены"); the names are the ones that document said to use.
"""
from __future__ import annotations

import re

# ---- Surfaces ----
BG_WINDOW = "#0b0b0d"        # окно
BG_PANEL = "#0a0a0c"         # панель / инспектор / подвал
BG_RAIL = "#08080a"          # рельс
BG_CARD = "#111114"          # карточка, поле ввода
BG_TILE = "#141417"          # кнопка категории в рельсе
BG_SLOT = "#15151b"          # площадка иконки
BG_HOVER = "#17171b"         # наведение, разделитель
BG_ACTIVE = "#1e1e22"        # активная кнопка рельса / активный сегмент
BG_ROW_ACTIVE = "#15151a"    # активная строка списка «Запуска»
BG_MATCH = "#2b2b33"         # подсветка совпавшей подстроки

# ---- Borders ----
BORDER = "#212126"
BORDER_STRONG = "#2c2c33"
BORDER_ACTIVE = "#33333a"
BORDER_SLOT = "#26262e"
BORDER_WINDOW = "#23232b"
BORDER_DRAG = "#6f7480"      # цель перетаскивания (dashed)

# ---- Text ----
TEXT_1 = "#e6e6e8"           # основной
TEXT_2 = "#c8ccd0"           # вторичный
TEXT_3 = "#9aa0a6"           # третичный
TEXT_4 = "#6b6b70"           # приглушённый
TEXT_5 = "#4a4a54"           # едва заметный
TEXT_6 = "#3d3d43"           # ещё тише
GLYPH_PLACEHOLDER = "#7f8590"  # глиф на месте не найденной иконки .exe

# ---- Accent ----
ACCENT = "#f5f5f7"
ON_ACCENT = "#0b0b0d"
ACCENT_CHOICES = ("#f5f5f7", "#4f7dff", "#3ecfaf", "#f0a020")

# ---- Success / running ----
OK = "#4ade80"
OK_TEXT = "#7ee2a8"
BADGE_BG = "#0c100e"
BADGE_BORDER = "#2a5f42"
BADGE_TEXT = "#d8fce6"

# ---- Error ----
ERR = "#e34f4f"
ERR_TEXT = "#ee8888"   # Flutter не понимает трёхзначный #e88 — он рисуется прозрачным
ERR_BG = "#1a1113"
ERR_BORDER = "#3a2222"
ERR_BTN_BORDER = "#5a2a2a"

STAR = "#f5c518"
WHITE = "#ffffff"          # глиф на цветной кнопке категории, звезда на постере
TOGGLE_OFF = "#2a2a30"     # выключенный переключатель
SCRIM = "#0c0c0edd"        # подложка кнопки поверх обложки
OVERLAY = "#05050699"      # затемнение под карточкой первого запуска

# Тени: 0 20px 50px rgba(0,0,0,0.6) для полосы и тоста,
# 0 24px 60px rgba(0,0,0,0.7) для поповера и карточки.
SHADOW_BAR = "#00000099"
SHADOW_CARD = "#000000b3"

# The only colours a category can be. Three RGB sliders and a hex field used to
# let a category be any colour at all, including ones that vanish on #08080a.
CAT_PALETTE = ("#e6e6e8", "#f5c518", "#f0a020", "#e34f4f",
               "#b06cf0", "#4f7dff", "#3ecfaf", "#7a8290")

# ---- Gradients ----
TILE_GRADIENT = ("#191920", "#111116")     # верх плитки приложения
POSTER_SCRIM = ("#00000000", "#000000e8")  # затемнение под названием постера

# ---- Sizes ----
RAIL_W = 76
RAIL_BTN = 44
RAIL_BAR_W = 3
RAIL_BAR_H = 28
INSPECTOR_W = 320
LAUNCH_W = 720
LAUNCH_H = 520
LAUNCH_HEAD_H = 64
LAUNCH_HINTS_H = 44
LIBRARY_W = 1180
LIBRARY_H = 768
LIBRARY_MIN_W = 940
LIBRARY_MIN_H = 620
TITLEBAR_H = 44
TILE_W = 172
TILE_W_COMPACT = 140
TILE_TOP_H = 104
TILE_FOOT_H = 48          # одинаковый низ плитки, с мета-строкой и без неё
TILE_TOP_H_COMPACT = 88
TILE_SLOT = 60
TILE_SLOT_COMPACT = 48
POSTER_W = 150
POSTER_H = 225
POSTER_W_COMPACT = 124
POSTER_H_COMPACT = 186
POPOVER_W = 300
TOAST_MIN_W = 360
TOAST_MAX_W = 520

# ---- Radii ----
R_CHIP = 5
R_BTN = 8
R_ROW = 11
R_CARD = 14
R_WINDOW = 16

# ---- Control heights ----
H_FIELD = 32
H_BTN = 34
H_BTN_LG = 36

# ---- Motion ----
# "Ничего длиннее 200 мс: это утилита, а не презентация."
ANIM_FAST = 120
ANIM_HOVER = 100


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
    def clamp(v):
        return max(0, min(255, int(v)))
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


def with_alpha(hex_color: str, alpha: float) -> str:
    """#rrggbb -> #rrggbbaa, for scrims Flet can't express as opacity."""
    base = parse_hex(hex_color) or "#000000"
    return base + "%02x" % max(0, min(255, round(alpha * 255)))


def palette_color(text: str) -> str:
    """A stable palette entry for a category that never picked a colour."""
    from .store import hue_from_string
    return CAT_PALETTE[hue_from_string(text or "") % len(CAT_PALETTE)]


def category_color(cat: dict) -> str:
    col = parse_hex(cat.get("color"))
    # "#ffffff" was the old default for every category: it isn't in the palette
    # and it made four categories in a row indistinguishable in the rail.
    if col and col != "#ffffff":
        return col
    return palette_color(cat.get("name") or cat.get("id") or "")
