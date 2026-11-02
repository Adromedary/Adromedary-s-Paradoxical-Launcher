"""
What the game's files mean, for judging conflicts the way the game does.

  * How each folder combines when several mods (and the game) define things there:
      lios     object by object, the file whose name sorts LAST wins (most of common/)
      fios     object by object, the file whose name sorts FIRST wins (GUI types and templates)
      whole    objects can't be replaced one by one: two mods defining one event id make a duplicate,
               a faith only changes with its whole religion, history characters duplicate
      append   on_actions: `events`, `random_events` and `on_actions` lists add up; `effect` and
               `trigger` blocks replace each other (with errors)
      defines  per setting (NCategory.KEY), last file name wins
      loc      text keys: a second definition is an error, unless it sits in a `replace` folder
      file     only the whole file can be replaced (windows, pictures, map data, sounds)
  * What an object is called in plain words (a trait, a decision...), what you notice in game when two
    mods disagree about one, and how much it matters (weights for grading).
  * Which script keys point at which kind of object, learned from the game's own scripts: `add_trait =
    x` names a trait, `trigger_event = x` an event, `faith:x` a faith... so a mod's references are
    typed. A reference is a CHECK (`has_trait`, `exists`...: harmless when the thing is missing) or a
    USE (adding it, firing it, calling it: breaks when it's missing). Files that first check whether
    another mod is there (a global variable, an "is loaded" trigger, a compat file) make their
    references optional.
  * The game's own rename tables (*.lookup) and its documentation of each folder (_*.info).
"""
import json
import os
import re
import time

import script as SC
from installer import read_text

