from __future__ import annotations

from . import log

_MODS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "option": "<alt>",
    "shift": "<shift>",
    "win": "<cmd>", "cmd": "<cmd>", "super": "<cmd>", "meta": "<cmd>",
}


def to_pynput(accel: str) -> str:
    """Translate a UI accelerator ("Ctrl+Shift+G") into pynput's syntax.

    Single characters pass through as-is, known modifiers are mapped, and any
    other token is wrapped as "<name>" — pynput's spelling for named keys such
    as <f5> or <space>. Unknown names are deliberately *not* rejected here;
    HotkeyManager.register validates each result against pynput itself.
    """
    out = []
    for raw in str(accel).split("+"):
        p = raw.strip().lower()
        if not p:
            continue
        if p in _MODS:
            out.append(_MODS[p])
        elif len(p) == 1:
            out.append(p)
        else:
            out.append(f"<{p}>")
    return "+".join(out)


class HotkeyManager:
    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self._listener = None
        self.available = False
        self.rejected: list[str] = []
        self.bound: set[str] = set()

    def _build_mapping(self, keyboard, bindings):
        """Turn accelerators into a pynput mapping, dropping the unusable ones.

        GlobalHotKeys parses its whole mapping in the constructor, so a single
        unparseable combo would take every other hotkey down with it. Validating
        one at a time keeps the good bindings working. Returns (mapping,
        rejected); kept separate from register() so it is testable without
        starting a real keyboard listener. Also records the accepted
        accelerators in self.bound, which handles() reads.
        """
        parse = getattr(keyboard.HotKey, "parse", None)
        mapping = {}
        rejected = []
        self.bound = set()
        for accel, app_id in bindings:
            if not accel:
                continue
            combo = to_pynput(accel)
            if not combo:
                continue
            if parse is not None:
                try:
                    parse(combo)
                except Exception:
                    rejected.append(accel)
                    log.warning("ignoring unparseable hotkey %r (as %r)", accel, combo)
                    continue
            if combo in mapping:
                rejected.append(accel)
                log.warning("ignoring duplicate hotkey %r", accel)
                continue
            mapping[combo] = (lambda aid=app_id: self._fire(aid))
            self.bound.add(accel.strip().lower())
        return mapping, rejected

    def register(self, bindings) -> bool:
        self.stop()
        self.rejected = []
        self.bound = set()
        try:
            from pynput import keyboard
        except Exception:
            self.available = False
            return False

        mapping, self.rejected = self._build_mapping(keyboard, bindings)
        if not mapping:
            self.available = False
            self.bound = set()
            return False
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            self.available = True
            return True
        except Exception:
            log.exception("failed to start the global hotkey listener")
            self.available = False
            self.bound = set()
            return False

    def handles(self, accel: str) -> bool:
        """True when the global listener already owns this accelerator.

        The listener does not swallow the keystroke, so a focused window sees
        it too. Any in-window shortcut handler must check this first or the
        same key press launches twice.
        """
        return self.available and (accel or "").strip().lower() in self.bound

    def _fire(self, app_id):
        # Runs on pynput's listener thread, where an escaping exception kills
        # the listener and takes every other hotkey with it — so it is caught,
        # but not swallowed silently.
        try:
            self.on_trigger(app_id)
        except Exception:
            log.exception("global hotkey handler for %s failed", app_id)

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


QUICK_SLOTS = 9


def quick_accels(apps) -> dict[str, str]:
    """Map app id -> accelerator. The single source of truth for Ctrl+N.

    Explicit per-app hotkeys win; the remaining "quick" apps take the free
    Ctrl+1…Ctrl+9 slots in library order. A slot already claimed by an explicit
    hotkey is skipped rather than burned, so no quick app is left with no
    binding at all. The quick-row badge, the global listener and the in-window
    fallback all read this map — what a tile promises is what actually fires.
    """
    accels: dict[str, str] = {}
    used: set[str] = set()
    for a in apps:
        hk = (a.get("hotkey") or "").strip()
        if hk:
            accels[a["id"]] = hk
            used.add(hk.lower())
    slot = 1
    for a in apps:
        if not a.get("quick") or a["id"] in accels:
            continue
        while slot <= QUICK_SLOTS and f"ctrl+{slot}" in used:
            slot += 1
        if slot > QUICK_SLOTS:
            break
        accel = f"Ctrl+{slot}"
        accels[a["id"]] = accel
        used.add(accel.lower())
        slot += 1
    return accels


def quick_bindings(apps) -> list[tuple[str, str]]:
    return [(accel, app_id) for app_id, accel in quick_accels(apps).items()]


def app_for_accel(apps, accel: str) -> str | None:
    """Reverse lookup: which app does this accelerator launch, if any."""
    want = (accel or "").strip().lower()
    if not want:
        return None
    return next((aid for aid, ac in quick_accels(apps).items() if ac.lower() == want), None)
