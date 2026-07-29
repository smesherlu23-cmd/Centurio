"""Centurio test suite.

Pure-logic tests (store, colours, discovery, icon generation) always run;
UI/dialog construction tests run only when Flet is importable and skip
themselves otherwise. Run with:  python tests/test_centurio.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    import flet as ft
except Exception:            # проверяется отдельно, тесты интерфейса пропустятся
    ft = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import Store, hue_from_string          # noqa: E402
from app import colors as C                           # noqa: E402
from app import iconify                               # noqa: E402

_passed = 0
_failed = 0
_skipped: list[str] = []


def ok(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print("FAIL:", msg)


def skip(name, reason):
    """Record a Flet-unavailable skip.

    A bare print() here used to let a broken Flet install pass CI silently —
    three UI tests would print "SKIP" and the run still exited 0. _summarize()
    below turns any skip into a failure when running under CI, since the
    workflow installs Flet as a hard requirement and a skip there means
    something is actually wrong, not "Flet isn't installed, which is fine for
    a local logic-only run."
    """
    _skipped.append(name)
    print(f"SKIP {name} (Flet unavailable):", reason)


def _summarize(passed: int, failed: int, skipped: list[str], is_ci: bool) -> tuple[int, str]:
    """Turn the run's counters into (exit_code, report_line).

    Pulled out of the __main__ block so the CI-escalation rule — any skip
    under CI is a failure — is itself testable, not just exercised by the
    one real run of this file. Reports by returning, never by printing: the
    escalation branch used to print "FAIL: ..." as a side effect, so the test
    that exercises it stamped a fake failure into the log of a green run.
    """
    note = ""
    if skipped and is_ci:
        failed += 1
        note = (f"\nFAIL: {len(skipped)} test(s) skipped under CI (Flet should be installed "
                f"here): {', '.join(skipped)}")
    line = f"{passed} passed, {failed} failed" + (f", {len(skipped)} skipped" if skipped else "")
    return (1 if failed else 0), line + note


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
        ok(cat["color"] == "#ffffff", "a new category starts with the neutral colour")
        ok(C.category_color(cat) in C.CAT_PALETTE,
           "which the palette turns into something visible on the rail")
        s.update_category(cat["id"], {"color": "#ff8800", "icon": "sports_esports"})
        got_cat = next(c for c in s.state()["categories"] if c["id"] == cat["id"])
        ok(got_cat["color"] == "#ff8800" and got_cat["icon"] == "sports_esports",
           "category colour + icon updated")

        s.move_category(cat["id"], -1) 
        order_ids = [c["id"] for c in sorted(s.state()["categories"], key=lambda c: c["order"])]
        ok(order_ids.index(cat["id"]) == len(order_ids) - 2, "move_category shifts order")

        s.update_app(a["id"], {"category_id": cat["id"]})
        undo = s.remove_category(cat["id"])
        ok(undo is not None, "remove_category reports what it removed")
        ok(s.get_app(a["id"])["category_id"] == s.state()["categories"][0]["id"],
           "orphaned app reassigned")

        s.set_setting("bogus", 1)
        ok("bogus" not in s.state()["settings"], "unknown setting rejected")
        s.set_setting("accent", "#4f7dff")

        # set_setting used to hand back the live settings dict, so a caller
        # could edit the store's state behind the lock and without a write.
        returned = s.set_setting("tile_size", "compact")
        returned["tile_size"] = "mutated-from-outside"
        ok(s.state()["settings"]["tile_size"] == "compact",
           "mutating set_setting's return value doesn't reach the store")

        s2 = Store(path)
        ok(s2.state()["settings"]["accent"] == "#4f7dff", "reload keeps setting")
        ok(len(s2.state()["apps"]) == 1, "reload keeps app")
        s2.remove_app(a["id"])
        ok(len(s2.state()["apps"]) == 0, "app removed")

        ok(hue_from_string("Notion") == hue_from_string("Notion"), "hue deterministic")
        ok(0 <= hue_from_string("X") < 360, "hue bounded")


def test_store_sets_inbox_undo():
    """Наборы, очередь разбора и обратимость — то, что добавил редизайн."""
    with tempfile.TemporaryDirectory() as d:
        s = Store(os.path.join(d, "data.json"))
        one = s.add_app({"name": "Notion", "path": "/x/n", "category_id": "work"})
        two = s.add_app({"name": "Figma", "path": "/x/f", "category_id": "create"})

        rec = s.add_set("Рабочее утро", [one["id"], two["id"], "no-such-app"])
        ok(rec is not None and rec["apps"] == [one["id"], two["id"]],
           "a set keeps only ids the library actually has")
        ok(rec["quick"] is True, "and lands in the quick-launch strip by default")
        ok(s.add_set("Пустой", ["ghost"]) is None, "a set with nothing real in it isn't stored")

        gone = s.remove_apps([one["id"]])
        ok([g["id"] for g in gone] == [one["id"]], "remove_apps hands back what it removed")
        ok(s.state()["sets"][0]["apps"] == [two["id"]],
           "a removed app leaves the sets it was in")
        ok(s.restore_apps(gone) == 1, "the record goes back in")
        ok(s.restore_apps(gone) == 0, "restoring twice doesn't duplicate it")

        ok(s.update_apps([one["id"], two["id"]], {"favorite": True}) == 2,
           "update_apps patches every id it was given in one write")

        undo = s.remove_category("create")
        ok(undo and two["id"] in undo["apps"], "remove_category reports the apps it moved")
        ok(s.restore_category(undo) is True, "and the category can be put back")
        ok(s.get_app(two["id"])["category_id"] == "create", "with its apps in it")

        # ---- очередь разбора ----
        added = s.queue_inbox([
            {"name": "OBS", "path": "C:/obs.exe", "source": "startmenu"},
            {"name": "Notion", "path": "/x/n"},          # уже в библиотеке
            {"name": "OBS again", "path": "C:/obs.exe"},  # уже в очереди
        ])
        ok(added == 1, "queueing skips what the library and the queue already know")
        item = s.state()["inbox"][0]
        taken = s.take_inbox(item["id"])
        ok(taken and taken["name"] == "OBS", "an entry can be taken out of the queue")
        ok(not s.state()["inbox"], "and it is gone from it")
        ok(s.restore_inbox(taken) is True, "putting it back works")
        ok(s.restore_inbox(taken) is False, "but only once")

        s.queue_inbox([{"name": "Krita", "path": "C:/krita.exe"}])
        cleared = s.clear_inbox()
        ok(len(cleared) == 2 and not s.state()["inbox"], "«Отложить всё» empties the queue")
        for entry in cleared:
            s.restore_inbox(entry)
        ok(len(s.state()["inbox"]) == 2, "and every entry can be restored")

        # Программа, добавленная в библиотеку, не должна остаться в очереди.
        s.add_app({"name": "Krita", "path": "C:/krita.exe", "category_id": "work"})
        s.flush()
        ok(len(Store(s.path).state()["inbox"]) == 1,
           "on load the queue drops what has since been added")

        s.data["sets"] = [{"id": "dead", "name": "Dead", "apps": ["ghost"]}]
        s.flush()
        ok(Store(s.path).state()["sets"] == [],
           "a set that lost every member is dropped on load")


def test_discovery_sources():
    """Найденное помечается источником и умеет докладывать об ошибках."""
    from app import discovery

    source = _read("app", "discovery.py")
    ok("'startmenu'" in source, "the Start Menu pass tags what it finds")
    ok("'registry'" in source, "and so do the uninstall and App Paths passes")

    merged = discovery._dedupe([
        {"name": "A", "path": "C:/a.exe", "source": "startmenu"},
        {"name": "A", "path": "C:/a.exe", "source": "registry", "icon": "/i.png"},
    ])
    ok(len(merged) == 1, "the same program from two sources is one entry")
    ok(merged[0]["source"] == "startmenu", "the first source it was seen in wins")
    ok(merged[0]["icon"] == "/i.png", "and an icon from the second is still adopted")

    report = {}
    discovery.discover_apps(None, report=report)
    ok("errors" in report, "a scan reports which sources failed")

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "Desktop"))
        with open(os.path.join(d, "Desktop", "Visual Studio Code.lnk"), "w") as fh:
            fh.write("x")
        old = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = d
        try:
            ok("visualstudiocode" in discovery.desktop_names(),
               "a desktop shortcut is recognised by name")
            picked = discovery.suggest_first_run([
                {"name": "Visual Studio Code", "path": "C:/x.exe", "source": "registry"},
                {"name": "Nothing", "path": "C:/y.exe", "source": "startmenu"}])
            ok(picked and picked[0]["hint"] == "на рабочем столе",
               "and is offered first, with the reason it was picked")
            ok(picked[1]["hint"] == "в меню «Пуск»",
               "the rest are honestly labelled, not guessed at")
        finally:
            if old is None:
                os.environ.pop("USERPROFILE", None)
            else:
                os.environ["USERPROFILE"] = old


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


def test_store_load_validation():
    """JSON that parses but carries junk must not blank the window.

    Corrupt files are quarantined by _load; this is the other half — records
    the UI indexes without a guard (id, name) or sorts on (order, added_at).
    """
    import json

    from app.store import DEFAULT_SETTINGS

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "data.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "version": "one",
                "categories": [{"id": "work", "name": "Работа", "order": 0},
                               {"name": "no id at all"},
                               "not even a dict",
                               {"id": "dup", "name": "First"},
                               {"id": "dup", "name": "Second"}],
                "apps": [
                    {"id": "good", "name": "Notion", "path": "/n", "order": 1},
                    {"name": "no id"},
                    {"id": "", "name": "empty id"},
                    None,
                    {"id": "nameless", "path": "/x"},
                    {"id": "junk-numbers", "name": "Junk", "order": "first",
                     "added_at": None, "last_launched": "yesterday", "hue": "blue"},
                    {"id": "good", "name": "Duplicate id"},
                ],
                "settings": ["not", "an", "object"],
            }, fh)

        state = Store(path).state()
        apps = [a for a in state["apps"] if isinstance(a, dict)]
        ok([a.get("id") for a in apps] == ["good", "nameless", "junk-numbers"],
           "unusable app records are dropped")
        ok(all(isinstance(a.get("name"), str) and a.get("name") for a in apps),
           "every surviving app has a usable name")
        by_id = {a.get("id"): a for a in apps}
        ok(by_id.get("nameless", {}).get("name") == "Без названия",
           "a nameless record gets the same placeholder as a new app")
        junk = by_id.get("junk-numbers", {})
        ok(all(isinstance(junk.get(k), int) for k in ("order", "added_at", "last_launched")),
           "non-numeric sort keys are coerced")
        ok(isinstance(junk.get("hue"), int) and 0 <= junk.get("hue", -1) < 360,
           "a bad hue is re-derived")
        cats = [c for c in state["categories"] if isinstance(c, dict)]
        ok([c.get("id") for c in cats] == ["work", "dup"],
           "unusable categories are dropped and ids deduped")
        ok(state["settings"] == dict(DEFAULT_SETTINGS),
           "settings that aren't an object fall back to the defaults")
        ok(state["version"] == 2, "the loaded file reports the current schema version")
        ok(state["sets"] == [] and state["inbox"] == [],
           "a file written before sets and triage existed loads with both empty")

        # set_setting() has always refused an unknown key (see "unknown setting
        # rejected" in test_store above); loading used to let one straight
        # through instead of filtering it the same way.
        path2 = os.path.join(d, "data2.json")
        with open(path2, "w", encoding="utf-8") as fh:
            json.dump({"apps": [], "settings": {"accent": "#123456", "legacy_flag_removed": True}},
                      fh)
        settings2 = Store(path2).state()["settings"]
        ok(settings2["accent"] == "#123456", "a known setting from disk is kept")
        ok("legacy_flag_removed" not in settings2,
           "an unknown key from disk is dropped, matching what set_setting() would do")
        ok(set(settings2) == set(DEFAULT_SETTINGS), "the settings schema is exactly the known keys")

        # The sanitised library must survive the operations the UI performs.
        from app import queries
        sections = queries.build_sections(state["apps"], state["categories"], "all", "", "alpha", set())
        ok(queries.flatten_sections(sections), "sanitised records render into sections")
        for sort in queries.SORT_KEYS:
            queries.sort_apps(state["apps"], sort)
        ok(True, "every sort order works on the sanitised records")


def test_store_write_failure():
    """A failing save must not take down the action that triggered it."""
    import builtins
    import contextlib

    real_open = builtins.open

    @contextlib.contextmanager
    def disk_full(store):
        def failing_open(file, *a, **kw):
            if str(file).startswith(str(store.path)):
                raise OSError(28, "No space left on device")
            return real_open(file, *a, **kw)

        builtins.open = failing_open
        try:
            yield
        finally:
            builtins.open = real_open

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "data.json")
        s = Store(path)
        s.add_app({"name": "Before", "path": "/b"})

        reported = []
        s.on_error = reported.append
        with disk_full(s):
            try:
                app, raised = s.add_app({"name": "During outage", "path": "/x"}), None
            except Exception as exc:
                app, raised = None, exc
            ok(raised is None, "a failing save doesn't propagate out of add_app")
            ok(app and app["name"] == "During outage",
               "add_app still returns its record when the save fails")
            ok(s.flush() is False, "flush reports the failure")
            ok(len(reported) == 1, "only the first failure of a streak is reported")
            ok("No space left" in reported[0], "the reported message carries the OS error")
            ok(s.write_error is not None, "the failure is remembered")
            ok(len(s.state()["apps"]) == 2, "the in-memory library keeps the change")
            ok(not any(n.endswith(".tmp") for n in os.listdir(d)), "no temp file is left behind")

        ok(s.flush() is True, "a later save succeeds again")
        ok(s.write_error is None, "the remembered failure is cleared")
        ok(len(Store(path).state()["apps"]) == 2, "the recovered save reaches disk")

        broken = Store(os.path.join(d, "other.json"))
        broken.on_error = lambda msg: 1 / 0
        with disk_full(broken):
            ok(broken.flush() is False, "a throwing error callback doesn't break the save path")


def test_store_batched_writes():
    """Bulk paths write the file once, not once per record."""
    from app import discovery
    from app.view_state import ViewState

    with tempfile.TemporaryDirectory() as d:
        s = Store(os.path.join(d, "data.json"))
        for i in range(20):
            s.add_app({"name": f"Game{i}", "path": f"steam://rungameid/{i}"})

        writes = {"n": 0}
        real_persist = s._persist

        def counting_persist():
            writes["n"] += 1
            return real_persist()
        s._persist = counting_persist

        changed = discovery.backfill_icons(s, None)
        ok(changed is True, "backfill patches the steam apps")
        ok(writes["n"] == 1, "backfilling 20 apps writes the file once, not 20 times")
        ok(all(a.get("sub") == "Steam" for a in Store(os.path.join(d, "data.json")).state()["apps"]),
           "the batched changes reach disk")

        writes["n"] = 0
        ok(discovery.backfill_icons(s, None) is False, "a second backfill has nothing to do")
        ok(writes["n"] == 0, "an unchanged backfill doesn't write at all")

        writes["n"] = 0
        ViewState(s).persist()
        ok(writes["n"] == 1, "the three view settings are stored in one write")

        writes["n"] = 0
        s.update_app(s.state()["apps"][0]["id"], {"favorite": True})
        ok(writes["n"] == 1, "a single update still writes immediately")


def test_image_cache_bounded():
    """The base64 caches used to keep every image the session ever touched."""
    try:
        from app import images
    except Exception as exc:  # flet only — a missing ceiling must not skip
        skip("image cache test", exc)
        return
    _IMG_B64_CACHE, _LruCache, img_b64 = (images._IMG_B64_CACHE, images._LruCache, images.img_b64)

    cache = _LruCache(max_entries=3)
    for i in range(10):
        cache.put(f"k{i}", 1.0, f"v{i}", 1)
    ok(len(cache) == 3, "the entry ceiling is enforced")
    ok(cache.get("k9", 1.0) == "v9" and cache.get("k0", 1.0) is None,
       "the least recently used entries are the ones evicted")
    ok(cache.get("k9", 2.0) is None, "a changed mtime invalidates the entry")

    byte_capped = _LruCache(max_entries=100, max_bytes=10)
    for i in range(5):
        byte_capped.put(f"k{i}", 1.0, "x" * 4, 4)
    ok(len(byte_capped) <= 3, "the byte ceiling is enforced independently of the count")

    ok(_IMG_B64_CACHE.max_entries <= 1024 and bool(_IMG_B64_CACHE.max_bytes),
       "the shared base64 cache declares a finite ceiling")
    _IMG_B64_CACHE.clear()
    with tempfile.TemporaryDirectory() as d:
        encoded = []
        for i in range(min(_IMG_B64_CACHE.max_entries, 200) + 20):
            p = os.path.join(d, f"i{i}.png")
            iconify.generate_icon(p, 8)
            encoded.append(img_b64(p))
        ok(all(encoded), "every image encodes")
        ok(len(_IMG_B64_CACHE) <= _IMG_B64_CACHE.max_entries,
           "img_b64 never grows past its ceiling")
        ok(img_b64(p) == encoded[-1], "an evicting cache still returns correct data")
    _IMG_B64_CACHE.clear()


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


def test_ci_skip_escalation():
    """A Flet skip is fine for a local run and a failure under CI.

    The workflow installs Flet as a hard requirement (no `pip install ... ||
    echo` fallback), but that alone doesn't catch every way the install can
    come up broken — a wrong-platform wheel, a partial install that satisfies
    `pip` but not `import flet`. _summarize() is the second guard: it turns a
    skip into a failure whenever CI=true, which GitHub Actions sets on every
    run, so a skip there can never quietly report success.
    """
    code, line = _summarize(10, 0, [], is_ci=True)
    ok(code == 0 and "10 passed, 0 failed" in line, "no skips, CI=true -> still green")

    code, line = _summarize(10, 0, ["UI tests"], is_ci=False)
    ok(code == 0, "a skip outside CI is not a failure (local run without Flet)")
    ok("1 skipped" in line, "the report mentions the skip even when it isn't fatal")

    code, line = _summarize(10, 0, ["UI tests", "UI settings-cache test"], is_ci=True)
    ok(code == 1, "any skip under CI fails the run")
    ok("1 failed" in line and "2 skipped" in line,
       "escalation adds one failure and the report still names the skip count")
    ok("UI tests" in line, "the escalation names the skipped tests in the returned report")

    code, line = _summarize(10, 0, [], is_ci=True)
    ok("FAIL" not in line, "a clean run's report carries no failure text")

    code, line = _summarize(10, 2, [], is_ci=True)
    ok(code == 1 and "2 failed" in line, "a genuine failure with no skips isn't inflated by escalation")


def test_hotkey_no_double_launch():
    """A globally registered combo must be ignored by the in-window handler.

    pynput doesn't swallow the keystroke, so a focused window sees it too —
    both handlers firing used to launch two apps on one Ctrl+N.
    """
    from app.hotkeys import HotkeyManager

    class FakeKeyboard:
        class HotKey:
            @staticmethod
            def parse(combo):
                return combo

    mgr = HotkeyManager(on_trigger=lambda _aid: None)
    mgr._build_mapping(FakeKeyboard(), [("Ctrl+1", "a"), ("Ctrl+2", "b")])
    ok(mgr.bound == {"ctrl+1", "ctrl+2"}, "accepted accelerators are recorded")
    ok(mgr.handles("Ctrl+1") is False, "no listener running -> the window handles the key")
    mgr.available = True
    ok(mgr.handles("Ctrl+1") is True and mgr.handles("ctrl+1") is True,
       "a registered combo is claimed by the global listener")
    ok(mgr.handles("Ctrl+7") is False, "an unregistered combo falls back to the window")
    ok(mgr.handles("") is False, "an empty accelerator is never claimed")


def _completes(fn, seconds=2.0) -> bool:
    """Run fn on a throwaway thread; False if it is still stuck afterwards.

    Keeps a deadlock regression a reported failure instead of a hung suite.
    """
    import threading
    done = threading.Event()
    threading.Thread(target=lambda: (fn(), done.set()), daemon=True).start()
    return done.wait(seconds)


def _settle_threads(before, timeout=3.0) -> bool:
    """Wait until the worker threads a test started have finished.

    Deleting a temp dir while a background scan is still writing into it used
    to be papered over with a fixed sleep; this waits for the actual condition
    instead, so the test is neither slow nor racy.
    """
    import threading
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        # A toast's countdown is a threading.Timer meant to outlive the action
        # it reports on — waiting for it would be waiting out the undo window.
        live = [t for t in threading.enumerate()
                if t not in before and t.is_alive() and not isinstance(t, threading.Timer)]
        if not live:
            return True
        time.sleep(0.01)
    return False


def test_geometry_debounce():
    """Debounce.schedule(immediate=True) must not deadlock.

    The window-close handler takes this path: the previous inline version ran
    the callback while holding its own non-reentrant lock, so closing the
    window hung the app instead of saving the geometry and exiting.
    """
    import time

    from app.debounce import Debounce

    # Every immediate flush goes through _completes(), and each assertion gets
    # its own instance: a deadlocked flush keeps that instance's lock forever.
    calls = []
    d = Debounce(0.05, lambda: calls.append(1))
    ok(_completes(lambda: d.schedule(immediate=True)),
       "immediate flush returns instead of deadlocking")
    ok(len(calls) == 1, "immediate flush runs the callback once")

    burst = []
    d2 = Debounce(0.05, lambda: burst.append(1))
    for _ in range(5):
        d2.schedule()
    ok(not burst, "debounced calls don't fire immediately")
    time.sleep(0.25)
    ok(len(burst) == 1, "a burst of calls collapses into one")

    mixed = []
    d3 = Debounce(0.05, lambda: mixed.append(1))
    d3.schedule()
    ok(_completes(lambda: d3.schedule(immediate=True)),
       "immediate flush after a pending one returns")
    time.sleep(0.2)
    ok(len(mixed) == 1, "an immediate flush cancels the pending one")

    dropped = []
    d4 = Debounce(0.05, lambda: dropped.append(1))
    d4.schedule()
    d4.cancel()
    time.sleep(0.2)
    ok(not dropped, "cancel drops the pending call")


def test_autostart():
    from app import autostart

    with tempfile.TemporaryDirectory() as d:
        prev = os.environ.get("APPDATA")
        os.environ["APPDATA"] = d
        try:
            link = autostart.startup_shortcut()
            ok(link is not None and link.name == "Centurio.lnk",
               "startup shortcut path derived from APPDATA")
            ok(autostart.remove_startup_shortcut() is False,
               "removing a missing shortcut is a quiet no-op")
            link.parent.mkdir(parents=True, exist_ok=True)
            link.write_text("shortcut")
            ok(autostart.remove_startup_shortcut() is True and not link.exists(),
               "the installer's startup shortcut is removed")
        finally:
            if prev is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = prev

    if os.name != "nt":
        ok(autostart.is_enabled() is False, "autostart reports off outside Windows")
        ok(autostart.sync(True) is True, "sync keeps the stored preference outside Windows")
        ok(autostart.sync(False) is False, "sync keeps 'off' outside Windows")


def types_ns(**kw):
    """A stand-in object with just the attributes a test hands it."""
    import types
    return types.SimpleNamespace(**kw)


def _find_control(node, pred, _depth=0):
    """Depth-first search of a built Flet tree, so dialog tests don't index
    into `content.controls[2].controls[0]` and break on every re-layout."""
    if _depth > 40 or node is None or isinstance(node, str):
        return None
    if pred(node):
        return node
    for attr in ("controls", "actions"):
        for child in getattr(node, attr, None) or []:
            found = _find_control(child, pred, _depth + 1)
            if found is not None:
                return found
    return _find_control(getattr(node, "content", None), pred, _depth + 1)


def _find_all(node, pred, _depth=0, out=None):
    """Every control in a built tree matching pred — for counting sliders etc."""
    out = [] if out is None else out
    if _depth > 40 or node is None or isinstance(node, str):
        return out
    if pred(node):
        out.append(node)
    for attr in ("controls", "actions"):
        for child in getattr(node, attr, None) or []:
            _find_all(child, pred, _depth + 1, out)
    _find_all(getattr(node, "content", None), pred, _depth + 1, out)
    return out


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_no_duplicate_icon_lists():
    """format.ICON_PACK is the one list of category icons.

    store.CATEGORY_ICONS and format.CATEGORY_ICON_CHOICES were byte-identical
    copies of each other that nothing read.
    """
    from app import format as fmt
    from app import store as store_mod

    ok(not hasattr(store_mod, "CATEGORY_ICONS"), "store carries no icon list of its own")
    ok(not hasattr(fmt, "CATEGORY_ICON_CHOICES"), "the unread choices copy is gone")
    ok(isinstance(fmt.ICON_PACK, list) and len(fmt.ICON_PACK) > 10,
       "ICON_PACK is the surviving list")
    ok("CATEGORY_ICON" not in _read("app", "ui.py"),
       "ui.py no longer imports a constant it never used")


def test_admin_argument_quoting():
    """The elevated command line is built with Windows' own quoting rules."""
    import subprocess

    from app.launcher import Launcher

    built = []

    class FakeShell:
        @staticmethod
        def ShellExecuteW(_h, _verb, _path, params, _cwd, _show):
            built.append(params)
            return 42

    lch = Launcher()
    real_ctypes = sys.modules.get("ctypes")
    fake = types_ns(windll=types_ns(shell32=FakeShell()))
    sys.modules["ctypes"] = fake
    try:
        args = ["--profile", "hello world", 'we"ird', r"C:\p ath" + "\\"]
        res = lch._run_as_admin(r"C:\x\app.exe", args, r"C:\x")
        ok(res.get("ok") is True, "a successful ShellExecuteW is reported as ok")
        ok(built and built[0] == subprocess.list2cmdline(args),
           f"arguments are quoted the way subprocess quotes them ({built})")
        ok(built and '\\"' in built[0],
           "an embedded quote is escaped instead of breaking the command line")
    finally:
        if real_ctypes is None:
            sys.modules.pop("ctypes", None)
        else:
            sys.modules["ctypes"] = real_ctypes


