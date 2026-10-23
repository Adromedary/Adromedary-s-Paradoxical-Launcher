"""
Browsing a game's Steam Workshop from inside the app.

Steam's Workshop browse page (steamcommunity.com/workshop/browse) is rendered on the server and ships
its data as JSON inside the page (<script id="valve-ssr-data">): the page of results with full item
details (title, preview picture, tags, dates, size, subscribers, rating...), the game's tag groups
(categories and "Compatible Version"), and the authors' names. Every filter the website has works as
a URL parameter: search text, sort, trend period, required and excluded tags, page.

An item's own page adds what the list doesn't have: its required items and screenshots. Its full
description comes from Steam's public API (GetPublishedFileDetails).

No account or API key is needed for any of this.
"""
import html
import json
import math
import re
import time
import urllib.parse

BROWSE = "https://steamcommunity.com/workshop/browse/"
DETAILS = "https://steamcommunity.com/sharedfiles/filedetails/?id={id}"

SORTS = [  # label, browsesort, days
    ("Trending this week", "trend", 7),
    ("Trending this month", "trend", 30),
    ("Trending this year", "trend", 365),
    ("Most popular (all time)", "totaluniquesubscribers", None),
    ("Top rated", "toprated", None),
    ("Newest", "mostrecent", None),
    ("Recently updated", "lastupdated", None),
]
SORT_BY_LABEL = {s[0]: s for s in SORTS}
VERSION_RX = re.compile(r"^(\d+)\.(\d+)")


class WsItem:
    __slots__ = ("id", "title", "preview", "short", "tags", "created", "updated", "size", "subs", "favs",
                 "stars", "votes", "views", "comments", "children", "creator", "author", "is_collection",
                 "appid")

    def __init__(self, d, authors=None):
        g = d.get
        self.id = str(g("publishedfileid", ""))
        self.title = html.unescape(g("title", "") or self.id)
        self.preview = g("preview_url", "") or ""
        self.short = g("short_description", "") or ""
        self.tags = [t.get("tag", "") for t in g("tags", []) if t.get("tag")]
        self.created, self.updated = int(g("time_created", 0) or 0), int(g("time_updated", 0) or 0)
        self.size = int(g("file_size", 0) or 0)
        self.subs = int(g("subscriptions", 0) or g("lifetime_subscriptions", 0) or 0)
        self.favs = int(g("favorited", 0) or 0)
        self.stars = int(g("star_rating", 0) or 0)
        self.votes = int(g("total_votes", 0) or 0)
        self.views = int(g("views", 0) or 0)
        self.comments = int(g("num_comments_public", 0) or 0)
        self.children = int(g("num_children", 0) or 0)
        self.creator = str(g("creator", "") or "")
        self.author = (authors or {}).get(self.creator, "")
        self.is_collection = g("file_type", 0) == 2
        self.appid = str(g("consumer_appid", "") or "")

    @property
    def url(self):
        return DETAILS.format(id=self.id)

    def versions(self):
        """Game versions the author ticked ('1.20 'Crozier'' -> (1, 20)); 'Older' -> (0, 0)."""
        out = []
        for t in self.tags:
            m = VERSION_RX.match(t)
            if m:
                out.append((int(m.group(1)), int(m.group(2))))
            elif t.lower() == "older":
                out.append((0, 0))
        return out

    def categories(self):
        return [t for t in self.tags if not VERSION_RX.match(t) and t.lower() != "older"]


def fits(item, game_version):
    """True / False / None (no version tag or no game version)."""
    m = VERSION_RX.match(game_version or "")
    vs = item.versions()
    if not m or not vs:
        return None
    return (int(m.group(1)), int(m.group(2))) in vs


def version_label(item, game_version):
    vs = [v for v in item.versions() if v != (0, 0)]
    if not vs:
        return "older" if item.versions() else ""
    best = max(vs)
    ok = fits(item, game_version)
    return ("✓ " if ok else ("○ " if ok is False else "")) + f"{best[0]}.{best[1]}"


class Page:
    def __init__(self):
        self.items, self.total, self.pages, self.page = [], 0, 0, 1
        self.tag_groups = []           # [(group name, [tag names])]
        self.error = ""


