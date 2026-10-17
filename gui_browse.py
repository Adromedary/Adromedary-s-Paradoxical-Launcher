"""The Browse tab: the game's Steam Workshop inside the app, with what you already have marked."""
import os
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk

import cards
import icons
import launcher as LA
import modscan
import updates as U
import workshop as W
from gui_common import (ACCENT, ACCENT_SOFT, BORDER, CARD, CARD_HI, ERR, ERR_SOFT, INFO, INFO_SOFT, MUTED, MUTED_SOFT,
                        OK, OK_SOFT, TAB_ON, TAB_ON_HI, TEXT, DetailPane, style_button, Split, Tooltip, Tree, button,
                        ctk_image, font, icon, page_frame, pick, px, tk_image, units, DETAIL_WIDTH)

INCLUDE, EXCLUDE = ("#d6e3fd", "#24406f"), ("#fde3e5", "#4a2228")
CARD_MIN, CARD_MAX, GAP = 196, 250, 12          # panel view: square cards, design units
STATUS_COLOR = {"ok": (OK, OK_SOFT), "update": (ACCENT, ACCENT_SOFT), "list": (ACCENT, ACCENT_SOFT),
                "dl": (ACCENT, ACCENT_SOFT), "missing": (ERR, ERR_SOFT), "": (MUTED, MUTED_SOFT)}
TREE_TAG = {"ok": "ok", "update": "update", "dl": "update", "list": "update", "missing": "missing"}


class BrowsePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.page = None
        self.page_no = 1
        self.token = 0
        self.by_row = {}
        self.items = {}                  # id -> WsItem (everything seen this session)
        self.tag_state = {}              # tag -> "in" / "out"
        self.tag_groups = {}             # appid -> [(group, tags)]
        self.chips = {}
        self.cache = {}                  # query -> Page (this session)
        self.details = {}                # id -> workshop.Details
        self.loading = False
        self.dirty = False
        self.started = False
        self.view = app.cfg.get("ws_view", "List")
        self.sel_ids = []                # selection in the panel view
        self.cards = {}                  # id -> {"label", "it", "img"}
        self._side = 0
        self._cols = 0
        self._card_token = 0
        self._layout_job = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ---- row 1: search + view
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(bar, placeholder_text="Search the Workshop: a mod's name, its author, or words "
                                                         "from its description", height=36, fg_color=CARD,
                                   border_color=BORDER, text_color=TEXT, font=font(13), corner_radius=9)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<Return>", lambda e: self.run(1))
        button(bar, "Search", lambda: self.run(1), primary=True, height=36, width=104, icon_name="search"
               ).grid(row=0, column=1, padx=(0, 12))
        vt = ctk.CTkFrame(bar, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER)
        vt.grid(row=0, column=2)
        self.view_btns = {}
        for i, (name, ic, tip) in enumerate((("List", "list", "A compact list with every detail in columns"),
                                             ("Panels", "grid", "Big pictures in a grid"))):
            b = ctk.CTkButton(vt, text=name, image=icon(ic, 15), compound="left", height=28, width=88, corner_radius=8,
                              font=font(12), text_color=TEXT, fg_color="transparent", hover_color=CARD_HI,
                              command=lambda n=name: self.set_view(n))
            b.grid(row=0, column=i, padx=3, pady=3)
            Tooltip(b, tip)
            self.view_btns[name] = b

        # ---- row 2: sort and filters
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        f.grid_columnconfigure(5, weight=1)
        self.sort = ctk.CTkOptionMenu(f, values=[s[0] for s in W.SORTS], width=188, height=32, fg_color=CARD,
                                      button_color=CARD, button_hover_color=CARD_HI, text_color=TEXT, font=font(12),
                                      dropdown_font=font(12), dynamic_resizing=False, command=lambda v: self.run(1),
                                      corner_radius=9)
        self.sort.set(app.cfg.get("ws_sort", W.SORTS[0][0]))
        self.sort.grid(row=0, column=0, padx=(0, 8))
        self.kind = ctk.CTkSegmentedButton(f, values=["Mods", "Collections"], command=lambda v: self._kind_changed(),
                                           fg_color=BORDER, selected_color=TAB_ON, selected_hover_color=TAB_ON_HI,
                                           unselected_color=CARD, unselected_hover_color=CARD_HI, text_color=TEXT,
                                           font=font(12), height=32, corner_radius=9)
        self.kind.set("Mods")
        self.kind.grid(row=0, column=1, padx=(0, 8))
        self.version = ctk.CTkOptionMenu(f, values=["Any game version"], width=196, height=32, fg_color=CARD,
                                         button_color=CARD, button_hover_color=CARD_HI, text_color=TEXT,
                                         font=font(12), dropdown_font=font(12), dynamic_resizing=False,
                                         command=lambda v: self.run(1), corner_radius=9)
        self.version.set("Any game version")
        self.version.grid(row=0, column=2, padx=(0, 12))
        self.hide_have = ctk.BooleanVar(value=app.cfg.get("ws_hide_installed", False))
        ctk.CTkSwitch(f, text="Hide mods I have", variable=self.hide_have, command=self._hide_changed,
                      text_color=TEXT, font=font(12), progress_color=ACCENT).grid(row=0, column=3, sticky="w")
        hint = ctk.CTkLabel(f, text="", image=icon("info", 16, MUTED), width=20)
        hint.grid(row=0, column=4, padx=(10, 0))
        Tooltip(hint, "Categories: click one to show only mods that have it (✓). Click again to hide mods that "
                      "have it (✗). A third click turns it off.")
        button(f, "Clear filters", self.clear_filters, height=32, icon_name="filter_off", icon_size=13
               ).grid(row=0, column=6)

        # ---- row 3: category chips (they wrap to the width)
        self.chip_box = ctk.CTkFrame(self, fg_color="transparent", height=28)
        self.chip_box.grid(row=2, column=0, sticky="ew", pady=(10, 8))
        self.chip_box.bind("<Configure>", lambda e: self._flow())

        # ---- row 4: results | details (the divider can be dragged)
        split = Split(self, app, "browse")
        split.grid(row=3, column=0, sticky="nsew")
        left = page_frame(split)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        cols = [("title", "Mod", 260, "w", True), ("author", "Author", 120, "w", False),
                ("updated", "Updated", 112, "w", False), ("subs", "Subscribers", 100, "e", False),
                ("rating", "Rating", 86, "w", False), ("version", "Game", 66, "w", False),
                ("status", "You", 110, "w", False)]
        self.table = Tree(left, cols, show_tree=True, big=True, image_width=56, main="title",
                          drop=("subs", "updated", "author", "rating"), min_main=220)
        self.table.grid(row=0, column=0, sticky="nsew")
        t = self.table.tree
        t.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        t.bind("<Double-1>", lambda e: self.catch_selected())
        self.panel = ctk.CTkScrollableFrame(left, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER)
        self.panel.grid(row=0, column=0, sticky="nsew")
        self.panel.bind("<Configure>", lambda e: self._schedule_layout(), add="+")
        self.msg = ctk.CTkLabel(left, text="", text_color=MUTED, font=font(13), wraplength=480, fg_color=CARD,
                                image=None, compound="top")
        self.dp = DetailPane(split)
        self.dp.on_resize = self.show_detail
        split.add_pane(left, minsize=420, stretch="always")
        split.add_pane(self.dp, size=DETAIL_WIDTH, minsize=300, stretch="never", name="detail")

        # ---- row 5: paging + catch list
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        foot.grid_columnconfigure(3, weight=1)
        self.prev_btn = button(foot, "Previous", lambda: self.run(self.page_no - 1), width=104, height=32,
                               icon_name="left", icon_size=13)
        self.prev_btn.grid(row=0, column=0)
        self.page_lbl = ctk.CTkLabel(foot, text="", text_color=TEXT, font=font(12, "bold"))
        self.page_lbl.grid(row=0, column=1, padx=12)
        self.next_btn = button(foot, "Next", lambda: self.run(self.page_no + 1), width=88, height=32,
                               icon_name="right", icon_size=13)
        self.next_btn.grid(row=0, column=2)
        self.list_box = ctk.CTkFrame(foot, fg_color=CARD, corner_radius=11, border_width=1, border_color=BORDER)
        self.list_box.grid(row=0, column=4, sticky="e")
        ctk.CTkLabel(self.list_box, text="", image=icon("layers", 16, MUTED), width=20).pack(side="left", padx=(12, 0))
        self.list_lbl = ctk.CTkLabel(self.list_box, text="", text_color=TEXT, font=font(12, "bold"))
        self.list_lbl.pack(side="left", padx=(6, 10), pady=6)
        button(self.list_box, "Clear", self.clear_list, height=28, width=60).pack(side="left", padx=(0, 4))
        self.list_btn = button(self.list_box, "Catch them", self.catch_list, primary=True, height=28,
                               icon_name="download", icon_size=14)
        self.list_btn.pack(side="left", padx=(0, 8), pady=6)
        self._render_list()
        self._paging()
        self.set_view(self.view, save=False)
        self.show_detail()

    # ================================================================ state
    def appid(self):
        return LA.game_info(self.app.game()).get("appid", "")

    def on_show(self):
        self.first_visit()
        if self.dirty:
            self.render()
        else:
            self.refresh_status()

    def first_visit(self):
        if not self.started:
            self.started = True
            self.run(1, new_tags=True)

    def game_changed(self):
        self.cache.clear()
        self.tag_state.clear()
        self.started = False
        self.page = None
        if self.app.visible("Browse"):
            self.first_visit()

    def installed_changed(self):
        """The mod folder was scanned again: mark what's installed now."""
        if self.app.visible("Browse"):
            self.render()
        else:
            self.dirty = True

    def version_changed(self):
        if self.tag_groups.get(self.appid()):
            self._build_chips(self._chip_kind or False)
        self.installed_changed()

    def search_for(self, text):
        self.search.delete(0, "end")
        self.search.insert(0, text)
        self.run(1)

    def filter_by(self, tag):
        """A category clicked in the details: show only mods that have it."""
        self.tag_state[tag] = "in"
        for tg in self.chips:
            self._chip_look(tg)
        self._flow()
        self.run(1)

    def query(self, page):
        label, sort, days = W.SORT_BY_LABEL.get(self.sort.get(), W.SORTS[0])
        tags = [t for t, s in self.tag_state.items() if s == "in"]
        ver = self.version.get()
        if ver != "Any game version" and self.kind.get() != "Collections":   # collections carry no version
            tag = self._version_tag(ver)
            if tag:
                tags.append(tag)
        out = [t for t, s in self.tag_state.items() if s == "out"]
        return (self.appid(), sort, days, self.search.get().strip(), tuple(tags), tuple(out), page,
                self.kind.get() == "Collections")

    def _kind_changed(self):
        coll = self.kind.get() == "Collections"
        self.version.configure(state="disabled" if coll else "normal")
        self.run(1, new_tags=True)

    def _version_tag(self, label):
        groups = self.tag_groups.get(self.appid(), [])
        vtags = [t for g, ts in groups for t in ts if W.VERSION_RX.match(t)]
        if label.startswith("Fits my version"):
            gv = self.app.game_version()
            m = W.VERSION_RX.match(gv or "")
            if not m:
                return ""
            want = f"{m.group(1)}.{m.group(2)}"
            return next((t for t in vtags if t.startswith(want + " ") or t == want), "")
        return label if label in vtags else ""

    def set_view(self, name, save=True):
        sel = [it.id for it in self.selected()] if save else []
        self.view = name
        for n, b in self.view_btns.items():
            b.configure(fg_color=TAB_ON if n == name else "transparent")
        (self.table if name == "List" else self.panel._parent_frame).tkraise()
        self.msg.lift()
        if save:
            self.app.cfg["ws_view"] = name
            self.app.save()
            self.render()
            self._select_ids(sel)

    # ================================================================ loading
    def run(self, page, new_tags=False):
        appid = self.appid()
        if not appid:
            self.page = None
            self.render()
            self._message("Pick a Paradox game at the top to browse its Workshop.", "browse")
            return
        if page < 1 or (self.page and self.page.pages and page > self.page.pages and not new_tags):
            return
        self.app.cfg["ws_sort"] = self.sort.get()
        q = self.query(page)
        self.page_no = page
        self.token += 1
        token = self.token
        if q in self.cache:
            self._show(token, q, self.cache[q])
            return
        self.loading = True
        self._message("Loading the Workshop...", "browse")
        self.page_lbl.configure(text="Loading...")

        def work():
            import net as N
            p = W.browse(N.Net(), *q)
            self.app.q.put(("ws_page", token, q, p))
        threading.Thread(target=work, daemon=True).start()

    def page_loaded(self, token, q, p):
        if token != self.token:
            return
        self.loading = False
        if not p.error:
            self.cache[q] = p
        self._show(token, q, p)

    def _show(self, token, q, p):
        self.page = p
        if p.tag_groups and (self.appid() not in self.tag_groups or not self.chips or q[-1] != self._chip_kind):
            self.tag_groups[self.appid()] = p.tag_groups
            self._build_chips(q[-1])
        for it in p.items:
            self.items[it.id] = it
        self.sel_ids = []
        self.render()
        self._paging()
        self._scroll_top()
        if p.error:
            self._message(f"Couldn't load the Workshop: {p.error}.", "alert")
        self._fetch_thumbs(p.items)

    _chip_kind = None

    def _fetch_thumbs(self, items):
        folder = self.app.thumbs_dir
        want = [(it.id, it.preview) for it in items if it.preview and not
                os.path.isfile(os.path.join(folder, it.id + ".jpg"))]
        if not want or not icons.available():
            return

        def one(net, wid, url):
            if icons.fetch_previews(net, {wid: url}, folder):
                self.app.q.put(("ws_thumb", wid))

        def work():
            import net as N
            nets = [N.Net() for _ in range(4)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                for i, (wid, url) in enumerate(want):
                    pool.submit(one, nets[i % 4], wid, url)
        threading.Thread(target=work, daemon=True).start()

    def thumb_ready(self, wid):
        for rid, it in self.by_row.items():
            if it.id == wid:
                img = self._row_img(it)
                if img:
                    self.table.tree.item(rid, image=img)
        if wid in self.cards:
            self._redraw_card(wid)
        sel = self.selected()
        if sel and sel[0].id == wid:
            self.show_detail()

    # ================================================================ drawing
    def _message(self, text, icon_name=None):
        if text:
            self.msg.configure(text=text, image=icon(icon_name, 40, MUTED) if icon_name else None)
            self.msg.place(relx=0.5, rely=0.42, anchor="center")
            self.msg.lift()
        else:
            self.msg.place_forget()

    def _scroll_top(self):
        try:
            self.panel._parent_canvas.yview_moveto(0)
            kids = self.table.tree.get_children()
            if kids:
                self.table.tree.see(kids[0])
        except Exception:
            pass

    def _paging(self):
        p = self.page
        if not p or p.error:
            self.page_lbl.configure(text="")
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            return
        self.page_lbl.configure(text=f"Page {self.page_no} of {max(1, p.pages):,}  ·  {p.total:,} found")
        self.prev_btn.configure(state="normal" if self.page_no > 1 else "disabled")
        self.next_btn.configure(state="normal" if self.page_no < p.pages else "disabled")

    def have(self):
        return self.app.installed_wids()

    def status(self, it):
        """(text, kind) for what you have of this item: installed, update, downloading, in the list..."""
        st = self.app.dl_state.get(it.id)
        if st and st[0] in ("Queued", "Working"):
            pr = st[1]
            return (f"↓ {int(pr * 100)}%" if st[0] == "Working" and pr is not None else
                    "↓ Downloading" if st[0] == "Working" else "↓ Queued"), "dl"
        if it.id in self.app.up_next:
            return "↓ Up next", "dl"
        m = self.have().get(it.id)
        if m is not None:
            reg = self.app.registry().get(it.id, {})
            mine = reg.get("steam_updated") or 0
            if not mine:
                mine = int(m.installed_at or 0)
            if it.updated and mine and it.updated > mine + U.SLACK:
                return "↻ Update", "update"
            return "✓ Installed", "ok"
        if st and st[0] == "Not found":
            return "✗ Not found", "missing"
        if it.id in self.app.catch_list:
            return "+ In list", "list"
        return "", ""

    def _row_img(self, it):
        if not icons.available():
            return ""
        p = os.path.join(self.app.thumbs_dir, it.id + ".jpg")
        if not os.path.isfile(p):
            return ""
        s = px(32)
        im = icons.load_thumb(p, s)
        return tk_image(self.table.tree, ("ws", it.id, s), icons.rounded(im, px(6))) if im is not None else ""

    def shown_items(self):
        p = self.page
        if not p:
            return []
        if self.hide_have.get():
            return [it for it in p.items if self.status(it)[1] != "ok"]
        return list(p.items)

    def render(self):
        self.dirty = False
        items = self.shown_items()
        if self.view == "List":
            self._render_list_view(items)
        else:
            self._render_panel(items)
        p = self.page
        if not p:
            self._message("")
        elif p.error:
            pass
        elif not p.items:
            self._message("Nothing found. Try fewer filters or other words.", "search")
        elif not items:
            self._message("Everything on this page is already installed (\"Hide mods I have\" is on).", "check")
        else:
            self._message("")
        self.show_detail()

    def _render_list_view(self, items):
        t = self.table.tree
        sel = {self.by_row[r].id for r in t.selection() if r in self.by_row}
        t.delete(*t.get_children())
        self.by_row.clear()
        gv = self.app.game_version()
        for i, it in enumerate(items):
            st, kind = self.status(it)
            ver = W.version_label(it, gv)
            tag = TREE_TAG.get(kind, "")
            if not tag and ver.startswith("○"):
                tag = "version"
            title = ("▤ " if it.is_collection else "") + it.title
            if it.is_collection:
                title += f"  ({it.children} items)"
            rating = W.stars(it.stars) if it.stars > 0 else ("few votes" if it.votes else "not rated")
            tags = tuple(x for x in (tag, "odd" if i % 2 else "") if x)
            rid = t.insert("", "end", image=self._row_img(it),
                           values=(title, it.author, W.ago(it.updated), W.human_count(it.subs) if it.subs else "—",
                                   rating, ver, st), tags=tags)
            self.by_row[rid] = it
            if it.id in sel:
                t.selection_add(rid)

    # ---- panel view: square cards, drawn as one picture each
    def _card_side(self):
        width = units(self.panel.winfo_width())
        if width < 100:
            width = 900
        avail = width - GAP
        cols = max(1, int(avail // (CARD_MIN + GAP)))
        side = int(min(CARD_MAX, (avail - GAP * cols) / cols))
        return cols, max(CARD_MIN - 20, side)

    def _card_args(self, it):
        gv = self.app.game_version()
        ver = W.version_label(it, gv)
        vkind = "fit" if ver.startswith("✓") else "old"
        st, kind = self.status(it)
        meta = (f"by {it.author}  ·  " if it.author else "") + W.ago(it.updated)
        return dict(version_text=ver, version_kind=vkind, status_text=st, status_kind=kind,
                    stars=it.stars if it.stars > 0 else 0, votes=it.votes,
                    subs=W.human_count(it.subs) if it.subs else "", meta=meta)

    def _card_picture(self, it):
        p = os.path.join(self.app.thumbs_dir, it.id + ".jpg")
        return p if os.path.isfile(p) else ""

    def _placeholder(self, side):
        key = ("ph", side, pick(CARD_HI))
        img = self._ph.get(key) if hasattr(self, "_ph") else None
        if img is None:
            from PIL import Image, ImageDraw
            n = px(side)
            im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            col = pick(CARD_HI).lstrip("#")
            rgb = tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))
            ImageDraw.Draw(im).rounded_rectangle((0, 0, n - 1, n - 1), radius=max(10, n // 14), fill=rgb + (255,))
            self._ph = getattr(self, "_ph", {})
            img = self._ph[key] = ctk_image(im, (side, side))
        return img

    def _render_panel(self, items):
        for c in self.cards.values():
            c["label"].destroy()
        self.cards = {}
        cols, side = self._card_side()
        self._cols, self._side = cols, side
        ph = self._placeholder(side) if cards.available() else None
        for i, it in enumerate(items):
            lbl = ctk.CTkLabel(self.panel, text="", image=ph, width=side, height=side, cursor="hand2")
            lbl.bind("<Button-1>", lambda e, x=it: self._card_click(x, e))
            lbl.bind("<Double-1>", lambda e, x=it: self.app.catch_ids([x.id]))
            self.cards[it.id] = {"label": lbl, "it": it, "img": None, "st": self.status(it)[0]}
        self._grid_cards()
        self._draw_cards_async([it.id for it in items])

    def _grid_cards(self):
        cols = self._cols
        for i in range(12):
            self.panel.grid_columnconfigure(i, weight=1 if i < cols else 0, uniform="cards" if i < cols else "")
        for i, c in enumerate(self.cards.values()):
            c["label"].grid(row=i // cols, column=i % cols, padx=GAP // 2, pady=GAP // 2)

    def _draw_cards_async(self, ids):
        """Draw the cards' pictures in the background; each one appears as soon as it's ready."""
        if not cards.available() or not ids:
            return
        self._card_token += 1
        token, side = self._card_token, self._side
        n = px(side)
        ring = tuple(int(pick(ACCENT).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        jobs = [(wid, self.cards[wid]["it"], self._card_picture(self.cards[wid]["it"]),
                 self._card_args(self.cards[wid]["it"]), wid in self.sel_ids) for wid in ids if wid in self.cards]

        def work():
            for wid, it, pic, args, sel in jobs:
                if token != self._card_token:
                    return
                try:
                    im = cards.render(it, pic, selected=sel, side=n, ring=ring, **args)
                except Exception:
                    im = None
                self.app.q.put(("ws_card", token, wid, im, side, sel))
        threading.Thread(target=work, daemon=True).start()

    def card_ready(self, token, wid, im, side, sel):
        c = self.cards.get(wid)
        if token != self._card_token or c is None or im is None or side != self._side:
            return
        if sel != (wid in self.sel_ids) or c["st"] != self.status(c["it"])[0]:
            self._redraw_card(wid)               # it changed while being drawn
            return
        c["img"] = ctk_image(im, (side, side))
        c["label"].configure(image=c["img"])

    def _redraw_card(self, wid):
        c = self.cards.get(wid)
        if c is None or not cards.available():
            return
        ring = tuple(int(pick(ACCENT).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        c["st"] = self.status(c["it"])[0]
        im = cards.render(c["it"], self._card_picture(c["it"]), selected=wid in self.sel_ids, side=px(self._side),
                          ring=ring, **self._card_args(c["it"]))
        if im is not None:
            c["img"] = ctk_image(im, (self._side, self._side))
            c["label"].configure(image=c["img"])

    def _schedule_layout(self):
        if self.view != "Panels" or not self.cards:
            return
        if self._layout_job:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(120, self._relayout)

    def _relayout(self):
        self._layout_job = None
        cols, side = self._card_side()
        if cols == self._cols and abs(side - self._side) < 6:
            return
        size_changed = abs(side - self._side) >= 6
        self._cols, self._side = cols, side
        if size_changed:
            ph = self._placeholder(side)
            for c in self.cards.values():
                c["img"] = None
                c["label"].configure(width=side, height=side, image=ph)
            self._draw_cards_async(list(self.cards))
        self._grid_cards()

    def _card_click(self, it, e):
        ids = list(self.cards)
        before = set(self.sel_ids)
        if e.state & 0x4:                                 # Ctrl: add / remove
            if it.id in self.sel_ids:
                self.sel_ids.remove(it.id)
            else:
                self.sel_ids.append(it.id)
        elif e.state & 0x1 and self.sel_ids:              # Shift: a range
            a, b = ids.index(self.sel_ids[-1]), ids.index(it.id)
            lo, hi = min(a, b), max(a, b)
            self.sel_ids = list(dict.fromkeys(self.sel_ids + ids[lo:hi + 1]))
        else:
            self.sel_ids = [it.id]
        for wid in before ^ set(self.sel_ids):
            self._redraw_card(wid)
        self.show_detail()

    def refresh_status(self):
        """Only the 'You' column / card pills: cheap enough to run while downloads report progress."""
        t = self.table.tree
        for rid, it in self.by_row.items():
            st, kind = self.status(it)
            if t.set(rid, "status") != st:
                t.set(rid, "status", st)
                tags = [x for x in t.item(rid, "tags") if x == "odd"]
                if TREE_TAG.get(kind):
                    tags.insert(0, TREE_TAG[kind])
                t.item(rid, tags=tags)
        for wid, c in self.cards.items():
            if c["st"] != self.status(c["it"])[0]:
                self._redraw_card(wid)

    # ---- category chips
    def _build_chips(self, collections):
        for w in self.chip_box.winfo_children():
            w.destroy()
        self.chips = {}
        self._chip_kind = collections
        groups = self.tag_groups.get(self.appid(), [])
        versions = []
        for g, tags in groups:
            for tg in tags:
                if W.VERSION_RX.match(tg) or tg.lower() == "older":
                    versions.append(tg)
                    continue
                b = ctk.CTkButton(self.chip_box, text=tg, height=28, width=10, corner_radius=14, font=font(12),
                                  border_width=1, border_color=BORDER, border_spacing=5,
                                  command=lambda tg=tg: self._cycle(tg))
                self.chips[tg] = b
                self._chip_look(tg)
        self._flow()
        if collections:                  # collections have no version tags: keep the mods' version menu as it is
            return
        gv = self.app.game_version()
        ver_vals = ["Any game version"] + ([f"Fits my version ({gv})"] if gv else []) + \
            sorted((v for v in versions if W.VERSION_RX.match(v)),
                   key=lambda v: [int(x) for x in W.VERSION_RX.match(v).groups()], reverse=True)
        self.version.configure(values=ver_vals)
        cur = self.version.get()
        if cur.startswith("Fits my version") and gv:
            self.version.set(f"Fits my version ({gv})")
        elif cur not in ver_vals:
            self.version.set("Any game version")

    def _chip_look(self, tg):
        s = self.tag_state.get(tg)
        b = self.chips.get(tg)
        if not b:
            return
        if s == "in":
            b.configure(fg_color=INCLUDE, hover_color=INCLUDE, text_color=ACCENT, border_color=ACCENT,
                        text="✓ " + tg)
        elif s == "out":
            b.configure(fg_color=EXCLUDE, hover_color=EXCLUDE, text_color=ERR, border_color=ERR, text="✗ " + tg)
        else:
            b.configure(fg_color=CARD, hover_color=CARD_HI, text_color=TEXT, border_color=BORDER, text=tg)

    def _cycle(self, tg):
        s = self.tag_state.get(tg)
        nxt = {"": "in", None: "in", "in": "out", "out": None}[s]
        if nxt:
            self.tag_state[tg] = nxt
        else:
            self.tag_state.pop(tg, None)
        self._chip_look(tg)
        self.after_idle(self._flow)
        self.run(1)

    def _flow(self):
        """Lay the chips out in rows that fit the width (they wrap when the window gets narrower).
        Measured in real pixels; place() and height take design units (customtkinter scales them)."""
        width = self.chip_box.winfo_width()
        if width < 50:
            return
        gap, row_h = px(7), px(34)
        x = y = 0
        for b in self.chips.values():
            w = b.winfo_reqwidth()
            if x + w > width - px(2) and x > 0:
                x, y = 0, y + row_h
            b.place(x=units(x), y=units(y))
            x += w + gap
        h = int(units(y + row_h)) if self.chips else 4
        if abs(int(self.chip_box.cget("height")) - h) > 1:
            self.chip_box.configure(height=h)

    def clear_filters(self):
        self.tag_state.clear()
        for tg in self.chips:
            self._chip_look(tg)
        self.after_idle(self._flow)
        self.version.set("Any game version")
        self.search.delete(0, "end")
        self.run(1)

    def _hide_changed(self):
        self.app.cfg["ws_hide_installed"] = bool(self.hide_have.get())
        self.app.save()
        self.render()

    # ================================================================ the detail pane
    def selected(self):
        if self.view == "Panels":
            return [self.items[i] for i in self.sel_ids if i in self.items and i in self.cards]
        return [self.by_row[r] for r in self.table.tree.selection() if r in self.by_row]

    def _select_ids(self, ids):
        if self.view == "Panels":
            self.sel_ids = [i for i in ids if i in self.cards]
            for wid in self.sel_ids:
                self._redraw_card(wid)
        else:
            rows = [r for r, it in self.by_row.items() if it.id in ids]
            self.table.tree.selection_set(rows)
        self.show_detail()

    def show_detail(self):
        self.dp.request(self._detail)

    def _detail(self):
        d = self.dp
        sel = self.selected()
        if not sel:
            d.message("Pick a mod to see its pictures, its description, the mods it needs and whether it fits your "
                      "game version.\n\nDouble-click a mod to download it right away. For several, Ctrl/Shift-click "
                      "them and use Add to list; the list sits at the bottom right.")
            return
        d.begin()
        if len(sel) > 1:
            d.accent(ACCENT)
            d.heading(f"{len(sel)} mods selected", "Download them now, or keep them in the catch list for later.")
            d.actions([("Catch them now", lambda: self.app.catch_ids([i.id for i in sel]), "download", "primary"),
                       ("Add to catch list", lambda: self.add_to_list(sel), "plus", "normal")])
            for it in sel[:20]:
                d.text.bullet(it.title)
            d.end()
            return
        it = sel[0]
        gv = self.app.game_version()
        st, kind = self.status(it)
        pic = os.path.join(self.app.thumbs_dir, it.id + ".jpg")
        if icons.available() and os.path.isfile(pic):
            im = icons.load_thumb(pic, 512)
            if im is not None:
                d.picture(icons.rounded(im, 30), key=("ws", it.id, os.path.getmtime(pic)))
        ok = W.fits(it, gv)
        d.accent({"ok": OK, "missing": ERR}.get(kind, INFO if ok is False else ACCENT))
        d.heading(("Collection: " if it.is_collection else "") + it.title, f"by {it.author}" if it.author else "")
        chips = []
        vs = [f"{a}.{b}" for a, b in sorted(it.versions(), reverse=True) if (a, b) != (0, 0)]
        if it.is_collection:
            chips.append((f"{it.children} mods", ACCENT, ACCENT_SOFT, "layers", None))
        elif ok is True:
            chips.append((f"Made for {gv}", OK, OK_SOFT, "check", None))
        elif ok is False:
            chips.append((f"Tagged {vs[0] if vs else 'older'}", INFO, INFO_SOFT, None, None))
        if st:
            col, soft = STATUS_COLOR.get(kind, STATUS_COLOR[""])
            chips.append((st, col, soft, None, None))
        d.chips(chips)
        catch_txt = "Update now" if kind == "update" else ("Catch again" if kind == "ok" else "Catch now")
        acts = [(catch_txt, lambda: self.app.catch_ids([it.id]), "download", "primary", kind != "dl")]
        if it.id in self.app.catch_list:
            acts.append(("Remove from list", lambda: self.remove_from_list([it]), "minus", "normal"))
        else:
            acts.append(("Add to list", lambda: self.add_to_list([it]), "plus", "normal"))
        acts.append(("Steam page", lambda: webbrowser.open(it.url), "external", "normal"))
        m = self.have().get(it.id)
        if m is not None:
            acts.append(("In Library", lambda: self.app.show_in_library(m.key), "library", "normal"))
        det = self.details.get(it.id)
        missing = []
        if det is not None and det.required:
            have = self.have()
            missing = [(rid, n) for rid, n in det.required if rid not in have]
            if missing:
                acts.append((f"Catch it + {len(missing)} it needs", lambda: self.app.catch_ids(
                    [it.id] + [x for x, _ in missing]), "download", "normal"))
        d.actions(acts)
        t = d.text
        rating = (W.stars(it.stars) + f"  {it.votes:,} votes") if it.stars > 0 else (
            f"{it.votes:,} vote{'s' if it.votes != 1 else ''}, not enough for stars yet" if it.votes else "Not rated yet")
        t.p(rating, "bold")
        stats = ([f"{it.subs:,} subscribers"] if it.subs else []) + [f"{it.favs:,} favourites",
                                                                    f"{it.comments:,} comments"]
        t.p("  ·  ".join(stats), "muted")
        bits = [f"Updated {W.ago(it.updated)}", f"published {W.ago(it.created)}"]
        if it.size:
            bits.append(modscan.human_size(it.size))
        t.p("  ·  ".join(bits), "muted", "small")
        if not it.is_collection:
            if ok is True:
                t.p(f"✓ Made for your game version ({gv}).", "ok")
            elif ok is False:
                t.p(f"○ Tagged for {', '.join(vs) or 'older versions'}; you play {gv}. It may be outdated.",
                    "warn")
            else:
                t.p("No game version given by the author." if gv else "Set your game version at the top to check "
                    "this.", "faint")
        cats = it.categories()
        if cats:
            t.h("Categories", small=True)
            t.p("")
            for i, c in enumerate(cats):
                t.link(c, lambda c=c: self.filter_by(c))
                if i < len(cats) - 1:
                    t.add("   ·   ", "faint")
            t.p("Click one to show only mods that have it.", "faint", "small")
        if det is None:
            t.p("Loading details...", "faint")
            d.end()
            self._load_details(it.id)
            return
        if det.required:
            t.h(f"Needs {len(det.required)} other mod{'s' if len(det.required) != 1 else ''}")
            have = self.have()
            for rid, n in det.required:
                t.p("✓  " if rid in have else "✗  ", "ok" if rid in have else "warn", "bold")
                t.link(n, lambda r=rid: webbrowser.open(W.DETAILS.format(id=r)))
            if missing:
                t.p(f"{len(missing)} of them {'is' if len(missing) == 1 else 'are'} missing; "
                    "\"Catch it + ...\" fetches them together.", "faint", "small")
        elif it.children and not it.is_collection:
            t.p(f"Lists {it.children} required item(s).", "faint")
        if det.screenshots and icons.available():
            t.h("Screenshots")
            t.p("")
            s = px(min(104, (d.inner() - 12) / 3))
            for i, url in enumerate(det.screenshots[:6]):
                local = os.path.join(self.app.thumbs_dir, f"{it.id}_s{i}.jpg")
                im = icons.load_thumb(local, s) if os.path.isfile(local) else None
                if im is not None:
                    t.picture(icons.rounded(im, px(8)), command=lambda u=url: webbrowser.open(u))
                else:
                    t.link(f"Picture {i + 1}   ", lambda u=url: webbrowser.open(u))
            t.p("Click a picture to open it full size.", "faint", "small")
        text = W.plain_description(det.description or it.short)
        if text:
            t.h("Description")
            t.p(text)
        d.end()

    def _load_details(self, wid):
        if getattr(self, "_loading_detail", None) == wid:
            return
        self._loading_detail = wid
        folder = self.app.thumbs_dir

        def work():
            import net as N
            net = N.Net()
            d = W.details(net, wid)
            if icons.available():
                want = {f"{wid}_s{i}": url for i, url in enumerate(d.screenshots[:6])
                        if not os.path.isfile(os.path.join(folder, f"{wid}_s{i}.jpg"))}
                if want:
                    icons.fetch_previews(net, want, folder)
            self.app.q.put(("ws_details", wid, d))
        threading.Thread(target=work, daemon=True).start()

    def details_loaded(self, wid, d):
        self.details[wid] = d
        self._loading_detail = None
        sel = self.selected()
        if len(sel) == 1 and sel[0].id == wid:
            self.show_detail()

    # ================================================================ catching
    def catch_selected(self):
        sel = self.selected()
        if sel:
            self.app.catch_ids([i.id for i in sel])

    def add_to_list(self, items):
        for it in items:
            self.app.catch_list[it.id] = it.title
        self._render_list()
        self.refresh_status()
        self.show_detail()

    def remove_from_list(self, items):
        for it in items:
            self.app.catch_list.pop(it.id, None)
        self._render_list()
        self.refresh_status()
        self.show_detail()

    def clear_list(self):
        self.app.catch_list.clear()
        self._render_list()
        self.refresh_status()

    def catch_list(self):
        ids = list(self.app.catch_list)
        if ids:
            self.app.catch_list.clear()
            self._render_list()
            self.app.catch_ids(ids)
            self.refresh_status()

    def _render_list(self):
        n = len(self.app.catch_list)
        self.list_lbl.configure(text=f"Catch list: {n} mod{'s' if n != 1 else ''}" if n else "Catch list is empty",
                                text_color=TEXT if n else MUTED)
        style_button(self.list_btn, "primary" if n else "normal", "download", 14)
        self.list_btn.configure(state="normal" if n else "disabled")

    def restyle(self):
        self.table.restyle()
        self.dp.restyle()
        for tg in self.chips:
            self._chip_look(tg)
        if self.cards:
            self._draw_cards_async(list(self.cards))
