from __future__ import annotations

SORT_KEYS = ("alpha", "recent", "added", "manual")

SORT_LABELS = {"alpha": "По алфавиту", "recent": "Недавние",
               "added": "Недавно добавленные", "manual": "Вручную"}

# Where a scan result came from — the group header on "Найти и добавить", plus
# the category that source implies.
SOURCES = {
    "steam": {"label": "Steam", "icon": "sports_esports", "cat": "games"},
    "epic": {"label": "Epic Games", "icon": "casino", "cat": "games"},
    "startmenu": {"label": "Меню «Пуск»", "icon": "apps", "cat": None},
    "registry": {"label": "Реестр", "icon": "data_object", "cat": None},
    "manual": {"label": "Вручную", "icon": "folder_open", "cat": None},
    "": {"label": "Другое", "icon": "folder", "cat": None},
}
# Manually added entries go on top: the user just typed them and wants to see
# them land somewhere.
SOURCE_ORDER = ("manual", "steam", "epic", "startmenu", "registry", "")

# Path/name fragments that say what a program is for. The add screen and the
# triage queue fill the category in from this; the user confirms.
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
    return f or "all"


def visible(apps: list[dict]) -> list[dict]:
    """Everything except what «Скрыть» put away.

    Hidden entries stay in the library — they keep their hotkey, their category
    and their history — they just don't take up room in the grid. The «Скрытые»
    view is the one place they show up, so the flag is never a one-way door.
    """
    return [a for a in apps if not a.get("hidden")]


def sort_apps(apps: list[dict], sort: str) -> list[dict]:
    if sort == "alpha":
        return sorted(apps, key=lambda a: a["name"].lower())
    if sort == "recent":
        return sorted(apps, key=lambda a: a.get("last_launched", 0), reverse=True)
    if sort == "added":
        return sorted(apps, key=lambda a: a.get("added_at", 0), reverse=True)
    if sort == "manual":
        return sorted(apps, key=lambda a: (a.get("order", 0), a.get("added_at", 0)))
    return apps


def recent_apps(apps: list[dict], limit: int | None = None) -> list[dict]:
    lst = sorted([a for a in apps if a.get("last_launched")],
                 key=lambda a: a["last_launched"], reverse=True)
    return lst[:limit] if limit else lst


def quick_apps(apps: list[dict]) -> list[dict]:
    return [a for a in apps if a.get("quick")]


def build_sections(apps: list[dict], categories: list[dict], view: str,
                   sort: str, running: set) -> list[dict]:
    """Секции сетки для активного раздела.

    Поиска здесь больше нет: он живёт в палитре поверх библиотеки, и сетка под
    ней намеренно не перестраивается — иначе теряется то, на что смотрели.
    """
    if view == "hidden":
        return [{"name": "Скрытые",
                 "apps": sort_apps([a for a in apps if a.get("hidden")], sort),
                 "editable": False, "cid": None}]
    shown = visible(apps)
    if view == "favorites":
        return [{"name": "Избранное",
                 "apps": sort_apps([a for a in shown if a.get("favorite")], sort),
                 "editable": False, "cid": None}]
    if view == "recent":
        return [{"name": "Недавние", "apps": recent_apps(shown),
                 "editable": False, "cid": None}]
    if view == "running":
        return [{"name": "Запущено",
                 "apps": sort_apps([a for a in shown if a["id"] in running], sort),
                 "editable": False, "cid": None}]
    if view.startswith("category:"):
        cid = view.split(":", 1)[1]
        cat = next((c for c in categories if c["id"] == cid), None)
        return [{"name": cat["name"] if cat else "Категория",
                 "apps": sort_apps([a for a in shown if a.get("category_id") == cid], sort),
                 "editable": bool(cat), "cid": cid}]
    sections = []
    known = set()
    for cat in categories:
        known.add(cat["id"])
        sections.append({"name": cat["name"], "cid": cat["id"], "editable": True,
                         "apps": sort_apps([a for a in shown if a.get("category_id") == cat["id"]], sort)})
    orphan = sort_apps([a for a in shown if a.get("category_id") not in known], sort)
    if orphan:
        sections.append({"name": "Без категории", "apps": orphan, "editable": False, "cid": None})
    return [s for s in sections if s["apps"]]


