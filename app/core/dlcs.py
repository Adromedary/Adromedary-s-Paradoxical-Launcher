"""
DLC of a Paradox game: which are installed, and which the game should load.

The game folder (launcher-settings.json "dlcPath", "../game" for Crusader Kings III) has dlc/<folder>/
with a <code>.dlc descriptor each:

    name = "Silk and Silver"
    path = "dlc/dlc031_ep5"
    steam_id = "4232910"
    localizable_name = "DLC031_EP5"

and often a thumbnail.png. dlc_metadata/00_dlc_metadata.txt (CK3) adds how big each one is (major =
expansion, medium = core expansion, minor = packs) and a sorting priority.

Turning DLC off works the way the official launcher does it: Documents/Paradox Interactive/<game>/
dlc_load.json lists the descriptors the game must skip:

    {"enabled_mods": [...], "disabled_dlcs": ["dlc/dlc031_ep5/dlc031.dlc"]}

The app only says which DLC are installed: whether you own one is between you and the store.
"""
import json
import os
import re

from app.core.installer import read_text

_PAIR = re.compile(r'(?m)^\s*([A-Za-z_]+)\s*=\s*"?([^"\n]*?)"?\s*$')
_BLOCK = re.compile(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*\{(.*?)^\}", re.S)
# what the folder code says the DLC is (CK3 naming; other games just say "DLC")
_KIND = [("ep", "Expansion"), ("ce", "Core expansion"), ("fp", "Flavour pack"), ("bp", "Event pack"),
         ("mp", "Music pack"), ("ccp", "Cosmetic pack"), ("cp", "Cosmetic pack"), ("sp", "Cosmetic pack"),
         ("afr", "Cosmetic pack"), ("preorder", "Cosmetic pack")]
KIND_ORDER = ["Expansion", "Core expansion", "Flavour pack", "Event pack", "Cosmetic pack", "Music pack", "DLC"]


class Dlc:
    __slots__ = ("key", "name", "folder", "descriptor", "steam_id", "kind", "size", "priority", "thumb", "number")

    def __init__(self):
        self.key = ""            # "dlc/dlc031_ep5/dlc031.dlc": what dlc_load.json lists
        self.name = ""
        self.folder = ""         # full path of dlc/dlc031_ep5
        self.descriptor = ""
        self.steam_id = ""
        self.kind = "DLC"
        self.size = "minor"      # major | medium | minor
        self.priority = 0
        self.thumb = ""          # thumbnail.png when there is one
        self.number = 0          # 31 for dlc031

    def __repr__(self):
        return f"Dlc({self.key!r}, {self.name!r}, {self.kind})"


def dlc_root(install):
    """The folder that holds dlc/ for this install (launcher-settings.json says where), or ""."""
    if not install:
        return ""
    cands = []
    try:
        with open(os.path.join(install, "launcher", "launcher-settings.json"), encoding="utf-8-sig") as f:
            rel = json.load(f).get("dlcPath") or ""
        if rel:
            cands.append(os.path.normpath(os.path.join(install, "launcher", rel)))
    except Exception:
        pass
    cands += [os.path.join(install, "game"), install]
    for c in cands:
        if os.path.isdir(os.path.join(c, "dlc")):
            return c
    return ""


def _parse(text):
    return {k.lower(): v.strip() for k, v in _PAIR.findall(text.lstrip("﻿"))}


def _metadata(root):
    """{name or steam id: (size, priority)} from dlc_metadata (CK3)."""
    out = {}
    folder = os.path.join(root, "dlc_metadata")
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith(".txt"))
    except OSError:
        return out
    for fn in files:
        try:
            text = read_text(os.path.join(folder, fn))
        except OSError:
            continue
        for _key, body in _BLOCK.findall(text.lstrip("﻿")):
            d = _parse(body)
            size = d.get("type", "").lower()
            try:
                prio = int(d.get("priority", "0") or 0)
            except ValueError:
                prio = 0
            for ident in (d.get("key", ""), d.get("steam_id", "")):
                if ident:
                    out[ident] = (size if size in ("major", "medium", "minor") else "", prio)
    return out


