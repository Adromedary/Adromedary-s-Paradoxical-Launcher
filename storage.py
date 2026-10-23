"""Cached files that only take up room: pictures, Workshop pages, SteamCMD leftovers.

Everything counted here comes back by itself when it's needed again (pictures and pages are downloaded
again when shown). Never counted: the saved mod check (analysis_cache.pkl), the game's definitions
(vanilla_names_*.json), unfinished downloads that can still be resumed (queue.json + staging), backups,
the error log, settings, playsets and the catch list.
"""
import os
import shutil

LIMITS_MB = [100, 250, 500, 1000, 2000, 5000, 10000]
DEFAULT_LIMIT_MB = 250


def label_mb(mb):
    return f"{mb // 1000} GB" if mb >= 1000 and mb % 1000 == 0 else (f"{mb / 1000:.1f} GB" if mb >= 1000
                                                                       else f"{mb} MB")


def human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _size(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def categories(work_dir, downloads_busy=False):
    """[(key, what it is, [paths], bytes)] of clutter in the work folder. Partial downloads are only
    counted when nothing is downloading or waiting to resume (then they're leftovers)."""
    cats = [
        ("pictures", "Mod pictures and Workshop thumbnails", [os.path.join(work_dir, "thumbs")]),
        ("shots", "Full-size screenshots", [os.path.join(work_dir, "shots")]),
        ("pages", "Saved Workshop pages", [os.path.join(work_dir, "workshop_pages.json")]),
    ]
    if not downloads_busy and not os.path.isfile(os.path.join(work_dir, "queue.json")):
        cats.append(("leftovers", "Leftovers of finished downloads",
                     [os.path.join(work_dir, "steamcmd_downloads", "steamapps", "workshop"),
                      os.path.join(work_dir, "staging")]))
    out = []
    for key, what, paths in cats:
        paths = [p for p in paths if os.path.exists(p)]
        n = sum(_size(p) for p in paths)
        if n:
            out.append((key, what, paths, n))
    return out


def total(cats):
    return sum(c[3] for c in cats)


def clear(cats):
    """Delete them. Returns the bytes freed (files in use are skipped)."""
    freed = 0
    for _, _, paths, n in cats:
        for p in paths:
            before = _size(p)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
            freed += before - (_size(p) if os.path.exists(p) else 0)
    return freed