def flatten_sections(sections: list[dict]) -> list[dict]:
    return [a for sec in sections for a in sec["apps"]]


def current_title(view: str, categories: list[dict]) -> str:
    """The sidebar's heading: the name of the active rail section.

    It used to say «Поиск» while a query was typed; searching is a palette over
    the library now, and the library keeps saying which section it is showing.
    """
    return {"all": "Все программы", "favorites": "Избранное", "recent": "Недавние",
            "running": "Запущено", "hidden": "Скрытые"}.get(view) or (
        next((c["name"] for c in categories if view == f"category:{c['id']}"), "Все программы"))


# ---- Палитра поиска ----
# Она заменила окно «Запуск»: ранжирование и подписи те же, изменилась только
# рамка, в которой это показывают.
PALETTE_LIMIT = 8


def search_rows(apps: list[dict], query: str, running: set,
                categories: list[dict], recent_limit: int = PALETTE_LIMIT) -> list[dict]:
    """Programs for the palette: matches, or what is open plus what was.

    One flat list — running first, then recent — and every row carries the note
    that used to be implied by a caps header above it.
    """
    names = {c["id"]: c["name"] for c in categories}
    pool = visible(apps)
    out: list[dict] = []

    def add(app, note):
        out.append({"app": app, "index": len(out), "note": note,
                    "cat": names.get(app.get("category_id"), "")})

    q = (query or "").strip().lower()
    if q:
        hits = [a for a in pool
                if q in a["name"].lower()
                or q in (a.get("sub") or "").lower()
                or q in names.get(a.get("category_id"), "").lower()]
        # A match at the start of the name is what the user meant: "co" should
        # offer Code before Discord.
        hits.sort(key=lambda a: (not a["name"].lower().startswith(q), a["name"].lower()))
        for app in hits:
            add(app, "открыто" if app["id"] in running else "")
        return out

    for app in sorted([a for a in pool if a["id"] in running], key=lambda a: a["name"].lower()):
        add(app, "открыто")
    for app in [a for a in recent_apps(pool) if a["id"] not in running][:recent_limit]:
        add(app, "")
    if not out:
        # Ничего не запущено и ничего ещё не запускали — первое Ctrl+Пробел не
        # должно открывать пустую палитру. Тогда предлагаются закреплённые, а за
        # ними просто библиотека по алфавиту.
        pinned = quick_apps(pool)
        rest = sorted((a for a in pool if not a.get("quick")),
                      key=lambda a: a["name"].lower())
        for app in (pinned + rest)[:recent_limit]:
            add(app, "")
    return out


def set_rows(sets: list[dict], apps: list[dict], query: str) -> list[dict]:
    """Sets for the palette, matched by their own name or a member's."""
    q = (query or "").strip().lower()
    names = {a["id"]: a["name"] for a in apps}
    out = []
    for rec in sets:
        members = [names[i] for i in rec.get("apps", []) if i in names]
        if q and q not in rec["name"].lower() and not any(q in m.lower() for m in members):
            continue
        out.append({"set": rec, "members": members})
    return out


def has_layout(rec: dict) -> bool:
    """True when the set places at least one window somewhere."""
    return any(i.get("slot") is not None or i.get("rect") for i in rec.get("items", []))


def set_summary(rec: dict) -> str:
    """The sidebar's second line: «4 программы · раскладка»."""
    from .format import plu_programs
    count = len(rec.get("items", []))
    text = f"{count} {plu_programs(count)}"
    return f"{text} · раскладка" if has_layout(rec) else text


