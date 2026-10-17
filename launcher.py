"""
Starting a Paradox game directly, with a chosen list of mods in a chosen order.

How the official launcher does it (checked on a real CK3 1.20 install):
  * <install>/launcher/launcher-settings.json names the game exe (exePath, relative to the launcher
    folder), its arguments (exeArgs, e.g. -gdpr-compliant), the version and the Documents data folder.
  * When you press Play, the launcher writes the active playset's enabled mods, in order, into
    Documents/Paradox Interactive/<game>/dlc_load.json:
        {"enabled_mods": ["mod/2871648329.mod", ...], "disabled_dlcs": []}
    (newer launcher versions use content_load.json for Victoria 3 and EU5) and then starts the exe.
    The game has no command-line option for mods; it reads that file.
  * Playsets themselves live in launcher-v2.sqlite next to it.
So "Play" here = write that file (after a backup) + start the exe with its arguments. The launcher's
database is only read (import) unless you explicitly export a playset into it.
"""
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

IS_WIN = sys.platform.startswith("win")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LauncherError(Exception):
    pass


# Documents folder name -> what we know about the game
GAMES = {
    "Crusader Kings III": {"appid": "1158310", "id": "ck3", "load": "dlc_load.json",
                           "names": ["Crusader Kings III", "Crusader Kings 3"], "exe": ["binaries/ck3.exe"]},
    "Stellaris": {"appid": "281990", "id": "stellaris", "load": "dlc_load.json",
                  "names": ["Stellaris"], "exe": ["stellaris.exe"]},
    "Hearts of Iron IV": {"appid": "394360", "id": "hoi4", "load": "dlc_load.json",
                          "names": ["Hearts of Iron IV", "Hearts of Iron 4"], "exe": ["hoi4.exe"]},
    "Europa Universalis IV": {"appid": "236850", "id": "eu4", "load": "dlc_load.json",
                              "names": ["Europa Universalis IV", "Europa Universalis 4"], "exe": ["eu4.exe"]},
    "Imperator": {"appid": "859580", "id": "imperator", "load": "dlc_load.json",
                  "names": ["Imperator: Rome", "Imperator Rome", "Imperator"], "exe": ["binaries/imperator.exe"]},
    "Victoria 3": {"appid": "529340", "id": "victoria3", "load": "content_load.json",
                   "names": ["Victoria 3", "Victoria III"], "exe": ["binaries/victoria3.exe"]},
    "Europa Universalis V": {"appid": "3450310", "id": "eu5", "load": "content_load.json",
                             "names": ["Europa Universalis V", "Europa Universalis 5"], "exe": ["binaries/eu5.exe"]},
    "Crusader Kings II": {"appid": "203770", "id": "ck2", "load": None,
                          "names": ["Crusader Kings II", "Crusader Kings 2"], "exe": ["CK2game.exe"]},
}


def game_info(game):
    return GAMES.get(game, {})


def data_dir_of(mod_dir):
    """Documents/Paradox Interactive/<game> for its mod folder."""
    return os.path.dirname(os.path.normpath(mod_dir))


# ================================================================== finding the installed game
def _reg_values(root, path, view=0):
    import winreg
    out = {}
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[n] = v
                i += 1
    except OSError:
        pass
    return out


def _reg_subkeys(root, path, view=0):
    import winreg
    out = []
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def steam_libraries():
    """Steam library folders (from the registry and libraryfolders.vdf)."""
    if not IS_WIN:
        return []
    import winreg
    roots = []
    for hive, path, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        v = _reg_values(hive, path).get(name)
        if v and os.path.isdir(v):
            roots.append(os.path.normpath(v))
    libs = []
    for r in roots:
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                for p in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                    libs.append(os.path.normpath(p.replace("\\\\", "\\")))
        except OSError:
            pass
    return list(dict.fromkeys(l for l in libs if os.path.isdir(l)))


