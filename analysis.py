"""
Deep analysis of a set of mods: what each mod is, what it defines and uses, how mods relate to each other,
and every way two mods can get in each other's way, judged by the game's own rules (gamedb.py).

How Paradox games (Clausewitz / Jomini, CK3 in particular) combine mods:
  * same relative file path in two mods -> the mod loaded LATER replaces the whole file
    (the only thing load order decides);
  * the same object (trait, effect, decision ...) defined in files with DIFFERENT names -> decided by
    the file names (LIOS: the alphabetically last file wins; FIOS for GUI types and templates),
    whatever the mod order. Modders use aaa_/zzz_ names on purpose: placeholders that lose to the real
    thing, and overrides that win over it;
  * events can't be overridden one at a time: two mods defining the same event id = duplicate;
  * on_actions merge their `events` / `on_actions` lists, but `effect` / `trigger` blocks replace
    each other (and log errors);
  * localisation keys defined twice are an error unless the file sits in a `replace` folder;
  * replace_path drops the game's own files in a folder (total conversions).

The analysis reads every text file of every mod once: normalised lines, what it defines (top level and
nested: titles, faiths), its typed references (which trait, event, effect, faith... it uses or only
checks for), localisation keys and on_action blocks. It compares with the game's own files (when the
install folder is known), so "changed" means changed compared to the game, and an unchanged copy of a
game object isn't mistaken for a change.

Then it works out how mods relate (one needs another, one only adds extras when another is there, one
pack already contains another mod, two mods by one author share code, a compatch or submod patches
another on purpose) before judging conflicts, so intended overlaps aren't reported as problems and real
ones are graded by what's at stake: the kind of object, how much each mod changed, and whether anything
else relies on it.
"""
import array
import collections
import hashlib
import json
import os
import pickle
import re
import threading
import time
import weakref
import zlib

import gamedb as GD
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
KNOWLEDGE_VERSION = 5


def is_text(rel):
    return os.path.splitext(rel)[1].lower() in TEXT_EXT


def stable_hash(s):
    """The same number in every run (Python's hash() of a string changes between runs)."""
    return zlib.crc32(s.encode("utf-8", "replace"))


object_folder = GD.object_folder

# ================================================================== reading files (cached)
_cache, _lock = collections.OrderedDict(), threading.Lock()
CACHE_FILES = 1500


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
            _cache.move_to_end(key)
    if hit:
        return hit
    try:
        text = read_text(path)
    except OSError:
        return "", frozenset()
    res = (text, _lines_of(text))
    if keep:
        with _lock:
            _cache[key] = res
            while len(_cache) > CACHE_FILES:
                _cache.popitem(last=False)
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
    """The game's own files: path lookup, which names each folder defines, and (learned once per game
    version, cached on disk) how its scripts refer to things, its objects' contents and what it uses."""

    def __init__(self, game_dir, cache_dir=""):
        self.game_dir = game_dir
        self.roots = content_roots(game_dir)
        self._index = None
        self._defs = {}            # folder -> set of names
        self._names = {}           # folder -> top level and nested names (memo)
        self._lock = threading.Lock()
        self.cache_path = ""
        self.model = GD.RefModel()
        self.nested = {}           # folder -> set of names defined below the top level (titles, faiths)
        self.hashes = {}           # folder -> {name: hash of its normalised body}
        self.used = {}             # name -> how many times the game's own scripts USE it (typed)
        self.oa_effect = {}        # on_action name -> file name, for game on_actions with effect / trigger
        self.containers = {}       # folder -> top-level keys the game defines in several files (they merge:
                                   # `accessory_genes = { ... }`, coat of arms `template = { ... }`)
        self._renames = None
        self.knowledge_ready = False
        self.stamp = ""
        if self.roots:
            ver = ""
            try:
                with open(os.path.join(game_dir, "launcher", "launcher-settings.json"), encoding="utf-8-sig") as f:
                    ver = json.load(f).get("rawVersion") or ""
            except Exception:
                pass
            self.stamp = re.sub(r"[^0-9A-Za-z]+", "_", ver or str(int(os.path.getmtime(self.roots[0]))))
        if cache_dir and self.roots:
            self.cache_path = os.path.join(cache_dir, f"vanilla_names_{self.stamp}.json")
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    self._defs = {k: set(v) for k, v in json.load(f).items()}
            except Exception:
                self._defs = {}
        self.cache_dir = cache_dir

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
        """Names the game itself defines in a folder (common/traits, events ...), top level and nested."""
        if not self.roots:
            return set()
        hit = self._names.get(folder)
        if hit is not None:
            return hit
        if folder not in self._defs:
            if self._index is None:
                self.path("")
            out = set()
            pre = folder + "/"
            for rel, full in self._index.items():
                if rel.startswith(pre) and rel.endswith(".txt") and object_folder(rel) == folder:
                    try:
                        out.update(SC.defined_keys(read_text(full)))
                    except OSError:
                        pass
            self._defs[folder] = out
        res = self._defs[folder] | self.nested.get(folder, set())
        self._names[folder] = res
        return res

    def all_names(self):
        """Every name the game defines anywhere in common/ and events/ (for telling a mod's own new names
        from the game's)."""
        if not self.roots:
            return set()
        if getattr(self, "_all", None) is None:
            if self._index is None:
                self.path("")
            folders = {object_folder(r) for r in self._index if r.endswith(".txt") and r.startswith(("common/", "events/"))}
            new = [fo for fo in folders if fo not in self._defs]
            folders |= set(self._defs)
            out = set()
            for fo in folders:
                out |= self.names(fo)
            for v in self.nested.values():
                out |= v
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

    def obj_hash(self, folder, name):
        return self.hashes.get(folder, {}).get(name)

    def renames(self):
        if self._renames is None:
            self._renames = GD.renames(self.game_dir) if self.roots else {}
        return self._renames

    def save(self):
        if self.cache_path:
            try:
                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump({k: sorted(v) for k, v in self._defs.items()}, f)
            except Exception:
                pass

    # ---------------------------------------------------------------- learned once per game version
    def knowledge(self, say=None):
        """Read every script of the game once: what it defines (also nested), each object's content,
        how its scripts refer to things (the reference model) and what it uses. Cached on disk."""
        if self.knowledge_ready or not self.roots:
            return
        path = os.path.join(self.cache_dir, f"game_knowledge_{self.stamp}.json") if self.cache_dir else ""
        if path:
            model, d = GD.load_model(path)
            if model is not None and d.get("v") == KNOWLEDGE_VERSION:
                self.model = model
                self.nested = {k: set(v) for k, v in d.get("nested", {}).items()}
                self.hashes = d.get("hashes", {})
                self.used = d.get("used", {})
                self.oa_effect = d.get("oa_effect", {})
                self.containers = {k: set(v) for k, v in d.get("containers", {}).items()}
                for k, v in d.get("defs", {}).items():
                    self._defs.setdefault(k, set(v))
                self.knowledge_ready = True
                self._names, self._all = {}, None
                return
        if say:
            say("Learning the game's own scripts (first time for this game version)", 0.03)
        if self._index is None:
            self.path("")
        texts, defs_by_name = {}, {}
        defs, nested, hashes, oa, files_of = {}, {}, {}, {}, {}
        for rel, full in self._index.items():
            if not (rel.endswith(".txt") and rel.startswith(("common/", "events/", "history/"))):
                continue
            try:
                raw = read_text(full)
            except OSError:
                continue
            text = SC.strip_comments(raw)
            texts[rel] = text
            if rel.startswith("history/"):
                continue
            fo = object_folder(rel)
            fname = rel.rsplit("/", 1)[1]
            hs = hashes.setdefault(fo, {})
            dset = defs.setdefault(fo, set())
            fk = files_of.setdefault(fo, {})
            for key, body, _ in SC.blocks(text):
                if key.startswith("@") or key in ("namespace",):
                    continue
                dset.add(key)
                fk.setdefault(key, set()).add(fname)
                hs.setdefault(key, stable_hash(SC.norm(body)))
                defs_by_name.setdefault(key, set()).add(fo)
                if fo.startswith("common/on_action") and body and SC.inner_keys(body) & {"effect", "trigger"}:
                    oa.setdefault(key, fname)
            for k, nf in GD.nested_defs(fo, text).items():
                nested.setdefault(nf, set()).add(k)
                defs_by_name.setdefault(k, set()).add(nf)
        if say:
            say("Learning how the game's scripts refer to things", 0.08)
        model = GD.learn_refs(texts, defs_by_name)
        used = {}
        for rel, text in texts.items():
            for (fo, name), (u, _c) in model.refs(text).items():
                if u:
                    used[name] = used.get(name, 0) + u
        containers = {fo: {k for k, fs in d.items() if len(fs) >= 2} for fo, d in files_of.items()}
        containers = {fo: v for fo, v in containers.items() if v and not fo.startswith("events")}
        self.model, self.nested, self.hashes, self.used, self.oa_effect = model, nested, hashes, used, oa
        self.containers = containers
        for fo, names in defs.items():
            self._defs[fo] = names
        self.knowledge_ready = True
        self._names, self._all = {}, None
        if path:
            GD.save_model(path, model, {"v": KNOWLEDGE_VERSION, "nested": {k: sorted(v) for k, v in nested.items()},
                                        "hashes": hashes, "used": used, "oa_effect": oa,
                                        "containers": {k: sorted(v) for k, v in containers.items()},
                                        "defs": {k: sorted(v) for k, v in defs.items()}})
        self.save()


_vanilla = {}


def vanilla_for(game_dir, cache_dir=""):
    key = os.path.normcase(os.path.abspath(game_dir)) if game_dir else ""
    if key not in _vanilla:
        _vanilla[key] = Vanilla(game_dir, cache_dir)
    return _vanilla[key]


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
# an author saying two mods don't work together: specific phrasings only ("breaks", "conflicts with
# another mod, please report it" and the like are not statements about a named mod)
_INCOMPAT = re.compile(r"\b(not\s+compatible\s+with|incompatible\s+with|isn'?t\s+compatible\s+with|"
                       r"(?:does\s*n[o']t|won'?t|will\s+not|can'?t|cannot)\s+work\s+(?:with|alongside|together\s+with)|"
                       r"(?:is|are)\s+(?:known\s+to\s+be\s+)?(?:in)?compatible\s+only\s+without|"
                       r"do\s+not\s+use\s+(?:it\s+|this(?:\s+mod)?\s+)?(?:with|alongside|together\s+with)|"
                       r"don'?t\s+use\s+(?:it\s+|this(?:\s+mod)?\s+)?(?:with|alongside|together\s+with)|"
                       r"(?:is\s+)?not\s+meant\s+to\s+be\s+used\s+with|"
                       r"conflicts?\s+with)\s+(.{2,120})", re.I)
_FEEDBACK = re.compile(r"\b(report|let me know|comment|tell me|feedback|if you (?:notice|find|see|encounter)|"
                       r"previous version|older version|old save|this version|bug)\b", re.I)
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
# short names that are ordinary words: never an alias of a mod
_COMMON_WORDS = {"MOD", "MODS", "THE", "AND", "FOR", "ALL", "NEW", "OLD", "BIG", "ART", "WAR", "MAP", "LOT", "ONE",
                 "TWO", "OUR", "YOU", "ANY", "CAN", "MAY", "USE", "NOT", "ARE", "WAS", "HAS", "GET", "SET",
                 "ADD", "FIX", "BUG", "API", "DLC", "GUI", "AI", "UI", "CK", "MP", "SP", "OK", "FAQ", "TBD",
                 "WIP", "LOL", "OMG", "PDX", "MOM", "DAD", "SON", "KING", "LORD", "GOD", "SEX", "LOVE"}
