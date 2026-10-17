"""
Update detection: asks Steam's public Workshop API when each installed mod last changed and
compares that with the version you have.

What "the version you have" means:
  * mods this app installed: the Steam update time recorded at install (installed.json);
  * anything else: when its files landed on this PC (the newest file time in its folder).
Results are cached in updates.json so the Update buttons survive a restart.
"""
import json
import os
import re
import threading
import time

import sources as S

_lock = threading.Lock()
SLACK = 120          # seconds of clock noise to ignore


def workshop_id(mod, registry):
    """The Steam Workshop ID behind an installed mod, or ''."""
    stem = os.path.splitext(mod.key)[0]
    if stem in registry:
        return stem
    if (mod.remote_id or "").isdigit():
        return mod.remote_id
    m = re.fullmatch(r"(?:ugc_)?(\d{6,})", stem)
    return m.group(1) if m else ""


def check(net, mods, registry):
    """{mod key: info} for every mod with a Workshop ID. info = id, title, steam_updated, local_updated, update."""
    ids = {}
    for m in mods:
        if m.missing:
            continue
        wid = workshop_id(m, registry)
        if wid:
            ids.setdefault(wid, []).append(m)
    details = S.steam_details(net, list(ids)) if ids else {}
    out = {}
    for wid, owners in ids.items():
        d = details.get(wid)
        for m in owners:
            if not d:
                out[m.key] = {"id": wid, "title": m.name, "steam_updated": 0, "local_updated": 0,
                              "update": False, "gone": True}
                continue
            rec = registry.get(wid, {})
            local = int(rec.get("steam_updated") or 0) if os.path.splitext(m.key)[0] == wid else 0
            if not local:
                local = int(getattr(m, "installed_at", 0) or m.mtime or 0)
            steam = int(d.get("time_updated") or 0)
            out[m.key] = {"id": wid, "title": d.get("title") or m.name, "steam_updated": steam,
                          "local_updated": local, "update": bool(steam and local and steam > local + SLACK),
                          "gone": False}
    return out


# ------------------------------------------------------------------ cache (updates.json)
def load_cache(path, mod_dir):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(os.path.normcase(mod_dir), {})
    except Exception:
        return {}


def save_cache(path, mod_dir, results):
    with _lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data[os.path.normcase(mod_dir)] = {"checked_at": int(time.time()), "mods": results}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)


def clear_ids(path, mod_dir, ids):
    """After updating, forget the 'update available' flag for these Workshop IDs."""
    with _lock:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        entry = data.get(os.path.normcase(mod_dir), {})
        for key, info in list(entry.get("mods", {}).items()):
            if info.get("id") in ids:
                info["update"] = False
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)


def when(ts):
    return time.strftime("%d %b %Y", time.localtime(ts)) if ts else "unknown"
