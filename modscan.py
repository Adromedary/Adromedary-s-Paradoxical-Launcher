"""
Reads a Paradox mod folder and finds file conflicts: two mods that ship a file with the same
relative path (e.g. common/traits/00_traits.txt). The game loads only one of them, so one mod's
version silently replaces the other's.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

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
        self.sizes = {}              # relative path -> bytes (files that count for conflicts)
        self.sig = ""                # changes whenever its files change (for the saved checks)

    @property
    def key(self):
        return os.path.basename(self.modfile)


def _resolve(mod_dir, value):
    """path=/archive= values are absolute or relative to the game's user folder (parent of mod/)."""
    v = value.replace("\\", "/").strip()
    if not v:
        return ""
    if len(v) > 1 and v[1] == ":" and os.sep == "/":
        # a Windows path on Linux (a Proton prefix, or a mod folder copied from Windows): the part from the
        # game's folder on, under this mod folder's game folder
        m = re.search(r"(?i)/mod/(.+)$", v)
        if m:
            return os.path.normpath(os.path.join(os.path.normpath(mod_dir), m.group(1)))
        return os.path.normpath(v)
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


def _walk(folder, stop=None):
    """Every file under folder as (relative path, full path, size, mtime, ctime), hidden folders skipped.
    os.scandir hands out each file's size and dates with the folder listing on Windows, so this costs one
    call per folder instead of one per file (the old os.walk + os.stat did both)."""
    out = []
    stack = [("", folder)]
    while stack:
        if stop is not None and stop.is_set():
            return out
        prefix, d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir():
                        if not e.name.startswith(".") and not e.is_symlink():
                            stack.append((prefix + e.name + "/", e.path))
                        continue
                    st = e.stat()
                except OSError:
                    continue
                out.append((prefix + e.name, e.path, st.st_size, st.st_mtime, st.st_ctime))
    return out


def _fill(m, stop=None):
    """A mod's files, sizes and dates from its folder."""
    files = _walk(m.folder, stop)
    newest = landed_max = 0.0
    total = 0
    win = os.name == "nt"
    for rel, full, size, mtime, ctime in files:
        total += size
        if mtime > newest:
            newest = mtime
        # Windows: st_ctime is when the file was created here, i.e. when it arrived
        landed = max(mtime, ctime) if win else mtime
        if landed > landed_max:
            landed_max = landed
        rl = rel.lower()
        if _counts(rl):
            m.files.add(rl)
            m.paths[rl] = full
            m.sizes[rl] = size
    m.size, m.mtime, m.installed_at = total, newest, landed_max
    names = "\n".join(sorted(m.files))
    m.sig = f"{len(files)}:{total}:{int(newest)}:{zlib.crc32(names.encode('utf-8', 'replace')):08x}"


def scan(mod_dir, stop=None, ignored=(), workers=8):
    """Returns (mods sorted by name, number of mods with conflicts). The mods' folders are listed side by
    side (several at once: the disk waits, not the processor)."""
    mods = []
    try:
        entries = sorted(os.listdir(mod_dir))
    except OSError:
        return [], 0
    walk = []
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
            walk.append(m)
        elif archive and os.path.isfile(archive):
            try:
                m.size, m.mtime = os.path.getsize(archive), os.path.getmtime(archive)
                m.installed_at = max(m.mtime, os.path.getctime(archive) if os.name == "nt" else m.mtime)
                with zipfile.ZipFile(archive) as z:
                    for zi in z.infolist():
                        n = zi.filename.lower()
                        if not n.endswith("/") and _counts(n):
                            m.files.add(n)
                            m.sizes[n] = zi.file_size
                m.sig = f"zip:{m.size}:{int(m.mtime)}"
            except Exception:
                m.missing = True
        else:
            m.missing = True
        mods.append(m)
    if walk:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(walk)))) as ex:
            list(ex.map(lambda m: _fill(m, stop), walk))
    if stop is not None and stop.is_set():
        return [], 0
    compute_conflicts(mods, ignored)
    mods.sort(key=lambda m: m.name.lower())
    return mods, sum(1 for m in mods if m.conflicts)


_hash_cache, _hash_lock = {}, threading.Lock()
_hash_dirty = [False]


def file_hash(path):
    """SHA-1 of a file, cached by (path, size, mtime) (kept between starts: load_hashes / save_hashes).
    '' if unreadable."""
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
        _hash_dirty[0] = True
    return _hash_cache[key]


def same_file(p, q, size_p=None, size_q=None):
    """Are two files byte for byte the same? Different sizes answer at once; only same-size files are read
    (and their fingerprints remembered)."""
    if not p or not q:
        return False
    try:
        sp = os.path.getsize(p) if size_p is None else size_p
        sq = os.path.getsize(q) if size_q is None else size_q
    except OSError:
        return False
    if sp != sq:
        return False
    a = file_hash(p)
    return bool(a) and a == file_hash(q)


def load_hashes(path):
    """The file fingerprints of earlier runs (only files that still look the same are kept)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    with _hash_lock:
        for p, (size, mtime, h) in data.items():
            _hash_cache[(p, size, mtime)] = h


def save_hashes(path, limit=200000):
    with _hash_lock:
        if not _hash_dirty[0]:
            return
        items = list(_hash_cache.items())[-limit:]
        _hash_dirty[0] = False
    data = {}
    for (p, size, mtime), h in items:
        data[p] = (size, mtime, h)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


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
        # byte-identical copies are found by size first: only copies of the same size get read
        by_size = {}
        for a in who:
            by_size.setdefault(a.sizes.get(rel, -1), []).append(a)
        digest = {}
        for size, group in by_size.items():
            for a in group:
                p = a.paths.get(rel)
                digest[a] = file_hash(p) if p and len(group) > 1 and size >= 0 else ("" if not p else f"#{id(a)}")
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
