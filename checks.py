"""
Playset checks: which mods a check covers, its fingerprint, and the saved results of earlier checks.

A check reads the mods of the active playset (what each defines and uses comes from analysis.FactStore,
so only new or changed mods are read again) and works out every conflict between them. Its result is
saved here, keyed by the playset's fingerprint: the mods it contains and the exact version of each
(their files), the game version and the settings the check depends on. Coming back to a combination
that was checked before (turning a test mod off again, switching playsets) loads the saved result in
moments instead of checking again.

The load order isn't part of the fingerprint: everything that depends on it (which mod wins each file,
Auto-sort, the playset's problems) is worked out from the check instantly, so re-sorting never needs a
new check.

Saved results are small: the mods' facts live once in the FactStore, a saved check keeps only what the
combination produced (conflicts, how mods relate, roles), with references to the facts.
"""
import hashlib
import io
import json
import os
import pickle
import re
import threading
import time

import analysis as A

HISTORY_VERSION = 1
DEFAULT_KEEP = 100
_PATCHY = re.compile(r"\b(com-?patch|compat(ibility)?|patch|bridge|integration|merge[dr]?|addon|add-on|submod)\b",
                     re.I)
_BASE_FIELDS = {"mod", "key", "name", "wid", "files", "total", "light_override_share"}


# ================================================================== which mods a check covers
def check_set(all_mods, enabled_keys):
    """The mods a playset's check reads: the enabled ones, plus installed mods that are off but matter to
    them (so the check can say "turn it on"): mods an enabled mod declares it needs, and compatches or
    add-ons made for enabled mods (they declare those as dependencies, or name one of them)."""
    by = {m.key: m for m in all_mods if not m.missing}
    on = [k for k in enabled_keys if k in by]
    on_set = set(on)
    out = [by[k] for k in on]
    names = {}
    for k in on:
        names[A.clean_title(by[k].name).lower()] = k
    want = set()
    # what enabled mods declare they need
    for k in on:
        for dep in by[k].dependencies:
            d = A.clean_title(dep).lower()
            for m in by.values():
                if m.key not in on_set and (A.clean_title(m.name).lower() == d or A.similarity(dep, m.name) >= 0.85):
                    want.add(m.key)
    # compatches / add-ons for enabled mods
    on_tokens = {k: set(A.tokens(by[k].name)) for k in on}
    for m in by.values():
        if m.key in on_set or m.key in want:
            continue
        deps = [A.clean_title(d).lower() for d in m.dependencies]
        if deps and all(d in names for d in deps):
            want.add(m.key)
            continue
        if _PATCHY.search(m.name):
            mt = set(A.tokens(m.name))
            hits = sum(1 for k, t in on_tokens.items() if t and len(t) <= len(mt) and t <= mt)
            if hits >= 1:
                want.add(m.key)
    out += [by[k] for k in sorted(want)]
    return out


def signature(mods, game_dir="", game_stamp="", hints=True):
    """The fingerprint of a check: the mods (each one's exact files and descriptor), the game and the
    settings that change what a check finds. The order of the mods doesn't count."""
    h = hashlib.sha1()
    h.update(f"h{HISTORY_VERSION}|f{A.FACTS_VERSION}|k{A.KNOWLEDGE_VERSION}|{os.path.normcase(game_dir or '')}|"
             f"{game_stamp}|{int(bool(hints))}".encode())
    for m in sorted(mods, key=lambda m: m.key):
        # what the descriptor says (not its file date: the official launcher rewrites descriptors)
        h.update(f"|{m.key}|{m.sig}|{m.name}|{m.version}|{m.supported}|{','.join(m.dependencies)}"
                 .encode("utf-8", "replace"))
    return h.hexdigest()


# ================================================================== saving a check without its facts
class _Pickler(pickle.Pickler):
    def persistent_id(self, obj):
        if isinstance(obj, A.ModFacts):
            return ("facts", obj.key)
        if obj.__class__.__name__ == "ModInfo":
            return ("mod", obj.key)
        return None


class _Unpickler(pickle.Unpickler):
    def __init__(self, f, facts, mods):
        super().__init__(f)
        self.facts, self.mods = facts, mods

    def persistent_load(self, pid):
        kind, key = pid
        return self.facts[key] if kind == "facts" else self.mods[key]