_TOKEN_STOP = {"the", "of", "a", "an", "and", "for", "in", "on", "mod", "mods", "ck3", "ck", "1", "2", "3",
               "updated", "update", "fixed", "fix", "version", "edition", "community", "plus", "expanded",
               "more", "better", "new", "with", "by", "to"}


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
    """Short names a mod goes by (DOL, RICE, VIET...): written in capitals, at least three letters, and
    never an ordinary word ("Music of Deliverance" is not "MOD")."""
    out = set()
    words = [w for w in re.split(r"[^0-9A-Za-z]+", clean_title(name)) if w]
    m = re.search(r"\(([A-Z][A-Z0-9]{2,6})\)", name or "")
    if m:
        out.add(m.group(1))                                   # "Daughters of Lust (DOL)"
    if 3 <= len(words) <= 5:
        acro = "".join(w[0] for w in words).upper()
        desc = clean_description(description or "")
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(acro) + r"(?![A-Za-z0-9])", desc):
            out.add(acro)                                     # only if the author uses it himself
    counts = {}
    for w in re.findall(r"\b[A-Z][A-Za-z0-9]{2,5}\b", clean_description(description or "")):
        counts[w] = counts.get(w, 0) + 1
    for w, n in counts.items():
        if n >= 3 and w not in _STOPWORDS and _abbreviates(w, name):
            out.add(w)
    return {a for a in out if 3 <= len(a) <= 6 and a.upper() not in _COMMON_WORDS}


_name_memo = weakref.WeakKeyDictionary()
_span_memo = {}


def _name_parts(other):
    """A mod's name, ready for matching (worked out once per mod: it's asked about hundreds of times)."""
    sig = (other.name, tuple(sorted(other.aliases)))
    hit = _name_memo.get(other)
    if hit is not None and hit[0] == sig:
        return hit[1]
    ot = [t for t in tokens(other.name) if t not in _TOKEN_STOP]
    one = None
    if len(ot) == 1 and len(ot[0]) >= 6:
        one = re.compile(r"(?<![A-Za-z0-9])" + re.escape(ot[0].capitalize()) + r"(?![A-Za-z0-9])")
    alias = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(a) for a in sorted(other.aliases)) +
                       r")(?![A-Za-z0-9])") if other.aliases else None
    val = (set(ot), len(ot), one, alias)
    _name_memo[other] = (sig, val)
    return val


def mentions(span, other):
    """Does this text name `other` (ModFacts)? By Workshop link, full name or short name (exact case)."""
    sp = _span_memo.get(span)
    if sp is None:
        plain = re.sub(r"<<[^>]*>>", " ", span)
        sp = (set(re.findall(r"id=(\d+)", span)), plain, set(tokens(plain)))
        if len(_span_memo) > 20000:
            _span_memo.clear()
        _span_memo[span] = sp
    wids, plain, st = sp
    if other.wid and other.wid in wids:
        return True
    ot, n, one, alias = _name_parts(other)
    if n >= 2 and ot <= st:
        return True
    # one-word names must be written as a name (capitalised) and not be an everyday word
    if one is not None and one.search(plain):
        return True
    if alias is not None and alias.search(plain):
        return True
    return False


def parse_hints(me, description, others):
    """[(kind, other or None, snippet)] with kind in after/before/top/bottom/after_tc/before_tc/
    incompatible/requires/compatible."""
    out = []
    text = clean_description(description)
    for s in _sentences(text):
        snippet = re.sub(r"\s*<<[^>]*>>", "", s)[:170]
        if not _FEEDBACK.search(s):
            for m in _INCOMPAT.finditer(s):
                if _NEG.search(s[:m.start()][-14:]) and not m.group(1).lower().startswith(("not", "is not", "isn")):
                    continue
                for o in others:
                    if o is not me and mentions(m.group(2), o):
                        out.append(("incompatible", o, snippet))
        for m in _REQUIRES.finditer(s):
            if _NEG.search(s[:m.start()][-14:]):
                continue                                       # "doesn't require X"
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
        if h[0] == "incompatible" and any(x[0] in ("compatible", "requires") and x[1] is h[1] for x in out):
            continue                 # "compatible with X" and "conflicts with X" in one page: not a clear no
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
        self.light = self.heavy = 0  # of those: lightly / heavily changed
        self.loc_lang = ""           # the language its texts were read in (English when it has it)
        # for each game file it replaces: (lines it adds, game lines it drops) as fingerprints, and its
        # objects' fingerprints, so two mods' copies are compared later without opening them again
        self.vdiff, self.vobjs = {}, {}
        self.light_override_share = 0.0
        self.defines = {}            # (folder, name) -> file name   (common/* objects and event ids)
        self.def_hash = {}           # (folder, name) -> hash of its definition, to spot identical copies
        self.def_size = {}           # (folder, name) -> lines in its definition
        self.provides = set()        # every name it defines, also nested ones (titles, faiths)
        self.loc = {}                # localisation key -> rel (outside replace folders)
        self.loc_hash = {}           # localisation key -> hash of its text
        self.loc_replace = set()
        self.on_actions = {}         # on_action name -> (rel, set of inner keys, hash of its body)
        self.ref_files = {}          # identifier -> in how many of its script files it appears
        self.refs = {}               # (folder, name) -> [uses, checks]: its typed references
        self.calls = {}              # name -> times it's called as `name = yes / { }` (scripted effects...)
        self.namespaces = set()
        self.aliases = set()
        self.hints = []
        self.builds_on = {}          # other key -> how many of the other mod's own names it really uses
        self.optional = {}           # other key -> names of the other mod it only checks for / guards
        self.used_by = {}
        self.uses_examples = {}      # other key -> a few names, for explanations
        self.role = None             # roles.RoleResult
        self.description = ""
        self.ws_tags = []            # categories ticked on its Workshop page
        self.define_vals = {}        # (category, KEY) -> (rel, value): common/defines it changes
        self.gui_defs = {}           # GUI template / type name -> (rel, "template" | "type"), new files only
        self.removed = {}            # (folder, name) -> rel: game objects its copy of a game file leaves out
        self.oa_overwrites = {}      # game on_action -> rel: it puts an effect/trigger block into one
        self.prefixes = {}           # name prefix -> how many of its new names use it
        self.bundles = {}            # other key -> share of the other mod's content this mod also ships

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
    that solves it (set per playset). score: how much is at stake (for sorting within a severity)."""

    def __init__(self, kind, severity, mods, title, detail, items=(), fix="", order=False, effect="",
                 confidence="", remedy="", objects=(), score=0.0):
        self.kind, self.severity, self.mods = kind, severity, tuple(mods)
        self.title, self.detail, self.items, self.fix, self.order = title, detail, list(items), fix, order
        meta = DIAG.get(kind, ("", "likely", "compatch"))
        self.effect = effect or meta[0]
        self.confidence = confidence or meta[1]
        self.remedy = remedy or ("order" if order else meta[2])
        self.objects = list(objects)
        self.patched_by = None
        self.patch_off = None            # an installed compatch for it that's turned off
        self.score = score

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
    "incompatible": ("Errors, broken events or a game that won't start, as its author warns.", "likely", "choose"),
    "duplicate_mod": ("Two copies fight over every file: half of each version is used.", "certain", "choose"),
    "bundled": ("The same content twice, in two versions: the pack and the separate mod overwrite each other "
                "file by file, so you get a mix of both versions.", "likely", "choose"),
    "missing_dependency": ("Parts of the mod do nothing or show errors (missing names in events and menus).",
                           "certain", "enable"),
    "two_conversions": ("A broken map: provinces, titles and history from two different worlds.", "certain", "choose"),
    "file_clash": ("Part of the losing mod's changes are simply missing in game.", "certain", "order"),
    "gui_window": ("The window shows only one mod's version: the other mod's buttons or panels are gone.",
                   "certain", "order"),
    "object_override": ("One mod's change to these game objects is ignored.", "certain", "compatch"),
    "reverted": ("One mod's unchanged copy of a game object wins and quietly undoes the other mod's change.",
                 "certain", "compatch"),
    "name_collision": ("One mod's new object behaves like the other's: odd traits, decisions or effects.",
                       "likely", "compatch"),
    "event_collision": ("Some events of one mod never show up, or show the other mod's text; the error log "
                        "fills up.", "certain", "compatch"),
    "on_action": ("Something one mod does on a game moment (birth, death, yearly...) never happens.",
                  "certain", "compatch"),
    "vanilla_on_action": ("Part of what the game itself does at that moment no longer happens.", "certain", "author"),
    "loc_duplicate": ("A few texts show one mod's wording instead of the other's.", "certain", "none"),
    "replace_path": ("Two different worlds: things missing or doubled.", "certain", "choose"),
    "removed_used": ("The other mod's events, decisions or effects that rely on them fail, and the error log "
                     "fills up.", "likely", "compatch"),
    "missing_refs": ("Parts of the mod fail: things it adds, fires or calls don't exist in this game version "
                     "(or in your other mods).", "likely", "update"),
    "define_clash": ("The game uses one mod's value for these settings; the other's change has no effect.",
                     "certain", "compatch"),
    "gui_type": ("Buttons, fonts or panels look like one mod's version everywhere.", "likely", "compatch"),
    "version": ("Usually nothing; sometimes small errors where the game changed since.", "possible", "none"),
    "merged": ("Nothing, as long as the merged copy loads last.", "certain", "order"),
    "identical": ("Nothing: both bring the same content.", "certain", "none"),
    "hook": ("Nothing: this is how the mods detect each other.", "certain", "none"),
    "integration": ("Nothing unexpected: one mod adjusts the other on purpose.", "likely", "none"),
    "shared_code": ("Usually nothing: both include the same piece of code; the newer copy is used for both.",
                    "likely", "none"),
    "optional": ("Nothing missing: it only adds extras when the other mod is on.", "likely", "none"),
}
REMEDY_LABEL = {"order": "Load order decides", "compatch": "Needs a compatch", "choose": "Keep only one",
                "enable": "Turn the missing mod on", "none": "Harmless", "patched": "Solved by a compatch",
                "update": "Needs an update", "author": "Up to its author"}
CONFIDENCE_LABEL = {"certain": "Certain", "likely": "Likely", "possible": "Possible"}


ISSUE_KINDS = {
    "incompatible": "Don't work together",
    "duplicate_mod": "Same mod twice",
    "bundled": "A pack already contains the other mod",
    "missing_dependency": "Missing a mod it needs",
    "two_conversions": "Two total conversions / map mods",
    "file_clash": "Same file, different content",
    "gui_window": "Both replace the same window",
    "object_override": "Same game object changed by both",
    "reverted": "An unchanged copy undoes the other's change",
    "name_collision": "Same new name used by both",
    "event_collision": "Duplicate event IDs",
    "on_action": "On-action effects overwritten",
    "vanilla_on_action": "Replaces the game's own on-action effect",
    "loc_duplicate": "Same text key in both",
    "replace_path": "Removes game files another mod needs",
    "version": "Made for another game version",
    "merged": "Shared files already merged",
    "identical": "Identical shared files",
    "hook": "Compatibility hooks",
    "integration": "One mod adjusts the other",
    "shared_code": "Same shared code in both",
    "optional": "Extras when both are on",
    "removed_used": "Removes game objects the other mod uses",
    "missing_refs": "Uses things that don't exist",
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
        self.owners = {}             # name prefix -> key of the mod it belongs to
        self.renamed = {}            # old game name -> new name (the game's rename tables)
        self.missing = {}            # mod key -> {(folder, name): uses} it uses that nobody defines


# ================================================================== the analysis
def _cover_known(add_x, rem_x, add_y, rem_y):
    """_coverage from what each copy adds to / drops from the game's file (the same numbers)."""
    total = len(add_x) + len(rem_x)
    if not total:
        return 1.0, 0
    kept = len(add_x & add_y) + len(rem_x & rem_y)
    return kept / total, total - kept


