from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

DEFAULT_CATEGORIES = [
    {"id": "work", "name": "Работа", "icon": "work", "order": 0},
    {"id": "create", "name": "Творчество", "icon": "brush", "order": 1},
    {"id": "games", "name": "Игры", "icon": "sports_esports", "order": 2},
    {"id": "dev", "name": "Разработка", "icon": "code", "order": 3},
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


DATA_FILENAME = "centurio-data.json"


def default_data_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home())
    return base / "Centurio" / DATA_FILENAME


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_data_path()
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
                parsed = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return self._defaults()

        cats = parsed.get("categories")
        return {
            "version": parsed.get("version", 1),
            "categories": cats if isinstance(cats, list) and cats else copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": parsed.get("apps", []) if isinstance(parsed.get("apps"), list) else [],
            "settings": {**DEFAULT_SETTINGS, **(parsed.get("settings") or {})},
        }

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def state(self) -> dict:
        return copy.deepcopy(self.data)

    def add_app(self, app: dict) -> dict:
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
        return next((a for a in self.data["apps"] if a["id"] == app_id), None)

    def update_app(self, app_id: str, patch: dict) -> dict | None:
        app = self.get_app(app_id)
        if not app:
            return None
        for key in ("name", "path", "args", "working_dir", "run_as_admin", "sub", "category_id",
                    "hue", "icon", "icon_fit", "poster", "favorite", "quick", "hotkey",
                    "track_exe", "order"):
            if key in patch:
                app[key] = patch[key]
        self._persist()
        return app

    def reorder_apps(self, ordered_ids: list[str]) -> None:
        pos = {aid: i for i, aid in enumerate(ordered_ids)}
        for app in self.data["apps"]:
            if app["id"] in pos:
                app["order"] = pos[app["id"]]
        self._persist()

    def remove_app(self, app_id: str) -> bool:
        before = len(self.data["apps"])
        self.data["apps"] = [a for a in self.data["apps"] if a["id"] != app_id]
        changed = len(self.data["apps"]) != before
        if changed:
            self._persist()
        return changed

    def mark_launched(self, app_id: str) -> dict | None:
        app = self.get_app(app_id)
        if not app:
            return None
        app["last_launched"] = int(time.time() * 1000)
        app["launch_count"] = app.get("launch_count", 0) + 1
        self._persist()
        return app

    def add_category(self, name: str, icon: str | None = None, color: str | None = None) -> dict:
        cat = {"id": str(uuid.uuid4()), "name": name or "Категория",
               "icon": icon or None, "color": color or None,
               "order": len(self.data["categories"])}
        self.data["categories"].append(cat)
        self._persist()
        return cat

    def update_category(self, cat_id: str, patch: dict) -> dict | None:
        cat = next((c for c in self.data["categories"] if c["id"] == cat_id), None)
        if not cat:
            return None
        for key in ("name", "icon", "color", "order"):
            if key in patch:
                cat[key] = patch[key]
        self._persist()
        return cat

    def reorder_categories(self, ordered_ids: list[str]) -> None:
        pos = {cid: i for i, cid in enumerate(ordered_ids)}
        for cat in self.data["categories"]:
            if cat["id"] in pos:
                cat["order"] = pos[cat["id"]]
        self._persist()

    def move_category(self, cat_id: str, delta: int) -> None:
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
        if key in DEFAULT_SETTINGS:
            self.data["settings"][key] = value
            if persist:
                self._persist()
        return self.data["settings"]

    def flush(self) -> None:
        self._persist()

    def export_data(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        return dest

    def backup(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.export_data(self.path.with_name(f"centurio-backup-{stamp}.json"))

    def import_data(self, src: str | Path, merge: bool = False) -> bool:
        try:
            with open(src, "r", encoding="utf-8") as fh:
                incoming = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(incoming, dict) or "apps" not in incoming:
            return False
        clean = {
            "version": incoming.get("version", 1),
            "categories": incoming.get("categories") if isinstance(incoming.get("categories"), list)
            else copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": incoming.get("apps") if isinstance(incoming.get("apps"), list) else [],
            "settings": {**DEFAULT_SETTINGS, **(incoming.get("settings") or {})},
        }
        if merge:
            have = {a["id"] for a in self.data["apps"] if a.get("id")}
            self.data["apps"] += [a for a in clean["apps"] if a.get("id") not in have]
            hc = {c["id"] for c in self.data["categories"] if c.get("id")}
            self.data["categories"] += [c for c in clean["categories"] if c.get("id") not in hc]
        else:
            self.data = clean
        self._persist()
        return True