def dump_analysis(an):
    """Bytes of an analysis without the mods' facts (those are in the FactStore)."""
    combo = {}
    for k, f in an.facts.items():
        combo[k] = {n: v for n, v in f.__dict__.items() if n not in _BASE_FIELDS and n not in A.READ_FIELDS}
    state = {n: v for n, v in an.__dict__.items() if n != "facts"}
    buf = io.BytesIO()
    pickle.dump(list(an.facts), buf, protocol=pickle.HIGHEST_PROTOCOL)       # read first, on its own
    _Pickler(buf, protocol=pickle.HIGHEST_PROTOCOL).dump({"combo": combo, "state": state})
    return buf.getvalue()


def load_analysis(data, mods_by_key, store, van, wids=None):
    """An analysis back from dump_analysis: each mod's facts from the store (None when a mod isn't there
    any more, or its facts were forgotten: then the check has to run again)."""
    buf = io.BytesIO(data)
    keys = pickle.load(buf)
    facts = {}
    for k in keys:
        m = mods_by_key.get(k)
        if m is None:
            return None
        part = store.load(m, van) if store is not None else None
        if part is None:
            return None
        f = A.ModFacts(m, (wids or {}).get(k, ""))
        A._apply_part(f, part)
        facts[k] = f
    d = _Unpickler(buf, facts, mods_by_key).load()
    for k, vals in d["combo"].items():
        facts[k].__dict__.update(vals)
    an = A.Analysis()
    an.__dict__.update(d["state"])
    an.facts = {k: facts[k] for k in keys}
    return an


# ================================================================== the saved checks
class CheckHistory:
    """The latest checks (one file each) and an index: fingerprint -> when, which playset, how many mods."""

    def __init__(self, folder, keep=DEFAULT_KEEP):
        self.folder = folder
        self.keep = max(1, int(keep or DEFAULT_KEEP))
        self._lock = threading.Lock()
        self.index = []
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("v") == HISTORY_VERSION:
                self.index = [e for e in d.get("checks", []) if os.path.isfile(self._path(e["sig"]))]
        except (OSError, ValueError, KeyError, TypeError):
            self.index = []

    def _path(self, sig):
        return os.path.join(self.folder, f"{sig}.pkl")

    def _save_index(self):
        try:
            tmp = os.path.join(self.folder, "index.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"v": HISTORY_VERSION, "checks": self.index}, f, indent=1)
            os.replace(tmp, os.path.join(self.folder, "index.json"))
        except OSError:
            pass

    def entry(self, sig):
        return next((e for e in self.index if e["sig"] == sig), None)

    def has(self, sig):
        return self.entry(sig) is not None

    def load(self, sig, mods_by_key, store, van, wids=None):
        e = self.entry(sig)
        if e is None:
            return None
        try:
            with open(self._path(sig), "rb") as f:
                data = f.read()
            an = load_analysis(data, mods_by_key, store, van, wids)
        except Exception:
            an = None
        if an is None:
            self.forget(sig)
            return None
        with self._lock:                       # most recently used first
            self.index = [e] + [x for x in self.index if x["sig"] != sig]
            e["used"] = time.time()
            self._save_index()
        an.from_cache = True
        an.seconds = 0.0
        return an

    def save(self, sig, an, playset="", game="", seconds=0.0):
        try:
            data = dump_analysis(an)
            tmp = self._path(sig) + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, self._path(sig))
        except Exception:
            return False
        e = {"sig": sig, "playset": playset, "game": game, "mods": len(an.facts), "when": time.time(),
             "used": time.time(), "seconds": round(seconds, 1), "bytes": len(data)}
        with self._lock:
            self.index = [e] + [x for x in self.index if x["sig"] != sig]
            self._trim()
            self._save_index()
        return True

    def forget(self, sig):
        with self._lock:
            self.index = [x for x in self.index if x["sig"] != sig]
            try:
                os.remove(self._path(sig))
            except OSError:
                pass
            self._save_index()

    def clear(self):
        with self._lock:
            for e in self.index:
                try:
                    os.remove(self._path(e["sig"]))
                except OSError:
                    pass
            self.index = []
            self._save_index()

    def set_keep(self, keep):
        with self._lock:
            self.keep = max(1, int(keep))
            self._trim()
            self._save_index()

    def _trim(self):
        for e in self.index[self.keep:]:
            try:
                os.remove(self._path(e["sig"]))
            except OSError:
                pass
        self.index = self.index[:self.keep]

    def last_for(self, playset):
        return next((e for e in self.index if e.get("playset") == playset), None)

    def size(self):
        return sum(e.get("bytes", 0) for e in self.index)
