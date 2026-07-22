from __future__ import annotations

import base64
import os

import flet as ft

from .store import hue_from_string

_RASTER_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
_IMG_B64_CACHE: dict[str, tuple[float, str]] = {}
_SVG_CACHE: dict[str, tuple[float, str]] = {}

_MIN_ART_PX = 160
_IMG_SIZE_CACHE: dict[str, tuple[float, tuple[int, int] | None]] = {}


def img_b64(path) -> str | None:
    if not path or not str(path).lower().endswith(_RASTER_EXT):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _IMG_B64_CACHE.get(path)
    if cached and cached[0] == st.st_mtime:
        return cached[1]
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    b = base64.b64encode(data).decode("ascii")
    _IMG_B64_CACHE[path] = (st.st_mtime, b)
    return b


def _svg_markup(path) -> str | None:
    if not path or not str(path).lower().endswith(".svg"):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _SVG_CACHE.get(path)
    if cached and cached[0] == st.st_mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    _SVG_CACHE[path] = (st.st_mtime, text)
    return text


def icon_image(path, **kw) -> "ft.Image | None":
    b64 = img_b64(path)
    if b64:
        return ft.Image(src_base64=b64, **kw)
    svg = _svg_markup(path)
    if svg:
        return ft.Image(src=svg, **kw)
    return None


def _is_launcher_art(a) -> bool:
    path = a.get("path") or ""
    return path.startswith("steam://") or path.startswith("com.epicgames.launcher://")


def _img_size(path) -> tuple[int, int] | None:
    if not path or not str(path).lower().endswith(_RASTER_EXT):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _IMG_SIZE_CACHE.get(path)
    if cached and cached[0] == st.st_mtime:
        return cached[1]
    size = None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if w and h:
            size = (w, h)
    except Exception:
        size = None
    _IMG_SIZE_CACHE[path] = (st.st_mtime, size)
    return size


def app_hue(a) -> int:
    h = a.get("hue")
    return h if isinstance(h, int) else hue_from_string(a.get("name") or "")
