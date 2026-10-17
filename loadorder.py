"""
Load order: turning the analysis (analysis.py) into the best order, with reasons.

Only shared file paths (and replace_path) depend on load order. Everything else is either fixed by
file names (objects, events, on_actions) or simply about presence (dependencies). So the sorter weighs
evidence about which mod should load later, strongest first:

    weight   evidence
    1000     your own rules; dependencies a mod declares
      80     its name says it's a compatch / patch for the other mod
      40     its Workshop page says "load after X" / "below X" (X linked, named or abbreviated)
  25/file    its copy of a shared file already contains the other mod's changes (a merge)
   <=40      a real clash on shared files: the mod whose loss would hurt more wins. Hurt = changed lines
             lost (weighted by what the file is: windows and map files count more, texts and pictures
             less) relative to everything the mod changes, plus definitions in the lost file that the mod
             uses elsewhere (losing those breaks other parts of it)
   <=30      it builds on the other mod (uses names only the other defines): add-ons load after their base
      30     replace_path: mods adding files to a folder another mod replaces load after it
       4     "load at the very top / bottom" on a Workshop page (per other mod)
       3     fix packs and total conversions near the top (as the Unofficial Patch asks)
     0.4     conventional bands: foundations (fixes, conversions, maps, frameworks, overhauls) first,
             add-ons / compatches / translations last; regular content keeps your order
   0.001     keep the current relative order when nothing else decides

The best order is the one satisfying the most total weight (a weighted linear-ordering problem):
greedy start, then single-mod moves until nothing improves, from two starting points.
"""

import analysis as A
import roles as R

W_HARD, W_COMPATCH, W_HINT, W_MERGE, W_MERGE_CAP = 1000.0, 80.0, 40.0, 25.0, 100.0
W_CLASH, W_CLASH_CAP, W_BROKEN, W_BUILDS_CAP = 20.0, 40.0, 25.0, 30.0
W_REPLACE, W_TOPBOTTOM, W_CONVENTION, W_TIER, W_KEEP = 30.0, 4.0, 3.0, 0.4, 0.001


class Edge:
    """A preference: `before` should load before `after`. `owner` is the mod whose own evidence it is."""
    __slots__ = ("before", "after", "weight", "reason", "kind", "owner")

    def __init__(self, before, after, weight, reason, kind, owner=None):
        self.before, self.after, self.weight, self.reason, self.kind = before, after, weight, reason, kind
        self.owner = owner


def area_factor(rel):
    """How much losing one changed line of this file hurts."""
    if rel.startswith("map_data/") or rel.startswith("common/landed_titles/"):
        return 2.0
    if rel.endswith(".gui"):
        return 2.0
    if rel.startswith(("localization/", "localisation/")):
        return 0.3
    if not A.is_text(rel):
        return 0.5
    return 1.0