def test_packaging_metadata():
    """The version and the dependency list live in files that can't import
    each other, so the check that they agree belongs here."""
    import re

    from app import __version__

    ok(re.fullmatch(r"\d+\.\d+\.\d+", __version__), "app.__version__ is a plain version number")

    pyproject = _read("pyproject.toml")
    installer = _read("installer", "centurio.iss")
    ui_source = _read("app", "ui.py")

    quoted = re.escape(f'"{__version__}"')
    ok(re.search(rf"^version = {quoted}$", pyproject, re.M),
       "pyproject [project].version matches app.__version__")
    ok(re.search(rf"^build_version = {quoted}$", pyproject, re.M),
       "pyproject [tool.flet].build_version matches app.__version__")
    ok(re.search(rf"#define MyAppVersion {quoted}", installer),
       "the installer's MyAppVersion matches app.__version__")
    ok(__version__ not in ui_source, "the sidebar footer renders the version instead of repeating it")

    readme = re.search(r'^readme = "([^"]+)"$', pyproject, re.M)
    ok(readme is not None, "pyproject declares a readme")
    ok(readme and os.path.exists(os.path.join(_ROOT, readme.group(1))),
       "the declared readme exists — otherwise `pip install .` fails on it")

    block = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.M | re.S)
    ok(block is not None, "pyproject declares dependencies")
    declared = set(re.findall(r'"([^"]+)"', block.group(1) if block else ""))
    required = {line.strip() for line in _read("requirements.txt").splitlines()
                if line.strip() and not line.startswith("#")}
    ok(declared == required,
       f"requirements.txt and pyproject agree (pyproject-only: {declared - required}, "
       f"requirements-only: {required - declared})")


