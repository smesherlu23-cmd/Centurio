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
        ok(s.get_app(b["id"])["order"] == 1, "add_app appends in library order")
        s.remove_app(b["id"])

        s.set_setting("view_filter", "favorites")
        s.set_setting("calm", True)
        ok(Store(path).state()["settings"]["view_filter"] == "favorites", "view_filter persisted")
        ok(Store(path).state()["settings"]["calm"] is True, "«Спокойный вид» persisted")

        s.mark_launched(a["id"])
        ok(s.get_app(a["id"])["launch_count"] == 1, "launch_count incremented")
        ok(s.get_app(a["id"])["last_launched"] > 0, "last_launched set")

        cat = s.add_category("Тест")
        ok(cat["icon"] == "folder" and cat["color"] in C.CAT_PALETTE,
           "a new category starts with a glyph and a palette colour")
        s.update_category(cat["id"], {"color": "#ff8800", "icon": "sports_esports"})
        got_cat = next(c for c in s.state()["categories"] if c["id"] == cat["id"])
        ok(got_cat["color"] == "#ff8800" and got_cat["icon"] == "sports_esports",
           "category colour + icon updated")

        order_ids = [c["id"] for c in sorted(s.state()["categories"], key=lambda c: c["order"])]
        s.reorder_categories([order_ids[-1]] + order_ids[:-1])
        moved = [c["id"] for c in sorted(s.state()["categories"], key=lambda c: c["order"])]
        ok(moved[0] == order_ids[-1], "dragging a category in the rail reorders it")

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


