"""Окна других программ: сколько их открыто, где они и как их расставить.

Всё здесь — Windows и только Windows, через `ctypes`. На другой системе (и в
веб-режиме, которым отлаживают не на Windows) `available()` возвращает False, а
каждая функция — пустой результат: вызывающему не нужно знать, где он работает.

Ни одна функция не поднимает исключение. Перечисление окон идёт через
пользовательский callback внутри user32, и упавшее оттуда исключение уносит
поток целиком — поэтому тело callback'а тоже под try.
"""
from __future__ import annotations

import ntpath
import sys
import threading

from . import log

# Кэш «pid -> имя exe»: EnumWindows отдаёт сотни окон, а psutil.Process() —
# системный вызов на каждое. Живёт один проход перечисления.
_SW_RESTORE = 9
_SW_MINIMIZE = 6
_SW_SHOWNORMAL = 1
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

_lock = threading.Lock()


def available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        return hasattr(ctypes, "windll")
    except Exception:
        return False


def _user32():
    import ctypes
    return ctypes.windll.user32


def _pid_names(pids) -> dict[int, str]:
    """pid -> lowercase exe name, for the pids a single pass actually saw."""
    try:
        import psutil
    except Exception:
        return {}
    out: dict[int, str] = {}
    wanted = set(pids)
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            pid = proc.info.get("pid")
            if pid in wanted and proc.info.get("name"):
                out[pid] = proc.info["name"].lower()
    except Exception:
        log.exception("reading process names failed")
    return out


def list_windows() -> list[dict]:
    """Top-level, visible, non-tool windows with a title, newest z-order first.

    Each entry: {"hwnd", "pid", "exe", "title", "rect": (x, y, w, h),
    "minimized"}. `exe` is the lowercase file name of the owning process, which
    is what the library indexes launches by.
    """
    if not available():
        return []
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    found: list[dict] = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _param):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, 4):        # GW_OWNER — дочернее окно
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append({
                "hwnd": int(hwnd), "pid": int(pid.value), "exe": "",
                "title": buf.value,
                "rect": (rect.left, rect.top, rect.right - rect.left,
                         rect.bottom - rect.top),
                "minimized": bool(user32.IsIconic(hwnd)),
            })
        except Exception:
            log.exception("reading a window failed")
        return True

    try:
        with _lock:
            user32.EnumWindows(proto(visit), 0)
    except Exception:
        log.exception("enumerating windows failed")
        return []

    names = _pid_names(w["pid"] for w in found)
    for entry in found:
        entry["exe"] = names.get(entry["pid"], "")
    return found


def windows_for(exe_names, snapshot=None) -> list[dict]:
    """The windows belonging to a set of executable names (lowercase)."""
    wanted = {str(n).lower() for n in exe_names if n}
    if not wanted:
        return []
    entries = list_windows() if snapshot is None else snapshot
    return [w for w in entries if w.get("exe") in wanted]


def count_for(exe_names, snapshot=None) -> int:
    return len(windows_for(exe_names, snapshot))


def activate(hwnd) -> bool:
    """Bring a window forward — what «Переключиться» actually does."""
    if not available() or not hwnd:
        return False
    try:
        user32 = _user32()
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        log.exception("activating a window failed")
        return False


def place(hwnd, rect) -> bool:
    """Move and size one window. `rect` is (x, y, width, height) in pixels."""
    if not available() or not hwnd:
        return False
    x, y, w, h = (int(v) for v in rect)
    try:
        user32 = _user32()
        if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, _SW_SHOWNORMAL)
        return bool(user32.SetWindowPos(hwnd, 0, x, y, w, h,
                                        _SWP_NOZORDER | _SWP_NOACTIVATE))
    except Exception:
        log.exception("moving a window failed")
        return False


def close_window(hwnd) -> bool:
    """Ask a window to close, the same way its own cross does (WM_CLOSE).

    Asking, not killing: a program with unsaved work gets to put up its own
    question instead of losing it.
    """
    if not available() or not hwnd:
        return False
    try:
        return bool(_user32().PostMessageW(hwnd, 0x0010, 0, 0))
    except Exception:
        log.exception("closing a window failed")
        return False


def minimize(hwnd) -> bool:
    if not available() or not hwnd:
        return False
    try:
        _user32().ShowWindow(hwnd, _SW_MINIMIZE)
        return True
    except Exception:
        log.exception("minimising a window failed")
        return False


def monitors() -> list[tuple[int, int, int, int]]:
    """Work areas (taskbar excluded), primary first: (left, top, width, height)."""
    if not available():
        return []
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    user32 = _user32()
    out: list[tuple[bool, tuple[int, int, int, int]]] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HANDLE, wintypes.HDC,
                               ctypes.POINTER(RECT), wintypes.LPARAM)

    def visit(handle, _hdc, _rect, _param):
        try:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                work = info.rcWork
                out.append((bool(info.dwFlags & 1),          # MONITORINFOF_PRIMARY
                            (work.left, work.top, work.right - work.left,
                             work.bottom - work.top)))
        except Exception:
            log.exception("reading a monitor failed")
        return True

    try:
        with _lock:
            user32.EnumDisplayMonitors(0, None, proto(visit), 0)
    except Exception:
        log.exception("enumerating monitors failed")
        return []
    out.sort(key=lambda entry: not entry[0])
    return [area for _primary, area in out]


def work_area(index: int = 0):
    """The work area of monitor `index`, or None when there is no such monitor.

    Returning None is what makes the «монитора нет» toast possible: the caller
    falls back to the primary one and says so.
    """
    areas = monitors()
    if not areas:
        return None
    if 0 <= index < len(areas):
        return areas[index]
    return None


def exe_names_for(app: dict) -> set[str]:
    """Which process names one library entry can appear under.

    Same rule as the launcher's index: an explicit `track_exe` plus the file
    name of the path, so a game started through steam:// still matches.
    """
    names = set()
    track = (app.get("track_exe") or "").strip().lower()
    if track:
        names.add(track)
    path = app.get("path") or ""
    if path and "://" not in path:
        base = ntpath.basename(path).lower()
        if base.endswith((".exe", ".bat", ".cmd", ".com")):
            names.add(base)
    return names