def _steam_install(appid):
    for lib in steam_libraries():
        acf = os.path.join(lib, "steamapps", f"appmanifest_{appid}.acf")
        try:
            with open(acf, encoding="utf-8", errors="replace") as f:
                m = re.search(r'"installdir"\s+"([^"]+)"', f.read())
        except OSError:
            continue
        if m:
            d = os.path.join(lib, "steamapps", "common", m.group(1))
            if os.path.isdir(d):
                return d
    return ""


def _registry_installs(names):
    """Install folders from GOG's registry keys and Windows' list of installed programs."""
    if not IS_WIN:
        return []
    import winreg
    want = [n.lower() for n in names]
    out = []
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        base = r"SOFTWARE\GOG.com\Games"
        for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, base, view):
            v = _reg_values(winreg.HKEY_LOCAL_MACHINE, base + "\\" + sub, view)
            if str(v.get("gameName", "")).lower() in want and v.get("path"):
                out.append(v["path"])
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            for sub in _reg_subkeys(hive, base, view):
                v = _reg_values(hive, base + "\\" + sub, view)
                name = str(v.get("DisplayName", "")).lower()
                loc = v.get("InstallLocation") or ""
                if loc and any(name == w or name.startswith(w + " ") or name.startswith(w + ":") for w in want):
                    out.append(loc)
    return [os.path.normpath(p) for p in dict.fromkeys(out) if os.path.isdir(p)]


def looks_like_install(game, folder):
    if not folder or not os.path.isdir(folder):
        return False
    s = read_launcher_settings(folder)
    if s and s.get("gameId") and game_info(game).get("id") and s["gameId"] != game_info(game)["id"]:
        return False
    if s:
        return True
    return any(os.path.isfile(os.path.join(folder, e)) for e in game_info(game).get("exe", []))


def on_steam(game):
    """Is this game installed through Steam on this PC? (a good hint that it's owned there)"""
    info = game_info(game)
    try:
        return bool(info and _steam_install(info["appid"]))
    except Exception:
        return False


def find_installs(game):
    """Install folders of this game found on this PC (Steam, GOG, installed-programs list)."""
    info = game_info(game)
    if not info:
        return []
    found = []
    d = _steam_install(info["appid"])
    if d:
        found.append(d)
    found += _registry_installs(info["names"])
    return [f for f in dict.fromkeys(found) if looks_like_install(game, f)]


