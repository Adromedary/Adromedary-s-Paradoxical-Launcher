"""The Conflicts tab: everything that can go wrong in the active playset, grouped and explained, with what
you'll notice in game, how sure the app is and what solves it, plus compatches (installed or on the
Workshop) and a compatch report to hand to a modder or an AI."""
import os
import threading
import webbrowser
from tkinter import filedialog

import customtkinter as ctk

import analysis as A
import compat as CP
import icons
import installer
import report as RP
import roles as R
import workshop as W
from gui_common import (ACCENT, ACCENT_SOFT, APP_NAME, BORDER, CARD, DETAIL_WIDTH, INFO, INFO_SOFT, MUTED, MUTED_SOFT,
                        OK, OK_SOFT, RIGHT_CLICK, SEV_COLOR, SEV_ICON, SEV_LABEL, SEV_SOFT, TEXT, WARN, WARN_SOFT,
                        copy_text, DetailPane, font, icon, open_folder, page_frame, popup_menu, px, Split, Tree,
                        units)

GROUP_ORDER = ["critical", "high", "medium", "low", "info"]
GROUP_TITLE = {"critical": "Don't work together / will break", "high": "Something of one mod is lost",
               "medium": "Probably needs a compatch", "low": "Cosmetic or minor", "info": "Fine (for your information)"}
REMEDY_COLOR = {"order": (OK, OK_SOFT), "compatch": (WARN, WARN_SOFT), "choose": (SEV_COLOR["critical"],
                SEV_SOFT["critical"]), "enable": (ACCENT, ACCENT_SOFT), "none": (MUTED, MUTED_SOFT),
                "patched": (OK, OK_SOFT)}
CONF_COLOR = {"certain": (TEXT, MUTED_SOFT), "likely": (INFO, INFO_SOFT), "possible": (MUTED, MUTED_SOFT)}
COMPATCH_KINDS = A.PATCHABLE


class ConflictsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.by_row = {}
        self.focus_key = None
        self.focus_sig = None
        self.dirty = False
        self.compat = {}                 # (a, b) -> "searching" | compat.Result
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        head.grid_columnconfigure(5, weight=1)
        self.cards = {}
        for i, sev in enumerate(("critical", "high", "medium", "low", "info")):
            c = ctk.CTkFrame(head, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER, width=1,
                             height=1)
            c.grid(row=0, column=i, padx=(0, 8), sticky="ns")
            strip = ctk.CTkFrame(c, width=4, height=1, corner_radius=2, fg_color=SEV_COLOR[sev])
            strip.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(8, 0), pady=10)
            n = ctk.CTkLabel(c, text="0", text_color=SEV_COLOR[sev], font=font(22, "bold"), anchor="w", width=92)
            n.grid(row=0, column=1, sticky="w", padx=(10, 14), pady=(6, 0))
            sub = ctk.CTkLabel(c, text=f"{SEV_ICON[sev]} {SEV_LABEL[sev]}", text_color=MUTED, font=font(11), anchor="w")
            sub.grid(row=1, column=1, sticky="w", padx=(10, 14), pady=(0, 8))
            self.cards[sev] = (c, n, strip)
        right = ctk.CTkFrame(head, fg_color="transparent")
        right.grid(row=0, column=5, sticky="e")
        self.scope = ctk.CTkLabel(right, text="", text_color=MUTED, font=font(11), anchor="e", justify="right")
        self.scope.pack(anchor="e")
        sw = ctk.CTkFrame(right, fg_color="transparent")
        sw.pack(anchor="e", pady=(6, 0))
        self.show_info = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(sw, text="Harmless ones", variable=self.show_info, command=self.render,
                      text_color=TEXT, font=font(12)).pack(side="left", padx=(0, 12))
        self.show_hidden = ctk.BooleanVar(value=False)
        self.hidden_sw = ctk.CTkSwitch(sw, text="Hidden (0)", variable=self.show_hidden, command=self.render,
                                       text_color=TEXT, font=font(12))
        self.hidden_sw.pack(side="left")
        self.verdict = ctk.CTkLabel(self, text="", text_color=MUTED, font=font(13, "bold"), anchor="w", justify="left",
                                    wraplength=900, fg_color=MUTED_SOFT, corner_radius=10, padx=14, height=38,
                                    compound="left")
        self.verdict.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        self._vw = 0
        self.bind("<Configure>", self._wrap_verdict, add="+")    # by the page's width: the text can't change it
        split = Split(self, app, "conflicts")
        split.grid(row=2, column=0, sticky="nsew")
        left = page_frame(split)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        self.table = Tree(left, [("mods", "Mods", 260, "w", True), ("what", "What", 260, "w", True),
                                 ("fix", "What solves it", 150, "w", False)], show_tree=True, selectmode="browse",
                          main="mods", drop=("fix",), min_main=400, key="conflicts")
        self.table.tree.column("#0", width=px(150), minwidth=px(110), stretch=False)
        self.table.tree.heading("#0", text="Severity", anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        for ev in RIGHT_CLICK:
            self.table.tree.bind(ev, self._context, add="+")
        self.dp = DetailPane(split)
        self.dp.on_resize = self.show_detail
        split.add_pane(left, minsize=420, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH + 20, minsize=300, stretch="never", name="detail")
        self.render()

    def on_show(self):
        if self.dirty:
            self.render()

    # ---------------------------------------------------------------- hidden conflicts
    def _hidden_store(self):
        return self.app.cfg.setdefault("hidden_issues", {}).setdefault(os.path.normcase(self.app.mod_dir()), [])

    def is_hidden(self, i):
        return i.signature() in self._hidden_store()

    def set_hidden(self, i, hide):
        store = self._hidden_store()
        sig = i.signature()
        if hide and sig not in store:
            store.append(sig)
        elif not hide and sig in store:
            store.remove(sig)
        self.app.save()
        self.render()
        self.app._tab_info()

    # ---------------------------------------------------------------- the list
    def issues(self):
        """This playset's conflicts, without the ones you've hidden (unless 'Hidden' is on)."""
        if self.app.analysis is None:
            return []
        return [i for i in self.app.playsets.issues if self.show_hidden.get() or not self.is_hidden(i)]

    def counted_issues(self):
        if self.app.analysis is None:
            return []
        return [i for i in self.app.playsets.issues if not self.is_hidden(i)]

    def render(self):
        if self.app.tabs.get() is not None and not self.app.visible("Conflicts"):
            self.dirty = True
            return
        self.dirty = False
        t = self.table.tree
        sel = [self.by_row[r].signature() for r in t.selection() if r in self.by_row]
        if self.focus_sig:
            sel = [self.focus_sig]
        t.delete(*t.get_children())
        self.by_row.clear()
        ps = self.app.playsets
        an = self.app.analysis
        issues = self.issues()
        n_hidden = sum(1 for i in ps.issues if self.is_hidden(i)) if an is not None else 0
        self.hidden_sw.configure(text=f"Hidden ({n_hidden})")
        counts = A.summary(self.counted_issues())
        for sev, (c, lbl, strip) in self.cards.items():
            on = counts[sev] > 0 and (sev != "info" or self.show_info.get())
            lbl.configure(text=str(counts[sev]), text_color=SEV_COLOR[sev] if on else MUTED)
            c.configure(fg_color=SEV_SOFT[sev] if on else CARD, border_color=SEV_SOFT[sev] if on else BORDER)
            strip.configure(fg_color=SEV_COLOR[sev] if on else BORDER)
        n_on = len(ps.enabled_keys())
        self.scope.configure(text=(f"Playset \"{ps.name}\"  ·  {n_on} mods on" if ps.name else "No playset") +
                             ("\nAnalysing..." if self.app.analyzing else ""))
        if an is None:
            self.verdict.configure(text="  Analysing your mods..." if self.app.analyzing else "  Pick your game at the top.",
                                   text_color=MUTED, fg_color=MUTED_SOFT, image=icon("info", 18, MUTED))
            self.show_detail()
            return
        patched = sum(1 for i in self.counted_issues() if i.patched_by)
        tail = f" {patched} conflict(s) are solved by compatches you have." if patched else ""
        if counts["critical"]:
            self._verdict(f"{counts['critical']} serious problem(s): some of these mods can't be used together, or "
                          "something they need is missing." + tail, "critical", "alert")
        elif counts["high"]:
            n_order = sum(1 for i in self.counted_issues() if i.severity == "high" and i.remedy == "order")
            self._verdict(f"The playset works, but {counts['high']} conflict(s) mean part of a mod is lost"
                          + (f" ({n_order} decided by load order, which Auto-sort handles)" if n_order else "")
                          + "." + tail, "high", "alert")
        elif counts["medium"] or counts["low"]:
            self._verdict("No serious conflicts. A few overlaps that mostly matter to the details." + tail, "ok", "check")
        else:
            self._verdict("No conflicts found between the mods of this playset." + tail, "ok", "check")
        show_info = self.show_info.get()
        first = None
        for sev in GROUP_ORDER:
            group = [i for i in issues if i.severity == sev]
            if not group or (sev == "info" and not show_info):
                continue
            gid = t.insert("", "end", text=f"{SEV_ICON[sev]}  {SEV_LABEL[sev]} ({len(group)})",
                           values=(GROUP_TITLE[sev], "", ""), tags=(sev, "bold"), open=sev != "info")
            for n_i, i in enumerate(group):
                mods = " + ".join(an.facts[k].name if k in an.facts else k for k in i.mods)
                fix = A.REMEDY_LABEL.get(i.remedy, "")
                if i.patch_off:
                    fix = "Turn on a compatch you have"
                tags = ["muted"] if self.is_hidden(i) else (["ok"] if i.patched_by else [sev])
                if n_i % 2:
                    tags.append("odd")
                rid = t.insert(gid, "end", text=f"   {SEV_ICON[sev]}", values=(mods, i.title, fix), tags=tags)
                self.by_row[rid] = i
                if i.signature() in sel:
                    first = rid
                elif first is None and (self.focus_key is None or self.focus_key in i.mods):
                    first = rid
        if first:
            t.selection_set(first)
            t.see(first)
        self.focus_key = None
        self.focus_sig = None
        self.show_detail()

    def focus_issue(self, issue):
        """Select this conflict (shown even when it's harmless or hidden)."""
        self.focus_sig = issue.signature()
        if issue.severity == "info":
            self.show_info.set(True)
        if self.is_hidden(issue):
            self.show_hidden.set(True)
        self.dirty = False
        self.render()

    def focus_on(self, key):
        """Show the first conflict involving this mod."""
        self.focus_key = key
        self.table.tree.selection_remove(*self.table.tree.selection())
        self.dirty = False
        self.render()

    def _wrap_verdict(self, e):
        if e.widget is not self:
            return
        w = int(max(300, units(e.width) - 70))
        if abs(w - self._vw) > 8:
            self._vw = w
            self.verdict.configure(wraplength=w)

    def _verdict(self, text, sev, ic):
        col, soft = (OK, OK_SOFT) if sev == "ok" else (SEV_COLOR[sev], SEV_SOFT[sev])
        self.verdict.configure(text="  " + text, text_color=col, fg_color=soft, image=icon(ic, 18, col))

    def selected(self):
        sel = [self.by_row[r] for r in self.table.tree.selection() if r in self.by_row]
        return sel[0] if sel else None

    # ---------------------------------------------------------------- the details
    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        i = self.selected()
        an = self.app.analysis
        if i is None or an is None:
            d.begin()
            t = d.text
            t.p("Select a conflict to see what you'll notice in game, how sure the app is and what to do about it.",
                "muted")
            t.h("How mods collide in Paradox games", small=True)
            t.bullet("Same file in two mods: the one loaded last replaces it whole (load order decides).", "muted")
            t.bullet("Same object in files with different names: the file name decides, so only a compatch helps. "
                     "Interface templates and types: the first file wins.", "muted")
            t.bullet("Events and on-action effects can't merge: one is lost.", "muted")
            t.bullet("Game settings (defines) are taken one by one: each value from one file.", "muted")
            t.bullet("A mod that replaces a game file without some of its objects breaks other mods that use them.",
                     "muted")
            d.end()
            return
        pair = tuple(sorted(i.mods)) if len(i.mods) == 2 else None
        d.begin()
        d.accent(OK if i.patched_by else SEV_COLOR[i.severity])
        d.heading(i.title, A.ISSUE_KINDS.get(i.kind, i.kind))
        rc, rs = REMEDY_COLOR.get(i.remedy, (MUTED, MUTED_SOFT))
        cc, cs = CONF_COLOR.get(i.confidence, (MUTED, MUTED_SOFT))
        d.chips([(f"{SEV_ICON[i.severity]} {SEV_LABEL[i.severity]}", SEV_COLOR[i.severity], SEV_SOFT[i.severity],
                  None, None),
                 (A.REMEDY_LABEL.get(i.remedy, i.remedy), rc, rs, "check" if i.remedy in ("order", "patched") else None,
                  None),
                 (A.CONFIDENCE_LABEL.get(i.confidence, ""), cc, cs, None, None)])
        acts = []
        if pair and i.kind in COMPATCH_KINDS and not i.patched_by:
            acts.append(("Look for a compatch", lambda: self.find_compatch(i), "search",
                         "primary" if i.remedy == "compatch" else "normal"))
        if pair and i.kind in COMPATCH_KINDS:
            acts.append(("Save compatch report", lambda: self.save_report(i), "log", "normal"))
        if i.items:
            acts.append(("Copy the details", lambda: self._copy(i.items), "copy", "normal"))
        hidden = self.is_hidden(i)
        acts.append(("Show it again" if hidden else "Hide this conflict", lambda: self.set_hidden(i, not hidden),
                     "filter_off", "normal"))
        d.actions(acts)
        t = d.text
        for k in i.mods:
            note = self.app.crash_note(k)
            if note:
                t.p("")
                t.add(f"{(an.facts[k].name if k in an.facts else k)}: {note[0]}  ", "crit", "bold")
                t.link("See the crash", lambda k=k: self.app.show_crash_suspect(k))
        t.h("What you'll notice in game", small=True)
        t.p(i.effect, "bold" if i.severity in ("critical", "high") else "")
        t.h("What to do", small=True)
        t.p(i.fix or A.REMEDY_LABEL.get(i.remedy, ""), "ok" if i.remedy in ("order", "patched") else "")
        if i.patched_by:
            c = an.facts.get(i.patched_by[0])
            t.p("")
            t.link(f"Show \"{c.name}\" in the playset", lambda k=i.patched_by[0]: self.app.show_in_playset(k))
        if i.patch_off:
            k = i.patch_off[0]
            t.p("")
            t.link(f"Turn on \"{an.facts[k].name}\"", lambda k=k: self._turn_on_patch(k))
        if pair and i.kind in COMPATCH_KINDS and not i.patched_by:
            self._compat_text(t, i, pair)
        self._mods_text(t, i, an)
        t.h("Why")
        t.p(i.detail, "muted")
        if i.items:
            t.h(f"Details ({len(i.items)})")
            t.p("\n".join(str(x) for x in i.items[:400]), "mono")
        d.end()

    def _mods_text(self, t, i, an):
        have = {m.key: m for m in self.app.mods}
        t.h("Mods involved")
        turn_off = i.kind not in ("identical", "hook", "integration", "merged", "version")
        for k in i.mods:
            f = an.facts.get(k)
            m = have.get(k)
            role = f.role.role if f and f.role else R.UNKNOWN
            t.p("")
            if icons.available() and m is not None:
                t.picture(icons.row_image(self.app.thumb(m), role, px(30), px(15), px(3)), pad=2)
            t.add("  " + (f.name if f else k), "bold")
            t.add(f"   {role.name}", "faint", "small")
            t.p("      ")
            t.link("Show in playset", lambda k=k: self.app.show_in_playset(k))
            if turn_off:
                t.add("    ·    ", "faint")
                t.link("Turn off", lambda k=k: self.app.playsets.set_enabled([k], False))

    def _compat_text(self, t, i, pair):
        t.h("Compatch on the Workshop", small=True)
        r = self.compat.get(pair)
        if r is None:
            t.p("Not looked for yet. \"Look for a compatch\" searches the Workshop for a mod that patches these two "
                "together.", "faint", "small")
            return
        if r == "searching":
            t.p("Searching the Workshop...", "faint")
            return
        if not r.candidates:
            t.p("None found" + (f" ({r.error})" if r.error else "") + ". \"Save compatch report\" writes everything a "
                "modder (or an AI) needs to make one.", "muted", "small")
            return
        have = self.app.installed_wids()
        for c in r.candidates[:6]:
            sure = {"certain": "ok", "likely": "accent", "possible": "faint"}[c.sure]
            t.p(f"{c.sure.capitalize()}: ", sure, "bold")
            t.link(c.item.title, lambda c=c: webbrowser.open(c.item.url))
            t.p(f"{c.why}  ·  updated {W.ago(c.item.updated)}" + (f"  ·  {c.item.subs:,} subscribers"
                                                                     if c.item.subs else ""), "faint", "small")
            if c.notes:
                t.p("May be outdated: " + "; ".join(c.notes) + ".", "warn", "small")
            t.p("   ")
            if c.item.id in have:
                t.add("installed", "ok", "small")
            else:
                t.link("Catch it", lambda c=c: self.app.catch_ids([c.item.id]), "small")

    def _turn_on_patch(self, k):
        ps = self.app.playsets
        if k in dict(ps.entries):
            ps.set_enabled([k], True)
        else:
            ps.add_keys([k])
        self.app.toast("Compatch turned on. Auto-sort places it after both mods.")

    # ---------------------------------------------------------------- compatch search and report
    def find_compatch(self, i):
        pair = tuple(sorted(i.mods))
        an = self.app.analysis
        if an is None or self.compat.get(pair) == "searching":
            return
        appid = self.app.browse.appid()
        if not appid:
            self.app.toast("Pick a Steam Workshop game at the top first.", color=MUTED)
            return
        reg = self.app.registry()
        info = []
        for k in pair:
            f = an.facts[k]
            upd = (self.app.updates.get(k) or {}).get("steam_updated") or (reg.get(f.wid, {}) or {}).get(
                "steam_updated") or 0
            info.append({"name": f.name, "wid": f.wid, "updated": int(upd or 0)})
        self.compat[pair] = "searching"
        self.show_detail()
        gv = self.app.game_version()

        def work():
            import net as N
            try:
                res = CP.search(N.Net(), appid, info[0], info[1], gv)
            except Exception as e:
                res = CP.Result()
                res.error = str(e)
            self.app.q.put(("compat", pair, res))
        threading.Thread(target=work, daemon=True).start()

    def compat_found(self, pair, res):
        self.compat[pair] = res
        i = self.selected()
        if i is not None and tuple(sorted(i.mods)) == pair:
            self.show_detail()
        n = len(res.candidates)
        self.app.toast(f"Compatch search: {n} candidate{'s' if n != 1 else ''} found." if n else
                       "No compatch found on the Workshop for these two.", color=OK if n else MUTED)

    def save_report(self, i):
        an = self.app.analysis
        if an is None or len(i.mods) != 2:
            return
        ka, kb = sorted(i.mods)
        pair_issues = [x for x in self.app.playsets.issues if set(x.mods) == {ka, kb} and x.severity != "info"] or [i]
        try:
            start = installer.documents_dir()
        except Exception:
            start = os.path.expanduser("~")
        path = filedialog.asksaveasfilename(parent=self.app, title="Save the compatch report",
                                            initialdir=start, initialfile=RP.default_name(an, ka, kb),
                                            defaultextension=".md",
                                            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")])
        if not path:
            return
        van = A.vanilla_for(self.app.game_install()) if self.app.game_install() else None
        text = RP.build(an, pair_issues, ka, kb, [k for k, on in self.app.playsets.entries if on],
                        self.app.game(), self.app.game_version(), van, APP_NAME)
        try:
            RP.save(path, text)
        except OSError as e:
            self.app.toast(f"Couldn't save the report ({e}).", color=SEV_COLOR["high"])
            return
        self.last_report = path
        self.app.banner.show(f"Compatch report saved: {os.path.basename(path)}. Paste its last section (the prompt) "
                             "into an AI chat with the report, or send it to a modder.",
                             actions=[("Open folder", lambda: open_folder(os.path.dirname(path))),
                                      ("Close", lambda: self.app.banner.hide("report"))], kind="report", tone="ok")

    # ---------------------------------------------------------------- right-click
    def _context(self, e):
        t = self.table.tree
        rid = t.identify_row(e.y)
        if rid not in self.by_row:
            return
        t.selection_set(rid)
        i = self.by_row[rid]
        an = self.app.analysis
        pair = len(i.mods) == 2 and i.kind in COMPATCH_KINDS
        names = [(k, an.facts[k].name) for k in i.mods if an and k in an.facts]
        hidden = self.is_hidden(i)
        popup_menu(t, e, [
            ("Look for a compatch", "search", lambda: self.find_compatch(i), pair and not i.patched_by),
            ("Save compatch report...", "log", lambda: self.save_report(i), pair),
            ("Copy the details", "copy", lambda: self._copy(i.items), bool(i.items)),
            None,
            ("Show in playset", "playsets", [(n, None, lambda k=k: self.app.show_in_playset(k)) for k, n in names]),
            ("Turn off", "power", [(n, None, lambda k=k: self.app.playsets.set_enabled([k], False))
                                   for k, n in names]),
            None,
            ("Show it again" if hidden else "Hide this conflict", "filter_off", lambda: self.set_hidden(i, not hidden))])

    def _copy(self, items):
        copy_text(self, "\n".join(str(x) for x in items))
        self.app.toast(f"Copied {len(items)} line(s).")

    def restyle(self):
        self.table.restyle()
        self.dp.restyle()
