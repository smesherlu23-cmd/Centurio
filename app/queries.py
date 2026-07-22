from __future__ import annotations

SORT_KEYS = ("alpha", "recent", "added", "manual")


def valid_filter(f: str, categories: list[dict]) -> str:
    if f and f.startswith("category:"):
        cid = f.split(":", 1)[1]
        if not any(c["id"] == cid for c in categories):
            return "all"
    return f or "all"


def matches(app: dict, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in app["name"].lower() or q in (app.get("sub") or "").lower()


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


def build_sections(apps: list[dict], categories: list[dict], filter: str,
                    query: str, sort: str, running: set) -> list[dict]:
    visible = [a for a in apps if matches(a, query)]
    q = (query or "").strip()
    if q:
        return [{"name": "Результаты поиска", "apps": sort_apps(visible, sort),
                 "editable": False, "cid": None}]
    if filter == "favorites":
        return [{"name": "Избранное",
                 "apps": sort_apps([a for a in visible if a.get("favorite")], sort),
                 "editable": False, "cid": None}]
    if filter == "recent":
        return [{"name": "Недавние", "apps": recent_apps(visible),
                 "editable": False, "cid": None}]
    if filter == "running":
        return [{"name": "Запущено",
                 "apps": sort_apps([a for a in visible if a["id"] in running], sort),
                 "editable": False, "cid": None}]
    if filter.startswith("category:"):
        cid = filter.split(":", 1)[1]
        cat = next((c for c in categories if c["id"] == cid), None)
        return [{"name": cat["name"] if cat else "Категория",
                 "apps": sort_apps([a for a in visible if a.get("category_id") == cid], sort),
                 "editable": bool(cat), "cid": cid}]
    sections = []
    known = set()
    for cat in categories:
        known.add(cat["id"])
        sections.append({"name": cat["name"], "cid": cat["id"], "editable": True,
                         "apps": sort_apps([a for a in visible if a.get("category_id") == cat["id"]], sort)})
    orphan = sort_apps([a for a in visible if a.get("category_id") not in known], sort)
    if orphan:
        sections.append({"name": "Без категории", "apps": orphan, "editable": False, "cid": None})
    return [s for s in sections if s["apps"]]


def flatten_sections(sections: list[dict]) -> list[dict]:
    return [a for sec in sections for a in sec["apps"]]


def current_title(filter: str, query: str, categories: list[dict]) -> str:
    if query:
        return "Поиск"
    return {"all": "Все приложения", "favorites": "Избранное", "recent": "Недавние",
            "running": "Запущено"}.get(filter) or (
        next((c["name"] for c in categories if filter == f"category:{c['id']}"), "Все приложения"))