def _kind(folder_name, size):
    code = folder_name.split("_", 1)[1] if "_" in folder_name else ""
    m = re.match(r"[a-z]+", code.lower())          # "sp_day1" -> "sp", "ep5" -> "ep", "preorder"
    letters = m.group(0) if m else ""
    label = next((lab for pre, lab in _KIND if letters == pre), "")
    if size == "major":
        return "Expansion"
    if size == "medium":
        return label if label in ("Core expansion",) else "Core expansion"
    return label or "DLC"


def installed(install):
    """Every DLC installed with this copy of the game, biggest first (as the game sorts them)."""
    root = dlc_root(install)
    if not root:
        return []
    meta = _metadata(root)
    base = os.path.join(root, "dlc")
    out = []
    for folder in sorted(os.listdir(base)):
        full = os.path.join(base, folder)
        if not os.path.isdir(full):
            continue
        try:
            descs = sorted(f for f in os.listdir(full) if f.lower().endswith(".dlc"))
        except OSError:
            continue
        if not descs:
            continue
        d = Dlc()
        d.descriptor = os.path.join(full, descs[0])
        try:
            info = _parse(read_text(d.descriptor))
        except OSError:
            info = {}
        d.folder = full
        rel = (info.get("path") or f"dlc/{folder}").replace("\\", "/").strip("/")
        d.key = f"{rel}/{descs[0]}"
        d.name = info.get("name") or info.get("localizable_name") or folder
        d.steam_id = info.get("steam_id", "")
        size, prio = meta.get(d.name) or meta.get(d.steam_id) or ("", 0)
        m = re.match(r"dlc(\d+)", folder.lower())
        d.number = int(m.group(1)) if m else 0
        d.size = size or ("major" if folder.lower().split("_", 1)[-1].startswith("ep") else
                          "medium" if folder.lower().split("_", 1)[-1].startswith("ce") else "minor")
        d.priority = prio
        d.kind = _kind(folder, d.size)
        thumb = os.path.join(full, "thumbnail.png")
        d.thumb = thumb if os.path.isfile(thumb) else ""
        out.append(d)
    rank = {"major": 0, "medium": 1, "minor": 2}
    # biggest first; newest first within a size (what players look for), then the game's own priority
    out.sort(key=lambda d: (rank.get(d.size, 3), -d.number, -d.priority, d.name.lower()))
    return out


def supported(game):
    """Can DLC be turned off for this game from here? (The games whose load file is dlc_load.json.)"""
    from app.core import launcher as LA
    return (LA.game_info(game).get("load") or "") == "dlc_load.json"


def read_disabled(game, data_dir):
    """The DLC the game will skip next time (dlc_load.json "disabled_dlcs"), as descriptor keys."""
    if not supported(game) or not data_dir:
        return []
    try:
        with open(os.path.join(data_dir, "dlc_load.json"), encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return []
    out = []
    for e in d.get("disabled_dlcs") or []:
        if isinstance(e, str) and e.strip():
            out.append(e.replace("\\", "/").strip())
    return out


def write_disabled(game, data_dir, keys, backup_dir=None):
    """Make the game skip exactly these DLC (descriptor keys); the mod list stays as it is."""
    from app.core import launcher as LA
    if not supported(game):
        raise LA.LauncherError(f"turning DLC off isn't supported for {game} here yet")
    path = os.path.join(data_dir, "dlc_load.json")
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
    if (data.get("disabled_dlcs") or []) == list(keys):
        return path
    data.setdefault("enabled_mods", [])
    data["disabled_dlcs"] = list(keys)
    if backup_dir:
        LA._backup(path, backup_dir)
    os.makedirs(data_dir, exist_ok=True)
    tmp = path + ".pmc-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def store_url(game, d):
    if d.steam_id:
        return f"https://store.steampowered.com/app/{d.steam_id}/"
    return ""
