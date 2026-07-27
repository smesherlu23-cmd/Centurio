from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from . import log

DEFAULT_CATEGORIES = [
    {"id": "work", "name": "Работа", "icon": "work", "color": "#ffffff", "order": 0},
    {"id": "create", "name": "Творчество", "icon": "brush", "color": "#ffffff", "order": 1},
    {"id": "games", "name": "Игры", "icon": "sports_esports", "color": "#ffffff", "order": 2},
    {"id": "dev", "name": "Разработка", "icon": "code", "color": "#ffffff", "order": 3},
]

DEFAULT_SETTINGS = {
    "autostart": False,
    "minimize_to_tray": True,
    "close_to_tray": True,
    "accent": "#f5f5f7",
    "tile_size": "large",
    "show_quick_row": True,
    "game_posters": True,
    "auto_rescan": False,
    "view_filter": "all",
    "view_sort": "alpha",
    "view_mode": "grid",
    "win_w": None,
    "win_h": None,
    "win_x": None,
    "win_y": None,
    "win_max": False,
    "icon_schema": 0,
}

CATEGORY_ICONS = ["work", "brush", "sports_esports", "code", "folder",
                  "movie", "music_note", "chat", "terminal", "rocket_launch"]


def hue_from_string(text: str) -> int:
    digest = hashlib.md5(str(text).lower().encode("utf-8")).digest()
    return ((digest[0] << 8) | digest[1]) % 360


