"""
Steam metadata, name matching, and the download sources used by the engine.

Every source exposes:
    key, name, kind, blurb, short, needs (settings key or None)
    fetch(item, ctx) -> Hit or None        # per-item sources, run in parallel by the engine
    fetch_batch(items, ctx)                # batch sources (Steam); reports each item itself
    reset()                                # called at the start of every run
Sources save their download into item.stage; the engine then installs it.
"""
import difflib
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.parse
import zipfile

from net import IS_WIN, ChallengeError, SourceError, Stopped, unpack  # noqa: F401

STEAM_API = "https://api.steampowered.com/ISteamRemoteStorage/"
COLLECTION_CREATOR_APP = 766      # Steam marks Workshop collections with this creator_app_id


# ------------------------------------------------------------------ name matching
_STOP = {"mod", "mods", "the", "a", "an", "for", "of", "and", "pack", "update", "updated", "version",
         "being", "wip", "beta", "alpha", "redux", "final", "fix", "patch", "compatch", "compatibility"}
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def clean_title(s):
    """Readable title for search boxes: drops [tags], (notes), *flags* and version numbers."""
    s = re.sub(r"[\[\(\{][^\]\)\}]*[\]\)\}]", " ", s)
    s = re.sub(r"\*[^*]*\*", " ", s)
    s = re.sub(r"\bv?\d+(\.\d+){1,}\w*\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" -_|:+") or s


def tokens(s):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", clean_title(s))
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s.lower())
    return [_ROMAN.get(t, t) for t in s.split() if t not in _STOP]


def _directional(ta, tb):
    total = 0.0
    for t in ta:
        best = max(difflib.SequenceMatcher(None, t, u).ratio() for u in tb)
        total += best if best >= 0.85 else 0.0
    return total / len(ta)


