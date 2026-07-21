"""Discover applications (and games) already installed on the system.

Sources:
  * Windows — Start Menu shortcuts, Programs & Features (Uninstall) and
    registered App Paths; real .exe icons are extracted to a PNG cache.
  * Linux   — .desktop entries (icon resolved from the icon theme / pixmaps).
  * macOS   — .app bundles (.icns converted to PNG via `sips`).
  * Games   — Steam (installed appmanifest_*.acf, launched via steam://…) and,
    on Windows, Epic Games (launcher manifests).

`discover_apps(icon_cache)` returns a de-duplicated, sorted list of
{"name", "path", "icon", "source"} dicts. `icon` is an absolute image path or
None. Nothing here raises — on error it returns whatever was found.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

_JUNK_TOKENS = ("uninstall", "удал", "readme", "read me", "help", "документац",
                "documentation", "release notes", "website", "на сайт", "лиценз",
                "license", "manual", "руководств", "support", "поддержк")

_WIN_NAME_JUNK = ("node.js", "command prompt", "командная строка", "stack builder",
                  "recovery drive", "диск восстановлен", "verifier", "debugger",
                  "redistributable", "runtime", "hotfix", "update for", "sdk ",
                  "web platform", "webview")


def discover_apps(icon_cache: str | None = None) -> list[dict]:
    if icon_cache:
        try:
            os.makedirs(icon_cache, exist_ok=True)
        except OSError:
            icon_cache = None
    apps: list[dict] = []
    try:
        if os.name == "nt":
            apps += _discover_windows(icon_cache)
        elif sys.platform == "darwin":
            apps += _discover_macos(icon_cache)
        else:
            apps += _discover_linux(icon_cache)
    except Exception:
        pass
    # Games (cross-platform Steam, Windows Epic).
    for fn in (_steam_games, _epic_games):
        try:
            apps += fn(icon_cache)
        except Exception:
            pass
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
            seen[key] = {"name": name, "path": path, "icon": a.get("icon"),
                         "icon_fit": a.get("icon_fit", "contain"), "source": a.get("source", ""),
                         "sub": a.get("sub", "")}
        elif not seen[key].get("icon") and a.get("icon"):
            seen[key]["icon"] = a.get("icon")
            seen[key]["icon_fit"] = a.get("icon_fit", "contain")
    return sorted(seen.values(), key=lambda x: x["name"].lower())


def _looks_like_junk(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _JUNK_TOKENS)


def _is_windows_system(name: str, path: str) -> bool:
    """True for OS/system executables the user shouldn't need to launch."""
    p = (path or "").lower().replace("/", "\\")
    if "\\windows\\" in f"\\{p}" or p.startswith(os.environ.get("SystemRoot", "c:\\windows").lower()):
        return True
    n = (name or "").lower()
    if _looks_like_junk(name) or any(t in n for t in _WIN_NAME_JUNK):
        return True
    return False


def _md5(text: str) -> str:
    return hashlib.md5(text.lower().encode("utf-8")).hexdigest()


