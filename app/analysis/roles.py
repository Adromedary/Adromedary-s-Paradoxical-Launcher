"""
What kind of mod is this? Roles, their mini icons, and the classifier.

A mod's files are sorted into AREAS by where the game reads them (common/traits -> gameplay,
gfx/portraits -> portraits, gui -> interface ...). Each file counts by how much the mod actually
changed in it (lines that differ from the game's own copy), so a 40 MB gene file doesn't outweigh
a hundred events. The primary role then comes from strong signals first (replace_path, map files,
fix packs, compatches, dependencies, other mods building on it) and otherwise from the biggest area.
Secondary roles are other areas with a real share of the work.
"""
import math
import re

# ------------------------------------------------------------------ roles
class Role:
    def __init__(self, rid, name, color, glyph, rank, blurb):
        self.id, self.name, self.color, self.glyph, self.rank, self.blurb = rid, name, color, glyph, rank, blurb


# rank = conventional place in a load order (top first). Only matters between mods that share files.
ROLES = [
    Role("fix", "Fix pack", "#2f9e44", "✚", 0, "fixes the game's own files; other mods' versions should win"),
    Role("total_conversion", "Total conversion", "#c92a2a", "✦", 1, "replaces large parts of the game world"),
    Role("map", "Map", "#a5682a", "▦", 2, "changes the map (provinces, terrain, titles)"),
    Role("framework", "Framework", "#5f3dc4", "⚙", 3, "shared code other mods build on"),
    Role("overhaul", "Overhaul", "#d9480f", "⚒", 4, "changes many of the game's systems at once"),
    Role("history", "History", "#8d6e63", "⌛", 5, "characters, titles, bookmarks and start dates"),
    Role("culture", "Cultures & faiths", "#c2255c", "❖", 6, "cultures, traditions, faiths, holy orders"),
    Role("gameplay", "Gameplay", "#1971c2", "⚔", 7, "new or changed mechanics: traits, laws, buildings, schemes"),
    Role("interactions", "Decisions & interactions", "#0c8599", "☛", 8, "decisions and character interactions"),
    Role("balance", "Balance tweak", "#5c940d", "⚖", 9, "numbers: defines, game rules, values, modifiers"),
    Role("events", "Events & flavor", "#e67700", "✉", 10, "events, story cycles, on-actions"),
    Role("utility", "Utility", "#495057", "⚡", 11, "a small convenience or cheat"),
    Role("coa", "Coats of arms", "#862e9c", "⚑", 12, "heraldry"),
    Role("portraits", "Portraits & genes", "#d6336c", "☺", 13, "faces, clothes, genes, ethnicities"),
    Role("graphics", "Graphics", "#1098ad", "◐", 14, "textures, models, icons, effects"),
    Role("ui", "Interface", "#3b5bdb", "▣", 15, "windows and widgets (gui files)"),
    Role("audio", "Music & sound", "#7048e8", "♫", 16, "music and sound"),
    Role("submod", "Submod / add-on", "#0b7285", "⊕", 17, "an add-on for another mod"),
    Role("compatch", "Compatibility patch", "#2b8a3e", "⇄", 18, "makes other mods work together"),
    Role("translation", "Translation", "#868e96", "Aä", 19, "localisation only"),
]
BY_ID = {r.id: r for r in ROLES}
UNKNOWN = Role("unknown", "Unknown", "#868e96", "?", 7, "couldn't read its files")

# ------------------------------------------------------------------ areas
_COMMON = {
    "interactions": "decisions decision_group_types character_interactions character_interaction_categories "
                    "scripted_guis important_actions",
    "culture": "culture religion holy_orders flavorization nicknames dynasty_house_mottos "
               "dynasty_house_motto_inserts",
    "history": "bookmarks bookmark_portraits dynasties dynasty_houses landed_titles legends",
    "balance": "defines game_rules script_values modifiers opinion_modifiers named_colors scripted_costs",
    "script": "scripted_effects scripted_triggers scripted_modifiers scripted_lists scripted_relations "
              "scripted_rules scripted_animations customizable_localization trigger_localization "
              "effect_localization",
    "events": "on_action event_backgrounds event_themes event_transitions event_2d_effects story_cycles "
              "character_memory_types",
    "portraits": "genes dna_data portrait_types ethnicities",
    "coa": "coat_of_arms",
    "ui": "modifier_icons message_filter_types message_group_types messages console_groups connection_arrows "
          "suggestions ruler_objective_advice_types tutorial_lessons tutorial_lesson_chains game_concepts "
          "modifier_definition_formats menu_scenes accolade_icons",
}
COMMON_AREA = {sub: area for area, subs in _COMMON.items() for sub in subs.split()}