# ================================================================== launcher-settings.json
def read_launcher_settings(install):
    p = os.path.join(install, "launcher", "launcher-settings.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def game_exe(game, install):
    """(exe path, [arguments], version text, platform) for starting the game the way the launcher does."""
    s = read_launcher_settings(install)
    exe, args = "", []
    if s.get("exePath"):
        exe = os.path.normpath(os.path.join(install, "launcher", s["exePath"]))
        args = [a for a in s.get("exeArgs", []) if isinstance(a, str)]
    if not exe or not os.path.isfile(exe):
        for cand in game_info(game).get("exe", []):
            p = os.path.join(install, cand)
            if os.path.isfile(p):
                exe = p
                break
    if not exe or not os.path.isfile(exe):
        raise LauncherError(f"couldn't find the game's .exe in {install}")
    return exe, args, s.get("version", ""), s.get("distPlatform", "")


def installed_version(install):
    """'1.20.0.2' from launcher-settings.json ('1.20.0.2 (Crozier)'), or ''."""
    m = re.search(r"\d+(\.\d+)+", read_launcher_settings(install).get("version", "") or "")
    return m.group(0) if m else ""


# ================================================================== the load file
def read_load_file(game, data_dir):
    """Mod list the game will load next: [.mod file names] in order (from dlc_load/content_load)."""
    name = game_info(game).get("load") or "dlc_load.json"
    p = os.path.join(data_dir, name)
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return []
    entries = d.get("enabled_mods") or d.get("enabledMods") or []
    out = []
    for e in entries:
        v = e.get("path", "") if isinstance(e, dict) else str(e)
        out.append(os.path.basename(v.replace("\\", "/").rstrip("/")))
    return [k if k.lower().endswith(".mod") else k + ".mod" for k in out if k]


def _backup(path, backup_dir, keep=15):
    if not os.path.isfile(path):
        return ""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.basename(path)
    dst = os.path.join(backup_dir, f"{stamp}_{base}")
    shutil.copy2(path, dst)
    olds = sorted(f for f in os.listdir(backup_dir) if f.endswith("_" + base))
    for f in olds[:-keep]:
        try:
            os.remove(os.path.join(backup_dir, f))
        except OSError:
            pass
    return dst


def write_load_file(game, data_dir, mod_keys, backup_dir):
    """Make the game load exactly these .mod files, in this order. DLC settings are left untouched.
    Returns the path written."""
    info = game_info(game)
    name = info.get("load")
    if not name:
        raise LauncherError(f"starting {game} with a mod list isn't supported")
    path = os.path.join(data_dir, name)
    existing = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    if name == "dlc_load.json":
        data = dict(existing) if isinstance(existing, dict) else {}
        data["enabled_mods"] = ["mod/" + k for k in mod_keys]
        data.setdefault("disabled_dlcs", [])
    else:
        # content_load.json: copy the shape the official launcher used last time
        sample = (existing.get("enabledMods") or [None])[0] if isinstance(existing, dict) else None
        if sample is None:
            raise LauncherError(f"{name} has no example entry yet. Start the game once from the official "
                                "launcher with at least one mod enabled, then Play works from here.")
        mod_dir = os.path.join(data_dir, "mod")

        def entry(k):
            folder_style = isinstance(sample, dict) and not str(sample.get("path", "")).lower().endswith(".mod")
            target = os.path.join(mod_dir, os.path.splitext(k)[0]) if folder_style else os.path.join(mod_dir, k)
            if isinstance(sample, dict):
                e = dict(sample)
                e["path"] = target
                return e
            return target
        data = dict(existing)
        data["enabledMods"] = [entry(k) for k in mod_keys]
    _backup(path, backup_dir)
    tmp = path + ".pmc-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


# ================================================================== processes
def running(image):
    """Is a program with this .exe name running? (Windows; False elsewhere)"""
    if not IS_WIN:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"], capture_output=True,
                             text=True, creationflags=NO_WINDOW, timeout=15).stdout
    except Exception:
        return False
    return image.lower() in out.lower()


def launcher_running():
    return running("dowser.exe") or running("Paradox Launcher.exe")


def start_game(exe, args, extra=()):
    try:
        return subprocess.Popen([exe] + list(args) + list(extra), cwd=os.path.dirname(exe),
                                close_fds=True)
    except OSError as e:
        raise LauncherError(f"couldn't start {os.path.basename(exe)} ({e})")


def start_steam():
    try:
        if IS_WIN:
            os.startfile("steam://open/main")  # noqa
        else:
            subprocess.Popen(["xdg-open", "steam://open/main"])
    except Exception:
        pass


# ================================================================== the official launcher's playsets
def _open_ro(db):
    uri = "file:" + db.replace("\\", "/") + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def read_playsets(db):
    """[{"name", "active", "mods": [(.mod file name, enabled)]}] from launcher-v2.sqlite (read-only)."""
    if not os.path.isfile(db):
        return []
    out = []
    con = _open_ro(db)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(playsets)")}
        where = "WHERE isRemoved = 0" if "isRemoved" in cols else ""
        for pid, name, active in con.execute(f"SELECT id, name, isActive FROM playsets {where} ORDER BY name"):
            rows = con.execute("SELECT m.gameRegistryId, pm.enabled, pm.position FROM playsets_mods pm "
                               "JOIN mods m ON m.id = pm.modId WHERE pm.playsetId = ? "
                               "ORDER BY pm.position", (pid,)).fetchall()
            mods = []
            for reg, enabled, _ in rows:
                if reg:
                    mods.append((os.path.basename(str(reg).replace("\\", "/")), bool(enabled)))
            out.append({"name": name, "active": bool(active), "mods": mods})
    finally:
        con.close()
    return out


