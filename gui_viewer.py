"""A picture viewer inside the app: a mod's screenshots full size, one at a time, with previous / next.

Pictures are downloaded once into .work\\shots (a cache the storage clean-up may empty: they come back
by themselves the next time they're opened)."""
import os
import threading
import webbrowser

import customtkinter as ctk

from gui_common import (ACCENT, WHITE, button, ctk_image, fit_geometry, font, icon, px, units)

try:
    from PIL import Image
except Exception:                       # pragma: no cover
    Image = None

STAGE = ("#0b0e14", "#05070b")          # the dark surround a picture sits on (both themes)
MAX_SIDE = 2400                         # pixels kept on disk per picture


def shot_path(shots_dir, key):
    return os.path.join(shots_dir, key + ".jpg")


def fetch_full(url, dest):
    """Download one picture to dest (shrunk to MAX_SIDE). Returns True when it's there."""
    if os.path.isfile(dest):
        return True
    try:
        import net as N
        r = N.Net().get(url, timeout=40, retries=1)
        if r.status != 200 or not r.content:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(r.content)
        if Image is not None:
            with Image.open(tmp) as im:
                im = im.convert("RGB")
                im.thumbnail((MAX_SIDE, MAX_SIDE))
                im.save(dest, "JPEG", quality=90)
            os.remove(tmp)
        else:
            os.replace(tmp, dest)
        return True
    except Exception:
        return False


