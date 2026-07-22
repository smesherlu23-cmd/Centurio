from __future__ import annotations

from . import queries

MODE_KEYS = ("grid", "list")


class ViewState:
    def __init__(self, store):
        self.store = store
        s = store.state()["settings"]
        self.filter = queries.valid_filter(s.get("view_filter") or "all",
                                           store.state()["categories"])
        self.query = ""
        self.sort = s.get("view_sort") if s.get("view_sort") in queries.SORT_KEYS else "alpha"
        self.mode = s.get("view_mode") if s.get("view_mode") in MODE_KEYS else "grid"
        self.sidebar_open = False
        self.selected = -1

    def is_all_view(self):
        return not self.filter.startswith("category:")

    def persist(self):
        self.store.set_setting("view_filter", self.filter)
        self.store.set_setting("view_sort", self.sort)
        self.store.set_setting("view_mode", self.mode)

    def set_filter(self, f):
        self.filter = f
        self.query = ""
        self.selected = -1
        self.persist()

    def set_query(self, q):
        self.query = q
        self.selected = -1

    def set_mode(self, m):
        self.mode = m
        self.persist()

    def set_sort(self, s):
        if s in queries.SORT_KEYS:
            self.sort = s
            self.persist()

    def cycle_sort(self):
        cur = self.sort if self.sort in queries.SORT_KEYS else "alpha"
        self.set_sort(queries.SORT_KEYS[(queries.SORT_KEYS.index(cur) + 1) % len(queries.SORT_KEYS)])

    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open

    def revalidate(self, categories):
        new = queries.valid_filter(self.filter, categories)
        if new != self.filter:
            self.filter = new
            self.persist()

    def move_selection(self, delta, count):
        if not count:
            self.selected = -1
            return
        cur = self.selected if self.selected >= 0 else (-1 if delta > 0 else 0)
        self.selected = max(0, min(count - 1, cur + delta))