def test_single_entry_point():
    """app/main.py builds the page; only the root main.py launches it."""
    root_main = _read("main.py")
    page_module = _read("app", "main.py")
    ok('if __name__ == "__main__"' in root_main and "ft.app(" in root_main,
       "the root main.py starts the app")
    # app/main.py still reads CENTURIO_WEB — that's is_web inside the page
    # builder, not a second launcher.
    ok('if __name__ == "__main__"' not in page_module,
       "app/main.py doesn't carry a second entry point")
    code = "\n".join(line for line in page_module.splitlines()
                     if not line.lstrip().startswith("#"))
    ok("ft.app(" not in code, "app/main.py doesn't call ft.app()")


def test_colors():
    c1, c2 = C.cover_colors(200)
    ok(c1.startswith("#") and len(c1) == 7, "cover color is hex")
    ok(c1 != c2, "cover gradient has two stops")
    ok(C.glyph_color(10) == "#ffffff", "glyph colour is white on a red hue")
    ok(C.glyph_color(240) == "#ffffff", "glyph colour is white on a blue hue")
    ok(C.glyph_color(60) == C.BG_1, "glyph colour is dark on a bright yellow hue")
    ok(C.glyph_color(120) == C.BG_1, "glyph colour is dark on a bright green hue")
    for hue in range(0, 360, 30):
        col = C.glyph_color(hue)
        ok(col.startswith("#") and len(col) == 7, f"glyph_color({hue}) is a valid hex colour")


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

    # _steam_roots is module-level state. Every stub below is restored: these
    # tests share one process with everything after them in __main__, and an
    # unrestored patch quietly makes the order of the test list significant.
    real_steam_roots = discovery._steam_roots
    try:
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
    finally:
        discovery._steam_roots = real_steam_roots


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
    try:
        discovery._steam_roots = lambda: []
        changed = discovery.backfill_icons(store2, None)
        ok(changed and store2.get_app(a["id"])["sub"] == "Steam",
           "backfill_icons fixes sub even when icon already present")
    finally:
        discovery._steam_roots = real_steam_roots
    ok(discovery._steam_roots is real_steam_roots,
       "the module-level Steam-root lookup is left as this test found it")


def test_hotkeys():
    from app.hotkeys import app_for_accel, quick_accels, quick_bindings, to_pynput
    ok(to_pynput("Ctrl+Shift+1") == "<ctrl>+<shift>+1", "hotkey -> pynput format")
    ok(to_pynput("Alt+G") == "<alt>+g", "hotkey letter")
    ok(to_pynput("F5") == "<f5>", "hotkey F-key")
    ok(to_pynput("Ctrl+Space") == "<ctrl>+<space>", "named key wrapped for pynput")
    apps = [{"id": "a", "quick": True, "hotkey": None},
            {"id": "b", "quick": True, "hotkey": "Ctrl+Shift+X"},
            {"id": "c", "quick": True, "hotkey": None}]
    binds = dict((aid, acc) for acc, aid in quick_bindings(apps))
    ok(binds["b"] == "Ctrl+Shift+X", "explicit hotkey kept")
    ok(binds["a"] == "Ctrl+1" and binds["c"] == "Ctrl+2", "auto Ctrl+N assigned")

    # The quick-row badge, the global listener and the in-window fallback used
    # to count slots independently and disagree about what Ctrl+N launches.
    ok(quick_accels(apps) == binds, "badge labels and global bindings share one map")
    ok(quick_accels(apps)["a"] == "Ctrl+1",
       "an app with its own hotkey doesn't shift the Ctrl+N numbering")
    ok(app_for_accel(apps, "ctrl+1") == "a", "Ctrl+N resolves to the app its badge shows")
    ok(app_for_accel(apps, "Ctrl+9") is None, "an unassigned slot resolves to nothing")
    ok(app_for_accel(apps, "") is None, "an empty accelerator resolves to nothing")

    taken = [{"id": "x", "quick": True, "hotkey": "Ctrl+1"},
             {"id": "y", "quick": True, "hotkey": None}]
    ok(quick_accels(taken).get("y") == "Ctrl+2",
       "a slot claimed by an explicit hotkey is skipped, not burned")

    many = [{"id": str(i), "quick": True, "hotkey": None} for i in range(12)]
    slots = quick_accels(many)
    ok(len(slots) == 9 and "9" not in slots, "only nine quick slots are handed out")
    ok(quick_accels([{"id": "n", "quick": False, "hotkey": None}]) == {},
       "non-quick apps without a hotkey get no accelerator")