def build_edges(an, keys, rules=()):
    """Preferences between the mods in `keys` (a playset's enabled mods)."""
    on = [an.facts[k] for k in keys if k in an.facts]
    keyset = {f.key for f in on}
    E = []

    def add(a, b, w, why, kind, owner=None):
        if a is not b and w > 0:
            E.append(Edge(a.key, b.key, w, why, kind, owner.key if owner else None))

    by_name = {}
    for f in on:
        by_name.setdefault(A.clean_title(f.name).lower(), f)
    for a, b in rules:
        if a in keyset and b in keyset:
            add(an.facts[a], an.facts[b], W_HARD, f'your rule: "{an.facts[a].name}" before "{an.facts[b].name}"', "rule")
    for f in on:
        for dep in f.mod.dependencies:
            t = by_name.get(A.clean_title(dep).lower()) or next(
                (o for o in on if o is not f and A.similarity(dep, o.name) >= 0.85), None)
            if t is not None and t is not f:
                add(t, f, W_HARD, f'"{f.name}" declares it needs "{t.name}"', "dependency", f)
        role = f.role.role.id if f.role else ""
        if role in ("compatch", "submod", "translation"):
            for t in on:
                if t is not f and A.mentions(A.clean_title(f.name), t):
                    add(t, f, W_COMPATCH, f'"{f.name}" is named as a patch / add-on for "{t.name}"', "compatch", f)
        for base, n in f.builds_on.items():
            if base in keyset:
                b = an.facts[base]
                ex = ", ".join(f.uses_examples.get(base, [])[:3])
                add(b, f, min(W_BUILDS_CAP, 6 + n), f'"{f.name}" builds on "{b.name}": it uses {n} things only '
                                                    f'"{b.name}" defines (e.g. {ex})', "builds_on", f)
        for kind, o, snip in f.hints:
            if o is not None and o.key not in keyset:
                continue
            quote = f'{f.name}\'s Workshop page: "{snip}"'
            if kind in ("after", "requires"):
                add(o, f, W_HINT if kind == "after" else W_HINT / 2, quote, "hint", f)
            elif kind == "before":
                add(f, o, W_HINT, quote, "hint", f)
            elif kind in ("top", "bottom", "after_tc", "before_tc"):
                for o2 in on:
                    if o2 is f:
                        continue
                    is_tc = o2.role and o2.role.role.id == "total_conversion"
                    if kind.endswith("_tc") and not is_tc:
                        continue
                    if any(k2 == kind for k2, _, _ in o2.hints):
                        continue
                    w = W_HINT if kind.endswith("_tc") else W_TOPBOTTOM
                    if kind in ("top", "before_tc"):
                        add(f, o2, w, quote, "position", f)
                    else:
                        add(o2, f, w, quote, "position", f)
        for rp in f.mod.replace_paths:
            for o in on:
                if o is not f and any(r.startswith(rp + "/") for r in o.files):
                    add(f, o, W_REPLACE, f'"{f.name}" replaces the game\'s {rp}/ and "{o.name}" adds files there',
                        "replace_path", f)
    # conventions and tidy roles
    for a in on:
        ra = a.role.role if a.role else R.UNKNOWN
        for b in on:
            if a is b:
                continue
            rb = b.role.role if b.role else R.UNKNOWN
            if ra.id in ("fix", "total_conversion") and rb.id not in ("fix", "total_conversion"):
                add(a, b, W_CONVENTION, f"{ra.name.lower()}s go near the top", "convention", a)
            elif band(ra) < band(rb):
                add(a, b, W_TIER, f"conventional order: {ra.name.lower()} before {rb.name.lower()}", "tier")
    # shared files
    for (ka, kb), fcs in an.conflicts.items():
        if ka not in keyset or kb not in keyset:
            continue
        fa, fb = an.facts[ka], an.facts[kb]
        merge_ab = [c for c in fcs if (c.kind == "a_in_b" and c.a == ka) or (c.kind == "b_in_a" and c.a == kb)]
        merge_ba = [c for c in fcs if (c.kind == "b_in_a" and c.a == ka) or (c.kind == "a_in_b" and c.a == kb)]
        if merge_ab:
            add(fa, fb, min(W_MERGE_CAP, W_MERGE * len(merge_ab)),
                f'"{fb.name}"\'s copy of {_files(merge_ab)} already includes "{fa.name}"\'s changes', "merge")
        if merge_ba:
            add(fb, fa, min(W_MERGE_CAP, W_MERGE * len(merge_ba)),
                f'"{fa.name}"\'s copy of {_files(merge_ba)} already includes "{fb.name}"\'s changes', "merge")
        clashes = [c for c in fcs if c.kind == "clash"]
        if not clashes:
            continue
        lost = {ka: 0.0, kb: 0.0}
        broken = {ka: [], kb: []}
        for c in clashes:
            af = area_factor(c.rel)
            la, lb = (c.lost_a, c.lost_b) if c.a == ka else (c.lost_b, c.lost_a)
            ba, bb = (c.broken_a, c.broken_b) if c.a == ka else (c.broken_b, c.broken_a)
            lost[ka] += la * af
            lost[kb] += lb * af
            broken[ka] += ba
            broken[kb] += bb
        hurt = {k: min(1.0, lost[k] / max(1.0, an.facts[k].total)) + 0.15 * min(len(broken[k]), 6) for k in (ka, kb)}
        pref = W_CLASH * (hurt[kb] - hurt[ka]) * min(3, len(clashes)) ** 0.5   # >0: kb should win (load later)
        pref = max(-W_CLASH_CAP, min(W_CLASH_CAP, pref))
        if abs(pref) < 1e-6:
            continue
        win, lose = (fb, fa) if pref > 0 else (fa, fb)
        why = (f"both change {_files(clashes)} differently. If \"{lose.name}\" won, \"{win.name}\" would lose "
               f"{_pct(min(1.0, lost[win.key] / max(1.0, win.total)))} of its changes"
               + (f" and {len(broken[win.key])} definitions it uses elsewhere ({', '.join(broken[win.key][:3])})"
                  if broken[win.key] else "")
               + f"; the other way round \"{lose.name}\" loses only "
               f"{_pct(min(1.0, lost[lose.key] / max(1.0, lose.total)))}"
               + (f" and {len(broken[lose.key])} used definitions" if broken[lose.key] else ""))
        add(lose, win, abs(pref), why, "clash")
    return E


