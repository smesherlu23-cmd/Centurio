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
    {"id": "work", "name": "Работа", "icon": "work", "color": "#e6e6e8", "order": 0},
    {"id": "create", "name": "Творчество", "icon": "brush", "color": "#3ecfaf", "order": 1},
    {"id": "games", "name": "Игры", "icon": "sports_esports", "color": "#f0a020", "order": 2},
    {"id": "dev", "name": "Разработка", "icon": "code", "color": "#4f7dff", "order": 3},
]

# The combination that shows and hides the "Запуск" window. Stored so the
# settings screen can rebind it; the format is the one hotkeys.to_pynput reads.
DEFAULT_LAUNCH_HOTKEY = "Ctrl+Space"

DEFAULT_SETTINGS = {
    # Вызов
    "launch_hotkey": DEFAULT_LAUNCH_HOTKEY,
    "hide_after": True,          # прятать окно после запуска
    "autostart": False,
    "close_to_tray": True,       # крестик сворачивает в трей
    # Список программ
    "auto_rescan": False,        # проверять новое раз в 15 минут
    "covers": True,              # скачивать обложки игр
    # Вид
    "accent": "#f5f5f7",
    "tile_size": "large",        # large | compact
    "game_posters": True,        # постеры вместо иконок у игр
    "hints": True,               # полоса подсказок в «Запуске»
    "calm": False,               # «Спокойный вид» — прячет все технические подписи
    # Данные
    "debug_log": False,
    # Не показывается в настройках
    "view_filter": "all",
    "onboarded": False,
    "win_w": None,
    "win_h": None,
    "win_x": None,
    "win_y": None,
    "win_max": False,
    "icon_schema": 0,
}


def hue_from_string(text: str) -> int:
    # usedforsecurity=False: this only picks a stable tile colour, and without
    # the flag hashlib.md5 refuses to run on a FIPS-enabled Windows install.
    digest = hashlib.md5(str(text).lower().encode("utf-8"), usedforsecurity=False).digest()
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


def _clean_set(item, index: int) -> dict | None:
    """Normalise one app set ("Рабочее утро" — several programs, one click)."""
    if not isinstance(item, dict):
        return None
    set_id = item.get("id")
    if not isinstance(set_id, str) or not set_id.strip():
        return None
    rec = dict(item)
    rec["id"] = set_id
    name = rec.get("name")
    rec["name"] = name.strip() if isinstance(name, str) and name.strip() else "Набор"
    raw_apps = rec.get("apps")
    rec["apps"] = [a for a in raw_apps if isinstance(a, str)] if isinstance(raw_apps, list) else []
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