class PictureViewer(ctk.CTkToplevel):
    """pictures: [(url, cache key)]. One window is reused: opening another set replaces what it shows."""
    current = None

    @classmethod
    def show(cls, app, title, pictures, index=0):
        if not pictures:
            return
        v = cls.current
        if v is None or not v.winfo_exists():
            v = cls.current = cls(app)
        v.load(title, pictures, index)
        v.deiconify()
        v.lift()
        v.focus_force()

    def __init__(self, app):
        super().__init__(app, fg_color=STAGE)
        self.app = app
        self.title("Pictures")
        fit_geometry(self, 1180, 780, app)
        self.minsize(520, 380)
        try:
            self.transient(app)
        except Exception:
            pass
        self.pictures, self.index, self.name = [], 0, ""
        self._pil, self._img, self._job, self._want = None, None, None, None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 6))
        top.grid_columnconfigure(0, weight=1)
        self.head = ctk.CTkLabel(top, text="", text_color=WHITE, font=font(14, "bold"), anchor="w")
        self.head.grid(row=0, column=0, sticky="w")
        self.count = ctk.CTkLabel(top, text="", text_color=("#aab4c6", "#aab4c6"), font=font(12), anchor="e")
        self.count.grid(row=0, column=1, sticky="e", padx=(8, 12))
        dark = dict(fg_color=("#1b2230", "#1b2230"), hover_color=("#2a3446", "#2a3446"), text_color=WHITE,
                    border_width=0)
        button(top, "Open in browser", self._browser, height=30, icon_name="external", icon_size=13,
               tip="The full picture on Steam", **dark).grid(row=0, column=2, padx=(0, 6))
        b = button(top, "Close", self.destroy, height=30, width=74, icon_name="close", icon_size=12, **dark)
        b.grid(row=0, column=3)
        for w in top.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.configure(image=icon("external" if w.cget("text") == "Open in browser" else "close", 13, WHITE))
        self.prev_b = self._nav(0, "left", lambda: self.step(-1))
        self.next_b = self._nav(2, "right", lambda: self.step(1))
        self.stage = ctk.CTkLabel(self, text="", fg_color="transparent", text_color=("#aab4c6", "#aab4c6"),
                                  font=font(13))
        self.stage.grid(row=1, column=1, sticky="nsew", pady=(0, 6))
        self.strip = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.strip.grid(row=2, column=0, columnspan=3, pady=(0, 12))
        self.dots = []
        self.bind("<Left>", lambda e: self.step(-1))
        self.bind("<Right>", lambda e: self.step(1))
        self.bind("<Escape>", lambda e: self.destroy())
        self.stage.bind("<Configure>", lambda e: self._schedule_fit())
        self.stage.bind("<Button-1>", lambda e: self.step(1))

    def _nav(self, col, name, cmd):
        b = ctk.CTkButton(self, text="", width=46, height=46, corner_radius=23, fg_color=("#1b2230", "#1b2230"),
                          hover_color=("#2a3446", "#2a3446"), image=icon(name, 20, WHITE), command=cmd)
        b.grid(row=1, column=col, padx=12)
        return b

    def load(self, title, pictures, index):
        self.name, self.pictures = title, list(pictures)
        self.index = max(0, min(index, len(self.pictures) - 1))
        for d in self.dots:
            d.destroy()
        self.dots = []
        for i in range(len(self.pictures)):
            d = ctk.CTkButton(self.strip, text="", width=10, height=10, corner_radius=5, border_width=0,
                              fg_color=("#3a4458", "#3a4458"), hover_color=ACCENT,
                              command=lambda i=i: self.go(i))
            d.grid(row=0, column=i, padx=4)
            self.dots.append(d)
        many = len(self.pictures) > 1
        for b in (self.prev_b, self.next_b):
            b.configure(state="normal" if many else "disabled")
        self.go(self.index)

    def step(self, d):
        if self.pictures:
            self.go((self.index + d) % len(self.pictures))

    def go(self, i):
        self.index = i
        url, key = self.pictures[i]
        self.head.configure(text=self.name)
        self.count.configure(text=f"{i + 1} of {len(self.pictures)}")
        for n, d in enumerate(self.dots):
            d.configure(fg_color=ACCENT if n == i else ("#3a4458", "#3a4458"))
        dest = shot_path(self.app.shots_dir, key)
        self._want = dest
        if os.path.isfile(dest):
            self._open(dest)
            return
        self._pil = None
        self.stage.configure(image=None, text="Loading the picture...")

        def work():
            ok = fetch_full(url, dest)
            self._ready = (dest, ok)
        self._ready = None
        threading.Thread(target=work, daemon=True).start()
        self._poll(dest)

    def _poll(self, dest):
        if not self.winfo_exists() or self._want != dest:
            return
        r = self._ready
        if r is None:
            self.after(120, lambda: self._poll(dest))
            return
        if r[1]:
            self._open(dest)
        else:
            self.stage.configure(image=None, text="Couldn't load this picture. \"Open in browser\" shows it on Steam.")
        # the next picture loads in the background, so stepping through feels instant
        if len(self.pictures) > 1:
            nurl, nkey = self.pictures[(self.index + 1) % len(self.pictures)]
            ndest = shot_path(self.app.shots_dir, nkey)
            if not os.path.isfile(ndest):
                threading.Thread(target=fetch_full, args=(nurl, ndest), daemon=True).start()

    def _open(self, path):
        try:
            with Image.open(path) as im:
                self._pil = im.convert("RGB")
        except Exception:
            self._pil = None
            self.stage.configure(image=None, text="Couldn't open this picture.")
            return
        self.stage.configure(text="")
        self._fit()

    def _schedule_fit(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self._fit)

    def _fit(self):
        self._job = None
        if self._pil is None:
            return
        w, h = self.stage.winfo_width() - px(8), self.stage.winfo_height() - px(8)
        if w < 50 or h < 50:
            return
        iw, ih = self._pil.size
        f = min(w / iw, h / ih, 2.0)
        size = (max(1, int(iw * f)), max(1, int(ih * f)))
        im = self._pil.resize(size, Image.LANCZOS)
        self._img = ctk_image(im, (units(size[0]), units(size[1])))
        self.stage.configure(image=self._img)

    def _browser(self):
        if self.pictures:
            webbrowser.open(self.pictures[self.index][0])