def similarity(a, b):
    """0..1. Strict: extra or missing words lower the score, so different mods don't match."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if "".join(ta) == "".join(tb):
        return 1.0
    return min(_directional(ta, tb), _directional(tb, ta))


GAME_ABBREVIATIONS = {"ck", "ck2", "ck3", "eu", "eu4", "eu5", "hoi", "hoi4", "vic", "vic2", "vic3", "v3",
                      "stellaris", "imperator", "ir", "mod", "pdx"}


def strip_game_words(name, game):
    """'ck3_for_the_realm' -> 'for the realm' when the game is Crusader Kings III."""
    drop = GAME_ABBREVIATIONS | set(tokens(game))
    kept = [t for t in re.split(r"[^0-9a-zA-Z]+", _camel(name)) if t and t.lower() not in drop
            and _ROMAN.get(t.lower(), t.lower()) not in drop]
    return " ".join(kept) or name


def _camel(s):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)


# ------------------------------------------------------------------ Steam metadata
def _batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def steam_details(net, ids):
    """{id: details} for every id Steam knows and is public."""
    out = {}
    for chunk in _batches(list(ids), 100):
        form = {"itemcount": len(chunk)}
        form.update({f"publishedfileids[{i}]": x for i, x in enumerate(chunk)})
        r = net.post(STEAM_API + "GetPublishedFileDetails/v1/", data=form)
        if r.status != 200:
            raise SourceError(f"Steam API answered HTTP {r.status}")
        for d in r.json()["response"].get("publishedfiledetails", []):
            if d.get("result") == 1:
                out[str(d["publishedfileid"])] = d
    return out


def steam_collection_children(net, ids):
    """{collection id: [child ids in order]} for the ids that are collections."""
    out = {}
    for chunk in _batches(list(ids), 100):
        form = {"collectioncount": len(chunk)}
        form.update({f"publishedfileids[{i}]": x for i, x in enumerate(chunk)})
        r = net.post(STEAM_API + "GetCollectionDetails/v1/", data=form)
        if r.status != 200:
            raise SourceError(f"Steam API answered HTTP {r.status}")
        for c in r.json()["response"].get("collectiondetails", []):
            if c.get("result") == 1 and "children" in c:
                kids = sorted(c["children"], key=lambda k: k.get("sortorder", 0))
                out[str(c["publishedfileid"])] = [str(k["publishedfileid"]) for k in kids]
    return out


def steam_game_name(net, app_id, cache={}):
    """The store name of a Steam app ('' if Steam doesn't answer). Only answers are remembered, so a
    failed lookup is tried again next time."""
    app_id = str(app_id or "")
    if not app_id:
        return ""
    if app_id not in cache:
        for attempt in range(2):
            try:
                d = net.get_json(f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic")
                if (d or {}).get(app_id, {}).get("success"):
                    cache[app_id] = d[app_id]["data"]["name"]
                    break
            except Exception:
                pass
        else:
            return ""
    return cache.get(app_id, "")


def game_name(net, app_id):
    """Which game a Workshop item belongs to: the Paradox games are known by heart; anything else is
    asked from Steam."""
    import launcher
    for info in launcher.GAMES.values():
        if str(info.get("appid")) == str(app_id):
            return info["names"][0]            # the store name ('Imperator: Rome'), as other sites spell it
    return steam_game_name(net, app_id) or f"App {app_id}"


# ------------------------------------------------------------------ result type

TERMINALS = (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
             ("xfce4-terminal", ["-x"]), ("mate-terminal", ["-x"]), ("tilix", ["-e"]), ("kitty", []),
             ("alacritty", ["-e"]), ("wezterm", ["start", "--"]), ("foot", []), ("xterm", ["-e"]))


class _TerminalRun:
    """SteamCMD in a terminal window on Linux (it asks for the password and Steam Guard code there).
    Terminals often hand the window to a server and return at once, so the end is seen through a marker
    file the wrapped command writes; poll / wait / kill work like a Popen's."""

    def __init__(self, cmd, work):
        term = next(((t, a) for t, a in TERMINALS if shutil.which(t)), None)
        if term is None:
            raise OSError("no terminal program found (install xterm, or leave the Steam account name empty)")
        os.makedirs(work, exist_ok=True)
        self.done = os.path.join(work, "steamcmd.done")
        self.pidf = os.path.join(work, "steamcmd.pid")
        for f in (self.done, self.pidf):
            try:
                os.remove(f)
            except OSError:
                pass
        import shlex
        inner = (f"echo $$ > {shlex.quote(self.pidf)}; " + " ".join(shlex.quote(c) for c in cmd) +
                 f"; echo $? > {shlex.quote(self.done)}")
        self.term = subprocess.Popen([term[0]] + term[1] + ["sh", "-c", inner], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.started = time.time()
        self.returncode = None

    def poll(self):
        if self.returncode is None and os.path.isfile(self.done):
            try:
                self.returncode = int(open(self.done).read().strip() or 0)
            except (OSError, ValueError):
                self.returncode = 0
        if self.returncode is None and self.term.poll() not in (None, 0) and time.time() - self.started < 5:
            self.returncode = self.term.returncode      # the terminal itself failed to start
        if self.returncode is None and time.time() - self.started > 20 and not os.path.isfile(self.pidf):
            self.returncode = -1                        # the window never ran the command
        return self.returncode

    def wait(self, timeout=None):
        end = None if timeout is None else time.time() + timeout
        while self.poll() is None:
            if end is not None and time.time() > end:
                raise subprocess.TimeoutExpired("steamcmd", timeout)
            time.sleep(0.5)
        return self.returncode

    def kill(self):
        try:
            pid = int(open(self.pidf).read().strip())
        except (OSError, ValueError):
            pid = 0
        pids = [pid] if pid else []
        try:                                            # its children (steamcmd and what it started)
            for p in os.listdir("/proc"):
                if p.isdigit():
                    try:
                        with open(f"/proc/{p}/stat") as f:
                            if int(f.read().rsplit(")", 1)[1].split()[1]) in pids:
                                pids.append(int(p))
                    except (OSError, ValueError, IndexError):
                        continue
        except OSError:
            pass
        import signal
        for p in reversed(pids):
            try:
                os.kill(p, signal.SIGTERM)
            except OSError:
                pass
        self.returncode = self.returncode if self.returncode is not None else -9

    terminate = kill

class Hit:
    def __init__(self, source, found_as="", version="", updated="", page="", note=""):
        self.source, self.found_as, self.version = source, found_as, version
        self.updated, self.page, self.note = updated, page, note


# ================================================================== sources
class Source:
    key = name = kind = blurb = short = ""
    needs = None
    batch = False

    def reset(self):
        """Forget per-run state (circuit breakers)."""

    def fetch(self, item, ctx):
        raise NotImplementedError


# ------------------------------------------------------------------ 1. Steam
class SteamSource(Source):
    key, name, kind = "steam", "Steam", "Official"
    short = "Steam"
    blurb = "Valve's own servers via SteamCMD. Some games need an account that owns them."
    batch = True
    RX = re.compile(r"Downloading item (\d+)|Success\. Downloaded item (\d+)|"
                    r"ERROR! Download item (\d+) failed \(([^)]*)\)")

    def _steamcmd(self, ctx):
        folder = os.path.join(ctx.app_dir, "steamcmd")
        exe = os.path.join(folder, "steamcmd.exe" if IS_WIN else "steamcmd.sh")
        if os.path.exists(exe):
            return exe
        ctx.log("Setting up SteamCMD (first run only)...")
        os.makedirs(folder, exist_ok=True)
        if IS_WIN:
            arc = os.path.join(folder, "steamcmd.zip")
            ctx.net.download("https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip", folder, "steamcmd.zip")
            with zipfile.ZipFile(arc) as z:
                z.extractall(folder)
        else:
            arc = os.path.join(folder, "steamcmd_linux.tar.gz")
            ctx.net.download("https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
                             folder, "steamcmd_linux.tar.gz")
            with tarfile.open(arc) as t:
                t.extractall(folder)
        os.remove(arc)
        ctx.log("Updating SteamCMD (one time, can take a minute)...")
        subprocess.run([exe, "+quit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=900)
        return exe

    def fetch_batch(self, items, ctx):
        try:
            exe = self._steamcmd(ctx)
        except Exception as e:
            raise SourceError(f"could not set up SteamCMD ({e})")
        staging = os.path.join(ctx.work, "steamcmd_downloads")
        user = ctx.cfg.get("steam_user", "").strip()
        # SteamCMD can hang (no connection, stuck login). Kill it after this long without disk activity.
        idle_limit = int(ctx.cfg.get("steam_idle_timeout") or (900 if user else 240))
        by_id = {it.id: it for it in items}
        for chunk in _batches(items, 150):
            if ctx.stop.is_set():
                raise Stopped()
            cmd = [exe, "+force_install_dir", staging, "+login", user or "anonymous"]
            for it in chunk:
                cmd += ["+workshop_download_item", it.app_id, it.id]
                ctx.status(it, "Steam", "Waiting for SteamCMD")
                stale = os.path.join(staging, "steamapps", "workshop", "content", it.app_id, it.id)
                shutil.rmtree(stale, ignore_errors=True)
            cmd += ["+quit"]
            results = {}
            hung = threading.Event()
            try:
                if user and not IS_WIN:
                    ctx.proc = _TerminalRun(cmd, ctx.work)    # a terminal window, for the password prompt
                    ctx.log("Steam: a terminal window opened. Enter your password / Steam Guard code there if asked.")
                elif user:
                    ctx.log("Steam: a console window opened. Enter your password / Steam Guard code there if asked.")
                    ctx.proc = subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                else:
                    ctx.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as e:
                raise SourceError(f"could not start SteamCMD ({e})")
            threading.Thread(target=self._watchdog, args=(ctx, ctx.proc, staging, idle_limit, hung),
                             daemon=True).start()
            if user:
                while ctx.proc.poll() is None and not ctx.stop.is_set() and not hung.is_set():
                    time.sleep(1)
                if ctx.stop.is_set() or hung.is_set():
                    ctx.proc.kill()
            else:
                for raw in ctx.proc.stdout:
                    line = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", "replace"))
                    for m in self.RX.finditer(line):
                        if m.group(1) and m.group(1) in by_id:
                            ctx.status(by_id[m.group(1)], "Steam", "Downloading from Steam")
                        elif m.group(2):
                            results[m.group(2)] = "ok"
                        elif m.group(3):
                            results[m.group(3)] = m.group(4)
                ctx.proc.wait()
            if ctx.stop.is_set():
                raise Stopped()
            if hung.is_set():
                ctx.log(f"Steam: SteamCMD showed no activity for {idle_limit}s and was stopped.")
            for it in chunk:
                src = os.path.join(staging, "steamapps", "workshop", "content", it.app_id, it.id)
                got = os.path.isdir(src) and bool(os.listdir(src))
                if got and results.get(it.id, "ok") == "ok":
                    shutil.rmtree(it.stage, ignore_errors=True)
                    os.makedirs(os.path.dirname(it.stage), exist_ok=True)
                    shutil.move(src, it.stage)
                    ctx.succeed(it, self, Hit(self.name, it.title, page=it.url))
                else:
                    reason = results.get(it.id) or ("SteamCMD hung (no connection?)" if hung.is_set()
                                                    else "not delivered")
                    hint = " (game probably has to be owned)" if reason == "Failure" else ""
                    ctx.fail(it, self, f"{reason}{hint}")

    @staticmethod
    def _watchdog(ctx, proc, staging, idle_limit, hung):
        """Kill SteamCMD if nothing on disk changes for idle_limit seconds."""
        def activity():
            total = 0
            for sub in ("steamapps/workshop/downloads", "steamapps/workshop/content", "steamapps/workshop/temp"):
                for root, _, files in os.walk(os.path.join(staging, sub)):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            return total
        last, idle = -1, 0
        while proc.poll() is None:
            time.sleep(5)
            if ctx.stop.is_set():
                return
            now = activity()
            idle = 0 if now != last else idle + 5
            last = now
            if idle >= idle_limit:
                hung.set()
                try:
                    proc.kill()
                except Exception:
                    pass
                return


# ------------------------------------------------------------------ 2. SkyMods
class SkyModsSource(Source):
    key, name, kind = "skymods", "SkyMods", "Workshop mirror"
    short = "SkyMods"
    blurb = "smods.ru / catalogue.smods.ru re-host Workshop mods. Matched by exact Workshop ID."
    SEARCHES = ("https://catalogue.smods.ru/?s={id}&app={app}", "https://smods.ru/?s={id}")
    GAP = 3.0            # seconds between SkyMods page requests, shared by all download threads
    LINK_RX = re.compile(r'href="(https?://(?:www\.)?modsbase\.com/[^"]+)"')

    def __init__(self):
        self.blocked = None
        self.lock = threading.Lock()

    def reset(self):
        self.blocked = None

    def _search(self, ctx, url):
        r = ctx.net.get(url, gap=self.GAP)
        if r.status != 200:
            raise SourceError(f"SkyMods search answered HTTP {r.status}")
        h = r.text
        if "<article" not in h and "post-list" not in h and "search" not in h[:3000].lower():
            raise SourceError("SkyMods sent an unexpected page instead of search results")
        return h

    def fetch(self, item, ctx):
        if self.blocked:
            raise SourceError(f"skipped: {self.blocked}")
        try:
            return self._fetch(item, ctx)
        except ChallengeError as e:
            with self.lock:
                if not self.blocked:
                    self.blocked = f"SkyMods' human check was not passed ({e.host})"
                    ctx.log(f"SkyMods: {e}. Skipping SkyMods for the rest of this run.")
            raise

    def _fetch(self, item, ctx):
        post = None
        for tpl in self.SEARCHES:
            h = self._search(ctx, tpl.format(id=item.id, app=item.app_id))
            for art in re.findall(r"<article.*?</article>", h, re.S):
                if item.id not in re.findall(r"filedetails/\?id=(\d+)", art):
                    continue
                link = self.LINK_RX.search(art)
                if link:
                    rev = re.search(r'skymods-item-date">([^<]+)<', art)
                    title = re.search(r'rel="bookmark"[^>]*>([^<]+)<', art)
                    post = (link.group(1), rev.group(1).strip() if rev else "",
                            title.group(1).strip() if title else item.title)
                    break
            if post:
                break
        if not post:
            return None
        url, revision, found_as = post
        ctx.status(item, self.name, f"Found (revision {revision}), opening file host")
        path = Modsbase.download(ctx, item, url)
        return Hit(self.name, found_as, updated=revision, page=url, note=unpack_if(ctx, path, item))


class Modsbase:
    """modsbase.com: page -> countdown (+ Turnstile human check since Oct 2026) -> form POST -> signed link."""

    CHECK_MARKERS = ("cf-turnstile", "g-recaptcha", "h-captcha")

    @staticmethod
    def download(ctx, item, page_url):
        r = ctx.net.get(page_url, gap=1.5)
        h = r.text
        if r.status != 200:
            raise SourceError(f"file host answered HTTP {r.status}")
        form = re.search(r'<form name="F1".*?</form>', h, re.S)
        if not form:
            raise SourceError("file host page layout changed (no download form)")
        f = form.group(0)
        if 'name="password"' in f:
            raise SourceError("file is password protected")
        if any(m in f for m in Modsbase.CHECK_MARKERS):
            # Every download now carries a human check. Only a real browser can pass it.
            ctx.status(item, "SkyMods", "Getting the download link in the check window")
            r2 = ctx.net.browser_form(page_url, "F1")
        else:
            data = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', f))
            sec = re.search(r'id="seconds"[^>]*>\s*(\d+)', h)
            wait = min(int(sec.group(1)), 120) if sec else 0
            for left in range(wait + 1, 0, -1):
                ctx.status(item, "SkyMods", f"File host countdown: {left}s")
                ctx.net._sleep(1)
            r2 = ctx.net.post(page_url, data=data, headers={"Referer": page_url, "Origin": "https://modsbase.com"})
        page = r2.text
        links = re.findall(r'href="(https?://[^"]+)"', page)
        direct = next((u for u in links if "X-Amz-Signature" in u or "response-content-disposition" in u), None)
        if not direct:
            fname = urllib.parse.unquote(page_url.rsplit("/", 1)[-1]).replace(".html", "")
            direct = next((u for u in links if fname and fname in urllib.parse.unquote(u)
                           and "modsbase.com" not in u), None)
        if not direct:
            if re.search(r"wrong captcha", page, re.I):
                raise SourceError("file host rejected the human check (Wrong captcha)")
            if re.search(r"you have to wait|wait \d+ (seconds|minutes) till next download", page, re.I):
                raise SourceError("file host asks to wait before the next download")
            raise SourceError("file host did not hand out a download link")
        direct = direct.replace("&amp;", "&")
        ctx.status(item, "SkyMods", "Downloading", progress=0.0)
        # the signed link changes every time; the file page doesn't, so a paused download can resume
        return ctx.net.download(direct, item.stage, progress=lambda p: ctx.status(item, "SkyMods", "Downloading", p),
                                key="modsbase:" + page_url)


def unpack_if(ctx, path, item):
    ctx.status(item, None, "Extracting")
    return unpack(path, item.stage)


# ------------------------------------------------------------------ 3. mod.io
class ModIOSource(Source):
    key, name, kind = "modio", "mod.io", "Official mod platform"
    short = "mod.io"
    blurb = "Matched by game and mod name. Needs a free API key (mod.io > account > API)."
    needs = "modio_key"

    def fetch(self, item, ctx):
        key = ctx.cfg.get("modio_key", "").strip()
        q = urllib.parse.quote
        base = "https://api.mod.io/v1"
        games = ctx.net.get_json(f"{base}/games?api_key={q(key)}&_q={q(item.game)}&_limit=10", gap=0.5)["data"]
        g = max(games, key=lambda x: similarity(item.game, x["name"]), default=None)
        if not g or similarity(item.game, g["name"]) < 0.8:
            return None
        mods = ctx.net.get_json(f"{base}/games/{g['id']}/mods?api_key={q(key)}&_q={q(clean_title(item.title))}"
                                f"&_sort=-date_updated&_limit=20", gap=0.5)["data"]
        cands = [(similarity(item.title, m["name"]), m) for m in mods if m.get("modfile")]
        if not cands:
            return None
        score, m = max(cands, key=lambda t: (t[0], t[1].get("date_updated", 0)))
        if score < 0.8:
            return None
        mf = m["modfile"]
        ctx.status(item, self.name, f"Matched \"{m['name']}\" ({score:.0%}), downloading", 0.0)
        path = ctx.net.download(mf["download"]["binary_url"], item.stage, mf.get("filename"),
                                progress=lambda p: ctx.status(item, self.name, "Downloading", p))
        return Hit(self.name, m["name"], mf.get("version") or "", str(mf.get("date_added", "")),
                   m.get("profile_url", ""), unpack_if(ctx, path, item))


# ------------------------------------------------------------------ 4. Thunderstore
class ThunderstoreSource(Source):
    key, name, kind = "thunderstore", "Thunderstore", "Mod hub"
    short = "Thunderstore"
    blurb = "Matched by game and mod name. Mostly Unity games (Valheim, Lethal Company...)."
    _communities = None
    _lock = threading.Lock()

    def fetch(self, item, ctx):
        with ThunderstoreSource._lock:
            self._load_communities(ctx)
        return self._fetch(item, ctx)

    def _load_communities(self, ctx):
        if ThunderstoreSource._communities is None:
            out, url, n = [], "https://thunderstore.io/api/experimental/community/", 0
            while url and n < 40:
                d = ctx.net.get_json(url, gap=0.3)
                out += [(c["identifier"], c["name"]) for c in d.get("results", [])]
                url, n = (d.get("pagination") or {}).get("next_link"), n + 1
            ThunderstoreSource._communities = out

    def _fetch(self, item, ctx):
        best = max(ThunderstoreSource._communities,
                   key=lambda c: max(similarity(item.game, c[1]), similarity(item.game, c[0])), default=None)
        if not best or max(similarity(item.game, best[1]), similarity(item.game, best[0])) < 0.85:
            return None
        q = urllib.parse.quote(clean_title(item.title))
        d = ctx.net.get_json(f"https://thunderstore.io/api/cyberstorm/listing/{best[0]}/?q={q}"
                             "&ordering=most-downloaded", gap=0.5)
        cands = [(similarity(item.title, p["name"]), p) for p in d.get("results", []) if not p.get("is_deprecated")]
        if not cands:
            return None
        score, p = max(cands, key=lambda t: t[0])
        if score < 0.8:
            return None
        pkg = ctx.net.get_json(f"https://thunderstore.io/api/experimental/package/{p['namespace']}/{p['name']}/")
        latest = pkg["latest"]
        ctx.status(item, self.name, f"Matched \"{p['name']}\" ({score:.0%}), downloading", 0.0)
        path = ctx.net.download(latest["download_url"], item.stage,
                                f"{p['namespace']}-{p['name']}-{latest['version_number']}.zip",
                                progress=lambda x: ctx.status(item, self.name, "Downloading", x))
        return Hit(self.name, p["name"], latest["version_number"], latest.get("date_created", ""),
                   pkg.get("package_url", ""), unpack_if(ctx, path, item))


# ------------------------------------------------------------------ 5. ModDB
class ModDBSource(Source):
    key, name, kind = "moddb", "ModDB", "Mod hub"
    short = "ModDB"
    blurb = "Matched by game and mod name; takes the newest file. Mostly bigger mods."
    B = "https://www.moddb.com"

    def _anchors(self, h, prefix):
        return [(u, re.sub(r"\s+", " ", t).strip()) for u, t in
                re.findall(r'<a href="(' + prefix + r'[a-z0-9\-]+)"[^>]*>([^<]{2,120})</a>', h)
                if not u.rsplit("/", 1)[-1] in ("top", "latest", "add")]

    def fetch(self, item, ctx):
        q = urllib.parse.quote_plus
        h = ctx.net.get(f"{self.B}/games?filter=t&kw={q(item.game)}", gap=1.0).text
        games = self._anchors(h, "/games/")
        g = max(games, key=lambda x: similarity(item.game, x[1]), default=None)
        if not g or similarity(item.game, g[1]) < 0.85:
            return None
        kw = q(clean_title(item.title))
        cands = []
        h = ctx.net.get(f"{self.B}{g[0]}/mods?filter=t&kw={kw}", gap=1.0).text
        cands += [("mod", u, t) for u, t in self._anchors(h, "/mods/")]
        h = ctx.net.get(f"{self.B}{g[0]}/addons?filter=t&kw={kw}", gap=1.0).text
        cands += [("addon", u, t) for u, t in self._anchors(h, g[0] + "/addons/")]
        scored = [(similarity(item.title, t), kind, u, t) for kind, u, t in cands]
        scored = [s for s in scored if s[0] >= 0.8]
        if not scored:
            return None
        score, kind, url, title = max(scored, key=lambda s: s[0])
        if kind == "mod":
            h = ctx.net.get(f"{self.B}{url}/downloads", gap=1.0).text
            files = [u for u, _ in self._anchors(h, url + "/downloads/") if not u.endswith("/feed")]
            if not files:
                raise SourceError(f"\"{title}\" has no downloadable files on ModDB")
            file_page = files[0]                      # ModDB lists newest first
        else:
            file_page = url
        fp = ctx.net.get(self.B + file_page, gap=1.0).text
        start = re.search(r'href="(/downloads/start/\d+[^"]*)"', fp)
        if not start:
            raise SourceError("ModDB file page has no download button")
        meta = dict((k, re.sub(r"<[^>]+>", "", v).strip()) for k, v in
                    re.findall(r"<h5>(Filename|Added|Updated)</h5>\s*<span[^>]*>(.*?)</span>", fp, re.S))
        sp = ctx.net.get(self.B + start.group(1), gap=1.0, headers={"Referer": self.B + file_page}).text
        mirror = re.search(r'href="(/downloads/mirror/[^"]+)"', sp)
        if not mirror:
            raise SourceError("ModDB did not offer a mirror")
        r = ctx.net.get(self.B + mirror.group(1), allow_redirects=False,
                        headers={"Referer": self.B + start.group(1)})
        direct = r.headers.get("location")
        if not direct:
            raise SourceError("ModDB mirror did not redirect to a file")
        ctx.status(item, self.name, f"Matched \"{title}\" ({score:.0%}), downloading", 0.0)
        path = ctx.net.download(direct, item.stage, meta.get("Filename"),
                                progress=lambda x: ctx.status(item, self.name, "Downloading", x))
        return Hit(self.name, title, "", meta.get("Updated") or meta.get("Added", ""), self.B + file_page,
                   unpack_if(ctx, path, item))


# ------------------------------------------------------------------ 6. GitHub Releases
class GitHubSource(Source):
    key, name, kind = "github", "GitHub Releases", "Creator-hosted"
    short = "GitHub"
    blurb = "Repositories whose name matches the mod and mention the game. A token raises the rate limit."

    def fetch(self, item, ctx):
        token = ctx.cfg.get("github_token", "").strip()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        gt = tokens(item.game)
        gkey = max(gt, key=len) if gt else ""
        q = urllib.parse.quote(f"{clean_title(item.title)} {gkey} in:name,description,readme")
        r = ctx.net.get(f"https://api.github.com/search/repositories?q={q}&per_page=10", headers=headers, gap=2.0)
        if r.status == 403:
            raise SourceError("GitHub rate limit reached (add a token in Settings)")
        if r.status != 200:
            raise SourceError(f"GitHub answered HTTP {r.status}")
        cands = []
        for repo in r.json().get("items", []):
            if repo.get("archived") or repo.get("fork"):
                continue
            blob = " ".join([repo.get("full_name", ""), repo.get("description") or "",
                             " ".join(repo.get("topics", []))]).lower()
            s = similarity(item.title, strip_game_words(repo["name"], item.game))
            if s >= 0.8 and (not gkey or gkey in blob):
                cands.append((s, repo))
        if not cands:
            return None
        score, repo = max(cands, key=lambda t: (t[0], t[1].get("pushed_at", "")))
        rr = ctx.net.get(f"https://api.github.com/repos/{repo['full_name']}/releases/latest", headers=headers)
        if rr.status != 200:
            # No release: many mods live directly in the repository. Use the main branch, but only if
            # it really is a mod (has a descriptor.mod somewhere), so tools/source repos are skipped.
            branch = repo.get("default_branch") or "main"
            tr = ctx.net.get(f"https://api.github.com/repos/{repo['full_name']}/git/trees/{branch}?recursive=1",
                             headers=headers)
            paths = [t.get("path", "") for t in tr.json().get("tree", [])] if tr.status == 200 else []
            if not any(p.lower().endswith("descriptor.mod") for p in paths):
                return None
            rel = {"tag_name": f"{branch} (latest commit)", "published_at": repo.get("pushed_at", ""), "assets": [],
                   "zipball_url": f"https://api.github.com/repos/{repo['full_name']}/zipball/{branch}"}
        else:
            rel = rr.json()
        pref = [".zip", ".7z", ".rar"]
        assets = sorted(rel.get("assets", []), key=lambda a: next(
            (i for i, e in enumerate(pref) if a["name"].lower().endswith(e)), 9))
        if assets:
            url, fn = assets[0]["browser_download_url"], assets[0]["name"]
        else:
            url, fn = rel.get("zipball_url"), f"{repo['name']}-{rel.get('tag_name', 'latest')}.zip"
        ctx.status(item, self.name, f"Matched {repo['full_name']} ({score:.0%}), downloading", 0.0)
        path = ctx.net.download(url, item.stage, fn, headers=headers,
                                progress=lambda x: ctx.status(item, self.name, "Downloading", x))
        return Hit(self.name, repo["full_name"], rel.get("tag_name", ""), rel.get("published_at", ""),
                   repo["html_url"], unpack_if(ctx, path, item))


# ------------------------------------------------------------------ 7. steamworkshop.download
class SWDownloadSource(Source):
    key, name, kind = "swdownload", "steamworkshop.download", "Workshop mirror"
    short = "SW.download"
    blurb = "Hands out copies it cached earlier, matched by exact Workshop ID. Can't fetch new ones any more."
    BASE = "http://steamworkshop.download"

    def fetch(self, item, ctx):
        r = ctx.net.post(f"{self.BASE}/online/steamonline.php", data={"item": item.id, "app": item.app_id},
                         headers={"Referer": f"{self.BASE}/download/view/{item.id}",
                                  "X-Requested-With": "XMLHttpRequest"}, timeout=180, gap=2.0)
        text = re.sub(r"<[^>]+>", " ", r.text)
        links = [u for u in re.findall(r'href=[\'"]([^\'"]+)[\'"]', r.text) if not u.startswith("#")]
        files = [urllib.parse.urljoin(self.BASE, u) for u in links if re.search(r"\.(zip|7z|rar)(\?|$)", u, re.I)]
        if not files:
            msg = re.sub(r"\s+", " ", text).strip()[:120] or f"HTTP {r.status}"
            raise SourceError(f"site says: {msg}")
        ctx.status(item, self.name, "Downloading", 0.0)
        path = ctx.net.download(files[0], item.stage,
                                progress=lambda x: ctx.status(item, self.name, "Downloading", x))
        return Hit(self.name, item.title, page=f"{self.BASE}/download/view/{item.id}", note=unpack_if(ctx, path, item))


ALL_SOURCES = [SteamSource(), SkyModsSource(), ModIOSource(), ThunderstoreSource(),
               ModDBSource(), GitHubSource(), SWDownloadSource()]
SOURCE_BY_KEY = {s.key: s for s in ALL_SOURCES}
DEFAULT_ORDER = [s.key for s in ALL_SOURCES]