def _coverage(x_lines, y_lines, van_lines):
    added = x_lines - van_lines if van_lines else x_lines
    removed = van_lines - x_lines if van_lines else frozenset()
    total = len(added) + len(removed)
    if not total:
        return 1.0, 0
    kept = len(added & y_lines) + len(removed - y_lines)
    return kept / total, total - kept


def analyze(mods, game_dir="", workshop=None, workshop_ids=None, stop=None, progress=None, cache_dir="",
            game_version="", store=None, workers=None):
    """mods: the mods to check together (modscan.ModInfo): a playset's mods (plus compatches and mods they
    need that are off). Pair problems are found for all of them; a playset then only looks at the pairs
    it contains (playset_issues). store: a FactStore that remembers what each mod defines and uses, so
    only new or changed mods are read. workers: processes for reading (None: decided by the machine).
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

    # ---- 0. the game itself (learned once per game version)
    if van.roots:
        van.knowledge(say)
        an.renamed = van.renames()
    # ---- 1. read every mod (remembered ones come from the store; the rest are read side by side)
    parts = read_mods(mods, van, store=store, workers=workers, stop=stop,
                      progress=lambda txt, p: say(txt, 0.05 + 0.6 * p))
    if stop and stop.is_set():
        return an
    for f in facts:
        part = parts.get(f.key)
        if part is not None:
            _apply_part(f, part)
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
    vanilla_all = van.all_names() if van.roots else set()
    for f in facts:
        for (folder, key) in f.defines:
            if key not in vanilla_all:
                p = GD.name_prefix(key)
                if p:
                    f.prefixes[p] = f.prefixes.get(p, 0) + 1
    # ---- 3. names, descriptions, how mods relate, roles
    for f in facts:
        d = workshop.get(f.wid, "")
        f.description = d.get("text", "") if isinstance(d, dict) else (d or "")
        f.ws_tags = list(d.get("tags", [])) if isinstance(d, dict) else []
        f.aliases = self_aliases(f.name, f.description)
    for f in facts:
        if f.description:
            f.hints = parse_hints(f, f.description, facts)
    say("Working out how mods relate to each other", 0.62)
    an.owners = _owners(facts)
    _builds_on(facts, van, an.owners)
    _bundles(facts)
    for f in facts:
        f.role = R.classify(f, facts, mentions)
    # ---- 4. shared files
    say("Comparing shared files", 0.72)
    owners = {}
    for f in facts:
        for rel in f.files:
            owners.setdefault(rel, []).append(f)
    for rel in sorted(owners):
        who = owners[rel]
        if len(who) < 2:
            continue
        vp = van.path(rel)
        # the game's copy is only opened if some mod's copy wasn't compared with it while reading
        need = vp and is_text(rel) and not all(rel in getattr(x, "vdiff", {}) for x in who)
        vlines = text_lines(vp) if need else frozenset()
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                a, b = who[x], who[y]
                an.conflicts.setdefault(tuple(sorted((a.key, b.key))), []).append(_compare(rel, a, b, vlines, vp))
    # ---- 5. everything else that can go wrong
    say("Looking for conflicts", 0.86)
    _issues(an, facts, van)
    say("Checking what each mod uses", 0.93)
    _single_mod_issues(an, facts, van)
    say("Looking for compatches you have", 0.96)
    an.patches = find_patches(an, facts)
    an.issues.sort(key=lambda i: (i.rank, -i.score, i.kind, i.title, tuple(sorted(i.mods))))
    an.seconds = time.time() - t0
    say("Done", 1.0)
    return an


# ================================================================== reading one mod
# What reading a mod produces. It depends only on the mod's own files and the game version, so it's kept
# on disk per mod (FactStore) and the next check reads only mods that are new or changed.
READ_FIELDS = ("units", "overrides", "light", "heavy", "defines", "def_hash", "def_size", "provides", "loc",
               "loc_hash", "loc_replace", "loc_lang", "on_actions", "ref_files", "refs", "calls", "namespaces",
               "define_vals", "gui_defs", "removed", "oa_overwrites", "vdiff", "vobjs")
FACTS_VERSION = 1
CHUNK_BYTES = 6_000_000          # a big mod is read in pieces of about this much text, side by side
_MEANINGFUL = re.compile(r"(?m)^[ \t]*[^\s#]")
_LANG_DIR = re.compile(r"^locali[sz]ation/(?:replace/)?([a-z_]+)/")
_LANG_FILE = re.compile(r"_l_([a-z_]+)\.yml$")
BYTES_PER_LINE = 38              # a file that isn't read: its lines estimated from its size


class _Part:
    """What one piece of a mod's files says (merged in order into the mod's ModFacts)."""

    def __init__(self):
        self.units, self.overrides, self.light, self.heavy = {}, 0, 0, 0
        self.defines, self.def_hash, self.def_size, self.provides = {}, {}, {}, set()
        self.loc, self.loc_hash, self.loc_replace, self.loc_lang = {}, {}, set(), ""
        self.on_actions, self.ref_files, self.refs, self.calls = {}, {}, {}, {}
        self.namespaces, self.define_vals, self.gui_defs, self.removed, self.oa_overwrites = set(), {}, {}, {}, {}
        self.vdiff, self.vobjs = {}, {}


def _english_first(rel):
    return ("/english/" not in rel and "_l_english" not in rel, rel)


def loc_language(rel):
    m = _LANG_DIR.match(rel) or _LANG_FILE.search(rel)
    return m.group(1) if m else ""


def _plan(m, van):
    """Which of a mod's files have to be read, and what the others count for (without opening them).
    Read: script files (common, events, history, gui...), the game files it replaces (to know what it
    changed), and its texts in one language (English when it has it: a text key clashes only within one
    language). Not read: pictures, sounds, models and other files nothing looks inside; their size
    stands in for how much they change."""
    files = sorted(m.files, key=_english_first)
    langs = {loc_language(r) for r in files if r.endswith(".yml")} - {""}
    lang = "english" if "english" in langs else (min(langs) if langs else "")
    part = _Part()
    part.loc_lang = lang
    read = []
    sizes = getattr(m, "sizes", {}) or {}
    for rel in files:
        p = m.paths.get(rel)
        vp = van.path(rel)
        if vp:
            part.overrides += 1
        if not p:
            continue
        size = sizes.get(rel)
        if size is None:
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
        ext = os.path.splitext(rel)[1]
        if not is_text(rel):
            part.units[rel] = 0 if vp and modscan.same_file(p, vp, size) else BIN_UNITS
            continue
        if not vp:
            if ext == ".yml":
                l_ = loc_language(rel)
                if l_ and l_ != lang:                  # another language's texts: same keys, not compared
                    part.units[rel] = max(1, size // BYTES_PER_LINE)
                    continue
            elif ext not in (".txt", ".gui"):          # assets, interface sprites, shaders, csv...
                part.units[rel] = max(1, size // BYTES_PER_LINE)
                continue
        read.append((rel, p, vp, size))
    return part, read


def _read_into(f, items, van):
    """Read files [(rel, path, game path, size)] into f (a ModFacts or a _Part)."""
    model = van.model if van.knowledge_ready else None
    for rel, p, vp, _size in items:
        ext = os.path.splitext(rel)[1]
        if vp:
            text, lines = read_cached(p, keep=False)
            vlines = text_lines(vp)
            changed = lines - vlines
            f.units[rel] = len(changed)
            f.vdiff[rel] = (frozenset(map(_h64, changed)), frozenset(map(_h64, vlines - lines)))
            if _object_file(rel):
                f.vobjs[rel] = {k: stable_hash(b) for k, b in SC.object_bodies(text).items()}
            if lines:
                if len(changed) <= 0.15 * len(lines):
                    f.light += 1
                else:
                    f.heavy += 1
        else:                                  # a new file: every line is the mod's own (counted roughly)
            try:
                text = read_text(p)
            except OSError:
                continue
            f.units[rel] = len(_MEANINGFUL.findall(text))
        if ext == ".yml":
            entries = SC.loc_entries(text)
            if "/replace/" in rel:
                f.loc_replace |= set(entries)
            else:
                for k, v in entries.items():
                    if k not in f.loc:
                        f.loc[k] = rel
                        f.loc_hash[k] = stable_hash(v)
            continue
        if ext not in SCRIPT_EXT:
            continue
        stripped = SC.strip_comments(text)
        fname = rel.rsplit("/", 1)[1]
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
            if rel.startswith("events/"):
                f.namespaces |= SC.namespaces(text)
            for key, body, _ in SC.blocks(stripped):
                if key.startswith("@") or key in ("namespace",):
                    continue
                if folder.startswith("common/on_action"):
                    inner = SC.inner_keys(body) if body else set()
                    f.on_actions[key] = (rel, inner, stable_hash(SC.norm(body)))
                    if inner & {"effect", "trigger"} and key in van.oa_effect and \
                            fname != van.oa_effect[key]:
                        f.oa_overwrites[key] = rel
                f.provides.add(key)
                if not folder.startswith(MERGING_FOLDERS) and (folder, key) not in f.defines:
                    f.defines[(folder, key)] = fname
                    f.def_hash[(folder, key)] = stable_hash(SC.norm(body))
                    f.def_size[(folder, key)] = body.count("\n") + 1
            for k in GD.nested_defs(folder, stripped):
                f.provides.add(k)
        if rel.endswith(".txt") and rel.startswith(("common/", "events/", "history/")):
            for k in GD.CALL.findall(stripped):
                f.calls[k] = f.calls.get(k, 0) + 1
            if model is not None:
                guarded = GD.is_guarded(stripped, fname)
                for key, (u, c) in model.refs(stripped, guarded).items():
                    slot = f.refs.get(key)
                    if slot is None:
                        f.refs[key] = [u, c]
                    else:
                        slot[0] += u
                        slot[1] += c
        if ext in (".txt", ".gui"):
            for ident in SC.identifiers(stripped):
                f.ref_files[ident] = f.ref_files.get(ident, 0) + 1


def _merge(f, part):
    """Add a later piece of the same mod (pieces are in file order: first definitions win, as in one pass)."""
    f.units.update(part.units)
    f.overrides += part.overrides
    f.light += part.light
    f.heavy += part.heavy
    for k, fn in part.defines.items():
        if k not in f.defines:
            f.defines[k] = fn
            f.def_hash[k] = part.def_hash[k]
            f.def_size[k] = part.def_size[k]
    f.provides |= part.provides
    for k, rel in part.loc.items():
        if k not in f.loc:
            f.loc[k] = rel
            f.loc_hash[k] = part.loc_hash[k]
    f.loc_replace |= part.loc_replace
    f.loc_lang = f.loc_lang or part.loc_lang
    f.on_actions.update(part.on_actions)
    for k, n in part.ref_files.items():
        f.ref_files[k] = f.ref_files.get(k, 0) + n
    for k, (u, c) in part.refs.items():
        slot = f.refs.get(k)
        if slot is None:
            f.refs[k] = [u, c]
        else:
            slot[0] += u
            slot[1] += c
    for k, n in part.calls.items():
        f.calls[k] = f.calls.get(k, 0) + n
    f.namespaces |= part.namespaces
    f.define_vals.update(part.define_vals)
    for k, v in part.gui_defs.items():
        f.gui_defs.setdefault(k, v)
    f.removed.update(part.removed)
    f.oa_overwrites.update(part.oa_overwrites)
    f.vdiff.update(part.vdiff)
    f.vobjs.update(part.vobjs)


def _apply_part(f, part):
    for name in READ_FIELDS:
        setattr(f, name, getattr(part, name))
    f.total = max(1, sum(f.units.values()))
    f.light_override_share = f.light / (f.light + f.heavy) if f.light + f.heavy else 0.0


def _h64(line):
    """A line's fingerprint that stays the same between runs (kept on disk)."""
    b = line.encode("utf-8", "replace")
    return (zlib.crc32(b) << 32) | zlib.adler32(b)


