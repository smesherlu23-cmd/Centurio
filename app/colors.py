"""Per-app colour tinting.

Every app gets a deterministic hue; from it we derive a clean, saturated
two-stop gradient for its tile (no haze, no glare) plus a readable glyph
colour — echoing the refined Centurio palette.
"""
from __future__ import annotations

import colorsys
import re

# Dark theme tokens (shared with the UI).
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


def _hex(rgb) -> str:
    r, g, b = rgb
    return "#%02x%02x%02x" % (max(0, min(255, round(r * 255))),
                              max(0, min(255, round(g * 255))),
                              max(0, min(255, round(b * 255))))


def cover_colors(hue: int) -> tuple[str, str]:
    """Bright top-left -> deeper bottom-right pair for a tile cover."""
    h = (hue % 360) / 360.0
    top = colorsys.hls_to_rgb(h, 0.58, 0.62)
    bottom = colorsys.hls_to_rgb(h, 0.42, 0.60)
    return _hex(top), _hex(bottom)


def chip_colors(hue: int) -> tuple[str, str]:
    """Slightly brighter pair for small square icons (quick row, list, recents)."""
    h = (hue % 360) / 360.0
    top = colorsys.hls_to_rgb(h, 0.62, 0.62)
    bottom = colorsys.hls_to_rgb(h, 0.48, 0.60)
    return _hex(top), _hex(bottom)


def glyph_color(hue: int) -> str:
    """Glyph colour on top of a cover — solid white reads cleanly on every hue."""
    return "#ffffff"


# ---- category icon colours (user-editable via RGB / hex) ----
def parse_hex(text) -> str | None:
    """Normalise a colour string to '#rrggbb', or None if unparseable.

    Accepts '#rgb', '#rrggbb' (with or without '#'), 'rgb(r,g,b)' and 'r,g,b'."""
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


def category_color(cat: dict) -> str:
    """The category's icon colour: its explicit hex, else a pleasant colour
    derived from the name so uncoloured categories still look distinct."""
    from .store import hue_from_string
    col = parse_hex(cat.get("color"))
    if col:
        return col
    return cover_colors(hue_from_string(cat.get("name") or cat.get("id") or ""))[0]