def test_store_sets_and_undo():
    """Deleting is not confirmed any more — it is undone, so it has to be
    reversible in the store, not just in the window."""
    with tempfile.TemporaryDirectory() as d:
        s = Store(os.path.join(d, "data.json"))
        one = s.add_app({"name": "Notion", "path": "/x/n", "category_id": "work"})
        two = s.add_app({"name": "Figma", "path": "/x/f", "category_id": "create"})

        rec = s.add_set("Рабочее утро", [one["id"], two["id"], "no-such-app"])
        ok(rec is not None and rec["apps"] == [one["id"], two["id"]],
           "a set keeps only ids the library actually has")
        ok(s.add_set("Пустой", ["ghost"]) is None, "a set with nothing real in it isn't stored")

        gone = s.remove_apps([one["id"]])
        ok([g["id"] for g in gone] == [one["id"]], "remove_apps hands back what it removed")
        ok(s.state()["sets"][0]["apps"] == [two["id"]],
           "a removed app leaves the sets it was in")
        ok(s.restore_apps(gone) == 1, "the removed record goes back in")
        ok(s.restore_apps(gone) == 0, "restoring twice doesn't duplicate it")
        ok(len(s.state()["apps"]) == 2, "the library is whole again")

        moved = s.update_apps([one["id"], two["id"]], {"favorite": True})
        ok(moved == 2, "update_apps patches every id it was given")
        ok(all(a["favorite"] for a in s.state()["apps"]), "and the patch landed")

        undo = s.remove_category("create")
        ok(undo and undo["category"]["id"] == "create", "remove_category returns the record")
        ok(two["id"] in undo["apps"], "and the apps it had to reassign")
        ok(s.get_app(two["id"])["category_id"] != "create", "those apps moved to the fallback")
        ok(s.restore_category(undo) is True, "the category can be put back")
        ok(s.get_app(two["id"])["category_id"] == "create", "and its apps come back with it")

        set_rec = s.remove_set(rec["id"])
        ok(set_rec and set_rec["id"] == rec["id"], "remove_set returns what it removed")
        ok(s.restore_set(set_rec) is True and len(s.state()["sets"]) == 1, "and it restores")

        # A set whose members were all deleted between two runs is not worth
        # keeping: it would launch nothing and still count its members.
        s.data["sets"] = [{"id": "dead", "name": "Dead", "apps": ["ghost"]}]
        s.flush()
        ok(Store(s.path).state()["sets"] == [], "a set that lost every member is dropped on load")


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
        cats = [c for c in state["categories"] if isinstance(c, dict)]
        ok([c.get("id") for c in cats] == ["work", "dup"],
           "unusable categories are dropped and ids deduped")
        ok(state["settings"] == dict(DEFAULT_SETTINGS),
           "settings that aren't an object fall back to the defaults")
        ok(state["version"] == 2, "the loaded file reports the current schema version")
        ok(state["sets"] == [], "a file written before sets existed loads with none")

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
        sections = queries.build_sections(state["apps"], state["categories"], "all", "", set())
        ok(queries.flatten_sections(sections), "sanitised records render into sections")
        ok(queries.launch_rows(state["apps"], "", set(), state["categories"]) is not None,
           "and into the «Запуск» list")
        ok(queries.sort_apps(state["apps"]) is not None,
           "and they sort without tripping over a missing field")


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
        # A toast's countdown is a threading.Timer that is meant to outlive the
        # action it reports on — waiting for it would be waiting for the undo
        # window to expire.
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
    """The tokens are the design's, and the UI is not allowed to invent more."""
    import re as _re

    named = {k: v for k, v in vars(C).items()
             if k.isupper() and isinstance(v, str) and v.startswith("#")}
    ok(len(named) > 20, "the token set covers the palette")
    for name, value in named.items():
        # Six or eight digits only: Flutter has no CSS shorthand, and a "#e88"
        # is parsed as transparent — the button it painted came out empty.
        ok(_re.fullmatch(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value),
           f"{name} is a hex colour Flutter can parse ({value})")

    ok(len(C.CAT_PALETTE) == 8, "a category can be one of eight colours")
    ok(len(set(C.CAT_PALETTE)) == 8, "and none of them repeat")
    ok(C.ACCENT in C.ACCENT_CHOICES, "the default accent is one of the offered accents")

    # A category that never picked a colour still has to be told apart from
    # its neighbours in the rail, and the answer must not move between runs.
    first = C.category_color({"id": "x", "name": "Работа"})
    ok(first in C.CAT_PALETTE, "an unset category colour comes from the palette")
    ok(C.category_color({"id": "x", "name": "Работа"}) == first, "and it is stable")
    ok(C.category_color({"id": "x", "name": "Работа", "color": "#ffffff"}) == first,
       "the old white default is treated as unset")
    ok(C.category_color({"id": "x", "name": "Работа", "color": "#4f7dff"}) == "#4f7dff",
       "an explicit colour wins")

    ok(C.with_alpha("#101014", 0.6) == "#10101499", "with_alpha appends the byte")
    ok(C.parse_hex("rgb(255, 0, 8)") == "#ff0008", "parse_hex reads an rgb() triple")
    ok(C.parse_hex("#abc") == "#aabbcc", "parse_hex expands a short form")
    ok(C.parse_hex("nonsense") is None, "parse_hex rejects junk")
    ok(C.hex_to_rgb("#4f7dff") == (0x4f, 0x7d, 0xff), "hex_to_rgb round-trips")
    ok(C.rgb_to_hex(999, -5, 8) == "#ff0008", "rgb_to_hex clamps")

    # "Дальше пользоваться только ими — хардкод цветов в ui.py не оставлять."
    for module in ("ui.py", "dialogs.py", "toast.py", "main.py"):
        stray = set(_re.findall(r'"#[0-9a-fA-F]{3,8}"', _read("app", module)))
        ok(not stray, f"app/{module} spells no colour of its own ({sorted(stray)})")


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

    cats = [{"id": "work", "name": "Work", "order": 0}, {"id": "games", "name": "Games", "order": 1}]
    apps = [
        {"id": "1", "name": "Notion", "category_id": "work", "favorite": True, "last_launched": 100},
        {"id": "2", "name": "Chrome", "category_id": "work", "last_launched": 200},
        {"id": "3", "name": "CS2", "category_id": "games", "quick": True},
        {"id": "4", "name": "Orphan", "category_id": "missing"},
    ]
    running = {"2"}

    ok(queries.valid_filter("category:missing", cats) == "all", "valid_filter drops a dead category")
    ok(queries.valid_filter("category:work", cats) == "category:work", "valid_filter keeps a live category")
    ok(queries.valid_filter("favorites", cats) == "favorites", "valid_filter passes a fixed filter through")
    ok(queries.valid_filter("recent", cats) == "all", "a filter the rail no longer has falls back")

    ids = lambda lst: [a["id"] for a in lst]
    ok(ids(queries.visible_apps(apps, "favorites", "", running)) == ["1"], "favourites filter")
    ok(ids(queries.visible_apps(apps, "running", "", running)) == ["2"], "running filter matches the ids set")
    ok(ids(queries.visible_apps(apps, "pinned", "", running)) == ["3"], "pinned filter")
    ok(ids(queries.visible_apps(apps, "category:games", "", running)) == ["3"], "category filter")
    ok(ids(queries.visible_apps(apps, "all", "chrome", running)) == ["2"], "a query narrows the view")

    sections = queries.build_sections(apps, cats, "all", "", running)
    ok([s["name"] for s in sections] == ["Work", "Games", "Без категории"],
       "the grid groups by category in rail order, orphans last")
    ok(all(s["apps"] for s in sections), "an empty group isn't drawn")

    ok(queries.current_title("category:games", cats) == "Games", "current_title resolves a category")
    ok(queries.current_title("pinned", cats) == "Закреплённые", "current_title names a fixed filter")

    # --- «Запуск» ---
    rows = queries.launch_rows(apps, "", running, cats)
    kinds = [(r["kind"], r.get("title") or r["app"]["name"]) for r in rows]
    ok(kinds[0] == ("head", "СЕЙЧАС ОТКРЫТО"), "what is open comes first")
    ok(("head", "ПОСЛЕДНЕЕ") in kinds, "then what was open recently")
    ok([r["app"]["id"] for r in rows if r["kind"] == "app"] == ["2", "1"],
       "a running app isn't repeated under «последнее»")
    ok([r["index"] for r in rows if r["kind"] == "app"] == [0, 1],
       "only app rows are numbered, so the highlight can index them")

    hits = queries.launch_rows(apps, "o", running, cats)
    ok([r["app"]["name"] for r in hits] == ["Orphan", "Chrome", "Notion"],
       "a match at the start of the name outranks one in the middle")
    ok(queries.launch_rows(apps, "zzz", running, cats) == [], "no match, no rows")

    spans = queries.match_spans("Visual Studio Code", "stu")
    ok(spans == [("Visual ", False), ("Stu", True), ("dio Code", False)],
       f"match_spans splits on the hit, keeping the original case ({spans})")
    ok(queries.match_spans("Notion", "") == [("Notion", False)], "no query, no highlight")

    # --- экран «Найти и добавить» ---
    found = [
        {"name": "Elden Ring", "path": "steam://rungameid/1", "source": "steam"},
        {"name": "OBS Studio", "path": "C:/pf/obs64.exe", "source": "startmenu"},
        {"name": "PyCharm", "path": "C:/pf/JetBrains/pycharm.exe", "source": "registry"},
        {"name": "Notion", "path": "/x/notion.exe", "source": "startmenu"},
    ]
    real_cats = [{"id": "work", "name": "Работа"}, {"id": "create", "name": "Творчество"},
                 {"id": "games", "name": "Игры"}, {"id": "dev", "name": "Разработка"}]
    groups = queries.group_found(found, {"/x/notion.exe"}, real_cats)
    ok([g["source"] for g in groups] == ["steam", "startmenu", "registry"],
       "sources come back in a fixed order")
    by_source = {g["source"]: g for g in groups}
    ok(by_source["startmenu"]["total"] == 2 and by_source["startmenu"]["new"] == 1,
       "a group counts what is already in the library separately")
    already = [r for r in by_source["startmenu"]["rows"] if not r["is_new"]]
    ok([r["name"] for r in already] == ["Notion"], "an app already added is flagged, not hidden")

    only_new = queries.group_found(found, {"/x/notion.exe"}, real_cats, only_new=True)
    names = [r["name"] for g in only_new for r in g["rows"]]
    ok("Notion" not in names, "«Только новые» hides what is already there")

    ok(queries.suggest_category({"name": "Elden Ring", "source": "steam"}, real_cats) == "games",
       "Steam means games")
    ok(queries.suggest_category({"name": "PyCharm", "path": "C:/JetBrains/x.exe",
                                 "source": "registry"}, real_cats) == "dev",
       "a known developer tool means development")
    ok(queries.suggest_category({"name": "Photoshop", "path": "C:/Adobe/Photoshop.exe",
                                 "source": "startmenu"}, real_cats) == "create",
       "a graphics package means creative work")
    ok(queries.suggest_category({"name": "Что-то своё", "path": "C:/x.exe"}, real_cats) == "work",
       "anything unrecognised falls back to the first category, never to nothing")
    ok(queries.suggest_category({"name": "X"}, []) is None, "with no categories there is nothing to suggest")

    ok(queries.set_name_for([{"name": "Notion"}, {"name": "Figma"}]) == "Notion и Figma",
       "a set is named after what is in it")
    ok(queries.set_name_for([]) == "Набор", "an empty selection still gets a name")