def test_launcher_monitor_lifecycle():
    """stop_monitor() used to crash the monitor thread with AttributeError."""
    import threading
    import time
    import types

    from app.launcher import Launcher

    fake = types.ModuleType("psutil")
    fake.process_iter = lambda attrs=None: []
    prev_mod = sys.modules.get("psutil")
    sys.modules["psutil"] = fake
    crashes = []
    prev_hook = threading.excepthook
    threading.excepthook = lambda args: crashes.append(args)
    try:
        lch = Launcher()
        ok(lch.start_monitor(interval=0.01) is True, "monitor starts when psutil is importable")
        ok(lch.start_monitor(interval=0.01) is True, "start_monitor is idempotent")
        time.sleep(0.05)
        lch.stop_monitor()
        time.sleep(0.15)
        ok(not crashes, "stopping the monitor doesn't crash its thread")
        ok(lch.start_monitor(interval=0.01) is True, "the monitor can be restarted after a stop")
        lch.stop_monitor()
        time.sleep(0.1)
        ok(not crashes, "restart + stop stays clean")
    finally:
        threading.excepthook = prev_hook
        if prev_mod is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = prev_mod


def test_launcher_emit():
    """Running-state changes are emitted once, and only when they change."""
    from app.launcher import Launcher

    seen = []
    lch = Launcher(on_change=lambda ids: seen.append(sorted(ids)))
    with lch._lock:
        lch._name_ids = {"a"}
    lch._emit()
    lch._emit()
    ok(seen == [["a"]], "an unchanged running set doesn't re-emit")
    with lch._lock:
        lch._name_ids = {"a", "b"}
    lch._emit()
    ok(seen == [["a"], ["a", "b"]], "a changed running set emits once")


def test_launcher_index():
    from app.launcher import Launcher
    lch = Launcher()
    lch.set_apps([{"id": "1", "path": r"C:\x\chrome.exe"},
                  {"id": "2", "path": "steam://rungameid/730"},
                  {"id": "3", "path": r"C:\tools\vim.bat"},
                  {"id": "4", "path": r"C:\tools\build.cmd"},
                  {"id": "5", "path": r"C:\old\legacy.com"},
                  {"id": "6", "path": r"C:\docs\notes.txt"}])
    keys = set(lch._exe_index)
    ok("chrome.exe" in keys and "vim.bat" in keys, "exe index built (Windows exe/bat)")
    ok("build.cmd" in keys and "legacy.com" in keys,
       "every extension in _EXE_EXTS is indexed, not a copy of the list")
    ok("notes.txt" not in keys, "non-executables stay out of the index")
    ok(all("steam" not in k for k in keys), "URL launchers excluded from index")

    # set_apps used to carry its own copy of the extension list.
    from app import launcher as launcher_module
    launcher_module._EXE_EXTS.add(".ps1")
    try:
        lch.set_apps([{"id": "7", "path": r"C:\s\script.ps1"}])
        ok("script.ps1" in lch._exe_index, "the index follows _EXE_EXTS, not a private copy")
    finally:
        launcher_module._EXE_EXTS.discard(".ps1")

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

    # os.startfile is Windows-only. The AttributeError it raised elsewhere
    # sailed past launch()'s `except OSError` and into the Flet event handler
    # behind the click; it has to come back as a reported failure instead.
    real_startfile = getattr(os, "startfile", None)
    if real_startfile is not None:
        del os.startfile
    try:
        raised = None
        try:
            res = lch.launch({"id": "u", "path": "steam://rungameid/730"})
        except Exception as exc:
            res, raised = None, exc
        ok(raised is None, "a URL launch without os.startfile doesn't raise")
        ok(res and res.get("ok") is False and res.get("error"),
           "it reports the failure instead, with a message for the toast")
    finally:
        if real_startfile is not None:
            os.startfile = real_startfile


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

        # is_all_view drives the rail's "Главное меню" highlight, and it used
        # to light up for every non-category filter.
        vs.set_filter("all")
        ok(vs.is_all_view() is True, "the all-apps view is the all view")
        for other in ("favorites", "recent", "running", f"category:{wid}"):
            vs.set_filter(other)
            ok(vs.is_all_view() is False, f"{other} is not the all view")

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


class _FakeWindow:
    def __init__(self):
        self.width = 1400
        self.height = 880
        self.left = 0
        self.top = 0
        self.maximized = False
        self.minimized = False
        self.visible = True
        self.resizable = True
        self.min_width = 0
        self.min_height = 0
        self.on_event = None
        self.prevent_close = False
        self.title_bar_hidden = False
        self.frameless = False

    def center(self):
        pass


class _FakePage:
    def __init__(self):
        self.overlay = []
        self.opened = []
        self.controls = []
        self.window = _FakeWindow()
        self.web = False

    def add(self, *controls):
        self.controls.extend(controls)

    def open(self, d):
        self.opened.append(d)

    def close(self, d):
        pass

    def update(self):
        pass

    def get_control(self, _id):
        return None


def _ui_for(store, window="library"):
    from unittest.mock import MagicMock

    from app.ui import CenturioUI
    page = _FakePage()
    ui = CenturioUI(page, store, MagicMock(), window=window)
    ui.mount()
    return ui, page


def _texts(control, depth=0, out=None):
    """Every ft.Text value in a built subtree, for asserting on what is shown."""
    import flet as ft
    out = [] if out is None else out
    if control is None or isinstance(control, str) or depth > 26:
        return out
    if isinstance(control, ft.Text):
        if control.value:
            out.append(control.value)
        for span in getattr(control, "spans", None) or []:
            if getattr(span, "text", None):
                out.append(span.text)
    for attr in ("controls", "actions"):
        for child in getattr(control, attr, None) or []:
            _texts(child, depth + 1, out)
    _texts(getattr(control, "content", None), depth + 1, out)
    return out


def _tap(x=300, y=250):
    return types_ns(global_x=x, global_y=y, local_x=x, local_y=y, kind="mouse")


def _key(name, ctrl=False, shift=False, alt=False):
    return types_ns(key=name, ctrl=ctrl, alt=alt, shift=shift, meta=False)


def _menu_labels(ui):
    return [r["label"] for r in ui.menu._rows if r["kind"] == "item"]


def test_no_modal_dialogs():
    """Приёмка: ни одного AlertDialog в коде."""
    for module in ("ui.py", "dialogs.py", "main.py", "toast.py", "menus.py"):
        source = _read("app", module)
        ok("AlertDialog(" not in source, f"app/{module} opens no modal dialog")
        ok("SnackBar(" not in source, f"app/{module} doesn't fall back to a snack bar")

    dialogs = _read("app", "dialogs.py")
    for gone in ("open_app_dialog", "open_context_menu", "open_settings_dialog",
                 "open_categories_dialog", "def confirm("):
        ok(gone not in dialogs, f"the old {gone.strip('def (')} entry point is gone")


