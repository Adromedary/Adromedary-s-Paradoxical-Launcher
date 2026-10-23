"""The Playsets tab: named mod lists in load order, Auto-sort, and who wins each shared file."""
import os
import tkinter as tk
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

import analysis as A
import icons
import launcher as LA
import loadorder as L
import modscan
import roles as R
import updates as U
import versions as V
from gui_common import badge_image
from gui_common import (ACCENT, APP_NAME, APP_SHORT, BORDER, CARD, CARD_HI, DETAIL_WIDTH, ERR, INFO, INFO_SOFT,
                        MISS_ICON, MUTED, OK, OK_SOFT, RIGHT_CLICK, SEV_COLOR, SEV_ICON, SEV_SOFT, TEXT, VER_ICON,
                        WARN, DetailPane, Split, Tree, button, card, clearable, fit_geometry, font,
                        page_frame, pick, popup_menu, row_picture, units)

ISSUE_COUNT_SEVS = ("critical", "high", "medium")


class PlaysetsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.name = ""
        self.entries = []              # [(key, enabled)] in load order (top loads first)
        self.rules = []                # [(before, after)]
        self.undo, self.redo = [], []
        self.win, self.reasons, self.issues, self.mod_issues = {}, {}, [], {}
        self.pending_sort = False
        self.by_row, self.extra_rows = {}, {}
        self._drag = None
        self.loaded_for = None
        self.dirty = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        split = Split(self, app, "playsets")
        split.grid(row=0, column=0, sticky="nsew")

        # ---- left: the list of playsets + its health
        lpane = page_frame(split)
        lpane.grid_columnconfigure(0, weight=1)
        lpane.grid_rowconfigure(0, weight=1)
        left = card(lpane)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="Playsets", text_color=TEXT, font=font(14, "bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.plist = Tree(left, [("name", "Name", 200, "w", True)], selectmode="browse", height=6)
        self.plist.tree.configure(show="tree", displaycolumns=())
        self.plist.tree.column("#0", width=200, stretch=True)
        self.plist.grid(row=1, column=0, sticky="nsew", padx=8)
        self.plist.tree.bind("<<TreeviewSelect>>", self._picked_profile)
        pb = ctk.CTkFrame(left, fg_color="transparent")
        pb.grid(row=2, column=0, sticky="ew", padx=8, pady=8)
        pb.grid_columnconfigure((0, 1), weight=1)
        button(pb, "New", self.new_profile, height=28, width=10, icon_name="plus", icon_size=13
               ).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        button(pb, "Copy", self.copy_profile, height=28, width=10, icon_name="copy", icon_size=13
               ).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        button(pb, "Rename", self.rename_profile, height=28, width=10).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        button(pb, "Delete", self.delete_profile, danger=True, height=28, width=10, icon_name="trash", icon_size=13
               ).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        self.import_btn = button(pb, "Import", self._import_menu, height=28, width=10, icon_name="download", icon_size=13)
        self.import_btn.grid(row=2, column=0, sticky="ew", padx=2, pady=(8, 2))
        button(pb, "Export", self.export_profile, height=28, width=10, icon_name="upload", icon_size=13
               ).grid(row=2, column=1, sticky="ew", padx=2, pady=(8, 2))
        self.clear_all_btn = button(pb, "Clear all rules", self.clear_all_rules, height=28, width=10,
                                    icon_name="broom", icon_size=13, tip="Remove every rule of this playset")
        self.clear_all_btn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=(8, 2))
        self.health = ctk.CTkFrame(left, fg_color=CARD_HI, corner_radius=10)
        self.health.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 10))

        # ---- middle: the order (top) and the installed mods that aren't in it (bottom, resizable)
        mid = page_frame(split)
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_rowconfigure(2, weight=1)
        tb = ctk.CTkFrame(mid, fg_color="transparent")
        tb.grid(row=0, column=0, sticky="ew")
        self.sort_btn = button(tb, "Auto-sort", self.auto_sort, primary=True, width=112, icon_name="sparkle")
        self.sort_btn.pack(side="left")
        self.clear_rules_btn = button(tb, "", self.clear_rules_selected, width=32, icon_name="broom",
                                      tip="Clear the rules of the selected mod(s)")
        self.clear_rules_btn.pack(side="left", padx=(4, 0))
        self.undo_btn = button(tb, "", self.do_undo, width=32, icon_name="undo", tip="Undo")
        self.undo_btn.pack(side="left", padx=(8, 2))
        self.redo_btn = button(tb, "", self.do_redo, width=32, icon_name="redo", tip="Redo")
        self.redo_btn.pack(side="left", padx=(0, 10))
        for ic, d, tip in (("top", "top", "To the top (loads first)"), ("up", -1, "Up one (Alt+Up)"),
                           ("down", 1, "Down one (Alt+Down)"), ("bottom", "bottom", "To the bottom (loads last, wins)")):
            button(tb, "", lambda d=d: self.move_selected(d), width=32, icon_name=ic, tip=tip).pack(side="left", padx=1)
        self.onoff_btn = button(tb, "On/off", self.toggle_selected, width=74, icon_name="power", icon_size=13)
        self.onoff_btn.pack(side="left", padx=(10, 2))
        self.remove_btn = button(tb, "Remove", self.remove_selected, width=82, icon_name="minus", icon_size=13)
        self.remove_btn.pack(side="left", padx=2)
        tb.bind("<Configure>", self._toolbar_fit)
        tl = ctk.CTkFrame(mid, fg_color="transparent")
        tl.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        tl.grid_columnconfigure(1, weight=1)
        self.title = ctk.CTkLabel(tl, text="", text_color=TEXT, font=font(12, "bold"), anchor="w")
        self.title.grid(row=0, column=0, sticky="w")
        self.status = ctk.CTkLabel(tl, text="", text_color=MUTED, font=font(11, "bold"), anchor="e", justify="right")
        self.status.grid(row=0, column=1, sticky="e", padx=(10, 0))
        vsplit = Split(mid, app, "playsets_mid", orient="vertical")
        vsplit.grid(row=2, column=0, sticky="nsew")
        top = page_frame(vsplit)
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(0, weight=1)
        bottom = page_frame(vsplit)
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_rowconfigure(1, weight=1)
        cols = [("pos", "#", 32, "e", False), ("on", "On", 34, "center", False),
                ("name", "Mod  (top loads first, lower wins)", 220, "w", True), ("role", "Role", 150, "w", False),
                ("files", "Shared files", 110, "w", False), ("issues", "Issues", 74, "w", False)]
        self.order = Tree(top, cols, show_tree=True, big=True, image_width=72, main="name",
                          drop=("files", "role"), min_main=200, key="playsets.order")
        self.order.grid(row=0, column=0, sticky="nsew")
        t = self.order.tree
        t.bind("<ButtonPress-1>", self._press, add="+")
        t.bind("<B1-Motion>", self._motion, add="+")
        t.bind("<ButtonRelease-1>", self._release, add="+")
        t.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        t.bind("<space>", lambda e: (self.toggle_selected(), "break")[1])
        t.bind("<Alt-Up>", lambda e: (self.move_selected(-1), "break")[1])
        t.bind("<Alt-Down>", lambda e: (self.move_selected(1), "break")[1])
        t.bind("<Delete>", lambda e: self.remove_selected())
        for ev in RIGHT_CLICK:
            t.bind(ev, self._order_context, add="+")
        ex = ctk.CTkFrame(bottom, fg_color="transparent")
        ex.grid(row=0, column=0, sticky="ew", pady=(2, 4))
        ex.grid_columnconfigure(1, weight=1)
        self.extra_lbl = ctk.CTkLabel(ex, text="", text_color=TEXT, font=font(12, "bold"), anchor="w")
        self.extra_lbl.grid(row=0, column=0, sticky="w")
        self.extra_search = ctk.CTkEntry(ex, placeholder_text="Filter", width=160, height=26, fg_color=CARD,
                                         border_color=BORDER, text_color=TEXT, font=font(11))
        self.extra_search.grid(row=0, column=1, sticky="e", padx=(8, 6))
        self.extra_search.bind("<KeyRelease>", lambda e: self._render_extra())
        clearable(self.extra_search, self._render_extra)
        button(ex, "Add all", self.add_all_extra, height=26, width=80).grid(row=0, column=2, padx=(0, 4))
        button(ex, "Add to playset", self.add_extra, height=26, icon_name="up", icon_size=13).grid(row=0, column=3)
        self.extra = Tree(bottom, [("name", "Installed, not in this playset (double-click to add)", 380, "w", True),
                                   ("role", "Role", 150, "w", False), ("info", "Size", 80, "e", False)],
                          main="name", drop=("info", "role"), min_main=200, key="playsets.extra")
        self.extra.grid(row=1, column=0, sticky="nsew")
        self.extra.tree.bind("<Double-1>", lambda e: self.add_extra())
        for ev in RIGHT_CLICK:
            self.extra.tree.bind(ev, self._extra_context, add="+")
            self.plist.tree.bind(ev, self._plist_context, add="+")
        vsplit.add_pane(top, minsize=160, stretch="always")
        vsplit.add_pane(bottom, size=190, minsize=90, stretch="never", name="extra")

        # ---- right: details for the selected mod
        self.dp = DetailPane(split)
        self.detail = self.dp.body
        self.dp.on_resize = self.show_detail
        split.add_pane(lpane, size=250, minsize=180, stretch="never", name="list")
        split.add_pane(mid, minsize=400, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH, minsize=300, stretch="never", name="detail")
        self._buttons_state()

    def on_show(self):
        if self.dirty:
            self.render_order()

    def _toolbar_fit(self, e):
        """On a narrow middle pane the On/off and Remove buttons keep only their icons."""
        narrow = e.width < 520 * (e.width / max(1, units(e.width)))
        if narrow == getattr(self, "_narrow", None):
            return
        self._narrow = narrow
        self.onoff_btn.configure(text="" if narrow else "On/off", width=32 if narrow else 74)
        self.remove_btn.configure(text="" if narrow else "Remove", width=32 if narrow else 82)

    # ================================================================ data
    @property
    def an(self):
        return self.app.analysis

    def mods_by_key(self):
        return {m.key: m for m in self.app.mods}

    def enabled_keys(self):
        have = self.mods_by_key()
        return [k for k, on in self.entries if on and k in have]

    def load(self):
        """(Re)load the active playset of the current mod folder; make one if there are none."""
        md = self.app.mod_dir()
        prof = self.app.profiles
        if not md:
            self.name, self.entries, self.rules = "", [], []
            self.render_all()
            return
        if not prof.names(md) and self.app.mods_loaded:
            self._first_profile(md)
        self.name = prof.active(md)
        p = prof.get(md, self.name) or {"mods": [], "rules": []}
        self.entries = [(k, bool(on)) for k, on in p["mods"]]
        self.rules = [tuple(r) for r in p.get("rules", [])]
        self.undo, self.redo = [], []
        self.refresh_derived()
        self.render_all()
        self.app.conflicts_changed()

    def _first_profile(self, md):
        """First visit: start from what the game will load now (the launcher's last choice)."""
        game = self.app.game()
        cur = LA.read_load_file(game, LA.data_dir_of(md)) if game else []
        have = self.mods_by_key()
        if cur:
            entries = [(k, True) for k in cur if k in have]
            name = "Current game setup"
        else:
            entries = [(m.key, True) for m in sorted(self.app.mods, key=lambda m: m.name.lower())]
            name = "All mods"
        self.app.profiles.put(md, name, entries, [])
        self.app.log(f"Created playset \"{name}\" with {len(entries)} mods"
                     + (" (the mods the game loads right now)." if cur else "."))

    def save(self, push_undo=None):
        md = self.app.mod_dir()
        if not md or not self.name:
            return
        if push_undo is not None:
            self.undo.append(push_undo)
            self.undo = self.undo[-50:]
            self.redo.clear()
        self.app.profiles.put(md, self.name, self.entries, self.rules)
        self._buttons_state()
        self.app.library.render()

    def _snapshot(self):
        return (list(self.entries), list(self.rules))

    def change(self, entries=None, rules=None):
        """Every edit goes through here: undo point, save, recompute, redraw."""
        snap = self._snapshot()
        if entries is not None:
            self.entries = entries
        if rules is not None:
            self.rules = rules
        self.save(push_undo=snap)
        self.after_change()

    def after_change(self):
        self.refresh_derived()
        self.render_order()
        self.app.conflicts_changed()

    def do_undo(self):
        if self.undo:
            self.redo.append(self._snapshot())
            self.entries, self.rules = self.undo.pop()
            self.save()
            self.after_change()

    def do_redo(self):
        if self.redo:
            self.undo.append(self._snapshot())
            self.entries, self.rules = self.redo.pop()
            self.save()
            self.after_change()

    def _buttons_state(self):
        self.undo_btn.configure(state="normal" if self.undo else "disabled")
        self.redo_btn.configure(state="normal" if self.redo else "disabled")
        self.sort_btn.configure(state="normal" if self.entries and not self.app.running() else "disabled")

    # ================================================================ analysis results for this playset
    def analysis_ready(self):
        self.refresh_derived()
        self.render_all()
        if self.pending_sort:
            self.pending_sort = False
            self.auto_sort()

    def refresh_derived(self):
        an = self.an
        if an is None:
            self.win, self.reasons, self.issues, self.mod_issues = {}, {}, [], {}
            self.status.configure(text="Analysing your mods..." if self.app.analyzing else "", text_color=MUTED)
            self._render_health()
            return
        order = [k for k in self.enabled_keys() if k in an.facts]
        self.win = L.winners(an, order, set(order))
        self.reasons, broken = L.explain(an, order, rules=self.rules, older_first=self.older_first())
        self.issues = A.playset_issues(an, order, self.app.game_version())
        self.mod_issues = {}
        for i in self.issues:
            for k in i.mods:
                self.mod_issues.setdefault(k, []).append(i)
        lost = sum(len(v["loses"]) for v in self.win.values())
        parts = [f"⚠ {lost} file{'s' if lost != 1 else ''} lost to other mods" if lost else
                 "No mod loses a shared file with this order"]
        if broken:
            parts.append(f"{len(broken)} strong wish{'es' if len(broken) != 1 else ''} not met")
        if not an.used_vanilla:
            parts.append("set the game folder in Settings for a deeper check")
        self.status.configure(text="  ·  ".join(parts), text_color=WARN if lost or broken else OK)
        self._render_health()

    def _render_health(self):
        for w in self.health.winfo_children():
            w.destroy()
        if self.an is None or not self.name:
            ctk.CTkLabel(self.health, text="Checking compatibility..." if self.app.analyzing else "",
                         text_color=MUTED, font=font(11)).pack(padx=10, pady=8)
            return
        counts = A.summary(self.issues)
        ctk.CTkLabel(self.health, text="Compatibility", text_color=TEXT, font=font(12, "bold"), anchor="w"
                     ).pack(fill="x", padx=12, pady=(10, 4))
        row = ctk.CTkFrame(self.health, fg_color="transparent")
        row.pack(fill="x", padx=10)
        for sev in ("critical", "high", "medium", "low"):
            if counts[sev]:
                ctk.CTkLabel(row, text=f"{SEV_ICON[sev]} {counts[sev]}", text_color=SEV_COLOR[sev],
                             fg_color=SEV_SOFT[sev], corner_radius=8, height=24, padx=7,
                             font=font(12, "bold")).pack(side="left", padx=(0, 5))
        if not any(counts[s] for s in ("critical", "high", "medium", "low")):
            ctk.CTkLabel(row, text="\u2713 No problems found", text_color=OK, fg_color=OK_SOFT, corner_radius=8,
                         height=24, padx=8, font=font(12, "bold")).pack(side="left")
        button(self.health, "Open the Conflicts tab", lambda: self.app.show_tab("Conflicts"), height=28,
               icon_name="conflicts", icon_size=13).pack(fill="x", padx=10, pady=(8, 10))

    # ================================================================ drawing
    def render_all(self):
        self.render_profiles()
        self.render_order()
        self._buttons_state()

    def render_profiles(self):
        t = self.plist.tree
        t.delete(*t.get_children())
        md = self.app.mod_dir()
        names = self.app.profiles.names(md) if md else []
        for n in names:
            rid = t.insert("", "end", text=("●  " if n == self.name else "     ") + n, values=(n,),
                           tags=("bold",) if n == self.name else ())
            if n == self.name:
                t.selection_set(rid)
        self.app.header_profiles(names, self.name)

    def row_image(self, tree, m, role):
        if m is None:
            return ""
        return row_picture(tree, m.key, self.app.thumb(m), role)

    def render_order(self):
        if not self.app.visible("Playsets") and not self._drag:
            self.dirty = True                # drawn when the tab is opened
            self.title.configure(text=self._title_text())
            return
        self.dirty = False
        t = self.order.tree
        sel = {self.by_row.get(r) for r in t.selection()}
        t.delete(*t.get_children())
        self.by_row.clear()
        have = self.mods_by_key()
        gv = self.app.game_version()
        an = self.an
        n_on = 0
        for row_i, (k, on) in enumerate(self.entries):
            m = have.get(k)
            if on and m:
                n_on += 1
            name = m.name if m else f"{k} (not installed)"
            role = an.facts[k].role.role if an and k in an.facts and an.facts[k].role else R.UNKNOWN
            files, tag = "", ""
            w = self.win.get(k) if an else None
            if w and on:
                parts = []
                if w["wins"]:
                    parts.append(f"wins {len(w['wins'])}")
                if w["loses"]:
                    parts.append(f"loses {len(w['loses'])}")
                if w["merged"]:
                    parts.append(f"merged {len(w['merged'])}")
                files = " · ".join(parts)
                if w["loses"]:
                    tag = "high"
            iss = [i for i in self.mod_issues.get(k, []) if i.severity in ISSUE_COUNT_SEVS] if on else []
            worst = min((i.rank for i in iss), default=None)
            issue_txt = ""
            if iss:
                by = {}
                for i in iss:
                    by[i.severity] = by.get(i.severity, 0) + 1
                issue_txt = "  ".join(f"{SEV_ICON[s]}{n}" for s, n in sorted(by.items(), key=lambda kv: A.SEV_RANK[kv[0]]))
                tag = A.SEVERITIES[worst] if worst is not None and worst <= 1 else tag
            if not m:
                tag = "missing"
                issue_txt = MISS_ICON + " missing"
            elif V.compatible(m.supported, gv) is False:
                issue_txt = (issue_txt + "  " + VER_ICON).strip()
            if not on:
                tag = "muted"
            img = self.row_image(t, m, role)
            rid = t.insert("", "end", image=img, values=(n_on if on and m else "", "☑" if on else "☐",
                                                         name, role.name if m else "", files, issue_txt),
                           tags=tuple(x for x in (tag, "odd" if row_i % 2 else "") if x))
            self.by_row[rid] = k
            if k in sel:
                t.selection_add(rid)
        self.title.configure(text=self._title_text())
        self._render_extra()
        if not self._drag:
            self.show_detail()
        self._buttons_state()

    def _title_text(self):
        have = self.mods_by_key()
        n_on = sum(1 for k, on in self.entries if on and k in have)
        return (f"\"{self.name}\": {n_on} of {len(self.entries)} mods on" if self.name else
                "No playset yet. Pick your game at the top.")

    def _render_extra(self):
        t = self.extra.tree
        t.delete(*t.get_children())
        self.extra_rows.clear()
        listed = {k for k, _ in self.entries}
        an = self.an
        extra = sorted((m for m in self.app.mods if m.key not in listed), key=lambda m: m.name.lower())
        n_all = len(extra)
        q = self.extra_search.get().strip().lower()
        if q:
            extra = [m for m in extra if q in m.name.lower()]
        for i, m in enumerate(extra):
            role = an.facts[m.key].role.role.name if an and m.key in an.facts and an.facts[m.key].role else ""
            rid = t.insert("", "end", values=(m.name, role, modscan.human_size(m.size)), tags=("odd",) if i % 2 else ())
            self.extra_rows[rid] = m.key
        self.extra_lbl.configure(text=f"Not in this playset ({n_all})")

    def selected_keys(self):
        return [self.by_row[r] for r in self.order.tree.selection() if r in self.by_row]

    # ================================================================ detail pane
    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        keys = self.selected_keys()
        if len(keys) != 1:
            d.message(f"{len(keys)} mods selected. Drag them, use the arrows, or Alt+Up/Down." if keys else
                      "Select a mod to see what it is, why it sits where it does, which shared files it wins or "
                      "loses, and any conflicts it has in this playset.\n\nDrag rows to reorder (several at once "
                      "with Ctrl/Shift), click the box to turn a mod on or off. Auto-sort works out the best order "
                      "from the mods' files, what they use from each other, their Workshop pages and your rules.")
            return
        k = keys[0]
        have = self.mods_by_key()
        m = have.get(k)
        an = self.an
        f = an.facts.get(k) if an else None
        role = f.role.role if f and f.role else R.UNKNOWN
        d.begin()
        if m is None:
            d.accent(ERR)
            d.heading(k, "Not installed (deleted or never downloaded). It's skipped when you Play.", ERR)
            d.actions([("Remove from playset", lambda: self.remove_keys([k]), "minus", "normal")])
            d.end()
            return
        if icons.available():
            path = self.app.thumb(m)
            d.picture(icons.hero(path, role, 512), key=("lib", m.key, path))
        d.accent(role.color if f and f.role else ACCENT)
        enabled = self.enabled_keys()
        pos = (f"Loads {enabled.index(k) + 1} of {len(enabled)}" if k in enabled else "Turned off in this playset")
        d.heading(m.name, f"{pos}  \u00B7  {modscan.human_size(m.size)}  \u00B7  {len(m.files)} files")
        chips = []
        if f and f.role:
            chips.append((role.name, TEXT, CARD_HI, None,
                          badge_image(role, 16) if icons.available() else None))
            for sec in f.role.secondary[:1]:
                chips.append((sec.name, MUTED, CARD_HI, None,
                              badge_image(sec, 14) if icons.available() else None))
        if V.compatible(m.supported, self.app.game_version()) is False:
            chips.append((f"Made for {m.supported}", INFO, INFO_SOFT, None, None))
        d.chips(chips[:3])
        lib = self.app.library
        d.actions([("Turn off" if k in enabled else "Turn on", lambda: self.set_enabled([k], k not in enabled),
                    "power", "normal"),
                   ("Remove", lambda: self.remove_keys([k]), "minus", "normal"),
                   ("Open folder", lambda: lib.open_mod(m), "folder", "normal"),
                   ("Delete", lambda: lib.delete_mods([m]), "trash", "danger")])
        t = d.text
        note = self.app.crash_note(k)
        if note:
            t.add(note[0] + "  ", "crit", "bold")
            t.link("See the crash", lambda: self.app.show_crash_suspect(k))
            t.p("")
        self._rules_text(t, k)
        if f and f.role:
            t.p(f.role.why + (f"  \u00B7  mostly {f.role.focus}" if f.role.focus else ""), "muted", "small")
            t.add("   ")
            t.link("In Library", lambda: self.app.show_in_library(k), "small")
        if f is None:
            t.p("Analysing your mods..." if self.app.analyzing else "", "faint")
            d.end()
            return
        iss = [i for i in self.mod_issues.get(k, []) if i.severity != "info"]
        if iss:
            t.h("Conflicts in this playset")
            for i in iss[:8]:
                others = [an.facts[o].name for o in i.mods if o != k and o in an.facts]
                t.bullet(i.title + (f"  (with {', '.join(others)})" if others else ""), "sev_" + i.severity,
                         mark=SEV_ICON[i.severity])
            t.p("")
            t.link("Open them in the Conflicts tab", lambda: self.app.show_conflicts_for(k))
        reasons = [x for x in self.reasons.get(k, []) if x["kind"] != "tier"][:8]
        if reasons:
            t.h("Why it sits here")
            for x in reasons:
                where = ""
                if x["other"]:
                    where = f"{'after' if x['rel'] == 'after' else 'before'} {an.facts[x['other']].name}: "
                sure = L.SURE_LABEL.get(x.get("sure"), "")
                t.bullet(where + x["text"] + (f"  [{sure.lower()}]" if sure else ""), "ok" if x["ok"] else "warn",
                         mark="\u2713" if x["ok"] else "\u2717")
        w = self.win.get(k, {})
        if w.get("wins") or w.get("loses") or w.get("merged") or w.get("same"):
            t.h("Shared files with this order")
            if w.get("loses"):
                t.p(f"Loses {len(w['loses'])} file{'s' if len(w['loses']) != 1 else ''}", "warn", "bold")
                t.p("\n".join(f"{rel}  (to {an.facts[winner].name})" for rel, winner in w["loses"]), "mono")
            if w.get("wins"):
                t.p(f"Wins {len(w['wins'])} file{'s' if len(w['wins']) != 1 else ''}", "ok", "bold")
                t.p("\n".join(f"{rel}  (over {', '.join(an.facts[b].name for b in beaten)})"
                              for rel, beaten in w["wins"]), "mono")
            if w.get("merged"):
                t.p(f"Merged {len(w['merged'])}", "teal", "bold")
                t.p("\n".join(f"{rel}  ({an.facts[winner].name}'s copy includes these changes)"
                              for rel, winner in w["merged"]), "mono")
            if w.get("same"):
                t.p(f"{w['same']} shared file(s) are identical, so it doesn't matter who loads last.", "teal", "small")
        if f.builds_on or f.used_by:
            t.h("Connections")
            for o, n in sorted(f.builds_on.items(), key=lambda kv: -kv[1])[:4]:
                t.bullet(f"Uses {n} things from \"{an.facts[o].name}\"" + ("" if o in enabled else "  (turned off!)"),
                         "warn" if o not in enabled else "muted")
            for o, n in sorted(f.used_by.items(), key=lambda kv: -kv[1])[:4]:
                t.bullet(f"\"{an.facts[o].name}\" uses {n} things from it", "muted")
        d.end()

    # ---- your rules for this mod (top of the panel)
    def _rules_text(self, t, k):
        have = self.mods_by_key()
        name = lambda x: have[x].name if x in have else x
        mode = next((a for a, b in self.rules if a in L.PLACEMENTS and b == k), "")
        t.h("Your rules", small=True)
        t.p("Placement:  ", "small")
        for mk, label in (("", "Automatic"), ("@first", "First"), ("@early", "Early"), ("@late", "Late"),
                          ("@last", "Last")):
            if mk == mode:
                t.add(f" {label} ", "chip")
            else:
                t.link(label, lambda mk=mk: self.set_placement(k, mk), "small")
            t.add("   ")
        pairs = [(a, b) for a, b in self.rules if a not in L.PLACEMENTS and k in (a, b)]
        for a, b in pairs:
            t.bullet((f"Loads before \"{name(b)}\"" if a == k else f"Loads after \"{name(a)}\"") + "   ", "small")
            t.link("remove", lambda rule=(a, b): self.change(rules=[x for x in self.rules if x != rule]), "small")
        if any(x != k for x in self.enabled_keys()):
            t.p("")
            t.link("+ Loads after...", lambda: self._rule_menu(k, "after"), "small")
            t.add("     ")
            t.link("+ Loads before...", lambda: self._rule_menu(k, "before"), "small")
        if not mode and not pairs:
            t.p("Auto-sort always keeps your rules; it works out everything else.", "faint", "small")

    def rules_of(self, keys):
        keys = set(keys)
        return [r for r in self.rules if r[1] in keys or (r[0] not in L.PLACEMENTS and r[0] in keys)]

    def clear_rules_selected(self):
        keys = self.selected_keys()
        if not keys:
            self.app.toast("Select a mod first: its rules (placement, loads before/after) are cleared.")
            return
        gone = self.rules_of(keys)
        if not gone:
            self.app.toast("The selected mod has no rules." if len(keys) == 1 else "The selected mods have no rules.")
            return
        self.change(rules=[r for r in self.rules if r not in gone])
        self._reselect(set(keys))
        self.app.toast(f"Cleared {len(gone)} rule{'s' if len(gone) != 1 else ''}. Undo brings them back.")

    def clear_all_rules(self):
        if not self.name:
            return
        if not self.rules:
            self.app.toast(f"\"{self.name}\" has no rules.")
            return
        n = len(self.rules)
        if not messagebox.askyesno(APP_NAME, f"Remove all {n} rule{'s' if n != 1 else ''} of \"{self.name}\" "
                                             "(placements and loads before/after)?\n\nAuto-sort will then work out "
                                             "the whole order on its own. Undo brings them back.", parent=self.app):
            return
        self.change(rules=[])
        self.app.toast(f"Cleared all rules of \"{self.name}\".")

    def set_placement(self, k, mode):
        rules = [r for r in self.rules if not (r[0] in L.PLACEMENTS and r[1] == k)]
        if mode:
            rules.append((mode, k))
        self.change(rules=rules)

    def _rule_menu(self, k, rel):
        """A menu of the playset's other mods: this one loads after / before the one you pick."""
        have = self.mods_by_key()
        others = sorted(((have[x].name, x) for x in self.enabled_keys() if x != k and x in have),
                        key=lambda v: v[0].lower())

        class _At:
            pass
        at = _At()
        at.x_root, at.y_root = self.winfo_pointerxy()
        popup_menu(self, at, [(n, None, (lambda x=x: self._add_rule(x, k)) if rel == "after" else
                               (lambda x=x: self._add_rule(k, x))) for n, x in others])

    def _add_rule(self, a, b):
        if not a or not b or a == b:
            return
        rules = [x for x in self.rules if x not in ((a, b), (b, a))] + [(a, b)]
        self.change(rules=rules)

    # ================================================================ right-click
    def _row_at(self, tree, e, rows):
        rid = tree.identify_row(e.y)
        if rid not in rows:
            return None
        if rid not in tree.selection():
            tree.selection_set(rid)
            tree.focus(rid)
        return rid

    def _order_context(self, e):
        t = self.order.tree
        if not self._row_at(t, e, self.by_row):
            return
        keys = self.selected_keys()
        have = self.mods_by_key()
        mods = [have[k] for k in keys if k in have]
        lib = self.app.library
        if len(keys) > 1:
            on = all(o for k, o in self.entries if k in keys)
            popup_menu(t, e, [
                (f"Turn {len(keys)} {'off' if on else 'on'}", "power", self.toggle_selected),
                (f"Remove {len(keys)} from the playset", "minus", self.remove_selected),
                None,
                ("Move to the top", "top", lambda: self.move_selected("top")),
                ("Move to the bottom", "bottom", lambda: self.move_selected("bottom")),
                ("Clear their rules", "broom", self.clear_rules_selected, bool(self.rules_of(keys))),
                None,
                (f"Delete {len(mods)} mods", "trash", lambda: lib.delete_mods(mods), bool(mods))])
            return
        k = keys[0]
        m = have.get(k)
        on = dict(self.entries).get(k, False)
        mode = next((a for a, b in self.rules if a in L.PLACEMENTS and b == k), "")
        wid = U.workshop_id(m, self.app.registry()) if m else ""
        has_issues = bool(self.mod_issues.get(k))
        place = [(("✓ " if mk == mode else "") + label, None, lambda mk=mk: self.set_placement(k, mk))
                 for mk, label in (("", "Automatic"), ("@first", "Loads first"), ("@early", "Loads early"),
                                   ("@late", "Loads late"), ("@last", "Loads last"))]
        popup_menu(t, e, [
            ("Turn off" if on else "Turn on", "power", lambda: self.set_enabled([k], not on), m is not None),
            ("Remove from the playset", "minus", lambda: self.remove_keys([k])),
            None,
            ("Move to the top", "top", lambda: self.move_selected("top")),
            ("Move to the bottom", "bottom", lambda: self.move_selected("bottom")),
            ("Placement", "layers", place),
            ("Loads after...", "down", lambda: self._rule_menu(k, "after"), len(self.enabled_keys()) > 1),
            ("Loads before...", "up", lambda: self._rule_menu(k, "before"), len(self.enabled_keys()) > 1),
            ("Clear its rules", "broom", self.clear_rules_selected, bool(self.rules_of([k]))),
            None,
            ("Show its conflicts", "conflicts", lambda: self.app.show_conflicts_for(k), has_issues),
            ("Show in Library", "library", lambda: self.app.show_in_library(k), m is not None),
            ("Open folder", "folder", lambda: lib.open_mod(m), m is not None),
            ("Steam page", "external", lambda: webbrowser.open(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}"), bool(wid)),
            None,
            ("Delete", "trash", lambda: lib.delete_mods([m]), m is not None)])

    def _extra_context(self, e):
        t = self.extra.tree
        if not self._row_at(t, e, self.extra_rows):
            return
        keys = [self.extra_rows[r] for r in t.selection() if r in self.extra_rows]
        have = self.mods_by_key()
        mods = [have[k] for k in keys if k in have]
        one = len(mods) == 1
        popup_menu(t, e, [
            (f"Add {len(keys)} to the playset" if not one else "Add to the playset", "plus", self.add_extra),
            ("Add, turned off", "power", lambda: self.add_keys(keys, enabled=False)),
            None,
            ("Show in Library", "library", lambda: self.app.show_in_library(keys[0]), one),
            ("Open folder", "folder", lambda: self.app.library.open_mod(mods[0]), one),
            None,
            ("Delete" if one else f"Delete {len(mods)} mods", "trash", lambda: self.app.library.delete_mods(mods))])

    def _plist_context(self, e):
        t = self.plist.tree
        rid = t.identify_row(e.y)
        if not rid:
            return
        name = t.item(rid, "values")[0]
        if name != self.name:
            t.selection_set(rid)                 # picking it makes it the active playset
        popup_menu(t, e, [
            ("Rename", None, self.rename_profile),
            ("Copy", "copy", self.copy_profile),
            ("Export to the Paradox launcher", "upload", self.export_profile),
            None,
            ("Delete", "trash", self.delete_profile)])

    # ================================================================ editing the order
    def _press(self, e):
        t = self.order.tree
        row, col = t.identify_row(e.y), t.identify_column(e.x)
        self._drag = None
        if not row:
            return
        if col == "#2":                           # the On column: toggle
            k = self.by_row.get(row)
            self.change(entries=[(kk, (not on) if kk == k else on) for kk, on in self.entries])
            return "break"
        keys = self.selected_keys() if row in t.selection() and not (e.state & 0x5) else None
        self._drag = {"keys": keys, "moved": False, "start": list(self.entries)}

    def _motion(self, e):
        d = self._drag
        if not d:
            return
        t = self.order.tree
        if d["keys"] is None:
            d["keys"] = self.selected_keys()
        keys = d["keys"]
        tkey = self.by_row.get(t.identify_row(e.y))
        if not keys or not tkey or tkey in keys:
            return
        order_keys = [k for k, _ in self.entries]
        moving = [(k, on) for k, on in self.entries if k in keys]
        rest = [(k, on) for k, on in self.entries if k not in keys]
        ti = [k for k, _ in rest].index(tkey)
        down = order_keys.index(tkey) > order_keys.index(moving[0][0])
        ins = ti + 1 if down else ti
        new = rest[:ins] + moving + rest[ins:]
        if new == self.entries:
            return
        self.entries = new
        d["moved"] = True
        rid_of = {k: r for r, k in self.by_row.items()}          # move the rows; a full redraw waits for the drop
        for idx, (k, _) in enumerate(new):
            if k in rid_of:
                t.move(rid_of[k], "", idx)
        self._reselect(keys)
        sel = t.selection()
        if sel:
            t.see(sel[0])

    def _release(self, e):
        d = self._drag
        self._drag = None
        if d and d["moved"]:
            self.undo.append((d["start"], list(self.rules)))
            self.undo = self.undo[-50:]
            self.redo.clear()
            self.save()
            self.after_change()

    def _reselect(self, keys):
        rows = [r for r, k in self.by_row.items() if k in keys]
        self.order.tree.selection_set(rows)

    def move_selected(self, d):
        keys = self.selected_keys()
        if not keys:
            return
        moving = [(k, on) for k, on in self.entries if k in keys]
        rest = [(k, on) for k, on in self.entries if k not in keys]
        first = [k for k, _ in self.entries].index(moving[0][0])
        if d == "top":
            new = moving + rest
        elif d == "bottom":
            new = rest + moving
        else:
            pos = max(0, min(len(rest), first + d))
            new = rest[:pos] + moving + rest[pos:]
        if new != self.entries:
            self.change(entries=new)
            self._reselect(keys)

    def toggle_selected(self):
        keys = set(self.selected_keys())
        if keys:
            turn_on = not all(on for k, on in self.entries if k in keys)
            self.change(entries=[(k, turn_on if k in keys else on) for k, on in self.entries])
            self._reselect(keys)

    def set_enabled(self, keys, on):
        keys = set(keys)
        self.change(entries=[(k, on if k in keys else e) for k, e in self.entries])

    def remove_selected(self):
        keys = set(self.selected_keys())
        if keys:
            self.change(entries=[(k, on) for k, on in self.entries if k not in keys],
                        rules=[r for r in self.rules if r[0] not in keys and r[1] not in keys])

    def add_extra(self):
        keys = [self.extra_rows[r] for r in self.extra.tree.selection() if r in self.extra_rows]
        if keys:
            self.add_keys(keys)

    def add_all_extra(self):
        keys = list(self.extra_rows.values())
        if keys and messagebox.askyesno(APP_NAME, f"Add all {len(keys)} listed mods to \"{self.name}\"? They go at "
                                                  "the bottom; Auto-sort can place them.", parent=self.app):
            self.add_keys(keys)

    def add_keys(self, keys, enabled=True):
        listed = {k for k, _ in self.entries}
        new = [(k, enabled) for k in keys if k not in listed]
        if new:
            self.change(entries=self.entries + new)

    def remove_keys(self, keys):
        keys = set(keys)
        self.change(entries=[(k, on) for k, on in self.entries if k not in keys],
                    rules=[r for r in self.rules if r[0] not in keys and r[1] not in keys])

    def select_key(self, key):
        if self.dirty:
            self.render_order()
        for rid, k in self.by_row.items():
            if k == key:
                self.order.tree.selection_set(rid)
                self.order.tree.see(rid)

    # ================================================================ auto-sort
    def older_first(self):
        return bool(self.app.cfg.get("older_first", False))

    def set_older_first(self, on):
        self.app.cfg["older_first"] = bool(on)
        self.app.save()
        self.refresh_derived()

    def sort_result(self):
        """(result, files lost before, files lost after) of Auto-sort for the current playset."""
        an = self.an
        keys = self.enabled_keys()
        current = [k for k, _ in self.entries]
        res = L.solve(an, current, set(keys), self.rules, older_first=self.older_first())
        before = L.winners(an, keys, set(keys))
        after = L.winners(an, res.enabled_order, set(keys))
        return (res, sum(len(v["loses"]) for v in before.values()),
                sum(len(v["loses"]) for v in after.values()))

    def auto_sort(self):
        if not self.entries:
            return
        keys = self.enabled_keys()
        if not keys:
            self.app.toast("Turn on at least one mod first.")
            return
        an = self.an
        if an is None or self.app.analyzing or any(k not in an.facts for k in keys):
            self.pending_sort = True
            self.app.schedule_analysis()
            self.status.configure(text="Analysing before sorting...")
            return
        res, lost_before, lost_after = self.sort_result()
        SortPreview(self, an, keys, res, lost_before, lost_after)

    def apply_sort(self, res):
        on = dict(self.entries)
        self.change(entries=[(k, on[k]) for k in res.order])
        self.app.toast(f"Auto-sort applied: {res.moved} mod{'s' if res.moved != 1 else ''} moved. The undo button "
                       "puts it back.")

    # ================================================================ playsets
    def _picked_profile(self, e=None):
        sel = self.plist.tree.selection()
        if not sel:
            return
        name = self.plist.tree.item(sel[0], "values")[0]
        if name != self.name:
            self.app.set_active_profile(name)

    def activate(self, name):
        md = self.app.mod_dir()
        if md and name in self.app.profiles.names(md):
            self.app.profiles.set_active(md, name)
            self.load()

    def _ask(self, title, text, initial=""):
        d = ctk.CTkInputDialog(title=title, text=text)
        try:
            d.after(50, lambda: (d._entry.insert(0, initial), d._entry.select_range(0, "end")))
        except Exception:
            pass
        v = d.get_input()
        return (v or "").strip()

    def new_profile(self):
        md = self.app.mod_dir()
        if not md:
            return
        name = self._ask("New playset", "Name of the new playset (starts empty):")
        if name:
            name = self.app.profiles.unique_name(md, name)
            self.app.profiles.put(md, name, [], [])
            self.load()

    def copy_profile(self):
        md = self.app.mod_dir()
        if not md or not self.name:
            return
        name = self.app.profiles.unique_name(md, self.name + " copy")
        self.app.profiles.put(md, name, self.entries, self.rules)
        self.load()

    def rename_profile(self):
        md = self.app.mod_dir()
        if not md or not self.name:
            return
        new = self._ask("Rename playset", f"New name for \"{self.name}\":", self.name)
        if new and new != self.name:
            if not self.app.profiles.rename(md, self.name, new):
                messagebox.showwarning(APP_NAME, f"There is already a playset called \"{new}\".", parent=self.app)
            self.load()

    def delete_profile(self):
        md = self.app.mod_dir()
        if not md or not self.name:
            return
        if messagebox.askyesno(APP_NAME, f"Delete the playset \"{self.name}\"?\n\nOnly the list is deleted; "
                                         "the mods stay installed.", parent=self.app):
            self.app.profiles.delete(md, self.name)
            self.load()

    def _import_menu(self):
        md = self.app.mod_dir()
        if not md:
            return
        menu = tk.Menu(self, tearoff=0, bg=pick(CARD), fg=pick(TEXT), activebackground=pick(ACCENT),
                       activeforeground="white")
        menu.add_command(label="What the game loads now (last launch)", command=self.import_current)
        try:
            sets = LA.read_playsets(os.path.join(LA.data_dir_of(md), "launcher-v2.sqlite"))
        except Exception as e:
            sets = []
            menu.add_command(label=f"Paradox launcher: couldn't read ({e})", state="disabled")
        if sets:
            menu.add_separator()
            for s in sets:
                menu.add_command(label=f"Paradox launcher: {s['name']} ({len(s['mods'])} mods)"
                                       + ("  • active" if s["active"] else ""),
                                 command=lambda s=s: self.import_launcher(s))
        x = self.import_btn.winfo_rootx()
        y = self.import_btn.winfo_rooty() + self.import_btn.winfo_height()
        menu.tk_popup(x, y)

    def import_current(self):
        md = self.app.mod_dir()
        game = self.app.game()
        keys = LA.read_load_file(game, LA.data_dir_of(md)) if game else []
        if not keys:
            messagebox.showinfo(APP_NAME, "The game isn't set to load any mods right now.", parent=self.app)
            return
        name = self.app.profiles.unique_name(md, "Current game setup")
        self.app.profiles.put(md, name, [(k, True) for k in keys], [])
        self.load()

    def import_launcher(self, s):
        md = self.app.mod_dir()
        name = self.app.profiles.unique_name(md, s["name"])
        self.app.profiles.put(md, name, s["mods"], [])
        have = self.mods_by_key()
        missing = [k for k, _ in s["mods"] if k not in have]
        self.load()
        self.app.toast(f"Imported \"{s['name']}\" ({len(s['mods'])} mods" +
                       (f", {len(missing)} not installed here)" if missing else ")"))

    def export_profile(self):
        md = self.app.mod_dir()
        if not md or not self.name:
            return
        db = os.path.join(LA.data_dir_of(md), "launcher-v2.sqlite")
        target = f"{self.name} ({APP_SHORT})"
        if not messagebox.askyesno(APP_NAME, f"Add this playset to the Paradox launcher as \"{target}\"?\n\n"
                                             "Close the launcher first. A backup of its database is made, and a "
                                             "playset with the same name there is replaced. Playing from this "
                                             "app doesn't need this.", parent=self.app):
            return
        have = self.mods_by_key()
        try:
            name, n = LA.export_playset(db, target, [(k, on) for k, on in self.entries if k in have], have,
                                        os.path.join(self.app.work_dir, "backups"))
            self.app.toast(f"Exported \"{name}\" ({n} mods) to the Paradox launcher.")
        except LA.LauncherError as e:
            messagebox.showwarning(APP_NAME, f"Export didn't happen: {e}", parent=self.app)


# ====================================================================== preview of an auto-sort
KIND_LABEL = {"rule": "your rule", "dependency": "dependency", "compatch": "patch / add-on", "hint": "Workshop page",
              "merge": "merged file", "clash": "shared files", "builds_on": "builds on", "replace_path": "replace_path",
              "position": "Workshop page", "convention": "convention", "tier": "conventional order",
              "placement": "your rule", "version": "game version"}


class SortPreview(ctk.CTkToplevel):
    def __init__(self, page, an, old, res, lost_before, lost_after):
        super().__init__(page.app, fg_color=page.app.cget("fg_color"))
        import appicon
        from gui_common import APP_DIR
        self.page, self.an, self.old = page, an, old
        self.title(f"Auto-sort - {APP_NAME}")
        fit_geometry(self, 1120, 680, page.app)
        self.minsize(780, 480)
        self.transient(page.app)
        appicon.apply(self, APP_DIR)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.head = ctk.CTkLabel(self, text="", text_color=TEXT, font=font(17, "bold"), anchor="w")
        self.head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        self.sub = ctk.CTkLabel(self, text="", text_color=MUTED, font=font(12), anchor="w", justify="left",
                                wraplength=1040)
        self.sub.grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 8))
        self.tree = Tree(self, [("new", "New", 44, "e", False), ("mod", "Mod", 270, "w", True),
                                ("old", "Was", 44, "e", False), ("move", "", 46, "center", False),
                                ("kind", "Because of", 110, "w", False), ("sure", "How sure", 84, "w", False),
                                ("why", "Main reason", 440, "w", True)],
                         selectmode="browse", show_tree=True, big=True, image_width=72, key="sortpreview")
        self.tree.grid(row=2, column=0, sticky="nsew", padx=16)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=16, pady=12)
        foot.grid_columnconfigure(0, weight=1)
        self.older = ctk.BooleanVar(value=page.older_first())
        ctk.CTkCheckBox(foot, text="Mods for older game versions load first", variable=self.older,
                        command=self._older, text_color=TEXT, font=font(12), fg_color=ACCENT,
                        checkbox_width=18, checkbox_height=18).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(foot, text="Only shared files depend on load order. Mods that share nothing keep your order, "
                                "except fix packs and total conversions near the top, interface mods near the "
                                "bottom, and add-ons, compatches and translations after the mods they're for. "
                                "How sure: certain (your rules, declared dependencies), likely (evidence in the "
                                "files or Workshop page), possible (weaker evidence), convention (no effect in game).",
                     text_color=MUTED, font=font(10), anchor="w", justify="left", wraplength=780
                     ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        btns = ctk.CTkFrame(foot, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, sticky="e")
        button(btns, "Cancel", self.destroy, width=90, height=34).pack(side="left", padx=8)
        button(btns, "Apply", self._apply, primary=True, width=100, height=34).pack(side="left")
        self.fill(res, lost_before, lost_after)
        self.after(150, self._grab)

    def fill(self, res, lost_before, lost_after):
        an, old, page = self.an, self.old, self.page
        self.res = res
        moved_keys = L.moved_keys(old, res.enabled_order)
        moved = len(moved_keys)
        self.head.configure(text="Best order found" if moved else "Your order is already the best one found")
        parts = [f"{moved} of {len(old)} mods move" if moved else "nothing to move",
                 f"files lost to other mods: {lost_before} → {lost_after}"]
        sure = {}
        for k in moved_keys:
            s = res.sure.get(k, "convention")
            sure[s] = sure.get(s, 0) + 1
        if sure:
            parts.append(", ".join(f"{n} {L.SURE_LABEL[s].lower()}" for s, n in
                                   sorted(sure.items(), key=lambda x: list(L.SURE_LABEL).index(x[0]))))
        if res.broken:
            parts.append(f"{len(res.broken)} strong wish{'es' if len(res.broken) != 1 else ''} can't all be met "
                         "(they contradict each other)")
        if not an.used_vanilla:
            parts.append("set the game folder in Settings to compare with the game's own files")
        self.sub.configure(text="  ·  ".join(parts))
        t = self.tree.tree
        t.delete(*t.get_children())
        oldpos = {k: i for i, k in enumerate(old)}
        have = page.mods_by_key()
        for i, k in enumerate(res.enabled_order):
            mv = k in moved_keys
            d = oldpos[k] - i if mv else 0
            arrow = f"↑{d}" if d > 0 else (f"↓{-d}" if d < 0 else "")
            why = L.main_reason(res.reasons.get(k, []))
            text, kind, how = "", "", ""
            if mv:
                if why:
                    kind = KIND_LABEL.get(why["kind"], why["kind"])
                    text = why["text"]
                    if why["other"]:
                        text = f"{'after' if why['rel'] == 'after' else 'before'} {an.facts[why['other']].name}: {text}"
                else:
                    kind, text = "conventional order", "its role's usual place (no effect in game)"
                how = L.SURE_LABEL.get(res.sure.get(k, "convention"), "")
            f = an.facts[k]
            img = page.row_image(t, have.get(k), f.role.role if f.role else R.UNKNOWN)
            t.insert("", "end", image=img, values=(i + 1, f.name, oldpos[k] + 1, arrow, kind, how, text),
                     tags=("update",) if mv else ())
        self.tree.stripe()

    def _older(self):
        self.page.set_older_first(self.older.get())
        self.fill(*self.page.sort_result())

    def _grab(self):
        try:
            self.grab_set()
            self.focus()
        except Exception:
            pass

    def _apply(self):
        self.page.apply_sort(self.res)
        self.destroy()
