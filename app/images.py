from __future__ import annotations

import base64
import os
import threading
from collections import OrderedDict

import flet as ft

from .store import hue_from_string

_RASTER_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
MIN_ART_PX = 160
_MISS = object()


class _LruCache:
    """Small mtime-keyed cache with a hard ceiling.

    These caches held every image the session had ever touched, and base64 is
    ~1.33x the file: a few hundred 600x900 game covers pinned tens of megabytes
    for the lifetime of the app. Entries are evicted least-recently-used, by
    count and (where values are big) by total size.
    """

    def __init__(self, max_entries: int, max_bytes: int | None = None):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._data: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key, mtime, default=None):
        with self._lock:
            hit = self._data.get(key)
            if hit is None or hit[0] != mtime:
                return default
            self._data.move_to_end(key)
            return hit[1]

    def put(self, key, mtime, value, size: int = 0):
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._bytes -= old[2]
            self._data[key] = (mtime, value, size)
            self._bytes += size
            while self._data and (len(self._data) > self.max_entries
                                  or (self.max_bytes is not None and self._bytes > self.max_bytes)):
                _key, evicted = self._data.popitem(last=False)
                self._bytes -= evicted[2]

    def __len__(self):
        with self._lock:
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()
            self._bytes = 0


_IMG_B64_CACHE = _LruCache(max_entries=192, max_bytes=24 * 1024 * 1024)
_SVG_CACHE = _LruCache(max_entries=64, max_bytes=2 * 1024 * 1024)
_IMG_SIZE_CACHE = _LruCache(max_entries=512)


def img_b64(path) -> str | None:
    if not path or not str(path).lower().endswith(_RASTER_EXT):
        return None
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _IMG_B64_CACHE.get(key, st.st_mtime)
    if cached is not None:
        return cached
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    b = base64.b64encode(data).decode("ascii")
    _IMG_B64_CACHE.put(key, st.st_mtime, b, len(b))
    return b


def _svg_markup(path) -> str | None:
    if not path or not str(path).lower().endswith(".svg"):
        return None
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return None
    cached = _SVG_CACHE.get(key, st.st_mtime)
    if cached is not None:
        return cached
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    _SVG_CACHE.put(key, st.st_mtime, text, len(text))
    return text


def icon_image(path, **kw) -> "ft.Image | None":
    b64 = img_b64(path)
    if b64:
        return ft.Image(src_base64=b64, **kw)
    svg = _svg_markup(path)
    if svg:
        return ft.Image(src=svg, **kw)
    return None


def is_launcher_art(a) -> bool:
    path = a.get("path") or ""
    return path.startswith("steam://") or path.startswith("com.epicgames.launcher://")


def img_size(path) -> tuple[int, int] | None:
    if not path or not str(path).lower().endswith(_RASTER_EXT):
        return None
    key = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return None
    # A miss and a cached "PIL couldn't read this" both look like None, so the
    # negative result is cached through a sentinel instead of re-opening.
    cached = _IMG_SIZE_CACHE.get(key, st.st_mtime, _MISS)
    if cached is not _MISS:
        return cached
    size = None
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if w and h:
            size = (w, h)
    except Exception:
        size = None
    _IMG_SIZE_CACHE.put(key, st.st_mtime, size)
    return size


def app_hue(a) -> int:
    h = a.get("hue")
    return h if isinstance(h, int) else hue_from_string(a.get("name") or "")
