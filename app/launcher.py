from __future__ import annotations

import ntpath
import os
import re
import shlex
import subprocess
import threading
from pathlib import Path

from . import log

_EXE_EXTS = {".exe", ".bat", ".cmd", ".com"}
_DETACHED_PROCESS = 0x00000008


class Launcher:
    def __init__(self, on_change=None):
        self._procs: dict[str, subprocess.Popen] = {}  
        self._name_ids: set[str] = set()                
        self._exe_index: dict[str, set[str]] = {}       
        self._last_emit: frozenset[str] = frozenset()
        self._lock = threading.Lock()
        self._monitor_stop = None
        self.on_change = on_change

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

    def set_apps(self, apps):
        index: dict[str, set[str]] = {}
        for a in apps:
            names: set[str] = set()
            track = (a.get("track_exe") or "").strip().lower()
            if track:
                names.add(track)
            path = a.get("path") or ""
            if path and "://" not in path:
                base = ntpath.basename(path).lower() 
                if base.endswith((".exe", ".bat", ".cmd", ".com")):
                    names.add(base)
            for base in names:
                index.setdefault(base, set()).add(a["id"])
        with self._lock:
            self._exe_index = index

    def start_monitor(self, interval: float = 4.0):
        try:
            import psutil 
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
                    log.exception("process monitor iteration failed")
                self._monitor_stop.wait(interval)
        threading.Thread(target=loop, daemon=True).start()
        return True

    def stop_monitor(self):
        if self._monitor_stop:
            self._monitor_stop.set()
            self._monitor_stop = None
    def _is_executable(self, path: str) -> bool:
        return Path(path).suffix.lower() in _EXE_EXTS

    def _open_with_os(self, path: str):
        os.startfile(path) 

    def _work_dir(self, app: dict, path: str) -> str:
        wd = (app.get("working_dir") or "").strip()
        if wd and os.path.isdir(wd):
            return wd
        return str(Path(path).parent)

    @staticmethod
    def _as_args(args) -> list[str]:
        if isinstance(args, str):
            try:
                return shlex.split(args, posix=False)
            except ValueError:
                return args.split()
        return list(args or [])

    def _run_as_admin(self, path: str, args: list[str], cwd: str) -> dict:
        try:
            import ctypes
            params = " ".join(f'"{a}"' if " " in a else a for a in args)
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", path, params or None, cwd, 1)
            if int(rc) <= 32:
                return {"ok": False, "error": f"Не удалось запустить от администратора (код {rc})"}
            return {"ok": True, "running": False}
        except Exception as exc:
            log.exception("run-as-admin failed for %s", path)
            return {"ok": False, "error": str(exc)}

    def launch(self, app: dict) -> dict:
        path = app.get("path") or ""
        if not path:
            return {"ok": False, "error": "Не указан путь к приложению"}

        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", path):
            try:
                self._open_with_os(path)
                return {"ok": True, "running": False}
            except OSError as exc:
                return {"ok": False, "error": str(exc)}

        if not os.path.exists(path):
            return {"ok": False, "error": f"Файл не найден: {path}"}

        app_id = app["id"]
        args = self._as_args(app.get("args"))
        cwd = self._work_dir(app, path)

        if app.get("run_as_admin"):
            return self._run_as_admin(path, args, cwd)

        if self._is_executable(path):
            try:
                proc = subprocess.Popen([path, *args], cwd=cwd, creationflags=_DETACHED_PROCESS)
            except OSError:
                log.exception("Popen failed for %s; falling back to shell open", path)
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
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