def test_ui_text_stays_inside_the_bundled_fonts():
    """Приёмка: интерфейс не показывает символов, которых нет в наших шрифтах.

    Flet ships only what assets/fonts holds, and a codepoint none of them covers
    is drawn as an empty box — «↵» looked like a stray dot in the menus until
    this was noticed. Rather than parse five cmap tables, the check works from
    the other side: letters, digits and a short list of symbols known to be
    present. Anything else has to be justified by adding it here.
    """
    import ast
    import unicodedata

    allowed = set("«»—–…·×→↑↓№°")
    offenders = []
    for module in ("ui.py", "dialogs.py", "menus.py", "toast.py", "queries.py",
                   "format.py", "store.py", "hotkeys.py"):
        tree = ast.parse(_read("app", module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            for ch in node.value:
                if ord(ch) < 128 or ch.isalpha() or ch in allowed:
                    continue
                offenders.append(f"app/{module}:{node.lineno} {ch!r} "
                                 f"({unicodedata.name(ch, '?')})")
    ok(not offenders, "every character shown has a glyph: " + ("; ".join(offenders[:5])
                                                               or "none missing"))
    ok("↵" not in _read("app", "ui.py") + _read("app", "dialogs.py"),
       "the Enter arrow in particular is spelled out, because no bundled font has it")


def test_ui_keeps_the_original_layout():
    """Правило редизайна: раскладка библиотеки не меняется."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI layout test", exc)
        return

    import flet as ft

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work",
                       "quick": True, "favorite": True})
        chrome = store.add_app({"name": "Chrome", "path": "/x/chrome.exe",
                                "category_id": "work"})
        store.mark_launched(chrome["id"])
        ui, page = _ui_for(store)

        ok(page.controls, "mount puts a control tree on the page")
        ok(ui.rail_container.width == 76, "the rail is still 76 wide")
        ok(ui.sidebar_container.width == 236, "the sidebar is still 236 wide")
        ok(ui.sidebar_container.visible, "and it is shown")
        ok(ui.toolbar_holder.visible, "the toolbar is still there")
        ok(ui.status_container.visible, "so is the status bar")

        rail = _texts(ui.rail_container)
        ok(not rail, "the rail is icons only, as it always was")

        side = _texts(ui.sidebar_container)
        for label in ("Все приложения", "ПОКАЗАТЬ", "Избранное", "Недавние", "Запущено",
                      "НЕДАВНИЕ", "Centurio"):
            ok(label in side, f"the sidebar still has «{label}»")
        ok("Наборы" in side, "and «Наборы» was added to it")
        ok(not any("Автозапуск" in t for t in side),
           "the settings that were duplicated in its footer are gone")

        bar = _texts(ui.toolbar_holder)
        ok("По алфавиту" in bar, "the toolbar keeps the sort selector")
        ok("Найти и добавить" in bar, "and carries one add button")
        ok("Найти и добавить" in bar, "and carries one add button")
        ok(not any("Обновить" in t or "сканировать" in t.lower() for t in bar),
           "the two refresh buttons are gone from it")

        content = _texts(ft.Column(ui.content_col.controls))
        ok("Быстрый запуск" in content, "the quick-launch strip is still drawn")
        ok("Ctrl+1…9" in content, "with the range it answers to")
        ok("Работа" in content, "and the category sections below it")

        ui.set_running([chrome["id"]])
        ok(any("запущено" in t for t in _texts(ui.status_container)),
           "the status bar reports what is running")

        # Три новые вещи поверх той же раскладки.
        ok("Запуск" in _texts(ui.titlebar_holder), "the title bar gained the mode switch")
        ui.view.select_one(chrome["id"])
        ui.refresh()
        ok(ui.inspector_container.visible, "selecting a tile opens the inspector")
        ok(ui.inspector_container.width == 320, "which is 320 wide")
        ok("РАЗМЕЩЕНИЕ" in _texts(ui.inspector_container), "and carries the placement group")


def test_ui_inbox_badge_and_triage():
    """Разбор: значок со счётчиком, очередь по одной, четыре клавиши."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI triage test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ui, _ = _ui_for(store)

        ok(not any("12" in t for t in _texts(ui.rail_container)),
           "an empty queue shows no badge at all")

        store.queue_inbox([
            {"name": "OBS Studio", "path": "C:/obs.exe", "source": "startmenu"},
            {"name": "Krita", "path": "C:/krita.exe", "source": "startmenu"},
        ])
        ui.refresh()
        ok("2" in _texts(ui.rail_container), "the badge counts what is waiting")
        ok(any("ждут разбора" in t for t in _texts(ui.status_container)),
           "and the status bar says so too")

        ui._open_triage()
        shown = _texts(ft.Column(ui.content_col.controls)) if False else _texts(
            ui.content_col.controls[0])
        ok("Разбор" in shown, "the queue is a screen inside the window")
        ok("OBS Studio" in shown, "showing one program at a time")
        ok("Творчество" in shown, "with the category it looks like")
        ok("похоже" in shown, "marked as the suggestion")

        ui.handle_key(_key("1"))
        names = [a["name"] for a in store.state()["apps"]]
        ok(names == ["OBS Studio"], "1 puts it in the first offered category")
        ok(store.get_app(store.state()["apps"][0]["id"])["category_id"] == "create",
           "the one that was suggested")
        ok(len(store.state()["inbox"]) == 1, "and the queue moves on")

        ui.toast.fire_action()
        ok(len(store.state()["inbox"]) == 2, "«Вернуть» puts it back in the queue")
        ok(not store.state()["apps"], "and takes it out of the library")

        first = ui.inbox()[0]["name"]
        ui.handle_key(_key("Arrow Right"))
        ok(ui.inbox()[0]["name"] != first, "→ skips to the next one")

        ui.handle_key(_key("Delete"))
        ok(len(store.state()["inbox"]) == 1, "Del drops it from the queue")
        ui.toast.fire_action()
        ok(len(store.state()["inbox"]) == 2, "and that is undoable as well")

        ui.handle_key(_key("Enter"))
        ok(len(store.state()["apps"]) == 1, "Enter takes the suggestion")

        ui.triage_defer_all()
        ok(not store.state()["inbox"], "«Отложить всё» empties the queue")
        ok(ui.view.screen == "grid", "and goes back to the library")
        ui.toast.fire_action()
        ok(len(store.state()["inbox"]) == 1, "undo brings the queue back")

        store.clear_inbox()
        ui._open_triage()
        ok("Всё разобрано" in _texts(ui.content_col.controls[0]),
           "an empty queue has its own finished screen")


def test_ui_context_menus():
    """Четыре меню по правому клику."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI context-menu test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "category_id": "work"})["id"]
               for n in ("A", "B", "C")]
        ui, page = _ui_for(store)

        ui._app_menu(store.get_app(ids[0]), _tap())
        ok(ui.menu.open, "right-clicking a tile opens a menu")
        ok(not page.opened, "and nothing modal was opened to do it")
        labels = _menu_labels(ui)
        for entry in ("Открыть", "Открыть ещё окно", "В избранное", "В быстрый запуск",
                      "Переложить в…", "Добавить в набор…", "Показать в папке",
                      "Настроить", "Убрать из библиотеки"):
            ok(entry in labels, f"the app menu offers «{entry}»")

        submenu = [r for r in ui.menu._rows if r["kind"] == "item" and r["submenu"]]
        ok(len(submenu) == 2, "two of its entries open submenus")
        ui.menu.toggle_submenu("cat", ui._category_submenu([ids[0]]), 250)
        ok(ui.menu.sub_card.visible, "and the submenu opens next to the menu")
        ok("Работа" in _texts(ui.menu.sub_card), "listing the categories to move into")

        ui.menu.close()
        ok(not ui.menu.open, "clicking away closes it")

        ui.view.select_one(ids[0])
        ui.view.toggle_selection(ids[1])
        ui._app_menu(store.get_app(ids[0]), _tap())
        ok("Собрать набор" in _menu_labels(ui),
           "right-clicking inside a selection offers the selection's menu")
        ok(any("Убрать" in x for x in _menu_labels(ui)), "including removing all of it")
        ui.menu.close()

        ui._category_menu(store.state()["categories"][0], _tap())
        labels = _menu_labels(ui)
        for entry in ("Переименовать", "Цвет и иконка", "Удалить категорию"):
            ok(entry in labels, f"the category menu offers «{entry}»")
        ok("Переместить выше" in labels, "and reordering")
        first_row = next(r for r in ui.menu._rows
                         if r["kind"] == "item" and r["label"] == "Переместить выше")
        ok(first_row["disabled"], "which is disabled for the first category")
        ui.menu.close()

        ui._empty_menu(_tap())
        labels = _menu_labels(ui)
        ok("Обновить список" in labels,
           "the empty-space menu is where rescanning lives now")
        ok("Сортировка" in labels and "Найти и добавить" in labels,
           "along with sorting and adding")
        ok("Обновить" not in "".join(_texts(ui.toolbar_holder)),
           "so the toolbar no longer carries a refresh button")

        # Меню не должно вылезать за край окна.
        ui.menu.close()
        ui._app_menu(store.get_app(ids[0]), _tap(1390, 870))
        ok(ui.menu.card.left < 1390 and ui.menu.card.top < 870,
           "a menu opened near the corner is flipped back inside the window")


def test_ui_inspector_replaces_the_modal_form():
    """Инспектор вместо окна на тринадцать полей."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI inspector test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        app_id = store.add_app({"name": "Excel", "path": r"C:\Office16\EXCEL.EXE",
                                "category_id": "work", "track_exe": "EXCEL.EXE"})["id"]
        ui, page = _ui_for(store)

        ui._select_tile(app_id)
        ok(ui.inspector_container.visible, "clicking a tile opens the panel")
        ok(not page.opened, "and blocks nothing")
        shown = _texts(ui.inspector_container)
        ok("Excel" in shown, "the panel names the app")
        ok(any("EXCEL.EXE" in t for t in shown), "and shows where it lives")
        ok("Открыть" in shown, "with the action that runs it")
        ok("Быстрый запуск" in shown and "Своя горячая клавиша" in shown,
           "the placement group is there")
        ok("ПАРАМЕТРЫ ЗАПУСКА" in shown, "and the collapsed launch options")

        # Каждое изменение применяется сразу, кнопки «Сохранить» нет.
        ok("Сохранить" not in shown, "there is no save button")
        ui._toggle_quick(app_id, True)
        ok(store.get_app(app_id)["quick"] is True, "the pin toggle writes through")
        ui._set_args(app_id, "--profile work")
        ok(store.get_app(app_id)["args"] == ["--profile", "work"], "so do the arguments")
        ui._set_admin(app_id, True)
        ok(store.get_app(app_id)["run_as_admin"] is True, "and the admin switch")

        ui.view.adv = True
        ui.refresh()
        ok("EXCEL.EXE" in _texts(ui.inspector_container), "the process is shown when known")

        second = store.add_app({"name": "Zoom", "path": "/x/z", "category_id": "work"})["id"]
        ui._select_tile(second)
        ok("Zoom" in _texts(ui.inspector_container),
           "selecting another tile switches the panel instead of stacking a window")

        ui._close_inspector()
        ok(not ui.inspector_container.visible, "the cross closes it")


def test_ui_delete_is_undone_not_confirmed():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI delete test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "category_id": "work"})["id"]
               for n in ("Notion", "Figma")]
        ui, page = _ui_for(store)

        ui._remove_apps([ids[0]])
        ok(not page.opened, "nothing was opened to ask first")
        ok(store.get_app(ids[0]) is None, "the app is gone straight away")
        ok(ui.toast.action_btn.visible and ui.toast.action_label.value == "Вернуть",
           "a toast offers to put it back")
        ok(ui.toast.countdown.value == "8", "counting down from eight seconds")
        ui.toast.fire_action()
        ok(store.get_app(ids[0]) is not None, "«Вернуть» restores it")

        cat = store.state()["categories"][1]
        ui._move_apps_to_category(ids, cat["id"])
        ok(all(store.get_app(i)["category_id"] == cat["id"] for i in ids), "moving works")
        ui.toast.fire_action()
        ok(all(store.get_app(i)["category_id"] == "work" for i in ids),
           "and is undoable too")

        ui._remove_category(cat["id"])
        ok(not any(c["id"] == cat["id"] for c in store.state()["categories"]),
           "a category goes without a confirmation")
        ui.toast.fire_action()
        ok(any(c["id"] == cat["id"] for c in store.state()["categories"]),
           "and comes back with its apps")

        while len(store.state()["categories"]) > 1:
            store.remove_category(store.state()["categories"][-1]["id"])
        ui.refresh()
        ui._remove_category(store.state()["categories"][0]["id"])
        ok(len(store.state()["categories"]) == 1,
           "the last category can't be deleted — the apps would have nowhere to go")