def _clean_settings(raw) -> dict:
    """Merge in only known settings keys — mirrors set_setting()'s own check.

    Without this, a key that set_setting() would reject (typo'd, renamed
    between versions, hand-edited into the file) still made it into
    state()["settings"] on load and stayed there forever: nothing ever wrote
    it back out, but nothing dropped it either.
    """
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key in DEFAULT_SETTINGS:
            if key in raw:
                settings[key] = raw[key]
    return settings


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
            "version": 2,
            "categories": copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": [],
            "sets": [],
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

        It doubles as the migration: a file written by an older version simply
        has no "sets" and none of the new settings keys, and comes back with
        the defaults filled in.
        """
        cats = _clean_records(parsed.get("categories"), _clean_category)
        apps = _clean_records(parsed.get("apps"), _clean_app)
        known = {a["id"] for a in apps}
        sets = _clean_records(parsed.get("sets"), _clean_set)
        for s in sets:
            # A set that outlived the programs in it would launch nothing and
            # count them anyway.
            s["apps"] = [aid for aid in s["apps"] if aid in known]
        return {
            "version": 2,
            "categories": cats or copy.deepcopy(DEFAULT_CATEGORIES),
            "apps": apps,
            "sets": [s for s in sets if s["apps"]],
            "settings": _clean_settings(parsed.get("settings")),
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
                        "icon", "icon_fit", "poster", "favorite", "quick", "hotkey",
                        "track_exe", "order"):
                if key in patch:
                    app[key] = patch[key]
            if persist:
                self._persist()
            return app

    def update_apps(self, app_ids, patch: dict) -> int:
        """Apply one patch to many apps in a single write.

        The bulk bar moves, favourites and pins whole selections; doing it
        through update_app() rewrote the JSON file once per app.
        """
        wanted = set(app_ids)
        with self._lock:
            touched = 0
            for app_id in wanted:
                if self.update_app(app_id, patch, persist=False) is not None:
                    touched += 1
            if touched:
                self._persist()
            return touched

    def remove_app(self, app_id: str) -> bool:
        return bool(self.remove_apps([app_id]))

    def remove_apps(self, app_ids) -> list[dict]:
        """Drop several apps at once and hand the records back.

        The returned records are what the "Отменить" toast restores, so they
        are the full stored dicts and not just the ids. Sets lose the removed
        members too — a set pointing at a deleted app would launch nothing.
        """
        wanted = set(app_ids)
        with self._lock:
            gone = [a for a in self.data["apps"] if a["id"] in wanted]
            if not gone:
                return []
            self.data["apps"] = [a for a in self.data["apps"] if a["id"] not in wanted]
            for s in self.data["sets"]:
                s["apps"] = [aid for aid in s["apps"] if aid not in wanted]
            self.data["sets"] = [s for s in self.data["sets"] if s["apps"]]
            self._persist()
            return copy.deepcopy(gone)

    def restore_apps(self, records) -> int:
        """Put back what remove_apps() returned, ignoring ids that came back."""
        with self._lock:
            have = {a["id"] for a in self.data["apps"]}
            fresh = [copy.deepcopy(r) for r in records
                     if isinstance(r, dict) and r.get("id") and r["id"] not in have]
            if not fresh:
                return 0
            self.data["apps"] += fresh
            self._persist()
            return len(fresh)

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
                   "icon": icon or "folder", "color": color or "#7a8290",
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

    def remove_category(self, cat_id: str) -> dict | None:
        """Delete a category, returning what it takes to put it back.

        Deleting is not confirmed any more — it is undone, for eight seconds,
        from a toast. That needs both the category record and the list of apps
        that were reassigned, because their old category_id is gone with it.
        """
        with self._lock:
            cat = next((c for c in self.data["categories"] if c["id"] == cat_id), None)
            if cat is None:
                return None
            self.data["categories"] = [c for c in self.data["categories"] if c["id"] != cat_id]
            fallback = self.data["categories"][0]["id"] if self.data["categories"] else None
            moved = []
            for app in self.data["apps"]:
                if app.get("category_id") == cat_id:
                    app["category_id"] = fallback
                    moved.append(app["id"])
            self._persist()
            return {"category": copy.deepcopy(cat), "apps": moved}

    def restore_category(self, undo: dict) -> bool:
        """Undo remove_category() — the record back, the apps back into it."""
        if not isinstance(undo, dict) or not isinstance(undo.get("category"), dict):
            return False
        cat = undo["category"]
        cat_id = cat.get("id")
        if not cat_id:
            return False
        with self._lock:
            if any(c["id"] == cat_id for c in self.data["categories"]):
                return False
            self.data["categories"].append(copy.deepcopy(cat))
            self.data["categories"].sort(key=lambda c: c.get("order", 0))
            back = set(undo.get("apps") or [])
            for app in self.data["apps"]:
                if app["id"] in back:
                    app["category_id"] = cat_id
            self._persist()
            return True

    # ---- Наборы ----
    def add_set(self, name: str, app_ids) -> dict | None:
        with self._lock:
            known = {a["id"] for a in self.data["apps"]}
            members = [aid for aid in dict.fromkeys(app_ids) if aid in known]
            if not members:
                return None
            rec = {"id": str(uuid.uuid4()), "name": (name or "").strip() or "Набор",
                   "apps": members, "order": len(self.data["sets"])}
            self.data["sets"].append(rec)
            self._persist()
            return dict(rec)

    def get_set(self, set_id: str) -> dict | None:
        with self._lock:
            found = next((s for s in self.data["sets"] if s["id"] == set_id), None)
            return copy.deepcopy(found) if found else None

    def remove_set(self, set_id: str) -> dict | None:
        with self._lock:
            rec = next((s for s in self.data["sets"] if s["id"] == set_id), None)
            if not rec:
                return None
            self.data["sets"] = [s for s in self.data["sets"] if s["id"] != set_id]
            self._persist()
            return copy.deepcopy(rec)

    def restore_set(self, record: dict) -> bool:
        if not isinstance(record, dict) or not record.get("id"):
            return False
        with self._lock:
            if any(s["id"] == record["id"] for s in self.data["sets"]):
                return False
            self.data["sets"].append(copy.deepcopy(record))
            self.data["sets"].sort(key=lambda s: s.get("order", 0))
            self._persist()
            return True

    def set_setting(self, key: str, value, persist: bool = True) -> dict:
        with self._lock:
            if key in DEFAULT_SETTINGS:
                self.data["settings"][key] = value
                if persist:
                    self._persist()
            # A copy, like state(): handing out the live dict let a caller
            # mutate the settings behind the lock and without a write.
            return dict(self.data["settings"])

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
                hs = {s["id"] for s in self.data["sets"] if s.get("id")}
                self.data["sets"] += [s for s in clean["sets"] if s.get("id") not in hs]
            else:
                self.data = clean
            self._persist()
        return True
