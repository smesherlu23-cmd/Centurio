"""Text, number, time and font-family formatting helpers for the UI.

Pure presentation helpers with no view state — kept out of ui.py so the UI
module stays focused on layout. Russian pluralisation lives here too.
"""
from __future__ import annotations

import time

import flet as ft

CATEGORY_ICON_CHOICES = ["work", "brush", "sports_esports", "code", "folder",
                         "movie", "music_note", "chat", "terminal", "rocket_launch"]

# A larger icon pack the user can pick from instead of the default first-letter
# chip. Names map to ft.Icons.<UPPER>; cat_icon() falls back to a folder for any
# name Flet doesn't know, so the list is safe to extend freely.
ICON_PACK = [
    "work", "business", "apartment", "store", "home", "folder", "folder_special",
    "code", "terminal", "data_object", "bug_report", "build", "engineering", "memory",
    "brush", "palette", "draw", "design_services", "architecture", "photo_camera",
    "image", "movie", "movie_creation", "music_note", "headphones", "mic", "podcasts",
    "sports_esports", "videogame_asset", "casino", "extension", "sports_soccer",
    "sports_basketball", "fitness_center", "directions_run", "chat", "mail", "forum",
    "language", "translate", "public", "map", "place", "flight", "directions_car",
    "school", "menu_book", "book", "science", "calculate", "functions",
    "cloud", "download", "storage", "dns", "wifi", "security", "lock", "vpn_key",
    "settings", "dashboard", "widgets", "apps", "star", "favorite", "bolt",
    "local_cafe", "restaurant", "shopping_cart", "attach_money", "credit_card",
    "calendar_month", "schedule", "alarm", "computer", "desktop_windows", "tv",
    "phone_android", "keyboard", "print", "rocket_launch", "pets", "spa",
]

_BOLD = {ft.FontWeight.BOLD, ft.FontWeight.W_700, ft.FontWeight.W_800, ft.FontWeight.W_900}


def _family_for(weight):
    """Pick a bundled Inter family for a weight (crisp real weights, not faux)."""
    if weight in _BOLD:
        return "Inter Bold"
    if weight == ft.FontWeight.W_600:
        return "Inter SemiBold"
    return "Inter"


def T(value="", **kw):
    """ft.Text that resolves font_family from the requested weight, and maps the
    'monospace' family to the bundled mono face — so text renders with the
    intended weight everywhere."""
    fam = kw.get("font_family")
    if fam == "monospace":
        kw["font_family"] = "mono"
    elif fam is None:
        kw["font_family"] = _family_for(kw.get("weight"))
    return ft.Text(value, **kw)


def cat_icon(name: str):
    return getattr(ft.Icons, (name or "folder").upper(), ft.Icons.FOLDER)


def initials(name: str) -> str:
    n = (name or "?").strip()
    return n[0].upper() if n else "?"


def time_ago(ms: int) -> str:
    if not ms:
        return ""
    diff = time.time() * 1000 - ms
    m = int(diff // 60000)
    if m < 1:
        return "только что"
    if m < 60:
        return f"{m} {_plural(m, 'минуту', 'минуты', 'минут')} назад"
    h = m // 60
    if h < 24:
        return f"{h} {_plural(h, 'час', 'часа', 'часов')} назад"
    d = h // 24
    return f"{d} {_plural(d, 'день', 'дня', 'дней')} назад"


def _plural(n, one, few, many):
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not (10 <= m100 < 20):
        return few
    return many


def plu_apps(n):
    return _plural(n, "приложение", "приложения", "приложений")


def plu_cats(n):
    return _plural(n, "категория", "категории", "категорий")