def test_ui_sets():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI sets test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "category_id": "work"})["id"]
               for n in ("VS Code", "Notion")]
        ui, _ = _ui_for(store)

        ui._make_set(ids)
        rec = store.state()["sets"][0]
        ok(rec["name"] == "VS Code и Notion", "a set is named after what is in it")
        ok(rec["quick"] is True, "and lands in the quick-launch strip")
        ok("набор · 2 программы" in _texts(ft.Column(ui.content_col.controls)),
           "where it says what it is")

        ui.view.filter = "sets"
        ui.refresh()
        ok("VS Code, Notion" in _texts(ft.Column(ui.content_col.controls)),
           "the sidebar's «Наборы» view lists them with their members")

        ui.launcher.launch.return_value = {"ok": True, "running": True}
        ui.launcher.running_ids.return_value = ids
        ui._launch_set(rec["id"])
        ok(ui.launcher.launch.call_count == 2, "running a set starts everything in it")

        third = store.add_app({"name": "Figma", "path": "/x/f", "category_id": "work"})["id"]
        ui._add_to_set(rec["id"], [third])
        ok(len(store.get_set(rec["id"])["apps"]) == 3, "a program can be added to a set")
        ui.toast.fire_action()
        ok(len(store.get_set(rec["id"])["apps"]) == 2, "and that is undoable")

        ui._remove_set(rec["id"])
        ok(not store.state()["sets"], "a set can be removed")
        ui.toast.fire_action()
        ok(len(store.state()["sets"]) == 1, "and restored")


def test_ui_quick_numbers_match_the_hotkeys():
    """A number in the quick strip is a promise that Ctrl+N does this."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("quick-slot numbering test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "quick": True})["id"]
               for n in ("Notion", "Figma")]
        ui, _ = _ui_for(store)
        ui._make_set(ids)          # goes into the strip, ahead of both cards
        ui.refresh()

        from app.hotkeys import free_quick_slot, quick_accels

        accels = quick_accels(store.state()["apps"])
        ok(sorted(a.split("+")[-1] for a in accels.values()) == ["1", "2"],
           "the two pinned programs own Ctrl+1 and Ctrl+2")

        strip = _texts(ft.Column(ui.content_col.controls))
        numbers = [t for t in strip if t.isdigit()]
        ok(numbers.count("1") == 1 and numbers.count("2") == 1,
           "and each number appears once — the set ahead of them claims none")
        ok("3" in numbers, "the empty slot offers the first free number, not the card count")

        for n in range(3, 10):
            store.add_app({"name": f"App {n}", "path": f"/x/{n}", "quick": True})
        ok(free_quick_slot(store.state()["apps"]) == 0, "nine pinned programs fill the strip")

def test_ui_add_screen():
    """Найденное сгруппировано по источнику, путь можно вставить руками."""
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI add-screen test", exc)
        return

    import threading as _threading

    found = [
        {"name": "Elden Ring", "path": "steam://rungameid/1", "source": "steam"},
        {"name": "OBS Studio", "path": "C:/pf/obs64.exe", "source": "startmenu"},
        {"name": "Notion", "path": "/x/notion.exe", "source": "registry"},
    ]
    real_discover = discovery.discover_apps
    real_backfill = discovery.backfill_icons
    before = set(_threading.enumerate())
    try:
        discovery.discover_apps = (
            lambda icon_cache=None, on_progress=None, report=None: list(found))
        discovery.backfill_icons = lambda *a, **kw: False
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work"})
            ui, _ = _ui_for(store)

            ui._open_add()
            ok(_settle_threads(before), "the scan thread finishes")
            ui.refresh()
            ok(ui.view.screen == "add", "«Найти и добавить» is a screen, not a dialog")
            ok(not ui.toolbar_holder.visible, "which takes over the toolbar's space")

            groups = ui.found_groups()
            ok([g["source"] for g in groups] == ["steam", "startmenu"],
               "results are grouped by where they came from")
            ok(all(r["is_new"] for g in groups for r in g["rows"]),
               "«Только новые» is on by default")

            ui.toggle_only_new()
            names = [r["name"] for g in ui.found_groups() for r in g["rows"]]
            ok("Notion" in names, "turning it off shows what is already there")

            rows = {r["name"]: r for g in ui.found_groups() for r in g["rows"]}
            ok(ui.add_category_for(rows["Elden Ring"]) == "games",
               "a Steam game is proposed for «Игры»")
            ui.cycle_add_category(rows["Elden Ring"])
            ok(ui.add_category_for(rows["Elden Ring"]) != "games",
               "and the proposal can be overridden in the row")

            ui.toggle_add_row(rows["Notion"])
            ok(not ui.view.add_sel, "an app already in the library can't be ticked")

            # Поле пути: вторая дорога в тот же список.
            fake_exe = os.path.join(d, "MyApp.exe")
            with open(fake_exe, "w") as fh:
                fh.write("x")
            ui.add_manual_path(fake_exe)
            manual = [g for g in ui.found_groups() if g["source"] == "manual"]
            ok(manual and manual[0]["rows"][0]["name"] == "MyApp",
               "a pasted path shows up in its own «Вручную» group")
            ok(fake_exe.lower() in ui.view.add_sel, "already ticked, since it was asked for")

            ui.add_manual_path("/no/such/file.exe")
            ok(ui.toast.icon.color == C.DANGER, "a path that isn't there is refused")

            ui.view.reset_add()
            ui.toggle_add_row(rows["Elden Ring"])
            ui.defer_add()
            ok(len(store.state()["inbox"]) == 1, "«Отложить в разбор» queues instead of adding")
            ok(not store.state()["apps"] or len(store.state()["apps"]) == 1,
               "and nothing new landed in the library")
            store.clear_inbox()

            ui._open_add()
            ui.view.reset_add()
            rows = {r["name"]: r for g in ui.found_groups() for r in g["rows"]}
            ui.toggle_add_row(rows["Elden Ring"])
            ui.commit_add()
            ok(_settle_threads(before), "the post-add icon pass finishes")
            ok("Elden Ring" in [a["name"] for a in store.state()["apps"]],
               "committing adds the ticked programs")
            ok(ui.view.screen == "grid", "and goes back to the library")
            ui.toast.fire_action()
            ok("Elden Ring" not in [a["name"] for a in store.state()["apps"]],
               "«Вернуть» takes them out again")
    finally:
        discovery.discover_apps = real_discover
        discovery.backfill_icons = real_backfill
        _settle_threads(before)


def test_ui_scanning_is_just_a_spinner():
    """05: кружок и слово, без процентов и имён источников."""
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI scanning test", exc)
        return

    import threading as _threading

    real_discover = discovery.discover_apps
    before = set(_threading.enumerate())
    gate = _threading.Event()
    try:
        def slow(icon_cache=None, on_progress=None, report=None):
            gate.wait(3)
            return []
        discovery.discover_apps = slow
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            ui, _ = _ui_for(store)
            ui._open_add()

            deadline = time.time() + 3
            while not ui.scanning() and time.time() < deadline:
                time.sleep(0.01)
            ui.refresh()
            shown = _texts(ui.content_col.controls[0])
            ok("Сканирование" in shown, "the scan says only that it is scanning")
            ok(not any("%" in t for t in shown), "no percentage")
            ok(not any(t.isdigit() for t in shown), "no counter of what was found")
            ok(not any("Steam" in t for t in shown), "and no source name")

            gate.set()
            ok(_settle_threads(before), "the scan finishes")
    finally:
        gate.set()
        discovery.discover_apps = real_discover
        _settle_threads(before)


def test_ui_category_popover():
    """08: палитра, HEX, два ползунка и своя картинка вместо RGB-ползунков."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI category popover test", exc)
        return

    import flet as ft

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ui, page = _ui_for(store)
        cat_id = store.state()["categories"][0]["id"]

        ui._open_popover(cat_id)
        ok(ui.popover_layer.visible, "the popover opens next to the rail")
        ok(not page.opened, "and it is not a dialog")
        shown = _texts(ui.popover_layer.content)
        ok("ЦВЕТ" in shown and "ИКОНКА" in shown, "it has the colour and icon groups")
        ok("Своя картинка" in shown, "and the custom-image row")
        ok("Удалить категорию" in shown, "and deletion, without a second dialog")

        sliders = _find_all(ui.popover_layer.content, lambda c: isinstance(c, ft.Slider))
        ok(len(sliders) == 2, f"two sliders, not three RGB ones ({len(sliders)})")
        ok(any(s.max == 359 for s in sliders), "one of them is the hue")

        ui.set_category_color(cat_id, "#3ecfaf")
        ok(store.state()["categories"][0]["color"] == "#3ecfaf", "a swatch writes through")
        ui.set_category_icon(cat_id, "brush")
        ok(store.state()["categories"][0]["icon"] == "brush", "so does an icon")

        # HEX-поле и ползунки дают тот же результат, что палитра.
        hue, light, _sat = C.hex_to_hsl("#3ecfaf")
        ok(C.hsl_to_hex(hue, light) != "", "hue/lightness round-trip to a colour")
        ui.set_category_color(cat_id, C.parse_hex("#B06CF0"))
        ok(store.state()["categories"][0]["color"] == "#b06cf0", "and so does typed HEX")

        png = iconify.generate_icon(os.path.join(d, "mark.png"), 32)
        stored = ui._store_category_image(cat_id, str(png))
        ok(stored and os.path.exists(stored), "a custom image is copied next to the library")
        store.update_category(cat_id, {"image": stored})
        ui.refresh()
        glyph = ui._cat_glyph(store.state()["categories"][0])
        ok(isinstance(glyph, ft.Image), "and it is what the rail draws")
        ui.clear_category_image(cat_id)
        ok(store.state()["categories"][0]["image"] is None, "it can be taken off again")

        ui.close_popover()
        ok(not ui.popover_layer.visible, "Esc closes the popover")


