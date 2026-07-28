"""Pure library queries: what the two modes show, and what a scan found.

Nothing here touches Flet — the UI asks these for lists and renders them.
"""
from __future__ import annotations

# The rail's fixed filters, in the order they appear above the categories.
FIXED_FILTERS = ("all", "favorites", "running", "pinned")

FILTER_TITLES = {
    "all": "Все приложения",
    "favorites": "Избранное",
    "running": "Открыто сейчас",
    "pinned": "Закреплённые",
}

# Where a scan result came from — label and glyph for the group header on the
# "Найти и добавить" screen, plus the category the source implies.
SOURCES = {
    "steam": {"label": "Steam", "icon": "sports_esports", "cat": "games"},
    "epic": {"label": "Epic Games", "icon": "casino", "cat": "games"},
    "startmenu": {"label": "Меню «Пуск»", "icon": "apps", "cat": None},
    "registry": {"label": "Реестр", "icon": "data_object", "cat": None},
    "": {"label": "Другое", "icon": "folder", "cat": None},
}
SOURCE_ORDER = ("steam", "epic", "startmenu", "registry", "")

# Path/name fragments that say what a program is for. The add screen fills the
# category in from this and the user corrects it, instead of picking every time.
_CATEGORY_HINTS = (
    ("dev", ("jetbrains", "pycharm", "intellij", "webstorm", "rider", "clion", "goland",
             "phpstorm", "datagrip", "android studio", "visual studio", "vscode",
             "vs code", "sublime text", "notepad++", "git", "github", "docker",
             "postman", "insomnia", "dbeaver", "putty", "windows terminal", "cmder",
             "sourcetree", "unity", "godot", "node.js", "python", "arduino")),
    ("create", ("photoshop", "illustrator", "premiere", "after effects", "lightroom",
                "indesign", "figma", "blender", "krita", "gimp", "inkscape", "affinity",
                "davinci", "obs", "audacity", "reaper", "ableton", "fl studio",
                "cubase", "capture one", "clip studio", "paint.net", "sketch",
                "substance", "cinema 4d", "maya", "3ds max")),
    ("games", ("steam", "epic games", "gog galaxy", "battle.net", "ubisoft connect",
               "origin", "ea app", "riot client", "roblox", "minecraft")),
)


def valid_filter(f: str, categories: list[dict]) -> str:
    """Note on naming: the view selector is called `view` in the signatures
    below, never `filter` — that name shadows the builtin."""
    if f and f.startswith("category:"):
        cid = f.split(":", 1)[1]
        if not any(c["id"] == cid for c in categories):
            return "all"
    return f if f in FIXED_FILTERS or (f or "").startswith("category:") else "all"