def set_palette_sub(rec: dict, members: list[str]) -> str:
    """«4 программы, включая 1С · с раскладкой»."""
    from .format import plu_programs
    count = len(members)
    text = f"{count} {plu_programs(count)}"
    if members:
        text += f", включая {members[0]}"
    return f"{text} · с раскладкой" if has_layout(rec) else text


def app_palette_sub(row: dict, windows: int = 0) -> str:
    """«Работа», «Работа · открыто, 2 окна», «Работа · 3 дня назад»."""
    from .format import plu_windows, short_ago
    parts = [row["cat"]] if row["cat"] else []
    if row["note"] == "открыто":
        parts.append(f"открыто, {windows} {plu_windows(windows)}" if windows > 1 else "открыто")
    else:
        ago = short_ago(row["app"].get("last_launched"))
        if ago:
            parts.append(ago)
    return " · ".join(parts)


# Строки группы «ДЕЙСТВИЯ»: относятся к выделенной программе и пересчитываются
# при смене выделения. hint — то, что написано справа.
PALETTE_ACTIONS = (
    {"key": "folder", "icon": "folder_open", "label": "Открыть папку программы", "hint": ""},
    {"key": "admin", "icon": "shield", "label": "Запустить от имени администратора",
     "hint": "Ctrl+Enter"},
    {"key": "set", "icon": "playlist_add", "label": "Добавить в набор…", "hint": ""},
)


def palette_actions(app: dict | None) -> list[dict]:
    if app is None:
        return []
    return [dict(a) for a in PALETTE_ACTIONS]


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


# ---- Экран «Найти и добавить» ----
def suggest_category(item: dict, categories: list[dict]) -> str | None:
    """Which category a freshly found program probably belongs in.

    The source decides first (Steam and Epic are games, full stop), then known
    program names in the path. Falls back to the first category, so a row is
    never left without one.
    """
    if not categories:
        return None
    hinted = SOURCES.get((item.get("source") or "").lower(), {}).get("cat")
    if not hinted:
        haystack = f"{item.get('name', '')} {item.get('path', '')}".lower()
        for cid, needles in _CATEGORY_HINTS:
            if any(n in haystack for n in needles):
                hinted = cid
                break
    known = {c["id"] for c in categories}
    return hinted if hinted in known else categories[0]["id"]


def suggest_categories(item: dict, categories: list[dict], limit: int = 4) -> list[dict]:
    """The category buttons the triage screen offers, best guess first."""
    if not categories:
        return []
    best = suggest_category(item, categories)
    ordered = [c for c in categories if c["id"] == best]
    ordered += [c for c in categories if c["id"] != best]
    return ordered[:limit]


def group_found(found: list[dict], existing_paths: set, categories: list[dict],
                only_new: bool = False, query: str = "") -> list[dict]:
    """Scan results grouped by source, each row flagged new / already added.

    `existing_paths` is a set of lowercase paths already in the library — the
    same comparison the old picker used, so re-adding stays impossible.
    """
    q = (query or "").strip().lower()
    buckets: dict[str, list[dict]] = {}
    for item in found:
        path = (item.get("path") or "").strip()
        name = item.get("name") or ""
        if not path:
            continue
        if q and q not in name.lower() and q not in path.lower():
            continue
        source = item.get("source") or ""
        if source not in SOURCES:
            source = ""
        buckets.setdefault(source, []).append({
            "key": path.lower(),
            "item": item,
            "name": name,
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
        groups.append({"source": source, "label": meta["label"], "icon": meta["icon"],
                       "rows": shown, "total": len(rows),
                       "new": sum(1 for r in rows if r["is_new"])})
    return groups


def set_name_for(apps: list[dict]) -> str:
    """A name for a set built from a selection: its first two programs."""
    names = [a["name"] for a in apps][:2]
    if not names:
        return "Набор"
    joined = " и ".join(names)
    return joined if len(joined) <= 32 else names[0]