def test_ui_calm_mode():
    """Один флаг убирает счётчики, пути, номера мест и подсказки."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI calm-mode test", exc)
        return

    import flet as ft

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        app_id = store.add_app({"name": "Notion", "path": r"C:\Program Files\Notion\N.exe",
                                "category_id": "work", "quick": True})["id"]
        store.mark_launched(app_id)
        ui, _ = _ui_for(store)
        ui.view.select_one(app_id)
        ui.refresh()

        def everything():
            return (_texts(ui.sidebar_container) + _texts(ui.toolbar_holder)
                    + _texts(ft.Column(ui.content_col.controls))
                    + _texts(ui.inspector_container) + _texts(ui.status_container))

        loud = everything()
        ok(any(t[:1].isdigit() and "приложени" in t for t in loud),
           "counters are normally shown")
        ok(any(t.startswith("…\\") for t in loud),
           "so is the path, shortened to the last two parts")
        ok("Ctrl+1…9" in loud, "and the key hints")

        store.set_setting("calm", True)
        ui.refresh()
        quiet = everything()
        ok(not any(t[:1].isdigit() and "приложени" in t for t in quiet),
           "calm mode drops the counters")
        ok(not any(t.startswith("…\\") for t in quiet), "and the paths")
        ok("Ctrl+1…9" not in quiet, "and the key hints")
        ok("Notion" in quiet, "but never the name of the program")

        ui.view.set_window("launch")
        ui.refresh()
        ok(not any("выбрать" in t for t in _texts(ui.body.content)),
           "the hint line in «Запуск» goes quiet too")


def test_ui_launch_window():
    """10: та же функциональность, меньше рамок."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI launch test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "VS Code", "path": "/x/code.exe",
                       "category_id": "dev", "quick": True})
        other = store.add_app({"name": "Notion", "path": "/x/n.exe",
                               "category_id": "work"})["id"]
        store.mark_launched(other)
        ui, _ = _ui_for(store, window="launch")

        shown = _texts(ui.body.content)
        ok("VS Code" in shown, "the pinned programs are there")
        ok("1" in shown, "with their position")
        ok("Notion" in shown, "and what was launched recently")
        ok("ЗАКРЕПЛЕНО" not in shown and "ПОСЛЕДНЕЕ" not in shown,
           "but the caps headers the old design had are gone")
        ok(any("выбрать" in t for t in shown), "the hints are one quiet line")

        ui.view.set_launch_query("not")
        ui.refresh()
        shown = _texts(ui.body.content)
        ok("Not" in shown, "the matched part is split out so it can be highlighted")
        ok("VS Code" not in shown, "and a query hides the pinned row")

        hidden = []
        ui.controllers["hide_to_tray"] = lambda: hidden.append(1)
        ui.launcher.launch.return_value = {"ok": True, "running": True}
        ui.launcher.running_ids.return_value = [other]
        ui.activate_selected()
        ok(ui.launcher.launch.called, "Enter launches the highlighted row")
        ok(hidden == [1], "and the window hides itself")
        ok(ui.view.launch_query == "", "with the query cleared for next time")

        store.set_setting("hide_after", False)
        hidden.clear()
        ui.view.set_launch_query("not")
        ui.refresh()
        ui.activate_selected()
        ok(hidden == [], "unless «Прятать окно после запуска» is off")

        ui.handle_key(_key("l", ctrl=True))
        ok(ui.view.window == "library", "Ctrl+L switches to the library")
        ui._open_launch()
        ok(ui.view.window == "launch", "and the switch in the title bar comes back")


def test_ui_launch_failure_offers_a_way_out():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI launch-failure test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        app_id = store.add_app({"name": "Zoom", "path": "/gone/zoom.exe",
                                "category_id": "work"})["id"]
        ui, _ = _ui_for(store)
        ui.launcher.launch.return_value = {"ok": False, "error": "Файл не найден: zoom.exe"}

        ui._launch(app_id)
        ok(ui.toast.icon.color == C.DANGER, "a failed launch is reported as an error")
        ok("не нашёлся" in ui.toast.text.value, f"in words ({ui.toast.text.value})")
        ok(ui.toast.detail.visible, "with a second line explaining why")
        ok(ui.toast.action_label.value == "Найти", "and the action that fixes it")


def test_ui_keyboard():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI keyboard test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "category_id": "work"})["id"]
               for n in ("A", "B", "C")]
        ui, _ = _ui_for(store)

        ui.handle_key(_key(",", ctrl=True))
        ok(ui.view.screen == "settings", "Ctrl+, opens the settings screen")
        ui.handle_key(_key("Escape"))
        ok(ui.view.screen == "grid", "Esc leaves it")

        ui.handle_key(_key("a", ctrl=True))
        ok(len(ui.view.sel) == 3, "Ctrl+A selects every visible tile")
        ui.handle_key(_key("Delete"))
        ok(not store.state()["apps"], "Delete removes the selection")
        ui.toast.fire_action()
        ok(len(store.state()["apps"]) == 3, "and it is undoable")

        ui.view.select_one(ids[0])
        ui._begin_capture()
        ok(ui.view.capture, "clicking the hotkey field starts listening")
        ui.handle_key(_key("Control", ctrl=True))
        ok(ui.view.capture, "a lone modifier isn't a combination")
        ui.handle_key(_key("G", ctrl=True, shift=True))
        ok(store.get_app(ids[0])["hotkey"] == "Ctrl+Shift+G", "the combination is recorded")

        ui.view.select_one(ids[1])
        ui._begin_capture()
        ui.handle_key(_key("G", ctrl=True, shift=True))
        ok(store.get_app(ids[1])["hotkey"] is None, "a combination already in use is refused")
        ok("занята" in ui.toast.text.value, "and says so")

        ui._begin_capture()
        ui.handle_key(_key("Escape"))
        ok(not ui.view.capture, "Esc cancels the capture")

        hidden = []
        ui.controllers["hide_to_tray"] = lambda: hidden.append(1)
        ui.view.close_inspector()
        ui.handle_key(_key("Escape"))
        ok(hidden == [1], "Esc with nothing left to close hides the window")


def test_ui_icons_are_never_letters():
    try:
        import flet as ft
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI icon test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work"})
        ui, _ = _ui_for(store)
        app = store.state()["apps"][0]

        slot = ui.icon_slot(app, 60, 16)
        ok(slot.bgcolor == C.SLOT_BG, "an icon-less app gets the neutral pad")
        ok(isinstance(slot.content, ft.Icon), "with a glyph, not a letter")
        ok(slot.content.color == C.SLOT_GLYPH, "in the muted placeholder colour")
        ok(slot.content.name == ft.Icons.WORK, "and the glyph is its category's")

        icon_png = iconify.generate_icon(os.path.join(d, "real.png"), 32)
        store.update_app(app["id"], {"icon": str(icon_png)})
        ui.refresh()
        slot = ui.icon_slot(store.get_app(app["id"]), 60, 16)
        ok(isinstance(slot.content, ft.Image), "once extracted, the real icon is what shows")

        ok("initials" not in _read("app", "ui.py"),
           "nothing in the window draws a letter placeholder any more")


def test_ui_settings_screen():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI settings test", exc)
        return

    from app.hotkeys import LAUNCH_HOTKEYS

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ui, page = _ui_for(store)
        ui._open_settings()
        ok(not page.opened, "the settings are a screen, not a dialog")

        shown = _texts(ui.content_col.controls[0])
        for row in ("Вызов окна", "Прятать окно после запуска", "Запускать с Windows",
                    "Крестик сворачивает в трей", "Складывать новое в разбор",
                    "Спокойный вид", "Размер плиток"):
            ok(row in shown, f"«{row}» is visible without unfolding anything")
        ok(any("Акцент" in t for t in shown), "and the rare things are named on one line")

        for key in ("hide_after", "autostart", "close_to_tray", "triage", "calm"):
            before = bool(store.state()["settings"].get(key))
            ui.set_setting(key, not before)
            ok(store.state()["settings"][key] is (not before), f"«{key}» writes through")

        start = store.state()["settings"]["launch_hotkey"]
        ui.cycle_launch_hotkey()
        ok(store.state()["settings"]["launch_hotkey"] != start, "the combination can change")
        ok(store.state()["settings"]["launch_hotkey"] in LAUNCH_HOTKEYS,
           "and only ever becomes one that registers")

        ui._settings_rare_open = True
        ui.refresh()
        rare = _texts(ui.content_col.controls[0])
        for row in ("Постеры вместо иконок у игр", "Кэш иконок", "Копия библиотеки",
                    "Подробный лог", "Показать первый запуск"):
            ok(row in rare, f"unfolding shows «{row}»")

        ui.backup()
        ok(any(p.name.startswith("centurio-backup-") for p in Path(d).glob("*.json")),
           "«Сохранить» writes a backup next to the library")


def test_ui_first_run():
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI first-run test", exc)
        return

    found = [{"name": "Chrome", "path": "C:/pf/chrome.exe", "source": "startmenu"},
             {"name": "Telegram", "path": "C:/pf/tg.exe", "source": "startmenu"}]
    real_discover = discovery.discover_apps
    real_suggest = discovery.suggest_first_run
    before = set(__import__("threading").enumerate())
    try:
        discovery.discover_apps = (
            lambda icon_cache=None, on_progress=None, report=None: list(found))
        discovery.suggest_first_run = (
            lambda items, limit=8: [{"app": i, "hint": "в автозагрузке"} for i in items])
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            ui, _ = _ui_for(store)

            ui.maybe_onboard()
            ok(ui.view.onboarding, "an empty library is offered the first-run screen")
            ok(_settle_threads(before), "its scan finishes")
            ui.refresh()
            ok(any("в автозагрузке" in t for t in _texts(ui.onboarding_layer.content)),
               "each suggestion says why it was suggested")

            ui.toggle_onboarding("c:/pf/chrome.exe")
            ui.commit_onboarding()
            ok([a["name"] for a in store.state()["apps"]] == ["Chrome"],
               "only the ticked programs are added")
            ok(store.state()["apps"][0]["quick"] is True, "and they go to the quick strip")

            ui.maybe_onboard()
            ok(not ui.view.onboarding, "the screen doesn't come back on the next start")
            ui.show_onboarding()
            ok(ui.view.onboarding, "but «Показать первый запуск» brings it back")
    finally:
        discovery.discover_apps = real_discover
        discovery.suggest_first_run = real_suggest
        _settle_threads(before)


def test_toast_lifecycle():
    try:
        from app.toast import ToastHost
    except Exception as exc:
        skip("toast test", exc)
        return

    host = ToastHost(_FakePage())
    host.show("Готово")
    ok(host.control.visible and host.text.value == "Готово", "a plain toast shows its text")
    ok(not host.action_btn.visible, "with no action")

    host.error("Реестр не отдал список программ",
               detail="Остальные источники прочитались", action_label="Повторить",
               action=lambda: None)
    ok(host.icon.color == C.DANGER, "an error toast is red")
    ok(host.card.bgcolor == C.ERR_BG, "and looks different, not just differently worded")
    ok(host.detail.visible, "a second line explains what happened")
    ok(host.action_label.value == "Повторить", "and the action closes it")

    fired = []
    host.show("Убрано", action=lambda: fired.append(1))
    ok(host.countdown.value == "8", "an undoable toast counts down from eight")
    host._tick(host._token)
    ok(host.countdown.value == "7", "each tick takes a second off")
    host.fire_action()
    ok(fired == [1], "clicking it runs the action once")
    host.fire_action()
    ok(fired == [1], "a second click can't run it again")

    host.show("Первый", action=lambda: None)
    stale = host._token
    host.show("Второй")
    host._tick(stale)
    ok(host.text.value == "Второй" and host.control.visible,
       "a stale timer doesn't clear the toast that replaced it")
    host.stop()