def test_view_state():
    """The window's own state: modes, screens, selection, Esc."""
    from app.view_state import ViewState

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        wid = store.state()["categories"][0]["id"]
        store.set_setting("view_filter", f"category:{wid}")

        vs = ViewState(store)
        ok(vs.mode == "library" and vs.screen == "grid", "it opens on the library grid")
        ok(vs.filter == f"category:{wid}", "a persisted, still-valid filter is restored")
        vs.set_filter("favorites")
        ok(store.state()["settings"]["view_filter"] == "favorites", "set_filter persists immediately")

        vs.select_one("a")
        ok(vs.sel == ["a"] and vs.inspector == "a", "clicking a tile selects it and opens the inspector")
        vs.toggle_selection("b")
        ok(vs.sel == ["a", "b"] and vs.inspector == "b", "the corner check adds to the selection")
        vs.toggle_selection("a")
        ok(vs.sel == ["b"], "and clicking it again removes")
        vs.add_many(["c", "d", "b"])
        ok(vs.sel == ["b", "c", "d"], "selecting a group adds without duplicating")
        vs.select_all(["a", "b", "c"])
        ok(vs.sel == ["a", "b", "c"], "Ctrl+A takes everything visible")
        vs.drop_missing(["a", "c"])
        ok(vs.sel == ["a", "c"], "ids the library lost are forgotten")
        ok(vs.inspector == "c", "one that survived still has the inspector")
        vs.drop_missing(["a"])
        ok(vs.inspector is None, "but an inspector on a deleted app closes")

        vs.select_one("a")
        vs.open_popover(wid)
        ok(vs.escape() is True and vs.popover is None, "Esc closes the popover first")
        vs.capture = True
        ok(vs.escape() is True and vs.capture is False, "then it cancels a hotkey capture")
        vs.set_screen("settings")
        ok(vs.escape() is True and vs.screen == "grid", "then it leaves the screen")
        vs.select_one("a")
        ok(vs.escape() is True and vs.sel == [], "then it drops the selection")
        ok(vs.escape() is False, "with nothing left to close it says so, and the window hides")

        vs.set_filter(f"category:{wid}")
        store.data["categories"] = []
        vs.revalidate(store.state()["categories"])
        ok(vs.filter == "all", "revalidate falls back once the active category is gone")

        vs.hi = 5
        vs.move_hi(1, 3)
        ok(vs.hi == 2, "the launch highlight clamps to the number of rows")
        vs.move_hi(-9, 3)
        ok(vs.hi == 0, "and at the top")
        vs.move_hi(1, 0)
        ok(vs.hi == 0, "an empty list leaves it at zero")


class _FakeWindow:
    def __init__(self):
        self.width = 1180
        self.height = 768
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


def _ui_for(store, mode="library"):
    from unittest.mock import MagicMock

    from app.ui import CenturioUI
    page = _FakePage()
    ui = CenturioUI(page, store, MagicMock(), mode=mode)
    ui.mount()
    return ui, page


def _texts(control, depth=0, out=None):
    """Every ft.Text value in a built subtree, for asserting on what is shown."""
    import flet as ft
    out = [] if out is None else out
    if control is None or isinstance(control, str) or depth > 24:
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


def _find_all(control, pred, depth=0, out=None):
    out = [] if out is None else out
    if control is None or isinstance(control, str) or depth > 24:
        return out
    if pred(control):
        out.append(control)
    for attr in ("controls", "actions"):
        for child in getattr(control, attr, None) or []:
            _find_all(child, pred, depth + 1, out)
    _find_all(getattr(control, "content", None), pred, depth + 1, out)
    return out


def test_no_modal_dialogs():
    """The redesign's hard rule: nothing in the app opens an AlertDialog."""
    for module in ("ui.py", "dialogs.py", "main.py", "toast.py"):
        source = _read("app", module)
        ok("AlertDialog(" not in source, f"app/{module} opens no modal dialog")
        ok("SnackBar(" not in source, f"app/{module} doesn't fall back to a snack bar")

    dialogs = _read("app", "dialogs.py")
    for gone in ("open_app_dialog", "open_context_menu", "open_settings_dialog",
                 "open_categories_dialog", "def confirm("):
        ok(gone not in dialogs, f"the old {gone.strip('def (')} entry point is gone")