# ================= Windows =================
# Shared icon-extraction helpers. Uses the built-in ExtractAssociatedIcon
# (always available on Windows PowerShell 5.1, no custom compilation) and, when
# it compiles, a P/Invoke path for a larger 96px icon. Either way an icon is
# produced — the earlier version silently failed when the inline C# didn't
# compile, so regular apps got no icons.
_PS_ICON_FUNCS = r'''
$ErrorActionPreference='SilentlyContinue'
$cache=__CACHE__
Add-Type -AssemblyName System.Drawing
$script:CentBig=$false
try {
  Add-Type -ReferencedAssemblies 'System.Drawing' -TypeDefinition @"
using System;using System.Runtime.InteropServices;using System.Drawing;
public class CentIcon {
 [DllImport("user32.dll")] public static extern int PrivateExtractIcons(string p,int i,int cx,int cy,IntPtr[] h,int[] id,int n,int f);
 [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr h);
 public static Bitmap Get(string p,int s){ IntPtr[] h=new IntPtr[1]; int[] id=new int[1]; int r=PrivateExtractIcons(p,0,s,s,h,id,1,0); if(r>0 && h[0]!=IntPtr.Zero){ Icon ic=Icon.FromHandle(h[0]); Bitmap b=new Bitmap(ic.ToBitmap()); DestroyIcon(h[0]); return b; } return null; } }
"@
  $script:CentBig=$true
} catch { $script:CentBig=$false }
function Md5($s){ $m=[System.Security.Cryptography.MD5]::Create(); (($m.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($s.ToLower())))|ForEach-Object{$_.ToString('x2')}) -join '' }
function Save-Icon($exe){
  if(-not $cache){ return $null }
  if(-not (Test-Path -LiteralPath $exe)){ return $null }
  $f=Join-Path $cache ((Md5 $exe)+'.png')
  if(Test-Path -LiteralPath $f){ return $f }
  $bmp=$null
  if($script:CentBig){ try{ $bmp=[CentIcon]::Get($exe,96) }catch{ $bmp=$null } }
  if(-not $bmp){ try{ $ic=[System.Drawing.Icon]::ExtractAssociatedIcon($exe); if($ic){ $bmp=$ic.ToBitmap() } }catch{ $bmp=$null } }
  if($bmp){ try{ $bmp.Save($f,[System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose(); return $f }catch{} }
  return $null
}
'''

_WIN_PS = _PS_ICON_FUNCS + r'''
$sh=New-Object -ComObject WScript.Shell
$out=New-Object System.Collections.ArrayList
function Add-App($n,$p){ if(-not $n -or -not $p){ return }; if($p.ToLower() -like '*\windows\*'){ return }; $ic=Save-Icon $p; [void]$out.Add([PSCustomObject]@{name="$n";path="$p";icon=$ic}) }

$menus=@(__DIRS__)
foreach($d in $menus){
  Get-ChildItem -LiteralPath $d -Recurse -Filter *.lnk 2>$null | ForEach-Object {
    $t=$sh.CreateShortcut($_.FullName); $p=$t.TargetPath
    if($p -and $p.ToLower().EndsWith('.exe') -and (Test-Path -LiteralPath $p)){ Add-App $_.BaseName $p }
  }
}
$uks=@('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')
foreach($k in $uks){
  Get-ChildItem -LiteralPath $k 2>$null | ForEach-Object {
    $pr=Get-ItemProperty -LiteralPath $_.PSPath 2>$null
    if(-not $pr.DisplayName){ return }
    if($pr.SystemComponent -eq 1){ return }
    $icon=$pr.DisplayIcon
    if($icon){ $exe=($icon -split ',')[0].Trim('"'); if($exe -and $exe.ToLower().EndsWith('.exe') -and (Test-Path -LiteralPath $exe)){ Add-App $pr.DisplayName $exe } }
  }
}
$aps=@('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths')
foreach($k in $aps){
  Get-ChildItem -LiteralPath $k 2>$null | ForEach-Object {
    $p=(Get-Item -LiteralPath $_.PSPath).GetValue(''); if($p){ $p=$p.Trim('"') }
    if($p -and $p.ToLower().EndsWith('.exe') -and (Test-Path -LiteralPath $p)){ Add-App ([System.IO.Path]::GetFileNameWithoutExtension($p)) $p }
  }
}
$out | ConvertTo-Json -Compress
'''

_WIN_ICON_ONE_PS = _PS_ICON_FUNCS + r'''
$r=Save-Icon __EXE__
if($r){ Write-Output $r }
'''


def _run_powershell(script: str, timeout: int = 60):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=timeout,
                          creationflags=0x08000000)  # CREATE_NO_WINDOW


def _ps_literal(value: str | None) -> str:
    if not value:
        return "$null"
    return "'" + value.replace("'", "''") + "'"


