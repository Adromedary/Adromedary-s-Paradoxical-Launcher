"""A compatch report: everything needed to write a compatibility patch for two mods, as one Markdown
file, ending with a ready prompt to paste into an AI chat (Claude, ChatGPT...) together with the file.

The report is built so that a modder (or an AI) can write the patch without guessing:
  * what the two mods are and how they relate (one builds on the other, one only adds extras...);
  * every problem between them, with what you notice in game;
  * the exact rules the game uses for each kind of thing involved (whole file, object by object with the
    last or the first file name winning, appended lists, text keys), with the game's own notes on those
    folders (its _*.info files);
  * for every object they fight over: who wins now and why, the game's own version, each mod's version,
    and what each mod changed compared with the game (as a diff), plus the names each version relies on
    that only its own mod defines (so the patch has to require both mods);
  * a concrete plan: which files the patch needs, at which paths and with which file names, and the
    descriptor;
  * a prompt with strict rules for the AI: keep both mods' features, follow the plan, invent nothing.
"""
import difflib
import os
import re
import time

import analysis as A
import gamedb as GD
import script as SC
from installer import read_text

MAX_OBJECT_LINES = 140             # a mod's own copy is printed in full up to this size (else its diff does)
MAX_OBJECTS = 40                   # objects shown; the rest are listed
CODE_BUDGET = 16000                # code lines in one report; past it, code is shortened (and says so)
SHORT_LINES = 120                  # what a shortened piece keeps

MERGE_TEXT = {
    "lios": "object by object; when two files define the same object, the file whose name sorts LAST wins "
            "(whatever the mod order)",
    "fios": "object by object; the file whose name sorts FIRST wins (GUI types and templates)",
    "whole": "objects can't be replaced one by one: the same ID twice is a duplicate (error), one copy is lost",
    "append": "`events`, `random_events` and `on_actions` lists add up; `effect` and `trigger` blocks replace "
              "each other (and log errors)",
    "defines": "value by value; each value comes from the file whose name sorts last",
    "loc": "text keys: a key defined twice is an error and only one text shows, unless one file sits in a "
           "`replace` folder (then it wins)",
    "file": "only the whole file can be replaced; the mod loaded last provides it",
}


def _read(path):
    try:
        return read_text(path) if path else ""
    except OSError:
        return ""


class _Budget:
    """Code is printed whole, so a patch can be written from the report alone, until the report gets too
    big for an AI chat; after that pieces are shortened with a marker saying where the rest is."""

    def __init__(self, n=CODE_BUDGET):
        self.left = n
        self.cut = 0

    def take(self, lines, where=""):
        if len(lines) <= self.left or len(lines) <= SHORT_LINES:
            self.left -= len(lines)
            return lines
        self.cut += 1
        keep = lines[:SHORT_LINES]
        self.left -= len(keep)
        return keep + [f"# SHORTENED: {len(lines) - SHORT_LINES} more lines" + (f" (full text: {where})" if where
                                                                                   else "")]


_BUDGET = _Budget()


def _cut(text, where=""):
    return "\n".join(_BUDGET.take(text.splitlines(), where))


def _diff(old, new, a_name, b_name, where=""):
    """Unified diff of two texts (comments and spacing kept as written), whole while the budget lasts."""
    out = list(difflib.unified_diff(old.splitlines(), new.splitlines(), a_name, b_name, n=3, lineterm=""))
    if not out:
        return ""
    return "\n".join(_BUDGET.take(out, where))


def _gui_block(text, name):
    m = re.search(r"(?m)^[ \t]*(template|type)\s+" + re.escape(name) + r"\b[^{\n]*\{", text)
    if not m:
        return ""
    end = SC._skip_block(text, text.index("{", m.start()))
    return text[m.start():end].strip("\n")


