"""Finding a compatibility patch for two mods on the Steam Workshop.

A compatch is usually a small mod that requires both mods (Steam's "Required items") and is named after
them ("A + B compatch", "B patch for A"). The Workshop is searched with both names and with each name plus
"compatch"; every result that could be one is checked on its own page:

    requires both                       -> certain
    requires one and names the other    -> likely
    names both and calls itself a patch -> likely
    names both                          -> possible

and whether it may be outdated (last updated before one of the two mods, or tagged for an older game
version). Never raises: problems end up in the result's `error`.
"""
import re

import workshop as W

try:
    from sources import clean_title, tokens
except Exception:                      # pragma: no cover
    def clean_title(s):
        return s

    def tokens(s):
        return [t for t in re.split(r"[^0-9a-z]+", s.lower()) if t]

PATCH_WORDS = re.compile(r"\b(com-?patch|compat(ibility)?|patch|bridge|integration|merge[dr]?|fix(es)?\s+for)\b",
                         re.I)
SURE_RANK = {"certain": 0, "likely": 1, "possible": 2}


_SMALL = {"and", "the", "of", "a", "an", "for", "&", "+", "mod", "-"}


def short_name(name, n=3):
    """The first few meaningful words of a mod's name, for searching."""
    t = clean_title(name)
    words = [w for w in re.split(r"[\s\-:|]+", t) if w and w.lower() not in _SMALL and
             not re.fullmatch(r"\d+(\.\d+)*\*?", w)]
    return " ".join(words[:n]) or name


def abbreviation(name):
    """'Regional Immersion and Cultural Enrichment (RICE)' -> 'RICE'; otherwise the initials of a long name."""
    m = re.search(r"[\(\[]([A-Z][A-Z0-9+]{1,7})[\)\]]", name)
    if m:
        return m.group(1)
    words = [w for w in re.split(r"[\s\-:|]+", clean_title(name)) if w and w.lower() not in _SMALL]
    return "".join(w[0] for w in words).upper() if len(words) >= 3 else ""


def names_mod(title, mod_name):
    """Does a Workshop title name this mod? (all of its meaningful words, or its initials)."""
    tt = set(tokens(title))
    mt = [w for w in tokens(mod_name)][:4]
    if not mt:
        return False
    if all(w in tt for w in mt):
        return True
    initials = "".join(w[0] for w in tokens(mod_name) if w)
    return len(initials) >= 3 and initials in tt


class Candidate:
    def __init__(self, item, sure, why):
        self.item, self.sure, self.why = item, sure, why
        self.notes = []                 # "older than X's last update", "tagged for 1.18"...

    @property
    def outdated(self):
        return bool(self.notes)


class Result:
    def __init__(self):
        self.candidates = []
        self.error = ""
        self.searched = []


def search(net, appid, a, b, game_version="", limit=12):
    """a, b: {"name", "wid", "updated"} of the two mods. Returns a Result, best candidates first."""
    res = Result()
    qa, qb = short_name(a["name"]), short_name(b["name"])
    queries = [f"{qa} {qb}", f"{qa} compatch", f"{qb} compatch", f"{qa} patch"]
    aa, ab = abbreviation(a["name"]), abbreviation(b["name"])
    if aa or ab:
        queries.insert(1, f"{aa or qa} {ab or qb}")
    seen, pool = set(), []
    for q in queries:
        res.searched.append(q)
        try:
            page = W.browse(net, appid, "trend", 7, q, (), (), 1, False)
        except Exception as e:
            page = None
            res.error = str(e)
        if page is None or page.error:
            res.error = res.error or (page.error if page else "")
            continue
        for it in W.rank(page.items, q)[:15]:
            if it.id in seen or it.id in (a.get("wid"), b.get("wid")):
                continue
            seen.add(it.id)
            na, nb = names_mod(it.title, a["name"]), names_mod(it.title, b["name"])
            if na or nb or PATCH_WORDS.search(it.title):
                pool.append((it, na, nb))
    if not pool:
        return res
    pool.sort(key=lambda x: -(x[1] + x[2] + bool(PATCH_WORDS.search(x[0].title))))
    for it, na, nb in pool[:limit]:
        try:
            req = {rid for rid, _ in W.details(net, it.id).required}
        except Exception:
            req = set()
        ra, rb = a.get("wid") in req, b.get("wid") in req
        patchy = bool(PATCH_WORDS.search(it.title))
        if ra and rb:
            c = Candidate(it, "certain", "requires both mods")
        elif (ra and nb) or (rb and na):
            c = Candidate(it, "likely", "requires one and is named after the other")
        elif na and nb and patchy:
            c = Candidate(it, "likely", "named as a patch for both")
        elif na and nb:
            c = Candidate(it, "possible", "names both mods")
        else:
            continue
        for m in (a, b):
            if m.get("updated") and it.updated and it.updated < m["updated"] - 86400:
                c.notes.append(f"older than \"{m['name']}\"'s last update")
        if W.fits(it, game_version) is False:
            vs = [f"{x}.{y}" for x, y in sorted(it.versions(), reverse=True) if (x, y) != (0, 0)]
            c.notes.append(f"tagged for {vs[0] if vs else 'an older version'}")
        res.candidates.append(c)
    res.candidates.sort(key=lambda c: (SURE_RANK[c.sure], c.outdated, -c.item.subs))
    return res