AREA_NAMES = {"gameplay": "mechanics", "interactions": "decisions & interactions", "culture": "cultures & faiths",
              "history": "history & titles", "balance": "balance values", "script": "scripted code",
              "events": "events", "portraits": "portraits", "coa": "coats of arms", "ui": "interface",
              "graphics": "graphics", "map": "map", "audio": "audio", "loc": "texts", "misc": "other files"}
CHECKSUM_TOPS = ("common/", "events/", "history/", "map_data/", "gui/", "localization/", "localisation/",
                 "data_binding/", "gfx/court_scene/scene_settings/")


def area(rel):
    """Which part of the game a file belongs to."""
    p = rel.split("/")
    top = p[0]
    if top == "common":
        return COMMON_AREA.get(p[1] if len(p) > 2 else "", "gameplay")
    if top == "events":
        return "events"
    if top == "history":
        return "culture" if len(p) > 1 and p[1] in ("cultures", "faiths") else "history"
    if top in ("map_data", "content_source"):
        return "map"
    if top == "gfx":
        sub = p[1] if len(p) > 2 else ""
        if sub == "portraits" or (sub == "models" and len(p) > 3 and p[2] == "portraits"):
            return "portraits"
        if sub == "coat_of_arms":
            return "coa"
        if sub in ("interface", "cursors"):
            return "ui" if rel.endswith(TEXT_EXT) else "graphics"     # icons are pictures, .gfx lists are UI
        return "graphics"
    if top in ("gui", "data_binding", "fonts", "notifications"):
        return "ui"
    if top in ("localization", "localisation"):
        return "loc"
    if top in ("music", "sound"):
        return "audio"
    return "misc"


TEXT_EXT = (".txt", ".gui", ".gfx", ".yml", ".asset", ".csv", ".shader", ".fxh", ".settings")


def file_weight(units, rel, mostly_binary=False):
    """How much one file says about what a mod is: grows with the work in it, but slowly.
    Pictures and models are supporting material for most mods (every new trait has an icon), so they
    count little unless the mod is mostly pictures."""
    if not rel.endswith(TEXT_EXT):
        return 1.0 if mostly_binary else 0.15
    w = 1.0 + math.sqrt(min(units, 4000)) / 4.0
    if rel.startswith(("localization/", "localisation/")):
        w *= 0.35                         # every mod has texts; they say little about its kind
    elif rel.endswith((".gui", ".gfx")):
        w = min(w, 3.0) * 0.6             # content mods bring (often whole copied) windows for their features
    return w


LANGS = ("english", "french", "german", "spanish", "russian", "korean", "simp_chinese", "chinese", "japanese",
         "polish", "braz_por", "portuguese", "turkish", "italian", "czech", "ukrainian")
_LANG_WORDS = re.compile(r"\b(translation|traduc|übersetz|ubersetz|перевод|localisation|localization|русск|"
                         r"french|german|spanish|russian|korean|chinese|japanese|polish|portuguese|brazilian|"
                         r"turkish|italian|czech|ukrainian|arabic|persian|deutsch|español|français|中文|한국어|تعريب|عربي)", re.I)
_FIX_RX = re.compile(r"\bunofficial\b|\bfix\s*-?\s*pack\b|\bbug\s*-?\s*fix(es)?\b|\bfixes\b|\bcommunity\s+patch\b"
                     r"|\bfixed?\b.*\bvanilla\b", re.I)
_TC_RX = re.compile(r"\btotal\s+conversion\b", re.I)
_LIB_RX = re.compile(r"\b(framework|library|lib|api|core|common\s+code|toolkit|base\s+mod)\b", re.I)
_PATCH_RX = re.compile(r"\b(com-?patch|compatibility|compat|patch\s+for|integration|bridge|fix\s+for)\b|"
                       r"\s[x+]\s", re.I)
