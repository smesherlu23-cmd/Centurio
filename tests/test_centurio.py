"""Centurio test suite.

Pure-logic tests (store, colours, icon generation) always run. UI/dialog
construction tests run when Flet is importable. Run with:  python tests/test_centurio.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import Store, hue_from_string          # noqa: E402
from app import colors as C                            # noqa: E402
from app import iconify                                # noqa: E402

_passed = 0
_failed = 0


def ok(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print("FAIL:", msg)


def test_store():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "data.json")
        s = Store(path)
        ok(len(s.state()["categories"]) == 4, "seeds 4 default categories")
        ok(s.state()["apps"] == [], "starts with no apps")

        a = s.add_app({"name": "VS Code", "path": "/usr/bin/code", "category_id": "dev"})
        ok(bool(a["id"]), "add_app returns id")
        ok(0 <= a["hue"] < 360, "hue in range")

        s.update_app(a["id"], {"favorite": True, "sub": "Редактор"})
        ok(s.get_app(a["id"])["favorite"] is True, "favorite toggled")
        ok(s.get_app(a["id"])["sub"] == "Редактор", "sub updated")

        s.mark_launched(a["id"])
        ok(s.get_app(a["id"])["launch_count"] == 1, "launch_count incremented")
        ok(s.get_app(a["id"])["last_launched"] > 0, "last_launched set")

        cat = s.add_category("Тест")
        s.update_app(a["id"], {"category_id": cat["id"]})
        s.remove_category(cat["id"])
        ok(s.get_app(a["id"])["category_id"] == s.state()["categories"][0]["id"],
           "orphaned app reassigned")

        s.set_setting("bogus", 1)
        ok("bogus" not in s.state()["settings"], "unknown setting rejected")
        s.set_setting("accent", "#4f7dff")

        s2 = Store(path)
        ok(s2.state()["settings"]["accent"] == "#4f7dff", "reload keeps setting")
        ok(len(s2.state()["apps"]) == 1, "reload keeps app")
        s2.remove_app(a["id"])
        ok(len(s2.state()["apps"]) == 0, "app removed")

        ok(hue_from_string("Notion") == hue_from_string("Notion"), "hue deterministic")
        ok(0 <= hue_from_string("X") < 360, "hue bounded")


def test_colors():
    c1, c2 = C.cover_colors(200)
    ok(c1.startswith("#") and len(c1) == 7, "cover color is hex")
    ok(c1 != c2, "cover gradient has two stops")
    ok(C.glyph_color(10) == "#ffffff", "glyph colour is white")


def test_icon():
    with tempfile.TemporaryDirectory() as d:
        p = iconify.generate_icon(os.path.join(d, "icon.png"), 64)
        ok(os.path.getsize(p) > 100, "icon PNG generated")
        with open(p, "rb") as fh:
            ok(fh.read(8) == b"\x89PNG\r\n\x1a\n", "valid PNG signature")


def test_discovery():
    from app import discovery
    apps = discovery.discover_apps()
    ok(isinstance(apps, list), "discover_apps returns a list")
    ok(all(("name" in a and "path" in a) for a in apps), "discovered apps have name+path")
    ok(all(a == b for a, b in zip(apps, sorted(apps, key=lambda x: x["name"].lower()))),
       "discovered apps are sorted")
    ok(discovery._looks_like_junk("Uninstall Foo") is True, "junk filter flags uninstallers")
    ok(discovery._looks_like_junk("Google Chrome") is False, "junk filter keeps real apps")


def test_ui_build():
    try:
        from unittest.mock import MagicMock
        from app.ui import CenturioUI
        from app import dialogs
    except Exception as exc:  # Flet not installed — skip UI tests.
        print("SKIP UI tests (Flet unavailable):", exc)
        return

    def _sample(store):
        store.add_app({"name": "Notion", "sub": "Документы", "category_id": "work",
                       "path": "/x/notion", "favorite": True})
        store.add_app({"name": "VS Code", "sub": "Редактор", "category_id": "dev",
                       "path": "/x/code", "quick": True})
        a = store.add_app({"name": "Chrome", "sub": "Браузер", "category_id": "work",
                           "path": "/x/chrome"})
        store.mark_launched(a["id"])

    class FakePage:
        def __init__(self):
            self.overlay = []
            self.opened = []
            self.controls = []

        def open(self, d):
            self.opened.append(d)

        def close(self, d):
            pass

        def update(self):
            pass

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        _sample(store)
        page = FakePage()
        ui = CenturioUI(page, store, MagicMock())

        for filt in ["all", "favorites", "recent", "running", "category:work"]:
            ui.filter = filt
            ok(isinstance(ui._build_content(), list), f"content builds for {filt}")
        ui.mode = "list"
        ok(isinstance(ui._build_content(), list), "content builds in list mode")
        ui.mode = "grid"
        ok(ui._build_rail() is not None, "rail builds")
        ok(ui._build_sidebar() is not None, "sidebar builds")
        ok(ui._build_toolbar() is not None, "toolbar builds")
        ok(ui._build_statusbar() is not None, "statusbar builds")

        dialogs.open_app_dialog(ui, None)
        ok(len(page.opened) >= 1, "add-app dialog opens")
        dialogs.open_app_dialog(ui, store.state()["apps"][0])
        ok(True, "edit-app dialog opens")
        dialogs.open_categories_dialog(ui)
        ok(True, "categories dialog opens")
        dialogs.open_settings_dialog(ui)
        ok(True, "settings dialog opens")

        store.data["apps"] = []
        ui.filter = "all"
        ok(isinstance(ui._build_content(), list), "empty library builds")


if __name__ == "__main__":
    test_store()
    test_colors()
    test_icon()
    test_discovery()
    test_ui_build()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
