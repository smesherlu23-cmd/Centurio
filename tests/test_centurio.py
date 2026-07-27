"""Centurio test suite.

Pure-logic tests (store, colours, discovery, icon generation) always run;
UI/dialog construction tests run only when Flet is importable and skip
themselves otherwise. Run with:  python tests/test_centurio.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import Store, hue_from_string          # noqa: E402
from app import colors as C                           # noqa: E402
from app import iconify                               # noqa: E402

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

        ok(a.get("track_exe") is None, "track_exe defaults to None")
        s.update_app(a["id"], {"track_exe": "code.exe"})
        ok(s.get_app(a["id"])["track_exe"] == "code.exe", "track_exe updated")

        ok(a.get("poster") is None, "poster defaults to None")
        s.update_app(a["id"], {"poster": "/x/poster.jpg"})
        ok(s.get_app(a["id"])["poster"] == "/x/poster.jpg", "poster updated")

        ok(a.get("working_dir") == "" and a.get("run_as_admin") is False,
           "launch options default empty/false")
        s.update_app(a["id"], {"args": ["--x"], "working_dir": "/tmp", "run_as_admin": True})
        got = s.get_app(a["id"])
        ok(got["args"] == ["--x"] and got["working_dir"] == "/tmp" and got["run_as_admin"] is True,
           "launch options updated")

        b = s.add_app({"name": "Zed", "path": "/z", "category_id": "dev"})
        s.reorder_apps([b["id"], a["id"]])
        ok(s.get_app(b["id"])["order"] == 0 and s.get_app(a["id"])["order"] == 1,
           "reorder_apps assigns order")
        s.remove_app(b["id"])  

        s.set_setting("view_mode", "list")
        s.set_setting("view_filter", "favorites")
        ok(Store(path).state()["settings"]["view_mode"] == "list", "view_mode persisted")
        ok(Store(path).state()["settings"]["view_filter"] == "favorites", "view_filter persisted")

        s.mark_launched(a["id"])
        ok(s.get_app(a["id"])["launch_count"] == 1, "launch_count incremented")
        ok(s.get_app(a["id"])["last_launched"] > 0, "last_launched set")

        cat = s.add_category("Тест")
        ok(cat["icon"] is None and cat["color"] == "#ffffff",
           "new category: letter chip, neutral white colour")
        s.update_category(cat["id"], {"color": "#ff8800", "icon": "sports_esports"})
        got_cat = next(c for c in s.state()["categories"] if c["id"] == cat["id"])
        ok(got_cat["color"] == "#ff8800" and got_cat["icon"] == "sports_esports",
           "category colour + icon updated")

        s.move_category(cat["id"], -1) 
        order_ids = [c["id"] for c in sorted(s.state()["categories"], key=lambda c: c["order"])]
        ok(order_ids.index(cat["id"]) == len(order_ids) - 2, "move_category shifts order")

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


def test_store_concurrency():
    import threading
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "data.json")
        s = Store(path)
        errors = []

        def writer(i):
            try:
                for j in range(40):
                    s.add_app({"name": f"A{i}-{j}", "path": f"/x/{i}/{j}"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ok(not errors, "concurrent writers raise nothing")
        ok(len(s.state()["apps"]) == 240, "every concurrent add is kept in memory")
        ok(len(Store(path).state()["apps"]) == 240, "the file on disk survives concurrent writes")
        leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
        ok(not leftovers, "no temp files are left behind")


def test_store_corrupt_recovery():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "data.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"apps": [ truncated...')

        s = Store(path)
        ok(s.state()["apps"] == [], "a corrupted file falls back to defaults")
        saved = [f for f in os.listdir(d) if f.startswith("centurio-corrupt-")]
        ok(len(saved) == 1, "the unreadable file is quarantined, not discarded")
        with open(os.path.join(d, saved[0]), encoding="utf-8") as fh:
            ok("truncated" in fh.read(), "the quarantined copy keeps the original bytes")

        s.add_app({"name": "After", "path": "/x"})
        ok(len(Store(path).state()["apps"]) == 1, "the store stays usable afterwards")


def test_cdn_circuit_breaker():
    from app import discovery

    discovery.reset_cdn_state()
    ok(discovery._cdn_available() is True, "downloads start out enabled")

    calls = {"n": 0}
    original = discovery._http_get

    def offline(url, timeout=None):
        calls["n"] += 1
        discovery._cdn_record(False)
        return None

    discovery._http_get = offline
    try:
        with tempfile.TemporaryDirectory() as cache:
            ok(discovery._steam_cdn_art("730", cache) is None, "art lookup fails while offline")
            tripped_after = calls["n"]
            ok(tripped_after <= discovery._CDN_MAX_FAILURES,
               "the breaker trips without exhausting every host/name combination")
            ok(discovery._cdn_available() is False, "repeated network errors disable downloads")

            ok(discovery._steam_cdn_art("999", cache) is None, "further lookups still fail")
            ok(calls["n"] == tripped_after, "a tripped breaker issues no further requests")

            discovery.reset_cdn_state()
            ok(discovery._cdn_available() is True, "an explicit rescan re-enables downloads")

            # A miss (server reachable, art absent) must not be retried either.
            def not_found(url, timeout=None):
                calls["n"] += 1
                discovery._cdn_record(True)
                return None

            discovery._http_get = not_found
            discovery._steam_cdn_art("555", cache)
            after_first = calls["n"]
            discovery._steam_cdn_art("555", cache)
            ok(calls["n"] == after_first, "a known miss is cached for the session")
    finally:
        discovery._http_get = original
        discovery.reset_cdn_state()


def test_hotkey_rejection():
    """A single bad accelerator must not take the other hotkeys down with it.

    Exercises the mapping builder directly: starting a real GlobalHotKeys
    listener would need a display and could hang a headless run.
    """
    from app.hotkeys import HotkeyManager

    class FakeHotKey:
        @staticmethod
        def parse(combo):
            for part in combo.split("+"):
                if part.startswith("<") and part.endswith(">"):
                    name = part[1:-1]
                    if not (name in {"ctrl", "alt", "shift", "cmd", "space", "enter"}
                            or (name.startswith("f") and name[1:].isdigit())):
                        raise ValueError(combo)
                elif len(part) != 1:
                    raise ValueError(combo)
            return combo

    class FakeKeyboard:
        HotKey = FakeHotKey

    mgr = HotkeyManager(on_trigger=lambda _aid: None)
    kb = FakeKeyboard()

    mapping, rejected = mgr._build_mapping(
        kb, [("Ctrl+Shift+G", "good"), ("Ctrl+Пробел", "bad"), ("F8", "also-good")])
    ok(rejected == ["Ctrl+Пробел"], "only the unparseable accelerator is rejected")
    ok(len(mapping) == 2, "the surviving hotkeys are still registered")
    ok("<ctrl>+<shift>+g" in mapping and "<f8>" in mapping, "good combos keep their pynput spelling")

    mapping, rejected = mgr._build_mapping(kb, [("Ctrl+G", "one"), ("ctrl+g", "two")])
    ok(rejected == ["ctrl+g"], "a duplicate accelerator is rejected, not silently overwritten")
    ok(len(mapping) == 1, "the first binding of a duplicated combo wins")

    mapping, rejected = mgr._build_mapping(kb, [(None, "x"), ("", "y")])
    ok(not mapping and not rejected, "empty accelerators are skipped quietly")


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
    ok(discovery._is_windows_system("Character Map", r"C:\WINDOWS\system32\charmap.exe") is True,
       "system filter drops Windows-dir tools")
    ok(discovery._is_windows_system("Node.js", r"C:\Program Files\nodejs\node.exe") is True,
       "system filter drops runtimes like Node.js")
    ok(discovery._is_windows_system("Google Chrome", r"C:\Program Files\Google\Chrome\chrome.exe") is False,
       "system filter keeps real apps")
    ok(discovery._vdf_val('"appid" "570" "name" "Dota 2"', "appid") == "570", "vdf value parsed")
    ok(discovery._vdf_val("nothing", "name") is None, "vdf missing key -> None")
    ok("228980" in discovery._STEAM_SKIP_ID, "steam redistributables skipped")
    ic, fit = discovery.resolve_icon_for("steam://rungameid/99999999")
    ok(ic is None and fit == "contain", "resolve_icon_for: missing steam art -> None/contain")
    ok(discovery.resolve_icon_for("")[0] is None, "resolve_icon_for: empty path -> None")

    with tempfile.TemporaryDirectory() as d:
        lib = os.path.join(d, "steamapps")
        os.makedirs(lib)
        with open(os.path.join(lib, "appmanifest_730.acf"), "w") as fh:
            fh.write('"AppState"{ "appid" "730" "name" "Counter-Strike 2" }')
        discovery._steam_roots = lambda: [d]
        games = discovery._steam_games(None)
        ok(games and games[0]["sub"] == "Steam", "steam games carry sub='Steam'")
        ok(games and "track_exe" in games[0], "steam games carry a track_exe field")
        ok(games and "poster" in games[0], "steam games carry a poster field")


    with tempfile.TemporaryDirectory() as d:
        lc = os.path.join(d, "appcache", "librarycache")
        os.makedirs(lc)
        with open(os.path.join(lc, "730_library_600x900.jpg"), "wb") as fh:
            fh.write(b"\0" * 2048)
        ok(discovery._steam_portrait(d, "730") == os.path.join(lc, "730_library_600x900.jpg"),
           "steam portrait: local library_600x900 found")
        ok(discovery._steam_portrait(d, "999") is None, "steam portrait: missing -> None")
    ok(discovery.poster_for("C:/x/app.exe") is None, "poster_for: non-steam path -> None")


    deduped = discovery._dedupe([{"name": "CS2", "path": "steam://rungameid/730",
                                  "sub": "Steam", "source": "steam", "track_exe": "cs2.exe",
                                  "poster": "/x/p.jpg"}])
    ok(deduped[0]["sub"] == "Steam", "_dedupe preserves sub field")
    ok(deduped[0]["track_exe"] == "cs2.exe", "_dedupe preserves track_exe field")
    ok(deduped[0]["poster"] == "/x/p.jpg", "_dedupe preserves poster field")

    with tempfile.TemporaryDirectory() as d:
        gdir = os.path.join(d, "steamapps", "common", "Portal")
        os.makedirs(gdir)
        for fn, size in [("portal.exe", 500), ("bigtool.exe", 9000),
                         ("vcredist_x64.exe", 8000), ("crashhandler.exe", 100)]:
            with open(os.path.join(gdir, fn), "wb") as fh:
                fh.write(b"\0" * size)
        ok(discovery._steam_game_exe(d, "Portal", "Portal") == "portal.exe",
           "steam exe: name-matching exe chosen over bigger unrelated exe")
    with tempfile.TemporaryDirectory() as d:
        gdir = os.path.join(d, "steamapps", "common", "Mystery")
        os.makedirs(gdir)
        for fn, size in [("game.exe", 7000), ("unins000.exe", 9000), ("tiny.exe", 10)]:
            with open(os.path.join(gdir, fn), "wb") as fh:
                fh.write(b"\0" * size)
        ok(discovery._steam_game_exe(d, "Mystery", "Mystery") == "game.exe",
           "steam exe: largest non-junk exe is the fallback")
    ok(discovery._steam_game_exe("/x", None, "n") is None, "steam exe: no installdir -> None")

    for name, tmpl, subs in [
        ("_WIN_PS", discovery._WIN_PS, {"__DIRS__": "'C:\\x'", "__CACHE__": "'C:\\c'"}),
        ("_WIN_ICON_ONE_PS", discovery._WIN_ICON_ONE_PS, {"__CACHE__": "'C:\\c'", "__EXE__": "'C:\\a.exe'"}),
    ]:
        s = tmpl
        for k, v in subs.items():
            s = s.replace(k, v)
        ok(s.count("{") == s.count("}"), f"{name}: braces balanced")
        ok(s.count('@"') == s.count('"@'), f"{name}: here-strings balanced")
        remaining = [k for k in ("__DIRS__", "__CACHE__", "__EXE__") if k in s]
        ok(not remaining, f"{name}: all placeholders substituted")

    store2 = Store(os.path.join(tempfile.mkdtemp(), "d.json"))
    a = store2.add_app({"name": "CS2", "path": "steam://rungameid/730", "icon": "/fake/cover.jpg"})
    ok(not a.get("sub"), "precondition: no sub yet")
    discovery._steam_roots = lambda: [] 
    changed = discovery.backfill_icons(store2, None)
    ok(changed and store2.get_app(a["id"])["sub"] == "Steam",
       "backfill_icons fixes sub even when icon already present")


def test_hotkeys():
    from app.hotkeys import to_pynput, quick_bindings
    ok(to_pynput("Ctrl+Shift+1") == "<ctrl>+<shift>+1", "hotkey -> pynput format")
    ok(to_pynput("Alt+G") == "<alt>+g", "hotkey letter")
    ok(to_pynput("F5") == "<f5>", "hotkey F-key")
    apps = [{"id": "a", "quick": True, "hotkey": None},
            {"id": "b", "quick": True, "hotkey": "Ctrl+Shift+X"},
            {"id": "c", "quick": True, "hotkey": None}]
    binds = dict((aid, acc) for acc, aid in quick_bindings(apps))
    ok(binds["b"] == "Ctrl+Shift+X", "explicit hotkey kept")
    ok(binds["a"] == "Ctrl+1" and binds["c"] == "Ctrl+2", "auto Ctrl+N assigned")


def test_launcher_index():
    from app.launcher import Launcher
    lch = Launcher()
    lch.set_apps([{"id": "1", "path": r"C:\x\chrome.exe"},
                  {"id": "2", "path": "steam://rungameid/730"},
                  {"id": "3", "path": r"C:\tools\vim.bat"}])
    keys = set(lch._exe_index)
    ok("chrome.exe" in keys and "vim.bat" in keys, "exe index built (Windows exe/bat)")
    ok(all("steam" not in k for k in keys), "URL launchers excluded from index")

    lch.set_apps([{"id": "g", "path": "steam://rungameid/730", "track_exe": "cs2.exe"},
                  {"id": "h", "path": "C:/x/Chrome.exe", "track_exe": None}])
    idx = lch._exe_index
    ok(idx.get("cs2.exe") == {"g"}, "URL game indexed by track_exe")
    ok(idx.get("chrome.exe") == {"h"}, "file app still indexed by path basename")


def test_color_parsing():
    ok(C.parse_hex("#ff8800") == "#ff8800", "hex parsed")
    ok(C.parse_hex("ff8800") == "#ff8800", "hex without # parsed")
    ok(C.parse_hex("#f80") == "#ff8800", "short hex expanded")
    ok(C.parse_hex("rgb(255, 136, 0)") == "#ff8800", "rgb() parsed")
    ok(C.parse_hex("255,136,0") == "#ff8800", "r,g,b parsed")
    ok(C.parse_hex("nonsense") is None, "bad colour -> None")
    ok(C.hex_to_rgb("#ff8800") == (255, 136, 0), "hex_to_rgb")
    ok(C.rgb_to_hex(255, 136, 0) == "#ff8800", "rgb_to_hex")
    ok(C.rgb_to_hex(999, -5, 0) == "#ff0000", "rgb_to_hex clamps")
    ok(C.category_color({"color": "#123456"}) == "#123456", "category_color uses explicit hex")
    derived = C.category_color({"name": "Игры"})
    ok(derived.startswith("#") and len(derived) == 7, "category_color derives from name")


def test_launch_options():
    from app.launcher import Launcher
    lch = Launcher()
    ok(lch._as_args("--a b") == ["--a", "b"], "string args split")
    ok(lch._as_args(["--x", "y"]) == ["--x", "y"], "list args preserved")
    ok(lch._as_args(None) == [], "no args -> empty")
    with tempfile.TemporaryDirectory() as d:
        ok(lch._work_dir({"working_dir": d}, r"C:\x\app.exe") == d, "working_dir honoured")
        bad = lch._work_dir({"working_dir": "/no/such/dir"}, os.path.join(d, "app.exe"))
        ok(bad == d, "invalid working_dir falls back to exe folder")
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
        exe = tf.name
    try:
        res = lch.launch({"id": "x", "path": exe, "run_as_admin": True})
        ok(res.get("ok") is False, "run_as_admin degrades gracefully off-Windows")
    finally:
        os.unlink(exe)


def test_data_ops():
    with tempfile.TemporaryDirectory() as d:
        s = Store(os.path.join(d, "data.json"))
        s.add_app({"name": "One", "path": "/one", "category_id": "work"})
        s.add_category("Мои игры")
        exp = s.export_data(os.path.join(d, "out.json"))
        ok(os.path.exists(exp), "export writes a file")

        s2 = Store(os.path.join(d, "data2.json"))
        ok(s2.import_data(exp) is True, "import loads exported data")
        ok(len(s2.state()["apps"]) == 1, "imported apps present")
        ok(any(c["name"] == "Мои игры" for c in s2.state()["categories"]), "imported categories present")
        ok(s2.import_data(os.path.join(d, "nope.json")) is False, "import of missing file -> False")

        bak = s.backup()
        ok(os.path.exists(bak) and "backup" in bak.name, "backup file created")


def test_log():
    import importlib

    from app import log as _log
    importlib.reload(_log)  
    import logging
    with tempfile.TemporaryDirectory() as d:
        _log.setup(debug=True, log_dir=d)
        _log._LOGGER.handlers = [h for h in _log._LOGGER.handlers
                                 if isinstance(h, logging.FileHandler)]
        try:
            raise ValueError("boom")
        except ValueError:
            _log.exception("handled test error")
        _log.debug("a debug line")
        ok(os.path.exists(os.path.join(d, "centurio.log")), "debug log file created")
        with open(os.path.join(d, "centurio.log"), encoding="utf-8") as fh:
            body = fh.read()
        ok("handled test error" in body and "boom" in body, "exception logged with traceback")


def test_queries():
    from app import queries
    from app.view_state import ViewState

    cats = [{"id": "work", "name": "Work", "order": 0}, {"id": "games", "name": "Games", "order": 1}]
    apps = [
        {"id": "1", "name": "Notion", "category_id": "work", "favorite": True, "last_launched": 100},
        {"id": "2", "name": "Chrome", "category_id": "work", "last_launched": 200},
        {"id": "3", "name": "CS2", "category_id": "games"},
        {"id": "4", "name": "Orphan", "category_id": "missing"},
    ]
    running = {"2"}

    ok(queries.valid_filter("category:missing", cats) == "all", "valid_filter drops a dead category")
    ok(queries.valid_filter("category:work", cats) == "category:work", "valid_filter keeps a live category")
    ok(queries.valid_filter("favorites", cats) == "favorites", "valid_filter passes non-category filters through")

    fav = queries.build_sections(apps, cats, "favorites", "", "alpha", running)
    ok([a["id"] for a in fav[0]["apps"]] == ["1"], "favorites section holds only favourited apps")

    run = queries.build_sections(apps, cats, "running", "", "alpha", running)
    ok([a["id"] for a in run[0]["apps"]] == ["2"], "running section matches the running-ids set")

    rec = queries.build_sections(apps, cats, "recent", "", "alpha", running)
    ok([a["id"] for a in rec[0]["apps"]] == ["2", "1"], "recent section sorts by last_launched, newest first")

    cat_sec = queries.build_sections(apps, cats, "category:games", "", "alpha", running)
    ok([a["id"] for a in cat_sec[0]["apps"]] == ["3"], "category section holds only that category's apps")

    all_sec = queries.build_sections(apps, cats, "all", "", "alpha", running)
    ok("Без категории" in [s["name"] for s in all_sec],
       "an app whose category was deleted gets its own section instead of being dropped")

    search = queries.build_sections(apps, cats, "all", "chrome", "alpha", running)
    ok(len(search) == 1 and search[0]["apps"][0]["id"] == "2", "a search query overrides the active filter")

    ok(queries.current_title("category:games", "", cats) == "Games", "current_title resolves a category name")
    ok(queries.current_title("all", "x", cats) == "Поиск", "current_title shows search state over the filter")

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_category("Work")
        wid = store.state()["categories"][0]["id"]
        store.set_setting("view_filter", f"category:{wid}")
        vs = ViewState(store)
        ok(vs.filter == f"category:{wid}", "ViewState restores a persisted, still-valid filter")

        vs.set_filter("favorites")
        ok(store.state()["settings"]["view_filter"] == "favorites", "set_filter persists immediately")

        vs.move_selection(1, 3)
        ok(vs.selected == 0, "move_selection picks the first item from nothing selected")
        vs.move_selection(1, 3)
        ok(vs.selected == 1, "move_selection advances by one")
        vs.move_selection(-5, 3)
        ok(vs.selected == 0, "move_selection clamps at the start")

        vs.set_filter(f"category:{wid}")
        store.data["categories"] = []
        vs.revalidate(store.state()["categories"])
        ok(vs.filter == "all", "revalidate falls back once the active category is gone")


def test_ui_build():
    try:
        from unittest.mock import MagicMock
        from app.ui import CenturioUI
        from app import dialogs
    except Exception as exc: 
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

    import shutil
    import time as _time

    d = tempfile.mkdtemp()
    try:
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

        poster_png = iconify.generate_icon(os.path.join(d, "poster.png"), 48)
        store.add_app({"name": "Half-Life", "path": "steam://rungameid/70",
                       "poster": str(poster_png), "category_id": "games"})
        ui.filter = "all"
        ok(ui._use_poster(store.state()["apps"][-1]) is True, "game with poster uses poster tile")
        ok(isinstance(ui._build_content(), list), "content builds with poster tiles")
        ui.selected = -1
        ui.move_selection(1)
        ok(ui.selected == 0, "keyboard nav selects first app")
        ui.move_selection(-5)
        ok(ui.selected == 0, "keyboard nav clamps at start")
        ui.activate_selected()
        ok(True, "activate_selected launches without error")
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
        dialogs._open_category_editor(ui, store.state()["categories"][0], lambda: None)
        ok(True, "category editor (colour + icon pack) opens")
        ok(ui._cat_glyph(store.state()["categories"][0]) is not None, "category glyph builds")
        dialogs.open_settings_dialog(ui)
        ok(True, "settings dialog opens")
        ids = [a["id"] for a in store.state()["apps"]]
        if len(ids) >= 2:
            ui._reorder_app(store.state()["apps"], ids[1], ids[0])
            ok(ui.sort == "manual", "reorder switches to manual sort")
        ui._move_app_to_category(ids[0], store.state()["categories"][-1]["id"])
        ok(True, "move-to-category runs")
        dialogs.open_context_menu(ui, store.state()["apps"][0])
        ok(True, "context menu opens")
        dialogs.confirm(ui, "T", "M", "OK", lambda: None)
        ok(True, "confirm dialog opens")

        store.data["apps"] = []
        ui.filter = "all"
        ok(isinstance(ui._build_content(), list), "empty library builds")

        from app.ui import img_b64, app_hue
        icon_png = iconify.generate_icon(os.path.join(d, "t.png"), 32)
        ok(isinstance(img_b64(str(icon_png)), str), "img_b64 encodes a PNG")
        ok(img_b64("/no/such.png") is None, "img_b64 missing -> None")
        ok(img_b64("/x/foo.svg") is None, "img_b64 skips non-raster")
        ok(0 <= app_hue({"name": "X"}) < 360, "app_hue falls back to name hue")
    finally:
        _time.sleep(0.4) 
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    test_store()
    test_store_concurrency()
    test_store_corrupt_recovery()
    test_cdn_circuit_breaker()
    test_hotkey_rejection()
    test_colors()
    test_icon()
    test_discovery()
    test_hotkeys()
    test_launcher_index()
    test_color_parsing()
    test_launch_options()
    test_data_ops()
    test_log()
    test_queries()
    test_ui_build()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