# ------------------------------------------------------------------ the page's embedded data
def _ssr_queries(text):
    s = text.find('id="valve-ssr-data"')
    if s < 0:
        return {}
    s = text.find(">", s) + 1
    e = text.find("</script>", s)
    try:
        data = json.loads(text[s:e])
    except Exception:
        return {}
    out = {}

    def walk(o):
        if isinstance(o, str):
            if o.startswith("{") and "queryKey" in o:
                try:
                    walk(json.loads(o))
                except Exception:
                    pass
            return
        if isinstance(o, dict):
            qs = o.get("queries")
            if isinstance(qs, list):
                for q in qs:
                    try:
                        out[json.dumps(q["queryKey"])] = (q["queryKey"], q["state"]["data"])
                    except Exception:
                        pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def browse_url(appid, sort="trend", days=7, search="", tags=(), excluded=(), page=1, collections=False):
    q = [("appid", appid), ("section", "collections" if collections else "readytouseitems"),
         ("browsesort", "textsearch" if search and sort == "trend" else sort), ("p", page), ("numperpage", 30)]
    if sort == "trend":
        q.append(("days", -1 if days is None else days))
    if search:
        q.append(("searchtext", search))
    q += [("requiredtags[]", t) for t in tags]
    q += [("excludedtags[]", t) for t in excluded]
    return BROWSE + "?" + urllib.parse.urlencode(q)