def matches(app: dict, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in app["name"].lower() or q in (app.get("sub") or "").lower()


def sort_apps(apps: list[dict]) -> list[dict]:
    """Alphabetical, always. The grid groups by category and the two
    time-ordered views ("сейчас открыто", "последнее") live in «Запуск»,
    so the sort selector the toolbar used to carry has nothing left to pick."""
    return sorted(apps, key=lambda a: a["name"].lower())


def recent_apps(apps: list[dict], limit: int | None = None) -> list[dict]:
    lst = sorted([a for a in apps if a.get("last_launched")],
                 key=lambda a: a["last_launched"], reverse=True)
    return lst[:limit] if limit else lst


def quick_apps(apps: list[dict]) -> list[dict]:
    """Pinned apps, in library order — the order the Ctrl+N numbers follow."""
    return sorted([a for a in apps if a.get("quick")],
                  key=lambda a: (a.get("order", 0), a.get("added_at", 0)))


# ---- «Запуск» ----
def launch_rows(apps: list[dict], query: str, running: set,
                categories: list[dict], recent_limit: int = 8) -> list[dict]:
    """The list under the search box: matches, or "открыто" + "последнее".

    Rows are either {"kind": "head", "title": ...} or {"kind": "app", "app":
    ...}; the caller renders them in order and only ever highlights the app
    rows, which is why the index of each one is included.
    """
    names = {c["id"]: c["name"] for c in categories}
    out: list[dict] = []

    def add(app):
        out.append({"kind": "app", "app": app, "index": sum(
            1 for r in out if r["kind"] == "app"), "cat": names.get(app.get("category_id"), "")})

    q = (query or "").strip().lower()
    if q:
        hits = [a for a in apps
                if q in a["name"].lower()
                or q in (a.get("sub") or "").lower()
                or q in names.get(a.get("category_id"), "").lower()]
        # A match at the start of the name is what the user meant; "co" should
        # offer Code before Discord.
        hits.sort(key=lambda a: (not a["name"].lower().startswith(q), a["name"].lower()))
        for a in hits:
            add(a)
        return out

    open_now = sorted([a for a in apps if a["id"] in running], key=lambda a: a["name"].lower())
    recent = [a for a in recent_apps(apps, None) if a["id"] not in running][:recent_limit]
    if open_now:
        out.append({"kind": "head", "title": "СЕЙЧАС ОТКРЫТО"})
        for a in open_now:
            add(a)
    if recent:
        out.append({"kind": "head", "title": "ПОСЛЕДНЕЕ"})
        for a in recent:
            add(a)
    return out


def match_spans(name: str, query: str) -> list[tuple[str, bool]]:
    """Split a name into (text, is_match) runs so the UI can tint the hit."""
    q = (query or "").strip()
    if not q:
        return [(name, False)]
    parts: list[tuple[str, bool]] = []
    low, ql = name.lower(), q.lower()
    i = 0
    while True:
        j = low.find(ql, i)
        if j < 0:
            break
        if j > i:
            parts.append((name[i:j], False))
        parts.append((name[j:j + len(q)], True))
        i = j + len(q)
    if i < len(name):
        parts.append((name[i:], False))
    return parts or [(name, False)]


# ---- «Библиотека» ----
def visible_apps(apps: list[dict], view: str, query: str, running: set) -> list[dict]:
    """Everything the grid shows under the current filter, already sorted."""
    out = [a for a in apps if matches(a, query)]
    if view == "favorites":
        out = [a for a in out if a.get("favorite")]
    elif view == "running":
        out = [a for a in out if a["id"] in running]
    elif view == "pinned":
        out = [a for a in out if a.get("quick")]
    elif (view or "").startswith("category:"):
        cid = view.split(":", 1)[1]
        out = [a for a in out if a.get("category_id") == cid]
    return sort_apps(out)


def build_sections(apps: list[dict], categories: list[dict], view: str,
                   query: str, running: set) -> list[dict]:
    """The grid, grouped by category in rail order. Empty groups are dropped."""
    visible = visible_apps(apps, view, query, running)
    by_cat: dict[str, list[dict]] = {}
    for a in visible:
        by_cat.setdefault(a.get("category_id"), []).append(a)

    sections = []
    known = set()
    for cat in categories:
        known.add(cat["id"])
        items = by_cat.get(cat["id"], [])
        if items:
            sections.append({"name": cat["name"], "cid": cat["id"], "cat": cat, "apps": items})
    orphan = [a for cid, items in by_cat.items() if cid not in known for a in items]
    if orphan:
        sections.append({"name": "Без категории", "cid": None, "cat": None,
                         "apps": sort_apps(orphan)})
    return sections


def flatten_sections(sections: list[dict]) -> list[dict]:
    return [a for sec in sections for a in sec["apps"]]


def current_title(view: str, categories: list[dict]) -> str:
    if view in FILTER_TITLES:
        return FILTER_TITLES[view]
    return next((c["name"] for c in categories if view == f"category:{c['id']}"),
                FILTER_TITLES["all"])


# ---- Экран «Найти и добавить» ----
def suggest_category(item: dict, categories: list[dict]) -> str | None:
    """Which category a freshly found program probably belongs in.

    Matched against the source first (Steam and Epic are games, full stop),
    then against known program names in the path. Falls back to the first
    category so a row is never left without one.
    """
    if not categories:
        return None
    source = (item.get("source") or "").lower()
    hinted = SOURCES.get(source, {}).get("cat")
    if not hinted:
        haystack = f"{item.get('name', '')} {item.get('path', '')}".lower()
        for cid, needles in _CATEGORY_HINTS:
            if any(n in haystack for n in needles):
                hinted = cid
                break
    known = {c["id"] for c in categories}
    return hinted if hinted in known else categories[0]["id"]


def group_found(found: list[dict], existing_paths: set, categories: list[dict],
                only_new: bool = False) -> list[dict]:
    """Scan results, grouped by source, each row flagged new / already added.

    `existing_paths` is a set of lowercase paths already in the library — the
    same comparison the old picker used, so re-adding is still impossible.
    """
    buckets: dict[str, list[dict]] = {}
    for item in found:
        path = (item.get("path") or "").strip()
        if not path:
            continue
        source = item.get("source") or ""
        if source not in SOURCES:
            source = ""
        buckets.setdefault(source, []).append({
            "key": path.lower(),
            "item": item,
            "name": item.get("name") or "",
            "path": path,
            "is_new": path.lower() not in existing_paths,
            "cat": suggest_category(item, categories),
        })

    groups = []
    for source in SOURCE_ORDER:
        rows = buckets.get(source)
        if not rows:
            continue
        rows.sort(key=lambda r: r["name"].lower())
        shown = [r for r in rows if r["is_new"]] if only_new else rows
        if not shown:
            continue
        meta = SOURCES[source]
        groups.append({
            "source": source,
            "label": meta["label"],
            "icon": meta["icon"],
            "rows": shown,
            "total": len(rows),
            "new": sum(1 for r in rows if r["is_new"]),
        })
    return groups


def set_name_for(apps: list[dict]) -> str:
    """A name for a set built from a selection: its first two programs."""
    names = [a["name"] for a in apps][:2]
    if not names:
        return "Набор"
    joined = " и ".join(names)
    return joined if len(joined) <= 32 else names[0]
