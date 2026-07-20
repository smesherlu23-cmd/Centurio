"""Launch external applications and track which of them are running.

Executables are started with subprocess.Popen so their lifetime can be
watched (drives the "Запущено" indicator). Documents, folders and shortcuts
are handed off to the OS. A tiny watcher thread notices when a tracked
process exits and calls the on_change callback.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path

_EXE_EXTS_WIN = {".exe", ".bat", ".cmd", ".com"}


class Launcher:
    def __init__(self, on_change=None):
        self._procs: dict[str, subprocess.Popen] = {}   # apps we spawned
        self._name_ids: set[str] = set()                # detected via psutil
        self._exe_index: dict[str, set[str]] = {}       # exe basename -> app ids
        self._last_emit: frozenset[str] = frozenset()
        self._lock = threading.Lock()
        self._monitor_stop = None
        self.on_change = on_change

    # ---- state ----
    def running_ids(self) -> list[str]:
        with self._lock:
            return list(set(self._procs.keys()) | self._name_ids)

    def is_running(self, app_id: str) -> bool:
        with self._lock:
            return app_id in self._procs or app_id in self._name_ids

    def _emit(self):
        ids = frozenset(self.running_ids())
        if ids == self._last_emit:
            return
        self._last_emit = ids
        if self.on_change:
            try:
                self.on_change(list(ids))
            except Exception:
                pass

    # ---- process-name monitoring (optional, needs psutil) ----
    def set_apps(self, apps):
        """Index apps by executable basename so already-running apps (launched
        anywhere, not just by us) show as 'running'."""
        index: dict[str, set[str]] = {}
        for a in apps:
            path = a.get("path") or ""
            if not path or "://" in path:   # skip URL launchers (Steam etc.)
                continue
            base = os.path.basename(path).lower()
            if base.endswith((".exe", ".bat", ".cmd", ".com")) or os.name != "nt":
                index.setdefault(base, set()).add(a["id"])
        with self._lock:
            self._exe_index = index

    def start_monitor(self, interval: float = 4.0):
        try:
            import psutil  # noqa: F401
        except Exception:
            return False
        if self._monitor_stop:
            return True
        self._monitor_stop = threading.Event()

        def loop():
            import psutil
            while not self._monitor_stop.is_set():
                try:
                    names = set()
                    for p in psutil.process_iter(["name"]):
                        n = p.info.get("name")
                        if n:
                            names.add(n.lower())
                    with self._lock:
                        matched = set()
                        for base, ids in self._exe_index.items():
                            if base in names:
                                matched |= ids
                        self._name_ids = matched
                    self._emit()
                except Exception:
                    pass
                self._monitor_stop.wait(interval)
        threading.Thread(target=loop, daemon=True).start()
        return True

    def stop_monitor(self):
        if self._monitor_stop:
            self._monitor_stop.set()
            self._monitor_stop = None

    # ---- helpers ----
    def _is_executable(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        if os.name == "nt":
            return ext in _EXE_EXTS_WIN
        if sys.platform == "darwin":
            return ext in ("", ".app")
        return ext in ("", ".sh", ".appimage", ".run") or os.access(path, os.X_OK)

    def _open_with_os(self, path: str):
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ---- launch ----
    def launch(self, app: dict) -> dict:
        path = app.get("path") or ""
        if not path:
            return {"ok": False, "error": "Не указан путь к приложению"}

        # URL-scheme launch (e.g. Steam games via steam://rungameid/<id>,
        # Epic via com.epicgames.launcher://…). Hand off to the OS, no tracking.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", path):
            try:
                self._open_with_os(path)
                return {"ok": True, "running": False}
            except OSError as exc:
                return {"ok": False, "error": str(exc)}

        if not os.path.exists(path):
            return {"ok": False, "error": f"Файл не найден: {path}"}

        app_id = app["id"]
        args = app.get("args") or []

        # macOS .app bundles must be opened via `open`.
        if sys.platform == "darwin" and Path(path).suffix.lower() == ".app":
            try:
                subprocess.Popen(["open", "-a", path, *args])
                return {"ok": True, "running": False}
            except OSError as exc:
                return {"ok": False, "error": str(exc)}

        if self._is_executable(path):
            try:
                kwargs = {"cwd": str(Path(path).parent)}
                if os.name == "nt":
                    kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
                else:
                    kwargs["start_new_session"] = True
                proc = subprocess.Popen([path, *args], **kwargs)
            except OSError:
                # Fall back to the OS opener.
                try:
                    self._open_with_os(path)
                    return {"ok": True, "running": False}
                except OSError as exc:
                    return {"ok": False, "error": str(exc)}
            with self._lock:
                self._procs[app_id] = proc
            self._watch(app_id, proc)
            self._emit()
            return {"ok": True, "running": True}

        # Non-executable: hand to the OS, no tracking.
        try:
            self._open_with_os(path)
            return {"ok": True, "running": False}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    def _watch(self, app_id: str, proc: subprocess.Popen):
        def run():
            try:
                proc.wait()
            finally:
                with self._lock:
                    if self._procs.get(app_id) is proc:
                        del self._procs[app_id]
                self._emit()
        threading.Thread(target=run, daemon=True).start()

    def show_in_folder(self, app: dict) -> dict:
        path = app.get("path") or ""
        if not path or not os.path.exists(path):
            return {"ok": False, "error": "Файл не найден"}
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", str(Path(path).parent)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
