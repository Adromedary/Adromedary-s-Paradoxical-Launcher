"""
The download engine. GUI-independent: everything is reported through `emit(event, *args)`.

Events:
    ("add", item)                                    a row to show (mod or collection)
    ("status", item_id, state, text, progress|None)
    ("log", message)
    ("progress", done, total)
    ("finished", summary_dict)

Flow: resolve links on Steam (expanding collections) -> for each site in the chain, in order,
try every mod that is still missing (up to `workers` mods at the same time) -> install each
finished download into the game's mod folder (or the downloads folder for other games).
"""
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import installer
import launcher as LA
import net as N
import sources as S

MAX_COLLECTION_DEPTH = 3


def remove_old_copies(mod_dir, new_id, olds):
    """After an update is installed as <id>.mod + <id>/, delete the previous copies completely.
    A folder is only deleted if it is inside the mod folder, isn't the new one, and no remaining
    .mod entry still points at it (so Steam's own Workshop folders are never touched)."""
    import modscan
    new_mod = os.path.normcase(os.path.join(mod_dir, new_id + ".mod"))
    new_dir = os.path.normcase(os.path.join(mod_dir, new_id))
    removed = []
    for old in olds:
        mf = old.get("modfile") or ""
        if mf and os.path.normcase(mf) != new_mod and os.path.isfile(mf):
            os.remove(mf)
            removed.append(os.path.basename(mf))
    still_used = set()
    for f in os.listdir(mod_dir):
        if f.lower().endswith(".mod"):
            try:
                text = installer.read_text(os.path.join(mod_dir, f))
            except OSError:
                continue
            p = modscan._resolve(mod_dir, installer.descriptor_value(text, "path") or
                                 installer.descriptor_value(text, "archive"))
            if p:
                still_used.add(os.path.normcase(os.path.normpath(p)))
    for old in olds:
        folder = old.get("folder") or ""
        key = os.path.normcase(os.path.normpath(folder)) if folder else ""
        if (folder and os.path.exists(folder) and key != new_dir and key not in still_used
                and modscan._inside(folder, mod_dir) and key != os.path.normcase(os.path.normpath(mod_dir))):
            shutil.rmtree(folder) if os.path.isdir(folder) else os.remove(folder)
            removed.append(os.path.basename(folder))
    return removed


def same_game(steam_name, folder_name):
    """'Imperator: Rome' (Steam) belongs in 'Imperator' (Documents); CK2 never matches CK3."""
    a, b = set(S.tokens(steam_name)), set(S.tokens(folder_name))
    if not a or not b:
        return False
    return a <= b or b <= a or S.similarity(steam_name, folder_name) >= 0.8


class Item:
    def __init__(self, id, title="", app_id="", game="", updated=0, is_collection=False, parent=""):
        self.id, self.title, self.app_id, self.game = id, title, app_id, game
        self.updated, self.is_collection, self.parent = updated, is_collection, parent
        self.state, self.hit = "Queued", None
        self.stage = ""          # where a source saves its download
        self.mode = "install"    # "install" into the mod folder, or "save" into the downloads folder
        self.final = ""          # destination for "save" mode
        self.tried = []          # [(source name, reason)]

    @property
    def url(self):
        return f"https://steamcommunity.com/sharedfiles/filedetails/?id={self.id}"

    def tried_names(self):
        return {n for n, _ in self.tried}

    FIELDS = ("id", "title", "app_id", "game", "updated", "is_collection", "parent", "state", "mode", "final", "tried")

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        it = cls(d["id"])
        for k in cls.FIELDS:
            if k in d:
                setattr(it, k, d[k])
        it.tried = [tuple(t) for t in it.tried]
        return it


RESUMABLE = ("Paused", "Interrupted", "Queued", "Working")


