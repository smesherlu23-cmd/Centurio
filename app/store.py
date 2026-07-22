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
    "game_posters": True,   # tall poster tiles for Steam/Epic games
    "auto_rescan": False,   # periodically look for newly installed programs

    # Remembered view state (restored on next launch).
    "view_filter": "all",   # 'all' | 'favorites' | 'recent' | 'running' | 'category:<id>'
    "view_sort": "alpha",   # 'alpha' | 'recent' | 'added'
    "view_mode": "grid",    # 'grid' | 'list'
    # Remembered window geometry (None until the window has been moved/resized).
    "win_w": None,
    "win_h": None,
    "win_x": None,
    "win_y": None,
    "win_max": False,
    # Internal (not user-facing): bumped when the icon pipeline improves, so a
    # one-time re-resolution can refresh icons stored by an older version.
    "icon_schema": 0,
}

CATEGORY_ICONS = ["work", "brush", "sports_esports", "code", "folder",
                  "movie", "music_note", "chat", "terminal", "rocket_launch"]


def hue_from_string(text: str) -> int:
    """Deterministic hue (0..359) from a name — stable per-app tint."""
    digest = hashlib.md5(str(text).lower().encode("utf-8")).digest()
    return ((digest[0] << 8) | digest[1]) % 360


DATA_FILENAME = "centurio-data.json"
PORTABLE_FLAG = "portable.flag"


def app_dir() -> Path:
    """Folder the app is running from (where portable data lives)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if sys.argv and sys.argv[0]:
        return Path(sys.argv[0]).resolve().parent
    return Path.cwd()


def portable_data_path() -> Path | None:
    """Portable data file next to the exe, if portable mode is in effect
    (a data file or an empty ``portable.flag`` marker sits beside the exe)."""
    d = app_dir()
    p = d / DATA_FILENAME
    if p.exists() or (d / PORTABLE_FLAG).exists():
        return p
    return None


def default_data_path() -> Path:
    """Portable data (next to the exe) wins; otherwise %APPDATA%\\Centurio.
    Windows-only app — the Path.home() fallback is just defensive for the
    rare case APPDATA isn't set, not a claim of cross-platform support."""
    portable = portable_data_path()
    if portable:
        return portable
    base = Path(os.environ.get("APPDATA") or Path.home())
    return base / "Centurio" / DATA_FILENAME


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
            # Launch options.
            "working_dir": app.get("working_dir") or "",
            "run_as_admin": bool(app.get("run_as_admin")),
            "sub": app.get("sub") or "",
            "category_id": app.get("category_id") or (cats[0]["id"] if cats else "work"),
            "hue": app["hue"] if isinstance(app.get("hue"), int) else hue_from_string(app.get("name") or app.get("path") or ""),
            "icon": app.get("icon") or None,
            "icon_fit": app.get("icon_fit") or "contain",
            # Portrait poster (Steam library_600x900) for the poster game layout.
            "poster": app.get("poster") or None,
            "favorite": bool(app.get("favorite")),
            "quick": bool(app.get("quick")),
            "hotkey": app.get("hotkey") or None,
            # Process/executable name used to detect the "Запущено" state for
            # apps we don't launch directly (Steam/Epic games run via a URL
            # scheme, so there's no PID to watch — we match the process name).
            "track_exe": app.get("track_exe") or None,
            # Manual sort position (drag-and-drop); ties fall back to added_at.
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
        """Assign manual `order` from a sequence of app ids (drag-and-drop)."""
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

    # ---- categories ----
    def add_category(self, name: str, icon: str | None = None, color: str | None = None) -> dict:
        # icon=None means "use the first letter of the name" (letter chip);
        # a non-empty value is a material-icon name from the icon pack.
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
        """Shift a category up (-1) or down (+1) in the ordering."""
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

    # ---- settings ----
    def set_setting(self, key: str, value) -> dict:
        if key in DEFAULT_SETTINGS:
            self.data["settings"][key] = value
            self._persist()
        return self.data["settings"]

    # ---- import / export / backup / portable ----
    def export_data(self, dest: str | Path) -> Path:
        """Write the whole library (apps + categories + settings) to a file."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        return dest

    def backup(self) -> Path:
        """Timestamped copy of the data file next to it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.export_data(self.path.with_name(f"centurio-backup-{stamp}.json"))

    def import_data(self, src: str | Path, merge: bool = False) -> bool:
        """Load a library from a file. Replaces the current data (or merges apps
        and categories by id when merge=True). Returns False on a bad file."""
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

    @property
    def is_portable(self) -> bool:
        return portable_data_path() is not None and Path(self.path) == portable_data_path()

    def make_portable(self) -> Path:
        """Copy the library next to the exe and switch to portable mode."""
        target = app_dir() / DATA_FILENAME
        self.path = target
        (app_dir() / PORTABLE_FLAG).write_text("", encoding="utf-8")
        self._persist()
        return target