def _locate(f, folder, name):
    """(relative path, text of the object) of one object in one mod, or ('', '')."""
    m = f.mod
    if folder == "defines":
        cat, _, key = name.partition(".")
        hit = f.define_vals.get((cat, key))
        return (hit[0], f"{cat} = {{\n\t{key} = {hit[1]}\n}}") if hit else ("", "")
    if folder == "gui":
        hit = f.gui_defs.get(name)
        if not hit:
            return "", ""
        return hit[0], _gui_block(_read(m.paths.get(hit[0])), name)
    if folder.startswith("common/on_action") and name in f.on_actions:
        rel = f.on_actions[name][0]
        return rel, SC.object_text(_read(m.paths.get(rel)), name)
    if "/" in folder and os.path.splitext(folder)[1]:                # a shared file: (rel, object)
        rel = folder
        if rel not in f.files:
            return "", ""
        return (rel, SC.object_text(_read(m.paths.get(rel)), name)) if name else (rel, "")
    fname = f.defines.get((folder, name))
    if fname:
        rel = f"{folder}/{fname}" if folder != "events" else next(
            (r for r in f.files if r.startswith("events/") and r.endswith("/" + fname)), "")
        return rel, SC.object_text(_read(m.paths.get(rel)), name)
    return "", ""


def _vanilla(van, folder, name, rel_hint=""):
    if van is None or not van.roots:
        return "", ""
    if folder == "defines":
        cat, _, key = name.partition(".")
        v = van.define_values().get((cat, key))
        return ("common/defines", f"{cat} = {{\n\t{key} = {v}\n}}") if v is not None else ("", "")
    if folder == "gui":
        return "", ""
    rels = [rel_hint] if rel_hint else []
    if os.path.splitext(folder)[1]:
        rels = [folder]
    for rel in rels:
        p = van.path(rel)
        if p:
            t = SC.object_text(_read(p), name) if name else _read(p)
            if t:
                return rel, t
    if "/" in folder and not os.path.splitext(folder)[1] and name:
        if van._index is None:
            van.path("")
        for rel, full in van._index.items():
            if rel.startswith(folder + "/") and rel.endswith(".txt") and A.object_folder(rel) == folder:
                text = _read(full)
                if re.search(r"(?m)^[ \t]*" + re.escape(name) + r"\s*=", text):
                    return rel, SC.object_text(text, name)
    return "", ""


def _own_names(text, f, other, vanilla_all):
    """Names this version of an object uses that only its own mod defines (not the game, not the other mod):
    the patch has to load with that mod."""
    if not text:
        return []
    out = []
    for ident in sorted(SC.identifiers(text)):
        if ident in f.provides and ident not in other.provides and ident not in vanilla_all and len(ident) >= 5:
            out.append(ident)
    return out[:20]


def _winner(an, fa, fb, folder, name):
    """(winner name, reason) for one object, by the game's rules."""
    for o in an.objects.get(tuple(sorted((fa.key, fb.key))), []):
        if o[0] == name and o[1] == folder:
            win = an.facts[o[5]]
            mode = GD.folder_info(folder).merge
            rule = "first file name wins" if mode == "fios" else "last file name wins"
            return win.name, f"{rule}: {o[2]} vs {o[3]}"
    return "", ""


def _rival_files(fa, fb, folder, names):
    """The file names the two mods define these objects in (the patch's file must beat all of them)."""
    out = set()
    for f in (fa, fb):
        for n in names:
            if folder == "gui":
                hit = f.gui_defs.get(n)
                if hit:
                    out.add(hit[0].rsplit("/", 1)[1])
            elif folder == "defines":
                cat, _, key = n.partition(".")
                hit = f.define_vals.get((cat, key))
                if hit:
                    out.add(hit[0].rsplit("/", 1)[1])
            else:
                fn = f.defines.get((folder, n))
                if fn:
                    out.add(fn)
    return out


def _last_name(rivals, slug):
    """A file name (without extension) that sorts after every rival: zzz_..., with more z's if needed."""
    name = f"zzz_{slug}_compatch"
    while any(name + ".txt" <= r.lower() for r in rivals):
        name = "z" + name
    return name


def _first_name(rivals, slug):
    """A file name that sorts before every rival (GUI types and templates: the first one wins)."""
    name = f"00_{slug}_compatch"
    if any(name + ".gui" >= r.lower() for r in rivals):
        name = "!" + name
    return name


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", A.clean_title(s).lower()).strip("_")[:24] or "mod"