def test_ui_builds_every_surface():
    """Both modes, three screens, the popover and the first-run card."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI tests", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work",
                       "favorite": True})
        store.add_app({"name": "VS Code", "path": "/x/code.exe", "category_id": "dev",
                       "quick": True})
        chrome = store.add_app({"name": "Chrome", "path": "/x/chrome.exe",
                                "category_id": "work"})
        store.mark_launched(chrome["id"])
        poster = iconify.generate_icon(os.path.join(d, "poster.png"), 48)
        game = store.add_app({"name": "Half-Life", "path": "steam://rungameid/70",
                              "poster": str(poster), "category_id": "games"})

        ui, page = _ui_for(store)
        ok(page.controls, "mount puts a control tree on the page")

        for filt in ("all", "favorites", "running", "pinned"):
            ui.view.filter = filt
            ui.refresh()
            ok(ui.body.content is not None, f"the library builds for the {filt} filter")
        ui.view.filter = "category:work"
        ui.refresh()
        ok(ui.body.content is not None, "the library builds for a category filter")

        ui.view.filter = "all"
        ok(ui._use_poster(store.get_app(game["id"])) is True, "a game with a cover uses a poster")
        store.set_setting("game_posters", False)
        ui.refresh()
        ok(ui._use_poster(store.get_app(game["id"])) is False, "turning posters off is obeyed")
        store.set_setting("game_posters", True)

        for size in ("large", "compact"):
            store.set_setting("tile_size", size)
            ui.refresh()
            ok(ui.body.content is not None, f"the grid builds with {size} tiles")

        ui.view.set_mode("launch")
        ui.refresh()
        shown = _texts(ui.body.content)
        ok("ЗАКРЕПЛЕНО" in shown, "«Запуск» shows the pinned row")
        ok("ПОСЛЕДНЕЕ" in shown, "and what was launched recently")
        ok("Chrome" in shown, "the recently launched app is in the list")

        ui.view.set_query("cod")
        ui.refresh()
        shown = _texts(ui.body.content)
        ok("ЗАКРЕПЛЕНО" not in shown, "a query hides the pinned row")
        ok("Cod" in shown, "the matched substring is split out so it can be highlighted")
        ui.view.set_query("нетакого")
        ui.refresh()
        ok(any("ничего нет" in t for t in _texts(ui.body.content)),
           "an empty result explains itself")
        ui.view.set_query("")

        ui.view.set_mode("library")
        ui.view.select_one(chrome["id"])
        ui.refresh()
        shown = _texts(ui.body.content)
        ok("РАЗМЕЩЕНИЕ" in shown, "selecting a tile opens the inspector")
        ok("Chrome" in shown, "on the app that was clicked")

        ui.view.adv = True
        ui.refresh()
        ok("ПАРАМЕТРЫ ЗАПУСКА" in _texts(ui.body.content), "the launch options group expands")

        cat_id = store.state()["categories"][0]["id"]
        ui.view.open_popover(cat_id)
        ui.refresh()
        ok(ui.popover_layer.visible is True, "the category popover opens next to the rail")
        ok("ЦВЕТ" in _texts(ui.popover_layer.content), "with the colour palette")
        ok("Удалить категорию" in _texts(ui.popover_layer.content), "and the delete entry")
        ui.view.close_popover()
        ui.refresh()
        ok(ui.popover_layer.visible is False, "and it closes again")

        ui.view.set_screen("settings")
        ui.refresh()
        shown = _texts(ui.body.content)
        for group in ("ВЫЗОВ", "СПИСОК ПРОГРАММ", "ВИД", "ДАННЫЕ"):
            ok(group in shown, f"the settings screen has the {group} group")
        ok("Спокойный вид" in shown, "including «Спокойный вид»")

        ui.view.set_screen("add")
        ui.refresh()
        ok("Найти и добавить" in _texts(ui.body.content), "the add screen is a screen, not a dialog")

        ui.view.set_screen("grid")
        ui.view.onboarding = True
        ui.refresh()
        ok(ui.onboarding_layer.visible is True, "the first-run card can be shown")
        ok(any("каждый день" in t for t in _texts(ui.onboarding_layer.content)),
           "and it asks what is used daily")
        ui.view.onboarding = False

        store.data["apps"] = []
        ui.view.filter = "all"
        ui.refresh()
        ok(any("Здесь будет ваша библиотека" in t for t in _texts(ui.body.content)),
           "an empty library says what to do next")


def test_ui_calm_mode_hides_technical_text():
    """«Спокойный вид» is one flag every technical caption has to obey."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI calm-mode test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        app = store.add_app({"name": "Notion", "path": r"C:\Program Files\Notion\Notion.exe",
                             "category_id": "work", "quick": True})
        store.mark_launched(app["id"])
        ui, _ = _ui_for(store)
        ui.view.select_one(app["id"])
        ui.refresh()

        loud = _texts(ui.body.content)
        ok(any(r"C:\Program Files" in t for t in loud), "the inspector normally shows the path")
        ok(any(t[:1].isdigit() and "приложени" in t for t in loud),
           "and the grid shows a count")

        store.set_setting("calm", True)
        ui.refresh()
        quiet = _texts(ui.body.content)
        ok(not any(r"C:\Program Files" in t for t in quiet), "calm mode drops the path")
        ok(not any(t[:1].isdigit() and "приложени" in t for t in quiet), "and the counters")
        ok("Ctrl+K" not in quiet, "and the key chips")
        ok("Notion" in quiet, "but never the name of the program")

        ui.view.set_mode("launch")
        ui.refresh()
        ok("↑↓" not in _texts(ui.body.content), "and the hint bar in «Запуск»")
        store.set_setting("calm", False)
        store.set_setting("hints", True)
        ui.refresh()
        ok("↑↓" in _texts(ui.body.content), "which comes back when calm mode is off")
        store.set_setting("hints", False)
        ui.refresh()
        ok("↑↓" not in _texts(ui.body.content), "«Подсказки клавиш» switches it off on its own")


def test_ui_icons_are_never_letters():
    """Rule from the handoff: an app tile shows the real icon or a neutral pad."""
    try:
        import flet as ft
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI icon test", exc)
        return

    from app import colors as _C

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work"})
        ui, _ = _ui_for(store)
        app = store.state()["apps"][0]

        slot = ui.icon_slot(app, 60, 16)
        ok(slot.bgcolor == _C.BG_SLOT, "an icon-less app gets the neutral pad")
        ok(isinstance(slot.content, ft.Icon), "with a glyph, not a letter")
        ok(slot.content.color == _C.GLYPH_PLACEHOLDER, "in the muted placeholder colour")
        ok(slot.content.name == ft.Icons.WORK, "and the glyph is its category's")

        icon_png = iconify.generate_icon(os.path.join(d, "real.png"), 32)
        store.update_app(app["id"], {"icon": str(icon_png)})
        ui.refresh()
        slot = ui.icon_slot(store.get_app(app["id"]), 60, 16)
        ok(isinstance(slot.content, ft.Image), "once an icon is extracted, that is what is shown")

        # A letter tile is exactly what the redesign removed; the helpers that
        # drew one are gone with it.
        for helper in ("chip_colors", "cover_colors", "glyph_color"):
            ok(not hasattr(_C, helper), f"the letter-tile helper {helper} is gone")
        ok("initials(" not in _read("app", "ui.py").split("def cat_glyph")[0],
           "nothing before cat_glyph reaches for initials")


def test_ui_selection_and_bulk_actions():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI selection test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}.exe", "category_id": "work"})["id"]
               for n in ("A", "B", "C")]
        ui, _ = _ui_for(store)

        ui._select_tile(ids[0])
        ok(ui.view.sel == [ids[0]] and ui.view.inspector == ids[0],
           "a click selects one and opens the inspector")
        ui._toggle_tile(ids[1])
        ok(ui.view.sel == ids[:2], "the corner check builds a multi-selection")
        ok(any("Выбрано 2" in t for t in _texts(ui.body.content)),
           "and the bulk bar appears at two")

        ui._bulk_favorite()
        ok(sum(1 for a in store.state()["apps"] if a.get("favorite")) == 2,
           "«В избранное» applies to the whole selection")

        ui._select_tile(ids[0])
        ui._toggle_tile(ids[1])
        ui._bulk_make_set()
        sets = store.state()["sets"]
        ok(len(sets) == 1 and sorted(sets[0]["apps"]) == sorted(ids[:2]),
           "«Собрать набор» makes a set out of the selection")
        ok(ui.view.sel == [], "and clears the selection")

        cat = store.state()["categories"][1]["id"]
        ui._move_apps_to_category(ids[:2], cat)
        ok(all(store.get_app(i)["category_id"] == cat for i in ids[:2]),
           "dragging a selection onto a category moves all of it")
        ok(ui.toast.action_btn.visible, "and the move is undoable")
        ui.toast.fire_action()
        ok(all(store.get_app(i)["category_id"] == "work" for i in ids[:2]),
           "«Отменить» puts them back")

        ui.view.select_all(ids)
        ok(len(ui.view.sel) == 3, "Ctrl+A takes everything visible")
        ui._select_group([ids[0]])
        ok(len(ui.view.sel) == 3, "selecting a group doesn't drop what is already picked")


