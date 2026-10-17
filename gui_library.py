"""The Library tab: every mod in the mod folder, with conflicts, version notes and updates."""
import os
import threading
import time
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

import analysis as A
import icons
import installer
import modscan
import roles as R
import net as N
import updates as U
import versions as V
from gui_common import (ACCENT, ACCENT_SOFT, APP_NAME, BORDER, CARD, CARD_HI, ERR, ERR_SOFT, INFO, INFO_SOFT,
                        MISS_ICON, MUTED, MUTED_SOFT, OK, OK_SOFT, SEV_ICON, TAB_ON, TAB_ON_HI, TEXT, UPD_ICON,
                        VER_ICON, WARN, WARN_ICON, WARN_SOFT, DetailPane, Split, Tree, button, ctk_image, font, icon,
                        open_folder, page_frame, pill, row_picture, DETAIL_WIDTH)

SORT_FOR_COLUMN = {"name": "Name", "version": "Mod version", "game": "Game version", "size": "Size",
                   "files": "File count"}


class LibraryPage(ctk.CTkFrame):
    FILTERS = ["All", "Conflicts", "Updates", "Version"]

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.checking = False
        self.dirty = False
        self.shown = []                 # mods in the tree, in order
        self.by_row = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(bar, placeholder_text="Search your mods", height=30, fg_color=CARD,
                                   border_color=BORDER, text_color=TEXT)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda e: self.render())
        self.filter = ctk.CTkSegmentedButton(bar, values=self.FILTERS, command=lambda v: self.render(),
                                             fg_color=BORDER, selected_color=TAB_ON, selected_hover_color=TAB_ON_HI,
                                             unselected_color=CARD_HI, unselected_hover_color=BORDER,
                                             text_color=TEXT, font=font(11), height=30)
        self.filter.set("All")
        self.filter.grid(row=0, column=1, padx=(0, 8))
        srt = ctk.CTkFrame(bar, fg_color="transparent")
        srt.grid(row=0, column=3)
        ctk.CTkLabel(srt, text="Sort", text_color=MUTED, font=font(11)).pack(side="left", padx=(0, 4))
        self.sort_by = ctk.CTkOptionMenu(srt, values=modscan.SORTS, width=140, height=30, fg_color=CARD,
                                         button_color=CARD, button_hover_color=BORDER, text_color=TEXT,
                                         font=font(11), command=lambda v: self._sort_changed())
        self.sort_by.set(app.cfg.get("mod_sort", "Name"))
        self.sort_by.pack(side="left")
        self.sort_dir = button(srt, "", self._flip_dir, width=32, icon_name="up", tip="Ascending / descending")
        self.sort_dir.pack(side="left", padx=(4, 0))
        self._dir_label()
        self.role_filter = ctk.CTkOptionMenu(bar, values=["All roles"] + [r.name for r in R.ROLES], width=160,
                                             height=30, fg_color=CARD, button_color=CARD,
                                             button_hover_color=BORDER, text_color=TEXT, font=font(11),
                                             dynamic_resizing=False, command=lambda v: self.render())
        self.role_filter.set("All roles")
        self.role_filter.grid(row=0, column=2, padx=(0, 8))

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        info.grid_columnconfigure(3, weight=1)
        self.summary = pill(info, "", MUTED, MUTED_SOFT, size=12)
        self.summary.grid(row=0, column=0, sticky="w")
        self.vsummary = pill(info, "", INFO, INFO_SOFT)
        self.vsummary.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.utext = pill(info, "", MUTED, MUTED_SOFT)
        self.utext.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.check_btn = button(info, "Check updates", self.check_updates, height=28, icon_name="refresh",
                                icon_size=13)
        self.check_btn.grid(row=0, column=4, padx=(8, 6))
        self.uall = button(info, "Update all", self.update_all, primary=True, height=28, icon_name="download",
                           icon_size=13)
        self.uall.grid(row=0, column=5, padx=(0, 6))
        self.uall.grid_remove()
        button(info, "Rescan", app.rescan, width=84, height=28, icon_name="refresh", icon_size=13).grid(row=0, column=6)

        cols = [("name", "Mod", 230, "w", True), ("role", "Role", 150, "w", False),
                ("version", "Version", 70, "w", False), ("game", "Made for", 78, "w", False),
                ("size", "Size", 78, "e", False), ("files", "Files", 52, "e", False),
                ("flags", "Notes", 58, "w", False), ("playset", "Playset", 64, "center", False)]
        split = Split(self, app, "library")
        split.grid(row=2, column=0, sticky="nsew")
        left = page_frame(split)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        self.table = Tree(left, cols, show_tree=True, big=True, image_width=72, main="name",
                          drop=("files", "version", "size", "game"), min_main=210)
        self.table.grid(row=0, column=0, sticky="nsew")
        t = self.table.tree
        for cid, *_ in cols:
            if cid in SORT_FOR_COLUMN:
                t.heading(cid, command=lambda c=cid: self._sort_column(c))
        t.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        t.bind("<Double-1>", lambda e: self._open_selected())
        t.bind("<Delete>", lambda e: self.delete_mods(self.selected()))
        self.dp = DetailPane(split)
        self.dp.on_resize = self.show_detail
        split.add_pane(left, minsize=420, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH, minsize=300, stretch="never", name="detail")
        self.empty = ctk.CTkLabel(self.table, text="", text_color=MUTED, font=font(12))
        self.show_detail()

    def on_show(self):
        if self.dirty:
            self.render()

    def select_key(self, key):
        if self.dirty:
            self.render()
        rows = [r for r, m in self.by_row.items() if m.key == key]
        if not rows and (self.search.get() or self.filter.get() != "All" or self.role_filter.get() != "All roles"):
            self.search.delete(0, "end")
            self.filter.set("All")
            self.role_filter.set("All roles")
            self.render()
            rows = [r for r, m in self.by_row.items() if m.key == key]
        if rows:
            self.table.tree.selection_set(rows[0])
            self.table.tree.see(rows[0])

    # ---------------------------------------------------------------- settings-backed state
    def _ignored(self):
        return set(self.app.cfg.get("ignored_mods", {}).get(os.path.normcase(self.app.mod_dir()), []))

    def set_ignored(self, mods, on):
        key = os.path.normcase(self.app.mod_dir())
        store = self.app.cfg.setdefault("ignored_mods", {})
        cur = set(store.get(key, []))
        for m in mods:
            cur.add(m.key) if on else cur.discard(m.key)
        store[key] = sorted(cur)
        self.app.save()
        modscan.compute_conflicts(self.app.mods, cur)
        self.refresh_view()

    def _sort_changed(self):
        self.app.cfg["mod_sort"] = self.sort_by.get()
        self.app.save()
        self.render()

    def _sort_column(self, col):
        by = SORT_FOR_COLUMN[col]
        if self.sort_by.get() == by:
            self._flip_dir()
        else:
            self.sort_by.set(by)
            self._sort_changed()

    def _flip_dir(self):
        self.app.cfg["mod_sort_desc"] = not self.app.cfg.get("mod_sort_desc", False)
        self.app.save()
        self._dir_label()
        self.render()

    def _dir_label(self):
        self.sort_dir.configure(text="", image=icon("down" if self.app.cfg.get("mod_sort_desc", False) else "up", 15))

    # ---------------------------------------------------------------- data
    def flags(self, m):
        gv = self.app.game_version()
        f = []
        if m.missing:
            f.append(MISS_ICON)
        elif m.conflicts and not m.ignored:
            f.append(WARN_ICON)
        if V.compatible(m.supported, gv) is False:
            f.append(VER_ICON)
        if self.app.updates.get(m.key, {}).get("update"):
            f.append(UPD_ICON)
        return f

    def refresh_view(self):
        """Mods (re)scanned or their state changed: summaries + table + detail."""
        mods = self.app.mods
        n = sum(1 for m in mods if m.conflicts and not m.ignored)
        ign = sum(1 for m in mods if m.ignored)
        tail = f"  ({ign} ignored)" if ign else ""
        d = self.app.mod_dir()
        if self.app.scan_error:
            self.summary.configure(text=f"Could not read the folder ({self.app.scan_error})", text_color=ERR,
                                   fg_color=ERR_SOFT)
        elif not d or not os.path.isdir(d):
            self.summary.configure(text="Pick your game at the top to see its mods.", text_color=MUTED,
                                   fg_color=MUTED_SOFT)
        elif n:
            self.summary.configure(text=f"{WARN_ICON}  {n} of {len(mods)} mods share files with another mod{tail}",
                                   text_color=WARN, fg_color=WARN_SOFT)
        else:
            self.summary.configure(text=(f"\u2713  {len(mods)} mods, no file conflicts{tail}" if mods else
                                         "No mods in this folder yet"), text_color=OK if mods else MUTED,
                                   fg_color=OK_SOFT if mods else MUTED_SOFT)
        gv = self.app.game_version()
        off = sum(1 for m in mods if V.compatible(m.supported, gv) is False)
        if not gv:
            self.vsummary.configure(text="Set your game version (top) for version notes.", text_color=MUTED,
                                    fg_color=MUTED_SOFT)
        else:
            self.vsummary.configure(text=(f"{VER_ICON}  {off} made for another version than {V.clean(gv)}" if off
                                          else f"All fit game {V.clean(gv)}"), text_color=INFO if off else MUTED,
                                    fg_color=INFO_SOFT if off else MUTED_SOFT)
        self._update_bar()
        self.render()

    def render(self):
        if not self.app.visible("Library"):
            self.dirty = True                  # drawn when the tab is opened
            return
        self.dirty = False
        t = self.table.tree
        sel = {self.by_row[r].key for r in t.selection() if r in self.by_row}
        t.delete(*t.get_children())
        self.by_row.clear()
        mods, f = self.app.mods, self.filter.get()
        gv = self.app.game_version()
        if f == "Conflicts":
            worst = self.worst_issue()
            mods = [m for m in mods if ((m.conflicts or m.missing) and not m.ignored) or worst.get(m.key, 9) <= 1]
        elif f == "Updates":
            mods = [m for m in mods if self.app.updates.get(m.key, {}).get("update")]
        elif f == "Version":
            mods = [m for m in mods if V.compatible(m.supported, gv) is False]
        q = self.search.get().strip().lower()
        if q:
            mods = [m for m in mods if q in m.name.lower() or q in m.key.lower()]
        rf = self.role_filter.get()
        if rf != "All roles":
            mods = [m for m in mods if self.role(m).name == rf]
        mods = modscan.sort_mods(mods, self.sort_by.get(), self.app.cfg.get("mod_sort_desc", False))
        in_set, on_set = self.app.playset_keys()
        self.shown = mods
        for i, m in enumerate(mods):
            fl = self.flags(m)
            tag = ("missing" if m.missing else "muted" if m.ignored else "conflict" if WARN_ICON in fl else
                   "update" if UPD_ICON in fl else "version" if VER_ICON in fl else "")
            pl = "✓" if m.key in on_set else ("off" if m.key in in_set else "")
            role = self.role(m)
            img = row_picture(t, m.key, self.app.thumb(m), role)
            rid = t.insert("", "end", image=img, values=(m.name, role.name if self.app.analysis else "...",
                                                         m.version or "", m.supported or "",
                                                         modscan.human_size(m.size), len(m.files), " ".join(fl), pl),
                           tags=tuple(x for x in (tag, "odd" if i % 2 else "") if x))
            self.by_row[rid] = m
            if m.key in sel:
                t.selection_add(rid)
        if not mods:
            msg = "No mods match." if self.app.mods else "No mods in this folder yet."
            self.empty.configure(text=msg, image=icon("library", 40, MUTED), compound="top")
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty.place_forget()
        self.show_detail()

    def worst_issue(self):
        """{mod key: rank of its worst possible conflict with any other installed mod}"""
        an = self.app.analysis
        out = {}
        if an is not None:
            for i in an.issues:
                for k in i.mods:
                    out[k] = min(out.get(k, 9), A.SEV_RANK.get(i.severity, 9))
        return out

    def role(self, m):
        an = self.app.analysis
        f = an.facts.get(m.key) if an else None
        return f.role.role if f and f.role else R.UNKNOWN

    def selected(self):
        return [self.by_row[r] for r in self.table.tree.selection() if r in self.by_row]

    # ---------------------------------------------------------------- detail pane
    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        mods = self.selected()
        if not mods:
            d.message("Select a mod to see what it is, whether it fits your game version, its updates and the files "
                      "it shares with other mods.\n\nCtrl/Shift-click selects several for bulk actions.")
            return
        if len(mods) > 1:
            self._multi_detail(mods)
            return
        m = mods[0]
        reg = self.app.registry()
        upd = self.app.updates.get(m.key) or {}
        gv = self.app.game_version()
        an = self.app.analysis
        f = an.facts.get(m.key) if an else None
        role = f.role.role if f and f.role else R.UNKNOWN
        d.begin()
        if icons.available():
            path = self.app.thumb(m)
            d.picture(icons.hero(path, role, 512), key=("lib", m.key, path))
        d.accent(role.color if f and f.role else ACCENT)
        bits = [f"v{m.version}" if m.version else "", f"for game {m.supported}" if m.supported else "",
                modscan.human_size(m.size), f"{len(m.files)} files"]
        d.heading(m.name, "  \u00B7  ".join(b for b in bits if b))
        chips = []
        if f and f.role:
            chips.append((role.name, TEXT, CARD_HI, None,
                          ctk_image(icons.badge(role, 48), (16, 16)) if icons.available() else None))
        if upd.get("update"):
            chips.append(("Update", ACCENT, ACCENT_SOFT, "refresh", None))
        if V.compatible(m.supported, gv) is False:
            chips.append((f"Made for {m.supported}", INFO, INFO_SOFT, None, None))
        if m.conflicts and not m.ignored:
            chips.append(("Shares files", WARN, WARN_SOFT, "alert", None))
        d.chips(chips[:3])
        in_set, on_set = self.app.playset_keys()
        acts = []
        if upd.get("update"):
            acts.append(("Update", lambda: self.update_mods([m]), "download", "primary"))
        if m.key in in_set:
            acts.append(("In playset", lambda: self.app.show_in_playset(m.key), "playsets", "normal"))
        else:
            acts.append(("Add to playset", lambda: self.app.add_to_playset([m.key]), "plus", "normal"))
        wid = U.workshop_id(m, reg)
        if wid:
            acts.append(("Steam page", lambda: webbrowser.open(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}"), "external", "normal"))
        acts.append(("Open folder", lambda: self.open_mod(m), "folder", "normal"))
        acts.append(("Unignore conflicts" if m.ignored else "Ignore conflicts",
                     lambda: self.set_ignored([m], not m.ignored), "filter_off", "normal"))
        acts.append(("Delete", lambda: self.delete_mods([m]), "trash", "danger"))
        d.actions(acts)
        t = d.text
        if f and f.role:
            t.p(f.role.why + (f"  \u00B7  mostly {f.role.focus}" if f.role.focus else ""), "muted", "small")
            ach = dict(f.role.attrs).get("achievements")
            t.p("\u2713 Achievement-friendly: changes nothing the game checksums" if ach else
                "Changes checksummed files: no achievements, no Ironman", "ok" if ach else "faint", "small")
        src = reg.get(os.path.splitext(m.key)[0], {}).get("source", "")
        notes = []
        if m.missing:
            notes.append((f"{MISS_ICON}  The .mod file points to a folder that isn't there.", "err"))
        if m.duplicate_of:
            notes.append((f"Same folder as \"{m.duplicate_of.name}\" (a duplicate entry, not a conflict).", "muted"))
        if m.ignored:
            notes.append(("Ignored: left out of conflict checks.", "muted"))
        if V.compatible(m.supported, gv) is False:
            notes.append((f"{VER_ICON}  Made for game {m.supported}; you play {V.clean(gv)}. It usually still loads.",
                          "info"))
        if upd.get("update"):
            notes.append((f"{UPD_ICON}  Newer Workshop version from {U.when(upd['steam_updated'])} "
                          f"(yours: {U.when(upd['local_updated'])}).", "accent"))
        elif upd.get("gone"):
            notes.append(("No longer on the Workshop (removed or made private).", "muted"))
        if m.same_files:
            notes.append((f"Shares {len(m.same_files)} identical file{'s' if len(m.same_files) != 1 else ''} with "
                          "other mods (same content, so not a conflict).", "teal"))
        for text, tag in notes:
            t.p(text, tag)
        if an is not None:
            mine = [i for i in an.issues if m.key in i.mods and i.severity in ("critical", "high", "medium")]
            if mine:
                t.h("Possible conflicts with other installed mods")
                for i in mine[:8]:
                    others = [an.facts[o].name for o in i.mods if o != m.key and o in an.facts]
                    t.bullet(i.title + (f"  (with {', '.join(others)})" if others else ""), "sev_" + i.severity,
                             mark=SEV_ICON[i.severity])
                t.p("These only matter when both are on in a playset; the Conflicts tab explains the ones in your "
                    "active playset.", "faint", "small")
        if m.conflicts and not m.ignored:
            others = sorted(m.conflicts.items(), key=lambda kv: (-len(kv[1]), kv[0].name.lower()))
            t.h(f"Shares files with {len(others)} mod{'s' if len(others) != 1 else ''}")
            t.p("Only one copy of each file is used: the one from the mod loaded last. The Playsets tab shows who "
                "wins with your order.", "faint", "small")
            paths = sorted({x for _, files in others for x in files})
            t.p("")
            t.link(f"Copy the {len(paths)} path{'s' if len(paths) != 1 else ''}", lambda: self._copy(paths))
            for o, files in others:
                t.p(f"With {o.name} ({len(files)})", "bold")
                t.p("\n".join(files[:300]) + (f"\n...and {len(files) - 300} more" if len(files) > 300 else ""),
                    "mono")
        t.p(m.folder or m.modfile, "faint", "small")
        if src:
            t.add(f"   \u00B7   installed from {src}", "faint", "small")
        d.end()

    def _multi_detail(self, mods):
        d = self.dp
        d.begin()
        d.accent(ACCENT)
        size = sum(m.size for m in mods)
        d.heading(f"{len(mods)} mods selected", f"{modscan.human_size(size)} in total")
        ups = [m for m in mods if self.app.updates.get(m.key, {}).get("update")]
        acts = []
        if ups:
            acts.append((f"Update {len(ups)}", lambda: self.update_mods(ups), "download", "primary"))
        acts += [("Add to playset", lambda: self.app.add_to_playset([m.key for m in mods]), "plus", "normal"),
                 ("Remove from playset", lambda: self.app.remove_from_playset([m.key for m in mods]), "minus",
                  "normal"),
                 ("Ignore their conflicts", lambda: self.set_ignored(mods, True), "filter_off", "normal"),
                 (f"Delete {len(mods)} mods", lambda: self.delete_mods(mods), "trash", "danger")]
        d.actions(acts)
        for m in mods[:30]:
            d.text.bullet(m.name)
        if len(mods) > 30:
            d.text.p(f"...and {len(mods) - 30} more", "faint")
        d.end()

    def _copy(self, paths):
        self.clipboard_clear()
        self.clipboard_append("\n".join(paths))
        self.app.toast(f"Copied {len(paths)} file path(s).")

    # ---------------------------------------------------------------- actions
    def _open_selected(self):
        mods = self.selected()
        if mods:
            self.open_mod(mods[0])

    def open_mod(self, mod):
        target = mod.folder if mod.folder and os.path.exists(mod.folder) else os.path.dirname(mod.modfile)
        if os.path.isfile(target):
            target = os.path.dirname(target)
        open_folder(target)

    def delete_mods(self, mods):
        if not mods:
            return
        md = self.app.mod_dir()
        plans = [(m, *modscan.delete_plan(m, md, self.app.mods)) for m in mods]
        listing = []
        for m, paths, notes in plans[:12]:
            listing.append(f"• {m.name}")
            listing += [f"      {p}" for p in paths]
            listing += [f"      ({n})" for n in notes]
        if len(plans) > 12:
            listing.append(f"...and {len(plans) - 12} more mods")
        title = f"\"{mods[0].name}\"" if len(mods) == 1 else f"{len(mods)} mods"
        msg = f"Delete {title}?\n\nThis permanently removes:\n" + "\n".join(listing) + "\n\nThis can't be undone."
        if not messagebox.askyesno(f"Delete - {APP_NAME}", msg, icon="warning", parent=self.app):
            return
        errors = []
        for m, _, _ in plans:
            try:
                modscan.delete_mod(m, md, self.app.mods)
                installer.forget(self.app.registry_file, os.path.splitext(m.key)[0])
            except Exception as e:
                errors.append(f"{m.name}: {e}")
        self.app.forget_in_playsets([m.key for m in mods])
        self.app.log(f"Deleted {len(mods) - len(errors)} mod(s).")
        if errors:
            messagebox.showerror(APP_NAME, "Could not delete everything:\n" + "\n".join(errors), parent=self.app)
        self.app.rescan()

    # ---------------------------------------------------------------- updates
    def check_updates(self):
        if self.checking or not self.app.mods:
            return
        self.checking = True
        self.check_btn.configure(state="disabled", text="Checking...")
        self.app.status_right.configure(text="Checking the Workshop for updates...")
        mods, mod_dir = list(self.app.mods), self.app.mod_dir()
        reg = self.app.registry()

        def work():
            try:
                res = U.check(N.Net(), mods, reg)
                U.save_cache(self.app.updates_file, mod_dir, res)
                self.app.q.put(("updates", mod_dir, res, int(time.time()), ""))
            except Exception as e:
                self.app.q.put(("updates", mod_dir, None, 0, f"{type(e).__name__}: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def show_updates(self, mod_dir, res, checked_at, error):
        self.checking = False
        self.check_btn.configure(state="normal", text="Check updates")
        self.app.status_right.configure(text="")
        if error:
            self.utext.configure(text=f"Update check failed ({error})", text_color=ERR, fg_color=ERR_SOFT)
            return
        if os.path.normcase(mod_dir) != os.path.normcase(self.app.mod_dir()):
            return
        self.app.updates, self.app.checked_at = res or {}, checked_at
        n = sum(1 for v in self.app.updates.values() if v.get("update"))
        self.app.log(f"Update check: {n} of {len(self.app.updates)} Workshop mods have a newer version.")
        self.refresh_view()

    def _update_bar(self):
        n = sum(1 for m in self.app.mods if self.app.updates.get(m.key, {}).get("update"))
        if not self.app.checked_at:
            self.utext.configure(text="Updates not checked yet", text_color=MUTED, fg_color=MUTED_SOFT)
        else:
            ago = max(0, int(time.time()) - self.app.checked_at)
            age = "just now" if ago < 90 else (f"{ago // 60} min ago" if ago < 3600 else
                                               (f"{ago // 3600} h ago" if ago < 172800 else f"{ago // 86400} days ago"))
            self.utext.configure(text=(f"{UPD_ICON}  {n} update{'s' if n != 1 else ''} · checked {age}" if n
                                       else f"Up to date · checked {age}"), text_color=ACCENT if n else MUTED,
                                 fg_color=ACCENT_SOFT if n else MUTED_SOFT)
        self.uall.configure(text=f"Update all ({n})")
        self.uall.grid() if n else self.uall.grid_remove()

    def update_mods(self, mods):
        reg = self.app.registry()
        jobs = {}
        for m in mods:
            wid = self.app.updates.get(m.key, {}).get("id") or U.workshop_id(m, reg)
            if not wid:
                continue
            same = [o for o in self.app.mods if U.workshop_id(o, reg) == wid]
            jobs[wid] = [{"modfile": o.modfile, "folder": o.folder} for o in same]
        if jobs:
            self.app.start_updates(jobs)

    def update_all(self):
        self.update_mods([m for m in self.app.mods if self.app.updates.get(m.key, {}).get("update")])

    def set_busy(self, running):
        self.check_btn.configure(state="disabled" if running or self.checking else "normal")
