"""
Deep analysis of a set of mods: what each mod is, what it defines and uses, and every way two mods
can get in each other's way.

How Paradox games (Clausewitz / Jomini, CK3 in particular) combine mods:
  * same relative file path in two mods -> the mod loaded LATER replaces the whole file
    (the only thing load order decides);
  * the same object (trait, effect, decision ...) defined in files with DIFFERENT names -> decided by
    the file names (LIOS: the alphabetically last file wins), whatever the mod order. Modders use
    aaa_/zzz_ names on purpose for compatibility hooks, so not every such case is a problem;
  * events can't be overridden one at a time: two mods defining the same event id = duplicate;
  * on_actions merge their `events` / `on_actions` lists, but `effect` / `trigger` blocks replace
    each other (and log errors);
  * localisation keys defined twice are an error unless the file sits in a `replace` folder;
  * replace_path drops the game's own files in a folder (total conversions).

The analysis reads every text file of every mod once (normalised lines, defined names, references,
localisation keys, on_action blocks) and compares with the game's own files when the install folder
is known, so "changed" means changed compared to the game, not just "present".
"""
import json
import os
import re
import threading
import time

import modscan
import roles as R
import script as SC
from installer import read_text

try:
    from sources import clean_title, similarity, tokens
except Exception:                     # pragma: no cover
    def clean_title(s):
        return re.sub(r"[\[\(\{][^\]\)\}]*[\]\)\}]", " ", s).strip()

    def tokens(s):
        return [t for t in re.split(r"[^0-9a-z]+", clean_title(s).lower()) if t]

    def similarity(a, b):
        ta, tb = set(tokens(a)), set(tokens(b))
        return len(ta & tb) / max(1, len(ta | tb))

TEXT_EXT = {".txt", ".gui", ".gfx", ".yml", ".yaml", ".asset", ".csv", ".json", ".shader", ".fxh",
            ".settings", ".info", ".lua", ".sfx", ".mod", ".map"}