# ------------------------------------------------------------------ folders
# (path prefix, singular, plural, weight 1..3, merge mode, what you notice in game when two mods disagree)
_F = [
    ("events", "event", "events", 3, "whole",
     "events of one mod never fire, or show the other mod's text and options"),
    ("common/on_action", "on-action", "on-actions", 3, "append",
     "something a mod does at a game moment (birth, death, yearly pulse...) never happens"),
    ("common/scripted_effects", "scripted effect", "scripted effects", 3, "lios",
     "code both mods call does what one mod expects: the other mod's events, decisions or interactions "
     "act wrongly"),
    ("common/scripted_triggers", "scripted trigger", "scripted triggers", 3, "lios",
     "a condition both mods check gives one mod's answer: things show up, or stay hidden, when the other "
     "mod doesn't expect it"),
    ("common/script_values", "script value", "script values", 2, "lios",
     "a number both mods use (a cost, chance or amount) comes from one mod"),
    ("common/scripted_modifiers", "scripted modifier", "scripted modifiers", 2, "lios",
     "AI and chance weights follow one mod"),
    ("common/scripted_lists", "scripted list", "scripted lists", 2, "lios", "a list both mods use follows one mod"),
    ("common/scripted_guis", "scripted GUI", "scripted GUIs", 3, "lios",
     "a button or panel does what one mod wants: the other mod's button does nothing or the wrong thing"),
    ("common/scripted_relations", "relation", "relations", 2, "lios", "a relation behaves like one mod's"),
    ("common/character_interactions", "character interaction", "character interactions", 3, "lios",
     "an interaction in the character menu works like one mod's version; the other's changes are gone"),
    ("common/decisions", "decision", "decisions", 3, "lios",
     "a decision works like one mod's version; the other's is gone"),
    ("common/schemes", "scheme", "schemes", 3, "lios", "a scheme works like one mod's version"),
    ("common/story_cycles", "story", "stories", 3, "lios", "a story (cycle of events) follows one mod"),
    ("common/activities", "activity", "activities", 3, "lios", "an activity (feast, hunt...) follows one mod"),
    ("common/situation", "situation", "situations", 3, "lios", "a situation follows one mod"),
    ("common/struggle", "struggle", "struggles", 3, "lios", "a struggle follows one mod"),
    ("common/traits", "trait", "traits", 2, "lios",
     "a trait has one mod's effects, opinions and icon; the other mod's version of it is gone"),
    ("common/modifiers", "modifier", "modifiers", 2, "lios", "a modifier gives one mod's bonuses"),
    ("common/opinion_modifiers", "opinion modifier", "opinion modifiers", 1, "lios",
     "an opinion value follows one mod"),
    ("common/laws", "law", "laws", 2, "lios", "a law works like one mod's version"),
    ("common/law_groups", "law group", "law groups", 2, "lios", "a group of laws follows one mod"),
    ("common/buildings", "building", "buildings", 2, "lios", "a building has one mod's costs and effects"),
    ("common/men_at_arms_types", "men-at-arms type", "men-at-arms types", 2, "lios",
     "a regiment type has one mod's stats"),
    ("common/casus_belli_types", "casus belli", "casus belli", 2, "lios", "a war goal works like one mod's"),
    ("common/governments", "government", "governments", 2, "lios", "a government type follows one mod"),
    ("common/religion/religion_types", "religion", "religions", 2, "lios",
     "a religion, with all its faiths, comes from one mod: the other's faiths or changes are gone"),
    ("common/religion/doctrine_types", "doctrine", "doctrines", 2, "lios", "a doctrine follows one mod"),
    ("common/religion", "religion piece", "religion pieces", 2, "lios", "a religion detail follows one mod"),
    ("common/culture/cultures", "culture", "cultures", 2, "lios", "a culture follows one mod"),
    ("common/culture/traditions", "tradition", "traditions", 2, "lios", "a tradition follows one mod"),
    ("common/culture/innovations", "innovation", "innovations", 2, "lios", "an innovation follows one mod"),
    ("common/culture/name_lists", "name list", "name lists", 1, "lios", "names come from one mod's list"),
    ("common/culture", "culture piece", "culture pieces", 2, "lios", "a culture detail follows one mod"),
    ("common/landed_titles", "title", "titles", 3, "lios", "titles, their counties and de jure lands mix two maps"),
    ("common/game_rules", "game rule", "game rules", 2, "lios", "a game rule shows one mod's options"),
    ("common/lifestyle_perks", "perk", "perks", 2, "lios", "a lifestyle perk follows one mod"),
    ("common/lifestyles", "lifestyle", "lifestyles", 2, "lios", "a lifestyle follows one mod"),
    ("common/focuses", "focus", "focuses", 2, "lios", "a focus follows one mod"),
    ("common/dynasty_perks", "dynasty perk", "dynasty perks", 2, "lios", "a dynasty perk follows one mod"),
    ("common/dynasty_legacies", "dynasty legacy", "dynasty legacies", 2, "lios", "a legacy follows one mod"),
    ("common/council_positions", "council position", "council positions", 2, "lios",
     "a council seat follows one mod"),
    ("common/council_tasks", "council task", "council tasks", 2, "lios", "a council task follows one mod"),
    ("common/court_positions", "court position", "court positions", 2, "lios", "a court position follows one mod"),
    ("common/artifacts", "artifact piece", "artifact pieces", 2, "lios", "artifacts follow one mod"),
    ("common/court_amenities", "court amenity", "court amenities", 2, "lios", "a court amenity follows one mod"),
    ("common/secret_types", "secret type", "secret types", 2, "lios", "a secret follows one mod"),
    ("common/hook_types", "hook type", "hook types", 2, "lios", "a hook follows one mod"),
    ("common/factions", "faction", "factions", 2, "lios", "a faction follows one mod"),
    ("common/holdings", "holding", "holdings", 2, "lios", "a holding type follows one mod"),
    ("common/defines", "game setting", "game settings", 2, "defines",
     "the game uses one mod's value for the setting"),
    ("common/genes", "gene", "genes", 2, "lios", "faces and bodies follow one mod's genes"),
    ("common/dna_data", "DNA", "DNA entries", 1, "lios", "a character's looks follow one mod"),
    ("common/portrait_types", "portrait type", "portrait types", 1, "lios", "portraits follow one mod"),
    ("common/coat_of_arms", "coat of arms", "coats of arms", 1, "lios", "a coat of arms follows one mod"),
    ("common/nicknames", "nickname", "nicknames", 1, "lios", "a nickname follows one mod"),
    ("common/customizable_localization", "text switch", "text switches", 1, "lios",
     "a piece of generated text follows one mod"),
    ("common/flavorization", "title name", "title names", 1, "lios", "rank names follow one mod"),
    ("common/event_backgrounds", "event background", "event backgrounds", 1, "lios", "event pictures follow one mod"),
    ("common/event_themes", "event theme", "event themes", 1, "lios", "event looks follow one mod"),
    ("common/character_memory_types", "memory type", "memory types", 1, "lios", "memories follow one mod"),
    ("common/game_concepts", "game concept", "game concepts", 1, "lios", "a tooltip concept follows one mod"),
    ("common/bookmarks", "bookmark", "bookmarks", 2, "lios", "a start date follows one mod"),
    ("common/dynasties", "dynasty", "dynasties", 1, "lios", "a dynasty follows one mod"),
    ("common/dynasty_houses", "house", "houses", 1, "lios", "a house follows one mod"),
    ("common/named_colors", "named colour", "named colours", 1, "lios", "a colour follows one mod"),
    ("common/achievements", "achievement", "achievements", 1, "lios", "an achievement follows one mod"),
    ("common/casus_belli_groups", "casus belli group", "casus belli groups", 1, "lios",
     "war goals are grouped and weighed by one mod's rules"),
    ("common/scripted_rules", "scripted rule", "scripted rules", 3, "lios",
     "a rule both mods change (who can raid, marry, travel...) follows one mod"),
    ("common/travel", "travel option", "travel options", 2, "lios", "travel options follow one mod"),
    ("common/important_actions", "important action", "important actions", 1, "lios",
     "a reminder in the top bar follows one mod"),
    ("common/succession_election", "election type", "election types", 2, "lios", "an election follows one mod"),
    ("common/subject_contracts", "vassal contract", "vassal contracts", 2, "lios", "a vassal contract follows one mod"),
    ("common/task_contracts", "contract", "contracts", 2, "lios", "an adventurer contract follows one mod"),
    ("common/domiciles", "domicile piece", "domicile pieces", 2, "lios", "an estate or camp detail follows one mod"),
    ("common/legends", "legend piece", "legend pieces", 2, "lios", "a legend follows one mod"),
    ("common/great_projects", "great project", "great projects", 2, "lios", "a great project follows one mod"),
    ("common/inspirations", "inspiration", "inspirations", 2, "lios", "an inspiration follows one mod"),
    ("common/accolade_types", "accolade", "accolades", 2, "lios", "an accolade follows one mod"),
    ("common/epidemics", "epidemic", "epidemics", 2, "lios", "an epidemic follows one mod"),
    ("common/raids", "raid type", "raid types", 2, "lios", "raids follow one mod"),
    ("common/court_types", "court type", "court types", 2, "lios", "a court type follows one mod"),
    ("common/vassal_stances", "vassal stance", "vassal stances", 2, "lios", "a vassal stance follows one mod"),
    ("common/deathreasons", "death reason", "death reasons", 1, "lios", "a death reason follows one mod"),
    ("common/messages", "message", "messages", 1, "lios", "a notification follows one mod"),
    ("common", "game object", "game objects", 2, "lios", "a game object follows one mod"),
    ("history/characters", "history character", "history characters", 2, "whole",
     "historical characters are created twice (duplicates) or with mixed details"),
    ("history/titles", "title history", "title histories", 2, "lios", "who holds a title at the start follows one mod"),
    ("history/provinces", "province history", "province histories", 2, "lios",
     "a province's culture, faith and buildings at the start follow one mod"),
    ("history", "history entry", "history entries", 2, "lios", "start-of-game history follows one mod"),
    ("gui", "interface piece", "interface pieces", 2, "fios",
     "buttons, fonts or panels look like one mod's version everywhere"),
    ("gfx", "picture or model", "pictures and models", 1, "file", "a picture or model comes from one mod"),
    ("localization", "text", "texts", 1, "loc", "a few texts show one mod's wording"),
    ("localisation", "text", "texts", 1, "loc", "a few texts show one mod's wording"),
    ("map_data", "map file", "map files", 3, "file", "the map comes from one mod: a broken mix of two worlds"),
    ("music", "music entry", "music entries", 1, "lios", "music follows one mod"),
    ("sound", "sound", "sounds", 1, "file", "a sound comes from one mod"),
    ("content_source", "map source", "map sources", 2, "file", "map sources come from one mod"),
    ("fonts", "font", "fonts", 1, "file", "a font comes from one mod"),
]
_F.sort(key=lambda x: -len(x[0]))


