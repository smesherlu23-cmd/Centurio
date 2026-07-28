"""Everything the window knows that isn't in the library file.

The model is the one from the design handoff ("Состояние"): a mode, a screen
inside the library, the two independent queries, the multi-selection, and the
transient bits (inspector, popover, hotkey capture, onboarding).
"""
from __future__ import annotations

from . import queries

MODES = ("hidden", "launch", "library")
SCREENS = ("grid", "add", "settings")


class ViewState:
    def __init__(self, store, mode: str = "library"):
        self.store = store
        state = store.state()
        self.mode = mode if mode in MODES else "library"
        self.screen = "grid"

        # «Запуск»
        self.query = ""
        self.hi = 0                       # активная строка списка

        # «Библиотека»
        self.filter = queries.valid_filter(
            state["settings"].get("view_filter") or "all", state["categories"])
        self.lib_query = ""
        self.sel: list[str] = []          # множественный выбор плиток
        self.anchor: str | None = None    # опора для Shift+клик
        self.inspector: str | None = None
        self.adv = False                  # раскрыты «Параметры запуска»
        self.capture = False              # ждём комбинацию для хоткея
        self.popover: str | None = None   # id категории
        self.icon_query = ""

        # Экран «Найти и добавить»
        self.only_new = True
        self.add_sel: set[str] = set()
        self.add_cat: dict[str, str] = {}  # ручная правка предложенной категории

        self.onboarding = False
        self.onboarding_sel: set[str] = set()

    # ---- режимы ----
    def set_mode(self, mode: str):
        if mode not in MODES:
            return
        self.mode = mode
        if mode == "launch":
            self.hi = 0
        if mode != "library":
            self.close_popover()

    def set_screen(self, screen: str):
        if screen in SCREENS:
            self.screen = screen
            self.inspector = None
            self.clear_selection()

    # ---- «Запуск» ----
    def set_query(self, q: str):
        self.query = q
        self.hi = 0

    def move_hi(self, delta: int, count: int):
        if count <= 0:
            self.hi = 0
            return
        self.hi = max(0, min(count - 1, self.hi + delta))

    # ---- «Библиотека» ----
    def persist(self):
        self.store.set_setting("view_filter", self.filter)

    def set_filter(self, f: str):
        self.filter = f
        self.lib_query = ""
        self.screen = "grid"
        self.inspector = None
        self.clear_selection()
        self.persist()

    def set_lib_query(self, q: str):
        self.lib_query = q
        self.clear_selection()

    def revalidate(self, categories):
        new = queries.valid_filter(self.filter, categories)
        if new != self.filter:
            self.filter = new
            self.persist()
        if self.popover and not any(c["id"] == self.popover for c in categories):
            self.close_popover()

    # ---- выбор ----
    def clear_selection(self):
        self.sel = []
        self.anchor = None

    def select_one(self, app_id: str):
        self.sel = [app_id]
        self.anchor = app_id
        self.inspector = app_id

    def toggle_selection(self, app_id: str):
        """Ctrl+клик: добавить или убрать одну плитку."""
        if app_id in self.sel:
            self.sel = [i for i in self.sel if i != app_id]
        else:
            self.sel = self.sel + [app_id]
        self.anchor = app_id if app_id in self.sel else (self.sel[-1] if self.sel else None)
        self.inspector = self.sel[-1] if self.sel else None

    def add_many(self, app_ids):
        """Add a whole group to the selection without dropping what's there."""
        for app_id in app_ids:
            if app_id not in self.sel:
                self.sel.append(app_id)
        if self.sel:
            self.anchor = self.sel[-1]
            self.inspector = self.sel[-1]

    def select_all(self, ordered_ids: list[str]):
        self.sel = list(ordered_ids)
        self.anchor = ordered_ids[0] if ordered_ids else None
        self.inspector = ordered_ids[-1] if ordered_ids else None

    def drop_missing(self, live_ids):
        """Forget ids the library no longer has (deleted, undone, rescanned)."""
        live = set(live_ids)
        self.sel = [i for i in self.sel if i in live]
        if self.anchor not in live:
            self.anchor = None
        if self.inspector not in live:
            self.inspector = None

    # ---- инспектор ----
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
        """Esc in the library: shed one layer. True if something was closed."""
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
        return False