NEEDED = {"playsets": {"id", "name", "isActive", "loadOrder", "createdOn"},
          "playsets_mods": {"playsetId", "modId", "enabled", "position"},
          "mods": {"id", "gameRegistryId", "displayName", "status", "source"}}


def export_playset(db, name, entries, mods_by_key, backup_dir, make_active=False):
    """Write a playset into the official launcher (only while it's closed, after a backup).
    entries: [(.mod file name, enabled)]; mods_by_key: {.mod file name: modscan.ModInfo}.
    Replaces a playset with the same name. Returns (playset name, number of mods)."""
    if not os.path.isfile(db):
        raise LauncherError("the official launcher hasn't created its database yet (start it once)")
    if launcher_running():
        raise LauncherError("close the Paradox launcher first; it overwrites its database while open")
    _backup(db, backup_dir, keep=10)
    con = sqlite3.connect(db, timeout=10)
    try:
        for table, cols in NEEDED.items():
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            if not cols <= have:
                raise LauncherError("this launcher version stores playsets differently; export is not "
                                    "safe, so nothing was changed")
        now_ms = int(time.time() * 1000)
        pcols = {r[1] for r in con.execute("PRAGMA table_info(playsets)")}
        row = con.execute("SELECT id FROM playsets WHERE name = ?" +
                          (" AND isRemoved = 0" if "isRemoved" in pcols else ""), (name,)).fetchone()
        if row:
            pid = row[0]
            con.execute("DELETE FROM playsets_mods WHERE playsetId = ?", (pid,))
            con.execute("UPDATE playsets SET updatedOn = ? WHERE id = ?", (now_ms, pid))
        else:
            pid = str(uuid.uuid4())
            fields = {"id": pid, "name": name, "isActive": 0, "loadOrder": "custom", "createdOn": now_ms,
                      "updatedOn": now_ms}
            fields = {k: v for k, v in fields.items() if k in pcols}
            con.execute(f"INSERT INTO playsets ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                        list(fields.values()))
        mcols = {r[1] for r in con.execute("PRAGMA table_info(mods)")}
        n = 0
        for pos, (key, enabled) in enumerate(entries):
            reg = "mod/" + key
            r = con.execute("SELECT id FROM mods WHERE gameRegistryId = ?", (reg,)).fetchone()
            if r:
                mid = r[0]
            else:
                m = mods_by_key.get(key)
                mid = str(uuid.uuid4())
                fields = {"id": mid, "gameRegistryId": reg, "displayName": m.name if m else key,
                          "status": "ready_to_play", "source": "local",
                          "version": (m.version if m else "") or None,
                          "requiredVersion": (m.supported if m else "") or None,
                          "dirPath": (m.folder if m else "") or None,
                          "tags": json.dumps(m.tags if m else []),
                          "createdDate": int(time.time())}
                fields = {k: v for k, v in fields.items() if k in mcols}
                con.execute(f"INSERT INTO mods ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                            list(fields.values()))
            con.execute("INSERT INTO playsets_mods (playsetId, modId, enabled, position) VALUES (?, ?, ?, ?)",
                        (pid, mid, 1 if enabled else 0, pos))
            n += 1
        if make_active:
            con.execute("UPDATE playsets SET isActive = 0")
            con.execute("UPDATE playsets SET isActive = 1 WHERE id = ?", (pid,))
        con.commit()
    except LauncherError:
        con.rollback()
        raise
    except sqlite3.Error as e:
        con.rollback()
        raise LauncherError(f"couldn't write the launcher's database ({e}); nothing was changed")
    finally:
        con.close()
    return name, n
