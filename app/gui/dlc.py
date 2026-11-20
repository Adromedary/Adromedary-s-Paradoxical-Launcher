"""The DLC tab: every DLC installed with the game as a card (its picture, name and kind) with an on/off
switch, like the official launcher. Off DLC go into dlc_load.json "disabled_dlcs", the switch the official
launcher uses, and are written again every time the game is started from here."""
import webbrowser

import customtkinter as ctk

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageOps
except Exception:                       # pragma: no cover
    Image = None

from app.core import dlcs as D
from app.core import launcher as LA
from app.gui.common import (ACCENT, ACCENT_SOFT, BORDER, CARD, CARD_HI, INFO, INFO_SOFT, MUTED, MUTED_SOFT, OK, OK_SOFT,
                            TEAL_SOFT, TEXT, WARN, WARN_SOFT, Tooltip, button, clearable, ctk_image, font, pill,
                            units)

PIC_W, PIC_H = 224, 128                  # design units (the game's thumbnails are 280 x 160)
CARD_W = 248
FILTERS = ["All", "Expansions", "Packs", "Off"]
KIND_COLOR = {"Expansion": (ACCENT, ACCENT_SOFT), "Core expansion": (INFO, INFO_SOFT),
              "Flavour pack": (OK, OK_SOFT), "Event pack": (WARN, WARN_SOFT), "Music pack": (OK, TEAL_SOFT)}