def _as_int(value, fallback: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _clean_app(item, index: int) -> dict | None:
    """Normalise one stored app record, or None if it is unusable.

    Everything downstream indexes app["id"] and app["name"] without a guard and
    sorts on the numeric fields, so a single hand-edited or half-written record
    used to be enough to blank the whole window with a KeyError/TypeError.
    """
    if not isinstance(item, dict):
        return None
    app_id = item.get("id")
    if not isinstance(app_id, str) or not app_id.strip():
        return None
    rec = dict(item)
    rec["id"] = app_id
    name = rec.get("name")
    rec["name"] = name.strip() if isinstance(name, str) and name.strip() else "Без названия"
    rec["path"] = rec["path"] if isinstance(rec.get("path"), str) else ""
    rec["order"] = _as_int(rec.get("order"), index)
    for key in ("added_at", "last_launched", "launch_count"):
        rec[key] = _as_int(rec.get(key))
    hue = _as_int(rec.get("hue"), -1)
    rec["hue"] = hue if 0 <= hue < 360 else hue_from_string(rec["name"] or rec["path"])
    return rec


def _clean_category(item, index: int) -> dict | None:
    if not isinstance(item, dict):
        return None
    cat_id = item.get("id")
    if not isinstance(cat_id, str) or not cat_id.strip():
        return None
    rec = dict(item)
    rec["id"] = cat_id
    name = rec.get("name")
    rec["name"] = name.strip() if isinstance(name, str) and name.strip() else "Категория"
    rec["order"] = _as_int(rec.get("order"), index)
    return rec


def _clean_records(raw, clean) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        rec = clean(item, index)
        if rec is None or rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    return out


DATA_FILENAME = "centurio-data.json"


def default_data_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home())
    return base / "Centurio" / DATA_FILENAME


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_data_path()
        self._lock = threading.RLock()
        # Set by the UI to surface save failures; called with the OS error text
        # on the first failure of a streak, not on every write.
        self.on_error = None
        self.write_error: str | None = None
        self.data = self._load()

    def _defaults(self) -> dict:
        return {
            "version": 1,
            "categories": copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": [],
            "settings": dict(DEFAULT_SETTINGS),
        }

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return self._defaults()
        except OSError:
            log.exception("reading data file failed: %s", self.path)
            return self._defaults()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.exception("data file is corrupted, quarantining a copy: %s", self.path)
            self._quarantine_corrupt(raw)
            return self._defaults()

        return self._sanitize(parsed)

    def _sanitize(self, parsed: dict) -> dict:
        """Turn whatever is on disk into a library the UI can render.

        Corrupt JSON is quarantined by _load; this is the other half — JSON
        that parses but carries junk (a record without an id, a string where a
        timestamp belongs, settings that aren't even an object).
        """
        cats = _clean_records(parsed.get("categories"), _clean_category)
        settings = parsed.get("settings")
        return {
            "version": _as_int(parsed.get("version"), 1),
            "categories": cats or copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": _clean_records(parsed.get("apps"), _clean_app),
            "settings": {**DEFAULT_SETTINGS, **(settings if isinstance(settings, dict) else {})},
        }

    def _quarantine_corrupt(self, raw: str) -> None:
        """Preserve unreadable data on disk instead of silently discarding it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = self.path.with_name(f"centurio-corrupt-{stamp}.json")
        try:
            dest.write_text(raw, encoding="utf-8")
        except OSError:
            log.exception("failed to save corrupted data file copy: %s", dest)

    def _persist(self) -> bool:
        """Write the library out. Never raises.

        A failing save (full disk, the file held by a backup tool, a profile
        that went away) used to propagate straight into the Flet event handler
        that triggered it: the click died with a traceback and the user was
        never told the data hadn't been saved. Now the caller keeps working and
        on_error reports the first failure of a streak.
        """
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except (OSError, ValueError, TypeError) as exc:
            log.exception("saving the data file failed: %s", self.path)
            self._discard_temp(tmp)
            self._report_write_error(str(exc))
            return False
        self.write_error = None
        return True

    def _discard_temp(self, tmp: Path | None) -> None:
        if tmp is None:
            return
        try:
            tmp.unlink()
        except OSError:
            pass

    def _report_write_error(self, message: str) -> None:
        first = self.write_error is None
        self.write_error = message
        if first and self.on_error:
            try:
                self.on_error(message)
            except Exception:
                log.exception("store error callback failed")

    def state(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def add_app(self, app: dict) -> dict:
        with self._lock:
            cats = self.data["categories"]
            record = {
                "id": str(uuid.uuid4()),
                "name": app.get("name") or "Без названия",
                "path": app.get("path") or "",
                "args": app.get("args") or [],
                "working_dir": app.get("working_dir") or "",
                "run_as_admin": bool(app.get("run_as_admin")),
                "sub": app.get("sub") or "",
                "category_id": app.get("category_id") or (cats[0]["id"] if cats else "work"),
                "hue": app["hue"] if isinstance(app.get("hue"), int) else hue_from_string(app.get("name") or app.get("path") or ""),
                "icon": app.get("icon") or None,
                "icon_fit": app.get("icon_fit") or "contain",
                "poster": app.get("poster") or None,
                "favorite": bool(app.get("favorite")),
                "quick": bool(app.get("quick")),
                "hotkey": app.get("hotkey") or None,
                "track_exe": app.get("track_exe") or None,
                "order": app["order"] if isinstance(app.get("order"), int) else len(self.data["apps"]),
                "last_launched": 0,
                "launch_count": 0,
                "added_at": int(time.time() * 1000),
            }
            self.data["apps"].append(record)
            self._persist()
            return record

    def get_app(self, app_id: str) -> dict | None:
        with self._lock:
            return next((a for a in self.data["apps"] if a["id"] == app_id), None)

    def update_app(self, app_id: str, patch: dict, persist: bool = True) -> dict | None:
        """Apply a patch. persist=False batches: the caller must flush().

        Used by bulk passes like the icon backfill, which patched every app in
        turn and rewrote the whole JSON file once per app.
        """
        with self._lock:
            app = self.get_app(app_id)
            if not app:
                return None
            for key in ("name", "path", "args", "working_dir", "run_as_admin", "sub", "category_id",
                        "hue", "icon", "icon_fit", "poster", "favorite", "quick", "hotkey",
                        "track_exe", "order"):
                if key in patch:
                    app[key] = patch[key]
            if persist:
                self._persist()
            return app

    def reorder_apps(self, ordered_ids: list[str]) -> None:
        with self._lock:
            pos = {aid: i for i, aid in enumerate(ordered_ids)}
            for app in self.data["apps"]:
                if app["id"] in pos:
                    app["order"] = pos[app["id"]]
            self._persist()

    def remove_app(self, app_id: str) -> bool:
        with self._lock:
            before = len(self.data["apps"])
            self.data["apps"] = [a for a in self.data["apps"] if a["id"] != app_id]
            changed = len(self.data["apps"]) != before
            if changed:
                self._persist()
            return changed

    def mark_launched(self, app_id: str) -> dict | None:
        with self._lock:
            app = self.get_app(app_id)
            if not app:
                return None
            app["last_launched"] = int(time.time() * 1000)
            app["launch_count"] = app.get("launch_count", 0) + 1
            self._persist()
            return app

    def add_category(self, name: str, icon: str | None = None, color: str | None = None) -> dict:
        with self._lock:
            cat = {"id": str(uuid.uuid4()), "name": name or "Категория",
                   "icon": icon or None, "color": color or "#ffffff",
                   "order": len(self.data["categories"])}
            self.data["categories"].append(cat)
            self._persist()
            return cat

    def update_category(self, cat_id: str, patch: dict) -> dict | None:
        with self._lock:
            cat = next((c for c in self.data["categories"] if c["id"] == cat_id), None)
            if not cat:
                return None
            for key in ("name", "icon", "color", "order"):
                if key in patch:
                    cat[key] = patch[key]
            self._persist()
            return cat

    def reorder_categories(self, ordered_ids: list[str]) -> None:
        with self._lock:
            pos = {cid: i for i, cid in enumerate(ordered_ids)}
            for cat in self.data["categories"]:
                if cat["id"] in pos:
                    cat["order"] = pos[cat["id"]]
            self._persist()

    def move_category(self, cat_id: str, delta: int) -> None:
        with self._lock:
            cats = sorted(self.data["categories"], key=lambda c: c.get("order", 0))
            ids = [c["id"] for c in cats]
            if cat_id not in ids:
                return
            i = ids.index(cat_id)
            j = max(0, min(len(ids) - 1, i + delta))
            if i == j:
                return
            ids.insert(j, ids.pop(i))
            self.reorder_categories(ids)

    def remove_category(self, cat_id: str) -> bool:
        with self._lock:
            before = len(self.data["categories"])
            self.data["categories"] = [c for c in self.data["categories"] if c["id"] != cat_id]
            fallback = self.data["categories"][0]["id"] if self.data["categories"] else None
            for app in self.data["apps"]:
                if app.get("category_id") == cat_id:
                    app["category_id"] = fallback
            changed = len(self.data["categories"]) != before
            if changed:
                self._persist()
            return changed

    def set_setting(self, key: str, value, persist: bool = True) -> dict:
        with self._lock:
            if key in DEFAULT_SETTINGS:
                self.data["settings"][key] = value
                if persist:
                    self._persist()
            return self.data["settings"]

    def flush(self) -> bool:
        with self._lock:
            return self._persist()

    def export_data(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
        return dest

    def backup(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.export_data(self.path.with_name(f"centurio-backup-{stamp}.json"))

    def import_data(self, src: str | Path, merge: bool = False) -> bool:
        """Load a previously exported file.

        Records go through the same shape check as the ones read from disk, so
        a malformed file can't blank the window. Still dormant — no UI path
        calls this — and note that the check is structural: an imported record
        names a launch target that nothing here has verified.
        """
        try:
            with open(src, "r", encoding="utf-8") as fh:
                incoming = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(incoming, dict) or "apps" not in incoming:
            return False
        clean = self._sanitize(incoming)
        with self._lock:
            if merge:
                have = {a["id"] for a in self.data["apps"] if a.get("id")}
                self.data["apps"] += [a for a in clean["apps"] if a.get("id") not in have]
                hc = {c["id"] for c in self.data["categories"] if c.get("id")}
                self.data["categories"] += [c for c in clean["categories"] if c.get("id") not in hc]
            else:
                self.data = clean
            self._persist()
        return True
