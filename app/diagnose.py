"""Self-diagnostic for Centurio — run on the target machine to check that the
platform-specific bits work. Prints what's available and what discovery finds.

    python -m app.diagnose

Copy the output and share it when reporting an issue.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path


def _mod(name):
    try:
        __import__(name)
        return "OK"
    except Exception as exc:  # noqa: BLE001
        return f"MISSING ({exc.__class__.__name__})"


def run() -> None:
    print("=== Centurio diagnostics ===")
    print(f"Python      : {platform.python_version()} ({sys.executable})")
    print(f"Platform    : {platform.system()} {platform.release()} ({os.name})")
    print("Dependencies:")
    for m in ("flet", "pystray", "PIL", "pynput", "psutil"):
        print(f"  {m:10}: {_mod(m)}")

    from app.store import default_data_path
    print(f"Data file   : {default_data_path()}")
    icon_cache = str(default_data_path().parent / "icons")

    print("\n=== Discovery ===")
    from app import discovery
    t0 = time.time()
    apps = discovery.discover_apps(icon_cache)
    dt = time.time() - t0
    games = [a for a in apps if a.get("source") in ("steam", "epic")]
    with_icon = [a for a in apps if a.get("icon")]
    print(f"Found {len(apps)} entries in {dt:.1f}s "
          f"({len(games)} games, {len(with_icon)} with icons)")
    print("Sample (up to 20):")
    for a in apps[:20]:
        icon = "🖼" if a.get("icon") else "·"
        print(f"  [{a.get('source',''):8}] {icon} {a['name'][:40]:40} {a.get('path','')[:60]}")

    print("\n=== Steam roots ===")
    for r in discovery._steam_roots():
        print(f"  {r}")
    if not discovery._steam_roots():
        print("  (none found)")

    print("\nDone. Share this output when reporting an issue.")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    run()
