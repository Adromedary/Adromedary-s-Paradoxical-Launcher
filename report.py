"""A compatch report: everything needed to write a compatibility patch for two mods, as one Markdown
file, ending with a ready prompt to paste into an AI chat (Claude, ChatGPT...) together with the file.

The report shows, for every object the two mods fight over, the game's own version (when the game folder
is known) and each mod's version side by side, plus the rules of how the game combines them, so the
person (or the AI) writing the patch has all of it in one place.
"""
import os
import re
import time

import analysis as A
import script as SC
from installer import read_text

MAX_OBJECT_LINES = 140             # per version of one object
MAX_OBJECTS = 40                   # objects shown in full; the rest are listed


def _read(path):
    try:
        return read_text(path) if path else ""
    except OSError:
        return ""


def _cut(text, n=MAX_OBJECT_LINES):
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    return "\n".join(lines[:n]) + f"\n# ... {len(lines) - n} more lines"


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
    if "/" in folder and folder.endswith(".txt"):                 # a shared file: (rel, object)
        rel = folder
        return (rel, SC.object_text(_read(m.paths.get(rel)), name)) if rel in f.files else ("", "")
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
    if folder.endswith(".txt"):
        rels = [folder]
    for rel in rels:
        p = van.path(rel)
        if p:
            t = SC.object_text(_read(p), name)
            if t:
                return rel, t
    if "/" in folder and not folder.endswith(".txt"):
        if van._index is None:
            van.path("")
        for rel, full in van._index.items():
            if rel.startswith(folder + "/") and rel.endswith(".txt"):
                text = _read(full)
                if re.search(r"(?m)^[ \t]*" + re.escape(name) + r"\s*=", text):
                    return rel, SC.object_text(text, name)
    return "", ""


def build(an, issues, ka, kb, order=(), game="", game_version="", van=None, app_name=""):
    """The report for the pair (ka, kb) as Markdown text. issues: their problems in the current playset."""
    fa, fb = an.facts[ka], an.facts[kb]
    pos = {k: i + 1 for i, k in enumerate(order)}
    L = []
    w = L.append
    w(f"# Compatch report: {fa.name} + {fb.name}")
    w("")
    w(f"Made by {app_name or 'the launcher'} on {time.strftime('%Y-%m-%d %H:%M')}"
      + (f" for {game} {game_version}" if game else "") + ".")
    w("")
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
    if order:
        w(f"| Place in the playset | {pos.get(ka, 'off')} | {pos.get(kb, 'off')} |")
    w("")
    w("## How the game combines mods (CK3 / Jomini)")
    w("")
    w("- Same file path in both mods: the mod loaded **later** replaces the whole file.")
    w("- Same object (trait, effect, decision...) in files with **different names**: the file whose name sorts "
      "**later** wins (last in, only served), whatever the load order. GUI templates and types are the "
      "opposite: the **first** file wins.")
    w("- Events can't be overridden one by one: the same event ID twice is an error and one is lost.")
    w("- On-actions: `events`, `random_events` and `on_actions` lists are merged; `effect` and `trigger` blocks "
      "replace each other.")
    w("- Defines are per value: each value comes from the file whose name sorts later.")
    w("- Localisation keys defined twice are an error unless the file is in a `replace` folder.")
    w("")
    w("## The problems")
    w("")
    if not issues:
        w("No problems between these two mods in the current playset.")
    for n, i in enumerate(issues, 1):
        w(f"### {n}. {i.title} ({A.SEVERITIES[i.rank] if i.rank < 5 else i.severity})")
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
    # ---- the content they fight over
    objs = []
    for i in issues:
        for folder, name in i.objects:
            if (folder, name) not in objs:
                objs.append((folder, name))
    if objs:
        w("## What they fight over, side by side")
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
            w(f"### `{name}`  ({folder})")
            w("")
            if tv:
                w(f"**The game's own version** (`{rv}`):")
                w("```")
                w(_cut(tv))
                w("```")
            for f_, r_, t_ in ((fa, ra, ta), (fb, rb, tb)):
                if t_:
                    w(f"**{f_.name}** (`{r_}`):")
                    w("```")
                    w(_cut(t_))
                    w("```")
                else:
                    gone = f_.removed.get((folder, name))
                    w(f"**{f_.name}**: " + (f"its copy of `{gone}` leaves it out." if gone else "doesn't define it."))
            w("")
        rest = [f"{n} ({fo})" for fo, n in objs if (fo, n) not in shown]
        if rest:
            w(f"...and {len(rest)} more: " + ", ".join(rest[:200]))
            w("")
    # ---- how to build it
    a_id, b_id = fa.wid or "<id of A>", fb.wid or "<id of B>"
    w("## How a compatch is built")
    w("")
    w("1. A new mod folder with a `descriptor.mod` naming both mods as dependencies:")
    w("```")
    w(f'name="{fa.name} + {fb.name} compatch"')
    w('version="1.0"')
    w(f'supported_version="{game_version + ".*" if game_version else "1.*"}"')
    w(f'dependencies={{ "{fa.name}" "{fb.name}" }}')
    w("```")
    w(f"2. On the Workshop, list both as Required items ({a_id} and {b_id}).")
    w("3. For each shared file: one merged copy at the same path. For each object: one merged definition in a "
      "file whose name sorts after both mods' files (e.g. `zzz_compatch_...txt`), or before them for GUI "
      "templates and types (`00_compatch_...gui`).")
    w("4. Load the compatch after both mods.")
    w("")
    # ---- the prompt
    w("## Prompt for an AI")
    w("")
    w("Copy everything below the line into an AI chat, and attach (or paste) this whole report after it.")
    w("")
    w("---")
    w("")
    w(f"You are an expert {game or 'Crusader Kings III'} modder (Paradox's Clausewitz/Jomini script). I use two "
      f"mods together, \"{fa.name}\" and \"{fb.name}\", and they conflict. The attached report lists every "
      "conflict, how the game combines mods, and each mod's version of the objects they both change (with "
      "the game's own version where known).")
    w("")
    w("Write a compatibility patch mod that keeps the changes of BOTH mods wherever possible:")
    w("1. For every object or file in the report, merge the two versions into one, keeping each mod's "
      "additions; where they truly contradict, keep the version that matches the mod whose feature it is and "
      "say which you chose and why.")
    w("2. Respect the override rules in the report: put merged objects in files that win (names sorting "
      "after both mods' files, or before them for GUI templates/types), and full copies of shared files at "
      "the same path.")
    w("3. Never redefine an event ID or an on-action effect block twice: route on-action effects through new "
      "on-actions listed in `on_actions = { ... }`.")
    w("4. Give the complete descriptor.mod and every file with its full path, ready to copy. Don't leave "
      "placeholders.")
    w("5. Finish with a checklist of what to test in game.")
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