def browse(net, appid, sort="trend", days=7, search="", tags=(), excluded=(), page=1, collections=False):
    """One page (30 items) of the game's Workshop. Never raises: errors land in Page.error."""
    p = Page()
    p.page = page
    url = browse_url(appid, sort, days, search, tags, excluded, page, collections)
    try:
        r = net.get(url, timeout=40, gap=1.0)
        if r.status != 200:
            p.error = f"Steam answered HTTP {r.status}"
            return p
        text = r.text
    except Exception as e:
        p.error = f"couldn't reach Steam ({e})"
        return p
    qs = _ssr_queries(text)
    authors, browse_data = {}, None
    for key, data in qs.values():
        if not key:
            continue
        if key[0] == "PlayerLinkDetails" and isinstance(data, dict):
            pub = data.get("public_data") or {}
            if pub.get("steamid"):
                authors[str(pub["steamid"])] = pub.get("persona_name", "")
        elif key[0] == "workshop_browse" and isinstance(data, dict):
            browse_data = data
        elif str(key[0]).startswith("declared_tags") and len(key) > 1 and str(key[1]) == str(appid) \
                and isinstance(data, dict):
            groups = data.get("collection_tags" if collections else "readytouse_tags") or data.get("mtx_tags") or []
            p.tag_groups = [(g.get("name") or "Categories", [t.get("name") for t in g.get("tags", []) if t.get("name")
                                                             and not t.get("admin_only")]) for g in groups]
    if browse_data is not None:
        p.items = [WsItem(d, authors) for d in browse_data.get("results", [])]
        p.total = int(browse_data.get("total_count", 0) or 0)
        p.pages = int(browse_data.get("total_pages", 0) or 0)
        return p
    # older page layout: item IDs in links, details from the public API
    ids = list(dict.fromkeys(re.findall(r"sharedfiles/filedetails/\?id=(\d+)", text)))
    if not ids:
        p.error = "Steam's Workshop page layout changed; browsing isn't possible right now"
        return p
    try:
        import sources as S
        det = S.steam_details(net, ids[:30])
        p.items = [WsItem(det[i]) for i in ids[:30] if i in det]
        m = re.search(r"of\s+([\d,]+)\s+entries", text)
        p.total = int(m.group(1).replace(",", "")) if m else len(p.items)
        p.pages = max(1, (p.total + 29) // 30)
    except Exception as e:
        p.error = f"couldn't read the results ({e})"
    return p


# ------------------------------------------------------------------ best matches first
RANKED_PAGES = 3            # a search is ranked across this many of Steam's pages (90 results)


def _words(text):
    return [w for w in re.findall(r"[\w']+", (text or "").lower()) if w]


def match_score(item, search):
    """How well an item matches the search words: the title counts most, then the author, then the
    description. Higher is better; 0 means only Steam's own matching found it."""
    words = _words(search)
    if not words:
        return 0
    phrase = " ".join(words)
    title = " ".join(_words(item.title))
    tw = set(title.split())
    score = 0.0
    if title == phrase:
        score += 1000
    elif title.startswith(phrase):
        score += 700
    elif phrase in title:
        score += 500
    hit = sum(1 for w in words if w in tw)
    part = sum(1 for w in words if w not in tw and any(t.startswith(w) for t in tw))
    score += 300 * hit / len(words) + 120 * part / len(words)
    if hit:                          # a title that is mostly the search beats one that adds a lot to it
        score -= min(200, 30 * max(0, len(tw) - len(words)))
        score += 25 * math.log10(1 + item.subs)          # and the original beats its copies
    author = " ".join(_words(item.author))
    if author and (phrase == author or phrase in author):
        score += 250
    elif author:
        score += 80 * sum(1 for w in words if w in author.split()) / len(words)
    desc = set(_words(item.short)[:400])
    score += 40 * sum(1 for w in words if w in desc) / len(words)
    return score


def rank(items, search):
    """Items in best-match order (ties keep Steam's order, then the most subscribed first)."""
    order = {it.id: i for i, it in enumerate(items)}
    return sorted(items, key=lambda it: (-match_score(it, search), order[it.id] // 10, -it.subs))


def browse_ranked(net, appid, sort, days, search, tags, excluded, collections, stop=None):
    """The first RANKED_PAGES of Steam's results for a search, ranked together and cut back into pages
    of 30: [Page, Page, Page]. Later pages come from Steam as they are."""
    got, first = [], None
    for n in range(1, RANKED_PAGES + 1):
        p = browse(net, appid, sort, days, search, tags, excluded, n, collections)
        if first is None:
            first = p
        if p.error:
            if n == 1:
                return [p]
            break
        got += p.items
        if n >= max(1, p.pages):
            break
    seen, items = set(), []
    for it in got:
        if it.id not in seen:
            seen.add(it.id)
            items.append(it)
    items = rank(items, search)
    out = []
    for i in range(0, max(1, len(items)), 30):
        p = Page()
        p.items, p.total, p.pages, p.page = items[i:i + 30], first.total, first.pages, len(out) + 1
        p.tag_groups = first.tag_groups
        out.append(p)
    return out


# ------------------------------------------------------------------ one item in depth
class Details:
    def __init__(self):
        self.required = []             # [(id, name)]
        self.screenshots = []          # picture URLs
        self.description = ""
        self.error = ""


_bb_cache = {}


def details(net, item_id):
    """Required items, screenshots and the full description of one item. Never raises."""
    if item_id in _bb_cache and time.time() - _bb_cache[item_id][0] < 1800:
        return _bb_cache[item_id][1]
    d = Details()
    try:
        r = net.get(DETAILS.format(id=item_id), timeout=40, gap=0.5)
        page = r.text if r.status == 200 else ""
    except Exception as e:
        page, d.error = "", str(e)
    if page:
        box = re.search(r'id="RequiredItems">(.*?)</div>\s*</div>', page, re.S)
        if box:
            for rid, name in re.findall(r'filedetails/\?id=(\d+)"[^>]*>\s*<div class="requiredItem">\s*(.*?)\s*</div>',
                                        box.group(1), re.S):
                d.required.append((rid, html.unescape(" ".join(re.sub(r"<[^>]+>", " ", name).split()))))
        # every screenshot sits in the page's picture strip (the enlarged-view script names only the first)
        shots = re.findall(r'highlight_strip_screenshot"[^>]*>\s*<img src="([^"]+)"', page)
        shots = shots or re.findall(r"ShowEnlargedImagePreview\(\s*'([^']+)'", page)
        d.screenshots = list(dict.fromkeys(s.split("?")[0] for s in shots if "steamusercontent" in s
                                           or "steamuserimages" in s))[:12]
    try:
        import sources as S
        det = S.steam_details(net, [item_id]).get(item_id) or {}
        d.description = det.get("description", "")
    except Exception:
        pass
    _bb_cache[item_id] = (time.time(), d)
    return d


def plain_description(bb, limit=4000):
    """BBCode description -> readable plain text."""
    t = bb or ""
    t = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", t, flags=re.I | re.S)
    t = re.sub(r"\[img\].*?\[/img\]", "", t, flags=re.I | re.S)
    t = re.sub(r"\[\*\]", "\n • ", t)
    t = re.sub(r"\[h\d\](.*?)\[/h\d\]", lambda m: "\n" + m.group(1).upper() + "\n", t, flags=re.I | re.S)
    t = re.sub(r"\[/?[a-z0-9]+(=[^\]]*)?\]", "", t, flags=re.I)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:limit] + ("..." if len(t) > limit else "")


def human_count(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def ago(ts, now=None):
    if not ts:
        return ""
    s = max(0, int((now or time.time()) - ts))
    for unit, secs in (("year", 31536000), ("month", 2592000), ("week", 604800), ("day", 86400), ("hour", 3600)):
        if s >= secs:
            n = s // secs
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def stars(n):
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)