def load_queue(path):
    """The saved queue of an unfinished run, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            q = json.load(f)
        items = [Item.from_dict(d) for d in q.get("items", [])]
        if any(it.state in RESUMABLE and not it.is_collection for it in items):
            q["items"] = items
            return q
    except Exception:
        pass
    return None


def discard_queue(work):
    for p in (os.path.join(work, "queue.json"),):
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(os.path.join(work, "staging"), ignore_errors=True)


class Context:
    """What a source sees while it works."""

    def __init__(self, engine):
        self.engine = engine
        self.net, self.cfg, self.work = engine.net, engine.cfg, engine.work
        self.app_dir, self.stop = engine.app_dir, engine.stop
        self.proc = None

    def log(self, msg):
        self.engine.emit("log", msg)

    def status(self, item, source, text, progress=None):
        self.engine.emit("status", item.id, "Working", (f"{source}: " if source else "") + text, progress)

    def succeed(self, item, source, hit):
        self.engine._succeed(item, source, hit)

    def fail(self, item, source, reason):
        self.engine._fail(item, source, reason)


class Engine:
    def __init__(self, cfg, app_dir, emit, bridge=None):
        self.cfg, self.app_dir, self.emit = cfg, app_dir, emit
        self.stop = threading.Event()
        self.work = os.path.join(app_dir, ".work")
        self.mod_dir = (cfg.get("mod_dir") or "").strip()
        self.other_dir = (cfg.get("other_dir") or "").strip() or os.path.join(app_dir, "downloads")
        self.registry = os.path.join(app_dir, "installed.json")
        self.workers = max(1, min(5, int(cfg.get("workers", 1) or 1)))
        use_bridge = bridge if cfg.get("check_window", True) else None
        self.net = N.Net(bridge=use_bridge, stop=self.stop, log=lambda m: self.emit("log", m),
                         verify_timeout=int(cfg.get("verify_timeout", 300)))
        self.ctx = Context(self)
        self.items, self.collections = [], []
        self.mod_game = installer.game_of_mod_dir(self.mod_dir) if self.mod_dir else ""
        self.mod_appid = str(LA.game_info(self.mod_game).get("appid", "")) if self.mod_game else ""
        # Workshop IDs already in the mod folder in any form (e.g. Steam's own ugc_<id>.mod)
        self.have_ids = set(cfg.get("have_ids", []))
        # updates: these IDs are fetched even if installed; afterwards their old copies are removed
        self.force_ids = set(cfg.get("force_ids", []))
        self.replace = cfg.get("replace", {})          # {workshop id: [{"modfile": .., "folder": ..}]}
        self.pause = False
        self.queue_path = os.path.join(self.work, "queue.json")
        self._qlock = threading.Lock()

    # ---------------------------------------------------------------- control
    def request_stop(self, pause=False):
        """pause=True: keep everything downloaded so far and the queue, to resume later."""
        self.pause = pause
        self.stop.set()
        p = self.ctx.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def chain(self):
        order = [k for k in self.cfg.get("order", S.DEFAULT_ORDER) if k in S.SOURCE_BY_KEY]
        order += [k for k in S.DEFAULT_ORDER if k not in order]
        enabled = self.cfg.get("enabled", {})
        return [S.SOURCE_BY_KEY[k] for k in order if enabled.get(k, True)]

    def _count_done(self):
        return sum(1 for i in self.items if i.state in ("Done", "Already"))

    # ---------------------------------------------------------------- run
    def run(self, ids, resume=None):
        """ids: Workshop IDs to fetch. resume: a saved queue (load_queue) to continue; its items keep
        what they already tried and what they downloaded so far."""
        t0 = time.time()
        summary = {"by_source": {}, "already": 0, "missing": 0, "stopped": False, "mods": 0,
                   "collections": 0, "installed": 0, "saved": 0, "paused": 0, "interrupted": 0}
        resumable = False
        try:
            os.makedirs(self.work, exist_ok=True)
            chain = self.chain()
            if not chain:
                raise N.SourceError("no download sites are switched on (Settings)")
            for src in chain:
                src.reset()
            self.emit("log", "Chain: " + "  >  ".join(s.name for s in chain)
                      + f"   ({self.workers} at a time)")
            if self.mod_dir:
                self.emit("log", f"Installing into: {self.mod_dir}"
                          + (f"  ({self.mod_game})" if self.mod_game else ""))
            kept = set()
            if resume:
                kept = self._restore(resume)
            fresh = [i for i in ids if i not in kept]
            if fresh:
                self._resolve(fresh)
            summary["mods"], summary["collections"] = len(self.items), len(self.collections)
            todo = self._prepare(kept)
            self._save_queue()
            total = len(self.items)
            self.emit("progress", self._count_done(), total)
            for src in chain:
                if self.stop.is_set():
                    break
                here = [it for it in todo if it.state not in ("Done", "Interrupted")
                        and src.name not in it.tried_names()]
                if not here:
                    continue
                if src.needs and not self.cfg.get(src.needs, "").strip():
                    self.emit("log", f"{src.name}: skipped, no {src.needs.replace('_', ' ')} in Settings")
                    for it in here:
                        it.tried.append((src.name, "skipped (not set up)"))
                    continue
                self.emit("log", f"--- {src.name}: trying {len(here)} mod(s) ---")
                if src.batch:
                    try:
                        src.fetch_batch(here, self.ctx)
                    except N.Stopped:
                        break
                    except Exception as e:
                        self.emit("log", f"{src.name}: {type(e).__name__}: {e}")
                        for it in here:
                            if it.state not in ("Done", "Interrupted") and src.name not in it.tried_names():
                                self._fail(it, src, str(e))
                else:
                    self._run_parallel(src, here, total)
                self._save_queue()
                self.emit("progress", self._count_done(), total)
            for it in self.items:
                if it.state == "Done":
                    name = it.hit.source if it.hit else "an earlier session"
                    summary["by_source"][name] = summary["by_source"].get(name, 0) + 1
                    summary["installed" if it.mode == "install" else "saved"] += 1
                elif it.state == "Already":
                    summary["already"] += 1
                elif it.state == "Missing":
                    summary["missing"] += 1
                elif it.state == "Interrupted":
                    summary["interrupted"] += 1
                    resumable = True
                elif self.stop.is_set():
                    if self.pause:
                        it.state = "Paused"
                        summary["paused"] += 1
                        resumable = True
                        self.emit("status", it.id, "Paused", "Paused; Resume continues where it stopped", None)
                    else:
                        it.state = "Stopped"
                        self.emit("status", it.id, "Stopped", "Stopped before it was found", None)
                else:
                    it.state = "Not found"
                    summary["missing"] += 1
                    tried = ", ".join(dict.fromkeys(n for n, _ in it.tried)) or "nothing"
                    self.emit("status", it.id, "Not found", f"Not on any enabled site (tried {tried})", None)
            summary["done_ids"] = [it.id for it in self.items if it.state == "Done"]
            summary["installed_ids"] = [it.id for it in self.items if it.state == "Done" and it.mode == "install"]
            summary["already_ids"] = [it.id for it in self.items if it.state == "Already"]
            summary["stopped"] = self.stop.is_set()
            summary["report"] = self._write_report()
        except Exception as e:
            self.emit("log", f"Error: {type(e).__name__}: {e}")
            summary["error"] = str(e)
        finally:
            if resumable:
                self._save_queue()
            else:
                discard_queue(self.work)
        summary["resumable"] = resumable
        summary["seconds"] = round(time.time() - t0)
        self.emit("finished", summary)
        return summary

    def _restore(self, q):
        """Put a saved queue back on the list. Returns the IDs restored."""
        self.force_ids |= set(q.get("force_ids", []))
        for k, v in (q.get("replace") or {}).items():
            self.replace.setdefault(k, v)
        kept = set()
        for it in q["items"]:
            if it.is_collection:
                self.collections.append(it)
                self.emit("add", it)
                self.emit("status", it.id, "Collection", f"{it.game} collection", None)
            else:
                if it.state in ("Working", "Queued", "Stopped"):
                    it.state = "Paused"
                self.items.append(it)
                self.emit("add", it)
                if it.state in ("Paused", "Interrupted"):
                    self.emit("status", it.id, "Queued", "Resuming", None)
                elif it.state in ("Done", "Already"):
                    self.emit("status", it.id, it.state, "Finished in an earlier session", None)
                elif it.state in ("Missing", "Not found"):
                    self.emit("status", it.id, "Not found", "Not found in an earlier session", None)
            kept.add(it.id)
        n = sum(1 for it in self.items if it.state in ("Paused", "Interrupted"))
        self.emit("log", f"Resuming {n} unfinished mod(s); downloads continue where they stopped.")
        return kept

    def _save_queue(self):
        with self._qlock:
            try:
                os.makedirs(self.work, exist_ok=True)
                data = {"saved": int(time.time()), "mod_dir": self.mod_dir,
                        "force_ids": sorted(self.force_ids), "replace": self.replace,
                        "items": [it.to_dict() for it in self.collections + self.items]}
                tmp = self.queue_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, self.queue_path)
            except Exception:
                pass

    def _run_parallel(self, src, todo, total):
        if self.workers == 1:
            for it in todo:
                if self.stop.is_set():
                    break
                self._try_one(src, it)
                self.emit("progress", self._count_done(), total)
            return
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=src.key) as pool:
            futures = [pool.submit(self._try_one, src, it) for it in todo]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:                   # _try_one already reports; this is a safety net
                    self.emit("log", f"{src.name}: unexpected {type(e).__name__}: {e}")
                self.emit("progress", self._count_done(), total)

    # ---------------------------------------------------------------- steps
    def _resolve(self, ids):
        """Expand collections (recursively, cycle-safe) and look every mod up on Steam's public API."""
        self.emit("log", f"Looking up {len(ids)} link(s) on Steam...")
        seen, frontier, depth = set(), [], 0
        for i in ids:
            if i not in seen:
                seen.add(i)
                frontier.append((i, ""))
        while frontier and not self.stop.is_set():
            fids = [f for f, _ in frontier]
            details = S.steam_details(self.net, fids)
            colls = S.steam_collection_children(self.net, fids)
            nxt = []
            for fid, parent in frontier:
                d = details.get(fid)
                if not d:
                    it = Item(fid, f"Workshop item {fid}", parent=parent)
                    it.state = "Missing"
                    it.tried.append(("Steam", "not listed (removed or private)"))
                    self.items.append(it)
                    self.emit("add", it)
                    self.emit("status", fid, "Not found", "Steam does not list this item (removed or private)", None)
                    continue
                app = str(d.get("consumer_app_id", ""))
                is_coll = fid in colls or d.get("creator_app_id") == S.COLLECTION_CREATOR_APP
                it = Item(fid, d.get("title") or fid, app, S.game_name(self.net, app),
                          d.get("time_updated", 0), is_coll, parent)
                self.emit("add", it)
                if is_coll:
                    kids = colls.get(fid, [])
                    fresh = [k for k in kids if k not in seen] if depth + 1 <= MAX_COLLECTION_DEPTH else []
                    for k in fresh:
                        seen.add(k)
                        nxt.append((k, fid))
                    self.collections.append(it)
                    self.emit("status", fid, "Collection", f"{it.game} collection: {len(kids)} entries", None)
                    self.emit("log", f"Collection \"{it.title}\": {len(kids)} entries, {len(fresh)} new")
                else:
                    self.items.append(it)
            frontier, depth = nxt, depth + 1

    def _belongs_to_mod_dir(self, it):
        if not self.mod_dir:
            return False
        if not self.mod_game:                 # a custom folder: trust the user
            return True
        if self.mod_appid and str(it.app_id or ""):   # Steam's app ID says for sure which game it's for
            return str(it.app_id) == self.mod_appid
        return same_game(it.game, self.mod_game)

    def _prepare(self, kept=()):
        todo, other_games = [], set()
        for it in self.items:
            it.stage = os.path.join(self.work, "staging", it.id)
            if it.state in ("Missing", "Done", "Already", "Not found"):
                continue
            if it.id in kept and it.state in ("Paused", "Interrupted"):
                it.state = "Queued"
                todo.append(it)                    # its partial download is still in its stage folder
                continue
            shutil.rmtree(it.stage, ignore_errors=True)
            if self._belongs_to_mod_dir(it):
                it.mode = "install"
                have = installer.is_installed(it, self.mod_dir)
                where = "Already in your mod folder"
                if not have and it.id in self.have_ids:
                    have, where = True, "Already in your mod folder (installed by Steam or another tool)"
            else:
                it.mode = "save"
                it.final = os.path.join(self.other_dir, N.safe_name(it.game), f"{N.safe_name(it.title)} [{it.id}]")
                have = os.path.isdir(it.final) and bool(os.listdir(it.final))
                where = "Already in the downloads folder"
                if self.mod_dir:
                    other_games.add(it.game)
            if have and self.cfg.get("skip_existing", True) and it.id not in self.force_ids:
                it.state = "Already"
                self.emit("status", it.id, "Already", f"{where}, skipped", None)
                continue
            todo.append(it)
        for g in sorted(other_games):
            self.emit("log", f"{g} mods are not for this mod folder; they go to {self.other_dir}")
        self.emit("log", f"{len(todo)} mod(s) to fetch, {len(self.items) - len(todo)} skipped or missing")
        return todo

    def _try_one(self, src, it):
        if self.stop.is_set() or it.state == "Done":
            return
        self.emit("status", it.id, "Working", f"{src.name}: searching", None)
        try:
            hit = src.fetch(it, self.ctx)
        except N.Stopped:
            if not self.pause:
                shutil.rmtree(it.stage, ignore_errors=True)
            return
        except N.Interrupted as e:
            it.state = "Interrupted"
            self.emit("status", it.id, "Interrupted", f"{src.name}: {e}", None)
            self.emit("log", f"  ..  {it.title}: {src.name}: {e}")
            self._save_queue()
            return
        except N.SourceError as e:
            self._fail(it, src, str(e))
            return
        except Exception as e:
            self._fail(it, src, f"{type(e).__name__}: {e}")
            return
        if hit:
            self._succeed(it, src, hit)
        else:
            self._fail(it, src, "no match")

    def _succeed(self, it, src, hit):
        try:
            if it.mode == "install":
                self.emit("status", it.id, "Working", f"{hit.source}: installing", None)
                note = installer.install(it, it.stage, self.mod_dir, hit.source, self.registry)
                where = "Installed"
                if it.id in self.replace:
                    removed = remove_old_copies(self.mod_dir, it.id, self.replace[it.id])
                    if removed:
                        note += f"; old version removed ({', '.join(removed)})"
                    where = "Updated"
            else:
                if os.path.isdir(it.final):
                    shutil.rmtree(it.final)
                os.makedirs(os.path.dirname(it.final), exist_ok=True)
                shutil.move(it.stage, it.final)
                with open(os.path.join(it.final, "SOURCE.txt"), "w", encoding="utf-8") as f:
                    f.write(f"Mod            : {it.title}\nGame           : {it.game}\n"
                            f"Steam Workshop : {it.url}\nDownloaded from: {hit.source}\n"
                            f"Matched as     : {hit.found_as} {hit.version}\nSource date    : {hit.updated}\n"
                            f"Source page    : {hit.page}\nSaved          : {time.strftime('%Y-%m-%d %H:%M')}\n")
                note, where = "saved", "Saved"
        except Exception as e:
            self._fail(it, src, f"downloaded, but could not be placed: {type(e).__name__}: {e}")
            return
        finally:
            shutil.rmtree(it.stage, ignore_errors=True)
        it.state, it.hit = "Done", hit
        extra = f" ({hit.updated})" if hit.updated and hit.source != "Steam" else ""
        self.emit("status", it.id, "Done", f"{where} from {hit.source}{extra}", None)
        self.emit("log", f"  OK  {it.title}  <-  {hit.source}{extra}  [{note}]")
        self._save_queue()

    def _fail(self, it, src, reason):
        it.tried.append((src.name, reason))
        shutil.rmtree(it.stage, ignore_errors=True)
        self.emit("status", it.id, "Working", f"{src.name}: {reason}. Moving on", None)
        self.emit("log", f"  --  {it.title}: {src.name}: {reason}")

    def _write_report(self):
        missing = [it for it in self.items if it.state in ("Not found", "Missing")]
        path = os.path.join(self.app_dir, "not_found.txt")
        if not missing:
            if os.path.exists(path):
                os.remove(path)
            return ""
        with open(path, "w", encoding="utf-8") as f:
            f.write("Mods no enabled site could deliver\n\n")
            for it in missing:
                f.write(f"{it.title}  [{it.game}]\n  {it.url}\n")
                for name, reason in it.tried:
                    f.write(f"    {name}: {reason}\n")
                f.write("\n")
        self.emit("log", f"List of mods not found: {path}")
        return path