def band(role):
    """Foundations (fixes, conversions, maps, frameworks, overhauls) first, regular content in the middle
    (kept in your order: between mods that share nothing the order has no effect), add-ons, compatches
    and translations last."""
    if role.id in ("fix", "total_conversion", "map", "framework", "overhaul"):
        return 0
    if role.id in ("submod", "compatch", "translation"):
        return 2
    return 1


def _files(cs, n=2):
    names = [c.rel for c in cs[:n]]
    more = len(cs) - n
    return ", ".join(names) + (f" and {more} more file{'s' if more != 1 else ''}" if more > 0 else "")


def _pct(x):
    return f"{x:.0%}" if x >= 0.01 or x == 0 else "<1%"


def role_of(an, key):
    f = an.facts.get(key)
    return f.role.role if f and f.role else R.UNKNOWN


class Result:
    def __init__(self):
        self.order = []            # full list of keys (disabled ones kept in place)
        self.enabled_order = []
        self.score = 0.0
        self.reasons = {}          # key -> [(satisfied, weight, text)]
        self.moved = 0
        self.broken = []           # strong preferences that could not all be met


def solve(an, current, enabled, rules=()):
    """current: all keys in today's order; enabled: set of enabled keys; rules: [(before, after)] by key.
    Returns a Result with the best order found."""
    keys = [k for k in current if k in enabled and k in an.facts]
    n = len(keys)
    idx = {k: i for i, k in enumerate(keys)}
    W = [[0.0] * n for _ in range(n)]
    edges = build_edges(an, keys, rules)
    for e in edges:
        if e.before in idx and e.after in idx:
            W[idx[e.before]][idx[e.after]] += e.weight
    for i in range(n):
        for j in range(i + 1, n):
            W[i][j] += W_KEEP
    best = None
    for start in (_greedy(W, n), list(range(n))):
        order = _improve(W, start)
        sc = _score(W, order)
        if best is None or sc > best[0] + 1e-9:
            best = (sc, order)
    sc, order = best
    res = Result()
    res.enabled_order = [keys[i] for i in order]
    res.score = sc
    it = iter(res.enabled_order)
    res.order = [next(it) if (k in enabled and k in an.facts) else k for k in current]
    res.moved = moved_count(keys, res.enabled_order)
    res.reasons, res.broken = explain(an, res.enabled_order, edges)
    return res


def explain(an, enabled_order, edges=None, rules=()):
    """Why each mod sits where it does in this order: ({key: [reason dicts]}, [strong edges not met])."""
    if edges is None:
        edges = build_edges(an, enabled_order, rules)
    reasons, broken = {k: [] for k in enabled_order}, []
    pos = {k: i for i, k in enumerate(enabled_order)}
    agg = {}
    for e in edges:
        if e.before not in pos or e.after not in pos:
            continue
        ok = pos[e.before] < pos[e.after]
        if not ok and e.weight >= W_HINT:
            broken.append(e)
        if e.kind == "tier":
            continue
        if e.kind in ("position", "convention"):           # one wish towards many mods: report once
            a = agg.setdefault((e.owner, e.reason, e.kind), [0, 0, 0.0])
            a[0] += ok
            a[1] += 1
            a[2] += e.weight
            continue
        for me, other, rel in ((e.after, e.before, "after"), (e.before, e.after, "before")):
            reasons[me].append({"ok": ok, "weight": e.weight, "text": e.reason, "other": other,
                                "rel": rel, "kind": e.kind})
    for (owner, reason, kind), (n_ok, n, w) in agg.items():
        if owner in reasons:
            extra = "" if n_ok == n else f" (kept for {n_ok} of {n} mods; stronger reasons decided the rest)"
            reasons[owner].append({"ok": n_ok == n, "weight": w, "text": reason + extra, "other": None,
                                   "rel": kind, "kind": kind})
    for k in reasons:
        reasons[k].sort(key=lambda r: (-r["weight"], not r["ok"]))
    return reasons, broken


