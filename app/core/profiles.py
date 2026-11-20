"""
Playsets of this app ("profiles"): named, ordered mod lists per mod folder, kept in profiles.json.

    {"<mod folder (normcase)>": {"active": "Default",
                                "profiles": {"Default": {"mods": [["2871648329.mod", true], ...],
                                                         "rules": [["a.mod", "b.mod"], ...],
                                                         "changed": 1792000000}}}}

mods: the order the game loads them (top first; the lower one wins a shared file), each with an
enabled flag. rules: your own "a loads before b" rules, which Auto-sort always keeps.
"""
import json
import os
import threading
import time

_lock = threading.Lock()


class Profiles:
    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def save(self):
        with _lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)

    # ---------------------------------------------------------------- per mod folder
    def _slot(self, mod_dir):
        return self.data.setdefault(os.path.normcase(os.path.normpath(mod_dir)), {"active": "", "profiles": {}})

    def names(self, mod_dir):
        return sorted(self._slot(mod_dir)["profiles"], key=str.lower)

    def active(self, mod_dir):
        s = self._slot(mod_dir)
        if s["active"] not in s["profiles"]:
            s["active"] = next(iter(sorted(s["profiles"], key=str.lower)), "")
        return s["active"]

    def set_active(self, mod_dir, name):
        s = self._slot(mod_dir)
        if name in s["profiles"]:
            s["active"] = name
            self.save()

    def get(self, mod_dir, name):
        return self._slot(mod_dir)["profiles"].get(name)

    def put(self, mod_dir, name, mods, rules=None, activate=True):
        s = self._slot(mod_dir)
        old = s["profiles"].get(name, {})
        s["profiles"][name] = {"mods": [[k, bool(on)] for k, on in mods],
                               "rules": [list(r) for r in (rules if rules is not None else old.get("rules", []))],
                               "changed": int(time.time())}
        if activate or not s["active"]:
            s["active"] = name
        self.save()
        return s["profiles"][name]

    def rename(self, mod_dir, old, new):
        s = self._slot(mod_dir)
        if old not in s["profiles"] or not new or new in s["profiles"]:
            return False
        s["profiles"][new] = s["profiles"].pop(old)
        if s["active"] == old:
            s["active"] = new
        self.save()
        return True

    def delete(self, mod_dir, name):
        s = self._slot(mod_dir)
        s["profiles"].pop(name, None)
        if s["active"] == name:
            s["active"] = next(iter(sorted(s["profiles"], key=str.lower)), "")
        self.save()

    def rename_key(self, mod_dir, old, new):
        """A mod's .mod file changed name (an update installed it as <id>.mod): follow it everywhere."""
        changed = False
        for p in self._slot(mod_dir)["profiles"].values():
            keys = [k for k, _ in p["mods"]]
            if old in keys:
                if new in keys:
                    p["mods"] = [m for m in p["mods"] if m[0] != old]
                else:
                    p["mods"] = [[new if k == old else k, on] for k, on in p["mods"]]
                p["rules"] = [[new if x == old else x for x in r] for r in p.get("rules", [])]
                changed = True
        if changed:
            self.save()
        return changed

    def forget_keys(self, mod_dir, keys):
        keys = set(keys)
        for p in self._slot(mod_dir)["profiles"].values():
            p["mods"] = [m for m in p["mods"] if m[0] not in keys]
            p["rules"] = [r for r in p.get("rules", []) if r[0] not in keys and r[1] not in keys]
        self.save()

    def unique_name(self, mod_dir, base):
        names = set(self._slot(mod_dir)["profiles"])
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"


def reconcile(entries, installed_keys):
    """Split a profile's entries against what's in the mod folder:
    (entries still present, missing keys, installed keys that aren't in the profile)."""
    present = [(k, on) for k, on in entries if k in installed_keys]
    missing = [k for k, _ in entries if k not in installed_keys]
    listed = {k for k, _ in entries}
    extra = sorted(k for k in installed_keys if k not in listed)
    return present, missing, extra