# top-level blocks that every file adds to instead of replacing: genes by category, coat-of-arms lists
CONTAINERS = {
    "common/genes": None,                                  # every top-level key is a category
    "common/coat_of_arms/template_lists": None,
    "common/coat_of_arms/dynamic_definitions": None,
    "common/coat_of_arms/coat_of_arms": {"template", "templates"},
    "common/culture/name_equivalency": None,
    "common/defines": None,
    "common/named_colors": {"colors"},
    "common/dna_data": None,
}


def is_container(folder, key):
    hit = CONTAINERS.get(folder, ())
    return hit is None or key in hit


class FolderInfo:
    __slots__ = ("prefix", "noun", "plural", "weight", "merge", "notice")

    def __init__(self, prefix, noun, plural, weight, merge, notice):
        self.prefix, self.noun, self.plural, self.weight, self.merge, self.notice = \
            prefix, noun, plural, weight, merge, notice

    def count(self, n):
        return f"{n} {self.noun if n == 1 else self.plural}"


_FCACHE = {}


def folder_info(folder):
    """FolderInfo for a folder (or a file path) of the game's content."""
    f = (folder or "").replace("\\", "/").lower()
    hit = _FCACHE.get(f)
    if hit is None:
        for pre, noun, plural, w, merge, notice in _F:
            if f == pre or f.startswith(pre + "/"):
                hit = FolderInfo(pre, noun, plural, w, merge, notice)
                break
        else:
            hit = FolderInfo(f, "file entry", "file entries", 1, "file", "one mod's version is used")
        _FCACHE[f] = hit
    return hit