def moved_keys(old, new):
    """The mods that really moved: everything outside the longest run that kept its relative order
    (when one mod jumps from 8th to 1st, the seven it jumped over did not 'move')."""
    import bisect
    where = {k: i for i, k in enumerate(old)}
    seq = [k for k in new if k in where]
    tails, tail_idx, prev = [], [], [None] * len(seq)
    for j, k in enumerate(seq):
        v = where[k]
        i = bisect.bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
            tail_idx.append(j)
        else:
            tails[i], tail_idx[i] = v, j
        prev[j] = tail_idx[i - 1] if i else None
    keep = set()
    j = tail_idx[-1] if tail_idx else None
    while j is not None:
        keep.add(seq[j])
        j = prev[j]
    return {k for k in seq if k not in keep}


def moved_count(old, new):
    return len(moved_keys(old, new))


def _score(W, order):
    s = 0.0
    for i in range(len(order)):
        row = W[order[i]]
        for j in range(i + 1, len(order)):
            s += row[order[j]]
    return s


def _greedy(W, n):
    rest = set(range(n))
    net = [sum(W[x][y] - W[y][x] for y in range(n) if y != x) for x in range(n)]
    out = []
    while rest:
        x = max(rest, key=lambda v: (net[v], -v))
        out.append(x)
        rest.discard(x)
        for v in rest:
            net[v] -= W[v][x] - W[x][v]
    return out


def _improve(W, order, passes=60):
    order = list(order)
    for _ in range(passes):
        changed = False
        for x in list(order):
            p = order.index(x)
            seq = order[:p] + order[p + 1:]
            c = sum(W[x][y] for y in seq)              # x placed first
            best_k, best_c = 0, c
            cur_c = c if p == 0 else None
            for k in range(len(seq)):
                y = seq[k]
                c += W[y][x] - W[x][y]                    # x moves past y
                if k + 1 == p:
                    cur_c = c
                if c > best_c + 1e-9:
                    best_k, best_c = k + 1, c
            if cur_c is None:
                cur_c = c
            if best_c > cur_c + 1e-9 and best_k != p:
                seq.insert(best_k, x)
                order = seq
                changed = True
        if not changed:
            break
    return order


# ================================================================== who wins what, for a given order
def winners(an, order, enabled):
    """What happens to every shared file with this order. The mod loaded last provides the file; every
    other mod that has it is either 'same' (identical/equivalent copy), 'merged' (the winner's copy
    already contains its changes) or 'loses' (its changes to that file are gone).
    Returns {key: {"wins": [(rel, [beaten keys])], "loses": [(rel, winner)], "merged": [(rel, winner)],
    "same": n}}."""
    pos = {k: i for i, k in enumerate(k for k in order if k in enabled)}
    out = {k: {"wins": [], "loses": [], "merged": [], "same": 0} for k in an.facts}
    per_file = {}
    for (ka, kb), fcs in an.conflicts.items():
        if ka not in pos or kb not in pos:
            continue
        for c in fcs:
            per_file.setdefault(c.rel, {})[(ka, kb)] = c
    for rel, pairs in per_file.items():
        members = {k for pair in pairs for k in pair}
        win = max(members, key=lambda k: pos[k])
        beaten = []
        for m in members:
            if m == win:
                continue
            c = pairs.get(tuple(sorted((m, win))))
            if c is None:
                continue
            if c.kind == "same":
                out[m]["same"] += 1
            elif (c.kind == "a_in_b" and c.a == m) or (c.kind == "b_in_a" and c.a == win):
                out[m]["merged"].append((rel, win))
            else:
                out[m]["loses"].append((rel, win))
                beaten.append(m)
        if beaten:
            out[win]["wins"].append((rel, beaten))
    return out


# ================================================================== Workshop descriptions (cached)


def load_descriptions(net, ids, cache_path, max_age=7 * 86400):
    """{workshop id: description text} (kept for older callers; see analysis.load_workshop)."""
    return {i: d.get("text", "") for i, d in A.load_workshop(net, ids, cache_path, max_age).items()}
