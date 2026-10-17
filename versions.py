"""
Game versions and the "made for another game version" check.

The lists are the released versions as of October 2026 (newest first). The version box in the app
also accepts anything typed in, for betas and future patches.
"""
import re

GAME_VERSIONS = {
    "Crusader Kings III": ["1.20", "1.19", "1.18", "1.17", "1.16", "1.15", "1.14", "1.13", "1.12"],
    "Europa Universalis V": ["1.3", "1.2", "1.1", "1.0"],
    "Europa Universalis IV": ["1.37", "1.36", "1.35", "1.34", "1.33"],
    "Hearts of Iron IV": ["1.19", "1.18", "1.17", "1.16", "1.15", "1.14"],
    "Stellaris": ["4.4", "4.3", "4.2", "4.1", "4.0", "3.14", "3.13", "3.12"],
    "Victoria 3": ["1.14", "1.13", "1.12", "1.11", "1.10", "1.9", "1.8"],
    "Imperator": ["2.0"],
    "Crusader Kings II": ["3.3"],
}


def versions_for(game):
    return list(GAME_VERSIONS.get(game, []))


def _parts(v):
    v = (v or "").strip().lower().lstrip("v")
    return [p for p in re.split(r"[.\s]+", v) if p]


def clean(v):
    """'v1.20.1 (Crozier)' -> '1.20.1'; '' if no version in it."""
    m = re.search(r"\d+(\.\d+)*", v or "")
    return m.group(0) if m else ""


def compatible(supported, game_version):
    """Does a mod's supported_version fit the game version?
    Compares major.minor like the launcher's warning does; '*' matches anything from there on.
    Returns None when either side is unknown (then no warning is shown)."""
    spec, game = _parts(supported), _parts(clean(game_version))
    if not spec or not game:
        return None
    for i in range(min(2, len(game))):
        if i >= len(spec):
            return True                         # '1' covers every 1.x
        if spec[i] == "*" or "*" in spec[i]:
            return True
        if not spec[i].isdigit():
            return None
        if int(spec[i]) != int(game[i]):
            return False
    return True