def object_folder(rel):
    """common/traits/00_traits.txt -> common/traits ; events/x/y.txt -> events"""
    if rel.startswith("events/"):
        return "events"
    return rel.rsplit("/", 1)[0]


# ------------------------------------------------------------------ definitions inside definitions
_TITLE = re.compile(r"(?m)^\s*([ekdcb]_[A-Za-z0-9_\-']+)\s*=\s*\{")


_GROUP = re.compile(r"\b(?:group|group_equivalence)\s*=\s*([A-Za-z_][\w]*)")


def nested_defs(folder, text):
    """Names defined below the top level that other scripts refer to: titles inside titles, faiths
    inside religions (before 1.20), laws inside law groups, trait groups (`has_trait = beauty_good`
    matches any trait of that group). {name: folder they count as}"""
    out = {}
    if folder == "common/landed_titles":
        for k in _TITLE.findall(SC.strip_comments(text)):
            out[k] = "common/landed_titles"
    elif folder == "common/traits":
        for k in _GROUP.findall(text):
            out[k] = "common/traits"
    elif folder == "common/laws":
        for _key, body, _ in SC.blocks(text):
            for k2, b2, _ in SC.blocks(body):
                if k2.endswith("_law") or (b2 and "modifier" in b2 and k2 not in ("modifier", "flag")):
                    out[k2] = "common/laws"
    elif folder == "common/religion/religion_types":
        for _key, body, _ in SC.blocks(text):
            for k2, b2, _ in SC.blocks(body):
                if k2 == "faiths":
                    for fk, _, _ in SC.blocks(b2):
                        out[fk] = "common/religion/faiths"
    return out


# ------------------------------------------------------------------ references in script
# key = value where the value is a single word (not a number, not yes/no); scope links like trait:brave
EVENT_ID = re.compile(r"^[A-Za-z_]\w*\.\d+$")          # namespace.123: the only dotted name


def _dotted(v):
    return "." in v and not EVENT_ID.match(v)


PAIR = re.compile(r"(?<![\w.:@$\[])([A-Za-z_][\w]*)\s*(?:=|\?=)\s*([A-Za-z_][\w.\-']*)(?![\w:.$])")
PREF = re.compile(r"(?<![\w.$])([a-z_]+):([A-Za-z_][\w\-']*)")
CALL = re.compile(r"(?<![\w.:@$])([A-Za-z_][\w]*)\s*=\s*(?:yes\b|no\b|\{)")
_EXISTS_PREF = re.compile(r"\bexists\s*=\s*([a-z_]+):([A-Za-z_][\w\-']*)")
# folders whose names collide with ordinary words too often to type a reference by them
_NOISY = ("common/game_concepts", "common/modifier_definition_formats", "common/named_colors",
          "common/event_themes", "common/message_filter_types")
