"""The Crashes tab: what the game was doing when it crashed, which mods are most likely to blame (with
the evidence), and a step-by-step culprit hunt for when the logs can't tell. Ties into the Conflicts
tab (each suspect's conflicts, compatch search and reports), Playsets and Library."""
import os
import shutil
import threading
import time
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

import analysis as A
import crash as C
import installer
import launcher as LA
import roles as R
from gui_common import (ACCENT, ACCENT_SOFT, APP_DIR, APP_NAME, BORDER, CARD, CRIT, DETAIL_WIDTH, ERR_SOFT, MUTED,
                        MUTED_SOFT, OK, OK_SOFT, RIGHT_CLICK, SEV_COLOR, SEV_ICON, TEXT, WARN, WARN_SOFT, DetailPane,
                        Split, Tree, button, copy_text, font, icon, open_folder, page_frame, popup_menu, px,
                        row_picture)

SURE_COLOR = {"likely": (CRIT, ERR_SOFT), "possible": (WARN, WARN_SOFT), "unlikely": (MUTED, MUTED_SOFT)}
SURE_TAG = {"likely": "critical", "possible": "high", "unlikely": "muted"}
SESSION = "Last session's errors (no crash)"
HUNT_PLAYSET = "Crash test"


def _when(t):
    if not t:
        return "?"
    d = time.time() - t
    stamp = time.strftime("%d %b %H:%M", time.localtime(t))
    if d < 3600:
        return f"{stamp} ({int(d // 60)} min ago)"
    if d < 86400:
        return f"{stamp} ({int(d // 3600)} h ago)"
    return f"{stamp} ({int(d // 86400)} days ago)"


def _mb(n):
    return f"{n / 1048576:.0f} MB" if n >= 1048576 else f"{n // 1024} KB"


class CrashPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.crashes = []                    # crash.Crash, newest first
        self.current = None                  # the Crash (or Session) shown
        self.results = {}                    # folder -> crash.Result
        self.busy = set()
        self.by_row = {}
        self.dirty = True
        # every crash and every game that worked, with their mods: the strongest evidence there is
        self.history = C.History(os.path.join(APP_DIR, "crash_history.json"))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ---- the picker and the tools
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        self.pick = ctk.CTkOptionMenu(head, values=["-"], width=360, height=32, fg_color=CARD, button_color=CARD,
                                      button_hover_color=BORDER, text_color=TEXT, font=font(12, "bold"),
                                      dropdown_font=font(12), dynamic_resizing=False, command=self._picked,
                                      corner_radius=9)
        self.pick.grid(row=0, column=0, sticky="w")
        tools = ctk.CTkFrame(head, fg_color="transparent")
        tools.grid(row=0, column=2, sticky="e")
        self.hunt_btn = button(tools, "Find the culprit", self.start_hunt, primary=True, icon_name="wand", width=150,
                               height=32, tip="Turn half the suspects off, play, answer; repeat until one mod is left")
        self.hunt_btn.pack(side="left", padx=(0, 6))
        self.report_btn = button(tools, "Save crash report", self.save_report, icon_name="log", width=160, height=32,
                                 tip="A Markdown report with everything found, ending with a prompt for an AI chat")
        self.report_btn.pack(side="left", padx=(0, 6))
        self.folder_btn = button(tools, "", self._open_folder, icon_name="folder", width=34, height=32,
                                 tip="Open this crash's folder")
        self.folder_btn.pack(side="left", padx=(0, 6))
        self.del_btn = button(tools, "", self.delete_crash, icon_name="trash", width=34, height=32, danger=True,
                              tip="Delete this crash's folder (logs, minidump and a copy of the save)")
        self.del_btn.pack(side="left", padx=(0, 6))
        button(tools, "", self.refresh, icon_name="refresh", width=34, height=32,
               tip="Look for new crashes").pack(side="left")

        # ---- the summary
        self.summary = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        self.summary.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.summary.grid_columnconfigure(1, weight=1)
        self.sum_icon = ctk.CTkLabel(self.summary, text="", image=icon("crash", 30, CRIT), width=50, height=50,
                                     corner_radius=25, fg_color=ERR_SOFT)
        self.sum_icon.grid(row=0, column=0, rowspan=3, sticky="n", padx=(14, 12), pady=14)
        self.sum_title = ctk.CTkLabel(self.summary, text="", text_color=TEXT, font=font(15, "bold"), anchor="w",
                                      justify="left")
        self.sum_title.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=(12, 0))
        self.sum_text = ctk.CTkLabel(self.summary, text="", text_color=MUTED, font=font(12), anchor="w",
                                     justify="left")
        self.sum_text.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(2, 0))
        self.chip_row = ctk.CTkFrame(self.summary, fg_color="transparent")
        self.chip_row.grid(row=2, column=1, sticky="w", padx=(0, 14), pady=(8, 12))
        self.chips = []
        self.summary.bind("<Configure>", self._wrap, add="+")

        # ---- the culprit hunt
        self.hunt_bar = ctk.CTkFrame(self, fg_color=ACCENT_SOFT, corner_radius=12)
        self.hunt_bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.hunt_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.hunt_bar, text="", image=icon("wand", 22, ACCENT), width=36).grid(
            row=0, column=0, rowspan=2, padx=(14, 6), pady=10)
        self.hunt_title = ctk.CTkLabel(self.hunt_bar, text="", text_color=ACCENT, font=font(13, "bold"), anchor="w",
                                       justify="left")
        self.hunt_title.grid(row=0, column=1, sticky="ew", pady=(10, 0))
        self.hunt_text = ctk.CTkLabel(self.hunt_bar, text="", text_color=TEXT, font=font(12), anchor="w",
                                      justify="left")
        self.hunt_text.grid(row=1, column=1, sticky="ew", pady=(0, 10))
        self.hunt_btns = ctk.CTkFrame(self.hunt_bar, fg_color="transparent")
        self.hunt_btns.grid(row=0, column=2, rowspan=2, padx=12)
        self.hunt_bar.grid_remove()

        # ---- suspects and details
        split = Split(self, app, "crashes")
        split.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        left = page_frame(split)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(left, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.grid_columnconfigure(0, weight=1)
        self.list_title = ctk.CTkLabel(bar, text="Suspects", text_color=TEXT, font=font(14, "bold"), anchor="w")
        self.list_title.grid(row=0, column=0, sticky="w")
        self.show_all = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(bar, text="Every mod", variable=self.show_all, command=self.render_list, text_color=TEXT,
                      font=font(12)).grid(row=0, column=1, sticky="e")
        self.table = Tree(left, [("mod", "Mod", 250, "w", True), ("sure", "How sure", 90, "w", False),
                                 ("why", "Main reason", 330, "w", True), ("errors", "Errors", 64, "e", False)],
                          show_tree=True, selectmode="browse", big=True, image_width=72, main="why",
                          drop=("errors",), min_main=180, key="crashes")
        self.table.grid(row=1, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        for ev in RIGHT_CLICK:
            self.table.tree.bind(ev, self._context, add="+")
        self.dp = DetailPane(split)
        self.dp.on_resize = self.show_detail
        split.add_pane(left, minsize=420, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH + 20, minsize=300, stretch="never", name="detail")
        self.empty = ctk.CTkFrame(self, fg_color="transparent")
        self._build_empty()
        self.after(400, self.refresh)

    # ================================================================ finding crashes
    def data_dir(self):
        md = self.app.mod_dir()
        return LA.data_dir_of(md) if md else ""

    def refresh(self):
        dd = self.data_dir()
        self.crashes = C.find_crashes(dd) if dd else []
        if dd:
            try:
                if self.history.refresh(dd, self.crashes):
                    self.results.clear()             # a new crash or a game that worked changes every reading
            except Exception:
                pass
        sess = C.Session(dd) if dd else None
        self.session = sess if sess and "error.log" in sess.logs else None
        labels = [self._label(c) for c in self.crashes] + ([SESSION] if self.session else [])
        self.pick.configure(values=labels or ["No crashes"])
        keep = self.current.folder if self.current else ""
        cur = next((c for c in self.crashes if c.folder == keep), None)
        if cur is None and self.current is not None and self.current.is_session and self.session:
            cur = self.session
        cur = cur or (self.crashes[0] if self.crashes else self.session)
        self.show(cur)
        self.app.crash_badge()
        self._hunt_render()

    def _label(self, c):
        n = len(c.mod_names)
        return f"Crash {time.strftime('%d %b, %H:%M', time.localtime(c.when))}  ·  {c.game_version or '?'}" + \
            (f"  ·  {n} mods" if n else "")

    def _picked(self, label):
        if label == SESSION:
            self.show(self.session)
            return
        c = next((c for c in self.crashes if self._label(c) == label), None)
        if c:
            self.show(c)

    def unseen(self):
        """Crashes the player hasn't opened in this tab yet."""
        seen = set(self.app.cfg.get("seen_crashes", []))
        return [c for c in self.crashes if c.name not in seen]

    def latest_result(self):
        """The newest crash's analysis, if it's been made (for notes in Conflicts and Library)."""
        if not self.crashes:
            return None
        return self.results.get(self.crashes[0].folder)

    # ================================================================ one crash
    def show(self, crash):
        self.current = crash
        if crash is None:
            self.pick.set("No crashes")
            self._show_empty(True)
            return
        self._show_empty(False)
        self.pick.set(SESSION if crash.is_session else self._label(crash))
        if not crash.is_session and self._really_shown():
            seen = self.app.cfg.setdefault("seen_crashes", [])
            if crash.name not in seen:
                seen.append(crash.name)
                self.app.save()
                self.app.crash_badge()
        for b in (self.folder_btn, self.del_btn):
            b.configure(state="disabled" if crash.is_session else "normal")
        r = self.results.get(crash.folder)
        if r is None:
            self._summary_wait(crash)
            self.analyse(crash)
            return
        self.render(r)

    def analyse(self, crash, force=False):
        an = self.app.analysis
        if an is None or self.app.analyzing:
            self._summary_wait(crash, "Waiting for the mod check to finish...")
            self.after(1500, lambda: self.current is crash and self.analyse(crash, force))
            return
        if crash.folder in self.busy:
            return
        if force:
            self.results.pop(crash.folder, None)
        self.busy.add(crash.folder)
        gi = self.app.game_install()
        keys = [k for k, on in self.app.playsets.entries if on]
        gv = self.app.game_version()
        hidden = self.app.conflicts.is_hidden

        def work():
            try:
                van = A.vanilla_for(gi) if gi else None
                res = C.analyse(crash, an, van, keys, gv, hidden, history=self.history)
            except Exception as e:                                     # never take the tab down
                res = C.Result(crash)
                res.error = f"Couldn't read this crash ({e})."
            self.after(0, lambda: self._done(crash, res))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, crash, res):
        self.busy.discard(crash.folder)
        self.results[crash.folder] = res
        if self.current is crash:
            self.render(res)
        self.app.conflicts.dirty = True
        self.app.crash_badge()

    def reanalyse(self):
        """The mods changed (rescan / new analysis): crash results are worked out again when shown."""
        self.results.clear()
        if self.current is not None and self.app.visible("Crashes"):
            self.show(self.current)
        else:
            self.dirty = True

    def _really_shown(self):
        """The player has this tab open (not the app drawing every tab while it starts)."""
        return self.app.tabs.get() == "Crashes" and not getattr(self.app, "_prerender", False)

    def on_show(self):
        if self.dirty or self.current is None:
            self.dirty = False
            self.refresh()
        elif self.current is not None and not self.current.is_session:
            seen = self.app.cfg.setdefault("seen_crashes", [])
            if self.current.name not in seen:
                seen.append(self.current.name)
                self.app.save()
                self.app.crash_badge()

    # ================================================================ drawing
    def _wrap(self, e=None):
        w = max(300, self.summary.winfo_width() / max(0.5, px(100) / 100.0) - 120)
        self.sum_title.configure(wraplength=w)
        self.sum_text.configure(wraplength=w)
        self.hunt_title.configure(wraplength=w - 280)
        self.hunt_text.configure(wraplength=w - 280)

    def _chips(self, items):
        for i, (text, col, soft) in enumerate(items):
            if i >= len(self.chips):
                self.chips.append(ctk.CTkLabel(self.chip_row, text="", corner_radius=9, height=24,
                                               font=font(11, "bold"), padx=9))
            self.chips[i].configure(text=text, text_color=col, fg_color=soft)
            self.chips[i].grid(row=0, column=i, padx=(0, 6))
        for c in self.chips[len(items):]:
            c.grid_remove()

    def _summary_wait(self, crash, text="Reading the crash and the logs..."):
        self.sum_title.configure(text=("Errors of your last session" if crash.is_session else
                                       f"The game crashed on {_when(crash.when)}"))
        self.sum_text.configure(text=text)
        self._chips([])
        self.table.tree.delete(*self.table.tree.get_children())
        self.by_row = {}
        self.dp.message("Working out what happened...")

    def render(self, r):
        c = r.crash
        if r.error:
            self._summary_wait(c, r.error)
            return
        if c.is_session:
            self.sum_icon.configure(image=icon("log", 28, ACCENT), fg_color=ACCENT_SOFT)
            self.sum_title.configure(text=f"Your last session's errors ({_when(c.when)}): the game didn't crash")
            self.sum_text.configure(text="The same reading as for a crash, for the errors your mods caused in the "
                                         "last game you played. Useful when something misbehaves without crashing.")
        else:
            self.sum_icon.configure(image=icon("crash", 30, CRIT), fg_color=ERR_SOFT)
            what = f"The game crashed {r.phase}" if r.phase else "The game crashed"
            self.sum_title.configure(text=f"{what}, {_when(c.when)}" +
                                     (f", {r.duration} after it started" if r.duration else "") + ".")
            bits = []
            if c.exception:
                bits.append(f"{c.exception_name.capitalize()} in {c.module or 'the game'}: {c.exception_plain}")
            if c.driver:
                bits.append(f"It crashed inside the {c.driver}: update or reinstall it before looking at mods.")
            if r.unknown_mods:
                bits.append(f"{len(r.unknown_mods)} of its mods aren't installed any more: "
                            f"{', '.join(r.unknown_mods[:4])}{'...' if len(r.unknown_mods) > 4 else ''}.")
            self.sum_text.configure(text="  ".join(bits) or "No exception details were saved.")
        likely = sum(1 for s in r.suspects if s.sure == "likely")
        possible = sum(1 for s in r.suspects if s.sure == "possible")
        chips = [(f"{len(c.mod_names) or len(r.keys)} mods", TEXT, MUTED_SOFT),
                 (f"{len(r.entries):,} errors logged", TEXT, MUTED_SOFT)]
        if likely:
            chips.append((f"{likely} likely suspect{'s' if likely != 1 else ''}", CRIT, ERR_SOFT))
        if possible:
            chips.append((f"{possible} possible", WARN, WARN_SOFT))
        if r.outdated:
            chips.append((f"{len(r.outdated)} made for an older version", ACCENT, ACCENT_SOFT))
        if not c.is_session:
            n = len(r.good_sessions)
            chips.append((f"Compared with {n} game{'s' if n != 1 else ''} that worked", OK, OK_SOFT) if n else
                         ("No game that worked to compare with yet", MUTED, MUTED_SOFT))
        if not likely and not possible:
            chips.append(("No mod stands out: try Find the culprit", OK, OK_SOFT))
        self._chips(chips)
        self._wrap()
        self.render_list()

    def render_list(self):
        r = self.results.get(self.current.folder) if self.current else None
        t = self.table.tree
        sel = self.by_row.get(t.selection()[0]) if t.selection() else None
        t.delete(*t.get_children())
        self.by_row = {}
        if r is None:
            return
        have = {m.key: m for m in self.app.mods}
        an = self.app.analysis
        shown = r.suspects if self.show_all.get() else [s for s in r.suspects if s.sure != "unlikely"]
        self.list_title.configure(text=f"Suspects ({len(shown)})" if not self.show_all.get() else
                                  f"Every mod of that game ({len(shown)})")
        for s in shown:
            f = an.facts.get(s.key) if an else None
            role = f.role.role if f and f.role else R.UNKNOWN
            img = row_picture(t, s.key, self.app.thumb(have[s.key]), role) if s.key in have else ""
            why = s.reasons[0][1] if s.reasons else "nothing points at it"
            name = s.name + ("  (not installed now)" if s.gone else "")
            rid = t.insert("", "end", image=img, values=(name, C.SURE[s.sure], why, f"{s.errors:,}"),
                           tags=(SURE_TAG[s.sure],))
            self.by_row[rid] = s
        self.table.stripe() if hasattr(self.table, "stripe") else None
        if sel is not None:
            rid = next((rid for rid, s in self.by_row.items() if s.key == sel.key), None)
            if rid:
                t.selection_set(rid)
                t.see(rid)
                return
        self.show_detail()

    def selected(self):
        t = self.table.tree
        return self.by_row.get(t.selection()[0]) if t.selection() else None

    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        r = self.results.get(self.current.folder) if self.current else None
        s = self.selected()
        an = self.app.analysis
        if r is None or an is None:
            d.message("Working out what happened...")
            return
        if s is None:
            self._overview(r)
            return
        f = an.facts.get(s.key)
        col, soft = SURE_COLOR[s.sure]
        d.begin()
        d.accent(col)
        d.heading(s.name, "Not installed any more: known from that game's list of mods" if s.gone else
                  f"Loaded {s.position} of {len(r.keys)}" + (f"  ·  made for {f.mod.supported}" if f and
                                                             f.mod.supported else ""))
        chips = [(C.SURE[s.sure], col, soft, "crash" if s.sure == "likely" else None, None)]
        if s.errors:
            chips.append((f"{s.errors:,} errors", TEXT, MUTED_SOFT, None, None))
        if s.outdated:
            chips.append((f"For {s.outdated}", ACCENT, ACCENT_SOFT, None, None))
        if s.cleared:
            chips.append((f"Worked {s.cleared}", OK, OK_SOFT, None, None))
        elif r.good_sessions:
            chips.append(("Never in a good game", CRIT, ERR_SOFT, None, None))
        if s.in_crashes and s.in_crashes[1] >= 2:
            chips.append((f"In {s.in_crashes[0]} of {s.in_crashes[1]} crashes", TEXT, MUTED_SOFT, None, None))
        d.chips(chips)
        on_now = dict(self.app.playsets.entries).get(s.key)
        acts = [("Turn it off" if on_now else "Not on in this playset", lambda: self._turn_off([s.key]), "power",
                 "primary" if s.sure == "likely" and on_now else "normal", bool(on_now)),
                ("Show in playset", lambda: self.app.show_in_playset(s.key), "playsets", "normal", s.key in dict(
                    self.app.playsets.entries)),
                ("Its conflicts", lambda: self.app.show_conflicts_for(s.key), "conflicts", "normal", bool(s.issues)),
                ("Copy its errors", lambda: self._copy_errors(s), "copy", "normal", bool(s.errors))]
        if f and f.wid:
            acts.append(("Workshop page", lambda: webbrowser.open(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={f.wid}"), "external", "normal"))
        d.actions(acts)
        t = d.text
        t.h("Why it's a suspect" if s.sure != "unlikely" else "What was found", small=True)
        if not s.reasons:
            t.p("Nothing in the logs points at it.", "muted")
        for w, text in s.reasons[:8]:
            t.bullet(text, "bold" if w >= 8 else ("muted" if w == 0 else ""))
        tips = self._advice(s, f)
        if tips:
            t.h("What to try", small=True)
            for tip in tips:
                t.bullet(tip)
        if s.removes:
            t.h("Game objects its copy of a game file leaves out", small=True)
            t.p("\n".join(f"{name}  ({rel})" for name, rel in s.removes[:40]), "mono")
        if s.objects:
            t.h("Things it uses that don't exist", small=True)
            for name, n in sorted(s.objects.items(), key=lambda x: -x[1])[:12]:
                new = r.renamed.get(name)
                t.bullet(f"{name}  ({n}x)" + (f": renamed to {new} in this game version" if new else ""),
                         "warn" if new else "")
        if s.issues:
            self._issues_text(t, s, an)
        for kind in C.KIND_ORDER:
            ex = s.samples.get(kind)
            if not ex:
                continue
            w, label, plain = C.KINDS[kind]
            t.h(f"{label} ({s.counts.get(kind, 0):,})", small=True)
            t.p(plain, "faint", "small")
            t.p("\n".join(f"[{e.time}] " + e.text.replace("\n", "  ")[:300] for e in ex[:4]), "mono")
        d.end()

    def _advice(self, s, f):
        out = []
        if s.missing_deps:
            out.append("Install or turn on the mod it needs: " + "; ".join(s.missing_deps[:2]) + ".")
        if s.removes:
            out.append("Load it before the mods that use what it leaves out, look for an updated version, or turn it "
                       "off.")
        if s.outdated or s.renamed:
            out.append("Look for an update made for your game version (Library > Check updates), or turn it off "
                       "until there is one.")
        if s.counts.get("syntax") or s.counts.get("event"):
            out.append("Some of its files don't load: re-download it (Catch) in case the copy is damaged; if it "
                       "persists, the mod itself needs fixing.")
        if any(i.remedy == "compatch" for i in s.issues):
            out.append("It clashes with mods it shares things with: a compatch keeps both (see its conflicts below).")
        if s.gone:
            out.append("It isn't installed any more. If you removed it and the game hasn't crashed since, it was "
                       "probably this mod.")
        if s.sure == "likely" and not out:
            out.append("Turn it off and start the game again. If it no longer crashes, it was this mod.")
        return out

    def _issues_text(self, t, s, an):
        t.h(f"Its conflicts in that playset ({len(s.issues)})", small=True)
        cf = self.app.conflicts
        for i in sorted(s.issues, key=lambda i: i.rank)[:8]:
            other = [an.facts[k].name for k in i.mods if k != s.key and k in an.facts]
            t.p(f"{SEV_ICON[i.severity]} ", "sev_" + i.severity)
            t.link(i.title + (f"  (with {', '.join(other[:2])})" if other else ""),
                   lambda i=i: self.app.show_issue(i))
            if len(i.mods) == 2 and i.remedy == "compatch":
                t.p("      ")
                t.link("Look for a compatch", lambda i=i: (self.app.show_issue(i), cf.find_compatch(i)))
                t.add("    ·    ", "faint")
                t.link("Save compatch report", lambda i=i: cf.save_report(i))

    def _overview(self, r):
        d = self.dp
        d.begin()
        t = d.text
        t.p("Select a suspect to see the evidence and what to do.", "muted")
        if r.last:
            t.h("The last errors before the " + ("end" if r.crash.is_session else "crash"), small=True)
            t.p("\n".join(f"[{e.time}] " + e.text.replace("\n", "  ")[:240] for e in r.last[-8:]), "mono")
        if r.missing_objects:
            t.h("Things mods use that this game doesn't have", small=True)
            for name, n in sorted(r.missing_objects.items(), key=lambda x: -x[1])[:14]:
                new = r.renamed.get(name)
                t.bullet(f"{name}  ({n:,}x)" + (f": renamed to {new} in this game version" if new else ""),
                         "warn" if new else "")
        if r.by_kind:
            t.h("Errors by kind", small=True)
            for k in C.KIND_ORDER:
                if r.by_kind.get(k):
                    t.bullet(f"{C.KINDS[k][1]}: {r.by_kind[k]:,}", "bold" if C.KINDS[k][0] >= 3 else "muted")
            if r.vanilla_errors:
                t.p(f"{r.vanilla_errors:,} of them are in the game's own files (often caused by mods that add "
                    "portrait genes or change what those files use).", "faint", "small")
        t.h("How this works", small=True)
        t.p("The game's crash report can't name a mod, so the app reads the session's error log: every error is "
            "traced to the mod whose file it points at (the copy the game really loaded) and weighed by kind (files "
            "that don't load count most, missing pictures and texts hardly at all). Errors in the last moments "
            "before the crash count more, and so do the playset's conflicts, missing required mods and mods made "
            "for an older version. The app also remembers every crash and every game that ended well, with the mods they "
            "had: a mod that was in a game that worked (and hasn't changed since) is cleared, and a mod that's never "
            "been in one, that changed just before, or that was in every crash at the same stage stands out. It's "
            "strong evidence, not proof: Find the culprit settles it.", "muted", "small")
        d.end()

    # ================================================================ actions
    def _turn_off(self, keys):
        self.app.playsets.set_enabled(keys, False)
        self.app.toast(f"Turned off in \"{self.app.playsets.name}\". Start the game again to see if it still "
                       "crashes.")
        self.show_detail()

    def _copy_errors(self, s):
        lines = [f"[{e.time}][{e.src}] " + e.text.replace("\n", " | ") for k in C.KIND_ORDER
                 for e in s.samples.get(k, [])]
        copy_text(self, "\n".join(lines))
        self.app.toast(f"Copied {len(lines)} error(s).")

    def _open_folder(self):
        if self.current is not None:
            open_folder(self.current.folder)

    def delete_crash(self):
        c = self.current
        if c is None or c.is_session:
            return
        if not messagebox.askyesno(APP_NAME, f"Delete this crash's folder ({_mb(c.size)})?\n\n{c.folder}\n\nIt holds "
                                             "the logs, a memory dump and a copy of your last save from that "
                                             "moment. Your real saves aren't touched.", parent=self.app):
            return
        shutil.rmtree(c.folder, ignore_errors=True)
        self.results.pop(c.folder, None)
        self.current = None
        self.refresh()

    def save_report(self):
        r = self.results.get(self.current.folder) if self.current else None
        an = self.app.analysis
        if r is None or an is None:
            return
        try:
            start = installer.documents_dir()
        except Exception:
            start = os.path.expanduser("~")
        path = filedialog.asksaveasfilename(parent=self.app, title="Save the crash report", initialdir=start,
                                            initialfile=C.default_name(r), defaultextension=".md",
                                            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(C.report(r, an, APP_NAME, self.app.game()))
        except OSError as e:
            self.app.toast(f"Couldn't save the report ({e}).", color=SEV_COLOR["high"])
            return
        self.app.banner.show(f"Crash report saved: {os.path.basename(path)}. Paste its last section (the prompt) into "
                             "an AI chat with the report, or share it with the mod authors.",
                             actions=[("Open folder", lambda: open_folder(os.path.dirname(path))),
                                      ("Close", lambda: self.app.banner.hide("report"))], kind="report", tone="ok")

    def _context(self, e):
        t = self.table.tree
        rid = t.identify_row(e.y)
        if rid not in self.by_row:
            return
        t.selection_set(rid)
        s = self.by_row[rid]
        on_now = dict(self.app.playsets.entries).get(s.key)
        r = self.results.get(self.current.folder)
        top = [x.key for x in r.top(5) if dict(self.app.playsets.entries).get(x.key)] if r else []
        popup_menu(t, e, [
            ("Turn it off", "power", lambda: self._turn_off([s.key]), bool(on_now)),
            (f"Turn off the {len(top)} likeliest", "power", lambda: self._turn_off(top), len(top) > 1),
            None,
            ("Show in playset", "playsets", lambda: self.app.show_in_playset(s.key), not s.gone),
            ("Show in Library", "library", lambda: self.app.show_in_library(s.key), not s.gone),
            ("Its conflicts", "conflicts", lambda: self.app.show_conflicts_for(s.key), bool(s.issues)),
            None,
            ("Copy its errors", "copy", lambda: self._copy_errors(s), bool(s.errors))])

    # ================================================================ the culprit hunt
    def hunt(self):
        h = self.app.cfg.get("crash_hunt")
        return h if isinstance(h, dict) and h.get("playset") else None

    def start_hunt(self):
        if self.hunt():
            self.app.toast("A culprit hunt is already going: see the bar above.")
            return
        an = self.app.analysis
        ps = self.app.playsets
        md = self.app.mod_dir()
        if an is None or not ps.name or not md:
            return
        keys = [k for k, on in ps.entries if on and k in an.facts]
        if len(keys) < 2:
            messagebox.showinfo(APP_NAME, "The playset needs at least two mods on for a culprit hunt.",
                                parent=self.app)
            return
        r = self.results.get(self.current.folder) if self.current else None
        hint = [s.key for s in r.suspects] if r else []
        state = C.Hunt.start(an, keys, hint)
        rounds = C.Hunt(state).remaining_rounds(an)
        if not messagebox.askyesno(
                APP_NAME, f"Find the culprit in \"{ps.name}\" ({len(keys)} mods on), about {rounds} round"
                          f"{'s' if rounds != 1 else ''}.\n\nA copy of the playset called \"{HUNT_PLAYSET}\" is made and "
                          "made active; yours isn't changed. Each round turns about half of the remaining suspects "
                          "off there (the likeliest first, with the mods that need them). You start the game with "
                          "Play, see whether it crashes, and answer here.\n\nStart?", parent=self.app):
            return
        name = self.app.profiles.unique_name(md, HUNT_PLAYSET)
        state.update(playset=ps.name, test=name, entries=[list(e) for e in ps.entries], rules=list(ps.rules),
                     started=time.time())
        self.app.cfg["crash_hunt"] = state
        self._hunt_round()

    def _hunt_round(self):
        st = self.hunt()
        an = self.app.analysis
        md = self.app.mod_dir()
        if st is None or an is None or not md:
            return
        H = C.Hunt(st)
        on = [k for k, e in st["entries"] if e and k in an.facts]
        off = set(H.next_round(an, on))
        st["round_started"] = time.time()
        self.app.cfg["crash_hunt"] = st
        self.app.save()
        if st.get("done"):
            self._hunt_render()
            return
        entries = [(k, bool(e) and k not in off) for k, e in st["entries"]]
        self.app.profiles.put(md, st["test"], entries, st.get("rules", []))
        self.app.playsets.load()
        self._hunt_render()

    def hunt_answer(self, crashed):
        st = self.hunt()
        if st is None:
            return
        an = self.app.analysis
        off = set(st.get("off", [])) | set(st.get("also_off", []))
        on = [k for k, e in st.get("entries", []) if e and k not in off]
        if crashed:
            c = self.new_crash_since_round()
            stage = C.crash_stage(c)[0] if c is not None else ""
        else:
            stage = "play"
        try:
            self.history.add("crash" if crashed else "ok", on, stage,
                             names=[an.facts[k].name for k in on if an and k in an.facts])
            self.results.clear()
        except Exception:
            pass
        C.Hunt(st).answer(crashed)
        self._hunt_round()

    def hunt_stop(self, apply_off=None):
        st = self.hunt()
        md = self.app.mod_dir()
        if st is None:
            return
        if md:
            self.app.profiles.delete(md, st.get("test", HUNT_PLAYSET))
            if st.get("playset") in self.app.profiles.names(md):
                self.app.profiles.set_active(md, st["playset"])
        self.app.cfg.pop("crash_hunt", None)
        self.app.save()
        self.app.playsets.load()
        if apply_off:
            self.app.playsets.set_enabled(apply_off, False)
            self.app.toast(f"Turned off in \"{st['playset']}\": " + ", ".join(
                self.app.analysis.facts[k].name for k in apply_off if k in self.app.analysis.facts))
        self._hunt_render()

    def new_crash_since_round(self):
        st = self.hunt()
        if st is None:
            return None
        t0 = st.get("round_started", 0)
        return next((c for c in self.crashes if c.when >= t0 - 5), None)

    def _hunt_render(self):
        st = self.hunt()
        for w in self.hunt_btns.winfo_children():
            w.destroy()
        if st is None:
            self.hunt_bar.grid_remove()
            self.hunt_btn.configure(state="normal")
            return
        self.hunt_btn.configure(state="disabled")
        self.hunt_bar.grid()
        an = self.app.analysis
        name = (lambda k: an.facts[k].name if an and k in an.facts else k)
        if st.get("done") == "found":
            res = st.get("result", [])
            self.hunt_title.configure(text="Culprit found: " + ", ".join(name(k) for k in res[:3]) +
                                           (" (and the mods that need it)" if len(res) > 1 else ""))
            self.hunt_text.configure(text=f"After {st['round']} round{'s' if st['round'] != 1 else ''}, "
                                          "only this is left. Turn it off in your playset, look for an update, or "
                                          "check its conflicts.")
            button(self.hunt_btns, f"Turn it off in \"{st['playset']}\"", lambda: self.hunt_stop(res), primary=True,
                   height=32).pack(side="left", padx=(0, 6))
            button(self.hunt_btns, "Back to my playset", lambda: self.hunt_stop(), height=32).pack(side="left")
            return
        if st.get("done") == "unclear":
            self.hunt_title.configure(text="No single culprit")
            self.hunt_text.configure(text="The answers don't point at one mod: it may take two mods together, or the "
                                          "crash doesn't happen every time. Your playset is back as it was.")
            button(self.hunt_btns, "Back to my playset", lambda: self.hunt_stop(), primary=True,
                   height=32).pack(side="left")
            return
        H = C.Hunt(st)
        left = max(0, H.remaining_rounds(an) - 1) if an else 0
        n_off = len(st.get("off", [])) + len(st.get("also_off", []))
        self.hunt_title.configure(text=f"Finding the culprit: round {st['round']}" +
                                       (f", about {left} more after this" if left else ", probably the last") +
                                       f"  ·  {len(st['pool'])} suspects left")
        new = self.new_crash_since_round()
        note = (f"  The game crashed again at {time.strftime('%H:%M', time.localtime(new.when))}: that's a "
                "\"Crashed\".") if new else ""
        self.hunt_text.configure(text=f"{n_off} mods are off in \"{st['test']}\" (the active playset). Press Play, "
                                      "play to where it crashed before, then answer." + note)
        button(self.hunt_btns, "It crashed", lambda: self.hunt_answer(True), danger=True, height=32,
               icon_name="crash").pack(side="left", padx=(0, 6))
        button(self.hunt_btns, "It didn't crash", lambda: self.hunt_answer(False), primary=True, height=32,
               icon_name="check").pack(side="left", padx=(0, 6))
        button(self.hunt_btns, "Stop", lambda: self.hunt_stop(), height=32).pack(side="left")

    # ================================================================ empty
    def _build_empty(self):
        e = self.empty
        e.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(e, fg_color="transparent")
        inner.grid(row=0, column=0, pady=60)
        ctk.CTkLabel(inner, text="", image=icon("crash", 44, OK), width=70, height=70, corner_radius=35,
                     fg_color=OK_SOFT).pack()
        ctk.CTkLabel(inner, text="No crashes", text_color=TEXT, font=font(20, "bold")).pack(pady=(12, 2))
        ctk.CTkLabel(inner, text="When the game crashes it leaves a report; it shows up here with the mods most "
                                 "likely to blame, the evidence, and a step-by-step culprit hunt.", text_color=MUTED,
                     font=font(12), wraplength=520, justify="center").pack()

    def _show_empty(self, on):
        if on:
            self.empty.grid(row=1, column=0, rowspan=3, sticky="nsew")
            self.empty.tkraise()
            for b in (self.report_btn, self.folder_btn, self.del_btn, self.hunt_btn):
                b.configure(state="disabled")
        else:
            self.empty.grid_remove()
            self.report_btn.configure(state="normal")
            if not self.hunt():
                self.hunt_btn.configure(state="normal")

    def restyle(self):
        self.table.restyle()
        self.dp.restyle()
        if self.current is not None and self.current.folder in self.results:
            self.render_list()
