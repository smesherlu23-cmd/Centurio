from __future__ import annotations

_MODS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "option": "<alt>",
    "shift": "<shift>",
    "win": "<cmd>", "cmd": "<cmd>", "super": "<cmd>", "meta": "<cmd>",
}


def to_pynput(accel: str) -> str:


    """по хорошему нужно сделать нормальный парсер, а не эту хуйню. еблан"""


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

    def register(self, bindings) -> bool:
        self.stop()
        try:
            from pynput import keyboard
        except Exception:
            self.available = False
            return False

        mapping = {}
        for accel, app_id in bindings:
            if not accel:
                continue
            try:
                combo = to_pynput(accel)
                if combo:
                    mapping[combo] = (lambda aid=app_id: self._fire(aid))
            except Exception:
                continue
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
