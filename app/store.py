"""Persistence layer for Centurio (apps, categories, settings).

Data is stored as JSON in a per-user directory. Writes are atomic
(temp file + os.replace) so a crash never corrupts the library.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
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
    "tile_size": "large",   # 'large' | 'compact'
    "show_quick_row": True,
}

CATEGORY_ICONS = ["work", "brush", "sports_esports", "code", "folder",
                  "movie", "music_note", "chat", "terminal", "rocket_launch"]


def hue_from_string(text: str) -> int:
    """Deterministic hue (0..359) from a name — stable per-app tint."""
    digest = hashlib.md5(str(text).lower().encode("utf-8")).digest()
    return ((digest[0] << 8) | digest[1]) % 360


def default_data_path() -> Path:
    """Resolve the platform-appropriate data file location."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Centurio" / "centurio-data.json"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_data_path()
        self.data = self._load()

    # ---- load / persist ----
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
        """A deep copy safe for the UI to read."""
        return copy.deepcopy(self.data)

    # ---- apps ----
    def add_app(self, app: dict) -> dict:
        cats = self.data["categories"]
        record = {
            "id": str(uuid.uuid4()),
            "name": app.get("name") or "Без названия",
            "path": app.get("path") or "",
            "args": app.get("args") or [],
            "sub": app.get("sub") or "",
            "category_id": app.get("category_id") or (cats[0]["id"] if cats else "work"),
            "hue": app["hue"] if isinstance(app.get("hue"), int) else hue_from_string(app.get("name") or app.get("path") or ""),
            "favorite": bool(app.get("favorite")),
            "quick": bool(app.get("quick")),
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
        for key in ("name", "path", "args", "sub", "category_id", "hue", "favorite", "quick"):
            if key in patch:
                app[key] = patch[key]
        self._persist()
        return app

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

    # ---- categories ----
    def add_category(self, name: str, icon: str = "folder") -> dict:
        cat = {"id": str(uuid.uuid4()), "name": name or "Категория",
               "icon": icon or "folder", "order": len(self.data["categories"])}
        self.data["categories"].append(cat)
        self._persist()
        return cat

    def update_category(self, cat_id: str, patch: dict) -> dict | None:
        cat = next((c for c in self.data["categories"] if c["id"] == cat_id), None)
        if not cat:
            return None
        for key in ("name", "icon", "order"):
            if key in patch:
                cat[key] = patch[key]
        self._persist()
        return cat

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

    # ---- settings ----
    def set_setting(self, key: str, value) -> dict:
        if key in DEFAULT_SETTINGS:
            self.data["settings"][key] = value
            self._persist()
        return self.data["settings"]