_FREE_PREFIXES = {"flag", "var", "local_var", "global_var", "scope", "event_id", "list_size", "define",
                  "player", "all", "top_participant_group"}


def is_check_key(key):
    """Keys that test whether something is there (harmless when it's missing) rather than use it."""
    k = key.lower()
    return k.startswith(("has_", "is_", "can_", "any_", "trait_is_")) or k in ("exists", "not", "nor")


# a file that first checks whether another mod is there: its references to that mod are optional
_GUARD = re.compile(r"has_global_variable\s*=\s*\w*(?:loaded|installed|active|enabled|present|compat|_on)\b|"
                    r"\b\w+_(?:is_)?(?:loaded|installed|active|enabled|present)(?:_trigger)?\s*=\s*yes|"
                    r"\bis_\w+_(?:loaded|installed|active|enabled)\s*=\s*yes|"
                    r"exists\s*=\s*global_var:\w*(?:loaded|installed|active|enabled|compat)", re.I)
_COMPAT_FILE = re.compile(r"compat|patch|integration|bridge|support|hook", re.I)


_GUARD_HINTS = ("loaded", "installed", "active", "enabled", "present", "compat", "_on")


def is_guarded(text, fname):
    if _COMPAT_FILE.search(fname):
        return True
    if not any(h in text for h in _GUARD_HINTS):
        return False
    return bool(_GUARD.search(text))


# words that are never names of things (scopes and keywords: `dynasty = none`, `culture = prev`...)
SCOPE_WORDS = {"root", "prev", "this", "from", "none", "generate", "inherit", "random", "yes", "no", "all",
               "scope", "liege", "holder", "owner", "father", "mother", "player", "primary_title", "self",
               "capital", "capital_county", "faith", "culture", "religion", "dynasty", "house", "host",
               "location", "target", "actor", "recipient", "secondary_actor", "secondary_recipient", "always",
               "default", "auto", "custom", "empty", "unknown", "any", "every", "first", "last", "previous",
               "next", "current", "same", "other", "true", "false", "null", "invalid", "dummy"}


class RefModel:
    """Which keys and scope links point at which folder of the game: {key: folder}, {prefix: folder},
    and the keywords each key also takes (`dynasty = none`)."""

    def __init__(self, keys=None, prefixes=None, keywords=None):
        self.keys = dict(keys or {})
        self.prefixes = dict(prefixes or {})
        self.keywords = {k: set(v) for k, v in (keywords or {}).items()}

    @property
    def ready(self):
        return bool(self.keys)

    def refs(self, text, guarded=False):
        """{(folder, name): [uses, checks]} of the typed references in one script text (comments gone)."""
        out = {}
        if not self.keys:
            return out
        keys, prefs = self.keys, self.prefixes
        kw = self.keywords
        for k, v in PAIR.findall(text):
            fo = keys.get(k)
            if fo is None or v in SCOPE_WORDS or _dotted(v) or v.isupper() or v in kw.get(k, ()):
                continue
            slot = out.get((fo, v))
            if slot is None:
                slot = out[(fo, v)] = [0, 0]
            slot[1 if (guarded or is_check_key(k)) else 0] += 1
        if prefs:
            checked = {(p, v) for p, v in _EXISTS_PREF.findall(text)}
            for p, v in PREF.findall(text):
                fo = prefs.get(p)
                if fo is None or v in SCOPE_WORDS or v in kw.get(p + ":", ()):
                    continue
                slot = out.get((fo, v))
                if slot is None:
                    slot = out[(fo, v)] = [0, 0]
                slot[1 if (guarded or (p, v) in checked) else 0] += 1
        return out