def _discover_windows(icon_cache: str | None) -> list[dict]:
    prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA", "")
    dirs = [os.path.join(prog_data, r"Microsoft\Windows\Start Menu\Programs")]
    if appdata:
        dirs.append(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"))
    dirs = [d for d in dirs if os.path.isdir(d)]
    dir_list = ",".join(_ps_literal(d) for d in dirs)

    ps = _WIN_PS.replace("__DIRS__", dir_list).replace("__CACHE__", _ps_literal(icon_cache))
    res = _run_powershell(ps, timeout=90)
    out = (res.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    apps = []
    for x in data:
        name, path = x.get("name"), x.get("path")
        if not name or not path or _is_windows_system(name, path):
            continue
        apps.append({"name": name, "path": path, "icon": x.get("icon"),
                     "icon_fit": "contain", "source": "windows"})
    return apps


def _win_extract_one(path: str, icon_cache: str) -> str | None:
    ps = _WIN_ICON_ONE_PS.replace("__CACHE__", _ps_literal(icon_cache)).replace(
        "__EXE__", _ps_literal(path))
    try:
        res = _run_powershell(ps, timeout=25)
    except Exception:
        return None
    out = (res.stdout or "").strip().splitlines()
    out = out[-1].strip() if out else ""
    return out if out and os.path.exists(out) else None


# ================= Linux =================
_LINUX_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
]
_ICON_THEME_SIZES = ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48", "32x32")
_PIXMAP_DIRS = ("/usr/share/pixmaps", "/usr/local/share/pixmaps")


def _discover_linux(icon_cache: str | None) -> list[dict]:
    apps = []
    for d in _LINUX_DIRS:
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.desktop")):
            entry = _parse_desktop(f)
            if entry and not _looks_like_junk(entry["name"]):
                apps.append(entry)
    return apps


def _icon_theme_dirs() -> list[str]:
    """Base dirs that may contain an `icons/<theme>/…` tree, per the XDG icon
    theme spec, plus Flatpak/Snap export locations (not always covered by
    $XDG_DATA_DIRS) so icons for sandboxed apps resolve too."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local/share"), os.path.join(home, ".icons")]
    xdg = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs += [d for d in xdg.split(":") if d]
    dirs += ["/var/lib/flatpak/exports/share",
             os.path.join(home, ".local/share/flatpak/exports/share"),
             "/var/lib/snapd/desktop"]
    out = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def _resolve_linux_icon(icon_field: str | None) -> str | None:
    if not icon_field:
        return None
    if os.path.isabs(icon_field):
        return icon_field if os.path.exists(icon_field) and icon_field.lower().endswith(
            (".png", ".jpg", ".jpeg", ".svg")) else None
    name = icon_field
    for d in _PIXMAP_DIRS:
        p = os.path.join(d, name + ".png")
        if os.path.exists(p):
            return p
    bases = _icon_theme_dirs()
    # Themed raster icons, biggest first, searched across every icon theme
    # (not just hicolor) since many distros ship Papirus/Breeze/Adwaita etc.
    for size in _ICON_THEME_SIZES:
        for base in bases:
            for p in glob.glob(os.path.join(base, "icons", "*", size, "apps", name + ".png")):
                return p
            for p in glob.glob(os.path.join(base, "icons", "*", "*", size, "apps", name + ".png")):
                return p
    # Scalable SVG fallback, any theme.
    for base in bases:
        for p in glob.glob(os.path.join(base, "icons", "*", "scalable", "apps", name + ".svg")):
            return p
        for p in glob.glob(os.path.join(base, "icons", "*", "*", "scalable", "apps", name + ".svg")):
            return p
    return None


def _parse_desktop(path: str) -> dict | None:
    name = exec_cmd = typ = tryexec = icon = None
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
                elif key == "Icon" and icon is None:
                    icon = val.strip()
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
    return {"name": name, "path": resolved, "icon": _resolve_linux_icon(icon),
            "icon_fit": "contain", "source": "desktop"}


# ================= macOS =================
def _discover_macos(icon_cache: str | None) -> list[dict]:
    dirs = ["/Applications", os.path.expanduser("~/Applications"),
            "/System/Applications", "/System/Applications/Utilities",
            "/Applications/Utilities"]
    apps = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            if entry.endswith(".app"):
                p = os.path.join(d, entry)
                apps.append({"name": entry[:-4], "path": p,
                             "icon": _macos_icon(p, icon_cache), "icon_fit": "contain",
                             "source": "app"})
    return apps


def _macos_icon(app_path: str, icon_cache: str | None) -> str | None:
    if not icon_cache:
        return None
    res_dir = os.path.join(app_path, "Contents", "Resources")
    icns = glob.glob(os.path.join(res_dir, "*.icns"))
    if not icns:
        return None
    out = os.path.join(icon_cache, _md5(app_path) + ".png")
    if os.path.exists(out):
        return out
    try:
        subprocess.run(["sips", "-s", "format", "png", "-Z", "128", icns[0], "--out", out],
                       capture_output=True, timeout=10)
    except Exception:
        return None
    return out if os.path.exists(out) else None


# ================= Steam =================
_STEAM_SKIP_ID = {"228980"}  # Steamworks Common Redistributables
_STEAM_SKIP_NAME = ("steamworks common", "proton", "steam linux runtime", "steamvr media")


def _steam_roots() -> list[str]:
    roots = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                p, _ = winreg.QueryValueEx(k, "SteamPath")
                if p:
                    roots.append(p)
        except Exception:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    elif sys.platform == "darwin":
        roots.append(os.path.expanduser("~/Library/Application Support/Steam"))
    else:
        roots += [os.path.expanduser("~/.steam/steam"),
                  os.path.expanduser("~/.local/share/Steam"),
                  os.path.expanduser("~/.steam/root")]
    return [r for r in dict.fromkeys(roots) if r and os.path.isdir(r)]


def _steam_libraries(root: str) -> list[str]:
    libs = [root]
    vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            libs.append(m.group(1).replace("\\\\", "\\"))
    except OSError:
        pass
    return list(dict.fromkeys(libs))


def _vdf_val(text: str, key: str) -> str | None:
    m = re.search(r'"%s"\s*"([^"]*)"' % re.escape(key), text, re.IGNORECASE)
    return m.group(1) if m else None


def _steam_icon(root: str, appid: str) -> tuple[str | None, str]:
    """Return (image_path, fit) for a Steam game. Handles both the old flat
    librarycache naming and the newer per-appid subfolder layout."""
    cache = os.path.join(root, "appcache", "librarycache")
    # Flat layout: a small square icon reads best centered (contain).
    icon = os.path.join(cache, f"{appid}_icon.jpg")
    if os.path.exists(icon):
        return icon, "contain"
    # Flat layout: cover-style art fills the whole tile.
    for suffix in (f"{appid}_library_600x900.jpg", f"{appid}_header.jpg",
                   f"{appid}_capsule_616x353.jpg", f"{appid}_capsule_231x87.jpg",
                   f"{appid}_library_hero.jpg", f"{appid}_logo.png"):
        p = os.path.join(cache, suffix)
        if os.path.exists(p):
            return p, "cover"
    # Newer layout: appcache/librarycache/<appid>/<hash>.(jpg|png)
    sub = os.path.join(cache, str(appid))
    if os.path.isdir(sub):
        imgs = glob.glob(os.path.join(sub, "*.jpg")) + glob.glob(os.path.join(sub, "*.png"))
        imgs = [p for p in imgs if os.path.isfile(p)]
        if imgs:
            best = max(imgs, key=lambda p: os.path.getsize(p))
            fit = "contain" if "icon" in os.path.basename(best).lower() else "cover"
            return best, fit
    return None, "contain"


def _steam_games(icon_cache: str | None) -> list[dict]:
    games = []
    seen = set()
    for root in _steam_roots():
        for lib in _steam_libraries(root):
            for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
                try:
                    with open(acf, encoding="utf-8", errors="ignore") as fh:
                        text = fh.read()
                except OSError:
                    continue
                appid = _vdf_val(text, "appid")
                name = _vdf_val(text, "name")
                if not appid or not name or appid in _STEAM_SKIP_ID or appid in seen:
                    continue
                if any(s in name.lower() for s in _STEAM_SKIP_NAME):
                    continue
                seen.add(appid)
                icon, fit = _steam_icon(root, appid)
                games.append({"name": name, "path": f"steam://rungameid/{appid}",
                              "icon": icon, "icon_fit": fit, "source": "steam", "sub": "Steam"})
    return games


# ================= Epic Games (Windows) =================
def _epic_games(icon_cache: str | None) -> list[dict]:
    if os.name != "nt":
        return []
    mani = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                        "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(mani):
        return []
    games = []
    for f in glob.glob(os.path.join(mani, "*.item")):
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                d = json.load(fh)
        except Exception:
            continue
        name = d.get("DisplayName")
        if not name or d.get("bIsIncompleteInstall"):
            continue
        app_name = d.get("MainGameAppName") or d.get("AppName")
        path = None
        if app_name:
            path = (f"com.epicgames.launcher://apps/{app_name}"
                    "?action=launch&silent=true")
        else:
            loc, exe = d.get("InstallLocation"), d.get("LaunchExecutable")
            if loc and exe:
                path = os.path.join(loc, exe)
        if not path:
            continue
        icon = None
        loc, exe = d.get("InstallLocation"), d.get("LaunchExecutable")
        if icon_cache and loc and exe:
            full = os.path.join(loc, exe)
            if os.path.exists(full):
                icon = _win_extract_one(full, icon_cache)
        games.append({"name": name, "path": path, "icon": icon,
                      "icon_fit": "contain", "source": "epic", "sub": "Epic Games"})
    return games


# ================= single-icon extraction (manual add) =================
def extract_icon(path: str, icon_cache: str | None) -> str | None:
    """Best-effort icon for a manually chosen file."""
    if not path or not icon_cache:
        return None
    try:
        if os.name == "nt" and path.lower().endswith(".exe") and os.path.exists(path):
            return _win_extract_one(path, icon_cache)
        if sys.platform == "darwin" and path.endswith(".app"):
            return _macos_icon(path, icon_cache)
    except Exception:
        return None
    return None


def resolve_icon_for(path: str, icon_cache: str | None = None) -> tuple[str | None, str]:
    """(icon, fit) for an already-stored app path (Steam URL or a file)."""
    if not path:
        return None, "contain"
    m = re.match(r"steam://rungameid/(\d+)", path)
    if m:
        appid = m.group(1)
        for root in _steam_roots():
            icon, fit = _steam_icon(root, appid)
            if icon:
                return icon, fit
        return None, "contain"
    try:
        if os.name == "nt" and path.lower().endswith(".exe") and os.path.exists(path):
            return _win_extract_one(path, icon_cache), "contain"
        if sys.platform == "darwin" and path.endswith(".app"):
            return _macos_icon(path, icon_cache), "contain"
    except Exception:
        pass
    return None, "contain"


def backfill_icons(store, icon_cache: str | None = None) -> bool:
    """Fill in icons and the "sub" label (e.g. "Steam") for apps added before
    that metadata existed or before art was cached."""
    changed = False
    for app in list(store.state().get("apps", [])):
        patch = {}
        path = app.get("path") or ""
        if not app.get("icon"):
            icon, fit = resolve_icon_for(path, icon_cache)
            if icon:
                patch["icon"] = icon
                patch["icon_fit"] = fit
        if not (app.get("sub") or "").strip():
            if path.startswith("steam://"):
                patch["sub"] = "Steam"
            elif path.startswith("com.epicgames.launcher://"):
                patch["sub"] = "Epic Games"
        if patch:
            store.update_app(app["id"], patch)
            changed = True
    return changed