def test_ui_settings_cache():
    """refresh() reads the store once, no matter how many tiles it draws."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI settings-cache test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        for i in range(5):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work"})
        ui, _ = _ui_for(store)

        calls = {"n": 0}
        real_state = store.state

        def counting_state():
            calls["n"] += 1
            return real_state()
        store.state = counting_state

        ui.refresh()
        few = calls["n"]
        ok(few > 0, "refresh() reads the store at least once")

        for i in range(5, 80):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work"})
        calls["n"] = 0
        ui.refresh()
        ok(calls["n"] == few, "the read count doesn't grow with the number of apps")
        ok(calls["n"] == 1, "refresh() takes exactly one snapshot")
        ok(ui._snapshot is None, "and drops it when the pass ends")

        calls["n"] = 0
        ui.view.set_query("app1")
        ui.refresh(content_only=True)
        ok(calls["n"] == 1, "a keystroke in the search box costs one store read")

        ui.view.set_query("")
        calls["n"] = 0
        before = len(ui.apps())
        store.add_app({"name": "Fresh", "path": "/x/fresh", "category_id": "work"})
        ok(len(ui.apps()) == before + 1, "reads outside a refresh go to the store")
        ok(calls["n"] >= 2, "those reads aren't served from a stale snapshot")


def test_ui_refresh_thread_safety():
    """refresh() runs from five threads and rebuilds one shared control tree."""
    try:
        import threading

        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI refresh thread-safety test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        for i in range(8):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work"})
        ui, _ = _ui_for(store)

        seen_elsewhere = []
        real_build = ui._build_content

        def probing_build():
            box = []
            t = threading.Thread(target=lambda: box.append(ui._snapshot))
            t.start()
            t.join()
            seen_elsewhere.append(box[0])
            return real_build()

        ui._build_content = probing_build
        try:
            ui.refresh()
        finally:
            ui._build_content = real_build
        ok(seen_elsewhere == [None],
           "a refresh's snapshot is invisible to every other thread")
        ok(ui._snapshot is None, "the snapshot is dropped when the pass ends")

        overlaps = []
        depth = {"n": 0}
        real_build2 = ui._build_content

        def counting_build():
            depth["n"] += 1
            if depth["n"] > 1:
                overlaps.append(depth["n"])
            try:
                return real_build2()
            finally:
                depth["n"] -= 1

        ui._build_content = counting_build
        errors = []

        def hammer():
            try:
                for _ in range(25):
                    ui.refresh()
                    ui.set_running(["nope"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            ui._build_content = real_build2
        ok(not errors, f"concurrent refreshes raise nothing ({errors[:1]})")
        ok(not overlaps, "two refresh passes never build the control tree at once")
        ok(ui._snapshot is None, "no snapshot is left behind after the storm")


def test_shutdown_releases_resources():
    """Quitting used to rely entirely on daemon threads and os._exit."""
    try:
        from app import main as main_mod
    except Exception as exc:
        skip("shutdown test", exc)
        return

    ok(hasattr(main_mod, "shutdown"), "app.main exposes a shutdown routine")
    shutdown = main_mod.shutdown

    page_module = _read("app", "main.py")
    ok("ui.handle_key(e)" in page_module,
       "the page's key handler delegates to the UI's key table")

    calls = []

    class Recorder:
        def __init__(self, label, boom=False):
            self.label = label
            self.boom = boom

        def __call__(self):
            calls.append(self.label)
            if self.boom:
                raise RuntimeError(f"{self.label} is already gone")

    shutdown(store=types_ns(flush=Recorder("flush")),
             tray=types_ns(stop=Recorder("tray")),
             launcher=types_ns(stop_monitor=Recorder("monitor")),
             hotkeys=types_ns(stop=Recorder("hotkeys")),
             geometry_flush=types_ns(cancel=Recorder("geometry")),
             toast=types_ns(stop=Recorder("toast")))
    ok(set(calls) == {"flush", "geometry", "hotkeys", "monitor", "tray", "toast"},
       f"every resource is released ({calls})")
    ok(calls[0] == "flush", "the store is flushed before anything is torn down")

    calls.clear()
    shutdown(store=types_ns(flush=Recorder("flush", boom=True)),
             tray=types_ns(stop=Recorder("tray")),
             launcher=types_ns(stop_monitor=Recorder("monitor")))
    ok("tray" in calls and "monitor" in calls,
       "a step that raises doesn't stop the rest of the teardown")

    raised = None
    try:
        shutdown()
    except Exception as exc:
        raised = exc
    ok(raised is None, "shutdown with nothing to release is a quiet no-op")


def test_tray_mini_launcher():
    try:
        from app import dialogs
        from app.tray import TrayController
    except Exception as exc:
        skip("tray test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        for i in range(8):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work",
                           "quick": i < 7})
        items = dialogs.tray_items(store)
        ok(len(items) == 6, "the menu offers at most six pinned programs")
        ok(all("Ctrl+" in i["label"] for i in items), "each shows the key that runs it")
        ok("8 приложений" in dialogs.library_summary(store), "and the menu sizes the library")

        store.queue_inbox([{"name": "New", "path": "C:/new.exe"}])
        ok("в разборе" in dialogs.library_summary(store),
           "and mentions the queue when something waits in it")

        opened = []
        tray = TrayController("/no/such/icon.png",
                              on_show=lambda: opened.append("launch"),
                              on_open_library=lambda: opened.append("library"),
                              menu_provider=lambda: ([("App0", lambda: opened.append("app"))],
                                                     "8 приложений"))
        ok(tray.start() is False, "a missing icon file doesn't crash the tray")
        tray._show()
        tray._open_library()
        ok(opened == ["launch", "library"], "the entries reach their callbacks")
        tray.menu_provider = lambda: 1 / 0
        ok(tray._provided() == ([], ""), "a failing menu provider degrades to an empty menu")


def test_ui_background_rescan():
    """Тихая проверка складывает новое в разбор и не переиконивает всё."""
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI background-rescan test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "App", "path": "/x/app.exe", "category_id": "work"})
        ui, _ = _ui_for(store)

        refreshes = []
        real_backfill = discovery.backfill_icons
        real_discover = discovery.discover_apps
        before = set(__import__("threading").enumerate())

        def fake_backfill(store_, icon_cache=None, refresh=False):
            refreshes.append(refresh)
            return False

        discovery.backfill_icons = fake_backfill
        discovery.discover_apps = (lambda icon_cache=None, on_progress=None, report=None:
                                   [{"name": "Fresh", "path": "C:/fresh.exe",
                                     "source": "startmenu"}])
        try:
            ui.rescan(silent=True)
            ok(_settle_threads(before), "the silent rescan finishes")
            ok(refreshes == [False],
               "a silent rescan only fills gaps, it doesn't re-resolve every icon")
            ok(len(store.state()["inbox"]) == 1,
               "what it found waits in the triage queue instead of appearing by itself")
            ok(not any(a["name"] == "Fresh" for a in store.state()["apps"]),
               "nothing was added to the library behind the user's back")

            store.clear_inbox()
            store.set_setting("triage", False)
            ui.rescan()
            ok(_settle_threads(before), "the explicit rescan finishes")
            ok(refreshes == [False, True],
               "an explicit rescan still forces the full icon refresh")
            ok(not store.state()["inbox"],
               "with «Складывать новое в разбор» off, nothing is queued")
        finally:
            discovery.backfill_icons = real_backfill
            discovery.discover_apps = real_discover
            _settle_threads(before)


def test_ui_discovery_reuse():
    """Rescan, then open «Найти и добавить»: the machine is walked once."""
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI discovery-reuse test", exc)
        return

    scans = {"n": 0}
    real_discover = discovery.discover_apps
    before = set(__import__("threading").enumerate())
    try:
        def counting(icon_cache=None, on_progress=None, report=None):
            scans["n"] += 1
            return []

        discovery.discover_apps = counting
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            ui, _ = _ui_for(store)

            ui.start_scan()
            ok(_settle_threads(before), "the first scan finishes")
            ok(scans["n"] == 1, "opening the add screen with nothing cached scans once")
            ok(ui.cached_discovery() is not None, "the result is cached")

            ui.start_scan()
            ok(_settle_threads(before), "the second open settles")
            ok(scans["n"] == 1, "a cached result is reused instead of rescanning")

            ui._discovered_at -= 200
            ok(ui.cached_discovery() is None, "a stale result is not reused")
    finally:
        discovery.discover_apps = real_discover
        _settle_threads(before)


if __name__ == "__main__":
    test_store()
    test_store_sets_inbox_undo()
    test_store_concurrency()
    test_store_load_validation()
    test_store_write_failure()
    test_store_batched_writes()
    test_image_cache_bounded()
    test_store_corrupt_recovery()
    test_cdn_circuit_breaker()
    test_hotkey_rejection()
    test_ci_skip_escalation()
    test_hotkey_no_double_launch()
    test_geometry_debounce()
    test_autostart()
    test_no_duplicate_icon_lists()
    test_admin_argument_quoting()
    test_packaging_metadata()
    test_single_entry_point()
    test_colors()
    test_icon()
    test_discovery()
    test_discovery_sources()
    test_hotkeys()
    test_launcher_index()
    test_launcher_monitor_lifecycle()
    test_launcher_emit()
    test_color_parsing()
    test_launch_options()
    test_data_ops()
    test_log()
    test_queries()
    test_no_modal_dialogs()
    test_ui_text_stays_inside_the_bundled_fonts()
    test_ui_keeps_the_original_layout()
    test_ui_inbox_badge_and_triage()
    test_ui_context_menus()
    test_ui_inspector_replaces_the_modal_form()
    test_ui_delete_is_undone_not_confirmed()
    test_ui_sets()
    test_ui_quick_numbers_match_the_hotkeys()
    test_ui_add_screen()
    test_ui_scanning_is_just_a_spinner()
    test_ui_category_popover()
    test_ui_calm_mode()
    test_ui_launch_window()
    test_ui_launch_failure_offers_a_way_out()
    test_ui_keyboard()
    test_ui_icons_are_never_letters()
    test_ui_settings_screen()
    test_ui_first_run()
    test_toast_lifecycle()
    test_ui_settings_cache()
    test_ui_refresh_thread_safety()
    test_shutdown_releases_resources()
    test_tray_mini_launcher()
    test_ui_background_rescan()
    test_ui_discovery_reuse()
    code, line = _summarize(_passed, _failed, _skipped, bool(os.environ.get("CI")))
    print(f"\n{line}")
    sys.exit(code)
