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
    one real run of this file.
    """
    if skipped and is_ci:
        failed += 1
        print(f"FAIL: {len(skipped)} test(s) skipped under CI (Flet should be installed here): "
              f"{', '.join(skipped)}")
    line = f"{passed} passed, {failed} failed" + (f", {len(skipped)} skipped" if skipped else "")
    return (1 if failed else 0), line


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
        ok(state["version"] == 1, "a non-numeric version falls back to 1")

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


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


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


def test_ui_build():
    try:
        from unittest.mock import MagicMock
        from app.ui import CenturioUI
        from app import dialogs
    except Exception as exc:
        skip("UI tests", exc)
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
        target_cat_id = store.state()["categories"][0]["id"]
        dialogs.open_categories_dialog(ui, target_cat_id)
        ok(True, "categories dialog opens with a category focused, without crashing")
        dialogs.open_categories_dialog(ui, "no-such-category-id")
        ok(True, "focusing a since-deleted category doesn't crash the dialog")
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

        from app import colors as _C
        page.opened.clear()
        ui._toast("Готово")
        ui._toast("Ошибка", error=True)
        ok_icon = page.opened[-2].content.controls[0]
        err_icon = page.opened[-1].content.controls[0]
        ok(ok_icon.color == _C.GREEN, "a success toast uses the green icon")
        ok(err_icon.color == _C.DANGER, "an error toast uses the red icon, not the same look as success")
        ok(ok_icon.name != err_icon.name, "success and error toasts use different icons")
    finally:
        _time.sleep(0.4) 
        shutil.rmtree(d, ignore_errors=True)


def test_ui_settings_cache():
    """_draggable_tile/_accent used to re-copy the whole store per tile via
    self.state(); refresh() now reads settings once and every tile consumer
    reuses that cache. Assert the store read count stays flat as the library
    grows, instead of scaling with the number of apps rendered.
    """
    try:
        from unittest.mock import MagicMock
        from app.ui import CenturioUI
    except Exception as exc:
        skip("UI settings-cache test", exc)
        return

    class FakePage:
        def __init__(self):
            self.overlay = []
            self.controls = []

        def open(self, d):
            pass

        def close(self, d):
            pass

        def update(self):
            pass

    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "data.json"))
        for i in range(5):
            store.add_app({"name": f"App{i}", "path": f"/x/{i}", "category_id": "work"})

        ui = CenturioUI(FakePage(), store, MagicMock())

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
        ok(many_apps_calls == 1,
           "refresh() takes exactly one snapshot of the store")
        ok(ui._snapshot is None, "the snapshot is dropped when the refresh pass ends")

        calls["n"] = 0
        ui.view.set_query("app1")
        ui.refresh(content_only=True)
        ok(calls["n"] == 1, "a keystroke in the search box costs one store read")

        # Outside a refresh pass nothing may serve stale data from the snapshot.
        ui.view.set_query("")
        calls["n"] = 0
        before = len(ui.apps())
        store.add_app({"name": "Fresh", "path": "/x/fresh", "category_id": "work"})
        ok(len(ui.apps()) == before + 1, "reads outside a refresh go to the store")
        ok(calls["n"] >= 2, "those reads aren't served from a stale snapshot")


if __name__ == "__main__":
    test_store()
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
    test_ui_build()
    test_ui_settings_cache()
    code, line = _summarize(_passed, _failed, _skipped, bool(os.environ.get("CI")))
    print(f"\n{line}")
    sys.exit(code)
