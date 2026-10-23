"""Crash analysis: what the game was doing when it crashed, and which mods are most likely to blame.

A Paradox crash leaves a folder in Documents\\Paradox Interactive\\<game>\\crashes\\<game>_<date>_<time>:

    exception.txt   the exception (C0000005 access violation...) and a stack trace (no function names in
                    release builds, so it only says which program or driver crashed)
    meta.yml        game version, DLC, hardware and the mods that were loaded, in load order
    logs/           error.log, debug.log, game.log of that session
    minidump.dmp, last_save.ck3, pdx_settings.txt

The stack trace can't name a mod, so the evidence is the session's error log. Every error is sorted into a
kind (a file that doesn't parse, something a mod uses that doesn't exist, a duplicate, cosmetic...) and
traced to the mod whose file the error points at (the copy the game really loaded: the last one in the
load order). Each mod's errors are weighed (broken files most, cosmetic ones hardly at all), the last
errors before the crash count more, and other evidence joins in: conflicts in the playset (from the
Conflicts tab's analysis), objects a mod's copy of a game file leaves out that others use, missing
required mods, mods made for an older game version. The game's own rename tables (trait_conversion.lookup
and friends) explain errors like "Cannot find scholar": renamed to "erudite" in this version.

The result is a ranked list of suspects with reasons and how sure the app is, plus a step-by-step culprit
hunt (turn half the suspects off, play, answer, repeat) for when the logs can't tell.
"""
import math
import os
import re
import time

import analysis as A

# ------------------------------------------------------------------ reading a crash folder
EXC_PLAIN = {
    "C0000005": ("access violation", "The game tried to use memory that wasn't there: almost always something "
                 "it expected to exist was missing or broken (a mod using a removed trait, event or "
                 "building, a broken file), or a graphics driver problem."),
    "C00000FD": ("stack overflow", "Something called itself without end: usually a mod's scripted effect or "
                 "event that triggers itself (an endless loop)."),
    "C0000094": ("division by zero", "A calculation divided by zero: often a mod's value or modifier set to 0 "
                 "where the game divides by it."),
    "E06D7363": ("C++ exception", "The game hit an error it didn't handle: often a missing or broken file."),
    "C0000409": ("security check", "The game stopped itself after detecting corrupted memory."),
    "C000001D": ("illegal instruction", "The processor got an instruction it doesn't support (rare; drivers or "
                 "hardware)."),
    "80000003": ("breakpoint", "The game stopped itself on purpose after a failed internal check."),
}
DRIVER_HINTS = (("amdxx", "AMD graphics driver"), ("atiumd", "AMD graphics driver"), ("aticfx", "AMD graphics driver"),
                ("amdvlk", "AMD graphics driver"), ("nvwgf", "NVIDIA graphics driver"), ("nvoglv", "NVIDIA graphics driver"),
                ("nvd3d", "NVIDIA graphics driver"), ("igd", "Intel graphics driver"), ("d3d11", "Direct3D"),
                ("d3d12", "Direct3D"), ("dxgi", "DirectX"), ("vulkan", "Vulkan"), ("steam_api", "Steam"))


class Crash:
    """One crash folder, read."""

    def __init__(self, folder):
        self.folder = folder
        self.name = os.path.basename(folder.rstrip("\\/"))
        self.meta = {}
        self.mod_names = []            # in load order, as meta.yml lists them
        self.dlc = []
        self.game_version = ""
        self.when = 0.0                # epoch seconds
        self.exception = ""            # e.g. C0000005
        self.exception_name = ""
        self.exception_plain = ""
        self.module = ""               # first non-system module in the stack trace
        self.driver = ""               # a graphics driver / system part, when that's what crashed
        self.stack = []
        self.logs = {}                 # name -> path
        self.size = 0
        self.stage = ""

    @property
    def is_session(self):
        return False


def _read(path, limit=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit) if limit else f.read()
    except OSError:
        return ""


def read_meta(text):
    meta, mods, dlc = {}, [], []
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z_0-9]+)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1]
        if re.fullmatch(r"Mod_\d+", k):
            mods.append((int(k[4:]), v))
        elif re.fullmatch(r"DLC_\d+", k):
            dlc.append((int(k[4:]), v))
        else:
            meta[k] = v
    return meta, [v for _, v in sorted(mods)], [v for _, v in sorted(dlc)]


