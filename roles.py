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
            return "ui"
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
                         r"turkish|italian|czech|ukrainian|deutsch|español|français|中文|한국어)", re.I)
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
    def __init__(self, role, why, secondary, focus, attrs):
        self.role, self.why, self.secondary, self.focus, self.attrs = role, why, secondary, focus, attrs


def classify(f, facts, mentions_name):
    """f: analysis.ModFacts. facts: all ModFacts. mentions_name(text, other) -> bool.
    Returns a RoleResult."""
    m = f.mod
    tags = {t.lower() for t in m.tags}
    name = f.name
    files = f.files
    if not files:
        return RoleResult(UNKNOWN, "no readable files", [], "", [])
    weights = {}
    binary = sum(1 for r in files if not r.endswith(TEXT_EXT)) / len(files)
    script_files = sum(1 for r in files if r.startswith(("common/", "events/", "history/")))
    mostly_binary = binary >= 0.7 and script_files <= 3
    for rel in files:
        a = area(rel)
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
    attrs = []
    touches_checksum = any(r.startswith(CHECKSUM_TOPS) for r in files)
    attrs.append(("achievements", not touches_checksum))
    targets = [o for o in facts if o is not f and mentions_name(name, o)]
    builds_on = getattr(f, "builds_on", {})              # other mod key -> number of its things this one uses
    used_by = getattr(f, "used_by", {})

    def result(rid, why):
        sec = [BY_ID[_AREA_ROLE[a]] for a, s in ordered if s >= 0.15 and _AREA_ROLE.get(a) and _AREA_ROLE[a] != rid]
        sec = list(dict.fromkeys(sec))[:3]
        return RoleResult(BY_ID[rid], why, sec, focus, attrs)

    # ---- strong signals
    tc_paths = [p for p in m.replace_paths if p.startswith(("history", "map_data", "common/landed_titles",
                                                             "common/culture", "common/religion"))]
    if _TC_RX.search(name) or "total conversion" in tags or (tc_paths and len(tc_paths) >= 2):
        return result("total_conversion", "replaces the game's " + ", ".join(tc_paths[:3]) if tc_paths
                      else "a total conversion (by its name/tags)")
    map_core = [r for r in files if r.startswith("map_data/") and r.rsplit("/", 1)[-1] in
                ("definition.csv", "provinces.png", "heightmap.heightmap", "default.map", "adjacencies.csv")]
    if map_core:
        if tc_paths or count("history/") > 50 and count("common/landed_titles/"):
            return result("total_conversion", "new map plus its own history and titles")
        return result("map", "changes the map itself (" + ", ".join(r.rsplit('/', 1)[-1] for r in map_core[:3]) + ")")
    if loc_files / n_files >= 0.9 and (langs - {"english"} or _LANG_WORDS.search(name) or "translation" in tags):
        other = sorted(langs - {"english"})
        return result("translation", "only texts" + (f" ({', '.join(other[:3])})" if other else ""))
    light_overrides = f.overrides >= 25 and f.overrides >= 0.5 * n_files and f.light_override_share >= 0.6
    if _FIX_RX.search(name) and not _PATCH_RX.search(name.replace("Patch", "")) or \
            ("fixes" in tags and light_overrides):
        return result("fix", f"fixes the game's own files ({f.overrides} vanilla files, mostly small edits)")
    if m.dependencies and (len(m.dependencies) >= 2 or _PATCH_RX.search(name)):
        return result("compatch", "declares it needs " + ", ".join(f'"{d}"' for d in m.dependencies[:3]))
    if _PATCH_RX.search(name) and len(targets) >= 1:
        return result("compatch", "named as a patch for " + ", ".join(f'"{t.name}"' for t in targets[:2]))
    strong_base = [k for k, n in builds_on.items() if n >= 5]
    if len(strong_base) >= 2 and n_files <= 60:
        return result("compatch", f"uses things defined by {len(strong_base)} other mods")
    if m.dependencies or (targets and _SUB_RX.search(name)) or (len(strong_base) == 1 and
                                                                 builds_on[strong_base[0]] >= 10):
        base = m.dependencies[:1] or [t.name for t in targets[:1]] or \
            [facts_name(facts, strong_base[0])]
        return result("submod", f'an add-on for "{base[0]}"')
    lib_score = share.get("script", 0)
    if _LIB_RX.search(name) or "framework" in tags or (lib_score >= 0.6 and sum(used_by.values()) >= 10):
        return result("framework", "shared scripted code" + (f" that {len(used_by)} other mod(s) use" if used_by else ""))
    areas_big = [a for a, s in share.items() if s >= 0.1 and a not in ("loc", "misc")]
    if f.overrides >= 60 or (len(areas_big) >= 5 and n_files >= 150) or "overhaul" in tags:
        return result("overhaul", f"touches {len(areas_big)} parts of the game and replaces {f.overrides} of its files")
    top_area, top_share = ordered[0]
    specific = top_share >= 0.6 and top_area in ("balance", "events", "culture", "history", "portraits", "graphics")
    if not specific and ((_UTIL_RX.search(name) and n_files <= 40) or
                         ({"utilities", "cheats"} & tags and n_files <= 12)):
        return result("utility", "a convenience mod (automates or unlocks something)")
    # ---- by the biggest part of the work. Windows and pictures usually serve a feature, so a mod is
    # only called "Interface"/"Graphics" when they are most of it or nothing else is there.
    content = {"gameplay", "interactions", "events", "culture", "history", "balance", "script", "map"}
    has_content = any(share.get(a, 0) >= 0.2 for a in content)
    for a, s in ordered:
        rid = _AREA_ROLE.get(a)
        if rid in ("ui", "graphics", "audio") and s < 0.5 and has_content:
            continue
        if rid:
            why = f"most of its work is {AREA_NAMES.get(a, a)} ({s:.0%})"
            if rid == "gameplay" and share.get("script", 0) >= 0.4 and a == "script":
                why = "mostly scripted code"
            return result(rid, why)
    return result("gameplay", "regular content")


def facts_name(facts, key):
    for o in facts:
        if o.key == key:
            return o.name
    return key


_AREA_ROLE = {"gameplay": "gameplay", "interactions": "interactions", "culture": "culture", "history": "history",
              "balance": "balance", "script": "gameplay", "events": "events", "portraits": "portraits",
              "coa": "coa", "ui": "ui", "graphics": "graphics", "map": "map", "audio": "audio"}
