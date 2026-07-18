"""Per-app colour tinting.

Every app gets a deterministic hue; from it we derive a clean, saturated
two-stop gradient for its tile (no haze, no glare) plus a readable glyph
colour — echoing the refined Centurio palette.
"""
from __future__ import annotations

import colorsys

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