def _picture(d, on, scale, dark=False):
    """The DLC's picture (greyed when it's off), or a plain tile with a box when it has none (darker in
    the dark theme)."""
    if Image is None:
        return None
    w, h = int(PIC_W * scale), int(PIC_H * scale)
    img = None
    if d.thumb:
        try:
            img = Image.open(d.thumb).convert("RGB")
            img = ImageOps.fit(img, (w, h), Image.LANCZOS)
        except Exception:
            img = None
    if img is None:
        from app.gui import glyphs
        img = Image.new("RGB", (w, h), (46, 52, 64) if dark else (226, 230, 238))
        g = glyphs.draw("dlc", int(h * 0.45), "#7b8597" if dark else "#8a94a6")
        img.paste(g, ((w - g.width) // 2, (h - g.height) // 2), g)
    if not on:
        img = ImageEnhance.Brightness(ImageOps.grayscale(img).convert("RGB")).enhance(0.75)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=int(9 * scale), fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


class DlcPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.items = []                  # dlcs.Dlc of the current game
        self.cards = {}                  # key -> (frame, picture label, switch)
        self._imgs = {}
        self._cols = 0
        self._shown_keys = []
        self._resize_after = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(3, weight=1)
        self.count = ctk.CTkLabel(head, text="", text_color=TEXT, font=font(15, "bold"), anchor="w")
        self.count.grid(row=0, column=0, sticky="w", padx=(2, 14))
        self.filter = ctk.CTkSegmentedButton(head, values=FILTERS, command=lambda v: self.render(), height=32,
                                             font=font(12), selected_color=ACCENT, selected_hover_color=ACCENT,
                                             unselected_color=CARD, unselected_hover_color=CARD_HI,
                                             fg_color=CARD, text_color=TEXT)
        self.filter.set("All")
        self.filter.grid(row=0, column=1, sticky="w")
        self.search = ctk.CTkEntry(head, placeholder_text="Search DLC", width=200, height=32, corner_radius=9,
                                   fg_color=CARD, border_color=BORDER, text_color=TEXT, font=font(12))
        self.search.grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.search.bind("<KeyRelease>", lambda e: self.render(), add="+")
        clearable(self.search, self.render)
        tools = ctk.CTkFrame(head, fg_color="transparent")
        tools.grid(row=0, column=4, sticky="e")
        self.all_on = button(tools, "Turn all on", lambda: self.set_all(True), icon_name="check", width=120,
                             height=32, tip="Every installed DLC loads")
        self.all_on.pack(side="left", padx=(0, 6))
        self.all_off = button(tools, "Turn all off", lambda: self.set_all(False), icon_name="power", width=124,
                              height=32, tip="The game starts without any DLC (handy to test a mod or a crash)")
        self.all_off.pack(side="left", padx=(0, 6))
        self.store_btn = button(tools, "Store", self.open_store, icon_name="external", width=90, height=32,
                                tip="The game's DLC page in the store")
        self.store_btn.pack(side="left", padx=(0, 6))
        button(tools, "", self.reload, icon_name="refresh", width=34, height=32,
               tip="Look again (after installing or updating the game)").pack(side="left")

        self.note = ctk.CTkLabel(self, text="", text_color=MUTED, font=font(11), anchor="w", justify="left",
                                 wraplength=900)
        self.note.grid(row=1, column=0, sticky="ew", pady=(8, 8), padx=2)
        self.grid_box = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12, border_width=1,
                                               border_color=BORDER)
        self.grid_box.grid(row=2, column=0, sticky="nsew")
        self.empty = ctk.CTkLabel(self.grid_box, text="", text_color=MUTED, font=font(13), justify="center",
                                  wraplength=600)
        self.bind("<Configure>", self._resized, add="+")
        self._loaded_for = None

    # ---------------------------------------------------------------- data
    def on_show(self):
        key = (self.app.game(), self.app.game_install())
        if key != self._loaded_for:
            self.reload()

    def reload(self):
        game, inst = self.app.game(), self.app.game_install()
        self._loaded_for = (game, inst)
        self.items = D.installed(inst) if inst else []
        for fr, _l, _s in self.cards.values():
            fr.destroy()
        self.cards, self._imgs, self._shown_keys = {}, {}, []
        self.render()

    def off(self):
        return set(self.app.dlc_off())

    def set_on(self, d, on):
        off = self.off()
        if on:
            off.discard(d.key)
        else:
            off.add(d.key)
        self.app.set_dlc_off(sorted(off))
        self._update_card(d)
        self._summary()

    def set_all(self, on):
        if not self.items:
            return
        self.app.set_dlc_off([] if on else sorted(d.key for d in self.items))
        for d in self.items:
            self._update_card(d)
        self.render()

    def open_store(self):
        inst = self.app.game_install()
        url = LA.read_launcher_settings(inst).get("browserDlcUrl", "") if inst else ""
        if not url:
            appid = LA.game_info(self.app.game()).get("appid", "")
            url = f"https://store.steampowered.com/dlc/{appid}/" if appid else ""
        if url:
            webbrowser.open(url)

    # ---------------------------------------------------------------- drawing
    def _summary(self):
        off = self.off()
        n = len(self.items)
        on = sum(1 for d in self.items if d.key not in off)
        self.count.configure(text=f"{n} DLC installed  ·  {on} on" if n else "DLC")
        self.app.tabs.set_badge("DLC", (n - on) or "", WARN)

    def _visible(self):
        f = self.filter.get()
        q = self.search.get().strip().lower()
        off = self.off()
        out = []
        for d in self.items:
            if f == "Expansions" and d.size == "minor":
                continue
            if f == "Packs" and d.size != "minor":
                continue
            if f == "Off" and d.key not in off:
                continue
            if q and q not in d.name.lower() and q not in d.kind.lower():
                continue
            out.append(d)
        return out

    def render(self):
        game, inst = self.app.game(), self.app.game_install()
        supported = D.supported(game)
        if not game:
            self.note.configure(text="Pick your game at the top.")
        elif not inst:
            self.note.configure(text="The game's folder isn't known: set it in Settings > Games, then press the "
                                     "refresh button here.")
        elif not supported:
            self.note.configure(text=f"Turning DLC off isn't supported for {game} here yet (it uses a different "
                                     "load file): use the official launcher for that. The list shows what's "
                                     "installed.")
        else:
            self.note.configure(text="Off DLC are skipped by the game. The choice goes into dlc_load.json, the "
                                     "switch the official launcher uses too, and is written again every time you "
                                     "press Play. It shows what's installed: owning a DLC is up to your store.")
        for w in (self.all_on, self.all_off):
            w.configure(state="normal" if supported and self.items else "disabled")
        self._summary()
        vis = self._visible()
        cols = self._columns()
        keys = [d.key for d in vis]
        if keys == self._shown_keys and cols == self._cols:
            return
        self._shown_keys, self._cols = keys, cols
        for fr, _l, _s in self.cards.values():
            fr.grid_forget()
        if not vis:
            self.empty.configure(text="No DLC found for this game's folder." if not self.items else
                                 "No DLC matches.")
            self.empty.grid(row=0, column=0, padx=30, pady=40)
            return
        self.empty.grid_forget()
        for c in range(max(cols, 8)):
            self.grid_box.grid_columnconfigure(c, weight=1 if c < cols else 0, uniform="dlc" if c < cols else "")
        for i, d in enumerate(vis):
            fr = self.cards.get(d.key, (None,))[0] or self._make_card(d)
            fr.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="n")

    def _columns(self):
        try:
            w = units(self.winfo_width()) - 40          # the page, less the list's border and scrollbar
        except Exception:
            w = 0
        if w < 100:
            w = 1100
        return max(1, int(w // (CARD_W + 20)))

    def _resized(self, e=None):
        if self._resize_after:
            try:
                self.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.after(150, self._relayout)

    def _relayout(self):
        self._resize_after = None
        if self._columns() != self._cols:
            self.render()

    def _image(self, d, on):
        k = (d.key, on)
        if k not in self._imgs:
            pil = _picture(d, on, 2)
            if pil is None:
                self._imgs[k] = None
            elif d.thumb:
                self._imgs[k] = ctk_image(pil, (PIC_W, PIC_H))
            else:                                   # the plain tile follows the theme
                self._imgs[k] = ctk.CTkImage(light_image=pil, dark_image=_picture(d, on, 2, dark=True),
                                             size=(PIC_W, PIC_H))
        return self._imgs[k]

    def _make_card(self, d):
        supported = D.supported(self.app.game())
        on = d.key not in self.off()
        fr = ctk.CTkFrame(self.grid_box, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER,
                          width=CARD_W)
        pic = ctk.CTkLabel(fr, text="", image=self._image(d, on), width=PIC_W, height=PIC_H)
        pic.pack(padx=12, pady=(12, 8))
        name = ctk.CTkLabel(fr, text=d.name, text_color=TEXT, font=font(13, "bold"), anchor="w", justify="left",
                            wraplength=PIC_W, width=PIC_W)
        name.pack(padx=12, anchor="w")
        row = ctk.CTkFrame(fr, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(6, 12))
        col, soft = KIND_COLOR.get(d.kind, (MUTED, MUTED_SOFT))
        pill(row, d.kind, col, soft).pack(side="left")
        sw = ctk.CTkSwitch(row, text="On" if on else "Off", width=40, font=font(12, "bold"), progress_color=OK,
                           text_color=TEXT, command=lambda: self.set_on(d, bool(self.cards[d.key][2].get())))
        if on:
            sw.select()
        else:
            sw.deselect()
        if not supported:
            sw.configure(state="disabled")
        sw.pack(side="right")
        Tooltip(pic, f"{d.name}\n{d.kind}" + (f"  ·  Steam {d.steam_id}" if d.steam_id else "") +
                f"\n{d.key}")
        for w in (fr, pic, name):
            w.bind("<Double-Button-1>", lambda e, d=d: self._open(d), add="+")
        self.cards[d.key] = (fr, pic, sw)
        return fr

    def _open(self, d):
        url = D.store_url(self.app.game(), d)
        if url:
            webbrowser.open(url)

    def _update_card(self, d):
        hit = self.cards.get(d.key)
        if not hit:
            return
        fr, pic, sw = hit
        on = d.key not in self.off()
        pic.configure(image=self._image(d, on))
        sw.configure(text="On" if on else "Off")
        if on:
            sw.select()
        else:
            sw.deselect()
        fr.configure(border_color=BORDER if on else (MUTED_SOFT[0], MUTED_SOFT[1]))