def build(an, issues, ka, kb, order=(), game="", game_version="", van=None, app_name=""):
    """The report for the pair (ka, kb) as Markdown text. issues: their problems in the current playset."""
    global _BUDGET
    _BUDGET = _Budget()
    fa, fb = an.facts[ka], an.facts[kb]
    pos = {k: i + 1 for i, k in enumerate(order)}
    vanilla_all = van.all_names() if van is not None and van.roots else set()
    patch_slug = f"{_slug(fa.name)}_x_{_slug(fb.name)}"
    L = []
    w = L.append
    w(f"# Compatch report: {fa.name} + {fb.name}")
    w("")
    w(f"Made by {app_name or 'the launcher'} on {time.strftime('%Y-%m-%d %H:%M')}"
      + (f" for {game} {game_version}" if game else "") + ".")
    w("")
    # ---- the mods
    w("## The two mods")
    w("")
    w("| | Mod A | Mod B |")
    w("|---|---|---|")
    w(f"| Name | {fa.name} | {fb.name} |")
    w(f"| Workshop ID | {fa.wid or '-'} | {fb.wid or '-'} |")
    w(f"| Mod version | {fa.mod.version or '-'} | {fb.mod.version or '-'} |")
    w(f"| Made for game | {fa.mod.supported or '-'} | {fb.mod.supported or '-'} |")
    w(f"| Files | {len(fa.files)} | {len(fb.files)} |")
    w(f"| Role | {fa.role.role.name if fa.role else '-'} | {fb.role.role.name if fb.role else '-'} |")
    w(f"| Its own name prefixes | {', '.join(sorted(p for p, k in an.owners.items() if k == ka)[:6]) or '-'} | "
      f"{', '.join(sorted(p for p, k in an.owners.items() if k == kb)[:6]) or '-'} |")
    if order:
        w(f"| Place in the playset | {pos.get(ka, 'off')} | {pos.get(kb, 'off')} |")
    w("")
    rel = []
    for x, y in ((fa, fb), (fb, fa)):
        if y.key in x.builds_on:
            rel.append(f"- {x.name} builds on {y.name}: it uses {x.builds_on[y.key]} things only {y.name} defines "
                       f"(e.g. {', '.join(x.uses_examples.get(y.key, [])[:4])}).")
        if y.key in x.optional:
            rel.append(f"- {x.name} has optional extras for {y.name} (it checks for {x.optional[y.key]} of its things).")
        if y.key in x.bundles:
            rel.append(f"- {x.name} already contains {round(x.bundles[y.key] * 100)}% of {y.name}'s files (a pack).")
        if y.key in A.b_dep_keys(x, list(an.facts.values())):
            rel.append(f"- {x.name} declares {y.name} as a required mod.")
    w("**How they relate:** " + ("\n" + "\n".join(rel) if rel else "independent mods (neither uses the other)."))
    w("")
    # ---- the problems
    w("## The problems")
    w("")
    if not issues:
        w("No problems between these two mods in the current playset.")
    for n, i in enumerate(issues, 1):
        w(f"### {n}. {i.title} ({i.severity})")
        w("")
        w(f"- **Kind:** {A.ISSUE_KINDS.get(i.kind, i.kind)}")
        w(f"- **In game:** {i.effect}")
        w(f"- **Why:** {i.detail}")
        w(f"- **What solves it:** {A.REMEDY_LABEL.get(i.remedy, i.remedy)}. {i.fix}")
        w(f"- **How sure:** {A.CONFIDENCE_LABEL.get(i.confidence, i.confidence)}")
        if i.items:
            w("")
            w("```text")
            w("\n".join(str(x) for x in i.items[:80]) + (f"\n... {len(i.items) - 80} more" if len(i.items) > 80
                                                        else ""))
            w("```")
        w("")
    # ---- the rules for what's involved
    objs, files = [], []
    for i in issues:
        for folder, name in i.objects:
            if os.path.splitext(folder)[1] and not name:
                if folder not in files:
                    files.append(folder)
            elif (folder, name) not in objs:
                objs.append((folder, name))
    clash_files = [c for c in an.conflicts.get(tuple(sorted((ka, kb))), []) if c.kind == "clash"]
    for c in clash_files:
        if c.rel not in files:
            files.append(c.rel)
    folders = []
    for folder, _ in objs:
        fo = A.object_folder(folder) if os.path.splitext(folder)[1] else folder
        if fo not in folders and fo not in ("defines", "gui"):
            folders.append(fo)
    for rel in files:
        fo = A.object_folder(rel)
        if fo not in folders:
            folders.append(fo)
    w("## How the game combines these")
    w("")
    w("- Same file path in two mods: the mod loaded **later** provides the whole file; the other's copy is ignored.")
    for fo in folders[:20]:
        info = GD.folder_info(fo)
        w(f"- `{fo}` ({info.plural}): {MERGE_TEXT.get(info.merge, info.merge)}.")
    if any(fo == "gui" for fo, _ in objs):
        w(f"- GUI templates and types: {MERGE_TEXT['fios']}.")
    if any(fo == "defines" for fo, _ in objs):
        w(f"- `common/defines`: {MERGE_TEXT['defines']}.")
    w("")
    docs = []
    if van is not None and van.roots:
        for fo in folders[:6]:
            d = GD.info_doc(van.game_dir, fo, max_lines=40)
            if d:
                docs.append((fo, d))
    if docs:
        w("### The game's own notes on these folders")
        w("")
        for fo, d in docs:
            w(f"`{fo}` (from the game's .info file):")
            w("```text")
            w(d)
            w("```")
        w("")
    # ---- the content they fight over
    if objs:
        w("## What they fight over, object by object")
        w("")
        shown = []
        for folder, name in objs:
            if len(shown) >= MAX_OBJECTS:
                break
            ra, ta = _locate(fa, folder, name)
            rb, tb = _locate(fb, folder, name)
            rv, tv = _vanilla(van, folder, name, ra or rb)
            if not ta and not tb and not tv:
                continue
            shown.append((folder, name))
            info = GD.folder_info(A.object_folder(folder) if os.path.splitext(folder)[1] else folder)
            w(f"### `{name}` ({info.noun}, `{folder}`)")
            w("")
            win, why = _winner(an, fa, fb, folder, name)
            if win:
                w(f"- **Used now:** {win}'s version ({why}).")
            w("- **Game's version:** " + (f"`{rv}`" if tv else "none: a new object (not in the game)"))
            for f_, r_, t_, o_ in ((fa, ra, ta, fb), (fb, rb, tb, fa)):
                own = _own_names(t_, f_, o_, vanilla_all)
                if own:
                    w(f"- **{f_.name}'s version relies on its own:** {', '.join(own)}")
            w("")
            if tv:
                w(f"**The game's own version** (`{rv}`, complete: the base of the merged object):")
                w("```")
                w(_cut(tv, f"the game's {rv}"))
                w("```")
            for f_, r_, t_ in ((fa, ra, ta), (fb, rb, tb)):
                if t_:
                    where = f"{f_.name}'s {r_}"
                    d = _diff(tv, t_, "game", f_.name, where) if tv else ""
                    if not tv or len(t_.splitlines()) <= MAX_OBJECT_LINES or not d:
                        w(f"**{f_.name}** (`{r_}`, complete):")
                        w("```")
                        w(_cut(t_, where))
                        w("```")
                    else:
                        w(f"**{f_.name}** (`{r_}`): the game's version with the changes below.")
                    if d:
                        w(f"What {f_.name} changed compared with the game (complete diff):")
                        w("```diff")
                        w(d)
                        w("```")
                else:
                    gone = f_.removed.get((folder, name))
                    w(f"**{f_.name}**: " + (f"its copy of `{gone}` leaves it out." if gone else "doesn't define it."))
            if ta and tb and not tv:
                d = _diff(ta, tb, fa.name, fb.name, f"{fb.name}'s {rb}")
                if d:
                    w("Differences between the two versions:")
                    w("```diff")
                    w(d)
                    w("```")
            w("")
        rest = [f"{n} ({fo})" for fo, n in objs if (fo, n) not in shown]
        if rest:
            w(f"...and {len(rest)} more: " + ", ".join(rest[:200]))
            w("")
    # ---- whole files
    if clash_files:
        w("## Shared files (same path in both)")
        w("")
        for c in clash_files[:20]:
            pa, pb = fa.mod.paths.get(c.rel), fb.mod.paths.get(c.rel)
            fa_, fb_ = (fa, fb) if c.a == ka else (fb, fa)
            w(f"### `{c.rel}`")
            w("")
            w(f"- {an.facts[c.a].name}: {c.lost_a} changed line(s) the other copy doesn't have; "
              f"{an.facts[c.b].name}: {c.lost_b}.")
            if c.objs_both:
                w(f"- Objects both changed differently: {', '.join(c.objs_both[:30])}")
            only_a = [o for o in c.objs_a if o not in c.objs_both]
            only_b = [o for o in c.objs_b if o not in c.objs_both]
            if only_a:
                w(f"- Changed only by {an.facts[c.a].name}: {', '.join(only_a[:30])}")
            if only_b:
                w(f"- Changed only by {an.facts[c.b].name}: {', '.join(only_b[:30])}")
            if A.is_text(c.rel) and pa and pb:
                vp = van.path(c.rel) if van is not None and van.roots else None
                if vp:
                    # what each mod changed in the game's file: the patch is the game's file + both diffs
                    vt = _read(vp)
                    w("- The game has this file too: below are the game's file and what each mod changed in it. "
                      "The merged copy = the game's file with both sets of changes.")
                    w(f"The game's `{c.rel}` (complete):")
                    w("```")
                    w(_cut(vt, f"the game's {c.rel}"))
                    w("```")
                    for f_ in (fa, fb):
                        d = _diff(vt, _read(f_.mod.paths.get(c.rel)), "game", f_.name, f"{f_.name}'s {c.rel}")
                        if d:
                            w(f"What {f_.name} changed:")
                            w("```diff")
                            w(d)
                            w("```")
                else:
                    d = _diff(_read(pa), _read(pb), fa.name, fb.name, f"{fb.name}'s {c.rel}")
                    if d:
                        w("```diff")
                        w(d)
                        w("```")
            elif not A.is_text(c.rel):
                w("- A picture, model, sound or font: it can't be merged; pick one mod's file.")
            w("")
        if len(clash_files) > 20:
            w(f"...and {len(clash_files) - 20} more shared files.")
            w("")
    # ---- the plan
    a_id, b_id = fa.wid or "<id of A>", fb.wid or "<id of B>"
    w("## The patch, step by step")
    w("")
    w("1. A new mod folder with a `descriptor.mod` that requires both mods:")
    w("```")
    w(f'name="{fa.name} + {fb.name} compatch"')
    w('version="1.0"')
    w(f'supported_version="{game_version + ".*" if game_version else "1.*"}"')
    w(f'dependencies={{ "{fa.name}" "{fb.name}" }}')
    w('tags={ "Fixes" }')
    w("```")
    w(f"2. On the Workshop, list both as Required items ({a_id} and {b_id}). Load the patch after both mods.")
    step = 3
    plan = []
    for rel in files:
        if os.path.splitext(rel)[1] in (".txt", ".gui", ".yml", ".gfx", ".asset") and A.is_text(rel):
            plan.append(f"`{rel}`: one merged copy at this same path (whole-file replacement; the patch loads last).")
        else:
            plan.append(f"`{rel}`: can't be merged (not text): ship the file of the mod you prefer at this path.")
    by_folder = {}
    for folder, name in objs:
        if os.path.splitext(folder)[1]:
            continue
        by_folder.setdefault(folder, []).append(name)
    for folder, names in by_folder.items():
        info = GD.folder_info(folder)
        sample = ", ".join(names[:5]) + (" ..." if len(names) > 5 else "")
        rivals = _rival_files(fa, fb, folder, names)
        if folder == "gui":
            plan.append(f"`gui/{_first_name(rivals, patch_slug)}.gui` (sorts FIRST, so it wins): merged GUI "
                        f"types/templates {sample}.")
        elif folder == "defines":
            plan.append(f"`common/defines/{_last_name(rivals, patch_slug)}.txt`: the chosen values for {sample}.")
        elif info.merge == "whole" and folder == "events":
            plan.append(f"Events {sample}: events can't be overridden one by one. Replace the events FILE of one mod "
                        "(same path) with a copy that leaves out the duplicate, and keep the merged event in the "
                        "other mod's file (also replaced at its path), so each ID exists once.")
        elif folder.startswith("common/on_action"):
            plan.append(f"`common/on_action/zzz_{patch_slug}_compatch_on_actions.txt`: for {sample}, don't redefine "
                        "`effect`/`trigger`; give each mod's effect its own new on-action and list both in "
                        "`on_actions = {{ ... }}` of the game's on-action.")
        else:
            plan.append(f"`{folder}/{_last_name(rivals, patch_slug)}.txt` (sorts after "
                        + (f"`{max(rivals)}`" if rivals else "both mods' files") + f", so it wins): one merged "
                        f"definition of each of {sample}.")
    for p in plan:
        w(f"{step}. {p}")
        step += 1
    w(f"{step}. Texts the patch adds or changes: `localization/english/replace/{patch_slug}_compatch_l_english.yml` "
      "(UTF-8 with BOM; first line `l_english:`).")
    w("")
    # ---- the prompt
    w("## Prompt for an AI")
    w("")
    w("Copy everything below the line into an AI chat, and attach (or paste) this whole report after it.")
    w("")
    w("---")
    w("")
    w(f"You are an expert {game or 'Crusader Kings III'} modder (Paradox Clausewitz/Jomini script"
      + (f", game version {game_version}" if game_version else "") + f"). I use two mods together, "
      f"\"{fa.name}\" and \"{fb.name}\", and they conflict. The attached report has: every conflict between them, "
      "the rules the game uses to combine each kind of file involved (with the game's own notes), each mod's "
      "version of every object they both change next to the game's own version, what each mod changed as a "
      "diff, and a step-by-step plan of the patch files.")
    w("")
    w("Write the compatibility patch:")
    w("1. Follow the plan in \"The patch, step by step\": exactly those file paths and file names (they decide "
      "which definition wins).")
    w("2. For each object, start from the game's version and apply BOTH mods' changes (use the diffs). Where "
      "they truly contradict, keep the change that belongs to the mod whose feature it is, and mark the spot "
      "with a comment `# COMPATCH: kept <mod>'s version because ...`.")
    w("3. For shared files, produce one complete merged copy: keep every object of both copies; never drop "
      "an object or a line you weren't asked to change.")
    w("4. Use only triggers, effects, scopes, modifiers and names that appear in the report's code or are standard "
      "in this game version. Don't invent new ones. Names listed as \"relies on its own\" must stay as they are "
      "(they're why the patch requires both mods).")
    w("5. Never define an event ID twice, and never put an `effect`/`trigger` block into an existing on-action: "
      "add new on-actions and list them in `on_actions = { ... }`.")
    w("6. Keep braces balanced and the files valid; localisation files are UTF-8 with BOM and start with "
      "`l_english:`.")
    w("7. Output: the complete descriptor.mod, then every file with its full path as a heading and its full "
      "content in a code block, ready to copy. No placeholders, no \"rest unchanged\".")
    w("8. End with: a short list of the choices you made, and a checklist of what to test in game (which "
      "decisions, interactions, events or windows to open).")
    if _BUDGET.cut:
        w(f"9. {_BUDGET.cut} piece(s) of code in the report are marked `SHORTENED` (the report would be too long "
          "otherwise). Before writing anything that depends on one, ask me to paste the full text from the place "
          "the marker names. Never guess the missing lines.")
        L.insert(4, f"> Note: {_BUDGET.cut} long piece(s) of code are shortened (marked `SHORTENED`, with where the "
                    "full text is). Everything else is complete.")
        L.insert(5, "")
    w("")
    return "\n".join(L) + "\n"


def default_name(an, ka, kb, ext=".md"):
    def slug(s):
        return re.sub(r"[^A-Za-z0-9]+", "_", A.clean_title(s)).strip("_")[:30] or "mod"
    return f"compatch_report_{slug(an.facts[ka].name)}_{slug(an.facts[kb].name)}{ext}"


def save(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
