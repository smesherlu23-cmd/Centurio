"""Discover applications already installed on the system.

Instead of hunting for a raw .exe across the disk, Centurio enumerates the
places the OS already lists installed apps:

  * Windows — Start Menu shortcuts (.lnk), resolved to their target .exe.
  * Linux   — .desktop entries in the standard application directories.
  * macOS   — .app bundles in the Applications folders.

`discover_apps()` returns a de-duplicated, alphabetically sorted list of
{"name", "path", "source"} dicts. It never raises — on any error it returns
whatever it found (possibly an empty list), so the UI can fall back to a
manual file picker.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

_JUNK_TOKENS = ("uninstall", "удал", "readme", "read me", "help", "документац",
                "documentation", "release notes", "website", "на сайт", "лиценз",
                "license", "manual", "руководств", "support", "поддержк")


def discover_apps() -> list[dict]:
    try:
        if os.name == "nt":
            apps = _discover_windows()
        elif sys.platform == "darwin":
            apps = _discover_macos()
        else:
            apps = _discover_linux()
    except Exception:
        return []
    return _dedupe(apps)


def _dedupe(apps: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for a in apps:
        path = (a.get("path") or "").strip()
        name = (a.get("name") or "").strip()
        if not path or not name:
            continue
        key = path.lower()
        if key not in seen:
            seen[key] = {"name": name, "path": path, "source": a.get("source", "")}
    return sorted(seen.values(), key=lambda x: x["name"].lower())


def _looks_like_junk(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _JUNK_TOKENS)


# ---------------- Windows ----------------
def _discover_windows() -> list[dict]:
    prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA", "")
    dirs = [os.path.join(prog_data, r"Microsoft\Windows\Start Menu\Programs")]
    if appdata:
        dirs.append(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"))
    dirs = [d for d in dirs if os.path.isdir(d)]
    if not dirs:
        return []

    dir_list = ",".join("'" + d.replace("'", "''") + "'" for d in dirs)
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$sh=New-Object -ComObject WScript.Shell;"
        f"$dirs=@({dir_list});$out=@();"
        "foreach($d in $dirs){"
        " Get-ChildItem -LiteralPath $d -Recurse -Filter *.lnk 2>$null | ForEach-Object {"
        "  $t=$sh.CreateShortcut($_.FullName);$p=$t.TargetPath;"
        "  if($p -and $p.ToLower().EndsWith('.exe') -and (Test-Path -LiteralPath $p)){"
        "   $out+=[PSCustomObject]@{name=$_.BaseName;path=$p}}}}"
        "$out|ConvertTo-Json -Compress"
    )
    import json
    creationflags = 0x08000000  # CREATE_NO_WINDOW
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, timeout=30, creationflags=creationflags)
    out = (res.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    apps = []
    for x in data:
        name, path = x.get("name"), x.get("path")
        if not name or not path or _looks_like_junk(name):
            continue
        apps.append({"name": name, "path": path, "source": "startmenu"})
    return apps


# ---------------- Linux ----------------
_LINUX_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
]


def _discover_linux() -> list[dict]:
    apps = []
    for d in _LINUX_DIRS:
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.desktop")):
            entry = _parse_desktop(f)
            if entry and not _looks_like_junk(entry["name"]):
                apps.append(entry)
    return apps


def _parse_desktop(path: str) -> dict | None:
    name = exec_cmd = typ = tryexec = None
    nodisplay = hidden = False
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            in_entry = False
            for raw in fh:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key == "Name" and name is None:
                    name = val.strip()
                elif key == "Exec" and exec_cmd is None:
                    exec_cmd = val.strip()
                elif key == "TryExec":
                    tryexec = val.strip()
                elif key == "Type":
                    typ = val.strip()
                elif key == "NoDisplay":
                    nodisplay = val.strip().lower() == "true"
                elif key == "Hidden":
                    hidden = val.strip().lower() == "true"
    except OSError:
        return None

    if nodisplay or hidden or (typ and typ != "Application"):
        return None
    if not name or not exec_cmd:
        return None

    cmd = re.sub(r"%[fFuUdDnNickvm]", "", exec_cmd).strip()
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    if not tokens:
        return None
    prog = tokens[0]
    resolved = prog if os.path.isabs(prog) else shutil.which(prog)
    if (not resolved or not os.path.exists(resolved)) and tryexec:
        resolved = tryexec if os.path.isabs(tryexec) else shutil.which(tryexec)
    if not resolved or not os.path.exists(resolved):
        return None
    return {"name": name, "path": resolved, "source": "desktop"}


# ---------------- macOS ----------------
def _discover_macos() -> list[dict]:
    dirs = ["/Applications", os.path.expanduser("~/Applications"),
            "/System/Applications", "/System/Applications/Utilities",
            "/Applications/Utilities"]
    apps = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            if entry.endswith(".app"):
                apps.append({"name": entry[:-4], "path": os.path.join(d, entry),
                             "source": "app"})
    return apps
