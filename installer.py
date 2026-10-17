"""
Installing downloaded mods straight into a Paradox game's mod folder.

Every Workshop item ends up as
    <mod folder>/<workshop id>/            the mod's files (descriptor.mod at its root)
    <mod folder>/<workshop id>.mod         descriptor + path=..., which the launcher reads
whatever shape the download came in (SkyMods zip, Steam folder, ModDB rar, bare files).
"""
import json
import os
import re
import shutil
import sys
import threading

IS_WIN = sys.platform.startswith("win")
_reg_lock = threading.Lock()

# Folder names the Paradox launcher uses under Documents\Paradox Interactive
PARADOX_GAMES = ["Crusader Kings III", "Europa Universalis IV", "Hearts of Iron IV", "Stellaris",
                 "Victoria 3", "Imperator", "Crusader Kings II", "Europa Universalis V"]
# Top-level folders a Paradox mod ships; finding one means we are at the mod's root.
CONTENT_DIRS = {"common", "events", "gfx", "history", "localization", "localisation", "map_data", "map",
                "music", "sound", "interface", "gui", "fonts", "content_source", "dlc_metadata", "decisions",
                "missions", "flags", "portraits", "tweakergui_assets", "data", "notifications", "coat_of_arms"}
DOC_FILES = re.compile(r"^(readme|changelog|license|credits)[^/]*$|\.(md|url|pdf)$", re.I)


