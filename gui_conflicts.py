"""The Conflicts tab: everything that can go wrong in the active playset, grouped and explained."""
import customtkinter as ctk

import analysis as A
import icons
import roles as R
from gui_common import (BORDER, CARD, MUTED, MUTED_SOFT, OK, OK_SOFT, SEV_COLOR, SEV_ICON, SEV_LABEL, SEV_SOFT, TEXT,
                        DetailPane, Split, Tree, font, icon, page_frame, px, units, DETAIL_WIDTH)

GROUP_ORDER = ["critical", "high", "medium", "low", "info"]
GROUP_TITLE = {"critical": "Don't work together / will break", "high": "Something of one mod is lost",
               "medium": "Probably needs a compatch", "low": "Cosmetic or minor", "info": "Fine (for your information)"}


class ConflictsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.by_row = {}
        self.focus_key = None
        self.dirty = False
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
        self.show_info = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(right, text="Show harmless ones too", variable=self.show_info, command=self.render,
                      text_color=TEXT, font=font(12)).pack(anchor="e", pady=(6, 0))
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
        self.table = Tree(left, [("mods", "Mods", 270, "w", True), ("what", "What", 280, "w", True),
                                 ("kind", "Kind", 170, "w", False)], show_tree=True, selectmode="browse",
                          main="mods", drop=("kind",), min_main=400)
        self.table.tree.column("#0", width=160, minwidth=120, stretch=False)
        self.table.tree.heading("#0", text="Severity", anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.dp = DetailPane(split)
        self.dp.on_resize = self.show_detail
        split.add_pane(left, minsize=420, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH + 20, minsize=300, stretch="never", name="detail")
        self.render()

    def on_show(self):
        if self.dirty:
            self.render()

    # ----------------------------------------------------------------
    def issues(self):
        return self.app.playsets.issues if self.app.analysis is not None else []

    def render(self):
        if self.app.tabs.get() is not None and not self.app.visible("Conflicts"):
            self.dirty = True
            return
        self.dirty = False
        t = self.table.tree
        t.delete(*t.get_children())
        self.by_row.clear()
        ps = self.app.playsets
        an = self.app.analysis
        issues = self.issues()
        counts = A.summary(issues)
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
        if counts["critical"]:
            self._verdict(f"{counts['critical']} serious problem(s): some of these mods can't be used together, or "
                          "something they need is missing.", "critical", "alert")
        elif counts["high"]:
            self._verdict(f"The playset works, but {counts['high']} conflict(s) mean part of a mod is lost. Load order "
                          "fixes some (Auto-sort); others need a compatch.", "high", "alert")
        elif counts["medium"] or counts["low"]:
            self._verdict("No serious conflicts. A few overlaps that mostly matter to the details.", "ok", "check")
        else:
            self._verdict("No conflicts found between the mods of this playset.", "ok", "check")
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
                rid = t.insert(gid, "end", text=f"   {SEV_ICON[sev]}", values=(mods, i.title, A.ISSUE_KINDS.get(i.kind, i.kind)),
                               tags=(sev, "odd") if n_i % 2 else (sev,))
                self.by_row[rid] = i
                if first is None and (self.focus_key is None or self.focus_key in i.mods):
                    first = rid
        if first and not t.selection():
            t.selection_set(first)
            t.see(first)
        self.focus_key = None
        self.show_detail()

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

    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        sel = [self.by_row[r] for r in self.table.tree.selection() if r in self.by_row]
        an = self.app.analysis
        if not sel or an is None:
            d.begin()
            t = d.text
            t.p("Select a conflict to see what happens in game and what to do about it.", "muted")
            t.h("How mods collide in Paradox games", small=True)
            t.bullet("Same file in two mods: the one loaded last replaces it whole (load order decides).", "muted")
            t.bullet("Same object in files with different names: the file name decides, so only a compatch helps.",
                     "muted")
            t.bullet("Events and on-action effects can't merge: one is lost.", "muted")
            t.bullet("Some mods need others, or say they don't work with them.", "muted")
            d.end()
            return
        i = sel[0]
        d.begin()
        d.accent(SEV_COLOR[i.severity])
        d.heading(i.title, A.ISSUE_KINDS.get(i.kind, i.kind))
        d.chips([(f"{SEV_ICON[i.severity]} {SEV_LABEL[i.severity]}", SEV_COLOR[i.severity], SEV_SOFT[i.severity],
                  None, None)] + ([("Auto-sort handles it", OK, OK_SOFT, "check", None)] if i.order else []))
        acts = []
        if i.kind in ("object_override", "file_clash", "gui_window", "on_action", "event_collision", "name_collision"):
            names = [an.facts[k].name for k in i.mods if k in an.facts][:2]
            if len(names) == 2:
                q = " ".join(" ".join(n.replace("-", " ").split()[:3]) for n in names)
                acts.append(("Look for a compatch", lambda q=q: self.app.show_in_browse_search(q), "search", "primary"))
        if i.items:
            acts.append(("Copy the details", lambda: self._copy(i.items), "copy", "normal"))
        d.actions(acts)
        t = d.text
        have = {m.key: m for m in self.app.mods}
        t.h("Mods involved")
        turn_off = i.kind in ("incompatible", "duplicate_mod", "two_conversions", "replace_path", "name_collision",
                              "event_collision", "on_action", "gui_window", "file_clash", "object_override")
        for k in i.mods:
            f = an.facts.get(k)
            m = have.get(k)
            role = f.role.role if f and f.role else R.UNKNOWN
            t.p("")
            if icons.available() and m is not None:
                h = px(30)
                t.picture(icons.row_image(self.app.thumb(m), role, h, px(15), px(3)), pad=2)
            t.add("  " + (f.name if f else k), "bold")
            t.add(f"   {role.name}", "faint", "small")
            t.p("      ")
            t.link("Show in playset", lambda k=k: self.app.show_in_playset(k))
            if turn_off:
                t.add("    \u00B7    ", "faint")
                t.link("Turn off", lambda k=k: self.app.playsets.set_enabled([k], False))
        t.h("What happens")
        t.p(i.detail, "muted")
        if i.fix:
            t.h("What to do")
            t.p(i.fix + (". Auto-sort already accounts for it." if i.order else ""), "ok" if i.order else "")
        if i.items:
            t.h(f"Details ({len(i.items)})")
            t.p("\n".join(str(x) for x in i.items[:400]), "mono")
        d.end()

    def _copy(self, items):
        self.clipboard_clear()
        self.clipboard_append("\n".join(str(x) for x in items))
        self.app.toast(f"Copied {len(items)} line(s).")