def test_ui_delete_is_undone_not_confirmed():
    """No confirmation dialog: removal happens and is reversible for 8 seconds."""
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

        ui.view.select_one(ids[0])
        ui._remove_selected()
        ok(not page.opened, "nothing was opened to ask first")
        ok(store.get_app(ids[0]) is None, "the app is gone straight away")
        ok(ui.toast.control.visible, "a toast reports it")
        ok(ui.toast.action_btn.visible and ui.toast.action_label.value == "Отменить",
           "with an undo action")
        ok(ui.toast.countdown.value == "8", "counting down from eight seconds")
        ok("Notion" in ui.toast.text.value, "and it names what went")

        ui.toast.fire_action()
        ok(store.get_app(ids[0]) is not None, "«Отменить» brings it back")
        ok(not ui.toast.control.visible, "and the toast goes away")

        ui.view.select_all(ids)
        ui._remove_selected()
        ok(len(store.state()["apps"]) == 0, "a whole selection can go at once")
        ok("Убрано 2" in ui.toast.text.value, f"reported as a count ({ui.toast.text.value})")
        ui.toast.fire_action()
        ok(len(store.state()["apps"]) == 2, "and comes back together")

        # A category is the same deal: it goes, its apps are reassigned, undo
        # puts both back.
        cat = store.state()["categories"][1]
        ui._move_apps_to_category(ids, cat["id"])
        ui.toast.dismiss()
        ui.remove_category(cat["id"])
        ok(not any(c["id"] == cat["id"] for c in store.state()["categories"]),
           "the category is deleted without a confirmation")
        ok(ui.toast.action_btn.visible, "and offers an undo")
        ui.toast.fire_action()
        ok(any(c["id"] == cat["id"] for c in store.state()["categories"]),
           "which restores the category")
        ok(all(store.get_app(i)["category_id"] == cat["id"] for i in ids),
           "and the apps that were in it")

        while len(store.state()["categories"]) > 1:
            store.remove_category(store.state()["categories"][-1]["id"])
        ui.refresh()
        ui.remove_category(store.state()["categories"][0]["id"])
        ok(len(store.state()["categories"]) == 1,
           "the last category can't be deleted — the apps would have nowhere to go")


def test_toast_lifecycle():
    """The toast replaces both the snack bar and the confirmation dialogs."""
    try:
        from app.toast import ToastHost
    except Exception as exc:
        skip("toast test", exc)
        return

    from app import colors as _C

    host = ToastHost(_FakePage())
    host.show("Готово")
    ok(host.control.visible and host.text.value == "Готово", "a plain toast shows its text")
    ok(not host.action_btn.visible, "with no action")
    ok(host.icon.color == _C.OK, "and the success colour")

    host.error("Файл не найден")
    ok(host.icon.color == _C.ERR, "an error toast is red")
    ok(host.card.bgcolor == _C.ERR_BG, "and looks different, not just differently worded")

    fired = []
    host.show("Убрано", action=lambda: fired.append(1), action_label="Отменить")
    ok(host.countdown.value == "8", "an undoable toast counts down from eight")
    host._tick(host._token)
    ok(host.countdown.value == "7", "each tick takes a second off")
    ok(not fired, "counting down doesn't fire the action")
    host.fire_action()
    ok(fired == [1], "clicking the action runs it once")
    ok(not host.control.visible, "and dismisses the toast")
    host.fire_action()
    ok(fired == [1], "a second click can't run it again")

    # A toast that was replaced while its timer was in flight must not clear
    # the one that took its place.
    host.show("Первый", action=lambda: None, action_label="Отменить")
    stale = host._token
    host.show("Второй")
    host._tick(stale)
    ok(host.text.value == "Второй" and host.control.visible,
       "a stale timer doesn't touch the toast that replaced it")
    host.stop()


def test_ui_hotkey_capture():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI hotkey-capture test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        one = store.add_app({"name": "A", "path": "/x/a", "category_id": "work"})["id"]
        two = store.add_app({"name": "B", "path": "/x/b", "category_id": "work"})["id"]
        ui, _ = _ui_for(store)
        ui.view.select_one(one)

        ui._begin_capture()
        ok(ui.view.capture is True, "clicking the field starts listening")
        ui.handle_key(types_ns(key="Control", ctrl=True, alt=False, shift=False, meta=False))
        ok(ui.view.capture is True, "a lone modifier isn't a combination")
        ui.handle_key(types_ns(key="G", ctrl=False, alt=False, shift=False, meta=False))
        ok(store.get_app(one)["hotkey"] is None, "and neither is a bare letter")

        ui.handle_key(types_ns(key="G", ctrl=True, alt=False, shift=True, meta=False))
        ok(store.get_app(one)["hotkey"] == "Ctrl+Shift+G", "the combination is recorded")
        ok(ui.view.capture is False, "and capture stops")

        ui.view.select_one(two)
        ui._begin_capture()
        ui.handle_key(types_ns(key="G", ctrl=True, alt=False, shift=True, meta=False))
        ok(store.get_app(two)["hotkey"] is None, "a combination already in use is refused")
        ok("занята" in ui.toast.text.value, f"and says so ({ui.toast.text.value})")

        ui.view.select_one(one)
        ui._begin_capture()
        ui.handle_key(types_ns(key="Escape", ctrl=False, alt=False, shift=False, meta=False))
        ok(ui.view.capture is False, "Esc cancels the capture")
        ok(store.get_app(one)["hotkey"] == "Ctrl+Shift+G", "leaving the old combination alone")

        ui._set_hotkey(one, None)
        ok(store.get_app(one)["hotkey"] is None, "and it can be cleared")