# ------------------------------------------------------------------ finding mod folders
def documents_dir():
    """The real Documents folder (handles OneDrive / moved Documents on Windows)."""
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                       (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if path and os.path.isdir(path):
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def detect_mod_dirs():
    """[(game folder name, mod folder path)] for Paradox games found in Documents."""
    root = os.path.join(documents_dir(), "Paradox Interactive")
    found = []
    try:
        for name in sorted(os.listdir(root)):
            game_dir = os.path.join(root, name)
            if os.path.isdir(game_dir) and (os.path.isdir(os.path.join(game_dir, "mod"))
                                            or name in PARADOX_GAMES):
                found.append((name, os.path.join(game_dir, "mod")))
    except OSError:
        pass
    found.sort(key=lambda g: (g[0] != "Crusader Kings III", g[0]))
    return found


def game_of_mod_dir(mod_dir):
    """'Crusader Kings III' for ...\\Paradox Interactive\\Crusader Kings III\\mod, else ''."""
    parent = os.path.basename(os.path.dirname(os.path.normpath(mod_dir)))
    return parent if os.path.basename(os.path.normpath(mod_dir)).lower() == "mod" else ""


# ------------------------------------------------------------------ descriptor handling
_TOP_KEY = re.compile(r'^\s*([A-Za-z_]+)\s*=')


def strip_keys(text, keys):
    """Remove top-level `key=...` entries (single line or {...} blocks) for the given keys."""
    out, depth, skipping = [], 0, False
    for line in text.splitlines():
        if depth == 0:
            m = _TOP_KEY.match(line)
            skipping = bool(m and m.group(1).lower() in keys)
        opens, closes = line.count("{"), line.count("}")
        if not skipping:
            out.append(line)
        depth = max(0, depth + opens - closes)
        if depth == 0:
            skipping = False
    return "\n".join(out).strip("\n")


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def descriptor_value(text, key):
    """Value of key="..." in a descriptor; tolerates several keys on one line ('path="x"name="y"')."""
    m = re.search(r'(?:^|[\s{}"])' + key + r'\s*=\s*"([^"]*)"', text, re.M | re.I)
    return m.group(1) if m else ""


def descriptor_values(text, key):
    """Every value of a key that may repeat (replace_path="a" replace_path="b")."""
    return re.findall(r'(?:^|[\s{}"])' + key + r'\s*=\s*"([^"]*)"', text, re.M | re.I)


def descriptor_list(text, key):
    """Quoted strings in a key={ "a" "b" } block (tags, dependencies)."""
    m = re.search(r'(?:^|[\s}"])' + key + r'\s*=\s*\{([^}]*)\}', text, re.M | re.I)
    return re.findall(r'"([^"]*)"', m.group(1)) if m else []


def _quote(s):
    return s.replace("\\", "/").replace('"', "'")


# ------------------------------------------------------------------ locating the mod inside a download
def find_mod_roots(staging):
    """Folders inside `staging` that are a mod root (contain descriptor.mod), shallowest first.
    Falls back to a .mod file's path= target, then to the folder holding the game content."""
    roots = []
    for root, dirs, files in os.walk(staging):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if any(f.lower() == "descriptor.mod" for f in files):
            if not any(os.path.commonpath([root, r]) == r for r in roots):
                roots.append(root)
    if roots:
        return sorted(roots, key=lambda r: r.count(os.sep))
    # no descriptor: maybe an outer .mod points at a folder
    for f in os.listdir(staging):
        if f.lower().endswith(".mod") and os.path.isfile(os.path.join(staging, f)):
            target = descriptor_value(read_text(os.path.join(staging, f)), "path")
            cand = os.path.join(staging, os.path.basename(target.rstrip("/\\"))) if target else ""
            if cand and os.path.isdir(cand):
                return [cand]
    # bare content: descend through single-folder wrappers until real content appears
    cur = staging
    while True:
        entries = [e for e in os.listdir(cur) if not e.startswith(".")]
        subdirs = [e for e in entries if os.path.isdir(os.path.join(cur, e))]
        files = [e for e in entries if os.path.isfile(os.path.join(cur, e))
                 and not e.lower().endswith(".mod") and e.lower() != "source.txt"]
        if len(subdirs) == 1 and not files and subdirs[0].lower() not in CONTENT_DIRS:
            cur = os.path.join(cur, subdirs[0])
        else:
            return [cur] if entries else []


def _outer_mod_text(staging, root):
    """Text of a top-level .mod file in the download that belongs to `root`, if any."""
    base = os.path.basename(root).lower()
    for f in os.listdir(staging):
        p = os.path.join(staging, f)
        if f.lower().endswith(".mod") and os.path.isfile(p):
            t = read_text(p)
            tgt = os.path.basename(descriptor_value(t, "path").replace("\\", "/").rstrip("/")).lower()
            if tgt == base or os.path.splitext(f)[0].lower() == base:
                return t
    return ""


# ------------------------------------------------------------------ install
def install(item, staging, mod_dir, source_name, registry_path):
    """Move the mod found in `staging` into `mod_dir`. Returns a short description."""
    roots = find_mod_roots(staging)
    if not roots:
        raise RuntimeError("the download was empty")
    os.makedirs(mod_dir, exist_ok=True)
    relative = os.path.basename(os.path.normpath(mod_dir)).lower() == "mod"
    installed = []
    for n, root in enumerate(roots):
        folder = item.id if n == 0 else f"{item.id}_{n + 1}"
        target = os.path.join(mod_dir, folder)
        modfile = os.path.join(mod_dir, folder + ".mod")
        desc_path = os.path.join(root, "descriptor.mod")
        if os.path.isfile(desc_path):
            text = read_text(desc_path)
        else:
            text = _outer_mod_text(staging, root)
        body = strip_keys(text, {"path", "archive"}) if text else ""
        if not descriptor_value(body, "name"):
            body = (body + "\n" if body else "") + f'name="{_quote(item.title)}"'
        if item.id.isdigit() and not descriptor_value(body, "remote_file_id"):
            body += f'\nremote_file_id="{item.id}"'
        if not os.path.isfile(desc_path):           # the launcher also wants one inside the folder
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(body + "\n")
        # replace any previous install of this folder
        if os.path.isdir(target):
            shutil.rmtree(target)
        if root == staging:
            os.makedirs(target)
            for e in os.listdir(staging):
                shutil.move(os.path.join(staging, e), os.path.join(target, e))
        else:
            shutil.move(root, target)
        for junk in ("SOURCE.txt",):
            if os.path.isfile(os.path.join(target, junk)):
                os.remove(os.path.join(target, junk))
        path_line = f"mod/{folder}" if relative else _quote(os.path.abspath(target))
        with open(modfile, "w", encoding="utf-8") as f:
            f.write(body.rstrip() + f'\npath="{path_line}"\n')
        installed.append(folder)
    record(registry_path, item, installed, source_name)
    return f"installed as {', '.join(installed)}"


def record(registry_path, item, folders, source_name):
    with _reg_lock:
        reg = load_registry(registry_path)
        reg[item.id] = {"title": item.title, "game": item.game, "folders": folders, "source": source_name,
                        "steam_updated": item.updated}
        tmp = registry_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=1)
        os.replace(tmp, registry_path)


def load_registry(registry_path):
    try:
        with open(registry_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_installed(item, mod_dir):
    return os.path.isfile(os.path.join(mod_dir, item.id + ".mod")) and \
        os.path.isdir(os.path.join(mod_dir, item.id))


def forget(registry_path, item_id):
    """Drop a deleted mod from installed.json."""
    with _reg_lock:
        reg = load_registry(registry_path)
        if reg.pop(item_id, None) is not None:
            tmp = registry_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=1)
            os.replace(tmp, registry_path)