def _object_file(rel):
    return rel.endswith(".txt") and rel.startswith(("common/", "events/", "history/")) and \
        not rel.startswith(MERGING_FOLDERS)


def _read_mod(f, van):
    """Read one mod in this process (kept for callers and tests that read a single mod)."""
    part, items = _plan(f.mod, van)
    _read_into(part, items, van)
    _apply_part(f, part)


def _chunks(items):
    out, cur, size = [], [], 0
    for it in items:
        cur.append(it)
        size += it[3]
        if size >= CHUNK_BYTES or len(cur) >= 1500:
            out.append(cur)
            cur, size = [], 0
    if cur or not out:
        out.append(cur)
    return out


# ---- reading side by side, in separate processes (each has its own copy of Python, so all cores work)
_W = {}


def _worker_init(game_dir, cache_dir):
    global CACHE_FILES
    CACHE_FILES = 400                  # a reading process keeps fewer of the game's files in memory
    van = vanilla_for(game_dir, cache_dir)
    van.knowledge()
    _W["van"] = van


def _worker_read(items):
    part = _Part()
    _read_into(part, items, _W["van"])
    return part


def default_workers():
    """Processes that read mods side by side: all cores but one (the window stays responsive), at most 6
    (each holds its own copy of the game's knowledge, about 100-300 MB).
    PMC_WORKERS overrides it (1 reads in the app's own process)."""
    try:
        forced = int(os.environ.get("PMC_WORKERS", "0"))
    except ValueError:
        forced = 0
    if forced > 0:
        return forced
    n = os.cpu_count() or 1
    return max(1, min(6, n - 1))