_SUB_RX = re.compile(r"\b(sub-?mod|add-?on|addon|expansion\s+for|for\s+\w+)\b", re.I)
_UTIL_RX = re.compile(r"\b(unlock(ed)?|cheat|instant|debug|toggle|no\s+\w+\s+limit|auto(matic)?|manager|"
                      r"utilit(y|ies)|tool|helper|quick|mass)\b", re.I)


class RoleResult:
    def __init__(self, role, why, secondary, focus, attrs, evidence=None, manual=False):
        self.role, self.why, self.secondary, self.focus, self.attrs = role, why, secondary, focus, attrs
        self.evidence = evidence or []          # [(role id, points, reason)], strongest first
        self.manual = manual                    # set by you (Library > Set role)

    def reasons(self, rid=None, n=4):
        """The strongest reasons for a role (the chosen one by default); the shares of the work in one
        sentence first."""
        rid = rid or self.role.id
        out = self.why.split("; ") if rid == self.role.id and not self.manual and self.why else []
        merged = any("of its work is" in x for x in out)
        for r, pts, why in self.evidence:
            if r == rid and why not in out and not (merged and "of its work is" in why):
                out.append(why)
        return out[:n]


# Workshop categories (the author's own ticks) and the role each one points to
TAG_ROLE = {
    "total conversion": "total_conversion", "map": "map", "fixes": "fix", "translation": "translation",
    "utilities": "utility", "graphics": "graphics", "portraits": "portraits", "interface": "ui", "sound": "audio",
    "music": "audio", "balance": "balance", "events": "events", "decisions": "interactions",
    "character interactions": "interactions", "culture": "culture", "religion": "culture",
    "historical": "history", "alternative history": "history", "gameplay": "gameplay", "warfare": "gameplay",
    "character focuses": "gameplay", "schemes": "gameplay", "economy": "gameplay", "military": "gameplay",
    "submod": "submod", "overhaul": "overhaul", "framework": "framework", "cheats": "utility",
}
_DESC_PATCH = re.compile(r"\b(this is a )?(compatibility patch|compatch|compat patch)\b", re.I)
_DESC_SUB = re.compile(r"\b(this is a )?sub-?mod\b|\badd-?on for\b", re.I)
_DESC_LIB = re.compile(r"\b(framework|library) (for|that) (other )?mod", re.I)
_DESC_TRANS = re.compile(r"\b(translation|translated|localisation|localization|перевод)\b", re.I)


