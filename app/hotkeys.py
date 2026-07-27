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
        elif p.startswith("f") and p[1:].isdigit():
            out.append(f"<{p}>")
        else:
            out.append(f"<{p}>")
    return "+".join(out)


class HotkeyManager:
    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self._listener = None
        self.available = False
        self.rejected: list[str] = []

    def _build_mapping(self, keyboard, bindings):
        """Turn accelerators into a pynput mapping, dropping the unusable ones.

        GlobalHotKeys parses its whole mapping in the constructor, so a single
        unparseable combo would take every other hotkey down with it. Validating
        one at a time keeps the good bindings working. Returns (mapping,
        rejected); kept separate from register() so it is testable without
        starting a real keyboard listener.
        """
        parse = getattr(keyboard.HotKey, "parse", None)
        mapping = {}
        rejected = []
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
        return mapping, rejected

    def register(self, bindings) -> bool:
        self.stop()
        self.rejected = []
        try:
            from pynput import keyboard
        except Exception:
            self.available = False
            return False

        mapping, self.rejected = self._build_mapping(keyboard, bindings)
        if not mapping:
            self.available = False
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
            return False

    def _fire(self, app_id):
        try:
            self.on_trigger(app_id)
        except Exception:
            pass

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


def quick_bindings(apps) -> list[tuple[str, str]]:
    bindings = []
    used = set()
    for a in apps:
        hk = a.get("hotkey")
        if hk:
            bindings.append((hk, a["id"]))
            used.add(hk.lower())
    i = 0
    for a in apps:
        if not a.get("quick") or a.get("hotkey"):
            continue
        i += 1
        if i > 9:
            break
        accel = f"Ctrl+{i}"
        if accel.lower() in used:
            continue
        bindings.append((accel, a["id"]))
    return bindings
