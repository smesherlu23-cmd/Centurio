"""View state: the current filter, search query, sort, display mode, panel
and keyboard-selection state — separate from widget building. ``CenturioUI``
owns one ``ViewState`` and reads it while building controls; ``app/queries.py``
turns (this state + library data) into the actual lists shown.

None of this module touches Flet — it only knows about plain dicts (apps,
categories, settings) and the store, so it can be exercised without a page.
"""
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
        # The bar panel (filters/recents/footer) is independent of the
        # selected filter/category — toggled by its own rail button.
        # Runtime-only: every launch starts with it closed.
        self.sidebar_open = False
        # Keyboard-navigation cursor (index into the flat list of visible apps).
        self.selected = -1

    def is_all_view(self):
        """The 'all applications' family (main-menu rail item): all + its filters."""
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
        """Call after the library changes — a category can be deleted while
        it's the active filter (or the app started with a stale persisted
        one); fall back instead of leaving the UI pointed at a dead view."""
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
