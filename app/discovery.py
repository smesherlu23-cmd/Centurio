from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess

from . import log

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
    if os.name == "nt":
        try:
            apps += _discover_windows(icon_cache)
        except Exception:
            log.exception("Windows app discovery failed")
    for fn in (_steam_games, _epic_games):
        try:
            apps += fn(icon_cache)
        except Exception:
            log.exception("%s failed", getattr(fn, "__name__", fn))
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
                         "sub": a.get("sub", ""), "track_exe": a.get("track_exe"),
                         "poster": a.get("poster")}
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


#  Винда
_PS_ICON_FUNCS = r'''
$ErrorActionPreference='SilentlyContinue'
try{[Console]::OutputEncoding=[System.Text.Encoding]::UTF8}catch{}
$OutputEncoding=[System.Text.Encoding]::UTF8
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
  $f=Join-Path $cache ((Md5 $exe)+'_256.png')
  if(Test-Path -LiteralPath $f){ return $f }
  $bmp=$null
  if($script:CentBig){ try{ $bmp=[CentIcon]::Get($exe,256) }catch{ $bmp=$null } }
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
    # декод
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=0x08000000)  # CREATE_NO_WINDOW


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
        log.exception("_win_extract_one powershell failed for %s", path)
        return None
    out = (res.stdout or "").strip().splitlines()
    out = out[-1].strip() if out else ""
    return out if out and os.path.exists(out) else None


# стим
_STEAM_SKIP_ID = {"228980"} 
_STEAM_SKIP_NAME = ("steamworks common", "proton", "steam linux runtime", "steamvr media")

# Executables that live inside a game folder but aren't the game itself — never
# pick these as the process to watch for the "Запущено" indicator.
_STEAM_EXE_JUNK = ("unins", "uninstall", "vcredist", "vc_redist", "dxsetup", "dxwebsetup",
                   "directx", "redist", "crashhandler", "crashreport", "launcher", "setup",
                   "cleanup", "touchup", "dotnet", "oalinst", "notification_helper",
                   "prereq", "activation", "diagnostic", "helper", "reporter")


def _steam_game_exe(lib: str, installdir: str | None, name: str) -> str | None:
    """пока только для винды, но можно высрать из этого и под линукс и мак, но потом мб
    """
    if not installdir:
        return None
    root = os.path.join(lib, "steamapps", "common", installdir)
    if not os.path.isdir(root):
        return None
    candidates: list[tuple[int, str, str]] = []
    seen = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".exe"):
                continue
            seen += 1
            if seen > 20000:      # ограничение 
                break
            low = fn.lower()
            if any(j in low for j in _STEAM_EXE_JUNK):
                continue
            try:
                size = os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                continue
            candidates.append((size, fn, low))
        if seen > 20000:
            break
    if not candidates:
        return None
    tokens = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) >= 3]
    for _size, fn, low in sorted(candidates, key=lambda c: -c[0]):
        if any(t in low for t in tokens):
            return fn
    return max(candidates, key=lambda c: c[0])[1]


def steam_exe_for(path: str) -> str | None:
    m = re.match(r"steam://rungameid/(\d+)", path or "")
    if not m or os.name != "nt":
        return None
    appid = m.group(1)
    for root in _steam_roots():
        for lib in _steam_libraries(root):
            acf = os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf")
            try:
                with open(acf, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            exe = _steam_game_exe(lib, _vdf_val(text, "installdir"), _vdf_val(text, "name") or "")
            if exe:
                return exe
    return None


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
            log.exception("reading Steam path from registry failed")
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
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


_STEAM_ART_NAMES = (
    "capsule_616x353.jpg",   # 616x353 
    "header.jpg",            # 460x215 
    "library_hero.jpg",      
    "capsule_231x87.jpg",
)
_STEAM_PORTRAIT_HINTS = ("600x900", "library_600x900", "portrait")
_STEAM_CDN_HOSTS = ("cdn.cloudflare.steamstatic.com", "cdn.akamai.steamstatic.com")
_STEAM_CDN_ART = ("capsule_616x353.jpg", "header.jpg")


def _http_get(url: str, timeout: int = 8) -> bytes | None:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Centurio"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return resp.read()
    except Exception:
        return None


def _steam_cdn_art(appid: str, icon_cache: str | None) -> str | None:
    if not icon_cache:
        return None
    out = os.path.join(icon_cache, f"steam_{appid}_capsule.jpg")
    if os.path.exists(out):
        return out
    for name in _STEAM_CDN_ART:
        for host in _STEAM_CDN_HOSTS:
            data = _http_get(f"https://{host}/steam/apps/{appid}/{name}")
            if data and len(data) >= 1024:  
                try:
                    os.makedirs(icon_cache, exist_ok=True)
                    with open(out, "wb") as fh:
                        fh.write(data)
                    return out
                except OSError:
                    return None
    return None


def _steam_logo(cache: str, sub: str, appid: str) -> str | None:
    for p in (os.path.join(cache, f"{appid}_logo.png"), os.path.join(sub, "logo.png")):
        if os.path.exists(p):
            return p
    return None


def _steam_icon(root: str, appid: str, icon_cache: str | None = None) -> tuple[str | None, str]:

    cache = os.path.join(root, "appcache", "librarycache")
    sub = os.path.join(cache, str(appid))
    for name in _STEAM_ART_NAMES:
        for p in (os.path.join(cache, f"{appid}_{name}"), os.path.join(sub, name)):
            if os.path.exists(p):
                return p, "cover"
    if os.path.isdir(sub):
        imgs = glob.glob(os.path.join(sub, "*.jpg")) + glob.glob(os.path.join(sub, "*.png"))
        art = [p for p in imgs if os.path.isfile(p) and not any(
            k in os.path.basename(p).lower()
            for k in ("icon", "logo", *_STEAM_PORTRAIT_HINTS))]
        if art:
            return max(art, key=lambda p: os.path.getsize(p)), "cover"
    dl = _steam_cdn_art(appid, icon_cache)
    if dl:
        return dl, "cover"
    logo = _steam_logo(cache, sub, appid)
    if logo:
        return logo, "logo"
    icon = os.path.join(cache, f"{appid}_icon.jpg")
    if os.path.exists(icon):
        return icon, "contain"
    return None, "contain"

_STEAM_PORTRAIT_NAMES = ("library_600x900_2x.jpg", "library_600x900.jpg")


def _steam_portrait(root: str, appid: str, icon_cache: str | None = None) -> str | None:
    cache = os.path.join(root, "appcache", "librarycache")
    sub = os.path.join(cache, str(appid))
    for name in _STEAM_PORTRAIT_NAMES:
        for p in (os.path.join(cache, f"{appid}_{name}"), os.path.join(sub, name)):
            if os.path.exists(p):
                return p
    return _steam_cdn_portrait(appid, icon_cache)


def _steam_cdn_portrait(appid: str, icon_cache: str | None) -> str | None:
    if not icon_cache:
        return None
    out = os.path.join(icon_cache, f"steam_{appid}_portrait.jpg")
    if os.path.exists(out):
        return out
    for name in _STEAM_PORTRAIT_NAMES:
        for host in _STEAM_CDN_HOSTS:
            data = _http_get(f"https://{host}/steam/apps/{appid}/{name}")
            if data and len(data) >= 1024:
                try:
                    os.makedirs(icon_cache, exist_ok=True)
                    with open(out, "wb") as fh:
                        fh.write(data)
                    return out
                except OSError:
                    return None
    return None


def poster_for(path: str, icon_cache: str | None = None) -> str | None:
    m = re.match(r"steam://rungameid/(\d+)", path or "")
    if not m:
        return None
    appid = m.group(1)
    for root in _steam_roots():
        p = _steam_portrait(root, appid, icon_cache)
        if p:
            return p
    return _steam_cdn_portrait(appid, icon_cache)


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
                icon, fit = _steam_icon(root, appid, icon_cache)
                poster = _steam_portrait(root, appid, icon_cache)
                track = (_steam_game_exe(lib, _vdf_val(text, "installdir"), name)
                         if os.name == "nt" else None)
                games.append({"name": name, "path": f"steam://rungameid/{appid}",
                              "icon": icon, "icon_fit": fit, "source": "steam",
                              "sub": "Steam", "track_exe": track, "poster": poster})
    return games


# епик 
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
        track = os.path.basename(exe) if exe else None
        if icon_cache and loc and exe:
            full = os.path.join(loc, exe)
            if os.path.exists(full):
                icon = _win_extract_one(full, icon_cache)
        games.append({"name": name, "path": path, "icon": icon,
                      "icon_fit": "contain", "source": "epic", "sub": "Epic Games",
                      "track_exe": track})
    return games


# нннннннннннннн
def extract_icon(path: str, icon_cache: str | None) -> str | None:
    if not path or not icon_cache:
        return None
    try:
        if os.name == "nt" and path.lower().endswith(".exe") and os.path.exists(path):
            return _win_extract_one(path, icon_cache)
    except Exception:
        log.exception("extract_icon failed for %s", path)
    return None


def resolve_icon_for(path: str, icon_cache: str | None = None) -> tuple[str | None, str]:
    if not path:
        return None, "contain"
    m = re.match(r"steam://rungameid/(\d+)", path)
    if m:
        appid = m.group(1)
        for root in _steam_roots():
            icon, fit = _steam_icon(root, appid, icon_cache)
            if icon:
                return icon, fit
        dl = _steam_cdn_art(appid, icon_cache)
        return (dl, "cover") if dl else (None, "contain")
    try:
        if os.name == "nt" and path.lower().endswith(".exe") and os.path.exists(path):
            return _win_extract_one(path, icon_cache), "contain"
    except Exception:
        log.exception("resolve_icon_for failed for %s", path)
    return None, "contain"

ICON_SCHEMA = 7


def backfill_icons(store, icon_cache: str | None = None, refresh: bool = False) -> bool:
    changed = False
    for app in list(store.state().get("apps", [])):
        patch = {}
        path = app.get("path") or ""
        if refresh or not app.get("icon"):
            icon, fit = resolve_icon_for(path, icon_cache)
            if icon and (icon != app.get("icon") or fit != app.get("icon_fit")):
                patch["icon"] = icon
                patch["icon_fit"] = fit
        if not (app.get("sub") or "").strip():
            if path.startswith("steam://"):
                patch["sub"] = "Steam"
            elif path.startswith("com.epicgames.launcher://"):
                patch["sub"] = "Epic Games"
        if path.startswith("steam://") and not (app.get("track_exe") or "").strip():
            exe = steam_exe_for(path)
            if exe:
                patch["track_exe"] = exe
        if path.startswith("steam://") and (refresh or not app.get("poster")):
            poster = poster_for(path, icon_cache)
            if poster and poster != app.get("poster"):
                patch["poster"] = poster
        if patch:
            store.update_app(app["id"], patch)
            changed = True
    return changed
