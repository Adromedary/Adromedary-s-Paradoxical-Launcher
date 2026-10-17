"""
Reads a Paradox mod folder and finds file conflicts: two mods that ship a file with the same
relative path (e.g. common/traits/00_traits.txt). The game loads only one of them, so one mod's
version silently replaces the other's.
"""
import hashlib
import os
import re
import shutil
import threading
import zipfile

from installer import DOC_FILES, descriptor_list, descriptor_value, descriptor_values, read_text


class ModInfo:
    def __init__(self, modfile, name, folder, version="", supported="", remote_id=""):
        self.modfile, self.name, self.folder = modfile, name, folder
        self.version, self.supported, self.remote_id = version, supported, remote_id
        self.files = set()
        self.paths = {}              # lower-case relative path -> real file path (folders only)
        self.tags, self.dependencies, self.replace_paths = [], [], []
        self.picture = ""
        self.same_files = set()      # files shared with another mod as byte-identical copies (no conflict)
        self.size = 0                # bytes on disk (all files, docs included)
        self.mtime = 0.0             # newest file change, for "recently changed" sorting
        self.installed_at = 0.0      # newest time a file landed here (mtime or, on Windows, creation)
        self.ignored = False         # the user said: don't flag this mod's conflicts
        self.missing = False
        self.duplicate_of = None     # another .mod entry pointing at the same folder
        self.conflicts = {}          # other ModInfo -> sorted list of shared paths

    @property
    def key(self):
        return os.path.basename(self.modfile)


def _resolve(mod_dir, value):
    """path=/archive= values are absolute or relative to the game's user folder (parent of mod/)."""
    v = value.replace("\\", "/").strip()
    if not v:
        return ""
    if os.path.isabs(v) or (len(v) > 1 and v[1] == ":"):
        return os.path.normpath(v)
    return os.path.normpath(os.path.join(os.path.dirname(os.path.normpath(mod_dir)), v))


def _counts(rel):
    """Files that matter for conflicts: inside a subfolder, not docs, not hidden."""
    if "/" not in rel:
        return False                 # descriptor.mod, thumbnail.png, readme at the root
    if any(part.startswith(".") for part in rel.split("/")):
        return False
    return not DOC_FILES.search(rel.rsplit("/", 1)[-1])


def scan(mod_dir, stop=None, ignored=()):
    """Returns (mods sorted by name, number of mods with conflicts)."""
    mods = []
    try:
        entries = sorted(os.listdir(mod_dir))
    except OSError:
        return [], 0
    for f in entries:
        p = os.path.join(mod_dir, f)
        if not (f.lower().endswith(".mod") and os.path.isfile(p)):
            continue
        try:
            text = read_text(p)
        except OSError:
            continue
        name = descriptor_value(text, "name") or os.path.splitext(f)[0]
        folder = _resolve(mod_dir, descriptor_value(text, "path"))
        archive = _resolve(mod_dir, descriptor_value(text, "archive"))
        m = ModInfo(p, name, folder or archive, descriptor_value(text, "version"),
                    descriptor_value(text, "supported_version"), descriptor_value(text, "remote_file_id"))
        m.picture = descriptor_value(text, "picture")
        inner = os.path.join(folder, "descriptor.mod") if folder else ""
        if inner and os.path.isfile(inner):
            try:
                text = text + "\n" + read_text(inner)          # tags/dependencies may live only there
            except OSError:
                pass
        m.tags = list(dict.fromkeys(descriptor_list(text, "tags")))
        m.dependencies = list(dict.fromkeys(descriptor_list(text, "dependencies")))
        m.replace_paths = sorted({v.replace("\\", "/").strip("/").lower()
                                  for v in descriptor_values(text, "replace_path") if v.strip("/")})
        if folder and os.path.isdir(folder):
            for root, dirs, files in os.walk(folder):
                if stop and stop.is_set():
                    return [], 0
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    full = os.path.join(root, fn)
                    try:
                        st = os.stat(full)
                        m.size += st.st_size
                        m.mtime = max(m.mtime, st.st_mtime)
                        # Windows: st_ctime is when the file was created here, i.e. when it arrived
                        landed = st.st_ctime if os.name == "nt" else st.st_mtime
                        m.installed_at = max(m.installed_at, st.st_mtime, landed)
                    except OSError:
                        pass
                    rel = os.path.relpath(full, folder).replace("\\", "/").lower()
                    if _counts(rel):
                        m.files.add(rel)
                        m.paths[rel] = full
        elif archive and os.path.isfile(archive):
            try:
                m.size, m.mtime = os.path.getsize(archive), os.path.getmtime(archive)
                m.installed_at = max(m.mtime, os.path.getctime(archive) if os.name == "nt" else m.mtime)
                with zipfile.ZipFile(archive) as z:
                    m.files = {n.lower() for n in z.namelist() if not n.endswith("/") and _counts(n.lower())}
            except Exception:
                m.missing = True
        else:
            m.missing = True
        mods.append(m)

    compute_conflicts(mods, ignored)
    mods.sort(key=lambda m: m.name.lower())
    return mods, sum(1 for m in mods if m.conflicts)