def read_crash(folder):
    c = Crash(folder)
    c.meta, c.mod_names, c.dlc = read_meta(_read(os.path.join(folder, "meta.yml")))
    c.game_version = c.meta.get("AppVersion", "")
    dt = c.meta.get("DateTime", "")
    try:
        c.when = time.mktime(time.strptime(dt[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        try:
            c.when = os.path.getmtime(folder)
        except OSError:
            c.when = 0
    exc = _read(os.path.join(folder, "exception.txt"), 200000)
    m = re.search(r"Exception\s+([0-9A-Fa-f]{8})(?:\s*\(([^)]*)\))?", exc)
    if m:
        c.exception = m.group(1).upper()
        name, plain = EXC_PLAIN.get(c.exception, ((m.group(2) or "").lower().replace("exception_", "")
                                                  .replace("_", " ") or "unknown error", ""))
        c.exception_name, c.exception_plain = name, plain
    for line in exc.splitlines():
        sm = re.match(r"\s*\d+\s+(\S+)\s+(.*)$", line)
        if sm:
            c.stack.append((sm.group(1), sm.group(2).strip()))
    sysmods = ("kernel32", "ntdll", "kernelbase", "ucrtbase", "msvcp", "vcruntime", "user32")
    for mod, _ in c.stack:
        low = mod.lower()
        if any(s in low for s in sysmods):
            continue
        c.module = mod
        break
    for mod, _ in c.stack[:6]:
        for pat, what in DRIVER_HINTS:
            if pat in mod.lower():
                c.driver = what
                break
        if c.driver:
            break
    logdir = os.path.join(folder, "logs")
    for n in ("error.log", "debug.log", "game.log", "system.log"):
        p = os.path.join(logdir, n)
        if os.path.isfile(p):
            c.logs[n] = p
    try:
        c.size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(folder) for f in fs)
    except OSError:
        pass
    return c


class Session(Crash):
    """The last game session's own logs (no crash): its errors, read the same way."""

    def __init__(self, data_dir):
        super().__init__(os.path.join(data_dir, "logs"))
        self.name = "Last session"
        for n in ("error.log", "debug.log", "game.log"):
            p = os.path.join(self.folder, n)
            if os.path.isfile(p):
                self.logs[n] = p
        try:
            self.when = os.path.getmtime(self.logs.get("error.log") or self.folder)
        except OSError:
            self.when = 0

    @property
    def is_session(self):
        return True


def find_crashes(data_dir):
    """Crash folders of a game, newest first."""
    root = os.path.join(data_dir, "crashes")
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for n in names:
        p = os.path.join(root, n)
        if os.path.isdir(p) and (os.path.isfile(os.path.join(p, "meta.yml")) or
                                 os.path.isfile(os.path.join(p, "exception.txt"))):
            out.append(read_crash(p))
    out.sort(key=lambda c: c.when, reverse=True)
    return out


# ------------------------------------------------------------------ reading the error log
LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\[([EWDI])\]\[([^\]]+?)(?::\d+)?\]:\s?(.*)$")
_EXT = r"(?:txt|gui|yml|mod|asset|dds|gfx|shader|csv|lookup|png|tga|mesh|anim|json|info|font)"
FILE_RES = [
    re.compile(r"(?:in )?file:\s*\"([^\"]+?\." + _EXT + r")\"", re.I),
    re.compile(r"(?:in)?file:\s*'?([\w./\\ \-+&()']+?\." + _EXT + r")'?(?=[\s:,)]|$)", re.I),
    re.compile(r"File '([^']+?\." + _EXT + r")'", re.I),
    re.compile(r"in both '([^']+)' and '([^']+)'", re.I),
    re.compile(r"Loaded \[\d+\] events from '([^']+)'"),
    re.compile(r"\(expanded from file: ([^\s]+\." + _EXT + r")", re.I),
    re.compile(r"((?:gui|common|events|gfx|history)/[\w./\-]+\.(?:gui|txt)):\d+"),
]
MISSING_FILE = re.compile(r"(?:VFSOpen Error: |missing texture '|Could not find (?:file|texture) ')([\w./\\\-]+\.\w{2,5})")


class Entry:
    __slots__ = ("time", "level", "src", "text", "files", "kind", "obj", "n", "missing_file")

    def __init__(self, t, level, src, text):
        self.time, self.level, self.src, self.text = t, level, src, text
        self.files, self.kind, self.obj, self.n, self.missing_file = [], "other", "", 0, ""


# kind, weight towards a crash, plain words
KINDS = {
    "assert": (25.0, "The game's own check failed", "the game stopped on an internal check right after reading this "
                                                    "mod's file: the closest thing to a direct accusation a log "
                                                    "can give"),
    "definition": (6.0, "Broken definition", "a trait, modifier or other definition with values the game doesn't "
                                             "accept: the game builds it anyway, half broken, and characters get it"),
    "gui": (4.0, "Interface file that doesn't work", "an interface file (.gui) that fails to build with this game "
                                                     "version: windows or map icons break, often a crash"),
    "syntax": (4.0, "File that doesn't load", "a file the game couldn't read properly (a typo, a missing brace "
                                              "or an outdated format): part of the mod is simply skipped"),
    "missing": (2.0, "Uses something that doesn't exist", "the mod uses a trait, event, modifier, building or "
                                                         "effect that this game version (or this mod set) "
                                                         "doesn't have: typical of mods made for an older version "
                                                         "or missing a required mod"),
    "event": (3.0, "Broken event", "an event the game couldn't build (no ID, no namespace, wrong structure)"),
    "victim": (0.3, "Hit by another mod's change", "the mod uses something another mod's copy of a game file "
                                                    "leaves out: that other mod is the one to look at"),
    "duplicate": (1.0, "Defined twice", "two files define the same thing; one silently wins"),
    "script": (0.6, "Script mistake", "a script that works on the wrong kind of thing (scope) or can't find "
                                      "its target"),
    "loc": (0.05, "Text", "missing or duplicate text keys: wrong or missing words in game, never a crash"),
    "graphics": (0.05, "Graphics", "missing pictures or portrait settings: looks wrong, rarely a crash"),
    "encoding": (0.0, "File encoding", "a file not saved as UTF-8 with BOM: the game reads it anyway"),
    "descriptor": (0.0, "Mod descriptor", "an odd supported_version in a .mod file: harmless"),
    "other": (0.3, "Other", "other errors"),
}
KIND_ORDER = ["assert", "definition", "gui", "syntax", "event", "missing", "victim", "duplicate", "script", "other", "graphics", "loc", "encoding",
              "descriptor"]

OBJ_PATTERNS = [re.compile(p, re.I) for p in (
    r"Cannot find '?([\w.:-]+)'? in [\w ]*?database",
    r"Cannot find trait group '?([\w.-]+)",
    r"Unknown (?:trait|effect|trigger|modifier type|death reason|scripted \w+|game rule|building)[: ]+'?([\w.:-]*\w)'?",
    r"Failed to lookup \w+ '([\w.:-]+)'",
    r"Invalid building type '?([\w.-]+)",
    r"unknown (?:random )?event with ID \[([\w.:-]+)\]",
    r"Event \[([\w.:-]+)\] not found",
    r"Failed to scope to \w+ '([\w.:-]+)'",
    r"Modifier '([\w.-]+)' doesn't match expected type",
    r"Invalid database object '([\w.:-]+)'",
    r"Failed to find a valid event target link '([\w.:-]+)'",
    r"Invalid (?:trait|faith|culture|religion|doctrine|tradition|innovation|holding|title|building)[^\n']*'([\w.:-]+)'",
)]
MISSING_WORDS = ("not found in database", "not a valid government rule", "is not defined", "isn't defined",
                 "undefined event", "undefined effect", "undefined trigger", "doesn't match expected type")
DB_CLASS = re.compile(r"Not found in database class C(\w+?)(?:Type)?Database")


def _object(e):
    for rx in OBJ_PATTERNS:
        m = rx.search(e.text)
        if m:
            return m.group(1)
    m = DB_CLASS.search(e.text)
    if m:
        return "(a " + re.sub(r"(?<!^)(?=[A-Z])", " ", m.group(1)).lower() + ")"
    return ""


DEF_FOLDERS = ("common/traits/", "common/modifiers/", "common/static_modifiers/", "common/opinion_modifiers/",
               "common/event_modifiers/", "common/game_rules/", "common/defines/", "common/men_at_arms_types/",
               "common/buildings/", "common/holdings/", "common/landed_titles/", "common/religion/",
               "common/culture/", "common/dynasties/", "common/bookmarks/", "common/character_backgrounds/",
               "common/lifestyles/", "common/focuses/", "common/court_positions/", "common/council_positions/",
               "common/governments/", "common/laws/", "common/accolade_types/", "common/artifacts/")


def classify(e):
    t, s = e.text, e.src.lower()
    low = t.lower()
    if "assertion failed" in low or s.startswith(("pdx_assert", "assert")) or "fatal" in low and "error" in low:
        return "assert"
    if s.startswith("dlc_descriptor") or "supported_version" in low:
        return "descriptor"
    if "utf8-bom" in low or "utf-8-bom" in low or ("encoding" in low and "should be" in low):
        return "encoding"
    if s.startswith(("pdx_localize", "culture_name_equivalency", "localization", "pdx_loc")) or \
            "localization key" in low or "missing loc" in low or "unrecognized loc key" in low:
        return "loc"
    if s.startswith(("portraitcontext", "ethnicity", "gene", "portrait", "pdx_gfx", "gfx_", "texture",
                     "virtualfilesystem", "pdx_gui_datatypes", "coat_of_arms", "mesh", "entity",
                     "artifact_visual")) or "texture" in low or "vfsopen" in low or "cannot find entity" in low:
        return "graphics"
    if s.startswith(("pdx_gui_factory", "pdx_data_factory", "pdx_gui_layout", "gui_")) or \
            (".gui" in low and ("failed" in low or "could not find widget" in low)):
        return "gui"
    if s.startswith(("pdx_persistent_reader", "modifier", "trait")) and any(
            f in low for f in DEF_FOLDERS) and ("cannot be used in" in low or "unknown modifier" in low or
                                                "invalid" in low or "unexpected token" in low or
                                                "not a valid" in low):
        return "definition"
    if any(rx.search(t) for rx in OBJ_PATTERNS) or any(w in low for w in MISSING_WORDS):
        return "missing"
    if s.startswith(("pdx_persistent_reader", "lexer", "parser")) or "unexpected token" in low or \
            "missing '}'" in low or "unexpected end of file" in low or "cannot read this many" in low or \
            ("unknown command" in low and "mtth" in low):
        return "syntax"
    if s.startswith(("jomini_eventmanager", "event.cpp", "event")) and ("not a valid event id" in low or
                                                                        "namespace" in low or "theme missing" in low
                                                                        or "duplicate event" in low):
        return "event"
    if "duplicate" in low or "collides with" in low or "id_override_priority" in low or \
            "defined in both" in low or "already defined" in low:
        return "duplicate"
    if ("inconsistent" in low and "scope" in low) or "event target" in low or "failed to read" in low or \
            "postvalidate" in low:
        return "script"
    return "other"


def norm_rel(p):
    p = p.replace("\\", "/").strip().strip("'\"")
    p = re.sub(r"^.*?/(?=(common|events|gui|gfx|localization|localisation|history|map_data|music|sound|"
               r"content_source|fonts|data_binding|notifications|tests|mod)/)", "", p)
    return p.lstrip("./").lower()


def read_log(path, max_entries=200000):
    """Errors (E) of a log, with continuation lines joined. Returns [Entry] in order."""
    out = []
    cur = None
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with f:
        for raw in f:
            line = raw.rstrip("\n")
            m = LINE.match(line)
            if m:
                if cur is not None:
                    out.append(cur)
                    if len(out) >= max_entries:
                        cur = None
                        break
                t, lvl, src, text = m.groups()
                cur = Entry(t, lvl, src.strip(), text) if lvl == "E" else None
            elif cur is not None and line.strip():
                cur.text += "\n" + line.strip()
        if cur is not None:
            out.append(cur)
    for i, e in enumerate(out):
        e.n = i
        files = []
        for rx in FILE_RES:
            for mm in rx.finditer(e.text):
                for g in mm.groups():
                    if g:
                        r = norm_rel(g)
                        if r and r not in files:
                            files.append(r)
        mf = MISSING_FILE.search(e.text)
        if mf:
            e.missing_file = norm_rel(mf.group(1))
            files = [x for x in files if x != e.missing_file]
        e.files = files
        e.kind = classify(e)
        e.obj = _object(e)
    return out


# ------------------------------------------------------------------ the game's own rename tables
def renames(van):
    """{old name: new name} from the game's *.lookup tables (e.g. common/traits/trait_conversion.lookup:
    'scholar = erudite'): things a version renamed, which older mods still use."""
    out = {}
    if van is None or not getattr(van, "roots", None):
        return out
    try:
        if van._index is None:
            van.path("")
        rels = [r for r in van._index if r.endswith(".lookup") and "conversion" in r]
    except Exception:
        rels = []
    for rel in rels:
        for line in _read(van.path(rel)).splitlines():
            m = re.match(r"\s*([\w.-]+)\s*=\s*([\w.-]+)", line)
            if m and not line.lstrip().startswith("#"):
                out[m.group(1)] = m.group(2)
    return out


# ------------------------------------------------------------------ who is to blame
class Suspect:
    def __init__(self, key, name):
        self.key, self.name = key, name
        self.score = 0.0
        self.counts = {}               # kind -> number of errors in its files
        self.samples = {}              # kind -> [Entry] (a few)
        self.last_words = 0            # errors in its files in the last moments before the crash
        self.reasons = []              # (weight, text)
        self.issues = []               # analysis.Issue of the playset involving it
        self.objects = {}              # things it uses that don't exist: name -> count
        self.renamed = {}              # old -> new (the game renamed it)
        self.removes = []              # (object, rel): game objects its copy of a file leaves out, used by others
        self.breaks = 0                # errors in other mods' files caused by what it leaves out
        self.hit_by = {}               # other key -> errors here caused by what that mod leaves out
        self.asserts = []              # the game's own checks that failed on its files
        self.cleared = ""              # when it was in a game that worked (and unchanged since)
        self.in_crashes = None         # (crashes at this stage it was in, crashes at this stage)
        self.stage_hits = []           # folders it touches that the game uses at the crash's stage
        self.clear_factor = 1.0
        self.passed = ""               # the game got past start-up with it (in a later crash)
        self.gone = False              # not installed any more (known only by name)
        self.position = 0              # in the crash's load order (1-based)
        self.outdated = ""             # e.g. "1.19"
        self.missing_deps = []
        self.sure = "unlikely"

    @property
    def errors(self):
        return sum(self.counts.values())

    def add(self, w, text):
        if w > 0:
            self.score += w
            self.reasons.append((w, text))


SURE = {"likely": "Likely", "possible": "Possible", "unlikely": "Unlikely"}


class Result:
    def __init__(self, crash):
        self.crash = crash
        self.entries = []
        self.by_kind = {}              # kind -> count
        self.suspects = []             # [Suspect], most suspicious first
        self.keys = []                 # the crash's mods (installed ones), in load order
        self.unknown_mods = []         # in meta.yml but not installed now
        self.phase = ""                # what the game was doing
        self.phase_detail = ""
        self.duration = ""             # how long the session ran
        self.last = []                 # the last errors before the crash
        self.vanilla_errors = 0        # errors in the game's own files
        self.missing_objects = {}      # name -> count (across all mods)
        self.renamed = {}
        self.outdated = []             # keys made for an older version
        self.issues = []
        self.error = ""
        self.stage = ""
        self.history_used = False
        self.good_sessions = []

    def suspect(self, key):
        return next((s for s in self.suspects if s.key == key), None)

    def top(self, n=5):
        return [s for s in self.suspects if s.sure != "unlikely"][:n]


def _ver(v):
    m = re.match(r"\s*v?(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def map_mods(names, an):
    """Mod names from meta.yml -> installed mod keys (exact name first, then the clean title, then a close
    match). Returns ([keys in order], [names not found])."""
    by_name, by_clean = {}, {}
    for k, f in an.facts.items():
        by_name.setdefault(f.name.strip().lower(), k)
        by_clean.setdefault(A.clean_title(f.name).lower(), k)
    keys, unknown = [], []
    for n in names:
        k = by_name.get(n.strip().lower()) or by_clean.get(A.clean_title(n).lower())
        if not k:
            best = max(an.facts.values(), key=lambda f: A.similarity(n, f.name), default=None)
            if best is not None and A.similarity(n, best.name) >= 0.9:
                k = best.key
        if k and k not in keys:
            keys.append(k)
        elif not k:
            unknown.append(n)
    return keys, unknown


# ------------------------------------------------------------------ how far a session got
STAGE_ORDER = {"db": 1, "menu": 1, "setup": 2, "load": 2, "gui": 3, "play": 4, "save": 4}
STAGE_TEXT = {
    "db": "while loading the game's files (before the main menu)",
    "setup": "while setting up the world for a new game (start date, history, characters)",
    "load": "while loading a save",
    "gui": "while building the map and the interface (just before you could play)",
    "play": "while playing",
    "save": "while saving",
}
# what a mod has to touch to matter at each stage
STAGE_FOLDERS = {
    "db": ("common/", "events/", "gui/", "localization/"),
    "setup": ("common/traits/", "history/", "common/bookmarks/", "common/on_action/", "common/game_rules/",
              "common/dynasties/", "common/dynasty_houses/", "common/landed_titles/", "common/religion/",
              "common/culture/", "common/holdings/", "common/character_backgrounds/", "common/genes/",
              "common/ethnicities/", "common/dna_data/", "common/coat_of_arms/", "common/script_values/",
              "common/scripted_effects/"),
    "load": ("common/traits/", "common/modifiers/", "common/religion/", "common/culture/", "common/game_rules/"),
    "gui": ("gui/", "gfx/interface/", "gfx/map/", "common/scripted_guis/", "data_binding/", "fonts/",
            "common/named_colors/", "gfx/fonts/"),
    "play": ("events/", "common/on_action/", "common/scripted_effects/", "common/decisions/",
             "common/character_interactions/", "common/schemes/", "common/men_at_arms_types/", "common/activities/",
             "common/story_cycles/", "common/casus_belli_types/", "gfx/models/", "common/ai_"),
    "save": ("common/", "events/"),
}


def _tail_lines(path, size=400000):
    try:
        n = os.path.getsize(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            if n > size:
                f.seek(n - size)
            return f.read().splitlines()
    except OSError:
        return []


def crash_stage(crash):
    """The stage a crash happened at: from its debug log, or 'gui' when the game's own check failed on an
    interface file just before it."""
    dbg = crash.logs.get("debug.log")
    if not dbg:
        return "", ""
    st, dur, _, _ = stage_of(dbg)
    err = crash.logs.get("error.log")
    if err:
        tail = [ln.lower() for ln in _tail_lines(err)[-30:]]
        if any("assert" in ln for ln in tail) and any(".gui" in ln for ln in tail):
            st = "gui"
    return st, dur


def stage_of(debug_path):
    """(stage code, duration text, start hh:mm:ss, end hh:mm:ss) of a session's debug log."""
    tail = _tail_lines(debug_path)
    head = _read(debug_path, 20000).splitlines()
    lines = [ln for ln in tail if LINE.match(ln) and "][E][" not in ln]
    last = "\n".join(lines[-80:]).lower()
    t0 = next((m.group(1) for m in map(LINE.match, head) if m), "")
    t1 = next((m.group(1) for m in map(LINE.match, reversed(tail)) if m), "")
    dur = ""
    if t0 and t1:
        a = sum(int(x) * k for x, k in zip(t0.split(":"), (3600, 60, 1)))
        b = sum(int(x) * k for x, k in zip(t1.split(":"), (3600, 60, 1)))
        s = (b - a) % 86400
        dur = f"{s // 60} min {s % 60} s" if s < 3600 else f"{s // 3600} h {s % 3600 // 60} min"
    if "quit:" in last:
        st = "play" if ("inside game" in last or "savegame" in "\n".join(tail[-3000:]).lower()) else "menu"
    elif "gamestate_persistence" in last or "saving" in last or "savegame" in last:
        st = "save"
    elif "bookmark" in last or "holy_order" in last or "history" in last or ("dynasty" in last and "invalid" in last):
        st = "setup"
    elif "loading save" in last or "loading game" in last or "deserializ" in last:
        st = "load"
    elif "regiment" in last or "army_manager" in last or "daily" in last or "monthly" in last or \
            "mesh_streamer" in last or "requesting mesh" in last or "tick" in last:
        st = "play"
    elif "widget" in last or "gui" in last or "animation" in last or "map_icon" in last or "glow" in last:
        st = "gui"
    elif "database node init" in last or ("loaded [" in last and "events from" in last) or "pre-enumerating" in last:
        st = "db"
    else:
        st = ""
    return st, dur, t0, t1


def session_mods(debug_path):
    """[(name, .mod file name)] of the mods a session loaded, from its debug log ('Mod:' block)."""
    head = _read(debug_path, 600000)
    m = re.search(r"\nMod:\n((?:[^\n]*\|[^\n]*\n)+)", head)
    out = []
    if m:
        for line in m.group(1).splitlines():
            parts = line.split("|")
            if len(parts) >= 3 and parts[-1].strip().lower() == "enabled":
                out.append((parts[0].strip(), os.path.basename(parts[1].strip().replace("\\", "/"))))
    return out


def _phase(crash, entries):
    """(plain words, duration) for the result summary."""
    st, dur = crash_stage(crash)
    if any(e.kind == "assert" for e in entries[-30:]) and any(
            f.endswith(".gui") for e in entries[-30:] for f in e.files):
        st = "gui"
    crash.stage = st
    return STAGE_TEXT.get(st, ""), dur


# ------------------------------------------------------------------ crashes and good games, remembered
class History:
    """Every crash and every game that ended well, with the mods they had. Kept in a small JSON file, filled
    from the crash folders and from the game's logs folder after each session (the logs of the last
    session are replaced by the next one, so they're read whenever the app looks)."""

    def __init__(self, path):
        self.path = path
        self.sessions = []
        try:
            with open(path, encoding="utf-8") as f:
                import json
                self.sessions = json.load(f).get("sessions", [])
        except Exception:
            self.sessions = []

    def save(self):
        import json
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sessions": self.sessions[-400:]}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def ids(self):
        return {s["id"] for s in self.sessions}

    def refresh(self, data_dir, crashes=None):
        """Add crashes and the last session's logs that aren't known yet. Returns how many were added."""
        known = self.ids()
        added = 0
        crashes = crashes if crashes is not None else find_crashes(data_dir)
        for c in crashes:
            if c.name in known:
                continue
            dbg = c.logs.get("debug.log", "")
            mods = session_mods(dbg) if dbg else []
            st = crash_stage(c)[0]
            self.sessions.append({"id": c.name, "time": c.when, "outcome": "crash", "stage": st,
                                  "mods": [k for _, k in mods] or [], "names": [n for n, _ in mods] or c.mod_names})
            added += 1
        logs = os.path.join(data_dir, "logs", "debug.log")
        if os.path.isfile(logs):
            st, dur, t0, t1 = stage_of(logs)
            end = os.path.getmtime(logs)
            sid = f"session_{time.strftime('%Y%m%d', time.localtime(end))}_{t0.replace(':', '')}"
            crashed = any(abs(c.when - end) < 300 for c in crashes)
            if sid not in known and st in ("play", "menu") and not crashed and t0:
                mods = session_mods(logs)
                self.sessions.append({"id": sid, "time": end, "outcome": "ok", "stage": st,
                                      "mods": [k for _, k in mods], "names": [n for n, _ in mods]})
                added += 1
        if added:
            self.sessions.sort(key=lambda s: s.get("time", 0))
            self.save()
        return added

    def add(self, outcome, keys, stage="play", sid=None, names=()):
        """A result the player told us (the culprit hunt): crashed or not with these mods."""
        self.sessions.append({"id": sid or f"told_{int(time.time())}", "time": time.time(), "outcome": outcome,
                              "stage": stage, "mods": list(keys), "names": list(names), "told": True})
        self.save()

    def good(self, before=None, at_least=""):
        need = STAGE_ORDER.get(at_least, 0)
        return [s for s in self.sessions if s["outcome"] == "ok" and (before is None or s["time"] < before + 1)
                and STAGE_ORDER.get(s.get("stage", ""), 0) >= need]

    def crashes(self, stage=""):
        return [s for s in self.sessions if s["outcome"] == "crash" and (not stage or s.get("stage") == stage)]


_NAMES = {}


def _in(sess, s):
    """Was this suspect's mod in that session? (by .mod file, or by name for mods not installed any more)"""
    if s.key in (sess.get("mods") or ()):
        return True
    names = _NAMES.get(id(sess))
    if names is None or names[0] is not sess:
        names = _NAMES[id(sess)] = (sess, {n.strip().lower() for n in sess.get("names", ())})
    names = names[1]
    return s.name.strip().lower() in names


# ------------------------------------------------------------------ the suspects
def analyse(crash, an, van=None, playset_keys=None, game_version="", hidden=None, history=None):
    """The suspects of one crash (or session). an: analysis.Analysis of the installed mods. history: a History
    (crashes and good games) for the evidence across sessions."""
    R = Result(crash)
    if an is None:
        R.error = "The mod check hasn't finished yet."
        return R
    by_name = {}
    for k, f in an.facts.items():
        by_name.setdefault(f.name.strip().lower(), k)
    dbg = crash.logs.get("debug.log")
    loaded = session_mods(dbg) if dbg else []
    if loaded:                                          # the debug log names the exact .mod files: best
        R.keys = [k for _, k in loaded if k in an.facts]
        R.unknown_mods = [n for n, k in loaded if k not in an.facts]
        if not R.keys and crash.mod_names:
            R.keys, R.unknown_mods = map_mods(crash.mod_names, an)
    elif crash.mod_names:
        R.keys, R.unknown_mods = map_mods(crash.mod_names, an)
    else:
        R.keys = [k for k in (playset_keys or []) if k in an.facts]
    keys = R.keys
    pos = {k: i + 1 for i, k in enumerate(keys)}
    gv = crash.game_version or game_version
    owner = {}
    for k in keys:
        for rel in an.facts[k].files:
            owner[rel] = k
    S = {k: Suspect(k, an.facts[k].name) for k in keys}
    for k in keys:
        S[k].position = pos[k]
    # mods of that game that aren't installed any more: no files to read, but the history still counts
    gone = {}
    for i, n in enumerate(R.unknown_mods):
        s = Suspect("?" + n, n)
        s.gone = True
        s.position = len(keys) + i + 1
        gone[s.key] = s
    R.renamed = renames(van)
    removed_by = {}
    for k in keys:
        for (folder, name), rel in getattr(an.facts[k], "removed", {}).items():
            removed_by.setdefault(name, []).append(k)
    # ---- the errors
    entries = read_log(crash.logs["error.log"]) if "error.log" in crash.logs else []
    R.entries = entries
    R.phase, R.duration = _phase(crash, entries)
    stage = getattr(crash, "stage", "")
    R.stage = stage
    total = len(entries)
    last_from = max(0, total - 40)
    for i, e in enumerate(entries):
        R.by_kind[e.kind] = R.by_kind.get(e.kind, 0) + 1
        if e.obj and e.kind == "missing":
            R.missing_objects[e.obj] = R.missing_objects.get(e.obj, 0) + 1
        files = list(e.files)
        if e.kind == "assert" and not files:          # an assertion names no file: the errors just before it do
            for p in entries[max(0, i - 8):i][::-1]:
                if p.files and p.time == e.time:
                    files = list(p.files)
                    break
        who = []
        for rel in files:
            if rel.startswith("mod/") and rel.endswith(".mod"):
                k = os.path.basename(rel)
                if k in S:
                    who.append(k)
                continue
            k = owner.get(rel)
            if k:
                who.append(k)
            elif van is not None and getattr(van, "roots", None) and van.path(rel):
                R.vanilla_errors += 1
        culprits = [k for k in removed_by.get(e.obj, ()) if k not in who] if e.kind == "missing" and e.obj else []
        late = e.n >= last_from
        for k in culprits:
            S[k].breaks += 1
            if late:
                S[k].last_words += 1
        for k in dict.fromkeys(who):
            s = S[k]
            kind = "victim" if culprits else e.kind
            for c in culprits:
                s.hit_by[c] = s.hit_by.get(c, 0) + 1
            s.counts[kind] = s.counts.get(kind, 0) + 1
            lst = s.samples.setdefault(kind, [])
            if len(lst) < 6:
                lst.append(e)
            if e.obj and e.kind == "missing":
                s.objects[e.obj] = s.objects.get(e.obj, 0) + 1
                if e.obj in R.renamed:
                    s.renamed[e.obj] = R.renamed[e.obj]
            if late and not culprits and KINDS[kind][0] > 0.1:
                s.last_words += 1
            if kind == "assert":
                s.asserts.append(e)
    R.last = entries[-12:]
    for s in S.values():
        for kind, n in s.counts.items():
            w = KINDS[kind][0]
            if w <= 0:
                continue
            pts = w * min(3.0, math.log2(1 + n))        # many errors of one kind don't pile up without end
            s.add(pts, f"{n} error{'s' if n != 1 else ''} in its files: {KINDS[kind][1].lower()}")
        if s.hit_by:
            who = ", ".join(f'"{S[k].name}"' for k in s.hit_by)
            s.reasons.append((0.0, f"its {sum(s.hit_by.values())} \"doesn't exist\" errors come from {who} leaving "
                                   "things out, not from this mod"))
        if s.renamed:
            pairs = ", ".join(f"{a} → {b}" for a, b in list(s.renamed.items())[:4])
            s.add(2.0, f"uses names this game version renamed ({pairs}): made for an older version")
        if s.last_words:
            s.add(min(12.0, 5.0 + 2 * math.log2(1 + s.last_words)),
                  f"{s.last_words} of the last errors before the crash point at it")
        if s.asserts:
            s.reasons.insert(0, (0.0, "right before the crash: " + s.asserts[-1].text.split("\n")[0][:160]))
    missing = set(R.missing_objects)
    if missing:
        for k in keys:
            for (folder, name), rel in getattr(an.facts[k], "removed", {}).items():
                if name in missing:
                    S[k].removes.append((name, rel))
        for s in S.values():
            if s.removes:
                ex = ", ".join(n for n, _ in s.removes[:4])
                s.add(6.0 + 2 * math.log2(1 + len(s.removes)) + 2 * min(3, math.log2(1 + s.breaks)),
                      f"its copy of {s.removes[0][1]} leaves out {ex}, which other mods use: "
                      f"{s.breaks} error{'s' if s.breaks != 1 else ''} say{'s' if s.breaks == 1 else ''} "
                      "they're missing")
    # ---- the stage it crashed at: what a mod touches there
    if stage in STAGE_FOLDERS and stage not in ("db", "save"):
        folders = STAGE_FOLDERS[stage]
        for k in keys:
            f = an.facts[k]
            hits = sorted({r.split("/")[0] + "/" + r.split("/")[1] if r.count("/") >= 2 else r.split("/")[0]
                           for r in f.files if r.startswith(folders)})
            if hits:
                S[k].stage_hits = hits
                S[k].add(3.0, f"it changes what the game uses at that stage ({', '.join(hits[:3])})")
    # ---- across sessions: crashes and games that worked
    H = history
    R.history_used = False
    cutoff = crash.when or time.time()
    ALL = dict(S)
    ALL.update(gone)
    if H is not None:
        need = STAGE_ORDER.get(stage, 0)
        # sessions that got past this crash's stage: games that worked (strong), and crashes that happened
        # later on (the game got through this stage with their mods first)
        past = []
        for sess in H.sessions:
            if sess.get("id") == crash.name:
                continue
            reached = STAGE_ORDER.get(sess.get("stage", ""), 0)
            if sess["outcome"] == "ok" and reached >= max(1, need):
                past.append((sess, 0.2, "it was in a game that worked ({when})"))
            elif sess["outcome"] == "crash" and stage in ("db", "setup", "load") and reached >= 3:
                # start-up crashes happen every time: a game that got past start-up with it says something
                past.append((sess, 0.5, "the game got past start-up with it ({when}, a crash later on)"))
        goods_p = [p for p in past if p[1] <= 0.2]
        later_p = [p for p in past if p[1] > 0.2]
        R.good_sessions = [p[0] for p in goods_p]
        if past:
            R.history_used = True
        if goods_p:
            cleared = {}
            for sess, factor, why in sorted(goods_p, key=lambda x: -x[0]["time"]):
                for k, s in ALL.items():
                    if k in cleared or not _in(sess, s):
                        continue
                    f = an.facts.get(k)
                    changed_at = getattr(f.mod, "installed_at", 0) if f else 0
                    if changed_at and changed_at > sess["time"] + 60:
                        # updated after that game: it may not be the copy that worked
                        cleared[k] = (sess, 0.6, why + ", but it was updated since")
                    else:
                        cleared[k] = (sess, factor, why + " and hasn't changed since")
            unc = [k for k in ALL if k not in cleared]
            share = len(unc) / max(1, len(ALL))
            goods = [p[0]["time"] for p in goods_p if p[0]["time"] < cutoff]
            last_good = max(goods) if goods else 0
            for k, s in ALL.items():
                f = an.facts.get(k)
                changed_at = getattr(f.mod, "installed_at", 0) if f else 0
                if k in cleared:
                    sess, factor, why = cleared[k]
                    when = time.strftime("%d %b %H:%M", time.localtime(sess["time"]))
                    s.cleared = when
                    s.clear_factor = factor
                    s.reasons.append((0.0, why.format(when=when)))
                else:
                    s.add(8.0 + 18.0 * (1 - share), "not in any game that worked")
                    if last_good and last_good < changed_at < cutoff:
                        s.add(10.0, "installed or updated after your last game that worked (" +
                              time.strftime("%d %b", time.localtime(last_good)) + ")")
                    elif changed_at and 0 < cutoff - changed_at < 3 * 86400:
                        s.add(6.0, "installed or updated in the 3 days before the crash")
        # start-up crashes happen every time: if the game got past start-up with a mod (and crashed later
        # on for something else), that mod probably isn't what stops it starting. Softer than a good game.
        for k, s in ALL.items():
            if s.cleared:
                continue
            for sess, factor, why in sorted(later_p, key=lambda x: -x[0]["time"]):
                if _in(sess, s):
                    when = time.strftime("%d %b %H:%M", time.localtime(sess["time"]))
                    s.passed = when
                    s.clear_factor = factor
                    s.reasons.append((0.0, why.format(when=when)))
                    break
        same = [c for c in H.crashes(stage) if c["time"] <= cutoff + 1] if stage else []
        if len(same) >= 2:
            for k, s in ALL.items():
                inn = sum(1 for c in same if _in(c, s))
                s.in_crashes = (inn, len(same))
                if inn == len(same):
                    s.add(5.0, f"in all {len(same)} crashes at this stage")
                elif inn >= len(same) * 0.7:
                    s.add(2.0, f"in {inn} of {len(same)} crashes at this stage")
    # ---- what changed just before the crash (when there's no game that worked to compare with)
    if not R.history_used and crash.when:
        for k in keys:
            ch = getattr(an.facts[k].mod, "installed_at", 0) or 0
            if 0 < crash.when - ch < 3 * 86400:
                S[k].add(6.0, "installed or updated in the 3 days before the crash")
    # ---- conflicts, required mods, versions
    try:
        issues = A.playset_issues(an, keys, gv)
    except Exception:
        issues = []
    R.issues = issues
    w_sev = {"critical": 4.0, "high": 1.5, "medium": 0.4, "low": 0.1}
    for i in issues:
        if hidden and hidden(i):
            continue
        for k in i.mods:
            if k in S:
                S[k].issues.append(i)
                if i.kind == "missing_dependency" and k == i.mods[0]:
                    S[k].missing_deps.append(i.title)
    for s in S.values():
        if s.issues:
            pts = 0.0
            for i in s.issues:
                w = 7.0 if i.kind == "missing_dependency" else w_sev.get(i.severity, 0)
                if i.kind in ("event_collision", "on_action", "removed_used", "two_conversions", "incompatible"):
                    w = max(w, 2.0)
                pts += w
            worst = sorted(s.issues, key=lambda i: i.rank)[0]
            s.add(min(pts, 8.0), f"{len(s.issues)} conflict{'s' if len(s.issues) != 1 else ''} in this playset "
                                 f"(worst: {worst.title.lower()})")
    g = _ver(gv)
    for k in keys:
        f = an.facts[k]
        v = _ver(f.mod.supported)
        if g and v and v < g:
            S[k].outdated = f"{v[0]}.{v[1]}"
            R.outdated.append(k)
            S[k].add(1.5, f"made for game {v[0]}.{v[1]} (the game was {g[0]}.{g[1]})")
    # ---- mods that got past this stage elsewhere: down, but not out (some crashes don't happen every time)
    for s in ALL.values():
        s.score *= s.clear_factor
    # ---- how sure: against the strongest suspect
    R.suspects = sorted(ALL.values(), key=lambda s: (-s.score, s.position))
    top = R.suspects[0].score if R.suspects else 0
    for rank, s in enumerate(R.suspects):
        strong = s.asserts or s.removes or s.missing_deps or (R.history_used and not s.cleared and rank < 3)
        if rank < 5 and s.score >= max(14, 0.5 * top) and (strong or s.score >= 0.7 * top):
            s.sure = "likely"
        elif rank < 15 and s.score >= max(6, 0.25 * top):
            s.sure = "possible"
        else:
            s.sure = "unlikely"
        s.reasons.sort(key=lambda r: -r[0])
    return R


# ------------------------------------------------------------------ the culprit hunt
def clusters(an, keys):
    """Groups of mods that have to be on or off together: a mod and every mod that needs it (declared
    dependencies, or building on it). {base key: [keys]}"""
    keyset = set(keys)
    by_name = {A.clean_title(an.facts[k].name).lower(): k for k in keys}
    needs = {k: set() for k in keys}                # k needs these
    for k in keys:
        f = an.facts[k]
        for d in f.mod.dependencies:
            t = by_name.get(A.clean_title(d).lower())
            if t and t != k:
                needs[k].add(t)
        for base, n in getattr(f, "builds_on", {}).items():
            if base in keyset and base != k and n >= 3:
                needs[k].add(base)
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for k, ns in needs.items():
        for t in ns:
            a, b = find(k), find(t)
            if a != b:
                parent[a] = b
    groups = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return groups


class Hunt:
    """Finding the culprit by halves. State is a plain dict (saved in the settings):
        playset: the playset that crashed, test: the copy the hunt changes, pool: suspects left,
        off: the ones turned off this round, round, history: [(round, off, crashed)]."""

    def __init__(self, state):
        self.s = state

    @staticmethod
    def start(an, keys, order_hint=()):
        """keys: the crashing playset's enabled mods. order_hint: most suspicious first."""
        return {"pool": list(keys), "off": [], "round": 0, "history": [], "hint": list(order_hint),
                "done": "", "result": []}

    def remaining_rounds(self, an):
        n = len(clusters(an, self.s["pool"]))
        return max(0, math.ceil(math.log2(n))) if n > 1 else 0

    def next_round(self, an, all_on):
        """Pick the half of the suspects to turn off. Returns the keys to turn off (whole groups, plus every
        mod outside the pool that needs one of them)."""
        pool = [k for k in self.s["pool"] if k in an.facts]
        groups = list(clusters(an, pool).values())
        if len(groups) <= 1:
            self.s["done"] = "found"
            self.s["result"] = pool
            return []
        rank = {k: i for i, k in enumerate(self.s.get("hint", []))}
        groups.sort(key=lambda g: min(rank.get(k, 10 ** 6) for k in g))       # most suspicious first
        half = sum(len(g) for g in groups) / 2.0
        off, n = [], 0
        for g in groups:
            if n >= half and off:
                break
            off.extend(g)
            n += len(g)
        if len(off) == len(pool):              # never everything: keep the last group on
            off = [k for k in off if k not in groups[-1]]
        # mods that need a mod we turn off go off too (they'd break without it)
        allg = clusters(an, list(all_on))
        extra = set()
        for g in allg.values():
            if any(k in off for k in g):
                extra.update(g)
        self.s["off"] = sorted(set(off) | (extra & set(pool)), key=lambda k: pool.index(k))
        self.s["also_off"] = sorted((extra - set(pool)) & set(all_on))
        self.s["round"] += 1
        return self.s["off"] + self.s["also_off"]

    def answer(self, crashed):
        """The player's answer for this round: did the game still crash?"""
        off, pool = self.s["off"], self.s["pool"]
        self.s["history"].append([self.s["round"], list(off), bool(crashed)])
        if crashed:
            self.s["pool"] = [k for k in pool if k not in off]     # the culprit is still on
        else:
            self.s["pool"] = list(off)                              # turning these off fixed it
        self.s["off"] = []
        if not self.s["pool"]:
            self.s["done"] = "unclear"
        return self.s["pool"]


# ------------------------------------------------------------------ the crash report
def report(R, an, app_name="", game=""):
    c = R.crash
    L = []
    w = L.append
    title = "Error report" if c.is_session else "Crash report"
    w(f"# {title}: {game or c.meta.get('AppName', 'the game')} {c.game_version}".rstrip())
    w("")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.when)) if c.when else "?"
    w(f"Made by {app_name or 'the launcher'} on {time.strftime('%Y-%m-%d %H:%M')}. "
      f"{'Session' if c.is_session else 'Crash'}: {when}" + (f", folder `{c.name}`" if not c.is_session else "") + ".")
    w("")
    w("## What happened")
    w("")
    if not c.is_session:
        w(f"- **Exception:** {c.exception} ({c.exception_name})" + (f" in {c.module}" if c.module else ""))
        if c.exception_plain:
            w(f"- **In plain words:** {c.exception_plain}")
        if c.driver:
            w(f"- **Crashed inside:** {c.driver}: update or reinstall it before blaming mods.")
    if R.phase:
        w(f"- **When:** {R.phase}" + (f", {R.duration} after the game started" if R.duration else ""))
    w(f"- **Mods loaded:** {len(c.mod_names) or len(R.keys)}" +
      (f" ({len(R.unknown_mods)} no longer installed: {', '.join(R.unknown_mods[:8])})" if R.unknown_mods else ""))
    if c.meta.get("OperatingSystem") or c.meta.get("GPUName"):
        w(f"- **PC:** {c.meta.get('OperatingSystem', '')}, {c.meta.get('CPUModel', '').strip()}, "
          f"{c.meta.get('GPUName', '')}, {c.meta.get('SystemMemory', '?')} MB RAM")
    w(f"- **Errors in the log:** {len(R.entries)}" + (": " + ", ".join(
        f"{R.by_kind[k]} {KINDS[k][1].lower()}" for k in KIND_ORDER if R.by_kind.get(k)) if R.by_kind else ""))
    w("")
    w("## Suspects")
    w("")
    top = [s for s in R.suspects if s.sure != "unlikely"][:15]
    if not top:
        w("No mod stands out. The errors don't point at any mod strongly; use the step-by-step culprit hunt.")
    for n, s in enumerate(top, 1):
        f = an.facts.get(s.key)
        w(f"### {n}. {s.name} ({SURE[s.sure]})")
        w("")
        w(f"- Workshop ID: {f.wid if f and f.wid else '-'}; place in the load order: {s.position}; made for: "
          f"{f.mod.supported if f else '-'}")
        for _, r in s.reasons[:6]:
            w(f"- {r}")
        ex = [e for k in KIND_ORDER for e in s.samples.get(k, [])][:5]
        if ex:
            w("")
            w("```text")
            for e in ex:
                w(f"[{e.time}] " + e.text.replace("\n", " | ")[:400])
            w("```")
        w("")
    if R.missing_objects:
        w("## Things mods use that this game doesn't have")
        w("")
        for name, n in sorted(R.missing_objects.items(), key=lambda x: -x[1])[:30]:
            new = R.renamed.get(name)
            w(f"- `{name}` ({n}x)" + (f": renamed to `{new}` in this game version" if new else ""))
        w("")
    if R.last:
        w("## The last errors before the crash")
        w("")
        w("```text")
        for e in R.last:
            w(f"[{e.time}][{e.src}] " + e.text.replace("\n", " | ")[:400])
        w("```")
        w("")
    w("## Mods in load order")
    w("")
    for i, n in enumerate(c.mod_names or [an.facts[k].name for k in R.keys], 1):
        w(f"{i}. {n}")
    w("")
    w("## Prompt for an AI")
    w("")
    w("Copy everything below the line into an AI chat, and attach (or paste) this whole report after it.")
    w("")
    w("---")
    w("")
    w(f"You are an expert {game or 'Crusader Kings III'} modder and troubleshooter. My game "
      f"{'crashed' if not c.is_session else 'logged errors'} with the mods listed in the attached report. The "
      "report has the exception, when it happened, the suspects a mod manager found (with the errors traced to "
      "each mod's files), things mods use that the game doesn't have, the last errors before the crash and the "
      "full load order.")
    w("")
    w("1. Tell me which mod (or pair of mods) most likely caused it and why, in plain words.")
    w("2. For each suspect: is it outdated for this game version, missing a required mod, broken, or in "
      "conflict with another mod? What can I do (update, remove, reorder, a compatibility patch)?")
    w("3. If the errors don't explain the crash, say so and give me the order in which to test mods.")
    w("4. Keep it short and practical.")
    w("")
    return "\n".join(L) + "\n"


def default_name(R, ext=".md"):
    c = R.crash
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(c.when)) if c.when else "now"
    return f"{'error' if c.is_session else 'crash'}_report_{stamp}{ext}"