SCRIPT_EXT = {".txt", ".gui", ".gfx", ".asset"}
BIN_UNITS = 3
MERGING_FOLDERS = ("common/on_action", "common/defines")
SEVERITIES = ["critical", "high", "medium", "low", "info"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def is_text(rel):
    return os.path.splitext(rel)[1].lower() in TEXT_EXT


# ================================================================== reading files (cached)
_cache, _lock = {}, threading.Lock()


def _stamp(path):
    try:
        st = os.stat(path)
        return (path, st.st_size, st.st_mtime)
    except OSError:
        return None


def _lines_of(text):
    return frozenset(" ".join(SC.strip_comments(ln).split()) for ln in text.splitlines()) - {""}


def read_cached(path, keep=True):
    """(text, normalised line set) of a file. Only a few hundred files are kept in memory (the game's
    files that mods override and the files mods share), so big libraries don't fill the RAM."""
    key = _stamp(path)
    if key is None:
        return "", frozenset()
    with _lock:
        hit = _cache.get(key)
    if hit:
        return hit
    try:
        text = read_text(path)
    except OSError:
        return "", frozenset()
    res = (text, _lines_of(text))
    if keep:
        with _lock:
            if len(_cache) > 600:
                _cache.clear()
            _cache[key] = res
    return res


def text_lines(path):
    return read_cached(path)[1]


# ================================================================== the game's own files
def content_roots(game_dir):
    if not game_dir or not os.path.isdir(game_dir):
        return []
    roots = [os.path.join(game_dir, d) for d in ("game", "jomini") if os.path.isdir(os.path.join(game_dir, d))]
    return roots or [game_dir]


class Vanilla:
    """The game's own files: path lookup, and (lazily, cached on disk) which names each folder defines."""

    def __init__(self, game_dir, cache_dir=""):
        self.game_dir = game_dir
        self.roots = content_roots(game_dir)
        self._index = None
        self._defs = {}            # folder -> set of names
        self._lock = threading.Lock()
        self.cache_path = ""
        if cache_dir and self.roots:
            ver = ""
            try:
                with open(os.path.join(game_dir, "launcher", "launcher-settings.json"), encoding="utf-8-sig") as f:
                    ver = json.load(f).get("rawVersion") or ""
            except Exception:
                pass
            stamp = re.sub(r"[^0-9A-Za-z]+", "_", ver or str(int(os.path.getmtime(self.roots[0]))))
            self.cache_path = os.path.join(cache_dir, f"vanilla_names_{stamp}.json")
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    self._defs = {k: set(v) for k, v in json.load(f).items()}
            except Exception:
                self._defs = {}

    def _build(self):
        idx = {}
        for root in self.roots:
            for d, _, files in os.walk(root):
                for fn in files:
                    full = os.path.join(d, fn)
                    idx.setdefault(os.path.relpath(full, root).replace("\\", "/").lower(), full)
        self._index = idx

    def path(self, rel):
        if not self.roots:
            return None
        if self._index is None:
            with self._lock:
                if self._index is None:
                    self._build()
        return self._index.get(rel)

    def names(self, folder):
        """Names the game itself defines in a folder (common/traits, events ...)."""
        if not self.roots:
            return set()
        if folder in self._defs:
            return self._defs[folder]
        if self._index is None:
            self.path("")
        out = set()
        pre = folder + "/"
        for rel, full in self._index.items():
            if rel.startswith(pre) and rel.endswith(".txt"):
                try:
                    out.update(SC.defined_keys(read_text(full)))
                except OSError:
                    pass
        self._defs[folder] = out
        return out

    def all_names(self):
        """Every name the game defines anywhere in common/ and events/ (for telling a mod's own new names
        from the game's)."""
        if not self.roots:
            return set()
        if getattr(self, "_all", None) is None:
            if self._index is None:
                self.path("")
            folders = {("events" if r.startswith("events/") else r.rsplit("/", 1)[0])
                       for r in self._index if r.endswith(".txt") and r.startswith(("common/", "events/"))}
            new = [fo for fo in folders if fo not in self._defs]
            folders |= set(self._defs)
            out = set()
            for fo in folders:
                out |= self.names(fo)
            self._all = out
            if new:
                self.save()
        return self._all

    def define_values(self):
        """{(category, KEY): value} of the game's own common/defines."""
        if getattr(self, "_defvals", None) is None:
            out = {}
            if self.roots:
                if self._index is None:
                    self.path("")
                for rel, full in sorted(self._index.items()):
                    if rel.startswith("common/defines/") and rel.endswith(".txt"):
                        try:
                            out.update(SC.define_values(read_text(full)))
                        except OSError:
                            pass
            self._defvals = out
        return self._defvals

    def save(self):
        if self.cache_path:
            try:
                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump({k: sorted(v) for k, v in self._defs.items()}, f)
            except Exception:
                pass


_vanilla = {}


def vanilla_for(game_dir, cache_dir=""):
    key = os.path.normcase(os.path.abspath(game_dir)) if game_dir else ""
    if key not in _vanilla:
        _vanilla[key] = Vanilla(game_dir, cache_dir)
    return _vanilla[key]


def object_folder(rel):
    """common/traits/00_traits.txt -> common/traits ; events/x/y.txt -> events"""
    if rel.startswith("events/"):
        return "events"
    return rel.rsplit("/", 1)[0]


# ================================================================== Workshop descriptions
_BB = re.compile(r"\[/?(?:b|i|u|s|h\d|list|olist|\*|quote|spoiler|strike|noparse|hr|code|table|tr|td|th)\]", re.I)
_URL = re.compile(r"\[url=([^\]]*)\](.*?)\[/url\]", re.I | re.S)
_VERB = re.compile(r"\b(load(?:ed|ing|s)?|plac(?:e|ed|ing)|put|position(?:ed)?|keep|move)\b", re.I)
_NEG = re.compile(r"\b(not|never|don'?t|do not|doesn'?t|isn'?t|no need)\b", re.I)
_TOP = re.compile(r"\b(?:at|to|on|near)\s+the\s+(?:very\s+|absolute\s+)?(?:top|beginning|start)\b|"
                  r"\btop\s+of\s+(?:your|the)\b|\bload(?:ed)?\s+(?:it\s+|this\s+(?:mod\s+)?)?first\b|"
                  r"\b(?:above|before)\s+(?:all|everything|every other mod|other mods)\b", re.I)
_BOTTOM = re.compile(r"\b(?:at|to|on|near)\s+the\s+(?:very\s+|absolute\s+)?(?:bottom|end)\b|"
                     r"\bbottom\s+of\s+(?:your|the)\b|\bload(?:ed)?\s+(?:it\s+|this\s+(?:mod\s+)?)?last\b|"
                     r"\b(?:after|below|under)\s+(?:all|everything|every other mod|other mods)\b", re.I)
_AFTER = re.compile(r"\b(after|below|under|beneath|underneath)\s+(.{2,90})", re.I)
_BEFORE = re.compile(r"\b(before|above|on top of|ahead of)\s+(.{2,90})", re.I)
_INCOMPAT = re.compile(r"\b(not\s+compatible\s+with|incompatible\s+with|isn'?t\s+compatible\s+with|"
                       r"(?:does\s*n[o']t|won'?t|will\s+not)\s+work\s+(?:with|alongside|together\s+with)|"
                       r"conflicts?\s+with|do\s+not\s+use\s+(?:it\s+)?(?:with|alongside)|"
                       r"don'?t\s+use\s+(?:it\s+)?(?:with|alongside)|breaks?\s+(?:with)?)\s+(.{2,120})", re.I)
_REQUIRES = re.compile(r"\b(requires?|required(?:\s+items?)?|depends\s+on|needs)\b\s*:?\s*(.{2,120})", re.I)
_COMPAT_WITH = re.compile(r"\b(compatible\s+with|works\s+(?:fine\s+)?with|compatch\s+for|patch\s+for)\s+(.{2,120})", re.I)
_STOPWORDS = {"The", "This", "That", "These", "It", "If", "You", "Your", "And", "Or", "But", "For", "With",
              "Steam", "Workshop", "Paradox", "Crusader", "Kings", "Europa", "Universalis", "Hearts", "Iron",
              "Stellaris", "Victoria", "Imperator", "Rome", "CK", "CK2", "CK3", "EU4", "EU5", "HOI4", "DLC",
              "DLCs", "AI", "UI", "GUI", "I", "A", "An", "In", "On", "To", "Of", "As", "At", "By", "We",
              "My", "Mod", "Mods", "Note", "Notes", "Version", "Patch", "Update", "Ironman", "Achievements",
              "Yes", "No", "New", "All", "Also", "Thanks", "Credits", "Features", "Compatibility", "Load",
              "Order", "Discord", "GitHub", "Github", "Links", "Changelog", "English", "Please", "Only",
              "Not", "Works", "Place", "Put", "Read", "Readme", "Content", "Translations", "Localization",
              "Game", "Rules", "Mechanics", "Events", "Decisions", "Install", "Enjoy", "Support"}


def clean_description(text):
    text = _URL.sub(lambda m: f" {m.group(2)} <<{m.group(1)}>> ", text or "")
    text = _BB.sub(" ", text)
    return re.sub(r"\[/?[a-z]+(=[^\]]*)?\]", " ", text, flags=re.I)


def _sentences(text):
    for block in re.split(r"[\r\n]+|(?<=[.!?;])\s+", text):
        s = " ".join(block.split())
        if 6 <= len(s) <= 400:
            yield s


def _abbreviates(alias, name):
    """'Unop' abbreviates 'Unofficial Patch': starts like it, letters in order, reaches the second word."""
    a = alias.lower()
    words = [w.lower() for w in re.split(r"[^0-9A-Za-z]+", clean_title(name)) if w]
    if len(words) < 2 or a in words or not a.startswith(words[0][0]):
        return False
    it = iter("".join(words))
    if not all(ch in it for ch in a):
        return False
    return words[1][0] in a[1:]


def self_aliases(name, description):
    out = set()
    words = [w for w in re.split(r"[^0-9A-Za-z]+", clean_title(name)) if w]
    if 3 <= len(words) <= 5:
        out.add("".join(w[0] for w in words).upper())
    counts = {}
    for w in re.findall(r"\b[A-Z][A-Za-z0-9]{2,5}\b", clean_description(description or "")):
        counts[w] = counts.get(w, 0) + 1
    for w, n in counts.items():
        if n >= 3 and w not in _STOPWORDS and _abbreviates(w, name):
            out.add(w)
    return {a for a in out if 3 <= len(a) <= 6}


def mentions(span, other):
    """Does this text name `other` (ModFacts)? By Workshop link, full name or short name."""
    for wid in re.findall(r"id=(\d+)", span):
        if other.wid and wid == other.wid:
            return True
    plain = re.sub(r"<<[^>]*>>", " ", span)
    ot, st = set(tokens(other.name)), set(tokens(plain))
    if ot and len(ot) >= 2 and ot <= st:
        return True
    if len(ot) == 1:
        (w,) = ot
        if len(w) >= 5 and w in st:
            return True
    for a in other.aliases:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", plain, re.I):
            return True
    return False


def parse_hints(me, description, others):
    """[(kind, other or None, snippet)] with kind in after/before/top/bottom/after_tc/before_tc/
    incompatible/requires/compatible."""
    out = []
    text = clean_description(description)
    for s in _sentences(text):
        snippet = re.sub(r"\s*<<[^>]*>>", "", s)[:170]
        for m in _INCOMPAT.finditer(s):
            for o in others:
                if o is not me and mentions(m.group(2), o):
                    out.append(("incompatible", o, snippet))
        for m in _REQUIRES.finditer(s):
            for o in others:
                if o is not me and mentions(m.group(2), o):
                    out.append(("requires", o, snippet))
        for m in _COMPAT_WITH.finditer(s):
            if _NEG.search(s[:m.start()][-12:]):
                continue
            for o in others:
                if o is not me and mentions(m.group(2), o):
                    out.append(("compatible", o, snippet))
        if not (_VERB.search(s) or re.search(r"load\s*order", s, re.I)):
            continue
        neg, verb = _NEG.search(s), _VERB.search(s)
        if neg and verb and neg.start() < verb.start():
            continue
        if _BOTTOM.search(s):
            out.append(("bottom", None, snippet))
        elif _TOP.search(s):
            out.append(("top", None, snippet))
        for rx, kind in ((_AFTER, "after"), (_BEFORE, "before")):
            for m in rx.finditer(s):
                span = m.group(2)
                if re.match(r"(all|everything|every other|other mods|it\b|this\b|that\b)", span, re.I):
                    continue
                if re.match(r"total conversions?|overhauls?", span, re.I):
                    out.append((kind + "_tc", None, snippet))
                    continue
                for o in others:
                    if o is not me and mentions(span, o):
                        out.append((kind, o, snippet))
    order_dirs = {}
    for kind, o, _ in out:
        if o is not None and kind in ("after", "before"):
            order_dirs.setdefault(o.key, set()).add(kind)
    seen, res = set(), []
    for h in out:
        sig = (h[0], h[1].key if h[1] else None)
        if sig in seen or (h[0] in ("after", "before") and len(order_dirs.get(h[1].key, ())) > 1):
            continue                 # "load ABOVE to keep X ... BELOW for Y" is a choice, not a rule
        if h[0] == "compatible" and any(x[0] == "incompatible" and x[1] is h[1] for x in out):
            continue
        seen.add(sig)
        res.append(h)
    return res


def load_workshop(net, ids, cache_path, max_age=7 * 86400):
    """{workshop id: {"text", "title", "preview", "tags"}} from Steam's public API, cached. Never raises."""
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    now = time.time()
    want = [i for i in ids if i and (i not in cache or now - cache[i].get("at", 0) > max_age
                                     or "preview" not in cache[i] or "tags" not in cache[i])]
    if want and net is not None:
        try:
            import sources as S
            got = S.steam_details(net, want)
            for i in want:
                d = got.get(i) or {}
                cache[i] = {"at": now, "text": d.get("description", ""), "title": d.get("title", ""),
                            "preview": d.get("preview_url", ""),
                            "tags": [t.get("tag", "") for t in d.get("tags", []) if t.get("tag")]}
            os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        except Exception:
            pass
    return {i: cache[i] for i in ids if i in cache}


# ================================================================== facts per mod
class ModFacts:
    def __init__(self, mod, wid=""):
        self.mod, self.key, self.name, self.wid = mod, mod.key, mod.name, wid
        self.files = set(mod.files)
        self.units = {}              # rel -> lines it changed compared to the game (or all lines if new)
        self.total = 1
        self.overrides = 0           # files replacing one of the game's own files
        self.light_override_share = 0.0
        self.defines = {}            # (folder, name) -> file name   (common/* objects and event ids)
        self.def_hash = {}           # (folder, name) -> hash of its definition, to spot identical copies
        self.loc = {}                # localisation key -> rel (outside replace folders)
        self.loc_hash = {}           # localisation key -> hash of its text
        self.loc_replace = set()
        self.on_actions = {}         # on_action name -> (rel, set of inner keys, hash of its body)
        self.ref_files = {}          # identifier -> in how many of its script files it appears
        self.namespaces = set()
        self.aliases = set()
        self.hints = []
        self.builds_on = {}          # other key -> how many of the other mod's own names it uses
        self.used_by = {}
        self.uses_examples = {}      # other key -> a few names, for explanations
        self.role = None             # roles.RoleResult
        self.description = ""
        self.ws_tags = []            # categories ticked on its Workshop page
        self.define_vals = {}        # (category, KEY) -> (rel, value): common/defines it changes
        self.gui_defs = {}           # GUI template / type name -> (rel, "template" | "type"), new files only
        self.removed = {}            # (folder, name) -> rel: game objects its copy of a game file leaves out

    @property
    def tier(self):
        return self.role.role.rank if self.role else 7


class FileConflict:
    """One shared path between mods a and b and what happens to each side.
    kind: same | a_in_b (b's copy contains a's changes) | b_in_a | clash.
    lost_x: changed lines x loses if the other wins; broken_x: names x defines in that file and uses
    elsewhere, which disappear if the other wins."""
    __slots__ = ("rel", "a", "b", "kind", "lost_a", "lost_b", "broken_a", "broken_b", "objs_a", "objs_b", "objs_both")

    def __init__(self, rel, a, b, kind, lost_a=0, lost_b=0, broken_a=(), broken_b=(), objs_a=(), objs_b=(),
                 objs_both=()):
        self.rel, self.a, self.b, self.kind = rel, a, b, kind
        self.lost_a, self.lost_b, self.broken_a, self.broken_b = lost_a, lost_b, list(broken_a), list(broken_b)
        # objects inside the file: changed by a and lost if b's copy wins, the other way round, changed by both
        self.objs_a, self.objs_b, self.objs_both = list(objs_a), list(objs_b), list(objs_both)


FIND_TXT = ("Look for a compatch on the Workshop; if there is none, a compatch report gives a modder (or an AI) "
            "what's needed to make one")


class Issue:
    """Something that goes wrong (or might) when these mods are used together.

    effect: what you'll notice in game. confidence: certain / likely / possible. remedy: what solves it:
    order (load order decides), compatch, choose (keep one), enable (turn something on), none (harmless).
    objects: [(folder or kind, name)] the conflict is about (for reports). patched_by: an installed mod
    that solves it (set per playset)."""

    def __init__(self, kind, severity, mods, title, detail, items=(), fix="", order=False, effect="",
                 confidence="", remedy="", objects=()):
        self.kind, self.severity, self.mods = kind, severity, tuple(mods)
        self.title, self.detail, self.items, self.fix, self.order = title, detail, list(items), fix, order
        meta = DIAG.get(kind, ("", "likely", "compatch"))
        self.effect = effect or meta[0]
        self.confidence = confidence or meta[1]
        self.remedy = remedy or ("order" if order else meta[2])
        self.objects = list(objects)
        self.patched_by = None
        self.patch_off = None            # an installed compatch for it that's turned off

    @property
    def rank(self):
        return SEV_RANK.get(self.severity, 9)

    def signature(self):
        """Stays the same between analyses (for hiding a conflict you've looked at)."""
        return f"{self.kind}|{'|'.join(sorted(self.mods))}|{self.title}"

    def copy(self):
        c = Issue.__new__(Issue)
        c.__dict__.update(self.__dict__)
        return c


# what you'll notice in game, how sure the app is, and what solves it (defaults per kind)
DIAG = {
    "incompatible": ("Errors, broken events or a game that won't start, as its author warns.", "certain", "choose"),
    "duplicate_mod": ("Two copies fight over every file: half of each version is used.", "certain", "choose"),
    "missing_dependency": ("Parts of the mod do nothing or show errors (missing names in events and menus).",
                           "certain", "enable"),
    "two_conversions": ("A broken map: provinces, titles and history from two different worlds.", "certain", "choose"),
    "file_clash": ("Part of the losing mod's changes are simply missing in game.", "certain", "order"),
    "gui_window": ("The window shows only one mod's version: the other mod's buttons or panels are gone.",
                   "certain", "order"),
    "object_override": ("One mod's change to these game objects is ignored.", "certain", "compatch"),
    "name_collision": ("One mod's new object behaves like the other's: odd traits, decisions or effects.",
                       "likely", "compatch"),
    "event_collision": ("Some events of one mod never show up, or show the other mod's text; the error log "
                        "fills up.", "certain", "compatch"),
    "on_action": ("Something one mod does on a game moment (birth, death, yearly...) never happens.",
                  "certain", "compatch"),
    "loc_duplicate": ("A few texts show one mod's wording instead of the other's.", "certain", "none"),
    "replace_path": ("Two different worlds: things missing or doubled.", "certain", "choose"),
    "removed_used": ("The other mod's events, decisions or effects that rely on them fail, and the error log "
                     "fills up.", "likely", "compatch"),
    "define_clash": ("The game uses one mod's value for these settings; the other's change has no effect.",
                     "certain", "compatch"),
    "gui_type": ("Buttons, fonts or panels look like one mod's version everywhere.", "likely", "compatch"),
    "version": ("Usually nothing; sometimes small errors where the game changed since.", "possible", "none"),
    "merged": ("Nothing, as long as the merged copy loads last.", "certain", "order"),
    "identical": ("Nothing: both bring the same content.", "certain", "none"),
    "hook": ("Nothing: this is how the mods detect each other.", "certain", "none"),
    "integration": ("Nothing unexpected: one mod adjusts the other on purpose.", "likely", "none"),
}
REMEDY_LABEL = {"order": "Load order decides", "compatch": "Needs a compatch", "choose": "Keep only one",
                "enable": "Turn the missing mod on", "none": "Harmless", "patched": "Solved by a compatch"}
CONFIDENCE_LABEL = {"certain": "Certain", "likely": "Likely", "possible": "Possible"}


ISSUE_KINDS = {
    "incompatible": "Don't work together",
    "duplicate_mod": "Same mod twice",
    "missing_dependency": "Missing a mod it needs",
    "two_conversions": "Two total conversions / map mods",
    "file_clash": "Same file, different content",
    "gui_window": "Both replace the same window",
    "object_override": "Same object defined twice",
    "name_collision": "Same new name used by both",
    "event_collision": "Duplicate event IDs",
    "on_action": "On-action effects overwritten",
    "loc_duplicate": "Same text key in both",
    "replace_path": "Removes game files another mod needs",
    "version": "Made for another game version",
    "merged": "Shared files already merged",
    "identical": "Identical shared files",
    "hook": "Compatibility hooks",
    "integration": "One mod adjusts the other",
    "removed_used": "Removes game objects the other mod uses",
    "define_clash": "Same game settings changed by both",
    "gui_type": "Same interface piece defined by both",
}


class Analysis:
    def __init__(self):
        self.facts = {}
        self.conflicts = {}          # (a, b) sorted -> [FileConflict]
        self.objects = {}            # (a, b) sorted -> [(name, folder, file_a, file_b, kind, winner)]
        self.issues = []
        self.patches = {}            # (a, b) sorted -> [(compatch key, how sure, why)]
        self.edges = []
        self.warnings = []           # (key, text) kept for older callers
        self.used_vanilla = False
        self.used_workshop = False
        self.seconds = 0.0


# ================================================================== the analysis
def _coverage(x_lines, y_lines, van_lines):
    added = x_lines - van_lines if van_lines else x_lines
    removed = van_lines - x_lines if van_lines else frozenset()
    total = len(added) + len(removed)
    if not total:
        return 1.0, 0
    kept = len(added & y_lines) + len(removed - y_lines)
    return kept / total, total - kept


def analyze(mods, game_dir="", workshop=None, workshop_ids=None, stop=None, progress=None, cache_dir="",
            game_version=""):   # game_version kept for older callers; versions are checked per playset
    """mods: every installed mod (modscan.ModInfo). Pair problems are found for all of them once; a
    playset then only looks at the pairs it contains (playset_issues).
    workshop: {workshop id: {"text": description, ...}} or {id: text}. workshop_ids: {mod key: id}."""
    t0 = time.time()
    workshop, workshop_ids = workshop or {}, workshop_ids or {}
    an = Analysis()
    van = vanilla_for(game_dir, cache_dir)
    an.used_vanilla = bool(van.roots)
    an.used_workshop = bool(workshop)
    facts = [ModFacts(m, workshop_ids.get(m.key, "")) for m in mods]
    an.facts = {f.key: f for f in facts}
    say = progress or (lambda txt, p: None)

    # ---- 1. read every mod
    for i, f in enumerate(facts):
        if stop and stop.is_set():
            return an
        say(f"Reading {f.name}", 0.05 + 0.5 * i / max(1, len(facts)))
        _read_mod(f, van)
    # ---- 2. the game's own names, for every folder some mod defines things in
    folders = sorted({fold for f in facts for (fold, _) in f.defines})
    if van.roots:
        missing = [fo for fo in folders if fo not in van._defs]
        if missing:
            say("Reading the game's own definitions (first time only)", 0.58)
        for fo in folders:
            van.names(fo)
        if missing:
            van.save()
    # ---- 3. names, descriptions, who builds on whom, roles
    for f in facts:
        d = workshop.get(f.wid, "")
        f.description = d.get("text", "") if isinstance(d, dict) else (d or "")
        f.ws_tags = list(d.get("tags", [])) if isinstance(d, dict) else []
        f.aliases = self_aliases(f.name, f.description)
    for f in facts:
        if f.description:
            f.hints = parse_hints(f, f.description, facts)
    say("Working out who builds on whom", 0.65)
    _builds_on(facts, van)
    for f in facts:
        f.role = R.classify(f, facts, mentions)
    # ---- 4. shared files
    say("Comparing shared files", 0.75)
    owners = {}
    for f in facts:
        for rel in f.files:
            owners.setdefault(rel, []).append(f)
    for rel, who in owners.items():
        if len(who) < 2:
            continue
        vp = van.path(rel)
        vlines = text_lines(vp) if vp and is_text(rel) else frozenset()
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                a, b = who[x], who[y]
                an.conflicts.setdefault(tuple(sorted((a.key, b.key))), []).append(_compare(rel, a, b, vlines, vp))
    # ---- 5. everything else that can go wrong
    say("Looking for conflicts", 0.88)
    _issues(an, facts, van)
    say("Looking for compatches you have", 0.96)
    an.patches = find_patches(an, facts)
    an.seconds = time.time() - t0
    say("Done", 1.0)
    return an


def _read_mod(f, van):
    light = heavy = 0
    for rel in f.files:
        p = f.mod.paths.get(rel)
        vp = van.path(rel)
        if vp:
            f.overrides += 1
        if not p:
            continue
        ext = os.path.splitext(rel)[1].lower()
        if not is_text(rel):
            u = 0 if vp and modscan.file_hash(p) == modscan.file_hash(vp) else BIN_UNITS
            f.units[rel] = u
            continue
        text, lines = read_cached(p, keep=False)
        vlines = text_lines(vp) if vp else frozenset()
        changed = lines - vlines if vp else lines
        f.units[rel] = len(changed)
        if vp and lines:
            if len(changed) <= 0.15 * len(lines):
                light += 1
            else:
                heavy += 1
        if ext == ".yml":
            entries = SC.loc_entries(text)
            if "/replace/" in rel:
                f.loc_replace |= set(entries)
            else:
                for k, v in entries.items():
                    if k not in f.loc:
                        f.loc[k] = rel
                        f.loc_hash[k] = hash(v)
            continue
        if ext not in SCRIPT_EXT:
            continue
        if rel.startswith("common/defines/") and rel.endswith(".txt"):
            vdef = van.define_values() if van.roots else {}
            for ck, v in SC.define_values(text).items():
                if vdef.get(ck) != v:
                    f.define_vals[ck] = (rel, v)
        if ext == ".gui" and not vp:
            for n, kind in SC.gui_names(text).items():
                f.gui_defs.setdefault(n, (rel, kind))
        if vp and rel.endswith(".txt") and rel.startswith(("common/", "events/")) and \
                not rel.startswith(MERGING_FOLDERS):
            mine = set(SC.defined_keys(text))
            for k in _defined_in(vp) - mine:
                if len(k) >= 4:
                    f.removed[(object_folder(rel), k)] = rel
        if rel.endswith(".txt") and (rel.startswith("common/") or rel.startswith("events/")):
            folder = object_folder(rel)
            fname = rel.rsplit("/", 1)[1]
            if rel.startswith("events/"):
                f.namespaces |= SC.namespaces(text)
            for key, body, _ in SC.blocks(text):
                if key.startswith("@") or key in ("namespace",):
                    continue
                if folder.startswith("common/on_action"):
                    f.on_actions[key] = (rel, SC.inner_keys(body) if body else set(), hash(SC.norm(body)))
                if not folder.startswith(MERGING_FOLDERS) and (folder, key) not in f.defines:
                    f.defines[(folder, key)] = fname
                    f.def_hash[(folder, key)] = hash(SC.norm(body))
        for ident in SC.identifiers(text):
            f.ref_files[ident] = f.ref_files.get(ident, 0) + 1
    f.total = max(1, sum(f.units.values()))
    f.light_override_share = light / (light + heavy) if light + heavy else 0.0


def _builds_on(facts, van):
    """Mod B uses names (effects, triggers, events, values...) that only mod A defines: B builds on A."""
    if not van.roots:
        return                        # without the game's own names we can't tell new names from vanilla ones
    owner = {}
    vanilla_all = van.all_names()
    for f in facts:
        for (folder, key) in f.defines:
            if len(key) < 6 or key in vanilla_all:
                continue
            owner.setdefault(key, set()).add(f.key)
    by_key = {f.key: f for f in facts}
    for b in facts:
        counts, examples = {}, {}
        for ident in b.ref_files:
            own = owner.get(ident)
            if not own or len(own) > 2 or b.key in own:
                continue
            for a in own:
                counts[a] = counts.get(a, 0) + 1
                ex = examples.setdefault(a, [])
                if len(ex) < 4:
                    ex.append(ident)
        for a, n in counts.items():
            if n >= 3:
                b.builds_on[a] = n
                b.uses_examples[a] = examples[a]
                by_key[a].used_by[b.key] = n


def _defined_in(path):
    text, _ = read_cached(path)
    return set(SC.defined_keys(text)) if path.endswith(".txt") else set()


def _broken(f, rel, lost_defs):
    """Names f defined in `rel` that it also uses in other files (they vanish if f's copy loses)."""
    out = []
    for k in lost_defs:
        if f.ref_files.get(k, 0) >= 2:      # used somewhere besides its own definition
            out.append(k)
    return sorted(out)[:50]


def _objects_lost(rel, pa, pb, vp):
    """Inside a shared script file: (objects a changed that b's copy doesn't have the same, the same for b,
    objects both changed differently)."""
    if not rel.endswith(".txt") or not rel.startswith(("common/", "events/", "history/")) or \
            rel.startswith(MERGING_FOLDERS):
        return [], [], []
    ao = SC.object_bodies(read_cached(pa)[0])
    bo = SC.object_bodies(read_cached(pb)[0])
    vo = SC.object_bodies(read_cached(vp)[0]) if vp else {}
    ch_a = {k for k, v in ao.items() if vo.get(k) != v}
    ch_b = {k for k, v in bo.items() if vo.get(k) != v}
    lost_a = sorted(k for k in ch_a if bo.get(k) != ao[k])
    lost_b = sorted(k for k in ch_b if ao.get(k) != bo[k])
    both = sorted(k for k in ch_a & ch_b if ao[k] != bo[k])
    return lost_a, lost_b, both


def _compare(rel, a, b, vlines, vp=None):
    pa, pb = a.mod.paths.get(rel), b.mod.paths.get(rel)
    if pa and pb and modscan.file_hash(pa) == modscan.file_hash(pb):
        return FileConflict(rel, a.key, b.key, "same")
    if not (pa and pb) or not is_text(rel):
        return FileConflict(rel, a.key, b.key, "clash", max(1, a.units.get(rel, BIN_UNITS)),
                            max(1, b.units.get(rel, BIN_UNITS)))
    la, lb = text_lines(pa), text_lines(pb)
    cov_ab, lost_a = _coverage(la, lb, vlines)
    cov_ba, lost_b = _coverage(lb, la, vlines)
    if cov_ab >= 0.9 and cov_ba >= 0.9:
        return FileConflict(rel, a.key, b.key, "same", lost_a, lost_b)
    if cov_ab >= 0.9:
        return FileConflict(rel, a.key, b.key, "a_in_b", lost_a, lost_b)
    if cov_ba >= 0.9:
        return FileConflict(rel, a.key, b.key, "b_in_a", lost_a, lost_b)
    da, db = _defined_in(pa), _defined_in(pb)
    oa, ob, both = _objects_lost(rel, pa, pb, vp)
    return FileConflict(rel, a.key, b.key, "clash", max(1, lost_a), max(1, lost_b),
                        _broken(a, rel, da - db), _broken(b, rel, db - da), oa, ob, both)


# ================================================================== issues
def file_severity(rel, broken=0):
    if rel.startswith("map_data/") or rel.startswith("common/landed_titles/"):
        return "critical" if rel.startswith("map_data/") else "high"
    if rel.startswith("gui/") and rel.endswith(".gui"):
        return "high"
    if broken:
        return "high"
    if rel.startswith(("common/", "events/", "history/")):
        return "medium"
    if rel.startswith(("localization/", "localisation/")):
        return "low"
    return "low"


def _issues(an, facts, van):
    I = an.issues
    by = an.facts
    names = lambda *ks: " and ".join(f'"{by[k].name}"' for k in ks)
    # ---- what the Workshop pages say
    for f in facts:
        for kind, o, snip in f.hints:
            if kind == "incompatible":
                I.append(Issue("incompatible", "critical", [f.key, o.key], f"{names(f.key, o.key)} don't work together",
                               f'{f.name}\'s Workshop page says: "{snip}"', fix="Keep only one of them"))
    # ---- two total conversions / map mods
    big = [f for f in facts if f.role and f.role.role.id in ("total_conversion", "map")]
    for x in range(len(big)):
        for y in range(x + 1, len(big)):
            a, b = big[x], big[y]
            if a.key in b.builds_on or b.key in a.builds_on or a.key in b_dep_keys(b, facts) or \
                    b.key in b_dep_keys(a, facts):
                continue
            I.append(Issue("two_conversions", "critical", [a.key, b.key],
                           f"Two {('total conversions' if 'total_conversion' in (a.role.role.id, b.role.role.id) else 'map mods')}",
                           f"{names(a.key, b.key)} each replace the game world. Only one map can load; the "
                           "other's provinces, titles and history won't match it.", fix="Keep only one of them"))
    # ---- the same mod twice
    for x in range(len(facts)):
        for y in range(x + 1, len(facts)):
            a, b = facts[x], facts[y]
            small = min(len(a.files), len(b.files))
            overlap = len(a.files & b.files)
            same_name = similarity(a.name, b.name) >= 0.92
            if (same_name and overlap >= 0.5 * max(1, small)) or (small >= 10 and overlap >= 0.8 * small):
                I.append(Issue("duplicate_mod", "critical", [a.key, b.key], f"{names(a.key, b.key)} look like the same mod",
                               f"They share {overlap} of {small} files. Two copies (or versions) of one mod "
                               "overwrite each other unpredictably.", fix="Turn one of them off"))
    # ---- shared files
    for (ka, kb), fcs in an.conflicts.items():
        same = [c for c in fcs if c.kind == "same"]
        merged = [c for c in fcs if c.kind in ("a_in_b", "b_in_a")]
        clashes = [c for c in fcs if c.kind == "clash"]
        if same:
            I.append(Issue("identical", "info", [ka, kb], f"{len(same)} identical shared file(s)",
                           "Both ship the same content, so it doesn't matter which loads last.",
                           items=[c.rel for c in same]))
        if merged:
            I.append(Issue("merged", "info", [ka, kb], f"{len(merged)} shared file(s) already merged",
                           "One mod's copy already contains the other's changes; it just has to load "
                           "after it (Auto-sort makes sure).", items=[c.rel for c in merged], order=True))
        if clashes:
            gui = [c for c in clashes if c.rel.startswith("gui/") and c.rel.endswith(".gui")]
            rest = [c for c in clashes if c not in gui]
            if gui:
                I.append(Issue("gui_window", "high", [ka, kb], f"Both replace {_short_files(gui)}",
                               "A .gui window file is replaced whole. Whichever mod loads last provides the "
                               "window; the other mod's additions to it (buttons, panels) disappear.",
                               items=[_clash_line(c, by) for c in gui],
                               fix="Pick the order that keeps the more important window, or find a compatch",
                               order=True))
            if rest:
                sev = min((file_severity(c.rel, len(c.broken_a) + len(c.broken_b)) for c in rest),
                          key=lambda s: SEV_RANK[s])
                broken = sum(len(c.broken_a) + len(c.broken_b) for c in rest)
                both = sorted({o for c in rest for o in c.objs_both})
                objs = [(c.rel, o) for c in rest for o in sorted(set(c.objs_a) | set(c.objs_b))]
                n_obj = len(objs)
                effect = (f"Whichever loads last, the other mod loses its changes to {n_obj} object(s) in these "
                          "files" + (f", {len(both)} of them changed by both (only a compatch can keep both "
                                     "versions)" if both else "") + "." if n_obj else DIAG["file_clash"][0])
                I.append(Issue("file_clash", sev, [ka, kb], f"{len(rest)} file{'s' if len(rest) != 1 else ''} changed differently",
                               "Both mods ship these files with different changes. The mod loaded last provides "
                               "each file whole; the other mod's changes to it are lost." +
                               (f" {broken} of the lost definitions are used elsewhere by their mod, so losing "
                                "them also breaks other parts of it." if broken else ""),
                               items=[_clash_line(c, by) for c in rest],
                               fix=("Load order decides which mod keeps its changes (Auto-sort picks the less "
                                    "damaging winner); only a compatch keeps both" if not both else
                                    "Load order only picks the loser here: both mods change the same objects, so "
                                    "only a compatch keeps both"), order=True, effect=effect,
                               remedy="compatch" if both and len(both) >= 3 else "order", objects=objs))
    # ---- objects defined twice under different file names
    defined = {}
    for f in facts:
        for (folder, key), fname in f.defines.items():
            defined.setdefault((folder, key), []).append((f, fname))
    obj_pairs = {}
    for (folder, key), where in defined.items():
        if len(where) < 2:
            continue
        vanilla_has = key in van.names(folder) if van.roots else None
        for x in range(len(where)):
            for y in range(x + 1, len(where)):
                (fa, na), (fb, nb) = where[x], where[y]
                if fa.key == fb.key or na == nb:
                    continue
                winner = fa.key if na > nb else fb.key          # LIOS: later file name wins
                if fa.def_hash.get((folder, key)) == fb.def_hash.get((folder, key)):
                    kind = "same"
                elif folder == "events":
                    kind = "event"
                elif vanilla_has:
                    kind = "vanilla"
                elif _is_hook(fa, folder, na, key) or _is_hook(fb, folder, nb, key):
                    kind = "hook"
                elif vanilla_has is None:
                    kind = "unknown"
                else:
                    kind = "other_mod" if (fb.key in fa.builds_on or fa.key in fb.builds_on) else "collision"
                pair = tuple(sorted((fa.key, fb.key)))
                fna, fnb = (na, nb) if fa.key == pair[0] else (nb, na)
                obj_pairs.setdefault(pair, []).append((key, folder, fna, fnb, kind, winner))
    an.objects = obj_pairs
    for (ka, kb), objs in obj_pairs.items():
        groups = {}
        for o in objs:
            groups.setdefault(o[4], []).append(o)
        line = lambda o: f"{o[0]}  [{o[1]}]  {by[ka].name}: {o[2]}  |  {by[kb].name}: {o[3]}  ->  {by[o[5]].name}'s is used"
        if "event" in groups:
            g = groups["event"]
            I.append(Issue("event_collision", "high", [ka, kb], f"{len(g)} duplicate event ID(s)",
                           "Both define events with the same IDs in different files. Events can't be overridden "
                           "one by one, so the game keeps one and logs errors; the other mod's event is lost.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           objects=[(o[1], o[0]) for o in g]))
        if "vanilla" in groups:
            g = groups["vanilla"]
            I.append(Issue("object_override", "medium", [ka, kb], f"Both change {len(g)} game object(s)",
                           "Both mods redefine the same objects of the game in files with different names. The "
                           "file name decides which version is used (the alphabetically later one), not the "
                           "load order, so one mod's change to each of these is ignored.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           objects=[(o[1], o[0]) for o in g]))
        if "collision" in groups:
            g = groups["collision"]
            I.append(Issue("name_collision", "high", [ka, kb], f"{len(g)} name(s) used by both for different things",
                           "Both mods add something new under the same name. Only one survives (decided by file "
                           "name), so the other mod's version silently changes behaviour.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           objects=[(o[1], o[0]) for o in g]))
        if "unknown" in groups:
            g = groups["unknown"]
            I.append(Issue("object_override", "low", [ka, kb], f"{len(g)} object(s) defined by both",
                           "Defined in both under different file names; the alphabetically later file wins. "
                           "(Set the game's folder in Settings to tell game objects from new ones.)",
                           items=[line(o) for o in g]))
        if "other_mod" in groups:
            g = groups["other_mod"]
            I.append(Issue("integration", "info", [ka, kb], f"{len(g)} object(s) of one mod adjusted by the other",
                           "One mod redefines things of the other on purpose (it builds on it).",
                           items=[line(o) for o in g]))
        if "same" in groups:
            g = groups["same"]
            I.append(Issue("identical", "info", [ka, kb], f"{len(g)} identical definition(s)",
                           "Both define these the same way (shared code they both include), so it doesn't "
                           "matter which copy the game uses.", items=[line(o) for o in g]))
        if "hook" in groups:
            g = groups["hook"]
            I.append(Issue("hook", "info", [ka, kb], f"{len(g)} compatibility hook(s)",
                           "Placeholder definitions (like `always = no`) that the other mod is meant to "
                           "replace. This is how mods detect each other: working as intended.",
                           items=[line(o) for o in g]))
    # ---- on_action effect / trigger blocks
    seen = {}
    for f in facts:
        for name, (rel, inner, h) in f.on_actions.items():
            if inner & {"effect", "trigger"}:
                seen.setdefault(name, []).append((f, rel, inner & {"effect", "trigger"}, h))
    pairs, intended, oa_objs = {}, {}, {}
    for name, who in seen.items():
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                (fa, ra, ia, ha), (fb, rb, ib, hb) = who[x], who[y]
                if fa.key == fb.key or ra == rb or ha == hb:
                    continue
                na_, nb_ = ra.rsplit("/", 1)[1], rb.rsplit("/", 1)[1]
                win_file = max(na_, nb_)
                line = f"{name}: {', '.join(sorted(ia | ib))} in {na_} and {nb_} (the one in {win_file} runs)"
                pair = tuple(sorted((fa.key, fb.key)))
                oa_objs.setdefault(pair, []).append(("common/on_action", name))
                deliberate = re.search(r"disabl|compat|override|patch|replace", win_file, re.I) or \
                    fb.key in fa.builds_on or fa.key in fb.builds_on
                (intended if deliberate else pairs).setdefault(pair, []).append(line)
    for (ka, kb), lines in pairs.items():
        I.append(Issue("on_action", "high", [ka, kb], f"{len(lines)} on-action effect(s) overwritten",
                       "Both put an effect/trigger block into the same on-action. Those blocks don't merge: "
                       "only one runs (decided by file name), so part of one mod never happens.",
                       items=lines, fix="Load order can't fix this. " + FIND_TXT + ".",
                       objects=oa_objs.get((ka, kb), [])))
    for (ka, kb), lines in intended.items():
        I.append(Issue("integration", "low", [ka, kb], f"{len(lines)} on-action(s) replaced on purpose",
                       "One mod replaces the other's on-action block deliberately (its file is named as a "
                       "disabler/compat override, or it builds on the other mod).", items=lines))
    # ---- localisation keys
    loc_owner = {}
    for f in facts:
        for k, rel in f.loc.items():
            loc_owner.setdefault(k, []).append((f, rel))
    lp = {}
    for k, who in loc_owner.items():
        if len(who) < 2:
            continue
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                (fa, ra), (fb, rb) = who[x], who[y]
                if fa.key != fb.key and ra != rb and fa.loc_hash.get(k) != fb.loc_hash.get(k):
                    lp.setdefault(tuple(sorted((fa.key, fb.key))), []).append(k)
    for (ka, kb), keys in lp.items():
        I.append(Issue("loc_duplicate", "low", [ka, kb], f"{len(keys)} text(s) worded differently by both",
                       "Both define the same text keys, with different wording, outside a 'replace' folder: one "
                       "text is shown, the other ignored, and the game logs a duplicate-key error. Cosmetic.",
                       items=sorted(keys)[:300]))
    # ---- replace_path
    for f in facts:
        for rp in f.mod.replace_paths:
            for o in facts:
                if o is f:
                    continue
                if rp in o.mod.replace_paths and o.key > f.key:
                    I.append(Issue("replace_path", "high", [f.key, o.key], f"Both replace the game's {rp}/",
                                   "Both remove the game's own files in that folder and bring their own; they "
                                   "were made for different worlds.", fix="Usually only one of them belongs in a playset"))
    # ---- game settings (common/defines) changed by both, with different values: per setting, the file
    # whose name sorts later wins (whatever the load order)
    dv = {}
    for f in facts:
        for ck, (rel, v) in f.define_vals.items():
            dv.setdefault(ck, []).append((f, rel, v))
    dpairs = {}
    for (cat, key), who in dv.items():
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                (fa, ra, va), (fb, rb, vb) = who[x], who[y]
                if fa.key == fb.key or va == vb or ra == rb:
                    continue
                win = fa if ra.rsplit("/", 1)[1] > rb.rsplit("/", 1)[1] else fb
                dpairs.setdefault(tuple(sorted((fa.key, fb.key))), []).append(
                    (cat, key, fa, va, fb, vb, win))
    for (ka, kb), rows in dpairs.items():
        if _related(by[ka], by[kb], facts):
            I.append(Issue("integration", "info", [ka, kb], f"{len(rows)} game setting(s) set on purpose",
                           "One mod builds on (or patches) the other and sets these values deliberately.",
                           items=[f"{cat}.{key}:  {fa.name} = {va}  |  {fb.name} = {vb}  ->  {win.name}'s is used"
                                  for cat, key, fa, va, fb, vb, win in rows]))
            continue
        I.append(Issue("define_clash", "medium" if len(rows) >= 3 else "low", [ka, kb],
                       f"{len(rows)} game setting(s) changed by both",
                       "Both mods change the same values in common/defines (things like fertility, health or "
                       "AI behaviour). Each value comes from one file only: the one whose name sorts later, "
                       "not the mod loaded last.",
                       items=[f"{cat}.{key}:  {fa.name} = {va}  |  {fb.name} = {vb}  ->  {win.name}'s is used"
                              for cat, key, fa, va, fb, vb, win in rows],
                       fix=FIND_TXT + ". Or accept one mod's values", objects=[("defines", f"{c}.{k}")
                                                                                   for c, k, *_ in rows]))
    # ---- GUI templates / types defined by both in new files: the first file read wins (FIOS)
    gd = {}
    for f in facts:
        for n, (rel, kind) in f.gui_defs.items():
            gd.setdefault(n, []).append((f, rel, kind))
    gpairs = {}
    for n, who in gd.items():
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                (fa, ra, kd), (fb, rb, _) = who[x], who[y]
                if fa.key == fb.key or ra == rb:
                    continue
                pa, pb = fa.mod.paths.get(ra), fb.mod.paths.get(rb)
                if pa and pb and modscan.file_hash(pa) == modscan.file_hash(pb):
                    continue
                win = fa if ra.rsplit("/", 1)[1] < rb.rsplit("/", 1)[1] else fb
                gpairs.setdefault(tuple(sorted((fa.key, fb.key))), []).append((n, kd, fa, ra, fb, rb, win))
    for (ka, kb), rows in gpairs.items():
        if _related(by[ka], by[kb], facts):
            continue
        I.append(Issue("gui_type", "medium" if len(rows) >= 3 else "low", [ka, kb],
                       f"{len(rows)} interface piece(s) defined by both",
                       "Both define the same GUI templates or types (shared looks like a button style or a font). "
                       "For these the FIRST file read wins (by file name), so one mod's version is used "
                       "everywhere, including in the other mod's windows.",
                       items=[f"{kd} {n}:  {fa.name}: {ra.rsplit('/', 1)[1]}  |  {fb.name}: {rb.rsplit('/', 1)[1]}"
                              f"  ->  {win.name}'s is used" for n, kd, fa, ra, fb, rb, win in rows],
                       fix="Load order can't fix this. " + FIND_TXT + ".",
                       objects=[("gui", n) for n, *_ in rows]))
    # ---- a mod's copy of a game file leaves out objects another mod uses
    defined_anywhere = {}
    for f in facts:
        for (folder, key) in f.defines:
            defined_anywhere.setdefault(key, set()).add(f.key)
    for a in facts:
        if not a.removed:
            continue
        gone = {}
        for (folder, name), rel in a.removed.items():
            if a.key in defined_anywhere.get(name, ()):
                continue                              # moved to another of its files, not removed
            gone.setdefault(name, (folder, rel))
        if not gone:
            continue
        for b in facts:
            if b is a or _related(a, b, facts):
                continue
            used = sorted(n for n in gone if b.ref_files.get(n) and b.key not in defined_anywhere.get(n, ()))
            if not used:
                continue
            I.append(Issue("removed_used", "high" if len(used) >= 3 else "medium", [a.key, b.key],
                           f'"{a.name}" removes {len(used)} game object(s) "{b.name}" uses',
                           f'"{a.name}" replaces game files with copies that leave these objects out, and '
                           f'"{b.name}" refers to them. With both on, those references point at nothing.',
                           items=[f"{n}  [{gone[n][0]}]  left out of {gone[n][1]}" for n in used[:300]],
                           fix=f'Needs a compatch; or load "{b.name}"\'s own copy of the file after, if it has one',
                           objects=[(gone[n][0], n) for n in used]))
    I.sort(key=lambda i: (i.rank, i.kind))


PATCHABLE = {"file_clash", "gui_window", "object_override", "name_collision", "event_collision", "on_action",
             "define_clash", "gui_type", "removed_used", "loc_duplicate"}


def find_patches(an, facts):
    """Installed mods that patch a pair of conflicting mods together: {(a, b): [(key, sure, why)]}.
    A compatch declares both as dependencies, or uses things only each of them defines, or is named as a
    patch for both, or (named after one of them) brings its own copy of the very files / objects they
    fight over."""
    pairs = {tuple(sorted(i.mods)) for i in an.issues if len(i.mods) == 2 and i.kind in PATCHABLE}
    if not pairs:
        return {}
    by = an.facts
    obj_owner = {}
    for f in facts:
        for (folder, key) in f.defines:
            obj_owner.setdefault((folder, key), set()).add(f.key)
    out = {}
    for ka, kb in pairs:
        a, b = by[ka], by[kb]
        clash_files = {c.rel for c in an.conflicts.get((ka, kb), []) if c.kind == "clash"}
        clash_objs = {(o[1], o[0]) for o in an.objects.get((ka, kb), [])}
        found = []
        for c in facts:
            if c.key in (ka, kb):
                continue
            deps = b_dep_keys(c, facts)
            why, sure = "", ""
            if ka in deps and kb in deps:
                why, sure = "declares it needs both", "certain"
            elif ka in c.builds_on and kb in c.builds_on:
                why, sure = "uses things only each of them defines", "certain"
            else:
                named = [x for x in (a, b) if mentions(clean_title(c.name), x)]
                role = c.role.role.id if c.role else ""
                covers = bool(clash_files & c.files) or any(c.key in obj_owner.get(o, ()) for o in clash_objs)
                if len(named) == 2 and (role in ("compatch", "submod") or covers or _PATCH_WORD.search(c.name)):
                    why, sure = "named as a patch for both", "likely"
                elif named and covers and (role == "compatch" or _PATCH_WORD.search(c.name)):
                    why, sure = "brings its own copy of what they fight over", "likely"
            if why:
                found.append((c.key, sure, why))
        if found:
            found.sort(key=lambda x: x[1] != "certain")
            out[(ka, kb)] = found
    return out


_PATCH_WORD = re.compile(r"\b(com-?patch|compat(ibility)?|patch|bridge|integration|merge[dr]?)\b", re.I)


def _related(a, b, facts):
    """One mod builds on or depends on the other: what they do to each other is on purpose."""
    return (b.key in a.builds_on or a.key in b.builds_on or b.key in b_dep_keys(a, facts)
            or a.key in b_dep_keys(b, facts))


def b_dep_keys(f, facts):
    out = set()
    for dep in f.mod.dependencies:
        for o in facts:
            if o is not f and (clean_title(dep).lower() == clean_title(o.name).lower()
                               or similarity(dep, o.name) >= 0.85):
                out.add(o.key)
    return out


def _is_hook(f, folder, fname, key):
    """A definition meant to be replaced: aaa_/zzz_ compat files or trivial `always = yes/no` bodies."""
    low = fname.lower()
    if "compat" in low or low.startswith(("aaa", "zzz", "00_compat", "zz_compat")):
        p = f.mod.paths.get(f"{folder}/{fname}".lower())
        if p:
            text, _ = read_cached(p)
            for k, body, _ in SC.blocks(text):
                if k == key:
                    return SC.is_trivial(body)
    return False


def _short_files(cs):
    names = [c.rel.rsplit("/", 1)[1] for c in cs[:2]]
    return ", ".join(names) + (f" and {len(cs) - 2} more" if len(cs) > 2 else "")


def _clash_line(c, by):
    a, b = by[c.a].name, by[c.b].name
    extra = ""
    if c.broken_a:
        extra += f"  ({a} also uses {', '.join(c.broken_a[:3])} from it)"
    if c.broken_b:
        extra += f"  ({b} also uses {', '.join(c.broken_b[:3])} from it)"
    return f"{c.rel}   {a}: {c.lost_a} changed lines  |  {b}: {c.lost_b}{extra}"


def playset_issues(an, enabled, game_version=""):
    """Problems of one playset: pair problems between its enabled mods, plus what the set itself lacks
    (declared dependencies, mods it builds on, requirements on Workshop pages)."""
    keys = [k for k in enabled if k in an.facts]
    on = set(keys)
    by = an.facts
    out = []
    patches = getattr(an, "patches", {}) or {}
    for i in an.issues:
        if not all(k in on for k in i.mods):
            continue
        cands = patches.get(tuple(sorted(i.mods))) if i.kind in PATCHABLE and len(i.mods) == 2 else None
        if cands:
            active = next((c for c in cands if c[0] in on), None)
            i = i.copy()
            if active:
                i.patched_by = active
                i.severity, i.remedy = "info", "patched"
                i.fix = (f'Solved by "{by[active[0]].name}" ({active[2]}), as long as it loads after both '
                         "(Auto-sort makes sure)")
            else:
                i.patch_off = cands[0]
                i.fix = (f'Turn on "{by[cands[0][0]].name}": it\'s installed and {cands[0][2]}. '
                         + (i.fix or ""))
        out.append(i)
    installed = list(by.values())
    for k in keys:
        f = by[k]
        for dep in f.mod.dependencies:
            t = next((o for o in installed if o is not f and (clean_title(o.name).lower() == clean_title(dep).lower()
                                                              or similarity(dep, o.name) >= 0.85)), None)
            if t is not None and t.key in on:
                continue
            out.append(Issue("missing_dependency", "critical", [k], f'"{f.name}" needs "{dep}"',
                             (f'"{t.name}" is installed but not turned on in this playset.' if t else
                              f'"{dep}" isn\'t installed.') + " The mod declares it can't work without it.",
                             fix="Turn it on" if t else "Download it (Catch tab)"))
        for a, n in f.builds_on.items():
            if a not in on and n >= 8:
                ex = ", ".join(f.uses_examples.get(a, [])[:3])
                out.append(Issue("missing_dependency", "high", [k], f'"{f.name}" uses "{by[a].name}", which is off',
                                 f"It uses {n} things only \"{by[a].name}\" defines (e.g. {ex}). Without it those "
                                 "parts break or log errors.", fix=f'Turn on "{by[a].name}"'))
        for kind, o, snip in f.hints:
            if kind == "requires" and o.key not in on:
                out.append(Issue("missing_dependency", "high", [k], f'"{f.name}" asks for "{o.name}"',
                                 f'Its Workshop page says: "{snip}"', fix=f'Turn on "{o.name}"'))
    if game_version:
        import versions as V
        for k in keys:
            f = by[k]
            if V.compatible(f.mod.supported, game_version) is False:
                out.append(Issue("version", "low", [k], f'"{f.name}" was made for game {f.mod.supported}',
                                 f"You play {V.clean(game_version)}. It usually still loads, but things it changes "
                                 "may have moved in the game since."))
    out.sort(key=lambda i: (i.rank, i.kind))
    return out


def summary(issues):
    out = {s: 0 for s in SEVERITIES}
    for i in issues:
        out[i.severity] += 1
    return out
