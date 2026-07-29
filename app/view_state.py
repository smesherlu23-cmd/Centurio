from __future__ import annotations

from . import queries

MODE_KEYS = ("grid", "list")
WINDOWS = ("launch", "library")
SCREENS = ("grid", "add", "settings", "triage")


class ViewState:
    """What the window knows that isn't in the library file.

    The original view (filter/query/sort/mode/selection) is unchanged — the
    library layout it drives didn't change either. Everything below the marker
    is what the redesign added: the second window mode, the screens that
    replaced modal dialogs, the inspector and the context menu.
    """

    def __init__(self, store, window: str = "library"):
        self.store = store
        # One snapshot, not two: store.state() deep-copies the whole library.
        state = store.state()
        s = state["settings"]
        self.filter = queries.valid_filter(s.get("view_filter") or "all",
                                           state["categories"])
        self.query = ""
        self.sort = s.get("view_sort") if s.get("view_sort") in queries.SORT_KEYS else "alpha"
        self.mode = s.get("view_mode") if s.get("view_mode") in MODE_KEYS else "grid"
        self.sidebar_open = True
        self.selected = -1

        # ---- добавлено редизайном ----
        self.window = window if window in WINDOWS else "library"
        self.screen = "grid"

        # «Запуск»
        self.launch_query = ""
        self.hi = 0

        # Инспектор и выбор
        self.inspector: str | None = None
        self.sel: list[str] = []
        self.adv = False
        self.capture = False

        # Поповер категории
        self.popover: str | None = None
        self.icon_query = ""

        # Экран «Найти и добавить»
        self.only_new = True
        self.add_query = ""
        self.manual_path = ""
        self.add_sel: set[str] = set()
        self.add_cat: dict[str, str] = {}

        self.onboarding = False

    def is_all_view(self):
        """True only for the real "all apps" view.

        Drives the rail's "Главное меню" highlight, which used to light up for
        favourites/recent/running too — those are sidebar filters and have
        their own highlight there.
        """
        return self.filter == "all"

    def persist(self):
        # One file write for the three view settings, not three: every click on
        # a filter, a sort or a view mode goes through here.
        self.store.set_setting("view_filter", self.filter, persist=False)
        self.store.set_setting("view_sort", self.sort, persist=False)
        self.store.set_setting("view_mode", self.mode)

    def set_filter(self, f):
        self.filter = f
        self.query = ""
        self.selected = -1
        self.screen = "grid"
        self.close_inspector()
        self.persist()

    def set_query(self, q):
        self.query = q
        self.selected = -1
        self.clear_selection()

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
        if self.popover and not any(c["id"] == self.popover for c in categories):
            self.close_popover()

    def move_selection(self, delta, count):
        if not count:
            self.selected = -1
            return
        cur = self.selected if self.selected >= 0 else (-1 if delta > 0 else 0)
        self.selected = max(0, min(count - 1, cur + delta))

    # ---- окно и экраны ----
    def set_window(self, window: str):
        if window in WINDOWS:
            self.window = window
            if window == "launch":
                self.hi = 0

    def set_screen(self, screen: str):
        if screen in SCREENS:
            self.screen = screen
            self.close_inspector()

    # ---- «Запуск» ----
    def set_launch_query(self, q: str):
        self.launch_query = q
        self.hi = 0

    def move_hi(self, delta: int, count: int):
        if count <= 0:
            self.hi = 0
            return
        self.hi = max(0, min(count - 1, self.hi + delta))

    # ---- выбор плиток ----
    def clear_selection(self):
        self.sel = []

    def select_one(self, app_id: str):
        self.sel = [app_id]
        self.inspector = app_id

    def toggle_selection(self, app_id: str):
        if app_id in self.sel:
            self.sel = [i for i in self.sel if i != app_id]
        else:
            self.sel = self.sel + [app_id]
        self.inspector = self.sel[-1] if self.sel else None

    def select_many(self, app_ids):
        for app_id in app_ids:
            if app_id not in self.sel:
                self.sel.append(app_id)
        if self.sel:
            self.inspector = self.sel[-1]

    def drop_missing(self, live_ids):
        """Forget ids the library no longer has (deleted, undone, rescanned)."""
        live = set(live_ids)
        self.sel = [i for i in self.sel if i in live]
        if self.inspector not in live:
            self.inspector = None
            self.capture = False

    def close_inspector(self):
        self.inspector = None
        self.capture = False
        self.clear_selection()

    # ---- поповер категории ----
    def open_popover(self, cat_id: str):
        self.popover = cat_id
        self.icon_query = ""

    def close_popover(self):
        self.popover = None
        self.icon_query = ""

    # ---- экран добавления ----
    def reset_add(self):
        self.add_sel = set()
        self.add_cat = {}
        self.add_query = ""
        self.manual_path = ""

    def toggle_add(self, key: str):
        if key in self.add_sel:
            self.add_sel.discard(key)
        else:
            self.add_sel.add(key)

    def set_add_group(self, keys, checked: bool):
        for key in keys:
            if checked:
                self.add_sel.add(key)
            else:
                self.add_sel.discard(key)

    def escape(self) -> bool:
        """Esc: shed one layer. True when something was actually closed."""
        if self.popover:
            self.close_popover()
            return True
        if self.capture:
            self.capture = False
            return True
        if self.screen != "grid":
            self.set_screen("grid")
            return True
        if self.inspector or self.sel:
            self.close_inspector()
            return True
        if self.query:
            self.query = ""
            self.selected = -1
            return True
        if self.selected >= 0:
            self.selected = -1
            return True
        return False
