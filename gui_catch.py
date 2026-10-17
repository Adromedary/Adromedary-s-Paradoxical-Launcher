"""The Catch tab: links in, download queue out."""
import re

import customtkinter as ctk

import sources as S
from gui_common import (ACCENT, ACCENT_SOFT, BG, BORDER, CARD_HI, MONO, MUTED, MUTED_SOFT, OK, OK_SOFT, TEAL,
                        TEAL_SOFT, TEXT, WARN, WARN_ICON, WARN_SOFT, Tree, button, card, font, icon)

KIND_COLOR = {"Official": OK, "Official mod platform": OK, "Workshop mirror": WARN,
              "Mod hub": ACCENT, "Creator-hosted": TEAL}
KIND_SOFT = {"Official": OK_SOFT, "Official mod platform": OK_SOFT, "Workshop mirror": WARN_SOFT,
             "Mod hub": ACCENT_SOFT, "Creator-hosted": TEAL_SOFT}
STATE_LABEL = {"Queued": "Queued", "Working": "Working", "Done": "Done", "Already": "Have it",
               "Not found": "Not found", "Collection": "Collection", "Stopped": "Stopped",
               "Paused": "Paused", "Interrupted": "Interrupted"}
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
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        # ---- links
        lc = card(top)
        lc.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
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
        button(head, "Paste", self._paste_button, width=70, height=26, icon_name="copy", icon_size=13
               ).grid(row=0, column=3, padx=(0, 4))
        button(head, "Clear", self._clear, width=66, height=26, icon_name="close", icon_size=13).grid(row=0, column=4)
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
        cc = card(top)
        cc.grid(row=0, column=1, sticky="nsew")
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

        # ---- queue
        qhead = ctk.CTkFrame(self, fg_color="transparent")
        qhead.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        qhead.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(qhead, text="Queue", text_color=TEXT, font=font(14, "bold")).grid(row=0, column=0, sticky="w")
        self.queue_note = ctk.CTkLabel(qhead, text="", text_color=MUTED, font=font(11), anchor="w")
        self.queue_note.grid(row=0, column=1, sticky="w", padx=10)
        button(qhead, "Mod folder", app.open_mod_dir, height=26, icon_name="folder", icon_size=13
               ).grid(row=0, column=2, padx=(0, 6))
        self.log_btn = button(qhead, "", self._toggle_log, height=26, width=96, icon_name="log", icon_size=13)
        self.log_btn.grid(row=0, column=3)
        self.queue = Tree(self, [("mod", "Mod", 380, "w", True), ("game", "Game", 150, "w", False),
                                 ("status", "Status", 110, "w", False), ("detail", "Details", 420, "w", True)],
                          show_tree=True, selectmode="browse", main="mod", drop=("game",), min_main=240)
        self.queue.grid(row=2, column=0, sticky="nsew")
        self.empty = ctk.CTkLabel(self.queue, text="Paste Workshop links above and press Start, or catch mods "
                                                   "from the Browse tab.\nUnfinished downloads resume where they "
                                                   "stopped.", text_color=MUTED, font=font(13), justify="center",
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
        self._insert_links(txt)
        return "break"

    def _paste_button(self):
        try:
            self._insert_links(self.clipboard_get(), at="end")
        except Exception:
            pass

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
        self.progress.set(0)
        self.count_lbl.configure(text="0 / 0 mods")
        self.empty.place_forget()

    def add_item(self, it):
        if it.id in self.rows:
            return
        parent = self.rows.get(it.parent, "")
        label = ("▤ " if it.is_collection else "") + it.title
        rid = self.queue.tree.insert(parent, "end", values=(label, it.game, "Queued", f"ID {it.id}"),
                                     tags=("group",) if it.is_collection else ("muted",), open=True)
        self.rows[it.id] = rid
        self.queue_note.configure(text=f"{len([1 for _ in self.rows])} entries")

    def set_status(self, iid, state, text, progress):
        rid = self.rows.get(iid)
        if not rid:
            return
        label = STATE_LABEL.get(state, state)
        if state == "Working" and progress is not None:
            label = f"Working {int(progress * 100)}%"
        vals = list(self.queue.tree.item(rid, "values"))
        vals[2] = label
        if text:
            vals[3] = text
        self.queue.tree.item(rid, values=vals, tags=(STATE_TAG.get(state, "muted"),))

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