class FactStore:
    """What each mod defines and uses, kept on disk (one file per mod folder) so a mod is read once and
    again only when its files change, or the game version or the app's reading rules do."""

    def __init__(self, folder):
        self.folder = folder
        self._lock = threading.Lock()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass

    def _file(self, m):
        h = hashlib.sha1(os.path.normcase(os.path.abspath(m.folder or m.modfile)).encode("utf-8", "replace"))
        return os.path.join(self.folder, h.hexdigest()[:20] + ".pkl")

    @staticmethod
    def signature(m, van):
        return f"{FACTS_VERSION}|{KNOWLEDGE_VERSION}|{van.stamp}|{len(van.roots)}|{m.sig or (len(m.files), m.size, m.mtime)}"

    def has(self, m, van):
        """Is this mod's facts there for its current files? (Only the file's small header is read.)"""
        try:
            with open(self._file(m), "rb") as fh:
                head = pickle.load(fh)
        except Exception:
            return False
        return head.get("sig") == self.signature(m, van)

    def load(self, m, van):
        try:
            with open(self._file(m), "rb") as fh:
                head = pickle.load(fh)
                if head.get("sig") != self.signature(m, van):
                    return None
                data = pickle.load(fh)
        except Exception:
            return None
        part = _Part()
        d = data["part"]
        packed = d.pop("loc_packed", None)
        part.__dict__.update(d)
        if packed is not None:
            keys, rels, idx, hashes = packed
            part.loc = {k: rels[i] for k, i in zip(keys, idx)}
            part.loc_hash = dict(zip(keys, hashes))
        return part

    def save(self, m, van, part):
        path = self._file(m)
        try:
            tmp = path + ".tmp"
            d = dict(part.__dict__)
            # texts: each key once (it was in two tables), file names by number
            keys = list(d.pop("loc"))
            hashes = d.pop("loc_hash")
            rels, ri = [], {}
            idx = array.array("I")
            for k in keys:
                r = part.loc[k]
                if r not in ri:
                    ri[r] = len(rels)
                    rels.append(r)
                idx.append(ri[r])
            d["loc_packed"] = (keys, rels, idx, array.array("I", (hashes.get(k, 0) for k in keys)))
            with open(tmp, "wb") as fh:
                pickle.dump({"sig": self.signature(m, van), "key": m.key}, fh, protocol=pickle.HIGHEST_PROTOCOL)
                pickle.dump({"part": d}, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except Exception:
            pass

    def prune(self, keep_mods, older_than_days=45):
        """Forget mods that aren't installed any more (after a while: they may come back)."""
        keep = {os.path.basename(self._file(m)) for m in keep_mods}
        limit = time.time() - older_than_days * 86400
        try:
            for fn in os.listdir(self.folder):
                p = os.path.join(self.folder, fn)
                if fn not in keep and os.path.getmtime(p) < limit:
                    os.remove(p)
        except OSError:
            pass

    def size(self):
        try:
            return sum(os.path.getsize(os.path.join(self.folder, f)) for f in os.listdir(self.folder))
        except OSError:
            return 0


def read_mods(mods, van, store=None, workers=None, stop=None, progress=None):
    """{mod key: _Part} for every mod: from the store when it's unchanged, otherwise read (big jobs in
    several processes, in pieces of about CHUNK_BYTES so one huge mod doesn't hold the others up)."""
    say = progress or (lambda txt, p: None)
    out, todo = {}, []
    for m in mods:
        part = store.load(m, van) if store is not None else None
        if part is not None:
            out[m.key] = part
        else:
            todo.append(m)
    if not todo:
        say(f"All {len(mods)} mods were read before", 1.0)
        return out
    plans = {}
    total = 0
    for m in todo:
        part, items = _plan(m, van)
        plans[m.key] = (m, part, _chunks(items))
        total += sum(it[3] for it in items)
    done_bytes = [0]
    n_done = [0]
    known = len(out)

    def finished(key):
        m, part, _ = plans[key]
        out[key] = part
        if store is not None:
            store.save(m, van, part)
        n_done[0] += 1

    def tell(name):
        say(f"Reading {name} ({known + n_done[0]} of {len(mods)} mods)", done_bytes[0] / max(1, total))

    workers = default_workers() if workers is None else workers
    tasks = [(key, i, ch) for key, (_m, _p, chs) in plans.items() for i, ch in enumerate(chs) if ch]
    for key, (_m, _p, chs) in plans.items():
        if not any(chs):
            finished(key)
    pending = {key: len([c for c in chs if c]) for key, (_m, _p, chs) in plans.items() if any(chs)}
    results = {key: {} for key in pending}

    def got(key, i, part_i, size):
        results[key][i] = part_i
        done_bytes[0] += size
        if len(results[key]) == pending[key]:
            base = plans[key][1]
            for j in sorted(results[key]):
                _merge(base, results[key][j])
            del results[key]
            finished(key)
            tell(plans[key][0].name)

    tasks.sort(key=lambda t: -sum(it[3] for it in t[2]))        # biggest pieces first
    left = list(tasks)
    # the processes load the game's knowledge from the cache file the first step wrote
    can_share = not van.roots or (van.knowledge_ready and van.cache_dir)
    if workers > 1 and len(tasks) > 1 and total > 2 * CHUNK_BYTES and can_share:
        try:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor, as_completed
            ctx = mp.get_context("spawn")
            ex = ProcessPoolExecutor(max_workers=min(workers, len(tasks)), mp_context=ctx,
                                     initializer=_worker_init, initargs=(van.game_dir, van.cache_dir))
            try:
                futs = {ex.submit(_worker_read, t[2]): t for t in tasks}
                for fut in as_completed(futs):
                    if stop is not None and stop.is_set():
                        ex.shutdown(wait=False, cancel_futures=True)
                        return out
                    key, i, items = futs[fut]
                    got(key, i, fut.result(), sum(it[3] for it in items))
                    left.remove(futs[fut])
            finally:
                ex.shutdown(wait=True, cancel_futures=True)
        except Exception as e:                     # no processes here (or one failed): read the rest here
            _log_note(f"Reading in parallel didn't work ({type(e).__name__}: {e}); reading in one process.")
    for key, i, items in left:
        if stop is not None and stop.is_set():
            return out
        if key not in results or i in results[key]:
            continue
        part = _Part()
        _read_into(part, items, van)
        got(key, i, part, sum(it[3] for it in items))
    return out


_notes = []


def _log_note(text):
    _notes.append(text)


# ================================================================== how mods relate
def _owners(facts):
    """Name prefix -> the mod it belongs to ('carn' -> Carnalitas): the mod whose name starts with it, or
    the one defining most names with it (if clearly the most)."""
    by_prefix = {}
    for f in facts:
        for p, n in f.prefixes.items():
            by_prefix.setdefault(p, []).append((n, f))
    out = {}
    for p, who in by_prefix.items():
        if len(p) < 2:
            continue
        named = [f for _, f in who if any(t.startswith(p) for t in tokens(f.name)[:2]) or
                 p.upper() in f.aliases or "".join(t[0] for t in tokens(f.name) if t not in _TOKEN_STOP) == p]
        if len(named) == 1:
            out[p] = named[0].key
            continue
        who.sort(key=lambda x: -x[0])
        if who[0][0] >= 5 and (len(who) == 1 or who[0][0] >= 3 * who[1][0]):
            out[p] = who[0][1].key
    return out


def _builds_on(facts, van, owners):
    """B builds on A when it really USES names only A defines (adds A's traits, fires A's events, calls A's
    effects), outside checks and guarded compatibility files. Names B only checks for, or uses inside
    files that first check whether A is there, are optional: B works without A."""
    vanilla_all = van.all_names() if van.roots else set()
    owner = {}
    for f in facts:
        for key in f.provides:
            if len(key) < 5 or key in vanilla_all:
                continue
            owner.setdefault(key, set()).add(f.key)
    by_key = {f.key: f for f in facts}
    for b in facts:
        hard, soft, examples = {}, {}, {}
        seen = set()
        # typed references: (folder, name) -> [uses, checks]
        for (folder, name), (u, c) in b.refs.items():
            seen.add(name)
            own = owner.get(name)
            if not own or len(own) > 2 or b.key in own:
                continue
            for a in own:
                if u:
                    hard[a] = hard.get(a, 0) + 1
                    ex = examples.setdefault(a, [])
                    if len(ex) < 4:
                        ex.append(name)
                else:
                    soft[a] = soft.get(a, 0) + 1
        # calls of scripted effects / triggers (`name = yes`)
        for name, n in b.calls.items():
            if name in seen:
                continue
            own = owner.get(name)
            if not own or len(own) > 2 or b.key in own:
                continue
            for a in own:
                folder = next((fo for (fo, k) in by_key[a].defines if k == name), "")
                if not folder.startswith(("common/scripted_effects", "common/scripted_triggers",
                                          "common/script_values", "common/scripted_modifiers")):
                    continue
                hard[a] = hard.get(a, 0) + 1
                ex = examples.setdefault(a, [])
                if len(ex) < 4:
                    ex.append(name)
        if not van.knowledge_ready:              # no reference model: untyped names (older behaviour)
            for ident in b.ref_files:
                own = owner.get(ident)
                if not own or len(own) > 2 or b.key in own:
                    continue
                for a in own:
                    hard[a] = hard.get(a, 0) + 1
                    ex = examples.setdefault(a, [])
                    if len(ex) < 4:
                        ex.append(ident)
        for a, n in hard.items():
            if n >= 3:
                b.builds_on[a] = n
                b.uses_examples[a] = examples[a]
                by_key[a].used_by[b.key] = n
        for a, n in soft.items():
            if a not in b.builds_on and n >= 2:
                b.optional[a] = n


def _content_paths(f):
    return {r for r in f.files if r.startswith(("common/", "events/", "gui/", "localization/", "localisation/",
                                                 "gfx/", "history/", "map_data/", "music/", "sound/"))}


def _bundles(facts):
    """A pack that already contains another mod: it ships most of that mod's files (the same paths), or
    most of its objects. Records a.bundles[b] = share of b found in a."""
    paths = {f.key: _content_paths(f) for f in facts}
    for a in facts:
        pa = paths[a.key]
        for b in facts:
            if a is b:
                continue
            pb = paths[b.key]
            if len(pb) < 4 or len(pa) <= len(pb):
                continue
            share = len(pa & pb) / len(pb)
            if share >= 0.5:
                a.bundles[b.key] = round(share, 2)
                continue
            if len(b.defines) >= 10:
                objs = sum(1 for k in b.defines if k in a.defines)
                if objs / len(b.defines) >= 0.6:
                    a.bundles[b.key] = round(objs / len(b.defines), 2)


def _related(a, b, facts):
    """One mod builds on, depends on, bundles or patches the other: what they do to each other is on purpose."""
    return (b.key in a.builds_on or a.key in b.builds_on or b.key in b_dep_keys(a, facts)
            or a.key in b_dep_keys(b, facts) or b.key in a.optional or a.key in b.optional)


_dep_memo = weakref.WeakKeyDictionary()


def b_dep_keys(f, facts):
    """Keys of the mods (among facts) that f declares as dependencies. Asked for every pair, so it's worked
    out once per mod and set of mods."""
    if not f.mod.dependencies:
        return set()
    sig = (len(facts), facts[0].key if facts else "", facts[-1].key if facts else "")
    hit = _dep_memo.get(f)
    if hit is not None and hit[0] == sig:
        return hit[1]
    out = set()
    for dep in f.mod.dependencies:
        cd = clean_title(dep).lower()
        for o in facts:
            if o is not f and (cd == clean_title(o.name).lower() or similarity(dep, o.name) >= 0.85):
                out.add(o.key)
    _dep_memo[f] = (sig, out)
    return out


_derived, _dlock = collections.OrderedDict(), threading.Lock()


def _memo(kind, path, make):
    """Something worked out from a file (its objects, its names), kept for the next pair that shares it:
    when 50 mods replace one game file, each copy is parsed once instead of once per pair."""
    key = (kind, _stamp(path))
    with _dlock:
        hit = _derived.get(key)
        if hit is not None:
            _derived.move_to_end(key)
            return hit
    val = make()
    with _dlock:
        _derived[key] = val
        while len(_derived) > 2 * CACHE_FILES:
            _derived.popitem(last=False)
    return val


def _defined_in(path):
    if not path.endswith(".txt"):
        return set()
    return _memo("defs", path, lambda: set(SC.defined_keys(read_cached(path)[0])))


def _bodies(path):
    return _memo("bodies", path, lambda: SC.object_bodies(read_cached(path)[0]))


def _broken(f, rel, lost_defs):
    """Names f defined in `rel` that it also uses in other files (they vanish if f's copy loses)."""
    out = []
    for k in lost_defs:
        if f.ref_files.get(k, 0) >= 2:      # used somewhere besides its own definition
            out.append(k)
    return sorted(out)[:50]


def _objects_lost(rel, pa, pb, vp, ao=None, bo=None):
    """Inside a shared script file: (objects a changed that b's copy doesn't have the same, the same for b,
    objects both changed differently). ao / bo: the copies' object fingerprints when already known."""
    if not _object_file(rel):
        return [], [], []
    if ao is not None and bo is not None:
        vo = _memo("vobj", vp, lambda: {k: stable_hash(b) for k, b in _bodies(vp).items()}) if vp else {}
    else:
        ao, bo = _bodies(pa), _bodies(pb)
        vo = _bodies(vp) if vp else {}
    ch_a = {k for k, v in ao.items() if vo.get(k) != v}
    ch_b = {k for k, v in bo.items() if vo.get(k) != v}
    lost_a = sorted(k for k in ch_a if bo.get(k) != ao[k])
    lost_b = sorted(k for k in ch_b if ao.get(k) != bo[k])
    both = sorted(k for k in ch_a & ch_b if ao[k] != bo[k])
    return lost_a, lost_b, both


def _compare(rel, a, b, vlines, vp=None):
    pa, pb = a.mod.paths.get(rel), b.mod.paths.get(rel)
    if pa and pb and modscan.same_file(pa, pb, a.mod.sizes.get(rel) if hasattr(a.mod, "sizes") else None,
                                       b.mod.sizes.get(rel) if hasattr(b.mod, "sizes") else None):
        return FileConflict(rel, a.key, b.key, "same")
    if not (pa and pb) or not is_text(rel):
        return FileConflict(rel, a.key, b.key, "clash", max(1, a.units.get(rel, BIN_UNITS)),
                            max(1, b.units.get(rel, BIN_UNITS)))
    fa_, fb_ = getattr(a, "vdiff", {}).get(rel), getattr(b, "vdiff", {}).get(rel)
    if fa_ is not None and fb_ is not None:
        # both replace this game file: what each changed is known from reading, nothing to open again
        (add_a, rem_a), (add_b, rem_b) = fa_, fb_
        if add_a == add_b and rem_a == rem_b:
            return FileConflict(rel, a.key, b.key, "same")
        cov_ab, lost_a = _cover_known(add_a, rem_a, add_b, rem_b)
        cov_ba, lost_b = _cover_known(add_b, rem_b, add_a, rem_a)
        if cov_ab >= 0.9 and cov_ba >= 0.9:
            return FileConflict(rel, a.key, b.key, "same", lost_a, lost_b)
        if cov_ab >= 0.9:
            return FileConflict(rel, a.key, b.key, "a_in_b", lost_a, lost_b)
        if cov_ba >= 0.9:
            return FileConflict(rel, a.key, b.key, "b_in_a", lost_a, lost_b)
        oa_, ob_ = a.vobjs.get(rel), b.vobjs.get(rel)
        if oa_ is not None and ob_ is not None:
            da, db = set(oa_), set(ob_)
            oa, ob, both = _objects_lost(rel, pa, pb, vp, oa_, ob_)
        else:
            da, db = _defined_in(pa), _defined_in(pb)
            oa, ob, both = _objects_lost(rel, pa, pb, vp)
        return FileConflict(rel, a.key, b.key, "clash", max(1, lost_a), max(1, lost_b),
                            _broken(a, rel, da - db), _broken(b, rel, db - da), oa, ob, both)
    la, lb = text_lines(pa), text_lines(pb)
    if la == lb:
        return FileConflict(rel, a.key, b.key, "same")          # only spacing or comments differ
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


# ================================================================== grading
def file_severity(rel, broken=0):
    """Kept for older callers: a rough severity for one shared file."""
    if rel.startswith("map_data/") or rel.startswith("common/landed_titles/"):
        return "critical" if rel.startswith("map_data/") else "high"
    if rel.startswith("gui/") and rel.endswith(".gui"):
        return "high"
    if broken:
        return "high"
    if rel.startswith(("common/", "events/", "history/")):
        return "medium"
    return "low"


def _sev(score, high=8.0, medium=3.0):
    return "high" if score >= high else "medium" if score >= medium else "low"


def _obj_score(folder, size_a=1, size_b=1):
    """What's at stake when two mods disagree about one object: the kind of object, and how big the
    changes are (a one-line tweak matters less than a rewritten decision)."""
    w = GD.folder_info(folder).weight
    size = min(size_a, size_b)
    return w * (0.5 if size <= 2 else 1.0 if size <= 30 else 1.4)


def _kinds_text(objs):
    """'3 traits, 1 decision' from [(folder, name)]; '' when they're only generic game objects."""
    counts = {}
    for folder, _ in objs:
        info = GD.folder_info(folder)
        counts[info.prefix] = counts.get(info.prefix, 0) + 1
    parts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    if all(GD.folder_info(p).noun == "game object" for p, _ in parts):
        return ""
    return ", ".join(GD.folder_info(p).count(n) for p, n in parts[:4]) + (" and more" if len(parts) > 4 else "")


def _paren(text):
    return f" ({text})" if text else ""


def _group_score(scores):
    """Many small disagreements add up, but not linearly: 13 objects matter more than 1, not 13 times more."""
    if not scores:
        return 0.0
    avg = sum(scores) / len(scores)
    return avg * len(scores) ** 0.65


def _notice(objs):
    """What you notice in game, for the most important kind of object involved."""
    if not objs:
        return ""
    folders = sorted({GD.folder_info(f).prefix for f, _ in objs}, key=lambda p: -GD.folder_info(p).weight)
    return GD.folder_info(folders[0]).notice


def _winner_file(fa, fb, mode):
    """Which of two file names the game keeps for an object ('a' or 'b')."""
    if mode == "fios":
        return "a" if fa < fb else "b"
    return "a" if fa > fb else "b"


# ================================================================== issues between two mods
def _issues(an, facts, van):
    I = an.issues
    by = an.facts
    names = lambda *ks: " and ".join(f'"{by[k].name}"' for k in ks)
    bundled_pairs = {tuple(sorted((a.key, b))) for a in facts for b in a.bundles}

    # ---- what the Workshop pages say
    for f in facts:
        for kind, o, snip in f.hints:
            if kind == "incompatible":
                exact = bool(o.wid and o.wid in f.description) or clean_title(o.name).lower() in snip.lower()
                I.append(Issue("incompatible", "critical" if exact else "high", [f.key, o.key],
                               f"{names(f.key, o.key)} don't work together",
                               f'{f.name}\'s Workshop page says: "{snip}"', fix="Keep only one of them",
                               confidence="likely" if exact else "possible", score=20))
    # ---- two total conversions / map mods
    big = [f for f in facts if f.role and f.role.role.id in ("total_conversion", "map")]
    for x in range(len(big)):
        for y in range(x + 1, len(big)):
            a, b = big[x], big[y]
            if a.key in b.builds_on or b.key in a.builds_on or a.key in b_dep_keys(b, facts) or \
                    b.key in b_dep_keys(a, facts) or b.key in a.bundles or a.key in b.bundles:
                continue
            I.append(Issue("two_conversions", "critical", [a.key, b.key],
                           f"Two {('total conversions' if 'total_conversion' in (a.role.role.id, b.role.role.id) else 'map mods')}",
                           f"{names(a.key, b.key)} each replace the game world. Only one map can load; the "
                           "other's provinces, titles and history won't match it.", fix="Keep only one of them",
                           score=30))
    # ---- the same mod twice / a pack that contains the other
    dup = set()
    for x in range(len(facts)):
        for y in range(x + 1, len(facts)):
            a, b = facts[x], facts[y]
            small = min(len(a.files), len(b.files))
            close = small >= 10 and abs(len(a.files) - len(b.files)) <= 0.25 * small
            same_name = similarity(a.name, b.name) >= 0.92
            if not (close or same_name):
                continue                      # neither condition can hold: skip comparing the file lists
            overlap = len(a.files & b.files)
            if (same_name and overlap >= 0.5 * max(1, small)) or (close and overlap >= 0.8 * small):
                dup.add(tuple(sorted((a.key, b.key))))
                I.append(Issue("duplicate_mod", "critical", [a.key, b.key], f"{names(a.key, b.key)} look like the same mod",
                               f"They share {overlap} of {small} files. Two copies (or versions) of one mod "
                               "overwrite each other unpredictably.", fix="Turn one of them off", score=30))
    for a in facts:
        for bk, share in sorted(a.bundles.items()):
            pair = tuple(sorted((a.key, bk)))
            if pair in dup:
                continue
            b = by[bk]
            fcs = an.conflicts.get(pair, [])
            same = sum(1 for c in fcs if c.kind != "clash")
            differ = [c for c in fcs if c.kind == "clash"]
            dep = b.key in b_dep_keys(a, facts) or a.key in b.builds_on
            if dep and not differ:
                continue                       # a submod that ships the files of its base on purpose
            sev = "high" if len(differ) >= 3 else "medium" if differ else "low"
            I.append(Issue("bundled", sev, [a.key, b.key], f'"{a.name}" already contains "{b.name}"',
                           f'"{a.name}" ships {round(share * 100)}% of "{b.name}" ({same} of the shared files '
                           f"are the same, {len(differ)} differ: most likely another version). Used together, the "
                           "two copies overwrite each other file by file and object by object.",
                           items=[_clash_line(c, by) for c in differ[:200]],
                           fix=f'Keep only one: usually the pack ("{a.name}"), unless you want "{b.name}"\'s '
                               "newer version: then check the pack's page for how to update it.",
                           confidence="likely", score=12 + len(differ)))

    # ---- one mod adds extras when the other is on (checks for its things, or guarded compat files)
    for f in facts:
        for ok, n in f.optional.items():
            o = by[ok]
            I.append(Issue("optional", "info", [f.key, ok], f'"{f.name}" has extras for "{o.name}"',
                           f'"{f.name}" checks for {n} thing(s) "{o.name}" defines (or uses them only after checking '
                           f'that it\'s there). It works without "{o.name}"; with both on, it adds or adjusts '
                           "content for it.", confidence="likely"))
        for kind, o, snip in f.hints:
            if kind == "compatible":
                I.append(Issue("optional", "info", [f.key, o.key], f'"{f.name}" says it works with "{o.name}"',
                               f'Its Workshop page says: "{snip}"', confidence="likely"))
    # ---- shared files
    for (ka, kb), fcs in an.conflicts.items():
        pair = (ka, kb)
        same = [c for c in fcs if c.kind == "same"]
        merged = [c for c in fcs if c.kind in ("a_in_b", "b_in_a")]
        clashes = [c for c in fcs if c.kind == "clash"]
        related = _related(by[ka], by[kb], facts)
        if same:
            I.append(Issue("identical", "info", [ka, kb], f"{len(same)} identical shared file(s)",
                           "Both ship the same content (spacing and comments aside), so it doesn't matter which "
                           "loads last.", items=[c.rel for c in same]))
        if merged:
            I.append(Issue("merged", "info", [ka, kb], f"{len(merged)} shared file(s) already merged",
                           "One mod's copy already contains the other's changes; it just has to load "
                           "after it (Auto-sort makes sure).", items=[c.rel for c in merged], order=True))
        if not clashes or pair in bundled_pairs:
            continue
        gui = [c for c in clashes if c.rel.startswith("gui/") and c.rel.endswith(".gui")]
        rest = [c for c in clashes if c not in gui]
        if gui:
            real = [c for c in gui if min(c.lost_a, c.lost_b) > 4]
            minor = [c for c in gui if c not in real]
            if real:
                least = max(min(c.lost_a, c.lost_b) for c in real)
                score = sum(min(c.lost_a, c.lost_b) for c in real) ** 0.5 * 2
                sev = "high" if least >= 15 else "medium"
                if related:
                    sev = "medium" if sev == "high" else "low"
                I.append(Issue("gui_window", sev, [ka, kb], f"Both replace {_short_files(real)}",
                               "A .gui window file is replaced whole. Whichever mod loads last provides the "
                               "window; the other mod's additions to it (buttons, panels) disappear. Both "
                               "changed this window substantially.",
                               items=[_clash_line(c, by) for c in real],
                               fix="Pick the order that keeps the more important window, or find a compatch "
                                   "(a merged copy of the window)", order=True, score=score,
                               objects=[(c.rel, "") for c in real]))
            if minor:
                I.append(Issue("gui_window", "low", [ka, kb], f"Both replace {_short_files(minor)} (one only slightly)",
                               "A .gui window file is replaced whole, but one of the two mods changes only a "
                               "few lines in it: load that mod first and the other's window keeps almost "
                               "everything (or merge the small change by hand).",
                               items=[_clash_line(c, by) for c in minor], order=True, score=1,
                               fix="Load the mod with the bigger change last (Auto-sort does)"))
        if rest:
            objs = [(c.rel, o) for c in rest for o in sorted(set(c.objs_a) | set(c.objs_b))]
            both = sorted({(c.rel, o) for c in rest for o in c.objs_both})
            broken = sum(len(c.broken_a) + len(c.broken_b) for c in rest)
            score = 0.0
            cosmetic = True
            for c in rest:
                info = GD.folder_info(c.rel)
                lines = min(c.lost_a, c.lost_b)
                if not is_text(c.rel):
                    score += info.weight * 0.5                 # a picture, model, sound or font
                else:
                    score += info.weight * (0.4 if lines <= 2 else 1.0 if lines <= 40 else 1.6)
                if info.weight > 1:
                    cosmetic = False
                if c.rel.startswith("map_data/"):
                    score += 20
            score += 2 * len(both) ** 0.5 + broken * 0.5
            if related:
                score *= 0.4
            sev = "critical" if any(c.rel.startswith("map_data/") for c in rest) and not related else _sev(score)
            if cosmetic and sev in ("high", "medium"):
                sev = "medium" if len(rest) >= 40 else "low"   # looks and texts only
            n_obj = len(objs)
            effect = (f"Whichever loads last, the other mod loses its changes to {n_obj} object(s) in these "
                      "files" + (f", {len(both)} of them changed by both (only a compatch can keep both "
                                 "versions)" if both else "") + "." if n_obj else
                      ("Pictures, sounds or texts come from the mod loaded last: only looks change." if cosmetic
                       else DIAG["file_clash"][0]))
            I.append(Issue("file_clash", sev, [ka, kb], f"{len(rest)} file{'s' if len(rest) != 1 else ''} changed differently",
                           "Both mods ship these files with different changes. The mod loaded last provides "
                           "each file whole; the other mod's changes to it are lost." +
                           (f" {broken} of the lost definitions are used elsewhere by their mod, so losing "
                            "them also breaks other parts of it." if broken else "") +
                           (" One mod builds on the other, so this is probably intended." if related else ""),
                           items=[_clash_line(c, by) for c in rest],
                           fix=("Load order decides which mod keeps its changes (Auto-sort picks the less "
                                "damaging winner); only a compatch keeps both" if not both else
                                "Load order only picks the loser here: both mods change the same objects, so "
                                "only a compatch keeps both"), order=True, effect=effect,
                           remedy="compatch" if both and len(both) >= 3 else "order",
                           objects=objs, score=score))

    # ---- objects defined twice under different file names
    _object_issues(an, facts, van, bundled_pairs)
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
                pair = tuple(sorted((fa.key, fb.key)))
                if pair in bundled_pairs:
                    continue
                na_, nb_ = ra.rsplit("/", 1)[1], rb.rsplit("/", 1)[1]
                win_file = max(na_, nb_)
                line = f"{name}: {', '.join(sorted(ia | ib))} in {na_} and {nb_} (the one in {win_file} runs)"
                oa_objs.setdefault(pair, []).append(("common/on_action", name))
                deliberate = re.search(r"disabl|compat|override|patch|replace", win_file, re.I) or \
                    _related(fa, fb, facts)
                (intended if deliberate else pairs).setdefault(pair, []).append(line)
    for (ka, kb), lines in pairs.items():
        I.append(Issue("on_action", "high" if len(lines) >= 2 else "medium", [ka, kb],
                       f"{len(lines)} on-action effect(s) overwritten",
                       "Both put an effect/trigger block into the same on-action. Those blocks don't merge: "
                       "only one runs (decided by file name), so part of one mod never happens.",
                       items=lines, fix="Load order can't fix this. " + FIND_TXT + ".",
                       objects=oa_objs.get((ka, kb), []), score=4 * len(lines)))
    for (ka, kb), lines in intended.items():
        I.append(Issue("integration", "low", [ka, kb], f"{len(lines)} on-action(s) replaced on purpose",
                       "One mod replaces the other's on-action block deliberately (its file is named as a "
                       "disabler/compat override, or it builds on the other mod).", items=lines))
    # ---- localisation keys
    # only keys at least two mods define are looked at (counted in one pass, not one dict entry per key)
    shared_keys = {k for k, n in collections.Counter(k for f in facts for k in f.loc).items() if n >= 2}
    loc_owner = {}
    for f in facts:
        loc = f.loc
        for k in shared_keys.intersection(loc):
            loc_owner.setdefault(k, []).append((f, loc[k]))
    lp = {}
    for k, who in loc_owner.items():
        if len(who) < 2:
            continue
        for x in range(len(who)):
            for y in range(x + 1, len(who)):
                (fa, ra), (fb, rb) = who[x], who[y]
                if fa.key != fb.key and ra != rb and fa.loc_hash.get(k) != fb.loc_hash.get(k) and \
                        getattr(fa, "loc_lang", "") == getattr(fb, "loc_lang", ""):
                    lp.setdefault(tuple(sorted((fa.key, fb.key))), []).append(k)
    for (ka, kb), keys in lp.items():
        if (ka, kb) in bundled_pairs:
            continue
        related = _related(by[ka], by[kb], facts)
        I.append(Issue("loc_duplicate", "info" if related else "low", [ka, kb],
                       f"{len(keys)} text(s) worded differently by both",
                       "Both define the same text keys, with different wording, outside a 'replace' folder: one "
                       "text is shown, the other ignored, and the game logs a duplicate-key error. Cosmetic.",
                       items=sorted(keys)[:300], score=min(2, len(keys) / 50)))
    # ---- replace_path
    for f in facts:
        for rp in f.mod.replace_paths:
            for o in facts:
                if o is f:
                    continue
                if rp in o.mod.replace_paths and o.key > f.key:
                    I.append(Issue("replace_path", "high", [f.key, o.key], f"Both replace the game's {rp}/",
                                   "Both remove the game's own files in that folder and bring their own; they "
                                   "were made for different worlds.", fix="Usually only one of them belongs in a playset",
                                   score=10))
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
        if (ka, kb) in bundled_pairs:
            continue
        if _related(by[ka], by[kb], facts):
            I.append(Issue("integration", "info", [ka, kb], f"{len(rows)} game setting(s) set on purpose",
                           "One mod builds on (or patches) the other and sets these values deliberately.",
                           items=[f"{cat}.{key}:  {fa.name} = {va}  |  {fb.name} = {vb}  ->  {win.name}'s is used"
                                  for cat, key, fa, va, fb, vb, win in rows]))
            continue
        I.append(Issue("define_clash", "medium" if len(rows) >= 4 else "low", [ka, kb],
                       f"{len(rows)} game setting(s) changed by both",
                       "Both mods change the same values in common/defines (things like fertility, health or "
                       "AI behaviour). Each value comes from one file only: the one whose name sorts later, "
                       "not the mod loaded last.",
                       items=[f"{cat}.{key}:  {fa.name} = {va}  |  {fb.name} = {vb}  ->  {win.name}'s is used"
                              for cat, key, fa, va, fb, vb, win in rows],
                       fix=FIND_TXT + ". Or accept one mod's values", objects=[("defines", f"{c}.{k}")
                                                                                for c, k, *_ in rows],
                       score=len(rows)))
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
                if pa and pb and modscan.same_file(pa, pb):
                    continue
                win = fa if ra.rsplit("/", 1)[1] < rb.rsplit("/", 1)[1] else fb
                gpairs.setdefault(tuple(sorted((fa.key, fb.key))), []).append((n, kd, fa, ra, fb, rb, win))
    for (ka, kb), rows in gpairs.items():
        if _related(by[ka], by[kb], facts) or (ka, kb) in bundled_pairs:
            continue
        I.append(Issue("gui_type", "medium" if len(rows) >= 3 else "low", [ka, kb],
                       f"{len(rows)} interface piece(s) defined by both",
                       "Both define the same GUI templates or types (shared looks like a button style or a font). "
                       "For these the FIRST file read wins (by file name), so one mod's version is used "
                       "everywhere, including in the other mod's windows.",
                       items=[f"{kd} {n}:  {fa.name}: {ra.rsplit('/', 1)[1]}  |  {fb.name}: {rb.rsplit('/', 1)[1]}"
                              f"  ->  {win.name}'s is used" for n, kd, fa, ra, fb, rb, win in rows],
                       fix="Load order can't fix this. " + FIND_TXT + ".",
                       objects=[("gui", n) for n, *_ in rows], score=len(rows)))
    # ---- a mod's copy of a game file leaves out objects another mod uses
    gone_names = {k for f in facts for (_fo, k) in f.removed}
    defined_anywhere = {}
    for f in facts:
        for key in gone_names.intersection(f.provides):
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
            if b.refs:
                used = sorted(n for n, (folder, _) in gone.items()
                              if b.refs.get((folder, n), (0, 0))[0] and b.key not in defined_anywhere.get(n, ()))
                checked = sorted(n for n, (folder, _) in gone.items()
                                 if n not in used and b.refs.get((folder, n), (0, 0))[1])
            else:
                used = sorted(n for n in gone if b.ref_files.get(n) and b.key not in defined_anywhere.get(n, ()))
                checked = []
            if not used:
                continue
            I.append(Issue("removed_used", "high" if len(used) >= 3 else "medium", [a.key, b.key],
                           f'"{a.name}" removes {len(used)} game object(s) "{b.name}" uses',
                           f'"{a.name}" replaces game files with copies that leave these objects out, and '
                           f'"{b.name}" adds, fires or calls them. With both on, those references point at nothing.'
                           + (f" (It also checks for {len(checked)} more, which only fail quietly.)" if checked else ""),
                           items=[f"{n}  [{gone[n][0]}]  left out of {gone[n][1]}" for n in used[:300]],
                           fix=f'Needs a compatch; or load "{b.name}"\'s own copy of the file after, if it has one',
                           objects=[(gone[n][0], n) for n in used], score=3 * len(used) ** 0.5 + 2))


def _object_issues(an, facts, van, bundled_pairs):
    """Objects two mods define under different file names: the file name decides (LIOS, FIOS for GUI),
    whatever the load order. Sorted into what's intended (placeholders, deliberate overrides, shared code,
    identical copies) and what isn't (both change one game object, an unchanged copy undoes a change, two
    independent things with one name, duplicate events)."""
    I = an.issues
    by = an.facts
    defined = {}
    for f in facts:
        for (folder, key), fname in f.defines.items():
            defined.setdefault((folder, key), []).append((f, fname))
    obj_pairs = {}
    for (folder, key), where in defined.items():
        if len(where) < 2 or key in van.containers.get(folder, ()) or GD.is_container(folder, key):
            continue                          # one entry, or a block the game merges from every file
        vanilla_has = key in van.names(folder) if van.roots else None
        vh = van.obj_hash(folder, key) if vanilla_has else None
        mode = GD.folder_info(folder).merge
        owner = an.owners.get(GD.name_prefix(key), "")
        for x in range(len(where)):
            for y in range(x + 1, len(where)):
                (fa, na), (fb, nb) = where[x], where[y]
                if fa.key == fb.key or na == nb:
                    continue
                pair = tuple(sorted((fa.key, fb.key)))
                w = _winner_file(na, nb, mode)
                winner, loser = (fa, fb) if w == "a" else (fb, fa)
                wfile, lfile = (na, nb) if w == "a" else (nb, na)
                ha, hb = fa.def_hash.get((folder, key)), fb.def_hash.get((folder, key))
                if ha == hb:
                    kind = "same"
                elif pair in bundled_pairs:
                    kind = "bundled"
                elif folder == "events":
                    kind = "event"
                elif vanilla_has and vh is not None and (ha == vh or hb == vh):
                    # one side is an unchanged copy of the game's object
                    unchanged = fa if ha == vh else fb
                    kind = "reverted" if unchanged is winner else "unchanged"
                elif vanilla_has:
                    # a game object both change: a file named to win only decides who loses. Intended
                    # only when one mod is made for the other (a submod, a compatch), or it's one author's
                    # shared code in two versions
                    if _related(fa, fb, facts):
                        kind = "other_mod"
                    elif GD.file_stem(na) == GD.file_stem(nb):
                        kind = "shared"
                    else:
                        kind = "vanilla"
                elif _is_hook(fa, folder, na, key) or _is_hook(fb, folder, nb, key):
                    kind = "hook"
                elif _placeholder(loser, lfile, winner, key, owner):
                    kind = "hook"
                elif _related(fa, fb, facts) or _deliberate(winner, wfile, loser, lfile, key, owner, facts):
                    kind = "other_mod"
                elif GD.file_stem(na) == GD.file_stem(nb) or _same_family(fa, fb, key, owner):
                    kind = "shared"
                elif vanilla_has is None:
                    kind = "unknown"
                else:
                    kind = "collision"
                fna, fnb = (na, nb) if fa.key == pair[0] else (nb, na)
                obj_pairs.setdefault(pair, []).append((key, folder, fna, fnb, kind, winner.key))
    an.objects = obj_pairs
    for (ka, kb), objs in obj_pairs.items():
        groups = {}
        for o in objs:
            groups.setdefault(o[4], []).append(o)
        A_, B_ = by[ka], by[kb]
        line = lambda o: (f"{o[0]}  [{GD.folder_info(o[1]).noun}, {o[1]}]  {A_.name}: {o[2]}  |  {B_.name}: {o[3]}"
                          f"  ->  {by[o[5]].name}'s is used")
        size = lambda o: _obj_score(o[1], A_.def_size.get((o[1], o[0]), 1), B_.def_size.get((o[1], o[0]), 1))
        if "event" in groups:
            g = groups["event"]
            meant = [o for o in g if _event_override(o, A_, B_, by)]
            plain = [o for o in g if o not in meant]
            if plain:
                score = _group_score([size(o) for o in plain]) + 4
                I.append(Issue("event_collision", "high", [ka, kb], f"{len(plain)} duplicate event ID(s)",
                               "Both define events with the same IDs in different files. Events can't be overridden "
                               "one by one, so the game keeps one and logs errors; the other mod's event is lost.",
                               items=[line(o) for o in plain], fix="Load order can't fix this. " + FIND_TXT + ".",
                               objects=[(o[1], o[0]) for o in plain], score=score))
            if meant:
                I.append(Issue("event_collision", "medium", [ka, kb],
                               f"{len(meant)} event(s) one mod tries to replace",
                               "One mod redefines the other's (or the game's) events on purpose, in a file named "
                               "to override them. Events can't be overridden one at a time, though: the game keeps "
                               "one copy and logs a duplicate-event error, and it isn't guaranteed to be the "
                               "intended one.", items=[line(o) for o in meant],
                               fix="Usually works out; if those events misbehave, a compatch replacing the whole "
                                   "events file solves it", objects=[(o[1], o[0]) for o in meant],
                               score=_group_score([size(o) for o in meant])))
        if "vanilla" in groups:
            g = groups["vanilla"]
            score = _group_score([size(o) for o in g])
            I.append(Issue("object_override", _sev(score, 10, 3), [ka, kb],
                           f"Both change {len(g)} game object{'s' if len(g) != 1 else ''}{_paren(_kinds_text([(o[1], o[0]) for o in g]))}",
                           "Both mods redefine the same objects of the game in files with different names. The "
                           "file name decides which version is used (the alphabetically later one), not the "
                           "load order, so one mod's change to each of these is ignored.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           effect=_notice([(o[1], o[0]) for o in g]).capitalize() + ".",
                           objects=[(o[1], o[0]) for o in g], score=score))
        if "reverted" in groups:
            g = groups["reverted"]
            score = _group_score([size(o) for o in g])
            I.append(Issue("reverted", _sev(score, 10, 3), [ka, kb],
                           f"An unchanged copy undoes {len(g)} change{'s' if len(g) != 1 else ''}{_paren(_kinds_text([(o[1], o[0]) for o in g]))}",
                           "One mod ships the game's own version of these objects, unchanged, in a file whose name "
                           "wins; the other mod's change to them is silently undone.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           objects=[(o[1], o[0]) for o in g], score=score))
        if "collision" in groups:
            g = groups["collision"]
            score = _group_score([size(o) for o in g]) + 1
            I.append(Issue("name_collision", _sev(score, 6, 2), [ka, kb],
                           f"{len(g)} name{'s' if len(g) != 1 else ''} used by both for different things"
                           f"{_paren(_kinds_text([(o[1], o[0]) for o in g]))}",
                           "Both mods add something new under the same name. Only one survives (decided by file "
                           "name), so the other mod's version silently changes behaviour.",
                           items=[line(o) for o in g], fix="Load order can't fix this. " + FIND_TXT + ".",
                           effect=_notice([(o[1], o[0]) for o in g]).capitalize() + ".",
                           objects=[(o[1], o[0]) for o in g], score=score))
        if "unknown" in groups:
            g = groups["unknown"]
            I.append(Issue("object_override", "low", [ka, kb], f"{len(g)} object(s) defined by both",
                           "Defined in both under different file names; the alphabetically later file wins. "
                           "(Set the game's folder in Settings to tell game objects from new ones.)",
                           items=[line(o) for o in g], score=1))
        if "shared" in groups:
            g = groups["shared"]
            I.append(Issue("shared_code", "low", [ka, kb], f"{len(g)} piece(s) of shared code in two versions",
                           "Both include the same piece of code (the same file apart from a prefix, or names of "
                           "one family both mods use), in different versions: usually one author's helper used by "
                           "several of their mods, or a framework both build on. The game uses the copy whose file "
                           "name sorts later for both mods; that's fine as long as it's the newer one.",
                           items=[line(o) for o in g], score=0.5,
                           fix="Usually nothing to do; if one of the mods misbehaves, update both"))
        if "other_mod" in groups:
            g = groups["other_mod"]
            I.append(Issue("integration", "info", [ka, kb], f"{len(g)} object(s) of one mod adjusted by the other",
                           "One mod redefines things of the other on purpose (a submod, a compatch, or a file "
                           "named to win over the other's).", items=[line(o) for o in g]))
        if "unchanged" in groups:
            g = groups["unchanged"]
            I.append(Issue("identical", "info", [ka, kb], f"{len(g)} unchanged game object(s) that lose anyway",
                           "One mod ships an unchanged copy of these game objects, but the other mod's version "
                           "wins, so its change is kept.", items=[line(o) for o in g]))
        if "same" in groups:
            g = groups["same"]
            I.append(Issue("identical", "info", [ka, kb], f"{len(g)} identical definition(s)",
                           "Both define these the same way (shared code they both include), so it doesn't "
                           "matter which copy the game uses.", items=[line(o) for o in g]))
        if "hook" in groups:
            g = groups["hook"]
            I.append(Issue("hook", "info", [ka, kb], f"{len(g)} compatibility hook(s)",
                           "Placeholders one mod defines in case the other isn't installed (they lose to the "
                           "real thing when it is), or `always = no` style checks the other mod replaces. This is "
                           "how mods detect each other: working as intended.",
                           items=[line(o) for o in g]))


def _is_hook(f, folder, fname, key):
    """A definition meant to be replaced: aaa_/zzz_ compat files or trivial `always = yes/no` bodies."""
    low = fname.lower()
    if "compat" in low or low.startswith(("aaa", "zzz", "00_compat", "zz_compat", "!")):
        p = f.mod.paths.get(f"{folder}/{fname}".lower())
        if p:
            text, _ = read_cached(p)
            for k, body, _ in SC.blocks(text):
                if k == key:
                    return SC.is_trivial(body)
    return False


def _placeholder(loser, lfile, winner, key, owner):
    """The losing definition is a stand-in for another mod's object: it sits in a file named to load first
    or to say it's for compatibility, and the name isn't the losing mod's own."""
    if owner == loser.key:
        return False
    named = GD.early_file(lfile) or GD._COMPAT_FILE.search(lfile)
    return bool(named) and (owner in ("", winner.key) or not owner)


def _deliberate(winner, wfile, loser, lfile, key, owner, facts=None):
    """The winning definition overrides the other mod's object on purpose: its file is named to load last
    or after the other's file ('zzz_cpr_carn_triggers.txt' beats 'carn_triggers.txt') and the name
    belongs to the losing mod (or nobody we know); or the name belongs to a third mod the winner is made
    for (a Carnalitas submod replacing a Carnalitas object, also in a pack that bundles Carnalitas)."""
    if owner == winner.key:
        return False
    stem = GD.file_stem(lfile)
    after_its_file = len(stem) >= 6 and stem in GD.file_stem(wfile) and wfile != lfile
    named = GD.late_file(wfile) or after_its_file
    if (GD.late_file(wfile) and owner == loser.key) or (after_its_file and owner in ("", loser.key)):
        return True
    if owner and owner != loser.key and facts is not None:
        made_for = owner in winner.builds_on or owner in b_dep_keys(winner, facts) or owner in winner.optional
        if made_for and (named or GD.file_stem(wfile) != GD.file_stem(lfile)):
            return True
    return False


def _same_family(fa, fb, key, owner=""):
    """Both mods name many of their own things with this name's prefix (one author's series of mods, or a
    framework both build on), or the prefix belongs to a third mod both copy helpers from: a name they
    share is shared code in two versions, not an accident."""
    p = GD.name_prefix(key)
    if not p:
        return False
    na, nb = fa.prefixes.get(p, 0), fb.prefixes.get(p, 0)
    if na >= 5 and nb >= 5:
        return True
    return bool(owner) and owner not in (fa.key, fb.key) and na >= 1 and nb >= 1


def _event_override(o, A_, B_, by):
    """A duplicate event that one mod defines on purpose to replace the other's (or the game's): its file
    is named to override ('zz_birth_events_override.txt', or contains the other file's name)."""
    fa, fb = o[2], o[3]
    for mine, other in ((fa, fb), (fb, fa)):
        stem = GD.file_stem(other)
        if re.search(r"overrid|overwrit|replace|patch|compat", mine, re.I) or GD.late_file(mine) or \
                (len(stem) >= 6 and stem in GD.file_stem(mine) and mine != other):
            return True
    return False


# ================================================================== problems of one mod on its own
def _single_mod_issues(an, facts, van):
    """Things one mod does that go wrong whatever else is installed: effect blocks put into the game's own
    on-actions (which replace what the game does there), and things it uses that exist nowhere: not in
    this game version, not in any installed mod (usually an outdated mod; renames explained)."""
    I = an.issues
    defined_anywhere = set()
    for f in facts:
        defined_anywhere |= f.provides
    vanilla_all = van.all_names() if van.roots else set()
    renamed = an.renamed or {}
    for f in facts:
        if f.oa_overwrites:
            items = [f"{name}: its block in {rel.rsplit('/', 1)[1]} replaces the game's "
                     f"(in {van.oa_effect.get(name, '?')})" for name, rel in sorted(f.oa_overwrites.items())]
            I.append(Issue("vanilla_on_action", "medium" if len(items) >= 2 else "low", [f.key],
                           f'"{f.name}" replaces {len(items)} of the game\'s own on-action effect(s)',
                           "It puts an effect or trigger block straight into on-actions the game already uses. "
                           "Those blocks don't add up: the game's own block (and any other mod's) for that moment "
                           "no longer runs. The usual way is a separate on-action added to the game's list.",
                           items=items, fix="Nothing to do as a player unless something at that moment breaks; "
                                            "tell the author", objects=[("common/on_action", n) for n in f.oa_overwrites],
                           score=len(items)))
        if not van.knowledge_ready or not f.refs:
            continue
        miss = {}
        for (folder, name), (u, _c) in f.refs.items():
            if not u or name in defined_anywhere or name in vanilla_all:
                continue
            if folder.startswith(("common/script_values", "common/modifiers", "common/game_rules")):
                continue                     # values, modifiers and rules also come from code and parameters
            if not (re.fullmatch(r"[A-Za-z][\w\-']{2,}", name) or GD.EVENT_ID.match(name)) or name.isupper():
                continue
            miss[(folder, name)] = u
        if not miss:
            continue
        an.missing[f.key] = miss
        if len(miss) < 2:
            continue
        rows = sorted(miss.items(), key=lambda x: (x[0][0], x[0][1]))
        ren = [(n, renamed[n]) for (_fo, n) in miss if n in renamed]
        weight = sum(GD.folder_info(fo).weight for (fo, _n) in miss)
        I.append(Issue("missing_refs", "medium" if weight >= 12 else "low", [f.key],
                       f'"{f.name}" uses {len(miss)} thing{"s" if len(miss) != 1 else ""} that don\'t exist'
                       f"{_paren(_kinds_text(list(miss)))}",
                       "It adds, fires or calls these, but neither this game version nor any installed mod "
                       "defines them. Usually the mod was made for an older version, or it expects another mod."
                       + (f" {len(ren)} {'was' if len(ren) == 1 else 'were'} renamed by the game: " + ", ".join(f"{a} -> {b}" for a, b in ren[:6])
                          + "." if ren else ""),
                       items=[f"{n}  [{GD.folder_info(fo).noun}]  used {u}x" + (f"  (now {renamed[n]})" if n in renamed else "")
                              for (fo, n), u in rows[:300]],
                       fix="Look for an update made for your game version", objects=list(miss),
                       score=weight / 4))


# ================================================================== installed compatches
PATCHABLE = {"file_clash", "gui_window", "object_override", "name_collision", "event_collision", "on_action",
             "define_clash", "gui_type", "removed_used", "loc_duplicate", "reverted"}


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
    # who could patch whom: a mod qualifies for a pair only if it needs, uses or names one of the two, so
    # each pair looks at those few mods instead of every installed one
    deps_of = {c.key: b_dep_keys(c, facts) for c in facts}
    pos = {c.key: i for i, c in enumerate(facts)}
    named_of = {}
    near = {}
    for c in facts:
        title = clean_title(c.name)
        hit = set()
        if any(t for t in tokens(title)):
            for x in facts:
                if x is not c and mentions(title, x):
                    hit.add(x.key)
        named_of[c.key] = hit
        for k in deps_of[c.key] | set(c.builds_on) | hit:
            near.setdefault(k, set()).add(c.key)
    out = {}
    for ka, kb in pairs:
        a, b = by[ka], by[kb]
        clash_files = {c.rel for c in an.conflicts.get((ka, kb), []) if c.kind == "clash"}
        clash_objs = {(o[1], o[0]) for o in an.objects.get((ka, kb), [])}
        found = []
        for ck in sorted(near.get(ka, set()) | near.get(kb, set()), key=pos.get):
            c = by[ck]
            if c.key in (ka, kb):
                continue
            deps = deps_of[c.key]
            why, sure = "", ""
            if ka in deps and kb in deps:
                why, sure = "declares it needs both", "certain"
            elif ka in c.builds_on and kb in c.builds_on:
                why, sure = "uses things only each of them defines", "certain"
            else:
                named = [x for x in (a, b) if x.key in named_of[c.key]]
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
    if not is_text(c.rel):
        return f"{c.rel}   different versions of this file in {a} and {b}{extra}"
    return f"{c.rel}   {a}: {c.lost_a} changed lines  |  {b}: {c.lost_b}{extra}"


# ================================================================== one playset
def playset_issues(an, enabled, game_version="", installed=None):
    """Problems of one playset: pair problems between its enabled mods, problems of each mod on its own,
    plus what the set itself lacks (declared dependencies, mods it really builds on, requirements on
    Workshop pages)."""
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
    # what's installed, for "it needs X": every installed mod when the caller knows them (a check only
    # covers the playset), otherwise the checked ones
    installed = list(installed) if installed is not None else list(by.values())
    for k in keys:
        f = by[k]
        for dep in f.mod.dependencies:
            t = next((o for o in installed if o.key != f.key and (clean_title(o.name).lower() == clean_title(dep).lower()
                                                              or similarity(dep, o.name) >= 0.85)), None)
            if t is not None and t.key in on:
                continue
            out.append(Issue("missing_dependency", "critical", [k], f'"{f.name}" needs "{dep}"',
                             (f'"{t.name}" is installed but not turned on in this playset.' if t else
                              f'"{dep}" isn\'t installed.') + " The mod declares it can't work without it.",
                             fix="Turn it on" if t else "Download it (Catch tab)", score=25))
        for a, n in f.builds_on.items():
            if a in on or n < 8:
                continue
            if any(a in by[x].bundles for x in on):
                continue                      # a pack that's on already contains it
            ex = ", ".join(f.uses_examples.get(a, [])[:3])
            out.append(Issue("missing_dependency", "high", [k], f'"{f.name}" uses "{by[a].name}", which is off',
                             f"It adds, fires or calls {n} things only \"{by[a].name}\" defines (e.g. {ex}), "
                             "outside any check for whether that mod is there. Without it those parts break or "
                             "log errors.", fix=f'Turn on "{by[a].name}"', confidence="likely", score=10))
        for kind, o, snip in f.hints:
            if kind == "requires" and o.key not in on and not any(o.key in by[x].bundles for x in on):
                out.append(Issue("missing_dependency", "high", [k], f'"{f.name}" asks for "{o.name}"',
                                 f'Its Workshop page says: "{snip}"', fix=f'Turn on "{o.name}"',
                                 confidence="likely", score=8))
    if game_version:
        import versions as V
        for k in keys:
            f = by[k]
            if V.compatible(f.mod.supported, game_version) is False:
                out.append(Issue("version", "low", [k], f'"{f.name}" was made for game {f.mod.supported}',
                                 f"You play {V.clean(game_version)}. It usually still loads, but things it changes "
                                 "may have moved in the game since."))
    out.sort(key=lambda i: (i.rank, -getattr(i, "score", 0), i.kind))
    return out


def summary(issues):
    out = {s: 0 for s in SEVERITIES}
    for i in issues:
        out[i.severity] += 1
    return out