def classify(f, facts, mentions_name):
    """What kind of mod f is (f: analysis.ModFacts, facts: all of them, mentions_name(text, other) -> bool).

    Every clue adds points to a role: what its files change (the most), what its files prove (a new map,
    replaced history, light edits of the game's own files, declared dependencies, other mods' names it
    uses), its title, its Workshop description and the categories its author ticked. The author's ticks
    count less the more of them there are (a mod ticking ten categories says little with each), and a
    Total conversion needs proof in the files: a tick alone never makes one. Returns a RoleResult whose
    evidence explains the choice."""
    m = f.mod
    name = f.name
    files = f.files
    if not files:
        return RoleResult(UNKNOWN, "no readable files", [], "", [])
    weights = {}
    binary = sum(1 for r in files if not r.endswith(TEXT_EXT)) / len(files)
    script_files = sum(1 for r in files if r.startswith(("common/", "events/", "history/")))
    mostly_binary = binary >= 0.7 and script_files <= 3
    windows = sum(1 for r in files if r.startswith("gui/"))
    for rel in files:
        a = area(rel)
        if a == "graphics" and windows >= 5 and rel.startswith("gfx/interface/"):
            a = "ui"                         # an interface mod's own icons belong to its windows
        weights[a] = weights.get(a, 0.0) + file_weight(f.units.get(rel, 1), rel, mostly_binary)
    total = sum(weights.values()) or 1.0
    share = {a: w / total for a, w in weights.items()}
    ordered = sorted(share.items(), key=lambda kv: -kv[1])
    focus = ", ".join(AREA_NAMES.get(a, a) for a, s in ordered[:3] if s >= 0.08)
    n_files = len(files)
    count = lambda *tops: sum(1 for r in files if r.startswith(tops))
    loc_files = count("localization/", "localisation/")
    langs = {p.split("/")[1] for p in files if p.startswith(("localization/", "localisation/")) and p.count("/") >= 2}
    langs |= {p.split("/")[2] for p in files if p.startswith(("localization/replace/", "localisation/replace/"))
              and p.count("/") >= 3}
    attrs = [("achievements", not any(r.startswith(CHECKSUM_TOPS) for r in files))]
    targets = [o for o in facts if o is not f and mentions_name(name, o)]
    builds_on = getattr(f, "builds_on", {})
    used_by = getattr(f, "used_by", {})
    desc = (getattr(f, "description", "") or "")[:1500]
    tags = [t for t in dict.fromkeys(list(m.tags) + list(getattr(f, "ws_tags", []) or []))
            if not re.match(r"^\d+\.\d+", t) and t.lower() != "older"]
    ev = []

    def add(rid, pts, why):
        if pts > 0:
            ev.append((rid, round(pts, 2), why))

    # ---- what its files change (the backbone): the share of the work in each part of the game
    content = {"gameplay", "interactions", "events", "culture", "history", "balance", "script", "map"}
    content_share = sum(share.get(a, 0) for a in content)
    has_content = content_share >= 0.25
    small = 0.5 + 0.5 * min(1.0, n_files / 6)          # a mod of one or two files proves less by them
    for a, s in ordered:
        rid = _AREA_ROLE.get(a)
        if not rid or s < 0.05:
            continue
        pts = 10 * s * small
        if rid in ("ui", "graphics", "audio") and s < 0.5 and has_content:
            pts *= 0.45                      # windows and pictures usually serve a feature
        add(rid, pts, f"{s:.0%} of its work is {AREA_NAMES.get(a, a)}")

    # ---- what its files prove
    world = ("history", "map_data", "common/landed_titles", "common/culture", "common/religion")
    tc_paths = [p for p in m.replace_paths if p.startswith(world)]
    map_core = [r for r in files if r.startswith("map_data/") and r.rsplit("/", 1)[-1] in
                ("definition.csv", "provinces.png", "heightmap.heightmap", "default.map", "adjacencies.csv")]
    tc_proof = len(tc_paths) >= 2 or (map_core and (tc_paths or count("history/") > 50
                                                    and count("common/landed_titles/")))
    if tc_proof:
        add("total_conversion", 16, "replaces the game's " + ", ".join(tc_paths[:3]) if tc_paths
            else "brings a new map with its own history and titles")
    elif map_core:
        add("map", 14, "changes the map itself (" + ", ".join(r.rsplit('/', 1)[-1] for r in map_core[:3]) + ")")
    loc_share = loc_files / n_files
    if loc_share >= 0.9:
        other = sorted(langs - {"english"})
        add("translation", 14, "only texts" + (f" ({', '.join(other[:3])})" if other else
                                               " (it rewrites the game's texts)"))
    light = f.overrides >= 25 and f.overrides >= 0.5 * n_files and f.light_override_share >= 0.6 and \
        content_share >= 0.4                         # light edits of scripts, not of pictures or texts
    if light:
        add("fix", 7, f"small edits to {f.overrides} of the game's own files")
    if m.dependencies:
        if len(m.dependencies) >= 2:
            add("compatch", 9, "declares it needs " + ", ".join(f'"{d}"' for d in m.dependencies[:3]))
        else:
            add("submod", 7, f'declares it needs "{m.dependencies[0]}"')
    strong_base = [k for k, n in builds_on.items() if n >= 5]
    if len(strong_base) >= 2 and n_files <= 60:
        add("compatch", 7, f"uses things defined by {len(strong_base)} other mods")
    elif len(strong_base) == 1 and builds_on[strong_base[0]] >= 10:
        add("submod", 6, f'uses {builds_on[strong_base[0]]} things only "{facts_name(facts, strong_base[0])}" defines')
    if share.get("script", 0) >= 0.6 and sum(used_by.values()) >= 10:
        add("framework", 8, f"scripted code that {len(used_by)} other mod(s) use")
    areas_big = [a for a, s in share.items() if s >= 0.1 and a not in ("loc", "misc")]
    if (f.overrides >= 60 and f.overrides >= 0.25 * n_files or f.overrides >= 200) and loc_share < 0.9:
        add("overhaul", 5 + min(4, f.overrides / 60), f"replaces {f.overrides} of the game's files")
    if len(areas_big) >= 5 and n_files >= 150:
        add("overhaul", 5, f"changes {len(areas_big)} parts of the game")

    # ---- its title
    if _TC_RX.search(name):
        add("overhaul" if not tc_proof else "total_conversion", 3, "calls itself a total conversion")
    if _FIX_RX.search(name) and not _PATCH_RX.search(name.replace("Patch", "")):
        add("fix", 5 + (3 if light else 0), "a fix by its name")
    if _LANG_WORDS.search(name) and loc_share >= 0.5:
        add("translation", 6, "a translation by its name")
    if _PATCH_RX.search(name):
        if targets:
            add("compatch", 7, "named as a patch for " + ", ".join(f'"{t.name}"' for t in targets[:2]))
        elif m.dependencies:
            add("compatch", 4, "named as a patch")
    if targets and _SUB_RX.search(name):
        add("submod", 5, f'named as an add-on for "{targets[0].name}"')
    if _LIB_RX.search(name):
        add("framework", 5, "a framework by its name")
    specific = ordered[0][1] >= 0.6 and ordered[0][0] in ("balance", "events", "culture", "history", "portraits",
                                                          "graphics")
    if _UTIL_RX.search(name) and n_files <= 40 and not specific:
        add("utility", 4, "a convenience by its name")

    # ---- its Workshop description
    if desc:
        if _DESC_PATCH.search(desc[:400]) and (targets or m.dependencies or strong_base):
            add("compatch", 4, "its description calls it a compatibility patch")
        if _DESC_SUB.search(desc[:400]) and (targets or m.dependencies or strong_base):
            add("submod", 3, "its description calls it a submod")
        if _DESC_TRANS.search(desc[:300]) and loc_share >= 0.6:
            add("translation", 4, "its description calls it a translation")
        if _DESC_LIB.search(desc[:600]):
            add("framework", 3, "its description calls it a framework for other mods")

    # ---- the categories its author ticked: worth less the more there are
    if tags:
        each = 3.0 if len(tags) <= 2 else 6.0 / len(tags)
        for t in tags:
            rid = TAG_ROLE.get(t.lower())
            if not rid:
                continue
            pts = each
            if rid == "total_conversion" and not tc_proof:
                continue                     # never on a tick alone (see below)
            if rid == "map" and not map_core:
                continue                     # "Map" is often ticked by mods that only touch map graphics
            if rid == "translation" and loc_share < 0.6:
                continue
            if rid == "fix" and not light:
                pts *= 0.5
            if rid in ("utility", "overhaul") and len(tags) > 4:
                pts *= 0.5
            add(rid, pts, f"its author ticked \"{t}\"" + (f" (one of {len(tags)})" if len(tags) > 3 else ""))

    # ---- decide
    score = {}
    for rid, pts, _ in ev:
        score[rid] = score.get(rid, 0.0) + pts
    if not score:
        return RoleResult(BY_ID["gameplay"], "regular content", [], focus, attrs, [("gameplay", 1, "regular content")])
    best = max(score, key=lambda r: (score[r], -BY_ID[r].rank))
    ev.sort(key=lambda e: (e[0] != best, -score.get(e[0], 0), -e[1]))
    sec = [BY_ID[r] for r, v in sorted(score.items(), key=lambda kv: -kv[1])
           if r != best and v >= 0.4 * score[best]][:3]
    notes = []
    if any(t.lower() == "total conversion" for t in tags) and not tc_proof:
        notes.append(("note", 0, "its author ticks \"Total Conversion\", but its files don't replace the game "
                                 "world, so it isn't treated as one"))
    parts = [(a, sh) for a, sh in ordered if _AREA_ROLE.get(a) == best and sh >= 0.05]
    reasons = []
    if parts:                         # "29% of its work is mechanics and scripted code"
        reasons.append(f"{sum(sh for _, sh in parts):.0%} of its work is " +
                       " and ".join(AREA_NAMES.get(a, a) for a, _ in parts))
    reasons += [why for r, pts, why in ev if r == best and "of its work is" not in why][:2 if not parts else 1]
    return RoleResult(BY_ID[best], "; ".join(reasons) or "regular content", sec, focus, attrs, ev + notes)


def facts_name(facts, key):
    for o in facts:
        if o.key == key:
            return o.name
    return key


_AREA_ROLE = {"gameplay": "gameplay", "interactions": "interactions", "culture": "culture", "history": "history",
              "balance": "balance", "script": "gameplay", "events": "events", "portraits": "portraits",
              "coa": "coa", "ui": "ui", "graphics": "graphics", "map": "map", "audio": "audio"}