def learn_refs(texts_by_rel, defs):
    """Learn the reference model from the game's own scripts. texts_by_rel: {rel: text (comments
    stripped)}; defs: {name: set(folders)} of everything the game defines."""
    from collections import Counter, defaultdict
    kc, ktot = defaultdict(Counter), Counter()
    pc, ptot = defaultdict(Counter), Counter()
    other = defaultdict(Counter)                       # key -> values that name nothing (keywords)
    for _rel, t in texts_by_rel.items():
        for k, v in PAIR.findall(t):
            if v in ("yes", "no") or k.isupper() or _dotted(v):
                continue
            ktot[k] += 1
            fos = defs.get(v, ())
            for fo in fos:
                kc[k][fo] += 1
            if not fos:
                other[k][v] += 1
        for p, v in PREF.findall(t):
            if p in _FREE_PREFIXES:
                continue
            ptot[p] += 1
            fos = defs.get(v, ())
            for fo in fos:
                pc[p][fo] += 1
            if not fos:
                other[p + ":"][v] += 1

    def best(c, tot, mn, share):
        out = {}
        for k, cnt in c.items():
            fo, n = cnt.most_common(1)[0]
            if fo.startswith(_NOISY):
                continue
            if n >= mn and n / max(1, tot[k]) >= share:
                out[k] = fo
        return out
    keys, prefs = best(kc, ktot, 8, 0.85), best(pc, ptot, 15, 0.9)
    kws = {}
    for k in list(keys) + [p + ":" for p in prefs]:
        vals = [v for v, n in other.get(k, {}).items() if n >= 2]
        if vals:
            kws[k] = sorted(vals)
    return RefModel(keys, prefs, kws)


# ------------------------------------------------------------------ names that tell their mod apart
def name_prefix(name):
    """'carn_sex_interaction' -> 'carn'; '' for names without a prefix part."""
    m = re.match(r"([A-Za-z][A-Za-z0-9]{1,11})_", name)
    return m.group(1).lower() if m else ""


_FILE_PREFIX = re.compile(r"^(?:[!_~\-]+|\d+_|[0z]{2,}_?|a{2,}_?|z_)+", re.I)


def file_stem(fname):
    """'zzz_cpr_carn_prostitution_triggers.txt' -> 'cpr_carn_prostitution_triggers';
    '10_chaplain_move.txt' -> 'chaplain_move' (the part that says what the file is)."""
    stem = os.path.splitext(fname)[0].lower()
    return _FILE_PREFIX.sub("", stem) or stem


def early_file(fname):
    """A file named to load first (placeholders / fallbacks): !, 0, aaa_ ..."""
    low = fname.lower()
    return bool(re.match(r"^(?:[!_~]|0+_|aaa|00)", low))


def late_file(fname):
    """A file named to load last (deliberate overrides): zzz_, zz_, z_, 99_ ..."""
    low = fname.lower()
    return bool(re.match(r"^(?:zz|z_|9{2,}|~)", low))


# ------------------------------------------------------------------ rename tables and documentation
def renames(game_dir):
    """{old name: new name} from the game's *.lookup files (traits, titles)."""
    out = {}
    for root in _roots(game_dir):
        for d, _, files in os.walk(os.path.join(root, "common")):
            for fn in files:
                if fn.endswith(".lookup") and "conversion" in fn:
                    try:
                        text = read_text(os.path.join(d, fn))
                    except OSError:
                        continue
                    for k, v in re.findall(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_]+)", SC.strip_comments(text)):
                        out.setdefault(k, v)
    return out


def info_doc(game_dir, folder, max_lines=60):
    """The game's own notes for a folder (common/traits/_traits.info), shortened; '' if none."""
    for root in _roots(game_dir):
        d = os.path.join(root, *folder.split("/"))
        try:
            names = sorted(fn for fn in os.listdir(d) if fn.endswith(".info"))
        except OSError:
            continue
        for fn in names:
            try:
                text = read_text(os.path.join(d, fn)).strip()
            except OSError:
                continue
            lines = text.splitlines()
            return "\n".join(lines[:max_lines]) + (f"\n# ... ({len(lines) - max_lines} more lines in {fn})"
                                                   if len(lines) > max_lines else "")
    return ""


def _roots(game_dir):
    if not game_dir or not os.path.isdir(game_dir):
        return []
    roots = [os.path.join(game_dir, d) for d in ("game", "jomini") if os.path.isdir(os.path.join(game_dir, d))]
    return roots or [game_dir]


# ------------------------------------------------------------------ learning, cached per game version
def load_model(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return RefModel(d.get("keys"), d.get("prefixes"), d.get("keywords")), d
    except Exception:
        return None, {}


def save_model(path, model, extra=None):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        d = {"keys": model.keys, "prefixes": model.prefixes, "at": time.time(),
             "keywords": {k: sorted(v) for k, v in model.keywords.items()}}
        d.update(extra or {})
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(path + ".tmp", path)
    except Exception:
        pass