def test_ui_keyboard_table():
    """The key table from the handoff, end to end through handle_key."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI keyboard test", exc)
        return

    def key(name, ctrl=False, shift=False):
        return types_ns(key=name, ctrl=ctrl, alt=False, shift=shift, meta=False)

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = []
        for name in ("A", "B", "C"):
            rec = store.add_app({"name": name, "path": f"/x/{name}", "category_id": "work"})
            store.mark_launched(rec["id"])
            ids.append(rec["id"])
        ui, _ = _ui_for(store, mode="launch")

        ui.handle_key(key("Arrow Down"))
        ok(ui.view.hi == 1, "↓ moves the highlight")
        ui.handle_key(key("Arrow Down"))
        ui.handle_key(key("Arrow Down"))
        ok(ui.view.hi == 2, "and stops at the end of the list")
        ui.handle_key(key("Arrow Up"))
        ok(ui.view.hi == 1, "↑ moves it back")

        launched = []
        ui._launch = lambda app_id: launched.append(app_id)
        ui.handle_key(key("Enter"))
        ok(len(launched) == 1, "↵ launches the highlighted row")

        ui.view.set_query("zzz")
        ui.handle_key(key("Escape"))
        ok(ui.view.query == "", "Esc with a query clears it")

        hidden = []
        ui.controllers["hide_to_tray"] = lambda: hidden.append(1)
        ui.handle_key(key("Escape"))
        ok(hidden == [1], "Esc with nothing to clear hides the window")

        ui.handle_key(key("l", ctrl=True))
        ok(ui.view.mode == "library", "Ctrl+L opens the library")
        ui.handle_key(key(",", ctrl=True))
        ok(ui.view.screen == "settings", "Ctrl+, opens the settings screen")
        ui.handle_key(key("Escape"))
        ok(ui.view.screen == "grid", "Esc leaves it again")

        ui.handle_key(key("a", ctrl=True))
        ok(len(ui.view.sel) == 3, "Ctrl+A selects every visible tile")
        ui.handle_key(key("Delete"))
        ok(len(store.state()["apps"]) == 0, "Delete removes the selection")
        ui.toast.fire_action()
        ok(len(store.state()["apps"]) == 3, "and it is undoable")


def test_ui_launch_flow_hides_the_window():
    """The main scenario: hotkey, two letters, Enter, the window goes away."""
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI launch-flow test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        app_id = store.add_app({"name": "Notion", "path": "/x/notion.exe",
                                "category_id": "work"})["id"]
        ui, _ = _ui_for(store, mode="launch")

        hidden = []
        ui.controllers["hide_to_tray"] = lambda: hidden.append(1)
        ui.launcher.launch.return_value = {"ok": True, "running": True}
        ui.launcher.running_ids.return_value = [app_id]

        ui.view.set_query("no")
        ui.refresh()
        ui.activate_selected()
        ok(ui.launcher.launch.called, "Enter launched the match")
        ok(store.get_app(app_id)["launch_count"] == 1, "the launch was recorded")
        ok(hidden == [1], "and the window hid itself")
        ok(ui.view.query == "", "with the query cleared for next time")

        store.set_setting("hide_after", False)
        hidden.clear()
        ui.view.set_query("no")
        ui.refresh()
        ui.activate_selected()
        ok(hidden == [], "with «Прятать окно после запуска» off, the window stays")

        ui.launcher.launch.return_value = {"ok": False, "error": "Файл не найден: notion.exe"}
        ui._launch(app_id)
        ok(ui.toast.icon.color == __import__("app.colors", fromlist=["x"]).ERR,
           "a failed launch is reported as an error")
        ok(ui.toast.action_btn.visible and ui.toast.action_label.value == "Указать путь",
           "and the message carries the action that fixes it")


def test_ui_sets():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI sets test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ids = [store.add_app({"name": n, "path": f"/x/{n}", "category_id": "work"})["id"]
               for n in ("A", "B")]
        rec = store.add_set("Рабочее утро", ids)
        ui, _ = _ui_for(store, mode="launch")

        ok("НАБОРЫ" in _texts(ui.body.content), "«Запуск» offers the sets")
        ok("Рабочее утро" in _texts(ui.body.content), "by name")

        ui.launcher.launch.return_value = {"ok": True, "running": True}
        ui.launcher.running_ids.return_value = ids
        ui._launch_set(rec["id"])
        ok(ui.launcher.launch.call_count == 2, "running a set starts everything in it")
        ok(all(store.get_app(i)["launch_count"] == 1 for i in ids), "and records each one")

        ui.launcher.launch.return_value = {"ok": False, "error": "нет"}
        ui._launch_set(rec["id"])
        ok(ui.toast.icon.color == __import__("app.colors", fromlist=["x"]).ERR,
           "a set that starts nothing says so")


def test_ui_add_screen():
    """Scan results are grouped by source, with a suggested category per row."""
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
        {"name": "Notion", "path": "/x/notion.exe", "source": "startmenu"},
    ]
    real_discover = discovery.discover_apps
    real_backfill = discovery.backfill_icons
    before = set(_threading.enumerate())
    try:
        discovery.discover_apps = (
            lambda icon_cache=None, on_progress=None, report=None: list(found))
        # Resolving a steam:// icon reaches the CDN; this test is about the screen.
        discovery.backfill_icons = lambda *a, **kw: False
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            store.add_app({"name": "Notion", "path": "/x/notion.exe", "category_id": "work"})
            ui, _ = _ui_for(store)

            ui._open_add()
            ok(_settle_threads(before), "the scan thread finishes")
            ui.refresh()
            ok(ui.view.screen == "add", "«Найти и добавить» is a screen inside the window")

            groups = ui.found_groups()
            ok([g["source"] for g in groups] == ["steam", "startmenu"],
               "results are grouped by where they came from")
            ok(all(r["is_new"] for g in groups for r in g["rows"]),
               "«Только новые» is on by default, so nothing already added is listed")

            ui.toggle_only_new()
            names = [r["name"] for g in ui.found_groups() for r in g["rows"]]
            ok("Notion" in names, "turning it off shows what is already in the library")

            rows = {r["name"]: r for g in ui.found_groups() for r in g["rows"]}
            ok(ui.add_category_for(rows["Elden Ring"]) == "games",
               "a Steam game is proposed for «Игры»")
            ui.cycle_add_category(rows["Elden Ring"])
            ok(ui.add_category_for(rows["Elden Ring"]) != "games",
               "and the proposal can be overridden in the row")

            ui.toggle_add_row(rows["Notion"])
            ok(not ui.view.add_sel, "an app already in the library can't be ticked")
            ok("уже в библиотеке" in ui.toast.text.value, "clicking it explains why")

            ui.toggle_add_row(rows["OBS Studio"])
            ok(len(ui.view.add_sel) == 1, "a new one ticks")
            group = next(g for g in ui.found_groups() if g["source"] == "startmenu")
            ui.toggle_add_group(group)
            ok(not ui.view.add_sel, "the group header unticks a group that is fully ticked")
            ui.toggle_add_group(group)
            ok({r["key"] for r in group["rows"] if r["is_new"]} <= ui.view.add_sel,
               "and ticks every new row in it")

            ui.view.reset_add()
            ui.toggle_add_row(rows["Elden Ring"])
            ui.commit_add()
            ok(_settle_threads(before), "the post-add icon pass finishes")
            names = [a["name"] for a in store.state()["apps"]]
            ok("Elden Ring" in names, "committing adds the ticked programs")
            ok(ui.view.screen == "grid", "and goes back to the grid")
            ok(ui.toast.action_btn.visible, "the add is undoable")
            ui.toast.fire_action()
            ok("Elden Ring" not in [a["name"] for a in store.state()["apps"]],
               "«Отменить» takes them out again")

            ui.commit_add()
            ok("Отметьте" in ui.toast.text.value, "committing nothing asks for a tick instead")
    finally:
        discovery.discover_apps = real_discover
        discovery.backfill_icons = real_backfill
        _settle_threads(before)


def test_ui_scan_states():
    """Progress while scanning, and an error that carries its own way out."""
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI scan-state test", exc)
        return

    import threading as _threading

    real_discover = discovery.discover_apps
    before = set(_threading.enumerate())
    gate = _threading.Event()
    try:
        def slow_discover(icon_cache=None, on_progress=None, report=None):
            if on_progress:
                on_progress("Steam", 1, 3)
            gate.wait(3)
            if report is not None:
                report["errors"] = [{"source": "windows", "label": "Реестр",
                                     "error": "не отдал список"}]
            return []

        discovery.discover_apps = slow_discover
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "data.json"))
            ui, _ = _ui_for(store)
            ui._open_add()

            deadline = time.time() + 3
            while ui.scan_state()["state"] != "running" and time.time() < deadline:
                time.sleep(0.01)
            ui.refresh()
            shown = _texts(ui.body.content)
            ok("Смотрю, что установлено" in shown, "a scan in progress says what it is doing")
            ok(any("Steam" in t for t in shown), "and names the source it is reading")
            ok("Прервать" in shown, "and can be stopped")

            gate.set()
            ok(_settle_threads(before), "the scan finishes")
            ui.refresh()
            shown = _texts(ui.body.content)
            ok(any("Реестр" in t for t in shown), "a source that failed is reported")
            ok("Повторить" in shown, "with an action that retries")
            ok(ui.scan_state()["errors"], "and the error is remembered until dismissed")
            ui.dismiss_scan_errors()
            ok(not ui.scan_state()["errors"], "«Скрыть» closes it")
    finally:
        gate.set()
        discovery.discover_apps = real_discover
        _settle_threads(before)


def test_ui_settings_screen_writes_through():
    try:
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI settings test", exc)
        return

    from app.hotkeys import LAUNCH_HOTKEYS, format_accel

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        ui, _ = _ui_for(store)
        seen = []
        ui.controllers["on_setting"] = lambda k, v: seen.append((k, v))

        ui.view.set_screen("settings")
        ui.refresh()

        for key in ("hide_after", "autostart", "close_to_tray", "auto_rescan", "covers",
                    "game_posters", "hints", "calm", "debug_log"):
            before = bool(store.state()["settings"].get(key))
            ui.set_setting(key, not before)
            ok(store.state()["settings"][key] is (not before), f"«{key}» is written straight through")
        ok(("autostart", True) in seen or ("autostart", False) in seen,
           "the autostart toggle reaches the controller that talks to Windows")

        ui.set_setting("accent", "#4f7dff")
        ok(ui.accent() == "#4f7dff", "the accent is applied without a restart")
        ui.set_setting("tile_size", "compact")
        ok(store.state()["settings"]["tile_size"] == "compact", "so is the tile size")

        start = store.state()["settings"]["launch_hotkey"]
        ui.cycle_launch_hotkey()
        ok(store.state()["settings"]["launch_hotkey"] != start,
           "the launch combination can be changed")
        ok(store.state()["settings"]["launch_hotkey"] in LAUNCH_HOTKEYS,
           "and only ever becomes one that registers")
        ok(format_accel("Ctrl+Space") == "Ctrl+Пробел", "and it is spelled in Russian")
        ok(format_accel(None) == "не задана", "an unset combination says so")

        ui.backup()
        ok(any(p.name.startswith("centurio-backup-") for p in Path(d).glob("*.json")),
           "«Сохранить» writes a backup next to the library")


def test_ui_settings_cache():
    """_tile/accent used to re-copy the whole store per tile via self.state();
    refresh() reads settings once and every consumer reuses that cache."""
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
        few_apps_calls = calls["n"]
        ok(few_apps_calls > 0, "refresh() reads the store at least once")

        for i in range(5, 80):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work"})

        calls["n"] = 0
        ui.refresh()
        many_apps_calls = calls["n"]

        ok(many_apps_calls == few_apps_calls,
           "store.state() call count during refresh() doesn't grow with the number of apps")
        ok(many_apps_calls == 1, "refresh() takes exactly one snapshot of the store")
        ok(ui._snapshot is None, "the snapshot is dropped when the pass ends")

        calls["n"] = 0
        ui.view.set_lib_query("app1")
        ui.refresh()
        ok(calls["n"] == 1, "a keystroke in the search box costs one store read")

        # Outside a refresh pass nothing may serve stale data from the snapshot.
        ui.view.set_lib_query("")
        calls["n"] = 0
        before = len(ui.apps())
        store.add_app({"name": "Fresh", "path": "/x/fresh", "category_id": "work"})
        ok(len(ui.apps()) == before + 1, "reads outside a refresh go to the store")
        ok(calls["n"] >= 2, "those reads aren't served from a stale snapshot")


def test_ui_refresh_thread_safety():
    """refresh() runs from five threads and rebuilds one shared control tree.

    Two things have to hold: a pass must not publish its snapshot to other
    threads (they would read a half-built library), and concurrent passes must
    not interleave.
    """
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
        real_build = ui._build_library

        def probing_build():
            box = []
            t = threading.Thread(target=lambda: box.append(ui._snapshot))
            t.start()
            t.join()
            seen_elsewhere.append(box[0])
            return real_build()

        ui._build_library = probing_build
        try:
            ui.refresh()
        finally:
            ui._build_library = real_build
        ok(seen_elsewhere == [None],
           "a refresh's snapshot is invisible to every other thread")
        ok(ui._snapshot is None, "the snapshot is dropped when the pass ends")

        overlaps = []
        depth = {"n": 0}
        real_build2 = ui._build_library

        def counting_build():
            depth["n"] += 1
            if depth["n"] > 1:
                overlaps.append(depth["n"])
            try:
                return real_build2()
            finally:
                depth["n"] -= 1

        ui._build_library = counting_build
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
            ui._build_library = real_build2
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

    # The key table lives in the UI now; app/main.py must hand every press to
    # it rather than acting on some keys itself.
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
    """The tray menu launches pinned programs without opening a window."""
    try:
        from app import dialogs
        from app.tray import TrayController
    except Exception as exc:
        skip("tray test", exc)
        return

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        for i in range(7):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work",
                           "quick": i < 6})
        items = dialogs.tray_items(store)
        ok(len(items) == 5, "the menu offers at most five pinned programs")
        ok(all("Ctrl+" in i["label"] for i in items), "each one shows the key that runs it")
        ok(dialogs.library_summary(store) == "7 приложений", "and the menu says how big the library is")

        opened = []
        tray = TrayController("/no/such/icon.png",
                              on_show=lambda: opened.append("launch"),
                              on_open_library=lambda: opened.append("library"),
                              menu_provider=lambda: ([("App0", lambda: opened.append("app"))],
                                                     "7 приложений"))
        ok(tray.start() is False, "a missing icon file doesn't crash the tray")
        tray._show()
        tray._open_library()
        ok(opened == ["launch", "library"], "the menu entries reach their callbacks")
        tray.refresh()
        ok(True, "refreshing a tray that never started is a no-op")

        # A provider that blows up must not take the tray icon down with it.
        tray.menu_provider = lambda: 1 / 0
        ok(tray._provided() == ([], ""), "a failing menu provider degrades to an empty menu")


def test_ui_background_rescan():
    """The silent 15-minute tick must not do the expensive icon pass."""
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
        discovery.discover_apps = lambda icon_cache=None, on_progress=None, report=None: []
        try:
            ui.rescan(silent=True)
            ok(_settle_threads(before), "the silent rescan finishes")
            ok(refreshes == [False],
               "a silent rescan only fills gaps, it doesn't re-resolve every icon")

            ui.rescan()
            ok(_settle_threads(before), "the explicit rescan finishes")
            ok(refreshes == [False, True],
               "an explicit rescan still forces the full icon refresh")
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
            ui.start_scan()
            ok(_settle_threads(before), "the refreshed scan finishes")
            ok(scans["n"] == 2, "so the next open scans again")
    finally:
        discovery.discover_apps = real_discover
        _settle_threads(before)


def test_ui_first_run():
    try:
        from app import discovery
        from app.ui import CenturioUI  # noqa: F401
    except Exception as exc:
        skip("UI first-run test", exc)
        return

    found = [{"name": "Chrome", "path": "C:/pf/chrome.exe", "source": "startmenu"},
             {"name": "Telegram", "path": "C:/pf/telegram.exe", "source": "startmenu"}]
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
            ok(ui.view.onboarding is True, "an empty library is offered the first-run screen")
            ok(_settle_threads(before), "its scan finishes")
            ui.refresh()
            ok(any("в автозагрузке" in t for t in _texts(ui.onboarding_layer.content)),
               "each suggestion says why it was suggested")

            ui.toggle_onboarding("c:/pf/chrome.exe")
            ui.commit_onboarding_selection()
            names = [a["name"] for a in store.state()["apps"]]
            ok(names == ["Chrome"], "only the ticked programs are added")
            ok(store.state()["apps"][0]["quick"] is True, "and they are pinned in «Запуск»")
            ok(store.state()["settings"]["onboarded"] is True, "the screen doesn't come back")

            ui.maybe_onboard()
            ok(ui.view.onboarding is False, "not on the next start either")
            ui.show_onboarding()
            ok(ui.view.onboarding is True, "but «Показать первый запуск» brings it back")
            ui.close_onboarding()
            ok(ui.view.onboarding is False, "«Позже» closes it")
    finally:
        discovery.discover_apps = real_discover
        discovery.suggest_first_run = real_suggest
        _settle_threads(before)


def test_discovery_sources_and_suggestions():
    """Windows results carry where they came from; suggestions carry why."""
    from app import discovery

    ok("'startmenu'" in _read("app", "discovery.py"),
       "the Start Menu pass tags what it finds")
    ok("'registry'" in _read("app", "discovery.py"),
       "and so do the uninstall and App Paths passes")

    merged = discovery._dedupe([
        {"name": "A", "path": "C:/a.exe", "source": "startmenu"},
        {"name": "A", "path": "C:/a.exe", "source": "registry", "icon": "/i.png"},
    ])
    ok(len(merged) == 1, "the same program from two sources is one entry")
    ok(merged[0]["source"] == "startmenu", "the first source it was seen in wins")
    ok(merged[0]["icon"] == "/i.png", "and an icon from the second is still adopted")

    steps = []
    report = {}
    discovery.discover_apps(None, on_progress=lambda *a: steps.append(a), report=report)
    ok(steps and steps[-1][1] == steps[-1][2],
       "progress is reported and ends at the last source")
    ok("errors" in report, "the report says which sources failed")

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "Desktop"))
        with open(os.path.join(d, "Desktop", "Visual Studio Code.lnk"), "w") as fh:
            fh.write("x")
        old = os.environ.get("USERPROFILE")
        os.environ["USERPROFILE"] = d
        try:
            names = discovery.desktop_names()
            ok("visualstudiocode" in names, "a desktop shortcut is recognised by name")
            items = [{"name": "Visual Studio Code", "path": "C:/x.exe", "source": "registry"},
                     {"name": "Nothing", "path": "C:/y.exe", "source": "startmenu"}]
            picked = discovery.suggest_first_run(items)
            ok(picked and picked[0]["app"]["name"] == "Visual Studio Code",
               "and it is offered first on the first-run screen")
            ok(picked[0]["hint"] == "на рабочем столе", "with the reason it was picked")
            ok(picked[1]["hint"] == "в меню «Пуск»",
               "the rest are honestly labelled, not guessed at")
        finally:
            if old is None:
                os.environ.pop("USERPROFILE", None)
            else:
                os.environ["USERPROFILE"] = old


if __name__ == "__main__":
    test_store()
    test_store_sets_and_undo()
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
    test_hotkeys()
    test_launcher_index()
    test_launcher_monitor_lifecycle()
    test_launcher_emit()
    test_color_parsing()
    test_launch_options()
    test_data_ops()
    test_log()
    test_queries()
    test_view_state()
    test_discovery_sources_and_suggestions()
    test_no_modal_dialogs()
    test_ui_builds_every_surface()
    test_ui_calm_mode_hides_technical_text()
    test_ui_icons_are_never_letters()
    test_ui_selection_and_bulk_actions()
    test_ui_delete_is_undone_not_confirmed()
    test_toast_lifecycle()
    test_ui_hotkey_capture()
    test_ui_keyboard_table()
    test_ui_launch_flow_hides_the_window()
    test_ui_sets()
    test_ui_add_screen()
    test_ui_scan_states()
    test_ui_settings_screen_writes_through()
    test_ui_settings_cache()
    test_ui_refresh_thread_safety()
    test_ui_background_rescan()
    test_ui_discovery_reuse()
    test_ui_first_run()
    test_tray_mini_launcher()
    test_shutdown_releases_resources()
    code, line = _summarize(_passed, _failed, _skipped, bool(os.environ.get("CI")))
    print(f"\n{line}")
    sys.exit(code)