_hash_cache, _hash_lock = {}, threading.Lock()


def file_hash(path):
    """SHA-1 of a file, cached by (path, size, mtime). '' if unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (path, st.st_size, st.st_mtime)
    with _hash_lock:
        if key in _hash_cache:
            return _hash_cache[key]
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    with _hash_lock:
        _hash_cache[key] = h.hexdigest()
    return _hash_cache[key]


def compute_conflicts(mods, ignored=()):
    """(Re)compute conflicts. Mods whose .mod file name is in `ignored` take no part at all, so they
    are not flagged and don't flag others. Two mods shipping a byte-identical copy of a file are not
    a conflict (whichever loads, the game gets the same file). Returns the number of mods with conflicts."""
    ignored = set(ignored)
    for m in mods:
        m.conflicts, m.duplicate_of, m.same_files = {}, None, set()
        m.ignored = m.key in ignored
    by_folder = {}
    for m in mods:
        if m.folder and not m.missing:
            key = os.path.normcase(os.path.normpath(m.folder))
            if key in by_folder:
                m.duplicate_of = by_folder[key]
            else:
                by_folder[key] = m
    owners = {}
    for m in mods:
        if m.duplicate_of or m.ignored:
            continue                 # same files as the entry it duplicates; not a conflict
        for rel in m.files:
            owners.setdefault(rel, []).append(m)
    for rel, who in owners.items():
        if len(who) < 2:
            continue
        digest = {}
        for a in who:
            p = a.paths.get(rel)
            digest[a] = file_hash(p) if p else ""
        for a in who:
            for b in who:
                if a is b:
                    continue
                if digest[a] and digest[a] == digest[b]:
                    a.same_files.add(rel)
                else:
                    a.conflicts.setdefault(b, []).append(rel)
    for m in mods:
        for other in m.conflicts:
            m.conflicts[other].sort()
    return sum(1 for m in mods if m.conflicts)


# ------------------------------------------------------------------ sorting
SORTS = ["Name", "Game version", "Size", "File count", "Recently changed", "Mod version"]


def _version_key(v):
    """'1.18.*' -> (1, 18, 999); unparseable -> None (always sorted last)."""
    nums = re.findall(r"\d+|\*", v or "")
    if not nums:
        return None
    return tuple(999 if n == "*" else int(n) for n in nums[:4])


def sort_mods(mods, by="Name", descending=False):
    """Mods with conflicts (or a missing folder) always come first; each group is sorted by `by`."""
    def key(m):
        if by == "Game version":
            return _version_key(m.supported)
        if by == "Mod version":
            return _version_key(m.version)
        if by == "Size":
            return m.size
        if by == "File count":
            return len(m.files)
        if by == "Recently changed":
            return m.mtime
        return m.name.lower()

    def ordered(group):
        known = [m for m in group if key(m) is not None]
        unknown = [m for m in group if key(m) is None]          # no version info: last either way
        known.sort(key=lambda m: m.name.lower())
        known.sort(key=key, reverse=descending)
        return known + sorted(unknown, key=lambda m: m.name.lower())

    flagged = [m for m in mods if (m.conflicts or m.missing) and not m.ignored]
    rest = [m for m in mods if not ((m.conflicts or m.missing) and not m.ignored)]
    return ordered(flagged) + ordered(rest)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# ------------------------------------------------------------------ deleting
def _inside(path, folder):
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(folder))]) == os.path.normcase(os.path.abspath(folder))
    except ValueError:                       # different drives on Windows
        return False


def delete_plan(mod, mod_dir, all_mods):
    """What deleting `mod` would remove: (paths to delete, notes for the user)."""
    paths, notes = [mod.modfile], []
    target = mod.folder
    if target and os.path.exists(target):
        shared = [o for o in all_mods if o is not mod and o.folder and
                  os.path.normcase(os.path.normpath(o.folder)) == os.path.normcase(os.path.normpath(target))]
        if shared:
            notes.append(f"Its files are kept because \"{shared[0].name}\" uses the same folder.")
        elif not _inside(target, mod_dir) or os.path.normcase(os.path.abspath(target)) == \
                os.path.normcase(os.path.abspath(mod_dir)):
            notes.append("Its files live outside your mod folder (e.g. Steam's Workshop folder), "
                         "so only the .mod entry is removed.")
        else:
            paths.append(target)
    return paths, notes


def delete_mod(mod, mod_dir, all_mods):
    paths, notes = delete_plan(mod, mod_dir, all_mods)
    for p in paths:
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    return paths, notes
