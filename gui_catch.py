"""The Catch tab: links in, download queue out."""
import os
import re
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

import icons
import sources as S
from gui_common import (ACCENT, ACCENT_SOFT, APP_NAME, BG, BORDER, CARD_HI, MONO, MUTED, MUTED_SOFT, OK, OK_SOFT,
                        RIGHT_CLICK, TEAL, TEAL_SOFT, TEXT, WARN, WARN_ICON, WARN_SOFT, button, card, copy_text, font,
                        icon, popup_menu, px, tk_image, Tree)

KIND_COLOR = {"Official": OK, "Official mod platform": OK, "Workshop mirror": WARN,
              "Mod hub": ACCENT, "Creator-hosted": TEAL}
KIND_SOFT = {"Official": OK_SOFT, "Official mod platform": OK_SOFT, "Workshop mirror": WARN_SOFT,
             "Mod hub": ACCENT_SOFT, "Creator-hosted": TEAL_SOFT}
STATE_LABEL = {"Queued": "Queued", "Working": "Working", "Done": "Done", "Already": "Have it",
               "Not found": "Not found", "Collection": "Collection", "Stopped": "Stopped",
               "Paused": "Paused", "Interrupted": "Interrupted"}
RETRY_STATES = ("Not found", "Interrupted", "Stopped")
STATE_TAG = {"Done": "ok", "Already": "ok", "Not found": "missing", "Collection": "group",
             "Stopped": "conflict", "Paused": "conflict", "Interrupted": "conflict", "Working": "update",
             "Queued": "muted"}


def parse_ids(text):
    ids = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = (re.search(r"[?&]id=(\d+)", line) or re.search(r"filedetails/(\d+)", line)
             or re.fullmatch(r"(\d{6,})", line))
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


class CatchPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.rows = {}               # item id -> tree row id
        self.titles = {}             # item id -> title
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.failed = {}             # item id -> title: downloads that didn't work (Retry)
        self.grid_columnconfigure(1, weight=0)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        side = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        side.grid(row=0, column=1, rowspan=4, sticky="ns", padx=(12, 0))
        side.grid_rowconfigure(1, weight=1)
        side.grid_columnconfigure(0, weight=1)
        # ---- links
        lc = card(top)
        lc.grid(row=0, column=0, sticky="nsew")
        lc.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(lc, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Workshop links or IDs", text_color=TEXT, font=font(13, "bold")
                     ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="mods or collections, one per line", text_color=MUTED, font=font(11)
                     ).grid(row=0, column=1, sticky="w", padx=(0, 10))
        self.count_chip = ctk.CTkLabel(head, text="0 links", width=66, height=22, corner_radius=11, fg_color=BG,
                                       text_color=MUTED, font=font(11, "bold"))
        self.count_chip.grid(row=0, column=2, padx=(0, 6))
        button(head, "Paste", self._paste_button, width=70, height=26, icon_name="copy", icon_size=13,
               tip="Paste links: they go straight to the catch list").grid(row=0, column=3, padx=(0, 4))
        button(head, "Add to list", self.to_list, primary=True, width=96, height=26, icon_name="layers", icon_size=13,
               tip="Put the links in the box on the catch list (nothing downloads yet)").grid(row=0, column=4,
                                                                                             padx=(0, 4))
        button(head, "Clear", self._clear, width=66, height=26, icon_name="close", icon_size=13).grid(row=0, column=5)
        self.links = ctk.CTkTextbox(lc, height=84, fg_color=BG, border_width=1, border_color=BORDER, text_color=TEXT,
                                    corner_radius=8, font=ctk.CTkFont(MONO, 12), wrap="none")
        self.links.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.links.bind("<KeyRelease>", lambda e: self._count())
        if app.cfg.get("catch_links"):
            self.links.insert("1.0", app.cfg["catch_links"].strip() + "\n")
        self.links._textbox.bind("<<Paste>>", self._on_paste)       # paste always ends on a fresh line
        self.chain_strip = ctk.CTkFrame(lc, fg_color="transparent", height=24)
        self.chain_strip.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))

        # ---- controls
        cc = card(side)
        cc.grid(row=0, column=0, sticky="new")
        btns = ctk.CTkFrame(cc, fg_color="transparent")
        btns.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.start_btn = button(btns, "Start", app.start_run, primary=True, width=96, height=34, icon_name="download")
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.pause_btn = button(btns, "Pause", app.pause_run, width=88, height=34, state="disabled", icon_name="pause",
                                icon_size=13)
        self.pause_btn.grid(row=0, column=1, padx=(0, 6))
        self.resume_btn = button(btns, "Resume", app.resume_run, width=96, height=34, state="disabled",
                                 icon_name="resume", icon_size=13)
        self.resume_btn.grid(row=0, column=2, padx=(0, 6))
        self.cancel_btn = button(btns, "Cancel", app.cancel_run, danger=True, width=84, height=34, state="disabled",
                                 icon_name="stop", icon_size=12)
        self.cancel_btn.grid(row=0, column=3)
        par = ctk.CTkFrame(cc, fg_color="transparent")
        par.grid(row=1, column=0, sticky="ew", padx=12)
        self.workers_lbl = ctk.CTkLabel(par, text="", text_color=TEXT, font=font(12, "bold"), width=78, anchor="w")
        self.workers_lbl.grid(row=0, column=0)
        self.workers = ctk.CTkSlider(par, from_=1, to=5, number_of_steps=4, width=150, button_color=ACCENT,
                                     button_hover_color=ACCENT, progress_color=ACCENT, command=self._workers_changed)
        self.workers.set(app.cfg["workers"])
        self.workers.grid(row=0, column=1, padx=(4, 0))
        self.workers_warn = ctk.CTkLabel(cc, text="", text_color=WARN, font=font(10), anchor="w", justify="left",
                                         wraplength=330)
        self.workers_warn.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 0))
        prog = ctk.CTkFrame(cc, fg_color="transparent")
        prog.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 12))
        prog.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(prog, height=8, corner_radius=4, fg_color=BORDER, progress_color=OK)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.count_lbl = ctk.CTkLabel(prog, text="0 / 0 mods", text_color=MUTED, font=font(11, "bold"))
        self.count_lbl.grid(row=0, column=1)
        self._workers_changed(app.cfg["workers"])

        # ---- the catch list: mods added in Browse, kept until they're installed or removed
        lst = card(side)
        lst.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        lst.grid_columnconfigure(0, weight=1)
        lst.grid_rowconfigure(2, weight=1)
        lh = ctk.CTkFrame(lst, fg_color="transparent")
        lh.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        lh.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(lh, text="", image=icon("layers", 17, ACCENT), width=20).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(lh, text="Catch list", text_color=TEXT, font=font(14, "bold")).grid(row=0, column=1, sticky="w")
        self.list_count = ctk.CTkLabel(lh, text="", height=22, corner_radius=11, fg_color=MUTED_SOFT,
                                       text_color=MUTED, font=font(11, "bold"), padx=8)
        self.list_count.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(lst, text="Added in Browse, from links or with Catch all. Each mod stays here until it's "
                               "installed or you remove it.",
                     text_color=MUTED, font=font(11), anchor="w", justify="left", wraplength=330
                     ).grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))
        self.clist = Tree(lst, [("title", "Mod", 190, "w", True), ("state", "Status", 92, "w", False),
                                ("dl", "", 34, "center", False), ("rm", "", 34, "center", False)],
                          show_tree=True, image_width=50, selectmode="extended", height=6)
        self.clist.grid(row=2, column=0, sticky="nsew", padx=8)
        ct = self.clist.tree
        ct.heading("dl", text="↓")
        ct.heading("rm", text="✕")
        ct.bind("<ButtonRelease-1>", self._list_click, add="+")
        ct.bind("<Motion>", self._list_hover, add="+")
        ct.bind("<Delete>", lambda e: self.app.remove_from_catch_list(self._list_selected()))
        ct.bind("<Double-1>", lambda e: self._list_open())
        self.list_rows = {}           # row id -> workshop id
        self.list_empty = ctk.CTkLabel(self.clist, text="Nothing waiting.\nPaste Workshop links above, or in\n"
                                                        "Browse pick mods and press \"Add to list\".", text_color=MUTED, font=font(12),
                                       justify="center", image=icon("layers", 34, MUTED), compound="top")
        lf = ctk.CTkFrame(lst, fg_color="transparent")
        lf.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 12))
        lf.grid_columnconfigure((0, 1), weight=1, uniform="lf")
        self.list_all = button(lf, "Download all", lambda: self.app.catch_from_list(), primary=True, height=32,
                               icon_name="download", icon_size=14)
        self.list_all.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.list_clear = button(lf, "Clear all", self._clear_list, height=32, icon_name="trash", icon_size=13,
                                 danger=True)
        self.list_clear.grid(row=0, column=1, sticky="ew")

        # ---- queue
        qhead = ctk.CTkFrame(self, fg_color="transparent")
        qhead.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        qhead.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(qhead, text="Queue", text_color=TEXT, font=font(14, "bold")).grid(row=0, column=0, sticky="w")
        self.queue_note = ctk.CTkLabel(qhead, text="", text_color=MUTED, font=font(11), anchor="w")
        self.queue_note.grid(row=0, column=1, sticky="w", padx=10)
        self.retry_btn = button(qhead, "Retry failed", self.retry_failed, height=26, icon_name="retry", icon_size=13,
                                tip="Try the downloads that didn't work again")
        self.retry_btn.grid(row=0, column=2, padx=(0, 6))
        self.retry_btn.grid_remove()
        button(qhead, "Mod folder", app.open_mod_dir, height=26, icon_name="folder", icon_size=13
               ).grid(row=0, column=3, padx=(0, 6))
        self.log_btn = button(qhead, "", self._toggle_log, height=26, width=96, icon_name="log", icon_size=13)
        self.log_btn.grid(row=0, column=4)
        self.queue = Tree(self, [("mod", "Mod", 300, "w", True), ("game", "Game", 130, "w", False),
                                 ("status", "Status", 110, "w", False), ("detail", "Details", 280, "w", True),
                                 ("act", "", 78, "center", False)],
                          show_tree=True, selectmode="browse", main="mod", drop=("game",), min_main=240,
                          key="catch.queue")
        self.queue.grid(row=2, column=0, sticky="nsew")
        self.empty = ctk.CTkLabel(self.queue, text="Paste Workshop links above: they go to the catch list. Press "
                                                   "Start (or Download all) to download it.\nUnfinished downloads "
                                                   "resume where they stopped.", text_color=MUTED, font=font(13), justify="center",
                                  image=icon("download", 42, MUTED), compound="top")
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.log_box = ctk.CTkTextbox(self, height=150, fg_color=BG, border_width=1, border_color=BORDER,
                                      text_color=MUTED, corner_radius=8, font=ctk.CTkFont(MONO, 11),
                                      state="disabled", wrap="word")
        self.log_box.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        if not app.cfg.get("show_log", True):
            self.log_box.grid_remove()
        self._log_label()
        self.draw_chain_strip()
        qt = self.queue.tree
        qt.bind("<ButtonRelease-1>", self._queue_click, add="+")
        qt.bind("<Motion>", self._queue_hover, add="+")
        for ev in RIGHT_CLICK:
            qt.bind(ev, self._queue_context, add="+")
            self.clist.tree.bind(ev, self._list_context, add="+")
        self.render_list()

    # ---------------------------------------------------------------- links box
    def ids(self):
        return parse_ids(self.links.get("1.0", "end"))

    def _count(self):
        n = len(self.ids())
        self.count_chip.configure(text=f"{n} link{'s' if n != 1 else ''}", text_color=OK if n else MUTED)

    def _insert_links(self, txt, at="insert"):
        """Insert pasted text on its own line(s) and leave the cursor on a fresh empty line."""
        txt = txt.strip().replace("\r\n", "\n").replace("\r", "\n")
        if not txt:
            return
        tb = self.links._textbox
        try:
            tb.delete("sel.first", "sel.last")
        except Exception:
            pass
        if at == "end":
            tb.mark_set("insert", "end-1c")
        if tb.get("insert linestart", "insert").strip():
            txt = "\n" + txt
        rest = tb.get("insert", "insert lineend")
        tb.insert("insert", txt + "\n")
        if rest.strip():
            tb.mark_set("insert", "insert lineend")
            tb.insert("insert", "\n")
        tb.see("insert")
        self._count()

    def _on_paste(self, event=None):
        try:
            txt = self.clipboard_get()
        except Exception:
            return "break"
        ids = parse_ids(txt)
        if ids:                                       # links go to the catch list; nothing downloads yet
            self.app.add_links_to_list(ids)
        else:
            self._insert_links(txt)
        return "break"

    def _paste_button(self):
        try:
            txt = self.clipboard_get()
        except Exception:
            return
        ids = parse_ids(txt)
        if ids:
            self.app.add_links_to_list(ids)
        else:
            self._insert_links(txt, at="end")

    def to_list(self):
        """The links typed in the box move to the catch list."""
        ids = self.ids()
        if not ids:
            self.app.toast("No Workshop links or IDs in the box.")
            return
        self.app.add_links_to_list(ids)
        self.remove_ids(ids)

    def _clear(self):
        self.links.delete("1.0", "end")
        self._count()

    def links_text(self):
        return self.links.get("1.0", "end").strip()

    def add_links(self, ids):
        have = set(self.ids())
        new = [i for i in ids if i not in have]
        if new:
            cur = self.links_text()
            self.links.insert("end", ("\n" if cur else "") + "\n".join(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={i}" for i in new) + "\n")
            self._count()

    def remove_ids(self, ids):
        """Links that finished (installed or already there) leave the box; the rest stay for another try."""
        ids = set(ids)
        keep = []
        for line in self.links.get("1.0", "end").splitlines():
            got = parse_ids(line)
            if got and got[0] in ids:
                continue
            if line.strip():
                keep.append(line.strip())
        self.links.delete("1.0", "end")
        if keep:
            self.links.insert("1.0", "\n".join(keep) + "\n")
        self._count()

    # ---------------------------------------------------------------- chain + workers
    def draw_chain_strip(self):
        for w in self.chain_strip.winfo_children():
            w.destroy()
        cfg = self.app.cfg
        en = self.app.effective_enabled()
        ctk.CTkLabel(self.chain_strip, text="Chain", text_color=MUTED, font=font(11)).pack(side="left", padx=(0, 6))
        chain = [k for k in cfg["order"] if en.get(k)]
        for n, k in enumerate(chain):
            src = S.SOURCE_BY_KEY[k]
            missing = src.needs and not cfg.get(src.needs)
            ctk.CTkLabel(self.chain_strip, text=src.short + (" (no key)" if missing else ""), height=22,
                         corner_radius=11, fg_color=MUTED_SOFT if missing else KIND_SOFT.get(src.kind, CARD_HI),
                         text_color=MUTED if missing else KIND_COLOR.get(src.kind, TEXT), font=font(11, "bold"),
                         padx=8).pack(side="left")
            if n < len(chain) - 1:
                ctk.CTkLabel(self.chain_strip, text="›", text_color=MUTED, font=font(12)).pack(side="left", padx=3)
        game = self.app.game()
        if cfg["enabled"].get("steam") and not en.get("steam") and game:
            ctk.CTkLabel(self.chain_strip, text="(Steam: not owned)", text_color=MUTED,
                         font=font(10)).pack(side="left", padx=(8, 0))

    def _workers_changed(self, v):
        n = int(round(float(v)))
        self.workers_lbl.configure(text=f"{n} at a time")
        if n != self.app.cfg.get("workers"):
            self.app.cfg["workers"] = n
            self.app.save()
        self.update_workers_warn()

    def update_workers_warn(self):
        n = self.app.cfg.get("workers", 1)
        if n > 1 and self.app.cfg["enabled"].get("skymods"):
            self.workers_warn.configure(text=f"{WARN_ICON} Above 1, SkyMods asks for human checks more often. "
                                             "Its links are still made one at a time.")
            self.workers_warn.grid()
        else:
            self.workers_warn.grid_remove()

    # ---------------------------------------------------------------- run state
    def set_running(self, running, can_resume=False):
        self.start_btn.configure(state="disabled" if running else "normal", text="Working..." if running else "Start")
        self.pause_btn.configure(state="normal" if running else "disabled")
        self.resume_btn.configure(state="normal" if (can_resume and not running) else "disabled")
        self.cancel_btn.configure(state="normal" if (running or can_resume) else "disabled",
                                  text="Cancel" if running else "Discard")
        self.empty.place_forget() if (running or self.rows) else None
        self.workers.configure(state="disabled" if running else "normal")

    def clear_queue(self):
        self.queue.tree.delete(*self.queue.tree.get_children())
        self.rows.clear()
        self.failed.clear()
        self._retry_button()
        self.progress.set(0)
        self.count_lbl.configure(text="0 / 0 mods")
        self.empty.place_forget()

    def add_item(self, it):
        if it.id in self.rows:
            return
        parent = self.rows.get(it.parent, "")
        label = ("▤ " if it.is_collection else "") + it.title
        rid = self.queue.tree.insert(parent, "end", values=(label, it.game, "Queued", f"ID {it.id}", ""),
                                     tags=("group",) if it.is_collection else ("muted",), open=True)
        self.rows[it.id] = rid
        self.titles[it.id] = it.title
        n = len(self.rows)
        self.queue_note.configure(text=f"{n} entr{'ies' if n != 1 else 'y'}")

    def set_status(self, iid, state, text, progress):
        rid = self.rows.get(iid)
        if not rid:
            return
        label = STATE_LABEL.get(state, state)
        if state == "Working" and progress is not None:
            label = f"Working {int(progress * 100)}%"
        vals = list(self.queue.tree.item(rid, "values"))
        while len(vals) < 5:
            vals.append("")
        vals[2] = label
        if text:
            vals[3] = text
        failed = state in RETRY_STATES
        vals[4] = "↻ Retry" if failed else ""
        if failed:
            self.failed[iid] = self.titles.get(iid, iid)
        else:
            self.failed.pop(iid, None)
        self.queue.tree.item(rid, values=vals, tags=(STATE_TAG.get(state, "muted"),))
        self._retry_button()

    def set_progress(self, done, total):
        self.progress.set(done / total if total else 0)
        self.count_lbl.configure(text=f"{done} / {total} mods")

    # ---------------------------------------------------------------- log
    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _toggle_log(self):
        show = not self.log_box.winfo_ismapped()
        self.log_box.grid() if show else self.log_box.grid_remove()
        self.app.cfg["show_log"] = show
        self.app.save()
        self._log_label()

    def _log_label(self):
        self.log_btn.configure(text="Hide log" if self.app.cfg.get("show_log", True) else "Show log")

    # ---------------------------------------------------------------- retrying what failed
    def _retry_button(self):
        n = len(self.failed)
        if n and not self.app.running():
            self.retry_btn.configure(text=f"Retry failed ({n})")
            self.retry_btn.grid()
        else:
            self.retry_btn.grid_remove()

    def retry_failed(self):
        if self.failed:
            self.app.retry_ids(list(self.failed))

    def _queue_cell(self, e):
        t = self.queue.tree
        if t.identify_region(e.x, e.y) != "cell":
            return None, None
        rid, col = t.identify_row(e.y), t.identify_column(e.x)
        try:
            cid = t.column(col, "id")
        except Exception:
            return None, None
        return rid, cid

    def _queue_click(self, e):
        rid, cid = self._queue_cell(e)
        if cid != "act" or not rid:
            return
        iid = next((i for i, r in self.rows.items() if r == rid), None)
        if iid in self.failed and not self.app.running():
            self.app.retry_ids([iid])

    def _queue_hover(self, e):
        rid, cid = self._queue_cell(e)
        iid = next((i for i, r in self.rows.items() if r == rid), None) if cid == "act" else None
        want = "hand2" if iid in self.failed else ""
        if str(self.queue.tree.cget("cursor")) != want:
            self.queue.tree.configure(cursor=want)

    # ---------------------------------------------------------------- the catch list
    def render_list(self):
        """Rows for every mod in the catch list, with what's happening to it right now."""
        t = self.clist.tree
        sel = {self.list_rows.get(r) for r in t.selection()}
        t.delete(*t.get_children())
        self.list_rows.clear()
        items = list(self.app.catch_list.items())
        for i, (wid, title) in enumerate(items):
            st, tag = self.app.list_state(wid)
            img = self._list_img(wid)
            rid = t.insert("", "end", image=img, values=(title, st, "↓", "✕"),
                           tags=tuple(x for x in (tag, "odd" if i % 2 else "") if x))
            self.list_rows[rid] = wid
            if wid in sel:
                t.selection_add(rid)
        n = len(items)
        self.list_count.configure(text=f"{n} mod{'s' if n != 1 else ''}" if n else "empty",
                                  text_color=ACCENT if n else MUTED, fg_color=ACCENT_SOFT if n else MUTED_SOFT)
        busy = n and all(self.app.list_state(w)[0].startswith("↓") for w in self.app.catch_list)
        self.list_all.configure(state="normal" if n and not busy else "disabled")
        self.list_clear.configure(state="normal" if n else "disabled")
        if n:
            self.list_empty.place_forget()
        else:
            self.list_empty.place(relx=0.5, rely=0.5, anchor="center")

    def refresh_list(self):
        """Only the Status column (cheap: runs while downloads report progress)."""
        t = self.clist.tree
        for rid, wid in self.list_rows.items():
            st, tag = self.app.list_state(wid)
            if t.set(rid, "state") != st:
                t.set(rid, "state", st)
                tags = [x for x in t.item(rid, "tags") if x == "odd"]
                if tag:
                    tags.insert(0, tag)
                t.item(rid, tags=tags)
        busy = self.list_rows and all(self.app.list_state(w)[0].startswith("↓") for w in self.list_rows.values())
        self.list_all.configure(state="disabled" if busy or not self.list_rows else "normal")

    def _list_img(self, wid):
        try:
            p = os.path.join(self.app.thumbs_dir, wid + ".jpg")
            if not icons.available() or not os.path.isfile(p):
                return ""
            im = icons.load_thumb(p, px(22))
            return tk_image(self.clist.tree, ("cl", wid, px(22)), icons.rounded(im, px(4))) if im is not None else ""
        except Exception:
            return ""

    def _list_selected(self):
        return [self.list_rows[r] for r in self.clist.tree.selection() if r in self.list_rows]

    def _list_cell(self, e):
        t = self.clist.tree
        if t.identify_region(e.x, e.y) != "cell":
            return None, None
        try:
            return self.list_rows.get(t.identify_row(e.y)), t.column(t.identify_column(e.x), "id")
        except Exception:
            return None, None

    def _list_click(self, e):
        wid, cid = self._list_cell(e)
        if not wid:
            return
        if cid == "dl":
            self.app.catch_from_list([wid])
        elif cid == "rm":
            self.app.remove_from_catch_list([wid])

    def _list_hover(self, e):
        wid, cid = self._list_cell(e)
        want = "hand2" if wid and cid in ("dl", "rm") else ""
        if str(self.clist.tree.cget("cursor")) != want:
            self.clist.tree.configure(cursor=want)

    def _list_open(self):
        sel = self._list_selected()
        if sel:
            webbrowser.open(f"https://steamcommunity.com/sharedfiles/filedetails/?id={sel[0]}")

    def _clear_list(self):
        n = len(self.app.catch_list)
        if n and messagebox.askyesno(APP_NAME, f"Remove all {n} mod{'s' if n != 1 else ''} from the catch list?",
                                     parent=self.app):
            self.app.remove_from_catch_list(list(self.app.catch_list))

    # ---------------------------------------------------------------- right-click
    def _queue_context(self, e):
        t = self.queue.tree
        rid = t.identify_row(e.y)
        iid = next((i for i, r in self.rows.items() if r == rid), None)
        if not iid:
            return
        t.selection_set(rid)
        url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={iid}"
        title = self.titles.get(iid, iid)
        popup_menu(t, e, [
            ("Retry", "retry", lambda: self.app.retry_ids([iid]), iid in self.failed and not self.app.running()),
            ("Retry every failed one", "retry", self.retry_failed, len(self.failed) > 1 and not self.app.running()),
            None,
            ("Steam page", "external", lambda: webbrowser.open(url)),
            ("Copy", "copy", [("Link", None, lambda: self._copy(url)), ("Title", None, lambda: self._copy(title)),
                              ("Details", None, lambda: self._copy(" | ".join(str(v) for v in t.item(rid, "values")
                                                                              if v)))])])

    def _list_context(self, e):
        t = self.clist.tree
        rid = t.identify_row(e.y)
        if rid not in self.list_rows:
            return
        if rid not in t.selection():
            t.selection_set(rid)
        ids = self._list_selected()
        one = ids[0]
        url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={one}"
        many = len(ids) > 1
        popup_menu(t, e, [
            (f"Download {len(ids)} now" if many else "Download now", "download", lambda: self.app.catch_from_list(ids)),
            (f"Remove {len(ids)} from the list" if many else "Remove from the list", "minus",
             lambda: self.app.remove_from_catch_list(ids)),
            None,
            ("Steam page", "external", lambda: webbrowser.open(url), not many),
            ("Copy the link" + ("s" if many else ""), "copy", lambda: self._copy("\n".join(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={i}" for i in ids)))])

    def _copy(self, text):
        copy_text(self, text)
        self.app.toast("Copied.", color=MUTED)
